# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""typologies_commercial — whole commercial and public buildings, composed from
the base tools (2026-09-06).

NO NEW KINDS. Every record this family writes is a built-in kind (wall, slab,
roof_flat, roof_gable, window, double_door, opening, column_rect, pyramid, box,
pad), so the tab, the rail and Blender already know how to draw all of it. The
seven tools here are recipes: they work out the cell blocks, call draw_box /
add_windows / add_opening / add_object / add_slab through
`arch_assistant.call_tool`, and place the few extras (rooftop plant, skylights,
canopy, spire) that the base tools cannot express at a non-storey height.

Optional richer elements from OTHER families are used only when they are loaded
at runtime — `add_curtain_wall` for a glazed tower, the `door_garage` opening
for the warehouse — and every tool falls back to a base-tool equivalent when
they are not, so this file never depends on another family.
"""

from __future__ import annotations

import math

from zyg_workflows import arch_assistant as A
from zyg_workflows.arch_assistant import (
    MATERIALS,
    MAX_OBJECTS,
    Drawing,
    _num,
    block_bounds,
    cell_name,
    parse_cell,
)

KINDS: dict = {}
OPENINGS: list = []

PROMPT = (
    'Commercial & public typologies — whole buildings from the base tools, plot = two corner cells: '
    'draw_office_tower(cell_from, cell_to, storeys, glass, core) glazed tower, lift core, flat roof, rooftop plant; '
    'draw_warehouse(cell_from, cell_to, height_m, doors, skylights) one tall shed storey, low gable roof, garage doors south; '
    'draw_shop(cell_from, cell_to, storeys) shopfront: 6 m glass strip, double door, canopy; '
    'draw_school(cell_from, cell_to, wings, storeys) main block plus perpendicular wings, windows, flat roofs; '
    'draw_church(cell_from, cell_to, tower) nave with tall windows and a gable roof plus a west tower with a pyramid spire; '
    'draw_parking_garage(cell_from, cell_to, decks) 3 m decks, no windows, a ramp opening per deck, a column grid; '
    'draw_stadium(cell_from, cell_to, tiers) four stands round a grass pitch. '
    'Use these when the user names the building type.'
)


# ── helpers ──────────────────────────────────────────────────────────────────
def _mat(m, default='mat_concrete'):
    return m if m in MATERIALS else default


def _cells(cell_from, cell_to) -> tuple:
    """Both corners as sorted 0-based cell indices (c0, r0, c1, r1)."""
    c0, r0 = parse_cell(cell_from)
    c1, r1 = parse_cell(cell_to)
    if c0 > c1:
        c0, c1 = c1, c0
    if r0 > r1:
        r0, r1 = r1, r0
    return c0, r0, c1, r1


def _call(d: Drawing, name: str, args: dict) -> str:
    return A.call_tool(d, name, args)


def _bad(res: str) -> bool:
    return res.startswith('refused') or res.startswith('bad arguments') or res.startswith('unknown tool')


def _has(tool: str) -> bool:
    return tool in A.TOOL_FN


def _grp_walls(d: Drawing, grp: str, side: str = '') -> list:
    out = [o for o in d.objs if o['grp'] == grp and o['kind'] == 'wall']
    if side:
        out = [o for o in out if o['name'].lower().startswith(side)]
    return out


def _room(d: Drawing, need: int) -> bool:
    return len(d.objs) + need <= MAX_OBJECTS


def _block(c0, r0, c1, r1) -> tuple:
    """Cell indices -> (xmin, zmin, xmax, zmax, W, D, cx, cz) in metres."""
    xmin, zmin, xmax, zmax = block_bounds(cell_name(c0, r0), cell_name(c1, r1))
    return xmin, zmin, xmax, zmax, xmax - xmin, zmax - zmin, (xmin + xmax) / 2, (zmin + zmax) / 2


# ── the tools ────────────────────────────────────────────────────────────────
def t_draw_office_tower(d: Drawing, a, cell_from, cell_to, storeys=12, glass=True, core=True, material='', name=''):
    c0, r0, c1, r1 = _cells(cell_from, cell_to)
    ncols, nrows = c1 - c0 + 1, r1 - r0 + 1
    if ncols < 4 or nrows < 4:
        return 'refused: an office tower needs a plot of at least 4 x 4 cells'
    n = max(1, min(200, int(_num(storeys, 12))))
    need = n * 5 + 2 + (n * 4 if core else 0) + (n * 16 if glass else 0)
    if not _room(d, need):
        return f'refused: that is about {need} objects, past the {MAX_OBJECTS} ceiling'
    grp = name or f'office tower {cell_name(c0, r0)}-{cell_name(c1, r1)}'
    res = _call(
        d,
        'draw_box',
        {
            'cell_from': cell_name(c0, r0),
            'cell_to': cell_name(c1, r1),
            'storeys': n,
            'slabs': True,
            'roof': 'flat',
            'material': _mat(material),
            'name': grp,
        },
    )
    if _bad(res):
        return res

    core_walls = 0
    if core and min(ncols, nrows) >= 8:
        cc0, cr0 = c0 + (ncols - 4) // 2, r0 + (nrows - 4) // 2
        rc = _call(
            d,
            'draw_box',
            {
                'cell_from': cell_name(cc0, cr0),
                'cell_to': cell_name(cc0 + 3, cr0 + 3),
                'storeys': n,
                'slabs': False,
                'roof': 'none',
                'material': 'mat_concrete',
                'name': f'{grp} core',
            },
        )
        if not _bad(rc):
            core_walls = n * 4

    glazing = ''
    if glass:
        if _has('add_curtain_wall'):
            rw = _call(d, 'add_curtain_wall', {'walls': grp})
            if not _bad(rw):
                glazing = rw
        if not glazing:
            glazing = _call(
                d,
                'add_windows',
                {
                    'walls': grp,
                    'per_wall': 4,
                    'width': 2.0,
                    'height': 2.0,
                    'sill': 0.5,
                    'material': 'mat_glass',
                    'every_n_storeys': 1,
                },
            )

    _, _, _, _, _W, _D, cx, cz = _block(c0, r0, c1, r1)
    top = n * d.storey_h
    plant = d.new(
        'box', {'w': 3.0, 'd': 3.0, 'h': 2.0}, cx, cz, top + 0.3, 0.0, 'mat_steel', name='rooftop plant', grp=grp
    )
    return (
        f'drew office tower "{grp}": {_W:g} x {_D:g} m, {n} storeys ({top:g} m), {4 * n} walls, {n} floor slabs, '
        f'a flat roof and plant box {plant["id"]}'
        + (f'; core "{grp} core" {core_walls} walls' if core_walls else '; no core (plot under 8 x 8 cells)')
        + (f'; {glazing}' if glazing else '; no glazing')
    )


def t_draw_warehouse(d: Drawing, a, cell_from, cell_to, height_m=8.0, doors=3, skylights=True, material='', name=''):
    c0, r0, c1, r1 = _cells(cell_from, cell_to)
    H = _num(height_m, 8.0)
    if H < 3 or H > 40:
        return 'refused: a warehouse wall is between 3 and 40 m tall'
    nd = max(0, min(12, int(_num(doors, 3))))
    if not _room(d, 6 + nd + 3):
        return f'refused: no room left under the {MAX_OBJECTS}-object ceiling'
    grp = name or f'warehouse {cell_name(c0, r0)}-{cell_name(c1, r1)}'
    res = _call(
        d,
        'draw_box',
        {
            'cell_from': cell_name(c0, r0),
            'cell_to': cell_name(c1, r1),
            'storeys': 1,
            'slabs': True,
            'roof': 'none',
            'wall_h': H,
            'material': _mat(material),
            'name': grp,
        },
    )
    if _bad(res):
        return res
    _, zmin, _, _, W, D, cx, cz = _block(c0, r0, c1, r1)
    d.new(
        'roof_gable',
        {'w': round(W, 4), 'd': round(D, 4), 'h': 2.0, 'over': 0.4},
        cx,
        cz,
        H,
        0.0,
        'mat_zinc',
        name='gable roof',
        grp=grp,
    )

    dk = 'door_garage' if ('door_garage' in A.KINDS and A.is_opening('door_garage')) else 'double_door'
    made = 0
    south = _grp_walls(d, grp, 'south')
    if nd and south:
        w = south[0]
        L = _num(w['p'].get('len'), 4)
        for i in range(nd):
            u = L * (i + 0.5) / nd
            rr = _call(
                d,
                'add_opening',
                {
                    'wall_id': w['id'],
                    'kind': dk,
                    'at': round(u, 3),
                    'width': 3.5 if dk == 'door_garage' else 2.4,
                    'height': round(min(4.0, H - 0.5), 3),
                },
            )
            if not _bad(rr):
                made += 1

    sk = 0
    if skylights:
        for i in range(3):
            zz = zmin + D * (i + 0.5) / 3
            d.new(
                'box',
                {'w': round(max(1.0, W * 0.5), 3), 'd': 1.2, 'h': 0.15},
                cx,
                zz,
                H + 1.6,
                0.0,
                'mat_glass',
                name=f'skylight {i + 1}',
                grp=grp,
            )
            sk += 1
    return (
        f'drew warehouse "{grp}": {W:g} x {D:g} m, one {H:g} m storey, 4 walls, a floor slab, '
        f'a low gable roof (2 m rise), {made} {dk}(s) on the south side' + (f' and {sk} glass skylights' if sk else '')
    )


def t_draw_shop(d: Drawing, a, cell_from, cell_to, storeys=1, material='', name=''):
    c0, r0, c1, r1 = _cells(cell_from, cell_to)
    n = max(1, min(6, int(_num(storeys, 1))))
    if not _room(d, n * 5 + 4):
        return f'refused: no room left under the {MAX_OBJECTS}-object ceiling'
    grp = name or f'shop {cell_name(c0, r0)}-{cell_name(c1, r1)}'
    res = _call(
        d,
        'draw_box',
        {
            'cell_from': cell_name(c0, r0),
            'cell_to': cell_name(c1, r1),
            'storeys': n,
            'slabs': True,
            'roof': 'flat',
            'material': _mat(material),
            'name': grp,
        },
    )
    if _bad(res):
        return res
    front = [w for w in _grp_walls(d, grp, 'south') if abs(w['y']) < 1e-6]
    if not front:
        return 'refused: the shopfront wall was not drawn'
    w = front[0]
    L = _num(w['p'].get('len'), 4)
    if L < 8:
        return 'refused: a shopfront needs a south side of at least 8 m (the glass strip alone is 6 m)'
    u_win, u_door = round(L * 0.35, 3), round(L * 0.78, 3)
    rw = _call(
        d,
        'add_opening',
        {
            'wall_id': w['id'],
            'kind': 'window',
            'at': u_win,
            'width': 6.0,
            'height': 2.4,
            'sill': 0.3,
            'material': 'mat_glass',
        },
    )
    rd = _call(d, 'add_opening', {'wall_id': w['id'], 'kind': 'double_door', 'at': u_door, 'width': 1.8, 'height': 2.4})
    dx, dz = A._wall_world(w, u_door)
    can = d.new(
        'box', {'w': 3.0, 'd': 1.2, 'h': 0.18}, dx, dz + 0.6, 2.6, 0.0, 'mat_steel', name='entrance canopy', grp=grp
    )
    _, _, _, _, W, D, _cx, _cz = _block(c0, r0, c1, r1)
    return (
        f'drew shop "{grp}": {W:g} x {D:g} m, {n} storey(s), flat roof; 6 m glass strip ({rw}), '
        f'double door ({rd}) and canopy {can["id"]} on the south front'
    )


def t_draw_school(d: Drawing, a, cell_from, cell_to, wings=2, storeys=2, material='', name=''):
    c0, r0, c1, r1 = _cells(cell_from, cell_to)
    ncols, nrows = c1 - c0 + 1, r1 - r0 + 1
    if ncols < 8 or nrows < 8:
        return 'refused: a school needs a plot of at least 8 x 8 cells'
    nw = max(0, min(6, int(_num(wings, 2))))
    n = max(1, min(8, int(_num(storeys, 2))))
    if not _room(d, (nw + 1) * (n * 5 + 1 + n * 12)):
        return f'refused: that many wings and storeys pass the {MAX_OBJECTS}-object ceiling'
    grp = name or f'school {cell_name(c0, r0)}-{cell_name(c1, r1)}'
    mh = max(4, nrows // 3)
    if nw and nrows - mh < 4:
        mh = max(3, nrows - 4)
    mat = _mat(material, 'mat_brick')

    groups = []
    main = f'{grp} main'
    res = _call(
        d,
        'draw_box',
        {
            'cell_from': cell_name(c0, r0),
            'cell_to': cell_name(c1, r0 + mh - 1),
            'storeys': n,
            'slabs': True,
            'roof': 'flat',
            'material': mat,
            'name': main,
        },
    )
    if _bad(res):
        return res
    groups.append(main)
    win = [
        _call(
            d,
            'add_windows',
            {'walls': main, 'spacing': 3.0, 'width': 1.4, 'height': 1.6, 'sill': 0.9, 'every_n_storeys': 1},
        )
    ]

    ww = max(3, ncols // (nw * 2)) if nw else 0
    for i in range(nw):
        ctr = c0 + int(round((i + 0.5) * ncols / nw))
        s = max(c0, min(c1 - ww + 1, ctr - ww // 2))
        g = f'{grp} wing {i + 1}'
        rr = _call(
            d,
            'draw_box',
            {
                'cell_from': cell_name(s, r0 + mh - 1),
                'cell_to': cell_name(s + ww - 1, r1),
                'storeys': n,
                'slabs': True,
                'roof': 'flat',
                'material': mat,
                'name': g,
            },
        )
        if _bad(rr):
            continue
        groups.append(g)
        win.append(
            _call(
                d,
                'add_windows',
                {'walls': g, 'spacing': 3.0, 'width': 1.4, 'height': 1.6, 'sill': 0.9, 'every_n_storeys': 1},
            )
        )
    return (
        f'drew school "{grp}": {len(groups)} blocks ({", ".join(groups)}), {n} storeys each, flat roofs; '
        f'main block {ncols} x {mh} m across the north, {len(groups) - 1} wing(s) {ww} m wide running south. '
        + '; '.join(win)
    )


def t_draw_church(d: Drawing, a, cell_from, cell_to, tower=True, material='', name=''):
    c0, r0, c1, r1 = _cells(cell_from, cell_to)
    ncols, nrows = c1 - c0 + 1, r1 - r0 + 1
    if ncols < 8 or nrows < 4:
        return 'refused: a church needs a plot of at least 8 x 4 cells (the nave plus a west tower)'
    if not _room(d, 40):
        return f'refused: no room left under the {MAX_OBJECTS}-object ceiling'
    want_tower = bool(tower)
    grp = name or f'church {cell_name(c0, r0)}-{cell_name(c1, r1)}'
    mat = _mat(material, 'mat_stone')
    nc0 = c0 + 3 if want_tower else c0
    nave = f'{grp} nave'
    res = _call(
        d,
        'draw_box',
        {
            'cell_from': cell_name(nc0, r0),
            'cell_to': cell_name(c1, r1),
            'storeys': 1,
            'slabs': True,
            'roof': 'none',
            'wall_h': 9.0,
            'material': mat,
            'name': nave,
        },
    )
    if _bad(res):
        return res
    _, _, _, _, Wn, Dn, cxn, czn = _block(nc0, r0, c1, r1)
    d.new(
        'roof_gable',
        {'w': round(Wn, 4), 'd': round(Dn, 4), 'h': 5.0, 'over': 0.5},
        cxn,
        czn,
        9.0,
        0.0,
        'mat_roof_tile',
        name='nave roof',
        grp=nave,
    )
    win = _call(
        d,
        'add_windows',
        {
            'walls': nave,
            'spacing': 4.0,
            'width': 1.2,
            'height': 4.0,
            'sill': 2.5,
            'material': 'mat_glass',
            'every_n_storeys': 1,
        },
    )

    tw = ''
    door_wall = [w for w in _grp_walls(d, nave, 'west')]
    if want_tower:
        tr0 = r0 + (nrows - 3) // 2
        tgrp = f'{grp} tower'
        rt = _call(
            d,
            'draw_box',
            {
                'cell_from': cell_name(c0, tr0),
                'cell_to': cell_name(c0 + 2, tr0 + 2),
                'storeys': 1,
                'slabs': False,
                'roof': 'none',
                'wall_h': 18.0,
                'material': mat,
                'name': tgrp,
            },
        )
        if not _bad(rt):
            _, _, _, _, Wt, Dt, cxt, czt = _block(c0, tr0, c0 + 2, tr0 + 2)
            d.new(
                'pyramid',
                {'r': round(math.hypot(Wt, Dt) / 2, 3), 'h': 5.0, 'sides': 4},
                cxt,
                czt,
                18.0,
                0.0,
                'mat_zinc',
                name='spire',
                grp=tgrp,
            )
            tw = f'; tower "{tgrp}" 3 x 3 m, 18 m to the pyramid spire (5 m)'
            door_wall = _grp_walls(d, tgrp, 'west') or door_wall
    dr = ''
    if door_wall:
        dr = _call(
            d,
            'add_opening',
            {
                'wall_id': door_wall[0]['id'],
                'kind': 'double_door',
                'at': 'middle',
                'width': 1.8,
                'height': 2.6,
                'material': 'mat_timber',
            },
        )
    return (
        f'drew church "{grp}": nave {Wn:g} x {Dn:g} m, walls 9 m, gable roof 5 m rise; {win}'
        + tw
        + (f'; west door ({dr})' if dr else '')
    )


def t_draw_parking_garage(d: Drawing, a, cell_from, cell_to, decks=3, material='', name=''):
    c0, r0, c1, r1 = _cells(cell_from, cell_to)
    ncols, nrows = c1 - c0 + 1, r1 - r0 + 1
    if ncols < 6 or nrows < 6:
        return 'refused: a parking garage needs a plot of at least 6 x 6 cells'
    nk = max(1, min(20, int(_num(decks, 3))))
    H = 3.0
    _, zmin, _, _, W, D, cx, cz = _block(c0, r0, c1, r1)
    xmin = _block(c0, r0, c1, r1)[0]
    nx = max(2, int(math.ceil(W / 8.0)) + 1)
    nz = max(2, int(math.ceil(D / 8.0)) + 1)
    need = nk * (5 + 1 + nx * nz)
    if not _room(d, need):
        return f'refused: that is about {need} objects, past the {MAX_OBJECTS} ceiling'
    grp = name or f'parking garage {cell_name(c0, r0)}-{cell_name(c1, r1)}'
    res = _call(
        d,
        'draw_box',
        {
            'cell_from': cell_name(c0, r0),
            'cell_to': cell_name(c1, r1),
            'storeys': nk,
            'slabs': True,
            'roof': 'none',
            'wall_h': H,
            'material': _mat(material),
            'name': grp,
        },
    )
    if _bad(res):
        return res
    ramps = 0
    for w in _grp_walls(d, grp, 'south'):
        rr = _call(
            d, 'add_opening', {'wall_id': w['id'], 'kind': 'opening', 'at': 'middle', 'width': 3.0, 'height': 2.4}
        )
        if not _bad(rr):
            ramps += 1
    inset = 0.8
    cols = 0
    for k in range(nk):
        for i in range(nx):
            for j in range(nz):
                x = xmin + inset + (W - 2 * inset) * i / (nx - 1)
                z = zmin + inset + (D - 2 * inset) * j / (nz - 1)
                rr = _call(
                    d,
                    'add_object',
                    {
                        'kind': 'column_rect',
                        'cell': A.cell_of(x, z),
                        'storey': 0,
                        'params': {'w': 0.3, 'd': 0.3, 'h': H},
                        'material': _mat(material),
                        'name': grp,
                    },
                )
                if _bad(rr):
                    continue
                # add_object counts height in storeys of d.storey_h; a parking deck is 3.0 m,
                # so the deck height is stamped on the record itself.
                rec = d.objs[-1]
                rec['y'] = round(k * H, 4)
                rec['name'] = f'column st{k}'
                cols += 1
    return (
        f'drew parking garage "{grp}": {W:g} x {D:g} m, {nk} decks of {H:g} m ({nk * H:g} m), {4 * nk} walls, '
        f'{nk} deck slabs, no windows, {ramps} ramp opening(s) 3 m wide in the south wall, '
        f'{cols} columns on a {nx} x {nz} grid per deck'
    )


def t_draw_stadium(d: Drawing, a, cell_from, cell_to, tiers=3, material='', name=''):
    c0, r0, c1, r1 = _cells(cell_from, cell_to)
    ncols, nrows = c1 - c0 + 1, r1 - r0 + 1
    if ncols < 12 or nrows < 12:
        return 'refused: a stadium needs a plot of at least 12 x 12 cells'
    nt = max(1, min(8, int(_num(tiers, 3))))
    H = 4.0 * nt
    grp = name or f'stadium {cell_name(c0, r0)}-{cell_name(c1, r1)}'
    _, _, _, _, W, D, cx, cz = _block(c0, r0, c1, r1)
    if not _room(d, 4 * 5 + 2):
        return f'refused: no room left under the {MAX_OBJECTS}-object ceiling'

    # Path 1: a real stadium bowl kind, when another family has registered it.
    if 'stadium_ring' in A.KINDS:
        rr = _call(
            d,
            'add_object',
            {
                'kind': 'stadium_ring',
                'cell': A.cell_of(cx, cz),
                'storey': 0,
                'params': {'w': round(W, 3), 'd': round(D, 3), 'h': H, 'tiers': nt},
                'material': _mat(material),
                'name': grp,
            },
        )
        if not _bad(rr):
            return f'drew stadium "{grp}" as one stadium_ring: {W:g} x {D:g} m, {nt} tiers ({H:g} m). {rr}'

    # Path 2 (base tools only): four stands around a grass pitch.
    sd = max(2, min(min(ncols, nrows) // 5, (min(ncols, nrows) - 3) // 2))
    stands = {
        'north stand': (c0, r0, c1, r0 + sd - 1),
        'south stand': (c0, r1 - sd + 1, c1, r1),
        'west stand': (c0, r0 + sd, c0 + sd - 1, r1 - sd),
        'east stand': (c1 - sd + 1, r0 + sd, c1, r1 - sd),
    }
    made = 0
    for label, (a0, b0, a1, b1) in stands.items():
        g = f'{grp} {label}'
        rr = _call(
            d,
            'draw_box',
            {
                'cell_from': cell_name(a0, b0),
                'cell_to': cell_name(a1, b1),
                'storeys': 1,
                'slabs': True,
                'roof': 'none',
                'wall_h': H,
                'material': _mat(material),
                'name': g,
            },
        )
        if not _bad(rr):
            made += 1
    pc0, pr0, pc1, pr1 = c0 + sd, r0 + sd, c1 - sd, r1 - sd
    _, _, _, _, pw, pdp, pcx, pcz = _block(pc0, pr0, pc1, pr1)
    rp = _call(
        d,
        'add_object',
        {
            'kind': 'pad',
            'cell': A.cell_of(pcx, pcz),
            'storey': 0,
            'params': {'w': round(pw, 3), 'd': round(pdp, 3), 't': 0.2},
            'material': 'mat_grass',
            'name': f'{grp} pitch',
        },
    )
    return (
        f'drew stadium "{grp}": {made} stands of {H:g} m ({nt} tiers x 4 m), {sd} m deep, around a '
        f'{pw:g} x {pdp:g} m grass pitch. {rp}'
    )


TOOLS = [
    (
        {
            'name': 'draw_office_tower',
            'description': 'A glazed office tower on a cell block: concrete box with a floor slab per storey, four glass windows per wall per storey (or curtain walls when that family is loaded), a central 4 x 4 m lift/stair core through every storey, a flat roof and a rooftop plant box. Use for "office tower", "kantoortoren", any tall glazed commercial block.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'cell_from': {'type': 'string'},
                    'cell_to': {'type': 'string'},
                    'storeys': {'type': 'integer'},
                    'glass': {'type': 'boolean'},
                    'core': {'type': 'boolean'},
                    'material': {'type': 'string', 'enum': MATERIALS},
                    'name': {'type': 'string'},
                },
                'required': ['cell_from', 'cell_to'],
            },
        },
        t_draw_office_tower,
    ),
    (
        {
            'name': 'draw_warehouse',
            'description': 'A single tall shed storey (height_m, default 8 m) with a floor slab, a low gable roof (2 m rise), a row of garage doors along the south side and glass skylights on the roof. Use for warehouses, distribution sheds, loods, bedrijfshal.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'cell_from': {'type': 'string'},
                    'cell_to': {'type': 'string'},
                    'height_m': {'type': 'number'},
                    'doors': {'type': 'integer'},
                    'skylights': {'type': 'boolean'},
                    'material': {'type': 'string', 'enum': MATERIALS},
                    'name': {'type': 'string'},
                },
                'required': ['cell_from', 'cell_to'],
            },
        },
        t_draw_warehouse,
    ),
    (
        {
            'name': 'draw_shop',
            'description': 'A shop unit: a box with a flat roof and a shopfront on the south side — a 6 m wide glass strip (h 2.4, sill 0.3), a double door and a canopy over it. Use for a shop, winkel, retail unit, a corner store.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'cell_from': {'type': 'string'},
                    'cell_to': {'type': 'string'},
                    'storeys': {'type': 'integer'},
                    'material': {'type': 'string', 'enum': MATERIALS},
                    'name': {'type': 'string'},
                },
                'required': ['cell_from', 'cell_to'],
            },
        },
        t_draw_shop,
    ),
    (
        {
            'name': 'draw_school',
            'description': 'A school: a main block across the north of the plot plus `wings` perpendicular blocks running south from it, each with windows on every storey and a flat roof. Use for schools, basisschool, a college, any comb-plan institutional building.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'cell_from': {'type': 'string'},
                    'cell_to': {'type': 'string'},
                    'wings': {'type': 'integer'},
                    'storeys': {'type': 'integer'},
                    'material': {'type': 'string', 'enum': MATERIALS},
                    'name': {'type': 'string'},
                },
                'required': ['cell_from', 'cell_to'],
            },
        },
        t_draw_school,
    ),
    (
        {
            'name': 'draw_church',
            'description': 'A church: a nave with 9 m walls, tall glass windows (1.2 x 4 m, sill 2.5) every 4 m and a gable roof with a 5 m rise, plus an optional 3 x 3 m west tower 18 m tall capped with a pyramid spire, and a double door at the west end. Use for a church, kerk, chapel, temple.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'cell_from': {'type': 'string'},
                    'cell_to': {'type': 'string'},
                    'tower': {'type': 'boolean'},
                    'material': {'type': 'string', 'enum': MATERIALS},
                    'name': {'type': 'string'},
                },
                'required': ['cell_from', 'cell_to'],
            },
        },
        t_draw_church,
    ),
    (
        {
            'name': 'draw_parking_garage',
            'description': "A multi-storey car park: `decks` decks of 3.0 m with a slab each, no windows, a 3 m wide ramp opening in every deck's south wall and a column grid at roughly 8 m on every deck. Use for a parking garage, parkeergarage, a deck park.",
            'input_schema': {
                'type': 'object',
                'properties': {
                    'cell_from': {'type': 'string'},
                    'cell_to': {'type': 'string'},
                    'decks': {'type': 'integer'},
                    'material': {'type': 'string', 'enum': MATERIALS},
                    'name': {'type': 'string'},
                },
                'required': ['cell_from', 'cell_to'],
            },
        },
        t_draw_parking_garage,
    ),
    (
        {
            'name': 'draw_stadium',
            'description': 'A stadium: one stadium_ring sized to the block when that kind is loaded, otherwise four stands (walls 4 m per tier) around a central grass pitch pad. Use for a stadium, arena, sports ground with stands.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'cell_from': {'type': 'string'},
                    'cell_to': {'type': 'string'},
                    'tiers': {'type': 'integer'},
                    'material': {'type': 'string', 'enum': MATERIALS},
                    'name': {'type': 'string'},
                },
                'required': ['cell_from', 'cell_to'],
            },
        },
        t_draw_stadium,
    ),
]

EXAMPLES = [
    {
        'ask': 'an office tower on the block C4 to V23, 12 floors, all glass, with a core',
        'calls': [
            {
                'tool': 'draw_office_tower',
                'args': {'cell_from': 'C4', 'cell_to': 'V23', 'storeys': 12, 'glass': True, 'core': True},
            }
        ],
    },
    {
        'ask': 'een loods van 30 bij 20 meter, 8 meter hoog, met drie roldeuren',
        'calls': [
            {'tool': 'draw_warehouse', 'args': {'cell_from': 'D40', 'cell_to': 'AG59', 'height_m': 8, 'doors': 3}}
        ],
    },
    {
        'ask': 'a corner shop from B12 to L17 with a shopfront',
        'calls': [{'tool': 'draw_shop', 'args': {'cell_from': 'B12', 'cell_to': 'L17', 'storeys': 1}}],
    },
    {
        'ask': 'a two-storey school with two wings on the plot C80 to V99',
        'calls': [{'tool': 'draw_school', 'args': {'cell_from': 'C80', 'cell_to': 'V99', 'wings': 2, 'storeys': 2}}],
    },
    {
        'ask': 'een dorpskerk met toren op C160 tot V179',
        'calls': [{'tool': 'draw_church', 'args': {'cell_from': 'C160', 'cell_to': 'V179', 'tower': True}}],
    },
    {
        'ask': 'a three-deck parking garage behind it, C200 to V219',
        'calls': [{'tool': 'draw_parking_garage', 'args': {'cell_from': 'C200', 'cell_to': 'V219', 'decks': 3}}],
    },
]
