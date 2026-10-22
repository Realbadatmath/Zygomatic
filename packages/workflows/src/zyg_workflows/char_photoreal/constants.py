#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""char_photoreal — the constants section, verbatim lines 115-364 of the original module."""

# What is left of the original module's top import block: the names this section
# actually uses. argparse/json/shutil/subprocess/tempfile/time/numpy came along in
# the verbatim move but no sibling re-imports them from here and the package
# __init__ imports its own copies, so they are gone.

from __future__ import annotations

import os
import sys

import logging as _zyg_logging

from zyg_workflows import paths

_zyg_log = _zyg_logging.getLogger(__package__)


# One extra dirname(): this module now sits inside the char_photoreal/ package,
# one level below the char_photoreal.py it was split out of. HERE keeps the
# original value, .../src/zyg_workflows.
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

PACK_DIR = os.path.join(HERE, 'data', 'assets', 'mesh_packs', 'blender_human_base', 'glb')
OUT_ROOT = os.path.join(HERE, 'output', 'photoreal')
PUB_ROOT = os.path.join(HERE, 'data', 'assets', 'mesh_packs', 'photoreal')
BLENDER = str(paths.BLENDER_BIN)
#: Operator anatomy plates, outside the package tree.
_DOCS_DIR = paths.ZYG_HOME / 'Documents'

BODIES = {
    'male_realistic': {'file': 'coll_body_male_realistic.glb', 'gender': 'male'},
    'female_realistic': {'file': 'coll_body_female_realistic.glb', 'gender': 'female'},
    'male_stylized': {'file': 'coll_body_male_stylized.glb', 'gender': 'male'},
    'female_stylized': {'file': 'coll_body_female_stylized.glb', 'gender': 'female'},
    # ÉCORCHÉ (2026-09-23): the same CC0 meshes, painted with the muscular
    # system instead of skin. 'look' switches the reference, the prompts, the
    # frontal-face gate and the published bump map; 'plates_from' reuses
    # another body's Blender output (identical mesh, identical cameras).
    # 'ref' is the operator's anatomy plate: half skeleton, half muscle —
    # 'ref_muscle_half' says which side of the split the muscle is on.
    'male_ecorche': {
        'file': 'coll_body_male_realistic.glb',
        'gender': 'male',
        'look': 'ecorche',
        'plates_from': 'male_realistic',
        'ref': str(_DOCS_DIR / 'perfect skeleton and muscl e packs.jpg'),
        'ref_muscle_half': 'right',
    },
    'female_ecorche': {
        'file': 'coll_body_female_realistic.glb',
        'gender': 'female',
        'look': 'ecorche',
        'plates_from': None,
        'ref': str(_DOCS_DIR / 'female skeleton and muscle packs.png'),
        'ref_muscle_half': 'right',
    },
}


def look_of(body):
    """'ecorche' or '' — every look branch in this module keys on this."""
    return BODIES.get(body, {}).get('look') or ''


# az 0 = the FRONT (camera on -Y looking +Y in Blender), az grows toward +X —
# the geom/mv_render turntable convention body_plates.py also follows.
BODY_VIEWS = {
    'body_front': {'az': 0, 'el': 0},
    'body_fl': {'az': -45, 'el': 0},
    'body_fr': {'az': 45, 'el': 0},
    'body_left': {'az': -90, 'el': 0},
    'body_right': {'az': 90, 'el': 0},
    'body_bl': {'az': -135, 'el': 0},
    'body_br': {'az': 135, 'el': 0},
    'body_back': {'az': 180, 'el': 0},
    'body_top': {'az': 0, 'el': 55},
    'body_low': {'az': 0, 'el': -40},
}
HEAD_VIEWS = {
    'head_front': {'az': 0, 'el': 0},
    'head_fl': {'az': -40, 'el': 0},
    'head_fr': {'az': 40, 'el': 0},
    'head_left': {'az': -90, 'el': 0},
    'head_right': {'az': 90, 'el': 0},
    'head_back': {'az': 180, 'el': 0},
    'head_up': {'az': 0, 'el': 35},
    'head_down': {'az': 0, 'el': -30},
}
# Hand close-ups (2026-09-20): klein paints hands dark red in every body view
# and they are small there; a dedicated view per hand, from the outside
# (camera on the hand's own side), sees the back of the hand at head-like
# pixel density. Subject's left hand is at +X (the body faces -Y), so its
# camera sits at az +90.
HAND_VIEWS = {'hand_l': {'az': 90, 'el': 0}, 'hand_r': {'az': -90, 'el': 0}}
# Eye close-ups (2026-09-20): the lid line and lashes need a photo whose
# plate-following error is a fraction of a millimetre, and the head close-up
# is 0.25 mm/px with a few px of drift. One straight-on view per eye, 0.10 m
# extent, confined to the socket in the bake.
EYE_VIEWS = {'eye_l': {'az': 0, 'el': 0}, 'eye_r': {'az': 0, 'el': 0}}
# Body close-ups (2026-09-20): the full-length photos are ~1.7 mm/px, four
# times coarser than the atlas, so body skin had no pores at all. Torso and
# legs, front/back/sides, at ~0.6 mm/px. Targets are fractions of the
# body height (see the Blender script).
ZOOM_VIEWS = {
    'torso_front': {'az': 0, 'el': 0},
    'torso_back': {'az': 180, 'el': 0},
    'torso_left': {'az': -90, 'el': 0},
    'torso_right': {'az': 90, 'el': 0},
    'legs_front': {'az': 0, 'el': 0},
    'legs_back': {'az': 180, 'el': 0},
}
EYE_RADIUS = (0.035, 0.05)
# Views that contribute DETAIL only: their tone (low band) is taken from the
# body/head photos that already cover the same skin, so a close-up never
# shows as a patch of its own exposure (measured 2026-09-20: a pale band
# round each eye where the eye photo's zone ended, dark hands before that).
DETAIL_KINDS = ('eye', 'hand', 'torso', 'legs')
# Which already-rendered photo is the APPEARANCE reference (RefControl image
# 2) for each view. 2026-09-20: with the frontal photo as the reference for
# every view AND a prompt that said "looking straight ahead", klein painted a
# frontal man on the back plate and a frontal face on every head plate but
# the front — the depth plate of a back is a featureless blob and the model
# followed the reference and the prompt instead (measured: body_back = a
# front with nipples and navel; head_left/right/back/up/down = the same
# frontal portrait; the bake then put a second front on his back and a face
# on each side of his head). So each view is referenced from its NEAREST
# rendered neighbour, never more than 45-50 degrees away, and the reference
# agrees with the plate about which way the man faces.
REF_OF = {
    'body_front': 'ref_seed',
    'body_fl': 'body_front',
    'body_fr': 'body_front',
    'body_left': 'body_fl',
    'body_right': 'body_fr',
    'body_bl': 'body_left',
    'body_br': 'body_right',
    'body_back': 'body_bl',
    'body_top': 'body_front',
    'body_low': 'body_front',
    'head_front': 'body_front',
    'head_fl': 'head_front',
    'head_fr': 'head_front',
    'head_left': 'head_fl',
    'head_right': 'head_fr',
    'head_back': 'head_left',
    'head_up': 'head_front',
    'head_down': 'head_front',
    'hand_l': 'body_front',
    'hand_r': 'body_front',
    'eye_l': 'head_front',
    'eye_r': 'head_front',
    'torso_front': 'body_front',
    'torso_back': 'body_back',
    'torso_left': 'body_left',
    'torso_right': 'body_right',
    'legs_front': 'body_front',
    'legs_back': 'legs_front',
}
# legs_back is referenced from legs_front, not body_back: with the full-figure
# back photo as reference klein painted a whole figure into the legs-only
# frame (silhouette IoU 0.17, twice, seed-stable); a legs-framed reference
# keeps the framing and the prompt/plate keep the orientation.
# Which view a photo's EXPOSURE is matched to in the bake. 2026-09-20: matching
# every view to body_front left the three back-family views with NO shared
# squarely-seen texels (gain 1.0 = unmatched) and both profiles on their
# clamps; with winner-takes-most every ownership boundary between two
# mismatched photos became a hard step (blocks on the upper arms, thighs and
# back). So the match runs along the render chain, parent first, each step
# no more than 45-90 degrees apart with plenty of overlap; the hands match
# the profile that looks the same way (hand_l az +90 = body_right).
GAIN_OF = dict(REF_OF, hand_l='body_right', hand_r='body_left')
# a hand view paints ONLY the hand: its frame also holds the thigh and the
# forearm at 20x the body view's pixel density and would own them
HAND_RADIUS = (0.14, 0.20)  # metres from the hand centre: full weight .. none
# inside HAND_RADIUS the hand photo owns the TONE as well as the detail
# (2026-09-22): its tone weight against a body photo's cos^2
HAND_TONE_PRIORITY = 30.0
# a photo pixel darker than this is background, deep shadow or a bridged
# gap, never skin; brighter AND neutral is backdrop or a specular chunk
BAD_DARK_L, BAD_WHITE_L, BAD_WHITE_CHROMA, BAD_NEUTRAL_RB = 36.0, 232.0, 36, 8
# a view's exposure ratio to its parent is trusted only over this many
# squarely-shared texels; below it the parent's gain is inherited
GAIN_MIN_SHARED = 40000
GAIN_MIN_SHARED_HAND = 8000  # the wrist band is small
DETAIL_RATIO = (0.4, 2.5)  # the high band of the two-band blend is a RATIO to the view's own tone
DETAIL_HUE_BRIGHT = (0.94, 1.06)  # per-channel hue drift a BRIGHT detail may carry (specular = grey)
# a diagonal body photo is rim-lit along its own silhouette (measured on
# the thigh: body_fr L 172-208 where torso_right reads 128-161), so its
# weight feathers out over a longer distance than the axial views'
FEATHER_M_VIEW = {'body_fl': 0.025, 'body_fr': 0.025}
# views whose TONE yields to any other view's coverage (rim-lit flanks).
# Tried with the three-quarter body views 2026-09-23: the hip-crest patch
# got WORSE (body_fr-owned crest vs torso_front 20 mm inside: +8.1 levels
# against +4.9 with their tone in), because without them the crest's tone
# falls to body_front's grazing silhouette strip, which is paler still.
# Left empty; the lever stays for a body whose diagonals are the problem.
TONE_YIELD_VIEWS = ()
# below this share of the strict coverage a texel falls back to the LOOSE
# test (one-sided 30 mm depth, no dark rule) — the perineum, the armpit
LOOSE_Z_TOL = 0.03
TONE_MIN_SUPPORT = 0.01  # strict tone weight below this = only a detail view's token
BAD_DARK_OPEN_M = 0.006  # a dark region narrower than this is shading, not a gap
# every view's weight (detail AND tone) feathers to zero over this many
# metres before its photo-mask edge, per view kind; a hand or eye frame is
# 0.1-0.2 mm/px and its features are a finger wide, so a shorter feather
FEATHER_M = {'body': 0.015, 'torso': 0.015, 'legs': 0.015, 'head': 0.010, 'hand': 0.004, 'eye': 0.004}
# Which photo OWNS a region when several see it. The primary of each family
# is the one photo the others were referenced from, so it is the least
# drifted; a diagonal is a filler for what the axial views miss. The head
# views already outrank the body views on the face through pixel density.
PRIORITY = {
    'body_front': 20,
    'body_back': 20,
    'body_left': 4,
    'body_right': 4,
    'body_fl': 1,
    'body_fr': 1,
    'body_bl': 1,
    'body_br': 1,
    'body_top': 0.3,
    'body_low': 0.3,
    'head_front': 200,
    'head_back': 10,
    'head_left': 12,
    'head_right': 12,
    'head_fl': 1.5,
    'head_fr': 1.5,
    'head_up': 0.1,
    'head_down': 0.1,
    'hand_l': 2,
    'hand_r': 2,
    'eye_l': 50,
    'eye_r': 50,
    'torso_front': 30,
    'torso_back': 30,
    'torso_left': 6,
    'torso_right': 6,
    'legs_front': 30,
    'legs_back': 30,
}
SIZE = 1024  # render size, square
TILE = 1024  # atlas texels per UDIM tile (the face lives in one)
STEPS = 20
CFG = 3.5


def log_to(fn):
    return fn or (lambda m: _zyg_log.info(m))
