# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""build_pufferball_actor.py — the creature proxy actor for the scene bridge.

A non-humanoid actor in the same format as the human ones, so a creature can be
walked (hopped) through the city.  Wan-Animate drives a 2D skeleton, so a
creature does not need 33 joints — it needs the subset its bones can honestly
fill, and ``mapping='creature'`` + a ``joint_map`` custom property says which.

    build:  flock /tmp/claude-1000/arch_ext_blender.lock \
              blender -b --factory-startup -noaudio \
              --python blender_scripts/build_pufferball_actor.py
    check:  ... --python blender_scripts/build_pufferball_actor.py -- --check

SOURCE RIG.  ``pufferball_solid_unirig.glb`` is auto-rigged by UniRig, so all 59
bones are called ``bone_<n>`` — there is no semantic name prefix to search for.
The chains are therefore derived from the *topology* (which is stable) and then
pinned with asserts against the names measured on 2026-09-15, so a changed source
fails loudly instead of animating the wrong limb.  All 59 names and the derived
chains are written into the sidecar JSON.

The glb already matches the pufferball.py conventions (-Y facing, +Z up, mesh
resting on z=0), so no re-orientation is needed; the script asserts that too.
"""

from __future__ import annotations

import json
import logging as _zyg_logging
import math
import os
import sys
import tempfile
import time

import bpy
from mathutils import Matrix, Vector

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import actor_joints as AJ  # noqa: E402

from zyg_workflows.paths import ZYG_LORA_DATASETS  # noqa: E402  the sys.path setup above must run first

_zyg_log = _zyg_logging.getLogger(__name__)

SRC_GLB = str(ZYG_LORA_DATASETS / 'creatures' / 'd0e44ab002ad' / 'mesh_rigged' / 'pufferball_solid_unirig.glb')
OUT_DIR = os.path.join(REPO, 'data', 'architecture', 'actors', 'pufferball')
OUT_BLEND = os.path.join(OUT_DIR, 'pufferball.blend')
OUT_JSON = os.path.join(OUT_DIR, 'pufferball.json')
OUT_STRIP = os.path.join(OUT_DIR, 'pufferball_strip.png')

ACTOR_NAME = 'pufferball'
ACTOR_HEIGHT_M = 0.30  # the body ball; the tail carries the mesh higher
FPS = 24
HOP_FRAMES = 48
IDLE_FRAMES = 24
DEFAULT_MOTION = 'hop'
CHECK_FRAMES = (1, 12, 24)

# --- the hop, in metres of world Z on the root bone -------------------------
HOP_AMP = 0.060  # the brief's 0.06 m sine: the big arch
HOP_LAUNCH_F, HOP_LAND_F = 7, 41
BOUNCE_AMP = 0.016  # the second, smaller hop
BOUNCE_F0, BOUNCE_F1 = 41, 47
CROUCH = -0.010  # squash at ground contact / the loop point
LEG_SWING_DEG = 20.0
TAIL_SWAY_DEG = 2.5  # per tail bone; 12 bones, so it accumulates
TAIL_WHIP_DEG = 2.0
SPINE_SWAY_DEG = 2.5
BREATH_SCALE = 0.02


# ---------------------------------------------------------------- utilities


def _log(msg):
    _zyg_log.info('[pufferball-actor] %s' % msg)


def _chain(bone):
    """Follow a single-child chain from ``bone`` to its first fork (inclusive)."""
    out = [bone]
    while len(bone.children) == 1:
        bone = bone.children[0]
        out.append(bone)
    return out


def _dir(bone):
    return (Vector(bone.tail_local) - Vector(bone.head_local)).normalized()


def _chain_through(bone, fan=4):
    """Follow a chain past its forks, always taking the best-aligned child.

    Stops at a *fan* — a bone with ``fan`` or more children, which on this rig is
    the head (the face/spike fan) rather than a limb branch.  A 2- or 3-way fork
    is a limb hanging off the spine, and the spine itself is the child that keeps
    going in the parent's direction.
    """
    out = [bone]
    while bone.children and len(bone.children) < fan:
        d = _dir(bone)
        bone = max(bone.children, key=lambda c: _dir(c).dot(d))
        out.append(bone)
    return out


def _tip(bone):
    """Deepest descendant tail position, following the longest branch."""
    best = Vector(bone.tail_local)
    for c in bone.children:
        t = _tip(c)
        if (t - Vector(bone.head_local)).length > (best - Vector(bone.head_local)).length:
            best = t
    return best


def _descendants(bone):
    out = [bone]
    for c in bone.children:
        out.extend(_descendants(c))
    return out


# ------------------------------------------------------------------ import


def import_source():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=SRC_GLB)

    # UniRig leaves a stray unskinned unit icosphere in the file.
    for ob in list(bpy.data.objects):
        if ob.type == 'MESH' and not ob.modifiers and not ob.vertex_groups:
            _log('dropping unskinned helper object %r' % ob.name)
            bpy.data.objects.remove(ob, do_unlink=True)

    arms = [o for o in bpy.data.objects if o.type == 'ARMATURE']
    meshes = [o for o in bpy.data.objects if o.type == 'MESH']
    if not (len(arms) == 1):
        raise RuntimeError('expected one armature, got %r' % [a.name for a in arms])
    if not (len(meshes) == 1):
        raise RuntimeError('expected one skinned mesh, got %r' % [m.name for m in meshes])
    arm, mesh = arms[0], meshes[0]
    arm.name = 'pufferball_rig'
    arm.data.name = 'pufferball_rig'
    mesh.name = 'pufferball_mesh'

    # Conventions: -Y facing, +Z up, standing on z=0.  Apply whatever transform
    # the importer left so world space == rig space.
    for ob in (arm, mesh):
        ob.rotation_mode = 'XYZ'
    bpy.ops.object.select_all(action='DESELECT')
    arm.select_set(True)
    mesh.select_set(True)
    bpy.context.view_layer.objects.active = arm
    if any(abs(v) > 1e-6 for v in arm.rotation_euler) or any(abs(v - 1.0) > 1e-6 for v in arm.scale):
        bpy.ops.object.transform_apply(location=False, rotation=True, scale=True)
    bpy.ops.object.select_all(action='DESELECT')

    lo, hi = rest_bbox(mesh)
    _log('rest bbox min=%s max=%s' % ([round(v, 4) for v in lo], [round(v, 4) for v in hi]))
    if abs(lo[2]) > 0.002:
        mesh_z = lo[2]
        for ob in (arm, mesh):
            ob.location.z -= mesh_z
        bpy.ops.object.select_all(action='DESELECT')
        arm.select_set(True)
        mesh.select_set(True)
        bpy.context.view_layer.objects.active = arm
        bpy.ops.object.transform_apply(location=True, rotation=False, scale=False)
        bpy.ops.object.select_all(action='DESELECT')
        lo, hi = rest_bbox(mesh)
        _log('re-grounded to z=0; bbox min=%s' % [round(v, 4) for v in lo])
    if abs(lo[2]) > 0.002:
        raise RuntimeError('creature does not stand on z=0: min z %.4f' % lo[2])
    # -Y is the front: the head must reach further forward than the tail.
    if not (lo[1] < 0 < hi[1]):
        raise RuntimeError('unexpected Y extent %s..%s' % (lo[1], hi[1]))
    return arm, mesh, lo, hi


def rest_bbox(mesh):
    pts = [mesh.matrix_world @ Vector(c) for c in mesh.bound_box]
    lo = [min(p[i] for p in pts) for i in range(3)]
    hi = [max(p[i] for p in pts) for i in range(3)]
    return lo, hi


# ------------------------------------------------- topology -> named chains


def derive_chains(arm):
    """Name the anatomy of a UniRig ``bone_<n>`` rig from its topology."""
    bones = arm.data.bones
    roots = [b for b in bones if b.parent is None]
    if not (len(roots) == 1):
        raise RuntimeError('expected one root bone, got %r' % [b.name for b in roots])
    root = roots[0]
    if not (len(root.children) == 1):
        raise RuntimeError('root %s forks' % root.name)
    body = root.children[0]

    kids = list(body.children)
    if not (len(kids) == 4):
        raise RuntimeError('body %s has %d children, expected 4' % (body.name, len(kids)))
    # the tail reaches furthest BEHIND (+Y); the two legs reach lowest (z); the
    # remainder is the spine/head chain.
    by_y = sorted(kids, key=lambda b: _tip(b).y)
    tail_root = by_y[-1]
    rest = [b for b in kids if b is not tail_root]
    by_z = sorted(rest, key=lambda b: _tip(b).z)
    legs = by_z[:2]
    spine_root = by_z[2]
    legs.sort(key=lambda b: -b.head_local.x)  # +X is the creature's left
    left_leg, right_leg = legs

    tail = _chain(tail_root)
    spine = _chain_through(spine_root)
    head = spine[-1]

    # front limbs: the two chains hanging off the spine that reach furthest
    # sideways.  They are not children of the head, so scan the whole spine.
    arms_ = []
    for sb in spine:
        for c in sb.children:
            if c in spine:
                continue
            arms_.append((abs(_tip(c).x), c))
    arms_.sort(key=lambda t: -t[0])
    front = [c for _, c in arms_[:2]]
    if not (len(front) == 2):
        raise RuntimeError('could not find two front limbs')
    front.sort(key=lambda b: -b.head_local.x)
    left_arm, right_arm = front

    # eyes: the best MIRROR pair in the head fan — two bones on opposite sides of
    # the median plane, at the same height and the same depth.
    hk = list(head.children)
    pairs = []
    for i in range(len(hk)):
        for j in range(i + 1, len(hk)):
            a, b = hk[i], hk[j]
            ha, hb = a.head_local, b.head_local
            if ha.x * hb.x >= 0 or abs(ha.x - hb.x) < 0.02:
                continue
            mirror = abs(ha.x + hb.x) + abs(ha.y - hb.y) + abs(ha.z - hb.z)
            pairs.append((mirror, a, b))
    if not (pairs):
        raise RuntimeError('no mirror pair under head %s' % head.name)
    pairs.sort(key=lambda t: t[0])
    _, e1, e2 = pairs[0]
    left_eye, right_eye = (e1, e2) if e1.head_local.x > e2.head_local.x else (e2, e1)

    def leg_parts(b):
        c = _chain(b)
        if len(c) < 3:
            raise RuntimeError('leg %s too short (%d bones)' % (b.name, len(c)))
        return c

    ch = {
        'root': root.name,
        'body': body.name,
        'spine': [b.name for b in spine],
        'head': head.name,
        'tail': [b.name for b in tail],
        'left_leg': [b.name for b in leg_parts(left_leg)],
        'right_leg': [b.name for b in leg_parts(right_leg)],
        'left_arm': [b.name for b in _chain(left_arm)],
        'right_arm': [b.name for b in _chain(right_arm)],
        'left_eye': left_eye.name,
        'right_eye': right_eye.name,
    }

    # Pinned against the rig measured on 2026-09-15.  A different source glb is
    # a different creature; fail rather than animate the wrong bones.
    expect = {
        'root': 'bone_0',
        'body': 'bone_1',
        'head': 'bone_7',
        'left_eye': 'bone_9',
        'right_eye': 'bone_10',
        'spine': ['bone_2', 'bone_3', 'bone_4', 'bone_5', 'bone_6', 'bone_7'],
        'left_leg': ['bone_39', 'bone_40', 'bone_41', 'bone_42'],
        'right_leg': ['bone_43', 'bone_44', 'bone_45', 'bone_46'],
    }
    for k, v in expect.items():
        if not (ch[k] == v):
            raise RuntimeError('chain %s derived %r, expected %r' % (k, ch[k], v))
    if not (len(ch['tail']) == 12 and ch['tail'][0] == 'bone_47'):
        raise RuntimeError(ch['tail'])
    if not (ch['left_arm'][0] == 'bone_15' and ch['right_arm'][0] == 'bone_27'):
        raise RuntimeError((ch['left_arm'], ch['right_arm']))
    return ch


def build_joint_map(ch):
    """MediaPipe subset a four-limbed creature can honestly fill (13 joints)."""
    la, ra = ch['left_arm'], ch['right_arm']
    ll, rl = ch['left_leg'], ch['right_leg']
    return {
        'nose': '%s:tail' % ch['head'],
        'left_eye': ch['left_eye'],
        'right_eye': ch['right_eye'],
        'left_shoulder': la[0],
        'right_shoulder': ra[0],
        'left_wrist': '%s:tail' % la[-1],
        'right_wrist': '%s:tail' % ra[-1],
        'left_hip': ll[0],
        'right_hip': rl[0],
        'left_knee': ll[1],
        'right_knee': rl[1],
        'left_ankle': ll[2],
        'right_ankle': rl[2],
    }


# ---------------------------------------------------------------- animation


def hop_root_z(f):
    """World-Z of the root bone at frame ``f`` (1..49; 49 == 1, the loop)."""
    if f < HOP_LAUNCH_F:
        return CROUCH * (1.0 - (f - 1) / float(HOP_LAUNCH_F - 1))
    if f <= HOP_LAND_F:
        u = (f - HOP_LAUNCH_F) / float(HOP_LAND_F - HOP_LAUNCH_F)
        return HOP_AMP * math.sin(math.pi * u)
    if f <= BOUNCE_F1:
        u = (f - BOUNCE_F0) / float(BOUNCE_F1 - BOUNCE_F0)
        return BOUNCE_AMP * math.sin(math.pi * u)
    return CROUCH * (f - BOUNCE_F1) / float(HOP_FRAMES + 1 - BOUNCE_F1)


def _basis_rot(pb, axis, angle):
    """Quaternion that rotates ``pb`` by ``angle`` about an ARMATURE-space axis.

    ``matrix_basis`` lives in the bone's own rest space, and matrix_local maps
    that space into armature space, so conjugating the armature-space rotation
    by the bone's rest orientation gives a rotation about the bone's own head
    around a world-aligned axis.
    """
    m3 = pb.bone.matrix_local.to_3x3()
    return (m3.inverted() @ Matrix.Rotation(angle, 3, axis) @ m3).to_quaternion()


def _key(pb, path, frame):
    pb.keyframe_insert(data_path=path, frame=frame, group=pb.name)


def make_action(arm, name):
    if arm.animation_data is None:
        arm.animation_data_create()
    act = bpy.data.actions.new(name)
    act.use_fake_user = True
    arm.animation_data.action = act
    return act


def author_hop(arm, ch):
    for pb in arm.pose.bones:
        pb.rotation_mode = 'QUATERNION'
        pb.location = (0, 0, 0)
        pb.rotation_quaternion = (1, 0, 0, 0)
        pb.scale = (1, 1, 1)

    act = make_action(arm, 'hop')
    root = arm.pose.bones[ch['root']]
    root_m3 = root.bone.matrix_local.to_3x3().inverted()
    legs = (arm.pose.bones[ch['left_leg'][0]], arm.pose.bones[ch['right_leg'][0]])
    tail = [arm.pose.bones[n] for n in ch['tail']]
    spine = [arm.pose.bones[n] for n in ch['spine']]

    last = HOP_FRAMES + 1  # frame 49 repeats frame 1
    for f in range(1, last + 1):
        t = (f - 1) / float(HOP_FRAMES)  # 0..1 over the loop

        root.location = root_m3 @ Vector((0.0, 0.0, hop_root_z(f)))
        _key(root, 'location', f)

        swing = math.radians(LEG_SWING_DEG) * math.sin(2 * math.pi * t)
        for pb, sign in zip(legs, (1.0, -1.0)):
            pb.rotation_quaternion = _basis_rot(pb, 'X', sign * swing)
            _key(pb, 'rotation_quaternion', f)

        for i, pb in enumerate(tail):
            sway = math.radians(TAIL_SWAY_DEG) * math.sin(2 * math.pi * 2 * t - i * 0.30)
            whip = math.radians(TAIL_WHIP_DEG) * math.sin(2 * math.pi * t - i * 0.25)
            q = _basis_rot(pb, 'Z', sway) @ _basis_rot(pb, 'X', whip)
            pb.rotation_quaternion = q
            _key(pb, 'rotation_quaternion', f)

        for i, pb in enumerate(spine):
            sway = math.radians(SPINE_SWAY_DEG) * math.sin(2 * math.pi * t - i * 0.20)
            pb.rotation_quaternion = _basis_rot(pb, 'Z', sway)
            _key(pb, 'rotation_quaternion', f)

    for fc in act.fcurves:
        for kp in fc.keyframe_points:
            kp.interpolation = 'BEZIER'
    return act


def author_idle(arm, ch):
    for pb in arm.pose.bones:
        pb.location = (0, 0, 0)
        pb.rotation_quaternion = (1, 0, 0, 0)
        pb.scale = (1, 1, 1)
    act = make_action(arm, 'idle')
    body = arm.pose.bones[ch['body']]
    for f in range(1, IDLE_FRAMES + 2):  # frame 25 repeats frame 1
        t = (f - 1) / float(IDLE_FRAMES)
        s = 1.0 + BREATH_SCALE * math.sin(2 * math.pi * t)
        body.scale = (s, s, s)
        _key(body, 'scale', f)
    for fc in act.fcurves:
        for kp in fc.keyframe_points:
            kp.interpolation = 'BEZIER'
    return act


# -------------------------------------------------------------- proof strip


def render_strip(arm, mesh, path, frames=CHECK_FRAMES, px=256, samples=8):
    scene = bpy.context.scene
    scene.render.engine = 'CYCLES'
    scene.cycles.device = 'CPU'
    scene.cycles.samples = samples
    scene.cycles.use_denoising = False
    scene.render.resolution_x = px
    scene.render.resolution_y = px
    scene.render.resolution_percentage = 100
    scene.render.film_transparent = False
    scene.render.image_settings.file_format = 'PNG'
    scene.render.image_settings.color_mode = 'RGB'

    world = bpy.data.worlds.new('strip')
    world.use_nodes = True
    world.node_tree.nodes['Background'].inputs[0].default_value = (0.35, 0.42, 0.5, 1)
    world.node_tree.nodes['Background'].inputs[1].default_value = 1.6
    scene.world = world

    cam_d = bpy.data.cameras.new('strip_cam')
    cam = bpy.data.objects.new('strip_cam', cam_d)
    scene.collection.objects.link(cam)
    target = Vector((-0.10, 0.10, 0.24))  # whole creature, tail included
    cam.location = Vector((-0.78, -0.92, 0.62))
    d = target - cam.location
    cam.rotation_mode = 'XYZ'
    cam.rotation_euler = d.to_track_quat('-Z', 'Y').to_euler()
    scene.camera = cam

    sun_d = bpy.data.lights.new('strip_sun', 'SUN')
    sun_d.energy = 4.0
    sun = bpy.data.objects.new('strip_sun', sun_d)
    sun.rotation_euler = (math.radians(55), 0, math.radians(35))
    scene.collection.objects.link(sun)

    import numpy as np

    tiles = []
    for f in frames:
        scene.frame_set(f)
        fd, tmp = tempfile.mkstemp(prefix='pufferball_strip_%02d_' % f, suffix='.png')
        os.close(fd)
        scene.render.filepath = tmp
        bpy.ops.render.render(write_still=True)
        img = bpy.data.images.load(tmp)
        buf = np.empty(len(img.pixels), dtype=np.float32)
        img.pixels.foreach_get(buf)
        tiles.append(buf.reshape(img.size[1], img.size[0], img.channels))
        bpy.data.images.remove(img)
        os.remove(tmp)

    strip = np.concatenate(tiles, axis=1)
    out = bpy.data.images.new('strip', width=strip.shape[1], height=strip.shape[0], alpha=(strip.shape[2] == 4))
    out.pixels.foreach_set(strip.ravel())
    out.filepath_raw = path
    out.file_format = 'PNG'
    out.save()
    bpy.data.images.remove(out)

    bpy.data.objects.remove(cam, do_unlink=True)
    bpy.data.objects.remove(sun, do_unlink=True)
    scene.frame_set(1)
    return path


# ------------------------------------------------------------------- build


def build():
    t0 = time.time()
    os.makedirs(OUT_DIR, exist_ok=True)
    arm, mesh, lo, hi = import_source()
    bone_names = [b.name for b in arm.data.bones]
    _log('%d bones: %s' % (len(bone_names), ', '.join(bone_names)))
    if not (len(bone_names) == 59):
        raise RuntimeError('expected 59 bones, got %d' % len(bone_names))

    ch = derive_chains(arm)
    _log('chains: %s' % json.dumps(ch))
    joint_map = build_joint_map(ch)

    scene = bpy.context.scene
    scene.render.fps = FPS
    scene.frame_start = 1
    scene.frame_end = HOP_FRAMES

    author_idle(arm, ch)
    hop = author_hop(arm, ch)
    arm.animation_data.action = hop  # 'motion' = hop by default

    arm['actor_name'] = ACTOR_NAME
    arm['actor_height_m'] = ACTOR_HEIGHT_M
    arm['motion_id'] = DEFAULT_MOTION
    arm['mapping'] = 'creature'
    arm['joint_map'] = json.dumps(joint_map, sort_keys=True)
    arm['actor_motions'] = ['hop', 'idle']
    arm['actor_fps'] = FPS
    arm['actor_frames'] = HOP_FRAMES

    render_strip(arm, mesh, OUT_STRIP)
    _log('strip -> %s' % OUT_STRIP)

    # no .blend1 backups: the disk is tight and this file is rebuildable
    bpy.context.preferences.filepaths.save_version = 0
    bpy.ops.wm.save_as_mainfile(filepath=OUT_BLEND, compress=True)
    _log('blend -> %s (%.1f MB)' % (OUT_BLEND, os.path.getsize(OUT_BLEND) / 1e6))

    meta = {
        'name': ACTOR_NAME,
        'height_m': ACTOR_HEIGHT_M,
        'mapping': 'creature',
        'joint_map': joint_map,
        'mapped_joints': AJ.mapped_names(joint_map),
        'motions': ['hop', 'idle'],
        'motion_default': DEFAULT_MOTION,
        'frames': HOP_FRAMES,
        'idle_frames': IDLE_FRAMES,
        'fps': FPS,
        'blend': os.path.relpath(OUT_BLEND, REPO),
        'strip': os.path.relpath(OUT_STRIP, REPO),
        'armature_object': arm.name,
        'mesh_object': mesh.name,
        'source_glb': SRC_GLB,
        'bone_names': bone_names,
        'chains': ch,
        'rest_bbox': {'min': [round(v, 4) for v in lo], 'max': [round(v, 4) for v in hi]},
        'conventions': 'faces -Y, +Z up, stands on z=0, metres',
        'built': time.strftime('%Y-%m-%dT%H:%M:%S'),
    }
    with open(OUT_JSON, 'w', encoding='utf-8') as fh:
        json.dump(meta, fh, indent=2, sort_keys=True)
        fh.write('\n')
    _log('json  -> %s' % OUT_JSON)
    _log('built in %.1f s' % (time.time() - t0))


# ------------------------------------------------------------------- check


def _eval_bbox_centre(mesh, dg):
    import numpy as np

    ob = mesh.evaluated_get(dg)
    me = ob.to_mesh()
    n = len(me.vertices)
    co = np.empty(n * 3, dtype=np.float64)
    me.vertices.foreach_get('co', co)
    co = co.reshape(n, 3)
    mw = np.array(ob.matrix_world.to_4x4()).reshape(4, 4)
    co = co @ mw[:3, :3].T + mw[:3, 3]
    lo, hi = co.min(axis=0), co.max(axis=0)
    ob.to_mesh_clear()
    return (lo + hi) * 0.5, lo, hi


def check():
    bpy.ops.wm.open_mainfile(filepath=OUT_BLEND)
    scene = bpy.context.scene
    arm = bpy.data.objects['pufferball_rig']
    mesh = bpy.data.objects['pufferball_mesh']
    meta = json.load(open(OUT_JSON, encoding='utf-8'))
    fails = []

    _zyg_log.info('--- pufferball actor check ---')
    _zyg_log.info('blend        %s (%.1f MB)' % (OUT_BLEND, os.path.getsize(OUT_BLEND) / 1e6))
    _zyg_log.info('fps          %d   frame range %d..%d' % (scene.render.fps, scene.frame_start, scene.frame_end))
    _zyg_log.info('actions      %s' % sorted(a.name for a in bpy.data.actions))
    _zyg_log.info(
        'props        actor_name=%r actor_height_m=%s motion_id=%r mapping=%r'
        % (arm['actor_name'], arm['actor_height_m'], arm['motion_id'], arm['mapping'])
    )
    _zyg_log.info('active action %r' % arm.animation_data.action.name)

    for want in ('hop', 'idle'):
        if want not in bpy.data.actions:
            fails.append('action %r missing from the .blend' % want)
    if arm.animation_data.action.name != DEFAULT_MOTION:
        fails.append('default motion is %r, expected %r' % (arm.animation_data.action.name, DEFAULT_MOTION))

    root_name = meta['chains']['root']
    dg = bpy.context.evaluated_depsgraph_get()
    rows = {}
    for f in CHECK_FRAMES:
        scene.frame_set(f)
        dg.update()
        rz = (arm.matrix_world @ arm.pose.bones[root_name].head).z
        centre, lo, hi = _eval_bbox_centre(mesh, dg)
        js = AJ.joints33(arm)
        rows[f] = {'root_z': rz, 'centre': centre, 'joints': js}
        _zyg_log.info(
            'frame %-3d root_z(%s) = %+0.4f m   mesh bbox centre = '
            '(%+0.4f, %+0.4f, %+0.4f)' % (f, root_name, rz, centre[0], centre[1], centre[2])
        )

    zs = [rows[f]['root_z'] for f in CHECK_FRAMES]
    spread = max(zs) - min(zs)
    pairs = [(CHECK_FRAMES[i], CHECK_FRAMES[j], abs(zs[i] - zs[j])) for i in range(3) for j in range(i + 1, 3)]
    _zyg_log.info('root z spread over frames %s = %.4f m   (need > 0.03)' % (list(CHECK_FRAMES), spread))
    for a, b, d in pairs:
        _zyg_log.info('   |z(f%d) - z(f%d)| = %.4f m' % (a, b, d))
    if spread <= 0.03:
        fails.append('root z spread %.4f m <= 0.03 m' % spread)
    for a, b, d in pairs:
        if d <= 0.03:
            fails.append('|z(f%d)-z(f%d)| = %.4f m <= 0.03 m' % (a, b, d))

    # the nose must sit in front of the body (more negative Y)
    scene.frame_set(1)
    dg.update()
    js = rows[1]['joints']
    nose = js[AJ.POSE_INDEX['nose']]
    centre = rows[1]['centre']
    ahead = float(centre[1]) - nose[1]
    _zyg_log.info(
        'nose = (%+0.4f, %+0.4f, %+0.4f) present=%s ; body centre Y = %+0.4f ; '
        'nose is %.4f m in front  (need > 0.08)' % (nose[0], nose[1], nose[2], nose[3], centre[1], ahead)
    )
    if not nose[3]:
        fails.append('nose joint not resolved')
    if ahead <= 0.08:
        fails.append('nose only %.4f m in front of the body centre' % ahead)

    present = [n for n, j in zip(AJ.POSE_NAMES, js) if j[3]]
    _zyg_log.info('joints33 -> %d entries, %d present: %s' % (len(js), len(present), ', '.join(present)))
    if len(js) != 33:
        fails.append('joints33 returned %d entries' % len(js))
    if len(present) < 10:
        fails.append('only %d joints present, need >= 10' % len(present))

    # the skinned mesh must follow the root, not just the armature object
    d_root = rows[24]['root_z'] - rows[1]['root_z']
    d_mesh = float(rows[24]['centre'][2] - rows[1]['centre'][2])
    _zyg_log.info(
        'mesh follows armature: d(root z) f1->f24 = %+0.4f m, d(mesh bbox centre z) = %+0.4f m' % (d_root, d_mesh)
    )
    if d_root * d_mesh <= 0 or abs(d_mesh) < 0.02:
        fails.append('mesh bbox centre did not move with the root (d_root=%+0.4f d_mesh=%+0.4f)' % (d_root, d_mesh))

    # idle really breathes
    arm.animation_data.action = bpy.data.actions['idle']
    body = meta['chains']['body']
    ss = []
    for f in (1, 7, 13):
        scene.frame_set(f)
        dg.update()
        ss.append(arm.pose.bones[body].scale.x)
    _zyg_log.info('idle breathing on %s: scale at f1/f7/f13 = %.4f / %.4f / %.4f' % (body, ss[0], ss[1], ss[2]))
    if abs(max(ss) - min(ss)) < 0.01:
        fails.append('idle breathing amplitude too small: %r' % ss)
    arm.animation_data.action = bpy.data.actions[DEFAULT_MOTION]

    for p in (OUT_BLEND, OUT_JSON, OUT_STRIP):
        ok = os.path.isfile(p)
        _zyg_log.info(
            '%-6s %s %s'
            % ('exists' if ok else 'MISSING', os.path.relpath(p, REPO), '(%d bytes)' % os.path.getsize(p) if ok else '')
        )
        if not ok:
            fails.append('missing output %s' % p)

    if fails:
        _zyg_log.info('--check FAIL')
        for f in fails:
            _zyg_log.info('  ! %s' % f)
        sys.exit(1)
    _zyg_log.info('--check pass')


if __name__ == '__main__':
    argv = sys.argv[sys.argv.index('--') + 1 :] if '--' in sys.argv else []
    if '--check' in argv:
        check()
    else:
        build()
