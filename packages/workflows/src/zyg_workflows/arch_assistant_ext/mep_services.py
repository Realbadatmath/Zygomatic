# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""mep_services — the assistant's building-services tools.

Everything here hangs off a GROUP that already exists (the name draw_box or a
draw_* tool printed). The one number the whole family turns on is the group's
TOP: top_y = max over the group's walls of (wall.y + the wall's height). A roof
record of the group sits at exactly that y, so roof plant, gutters and chimneys
placed at top_y meet the roof; on a pitched roof (roof_gable / roof_hip / …)
solar panels are lifted 0.3 m and the result string says the placement is
approximate, because the slope's real height under each panel is not a number
the record model carries.

Inward / outward are measured against the group's plan CENTROID: a gutter is
pushed out of the wall by t/2 + 0.1, a radiator is pulled in by t/2 + 0.05.
"""

from __future__ import annotations

import math

from zyg_workflows.arch_assistant import (
    Drawing,
    MATERIALS,
    MAX_OBJECTS,
    _num,
    _wall_world,
    cell_centre,
    cell_name,
    parse_cell,
    storey_of,
    surface_top,
)

KINDS = {
    'duct': {'len': 4, 'w': 0.4, 'h': 0.3},
    'pipe': {'len': 4, 'r': 0.05},
    'cable_tray': {'len': 4, 'w': 0.3, 'h': 0.05},
    'solar_panel': {'w': 1.7, 'd': 1.0, 'tilt': 30, 't': 0.04, 'leg': 0.3},
    'hvac_unit': {'w': 1.2, 'd': 0.8, 'h': 1.0},
    'water_tank': {'r': 1.0, 'h': 2.0},
    'chimney': {'w': 0.6, 'd': 0.6, 'h': 1.5, 'cap': 0.1},
    'gutter': {'len': 4, 'r': 0.08},
    'downpipe': {'h': 2.7, 'r': 0.05},
    'antenna': {'h': 3, 'r': 0.03},
    'satellite_dish': {'r': 0.4, 'h': 0.5},
    'radiator': {'w': 1.0, 'h': 0.6, 't': 0.1},
}
OPENINGS: list = []

PROMPT = (
    'Services (MEP), all on a group that already exists: add_solar(group | cell_from+cell_to, rows, cols, tilt) '
    'tiles PV panels over the roof at the group top (0.3 m higher and approximate on a pitched roof); '
    'add_chimney(group, side=north|south|east|west, height) stands a stack on that side of the top storey; '
    'add_gutters(group) runs a gutter along every top-storey wall on the outside; add_downpipes(group, count) '
    'drops full-height downpipes at the corners; add_radiators(walls="all"|group|[ids], storeys) hangs one '
    'radiator on the inside face of each wall of each storey; run_pipe(cells, storey, height, kind=pipe|duct|'
    'cable_tray) runs a service line through a list of cells at a fixed height above that storey; '
    'add_rooftop_plant(group, kinds) spreads hvac_unit / water_tank / antenna / satellite_dish along the roof. '
    "Draw the shell first — these read the group's walls and refuse without them."
)

_SIDES = ('north', 'south', 'east', 'west')
_RUN_KINDS = ('pipe', 'duct', 'cable_tray')
_PLANT_KINDS = ('hvac_unit', 'water_tank', 'antenna', 'satellite_dish', 'solar_panel', 'chimney')


# ── the group's geometry ────────────────────────────────────────────────────
def _walls(d: Drawing, which):
    return [o for o in d.select(which if which not in (None, '') else 'all') if o['kind'] in ('wall', 'partition')]


def _top_y(d: Drawing, walls) -> float:
    return max(w['y'] + _num(w['p'].get('h'), d.storey_h) for w in walls)


def _footprint(walls) -> tuple:
    """(xmin, zmin, xmax, zmax, cx, cz) from the walls' end points."""
    xs, zs = [], []
    for w in walls:
        L = _num(w['p'].get('len'), 4)
        for u in (0.0, L):
            x, z = _wall_world(w, u)
            xs.append(x)
            zs.append(z)
    return min(xs), min(zs), max(xs), max(zs), (min(xs) + max(xs)) / 2, (min(zs) + max(zs)) / 2


def _top_walls(d: Drawing, walls) -> list:
    st = max(storey_of(w['y'], d.storey_h) for w in walls)
    return [w for w in walls if storey_of(w['y'], d.storey_h) == st]


def _outward(w: dict, cx: float, cz: float) -> tuple:
    """The unit plan normal of a wall pointing AWAY from (cx, cz)."""
    nx, nz = math.sin(w['ry']), math.cos(w['ry'])
    if (w['x'] - cx) * nx + (w['z'] - cz) * nz < 0:
        nx, nz = -nx, -nz
    return nx, nz


def _pitched(d: Drawing, which) -> bool:
    return any(o['kind'].startswith('roof_') and o['kind'] != 'roof_flat' for o in d.select(which or 'all'))


# 2026-09-10: rooftop plant used to fall through to mat_steel, so an air handling
# unit, a water tank, a dish and an antenna all rendered as the same black block.
# One light-metal / galvanised / dark id per kind, all in the PBR library.
PLANT_MATS = {
    'hvac_unit': 'acg_Metal032',  # light brushed metal casing
    'water_tank': 'pht_corrugated_iron_02',  # galvanised tank
    'antenna': 'acg_Metal041A',  # dark mast
    'satellite_dish': 'pht_white_plaster_02',  # white dish
    'solar_panel': 'pht_blue_metal_plate',  # dark blue PV
    'chimney': 'pht_corrugated_iron',  # a rooftop flue, not a brick stack
}


def _mat(m, default='mat_steel', kind=''):
    """The caller's material, else the kind's own finish, else `default`."""
    if m in MATERIALS:
        return m
    k = PLANT_MATS.get(kind)
    return k if k and k in MATERIALS else default


def _room(d: Drawing, n: int):
    return len(d.objs) + n <= MAX_OBJECTS


# ── tools ───────────────────────────────────────────────────────────────────
def t_add_solar(
    d: Drawing,
    a,
    group=None,
    cell_from=None,
    cell_to=None,
    rows=2,
    cols=None,
    tilt=30,
    spacing=0.1,
    storey=None,
    material='',
    name='',
):
    tl = _num(tilt, 30)
    if tl < 0 or tl > 60:
        return 'refused: tilt must be between 0 and 60 degrees'
    sp = max(0.0, _num(spacing, 0.1))
    approx = ''
    if group:
        walls = _walls(d, group)
        if not walls:
            return f'refused: no walls in group "{group}" — draw the shell first, or give cell_from/cell_to'
        xmin, zmin, xmax, zmax, cx, cz = _footprint(walls)
        y = _top_y(d, walls)
        if _pitched(d, group):
            y += 0.3
            approx = ' (pitched roof: laid 0.3 m above the eaves, so the height is approximate)'
        where = f'group "{group}"'
    elif cell_from and cell_to:
        from zyg_workflows.arch_assistant import block_bounds

        xmin, zmin, xmax, zmax = block_bounds(cell_from, cell_to)
        cx, cz = (xmin + xmax) / 2, (zmin + zmax) / 2
        y = int(_num(storey, 0)) * d.storey_h
        where = f'cells {cell_name(*parse_cell(cell_from))}..{cell_name(*parse_cell(cell_to))}'
    else:
        return 'refused: give a group name, or cell_from and cell_to'
    pw, pd = KINDS['solar_panel']['w'], KINDS['solar_panel']['d']
    W, D = xmax - xmin, zmax - zmin
    fit_c = int((W + sp) // (pw + sp))
    fit_r = int((D + sp) // (pd + sp))
    nc = int(_num(cols, 0)) or fit_c
    nr = int(_num(rows, 2)) or fit_r
    nc, nr = max(0, min(nc, fit_c)), max(0, min(nr, fit_r))
    if nc < 1 or nr < 1:
        return f'refused: {W:.1f} x {D:.1f} m is too small for a {pw:g} x {pd:g} m panel'
    if not _room(d, nc * nr):
        return f'refused: {nc * nr} panels would pass the {MAX_OBJECTS}-object ceiling'
    grp = name or 'solar array'
    tw, td = nc * pw + (nc - 1) * sp, nr * pd + (nr - 1) * sp
    for r in range(nr):
        for c in range(nc):
            x = cx - tw / 2 + pw / 2 + c * (pw + sp)
            z = cz - td / 2 + pd / 2 + r * (pd + sp)
            d.new(
                'solar_panel',
                {'w': pw, 'd': pd, 'tilt': round(tl, 2), 't': 0.04, 'leg': 0.3},
                x,
                z,
                y,
                0.0,
                _mat(material, 'mat_glass', 'solar_panel'),
                name=f'panel r{r + 1}c{c + 1}',
                grp=grp,
            )
    return (
        f'added {nc * nr} solar panels ({nr} rows x {nc} columns, {tl:g}° tilt) in group "{grp}" '
        f'over {where} at y {y:.2f} m{approx}'
    )


def t_add_chimney(d: Drawing, a, group, side='north', height=1.5, width=0.6, material='', name=''):
    s = str(side or 'north').lower()
    if s not in _SIDES:
        return 'refused: side must be north, south, east or west'
    walls = _walls(d, group)
    if not walls:
        return f'refused: no walls in group "{group}"'
    tops = _top_walls(d, walls)
    xmin, zmin, xmax, zmax, cx, cz = _footprint(walls)
    pick = [w for w in tops if w['name'].lower().startswith(s)]
    if not pick:
        key = {
            'north': lambda w: w['z'],
            'south': lambda w: -w['z'],
            'west': lambda w: w['x'],
            'east': lambda w: -w['x'],
        }[s]
        pick = [sorted(tops, key=key)[0]]
    w = pick[0]
    L = _num(w['p'].get('len'), 4)
    x, z = _wall_world(w, min(1.0, L / 2))
    y = _top_y(d, walls)
    h = _num(height, 1.5)
    if h < 0.3 or h > 30:
        return 'refused: chimney height must be between 0.3 and 30 m'
    bw = max(0.2, _num(width, 0.6))
    if not _room(d, 1):
        return f'refused: the drawing is at the {MAX_OBJECTS}-object ceiling'
    o = d.new(
        'chimney',
        {'w': bw, 'd': bw, 'h': round(h, 3), 'cap': 0.1},
        x,
        z,
        y,
        w['ry'],
        _mat(material, 'mat_brick'),
        name=name or f'{s} chimney',
        grp=name or (w['grp'] or 'chimneys'),
    )
    # a chimney on a WALL is masonry (mat_brick); PLANT_MATS['chimney'] is the
    # metal flue add_rooftop_plant stands in the middle of a deck.
    return (
        f'chimney {o["id"]} on the {s} wall {w["id"]} of "{group}", 1 m in from its end, '
        f'standing at y {y:.2f} m, {h:g} m tall plus a 0.1 m cap'
    )


def t_add_gutters(d: Drawing, a, group, radius=0.08, material='', name=''):
    walls = _walls(d, group)
    if not walls:
        return f'refused: no walls in group "{group}"'
    tops = _top_walls(d, walls)
    xmin, zmin, xmax, zmax, cx, cz = _footprint(walls)
    y = _top_y(d, walls)
    r = max(0.02, _num(radius, 0.08))
    if not _room(d, len(tops)):
        return f'refused: {len(tops)} gutters would pass the {MAX_OBJECTS}-object ceiling'
    grp = name or 'rainwater'
    ids = []
    for w in tops:
        L = _num(w['p'].get('len'), 4)
        t = _num(w['p'].get('t'), d.wall_t)
        nx, nz = _outward(w, cx, cz)
        off = t / 2 + 0.1
        o = d.new(
            'gutter',
            {'len': round(L, 4), 'r': r},
            w['x'] + nx * off,
            w['z'] + nz * off,
            y,
            w['ry'],
            _mat(material, 'mat_zinc', 'gutter'),
            name=f'gutter {w["name"].split(" ")[0]}',
            grp=grp,
        )
        ids.append(o['id'])
    if not ids:
        return (
            f'refused: "{group}" has no top-storey wall to hang a gutter on — '
            f'add_gutters(group=<the group draw_box printed>)'
        )
    return (
        f'added {len(ids)} gutters {ids[0]}..{ids[-1]} in group "{grp}" along the top-storey walls of '
        f'"{group}" at y {y:.2f} m, set {0.1 + d.wall_t / 2:.2f} m outside each wall'
    )


def t_add_downpipes(d: Drawing, a, group, count=2, radius=0.05, material='', name=''):
    walls = _walls(d, group)
    if not walls:
        return f'refused: no walls in group "{group}"'
    n = int(_num(count, 2))
    if n < 1 or n > 4:
        return 'refused: count must be 1..4 — a rectangular footprint has four corners'
    xmin, zmin, xmax, zmax, cx, cz = _footprint(walls)
    y0 = min(w['y'] for w in walls)
    h = _top_y(d, walls) - y0
    r = max(0.02, _num(radius, 0.05))
    if not _room(d, n):
        return f'refused: {n} downpipes would pass the {MAX_OBJECTS}-object ceiling'
    grp = name or 'rainwater'
    corners = [
        (xmin, zmin, 'north-west'),
        (xmax, zmin, 'north-east'),
        (xmax, zmax, 'south-east'),
        (xmin, zmax, 'south-west'),
    ]
    ids = []
    for x, z, lab in corners[:n]:
        o = d.new(
            'downpipe',
            {'h': round(h, 3), 'r': r},
            x + (0.1 if x < cx else -0.1),
            z + (0.1 if z < cz else -0.1),
            y0,
            0.0,
            _mat(material, 'mat_zinc', 'downpipe'),
            name=f'downpipe {lab}',
            grp=grp,
        )
        ids.append(o['id'])
    if not ids:
        return f'refused: count must be 1..4 — add_downpipes(group="{group}", count=2)'
    return (
        f'added {n} downpipes {ids[0]}..{ids[-1]} in group "{grp}" at the corners of "{group}", '
        f'each {h:.2f} m tall from y {y0:g} m up to the gutter'
    )


def t_add_radiators(d: Drawing, a, walls='all', storeys=None, width=1.0, height=0.6, material='', name=''):
    recs = _walls(d, walls)
    if not recs:
        return 'refused: no walls match — pass "all", a group name, or a list of wall ids'
    if storeys is not None:
        want = {int(_num(s, -999)) for s in (storeys if isinstance(storeys, list) else [storeys])}
        recs = [w for w in recs if storey_of(w['y'], d.storey_h) in want]
        if not recs:
            return f'refused: none of those walls are on storey(s) {sorted(want)}'
    xmin, zmin, xmax, zmax, cx, cz = _footprint(recs)
    rw, rh, rt = max(0.2, _num(width, 1.0)), max(0.2, _num(height, 0.6)), 0.1
    if not _room(d, len(recs)):
        return f'refused: {len(recs)} radiators would pass the {MAX_OBJECTS}-object ceiling'
    grp = name or 'radiators'
    made = 0
    for w in recs:
        L = _num(w['p'].get('len'), 4)
        if L < rw + 0.2:
            continue
        t = _num(w['p'].get('t'), d.wall_t)
        nx, nz = _outward(w, cx, cz)
        off = t / 2 + rt / 2
        x, z = _wall_world(w, L / 2)
        d.new(
            'radiator',
            {'w': rw, 'h': rh, 't': rt},
            x - nx * off,
            z - nz * off,
            w['y'] + 0.15,
            w['ry'],
            _mat(material, 'mat_paint_white', 'radiator'),
            name=f'radiator st{storey_of(w["y"], d.storey_h)}',
            grp=grp,
        )
        made += 1
    if not made:
        return (
            f'refused: every matching wall is shorter than {rw + 0.2:g} m — '
            f'add_radiators(walls=<group>, width={max(0.2, min(rw, 0.6)):g})'
        )
    return (
        f'added {made} radiators in group "{grp}" — one per wall, on the inside face, centred, '
        f'0.15 m above each floor ({rw:g} x {rh:g} m)'
    )


def t_run_pipe(d: Drawing, a, cells, storey=0, height=2.4, radius=0.05, kind='pipe', material='', name=''):
    k = str(kind or 'pipe')
    if k not in _RUN_KINDS:
        return 'refused: kind must be pipe, duct or cable_tray'
    pts = list(cells or [])
    if len(pts) < 2:
        return 'refused: give at least two cells — a run needs a start and an end'
    try:
        xy = [cell_centre(*parse_cell(c)) for c in pts]
    except ValueError as e:
        return f'refused: {e}'
    y = int(_num(storey, 0)) * d.storey_h + _num(height, 2.4)
    r = max(0.01, _num(radius, 0.05))
    if not _room(d, len(xy) - 1):
        return f'refused: {len(xy) - 1} segments would pass the {MAX_OBJECTS}-object ceiling'
    grp = name or f'{k} run'
    ids, total = [], 0.0
    for (x0, z0), (x1, z1) in zip(xy, xy[1:]):
        L = math.hypot(x1 - x0, z1 - z0)
        if L < 0.2:
            continue
        ry = math.atan2(-(z1 - z0), x1 - x0)
        if k == 'pipe':
            p = {'len': round(L, 4), 'r': r}
        elif k == 'duct':
            p = {'len': round(L, 4), 'w': 0.4, 'h': 0.3}
        else:
            p = {'len': round(L, 4), 'w': 0.3, 'h': 0.05}
        o = d.new(
            k,
            p,
            (x0 + x1) / 2,
            (z0 + z1) / 2,
            y,
            ry,
            _mat(material, 'mat_steel', k),
            name=f'{k} {len(ids) + 1}',
            grp=grp,
        )
        ids.append(o['id'])
        total += L
    if not ids:
        return (
            'refused: those cells are all the same place — a run needs cells at least 0.2 m apart, '
            'e.g. run_pipe(cells=["D6", "H6", "H11"], storey=0, height=2.4)'
        )
    return (
        f'ran {len(ids)} {k} segments {ids[0]}..{ids[-1]} in group "{grp}" through '
        f'{" -> ".join(str(c) for c in pts)}, {total:.2f} m in all, at y {y:.2f} m'
    )


def t_add_rooftop_plant(d: Drawing, a, group, kinds=None, material='', name=''):
    walls = _walls(d, group)
    if not walls:
        return (
            f'refused: no walls in group "{group}" — draw the shell first, then '
            f'add_rooftop_plant(group=<the group draw_box printed>)'
        )
    ks = [str(x) for x in (kinds or ['hvac_unit', 'water_tank', 'antenna'])]
    bad = [k for k in ks if k not in _PLANT_KINDS]
    if bad:
        return 'refused: rooftop plant must be one of ' + ', '.join(_PLANT_KINDS) + f' (not {", ".join(bad)})'
    if not ks:
        return (
            f'refused: name at least one unit — add_rooftop_plant(group="{group}", kinds=["hvac_unit", "water_tank"])'
        )
    xmin, zmin, xmax, zmax, cx, cz = _footprint(walls)
    y = _top_y(d, walls)
    if not _room(d, len(ks)):
        return f'refused: {len(ks)} units would pass the {MAX_OBJECTS}-object ceiling'
    grp = name or 'rooftop plant'
    W = xmax - xmin
    ids = []
    for i, k in enumerate(ks):
        x = xmin + W * (i + 1) / (len(ks) + 1)
        # 2026-09-08: the top of the walls is the roof record's BASE. Plant left
        # there floats above (or sinks into) the deck, which is base + the
        # roof's thickness; surface_top gives the surface a unit actually
        # stands on, so the roof set lands ON the roof.
        yk = surface_top(d, x, cz)
        if abs(yk - y) > d.storey_h * 0.6:
            yk = y  # no deck found: keep the wall top
        # each unit gets its OWN finish (PLANT_MATS), not one shared mat_steel
        o = d.new(k, dict(KINDS[k]), x, cz, yk, 0.0, _mat(material, 'mat_steel', k), name=k.replace('_', ' '), grp=grp)
        ids.append(f'{o["id"]} {k}')
    if not ids:
        return (
            f'refused: nothing was placed on "{group}" — '
            f'add_rooftop_plant(group="{group}", kinds=["hvac_unit", "water_tank"])'
        )
    y = d.find(ids[0].split()[0])['y']
    mats = ', '.join(sorted({d.find(i.split()[0])['mat'] for i in ids}))
    return (
        f'placed {len(ids)} units on the roof of "{group}" at y {y:.2f} m, spread along x in group '
        f'"{grp}": ' + ', '.join(ids) + f'. Finishes: {mats}'
    )


_MATS = {'type': 'string', 'enum': MATERIALS}

TOOLS = [
    (
        {
            'name': 'add_solar',
            'description': "Tile solar panels over a building group's roof (or over a block of cells). Panels sit at the top of the group's walls, tilted; on a pitched roof they are laid 0.3 m higher and the placement is approximate. rows/cols cap the array, otherwise as many as fit.",
            'input_schema': {
                'type': 'object',
                'properties': {
                    'group': {'type': 'string'},
                    'cell_from': {'type': 'string'},
                    'cell_to': {'type': 'string'},
                    'rows': {'type': 'integer'},
                    'cols': {'type': 'integer'},
                    'tilt': {'type': 'number'},
                    'spacing': {'type': 'number'},
                    'storey': {'type': 'integer'},
                    'material': _MATS,
                    'name': {'type': 'string'},
                },
                'required': [],
            },
        },
        t_add_solar,
    ),
    (
        {
            'name': 'add_chimney',
            'description': "Stand a chimney on the top-storey wall of one side of a group (north, south, east or west), inset 1 m from that wall's end.",
            'input_schema': {
                'type': 'object',
                'properties': {
                    'group': {'type': 'string'},
                    'side': {'type': 'string', 'enum': list(_SIDES)},
                    'height': {'type': 'number'},
                    'width': {'type': 'number'},
                    'material': _MATS,
                    'name': {'type': 'string'},
                },
                'required': ['group'],
            },
        },
        t_add_chimney,
    ),
    (
        {
            'name': 'add_gutters',
            'description': 'Run a gutter along every top-storey wall of a group, on the outside face at eaves level.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'group': {'type': 'string'},
                    'radius': {'type': 'number'},
                    'material': _MATS,
                    'name': {'type': 'string'},
                },
                'required': ['group'],
            },
        },
        t_add_gutters,
    ),
    (
        {
            'name': 'add_downpipes',
            'description': "Drop rainwater downpipes at a group's corners, each running the full height from the ground to the gutter.",
            'input_schema': {
                'type': 'object',
                'properties': {
                    'group': {'type': 'string'},
                    'count': {'type': 'integer'},
                    'radius': {'type': 'number'},
                    'material': _MATS,
                    'name': {'type': 'string'},
                },
                'required': ['group'],
            },
        },
        t_add_downpipes,
    ),
    (
        {
            'name': 'add_radiators',
            'description': 'Hang one panel radiator on the inside face of each wall, centred along it and 0.15 m above the floor. walls = "all", a group name or a list of wall ids; storeys limits which floors.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'walls': {'type': 'string'},
                    'storeys': {'type': 'array', 'items': {'type': 'integer'}},
                    'width': {'type': 'number'},
                    'height': {'type': 'number'},
                    'material': _MATS,
                    'name': {'type': 'string'},
                },
                'required': [],
            },
        },
        t_add_radiators,
    ),
    (
        {
            'name': 'run_pipe',
            'description': 'Run a pipe, duct or cable tray through a list of cells at a fixed height above a storey — one straight segment between each pair of cells.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'cells': {'type': 'array', 'items': {'type': 'string'}},
                    'storey': {'type': 'integer'},
                    'height': {'type': 'number'},
                    'radius': {'type': 'number'},
                    'kind': {'type': 'string', 'enum': list(_RUN_KINDS)},
                    'material': _MATS,
                    'name': {'type': 'string'},
                },
                'required': ['cells'],
            },
        },
        t_run_pipe,
    ),
    (
        {
            'name': 'add_rooftop_plant',
            'description': "Put one of each named unit (hvac_unit, water_tank, antenna, satellite_dish, ...) on a group's roof, spread along x.",
            'input_schema': {
                'type': 'object',
                'properties': {
                    'group': {'type': 'string'},
                    'kinds': {'type': 'array', 'items': {'type': 'string', 'enum': list(_PLANT_KINDS)}},
                    'material': _MATS,
                    'name': {'type': 'string'},
                },
                'required': ['group'],
            },
        },
        t_add_rooftop_plant,
    ),
]

EXAMPLES = [
    {
        'ask': 'put solar panels on the roof of the house',
        'calls': [{'tool': 'add_solar', 'args': {'group': 'box C4-L13', 'rows': 3, 'tilt': 35}}],
    },
    {
        'ask': 'gutters and two downpipes on that block',
        'calls': [
            {'tool': 'add_gutters', 'args': {'group': 'box C4-L13'}},
            {'tool': 'add_downpipes', 'args': {'group': 'box C4-L13', 'count': 2}},
        ],
    },
    {
        'ask': 'a 1.8 m chimney on the north side',
        'calls': [{'tool': 'add_chimney', 'args': {'group': 'box C4-L13', 'side': 'north', 'height': 1.8}}],
    },
    {
        'ask': 'a radiator under every window on the ground floor',
        'calls': [{'tool': 'add_radiators', 'args': {'walls': 'box C4-L13', 'storeys': [0], 'width': 1.2}}],
    },
    {
        'ask': 'run a heating pipe from D6 to H6 to H11 at 2.4 m',
        'calls': [{'tool': 'run_pipe', 'args': {'cells': ['D6', 'H6', 'H11'], 'storey': 0, 'height': 2.4}}],
    },
    {
        'ask': 'an air handling unit and a water tank on the roof',
        'calls': [{'tool': 'add_rooftop_plant', 'args': {'group': 'box C4-L13', 'kinds': ['hvac_unit', 'water_tank']}}],
    },
]
