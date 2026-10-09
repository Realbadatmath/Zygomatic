# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""landmarks_special — one tool, add_landmark, and the fifteen landmark kinds.

Every kind is a SINGLE record placed at the centre of a cell: a landmark is a
whole object, not a kit of parts, so the outliner stays readable and a 60 m
wind turbine costs one line in the drawing. `size` rescales the kind's own
defaults uniformly around its defining dimension (height for the towers and
monuments, radius for the domes, the tent, the gazebo, the wheel and the
stadium) — counts (sails, legs, posts, steps, tiers, cabins, sides, detail)
and the minaret's balcony fraction are never scaled.
"""

from __future__ import annotations

import math

from zyg_workflows.arch_assistant import (
    Drawing,
    cell_centre,
    cell_name,
    parse_cell,
    place_height,
    MATERIALS,
    MAX_OBJECTS,
    _num,
)

KINDS = {
    'windmill': {'h': 12, 'r': 3, 'cap': 2, 'sails': 4, 'sail_len': 8},
    'lighthouse': {'h': 20, 'r_base': 3, 'r_top': 2, 'lantern': 2.5},
    'water_tower': {'h': 15, 'r_tank': 4, 'tank_h': 4, 'legs': 4},
    'silo': {'r': 3, 'h': 12, 'cone': 2},
    'geodesic_dome': {'r': 8, 'detail': 1},
    'tent': {'r': 6, 'h': 5, 'sides': 8},
    'gazebo': {'r': 2.5, 'h': 2.6, 'posts': 6, 'roof_h': 1.2},
    'obelisk': {'h': 10, 'w': 1.2},
    'arch_monument': {'w': 8, 'h': 10, 'd': 3, 'opening_w': 4, 'opening_h': 7},
    'spire': {'r': 3, 'h': 12, 'sides': 8},
    'minaret': {'r': 1.5, 'h': 25, 'balcony': 0.7},
    'stadium_ring': {'rx': 60, 'rz': 45, 'tiers': 3, 'tier_h': 4, 'tier_d': 8},
    'wind_turbine': {'h': 60, 'blade': 30, 'r_mast': 2},
    'pyramid_stepped': {'w': 30, 'steps': 5, 'h': 20},
    'ferris_wheel': {'r': 15, 'cabins': 12},
}
OPENINGS: list = []

# what `size` sets, per kind — the dimension the user means when they say "big"
SIZE_KEY = {
    'windmill': 'h',
    'lighthouse': 'h',
    'water_tower': 'h',
    'silo': 'h',
    'geodesic_dome': 'r',
    'tent': 'r',
    'gazebo': 'r',
    'obelisk': 'h',
    'arch_monument': 'h',
    'spire': 'h',
    'minaret': 'h',
    'stadium_ring': 'rx',
    'wind_turbine': 'h',
    'pyramid_stepped': 'h',
    'ferris_wheel': 'r',
}
# counts and fractions: never multiplied by the size factor
COUNT_KEYS = {'sails', 'legs', 'detail', 'sides', 'posts', 'steps', 'tiers', 'cabins', 'balcony'}

# R7 — REAL SIZES (2026-09-07). A landmark is a real thing: its size is absolute
# metres, never a fraction of the block it stands on. {kind: (lo, hi, what `size`
# is)}; outside the range the tool refuses and says the real range. Kinds that
# are not in the table keep the loose 0.5..400 m guard.
SIZE_RANGE = {
    'windmill': (8.0, 16.0, 'the tower height'),
    'lighthouse': (12.0, 40.0, 'its height'),
    'water_tower': (10.0, 30.0, 'its height'),
    'silo': (6.0, 25.0, 'its height'),
    'wind_turbine': (30.0, 150.0, 'the hub height'),
    'obelisk': (5.0, 40.0, 'its height'),
    'ferris_wheel': (8.0, 40.0, 'its radius'),
}
# a Dutch windmill's sails are a fixed fraction of the tower, never of the block
SAIL_FRACTION = 0.65
SAIL_MAX = 10.0
MILL_MAX_OVERALL = 22.0  # scene rule: tower + sails never passes 22 m


def sail_len_for(tower_h: float) -> float:
    """The sail length that belongs to a tower of `tower_h` metres: 0.65 x the
    tower, never more than 10 m, and never so long that tower + sails passes the
    scene rule of 22 m overall (a real Dutch mill: 12 m tower, ~8 m sails)."""
    return round(min(SAIL_MAX, SAIL_FRACTION * float(tower_h), MILL_MAX_OVERALL - float(tower_h)), 4)


LM_MAT = {
    'windmill': 'mat_brick',
    'lighthouse': 'mat_paint_white',
    'water_tower': 'mat_steel',
    'silo': 'mat_steel',
    'geodesic_dome': 'mat_steel',
    'tent': 'mat_plaster',
    'gazebo': 'mat_timber',
    'obelisk': 'mat_stone',
    'arch_monument': 'mat_stone',
    'spire': 'mat_stone',
    'minaret': 'mat_plaster',
    'stadium_ring': 'mat_concrete',
    'wind_turbine': 'mat_paint_white',
    'pyramid_stepped': 'mat_stone',
    'ferris_wheel': 'mat_steel',
}
LM_LABEL = {
    'windmill': 'windmill',
    'lighthouse': 'lighthouse',
    'water_tower': 'water tower',
    'silo': 'silo',
    'geodesic_dome': 'geodesic dome',
    'tent': 'tent',
    'gazebo': 'gazebo',
    'obelisk': 'obelisk',
    'arch_monument': 'monumental arch',
    'spire': 'spire',
    'minaret': 'minaret',
    'stadium_ring': 'stadium ring',
    'wind_turbine': 'wind turbine',
    'pyramid_stepped': 'stepped pyramid',
    'ferris_wheel': 'ferris wheel',
}

PROMPT = (
    'Landmarks: add_landmark(kind, cell, size, rotation_deg, storey, material, base_height) places ONE whole landmark '
    'at the centre of a cell — a monument or special structure rather than a building: windmill, lighthouse, '
    'water_tower, silo, minaret, wind_turbine (towers — `size` is their height in metres), geodesic_dome, tent, '
    'gazebo, ferris_wheel (`size` is the radius), stadium_ring (`size` is the long semi-axis rx), obelisk, '
    'arch_monument, spire, pyramid_stepped (`size` is the height). A landmark lands on the ground under it (a hill, a '
    "slope, a plateau, a dyke); base_height overrides. A windmill's `size` is the TOWER height and real ones are "
    '8-16 m, with sails 0.65 x the tower (max 10 m) added on top and the overall height is capped at 22 m (the sails '
    'shrink on a tall tower) — sizes are absolute metres, never scaled with the '
    "block, and outside a kind's real range (lighthouse 12-40, water tower 10-30, silo 6-25, wind turbine 30-150, "
    'obelisk 5-40, ferris wheel radius 8-40) the tool refuses. Omit `size` for the sensible default (windmill 12 m '
    'tower with 8 m sails, lighthouse 20 m, wind turbine 60 m). rotation_deg turns it on the plan. One call = one '
    'object.'
)


def _pretty_params(k: str, p: dict) -> str:
    return ', '.join(f'{key} {p[key]:g}' for key in KINDS[k])


def t_add_landmark(
    d: Drawing, a, kind, cell, size=None, rotation_deg=0.0, storey=0, material=None, name='', base_height=None
):
    k = str(kind or '').strip().lower()
    if k not in KINDS:
        return 'refused: "' + str(kind) + '" is not a landmark kind — pick one of ' + ', '.join(sorted(KINDS))
    c, r = parse_cell(cell)  # ValueError -> "refused: ..." in call_tool
    cx, cz = cell_centre(c, r)
    base = KINDS[k]
    skey = SIZE_KEY[k]
    p = dict(base)
    if size is not None and str(size) != '':
        s = _num(size, 0.0)
        rng = SIZE_RANGE.get(k)
        if rng is None:
            if s < 0.5 or s > 400:
                return f'refused: size must be between 0.5 and 400 m ({skey} of a {LM_LABEL[k]}), got {size!r}'
        elif k == 'windmill' and not (rng[0] <= s <= rng[1]):
            return (
                f'refused: a Dutch windmill tower is {rng[0]:g}-{rng[1]:g} m; sails are added on top '
                f'(size is the tower height, got {s:g} m)'
            )
        elif not (rng[0] <= s <= rng[1]):
            return (
                f'refused: a real {LM_LABEL[k]} is {rng[0]:g}-{rng[1]:g} m ({rng[2]}), got {s:g} m — '
                f'real things keep their real size whatever the block around them'
            )
        f = s / float(base[skey])
        p = {key: (v if key in COUNT_KEYS else round(v * f, 4)) for key, v in base.items()}
        if k == 'windmill':  # sails are 0.65 x the tower, capped at 10 m
            p['sail_len'] = sail_len_for(s)
    if len(d.objs) + 1 > MAX_OBJECTS:
        return f'refused: the drawing already holds {MAX_OBJECTS} objects — that is the ceiling'
    st = int(_num(storey, 0))
    ry = math.radians(_num(rotation_deg, 0.0))
    mat = material if material in MATERIALS else LM_MAT[k]
    # R5: a landmark is a POINT thing — it stands on the ground under its centre.
    gy = place_height(d, cx, cz, base_height)
    y = round(gy + st * d.storey_h, 4)
    o = d.new(k, p, cx, cz, y, ry, mat, name=name or f'{LM_LABEL[k]} {cell_name(c, r)}', grp=name or 'landmarks')
    d.selected = [o['id']]
    deg = round(_num(rotation_deg, 0.0)) % 360
    where = (
        f'y {y:g} m'
        if base_height is None or base_height == ''
        else f'y {y:g} m (base_height {_num(base_height, 0.0):g})'
    )
    if base_height in (None, '') and gy > 0.01:
        where += f' — standing on the ground {gy:g} m up'
    return (
        f'placed a {LM_LABEL[k]} as {o["id"]} at {cell_name(c, r)}, storey {st} ({where}), '
        f'{_pretty_params(k, p)}, {mat}' + (f', turned {deg}deg' if deg else '')
    )


TOOLS = [
    (
        {
            'name': 'add_landmark',
            'description': (
                'Place one landmark or special structure at the centre of a cell: a windmill, lighthouse, water '
                'tower, silo, geodesic dome, tent, gazebo, obelisk, monumental arch, spire, minaret, stadium '
                'ring, wind turbine, stepped pyramid or ferris wheel. It lands on the ground under that cell '
                '(a hill, a slope, a dyke); base_height overrides. `size` scales the whole thing uniformly '
                '(absolute metres, never a fraction of the block): the height for towers, monuments and the '
                'pyramid, the radius for the dome, tent, gazebo and wheel, the long semi-axis rx for the '
                "stadium ring. A windmill's size is its TOWER height (8-16 m; sails are 0.65 x that, max "
                '10 m). Leave size out for the default. One call places one object.'
            ),
            'input_schema': {
                'type': 'object',
                'properties': {
                    'kind': {'type': 'string', 'enum': sorted(KINDS)},
                    'cell': {
                        'type': 'string',
                        'description': 'grid cell, e.g. C4 or AB12 — the landmark is centred on it',
                    },
                    'size': {
                        'type': 'number',
                        'description': 'metres; height for towers/monuments (windmill: the TOWER, 8-16 m), radius for domes and the wheel, rx for the stadium ring',
                    },
                    'rotation_deg': {'type': 'number'},
                    'storey': {'type': 'integer'},
                    'material': {'type': 'string', 'enum': MATERIALS},
                    'name': {'type': 'string'},
                    'base_height': {
                        'type': 'number',
                        'description': 'metres; omit to stand on the ground under the cell',
                    },
                },
                'required': ['kind', 'cell'],
            },
        },
        t_add_landmark,
    ),
]

EXAMPLES = [
    {
        'ask': 'zet een molen op D12, tower 14 metres',
        'calls': [{'tool': 'add_landmark', 'args': {'kind': 'windmill', 'cell': 'D12', 'size': 14}}],
    },
    {
        'ask': 'a lighthouse at the end of the pier on AB40, 28 m tall',
        'calls': [{'tool': 'add_landmark', 'args': {'kind': 'lighthouse', 'cell': 'AB40', 'size': 28}}],
    },
    {
        'ask': 'two silos next to the barn at F8 and H8',
        'calls': [
            {'tool': 'add_landmark', 'args': {'kind': 'silo', 'cell': 'F8'}},
            {'tool': 'add_landmark', 'args': {'kind': 'silo', 'cell': 'H8'}},
        ],
    },
    {
        'ask': 'a wind turbine in the polder at CA150, 90 m to the hub',
        'calls': [{'tool': 'add_landmark', 'args': {'kind': 'wind_turbine', 'cell': 'CA150', 'size': 90}}],
    },
    {
        'ask': 'a gazebo in the garden on M22, timber, turned 30 degrees',
        'calls': [
            {
                'tool': 'add_landmark',
                'args': {'kind': 'gazebo', 'cell': 'M22', 'material': 'mat_timber', 'rotation_deg': 30},
            }
        ],
    },
    {
        'ask': 'a windmill on the dyke at R40 — it should stand on top of it, not in it',
        'calls': [{'tool': 'add_landmark', 'args': {'kind': 'windmill', 'cell': 'R40'}}],
    },
    {
        'ask': 'a stadium 160 m long on the field at BB100',
        'calls': [{'tool': 'add_landmark', 'args': {'kind': 'stadium_ring', 'cell': 'BB100', 'size': 80}}],
    },
]
