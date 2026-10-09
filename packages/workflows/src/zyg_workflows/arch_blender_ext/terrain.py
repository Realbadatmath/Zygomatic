# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""terrain — Blender geometry for terrain, hill, slope, plateau,
retaining_wall and berm.

Local frame (see arch_blender_build.build_kind): X along, Y = studio -Z, Z up,
bottom at z=0. A studio plan angle theta is the ordinary counter-clockwise
angle in Blender's XY plane.

The noise is the third copy of the contract in arch_ext/terrain.js and
arch_assistant_ext/terrain.py — the same arithmetic, so a terrain record is
the same landscape in the tab, in the assistant and here.
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


def build_terrain(bm, p, kit):
    N = lambda k, d: kit['num'](p, k, d)  # noqa: E731
    w, d, amp = N('w', 20.0), N('d', 20.0), N('amp', 2.0)
    seed, base = N('seed', 1.0), N('base', 0.0)
    res = max(2, min(96, int(round(N('res', 24.0)))))
    rows = []
    for j in range(res + 1):
        row = []
        for i in range(res + 1):
            x = -w / 2 + i / res * w
            sz = -d / 2 + j / res * d  # studio z
            z = base + amp * value_noise(i / res * 4, j / res * 4, seed)
            row.append(bm.verts.new((x, -sz, z)))
        rows.append(row)
    for j in range(res):
        for i in range(res):
            f = bm.faces.new((rows[j][i], rows[j][i + 1], rows[j + 1][i + 1], rows[j + 1][i]))
            f.material_index = 1
    bm.normal_update()
    return ('', ['mat_grass'])


def build_hill(bm, p, kit):
    N = lambda k, d: kit['num'](p, k, d)  # noqa: E731
    r, h = max(0.2, N('r', 8.0)), N('h', 3.0)
    seg, rings = 32, 12
    apex = bm.verts.new((0.0, 0.0, h))
    ring = []
    for k in range(1, rings + 1):
        rad = r * k / rings
        z = h * 0.5 * (1 + math.cos(math.pi * rad / r))
        ring.append(
            [
                bm.verts.new((math.cos(2 * math.pi * i / seg) * rad, math.sin(2 * math.pi * i / seg) * rad, z))
                for i in range(seg)
            ]
        )
    for i in range(seg):
        j = (i + 1) % seg
        bm.faces.new((apex, ring[0][j], ring[0][i]))
    for k in range(rings - 1):
        A, B = ring[k], ring[k + 1]
        for i in range(seg):
            j = (i + 1) % seg
            bm.faces.new((A[j], A[i], B[i], B[j]))
    ctr = bm.verts.new((0.0, 0.0, 0.0))
    for i in range(seg):
        j = (i + 1) % seg
        bm.faces.new((ctr, ring[-1][i], ring[-1][j]))
    bm.normal_update()
    return ('', [])


def _prism_yz(bm, profile, x0, x1, deg=0.0):
    """A closed (Y, Z) profile swept from X=x0 to X=x1, then turned `deg`
    counter-clockwise about Z (= the studio's plan angle)."""
    c, s = math.cos(math.radians(deg)), math.sin(math.radians(deg))

    def V(x, y, z):
        return bm.verts.new((x * c - y * s, x * s + y * c, z))

    v0 = [V(x0, u, v) for u, v in profile]
    v1 = [V(x1, u, v) for u, v in profile]
    bm.faces.new(v0)
    bm.faces.new(list(reversed(v1)))
    n = len(profile)
    for i in range(n):
        j = (i + 1) % n
        bm.faces.new((v0[i], v0[j], v1[j], v1[i]))
    bm.normal_update()


def build_slope(bm, p, kit):
    N = lambda k, d: kit['num'](p, k, d)  # noqa: E731
    w, d, h, deg = N('w', 10.0), N('d', 10.0), N('h', 2.0), N('dir', 0.0)
    # studio +Z (the direction the ground climbs at dir=0) is Blender -Y
    _prism_yz(bm, [(d / 2, 0.0), (-d / 2, 0.0), (-d / 2, h)], -w / 2, w / 2, deg)
    return ('', [])


def build_plateau(bm, p, kit):
    N = lambda k, d: kit['num'](p, k, d)  # noqa: E731
    w, d, h, batter = N('w', 20.0), N('d', 20.0), N('h', 1.5), N('batter', 0.5)
    b = max(0.0, min(batter * h, w / 2 - 0.05, d / 2 - 0.05))
    tw, td = w / 2 - b, d / 2 - b
    v = [
        bm.verts.new(q)
        for q in (
            (-w / 2, -d / 2, 0.0),
            (w / 2, -d / 2, 0.0),
            (w / 2, d / 2, 0.0),
            (-w / 2, d / 2, 0.0),
            (-tw, -td, h),
            (tw, -td, h),
            (tw, td, h),
            (-tw, td, h),
        )
    ]
    for idx in ((0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7), (4, 5, 6, 7), (0, 3, 2, 1)):
        bm.faces.new([v[i] for i in idx])
    bm.normal_update()
    return ('', [])


def build_retaining_wall(bm, p, kit):
    N = lambda k, d: kit['num'](p, k, d)  # noqa: E731
    ln, h, t, batter = N('len', 10.0), N('h', 1.5), N('t', 0.3), N('batter', 0.1)
    T = t + batter * h
    # the studio section (z, y) mirrored into Blender (Y = -z): the vertical
    # face is at Y = +T/2, the battered back runs from Y = -T/2 up to Y = T/2 - t
    _prism_yz(bm, [(T / 2, 0.0), (-T / 2, 0.0), (T / 2 - t, h), (T / 2, h)], -ln / 2, ln / 2)
    return ('', [])


def build_berm(bm, p, kit):
    N = lambda k, d: kit['num'](p, k, d)  # noqa: E731
    ln, w, h = N('len', 20.0), N('w', 4.0), N('h', 1.2)
    _prism_yz(bm, [(-w / 2, 0.0), (w / 2, 0.0), (0.0, h)], -ln / 2, ln / 2)
    return ('', [])


BUILDERS = {
    'terrain': build_terrain,
    'hill': build_hill,
    'slope': build_slope,
    'plateau': build_plateau,
    'retaining_wall': build_retaining_wall,
    'berm': build_berm,
}
