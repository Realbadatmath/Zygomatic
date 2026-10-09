# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""fit_preview.py — stand every groom on the clay base body and render it.
blender -b --factory-startup --python fit_preview.py -- <body.glb> <groom_dir> <out_dir> [ids...]

This is the client's fit, done first where it can be LOOKED AT. char_hair.js
repeats exactly these two mappings:

  cards   (MakeHuman)      head frame:  world = headOrigin + local * headW
                           headOrigin = (cx, cy, zTop) of the head band,
                           headW = its X extent
  strands (Blender Studio) skull frame: world = skullCentre + local * skullR
                           from a least-squares sphere through the head band

Both frames are MEASURED on whichever body is standing, so a groom modelled on
MakeHuman's hm08 and a groom grown on Einar's scalp land on the same clay head
without either one carrying a hard-coded offset."""

import json
import math
import os
import sys

import bpy
from mathutils import Vector


def sphere_fit(pts):
    n = len(pts)
    if n < 8:
        return None, None
    A = [[0.0] * 4 for _ in range(4)]
    b = [0.0] * 4
    for p in pts:
        row = (2.0 * p[0], 2.0 * p[1], 2.0 * p[2], 1.0)
        rhs = p[0] * p[0] + p[1] * p[1] + p[2] * p[2]
        for i in range(4):
            for j in range(4):
                A[i][j] += row[i] * row[j]
            b[i] += row[i] * rhs
    M = [A[i][:] + [b[i]] for i in range(4)]
    for c in range(4):
        piv = max(range(c, 4), key=lambda r: abs(M[r][c]))
        if abs(M[piv][c]) < 1e-12:
            return None, None
        M[c], M[piv] = M[piv], M[c]
        for r in range(4):
            if r == c:
                continue
            f = M[r][c] / M[c][c]
            for k in range(c, 5):
                M[r][k] -= f * M[c][k]
    x = [M[i][4] / M[i][i] for i in range(4)]
    centre = Vector((x[0], x[1], x[2]))
    r2 = x[3] + centre.length_squared
    return (centre, math.sqrt(r2)) if r2 > 0 else (None, None)


def body_frames(objs):
    """Both frames of the standing body, in Blender space (+Z up).

    headH is 0.13 of the body's height, the same fraction char_hair.js uses, so
    the head band here is the head band there."""
    pts = []
    for ob in objs:
        if ob.type != 'MESH':
            continue
        mw = ob.matrix_world
        pts.extend(mw @ v.co for v in ob.data.vertices)
    if not pts:
        return None
    zs = [p.z for p in pts]
    zTop, zMin = max(zs), min(zs)
    H = zTop - zMin
    headH = 0.13 * H
    chin = zTop - headH
    band = [p for p in pts if p.z > chin]
    xs = [p.x for p in band]
    ys = [p.y for p in band]
    cx = (min(xs) + max(xs)) * 0.5
    cy = (min(ys) + max(ys)) * 0.5
    headW = max(1e-4, max(xs) - min(xs))
    # the skull dome: the top DOME_FRAC of the head band's own height. The
    # converter takes the same fraction of the donor surface, so the two
    # spheres describe the same part of a skull.
    DOME_FRAC = 0.45
    dome = [p for p in pts if p.z > zTop - DOME_FRAC * headH]
    centre, radius = sphere_fit(dome)
    return {
        'headOrigin': (cx, cy, zTop),
        'headW': headW,
        'skullCentre': tuple(centre) if centre else None,
        'skullRadius': radius,
        'H': H,
        'headH': headH,
        'band': len(band),
        'dome': len(dome),
    }


def main():
    argv = sys.argv[sys.argv.index('--') + 1 :]
    body_glb, groom_dir, out_dir = argv[0], argv[1], argv[2]
    only = set(argv[3:]) or None
    os.makedirs(out_dir, exist_ok=True)

    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=body_glb)
    body = [o for o in bpy.context.scene.objects if o.type == 'MESH']
    for o in body:
        o.data.materials.clear()
    clay = bpy.data.materials.new('clay')
    clay.use_nodes = True
    clay.node_tree.nodes['Principled BSDF'].inputs['Base Color'].default_value = (0.62, 0.58, 0.53, 1)
    clay.node_tree.nodes['Principled BSDF'].inputs['Roughness'].default_value = 0.8
    for m in bpy.data.materials:
        if hasattr(m, 'surface_render_method'):
            m.surface_render_method = 'DITHERED'
    for o in body:
        o.data.materials.append(clay)
    F = body_frames(body)
    if not F:
        print('ZYGFIT' + json.dumps({'error': 'no body geometry'}))
        return

    # lights + camera
    for nm, loc, e in (
        ('key', (2.2, -3.0, 2.4), 900.0),
        ('fill', (-2.6, -2.2, 1.6), 380.0),
        ('rim', (0.0, 3.2, 2.6), 520.0),
    ):
        lt = bpy.data.lights.new(nm, 'POINT')
        lt.energy = e
        lt.shadow_soft_size = 0.6
        bpy.context.scene.collection.objects.link(bpy.data.objects.new(nm, lt))
        bpy.data.objects[nm].location = loc
    cam_d = bpy.data.cameras.new('cam')
    cam_d.lens = 85
    cam = bpy.data.objects.new('cam', cam_d)
    bpy.context.scene.collection.objects.link(cam)
    bpy.context.scene.camera = cam
    sc = bpy.context.scene
    sc.render.engine = 'BLENDER_EEVEE_NEXT'
    sc.render.resolution_x = 420
    sc.render.resolution_y = 520
    sc.render.film_transparent = False
    sc.world = bpy.data.worlds.new('w')
    sc.world.use_nodes = True
    sc.world.node_tree.nodes['Background'].inputs['Color'].default_value = (0.05, 0.06, 0.08, 1)

    hx, hy, hz = F['headOrigin']
    hw = F['headW']
    out, problems = [], []
    files = sorted(f for f in os.listdir(groom_dir) if f.endswith('.glb'))
    for fn in files:
        gid = os.path.splitext(fn)[0]
        if only and gid not in only:
            continue
        before = set(o.name for o in bpy.context.scene.objects)
        try:
            bpy.ops.import_scene.gltf(filepath=os.path.join(groom_dir, fn))
        except Exception as e:  # noqa: BLE001
            problems.append(f'{gid}: import {e!r}')
            continue
        new = [o for o in bpy.context.scene.objects if o.name not in before]
        meshes = [o for o in new if o.type == 'MESH']
        kind = 'strands' if 'blender_studio' in groom_dir or _is_strands(meshes) else 'cards'
        if kind == 'strands' and F['skullCentre']:
            o0 = Vector(F['skullCentre'])
            s = F['skullRadius']
        else:
            o0 = Vector((hx, hy, hz))
            s = hw
        # ROOTS ONLY. The glTF importer hangs the meshes under a scene root
        # that already carries the axis conversion; scaling and moving every
        # imported object applied the fit twice to the children and dropped
        # every groom over the face.
        names = {o.name for o in new}
        roots = [o for o in new if (o.parent is None or o.parent.name not in names)]
        for o in roots:
            o.scale = (o.scale.x * s, o.scale.y * s, o.scale.z * s)
            o.location = (o0.x + o.location.x * s, o0.y + o.location.y * s, o0.z + o.location.z * s)
        for o in meshes:
            for mm in o.data.materials:
                if mm and hasattr(mm, 'surface_render_method'):
                    mm.surface_render_method = 'DITHERED'
            if not o.data.materials:
                m = bpy.data.materials.new('hair')
                m.use_nodes = True
                m.node_tree.nodes['Principled BSDF'].inputs['Base Color'].default_value = (0.09, 0.05, 0.03, 1)
                m.node_tree.nodes['Principled BSDF'].inputs['Roughness'].default_value = 0.45
                o.data.materials.append(m)

        # frame the head from the front and from the side
        for tag, ang in (('front', 0.0), ('side', math.pi * 0.5)):
            r = hw * 5.0
            cam.location = (o0.x + r * math.sin(ang), o0.y - r * math.cos(ang), hz - hw * 0.35)
            d = Vector((o0.x, o0.y, hz - hw * 0.45)) - cam.location
            cam.rotation_euler = d.to_track_quat('-Z', 'Y').to_euler()
            sc.render.filepath = os.path.join(out_dir, f'{gid}_{tag}.png')
            bpy.ops.render.render(write_still=True)
        out.append({'id': gid, 'kind': kind})
        for o in new:
            bpy.data.objects.remove(o, do_unlink=True)

    print('ZYGFIT' + json.dumps({'frames': F, 'rendered': out, 'problems': problems}))


def _is_strands(meshes):
    return any(not m.data.materials for m in meshes)


main()
