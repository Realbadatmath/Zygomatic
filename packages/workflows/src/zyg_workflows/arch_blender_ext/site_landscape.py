# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""site_landscape — Blender geometry for the site kinds.

Local frame (see arch_blender_build.build_kind): X along, Y = studio -Z (depth),
Z up, bottom at z=0. A studio plan angle θ (0 = +X, 90 = studio -Z) is therefore
the ordinary counter-clockwise angle in Blender's XY plane: (r cosθ, r sinθ).

Material slots: 0 is the record's own material; the ids returned as `extra` fill
slots 1, 2, ... in that order, matching the `sub` overrides in site_landscape.js.

GROUND (2026-09-07): flowerbed, sidewalk and parking_bay carry the ground plane
in gx, gz — the rise per metre along the record's LOCAL x and z — and are SHEARED
onto it rather than rotated, so whatever stands on them stays upright. In the tab
that is `y += gx*x + gz*z`; here studio z is -y, so it is `z += gx*x - gz*y`.
"""

import math

TIMBER, GREEN = 1, 2  # slot indices used by the planting builders


def _drape(bm, gx, gz):
    """Shear every vertex onto the ground plane (see the module docstring)."""
    if not gx and not gz:
        return
    for v in bm.verts:
        v.co.z += gx * v.co.x - gz * v.co.y
    bm.normal_update()


def build_fence(bm, p, kit):
    N = lambda k, d: kit['num'](p, k, d)
    L, h = N('len', 5.0), N('h', 1.2)
    np_ = max(2, int(round(N('posts', 3))))
    nr = max(0, int(round(N('rails', 3))))
    t = N('t', 0.04)
    for i in range(np_):
        kit['add_box_c'](bm, t, t, h, cx=-L / 2 + L * i / (np_ - 1))
    for i in range(nr):
        z = h * (i + 1) / (nr + 0.4)
        kit['add_box_c'](bm, L, t * 0.6, t * 1.2, z0=z - t * 0.6)
    return ('', [])


def build_hedge(bm, p, kit):
    N = lambda k, d: kit['num'](p, k, d)
    kit['add_box_c'](bm, N('len', 5.0), N('w', 0.6), N('h', 1.2), mi=1)
    return ('', ['mat_grass'])


def build_tree_conifer(bm, p, kit):
    N = lambda k, d: kit['num'](p, k, d)
    h, r = max(0.5, N('h', 8.0)), max(0.1, N('r', 2.0))
    rt = max(0.05, min(r * 0.4, r * 0.09 + 0.02))
    kit['add_cylinder'](bm, rt, h * 0.2, z0=0.0, seg=10, r_top=rt * 0.85, mi=TIMBER)
    kit['add_cylinder'](bm, r, h * 0.85, z0=h * 0.15, seg=20, r_top=0.0, mi=GREEN)
    return ('', ['mat_timber', 'mat_grass'])


def build_tree_deciduous(bm, p, kit):
    N = lambda k, d: kit['num'](p, k, d)
    h = max(0.5, N('h', 7.0))
    rc = max(0.1, N('r_can', 3.0))
    rt = min(max(0.03, N('r_trunk', 0.25)), rc * 0.8)
    trunk = max(0.2, h - rc)
    kit['add_cylinder'](bm, rt, trunk, z0=0.0, seg=12, r_top=rt * 0.8, mi=TIMBER)
    kit['add_sphere'](bm, rc, h - rc, useg=32, vseg=16, mi=GREEN)
    return ('', ['mat_timber', 'mat_grass'])


def build_tree_palm(bm, p, kit):
    N = lambda k, d: kit['num'](p, k, d)
    math_ = kit['math']
    bmesh = kit['bmesh']
    h = max(0.5, N('h', 7.0))
    nf = max(3, int(round(N('fronds', 7))))
    kit['add_cylinder'](bm, h * 0.026, h, z0=0.0, seg=10, r_top=h * 0.019, mi=TIMBER)
    L = h * 0.34
    for i in range(nf):
        before = set(bm.verts)
        kit['add_box'](bm, 0.0, L, -0.21, 0.21, -0.05, 0.0, mi=GREEN)
        vs = [v for v in bm.verts if v not in before]
        bmesh.ops.rotate(bm, verts=vs, cent=(0.0, 0.0, 0.0), matrix=_rot(math_, -0.34, 'Y'))
        bmesh.ops.rotate(bm, verts=vs, cent=(0.0, 0.0, 0.0), matrix=_rot(math_, i * 2 * math_.pi / nf, 'Z'))
        bmesh.ops.translate(bm, verts=vs, vec=(0.0, 0.0, h))
    return ('', ['mat_timber', 'mat_grass'])


def _rot(math_, ang, axis):
    """A 3x3 rotation matrix without importing mathutils at module level."""
    from mathutils import Matrix

    return Matrix.Rotation(ang, 3, axis)


def build_shrub(bm, p, kit):
    N = lambda k, d: kit['num'](p, k, d)
    r, h = max(0.05, N('r', 0.6)), max(0.05, N('h', 0.8))
    kit['add_sphere'](bm, r, h / 2, useg=14, vseg=10, sz=h / (2 * r), mi=1)
    return ('', ['mat_grass'])


def build_flowerbed(bm, p, kit):
    N = lambda k, d: kit['num'](p, k, d)
    kit['add_box_c'](bm, N('w', 3.0), N('d', 1.5), N('t', 0.15), mi=1)
    _drape(bm, N('gx', 0.0), N('gz', 0.0))
    return ('', ['mat_grass'])


def build_lamp_post(bm, p, kit):
    N = lambda k, d: kit['num'](p, k, d)
    h, r = max(0.5, N('h', 4.0)), max(0.02, N('r', 0.06))
    kit['add_cylinder'](bm, r * 1.35, h, z0=0.0, seg=12, r_top=r)
    kit['add_box_c'](bm, 0.36, 0.36, 0.12, z0=h - 0.12, mi=1)
    return ('', ['mat_glass'])


def build_bench(bm, p, kit):
    N = lambda k, d: kit['num'](p, k, d)
    L, h, d = max(0.4, N('len', 1.8)), max(0.15, N('h', 0.45)), 0.45
    kit['add_box_c'](bm, L, d, 0.06, z0=h - 0.06, mi=1)
    kit['add_box_c'](bm, 0.07, d * 0.8, h - 0.06, cx=-L / 2 + 0.12)
    kit['add_box_c'](bm, 0.07, d * 0.8, h - 0.06, cx=L / 2 - 0.12)
    return ('', ['mat_timber'])


def build_bin(bm, p, kit):
    N = lambda k, d: kit['num'](p, k, d)
    r, h = max(0.05, N('r', 0.25)), max(0.1, N('h', 0.9))
    kit['add_cylinder'](bm, r * 0.85, h * 0.9, z0=0.0, seg=16, r_top=r)
    kit['add_cylinder'](bm, r, h * 0.1, z0=h * 0.9, seg=16, mi=1)
    return ('', ['mat_paint_dark'])


def build_kerb(bm, p, kit):
    N = lambda k, d: kit['num'](p, k, d)
    kit['add_box_c'](bm, N('len', 5.0), N('w', 0.15), N('h', 0.12))
    return ('', [])


def build_sidewalk(bm, p, kit):
    N = lambda k, d: kit['num'](p, k, d)
    kit['add_box_c'](bm, N('len', 10.0), N('w', 2.0), N('t', 0.06))
    _drape(bm, N('gx', 0.0), N('gz', 0.0))
    return ('', [])


def build_parking_bay(bm, p, kit):
    N = lambda k, d: kit['num'](p, k, d)
    w, d = max(0.4, N('w', 2.5)), max(0.4, N('d', 5.0))
    t = max(0.005, N('t', 0.02))
    lw, lt = min(0.12, w / 6), t * 0.4
    kit['add_box_c'](bm, w, d, t)
    kit['add_box_c'](bm, lw, d, lt, cx=-(w / 2 - lw / 2), z0=t - lt, mi=1)
    kit['add_box_c'](bm, lw, d, lt, cx=(w / 2 - lw / 2), z0=t - lt, mi=1)
    kit['add_box_c'](bm, w, lw, lt, cy=(d / 2 - lw / 2), z0=t - lt, mi=1)
    _drape(bm, N('gx', 0.0), N('gz', 0.0))
    return ('', ['mat_paint_white'])


def build_road_curved(bm, p, kit):
    """An arc of carriageway: inner radius r - w/2, outer r + w/2, t thick."""
    N = lambda k, d: kit['num'](p, k, d)
    r = max(0.5, N('r', 10.0))
    a0, a1 = N('a0', 0.0), N('a1', 90.0)
    w, t = max(0.2, N('w', 6.0)), max(0.01, N('t', 0.08))
    seg = max(4, int(N('seg', 24)))
    if abs(a1 - a0) < 0.5:
        a1 = a0 + 0.5
    if abs(a1 - a0) >= 360:
        a1 = a0 + 359.9
    ri, ro = max(0.05, r - w / 2), r + w / 2
    a0r, a1r = math.radians(a0), math.radians(a1)
    inner, outer = [], []
    for i in range(seg + 1):
        a = a0r + (a1r - a0r) * i / seg
        c, s = math.cos(a), math.sin(a)
        inner.append((bm.verts.new((ri * c, ri * s, 0.0)), bm.verts.new((ri * c, ri * s, t))))
        outer.append((bm.verts.new((ro * c, ro * s, 0.0)), bm.verts.new((ro * c, ro * s, t))))
    for i in range(seg):
        i0, i1 = inner[i], inner[i + 1]
        o0, o1 = outer[i], outer[i + 1]
        bm.faces.new((o0[0], o1[0], o1[1], o0[1]))
        bm.faces.new((i1[0], i0[0], i0[1], i1[1]))
        bm.faces.new((o0[1], o1[1], i1[1], i0[1]))
        bm.faces.new((i0[0], i1[0], o1[0], o0[0]))
    if abs(abs(a1 - a0) - 360) > 0.2:
        bm.faces.new((inner[0][0], outer[0][0], outer[0][1], inner[0][1]))
        bm.faces.new((outer[-1][0], inner[-1][0], inner[-1][1], outer[-1][1]))
    bm.normal_update()
    return ('', [])


BUILDERS = {
    'fence': build_fence,
    'hedge': build_hedge,
    'tree_conifer': build_tree_conifer,
    'tree_deciduous': build_tree_deciduous,
    'tree_palm': build_tree_palm,
    'shrub': build_shrub,
    'flowerbed': build_flowerbed,
    'lamp_post': build_lamp_post,
    'bench': build_bench,
    'bin': build_bin,
    'kerb': build_kerb,
    'sidewalk': build_sidewalk,
    'parking_bay': build_parking_bay,
    'road_curved': build_road_curved,
}
