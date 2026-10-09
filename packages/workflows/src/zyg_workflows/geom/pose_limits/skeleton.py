# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""THE UNIFIED SKELETON — one record, three sources.

Moved verbatim out of the old single-file pose_limits.py (lines 1143-1375).
"""

from zyg_workflows.geom.pose_limits.base import np
from zyg_workflows.geom.pose_limits.rig import _model_index, bone_index, rig_state


# ---------------------------------------------------------------------------------
# THE UNIFIED SKELETON. One record, three sources, and an explicit statement of what the
# data it carries can and cannot answer.
# ---------------------------------------------------------------------------------
METRIC3D, PSEUDO3D, IMAGE2D = 'metric3d', 'pseudo3d', 'image2d'

FRAME_NOTES = {
    METRIC3D: 'metric 3D joint centres in one isotropic frame; angles are angles',
    PSEUDO3D: (
        'BlazePose x,y in pixels with its own per-landmark z in roughly image-width '
        'units, hip-relative. The three axes are NOT the same scale, so every angle '
        'is biased by an unknown anisotropy. Measured and reported, never gated'
    ),
    IMAGE2D: (
        'x,y only. A 3D angle is not recoverable from its projection and the '
        'projection does not even bound it — two directions 10 deg apart in space '
        'project to 180 deg when the view direction passes between them. Every '
        'angular gate returns UNMEASURABLE'
    ),
}

# The joint vocabulary both sources map onto. A name absent from a skeleton is absent, not
# zero: every consumer checks membership and reports what it could not find.
POSE_JOINTS = (
    'shoulder_l',
    'shoulder_r',
    'elbow_l',
    'elbow_r',
    'wrist_l',
    'wrist_r',
    'index_mcp_l',
    'index_mcp_r',
    'pinky_mcp_l',
    'pinky_mcp_r',
    'thumb_tip_l',
    'thumb_tip_r',
    'mcp3_l',
    'mcp3_r',
    'hip_l',
    'hip_r',
    'knee_l',
    'knee_r',
    'ankle_l',
    'ankle_r',
    'thorax',
    'neck_base',
    'head_base',
    'head_top',
    'eye_l',
    'eye_r',
)

_RIG_JOINT_MAP = {
    'shoulder_%s': ('head', 'upperarm01.%s'),
    'elbow_%s': ('head', 'lowerarm01.%s'),
    'wrist_%s': ('head', 'wrist.%s'),
    'index_mcp_%s': ('head', 'finger2-1.%s'),
    'pinky_mcp_%s': ('head', 'finger5-1.%s'),
    'thumb_tip_%s': ('tail', 'finger1-3.%s'),
    'mcp3_%s': ('head', 'finger3-1.%s'),
    'hip_%s': ('head', 'upperleg01.%s'),
    'knee_%s': ('head', 'lowerleg01.%s'),
    'ankle_%s': ('head', 'foot.%s'),
}
_RIG_MIDLINE_MAP = {
    'thorax': ('head', 'spine01'),
    'neck_base': ('head', 'neck01'),
    'head_base': ('head', 'head'),
    'head_top': ('tail', 'head'),
    'eye_l': ('head', 'eye.L'),
    'eye_r': ('head', 'eye.R'),
}


class Skeleton(object):
    """Named joint positions plus, where the source has them, bone orientations.

    `frame` is the honesty field. Everything downstream branches on it and refuses rather
    than guesses; see FRAME_NOTES.
    """

    __slots__ = ('source', 'frame', 'joints', 'state', 'constructed', 'note')

    def __init__(self, source, frame, joints, state=None, constructed=(), note=''):
        if frame not in FRAME_NOTES:
            raise ValueError('unknown frame %r; valid: %s' % (frame, ', '.join(sorted(FRAME_NOTES))))
        self.source = source
        self.frame = frame
        self.joints = {k: np.asarray(v, np.float64) for k, v in joints.items() if v is not None}
        self.state = state  # the full rig record, when there is one
        self.constructed = tuple(constructed)  # joints that are a construction, not a datum
        self.note = note

    def has(self, *names):
        return all(n in self.joints for n in names)

    def missing(self, *names):
        return [n for n in names if n not in self.joints]

    def p(self, name):
        return self.joints[name]

    def __repr__(self):
        return '<Skeleton %s frame=%s joints=%d rig=%s>' % (
            self.source,
            self.frame,
            len(self.joints),
            self.state is not None,
        )


def _rig_joints(state):
    j = {}
    for tmpl, (end, bone_tmpl) in _RIG_JOINT_MAP.items():
        for s, S in (('l', 'L'), ('r', 'R')):
            bone = bone_tmpl % S
            if bone in _model_index():
                arr = state['heads'] if end == 'head' else state['tails']
                j[tmpl % s] = arr[bone_index(bone)]
    for name, (end, bone) in _RIG_MIDLINE_MAP.items():
        if bone in _model_index():
            arr = state['heads'] if end == 'head' else state['tails']
            j[name] = arr[bone_index(bone)]
    return j


def skeleton_from_rig(phenotype, local_changes=None, pose_aa=None, source='rig'):
    st = rig_state(phenotype, local_changes, pose_aa)
    return Skeleton(source, METRIC3D, _rig_joints(st), state=st)


def skeleton_from_pose_aa(phenotype, pose_aa, local_changes=None, source='pose_aa'):
    """A recorded 163x3 axis-angle pose — the format geom/anny_fit.py writes."""
    return skeleton_from_rig(phenotype, local_changes, pose_aa, source=source)


# BlazePose landmark names, imported by NAME from geom.keypoints so the two cannot drift.
def _blaze_names():
    try:
        from zyg_workflows.geom import keypoints as KP

        return list(KP.POSE_NAMES)
    except Exception:  # pragma: no cover
        return None


_BLAZE_MAP = {
    'shoulder_%s': '%s_shoulder',
    'elbow_%s': '%s_elbow',
    'wrist_%s': '%s_wrist',
    'index_mcp_%s': '%s_index',
    'pinky_mcp_%s': '%s_pinky',
    'thumb_tip_%s': '%s_thumb',
    'hip_%s': '%s_hip',
    'knee_%s': '%s_knee',
    'ankle_%s': '%s_ankle',
    'eye_%s': '%s_eye',
}


def skeleton_from_blazepose(pts, z=None, visibility=None, min_visibility=0.5, source='blazepose'):
    """The 33-point detection geom.keypoints returns, as a Skeleton.

    pts is (33,2) or (33,3) in ORIGINAL-IMAGE pixels; the third column geom.keypoints
    packs is VISIBILITY, not depth, so depth must be handed in separately as `z`
    (det.body.extra['z']), exactly as that module stores it. Passing no z produces an
    IMAGE2D skeleton, which is the honest description of a raw ControlNet pose.

    Landmarks below `min_visibility` are DROPPED rather than used, because BlazePose emits
    a plausible coordinate for a joint it cannot see and a ROM gate fed that would be
    measuring the detector's prior.
    """
    names = _blaze_names()
    if names is None:
        raise RuntimeError(
            'geom.keypoints could not be imported, so the BlazePose '
            'landmark ORDER cannot be verified. Refusing to guess it: a '
            'silently permuted skeleton would produce confident, wrong '
            'angles.'
        )
    P = {n: i for i, n in enumerate(names)}
    pts = np.asarray(pts, np.float64)
    if pts.shape[0] != len(names):
        raise ValueError('expected %d BlazePose landmarks, got %d' % (len(names), pts.shape[0]))
    vis = (
        np.asarray(visibility, np.float64)
        if visibility is not None
        else (pts[:, 2] if pts.shape[1] >= 3 else np.ones(len(pts)))
    )
    frame = PSEUDO3D if z is not None else IMAGE2D
    zz = np.asarray(z, np.float64) if z is not None else np.zeros(len(pts))

    def get(nm):
        i = P[nm]
        if vis[i] < min_visibility:
            return None
        return np.array([pts[i, 0], pts[i, 1], zz[i]])

    j, constructed = {}, []
    for tmpl, blaze in _BLAZE_MAP.items():
        for s in ('l', 'r'):
            v = get(blaze % ('left' if s == 'l' else 'right'))
            if v is not None:
                j[tmpl % s] = v
    for s in ('l', 'r'):
        a, b = j.get('index_mcp_%s' % s), j.get('pinky_mcp_%s' % s)
        if a is not None and b is not None:
            j['mcp3_%s' % s] = 0.5 * (a + b)
            constructed.append('mcp3_%s' % s)
    if 'shoulder_l' in j and 'shoulder_r' in j:
        j['neck_base'] = 0.5 * (j['shoulder_l'] + j['shoulder_r'])
        constructed.append('neck_base')
    if 'hip_l' in j and 'hip_r' in j:
        j['thorax'] = 0.5 * (j['hip_l'] + j['hip_r'])
        constructed.append('thorax')
    el, er = get('left_ear'), get('right_ear')
    if el is not None and er is not None:
        j['head_base'] = 0.5 * (el + er)
        constructed.append('head_base')
    return Skeleton(
        source,
        frame,
        j,
        constructed=constructed,
        note=(
            'mcp3 is the midpoint of the index and pinky MCPs, not a '
            'detected third metacarpal; thorax is the hip midpoint, not '
            'spine01; there is no head_top landmark in BlazePose so head '
            'PITCH about the skull axis is not recoverable from this source'
        ),
    )
