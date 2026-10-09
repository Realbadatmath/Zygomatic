# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""typologies_residential — whole houses in one call.

This family adds NO new kinds. Every tool is a RECIPE: it composes the base
tools through `arch_assistant.call_tool` (draw_box, add_windows, add_opening,
add_roof, add_slab, add_object, set_material) with Dutch/European defaults, so
the records are exactly the ones the tab and Blender already know how to build.

Tools: draw_house, draw_row_houses, draw_apartment_block, draw_villa, draw_farm.

Two conventions the recipes rely on:
  · `draw_box` names its walls '<side> wall st<k>' inside the group it is given,
    with north = zmin, south = zmax, west = xmin, east = xmax. That is how a
    door lands on the right wall without parsing the result text.
  · `add_roof` places an unrotated record, and roof_gable's ridge runs along the
    record's local X. When the block is deeper than it is wide the recipe swaps
    w/d and sets ry = 90 deg so the ridge follows the LONG axis.

Where an optional tool from another family exists (add_balconies, add_pool) the
recipe delegates to it, but only KEEPS the result when it produced at least the
expected number of objects and all of them landed inside the requested block;
otherwise it undoes the delegation and falls back to base tools, so a recipe
never scatters objects a caller did not ask for.
"""

from __future__ import annotations

import math

from zyg_workflows import arch_assistant as A
from zyg_workflows.arch_assistant import MATERIALS, MAX_OBJECTS, Drawing, _num, block_bounds, cell_name, parse_cell

KINDS: dict = {}
OPENINGS: list = []

STYLES = ('rowhouse', 'villa', 'bungalow', 'farmhouse', 'modern')
SIDES = ('north', 'east', 'south', 'west')
_STYLE_MAT = {
    'rowhouse': 'mat_brick',
    'farmhouse': 'mat_brick',
    'bungalow': 'mat_brick',
    'villa': 'mat_plaster',
    'modern': 'mat_concrete',
}
_STYLE_ROOF = {'rowhouse': 'gable', 'villa': 'hip', 'bungalow': 'gable', 'farmhouse': 'gable', 'modern': 'flat'}
_STYLE_PITCH = {'farmhouse': 0.6, 'bungalow': 0.25}  # roof h / min(w, d); 0.4 otherwise
_TOL = 2.5  # m a delegated tool may stray outside the block

PROMPT = (
    'Residential typologies (a whole building per call, Dutch proportions): '
    'draw_house(cell_from, cell_to, storeys, style, door_side, garage) draws walls, slabs, the style roof '
    '(rowhouse/bungalow/farmhouse gable, villa hip, modern flat), 2 windows per wall per storey (rowhouse: '
    'front and back only) and one front door — for "build a house/bungalow/farmhouse here"; '
    'draw_row_houses(cell_from, cell_to, count, storeys) splits the block into count terraced houses, '
    'party walls shared, doors alternating, one continuous gable; '
    'draw_apartment_block(cell_from, cell_to, storeys, balconies, entrances) is a flat-roofed block with 3 '
    'windows per wall per storey, a balcony per upper storey and entrance doors; draw_villa(cell_from, '
    'cell_to, storeys, pool) is a villa with a garage and an optional pool in the garden; draw_farm('
    'cell_from, cell_to) lays a farmhouse, a 5 m barn and a steel silo along the block.'
)


# ── helpers ─────────────────────────────────────────────────────────────────
def _call(d: Drawing, name: str, args: dict) -> str:
    return A.call_tool(d, name, args)


def _cells(cell_from, cell_to) -> tuple:
    c0, r0 = parse_cell(cell_from)
    c1, r1 = parse_cell(cell_to)
    return min(c0, c1), min(r0, r1), max(c0, c1), max(r0, r1)


def _last(d: Drawing):
    return d.find(d.added[-1]) if d.added else None


def _mat(material, default):
    return material if material in MATERIALS else default


def _grp_walls(d: Drawing, grp: str, side=None, storey=None) -> list:
    out = []
    for o in d.objs:
        if o['grp'] != grp or o['kind'] != 'wall':
            continue
        if side and not o['name'].lower().startswith(side):
            continue
        if storey is not None and not o['name'].endswith('st%d' % int(storey)):
            continue
        out.append(o)
    return out


def _count(d: Drawing, grp: str, kind: str) -> int:
    return sum(1 for o in d.objs if o['grp'] == grp and o['kind'] == kind)


def _inside(o: dict, box: tuple, tol: float = _TOL) -> bool:
    xmin, zmin, xmax, zmax = box
    return xmin - tol <= o['x'] <= xmax + tol and zmin - tol <= o['z'] <= zmax + tol


def _roof(d: Drawing, grp, cf, ct, storey, kind, W, D, height=None, y=None, material=''):
    """add_roof + the two things add_roof cannot do: a group, and the gable ridge
    on the long axis. `y` overrides the storey height (a 5 m barn wall)."""
    args = {'cell_from': cf, 'cell_to': ct, 'storey': int(storey), 'kind': kind}
    if kind != 'flat':
        args['height'] = round(_num(height, min(W, D) * 0.4), 3)
        args['overhang'] = 0.4
    if material:
        args['material'] = material
    txt = _call(d, 'add_roof', args)
    r = _last(d)
    if r is None or not r['kind'].startswith('roof_'):
        return None, txt
    r['grp'] = grp
    r['name'] = f'{kind} roof'
    if y is not None:
        r['y'] = round(float(y), 4)
    if kind == 'gable' and D > W:
        r['p']['w'], r['p']['d'] = r['p']['d'], r['p']['w']
        r['ry'] = round(math.pi / 2, 6)
    return r, txt


def _delegate(d: Drawing, tool: str, args: dict, want: int, box: tuple, grp: str) -> int:
    """Try another family's tool. Keep it only if it made at least `want` objects
    and all of them are in the block; otherwise undo. Returns how many kept."""
    if tool not in A.TOOL_FN:
        return 0
    n0 = len(d.objs)
    _call(d, tool, args)
    made = d.objs[n0:]
    if len(made) >= want and all(_inside(o, box) for o in made):
        for o in made:
            o['grp'] = grp
        return len(made)
    if made:
        d.remove(list(made))
    return 0


def _house_shell(d: Drawing, grp, cf, ct, storeys, style, door_side, mat, W, D):
    """walls + slabs + windows + roof + one door. Returns (windows, door_id)."""
    txt = _call(
        d,
        'draw_box',
        {
            'cell_from': cf,
            'cell_to': ct,
            'storeys': storeys,
            'storey_from': 0,
            'slabs': True,
            'roof': 'none',
            'material': mat,
            'name': grp,
        },
    )
    if txt.startswith('refused'):
        return None, txt
    wargs = {
        'walls': grp,
        'per_wall': 2,
        'width': 1.2,
        'height': 1.4,
        'sill': 0.9,
        'material': 'mat_glass' if style == 'modern' else 'mat_plaster',
    }
    if style == 'rowhouse':
        wargs['sides'] = ['north', 'south']
    _call(d, 'add_windows', wargs)
    if style == 'modern':
        south = [o['id'] for o in _grp_walls(d, grp, 'south')]
        if south:
            _call(d, 'set_material', {'which': south, 'material': 'mat_glass'})
    door_id = ''
    front = _grp_walls(d, grp, door_side, storey=0)
    if front:
        _call(
            d, 'add_opening', {'wall_id': front[0]['id'], 'kind': 'door', 'at': 'middle', 'width': 0.95, 'height': 2.15}
        )
        o = _last(d)
        if o is not None:
            o['name'] = f'front door ({door_side})'
            door_id = o['id']
    _roof(d, grp, cf, ct, storeys, _STYLE_ROOF[style], W, D, height=_STYLE_PITCH.get(style, 0.4) * min(W, D))
    return _count(d, grp, 'window'), door_id


# ── tools ───────────────────────────────────────────────────────────────────
def t_draw_house(
    d: Drawing,
    a,
    cell_from,
    cell_to,
    storeys=2,
    style='rowhouse',
    door_side='south',
    garage=False,
    material=None,
    name='',
):
    style = str(style or 'rowhouse').strip().lower()
    if style not in STYLES:
        return 'refused: style must be one of ' + ', '.join(STYLES)
    side = str(door_side or 'south').strip().lower()
    if side not in SIDES:
        return 'refused: door_side must be north, east, south or west'
    c0, r0, c1, r1 = _cells(cell_from, cell_to)
    ncols, nrows = c1 - c0 + 1, r1 - r0 + 1
    if ncols < 3 or nrows < 3:
        return f'refused: {ncols} x {nrows} cells is too small — a house needs at least 3 x 3 m'
    n = max(1, min(20, int(_num(storeys, 2))))
    gar = bool(garage)
    if gar and (ncols < 8 or nrows < 6):
        return (
            'refused: a house with a garage needs at least 8 x 6 cells '
            '(5 across for the house, 3 for the 3 x 6 m garage)'
        )
    need = n * 5 + 1 + n * 8 + 2 + (8 if gar else 0)
    if len(d.objs) + need > MAX_OBJECTS:
        return f'refused: that is about {need} objects and the drawing may hold {MAX_OBJECTS} in total'

    hc1 = c1 - 3 if gar else c1
    W, D = float(hc1 - c0 + 1), float(nrows)
    grp = str(name or f'{style} {cell_name(c0, r0)}')
    mat = _mat(material, _STYLE_MAT[style])
    cf, ct = cell_name(c0, r0), cell_name(hc1, r1)
    nwin, door_id = _house_shell(d, grp, cf, ct, n, style, side, mat, W, D)
    if nwin is None:
        return door_id  # the base tool's refusal

    ggrp = ''
    if gar:
        ggrp = f'{grp} garage'
        gd = min(6, nrows)
        gf, gt = cell_name(hc1 + 1, r0), cell_name(c1, r0 + gd - 1)
        _call(
            d,
            'draw_box',
            {
                'cell_from': gf,
                'cell_to': gt,
                'storeys': 1,
                'slabs': True,
                'roof': 'none',
                'material': mat,
                'name': ggrp,
            },
        )
        _roof(d, ggrp, gf, gt, 1, 'gable', 3.0, float(gd), height=0.75)
        gside = side if side in ('north', 'south') else 'south'
        gw = _grp_walls(d, ggrp, gside, storey=0)
        if gw:
            if A.is_opening('door_garage'):
                _call(d, 'add_opening', {'wall_id': gw[0]['id'], 'kind': 'door_garage', 'at': 'middle'})
            else:
                _call(
                    d,
                    'add_opening',
                    {'wall_id': gw[0]['id'], 'kind': 'double_door', 'at': 'middle', 'width': 2.4, 'height': 2.2},
                )
            o = _last(d)
            if o is not None:
                o['name'] = 'garage door'
    return (
        f'drew {style} house "{grp}" on {cell_name(c0, r0)}..{cell_name(c1, r1)}: {W:g} x {D:g} m, '
        f'{n} storeys, {4 * n} walls, {n} slabs, a {_STYLE_ROOF[style]} roof, {nwin} windows, '
        f'1 {side} door ({door_id or "none"}), {mat}'
        + (f'; plus a 3 x {min(6, nrows)} m garage "{ggrp}"' if gar else '')
    )


def t_draw_row_houses(d: Drawing, a, cell_from, cell_to, count=4, storeys=2, style='rowhouse', material=None, name=''):
    style = str(style or 'rowhouse').strip().lower()
    if style not in STYLES:
        return 'refused: style must be one of ' + ', '.join(STYLES)
    c0, r0, c1, r1 = _cells(cell_from, cell_to)
    ncols, nrows = c1 - c0 + 1, r1 - r0 + 1
    k = int(_num(count, 4))
    if k < 2 or k > 30:
        return 'refused: count must be between 2 and 30 houses'
    n = max(1, min(20, int(_num(storeys, 2))))
    along_cols = ncols >= nrows
    span = ncols if along_cols else nrows
    if span < 4 * k:
        return (
            f'refused: {span} m along the long axis is too little for {k} houses '
            f'— give at least {4 * k} cells or fewer houses'
        )
    if min(ncols, nrows) < 4:
        return 'refused: the block must be at least 4 m across the row'
    need = k * (n * 5 + n * 4 + 1) + 1
    if len(d.objs) + need > MAX_OBJECTS:
        return f'refused: that is about {need} objects and the drawing may hold {MAX_OBJECTS} in total'

    base = c0 if along_cols else r0
    edges = [base + (i * span) // k for i in range(k + 1)]
    stem = str(name or f'row {cell_name(c0, r0)}')
    pair = ('south', 'north') if along_cols else ('east', 'west')
    mat = _mat(material, _STYLE_MAT[style])
    grps, doors = [], 0
    for i in range(k):
        if along_cols:
            hf, ht = cell_name(edges[i], r0), cell_name(edges[i + 1] - 1, r1)
        else:
            hf, ht = cell_name(c0, edges[i]), cell_name(c1, edges[i + 1] - 1)
        grp = f'{stem} house {i + 1}'
        grps.append(grp)
        _call(
            d,
            'draw_box',
            {
                'cell_from': hf,
                'cell_to': ht,
                'storeys': n,
                'storey_from': 0,
                'slabs': True,
                'roof': 'none',
                'material': mat,
                'name': grp,
            },
        )
        wargs = {
            'walls': grp,
            'per_wall': 2,
            'material': 'mat_plaster',
            'sides': list(pair) if style == 'rowhouse' else None,
        }
        if wargs['sides'] is None:
            wargs.pop('sides')
        _call(d, 'add_windows', wargs)
        side = pair[i % 2]
        front = _grp_walls(d, grp, side, storey=0)
        if front:
            _call(
                d,
                'add_opening',
                {'wall_id': front[0]['id'], 'kind': 'door', 'at': 'middle', 'width': 0.95, 'height': 2.15},
            )
            o = _last(d)
            if o is not None:
                o['name'] = f'front door ({side})'
            doors += 1
    _roof(
        d,
        f'{stem} roof',
        cell_name(c0, r0),
        cell_name(c1, r1),
        n,
        'gable',
        float(ncols),
        float(nrows),
        height=0.4 * min(ncols, nrows),
    )
    return (
        f'drew {k} terraced houses "{grps[0]}".."{grps[-1]}" across {cell_name(c0, r0)}..'
        f'{cell_name(c1, r1)}: {span / k:.1f} m wide each, {n} storeys, {4 * n * k} walls, '
        f'{n * k} slabs, {doors} doors alternating {pair[0]}/{pair[1]}, one continuous gable roof'
    )


def t_draw_apartment_block(
    d: Drawing, a, cell_from, cell_to, storeys=5, balconies=True, entrances=1, material=None, name=''
):
    c0, r0, c1, r1 = _cells(cell_from, cell_to)
    ncols, nrows = c1 - c0 + 1, r1 - r0 + 1
    if ncols < 6 or nrows < 6:
        return f'refused: {ncols} x {nrows} cells is too small — an apartment block needs at least 6 x 6 m'
    n = max(1, min(60, int(_num(storeys, 5))))
    e = max(0, min(6, int(_num(entrances, 1))))
    need = n * 5 + n * 12 + n + e + 1
    if len(d.objs) + need > MAX_OBJECTS:
        return f'refused: that is about {need} objects and the drawing may hold {MAX_OBJECTS} in total'
    grp = str(name or f'apartments {cell_name(c0, r0)}')
    mat = _mat(material, 'mat_concrete')
    cf, ct = cell_name(c0, r0), cell_name(c1, r1)
    box = block_bounds(cf, ct)
    _call(
        d,
        'draw_box',
        {
            'cell_from': cf,
            'cell_to': ct,
            'storeys': n,
            'storey_from': 0,
            'slabs': True,
            'roof': 'none',
            'material': mat,
            'name': grp,
        },
    )
    _call(
        d,
        'add_windows',
        {'walls': grp, 'per_wall': 3, 'width': 1.4, 'height': 1.5, 'sill': 0.85, 'material': 'mat_glass'},
    )
    _roof(d, grp, cf, ct, n, 'flat', float(ncols), float(nrows), material=mat)

    bgrp = f'{grp} balconies'
    nbal = 0
    if balconies and n > 1:
        want = n - 1
        nbal = _delegate(d, 'add_balconies', {'walls': grp, 'side': 'south', 'storeys': want}, want, box, bgrp)
        if not nbal:
            br1 = min(r1 + 1, A.GRID_N - 1)
            for st in range(1, n):
                _call(
                    d,
                    'add_slab',
                    {
                        'cell_from': cell_name(c0, r1),
                        'cell_to': cell_name(c1, br1),
                        'storey': st,
                        'thickness': 0.18,
                        'material': mat,
                        'name': bgrp,
                    },
                )
                o = _last(d)
                if o is not None:
                    o['name'] = f'balcony st{st}'
                nbal += 1
    ndoor = 0
    south = _grp_walls(d, grp, 'south', storey=0)
    if south and e:
        L = _num(south[0]['p'].get('len'), float(ncols))
        for j in range(e):
            _call(
                d,
                'add_opening',
                {
                    'wall_id': south[0]['id'],
                    'kind': 'double_door',
                    'at': round(L * (j + 0.5) / e, 3),
                    'width': 1.8,
                    'height': 2.3,
                },
            )
            o = _last(d)
            if o is not None:
                o['name'] = f'entrance {j + 1}'
            ndoor += 1
    return (
        f'drew apartment block "{grp}" on {cf}..{ct}: {ncols} x {nrows} m, {n} storeys '
        f'({n * d.storey_h:g} m), {4 * n} walls, {n} slabs, {_count(d, grp, "window")} windows '
        f'(3 per wall per storey), a flat roof, {nbal} balconies ("{bgrp}"), {ndoor} entrance doors'
    )


def t_draw_villa(d: Drawing, a, cell_from, cell_to, storeys=2, pool=False, material=None, name=''):
    c0, r0, c1, r1 = _cells(cell_from, cell_to)
    ncols, nrows = c1 - c0 + 1, r1 - r0 + 1
    if ncols < 8 or nrows < 10:
        return (
            f'refused: {ncols} x {nrows} cells is too small — a villa needs at least 8 x 10 m '
            '(house, garage and garden)'
        )
    grp = str(name or f'villa {cell_name(c0, r0)}')
    hrows = max(6, (nrows * 6) // 10)
    hr1 = r0 + hrows - 1
    txt = t_draw_house(
        d,
        a,
        cell_name(c0, r0),
        cell_name(c1, hr1),
        storeys=storeys,
        style='villa',
        door_side='south',
        garage=True,
        material=material,
        name=grp,
    )
    if txt.startswith('refused'):
        return txt
    pgrp = ''
    if pool:
        pr0 = hr1 + 2
        if pr0 > r1 - 2:
            return txt + '; no pool: the garden strip south of the house is under 3 m deep'
        pgrp = f'{grp} pool'
        pw, pd = float(min(8, ncols - 2)), float(min(4, r1 - pr0))
        box = block_bounds(cell_name(c0, r0), cell_name(c1, r1))
        pcell = cell_name(c0 + ncols // 2, (pr0 + r1) // 2)
        if not _delegate(
            d, 'add_pool', {'cell_from': cell_name(c0 + 1, pr0), 'cell_to': cell_name(c1 - 1, r1 - 1)}, 1, box, pgrp
        ):
            _call(
                d,
                'add_object',
                {
                    'kind': 'box',
                    'cell': pcell,
                    'storey': 0,
                    'params': {'w': pw, 'd': pd, 'h': 0.25},
                    'material': 'mat_water',
                    'name': pgrp,
                },
            )
            o = _last(d)
            if o is not None:
                o['name'] = f'pool {pw:g} x {pd:g} m'
    return txt + (f'; pool "{pgrp}" in the garden' if pgrp else '')


def t_draw_farm(d: Drawing, a, cell_from, cell_to, storeys=2, material=None, name=''):
    c0, r0, c1, r1 = _cells(cell_from, cell_to)
    ncols, nrows = c1 - c0 + 1, r1 - r0 + 1
    along_cols = ncols >= nrows
    span, across = (ncols, nrows) if along_cols else (nrows, ncols)
    if span < 20 or across < 8:
        return (
            f'refused: {ncols} x {nrows} cells is too small — a farm needs at least 20 m along its '
            'long axis and 8 m across (farmhouse, barn and a 6 m silo)'
        )
    n = max(1, min(4, int(_num(storeys, 2))))
    need = n * 9 + 12 + 4
    if len(d.objs) + need > MAX_OBJECTS:
        return f'refused: that is about {need} objects and the drawing may hold {MAX_OBJECTS} in total'
    stem = str(name or f'farm {cell_name(c0, r0)}')
    base = c0 if along_cols else r0
    end = base + span - 1
    cut = base + (span - 8) // 2  # farmhouse | barn | 8 cells of silo yard

    def blk(u0, u1):
        if along_cols:
            return cell_name(u0, r0), cell_name(u1, r1)
        return cell_name(c0, u0), cell_name(c1, u1)

    hgrp = f'{stem} farmhouse'
    hf, ht = blk(base, cut - 1)
    hW, hD = (float(cut - base), float(nrows)) if along_cols else (float(ncols), float(cut - base))
    _house_shell(d, hgrp, hf, ht, n, 'farmhouse', 'south', _mat(material, 'mat_brick'), hW, hD)

    bgrp = f'{stem} barn'
    bf, bt = blk(cut, end - 8)
    bW, bD = (float(end - 7 - cut), float(nrows)) if along_cols else (float(ncols), float(end - 7 - cut))
    _call(
        d,
        'draw_box',
        {
            'cell_from': bf,
            'cell_to': bt,
            'storeys': 1,
            'storey_from': 0,
            'wall_h': 5.0,
            'slabs': True,
            'roof': 'none',
            'material': 'mat_timber',
            'name': bgrp,
        },
    )
    _roof(d, bgrp, bf, bt, 2, 'gable', bW, bD, height=0.45 * min(bW, bD), y=5.0)
    bdoor = _grp_walls(d, bgrp, 'south' if along_cols else 'west', storey=0)
    if bdoor:
        _call(
            d,
            'add_opening',
            {'wall_id': bdoor[0]['id'], 'kind': 'opening', 'at': 'middle', 'width': 4.0, 'height': 4.2},
        )
        o = _last(d)
        if o is not None:
            o['name'] = 'barn door'

    sgrp = f'{stem} silo'
    mid = end - 3
    scell = cell_name(mid, (r0 + r1) // 2) if along_cols else cell_name((c0 + c1) // 2, mid)
    _call(
        d,
        'add_object',
        {
            'kind': 'cylinder',
            'cell': scell,
            'storey': 0,
            'params': {'r': 3.0, 'h': 12.0},
            'material': 'mat_steel',
            'name': sgrp,
        },
    )
    o = _last(d)
    if o is not None:
        o['name'] = 'silo 6 m across, 12 m tall'
    return (
        f'drew farmyard "{stem}" on {cell_name(c0, r0)}..{cell_name(c1, r1)}: farmhouse "{hgrp}" '
        f'({hW:g} x {hD:g} m, {n} storeys, steep gable), barn "{bgrp}" ({bW:g} x {bD:g} m, 5 m walls, '
        f'gable, a 4 m door) and a steel silo "{sgrp}" at {scell} (r 3 m, 12 m tall)'
    )


# ── registration ────────────────────────────────────────────────────────────
_CELL = {'type': 'string'}
_MATP = {'type': 'string', 'enum': MATERIALS}

TOOLS = [
    (
        {
            'name': 'draw_house',
            'description': 'One detached or terraced house in a block of cells: walls and floor slabs per storey, '
            'the roof of the chosen style (rowhouse/bungalow/farmhouse gable, villa hip, modern flat), '
            '2 windows per wall per storey (rowhouse: front and back only) and a front door on '
            'door_side. garage=true reserves the eastern 3 cells for a 3 x 6 m garage with its own '
            'door. Use this instead of draw_box whenever the user says "house".',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'cell_from': _CELL,
                    'cell_to': _CELL,
                    'storeys': {'type': 'integer'},
                    'style': {'type': 'string', 'enum': list(STYLES)},
                    'door_side': {'type': 'string', 'enum': list(SIDES)},
                    'garage': {'type': 'boolean'},
                    'material': _MATP,
                    'name': {'type': 'string'},
                },
                'required': ['cell_from', 'cell_to'],
            },
        },
        t_draw_house,
    ),
    (
        {
            'name': 'draw_row_houses',
            'description': 'A terrace: the block split into `count` equal houses along its long axis, each its own '
            'group with its own walls (party walls shared on the plan), doors alternating front and '
            'back, under ONE continuous gable roof. Use for "a row of houses", "a terrace", '
            '"rijtjeshuizen".',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'cell_from': _CELL,
                    'cell_to': _CELL,
                    'count': {'type': 'integer'},
                    'storeys': {'type': 'integer'},
                    'style': {'type': 'string', 'enum': list(STYLES)},
                    'material': _MATP,
                    'name': {'type': 'string'},
                },
                'required': ['cell_from', 'cell_to'],
            },
        },
        t_draw_row_houses,
    ),
    (
        {
            'name': 'draw_apartment_block',
            'description': 'A flat-roofed apartment block: walls and slabs per storey, 3 windows per wall per '
            'storey, a balcony along the south side of every storey above the ground floor, and '
            '`entrances` double doors on the ground floor. Use for "flats", "an apartment building".',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'cell_from': _CELL,
                    'cell_to': _CELL,
                    'storeys': {'type': 'integer'},
                    'balconies': {'type': 'boolean'},
                    'entrances': {'type': 'integer'},
                    'material': _MATP,
                    'name': {'type': 'string'},
                },
                'required': ['cell_from', 'cell_to'],
            },
        },
        t_draw_apartment_block,
    ),
    (
        {
            'name': 'draw_villa',
            'description': 'A detached villa with a hipped roof and a garage on the north part of the block, and an '
            'optional swimming pool in the garden strip south of it. Needs at least 8 x 10 cells.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'cell_from': _CELL,
                    'cell_to': _CELL,
                    'storeys': {'type': 'integer'},
                    'pool': {'type': 'boolean'},
                    'material': _MATP,
                    'name': {'type': 'string'},
                },
                'required': ['cell_from', 'cell_to'],
            },
        },
        t_draw_villa,
    ),
    (
        {
            'name': 'draw_farm',
            'description': 'A farmyard laid out along the long axis of the block: a steep-gabled brick farmhouse, a '
            'timber barn with 5 m walls and a 4 m door, and a steel silo 6 m across and 12 m tall. '
            'Needs at least 20 m along the long axis and 8 m across.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'cell_from': _CELL,
                    'cell_to': _CELL,
                    'storeys': {'type': 'integer'},
                    'material': _MATP,
                    'name': {'type': 'string'},
                },
                'required': ['cell_from', 'cell_to'],
            },
        },
        t_draw_farm,
    ),
]

EXAMPLES = [
    {
        'ask': 'build a two-storey brick house from C4 to H13, front door on the south',
        'calls': [
            {
                'tool': 'draw_house',
                'args': {'cell_from': 'C4', 'cell_to': 'H13', 'storeys': 2, 'style': 'rowhouse', 'door_side': 'south'},
            }
        ],
    },
    {
        'ask': 'a row of 6 terraced houses from C4 to Z13',
        'calls': [{'tool': 'draw_row_houses', 'args': {'cell_from': 'C4', 'cell_to': 'Z13', 'count': 6, 'storeys': 2}}],
    },
    {
        'ask': 'a block of flats on C4 to N23, 5 floors with balconies and two entrances',
        'calls': [
            {
                'tool': 'draw_apartment_block',
                'args': {'cell_from': 'C4', 'cell_to': 'N23', 'storeys': 5, 'balconies': True, 'entrances': 2},
            }
        ],
    },
    {
        'ask': 'a villa with a garage and a pool between C4 and N23',
        'calls': [{'tool': 'draw_villa', 'args': {'cell_from': 'C4', 'cell_to': 'N23', 'storeys': 2, 'pool': True}}],
    },
    {
        'ask': 'a farm with a barn and a silo from C4 to AF13',
        'calls': [{'tool': 'draw_farm', 'args': {'cell_from': 'C4', 'cell_to': 'AF13'}}],
    },
    {
        'ask': 'a modern flat-roofed house with a lot of glass, C10 to K20',
        'calls': [
            {'tool': 'draw_house', 'args': {'cell_from': 'C10', 'cell_to': 'K20', 'storeys': 2, 'style': 'modern'}}
        ],
    },
]
