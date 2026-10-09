# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

import json
import os
import sys
import time

import bpy
from mathutils import Vector

from zyg_workflows.blender_scripts.proxy_actor.args_scene import (
    age_macro,
    clear_scene,
    find_clip,
    load_library,
    parse_args,
    standing_height,
)
from zyg_workflows.blender_scripts.proxy_actor.body import (
    add_rig,
    bound_arm_chain,
    bound_clavicles,
    build_body,
    load_base_body,
    strip_helpers,
)
from zyg_workflows.blender_scripts.proxy_actor.constants import (
    ALIGN_BONES,
    BONE_ALIAS,
    MOTION_ROOT,
    RETARGET_NOTE,
)
from zyg_workflows.blender_scripts.proxy_actor.fit import fit_rig, load_fit_spec, scale_actor
from zyg_workflows.blender_scripts.proxy_actor.motion import (
    align_rest,
    face_minus_y,
    ground,
    hierarchy_order,
    import_bvh,
    retarget,
    sample_bvh,
)
from zyg_workflows.blender_scripts.proxy_actor.output import make_collection, render_strip, run_checks

from zyg_workflows.blender_scripts import motion_authored as MA
from zyg_workflows.blender_scripts import skeleton_bind

import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)

# ----------------------------------------------------------------------- main


def skeleton_meta(skel):
    """The sidecar's 'skeleton' entry — counted on the mesh as it ships, or None."""
    if skel is None:
        return None
    skel.data.calc_loop_triangles()
    return {
        'vertices': len(skel.data.vertices),
        'triangles': len(skel.data.loop_triangles),
        'pieces': len(json.loads(skel['pieces'])),
        'tuck_push': skeleton_bind.LAST_FIT.get('tuck_push'),
        # what it took to keep this skeleton inside THIS body: the per-band
        # depth field and the clearance it reached, so a chest that reads wrong
        # can be read off the sidecar instead of rebuilt to find out
        'tuck': skeleton_bind.LAST_FIT.get('tuck'),
        'source': skel['source'],
    }


def build(args):
    lib = load_library()
    clip = find_clip(lib, args.motion)
    authored = MA.is_authored(clip['id'])
    bvh_path = None if authored else os.path.join(MOTION_ROOT, clip['file'])
    scene = bpy.context.scene
    scene.render.fps = int(args.fps or round(clip['fps']))
    scene.render.fps_base = 1.0

    clear_scene()
    t0 = time.time()
    del skeleton_bind.EXTRA_MESHES[:]  # clear_scene() freed any earlier one
    skel = None  # MPFB bodies get no skeleton
    clav = armw = None  # the weight bounds are base-body only
    if args.body == 'base':
        body, arm, base_id = load_base_body(args)
        verts, groups = len(body.data.vertices), len(body.vertex_groups)
        _zyg_log.info(
            '[proxy] base body %r: %d verts, %d groups, %d bones' % (base_id, verts, groups, len(arm.data.bones))
        )
        clav = bound_clavicles(body, arm)
        _zyg_log.info('[proxy] clavicle weights bounded: %s' % clav)
        armw = bound_arm_chain(body, arm)
        _zyg_log.info('[proxy] arm-chain weights bounded: %s' % armw)
    else:
        base_id = None
        body = build_body(args)
        arm = add_rig(body, args.name)
        verts, groups = strip_helpers(body)
    bpy.context.view_layer.update()

    fit = None
    if args.fit:
        spec, want = load_fit_spec(args.fit)
        fit = fit_rig(arm, body, want)
        fit['spec'] = args.fit
        fit['schema'] = spec.get('schema')
        fit['spec_height_m'] = spec.get('height_m')

    raw_h = standing_height(body)
    factor = args.height / raw_h
    scale_actor(arm, body, factor)
    final_h = standing_height(body)
    hips_z = arm.data.bones['Hips'].head_local.z
    _zyg_log.info(
        '[proxy] body %d verts, %d groups, %.3f m -> x%.5f -> %.3f m, hips %.4f m'
        % (verts, groups, raw_h, factor, final_h, hips_z)
    )

    if authored:
        # No BVH, no retarget: the rest pose is left exactly as MPFB built it and
        # the action states each bone's world orientation directly.
        bvh_scale, aligned, missing, max_delta = None, {}, [], None
        frame_count = int(clip['frames'])
        scene.frame_start, scene.frame_end = 1, frame_count
        mapping = {b.name: b.name for b in arm.data.bones}
        action = MA.build_action(arm, clip['id'], fps=scene.render.fps)
        _zyg_log.info(
            '[proxy] authored action %r: %d frames @ %d fps (%.1fs)'
            % (action.name, frame_count, scene.render.fps, time.time() - t0)
        )
    else:
        src = import_bvh(bvh_path, global_scale=1.0)
        scene.frame_set(1)
        bpy.context.view_layer.update()
        bvh_hips_z = (src.matrix_world @ src.pose.bones['Hips'].matrix).translation.z
        bvh_scale = hips_z / bvh_hips_z
        src.scale = (bvh_scale, bvh_scale, bvh_scale)
        bpy.context.view_layer.update()
        _zyg_log.info(
            '[proxy] bvh hips %.4f units -> global_scale %.6f (clip height_units %s)'
            % (bvh_hips_z, bvh_scale, clip.get('height_units'))
        )

        mapping = {}
        for bone in arm.data.bones:
            src_name = BONE_ALIAS.get(bone.name, bone.name)
            if src_name in src.pose.bones:
                mapping[bone.name] = src_name
        missing = [b.name for b in arm.data.bones if b.name not in mapping]
        frame_count = int(round(src.animation_data.action.frame_range[1]))
        scene.frame_start, scene.frame_end = 1, frame_count
        _zyg_log.info(
            '[proxy] %d/%d bones mapped (unmapped: %s), %d frames @ %d fps'
            % (len(mapping), len(arm.data.bones), missing or 'none', frame_count, scene.render.fps)
        )

        aligned = align_rest(arm, body, src, mapping, ALIGN_BONES, args.body)
        _zyg_log.info('[proxy] rest aligned to BVH frame 1: %s' % aligned)

        samples = sample_bvh(src, sorted(set(mapping.values())), range(1, frame_count + 1))
        bpy.data.objects.remove(src, do_unlink=True)
        action, max_delta = retarget(arm, samples, mapping)
        _zyg_log.info(
            '[proxy] baked action %r, largest bone delta %.1f deg (%.1fs)' % (action.name, max_delta, time.time() - t0)
        )

    # ---- the anatomical skeleton, fitted to the rest pose that will STAND ---
    # It used to be fitted right after the base body was appended, which is
    # before the bone-length fit, the height scale and align_rest's bake. Every
    # one of those moves the SKIN -- align_rest turns the arms 58 deg and the
    # legs 9-16 deg, and the chest skin is weighted to the clavicles, so it
    # pulls in by millimetres -- while the skeleton, rigid at weight 1.0 in one
    # group, rode along unchanged. A ribcage tucked inside the A-pose chest was
    # then 7 mm outside the chest the actor actually stands in, which is what
    # the operator saw come through it. Fitted here, the skeleton measures the
    # final body: the same reason the tuck exists at all.
    if args.body == 'base':
        skel = skeleton_bind.attach_skeleton(arm, body)
        _zyg_log.info(
            '[proxy] skeleton %d verts, %d pieces' % (len(skel.data.vertices), skeleton_bind.LAST_FIT['pieces'])
        )

    # A capture does not start in a T-pose, so motion_capture.py prepends one
    # reference frame for align_rest/retarget/bvh_scale to work from. That frame
    # is not part of the performance: the playable motion starts at frame 2.
    rest_frame = int(clip.get('rest_frame') or 0)
    first_frame = rest_frame + 1 if rest_frame else 1
    scene.frame_start = first_frame

    theta = face_minus_y(arm)
    # An authored action carries its own vertical shape (the flight bob, the
    # seated hold); a per-frame ground lock would flatten it, so the default
    # 'auto' means OFF there.
    lock_mode = 'off' if (authored and args.ground_lock == 'auto') else args.ground_lock
    offset, spread, locked = ground(arm, body, range(first_frame, frame_count + 1), lock_mode)
    _zyg_log.info(
        '[proxy] facing correction %.2f deg, ground offset %+.4f m, half-spread %.4f m, lock=%s'
        % (theta, offset, spread, locked)
    )

    root = bpy.data.objects.new('actor_root', None)
    root.empty_display_type = 'PLAIN_AXES'
    root.empty_display_size = 0.5
    bpy.context.scene.collection.objects.link(root)
    arm.parent = root
    arm.matrix_parent_inverse = root.matrix_world.inverted()
    make_collection('actor', [root, arm, body] + ([skel] if skel else []))

    arm['actor_name'] = args.name
    arm['actor_height_m'] = round(final_h, 4)
    arm['motion_id'] = clip['id']
    arm['mapping'] = 'cmu_mb'
    arm['root_offset_z'] = MA.root_offset_z(clip['id'], final_h) if authored else 0.0

    # counted before the save: orphans_purge below may invalidate the reference
    skel_meta = skeleton_meta(skel)

    checks = run_checks(body, arm, frame_count)
    checks['name'] = args.name
    if authored:
        checks['authored'] = MA.measure(arm, clip['id'])
    scene.frame_set(first_frame)

    out_dir = os.path.join(args.out, args.name)
    os.makedirs(out_dir, exist_ok=True)
    blend_path = os.path.join(out_dir, args.name + '.blend')
    try:
        bpy.ops.outliner.orphans_purge(do_local_ids=True, do_linked_ids=True, do_recursive=True)
    except Exception as exc:  # noqa: BLE001
        _zyg_log.info('[proxy] orphan purge skipped: %r' % (exc,))
    bpy.ops.wm.save_as_mainfile(filepath=blend_path, compress=True)
    size_mb = os.path.getsize(blend_path) / 1e6

    meta = {
        'name': args.name,
        'body': args.body,
        'base_body_id': base_id,
        'fit': fit,
        'height_m': round(final_h, 4),
        'motion': clip['id'],
        'frames': frame_count,
        'rest_frame': rest_frame or None,
        'fps': scene.render.fps,
        'bones': hierarchy_order(arm),
        'mapping': 'cmu_mb',
        'motion_source': 'authored' if authored else 'mocap',
        'root_offset_z': arm['root_offset_z'],
        'gender': args.gender,
        'age_years': args.age,
        'age_macro': round(age_macro(args.age), 4),
        'mesh_vertices': len(body.data.vertices),
        'clavicle_bound': clav,
        'arm_chain_bound': armw,
        'skeleton': skel_meta,
        'retarget': None if authored else RETARGET_NOTE,
        'bvh_global_scale': None if authored else round(bvh_scale, 6),
        'rest_aligned_deg': aligned,
        'ground_offset_m': round(offset, 4),
        'ground_locked': locked,
        'unmapped_bones': missing,
        'blend_mb': round(size_mb, 2),
        'source': clip.get('file') or clip.get('source'),
        'licence': clip['licence'] if authored else lib.get('licence'),
        'built': time.strftime('%Y-%m-%d %H:%M:%S'),
        'checks': checks,
    }
    if authored and 'seat_offset' in MA.spec(clip['id']):
        meta['seat_offset'] = dict(MA.spec(clip['id'])['seat_offset'])
        meta['vehicle_kind'] = MA.spec(clip['id'])['vehicle_kind']
    with open(os.path.join(out_dir, args.name + '.json'), 'w', encoding='utf-8') as fh:
        json.dump(meta, fh, indent=1)

    if not args.no_strip:
        strip_frames = [first_frame, checks['mid_frame'], frame_count]
        render_strip(body, arm, strip_frames, os.path.join(out_dir, args.name + '_strip.png'), final_h)

    _zyg_log.info('[proxy] wrote %s (%.1f MB) in %.1fs' % (blend_path, size_mb, time.time() - t0))
    return checks


def check_blend(path):
    """Re-open a saved .blend and measure it, structure included."""
    bpy.ops.wm.open_mainfile(filepath=path)
    arm = next(o for o in bpy.data.objects if o.type == 'ARMATURE')
    body = next(o for o in bpy.data.objects if o.type == 'MESH')
    frames = int(bpy.context.scene.frame_end)
    checks = run_checks(body, arm, frames)
    checks['name'] = arm.get('actor_name', os.path.basename(path))

    coll = bpy.data.collections.get('actor')
    root = bpy.data.objects.get('actor_root')
    bpy.context.scene.frame_set(1)
    bpy.context.view_layer.update()
    left = (arm.matrix_world @ arm.pose.bones['LeftUpLeg'].head) - (
        arm.matrix_world @ arm.pose.bones['RightUpLeg'].head
    )
    left.z = 0.0
    facing = left.normalized().cross(Vector((0.0, 0.0, 1.0)))
    checks['structure'] = {
        'collection_actor': coll is not None,
        'collection_objects': sorted(o.name for o in coll.objects) if coll else [],
        'actor_root_at_origin': bool(root is not None and root.matrix_world.translation.length < 1e-6),
        'armature_parent': arm.parent.name if arm.parent else None,
        'mesh_parent': body.parent.name if body.parent else None,
        'action': arm.animation_data.action.name if arm.animation_data else None,
        'props': {k: arm.get(k) for k in ('actor_name', 'actor_height_m', 'motion_id', 'mapping', 'root_offset_z')},
        'facing_at_frame1': [round(v, 3) for v in facing],
        'mesh_vertices': len(body.data.vertices),
        'bones': len(arm.data.bones),
        'blend_mb': round(os.path.getsize(path) / 1e6, 2),
    }
    motion_id = arm.get('motion_id')
    if MA.is_authored(motion_id):
        checks['authored'] = MA.measure(arm, motion_id)
    return checks


def main():
    argv = sys.argv[sys.argv.index('--') + 1 :] if '--' in sys.argv else []
    args = parse_args(argv)

    if args.list_motions:
        lib = load_library()
        for source, records in (('mocap', lib['clips']), ('authored', lib.get('authored', []))):
            for clip in records:
                print(
                    '%-12s %-9s %-8s %5d frames @ %3d fps  %s'
                    % (clip['id'], source, clip['label'], clip['frames'], clip['fps'], clip.get('index_text', ''))
                )
        return

    if args.check is not None and args.check != '':
        checks = check_blend(args.check)
    else:
        if not args.name:
            raise SystemExit('need --name')
        checks = build(args)

    print('CHECKS ' + json.dumps(checks, sort_keys=True))
