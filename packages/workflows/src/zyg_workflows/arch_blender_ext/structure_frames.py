# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""structure_frames — Blender geometry for the structural skeleton kinds.

Local frame (see arch_blender_build.build_kind): X along, Y = studio -Z
(depth), Z up, bottom at z=0. So a studio part sized (sx in x, sy in studio z,
sz in y) is add_box_c(bm, sx, sy_depth, height, cx, cy, z0) here, and a studio
z coordinate becomes Blender y = -z.
"""

import math


def _member_xz(kit, bm, ax, az, bx, bz, sw, sd):
    """A rectangular member of section sw (in the XZ plane) x sd (along Y)
    between (ax, az) and (bx, bz) — the rafters, voussoirs and braces."""
    dx, dz = bx - ax, bz - az
    L = math.hypot(dx, dz)
    if L < 1e-5:
        return
    ux, uz = dx / L, dz / L
    nx, nz = -uz * sw / 2, ux * sw / 2
    profile = [(ax + nx, az + nz), (bx + nx, bz + nz), (bx - nx, bz - nz), (ax - nx, az - nz)]
    kit['add_prism'](bm, profile, 'y', -sd / 2, sd / 2)


def build_beam_i(bm, p, kit):
    N = lambda k, d: kit['num'](p, k, d)
    L, h, w = N('len', 5.0), N('h', 0.4), N('w', 0.2)
    tf = max(0.004, min(N('tf', 0.02), h / 2 - 0.002))
    tw = max(0.003, min(N('tw', 0.012), w))
    kit['add_box_c'](bm, L, w, tf, 0.0, 0.0, 0.0)
    kit['add_box_c'](bm, L, w, tf, 0.0, 0.0, h - tf)
    kit['add_box_c'](bm, L, tw, h - 2 * tf, 0.0, 0.0, tf)
    return ('', [])


def build_column_h(bm, p, kit):
    N = lambda k, d: kit['num'](p, k, d)
    h, w, d = N('h', 3.0), N('w', 0.3), N('d', 0.3)
    tf = max(0.004, min(N('tf', 0.02), d / 2 - 0.002))
    tw = max(0.003, min(N('tw', 0.012), w))
    kit['add_box_c'](bm, w, tf, h, 0.0, -(d / 2 - tf / 2), 0.0)
    kit['add_box_c'](bm, w, tf, h, 0.0, (d / 2 - tf / 2), 0.0)
    kit['add_box_c'](bm, tw, d - 2 * tf, h, 0.0, 0.0, 0.0)
    return ('', [])


def build_portal_frame(bm, p, kit):
    N = lambda k, d: kit['num'](p, k, d)
    span, h, rise = max(0.5, N('span', 12.0)), max(0.3, N('h', 6.0)), N('rise', 1.5)
    w, d = N('w', 0.25), N('d', 0.5)
    kit['add_box_c'](bm, w, d, h, -span / 2, 0.0, 0.0)
    kit['add_box_c'](bm, w, d, h, span / 2, 0.0, 0.0)
    if abs(rise) < 1e-4:
        kit['add_box_c'](bm, span, d, w, 0.0, 0.0, h)
    else:
        _member_xz(kit, bm, -span / 2, h, 0.0, h + rise, w, d)
        _member_xz(kit, bm, span / 2, h, 0.0, h + rise, w, d)
    return ('', [])


def build_arch_beam(bm, p, kit):
    N = lambda k, d: kit['num'](p, k, d)
    span, rise = max(0.5, N('span', 6.0)), max(0.05, N('rise', 1.5))
    w, d, seg = N('w', 0.25), N('d', 0.5), max(3, int(N('seg', 16)))
    R = (span * span / 4 + rise * rise) / (2 * rise)
    cz = rise - R
    a = math.asin(min(1.0, (span / 2) / R))

    def pt(t):
        th = (math.pi / 2 + a) + (-2 * a) * t
        return R * math.cos(th), cz + R * math.sin(th)

    for i in range(seg):
        ax, az = pt(i / seg)
        bx, bz = pt((i + 1) / seg)
        _member_xz(kit, bm, ax, az, bx, bz, w, d)
    return ('', [])


def build_buttress(bm, p, kit):
    """Back flat against the wall at studio z = -d/2, i.e. Blender y = +d/2."""
    N = lambda k, d: kit['num'](p, k, d)
    h, w, d = max(0.2, N('h', 3.0)), N('w', 0.6), max(0.1, N('d', 1.2))
    top = max(0.02, min(N('top', 0.3), d))
    profile = [(d / 2, 0.0), (d / 2, h), (d / 2 - top, h), (-d / 2, 0.0)]
    kit['add_prism'](bm, profile, 'x', -w / 2, w / 2)
    return ('', [])


def build_bracing_x(bm, p, kit):
    N = lambda k, d: kit['num'](p, k, d)
    w, h, t = max(0.2, N('w', 4.0)), max(0.2, N('h', 2.7)), N('t', 0.08)
    _member_xz(kit, bm, -w / 2, 0.0, w / 2, h, t, t)
    _member_xz(kit, bm, -w / 2, h, w / 2, 0.0, t, t)
    return ('', [])


def build_pergola(bm, p, kit):
    N = lambda k, d: kit['num'](p, k, d)
    w, d, h = max(0.5, N('w', 4.0)), max(0.5, N('d', 3.0)), max(0.6, N('h', 2.4))
    po = max(0.04, N('post', 0.12))
    nb = max(2, int(round(N('beams', 6))))
    ph = max(0.1, h - 2.5 * po)
    for sx in (-1, 1):
        for sy in (-1, 1):
            kit['add_box_c'](bm, po, po, ph, sx * (w / 2 - po / 2), sy * (d / 2 - po / 2), 0.0)
    for sy in (-1, 1):
        kit['add_box_c'](bm, w, po, 1.5 * po, 0.0, sy * (d / 2 - po / 2), h - 2.5 * po)
    for i in range(nb):
        x = -w / 2 + po / 2 + (w - po) * (i / (nb - 1) if nb > 1 else 0.5)
        kit['add_box_c'](bm, po, d, po, x, 0.0, h - po)
    return ('', [])


def build_cantilever(bm, p, kit):
    N = lambda k, d: kit['num'](p, k, d)
    L, w, h = max(0.2, N('len', 3.0)), N('w', 0.3), N('h', 0.5)
    kit['add_box_c'](bm, L, w, h, L / 2, 0.0, 0.0)
    return ('', [])


BUILDERS = {
    'beam_i': build_beam_i,
    'column_h': build_column_h,
    'portal_frame': build_portal_frame,
    'arch_beam': build_arch_beam,
    'buttress': build_buttress,
    'bracing_x': build_bracing_x,
    'pergola': build_pergola,
    'cantilever': build_cantilever,
}
