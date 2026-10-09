# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""pipeline_remix.media — subprocess/ffprobe helpers, the transcript and the audio analysis.

Lines 251-437 of the original pipeline_remix.py, moved verbatim
(2026-10-06 split). No logic changed.
"""

from __future__ import annotations

import json
import logging as _zyg_logging
import math
import re
import subprocess

from zyg_workflows.bin import exe

from .jobs import _log

# Bound by assignment (never `from . import`), to __package__ — which IS the
# old module's own __name__, whichever route it is imported by. The logger a
# moved line writes to must not be renamed by the move.
_zyg_log = _zyg_logging.getLogger(__package__)


# ── subprocess / ffprobe helpers ─────────────────────────────────────────────


def _run(cmd, timeout=600):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.returncode, r.stdout or '', r.stderr or ''
    except subprocess.TimeoutExpired:
        return -1, '', f'timeout after {timeout}s'
    except Exception as e:
        return -1, '', str(e)


def _ffprobe(path, ignore_editlist=False):
    cmd = [exe('ffprobe'), '-v', 'error']
    if ignore_editlist:
        cmd += ['-ignore_editlist', '1']
    cmd += ['-print_format', 'json', '-show_streams', '-show_format', path]
    rc, out, _err = _run(cmd, timeout=60)
    if rc != 0:
        return {}
    try:
        return json.loads(out)
    except Exception:
        return {}


def _duration(path) -> float:
    info = _ffprobe(path)
    try:
        return float((info.get('format') or {}).get('duration') or 0)
    except (TypeError, ValueError):
        return 0.0


def _enc_timeout(dur_s: float) -> int:
    return max(180, int(dur_s * 8) + 60)


# ── transcript ───────────────────────────────────────────────────────────────


def _fetch_captions(video_id: str):
    """YouTube auto-captions: zero GPU. No punctuation / no words — snapping degrades."""
    try:
        from youtube_transcript_api import YouTubeTranscriptApi

        api = YouTubeTranscriptApi()
        tx = api.fetch(video_id, languages=['en'])
        return [
            {
                'start': float(s.start),
                'end': float(s.start) + float(s.duration),
                'text': (s.text or '').strip(),
                'words': None,
            }
            for s in tx.snippets
            if (s.text or '').strip()
        ]
    except Exception:
        return None


def _gpu_clear(min_free_gb: float) -> bool:
    """Fail-closed GPU gate (vlm_inspector pattern): never squeeze a render."""
    try:
        from zyg_workflows import comfy_offload as CO

        if CO.comfy_is_sampling():
            return False
        free = CO.gpu_free_gb()
        return free is None or free >= min_free_gb
    except Exception:
        return False


def _whisper_transcribe(pid, media_path):
    if not _gpu_clear(6.0):
        _log(pid, 'WARNING', 'Transcribe', 'GPU busy — skipping local ASR (captions only)')
        return None
    try:
        import zyg_whisper as _zw

        segs, _info = _zw.transcribe_segments(media_path, language='en', want_words=True, vad=True)
        try:
            _zw.unload_models()
        except Exception as _exc:
            _zyg_log.debug('whisper model unload skipped: %s', _exc)
        return [
            {
                'start': float(s['start']),
                'end': float(s['end']),
                'text': (s.get('text') or '').strip(),
                'words': s.get('words'),
            }
            for s in segs
            if (s.get('text') or '').strip()
        ]
    except Exception as e:
        _log(pid, 'WARNING', 'Transcribe', f'whisper failed: {e}')
        return None


def _punct_density(segments) -> float:
    words = sum(len((s['text'] or '').split()) for s in segments)
    punct = sum((s['text'] or '').count(c) for s in segments for c in '.?!')
    return (punct / max(words, 1)) * 100.0


def _get_transcript(pid, video_id, media_path):
    """Captions for content, local ASR (word-level) when the GPU is free —
    captions have no punctuation, which silently no-ops boundary snapping."""
    caps = _fetch_captions(video_id)
    segs = _whisper_transcribe(pid, media_path)
    if segs:
        return segs, 'whisper'
    if caps:
        _log(
            pid,
            'WARNING',
            'Transcribe',
            f'captions-only transcript (punct density {_punct_density(caps):.1f}/100w) '
            '— boundary snapping degraded to silence detection',
        )
        return caps, 'captions'
    return None, 'none'


# ── audio analysis ───────────────────────────────────────────────────────────

_SIL_RE = re.compile(r'silence_(start|end): ([\d.]+)')


def _silences(path, extra_af='') -> list:
    """[(start,end)] silence intervals via silencedetect (-30dB / 0.35s)."""
    cmd = [
        exe('ffmpeg'),
        '-hide_banner',
        '-nostats',
        '-i',
        path,
        '-af',
        (extra_af + ',' if extra_af else '') + 'silencedetect=noise=-30dB:d=0.35',
        '-vn',
        '-f',
        'null',
        '-',
    ]
    _rc, _out, err = _run(cmd, timeout=max(300, int(_duration(path) * 0.6) + 60))
    out, start = [], None
    for kind, val in _SIL_RE.findall(err):
        if kind == 'start':
            start = float(val)
        elif start is not None:
            out.append((start, float(val)))
            start = None
    return out


def _rms_curve(path, dur) -> list:
    """1 Hz normalized RMS curve (bp_claude_clip astats idiom, 0.5 s frames)."""
    cmd = [
        exe('ffmpeg'),
        '-hide_banner',
        '-nostats',
        '-i',
        path,
        '-map',
        'a:0',
        '-af',
        'aresample=48000,asetnsamples=n=24000,astats=metadata=1:reset=1,'
        'ametadata=print:key=lavfi.astats.Overall.RMS_level:file=-',
        '-f',
        'null',
        '-',
    ]
    _rc, out, _err = _run(cmd, timeout=max(300, int(dur * 0.6) + 60))
    vals = [float(m) for m in re.findall(r'RMS_level=(-?[\d.]+)', out)]
    n = int(math.ceil(dur))
    curve = [0.0] * n
    for i in range(n):
        pair = vals[i * 2 : i * 2 + 2]
        if pair:
            curve[i] = max(0.0, min(1.0, (max(pair) + 60.0) / 60.0))
    return curve
