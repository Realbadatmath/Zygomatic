# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""mountains: the four tools — add_mountain, add_mountain_range, add_ridge and
add_valley, in both the sculpt and the solid mode."""

from __future__ import annotations

import math

from zyg_workflows.arch_assistant import (
    Drawing,
    parse_cell,
    cell_centre,
    cell_name,
    block_bounds,
    MAX_OBJECTS,
    _num,
    place_height,
)

from .field import (
    _hash,
    peak_radius,
)

from .plumbing import (
    _STYLES,
    MAX_H,
    MAX_BLOCK,
    MOUNT_MAX_SLOPE,
    MOUNT_MIN_SLOPE,
    MESA_MAX_SLOPE,
    RIDGE_MAX_SLOPE,
    VALLEY_MAX_DEPTH,
    VALLEY_DEF_DEPTH,
    RANGE_DEF_HEIGHT,
    SCULPT_FEATHER,
    RANGE_SPREAD,
    SCULPT_MAT,
    has_ground,
    sculpt_y,
    ground_snow_words,
    SOLID_WORDS,
    SCULPT_WORDS,
    _mat,
    _bad_size,
    _res_for,
    resolve_snow,
    _snow_words,
)


# ── tools ───────────────────────────────────────────────────────────────────
def t_add_mountain(
    d: Drawing,
    a,
    centre,
    radius=60.0,
    height=40.0,
    style='peak',
    ruggedness=0.45,
    seed=1,
    snow_line='auto',
    base_height=None,
    material='',
    name='',
):
    st = str(style or 'peak').strip().lower()
    if st not in _STYLES:
        return "refused: style must be 'peak', 'volcano' or 'mesa'"
    r = _num(radius, 60.0)
    h = _num(height, 40.0)
    bad = _bad_size(r, h)
    if bad:
        return bad
    cap = MESA_MAX_SLOPE if st == 'mesa' else MOUNT_MAX_SLOPE
    if h > cap * r + 1e-9:
        if st == 'mesa':
            return (
                f'refused: {h:g} m on a {r:g} m radius is a tower, not a mesa — a table mountain is at most '
                f'{cap:g} x its radius; use radius {h / cap:g} or height {cap * r:g}'
            )
        return (
            f'refused: {h:g} m on a {r:g} m radius is a needle — a mountain is at most as tall as its '
            f'radius; use radius {h:g} or height {r:g}'
        )
    if h < MOUNT_MIN_SLOPE * r - 1e-9:
        return (
            f'refused: {h:g} m on a {r:g} m radius is a hill, not a mountain — a mountain is at least '
            f'{MOUNT_MIN_SLOPE:g} x its radius; use add_hill, or height {MOUNT_MIN_SLOPE * r:g} and up'
        )
    rug = max(0.0, min(0.95, _num(ruggedness, 0.45)))
    sd = _num(seed, 1)
    snow, why = resolve_snow(snow_line, h)
    if snow is None:
        return why
    if len(d.objs) + 1 > MAX_OBJECTS:
        return f'refused: the drawing is at the {MAX_OBJECTS} object ceiling'
    cx, cz = cell_centre(*parse_cell(centre))
    cn = cell_name(*parse_cell(centre))
    grp = name or 'mountains'
    fe = round(SCULPT_FEATHER * r, 3)

    # ── v3: a peak and a mesa become sculpts of the one ground ───────────────
    if has_ground(d) and st != 'volcano':
        y = sculpt_y(base_height)
        if st == 'mesa':
            p = {
                'r': round(r, 3),
                'h': round(h, 3),
                'top_r': round(r * 0.75, 3),
                'rug': round(rug, 3),
                'seed': sd,
                'feather': fe,
            }
            kind, what = 'sculpt_mesa', f'flat top {2 * r * 0.75:g} m across inside a {2 * r:g} m flank'
        else:
            p = {'r': round(r, 3), 'h': round(h, 3), 'rug': round(rug, 3), 'seed': sd, 'feather': fe}
            kind, what = 'sculpt_peak', f'a summit {2 * r:g} m across'
        o = d.new(kind, p, cx, cz, y, 0.0, SCULPT_MAT, name=name or f'{st} {cn}', grp=grp)
        return (
            f'drew {st} {o["id"]} on {cn} {SCULPT_WORDS}: {what}, rising {h:g} m out of the land around it'
            f'{" and lifted " + format(y, "g") + " m by base_height" if y else ""}, feathered into it over '
            f'{fe:g} m at the rim — {ground_snow_words(d)}, so snow_line sets nothing here.'
        )

    y = place_height(d, cx, cz, base_height)
    if st == 'volcano':
        p = {
            'r': round(r, 3),
            'h': round(h, 3),
            'crater_r': round(r * 0.2, 3),
            'crater_d': round(h * 0.23, 3),
            'seg': 48,
            'rings': 16,
        }
        kind, what = 'volcano', f'crater {2 * r * 0.2:g} m across and {h * 0.23:.1f} m deep'
    elif st == 'mesa':
        p = {
            'r': round(r, 3),
            'h': round(h, 3),
            'top_r': round(r * 0.75, 3),
            'rug': round(rug, 3),
            'seed': sd,
            'seg': 48,
        }
        kind, what = 'mesa', f'flat grass top {2 * r * 0.75:g} m across, rock cliffs'
    else:
        p = {
            'r': round(r, 3),
            'h': round(h, 3),
            'rug': round(rug, 3),
            'seed': sd,
            'res': _res_for(2 * r),
            'snow': round(snow, 3),
        }
        kind, what = 'mountain', _snow_words(snow, why, h)
    o = d.new(kind, p, cx, cz, y, 0.0, _mat(material), name=name or f'{st} {cn}', grp=grp)
    # a crater is not a sculpt kind yet, so a volcano stays a solid even on a v3 ground
    how = (
        'as a solid on the sculpted ground — a crater is not a sculpt yet, so this cone stands on the '
        'heightfield rather than being cut into it'
        if st == 'volcano' and has_ground(d)
        else SOLID_WORDS
    )
    return (
        f'drew {st} {o["id"]} on {cn}: {2 * r:g} m across the foot, summit at {h:g} m'
        f'{" above " + format(y, "g") + " m of ground" if y else ""} — {what}, {how}'
    )


def t_add_mountain_range(
    d: Drawing,
    a,
    cell_from,
    cell_to,
    height=None,
    peaks=4,
    seed=1,
    snow_line='auto',
    ruggedness=0.45,
    base_height=None,
    material='',
    name='',
):
    n = int(_num(peaks, 4))
    if n < 1 or n > 20:
        return 'refused: a range needs between 1 and 20 peaks'
    xmin, zmin, xmax, zmax = block_bounds(cell_from, cell_to)
    W, D = xmax - xmin, zmax - zmin
    if W > MAX_BLOCK or D > MAX_BLOCK:
        return f'refused: {W:g} x {D:g} m is too big for one range — {MAX_BLOCK:g} m a side is the limit'
    # the record's length always runs along its local X; turn it a quarter when
    # the block is longer in z, exactly as add_slope swaps w and d.
    turn = D > W
    ln, w = (D, W) if turn else (W, D)
    ry = math.pi / 2 if turn else 0.0
    pr = peak_radius(ln, n)
    if height is None or height == '':
        h = round(RANGE_DEF_HEIGHT * pr, 3)
    else:
        h = _num(height, RANGE_DEF_HEIGHT * pr)
        if h <= 0 or h > MAX_H:
            return f'refused: height must be more than 0 and at most {MAX_H:g} m'
        if h > pr + 1e-9:
            return (
                f'refused: {h:g} m over a {ln:g} m block with {n} peaks is a row of needles — each summit '
                f'stands on a {pr:.1f} m radius and can be no taller than that; use height {pr:.1f} or less, '
                f'fewer peaks, or a longer block'
            )
    snow, why = resolve_snow(snow_line, h)
    if snow is None:
        return why
    rug = round(max(0.0, min(0.95, _num(ruggedness, 0.45))), 3)
    sd = _num(seed, 1)
    cx, cz = (xmin + xmax) / 2, (zmin + zmax) / 2
    cf, ct = cell_name(*parse_cell(cell_from)), cell_name(*parse_cell(cell_to))

    # ── v3: a range is a CHAIN OF SUMMITS sculpted into the ground, never one
    # solid block. The summits sit where range_lattice puts them (0.65 x len /
    # peaks apart along the block's long axis) and their heights carry the same
    # +-25 % hash spread, normalised so the tallest is exactly `height`.
    if has_ground(d):
        if len(d.objs) + n > MAX_OBJECTS:
            return f'refused: that is {n} objects past the {MAX_OBJECTS} ceiling'
        y = sculpt_y(base_height)
        c, s = math.cos(ry), math.sin(ry)
        phs = [1 + RANGE_SPREAD * (_hash(m, 0, sd) - 0.5) for m in range(n)]
        top = max(phs) or 1.0
        fe = round(SCULPT_FEATHER * pr, 3)
        ids = []
        for m, ph in enumerate(phs):
            px = -ln / 2 + (m + 0.5) * ln / n  # the summit's offset along local +X
            o = d.new(
                'sculpt_peak',
                {'r': round(pr, 3), 'h': round(h * ph / top, 3), 'rug': rug, 'seed': sd + m, 'feather': fe},
                cx + px * c,
                cz - px * s,
                y,
                0.0,
                SCULPT_MAT,
                name=f'{name or "range"} summit {m + 1}',
                grp=name or 'mountains',
            )
            ids.append(o['id'])
        lo = min(phs) / top
        return (
            f'drew a range of {n} summits {ids[0]}..{ids[-1]} over {cf}..{ct} {SCULPT_WORDS}: '
            f'{ln:g} m of chain, each on a {pr:.1f} m radius, heights varying {RANGE_SPREAD / 2:.0%} by seed '
            f'({h * lo:.1f}-{h:g} m), every one growing out of the land and feathered into it over {fe:g} m — '
            f'{ground_snow_words(d)}, so snow_line sets nothing here.'
        )

    if len(d.objs) + 1 > MAX_OBJECTS:
        return f'refused: the drawing is at the {MAX_OBJECTS} object ceiling'
    y = place_height(d, cx, cz, base_height)
    p = {
        'len': round(ln, 4),
        'w': round(w, 4),
        'h': round(h, 3),
        'peaks': n,
        'rug': rug,
        'seed': sd,
        'res': _res_for(ln),
        'snow': round(snow, 3),
    }
    o = d.new(
        'mountain_range', p, cx, cz, y, ry, _mat(material), name=name or f'range {cf}-{ct}', grp=name or 'mountains'
    )
    return (
        f'drew mountain range {o["id"]} over {cf}..{ct}: {ln:g} m long, {w:g} m deep, '
        f'{n} peaks on a {pr:.1f} m radius each, highest summit {h:g} m'
        f'{" above " + format(y, "g") + " m of ground" if y else ""} — {_snow_words(snow, why, h)}, '
        f'{SOLID_WORDS}'
    )


def t_add_ridge(
    d: Drawing, a, cells, height=15.0, width=20.0, ruggedness=0.3, seed=1, base_height=None, material='', name=''
):
    if not isinstance(cells, (list, tuple)) or len(cells) < 2:
        return 'refused: give a list of at least two cells — one ridge is drawn between each pair'
    h = _num(height, 15.0)
    if h <= 0 or h > MAX_H:
        return f'refused: height must be more than 0 and at most {MAX_H:g} m'
    w = _num(width, 20.0)
    if w <= 0 or w > MAX_BLOCK:
        return f'refused: width must be more than 0 and at most {MAX_BLOCK:g} m'
    if h > RIDGE_MAX_SLOPE * w + 1e-9:
        return (
            f'refused: a {h:g} m crest on a {w:g} m foot is a blade — a ridge is at most {RIDGE_MAX_SLOPE:g} x '
            f'its width; use width {h / RIDGE_MAX_SLOPE:g} or height {RIDGE_MAX_SLOPE * w:g}'
        )
    pts = [cell_centre(*parse_cell(c)) for c in cells]
    need = len(pts) - 1
    if len(d.objs) + need > MAX_OBJECTS:
        return f'refused: that is {need} objects past the {MAX_OBJECTS} ceiling'
    rug = max(0.0, min(0.95, _num(ruggedness, 0.3)))
    sd = _num(seed, 1)
    grp = name or 'ridges'
    # v3: one sculpt_ridge per pair instead of one ridge solid per pair. Same
    # centres, same atan2 turn, same crest — but a term in the ground's own sum.
    sculpted = has_ground(d)
    ids, total = [], 0.0
    for i in range(need):
        (x0, z0), (x1, z1) = pts[i], pts[i + 1]
        L = math.hypot(x1 - x0, z1 - z0)
        if L < 0.5:
            return f'refused: {cells[i]} and {cells[i + 1]} are the same cell — a ridge needs two different cells'
        ry = math.atan2(-(z1 - z0), x1 - x0)
        cx, cz = (x0 + x1) / 2, (z0 + z1) / 2
        if sculpted:
            o = d.new(
                'sculpt_ridge',
                {
                    'len': round(L, 4),
                    'w': round(w, 3),
                    'h': round(h, 3),
                    'rug': round(rug, 3),
                    'seed': sd + i,
                    'feather': round(SCULPT_FEATHER * L / 2, 3),
                },
                cx,
                cz,
                sculpt_y(base_height),
                ry,
                SCULPT_MAT,
                name=f'ridge {i + 1}',
                grp=grp,
            )
        else:
            o = d.new(
                'ridge',
                {
                    'len': round(L, 4),
                    'w': round(w, 3),
                    'h': round(h, 3),
                    'rug': round(rug, 3),
                    'seed': sd + i,
                    'res': max(8, min(96, int(round(L / 2.5)))),
                },
                cx,
                cz,
                place_height(d, cx, cz, base_height),
                ry,
                _mat(material, 'mat_grass'),
                name=f'ridge {i + 1}',
                grp=grp,
            )
        ids.append(o['id'])
        total += L
    if sculpted:
        return (
            f'drew {need} crest(s) {ids[0]}..{ids[-1]} through {", ".join(str(c) for c in cells)} '
            f'{SCULPT_WORDS}: {total:.1f} m of ridge, {h:g} m out of the land, {w:g} m foot to foot, '
            f'feathered into it at both ends — {ground_snow_words(d)}.'
        )
    return (
        f'drew {need} grassy ridge(s) {ids[0]}..{ids[-1]} through {", ".join(str(c) for c in cells)}: '
        f'{total:.1f} m of crest, {h:g} m tall, {w:g} m foot to foot, {SOLID_WORDS}'
    )


def t_add_valley(
    d: Drawing,
    a,
    cell_from,
    cell_to,
    depth=None,
    direction='z',
    profile='v',
    floor_width=20.0,
    base_height=None,
    material='',
    name='',
):
    dr = str(direction or 'z').strip().lower()
    if dr not in ('x', 'z'):
        return "refused: direction must be 'x' or 'z' — the axis the valley RUNS along"
    pf = str(profile or 'v').strip().lower()
    if pf not in ('v', 'u'):
        return "refused: profile must be 'v' (a cleft) or 'u' (a glacial trough)"
    xmin, zmin, xmax, zmax = block_bounds(cell_from, cell_to)
    W, D = xmax - xmin, zmax - zmin
    if W > MAX_BLOCK or D > MAX_BLOCK:
        return f'refused: {W:g} x {D:g} m is too big for one valley — {MAX_BLOCK:g} m a side is the limit'
    # local X is ACROSS the valley, local Z runs ALONG it; ry = 90 deg turns the
    # local +Z to world +X, so 'x' runs the trough east-west.
    across, along = (D, W) if dr == 'x' else (W, D)
    fw = _num(floor_width, 20.0)
    if fw < 0 or fw >= across:
        return f'refused: floor_width must be between 0 and {across:g} m (the valley is {across:g} m across)'
    h = round(VALLEY_DEF_DEPTH * across, 3) if depth is None or depth == '' else _num(depth, 30.0)
    if h <= 0 or h > MAX_H:
        return f'refused: depth must be more than 0 and at most {MAX_H:g} m'
    if h > VALLEY_MAX_DEPTH * across + 1e-9:
        return (
            f'refused: {h:g} m deep and only {across:g} m across is a canyon — a valley is at most '
            f'{VALLEY_MAX_DEPTH:g} x its width deep; use depth {VALLEY_MAX_DEPTH * across:g} or a wider block'
        )
    if len(d.objs) + 1 > MAX_OBJECTS:
        return f'refused: the drawing is at the {MAX_OBJECTS} object ceiling'
    cx, cz = (xmin + xmax) / 2, (zmin + zmax) / 2
    cf, ct = cell_name(*parse_cell(cell_from)), cell_name(*parse_cell(cell_to))

    # ── v3: a real hollow, not a raised plinth. sculpt_cut runs along its LOCAL
    # +X (the solid `valley` kind runs along its local +Z), so the quarter turn
    # is the OTHER way round: 'z' turns the record, 'x' leaves it.
    if has_ground(d):
        if len(d.objs) + 1 > MAX_OBJECTS:
            return f'refused: the drawing is at the {MAX_OBJECTS} object ceiling'
        fe = round(SCULPT_FEATHER * along / 2, 3)
        o = d.new(
            'sculpt_cut',
            {
                'len': round(along, 4),
                'w': round(across, 4),
                'depth': round(h, 3),
                'floor_w': round(fw, 3),
                'profile': 1 if pf == 'u' else 0,
                'feather': fe,
            },
            cx,
            cz,
            sculpt_y(base_height),
            0.0 if dr == 'x' else math.pi / 2,
            SCULPT_MAT,
            name=name or f'valley {cf}-{ct}',
            grp=name or 'valleys',
        )
        return (
            f'cut valley {o["id"]} over {cf}..{ct} {SCULPT_WORDS}: runs {along:g} m along {dr}, '
            f'{across:g} m across, {h:g} m DOWN into the land with a floor {fw:g} m wide '
            f'({"U" if pf == "u" else "V"} profile), its walls following the ground it cuts through and '
            f'feathered into it over {fe:g} m at each end — run a river along that floor'
        )

    y = place_height(d, cx, cz, base_height)
    ry = math.pi / 2 if dr == 'x' else 0.0
    o = d.new(
        'valley',
        {
            'w': round(across, 4),
            'd': round(along, 4),
            'h': round(h, 3),
            'floor_w': round(fw, 3),
            'profile': 1 if pf == 'u' else 0,
            'res': _res_for(max(across, along)),
        },
        cx,
        cz,
        y,
        ry,
        _mat(material, 'mat_grass'),
        name=name or f'valley {cf}-{ct}',
        grp=name or 'valleys',
    )
    return (
        f'cut valley {o["id"]} over {cf}..{ct}: runs {along:g} m along {dr}, {across:g} m across, '
        f'grass sides rising {h:g} m, a soil floor {fw:g} m wide ({"U" if pf == "u" else "V"} profile), '
        f'{SOLID_WORDS} — run a river along that floor'
    )
