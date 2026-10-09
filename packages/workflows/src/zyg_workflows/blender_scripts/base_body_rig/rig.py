# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Inside tests, the armature, the weights, the rest render and the checks —
base_body_rig sections 8-12."""

import math
import os
import tempfile

import bpy
from mathutils import Vector

from .scene import (
    ARM_FRACTION,
    ARM_LENGTH_FRACTION,
    BONE_RENAME,
    CENTRE_BONES,
    ELBOW_FRACTION,
    FOREARM_RATIO,
    GROUND_TOL,
    HEIGHT_FRACTIONS,
    INSIDE_MARGIN,
    MIRROR_PAIRS,
    MIRROR_TOL,
    TIP_TAILS,
    VIEW_H,
    VIEW_W,
    WRIST_FRACTION,
    activate,
    bbox,
    local_verts,
)

# ------------------------------------------------------------- inside / nudge


def hit_count(tree, origin, direction, limit=64):
    here = Vector(origin)
    hits = 0
    for _ in range(limit):
        loc, _nor, _idx, _dist = tree.ray_cast(here, direction, 1e4)
        if loc is None:
            break
        hits += 1
        here = loc + direction * 1e-5
    return hits


RAYS = (
    Vector((1, 0, 0)),
    Vector((-1, 0, 0)),
    Vector((0, 1, 0)),
    Vector((0, -1, 0)),
    Vector((0, 0, 1)),
    Vector((0, 0, -1)),
)


def is_inside(tree, point):
    """Ray parity in six directions, majority vote.

    A single ray is not enough: the body is not perfectly watertight (the mouth
    bag and the eye sockets are open), so a ray that leaves through one of them
    reports the wrong parity. When the vote is split the nearest surface's
    normal decides."""
    odd = sum(1 for d in RAYS if hit_count(tree, point, d) % 2 == 1)
    if odd >= 4:
        return True
    if odd <= 1:
        return False
    loc, nor, _idx, _dist = tree.find_nearest(point)
    return loc is not None and (point - loc).dot(Vector(nor)) < 0.0


def surface_distance(tree, point):
    loc, _nor, _idx, dist = tree.find_nearest(point)
    return dist if loc is not None else 0.0


def nudge_inside(tree, point, anchor):
    """Push a joint that fell outside the surface back in, or fail honestly."""
    if is_inside(tree, point):
        return point, 0.0
    start = point.copy()
    loc, nor, _idx, _dist = tree.find_nearest(point)
    if loc is not None:
        cand = loc - Vector(nor).normalized() * INSIDE_MARGIN
        if is_inside(tree, cand):
            return cand, (cand - start).length
    for i in range(1, 21):
        cand = start.lerp(anchor, i / 20.0)
        if is_inside(tree, cand):
            return cand, (cand - start).length
    return start, 0.0


# ------------------------------------------------------------------ armature


def bone_table(arm):
    return {b.name: (b.head_local.copy(), b.tail_local.copy()) for b in arm.data.bones}


def write_bones(arm, heads, tails):
    activate(arm)
    bpy.ops.object.mode_set(mode='EDIT')
    for bone in arm.data.edit_bones:
        bone.use_connect = False
    for bone in arm.data.edit_bones:
        head, tail = heads[bone.name], tails[bone.name]
        if (tail - head).length < 1e-4:  # Blender deletes zero-length bones
            tail = head + (bone.tail - bone.head).normalized() * 0.01
        roll = bone.roll
        bone.head = head
        bone.tail = tail
        bone.roll = roll
    bpy.ops.object.mode_set(mode='OBJECT')
    bpy.context.view_layer.update()


def rename_bones(arm):
    for old, new in BONE_RENAME.items():
        if old in arm.data.bones:
            arm.data.bones[old].name = new


def symmetrise(heads, tails):
    """Mirror every Left/Right pair exactly and pin the centre chain to x = 0."""
    for table in (heads, tails):
        for name in CENTRE_BONES:
            table[name].x = 0.0
        for left, right in MIRROR_PAIRS:
            lv, rv = table[left], table[right]
            half = (lv.x - rv.x) * 0.5
            mid_y = (lv.y + rv.y) * 0.5
            mid_z = (lv.z + rv.z) * 0.5
            table[left] = Vector((half, mid_y, mid_z))
            table[right] = Vector((-half, mid_y, mid_z))


# ------------------------------------------------------------------- weights


def bind(mesh, arm):
    bpy.ops.object.select_all(action='DESELECT')
    mesh.select_set(True)
    arm.select_set(True)
    bpy.context.view_layer.objects.active = arm
    bpy.ops.object.parent_set(type='ARMATURE_AUTO')


def pin_eyes(mesh, bone='Head'):
    group = mesh.vertex_groups.get('EYES')
    if group is None:
        return 0
    eyes = [v.index for v in mesh.data.vertices if any(g.group == group.index for g in v.groups)]
    head = mesh.vertex_groups.get(bone) or mesh.vertex_groups.new(name=bone)
    for other in mesh.vertex_groups:
        if other.index in (group.index, head.index):
            continue
        other.remove(eyes)
    head.add(eyes, 1.0, 'REPLACE')
    return len(eyes)


def unweighted(mesh, ignore=('EYES',)):
    skip = {mesh.vertex_groups[n].index for n in ignore if n in mesh.vertex_groups}
    count = 0
    for vert in mesh.data.vertices:
        total = sum(g.weight for g in vert.groups if g.group not in skip)
        if total < 0.01:
            count += 1
    return count


# -------------------------------------------------------------------- render


def bone_sticks(arm, name='rig_viz'):
    """Octahedral sticks, one per bone — armatures do not appear in a render."""
    verts, faces = [], []
    for bone in arm.data.bones:
        head, tail = bone.head_local, bone.tail_local
        span = tail - head
        length = span.length
        if length < 1e-6:
            continue
        direction = span.normalized()
        up = Vector((0, 0, 1)) if abs(direction.z) < 0.9 else Vector((1, 0, 0))
        axis_a = direction.cross(up).normalized()
        axis_b = direction.cross(axis_a).normalized()
        radius = max(0.005, 0.045 * length)
        ring = head + direction * (0.14 * length)
        base = len(verts)
        verts.append(head.copy())
        verts.append(tail.copy())
        for sx, sy in ((1, 0), (0, 1), (-1, 0), (0, -1)):
            verts.append(ring + axis_a * (radius * sx) + axis_b * (radius * sy))
        for i in range(4):
            j = (i + 1) % 4
            faces.append((base, base + 2 + i, base + 2 + j))
            faces.append((base + 1, base + 2 + j, base + 2 + i))
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata([tuple(v) for v in verts], [], faces)
    mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(obj)
    return obj


def load_png(path):
    import numpy as np

    img = bpy.data.images.load(path)
    img.colorspace_settings.name = 'Non-Color'
    buf = np.empty(len(img.pixels), dtype=np.float32)
    img.pixels.foreach_get(buf)
    arr = buf.reshape(img.size[1], img.size[0], 4).copy()
    bpy.data.images.remove(img)
    return arr


def save_png(arr, path):
    out = bpy.data.images.new('rest', width=arr.shape[1], height=arr.shape[0], alpha=True)
    out.colorspace_settings.name = 'Non-Color'
    out.pixels.foreach_set(arr.ravel())
    out.filepath_raw = path
    out.file_format = 'PNG'
    out.save()
    bpy.data.images.remove(out)


def render_rest(mesh, arm, out_path, height):
    import numpy as np

    scene = bpy.context.scene
    scene.render.engine = 'BLENDER_WORKBENCH'
    if hasattr(scene, 'cycles'):
        scene.cycles.device = 'CPU'
    scene.display.shading.light = 'STUDIO'
    scene.display.shading.color_type = 'OBJECT'
    scene.display.shading.show_shadows = False
    scene.render.resolution_x = VIEW_W
    scene.render.resolution_y = VIEW_H
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = 'PNG'
    scene.render.image_settings.color_mode = 'RGBA'

    mesh.color = (0.62, 0.58, 0.54, 1.0)
    viz = bone_sticks(arm)
    viz.color = (0.95, 0.20, 0.12, 1.0)

    cam_data = bpy.data.cameras.new('rest_cam')
    cam_data.type = 'ORTHO'
    cam_data.ortho_scale = height * 1.12
    cam = bpy.data.objects.new('rest_cam', cam_data)
    scene.collection.objects.link(cam)
    scene.camera = cam

    lo, hi = bbox(local_verts(mesh))
    centre = (lo + hi) * 0.5
    views = (
        ('front', (math.pi / 2.0, 0.0, 0.0), (centre.x, centre.y - 6.0, centre.z)),
        ('side', (math.pi / 2.0, 0.0, math.pi / 2.0), (centre.x + 6.0, centre.y, centre.z)),
    )

    tiles = []
    for name, rot, loc in views:
        cam.rotation_euler = rot
        cam.location = loc
        layers = []
        for solo, transparent in ((mesh, False), (viz, True)):
            mesh.hide_render = solo is not mesh
            viz.hide_render = solo is not viz
            scene.render.film_transparent = transparent
            fd, path = tempfile.mkstemp(prefix='base_body_rig_%s_%s_' % (name, solo.name), suffix='.png')
            os.close(fd)
            scene.render.filepath = path
            bpy.ops.render.render(write_still=True)
            layers.append(load_png(path))
            os.remove(path)
        body_px, bone_px = layers
        alpha = bone_px[:, :, 3:4]
        tiles.append(body_px * (1.0 - alpha) + bone_px * alpha)
    mesh.hide_render = False

    save_png(np.concatenate(tiles, axis=1), out_path)
    bpy.data.objects.remove(viz, do_unlink=True)
    bpy.data.objects.remove(cam, do_unlink=True)
    bpy.data.cameras.remove(cam_data)


# -------------------------------------------------------------------- checks


def arm_measures(arm, height):
    """The left arm's lengths and joint heights — the numbers the bands gate.

    symmetrise() has already made the right arm the mirror of these."""
    head = lambda name: arm.data.bones[name].head_local
    shoulder, elbow, wrist = head('LeftArm'), head('LeftForeArm'), head('LeftHand')
    upper = (elbow - shoulder).length
    fore = (wrist - elbow).length
    return {
        'upper_arm_m': round(upper, 4),
        'forearm_m': round(fore, 4),
        'shoulder_to_wrist_m': round((wrist - shoulder).length, 4),
        'arm_fraction': round((wrist - shoulder).length / height, 4),
        'arm_length_fraction': round((upper + fore) / height, 4),
        'forearm_ratio': round(fore / upper, 4) if upper > 1e-6 else 0.0,
        'shoulder_fraction': round(shoulder.z / height, 4),
        'elbow_fraction': round(elbow.z / height, 4),
        'wrist_fraction': round(wrist.z / height, 4),
    }


def run_checks(mesh, arm, height, wanted, outside, unweighted_count):
    names = sorted(b.name for b in arm.data.bones)
    lo, _hi = bbox(local_verts(mesh))
    mirror_ok = True
    mirror_worst = 0.0
    for left, right in MIRROR_PAIRS:
        lv = arm.data.bones[left].head_local
        rv = arm.data.bones[right].head_local
        mirror_worst = max(mirror_worst, abs(lv.x + rv.x), abs(lv.z - rv.z))
    mirror_ok = mirror_worst <= MIRROR_TOL

    fractions = {}
    frac_ok = True
    for bone, (low, high) in HEIGHT_FRACTIONS.items():
        frac = arm.data.bones[bone].head_local.z / height
        fractions[bone] = round(frac, 4)
        frac_ok = frac_ok and low <= frac <= high

    arm_info = arm_measures(arm, height)

    hard = [d for name, d in outside.items() if d > 0.0 and name not in ['%s.tail' % b for b in TIP_TAILS]]
    tips = [d for name, d in outside.items() if name in ['%s.tail' % b for b in TIP_TAILS]]
    within = lambda key, band: band[0] <= arm_info[key] <= band[1]
    return {
        'bone_count_31': len(names) == 31,
        'bone_names_match_cmu_mb': names == sorted(wanted),
        'joints_inside_mesh': (not hard) and (max(tips) if tips else 0.0) <= 0.005,
        'mirror_symmetric': bool(mirror_ok),
        'height_fractions_ok': bool(frac_ok),
        'feet_on_ground': abs(lo.z) <= GROUND_TOL,
        'weights_complete': unweighted_count == 0,
        'arm_length_ok': within('arm_fraction', ARM_FRACTION),
        'arm_segments_ok': within('arm_length_fraction', ARM_LENGTH_FRACTION),
        'forearm_ratio_ok': within('forearm_ratio', FOREARM_RATIO),
        'elbow_height_ok': within('elbow_fraction', ELBOW_FRACTION),
        'wrist_height_ok': within('wrist_fraction', WRIST_FRACTION),
    }, {
        'height_fractions': fractions,
        'arm': arm_info,
        'mirror_worst_m': round(mirror_worst, 5),
        'max_outside_m': round(max(list(outside.values()) or [0.0]), 5),
        'outside_joints': {k: round(v, 5) for k, v in sorted(outside.items()) if v > 0.0},
        'mesh_min_z': round(lo.z, 5),
    }
