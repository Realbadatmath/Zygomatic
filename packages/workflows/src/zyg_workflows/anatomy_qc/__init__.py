# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""anatomy_qc.py — MediaPipe hand + face anatomy gates (CPU, zero VRAM).

2026-07-30: Built as item 2 of the debug-expansion plan. Two jobs:

  1. Measure what the count-only hand detector could not — six/fused fingers,
     backwards joints, impossible bone proportions, scrambled knuckles,
     left/right ambiguity — from the 21 hand landmarks.
  2. Measure facial melt / ghost faces from the 478-point face mesh:
     detection-rate collapse across a clip, inter-ocular + mouth ratio drift,
     and ECC-compensated landmark jitter.

It also REPLACES the AGPL-3.0 ``ultralytics`` YOLO hand detector: MediaPipe is
Apache-2.0 (google-ai-edge/mediapipe), model bundles included, so the whole
hand path becomes commercially clean. See ``detect_hand_boxes_strict`` and the
``ZYG_HANDS_BACKEND`` switch in hand_qc_service.py.

Why landmark geometry is worth a second look
--------------------------------------------
The 2026-07-24 HandFixer rebuild evaluated landmark scoring and REJECTED it,
correctly: MediaPipe fits its fixed 21-landmark / 5-finger topology onto ANY
hand, so "count the fingers from the landmarks" measures the template, not the
image, and every known-bad frame scored clean. This module therefore never
counts landmarks. It measures how BADLY the fixed template had to be deformed
to fit — degenerate fingertip clusters, reversed joint chains, bone-length
ratios outside human range, knuckles out of order, and (the strongest signal)
a handedness classifier that cannot decide which hand it is looking at. Those
are properties of the fit residual, not of the template.

Contract (pinned across the expansion plan)
-------------------------------------------
  qc_hands_frame(image_path, expected_hands=None) -> {'ok','hands','issues',...}
  qc_hands_clip(clip_path, n_people, sample_every=8)  -> aggregate
  qc_face_frame(image_path, expected_faces=None) -> {'ok','faces','issues',...}
  qc_face_clip(clip_path, n_people, sample_every=8)   -> aggregate

'ok' tri-state, and the r4 rule applies unchanged:
    True  = measured clean
    False = measured defective
    None  = UNKNOWN (tool unavailable, nothing detected, stylized art the
            photoreal detectors cannot score). None is NEVER "clean".
Nothing in this module raises across the module boundary; QC breakage must
never block generation. The single deliberate exception is
``detect_hand_boxes_strict``, the fail-closed HandFixer gate, which RAISES —
see its docstring.

Stylized / Arcane caveat (documented, load-bearing)
--------------------------------------------------
MediaPipe's palm and face detectors are trained on photographs and on a small
square input, so a subject occupying a modest fraction of a 1664x960 render is
below their operating range. Measured on scene20_v7 beat_1.0.png: ZERO faces
whole-frame even at confidence 0.01, yet Cornelis's face resolves immediately
from a head-sized crop; hands go 0 detections at 0.5 confidence, 2 at 0.2.
Three mitigations, all measured:
  * TWO passes — permissive (ZYG_MP_*_CONF, default 0.20) for recall, strict
    (ZYG_MP_*_CONF_STRONG, default 0.50) for scoring. Geometry only turns 'ok'
    False on a hand/face the STRICT pass also found in the same region;
    permissive-only detections are advisory and drive 'ok' to None. Low
    detection confidence is a reported signal, not a silent miss.
  * TILED escalation (ZYG_MP_TILE_GRIDS, default '2,3'), skipped on images
    already smaller than ZYG_MP_TILE_MIN_PX (400) so subject-sized crops are
    not re-tiled into duplicates.
  * a resolution gate (ZYG_MP_MIN_PALM_PX, 24): below it a phalanx spans a
    handful of pixels, so geometry can never produce a hard verdict.
Even so, on 1672-drama Arcane footage the face detector loses profile heads
entirely. That is why a face-track dropout is only HARD evidence of melt when
the last observed pose was frontal — verified: Cornelis's track drops out
twice while his face is perfectly intact, at yaw proxy 0.56/0.57. ROI-scoped
calls (per-character head crops, as the forensics writer already produces) are
the reliable way to use the face gate on this content.

GPU posture and real cost
-------------------------
Pure CPU, zero VRAM. MediaPipe's task graphs otherwise open an EGL/GL context
on the NVIDIA device even when the delegate is CPU (observed: 'renderer:
NVIDIA GeForce RTX 4090'); this module pins EGL to the Mesa software vendor
before the first import. Disable with ZYG_MP_CPU_GL=0.
Measured 2026-07-30 on this box (single thread):
    233x201 hand crop, no tiling ............  19-42 ms/frame
    832x480 frame, tiled ....................    ~250 ms/frame
    1664x960 frame, tiled 2+3 ...............    ~340-700 ms/frame
    299x259 head crop, face gate ............     54 ms/frame
    qc_hands_clip + qc_face_clip, 341-frame 832x480 clip @ sample_every=8
      (43 samples) ..........................   ~28 s + ~41 s
Set ZYG_MP_TILE_GRIDS=0 for the ~5x cheaper whole-frame-only path when the
subject is large in frame.

Self-test:
  python3 anatomy_qc.py --hands <image|dir> [...]
  python3 anatomy_qc.py --faces <image|dir> [...]
  python3 anatomy_qc.py --clip  <video.mp4> --people 2 [--every 8]
"""

from __future__ import annotations

import math
import os
import sys
import threading
import logging as _zyg_logging

from zyg_workflows import paths

from .constants import (
    BONE_TOL,
    CHIRAL_AMBIG,
    CHIRAL_SURE,
    CHIRAL_TRACK_FRAC,
    DETECT_RATE_FLOOR,
    FACE_CONF,
    FACE_CONF_STRONG,
    FACE_TASK,
    FACE_TASK_URL,
    FACE_TRACK_FRAC,
    FINGERS,
    FUSE_FRAC,
    FUSE_REL,
    HAND_CONF,
    HAND_CONF_STRONG,
    HAND_TASK,
    HAND_TASK_URL,
    JITTER_FLOOR,
    JITTER_MAX,
    JITTER_Z,
    KNUCKLE_SLACK,
    MAX_FACES,
    MAX_HANDS,
    MELT_RUN,
    MIN_PALM_PX,
    MODEL_DIR,
    NOISE_FACE_PX,
    NOISE_PALM_PX,
    OPEN_FRAC,
    RATIO_Z,
    REVERSE_DEG,
    REVERSE_DOT,
    STRICT_COUNT,
    TURN_MAX_DEG,
    WRIST,
    YAW_FRONTAL,
    _BONE_REF,
    _F_BROW,
    _F_CHEEK_L,
    _F_CHEEK_R,
    _F_CHIN,
    _F_EYE_L_IN,
    _F_EYE_L_OUT,
    _F_EYE_R_IN,
    _F_EYE_R_OUT,
    _F_IRIS_L,
    _F_IRIS_R,
    _F_LIP_BOT,
    _F_LIP_TOP,
    _F_MOUTH_L,
    _F_MOUTH_R,
    _KNUCKLES,
    _LANDMARKERS,
    _LOCK,
    _LONG_FINGERS,
    _TIPS,
    _envf,
    _envi,
    _log_noop,
)

from .runtime import (
    _angle_deg,
    _dist,
    _get_landmarker,
    _ledger_fallback,
    _ledger_gate,
    _mp_image,
    _np,
    _pin_cpu_gl,
    _read_bgr,
    _robust_z,
    _unit,
    available,
    hands_available,
)

from .hands import (
    _dedupe,
    _detect_hands,
    _hand_box,
    _hand_candidates,
    _hand_points,
    _hand_world,
    _hands_from_array,
    _score_hand,
    _tile_boxes,
    _tile_grids,
    qc_hands_frame,
)

from .faces import (
    _FACE_BANDS,
    _detect_faces,
    _face_candidates,
    _face_metrics,
    _face_points,
    _faces_from_array,
    qc_face_frame,
)

from .clips import (
    _clip_fps,
    _iter_frames,
    qc_face_clip,
    qc_hands_clip,
)

from .cli import (
    _expand,
    _main,
    detect_hand_boxes_strict,
)

_zyg_log = _zyg_logging.getLogger(__name__)

__all__ = [
    'math',
    'os',
    'sys',
    'threading',
    '_zyg_logging',
    'paths',
    'BONE_TOL',
    'CHIRAL_AMBIG',
    'CHIRAL_SURE',
    'CHIRAL_TRACK_FRAC',
    'DETECT_RATE_FLOOR',
    'FACE_CONF',
    'FACE_CONF_STRONG',
    'FACE_TASK',
    'FACE_TASK_URL',
    'FACE_TRACK_FRAC',
    'FINGERS',
    'FUSE_FRAC',
    'FUSE_REL',
    'HAND_CONF',
    'HAND_CONF_STRONG',
    'HAND_TASK',
    'HAND_TASK_URL',
    'JITTER_FLOOR',
    'JITTER_MAX',
    'JITTER_Z',
    'KNUCKLE_SLACK',
    'MAX_FACES',
    'MAX_HANDS',
    'MELT_RUN',
    'MIN_PALM_PX',
    'MODEL_DIR',
    'NOISE_FACE_PX',
    'NOISE_PALM_PX',
    'OPEN_FRAC',
    'RATIO_Z',
    'REVERSE_DEG',
    'REVERSE_DOT',
    'STRICT_COUNT',
    'TURN_MAX_DEG',
    'WRIST',
    'YAW_FRONTAL',
    '_BONE_REF',
    '_F_BROW',
    '_F_CHEEK_L',
    '_F_CHEEK_R',
    '_F_CHIN',
    '_F_EYE_L_IN',
    '_F_EYE_L_OUT',
    '_F_EYE_R_IN',
    '_F_EYE_R_OUT',
    '_F_IRIS_L',
    '_F_IRIS_R',
    '_F_LIP_BOT',
    '_F_LIP_TOP',
    '_F_MOUTH_L',
    '_F_MOUTH_R',
    '_KNUCKLES',
    '_LANDMARKERS',
    '_LOCK',
    '_LONG_FINGERS',
    '_TIPS',
    '_envf',
    '_envi',
    '_log_noop',
    '_angle_deg',
    '_dist',
    '_get_landmarker',
    '_ledger_fallback',
    '_ledger_gate',
    '_mp_image',
    '_np',
    '_pin_cpu_gl',
    '_read_bgr',
    '_robust_z',
    '_unit',
    'available',
    'hands_available',
    '_dedupe',
    '_detect_hands',
    '_hand_box',
    '_hand_candidates',
    '_hand_points',
    '_hand_world',
    '_hands_from_array',
    '_score_hand',
    '_tile_boxes',
    '_tile_grids',
    'qc_hands_frame',
    '_FACE_BANDS',
    '_detect_faces',
    '_face_candidates',
    '_face_metrics',
    '_face_points',
    '_faces_from_array',
    'qc_face_frame',
    '_clip_fps',
    '_iter_frames',
    'qc_face_clip',
    'qc_hands_clip',
    '_expand',
    '_main',
    'detect_hand_boxes_strict',
    '_zyg_log',
]
