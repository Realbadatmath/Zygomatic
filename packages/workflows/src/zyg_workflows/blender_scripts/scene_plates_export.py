#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""scene_plates_export.py — a built shot .blend -> the raw plates the video engines need.

This is the bridge between ``scene_build.py`` (which makes the city, the camera, the
effects and the actors) and ``scene_plates.py`` (which turns raw plates into the
VACE / Wan-Animate plate sets).  It runs headless inside Blender:

    flock /tmp/claude-1000/arch_ext_blender.lock \
        blender -b <shot_dir>/scene.blend --python blender_scripts/scene_plates_export.py -- \
            --shot data/architecture/shots/<id>/shot.json [--frames 1:49] [--cpu 1]

WHAT IT WRITES  (``<shot_dir>/plates_raw/``, the contract ``scene_plates.build`` reads)

    beauty_%05d.png          RGB 8-bit at the shot resolution, the city + the actors'
                             proxy meshes + the effects, through the scene's own look.
    depth_%05d.png           16-bit greyscale.  HOUSE CONVENTION: near = WHITE (65535),
                             far = BLACK (0), LINEAR in camera Z over [near, far] as
                             recorded in camera.json.  Sky (and anything past ``far``)
                             is 0.
    matte_<actor>_%05d.png   8-bit, 255 where that actor's proxy mesh is the frontmost
                             surface, 0 elsewhere.
    joints.json              33 MediaPipe landmarks per actor per frame, in pixels,
                             with a visibility flag from a depth test.
    camera.json              per-frame camera in STUDIO coordinates plus the depth range.
    actors.json              actor id -> character id / proxy / pass_index / mapping.

Frame numbers are Blender's own and start at 1.

HOW THE PASSES ARE MADE, AND WHY NOT THE OBVIOUS WAY.
``BLENDER_EEVEE_NEXT`` (4.3) exposes exactly three Render-Layers outputs — Image, Alpha
and Depth.  **There is no IndexOB pass in EEVEE Next**, measured on this box, so the
object-index/IDMask route the rest of the house uses under Cycles cannot make the
mattes here.  Rather than pay a Cycles pass per frame just for an index, the matte is
taken from the DEPTH buffer itself: the frame's Z is rendered once with every actor
visible and once per actor with that actor hidden, and the matte is the set of pixels
whose Z changed.  That is exactly "where this actor is the frontmost surface" — it is
occlusion-correct by construction, it costs one extra Z render per actor per frame, and
it works identically under Cycles or Workbench if EEVEE ever refuses.

Effects (the VDB volumes) are visible for the beauty render and hidden for every depth
render, so the volume never eats the geometry's Z or an actor's matte.  That choice is
recorded honestly in camera.json as ``depth_excludes_effects: true``.

THE 33 JOINTS come from ``blender_scripts/actor_joints.joints33`` — the one table
(``CMU_MB_JOINT_MAP``) that the actor builders, this exporter and the tests share.  The
actors are COLLECTION INSTANCES, so a pose bone's ``matrix_world`` is in the source
collection's space, not the shot's: the instance's own matrix is recovered from the
depsgraph and applied on top (``_instance_correction``).

The last stdout line is the contract: ``{"ok":true,…}`` or ``{"ok":false,"error":…}``
with exit 1 — the same shape as ``scene_build.main``.
"""

from __future__ import annotations

import argparse
import glob
import json
import math
import os
import shutil
import sys
import time
import traceback

try:  # only importable inside Blender; guarded so the module
    import bpy  # can be imported by a plain pytest run
    import mathutils
except ImportError:
    bpy = mathutils = None
import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)


HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(HERE, 'blender_scripts')

# Only the repo root and blender_scripts.  NOT arch_server_ext: it holds a
# server-side module ALSO called scene_shot.py, which would shadow the real one
# and make it import itself (AttributeError: partially initialized module).
for _p in (HERE, SCRIPTS):
    if _p not in sys.path:
        sys.path.insert(0, _p)

SCHEMA = 'zyg.plates_raw/1'

NEAR_M = 0.5  # the near end of the depth ramp, fixed by the house contract
FAR_PCT = 99.0  # far = this percentile of the non-sky depth of the first frame
FAR_MIN_M, FAR_MAX_M = 20.0, 500.0
SKY_FRAC_OF_CLIP = 0.9  # Z at/above 0.9*clip_end is the world background, not geometry

VIS_TOL_M = 0.15  # a joint this far behind the depth buffer is still "visible"
MATTE_EPS_M = 1e-3  # |dZ| over max(EPS, EPS*Z) counts as "this actor is here"

BEAUTY_ENGINES = ('BLENDER_EEVEE_NEXT', 'BLENDER_WORKBENCH')
DEPTH_ENGINES = ('BLENDER_EEVEE_NEXT', 'CYCLES')


# --------------------------------------------------------------------------
# image io — Blender's Python has numpy but no PIL, so every read and write of a
# PNG/EXR on this path goes through bpy.data.images.
# --------------------------------------------------------------------------


def _read_gray(path):
    """First channel of an image on disk as a float32 (H, W) array, rows BOTTOM-UP
    (the order Blender keeps pixels in, and the order ``world_to_camera_view``'s v
    runs in, so no flip is needed when indexing with v)."""
    import numpy as np

    img = bpy.data.images.load(os.path.abspath(path))
    try:
        w, h = img.size
        buf = np.empty(w * h * img.channels, dtype=np.float32)
        img.pixels.foreach_get(buf)
        return buf.reshape(h, w, img.channels)[:, :, 0].copy()
    finally:
        bpy.data.images.remove(img)


def _write_mask(path, mask):
    """An 8-bit PNG, 255 where ``mask`` is true.  ``mask`` is (H, W), rows bottom-up."""
    import numpy as np

    h, w = mask.shape
    img = bpy.data.images.new(os.path.basename(path), w, h, alpha=False, float_buffer=False)
    try:
        img.colorspace_settings.name = 'Non-Color'  # no transform on the way out
        v = mask.astype(np.float32)
        rgba = np.empty((h, w, 4), np.float32)
        rgba[:, :, 0] = rgba[:, :, 1] = rgba[:, :, 2] = v
        rgba[:, :, 3] = 1.0
        img.pixels.foreach_set(rgba.ravel())
        img.file_format = 'PNG'
        img.filepath_raw = os.path.abspath(path)
        img.save()
    finally:
        bpy.data.images.remove(img)


# --------------------------------------------------------------------------
# the compositor: beauty out of Composite, Z out of two File Output nodes
# --------------------------------------------------------------------------


def _raw_format(fmt, file_format, color_depth):
    fmt.file_format = file_format
    fmt.color_mode = 'BW'
    fmt.color_depth = color_depth
    # A view transform (AgX) on a depth pass would destroy the linearity the whole
    # contract rests on, so the depth outputs are pinned to Raw.
    try:
        fmt.color_management = 'OVERRIDE'
        fmt.view_settings.view_transform = 'Raw'
        fmt.view_settings.look = 'None'
        fmt.view_settings.exposure = 0.0
        fmt.view_settings.gamma = 1.0
    except (AttributeError, TypeError) as _exc:  # pragma: no cover
        _zyg_log.debug('raw colour management not settable on this build: %s', _exc)


def build_nodes(sc, scratch):
    """Composite <- Image, one File Output for the normalised 16-bit depth and one for
    the raw float Z.  Returns the handles the render loop drives."""
    sc.use_nodes = True
    nt = sc.node_tree
    for n in list(nt.nodes):
        nt.nodes.remove(n)

    rl = nt.nodes.new('CompositorNodeRLayers')
    comp = nt.nodes.new('CompositorNodeComposite')
    nt.links.new(rl.outputs['Image'], comp.inputs['Image'])
    if 'Depth' not in rl.outputs:
        raise RuntimeError(
            'the render engine exposes no Depth pass (outputs: %s)' % ', '.join(s.name for s in rl.outputs if s.enabled)
        )

    mr = nt.nodes.new('CompositorNodeMapRange')
    mr.use_clamp = True
    nt.links.new(rl.outputs['Depth'], mr.inputs[0])

    fo_depth = nt.nodes.new('CompositorNodeOutputFile')
    fo_depth.base_path = scratch
    _raw_format(fo_depth.format, 'PNG', '16')
    fo_depth.file_slots.clear()
    fo_depth.file_slots.new('depth_')
    nt.links.new(mr.outputs[0], fo_depth.inputs['depth_'])

    fo_z = nt.nodes.new('CompositorNodeOutputFile')
    fo_z.base_path = scratch
    _raw_format(fo_z.format, 'OPEN_EXR', '32')
    fo_z.file_slots.clear()
    fo_z.file_slots.new('z_')
    nt.links.new(rl.outputs['Depth'], fo_z.inputs['z_'])

    return {'rl': rl, 'comp': comp, 'map_range': mr, 'depth': fo_depth, 'z': fo_z}


def set_depth_range(nodes, near, far):
    """near -> 1.0 (white), far -> 0.0 (black), clamped: the house convention."""
    mr = nodes['map_range']
    mr.inputs[1].default_value = float(near)  # From Min
    mr.inputs[2].default_value = float(far)  # From Max
    mr.inputs[3].default_value = 1.0  # To Min
    mr.inputs[4].default_value = 0.0  # To Max


# --------------------------------------------------------------------------
# scene bookkeeping
# --------------------------------------------------------------------------


def _wipe(d):
    for p in glob.glob(os.path.join(d, '*')):
        try:
            os.unlink(p)
        except OSError as _exc:
            _zyg_log.debug('scratch file removal skipped: %s', _exc)


def _take(scratch, prefix, dest=None):
    """The one file a File Output slot just wrote (it appends the frame number)."""
    hits = sorted(glob.glob(os.path.join(scratch, prefix + '*')))
    if not hits:
        raise RuntimeError('the compositor wrote no %r file into %s' % (prefix, scratch))
    if dest is None:
        return hits[-1]
    os.replace(hits[-1], dest)
    return dest


def effect_objects(sc):
    """Every object that belongs to a shot effect — the collection scene_build makes,
    plus anything carrying its ``shot_effect`` stamp."""
    out = []
    coll = bpy.data.collections.get('effects')
    if coll is not None:
        out = [o for o in coll.all_objects]
    for ob in sc.objects:
        if ob.get('shot_effect') is not None and ob not in out:
            out.append(ob)
    return out


def find_actors(sc, shot):
    """Resolve the shot's actors to what scene_build actually put in the .blend.

    Returns one record per PLACED actor; an actor whose proxy was missing at build
    time has no instancer and is reported (and skipped) rather than raising.
    """
    import actor_joints as AJ  # noqa: N814

    found, missing = [], []
    for i, actor in enumerate(shot.get('actors') or []):
        aid = str(actor['id'])
        inst = bpy.data.objects.get('actor %s' % aid)
        if inst is None:
            want = 'actor_%s' % aid
            for ob in sc.objects:
                if ob.instance_collection is not None and ob.instance_collection.name == want:
                    inst = ob
                    break
        if inst is None or inst.instance_collection is None:
            missing.append({'id': aid, 'reason': 'no collection instance in the .blend'})
            continue
        coll = inst.instance_collection
        meshes = [o for o in coll.all_objects if o.type == 'MESH']
        arms = [o for o in coll.all_objects if o.type == 'ARMATURE']
        if not arms:
            missing.append({'id': aid, 'reason': 'collection %r has no armature' % coll.name})
            continue
        arm = arms[0]
        # The pass_index is part of the published contract even though the mattes are
        # made from depth: it is what a Cycles consumer of this .blend would use.
        for ob in meshes:
            ob.pass_index = i + 1
        mapping = arm.get('mapping') or str(actor.get('mapping') or '') or 'cmu_mb'
        found.append(
            {
                'id': aid,
                'instancer': inst,
                'collection': coll,
                'armature': arm,
                'armature_name': arm.name,
                'meshes': [o.name for o in meshes],
                'pass_index': i + 1,
                'mapping': str(mapping),
                'proxy': str(actor.get('proxy') or aid),
                'char_id': str(actor.get('char_id') or aid),
                'joint_map': AJ.mapping_for(arm, str(mapping)),
            }
        )
    return found, missing


def _instance_correction(dg, rec):
    """(evaluated armature, matrix) that takes an armature-space world point to the
    SHOT's world space.

    An actor is a collection instance, so ``armature.matrix_world`` is still the source
    collection's — the empty's transform (and the collection's instance offset) live on
    the depsgraph instance instead.  ``M = instance.matrix_world @ arm.matrix_world^-1``
    is the correction, and it is the identity for a plain, non-instanced armature.
    """
    name = rec['armature_name']
    inst_eval = rec['instancer'].evaluated_get(dg)
    best = None
    for di in dg.object_instances:
        ob = di.object
        if ob is None or ob.type != 'ARMATURE' or ob.original.name != name:
            continue
        if di.is_instance:
            par = di.parent
            if par is None or par.original != inst_eval.original:
                continue
            return ob, di.matrix_world.copy() @ ob.matrix_world.inverted()
        best = (ob, mathutils.Matrix.Identity(4))
    if best is None:
        raise RuntimeError('armature %r for actor %r is not in the depsgraph' % (name, rec['id']))
    return best


# --------------------------------------------------------------------------
# joints
# --------------------------------------------------------------------------


def joints_for_frame(sc, cam, rec, dg, zbuf, width, height):
    """33 ``[x_px, y_px, vis]`` for one actor on the current frame.

    ``vis`` is 1.0 when the rig actually has the joint, the joint projects in front of
    the camera and inside the frame, and it is no more than ``VIS_TOL_M`` behind the
    depth buffer at its own pixel — i.e. nothing in the city is standing in front of it.
    """
    import actor_joints as AJ  # noqa: N814
    from bpy_extras.object_utils import world_to_camera_view

    arm, corr = _instance_correction(dg, rec)
    raw = AJ.joints_from_map(arm, rec['joint_map'])
    zh, zw = zbuf.shape if zbuf is not None else (0, 0)

    pts, n_vis = [], 0
    for x, y, z, present in raw:
        if not present:
            pts.append([0.0, 0.0, 0.0])
            continue
        co = world_to_camera_view(sc, cam, corr @ mathutils.Vector((x, y, z)))
        px = co.x * width
        py = (1.0 - co.y) * height
        inside = co.z > 0.0 and 0.0 <= px < width and 0.0 <= py < height
        vis = 0.0
        if inside and zbuf is not None:
            row = min(zh - 1, max(0, int(co.y * zh)))
            col = min(zw - 1, max(0, int(co.x * zw)))
            if co.z <= float(zbuf[row, col]) + VIS_TOL_M:
                vis = 1.0
                n_vis += 1
        pts.append([round(float(px), 2), round(float(py), 2), vis])
    return pts, n_vis


# --------------------------------------------------------------------------
# camera
# --------------------------------------------------------------------------


def camera_record(sc, cam, shot, f, SS):
    """The camera of the current frame, back in STUDIO coordinates.

    ``p`` and ``t`` are read off the camera Blender actually rendered with (not off the
    shot's keys), so a hand-edited .blend is reported honestly; the aim distance comes
    from the shot's own target because a direction alone does not fix a point.
    """
    mw = cam.matrix_world
    p_bl = mw.translation.copy()
    fwd = (mw.to_3x3() @ mathutils.Vector((0.0, 0.0, -1.0))).normalized()
    key = SS.camera_at(shot, f)
    dist = (mathutils.Vector(SS.to_blender(key['t'])) - p_bl).length or 1.0
    t_bl = p_bl + fwd * dist

    cd = cam.data
    sensor = cd.sensor_height if cd.sensor_fit != 'HORIZONTAL' else cd.sensor_width
    fov = math.degrees(2.0 * math.atan((sensor * 0.5) / max(1e-6, cd.lens)))
    return {
        'f': int(f),
        'p': [round(v, 5) for v in SS.from_blender(p_bl)],
        't': [round(v, 5) for v in SS.from_blender(t_bl)],
        'fov': round(fov, 5),
        'lens_mm': round(float(cd.lens), 5),
        'matrix_world': [round(float(v), 6) for row in mw for v in row],
    }


# --------------------------------------------------------------------------
# the render loop
# --------------------------------------------------------------------------


def _try_engines(sc, engines, cpu):
    """Set the first engine of ``engines`` that renders this scene without raising."""
    errs = []
    for eng in engines:
        try:
            sc.render.engine = eng
        except TypeError as exc:
            errs.append('%s: %s' % (eng, exc))
            continue
        if eng == 'CYCLES':
            sc.cycles.samples = 1
            sc.cycles.use_adaptive_sampling = False
            sc.cycles.use_denoising = False
            if cpu:
                sc.cycles.device = 'CPU'
        try:
            bpy.ops.render.render(write_still=False)
            return eng, errs
        except Exception as exc:  # noqa: BLE001
            errs.append('%s: %s' % (eng, exc))
    raise RuntimeError('no render engine worked (%s)' % '; '.join(errs))


def export(shot, raw_dir, frames, cpu=False, log=print):
    import numpy as np
    from zyg_workflows import scene_shot as SS  # noqa: N814

    sc = bpy.context.scene
    cam = sc.camera
    if cam is None:
        raise RuntimeError('the .blend has no active camera — run scene_build first')

    width, height = int(shot['resolution'][0]), int(shot['resolution'][1])
    sc.render.resolution_x, sc.render.resolution_y = width, height
    sc.render.resolution_percentage = 100
    sc.render.film_transparent = False
    sc.render.use_file_extension = True
    sc.render.image_settings.file_format = 'PNG'
    sc.render.image_settings.color_mode = 'RGB'
    sc.render.image_settings.color_depth = '8'
    bpy.context.view_layer.use_pass_z = True
    bpy.context.view_layer.use_pass_object_index = True

    os.makedirs(raw_dir, exist_ok=True)
    scratch = os.path.join(raw_dir, '_scratch')
    os.makedirs(scratch, exist_ok=True)
    _wipe(scratch)

    actors, missing = find_actors(sc, shot)
    for m in missing:
        log('[plates] warning: actor %r skipped — %s' % (m['id'], m['reason']))
    fx = effect_objects(sc)
    fx_hidden = [(o, o.hide_render) for o in fx]

    def hide_fx(on):
        for ob, _was in fx_hidden:
            ob.hide_render = bool(on)

    def restore_fx():
        for ob, was in fx_hidden:
            ob.hide_render = was

    nodes = build_nodes(sc, scratch)
    set_depth_range(nodes, NEAR_M, max(FAR_MIN_M, NEAR_M + 1.0))

    # ---- the depth range, measured on the first exported frame ----
    sc.frame_set(frames[0])
    hide_fx(True)
    engine_depth, depth_errs = _try_engines(sc, DEPTH_ENGINES, cpu)
    if engine_depth != sc.render.engine:  # pragma: no cover
        sc.render.engine = engine_depth
    z0 = _read_gray(_take(scratch, 'z_'))
    _wipe(scratch)
    sky_cut = SKY_FRAC_OF_CLIP * float(cam.data.clip_end)
    scene_z = z0[z0 < sky_cut]
    if scene_z.size < 16:
        far = FAR_MIN_M
    else:
        far = float(np.percentile(scene_z, FAR_PCT))
    far = float(min(FAR_MAX_M, max(FAR_MIN_M, far)))
    set_depth_range(nodes, NEAR_M, far)
    log(
        '[plates] depth range near=%.3f far=%.3f m (sky %.1f %% of frame %d, engine %s)'
        % (NEAR_M, far, 100.0 * float((z0 >= sky_cut).mean()), frames[0], engine_depth)
    )

    # ---- the beauty engine, chosen once on the same frame ----
    hide_fx(False)
    engine_beauty, beauty_errs = _try_engines(sc, BEAUTY_ENGINES, cpu)
    _wipe(scratch)
    log('[plates] beauty engine %s, depth engine %s' % (engine_beauty, engine_depth))

    names = None
    jframes, cam_frames, matte_cover = [], [], {a['id']: [] for a in actors}
    t0 = time.time()

    for f in frames:
        sc.frame_set(f)

        # 1. beauty — effects visible, everybody visible, the scene's own look
        restore_fx()
        sc.render.engine = engine_beauty
        sc.render.filepath = os.path.join(raw_dir, 'beauty_%05d.png' % f)
        bpy.ops.render.render(write_still=True)
        _wipe(scratch)

        # 2. depth — effects hidden, everybody visible
        sc.render.engine = engine_depth
        hide_fx(True)
        bpy.ops.render.render(write_still=False)
        _take(scratch, 'depth_', os.path.join(raw_dir, 'depth_%05d.png' % f))
        z_full = _read_gray(_take(scratch, 'z_'))
        _wipe(scratch)

        # 3. one matte per actor — the pixels whose Z moves when that actor goes away
        for rec in actors:
            rec['instancer'].hide_render = True
            bpy.ops.render.render(write_still=False)
            z_wo = _read_gray(_take(scratch, 'z_'))
            rec['instancer'].hide_render = False
            _wipe(scratch)
            tol = np.maximum(MATTE_EPS_M, MATTE_EPS_M * np.minimum(z_full, z_wo))
            mask = np.abs(z_full - z_wo) > tol
            _write_mask(os.path.join(raw_dir, 'matte_%s_%05d.png' % (rec['id'], f)), mask)
            matte_cover[rec['id']].append(float(mask.mean()))

        # 4. joints and camera, off the restored (everything visible) depsgraph
        restore_fx()
        dg = bpy.context.evaluated_depsgraph_get()
        acts = {}
        for rec in actors:
            import actor_joints as AJ  # noqa: N814

            names = names or list(AJ.POSE_NAMES)
            pts, n_vis = joints_for_frame(sc, cam, rec, dg, z_full, width, height)
            acts[rec['id']] = {'pts': pts, 'visible': n_vis}
        jframes.append({'f': int(f), 'actors': acts})
        cam_frames.append(camera_record(sc, cam, shot, f, SS))
        if f == frames[0] or f == frames[-1] or (f - frames[0]) % 10 == 0:
            log('[plates] frame %d/%d (%.1f s)' % (f, frames[-1], time.time() - t0))

    restore_fx()
    shutil.rmtree(scratch, ignore_errors=True)

    import actor_joints as AJ  # noqa: N814

    fps = float(shot['fps'])
    joints = {
        'schema': SCHEMA,
        'fps': fps,
        'width': width,
        'height': height,
        'names': names or list(AJ.POSE_NAMES),
        'chars': {a['id']: a['char_id'] for a in actors},
        'frames': jframes,
    }
    camera = {
        'schema': SCHEMA,
        'width': width,
        'height': height,
        'fps': fps,
        'near': round(NEAR_M, 5),
        'far': round(far, 5),
        'depth_excludes_effects': True,
        'depth_convention': 'linear camera Z, near=white(65535), far=black(0), sky=0',
        'engine_beauty': engine_beauty,
        'engine_depth': engine_depth,
        'sensor_mm': round(float(cam.data.sensor_height), 5),
        'frames': cam_frames,
    }
    with open(os.path.join(raw_dir, 'joints.json'), 'w', encoding='utf-8') as fh:
        json.dump(joints, fh, indent=1)
    with open(os.path.join(raw_dir, 'camera.json'), 'w', encoding='utf-8') as fh:
        json.dump(camera, fh, indent=1)
    with open(os.path.join(raw_dir, 'actors.json'), 'w', encoding='utf-8') as fh:
        json.dump(
            {
                a['id']: {
                    'char_id': a['char_id'],
                    'proxy': a['proxy'],
                    'pass_index': a['pass_index'],
                    'mapping': a['mapping'],
                    'meshes': a['meshes'],
                    'matte_coverage_mean': round(sum(matte_cover[a['id']]) / max(1, len(matte_cover[a['id']])), 8),
                }
                for a in actors
            },
            fh,
            indent=1,
        )

    return {
        'ok': True,
        'frames': len(frames),
        'actors': [a['id'] for a in actors],
        'skipped_actors': missing,
        'engine_beauty': engine_beauty,
        'engine_depth': engine_depth,
        'matte_method': 'depth-difference (EEVEE Next has no IndexOB pass)',
        'width': width,
        'height': height,
        'near': round(NEAR_M, 5),
        'far': round(far, 5),
        'dir': raw_dir,
        'seconds': round(time.time() - t0, 2),
    }


# --------------------------------------------------------------------------


def parse_frames(spec, lo, hi):
    """``a:b`` (inclusive, clamped) or empty for the whole shot."""
    if not spec:
        return list(range(lo, hi + 1))
    a, _, b = str(spec).partition(':')
    a = int(a) if a.strip() else lo
    b = int(b) if b.strip() else hi
    a, b = max(lo, min(hi, a)), max(lo, min(hi, b))
    if b < a:
        a, b = b, a
    return list(range(a, b + 1))


def main():
    argv = sys.argv[sys.argv.index('--') + 1 :] if '--' in sys.argv else []
    ap = argparse.ArgumentParser(prog='scene_plates_export.py')
    ap.add_argument('--shot', required=True, help='a zyg.scene_shot/1 shot.json')
    ap.add_argument('--frames', default='', help='a:b, inclusive (default: the whole shot)')
    ap.add_argument(
        '--cpu',
        type=int,
        default=0,
        help='1 = never ask a renderer for a GPU compute device '
        '(EEVEE is a rasteriser and always uses the display GPU)',
    )
    ap.add_argument('--out', default='', help='override the plates_raw directory')
    args = ap.parse_args(argv)

    from zyg_workflows import scene_shot as SS  # noqa: N814

    shot = SS.resolve_positions(SS.load(os.path.abspath(args.shot)))
    raw_dir = os.path.abspath(args.out or os.path.join(SS.shot_dir(shot), 'plates_raw'))
    frames = parse_frames(args.frames, 1, max(1, int(shot['frames'])))
    res = export(shot, raw_dir, frames, cpu=bool(args.cpu))
    print(json.dumps(res), flush=True)


if __name__ == '__main__':
    try:
        main()
    except Exception as e:  # noqa: BLE001 — one JSON line is the contract
        traceback.print_exc()
        print(json.dumps({'ok': False, 'error': '%s: %s' % (type(e).__name__, e)}), flush=True)
        sys.exit(1)
