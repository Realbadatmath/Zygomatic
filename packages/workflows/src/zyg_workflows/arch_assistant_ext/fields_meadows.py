# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""fields_meadows — farmland and wet ground: crop fields, tulip fields, meadows,
marsh and vineyards, plus the two recipes: make_polder draws a field ringed by
its ditches (the `canal` kind), add_pasture a flowerless meadow ringed by the
`fence` kind. Both borrow kinds another family owns; nothing here edits them.

A field is ONE record: the soil plate and every row of crop are merged into a
handful of parts inside the geometry, so a 60 x 40 m tulip field with 54 rows is
one object in the outliner, not 54. The row arithmetic (`field_rows`) and the
flower/reed scatter (`value_noise`'s hash) are written out identically in
arch_ext/fields_meadows.js and arch_blender_ext/fields_meadows.py — the test
evaluates the copies here and compares triangle counts with the tab.

THE GROUND (2026-09-07). Nothing lands at y = 0 any more:

  R1  base_height defaults to None — "the ground under it". A number overrides
      and means a level terrace (no drape, no tiling).
  R2  A field, a meadow and a vineyard are a thin surface carrying a scatter of
      upright things, so they DRAPE: the record takes the ground plane's slopes
      as p.gx / p.gz (rise per metre along its local x and z) and the geometry
      drops every plate corner, every row, every post and every flower onto that
      plane while their sides stay vertical. Tilting the record itself would
      lean the crop over. Where the ground is not planar under the footprint
      (ground_plane's spread > 1 m) the tool TILES it: ceil(W/25) x ceil(D/25)
      sub-blocks, halved again until every tile is planar, capped at 64, one
      record each in one group — and it says so.
  R3  A marsh is WATER and lies LEVEL: it takes the ground at its centre and
      REFUSES ground that varies more than 0.5 m under it. make_polder's four
      ditches are level water too, so a polder refuses the same ground.
  R4  add_pasture's fences are linear things along the ground: each takes the
      ground at its own centre and an rz tilt so it runs downhill with the
      slope it sits on.
  R7  Real sizes, absolute: crop rows 0.15-0.5 m tall (wheat 0.6, corn 2.2),
      vine rows 1.6-2.0 m, reeds 1.5-2.5 m. A row is 0.6 x spacing wide so it
      reads as a stripe with soil showing between, never a pipe.

Rows follow the CONTOUR when the caller names no direction: add_field and
add_vineyard run them across the steeper of the two ground gradients.

The scatter hash is the SAME generator as arch_ext/terrain.js:
frac(sin(i*127.1 + j*311.7 + seed*74.7) * 43758.5453).
"""

from __future__ import annotations

import math

from zyg_workflows.arch_assistant import (
    Drawing,
    parse_cell,
    cell_name,
    block_bounds,
    MATERIALS,
    MAX_OBJECTS,
    _num,
    ground_at,
    ground_height,
    ground_plane,
    place_height,
)

KINDS = {
    'crop_field': {'w': 60, 'd': 40, 'crop': 0, 'spacing': 0.75, 'h': 0.6, 'dir': 0, 'gx': 0, 'gz': 0},
    'meadow': {'w': 60, 'd': 40, 'flowers': 200, 'seed': 1, 'h': 0.25, 'gx': 0, 'gz': 0},
    'marsh': {'w': 60, 'd': 40, 'depth': 0.4, 'reeds': 150, 'seed': 1, 'reed_h': 1.8},
    'vineyard': {'w': 60, 'd': 40, 'row_spacing': 2.5, 'h': 1.8, 'dir': 0, 'gx': 0, 'gz': 0},
}
OPENINGS: list = []

PROMPT = (
    'Fields & meadows: add_field(cell_from, cell_to, crop, direction, spacing) lays a field (akker) over a '
    "block — one object however many rows — with crop 'wheat', 'corn', 'potatoes', 'grass' or 'tulips' "
    '(the striped bollenveld). Rows are real crop heights (wheat 0.6 m, corn 2.2, potatoes 0.5, '
    'tulips 0.3, grass 0.25) and 0.6 x spacing wide, so they read as stripes with soil between. Everything '
    'lands on the ground under it (a hill, a slope, a plateau, a dune) and is DRAPED over it — rows, posts '
    'and flowers stay upright; base_height overrides with a level terrace. Leave direction out and the rows '
    'follow the contour of the slope. Over broken ground it tiles, one record a patch. '
    'make_polder(cell_from, cell_to, ditch_width, crop) is a whole polder: a field inset by its four '
    'ditches (sloten). add_meadow(cell_from, cell_to, flowers, seed) is grass (weiland) dotted with flowers, '
    'add_pasture fences it for grazing; add_marsh(cell_from, cell_to, reeds, depth) is shallow water with '
    'reeds (moeras) and refuses uneven ground, because water lies level; add_vineyard plants 1.6-2.0 m vine '
    'rows on posts.'
)

MAX_ROWS = 400
MAX_FLOWERS = 2000
MAX_REEDS = 1500
MAX_SIDE = 1000.0
ROW_FRAC = 0.6  # a row of crop is 0.6 x spacing wide: a stripe, not a pipe
VINE_BAND = 0.5  # how wide the vine mass of one row is
POST_SPACING = 6.0  # a vineyard post every 6 m along the row

# ── the ground constants (R2, R3) ───────────────────────────────────────────
FLAT_M = 1.0  # ground_plane spread a single draped record may carry
WATER_FLAT_M = 0.5  # ground variation level water tolerates under it
TILE_M = 25.0  # the first tile size when the footprint is not planar
MAX_TILES = 64
CONTOUR_MIN = 0.02  # a gradient under this is flat: no contour to follow

# crop name -> (code, real row height, default spacing)   R7: 0.15-0.5, wheat 0.6, corn 2.2
CROPS = {
    'wheat': (0, 0.6, 0.75),
    'corn': (1, 2.2, 0.75),
    'maize': (1, 2.2, 0.75),
    'potatoes': (2, 0.5, 0.75),
    'grass': (3, 0.25, 0.75),
    'hay': (3, 0.25, 0.75),
    'tulips': (4, 0.3, 0.75),
}
CROP_NAMES = ('wheat', 'corn', 'potatoes', 'grass', 'tulips')
CROP_PARTS = (1, 1, 1, 1, 3)  # sub-material parts the rows are merged into

VINE_H = (1.6, 2.0)  # R7: a vine row is 1.6-2.0 m
REED_H = (1.5, 2.5)  # R7: reeds are 1.5-2.5 m


# ── the shared arithmetic (identical in the JS and the Blender copies) ───────
def _hash(ix: float, iy: float, seed: float) -> float:
    v = math.sin(ix * 127.1 + iy * 311.7 + seed * 74.7) * 43758.5453
    return v - math.floor(v)


def row_band(spacing: float) -> float:
    """How wide one row of crop is, across the rows: 0.6 x the gap between them,
    so the soil shows and the field reads as stripes."""
    return max(0.05, ROW_FRAC * max(0.05, spacing))


def field_rows(d: float, spacing: float, band: float | None = None) -> list:
    """Row centres across a plot `d` deep: floor(d/spacing)+1 rows, spread so a
    row `band` wide reaches exactly to the plot edge at both ends."""
    if band is None:
        band = row_band(spacing)
    n = max(2, min(2000, int(math.floor(d / max(0.05, spacing))) + 1))
    span = max(0.0, d - band)
    step = span / (n - 1)
    return [-span / 2 + j * step for j in range(n)]


def row_count(d: float, spacing: float) -> int:
    """How many rows a field `d` deep carries at `spacing` — the number the tab
    and Blender both build."""
    return max(2, min(2000, int(math.floor(d / max(0.05, spacing))) + 1))


def post_count(w: float) -> int:
    """Posts along one vineyard row, one every POST_SPACING metres."""
    return max(2, min(400, int(math.floor(max(0.5, w) / POST_SPACING)) + 1))


def flower_colours(flowers: int, seed: float) -> list:
    """How many flower heads fall to each of the three colours — the tab merges
    each colour into one part, so this decides the record's part count."""
    n = [0, 0, 0]
    for i in range(max(0, min(MAX_FLOWERS, int(flowers)))):
        n[int(_hash(i, 3, seed) * 3) % 3] += 1
    return n


def crop_field_tris(d: float, spacing: float) -> int:
    """Triangles the tab builds for a crop field: the soil plate plus 12 per row.
    Draping moves vertices, it never adds any."""
    return 12 + 12 * row_count(d, spacing)


def meadow_tris(flowers: int) -> int:
    return 12 + 12 * max(0, min(MAX_FLOWERS, int(flowers)))


def marsh_tris(reeds: int) -> int:
    """4 rim boxes + bed + water surface, then 12 per 4-sided reed."""
    return 12 * 6 + 12 * max(0, min(MAX_REEDS, int(reeds)))


def vineyard_tris(w: float, d: float, row_spacing: float) -> int:
    return row_count(d, row_spacing) * 12 * (1 + post_count(w))


def draped_height(w: float, d: float, gx: float, gz: float, top: float, dir_deg: float = 0.0) -> float:
    """The bounding-box height of a draped w x d record whose tallest solid rises
    `top` above the plane: the plane's own rise across the footprint plus `top`.
    dir_deg is the record's `dir` — the plan turn the geometry applies before the
    plane is read, so the footprint's extent along the local axes turns with it."""
    a = math.radians(dir_deg)
    c, s = math.cos(a), math.sin(a)
    return abs(gx * c - gz * s) * w + abs(gx * s + gz * c) * d + top


# ── the ground (R1, R2, R3) ─────────────────────────────────────────────────
def _lattice(d: Drawing, cx: float, cz: float, W: float, D: float, ry: float, nx: int, nz: int):
    """nx x nz sub-blocks over the footprint, each with its own ground plane."""
    c, s = math.cos(ry), math.sin(ry)
    tw, td = W / nx, D / nz
    out, worst = [], 0.0
    for j in range(nz):
        for i in range(nx):
            lx = -W / 2 + (i + 0.5) * tw
            lz = -D / 2 + (j + 0.5) * td
            wx = cx + lx * c + lz * s
            wz = cz - lx * s + lz * c
            y0, glx, glz, sp = ground_plane(d, wx, wz, tw, td, ry)
            out.append((wx, wz, tw, td, y0, glx, glz))
            worst = max(worst, sp)
    return out, worst


def ground_tiles(d: Drawing, cx: float, cz: float, W: float, D: float, ry: float = 0.0):
    """R2: ([(x, z, w, dd, y, gx, gz)], spread). The whole footprint as ONE
    sub-block when the ground under it is planar (spread <= 1 m); otherwise
    ceil(W/25) x ceil(D/25) tiles, halved again until every tile is planar,
    never more than 64."""
    y0, glx, glz, spread = ground_plane(d, cx, cz, W, D, ry)
    if spread <= FLAT_M:
        return [(cx, cz, W, D, y0, glx, glz)], spread
    side = int(math.isqrt(MAX_TILES))
    nx = max(1, min(side, int(math.ceil(W / TILE_M))))
    nz = max(1, min(side, int(math.ceil(D / TILE_M))))
    while True:
        out, worst = _lattice(d, cx, cz, W, D, ry, nx, nz)
        if worst <= FLAT_M or (2 * nx) * (2 * nz) > MAX_TILES:
            return out, worst
        nx, nz = nx * 2, nz * 2


def ground_range(d: Drawing, cx: float, cz: float, W: float, D: float, n: int = 5):
    """(low, high) of the ground under a W x D footprint. Level water needs the
    real range, not ground_plane's deviation from a plane — a planar hillside has
    no spread at all and is still no place for a pond."""
    lo = hi = None
    for j in range(n):
        for i in range(n):
            y = ground_height(d, cx - W / 2 + (i + 0.5) * W / n, cz - D / 2 + (j + 0.5) * D / n)
            lo = y if lo is None else min(lo, y)
            hi = y if hi is None else max(hi, y)
    return (lo or 0.0), (hi or 0.0)


def _level_refusal(cf: str, ct: str, rise: float) -> str:
    return (
        f'refused: the ground under {cf}..{ct} rises {rise:.1f} m — water lies level; flatten_pad it, '
        'put it lower on the slope, or use add_stream/add_river for water that flows'
    )


def contour_direction(d: Drawing, cx: float, cz: float):
    """(direction, note) for a caller who named none: rows run ALONG the contour,
    which is across the steeper of the two ground gradients."""
    _y, gx, gz = ground_at(d, cx, cz)
    if max(abs(gx), abs(gz)) < CONTOUR_MIN:
        return 'x', ''
    if abs(gz) >= abs(gx):
        return 'x', 'rows run east-west along the contour of the slope'
    return 'z', 'rows run north-south along the contour of the slope'


# ── helpers ─────────────────────────────────────────────────────────────────
def _mat(m, default='mat_grass'):
    return m if m in MATERIALS else default


def _block(cell_from, cell_to):
    xmin, zmin, xmax, zmax = block_bounds(cell_from, cell_to)
    return xmin, zmin, xmax, zmax, xmax - xmin, zmax - zmin


def _too_big(W, D):
    if W > MAX_SIDE or D > MAX_SIDE:
        return f'refused: {W:g} x {D:g} m is too big for one field — {MAX_SIDE:g} m a side is the limit'
    return ''


def _room(d: Drawing, n: int):
    if len(d.objs) + n > MAX_OBJECTS:
        return f'refused: that is {n} object(s) past the {MAX_OBJECTS} ceiling'
    return ''


def _plot(direction, W, D):
    """direction names the axis the rows RUN along. 'x' leaves the plot alone;
    'z' turns the record a quarter turn, which swaps its w and d."""
    return (W, D, 0) if direction == 'x' else (D, W, 90)


def _names(cell_from, cell_to):
    return cell_name(*parse_cell(cell_from)), cell_name(*parse_cell(cell_to))


def _has_base(base_height) -> bool:
    return base_height is not None and base_height != ''


def _place(d: Drawing, cx: float, cz: float, W: float, D: float, base_height):
    """R1 + R2: the sub-blocks one draped record each covers. An explicit
    base_height is a level terrace — one record, no drape, no tiling."""
    if _has_base(base_height):
        return [(cx, cz, W, D, _num(base_height, 0.0), 0.0, 0.0)], 0.0
    return ground_tiles(d, cx, cz, W, D)


def _stood_on(base_height, tiles) -> str:
    y = tiles[0][4]
    if _has_base(base_height):
        return f', standing on {y:g} m' if y else ''
    if abs(y) < 0.005 and all(abs(t[5]) < 1e-6 and abs(t[6]) < 1e-6 for t in tiles):
        return ''
    lo = min(t[4] for t in tiles)
    hi = max(t[4] for t in tiles)
    if hi - lo > 0.05:
        return f', draped on the ground from {lo:.1f} to {hi:.1f} m'
    return f', draped on the ground at {y:.2f} m'


def _tiled(tiles) -> str:
    return f'in {len(tiles)} tiles over the uneven ground' if len(tiles) > 1 else ''


def _join(head: str, bits: list, tail: str) -> str:
    bits = [b for b in bits if b]
    return head + (', ' + ', '.join(bits) if bits else '') + tail


# ── tools ───────────────────────────────────────────────────────────────────
def t_add_field(
    d: Drawing,
    a,
    cell_from,
    cell_to,
    crop='wheat',
    direction=None,
    spacing=None,
    base_height=None,
    material='',
    name='',
):
    cr = str(crop or 'wheat').strip().lower()
    if cr not in CROPS:
        return 'refused: crop must be one of ' + ', '.join(CROP_NAMES)
    dr = None if direction in (None, '') else str(direction).strip().lower()
    if dr is not None and dr not in ('x', 'z'):
        return "refused: direction must be 'x' or 'z' — it names the axis the rows run along"
    xmin, zmin, xmax, zmax, W, D = _block(cell_from, cell_to)
    big = _too_big(W, D)
    if big:
        return big
    code, hgt, defsp = CROPS[cr]
    sp = defsp if spacing is None else _num(spacing, defsp)
    if sp < 0.1:
        return 'refused: rows must be at least 0.1 m apart'
    cx, cz = (xmin + xmax) / 2, (zmin + zmax) / 2
    note = ''
    if dr is None:
        dr, note = contour_direction(d, cx, cz)
    w, dd, ang = _plot(dr, W, D)
    n = row_count(dd, sp)
    if n > MAX_ROWS:
        return (
            f'refused: {sp:g} m rows over {dd:g} m is {n} rows — raise spacing, '
            f'{MAX_ROWS} rows is the limit for one field'
        )
    tiles, _spread = _place(d, cx, cz, W, D, base_height)
    full = _room(d, len(tiles))
    if full:
        return full
    cf, ct = _names(cell_from, cell_to)
    grp = name or 'fields'
    ids = []
    for k, (tx, tz, tw, td, ty, glx, glz) in enumerate(tiles):
        pw, pd, _ang = _plot(dr, tw, td)
        o = d.new(
            'crop_field',
            {
                'w': round(pw, 4),
                'd': round(pd, 4),
                'crop': code,
                'spacing': round(sp, 4),
                'h': round(hgt, 3),
                'dir': ang,
                'gx': round(glx, 4),
                'gz': round(glz, 4),
            },
            tx,
            tz,
            ty,
            0.0,
            _mat(material, 'mat_soil'),
            name=(name or f'{cr} field {cf}-{ct}') + (f' {k + 1}' if len(tiles) > 1 else ''),
            grp=grp,
        )
        ids.append(o['id'])
    span = ids[0] if len(ids) == 1 else f'{ids[0]}..{ids[-1]}'
    head = (
        f'sowed {cr} field {span} over {cf}..{ct}: {W:g} x {D:g} m, {n} rows {sp:g} m apart '
        f'running along {dr}, {hgt:g} m tall'
    )
    return _join(head, [_tiled(tiles), note], _stood_on(base_height, tiles) + f', group "{grp}"')


def t_add_meadow(d: Drawing, a, cell_from, cell_to, flowers=200, seed=1, base_height=None, material='', name=''):
    xmin, zmin, xmax, zmax, W, D = _block(cell_from, cell_to)
    big = _too_big(W, D)
    if big:
        return big
    nf = int(_num(flowers, 200))
    if nf < 0:
        return 'refused: flowers cannot be negative'
    if nf > MAX_FLOWERS:
        return f'refused: {nf} flowers is past the {MAX_FLOWERS} a meadow may carry'
    sd = _num(seed, 1)
    cx, cz = (xmin + xmax) / 2, (zmin + zmax) / 2
    tiles, _spread = _place(d, cx, cz, W, D, base_height)
    full = _room(d, len(tiles))
    if full:
        return full
    cf, ct = _names(cell_from, cell_to)
    grp = name or 'meadows'
    ids = _sow_meadow(d, tiles, nf, sd, W, D, _mat(material, 'mat_grass'), name or f'meadow {cf}-{ct}', grp)
    span = ids[0] if len(ids) == 1 else f'{ids[0]}..{ids[-1]}'
    head = f'laid meadow {span} over {cf}..{ct}: {W:g} x {D:g} m of grass with {nf} flowers, seed {sd:g}'
    return _join(head, [_tiled(tiles)], _stood_on(base_height, tiles) + f', group "{grp}"')


def _sow_meadow(d: Drawing, tiles, nf, sd, W, D, mat, base_name, grp):
    """One meadow record per tile; the flowers are shared out by area and each
    tile gets its own seed so the patches do not repeat."""
    ids = []
    area = max(1e-9, W * D)
    for k, (tx, tz, tw, td, ty, glx, glz) in enumerate(tiles):
        share = nf if len(tiles) == 1 else int(round(nf * (tw * td) / area))
        o = d.new(
            'meadow',
            {
                'w': round(tw, 4),
                'd': round(td, 4),
                'flowers': share,
                'seed': sd if len(tiles) == 1 else sd + k,
                'h': 0.25,
                'gx': round(glx, 4),
                'gz': round(glz, 4),
            },
            tx,
            tz,
            ty,
            0.0,
            mat,
            name=base_name + (f' {k + 1}' if len(tiles) > 1 else ''),
            grp=grp,
        )
        ids.append(o['id'])
    return ids


def t_add_pasture(d: Drawing, a, cell_from, cell_to, fence_height=1.2, base_height=None, material='', name=''):
    """Grazing land: a meadow with no flowers, fenced on all four sides. The fence
    is the existing `fence` kind, one record a side, each sitting on the ground at
    its own centre and tilted (rz) to run downhill with the slope (R4)."""
    xmin, zmin, xmax, zmax, W, D = _block(cell_from, cell_to)
    big = _too_big(W, D)
    if big:
        return big
    fh = _num(fence_height, 1.2)
    if fh < 0.2 or fh > 4:
        return 'refused: a stock fence is between 0.2 and 4 m tall'
    if W < 1 or D < 1:
        return f'refused: {W:g} x {D:g} m is too small to fence as a pasture'
    cx, cz = (xmin + xmax) / 2, (zmin + zmax) / 2
    tiles, _spread = _place(d, cx, cz, W, D, base_height)
    full = _room(d, len(tiles) + 4)
    if full:
        return full
    cf, ct = _names(cell_from, cell_to)
    grp = name or f'pasture {cf}-{ct}'
    ids = _sow_meadow(d, tiles, 0, 1, W, D, _mat(material, 'mat_grass'), 'grazing', grp)
    ring = (
        ('north fence', W, cx, zmin, 0.0),
        ('south fence', W, cx, zmax, 0.0),
        ('west fence', D, xmin, cz, math.pi / 2),
        ('east fence', D, xmax, cz, math.pi / 2),
    )
    drops = []
    for label, L, x, z, ry in ring:
        ex, ez = L / 2 * math.cos(ry), -L / 2 * math.sin(ry)
        y0, y1 = ground_height(d, x - ex, z - ez), ground_height(d, x + ex, z + ez)
        o = d.new(
            'fence',
            {'len': round(L, 3), 'h': round(fh, 3), 'posts': max(2, int(L / 2.5) + 1), 'rails': 3, 't': 0.04},
            x,
            z,
            place_height(d, x, z, base_height),
            ry,
            'mat_timber',
            name=label,
            grp=grp,
        )
        if not _has_base(base_height) and L > 0.01:
            o['rz'] = round(math.atan((y1 - y0) / L), 6)
            if abs(y1 - y0) > 0.05:
                drops.append(abs(y1 - y0))
        ids.append(o['id'])
    head = (
        f'fenced pasture "{grp}" over {cf}..{ct}: {W:g} x {D:g} m of grazing grass {ids[0]}, '
        f'ringed by 4 fences {ids[-4]}..{ids[-1]} {fh:g} m tall ({W:g} m and {D:g} m long)'
    )
    slope = f'{len(drops)} of them running downhill, the steepest by {max(drops):.1f} m' if drops else ''
    return _join(head, [_tiled(tiles), slope], _stood_on(base_height, tiles))


def t_add_marsh(
    d: Drawing,
    a,
    cell_from,
    cell_to,
    reeds=150,
    seed=1,
    depth=0.4,
    reed_height=1.8,
    base_height=None,
    material='',
    name='',
):
    xmin, zmin, xmax, zmax, W, D = _block(cell_from, cell_to)
    big = _too_big(W, D)
    if big:
        return big
    nr = int(_num(reeds, 150))
    if nr < 0:
        return 'refused: reeds cannot be negative'
    if nr > MAX_REEDS:
        return f'refused: {nr} reeds is past the {MAX_REEDS} a marsh may carry'
    dep = _num(depth, 0.4)
    if dep < 0.1 or dep > 5:
        return 'refused: a marsh is between 0.1 and 5 m deep — deeper than that is a pond or a canal'
    rh = _num(reed_height, 1.8)
    if rh < REED_H[0] or rh > REED_H[1]:
        return f'refused: reeds are between {REED_H[0]:g} and {REED_H[1]:g} m tall'
    cf, ct = _names(cell_from, cell_to)
    cx, cz = (xmin + xmax) / 2, (zmin + zmax) / 2
    if _has_base(base_height):
        y = _num(base_height, 0.0)
    else:
        lo, hi = ground_range(d, cx, cz, W, D)
        if hi - lo > WATER_FLAT_M:
            return _level_refusal(cf, ct, hi - lo)
        y = round(ground_height(d, cx, cz), 4)
    full = _room(d, 1)
    if full:
        return full
    sd = _num(seed, 1)
    o = d.new(
        'marsh',
        {'w': round(W, 4), 'd': round(D, 4), 'depth': round(dep, 3), 'reeds': nr, 'seed': sd, 'reed_h': round(rh, 3)},
        cx,
        cz,
        y,
        0.0,
        _mat(material, 'mat_soil'),
        name=name or f'marsh {cf}-{ct}',
        grp=name or 'wetland',
    )
    return (
        f'flooded marsh {o["id"]} over {cf}..{ct}: {W:g} x {D:g} m, {dep:g} m deep with {nr} reeds '
        f'{rh:g} m tall, seed {sd:g}, lying level' + (f' on {y:g} m' if y else '') + f', group "{o["grp"]}"'
    )


def t_add_vineyard(
    d: Drawing,
    a,
    cell_from,
    cell_to,
    direction=None,
    row_spacing=2.5,
    height=1.8,
    base_height=None,
    material='',
    name='',
):
    dr = None if direction in (None, '') else str(direction).strip().lower()
    if dr is not None and dr not in ('x', 'z'):
        return "refused: direction must be 'x' or 'z' — it names the axis the rows run along"
    xmin, zmin, xmax, zmax, W, D = _block(cell_from, cell_to)
    big = _too_big(W, D)
    if big:
        return big
    rs = _num(row_spacing, 2.5)
    if rs < 0.5:
        return 'refused: vine rows must be at least 0.5 m apart'
    h = _num(height, 1.8)
    if h < VINE_H[0] or h > VINE_H[1]:
        return f'refused: a vine row is between {VINE_H[0]:g} and {VINE_H[1]:g} m tall — that is what a vineyard is'
    cx, cz = (xmin + xmax) / 2, (zmin + zmax) / 2
    note = ''
    if dr is None:
        dr, note = contour_direction(d, cx, cz)
    w, dd, ang = _plot(dr, W, D)
    n = row_count(dd, rs)
    if n > MAX_ROWS:
        return f'refused: {rs:g} m rows over {dd:g} m is {n} rows — raise row_spacing, {MAX_ROWS} is the limit'
    tiles, _spread = _place(d, cx, cz, W, D, base_height)
    full = _room(d, len(tiles))
    if full:
        return full
    cf, ct = _names(cell_from, cell_to)
    grp = name or 'vineyard'
    ids = []
    for k, (tx, tz, tw, td, ty, glx, glz) in enumerate(tiles):
        pw, pd, _ang = _plot(dr, tw, td)
        o = d.new(
            'vineyard',
            {
                'w': round(pw, 4),
                'd': round(pd, 4),
                'row_spacing': round(rs, 4),
                'h': round(h, 3),
                'dir': ang,
                'gx': round(glx, 4),
                'gz': round(glz, 4),
            },
            tx,
            tz,
            ty,
            0.0,
            _mat(material, 'mat_soil'),
            name=(name or f'vineyard {cf}-{ct}') + (f' {k + 1}' if len(tiles) > 1 else ''),
            grp=grp,
        )
        ids.append(o['id'])
    span = ids[0] if len(ids) == 1 else f'{ids[0]}..{ids[-1]}'
    head = (
        f'planted vineyard {span} over {cf}..{ct}: {W:g} x {D:g} m, {n} rows {rs:g} m apart along {dr}, '
        f'{post_count(w)} posts a row, {h:g} m tall'
    )
    return _join(head, [_tiled(tiles), note], _stood_on(base_height, tiles) + f', group "{grp}"')


def t_make_polder(
    d: Drawing, a, cell_from, cell_to, ditch_width=3.0, crop='grass', depth=1.2, base_height=None, material='', name=''
):
    """A field inset by the ditch, ringed by four canal reaches centred on the
    block edges — one polder, five records. The four ditches are LEVEL water, so
    the whole polder refuses ground that varies more than 0.5 m (R3)."""
    cr = str(crop or 'grass').strip().lower()
    if cr not in CROPS:
        return 'refused: crop must be one of ' + ', '.join(CROP_NAMES)
    xmin, zmin, xmax, zmax, W, D = _block(cell_from, cell_to)
    big = _too_big(W, D)
    if big:
        return big
    dw = _num(ditch_width, 3.0)
    if dw < 0.5 or dw > 60:
        return 'refused: a ditch is between 0.5 and 60 m wide'
    fw, fd = W - 2 * dw, D - 2 * dw
    if fw < 1 or fd < 1:
        return (
            f'refused: {dw:g} m ditches leave {fw:g} x {fd:g} m of field inside a {W:g} x {D:g} m block — '
            'use a bigger block or a narrower ditch'
        )
    dep = _num(depth, 1.2)
    if dep < 0.3 or dep > 20:
        return 'refused: a ditch is between 0.3 and 20 m deep'
    code, hgt, defsp = CROPS[cr]
    n = row_count(fd, defsp)
    if n > MAX_ROWS:
        return f'refused: {defsp:g} m rows over {fd:g} m is {n} rows — {MAX_ROWS} is the limit for one field'
    cf, ct = _names(cell_from, cell_to)
    cx, cz = (xmin + xmax) / 2, (zmin + zmax) / 2
    if _has_base(base_height):
        y = _num(base_height, 0.0)
    else:
        lo, hi = ground_range(d, cx, cz, W, D)
        if hi - lo > WATER_FLAT_M:
            return _level_refusal(cf, ct, hi - lo)
        y = round(ground_height(d, cx, cz), 4)
    full = _room(d, 5)
    if full:
        return full
    grp = name or f'polder {cf}-{ct}'
    field = d.new(
        'crop_field',
        {
            'w': round(fw, 4),
            'd': round(fd, 4),
            'crop': code,
            'spacing': round(defsp, 4),
            'h': round(hgt, 3),
            'dir': 0,
            'gx': 0,
            'gz': 0,
        },
        cx,
        cz,
        y,
        0.0,
        _mat(material, 'mat_soil'),
        name=f'{cr} field',
        grp=grp,
    )
    ids = [field['id']]
    ring = (
        ('north ditch', round(W, 4), cx, zmin, 0.0),
        ('south ditch', round(W, 4), cx, zmax, 0.0),
        ('west ditch', round(D, 4), xmin, cz, math.pi / 2),
        ('east ditch', round(D, 4), xmax, cz, math.pi / 2),
    )
    for label, L, x, z, ry in ring:
        o = d.new(
            'canal', {'len': L, 'w': round(dw, 3), 'depth': round(dep, 3)}, x, z, y, ry, 'mat_soil', name=label, grp=grp
        )
        ids.append(o['id'])
    return (
        f'drained polder "{grp}" over {cf}..{ct}: {W:g} x {D:g} m — {cr} field {ids[0]} '
        f'{fw:g} x {fd:g} m with {n} rows, ringed by 4 level ditches {ids[1]}..{ids[-1]} '
        f'{dw:g} m wide and {dep:g} m deep ({W:g} m and {D:g} m long)' + (f', standing on {y:g} m' if y else '')
    )


_CELL = {'type': 'string'}

TOOLS = [
    (
        {
            'name': 'add_field',
            'description': "One farmed field over a block of cells — a soil plate with rows of crop, ONE object however many rows it carries (several when the ground under it is broken). crop 'wheat', 'corn', 'potatoes', 'grass' (hay) or 'tulips' (the striped red/white/yellow Dutch bulb field). It lands on the ground and drapes over it; leave direction out and the rows follow the contour, or name the axis they run along.",
            'input_schema': {
                'type': 'object',
                'properties': {
                    'cell_from': _CELL,
                    'cell_to': _CELL,
                    'crop': {'type': 'string', 'enum': list(CROP_NAMES)},
                    'direction': {'type': 'string', 'enum': ['x', 'z']},
                    'spacing': {'type': 'number'},
                    'base_height': {'type': 'number'},
                    'material': {'type': 'string', 'enum': MATERIALS},
                    'name': {'type': 'string'},
                },
                'required': ['cell_from', 'cell_to'],
            },
        },
        t_add_field,
    ),
    (
        {
            'name': 'add_meadow',
            'description': 'Rough grass over a block of cells with `flowers` flower heads scattered by the seed — a paddock, a wildflower meadow, the grass of a park. It drapes over the ground under it. Same seed = same meadow.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'cell_from': _CELL,
                    'cell_to': _CELL,
                    'flowers': {'type': 'integer'},
                    'seed': {'type': 'number'},
                    'base_height': {'type': 'number'},
                    'material': {'type': 'string', 'enum': MATERIALS},
                    'name': {'type': 'string'},
                },
                'required': ['cell_from', 'cell_to'],
            },
        },
        t_add_meadow,
    ),
    (
        {
            'name': 'add_pasture',
            'description': 'Grazing land over a block of cells: bare grass with no flowers, fenced on all four sides with the timber fence, each fence sitting on the ground and running downhill with it. Use when the user asks for a paddock, a pasture, a fenced field for animals.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'cell_from': _CELL,
                    'cell_to': _CELL,
                    'fence_height': {'type': 'number'},
                    'base_height': {'type': 'number'},
                    'material': {'type': 'string', 'enum': MATERIALS},
                    'name': {'type': 'string'},
                },
                'required': ['cell_from', 'cell_to'],
            },
        },
        t_add_pasture,
    ),
    (
        {
            'name': 'add_marsh',
            'description': 'Shallow standing water over a block of cells with reeds growing out of it: the basin is `depth` deep, the surface sits just under the ground. Water lies LEVEL, so it refuses ground that varies more than 0.5 m — flatten_pad first. Use for wetland, a fen, the edge of a lake.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'cell_from': _CELL,
                    'cell_to': _CELL,
                    'reeds': {'type': 'integer'},
                    'seed': {'type': 'number'},
                    'depth': {'type': 'number'},
                    'reed_height': {'type': 'number'},
                    'base_height': {'type': 'number'},
                    'material': {'type': 'string', 'enum': MATERIALS},
                    'name': {'type': 'string'},
                },
                'required': ['cell_from', 'cell_to'],
            },
        },
        t_add_marsh,
    ),
    (
        {
            'name': 'add_vineyard',
            'description': 'Vines in rows over a block of cells: a timber post every 6 m along each row and a continuous vine mass on the wire, 1.6-2.0 m tall. It drapes over the ground; leave direction out and the rows follow the contour of the slope, row_spacing is the gap between them.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'cell_from': _CELL,
                    'cell_to': _CELL,
                    'direction': {'type': 'string', 'enum': ['x', 'z']},
                    'row_spacing': {'type': 'number'},
                    'height': {'type': 'number'},
                    'base_height': {'type': 'number'},
                    'material': {'type': 'string', 'enum': MATERIALS},
                    'name': {'type': 'string'},
                },
                'required': ['cell_from', 'cell_to'],
            },
        },
        t_add_vineyard,
    ),
    (
        {
            'name': 'make_polder',
            'description': 'A whole polder in one call: one field inset by the ditch width over the block, ringed by four water-filled ditches whose centres sit on the block edges. The ditches are level water, so it refuses uneven ground. Use when the user asks for a polder, reclaimed land, fields with ditches around them.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'cell_from': _CELL,
                    'cell_to': _CELL,
                    'ditch_width': {'type': 'number'},
                    'crop': {'type': 'string', 'enum': list(CROP_NAMES)},
                    'depth': {'type': 'number'},
                    'base_height': {'type': 'number'},
                    'material': {'type': 'string', 'enum': MATERIALS},
                    'name': {'type': 'string'},
                },
                'required': ['cell_from', 'cell_to'],
            },
        },
        t_make_polder,
    ),
]

EXAMPLES = [
    {
        'ask': 'a wheat field from C4 to L13',
        'calls': [{'tool': 'add_field', 'args': {'cell_from': 'C4', 'cell_to': 'L13', 'crop': 'wheat'}}],
    },
    {
        'ask': 'tulip fields north of the farm, A20 to AH45, stripes running north-south',
        'calls': [
            {'tool': 'add_field', 'args': {'cell_from': 'A20', 'cell_to': 'AH45', 'crop': 'tulips', 'direction': 'z'}}
        ],
    },
    {
        'ask': 'plant the hillside D30 to X50 with vines',
        'calls': [{'tool': 'add_vineyard', 'args': {'cell_from': 'D30', 'cell_to': 'X50'}}],
    },
    {
        'ask': 'make the block D30 to X50 a polder with 4 m ditches and grass',
        'calls': [
            {'tool': 'make_polder', 'args': {'cell_from': 'D30', 'cell_to': 'X50', 'ditch_width': 4, 'crop': 'grass'}}
        ],
    },
    {
        'ask': 'a wildflower meadow behind the house, E10 to N19, and marshy ground along the stream P10 to T19',
        'calls': [
            {'tool': 'add_meadow', 'args': {'cell_from': 'E10', 'cell_to': 'N19', 'flowers': 400}},
            {'tool': 'add_marsh', 'args': {'cell_from': 'P10', 'cell_to': 'T19', 'reeds': 300}},
        ],
    },
    {
        'ask': 'a vineyard on the terrace at 3 m, F40 to R55, rows 2.2 m apart',
        'calls': [
            {
                'tool': 'add_vineyard',
                'args': {'cell_from': 'F40', 'cell_to': 'R55', 'row_spacing': 2.2, 'base_height': 3},
            }
        ],
    },
    {
        'ask': 'a hay meadow with no flowers on B60 to K70',
        'calls': [{'tool': 'add_meadow', 'args': {'cell_from': 'B60', 'cell_to': 'K70', 'flowers': 0}}],
    },
    {
        'ask': 'fence B60 to K70 as a paddock for the horses',
        'calls': [{'tool': 'add_pasture', 'args': {'cell_from': 'B60', 'cell_to': 'K70'}}],
    },
]
