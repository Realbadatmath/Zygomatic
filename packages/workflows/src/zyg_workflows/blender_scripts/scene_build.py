#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""scene_build.py — build a shot's .blend: the city, its camera, and the VFX.

This is the bridge the operator asked for: "inject VFX Studio effects into a
Blender city".  It runs headless inside Blender and does, in one process:

  1. ``arch_blender_build.build()`` — the very builder the Architecture Studio
     drives, so the geometry is identical to what the studio renders.  It starts
     from ``read_factory_settings(use_empty=True)`` and saves the .blend itself,
     which is why it must run FIRST and why we save again at the end.
  2. the shot camera, baked one key per frame from ``scene_shot.camera_at``.
  3. a sun and sky (``render_offline_blender.place_sun`` / ``make_world``).
  4. every effect: its VDB sequence imported with
     ``vfx_volume_render.import_sequence``, shaded with that module's own
     ``build_material`` (the grid set is READ off the pack — a hardcoded
     ``density`` renders a fire pack black), measured with ``sequence_bounds``
     and then SCALED and PLACED at the shot's coordinates.
  5. an actors hook: a proxy .blend per actor if one exists yet.

Frames: the studio is Y-up, Blender is Z-up.  Every position goes through
``scene_shot.to_blender`` — (x, y, z) -> (x, -z, y) — and an effect's heading
``ry`` about the studio's vertical becomes a rotation about Blender's +Z.

    flock /tmp/claude-1000/arch_ext_blender.lock \
        blender -b --python blender_scripts/scene_build.py -- \
            --shot data/architecture/shots/fixture_house/shot.json [--probe]

Two headless Blenders at once SIGBUS the Bonsai add-on, hence the flock.

The extraction of a pack into ``f_%04d.vdb`` is NOT done here: the extractors
live in ``vfx_volume_preview``, which imports Pillow, and Blender's Python has
numpy but no PIL.  ``scene_effects.ensure_extracted`` is called as a subprocess
with the crews venv instead, or ``--extract-dir`` hands over a ready sequence.

The last stdout line is the contract: ``{"ok":true,"blend":…}`` or
``{"ok":false,"error":…}`` with exit 1 — the same shape as
``arch_blender_build.main``.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import subprocess
import sys
import traceback

try:  # only importable inside Blender; guarded so the
    import bpy  # module can be imported by a plain pytest run
    import mathutils  # (same trick as arch_server_ext/render_offline_blender.py)
except ImportError:
    bpy = mathutils = None
import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)


HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXT_DIR = os.path.join(HERE, 'arch_server_ext')
ACTORS_DIR = os.path.join(HERE, 'data', 'architecture', 'actors')
VENV_PY = os.path.join(os.path.dirname(HERE), '.venv', 'bin', 'python')

SENSOR_MM = 36.0  # vertical sensor fit, as in render_offline_blender
PROBE_W, PROBE_H = 256, 144
PROBE_SAMPLES = 4
PROBE_FRAME = 24

# the crews root goes in LAST so it ends up FIRST on sys.path: arch_server_ext
# holds a family module called scene_shot, and it must never shadow the contract
# module of the same name at the crews root.
for _p in (EXT_DIR, HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)


# --------------------------------------------------------------------------
# sequence sourcing
# --------------------------------------------------------------------------


def _count_seq(seq_dir):
    """Frame count of a ready ``f_%04d.vdb`` run — cache.json, else counted."""
    try:
        with open(os.path.join(seq_dir, 'cache.json'), 'r', encoding='utf-8') as fh:
            n = json.load(fh).get('n')
        if isinstance(n, int) and n > 0:
            return n
    except (OSError, ValueError, AttributeError) as _exc:
        _zyg_log.debug('VDB cache.json unreadable, counting the frames on disk: %s', _exc)
    n = 0
    while os.path.isfile(os.path.join(seq_dir, 'f_%04d.vdb' % n)):
        n += 1
    return n


def _ready_dir(root, pack):
    """``--extract-dir`` may be the sequence itself or a cache root of slugs."""
    if not root:
        return ''
    if os.path.isfile(os.path.join(root, 'f_0000.vdb')):
        return root
    from zyg_workflows import scene_effects as SE  # noqa: N814

    sub = os.path.join(root, SE.slug(pack))
    return sub if os.path.isfile(os.path.join(sub, 'f_0000.vdb')) else ''


def sequence_for(pack, extract_dir='', allow_big=False, max_frames=0):
    """``(seq_dir, n)`` for a pack — a ready directory, or the crews venv."""
    ready = _ready_dir(extract_dir, pack)
    if ready:
        n = _count_seq(ready)
        if n < 1:
            raise RuntimeError('--extract-dir %s holds no f_%%04d.vdb frames' % ready)
        return ready, n

    cmd = [VENV_PY, os.path.join(HERE, 'scene_effects.py'), '--pack', pack]
    if allow_big:
        cmd.append('--allow-big')
    if max_frames:
        cmd += ['--max-frames', str(int(max_frames))]
    if not os.path.isfile(VENV_PY):
        raise RuntimeError(
            'crews venv python not found at %s — extract the pack first and pass --extract-dir' % VENV_PY
        )
    _zyg_log.info('[scene] %s' % ' '.join(cmd))
    r = subprocess.run(cmd, capture_output=True, text=True)
    for ln in (r.stderr or '').splitlines():
        _zyg_log.info('[fx] %s' % ln)
    last = [ln for ln in (r.stdout or '').splitlines() if ln.strip().startswith('{')]
    if not last:
        raise RuntimeError(
            'scene_effects.py printed no JSON (rc=%d): %s' % (r.returncode, (r.stdout or r.stderr or '')[-300:])
        )
    rec = json.loads(last[-1])
    if not rec.get('ok'):
        raise RuntimeError('scene_effects.py: %s' % rec.get('error'))
    return rec['seq'], int(rec['n'])


# --------------------------------------------------------------------------
# scene furniture
# --------------------------------------------------------------------------


def set_timing(sc, shot):
    sc.frame_start = 1
    sc.frame_end = max(1, int(shot['frames']))
    fps = float(shot['fps'])
    rounded = int(round(fps))
    if abs(fps - rounded) < 1e-6:
        sc.render.fps, sc.render.fps_base = rounded, 1.0
    else:  # 23.976 and friends
        sc.render.fps, sc.render.fps_base = rounded, rounded / fps
    sc.render.resolution_x, sc.render.resolution_y = (int(shot['resolution'][0]), int(shot['resolution'][1]))
    sc.render.resolution_percentage = 100


def build_camera(sc, shot, SS, span):
    """One key per frame — the shot's camera path is linear between its keys and
    baking it removes any question of which interpolation Blender would pick."""
    cd = bpy.data.cameras.new('shot_cam')
    cam = bpy.data.objects.new('shot_cam', cd)
    sc.collection.objects.link(cam)
    sc.camera = cam
    cd.type = 'PERSP'
    cd.sensor_fit = 'VERTICAL'
    cd.sensor_height = SENSOR_MM
    cd.sensor_width = SENSOR_MM
    cd.clip_start = 0.02
    cd.clip_end = span * 20.0 + 5000.0
    # Quaternions, not Eulers: a baked Euler track can flip by 2*pi between two
    # frames of a pan and the camera spins through the shot.
    cam.rotation_mode = 'QUATERNION'

    for f in range(sc.frame_start, sc.frame_end + 1):
        k = SS.camera_at(shot, f)
        pos = mathutils.Vector(SS.to_blender(k['p']))
        tgt = mathutils.Vector(SS.to_blender(k['t']))
        back = pos - tgt  # a Blender camera looks down its -Z
        if back.length < 1e-6:
            back = mathutils.Vector((0.0, -1.0, 0.3))
        fov = min(160.0, max(4.0, float(k['fov'])))
        cam.location = pos
        cam.rotation_quaternion = back.to_track_quat('Z', 'Y')
        cd.lens = (SENSOR_MM / 2.0) / math.tan(math.radians(fov) / 2.0)
        cam.keyframe_insert('location', frame=f)
        cam.keyframe_insert('rotation_quaternion', frame=f)
        cd.keyframe_insert('lens', frame=f)
    for ad in (cam.animation_data, cd.animation_data):
        if ad and ad.action:
            for fc in ad.action.fcurves:
                for kp in fc.keyframe_points:
                    kp.interpolation = 'LINEAR'
    return cam, cd


# --------------------------------------------------------------------------
# effects
# --------------------------------------------------------------------------


def place_effect(sc, SS, VR, fx, seq_dir, n, coll, frames):
    """Import, shade, measure, scale and put the volume where the shot says.

    The scale is driven by HEIGHT: ``size_m`` is what the operator means by "a
    metre-and-a-half campfire", and the sequence's own bounds are what that has
    to be measured against, because a VDB's world units are the simulation's,
    not metres.  Bounds are taken BEFORE ``frame_offset`` is applied so frames
    1..n still map to files 0..n-1 while measuring.
    """
    before = {o.name for o in sc.objects if o.type == 'VOLUME'}
    VR.import_sequence(seq_dir, n)  # returns objects[0], not necessarily ours
    new = [o for o in sc.objects if o.type == 'VOLUME' and o.name not in before]
    if not new:
        raise RuntimeError('volume import produced no new object for %s' % fx['id'])
    ob = new[0]

    for c in list(ob.users_collection):
        c.objects.unlink(ob)
    coll.objects.link(ob)

    grids = VR.grid_names(ob)
    wiring = VR.build_material(ob, grids)

    ob.location = (0.0, 0.0, 0.0)
    ob.rotation_mode = 'XYZ'
    ob.rotation_euler = (0.0, 0.0, 0.0)
    ob.scale = (1.0, 1.0, 1.0)
    bpy.context.view_layer.update()
    lo, hi = VR.sequence_bounds(ob, n)

    height_units = max(1e-6, hi.z - lo.z)
    s = float(fx['size_m']) / height_units
    ry = math.radians(float(fx.get('ry', 0.0)))
    ob.scale = (s, s, s)
    ob.rotation_euler = (0.0, 0.0, ry)
    # Bottom-CENTRE of the sequence's union box is the anchor: an operator
    # places a campfire by where it stands on the ground, not by its centroid.
    anchor = mathutils.Vector(((lo.x + hi.x) * 0.5, (lo.y + hi.y) * 0.5, lo.z)) * s
    rot = mathutils.Matrix.Rotation(ry, 3, 'Z')
    ob.location = mathutils.Vector(SS.to_blender(fx['p'])) - (rot @ anchor)

    vol = ob.data
    start = int(fx.get('start_frame', 1))
    vol.frame_offset = -(start - 1)
    loop = bool(fx.get('loop', False))
    vol.sequence_mode = 'REPEAT' if (loop and frames > n) else 'CLIP'

    ob.name = 'fx %s' % fx['id']
    ob['shot_effect'] = fx['id']
    ob['shot_pack'] = fx['pack']
    bpy.context.view_layer.update()

    bbox = ((hi.x - lo.x) * s, (hi.y - lo.y) * s, (hi.z - lo.z) * s)
    return ob, {
        'id': fx['id'],
        'pack': fx['pack'],
        'n': n,
        'scale': round(s, 6),
        'bbox_m': [round(c, 4) for c in bbox],
        'p': [round(c, 4) for c in fx['p']],
        'loc': [round(c, 4) for c in ob.location],
        'ry': float(fx.get('ry', 0.0)),
        'start_frame': start,
        'frame_offset': vol.frame_offset,
        'sequence_mode': vol.sequence_mode,
        'grids': grids,
        'density': wiring['density'],
        'temperature': wiring['temperature'],
        'seq': seq_dir,
    }


# --------------------------------------------------------------------------
# actors (task 7 writes the proxy .blends; missing ones are a warning)
# --------------------------------------------------------------------------


def place_actor(sc, SS, shot, actor, coll):
    aid = actor['id']
    proxy = str(actor.get('proxy') or aid)
    path = os.path.join(ACTORS_DIR, proxy, '%s.blend' % proxy)
    if not os.path.isfile(path):
        _zyg_log.info('[scene] warning: no proxy .blend for actor %r at %s — skipped' % (aid, path))
        return None, {'id': aid, 'proxy': proxy, 'ok': False, 'reason': 'proxy blend missing', 'path': path}
    with bpy.data.libraries.load(path, link=False) as (src, dst):
        if 'actor' not in src.collections:
            raise RuntimeError(
                '%s has no collection named "actor" (has: %s)' % (path, ', '.join(src.collections) or 'none')
            )
        dst.collections = ['actor']
    src_coll = dst.collections[0]
    src_coll.name = 'actor_%s' % aid

    off = int(actor.get('start_frame', 1)) - 1
    shifted = set()
    if off:
        for ob in src_coll.all_objects:
            ad = ob.animation_data
            act = ad.action if ad else None
            if act is None or act.name in shifted:
                continue
            shifted.add(act.name)
            for fc in act.fcurves:
                for kp in fc.keyframe_points:
                    kp.co.x += off
                    kp.handle_left.x += off
                    kp.handle_right.x += off
                fc.update()

    inst = bpy.data.objects.new('actor %s' % aid, None)
    inst.instance_type = 'COLLECTION'
    inst.instance_collection = src_coll
    inst.rotation_mode = 'XYZ'
    coll.objects.link(inst)
    for f in range(sc.frame_start, sc.frame_end + 1):
        st = SS.actor_at(shot, actor, f)
        inst.location = SS.to_blender(st['p'])
        inst.rotation_euler = (0.0, 0.0, math.radians(float(st['ry'])))
        inst.keyframe_insert('location', frame=f)
        inst.keyframe_insert('rotation_euler', frame=f)
    if inst.animation_data and inst.animation_data.action:
        for fc in inst.animation_data.action.fcurves:
            for kp in fc.keyframe_points:
                kp.interpolation = 'LINEAR'
    return inst, {
        'id': aid,
        'proxy': proxy,
        'ok': True,
        'actions_shifted': len(shifted),
        'frame_offset': off,
        'objects': len(src_coll.all_objects),
    }


# --------------------------------------------------------------------------
# probe — a tiny CPU render that proves the effect is actually IN the picture
# --------------------------------------------------------------------------


def _luma(png):
    """Per-pixel luminance of a PNG on disk, rows bottom-up as Blender keeps
    them (which is also how ``world_to_camera_view``'s v runs)."""
    import numpy as np

    img = bpy.data.images.load(os.path.abspath(png))
    try:
        w, h = img.size
        buf = np.empty(w * h * img.channels, dtype=np.float32)
        img.pixels.foreach_get(buf)
        px = buf.reshape(h, w, img.channels)
        return (0.2126 * px[:, :, 0] + 0.7152 * px[:, :, 1] + 0.0722 * px[:, :, 2]), w, h
    finally:
        bpy.data.images.remove(img)


def probe(sc, cam, vol_obs, out_png, frame=PROBE_FRAME):
    """Render one small frame on the CPU and measure the effect in it.

    This is the only check that catches the failure this bridge is most likely
    to have: a volume that imported, shaded and saved perfectly and sits behind
    the camera, inside a wall, or a thousand units away.

    Two numbers, because one of them is not enough for every pack:

    ``ratio``  mean brightness inside the effect's projected box over the mean
        outside it.  That is the intended test and it is decisive for an
        EMISSIVE pack — one with a ``temperature`` grid, which
        ``vfx_volume_render.build_material`` wires to blackbody.  It is NOT
        decisive for a pack whose grids are only ``density``/``flames``
        (SmallCampfireVDB is one): that shades as grey smoke, and grey smoke in
        front of a sunlit grey wall barely moves the mean.
    ``delta``  the same frame is rendered twice, once with every volume set to
        ``hide_render`` and once without, at the same Cycles seed, and the mean
        |difference| inside the box is compared with the mean outside.  Only the
        pixels the volume actually covers change, so this proves the effect is
        in the picture AND where it is, whatever its grids.  The hidden pass is
        written to a scratch file and deleted.
    """
    import tempfile

    import numpy as np
    from bpy_extras.object_utils import world_to_camera_view

    frame = max(sc.frame_start, min(sc.frame_end, int(frame)))
    sc.render.engine = 'CYCLES'
    sc.cycles.device = 'CPU'  # a LIGHT task never takes the GPU
    sc.cycles.samples = PROBE_SAMPLES
    sc.cycles.use_adaptive_sampling = True
    sc.cycles.use_denoising = False
    sc.cycles.seed = 0  # the A/B pass must share the noise
    sc.cycles.use_animated_seed = False
    sc.render.resolution_x, sc.render.resolution_y = PROBE_W, PROBE_H
    sc.render.resolution_percentage = 100
    sc.render.image_settings.file_format = 'PNG'
    sc.render.image_settings.color_mode = 'RGB'
    sc.render.film_transparent = False
    sc.render.use_file_extension = False
    sc.frame_set(frame)

    base = None
    if vol_obs:
        fd, scratch = tempfile.mkstemp(prefix='probe-nofx-', suffix='.png')
        os.close(fd)
        try:
            for ob in vol_obs:
                ob.hide_render = True
            sc.render.filepath = scratch
            bpy.context.view_layer.update()
            bpy.ops.render.render(write_still=True)
            base = _luma(scratch)[0]
        finally:
            for ob in vol_obs:
                ob.hide_render = False
            if os.path.exists(scratch):
                os.unlink(scratch)

    sc.render.filepath = os.path.abspath(out_png)
    bpy.context.view_layer.update()
    bpy.ops.render.render(write_still=True)
    lum, w, h = _luma(out_png)
    diff = np.abs(lum - base) if base is not None else None

    dg = bpy.context.evaluated_depsgraph_get()
    out = []
    for ob in vol_obs:
        ev = ob.evaluated_get(dg)
        u0 = v0 = 1e9
        u1 = v1 = -1e9
        for c in ev.bound_box:
            co = world_to_camera_view(sc, cam, ev.matrix_world @ mathutils.Vector(c))
            if co.z <= 0.0:
                continue
            u0, u1 = min(u0, co.x), max(u1, co.x)
            v0, v1 = min(v0, co.y), max(v1, co.y)
        if u1 <= u0 or v1 <= v0:
            out.append(
                {'id': ob.get('shot_effect'), 'ok': False, 'reason': 'bbox does not project in front of the camera'}
            )
            continue
        x0 = max(0, min(w - 1, int(math.floor(u0 * w))))
        x1 = max(x0 + 1, min(w, int(math.ceil(u1 * w))))
        y0 = max(0, min(h - 1, int(math.floor(v0 * h))))
        y1 = max(y0 + 1, min(h, int(math.ceil(v1 * h))))
        mask = np.zeros((h, w), dtype=bool)
        mask[y0:y1, x0:x1] = True  # image rows run bottom-up, and so does v
        inside = float(lum[mask].mean())
        outside = float(lum[~mask].mean()) if (~mask).any() else 0.0
        rec = {
            'id': ob.get('shot_effect'),
            'ok': True,
            'frame': frame,
            'box_px': [x0, y0, x1, y1],
            'px_inside': int(mask.sum()),
            'px_outside': int((~mask).sum()),
            'mean_inside': round(inside, 5),
            'mean_outside': round(outside, 5),
            'ratio': round(inside / outside, 4) if outside > 1e-9 else None,
        }
        if diff is not None:
            d_in = float(diff[mask].mean())
            d_out = float(diff[~mask].mean()) if (~mask).any() else 0.0
            rec.update(
                {
                    'delta_inside': round(d_in, 6),
                    'delta_outside': round(d_out, 6),
                    'delta_ratio': round(d_in / d_out, 2) if d_out > 1e-9 else None,
                    'changed_px_inside': int((diff[mask] > 0.004).sum()),
                    'changed_px_outside': int((diff[~mask] > 0.004).sum()),
                }
            )
        out.append(rec)
    return {
        'png': os.path.abspath(out_png),
        'frame': frame,
        'width': w,
        'height': h,
        'samples': PROBE_SAMPLES,
        'device': sc.cycles.device,
        'effects': out,
    }


# --------------------------------------------------------------------------


def main():
    argv = sys.argv[sys.argv.index('--') + 1 :] if '--' in sys.argv else []
    ap = argparse.ArgumentParser(prog='scene_build.py')
    ap.add_argument('--shot', required=True, help='a zyg.scene_shot/1 shot.json')
    ap.add_argument('--no-effects', action='store_true', help='geometry + camera only')
    ap.add_argument('--extract-dir', default='', help='a ready f_%%04d.vdb sequence, or a cache root of pack slugs')
    ap.add_argument('--allow-big', action='store_true', help='let scene_effects extract an archive over its size limit')
    ap.add_argument('--max-frames', type=int, default=0, help='stride a long sequence down on extraction')
    ap.add_argument('--probe', action='store_true', help='render one tiny CPU frame and measure the effect in it')
    ap.add_argument('--probe-frame', type=int, default=PROBE_FRAME)
    ap.add_argument('--out', default='', help='override the .blend path')
    args = ap.parse_args(argv)

    from zyg_workflows import scene_shot as SS  # noqa: N814
    from zyg_workflows import arch_blender_build as ABB  # noqa: N814
    import render_offline_blender as RO  # noqa: N814
    from zyg_workflows import vfx_volume_render as VR  # noqa: N814

    shot = SS.resolve_positions(SS.load(os.path.abspath(args.shot)))
    sdir = SS.shot_dir(shot)
    os.makedirs(sdir, exist_ok=True)
    blend = os.path.abspath(args.out or os.path.join(sdir, 'scene.blend'))

    with open(shot['drawing'], 'r', encoding='utf-8') as fh:
        drawing = json.load(fh)
    info = ABB.build(drawing, blend, None)  # wipes the file and saves it itself
    sc = bpy.context.scene

    set_timing(sc, shot)
    lo, hi, ctr, span = RO._scene_bounds(sc)
    cam, cd = build_camera(sc, shot, SS, span)
    sv = RO.place_sun(sc, ctr, span)
    RO.make_world(sc)
    RO.set_look(sc)

    fx_coll = bpy.data.collections.new('effects')
    sc.collection.children.link(fx_coll)
    vol_obs = []
    effects = []
    if not args.no_effects:
        for fx in shot.get('effects', []):
            seq_dir, n = sequence_for(
                fx['pack'], args.extract_dir, allow_big=args.allow_big, max_frames=args.max_frames
            )
            ob, rec = place_effect(sc, SS, VR, fx, seq_dir, n, fx_coll, sc.frame_end)
            vol_obs.append(ob)
            effects.append(rec)
            print(
                '[scene] fx %s: %d frames, scale %.5f, bbox %s m, at %s'
                % (rec['id'], n, rec['scale'], rec['bbox_m'], rec['loc']),
                flush=True,
            )

    ac_coll = bpy.data.collections.new('actors')
    sc.collection.children.link(ac_coll)
    actors = []
    for actor in shot.get('actors', []):
        _inst, arec = place_actor(sc, SS, shot, actor, ac_coll)
        actors.append(arec)

    sc.frame_set(sc.frame_start)
    bpy.context.view_layer.update()
    bpy.ops.wm.save_as_mainfile(filepath=blend)

    result = {
        'ok': True,
        'blend': blend,
        'bytes': os.path.getsize(blend),
        'objects': len(sc.objects),
        'built': info.get('objects'),
        'skipped': info.get('skipped'),
        'frames': [sc.frame_start, sc.frame_end],
        'fps': sc.render.fps,
        'cam_loc': [round(c, 3) for c in cam.location],
        'sun_dir': [round(c, 4) for c in sv],
        'effects': effects,
        'actors': actors,
    }

    if args.probe:
        result['probe'] = probe(sc, cam, vol_obs, os.path.join(sdir, 'probe.png'), args.probe_frame)
        print('[scene] probe: %s' % json.dumps(result['probe']), flush=True)

    print(json.dumps(result), flush=True)


if __name__ == '__main__':
    try:
        main()
    except Exception as e:  # noqa: BLE001 — one JSON line is the contract
        traceback.print_exc()
        print(json.dumps({'ok': False, 'error': '%s: %s' % (type(e).__name__, e)}), flush=True)
        sys.exit(1)
