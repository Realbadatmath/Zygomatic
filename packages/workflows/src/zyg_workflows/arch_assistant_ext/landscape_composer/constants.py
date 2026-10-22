# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later
# This module inherits the original top import block of landscape_composer.py;
# names it does not use itself are imported by its siblings and by importers of
# the package, so they are re-exported through __all__ below.

"""arch_assistant_ext/landscape_composer.py — whole landscapes in one call.

This family adds NO kinds of its own. It is a recipe book: `compose_landscape`
lays a coherent scene over a block by calling the landscape families
(ground_v3, water_v3, mountains, rivers_lakes, forests, cliffs_rocks,
coast_dunes, fields_meadows, landmarks_special) through
`arch_assistant.call_tool` in a fixed order.

WHY THIS FILE WAS REBUILT ON 2026-09-07 (v3-B). Every recipe used to start with
`make_terrain` and then ADD a separate solid per landform: a `valley` record, a
`mountain_range` record, a `sea` record. Nothing could CUT into the ground, so
the operator's eye verdicts were all the same fault seen seven ways — "the
valley is a raised straight-edged plinth", "two grey cones sitting ON a green
lawn", "the wood covers the block wall to wall and the lake is not visible",
"sea and beach the same value so the waterline is invisible".

So the three rules this file is now built on:

  * EVERY recipe starts with `make_ground` over the whole block and after that
    only SCULPTS it (raise_ground, lower_ground, level_ground, carve_river,
    fill_lake, fill_sea, add_beach, add_dunes, add_cliff) or DRAPES things over
    it (forests, meadows, rocks, a mill). No recipe may emit a kind from
    OLD_SOLID_GROUND — a valley is now a hole in the one ground, not a box on
    it. `compose_landscape` refuses its own output if one appears.
  * SIZES ARE REAL METRES, never a fraction of the block. A conifer is 16 m
    whether it stands on a 240 m block or a 1 km one; a boulder is 2.5 m; a
    windmill tower is 12 m. Only the COUNTS and the BANDS follow the block.
    The one exception is the RANGE: a mountain is the one landform that really
    does scale with the ground it stands on, so a peak's radius is
    PEAK_R_OF_W (0.15) x the block width and its height PEAK_H_OF_R (0.8) x
    that radius, capped at PEAK_H_CAP. A 1 km block gets a 120 m range.
  * THE BLOCK MAY BE A KILOMETRE. The old 400 m ceiling was the solid terrain
    record's, and that record is gone; a v3 ground is one heightfield at
    res 200 whatever its size. What is still capped is the per-CALL block of
    the drape tools (forests, rocks, meadows refuse past 600 m), so anything
    draped is laid in bands of at most DRAPE_MAX_M.

If any step refuses, the recipe STOPS and hands the refusal back naming the
step, so a half-built scene never appears.
"""

from __future__ import annotations

import math
import unicodedata

from zyg_workflows import arch_assistant as _A
from zyg_workflows.arch_assistant import Drawing, block_bounds, cell_name, parse_cell  # noqa: F401

# re-exported for the siblings and for importers of the landscape_composer package
__all__ = [
    'math',
    'unicodedata',
    '_A',
    'Drawing',
    'block_bounds',
    'cell_name',
    'parse_cell',
]

KINDS: dict = {}
OPENINGS: list = []

SCENES = ('alpine', 'river_valley', 'forest_lake', 'coast', 'polder', 'heath', 'canyon')
MIN_CELLS = {'alpine': 10, 'coast': 10, 'canyon': 10}
# the real floor is metres, not cells: the sizes below are absolute. alpine's
# floor is set by its own proportion rule — a conifer is at most 0.3 of the
# summit and no thinner than 8 m, so the range has to reach 27 m, so the block
# has to be wide enough for a 0.15 x W peak radius: 240 m.
MIN_METRES = {
    'alpine': 240.0,
    'canyon': 120.0,
    'coast': 120.0,
    'river_valley': 100.0,
    'forest_lake': 80.0,
    'polder': 80.0,
    'heath': 60.0,
}
# a v3 ground is ONE heightfield however big the block, so the old 400 m cap
# (the solid terrain record's) is gone. The ceiling that replaces it is a
# MEASURED one, not the grid's: past a kilometre carve_river's reaches stop
# being physical — a reach holds ONE level and never climbs, so on a 2 km block
# a 300 m reach ends up tens of metres under the bank it is supposed to be
# cutting. A kilometre is what composes clean on every scene.
MAX_METRES = 1000.0
# forests / rocks / meadows / undergrowth refuse a block past 600 m a side, and
# a forest at 0.025 trees/m2 hits its own 3000-tree ceiling at 346 m, so
# everything DRAPED is laid in patches of at most this
DRAPE_MAX_M = 300.0
# make_polder lays a ditch row every 0.75 m and holds 400 of them
POLDER_MAX_M = 250.0
# a carved reach is a straight fall, so it must be short enough to follow the
# trough it lies in — see _river_nodes
HEAD_FRAC = 0.18
HEAD_REACHES = 20
BODY_REACHES = 18
MIN_REACH_M = 1.5

# the ground style each scene stands on
GROUND_STYLE = {
    'alpine': 'rolling',
    'river_valley': 'gentle',
    'forest_lake': 'gentle',
    'coast': 'flat',
    'polder': 'flat',
    'heath': 'gentle',
    'canyon': 'gentle',
}

# ── real sizes (R7). Metres. Not a function of the block. ─────────────────────
TREE_H = {'conifer': 16.0, 'deciduous': 12.0, 'poplar': 20.0, 'fruit': 4.0}
BOULDER_M = 2.5  # the largest boulder in a field (1.2 - 2.5)
SMALL_BOULDER_M = 1.2
WINDMILL_M = 12.0  # tower height; the sails follow it
LAMP_M = 4.0
STREAM_W = (2.0, 0.5)  # width, depth
RIVER_W = (6.0, 12.0)
LAKE_R = (8.0, 60.0)
DUNE_M = 10.0  # 8 - 12
CLIFF_M = (15.0, 25.0)
BERM_H, BERM_W = 4.0, 12.0  # the polder dyke
SEA_LEVEL = -0.3  # the coast datum: the ground's water line AND fill_sea's
CANYON_DEPTH = 25.0  # the cut the brief asks for, clamped to what the block can hold
CLEARING_M = 15.0  # forest_lake: how far the wood keeps off the water

# a mountain IS a function of the block — it is the one thing that is
MESA_R_OF_W = 0.20  # mesa radius = 0.20 x block width
MESA_H_OF_R = 0.60  # mesa height = 0.60 x its radius
PEAK_R_OF_W = 0.15  # peak radius = 0.15 x block width
PEAK_H_OF_R = 0.8  # peak height = 0.8 x its radius
PEAK_H_CAP = 150.0  # ...capped: a 1 km block gets a 120 m range
RANGE_PEAKS = 3  # one range, three summits, spanning the block
SWELL_R_OF_W = 0.18  # heath: a swell is wide and low
SWELL_H_OF_R = 0.30
SWELL_H_CAP = 20.0  # ...and a heath swell stays a swell however big the heath
VALLEY_D_OF_W = 0.30  # valley depth = 0.30 x the valley's width

# ── the checks describe_landscape and the test share (R8) ─────────────────────
GROUND_TOL = 0.35  # how far a record's y may be off the ground under it
WATER_TOL = 0.25  # level water sits ON the ground (a ditch RING shares one level,
#                                 so a member may sit a base-terrain relief off its own patch)
POOL_TOL = 1.2  # flowing water may pool BELOW it (R4's no-uphill rule)
RIM_TOL = 0.35  # v3 water: how far a rim sample may fall below the surface
MAX_TREE_OF_PEAK = 0.3
PEAK_MIN_M = 30.0  # under this a summit is a hillock, and a 12 m tree
#                                 standing on a 16 m heath swell is the real world,
#                                 not a proportion fault. The rule is about MOUNTAINS.
MAX_BOULDER_M = 4.0
MAX_WINDMILL_M = 22.0

LEVEL_WATER = frozenset(('sea', 'lake', 'pond', 'pool', 'canal', 'marsh', 'fountain'))
FLOW_WATER = frozenset(('river', 'stream', 'waterfall'))
WATER_KINDS = LEVEL_WATER | FLOW_WATER
# a composed landscape is drawn at 5-10 m cells: its tree lines stay the one-object
# low-poly rows (model='parametric'), while plant_tree_line alone places real trees
TREE_KINDS = frozenset(('forest', 'tree_line', 'orchard'))
PEAK_KINDS = frozenset(
    ('mountain', 'mountain_range', 'ridge', 'volcano', 'mesa', 'sculpt_peak', 'sculpt_ridge', 'sculpt_mesa')
)

# ── v3: the one ground, its sculpts and the water that lies on it ────────────
GROUND_KIND = 'ground'
SCULPT_KINDS = frozenset(
    (
        'sculpt_peak',
        'sculpt_ridge',
        'sculpt_mesa',
        'sculpt_cut',
        'sculpt_channel',
        'sculpt_basin',
        'sculpt_flat',
        'sculpt_step',
        'sculpt_dunes',
        'sculpt_shelf',
    )
)
V3_LEVEL_WATER = frozenset(('water_body', 'water_plane'))
V3_FLOW_WATER = frozenset(('water_path',))
V3_WATER = V3_LEVEL_WATER | V3_FLOW_WATER

# the kinds a v1 solid ground was built out of. On a v3 drawing every one of
# them is a bug: the old families all branch to a sculpt when a ground exists,
# so one of these appearing means a recipe reached for a solid tool.
OLD_SOLID_GROUND = frozenset(
    ('terrain', 'hill', 'slope', 'valley', 'mountain', 'mountain_range', 'sea', 'beach', 'dune_field', 'river', 'lake')
)

PROMPT = (
    "Landscapes: for a landscape ('a mountain scene', 'een kustlandschap') call compose_landscape(cell_from, "
    'cell_to, scene) ONCE, then adjust with the family tools. Every recipe lays ONE sculpted ground '
    '(make_ground) over the block first and then only CUTS INTO it (lower_ground, carve_river, fill_lake, '
    'fill_sea) or drapes over it — no solid terrain, valley, mountain or sea records. Sizes are REAL metres, '
    'never a fraction of the block: conifer 16 m (capped at 0.3 of the summit), poplar 20, boulder 2.5, mill 12, '
    'stream 2, river 6-12, dune 10, cliff 15-25; only a mountain scales with the block (radius 0.15 x width, '
    'height 0.8 x that, capped 150 m). Scenes: alpine (range, carved valley, stream, tarn), river_valley '
    '(trough, river, bank meadows), forest_lake (lake basin, wood held 15 m back), coast (sea, beach, dunes, '
    'cliff), polder (dyke, mill, ditches), heath (swells, heather, pond), canyon (25 m cut, two mesas, river, '
    'scree). alpine needs 240 m, coast/canyon 120 m, 1000 m max; real mountains want a 10 m grid. '
    'describe_landscape warns about anything buried, floating or out of proportion.'
)

# every landscape kind the families (and their neighbours) can draw
LANDSCAPE_KINDS = {
    'mountain': 'mountains',
    'mountain_range': 'mountains',
    'ridge': 'mountains',
    'volcano': 'mountains',
    'mesa': 'mountains',
    'valley': 'mountains',
    'river': 'rivers_lakes',
    'lake': 'rivers_lakes',
    'waterfall': 'rivers_lakes',
    'forest': 'forests',
    'tree_line': 'forests',
    'orchard': 'forests',
    'undergrowth': 'forests',
    'cliff': 'cliffs_rocks',
    'escarpment': 'cliffs_rocks',
    'boulder': 'cliffs_rocks',
    'rock_field': 'cliffs_rocks',
    'scree': 'cliffs_rocks',
    'sea_stack': 'cliffs_rocks',
    'sea': 'coast_dunes',
    'beach': 'coast_dunes',
    'dune_field': 'coast_dunes',
    'island': 'coast_dunes',
    'breakwater': 'coast_dunes',
    'crop_field': 'fields_meadows',
    'meadow': 'fields_meadows',
    'marsh': 'fields_meadows',
    'vineyard': 'fields_meadows',
    'fence': 'fields_meadows',
    'terrain': 'terrain',
    'hill': 'terrain',
    'slope': 'terrain',
    'plateau': 'terrain',
    'berm': 'terrain',
    'retaining_wall': 'terrain',
    'pond': 'water_leisure',
    'canal': 'water_leisure',
    'pool': 'water_leisure',
    'windmill': 'landmarks_special',
    'lighthouse': 'landmarks_special',
    'pad': 'site',
    GROUND_KIND: 'ground_v3',
}
LANDSCAPE_KINDS.update({k: 'ground_v3' for k in SCULPT_KINDS})
LANDSCAPE_KINDS.update({k: 'water_v3' for k in V3_WATER})
