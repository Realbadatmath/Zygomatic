# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

# ruff: noqa: F401 — the shared namespace: these imports exist for the sibling modules.
"""storyteller_scene_service.constants — module-level imports, paths and tuning constants (lines 31-95).

Moved verbatim out of the old single-file storyteller_scene_service.py.
"""

from __future__ import annotations

import json
import logging as _zyg_logging
import math
import os
import shutil
import subprocess
import time
import zlib

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

from zyg_workflows import paths
from zyg_workflows.bin import exe

_zyg_log = _zyg_logging.getLogger(__name__)

# THE ONE LINE THE SPLIT HAD TO CHANGE: this module sits one directory deeper
# than the old storyteller_scene_service.py, so a single dirname() of __file__
# would point at the package instead of zyg_workflows/ and every asset path
# below it would move. The extra dirname() keeps _CREWS — and therefore
# _OUT_ROOT, the five asset-library dirs, _POOL_DIR and _ROOT_ENV — byte-equal
# to what the single file resolved.
_CREWS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Standalone runs need the same env the GUI loads (ZYG_USE_COMFYUI etc.) —
# mirror crewai_web_gui's root-.env dotenv load, never overriding real env.
_ROOT_ENV = os.path.normpath(os.path.join(_CREWS, '..', '..', '.env'))
try:
    from dotenv import load_dotenv as _load_dotenv

    if os.path.isfile(_ROOT_ENV):
        _load_dotenv(_ROOT_ENV, override=False)
except ImportError as _exc:
    _zyg_log.warning('root .env load skipped, continuing with the real environment only: %s', _exc)
_OUT_ROOT = os.path.join(_CREWS, 'output', 'storyteller')
_SFX_DIR = os.path.join(_CREWS, 'data', 'asset_libraries', 'sfx')
_VOCAL_DIR = os.path.join(_CREWS, 'data', 'asset_libraries', 'vocal_fx')
_FOLEY_DIR = os.path.join(_CREWS, 'data', 'asset_libraries', 'foley')
_MUSIC_DIR = os.path.join(_CREWS, 'data', 'asset_libraries', 'soundtracks')
# merged (2026-08-25): files saved from the SFX Merger — resolved LAST, so a
# merge can never shadow a library name.
_MERGED_DIR = os.path.join(_CREWS, 'data', 'asset_libraries', 'merged')
# instruments (2026-09-02): sampled musical-instrument notes — resolved LAST
# alongside merged, so a bed / vocal / foley name can never be shadowed by a
# note file that happens to share it.
_INSTR_DIR = os.path.join(_CREWS, 'data', 'asset_libraries', 'instruments')
# Where a bare `sfx:` / `bed:` filename is looked up, in order. sfx first so the
# ambience beds keep resolving exactly as before; vocal_fx is the mouth-noise
# library, which is a SEPARATE category (see asset_library_service) but shares
# one flat namespace here so a spec never has to name the category.
# foley (2026-08-25) is the one-shot library — weapons, impacts, gore, object
# recordings — resolved last so an existing bed or vocal name always wins.
_AUDIO_DIRS = (_SFX_DIR, _VOCAL_DIR, _FOLEY_DIR, _MERGED_DIR, _INSTR_DIR)
_POOL_DIR = os.path.join(_CREWS, 'data', 'assets', 'voice_seeds', 'pool')
_FONT_PATH = '/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf'

_SR = 48000
_FPS = 24
# Below this zoom a still is framed at delivery size: a 5 % Ken Burns drift does
# not justify an ESRGAN pass, and LANCZOS is indistinguishable at that scale.
_HIRES_MIN = 1.15
# RealESRGAN x4 weights, resolved once at import (see _esrgan_resize).
_ESRGAN_WEIGHTS = str(paths.ZYG_REALESRGAN_ROOT / 'RealESRGAN_x4plus.pth')


def _log_noop(msg):
    pass
