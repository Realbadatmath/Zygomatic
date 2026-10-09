# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""
Fail-safe bridge from the crews pipeline to the isolated Sortformer diarizer.

Runs the NeMo worker (in models/diarization/.venv) as a subprocess so NeMo's
torch never touches the production venv. EVERY failure mode — feature disabled,
venv missing, NeMo error, timeout, OOM — returns None, and the caller simply
keeps an unlabelled transcript. Diarization must never break transcription.

Env knobs:
  ZYG_DIARIZATION      "0" disables entirely (default: enabled)
  ZYG_DIAR_HOME        override path to models/diarization
  ZYG_DIAR_TIMEOUT     subprocess timeout seconds (default: 3600)
  ZYG_SORTFORMER_MODEL / ZYG_DIAR_WINDOW_SEC / ZYG_DIAR_OVERLAP_SEC → worker
"""

import json
import os
import subprocess
import sys
import tempfile
import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)


_DIR = os.path.dirname(os.path.abspath(__file__))
_DIAR_HOME = os.environ.get('ZYG_DIAR_HOME') or os.path.abspath(os.path.join(_DIR, '..', '..', 'models', 'diarization'))
_DIAR_PY = os.path.join(_DIAR_HOME, '.venv', 'bin', 'python')
_DIAR_WORKER = os.path.join(_DIAR_HOME, 'diarize_worker.py')
_ENV_FILE = os.path.abspath(os.path.join(_DIR, '..', '..', '.env'))


def _warn(msg):
    _zyg_log.warning(f'[diarize_sortformer] {msg}')


def _hf_token():
    tok = os.environ.get('HF_TOKEN') or os.environ.get('HUGGING_FACE_HUB_TOKEN')
    if tok:
        return tok
    try:
        with open(_ENV_FILE) as f:
            for line in f:
                line = line.strip()
                if line.startswith('HF_TOKEN=') or line.startswith('HUGGING_FACE_HUB_TOKEN='):
                    return line.split('=', 1)[1].strip().strip('"').strip("'")
    except OSError as _exc:
        _zyg_log.debug('hf token env file unreadable: %s', _exc)
    return None


def available():
    """True if diarization is enabled and the isolated worker is installed."""
    if os.environ.get('ZYG_DIARIZATION', '1') != '1':
        return False
    return os.path.exists(_DIAR_PY) and os.path.exists(_DIAR_WORKER)


def diarize(media_path, timeout=None):
    """Return [{'start','end','speaker'}, ...] for the media, or None on any
    failure / when disabled. `media_path` may be audio or video."""
    if os.environ.get('ZYG_DIARIZATION', '1') != '1':
        return None
    if not (os.path.exists(_DIAR_PY) and os.path.exists(_DIAR_WORKER)):
        _warn(f'worker unavailable ({_DIAR_HOME}) — skipping diarization')
        return None
    if not os.path.exists(media_path):
        _warn(f'media not found: {media_path}')
        return None
    timeout = timeout or int(os.environ.get('ZYG_DIAR_TIMEOUT', '3600'))

    env = dict(os.environ)
    tok = _hf_token()
    if tok:
        env['HF_TOKEN'] = tok
        env['HUGGING_FACE_HUB_TOKEN'] = tok

    fd, out_json = tempfile.mkstemp(suffix='.json', prefix='diar_')
    os.close(fd)
    try:
        subprocess.run(
            [_DIAR_PY, _DIAR_WORKER, '--audio', os.path.abspath(media_path), '--out', out_json],
            check=True,
            timeout=timeout,
            capture_output=True,
            env=env,
        )
        with open(out_json) as f:
            data = json.load(f)
        segs = data.get('segments') or None
        return segs
    except subprocess.TimeoutExpired:
        _warn(f'diarization timed out after {timeout}s')
        return None
    except subprocess.CalledProcessError as e:
        tail = (e.stderr or b'')[-600:]
        if isinstance(tail, bytes):
            tail = tail.decode('utf-8', 'replace')
        _warn(f'worker failed (rc={e.returncode}): {tail}')
        return None
    except Exception as e:  # noqa: BLE001 — fail-safe by design
        _warn(f'unexpected error: {e}')
        return None
    finally:
        try:
            os.unlink(out_json)
        except OSError as _exc:
            _zyg_log.debug('diarization temp json cleanup skipped: %s', _exc)


def assign_speakers(num_segments, diar_segments):
    """Map transcript segment index → speaker label.

    num_segments : [(start_f, end_f, text), ...] (numeric seconds)
    diar_segments: [{'start','end','speaker'}, ...]
    Each transcript segment gets the speaker it overlaps most; if it overlaps
    none (e.g. a gap), it gets the nearest turn by midpoint.
    """
    ds = [(float(d['start']), float(d['end']), d['speaker']) for d in diar_segments]
    out = {}
    if not ds:
        return out
    for i, seg in enumerate(num_segments):
        s, e = float(seg[0]), float(seg[1])
        best_spk, best_ov = None, 0.0
        for a, b, spk in ds:
            ov = min(e, b) - max(s, a)
            if ov > best_ov:
                best_ov, best_spk = ov, spk
        if best_spk is None:  # no overlap → nearest by midpoint
            mid = (s + e) / 2.0
            best_dist = None
            for a, b, spk in ds:
                dist = 0.0 if a <= mid <= b else min(abs(mid - a), abs(mid - b))
                if best_dist is None or dist < best_dist:
                    best_dist, best_spk = dist, spk
        if best_spk is not None:
            out[i] = best_spk
    return out


if __name__ == '__main__':
    # Manual test: python diarize_sortformer.py <media>
    import pprint

    segs = diarize(sys.argv[1]) if len(sys.argv) > 1 else None
    pprint.pprint(segs[:20] if segs else segs)
