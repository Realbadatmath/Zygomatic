# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""landmarks_special — Blender geometry for the fifteen landmark kinds.

Local frame (arch_blender_build.build_kind): X along, Y = studio -Z (depth),
Z up, bottom at z = 0. The studio's plan angle t (0 = +X, 90 = studio -Z) is
therefore the ordinary counter-clockwise angle in Blender's XY plane.

Sizes match arch_ext/landmarks_special.js exactly — the same defaults, the
same arithmetic — so a drawing looks the same in the tab and in Blender.
"""

import math

TAU = math.pi * 2


def _beam(bm, ox, oy, oz, dx, dz, length, wide, thick, mi=0):
    """A box `length` long from (ox,oy,oz) along the unit direction (dx,0,dz)
    in the XZ plane, `wide` across it in that plane, `thick` along Y."""
    px, pz = -dz, dx
    hw, ht = wide / 2.0, thick / 2.0

    def pt(u, v, w):
        return (ox + dx * u + px * w, oy + v, oz + dz * u + pz * w)

    vs = [
        bm.verts.new(p)
        for p in (
            pt(0, -ht, -hw),
            pt(length, -ht, -hw),
            pt(length, ht, -hw),
            pt(0, ht, -hw),
            pt(0, -ht, hw),
            pt(length, -ht, hw),
            pt(length, ht, hw),
            pt(0, ht, hw),
        )
    ]
    for idx in ((0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)):
        f = bm.faces.new([vs[i] for i in idx])
        f.material_index = mi


def _ring_band(bm, axo, ayo, axi, ayi, z0, z1, seg=48, mi=0):
    """A closed band between two concentric ellipses in the XY plane."""
    axi, ayi = max(0.02, axi), max(0.02, ayi)
    rows = []
    for i in range(seg):
        a = i / seg * TAU
        c, s = math.cos(a), math.sin(a)
        rows.append(
            (
                bm.verts.new((axo * c, ayo * s, z0)),
                bm.verts.new((axo * c, ayo * s, z1)),
                bm.verts.new((axi * c, ayi * s, z0)),
                bm.verts.new((axi * c, ayi * s, z1)),
            )
        )
    for i in range(seg):
        A, B = rows[i], rows[(i + 1) % seg]
        for quad in (
            (A[0], B[0], B[1], A[1]),
            (B[2], A[2], A[3], B[3]),
            (A[1], B[1], B[3], A[3]),
            (A[2], B[2], B[0], A[0]),
        ):
            bm.faces.new(quad).material_index = mi


def _frustum(bm, w0, w1, z0, z1, mi=0):
    """A square frustum: w0 across at z0, w1 across at z1, axis-aligned."""
    a, b = w0 / 2.0, max(1e-4, w1) / 2.0
    lo = [bm.verts.new(p) for p in ((-a, -a, z0), (a, -a, z0), (a, a, z0), (-a, a, z0))]
    hi = [bm.verts.new(p) for p in ((-b, -b, z1), (b, -b, z1), (b, b, z1), (-b, b, z1))]
    bm.faces.new(list(reversed(lo))).material_index = mi
    bm.faces.new(hi).material_index = mi
    for i in range(4):
        j = (i + 1) % 4
        bm.faces.new((lo[i], lo[j], hi[j], hi[i])).material_index = mi


def _icosphere(bmesh_mod, bm, r, subdivisions):
    try:
        return bmesh_mod.ops.create_icosphere(bm, subdivisions=subdivisions, radius=r)
    except TypeError:  # Blender < 3.0 called it diameter
        return bmesh_mod.ops.create_icosphere(bm, subdivisions=subdivisions, diameter=r)


# ── mills, towers, tanks ────────────────────────────────────────────────────
def build_windmill(bm, p, kit):
    N = lambda k, d: kit['num'](p, k, d)
    h, r, cap = N('h', 12), N('r', 3), N('cap', 2)
    sails, sl = max(2, int(N('sails', 4))), N('sail_len', 8)
    kit['add_cylinder'](bm, r, h, seg=24, r_top=r * 0.6)
    kit['add_cylinder'](bm, r * 0.74, max(0.05, cap), z0=h, seg=24, r_top=0.02)
    hz = -(r * 0.6 + r * 0.16)  # hub on the studio -z (Blender +Y) face
    kit['add_box_c'](bm, r * 0.4, r * 0.42, r * 0.4, cy=-hz - r * 0.1, z0=h - r * 0.2)
    for i in range(sails):
        a = i * TAU / sails
        _beam(bm, 0.0, -hz, h, math.cos(a), math.sin(a), sl, max(0.3, sl * 0.09), max(0.06, sl * 0.02))
    bm.normal_update()
    return ('', [])


def build_lighthouse(bm, p, kit):
    N = lambda k, d: kit['num'](p, k, d)
    h, rb, rt, lan = N('h', 20), N('r_base', 3), N('r_top', 2), max(0.4, N('lantern', 2.5))
    deck = min(0.25, lan * 0.08)
    drum_h = lan * 0.6
    cap_h = lan - deck - drum_h
    kit['add_cylinder'](bm, rb, h, seg=32, r_top=rt)
    kit['add_cylinder'](bm, rt * 1.3, deck, z0=h, seg=32)
    kit['add_cylinder'](bm, rt * 1.05, drum_h, z0=h + deck, seg=24, mi=1)
    kit['add_cylinder'](bm, rt * 1.12, cap_h, z0=h + deck + drum_h, seg=24, r_top=0.02)
    bm.normal_update()
    return ('', ['mat_glass'])


def build_water_tower(bm, p, kit):
    N = lambda k, d: kit['num'](p, k, d)
    h, rt, th, legs = N('h', 15), N('r_tank', 4), N('tank_h', 4), max(3, int(N('legs', 4)))
    th = min(th, h * 0.9)
    lh, lr = max(0.2, h - th), rt * 0.72
    for i in range(legs):
        a = i * TAU / legs
        kit['add_box_c'](bm, rt * 0.09, rt * 0.09, lh, cx=lr * math.cos(a), cy=lr * math.sin(a))
    _ring_band(
        bm,
        lr + rt * 0.03,
        lr + rt * 0.03,
        lr - rt * 0.03,
        lr - rt * 0.03,
        lh * 0.55 - rt * 0.03,
        lh * 0.55 + rt * 0.03,
        seg=max(12, legs * 6),
    )
    kit['add_cylinder'](bm, rt, th, z0=h - th, seg=32)
    bm.normal_update()
    return ('', [])


def build_silo(bm, p, kit):
    N = lambda k, d: kit['num'](p, k, d)
    r, h, cn = N('r', 3), N('h', 12), max(0.05, N('cone', 2))
    kit['add_cylinder'](bm, r, h, seg=32)
    kit['add_cylinder'](bm, r, cn, z0=h, seg=32, r_top=0.02)
    bm.normal_update()
    return ('', [])


def build_minaret(bm, p, kit):
    N = lambda k, d: kit['num'](p, k, d)
    r, h = N('r', 1.5), N('h', 25)
    by = max(0.15, min(0.92, N('balcony', 0.7))) * h
    kit['add_cylinder'](bm, r, h * 0.9, seg=24, r_top=r * 0.62)
    kit['add_cylinder'](bm, r * 1.6, 0.3, z0=by - 0.15, seg=24)
    _ring_band(bm, r * 1.65, r * 1.65, r * 1.55, r * 1.55, by + 0.7, by + 0.8, seg=24)
    kit['add_cylinder'](bm, r * 0.75, h * 0.1, z0=h * 0.9, seg=24, r_top=0.02)
    bm.normal_update()
    return ('', [])


def build_wind_turbine(bm, p, kit):
    N = lambda k, d: kit['num'](p, k, d)
    h, bl, rm = N('h', 60), N('blade', 30), N('r_mast', 2)
    kit['add_cylinder'](bm, rm, h, seg=24, r_top=rm * 0.45)
    hz, hy = h + rm * 0.55, rm * 0.6  # studio -z = Blender +Y
    kit['add_box_c'](bm, rm * 1.2, rm * 3, rm * 1.1, cy=hy, z0=hz - rm * 0.55)
    kit['add_box_c'](bm, rm * 1.1, rm * 1.2, rm * 1.1, cy=hy + rm * 2.1, z0=hz - rm * 0.55)  # hub
    for i in range(3):
        a = i * TAU / 3
        _beam(bm, 0.0, hy + rm * 2.6, hz, math.cos(a), math.sin(a), bl, max(0.3, bl * 0.055), max(0.1, bl * 0.012))
    bm.normal_update()
    return ('', [])


# ── shells & shelters ───────────────────────────────────────────────────────
def build_geodesic_dome(bm, p, kit):
    N = lambda k, d: kit['num'](p, k, d)
    r = N('r', 8)
    det = max(1, min(4, int(N('detail', 1))))
    res = _icosphere(kit['bmesh'], bm, r, det + 1)  # Blender subdivisions 1 = raw icosahedron
    for v in res['verts']:
        if v.co.z < 0.0:
            v.co.z = 0.0
    bm.normal_update()
    return ('', [])


def build_tent(bm, p, kit):
    N = lambda k, d: kit['num'](p, k, d)
    r, h, sides = N('r', 6), N('h', 5), max(3, int(N('sides', 8)))
    kit['add_cylinder'](bm, r, h, seg=sides, r_top=0.02)
    kit['add_cylinder'](bm, r * 0.035, h, seg=8)
    bm.normal_update()
    return ('', [])


def build_gazebo(bm, p, kit):
    N = lambda k, d: kit['num'](p, k, d)
    r, h, posts, rh = N('r', 2.5), N('h', 2.6), max(3, int(N('posts', 6))), N('roof_h', 1.2)
    kit['add_cylinder'](bm, r * 1.06, 0.15, seg=max(8, posts * 4))
    for i in range(posts):
        a = i * TAU / posts
        kit['add_box_c'](bm, 0.12, 0.12, h - 0.15, cx=r * 0.92 * math.cos(a), cy=r * 0.92 * math.sin(a), z0=0.15)
    kit['add_cylinder'](bm, r * 1.06, max(0.05, rh), z0=h, seg=posts, r_top=0.02)
    bm.normal_update()
    return ('', [])


# ── monuments ───────────────────────────────────────────────────────────────
def build_obelisk(bm, p, kit):
    N = lambda k, d: kit['num'](p, k, d)
    h, w = N('h', 10), N('w', 1.2)
    _frustum(bm, w, w * 0.62, 0.0, h * 0.9)
    _frustum(bm, w * 0.62, 0.02, h * 0.9, h)
    bm.normal_update()
    return ('', [])


def build_arch_monument(bm, p, kit):
    N = lambda k, d: kit['num'](p, k, d)
    w, h, dd = N('w', 8), N('h', 10), N('d', 3)
    ow, oh = min(N('opening_w', 4), w * 0.9), min(N('opening_h', 7), h * 0.92)
    leg = (w - ow) / 2.0
    kit['add_box_c'](bm, leg, dd, oh, cx=-(w - leg) / 2.0)
    kit['add_box_c'](bm, leg, dd, oh, cx=(w - leg) / 2.0)
    kit['add_box_c'](bm, w, dd, h - oh, z0=oh)
    bm.normal_update()
    return ('', [])


def build_spire(bm, p, kit):
    N = lambda k, d: kit['num'](p, k, d)
    r, h, sides = N('r', 3), N('h', 12), max(3, int(N('sides', 8)))
    kit['add_cylinder'](bm, r, h * 0.12, seg=sides)
    kit['add_cylinder'](bm, r, h * 0.88, z0=h * 0.12, seg=sides, r_top=0.02)
    bm.normal_update()
    return ('', [])


def build_pyramid_stepped(bm, p, kit):
    N = lambda k, d: kit['num'](p, k, d)
    w, h = N('w', 30), N('h', 20)
    steps = max(1, min(40, int(N('steps', 5))))
    sh = h / steps
    for i in range(steps):
        side = w * (1 - i / steps)
        kit['add_box_c'](bm, side, side, sh, z0=i * sh)
    bm.normal_update()
    return ('', [])


# ── big structures ──────────────────────────────────────────────────────────
def build_stadium_ring(bm, p, kit):
    N = lambda k, d: kit['num'](p, k, d)
    rx, rz = N('rx', 60), N('rz', 45)
    tiers = max(1, min(12, int(N('tiers', 3))))
    th, td = N('tier_h', 4), N('tier_d', 8)
    for i in range(tiers):
        fo = max(0.06, (rx - (tiers - 1 - i) * td) / rx)
        fi = max(0.04, (rx - (tiers - i) * td) / rx)
        _ring_band(bm, rx * fo, rz * fo, rx * fi, rz * fi, i * th, (i + 1) * th, seg=48)
    bm.normal_update()
    return ('', [])


def build_ferris_wheel(bm, p, kit):
    N = lambda k, d: kit['num'](p, k, d)
    r = N('r', 15)
    cab = max(3, min(48, int(N('cabins', 12))))
    hz = r + max(0.5, r * 0.07)
    rt, off = r * 0.035, r * 0.09
    for sgn in (-1.0, 1.0):
        rows = []
        for i in range(48):
            a = i / 48.0 * TAU
            c, s = math.cos(a), math.sin(a)
            y0, y1 = sgn * off - rt, sgn * off + rt
            rows.append(
                (
                    bm.verts.new(((r + rt) * c, y0, hz + (r + rt) * s)),
                    bm.verts.new(((r + rt) * c, y1, hz + (r + rt) * s)),
                    bm.verts.new(((r - rt) * c, y0, hz + (r - rt) * s)),
                    bm.verts.new(((r - rt) * c, y1, hz + (r - rt) * s)),
                )
            )
        for i in range(48):
            A, B = rows[i], rows[(i + 1) % 48]
            for quad in (
                (A[0], B[0], B[1], A[1]),
                (B[2], A[2], A[3], B[3]),
                (A[1], B[1], B[3], A[3]),
                (A[2], B[2], B[0], A[0]),
            ):
                bm.faces.new(quad)
    kit['add_box_c'](bm, r * 0.1, off * 2.4, r * 0.1, z0=hz - r * 0.05)
    cw = r * 0.09
    for i in range(cab):
        a = i * TAU / cab
        _beam(bm, 0.0, 0.0, hz, -math.sin(a), math.cos(a), r, r * 0.012, r * 0.012)
        kit['add_box_c'](bm, cw, cw * 1.6, cw * 1.2, cx=-r * math.sin(a), z0=hz + r * math.cos(a) - cw * 1.2)
    lx = r * 0.6
    L = math.hypot(lx, hz)
    for sgn in (-1.0, 1.0):
        for x0 in (lx, -lx):
            _beam(bm, x0, sgn * off * 1.4, 0.0, -x0 / L, hz / L, L, r * 0.03, r * 0.03)
    bm.normal_update()
    return ('', [])


BUILDERS = {
    'windmill': build_windmill,
    'lighthouse': build_lighthouse,
    'water_tower': build_water_tower,
    'silo': build_silo,
    'geodesic_dome': build_geodesic_dome,
    'tent': build_tent,
    'gazebo': build_gazebo,
    'obelisk': build_obelisk,
    'arch_monument': build_arch_monument,
    'spire': build_spire,
    'minaret': build_minaret,
    'stadium_ring': build_stadium_ring,
    'wind_turbine': build_wind_turbine,
    'pyramid_stepped': build_pyramid_stepped,
    'ferris_wheel': build_ferris_wheel,
}
