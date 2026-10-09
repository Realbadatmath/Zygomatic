# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""floor_plans.registration — the TOOLS table, the family PROMPT and the EXAMPLES
the loader reads. Moved verbatim out of floor_plans.py (2026-10-06)."""

from __future__ import annotations

from zyg_workflows.arch_assistant_ext.floor_plans.plan_packs import (
    KINDS_OK,
)
from zyg_workflows.arch_assistant_ext.floor_plans.placing import (
    t_attributions,
)
from zyg_workflows.arch_assistant_ext.floor_plans.tools import (
    t_core_from_plan,
    t_place_plan,
    t_plan_info,
    t_search_plans,
)
from zyg_workflows.arch_assistant_ext.floor_plans.tiling import (
    t_tile_units,
)


# ── registration ─────────────────────────────────────────────────────────────
TOOLS = [
    (
        {
            'name': 'search_plans',
            'description': 'Search the real floor-plan library (Swiss Dwellings, ResPlan, ProcTHOR — all CC BY or '
            'Apache) for a plan that fits a bay. width/depth are cells, or the name of a group whose '
            'slab is the bay. Every row says whether it fits within ±12 % and at what rotation. Use '
            'this before place_plan whenever the user asks for a real apartment, unit, house or floor '
            'layout instead of a generated one.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'kind': {
                        'type': 'string',
                        'enum': list(KINDS_OK),
                        'description': 'unit = one apartment, floor = a whole storey with its core, house = a '
                        'single-family plan',
                    },
                    'width': {'type': 'string', 'description': 'the bay width in cells, or a group name (its slab)'},
                    'depth': {
                        'type': 'string',
                        'description': 'the bay depth in cells (ignored when width is a group)',
                    },
                    'rooms': {'type': 'integer', 'description': 'exact room count wanted'},
                    'types': {
                        'type': 'string',
                        'description': 'comma-separated room types wanted, e.g. "living,kitchen,bedroom,bathroom"',
                    },
                    'pack': {'type': 'string', 'description': 'restrict to one pack'},
                    'limit': {'type': 'integer'},
                    'storey': {'type': 'integer'},
                },
            },
        },
        t_search_plans,
    ),
    (
        {
            'name': 'plan_info',
            'description': 'Everything on record for one plan id: size, room schedule, doors, windows, fixtures, '
            'core, entrance side, source ids and the attribution line that must go in the credits.',
            'input_schema': {'type': 'object', 'properties': {'plan_id': {'type': 'string'}}, 'required': ['plan_id']},
        },
        t_plan_info,
    ),
    (
        {
            'name': 'place_plan',
            'description': 'Draw a real floor plan into a box or onto cells: interior walls become partitions, rooms '
            'become zones, doors and windows and fixtures come with them. The plan is mirrored, '
            'rotated and scaled to fit (only within ±12 % — a plan that needs more is refused, with '
            'the search that finds one that fits). align="centre" centres it, "entrance" turns it so '
            'its front door lands on entrance_side, "core" (floor plans) drops its stair onto the '
            'stair the group already has. The outer walls are dropped inside a box and drawn only '
            'with shell=true (a house on empty cells). Records overlapping the existing stair or lift '
            'are left out. The placement is registered so repeat_floor carries it up the tower, and '
            "the pack's attribution is recorded on the drawing.",
            'input_schema': {
                'type': 'object',
                'properties': {
                    'plan_id': {'type': 'string', 'description': 'an id from search_plans'},
                    'group': {
                        'type': 'string',
                        'description': 'the box to place it in (the name draw_box returned); '
                        'its slab at `storey` is the bay',
                    },
                    'cell_from': {'type': 'string', 'description': 'instead of a group: one corner of the block'},
                    'cell_to': {'type': 'string'},
                    'storey': {'type': 'integer'},
                    'align': {'type': 'string', 'enum': ['centre', 'core', 'entrance']},
                    'entrance_side': {'type': 'string', 'enum': ['north', 'south', 'east', 'west']},
                    'mirror': {'type': 'boolean'},
                    'rotate_deg': {'type': 'integer', 'enum': [0, 90, 180, 270]},
                    'scale': {'type': 'string', 'description': '"fit" (default) or a number'},
                    'snap': {'type': 'number', 'description': 'grid the placed points snap to, default 0.25 m'},
                    'doors': {'type': 'boolean'},
                    'windows': {'type': 'boolean'},
                    'zones': {'type': 'boolean'},
                    'fixtures': {'type': 'boolean'},
                    'shell': {
                        'type': 'boolean',
                        'description': "draw the plan's OUTER walls too — for a house on "
                        'empty cells; leave false inside a box',
                    },
                    'name': {'type': 'string', 'description': 'group name for the placed records'},
                },
                'required': ['plan_id'],
            },
        },
        t_place_plan,
    ),
    (
        {
            'name': 'core_from_plan',
            'description': 'Draw the stair and the lifts WHERE THE FLOOR PLAN HAS THEM, before the plan itself: '
            "the plan's own core polygons are mapped through exactly the transform place_plan "
            'will use on that box, and add_stair / add_elevator are called on the cells they land '
            'on. Use it whenever a floor plan is going into a tower — it is what makes '
            'place_plan(align="core") fit by construction instead of guessing a core cell by hand '
            'and hoping the plan lands on it. Refused when the plan carries no core, when a core '
            "polygon falls outside the box's slab, or when the box already has a stair.",
            'input_schema': {
                'type': 'object',
                'properties': {
                    'plan_id': {'type': 'string', 'description': 'a floor plan id from search_plans(kind="floor")'},
                    'group': {
                        'type': 'string',
                        'description': 'the box the core goes in (the name draw_box returned); its slab is the plate',
                    },
                    'storeys': {
                        'type': 'integer',
                        'description': "how many storeys the core serves; the box's own storey count by default",
                    },
                    'stair_kind': {
                        'type': 'string',
                        'enum': ['straight', 'u', 'winder', 'spiral'],
                        'description': 'default "u" — the kind that climbs a tower with landings',
                    },
                    'width': {'type': 'number', 'description': 'stair width in m, default 1.2'},
                    'lift_w': {'type': 'number', 'description': 'lift shaft width in m, default 1.8'},
                    'lift_d': {'type': 'number', 'description': 'lift shaft depth in m, default 2.0'},
                    'mirror': {'type': 'boolean', 'description': 'pass the SAME mirror you will pass to place_plan'},
                    'rotate_deg': {
                        'type': 'integer',
                        'enum': [0, 90, 180, 270],
                        'description': 'pass the SAME rotation you will pass to place_plan',
                    },
                },
                'required': ['plan_id', 'group'],
            },
        },
        t_core_from_plan,
    ),
    (
        {
            'name': 'tile_units',
            'description': 'Fill a WHOLE floor of a box with real apartments: a corridor down the long axis '
            '(moved beside the stair/lift so the core stands in it), a band of surveyed units '
            'either side, each one chosen because its own depth matches the band, turned and '
            'mirrored so its front door opens onto the corridor, its widths filling the run. One '
            'party wall per shared edge, an entrance door per unit, a corridor zone. This is '
            'layout_floor done with real plans instead of equal generic boxes — use it when the '
            'user wants a floor of real flats, not one plan. The placement is registered so '
            'repeat_floor carries it up the tower, and the pack attribution is recorded.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'group': {'type': 'string', 'description': 'the box to fill (the name draw_box returned)'},
                    'storey': {'type': 'integer'},
                    'corridor_w': {'type': 'number', 'description': 'clear corridor width, default 1.8 m'},
                    'pack': {'type': 'string', 'description': 'which pack the units come from'},
                    'depth_tol': {
                        'type': 'number',
                        'description': "how far a unit's depth may differ from the band, default 0.8 m",
                    },
                    'min_unit_w': {'type': 'number', 'description': 'narrowest unit to use, default 4.5 m'},
                    'max_scale': {
                        'type': 'number',
                        'description': 'how much the last unit of a run may be stretched to close it, default 0.08',
                    },
                    'keep_core': {'type': 'boolean', 'description': 'leave the stair/lift clear, default true'},
                    'name': {'type': 'string', 'description': 'plate name for the placed records'},
                },
                'required': ['group'],
            },
        },
        t_tile_units,
    ),
    (
        {
            'name': 'attributions',
            'description': 'The credit lines this drawing owes, word for word, because real floor plans from the '
            'CC BY library were placed in it. Every pack used appears once, with the plans taken '
            'from it. Use it when the user asks about credits, attribution, licensing, "can I '
            'publish this" or where the plans came from — and read the lines back exactly, they '
            'are a licence condition. design_check reports the same as an INFO finding, and every '
            'export writes them to a .credits.txt beside the file.',
            'input_schema': {'type': 'object', 'properties': {}, 'required': []},
        },
        t_attributions,
    ),
]

PROMPT = (
    'REAL FLOOR PLANS, CC BY, attribution recorded: search_plans(kind="unit"/"floor"/"house", '
    'width=<cells or a group name>, depth, types="living,kitchen,bedroom") searches; plan_info(id) '
    'shows its rooms; place_plan(id, group=<box>, storey=N) draws ONE — partitions, doors, windows, '
    'zones, fixtures — mirrored, rotated, scaled to fit within ±12 %, the box facade left alone '
    '(shell=true adds its outer walls); align="entrance" puts the front door on a side you name, '
    'align="core" lands it on the stair there. First, core_from_plan(id, group=<box>) draws the stair '
    'and lifts where THAT plan has them, so align="core" fits by construction. '
    'tile_units(group=<box>, storey=N) fills a WHOLE floor with real flats: corridor beside the core, '
    'matching-depth units each side. Then repeat_floor(from_storey, to_storey, source_storey=N) '
    'carries it up. attributions() prints the credit lines that MUST be published.'
)
if len(PROMPT) > 900:
    raise RuntimeError(f'PROMPT is {len(PROMPT)} chars (max 900)')

EXAMPLES = [
    {
        'ask': 'put a real apartment floor plan on every floor of the tower',
        'calls': [
            {'tool': 'search_plans', 'args': {'kind': 'floor', 'width': 'tower'}},
            {'tool': 'place_plan', 'args': {'plan_id': 'sd_f_8975', 'group': 'tower', 'storey': 1, 'align': 'core'}},
            {'tool': 'repeat_floor', 'args': {'from_storey': 2, 'to_storey': 8, 'source_storey': 1}},
        ],
    },
    {
        'ask': 'give the tower the stair and lifts that floor plan has, then lay the plan on them',
        'calls': [
            {'tool': 'core_from_plan', 'args': {'plan_id': 'sd_f_8975', 'group': 'tower'}},
            {'tool': 'place_plan', 'args': {'plan_id': 'sd_f_8975', 'group': 'tower', 'storey': 1, 'align': 'core'}},
            {'tool': 'repeat_floor', 'args': {'from_storey': 2, 'to_storey': 8, 'source_storey': 1}},
        ],
    },
    {
        'ask': 'a real two-bedroom flat in that 12 by 10 bay, front door on the north',
        'calls': [
            {
                'tool': 'search_plans',
                'args': {'kind': 'unit', 'width': '12', 'depth': '10', 'types': 'living,kitchen,bedroom,bathroom'},
            },
            {
                'tool': 'place_plan',
                'args': {
                    'plan_id': 'sd_u_026cec6eb950140e3234e62ab041a4ca',
                    'cell_from': 'B2',
                    'cell_to': 'M11',
                    'storey': 0,
                    'align': 'entrance',
                    'entrance_side': 'north',
                },
            },
        ],
    },
    {
        'ask': 'drop a real house plan on the empty plot at C4..P11, walls and all',
        'calls': [
            {'tool': 'search_plans', 'args': {'kind': 'house', 'width': '14', 'depth': '8'}},
            {
                'tool': 'place_plan',
                'args': {'plan_id': 'rp_2707', 'cell_from': 'C4', 'cell_to': 'P11', 'storey': 0, 'shell': True},
            },
        ],
    },
    {
        'ask': 'what is in that plan?',
        'calls': [{'tool': 'plan_info', 'args': {'plan_id': 'sd_u_026cec6eb950140e3234e62ab041a4ca'}}],
    },
    {'ask': 'what do I have to credit if I publish this?', 'calls': [{'tool': 'attributions', 'args': {}}]},
    {
        'ask': 'fill every typical floor of the tower with real apartments off a corridor',
        'calls': [
            {
                'tool': 'tile_units',
                'args': {'group': 'tower', 'storey': 1, 'corridor_w': 1.8, 'pack': 'swiss_dwellings'},
            },
            {'tool': 'repeat_floor', 'args': {'from_storey': 2, 'to_storey': 8, 'source_storey': 1}},
        ],
    },
]
