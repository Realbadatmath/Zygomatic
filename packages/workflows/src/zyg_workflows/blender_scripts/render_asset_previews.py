# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""render_asset_previews.py — thumbnails for the packs that ship none.

    blender -b --factory-startup --python render_asset_previews.py -- [--pack X] [--limit N]

Kenney ships a rendered PNG beside every model and Quaternius mostly does not;
Poly Haven ships none at all. The rail wants one picture per item regardless,
so this renders the gaps into

    data/assets/mesh_packs/_generated_previews/<pack>/<item>.png

kept OUTSIDE the pack directories on purpose: a pack may be re-downloaded at
any time, and nothing we made should be sitting in the way when it is.

FRAMING IS THE POINT. A thumbnail that crops the model or shows it edge-on is
worse than no thumbnail. The camera is orthographic, placed on a fixed 3/4
vector, and its scale is solved from the model's own bounding box projected
into camera space — so a 20 m road tile and a 6 cm doorknob both fill the same
frame. Nothing is scaled: the CAMERA moves, so proportions stay honest.

Renders on a transparent background so the rail can sit them on its own paper.
"""

import argparse
import math
import os
import sys

import bpy
from mathutils import Vector
import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)


HERE = os.path.dirname(os.path.abspath(__file__))
CREWS = os.path.dirname(HERE)
PACKS_ROOT = os.path.join(CREWS, 'data', 'assets', 'mesh_packs')
OUT_ROOT = os.path.join(PACKS_ROOT, '_generated_previews')

# The card shows these at 212 CSS px, so 512 covers a 2× display with room to
# spare. Worth stating why it is not smaller: Kenney's own shipped previews are
# 64×64, which is a quarter of the card's width and reads as a smudge — the
# reason this renders every item rather than only the packs that ship nothing.
RES = 512
MARGIN = 1.06  # a hair of air so nothing touches the frame edge
SAMPLES = 96  # EEVEE TAA; the edges are what a thumbnail is judged on


def argv_after_dashes():
    return sys.argv[sys.argv.index('--') + 1 :] if '--' in sys.argv else []


def setup_world():
    scn = bpy.context.scene
    scn.render.resolution_x = scn.render.resolution_y = RES
    scn.render.film_transparent = True
    scn.render.image_settings.file_format = 'PNG'
    scn.render.image_settings.color_mode = 'RGBA'

    # EEVEE if this Blender can get a GL context in background, else Cycles on
    # CPU at low samples — 256 px of preview does not need path tracing, and a
    # renderer that fails silently is worse than a slow one.
    try:
        scn.render.engine = 'BLENDER_EEVEE_NEXT'
    except TypeError:
        try:
            scn.render.engine = 'BLENDER_EEVEE'
        except TypeError:
            scn.render.engine = 'CYCLES'
    if scn.render.engine == 'CYCLES':
        scn.cycles.samples = 64
        scn.cycles.use_denoising = True
    else:
        scn.eevee.taa_render_samples = SAMPLES
        # EEVEE Next puts AO and proper shadows behind the raytracing switch;
        # without it the crevices of a stone wall render as flat grey.
        for attr, val in (
            ('use_raytracing', True),
            ('use_shadows', True),
            ('use_gtao', True),
            ('use_soft_shadows', True),
        ):
            if hasattr(scn.eevee, attr):
                setattr(scn.eevee, attr, val)

    # Blender 4.x defaults to the AgX view transform, which is built for
    # filmic latitude and deliberately desaturates. On a 512 px thumbnail of a
    # CC0 albedo that reads as "the texture is grey" — Standard shows the
    # colour the material actually has.
    vs = scn.view_settings
    try:
        vs.view_transform = 'Standard'
        vs.look = 'None'
        # Standard has no filmic shoulder, so a highlight that would have
        # rolled off under AgX simply clips to white. The rig below is lit
        # about a stop under to keep the form in the bright end — a white
        # statue rendering as a white silhouette is the failure mode.
        vs.exposure = -0.35
    except TypeError as _exc:
        _zyg_log.debug('standard view transform not available on this build: %s', _exc)

    # A gradient sky rather than a flat colour: a constant world gives every
    # curved surface the same highlight everywhere and kills the read of form.
    world = bpy.data.worlds.new('pv')
    world.use_nodes = True
    nt = world.node_tree
    bg = nt.nodes['Background']
    grad = nt.nodes.new('ShaderNodeTexGradient')
    grad.gradient_type = 'EASING'
    ramp = nt.nodes.new('ShaderNodeValToRGB')
    ramp.color_ramp.elements[0].color = (0.10, 0.11, 0.13, 1.0)
    ramp.color_ramp.elements[1].color = (0.46, 0.48, 0.52, 1.0)
    tex = nt.nodes.new('ShaderNodeTexCoord')
    mapn = nt.nodes.new('ShaderNodeMapping')
    mapn.inputs['Rotation'].default_value = (math.radians(90), 0, 0)
    nt.links.new(tex.outputs['Generated'], mapn.inputs['Vector'])
    nt.links.new(mapn.outputs['Vector'], grad.inputs['Vector'])
    nt.links.new(grad.outputs['Color'], ramp.inputs['Fac'])
    nt.links.new(ramp.outputs['Color'], bg.inputs['Color'])
    bg.inputs['Strength'].default_value = 0.85
    scn.world = world

    # Three-point rig. Suns because direction-only lighting keeps the framing
    # solver independent of how far away the lamps are; a non-zero angle makes
    # the shadow terminator soft instead of a hard CAD edge.
    for rot, energy, angle in (
        ((math.radians(52), 0, math.radians(40)), 1.9, math.radians(9)),  # key
        ((math.radians(74), 0, math.radians(-118)), 0.7, math.radians(24)),  # fill
        ((math.radians(116), 0, math.radians(196)), 0.9, math.radians(6)),
    ):  # rim
        ld = bpy.data.lights.new('sun', 'SUN')
        ld.energy = energy
        ld.angle = angle
        ob = bpy.data.objects.new('sun', ld)
        ob.rotation_euler = rot
        bpy.context.collection.objects.link(ob)

    cam_d = bpy.data.cameras.new('cam')
    cam_d.type = 'ORTHO'
    cam = bpy.data.objects.new('cam', cam_d)
    bpy.context.collection.objects.link(cam)
    scn.camera = cam
    return cam


def frame(cam, objs):
    """Aim the camera down a fixed 3/4 vector and solve its ortho scale.

    Returns False when there is nothing with a size to look at."""
    pts = []
    for o in objs:
        if o.type != 'MESH' or not o.data.vertices:
            continue
        for c in o.bound_box:
            pts.append(o.matrix_world @ Vector(c))
    if not pts:
        return False
    lo = Vector((min(p.x for p in pts), min(p.y for p in pts), min(p.z for p in pts)))
    hi = Vector((max(p.x for p in pts), max(p.y for p in pts), max(p.z for p in pts)))
    centre = (lo + hi) / 2.0
    size = hi - lo
    if max(size) < 1e-6:
        return False

    direction = Vector((1.0, -1.0, 0.72)).normalized()
    cam.location = centre + direction * (max(size) * 4.0 + 1.0)
    # Point at the centre: track the -Z axis of the camera down the view vector.
    cam.rotation_euler = (-direction).to_track_quat('-Z', 'Y').to_euler()
    bpy.context.view_layer.update()

    # Project the bounding corners into camera space and take the widest
    # extent — the only way an ortho scale is right for every shape.
    inv = cam.matrix_world.inverted()
    ext = 0.0
    for p in (Vector((x, y, z)) for x in (lo.x, hi.x) for y in (lo.y, hi.y) for z in (lo.z, hi.z)):
        q = inv @ p
        ext = max(ext, abs(q.x), abs(q.y))
    cam.data.ortho_scale = max(ext * 2.0 * MARGIN, 1e-3)
    return True


def render_one(path, out_png):
    before = set(bpy.data.objects)
    try:
        bpy.ops.import_scene.gltf(filepath=path, import_pack_images=False)
    except Exception as e:  # noqa: BLE001
        return f'import failed: {type(e).__name__}'
    new = [o for o in bpy.data.objects if o not in before]
    if not new:
        return 'nothing imported'
    cam = bpy.context.scene.camera
    ok = frame(cam, new)
    if ok:
        os.makedirs(os.path.dirname(out_png), exist_ok=True)
        bpy.context.scene.render.filepath = out_png
        try:
            bpy.ops.render.render(write_still=True)
        except Exception as e:  # noqa: BLE001
            ok = f'render failed: {type(e).__name__}: {str(e)[:80]}'
    else:
        ok = 'empty bounding box'
    for o in new:
        ob = bpy.data.objects.get(o.name) if o.name in bpy.data.objects else None
        if ob is not None:
            bpy.data.objects.remove(ob, do_unlink=True)
    for blk in (bpy.data.meshes, bpy.data.materials, bpy.data.images):
        for d in list(blk):
            if d.users == 0:
                blk.remove(d)
    return True if ok is True else ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--pack')
    ap.add_argument('--limit', type=int)
    ap.add_argument('--force', action='store_true')
    a = ap.parse_args(argv_after_dashes())

    sys.path.insert(0, CREWS)
    from zyg_workflows import architecture_assets as aa

    cat = aa.catalogue()

    todo = []
    for g in cat['groups']:
        if a.pack and g['pack'] != a.pack:
            continue
        for it in g['items']:
            # NOT `if it.get('pv')`. A pack that ships its own art still has
            # `pv` set, and skipping on that is how the 41 new Kenney kits
            # would have kept their 64x64 vendor thumbnails while the policy
            # says every item is rendered here and the generated tree wins in
            # _preview_index. The only thing worth skipping is an item this
            # script has ALREADY rendered, which is the next line.
            out = os.path.join(OUT_ROOT, g['pack'], it['p']['item'] + '.png')
            if os.path.isfile(out) and not a.force:
                continue
            todo.append((g['pack'], it['p']['item'], os.path.join(PACKS_ROOT, it['u']), out))
    if a.limit:
        todo = todo[: a.limit]
    print(f'@@TODO@@ {len(todo)} previews to render (engine {bpy.context.scene.render.engine})')

    bpy.ops.wm.read_factory_settings(use_empty=True)
    setup_world()

    done, failed = 0, {}
    for n, (_pack, item, src, out) in enumerate(todo, 1):
        if not os.path.isfile(src):
            failed[item] = 'source missing'
            continue
        r = render_one(src, out)
        if r is True:
            done += 1
        else:
            failed[item] = r
        if n % 25 == 0:
            print(f'    {n}/{len(todo)} ({done} ok)…', flush=True)
    print(
        '@@RESULT@@ '
        + repr(
            {
                'rendered': done,
                'failed': len(failed),
                'why': dict(list(failed.items())[:5]),
                'engine': bpy.context.scene.render.engine,
            }
        )
    )


if __name__ == '__main__':
    main()
