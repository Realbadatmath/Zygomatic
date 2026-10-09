# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""site_landscape.tool_schema — the tool schemas and the worked examples.

Moved verbatim out of the 1,180-line site_landscape.py; original lines
971-1180.
"""

from __future__ import annotations

from zyg_workflows.arch_assistant import MATERIALS

from zyg_workflows.arch_assistant_ext.site_landscape.constants import (
    BED_KINDS,
    FENCE_KINDS,
    FURNITURE_KINDS,
    TREE_KINDS,
)

from zyg_workflows.arch_assistant_ext.site_landscape.site_tools import (
    t_add_curved_road,
    t_add_fence,
    t_add_garden_bed,
    t_add_parking,
    t_add_road,
    t_add_street_furniture,
    t_plant_trees,
)

_CELL = {'type': 'string'}
_CELL_LIST = {'type': 'array', 'items': {'type': 'string'}}
_BASE = {
    'type': 'number',
    'description': 'Override the ground: a literal y in metres. Leave it out and the '
    'record lands on the hill, slope or plateau under it.',
}

TOOLS = [
    (
        {
            'name': 'plant_trees',
            'description': 'Plant trees over a block of cells: on a grid at `spacing` metres, or `count` trees scattered by a seeded generator. kind is tree_deciduous (6-20 m, round crown), tree_conifer (8-25 m, cone), tree_palm (5-15 m) or the plain tree. By default each tree is a REAL life-size pack model (photoscanned, scaled to `height`); model="parametric" gives the sphere-on-a-trunk placeholder for a sketch. Trees are kept a crown apart and the block must have room for them (a refusal names the block size that fits). No tree stands in a carriageway: a block that puts one within half the road width + 0.3 m of a road centreline is refused, naming the offset (half the width + 0.5 m) to plant at instead. Every tree lands on the ground under its own trunk. Same seed = same positions.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'cell_from': _CELL,
                    'cell_to': _CELL,
                    'spacing': {'type': 'number'},
                    'count': {'type': 'integer'},
                    'kind': {'type': 'string', 'enum': list(TREE_KINDS)},
                    'height': {'type': 'number'},
                    'jitter': {'type': 'number'},
                    'seed': {'type': 'integer'},
                    'base_height': _BASE,
                    'model': {'type': 'string', 'enum': ['real', 'parametric']},
                    'material': {'type': 'string', 'enum': MATERIALS},
                    'name': {'type': 'string'},
                },
                'required': ['cell_from', 'cell_to'],
            },
        },
        t_plant_trees,
    ),
    (
        {
            'name': 'add_fence',
            'description': 'A fence or a hedge running through a list of cells: one straight segment between each pair of consecutive cell centres, each sitting on the ground at its centre and leaning down the slope it crosses (a leg steeper than 15% is cut into 5 m pieces). Use for garden boundaries, site hoarding, a clipped hedge along a drive.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'cells': _CELL_LIST,
                    'kind': {'type': 'string', 'enum': list(FENCE_KINDS)},
                    'height': {'type': 'number'},
                    'base_height': _BASE,
                    'material': {'type': 'string', 'enum': MATERIALS},
                    'name': {'type': 'string'},
                },
                'required': ['cells'],
            },
        },
        t_add_fence,
    ),
    (
        {
            'name': 'add_parking',
            'description': 'Tile a block of cells with marked parking bays — as many whole bays as fit. direction "x" puts the bays side by side along x, "z" turns them a quarter turn. Refused on ground that is not near level (more than 0.5 m off a plane or steeper than 8%): flatten_pad it first.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'cell_from': _CELL,
                    'cell_to': _CELL,
                    'bay_w': {'type': 'number'},
                    'bay_d': {'type': 'number'},
                    'direction': {'type': 'string', 'enum': ['x', 'z']},
                    'material': {'type': 'string', 'enum': MATERIALS},
                    'base_height': _BASE,
                    'name': {'type': 'string'},
                },
                'required': ['cell_from', 'cell_to'],
            },
        },
        t_add_parking,
    ),
    (
        {
            'name': 'add_road',
            'description': 'Straight carriageway through a list of cells, one piece per leg, `width` metres wide, each piece on the ground at its centre and running downhill. Use for a street, a drive, an access road.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'cells': _CELL_LIST,
                    'width': {'type': 'number'},
                    'material': {'type': 'string', 'enum': MATERIALS},
                    'base_height': _BASE,
                    'name': {'type': 'string'},
                },
                'required': ['cells'],
            },
        },
        t_add_road,
    ),
    (
        {
            'name': 'add_curved_road',
            'description': 'One arc of carriageway around a centre cell: radius in metres, from start_deg to end_deg on the plan (0 = east, 90 = north, counter-clockwise). It takes the ground height at the centre and leans onto the ground plane there. Use for a bend, a roundabout leg, a curved drive.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'centre': _CELL,
                    'radius': {'type': 'number'},
                    'start_deg': {'type': 'number'},
                    'end_deg': {'type': 'number'},
                    'width': {'type': 'number'},
                    'material': {'type': 'string', 'enum': MATERIALS},
                    'base_height': _BASE,
                    'name': {'type': 'string'},
                },
                'required': ['centre'],
            },
        },
        t_add_curved_road,
    ),
    (
        {
            'name': 'add_street_furniture',
            'description': 'One lamp post (3-6 m, 4 m by default), bench or litter bin on each cell in the list, all turned by rotation_deg, each standing on the ground under it. A lamp post is a REAL pack model by default (model="parametric" for the plain pole). Lamp posts obey the site: a cell under a canopy or awning plate — or within 1 m of its edge — is refused, naming the cells to use instead; a cell in the carriageway — closer than half the road width + 0.3 m to a road centreline — is refused, naming the offset (half the width + 0.5 m) to stand at; and a lamp within 6 m of a canopy is clamped to 0.5 m under its soffit, so a 5 m lamp beside a 4.2 m porte-cochere becomes 3.7 m and the reply says so.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'cells': _CELL_LIST,
                    'kind': {'type': 'string', 'enum': list(FURNITURE_KINDS)},
                    'rotation_deg': {'type': 'number'},
                    'height': {'type': 'number'},
                    'base_height': _BASE,
                    'model': {'type': 'string', 'enum': ['real', 'parametric']},
                    'material': {'type': 'string', 'enum': MATERIALS},
                    'name': {'type': 'string'},
                },
                'required': ['cells'],
            },
        },
        t_add_street_furniture,
    ),
    (
        {
            'name': 'add_garden_bed',
            'description': 'Plant a block of cells: one flowerbed sized to the block (tilted onto the ground plane, tiled when the ground is not planar), one hedge along its longer side, or shrubs on a 1.5 m grid, each shrub upright on the ground under it.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'cell_from': _CELL,
                    'cell_to': _CELL,
                    'kind': {'type': 'string', 'enum': list(BED_KINDS)},
                    'material': {'type': 'string', 'enum': MATERIALS},
                    'base_height': _BASE,
                    'name': {'type': 'string'},
                },
                'required': ['cell_from', 'cell_to'],
            },
        },
        t_add_garden_bed,
    ),
]

EXAMPLES = [
    {
        'ask': 'plant trees in the back garden, C10 to N21, about 6 m apart',
        'calls': [
            {
                'tool': 'plant_trees',
                'args': {'cell_from': 'C10', 'cell_to': 'N21', 'spacing': 6, 'kind': 'tree_deciduous', 'height': 7},
            }
        ],
    },
    {
        'ask': 'a 1.8 m fence around the plot from B4 to B20 to R20',
        'calls': [{'tool': 'add_fence', 'args': {'cells': ['B4', 'B20', 'R20'], 'kind': 'fence', 'height': 1.8}}],
    },
    {
        'ask': '20 parking spaces next to the office, F30 to Q39',
        'calls': [
            {
                'tool': 'add_parking',
                'args': {'cell_from': 'F30', 'cell_to': 'Q39', 'bay_w': 2.5, 'bay_d': 5, 'direction': 'x'},
            }
        ],
    },
    {
        'ask': 'a 6 m street along the front from A25 to Z25, bending 90 degrees around AB25',
        'calls': [
            {'tool': 'add_road', 'args': {'cells': ['A25', 'Z25'], 'width': 6}},
            {
                'tool': 'add_curved_road',
                'args': {'centre': 'AB25', 'radius': 12, 'start_deg': 0, 'end_deg': 90, 'width': 6},
            },
        ],
    },
    {
        'ask': 'lamp posts on D26, J26 and P26 and a bench on G26',
        'calls': [
            {'tool': 'add_street_furniture', 'args': {'cells': ['D26', 'J26', 'P26'], 'kind': 'lamp_post'}},
            {'tool': 'add_street_furniture', 'args': {'cells': ['G26'], 'kind': 'bench', 'rotation_deg': 90}},
        ],
    },
    {
        'ask': 'a flower bed along the terrace, E12 to K13',
        'calls': [{'tool': 'add_garden_bed', 'args': {'cell_from': 'E12', 'cell_to': 'K13', 'kind': 'flowerbed'}}],
    },
    {
        'ask': 'plant conifers up the hillside and run a fence down it',
        'calls': [
            {
                'tool': 'plant_trees',
                'args': {'cell_from': 'C10', 'cell_to': 'N21', 'count': 30, 'kind': 'tree_conifer', 'height': 14},
            },
            {'tool': 'add_fence', 'args': {'cells': ['C10', 'C21'], 'kind': 'fence', 'height': 1.2}},
        ],
    },
]
