# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""rivers_lakes — Blender geometry for river, lake and waterfall.

Local frame (see arch_blender_build.build_kind): X along, Y = studio -Z
(depth), Z up. These three DIG, so their meshes reach below z=0 exactly as
arch_ext/rivers_lakes.js does in the tab.

The noise and the two shape functions are the third copy of the contract in
arch_ext/rivers_lakes.js and arch_assistant_ext/rivers_lakes.py — the same
arithmetic, so a river bends the same way in all three engines.
"""

import math


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


def lake_shore(rx, rz, wobble, shore):
    return max(0.05, min(shore, min(rx, rz) * (1 - wobble) * 0.4))


def lake_rim(rx, rz, wobble, shore, rim):
    return max(0.05, min(max(0.05, rim), lake_shore(rx, rz, wobble, shore)))


BANK_GRASS = 0.4


def channel_section(w, dep, bank):
    """Outer bank to outer bank: [(z, y)] x 6 — the top BANK_GRASS of each bank
    slope is its own strip (grass), the rest plus the bed is gravel."""
    g = BANK_GRASS
    return [
        (-(w / 2 + bank), 0.0),
        (-(w / 2 + bank * (1 - g)), -g * dep),
        (-w / 2, -dep),
        (w / 2, -dep),
        (w / 2 + bank * (1 - g), -g * dep),
        (w / 2 + bank, 0.0),
    ]


def _box(kit, bm, w, h, dp, x, y, z, mi=0):
    """A studio box (w, h, dp) centred at (x, y, z) in the tab's frame."""
    kit['add_box_c'](bm, max(w, 1e-4), max(dp, 1e-4), max(h, 1e-4), cx=x, cy=-z, z0=y - max(h, 1e-4) / 2, mi=mi)


def build_river(bm, p, kit):
    N = lambda k, d: kit['num'](p, k, d)  # noqa: E731
    L, w = max(1.0, N('len', 60.0)), max(0.5, N('w', 12.0))
    dep, mea = max(0.2, N('depth', 2.0)), max(0.0, N('meander', 6.0))
    seed, bank = N('seed', 1.0), max(0.05, N('bank', 2.0))
    seg = max(4, min(200, int(round(N('seg', 24.0)))))
    sec = channel_section(w, dep, bank)
    npt = len(sec)
    hw = (w + bank) / 2
    rows, wrows = [], []
    for i in range(seg + 1):
        t = i / seg
        x = -L / 2 + t * L
        zc = meander_offset(t, mea, seed)
        rows.append([bm.verts.new((x, -(zc + sec[j][0]), sec[j][1])) for j in range(npt)])
        wrows.append([bm.verts.new((x, -(zc - hw), -0.15)), bm.verts.new((x, -(zc + hw), -0.15))])
    for i in range(seg):
        for j in range(npt - 1):
            f = bm.faces.new((rows[i][j], rows[i][j + 1], rows[i + 1][j + 1], rows[i + 1][j]))
            # strips 0 and npt-2 are the grassy tops of the two banks
            f.material_index = 1 if (j == 0 or j == npt - 2) else 2
        f = bm.faces.new((wrows[i][0], wrows[i][1], wrows[i + 1][1], wrows[i + 1][0]))
        f.material_index = 3
    bm.normal_update()
    return ('', ['mat_grass', 'mat_gravel', 'mat_water'])


def build_lake(bm, p, kit):
    N = lambda k, d: kit['num'](p, k, d)  # noqa: E731
    rx, rz = max(0.5, N('rx', 30.0)), max(0.5, N('rz', 20.0))
    dep = max(0.2, N('depth', 3.0))
    wob = max(0.0, min(0.9, N('wobble', 0.25)))
    seed = N('seed', 1.0)
    seg = max(8, min(256, int(round(N('seg', 48.0)))))
    sh = lake_shore(rx, rz, wob, max(0.1, N('shore', 3.0)))
    rw = lake_rim(rx, rz, wob, max(0.1, N('shore', 3.0)), N('rim', 1.0))
    O, M, B, W, S = [], [], [], [], []
    for i in range(seg):
        a = 2 * math.pi * i / seg
        m = lake_factor(a, wob, seed)
        X, Z = rx * math.cos(a) * m, -rz * math.sin(a) * m
        r = max(1e-4, math.hypot(X, Z))
        f1 = max(0.05, (r - sh) / r)
        f2 = max(0.02, (r - 2 * sh) / r)
        fw = f1 + (f2 - f1) * min(1.0, 0.15 / dep)
        fs = max(0.05, (r - rw) / r)
        O.append((X, Z))
        M.append((X * f1, Z * f1))
        B.append((X * f2, Z * f2))
        W.append((X * fw, Z * fw))
        S.append((X * fs, Z * fs))

    def V(pt, z):
        return bm.verts.new((pt[0], -pt[1], z))

    mv = [V(q, 0.0) for q in M]
    bv = [V(q, -dep) for q in B]
    ctr = bm.verts.new((0.0, 0.0, -dep))
    for i in range(seg):
        j = (i + 1) % seg
        f = bm.faces.new((mv[i], bv[i], bv[j], mv[j]))
        f.material_index = 1
        f = bm.faces.new((ctr, bv[j], bv[i]))
        f.material_index = 1
    wv = [V(q, -0.15) for q in W]
    wc = bm.verts.new((0.0, 0.0, -0.15))
    for i in range(seg):
        j = (i + 1) % seg
        f = bm.faces.new((wc, wv[i], wv[j]))
        f.material_index = 2
    it = [V(q, 0.02) for q in S]
    ot = [V(q, 0.02) for q in O]
    ib = [V(q, 0.0) for q in S]
    ob = [V(q, 0.0) for q in O]
    for i in range(seg):
        j = (i + 1) % seg
        for quad in (
            (it[i], ot[i], ot[j], it[j]),
            (ib[i], ib[j], ob[j], ob[i]),
            (ot[i], ob[i], ob[j], ot[j]),
            (it[i], it[j], ib[j], ib[i]),
        ):
            f = bm.faces.new(quad)
            f.material_index = 3
    bm.normal_update()
    return ('', ['mat_soil', 'mat_water', 'mat_sand'])


def build_waterfall(bm, p, kit):
    N = lambda k, d: kit['num'](p, k, d)  # noqa: E731
    w, h = max(0.5, N('w', 8.0)), max(1.0, N('h', 12.0))
    dep, pr = max(0.2, N('depth', 2.0)), max(1.0, N('pool_r', 8.0))
    xf = -max(0.6, pr * 0.6)
    kit['add_cylinder'](bm, pr * 0.7, dep, z0=-dep, seg=32, cx=0.0, cy=0.0, r_top=pr, mi=0)
    kit['add_cylinder'](bm, pr * 0.92, 0.03, z0=-0.16, seg=32, cx=0.0, cy=0.0, mi=2)
    _box(kit, bm, 0.3, h, w, xf, h / 2, 0.0, mi=2)
    _box(kit, bm, 2.0, 1.0, w, xf - 0.85, h + 0.5, 0.0, mi=1)
    bm.normal_update()
    return ('', ['mat_rock', 'mat_water'])


BUILDERS = {'river': build_river, 'lake': build_lake, 'waterfall': build_waterfall}
