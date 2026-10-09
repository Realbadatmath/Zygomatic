# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""ground_v3 — ONE sculpted heightfield per drawing, in Blender (2026-09-07).

`ground` is the only geometry this family builds: a lattice mesh whose height at
every vertex is the base roll PLUS the contribution of every `sculpt_*` record in
the drawing, read through kit['records'], with one colour per vertex from
kit['mat_rgb'] so the same mesh is grass on the flat, rock on the steep face,
sand at the water and snow on top. The ten sculpt kinds are VOID: their builders
fill nothing, so they produce an empty mesh object and no geometry at all.

THE ARITHMETIC IS A CONTRACT. `value_noise`, `smoothstep`, `meander_offset`,
`lake_factor`, the ten sculpt functions, `field_at`, `slope_deg` and
`colour_weights` below are the SAME arithmetic as arch_assistant_ext/ground_v3.py
and arch_ext/ground_v3.js, line for line. Change one copy and you have three
landscapes.

Every sculpt function returns (dh, mask): `dh` metres to add (or, for a SET sculpt,
the LEVEL), `mask` 0..1 how much of it is felt there. Two sculpts are SET:
sculpt_flat always, and a sculpt_channel that names level0 AND level1.

Frame (arch_blender_build.build_kind): X along, Y = studio -Z, Z up, the record's
x/z the centre in plan. A studio local point (lx, H, lz) is (lx, -lz, H) here.
"""

import math

RES_MAX = 200
RES_MIN = 4
BASE_CELL = 50.0
FEATHER_FRAC = 0.20
COLOUR_BAND = 2.0
SLOPE_BAND = 8.0
WATER_SOIL = 0.30
COLOUR_MATS = ('mat_grass', 'mat_sand', 'mat_rock', 'mat_snow', 'mat_soil')
SAND_KINDS = ('sculpt_dunes', 'sculpt_shelf')

VOID_KINDS = [
    'sculpt_peak',
    'sculpt_ridge',
    'sculpt_mesa',
    'sculpt_cut',
    'sculpt_channel',
    'sculpt_basin',
    'sculpt_flat',
    'sculpt_step',
    'sculpt_dunes',
    'sculpt_shelf',
]


def _num(v, d):
    try:
        f = float(v)
        return f if math.isfinite(f) else d
    except (TypeError, ValueError):
        return d


def _N(p, k, d):
    return _num((p or {}).get(k), d)


# ── the shared noise ─────────────────────────────────────────────────────────
def _hash(ix, iy, seed):
    v = math.sin(ix * 127.1 + iy * 311.7 + seed * 74.7) * 43758.5453
    return v - math.floor(v)


def value_noise(u, v, seed):
    ix, iy = math.floor(u), math.floor(v)
    fx, fy = u - ix, v - iy
    a = _hash(ix, iy, seed)
    b = _hash(ix + 1, iy, seed)
    c = _hash(ix, iy + 1, seed)
    e = _hash(ix + 1, iy + 1, seed)
    return a + (b - a) * fx + (c - a) * fy + (a - b - c + e) * fx * fy


def meander_offset(t, meander, seed):
    return (
        meander
        * math.sin(math.pi * t)
        * (0.6 * math.sin(2 * math.pi * t * 1.5) + 0.4 * (2 * value_noise(t * 4, seed, seed) - 1))
    )


def lake_factor(a, wobble, seed):
    return 1 + wobble * (2 * value_noise(math.cos(a) * 2 + 2, math.sin(a) * 2 + 2, seed) - 1)


# ── the feather ──────────────────────────────────────────────────────────────
def clamp(v, lo, hi):
    return lo if v < lo else (hi if v > hi else v)


def smoothstep(t):
    t = clamp(t, 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def band(dist, fe):
    if fe <= 1e-9:
        return 1.0 if dist > 0.0 else 0.0
    return smoothstep(dist / fe)


def feather_of(p, size):
    f = _N(p, 'feather', 0.0)
    if f <= 0.0:
        f = FEATHER_FRAC * size
    return clamp(f, 0.0, size)


# ── the ten sculpts: (dh, mask) in the sculpt's own LOCAL plan frame ────────
def s_peak(p, lx, lz):
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
    """A sculpt_channel's SET bed, or None: (level0, level1) when the record
    names BOTH. Then the channel SETS the ground to a straight fall from level0
    (local x = -len/2) to level1 (+len/2) instead of digging `depth` below the
    roll it crosses, so the sloping water over it is never surfaced through."""
    p = p or {}
    a, b = p.get('level0'), p.get('level1')
    if a is None or b is None:
        return None
    return _num(a, 0.0), _num(b, 0.0)


def s_channel(p, lx, lz):
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
    """The one SET sculpt: `dh` is the LEVEL, not a delta. Byte-for-byte the
    weight arch_assistant._sculpt_flat_weight uses."""
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


# ── H(lx, lz) = base + the sum of the sculpts ───────────────────────────────
def base_height(p, lx, lz):
    w = max(1.0, abs(_N(p, 'w', 200.0)))
    dd = max(1.0, abs(_N(p, 'd', 200.0)))
    return _N(p, 'base', 0.0) + _N(p, 'amp', 1.5) * value_noise(
        (lx + w / 2) / BASE_CELL, (lz + dd / 2) / BASE_CELL, _N(p, 'seed', 1.0)
    )


def field_at(p, lx, lz, records, ox=0.0, oz=0.0, ory=0.0):
    """(H, sand) at a point in the GROUND's local plan frame. The sculpts are in
    WORLD coordinates, so the point goes back out through the ground's own origin
    and yaw first — the inverse of arch_assistant.world_to_local."""
    h = base_height(p, lx, lz)
    c, s = math.cos(ory), math.sin(ory)
    wx = ox + lx * c + lz * s
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


def height_at(p, lx, lz, records, ox=0.0, oz=0.0, ory=0.0):
    return field_at(p, lx, lz, records, ox, oz, ory)[0]


def slope_deg(hs, n, i, j, stepx, stepz):
    res = n - 1
    i0, i1 = (i - 1 if i > 0 else i), (i + 1 if i < res else i)
    j0, j1 = (j - 1 if j > 0 else j), (j + 1 if j < res else j)
    gx = (hs[j * n + i1] - hs[j * n + i0]) / max(1e-6, (i1 - i0) * stepx)
    gz = (hs[j1 * n + i] - hs[j0 * n + i]) / max(1e-6, (j1 - j0) * stepz)
    return math.degrees(math.atan(math.hypot(gx, gz)))


def colour_weights(h, slope, sand, water_h, snow_h, grass_max_slope):
    """(grass, sand, rock, snow, soil), summing to 1 — the same five lines the
    tab and the assistant run."""
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


def ground_record(p, records):
    """The record whose params ARE `p` — the builder is handed the params, but
    the sculpts around it are in world coordinates, so it needs the origin."""
    for o in records or ():
        if isinstance(o, dict) and o.get('kind') == 'ground' and o.get('p') is p:
            return o
    for o in records or ():
        if isinstance(o, dict) and o.get('kind') == 'ground':
            return o
    return None


# ── the one builder with geometry in this family ────────────────────────────
def build_ground(bm, p, kit):
    recs = kit.get('records') or []
    w = max(1.0, abs(_N(p, 'w', 200.0)))
    dd = max(1.0, abs(_N(p, 'd', 200.0)))
    res = int(clamp(round(_N(p, 'res', 100.0)), RES_MIN, RES_MAX))
    n = res + 1
    g0 = ground_record(p, recs)
    ox = _num(g0.get('x'), 0.0) if g0 else 0.0
    oz = _num(g0.get('z'), 0.0) if g0 else 0.0
    ory = _num(g0.get('ry'), 0.0) if g0 else 0.0

    hs = [0.0] * (n * n)
    sd = [0.0] * (n * n)
    verts = []
    for j in range(n):
        lz = -dd / 2 + j / res * dd
        for i in range(n):
            lx = -w / 2 + i / res * w
            h, sand = field_at(p, lx, lz, recs, ox, oz, ory)
            hs[j * n + i] = h
            sd[j * n + i] = sand
            verts.append(bm.verts.new((lx, -lz, h)))  # studio (lx, h, lz)
    bm.verts.ensure_lookup_table()
    # CCW seen from +Z (up): (i,j) -> (i,j+1) -> (i+1,j+1) -> (i+1,j),
    # because a growing j walks towards -Y here.
    for j in range(res):
        for i in range(res):
            v00 = j * n + i
            v10 = v00 + 1
            v01 = v00 + n
            v11 = v01 + 1
            bm.faces.new((verts[v00], verts[v01], verts[v10]))
            bm.faces.new((verts[v10], verts[v01], verts[v11]))

    mat_rgb = kit.get('mat_rgb') or (lambda m: (0.6, 0.6, 0.6))
    pal = [tuple(mat_rgb(m))[:3] for m in COLOUR_MATS]
    water_h = _N(p, 'water_h', -0.15)
    snow_h = _N(p, 'snow_h', 60.0)
    gms = _N(p, 'grass_max_slope', 32.0)
    stepx, stepz = w / res, dd / res
    vcolors = []
    for j in range(n):
        for i in range(n):
            k = j * n + i
            ws = colour_weights(hs[k], slope_deg(hs, n, i, j, stepx, stepz), sd[k], water_h, snow_h, gms)
            vcolors.append(tuple(sum(ws[m] * pal[m][ch] for m in range(5)) for ch in range(3)))
    return ('', [], vcolors)


# ── the ten VOID sculpts: no geometry at all ────────────────────────────────
def build_void(bm, p, kit):
    """A sculpt is a PARAMETER OF THE GROUND, not a thing standing on it: the
    ground mesh already carries its shape, so there is nothing to build. An
    empty bm gives an empty mesh object — arch_blender_build handles that
    cleanly (remove_doubles and recalc_face_normals on nothing are no-ops)."""
    return ('', [])


BUILDERS = {'ground': build_ground}
for _k in VOID_KINDS:
    BUILDERS[_k] = build_void
