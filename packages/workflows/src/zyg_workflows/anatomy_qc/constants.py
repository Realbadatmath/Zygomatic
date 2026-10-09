# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""anatomy_qc model assets, env-overridable tunables and landmark topology."""

from __future__ import annotations

import os
import threading

from zyg_workflows import paths


# ---------------------------------------------------------------------------
# model assets
# ---------------------------------------------------------------------------
MODEL_DIR = paths.ZYG_MP_MODEL_DIR
HAND_TASK = os.path.join(MODEL_DIR, 'hand_landmarker.task')
FACE_TASK = os.path.join(MODEL_DIR, 'face_landmarker.task')

# Official Apache-2.0 bundles (google-ai-edge MediaPipe model garden), kept
# here so re-provisioning does not have to go hunting:
HAND_TASK_URL = (
    'https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task'
)
FACE_TASK_URL = (
    'https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task'
)


# ---------------------------------------------------------------------------
# tunables (all env-overridable; defaults calibrated on scene20_v7)
# ---------------------------------------------------------------------------
def _envf(name, default):
    try:
        return float(os.environ.get(name, default))
    except (TypeError, ValueError):
        return float(default)


def _envi(name, default):
    try:
        return int(float(os.environ.get(name, default)))
    except (TypeError, ValueError):
        return int(default)


HAND_CONF = _envf('ZYG_MP_HAND_CONF', 0.20)  # permissive: recall
HAND_CONF_STRONG = _envf('ZYG_MP_HAND_CONF_STRONG', 0.50)  # strict: scoring
FACE_CONF = _envf('ZYG_MP_FACE_CONF', 0.20)
FACE_CONF_STRONG = _envf('ZYG_MP_FACE_CONF_STRONG', 0.50)
MAX_HANDS = _envi('ZYG_MP_MAX_HANDS', 6)
MAX_FACES = _envi('ZYG_MP_MAX_FACES', 6)

FUSE_FRAC = _envf('ZYG_MP_FUSE_FRAC', 0.16)  # tip gap / palm unit
FUSE_REL = _envf('ZYG_MP_FUSE_REL', 0.35)  # tip gap / knuckle gap
OPEN_FRAC = _envf('ZYG_MP_OPEN_FRAC', 0.85)  # span/chain -> finger extended
TURN_MAX_DEG = _envf('ZYG_MP_JOINT_TURN_MAX_DEG', 115.0)
REVERSE_DEG = _envf('ZYG_MP_REVERSE_DEG', 25.0)
REVERSE_DOT = _envf('ZYG_MP_REVERSE_DOT', -0.60)  # bend-axis anti-alignment
BONE_TOL = _envf('ZYG_MP_BONE_TOL', 2.2)  # factor around the model's own median
CHIRAL_AMBIG = _envf('ZYG_MP_CHIRAL_AMBIG', 0.62)  # handedness score floor
CHIRAL_SURE = _envf('ZYG_MP_CHIRAL_SURE', 0.85)  # bar for claiming a FLIP
CHIRAL_TRACK_FRAC = _envf('ZYG_MP_CHIRAL_TRACK_FRAC', 0.75)  # of hand diagonal
KNUCKLE_SLACK = _envf('ZYG_MP_KNUCKLE_SLACK', 0.12)
MIN_PALM_PX = _envf('ZYG_MP_MIN_PALM_PX', 24.0)  # below this, geometry is advisory
NOISE_PALM_PX = _envf('ZYG_MP_NOISE_PALM_PX', 12.0)  # below this, not a hand
NOISE_FACE_PX = _envf('ZYG_MP_NOISE_FACE_PX', 40.0)  # hull width floor
YAW_FRONTAL = _envf('ZYG_MP_YAW_FRONTAL', 0.18)  # |nose offset|/inter-ocular

RATIO_Z = _envf('ZYG_MP_RATIO_Z', 4.0)
JITTER_Z = _envf('ZYG_MP_JITTER_Z', 3.5)
JITTER_FLOOR = _envf('ZYG_MP_JITTER_FLOOR', 0.06)  # of inter-ocular distance
JITTER_MAX = _envf('ZYG_MP_JITTER_MAX', 2.0)  # above this = association slip
FACE_TRACK_FRAC = _envf('ZYG_MP_FACE_TRACK_FRAC', 0.90)  # of face width
MELT_RUN = _envi('ZYG_MP_MELT_RUN', 3)  # consecutive lost samples
DETECT_RATE_FLOOR = _envf('ZYG_MP_DETECT_RATE_FLOOR', 0.60)
STRICT_COUNT = os.environ.get('ZYG_MP_STRICT_COUNT', '0') == '1'

# Per-finger phalanx-length ratios (mid/prox, dist/mid) measured from the
# hand_landmarker's own WORLD landmarks, not from anthropometry tables. That
# distinction is the whole point: the landmarker regularizes every hand toward
# its learned skeleton, so the only informative question is how far a fit sits
# outside the envelope the model itself produces on ordinary frames. Medians
# below come from 154 detections over the scene20_v7 forensics strips, the
# scene20_v6 beats and the multichar_walk iterations (2026-07-30). Textbook
# anthropometric values (0.60 / 0.70 for every finger) flagged the thumb on
# essentially every hand — the thumb's landmark-1 "metacarpal" is not a
# phalanx and does not obey the finger ratios.
_BONE_REF = {
    'thumb': (1.175, 0.881),
    'index': (0.703, 1.305),
    'middle': (0.888, 0.843),
    'ring': (0.857, 0.888),
    'pinky': (1.109, 0.895),
}

_LOCK = threading.Lock()
_LANDMARKERS: dict = {}

# hand landmark topology
WRIST = 0
FINGERS = {  # name -> [MCP, PIP, DIP, TIP]  (thumb: CMC,MCP,IP,TIP)
    'thumb': [1, 2, 3, 4],
    'index': [5, 6, 7, 8],
    'middle': [9, 10, 11, 12],
    'ring': [13, 14, 15, 16],
    'pinky': [17, 18, 19, 20],
}
_LONG_FINGERS = ('index', 'middle', 'ring', 'pinky')
_TIPS = [4, 8, 12, 16, 20]
_KNUCKLES = [5, 9, 13, 17]

# face mesh landmarks (canonical 478-pt attention mesh)
_F_IRIS_L, _F_IRIS_R = 468, 473
_F_EYE_L_OUT, _F_EYE_L_IN = 33, 133
_F_EYE_R_IN, _F_EYE_R_OUT = 362, 263
_F_MOUTH_L, _F_MOUTH_R = 61, 291
_F_LIP_TOP, _F_LIP_BOT = 0, 17
_F_CHEEK_L, _F_CHEEK_R = 234, 454
_F_CHIN, _F_BROW = 152, 10


def _log_noop(_m):
    pass
