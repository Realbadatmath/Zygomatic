#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""char_photoreal.py — a photoreal skin texture for a Character Studio base body.

WHAT THIS BUILDS (2026-09-19)
=============================
The studio's 3D figure is the CC0 Blender Studio human base mesh in flat clay.
This module turns that base sculpt into a photoreal person WITHOUT touching the
geometry: the mesh's own depth plates drive the licensed depth-control render
route (FLUX.2 klein 4B + the Apache-2.0 RefControl adapter, the only clean
geometric-control path this repo has — see comfy_generation_service), the
photographs that come back are projected through the very cameras that drew
the plates into the body's UV space, and the result is ONE albedo atlas the
studio applies to the same mesh. Compare then shows clay base against the
photoreal skin on identical geometry — which is the whole point: the shape is
the base sculpt's, the skin (pores, freckles, lips, brows) is painted.

STAGES, each resumable from disk under output/photoreal/<body>/:
  plates   Blender (Cycles, CPU) renders every view of the GLB: an RGB beauty
           (grey), a Z pass in metres, an object-index pass, and dumps the
           camera intrinsics/extrinsics plus the body's WORLD-SPACE loop
           triangles with their UVs (geom.npz). Geometry is taken from the
           same Blender scene the cameras live in, so no up-axis or node
           hierarchy guess can put the texture on the wrong side of the body.
  render   klein RefControl per view: depth plate as image 1 (geometry),
           an appearance reference as image 2. The chain that keeps one
           person across views AND facing the plate's way (REF_OF): seed
           portrait -> body front -> three-quarters -> profiles -> back
           three-quarters -> back; head front (ref = body front) -> the
           same fan-out; hands from the body front. Every view's prompt
           states its orientation (_view_prompt) and an orientation gate
           (Haar frontal-face count in the head box) rejects a photo that
           faces the wrong way — 2026-09-20 measured a frontal man on the
           back plate and a frontal face on every side/back head plate.
  bake     Projection. The atlas is rasterised in UV space (the body is UDIM:
           9 x 4 tiles, packed into a 6 x 4 grid of TILE px cells, see
           tile_grid()); every texel knows its world point + normal; each
           view contributes where the texel is visible (Z-pass test, eroded
           away from silhouettes), weighted by facing and by pixel density
           (f/z)^2 so a head close-up outranks the full-body view on the
           face. Per-view colour gain is matched to the primary view over
           the shared texels before blending, holes are filled by diffusion,
           islands are padded.
  publish  data/assets/mesh_packs/photoreal/<body>/albedo.jpg + manifest.json
           (served by the existing /inspect/arch-asset/ route).

BAKE LESSONS 2026-09-22 (five measured defects on the published atlas, each
reproduced by re-projecting texel subsets through every view before a fix):
  * DEPTH TEST is two-sided and tight: the plate IS the geometry, so a
    visible texel matches the Z pass within a millimetre; tol = 5 mm + 3 px
    of depth against the 3x3 min/max of the Z pass. The old one-sided 30 mm
    let head photos paint through lids and lips and let a finger side
    project into the gap between fingers (the plate shows the thigh there,
    the closed mask bridged the gap, the photo pixel was the black gap or
    the grey backdrop): the black caps on fingers/toes and the white chunks.
  * BAD PIXELS: a photo pixel that is near-black (L < 36, 3x3-opened so a
    stubble dot stays), not warm (R - B < 8 = backdrop), or white and
    neutral is no contribution. Per-pixel or blurred-L < 45 rules speckled
    the jaw and threw away the shaded side of every head photo — the
    head_back gain was then matched over 8k texels and read 0.72 —
    so GAIN_MIN_SHARED: a view with too little squarely-shared skin
    inherits its render parent's gain.
  * HOLES (nothing valid saw the texel, 5 % of the island) are filled from
    the 3D skin tone round them (12/30/60 mm), never inpainted: TELEA ran on
    an image that was black outside the covered texels and painted every
    island border that touched a hole dark — the "dark island rim" (L 110
    at the border vs 128 inside) entered at the inpaint, measured stage by
    stage. Padding is a plain nearest-texel dilation over the whole atlas.
  * MASK FEATHER in metres (15 mm on a body photo, smoothstep, bilinear
    distance transform of a median-smoothed mask) on the TONE band as well:
    the tone weight had no feather at all, so body_front's tone stopped
    dead on its mask's stair-steps at the hip.
  * HANDS: the hand photo owns the TONE inside HAND_RADIUS
    (HAND_TONE_PRIORITY), its gain is matched over the wrist band, and
    _equalise_hands pins the 20 mm tone of the hand to the forearm's after
    the desheen (which darkens every finger as a ridge, -10 levels).
  * FACE: a second mirror pass at 7 mm on the head only, biased to the
    brighter side; the 26 mm pass could not see socket-scale shading.
  * The high band of the two-band blend is a RATIO (col / own 12 mm tone,
    DETAIL_RATIO), not an offset: an additive pale sliver on the fingers
    desaturated the pinned hand tone to grey-olive (a* 5 where the forearm
    is 14); a ratio keeps the hue through every brightness detail.
  * Inside a mask feather the detail band blends LINEARLY by the feathered
    weights (no winner-takes-most there), so the hairy/smooth handover at
    torso_front's hip edge is a 15 mm ramp and not a sawtooth.
  * Texels no view passes strictly (perineum, armpit floor) take the LOOSE
    test (one-sided 30 mm depth, shadow allowed) before becoming holes —
    strict-only left 16 % of the crotch as flat-tone chunks. The TONE band
    takes strict and loose contributions alike (a view that sees a texel in
    shadow still knows its tone); a zoom frame's BORDER counts as a mask
    edge (legs_front painted L 163 at its top edge over the perineum).
  * A bright detail is hue-protected (DETAIL_HUE_BRIGHT: specular = grey)
    and _equalise_hands pins the hand's HUE at 6 mm as well as its tone at
    20 mm: klein's lit finger sides are pale and grey over ~10 mm.
  * No local gain field: tried twice, it compounds down the render chain
    and darkened the atlas by 8 levels (see the note in stage_bake).

VERIFIED BEFORE ANY GPU TIME: `selfcheck` re-projects the dumped triangles
into every view and demands that >= 97 % of front-facing, depth-visible
vertices land on the index mask. A camera convention error (sensor fit,
pixel origin, handedness) fails loudly here rather than as a texture that is
mysteriously mirrored.

CLI:
    python3 char_photoreal.py male_realistic                # all stages
    python3 char_photoreal.py male_realistic --stage plates
    python3 char_photoreal.py male_realistic --stage bake --force
    python3 char_photoreal.py male_realistic --job output/charstudio_jobs/<id>
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

import numpy as np
import logging as _zyg_logging

from zyg_workflows import paths

from zyg_workflows.char_photoreal import constants as constants
from zyg_workflows.char_photoreal import plates as plates
from zyg_workflows.char_photoreal import renders as renders
from zyg_workflows.char_photoreal import atlas as atlas
from zyg_workflows.char_photoreal import equalise as equalise
from zyg_workflows.char_photoreal import bake as bake
from zyg_workflows.char_photoreal import publish as publish

from zyg_workflows.char_photoreal.constants import (
    HERE as HERE,
    PACK_DIR as PACK_DIR,
    OUT_ROOT as OUT_ROOT,
    PUB_ROOT as PUB_ROOT,
    BLENDER as BLENDER,
    _DOCS_DIR as _DOCS_DIR,
    BODIES as BODIES,
    look_of as look_of,
    BODY_VIEWS as BODY_VIEWS,
    HEAD_VIEWS as HEAD_VIEWS,
    HAND_VIEWS as HAND_VIEWS,
    EYE_VIEWS as EYE_VIEWS,
    ZOOM_VIEWS as ZOOM_VIEWS,
    EYE_RADIUS as EYE_RADIUS,
    DETAIL_KINDS as DETAIL_KINDS,
    REF_OF as REF_OF,
    GAIN_OF as GAIN_OF,
    HAND_RADIUS as HAND_RADIUS,
    HAND_TONE_PRIORITY as HAND_TONE_PRIORITY,
    BAD_DARK_L as BAD_DARK_L,
    BAD_WHITE_L as BAD_WHITE_L,
    BAD_WHITE_CHROMA as BAD_WHITE_CHROMA,
    BAD_NEUTRAL_RB as BAD_NEUTRAL_RB,
    GAIN_MIN_SHARED as GAIN_MIN_SHARED,
    GAIN_MIN_SHARED_HAND as GAIN_MIN_SHARED_HAND,
    DETAIL_RATIO as DETAIL_RATIO,
    DETAIL_HUE_BRIGHT as DETAIL_HUE_BRIGHT,
    FEATHER_M_VIEW as FEATHER_M_VIEW,
    TONE_YIELD_VIEWS as TONE_YIELD_VIEWS,
    LOOSE_Z_TOL as LOOSE_Z_TOL,
    TONE_MIN_SUPPORT as TONE_MIN_SUPPORT,
    BAD_DARK_OPEN_M as BAD_DARK_OPEN_M,
    FEATHER_M as FEATHER_M,
    PRIORITY as PRIORITY,
    SIZE as SIZE,
    TILE as TILE,
    STEPS as STEPS,
    CFG as CFG,
    log_to as log_to,
)
from zyg_workflows.char_photoreal.plates import (
    _BL_SCRIPT as _BL_SCRIPT,
    work_dir as work_dir,
    _run_blender as _run_blender,
    _copy_plates as _copy_plates,
    stage_plates as stage_plates,
    Cam as Cam,
    load_geom as load_geom,
    _sample_nearest as _sample_nearest,
    stage_selfcheck as stage_selfcheck,
)
from zyg_workflows.char_photoreal.renders import (
    ECORCHE_LIGHT as ECORCHE_LIGHT,
    ECORCHE_GROUPS_FRONT as ECORCHE_GROUPS_FRONT,
    ECORCHE_GROUPS_BACK as ECORCHE_GROUPS_BACK,
    ECORCHE_HEAD_FRONT as ECORCHE_HEAD_FRONT,
    ECORCHE_HEAD_BACK as ECORCHE_HEAD_BACK,
    _prompts_ecorche as _prompts_ecorche,
    _prompts as _prompts,
    _view_prompt_ecorche as _view_prompt_ecorche,
    _view_prompt as _view_prompt,
    _render_one as _render_one,
    _head_box as _head_box,
    _frontal_faces as _frontal_faces,
    _silhouette_iou as _silhouette_iou,
    IOU_MIN as IOU_MIN,
    _orientation_gate as _orientation_gate,
    _render_view as _render_view,
    _ecorche_ref_seed as _ecorche_ref_seed,
    stage_render as stage_render,
    _depth_in_chain as _depth_in_chain,
    _photo_foreground as _photo_foreground,
)
from zyg_workflows.char_photoreal.atlas import (
    tile_grid as tile_grid,
    atlas_uv as atlas_uv,
    _cell_slice as _cell_slice,
    _seam_mask as _seam_mask,
    _seam_twins as _seam_twins,
    _seam_report as _seam_report,
    rasterise as rasterise,
    _bilinear as _bilinear,
    _partner as _partner,
    _symmetrise as _symmetrise,
    _pad_islands as _pad_islands,
)
from zyg_workflows.char_photoreal.equalise import (
    Vox as Vox,
    _equalise_mirror as _equalise_mirror,
    _equalise_hands as _equalise_hands,
    _detail_ratio as _detail_ratio,
    _nearest_fill as _nearest_fill,
    _desheen3d as _desheen3d,
    _tile_texel_m as _tile_texel_m,
    _desheen as _desheen,
    _equalise_pairs as _equalise_pairs,
    _equalise_halves as _equalise_halves,
    _sh_basis as _sh_basis,
    _smooth_normals as _smooth_normals,
    _delight as _delight,
)
from zyg_workflows.char_photoreal.bake import (
    stage_bake as stage_bake,
)
from zyg_workflows.char_photoreal.publish import (
    stage_publish as stage_publish,
    PREVIEW_PANEL as PREVIEW_PANEL,
    stage_previews as stage_previews,
    published as published,
    JobLog as JobLog,
    run_all as run_all,
    main as main,
)


# Every name below is imported above and not used in this module: this package
# IS the re-export surface of the pre-split module, so the imports are the
# deliberate public surface, not dead weight.  Nothing does ``import *`` from
# here, so __all__ changes no behaviour.
__all__ = [
    'argparse',
    'json',
    'os',
    'shutil',
    'subprocess',
    'sys',
    'tempfile',
    'time',
    'np',
    'paths',
]

_zyg_log = _zyg_logging.getLogger(__name__)
