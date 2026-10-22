# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""ground_v3 — ONE sculpted heightfield per drawing (2026-09-07).

Before v3 every landform was a separate SOLID added on top of a flat base, so a
valley came out as a raised plinth, a canyon as two cones on a lawn, and each
solid was one flat colour that never blended into its neighbour. v3 turns that
inside out: the drawing has ONE `ground` record, and every feature is a SCULPT —
a void record that is a *parameter of the ground*, not a thing standing on it.

    H(lx, lz) = base + amp * vnoise(lx, lz, seed)
                + SUM over every sculpt_* record in the drawing of its
                  contribution at the same WORLD point

Because a cut is a term in that sum, a valley is a valley. Because every
contribution feathers smoothly to 0 at its rim, a peak grows out of the land
instead of being parked on it. Because the whole thing is ONE mesh, it can be
grass on the flat, rock on the steep face, sand at the water and snow on top at
the same time, from the studio's own material hexes.

THE ARITHMETIC IS A CONTRACT. `value_noise`, `smoothstep`, `meander_offset`,
`lake_factor`, the ten sculpt functions, `field_at`, `height_at` and
`colour_weights` below are byte-for-byte the same arithmetic as arch_ext/
ground_v3.js (the tab) and arch_blender_ext/ground_v3.py (Blender). Change one
copy and you have three landscapes. The hash/vnoise pair is copied verbatim
from arch_ext/terrain.js, and `meander_offset` / `lake_factor` verbatim from
arch_assistant_ext/rivers_lakes.py, so a sculpt_channel is the same wander as
the river drawn over it and a sculpt_basin the same shoreline as its lake.

EVERY SCULPT FUNCTION RETURNS (dh, mask):
  · `dh`   metres to add to H at that point (negative for a cut/basin/shelf);
           for a SET sculpt it is the LEVEL instead. Two sculpts are SET:
           `sculpt_flat` always, and a `sculpt_channel` that names level0 AND
           level1 (a riverbed set to a straight fall, not dug `depth` below the
           roll it crosses — see channel_levels).
  · `mask` 0..1, how much of the sculpt is felt there: 1 at its heart, 0 at its
           rim. It is what makes the record's own `y` shift a raise's base
           without leaving a step at the rim (H += dh + y*mask), and what tells
           the colour a vertex is inside a dune field or a sea bed (sand).

The SET sculpts are applied LAST, after every raise and cut:
    H = H*(1 - mask) + level*mask
and its mask is the SAME arithmetic as arch_assistant._sculpt_flat_weight, so
`pad_level()` re-applying it on top of this ground is exactly idempotent — the
building pads the buildings-on-ground seam writes are already part of H.

VOID KINDS. The ten sculpt kinds are void: the tab draws only a thin outline of
their footprint at y = 0.05 so the operator can select and move them, and the
Blender builder returns an empty mesh. The ground mesh is the only geometry.
`tests_arch_ext/test_all.py` keeps its own VOID_KINDS = {'opening'}; this module
exports VOID_KINDS for the sweep to union in (test_all.py is not ours to edit).

REAL SIZES. The tools refuse what is not a landform: a peak is 0.25-1.0 x its
radius tall (steeper is a needle, flatter is a hill), a mesa's top is at most
0.8 x its radius, a trough is at most 0.4 x its width deep. One ground per
drawing, at most 200 lattice cells a side (40 401 vertices, ~80 000 triangles).
"""

# This package IS the re-export surface of the old single file: every name it
# defined must stay an attribute of the same import path.

from __future__ import annotations

import math

from zyg_workflows.arch_assistant import (
    Drawing,
    parse_cell,
    cell_name,
    cell_of,
    block_bounds,
    MATERIALS,
    MAX_OBJECTS,
    _num,
    footprint_level,
    sculpts_of,
    current_drawing,
)

from .constants import (
    KINDS,
    OPENINGS,
    VOID_KINDS,
    SAND_KINDS,
    PROMPT,
    RES_MAX,
    RES_MIN,
    BASE_CELL,
    FEATHER_FRAC,
    COLOUR_BAND,
    SLOPE_BAND,
    WATER_SOIL,
    COLOUR_MATS,
    STYLE_AMP,
    PEAK_H_FRAC,
    MESA_H_FRAC,
    TROUGH_FRAC,
    LEVEL_BATTER,
)

from .field import (
    _hash,
    value_noise,
    meander_offset,
    lake_factor,
    clamp,
    smoothstep,
    band,
    feather_of,
    _N,
    s_peak,
    s_ridge,
    s_mesa,
    s_cut,
    channel_levels,
    s_channel,
    s_basin,
    s_flat,
    s_step,
    s_dunes,
    s_shelf,
    SCULPTS,
    base_height,
    field_at,
    height_at,
    lattice,
    slope_deg,
    colour_weights,
    studio_rgb,
    colour_at,
    ground_record,
    h_ground,
    HEIGHTS,
)

from .tools import (
    the_ground,
    _mat,
    _block,
    _res_for,
    t_make_ground,
    _need_ground,
    _sculpt,
    t_raise_ground,
    t_lower_ground,
    t_level_ground,
    t_describe_ground,
)

from .catalog import (
    TOOLS,
    EXAMPLES,
)

__all__ = [
    'math',
    'Drawing',
    'parse_cell',
    'cell_name',
    'cell_of',
    'block_bounds',
    'MATERIALS',
    'MAX_OBJECTS',
    '_num',
    'footprint_level',
    'sculpts_of',
    'current_drawing',
    'KINDS',
    'OPENINGS',
    'VOID_KINDS',
    'SAND_KINDS',
    'PROMPT',
    'RES_MAX',
    'RES_MIN',
    'BASE_CELL',
    'FEATHER_FRAC',
    'COLOUR_BAND',
    'SLOPE_BAND',
    'WATER_SOIL',
    'COLOUR_MATS',
    'STYLE_AMP',
    'PEAK_H_FRAC',
    'MESA_H_FRAC',
    'TROUGH_FRAC',
    'LEVEL_BATTER',
    '_hash',
    'value_noise',
    'meander_offset',
    'lake_factor',
    'clamp',
    'smoothstep',
    'band',
    'feather_of',
    '_N',
    's_peak',
    's_ridge',
    's_mesa',
    's_cut',
    'channel_levels',
    's_channel',
    's_basin',
    's_flat',
    's_step',
    's_dunes',
    's_shelf',
    'SCULPTS',
    'base_height',
    'field_at',
    'height_at',
    'lattice',
    'slope_deg',
    'colour_weights',
    'studio_rgb',
    'colour_at',
    'ground_record',
    'h_ground',
    'HEIGHTS',
    'the_ground',
    '_mat',
    '_block',
    '_res_for',
    't_make_ground',
    '_need_ground',
    '_sculpt',
    't_raise_ground',
    't_lower_ground',
    't_level_ground',
    't_describe_ground',
    'TOOLS',
    'EXAMPLES',
]
