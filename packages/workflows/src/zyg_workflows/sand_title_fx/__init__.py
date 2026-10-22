# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Words written in the sand, proved by OCR, then swirled into being.

The title card for the Video Studio intro is not a font composited over a
plate: the letters are *in* the picture, raised out of the same golden sand the
ground is made of, lit by the same sun. Qwen-Image-Edit-2511 is the only model
on this path that can write real words, and even it misspells — so nothing here
trusts a render. Every candidate is read back with the local OCR engine
(``typography_ocr``, PP-OCR, CPU, free) and a seed only wins when what the
engine reads, normalised, is *exactly* the words that were asked for. Best-of-N
against a measurement, not against a vibe.

Three pieces:

``write_words_in_sand``  N seeds through the edit graph, OCR gate, early exit
                         on the first exact hit, the winner pasted back onto
                         the full-resolution plate through the letter mask so
                         the untouched sand stays as sharp as it was rendered.
``letters_mask``         where the edit actually changed the picture — the
                         letters and nothing else.
``swirl_in``             the reveal: grains of the plate's own sand blown in
                         from a band around the letters, each one homing on a
                         pixel of the mask, while the base crossfades to the
                         written frame inside the mask only.

Licence: Qwen-Image-2512 / Qwen-Image-Edit-2511 are Apache-2.0, PP-OCR
(rapidocr-onnxruntime) Apache-2.0, x264 encoding through the system ffmpeg.
No FLUX on this path.

CLI
---
    sand_title_fx.py --selftest                      # CPU only, no ComfyUI
    sand_title_fx.py --src P --words 'Zygomatic Ai' --out W.png --only-write
    sand_title_fx.py --src P --words W.png --out S.mp4 --only-swirl --hold 1.0
    sand_title_fx.py --receipt                       # the GPU receipt, end to end
"""

from __future__ import annotations

import argparse
import difflib
import json
import os
import re
import subprocess
import sys
import tempfile

import cv2
import numpy as np
from PIL import Image
from zyg_workflows.bin import exe
import logging as _zyg_logging

# This module keeps the original docstring and the original top import block, so that every
# old `sand_title_fx.<name>` attribute access still resolves, and re-exports every name the
# single file defined; none of it is used here, so the surface is declared in `__all__`.

# 2026-10-07 modularization: the 1,286-line sand_title_fx.py became this package, cut at
# its own section banners. The submodules are imported in the single file's section
# order, so module-level side effects still happen in that order.
from zyg_workflows.sand_title_fx.constants import (
    HERE,
    RECEIPT_DIR,
    INSTRUCTION,
    EXTRA_INSTRUCTION,
    NEGATIVE,
    PLATE_PROMPT,
    CROP_PAD_FRAC,
    CROP_UPSCALE,
    DIFF_THRESH,
    DILATE_PX,
    MIN_COMP_FRAC,
    BAND_FRAC,
    N_PARTICLES,
    STREAK_PX,
    GRAIN,
    FONT,
    EMBOSS_DILATE_PX,
    EMBOSS_RELIEF,
    EMBOSS_FILL,
    EMBOSS_SHADOW,
    EMBOSS_SHADOW_PX,
    EMBOSS_SHADOW_SIGMA,
    EMBOSS_HEIGHT_SIGMA,
    EMBOSS_SAMPLE_PX,
    EMBOSS_GRAIN,
    EMBOSS_TRACK_FRAC,
    EMBOSS_MAX_WIDTH_FRAC,
    EMBOSS_TOP_SCALE,
    RAMP_PARTICLES,
    RAMP_BAND_FRAC,
    RAMP_STREAK_PX,
    RAMP_GRAIN_PX,
    RAMP_GRAIN_MUL,
    RAMP_HAZE_PEAK,
    RAMP_HAZE_AT,
    RAMP_RELIEF_START,
    _log,
)
from zyg_workflows.sand_title_fx.ocr_gate import (
    normalise,
    read_words,
    _regions,
    lettering_crop,
    _prefix_gap,
    VLM_PREAMBLE,
    VLM_QUESTION,
    VLM_MIN_FREE_MIB,
    _QUOTE_RE,
    _gpu_free_mib,
    _quotes,
    vlm_read_lettering,
    vlm_confirms,
    judge_lettering,
)
from zyg_workflows.sand_title_fx.letters import (
    _luma,
    letters_mask,
    _paste_letters,
    _ensure_comfy_env,
    render_plate,
    _score,
    write_words_in_sand,
)
from zyg_workflows.sand_title_fx.emboss import (
    _unit,
    _emboss_dilate,
    emboss_text_mask,
    emboss_cache,
    emboss_apply,
    emboss_words,
    write_words_any,
)
from zyg_workflows.sand_title_fx.reveal import (
    _smoothstep,
    _ease_io,
    _band,
    _haze_env,
    _haze_field,
    _grain_layer,
    swirl_in,
    _streaks,
    _ffmpeg,
)
from zyg_workflows.sand_title_fx.cli import (
    _fake_plate,
    _fake_words,
    selftest,
    _read_frames,
    _mp4_frames,
    receipt,
    main,
)

_zyg_log = _zyg_logging.getLogger(__name__)

# Every name imported above is re-exported, not used here: this package IS the module
# the split replaced, so `__all__` declares the surface instead of a file-level noqa.
__all__ = [
    'argparse',
    'difflib',
    'json',
    'os',
    're',
    'subprocess',
    'sys',
    'tempfile',
    'cv2',
    'np',
    'Image',
    'exe',
    'HERE',
    'RECEIPT_DIR',
    'INSTRUCTION',
    'EXTRA_INSTRUCTION',
    'NEGATIVE',
    'PLATE_PROMPT',
    'CROP_PAD_FRAC',
    'CROP_UPSCALE',
    'DIFF_THRESH',
    'DILATE_PX',
    'MIN_COMP_FRAC',
    'BAND_FRAC',
    'N_PARTICLES',
    'STREAK_PX',
    'GRAIN',
    'FONT',
    'EMBOSS_DILATE_PX',
    'EMBOSS_RELIEF',
    'EMBOSS_FILL',
    'EMBOSS_SHADOW',
    'EMBOSS_SHADOW_PX',
    'EMBOSS_SHADOW_SIGMA',
    'EMBOSS_HEIGHT_SIGMA',
    'EMBOSS_SAMPLE_PX',
    'EMBOSS_GRAIN',
    'EMBOSS_TRACK_FRAC',
    'EMBOSS_MAX_WIDTH_FRAC',
    'EMBOSS_TOP_SCALE',
    'RAMP_PARTICLES',
    'RAMP_BAND_FRAC',
    'RAMP_STREAK_PX',
    'RAMP_GRAIN_PX',
    'RAMP_GRAIN_MUL',
    'RAMP_HAZE_PEAK',
    'RAMP_HAZE_AT',
    'RAMP_RELIEF_START',
    '_log',
    'normalise',
    'read_words',
    '_regions',
    'lettering_crop',
    '_prefix_gap',
    'VLM_PREAMBLE',
    'VLM_QUESTION',
    'VLM_MIN_FREE_MIB',
    '_QUOTE_RE',
    '_gpu_free_mib',
    '_quotes',
    'vlm_read_lettering',
    'vlm_confirms',
    'judge_lettering',
    '_luma',
    'letters_mask',
    '_paste_letters',
    '_ensure_comfy_env',
    'render_plate',
    '_score',
    'write_words_in_sand',
    '_unit',
    '_emboss_dilate',
    'emboss_text_mask',
    'emboss_cache',
    'emboss_apply',
    'emboss_words',
    'write_words_any',
    '_smoothstep',
    '_ease_io',
    '_band',
    '_haze_env',
    '_haze_field',
    '_grain_layer',
    'swirl_in',
    '_streaks',
    '_ffmpeg',
    '_fake_plate',
    '_fake_words',
    'selftest',
    '_read_frames',
    '_mp4_frames',
    'receipt',
    'main',
]
