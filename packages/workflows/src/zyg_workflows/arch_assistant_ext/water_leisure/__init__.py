# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""water_leisure — the assistant's water and leisure tools.

Pools, ponds, canals and fountains; sports courts with their goals and nets;
a playground laid out inside a block; sun loungers and parasols along a row of
cells. Basins DIG: a pool or a canal record's geometry runs from -depth to a
little above the ground plane, so `y` stays the record's ground level and the
hole is in the parameters, not in the record's position.

Ground (2026-09-07): every record lands on the ground under it — `y` comes from
arch_assistant.place_height, and `base_height` overrides it. The four water
tools are LEVEL WATER (R3): the basin's `y` is the ground at its centre and the
tool REFUSES when the ground varies more than 0.5 m under the footprint, because
a level surface on sloping ground is either buried or floating. Flowing water is
the rivers family (add_stream / add_river). A sports court is a level plane too
(R2): it refuses ground steeper than 3 % or a footprint that is not planar.
Playground pieces and beach sets are point things (R5): each piece sits on the
ground under itself, with no tilt.

Decks (2026-09-08, design rules): a slab or flat roof spans [y, y + t], so the
walkable DECK is its top. Twenty storeys put the roof record at 54 and its deck
at 54.3; a pool told base_height=54 used to land INSIDE the roof — its water
0.4 m under the deck, its coping coplanar with it (a white z-fighting outline),
its basin hanging into the glass top storey: "no pool". Now `_level_check`
lifts an explicit base inside a deck to the deck's top (deck_top) and, with no
base given, prefers a deck over the ground under the building (surface_top).
On a deck a pool is RAISED by default — the basin stands on the deck with its
walls exposed (p.raised = depth) — unless sunk=true (a plant storey below), and
`infinity` puts a glass overflow weir with a catch trough on the deck edge.
"""

from __future__ import annotations

# ruff: noqa: F401,E402  # this file is the re-export surface of the split
# module: every top-level name water_leisure.py defined is re-bound here, so no
# importer anywhere needs editing.  The submodules are imported in the original
# section order, so their module-level side effects still run in that order.

import sys as _sys
from types import ModuleType as _ModuleType

# An importlib reload of this package re-executes only this file; the submodules
# would be handed back from sys.modules unchanged, so a reload would no longer
# re-read the environment the way reloading the single water_leisure.py did.  Drop
# them first, so a reload really does re-execute every moved section.
for _m in [_m for _m in _sys.modules if _m.startswith(__name__ + '.')]:
    del _sys.modules[_m]

# base.py — top imports, KINDS/PROMPT, the ground rules (R1/R3/R5) and the deck helpers
from zyg_workflows.arch_assistant_ext.water_leisure.base import (
    A,
    COURT_SLOPE,
    COURT_SPREAD,
    DECK_CLEAR,
    Drawing,
    INF_INSET,
    INF_REACH,
    KINDS,
    LEVEL_TOL,
    MATERIALS,
    MAX_OBJECTS,
    OPENINGS,
    PROMPT,
    SIDES,
    SPORTS,
    _DEFAULT_MAT,
    _INF,
    _cells,
    _deck_at,
    _deck_extent,
    _ground_span,
    _label,
    _level_check,
    _line_span,
    _mat,
    _num,
    _parapet_along,
    _room,
    _storey_deck,
    block_bounds,
    cell_centre,
    cell_name,
    cell_of,
    cell_size,
    deck_top,
    deck_tops,
    ground_height,
    ground_plane,
    math,
    parse_cell,
    place_height,
    surface_top,
)

# pool.py — add_pool, and the rooftop-infinity constants plus its geometry/deck-contents helpers
from zyg_workflows.arch_assistant_ext.water_leisure.pool import (
    CORE_CLEAR,
    DECK_MARGIN,
    GUARD_H,
    GUARD_IN,
    GUARD_T,
    GUARD_WORDS,
    INF_COPING,
    INF_RIM,
    INF_TILE,
    INF_TILES,
    LIGHT_CAP,
    LIGHT_N,
    LOUNGER_MAX,
    LOUNGER_OFF,
    LOUNGER_STEP,
    PALM_GUARD,
    PALM_IN,
    PALM_R,
    PARASOL_OFF,
    PLANT_KINDS,
    POOL_MIN_SIDE,
    SWIM_DEPTH,
    WALK_MIN,
    _DIR,
    _FACE_NZ,
    _FACE_X,
    _OPP,
    _block_cells,
    _coverage,
    _deck_cores,
    _guards_along,
    _inside,
    _move_suggestion,
    _n_treads,
    _pool_deck,
    _pool_span,
    _rect_gap,
    _storey_base,
    _walk_short,
    _walk_suggestion,
    _would_deck,
    t_add_pool,
)

# infinity.py — add_infinity_pool as one call, and check_infinity_pools / DESIGN_CHECKS
from zyg_workflows.arch_assistant_ext.water_leisure.infinity import (
    DESIGN_CHECKS,
    check_infinity_pools,
    t_add_infinity_pool,
)

# leisure.py — ponds, canals and fountains; sports courts, playgrounds and beach sets
from zyg_workflows.arch_assistant_ext.water_leisure.leisure import (
    CANAL_LEVEL_MSG,
    _deck_or_ground,
    t_add_beach_set,
    t_add_canal,
    t_add_fountain,
    t_add_playground,
    t_add_pond,
    t_add_sports_court,
)

# tools.py — _BASE_H, the TOOLS registration table and EXAMPLES
from zyg_workflows.arch_assistant_ext.water_leisure.tools import (
    EXAMPLES,
    TOOLS,
    _BASE_H,
)

_SECTIONS = tuple(
    _sys.modules[f'{__name__}.{_m}']
    for _m in (
        'base',
        'pool',
        'infinity',
        'infinity_build',
        'leisure',
        'tools',
    )
)


class _SplitModule(_ModuleType):
    """water_leisure.py was ONE module, so `setattr(mod, name, value)` — pytest's
    monkeypatch, and the restore-after-call patching some callers do — rebound the
    single global every function read.  The readers are now sibling modules with
    their own globals, which a write to the package attribute would not reach, so
    the write is mirrored into every section whose namespace holds that name.
    """

    def __setattr__(self, name, value):
        super().__setattr__(name, value)
        for _m in self.__dict__.get('_SECTIONS') or ():
            if name in _m.__dict__:
                _m.__dict__[name] = value

    def __delattr__(self, name):
        super().__delattr__(name)
        for _m in self.__dict__.get('_SECTIONS') or ():
            _m.__dict__.pop(name, None)


# last statement: from here on every attribute write to this package fans out
_sys.modules[__name__].__class__ = _SplitModule
