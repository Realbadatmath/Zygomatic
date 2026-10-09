# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""site_landscape.site_tools — the seven site & landscape tools.

Moved verbatim out of the 1,180-line site_landscape.py; original lines
444-968.
"""

from __future__ import annotations

import math

from zyg_workflows.arch_assistant import (
    Drawing,
    MAX_OBJECTS,
    _num,
    block_bounds,
    cell_centre,
    cell_name,
    cell_of,
    ground_plane,
    ground_tilt,
    parse_cell,
    place_height,
)

from zyg_workflows.arch_assistant_ext.site_landscape.constants import (
    BED_KINDS,
    CROWN_FIT,
    FENCE_KINDS,
    FENCE_PIECE,
    FURNITURE_KINDS,
    FURNITURE_RANGE,
    KINDS,
    LAMP_DEFAULT_H,
    PARK_SLOPE,
    PARK_SPREAD,
    REAL_LAMPS,
    REAL_TREES,
    TILE_SPREAD,
    TREE_DEFAULT_H,
    TREE_KINDS,
    TREE_RANGE,
    _assets,
    _cells,
    _mat,
    _real_pick,
    _rnd,
    _tree_p,
)

from zyg_workflows.arch_assistant_ext.site_landscape.ground_seam import (
    _canopy_refusal,
    _carriageway_refusal,
    _fall,
    _leg_pieces,
    _local_slopes,
    _soffit_cap,
    _tile_block,
)


# ── tools ────────────────────────────────────────────────────────────────────
def t_plant_trees(
    d: Drawing,
    a,
    cell_from,
    cell_to,
    spacing=6.0,
    count=None,
    kind='tree_deciduous',
    height=None,
    jitter=0.3,
    seed=1,
    material='mat_grass',
    base_height=None,
    name='',
    model='real',
):
    kind = str(kind or 'tree_deciduous')
    model = str(model or 'real').lower()
    if model not in ('real', 'parametric'):
        return 'refused: model must be "real" (a life-size pack model) or "parametric" (sphere-on-a-trunk placeholder)'
    if kind not in TREE_KINDS:
        return 'refused: kind must be tree_deciduous, tree_conifer, tree_palm or tree'
    h = _num(height, TREE_DEFAULT_H[kind])
    lo, hi = TREE_RANGE[kind]
    if h < lo - 1e-9 or h > hi + 1e-9:  # R7
        return (
            f'refused: a real {kind.replace("_", " ")} is {lo:g}-{hi:g} m tall, not {h:g} m — '
            'a tree is an absolute size, it never scales with the block'
        )
    xmin, zmin, xmax, zmax = block_bounds(cell_from, cell_to)
    W, D = xmax - xmin, zmax - zmin
    sp = _num(spacing, 6.0)
    if sp < 0.5:
        return 'refused: spacing must be at least 0.5 m'
    jit = max(0.0, _num(jitter, 0.3))
    sd = int(_num(seed, 1))
    grp = name or f'trees {cell_name(*parse_cell(cell_from))}-{cell_name(*parse_cell(cell_to))}'
    p = _tree_p(kind, h)
    mat = _mat(material, 'mat_grass')
    spots = []
    n_want = None if count is None else max(1, int(_num(count, 1)))
    if n_want is not None:
        for i in range(n_want):
            spots.append((xmin + _rnd(sd, i, 1) * W, zmin + _rnd(sd, i, 2) * D))
    else:
        nx = max(1, int(math.floor(W / sp + 1e-9)) + 1)
        nz = max(1, int(math.floor(D / sp + 1e-9)) + 1)
        x0 = xmin + (W - (nx - 1) * sp) / 2
        z0 = zmin + (D - (nz - 1) * sp) / 2
        for j in range(nz):
            for i in range(nx):
                k = j * nx + i
                spots.append(
                    (x0 + i * sp + (_rnd(sd, k, 1) * 2 - 1) * jit, z0 + j * sp + (_rnd(sd, k, 2) * 2 - 1) * jit)
                )
    if len(d.objs) + len(spots) > MAX_OBJECTS:
        return f'refused: that is {len(spots)} trees and the drawing may hold {MAX_OBJECTS} objects in total'
    # crowding (design rule): crowns that overlap read as one green blob. A crown
    # is r_can (deciduous/plain), r (conifer) or 0.34 h (palm fronds) in radius;
    # `count` trees need room for count x (CROWN_FIT x crown diameter)^2 and a
    # scatter that keeps them that far apart. Refuse with the block size that fits.
    crown_r = _num(p.get('r_can'), _num(p.get('r'), h * 0.34 if kind == 'tree_palm' else 3.0))
    min_gap = CROWN_FIT * 2 * crown_r
    if n_want is not None and n_want > 1:
        need_area = n_want * min_gap * min_gap
        if W * D < need_area * 0.9:
            side = math.ceil(math.sqrt(need_area))
            return (
                f'refused: {n_want} {kind.replace("_", " ")}s of {h:g} m have {2 * crown_r:.1f} m crowns and need '
                f'about {min_gap:.1f} m between trunks — the block {cell_name(*parse_cell(cell_from))}..'
                f'{cell_name(*parse_cell(cell_to))} is only {W:g} x {D:g} m. Give a block of at least '
                f'{side} x {side} cells ({need_area:.0f} m2), plant fewer trees, or use a row: '
                f'place_assets_along(cells, "tree", spacing={math.ceil(min_gap)})'
            )
        # re-scatter with a minimum distance (seeded; same seed = same positions)
        spots = []
        tries = 0
        while len(spots) < n_want and tries < 400:
            x = xmin + _rnd(sd, tries, 1) * W
            z = zmin + _rnd(sd, tries, 2) * D
            tries += 1
            if all(math.hypot(x - sx, z - sz) >= min_gap for sx, sz in spots):
                spots.append((x, z))
        if len(spots) < n_want:
            # the block has the area but the scatter could not find the packing:
            # a jittered grid at the spacing the area affords (still seeded)
            sgrid = math.sqrt(W * D / n_want)
            nx = max(1, int(math.ceil(W / sgrid)))
            nz = max(1, int(math.ceil(n_want / nx)))
            gx, gz = W / nx, D / nz
            spots = []
            for j in range(nz):
                for i in range(nx):
                    if len(spots) >= n_want:
                        break
                    k = j * nx + i
                    spots.append(
                        (
                            xmin + (i + 0.5) * gx + (_rnd(sd, k, 3) - 0.5) * 0.3 * gx,
                            zmin + (j + 0.5) * gz + (_rnd(sd, k, 4) - 0.5) * 0.3 * gz,
                        )
                    )
            min_gap = min(min_gap, 0.7 * min(gx, gz))
    elif n_want is None and sp < min_gap * 0.75:
        return (
            f'refused: {kind.replace("_", " ")}s of {h:g} m have {2 * crown_r:.1f} m crowns; spacing {sp:g} m '
            f'merges them into one blob — use spacing >= {min_gap:.0f}'
        )
    # the carriageway: a tree standing in the road is a tree in the road
    err = _carriageway_refusal(d, [cell_of(x, z) for x, z in spots], spots, 'tree')
    if err:
        return err
    # real model or placeholder
    row, scale = (None, 1.0)
    if model == 'real':
        row, scale = _real_pick(REAL_TREES.get(kind, []), h)
    ids, ys = [], []
    for i, (x, z) in enumerate(spots):
        y = place_height(d, x, z, base_height)  # R5, exact per tree
        ys.append(y)
        if row is not None:
            AS = _assets()
            o = d.new(
                'asset',
                AS._params(row),
                x,
                z,
                y,
                _rnd(sd, i, 7) * 2 * math.pi,
                None,
                name=f'{row["n"]} {i + 1}',
                grp=grp,
            )
            o['s'] = scale
        else:
            o = d.new(kind, dict(p), x, z, y, 0.0, mat, name=f'{kind.replace("_", " ")} {i + 1}', grp=grp)
        ids.append(o['id'])
    what = (
        f'{row["n"]} ({row["id"]}, real model, scale {scale:g} = {row["size"][1] * scale:.1f} m tall)'
        if row is not None
        else f'{kind} placeholder{"" if model == "parametric" else " (no life-size " + kind.replace("_", " ") + " in the packs)"}'
    )
    return (
        f'planted {len(ids)} x {what} {ids[0]}..{ids[-1]} in group "{grp}" over cells '
        f'{cell_name(*parse_cell(cell_from))}..{cell_name(*parse_cell(cell_to))} '
        f'({W:g} x {D:g} m), asked {h:g} m, seed {sd}, trunks >= {min_gap:.1f} m apart, '
        f'each on the ground under it (y {min(ys):.2f}..{max(ys):.2f} m)'
    )


def t_add_fence(d: Drawing, a, cells, kind='fence', height=1.2, material='', base_height=None, name=''):
    kind = str(kind or 'fence')
    if kind not in FENCE_KINDS:
        return 'refused: kind must be fence or hedge'
    pts = _cells(cells, 2)
    h = max(0.2, _num(height, 1.2))
    if kind == 'hedge' and h > 6.0:
        return 'refused: a clipped hedge is 0.4-6 m tall — taller than that is a tree line'
    grp = name or f'{kind} {cells[0]}-{cells[-1]}'
    mat = _mat(material, 'mat_timber' if kind == 'fence' else 'mat_grass')
    legs = []
    for i in range(len(pts) - 1):
        A, B = pts[i], pts[i + 1]
        if math.hypot(B[0] - A[0], B[1] - A[1]) < 0.5:
            return f'refused: {cells[i]} and {cells[i + 1]} are the same cell — a segment needs two different cells'
        legs.append(_leg_pieces(d, A, B, base_height, split=True))
    n = sum(len(g) for g in legs)
    if len(d.objs) + n > MAX_OBJECTS:
        return f'refused: that is {n} segments past the {MAX_OBJECTS} ceiling'
    ids, total, ys, split = [], 0.0, [], 0
    for g in legs:
        if len(g) > 1:
            split += 1
        for pc in g:
            L = pc['len']
            total += L
            if kind == 'fence':
                p = {'len': round(L, 3), 'h': h, 'posts': max(2, int(L / 2.5) + 1), 'rails': 3, 't': 0.04}
            else:
                p = {'len': round(L, 3), 'h': h, 'w': 0.6}
            o = d.new(kind, p, pc['cx'], pc['cz'], pc['y'], pc['ry'], mat, name=f'{kind} {len(ids) + 1}', grp=grp)
            o['rz'] = round(pc['rz'], 6)  # R4 — it runs downhill
            ids.append(o['id'])
            ys.append(pc['y'])
    return (
        f'drew {len(ids)} {kind} segment(s) {ids[0]}..{ids[-1]} through {", ".join(str(c) for c in cells)}: '
        f'{total:.1f} m in total, {h:g} m high, group "{grp}"'
        + _fall(ys)
        + (f' ({split} steep leg(s) cut into {FENCE_PIECE:g} m pieces)' if split else '')
    )


def t_add_parking(
    d: Drawing,
    a,
    cell_from,
    cell_to,
    bay_w=2.5,
    bay_d=5.0,
    direction='x',
    material='mat_asphalt',
    base_height=None,
    name='',
):
    direction = str(direction or 'x').lower()
    if direction not in ('x', 'z'):
        return 'refused: direction must be "x" (bays side by side along x) or "z"'
    bw, bd = _num(bay_w, 2.5), _num(bay_d, 5.0)
    if bw < 1.5 or bd < 2.5:
        return 'refused: a bay is at least 1.5 m wide and 2.5 m deep'
    xmin, zmin, xmax, zmax = block_bounds(cell_from, cell_to)
    W, D = xmax - xmin, zmax - zmin
    cf, ct = cell_name(*parse_cell(cell_from)), cell_name(*parse_cell(cell_to))
    py, pgx, pgz, spread = (
        (_num(base_height, 0.0), 0.0, 0.0, 0.0)
        if base_height is not None
        else ground_plane(d, (xmin + xmax) / 2, (zmin + zmax) / 2, W, D, 0.0)
    )
    slope = math.hypot(pgx, pgz)
    if spread > PARK_SPREAD or slope > PARK_SLOPE:  # R2 refusal
        return (
            f'refused: a car park needs near-level ground: flatten_pad first — the ground over {cf}..{ct} '
            f'is {spread:.2f} m off a plane and falls {slope * 100:.1f}% '
            f'(a bay wants under {PARK_SPREAD:g} m and under {PARK_SLOPE * 100:g}%)'
        )
    sx, sz = (bw, bd) if direction == 'x' else (bd, bw)
    cols = int(W / sx + 1e-9)
    rows = int(D / sz + 1e-9)
    if cols < 1 or rows < 1:
        return f'refused: no {bw:g} x {bd:g} m bay fits in {W:g} x {D:g} m — give a bigger block or smaller bays'
    n = cols * rows
    if len(d.objs) + n > MAX_OBJECTS:
        return f'refused: that is {n} bays past the {MAX_OBJECTS} ceiling'
    grp = name or f'parking {cf}-{ct}'
    ry = 0.0 if direction == 'x' else math.pi / 2
    gx, gz = _local_slopes(pgx, pgz, ry)  # R2 — the bay tilts, upright record
    bp = {'gx': round(gx, 4), 'gz': round(gz, 4)}
    ids, ys = [], []
    for j in range(rows):
        for i in range(cols):
            bx = xmin + (i + 0.5) * sx
            bz = zmin + (j + 0.5) * sz
            y = place_height(d, bx, bz, base_height)
            ys.append(y)
            o = d.new(
                'parking_bay',
                dict({'w': round(bw, 3), 'd': round(bd, 3), 't': 0.02}, **bp),
                bx,
                bz,
                y,
                ry,
                _mat(material, 'mat_asphalt'),
                name=f'bay {j * cols + i + 1}',
                grp=grp,
            )
            ids.append(o['id'])
    return (
        f'laid {n} parking bays {ids[0]}..{ids[-1]} ({cols} x {rows}, {bw:g} x {bd:g} m each, facing {direction}) '
        f'in group "{grp}" over {W:g} x {D:g} m, on ground at y {min(ys):.2f}..{max(ys):.2f} m'
        + (f', each bay tilted {slope * 100:.1f}% with the ground' if slope > 0.002 else '')
    )


def t_add_road(d: Drawing, a, cells, width=6.0, material='mat_asphalt', base_height=None, name=''):
    pts = _cells(cells, 2)
    w = _num(width, 6.0)
    if w < 1 or w > 60:
        return 'refused: road width must be between 1 and 60 m'
    if len(d.objs) + len(pts) - 1 > MAX_OBJECTS:
        return f'refused: that is {len(pts) - 1} road pieces past the {MAX_OBJECTS} ceiling'
    grp = name or f'road {cells[0]}-{cells[-1]}'
    ids, total, ys = [], 0.0, []
    for i in range(len(pts) - 1):
        A, B = pts[i], pts[i + 1]
        if math.hypot(B[0] - A[0], B[1] - A[1]) < 0.5:
            return f'refused: {cells[i]} and {cells[i + 1]} are the same cell'
        pc = _leg_pieces(d, A, B, base_height)[0]  # R4 — one piece per leg
        total += pc['len']
        o = d.new(
            'road',
            {'len': round(pc['len'], 3), 'w': round(w, 3), 't': 0.08},
            pc['cx'],
            pc['cz'],
            pc['y'],
            pc['ry'],
            _mat(material, 'mat_asphalt'),
            name=f'road {i + 1}',
            grp=grp,
        )
        o['rz'] = round(pc['rz'], 6)
        ids.append(o['id'])
        ys.append(pc['y'])
    return (
        f'laid {len(ids)} road piece(s) {ids[0]}..{ids[-1]} through {", ".join(str(c) for c in cells)}: '
        f'{total:.1f} m of {w:g} m carriageway, group "{grp}"' + _fall(ys)
    )


def t_add_curved_road(
    d: Drawing,
    a,
    centre,
    radius=10.0,
    start_deg=0.0,
    end_deg=90.0,
    width=6.0,
    material='mat_asphalt',
    base_height=None,
    name='',
):
    cx, cz = cell_centre(*parse_cell(centre))
    r = _num(radius, 10.0)
    w = _num(width, 6.0)
    if r < 1 or r > 300:
        return 'refused: radius must be between 1 and 300 m'
    if w < 1 or w > 60:
        return 'refused: road width must be between 1 and 60 m'
    if w >= 2 * r:
        return f'refused: a {w:g} m carriageway does not fit on a {r:g} m radius — the inner edge would be inside out'
    a0, a1 = _num(start_deg, 0.0), _num(end_deg, 90.0)
    if abs(a1 - a0) < 1:
        return 'refused: the arc needs at least 1 degree between start_deg and end_deg'
    ro = r + w / 2
    if base_height is None:
        y, glx, glz, spread = ground_plane(d, cx, cz, 2 * ro, 2 * ro, 0.0)
    else:
        y, glx, glz, spread = _num(base_height, 0.0), 0.0, 0.0, 0.0
    rx, rz = ground_tilt(glx, glz)  # the arc is a thin slab: lean it
    o = d.new(
        'road_curved',
        {
            'r': round(r, 3),
            'a0': round(a0, 2),
            'a1': round(a1, 2),
            'w': round(w, 3),
            't': 0.08,
            'seg': max(8, int(abs(a1 - a0) / 6) + 4),
        },
        cx,
        cz,
        round(y, 4),
        0.0,
        _mat(material, 'mat_asphalt'),
        name=name or 'curved road',
        grp=name,
    )
    o['rx'], o['rz'] = round(rx, 6), round(rz, 6)
    slope = math.hypot(glx, glz)
    return (
        f'curved road {o["id"]} around {cell_name(*parse_cell(centre))}: radius {r:g} m, '
        f'{a0:g}° to {a1:g}°, {w:g} m wide, on the ground at y {y:.2f} m'
        + (f', laid over a {slope * 100:.1f}% fall' if slope > 0.002 else '')
        + (
            f' (the ground there is {spread:.1f} m off a plane — flatten_pad would be kinder)'
            if spread > TILE_SPREAD
            else ''
        )
    )


def t_add_street_furniture(
    d: Drawing,
    a,
    cells,
    kind='lamp_post',
    rotation_deg=0.0,
    height=None,
    material='',
    base_height=None,
    name='',
    model='real',
):
    kind = str(kind or 'lamp_post')
    if kind not in FURNITURE_KINDS:
        return 'refused: kind must be lamp_post, bench or bin'
    model = str(model or 'real').lower()
    pts = _cells(cells, 1)
    names = [str(c) for c in cells]
    if len(d.objs) + len(pts) > MAX_OBJECTS:
        return f'refused: that is {len(pts)} items past the {MAX_OBJECTS} ceiling'
    ry = math.radians(_num(rotation_deg, 0.0))
    rng = FURNITURE_RANGE.get(kind)
    hv, clamped = None, ''
    if kind == 'lamp_post':
        # the site defaults: clear of the canopy, clear of the drive, under the soffit
        hv = _num(height, LAMP_DEFAULT_H) if height is not None else LAMP_DEFAULT_H
        if rng and (hv < rng[0] - 1e-9 or hv > rng[1] + 1e-9):  # R7
            return (
                f'refused: a real {kind.replace("_", " ")} is {rng[0]:g}-{rng[1]:g} m tall, not {hv:g} m — '
                'street furniture is an absolute size'
            )
        err = _canopy_refusal(d, names, pts) or _carriageway_refusal(d, names, pts, 'lamp post')
        if err:
            return err
        cap, soffit = _soffit_cap(d, pts)
        if cap is not None and cap < hv - 1e-9:
            if rng and cap < rng[0] - 1e-9:
                return (
                    f'refused: the canopy soffit here is {soffit:g} m, so a lamp under it would be '
                    f'{cap:g} m and a real {kind.replace("_", " ")} is {rng[0]:g}-{rng[1]:g} m — '
                    'stand it clear of the canopy instead'
                )
            clamped = f', lamp height {hv:g} m clamped to {cap:g} m: the canopy soffit is {soffit:g} m'
            hv = cap
    elif height is not None:
        hv = _num(height, KINDS[kind]['h'])
        if rng and (hv < rng[0] - 1e-9 or hv > rng[1] + 1e-9):  # R7
            return (
                f'refused: a real {kind.replace("_", " ")} is {rng[0]:g}-{rng[1]:g} m tall, not {hv:g} m — '
                'street furniture is an absolute size'
            )
    if kind == 'lamp_post' and model == 'real':
        row, scale = _real_pick(REAL_LAMPS, hv)
        if row is not None:
            AS = _assets()
            grp = name or 'lamp posts'
            ids, ys = [], []
            for i, (x, z) in enumerate(pts):
                y = place_height(d, x, z, base_height)
                ys.append(y)
                o = d.new('asset', AS._params(row), x, z, y, ry, None, name=f'lamp post {i + 1}', grp=grp)
                o['s'] = scale
                ids.append(o['id'])
            return (
                f'placed {len(ids)} real lamp posts ({row["id"]}, {row["size"][1] * scale:.1f} m) '
                f'{ids[0]}..{ids[-1]} on {", ".join(names)}, group "{grp}", '
                f'on the ground at y {min(ys):.2f}..{max(ys):.2f} m' + clamped
            )
    grp = name or f'{kind}s'
    p = dict(KINDS[kind])
    if hv is not None:
        p['h'] = round(max(0.2, hv), 3)
    mat = _mat(material, 'mat_timber' if kind == 'bench' else 'mat_steel')
    ids, ys = [], []
    for i, (x, z) in enumerate(pts):
        y = place_height(d, x, z, base_height)  # R5
        ys.append(y)
        o = d.new(kind, dict(p), x, z, y, ry, mat, name=f'{kind.replace("_", " ")} {i + 1}', grp=grp)
        ids.append(o['id'])
    return (
        f'placed {len(ids)} {kind} {ids[0]}..{ids[-1]} on {", ".join(names)}'
        + (f', turned {_num(rotation_deg, 0):g}°' if _num(rotation_deg, 0) else '')
        + f', group "{grp}", on the ground at y {min(ys):.2f}..{max(ys):.2f} m'
        + clamped
    )


def t_add_garden_bed(d: Drawing, a, cell_from, cell_to, kind='flowerbed', material='', base_height=None, name=''):
    kind = str(kind or 'flowerbed')
    if kind not in BED_KINDS:
        return 'refused: kind must be flowerbed, hedge or shrubs'
    xmin, zmin, xmax, zmax = block_bounds(cell_from, cell_to)
    W, D = xmax - xmin, zmax - zmin
    cx, cz = (xmin + xmax) / 2, (zmin + zmax) / 2
    grp = name or f'garden {cell_name(*parse_cell(cell_from))}-{cell_name(*parse_cell(cell_to))}'
    mat = _mat(material, 'mat_grass')
    if kind == 'flowerbed':
        tiles = _tile_block(d, xmin, zmin, xmax, zmax, base_height)  # R2
        if len(d.objs) + len(tiles) > MAX_OBJECTS:
            return f'refused: that is {len(tiles)} bed tiles past the {MAX_OBJECTS} ceiling'
        ids = []
        for i, (tx, tz, tw, td, ty, gx, gz) in enumerate(tiles):
            o = d.new(
                'flowerbed',
                {'w': round(tw, 3), 'd': round(td, 3), 't': 0.15, 'gx': gx, 'gz': gz},
                tx,
                tz,
                ty,
                0.0,
                mat,
                name='flower bed' if len(tiles) == 1 else f'flower bed {i + 1}',
                grp=grp,
            )
            ids.append(o['id'])
        gx, gz = tiles[0][5], tiles[0][6]
        return (
            f'flower bed {ids[0]}'
            + (f'..{ids[-1]} in {len(tiles)} tiles over the ground' if len(tiles) > 1 else '')
            + f' {W:g} x {D:g} m over {cell_from}..{cell_to}, group "{grp}", '
            f'lying on the ground at y {tiles[0][4]:.2f} m'
            + (f' and tilted with it (gx {gx:g}, gz {gz:g})' if abs(gx) > 0.002 or abs(gz) > 0.002 else '')
        )
    if kind == 'hedge':
        along_x = W >= D
        L = W if along_x else D
        A = (cx - L / 2, cz) if along_x else (cx, cz - L / 2)
        B = (cx + L / 2, cz) if along_x else (cx, cz + L / 2)
        pc = _leg_pieces(d, A, B, base_height)[0]  # R4
        o = d.new(
            'hedge',
            {'len': round(L, 3), 'h': 1.2, 'w': 0.6},
            pc['cx'],
            pc['cz'],
            pc['y'],
            0.0 if along_x else math.pi / 2,
            mat,
            name='hedge',
            grp=grp,
        )
        o['rz'] = round(pc['rz'], 6)
        return (
            f'hedge {o["id"]} {L:g} m long over {cell_from}..{cell_to}, group "{grp}", '
            f'on the ground at y {pc["y"]:.2f} m' + _fall([pc['y0'], pc['y1']])
        )
    sp = 1.5
    nx, nz = max(1, int(W / sp + 1e-9)), max(1, int(D / sp + 1e-9))
    n = nx * nz
    if len(d.objs) + n > MAX_OBJECTS:
        return f'refused: that is {n} shrubs past the {MAX_OBJECTS} ceiling'
    x0 = xmin + (W - (nx - 1) * sp) / 2
    z0 = zmin + (D - (nz - 1) * sp) / 2
    ids, ys = [], []
    for j in range(nz):
        for i in range(nx):
            x, z = x0 + i * sp, z0 + j * sp
            y = place_height(d, x, z, base_height)  # R5 per shrub: exact, and upright
            ys.append(y)
            o = d.new('shrub', {'r': 0.6, 'h': 0.8}, x, z, y, 0.0, mat, name=f'shrub {j * nx + i + 1}', grp=grp)
            ids.append(o['id'])
    return (
        f'planted {n} shrubs {ids[0]}..{ids[-1]} on a {sp:g} m grid ({nx} x {nz}) over '
        f'{cell_from}..{cell_to}, group "{grp}", each standing upright on the ground '
        f'(y {min(ys):.2f}..{max(ys):.2f} m)'
    )
