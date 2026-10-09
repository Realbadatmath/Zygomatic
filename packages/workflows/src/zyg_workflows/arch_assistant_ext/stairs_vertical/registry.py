# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""stairs_vertical.registry — the TOOLS schemas and the EXAMPLES the planner reads.

Verbatim sections of the original stairs_vertical.py (lines 893-1036).
"""

from __future__ import annotations

from zyg_workflows.arch_assistant_ext.stairs_vertical.constants import MATERIALS, STAIR_KINDS
from zyg_workflows.arch_assistant_ext.stairs_vertical.tools import (
    t_add_elevator,
    t_add_escalator,
    t_add_fire_escape,
    t_add_stair,
)


TOOLS = [
    (
        {
            'name': 'add_stair',
            'description': 'add_stair(cell, from_storey, to_storey=<storeys> to reach the roof deck) draws one stair per storey, cuts the floor openings, adds rails, builds the head house when it reaches the deck. The rise is solved per storey so each flight lands exactly on the floor above. kind: u (two flights round a landing — the normal stairwell), winder (quarter turn), spiral (round, for towers); straight has no landing, so it is refused over 3 storeys or more. direction_deg turns it on the plan (0 = east, 90 = north); the stair must stand inside the building and clear of its facades. Refused when its plan, or the 1.2 m of floor at its foot (its -X side), meets a lift shaft.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'cell': {'type': 'string'},
                    'from_storey': {'type': 'integer'},
                    'to_storey': {'type': 'integer'},
                    'kind': {'type': 'string', 'enum': list(STAIR_KINDS)},
                    'direction_deg': {'type': 'number'},
                    'width': {'type': 'number'},
                    'material': {'type': 'string', 'enum': MATERIALS},
                    'name': {'type': 'string'},
                },
                'required': ['cell'],
            },
        },
        t_add_stair,
    ),
    (
        {
            'name': 'add_elevator',
            'description': 'A lift, goods hoist or service core: a shaft from from_storey to the top of to_storey with a door on EVERY served storey, a 1.5 m overrun above the top served deck for the motor room, a car, and a floor opening cut through every floor the shaft passes. to_storey = the storey count serves the roof deck. door_side is the shaft face the doors open onto (north is -Z, the small rows). The cell must be inside a building and the shaft clear of its facades. Refused when the shaft meets a stair, the 1.2 m of floor at a stair foot, or another shaft — a 1.2 m u stair is 3.4 x 2.6 m: lift centres >= 4 cells west or >= 3 cells east of its cell, never in front of its foot.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'cell': {'type': 'string'},
                    'from_storey': {'type': 'integer'},
                    'to_storey': {'type': 'integer'},
                    'w': {'type': 'number'},
                    'depth': {'type': 'number'},
                    'car': {'type': 'boolean'},
                    'door_side': {'type': 'string', 'enum': ['north', 'south', 'east', 'west']},
                    'material': {'type': 'string', 'enum': MATERIALS},
                    'name': {'type': 'string'},
                },
                'required': ['cell'],
            },
        },
        t_add_elevator,
    ),
    (
        {
            'name': 'add_fire_escape',
            'description': 'An external fire-escape stair hung on a FACADE: one straight flight plus a landing per storey, alternating direction, the flights running along the wall. Pass group (the name draw_box returned) and side (north/south/east/west) — a fire escape is outside the plan, so a cell inside a building is refused. storeys defaults to the building. Use when the user asks for a fire escape, an outside stair or an escape stair.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'group': {'type': 'string'},
                    'side': {'type': 'string', 'enum': ['north', 'south', 'east', 'west']},
                    'storeys': {'type': 'integer'},
                    'cell': {'type': 'string'},
                    'direction_deg': {'type': 'number'},
                    'width': {'type': 'number'},
                    'material': {'type': 'string', 'enum': MATERIALS},
                    'name': {'type': 'string'},
                },
                'required': [],
            },
        },
        t_add_fire_escape,
    ),
    (
        {
            'name': 'add_escalator',
            'description': 'An escalator bank between two storeys at a 30 degree pitch by default. One flight per storey: a span of several storeys is stacked, each flight reversed so the bank keeps one footprint. The horizontal run follows from the rise, so each flight needs floor space: 2.7 m of rise is about 4.7 m of run.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'cell': {'type': 'string'},
                    'from_storey': {'type': 'integer'},
                    'to_storey': {'type': 'integer'},
                    'direction_deg': {'type': 'number'},
                    'width': {'type': 'number'},
                    'angle': {'type': 'number'},
                    'material': {'type': 'string', 'enum': MATERIALS},
                    'name': {'type': 'string'},
                },
                'required': ['cell'],
            },
        },
        t_add_escalator,
    ),
]

EXAMPLES = [
    {
        'ask': 'put a stairwell on H12, ground floor to the first floor',
        'calls': [{'tool': 'add_stair', 'args': {'cell': 'H12', 'from_storey': 0, 'to_storey': 1, 'kind': 'u'}}],
    },
    {
        'ask': 'run the stair core of the 20-storey tower all the way up to the roof deck, at FH96',
        'calls': [
            {
                'tool': 'add_stair',
                'args': {'cell': 'FH96', 'from_storey': 0, 'to_storey': 20, 'kind': 'u', 'width': 1.2},
            }
        ],
    },
    {
        'ask': 'a spiral stair 1.1 m wide in the tower at D30, from the ground to the third floor',
        'calls': [
            {
                'tool': 'add_stair',
                'args': {'cell': 'D30', 'from_storey': 0, 'to_storey': 3, 'kind': 'spiral', 'width': 1.1},
            }
        ],
    },
    {
        'ask': 'a lift in the core at K18 serving the ground floor up to floor 5',
        'calls': [
            {'tool': 'add_elevator', 'args': {'cell': 'K18', 'from_storey': 0, 'to_storey': 5, 'w': 1.8, 'depth': 2.0}}
        ],
    },
    {
        'ask': 'two lifts at FD96 and FK96 serving every floor of the 20-storey tower including the roof deck',
        'calls': [
            {'tool': 'add_elevator', 'args': {'cell': 'FD96', 'from_storey': 0, 'to_storey': 20, 'door_side': 'south'}},
            {'tool': 'add_elevator', 'args': {'cell': 'FK96', 'from_storey': 0, 'to_storey': 20, 'door_side': 'south'}},
        ],
    },
    {
        'ask': 'add a fire escape on the north side of the tower',
        'calls': [{'tool': 'add_fire_escape', 'args': {'group': 'tower', 'side': 'north'}}],
    },
    {
        'ask': 'add a fire escape on the back of the block, 4 storeys',
        'calls': [{'tool': 'add_fire_escape', 'args': {'group': 'block', 'side': 'north', 'storeys': 4, 'width': 1.2}}],
    },
    {
        'ask': 'an escalator from the shop floor to the first floor at F9, pointing north',
        'calls': [
            {'tool': 'add_escalator', 'args': {'cell': 'F9', 'from_storey': 0, 'to_storey': 1, 'direction_deg': 90}}
        ],
    },
    {
        'ask': 'escalators from the ground up to the third floor of the mall at F9',
        'calls': [{'tool': 'add_escalator', 'args': {'cell': 'F9', 'from_storey': 0, 'to_storey': 3}}],
    },
]
