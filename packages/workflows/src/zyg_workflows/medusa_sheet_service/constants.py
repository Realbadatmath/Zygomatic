# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

# ruff: noqa: F401  this module inherits the pre-split file's top import
# block verbatim; its siblings re-import from here, so nothing is unused.

from __future__ import annotations

import json
import math
import os
import re
import threading
import time
from typing import Any, Callable
import logging as _zyg_logging

from zyg_workflows import paths

# channel kept from the pre-split module
_zyg_log = _zyg_logging.getLogger('zyg_workflows.medusa_sheet_service')


# Must stay in step with bp_medusa_training._SHEET_PAGE_RE, which gates serving.
_PAGE_NAME_RE = re.compile(r'^medusa_sheet_[0-9]{2,4}\.png$')

# ── Detector bundles (Apache-2.0, already vendored on disk) ──────────────────
_DETECTOR_DIR = os.environ.get(
    'ZYG_MEDUSA_SHEET_DETECTORS',
    str(paths.DATA_DIR / 'assets' / 'detectors'),
)
_FACE_TASK = os.path.join(_DETECTOR_DIR, 'face_landmarker.task')
_POSE_TASK = os.path.join(_DETECTOR_DIR, 'pose_landmarker_full.task')

# Worker threads for the classify pass. The box has a system-wide 20-of-24 core
# ceiling, and MediaPipe IMAGE mode is CPU-bound, so keep this modest and
# tunable rather than saturating.
_WORKERS = max(1, min(8, int(os.environ.get('ZYG_MEDUSA_SHEET_WORKERS', '4') or 4)))

# QC thresholds
_BLUR_VAR_MIN = float(os.environ.get('ZYG_MEDUSA_SHEET_BLUR_MIN', '55'))
_MIN_EDGE_PX = int(os.environ.get('ZYG_MEDUSA_SHEET_MIN_EDGE', '384'))
_DUPE_HAMMING_MAX = int(os.environ.get('ZYG_MEDUSA_SHEET_DUPE_HAMMING', '4'))

# Montage layout
_SHEET_COLS = int(os.environ.get('ZYG_MEDUSA_SHEET_COLS', '8'))
_SHEET_ROWS = int(os.environ.get('ZYG_MEDUSA_SHEET_ROWS', '6'))
_CELL_PX = int(os.environ.get('ZYG_MEDUSA_SHEET_CELL_PX', '256'))
_LABEL_PX = 22


# ══════════════════════════════════════════════════════════════════════════
# Canonical taxonomy
# ══════════════════════════════════════════════════════════════════════════
# Yaw sign convention matches contact_sheet_pipeline's prompt vocabulary:
# negative yaw is described "left" (measured: its "35 degrees left" cell reads
# -37.4). Bounds are half-open [lo, hi).
YAW_BUCKETS: list[tuple[str, float, float]] = [
    ('profile_left', -180.0, -75.0),
    ('strong_three_quarter_left', -75.0, -52.0),
    ('three_quarter_left', -52.0, -28.0),
    ('near_frontal_left', -28.0, -12.0),
    ('front', -12.0, 12.0),
    ('near_frontal_right', 12.0, 28.0),
    ('three_quarter_right', 28.0, 52.0),
    ('strong_three_quarter_right', 52.0, 75.0),
    ('profile_right', 75.0, 180.0),
]

# Slots reachable only via the pose fallback (no face mesh). The "_unsided"
# variants exist because that tier can prove an angle band without proving a
# side; inventing the side would be exactly the guess this module refuses.
YAW_TERMS: dict[str, str] = {
    'front': 'front view',
    'near_frontal_left': 'near-frontal left view',
    'near_frontal_right': 'near-frontal right view',
    'three_quarter_left': 'three-quarter left view',
    'three_quarter_right': 'three-quarter right view',
    'strong_three_quarter_left': 'strong three-quarter left view',
    'strong_three_quarter_right': 'strong three-quarter right view',
    'profile_left': 'left profile view',
    'profile_right': 'right profile view',
    'profile_unsided': 'profile view',
    'back_three_quarter': 'back three-quarter view',
    'back': 'back view, back of head',
    'unknown': '',
}

# ── Tier-2 thresholds (all calibrated 2026-08-07 — see module docstring) ────
_POSE_MIN_SHOULDER_SPAN = 0.06  # below this the pose is degenerate
_EAR_DX_BACK_MAX = -0.12  # <= this -> facing away
_EAR_DX_PROFILE_MAX = 0.35  # between back and this -> profile band
_NOSE_OFF_SIDED_MIN = 0.9  # |nose_off| above this -> the side is resolvable

# Front-view pitch carries a small positive bias in practice (measured +2.5 to
# +11 on cells whose intent was eye-level), so 'level' is deliberately wide.
PITCH_BUCKETS: list[tuple[str, float, float]] = [
    ('below_chin', -90.0, -28.0),
    ('low_angle', -28.0, -14.0),
    ('level', -14.0, 16.0),
    ('high_angle', 16.0, 38.0),
    ('overhead', 38.0, 90.0),
]

PITCH_TERMS: dict[str, str] = {
    'below_chin': 'low upward camera below chin level',
    'low_angle': 'low camera angle',
    'level': '',
    'high_angle': 'high camera angle',
    'overhead': 'overhead top-down camera',
    'unknown': '',
}

FRAMING_TERMS: dict[str, str] = {
    'close_up': 'close-up face',
    'head_shoulders': 'head and shoulders',
    'chest_up': 'chest-up medium shot',
    'full_body': 'full body',
    'unknown': '',
}

# The coverage target. Reported as GROUPS of slots rather than raw slots: the
# question that matters for a training set is "is there profile coverage",
# which an unsided profile answers just as well as a sided one. Sidedness is
# still reported separately (see coverage_report -> 'sided_gaps') because a set
# with six left profiles and no right ones is genuinely lopsided.
COVERAGE_GROUPS: dict[str, tuple[str, ...]] = {
    'front': ('front',),
    'near_frontal': ('near_frontal_left', 'near_frontal_right'),
    'three_quarter': ('three_quarter_left', 'three_quarter_right'),
    'strong_three_quarter': ('strong_three_quarter_left', 'strong_three_quarter_right'),
    'profile': ('profile_left', 'profile_right', 'profile_unsided'),
    'back_three_quarter': ('back_three_quarter',),
    'back': ('back',),
}
# Pairs whose two sides should both be present; reported as 'sided_gaps'.
COVERAGE_SIDED_PAIRS: tuple[tuple[str, str, str], ...] = (
    ('near_frontal', 'near_frontal_left', 'near_frontal_right'),
    ('three_quarter', 'three_quarter_left', 'three_quarter_right'),
    ('strong_three_quarter', 'strong_three_quarter_left', 'strong_three_quarter_right'),
    ('profile', 'profile_left', 'profile_right'),
)
COVERAGE_FRAMINGS = ('close_up', 'head_shoulders', 'chest_up', 'full_body')
# Pitch variety is reported separately rather than as a required slot.
COVERAGE_PITCHES = ('low_angle', 'level', 'high_angle')


def _bucket(value: float, table: list[tuple[str, float, float]]) -> str:
    for name, lo, hi in table:
        if lo <= value < hi:
            return name
    return 'unknown'


# ══════════════════════════════════════════════════════════════════════════
# Detectors — one set per worker thread (MediaPipe tasks are not thread-safe)
# ══════════════════════════════════════════════════════════════════════════
_tls = threading.local()


def detectors_available() -> tuple[bool, str]:
    """Cheap preflight so the UI can explain itself instead of failing mid-run."""
    for p in (_FACE_TASK, _POSE_TASK):
        if not os.path.isfile(p):
            return False, f'missing detector bundle: {p}'
    try:
        import mediapipe  # noqa: F401
    except Exception as exc:
        return False, f'mediapipe unavailable ({exc.__class__.__name__})'
    return True, ''


def _get_detectors():
    got = getattr(_tls, 'det', None)
    if got is not None:
        return got
    os.environ.setdefault('GLOG_minloglevel', '3')
    from mediapipe.tasks.python import BaseOptions
    from mediapipe.tasks.python import vision

    face = vision.FaceLandmarker.create_from_options(
        vision.FaceLandmarkerOptions(
            base_options=BaseOptions(model_asset_path=_FACE_TASK),
            running_mode=vision.RunningMode.IMAGE,
            num_faces=1,
            min_face_detection_confidence=0.25,
            min_face_presence_confidence=0.25,
            output_facial_transformation_matrixes=True,
        )
    )
    pose = vision.PoseLandmarker.create_from_options(
        vision.PoseLandmarkerOptions(
            base_options=BaseOptions(model_asset_path=_POSE_TASK),
            running_mode=vision.RunningMode.IMAGE,
            num_poses=1,
            min_pose_detection_confidence=0.25,
            min_pose_presence_confidence=0.25,
        )
    )
    _tls.det = (face, pose)
    return _tls.det


def _euler_from_matrix(matrix) -> tuple[float, float, float]:
    """Yaw/pitch/roll in degrees from MediaPipe's 4x4 facial transform."""
    import numpy as np

    R = np.asarray(matrix, dtype=float)[:3, :3]
    sy = math.sqrt(float(R[0, 0]) ** 2 + float(R[1, 0]) ** 2)
    if sy > 1e-6:
        pitch = math.degrees(math.atan2(float(R[2, 1]), float(R[2, 2])))
        yaw = math.degrees(math.atan2(-float(R[2, 0]), sy))
        roll = math.degrees(math.atan2(float(R[1, 0]), float(R[0, 0])))
    else:
        pitch = math.degrees(math.atan2(-float(R[1, 2]), float(R[1, 1])))
        yaw = math.degrees(math.atan2(-float(R[2, 0]), sy))
        roll = 0.0
    return yaw, pitch, roll
