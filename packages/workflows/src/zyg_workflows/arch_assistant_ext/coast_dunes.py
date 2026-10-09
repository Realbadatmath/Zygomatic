# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""coast_dunes — the shoreline: sea, beaches, dune fields, islands, breakwaters.

The noise below is the SAME arithmetic as arch_ext/coast_dunes.js and
arch_blender_ext/coast_dunes.py (all three copied from terrain's). It lives
here as well so the assistant — and the test — can say how big a coast record
really is without rendering it:

  sea_span(depth, wave, res, seed)   the sea record's height, bed to crest
  dune_scale(res, seed)              the factor the raw ridged field is
                                     multiplied by so its peak lands on h
  island_span(r, wobble, beach, seed, seg)  the island's width on the plan
  beach_scale(seed)                  the same normalisation for the beach wedge

GROUND (2026-09-07). A beach, a dune field, an island and a breakwater are all
things you can stand on, so this family exports HEIGHTS for them and everything
placed on them lands on them. The SEA is deliberately NOT ground — its entry is
None — because water is not a surface: a boat floats on it, a house does not
stand on it. That is also why an island dropped into a sea at y=0 stays at 0.

v3 SCULPTED GROUND (2026-09-07). When the drawing has a `ground` record the
coast stops being solids standing on the land and becomes the land:
  add_sea    -> water_v3's fill_sea (a sculpt_shelf bed under a water_plane)
  add_dunes  -> one sculpt_dunes (the ground colours its footprint sand)
  add_beach  -> per reach a sculpt_flat at the water level + BEACH_RISE with a
                feather 0.6 x the strip width (that reads as a beach running
                down to the water) PLUS a sculpt_shelf of depth 0 over the same
                strip: depth 0 moves no height, it is there purely because the
                ground's colour function treats a shelf footprint as SAND.
  add_island -> a low wide sculpt_peak plus that same depth-0 sand shelf round it
  add_breakwater keeps its solid: a rubble mound is an object, not a landform.
The R7 ranges are checked FIRST on both paths, base_height does not apply to a
sculpted ground, and every reply says which path it took.

`make_coast` is a recipe, not a kind: it calls the tool functions below, so a
shoreline laid in one call is made of exactly the same records a patient user
would have drawn by hand — sculpts on a sculpted ground, solids without one.
"""

from __future__ import annotations

import functools
import math

from zyg_workflows import arch_assistant as _A
from zyg_workflows.arch_assistant import (
    Drawing,
    parse_cell,
    cell_centre,
    cell_name,
    block_bounds,
    MATERIALS,
    MAX_OBJECTS,
    _num,
)

KINDS = {
    'sea': {'w': 200, 'd': 200, 'depth': 6, 'wave': 0.15, 'seed': 1, 'res': 32},
    'beach': {'len': 60, 'w': 25, 'h': 2, 'seed': 1},
    'dune_field': {'w': 120, 'd': 60, 'h': 8, 'seed': 1, 'res': 40, 'dir': 0},
    'island': {'r': 40, 'h': 6, 'wobble': 0.3, 'beach': 6, 'seed': 1, 'seg': 48, 'rings': 10},
    'breakwater': {'len': 60, 'w': 8, 'h': 3},
}
OPENINGS: list = []

PROMPT = (
    'Coast and dunes: everything lands on the ground under it; base_height overrides. With a sculpted '
    'ground add_sea/add_beach/add_dunes/add_island shape the LAND itself — sculpts plus a water surface, '
    'so a bay is a bay — and base_height does not apply; without one they draw the old solids. '
    'add_sea(cell_from, cell_to, depth, wave) lays the water LEVEL — draw the sea FIRST; on unsculpted '
    'ground it refuses a bed varying over 0.5 m, so flatten_pad it. Water is not ground. '
    'add_beach(cells, width, height) runs a sand strip (strand) between each pair of cells, rising '
    '0.5-4 m away from the water with the sea always on the LEFT of the walk. add_dunes(cell_from, '
    'cell_to, height) fills a block with sand ridges (duin) across its shorter side, 3-25 m tall (Dutch '
    'dunes are 8-15 m). add_island(centre, radius, height) is a 1-40 m hill with a sand ring — put it IN '
    'the sea. add_breakwater(cells, height, width) is a 1-6 m rubble mound (strekdam) and always stays a '
    'solid. make_coast(cell_from, cell_to, sea_side) draws the whole shore: sea 40%, beach 20%, dunes 40%.'
)

_SIDES = ('north', 'south', 'east', 'west')

# R7 real sizes — absolute metres, never scaled with the block.
DUNE_H = (3.0, 25.0)  # a dune belt: 3 to 25 m (Dutch dunes 8-15)
BEACH_H = (0.5, 4.0)  # the rise from the water edge to the back crest
ISLAND_H = (1.0, 40.0)  # the summit above the water
BREAKWATER_H = (1.0, 6.0)  # how far the mound stands out of the water
LEVEL_TOL = 0.5  # R3: the ground a sea may sit on may vary this much


# ── the shared lattice and looks (identical in the JS and the Blender copies) ─
BX, BZ = 24, 20  # the beach wedge's lattice: along the shore, across it
WET = 0.15  # wet sand: the 15 % of the width at the water edge
WET_ROWS = round(BZ * WET)  # 3 of the 20 rows — exactly 15 %
MARRAM = 0.70  # marram grass on every dune face above 70 % of h


# ── the shared noise (identical in the JS and the Blender copies) ────────────
def _hash(ix: float, iy: float, seed: float) -> float:
    v = math.sin(ix * 127.1 + iy * 311.7 + seed * 74.7) * 43758.5453
    return v - math.floor(v)


def value_noise(u: float, v: float, seed: float) -> float:
    ix, iy = math.floor(u), math.floor(v)
    fx, fy = u - ix, v - iy
    a = _hash(ix, iy, seed)
    b = _hash(ix + 1, iy, seed)
    c = _hash(ix, iy + 1, seed)
    e = _hash(ix + 1, iy + 1, seed)
    return a + (b - a) * fx + (c - a) * fy + (a - b - c + e) * fx * fy


def sea_span(depth: float = 6.0, wave: float = 0.15, res: int = 32, seed: float = 1) -> float:
    """Height of a `sea` record's bounding box: the highest wave crest
    (-0.3 + wave*(2v-1)) down to the underside of the 0.2 m bed at -depth."""
    res = max(2, min(96, int(res)))
    hi = max(value_noise(i / res * 8, j / res * 8, seed) for j in range(res + 1) for i in range(res + 1))
    return (-0.3 + wave * (2 * hi - 1)) - (-depth - 0.1)


@functools.lru_cache(maxsize=256)
def dune_scale(res: int = 40, seed: float = 1) -> float:
    """The factor the raw ridged field 1-|2v-1| is multiplied by so that its
    tallest crest lands exactly on the record's h (i.e. 1 / the lattice max)."""
    res = max(2, min(96, int(res)))
    mx = max(
        1 - abs(2 * value_noise(i / res * 2.5, j / res * 7, seed) - 1) for j in range(res + 1) for i in range(res + 1)
    )
    return 1.0 / max(mx, 1e-9)


@functools.lru_cache(maxsize=256)
def beach_scale(seed: float = 1) -> float:
    """The same normalisation for the beach wedge: 1 / the BX x BZ lattice's
    maximum of profile * along-shore swell, so raw * h * beach_scale tops out
    at exactly h. The profile is 1 at the back crest, so this is really
    1 / max(swell), but it is computed over the whole lattice to stay a
    line-for-line copy of the two geometry builders."""
    mx = 1e-9
    for j in range(BZ + 1):
        prof = 0.5 * (1 - math.cos(math.pi * j / BZ))
        for i in range(BX + 1):
            v = prof * (1 - 0.15 * (2 * value_noise(i / BX * 3, 4.5, seed) - 1))
            if v > mx:
                mx = v
    return 1.0 / mx


@functools.lru_cache(maxsize=256)
def _rim(r: float, wobble: float, seed: float, seg: int) -> tuple:
    return tuple(
        r
        * (
            1
            + wobble
            * (
                2 * value_noise(math.cos(2 * math.pi * i / seg) * 2 + 2, math.sin(2 * math.pi * i / seg) * 2 + 2, seed)
                - 1
            )
        )
        for i in range(seg)
    )


def island_rim(r: float = 40.0, wobble: float = 0.3, seed: float = 1, seg: int = 48) -> list:
    """The shoreline radius at each of the `seg` sampled angles."""
    return list(_rim(r, wobble, seed, max(8, min(128, int(seg)))))


def island_span(r: float = 40.0, wobble: float = 0.3, beach: float = 6.0, seed: float = 1, seg: int = 48) -> tuple:
    """(x, z) size of an `island` record on the plan — the outer edge of the
    sand ring, which is what the bounding box sees."""
    R = island_rim(r, wobble, seed, max(8, min(128, int(seg))))
    n = len(R)
    xs = [(R[i] + beach) * math.cos(2 * math.pi * i / n) for i in range(n)]
    zs = [(R[i] + beach) * math.sin(2 * math.pi * i / n) for i in range(n)]
    return max(xs) - min(xs), max(zs) - min(zs)


def _mat(m, default='mat_sand'):
    return m if m in MATERIALS else default


def _res_for(w: float, d: float, lo: int = 8, hi: int = 64) -> int:
    return max(lo, min(hi, int(round(max(w, d) / 3.0))))


def _cells_ok(cells) -> bool:
    return isinstance(cells, (list, tuple)) and len(cells) >= 2


# ── ground heights (the seam, 2026-09-07) ───────────────────────────────────
# fn(p, lx, lz) -> metres above the record's base at a LOCAL plan point, or None
# outside the footprint. The same arithmetic as the geometry in the .js and the
# Blender copy, so a thing placed here lands exactly where it is drawn.
def h_beach(p, lx, lz):
    """The sand wedge: 0 at the water edge (local -Z), h at the back crest
    (local +Z), with the along-shore swell — the continuous form of the
    BX x BZ lattice both builders walk."""
    L = max(1.0, _num(p.get('len'), 60.0))
    w = max(1.0, _num(p.get('w'), 25.0))
    h = max(0.05, _num(p.get('h'), 2.0))
    seed = _num(p.get('seed'), 1)
    if abs(lx) > L / 2 + 1e-9 or abs(lz) > w / 2 + 1e-9:
        return None
    prof = 0.5 * (1 - math.cos(math.pi * (lz + w / 2) / w))
    amp = 1 - 0.15 * (2 * value_noise((lx + L / 2) / L * 3, 4.5, seed) - 1)
    return prof * amp * h * beach_scale(seed)


def h_dune_field(p, lx, lz):
    """The ridged lattice, normalised by dune_scale so the tallest crest is h.
    `dir` turns the geometry on the plan, so the query point is turned back."""
    w = max(1.0, _num(p.get('w'), 120.0))
    dd = max(1.0, _num(p.get('d'), 60.0))
    h = max(0.05, _num(p.get('h'), 8.0))
    seed = _num(p.get('seed'), 1)
    res = max(2, min(96, int(round(_num(p.get('res'), 40)))))
    a = math.radians(_num(p.get('dir'), 0.0))
    c, s = math.cos(a), math.sin(a)
    x0 = lx * c - lz * s  # undo the geometry's rotateY(dir)
    z0 = lx * s + lz * c
    if abs(x0) > w / 2 + 1e-9 or abs(z0) > dd / 2 + 1e-9:
        return None
    u = (x0 + w / 2) / w * 2.5
    v = (z0 + dd / 2) / dd * 7.0
    return h * dune_scale(res, seed) * (1 - abs(2 * value_noise(u, v, seed) - 1))


def h_island(p, lx, lz):
    """The hill (h at the middle falling to 0.3 at the wandering rim) and then
    the sand ring, 0.3 down to 0 over `beach` metres."""
    r = max(1.0, _num(p.get('r'), 40.0))
    h = max(0.5, _num(p.get('h'), 6.0))
    wob = max(0.0, min(0.9, _num(p.get('wobble'), 0.3)))
    bch = max(0.2, _num(p.get('beach'), 6.0))
    seed = _num(p.get('seed'), 1)
    seg = max(8, min(128, int(round(_num(p.get('seg'), 48)))))
    R = _rim(r, wob, seed, seg)
    t = (math.atan2(lz, lx) % (2 * math.pi)) / (2 * math.pi) * seg
    i0 = int(math.floor(t)) % seg
    rr = R[i0] + (R[(i0 + 1) % seg] - R[i0]) * (t - math.floor(t))
    rad = math.hypot(lx, lz)
    if rad <= rr:
        return 0.3 + (h - 0.3) * 0.5 * (1 + math.cos(math.pi * (rad / rr if rr > 1e-9 else 0.0)))
    if rad <= rr + bch:
        return 0.3 * (1 - (rad - rr) / bch)
    return None


def h_breakwater(p, lx, lz):
    """The trapezoid mound: w at the base, w/3 flat on the crest at h."""
    L = max(1.0, _num(p.get('len'), 60.0))
    w = max(0.5, _num(p.get('w'), 8.0))
    h = max(0.2, _num(p.get('h'), 3.0))
    if abs(lx) > L / 2 + 1e-9 or abs(lz) > w / 2 + 1e-9:
        return None
    top = w / 6.0
    if abs(lz) <= top:
        return h
    return h * (w / 2 - abs(lz)) / (w / 2 - top)


# The sea is NOT ground: water is not a surface anything stands on. Its None
# entry is the statement, not an omission — ground_height() skips it.
HEIGHTS = {'sea': None, 'beach': h_beach, 'dune_field': h_dune_field, 'island': h_island, 'breakwater': h_breakwater}


# ── the v3 seam ─────────────────────────────────────────────────────────────
BEACH_RISE = 0.5  # how far the beach pad sits above the ground's water level
BEACH_FEATHER = 0.6  # the pad's feather as a fraction of the strip width. s_flat
# clamps a feather to half the side, so 0.6 * w reaches that
# clamp: the pad has no flat middle at all, it is all ramp.
ISLAND_RUG = 0.25  # a sea island is a soft dome, not a rocky summit


def the_ground(d):
    """The drawing's one `ground` record, or None. A hidden ground is no ground:
    hiding it in the outliner puts every tool back on the old solid path."""
    for o in getattr(d, 'objs', None) or ():
        if o.get('kind') == 'ground' and not o.get('hidden'):
            return o
    return None


def _water_tool(name: str):
    """water_v3's tool function, or None if that family is not installed.
    load_extensions() walks arch_assistant_ext/ alphabetically, so water_v3 is
    NOT in EXT_MODULES while this module is imported — look it up at call time."""
    mod = _A.EXT_MODULES.get('water_v3')
    return getattr(mod, name, None) if mod else None


def _given(base_height) -> bool:
    return not (base_height is None or base_height == '')


def _bh_note(base_height) -> str:
    return ' (base_height does not apply to a sculpted ground)' if _given(base_height) else ''


def _sculpt(d, kind, p, x, z, nm, ry=0.0):
    """A sculpt record, exactly as ground_v3 writes one: y=0 (field_at adds the
    record's own y to the land, so a bed at ground height would LIFT it first),
    mat_soil, and the 'ground sculpts' group so the outliner keeps them together."""
    return d.new(kind, p, x, z, 0.0, ry, 'mat_soil', name=nm, grp='ground sculpts')


def water_level_of(g) -> float:
    """The ground record's own water line — the height the beach is measured from."""
    return _num((g.get('p') or {}).get('water_h'), -0.15)


def _ground_span(d, cx: float, cz: float, W: float, D: float, n: int = 5) -> tuple:
    """(lowest, highest) ground under a W x D footprint centred on (cx, cz),
    sampled on an n x n lattice. R3 uses the difference: water lies level."""
    vals = [
        _A.ground_height(d, cx - W / 2 + (i + 0.5) * W / n, cz - D / 2 + (j + 0.5) * D / n)
        for j in range(n)
        for i in range(n)
    ]
    return min(vals), max(vals)


def _reach_ground(d, pts: list, base_height) -> list:
    """R4, for a chain of linear records: the ground at every cell in the walk,
    read BEFORE anything is drawn, so strip 2 does not climb onto strip 1."""
    if base_height is not None and base_height != '':
        return [_num(base_height, 0.0)] * len(pts)
    return [_A.ground_height(d, x, z) for x, z in pts]


# ── tools ───────────────────────────────────────────────────────────────────
def t_add_sea(d: Drawing, a, cell_from, cell_to, depth=6.0, wave=0.15, seed=1, base_height=None, material='', name=''):
    xmin, zmin, xmax, zmax = block_bounds(cell_from, cell_to)
    W, D = xmax - xmin, zmax - zmin
    if W > 2000 or D > 2000:
        return f'refused: {W:g} x {D:g} m is too big for one sea — 2000 m a side is the limit'
    dep = _num(depth, 6.0)
    if dep <= 0 or dep > 200:
        return 'refused: depth must be between 0 and 200 m'
    wv = _num(wave, 0.15)
    if wv < 0 or wv > 5:
        return 'refused: wave must be between 0 and 5 m'
    sd = _num(seed, 1)
    # v3: the ranges above are checked FIRST, then water_v3 dishes the bed out of
    # the one ground — a sea that is the land, so the shore is a real shore
    if the_ground(d) is not None:
        fill = _water_tool('t_fill_sea')
        if fill is not None:
            txt = fill(d, {}, cell_from=cell_from, cell_to=cell_to, depth=dep, wave=wv, seed=sd, name=name or 'sea')
            if txt.startswith('refused'):
                return txt
            return (
                txt + ' The ground is sculpted, so this sea is a sculpt_shelf dished into the land '
                'under a water_plane, not a solid `sea` record — the shelf footprint also reads as '
                'sand — and no level check is needed'
                + _bh_note(base_height)
                + ('; material does not apply to a dished bed' if material else '')
                + '.'
            )
    if len(d.objs) + 1 > MAX_OBJECTS:
        return f'refused: the drawing is at the {MAX_OBJECTS} object ceiling'
    res = _res_for(W, D, 8, 64)
    cf, ct = cell_name(*parse_cell(cell_from)), cell_name(*parse_cell(cell_to))
    cx, cz = (xmin + xmax) / 2, (zmin + zmax) / 2
    # R3: a sea lies LEVEL. Refuse ground that will not hold a level surface.
    lo, hi = _ground_span(d, cx, cz, W, D)
    if hi - lo > LEVEL_TOL:
        return (
            f'refused: the ground under {cf}..{ct} rises {hi - lo:.1f} m — water lies level; '
            'flatten_pad it, put it lower on the slope, or use add_stream/add_river for '
            'water that flows'
        )
    y = _A.place_height(d, cx, cz, base_height)
    o = d.new(
        'sea',
        {'w': round(W, 4), 'd': round(D, 4), 'depth': round(dep, 3), 'wave': round(wv, 3), 'seed': sd, 'res': res},
        cx,
        cz,
        y,
        0.0,
        _mat(material, 'mat_water'),
        name=name or f'sea {cf}-{ct}',
        grp=name or 'coast',
    )
    return (
        f'laid sea {o["id"]} over {cf}..{ct}: {W:g} x {D:g} m, {dep:g} m deep, '
        f'{wv:g} m swell, seed {sd:g} — level at y={y:g}; water is not ground, so what '
        f'you put in it stands on the bed, not on the waves'
    )


def t_add_beach(d: Drawing, a, cells, width=25.0, height=2.0, seed=1, base_height=None, material='', name=''):
    if not _cells_ok(cells):
        return 'refused: give a list of at least two cells — one beach is drawn between each pair'
    w = _num(width, 25.0)
    if w < 2 or w > 500:
        return 'refused: width must be between 2 and 500 m (bank of sand, water edge to crest)'
    h = _num(height, 2.0)
    if h < BEACH_H[0] or h > BEACH_H[1]:
        return (
            f'refused: a beach rises {BEACH_H[0]:g} to {BEACH_H[1]:g} m from the water edge to its '
            f'back crest — {h:g} m is not a beach'
        )
    pts = [cell_centre(*parse_cell(c)) for c in cells]
    need = len(pts) - 1
    if len(d.objs) + need > MAX_OBJECTS:
        return f'refused: that is {need} objects past the {MAX_OBJECTS} ceiling'
    sd = _num(seed, 1)
    # v3: a beach is a PARAMETER of the ground, not a wedge on it. Per reach a
    # sculpt_flat pulls the land down to just above the water line with a feather
    # 0.6 x the strip width (all ramp, no plateau — that is what reads as a
    # beach), and a sculpt_shelf of depth 0 over the same strip changes nothing
    # about the height and everything about the colour: a shelf footprint is SAND.
    g = the_ground(d)
    if g is not None:
        if len(d.objs) + 2 * need > MAX_OBJECTS:
            return f'refused: that is {2 * need} objects past the {MAX_OBJECTS} ceiling'
        lvl = round(water_level_of(g) + BEACH_RISE, 4)
        fe = round(BEACH_FEATHER * w, 4)
        grp = name or 'beach'
        ids, total = [], 0.0
        for i in range(need):
            (x0, z0), (x1, z1) = pts[i], pts[i + 1]
            L = math.hypot(x1 - x0, z1 - z0)
            if L < 0.5:
                return f'refused: {cells[i]} and {cells[i + 1]} are the same cell — a beach needs two different cells'
            ry = math.atan2(-(z1 - z0), x1 - x0)
            cx, cz = (x0 + x1) / 2, (z0 + z1) / 2
            _sculpt(
                d,
                'sculpt_flat',
                {'w': round(L, 4), 'd': round(w, 4), 'level': lvl, 'feather': fe},
                cx,
                cz,
                f'{grp} strand {i + 1}',
                ry,
            )
            o = _sculpt(
                d,
                'sculpt_shelf',
                {'w': round(L, 4), 'd': round(w, 4), 'depth': 0, 'feather': 0},
                cx,
                cz,
                f'{grp} sand {i + 1}',
                ry,
            )
            ids.append(o['id'])
            total += L
        return (
            f'sculpted {need} beach strip(s) into the ground through '
            f'{", ".join(str(c) for c in cells)}: {total:.1f} m of shore, {w:g} m from the water '
            f'edge to the crest, the sand pulled to {lvl:g} m (the ground water line '
            f'{water_level_of(g):g} m + {BEACH_RISE:g} m) with a {fe:g} m feather, plus a depth-0 '
            f'sculpt_shelf per strip ({ids[0]}..{ids[-1]}) that moves no height and only paints the '
            f'strip sand. No solid `beach` record; the sea is on the LEFT of the walk from '
            f'{cells[0]} to {cells[-1]}'
            + _bh_note(base_height)
            + ('; material does not apply to a sculpted beach' if material else '')
            + '.'
        )
    # R4: read the ground along the whole walk FIRST, so strip 2 does not climb
    # onto strip 1's own sand (a beach is ground now).
    gy = _reach_ground(d, pts, base_height)
    grp = name or 'beach'
    ids, total, drop = [], 0.0, 0.0
    for i in range(need):
        (x0, z0), (x1, z1) = pts[i], pts[i + 1]
        L = math.hypot(x1 - x0, z1 - z0)
        if L < 0.5:
            return f'refused: {cells[i]} and {cells[i + 1]} are the same cell — a beach needs two different cells'
        ry = math.atan2(-(z1 - z0), x1 - x0)
        y = (gy[i] + gy[i + 1]) / 2  # the ground at the reach centre
        rz = math.atan2(gy[i + 1] - gy[i], L)  # positive rz lifts the +X (far) end
        o = d.new(
            'beach',
            {'len': round(L, 4), 'w': round(w, 3), 'h': round(h, 3), 'seed': sd},
            (x0 + x1) / 2,
            (z0 + z1) / 2,
            round(y, 4),
            ry,
            _mat(material, 'mat_sand'),
            name=f'beach {i + 1}' if need > 1 else (name or 'beach'),
            grp=grp,
        )
        o['rz'] = round(rz, 6)
        ids.append(o['id'])
        total += L
        drop = max(drop, abs(gy[i + 1] - gy[i]))
    fall = f', following the ground over {drop:.1f} m of fall' if drop > 0.05 else ''
    return (
        f'drew {need} beach strip(s) {ids[0]}..{ids[-1]} through {", ".join(str(c) for c in cells)}: '
        f'{total:.1f} m of shore, {w:g} m from water edge to crest, rising {h:g} m{fall} — '
        f'the sea is on the LEFT of the walk from {cells[0]} to {cells[-1]}'
    )


def t_add_dunes(d: Drawing, a, cell_from, cell_to, height=8.0, seed=1, base_height=None, material='', name=''):
    h = _num(height, 8.0)
    if h < DUNE_H[0] or h > DUNE_H[1]:
        return (
            f'refused: a dune is {DUNE_H[0]:g} to {DUNE_H[1]:g} m tall (Dutch dunes are 8-15 m) — {h:g} m is not a dune'
        )
    xmin, zmin, xmax, zmax = block_bounds(cell_from, cell_to)
    W, D = xmax - xmin, zmax - zmin
    if W > 2000 or D > 2000:
        return f'refused: {W:g} x {D:g} m is too big for one dune field — 2000 m a side is the limit'
    # the ridges always run along the record's own X, so turning the record a
    # quarter when the block is deeper than it is wide keeps them across the
    # SHORTER side of the block — the same swap add_slope makes.
    w, dd, ang = (D, W, 90) if D > W else (W, D, 0)
    sd = _num(seed, 1)
    if len(d.objs) + 1 > MAX_OBJECTS:
        return f'refused: the drawing is at the {MAX_OBJECTS} object ceiling'
    cf, ct = cell_name(*parse_cell(cell_from)), cell_name(*parse_cell(cell_to))
    cx, cz = (xmin + xmax) / 2, (zmin + zmax) / 2
    # v3: one sculpt_dunes. `dir` turns the ridges inside the sculpt, exactly as
    # it turns them inside the solid, and the ground paints the footprint sand.
    if the_ground(d) is not None:
        o = _sculpt(
            d,
            'sculpt_dunes',
            {'w': round(w, 4), 'd': round(dd, 4), 'h': round(h, 3), 'seed': sd, 'dir': ang, 'feather': 0},
            cx,
            cz,
            name or f'dunes {cf}-{ct}',
        )
        return (
            f'sculpted dune belt {o["id"]} into the ground over {cf}..{ct}: {W:g} x {D:g} m, crests '
            f'{h:g} m over the land, ridges running {"north-south" if ang else "east-west"}, seed '
            f'{sd:g}. This is a sculpt_dunes, not a solid `dune_field` — the ground itself rises '
            'and its footprint is coloured sand'
            + _bh_note(base_height)
            + ('; material does not apply to a sculpted dune' if material else '')
            + '.'
        )
    res = _res_for(w, dd, 12, 64)
    y = _A.place_height(d, cx, cz, base_height)  # R1/R6: dunes stack on the ground
    o = d.new(
        'dune_field',
        {'w': round(w, 4), 'd': round(dd, 4), 'h': round(h, 3), 'seed': sd, 'res': res, 'dir': ang},
        cx,
        cz,
        y,
        0.0,
        _mat(material, 'mat_sand'),
        name=name or f'dunes {cf}-{ct}',
        grp=name or 'dunes',
    )
    return (
        f'drew dune field {o["id"]} over {cf}..{ct}: {W:g} x {D:g} m, crests {h:g} m above y={y:g}, '
        f'ridges running {"north-south" if ang else "east-west"}, marram grass over '
        f'{MARRAM * h:.1f} m, seed {sd:g}'
    )


def t_add_island(
    d: Drawing,
    a,
    centre,
    radius=40.0,
    height=6.0,
    beach=6.0,
    wobble=0.3,
    seed=1,
    base_height=None,
    material='',
    name='',
):
    r = _num(radius, 40.0)
    if r < 2:
        return 'refused: radius must be at least 2 m'
    if r > 1000:
        return 'refused: radius must be under 1000 m'
    h = _num(height, 6.0)
    if h < ISLAND_H[0] or h > ISLAND_H[1]:
        return (
            f'refused: an island stands {ISLAND_H[0]:g} to {ISLAND_H[1]:g} m out of the water — '
            f'{h:g} m is not an island'
        )
    b = _num(beach, 6.0)
    if b <= 0 or b > r:
        return 'refused: the beach ring must be wider than 0 m and no wider than the radius'
    wob = _num(wobble, 0.3)
    if wob < 0 or wob > 0.9:
        return 'refused: wobble must be between 0 and 0.9'
    cx, cz = cell_centre(*parse_cell(centre))
    if len(d.objs) + 1 > MAX_OBJECTS:
        return f'refused: the drawing is at the {MAX_OBJECTS} object ceiling'
    sd = _num(seed, 1)
    cn = cell_name(*parse_cell(centre))
    # v3: a low wide sculpt_peak lifts the sea bed back out of the water, and a
    # depth-0 sculpt_shelf over the whole island + ring paints it sand.
    if the_ground(d) is not None:
        if len(d.objs) + 2 > MAX_OBJECTS:
            return f'refused: the drawing is at the {MAX_OBJECTS} object ceiling'
        side = round(2 * (r + b), 4)
        o = _sculpt(
            d,
            'sculpt_peak',
            {'r': round(r + b, 3), 'h': round(h, 3), 'rug': ISLAND_RUG, 'seed': sd, 'feather': 0},
            cx,
            cz,
            name or f'island {cn}',
        )
        _sculpt(
            d,
            'sculpt_shelf',
            {'w': side, 'd': side, 'depth': 0, 'feather': 0},
            cx,
            cz,
            f'{name or f"island {cn}"} sand',
        )
        return (
            f'sculpted island {o["id"]} into the ground on {cn}: a {h:g} m sculpt_peak {2 * (r + b):g} m '
            f'across (radius {r:g} m plus a {b:g} m beach ring), with a depth-0 sculpt_shelf over the '
            f'same {side:g} x {side:g} m square that moves no height and only paints it sand. No solid '
            '`island` record; the land itself rises out of the water'
            + _bh_note(base_height)
            + ('; material does not apply to a sculpted island' if material else '')
            + '. The shelf is a square, so the sand reaches the whole footprint, not only the ring.'
        )
    # R1/R6: an island stands on the ground under it. A sea is NOT ground, so an
    # island dropped into open water rises from the bed at y=0, as it should.
    y = _A.place_height(d, cx, cz, base_height)
    o = d.new(
        'island',
        {
            'r': round(r, 3),
            'h': round(h, 3),
            'wobble': round(wob, 3),
            'beach': round(b, 3),
            'seed': sd,
            'seg': 48,
            'rings': 10,
        },
        cx,
        cz,
        y,
        0.0,
        _mat(material, 'mat_grass'),
        name=name or f'island {cn}',
        grp=name or 'islands',
    )
    sx, sz = island_span(r, wob, b, sd, 48)
    return (
        f'drew island {o["id"]} on {cn}: {h:g} m tall from y={y:g}, shore about {2 * r:g} m across '
        f'({sx:.1f} x {sz:.1f} m including the {b:g} m beach ring) — place it in the sea'
    )


def t_add_breakwater(d: Drawing, a, cells, height=3.0, width=8.0, base_height=None, material='', name=''):
    if not _cells_ok(cells):
        return 'refused: give a list of at least two cells — one mound is drawn between each pair'
    h = _num(height, 3.0)
    if h < BREAKWATER_H[0] or h > BREAKWATER_H[1]:
        return (
            f'refused: a breakwater stands {BREAKWATER_H[0]:g} to {BREAKWATER_H[1]:g} m out of the '
            f'water — {h:g} m is not a rubble mound'
        )
    w = _num(width, 8.0)
    if w < 0.5 or w > 100:
        return 'refused: width must be between 0.5 and 100 m at the base'
    pts = [cell_centre(*parse_cell(c)) for c in cells]
    need = len(pts) - 1
    if len(d.objs) + need > MAX_OBJECTS:
        return f'refused: that is {need} objects past the {MAX_OBJECTS} ceiling'
    gy = _reach_ground(d, pts, base_height)  # R4, read before anything is drawn
    grp = name or 'breakwaters'
    ids, total, drop = [], 0.0, 0.0
    for i in range(need):
        (x0, z0), (x1, z1) = pts[i], pts[i + 1]
        L = math.hypot(x1 - x0, z1 - z0)
        if L < 0.5:
            return f'refused: {cells[i]} and {cells[i + 1]} are the same cell — a mound needs two different cells'
        ry = math.atan2(-(z1 - z0), x1 - x0)
        y = (gy[i] + gy[i + 1]) / 2
        o = d.new(
            'breakwater',
            {'len': round(L, 4), 'w': round(w, 3), 'h': round(h, 3)},
            (x0 + x1) / 2,
            (z0 + z1) / 2,
            round(y, 4),
            ry,
            _mat(material, 'mat_rock'),
            name=f'breakwater {i + 1}' if need > 1 else (name or 'breakwater'),
            grp=grp,
        )
        o['rz'] = round(math.atan2(gy[i + 1] - gy[i], L), 6)
        ids.append(o['id'])
        total += L
        drop = max(drop, abs(gy[i + 1] - gy[i]))
    fall = f', running down {drop:.1f} m into the water' if drop > 0.05 else ''
    return (
        f'drew {need} breakwater(s) {ids[0]}..{ids[-1]} through {", ".join(str(c) for c in cells)}: '
        f'{total:.1f} m of rubble mound, {w:g} m at the base, {w / 3:.1f} m at the top, '
        f'{h:g} m tall{fall}'
        + (
            '. A rubble mound is an object, not a landform, so a breakwater keeps its solid even on a sculpted ground.'
            if the_ground(d) is not None
            else ''
        )
    )


def t_make_coast(
    d: Drawing,
    a,
    cell_from,
    cell_to,
    sea_side='north',
    seed=1,
    dune_height=8.0,
    sea_depth=6.0,
    base_height=None,
    name='',
):
    """The whole shoreline in one call. It draws nothing itself: it works out
    the three bands and hands them to add_sea, add_beach and add_dunes."""
    side = str(sea_side or 'north').strip().lower()
    if side not in _SIDES:
        return "refused: sea_side must be 'north', 'south', 'east' or 'west'"
    c0, r0 = parse_cell(cell_from)
    c1, r1 = parse_cell(cell_to)
    ca, cb = sorted((c0, c1))
    ra, rb = sorted((r0, r1))
    ncols, nrows = cb - ca + 1, rb - ra + 1
    across = ncols if side in ('east', 'west') else nrows
    if across < 3:
        return (
            f'refused: the block is only {across} cells across the shore — a coast needs at least 3 (sea, beach, dunes)'
        )
    dh = _num(dune_height, 8.0)
    if dh < DUNE_H[0] or dh > DUNE_H[1]:
        return (
            f'refused: a dune is {DUNE_H[0]:g} to {DUNE_H[1]:g} m tall (Dutch dunes are 8-15 m) — '
            f'{dh:g} m is not a dune'
        )
    sdep = _num(sea_depth, 6.0)
    if sdep <= 0 or sdep > 200:
        return 'refused: sea_depth must be between 0 and 200 m'
    # 3 solids without a ground; on a sculpted one it is 5 records — a shelf and
    # a water_plane for the sea, a flat and a shelf for the beach, one dune sculpt
    if len(d.objs) + (5 if the_ground(d) is not None else 3) > MAX_OBJECTS:
        return f'refused: the drawing is at the {MAX_OBJECTS} object ceiling'
    n_sea = max(1, round(across * 0.4))
    n_bch = max(1, round(across * 0.2))
    n_dun = across - n_sea - n_bch
    if n_dun < 1:  # only possible on a 3-cell block
        n_sea, n_bch, n_dun = 1, 1, across - 2
    sd = _num(seed, 1)
    bh = base_height  # None = each band reads its own ground
    grp = name or 'coast'

    # bands counted from the seaward edge inwards
    if side == 'north':  # sea at the small-z end
        bands = [(ca, ra + o, cb, ra + o + n - 1) for o, n in ((0, n_sea), (n_sea, n_bch), (n_sea + n_bch, n_dun))]
    elif side == 'south':  # sea at the large-z end
        bands = [(ca, rb - o - n + 1, cb, rb - o) for o, n in ((0, n_sea), (n_sea, n_bch), (n_sea + n_bch, n_dun))]
    elif side == 'west':  # sea at the small-x end
        bands = [(ca + o, ra, ca + o + n - 1, rb) for o, n in ((0, n_sea), (n_sea, n_bch), (n_sea + n_bch, n_dun))]
    else:  # east: sea at the large-x end
        bands = [(cb - o - n + 1, ra, cb - o, rb) for o, n in ((0, n_sea), (n_sea, n_bch), (n_sea + n_bch, n_dun))]
    (sc0, sr0, sc1, sr1), (bc0, br0, bc1, br1), (dc0, dr0, dc1, dr1) = bands

    ids, out = [], []
    r_sea = t_add_sea(d, a, cell_name(sc0, sr0), cell_name(sc1, sr1), depth=sdep, seed=sd, base_height=bh, name=grp)
    if r_sea.startswith('refused'):
        return 'refused: make_coast could not lay the whole shore — ' + r_sea[9:]
    out.append(r_sea)
    ids.append(d.objs[-1]['id'])
    # the beach is one record turned to the shore: walk it so that the sea
    # stays on the LEFT — east with the sea north, west with it south, south
    # with it east, north with it west.
    bm_c = (bc0 + bc1) // 2
    bm_r = (br0 + br1) // 2
    if side == 'north':
        walk = [cell_name(bc0, bm_r), cell_name(bc1, bm_r)]
    elif side == 'south':
        walk = [cell_name(bc1, bm_r), cell_name(bc0, bm_r)]
    elif side == 'east':
        walk = [cell_name(bm_c, br0), cell_name(bm_c, br1)]
    else:
        walk = [cell_name(bm_c, br1), cell_name(bm_c, br0)]
    band_w = (bc1 - bc0 + 1) if side in ('east', 'west') else (br1 - br0 + 1)
    r_bch = t_add_beach(d, a, walk, width=float(band_w), height=2.0, seed=sd, base_height=bh, name=grp)
    if r_bch.startswith('refused'):
        return 'refused: make_coast could not lay the whole shore — ' + r_bch[9:]
    out.append(r_bch)
    ids.append(d.objs[-1]['id'])
    r_dun = t_add_dunes(d, a, cell_name(dc0, dr0), cell_name(dc1, dr1), height=dh, seed=sd, base_height=bh, name=grp)
    if r_dun.startswith('refused'):
        return 'refused: make_coast could not lay the whole shore — ' + r_dun[9:]
    out.append(r_dun)
    ids.append(d.objs[-1]['id'])
    return (
        f'laid a coast over {cell_name(ca, ra)}..{cell_name(cb, rb)} with the sea to the {side}: '
        f'sea {ids[0]} ({n_sea} cells, 40%), beach {ids[1]} ({n_bch} cells wide, 20%), '
        f'dunes {ids[2]} ({n_dun} cells, 40%) — {ncols} x {nrows} m in all, '
        + (
            'every band cut into the one sculpted ground, no solid sea/beach/dune_field records'
            if the_ground(d) is not None
            else 'each band on the ground under it'
        )
    )


TOOLS = [
    (
        {
            'name': 'add_sea',
            'description': 'ONE body of open water over a block of cells: a rolling water surface with a sand bed at -depth. It lies LEVEL at the ground under its centre and is refused when that ground varies by more than 0.5 m — flatten_pad it first. Water is not ground: nothing stands on a sea, it stands on the bed. With a sculpted ground it dishes a sculpt_shelf bed out of the land under a water_plane instead, and base_height does not apply. Draw the sea before anything else on the coast. Use for the North Sea, a lake edge, a harbour basin.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'cell_from': {'type': 'string'},
                    'cell_to': {'type': 'string'},
                    'depth': {'type': 'number'},
                    'wave': {'type': 'number'},
                    'seed': {'type': 'number'},
                    'base_height': {'type': 'number'},
                    'material': {'type': 'string', 'enum': MATERIALS},
                    'name': {'type': 'string'},
                },
                'required': ['cell_from', 'cell_to'],
            },
        },
        t_add_sea,
    ),
    (
        {
            'name': 'add_beach',
            'description': 'A sand wedge along the shore, one between each pair of cells in the list (3 cells = 2 strips). It is flat and wet at the water edge and rises `height` (0.5 to 4 m, a real beach) over `width` to the dry back crest; the sea is always on the LEFT of the walk from the first cell to the last, so order the cells to put it there. Each strip sits on the ground at its own centre and tilts to follow the fall along the shore; base_height overrides that and lays them flat. With a sculpted ground it sculpts the beach into the land instead: a sculpt_flat pulled to just above the water line plus a depth-0 sculpt_shelf that only paints the strip sand.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'cells': {'type': 'array', 'items': {'type': 'string'}},
                    'width': {'type': 'number'},
                    'height': {'type': 'number'},
                    'seed': {'type': 'number'},
                    'base_height': {'type': 'number'},
                    'material': {'type': 'string', 'enum': MATERIALS},
                    'name': {'type': 'string'},
                },
                'required': ['cells'],
            },
        },
        t_add_beach,
    ),
    (
        {
            'name': 'add_dunes',
            'description': 'A field of ridged sand dunes over a block of cells, the tallest crest exactly `height` above the ground under the block (3 to 25 m; Dutch dunes are 8-15 m). The ridges are laid across the shorter side of the block, the way a dune belt lies across the wind, and marram grass holds the crests. The dunes are ground themselves: things placed on them land on them. With a sculpted ground it is one sculpt_dunes, so the land itself rises and its footprint is coloured sand.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'cell_from': {'type': 'string'},
                    'cell_to': {'type': 'string'},
                    'height': {'type': 'number'},
                    'seed': {'type': 'number'},
                    'base_height': {'type': 'number'},
                    'material': {'type': 'string', 'enum': MATERIALS},
                    'name': {'type': 'string'},
                },
                'required': ['cell_from', 'cell_to'],
            },
        },
        t_add_dunes,
    ),
    (
        {
            'name': 'add_island',
            'description': 'A grass hill with a wandering shoreline and a sand beach ring round it, centred on one cell. `height` is the summit out of the water (1 to 40 m), `radius` the mean distance to the water, `wobble` how far the shore strays from it. Place it inside a sea: the water is not ground, so the island rises from the bed at y=0 as it should. With a sculpted ground it is a low wide sculpt_peak plus a depth-0 sculpt_shelf sand mask.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'centre': {'type': 'string'},
                    'radius': {'type': 'number'},
                    'height': {'type': 'number'},
                    'beach': {'type': 'number'},
                    'wobble': {'type': 'number'},
                    'seed': {'type': 'number'},
                    'base_height': {'type': 'number'},
                    'material': {'type': 'string', 'enum': MATERIALS},
                    'name': {'type': 'string'},
                },
                'required': ['centre'],
            },
        },
        t_add_island,
    ),
    (
        {
            'name': 'add_breakwater',
            'description': 'A rubble mound running out into the water, one between each pair of cells in the list. `width` is the base, the top is a third of it, `height` is how far it stands out of the water (1 to 6 m). Each mound sits on the ground at its own centre and tilts to follow it. It always keeps its solid, sculpted ground or not — a rubble mound is an object, not a landform. Use for a groyne, a harbour mole, a wave break.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'cells': {'type': 'array', 'items': {'type': 'string'}},
                    'height': {'type': 'number'},
                    'width': {'type': 'number'},
                    'base_height': {'type': 'number'},
                    'material': {'type': 'string', 'enum': MATERIALS},
                    'name': {'type': 'string'},
                },
                'required': ['cells'],
            },
        },
        t_add_breakwater,
    ),
    (
        {
            'name': 'make_coast',
            'description': "A whole shoreline over a block of cells in one call: sea over the seaward 40% of the block, a beach strip 20% wide along the shore, dunes over the remaining 40%. sea_side names the edge the water is on ('north' is the small-z edge, up in the top view). Every band lands on the ground under it unless base_height is given; with a sculpted ground all three bands are cut into the land instead. Use this whenever someone asks for a coast, a seafront or a dune landscape.",
            'input_schema': {
                'type': 'object',
                'properties': {
                    'cell_from': {'type': 'string'},
                    'cell_to': {'type': 'string'},
                    'sea_side': {'type': 'string', 'enum': list(_SIDES)},
                    'seed': {'type': 'number'},
                    'dune_height': {'type': 'number'},
                    'sea_depth': {'type': 'number'},
                    'base_height': {'type': 'number'},
                    'name': {'type': 'string'},
                },
                'required': ['cell_from', 'cell_to', 'sea_side'],
            },
        },
        t_make_coast,
    ),
]

EXAMPLES = [
    {
        'ask': 'lay out the Dutch coast from A1 to CV50, sea to the west, dunes 12 m',
        'calls': [
            {
                'tool': 'make_coast',
                'args': {'cell_from': 'A1', 'cell_to': 'CV50', 'sea_side': 'west', 'dune_height': 12},
            }
        ],
    },
    {
        'ask': 'put the sea over B2..BX40 and a beach along the row at BX20',
        'calls': [
            {'tool': 'add_sea', 'args': {'cell_from': 'B2', 'cell_to': 'BX40', 'depth': 8}},
            {'tool': 'add_beach', 'args': {'cells': ['B41', 'BX41'], 'width': 60, 'height': 2}},
        ],
    },
    {
        'ask': 'a dune belt 10 m high from C60 to BZ80',
        'calls': [{'tool': 'add_dunes', 'args': {'cell_from': 'C60', 'cell_to': 'BZ80', 'height': 10}}],
    },
    {
        'ask': 'drop a small island in the middle of the sea at AK20, 30 m across with a wide beach',
        'calls': [{'tool': 'add_island', 'args': {'centre': 'AK20', 'radius': 15, 'height': 4, 'beach': 8}}],
    },
    {
        'ask': 'three groynes running out from the beach at H45, H38 / M45, M38 / R45, R38',
        'calls': [
            {'tool': 'add_breakwater', 'args': {'cells': ['H45', 'H38'], 'height': 2}},
            {'tool': 'add_breakwater', 'args': {'cells': ['M45', 'M38'], 'height': 2}},
            {'tool': 'add_breakwater', 'args': {'cells': ['R45', 'R38'], 'height': 2}},
        ],
    },
    {
        'ask': 'a seafront on the south side of D10..BB35 with the dunes on a 3 m plateau',
        'calls': [
            {
                'tool': 'make_coast',
                'args': {'cell_from': 'D10', 'cell_to': 'BB35', 'sea_side': 'south', 'base_height': 3},
            }
        ],
    },
    {
        'ask': 'the ground from A1 to T20 slopes 4 m down to the sea — put a harbour basin on the low end and dunes on the high end',
        'calls': [
            {'tool': 'flatten_pad', 'args': {'cell_from': 'A1', 'cell_to': 'T6'}},
            {'tool': 'add_sea', 'args': {'cell_from': 'A1', 'cell_to': 'T6', 'depth': 5}},
            {'tool': 'add_dunes', 'args': {'cell_from': 'A14', 'cell_to': 'T20', 'height': 9}},
        ],
    },
]
