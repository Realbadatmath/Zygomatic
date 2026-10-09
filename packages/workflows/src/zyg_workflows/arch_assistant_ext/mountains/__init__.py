# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""mountains — real mountains: peaks, ranges, ridges, volcanoes, mesas, valleys.

The terrain family gives rolling ground (amp <= 100 m) and one smooth hill.
This family gives the mountains themselves, and the valley a river runs down.

The noise below is the SAME arithmetic as arch_ext/mountains.js and
arch_blender_ext/mountains.py (itself a verbatim copy of the terrain family's
value_noise). It lives here too so the assistant — and the test — can say what
a mountain record really does without rendering it:

    peak_scale(r, h, rug, seed, res)    the factor the raw lattice is
                                        multiplied by so its highest vertex is
                                        exactly h (h / max(raw))
    snow_ceiling(r, h, rug, seed, res)  the highest TRIANGLE centroid of that
                                        lattice as a fraction of h — i.e. the
                                        snow line above which no face is snow.
                                        Cross the three engines with it: a
                                        mountain with snow just under the
                                        ceiling has two parts, just over it
                                        has one.

HEIGHTS (2026-09-07, the ground seam): every one of the six kinds is GROUND, so
each exports fn(p, lx, lz) -> metres above the record's base at a LOCAL plan
point, None outside the footprint. They are the SAME normalised field the tab
draws — the lattice kinds interpolate the very lattice the geometry builds, so
the maximum of the field is the record's bounding-box height.

V3 (2026-09-07, the sculpted heightfield): the six kinds above are SOLIDS, and a
solid standing on a lawn is exactly what the operator rejected — two grey cones
on green baize, a valley that is a raised plinth. So when the drawing has a
`ground` record (the one sculpted heightfield of arch_assistant_ext/ground_v3.py)
these tools stop drawing solids and write SCULPTS instead: void records whose
contribution is a TERM in the ground's own height sum, feathered to nothing at
their rim, so a peak grows out of the land and a valley is a real hollow.

    add_mountain   peak  -> sculpt_peak     mesa -> sculpt_mesa
                   volcano -> volcano (still a solid: a crater is not a sculpt
                   kind yet — the tool says so in its reply)
    add_mountain_range   -> `peaks` sculpt_peak records spaced along the block,
                            heights varying +-25 % by hash — NOT one range solid
    add_ridge            -> one sculpt_ridge per consecutive pair of cells
    add_valley           -> sculpt_cut

Two things follow from the contribution being ADDITIVE. First, a sculpt's own
`y` must be 0: ground_v3.field_at adds `dh + y * mask` onto the ground already
under the point, so a peak on rolling ground rises FROM that ground for free and
a non-zero y would count the land twice. An explicit `base_height` still
overrides — it shifts the whole feature that many metres, feathered by the
sculpt's own mask. Second, snow is no longer the record's business: the ground
colours itself above its own absolute `snow_h`, so `snow_line` sets nothing on a
v3 drawing and the reply says which height the ground uses.

Without a `ground` record NOTHING changes: the old six kinds, the old y = the
ground under the record, the old snow arithmetic, the old refusals. The
proportion rules (a mountain 0.25-1.0 x its radius, a mesa 0.8, a ridge 0.8 x
its width, a valley 0.4 x its width deep) are refusals in BOTH modes.
"""

# ruff: noqa: F401, E402 — this package IS the re-export surface of the old
# single file: every name it defined must stay an attribute of the same
# import path, and the submodule imports sit below the shared top block.

from __future__ import annotations

import math

from zyg_workflows.arch_assistant import (
    Drawing,
    parse_cell,
    cell_centre,
    cell_name,
    block_bounds,
    MATERIALS,
    MAX_OBJECTS,
    _num,
    place_height,
)

KINDS = {
    'mountain': {'r': 60, 'h': 40, 'rug': 0.45, 'seed': 1, 'res': 48, 'snow': 0.7},
    'mountain_range': {'len': 200, 'w': 80, 'h': 50, 'peaks': 4, 'rug': 0.45, 'seed': 1, 'res': 64, 'snow': 0.75},
    'ridge': {'len': 80, 'w': 20, 'h': 15, 'rug': 0.3, 'seed': 1, 'res': 32},
    'volcano': {'r': 50, 'h': 35, 'crater_r': 10, 'crater_d': 8, 'seg': 48, 'rings': 16},
    'mesa': {'r': 40, 'h': 25, 'top_r': 30, 'rug': 0.25, 'seed': 1, 'seg': 48},
    'valley': {'w': 120, 'd': 80, 'h': 30, 'floor_w': 20, 'profile': 0, 'res': 32},
}
OPENINGS: list = []

PROMPT = (
    'Mountains (berg) are ground: draw them before any building, and everything lands on the ground under it — '
    'base_height overrides. add_mountain(centre, radius, height, style) is ONE landform, height 0.25 to 1.0 x '
    "radius, style 'peak'/'volcano'/'mesa', snow_line 'auto' capping a summit 60 m or more above its base; "
    'add_mountain_range(cell_from, cell_to, peaks) chains summits; add_ridge(cells) runs a crest; '
    'add_valley(cell_from, cell_to) is a trough where a river runs, so call a river tool along it after. '
    'TWO MODES: with a ground (make_ground) all four are sculpted into that one '
    'heightfield; without a ground they are drawn as solids. explain("mountains") has the detail.'
)

from .field import (
    _hash,
    value_noise,
    mountain_lattice,
    range_lattice,
    ridge_crest,
    peak_scale,
    snow_ceiling,
    peak_radius,
    _LAT_CACHE,
    _cached,
    _bilinear,
    h_mountain,
    h_mountain_range,
    h_ridge,
    h_volcano,
    h_mesa,
    h_valley,
    HEIGHTS,
)

from .plumbing import (
    _STYLES,
    MAX_R,
    MIN_R,
    MAX_H,
    MAX_BLOCK,
    SNOW_MIN_SUMMIT,
    SNOW_AUTO_LINE,
    NO_SNOW,
    MOUNT_MAX_SLOPE,
    MOUNT_MIN_SLOPE,
    MESA_MAX_SLOPE,
    RIDGE_MAX_SLOPE,
    VALLEY_MAX_DEPTH,
    VALLEY_DEF_DEPTH,
    RANGE_DEF_HEIGHT,
    SCULPT_FEATHER,
    RANGE_SPREAD,
    SCULPT_MAT,
    has_ground,
    ground_of,
    sculpt_y,
    ground_snow_words,
    SOLID_WORDS,
    SCULPT_WORDS,
    _mat,
    _bad_size,
    _res_for,
    resolve_snow,
    _snow_words,
)

from .tools import (
    t_add_mountain,
    t_add_mountain_range,
    t_add_ridge,
    t_add_valley,
)

from .catalog import (
    TOOLS,
    EXAMPLES,
)
