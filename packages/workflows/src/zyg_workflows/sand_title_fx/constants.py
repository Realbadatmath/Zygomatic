# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The dials: prompts, OCR-gate thresholds, emboss and relief-ramp constants, and the
logging helper — verbatim sections of the former sand_title_fx.py."""

from __future__ import annotations

import os

import logging as _zyg_logging

from zyg_workflows import paths

# channel kept from the pre-split module
_zyg_log = _zyg_logging.getLogger('zyg_workflows.sand_title_fx')


HERE = str(paths.PKG_DIR)
RECEIPT_DIR = os.path.join(HERE, 'output', 'video_studio', '_sandtitle')

INSTRUCTION = (
    'Write the words "{words}" in large raised letters formed from '
    'sand on the desert floor, the letters made of the same golden '
    'sand as the ground, centred in the picture, seen from this same '
    'angle and lighting, keep everything else in the picture '
    'identical.'
)
# Appended to the instruction by default (write_words_in_sand's
# extra_instruction=None means "this"): the failure this path actually has is a
# thin final lowercase letter fused into its neighbour, not a misspelling.
EXTRA_INSTRUCTION = (
    ', the letters thick, blocky and well separated, each '
    'letter clearly distinct, the final lowercase i clearly '
    'visible with its dot'
)
NEGATIVE = 'misspelled, extra letters, wrong letters, missing letters, watermark, logo, signature, people'

PLATE_PROMPT = (
    'close view of a flat desert floor of golden rippled sand seen '
    'from a low hovering angle, fine sand grains blowing across the '
    'ground, warm low sun from the left, long soft shadows, '
    'photoreal, no people, no animals, no text'
)

CROP_PAD_FRAC = 0.08  # padding around the lettering bbox before OCR
CROP_UPSCALE = 2
DIFF_THRESH = 12  # luma delta that counts as "the edit touched this"
DILATE_PX = 2
MIN_COMP_FRAC = 0.002  # 0.2 % of the frame
BAND_FRAC = 0.12  # spawn band / grain band around the letters
N_PARTICLES = 6000
STREAK_PX = 3
GRAIN = 4  # /255

FONT = '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf'

# ── the deterministic fallback's dials ──────────────────────────────────────
EMBOSS_DILATE_PX = 3 * DILATE_PX  # the "3x dilated" letter mask
EMBOSS_RELIEF = 40.0  # +- luma of the relief shading
EMBOSS_FILL = 0.80  # letters are denser, darker sand
EMBOSS_SHADOW = 0.60  # multiply under the cast shadow
EMBOSS_SHADOW_PX = 10  # how far the shadow falls from the letters
EMBOSS_SHADOW_SIGMA = 6.0
EMBOSS_HEIGHT_SIGMA = 3.0  # height map = mask blurred by this
EMBOSS_SAMPLE_PX = 6  # sand for the letter fill, sampled up-left
EMBOSS_GRAIN = 5  # /255, inside the dilated mask only
EMBOSS_TRACK_FRAC = 0.08  # letter spacing, as a fraction of cap height
EMBOSS_MAX_WIDTH_FRAC = 0.84  # the words may not be wider than this
EMBOSS_TOP_SCALE = 0.92  # ground plane: top edge / bottom edge

# ── the relief-ramp reveal (swirl_in(relief_ramp=True)) ─────────────────────
RAMP_PARTICLES = 14000  # grains in flight; 6000 was invisible
RAMP_BAND_FRAC = 0.15  # spawn band, fraction of the frame
RAMP_STREAK_PX = 4  # motion-blur tail behind each grain
RAMP_GRAIN_PX = (2, 4)  # grain thickness, randint low..high
RAMP_GRAIN_MUL = 0.62  # grain colour = the plate's sand x this
RAMP_HAZE_PEAK = 0.35  # sand-haze alpha at its densest
RAMP_HAZE_AT = 0.55  # ...which happens this far through
RAMP_RELIEF_START = 0.35  # the letters only start rising here


def _log(fn, msg):
    if fn:
        try:
            fn(str(msg))
        except Exception as _exc:  # noqa: BLE001
            _zyg_log.debug('log callback raised, message dropped: %s', _exc)
    else:
        _zyg_log.info(msg)
