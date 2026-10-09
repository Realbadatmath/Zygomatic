# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""cliffs_rocks — Blender geometry for cliff, escarpment, boulder, rock_field,
scree and sea_stack.

Local frame (see arch_blender_build.build_kind): X along, Y = studio -Z, Z up,
bottom at z=0. Everything below is written in the STUDIO frame (x, y up, z
depth) and mapped once, in V(), so the arithmetic reads the same as
arch_ext/cliffs_rocks.js.

The noise is the third copy of the contract in arch_ext/cliffs_rocks.js and
arch_assistant_ext/cliffs_rocks.py — the same arithmetic, so a cliff record is
the same rock in the tab, in the assistant and here.
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


def _V(bm, x, y, z):
    """One studio point (x, y up, z depth) as a Blender vertex."""
    return bm.verts.new((x, -z, y))


def _face(bm, verts, mi=0):
    try:
        f = bm.faces.new(verts)
    except ValueError:  # a duplicate face, harmless here
        return None
    f.material_index = mi
    return f


# ── the rock face shared by cliff and escarpment ────────────────────────────
def _face_body(bm, ln, h, d, rug, seed, res, ledge_top, mi=0):
    F = [
        [
            _V(
                bm,
                -ln / 2 + i / res * ln,
                h * j / res,
                -d / 2 - rug + 2 * rug * value_noise(i / res * 3, j / res * 3, seed),
            )
            for i in range(res + 1)
        ]
        for j in range(res + 1)
    ]
    B = [_V(bm, -ln / 2 + i / res * ln, 0.0, d / 2) for i in range(res + 1)]
    T = [_V(bm, -ln / 2 + i / res * ln, h, d / 2) for i in range(res + 1)] if ledge_top else B
    for j in range(res):
        for i in range(res):
            _face(bm, (F[j][i], F[j + 1][i], F[j + 1][i + 1], F[j][i + 1]), mi)
    for i in range(res):
        _face(bm, (F[res][i], T[i], T[i + 1], F[res][i + 1]), mi)  # ledge / tilted top
        _face(bm, (F[0][i], F[0][i + 1], B[i + 1], B[i]), mi)  # bottom
        if ledge_top:
            _face(bm, (B[i], B[i + 1], T[i + 1], T[i]), mi)  # back wall
    for j in range(res):
        _face(bm, (B[0], F[j + 1][0], F[j][0]), mi)
        _face(bm, (B[res], F[j][res], F[j + 1][res]), mi)
    if ledge_top:
        _face(bm, (B[0], T[0], F[res][0]), mi)
        _face(bm, (B[res], F[res][res], T[res]), mi)
    bm.normal_update()


def build_cliff(bm, p, kit):
    N = lambda k, d: kit['num'](p, k, d)  # noqa: E731
    ln, h, d = max(0.5, N('len', 40.0)), max(0.1, N('h', 15.0)), max(0.5, N('d', 12.0))
    rug, seed, ledge = max(0.0, N('rug', 0.35)), N('seed', 1.0), N('ledge', 1.0)
    res = max(2, min(64, int(round(N('res', 24.0)))))
    _face_body(bm, ln, h, d, rug, seed, res, True, 0)
    if ledge > 0:
        lt, rr = min(ledge, h * 0.9), min(rug, d * 0.25)
        kit['add_box'](bm, -ln / 2, ln / 2, -d / 2, d / 2 - rr, h - lt, h, 1)
    bm.normal_update()
    return ('', ['mat_grass'])


def _top_strip(bm, ln, h, d, lg, mi=1):
    """The grass strip lying ON an escarpment's tilted top, from the front edge
    back `lg` metres. Highest point exactly h, so the bbox does not grow."""
    t = min(0.15, h * 0.1)
    yf, yb, zf, zb, X = h, h * (1 - lg / d), -d / 2, -d / 2 + lg, ln / 2
    v = [
        _V(bm, -X, yf, zf),
        _V(bm, X, yf, zf),
        _V(bm, X, yb, zb),
        _V(bm, -X, yb, zb),
        _V(bm, -X, yf - t, zf),
        _V(bm, X, yf - t, zf),
        _V(bm, X, yb - t, zb),
        _V(bm, -X, yb - t, zb),
    ]
    for q in ((0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (3, 7, 6, 2), (0, 4, 7, 3), (1, 2, 6, 5)):
        _face(bm, tuple(v[i] for i in q), mi)


def build_escarpment(bm, p, kit):
    N = lambda k, d: kit['num'](p, k, d)  # noqa: E731
    ln, h, d = max(0.5, N('len', 60.0)), max(0.1, N('h', 20.0)), max(0.5, N('d', 40.0))
    rug, seed = max(0.0, N('rug', 0.3)), N('seed', 1.0)
    res = max(2, min(64, int(round(N('res', 24.0)))))
    _face_body(bm, ln, h, d, rug, seed, res, False, 0)
    lg = max(0.0, min(N('ledge', 1.0), d * 0.5))
    if lg > 0.01:
        _top_strip(bm, ln, h, d, lg, 1)
    bm.normal_update()
    return ('', ['mat_grass'])


# ── one noisy sphere, lowest vertex at y = 0 ────────────────────────────────
def _boulder_pts(r, rug, seed, seg, rings):
    def R(u, v):
        return r * (1 + rug * (2 * value_noise(u * 3, v * 3, seed) - 1))

    pts = [(0.0, R(0.0, 0.0), 0.0)]
    for j in range(1, rings):
        v = j / rings
        phi = math.pi * v
        for i in range(seg):
            u = i / seg
            th = 2 * math.pi * u
            rad = R(u, v)
            pts.append((rad * math.sin(phi) * math.cos(th), rad * math.cos(phi), -rad * math.sin(phi) * math.sin(th)))
    pts.append((0.0, -R(0.0, 1.0), 0.0))
    lo = min(q[1] for q in pts)
    return [(q[0], q[1] - lo, q[2]) for q in pts]


def _boulder(bm, r, rug, seed, seg, rings, dx=0.0, dy=0.0, dz=0.0, mi=0):
    pts = _boulder_pts(r, rug, seed, seg, rings)
    vs = [_V(bm, q[0] + dx, q[1] + dy, q[2] + dz) for q in pts]
    south = len(vs) - 1

    def ring(j, i):
        return vs[1 + (j - 1) * seg + (i % seg)]

    for i in range(seg):
        _face(bm, (vs[0], ring(1, i), ring(1, i + 1)), mi)
        _face(bm, (ring(rings - 1, i), vs[south], ring(rings - 1, i + 1)), mi)
    for j in range(1, rings - 1):
        for i in range(seg):
            _face(bm, (ring(j, i), ring(j + 1, i), ring(j + 1, i + 1), ring(j, i + 1)), mi)
    return pts


def build_boulder(bm, p, kit):
    N = lambda k, d: kit['num'](p, k, d)  # noqa: E731
    r = max(0.05, N('r', 1.5))
    rug = max(0.0, min(0.9, N('rug', 0.35)))
    seg = max(6, min(48, int(round(N('seg', 12.0)))))
    _boulder(bm, r, rug, N('seed', 1.0), seg, max(2, int(round(seg / 2))))
    bm.normal_update()
    return ('', [])


def build_rock_field(bm, p, kit):
    N = lambda k, d: kit['num'](p, k, d)  # noqa: E731
    w, d = max(1.0, N('w', 30.0)), max(1.0, N('d', 30.0))
    cnt = max(1, min(400, int(round(N('count', 20.0)))))
    size, seed = max(0.05, N('size', 1.2)), N('seed', 1.0)
    rug = max(0.0, min(0.9, N('rug', 0.35)))
    gx, gz = N('gx', 0.0), N('gz', 0.0)
    for n in range(cnt):
        rr = size / 2 * (0.4 + 0.6 * _hash(n, 3, seed))  # size = the LARGEST diameter
        px = -w / 2 + _hash(n, 1, seed) * w
        pz = -d / 2 + _hash(n, 2, seed) * d
        # the base follows the ground plane; the rock itself stays upright
        _boulder(bm, rr, rug, seed + n + 1, 8, 4, px, gx * px + gz * pz, pz, 1 if _hash(n, 4, seed) < 0.3 else 0)
    bm.normal_update()
    return ('', ['mat_stone'])


def build_scree(bm, p, kit):
    N = lambda k, d: kit['num'](p, k, d)  # noqa: E731
    ln, w, h = max(0.5, N('len', 30.0)), max(0.5, N('w', 12.0)), max(0.1, N('h', 6.0))
    # studio section (z, y): (w/2, 0) -> (-w/2, 0) -> (-w/2, h); Blender Y = -z
    kit['add_prism'](bm, [(-w / 2, 0.0), (w / 2, 0.0), (w / 2, h)], 'x', -ln / 2, ln / 2, 0)
    for n in range(12):
        rb = 0.15 + 0.25 * _hash(n, 3, 1)
        pts = _boulder_pts(rb, 0.3, 5 + n, 8, 4)
        hx = max(abs(q[0]) for q in pts)
        hy = max(q[1] for q in pts)
        hz = max(abs(q[2]) for q in pts)
        xlo, xhi = -ln / 2 + hx, ln / 2 - hx
        zlo, zhi = -w / 2 + hz, w / 2 - hz
        zmin = max(zlo, w / 2 - w * (1 - hy / h))
        if xhi <= xlo or zhi <= zmin:
            continue
        pz = zmin + _hash(n, 2, 1) * (zhi - zmin)
        _boulder(bm, rb, 0.3, 5 + n, 8, 4, xlo + _hash(n, 1, 1) * (xhi - xlo), h * (w / 2 - pz) / w, pz, 1)
    bm.normal_update()
    return ('', ['mat_rock'])


def build_sea_stack(bm, p, kit):
    N = lambda k, d: kit['num'](p, k, d)  # noqa: E731
    r, h = max(0.2, N('r', 6.0)), max(0.2, N('h', 25.0))
    rug, seed = max(0.0, min(0.9, N('rug', 0.3))), N('seed', 1.0)
    seg = max(6, min(64, int(round(N('seg', 24.0)))))
    rings = max(2, min(48, int(round(N('rings', 10.0)))))
    R = []
    for j in range(rings + 1):
        v = j / rings
        row = []
        for i in range(seg):
            u = i / seg
            th = 2 * math.pi * u
            rad = r * (1 + rug * (2 * value_noise(u * 3, v * 3, seed) - 1))
            row.append(_V(bm, rad * math.cos(th), h * v, -rad * math.sin(th)))
        R.append(row)
    ctop, cbot = _V(bm, 0.0, h, 0.0), _V(bm, 0.0, 0.0, 0.0)
    for j in range(rings):
        for i in range(seg):
            k = (i + 1) % seg
            _face(bm, (R[j + 1][i], R[j][i], R[j][k], R[j + 1][k]), 0)
    for i in range(seg):
        k = (i + 1) % seg
        _face(bm, (ctop, R[rings][i], R[rings][k]), 0)
        _face(bm, (cbot, R[0][k], R[0][i]), 0)
    bm.normal_update()
    return ('', [])


BUILDERS = {
    'cliff': build_cliff,
    'escarpment': build_escarpment,
    'boulder': build_boulder,
    'rock_field': build_rock_field,
    'scree': build_scree,
    'sea_stack': build_sea_stack,
}
