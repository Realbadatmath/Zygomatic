#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""scene_render.py — render a shot's .blend twice from ONE placement record.

The operator's question is "is the tornado where I said it was?", and that
question has to be answerable in seconds, not in a Cycles queue.  So the same
scene renders in two modes and both write the SAME ``placement.json``:

DRAFT   Workbench at 320x180.  Every effect volume is hidden and replaced by a
        translucent, wire-caged box of its own scaled bounds with its id
        floating above it.  Nothing is sampled, nothing is denoised; the point
        is purely *where the effect sits in the frame*, and that is legible at
        a tenth of a second per frame.
FULL    Cycles with the real volumes, GPU unless ``--cpu 1``.  With
        ``--effects-only 1`` the buildings become holdouts and the effects come
        out on transparent RGBA + a ProRes 4444 element, which is the layer the
        assembler lays over the video engine's output.

placement.json is the contract between this renderer and the UI: per effect per
frame the projected pixel bbox of its bounds, its projected ground point and
its distance to camera, plus every actor's projected ground point.  The studio
overlay and the Video Studio placement tool both read it, so it is written in
BOTH modes and its pixel coordinates are in the mode's own render resolution.

    flock /tmp/claude-1000/arch_ext_blender.lock \
        blender -b <shot_dir>/scene.blend --python blender_scripts/scene_render.py -- \
            --shot <shot.json> --mode draft|full [--frames a:b] [--cpu 1] \
            [--effects-only 1] [--samples N]

Two headless Blenders at once SIGBUS the Bonsai add-on, hence the flock.

The last stdout line is the contract:
``{"ok":true,"mode":…,"frames":N,"mp4":…,"placement":…,"fps_render":…}``
or ``{"ok":false,"error":…}`` with exit 1.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import traceback

try:  # only importable inside Blender; guarded so the
    import bpy  # module can be imported by a plain pytest run
    import mathutils  # (same trick as blender_scripts/scene_build.py)
except ImportError:
    bpy = mathutils = None
import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)


HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXT_DIR = os.path.join(HERE, 'arch_server_ext')

# the crews root goes in LAST so it ends up FIRST on sys.path: arch_server_ext
# holds a family module called scene_shot, and it must never shadow the contract
# module of the same name at the crews root.
for _p in (EXT_DIR, HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

PLACEMENT_SCHEMA = 'zyg.scene_placement/1'
BOUNDS_SCHEMA = 'zyg.scene_effect_bounds/1'

DRAFT_W, DRAFT_H = 320, 180
DRAFT_ENGINE = 'BLENDER_WORKBENCH'
DRAFT_SKY = (0.62, 0.74, 0.85)
FULL_SAMPLES = 64
LABEL_M = 0.4  # cap height of the in-scene effect label
BOX_ALPHA = 0.35
WIRE_M = 0.025  # world thickness of the box's wire cage

# Six saturated hues, cycled per effect.  Saturated because a draft frame is
# read at a glance next to grey concrete, not colour-matched.
FX_COLOURS = [
    (1.00, 0.15, 0.10),
    (1.00, 0.62, 0.05),
    (0.25, 0.90, 0.20),
    (0.10, 0.80, 0.95),
    (0.25, 0.35, 1.00),
    (0.95, 0.20, 0.85),
]


# --------------------------------------------------------------------------
# small helpers
# --------------------------------------------------------------------------


def _run(cmd):
    return subprocess.run(cmd, capture_output=True, text=True)


def parse_frames(spec, lo, hi):
    """``"a:b"`` -> an inclusive frame range clamped into the scene's own."""
    if not spec:
        return lo, hi
    txt = str(spec).strip()
    if ':' in txt:
        a, _, b = txt.partition(':')
    else:
        a = b = txt
    try:
        a = int(a) if a.strip() else lo
        b = int(b) if b.strip() else hi
    except ValueError as _exc:
        raise SystemExit('bad --frames %r (want a:b)' % spec) from _exc
    a, b = max(lo, min(hi, a)), max(lo, min(hi, b))
    if b < a:
        a, b = b, a
    return a, b


def effect_objects(sc):
    """Every object the builder stamped with ``shot_effect``, in shot order."""
    out = []
    for ob in sc.objects:
        fid = ob.get('shot_effect')
        if fid:
            out.append((str(fid), ob))
    out.sort(key=lambda t: t[1].name)
    return out


# --------------------------------------------------------------------------
# bounds (cached — evaluating a VDB frame is the expensive part of a draft)
# --------------------------------------------------------------------------


def _eval_bounds_frame(sc, ob):
    """``start_frame + n//2`` of the effect's own sequence, clamped to the shot.

    Mid-sequence and not frame 1: a fire pack's first frames are a spark, and a
    box drawn round a spark is a lie about where the fire will be.
    """
    start = 1
    n = 0
    try:
        vol = ob.data
        n = int(getattr(vol, 'frame_duration', 0) or 0)
        start = 1 - int(getattr(vol, 'frame_offset', 0) or 0)
    except Exception as _exc:  # noqa: BLE001
        _zyg_log.debug('volume frame range not readable, using the scene range: %s', _exc)
    if n <= 0:
        n = sc.frame_end - sc.frame_start + 1
    f = int(start) + n // 2
    return max(sc.frame_start, min(sc.frame_end, f))


def effect_bounds(sc, fx_obs, cache_path, refresh=False):
    """Local-space bound_box per effect, cached on disk.

    LOCAL and not world, so the box follows the volume object through any
    animation the shot gave it: the cage mesh is parented to the volume and
    inherits its matrix exactly.
    """
    cache = {}
    if os.path.isfile(cache_path) and not refresh:
        try:
            with open(cache_path, 'r', encoding='utf-8') as fh:
                got = json.load(fh)
            if got.get('schema') == BOUNDS_SCHEMA:
                cache = got.get('effects') or {}
        except Exception:  # noqa: BLE001
            cache = {}

    out = {}
    dirty = False
    for fid, ob in fx_obs:
        rec = cache.get(fid)
        if rec and len(rec.get('local') or ()) == 8:
            out[fid] = rec
            continue
        f = _eval_bounds_frame(sc, ob)
        sc.frame_set(f)
        bpy.context.view_layer.update()
        dg = bpy.context.evaluated_depsgraph_get()
        ev = ob.evaluated_get(dg)
        local = [[float(c[0]), float(c[1]), float(c[2])] for c in ev.bound_box]
        mw = ob.matrix_world
        world = [mw @ mathutils.Vector(c) for c in local]
        lo = [min(v[i] for v in world) for i in range(3)]
        hi = [max(v[i] for v in world) for i in range(3)]
        rec = {
            'frame': f,
            'object': ob.name,
            'local': [[round(c, 6) for c in v] for v in local],
            'world_min': [round(c, 4) for c in lo],
            'world_max': [round(c, 4) for c in hi],
            'size_m': [round(hi[i] - lo[i], 4) for i in range(3)],
        }
        out[fid] = rec
        dirty = True
        _zyg_log.info('[render] bounds %s @f%d: %s m' % (fid, f, rec['size_m']))

    if dirty:
        os.makedirs(os.path.dirname(cache_path), exist_ok=True)
        tmp = cache_path + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as fh:
            json.dump({'schema': BOUNDS_SCHEMA, 'effects': out}, fh, indent=1)
        os.replace(tmp, cache_path)
    return out, dirty


# --------------------------------------------------------------------------
# placement — the record both modes write
# --------------------------------------------------------------------------


def _project(sc, cam, co, w, h):
    """World point -> pixel, y measured DOWN from the top-left of the frame.

    ``world_to_camera_view`` hands back 0..1 with v running bottom-up, which is
    Blender's convention and nobody else's; every consumer of placement.json is
    a canvas or an ffmpeg filter, so it is flipped here once and for all.
    """
    from bpy_extras.object_utils import world_to_camera_view

    uvz = world_to_camera_view(sc, cam, co)
    return (round(uvz.x * w, 2), round((1.0 - uvz.y) * h, 2), float(uvz.z))


def compute_placement(sc, cam, shot, SS, fx_obs, bounds, a, b, w, h):
    """One pass over the frames: pixel geometry for the UI, world boxes for the
    draft cage's label track.  No rendering happens here."""
    frames = []
    world_boxes = {}  # fid -> {frame: (lo, hi)}
    for fid, _ob in fx_obs:
        world_boxes[fid] = {}
    actors = [a_ for a_ in (shot.get('actors') or []) if a_.get('id')]

    for f in range(a, b + 1):
        sc.frame_set(f)
        bpy.context.view_layer.update()
        cam_p = cam.matrix_world.translation
        rec = {'f': f, 'effects': {}, 'actors': {}}

        for fid, ob in fx_obs:
            mw = ob.matrix_world
            corners = [mw @ mathutils.Vector(c) for c in bounds[fid]['local']]
            lo = [min(v[i] for v in corners) for i in range(3)]
            hi = [max(v[i] for v in corners) for i in range(3)]
            world_boxes[fid][f] = (lo, hi)
            centre = mathutils.Vector(((lo[0] + hi[0]) * 0.5, (lo[1] + hi[1]) * 0.5, (lo[2] + hi[2]) * 0.5))
            ground = mathutils.Vector(((lo[0] + hi[0]) * 0.5, (lo[1] + hi[1]) * 0.5, lo[2]))
            px = [_project(sc, cam, c, w, h) for c in corners]
            front = [p for p in px if p[2] > 0.0]
            gx, gy, gz = _project(sc, cam, ground, w, h)
            cx, cy, cz = _project(sc, cam, centre, w, h)
            e = {
                'in_front': bool(front),
                'clipped': len(front) != len(px),
                'bbox_px': None,
                'centre_px': [cx, cy] if cz > 0.0 else None,
                'ground_px': [gx, gy] if gz > 0.0 else None,
                'distance_m': round((centre - cam_p).length, 4),
                'ground_distance_m': round((ground - cam_p).length, 4),
                'world_min': [round(c, 4) for c in lo],
                'world_max': [round(c, 4) for c in hi],
            }
            if front:
                e['bbox_px'] = [
                    round(min(p[0] for p in front), 2),
                    round(min(p[1] for p in front), 2),
                    round(max(p[0] for p in front), 2),
                    round(max(p[1] for p in front), 2),
                ]
                e['on_screen'] = bool(
                    e['bbox_px'][2] > 0 and e['bbox_px'][0] < w and e['bbox_px'][3] > 0 and e['bbox_px'][1] < h
                )
            else:
                e['on_screen'] = False
            rec['effects'][fid] = e

        for actor in actors:
            aid = str(actor['id'])
            st = SS.actor_at(shot, actor, f)
            gp = mathutils.Vector(SS.to_blender(st['p']))
            ax, ay, az = _project(sc, cam, gp, w, h)
            rec['actors'][aid] = {
                'ground_px': [ax, ay] if az > 0.0 else None,
                'in_front': bool(az > 0.0),
                'on_screen': bool(az > 0.0 and 0 <= ax <= w and 0 <= ay <= h),
                'distance_m': round((gp - cam_p).length, 4),
                'ry': round(float(st.get('ry', 0.0)), 3),
                'world': [round(c, 4) for c in gp],
            }
        frames.append(rec)

    doc = {
        'schema': PLACEMENT_SCHEMA,
        'shot': shot['id'],
        'width': w,
        'height': h,
        'fps': int(shot.get('fps', 24)),
        'frame_start': a,
        'frame_end': b,
        'n_frames': len(frames),
        'pixel_origin': 'top-left, y down',
        'effects': [fid for fid, _ in fx_obs],
        'actors': [str(x['id']) for x in actors],
        'frames': frames,
    }
    return doc, world_boxes


# --------------------------------------------------------------------------
# draft — boxes, cages, labels
# --------------------------------------------------------------------------


def _flat_material(name, rgba):
    mat = bpy.data.materials.new(name)
    mat.diffuse_color = rgba  # what Workbench MATERIAL reads
    mat.use_nodes = True
    mat.blend_method = 'BLEND'
    try:
        bsdf = mat.node_tree.nodes.get('Principled BSDF')
        if bsdf:
            bsdf.inputs['Base Color'].default_value = rgba
            if 'Alpha' in bsdf.inputs:
                bsdf.inputs['Alpha'].default_value = rgba[3]
    except Exception as _exc:  # noqa: BLE001
        _zyg_log.debug('base colour not settable on this material: %s', _exc)
    return mat


def _box_mesh(name, corners):
    """A cube from Blender's own bound_box corner order.

    ``bound_box`` runs (-x-y-z), (-x-y+z), (-x+y+z), (-x+y-z), (+x-y-z),
    (+x-y+z), (+x+y+z), (+x+y-z) — so the faces are spelled out rather than
    guessed.
    """
    faces = [(0, 1, 2, 3), (4, 7, 6, 5), (0, 4, 5, 1), (3, 2, 6, 7), (0, 3, 7, 4), (1, 5, 6, 2)]
    me = bpy.data.meshes.new(name)
    me.from_pydata([tuple(c) for c in corners], [], faces)
    me.update()
    return me


def build_draft_proxies(sc, fx_obs, bounds, world_boxes, cam, coll):
    """Hide every volume; draw its bounds instead, labelled.

    The label is keyed per frame from the world boxes rather than parented,
    because the volume object carries the pack's own scale (a VDB's units are
    the simulation's) and a parented text would inherit it — "0.4 m" has to
    mean 0.4 m in the shot, not 0.4 sim units.
    """
    made = []
    for i, (fid, ob) in enumerate(fx_obs):
        rgb = FX_COLOURS[i % len(FX_COLOURS)]
        rgba = (rgb[0], rgb[1], rgb[2], BOX_ALPHA)
        ob.hide_render = True

        local = bounds[fid]['local']
        box = bpy.data.objects.new('fxbox %s' % fid, _box_mesh('fxbox %s' % fid, local))
        box.data.materials.append(_flat_material('fxbox %s' % fid, rgba))
        box['shot_effect_box'] = fid
        coll.objects.link(box)
        box.parent = ob
        box.matrix_parent_inverse = mathutils.Matrix.Identity(4)

        # the wire cage: the same box run through Wireframe, opaque, so the
        # edges stay readable where the translucent faces wash out.
        scale = max(1e-9, sum(ob.matrix_world.to_scale()) / 3.0)
        wire = bpy.data.objects.new('fxwire %s' % fid, _box_mesh('fxwire %s' % fid, local))
        wire.data.materials.append(_flat_material('fxwire %s' % fid, (rgb[0], rgb[1], rgb[2], 1.0)))
        mod = wire.modifiers.new('wire', 'WIREFRAME')
        mod.thickness = WIRE_M / scale
        mod.use_replace = True
        coll.objects.link(wire)
        wire.parent = ob
        wire.matrix_parent_inverse = mathutils.Matrix.Identity(4)

        cu = bpy.data.curves.new('fxlabel %s' % fid, type='FONT')
        cu.body = fid
        cu.size = LABEL_M
        cu.align_x = 'CENTER'
        cu.align_y = 'BOTTOM'
        txt = bpy.data.objects.new('fxlabel %s' % fid, cu)
        cu.materials.append(_flat_material('fxlabel %s' % fid, (rgb[0], rgb[1], rgb[2], 1.0)))
        coll.objects.link(txt)
        con = txt.constraints.new('TRACK_TO')  # always broadside to camera
        con.target = cam
        con.track_axis = 'TRACK_Z'
        con.up_axis = 'UP_Y'
        for f, (lo, hi) in sorted(world_boxes[fid].items()):
            txt.location = ((lo[0] + hi[0]) * 0.5, (lo[1] + hi[1]) * 0.5, hi[2] + LABEL_M * 0.5)
            txt.keyframe_insert('location', frame=f)
        if txt.animation_data and txt.animation_data.action:
            for fc in txt.animation_data.action.fcurves:
                for kp in fc.keyframe_points:
                    kp.interpolation = 'LINEAR'
        made += [box.name, wire.name, txt.name]
    bpy.context.view_layer.update()
    return made


def effective_res(sc):
    """What Blender will actually write, once ``resolution_percentage`` is in.

    placement.json is in pixels, so it has to be the OUTPUT size and not the
    nominal one, or every overlay is off by the preview scale.
    """
    pct = int(sc.render.resolution_percentage)
    return (max(1, sc.render.resolution_x * pct // 100), max(1, sc.render.resolution_y * pct // 100))


def setup_draft(sc, shot, percent=100):
    d = (shot.get('render') or {}).get('draft') or {}
    engine = str(d.get('engine') or DRAFT_ENGINE)
    w = int(d.get('width') or DRAFT_W)
    h = int(d.get('height') or DRAFT_H)
    sc.render.engine = engine
    sc.render.resolution_x, sc.render.resolution_y = w, h
    sc.render.resolution_percentage = int(percent)
    sc.render.film_transparent = False
    sc.render.image_settings.file_format = 'PNG'
    sc.render.image_settings.color_mode = 'RGB'
    sc.render.use_file_extension = False
    sh = sc.display.shading
    try:
        sh.light = 'STUDIO'
        sh.show_shadows = True
        sh.color_type = 'MATERIAL'
        sh.background_type = 'VIEWPORT'
        sh.background_color = DRAFT_SKY
        sh.show_xray = False
    except Exception as _exc:  # noqa: BLE001
        _zyg_log.debug('draft shading settings not available on this build: %s', _exc)
    w, h = effective_res(sc)
    return engine, w, h


# --------------------------------------------------------------------------
# full — Cycles
# --------------------------------------------------------------------------

HOLDOUT_TYPES = {'MESH', 'CURVE', 'SURFACE', 'META', 'FONT', 'EMPTY', 'VOLUME'}


def setup_full(sc, shot, RO, samples=0, cpu=False, effects_only=False, fx_obs=(), percent=100):
    """Cycles with the volume settings ``vfx_volume_render.setup_render`` pins.

    Those two numbers are not decoration: at Blender's default 64 volume steps
    a scaled-down VDB renders as banded soup, and with 0 volume bounces the
    smoke self-shadows to black.
    """
    f = (shot.get('render') or {}).get('full') or {}
    w, h = [int(x) for x in (shot.get('resolution') or [832, 480])]
    sc.render.engine = 'CYCLES'
    sc.render.resolution_x, sc.render.resolution_y = w, h
    sc.render.resolution_percentage = int(percent)
    sc.render.image_settings.file_format = 'PNG'
    sc.render.use_file_extension = False
    sc.cycles.samples = int(samples or f.get('samples') or FULL_SAMPLES)
    sc.cycles.use_adaptive_sampling = True
    sc.cycles.use_denoising = bool(int(f.get('denoise', 1)))
    sc.cycles.volume_max_steps = 256
    sc.cycles.volume_step_rate = 1.0
    sc.cycles.max_bounces = 4
    sc.cycles.volume_bounces = 2
    sc.cycles.transparent_max_bounces = 8

    device, backend = 'CPU', ''
    if cpu:
        sc.cycles.device = 'CPU'
    else:
        device, backend = RO.enable_gpu(sc)

    fx_names = {ob.name for _fid, ob in fx_obs}
    holdouts = []
    if effects_only:
        sc.render.film_transparent = True
        sc.render.image_settings.color_mode = 'RGBA'
        for ob in sc.objects:
            if ob.name in fx_names or ob.type not in HOLDOUT_TYPES:
                continue
            ob.is_holdout = True  # still occludes, renders as a hole
            holdouts.append(ob.name)
    else:
        sc.render.film_transparent = False
        sc.render.image_settings.color_mode = 'RGB'
    bpy.context.view_layer.update()
    w, h = effective_res(sc)
    return {
        'width': w,
        'height': h,
        'samples': sc.cycles.samples,
        'denoise': bool(sc.cycles.use_denoising),
        'device': sc.cycles.device,
        'backend': backend,
        'holdouts': len(holdouts),
        'effects_only': bool(effects_only),
    }


# --------------------------------------------------------------------------
# render + encode
# --------------------------------------------------------------------------


def render_range(sc, out_dir, a, b):
    os.makedirs(out_dir, exist_ok=True)
    t0 = time.time()
    n = 0
    for f in range(a, b + 1):
        sc.frame_set(f)
        sc.render.filepath = os.path.join(out_dir, 'f_%05d.png' % f)
        bpy.ops.render.render(write_still=True)
        n += 1
        if n == 1 or n % 10 == 0 or f == b:
            _zyg_log.info('[render] frame %d/%d  %.3f s/frame' % (f, b, (time.time() - t0) / n))
    return n, time.time() - t0


def encode_mp4(out_dir, out, fps, start, n, crf):
    r = _run(
        [
            'ffmpeg',
            '-y',
            '-v',
            'error',
            '-framerate',
            str(fps),
            '-start_number',
            str(start),
            '-i',
            os.path.join(out_dir, 'f_%05d.png'),
            '-frames:v',
            str(n),
            '-c:v',
            'libx264',
            '-pix_fmt',
            'yuv420p',
            '-crf',
            str(crf),
            '-an',
            out,
        ]
    )
    if r.returncode != 0 or not os.path.exists(out):
        raise RuntimeError('x264 encode failed: %s' % r.stderr[-400:])
    return out


def encode_prores(out_dir, out, fps, start, n):
    """Same arguments as ``vfx_volume_element.encode_prores`` L345 — profile
    4444 is the one that carries an alpha channel."""
    r = _run(
        [
            'ffmpeg',
            '-y',
            '-v',
            'error',
            '-framerate',
            str(fps),
            '-start_number',
            str(start),
            '-i',
            os.path.join(out_dir, 'f_%05d.png'),
            '-frames:v',
            str(n),
            '-c:v',
            'prores_ks',
            '-profile:v',
            '4444',
            '-pix_fmt',
            'yuva444p10le',
            '-alpha_bits',
            '16',
            '-vendor',
            'apl0',
            '-an',
            out,
        ]
    )
    if r.returncode != 0 or not os.path.exists(out):
        raise RuntimeError('prores encode failed: %s' % r.stderr[-400:])
    return out


# --------------------------------------------------------------------------


def main():
    argv = sys.argv[sys.argv.index('--') + 1 :] if '--' in sys.argv else []
    ap = argparse.ArgumentParser(prog='scene_render.py')
    ap.add_argument('--shot', required=True, help='a zyg.scene_shot/1 shot.json')
    ap.add_argument('--mode', default='draft', choices=('draft', 'full'))
    ap.add_argument('--frames', default='', help='a:b, inclusive; default the whole shot')
    ap.add_argument('--cpu', type=int, default=0, help='full: force CPU (skip the GPU probe)')
    ap.add_argument('--effects-only', type=int, default=0, help='full: holdout the geometry and write an RGBA element')
    ap.add_argument('--samples', type=int, default=0, help='full: override shot.render.full.samples')
    ap.add_argument(
        '--percent', type=int, default=100, help='resolution_percentage; a CPU proof render wants a small one'
    )
    ap.add_argument('--refresh-bounds', type=int, default=0, help='ignore effects_bounds.json')
    ap.add_argument('--no-encode', type=int, default=0, help='skip ffmpeg (frames only)')
    args = ap.parse_args(argv)

    from zyg_workflows import scene_shot as SS  # noqa: N814
    import render_offline_blender as RO  # noqa: N814

    shot = SS.resolve_positions(SS.load(os.path.abspath(args.shot)))
    sdir = SS.shot_dir(shot)
    out_dir = os.path.join(sdir, args.mode)
    os.makedirs(out_dir, exist_ok=True)

    sc = bpy.context.scene
    sc.frame_start = 1
    sc.frame_end = max(1, int(shot['frames']))
    sc.render.fps = int(shot.get('fps', 24))
    cam = bpy.data.objects.get('shot_cam') or sc.camera
    if cam is None:
        raise RuntimeError('no camera named "shot_cam" in %s' % bpy.data.filepath)
    sc.camera = cam

    fx_obs = effect_objects(sc)
    a, b = parse_frames(args.frames, sc.frame_start, sc.frame_end)

    bounds, fresh = effect_bounds(
        sc, fx_obs, os.path.join(sdir, 'effects_bounds.json'), refresh=bool(args.refresh_bounds)
    )

    if args.mode == 'draft':
        engine, w, h = setup_draft(sc, shot, percent=args.percent)
        setup = {'engine': engine, 'width': w, 'height': h}
    else:
        setup = setup_full(
            sc,
            shot,
            RO,
            samples=args.samples,
            cpu=bool(args.cpu),
            effects_only=bool(args.effects_only),
            fx_obs=fx_obs,
            percent=args.percent,
        )
        w, h = setup['width'], setup['height']

    placement, world_boxes = compute_placement(sc, cam, shot, SS, fx_obs, bounds, a, b, w, h)
    placement['mode'] = args.mode
    placement['bounds_cached'] = not fresh
    ppath = os.path.join(out_dir, 'placement.json')
    tmp = ppath + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as fh:
        json.dump(placement, fh, indent=1)
    os.replace(tmp, ppath)

    if args.mode == 'draft':
        coll = bpy.data.collections.get('draft_proxies')
        if coll is None:
            coll = bpy.data.collections.new('draft_proxies')
            sc.collection.children.link(coll)
        made = build_draft_proxies(sc, fx_obs, bounds, world_boxes, cam, coll)
        print('[render] draft proxies: %s' % ', '.join(made), flush=True)

    n, secs = render_range(sc, out_dir, a, b)
    fps_render = round(n / secs, 3) if secs > 0 else None

    mp4 = mov = None
    if not args.no_encode:
        crf = 22 if args.mode == 'draft' else 18
        mp4 = encode_mp4(out_dir, os.path.join(out_dir, '%s.mp4' % args.mode), sc.render.fps, a, n, crf)
        if args.mode == 'full' and args.effects_only:
            mov = encode_prores(out_dir, os.path.join(out_dir, 'effects_alpha.mov'), sc.render.fps, a, n)

    result = {
        'ok': True,
        'mode': args.mode,
        'frames': n,
        'frame_range': [a, b],
        'mp4': mp4,
        'mov': mov,
        'placement': ppath,
        'fps_render': fps_render,
        'sec_per_frame': round(secs / n, 4) if n else None,
        'render_seconds': round(secs, 2),
        'effects': [fid for fid, _ in fx_obs],
        'out_dir': out_dir,
        'setup': setup,
    }
    print(json.dumps(result), flush=True)


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:  # noqa: BLE001
        traceback.print_exc()
        print(json.dumps({'ok': False, 'error': '%s: %s' % (type(exc).__name__, exc)}), flush=True)
        sys.exit(1)
