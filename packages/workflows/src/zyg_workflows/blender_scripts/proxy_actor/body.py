# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

import os

import bpy
from mathutils import Matrix

from zyg_workflows.blender_scripts import skeleton_bind
from zyg_workflows.blender_scripts.proxy_actor.args_scene import age_macro
from zyg_workflows.blender_scripts.proxy_actor.constants import BASE_BODY_ROOT

# ---------------------------------------------------------------------- body


def build_body(args):
    from bl_ext.user_default.mpfb.services.humanservice import HumanService
    from bl_ext.user_default.mpfb.services.targetservice import TargetService

    macro = TargetService.get_default_macro_info_dict()
    macro.update(
        {
            'gender': args.gender,
            'age': age_macro(args.age),
            'height': args.height01,
            'weight': args.weight,
            'muscle': args.muscle,
        }
    )
    # detailed_helpers must stay True: the cmu_mb rig locates every bone head and
    # tail from the `joint-*` helper vertex groups (entities/rig.py CUBE strategy).
    # Without them the rig falls back to its un-morphed default positions.
    body = HumanService.create_human(
        mask_helpers=True,
        detailed_helpers=True,
        extra_vertex_groups=False,
        feet_on_ground=True,
        scale=0.1,
        macro_detail_dict=macro,
    )
    body.name = args.name
    body.data.name = args.name
    return body


def add_rig(body, name):
    from bl_ext.user_default.mpfb.services.humanservice import HumanService

    arm = HumanService.add_builtin_rig(body, 'cmu_mb', import_weights=True)
    arm.name = arm.data.name = name + '_rig'
    if body.parent is not arm:
        body.parent = arm
        body.matrix_parent_inverse = arm.matrix_world.inverted()
    return arm


def strip_helpers(body):
    """Bake the macro shape keys, apply the helper mask, drop helper vertex groups."""
    from bl_ext.user_default.mpfb.services.targetservice import TargetService

    if body.data.shape_keys:
        TargetService.bake_targets(body)
    bpy.ops.object.select_all(action='DESELECT')
    body.select_set(True)
    bpy.context.view_layer.objects.active = body
    for mod in list(body.modifiers):
        if mod.type == 'MASK' and mod.vertex_group == 'body' and not mod.invert_vertex_group:
            bpy.ops.object.modifier_apply(modifier=mod.name)
    for group in list(body.vertex_groups):
        if (
            group.name.startswith('helper-')
            or group.name.startswith('joint-')
            or group.name in ('Mid', 'Left', 'Right', 'HelperGeometry', 'JointCubes')
        ):
            body.vertex_groups.remove(group)
    return len(body.data.vertices), len(body.vertex_groups)


# ── the clavicles must not drive the chest ──────────────────────────────────
# Bone heat (``base_body_rig.py``) gave the chest wall to the two clavicle
# bones, because that is where the geodesic heuristic looks: LeftShoulder and
# RightShoulder run 15 cm across the top of the chest a centimetre under the
# skin, so they win vertices the thorax owns. Measured on male_realistic: the
# sternum is 70 % clavicle and 9 % Spine1, the pectoral 77 % clavicle and 1 %
# Spine1, and vertices 20-40 cm from either clavicle still carry 15 % of one.
#
# On a walk the two clavicles counter-rotate with the arms, so the whole chest
# wall swung with them and collapsed INWARD PAST THE RIBCAGE -- up to 369
# ribcage vertices ended up outside the skin, by 28 mm, on a chest that is
# 32 mm clear at the bind pose. That is the "skin on his chest goes through the
# chest while walking" of 2026-09-24, and no fit of the skeleton can cure it:
# the skin is what moves.
#
# So a clavicle's influence is bounded by the distance to its own SEGMENT --
# kept whole within CLAVICLE_NEAR, gone by CLAVICLE_FAR, linear between -- and
# every gram taken off it is handed to Spine1, the bone that carries the
# thorax. The band is 5 cm wide, so nothing creases; the skin over the clavicle
# itself still belongs to the clavicle.
CLAVICLE_BONES = ('LeftShoulder', 'RightShoulder')
CLAVICLE_HOST = 'Spine1'
CLAVICLE_NEAR = 0.04  # m: the clavicle's own skin, kept whole
CLAVICLE_FAR = 0.09  # m: beyond this the thorax owns the vertex


def bound_clavicles(body, arm):
    """Cap the clavicle groups by distance to the clavicle, thorax keeps the rest."""
    groups = {b: body.vertex_groups.get(b) for b in CLAVICLE_BONES}
    host = body.vertex_groups.get(CLAVICLE_HOST) or body.vertex_groups.new(name=CLAVICLE_HOST)
    if not all(groups.values()):
        return {'skipped': 'no clavicle vertex groups on %s' % body.name}
    segs = []
    for b in CLAVICLE_BONES:
        bone = arm.data.bones[b]
        segs.append((arm.matrix_world @ bone.head_local, arm.matrix_world @ bone.tail_local))
    gi = {g.index: b for b, g in groups.items()}
    hi = host.index
    moved, touched, worst = 0.0, 0, 0.0
    for v in body.data.vertices:
        w = {gi[g.group]: g.weight for g in v.groups if g.group in gi}
        if not w or sum(w.values()) <= 0.0:
            continue
        co = body.matrix_world @ v.co
        d = min(_point_segment(co, a, t) for a, t in segs)
        keep = (CLAVICLE_FAR - d) / (CLAVICLE_FAR - CLAVICLE_NEAR)
        keep = 0.0 if keep < 0.0 else (1.0 if keep > 1.0 else keep)
        if keep >= 1.0:
            continue
        give = 0.0
        for b, old in w.items():
            groups[b].add([v.index], old * keep, 'REPLACE')
            give += old * (1.0 - keep)
        was = next((g.weight for g in v.groups if g.group == hi), 0.0)
        host.add([v.index], min(1.0, was + give), 'REPLACE')
        moved += give
        touched += 1
        worst = max(worst, give)
    return {
        'vertices': touched,
        'weight_moved': round(moved, 2),
        'worst_vertex': round(worst, 3),
        'host': CLAVICLE_HOST,
        'near_m': CLAVICLE_NEAR,
        'far_m': CLAVICLE_FAR,
    }


# ── and the arms must not drive the flank ───────────────────────────────────
# Same failure, one bone further out. In the base body's A-pose the upper arm
# hangs a few centimetres from the lateral chest, so bone heat handed the flank
# to it: measured on male_realistic, the skin over the lower lateral ribs is
# 18 % RightArm, and 415 of 1446 torso vertices carry more than 5 % of the arm
# chain (worst 62 %). On a walk the arm swings 45 deg and drags that skin with
# it -- the lateral chest travels 45 mm in the thorax's own frame and swallows
# 300 ribcage vertices -- and align_rest's 58 deg turn to the BVH's T-pose bakes
# a pulled chest into the bind pose before anything else has run.
#
# WHICH SKIN IS THE ARM'S CANNOT BE DECIDED BY DISTANCE (the hanging arm is
# nearer the flank than the spine is) AND NOT BY SLICES EITHER: the arm touches
# the torso all the way down this body's A-pose, so the first horizontal slice
# that splits arm | torso | arm -- base_body_rig.arm_region's own test -- lands
# at 1.146 m, below the ribs that are the problem (measured).
#
# So it is decided by the weights themselves, which get the DOMINANT bone right
# even where the secondary influences are wrong. On skin whose home is the
# trunk core, the arm chain's share is scaled by how close it comes to that
# home bone: nothing below ARM_RATIO_LO of it, everything at ARM_RATIO_HI, a
# smooth ramp between. The flank (Spine 0.35, arm 0.18, ratio 0.51) loses the
# arm; a vertex on the boundary where the two are comparable keeps it, so no
# crease is cut anywhere along it. The deltoid and the shoulder cap are not
# touched at all -- their home bone IS the arm or the clavicle.
ARM_CHAIN = (
    'LeftArm',
    'LeftForeArm',
    'LeftHand',
    'LeftFingerBase',
    'LeftHandIndex1',
    'LThumb',
    'RightArm',
    'RightForeArm',
    'RightHand',
    'RightFingerBase',
    'RightHandIndex1',
    'RThumb',
)
TRUNK_CORE = ('Hips', 'LHipJoint', 'RHipJoint', 'LowerBack', 'Spine', 'Spine1')
ARM_RATIO_LO = 0.55  # arm share this far under the home bone's: gone
ARM_RATIO_HI = 1.00  # as big as the home bone's: kept whole


def bound_arm_chain(body, arm):  # noqa: ARG001
    """Fade the arm chain out of trunk-core skin. -> report."""
    by_index = {g.index: g for g in body.vertex_groups}
    chain = {g.index for b in ARM_CHAIN for g in (body.vertex_groups.get(b),) if g}
    core = {g.index for b in TRUNK_CORE for g in (body.vertex_groups.get(b),) if g}
    if not chain or not core:
        return {'skipped': 'no arm or no trunk groups on %s' % body.name}
    moved, touched, worst = 0.0, 0, 0.0
    for v in body.data.vertices:
        w = [(g.group, g.weight) for g in v.groups if g.weight > 0.0]
        if not w:
            continue
        home, home_w = max(w, key=lambda x: x[1])
        if home not in core:
            continue
        armw = sum(x[1] for x in w if x[0] in chain)
        if armw <= 1e-6:
            continue
        ratio = armw / home_w
        keep = (ratio - ARM_RATIO_LO) / (ARM_RATIO_HI - ARM_RATIO_LO)
        keep = 0.0 if keep < 0.0 else (1.0 if keep > 1.0 else keep)
        keep = keep * keep * (3.0 - 2.0 * keep)  # smoothstep
        give = armw * (1.0 - keep)
        if give <= 1e-6:
            continue
        for group, old in w:
            if group in chain:
                by_index[group].add([v.index], old * keep, 'REPLACE')
        rest = [x for x in w if x[0] not in chain]
        total = sum(x[1] for x in rest)
        if total > 0.0:
            for group, old in rest:
                by_index[group].add([v.index], old + give * old / total, 'REPLACE')
        moved += give
        touched += 1
        worst = max(worst, give)
    return {
        'vertices': touched,
        'weight_moved': round(moved, 2),
        'worst_vertex': round(worst, 3),
        'ratio_band': [ARM_RATIO_LO, ARM_RATIO_HI],
    }


def _point_segment(p, a, b):
    ab = b - a
    denom = ab.dot(ab)
    if denom <= 0.0:
        return (p - a).length
    t = max(0.0, min(1.0, (p - a).dot(ab) / denom))
    return (p - (a + ab * t)).length


def base_body_id(gender):
    return 'male_realistic' if gender >= 0.5 else 'female_realistic'


def load_base_body(args):
    """Append the rigged CC0 base body whole: mesh, cmu_mb armature, weights.

    Replaces build_body + add_rig + strip_helpers for ``--body base``. The rig
    is already the 31-bone cmu_mb skeleton with identity transforms and the feet
    on the ground, so the caller can carry straight on at standing_height()."""
    base_id = base_body_id(args.gender)
    path = os.path.join(BASE_BODY_ROOT, base_id, base_id + '.blend')
    if not os.path.isfile(path):
        raise SystemExit('no base body rig at %s' % path)
    with bpy.data.libraries.load(path, link=False) as (src, dst):
        dst.objects = list(src.objects)
    appended = [obj for obj in dst.objects if obj is not None]
    for obj in appended:
        bpy.context.scene.collection.objects.link(obj)
    arms = [obj for obj in appended if obj.type == 'ARMATURE']
    meshes = [obj for obj in appended if obj.type == 'MESH']
    if len(arms) != 1 or not meshes:
        raise SystemExit(
            '%s: want one armature and at least one mesh, got %s'
            % (path, sorted((obj.name, obj.type) for obj in appended))
        )
    arm = arms[0]
    body = max(meshes, key=lambda obj: len(obj.data.vertices))
    for obj in appended:
        if obj is not arm and obj is not body:
            bpy.data.objects.remove(obj, do_unlink=True)

    body.name = body.data.name = args.name
    arm.name = arm.data.name = args.name + '_rig'
    arm.matrix_world = Matrix.Identity(4)
    body.matrix_world = Matrix.Identity(4)
    if body.parent is not arm:
        body.parent = arm
        body.matrix_parent_inverse = arm.matrix_world.inverted()
    bound = [mod for mod in body.modifiers if mod.type == 'ARMATURE']
    if not bound:
        bound = [body.modifiers.new(name='Armature', type='ARMATURE')]
    for mod in bound:
        mod.object = arm
    bpy.context.view_layer.update()
    return body, arm, base_id


def bake_pose_as_rest(arm, body):
    """Apply the current pose as the rest pose, carrying the mesh with it.

    The body-agnostic form of MPFB's RigService.apply_pose_as_rest_pose, which
    only finds meshes MPFB itself created: bake the armature modifier into the
    mesh while the pose is still live, apply the pose as rest, re-bind.

    Every mesh in skeleton_bind.EXTRA_MESHES rides along: it is skinned to the
    same armature, so leaving it out would strand it in the OLD rest pose. Its
    weights are rigid 1.0 in one group, which an Armature-modifier apply
    reproduces exactly. Since 2026-09-24 the anatomical skeleton is fitted
    AFTER the last of these bakes (build(), and the reason is there), so the
    list is normally empty by now -- which is the point: a rigid mesh carried
    through a bake keeps its shape while the skin changes shape around it."""
    if body.data.shape_keys:
        raise SystemExit('%s still carries shape keys; bake them before the pose' % body.name)
    meshes = [body] + [m for m in skeleton_bind.EXTRA_MESHES if m.name in bpy.data.objects]
    if bpy.context.object is not None and bpy.context.object.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')
    for mesh in meshes:
        bpy.ops.object.select_all(action='DESELECT')
        mesh.select_set(True)
        bpy.context.view_layer.objects.active = mesh
        for mod in [m for m in mesh.modifiers if m.type == 'ARMATURE' and m.object is arm]:
            # Blender 4.x puts a 'Smooth by Angle' node modifier ahead of the deform
            # stack; applying out of order only warns, but the warning is noise.
            bpy.ops.object.modifier_move_to_index(modifier=mod.name, index=0)
            bpy.ops.object.modifier_apply(modifier=mod.name)
    bpy.ops.object.select_all(action='DESELECT')
    arm.select_set(True)
    bpy.context.view_layer.objects.active = arm
    bpy.ops.object.mode_set(mode='POSE')
    bpy.ops.pose.armature_apply(selected=False)
    bpy.ops.object.mode_set(mode='OBJECT')
    for mesh in meshes:
        mod = mesh.modifiers.new(name='Armature', type='ARMATURE')
        mod.object = arm
        bpy.context.view_layer.objects.active = mesh
        bpy.ops.object.modifier_move_to_index(modifier=mod.name, index=0)
    bpy.context.view_layer.update()


def apply_pose_as_rest(arm, body, kind):
    if kind == 'mpfb':
        from bl_ext.user_default.mpfb.services.rigservice import RigService

        RigService.apply_pose_as_rest_pose(arm)
    else:
        bake_pose_as_rest(arm, body)
