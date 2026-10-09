# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""motion_authored.py — keyframed actions for the verbs mocap does not cover.

The CMU library gives us walk / run / fight / dance / sit.  Three verbs of the
shot vocabulary have no clean clip in it — fly, drive (seated at a wheel) and
scream — so they are AUTHORED here as keyframe actions on the very same
``cmu_mb`` rig, and are selectable exactly like a BVH clip:

    blender -b --python blender_scripts/proxy_actor.py -- \\
        --name abel_fly --motion auth/fly

Pose convention (identical to proxy_actor's retarget, so the two sources are
interchangeable): every bone is given a WORLD-space delta quaternion applied on
top of its rest orientation, and the chain is baked by walking the hierarchy in
order.  A delta on a parent therefore does NOT propagate to its children — each
bone's absolute orientation is stated, the way a BVH frame states it.

Axes are derived from the rig, not assumed (``body_axes``): ``left`` is the
hip-to-hip direction, ``up`` is +Z, ``fwd = left x up`` is the way the character
faces at rest.  For an MPFB human that is ``left=+X, fwd=-Y``, so a *forward*
pitch is a positive rotation about world X — which is what the --check numbers
report.  Bones whose rest direction points DOWN (the thighs) swing forward on a
NEGATIVE X rotation; the check reports the unsigned delta angle for those.

Root height: a flying or seated actor is not standing on the path the shot
gives it.  The action stays grounded and the lift is carried by the custom
property ``root_offset_z`` on the armature — metres the scene builder must
raise ``actor_root`` above the path point.  See ``root_offset_z()``.
"""

from __future__ import annotations

import math

try:  # inside Blender
    import bpy
    from mathutils import Matrix, Quaternion, Vector
except ImportError:  # plain python: metadata only
    bpy = None
    Matrix = Quaternion = Vector = None

ACTION_NAME = 'motion'
ROOT_BONE = 'Hips'

# ----------------------------------------------------------------- the rig
TORSO = ('Hips', 'LHipJoint', 'RHipJoint', 'LowerBack', 'Spine', 'Spine1', 'LeftShoulder', 'RightShoulder')
NECK = ('Neck', 'Neck1')
HEAD = ('Head',)
ARMS = ('LeftArm', 'RightArm')
FOREARMS = ('LeftForeArm', 'RightForeArm')
HANDS = ('LeftHand', 'RightHand')
# The MPFB cmu_mb rig spells the index fingers LeftHandFinger1 / RightHandFinger1
# where the BVH says LeftHandIndex1 (proxy_actor.BONE_ALIAS); both are listed and
# whichever the rig actually carries is used — see _on_rig.
LEFT_FINGERS = ('LeftFingerBase', 'LeftHandFinger1', 'LeftHandIndex1', 'LThumb')
RIGHT_FINGERS = ('RightFingerBase', 'RightHandFinger1', 'RightHandIndex1', 'RThumb')
FINGERS = LEFT_FINGERS + RIGHT_FINGERS
THIGHS = ('LeftUpLeg', 'RightUpLeg')
SHINS = ('LeftLeg', 'RightLeg')
FEET = ('LeftFoot', 'RightFoot', 'LeftToeBase', 'RightToeBase')

# ------------------------------------------------------------------ motions
FLY_PITCH_DEG = 80.0  # body pitched forward about X at the Hips
FLY_RISE_FRAMES = 12  # frames from idle to the full flight pose
FLY_SPEED_MS = 2.0  # root travel along the heading, metres per second
FLY_BOB_M = 0.15  # vertical bob amplitude
FLY_BOB_HZ = 0.5
FLY_ROLL_DEG = 6.0  # slow roll oscillation about the flight axis
FLY_ROLL_PERIOD_S = 4.0

DRIVE_THIGH_DEG = 85.0  # UpLegs forward from the rest (down) direction
DRIVE_KNEE_DEG = 80.0  # Legs back from the thigh
DRIVE_WHEEL_FWD_M = 0.35  # wheel centre in front of the chest
DRIVE_WHEEL_R_M = 0.18  # where the hands sit on the rim
DRIVE_HAND_TURN_DEG = 12.0  # hands turning about the wheel axis
DRIVE_TURN_FRAMES = 24  # ... sign flips every 24 frames
DRIVE_GRIP_DEG = 70.0  # fingers closed round the rim
DRIVE_HEAD_YAW_DEG = 3.0
DRIVE_SEAT_Z_M = 0.45  # seat height above the car's floor
# Where in the car's own frame (X front, Y width, Z up — vehicles_props.build_car)
# the driver sits, so task 17 can put the actor behind the wheel.
DRIVE_SEAT_OFFSET = {'x': 0.35, 'z': 0.2, 'units': 'm', 'note': '0.35 m left of the vehicle centre, 0.2 m back'}

SCREAM_RISE_FRAMES = 12  # head/arms/torso reach the pose on frame 12
SCREAM_TREMOR_FRAMES = 36  # frames 13..48
SCREAM_HEAD_DEG = -25.0  # head pitches BACK (negative about X)
SCREAM_NECK_DEG = -17.5  # neck splits the difference with the torso
SCREAM_TORSO_DEG = -10.0
SCREAM_ARM_ELEV_DEG = 30.0  # arms above horizontal
SCREAM_FIST_DEG = 90.0
SCREAM_TREMOR_DEG = 1.5
SCREAM_TREMOR_HZ = 3.0

MOTIONS = {
    'auth/fly': {
        'id': 'auth/fly',
        'label': 'fly',
        'frames': 96,
        'fps': 24,
        'licence': 'in-house',
        'tags': ['fly'],
        'loop': False,
        'index_text': 'flight: body pitched 80 deg forward, arms along the '
        'flight axis, 2.0 m/s travel with a 0.15 m bob and a 6 deg roll',
        'root_offset': ('height', 1.2),
    },
    'auth/drive': {
        'id': 'auth/drive',
        'label': 'drive',
        'frames': 48,
        'fps': 24,
        'licence': 'in-house',
        'tags': ['drive', 'sit'],
        'loop': True,
        'index_text': 'seated at a wheel: thighs 85 deg forward, knees 80 deg, '
        'hands on a wheel 0.35 m ahead of the chest turning +-12 deg',
        'root_offset': ('abs', DRIVE_SEAT_Z_M),
        'seat_offset': DRIVE_SEAT_OFFSET,
        'vehicle_kind': 'car',
    },
    'auth/scream': {
        'id': 'auth/scream',
        'label': 'scream',
        'frames': 72,
        'fps': 24,
        'licence': 'in-house',
        'tags': ['scream'],
        'loop': False,
        'index_text': 'scream: head back 25 deg, arms 30 deg above horizontal '
        'with fists, torso back 10 deg, 3 Hz tremor, release',
        'root_offset': ('abs', 0.0),
    },
}

MOTION_IDS = tuple(MOTIONS)


def is_authored(motion_id):
    return motion_id in MOTIONS


def spec(motion_id):
    try:
        return MOTIONS[motion_id]
    except KeyError as _exc:
        raise KeyError('unknown authored motion %r; have %s' % (motion_id, ', '.join(MOTION_IDS))) from _exc


def library_records():
    """The records this module contributes to library.json's "authored" list."""
    out = []
    for key in MOTION_IDS:
        rec = spec(key)
        out.append(
            {
                'id': rec['id'],
                'label': rec['label'],
                'frames': rec['frames'],
                'fps': rec['fps'],
                'licence': rec['licence'],
                'tags': list(rec['tags']),
                'loop': rec['loop'],
                'source': 'motion_authored.py',
                'index_text': rec['index_text'],
            }
        )
    return out


def root_offset_z(motion_id, height_m):
    """Metres the scene builder must lift ``actor_root`` above the path point.

    Flight height is 1.2 x the actor's standing height; a driver sits at the
    seat height; a screaming actor stands on the path like any mocap clip.
    """
    kind, value = spec(motion_id)['root_offset']
    return round(value * float(height_m) if kind == 'height' else value, 4)


# ------------------------------------------------------------------- maths


def _ident():
    return Quaternion((1.0, 0.0, 0.0, 0.0))


def _about(axis, deg):
    return Quaternion(axis, math.radians(deg))


def _ease(q, k):
    """Blend a delta in from rest; k = 0 is the rest pose, 1 is the full pose."""
    return _ident().slerp(q, max(0.0, min(1.0, k)))


def body_axes(arm):
    """``(fwd, left, up)`` in armature space, read off the rig's own hips."""
    left = arm.data.bones['LeftUpLeg'].head_local - arm.data.bones['RightUpLeg'].head_local
    left.z = 0.0
    left.normalize()
    up = Vector((0.0, 0.0, 1.0))
    return left.cross(up).normalized(), left, up


def rest_dirs(arm):
    """Each bone's rest direction (its local +Y) in armature space."""
    return {b.name: (b.tail_local - b.head_local).normalized() for b in arm.data.bones}


def _on_rig(arm, names):
    """The subset of ``names`` this armature actually has (finger spellings vary)."""
    return [n for n in names if n in arm.data.bones]


def hierarchy_order(arm):
    order = []
    stack = [b for b in arm.data.bones if b.parent is None]
    while stack:
        bone = stack.pop(0)
        order.append(bone.name)
        stack.extend(bone.children)
    return order


def _point(rest_dir, target):
    """World delta that turns a bone's rest direction onto ``target``."""
    return rest_dir.rotation_difference(Vector(target).normalized())


def _fist(rest, hand_delta, finger_names, deg):
    """Deltas that fold the finger bones into the palm.

    The fingers inherit the hand's own delta and then flex; aiming them at a
    world direction of their own splays them instead, which is what a 'fist'
    must not look like.  Which way is 'into the palm' is read off the rig — a
    finger curls toward the thumb and the thumb toward the fingers — so the
    sign comes out right on the left and the right hand without a special case.
    """
    out = {}
    dirs = {n: (hand_delta @ rest[n]).normalized() for n in finger_names}
    thumb = next((n for n in finger_names if 'Thumb' in n), None)
    fingers = [n for n in finger_names if n != thumb]
    if thumb is None or not fingers:
        return {n: hand_delta for n in finger_names}
    for name in fingers:
        axis = dirs[name].cross(dirs[thumb])
        out[name] = _about(axis.normalized(), deg) @ hand_delta if axis.length > 1e-6 else hand_delta
    axis = dirs[thumb].cross(dirs[fingers[0]])
    out[thumb] = _about(axis.normalized(), deg * 0.6) @ hand_delta if axis.length > 1e-6 else hand_delta
    return out


def _two_bone_aim(root_pos, target, l1, l2, pole):
    """Directions for a 2-bone chain reaching from ``root_pos`` to ``target``.

    Analytic, not iterative: the elbow sits where the two circles of radius l1
    and l2 meet, on the side ``pole`` points to.  Returns ``(upper, lower)``
    unit directions; an out-of-reach target is aimed at straight.
    """
    to = target - root_pos
    dist = to.length
    if dist < 1e-6:
        return Vector(pole).normalized(), Vector(pole).normalized()
    chord = to.normalized()
    dist = min(dist, (l1 + l2) * 0.999)
    cos_a = (dist * dist + l1 * l1 - l2 * l2) / (2.0 * dist * l1)
    angle = math.acos(max(-1.0, min(1.0, cos_a)))
    axis = chord.cross(Vector(pole))
    if axis.length < 1e-6:
        axis = chord.cross(Vector((0.0, 0.0, 1.0)))
    upper = (Quaternion(axis.normalized(), angle) @ chord).normalized()
    return upper, (target - (root_pos + upper * l1)).normalized()


# ----------------------------------------------------------------- the poses
# Each generator returns one (deltas, root_translation) pair per frame.


def _fly(arm, fps, frames):
    fwd, left, up = body_axes(arm)
    rest = rest_dirs(arm)
    pitch = _about(left, FLY_PITCH_DEG)  # +X for an MPFB human
    trail = pitch @ (-up)  # legs stream out behind
    pose = {}
    for name in _on_rig(arm, TORSO + NECK + HEAD):
        pose[name] = pitch
    for name in _on_rig(arm, ARMS + FOREARMS + HANDS + FINGERS):
        pose[name] = _point(rest[name], fwd)  # reaching along the flight axis
    for name in _on_rig(arm, THIGHS + SHINS + FEET):
        pose[name] = _point(rest[name], trail)  # legs together, no A-pose splay

    out = []
    for index in range(frames):
        t = index / float(fps)
        k = min(1.0, index / float(FLY_RISE_FRAMES - 1))
        roll = _about(fwd, FLY_ROLL_DEG * math.sin(2.0 * math.pi * t / FLY_ROLL_PERIOD_S))
        deltas = {name: roll @ _ease(q, k) for name, q in pose.items()}
        root = fwd * (FLY_SPEED_MS * t) + up * (FLY_BOB_M * math.sin(2.0 * math.pi * FLY_BOB_HZ * t))
        out.append((deltas, root))
    return out


def _drive(arm, fps, frames):
    fwd, left, up = body_axes(arm)
    rest = rest_dirs(arm)
    bones = arm.data.bones
    # A thigh's rest direction is DOWN, so swinging it forward is a negative
    # rotation about X; the knee then folds back by DRIVE_KNEE_DEG.
    thigh = _about(left, -DRIVE_THIGH_DEG)
    shin = _about(left, -DRIVE_THIGH_DEG + DRIVE_KNEE_DEG)

    chest = bones['Spine1'].head_local.copy()
    wheel = chest + fwd * DRIVE_WHEEL_FWD_M
    pose = {}
    for name in _on_rig(arm, THIGHS):
        pose[name] = thigh
    for name in _on_rig(arm, SHINS):
        pose[name] = shin
    for name in _on_rig(arm, FEET):
        pose[name] = _point(rest[name], fwd)  # soles flat on the floor pan
    for side, arm_b, fore_b, hand_b, fingers in (
        (1.0, 'LeftArm', 'LeftForeArm', 'LeftHand', LEFT_FINGERS),
        (-1.0, 'RightArm', 'RightForeArm', 'RightHand', RIGHT_FINGERS),
    ):
        target = wheel + left * (DRIVE_WHEEL_R_M * side)
        upper, lower = _two_bone_aim(
            bones[arm_b].head_local.copy(), target, bones[arm_b].length, bones[fore_b].length, -up
        )
        pose[arm_b] = _point(rest[arm_b], upper)
        pose[fore_b] = _point(rest[fore_b], lower)
        pose[hand_b] = _point(rest[hand_b], lower)
        pose.update(_fist(rest, pose[hand_b], _on_rig(arm, fingers), DRIVE_GRIP_DEG))  # closed round the rim

    hand_names = set(HANDS) | set(FINGERS)
    head_names = _on_rig(arm, NECK + HEAD)
    out = []
    for index in range(frames):
        t = index / float(fps)
        turn = DRIVE_HAND_TURN_DEG * math.cos(2.0 * math.pi * t * fps / (2.0 * DRIVE_TURN_FRAMES))
        wheel_turn = _about(fwd, turn)
        yaw = _about(up, DRIVE_HEAD_YAW_DEG * math.sin(2.0 * math.pi * t * fps / (2.0 * DRIVE_TURN_FRAMES)))
        deltas = {name: (wheel_turn @ q if name in hand_names else q) for name, q in pose.items()}
        for name in head_names:
            deltas[name] = yaw
        out.append((deltas, None))
    return out


def _scream(arm, fps, frames):
    fwd, left, up = body_axes(arm)
    rest = rest_dirs(arm)
    elev = math.radians(SCREAM_ARM_ELEV_DEG)
    hold_end = SCREAM_RISE_FRAMES + SCREAM_TREMOR_FRAMES

    reach = {}
    for side, arm_b, fore_b, hand_b, fingers in (
        (1.0, 'LeftArm', 'LeftForeArm', 'LeftHand', LEFT_FINGERS),
        (-1.0, 'RightArm', 'RightForeArm', 'RightHand', RIGHT_FINGERS),
    ):
        raised = (left * (side * math.cos(elev)) + up * math.sin(elev)).normalized()
        for name in (arm_b, fore_b, hand_b):
            reach[name] = _point(rest[name], raised)
        reach.update(_fist(rest, reach[hand_b], _on_rig(arm, fingers), SCREAM_FIST_DEG))

    out = []
    for index in range(frames):
        if index < SCREAM_RISE_FRAMES:
            k, tremor = index / float(SCREAM_RISE_FRAMES - 1), 0.0
        elif index < hold_end:
            k = 1.0
            tremor = SCREAM_TREMOR_DEG * math.sin(
                2.0 * math.pi * SCREAM_TREMOR_HZ * (index - SCREAM_RISE_FRAMES) / float(fps)
            )
        else:
            k = max(0.0, 1.0 - (index - hold_end) / float(frames - hold_end - 1))
            tremor = 0.0
        deltas = {}
        for name in _on_rig(arm, TORSO):
            if name == 'Spine1':
                deltas[name] = _about(left, SCREAM_TORSO_DEG * k + tremor)
            else:
                deltas[name] = _ease(_about(left, SCREAM_TORSO_DEG), k)
        for name in _on_rig(arm, NECK):
            deltas[name] = _about(left, SCREAM_NECK_DEG * k + tremor)
        deltas['Head'] = _about(left, SCREAM_HEAD_DEG * k)
        for name, q in reach.items():
            deltas[name] = _ease(q, k)
        out.append((deltas, None))
    return out


GENERATORS = {'auth/fly': _fly, 'auth/drive': _drive, 'auth/scream': _scream}


# ------------------------------------------------------------------- baking


def bake(arm, per_frame, action_name=ACTION_NAME):
    """Bake world-space deltas onto the rig, one keyframe per bone per frame.

    Mirrors proxy_actor.retarget: the chain is walked in hierarchy order, each
    bone's world matrix is ``delta @ rest`` at its FK position, and the pose
    basis that produces it is keyed.
    """
    order = hierarchy_order(arm)
    rest_rel = {}
    for bone in arm.data.bones:
        rest_rel[bone.name] = (
            bone.parent.matrix_local.inverted() @ bone.matrix_local if bone.parent else bone.matrix_local.copy()
        )
    rest_q = {b.name: b.matrix_local.to_3x3().to_quaternion() for b in arm.data.bones}

    for pbone in arm.pose.bones:
        pbone.rotation_mode = 'QUATERNION'
    arm.animation_data_create()
    action = bpy.data.actions.new(action_name)
    arm.animation_data.action = action
    identity = Matrix.Identity(4)

    for index, (deltas, root) in enumerate(per_frame):
        frame = index + 1
        world = {}
        for name in order:
            bone = arm.data.bones[name]
            parent_world = world[bone.parent.name] if bone.parent else identity
            fk = parent_world @ rest_rel[name]
            delta = deltas.get(name)
            if delta is None:
                new_world = fk.copy()
            else:
                new_world = Matrix.Translation(fk.translation) @ (delta @ rest_q[name]).to_matrix().to_4x4()
            if name == ROOT_BONE and root is not None:
                new_world.translation = fk.translation + root
            pbone = arm.pose.bones[name]
            pbone.matrix_basis = rest_rel[name].inverted() @ parent_world.inverted() @ new_world
            pbone.keyframe_insert('location', frame=frame, group=name)
            pbone.keyframe_insert('rotation_quaternion', frame=frame, group=name)
            world[name] = new_world
    return action


def build_action(armature, motion_id, fps=24):
    """Build and assign the authored action ``motion_id`` on ``armature``.

    Returns the bpy Action (named ``motion``, like the retargeted one), with
    ``frames``/``fps``/``motion_id`` stamped on it as custom properties.
    """
    rec = spec(motion_id)
    frames = int(rec['frames'])
    fps = int(fps or rec['fps'])
    action = bake(armature, GENERATORS[motion_id](armature, fps, frames))
    action['motion_id'] = motion_id
    action['frames'] = frames
    action['fps'] = fps
    return action


# ------------------------------------------------------------------- checks


def twist_deg(delta, axis='X'):
    """Signed rotation of ``delta`` about a world axis (swing-twist)."""
    return round(math.degrees(delta.to_swing_twist(axis)[1]), 3)


def measure(arm, motion_id):
    """The --check numbers for an authored action, read off the posed rig.

    Every bone's delta is its posed armature-space orientation against its
    rest orientation, so the numbers are the ones the pose generator asked for.
    """
    scene = bpy.context.scene
    rec = spec(motion_id)
    fwd, left, _up = body_axes(arm)
    rest_q = {b.name: b.matrix_local.to_3x3().to_quaternion() for b in arm.data.bones}

    def delta(name, frame):
        scene.frame_set(frame)
        bpy.context.view_layer.update()
        return arm.pose.bones[name].matrix.to_3x3().to_quaternion() @ rest_q[name].inverted()

    out = {
        'motion': motion_id,
        'facing_armature_space': [round(v, 3) for v in fwd],
        'left_axis': [round(v, 3) for v in left],
        'root_offset_z_prop': arm.get('root_offset_z'),
    }

    if motion_id == 'auth/fly':
        d = delta('Hips', 48)
        out['hips_pitch_deg_frame48'] = twist_deg(d)
        out['hips_pitch_ok'] = bool(abs(abs(out['hips_pitch_deg_frame48']) - FLY_PITCH_DEG) < 1.0)
        out['root_offset_z_set'] = bool(arm.get('root_offset_z'))

        def hips_at(frame):
            scene.frame_set(frame)
            bpy.context.view_layer.update()
            return (arm.matrix_world @ arm.pose.bones[ROOT_BONE].head).copy()

        travel = hips_at(int(rec['frames'])) - hips_at(1)
        want = FLY_SPEED_MS * (rec['frames'] - 1) / float(rec['fps'])
        out['root_travel_m'] = round(travel.length, 3)
        out['root_travel_expected_m'] = round(want, 3)
        out['root_travel_ok'] = bool(abs(travel.length - want) < 0.3)
    elif motion_id == 'auth/drive':
        for name in THIGHS:
            d = delta(name, 1)
            out[name.lower() + '_angle_deg'] = round(math.degrees(d.angle), 3)
            out[name.lower() + '_pitch_deg'] = twist_deg(d)
        out['upleg_angle_ok'] = bool(
            abs(out['leftupleg_angle_deg'] - DRIVE_THIGH_DEG) < 1.0
            and abs(out['rightupleg_angle_deg'] - DRIVE_THIGH_DEG) < 1.0
        )
        out['knee_angle_deg'] = round(math.degrees(delta('LeftLeg', 1).angle), 3)
        out['seat_offset'] = dict(DRIVE_SEAT_OFFSET)
    elif motion_id == 'auth/scream':
        out['head_pitch_deg_frame12'] = twist_deg(delta('Head', 12))
        out['head_pitch_ok'] = bool(abs(out['head_pitch_deg_frame12'] - SCREAM_HEAD_DEG) < 1.0)
        out['head_pitch_deg_frame1'] = twist_deg(delta('Head', 1))
        finger = next(iter(_on_rig(arm, ('LeftHandFinger1', 'LeftHandIndex1'))), None)
        if finger:
            hold = SCREAM_RISE_FRAMES + SCREAM_TREMOR_FRAMES // 2
            out['fist_finger_vs_hand_deg'] = round(
                math.degrees((delta(finger, hold) @ delta('LeftHand', hold).inverted()).angle), 1
            )
        out['spine1_tremor_span_deg'] = round(
            max(twist_deg(delta('Spine1', f)) for f in range(13, 49))
            - min(twist_deg(delta('Spine1', f)) for f in range(13, 49)),
            3,
        )
    scene.frame_set(1)
    bpy.context.view_layer.update()
    return out
