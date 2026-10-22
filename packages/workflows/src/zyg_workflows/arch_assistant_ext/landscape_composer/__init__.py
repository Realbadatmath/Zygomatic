# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later
# This package re-exports every name landscape_composer.py defined; __all__ at the
# foot of the file is that surface.

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

This package replaces the single module landscape_composer.py; the import path is unchanged.
Its sections, moved verbatim and imported below in their original order:

  * constants.py — the module header, the original import block and every constant (lines 1-243)
  * checks.py — block arithmetic and the ground checks describe_landscape shares with the test (lines 244-713)
  * recipes_core.py — the step runner and the alpine / river_valley / forest_lake recipes (lines 714-1092)
  * recipes_more.py — the coast / polder / heath / canyon recipes and the RECIPES table (lines 1093-1507)
  * tools.py — the three tools, the scene-word index, TOOLS and EXAMPLES (lines 1508-1884)
"""

from __future__ import annotations

import math
import unicodedata

from zyg_workflows import arch_assistant as _A
from zyg_workflows.arch_assistant import Drawing, block_bounds, cell_name, parse_cell  # noqa: F401

from zyg_workflows.arch_assistant_ext.landscape_composer import constants as _constants
from zyg_workflows.arch_assistant_ext.landscape_composer import checks as _checks
from zyg_workflows.arch_assistant_ext.landscape_composer import recipes_core as _recipes_core
from zyg_workflows.arch_assistant_ext.landscape_composer import recipes_more as _recipes_more
from zyg_workflows.arch_assistant_ext.landscape_composer import tools as _tools

from zyg_workflows.arch_assistant_ext.landscape_composer.constants import (
    BERM_H,
    BERM_W,
    BODY_REACHES,
    BOULDER_M,
    CANYON_DEPTH,
    CLEARING_M,
    CLIFF_M,
    DRAPE_MAX_M,
    DUNE_M,
    FLOW_WATER,
    GROUND_KIND,
    GROUND_STYLE,
    GROUND_TOL,
    HEAD_FRAC,
    HEAD_REACHES,
    KINDS,
    LAKE_R,
    LAMP_M,
    LANDSCAPE_KINDS,
    LEVEL_WATER,
    MAX_BOULDER_M,
    MAX_METRES,
    MAX_TREE_OF_PEAK,
    MAX_WINDMILL_M,
    MESA_H_OF_R,
    MESA_R_OF_W,
    MIN_CELLS,
    MIN_METRES,
    MIN_REACH_M,
    OLD_SOLID_GROUND,
    OPENINGS,
    PEAK_H_CAP,
    PEAK_H_OF_R,
    PEAK_KINDS,
    PEAK_MIN_M,
    PEAK_R_OF_W,
    POLDER_MAX_M,
    POOL_TOL,
    PROMPT,
    RANGE_PEAKS,
    RIM_TOL,
    RIVER_W,
    SCENES,
    SCULPT_KINDS,
    SEA_LEVEL,
    SMALL_BOULDER_M,
    STREAM_W,
    SWELL_H_CAP,
    SWELL_H_OF_R,
    SWELL_R_OF_W,
    TREE_H,
    TREE_KINDS,
    V3_FLOW_WATER,
    V3_LEVEL_WATER,
    V3_WATER,
    VALLEY_D_OF_W,
    WATER_KINDS,
    WATER_TOL,
    WINDMILL_M,
)
from zyg_workflows.arch_assistant_ext.landscape_composer.checks import (
    _at,
    _bands,
    _block_cells,
    _cell_m,
    _cells_m,
    _clamp,
    _f,
    _hh,
    _label,
    _meander_m,
    _mid,
    _rim_offsets,
    _river_nodes,
    _span,
    _sq,
    _walk,
    boulder_across,
    drape_band,
    flow_band,
    ground_fault,
    ground_under,
    is_ground_kind,
    is_tiled_drape,
    landscape_warnings,
    reach_bed,
    solid_ground_kinds,
    surface_y,
    v3_water_fault,
    water_extent,
    water_rim,
    windmill_top,
)
from zyg_workflows.arch_assistant_ext.landscape_composer.recipes_core import (
    SPLIT_ARGS,
    _drape,
    _ground_step,
    _r_alpine,
    _r_forest_lake,
    _r_river_valley,
    _run,
)
from zyg_workflows.arch_assistant_ext.landscape_composer.recipes_more import (
    RECIPES,
    _r_canyon,
    _r_coast,
    _r_heath,
    _r_polder,
)
from zyg_workflows.arch_assistant_ext.landscape_composer.tools import (
    EXAMPLES,
    TOOLS,
    _SCENE_WORDS,
    _fold,
    t_compose_landscape,
    t_describe_landscape,
    t_suggest_scene,
)

__all__ = [
    'math',
    'unicodedata',
    '_A',
    'Drawing',
    'block_bounds',
    'cell_name',
    'parse_cell',
    '_constants',
    '_checks',
    '_recipes_core',
    '_recipes_more',
    '_tools',
    'BERM_H',
    'BERM_W',
    'BODY_REACHES',
    'BOULDER_M',
    'CANYON_DEPTH',
    'CLEARING_M',
    'CLIFF_M',
    'DRAPE_MAX_M',
    'DUNE_M',
    'FLOW_WATER',
    'GROUND_KIND',
    'GROUND_STYLE',
    'GROUND_TOL',
    'HEAD_FRAC',
    'HEAD_REACHES',
    'KINDS',
    'LAKE_R',
    'LAMP_M',
    'LANDSCAPE_KINDS',
    'LEVEL_WATER',
    'MAX_BOULDER_M',
    'MAX_METRES',
    'MAX_TREE_OF_PEAK',
    'MAX_WINDMILL_M',
    'MESA_H_OF_R',
    'MESA_R_OF_W',
    'MIN_CELLS',
    'MIN_METRES',
    'MIN_REACH_M',
    'OLD_SOLID_GROUND',
    'OPENINGS',
    'PEAK_H_CAP',
    'PEAK_H_OF_R',
    'PEAK_KINDS',
    'PEAK_MIN_M',
    'PEAK_R_OF_W',
    'POLDER_MAX_M',
    'POOL_TOL',
    'PROMPT',
    'RANGE_PEAKS',
    'RIM_TOL',
    'RIVER_W',
    'SCENES',
    'SCULPT_KINDS',
    'SEA_LEVEL',
    'SMALL_BOULDER_M',
    'STREAM_W',
    'SWELL_H_CAP',
    'SWELL_H_OF_R',
    'SWELL_R_OF_W',
    'TREE_H',
    'TREE_KINDS',
    'V3_FLOW_WATER',
    'V3_LEVEL_WATER',
    'V3_WATER',
    'VALLEY_D_OF_W',
    'WATER_KINDS',
    'WATER_TOL',
    'WINDMILL_M',
    '_at',
    '_bands',
    '_block_cells',
    '_cell_m',
    '_cells_m',
    '_clamp',
    '_f',
    '_hh',
    '_label',
    '_meander_m',
    '_mid',
    '_rim_offsets',
    '_river_nodes',
    '_span',
    '_sq',
    '_walk',
    'boulder_across',
    'drape_band',
    'flow_band',
    'ground_fault',
    'ground_under',
    'is_ground_kind',
    'is_tiled_drape',
    'landscape_warnings',
    'reach_bed',
    'solid_ground_kinds',
    'surface_y',
    'v3_water_fault',
    'water_extent',
    'water_rim',
    'windmill_top',
    'SPLIT_ARGS',
    '_drape',
    '_ground_step',
    '_r_alpine',
    '_r_forest_lake',
    '_r_river_valley',
    '_run',
    'RECIPES',
    '_r_canyon',
    '_r_coast',
    '_r_heath',
    '_r_polder',
    'EXAMPLES',
    'TOOLS',
    '_SCENE_WORDS',
    '_fold',
    't_compose_landscape',
    't_describe_landscape',
    't_suggest_scene',
]
