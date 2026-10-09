# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""forests — Blender geometry for the four one-record planting kinds.

Local frame (see arch_blender_build.build_kind): X along, Y = studio -Z
(depth), Z up, bottom at z=0. A spot the studio calls (x, z) is therefore
(x, -z) here.

Material slots: 0 is the record's own material, then the ids returned as
`extra` fill slots 1, 2, ... — slot 1 is mat_foliage (every crown) and slot 2
is mat_timber (every trunk), matching the `sub` overrides in forests.js.

THE SCATTER IS A CONTRACT. _hash / _forest_spots / _line_spots /
_orchard_spots / _scatter_spots below are the same arithmetic as
arch_assistant_ext/forests.py and arch_ext/forests.js. They are written out
rather than imported because this module is executed inside Blender, which has
no access to the assistant's dependencies. Change one copy and the three
engines grow different woods; tests_arch_ext/test_forests.py is what notices.

THE GROUND DRAPES, THE TREES DO NOT LEAN (2026-09-07). p['gx'] / p['gz'] are
the slope of the ground plane under the record along its LOCAL x and z (rise
per metre). Every tree's base sits at y = gx*lx + gz*lz — here z0 of the trunk
and the centre of the crown both move by it — and the trunk stays VERTICAL.
The record is never given rx/rz for this: tilting it would lean a whole wood.
"""

import math

FOLIAGE, TIMBER = 1, 2
FOREST_MAX, LINE_MAX, SCATTER_MAX = 3000, 400, 2000
TRUNK_SEG, CONE_SEG, CROWN_USEG, CROWN_VSEG = 6, 8, 8, 4
ORCHARD_RC = 1.6
_MATS = ['mat_foliage', 'mat_timber']


def _clamp(v, lo, hi):
    return lo if v < lo else (hi if v > hi else v)


def _hash(ix, iy, seed):
    v = math.sin(ix * 127.1 + iy * 311.7 + seed * 74.7) * 43758.5453
    return v - math.floor(v)


def _forest_spots(w, d, dens, mix, h, jitter, seed):
    s = math.sqrt(1.0 / dens)
    n = max(1, min(FOREST_MAX, int(math.floor(w * d * dens + 0.5))))
    nx = max(1, int(math.floor(w / s + 0.5)))
    x0, z0 = -w / 2 + s / 2, -d / 2 + s / 2
    out = []
    for k in range(n):
        j, i = divmod(k, nx)
        out.append(
            (
                x0 + i * s + (2 * _hash(i, j, seed) - 1) * jitter * s,
                z0 + j * s + (2 * _hash(i, j, seed + 1) - 1) * jitter * s,
                1 if _hash(i, j, seed + 2) < mix else 0,
                h * (0.7 + 0.6 * _hash(i, j, seed + 3)),
                0.8 + 0.4 * _hash(i, j, seed + 4),
            )
        )
    return out


def _line_spots(length, spacing, h, jitter, seed):
    n = max(1, min(LINE_MAX, int(math.floor(length / spacing)) + 1))
    return [
        (
            -length / 2 + i * spacing,
            (2 * _hash(i, 0, seed) - 1) * jitter,
            h * (0.85 + 0.3 * _hash(i, 0, seed + 3)),
            0.8 + 0.4 * _hash(i, 0, seed + 4),
        )
        for i in range(n)
    ]


def _orchard_spots(w, d, spacing):
    nx = int(math.floor(w / spacing)) + 1
    nz = int(math.floor(d / spacing)) + 1
    x0, z0 = -(nx - 1) * spacing / 2, -(nz - 1) * spacing / 2
    return [(x0 + i * spacing, z0 + j * spacing) for j in range(nz) for i in range(nx)]


def _scatter_spots(w, d, n, seed, r):
    return [
        (-w / 2 + _hash(i, 0, seed) * w, -d / 2 + _hash(i, 0, seed + 1) * d, r * (0.6 + 0.8 * _hash(i, 0, seed + 2)))
        for i in range(n)
    ]


# ── one tree: kind 0 deciduous, 1 conifer, 2 poplar. (cx, cz) is a STUDIO spot ──
# cf scales the CROWN only (0.8-1.2 from the hash); y0 is the ground under the tree.
def _tree(bm, kit, kind, cx, cz, h, cf=1.0, y0=0.0):
    h = max(0.5, h)
    cf = cf if cf > 0 else 1.0
    cy = -cz
    if kind == 0:
        rc = 0.36 * h * cf
        kit['add_cylinder'](bm, 0.05 * h, h - 2 * rc, z0=y0, seg=TRUNK_SEG, cx=cx, cy=cy, r_top=0.04 * h, mi=TIMBER)
        kit['add_sphere'](bm, rc, y0 + h - rc, cx=cx, cy=cy, useg=CROWN_USEG, vseg=CROWN_VSEG, mi=FOLIAGE)
    else:
        r = (0.12 if kind == 2 else 0.25) * h * cf
        kit['add_cylinder'](bm, 0.045 * h, 0.15 * h, z0=y0, seg=TRUNK_SEG, cx=cx, cy=cy, r_top=0.035 * h, mi=TIMBER)
        kit['add_cylinder'](bm, r, 0.85 * h, z0=y0 + 0.15 * h, seg=CONE_SEG, cx=cx, cy=cy, r_top=0.0, mi=FOLIAGE)


def build_forest(bm, p, kit):
    N = lambda k, d: kit['num'](p, k, d)
    w, d = _clamp(N('w', 100.0), 1.0, 600.0), _clamp(N('d', 100.0), 1.0, 600.0)
    dens = _clamp(N('density', 0.04), 0.0005, 4.0)
    mix = _clamp(N('mix', 0.5), 0.0, 1.0)
    h = _clamp(N('h', 14.0), 0.5, 120.0)
    jitter = _clamp(N('jitter', 0.45), 0.0, 2.0)
    gx, gz = N('gx', 0.0), N('gz', 0.0)
    for x, z, conifer, hk, cf in _forest_spots(w, d, dens, mix, h, jitter, N('seed', 1.0)):
        _tree(bm, kit, 1 if conifer else 0, x, z, hk, cf, gx * x + gz * z)
    return ('', list(_MATS))


def build_tree_line(bm, p, kit):
    N = lambda k, d: kit['num'](p, k, d)
    L = _clamp(N('len', 60.0), 1.0, 2000.0)
    sp = _clamp(N('spacing', 6.0), 1.0, 100.0)
    kind = max(0, min(2, int(round(N('kind', 0.0)))))
    h = _clamp(N('h', 10.0), 0.5, 120.0)
    jitter = _clamp(N('jitter', 0.2), 0.0, 10.0)
    gx, gz = N('gx', 0.0), N('gz', 0.0)
    for x, z, hk, cf in _line_spots(L, sp, h, jitter, N('seed', 1.0)):
        _tree(bm, kit, kind, x, z, hk, cf, gx * x + gz * z)
    return ('', list(_MATS))


def build_orchard(bm, p, kit):
    N = lambda k, d: kit['num'](p, k, d)
    w, d = _clamp(N('w', 40.0), 1.0, 600.0), _clamp(N('d', 30.0), 1.0, 600.0)
    sp = _clamp(N('spacing', 5.0), 1.0, 100.0)
    h = _clamp(N('h', 4.0), 1.0, 40.0)
    gx, gz = N('gx', 0.0), N('gz', 0.0)
    rc = min(ORCHARD_RC, h * 0.4)
    for x, z in _orchard_spots(w, d, sp):
        y0 = gx * x + gz * z
        kit['add_cylinder'](bm, 0.09 * h, h - 2 * rc, z0=y0, seg=TRUNK_SEG, cx=x, cy=-z, r_top=0.07 * h, mi=TIMBER)
        kit['add_sphere'](bm, rc, y0 + h - rc, cx=x, cy=-z, useg=CROWN_USEG, vseg=CROWN_VSEG, mi=FOLIAGE)
    return ('', list(_MATS))


def build_undergrowth(bm, p, kit):
    N = lambda k, d: kit['num'](p, k, d)
    w, d = _clamp(N('w', 40.0), 1.0, 600.0), _clamp(N('d', 40.0), 1.0, 600.0)
    n = max(1, min(SCATTER_MAX, int(round(N('count', 60.0)))))
    r = _clamp(N('r', 0.8), 0.05, 8.0)
    gx, gz = N('gx', 0.0), N('gz', 0.0)
    for x, z, rr in _scatter_spots(w, d, n, N('seed', 1.0), r):
        kit['add_sphere'](
            bm, rr, gx * x + gz * z + 0.6 * rr, cx=x, cy=-z, useg=CROWN_USEG, vseg=CROWN_VSEG, sz=0.6, mi=FOLIAGE
        )
    return ('', list(_MATS))


BUILDERS = {
    'forest': build_forest,
    'tree_line': build_tree_line,
    'orchard': build_orchard,
    'undergrowth': build_undergrowth,
}
