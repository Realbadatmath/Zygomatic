# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""sam3_service.py — crews-side bridge to the SAM 3 concept-segmentation worker.

SAM 3 (facebook/sam3, SAM License — commercial, no outputs-train clause; pinned
2026-08-09) does text-prompted detect + segment + track in one 848M model. This
service is the foundation for the prop-persistence gate the VACE QC has wanted,
asserting "the <prop> persists across frames" by phrase instead of chaining
GroundingDINO→SAM2. Same fail-safe subprocess pattern as diarize_sortformer /
_identity_embed_worker: every failure mode returns None and the caller degrades.

Usage:
    from zyg_workflows import sam3_service
    res = sam3_service.segment('/abs/frame.png', ['leather-bound ledger', 'clay pipe'])
    # → {'leather-bound ledger': {'instances': [...], 'count': 1}, ...} or None
"""

from __future__ import annotations
import json
import os
import subprocess
import tempfile
from zyg_workflows import paths
import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)


_SAM3_HOME = paths.ZYG_SAM3_HOME
_WORKER = os.path.join(_SAM3_HOME, 'sam3_worker.py')
# vlm_judge venv carries transformers >= 5.14 (Sam3* classes) + CUDA torch
_WORKER_PYTHON = paths.ZYG_SAM3_PYTHON
_TIMEOUT_S = float(os.environ.get('ZYG_SAM3_TIMEOUT_S', '300'))


def available() -> tuple[bool, str]:
    if not os.path.isfile(_WORKER):
        return False, f'worker missing: {_WORKER}'
    if not os.path.isfile(_WORKER_PYTHON):
        return False, f'worker python missing: {_WORKER_PYTHON}'
    wdir = os.path.join(_SAM3_HOME, 'weights')
    if not os.path.isfile(os.path.join(wdir, 'model.safetensors')):
        return False, f'weights missing under {wdir}'
    return True, 'ok'


def segment(
    image_path: str,
    phrases: list[str],
    *,
    threshold: float = 0.5,
    save_masks_dir: str | None = None,
    log_fn=None,
) -> dict | None:
    """Phrase-prompted instance segmentation on one image. None on any failure."""
    log = log_fn or (lambda _m: None)
    ok, why = available()
    if not ok:
        log(f'SAM3: unavailable — {why}')
        return None
    if not os.path.isfile(image_path):
        log(f'SAM3: image missing — {image_path}')
        return None
    req = {
        'image': image_path,
        'phrases': list(phrases),
        'threshold': float(threshold),
        'save_masks_dir': save_masks_dir,
    }
    return _run_worker(req, log)


def segment_batch(
    image_paths: list[str],
    phrases: list[str],
    *,
    threshold: float = 0.5,
    log_fn=None,
) -> dict | None:
    """Segment many images in ONE worker invocation (single model load).
    Returns {path: {phrase: {'instances': [...], 'count': int}}} or None."""
    log = log_fn or (lambda _m: None)
    ok, why = available()
    if not ok:
        log(f'SAM3: unavailable — {why}')
        return None
    paths = [p for p in image_paths if os.path.isfile(p)]
    if not paths:
        log('SAM3: no readable images')
        return None
    req = {'images': paths, 'phrases': list(phrases), 'threshold': float(threshold), 'save_masks_dir': None}
    return _run_worker(req, log)


def prop_persistence(
    video_path: str,
    phrases: list[str],
    *,
    n_frames: int = 8,
    threshold: float = 0.5,
    min_frac: float = 0.75,
    log_fn=None,
) -> dict | None:
    """Prop-persistence measurement: does each phrase-named prop appear across
    the clip? Samples ``n_frames`` evenly, segments each in one worker call,
    and reports per-phrase presence.

    Returns {phrase: {'present_frames': int, 'total_frames': int,
                      'presence_frac': float, 'mean_score': float,
                      'persistent': bool}} plus '_frames' with the sampled
    timestamps — or None on any failure (caller degrades; ADVISORY by design,
    same warn-first pattern as every new gate in this codebase).
    """
    log = log_fn or (lambda _m: None)
    if not os.path.isfile(video_path):
        log(f'SAM3: clip missing — {video_path}')
        return None
    import tempfile as _tf

    tmpdir = _tf.mkdtemp(prefix='sam3_pp_')
    frames: list[str] = []
    try:
        # even sampling via ffmpeg: duration probe then N timestamps
        probe = subprocess.run(
            [
                'ffprobe',
                '-v',
                'error',
                '-select_streams',
                'v',
                '-show_entries',
                'format=duration',
                '-of',
                'csv=p=0',
                video_path,
            ],
            capture_output=True,
            timeout=30,
        )
        dur = float(probe.stdout.decode().strip() or 0)
        if dur <= 0:
            log('SAM3: could not probe clip duration')
            return None
        stamps = [dur * (i + 0.5) / n_frames for i in range(n_frames)]
        for i, ts in enumerate(stamps):
            fp = os.path.join(tmpdir, f'f{i:03d}.png')
            subprocess.run(
                [
                    'ffmpeg',
                    '-y',
                    '-hide_banner',
                    '-loglevel',
                    'error',
                    '-ss',
                    f'{ts:.3f}',
                    '-i',
                    video_path,
                    '-frames:v',
                    '1',
                    fp,
                ],
                capture_output=True,
                timeout=60,
            )
            if os.path.isfile(fp):
                frames.append(fp)
        if len(frames) < max(2, n_frames // 2):
            log(f'SAM3: only {len(frames)} frames extracted')
            return None
        seg = segment_batch(frames, phrases, threshold=threshold, log_fn=log_fn)
        if seg is None:
            return None
        report: dict = {'_frames': {'count': len(frames), 'stamps': [round(s, 2) for s in stamps]}}
        for phrase in phrases:
            hits = []
            for f in frames:
                inst = (seg.get(f, {}).get(phrase) or {}).get('instances') or []
                if inst:
                    hits.append(max(i['score'] for i in inst))
            frac = len(hits) / len(frames)
            report[phrase] = {
                'present_frames': len(hits),
                'total_frames': len(frames),
                'presence_frac': round(frac, 3),
                'mean_score': round(sum(hits) / len(hits), 3) if hits else 0.0,
                'persistent': frac >= min_frac,
            }
        return report
    except Exception as exc:
        log(f'SAM3: prop_persistence — {exc}')
        return None
    finally:
        for f in frames:
            try:
                os.remove(f)
            except OSError as _exc:
                _zyg_log.debug('temp file %s cleanup skipped: %s', f, _exc)
        try:
            os.rmdir(tmpdir)
        except OSError as _exc:
            _zyg_log.debug('temp dir %s cleanup skipped: %s', tmpdir, _exc)


def _run_worker(req: dict, log) -> dict | None:
    in_f = out_f = None
    try:
        with tempfile.NamedTemporaryFile('w', suffix='.json', delete=False) as fh:
            json.dump(req, fh)
            in_f = fh.name
        out_f = in_f + '.out'
        r = subprocess.run(
            [_WORKER_PYTHON, _WORKER, '--in', in_f, '--out', out_f],
            capture_output=True,
            timeout=_TIMEOUT_S,
        )
        if r.returncode != 0:
            log(f'SAM3: worker rc={r.returncode} — {r.stderr.decode()[-300:]}')
            return None
        with open(out_f, encoding='utf-8') as fh:
            return json.load(fh)
    except Exception as exc:
        log(f'SAM3: {exc}')
        return None
    finally:
        for p in (in_f, out_f):
            if p and os.path.exists(p):
                try:
                    os.remove(p)
                except OSError as _exc:
                    _zyg_log.debug('temp file %s cleanup skipped: %s', p, _exc)
