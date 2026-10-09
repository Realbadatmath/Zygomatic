# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""anatomy_qc ledger hook, lazy CPU-pinned MediaPipe loading and vector helpers."""

from __future__ import annotations

import math
import os
import logging as _zyg_logging


from .constants import (
    FACE_CONF,
    FACE_TASK,
    FACE_TASK_URL,
    HAND_CONF,
    HAND_TASK,
    HAND_TASK_URL,
    MAX_FACES,
    MAX_HANDS,
    _LANDMARKERS,
    _LOCK,
)

_zyg_log = _zyg_logging.getLogger('zyg_workflows.anatomy_qc')


# ---------------------------------------------------------------------------
# defensive ledger hook (run_ledger is built by a sibling task; never required)
# ---------------------------------------------------------------------------
def _ledger_gate(gate: str, outcome, score=None, tag: str = '', run_id=None) -> None:
    try:
        from zyg_workflows import run_ledger  # noqa: PLC0415  (lazy + optional by design)
    except Exception:
        return
    try:
        run_id = run_id or os.environ.get('ZYG_RUN_ID') or 'adhoc'
        run_ledger.record_gate(
            run_id, gate, 'unknown' if outcome is None else ('pass' if outcome else 'fail'), score=score, tag=tag
        )
    except Exception as _exc:
        _zyg_log.warning('run ledger write failed, gate %s not recorded: %s', gate, _exc)


def _ledger_fallback(component: str, expected: str, actual: str, detail: str = '') -> None:
    try:
        from zyg_workflows import run_ledger  # noqa: PLC0415  (lazy + optional by design)
    except Exception:
        return
    try:
        run_ledger.record_fallback(component, expected, actual, detail=detail)
    except Exception as _exc:
        _zyg_log.warning('run ledger write failed, fallback %s not recorded: %s', component, _exc)


# ---------------------------------------------------------------------------
# lazy mediapipe loading (CPU-pinned)
# ---------------------------------------------------------------------------
def _pin_cpu_gl() -> None:
    """Keep MediaPipe's task graph off the NVIDIA GL driver.

    Even with a CPU delegate the vision graphs create an EGL context; on this
    box that logged 'renderer: NVIDIA GeForce RTX 4090' and took VRAM from a
    running render. Pointing EGL at the Mesa software vendor removes the
    NVIDIA context entirely (verified: no gl_context_egl line, detection
    unchanged). Opt out with ZYG_MP_CPU_GL=0.
    """
    if os.environ.get('ZYG_MP_CPU_GL', '1') != '1':
        return
    os.environ.setdefault('MEDIAPIPE_DISABLE_GPU', '1')
    mesa = os.environ.get('ZYG_MP_EGL_VENDOR', '/usr/share/glvnd/egl_vendor.d/50_mesa.json')
    if mesa and os.path.isfile(mesa):
        os.environ.setdefault('__EGL_VENDOR_LIBRARY_FILENAMES', mesa)
    else:
        # No software EGL vendor on this host: MediaPipe will build its GL
        # context on the NVIDIA driver and take (a little) VRAM from whatever
        # render owns the card. Not fatal, but never silent.
        _ledger_fallback('anatomy_qc.egl', 'mesa-software', 'system-default', detail=f'missing EGL vendor json: {mesa}')


def available() -> tuple:
    """(bool, reason). True when both landmarkers can actually be built."""
    try:
        _get_landmarker('hand', HAND_CONF)
        _get_landmarker('face', FACE_CONF)
    except Exception as exc:
        return False, f'{type(exc).__name__}: {exc}'
    return True, ''


def hands_available() -> tuple:
    """(bool, reason) for the hand path only — used by the HandFixer switch."""
    try:
        _get_landmarker('hand', HAND_CONF)
    except Exception as exc:
        return False, f'{type(exc).__name__}: {exc}'
    return True, ''


def _get_landmarker(kind: str, conf: float):
    """Build (once) and return a MediaPipe landmarker. RAISES on failure —
    every public entry point wraps this."""
    key = (kind, round(float(conf), 4))
    with _LOCK:
        obj = _LANDMARKERS.get(key)
        if obj is not None:
            return obj
        _pin_cpu_gl()
        from mediapipe.tasks import python as mp_python
        from mediapipe.tasks.python import vision as mp_vision

        task = HAND_TASK if kind == 'hand' else FACE_TASK
        if not os.path.isfile(task):
            raise FileNotFoundError(
                f'mediapipe {kind} bundle missing: {task} (fetch {HAND_TASK_URL if kind == "hand" else FACE_TASK_URL})'
            )
        base = mp_python.BaseOptions(model_asset_path=task, delegate=mp_python.BaseOptions.Delegate.CPU)
        if kind == 'hand':
            opts = mp_vision.HandLandmarkerOptions(
                base_options=base,
                running_mode=mp_vision.RunningMode.IMAGE,
                num_hands=MAX_HANDS,
                min_hand_detection_confidence=conf,
                min_hand_presence_confidence=conf,
                min_tracking_confidence=conf,
            )
            obj = mp_vision.HandLandmarker.create_from_options(opts)
        else:
            opts = mp_vision.FaceLandmarkerOptions(
                base_options=base,
                running_mode=mp_vision.RunningMode.IMAGE,
                num_faces=MAX_FACES,
                min_face_detection_confidence=conf,
                min_face_presence_confidence=conf,
                min_tracking_confidence=conf,
                output_face_blendshapes=False,
                output_facial_transformation_matrixes=False,
            )
            obj = mp_vision.FaceLandmarker.create_from_options(opts)
        _LANDMARKERS[key] = obj
        return obj


def _mp_image(bgr):
    import mediapipe as mp
    import cv2

    return mp.Image(image_format=mp.ImageFormat.SRGB, data=cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB))


def _read_bgr(image_path: str):
    import cv2
    import numpy as np

    img = cv2.imread(image_path, cv2.IMREAD_COLOR)
    if img is None:  # non-ASCII paths / odd containers
        with open(image_path, 'rb') as fh:
            buf = np.frombuffer(fh.read(), dtype=np.uint8)
        img = cv2.imdecode(buf, cv2.IMREAD_COLOR)
    if img is None:
        raise OSError(f'unreadable image: {image_path}')
    return img


# ---------------------------------------------------------------------------
# small vector helpers (numpy is already a hard dep of the stack)
# ---------------------------------------------------------------------------
def _np():
    import numpy as np

    return np


def _dist(a, b):
    return float(math.dist(a, b))


def _unit(v):
    np = _np()
    n = float(np.linalg.norm(v))
    return v / n if n > 1e-9 else v * 0.0


def _angle_deg(u, v):
    np = _np()
    nu, nv = float(np.linalg.norm(u)), float(np.linalg.norm(v))
    if nu < 1e-9 or nv < 1e-9:
        return 0.0
    c = max(-1.0, min(1.0, float(np.dot(u, v)) / (nu * nv)))
    return math.degrees(math.acos(c))


def _robust_z(values):
    """(median, mad_scaled, [z...]) — MAD z-scores, immune to the outliers we
    are hunting. Returns zeros when the series is degenerate."""
    np = _np()
    arr = np.asarray([v for v in values if v is not None], dtype=float)
    if arr.size < 3:
        return (float(arr.mean()) if arr.size else 0.0), 0.0, [0.0] * len(values)
    med = float(np.median(arr))
    mad = float(np.median(np.abs(arr - med))) * 1.4826
    if mad < 1e-9:
        return med, 0.0, [0.0] * len(values)
    out = [(0.0 if v is None else abs(float(v) - med) / mad) for v in values]
    return med, mad, out
