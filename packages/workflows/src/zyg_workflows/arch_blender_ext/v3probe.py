# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""v3probe — the Blender half of the v3 seam's test fixture.

Same quad, same arithmetic, same vertex order as arch_ext/v3probe.js: a 2 m x
2 m plan quad whose far edge is lifted by the number of `box` records in the
drawing, coloured red / green / blue / white per vertex.

It proves the two things the sculpted ground needs from this engine:
  · kit['records'] — the drawing's whole object list reaches a builder;
  · the third element of the return, `vcolors` — one (r, g, b) per vertex in
    bm.verts order, which arch_blender_build turns into a 'Col' colour
    attribute and a material whose Base Color reads it.

Local frame (arch_blender_build.build_kind): X along, Y = studio -Z, Z up.
Studio (x, y, z) becomes (x, -z, y), so the studio quad
(-1,0,-1) (1,0,-1) (1,h,1) (-1,h,1) is (-1,1,0) (1,1,0) (1,-1,h) (-1,-1,h).
"""


def build_v3probe(bm, p, kit):
    h = float(sum(1 for r in (kit.get('records') or []) if isinstance(r, dict) and r.get('kind') == 'box'))
    vs = [bm.verts.new(v) for v in ((-1.0, 1.0, 0.0), (1.0, 1.0, 0.0), (1.0, -1.0, h), (-1.0, -1.0, h))]
    # two triangles, not one quad: the same topology the tab builds from its index
    bm.faces.new((vs[0], vs[1], vs[2]))
    bm.faces.new((vs[0], vs[2], vs[3]))
    vcolors = [(1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0), (1.0, 1.0, 1.0)]
    return ('', [], vcolors)


BUILDERS = {'v3probe': build_v3probe}
