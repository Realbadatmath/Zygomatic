# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""arch_reference_build.scene — the empty scene, the cameras, the lighting and
the renders (lines 321-693 of the original single file, moved verbatim).
"""

import logging as _zyg_logging
import math
import os

import bmesh
import bpy
import mathutils

from .api import asset_objects
from .base import _REF_OBJS, log

_zyg_log = _zyg_logging.getLogger('zyg_workflows.arch_reference_build')


# ── scene, framing, render ───────────────────────────────────────────────────
def _empty_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    sc = bpy.context.scene
    sc.unit_settings.system = 'METRIC'
    sc.unit_settings.scale_length = 1.0
    return sc


def _bounds(objs):
    lo = [1e18] * 3
    hi = [-1e18] * 3
    dg = bpy.context.evaluated_depsgraph_get()
    found = False
    for ob in objs:
        if ob.type not in ('MESH', 'CURVE', 'SURFACE', 'META', 'FONT'):
            continue
        try:
            ev = ob.evaluated_get(dg)
            corners = [ev.matrix_world @ mathutils.Vector(c) for c in ev.bound_box]
        except Exception as _exc:  # noqa: BLE001
            _zyg_log.debug('object bounds skipped, not evaluable: %s', _exc)
            continue
        for c in corners:
            found = True
            for k in range(3):
                lo[k] = min(lo[k], c[k])
                hi[k] = max(hi[k], c[k])
    if not found:
        return None
    return lo, hi


def _tris(objs):
    dg = bpy.context.evaluated_depsgraph_get()
    n = 0
    for ob in objs:
        if ob.type != 'MESH':
            continue
        try:
            me = ob.evaluated_get(dg).to_mesh()
        except Exception as _exc:  # noqa: BLE001
            _zyg_log.debug('object mesh skipped, not evaluable: %s', _exc)
            continue
        bm = bmesh.new()
        bm.from_mesh(me)
        bmesh.ops.triangulate(bm, faces=bm.faces[:])
        n += len(bm.faces)
        bm.free()
        ob.evaluated_get(dg).to_mesh_clear()
    return n


DIRS = {
    'iso': (1.0, -1.0, 0.8),
    'side': (0.0, -1.0, 0.0),
    'other_side': (0.0, 1.0, 0.0),
    'front': (1.0, 0.0, 0.0),
    'back': (-1.0, 0.0, 0.0),
    'top': (0.0, 0.0, 1.0),
    'bottom': (0.0, 0.0, -1.0),
}
ROLE_DIR = {
    'view_side': 'side',
    'view_side_other': 'other_side',
    'view_front': 'front',
    'view_back': 'back',
    'view_top': 'top',
    'view_bottom': 'bottom',
    'section': 'front',
}


def _aim(cam, view, d):
    """Point the camera at the subject, with the roll SETTLED rather than left
    to to_track_quat: looking straight down, the up hint is parallel to the
    view and Blender is free to pick any roll, which turns a plan on its side."""
    if view == 'top':
        cam.rotation_euler = (0.0, 0.0, 0.0)
    elif view == 'bottom':
        cam.rotation_euler = (0.0, math.pi, 0.0)
    else:
        cam.rotation_euler = (-d).to_track_quat('-Z', 'Y').to_euler()


def _setup(width, height, engine):
    sc = bpy.context.scene
    sc.render.resolution_x = int(width)
    sc.render.resolution_y = int(height)
    sc.render.resolution_percentage = 100
    sc.render.image_settings.file_format = 'PNG'
    sc.render.image_settings.color_mode = 'RGBA'
    # A plan is a DOCUMENT, not a photograph: under Filmic/AgX its white paper
    # renders mid-grey and its black lines wash out — exactly the contrast you
    # are trying to read the shape against.
    try:
        sc.view_settings.view_transform = 'Standard'
        sc.view_settings.look = 'None'
        sc.view_settings.exposure = 0.0
        sc.view_settings.gamma = 1.0
    except (AttributeError, TypeError) as _exc:
        _zyg_log.debug('neutral view transform not available on this build: %s', _exc)
    if engine == 'eevee':
        sc.render.engine = 'BLENDER_EEVEE_NEXT' if 'BLENDER_EEVEE_NEXT' in _engines() else 'BLENDER_EEVEE'
        _world(sc)
    else:
        sc.render.engine = 'BLENDER_WORKBENCH'
    return sc


def _ortho_span(across_m, up_m, k=1.12):
    """The ortho_scale that fits `across_m` horizontally AND `up_m` vertically
    in the scene's current frame.

    ortho_scale spans the LONGER side of the frame, so a subject taller than it
    is wide loses exactly the aspect ratio off the top unless the scale is
    grown for it: the 38 m rig of this 51 m ship went off the top of every 16:9
    view until this existed."""
    sc = bpy.context.scene
    w = float(sc.render.resolution_x or 1280)
    h = float(sc.render.resolution_y or 720)
    a, u = abs(float(across_m)), abs(float(up_m))
    return (max(a, u * w / max(1.0, h)) if w >= h else max(u, a * h / max(1.0, w))) * k


def _projected(objs, quat):
    """(width, height) of `objs` as the camera with this rotation sees them."""
    b = _bounds(objs)
    if b is None:
        return (1.0, 1.0)
    lo, hi = b
    right = quat @ mathutils.Vector((1.0, 0.0, 0.0))
    up = quat @ mathutils.Vector((0.0, 1.0, 0.0))
    pts = [
        mathutils.Vector((hi[0] if i & 1 else lo[0], hi[1] if i & 2 else lo[1], hi[2] if i & 4 else lo[2]))
        for i in range(8)
    ]
    us = [c.dot(right) for c in pts]
    vs = [c.dot(up) for c in pts]
    return (max(max(us) - min(us), 0.5), max(max(vs) - min(vs), 0.5))


def _make_cam(view, bound_objs):
    """One orthographic camera framing `bound_objs`. Returned so two passes can
    share it exactly — an overlay whose halves were framed separately is not an
    overlay."""
    sc = bpy.context.scene
    b = _bounds(bound_objs) or _bounds(list(bpy.data.objects))
    if b is None:
        return None
    lo, hi = b
    ctr = mathutils.Vector([(lo[k] + hi[k]) / 2.0 for k in range(3)])
    size = max(hi[k] - lo[k] for k in range(3)) or 1.0
    d = mathutils.Vector(DIRS.get(view, DIRS['iso'])).normalized()
    cd = bpy.data.cameras.new('refcam')
    cd.type = 'ORTHO'
    # ortho_scale spans the LONGER side of the frame, so a subject taller than
    # it is wide is cropped by exactly the aspect ratio unless it is grown:
    # the 38 m rig of a 51 m ship went off the top of every 16:9 view.
    if view == 'top':
        q = mathutils.Euler((0.0, 0.0, 0.0)).to_quaternion()
    elif view == 'bottom':
        q = mathutils.Euler((0.0, math.pi, 0.0)).to_quaternion()
    else:
        q = (-d).to_track_quat('-Z', 'Y')
    cd.ortho_scale = _ortho_span(*_projected(bound_objs, q), k=1.12)
    cd.clip_start = 0.01
    cd.clip_end = size * 40.0 + 100.0
    cam = bpy.data.objects.new('refcam', cd)
    cam['zyg_ref'] = 1
    sc.collection.objects.link(cam)
    cam.location = ctr + d * (size * 4.0 + 5.0)
    _aim(cam, view, d)
    sc.camera = cam
    return cam


def _shoot(png, transparent=False):
    sc = bpy.context.scene
    sc.render.film_transparent = bool(transparent)
    sc.render.filepath = png
    bpy.ops.render.render(write_still=True)
    return png if os.path.exists(png) else ''


def _render(view, out_png, width, height, engine):
    """A plain picture of the asset alone."""
    objs = asset_objects()
    sc = _setup(width, height, engine)
    cam = _make_cam(view, objs)
    if cam is None:
        return ''
    if engine == 'eevee':
        _sun(sc, mathutils.Vector(DIRS.get(view, DIRS['iso'])).normalized())
    else:
        sh = sc.display.shading
        sh.show_xray = False
        sh.light = 'STUDIO'
        sh.color_type = 'MATERIAL'
        sh.show_cavity = True
        sh.show_object_outline = True
    png = _shoot(out_png)
    bpy.data.objects.remove(cam, do_unlink=True)
    return png


def _overlay(role, out_png, width, height):
    """THE CHECK: the asset drawn over its own plan, through the plan's own view.

    Two passes, one camera. The first renders the plan alone at full contrast;
    the second renders the asset alone on a transparent film in draughtsman's
    blue; then they are mixed. The obvious single-pass version — Workbench
    X-ray — fades BOTH, and a plan at 45 % is not a plan you can measure
    against. This is the tracing-paper overlay, and the whole point of it is
    that the difference between the two is visible."""
    view = ROLE_DIR.get(role)
    planes = [o for o in _REF_OBJS if o.name == 'ref_' + role and o.type == 'MESH']
    assets = [o for o in asset_objects() if o.type in ('MESH', 'CURVE', 'SURFACE')]
    if not view or not planes or not assets:
        return ''
    sc = _setup(width, height, 'workbench')
    cam = _make_cam(view, planes + assets)
    if cam is None:
        return ''
    saved = {o.name: o.hide_render for o in bpy.data.objects}
    a_png, b_png = out_png + '.plan.png', out_png + '.asset.png'
    try:
        sh = sc.display.shading
        sh.show_xray = False
        sh.show_cavity = False
        sh.light = 'FLAT'
        sh.color_type = 'TEXTURE'
        sh.show_object_outline = False
        for o in bpy.data.objects:
            o.hide_render = o not in planes
        _shoot(a_png, transparent=False)
        sh.color_type = 'SINGLE'
        sh.single_color = (0.07, 0.42, 0.85)
        sh.show_object_outline = True
        sh.object_outline_color = (0.0, 0.07, 0.2)
        for o in bpy.data.objects:
            o.hide_render = bool(o.get('zyg_ref'))
        _shoot(b_png, transparent=True)
    finally:
        for o in bpy.data.objects:
            if o.name in saved:
                o.hide_render = saved[o.name]
        bpy.data.objects.remove(cam, do_unlink=True)
    return _mix(a_png, b_png, out_png, 0.55)


def _mix(plan_png, asset_png, out_png, k):
    """plan * (1 - a*k) + asset * (a*k). Both buffers are read Non-Color so
    nothing is colour-managed twice on the way in and out."""
    try:
        import numpy as np
    except ImportError:
        return plan_png
    ip = ia = res = None
    try:
        ip = bpy.data.images.load(plan_png)
        ia = bpy.data.images.load(asset_png)
        ip.colorspace_settings.name = 'Non-Color'
        ia.colorspace_settings.name = 'Non-Color'
        w, h = ip.size
        if tuple(ia.size) != (w, h):
            return plan_png
        P = np.array(ip.pixels[:], dtype='f4').reshape(-1, 4)
        A = np.array(ia.pixels[:], dtype='f4').reshape(-1, 4)
        al = A[:, 3:4] * float(k)
        out = P.copy()
        out[:, :3] = P[:, :3] * (1.0 - al) + A[:, :3] * al
        out[:, 3] = 1.0
        res = bpy.data.images.new('overlay', w, h, alpha=False)
        res.colorspace_settings.name = 'Non-Color'
        res.pixels = out.reshape(-1).tolist()
        res.filepath_raw = out_png
        res.file_format = 'PNG'
        res.save()
    except Exception as e:  # noqa: BLE001
        log(f'overlay mix failed ({type(e).__name__}: {e}) — keeping the plan pass')
        return plan_png
    finally:
        for im in (ip, ia, res):
            if im is not None:
                try:
                    bpy.data.images.remove(im)
                except (ReferenceError, RuntimeError) as _exc:
                    _zyg_log.debug('temporary image removal skipped: %s', _exc)
        for tmp in (plan_png, asset_png):
            try:
                os.remove(tmp)
            except OSError as _exc:
                _zyg_log.debug('temporary render file removal skipped: %s', _exc)
    return out_png if os.path.exists(out_png) else ''


def _engines():
    try:
        return {e.identifier for e in bpy.types.RenderEngine.bl_rna.properties['bl_idname'].enum_items}
    except Exception:  # noqa: BLE001
        return {getattr(c, 'bl_idname', '') for c in bpy.types.RenderEngine.__subclasses__()} | {
            'BLENDER_EEVEE_NEXT',
            'BLENDER_WORKBENCH',
            'CYCLES',
        }


def _sun(sc, d):
    if any(o.type == 'LIGHT' for o in bpy.data.objects):
        return
    ld = bpy.data.lights.new('refsun', 'SUN')
    ld.energy = 3.0
    ob = bpy.data.objects.new('refsun', ld)
    ob['zyg_ref'] = 1
    sc.collection.objects.link(ob)
    ob.rotation_euler = mathutils.Vector((-0.5, -0.4, 1.0)).to_track_quat('-Z', 'Y').to_euler()


def _world(sc):
    if sc.world is None:
        sc.world = bpy.data.worlds.new('refworld')
    sc.world.use_nodes = True
    bg = sc.world.node_tree.nodes.get('Background')
    if bg:
        bg.inputs[0].default_value = (0.05, 0.06, 0.08, 1.0)
        bg.inputs[1].default_value = 1.0


def _photo_look(sc):
    """The lighting a PORTFOLIO frame is judged in: a filmic transform, a sun
    that casts, and a sky bright enough to fill a hold. The first portfolio of
    the pinas came back so dark that "every surface is a flat colour" had to be
    read off the audit rather than off the pictures."""
    try:
        opts = {e.identifier for e in type(sc.view_settings).bl_rna.properties['view_transform'].enum_items}
    except (AttributeError, KeyError, TypeError):
        opts = set()
    for want in ('AgX', 'Filmic', 'Standard'):
        if want in opts or not opts:
            try:
                sc.view_settings.view_transform = want
                break
            except (TypeError, AttributeError) as _exc:
                _zyg_log.debug('view transform not accepted by this build: %s', _exc)
                continue
    try:
        sc.view_settings.exposure = 0.6
    except (AttributeError, TypeError) as _exc:
        _zyg_log.debug('view exposure not settable on this build: %s', _exc)
    if sc.world is not None and sc.world.use_nodes:
        bg = sc.world.node_tree.nodes.get('Background')
        if bg:
            bg.inputs[0].default_value = (0.32, 0.40, 0.52, 1.0)  # an overcast sky, not a night
            bg.inputs[1].default_value = 1.0
    for ob in bpy.data.objects:
        if ob.type == 'LIGHT' and ob.data.type == 'SUN':
            ob.data.energy = max(ob.data.energy, 4.0)
            try:
                ob.data.angle = 0.12  # a soft edge to every shadow
            except (AttributeError, TypeError) as _exc:
                _zyg_log.debug('sun angle not settable on this lamp: %s', _exc)


def _export_glb(path):
    for ob in bpy.data.objects:
        ob.select_set(bool(not ob.get('zyg_ref')) and ob.type in ('MESH', 'CURVE', 'EMPTY', 'ARMATURE'))
    bpy.ops.export_scene.gltf(
        filepath=path, export_format='GLB', use_selection=True, export_apply=True, export_yup=True
    )
    return path if os.path.exists(path) else ''
