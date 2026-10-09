# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""water_v3 — the water that SITS ON the v3 sculpted bed, in Blender (2026-09-07).

Three water-only kinds, every face on the `mat_water` slot. water_path and
water_plane are 0.02 m thin skins; water_body is a single upward fan:

    water_body   {rx, rz, wobble, seed, seg}    a lake / pond surface
    water_path   {len, w, meander, seed, seg,   a river / stream reach surface
                  level0, level1}               (the pair makes it SLOPE)
    water_plane  {w, d, wave, seed, res}        the sea surface

The bed is NOT built here — it is a sculpt of the one v3 ground
(sculpt_basin / sculpt_channel / sculpt_shelf), which ground_v3's builder cuts.

THE SHORELINE IS A CONTRACT. `_hash`/`value_noise` are verbatim from terrain;
`meander_offset`/`lake_factor` verbatim from ground_v3, so a water_body sits on
its sculpt_basin's rim and a water_path in its sculpt_channel's trough. Four
copies of one arithmetic: this file, arch_ext/water_v3.js,
arch_assistant_ext/water_v3.py and ground_v3.

Frame: bmesh (x, y, z) = studio (x, -z, y). The water SURFACE is z = 0 in the
record's local frame — the record's own y is the water level.
"""

import math

WATER_T = 0.02


def _N(kit, p, k, d):
    return kit['num'](p, k, d)


def _clamp(v, lo, hi):
    return lo if v < lo else (hi if v > hi else v)


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


def _V(bm, x, z, y):
    """A vertex at studio (x, y_up, z)."""
    return bm.verts.new((x, -z, y))


def _face(bm, verts):
    f = bm.faces.new(verts)
    f.material_index = 1  # slot 1 = mat_water (slot 0 is the record's own)
    return f


def _num_or(v):
    try:
        f = float(v)
        return f if math.isfinite(f) else 0.0
    except (TypeError, ValueError):
        return 0.0


def path_levels(p):
    """A water_path's FALL, or None: (level0, level1) is the surface height at
    the reach's start (local x = -len/2) and end (+len/2), in the RECORD's own
    frame. The bed under it is a SET sculpt_channel of the same two levels
    (ground_v3.channel_levels), so bed and water fall together — held at one
    level the water goes under the valley's own roll half way along."""
    p = p or {}
    a, b = p.get('level0'), p.get('level1')
    if a is None or b is None:
        return None
    return _num_or(a), _num_or(b)


def path_y(p, t):
    """The water_path's surface height at station t, in the record's frame."""
    lv = path_levels(p)
    return 0.0 if lv is None else lv[0] + (lv[1] - lv[0]) * t


# ── the three kinds ──────────────────────────────────────────────────────────
def build_water_body(bm, p, kit):
    """THE LAKE IS ONE FAN, NOT A DISC OF ICE. It used to be a closed skin — a
    top fan, a second fan 0.02 m under it and a rim — and the studio drew it as a
    radial pattern of dark and light wedges. There is nothing for the underside
    to do: the record's y IS the water level, the basin bed is `shore` lower, and
    mat_water is two-sided. So one fan of `seg` triangles at z = +WATER_T."""
    rx = max(0.5, _N(kit, p, 'rx', 30.0))
    rz = max(0.5, _N(kit, p, 'rz', 20.0))
    wob = _clamp(_N(kit, p, 'wobble', 0.25), 0.0, 0.9)
    seed = _N(kit, p, 'seed', 1.0)
    seg = int(_clamp(round(_N(kit, p, 'seg', 48.0)), 8, 256))
    ring = []
    for i in range(seg):
        a = 2 * math.pi * i / seg
        m = lake_factor(a, wob, seed)
        ring.append((rx * math.cos(a) * m, -rz * math.sin(a) * m))
    cx = sum(q[0] for q in ring) / seg
    cz = sum(q[1] for q in ring) / seg
    tc = _V(bm, cx, cz, WATER_T)
    tv = [_V(bm, q[0], q[1], WATER_T) for q in ring]
    for i in range(seg):
        _face(bm, (tc, tv[i], tv[(i + 1) % seg]))  # one fan, wound face-up
    bm.normal_update()
    return ('', ['mat_water'])


def build_water_path(bm, p, kit):
    ln = max(1.0, _N(kit, p, 'len', 60.0))
    w = max(0.2, _N(kit, p, 'w', 8.0))
    mea = max(0.0, _N(kit, p, 'meander', 6.0))
    seed = _N(kit, p, 'seed', 1.0)
    seg = int(_clamp(round(_N(kit, p, 'seg', 24.0)), 2, 200))
    tl, tr, bl, br = [], [], [], []
    for i in range(seg + 1):
        t = i / seg
        x = -ln / 2 + t * ln
        zc = meander_offset(t, mea, seed)
        sy = path_y(p, t)
        tl.append(_V(bm, x, zc - w / 2, sy))
        tr.append(_V(bm, x, zc + w / 2, sy))
        bl.append(_V(bm, x, zc - w / 2, sy - WATER_T))
        br.append(_V(bm, x, zc + w / 2, sy - WATER_T))
    for i in range(seg):
        _face(bm, (tl[i], tr[i], tr[i + 1], tl[i + 1]))  # top
        _face(bm, (bl[i], bl[i + 1], br[i + 1], br[i]))  # bottom
        _face(bm, (tl[i], tl[i + 1], bl[i + 1], bl[i]))  # left bank
        _face(bm, (tr[i], br[i], br[i + 1], tr[i + 1]))  # right bank
    _face(bm, (tl[0], bl[0], br[0], tr[0]))  # upstream cap
    _face(bm, (tl[seg], tr[seg], br[seg], bl[seg]))  # downstream cap
    bm.normal_update()
    return ('', ['mat_water'])


def build_water_plane(bm, p, kit):
    w = max(1.0, _N(kit, p, 'w', 200.0))
    dd = max(1.0, _N(kit, p, 'd', 120.0))
    wave = max(0.0, _N(kit, p, 'wave', 0.15))
    seed = _N(kit, p, 'seed', 1.0)
    res = int(_clamp(round(_N(kit, p, 'res', 24.0)), 2, 200))
    top, bot = [], []
    for j in range(res + 1):
        rt, rb = [], []
        z = -dd / 2 + j / res * dd
        for i in range(res + 1):
            x = -w / 2 + i / res * w
            h = wave * (2 * value_noise(i / res * 8, j / res * 8, seed) - 1)
            rt.append(_V(bm, x, z, h))
            rb.append(_V(bm, x, z, h - WATER_T))
        top.append(rt)
        bot.append(rb)
    for j in range(res):
        for i in range(res):
            _face(bm, (top[j][i], top[j][i + 1], top[j + 1][i + 1], top[j + 1][i]))
            _face(bm, (bot[j][i], bot[j + 1][i], bot[j + 1][i + 1], bot[j][i + 1]))
    for i in range(res):  # the four rim strips
        _face(bm, (top[0][i], bot[0][i], bot[0][i + 1], top[0][i + 1]))
        _face(bm, (top[res][i + 1], bot[res][i + 1], bot[res][i], top[res][i]))
        _face(bm, (top[i + 1][0], bot[i + 1][0], bot[i][0], top[i][0]))
        _face(bm, (top[i][res], bot[i][res], bot[i + 1][res], top[i + 1][res]))
    bm.normal_update()
    return ('', ['mat_water'])


BUILDERS = {
    'water_body': build_water_body,
    'water_path': build_water_path,
    'water_plane': build_water_plane,
}
