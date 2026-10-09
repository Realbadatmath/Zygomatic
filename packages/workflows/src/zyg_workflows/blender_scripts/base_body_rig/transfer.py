# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The MPFB donor and the two joint transfers — base_body_rig sections 5-7."""

import bisect

import bpy
from mathutils import Vector

from .scene import (
    ARM_SLICE_FRAC,
    CLUSTER_GAP,
    PA,
    SLICE_BAND,
    UV_MARGIN,
    activate,
    apply_transforms,
    bbox,
    facing_sign,
    local_verts,
)

import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)

# -------------------------------------------------------------------- donor


class DonorArgs(object):
    def __init__(self, gender):
        self.gender = gender
        self.age = 25.0
        self.height01 = 0.5
        self.weight = 0.5
        self.muscle = 0.5
        self.name = 'donor'


def build_donor(gender, target_height):
    donor = PA.build_body(DonorArgs(gender))
    arm = PA.add_rig(donor, 'donor')
    PA.strip_helpers(donor)
    bpy.context.view_layer.update()
    raw = PA.standing_height(donor)
    PA.scale_actor(arm, donor, target_height / raw)
    bpy.context.view_layer.update()
    apply_transforms(donor)
    apply_transforms(arm)
    bpy.context.view_layer.update()
    lo, _hi = bbox(local_verts(donor))
    if abs(lo.z) > 1e-4:  # feet back on the ground
        for vert in donor.data.vertices:
            vert.co.z -= lo.z
        donor.data.update()
        activate(arm)
        bpy.ops.object.mode_set(mode='EDIT')
        for bone in arm.data.edit_bones:
            roll = bone.roll
            bone.head = bone.head - Vector((0.0, 0.0, lo.z))
            bone.tail = bone.tail - Vector((0.0, 0.0, lo.z))
            bone.roll = roll
        bpy.ops.object.mode_set(mode='OBJECT')
    sign = facing_sign(local_verts(donor))
    _zyg_log.info(
        '[rig] donor: %d verts, %.4f m -> x%.5f -> %.4f m, facing_sign %+d'
        % (len(donor.data.vertices), raw, target_height / raw, PA.standing_height(donor), sign)
    )
    if sign > 0:
        raise SystemExit('donor faces +Y; the transfer assumes both bodies face -Y')
    return donor, arm


# ------------------------------------------------------------ slice transfer


class ZIndex(object):
    """Vertices sorted by z, so a horizontal slice is a bisect away."""

    def __init__(self, points):
        self.points = sorted(points, key=lambda p: p.z)
        self.zs = [p.z for p in self.points]
        self.zmin = self.zs[0]
        self.zmax = self.zs[-1]

    def band(self, z, half=SLICE_BAND):
        lo = bisect.bisect_left(self.zs, z - half)
        hi = bisect.bisect_right(self.zs, z + half)
        return self.points[lo:hi]

    def clusters(self, z, half=SLICE_BAND, gap=CLUSTER_GAP):
        sel = sorted(self.band(z, half), key=lambda p: p.x)
        if not sel:
            return []
        out = [[sel[0]]]
        for point in sel[1:]:
            if point.x - out[-1][-1].x > gap:
                out.append([])
            out[-1].append(point)
        return out


def cluster_box(cluster):
    xs = [p.x for p in cluster]
    ys = [p.y for p in cluster]
    return min(xs), max(xs), min(ys), max(ys)


def cluster_centroid(cluster):
    n = float(len(cluster))
    return (sum(p.x for p in cluster) / n, sum(p.y for p in cluster) / n)


def half_width(points, positive):
    """How far the body reaches out from its centre line on one side of a slice."""
    return max(p.x for p in points) if positive else -min(p.x for p in points)


def pick_cluster(clusters, x):
    """The cluster this x falls in, or the nearest one."""
    for i, cluster in enumerate(clusters):
        x0, x1, _y0, _y1 = cluster_box(cluster)
        if x0 <= x <= x1:
            return i
    return min(
        range(len(clusters)),
        key=lambda i: min(abs(x - cluster_box(clusters[i])[0]), abs(x - cluster_box(clusters[i])[1])),
    )


def clamp_into(x, low, high, margin=UV_MARGIN):
    span = high - low
    return max(low + margin * span, min(high - margin * span, x))


def transfer_point(point, donor_index, base_index):
    """Donor joint -> the same anatomical place on the base body.

    x is carried across as the same FRACTION of the body's half width at that
    height. Matching clusters by their rank in the row was tried first and is
    wrong: at 0.90 m the donor's crotch has already split into two thighs while
    the base body's has not, so "first cluster left of centre" is the donor's
    thigh and the base body's HAND, and the hip sockets land in the fingers.
    The half-width fraction has no such ambiguity, and the cluster is then only
    used for the depth (y) mapping — which is the part that does need to know
    whether it is looking at an arm or a torso."""
    z = min(max(point.z, donor_index.zmin + 1e-4), donor_index.zmax - 1e-4)
    zb = min(max(point.z, base_index.zmin + 1e-4), base_index.zmax - 1e-4)
    dband, bband = donor_index.band(z), base_index.band(zb)
    if not dband or not bband:
        return point.copy(), 'failed: empty slice'

    positive = point.x >= 0.0
    dwide, bwide = half_width(dband, positive), half_width(bband, positive)
    fx = point.x / dwide if dwide > 1e-6 else 0.0
    x = fx * bwide

    dcl, bcl = donor_index.clusters(z), base_index.clusters(zb)
    dbox = cluster_box(dcl[pick_cluster(dcl, point.x)])
    bidx = pick_cluster(bcl, x)
    bbx0, bbx1, bby0, bby1 = cluster_box(bcl[bidx])
    # UV_MARGIN keeps the joint a hair inside the slice: a point exactly on the
    # bounding box is a point on the skin, which "inside the mesh" rightly refuses.
    v = (point.y - dbox[2]) / (dbox[3] - dbox[2]) if dbox[3] - dbox[2] > 1e-6 else 0.5
    v = max(UV_MARGIN, min(1.0 - UV_MARGIN, v))
    out = Vector((clamp_into(x, bbx0, bbx1), bby0 + v * (bby1 - bby0), point.z))
    note = 'fx%+.3f of %.3f -> %.3f v%.2f; donor %d clusters, base %d, cluster %d' % (
        fx,
        dwide,
        bwide,
        v,
        len(dcl),
        len(bcl),
        bidx,
    )
    return out, note


# ------------------------------------------------------------ arm transfer

# Bones carried along the arm axis instead of by height. ``LeftArm``'s HEAD is
# the shoulder joint and stays with the slice transfer (it is the axis' own
# origin); everything from its tail — the elbow — outwards moves by fraction.
ARM_CHAIN = ('Arm', 'ForeArm', 'Hand', 'FingerBase', 'HandIndex1')


def arm_side(name, kind):
    """+1 for a left arm point, -1 for a right one, None for 'not on an arm'."""
    if name in ('LThumb', 'RThumb'):
        return 1 if name[0] == 'L' else -1
    for suffix in ARM_CHAIN:
        for prefix, side in (('Left', 1), ('Right', -1)):
            if name == prefix + suffix:
                if suffix == 'Arm' and kind == 'head':
                    return None  # the shoulder joint IS the axis origin
                return side
    return None


def arm_region(zindex, shoulder):
    """The vertices of one arm, from the armpit down to the fingertips.

    Walked as horizontal slices: from the shoulder downwards the first slice
    that splits into three or more clusters is the armpit, and from there the
    outermost cluster on the shoulder's side is the arm — until the slices stop
    splitting, which is the bottom of the hand. This says nothing about how the
    arm is angled, so it holds for the donor's open A-pose and for the base
    body's much steeper one alike.

    Two guards stop the walk running on down the leg when a low-hanging hand
    touches the thigh and the two clusters merge: the arm's inner edge may not
    jump back towards the mid-line, and nothing below 0.30 of standing height is
    an arm on either body (the fingertips hang at about 0.40)."""
    side = 1 if shoulder.x >= 0.0 else -1
    inner = lambda box: box[0] if side > 0 else -box[1]
    z = shoulder.z
    while z > 0.25 * zindex.zmax and len(zindex.clusters(z)) < 3:
        z -= SLICE_BAND
    out, edge = [], None
    while z > max(zindex.zmin, 0.30 * zindex.zmax):
        clusters = zindex.clusters(z)
        if len(clusters) < 3:
            break
        box = cluster_box(clusters[-1] if side > 0 else clusters[0])
        if inner(box) <= 0.0 or (edge is not None and inner(box) < edge - CLUSTER_GAP):
            break
        edge = inner(box) if edge is None else max(edge, inner(box))
        out.extend(clusters[-1] if side > 0 else clusters[0])
        z -= SLICE_BAND
    return out


class ArmFrame(object):
    """One arm as a centre line plus a cross-section, in its own coordinates.

    ``u`` is the fraction of the way along the arm's own centre line — the
    centroid of each cross-section, strung shoulder to fingertip and measured by
    ARC length, not along the straight chord. The chord is what the first
    version used and it flattens a bent arm: projecting the elbow of a donor
    whose arm is not quite straight onto the shoulder-fingertip line puts it at
    0.35 of the way down instead of 0.42, and the forearm comes out longer than
    the upper arm. The centre line follows the bend, so the donor's own segment
    proportions survive.

    ``a`` and ``b`` are the offsets across the arm at that point, along +Y
    (depth) and laterally outwards. The lateral axis is signed by the side, so a
    left and a right arm describe the same anatomy with the same numbers."""

    NODES = 24

    def __init__(self, side, shoulder, tip, points):
        span = tip - shoulder
        chord, reach = span.normalized(), span.length
        nodes = [shoulder.copy()]
        for i in range(1, self.NODES):
            s = float(i) / self.NODES
            sel = [p for p in points if abs((p - shoulder).dot(chord) / reach - s) <= 0.5 / self.NODES]
            if len(sel) >= 8:
                centre = Vector((0.0, 0.0, 0.0))
                for p in sel:
                    centre += p
                nodes.append(centre / float(len(sel)))
        nodes.append(tip.copy())
        self.nodes = nodes
        self.arc = [0.0]
        for a, b in zip(nodes, nodes[1:]):
            self.arc.append(self.arc[-1] + (b - a).length)
        self.length = self.arc[-1]
        self.frames = []
        for a, b in zip(nodes, nodes[1:]):
            direction = (b - a).normalized()
            e1 = Vector((0.0, 1.0, 0.0)) - direction * direction.y
            # +Y made perpendicular to the arm is never mirrored, so both arms
            # agree; the lateral axis is flipped by the side so both point out.
            e1 = e1.normalized() if e1.length > 1e-6 else Vector((0.0, 0.0, 1.0))
            self.frames.append((e1, direction.cross(e1) * float(side)))
        self.local = [self.locate(p) for p in points]

    def locate(self, point):
        """(u, a, b): how far along the centre line, and how far off it."""
        best = None
        for i, (a, b) in enumerate(zip(self.nodes, self.nodes[1:])):
            span = b - a
            t = min(1.0, max(0.0, (point - a).dot(span) / span.length_squared))
            foot = a + span * t
            gap = (point - foot).length
            if best is None or gap < best[0]:
                best = (gap, i, t, foot)
        _gap, i, t, foot = best
        u = (self.arc[i] + t * (self.arc[i + 1] - self.arc[i])) / self.length
        e1, e2 = self.frames[i]
        across = point - foot
        return u, across.dot(e1), across.dot(e2)

    def section(self, u):
        """(a0, a1, b0, b1) of the arm's cross-section at this fraction."""
        half = ARM_SLICE_FRAC
        for _ in range(6):
            sel = [(a, b) for uu, a, b in self.local if abs(uu - u) <= half]
            if len(sel) >= 8:
                return (
                    min(a for a, _b in sel),
                    max(a for a, _b in sel),
                    min(b for _a, b in sel),
                    max(b for _a, b in sel),
                )
            half *= 2.0
        return -0.05, 0.05, -0.05, 0.05

    def at(self, u, fa, fb):
        target = max(0.0, min(1.0, u)) * self.length
        i = max(0, min(len(self.nodes) - 2, bisect.bisect_right(self.arc, target) - 1))
        run = self.arc[i + 1] - self.arc[i]
        foot = self.nodes[i].lerp(self.nodes[i + 1], (target - self.arc[i]) / run if run > 1e-9 else 0.0)
        e1, e2 = self.frames[i]
        a0, a1, b0, b1 = self.section(u)
        return foot + e1 * (a0 + fa * (a1 - a0)) + e2 * (b0 + fb * (b1 - b0))


class ArmAxis(object):
    """The donor arm and the base arm, joint for joint by fraction along them."""

    def __init__(self, side, donor_shoulder, donor_points, base_shoulder, base_points):
        self.side = side
        tip_d = max(donor_points, key=lambda p: (p - donor_shoulder).length)
        tip_b = max(base_points, key=lambda p: (p - base_shoulder).length)
        self.donor = ArmFrame(side, donor_shoulder, tip_d, donor_points)
        self.base = ArmFrame(side, base_shoulder, tip_b, base_points)

    def transfer(self, point):
        u, a, b = self.donor.locate(point)
        a0, a1, b0, b1 = self.donor.section(u)
        frac = lambda v, lo, hi: max(UV_MARGIN, min(1.0 - UV_MARGIN, (v - lo) / (hi - lo))) if hi - lo > 1e-6 else 0.5
        fa, fb = frac(a, a0, a1), frac(b, b0, b1)
        out = self.base.at(u, fa, fb)
        note = 'arm axis %+d: u %.3f of %.3f m -> %.3f m, a %.2f b %.2f' % (
            self.side,
            u,
            self.donor.length,
            self.base.length,
            fa,
            fb,
        )
        return out, note


def build_arm_axes(donor_index, base_index, table):
    """One ArmAxis per side, or nothing when either arm cannot be isolated."""
    axes, report = {}, {}
    for side, bone in ((1, 'LeftArm'), (-1, 'RightArm')):
        shoulder_d = table[bone][0]
        shoulder_b, _note = transfer_point(shoulder_d, donor_index, base_index)
        region_d = arm_region(donor_index, shoulder_d)
        region_b = arm_region(base_index, shoulder_b)
        if len(region_d) < 50 or len(region_b) < 50:
            report[bone] = 'not isolated: donor %d verts, base %d' % (len(region_d), len(region_b))
            _zyg_log.info(
                '[rig] arm axis %s NOT built (%s) — falling back to the slice transfer' % (bone, report[bone])
            )
            continue
        axis = ArmAxis(side, shoulder_d, region_d, shoulder_b, region_b)
        axes[side] = axis
        report[bone] = 'donor %d verts %.4f m, base %d verts %.4f m' % (
            len(region_d),
            axis.donor.length,
            len(region_b),
            axis.base.length,
        )
        _zyg_log.info('[rig] arm axis %s: %s' % (bone, report[bone]))
        if side > 0:
            # Girth down the base arm, the evidence behind WRIST_FRACTION: the
            # narrowest cross-section IS the mesh's wrist, and the joint the
            # donor lands there should sit at the same u.
            prof = []
            for step in range(6, 21):
                u = step / 20.0
                sel = [(a, b) for uu, a, b in axis.base.local if abs(uu - u) <= 0.02]
                if len(sel) < 8:
                    continue
                girth = max(
                    max(a for a, _ in sel) - min(a for a, _ in sel), max(b for _, b in sel) - min(b for _, b in sel)
                )
                prof.append('u%.2f z%.3f g%.3f' % (u, axis.base.at(u, 0.5, 0.5).z, girth))
            _zyg_log.info('[rig] base arm profile: ' + ' '.join(prof))
    return axes, report
