# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""ground_v3, THE ARITHMETIC: the shared noise, the feather, the ten sculpts,
H(lx, lz), the colour mix and the HEIGHTS seam. Byte-for-byte the same
arithmetic as arch_ext/ground_v3.js and arch_blender_ext/ground_v3.py."""

from __future__ import annotations

import math

from zyg_workflows.arch_assistant import (
    _num,
    current_drawing,
)

from .constants import (
    SAND_KINDS,
    RES_MAX,
    RES_MIN,
    BASE_CELL,
    FEATHER_FRAC,
    COLOUR_BAND,
    SLOPE_BAND,
    WATER_SOIL,
    COLOUR_MATS,
)


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


def meander_offset(t: float, meander: float, seed: float) -> float:
    """A river reach's sideways offset — verbatim from rivers_lakes, so a
    sculpt_channel wanders exactly like the water_path drawn along it."""
    return (
        meander
        * math.sin(math.pi * t)
        * (0.6 * math.sin(2 * math.pi * t * 1.5) + 0.4 * (2 * value_noise(t * 4, seed, seed) - 1))
    )


def lake_factor(a: float, wobble: float, seed: float) -> float:
    """A lake rim's radius multiplier at plan angle a — verbatim from
    rivers_lakes, so a sculpt_basin's shore is the shape of its lake."""
    return 1 + wobble * (2 * value_noise(math.cos(a) * 2 + 2, math.sin(a) * 2 + 2, seed) - 1)


# ── the feather ──────────────────────────────────────────────────────────────
def clamp(v: float, lo: float, hi: float) -> float:
    return lo if v < lo else (hi if v > hi else v)


def smoothstep(t: float) -> float:
    t = clamp(t, 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def band(dist: float, fe: float) -> float:
    """1 well inside the rim, smoothstepped to 0 over the outer `fe` metres."""
    if fe <= 1e-9:
        return 1.0 if dist > 0.0 else 0.0
    return smoothstep(dist / fe)


def feather_of(p, size: float) -> float:
    """A sculpt's feather in metres: its own `feather` when it names one, else
    FEATHER_FRAC of `size` — and never wider than the size itself."""
    f = _num((p or {}).get('feather'), 0.0)
    if f <= 0.0:
        f = FEATHER_FRAC * size
    return clamp(f, 0.0, size)


def _N(p, k, d):
    return _num((p or {}).get(k), d)


# ── the ten sculpts: (dh, mask) in the sculpt's own LOCAL plan frame ─────────
def s_peak(p, lx, lz):
    """A rocky summit: the old mountain field, normalised so the summit is h."""
    r = max(0.5, _N(p, 'r', 40.0))
    h = _N(p, 'h', 30.0)
    rug = clamp(_N(p, 'rug', 0.45), 0.0, 0.9)
    seed = _N(p, 'seed', 1.0)
    rho = math.hypot(lx, lz)
    if rho >= r:
        return 0.0, 0.0
    mask = 0.5 * (1 + math.cos(math.pi * rho / r)) * band(r - rho, feather_of(p, r))
    if mask <= 0.0:
        return 0.0, 0.0
    n0 = 1 - rug * value_noise(3.0, 3.0, seed)
    n = 1 - rug * value_noise((lx / r * 0.5 + 0.5) * 6.0, (lz / r * 0.5 + 0.5) * 6.0, seed)
    return h * mask * (n / n0 if n0 > 1e-6 else 1.0), mask


def s_ridge(p, lx, lz):
    """A long crest along X with a triangular section and a wandering spine."""
    ln = max(1.0, _N(p, 'len', 120.0))
    w = max(1.0, _N(p, 'w', 40.0))
    h = _N(p, 'h', 25.0)
    rug = clamp(_N(p, 'rug', 0.35), 0.0, 0.9)
    seed = _N(p, 'seed', 1.0)
    if abs(lx) > ln / 2 or abs(lz) > w / 2:
        return 0.0, 0.0
    t = (lx + ln / 2) / ln
    crest = 0.15 * w * (2 * value_noise(t * 4.0, seed, seed) - 1)
    q = abs(lz - crest) / (w / 2)
    if q >= 1.0:
        return 0.0, 0.0
    mask = (1.0 - q) * band(min(lx + ln / 2, ln / 2 - lx), feather_of(p, ln / 2))
    if mask <= 0.0:
        return 0.0, 0.0
    n = max(0.0, 1 - rug * value_noise(t * 6.0, (lz / w + 0.5) * 6.0, seed))
    return h * mask * n, mask


def s_mesa(p, lx, lz):
    """A table mountain: a flat top h inside top_r, an eroded flank to the rim."""
    r = max(0.5, _N(p, 'r', 40.0))
    h = _N(p, 'h', 25.0)
    tr = clamp(_N(p, 'top_r', r * 0.7), 0.0, r * 0.95)
    rug = clamp(_N(p, 'rug', 0.25), 0.0, 0.9)
    seed = _N(p, 'seed', 1.0)
    rho = math.hypot(lx, lz)
    if rho >= r:
        return 0.0, 0.0
    if rho <= tr:
        prof, ero = 1.0, 1.0
    else:
        u = (rho - tr) / (r - tr)
        prof = 1.0 - smoothstep(u)
        ero = max(0.0, 1 - rug * u * value_noise((lx / r * 0.5 + 0.5) * 6.0, (lz / r * 0.5 + 0.5) * 6.0, seed))
    mask = prof * band(r - rho, feather_of(p, r))
    if mask <= 0.0:
        return 0.0, 0.0
    return h * mask * ero, mask


def s_cut(p, lx, lz):
    """A trough along X — the valley and the canyon. profile 0 is a V, 1 a U."""
    ln = max(1.0, _N(p, 'len', 200.0))
    w = max(1.0, _N(p, 'w', 60.0))
    dep = _N(p, 'depth', 15.0)
    fw = clamp(_N(p, 'floor_w', w * 0.25), 0.0, w * 0.95)
    pr = clamp(_N(p, 'profile', 0.0), 0.0, 1.0)
    if abs(lx) > ln / 2 or abs(lz) > w / 2:
        return 0.0, 0.0
    a = abs(lz)
    if a <= fw / 2:
        sec = 1.0
    else:
        u = (a - fw / 2) / (w / 2 - fw / 2)
        if u >= 1.0:
            return 0.0, 0.0
        sec = (1.0 - u) * (1.0 - pr) + (1.0 - smoothstep(u)) * pr
    mask = sec * band(min(lx + ln / 2, ln / 2 - lx), feather_of(p, ln / 2))
    if mask <= 0.0:
        return 0.0, 0.0
    return -dep * mask, mask


def channel_levels(p):
    """A sculpt_channel's SET bed, or None.

    When a channel names BOTH `level0` and `level1` it stops being a trough dug
    `depth` below whatever rolls past and becomes a bed SET to a straight fall
    from level0 (at the reach start, local x = -len/2) to level1 (at the end).
    That is what makes a river read as a river: the water is one sloping plane
    and the bed under it is FLAT ACROSS and FALLING ALONG, so the base noise can
    no longer surface through the water half way down the reach.

    Without the pair the old 'lower by depth' behaviour is untouched."""
    p = p or {}
    a, b = p.get('level0'), p.get('level1')
    if a is None or b is None:
        return None
    return _num(a, 0.0), _num(b, 0.0)


def s_channel(p, lx, lz):
    """The riverbed: a meandering trough, the same wander as the river kind."""
    ln = max(1.0, _N(p, 'len', 120.0))
    w = max(0.5, _N(p, 'w', 12.0))
    dep = _N(p, 'depth', 2.0)
    mea = max(0.0, _N(p, 'meander', 6.0))
    seed = _N(p, 'seed', 1.0)
    bank = max(0.05, _N(p, 'bank', 2.0))
    if abs(lx) > ln / 2:
        return 0.0, 0.0
    t = (lx + ln / 2) / ln
    a = abs(lz - meander_offset(t, mea, seed))
    if a >= w / 2 + bank:
        return 0.0, 0.0
    sec = 1.0 if a <= w / 2 else 1.0 - smoothstep((a - w / 2) / bank)
    lv = channel_levels(p)
    if lv is not None:  # SET: dh is the LEVEL, like s_flat
        if sec <= 0.0:  # no end band — reaches of one river
            return 0.0, 0.0  # share a node level and must butt
        return lv[0] + (lv[1] - lv[0]) * t, sec
    mask = sec * band(min(lx + ln / 2, ln / 2 - lx), feather_of(p, ln / 2))
    if mask <= 0.0:
        return 0.0, 0.0
    return -dep * mask, mask


def s_basin(p, lx, lz):
    """The lake bed: an ellipse with the lake kind's own wobbled shoreline."""
    rx = max(0.5, _N(p, 'rx', 40.0))
    rz = max(0.5, _N(p, 'rz', 28.0))
    dep = _N(p, 'depth', 6.0)
    wob = clamp(_N(p, 'wobble', 0.25), 0.0, 0.9)
    seed = _N(p, 'seed', 1.0)
    shore = max(0.05, _N(p, 'shore', 6.0))
    f = lake_factor(math.atan2(lz, lx), wob, seed)
    if f <= 1e-6:
        return 0.0, 0.0
    e = math.hypot(lx / (rx * f), lz / (rz * f))
    if e >= 1.0:
        return 0.0, 0.0
    sf = clamp(shore / min(rx, rz), 0.02, 0.9)
    mask = 1.0 if e <= 1.0 - sf else 1.0 - smoothstep((e - (1.0 - sf)) / sf)
    if mask <= 0.0:
        return 0.0, 0.0
    return -dep * mask, mask


def s_flat(p, lx, lz):
    """The one SET sculpt: a building pad, a car park, a level lawn. `dh` is the
    LEVEL, not a delta, and the mask is the pull. Byte-for-byte the weight
    arch_assistant._sculpt_flat_weight uses, so pad_level() is idempotent on
    top of this ground. The record's own y is NOT added: `level` is absolute."""
    w = abs(_N(p, 'w', 0.0))
    dd = abs(_N(p, 'd', 0.0))
    if w <= 0 or dd <= 0 or abs(lx) > w / 2 or abs(lz) > dd / 2:
        return 0.0, 0.0
    f = _N(p, 'feather', 0.0)
    f = min(max(f, 0.0), w / 2, dd / 2)
    if f <= 1e-9:
        return _N(p, 'level', 0.0), 1.0
    t = min((w / 2 - abs(lx)) / f, (dd / 2 - abs(lz)) / f, 1.0)
    return _N(p, 'level', 0.0), t * t * (3.0 - 2.0 * t)


def s_step(p, lx, lz):
    """The cliff / escarpment: everything behind the face (local +z) lifted h."""
    ln = max(1.0, _N(p, 'len', 120.0))
    h = _N(p, 'h', 20.0)
    dd = max(1.0, _N(p, 'd', 40.0))
    rug = clamp(_N(p, 'rug', 0.3), 0.0, 0.9)
    seed = _N(p, 'seed', 1.0)
    if abs(lx) > ln / 2 or abs(lz) > dd / 2:
        return 0.0, 0.0
    t = (lx + ln / 2) / ln
    fz = 0.06 * dd * (2 * value_noise(t * 5.0, seed, seed) - 1)
    lift = smoothstep((lz - fz) / max(0.5, 0.08 * dd))
    if lift <= 0.0:
        return 0.0, 0.0
    mask = lift * band(min(lx + ln / 2, ln / 2 - lx), feather_of(p, ln / 2)) * band(dd / 2 - lz, feather_of(p, dd / 2))
    if mask <= 0.0:
        return 0.0, 0.0
    n = max(0.0, 1 - rug * value_noise(t * 6.0, (lz / dd + 0.5) * 6.0, seed))
    return h * mask * n, mask


def s_dunes(p, lx, lz):
    """A belt of ridged dune noise; its whole footprint reads as SAND."""
    w = max(1.0, _N(p, 'w', 160.0))
    dd = max(1.0, _N(p, 'd', 80.0))
    h = _N(p, 'h', 10.0)
    seed = _N(p, 'seed', 1.0)
    a = math.radians(_N(p, 'dir', 0.0))
    if abs(lx) > w / 2 or abs(lz) > dd / 2:
        return 0.0, 0.0
    c, s = math.cos(a), math.sin(a)
    rx, rz = lx * c - lz * s, lx * s + lz * c
    ridged = 1.0 - abs(2 * value_noise((rx / w + 0.5) * 8.0, (rz / dd + 0.5) * 2.0, seed) - 1)
    mask = band(min(w / 2 - abs(lx), dd / 2 - abs(lz)), feather_of(p, min(w, dd) / 2))
    if mask <= 0.0:
        return 0.0, 0.0
    return h * ridged * mask, mask


def s_shelf(p, lx, lz):
    """The sea bed: a broad shallow dish, its whole footprint SAND."""
    w = max(1.0, _N(p, 'w', 200.0))
    dd = max(1.0, _N(p, 'd', 120.0))
    dep = _N(p, 'depth', 8.0)
    if abs(lx) > w / 2 or abs(lz) > dd / 2:
        return 0.0, 0.0
    mask = band(min(w / 2 - abs(lx), dd / 2 - abs(lz)), feather_of(p, min(w, dd) / 2))
    if mask <= 0.0:
        return 0.0, 0.0
    return -dep * mask, mask


SCULPTS = {
    'sculpt_peak': s_peak,
    'sculpt_ridge': s_ridge,
    'sculpt_mesa': s_mesa,
    'sculpt_cut': s_cut,
    'sculpt_channel': s_channel,
    'sculpt_basin': s_basin,
    'sculpt_flat': s_flat,
    'sculpt_step': s_step,
    'sculpt_dunes': s_dunes,
    'sculpt_shelf': s_shelf,
}


# ── H(lx, lz): the base plus the sum of the sculpts ─────────────────────────
def base_height(p, lx, lz) -> float:
    """The ground's own gentle roll, before any sculpt. One noise cell is
    BASE_CELL metres, so a 2 km ground is not one single bump."""
    w = max(1.0, abs(_N(p, 'w', 200.0)))
    dd = max(1.0, abs(_N(p, 'd', 200.0)))
    return _N(p, 'base', 0.0) + _N(p, 'amp', 1.5) * value_noise(
        (lx + w / 2) / BASE_CELL, (lz + dd / 2) / BASE_CELL, _N(p, 'seed', 1.0)
    )


def field_at(p, lx, lz, records, ox=0.0, oz=0.0, ory=0.0):
    """(H, sand) at a point in the GROUND's local plan frame.

    `records` is the drawing's whole object list; the sculpts in it are in world
    coordinates, so (lx, lz) is turned back into a world point with the ground's
    own origin (ox, oz) and yaw (ory) first. `sand` is the strongest dune/shelf
    mask at the point — what makes the colour sand there."""
    h = base_height(p, lx, lz)
    c, s = math.cos(ory), math.sin(ory)
    wx = ox + lx * c + lz * s  # the inverse of arch_assistant.world_to_local
    wz = oz - lx * s + lz * c
    sand = 0.0
    flats = []
    for o in records or ():
        if not isinstance(o, dict) or o.get('hidden'):
            continue
        fn = SCULPTS.get(o.get('kind'))
        if fn is None:
            continue
        sc = _num(o.get('s'), 1.0) or 1.0
        dx, dz = wx - _num(o.get('x'), 0.0), wz - _num(o.get('z'), 0.0)
        cc, ss = math.cos(_num(o.get('ry'), 0.0)), math.sin(_num(o.get('ry'), 0.0))
        dh, mask = fn(o.get('p') or {}, (dx * cc - dz * ss) / sc, (dx * ss + dz * cc) / sc)
        if mask <= 0.0:
            continue
        if o['kind'] == 'sculpt_flat' or (o['kind'] == 'sculpt_channel' and channel_levels(o.get('p')) is not None):
            flats.append((dh, mask))  # a SET sculpt: dh is the LEVEL
            continue
        h += dh * sc + _num(o.get('y'), 0.0) * mask
        if o['kind'] in SAND_KINDS and mask > sand:
            sand = mask
    for level, mask in flats:  # SET semantics, applied LAST
        h = h * (1.0 - mask) + level * mask
    return h, sand


def height_at(p, lx, lz, records, ox=0.0, oz=0.0, ory=0.0) -> float:
    """H at a point in the ground's local plan frame — the one number the tab,
    Blender and HEIGHTS['ground'] all have to agree about."""
    return field_at(p, lx, lz, records, ox, oz, ory)[0]


def lattice(p, records, ox=0.0, oz=0.0, ory=0.0):
    """(heights, sands): two (res+1) x (res+1) row-major lattices, the very
    vertices the tab and Blender build the mesh from."""
    w = max(1.0, abs(_N(p, 'w', 200.0)))
    dd = max(1.0, abs(_N(p, 'd', 200.0)))
    res = int(clamp(round(_N(p, 'res', 100.0)), RES_MIN, RES_MAX))
    hs, sd = [], []
    for j in range(res + 1):
        lz = -dd / 2 + j / res * dd
        rowh, rows = [], []
        for i in range(res + 1):
            hh, ss = field_at(p, -w / 2 + i / res * w, lz, records, ox, oz, ory)
            rowh.append(hh)
            rows.append(ss)
        hs.append(rowh)
        sd.append(rows)
    return hs, sd


def slope_deg(hs, i, j, stepx, stepz) -> float:
    """The slope in degrees at lattice (i, j), from the NEIGHBOURING heights —
    central differences inside, one-sided at the rim. The same three lines run
    in the tab and in Blender."""
    res = len(hs) - 1
    i0, i1 = (i - 1 if i > 0 else i), (i + 1 if i < res else i)
    j0, j1 = (j - 1 if j > 0 else j), (j + 1 if j < res else j)
    gx = (hs[j][i1] - hs[j][i0]) / max(1e-6, (i1 - i0) * stepx)
    gz = (hs[j1][i] - hs[j0][i]) / max(1e-6, (j1 - j0) * stepz)
    return math.degrees(math.atan(math.hypot(gx, gz)))


# ── colour: one arithmetic, three palettes ──────────────────────────────────
def colour_weights(h, slope, sand, water_h, snow_h, grass_max_slope) -> list:
    """The weights of (grass, sand, rock, snow, soil) at a vertex, summing to 1.

    Sequential mixing, in this order and no other: grass is the land, sand takes
    over inside a dune belt or a sea bed, rock on anything steeper than
    grass_max_slope, snow above snow_h, and the wet bed at the waterline wins
    last — a river bed is soil even where it is steep. Each band blends over
    COLOUR_BAND metres (SLOPE_BAND degrees for the slope) so nothing is a
    cut-out shape on the hillside."""
    w_sand = clamp(sand, 0.0, 1.0)
    w_rock = smoothstep((slope - grass_max_slope) / SLOPE_BAND)
    w_snow = smoothstep((h - snow_h) / COLOUR_BAND)
    w_soil = 1.0 - smoothstep((h - (water_h + WATER_SOIL)) / COLOUR_BAND)
    rest = (1.0 - w_snow) * (1.0 - w_soil)
    return [
        (1.0 - w_sand) * (1.0 - w_rock) * rest,
        w_sand * (1.0 - w_rock) * rest,
        w_rock * rest,
        w_snow * (1.0 - w_soil),
        w_soil,
    ]


def studio_rgb(mat_id):
    """(r, g, b) 0..1 for a material preset, from architecture_studio's own hex —
    the tab reads the same table through AR.matDefs, Blender through MAT_COLOURS."""
    from zyg_workflows import architecture_studio as st

    for sec in st.MATERIALS:
        for it in sec[1] if isinstance(sec, (list, tuple)) and len(sec) > 1 else []:
            if isinstance(it, (list, tuple)) and it and it[0] == mat_id:
                hexc = str((it[2] or {}).get('col') or '#9a9a94').lstrip('#')
                return (int(hexc[0:2], 16) / 255.0, int(hexc[2:4], 16) / 255.0, int(hexc[4:6], 16) / 255.0)
    return (0.6, 0.6, 0.6)


def colour_at(p, h, slope, sand, palette=None):
    """The blended (r, g, b) of a ground vertex. `palette` is five (r, g, b) in
    COLOUR_MATS order; the studio's own hexes when it is not given."""
    if palette is None:
        palette = [studio_rgb(m) for m in COLOUR_MATS]
    ws = colour_weights(h, slope, sand, _N(p, 'water_h', -0.15), _N(p, 'snow_h', 60.0), _N(p, 'grass_max_slope', 32.0))
    return tuple(sum(ws[k] * palette[k][ch] for k in range(5)) for ch in range(3))


# ── HEIGHTS: the seam the whole studio reads ────────────────────────────────
def ground_record(p, records):
    """The record whose params ARE `p` — a HEIGHTS fn is handed the params, but
    the sculpts around it are in world coordinates, so it needs the origin."""
    for o in records or ():
        if isinstance(o, dict) and o.get('kind') == 'ground' and o.get('p') is p:
            return o
    for o in records or ():
        if isinstance(o, dict) and o.get('kind') == 'ground':
            return o
    return None


def h_ground(p, lx, lz):
    """HEIGHTS['ground']: H at a local plan point, None outside the footprint.
    Reads the other records through arch_assistant.current_drawing() — that is
    the whole point of the v3 seam."""
    w = max(1.0, abs(_N(p, 'w', 200.0)))
    dd = max(1.0, abs(_N(p, 'd', 200.0)))
    if abs(lx) > w / 2 + 1e-9 or abs(lz) > dd / 2 + 1e-9:
        return None
    d = current_drawing()
    recs = list(getattr(d, 'objs', None) or ()) if d is not None else []
    g = ground_record(p, recs)
    ox, oz, ory = (_num(g.get('x'), 0.0), _num(g.get('z'), 0.0), _num(g.get('ry'), 0.0)) if g else (0.0, 0.0, 0.0)
    return height_at(p, lx, lz, recs, ox, oz, ory)


HEIGHTS = {'ground': h_ground}
