# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""polygon_footprints — Blender geometry for slab_poly.

Local frame (see arch_blender_build.build_kind): X along, Y = studio -Z, Z up,
bottom at z=0. A studio-local point (x, z) is therefore (x, -z) here — the same
handedness flip arch_ext/polygon_footprints.js makes when it feeds the shape.

Holes are cut for real with mathutils.geometry.tessellate_polygon, which fills
an outer contour with its holes and hands back triangle indices into the
concatenated point list. When that is unavailable or refuses the input the
builder falls back to a solid plate and returns the '~' prefix, so an odd
polygon costs its holes, never the export.
"""

import math
import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)


DEF_PTS = [[-3.0, -2.0], [3.0, -2.0], [3.0, 2.0], [-3.0, 2.0]]


def _ring(v, fallback=None):
    """[[x, z], ...] -> a clean list of >= 3 (x, z) tuples, or `fallback`."""
    out = []
    if isinstance(v, (list, tuple)):
        for a in v:
            if not isinstance(a, (list, tuple)) or len(a) < 2:
                continue
            try:
                x, z = float(a[0]), float(a[1])
            except (TypeError, ValueError) as _exc:
                _zyg_log.debug('non-numeric ring vertex %r skipped: %s', a, _exc)
                continue
            if math.isfinite(x) and math.isfinite(z):
                out.append((x, z))
    if len(out) > 3 and abs(out[0][0] - out[-1][0]) < 1e-9 and abs(out[0][1] - out[-1][1]) < 1e-9:
        out.pop()
    return out if len(out) >= 3 else fallback


def _tess(loops):
    """Triangle indices into the flattened point list of `loops` (outer first)."""
    from mathutils import Vector
    from mathutils.geometry import tessellate_polygon

    tri = tessellate_polygon([[Vector((x, y, 0.0)) for x, y in L] for L in loops])
    n = sum(len(L) for L in loops)
    out = []
    for f in tri:
        if len(f) != 3:
            continue
        f = tuple(int(i) for i in f)
        if len(set(f)) == 3 and all(0 <= i < n for i in f):
            out.append(f)
    return out or None


def _plate(bm, loops, t, tris):
    """Caps from `tris` plus a vertical skin around every loop."""
    flat = [pt for L in loops for pt in L]
    bot = [bm.verts.new((x, y, 0.0)) for x, y in flat]
    top = [bm.verts.new((x, y, t)) for x, y in flat]
    made = 0
    for a, b, c in tris:
        for face in ((bot[a], bot[c], bot[b]), (top[a], top[b], top[c])):
            try:
                bm.faces.new(face)
                made += 1
            except ValueError as _exc:  # duplicate / degenerate
                _zyg_log.debug('duplicate or degenerate cap face skipped: %s', _exc)
    off = 0
    for L in loops:
        n = len(L)
        for i in range(n):
            j = (i + 1) % n
            try:
                bm.faces.new((bot[off + i], bot[off + j], top[off + j], top[off + i]))
                made += 1
            except ValueError as _exc:
                _zyg_log.debug('duplicate or degenerate side face skipped: %s', _exc)
        off += n
    bm.normal_update()
    return made


def build_slab_poly(bm, p, kit):
    bmesh = kit['bmesh']
    t = max(0.01, kit['num'](p, 't', 0.22))
    pts = _ring(p.get('pts'), DEF_PTS)
    holes = []
    raw = p.get('holes')
    if isinstance(raw, (list, tuple)):
        for h in raw:
            r = _ring(h)
            if r:
                holes.append([(x, -z) for x, z in r])
    outer = [(x, -z) for x, z in pts]

    prefix, tris = '', None
    try:
        tris = _tess([outer] + holes)
    except Exception:  # noqa: BLE001
        tris = None
    if tris is None and holes:  # retry without the holes
        prefix = '~'  # approximate: solid plate
        holes = []
        try:
            tris = _tess([outer])
        except Exception:  # noqa: BLE001
            tris = None
    if tris is not None and _plate(bm, [outer] + holes, t, tris) > 0:
        return (prefix, [])

    # last resort: one n-gon face (concave-safe) extruded to the thickness
    bm.clear()
    vs = [bm.verts.new((x, y, 0.0)) for x, y in outer]
    f = bm.faces.new(vs)
    r = bmesh.ops.extrude_face_region(bm, geom=[f])
    bmesh.ops.translate(bm, verts=[g for g in r['geom'] if isinstance(g, bmesh.types.BMVert)], vec=(0.0, 0.0, t))
    bm.normal_update()
    return ('~', [])


BUILDERS = {'slab_poly': build_slab_poly}
