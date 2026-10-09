# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""furniture_kitchen_bath — the assistant's kitchen, bathroom and utility tools.

Conventions (the same as furniture_living): a piece's record x/z is the CENTRE
of its footprint, its bottom sits at y = storey * storey_h, and it FACES local
-Z. A unit standing against the NORTH wall of a room (the low-z side, up in the
top view) therefore carries ry = PI so that its front looks back into the room.

Kitchens are wall runs, not scatterings: `_wall_frame` turns a side name into
(ry, wall length, a point(u, back) function), where u runs along the wall from
its low end and `back` is the distance from the wall face to the piece's
centre. Every tool below places its furniture with that one helper, so a run
against the east wall is the same arithmetic as one against the north wall.
"""

from __future__ import annotations

import math

from zyg_workflows.arch_assistant import MATERIALS, MAX_OBJECTS, Drawing, _num, block_bounds, cell_name, parse_cell

KINDS = {
    'kitchen_counter': {'len': 2.0, 'd': 0.6, 'h': 0.9, 'top': 0.04},
    'kitchen_island': {'w': 2.0, 'd': 0.9, 'h': 0.9},
    'wall_cabinet': {'len': 1.2, 'd': 0.35, 'h': 0.7},
    'sink': {'w': 0.6, 'd': 0.5, 'h': 0.9},
    'stove': {'w': 0.6, 'd': 0.6, 'h': 0.9},
    'fridge': {'w': 0.7, 'd': 0.7, 'h': 1.8},
    'dishwasher': {'w': 0.6, 'd': 0.6, 'h': 0.85},
    'washing_machine': {'w': 0.6, 'd': 0.6, 'h': 0.85},
    'toilet': {'w': 0.4, 'd': 0.7, 'h': 0.8},
    'bathtub': {'w': 0.75, 'l': 1.7, 'h': 0.55},
    'shower': {'w': 0.9, 'd': 0.9, 'h': 2.0, 'tray': 0.05},
    'washbasin': {'w': 0.6, 'd': 0.45, 'h': 0.85},
    'mirror': {'w': 0.6, 'h': 0.8, 't': 0.02},
    'towel_rail': {'len': 0.6},
    'boiler': {'r': 0.3, 'h': 1.2},
}
OPENINGS: list = []

PROMPT = (
    'Kitchens and bathrooms: furnish_kitchen(cell_from, cell_to, side, island) fits a counter run '
    'along one wall of a block (side = the wall it stands against: north, south, east or west), with a '
    'fridge, dishwasher, sink and cooker inline and wall cabinets 1.5 m up; ask for island=true only in a '
    'room at least 4 m deep. furnish_bathroom(cell_from, cell_to, door_side, bath, shower) fits a toilet, '
    'a washbasin with a mirror over it, a bath along the longest free wall and a shower in the far corner '
    '(the corner needs 2.5 x 2.5 m); door_side is the wall the door is in, so nothing is placed there. '
    'add_utility(cell_from, cell_to) is the laundry: washing machine, boiler and a short counter. '
    'Draw the room (draw_box / add_room) first, then furnish it; each tool takes a cell block and a storey.'
)

_SIDES = ('north', 'south', 'east', 'west')
_OPPOSITE = {'north': 'south', 'south': 'north', 'east': 'west', 'west': 'east'}


def _wall_frame(side: str, xmin, zmin, xmax, zmax):
    """side -> (ry, wall length, point(u, back) -> (x, z), room depth from it).

    u runs along the wall from its low end (low x for north/south, low z for
    east/west); `back` is the distance from the wall INTO the room."""
    W, D = xmax - xmin, zmax - zmin
    if side == 'north':  # the low-z wall; the room is to +z, so the piece faces +z
        return math.pi, W, (lambda u, back: (xmin + u, zmin + back)), D
    if side == 'south':
        return 0.0, W, (lambda u, back: (xmin + u, zmax - back)), D
    if side == 'west':
        return -math.pi / 2, D, (lambda u, back: (xmin + back, zmin + u)), W
    return math.pi / 2, D, (lambda u, back: (xmax - back, zmin + u)), W


def _mat(m, default='mat_timber'):
    return m if m in MATERIALS else default


def _room(cell_from, cell_to):
    xmin, zmin, xmax, zmax = block_bounds(cell_from, cell_to)
    return xmin, zmin, xmax, zmax, cell_name(*parse_cell(cell_from)), cell_name(*parse_cell(cell_to))


def t_furnish_kitchen(
    d: Drawing, a, cell_from, cell_to, storey=0, side='north', island=False, material='mat_timber', name=''
):
    xmin, zmin, xmax, zmax, ca, cb = _room(cell_from, cell_to)
    side = str(side or 'north').strip().lower()
    if side not in _SIDES:
        return 'refused: side must be north, south, east or west'
    ry, wall_len, pt, depth = _wall_frame(side, xmin, zmin, xmax, zmax)
    run = round(wall_len - 0.2, 4)
    if run < 1.2:
        return f'refused: the {side} wall is only {wall_len:g} m — a kitchen run needs at least 1.4 m'
    st = int(_num(storey, 0))
    y = st * d.storey_h
    mat = _mat(material)
    grp = str(name or f'kitchen {ca}-{cb}')
    if len(d.objs) + 12 > MAX_OBJECTS:
        return f'refused: a kitchen is up to 12 objects and the drawing may hold {MAX_OBJECTS} in total'

    x, z = pt(wall_len / 2, 0.3)
    counter = d.new(
        'kitchen_counter',
        {'len': run, 'd': 0.6, 'h': 0.9, 'top': 0.04},
        x,
        z,
        y,
        ry,
        mat,
        name=f'counter run ({side})',
        grp=grp,
    )

    line = [
        ('fridge', 0.7, 0.7, 'mat_steel'),
        ('dishwasher', 0.6, 0.6, 'mat_steel'),
        ('sink', 0.6, 0.5, 'mat_steel'),
        ('stove', 0.6, 0.6, 'mat_steel'),
    ]
    u, app = 0.1, []
    for kind, w, dep, amat in line:
        if u + w > wall_len - 0.1:
            break
        x, z = pt(u + w / 2, dep / 2)
        p = dict(KINDS[kind])
        app.append(d.new(kind, p, x, z, y, ry, amat, name=kind.replace('_', ' '), grp=grp)['id'])
        u += w

    cab_from, cab_to = 0.8, wall_len - 0.1
    cabs = []
    span = cab_to - cab_from
    if span >= 0.6:
        n = max(1, int(round(span / 1.2)))
        seg = span / n
        for i in range(n):
            x, z = pt(cab_from + (i + 0.5) * seg, 0.175)
            cabs.append(
                d.new(
                    'wall_cabinet',
                    {'len': round(seg, 4), 'd': 0.35, 'h': 0.7},
                    x,
                    z,
                    y + 1.5,
                    ry,
                    mat,
                    name=f'wall cabinet {i + 1}',
                    grp=grp,
                )['id']
            )

    isl = None
    note = ''
    if island:
        if depth >= 4.0:
            x, z = pt(wall_len / 2, 1.95)
            isl = d.new('kitchen_island', {'w': 2.0, 'd': 0.9, 'h': 0.9}, x, z, y, ry, mat, name='island', grp=grp)[
                'id'
            ]
        else:
            note = f'; no island — the room is only {depth:g} m deep and an island wants 4 m'
    return (
        f'furnished kitchen "{grp}" on the {side} wall of {ca}..{cb}, storey {st}: counter {counter["id"]} '
        f'{run:g} m long, {len(app)} appliances ({", ".join(app)}), {len(cabs)} wall cabinets at 1.5 m'
        + (f', island {isl}' if isl else '')
        + note
    )


def t_furnish_bathroom(
    d: Drawing,
    a,
    cell_from,
    cell_to,
    storey=0,
    door_side='south',
    bath=True,
    shower=True,
    material='mat_paint_white',
    name='',
):
    xmin, zmin, xmax, zmax, ca, cb = _room(cell_from, cell_to)
    door_side = str(door_side or 'south').strip().lower()
    if door_side not in _SIDES:
        return 'refused: door_side must be north, south, east or west'
    W, D = xmax - xmin, zmax - zmin
    if min(W, D) < 1.4:
        return f'refused: {W:g} x {D:g} m is too small for a bathroom — 1.4 m is the minimum side'
    st = int(_num(storey, 0))
    y = st * d.storey_h
    mat = _mat(material, 'mat_paint_white')
    grp = str(name or f'bathroom {ca}-{cb}')
    if len(d.objs) + 6 > MAX_OBJECTS:
        return f'refused: the drawing may hold {MAX_OBJECTS} objects in total'

    # the bath takes the longest wall that is not the door's; ties go to the wall opposite the door
    order = [_OPPOSITE[door_side]] + [s for s in _SIDES if s not in (door_side, _OPPOSITE[door_side])]
    bath_wall = max(order, key=lambda s: (_wall_frame(s, xmin, zmin, xmax, zmax)[1], -order.index(s)))
    bry, blen, bpt, _bd = _wall_frame(bath_wall, xmin, zmin, xmax, zmax)
    made = []

    u_free = 0.1
    if bath:
        L = round(min(1.7, blen - 0.2), 4)
        x, z = bpt(0.1 + L / 2, 0.375)
        made.append(d.new('bathtub', {'w': 0.75, 'l': L, 'h': 0.55}, x, z, y, bry, mat, name='bath', grp=grp)['id'])
        u_free = 0.1 + L

    if shower and W >= 2.5 and D >= 2.5 and (blen - 0.1 - u_free) >= 1.0:
        x, z = bpt(blen - 0.1 - 0.45, 0.45)
        made.append(
            d.new(
                'shower',
                {'w': 0.9, 'd': 0.9, 'h': 2.0, 'tray': 0.05},
                x,
                z,
                y,
                bry,
                'mat_glass',
                name='shower',
                grp=grp,
            )['id']
        )

    free = [s for s in _SIDES if s not in (door_side, bath_wall)] or [_OPPOSITE[bath_wall]]
    t_side = free[0]
    b_side = free[-1] if len(free) > 1 else free[0]

    ry, wlen, pt, _dep = _wall_frame(t_side, xmin, zmin, xmax, zmax)
    x, z = pt(max(0.4, wlen - 0.6), 0.35)
    made.append(d.new('toilet', {'w': 0.4, 'd': 0.7, 'h': 0.8}, x, z, y, ry, mat, name='toilet', grp=grp)['id'])

    ry, wlen, pt, _dep = _wall_frame(b_side, xmin, zmin, xmax, zmax)
    ub = wlen / 2 if b_side != t_side else max(0.4, wlen * 0.25)
    x, z = pt(ub, 0.225)
    made.append(d.new('washbasin', {'w': 0.6, 'd': 0.45, 'h': 0.85}, x, z, y, ry, mat, name='washbasin', grp=grp)['id'])
    x, z = pt(ub, 0.02)
    made.append(
        d.new('mirror', {'w': 0.6, 'h': 0.8, 't': 0.02}, x, z, y + 1.2, ry, 'mat_glass', name='mirror', grp=grp)['id']
    )
    x, z = pt(min(max(ub + 0.75, 0.4), wlen - 0.4), 0.06)
    made.append(d.new('towel_rail', {'len': 0.6}, x, z, y + 1.3, ry, 'mat_steel', name='towel rail', grp=grp)['id'])

    kinds = [o['kind'] for o in d.objs if o['id'] in made]
    return (
        f'furnished bathroom "{grp}" in {ca}..{cb} ({W:g} x {D:g} m), storey {st}, door on the {door_side}: '
        f'{len(made)} pieces {made[0]}..{made[-1]} — {", ".join(kinds)}; bath on the {bath_wall} wall, '
        f'toilet on the {t_side} wall, basin and mirror (1.2 m) on the {b_side} wall'
    )


def t_add_utility(d: Drawing, a, cell_from, cell_to, storey=0, side='north', material='mat_timber', name=''):
    xmin, zmin, xmax, zmax, ca, cb = _room(cell_from, cell_to)
    side = str(side or 'north').strip().lower()
    if side not in _SIDES:
        return 'refused: side must be north, south, east or west'
    ry, wall_len, pt, _depth = _wall_frame(side, xmin, zmin, xmax, zmax)
    run = round(wall_len - 0.2, 4)
    if run < 1.2:
        return f'refused: the {side} wall is only {wall_len:g} m — a utility run needs at least 1.4 m'
    st = int(_num(storey, 0))
    y = st * d.storey_h
    mat = _mat(material)
    grp = str(name or f'utility {ca}-{cb}')
    if len(d.objs) + 3 > MAX_OBJECTS:
        return f'refused: the drawing may hold {MAX_OBJECTS} objects in total'

    x, z = pt(wall_len / 2, 0.3)
    counter = d.new(
        'kitchen_counter',
        {'len': run, 'd': 0.6, 'h': 0.9, 'top': 0.04},
        x,
        z,
        y,
        ry,
        mat,
        name='utility counter',
        grp=grp,
    )
    x, z = pt(0.4, 0.3)
    wm = d.new(
        'washing_machine', {'w': 0.6, 'd': 0.6, 'h': 0.85}, x, z, y, ry, 'mat_steel', name='washing machine', grp=grp
    )
    x, z = pt(max(0.4, wall_len - 0.4), 0.35)
    bo = d.new('boiler', {'r': 0.3, 'h': 1.2}, x, z, y + 0.8, ry, 'mat_steel', name='boiler', grp=grp)
    return (
        f'utility "{grp}" on the {side} wall of {ca}..{cb}, storey {st}: washing machine {wm["id"]}, '
        f'boiler {bo["id"]} hung at 0.8 m, counter {counter["id"]} {run:g} m long (3 objects)'
    )


_CELLS = {'cell_from': {'type': 'string'}, 'cell_to': {'type': 'string'}, 'storey': {'type': 'integer'}}

TOOLS = [
    (
        {
            'name': 'furnish_kitchen',
            'description': 'Fit a kitchen into a cell block: a counter run along one wall (side = north, south, east '
            'or west) with a fridge, dishwasher, sink and cooker inline, wall cabinets 1.5 m above the '
            'floor, and an island when the room is at least 4 m deep.',
            'input_schema': {
                'type': 'object',
                'properties': dict(
                    _CELLS,
                    **{
                        'side': {'type': 'string', 'enum': list(_SIDES)},
                        'island': {'type': 'boolean'},
                        'material': {'type': 'string', 'enum': MATERIALS},
                        'name': {'type': 'string'},
                    },
                ),
                'required': ['cell_from', 'cell_to'],
            },
        },
        t_furnish_kitchen,
    ),
    (
        {
            'name': 'furnish_bathroom',
            'description': 'Fit a bathroom into a cell block: toilet, washbasin with a mirror 1.2 m up and a towel '
            'rail, a bath along the longest free wall and a shower in the far corner when the room is '
            'at least 2.5 x 2.5 m. door_side names the wall the door is in; nothing is put there.',
            'input_schema': {
                'type': 'object',
                'properties': dict(
                    _CELLS,
                    **{
                        'door_side': {'type': 'string', 'enum': list(_SIDES)},
                        'bath': {'type': 'boolean'},
                        'shower': {'type': 'boolean'},
                        'material': {'type': 'string', 'enum': MATERIALS},
                        'name': {'type': 'string'},
                    },
                ),
                'required': ['cell_from', 'cell_to'],
            },
        },
        t_furnish_bathroom,
    ),
    (
        {
            'name': 'add_utility',
            'description': 'A utility / laundry room: a washing machine, a wall-hung boiler and a short counter along '
            'one wall of the cell block.',
            'input_schema': {
                'type': 'object',
                'properties': dict(
                    _CELLS,
                    **{
                        'side': {'type': 'string', 'enum': list(_SIDES)},
                        'material': {'type': 'string', 'enum': MATERIALS},
                        'name': {'type': 'string'},
                    },
                ),
                'required': ['cell_from', 'cell_to'],
            },
        },
        t_add_utility,
    ),
]

EXAMPLES = [
    {
        'ask': 'put a kitchen along the north wall of D10 to G12',
        'calls': [{'tool': 'furnish_kitchen', 'args': {'cell_from': 'D10', 'cell_to': 'G12', 'side': 'north'}}],
    },
    {
        'ask': 'kitchen with an island in the big room H4..M9, first floor',
        'calls': [
            {
                'tool': 'furnish_kitchen',
                'args': {'cell_from': 'H4', 'cell_to': 'M9', 'side': 'west', 'island': True, 'storey': 1},
            }
        ],
    },
    {
        'ask': 'a bathroom in P6..R8, the door is on the south side',
        'calls': [{'tool': 'furnish_bathroom', 'args': {'cell_from': 'P6', 'cell_to': 'R8', 'door_side': 'south'}}],
    },
    {
        'ask': 'a shower room upstairs in B12..C14, no bath',
        'calls': [
            {'tool': 'furnish_bathroom', 'args': {'cell_from': 'B12', 'cell_to': 'C14', 'storey': 1, 'bath': False}}
        ],
    },
    {
        'ask': 'washing machine and boiler in the little room K2..L3',
        'calls': [{'tool': 'add_utility', 'args': {'cell_from': 'K2', 'cell_to': 'L3'}}],
    },
]
