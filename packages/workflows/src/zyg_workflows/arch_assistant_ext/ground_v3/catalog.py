# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""ground_v3: the TOOLS registrations and the EXAMPLES the assistant is shown."""

from __future__ import annotations


from zyg_workflows.arch_assistant import (
    MATERIALS,
)

from .tools import (
    t_make_ground,
    t_raise_ground,
    t_lower_ground,
    t_level_ground,
    t_describe_ground,
)


TOOLS = [
    (
        {
            'name': 'make_ground',
            'description': 'THE ground: one sculpted heightfield the whole drawing shares. Lay it first, before any '
            "landform or building. style 'flat' is a level field, 'gentle' a garden roll (1.5 m of "
            "relief), 'rolling' real country (5 m). Every hill, valley, river bed, lake bed and "
            'building pad after this is a SCULPT of this one surface, not a solid on top of it. '
            'A drawing has exactly one ground; a second call is refused.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'cell_from': {'type': 'string'},
                    'cell_to': {'type': 'string'},
                    'style': {'type': 'string', 'enum': ['flat', 'gentle', 'rolling']},
                    'seed': {'type': 'number'},
                    'snow_height': {'type': 'number'},
                    'water_level': {'type': 'number'},
                    'material': {'type': 'string', 'enum': MATERIALS},
                    'name': {'type': 'string'},
                },
                'required': ['cell_from', 'cell_to'],
            },
        },
        t_make_ground,
    ),
    (
        {
            'name': 'raise_ground',
            'description': 'Lift a block of the ground into a landform, blended into the land at its rim. '
            "shape 'peak' is a rocky summit (0.25-1.0 x its radius tall), 'ridge' a long crest along "
            "the block's longer side, 'mesa' a flat-topped table mountain (at most 0.8 x its radius). "
            'Needs a ground: call make_ground first.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'cell_from': {'type': 'string'},
                    'cell_to': {'type': 'string'},
                    'height': {'type': 'number'},
                    'shape': {'type': 'string', 'enum': ['peak', 'ridge', 'mesa']},
                    'seed': {'type': 'number'},
                    'name': {'type': 'string'},
                },
                'required': ['cell_from', 'cell_to', 'height'],
            },
        },
        t_raise_ground,
    ),
    (
        {
            'name': 'lower_ground',
            'description': "Dig a block of the ground out, walls following the land it cuts through. shape 'valley' "
            "is a trough along the block's longer side (a river runs down it; profile 0 is a V, 1 a U), "
            "'basin' is a lake bed with a wobbled shore. At most 0.4 x the block's narrow side deep. "
            'Needs a ground.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'cell_from': {'type': 'string'},
                    'cell_to': {'type': 'string'},
                    'depth': {'type': 'number'},
                    'shape': {'type': 'string', 'enum': ['valley', 'basin']},
                    'profile': {'type': 'number'},
                    'seed': {'type': 'number'},
                    'name': {'type': 'string'},
                },
                'required': ['cell_from', 'cell_to', 'depth'],
            },
        },
        t_lower_ground,
    ),
    (
        {
            'name': 'level_ground',
            'description': 'Flatten a block of the ground to one height, cut AND fill, battered into the land at its '
            'edges — the flatten for a building footprint, a car park or a level lawn. Leave `level` '
            'out and it takes the mean ground there. Needs a ground.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'cell_from': {'type': 'string'},
                    'cell_to': {'type': 'string'},
                    'level': {'type': 'number'},
                    'name': {'type': 'string'},
                },
                'required': ['cell_from', 'cell_to'],
            },
        },
        t_level_ground,
    ),
    (
        {
            'name': 'describe_ground',
            'description': 'What the ground is: its extent in cells, its lowest and highest point, its water and snow '
            'lines, and every sculpt shaping it. Read it before shaping the land further.',
            'input_schema': {'type': 'object', 'properties': {}},
        },
        t_describe_ground,
    ),
]

EXAMPLES = [
    {
        'ask': 'give me real ground over the whole site, C4 to CV200, rolling country',
        'calls': [{'tool': 'make_ground', 'args': {'cell_from': 'C4', 'cell_to': 'CV200', 'style': 'rolling'}}],
    },
    {
        'ask': 'a 90 m mountain on the block from K20 to CG116',
        'calls': [
            {'tool': 'raise_ground', 'args': {'cell_from': 'K20', 'cell_to': 'CG116', 'height': 90, 'shape': 'peak'}}
        ],
    },
    {
        'ask': 'cut a valley 25 m deep from A60 to EL60 for the river',
        'calls': [
            {'tool': 'lower_ground', 'args': {'cell_from': 'A60', 'cell_to': 'EL60', 'depth': 25, 'shape': 'valley'}}
        ],
    },
    {
        'ask': 'flatten D40 to N50 for the farmhouse',
        'calls': [{'tool': 'level_ground', 'args': {'cell_from': 'D40', 'cell_to': 'N50'}}],
    },
    {'ask': 'how high does the land get?', 'calls': [{'tool': 'describe_ground', 'args': {}}]},
]
