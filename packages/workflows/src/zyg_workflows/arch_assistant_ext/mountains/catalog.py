# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""mountains: the TOOLS registrations and the EXAMPLES the assistant is shown."""

from __future__ import annotations


from zyg_workflows.arch_assistant import (
    MATERIALS,
)

from .plumbing import (
    _STYLES,
)

from .tools import (
    t_add_mountain,
    t_add_mountain_range,
    t_add_ridge,
    t_add_valley,
)


TOOLS = [
    (
        {
            'name': 'add_mountain',
            'description': "ONE mountain centred on a cell. style 'peak' is a rocky summit with a snow cap (height IS the summit, radius is half the foot), 'volcano' is a cone with a crater, 'mesa' is a flat-topped table mountain with grass on top. Height must be 0.25 to 1.0 x radius (0.8 for a mesa) — flatter than that is add_hill. Mountains are ground: draw them before the buildings, and they land on whatever ground is already there. On a drawing with a ground (make_ground) a peak or mesa is SCULPTED into that one heightfield and snow_line sets nothing (the ground's own snow height rules); a volcano stays a solid, because a crater is not a sculpt kind yet.",
            'input_schema': {
                'type': 'object',
                'properties': {
                    'centre': {'type': 'string'},
                    'radius': {'type': 'number'},
                    'height': {'type': 'number'},
                    'style': {'type': 'string', 'enum': list(_STYLES)},
                    'ruggedness': {'type': 'number'},
                    'seed': {'type': 'number'},
                    'snow_line': {
                        'description': "0..1, the fraction of the height snow starts at; 'auto' (the default) caps only a summit 60 m or more above its base, at 0.75; 'none' for bare rock"
                    },
                    'base_height': {
                        'type': 'number',
                        'description': 'leave it out and the mountain sits on the ground under its centre',
                    },
                    'material': {'type': 'string', 'enum': MATERIALS},
                    'name': {'type': 'string'},
                },
                'required': ['centre'],
            },
        },
        t_add_mountain,
    ),
    (
        {
            'name': 'add_mountain_range',
            'description': 'A chain of peaks filling a block of cells, sized to the block and turned to run along its longer side. Use it for a horizon or a backdrop behind a site; height is the highest summit and is capped by the peak radius (0.65 x length / peaks) — leave it out for 0.7 of that. On a drawing with a ground it writes ONE SCULPTED SUMMIT PER PEAK into that heightfield, not one range solid.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'cell_from': {'type': 'string'},
                    'cell_to': {'type': 'string'},
                    'height': {'type': 'number'},
                    'peaks': {'type': 'number'},
                    'seed': {'type': 'number'},
                    'snow_line': {
                        'description': "0..1; 'auto' (the default) caps only a summit 60 m or more above its base, at 0.75; 'none' for bare rock"
                    },
                    'ruggedness': {'type': 'number'},
                    'base_height': {
                        'type': 'number',
                        'description': 'leave it out and the range sits on the ground under it',
                    },
                    'material': {'type': 'string', 'enum': MATERIALS},
                    'name': {'type': 'string'},
                },
                'required': ['cell_from', 'cell_to'],
            },
        },
        t_add_mountain_range,
    ),
    (
        {
            'name': 'add_ridge',
            'description': 'A sharp grassy crest with a triangular section through a list of cells: one ridge between each pair (3 cells = 2 ridges). height is the crest and is at most 0.8 x width, which is foot to foot. On a drawing with a ground each crest is sculpted into that heightfield instead.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'cells': {'type': 'array', 'items': {'type': 'string'}},
                    'height': {'type': 'number'},
                    'width': {'type': 'number'},
                    'ruggedness': {'type': 'number'},
                    'seed': {'type': 'number'},
                    'base_height': {
                        'type': 'number',
                        'description': 'leave it out and each ridge sits on the ground under it',
                    },
                    'material': {'type': 'string', 'enum': MATERIALS},
                    'name': {'type': 'string'},
                },
                'required': ['cells'],
            },
        },
        t_add_ridge,
    ),
    (
        {
            'name': 'add_valley',
            'description': "A grass trough over a block of cells with a soil floor between two rising sides. direction is the axis the valley RUNS along, profile 'v' is a cleft and 'u' a glacial trough. depth is at most 0.4 x the distance across; leave it out for 0.35 of that. Draw it before a river, which runs along the floor. On a drawing with a ground it CUTS DOWN into that one heightfield — a real hollow, not a raised trough.",
            'input_schema': {
                'type': 'object',
                'properties': {
                    'cell_from': {'type': 'string'},
                    'cell_to': {'type': 'string'},
                    'depth': {'type': 'number'},
                    'direction': {'type': 'string', 'enum': ['x', 'z']},
                    'profile': {'type': 'string', 'enum': ['v', 'u']},
                    'floor_width': {'type': 'number'},
                    'base_height': {
                        'type': 'number',
                        'description': 'leave it out and the valley sits on the ground under it',
                    },
                    'material': {'type': 'string', 'enum': MATERIALS},
                    'name': {'type': 'string'},
                },
                'required': ['cell_from', 'cell_to'],
            },
        },
        t_add_valley,
    ),
]

EXAMPLES = [
    {
        'ask': 'put a mountain 120 m across and 40 m high at F40',
        'calls': [{'tool': 'add_mountain', 'args': {'centre': 'F40', 'radius': 60, 'height': 40}}],
    },
    {
        'ask': 'a snow-capped peak behind the chalet at P60, 200 m wide, 90 m tall, snow on the top quarter',
        'calls': [{'tool': 'add_mountain', 'args': {'centre': 'P60', 'radius': 100, 'height': 90, 'snow_line': 0.75}}],
    },
    {
        'ask': 'give the site a mountain range on the horizon from A1 to KN60, 35 m high with 5 peaks',
        'calls': [
            {'tool': 'add_mountain_range', 'args': {'cell_from': 'A1', 'cell_to': 'KN60', 'height': 35, 'peaks': 5}}
        ],
    },
    {
        'ask': 'a valley running north-south from D10 to AX70 for the river, 15 m deep with a 25 m floor',
        'calls': [
            {
                'tool': 'add_valley',
                'args': {'cell_from': 'D10', 'cell_to': 'AX70', 'depth': 15, 'direction': 'z', 'floor_width': 25},
            }
        ],
    },
    {
        'ask': 'a rocky ridge along E20, K20 and K34, 18 m high',
        'calls': [
            {
                'tool': 'add_ridge',
                'args': {'cells': ['E20', 'K20', 'K34'], 'height': 18, 'width': 25, 'material': 'mat_rock'},
            }
        ],
    },
    {
        'ask': 'a volcano at M50, 100 m across, and a mesa at T50 of the same size, both standing on the 20 m plateau',
        'calls': [
            {
                'tool': 'add_mountain',
                'args': {'centre': 'M50', 'radius': 50, 'height': 35, 'style': 'volcano', 'base_height': 20},
            },
            {
                'tool': 'add_mountain',
                'args': {'centre': 'T50', 'radius': 50, 'height': 25, 'style': 'mesa', 'base_height': 20},
            },
        ],
    },
]
