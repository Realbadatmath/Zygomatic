# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""pufferball.checks — the geometric invariants, the assembly entry point and bounds.

Verbatim sections of the original pufferball.py (lines 876-1038): is_fur_geometry,
signed_volume, assert_geometry, assert_parts_visible, build() and bounds().
"""

from .constants import IDX, P, Vector, _zyg_log, bmesh, bpy
from .geometry import _link
from .parts import (
    build_arms,
    build_body,
    build_eyes,
    build_face,
    build_feet,
    build_legs,
    build_mouth,
    build_tail,
    materials,
)


# ── checks ───────────────────────────────────────────────────────────────────
# Both of the worst defects this creature shipped with were invisible to every
# render that was ever looked at. Inverted normals are invisible because Cycles
# flips the shading normal toward the ray; a buried mouth is invisible because
# there is nothing to see. Neither needs a reference image or a judge to catch —
# only a count. These run on every build, so neither can come back quietly.

FUR_GEOMETRY_TAGS = ('_locks', '_tuft', '_wisp', '_fringe')


def is_fur_geometry(ob):
    """A mesh that IS fur (lock/tuft/wisp geometry from a look layer)."""
    return any(t in ob.name for t in FUR_GEOMETRY_TAGS)


def signed_volume(ob):
    """World-space signed volume by the divergence theorem. Negative means the
    normals point inward.

    bm.normal_update() after the transform is NOT optional: bm.transform() moves
    vertices and leaves every cached face normal in the OLD frame, so the sum
    silently pairs world-space positions with local-space normals and returns a
    number that is neither. It kept its sign here by luck and lost its magnitude
    (an arm read -0.000210 transformed against -0.000065 untransformed, for a
    rigid transform that cannot change the volume at all)."""
    bm = bmesh.new()
    bm.from_mesh(ob.data)
    bm.transform(ob.matrix_world)
    bm.normal_update()
    v = sum(f.normal.dot(f.calc_center_median()) * f.calc_area() for f in bm.faces) / 3.0
    bm.free()
    return v


def assert_geometry(parts, p=P):
    """Every closed part faces outward, nothing sinks through the floor, and the
    tail stays out of the body. Raises AssertionError listing every failure at
    once rather than stopping at the first."""
    bpy.context.view_layer.update()
    bad = []
    # Hidden objects are not the creature (a look layer parks the base mouth
    # below the floor and hides it); fur GEOMETRY (lock/wisp/tuft meshes) is fur,
    # not body — it may be an edge-only strand mesh with no polygons to carry UVs,
    # and its tips may brush the floor like hair does.
    solid = [ob for ob in parts if ob.name != 'pb_ground' and not ob.hide_render and not is_fur_geometry(ob)]

    for ob in solid:
        v = signed_volume(ob)
        if v < 0:
            bad.append('%s: inverted normals (signed volume %+.7f)' % (ob.name, v))
        if len(ob.data.polygons) and not ob.data.uv_layers:
            bad.append('%s: no UV layer' % ob.name)

    zmin = min((ob.matrix_world @ Vector(v.co)).z for ob in solid for v in ob.data.vertices)
    if zmin < -1e-4:
        bad.append('geometry sinks %.4f m through the ground plane' % -zmin)

    # Tail beads must not be swallowed by the body ellipsoid — but only from the
    # midpoint out. The base HAS to be inside it; that is what attaches the tail.
    tail_n = len([o for o in parts if o.name.startswith('pb_tail_')])
    for ob in parts:
        if not ob.name.startswith('pb_tail_'):
            continue
        try:
            if int(ob.name.rsplit('_', 1)[1]) < tail_n // 2:
                continue
        except (ValueError, IndexError) as _exc:
            _zyg_log.debug('tail index unparsable from object name %s: %s', ob.name, _exc)
        inside = 0
        for vt in ob.data.vertices:
            w = ob.matrix_world @ Vector(vt.co)
            if (
                (w.x / p['body_rx']) ** 2 + (w.y / p['body_ry']) ** 2 + ((w.z - p['body_lift']) / p['body_rz']) ** 2
            ) < 1.0:
                inside += 1
        frac = inside / float(len(ob.data.vertices))
        if frac > 0.5:
            bad.append('%s: %.0f%% inside the body' % (ob.name, frac * 100))

    # Consecutive tail beads must OVERLAP. The radius tapers along the spire while
    # the spacing does not, so a longer sweep at the same segment count pulls the
    # tip beads apart into a dotted line — visible in the side and three-quarter
    # views as a string of loose pearls rather than a tail.
    tail = sorted((o for o in parts if o.name.startswith('pb_tail_')), key=lambda o: o.name)
    for a, b in zip(tail, tail[1:]):
        ra = max(a.dimensions) / 2.0
        rb = max(b.dimensions) / 2.0
        gap = (a.matrix_world.translation - b.matrix_world.translation).length - (ra + rb)
        if gap > 0:
            bad.append('%s..%s: tail beads do not touch (gap %.4f m)' % (a.name, b.name, gap))

    if bad:
        raise AssertionError('geometry checks failed:\n  ' + '\n  '.join(bad))
    return True


def assert_parts_visible(index_arrays, idx_map=None, exclude=('ground',)):
    """Every part that owns a pass_index must occupy pixels in at least one view.

    `index_arrays` is an iterable of 2D IndexOB arrays, one per rendered view.
    A part visible in NO view is a placement bug — that is exactly the state
    pb_mouth shipped in, buried 42 mm inside the head with IDX['mouth'] reserved
    for it and no segment map ever containing one. This is the cheapest check in
    the pipeline and it is the one that would have caught it on day one."""
    idx_map = idx_map or IDX
    want = {k: v for k, v in idx_map.items() if k not in (exclude or ())}
    seen = {k: 0 for k in want}
    views = 0
    for arr in index_arrays:
        views += 1
        for name, i in want.items():
            seen[name] += int((arr == i).sum())
    dead = sorted(k for k, px in seen.items() if px == 0)
    if dead:
        raise AssertionError('parts with zero pixels in all %d views: %s' % (views, ', '.join(dead)))
    return seen


def build(scene, mats=None, p=P, ground=False, check=True):
    """Everything. Returns {'body':..., 'parts':[...], 'mats':{...}}."""
    mats = mats or materials()
    parts = [build_body(mats, scene, p), build_face(mats, scene, p)]
    parts += build_eyes(mats, scene, p)
    parts += build_mouth(mats, scene, p)
    parts += build_legs(mats, scene, p)
    parts += build_arms(mats, scene, p)
    parts += build_feet(mats, scene, p)
    parts += build_tail(mats, scene, p)
    if ground:
        me = bpy.data.meshes.new('pb_ground')
        s = 3.0
        me.from_pydata([(-s, -s, 0), (s, -s, 0), (s, s, 0), (-s, s, 0)], [], [(0, 1, 2, 3)])
        me.validate()
        g = bpy.data.objects.new('pb_ground', me)
        g.data.materials.append(mats['ground'])
        g.pass_index = IDX['ground']
        _link(g, scene)
        parts.append(g)
    if check:
        assert_geometry(parts, p)
    return {'parts': parts, 'mats': mats}


def bounds(parts):
    """World-space bbox of the creature, ignoring the ground plane.

    The view_layer.update() is not optional. In background mode nothing evaluates
    the depsgraph on its own, so `ob.matrix_world` still carries the scale the
    object had at creation — every part reports its UNSCALED local bbox and the
    body (built at radius 1.0 then scaled to ~0.15) measures 2 m across. That is
    how the first smoke test got a 2x2x2 creature and a "wider than tall" check
    that passed on 2.0 > 2.0."""
    bpy.context.view_layer.update()
    lo = Vector((1e9, 1e9, 1e9))
    hi = Vector((-1e9, -1e9, -1e9))
    for ob in parts:
        if ob.name == 'pb_ground':
            continue
        for c in ob.bound_box:
            w = ob.matrix_world @ Vector(c)
            lo = Vector((min(lo.x, w.x), min(lo.y, w.y), min(lo.z, w.z)))
            hi = Vector((max(hi.x, w.x), max(hi.y, w.y), max(hi.z, w.z)))
    return lo, hi
