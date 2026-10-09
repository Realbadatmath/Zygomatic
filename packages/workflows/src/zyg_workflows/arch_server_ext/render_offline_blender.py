# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""render_offline_blender.py — the script `blender -b --python` runs for r_ray.

It is NOT a kind builder, so it does not live under arch_blender_ext/. It builds
the drawing with arch_blender_build.build() (the very entry point
arch_assistant.start_blender drives with --in/--out), then places the studio's
own camera, a sun and a sky, switches the scene to CYCLES and renders one PNG.

    blender -b --python render_offline_blender.py -- \
        --in doc.json --out ray.png --blend scratch.blend \
        --samples 64 --width 1280 --height 720 --denoise 1 \
        --cam '{"p":[x,y,z],"t":[x,y,z],"fov":50,"ortho":0,"top":10}'

Frames: the studio is Y-up, Blender is Z-up, and the studio record loader maps
(x, y, z) -> (x, -z, y). The camera is mapped by exactly the same rule.
Camera orientation copies arch_assistant_ext/blender_power.py's `_bp_frame`:
the vector handed to `to_track_quat('Z', 'Y')` points FROM the target TOWARD the
camera, because a Blender camera looks down its own -Z.

Everything it prints on the last JSON line is the contract: {"ok":true,"png":...}.
Licences: Blender (GPL) is a subprocess; no Python package beyond the stdlib.
"""

import argparse
import json
import math
import os
import sys
import traceback

try:  # only importable inside Blender; guarded so that
    import bpy  # architecture_studio.ext_families() (which imports
    import mathutils  # every arch_server_ext/*.py) does not list an ERROR
except ImportError:  # for a file that is a Blender script, not a route set
    bpy = mathutils = None
import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)


HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

SKY_RGB = (0.62, 0.74, 0.85)  # the same sky blender_power's EEVEE/Workbench pass uses
SUN_ENERGY = 3.0
SUN_ANGLE_DEG = 2.0
SUN_ELEV_DEG = 35.0
SUN_AZIM_DEG = 225.0
EXPOSURE_EV = -1.2
SENSOR_MM = 36.0


def _num(v, d=0.0):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return float(d)
    return f if f == f and abs(f) != float('inf') else float(d)


def _scene_bounds(sc):
    lo = [1e9, 1e9, 1e9]
    hi = [-1e9, -1e9, -1e9]
    for ob in sc.objects:
        if ob.type != 'MESH':
            continue
        for c in ob.bound_box:
            w = ob.matrix_world @ mathutils.Vector(c)
            for i in range(3):
                lo[i] = min(lo[i], w[i])
                hi[i] = max(hi[i], w[i])
    if lo[0] > 1e8:
        lo, hi = [-5.0, -5.0, 0.0], [5.0, 5.0, 5.0]
    ctr = mathutils.Vector([(lo[i] + hi[i]) / 2.0 for i in range(3)])
    span = max(2.0, max(hi[i] - lo[i] for i in range(3)))
    return lo, hi, ctr, span


def _studio_to_blender(v):
    """(studio x, y up, z) -> (x, -z, y) — arch_blender_build's own record frame."""
    return mathutils.Vector((_num(v[0]), -_num(v[2]), _num(v[1])))


def place_camera(sc, cam_spec, span, ctr):
    """The studio camera, in Blender. Perspective: THREE's fov is the VERTICAL
    angle, so lens = (sensor/2) / tan(fov/2) with a VERTICAL sensor fit.
    Orthographic: THREE's `top` is the visible HALF height, Blender's
    ortho_scale the full one -> ortho_scale = 2 * top."""
    spec = cam_spec if isinstance(cam_spec, dict) else {}
    p = spec.get('p') if isinstance(spec.get('p'), list) and len(spec['p']) == 3 else None
    t = spec.get('t') if isinstance(spec.get('t'), list) and len(spec['t']) == 3 else None
    if p is None:
        v = mathutils.Vector((1.0, -1.0, 0.8)).normalized()
        pos = ctr + v * (span * 2.0 + 10.0)
        tgt = ctr
    else:
        pos = _studio_to_blender(p)
        tgt = _studio_to_blender(t) if t is not None else ctr
    cd = bpy.data.cameras.new('ro_cam')
    cam = bpy.data.objects.new('ro_cam', cd)
    sc.collection.objects.link(cam)
    sc.camera = cam
    cd.sensor_fit = 'VERTICAL'
    cd.sensor_height = SENSOR_MM
    cd.sensor_width = SENSOR_MM
    cd.clip_start = 0.02
    cd.clip_end = span * 20.0 + 5000.0
    if int(_num(spec.get('ortho'), 0)):
        cd.type = 'ORTHO'
        cd.ortho_scale = max(0.1, 2.0 * _num(spec.get('top'), max(1.0, span * 0.8)))
    else:
        cd.type = 'PERSP'
        fov = min(160.0, max(4.0, _num(spec.get('fov'), 50.0)))
        cd.lens = (SENSOR_MM / 2.0) / math.tan(math.radians(fov) / 2.0)
    cam.location = pos
    back = pos - tgt
    if back.length < 1e-6:
        back = mathutils.Vector((0.0, -1.0, 0.3))
    cam.rotation_euler = back.to_track_quat('Z', 'Y').to_euler()
    return cam, cd


def place_sun(sc, ctr, span):
    el, az = math.radians(SUN_ELEV_DEG), math.radians(SUN_AZIM_DEG)
    sv = mathutils.Vector((math.sin(az) * math.cos(el), math.cos(az) * math.cos(el), math.sin(el)))
    sd = bpy.data.lights.new('ro_sun', 'SUN')
    sd.energy = SUN_ENERGY
    try:
        sd.angle = math.radians(SUN_ANGLE_DEG)
    except Exception as _exc:  # noqa: BLE001
        _zyg_log.debug('sun angle not settable on this build: %s', _exc)
    sun = bpy.data.objects.new('ro_sun', sd)
    sc.collection.objects.link(sun)
    sun.location = ctr + sv * (span * 3.0 + 50.0)
    sun.rotation_euler = sv.to_track_quat('Z', 'Y').to_euler()
    return sv


def make_world(sc):
    if sc.world is None:
        sc.world = bpy.data.worlds.new('ro_world')
    w = sc.world
    w.use_nodes = True
    bg = w.node_tree.nodes.get('Background')
    if bg is None:
        for n in w.node_tree.nodes:
            if n.type == 'BACKGROUND':
                bg = n
                break
    if bg is not None:
        bg.inputs[0].default_value = (SKY_RGB[0], SKY_RGB[1], SKY_RGB[2], 1.0)
        try:
            bg.inputs[1].default_value = 1.0
        except Exception as _exc:  # noqa: BLE001
            _zyg_log.debug('world background strength not settable: %s', _exc)
    return w


def set_look(sc):
    vs = sc.view_settings
    got = ''
    for t in ('Filmic', 'AgX', 'Standard'):
        try:
            vs.view_transform = t
            got = t
            break
        except TypeError as _exc:
            _zyg_log.debug('view transform not accepted by this build: %s', _exc)
            continue
    try:
        vs.exposure = EXPOSURE_EV
    except Exception as _exc:  # noqa: BLE001
        _zyg_log.debug('view exposure not settable on this build: %s', _exc)
    return got


def enable_gpu(sc):
    """OPTIX, then CUDA, then HIP/ONEAPI; anything unavailable falls back to CPU.
    Returns the device string actually set plus the backend that took."""
    try:
        prefs = bpy.context.preferences.addons['cycles'].preferences
    except KeyError:
        try:
            bpy.ops.preferences.addon_enable(module='cycles')
            prefs = bpy.context.preferences.addons['cycles'].preferences
        except Exception:  # noqa: BLE001
            return 'CPU', ''
    for backend in ('OPTIX', 'CUDA', 'HIP', 'ONEAPI'):
        try:
            prefs.compute_device_type = backend
        except TypeError as _exc:
            _zyg_log.debug('compute device backend not accepted by this build: %s', _exc)
            continue
        try:
            devs = prefs.get_devices_for_type(backend)
        except Exception:  # noqa: BLE001
            try:
                prefs.get_devices()
                devs = [d for d in prefs.devices if d.type == backend]
            except Exception:  # noqa: BLE001
                devs = []
        got = False
        for d in devs:
            d.use = True
            got = True
        if got:
            sc.cycles.device = 'GPU'
            return 'GPU', backend
    sc.cycles.device = 'CPU'
    return 'CPU', ''


def main():
    argv = sys.argv[sys.argv.index('--') + 1 :] if '--' in sys.argv else []
    ap = argparse.ArgumentParser(prog='render_offline_blender.py')
    ap.add_argument('--in', dest='inp', required=True, help='Architecture Studio drawing JSON')
    ap.add_argument('--out', required=True, help='output .png')
    ap.add_argument('--blend', default='', help='scratch .blend arch_blender_build.build() writes')
    ap.add_argument('--cam', default='', help='camera JSON {p,t,fov,ortho,top} in studio coordinates')
    ap.add_argument('--samples', type=int, default=64)
    ap.add_argument('--width', type=int, default=1280)
    ap.add_argument('--height', type=int, default=720)
    ap.add_argument('--denoise', type=int, default=1)
    ap.add_argument('--cpu', type=int, default=0, help='force CPU (skip the GPU probe)')
    args = ap.parse_args(argv)

    sys.path.insert(0, HERE)
    from zyg_workflows import arch_blender_build as ABB  # noqa: N814  the same builder the studio uses

    with open(args.inp, 'r', encoding='utf-8') as fh:
        drawing = json.load(fh)
    blend = args.blend or (os.path.splitext(args.out)[0] + '.blend')
    info = ABB.build(drawing, blend, None)  # the --in/--out entry point, in-process

    sc = bpy.context.scene
    lo, hi, ctr, span = _scene_bounds(sc)
    cam_spec = json.loads(args.cam) if args.cam else {}
    cam, cd = place_camera(sc, cam_spec, span, ctr)
    sv = place_sun(sc, ctr, span)
    make_world(sc)
    transform = set_look(sc)

    sc.render.engine = 'CYCLES'
    device, backend = ('CPU', '') if args.cpu else enable_gpu(sc)
    cy = sc.cycles
    cy.samples = max(1, min(4096, int(args.samples)))
    cy.use_adaptive_sampling = True
    cy.use_denoising = bool(args.denoise)
    if cy.use_denoising:
        for dn in ('OPENIMAGEDENOISE', 'OPTIX'):
            try:
                cy.denoiser = dn
                break
            except TypeError as _exc:
                _zyg_log.debug('denoiser not accepted by this build: %s', _exc)
                continue
    sc.render.resolution_x = max(16, min(4096, int(args.width)))
    sc.render.resolution_y = max(16, min(4096, int(args.height)))
    sc.render.resolution_percentage = 100
    sc.render.image_settings.file_format = 'PNG'
    sc.render.image_settings.color_mode = 'RGBA'
    sc.render.film_transparent = False
    sc.render.use_file_extension = False
    sc.render.filepath = os.path.abspath(args.out)

    bpy.context.view_layer.update()
    bpy.ops.render.render(write_still=True)
    png = os.path.abspath(args.out)
    print(
        json.dumps(
            {
                'ok': os.path.exists(png),
                'png': png,
                'bytes': os.path.getsize(png) if os.path.exists(png) else 0,
                'objects': info.get('objects'),
                'skipped': info.get('skipped'),
                'engine': 'CYCLES',
                'device': device,
                'backend': backend,
                'samples': cy.samples,
                'denoise': bool(cy.use_denoising),
                'cam': cd.type,
                'lens': round(cd.lens, 3),
                'ortho_scale': round(cd.ortho_scale, 3),
                'cam_loc': [round(c, 3) for c in cam.location],
                'sun_dir': [round(c, 4) for c in sv],
                'transform': transform,
                'width': sc.render.resolution_x,
                'height': sc.render.resolution_y,
                'lo': [round(c, 2) for c in lo],
                'hi': [round(c, 2) for c in hi],
            }
        ),
        flush=True,
    )


if __name__ == '__main__':
    try:
        main()
    except Exception as e:  # noqa: BLE001 — one JSON line is the contract
        traceback.print_exc()
        print(json.dumps({'ok': False, 'error': '%s: %s' % (type(e).__name__, e)}), flush=True)
        sys.exit(1)
