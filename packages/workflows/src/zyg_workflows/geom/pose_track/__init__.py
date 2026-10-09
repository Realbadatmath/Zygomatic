# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

# ruff: noqa: E402,F401

"""pose_track.py — a per-shot POSE TRACK for the VACE control channel (2026-09-02).

RUN (either venv; the two model stacks are subprocesses):
    python -m zyg_workflows.geom.pose_track <clip.mp4> --out <dir> [--subject "the young man"]
                              [--fps 17] [--max-frames N] [--smooth savgol|oneeuro|none]

WHAT WAS MISSING. Every character control this box has ever built is ONE geometry
statement stretched over a clip: char_vace paints the still's detected skeleton into
every frame, and anny_animate lerps between exactly two fitted poses
(geom/anny_animate.py:81-153). geom/keypoints.py builds MediaPipe in IMAGE mode with
no tracking at all, and anny_fit.fit_cell takes a cell DIRECTORY, not keypoints. So
there has been no per-shot track to drive anything with. This is that track.

THE CHAIN:
    clip -> ffmpeg frames at the render fps (17 by default: the control sequence and
            the render must agree frame for frame or the guidance slides)
    -> SAM 3 (phrase-prompted, one worker invocation for the whole clip) gives a box
       and a mask PER FRAME for the named subject; the box is chosen by IoU
       continuity from the first frame, not by per-frame score, so a two-hander does
       not swap people halfway through
    -> SAM 3D Body per frame WITH those boxes -> MHR params, 70 keypoints in 2D and
       3D, 127 joint global rotations, 18439 vertices
    -> shape lock: median shape_params/scale_params over the track
    -> temporal filter on rotations, translations, keypoints and vertices
    -> track.json + track_arrays.npz + masks/m_%05d.png (the VACE mask format)

HONEST LIMITS, because two of them change what the numbers mean:

  1. THE SHAPE LOCK IS RECORDED, NOT RE-SYNTHESISED. Locking identity properly means
     re-running the MHR forward with the median shape and each frame's pose. That
     needs `pymomentum`, which Meta ships through conda only — and the PyPI package
     of that name is an unrelated SMS library, so it must not be installed (see
     sam3d_body_service.mhr_decode_available). The median is therefore written to
     track.json as `shape_locked`, the per-frame deviation from it is MEASURED and
     reported, and the vertices used downstream are the estimator's own per-frame
     `pred_vertices`. `shape_lock_applied` in track.json says false. A track that
     claimed a lock it did not apply would be the exact kind of gate this codebase
     keeps catching.

  2. THE TRACK IS A PER-FRAME FIT, NOT A TEMPORAL MODEL. SAM 3D Body has no memory
     between frames; continuity comes from the box track and the filter, and that is
     all. The jitter number in `metrics` is the honest measure of how much is left.

LEDGER. Every frame gets one of four states, never a silent zero:
    found          — the subject was detected and fitted
    not_found      — the fitter ran and returned nothing (the person is absent/occluded)
    not_detectable — no box for this frame at all (SAM 3 found no subject)
    unmeasurable   — the frame could not be read or the worker errored on it
"""

from __future__ import annotations

import argparse
import contextlib
import glob
import json
import os
import subprocess
import sys
import time

import numpy as np

try:
    import cv2
except Exception:  # pragma: no cover
    cv2 = None
import logging as _zyg_logging
from zyg_workflows import paths
from zyg_workflows.bin import exe

from . import constants as _constants
from . import track as _track
from . import probes as _probes
from . import cli as _cli

from .constants import (
    FOUND,
    MHR70_TO_POSE,
    NOT_DETECTABLE,
    NOT_FOUND,
    OUT_ROOT,
    UNMEASURABLE,
    _CREWS,
    _GPU_LOCK,
    _mem_available_gb,
    _wait_for_ram,
    _zyg_log,
    gpu_lock,
)
from .track import (
    _iou,
    _one_euro,
    _rotvec,
    _savgol,
    _unwrap_rotvec,
    build_track,
    extract_frames,
    rotvec_to_matrix,
    smooth_series,
    subject_track,
)
from .probes import (
    SOMA_X,
    _obj_verts,
    _umeyama,
    gate_against_2d,
    soma_registration_probe,
)
from .cli import (
    main,
)

import sys as _sys
import types as _types

#: tests/test_gpu_run.py:125,150 do `monkeypatch.setattr(P, '_GPU_LOCK', TMP_LOCK)`
#: — in the single-file module that rebound the very global `gpu_lock` reads.
#: Across modules it would only rebind the package attribute and the patch would
#: silently do nothing (the real ~/.zyg_gpu.lock would be taken instead), so every
#: write to the package is mirrored into each section module that holds the name.
_SECTIONS = (_constants, _track, _probes, _cli)


class _PoseTrackModule(_types.ModuleType):
    def __setattr__(self, name, value):
        _types.ModuleType.__setattr__(self, name, value)
        for _m in self.__dict__.get('_SECTIONS') or ():
            if name in _m.__dict__:
                setattr(_m, name, value)

    def __delattr__(self, name):
        for _m in self.__dict__.get('_SECTIONS') or ():
            if name in _m.__dict__:
                delattr(_m, name)
        _types.ModuleType.__delattr__(self, name)


_sys.modules[__name__].__class__ = _PoseTrackModule
