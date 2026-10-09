# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""zyg_workflows.arch_assistant_ext.water_leisure.leisure — ponds, canals and fountains; sports courts, playgrounds and beach sets.

Moved verbatim out of water_leisure.py (lines 1262-1603); zero logic changes.
"""

from __future__ import annotations

from zyg_workflows.arch_assistant_ext.water_leisure.base import (
    COURT_SLOPE,
    COURT_SPREAD,
    Drawing,
    LEVEL_TOL,
    SPORTS,
    _cells,
    _level_check,
    _line_span,
    _mat,
    _num,
    _room,
    block_bounds,
    cell_centre,
    cell_name,
    ground_height,
    ground_plane,
    math,
    parse_cell,
    place_height,
)

from zyg_workflows.arch_assistant_ext.water_leisure.pool import _storey_base


def t_add_pond(d: Drawing, a, centre, radius=4.0, radius_z=None, depth=0.6, base_height=None, material='', name=''):
    cx, cz = cell_centre(*parse_cell(centre))
    rx = _num(radius, 4.0)
    rz = _num(radius_z, rx) if radius_z is not None else rx
    if rx < 0.5 or rx > 80 or rz < 0.5 or rz > 80:
        return 'refused: a pond radius must be between 0.5 and 80 m'
    dep = _num(depth, 0.6)
    if dep < 0.15 or dep > 5:
        return 'refused: a pond must be between 0.15 and 5 m deep'
    full = _room(d, 1)
    if full:
        return full
    cn = cell_name(*parse_cell(centre))
    y, bad, _deck, note = _level_check(d, f'the pond at {cn}', cx, cz, 2 * rx, 2 * rz, 0.0, base_height)
    if bad:
        return bad
    o = d.new(
        'pond',
        {'rx': round(rx, 3), 'rz': round(rz, 3), 'depth': round(dep, 3)},
        cx,
        cz,
        y,
        0.0,
        _mat(material, 'pond'),
        name=name or 'pond',
        grp=name or 'pond',
    )
    return f'pond {o["id"]} at {cn}: {2 * rx:g} x {2 * rz:g} m across, {dep:g} m deep, ' + note + f'water level {y:g} m'


CANAL_LEVEL_MSG = 'a canal is level water — use add_stream for water that flows, or flatten the ground'


def t_add_canal(d: Drawing, a, cells, width=6.0, depth=1.5, base_height=None, material='', name=''):
    try:
        pts = _cells(cells)
    except ValueError as e:
        return f'refused: {e}'
    if len(pts) < 2:
        return 'refused: a canal needs at least two cells — one segment per pair'
    w = _num(width, 6.0)
    dep = _num(depth, 1.5)
    if w < 0.5 or w > 120:
        return 'refused: a canal must be between 0.5 and 120 m wide'
    if dep < 0.3 or dep > 20:
        return 'refused: a canal must be between 0.3 and 20 m deep'
    full = _room(d, len(pts) - 1)
    if full:
        return full
    # every reach is checked BEFORE any of them is drawn: half a canal is worse
    # than none. Per reach: the two ends must agree within 0.5 m and the ground
    # along the reach must not hump more than that either.
    reaches = []
    for i in range(len(pts) - 1):
        (x0, z0), (x1, z1) = pts[i], pts[i + 1]
        L = math.hypot(x1 - x0, z1 - z0)
        if L < 0.5:
            return f'refused: cells {i + 1} and {i + 2} are the same — every segment needs two different cells'
        ry = math.atan2(-(z1 - z0), x1 - x0)
        mx, mz = (x0 + x1) / 2, (z0 + z1) / 2
        if base_height is not None and base_height != '':
            reaches.append((L, ry, mx, mz, _num(base_height, 0.0)))
            continue
        ends = abs(ground_height(d, x1, z1) - ground_height(d, x0, z0))
        lo, hi = _line_span(d, x0, z0, x1, z1)
        rise = max(ends, hi - lo)
        if rise > LEVEL_TOL:
            return f'refused: the ground along reach {i + 1} rises {rise:.2f} m over {L:g} m — ' + CANAL_LEVEL_MSG
        reaches.append((L, ry, mx, mz, round(ground_height(d, mx, mz), 4)))
    grp = name or 'canal'
    ids, total = [], 0.0
    for i, (L, ry, mx, mz, y) in enumerate(reaches):
        o = d.new(
            'canal',
            {'len': round(L, 4), 'w': round(w, 3), 'depth': round(dep, 3)},
            mx,
            mz,
            y,
            ry,
            _mat(material, 'canal'),
            name=f'canal reach {i + 1}',
            grp=grp,
        )
        ids.append(o['id'])
        total += L
    ys = [r[4] for r in reaches]
    return (
        f'dug canal "{grp}": {len(ids)} segment(s) {ids[0]}..{ids[-1]}, {total:.1f} m in all, '
        f'{w:g} m wide and {dep:g} m deep, water level '
        + (f'{ys[0]:g} m' if max(ys) - min(ys) < 1e-6 else f'{min(ys):g}..{max(ys):g} m')
    )


def t_add_fountain(
    d: Drawing, a, centre, radius=2.0, tiers=3, height=2.5, base_height=None, material='', name='', storey=None
):
    base_height = _storey_base(d, storey, base_height)
    cx, cz = cell_centre(*parse_cell(centre))
    r = _num(radius, 2.0)
    if r < 0.4 or r > 40:
        return 'refused: a fountain basin must be between 0.4 and 40 m across the radius'
    n = int(_num(tiers, 3))
    if n < 1 or n > 8:
        return 'refused: a fountain has between 1 and 8 tiers'
    h = _num(height, 2.5)
    if h < 1.0 or h > 30:
        return 'refused: a fountain must be between 1 and 30 m tall'
    full = _room(d, 1)
    if full:
        return full
    cn = cell_name(*parse_cell(centre))
    y, bad, _deck, note = _level_check(d, f'the fountain at {cn}', cx, cz, 2 * r, 2 * r, 0.0, base_height)
    if bad:
        return bad
    o = d.new(
        'fountain',
        {'r': round(r, 3), 'tiers': n, 'h': round(h, 3)},
        cx,
        cz,
        y,
        0.0,
        _mat(material, 'fountain'),
        name=name or 'fountain',
        grp=name or 'fountain',
    )
    return (
        f'fountain {o["id"]} at {cn}: basin {2 * r:g} m across, {n} tier(s), {h:g} m tall, '
        + note
        + f'standing at {y:g} m'
    )


# ── sport & play ────────────────────────────────────────────────────────────
def t_add_sports_court(
    d: Drawing, a, cell_from, cell_to, sport='football', lines=True, base_height=None, material='', name=''
):
    s = str(sport or 'football').strip().lower()
    if s not in SPORTS:
        return 'refused: sport must be football, tennis or basketball'
    xmin, zmin, xmax, zmax = block_bounds(cell_from, cell_to)
    W, D = xmax - xmin, zmax - zmin
    cx, cz = (xmin + xmax) / 2, (zmin + zmax) / 2
    if W < 5 or D < 5:
        return 'refused: a court needs a block of at least 5 x 5 cells'
    full = _room(d, 3)
    if full:
        return full
    if base_height is not None and base_height != '':
        y = _num(base_height, 0.0)
    else:
        y0, glx, glz, spread = ground_plane(d, cx, cz, W, D, 0.0, 5)
        grade = math.hypot(glx, glz)
        if grade > COURT_SLOPE:
            return (
                f'refused: the ground under that block falls {100 * grade:.1f} % — a court needs level '
                f'ground (3 % at most): flatten_pad it first, or find flatter ground'
            )
        if spread > COURT_SPREAD:
            return (
                f'refused: the ground under that block is {spread:.2f} m off a plane — a court needs level '
                f'ground (0.3 m at most): flatten_pad it first, or find flatter ground'
            )
        y = round(y0, 4)
    grp = name or f'{s} court'
    court = d.new(
        'sports_court',
        {'w': round(W, 4), 'd': round(D, 4), 'lines': 1 if lines else 0},
        cx,
        cz,
        y,
        0.0,
        _mat(material, 'sports_court'),
        name=f'{s} court',
        grp=grp,
    )
    long_x = W >= D
    long_len, short_len = (W, D) if long_x else (D, W)
    extra = []
    if s == 'football':
        gw = round(min(7.32, short_len * 0.45), 3)
        gh = round(min(2.44, gw / 3.0), 3)
        gd = round(min(2.0, short_len * 0.12), 3)
        for sign in (-1, 1):
            if long_x:
                gx, gz, ry = cx + sign * (W / 2 - 1.0), cz, (-math.pi / 2 if sign < 0 else math.pi / 2)
            else:
                gx, gz, ry = cx, cz + sign * (D / 2 - 1.0), (math.pi if sign < 0 else 0.0)
            extra.append(
                d.new(
                    'goal_posts',
                    {'w': gw, 'h': gh, 'd': gd},
                    gx,
                    gz,
                    y,
                    ry,
                    _mat('', 'goal_posts'),
                    name=f'{"west" if sign < 0 else "east"} goal',
                    grp=grp,
                )['id']
            )
    elif s == 'tennis':
        nw = round(min(12.8, short_len + 0.9), 3)
        extra.append(
            d.new(
                'tennis_net',
                {'w': nw, 'h': 1.07},
                cx,
                cz,
                y,
                (math.pi / 2 if long_x else 0.0),
                _mat('', 'tennis_net'),
                name='net',
                grp=grp,
            )['id']
        )
    return (
        f'{s} court {court["id"]} "{grp}": {W:g} x {D:g} m over cells {cell_name(*parse_cell(cell_from))}..'
        f'{cell_name(*parse_cell(cell_to))} at {y:g} m'
        + (f', plus {len(extra)} fitting(s) {", ".join(extra)}' if extra else ', lines only')
    )


def t_add_playground(d: Drawing, a, cell_from, cell_to, base_height=None, material='', name=''):
    xmin, zmin, xmax, zmax = block_bounds(cell_from, cell_to)
    W, D = xmax - xmin, zmax - zmin
    if W < 6 or D < 6:
        return f'refused: a playground needs at least 6 x 6 cells — that block is {W:g} x {D:g} m'
    full = _room(d, 3)
    if full:
        return full
    cx, _cz = (xmin + xmax) / 2, (zmin + zmax) / 2
    grp = name or 'playground'
    # R5: each piece stands on the ground under ITSELF, upright, no tilt
    sl = round(min(4.0, W * 0.45), 3)
    slx, slz = xmin + sl / 2 + 0.5, zmin + 1.2
    slide = d.new(
        'playground_slide',
        {'h': 2, 'l': sl, 'w': 0.6},
        slx,
        slz,
        place_height(d, slx, slz, base_height),
        0.0,
        _mat(material, 'playground_slide'),
        name='slide',
        grp=grp,
    )
    sw = round(min(3.0, W * 0.35), 3)
    swx, swz = xmax - sw / 2 - 0.5, zmin + 1.2
    swing = d.new(
        'swing',
        {'w': sw, 'h': 2.4, 'seats': 2},
        swx,
        swz,
        place_height(d, swx, swz, base_height),
        0.0,
        _mat(material, 'swing'),
        name='swings',
        grp=grp,
    )
    pw = round(min(3.0, W * 0.4), 3)
    pd = round(min(3.0, D * 0.4), 3)
    pz = zmax - pd / 2 - 0.5
    pit = d.new(
        'sandpit',
        {'w': pw, 'd': pd, 't': 0.3},
        cx,
        pz,
        place_height(d, cx, pz, base_height),
        0.0,
        _mat(material, 'sandpit'),
        name='sandpit',
        grp=grp,
    )
    ys = [slide['y'], swing['y'], pit['y']]
    return (
        f'playground "{grp}" over {W:g} x {D:g} m: slide {slide["id"]} ({sl:g} m long), '
        f'swings {swing["id"]} ({sw:g} m wide, 2 seats), sandpit {pit["id"]} ({pw:g} x {pd:g} m)'
        + (
            f' — each on the deck or ground under it, {min(ys):g}..{max(ys):g} m'
            if max(ys) - min(ys) > 1e-6
            else f' — on the ground at {ys[0]:g} m'
        )
    )


def _deck_or_ground(d: Drawing, x, z, base_height):
    """2026-09-10: a lounger on a roof cell lands on the ROOF DECK, not on the
    ground 54 m below it (two runs placed the roof loungers at 0 m, deleted them
    and placed them again with base_height=54.3). No base: the highest deck
    covering the point, else the ground; a base is lifted out of a deck as before."""
    if base_height in (None, ''):
        from zyg_workflows.arch_assistant import surface_top

        return round(surface_top(d, x, z), 4)
    return place_height(d, x, z, base_height)


def t_add_beach_set(d: Drawing, a, cells, umbrellas=True, base_height=None, material='', name='', storey=None):
    base_height = _storey_base(d, storey, base_height)
    try:
        pts = _cells(cells)
    except ValueError as e:
        return f'refused: {e}'
    full = _room(d, len(pts) * (2 if umbrellas else 1))
    if full:
        return full
    grp = name or 'beach set'
    n_l = n_u = 0
    ys = []
    for i, (x, z) in enumerate(pts):
        # R5: a lounger and its parasol each sit on the ground under themselves
        d.new(
            'sun_lounger',
            {'l': 1.9, 'w': 0.7, 'h': 0.4},
            x,
            z,
            _deck_or_ground(d, x, z, base_height),
            0.0,
            _mat(material, 'sun_lounger'),
            name=f'lounger {i + 1}',
            grp=grp,
        )
        ys.append(_deck_or_ground(d, x, z, base_height))
        n_l += 1
        if umbrellas:
            d.new(
                'umbrella',
                {'r': 1.5, 'h': 2.3},
                x - 1.4,
                z,
                _deck_or_ground(d, x - 1.4, z, base_height),
                0.0,
                _mat('', 'umbrella'),
                name=f'parasol {i + 1}',
                grp=grp,
            )
            n_u += 1
    return (
        f'set out "{grp}": {n_l} sun lounger(s)'
        + (f' and {n_u} parasol(s)' if n_u else '')
        + f' on {len(pts)} cell(s), each on the deck or ground under it ({min(ys):g}..{max(ys):g} m)'
    )
