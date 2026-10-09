# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Body reference boxes: the skin volumes a placed group is judged against."""

import math

from .piece_map import _ABSORBED

# --------------------------------------------------------------------------
# body reference boxes
# --------------------------------------------------------------------------


def _body_boxes(body, threshold=0.0):
    """bone name -> world bbox of the body vertices this bone owns.

    A rig bone the piece mapping folds into a parent (LHipJoint into Hips, the
    finger bones into Hand) contributes to the parent's box, so that every body
    vertex is counted against exactly one skeleton group.

    ``threshold`` 0.5 is the brief's literal reading; it is reported but not
    gated on, because the bodies' bone-heat weighting puts > 0.5 on a torso
    bone only in a narrow strip beside that bone (the male body's Spine1 strip
    is 14 cm wide and 8 cm deep), so no anatomical ribcage can ever fit it.
    ``threshold`` 0 assigns every skinned vertex to its dominant bone, which
    partitions the whole body surface and is the box the gate uses.
    """
    boxes = {}
    for bone, points in _body_points(body, threshold).items():
        box = [list(points[0]), list(points[0])]
        for co in points:
            for i in range(3):
                box[0][i] = min(box[0][i], co[i])
                box[1][i] = max(box[1][i], co[i])
        boxes[bone] = box
    return boxes


def _body_points(body, threshold=0.0):
    """bone name -> world coordinates of the body vertices this bone owns."""
    idx_to_bone = {}
    for vg in body.vertex_groups:
        if vg.name == 'EYES':
            continue
        idx_to_bone[vg.index] = _ABSORBED.get(vg.name, vg.name)

    mw = body.matrix_world
    out = {}
    for v in body.data.vertices:
        best = None
        for g in v.groups:
            if g.group in idx_to_bone and g.weight > threshold:
                if best is None or g.weight > best[1]:
                    best = (idx_to_bone[g.group], g.weight)
        if best is not None:
            out.setdefault(best[0], []).append(mw @ v.co)
    return out


def _raw_group_points(body, name):
    """World coords of the body vertices whose dominant weight is exactly `name`.

    Unlike :func:`_body_points` this does not fold a group into the skeleton
    group that absorbs it, so the thumb flesh can still be found after LThumb
    has been folded into LeftHand.
    """
    vg = body.vertex_groups.get(name)
    if vg is None:
        return []
    mw = body.matrix_world
    out = []
    for v in body.data.vertices:
        best = max(v.groups, key=lambda g: g.weight, default=None)
        if best is not None and best.group == vg.index and best.weight > 0.0:
            out.append(mw @ v.co)
    return out


def _body_bvh(body):
    """BVH of the body's OUTER SKIN only.

    The base bodies carry two eyeball spheres inside the head (vertex group
    ``EYES``); to a nearest-surface test they are surfaces the skull is
    "outside" of, which reads half the cranium as protruding.  Drop them.
    """
    from mathutils.bvhtree import BVHTree

    mw = body.matrix_world
    me = body.data
    eyes = None
    for vg in body.vertex_groups:
        if vg.name == 'EYES':
            eyes = vg.index
    eye_verts = set()
    if eyes is not None:
        eye_verts = {v.index for v in me.vertices for g in v.groups if g.group == eyes and g.weight > 0.0}
    verts = [mw @ v.co for v in me.vertices]
    polys = [list(p.vertices) for p in me.polygons if not eye_verts.intersection(p.vertices)]
    return BVHTree.FromPolygons(verts, polys, all_triangles=False, epsilon=0.0)


def _column_overflow(cols, obj, cell=0.02):
    """Deepest break of the body's front/back silhouette by this piece.

    The nearest-surface reading below is the only one that sees sideways, but
    it is fooled wherever the body is not watertight -- it calls half the
    cranium "outside" because the nearest face is the inside of the mouth bag.
    This one only sees depth, and cannot be fooled: it asks, per 2 cm (x, z)
    column, whether the piece is in front of the chest or behind the back.
    """
    mw = obj.matrix_world
    worst = 0.0
    for v in obj.data.vertices:
        co = mw @ v.co
        band = cols.get((int(math.floor(co.x / cell)), int(math.floor(co.z / cell))))
        if band is None:
            continue
        over = max(band[0] - co.y, co.y - band[1])
        if over > worst:
            worst = over
    return worst


def _surface_depth(bvh, obj):
    """(fraction of vertices outside the skin, deepest protrusion, its place).

    Signed by the nearest surface normal.  The bodies are not watertight (open
    mouth bag, eye sockets), so ray parity lies; the nearest-face normal does
    not, once the interior eyeballs are out of the tree.
    """
    mw = obj.matrix_world
    outside = 0
    worst = 0.0
    where = None
    total = 0
    for v in obj.data.vertices:
        co = mw @ v.co
        loc, nor, _idx, _d = bvh.find_nearest(co)
        if loc is None:
            continue
        total += 1
        signed = (co - loc).dot(nor)
        if signed > 0.0:
            outside += 1
            if signed > worst:
                worst = signed
                where = co
    return (outside / total if total else 0.0), worst, where


def _collapsed_adjacency(arm):
    """group -> set of groups joined to it by a rig parent/child edge."""
    adj = {}
    for b in arm.data.bones:
        if not b.parent:
            continue
        x = _ABSORBED.get(b.name, b.name)
        y = _ABSORBED.get(b.parent.name, b.parent.name)
        if x == y:
            continue
        adj.setdefault(x, set()).add(y)
        adj.setdefault(y, set()).add(x)
    return adj


def _neighbour_box(arm, boxes, bone):
    """Body box of ``bone`` unioned with its rig parent's and children's.

    A piece legitimately reaches into the skin its bone's neighbours own: the
    ribcage is mapped to Spine1 but spans Spine's band, the toe phalanges start
    inside the foot's, the mandible hangs into the neck's, the ischium sits
    below the crotch in skin the thighs own.  Compared against the bone's own
    band alone, no placement can pass -- compared against the chain
    neighbourhood, a piece that has wandered into a different limb still fails.

    Adjacency is taken on the *collapsed* rig graph, where every bone folded
    into a group (LHipJoint, the finger stubs) has become that group: Hips and
    LeftUpLeg are neighbours even though LHipJoint sits between them.
    """
    names = {bone} | _collapsed_adjacency(arm).get(bone, set())

    lo = [1e9] * 3
    hi = [-1e9] * 3
    for n in names:
        box = boxes.get(n)
        if not box:
            continue
        for i in range(3):
            lo[i] = min(lo[i], box[0][i])
            hi[i] = max(hi[i], box[1][i])
    if lo[0] > hi[0]:
        return [0.0, 0.0, 0.0], [0.0, 0.0, 0.0]
    return lo, hi
