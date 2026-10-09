# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""interior_rooms — Blender geometry for the interior finishes.

Local frame (see arch_blender_build.build_kind): X along, Y = studio -Z
(depth), Z up, bottom at z=0. Every kind here is a box or a grid of boxes, so
the mapping from the tab's arGeom is one to one: a part the tab builds at
studio (x, y, z) is built here at (x, -z, y).
"""


def _grid_lines(span, step):
    """Offsets from -span/2 to +span/2, `step` apart, both edges included."""
    s = max(0.1, float(step))
    out, v = [], -span / 2.0
    while v < span / 2.0 - 1e-6:
        out.append(v)
        v += s
    out.append(span / 2.0)
    return out


def build_ceiling(bm, p, kit):
    N = lambda k, d: kit['num'](p, k, d)
    w, d, t = N('w', 6.0), N('d', 4.0), max(0.005, N('t', 0.1))
    kit['add_box_c'](bm, w, d, t, 0.0, 0.0, 0.0)
    return ('', [])


def build_floor_finish(bm, p, kit):
    N = lambda k, d: kit['num'](p, k, d)
    w, d, t = N('w', 6.0), N('d', 4.0), max(0.002, N('t', 0.02))
    kit['add_box_c'](bm, w, d, t, 0.0, 0.0, 0.0)
    return ('', [])


def build_skirting(bm, p, kit):
    N = lambda k, d: kit['num'](p, k, d)
    L, h, t = max(0.05, N('len', 4.0)), max(0.02, N('h', 0.1)), max(0.002, N('t', 0.015))
    kit['add_box_c'](bm, L, t, h, 0.0, 0.0, 0.0)
    return ('', [])


def build_raised_floor(bm, p, kit):
    N = lambda k, d: kit['num'](p, k, d)
    w, d = N('w', 6.0), N('d', 4.0)
    h, sp = max(0.05, N('h', 0.3)), max(0.2, N('pedestals', 0.6))
    td = min(0.03, h * 0.4)
    kit['add_box_c'](bm, w, d, td, 0.0, 0.0, h - td)
    nx = max(1, int(round(w / sp)))
    nz = max(1, int(round(d / sp)))
    if nx * nz > 900:
        nx, nz = min(nx, 30), min(nz, 30)
    ph = h - td
    for i in range(nx):
        px = -w / 2 + w * (i + 0.5) / nx
        for j in range(nz):
            pz = -d / 2 + d * (j + 0.5) / nz
            kit['add_box_c'](bm, 0.06, 0.06, ph, px, -pz, 0.0, 1)
    return ('', ['mat_steel'])


def build_suspended_ceiling(bm, p, kit):
    N = lambda k, d: kit['num'](p, k, d)
    w, d = N('w', 6.0), N('d', 4.0)
    t, tile = max(0.01, N('t', 0.05)), max(0.2, N('tiles', 0.6))
    bt = min(0.024, t * 0.5, w * 0.2, d * 0.2)
    xs, zs = _grid_lines(w, tile), _grid_lines(d, tile)
    for z in zs:  # bars running along X
        zc = max(-d / 2 + bt / 2, min(d / 2 - bt / 2, z))
        kit['add_box_c'](bm, w, bt, t, 0.0, -zc, 0.0, 1)
    for x in xs:  # bars running along Z
        xc = max(-w / 2 + bt / 2, min(w / 2 - bt / 2, x))
        kit['add_box_c'](bm, bt, d, t, xc, 0.0, 0.0, 1)
    tp = t * 0.4
    if (len(xs) - 1) * (len(zs) - 1) <= 900:
        for i in range(len(xs) - 1):
            for j in range(len(zs) - 1):
                pw, pd = xs[i + 1] - xs[i] - bt, zs[j + 1] - zs[j] - bt
                if pw <= 0.01 or pd <= 0.01:
                    continue
                kit['add_box_c'](bm, pw, pd, tp, (xs[i] + xs[i + 1]) / 2, -(zs[j] + zs[j + 1]) / 2, 0.0, 2)
    return ('', ['mat_steel', 'mat_plaster'])


BUILDERS = {
    'ceiling': build_ceiling,
    'floor_finish': build_floor_finish,
    'skirting': build_skirting,
    'raised_floor': build_raised_floor,
    'suspended_ceiling': build_suspended_ceiling,
}
