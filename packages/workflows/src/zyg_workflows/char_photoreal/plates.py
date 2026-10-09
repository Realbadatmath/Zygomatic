#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""char_photoreal — the plates section, verbatim lines 365-744 of the original module."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import time
import numpy as np

from zyg_workflows.char_photoreal.constants import (
    BLENDER,
    BODIES,
    BODY_VIEWS,
    EYE_VIEWS,
    HAND_VIEWS,
    HEAD_VIEWS,
    HERE,
    OUT_ROOT,
    PACK_DIR,
    SIZE,
    ZOOM_VIEWS,
)


# ── the Blender half ───────────────────────────────────────────────────────
_BL_SCRIPT = r"""
import json, math, os, sys
import numpy as np
import bpy, mathutils

CFG = json.load(open(sys.argv[sys.argv.index('--') + 1]))
sys.path.insert(0, CFG['crews'])
sys.path.insert(0, os.path.join(CFG['crews'], 'prop_mesh'))
import pass_lib

bpy.ops.wm.read_factory_settings(use_empty=True)
sc = bpy.context.scene
sc.render.engine = 'CYCLES'
sc.cycles.device = 'CPU'
sc.render.resolution_x = CFG['size']
sc.render.resolution_y = CFG['size']
sc.render.resolution_percentage = 100
sc.render.film_transparent = True
sc.world = bpy.data.worlds.new('w')
sc.world.use_nodes = True
sc.world.node_tree.nodes['Background'].inputs[0].default_value = (0.05, 0.05, 0.05, 1)

bpy.ops.import_scene.gltf(filepath=CFG['glb'])
meshes = [o for o in bpy.context.scene.objects if o.type == 'MESH']
if not meshes:
    raise SystemExit('no mesh in %s' % CFG['glb'])
body = max(meshes, key=lambda o: len(o.data.vertices))
for ob in meshes:
    ob.pass_index = 2
body.pass_index = 1

mat = bpy.data.materials.new('plate_grey')
mat.use_nodes = True
bsdf = mat.node_tree.nodes['Principled BSDF']
bsdf.inputs['Base Color'].default_value = (0.5, 0.5, 0.5, 1)
bsdf.inputs['Roughness'].default_value = 0.9
for ob in meshes:
    ob.data.materials.clear()
    ob.data.materials.append(mat)
bpy.context.view_layer.update()

def bbox(obs):
    lo = mathutils.Vector((1e9, 1e9, 1e9)); hi = mathutils.Vector((-1e9, -1e9, -1e9))
    for ob in obs:
        for c in ob.bound_box:
            w = ob.matrix_world @ mathutils.Vector(c)
            lo = mathutils.Vector((min(lo[k], w[k]) for k in range(3)))
            hi = mathutils.Vector((max(hi[k], w[k]) for k in range(3)))
    return lo, hi

lo, hi = bbox(meshes)
height = hi[2] - lo[2]
# The Blender Studio bundle is authored Y-up (a proper glTF), so after import
# it STANDS along Blender Z. Refuse anything else rather than guess.
if not (1.2 < height < 2.4) or height < (hi[1] - lo[1]) or height < (hi[0] - lo[0]):
    raise SystemExit('body does not stand along Z after import: extents x=%.3f y=%.3f z=%.3f'
                     % (hi[0] - lo[0], hi[1] - lo[1], height))

# ── world-space geometry of the body, per loop triangle, with UVs ──────────
dg = bpy.context.evaluated_depsgraph_get()
ob_ev = body.evaluated_get(dg)
me = ob_ev.to_mesh()
me.calc_loop_triangles()
try:
    me.calc_normals_split()
except (AttributeError, RuntimeError) as _exc:
    _zyg_log.debug('split normals not computed on this build: %s', _exc)
uvl = me.uv_layers.active.data
M = ob_ev.matrix_world
Mn = M.to_3x3().inverted().transposed()
tris = me.loop_triangles
T = len(tris)
P = np.zeros((T, 3, 3), np.float32); N = np.zeros((T, 3, 3), np.float32); UV = np.zeros((T, 3, 2), np.float32)
vco = np.array([ (M @ v.co)[:] for v in me.vertices ], np.float32)
vno = np.array([ (Mn @ v.normal).normalized()[:] for v in me.vertices ], np.float32)
loop_uv = np.array([ d.uv[:] for d in uvl ], np.float32)
loop_n = np.array([ (Mn @ l.normal).normalized()[:] for l in me.loops ], np.float32)
for i, t in enumerate(tris):
    vi = t.vertices; li = t.loops
    P[i] = vco[list(vi)]
    UV[i] = loop_uv[list(li)]
    ln = loop_n[list(li)]
    N[i] = ln if np.isfinite(ln).all() and (np.abs(ln).sum(1) > 0).all() else vno[list(vi)]
ob_ev.to_mesh_clear()
np.savez_compressed(CFG['geom'], P=P, N=N, UV=UV)

# hand boxes: in the A-pose the hands are the outermost 22 % of the half-span
# on each side; the mean of those vertices is the hand's centre
cx = 0.5 * (lo[0] + hi[0])
hand_c = {}
for hv, sel in (('hand_l', vco[:, 0] > cx + 0.78 * (hi[0] - cx)),
                ('hand_r', vco[:, 0] < cx - 0.78 * (cx - lo[0]))):
    if sel.sum() > 50:
        hand_c[hv] = mathutils.Vector(tuple(float(x) for x in vco[sel].mean(0)))

# head box: the top of the body above the chin line, measured from the mesh —
# eyes are their own objects in the bundle and sit at the head's centre height
eyes = [o for o in meshes if o is not body]
eye_c = {}
for o in eyes:
    olo, ohi = bbox([o])
    ec = (olo + ohi) * 0.5
    eye_c['eye_l' if ec[0] > 0.5 * (lo[0] + hi[0]) else 'eye_r'] = ec
if eyes:
    elo, ehi = bbox(eyes)
    eye_z = 0.5 * (elo[2] + ehi[2])
    head_c = mathutils.Vector((0.5 * (lo[0] + hi[0]), 0.5 * (elo[1] + ehi[1]) + 0.02, eye_z - 0.02))
    head_h = 2.0 * (hi[2] - eye_z) + 0.06
else:
    head_c = mathutils.Vector((0.5 * (lo[0] + hi[0]), 0.5 * (lo[1] + hi[1]), hi[2] - 0.12))
    head_h = 0.26

cam_d = bpy.data.cameras.new('cam')
cam_d.lens = 50.0
cam_d.sensor_fit = 'VERTICAL'
cam_d.sensor_height = 24.0
cam = bpy.data.objects.new('cam', cam_d)
sc.collection.objects.link(cam)
sc.camera = cam

key = bpy.data.objects.new('key', bpy.data.lights.new('key', type='SUN'))
key.data.energy = 3.0
sc.collection.objects.link(key)
key.rotation_euler = (math.radians(55), 0, math.radians(35))

body_target = (lo + hi) * 0.5
out = {}
for vid, v in CFG['views'].items():
    a, e = math.radians(v['az']), math.radians(v['el'])
    if vid.startswith('head'):
        target, extent, fill, lens = head_c, head_h, 0.72, 85.0
    elif vid.startswith('hand'):
        if vid not in hand_c:
            continue
        target, extent, fill, lens = hand_c[vid], 0.30, 0.72, 85.0
    elif vid.startswith('eye'):
        if vid not in eye_c:
            continue
        target, extent, fill, lens = eye_c[vid], 0.10, 0.72, 85.0
    elif vid.startswith('torso'):
        target = mathutils.Vector((body_target[0], body_target[1], lo[2] + 0.66 * height))
        extent, fill, lens = 0.46 * height, 0.86, 85.0
    elif vid.startswith('legs'):
        target = mathutils.Vector((body_target[0], body_target[1], lo[2] + 0.26 * height))
        extent, fill, lens = 0.54 * height, 0.86, 85.0
    else:
        target, extent, fill, lens = body_target, height, 0.86, 50.0
    cam_d.lens = lens
    dist = (extent / fill) * (lens / cam_d.sensor_height)
    cam.location = target + mathutils.Vector((dist * math.cos(e) * math.sin(a),
                                              -dist * math.cos(e) * math.cos(a),
                                              dist * math.sin(e)))
    cam.rotation_euler = (target - cam.location).to_track_quat('-Z', 'Y').to_euler()
    bpy.context.view_layer.update()
    d = pass_lib.render_set(vid, CFG['passdir'], scene=sc, samples=CFG['samples'])
    out[vid] = {'dir': d, 'lens': lens, 'sensor_h': cam_d.sensor_height,
                'cam_world': [list(r) for r in cam.matrix_world],
                'dist': dist, 'target': list(target)}
json.dump({'views': out, 'height_m': height, 'lo': list(lo), 'hi': list(hi),
           'head_c': list(head_c), 'head_h': head_h, 'tris': int(T),
           'hand_c': {k: list(v) for k, v in hand_c.items()},
           'eye_c': {k: list(v) for k, v in eye_c.items()}},
          open(CFG['report'], 'w'), indent=1)
print('PHOTOREAL_PLATES_OK')
"""


def work_dir(body):
    return os.path.join(OUT_ROOT, body)


def _run_blender(cfg, log):
    with tempfile.TemporaryDirectory() as td:
        sp = os.path.join(td, 'photoreal_plates.py')
        cp = os.path.join(td, 'cfg.json')
        with open(sp, 'w', encoding='utf-8') as fh:
            fh.write(_BL_SCRIPT)
        with open(cp, 'w', encoding='utf-8') as fh:
            json.dump(cfg, fh)
        cmd = [BLENDER, '-b', '--factory-startup', '-P', sp, '--', cp]
        log('[plates] ' + ' '.join(cmd))
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=7200)
        if 'PHOTOREAL_PLATES_OK' not in (r.stdout or ''):
            tail = ((r.stdout or '') + (r.stderr or ''))[-3000:]
            raise RuntimeError(f'blender failed (exit {r.returncode}):\n{tail}')
        with open(cfg['report'], encoding='utf-8') as fh:
            return json.load(fh)


def _copy_plates(src_body, wd, log):
    """Reuse another body's Blender output when the mesh and the cameras are
    the same (an écorché is the realistic body's own GLB). Copies plates/,
    passes/, geom.npz, cameras.json and blender_report.json (~270 MB) instead
    of spending nine CPU minutes rendering identical plates. Returns False if
    the source is not complete, so the caller renders as usual."""
    src = work_dir(src_body)
    dirs = ['plates', 'passes']
    files = ['geom.npz', 'cameras.json', 'blender_report.json']
    missing = [n for n in dirs + files if not os.path.exists(os.path.join(src, n))]
    if missing:
        log(f'[plates] plates_from {src_body}: missing {", ".join(missing)} — rendering instead')
        return False
    os.makedirs(wd, exist_ok=True)
    t0 = time.time()
    for d in dirs:
        dst = os.path.join(wd, d)
        if os.path.isdir(dst):
            shutil.rmtree(dst)
        shutil.copytree(os.path.join(src, d), dst)
    for f in files:
        shutil.copy2(os.path.join(src, f), os.path.join(wd, f))
    cams_p = os.path.join(wd, 'cameras.json')
    cams = json.load(open(cams_p))
    cams['body'] = os.path.basename(wd)
    cams['plates_from'] = src_body
    with open(cams_p, 'w', encoding='utf-8') as fh:
        json.dump(cams, fh, indent=1)
    log(
        f'[plates] copied plates/passes/geom/cameras from {src_body} '
        f'({len(cams["views"])} views) in {time.time() - t0:.0f}s — same mesh, same cameras'
    )
    return True


def stage_plates(body, log, force=False, samples=24):
    """Blender → passes/<view>/ (rgb, depth, index), plates/<view>_depth.png,
    geom.npz, cameras.json."""
    import zyg_workflows.geom.conditioning as COND
    import zyg_workflows.geom.passes_io as PIO
    from PIL import Image

    wd = work_dir(body)
    cams_p = os.path.join(wd, 'cameras.json')
    if os.path.isfile(cams_p) and os.path.isfile(os.path.join(wd, 'geom.npz')) and not force:
        log(f'[plates] {body}: up to date')
        return json.load(open(cams_p))
    src_body = BODIES[body].get('plates_from')
    if src_body and _copy_plates(src_body, wd, log):
        return json.load(open(cams_p))
    os.makedirs(os.path.join(wd, 'plates'), exist_ok=True)
    passdir = os.path.join(wd, 'passes')
    if os.path.isdir(passdir):
        shutil.rmtree(passdir)
    os.makedirs(passdir)
    views = dict(BODY_VIEWS)
    views.update(HEAD_VIEWS)
    views.update(HAND_VIEWS)
    views.update(EYE_VIEWS)
    views.update(ZOOM_VIEWS)
    cfg = {
        'crews': HERE,
        'glb': os.path.join(PACK_DIR, BODIES[body]['file']),
        'size': SIZE,
        'samples': int(samples),
        'passdir': passdir,
        'geom': os.path.join(wd, 'geom.npz'),
        'report': os.path.join(wd, 'blender_report.json'),
        'views': views,
    }
    t0 = time.time()
    rep = _run_blender(cfg, log)
    log(
        f'[plates] blender rendered {len(rep["views"])} views in {time.time() - t0:.0f}s, '
        f'{rep["tris"]} triangles dumped'
    )
    cams = {'body': body, 'size': SIZE, 'height_m': rep['height_m'], 'views': {}}
    for vid, v in views.items():
        if vid not in rep['views']:
            log(f'[plates] {vid}: no target on this body, skipped')
            continue
        r = rep['views'][vid]
        ps = PIO.load_set(r['dir'])
        # body AND eyes: the eyeballs are their own objects (index 2) and a
        # depth plate with two black holes where the eyes sit asks the render
        # model for empty sockets
        mask = ps.valid & (ps.index > 0)
        if not mask.any():
            mask = ps.mask(1)
        # the depth plate normalised over the SUBJECT (body_plates convention)
        depth = COND.depth_map(ps, mask=mask)
        Image.fromarray(depth).save(os.path.join(wd, 'plates', f'{vid}_depth.png'))
        np.save(os.path.join(wd, 'plates', f'{vid}_z.npy'), ps.depth.astype(np.float32))
        Image.fromarray((mask.astype(np.uint8) * 255)).save(os.path.join(wd, 'plates', f'{vid}_mask.png'))
        cams['views'][vid] = {
            'az': v['az'],
            'el': v['el'],
            'lens': r['lens'],
            'sensor_h': r['sensor_h'],
            'cam_world': r['cam_world'],
            'coverage': round(float(mask.mean()), 4),
            'kind': vid.split('_')[0],
        }
    with open(cams_p, 'w', encoding='utf-8') as fh:
        json.dump(cams, fh, indent=1)
    return cams


# ── camera model ───────────────────────────────────────────────────────────
class Cam:
    """Blender camera → pixel. Camera looks down its local -Z, +Y is up;
    sensor_fit VERTICAL so the vertical FOV is governed by sensor_h."""

    def __init__(self, v, size):
        M = np.array(v['cam_world'], np.float64)
        self.R = M[:3, :3]
        self.t = M[:3, 3]
        self.f = v['lens'] / v['sensor_h'] * size
        self.size = size

    def to_cam(self, P):
        return (P - self.t) @ self.R  # R is orthonormal: R^T (P - t)

    def project(self, P):
        c = self.to_cam(P)
        z = -c[..., 2]
        with np.errstate(divide='ignore', invalid='ignore'):
            u = self.size / 2.0 + self.f * c[..., 0] / z
            v = self.size / 2.0 - self.f * c[..., 1] / z
        return u, v, z

    def forward(self):
        return -self.R[:, 2]


def load_geom(body):
    g = np.load(os.path.join(work_dir(body), 'geom.npz'))
    return g['P'].astype(np.float64), g['N'].astype(np.float64), g['UV'].astype(np.float64)


def _sample_nearest(img, u, v):
    H, W = img.shape[:2]
    ui = np.clip(np.round(u).astype(int), 0, W - 1)
    vi = np.clip(np.round(v).astype(int), 0, H - 1)
    return img[vi, ui]


def stage_selfcheck(body, log, min_frac=0.97):
    """Re-project the dumped triangles into every view and demand they land on
    the index mask. Fails loudly on a camera-convention error.

    The mask is sampled one pixel dilated: a vertex exactly on the silhouette
    rasterises half in, half out, and that edge band is the only thing that
    ever misses on a correct camera. It is mesh-dependent — the female body's
    body_top lost 0.966 of its facing vertices to it where the male lost
    0.975 — while a wrong convention misses by a landslide, not by a pixel."""
    from scipy.ndimage import binary_dilation

    cams = json.load(open(os.path.join(work_dir(body), 'cameras.json')))
    P, N, _ = load_geom(body)
    V = P.reshape(-1, 3)
    Nv = N.reshape(-1, 3)
    wd = work_dir(body)
    worst = 1.0
    for vid, v in cams['views'].items():
        cam = Cam(v, cams['size'])
        z_img = np.load(os.path.join(wd, 'plates', f'{vid}_z.npy'))
        mask = binary_dilation(z_img == z_img)
        u, vv, z = cam.project(V)
        to_cam = cam.t - V
        to_cam /= np.linalg.norm(to_cam, axis=1, keepdims=True)
        facing = (Nv * to_cam).sum(1) > 0.2
        inside = (u >= 0) & (u < cams['size']) & (vv >= 0) & (vv < cams['size']) & (z > 0)
        zs = _sample_nearest(z_img, u, vv)
        vis = facing & inside & np.isfinite(zs) & (np.abs(zs - z) < 0.02)
        on = _sample_nearest(mask, u, vv)
        frac = float(on[facing & inside].mean()) if (facing & inside).any() else 0.0
        # of the vertices the camera can see, how many pass the Z test — the
        # convention check for the Z pass being camera-space depth
        zfrac = float(vis[facing & inside].mean()) if (facing & inside).any() else 0.0
        worst = min(worst, frac)
        log(f'[selfcheck] {vid:11s} on-mask {frac:.3f}  z-visible {zfrac:.3f}')
        if frac < min_frac:
            raise RuntimeError(
                f'{vid}: only {frac:.3f} of facing vertices land on the rendered mask — camera convention is wrong'
            )
    log(f'[selfcheck] OK, worst on-mask {worst:.3f}')
    return worst
