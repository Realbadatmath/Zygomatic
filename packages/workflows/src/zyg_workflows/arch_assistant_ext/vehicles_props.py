# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""vehicles_props — the assistant's tools for the things that STAND on a site:
road vehicles, a boat, and the plant of a building site.

Tools: add_vehicles (a row or grid of one kind inside a cell block),
park_cars (one car per named cell), add_construction_site (a tower crane,
containers, pallets, a skip — optionally scaffolding a named building group),
add_scaffold (a scaffold against one wall).

Every vehicle record runs its LENGTH along its local +X with the front toward
+X, so `rotation_deg` reads as a compass bearing on the plan: 0 = pointing
east, 90 = pointing north (up in the top view).

Placement rule R5 (2026-09-07): everything here is a POINT thing — it stands on
the GROUND under its own centre (arch_assistant.ground_at), never at y = 0
inside a hill or a slope. A vehicle also leans along its heading on a slope
(rz), which the site plant does not. `base_height` overrides the ground.
"""

from __future__ import annotations

import math

from zyg_workflows.arch_assistant import (
    Drawing,
    parse_cell,
    cell_centre,
    cell_name,
    block_bounds,
    cell_of,
    ground_at,
    MATERIALS,
    MAX_OBJECTS,
    _num,
)

KINDS = {
    'car': {'l': 4.5, 'w': 1.8, 'h': 1.5},
    'van': {'l': 5.5, 'w': 2.0, 'h': 2.4},
    'bus': {'l': 12, 'w': 2.5, 'h': 3.2},
    'truck': {'l': 9, 'w': 2.5, 'h': 3.6},
    'bicycle': {'l': 1.8, 'h': 1.0},
    'motorcycle': {'l': 2.1, 'h': 1.1},
    'boat': {'l': 6, 'w': 2.2, 'h': 1.5},
    'tractor': {'l': 4, 'w': 2.2, 'h': 2.8},
    'crane_tower': {'h': 30, 'jib': 25, 'mast': 1.6},
    'scaffold': {'w': 6, 'h': 6, 'd': 1.2, 'bays': 3, 'lifts': 3},
    'container': {'l': 6.06, 'w': 2.44, 'h': 2.59},
    'dumpster': {'l': 3, 'w': 1.8, 'h': 1.4},
    'pallet': {'l': 1.2, 'w': 0.8, 'h': 0.15},
    'forklift': {'l': 3, 'w': 1.2, 'h': 2.1},
}
OPENINGS: list = []

# what add_vehicles / park_cars may place, and the plan width of the kinds
# whose width is not a parameter (the two-wheelers' handlebars).
VEHICLE_KINDS = (
    'car',
    'van',
    'bus',
    'truck',
    'bicycle',
    'motorcycle',
    'boat',
    'tractor',
    'forklift',
    'container',
    'dumpster',
    'pallet',
)
FIXED_W = {'bicycle': 0.55, 'motorcycle': 0.8}
SCAFFOLD_D = 1.2
SCAFFOLD_T = 0.06

PROMPT = (
    'Vehicles and site plant: add_vehicles(cell_from, cell_to, kind, count, spacing, rotation_deg) fills a cell '
    'block with a row or grid of one kind (car, van, bus, truck, bicycle, motorcycle, boat, tractor, forklift, '
    'container, dumpster, pallet) — use it for a car park, a bus bay, a bike rack, a yard. park_cars(cells) puts '
    'one car in each named cell, for kerbside or drive parking. add_construction_site(cell_from, cell_to, crane, '
    'containers, scaffold_group) turns a block into a building site: a tower crane at its corner, site containers '
    'along one edge, pallets and a skip, and — if you name a building group — a scaffold along each of its outside '
    'walls. add_scaffold(wall_id) scaffolds ONE wall (get wall ids from draw_box or list_storeys). Vehicles point '
    'along +X at rotation_deg 0 and north at 90. Every vehicle and site piece lands on the ground under its own '
    'centre (a hill, a slope, a plateau, a dyke) and a vehicle on a slope leans along its heading; base_height '
    'overrides.'
)


def _mat(m, default='mat_paint_white'):
    return m if m in MATERIALS else default


def _foot(kind: str, p: dict) -> tuple:
    """(length along local X, width along local Z) of one record in metres."""
    l = _num(p.get('l'), _num(KINDS.get(kind, {}).get('l'), 2.0))
    w = FIXED_W.get(kind)
    if w is None:
        w = _num(p.get('w'), _num(KINDS.get(kind, {}).get('w'), 2.0))
    return l, w


def _plan_extent(l: float, w: float, deg: float) -> tuple:
    """The axis-aligned footprint of an l x w record turned by deg."""
    c, s = abs(math.cos(math.radians(deg))), abs(math.sin(math.radians(deg)))
    return l * c + w * s, l * s + w * c


# ── R5: everything here is a POINT thing — it stands on the ground under its
# own centre (2026-09-07). A vehicle on a slope also leans along its heading:
# a record's LOCAL +X points at (cos ry, -sin ry) on the plan, so the rise per
# metre along the heading is gx*cos(ry) - gz*sin(ry) and rz = atan(that) lifts
# its nose (arch_assistant.ground_tilt's convention).
MAX_LEAN = math.radians(25.0)


def _stand(d: Drawing, x: float, z: float, ry: float, base_height=None, lean: bool = True) -> tuple:
    """(y, rz) for a record standing at world (x, z) with yaw ry."""
    if base_height is not None and base_height != '':
        return _num(base_height, 0.0), 0.0
    y, gx, gz = ground_at(d, x, z)
    if not lean:
        return round(y, 4), 0.0
    along = gx * math.cos(ry) - gz * math.sin(ry)
    rz = math.atan(along)
    if abs(rz) > MAX_LEAN:  # a lean this steep is a bug, not a hill
        rz = math.copysign(MAX_LEAN, rz)
    return round(y, 4), round(rz, 6)


def _place(
    d: Drawing,
    kind: str,
    p: dict,
    x: float,
    z: float,
    y0: float,
    ry: float,
    mat: str,
    name: str,
    grp: str,
    base_height=None,
    lean: bool = True,
):
    """d.new, but standing on the ground under (x, z) with y0 (the storey lift)
    added on top, and leaning with the slope along its own heading."""
    gy, rz = _stand(d, x, z, ry, base_height, lean)
    o = d.new(kind, p, x, z, round(gy + y0, 4), ry, mat, name=name, grp=grp)
    if rz:
        o['rz'] = rz
    return o


def t_add_vehicles(
    d: Drawing,
    a,
    cell_from,
    cell_to,
    kind='car',
    count=4,
    spacing=None,
    rotation_deg=0,
    storey=0,
    material='',
    name='',
    base_height=None,
):
    if kind not in VEHICLE_KINDS:
        return 'refused: kind must be one of ' + ', '.join(VEHICLE_KINDS)
    n = int(_num(count, 4))
    if n < 1 or n > 400:
        return 'refused: count must be between 1 and 400'
    xmin, zmin, xmax, zmax = block_bounds(cell_from, cell_to)
    W, D = xmax - xmin, zmax - zmin
    p0 = dict(KINDS[kind])
    l, w = _foot(kind, p0)
    deg = _num(rotation_deg, 0)
    fx, fz = _plan_extent(l, w, deg)
    if fx > W + 1e-6 or fz > D + 1e-6:
        return (
            f'refused: a {kind} needs {fx:.1f} x {fz:.1f} m and cells {cell_from}..{cell_to} are only '
            f'{W:g} x {D:g} m — use a bigger block or turn them with rotation_deg'
        )
    if len(d.objs) + n > MAX_OBJECTS:
        return f'refused: that is {n} objects past the {MAX_OBJECTS} ceiling'
    pitch_x = _num(spacing, 0) or (fx + 1.0)
    pitch_z = fz + 1.0
    per_row = max(1, int((W - fx) // pitch_x) + 1)
    rows = int(math.ceil(n / per_row))
    y0 = int(_num(storey, 0)) * d.storey_h
    ry = math.radians(deg)
    mat = _mat(material)
    grp = name or f'{kind}s {cell_name(*parse_cell(cell_from))}-{cell_name(*parse_cell(cell_to))}'
    ids, ys = [], []
    for i in range(n):
        col, row = i % per_row, i // per_row
        x = min(max(xmin + fx / 2 + col * pitch_x, xmin + fx / 2), xmax - fx / 2)
        z = min(max(zmin + fz / 2 + row * pitch_z, zmin + fz / 2), zmax - fz / 2)
        o = _place(d, kind, dict(p0), x, z, y0, ry, mat, f'{kind} {i + 1}', grp, base_height)
        ids.append(o['id'])
        ys.append(o['y'])
    if not ids:
        # 2026-09-10: a tool that made nothing REFUSES with the cause and the call
        # that works — never 'placed 0' (a model reads that as done).
        return (
            f'refused: placed 0 {kind}(s) — cells {cell_from}..{cell_to} are {W:g} x {D:g} m and one '
            f'{kind} needs {fx:.1f} x {fz:.1f} m — call add_vehicles with a bigger block or count >= 1'
        )
    ground = (
        f', following the ground from {min(ys):g} to {max(ys):g} m'
        if max(ys) - min(ys) > 0.05
        else (f', on the ground at {ys[0]:g} m' if ys[0] > 0.01 else '')
    )
    return (
        f'placed {len(ids)} {kind}(s) {ids[0]}..{ids[-1]} in group "{grp}" across cells {cell_from}..{cell_to} '
        f'({W:g} x {D:g} m): {per_row} per row, {rows} row(s), {pitch_x:g} m apart, turned {deg:g}°, storey '
        f'{int(_num(storey, 0))}' + ground
    )


def t_park_cars(d: Drawing, a, cells, rotation_deg=90, kind='car', material='', name='', base_height=None):
    if not isinstance(cells, (list, tuple)) or not cells:
        return 'refused: cells must be a list of cell labels, like ["C4", "C5", "C6"]'
    if kind not in VEHICLE_KINDS:
        return 'refused: kind must be one of ' + ', '.join(VEHICLE_KINDS)
    if len(cells) > 400:
        return 'refused: at most 400 cells at a time'
    if len(d.objs) + len(cells) > MAX_OBJECTS:
        return f'refused: that is {len(cells)} objects past the {MAX_OBJECTS} ceiling'
    deg = _num(rotation_deg, 90)
    ry = math.radians(deg)
    mat = _mat(material)
    grp = name or 'parked cars'
    ids, bad, ys = [], [], []
    for c in cells:
        try:
            cx, cz = cell_centre(*parse_cell(c))
        except ValueError:
            bad.append(str(c))
            continue
        o = _place(d, kind, dict(KINDS[kind]), cx, cz, 0.0, ry, mat, f'{kind} {cell_of(cx, cz)}', grp, base_height)
        ids.append(o['id'])
        ys.append(o['y'])
    if not ids:
        return 'refused: none of those cells are on the grid — ' + ', '.join(bad[:8])
    ground = (
        f', following the ground from {min(ys):g} to {max(ys):g} m'
        if max(ys) - min(ys) > 0.05
        else (f', on the ground at {ys[0]:g} m' if ys[0] > 0.01 else '')
    )
    return (
        f'parked {len(ids)} {kind}(s) {ids[0]}..{ids[-1]} in group "{grp}", one per cell, turned {deg:g}°'
        + ground
        + (f' (skipped {len(bad)} bad cells: ' + ', '.join(bad[:6]) + ')' if bad else '')
    )


def _group_walls(d: Drawing, which):
    """The storey-0 walls of a group, deduplicated by position — one scaffold
    per outside wall, not one per storey."""
    recs = [o for o in d.select(which) if o['kind'] in ('wall', 'partition')]
    if not recs:
        return [], (0.0, 0.0), 0.0
    y0 = min(o['y'] for o in recs)
    top = max(o['y'] + _num(o['p'].get('h'), d.storey_h) for o in recs)
    base = [o for o in recs if abs(o['y'] - y0) < 1e-6]
    seen, out = set(), []
    for o in base:
        key = (round(o['x'], 2), round(o['z'], 2), round(o['ry'], 3))
        if key in seen:
            continue
        seen.add(key)
        out.append(o)
    cx = sum(o['x'] for o in base) / len(base)
    cz = sum(o['z'] for o in base) / len(base)
    return out, (cx, cz), top


def _scaffold_on(d: Drawing, wall: dict, height: float, lifts, grp: str, material=''):
    """One scaffold record against `wall`, standing on the side away from
    `wall['_away']` (set by the caller) — its own local +Z faces the wall."""
    L = _num(wall['p'].get('len'), 4.0)
    H = max(1.0, _num(height, d.storey_h))
    lf = int(_num(lifts, 0)) or max(1, int(round(H / 2.0)))
    bays = max(1, int(round(L / 2.0)))
    ry = wall['ry']
    nx, nz = math.sin(ry), math.cos(ry)  # the wall's local +Z in world
    ax, az = wall.get('_away', (0.0, 0.0))
    if nx * ax + nz * az < 0:  # +Z points inward: use the other face
        nx, nz, ry = -nx, -nz, ry + math.pi
    off = _num(wall['p'].get('t'), d.wall_t) / 2 + SCAFFOLD_D / 2 + SCAFFOLD_T
    p = {'w': round(L, 4), 'h': round(H, 3), 'd': SCAFFOLD_D, 'bays': bays, 'lifts': lf}
    o = d.new(
        'scaffold',
        p,
        wall['x'] + nx * off,
        wall['z'] + nz * off,
        wall['y'],
        ry,
        _mat(material, 'mat_steel'),
        name=f'scaffold on {wall["id"]}',
        grp=grp,
    )
    return o, L, H, bays, lf


def t_add_scaffold(d: Drawing, a, wall_id, lifts=None, height=None, side='outside', material='', name=''):
    w = d.find(str(wall_id))
    if not w:
        return f'refused: there is no object {wall_id} — pass a wall id from draw_box or list_storeys'
    if w['kind'] not in ('wall', 'partition'):
        return (
            f'refused: {wall_id} is a {w["kind"]}, not a wall — a scaffold stands against a wall; '
            'pass a wall id from draw_box or list_storeys'
        )
    H = _num(height, 0) or _num(w['p'].get('h'), d.storey_h)
    # "outside" = away from the centre of the wall's own group, if it has one
    away = (math.sin(w['ry']), math.cos(w['ry']))
    if w['grp']:
        peers = [o for o in d.objs if o['grp'] == w['grp'] and o['kind'] in ('wall', 'partition')]
        if len(peers) > 1:
            gx = sum(o['x'] for o in peers) / len(peers)
            gz = sum(o['z'] for o in peers) / len(peers)
            v = (w['x'] - gx, w['z'] - gz)
            if abs(v[0]) + abs(v[1]) > 1e-6:
                away = v
    if str(side).lower() in ('inside', 'in'):
        away = (-away[0], -away[1])
    w = dict(w, _away=away)
    o, L, H, bays, lf = _scaffold_on(d, w, H, lifts, name or f'scaffold {wall_id}', material)
    return (
        f'scaffold {o["id"]} against wall {wall_id}: {L:g} m long, {H:g} m high, {bays} bays x {lf} lifts, '
        f'standing on its {side} face'
    )


def t_add_construction_site(
    d: Drawing,
    a,
    cell_from,
    cell_to,
    crane=True,
    containers=2,
    scaffold_group=None,
    crane_height=30.0,
    jib=25.0,
    pallets=4,
    skip=True,
    name='',
    base_height=None,
):
    xmin, zmin, xmax, zmax = block_bounds(cell_from, cell_to)
    W, D = xmax - xmin, zmax - zmin
    if W < 6 or D < 6:
        return (
            f'refused: a building site needs at least 6 x 6 m and {cell_from}..{cell_to} is {W:g} x {D:g} m '
            f'— call add_construction_site with a block at least 6 cells wide and 6 deep'
        )
    nc = max(0, min(20, int(_num(containers, 2))))
    npal = max(0, min(40, int(_num(pallets, 4))))
    grp = name or f'site {cell_name(*parse_cell(cell_from))}-{cell_name(*parse_cell(cell_to))}'
    walls, centre, top = ([], (0.0, 0.0), 0.0)
    if scaffold_group:
        walls, centre, top = _group_walls(d, scaffold_group)
        if not walls:
            return f'refused: no walls in group "{scaffold_group}" — pass the group name draw_box reported'
    need = (1 if crane else 0) + nc + npal + (1 if skip else 0) + len(walls)
    if len(d.objs) + need > MAX_OBJECTS:
        return f'refused: that is {need} objects past the {MAX_OBJECTS} ceiling'
    made, ys = [], []
    if crane:
        cm = _num(KINDS['crane_tower']['mast'], 1.6)
        o = _place(
            d,
            'crane_tower',
            {'h': _num(crane_height, 30.0), 'jib': _num(jib, 25.0), 'mast': cm},
            xmin + cm,
            zmin + cm,
            0.0,
            0.0,
            'mat_steel',
            'tower crane',
            grp,
            base_height,
            lean=False,
        )
        made.append('crane ' + o['id'])
        ys.append(o['y'])
    cids = []
    for i in range(nc):  # containers along the -Z edge, nose to tail
        cl = _num(KINDS['container']['l'], 6.06)
        cw = _num(KINDS['container']['w'], 2.44)
        x = min(xmax - cl / 2, xmin + cl / 2 + i * (cl + 0.6))
        o = _place(
            d,
            'container',
            dict(KINDS['container']),
            x,
            zmax - cw / 2 - 0.4,
            0.0,
            0.0,
            'mat_paint_white',
            f'site container {i + 1}',
            grp,
            base_height,
            lean=False,
        )
        cids.append(o['id'])
        ys.append(o['y'])
    if cids:
        made.append(f'{len(cids)} containers {cids[0]}..{cids[-1]}')
    pids = []
    for i in range(npal):
        x = xmin + W * 0.55 + (i % 4) * 1.4
        z = zmin + D * 0.5 + (i // 4) * 1.0
        o = _place(
            d,
            'pallet',
            dict(KINDS['pallet']),
            min(x, xmax - 0.6),
            min(z, zmax - 0.4),
            0.0,
            0.0,
            'mat_timber',
            f'pallet {i + 1}',
            grp,
            base_height,
            lean=False,
        )
        pids.append(o['id'])
        ys.append(o['y'])
    if pids:
        made.append(f'{len(pids)} pallets')
    if skip:
        dl = _num(KINDS['dumpster']['l'], 3.0)
        o = _place(
            d,
            'dumpster',
            dict(KINDS['dumpster']),
            xmax - dl / 2 - 0.5,
            zmin + 1.2,
            0.0,
            0.0,
            'mat_paint_dark',
            'skip',
            grp,
            base_height,
            lean=False,
        )
        made.append('skip ' + o['id'])
        ys.append(o['y'])
    sids = []
    for wl in walls:
        wl = dict(wl, _away=(wl['x'] - centre[0], wl['z'] - centre[1]))
        o, _L, _H, _b, _lf = _scaffold_on(d, wl, top, None, grp, 'mat_steel')
        sids.append(o['id'])
    if sids:
        made.append(f'{len(sids)} scaffolds on group "{scaffold_group}" ({top:g} m high)')
    if ys and max(ys) - min(ys) > 0.05:
        made.append(f'each piece on the ground under it ({min(ys):g} to {max(ys):g} m)')
    elif ys and ys[0] > 0.01:
        made.append(f'on the ground at {ys[0]:g} m')
    return (
        f'building site "{grp}" across cells {cell_from}..{cell_to} ({W:g} x {D:g} m): ' + ', '.join(made)
        if made
        else 'refused: nothing to place — set crane, containers, pallets or skip'
    )


TOOLS = [
    (
        {
            'name': 'add_vehicles',
            'description': 'Fill a block of cells with a row or grid of one vehicle kind (car, van, bus, truck, bicycle, motorcycle, boat, tractor, forklift, container, dumpster, pallet). Use for car parks, bus bays, bike racks, storage yards. rotation_deg turns them: 0 = nose east, 90 = nose north. Each one stands on the ground under itself and leans with the slope along its heading; base_height overrides.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'cell_from': {'type': 'string'},
                    'cell_to': {'type': 'string'},
                    'kind': {'type': 'string', 'enum': list(VEHICLE_KINDS)},
                    'count': {'type': 'integer'},
                    'spacing': {'type': 'number'},
                    'rotation_deg': {'type': 'number'},
                    'storey': {'type': 'integer'},
                    'material': {'type': 'string', 'enum': MATERIALS},
                    'name': {'type': 'string'},
                    'base_height': {'type': 'number', 'description': 'metres; omit to stand on the ground'},
                },
                'required': ['cell_from', 'cell_to'],
            },
        },
        t_add_vehicles,
    ),
    (
        {
            'name': 'park_cars',
            'description': 'One car per named cell — kerbside parking, a driveway, cars on named bays. rotation_deg 90 (the default) parks them nose-north, across an east-west street. Each car stands on the ground under its own cell and leans with the slope along its heading; base_height overrides.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'cells': {'type': 'array', 'items': {'type': 'string'}},
                    'rotation_deg': {'type': 'number'},
                    'kind': {'type': 'string', 'enum': list(VEHICLE_KINDS)},
                    'material': {'type': 'string', 'enum': MATERIALS},
                    'name': {'type': 'string'},
                    'base_height': {'type': 'number', 'description': 'metres; omit to stand on the ground'},
                },
                'required': ['cells'],
            },
        },
        t_park_cars,
    ),
    (
        {
            'name': 'add_construction_site',
            'description': 'Turn a block of cells into a building site: a tower crane at its corner, site containers along one edge, pallets, a skip. Give scaffold_group the name of a building group and each of its outside walls gets a scaffold the full height of the group. Every piece stands on the ground under itself; base_height overrides.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'cell_from': {'type': 'string'},
                    'cell_to': {'type': 'string'},
                    'crane': {'type': 'boolean'},
                    'containers': {'type': 'integer'},
                    'scaffold_group': {'type': 'string'},
                    'crane_height': {'type': 'number'},
                    'jib': {'type': 'number'},
                    'pallets': {'type': 'integer'},
                    'skip': {'type': 'boolean'},
                    'name': {'type': 'string'},
                    'base_height': {'type': 'number', 'description': 'metres; omit to stand on the ground'},
                },
                'required': ['cell_from', 'cell_to'],
            },
        },
        t_add_construction_site,
    ),
    (
        {
            'name': 'add_scaffold',
            'description': 'A scaffold against ONE wall, as long and as tall as that wall, standing on its outside face. lifts sets the number of working levels (default one per 2 m).',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'wall_id': {'type': 'string'},
                    'lifts': {'type': 'integer'},
                    'height': {'type': 'number'},
                    'side': {'type': 'string', 'enum': ['outside', 'inside']},
                    'material': {'type': 'string', 'enum': MATERIALS},
                    'name': {'type': 'string'},
                },
                'required': ['wall_id'],
            },
        },
        t_add_scaffold,
    ),
]

EXAMPLES = [
    {
        'ask': 'a car park on the plot from D10 to X20, about 20 cars',
        'calls': [
            {
                'tool': 'add_vehicles',
                'args': {
                    'cell_from': 'D10',
                    'cell_to': 'X20',
                    'kind': 'car',
                    'count': 20,
                    'spacing': 2.6,
                    'rotation_deg': 90,
                },
            }
        ],
    },
    {
        'ask': 'park a car in front of each house, on C12, F12 and I12',
        'calls': [{'tool': 'park_cars', 'args': {'cells': ['C12', 'F12', 'I12'], 'rotation_deg': 90}}],
    },
    {
        'ask': 'put a bus and two vans in the depot yard, K30 to T36',
        'calls': [
            {'tool': 'add_vehicles', 'args': {'cell_from': 'K30', 'cell_to': 'T36', 'kind': 'bus', 'count': 1}},
            {'tool': 'add_vehicles', 'args': {'cell_from': 'K34', 'cell_to': 'T36', 'kind': 'van', 'count': 2}},
        ],
    },
    {
        'ask': 'make it a building site: crane, three containers, and scaffold the house',
        'calls': [
            {
                'tool': 'add_construction_site',
                'args': {
                    'cell_from': 'B4',
                    'cell_to': 'P18',
                    'crane': True,
                    'containers': 3,
                    'scaffold_group': 'box B6-J12',
                },
            }
        ],
    },
    {'ask': 'scaffold just the south wall o7', 'calls': [{'tool': 'add_scaffold', 'args': {'wall_id': 'o7'}}]},
    {
        'ask': 'three cars parked up the hill road on P30, P34 and P38',
        'calls': [{'tool': 'park_cars', 'args': {'cells': ['P30', 'P34', 'P38'], 'rotation_deg': 90}}],
    },
    {
        'ask': 'twelve bikes in the rack from A2 to F3',
        'calls': [
            {
                'tool': 'add_vehicles',
                'args': {
                    'cell_from': 'A2',
                    'cell_to': 'F3',
                    'kind': 'bicycle',
                    'count': 12,
                    'spacing': 0.7,
                    'rotation_deg': 90,
                },
            }
        ],
    },
]
