# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

# ruff: noqa: E402, F401
#   E402: the submodule imports follow the original top-level import block, which this
#         file re-does verbatim so old attribute reads (walk_rules.math, .A) still resolve.
#   F401: this file re-exports every name the single module defined.

"""walk_rules — can a person WALK it? (2026-09-16)

The operator's third defect on 2026-09-12 was "cannot walk it": job 94f5813b's
stair arrived INSIDE a lift shaft, with no landing anywhere outside a shaft
wall. circulation_rules could say the stair reached every storey and that a
lift served them; nothing could say that a person standing at the entrance
door could put one foot in front of the other and arrive at either of them.
Reachability is not a property of a record, it is a property of the FLOOR —
so this family owns no kinds and no tools and asks one question per storey:

    from where you come IN, can you get to the things you must get to?

It answers it the only way that cannot be fooled by a record's good
intentions: a 0.25 m occupancy grid over the storey, a breadth-first flood
fill, and a list of targets.

  floor    a cell has floor when a slab or flat roof top sits within 0.35 m of
           the storey floor (outside the envelope on storey 0 the ground
           counts — the approach is somebody else's check), and it is not in a
           registered slab void.
  solid    a cell is blocked when a wall, partition, curtain wall, column,
           shaft, car, pool basin, stair or piece of floor-standing furniture
           whose height band crosses [floor + 0.2, floor + 1.9] covers it.
  door     every door opening cuts a free tunnel through its host wall — that
           is how people pass a solid — 0.3 m out each side of the leaf.
  width    the free grid eroded by a 5-cell window that tolerates one blocked
           cell is the 'wide' grid: what is left is floor a 1.0 m body fits
           through — a 4-cell run keeps its middle, a 3-cell (0.9 m) run keeps
           nothing. The same window tolerating two is the 'squeeze' grid: 0.75 m,
           turn sideways. Door tunnels stay wide (a 0.9 m leaf is a door, not a
           pinch point); a corridor squeezed by a stray partition does not.

A target reachable on 'wide' is silent; one reachable only on 'squeeze' is a
width warning — you can get there, badly; one reachable on neither is an error
naming the first record standing on the straight line to it. Reaching a lift
down a 0.5 m slot between a partition and the facade is not reaching it.

Plan axes as everywhere in the studio: column letters along +X, rows along +Z,
north = -Z. Storeys are counted from the group's own base (env['y0']), so a
building on a hill answers the same as one at y = 0; storey == storeys is the
roof deck and is only walked when something other than roof plant stands on it.

Implementation note: the floor test rasterises the slab/roof records' plan
rects rather than calling A.deck_tops per cell — 104 x 104 cells x 21 storeys
is 227 000 points and deck_tops is a scan of the whole drawing. Same answer,
three orders of magnitude cheaper.
"""

from __future__ import annotations

import math
from collections import deque

from zyg_workflows import arch_assistant as A
from zyg_workflows.arch_assistant import Drawing, _num
import logging as _zyg_logging

# the sections, in the order the single module ran them
from .grid import (
    BLOCK_KINDS,
    BODY_HI,
    BODY_LO,
    BODY_M,
    CELL,
    DECK_KINDS,
    DOOR_KINDS,
    DOOR_REACH,
    ERODE,
    FLOOR_TOL,
    KINDS,
    LANDING_M,
    MAX_CELLS,
    MAX_FINDINGS,
    NEVER_BLOCK,
    OBJ_REACH,
    OPENINGS,
    PAD,
    POLE_KINDS,
    POLE_M,
    PROMPT,
    ROOF_PLANT,
    SHAFT_KIND,
    SIDE_SHORT,
    SLACK,
    SQUEEZE_M,
    SQUEEZE_SLACK,
    STAIR_KINDS,
    TOOLS,
    WALL_KINDS,
    _Grid,
    _cap,
    _fill,
    _lbl,
    _mod,
    _p,
    _zyg_log,
    block_kinds,
)
from .reading import (
    OBB_MAX_CELLS,
    SQUARE_TOL,
    _Building,
    _cores,
    _deck_is_used,
    _deck_targets,
    _door_rects,
    _entrance_doors,
    _ground_fn,
    _grow,
    _head_house_door,
    _host_of,
    _landing_rect,
    _obb_of,
    _p_str,
    _room_doors,
    _rot_rect,
    _stair_height,
    _storey_grid,
    _vspan,
)
from .checks import (
    DESIGN_CHECKS,
    MAX_TRY,
    _blocker,
    _candidates,
    _cell_name,
    _in_front,
    _pinch,
    _reach,
    _skip_ids,
    _stop_point,
    _walk_group,
    _walk_storey,
    _walkable,
    _without,
    check_walkable,
)
