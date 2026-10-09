# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Constants shared by the outer python side and the Blender worker.

Moved verbatim out of geom/mv_render.py; see that package's __init__ for the
full rationale. ROOT comes from `paths.PKG_DIR` and the logger keeps the
pre-split channel name explicitly, so neither depends on where this file sits.
"""

# ruff: noqa: F401  # the original top import block lives here; siblings re-import from it

import argparse
import datetime
import glob
import json
import math
import os
import shutil
import subprocess
import sys
import tempfile
import logging as _zyg_logging

from zyg_workflows import paths

# channel kept from the pre-split module
_zyg_log = _zyg_logging.getLogger('zyg_workflows.geom.mv_render')


# ---------------------------------------------------------------------------
# Constants shared by BOTH sides (outer python and the Blender worker). The
# Blender worker gets them through the JSON config, never by import: Blender's
# bundled python is 3.11 with no access to this repo's venv.
# ---------------------------------------------------------------------------

BLENDER = str(paths.BLENDER_BIN)
ROOT = str(paths.PKG_DIR)

FEMALE_GLB = 'data/assets/mesh_skeletons/originals/female/skeleton_female.glb'

OUT_W, OUT_H = 1024, 1152  # exactly the real exported cell size
N_VIEWS = 48
AZIMUTH_STEP_DEG = 360.0 / N_VIEWS  # 7.5
ELEVATION_DEG = 0.0

# Portrait-orientation full frame: the 36 mm dimension is the VERTICAL one, which is
# what a portrait photographer actually has. sensor_fit must be set to VERTICAL or
# Blender's AUTO fit silently applies sensor_width to the longer axis instead.
SENSOR_MM = 36.0
LENS_MM = 85.0

# Frame height as a multiple of stature. Calibrated 2026-08-07 against the measured
# head-and-shoulders coverage of the real cells (median 0.508): 0.2755 x stature lands
# the rendered cage at 0.4783 median coverage over the 48 turntable frames — 6 % low in
# relative terms, and left there rather than nudged, because the two numbers come from
# different instruments (see difference D7) and chasing the last 6 % would be fitting
# our own asset to the measurement error of a segmenter. This is a FRAMING match, not a
# threshold; no gate anywhere consumes it.
FRAME_H_PER_STATURE = 0.2755
# Fraction of frame height between the top edge and the head vertex. Measured off
# cell_00: subject mask starts at y = 0.058 H.
HEAD_TOP_MARGIN = 0.058

# 32 samples + OpenImageDenoise. MEASURED against a 160-sample reference of the same
# frame: mean |diff| 0.52 bytes, rms 1.04 bytes, p99 4 bytes, on a subject whose own
# pixel sd is 34.7 bytes — a 33:1 signal-to-residual ratio, far below anything a DoG
# detector will latch onto. 160 spp took 50 s PER FRAME and would have bought nothing.
# Wall clock at 32 spp: 5.1 s/frame on an idle machine (~4 min for a 48-frame set); the
# delivered build ran against a load average of ~70 from other agents and took 17.1 min
# for positive_textured and 11.3 min for positive_untextured. Budget by load, not by
# the 4 min number.
CYCLES_SAMPLES = 32

# Slack around the projected-shift PREDICTION WINDOW in the texture-lock translation test.
# It absorbs the integer NCC peak (+/-1 px) and the depth weighting inside the crop; it is
# NOT slack around a single predicted value, because the prediction is a range — see
# _bl_verify_texture_lock. A screen-locked pattern peaks at 0 px against a window at 74-79,
# so this tolerance has no bearing on the test's power.
TRANSLATION_TOL_PX = 3.0

# Written by the Blender worker as its LAST act, and read by _render_positive. Blender exits
# 0 on an uncaught Python exception, so a returncode is not proof the worker finished; a
# sentinel that only a completed run can have written is.
WORKER_STATUS = 'worker_status.json'

# The six characters with a complete 48-cell sheet. All six were verified to carry an
# IDENTICAL cell_angles list in their contact_sheet/manifest.json, which is what makes
# "matching angle indices" meaningful: index i is the same requested camera for all six.
NEG_CHARS = ['c3345deb5bde', 'f60a454aa472', 'e58b9137bdc5', 'dc1669d1afdb', 'd835e0711f41', 'd00967bf3bb6']
CHAR_ROOT = str(paths.ZYG_LORA_DATASETS / 'storyteller_chars')

SETS = ('positive_textured', 'positive_untextured', 'negative_mixed')


def _now():
    return datetime.datetime.now().replace(microsecond=0).isoformat()
