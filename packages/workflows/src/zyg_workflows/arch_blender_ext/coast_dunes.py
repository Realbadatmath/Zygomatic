# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""coast_dunes — Blender geometry for sea, beach, dune_field, island and
breakwater.

Local frame (see arch_blender_build.build_kind): X along, Y = studio -Z
(depth), Z up, bottom normally at z=0. The sea is the exception: it digs, so
its bed reaches below z=0 exactly as the tab's arGeom does — the same rule
water_leisure's pool and canal follow. `_pt` maps a studio point straight
into that frame so the two engines stay line for line.

The noise is the third copy of the contract in arch_ext/coast_dunes.js and
arch_assistant_ext/coast_dunes.py — the same arithmetic, so a coast is the
same coast in the tab, in the assistant and here.

TWO MATERIALS OVER ONE MESH. The beach's first 15% of width (the rows nearest
the water) is wet sand — mat_soil — and every dune quad whose four corners
average above 70% of h is marram grass — mat_grass. Both are only a
material_index on faces of the SAME vertices, so a beach and a dune field
occupy exactly the box they did before the looks were added; the tab does it
with an index subset of one position array, which comes to the same thing.
"""

import math

BX, BZ = 24, 20  # the beach lattice, same as the tab's
WET = 0.15  # wet sand: the share of the width at the water edge
WETJ = round(BZ * WET)  # ... which is exactly 3 of the 20 rows
MARRAM = 0.70  # marram grass above this share of a dune's h


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


def _pt(bm, x, y, z, rot=None):
    """A studio point (x right, y up, z south) as a Blender vertex. `rot` is
    (cos, sin) of a studio plan angle: the tab's g.rotateY(theta) turns +X
    towards -Z, so x' = x*cos + z*sin and z' = -x*sin + z*cos."""
    if rot is not None:
        c, s = rot
        x, z = x * c + z * s, -x * s + z * c
    return bm.verts.new((x, -z, y))


def _quad(bm, a, b, c, e, mi=0, rot=None):
    """A face through four studio points."""
    f = bm.faces.new([_pt(bm, q[0], q[1], q[2], rot) for q in (a, b, c, e)])
    f.material_index = mi
    return f


def _grid_faces(bm, rows, mi=0, pick=None):
    """The lattice of a height field. `pick(j, i) -> material index` overrides
    `mi` per quad — that is how the wet band and the marram crests get their
    own material without moving a single vertex."""
    for j in range(len(rows) - 1):
        for i in range(len(rows[0]) - 1):
            f = bm.faces.new((rows[j][i], rows[j][i + 1], rows[j + 1][i + 1], rows[j + 1][i]))
            f.material_index = mi if pick is None else pick(j, i)


def _box(kit, bm, w, h, dp, x, y, z, mi=0):
    kit['add_box_c'](bm, max(w, 1e-4), max(dp, 1e-4), max(h, 1e-4), cx=x, cy=-z, z0=y - max(h, 1e-4) / 2, mi=mi)


# ── the sea ─────────────────────────────────────────────────────────────────
def build_sea(bm, p, kit):
    N = lambda k, d: kit['num'](p, k, d)  # noqa: E731
    w, d = max(1.0, N('w', 200.0)), max(1.0, N('d', 200.0))
    dep, wave, seed = max(0.4, N('depth', 6.0)), max(0.0, N('wave', 0.15)), N('seed', 1.0)
    res = max(2, min(96, int(round(N('res', 32.0)))))
    rows = []
    for j in range(res + 1):
        row = []
        for i in range(res + 1):
            row.append(
                _pt(
                    bm,
                    -w / 2 + i / res * w,
                    -0.3 + wave * (2 * value_noise(i / res * 8, j / res * 8, seed) - 1),
                    -d / 2 + j / res * d,
                )
            )
        rows.append(row)
    _grid_faces(bm, rows, 1)
    _box(kit, bm, w, 0.2, d, 0.0, -dep, 0.0, 2)
    bm.normal_update()
    return ('', ['mat_water', 'mat_sand'])


# ── the beach ───────────────────────────────────────────────────────────────
def _beach_field(h, seed):
    raw, mx = [], 1e-9
    for j in range(BZ + 1):
        row = []
        for i in range(BX + 1):
            prof = 0.5 * (1 - math.cos(math.pi * j / BZ))
            amp = 1 - 0.15 * (2 * value_noise(i / BX * 3, 4.5, seed) - 1)
            v = prof * amp
            row.append(v)
            mx = max(mx, v)
        raw.append(row)
    return raw, h / mx


def build_beach(bm, p, kit):
    N = lambda k, d: kit['num'](p, k, d)  # noqa: E731
    L, w = max(1.0, N('len', 60.0)), max(1.0, N('w', 25.0))
    h, seed = max(0.05, N('h', 2.0)), N('seed', 1.0)
    raw, sc = _beach_field(h, seed)
    X = lambda i: -L / 2 + i / BX * L  # noqa: E731
    Z = lambda j: -w / 2 + j / BZ * w  # noqa: E731
    rows = [[_pt(bm, X(i), raw[j][i] * sc, Z(j)) for i in range(BX + 1)] for j in range(BZ + 1)]
    _grid_faces(bm, rows, 1, lambda j, i: 2 if j < WETJ else 1)  # wet sand at the water edge
    for i in range(BX):  # the back scarp
        _quad(
            bm,
            (X(i + 1), 0, Z(BZ)),
            (X(i), 0, Z(BZ)),
            (X(i), raw[BZ][i] * sc, Z(BZ)),
            (X(i + 1), raw[BZ][i + 1] * sc, Z(BZ)),
            1,
        )
    for j in range(BZ):  # the two ends
        _quad(
            bm,
            (X(0), 0, Z(j + 1)),
            (X(0), 0, Z(j)),
            (X(0), raw[j][0] * sc, Z(j)),
            (X(0), raw[j + 1][0] * sc, Z(j + 1)),
            1,
        )
        _quad(
            bm,
            (X(BX), 0, Z(j)),
            (X(BX), 0, Z(j + 1)),
            (X(BX), raw[j + 1][BX] * sc, Z(j + 1)),
            (X(BX), raw[j][BX] * sc, Z(j)),
            1,
        )
    _quad(bm, (-L / 2, 0, -w / 2), (-L / 2, 0, w / 2), (L / 2, 0, w / 2), (L / 2, 0, -w / 2), 1)
    bm.normal_update()
    return ('', ['mat_sand', 'mat_soil'])


# ── the dune field ──────────────────────────────────────────────────────────
def build_dune_field(bm, p, kit):
    N = lambda k, d: kit['num'](p, k, d)  # noqa: E731
    w, d = max(1.0, N('w', 120.0)), max(1.0, N('d', 60.0))
    h, seed, deg = max(0.05, N('h', 8.0)), N('seed', 1.0), N('dir', 0.0)
    res = max(2, min(96, int(round(N('res', 40.0)))))
    raw, mx = [], 1e-9
    for j in range(res + 1):
        row = []
        for i in range(res + 1):
            v = 1 - abs(2 * value_noise(i / res * 2.5, j / res * 7, seed) - 1)
            row.append(v)
            mx = max(mx, v)
        raw.append(row)
    sc = h / mx
    rot = (math.cos(math.radians(deg)), math.sin(math.radians(deg)))
    X = lambda i: -w / 2 + i / res * w  # noqa: E731
    Z = lambda j: -d / 2 + j / res * d  # noqa: E731
    rows = [[_pt(bm, X(i), raw[j][i] * sc, Z(j), rot) for i in range(res + 1)] for j in range(res + 1)]
    lim = MARRAM * h  # marram grass on the crests
    _grid_faces(
        bm,
        rows,
        1,
        lambda j, i: 2 if (raw[j][i] + raw[j][i + 1] + raw[j + 1][i] + raw[j + 1][i + 1]) * sc / 4 > lim else 1,
    )
    for i in range(res):
        _quad(
            bm,
            (X(i), 0, Z(0)),
            (X(i + 1), 0, Z(0)),
            (X(i + 1), raw[0][i + 1] * sc, Z(0)),
            (X(i), raw[0][i] * sc, Z(0)),
            1,
            rot,
        )
        _quad(
            bm,
            (X(i + 1), 0, Z(res)),
            (X(i), 0, Z(res)),
            (X(i), raw[res][i] * sc, Z(res)),
            (X(i + 1), raw[res][i + 1] * sc, Z(res)),
            1,
            rot,
        )
    for j in range(res):
        _quad(
            bm,
            (X(0), 0, Z(j + 1)),
            (X(0), 0, Z(j)),
            (X(0), raw[j][0] * sc, Z(j)),
            (X(0), raw[j + 1][0] * sc, Z(j + 1)),
            1,
            rot,
        )
        _quad(
            bm,
            (X(res), 0, Z(j)),
            (X(res), 0, Z(j + 1)),
            (X(res), raw[j + 1][res] * sc, Z(j + 1)),
            (X(res), raw[j][res] * sc, Z(j)),
            1,
            rot,
        )
    _quad(bm, (-w / 2, 0, -d / 2), (-w / 2, 0, d / 2), (w / 2, 0, d / 2), (w / 2, 0, -d / 2), 1, rot)
    bm.normal_update()
    return ('', ['mat_sand', 'mat_grass'])


# ── the island ──────────────────────────────────────────────────────────────
def build_island(bm, p, kit):
    N = lambda k, d: kit['num'](p, k, d)  # noqa: E731
    r, h = max(1.0, N('r', 40.0)), max(0.5, N('h', 6.0))
    wob = max(0.0, min(0.9, N('wobble', 0.3)))
    bch, seed = max(0.2, N('beach', 6.0)), N('seed', 1.0)
    seg = max(8, min(128, int(round(N('seg', 48.0)))))
    rings = max(2, min(40, int(round(N('rings', 10.0)))))
    R = [
        r
        * (
            1
            + wob
            * (
                2 * value_noise(math.cos(2 * math.pi * i / seg) * 2 + 2, math.sin(2 * math.pi * i / seg) * 2 + 2, seed)
                - 1
            )
        )
        for i in range(seg)
    ]
    apex = _pt(bm, 0.0, h, 0.0)
    ring = []
    for k in range(1, rings + 1):
        f = k / rings
        y = 0.3 + (h - 0.3) * 0.5 * (1 + math.cos(math.pi * f))
        ring.append(
            [
                _pt(bm, math.cos(2 * math.pi * i / seg) * R[i] * f, y, math.sin(2 * math.pi * i / seg) * R[i] * f)
                for i in range(seg)
            ]
        )
    outer = [
        _pt(bm, math.cos(2 * math.pi * i / seg) * (R[i] + bch), 0.0, math.sin(2 * math.pi * i / seg) * (R[i] + bch))
        for i in range(seg)
    ]
    for i in range(seg):
        j = (i + 1) % seg
        bm.faces.new((apex, ring[0][j], ring[0][i]))
    for k in range(rings - 1):
        A, B = ring[k], ring[k + 1]
        for i in range(seg):
            j = (i + 1) % seg
            bm.faces.new((A[j], A[i], B[i], B[j]))
    for i in range(seg):  # the sand ring
        j = (i + 1) % seg
        f = bm.faces.new((ring[-1][j], ring[-1][i], outer[i], outer[j]))
        f.material_index = 1
    ctr = _pt(bm, 0.0, 0.0, 0.0)
    for i in range(seg):  # the flat base
        j = (i + 1) % seg
        f = bm.faces.new((ctr, outer[j], outer[i]))
        f.material_index = 1
    bm.normal_update()
    return ('', ['mat_sand'])


# ── the breakwater ──────────────────────────────────────────────────────────
def build_breakwater(bm, p, kit):
    N = lambda k, d: kit['num'](p, k, d)  # noqa: E731
    ln = max(1.0, N('len', 60.0))
    w, h = max(0.5, N('w', 8.0)), max(0.2, N('h', 3.0))
    # the studio section (across, up) mirrored into Blender (Y = -z)
    kit['add_prism'](bm, [(w / 2, 0.0), (-w / 2, 0.0), (-w / 6, h), (w / 6, h)], 'x', -ln / 2, ln / 2)
    bm.normal_update()
    return ('', [])


BUILDERS = {
    'sea': build_sea,
    'beach': build_beach,
    'dune_field': build_dune_field,
    'island': build_island,
    'breakwater': build_breakwater,
}
