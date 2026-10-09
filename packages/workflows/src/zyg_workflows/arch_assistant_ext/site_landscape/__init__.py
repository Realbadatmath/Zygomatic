# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""site_landscape — the assistant's tools for everything around the building:
planting, boundaries, street furniture, paving, parking and roads.

Tools: plant_trees, add_fence, add_parking, add_road, add_curved_road,
add_street_furniture, add_garden_bed. Randomness is DETERMINISTIC — a tiny LCG
seeded on (seed, index), never random.random() — so the same request twice puts
the same tree in the same place, which is what makes a drawing reproducible.

GROUND (2026-09-07): nothing here lands at y = 0 any more. Every tool asks the
ground seam in arch_assistant (ground_height / ground_plane / ground_tilt /
place_height) for the height of the hill, slope or plateau under it:

  R5 point things — trees, lamp posts, benches, bins, shrubs — take the ground
     height at their OWN x/z and stay vertical (one record per item makes this
     exact: no plane is needed).
  R4 linear things — a fence or hedge leg, a road piece — sit at the ground
     height at the leg's CENTRE and lean along their run with
     rz = atan((y_end - y_start) / len). A fence leg steeper than 15 % is cut
     into 5 m pieces, each at its own height.
  R2 thin surfaces — a flower bed, a parking bay — keep their record UPRIGHT and
     carry the ground plane in two new parameters gx, gz (rise per metre along
     the record's LOCAL x and z); the tab and Blender shear the slab to match.
     A bed over ground that is not planar (spread > 1 m) is TILED.
  R7 real sizes are absolute: a deciduous tree is 6-20 m, a conifer 8-25 m, a
     palm 5-15 m, a lamp post 3-6 m, whatever the block's size.

`base_height` on every tool overrides the ground with a literal y (0 puts the
old flat behaviour back).
"""

# Pattern A split (2026-10-07): the 1,180-line site_landscape.py became this
# package. Every section moved byte for byte into one of the modules below;
# this __init__ re-does the original top import block and re-exports every
# name the single file defined, so `import ...arch_assistant_ext.site_landscape`
# resolves exactly as before.
# ruff: noqa: F401

from __future__ import annotations

import math

from zyg_workflows.arch_assistant import (
    Drawing,
    parse_cell,
    cell_centre,
    cell_name,
    cell_of,
    cell_size,
    block_bounds,
    MATERIALS,
    _num,
    MAX_OBJECTS,
    EXT_MODULES,
    ground_height,
    ground_plane,
    ground_tilt,
    place_height,
)

# the submodules, in the original section order (module-level side effects
# must run in the order the single file ran them)
from zyg_workflows.arch_assistant_ext.site_landscape import constants
from zyg_workflows.arch_assistant_ext.site_landscape import ground_seam
from zyg_workflows.arch_assistant_ext.site_landscape import site_tools
from zyg_workflows.arch_assistant_ext.site_landscape import tool_schema

from zyg_workflows.arch_assistant_ext.site_landscape.constants import (
    KINDS,
    OPENINGS,
    PROMPT,
    TREE_KINDS,
    FENCE_KINDS,
    FURNITURE_KINDS,
    BED_KINDS,
    TREE_RANGE,
    TREE_DEFAULT_H,
    CROWN_R,
    FURNITURE_RANGE,
    FENCE_LEAN,
    FENCE_PIECE,
    PARK_SPREAD,
    PARK_SLOPE,
    TILE_SPREAD,
    MAX_TILES,
    _mat,
    _rnd,
    _clamp,
    REAL_TREES,
    REAL_LAMPS,
    SCALE_RANGE,
    CROWN_FIT,
    CANOPY_KINDS,
    CANOPY_CLEAR,
    CANOPY_NEAR,
    SOFFIT_GAP,
    LAMP_DEFAULT_H,
    ROAD_CLEAR,
    ROAD_OFFSET,
    _assets,
    _real_pick,
    _tree_p,
    _cells,
    _ry,
)
from zyg_workflows.arch_assistant_ext.site_landscape.ground_seam import (
    _local_slopes,
    _leg_pieces,
    _tile_block,
    _fall,
    _canopies,
    _canopy_dist,
    _clear_cell,
    _canopy_refusal,
    _roads,
    _road_dist,
    _verge_cells,
    _carriageway_refusal,
    _soffit_cap,
)
from zyg_workflows.arch_assistant_ext.site_landscape.site_tools import (
    t_plant_trees,
    t_add_fence,
    t_add_parking,
    t_add_road,
    t_add_curved_road,
    t_add_street_furniture,
    t_add_garden_bed,
)
from zyg_workflows.arch_assistant_ext.site_landscape.tool_schema import (
    _CELL,
    _CELL_LIST,
    _BASE,
    TOOLS,
    EXAMPLES,
)
