# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""zyg_workflows.arch_assistant_ext.water_leisure.tools — _BASE_H, the TOOLS registration table and EXAMPLES.

Moved verbatim out of water_leisure.py (lines 1606-1909); zero logic changes.
"""

from __future__ import annotations

from zyg_workflows.arch_assistant_ext.water_leisure.base import MATERIALS, SPORTS

from zyg_workflows.arch_assistant_ext.water_leisure.pool import t_add_pool

from zyg_workflows.arch_assistant_ext.water_leisure.infinity import t_add_infinity_pool

from zyg_workflows.arch_assistant_ext.water_leisure.leisure import (
    t_add_beach_set,
    t_add_canal,
    t_add_fountain,
    t_add_playground,
    t_add_pond,
    t_add_sports_court,
)


_BASE_H = {
    'type': 'number',
    'description': 'Level to stand on, in metres. Leave it out and the record lands on the ground under it.',
}

TOOLS = [
    (
        {
            'name': 'add_pool',
            'description': 'A swimming pool over a block of cells: the basin fills the block exactly, the floor sits `depth` below the water level and the coping rim stands just above the terrace. On the GROUND it is sunk and REFUSES ground that varies more than 0.5 m across the block — water lies level. On a ROOF or SLAB it lands on the DECK (roof y + thickness; a base_height inside the slab is lifted) and stands RAISED with its walls showing, unless sunk=true. infinity puts a glass overflow weir on the deck edge facing the view. Use for gardens, hotels, rooftops.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'cell_from': {'type': 'string'},
                    'cell_to': {'type': 'string'},
                    'depth': {'type': 'number'},
                    'coping': {'type': 'number'},
                    'storey': {
                        'type': 'integer',
                        'description': 'the storey whose deck this stands on — storey 20 on a 20-storey box is the roof deck; instead of base_height',
                    },
                    'base_height': _BASE_H,
                    'raised': {
                        'type': ['number', 'string'],
                        'description': 'Metres the rim stands above the deck/ground. Leave out for auto: 0 on the ground (a sunk basin), depth on a deck (the basin stands on the roof).',
                    },
                    'sunk': {
                        'type': 'boolean',
                        'description': 'On a deck, allow raised < depth — the basin cuts into the storey below (a plant storey). Default false: raised is clamped to depth.',
                    },
                    'infinity': {
                        'type': 'string',
                        'enum': ['none', 'north', 'south', 'east', 'west'],
                        'description': 'The overflow edge: that wall has no coping, its top is the water level, drawn as a glass weir with a catch trough outside. On a deck it must be the deck edge (moved onto it when within 1.5 m). The roof edge behind it still needs a glass guard >= 1.1 m — add_infinity_pool builds the whole thing.',
                    },
                    'steps': {
                        'type': 'string',
                        'enum': ['none', 'north', 'south', 'east', 'west'],
                        'description': 'The side the entry steps descend from (0.3 m treads inside the basin). Never the infinity side.',
                    },
                    'material': {'type': 'string', 'enum': MATERIALS},
                    'name': {'type': 'string'},
                },
                'required': ['cell_from', 'cell_to'],
            },
        },
        t_add_pool,
    ),
    (
        {
            'name': 'add_infinity_pool',
            'description': 'A ROOFTOP INFINITY POOL built correctly and luxuriously in one call (the rules of explain("infinity pool")): the basin over the block with deck-level water (level="deck": the rim 0.12 m proud, the tank hanging into the storey below, a "pool tank + balance tank + plant" zone registered there; level="raised" keeps the basin standing on the deck), the glass overflow weir on the `view` side with its 0.5 m catch trough (the pool edge is moved onto the deck edge; refused when more than 1.5 m from it), a frameless glass balustrade 1.1 m along that deck edge OUTBOARD of the trough (an existing parapet there is turned glass and raised to 1.1 m), entry steps on the deck side, a row of sun loungers facing the view with parasols behind them, two palms at the ends of the row, a fire-pit lounge (sofa + 2 armchairs) on a free side, four warm underwater lights on the deck side, and a deep-blue small-format tile (material="turquoise" or "charcoal", or any material id). Each part is skipped with a note when the deck has no room for it. Needs a flat roof or slab under the block: draw_box(..., roof="flat") first; storey=<storeys> names the roof deck. Use for "infinity pool", "rooftop pool", "luxurious pool on the roof".',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'cell_from': {'type': 'string'},
                    'cell_to': {'type': 'string'},
                    'view': {
                        'type': 'string',
                        'enum': ['north', 'south', 'east', 'west'],
                        'description': 'The side the water falls away towards — the skyline or sea side. Default south.',
                    },
                    'storey': {
                        'type': 'integer',
                        'description': 'the storey whose deck this stands on — storey 20 on a 20-storey box is the roof deck; instead of base_height',
                    },
                    'base_height': _BASE_H,
                    'depth': {
                        'type': 'number',
                        'description': 'Swimming depth, 1.0-2.0 m; 1.4 by default (the rule is 1.2-1.5 uniform).',
                    },
                    'level': {
                        'type': 'string',
                        'enum': ['deck', 'raised'],
                        'description': '"deck": the water meets the walking surface and the tank hangs into the storey below (the pictures). "raised": the basin stands on the deck with its walls showing.',
                    },
                    'loungers': {'type': 'boolean'},
                    'parasols': {'type': 'boolean'},
                    'palms': {'type': 'boolean'},
                    'lounge': {
                        'type': 'boolean',
                        'description': 'fire pit + sofa + 2 armchairs on a free side (default true)',
                    },
                    'lights': {
                        'type': 'boolean',
                        'description': 'four warm underwater point lights (default true; 32 lamps is the budget)',
                    },
                    'material': {
                        'type': 'string',
                        'description': 'basin tile: "blue" (default, acg_Tiles135A), "turquoise", "charcoal", or any material id',
                    },
                    'name': {'type': 'string'},
                },
                'required': ['cell_from', 'cell_to'],
            },
        },
        t_add_infinity_pool,
    ),
    (
        {
            'name': 'add_pond',
            'description': 'An elliptical garden pond around a centre cell. radius is the half-width across x, radius_z the half-width across z (leave it out for a circle). It lands on the ground under it and REFUSES ground that varies more than 0.5 m across the pond — a small pond fits on a slope where a big one does not.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'centre': {'type': 'string'},
                    'radius': {'type': 'number'},
                    'radius_z': {'type': 'number'},
                    'depth': {'type': 'number'},
                    'base_height': _BASE_H,
                    'material': {'type': 'string', 'enum': MATERIALS},
                    'name': {'type': 'string'},
                },
                'required': ['centre'],
            },
        },
        t_add_pond,
    ),
    (
        {
            'name': 'add_canal',
            'description': 'A canal or water channel along a chain of cells: one straight reach between each pair of consecutive cells, so three cells give a bend. Quay walls both sides, water surface just below ground. Each reach lands on the ground and is REFUSED when the ground differs more than 0.5 m between its two ends or across it — a canal is level water; use add_stream or add_river for water that flows.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'cells': {'type': 'array', 'items': {'type': 'string'}},
                    'width': {'type': 'number'},
                    'depth': {'type': 'number'},
                    'base_height': _BASE_H,
                    'material': {'type': 'string', 'enum': MATERIALS},
                    'name': {'type': 'string'},
                },
                'required': ['cells'],
            },
        },
        t_add_canal,
    ),
    (
        {
            'name': 'add_fountain',
            'description': 'A tiered fountain on a centre cell: a round basin, a stem and `tiers` overflowing bowls, `height` tall in total. It stands on the ground under it and refuses ground that varies more than 0.5 m under the basin. Use on squares, in courtyards, at the head of an axis.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'centre': {'type': 'string'},
                    'radius': {'type': 'number'},
                    'tiers': {'type': 'integer'},
                    'height': {'type': 'number'},
                    'storey': {
                        'type': 'integer',
                        'description': 'the storey whose deck this stands on — storey 20 on a 20-storey box is the roof deck; instead of base_height',
                    },
                    'base_height': _BASE_H,
                    'material': {'type': 'string', 'enum': MATERIALS},
                    'name': {'type': 'string'},
                },
                'required': ['centre'],
            },
        },
        t_add_fountain,
    ),
    (
        {
            'name': 'add_sports_court',
            'description': 'A paved sports court filling a block of cells, with painted lines. football adds goal posts at both ends of the long axis; tennis adds a net across the middle; basketball is the court alone. The court lies on the ground under it and REFUSES ground steeper than 3 % or more than 0.3 m off a plane — call flatten_pad first on sloping ground.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'cell_from': {'type': 'string'},
                    'cell_to': {'type': 'string'},
                    'sport': {'type': 'string', 'enum': list(SPORTS)},
                    'lines': {'type': 'boolean'},
                    'base_height': _BASE_H,
                    'material': {'type': 'string', 'enum': MATERIALS},
                    'name': {'type': 'string'},
                },
                'required': ['cell_from', 'cell_to'],
            },
        },
        t_add_sports_court,
    ),
    (
        {
            'name': 'add_playground',
            'description': 'A childrens playground inside a block of cells: a slide along one edge, a swing frame opposite it and a sandpit at the far side. Needs at least 6 x 6 cells. Every piece stands upright on the ground under itself, so the set follows a slope.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'cell_from': {'type': 'string'},
                    'cell_to': {'type': 'string'},
                    'base_height': _BASE_H,
                    'material': {'type': 'string', 'enum': MATERIALS},
                    'name': {'type': 'string'},
                },
                'required': ['cell_from', 'cell_to'],
            },
        },
        t_add_playground,
    ),
    (
        {
            'name': 'add_beach_set',
            'description': 'A sun lounger and a parasol on every cell in the list — a poolside terrace, a beach, a hotel roof deck. Set umbrellas false for loungers alone. Each piece sits on the deck under itself (a roof cell = the roof deck), else the ground.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'cells': {'type': 'array', 'items': {'type': 'string'}},
                    'umbrellas': {'type': 'boolean'},
                    'storey': {
                        'type': 'integer',
                        'description': 'the storey whose deck this stands on — storey 20 on a 20-storey box is the roof deck; instead of base_height',
                    },
                    'base_height': _BASE_H,
                    'material': {'type': 'string', 'enum': MATERIALS},
                    'name': {'type': 'string'},
                },
                'required': ['cells'],
            },
        },
        t_add_beach_set,
    ),
]

EXAMPLES = [
    {
        'ask': 'put a 10 by 4 metre swimming pool in the back garden, cells F12 to O15, 1.4 m deep',
        'calls': [{'tool': 'add_pool', 'args': {'cell_from': 'F12', 'cell_to': 'O15', 'depth': 1.4}}],
    },
    {
        'ask': 'a pond about 8 by 6 metres around K20, with two loungers and parasols on K18 and L18',
        'calls': [
            {'tool': 'add_pond', 'args': {'centre': 'K20', 'radius': 4, 'radius_z': 3}},
            {'tool': 'add_beach_set', 'args': {'cells': ['K18', 'L18']}},
        ],
    },
    {
        'ask': 'dig a 6 m canal from D10 east to H10 and then north to H14',
        'calls': [{'tool': 'add_canal', 'args': {'cells': ['D10', 'H10', 'H14'], 'width': 6, 'depth': 1.5}}],
    },
    {
        'ask': 'a football pitch on A20 to AD35 with goals',
        'calls': [{'tool': 'add_sports_court', 'args': {'cell_from': 'A20', 'cell_to': 'AD35', 'sport': 'football'}}],
    },
    {
        'ask': 'a playground on the square B2 to I9 and a fountain in the middle of E5',
        'calls': [
            {'tool': 'add_playground', 'args': {'cell_from': 'B2', 'cell_to': 'I9'}},
            {'tool': 'add_fountain', 'args': {'centre': 'E5', 'radius': 2, 'tiers': 3}},
        ],
    },
    {
        'ask': 'a tennis court on the sloping field D40 to X55',
        'calls': [
            {'tool': 'flatten_pad', 'args': {'cell_from': 'D40', 'cell_to': 'X55'}},
            {'tool': 'add_sports_court', 'args': {'cell_from': 'D40', 'cell_to': 'X55', 'sport': 'tennis'}},
        ],
    },
    {'ask': 'a pond on the hillside at M30', 'calls': [{'tool': 'add_pond', 'args': {'centre': 'M30', 'radius': 2}}]},
    {
        'ask': 'a luxurious infinity pool on the roof of the 20-storey tower, view south',
        'core': True,
        'calls': [
            {
                'tool': 'draw_box',
                'args': {'cell_from': 'EX141', 'cell_to': 'FQ160', 'storeys': 20, 'roof': 'flat', 'name': 'tower'},
            },
            {
                'tool': 'add_infinity_pool',
                'args': {'cell_from': 'FB150', 'cell_to': 'FM160', 'view': 'south', 'storey': 20},
            },
            {'tool': 'add_parapet', 'args': {'group': 'tower', 'height': 1.1}},
        ],
    },
    {
        'ask': 'an infinity pool on the roof, edge to the west, no lounge furniture',
        'calls': [
            {
                'tool': 'add_infinity_pool',
                'args': {'cell_from': 'FB145', 'cell_to': 'FF158', 'view': 'west', 'storey': 12, 'lounge': False},
            }
        ],
    },
    {
        'ask': 'just the basin with a west weir and steps on the east side',
        'calls': [
            {
                'tool': 'add_pool',
                'args': {
                    'cell_from': 'FB145',
                    'cell_to': 'FN160',
                    'depth': 1.4,
                    'coping': 0.3,
                    'infinity': 'west',
                    'steps': 'east',
                    'storey': 20,
                },
            }
        ],
    },
    {
        'ask': 'a sunken pool in the garden',
        'calls': [{'tool': 'add_pool', 'args': {'cell_from': 'F12', 'cell_to': 'O15', 'depth': 1.5}}],
    },
]
