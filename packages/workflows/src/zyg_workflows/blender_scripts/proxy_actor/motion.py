# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

import math

import bpy
from mathutils import Matrix, Vector

from zyg_workflows.blender_scripts.proxy_actor.args_scene import evaluated_points
from zyg_workflows.blender_scripts.proxy_actor.body import apply_pose_as_rest
from zyg_workflows.blender_scripts.proxy_actor.constants import GROUND_TOL, TRACK_GROUPS, TRACK_WEIGHT_MIN

# -------------------------------------------------------------------- motion


def import_bvh(path, global_scale=1.0):
    before = set(bpy.data.objects)
    bpy.ops.import_anim.bvh(
        filepath=path,
        rotate_mode='NATIVE',
        axis_forward='-Z',
        axis_up='Y',
        use_fps_scale=True,
        update_scene_fps=False,
        update_scene_duration=False,
        global_scale=global_scale,
    )
    new = [o for o in bpy.data.objects if o not in before]
    if not new:
        raise SystemExit('BVH import produced no object: %s' % path)
    return new[0]


def hierarchy_order(arm):
    order = []
    stack = [b for b in arm.data.bones if b.parent is None]
    while stack:
        bone = stack.pop(0)
        order.append(bone.name)
        stack.extend(bone.children)
    return order


def sample_bvh(src, names, frames):
    """World matrix of every mapped BVH bone, per frame."""
    scene = bpy.context.scene
    out = []
    for frame in frames:
        scene.frame_set(frame)
        bpy.context.view_layer.update()
        mat_world = src.matrix_world
        out.append({nm: (mat_world @ src.pose.bones[nm].matrix).copy() for nm in names})
    return out


def align_rest(arm, body, src, mapping, names, kind='mpfb'):
    """Turn the named rest bones to their BVH frame-1 world direction, apply as rest.

    Direction only — the rig's own roll is kept. Matching the BVH's full
    orientation would drag its roll convention in with it, and that disagrees by
    up to 181 deg on the thighs, which twists the mesh around the limb axis.
    The base body rests in the same A-pose as MPFB, so it needs the same turn."""
    bpy.context.scene.frame_set(1)
    bpy.context.view_layer.update()
    to_local = arm.matrix_world.inverted()
    applied = {}
    for name in hierarchy_order(arm):
        src_name = mapping.get(name)
        if name not in names or src_name is None:
            continue
        pbone = arm.pose.bones[name]
        cur = pbone.matrix.copy()
        cur_dir = (cur.to_3x3() @ Vector((0.0, 1.0, 0.0))).normalized()
        want = to_local @ src.matrix_world @ src.pose.bones[src_name].matrix
        want_dir = (want.to_3x3() @ Vector((0.0, 1.0, 0.0))).normalized()
        rot = cur_dir.rotation_difference(want_dir)
        pbone.matrix = Matrix.Translation(cur.translation) @ (rot.to_matrix() @ cur.to_3x3()).to_4x4()
        bpy.context.view_layer.update()
        applied[name] = round(math.degrees(rot.angle), 1)
    apply_pose_as_rest(arm, body, kind)
    bpy.context.view_layer.update()
    return applied


def retarget(arm, samples, mapping, root_bone='Hips'):
    """Bake the world-space delta of every mapped bone onto the MPFB rig."""
    order = hierarchy_order(arm)
    rest = {b.name: b.matrix_local.copy() for b in arm.data.bones}
    rest_rel = {}
    for bone in arm.data.bones:
        rest_rel[bone.name] = (
            bone.parent.matrix_local.inverted() @ bone.matrix_local if bone.parent else bone.matrix_local.copy()
        )
    rest_q = {nm: mat.to_3x3().to_quaternion() for nm, mat in rest.items()}

    for pbone in arm.pose.bones:
        pbone.rotation_mode = 'QUATERNION'
    arm.animation_data_create()
    action = bpy.data.actions.new('motion')
    arm.animation_data.action = action

    base = samples[0]
    base_q = {nm: mat.to_3x3().to_quaternion() for nm, mat in base.items()}
    identity = Matrix.Identity(4)
    max_delta = 0.0

    for index, rec in enumerate(samples):
        frame = index + 1
        world = {}
        for name in order:
            bone = arm.data.bones[name]
            parent_world = world[bone.parent.name] if bone.parent else identity
            fk = parent_world @ rest_rel[name]
            src_name = mapping.get(name)
            if src_name is None:
                new_world = fk
            else:
                delta = rec[src_name].to_3x3().to_quaternion() @ base_q[src_name].inverted()
                turn = abs(delta.angle) % (2.0 * math.pi)
                max_delta = max(max_delta, min(turn, 2.0 * math.pi - turn))
                new_world = Matrix.Translation(fk.translation) @ (delta @ rest_q[name]).to_matrix().to_4x4()
                if name == root_bone:
                    new_world.translation = fk.translation + (rec[src_name].translation - base[src_name].translation)
            basis = rest_rel[name].inverted() @ parent_world.inverted() @ new_world
            pbone = arm.pose.bones[name]
            pbone.matrix_basis = basis
            pbone.keyframe_insert('location', frame=frame, group=name)
            pbone.keyframe_insert('rotation_quaternion', frame=frame, group=name)
            world[name] = new_world
    return action, math.degrees(max_delta)


# ------------------------------------------------------------------ grounding


def track_vertex_indices(body, groups=TRACK_GROUPS, threshold=TRACK_WEIGHT_MIN):
    """Rest-mesh indices of the vertices mostly bound to the root chain."""
    wanted = {body.vertex_groups[name].index for name in groups if name in body.vertex_groups}
    indices = []
    for vert in body.data.vertices:
        for entry in vert.groups:
            if entry.group in wanted and entry.weight > threshold:
                indices.append(vert.index)
                break
    return indices


def per_frame_stats(body, arm, frames, hips='Hips', track_indices=()):
    scene = bpy.context.scene
    rows = []
    for frame in frames:
        scene.frame_set(frame)
        bpy.context.view_layer.update()
        lo, hi, centroid = evaluated_points(body, track_indices)
        centre = (lo + hi) * 0.5
        head = arm.matrix_world @ arm.pose.bones[hips].head
        rows.append((frame, lo.z, centre, head, centroid))
    return rows


def ground(arm, body, frames, mode):
    """Centre the per-frame lowest mesh point on z = 0; per-frame lock if needed."""
    rows = per_frame_stats(body, arm, frames)
    lows = [r[1] for r in rows]
    offset = -(max(lows) + min(lows)) * 0.5
    arm.location.z += offset
    spread = (max(lows) - min(lows)) * 0.5
    locked = False
    if mode == 'on' or (mode == 'auto' and spread > GROUND_TOL):
        base_z = arm.location.z
        for frame, low, _c, _h, _t in rows:
            arm.location.z = base_z - (low + offset)
            arm.keyframe_insert('location', index=2, frame=frame)
        locked = True
    return offset, spread, locked


def face_minus_y(arm):
    """Rotate about z so the character faces -Y (studio -Z) at frame 1."""
    bpy.context.scene.frame_set(1)
    bpy.context.view_layer.update()
    left = (arm.matrix_world @ arm.pose.bones['LeftUpLeg'].head) - (
        arm.matrix_world @ arm.pose.bones['RightUpLeg'].head
    )
    left.z = 0.0
    if left.length < 1e-6:
        return 0.0
    left.normalize()
    facing = left.cross(Vector((0.0, 0.0, 1.0)))
    theta = math.atan2(-facing.x, -facing.y)  # angle from facing to (0,-1,0)
    arm.rotation_euler.z += theta
    bpy.context.view_layer.update()
    return math.degrees(theta)
