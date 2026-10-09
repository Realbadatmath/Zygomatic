# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Render a gesture's keys from a saved character.blend.

Headless Blender only:

    flock /tmp/claude-1000/arch_ext_blender.lock /usr/local/bin/blender -b \
        output/char2d/_bench_mika/character.blend \
        --python blender_scripts/char2d_render_pose.py -- \
        --gesture data/char2d/gestures/01_open_palm.json \
        --views front,front45R,profileR --out output/char2d/_gesture_bench \
        [--keys 1,2,3] [--res 768x1152]

The gesture is validated with char2d_poses.validate() first (a bad gesture is
never rendered), then every key is applied over the idle pose and rendered to
OUT/<gesture name>/<view>_k<n>.png with the camera, cel materials and Freestyle
ink of char2d_build.py.  The framing is solved once, on the idle pose, so the
keys of a strip line up pixel for pixel.
"""

import argparse
import json
import logging as _zyg_logging
import os
import sys

import bpy

_HERE = os.path.dirname(os.path.abspath(__file__))
_CREWS = os.path.dirname(_HERE)
for _path in (_HERE, _CREWS):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import char2d_build as B  # noqa: E402  (needs the sys.path above)
from zyg_workflows import char2d_poses as P  # noqa: E402

_zyg_log = _zyg_logging.getLogger(__name__)


def parse_args():
    argv = sys.argv[sys.argv.index('--') + 1 :] if '--' in sys.argv else []
    p = argparse.ArgumentParser(prog='char2d_render_pose.py')
    p.add_argument('--gesture', required=True)
    p.add_argument('--out', required=True)
    p.add_argument('--views', default='front,front45R,profileR')
    p.add_argument('--res', default='768x1152')
    p.add_argument('--keys', default=None, help='1-based key numbers, e.g. 1,3')
    args = p.parse_args(argv)
    args.view_list = [v.strip() for v in args.views.split(',') if v.strip()]
    for view in args.view_list:
        if view not in B.YAW:
            p.error('unknown view %r; known: %s' % (view, ', '.join(B.YAW)))
    try:
        wide, high = args.res.lower().split('x')
        args.res_wh = (int(wide), int(high))
    except ValueError:
        p.error('--res must look like 768x1152')
    if args.keys:
        try:
            args.key_list = [int(k) for k in args.keys.split(',') if k.strip()]
        except ValueError:
            p.error('--keys must be 1-based integers, e.g. 1,2,3')
    else:
        args.key_list = None
    return args


def load_gesture(path):
    with open(path, 'r', encoding='utf-8') as fh:
        gesture = json.load(fh)
    errors = P.validate(gesture)
    if errors:
        for message in errors:
            _zyg_log.info('GESTURE ERROR %s' % message)
        raise SystemExit('%s is not a valid gesture (%d errors)' % (path, len(errors)))
    return gesture


def find_rig():
    arm = bpy.data.objects.get('Human.rig')
    if arm is None:
        arms = [o for o in bpy.data.objects if o.type == 'ARMATURE']
        if not arms:
            raise SystemExit('no armature in the .blend')
        arm = arms[0]
    return arm


def find_body():
    body = bpy.data.objects.get('Human')
    if body is None or body.type != 'MESH':
        meshes = [o for o in bpy.data.objects if o.type == 'MESH']
        if not meshes:
            raise SystemExit('no mesh in the .blend')
        body = max(meshes, key=lambda o: len(o.data.vertices))
    return body


def get_camera():
    cam = bpy.context.scene.camera
    if cam is None:
        cam = bpy.data.objects.get('c2d_cam')
        if cam is not None:
            bpy.context.scene.camera = cam
    if cam is None:
        cam = B.make_camera()
    return cam


def main():
    args = parse_args()
    gesture = load_gesture(args.gesture)
    keys = gesture['keys']
    wanted = args.key_list or list(range(1, len(keys) + 1))
    for number in wanted:
        if not 1 <= number <= len(keys):
            raise SystemExit('--keys %d is outside 1..%d' % (number, len(keys)))

    out_dir = os.path.join(os.path.abspath(args.out), gesture['name'])
    os.makedirs(out_dir, exist_ok=True)

    arm = find_rig()
    body = find_body()
    cam = get_camera()
    scene = B.setup_render(args.res_wh)
    print(
        'SCENE rig=%s bones=%d body=%s verts=%d' % (arm.name, len(arm.data.bones), body.name, len(body.data.vertices))
    )

    # One framing for the whole gesture, solved on the idle pose.
    B.apply_idle(arm)
    posed, _flags = B.posed_body_points(body)
    dist, centre_z = B.frame_camera(posed, [B.YAW[v] for v in args.view_list])
    print('CAMERA dist=%.3f centre_z=%.3f res=%dx%d' % (dist, centre_z, args.res_wh[0], args.res_wh[1]))

    manifest = {
        'gesture': gesture['name'],
        'label': gesture.get('label'),
        'hands': gesture.get('hands'),
        'res': list(args.res_wh),
        'views': args.view_list,
        'keys': [],
    }
    for number in wanted:
        key = keys[number - 1]
        bones = key.get('bones') or {}
        B.apply_idle(arm)
        B.apply_bones(arm, bones)
        entry = {
            'n': number,
            'name': key['name'],
            'hold_frames': key.get('hold_frames'),
            'posed_bones': len(bones),
            'files': {},
        }
        for view in args.view_list:
            B.place_camera(cam, B.YAW[view], dist, centre_z)
            path = B.render_still(scene, os.path.join(out_dir, '%s_k%d.png' % (view, number)))
            entry['files'][view] = os.path.basename(path)
            print(
                'KEY %d %-8s %-9s -> %s bbox=%s'
                % (number, key['name'], view, os.path.basename(path), B.alpha_bbox(path))
            )
        manifest['keys'].append(entry)

    with open(os.path.join(out_dir, 'render.json'), 'w', encoding='utf-8') as fh:
        json.dump(manifest, fh, indent=2)
    print('DONE %s keys=%d views=%d -> %s' % (gesture['name'], len(wanted), len(args.view_list), out_dir))


if __name__ == '__main__':
    main()
