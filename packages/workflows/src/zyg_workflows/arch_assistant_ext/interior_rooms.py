# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""interior_rooms — the assistant's room-planning tools.

Rooms are NOT a new kind: a room is the base kinds `partition` and `door`
placed the way arch_assistant.t_draw_wall / t_add_opening place them (a
partition record carries {len, h, t}, sits at the segment's midpoint with
ry = atan2(-(z1-z0), x1-x0); a door sits at a point ON that partition, with
the partition's own y and ry). What IS new here are the five finish kinds —
ceiling, suspended_ceiling, floor_finish, skirting, raised_floor — each a
plain parametric box (or grid of boxes) sized exactly by its parameters.

Tools: subdivide_floor (a block into cols x rows rooms, with doors, optionally
around a corridor), add_room (one room's four partitions + a door),
add_corridor (the two partitions that bound a corridor), add_ceiling,
add_floor_finish, add_skirting.
"""

from __future__ import annotations

import math

from zyg_workflows import arch_assistant as A
from zyg_workflows.arch_assistant import (
    Drawing,
    MATERIALS,
    MAX_OBJECTS,
    KINDS as BASE_KINDS,
    block_bounds,
    cell_name,
    parse_cell,
    _num,
)

KINDS = {
    'ceiling': {'w': 6, 'd': 4, 't': 0.1},
    'floor_finish': {'w': 6, 'd': 4, 't': 0.02},
    'skirting': {'len': 4, 'h': 0.1, 't': 0.015},
    'raised_floor': {'w': 6, 'd': 4, 'h': 0.3, 'pedestals': 0.6},
    'suspended_ceiling': {'w': 6, 'd': 4, 't': 0.05, 'tiles': 0.6},
}
OPENINGS: list = []

PROMPT = (
    'Interior rooms: subdivide_floor(cell_from, cell_to, cols, rows, storey, doors, corridor) splits a '
    'floor block into cols x rows rooms — partitions on the internal grid lines, a door between neighbouring '
    'rooms; corridor="x" or "z" leaves a 1.5 m corridor down the middle instead of that line of partitions '
    'and gives every room a door onto it. add_room(cell_from, cell_to, name, door_side, sides) walls one '
    'block (never doubling a facade) with a door on an interior side; add_corridor(width, direction) draws only the two '
    'partitions bounding a passage. Finishes over a block: add_ceiling(kind="ceiling" or '
    '"suspended_ceiling") hangs at the top of the storey, add_floor_finish(material) lays the visible floor '
    '(mat_timber, mat_stone), add_skirting runs skirting along the four edges. Draw the outer shell with '
    'draw_box first; these do the inside.'
)
if len(PROMPT) > 900:
    raise RuntimeError(f'PROMPT is {len(PROMPT)} chars (max 900)')

SIDES = ('north', 'south', 'east', 'west')
FACADE_LINE_TOL = 0.3  # a room side this close to the envelope edge IS the facade


def _mat(m, default='mat_plaster'):
    return m if m in MATERIALS else default


def _storey_y(d: Drawing, storey):
    return int(_num(storey, 0)) * d.storey_h


def _partition(d: Drawing, x0, z0, x1, z1, y, h, t, mat, name, grp):
    """A partition record between two world points, exactly as t_draw_wall."""
    L = math.hypot(x1 - x0, z1 - z0)
    ry = math.atan2(-(z1 - z0), (x1 - x0))
    return d.new(
        'partition', {'len': round(L, 4), 'h': h, 't': t}, (x0 + x1) / 2, (z0 + z1) / 2, y, ry, mat, name=name, grp=grp
    )


def _door(d: Drawing, w: dict, x, z, width, height, name, grp):
    """A door ON the partition `w` at world (x, z), as t_add_opening does it."""
    p = dict(BASE_KINDS.get('door') or {'w': 0.9, 'h': 2.1})
    p['w'] = _num(width, p['w'])
    p['h'] = min(_num(height, p['h']), _num(w['p'].get('h'), 2.5) - 0.05)
    o = d.new('door', p, x, z, w['y'], w['ry'], 'mat_timber', name=name, grp=grp)
    o['meta']['host'] = w['id']  # delete the wall, the door goes with it
    return o


def _room_h(d: Drawing, h):
    # 2026-09-16: the default WAS storey_h - 0.2 (a 2.5 m room under a 2.7 m
    # storey) and every lobby shipped with an open 0.2 m strip above its
    # partitions — the 4K lobby frame of job 5e7eb915e1f9 showed the curtain
    # wall through it. A partition runs to the slab underside (slabs sit ON
    # their storey line and grow UP, arch_blender_build 'slab'); wall_h still
    # overrides for a deliberately low screen.
    return _num(h, max(0.5, d.storey_h)) or max(0.5, d.storey_h)


# ── the tools ───────────────────────────────────────────────────────────────
def t_subdivide_floor(
    d: Drawing,
    a,
    cell_from,
    cell_to,
    cols=2,
    rows=2,
    storey=0,
    doors=True,
    corridor=None,
    wall_h=None,
    wall_t=0.1,
    material='',
    name='',
):
    xmin, zmin, xmax, zmax = block_bounds(cell_from, cell_to)
    W, D = xmax - xmin, zmax - zmin
    cx, cz = (xmin + xmax) / 2, (zmin + zmax) / 2
    nc, nr = int(_num(cols, 2)), int(_num(rows, 2))
    if not (1 <= nc <= 20 and 1 <= nr <= 20):
        return 'refused: cols and rows must each be between 1 and 20'
    if nc == 1 and nr == 1 and not corridor:
        return 'refused: cols=1 and rows=1 subdivides nothing — use add_room for a single room'
    st = int(_num(storey, 0))
    y = st * d.storey_h
    H = _room_h(d, wall_h)
    T = _num(wall_t, 0.1) or 0.1
    mat = _mat(material)
    grp = name or f'rooms st{st}'
    cw = 1.5
    corr = str(corridor).lower() if corridor else ''
    if corr and corr not in ('x', 'z'):
        return 'refused: corridor must be "x", "z" or omitted'
    if corr == 'x' and D <= cw + 0.8:
        return f'refused: the block is only {D:g} m deep — no room for a {cw:g} m corridor plus rooms'
    if corr == 'z' and W <= cw + 0.8:
        return f'refused: the block is only {W:g} m wide — no room for a {cw:g} m corridor plus rooms'

    parts: list = []
    door_specs: list = []  # (partition index, x, z)
    if not corr:
        for i in range(1, nc):  # partitions running along Z
            x = xmin + W * i / nc
            parts.append(('z', x, zmin, x, zmax))
            for j in range(nr):
                door_specs.append((len(parts) - 1, x, zmin + D * (j + 0.5) / nr))
        for j in range(1, nr):  # partitions running along X
            z = zmin + D * j / nr
            parts.append(('x', xmin, z, xmax, z))
            for i in range(nc):
                door_specs.append((len(parts) - 1, xmin + W * (i + 0.5) / nc, z))
        rooms = nc * nr
    elif corr == 'x':
        za, zb = cz - cw / 2, cz + cw / 2
        parts.append(('x', xmin, za, xmax, za))
        parts.append(('x', xmin, zb, xmax, zb))
        band = (D - cw) / 2
        for i in range(1, nc):
            x = xmin + W * i / nc
            if band > 0.4:
                parts.append(('z', x, zmin, x, za))
                parts.append(('z', x, zb, x, zmax))
        for i in range(nc):
            xd = xmin + W * (i + 0.5) / nc
            door_specs.append((0, xd, za))
            door_specs.append((1, xd, zb))
        rooms = 2 * nc
    else:
        xa, xb = cx - cw / 2, cx + cw / 2
        parts.append(('z', xa, zmin, xa, zmax))
        parts.append(('z', xb, zmin, xb, zmax))
        band = (W - cw) / 2
        for j in range(1, nr):
            z = zmin + D * j / nr
            if band > 0.4:
                parts.append(('x', xmin, z, xa, z))
                parts.append(('x', xb, z, xmax, z))
        for j in range(nr):
            zd = zmin + D * (j + 0.5) / nr
            door_specs.append((0, xa, zd))
            door_specs.append((1, xb, zd))
        rooms = 2 * nr

    want_doors = bool(doors)
    need = len(parts) + (len(door_specs) if want_doors else 0)
    if len(d.objs) + need > MAX_OBJECTS:
        return f'refused: that is {need} objects and the drawing may hold {MAX_OBJECTS} in total'
    recs = []
    for n, (axis, x0, z0, x1, z1) in enumerate(parts):
        recs.append(_partition(d, x0, z0, x1, z1, y, H, T, mat, f'partition {axis}{n + 1} st{st}', grp))
    made_doors = 0
    if want_doors:
        for idx, dx, dz in door_specs:
            _door(d, recs[idx], dx, dz, None, None, f'door st{st}', grp)
            made_doors += 1
    return (
        f'subdivided {cell_name(*parse_cell(cell_from))}..{cell_name(*parse_cell(cell_to))} '
        f'({W:g} x {D:g} m, storey {st}) into {rooms} rooms in group "{grp}": {len(recs)} partitions '
        f'{recs[0]["id"]}..{recs[-1]["id"]}, {made_doors} doors' + (f', {cw:g} m corridor along {corr}' if corr else '')
    )


def t_add_room(
    d: Drawing,
    a,
    cell_from,
    cell_to,
    storey=0,
    name='room',
    door_side=None,
    partitions=True,
    sides=None,
    wall_h=None,
    wall_t=0.1,
    material='',
    door_width=None,
):
    xmin, zmin, xmax, zmax = block_bounds(cell_from, cell_to)
    W, D = xmax - xmin, zmax - zmin
    cx, cz = (xmin + xmax) / 2, (zmin + zmax) / 2
    asked = str(door_side or '').strip().lower()
    auto = asked in ('', 'auto')
    side = 'south' if auto else asked
    if side not in SIDES and side != 'none':
        return 'refused: door_side must be north, south, east, west or none'
    want = [str(s).lower() for s in sides] if sides else list(SIDES)
    bad = [s for s in want if s not in SIDES]
    if bad:
        return f'refused: unknown side(s) {", ".join(bad)} — use north, south, east, west'
    st = int(_num(storey, 0))
    y = st * d.storey_h
    H = _room_h(d, wall_h)
    T = _num(wall_t, 0.1) or 0.1
    mat = _mat(material)
    grp = str(name or 'room')
    # 2026-09-16: a room block laid over the stair or the lift walls the core
    # shut — four partitions straight through the flight, and design_check only
    # says so after the records exist. clash_rules owns where the cores are.
    CL = A.EXT_MODULES.get('clash_rules')
    hit = CL.blocking_core(d, (xmin, zmin, xmax, zmax), st) if CL is not None else None
    if hit:
        o, cr, ox, oz = hit
        return (
            f'refused: the block {cell_name(*parse_cell(cell_from))}..{cell_name(*parse_cell(cell_to))} '
            f'crosses {CL.core_phrase(o, cr)} by {ox:.2f} x {oz:.2f} m on storey {st} — a room may not be '
            f'drawn over a stair or a lift. Use a block clear of it, or layout_floor(core_from, core_to) '
            f'which lays out the whole plate and leaves the core out'
        )
    geom = {
        'north': (xmin, zmin, xmax, zmin),
        'south': (xmin, zmax, xmax, zmax),
        'west': (xmin, zmin, xmin, zmax),
        'east': (xmax, zmin, xmax, zmax),
    }
    if not partitions:
        return f'refused: partitions=False leaves nothing to draw for room "{grp}"'
    # A room side lying on the building's own envelope edge IS the facade — glass
    # on a glazed storey. Doubling it with a partition walls the view out, and a
    # room door there opens into thin air (the live tower, job 038ca075c052).
    E = A.EXT_MODULES.get('envelope_rules')
    envs = E.envelopes(d) if E else {}
    group = E.group_at(d, cx, cz, envs) if envs else None
    env = envs.get(group) if group else None
    facade = []
    if env:
        gap = {
            'north': abs(zmin - env['zmin']),
            'south': abs(zmax - env['zmax']),
            'west': abs(xmin - env['xmin']),
            'east': abs(xmax - env['xmax']),
        }
        facade = [s for s in want if gap[s] <= FACADE_LINE_TOL]
    if not auto and side in facade:
        inner = [s for s in want if s not in facade] or [s for s in SIDES if s not in facade]
        return (
            f'refused: the {side} side of "{grp}" is the {side} facade of "{group}" — the facade '
            f'(glass on a glazed storey) is that wall and holds no room door; door_side must be one of '
            f'{", ".join(inner)} (toward the core), or omit it'
        )
    draw = [s for s in want if s not in facade]
    if len(d.objs) + len(draw) + 1 > MAX_OBJECTS:
        return f'refused: that is {len(draw) + 1} objects past the {MAX_OBJECTS} ceiling'
    made = {}
    for s in draw:
        x0, z0, x1, z1 = geom[s]
        made[s] = _partition(d, x0, z0, x1, z1, y, H, T, mat, f'{s} partition {grp}', grp)
    if auto and side != 'none' and made:
        # the door faces the middle of the building: the partition whose midpoint
        # is nearest the envelope centre (with no envelope, the old default)
        if env:
            ex, ez = (env['xmin'] + env['xmax']) / 2, (env['zmin'] + env['zmax']) / 2
            side = min(
                made, key=lambda s: math.hypot((geom[s][0] + geom[s][2]) / 2 - ex, (geom[s][1] + geom[s][3]) / 2 - ez)
            )
    door = ''
    if side != 'none' and side in made:
        w = made[side]
        o = _door(d, w, w['x'], w['z'], door_width, None, f'door {grp}', grp)
        door = f', door {o["id"]} in the {side} partition'
    elif side != 'none':
        door = f' (no {side} partition, so no door)'
    listed = ', '.join('%s %s' % (s, r['id']) for s, r in made.items())
    notes = ''
    for s in facade:
        glazed = A.wall_on_side(d, group, s, st, kinds=('curtain_wall',))[0] is not None
        notes += f', no {s} partition: that line is the {s} facade of "{group}"' + (
            ' (a glass curtain wall on this storey)' if glazed else ''
        )
    return (
        f'room "{grp}" at {cell_name(*parse_cell(cell_from))}..{cell_name(*parse_cell(cell_to))}: '
        f'{W:g} x {D:g} m, storey {st}, {len(made)} partitions ({listed}){door}{notes}'
    )


def t_add_corridor(
    d: Drawing, a, cell_from, cell_to, storey=0, width=1.5, direction='x', wall_h=None, wall_t=0.1, material='', name=''
):
    xmin, zmin, xmax, zmax = block_bounds(cell_from, cell_to)
    W, D = xmax - xmin, zmax - zmin
    cx, cz = (xmin + xmax) / 2, (zmin + zmax) / 2
    dirn = str(direction or 'x').lower()
    if dirn not in ('x', 'z'):
        return 'refused: direction must be "x" (the corridor runs east-west) or "z" (north-south)'
    cw = _num(width, 1.5)
    if cw < 0.8 or cw > 6:
        return 'refused: a corridor is between 0.8 and 6 m wide'
    span = D if dirn == 'x' else W
    if cw >= span:
        return f'refused: a {cw:g} m corridor does not fit across {span:g} m'
    st = int(_num(storey, 0))
    y = st * d.storey_h
    H = _room_h(d, wall_h)
    T = _num(wall_t, 0.1) or 0.1
    mat = _mat(material)
    grp = name or f'corridor st{st}'
    if dirn == 'x':
        pairs = [(xmin, cz - cw / 2, xmax, cz - cw / 2), (xmin, cz + cw / 2, xmax, cz + cw / 2)]
    else:
        pairs = [(cx - cw / 2, zmin, cx - cw / 2, zmax), (cx + cw / 2, zmin, cx + cw / 2, zmax)]
    if len(d.objs) + 2 > MAX_OBJECTS:
        return f'refused: the drawing is at the {MAX_OBJECTS}-object ceiling'
    ids = [_partition(d, *pr, y, H, T, mat, f'corridor wall {i + 1} st{st}', grp)['id'] for i, pr in enumerate(pairs)]
    return (
        f'corridor "{grp}": {cw:g} m wide along {dirn}, '
        f'{(W if dirn == "x" else D):g} m long, storey {st}, partitions {ids[0]} and {ids[1]}'
    )


def t_add_ceiling(
    d: Drawing, a, cell_from, cell_to, storey=0, kind='ceiling', thickness=None, tiles=0.6, material='', name=''
):
    if kind not in ('ceiling', 'suspended_ceiling'):
        return 'refused: kind must be "ceiling" (a plastered slab) or "suspended_ceiling" (a tiled grid)'
    xmin, zmin, xmax, zmax = block_bounds(cell_from, cell_to)
    st = int(_num(storey, 0))
    t = _num(thickness, KINDS[kind]['t'])
    if t <= 0 or t > 0.6:
        return 'refused: ceiling thickness must be between 0 and 0.6 m'
    p = {'w': round(xmax - xmin, 4), 'd': round(zmax - zmin, 4), 't': round(t, 4)}
    if kind == 'suspended_ceiling':
        p['tiles'] = max(0.2, _num(tiles, 0.6))
    y = st * d.storey_h + d.storey_h - t
    o = d.new(
        kind,
        p,
        (xmin + xmax) / 2,
        (zmin + zmax) / 2,
        y,
        0.0,
        _mat(material),
        name=name or f'{kind.replace("_", " ")} st{st}',
        grp=name or f'ceiling st{st}',
    )
    return (
        f'{kind} {o["id"]} over {cell_name(*parse_cell(cell_from))}..{cell_name(*parse_cell(cell_to))}: '
        f'{p["w"]:g} x {p["d"]:g} m, {t:g} m thick, its underside at {y:g} m (storey {st})'
    )


def t_add_floor_finish(d: Drawing, a, cell_from, cell_to, storey=0, material='mat_timber', thickness=0.02, name=''):
    xmin, zmin, xmax, zmax = block_bounds(cell_from, cell_to)
    st = int(_num(storey, 0))
    t = _num(thickness, 0.02)
    if t <= 0 or t > 0.3:
        return 'refused: a floor finish is between 0 and 0.3 m thick'
    p = {'w': round(xmax - xmin, 4), 'd': round(zmax - zmin, 4), 't': round(t, 4)}
    o = d.new(
        'floor_finish',
        p,
        (xmin + xmax) / 2,
        (zmin + zmax) / 2,
        st * d.storey_h,
        0.0,
        _mat(material, 'mat_timber'),
        name=name or f'floor finish st{st}',
        grp=name or f'finishes st{st}',
    )
    return (
        f'floor finish {o["id"]} over {cell_name(*parse_cell(cell_from))}..'
        f'{cell_name(*parse_cell(cell_to))}: {p["w"]:g} x {p["d"]:g} m, {t:g} m, '
        f'{_mat(material, "mat_timber")}, storey {st}'
    )


def t_add_skirting(
    d: Drawing,
    a,
    cell_from,
    cell_to,
    storey=0,
    height=0.1,
    thickness=0.015,
    material='mat_paint_white',
    sides=None,
    name='',
):
    xmin, zmin, xmax, zmax = block_bounds(cell_from, cell_to)
    W, D = xmax - xmin, zmax - zmin
    cx, cz = (xmin + xmax) / 2, (zmin + zmax) / 2
    h, t = _num(height, 0.1), _num(thickness, 0.015)
    if h <= 0 or h > 0.5:
        return 'refused: skirting height must be between 0 and 0.5 m'
    want = [str(s).lower() for s in sides] if sides else list(SIDES)
    bad = [s for s in want if s not in SIDES]
    if bad:
        return f'refused: unknown side(s) {", ".join(bad)} — use north, south, east, west'
    st = int(_num(storey, 0))
    y = st * d.storey_h
    grp = name or f'skirting st{st}'
    geom = {
        'north': (W, cx, zmin, 0.0),
        'south': (W, cx, zmax, 0.0),
        'west': (D, xmin, cz, math.pi / 2),
        'east': (D, xmax, cz, math.pi / 2),
    }
    if len(d.objs) + len(want) > MAX_OBJECTS:
        return f'refused: that is {len(want)} objects past the {MAX_OBJECTS} ceiling'
    ids = []
    for s in want:
        L, x, z, ry = geom[s]
        o = d.new(
            'skirting',
            {'len': round(L, 4), 'h': round(h, 4), 't': round(t, 4)},
            x,
            z,
            y,
            ry,
            _mat(material, 'mat_paint_white'),
            name=f'{s} skirting st{st}',
            grp=grp,
        )
        ids.append(o['id'])
    return (
        f'{len(ids)} skirting runs {ids[0]}..{ids[-1]} around {cell_name(*parse_cell(cell_from))}..'
        f'{cell_name(*parse_cell(cell_to))} ({2 * (W + D):g} m total), {h:g} m high, storey {st}'
    )


_CELLS = {'cell_from': {'type': 'string'}, 'cell_to': {'type': 'string'}}

TOOLS = [
    (
        {
            'name': 'subdivide_floor',
            'description': 'Split a floor block into cols x rows rooms: partitions on the internal grid lines and a door between every pair of neighbouring rooms. corridor="x" or "z" leaves a 1.5 m corridor down the middle instead and gives each room a door onto it. Use for apartment plans, office floors, school wings.',
            'input_schema': {
                'type': 'object',
                'properties': dict(
                    _CELLS,
                    **{
                        'cols': {'type': 'integer'},
                        'rows': {'type': 'integer'},
                        'storey': {'type': 'integer'},
                        'doors': {'type': 'boolean'},
                        'corridor': {'type': 'string', 'enum': ['x', 'z']},
                        'wall_h': {'type': 'number'},
                        'wall_t': {'type': 'number'},
                        'material': {'type': 'string', 'enum': MATERIALS},
                        'name': {'type': 'string'},
                    },
                ),
                'required': ['cell_from', 'cell_to'],
            },
        },
        t_subdivide_floor,
    ),
    (
        {
            'name': 'add_room',
            'description': 'One room: partitions around a cell block (all four sides, or only the sides you list) and a single door in the door_side partition. Use when the user names one room ("a 4x3 bathroom at D7..F9, door on the west"). A side lying on the building facade gets NO partition (the facade — glass on a glazed storey — is that wall) and holds no door; omit door_side and the door goes on the interior side facing the plan centre.',
            'input_schema': {
                'type': 'object',
                'properties': dict(
                    _CELLS,
                    **{
                        'storey': {'type': 'integer'},
                        'name': {'type': 'string'},
                        'door_side': {'type': 'string', 'enum': ['north', 'south', 'east', 'west', 'none']},
                        'partitions': {'type': 'boolean'},
                        'sides': {'type': 'array', 'items': {'type': 'string'}},
                        'wall_h': {'type': 'number'},
                        'wall_t': {'type': 'number'},
                        'door_width': {'type': 'number'},
                        'material': {'type': 'string', 'enum': MATERIALS},
                    },
                ),
                'required': ['cell_from', 'cell_to'],
            },
        },
        t_add_room,
    ),
    (
        {
            'name': 'add_corridor',
            'description': 'The two partitions that bound a corridor through the middle of a block: direction "x" runs it east-west, "z" north-south. Use for a hallway between rooms already drawn.',
            'input_schema': {
                'type': 'object',
                'properties': dict(
                    _CELLS,
                    **{
                        'storey': {'type': 'integer'},
                        'width': {'type': 'number'},
                        'direction': {'type': 'string', 'enum': ['x', 'z']},
                        'wall_h': {'type': 'number'},
                        'wall_t': {'type': 'number'},
                        'material': {'type': 'string', 'enum': MATERIALS},
                        'name': {'type': 'string'},
                    },
                ),
                'required': ['cell_from', 'cell_to'],
            },
        },
        t_add_corridor,
    ),
    (
        {
            'name': 'add_ceiling',
            'description': 'A ceiling over a cell block, hung at the top of the storey: kind "ceiling" is a plastered slab, "suspended_ceiling" is an office T-bar grid with tiles every `tiles` metres.',
            'input_schema': {
                'type': 'object',
                'properties': dict(
                    _CELLS,
                    **{
                        'storey': {'type': 'integer'},
                        'kind': {'type': 'string', 'enum': ['ceiling', 'suspended_ceiling']},
                        'thickness': {'type': 'number'},
                        'tiles': {'type': 'number'},
                        'material': {'type': 'string', 'enum': MATERIALS},
                        'name': {'type': 'string'},
                    },
                ),
                'required': ['cell_from', 'cell_to'],
            },
        },
        t_add_ceiling,
    ),
    (
        {
            'name': 'add_floor_finish',
            'description': 'The visible floor layer over a cell block at the storey base — mat_timber for planks, mat_stone for tiles, mat_concrete for a polished screed.',
            'input_schema': {
                'type': 'object',
                'properties': dict(
                    _CELLS,
                    **{
                        'storey': {'type': 'integer'},
                        'thickness': {'type': 'number'},
                        'material': {'type': 'string', 'enum': MATERIALS},
                        'name': {'type': 'string'},
                    },
                ),
                'required': ['cell_from', 'cell_to'],
            },
        },
        t_add_floor_finish,
    ),
    (
        {
            'name': 'add_skirting',
            'description': 'A skirting board along the four edges of a cell block (or only the sides you list). Use after the floor finish to close the joint with the wall.',
            'input_schema': {
                'type': 'object',
                'properties': dict(
                    _CELLS,
                    **{
                        'storey': {'type': 'integer'},
                        'height': {'type': 'number'},
                        'thickness': {'type': 'number'},
                        'sides': {'type': 'array', 'items': {'type': 'string'}},
                        'material': {'type': 'string', 'enum': MATERIALS},
                        'name': {'type': 'string'},
                    },
                ),
                'required': ['cell_from', 'cell_to'],
            },
        },
        t_add_skirting,
    ),
]

EXAMPLES = [
    {
        'ask': 'split the ground floor of the house at C4..M14 into four rooms with doors between them',
        'calls': [
            {
                'tool': 'subdivide_floor',
                'args': {'cell_from': 'C4', 'cell_to': 'M14', 'cols': 2, 'rows': 2, 'storey': 0},
            }
        ],
    },
    {
        'ask': 'first floor of the office block D10..X30: eight rooms off a corridor down the middle',
        'calls': [
            {
                'tool': 'subdivide_floor',
                'args': {'cell_from': 'D10', 'cell_to': 'X30', 'cols': 4, 'rows': 2, 'storey': 1, 'corridor': 'x'},
            }
        ],
    },
    {
        'ask': 'a 3 by 2 m bathroom at F7..H8 with its door on the west side',
        'calls': [
            {'tool': 'add_room', 'args': {'cell_from': 'F7', 'cell_to': 'H8', 'name': 'bathroom', 'door_side': 'west'}}
        ],
    },
    {
        'ask': 'give that office floor a suspended ceiling and a timber floor',
        'calls': [
            {
                'tool': 'add_ceiling',
                'args': {'cell_from': 'D10', 'cell_to': 'X30', 'storey': 1, 'kind': 'suspended_ceiling'},
            },
            {
                'tool': 'add_floor_finish',
                'args': {'cell_from': 'D10', 'cell_to': 'X30', 'storey': 1, 'material': 'mat_timber'},
            },
        ],
    },
    {
        'ask': 'skirting boards round the living room at C4..H9',
        'calls': [{'tool': 'add_skirting', 'args': {'cell_from': 'C4', 'cell_to': 'H9', 'height': 0.12}}],
    },
    {
        'ask': 'a 2 m hallway running north-south through K12..P22',
        'calls': [
            {'tool': 'add_corridor', 'args': {'cell_from': 'K12', 'cell_to': 'P22', 'width': 2, 'direction': 'z'}}
        ],
    },
]
