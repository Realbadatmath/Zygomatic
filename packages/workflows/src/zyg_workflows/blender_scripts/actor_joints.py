# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""actor_joints.py — one resolver that turns any rigged actor into 33 joints.

CONTRACT (this is the seam between the actor builders and the pose exporter).

    joints33(armature, mapping=None) -> list[tuple[float, float, float, bool]]

    * ``armature``  a Blender ARMATURE **object** (not the armature data).  It is
      read in its current pose, so set ``scene.frame_set(f)`` first; the caller
      owns the frame.
    * ``mapping``   ``'cmu_mb'`` | ``'creature'`` | a joint_map dict | ``None``.
      ``None`` means "ask the object": the actor builders stamp the armature with
      a custom property ``mapping`` (and, for ``'creature'``, a custom property
      ``joint_map`` holding the map as a JSON string).
    * returns exactly **33** entries, in ``POSE_NAMES`` order (the BlazePose /
      MediaPipe Pose landmark order, identical to ``geom/keypoints.POSE_NAMES``).
      Each entry is ``(x, y, z, present)`` with x/y/z in **world** space (metres,
      Blender axes: +Z up, the actor faces -Y) and ``present`` a bool.
      A joint the rig does not have is ``(0.0, 0.0, 0.0, False)`` — the exporter
      writes visibility 0 for those.  Wan-Animate drives non-humanoids precisely
      because it takes a 2D skeleton, so a creature only needs the subset its
      bones can honestly fill.

JOINT MAP FORMAT.  ``joint_map`` maps a MediaPipe landmark name to a bone
reference.  Three equivalent spellings:

    "bone_7"                                  -> head of bone_7
    "bone_7:tail"                             -> tail of bone_7
    {"bone": "Head", "at": "tail",
     "offset": [0.04, 0.0, 0.0]}              -> tail of Head, plus 0.04 m along
                                                 the **bone-local X** axis of the
                                                 posed bone

``at`` is ``'head'`` (default) or ``'tail'``.  ``offset`` is optional and is
expressed in the posed bone's own space (local X / Y / Z, Y being along the
bone), so it follows the bone when the rig moves.  Names not in the map are
absent.  Names in the map whose bone is missing from the rig are absent too —
the resolver never raises on a stale map.

TABLES IN THIS MODULE.
    POSE_NAMES          the 33 landmark names, in order.
    CMU_MB_JOINT_MAP    the map for the MPFB ``cmu_mb`` human rig (the skeleton
                        the CMU mocap BVH clips in ``motion_library.py`` use).
                        All 33 landmarks are filled; the face landmarks are
                        bone-local offsets off ``Head`` because that rig has no
                        eye or mouth bones.
    CREATURE_REQUIRED   the minimum a ``mapping='creature'`` actor must fill.

This module imports ``bpy``/``mathutils`` **inside** the functions only, so the
tables can be read (and unit-tested) by a plain CPython interpreter.
"""

from __future__ import annotations

import json
import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)


# BlazePose 33-landmark order — kept byte-identical to geom/keypoints.POSE_NAMES.
POSE_NAMES = [
    'nose',
    'left_eye_inner',
    'left_eye',
    'left_eye_outer',
    'right_eye_inner',
    'right_eye',
    'right_eye_outer',
    'left_ear',
    'right_ear',
    'mouth_left',
    'mouth_right',
    'left_shoulder',
    'right_shoulder',
    'left_elbow',
    'right_elbow',
    'left_wrist',
    'right_wrist',
    'left_pinky',
    'right_pinky',
    'left_index',
    'right_index',
    'left_thumb',
    'right_thumb',
    'left_hip',
    'right_hip',
    'left_knee',
    'right_knee',
    'left_ankle',
    'right_ankle',
    'left_heel',
    'right_heel',
    'left_foot_index',
    'right_foot_index',
]

POSE_INDEX = {n: i for i, n in enumerate(POSE_NAMES)}

# The MPFB cmu_mb human rig.  Bone names are the CMU MotionBuilder-friendly BVH
# joint names (motion_library.CMU_MB_JOINTS).  Face landmarks are offsets off the
# Head bone in bone-local space: +X is the character's left, +Y runs along the
# bone (up, towards the tail), +Z is forward.
CMU_MB_JOINT_MAP = {
    'nose': {'bone': 'Head', 'at': 'tail', 'offset': [0.0, -0.01, 0.09]},
    'left_eye_inner': {'bone': 'Head', 'at': 'tail', 'offset': [0.018, 0.005, 0.075]},
    'left_eye': {'bone': 'Head', 'at': 'tail', 'offset': [0.032, 0.005, 0.072]},
    'left_eye_outer': {'bone': 'Head', 'at': 'tail', 'offset': [0.046, 0.005, 0.066]},
    'right_eye_inner': {'bone': 'Head', 'at': 'tail', 'offset': [-0.018, 0.005, 0.075]},
    'right_eye': {'bone': 'Head', 'at': 'tail', 'offset': [-0.032, 0.005, 0.072]},
    'right_eye_outer': {'bone': 'Head', 'at': 'tail', 'offset': [-0.046, 0.005, 0.066]},
    'left_ear': {'bone': 'Head', 'at': 'tail', 'offset': [0.075, 0.0, 0.01]},
    'right_ear': {'bone': 'Head', 'at': 'tail', 'offset': [-0.075, 0.0, 0.01]},
    'mouth_left': {'bone': 'Head', 'at': 'tail', 'offset': [0.025, -0.04, 0.07]},
    'mouth_right': {'bone': 'Head', 'at': 'tail', 'offset': [-0.025, -0.04, 0.07]},
    'left_shoulder': 'LeftArm',
    'right_shoulder': 'RightArm',
    'left_elbow': 'LeftForeArm',
    'right_elbow': 'RightForeArm',
    'left_wrist': 'LeftHand',
    'right_wrist': 'RightHand',
    'left_pinky': 'LeftFingerBase:tail',
    'right_pinky': 'RightFingerBase:tail',
    'left_index': 'LeftHandIndex1:tail',
    'right_index': 'RightHandIndex1:tail',
    'left_thumb': 'LThumb:tail',
    'right_thumb': 'RThumb:tail',
    'left_hip': 'LeftUpLeg',
    'right_hip': 'RightUpLeg',
    'left_knee': 'LeftLeg',
    'right_knee': 'RightLeg',
    'left_ankle': 'LeftFoot',
    'right_ankle': 'RightFoot',
    'left_heel': {'bone': 'LeftFoot', 'at': 'head', 'offset': [0.0, 0.0, -0.03]},
    'right_heel': {'bone': 'RightFoot', 'at': 'head', 'offset': [0.0, 0.0, -0.03]},
    'left_foot_index': 'LeftToeBase:tail',
    'right_foot_index': 'RightToeBase:tail',
}

# A creature rig cannot fill the face fan or the fingers, but a 2D skeleton is
# only useful if the torso box and both limb pairs are there.
CREATURE_REQUIRED = (
    'nose',
    'left_shoulder',
    'right_shoulder',
    'left_hip',
    'right_hip',
    'left_knee',
    'right_knee',
    'left_ankle',
    'right_ankle',
)

BUILTIN_MAPPINGS = {'cmu_mb': CMU_MB_JOINT_MAP}

_ZERO = (0.0, 0.0, 0.0, False)


def normalise_entry(entry):
    """Expand any of the three joint_map spellings to ``(bone, at, offset)``.

    Returns ``None`` for an unusable entry rather than raising, so a stale map
    degrades to "joint absent" instead of killing an export.
    """
    if entry is None:
        return None
    if isinstance(entry, str):
        name, _, at = entry.partition(':')
        name = name.strip()
        at = (at or 'head').strip().lower()
        if not name:
            return None
        return (name, 'tail' if at == 'tail' else 'head', None)
    if isinstance(entry, dict):
        name = str(entry.get('bone') or '').strip()
        if not name:
            return None
        at = str(entry.get('at') or 'head').strip().lower()
        off = entry.get('offset')
        if off is not None:
            try:
                off = tuple(float(v) for v in off)
                if len(off) != 3:
                    off = None
            except (TypeError, ValueError):
                off = None
        return (name, 'tail' if at == 'tail' else 'head', off)
    return None


def joints_from_map(armature, joint_map):
    """Resolve a joint_map against a posed armature object.

    Generic: it knows nothing about humans or creatures, only about bones.
    Returns 33 ``(x, y, z, present)`` tuples in ``POSE_NAMES`` order, world space.
    """
    from mathutils import Vector

    joint_map = joint_map or {}
    mw = armature.matrix_world
    pbs = armature.pose.bones

    out = []
    for name in POSE_NAMES:
        spec = normalise_entry(joint_map.get(name))
        if spec is None:
            out.append(_ZERO)
            continue
        bone_name, at, off = spec
        pb = pbs.get(bone_name)
        if pb is None:
            out.append(_ZERO)
            continue
        p = Vector(pb.tail if at == 'tail' else pb.head)
        if off is not None:
            p = p + (pb.matrix.to_3x3() @ Vector(off))
        w = mw @ p
        out.append((float(w.x), float(w.y), float(w.z), True))
    return out


def mapping_for(armature, mapping=None):
    """Resolve ``mapping`` to an actual joint_map dict.

    ``None`` reads the armature's own ``mapping`` custom property.  ``'creature'``
    reads the per-actor map from the armature's ``joint_map`` custom property
    (JSON string or a dict-like ID property).
    """
    if isinstance(mapping, dict):
        return dict(mapping)
    if mapping is None:
        mapping = armature.get('mapping') if armature is not None else None
    key = str(mapping or '').strip().lower()
    if not key:
        raise ValueError('actor_joints: no mapping given and the armature carries no "mapping" custom property')
    if key in BUILTIN_MAPPINGS:
        return dict(BUILTIN_MAPPINGS[key])
    if key == 'creature':
        raw = armature.get('joint_map') if armature is not None else None
        if raw is None:
            raise ValueError("actor_joints: mapping='creature' needs a 'joint_map' custom property on the armature")
        if isinstance(raw, str):
            raw = json.loads(raw)
        return {str(k): _plain(v) for k, v in dict(raw).items()}
    raise ValueError('actor_joints: unknown mapping %r' % (mapping,))


def _plain(v):
    """Blender ID-property values come back as IDPropertyGroup / IDPropertyArray."""
    if isinstance(v, str):
        return v
    try:
        return {str(k): _plain(x) for k, x in dict(v).items()}
    except (TypeError, ValueError) as _exc:
        _zyg_log.debug('value not a mapping, trying the sequence form: %s', _exc)
    try:
        return [float(x) for x in v]
    except (TypeError, ValueError):
        return v


def joints33(armature, mapping=None):
    """The one function the exporter imports.  See the module docstring."""
    return joints_from_map(armature, mapping_for(armature, mapping))


def mapped_names(joint_map):
    """The MediaPipe names a joint_map actually fills (order of POSE_NAMES)."""
    return [n for n in POSE_NAMES if normalise_entry((joint_map or {}).get(n))]
