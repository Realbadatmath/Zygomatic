# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""kids_series_common.py — the module docstring aside: the original top import block and every module-level constant (lines 76-76, 77-168 of the pre-split file, verbatim)."""

from __future__ import annotations

import argparse
import glob
import importlib
import json
import os
import random
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import traceback
import uuid
import logging as _zyg_logging

from zyg_workflows import paths as _paths
from zyg_workflows import provenance_seal as _seal
from zyg_workflows import runtime as _runtime
from zyg_workflows.bin import exe
from zyg_workflows.runtime import ams_iso as _ams_iso, workflow_jobs as _workflow_jobs

# channel kept from the pre-split module
_zyg_log = _zyg_logging.getLogger('zyg_workflows.kids_series_common')

# ── re-export surface ────────────────────────────────────────────────────────
# This is the original top import block and the names below are not used here:
# the siblings re-import them off this module (``from .constants import json, os,
# …``) — jobs.py takes argparse/glob/importlib/json/sys/threading/time/traceback/
# uuid/_runtime/_ams_iso/_workflow_jobs, ffmpeg.py json/shutil/subprocess/
# tempfile/_seal, audio.py random/shutil/tempfile/threading, visuals.py shutil.
# Declaring them is what makes the re-export deliberate rather than an unused
# import; nothing does ``import *`` from here, so __all__ changes no behaviour.
__all__ = [
    'argparse',
    'glob',
    'importlib',
    'json',
    'random',
    'shutil',
    'subprocess',
    'sys',
    'tempfile',
    'threading',
    'time',
    'traceback',
    'uuid',
    '_seal',
    '_runtime',
    '_ams_iso',
    '_workflow_jobs',
]


CREWS = str(_paths.PKG_DIR)
OUT_BASE = os.path.join(CREWS, 'output')

W, H, FPS = 1280, 720, 24

# The look.  One sentence prefixed to every prompt in a series so an episode
# reads as one film.  Copied from kids_video_service.BASE_STYLE rather than
# imported, because that module resolves a checkpoint and a gate at import
# time and this one must stay cheap enough for a CPU-only test to import.
KID_STYLE = (
    'flat 2D cartoon illustration for young children, children picture-book art, '
    'bold clean dark outlines, simple rounded shapes, large friendly forms, '
    'flat colour fills, minimal detail, plain uncluttered background, '
    'cheerful joyful and wholesome, sweet and gentle, safe for toddlers, '
    'no text anywhere in the picture'
)

# The anti-photoreal terms are repeated here because a positive alone does not
# stop a model reaching for photography — and the lettering terms because the
# voice says the words, the picture never writes them.
KID_NEGATIVE = (
    'photorealistic, photograph, photo, realistic, hyperrealistic, 3d render, cgi, '
    'octane render, live action, film still, depth of field, bokeh, camera, '
    'scary, creepy, horror, monster, dark, gloomy, gritty, grim, sad, crying, '
    'violence, weapon, blood, '
    'text, letters, words, numbers, writing, caption, subtitle, logo, watermark, '
    'signature, cluttered, busy background, intricate detail, ornate, '
    'ugly, deformed, distorted, low quality, blurry'
)

FFMPEG = exe('ffmpeg', required=False) or 'ffmpeg'  # resolve lazily: importing must not need ffmpeg
FFPROBE = '/usr/bin/ffprobe'

_COMFY_ROOT = str(_paths.ZYG_COMFY_ROOT)
_KLEIN_DISTILLED = 'flux-2-klein-4b.safetensors'
_KLEIN_BASE = 'flux-2-klein-base-4b.safetensors'

VOICE_POOL_DIR = os.path.join(CREWS, 'data', 'assets', 'voice_seeds', 'pool')
VOICE_POOL = (
    'f01_warm_alto',
    'f02_bright_clear',
    'f03_british_poised',
    'f04_elder_gentle',
    'f05_soft_intimate',
    'f06_young_light',
    'f07_low_smoky',
    'f08_crisp_journalist',
    'm01_warm_baritone',
    'm02_bright_tenor',
    'm03_elder_gravel',
    'm04_british_crisp',
    'm05_soft_intimate',
    'm06_young_earnest',
    'm07_dark_resonant',
    'm08_wry_mid',
)

SFX_KINDS = ('pop', 'ding', 'whoosh', 'engine', 'train', 'plane', 'horn', 'splash', 'bell', 'tick')

SR = 48000


def _log_noop(_m):
    pass
