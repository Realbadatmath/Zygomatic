# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""organise_model — Blender geometry for the Organise family's kinds.

Local frame (arch_blender_build.build_kind): X along, Y = studio -Z, Z up,
bottom at z=0. A studio local offset (x, y, z) is therefore Blender
(x, -z, y), and the studio's ry is an ordinary rotation about Blender's +Z.

component
    An APPROXIMATION, and it says so. The browser builds a component from its
    children's real arGeom() output; here each child is rebuilt from the kit's
    own helpers: a box for the box-like kinds (wall, slab, beam, column_rect,
    box, roof-less massing…), a cylinder for the round ones, and for anything
    else a plain bounding box from whatever size parameters the child carries.
    When any child took that last road the object comes back with the prefix
    '~', so a Blender scene never pretends a component is exact.

zone
    A flat extruded polygon: the plan points of p.pts swept from z=0 to z=h.
    arch_blender_build.add_prism sweeps a profile along X or Y — it cannot
    extrude a PLAN polygon upward — so the prism is built here, in the same
    shape (bottom cap, top cap, side quads).

gridline
    A VOID: a grid line is a line on the plan, not a solid. Declaring it in
    VOID_KINDS is not enough — a kind with no BUILDERS entry falls through to
    arch_blender_build.build_kind's generic branch, which gives an unknown kind
    a 1 m cuboid. build_gridline is therefore registered and adds nothing, the
    same no-op the measure_annotations family uses for its three kinds.
"""

import math
import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)


VOID_KINDS = ['gridline']

# kinds this file can rebuild exactly from their parameters
_BOXY = {
    'wall': lambda N: (N('len', 4.0), N('t', 0.24), N('h', 2.7)),
    'partition': lambda N: (N('len', 4.0), N('t', 0.1), N('h', 2.7)),
    'slab': lambda N: (N('w', 4.0), N('d', 4.0), N('t', 0.22)),
    'beam': lambda N: (N('len', 4.0), N('w', 0.2), N('h', 0.4)),
    'column_rect': lambda N: (N('w', 0.3), N('d', 0.3), N('h', 2.7)),
    'box': lambda N: (N('w', 1.0), N('d', 1.0), N('h', 1.0)),
    'door': lambda N: (N('w', 0.9), 0.06, N('h', 2.1)),
    'window': lambda N: (N('w', 1.2), 0.06, N('h', 1.2)),
    'opening': lambda N: (N('w', 1.0), 0.06, N('h', 2.1)),
}
_ROUND = {
    'column_round': lambda N: (N('r', 0.15), N('h', 2.7)),
    'cylinder': lambda N: (N('r', 0.5), N('h', 1.0)),
    'pipe': lambda N: (N('r', 0.1), N('len', 2.0)),
}


def _prism_z(bm, pts, h):
    """A plan polygon (list of (x, y) in Blender's XY) extruded from 0 to h."""
    lo = [bm.verts.new((x, y, 0.0)) for x, y in pts]
    hi = [bm.verts.new((x, y, h)) for x, y in pts]
    bm.faces.new(list(reversed(lo)))
    bm.faces.new(hi)
    n = len(pts)
    for i in range(n):
        j = (i + 1) % n
        bm.faces.new((lo[i], lo[j], hi[j], hi[i]))


def _child(bm, kind, p, kit):
    """Fill bm with ONE child's local geometry. True when the kind was known,
    False when it fell back to a bounding box."""
    num = kit['num']

    def N(k, d):
        return num(p, k, d)

    if kind in _BOXY:
        sx, sy, sz = _BOXY[kind](N)
        kit['add_box_c'](bm, max(sx, 1e-3), max(sy, 1e-3), max(sz, 1e-3))
        return True
    if kind in _ROUND:
        r, h = _ROUND[kind](N)
        kit['add_cylinder'](bm, max(r, 1e-3), max(h, 1e-3), 0.0, 24)
        return True
    if kind == 'zone':
        _build_zone(bm, p, kit)
        return True
    if kind == 'gridline':
        return True  # a void: no mesh, and that is correct
    # anything else: a bounding box from whatever size parameters it carries
    sx = N('len', 0.0) or N('w', 0.0) or 2 * N('r', 0.0) or 1.0
    sy = N('d', 0.0) or N('t', 0.0) or 2 * N('r', 0.0) or 1.0
    sz = N('h', 0.0) or N('t', 0.0) or 1.0
    kit['add_box_c'](bm, max(sx, 1e-3), max(sy, 1e-3), max(sz, 1e-3))
    return False


def build_component(bm, p, kit):
    bmesh = kit['bmesh']
    num = kit['num']
    kids = p.get('children') if isinstance(p.get('children'), list) else []
    exact = True
    built = 0
    for c in kids[:400]:
        if not isinstance(c, dict) or not c.get('kind'):
            continue
        before = set(bm.verts)
        exact = _child(bm, str(c['kind']), (c.get('p') if isinstance(c.get('p'), dict) else {}), kit) and exact
        vs = [v for v in bm.verts if v not in before]
        if not vs:
            continue
        built += 1
        s = num(c, 's', 1.0) or 1.0
        if s != 1.0:
            bmesh.ops.scale(bm, verts=vs, vec=(s, s, s))
        ry = num(c, 'ry', 0.0)
        if ry:
            bmesh.ops.rotate(bm, verts=vs, cent=(0.0, 0.0, 0.0), matrix=_rotz(kit, ry))
        # studio local (x, y, z) -> Blender (x, -z, y)
        bmesh.ops.translate(bm, verts=vs, vec=(num(c, 'x', 0.0) * s, -num(c, 'z', 0.0) * s, num(c, 'y', 0.0) * s))
    bm.normal_update()
    if not built:
        return ('', [])
    return ('' if exact else '~', [])


def _rotz(kit, a):
    """A Z rotation as the 3x3 matrix bmesh.ops.rotate wants, without
    importing mathutils at module level (this file is read outside Blender)."""
    import mathutils

    return mathutils.Matrix.Rotation(a, 3, 'Z')


def _build_zone(bm, p, kit):
    num = kit['num']
    raw = p.get('pts') if isinstance(p.get('pts'), list) else []
    pts = []
    for q in raw[:512]:
        try:
            x, z = float(q[0]), float(q[1])
        except (TypeError, ValueError, IndexError) as _exc:
            _zyg_log.debug('non-numeric zone point %r skipped: %s', q, _exc)
            continue
        if math.isfinite(x) and math.isfinite(z):
            pts.append((x, -z))  # studio z -> Blender -y
    # drop a repeated closing point and any duplicate neighbour
    out = []
    for q in pts:
        if not out or abs(q[0] - out[-1][0]) > 1e-6 or abs(q[1] - out[-1][1]) > 1e-6:
            out.append(q)
    if len(out) > 2 and abs(out[0][0] - out[-1][0]) < 1e-6 and abs(out[0][1] - out[-1][1]) < 1e-6:
        out.pop()
    if len(out) < 3:
        return
    # the studio's plan is left-handed against Blender's XY, so a shoelace test
    # keeps the caps facing up whichever way the points were clicked
    s = 0.0
    for i in range(len(out)):
        a, b = out[i], out[(i + 1) % len(out)]
        s += a[0] * b[1] - b[0] * a[1]
    if s < 0:
        out.reverse()
    _prism_z(bm, out, max(0.005, num(p, 'h', 0.05)))


def build_zone(bm, p, kit):
    _build_zone(bm, p, kit)
    bm.normal_update()
    return ('', [])


def build_gridline(bm, p, kit):
    """A void: adds nothing, so the exported model carries no grid line."""
    return ('~', [])


BUILDERS = {'component': build_component, 'zone': build_zone, 'gridline': build_gridline}
