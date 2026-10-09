# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Placement: the trunk block, the per-segment limb fits, ``compute_placement``."""

import math

from mathutils import Matrix, Vector

from .body_boxes import _body_points, _raw_group_points
from .linalg import _affine, _rotation_between, _segment_matrix
from .piece_map import TRUNK_BONES

# --------------------------------------------------------------------------
# placement
# --------------------------------------------------------------------------


def _bone_world(arm, name):
    b = arm.data.bones[name]
    mw = arm.matrix_world
    return (mw @ b.head_local).copy(), (mw @ b.tail_local).copy()


def _mean(origins, names):
    acc = Vector((0.0, 0.0, 0.0))
    for n in names:
        acc += origins[n]
    return acc / len(names)


def _limb_frames(origins, side):
    """(J_s, a_s) per limb bone, read from the piece origins."""
    sfx = '.' + side
    shoulder = origins['arm_humerus' + sfx]
    elbow = origins['arm_radius' + sfx]
    wrist = origins['hand_center' + sfx]
    # distal ends of the metacarpals == the MCP joints == the proximal phalanx
    # origins (the thumb points sideways, so it is left out of the mean).
    mcp = _mean(origins, ['proximal.%s%s' % (f, sfx) for f in ('index', 'middle', 'ring', 'little')])
    hip = origins['leg_femur' + sfx]
    knee = origins['leg_tibula' + sfx]
    ankle = origins['foot_talus' + sfx]
    toe_mean = _mean(origins, ['proximal.%d%s' % (i, sfx) for i in range(1, 6)])
    toe_tips = _mean(origins, ['distal.%d%s' % (i, sfx) for i in range(1, 6)])
    return {
        'Arm': (shoulder, elbow - shoulder),
        'ForeArm': (elbow, wrist - elbow),
        'Hand': (wrist, mcp - wrist),
        'UpLeg': (hip, knee - hip),
        'Leg': (knee, ankle - knee),
        'Foot': (ankle, toe_mean - ankle),
        'ToeBase': (toe_mean, toe_tips - toe_mean),
    }


TRUNK_ANCHORS = (
    ('skull', 'skull', 'Head'),
    ('hip', 'hip', 'LowerBack'),
    ('femur.L', 'leg_femur.L', 'LeftUpLeg'),
    ('femur.R', 'leg_femur.R', 'RightUpLeg'),
)


def _skin_columns(body, cell=0.02, min_depth=0.03):
    """(x, z) cell -> (front y, back y) of the body skin in that column.

    Columns thinner than ``min_depth`` (grazing cells at the silhouette edge,
    where front and back of the skin nearly meet) carry no usable depth
    information and are dropped.
    """
    mw = body.matrix_world
    cols = {}
    for v in body.data.vertices:
        co = mw @ v.co
        key = (int(math.floor(co.x / cell)), int(math.floor(co.z / cell)))
        band = cols.get(key)
        if band is None:
            cols[key] = [co.y, co.y, 1]
        else:
            band[0] = min(band[0], co.y)
            band[1] = max(band[1], co.y)
            band[2] += 1
    return {k: (v[0], v[1]) for k, v in cols.items() if v[2] >= 4 and v[1] - v[0] >= min_depth}


def _trunk_depth_offset(pieces, mapping, trunk, body, cell=0.02, stride=7):
    """How far back the trunk block must slide to sit inside the torso.

    Anchoring the skeleton's atlas on the rig Head bone head alone leaves the
    block too far forward (the skull breaks the face, the xiphoid the belly);
    the brief's other three landmarks pull it much too far back (the spine and
    the scapulae then break the back).  Neither landmark set measures what is
    actually wrong, so the depth is fitted against the skin itself: the body is
    reduced to front/back y per 2 cm (x, z) column and the slide that minimises
    the summed SQUARE of the per-probe protrusion is chosen, nearest zero on a
    tie.  Least squares rather than the worst case: a single unsatisfiable
    column (the female pelvis is narrower than the sacrum through one cell)
    otherwise dominates the max and drags the whole block to the scan limit.
    The residual reported as ``trunk_skin_overflow_mm`` is still the worst
    protrusion at the chosen slide.
    """
    cols = _skin_columns(body, cell)
    probes = []
    for short, bone in mapping.items():
        if bone not in TRUNK_BONES:
            continue
        mw = trunk @ pieces[short].matrix_world
        verts = pieces[short].data.vertices
        for i in range(0, len(verts), stride):
            co = mw @ verts[i].co
            band = cols.get((int(math.floor(co.x / cell)), int(math.floor(co.z / cell))))
            if band is not None:
                probes.append((co.y, band[0], band[1]))

    best = None
    step = 0.001
    for n in range(-80, 81):
        dy = n * step
        cost = 0.0
        worst = 0.0
        for y, front, back in probes:
            over = max(front - (y + dy), (y + dy) - back)
            if over > 0.0:
                cost += over * over
                if over > worst:
                    worst = over
        score = (round(cost, 6), abs(dy))
        if best is None or score < best[0]:
            best = (score, dy, worst)
    return best[1], best[2]


# Groups whose rig bone is a stub that does not span the skin it owns, so the
# brief's ``a_r = tail - head`` is meaningless there: cmu_mb's Hand bone is
# 33 mm of palm carrying a whole hand of skin (the finger bones are folded into
# the group), and its ToeBase is an 18 mm nub carrying the toes.  Measured
# straight, K comes out at 0.38 for both, the 0.8 clamp catches it, and the
# hands and toes render a clear 25 mm outside the skin.  For these two the axis
# is taken from the skin the group owns instead of from the bone.
STUB_GROUPS = ('Hand', 'ToeBase')

# Foot before ToeBase: the toes borrow the foot's spin about its own axis.
LIMB_ORDER = ('Arm', 'ForeArm', 'Hand', 'UpLeg', 'Leg', 'Foot', 'ToeBase')

# The hip is the one joint whose position the skeleton states outright -- the
# femoral head IS the acetabulum -- so the trunk placement gives a second,
# anatomical opinion on where it is.  Past SOCKET_TOL that opinion wins, see
# compute_placement.  The shoulder is not in the list: the glenoid rides on the
# scapula, which the trunk block only places to within a couple of centimetres,
# and anchoring the humerus there measured worse on both rigs.
SOCKET_GROUPS = ('UpLeg',)
SOCKET_TOL = 0.03  # the brief's own "expected within 3 cm"


def _centroid(points):
    acc = Vector((0.0, 0.0, 0.0))
    for p in points:
        acc += p
    return acc / len(points)


def _far_axis(points, origin, band=0.9):
    """origin -> centroid of the points lying past ``band`` of the reach.

    Selected by distance, never by rank: the skeleton hand's meshes are far
    denser at the metacarpals than at the phalanges, so a "farthest 5 % of the
    vertices" rule reaches back into the middle phalanges and reports a hand a
    quarter short.
    """
    far = [((p - origin).length, p) for p in points]
    cut = max(d for d, _ in far) * band
    take = [p for d, p in far if d >= cut]
    return _centroid(take) - origin


def _slab_frame(points, origin, toward):
    """(long axis, width axis) of a point cloud, by principal components.

    A hand is a flat slab: its longest spread runs down the fingers, its next
    across the knuckles, its shortest through the palm.  The skeleton hand and
    the flesh hand are the same slab, so their principal axes correspond, which
    fixes the spin that a single long-axis landmark cannot.  The long axis is
    signed away from ``origin``; the width axis by ``toward`` (the thumb).
    Returned as (axis * reach, width unit vector).
    """
    import numpy as np

    P = np.array([[p.x, p.y, p.z] for p in points], dtype=float)
    c = P.mean(axis=0)
    _, vecs = np.linalg.eigh(np.cov((P - c).T))
    long_ax = Vector(vecs[:, 2]).normalized()
    wide_ax = Vector(vecs[:, 1]).normalized()
    if long_ax.dot(Vector(c) - origin) < 0.0:
        long_ax = -long_ax
    perp = toward - long_ax * toward.dot(long_ax)
    if wide_ax.dot(perp) < 0.0:
        wide_ax = -wide_ax
    reach = max((p - origin).dot(long_ax) for p in points)
    return long_ax * reach, wide_ax


def _group_verts(pieces, mapping, bone, stride=3):
    out = []
    for short, b in mapping.items():
        if b != bone:
            continue
        mw = pieces[short].matrix_world
        verts = pieces[short].data.vertices
        out.extend(mw @ verts[i].co for i in range(0, len(verts), stride))
    return out


def compute_placement(arm, origins, s, mid_x, pieces, mapping, body):
    """-> (bone name -> (4x4 matrix, info dict), piece name -> extra 4x4)."""
    out = {}
    fix = {}

    head_head, _ = _bone_world(arm, 'Head')
    skull = origins['skull']
    t = head_head - skull * s
    t.x = -s * mid_x
    trunk = _affine(Matrix.Identity(3) * s, t)

    dy, residual = _trunk_depth_offset(pieces, mapping, trunk, body)
    trunk = Matrix.Translation(Vector((0.0, dy, 0.0))) @ trunk

    for bone in TRUNK_BONES:
        out[bone] = (
            trunk,
            {
                'kind': 'trunk',
                'axis_scale': s,
                'axis_scale_raw': s,
                'trunk_dy_m': round(dy, 4),
                'trunk_skin_overflow_mm': round(residual * 1000.0, 1),
            },
        )

    skin = _body_points(body)
    for side, S in (('L', 'Left'), ('R', 'Right')):
        frames = _limb_frames(origins, side)
        sfx = '.' + side
        foot_rot = Matrix.Identity(3)  # replaced when 'Foot' is placed, which LIMB_ORDER does first
        for bone in LIMB_ORDER:
            j_s, a_s = frames[bone]
            rig_name = S + bone
            head_r, tail_r = _bone_world(arm, rig_name)
            anchor = 'rig_head'
            offset = 0.0
            if bone in SOCKET_GROUPS:
                # Where the trunk block puts this joint: the femoral head IS
                # the acetabulum, the humeral head the glenoid.  The rigs do
                # not always agree -- female_realistic's LeftUpLeg head sits
                # 16.0 cm off the midline, against an 18.2 cm hip half-width,
                # so a femur hung on it floats clear outside the skin.  Past
                # SOCKET_TOL the anatomy wins and the offset is reported.
                anat = trunk @ j_s
                offset = (anat - head_r).length
                if offset > SOCKET_TOL:
                    head_r = anat
                    anchor = 'trunk_socket'
            a_r = tail_r - head_r
            roll = None
            if bone == 'Hand':
                # Axis AND spin from the shape of the two hands, not from the
                # bone: the cmu_mb Hand is a 33 mm stub, and the thumb -- the
                # only landmark both sides carry -- lies so nearly along the
                # hand that once its axial part is removed the remainder is
                # noise, which rolls the metacarpal fan out through the dorsum.
                # The thumb is still good enough to pick the width axis' SIGN.
                thumb = _raw_group_points(body, side + 'Thumb')
                t_s = origins['proximal.thumb' + sfx] - j_s
                t_r = (_centroid(thumb) - head_r) if thumb else (tail_r - head_r)
                a_s, w_s = _slab_frame(_group_verts(pieces, mapping, rig_name), j_s, t_s)
                a_r, w_r = _slab_frame(skin[rig_name], head_r, t_r)
                roll = (w_s, w_r)
            elif bone == 'ToeBase':
                # ToeBase is an 18 mm nub too, so the axis comes from the skin;
                # there is no toe landmark though, so the toes keep the foot's
                # spin, which is what they do in the rest pose anyway.
                a_s = _far_axis(_group_verts(pieces, mapping, rig_name), j_s)
                a_r = _far_axis(skin[rig_name], head_r)
                lat = origins['proximal.5' + sfx] - origins['proximal.1' + sfx]
                roll = (lat, foot_rot @ lat)
            mat, raw, used = _segment_matrix(j_s, a_s, head_r, a_r, s, roll)
            if bone == 'Foot':
                foot_rot = _rotation_between(a_s, a_r)
            info = {
                'kind': 'limb',
                'axis_scale': round(used, 4),
                'axis_scale_raw': round(raw, 4),
                'clamped': abs(raw - used) > 1e-6,
                'residual_m': round((mat @ j_s - head_r).length, 6),
                'anchor': anchor,
                'rig_head_offset_m': round(offset, 4),
            }
            if bone == 'Hand' and thumb:
                # One rigid transform cannot hold a hand whose thumb is posed
                # differently from the skeleton's: aligned as a slab the four
                # fingers sit right and the thumb ray stands 21 mm out of the
                # web.  The three thumb pieces therefore hinge once more about
                # their own CMC joint, onto the thumb flesh.  They still skin
                # rigidly to the Hand group -- only where they sit changes.
                cmc = mat @ origins['metacarpal.thumb' + sfx]
                tip = mat @ origins['distal.thumb' + sfx]
                t_mat, t_raw, t_used = _segment_matrix(cmc, tip - cmc, cmc, _far_axis(thumb, cmc), 1.0, None)
                for short in ('metacarpal.thumb', 'proximal.thumb', 'distal.thumb'):
                    fix[short + sfx] = t_mat
                info['thumb_fix_axis_scale'] = round(t_used, 4)
                info['thumb_fix_axis_scale_raw'] = round(t_raw, 4)
            out[rig_name] = (mat, info)
    return out, fix
