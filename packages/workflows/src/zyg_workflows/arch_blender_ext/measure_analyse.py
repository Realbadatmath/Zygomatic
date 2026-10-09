# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""measure_analyse — Blender geometry for annotation and dimension.

Local frame (see arch_blender_build.build_kind): X along, Y = studio -Z
(depth), Z up, bottom at z=0. The tab draws the dimension's shaft as a line;
Blender has no line primitive worth exporting, so the shaft is a 20 mm square
bar — a real, printable, measurable stick of the same length.
"""


def build_annotation(bm, p, kit):
    N = lambda k, d: kit['num'](p, k, d)  # noqa: E731
    h = max(0.2, N('h', 1.5))
    r = max(0.02, N('r', 0.15))
    kit['add_cylinder'](bm, r * 0.18, h, z0=0.0, seg=12)  # pole
    kit['add_sphere'](bm, r, h, useg=16, vseg=10)  # ball head at the top
    return ('', [])


def build_dimension(bm, p, kit):
    N = lambda k, d: kit['num'](p, k, d)  # noqa: E731
    L = max(0.05, N('len', 5.0))
    t = max(0.02, N('tick', 0.3))
    kit['add_box_c'](bm, L, 0.02, 0.02)  # the shaft, along X
    kit['add_box_c'](bm, 0.03, t, 0.03, cx=-L / 2)  # end ticks, across it
    kit['add_box_c'](bm, 0.03, t, 0.03, cx=L / 2)
    return ('', [])


BUILDERS = {'annotation': build_annotation, 'dimension': build_dimension}
