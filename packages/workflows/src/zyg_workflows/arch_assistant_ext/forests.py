# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""forests — woods, tree lines, orchards and undergrowth, each as ONE record.

site_landscape.plant_trees makes one record PER tree. That is right for the
half dozen trees a user will drag around by hand, and hopeless for a wood: a
100 x 100 m forest at a realistic density is 400 trees, which is 5 % of
MAX_OBJECTS (8000) spent on scenery and 400 more nodes for the tab to draw.
Everything here bakes hundreds of trees into a single record whose geometry is
rebuilt from the parameters in all three engines.

THE SCATTER IS A CONTRACT. _hash() is the same arithmetic as hash() in
arch_ext/forests.js, as value_noise()'s hash in terrain.py, and as the copy in
arch_blender_ext/forests.py; forest_count / forest_spots / tree_line_spots /
orchard_spots / undergrowth_spots are mirrored line for line in the JS and the
Blender builder. tests_arch_ext/test_forests.py evaluates the copy here and
asserts the tab's triangle count and bounding box agree tree for tree.

THE GROUND DRAPES, THE TREES DO NOT LEAN (2026-09-07). base_height now defaults
to None, which means "the ground under it": every tool asks ground_plane() for
the least-squares plane under its footprint and puts that plane's centre height
in the record's y and its LOCAL slopes in p['gx'] / p['gz']. The geometry lifts
each tree's BASE to gx*lx + gz*lz and keeps the trunk VERTICAL — the record is
never tilted with rx/rz, because tilting it would lean a whole wood downhill.
When the ground under the block is not planar (spread > 1 m: a hill), the tool
TILES the block into sub-records of at most 25 m a side, each with its own y and
its own gx/gz, all in one group, and says so in its reply.

REAL SIZES (R7) are absolute, never scaled with the block: deciduous 6-20 m,
conifer 8-25, poplar 15-25, fruit 3-5, shrubs 0.4-2 m tall. plant_forest's
`height` is the MEAN of the wood; every tree is 0.7-1.3 of it.
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
    MAX_OBJECTS,
    _num,
    ground_height,
    ground_plane,
    place_height,
    EXT_MODULES,
)

KINDS = {
    'forest': {
        'w': 100,
        'd': 100,
        'density': 0.04,
        'mix': 0.5,
        'h': 14,
        'seed': 1,
        'jitter': 0.45,
        'res': 0,
        'gx': 0,
        'gz': 0,
    },
    'tree_line': {'len': 60, 'spacing': 6, 'kind': 0, 'h': 10, 'jitter': 0.2, 'seed': 1, 'gx': 0, 'gz': 0},
    'orchard': {'w': 40, 'd': 30, 'spacing': 5, 'h': 4, 'gx': 0, 'gz': 0},
    'undergrowth': {'w': 40, 'd': 40, 'count': 60, 'seed': 1, 'r': 0.8, 'gx': 0, 'gz': 0},
}
OPENINGS: list = []

PROMPT = (
    'Forests: plant_forest(cell_from, cell_to, density, mix, height, seed, base_height) draws a whole wood (bos) as '
    'ONE object holding hundreds of trees — density is trees per m2 (0.04 = one every 5 m, a dense wood; 0.01 = '
    'parkland), mix is conifer, deciduous or mixed, height is the MEAN tree (each is 0.7-1.3 of it), and it reports '
    'the count and the spacing; past 3000 trees it refuses: split the block or lower the density. Use plant_trees '
    '(site) only for a few trees the user will move. plant_tree_line(cells, spacing, '
    'kind=deciduous|conifer|poplar, height) runs a row between each pair of cells — poplars along a canal '
    '(bomenrij); plant_orchard(cell_from, cell_to, spacing, height) grids fruit trees (boomgaard); '
    'add_undergrowth(cell_from, cell_to, count, bush_radius) scatters shrubs (onderbegroeiing). Real sizes, refused '
    'outside: deciduous 6-20 m, conifer 8-25, poplar 15-25, fruit 3-5, shrub 0.4-2 m tall. base_height is None by '
    'default: a forest drapes over the ground under it and tiles over a hill, each trunk vertical on its own patch '
    'of slope; pass base_height only to override the ground.'
)

# ── geometry constants (the JS and Blender copies use the same numbers) ──────
FOREST_MAX = 3000  # trees in one forest record
LINE_MAX = 400  # trees in one tree_line record
SCATTER_MAX = 2000  # bushes in one undergrowth record
TRUNK_SEG, CONE_SEG = 6, 8
CROWN_USEG, CROWN_VSEG = 8, 4
ORCHARD_RC = 1.6

TRIS_TRUNK = 3 * TRUNK_SEG  # 18
TRIS_CONE = 2 * CONE_SEG  # 16
TRIS_CROWN = CROWN_USEG * (2 + 2 * (CROWN_VSEG - 2))  # 48
DECIDUOUS, CONIFER, POPLAR, SHRUB = 0, 1, 2, 3
TREE_TRIS = {
    DECIDUOUS: TRIS_TRUNK + TRIS_CROWN,  # 66
    CONIFER: TRIS_TRUNK + TRIS_CONE,  # 34
    POPLAR: TRIS_TRUNK + TRIS_CONE,  # 34
    SHRUB: TRIS_CROWN,
}  # 48
CROWN_F = {DECIDUOUS: 0.36, CONIFER: 0.25, POPLAR: 0.12}
LINE_KINDS = {'deciduous': DECIDUOUS, 'conifer': CONIFER, 'poplar': POPLAR}
MIXES = {'mixed': 0.5, 'conifer': 1.0, 'deciduous': 0.0}

# ── R7: the real heights of real trees, in metres. Absolute — never scaled with
# the block. The tool refuses outside them and quotes the range it refused with.
TREE_H = {DECIDUOUS: (6.0, 20.0), CONIFER: (8.0, 25.0), POPLAR: (15.0, 25.0)}
TREE_NAME = {DECIDUOUS: 'a deciduous tree', CONIFER: 'a conifer', POPLAR: 'a poplar'}
# a MIXED wood must be a plausible mean for both of its species, so the two ranges overlap
MIX_H = {
    'deciduous': TREE_H[DECIDUOUS],
    'conifer': TREE_H[CONIFER],
    'mixed': (max(TREE_H[DECIDUOUS][0], TREE_H[CONIFER][0]), min(TREE_H[DECIDUOUS][1], TREE_H[CONIFER][1])),
}
FRUIT_H = (3.0, 5.0)  # an orchard tree
SHRUB_H = (0.4, 2.0)  # undergrowth; a bush is 1.2 x its radius tall
SPREAD_LO, SPREAD_HI = 0.7, 1.3  # plant_forest's `height` is the MEAN of this spread

# ── R2: draping and tiling ───────────────────────────────────────────────────
TILE_SPREAD = 1.0  # m of non-planarity a single record may carry
TILE_M = 25.0  # first tile size when the ground is not planar
TILE_MAX = 64  # the cap on records one tool call may make


def crown_radius(kind_code: int, h: float, cf: float = 1.0) -> float:
    """Half the horizontal spread of one tree, in metres. cf is the per-tree crown
    factor (0.8-1.2 out of the hash) that keeps the canopy from being a lawn of
    identical balls; the trunk and the tree's total height do NOT change with it."""
    return CROWN_F[kind_code] * float(h) * float(cf)


def _clamp(v, lo, hi):
    return lo if v < lo else (hi if v > hi else v)


# ── the shared scatter ───────────────────────────────────────────────────────
def _hash(ix: float, iy: float, seed: float) -> float:
    v = math.sin(ix * 127.1 + iy * 311.7 + seed * 74.7) * 43758.5453
    return v - math.floor(v)


def forest_spacing(density: float) -> float:
    return math.sqrt(1.0 / _clamp(float(density), 0.0005, 4.0))


def forest_count(w: float, d: float, density: float) -> int:
    """round(w * d * density), capped at FOREST_MAX — the trees a forest holds."""
    w, d = _clamp(float(w), 1.0, 600.0), _clamp(float(d), 1.0, 600.0)
    density = _clamp(float(density), 0.0005, 4.0)
    return max(1, min(FOREST_MAX, int(math.floor(w * d * density + 0.5))))


def forest_grid(w: float, d: float, density: float) -> tuple:
    """(n, spacing, nx, nz) — n trees on an nx x nz grid at `spacing` metres."""
    w, d = _clamp(float(w), 1.0, 600.0), _clamp(float(d), 1.0, 600.0)
    s = forest_spacing(density)
    n = forest_count(w, d, density)
    nx = max(1, int(math.floor(w / s + 0.5)))
    return n, s, nx, max(1, int(math.ceil(n / nx)))


def forest_spots(
    w: float, d: float, density: float = 0.04, mix: float = 0.5, h: float = 14.0, jitter: float = 0.45, seed: float = 1
) -> list:
    """[(x, z, conifer, h, crown_factor)] for every tree of a forest record, in the
    record's own frame (its centre is 0, 0). The JS and Blender copies produce
    this list element for element."""
    w, d = _clamp(float(w), 1.0, 600.0), _clamp(float(d), 1.0, 600.0)
    mix = _clamp(float(mix), 0.0, 1.0)
    h = _clamp(float(h), 0.5, 120.0)
    jitter = _clamp(float(jitter), 0.0, 2.0)
    n, s, nx, _nz = forest_grid(w, d, density)
    x0, z0 = -w / 2 + s / 2, -d / 2 + s / 2
    out = []
    for k in range(n):
        j, i = divmod(k, nx)
        out.append(
            (
                x0 + i * s + (2 * _hash(i, j, seed) - 1) * jitter * s,
                z0 + j * s + (2 * _hash(i, j, seed + 1) - 1) * jitter * s,
                _hash(i, j, seed + 2) < mix,
                h * (0.7 + 0.6 * _hash(i, j, seed + 3)),
                0.8 + 0.4 * _hash(i, j, seed + 4),
            )
        )
    return out


def forest_bbox(p: dict) -> tuple:
    """(sx, sy, sz) — the bounding box of a `forest` record built from p, in metres.

    The x and z spans are the scatter plus each tree's own crown radius; they do
    NOT move with gx/gz, because a draped tree slides straight up, never sideways.
    The y span DOES: every tree's base is at gx*x + gz*z and its top at base + h,
    so the box grows by the ground plane's rise across the footprint. The tab's
    Box3 over the same record matches this; test_forests.py asserts it within 2 %.
    """
    w = _clamp(_num(p.get('w'), 100.0), 1.0, 600.0)
    dd = _clamp(_num(p.get('d'), 100.0), 1.0, 600.0)
    gx, gz = _num(p.get('gx'), 0.0), _num(p.get('gz'), 0.0)
    spots = forest_spots(
        w,
        dd,
        _num(p.get('density'), 0.04),
        _num(p.get('mix'), 0.5),
        _num(p.get('h'), 14.0),
        _num(p.get('jitter'), 0.45),
        _num(p.get('seed'), 1),
    )
    xs, zs, ys = [], [], []
    for x, z, conifer, hk, cf in spots:
        r = crown_radius(CONIFER if conifer else DECIDUOUS, hk, cf)
        base = gx * x + gz * z
        xs += [x - r, x + r]
        zs += [z - r, z + r]
        ys += [base, base + max(0.5, hk)]
    return max(xs) - min(xs), max(ys) - min(ys), max(zs) - min(zs)


def line_count(length: float, spacing: float) -> int:
    length = _clamp(float(length), 1.0, 2000.0)
    spacing = _clamp(float(spacing), 1.0, 100.0)
    return max(1, min(LINE_MAX, int(math.floor(length / spacing)) + 1))


def tree_line_spots(length: float, spacing: float = 6.0, h: float = 10.0, jitter: float = 0.2, seed: float = 1) -> list:
    """[(x, z, h, crown_factor)] for a row of trees along local +X."""
    length = _clamp(float(length), 1.0, 2000.0)
    spacing = _clamp(float(spacing), 1.0, 100.0)
    h = _clamp(float(h), 0.5, 120.0)
    jitter = _clamp(float(jitter), 0.0, 10.0)
    n = line_count(length, spacing)
    return [
        (
            -length / 2 + i * spacing,
            (2 * _hash(i, 0, seed) - 1) * jitter,
            h * (0.85 + 0.3 * _hash(i, 0, seed + 3)),
            0.8 + 0.4 * _hash(i, 0, seed + 4),
        )
        for i in range(n)
    ]


def orchard_grid(w: float, d: float, spacing: float = 5.0) -> tuple:
    w, d = _clamp(float(w), 1.0, 600.0), _clamp(float(d), 1.0, 600.0)
    spacing = _clamp(float(spacing), 1.0, 100.0)
    return int(math.floor(w / spacing)) + 1, int(math.floor(d / spacing)) + 1


def orchard_spots(w: float, d: float, spacing: float = 5.0) -> list:
    """[(x, z)] for every fruit tree — an exact grid, no jitter."""
    spacing = _clamp(float(spacing), 1.0, 100.0)
    nx, nz = orchard_grid(w, d, spacing)
    x0, z0 = -(nx - 1) * spacing / 2, -(nz - 1) * spacing / 2
    return [(x0 + i * spacing, z0 + j * spacing) for j in range(nz) for i in range(nx)]


def undergrowth_spots(w: float, d: float, count: int = 60, seed: float = 1, r: float = 0.8) -> list:
    """[(x, z, radius)] for every bush; each bush is 1.2 x radius tall."""
    w, d = _clamp(float(w), 1.0, 600.0), _clamp(float(d), 1.0, 600.0)
    r = _clamp(float(r), 0.05, 8.0)
    n = max(1, min(SCATTER_MAX, int(round(float(count)))))
    return [
        (-w / 2 + _hash(i, 0, seed) * w, -d / 2 + _hash(i, 0, seed + 1) * d, r * (0.6 + 0.8 * _hash(i, 0, seed + 2)))
        for i in range(n)
    ]


def _mat(m, default='mat_foliage'):
    return m if m in MATERIALS else default


def _ry(a, b):
    return math.atan2(-(b[1] - a[1]), b[0] - a[0])


# ── R2: drape a block over the ground, tiling it when the ground is not planar ──
def drape_tiles(d: Drawing, cx: float, cz: float, W: float, D: float, base_height=None) -> list:
    """[(x, z, w, dd, y, gx, gz)] — the sub-blocks one planting call should become.

    ONE entry when the caller pinned base_height (a platform: flat, no slope) or
    when the ground under the whole block is planar within TILE_SPREAD — that is
    the flat case and the slope case, both of which a single draped record draws
    exactly. Otherwise the block is cut into tiles of at most TILE_M a side and
    halved again until every tile is planar within TILE_SPREAD, capped at
    TILE_MAX records; each tile gets the ground height under its own centre and
    its own local slopes, so a wood follows a hill without any record being tilted.
    """
    if base_height is not None and base_height != '':
        return [(cx, cz, W, D, _num(base_height, 0.0), 0.0, 0.0)]

    def grid(nx, nz):
        tw, td = W / nx, D / nz
        out, worst = [], 0.0
        for j in range(nz):
            for i in range(nx):
                tx = cx - W / 2 + (i + 0.5) * tw
                tz = cz - D / 2 + (j + 0.5) * td
                _y0, glx, glz, spread = ground_plane(d, tx, tz, tw, td, 0.0)
                # the fitted plane gives the SLOPE; the HEIGHT is the real ground under
                # the tile's own centre (R5/R8). A least-squares y0 sits ~0.7 m under a
                # 20 m tile of a dome, which would bury that tile's trunks.
                out.append((tx, tz, tw, td, ground_height(d, tx, tz), glx, glz))
                worst = max(worst, spread)
        return out, worst

    tiles, worst = grid(1, 1)
    nx, nz = 1, 1
    while worst > TILE_SPREAD:
        nx = max(nx * 2, int(math.ceil(W / TILE_M))) if nx == 1 else nx * 2
        nz = max(nz * 2, int(math.ceil(D / TILE_M))) if nz == 1 else nz * 2
        if nx * nz > TILE_MAX:
            break
        tiles, worst = grid(nx, nz)
    return tiles


def _tiled_note(tiles: list) -> str:
    return f', in {len(tiles)} tiles over the ground' if len(tiles) > 1 else ''


def _drop_note(tiles: list) -> str:
    """'draped over a 6.4 m fall' — what the ground does under the whole planting."""
    ys = [t[4] for t in tiles]
    fall = max(ys) - min(ys)
    if len(tiles) == 1:
        gx, gz = tiles[0][5], tiles[0][6]
        rise = abs(gx) * tiles[0][2] + abs(gz) * tiles[0][3]
        return f', draped on a slope falling {rise:.1f} m across it' if rise > 0.1 else ''
    return f', draped over a {fall:.1f} m fall' if fall > 0.1 else ''


# ── tools ────────────────────────────────────────────────────────────────────
def t_plant_forest(
    d: Drawing,
    a,
    cell_from,
    cell_to,
    density=0.04,
    mix='mixed',
    height=14.0,
    seed=1,
    jitter=0.45,
    base_height=None,
    material='',
    name='',
):
    mx = str(mix or 'mixed').strip().lower()
    if mx not in MIXES:
        return "refused: mix must be 'mixed', 'conifer' or 'deciduous'"
    dens = _num(density, 0.04)
    if dens <= 0 or dens > 1:
        return 'refused: density is trees per square metre — between 0.0005 and 1 (0.04 is a dense wood)'
    h = _num(height, 14.0)
    lo, hi = MIX_H[mx]
    if h < lo or h > hi:
        return (
            f'refused: {h:g} m is not the mean height of a {mx} wood — a deciduous tree is '
            f'{TREE_H[DECIDUOUS][0]:g}-{TREE_H[DECIDUOUS][1]:g} m and a conifer '
            f'{TREE_H[CONIFER][0]:g}-{TREE_H[CONIFER][1]:g} m, so a {mx} wood means {lo:g}-{hi:g} m '
            f'(each tree comes out {SPREAD_LO:g}-{SPREAD_HI:g} of the mean)'
        )
    xmin, zmin, xmax, zmax = block_bounds(cell_from, cell_to)
    W, D = xmax - xmin, zmax - zmin
    if W > 600 or D > 600:
        return f'refused: {W:g} x {D:g} m is too big for one forest — 600 m a side is the limit'
    n = int(math.floor(W * D * dens + 0.5))
    if n > FOREST_MAX:
        return (
            f'refused: {W:g} x {D:g} m at density {dens:g} is {n} trees and one forest holds {FOREST_MAX} — '
            f'split the block into two forests or lower the density (try {FOREST_MAX / (W * D):.3f})'
        )
    if n < 1:
        return f'refused: {W:g} x {D:g} m at density {dens:g} is not one whole tree — raise the density'
    cx, cz = (xmin + xmax) / 2, (zmin + zmax) / 2
    tiles = drape_tiles(d, cx, cz, W, D, base_height)
    if len(d.objs) + len(tiles) > MAX_OBJECTS:
        return f'refused: the drawing is at the {MAX_OBJECTS} object ceiling'
    jit = _clamp(_num(jitter, 0.45), 0.0, 2.0)
    sd = _num(seed, 1)
    s = forest_spacing(dens)
    cf, ct = cell_name(*parse_cell(cell_from)), cell_name(*parse_cell(cell_to))
    grp = name or 'forest'
    ids, planted = [], 0
    for i, (tx, tz, tw, td, ty, gx, gz) in enumerate(tiles):
        planted += forest_count(tw, td, dens)
        o = d.new(
            'forest',
            {
                'w': round(tw, 4),
                'd': round(td, 4),
                'density': round(dens, 6),
                'mix': MIXES[mx],
                'h': round(h, 3),
                'seed': sd + i,
                'jitter': round(jit, 3),
                'res': 0,
                'gx': round(gx, 5),
                'gz': round(gz, 5),
            },
            tx,
            tz,
            ty,
            0.0,
            _mat(material),
            name=(name or f'forest {cf}-{ct}') + (f' {i + 1}' if len(tiles) > 1 else ''),
            grp=grp,
        )
        ids.append(o['id'])
    stood = f', standing at {tiles[0][4]:g} m' if base_height not in (None, '') and tiles[0][4] else ''
    return (
        f'planted forest {ids[0]}{".." + ids[-1] if len(ids) > 1 else ""} over {cf}..{ct}: {W:g} x {D:g} m, '
        f'{planted} {mx} trees {s:.1f} m apart (density {dens:g}/m2), {h:g} m tall on average, seed {sd:g}, '
        f'{"one object" if len(ids) == 1 else str(len(ids)) + " objects"}'
        + _tiled_note(tiles)
        + _drop_note(tiles)
        + stood
        + f', group "{grp}"'
    )


def _real_line(d: Drawing, pts, sp, kd, h, sd, base_height, grp, cells):
    """An avenue of REAL pack trees (2026-09-08): one asset every `spacing` m
    along the polyline, turned at random, spacing at least 0.6 of a crown so
    the row reads as trees, not a hedge. None when no life-size model fits."""
    SL, AS = EXT_MODULES.get('site_landscape'), EXT_MODULES.get('assets_search')
    if SL is None or AS is None:
        return None
    species = {'deciduous': 'tree_deciduous', 'conifer': 'tree_conifer', 'poplar': 'tree_conifer'}[kd]
    row, scale = SL._real_pick(SL.REAL_TREES.get(species, []), h)
    if row is None:
        return None
    # a scanned tree's bbox can be wider than its crown (stray branches, a ground
    # disc): a crown is never wider than 0.6 x the height it stands at
    crown = min(max(row['size'][0], row['size'][2]) * scale, row['size'][1] * scale * 0.6)
    min_sp = round(0.6 * crown, 1)
    if sp < min_sp - 1e-6:
        return (
            f'refused: {row["n"]} at {h:g} m has a {crown:.1f} m crown — a row at {sp:g} m merges into a hedge; '
            f'use spacing >= {min_sp:g} (or a clipped hedge: add_fence(kind="hedge"))'
        )
    ids, n, total = [], 0, 0.0
    for i in range(len(pts) - 1):
        A, B = pts[i], pts[i + 1]
        L = math.hypot(B[0] - A[0], B[1] - A[1])
        total += L
        k = line_count(L, sp)
        if len(d.objs) + k > MAX_OBJECTS:
            return f'refused: that is {k} trees past the {MAX_OBJECTS} ceiling'
        for j in range(k):
            f = (j * sp) / L if k > 1 else 0.5
            f = min(f, 1.0)
            x, z = A[0] + (B[0] - A[0]) * f, A[1] + (B[1] - A[1]) * f
            y = place_height(d, x, z, base_height)
            o = d.new(
                'asset',
                AS._params(row),
                x,
                z,
                y,
                (hash((int(sd), i, j)) % 360) * math.pi / 180,
                None,
                name=f'{row["n"]} {n + 1}',
                grp=grp,
            )
            o['s'] = scale
            ids.append(o['id'])
            n += 1
    return (
        f'planted {n} x {row["n"]} ({row["id"]}, real model, scale {scale:g} = {row["size"][1] * scale:.1f} m tall) '
        f'{ids[0]}..{ids[-1]} every {sp:g} m along {total:.1f} m through {", ".join(str(c) for c in cells)}, '
        f'each on the ground under it, group "{grp}"'
    )


def t_plant_tree_line(
    d: Drawing,
    a,
    cells,
    spacing=6.0,
    kind='deciduous',
    height=10.0,
    jitter=0.2,
    seed=1,
    base_height=None,
    material='',
    name='',
    model='real',
):
    kd = str(kind or 'deciduous').strip().lower()
    if kd not in LINE_KINDS:
        return "refused: kind must be 'deciduous', 'conifer' or 'poplar'"
    if not isinstance(cells, (list, tuple)) or len(cells) < 2:
        return 'refused: give a list of at least two cells — one tree line is drawn between each pair'
    sp = _num(spacing, 6.0)
    if sp < 1:
        return 'refused: trees in a row stand at least 1 m apart'
    h = _num(height, 10.0)
    code = LINE_KINDS[kd]
    lo, hi = TREE_H[code]
    if h < lo or h > hi:
        return f'refused: {h:g} m is not the height of {TREE_NAME[code]} — they are {lo:g}-{hi:g} m tall'
    pts = [cell_centre(*parse_cell(c)) for c in cells]
    if str(model or 'real').lower() == 'real':
        grp0 = name or f'tree line {cells[0]}-{cells[-1]}'
        out = _real_line(d, pts, sp, kd, h, _num(seed, 1), base_height, grp0, cells)
        if out is not None:
            return out
    need = len(pts) - 1
    if len(d.objs) + need > MAX_OBJECTS:
        return f'refused: that is {need} objects past the {MAX_OBJECTS} ceiling'
    jit = _clamp(_num(jitter, 0.2), 0.0, 10.0)
    sd = _num(seed, 1)
    grp = name or f'tree line {cells[0]}-{cells[-1]}'
    mat = _mat(material)
    ids, total, trees, falls = [], 0.0, 0, []
    for i in range(need):
        A, B = pts[i], pts[i + 1]
        L = math.hypot(B[0] - A[0], B[1] - A[1])
        if L < 1:
            return f'refused: {cells[i]} and {cells[i + 1]} are the same cell — a tree line needs two different cells'
        total += L
        trees += line_count(L, sp)
        mx, mz = (A[0] + B[0]) / 2, (A[1] + B[1]) / 2
        y = place_height(d, mx, mz, base_height)
        # R4 with a twist: a tree line runs along the ground like a fence, but its
        # trees must stay VERTICAL — so the fall along the reach becomes gx (local
        # +X points from A to B), never rz, which would lean every trunk downhill.
        if base_height in (None, ''):
            gx = (ground_height(d, B[0], B[1]) - ground_height(d, A[0], A[1])) / L
        else:
            gx = 0.0
        falls.append(gx * L)
        o = d.new(
            'tree_line',
            {
                'len': round(L, 4),
                'spacing': round(sp, 3),
                'kind': code,
                'h': round(h, 3),
                'jitter': round(jit, 3),
                'seed': sd,
                'gx': round(gx, 5),
                'gz': 0,
            },
            mx,
            mz,
            y,
            _ry(A, B),
            mat,
            name=f'tree line {i + 1}',
            grp=grp,
        )
        ids.append(o['id'])
    drop = max(abs(f) for f in falls)
    ran = f', running downhill {drop:.1f} m over {total:.0f} m' if drop > 0.1 else ''
    lifted = _num(base_height, 0.0) if base_height not in (None, '') else 0.0
    stood = f', standing at {lifted:g} m' if lifted else ''
    return (
        f'planted {need} {kd} tree line(s) {ids[0]}..{ids[-1]} through {", ".join(str(c) for c in cells)}: '
        f'{trees} trees {sp:g} m apart over {total:.1f} m, {h:g} m tall' + ran + stood + f', group "{grp}"'
    )


def t_plant_orchard(d: Drawing, a, cell_from, cell_to, spacing=5.0, height=4.0, base_height=None, material='', name=''):
    sp = _num(spacing, 5.0)
    if sp < 1:
        return 'refused: fruit trees stand at least 1 m apart'
    h = _num(height, 4.0)
    if h < FRUIT_H[0] or h > FRUIT_H[1]:
        return (
            f'refused: {h:g} m is not the height of a fruit tree — they are '
            f'{FRUIT_H[0]:g}-{FRUIT_H[1]:g} m tall (use plant_forest for a wood)'
        )
    xmin, zmin, xmax, zmax = block_bounds(cell_from, cell_to)
    W, D = xmax - xmin, zmax - zmin
    if W > 600 or D > 600:
        return f'refused: {W:g} x {D:g} m is too big for one orchard — 600 m a side is the limit'
    nx, nz = orchard_grid(W, D, sp)
    if nx * nz > FOREST_MAX:
        return (
            f'refused: {nx} x {nz} is {nx * nz} fruit trees and one orchard holds {FOREST_MAX} — '
            'split the block or widen the spacing'
        )
    cx, cz = (xmin + xmax) / 2, (zmin + zmax) / 2
    tiles = drape_tiles(d, cx, cz, W, D, base_height)
    if len(d.objs) + len(tiles) > MAX_OBJECTS:
        return f'refused: the drawing is at the {MAX_OBJECTS} object ceiling'
    cf, ct = cell_name(*parse_cell(cell_from)), cell_name(*parse_cell(cell_to))
    grp = name or 'orchard'
    ids, total = [], 0
    for i, (tx, tz, tw, td, ty, gx, gz) in enumerate(tiles):
        tnx, tnz = orchard_grid(tw, td, sp)
        total += tnx * tnz
        o = d.new(
            'orchard',
            {
                'w': round(tw, 4),
                'd': round(td, 4),
                'spacing': round(sp, 3),
                'h': round(h, 3),
                'gx': round(gx, 5),
                'gz': round(gz, 5),
            },
            tx,
            tz,
            ty,
            0.0,
            _mat(material),
            name=(name or f'orchard {cf}-{ct}') + (f' {i + 1}' if len(tiles) > 1 else ''),
            grp=grp,
        )
        ids.append(o['id'])
    stood = f', standing at {tiles[0][4]:g} m' if base_height not in (None, '') and tiles[0][4] else ''
    counted = f'{nx} x {nz} = {nx * nz} fruit trees' if len(ids) == 1 else f'{total} fruit trees'
    return (
        f'planted orchard {ids[0]}{".." + ids[-1] if len(ids) > 1 else ""} over {cf}..{ct}: '
        f'{W:g} x {D:g} m, {counted} {sp:g} m apart, {h:g} m tall, '
        f'{"one object" if len(ids) == 1 else str(len(ids)) + " objects"}'
        + _tiled_note(tiles)
        + _drop_note(tiles)
        + stood
        + f', group "{grp}"'
    )


def t_add_undergrowth(
    d: Drawing, a, cell_from, cell_to, count=60, seed=1, bush_radius=0.8, base_height=None, material='', name=''
):
    n = int(_num(count, 60))
    if n < 1 or n > SCATTER_MAX:
        return f'refused: count must be between 1 and {SCATTER_MAX} bushes'
    r = _num(bush_radius, 0.8)
    # a bush is 1.2 x its radius tall (the squashed crown sphere), and a real shrub
    # is SHRUB_H tall — so the radius the tool accepts follows from the real range
    r_lo, r_hi = SHRUB_H[0] / 1.2, SHRUB_H[1] / 1.2
    if r < r_lo or r > r_hi:
        return (
            f'refused: a bush {1.2 * r:.2f} m tall is not a shrub — shrubs are '
            f'{SHRUB_H[0]:g}-{SHRUB_H[1]:g} m tall, so bush_radius is {r_lo:.2f}-{r_hi:.2f} m '
            f'(use plant_forest for trees)'
        )
    xmin, zmin, xmax, zmax = block_bounds(cell_from, cell_to)
    W, D = xmax - xmin, zmax - zmin
    if W > 600 or D > 600:
        return f'refused: {W:g} x {D:g} m is too big for one scatter — 600 m a side is the limit'
    cx, cz = (xmin + xmax) / 2, (zmin + zmax) / 2
    tiles = drape_tiles(d, cx, cz, W, D, base_height)
    if len(d.objs) + len(tiles) > MAX_OBJECTS:
        return f'refused: the drawing is at the {MAX_OBJECTS} object ceiling'
    sd = _num(seed, 1)
    cf, ct = cell_name(*parse_cell(cell_from)), cell_name(*parse_cell(cell_to))
    grp = name or 'undergrowth'
    per = max(1, int(round(n / len(tiles))))
    ids = []
    for i, (tx, tz, tw, td, ty, gx, gz) in enumerate(tiles):
        o = d.new(
            'undergrowth',
            {
                'w': round(tw, 4),
                'd': round(td, 4),
                'count': n if len(tiles) == 1 else per,
                'seed': sd + i,
                'r': round(r, 3),
                'gx': round(gx, 5),
                'gz': round(gz, 5),
            },
            tx,
            tz,
            ty,
            0.0,
            _mat(material),
            name=(name or f'undergrowth {cf}-{ct}') + (f' {i + 1}' if len(tiles) > 1 else ''),
            grp=grp,
        )
        ids.append(o['id'])
    stood = f', standing at {tiles[0][4]:g} m' if base_height not in (None, '') and tiles[0][4] else ''
    return (
        f'scattered undergrowth {ids[0]}{".." + ids[-1] if len(ids) > 1 else ""} over {cf}..{ct}: '
        f'{W:g} x {D:g} m, {n if len(ids) == 1 else per * len(ids)} bushes around {r:g} m across, seed {sd:g}, '
        f'{"one object" if len(ids) == 1 else str(len(ids)) + " objects"}'
        + _tiled_note(tiles)
        + _drop_note(tiles)
        + stood
        + f', group "{grp}"'
    )


_CELL = {'type': 'string'}
_CELL_LIST = {'type': 'array', 'items': {'type': 'string'}}
_BASE = {
    'type': 'number',
    'description': 'Leave it out to drape on the ground under the planting (a hill, a slope, a plateau); give a number to override that ground level.',
}

TOOLS = [
    (
        {
            'name': 'plant_forest',
            'description': 'A whole wood over a block of cells as ONE object: hundreds of low-poly trees on a jittered grid. density is trees per square metre (0.04 = one every 5 m, a dense wood; 0.01 = parkland); mix is mixed, conifer or deciduous; height is the MEAN tree — 6-20 m deciduous, 8-25 conifer, refused outside. It drapes over the ground under it, every trunk vertical, and splits into tiles over a hill. Use this, not plant_trees, for anything bigger than a handful of trees.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'cell_from': _CELL,
                    'cell_to': _CELL,
                    'density': {'type': 'number'},
                    'mix': {'type': 'string', 'enum': list(MIXES)},
                    'height': {'type': 'number'},
                    'seed': {'type': 'number'},
                    'jitter': {'type': 'number'},
                    'base_height': _BASE,
                    'material': {'type': 'string', 'enum': MATERIALS},
                    'name': {'type': 'string'},
                },
                'required': ['cell_from', 'cell_to'],
            },
        },
        t_plant_forest,
    ),
    (
        {
            'name': 'plant_tree_line',
            'description': 'A row of trees between each pair of cells in the list: limes along a drive, poplars along a canal, a conifer windbreak. By default every tree is a REAL life-size pack model scaled to `height` (model="parametric" gives the one-object low-poly row); spacing is the gap between trunks and must be at least 0.6 of a crown (crowns touch in an avenue). kind is deciduous (6-20 m), conifer (8-25) or poplar (15-25), refused outside. The row follows the ground with every trunk vertical.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'cells': _CELL_LIST,
                    'spacing': {'type': 'number'},
                    'model': {'type': 'string', 'enum': ['real', 'parametric']},
                    'kind': {'type': 'string', 'enum': list(LINE_KINDS)},
                    'height': {'type': 'number'},
                    'jitter': {'type': 'number'},
                    'seed': {'type': 'number'},
                    'base_height': _BASE,
                    'material': {'type': 'string', 'enum': MATERIALS},
                    'name': {'type': 'string'},
                },
                'required': ['cells'],
            },
        },
        t_plant_tree_line,
    ),
    (
        {
            'name': 'plant_orchard',
            'description': 'A grid of small round-crowned fruit trees over a block of cells, as ONE object. spacing is the row and tree gap, height the tree — a fruit tree is 3-5 m, refused outside. It drapes on the ground under it and tiles over a hill.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'cell_from': _CELL,
                    'cell_to': _CELL,
                    'spacing': {'type': 'number'},
                    'height': {'type': 'number'},
                    'base_height': _BASE,
                    'material': {'type': 'string', 'enum': MATERIALS},
                    'name': {'type': 'string'},
                },
                'required': ['cell_from', 'cell_to'],
            },
        },
        t_plant_orchard,
    ),
    (
        {
            'name': 'add_undergrowth',
            'description': 'A seeded scatter of low bushes over a block of cells, as ONE object — the forest floor under a wood, scrub on waste ground, planting under a tree line. A shrub is 0.4-2 m tall (bush_radius 0.33-1.67 m), refused outside. It drapes on the ground under it and tiles over a hill.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'cell_from': _CELL,
                    'cell_to': _CELL,
                    'count': {'type': 'integer'},
                    'seed': {'type': 'number'},
                    'bush_radius': {'type': 'number'},
                    'base_height': _BASE,
                    'material': {'type': 'string', 'enum': MATERIALS},
                    'name': {'type': 'string'},
                },
                'required': ['cell_from', 'cell_to'],
            },
        },
        t_add_undergrowth,
    ),
]

EXAMPLES = [
    {
        'ask': 'a dense mixed wood behind the house, from D20 to AC49',
        'calls': [
            {
                'tool': 'plant_forest',
                'args': {'cell_from': 'D20', 'cell_to': 'AC49', 'density': 0.04, 'mix': 'mixed', 'height': 14},
            }
        ],
    },
    {
        'ask': 'plant the whole north field as parkland, B4 to BH53, big oaks well apart',
        'calls': [
            {
                'tool': 'plant_forest',
                'args': {'cell_from': 'B4', 'cell_to': 'BH53', 'density': 0.01, 'mix': 'deciduous', 'height': 18},
            }
        ],
    },
    {
        'ask': 'poplars along the canal from C10 to C70',
        'calls': [
            {'tool': 'plant_tree_line', 'args': {'cells': ['C10', 'C70'], 'kind': 'poplar', 'spacing': 6, 'height': 16}}
        ],
    },
    {
        'ask': 'a conifer windbreak along the north and west edges, A5 to A40 to X40',
        'calls': [
            {
                'tool': 'plant_tree_line',
                'args': {'cells': ['A5', 'A40', 'X40'], 'kind': 'conifer', 'spacing': 4, 'height': 9},
            }
        ],
    },
    {
        'ask': 'an apple orchard on the south paddock, E60 to N75',
        'calls': [{'tool': 'plant_orchard', 'args': {'cell_from': 'E60', 'cell_to': 'N75', 'spacing': 5, 'height': 4}}],
    },
    {
        'ask': 'scrub under the wood, D20 to AC49, and put the wood on the 3 m plateau',
        'calls': [
            {'tool': 'plant_forest', 'args': {'cell_from': 'D20', 'cell_to': 'AC49', 'base_height': 3}},
            {
                'tool': 'add_undergrowth',
                'args': {'cell_from': 'D20', 'cell_to': 'AC49', 'count': 300, 'base_height': 3},
            },
        ],
    },
    {
        'ask': 'cover the hill in pines',
        'calls': [
            {'tool': 'plant_forest', 'args': {'cell_from': 'D20', 'cell_to': 'AC49', 'mix': 'conifer', 'height': 16}}
        ],
    },
]
