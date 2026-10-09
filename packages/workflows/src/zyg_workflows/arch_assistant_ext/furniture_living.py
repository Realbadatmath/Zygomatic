# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""furniture_living — the assistant's furniture tools.

Two tools: furnish_room lays a standard arrangement inside a block of cells
(bedroom, living, dining, office, library); place_furniture_set drops a small
cluster on one cell at any rotation.

FRAME. Every furniture record has its footprint centre at x/z, its bottom at
y = storey * d.storey_h, and its FRONT along local -Z — so ry = 0 faces north
(up in the plan). Rotating a piece by ry moves a local offset (ox, oz) to
world (x + ox*cos(ry) + oz*sin(ry), z - ox*sin(ry) + oz*cos(ry)), the same
handedness arch_assistant._wall_world uses for walls.

Wall sides follow draw_box: north = zmin, south = zmax, west = xmin,
east = xmax. A piece with its back against the east wall therefore wants
ry = +pi/2 (its front then looks west, into the room).
"""

from __future__ import annotations

import math

from zyg_workflows.arch_assistant import (
    Drawing,
    parse_cell,
    cell_centre,
    cell_name,
    block_bounds,
    MATERIALS,
    _num,
    MAX_OBJECTS,
)

KINDS = {
    'bed_single': {'w': 0.9, 'l': 2.0, 'h': 0.5, 'head': 0.9},
    'bed_double': {'w': 1.6, 'l': 2.0, 'h': 0.5, 'head': 1.0},
    'wardrobe': {'w': 1.2, 'd': 0.6, 'h': 2.1},
    'nightstand': {'w': 0.45, 'd': 0.4, 'h': 0.55},
    'sofa': {'w': 2.2, 'd': 0.9, 'h': 0.85, 'seat': 0.45},
    'armchair': {'w': 0.9, 'd': 0.9, 'h': 0.85},
    'coffee_table': {'w': 1.1, 'd': 0.6, 'h': 0.42},
    'dining_table': {'w': 1.8, 'd': 0.9, 'h': 0.75},
    'chair': {'w': 0.45, 'd': 0.45, 'h': 0.9, 'seat': 0.45},
    'desk': {'w': 1.4, 'd': 0.7, 'h': 0.75},
    'bookcase': {'w': 0.9, 'd': 0.35, 'h': 2.0, 'shelves': 5},
    'tv_unit': {'w': 1.6, 'd': 0.45, 'h': 0.5, 'screen': 1.2},
    'rug': {'w': 2.4, 'd': 1.7, 't': 0.02},
    'lamp_floor': {'h': 1.6, 'r': 0.2},
}
OPENINGS: list = []

ROOMS = ('bedroom', 'living', 'dining', 'office', 'library')
SETS = ('bedroom_pair', 'dining_4', 'dining_6', 'living_trio')
SIDES = ('north', 'east', 'south', 'west')
GAP = 0.06  # clearance between a piece and the wall behind it

PROMPT = (
    'Furniture: furnish_room(cell_from, cell_to, storey, room, door_side, material) fills a block of cells '
    'with a standard arrangement — room=bedroom (double bed with its head on the north wall, a nightstand '
    'either side, a wardrobe on the east wall), living (sofa facing a tv_unit across the room, coffee table '
    'and rug between), dining (table centred, 4-8 chairs around it by table size), office (desk and chair on '
    'the north wall, a bookcase), library (bookcases along three walls); it needs at least 3x3 cells and it '
    'keeps the wall with the door clear. place_furniture_set(cell, storey, set, rotation_deg) drops one small '
    'cluster at a single cell: bedroom_pair, dining_4, dining_6 or living_trio, turned by rotation_deg. Use '
    'furnish_room when the user names a room or a block of cells, place_furniture_set for one spot. Single '
    'pieces (bed_single, armchair, desk, bookcase, rug, lamp_floor...) go in with add_object.'
)


def _mat(m, default='mat_timber'):
    return m if m in MATERIALS else default


def _rot(ox, oz, ry):
    """A local offset -> a world offset, plan rotation ry (radians)."""
    c, s = math.cos(ry), math.sin(ry)
    return ox * c + oz * s, -ox * s + oz * c


def _room_bounds(cell_from, cell_to):
    xmin, zmin, xmax, zmax = block_bounds(cell_from, cell_to)
    nc, nr = int(round(xmax - xmin)), int(round(zmax - zmin))
    if nc < 3 or nr < 3:
        raise ValueError(f'a room needs at least 3x3 cells — {cell_from}..{cell_to} is {nc}x{nr}')
    return xmin, zmin, xmax, zmax, nc, nr


def _clamp(v, lo, hi):
    return max(lo, min(hi, v))


def _plan_bedroom(xmin, zmin, xmax, zmax, cx, cz, door):
    """(kind, params, x, z, ry, name) for a bedroom. Bed head on the north wall."""
    out = []
    bw, bl = 1.6, 2.0
    bz = zmin + GAP + bl / 2
    out.append(('bed_double', {}, cx, bz, 0.0, 'double bed'))
    for s, side in ((-1, 'west'), (1, 'east')):
        out.append(
            (
                'nightstand',
                {},
                _clamp(cx + s * (bw / 2 + 0.05 + 0.225), xmin + 0.25, xmax - 0.25),
                zmin + GAP + 0.2,
                0.0,
                f'nightstand {side}',
            )
        )
    wside = 'west' if door == 'east' else 'east'
    wx = (xmin + GAP + 0.3) if wside == 'west' else (xmax - GAP - 0.3)
    out.append(
        (
            'wardrobe',
            {},
            wx,
            _clamp(cz + 0.3, zmin + 0.7, zmax - 0.7),
            -math.pi / 2 if wside == 'west' else math.pi / 2,
            f'wardrobe {wside} wall',
        )
    )
    return out


def _plan_living(xmin, zmin, xmax, zmax, cx, cz, door):
    out = [
        ('sofa', {}, cx, zmax - GAP - 0.45, 0.0, 'sofa'),
        ('tv_unit', {}, cx, zmin + GAP + 0.225, math.pi, 'tv unit'),
        ('coffee_table', {}, cx, cz + 0.2, 0.0, 'coffee table'),
        ('rug', {}, cx, cz + 0.2, 0.0, 'rug'),
    ]
    if (xmax - xmin) >= 4.5:
        out.append(
            ('armchair', {}, _clamp(xmax - GAP - 0.45, xmin + 0.5, xmax - 0.5), cz + 0.2, math.pi / 2, 'armchair')
        )
        out.append(
            ('lamp_floor', {}, _clamp(xmin + GAP + 0.2, xmin + 0.25, xmax - 0.25), zmax - GAP - 0.25, 0.0, 'floor lamp')
        )
    return out


def _chair_ring(cx, cz, tw, td, n, ry0=0.0):
    """n chairs around a table centred at cx/cz: the long sides first, then the ends."""
    out = []
    per = max(1, (n - 2) // 2) if n > 4 else n // 2
    ends = n - 2 * per
    for i in range(per):
        u = (i + 0.5) / per - 0.5
        out.append(('chair', {}, cx + u * tw, cz - td / 2 - 0.30, math.pi + ry0, f'chair n{i + 1}'))
        out.append(('chair', {}, cx + u * tw, cz + td / 2 + 0.30, 0.0 + ry0, f'chair s{i + 1}'))
    if ends >= 1:
        out.append(('chair', {}, cx - tw / 2 - 0.30, cz, -math.pi / 2 + ry0, 'chair w'))
    if ends >= 2:
        out.append(('chair', {}, cx + tw / 2 + 0.30, cz, math.pi / 2 + ry0, 'chair e'))
    return out[:n]


def _plan_dining(xmin, zmin, xmax, zmax, cx, cz, door):
    tw, td = 1.8, 0.9
    span = min(xmax - xmin, zmax - zmin)
    n = 4 if span < 3.6 else (6 if span < 4.6 else 8)
    return [('dining_table', {}, cx, cz, 0.0, 'dining table')] + _chair_ring(cx, cz, tw, td, n)


def _plan_office(xmin, zmin, xmax, zmax, cx, cz, door):
    out = [
        ('desk', {}, cx, zmin + GAP + 0.35, math.pi, 'desk'),
        ('chair', {}, cx, zmin + GAP + 0.35 + 0.35 + 0.35, 0.0, 'desk chair'),
    ]
    bside = 'west' if door == 'east' else 'east'
    bx = (xmin + GAP + 0.175) if bside == 'west' else (xmax - GAP - 0.175)
    out.append(
        (
            'bookcase',
            {},
            bx,
            _clamp(cz + 0.4, zmin + 0.6, zmax - 0.6),
            -math.pi / 2 if bside == 'west' else math.pi / 2,
            f'bookcase {bside} wall',
        )
    )
    return out


def _plan_library(xmin, zmin, xmax, zmax, cx, cz, door):
    out = []
    for side in SIDES:
        if side == door:
            continue
        if side in ('north', 'south'):
            run, ry = xmax - xmin, (math.pi if side == 'north' else 0.0)
            z = (zmin + GAP + 0.175) if side == 'north' else (zmax - GAP - 0.175)
        else:
            run, ry = zmax - zmin, (-math.pi / 2 if side == 'west' else math.pi / 2)
            x = (xmin + GAP + 0.175) if side == 'west' else (xmax - GAP - 0.175)
        run -= 1.0  # keep the corners clear
        n = int(run // 0.9)
        for i in range(max(0, n)):
            u = (i + 0.5) / n - 0.5 if n else 0.0
            if side in ('north', 'south'):
                out.append(('bookcase', {}, cx + u * run, z, ry, f'bookcase {side} {i + 1}'))
            else:
                out.append(('bookcase', {}, x, cz + u * run, ry, f'bookcase {side} {i + 1}'))
    if len(out) > 2:
        out.append(('armchair', {}, cx, cz, 0.0, 'reading chair'))
    return out


_PLANNERS = {
    'bedroom': _plan_bedroom,
    'living': _plan_living,
    'dining': _plan_dining,
    'office': _plan_office,
    'library': _plan_library,
}


def t_furnish_room(
    d: Drawing, a, cell_from, cell_to, storey=0, room='bedroom', door_side='south', material='mat_timber', name=''
):
    room = str(room or 'bedroom').strip().lower()
    if room not in ROOMS:
        return f'refused: room must be one of {", ".join(ROOMS)}'
    door = str(door_side or 'south').strip().lower()
    if door not in SIDES:
        return 'refused: door_side must be north, east, south or west'
    xmin, zmin, xmax, zmax, nc, nr = _room_bounds(cell_from, cell_to)
    cx, cz = (xmin + xmax) / 2, (zmin + zmax) / 2
    st = int(_num(storey, 0))
    y = st * d.storey_h
    mat = _mat(material)
    grp = name or f'{room} {cell_name(*parse_cell(cell_from))}-{cell_name(*parse_cell(cell_to))}'
    items = _PLANNERS[room](xmin, zmin, xmax, zmax, cx, cz, door)
    if len(d.objs) + len(items) > MAX_OBJECTS:
        return f'refused: that is {len(items)} objects past the {MAX_OBJECTS} ceiling'
    counts: dict = {}
    for kind, extra, x, z, ry, nm in items:
        x = _clamp(x, xmin + 0.15, xmax - 0.15)
        z = _clamp(z, zmin + 0.15, zmax - 0.15)
        p = dict(KINDS[kind])
        p.update(extra or {})
        d.new(kind, p, x, z, y, ry, mat, name=nm, grp=grp)
        counts[kind] = counts.get(kind, 0) + 1
    d.selected = list(d.added[-len(items) :])
    return (
        f'furnished "{grp}" as a {room}: {len(items)} pieces on storey {st} '
        f'({", ".join(f"{v} {k}" for k, v in sorted(counts.items()))}) inside the {nc}x{nr} m block '
        f'{cell_name(*parse_cell(cell_from))}..{cell_name(*parse_cell(cell_to))}, door wall ({door}) kept clear. '
        f'ids {d.added[-len(items)]}..{d.added[-1]}'
    )


_SET_ITEMS = {
    'bedroom_pair': [
        ('bed_double', 0.0, 0.55, 0.0, 'double bed'),
        ('nightstand', -1.05, -0.75, 0.0, 'nightstand west'),
        ('nightstand', 1.05, -0.75, 0.0, 'nightstand east'),
    ],
    'living_trio': [
        ('sofa', 0.0, 1.25, 0.0, 'sofa'),
        ('coffee_table', 0.0, 0.0, 0.0, 'coffee table'),
        ('tv_unit', 0.0, -1.35, math.pi, 'tv unit'),
    ],
}


def _dining_set(n):
    out = [('dining_table', 0.0, 0.0, 0.0, 'dining table')]
    for kind, _extra, x, z, ry, nm in _chair_ring(0.0, 0.0, 1.8, 0.9, n):
        out.append((kind, x, z, ry, nm))
    return out


def t_place_furniture_set(
    d: Drawing, a, cell, storey=0, set='bedroom_pair', rotation_deg=0.0, material='mat_timber', name=''
):
    key = str(set or 'bedroom_pair').strip().lower()
    if key not in SETS:
        return f'refused: set must be one of {", ".join(SETS)}'
    c, r = parse_cell(cell)
    cx, cz = cell_centre(c, r)
    st = int(_num(storey, 0))
    y = st * d.storey_h
    ry0 = math.radians(_num(rotation_deg, 0.0))
    mat = _mat(material)
    items = _dining_set(4 if key == 'dining_4' else 6) if key.startswith('dining_') else _SET_ITEMS[key]
    if len(d.objs) + len(items) > MAX_OBJECTS:
        return f'refused: that is {len(items)} objects past the {MAX_OBJECTS} ceiling'
    grp = name or f'{key} {cell_name(c, r)}'
    counts: dict = {}
    for kind, ox, oz, ry, nm in items:
        wx, wz = _rot(ox, oz, ry0)
        d.new(kind, dict(KINDS[kind]), cx + wx, cz + wz, y, ry + ry0, mat, name=nm, grp=grp)
        counts[kind] = counts.get(kind, 0) + 1
    d.selected = list(d.added[-len(items) :])
    return (
        f'placed set "{grp}" at {cell_name(c, r)} storey {st}, turned {_num(rotation_deg, 0):g}°: '
        f'{len(items)} pieces ({", ".join(f"{v} {k}" for k, v in sorted(counts.items()))}), '
        f'ids {d.added[-len(items)]}..{d.added[-1]}'
    )


TOOLS = [
    (
        {
            'name': 'furnish_room',
            'description': 'Furnish a block of cells as a room: a standard arrangement of beds, seating, tables, desks or bookcases laid out from the block walls. Needs at least 3x3 cells; the wall named by door_side is kept clear. Use when the user names a room ("furnish B4..E7 as a bedroom").',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'cell_from': {'type': 'string'},
                    'cell_to': {'type': 'string'},
                    'storey': {'type': 'integer'},
                    'room': {'type': 'string', 'enum': list(ROOMS)},
                    'door_side': {'type': 'string', 'enum': list(SIDES)},
                    'material': {'type': 'string', 'enum': MATERIALS},
                    'name': {'type': 'string'},
                },
                'required': ['cell_from', 'cell_to'],
            },
        },
        t_furnish_room,
    ),
    (
        {
            'name': 'place_furniture_set',
            'description': 'Drop one small furniture cluster at a single cell, turned by rotation_deg: bedroom_pair (bed + two nightstands), dining_4 or dining_6 (table + chairs), living_trio (sofa, coffee table, tv unit). Use for a spot, not a whole room.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'cell': {'type': 'string'},
                    'storey': {'type': 'integer'},
                    'set': {'type': 'string', 'enum': list(SETS)},
                    'rotation_deg': {'type': 'number'},
                    'material': {'type': 'string', 'enum': MATERIALS},
                    'name': {'type': 'string'},
                },
                'required': ['cell'],
            },
        },
        t_place_furniture_set,
    ),
]

EXAMPLES = [
    {
        'ask': 'furnish the room from C4 to F7 as a bedroom, the door is on the south side',
        'calls': [
            {
                'tool': 'furnish_room',
                'args': {'cell_from': 'C4', 'cell_to': 'F7', 'room': 'bedroom', 'door_side': 'south'},
            }
        ],
    },
    {
        'ask': 'make the living room on the first floor, cells H10 to N16',
        'calls': [
            {'tool': 'furnish_room', 'args': {'cell_from': 'H10', 'cell_to': 'N16', 'room': 'living', 'storey': 1}}
        ],
    },
    {
        'ask': 'a dining table for six on K12, turned a quarter turn',
        'calls': [{'tool': 'place_furniture_set', 'args': {'cell': 'K12', 'set': 'dining_6', 'rotation_deg': 90}}],
    },
    {
        'ask': 'put a sofa, a coffee table and the tv at D20',
        'calls': [{'tool': 'place_furniture_set', 'args': {'cell': 'D20', 'set': 'living_trio'}}],
    },
    {
        'ask': 'line the study from B2 to F6 with bookcases',
        'calls': [{'tool': 'furnish_room', 'args': {'cell_from': 'B2', 'cell_to': 'F6', 'room': 'library'}}],
    },
    {'ask': 'add a single bed at G8', 'calls': [{'tool': 'add_object', 'args': {'kind': 'bed_single', 'cell': 'G8'}}]},
]
