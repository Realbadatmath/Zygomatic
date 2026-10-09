# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""curved_walls — Blender geometry for wall_arc and wall_ring.

Local frame (see arch_blender_build.build_kind): X along, Y = studio -Z, Z up,
bottom at z=0. Studio plan angle θ (0 = +X, 90 = studio -Z) is therefore the
ordinary counter-clockwise angle in Blender's XY plane: (r cosθ, r sinθ).
"""

import math


def _arc(bm, r, a0, a1, h, t, seg):
    ri, ro = max(0.05, r - t / 2), r + t / 2
    n = max(4, int(seg))
    a0r, a1r = math.radians(a0), math.radians(a1)
    inner, outer = [], []
    for i in range(n + 1):
        a = a0r + (a1r - a0r) * i / n
        c, s = math.cos(a), math.sin(a)
        inner.append((bm.verts.new((ri * c, ri * s, 0.0)), bm.verts.new((ri * c, ri * s, h))))
        outer.append((bm.verts.new((ro * c, ro * s, 0.0)), bm.verts.new((ro * c, ro * s, h))))
    for i in range(n):
        i0, i1 = inner[i], inner[i + 1]
        o0, o1 = outer[i], outer[i + 1]
        bm.faces.new((o0[0], o1[0], o1[1], o0[1]))  # outer face
        bm.faces.new((i1[0], i0[0], i0[1], i1[1]))  # inner face
        bm.faces.new((o0[1], o1[1], i1[1], i0[1]))  # top
        bm.faces.new((i0[0], i1[0], o1[0], o0[0]))  # bottom
    closed = abs((a1 - a0) % 360) < 1e-6 or abs(abs(a1 - a0) - 360) < 0.05
    if not closed:
        bm.faces.new((inner[0][0], outer[0][0], outer[0][1], inner[0][1]))  # start cap
        bm.faces.new((outer[-1][0], inner[-1][0], inner[-1][1], outer[-1][1]))  # end cap
    bm.normal_update()


def build_wall_arc(bm, p, kit):
    N = lambda k, d: kit['num'](p, k, d)
    a0, a1 = N('a0', 0.0), N('a1', 90.0)
    if abs(a1 - a0) < 0.5:
        a1 = a0 + 0.5
    _arc(bm, N('r', 5.0), a0, a1, N('h', 2.7), N('t', 0.24), N('seg', 24))
    return ('', [])


def build_wall_ring(bm, p, kit):
    N = lambda k, d: kit['num'](p, k, d)
    _arc(bm, N('r', 5.0), 0.0, 360.0, N('h', 2.7), N('t', 0.24), N('seg', 48))
    return ('', [])


BUILDERS = {'wall_arc': build_wall_arc, 'wall_ring': build_wall_ring}
