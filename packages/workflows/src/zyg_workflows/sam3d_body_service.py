# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""sam3d_body_service.py — crews-side bridge to the SAM 3D Body (MHR) worker (2026-09-02).

Same fail-safe subprocess contract as sam3_service / diarize_sortformer /
_identity_embed_worker: the worker's torch stack (py3.11, torch 2.13 cu126, in
$ZYG_MODELS_DIR/sam3/body_venv) never touches the production venv, every
failure mode returns None, and the caller degrades to whatever it did before.

WHY A BATCH-FIRST API. The worker pays ~34 s to load the checkpoint and ~0.7-1.1 s
per frame after that (measured 2026-09-02, receipt in the S08 notes). Calling it
per frame would cost 34 s x N. `fit_batch` therefore takes the whole clip's frames
in ONE invocation and is the only entry point a track should use; `fit_one` exists
for the single-cell fit path and is a thin wrapper over it.

BOXES AND MASKS. The worker used to run whole-image single-person, which silently
picks one person in a two-hander and offers no way to say which. `fit_batch` passes
per-frame boxes (and optionally masks) straight through to
`SAM3DBodyEstimator.process_one_image`, so a caller that has a SAM 3 track can fit
the subject it actually means.

BIG ARRAYS. With `arrays_dir` set, per-frame vertices (18439x3), joint coords
(127x3), joint global rotations (127x3x3) and the mask are written as .npy/.png and
the returned JSON carries their paths — a 112-frame clip's vertices are ~25 MB and
have no business inside a JSON document.

LICENCE. Weights: facebook/sam-3d-body-dinov3 under the SAM License (commercial,
worldwide, no outputs-train clause; pinned 2026-08-09). The MHR rig itself is
Apache-2.0. smplx is present in that venv as a SAM 3D Body dependency and is never
called from here.

Usage:
    from zyg_workflows import sam3d_body_service as S3B
    res = S3B.fit_batch(frames, bboxes={f: [x0,y0,x1,y1]}, arrays_dir='/abs/arrays')
    # → {"/abs/f_00000.png": {...}, ..., "_meta": {...}} or None
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
_WORKER = os.path.join(_SAM3_HOME, 'sam3d_body_worker.py')
_WORKER_PYTHON = os.environ.get('ZYG_SAM3DB_PYTHON', os.path.join(_SAM3_HOME, 'body_venv', 'bin', 'python'))
# model load is ~35 s and each frame ~1 s; the floor covers the load, the per-frame
# term covers the clip. A 341-frame shot gets ~12 min, not the 5 min sam3_service uses.
_LOAD_S = float(os.environ.get('ZYG_SAM3DB_LOAD_S', '240'))
_PER_FRAME_S = float(os.environ.get('ZYG_SAM3DB_PER_FRAME_S', '6'))

# GPU lock shared by every render on this box (README rule 5 of the 2026-09-02 plan).
# Set ZYG_SAM3DB_NO_LOCK=1 only when the caller already holds it.
_LOCK = paths.ZYG_GPU_LOCK


def available() -> tuple[bool, str]:
    if not os.path.isfile(_WORKER):
        return False, f'worker missing: {_WORKER}'
    if not os.path.isfile(_WORKER_PYTHON):
        return False, f'worker python missing: {_WORKER_PYTHON}'
    ckpt = os.path.join(_SAM3_HOME, 'sam3d_body_weights', 'model.ckpt')
    if not os.path.isfile(ckpt):
        return False, f'weights missing: {ckpt}'
    mhr = os.path.join(_SAM3_HOME, 'sam3d_body_weights', 'assets', 'mhr_model.pt')
    if not os.path.isfile(mhr):
        return False, f'mhr assets missing: {mhr}'
    return True, 'ok'


def mhr_decode_available() -> tuple[bool, str]:
    """Is the standalone MHR forward model importable in the worker venv?

    Measured 2026-09-02: `pip install mhr` succeeds (Apache-2.0, 15 KB of pure
    python) but `mhr.mhr.MHR` imports `pymomentum`, which Meta ships through conda
    only — the PyPI name `pymomentum` is an unrelated SMS library by another author
    and must NOT be installed. So the answer here is False on this box, and every
    caller that wants a posed body uses the estimator's own `pred_vertices` instead
    of re-posing the rig. Stated rather than assumed because a silent fallback here
    would look exactly like a working decode.
    """
    if not os.path.isfile(_WORKER_PYTHON):
        return False, 'worker python missing'
    try:
        r = subprocess.run([_WORKER_PYTHON, '-c', 'from mhr.mhr import MHR'], capture_output=True, timeout=120)
    except Exception as exc:  # noqa: BLE001
        return False, f'{exc}'
    if r.returncode == 0:
        return True, 'mhr.mhr.MHR importable'
    return False, r.stderr.decode()[-200:].strip()


def fit_batch(
    image_paths: list[str],
    *,
    bboxes: dict | None = None,
    masks: dict | None = None,
    arrays_dir: str | None = None,
    inference_type: str = 'full',
    use_gpu_lock: bool = True,
    log_fn=None,
) -> dict | None:
    """Fit every frame in ONE worker invocation. None on any failure.

    bboxes / masks: {image_path: [x0,y0,x1,y1]} and {image_path: '/abs/mask.png'}.
    A mask without a box is ignored by the worker (the estimator requires the box).
    """
    log = log_fn or (lambda _m: None)
    ok, why = available()
    if not ok:
        log(f'SAM3DB: unavailable — {why}')
        return None
    paths = [p for p in image_paths if os.path.isfile(p)]
    if not paths:
        log('SAM3DB: no readable images')
        return None
    req = {
        'images': paths,
        'bboxes': {k: list(v) for k, v in (bboxes or {}).items() if k in paths},
        'masks': {k: v for k, v in (masks or {}).items() if k in paths},
        'arrays_dir': arrays_dir,
        'inference_type': inference_type,
    }
    timeout = _LOAD_S + _PER_FRAME_S * len(paths)
    return _run_worker(req, timeout, use_gpu_lock, log)


def fit_one(image_path: str, *, bbox=None, arrays_dir=None, log_fn=None) -> dict | None:
    """One image. Returns that image's record (not the whole map), or None."""
    bb = {image_path: list(bbox)} if bbox else None
    res = fit_batch([image_path], bboxes=bb, arrays_dir=arrays_dir, log_fn=log_fn)
    if not res:
        return None
    rec = res.get(image_path)
    return rec if rec and rec.get('detected') else None


def _run_worker(req: dict, timeout: float, use_gpu_lock: bool, log) -> dict | None:
    in_f = out_f = None
    try:
        with tempfile.NamedTemporaryFile('w', suffix='.json', delete=False) as fh:
            json.dump(req, fh)
            in_f = fh.name
        out_f = in_f + '.out'
        cmd = [_WORKER_PYTHON, _WORKER, '--in', in_f, '--out', out_f]
        if use_gpu_lock and os.environ.get('ZYG_SAM3DB_NO_LOCK') != '1':
            inner = ' '.join(_sh_quote(c) for c in cmd)
            cmd = ['flock', '-w', '7200', _LOCK, '-c', inner]
        r = subprocess.run(cmd, capture_output=True, timeout=timeout)
        if r.returncode != 0:
            log(f'SAM3DB: worker rc={r.returncode} — {r.stderr.decode()[-400:]}')
            return None
        with open(out_f, encoding='utf-8') as fh:
            return json.load(fh)
    except Exception as exc:  # noqa: BLE001
        log(f'SAM3DB: {exc}')
        return None
    finally:
        for p in (in_f, out_f):
            if p and os.path.exists(p):
                try:
                    os.remove(p)
                except OSError as _exc:
                    _zyg_log.debug('temp file %s cleanup skipped: %s', p, _exc)


def _sh_quote(s: str) -> str:
    return "'" + str(s).replace("'", "'\\''") + "'"


if __name__ == '__main__':  # the CLI lives in sam3d_body_service_cli
    from zyg_workflows.sam3d_body_service_cli import main as _cli_main

    raise SystemExit(_cli_main())
