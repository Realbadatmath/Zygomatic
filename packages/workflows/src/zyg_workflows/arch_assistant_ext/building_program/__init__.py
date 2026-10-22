# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""building_program — the BUILD CHECKLIST, resolved in one call (2026-09-08).

The operator's rule: "a building of 3+ storeys has elevators — build elevators?
yes — select elevator type. A building always has an entrance."  That is a
checklist, and the obvious way to run it is to ask the user each question in
turn.  It is also the one way that cannot work here:

  · `ask_user` PARKS the whole job and injects nothing until the answer comes
    back, so ten questions are ten round trips;
  · the job has 28 turns total (MAX_CALLS) and the last 20-storey tower already
    spent 27 of them, 784 s and 1.26M cached tokens.

So the checklist is not a conversation.  `plan_building()` resolves the whole
program deterministically in ONE call — every required item with its default
already chosen — and hands back a build order.  The genuine either/ors come
back as one DECIDE block with defaults marked, to be batched into a single
ask_user only when the request asked to be consulted.  "Just build it" costs
zero questions.

The program is then STATE: it lives in `doc.ext.building_program`, so it
survives the job, the injection and the save, and a later request continues the
same checklist instead of guessing again.  `check_program` is a design check,
so `done` refuses while a REQUIRED item is missing — a rule the model can read
and skip is not a rule (measured: it routed around plant_trees the moment
plant_trees refused).

Numbers here are conventional practice, not code citations; each item names the
`spec()` sheet that carries the detail and the sources.
No new kinds.  Two tools.
"""

from __future__ import annotations

import math
import re

# Sections in the EXACT original declaration order.
from zyg_workflows.arch_assistant_ext.building_program.evidence import (
    ANCILLARY_ROOF,
    DENSITY,
    DOORS,
    Drawing,
    EXT_KEY,
    KINDS,
    LIFTS,
    OPENINGS,
    ROOFS,
    STAIRS,
    TREES,
    USES,
    _A,
    _count,
    _ev_lift,
    _ev_plant,
    _ev_roof_access,
    _ev_second_escape,
    _ev_stair,
    _far_apart,
    _groups,
    _hit,
    _names,
    _num,
    _reach_y,
    _reaches_top,
    _shafts_to_top,
    _stair_stack,
    _storeys_reached,
    _top_deck,
    _top_storey,
    block_bounds,
    cell_name,
    parse_cell,
    resolve_block,
)
from zyg_workflows.arch_assistant_ext.building_program.request_items import (
    BALCONY_WORDS,
    DECK_FURNITURE,
    FINISH_KINDS,
    FLAT_PRESETS,
    GLASS_OK_KINDS,
    INTERIOR_KINDS,
    LIGHT_KINDS,
    LOBBY_ACROSS_M,
    LOBBY_DEEP_M,
    LOBBY_WORDS,
    SEATS,
    SEAT_WORDS,
    _ev_balconies,
    _ev_corridor,
    _ev_deck_furniture,
    _ev_finishes,
    _ev_lobby,
    _ev_roof_pool,
    _ev_typical_floors,
    _how_typical_floors,
    _laid_out,
    _lobby_contents,
    _room_rect,
    _room_span,
    _room_spans,
    _seat_kind,
    _shell_records,
)
from zyg_workflows.arch_assistant_ext.building_program.checklist import (
    BY_KEY,
    ITEMS,
    _R,
    _macro,
)
from zyg_workflows.arch_assistant_ext.building_program.resolving import (
    NOUNS,
    REQUEST_RULES,
    _amenity_item,
    _ctx,
    _ev_ctx,
    _row,
    _short_title,
    get_program,
    item_for,
    read_request,
    resolve,
    status,
)
from zyg_workflows.arch_assistant_ext.building_program.tools import (
    DESIGN_CHECKS,
    EXAMPLES,
    PROMPT,
    TOOLS,
    _fmt,
    check_program,
    t_plan_building,
    t_program_status,
)
from zyg_workflows.arch_assistant_ext.building_program import (
    evidence,
    request_items,
    checklist,
    resolving,
    tools,
)

__all__ = [
    'math',
    're',
    'ANCILLARY_ROOF',
    'DENSITY',
    'DOORS',
    'Drawing',
    'EXT_KEY',
    'KINDS',
    'LIFTS',
    'OPENINGS',
    'ROOFS',
    'STAIRS',
    'TREES',
    'USES',
    '_A',
    '_count',
    '_ev_lift',
    '_ev_plant',
    '_ev_roof_access',
    '_ev_second_escape',
    '_ev_stair',
    '_far_apart',
    '_groups',
    '_hit',
    '_names',
    '_num',
    '_reach_y',
    '_reaches_top',
    '_shafts_to_top',
    '_stair_stack',
    '_storeys_reached',
    '_top_deck',
    '_top_storey',
    'block_bounds',
    'cell_name',
    'parse_cell',
    'resolve_block',
    'BALCONY_WORDS',
    'DECK_FURNITURE',
    'FINISH_KINDS',
    'FLAT_PRESETS',
    'GLASS_OK_KINDS',
    'INTERIOR_KINDS',
    'LIGHT_KINDS',
    'LOBBY_ACROSS_M',
    'LOBBY_DEEP_M',
    'LOBBY_WORDS',
    'SEATS',
    'SEAT_WORDS',
    '_ev_balconies',
    '_ev_corridor',
    '_ev_deck_furniture',
    '_ev_finishes',
    '_ev_lobby',
    '_ev_roof_pool',
    '_ev_typical_floors',
    '_how_typical_floors',
    '_laid_out',
    '_lobby_contents',
    '_room_rect',
    '_room_span',
    '_room_spans',
    '_seat_kind',
    '_shell_records',
    'BY_KEY',
    'ITEMS',
    '_R',
    '_macro',
    'NOUNS',
    'REQUEST_RULES',
    '_amenity_item',
    '_ctx',
    '_ev_ctx',
    '_row',
    '_short_title',
    'get_program',
    'item_for',
    'read_request',
    'resolve',
    'status',
    'DESIGN_CHECKS',
    'EXAMPLES',
    'PROMPT',
    'TOOLS',
    '_fmt',
    'check_program',
    't_plan_building',
    't_program_status',
    'evidence',
    'request_items',
    'checklist',
    'resolving',
    'tools',
]
