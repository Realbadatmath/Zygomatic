# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""openings_special — Blender geometry for the special openings and the
curtain wall.

Local frame (see arch_blender_build.build_kind): X along the wall, Y = the
studio's -Z (so a bay window projects toward +Y here), Z up, bottom at z=0.
The frames are built solid — the hole in the host wall is cut by the studio,
not here.
"""


def _ring(kit, bm, cx, cz, rxi, rzi, rxo, rzo, a0, a1, seg, y0, y1):
    """An elliptical ring standing in the XZ plane, swept from Y=y0 to Y=y1."""
    math = kit['math']
    seg = max(3, int(seg))
    for i in range(seg):
        t0 = a0 + (a1 - a0) * i / seg
        t1 = a0 + (a1 - a0) * (i + 1) / seg
        prof = [
            (cx + rxo * math.cos(t0), cz + rzo * math.sin(t0)),
            (cx + rxo * math.cos(t1), cz + rzo * math.sin(t1)),
            (cx + rxi * math.cos(t1), cz + rzi * math.sin(t1)),
            (cx + rxi * math.cos(t0), cz + rzi * math.sin(t0)),
        ]
        kit['add_prism'](bm, prof, 'y', y0, y1)


def _fan(kit, bm, cx, cz, rx, rz, a0, a1, seg, y0, y1):
    """A filled ellipse sector in the XZ plane (the glass), swept along Y."""
    math = kit['math']
    seg = max(3, int(seg))
    pts = [
        (cx + rx * math.cos(a0 + (a1 - a0) * i / seg), cz + rz * math.sin(a0 + (a1 - a0) * i / seg))
        for i in range(seg + 1)
    ]
    for i in range(1, len(pts) - 1):
        kit['add_prism'](bm, [pts[0], pts[i], pts[i + 1]], 'y', y0, y1)


def _plan_prism(bm, pts, z0, z1):
    """A plan polygon (x, y) extruded upwards from z0 to z1."""
    v0 = [bm.verts.new((x, y, z0)) for x, y in pts]
    v1 = [bm.verts.new((x, y, z1)) for x, y in pts]
    bm.faces.new(list(reversed(v0)))
    bm.faces.new(v1)
    n = len(pts)
    for i in range(n):
        j = (i + 1) % n
        bm.faces.new((v0[i], v0[j], v1[j], v1[i]))


FT = 0.06
WT = 0.16


def _frame(kit, bm, w, h, z0):
    """Two jambs and a head around a w x h opening starting at z0."""
    kit['add_box_c'](bm, FT, WT, h, cx=-(w / 2 + FT / 2), z0=z0)
    kit['add_box_c'](bm, FT, WT, h, cx=(w / 2 + FT / 2), z0=z0)
    kit['add_box_c'](bm, w + 2 * FT, WT, FT, z0=z0 + h)


def build_window_arch(bm, p, kit):
    N = lambda k, d: kit['num'](p, k, d)  # noqa: E731
    w, h, sill = N('w', 1.2), N('h', 1.4), N('sill', 0.9)
    arch = max(0.05, N('arch', N('w', 1.2) / 2))
    pi = kit['math'].pi
    kit['add_box_c'](bm, FT, WT, h, cx=-(w / 2 + FT / 2), z0=sill)
    kit['add_box_c'](bm, FT, WT, h, cx=(w / 2 + FT / 2), z0=sill)
    kit['add_box_c'](bm, w + 2 * FT, WT, FT, z0=sill - FT)  # sill board
    _ring(kit, bm, 0.0, sill + h, w / 2, arch, w / 2 + FT, arch + FT, 0.0, pi, 20, -WT / 2, WT / 2)
    kit['add_box_c'](bm, w - 0.02, 0.012, h - 0.02, z0=sill)  # glass
    _fan(kit, bm, 0.0, sill + h, w / 2 - 0.01, arch - 0.01, 0.0, pi, 20, -0.006, 0.006)
    return ('', [])


def build_window_round(bm, p, kit):
    N = lambda k, d: kit['num'](p, k, d)  # noqa: E731
    r, sill = N('r', 0.6), N('sill', 1.2)
    tau = 2 * kit['math'].pi
    _ring(kit, bm, 0.0, sill + r, r, r, r + FT, r + FT, 0.0, tau, 32, -WT / 2, WT / 2)
    _fan(kit, bm, 0.0, sill + r, r, r, 0.0, tau, 32, -0.006, 0.006)
    return ('', [])


def build_window_bay(bm, p, kit):
    N = lambda k, d: kit['num'](p, k, d)  # noqa: E731
    w, h, sill, dep = N('w', 2.4), N('h', 1.4), N('sill', 0.9), max(0.1, N('depth', 0.8))
    plan = [(-w / 2, 0.0), (-w * 0.25, dep), (w * 0.25, dep), (w / 2, 0.0)]
    _plan_prism(bm, plan, sill, sill + FT)  # sill slab
    _plan_prism(bm, plan, sill + h - FT, sill + h)  # head slab
    for cx, cy in plan:
        kit['add_box_c'](bm, FT, FT, h, cx=cx, cy=cy, z0=sill)  # corner posts
    inner = [(x * 0.96, y * 0.96) for x, y in plan]
    _plan_prism(bm, inner, sill + FT, sill + h - FT)  # the glazed volume
    return ('~', [])


def build_window_strip(bm, p, kit):
    N = lambda k, d: kit['num'](p, k, d)  # noqa: E731
    w, h, sill = N('w', 8.0), N('h', 1.0), N('sill', 1.1)
    kit['add_box_c'](bm, w + 2 * FT, WT, FT, z0=sill - FT)
    kit['add_box_c'](bm, w + 2 * FT, WT, FT, z0=sill + h)
    kit['add_box_c'](bm, FT, WT, h, cx=-(w / 2 + FT / 2), z0=sill)
    kit['add_box_c'](bm, FT, WT, h, cx=(w / 2 + FT / 2), z0=sill)
    bays = max(1, int(round(w / 1.5)))
    for i in range(1, bays):
        kit['add_box_c'](bm, 0.05, 0.08, h, cx=-w / 2 + w * i / bays, z0=sill)
    kit['add_box_c'](bm, w - 0.02, 0.012, h - 0.02, z0=sill)
    return ('', [])


def build_door_garage(bm, p, kit):
    N = lambda k, d: kit['num'](p, k, d)  # noqa: E731
    w, h = N('w', 2.5), N('h', 2.2)
    n = max(1, min(24, int(round(N('panels', 4)))))
    _frame(kit, bm, w, h, 0.0)
    ph = h / n
    for i in range(n):
        kit['add_box_c'](bm, w - 0.04, 0.06, ph - 0.03, z0=i * ph + 0.015)
    return ('', [])


def build_door_sliding(bm, p, kit):
    N = lambda k, d: kit['num'](p, k, d)  # noqa: E731
    w, h = N('w', 2.4), N('h', 2.1)
    _frame(kit, bm, w, h, 0.0)
    kit['add_box_c'](bm, w / 2 - 0.03, 0.02, h - FT, cx=-w / 4, cy=-0.03, z0=FT / 2)
    kit['add_box_c'](bm, w / 2 - 0.03, 0.02, h - FT, cx=w / 4, cy=0.03, z0=FT / 2)
    return ('', [])


def build_door_french(bm, p, kit):
    N = lambda k, d: kit['num'](p, k, d)  # noqa: E731
    w, h = N('w', 1.6), N('h', 2.1)
    lw = w / 2 - 0.02
    _frame(kit, bm, w, h, 0.0)
    for s in (-1, 1):
        cx = s * w / 4
        kit['add_box_c'](bm, 0.05, 0.05, h - 0.04, cx=cx - (lw / 2 - 0.025), z0=0.0)
        kit['add_box_c'](bm, 0.05, 0.05, h - 0.04, cx=cx + (lw / 2 - 0.025), z0=0.0)
        kit['add_box_c'](bm, lw, 0.05, 0.05, cx=cx, z0=0.0)
        kit['add_box_c'](bm, lw, 0.05, 0.05, cx=cx, z0=h - 0.09)
        kit['add_box_c'](bm, lw - 0.1, 0.014, h - 0.2, cx=cx, z0=0.08)
    return ('', [])


def build_curtain_wall(bm, p, kit):
    N = lambda k, d: kit['num'](p, k, d)  # noqa: E731
    L, h = N('len', 6.0), N('h', 2.7)
    mu, tr, t = max(0.2, N('mullion', 1.5)), max(0.2, N('transom', 1.2)), N('t', 0.15)
    kit['add_box_c'](bm, L, 0.012, h, z0=0.0)  # the sheet of glass
    nv, nh = max(1, int(round(L / mu))), max(1, int(round(h / tr)))
    for i in range(nv + 1):
        x = min(L / 2 - FT / 2, max(-L / 2 + FT / 2, -L / 2 + L * i / nv))
        kit['add_box_c'](bm, FT, t, h, cx=x, z0=0.0)
    for i in range(nh + 1):
        z = min(h - FT, max(0.0, h * i / nh - FT / 2))
        kit['add_box_c'](bm, L, t, FT, z0=z)
    return ('', [])


BUILDERS = {
    'window_arch': build_window_arch,
    'window_round': build_window_round,
    'window_bay': build_window_bay,
    'window_strip': build_window_strip,
    'door_garage': build_door_garage,
    'door_sliding': build_door_sliding,
    'door_french': build_door_french,
    'curtain_wall': build_curtain_wall,
}
