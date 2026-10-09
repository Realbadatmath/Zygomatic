# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""circulation_rules — can a person actually GET to every floor? (2026-09-10)

Job 71ac02b0's 20-storey tower had, on paper, a stair and two lifts. What it
had in fact was ONE stair_u record of 285 steps — two 39.8 m flights climbing
51.3 m through nineteen slabs and out through the east wall — two 54 m lift
shafts with no doors, and nothing at all reaching the roof deck, where the
infinity pool was. design_check said "0 errors" three times, because every tool
could only see the record it had just made.

Circulation is not a record, it is a RELATION between the storeys of a building
and the things that climb between them. This module measures twelve of them and
owns no kinds and no tools:

  continuity   every floor with a slab is reached by a stair, and by a lift when
               the building is tall enough to need one; the roof deck too, when
               anything but roof plant stands on it.
  flight       a flight is at most 18 steps, and one record spans one storey —
               285 steps in one record is not a stair, it is a ramp to nowhere.
  guarding     a flight has rails, a landing has something along its open edges.
  head house   a stair that arrives on a roof deck arrives INSIDE something.
  core clash   a stair and a lift shaft are two cores: neither stands in the
               other's plan.
  approach     a stair's foot has floor to step onto, not a shaft wall.
  landing      and so does its HEAD: a flight arrives on a landing, not on the
               hole the tool cut for it.
  headroom     the floor above a flight is open over the whole flight.
  enclosure    a stair well on a fitted-out floor is a room, not a sculpture.
  overrun      a lift that serves the top deck has a motor room above it.
  water        no core comes up through the pool.
  lift landing the floor in front of the doors is there, and is empty.

The crossing relation (a stair through a slab with no opening) belongs to
slab_voids.check_voids and is deliberately not repeated here.

Plan axes as everywhere in the studio: column letters along +X, rows along +Z,
north = -Z. Heights are storeys of d.storey_h, counted from the group's own
base (env['y0']), so a building on a hill answers the same as one at y = 0.
"""

from __future__ import annotations

# ruff: noqa: E402,F401
import re

from zyg_workflows import arch_assistant as A
from zyg_workflows.arch_assistant import Drawing, _num
import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)

from zyg_workflows.arch_assistant_ext.circulation_rules import common as common
from zyg_workflows.arch_assistant_ext.circulation_rules import cores as cores
from zyg_workflows.arch_assistant_ext.circulation_rules import floors as floors
from zyg_workflows.arch_assistant_ext.circulation_rules import registry as registry

from zyg_workflows.arch_assistant_ext.circulation_rules.common import KINDS as KINDS
from zyg_workflows.arch_assistant_ext.circulation_rules.common import OPENINGS as OPENINGS
from zyg_workflows.arch_assistant_ext.circulation_rules.common import TOOLS as TOOLS
from zyg_workflows.arch_assistant_ext.circulation_rules.common import STAIR_KINDS as STAIR_KINDS
from zyg_workflows.arch_assistant_ext.circulation_rules.common import SHAFT_KIND as SHAFT_KIND
from zyg_workflows.arch_assistant_ext.circulation_rules.common import DECK_KINDS as DECK_KINDS
from zyg_workflows.arch_assistant_ext.circulation_rules.common import WALL_KINDS as WALL_KINDS
from zyg_workflows.arch_assistant_ext.circulation_rules.common import MAX_FLIGHT as MAX_FLIGHT
from zyg_workflows.arch_assistant_ext.circulation_rules.common import MAX_TURNED as MAX_TURNED
from zyg_workflows.arch_assistant_ext.circulation_rules.common import MAX_SPAN as MAX_SPAN
from zyg_workflows.arch_assistant_ext.circulation_rules.common import LIFT_FROM as LIFT_FROM
from zyg_workflows.arch_assistant_ext.circulation_rules.common import START_TOL as START_TOL
from zyg_workflows.arch_assistant_ext.circulation_rules.common import DECK_BAND as DECK_BAND
from zyg_workflows.arch_assistant_ext.circulation_rules.common import GUARD_H as GUARD_H
from zyg_workflows.arch_assistant_ext.circulation_rules.common import HEAD_MARGIN as HEAD_MARGIN
from zyg_workflows.arch_assistant_ext.circulation_rules.common import LANDING_TOL as LANDING_TOL
from zyg_workflows.arch_assistant_ext.circulation_rules.common import LANDING_DROP as LANDING_DROP
from zyg_workflows.arch_assistant_ext.circulation_rules.common import MAX_FINDINGS as MAX_FINDINGS
from zyg_workflows.arch_assistant_ext.circulation_rules.common import WORD as WORD
from zyg_workflows.arch_assistant_ext.circulation_rules.common import ROOF_PLANT as ROOF_PLANT
from zyg_workflows.arch_assistant_ext.circulation_rules.common import NOT_OCCUPANTS as NOT_OCCUPANTS
from zyg_workflows.arch_assistant_ext.circulation_rules.common import _p as _p
from zyg_workflows.arch_assistant_ext.circulation_rules.common import _env_mod as _env_mod
from zyg_workflows.arch_assistant_ext.circulation_rules.common import _geom as _geom
from zyg_workflows.arch_assistant_ext.circulation_rules.common import _is_guard as _is_guard
from zyg_workflows.arch_assistant_ext.circulation_rules.common import _ranges as _ranges
from zyg_workflows.arch_assistant_ext.circulation_rules.common import _steps as _steps
from zyg_workflows.arch_assistant_ext.circulation_rules.common import stair_height as stair_height
from zyg_workflows.arch_assistant_ext.circulation_rules.common import stair_reach as stair_reach
from zyg_workflows.arch_assistant_ext.circulation_rules.common import lift_reach as lift_reach
from zyg_workflows.arch_assistant_ext.circulation_rules.common import _in_env as _in_env
from zyg_workflows.arch_assistant_ext.circulation_rules.common import _group_records as _group_records
from zyg_workflows.arch_assistant_ext.circulation_rules.common import _floors as _floors
from zyg_workflows.arch_assistant_ext.circulation_rules.common import deck_occupants as deck_occupants
from zyg_workflows.arch_assistant_ext.circulation_rules.common import _cap as _cap
from zyg_workflows.arch_assistant_ext.circulation_rules.cores import check_continuity as check_continuity
from zyg_workflows.arch_assistant_ext.circulation_rules.cores import _flight_phrase as _flight_phrase
from zyg_workflows.arch_assistant_ext.circulation_rules.cores import check_flights as check_flights
from zyg_workflows.arch_assistant_ext.circulation_rules.cores import _landing_open_edges as _landing_open_edges
from zyg_workflows.arch_assistant_ext.circulation_rules.cores import check_stair_guarding as check_stair_guarding
from zyg_workflows.arch_assistant_ext.circulation_rules.cores import check_head_house as check_head_house
from zyg_workflows.arch_assistant_ext.circulation_rules.cores import CORE_KINDS as CORE_KINDS
from zyg_workflows.arch_assistant_ext.circulation_rules.cores import APPROACH_BLOCKERS as APPROACH_BLOCKERS
from zyg_workflows.arch_assistant_ext.circulation_rules.cores import CLASH_TOL as CLASH_TOL
from zyg_workflows.arch_assistant_ext.circulation_rules.cores import _stairs_mod as _stairs_mod
from zyg_workflows.arch_assistant_ext.circulation_rules.cores import _word as _word
from zyg_workflows.arch_assistant_ext.circulation_rules.cores import _core_span as _core_span
from zyg_workflows.arch_assistant_ext.circulation_rules.cores import _overlap as _overlap
from zyg_workflows.arch_assistant_ext.circulation_rules.cores import _clash_key as _clash_key
from zyg_workflows.arch_assistant_ext.circulation_rules.cores import check_core_clash as check_core_clash
from zyg_workflows.arch_assistant_ext.circulation_rules.cores import check_stair_approach as check_stair_approach
from zyg_workflows.arch_assistant_ext.circulation_rules.floors import LANDING_TOL_Y as LANDING_TOL_Y
from zyg_workflows.arch_assistant_ext.circulation_rules.floors import LANDING_VOID as LANDING_VOID
from zyg_workflows.arch_assistant_ext.circulation_rules.floors import HEADROOM_MIN as HEADROOM_MIN
from zyg_workflows.arch_assistant_ext.circulation_rules.floors import ENCLOSE_M as ENCLOSE_M
from zyg_workflows.arch_assistant_ext.circulation_rules.floors import ENCLOSE_RUN as ENCLOSE_RUN
from zyg_workflows.arch_assistant_ext.circulation_rules.floors import ENCLOSE_OPEN as ENCLOSE_OPEN
from zyg_workflows.arch_assistant_ext.circulation_rules.floors import ENCLOSE_TALL as ENCLOSE_TALL
from zyg_workflows.arch_assistant_ext.circulation_rules.floors import ENCLOSE_FITTED as ENCLOSE_FITTED
from zyg_workflows.arch_assistant_ext.circulation_rules.floors import OVERRUN_MIN as OVERRUN_MIN
from zyg_workflows.arch_assistant_ext.circulation_rules.floors import LIFT_LANDING_M as LIFT_LANDING_M
from zyg_workflows.arch_assistant_ext.circulation_rules.floors import LANDING_BLOCK as LANDING_BLOCK
from zyg_workflows.arch_assistant_ext.circulation_rules.floors import LIFT_CLEAR_W as LIFT_CLEAR_W
from zyg_workflows.arch_assistant_ext.circulation_rules.floors import ENCLOSE_KINDS as ENCLOSE_KINDS
from zyg_workflows.arch_assistant_ext.circulation_rules.floors import SLAB_KINDS as SLAB_KINDS
from zyg_workflows.arch_assistant_ext.circulation_rules.floors import POOL_KINDS as POOL_KINDS
from zyg_workflows.arch_assistant_ext.circulation_rules.floors import _voids_mod as _voids_mod
from zyg_workflows.arch_assistant_ext.circulation_rules.floors import _rect_inter as _rect_inter
from zyg_workflows.arch_assistant_ext.circulation_rules.floors import _rect_area as _rect_area
from zyg_workflows.arch_assistant_ext.circulation_rules.floors import _storey_of as _storey_of
from zyg_workflows.arch_assistant_ext.circulation_rules.floors import _group_env as _group_env
from zyg_workflows.arch_assistant_ext.circulation_rules.floors import _biggest_void as _biggest_void
from zyg_workflows.arch_assistant_ext.circulation_rules.floors import _cells_of as _cells_of
from zyg_workflows.arch_assistant_ext.circulation_rules.floors import check_landing_floor as check_landing_floor
from zyg_workflows.arch_assistant_ext.circulation_rules.floors import check_headroom as check_headroom
from zyg_workflows.arch_assistant_ext.circulation_rules.floors import _open_sides as _open_sides
from zyg_workflows.arch_assistant_ext.circulation_rules.floors import check_enclosure as check_enclosure
from zyg_workflows.arch_assistant_ext.circulation_rules.floors import check_overrun as check_overrun
from zyg_workflows.arch_assistant_ext.circulation_rules.floors import _deck_reported as _deck_reported
from zyg_workflows.arch_assistant_ext.circulation_rules.floors import _core_ids as _core_ids
from zyg_workflows.arch_assistant_ext.circulation_rules.floors import check_shaft_in_water as check_shaft_in_water
from zyg_workflows.arch_assistant_ext.circulation_rules.floors import _landing_rect as _landing_rect
from zyg_workflows.arch_assistant_ext.circulation_rules.floors import _landing_gap as _landing_gap
from zyg_workflows.arch_assistant_ext.circulation_rules.floors import check_lift_landing as check_lift_landing
from zyg_workflows.arch_assistant_ext.circulation_rules.registry import DESIGN_CHECKS as DESIGN_CHECKS
from zyg_workflows.arch_assistant_ext.circulation_rules.registry import PROMPT as PROMPT
from zyg_workflows.arch_assistant_ext.circulation_rules.registry import EXAMPLES as EXAMPLES
