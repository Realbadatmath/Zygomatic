# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""floor_plans — real, openly licensed floor plans as a library the assistant
searches and places (2026-09-10).

Why: `layout_floor` generates a plausible double-loaded floor, but a generated
plan is a diagram — equal units, one corridor, no hall, no wet core. The packs
under data/architecture/plans/ are SURVEYED plans (Swiss Dwellings), recovered
listing plans (ResPlan) and procedurally generated houses (ProcTHOR), all under
CC BY / Apache licences. Each plan is one JSON file on the schema the converters
write: boundary, rooms, wall centrelines, doors, windows, fixtures, entrance and
(for a floor) the stair/lift core.

Placing one is a transform, not a redraw: mirror -> rotate -> scale (within
±12 %, else refused) -> align (centre / entrance side / core), snap, then the
plan's own records become the studio's own kinds — interior walls become
`partition` records exactly as interior_rooms places them, doors become `door`
records on those partitions, rooms become `zone` records the planning analyses
read, fixtures become the furniture kinds. The outer walls are DROPPED when the
plan goes inside a box (the box already has them) and drawn only when
shell=True, which is how a house lands on empty cells.

The placement is registered in d.ext['floor_layouts'][storey] exactly as
layout_floor does, so `repeat_floor` carries a real plan up a tower.

LICENCE: every pack carries its attribution line; placing a plan appends it to
d.ext['attributions'], and credits_text(d) prints the lines that must appear in
the credits. Nothing is drawn from a pack whose manifest has no licence.

No new kinds.
"""

# ruff: noqa: F401, E402

from __future__ import annotations

import json
import math
import os

from zyg_workflows import arch_assistant as A
from zyg_workflows import paths
from zyg_workflows.arch_assistant import (
    Drawing,
    MATERIALS,
    MAX_OBJECTS,
    block_bounds,
    _num,
)
import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)


from zyg_workflows.arch_assistant_ext.floor_plans.plan_packs import (
    ATTR_KEY,
    CORE_KINDS,
    DEFAULT_DIR,
    EXT_KEY,
    FIXTURE_KIND,
    HEAD_LINTEL,
    JAMB_M,
    KINDS,
    KINDS_OK,
    MIN_GLASS,
    OPENINGS,
    OVERLAP_M,
    SCALE_MAX,
    SCALE_MIN,
    SIDES_CW,
    _CACHE,
    _T,
    _approach_rects,
    _best_rot,
    _claim,
    _clamp,
    _clip_segment,
    _core_centre,
    _core_rects,
    _facade,
    _fit_scale,
    _group_plate,
    _group_slab,
    _group_wall_mat,
    _in_rects,
    _landing_rects,
    _mirror_side,
    _on_wall,
    _poly_centre,
    _rec_bbox,
    _rot_side,
    _slab_rect,
    _snap,
    attribution_of,
    load_plan,
    packs,
    plans_dir,
    row_of,
)

from zyg_workflows.arch_assistant_ext.floor_plans.placing import (
    DESIGN_CHECKS,
    _place,
    _plan_transform,
    _side_of,
    check_attributions,
    credits_text,
    record_attribution,
    t_attributions,
)

from zyg_workflows.arch_assistant_ext.floor_plans.tools import (
    _plan_errors,
    _slab_storeys,
    _target,
    _types_text,
    t_core_from_plan,
    t_place_plan,
    t_plan_info,
    t_search_plans,
)

from zyg_workflows.arch_assistant_ext.floor_plans.tiling import (
    BAND_MIN,
    CORRIDOR_MIN,
    DEDUPE_TOL,
    FILL_OK,
    FILL_STEP,
    WALL_T,
    _candidates,
    _dedupe_partitions,
    _fill,
    _free_spans,
    _nearest_depths,
    _orient,
    _rects_overlap,
    _seg_point_dist,
    _unit_rows,
    t_tile_units,
)

from zyg_workflows.arch_assistant_ext.floor_plans.registration import (
    EXAMPLES,
    PROMPT,
    TOOLS,
)
