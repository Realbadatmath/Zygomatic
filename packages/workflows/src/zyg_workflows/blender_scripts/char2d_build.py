# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Build a cel-shaded 2D-look character from a JSON brief and render six views.

Headless Blender only:

    flock /tmp/claude-1000/arch_ext_blender.lock /usr/local/bin/blender -b \
        --python blender_scripts/char2d_build.py -- \
        --brief BRIEF.json --out DIR [--views ...] [--res 1024x1536] [--pose POSE.json] [--no-save]

The brief drives an MPFB human (macro shape, 'default' rig with finger bones), the
helper geometry becomes clothing/hair/eyes, everything else is masked away, and the
result is rendered with a two-tone cel material plus a Freestyle ink outline onto a
transparent background.  Alongside the PNGs the script writes views.json with the
per-view mouth / head-top / chin anchors that the later stages of the pipeline read.
"""

import argparse
import json
import math
import os
import sys

import bpy
import numpy as np
from mathutils import Vector
from bpy_extras.object_utils import world_to_camera_view

import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)

# --------------------------------------------------------------------- config

YAW = {
    'front': 0.0,
    'front30L': 30.0,
    'front30R': 330.0,
    'front45L': 45.0,
    'front45R': 315.0,
    'profileL': 90.0,
    'profileR': 270.0,
    'back': 180.0,
}
DEFAULT_VIEWS = ('front', 'front45L', 'front45R', 'profileL', 'profileR', 'back')

# The one MPFB body height the macro table is anchored on (see the standing facts).
REF_HEIGHT = 1.66
CAM_LENS = 85.0
CAM_SENSOR = 36.0
CAM_FILL = 0.88  # fraction of the frame height the body should occupy
HEIGHT_TOL = 0.02  # metres; the brief's accuracy requirement
HEIGHT_SLOPE = 0.45  # m of standing height per unit of the MPFB height macro

SKIN, TOP, BOTTOM, HAIR, EYE, HIDDEN = range(6)
SLOT_NAMES = ('skin', 'top', 'bottom', 'hair', 'eye', 'hidden')

# Vertex groups that classify a vertex.  They partition the mesh exactly; every
# other group (bone weights, body regions, joint cubes helpers) is ignored here.
CLASS_BY_GROUP = {
    'helper-tights': TOP,  # split into top/bottom by z further down
    'helper-hair': HAIR,
    'helper-l-eye': EYE,
    'helper-r-eye': EYE,
    'helper-skirt': HIDDEN,
    'helper-genital': HIDDEN,
    'helper-tongue': HIDDEN,
    'helper-upper-teeth': HIDDEN,
    'helper-lower-teeth': HIDDEN,
    'helper-l-eyelashes-1': HIDDEN,
    'helper-l-eyelashes-2': HIDDEN,
    'helper-r-eyelashes-1': HIDDEN,
    'helper-r-eyelashes-2': HIDDEN,
    'JointCubes': HIDDEN,
    'body': SKIN,
}

DEFAULTS = {
    'gender': 0.5,
    'age': 25.0,
    'height_m': 1.68,
    'weight': 0.5,
    'muscle': 0.5,
    'skin': '#f2cdb4',
    'hair': '#2a1a12',
    'top': '#3b5fa3',
    'bottom': '#2b2f3a',
    'eye': '#1a1a22',
    'hair_cut': 'bob',
}

FINGER_SEGMENTS = ['finger%d-%d.%s' % (f, s, side) for f in (2, 3, 4, 5) for s in (1, 2, 3) for side in ('L', 'R')]
THUMB_SEGMENTS = ['finger1-%d.%s' % (s, side) for s in (2, 3) for side in ('L', 'R')]
# A relaxed hand keeps the fingers together: only a hair of abduction on the
# proximal segments, enough to stop the four digits fusing into one ink mass but
# far short of the splayed fan that read as a claw.  Mirrored on the right hand.
FINGER_FAN = {2: 2.0, 3: 0.7, 4: -0.7, 5: -2.0}
# Idle flexion cascade per segment (MCP, PIP, DIP): the natural resting curve of
# a hanging hand, not the uniform 12 degrees on every joint that looked hooked.
IDLE_CURL = (15.0, 20.0, 8.0)
# The thumb rests along the index instead of sticking out sideways: finger1-1 is
# swung toward the palm (y), the two distal segments keep a soft bend.  y = 20
# is the measured minimum of the thumb-tip -> index-PIP distance (54.0 mm, from
# 56.9 mm at y = 0); past it the thumb swings back out again.
IDLE_THUMB_Y = 20.0
IDLE_THUMB_CURL = (10.0, 6.0)
# Forearm rotation that turns the palm toward the thigh.  The palm direction is
# measured the only way that cannot be sign-confused: pose the hand twice, once
# with the idle curl and once with the curl zeroed, and take the direction the
# middle fingertip travels -- fingers curl toward the palm, so that vector IS the
# palm normal.  Swept over the whole wrist ROM on the right hand, y = -25 is the
# best it gets: volar = (+0.63, +0.78, +0.02), i.e. the palm faces medially onto
# the thigh with no upward cup, and volar.y > 0 means the front camera (which
# looks along +Y) sees the back of the hand.  Mirrored on the left.
# The hand still reaches forward: lowerarm01's ROM starts at 0, so the MPFB rest
# elbow flexion cannot be extended away inside the declared range.
IDLE_WRIST_Y = -25.0

# ------------------------------------------------------------------------ ink
# Freestyle line width in delivered pixels.  At 1024x1536 a finger is ~12 px
# across, so the 2.5 px ink of the first pass swallowed it.
INK_PX = 1.8
INK_RELATIVE_REF = 480.0  # Blender scales RELATIVE thickness by res_y / 480
# Every still is rendered at SUPERSAMPLE x the delivered size and resampled down
# with Lanczos, which is what turns the hard Freestyle ink into a clean edge.
SUPERSAMPLE = 2


# ----------------------------------------------------------------------- cli


def parse_args():
    argv = sys.argv[sys.argv.index('--') + 1 :] if '--' in sys.argv else []
    p = argparse.ArgumentParser(prog='char2d_build.py')
    p.add_argument('--brief', required=True)
    p.add_argument('--out', required=True)
    p.add_argument('--views', default=','.join(DEFAULT_VIEWS))
    p.add_argument('--res', default='1024x1536')
    p.add_argument('--pose', default=None)
    p.add_argument('--no-save', action='store_true')
    args = p.parse_args(argv)
    args.view_list = [v.strip() for v in args.views.split(',') if v.strip()]
    for view in args.view_list:
        if view not in YAW:
            p.error('unknown view %r; known: %s' % (view, ', '.join(YAW)))
    try:
        wide, high = args.res.lower().split('x')
        args.res_wh = (int(wide), int(high))
    except ValueError:
        p.error('--res must look like 1024x1536')
    return args


def load_brief(path):
    with open(path, 'r', encoding='utf-8') as fh:
        raw = json.load(fh)
    if 'name' not in raw:
        raise SystemExit('brief %s has no "name"' % path)
    brief = dict(DEFAULTS)
    brief.update({k: v for k, v in raw.items() if v is not None})
    if brief['hair_cut'] not in ('bob', 'short', 'long'):
        raise SystemExit('hair_cut must be bob|short|long, got %r' % brief['hair_cut'])
    return brief


# ------------------------------------------------------------------- colours


def srgb_to_linear(channel):
    return channel / 12.92 if channel <= 0.04045 else ((channel + 0.055) / 1.055) ** 2.4


def hex_to_linear(value):
    text = str(value).lstrip('#')
    if len(text) == 3:
        text = ''.join(c * 2 for c in text)
    if len(text) != 6:
        raise SystemExit('bad hex colour %r' % value)
    return tuple(srgb_to_linear(int(text[i : i + 2], 16) / 255.0) for i in (0, 2, 4))


# ---------------------------------------------------------------------- body


def age_macro(age):
    """MPFB/MakeHuman age macro: 0.0 = 1 y, 0.5 = 25 y, 1.0 = 90 y (proxy_actor.py)."""
    if age <= 1.0:
        return max(0.0, min(1.0, age))
    if age <= 25.0:
        return max(0.0, (age - 1.0) / 24.0 * 0.5)
    return min(1.0, 0.5 + (age - 25.0) / 65.0 * 0.5)


def clear_scene():
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj, do_unlink=True)
    for block in list(bpy.data.meshes):
        bpy.data.meshes.remove(block)
    for block in list(bpy.data.armatures):
        bpy.data.armatures.remove(block)


def create_body(brief, height_macro):
    from bl_ext.user_default.mpfb.services.humanservice import HumanService
    from bl_ext.user_default.mpfb.services.targetservice import TargetService

    macro = TargetService.get_default_macro_info_dict()
    macro.update(
        {
            'gender': float(brief['gender']),
            'age': age_macro(float(brief['age'])),
            'height': float(height_macro),
            'weight': float(brief['weight']),
            'muscle': float(brief['muscle']),
        }
    )
    body = HumanService.create_human(
        mask_helpers=False, detailed_helpers=True, feet_on_ground=True, macro_detail_dict=macro
    )
    return body


def evaluated_world_coords(obj):
    """World-space positions of the evaluated mesh.

    obj.dimensions is stale in background mode, so every measurement in this
    script goes through the depsgraph vertices instead.  Called before the MASK
    modifier is added, so indices line up 1:1 with obj.data.vertices.
    """
    bpy.context.view_layer.update()
    dg = bpy.context.evaluated_depsgraph_get()
    ev = obj.evaluated_get(dg)
    mesh = ev.to_mesh()
    mat = ev.matrix_world
    count = len(mesh.vertices)
    flat = np.empty(count * 3, dtype=np.float64)
    mesh.vertices.foreach_get('co', flat)
    local = flat.reshape(count, 3)
    rot = np.array(mat.to_3x3()).reshape(3, 3)
    world = local @ rot.T + np.array(mat.translation)
    ev.to_mesh_clear()
    return world


def group_mask(obj, world, group_name):
    idx = obj.vertex_groups[group_name].index
    flags = np.zeros(len(world), dtype=bool)
    for vert in obj.data.vertices:
        for entry in vert.groups:
            if entry.group == idx:
                flags[vert.index] = True
                break
    return flags


def body_height(obj, world, body_flags):
    zs = world[body_flags][:, 2]
    return float(zs.max() - zs.min())


def build_with_height(brief):
    """Solve the MPFB height macro so the standing body height matches height_m."""
    target = float(brief['height_m'])
    macro_h = 0.5
    samples = []
    body = None
    for attempt in range(4):
        if body is not None:
            clear_scene()
        body = create_body(brief, macro_h)
        world = evaluated_world_coords(body)
        flags = group_mask(body, world, 'body')
        height = body_height(body, world, flags)
        samples.append((macro_h, height))
        _zyg_log.info('HEIGHT pass %d macro=%.4f -> %.4f m (target %.4f)' % (attempt + 1, macro_h, height, target))
        if abs(height - target) <= HEIGHT_TOL * 0.25:
            break
        if len(samples) >= 2 and abs(samples[-1][0] - samples[-2][0]) > 1e-6:
            slope = (samples[-1][1] - samples[-2][1]) / (samples[-1][0] - samples[-2][0])
        else:
            slope = HEIGHT_SLOPE
        if abs(slope) < 1e-3:
            break
        nxt = min(1.0, max(0.0, macro_h + (target - height) / slope))
        if abs(nxt - macro_h) < 1e-4:
            break
        macro_h = nxt
    return body, macro_h, samples[-1][1]


def add_rig(body):
    from bl_ext.user_default.mpfb.services.humanservice import HumanService

    arm = HumanService.add_builtin_rig(body, 'default', import_weights=True)
    if body.parent is not arm:
        body.parent = arm
        body.matrix_parent_inverse = arm.matrix_world.inverted()
    return arm


def landmarks(arm):
    """jaw head, chin (jaw tail) and top of head (head tail) in world metres."""
    mat = arm.matrix_world
    jaw = arm.pose.bones['jaw']
    head = arm.pose.bones['head']
    return (mat @ jaw.head, mat @ jaw.tail, mat @ head.tail)


# ----------------------------------------------------------------- materials


def cel_material(name, rgb):
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    mat.use_backface_culling = False
    tree = mat.node_tree
    tree.nodes.clear()
    diffuse = tree.nodes.new('ShaderNodeBsdfDiffuse')
    to_rgb = tree.nodes.new('ShaderNodeShaderToRGB')
    ramp = tree.nodes.new('ShaderNodeValToRGB')
    emission = tree.nodes.new('ShaderNodeEmission')
    out = tree.nodes.new('ShaderNodeOutputMaterial')
    for i, node in enumerate((diffuse, to_rgb, ramp, emission, out)):
        node.location = (i * 220, 0)
    diffuse.inputs['Color'].default_value = (1.0, 1.0, 1.0, 1.0)
    ramp.color_ramp.interpolation = 'CONSTANT'
    shadow = tuple(c * 0.62 for c in rgb)
    ramp.color_ramp.elements[0].position = 0.0
    ramp.color_ramp.elements[0].color = shadow + (1.0,)
    ramp.color_ramp.elements[1].position = 0.35
    ramp.color_ramp.elements[1].color = tuple(rgb) + (1.0,)
    emission.inputs['Strength'].default_value = 1.0
    tree.links.new(diffuse.outputs['BSDF'], to_rgb.inputs['Shader'])
    tree.links.new(to_rgb.outputs['Color'], ramp.inputs['Fac'])
    tree.links.new(ramp.outputs['Color'], emission.inputs['Color'])
    tree.links.new(emission.outputs['Emission'], out.inputs['Surface'])
    return mat


def hair_cut_line(brief, jaw_head, height):
    cut = brief['hair_cut']
    if cut == 'long':
        return -1e9
    if cut == 'short':
        return jaw_head.z + 0.06 * height / REF_HEIGHT
    return jaw_head.z  # bob


def classify(body, world, brief, height, jaw_head, chin, head_top):
    """Per-vertex class, the kept-hair face set, and the 'show2d' vertex group."""
    count = len(world)
    order = [
        'helper-tights',
        'helper-hair',
        'helper-l-eye',
        'helper-r-eye',
        'helper-skirt',
        'helper-genital',
        'helper-tongue',
        'helper-upper-teeth',
        'helper-lower-teeth',
        'helper-l-eyelashes-1',
        'helper-l-eyelashes-2',
        'helper-r-eyelashes-1',
        'helper-r-eyelashes-2',
        'JointCubes',
        'body',
    ]
    present = [g for g in order if g in body.vertex_groups]
    rank = {body.vertex_groups[n].index: (i, CLASS_BY_GROUP[n]) for i, n in enumerate(present)}
    vclass = np.full(count, HIDDEN, dtype=np.int8)
    for vert in body.data.vertices:
        best = None
        for entry in vert.groups:
            hit = rank.get(entry.group)
            if hit is not None and (best is None or hit[0] < best[0]):
                best = hit
        if best is not None:
            vclass[vert.index] = best[1]

    waist_z = 0.62 * height
    cut_z = hair_cut_line(brief, jaw_head, height)
    hair_xs = np.abs(world[vclass == HAIR][:, 0])
    hair_max_x = float(hair_xs.max()) if hair_xs.size else 0.0
    # The MPFB hair helper is a closed hull that also sits over the face; the z cut
    # alone would leave a mask over the eyes.  Carve the frontal face window out of
    # every cut so the face is always visible.
    brow_z = chin.z + 0.78 * (head_top.z - chin.z)
    face_y = jaw_head.y

    polys = body.data.polygons
    nfaces = len(polys)
    loop_verts = np.empty(len(body.data.loops), dtype=np.int32)
    body.data.loops.foreach_get('vertex_index', loop_verts)
    starts = np.empty(nfaces, dtype=np.int32)
    totals = np.empty(nfaces, dtype=np.int32)
    polys.foreach_get('loop_start', starts)
    polys.foreach_get('loop_total', totals)

    mat_index = np.empty(nfaces, dtype=np.int32)
    kept_hair_verts = set()
    hidden_hair_faces = 0
    for fi in range(nfaces):
        vids = loop_verts[starts[fi] : starts[fi] + totals[fi]]
        counts = np.bincount(vclass[vids].astype(np.int64), minlength=HIDDEN + 1)
        cls = int(counts.argmax())
        pts = world[vids]
        centre = pts.mean(axis=0)
        if cls == TOP:  # helper-tights
            cls = TOP if centre[2] > waist_z else BOTTOM
        elif cls == HAIR:
            drop = bool((pts[:, 2] < cut_z).all())
            face_window = centre[2] < brow_z and centre[1] < face_y and abs(centre[0]) < 0.75 * hair_max_x
            if drop or face_window:
                cls = HIDDEN
                hidden_hair_faces += 1
            else:
                kept_hair_verts.update(int(v) for v in vids)
        mat_index[fi] = cls

    show = np.zeros(count, dtype=bool)
    show |= vclass == SKIN
    show |= (vclass == TOP) | (vclass == BOTTOM)
    show |= vclass == EYE
    # A hair vertex only survives if it belongs to a face we kept.
    if kept_hair_verts:
        show[np.fromiter(kept_hair_verts, dtype=np.int32)] = True
    return vclass, mat_index, show, hidden_hair_faces


def apply_materials(body, brief, mat_index):
    colours = {
        SKIN: brief['skin'],
        TOP: brief['top'],
        BOTTOM: brief['bottom'],
        HAIR: brief['hair'],
        EYE: brief['eye'],
        HIDDEN: '#ff00ff',
    }
    body.data.materials.clear()
    for slot in range(HIDDEN + 1):
        body.data.materials.append(
            cel_material('c2d_%s_%s' % (brief['name'], SLOT_NAMES[slot]), hex_to_linear(colours[slot]))
        )
    body.data.polygons.foreach_set('material_index', mat_index.astype(np.int32))
    body.data.update()


def apply_show_mask(body, show):
    for mod in list(body.modifiers):
        if mod.type == 'MASK':
            body.modifiers.remove(mod)
    if 'show2d' in body.vertex_groups:
        body.vertex_groups.remove(body.vertex_groups['show2d'])
    group = body.vertex_groups.new(name='show2d')
    group.add([int(i) for i in np.nonzero(show)[0]], 1.0, 'REPLACE')
    mod = body.modifiers.new('show2d', 'MASK')
    mod.vertex_group = 'show2d'
    mod.threshold = 0.5
    return int(show.sum())


# -------------------------------------------------------------------- posing


def idle_pose():
    """The neutral standing pose as {bone: (x, y, z) degrees}.  No bpy.

    char2d_poses.IDLE_POSE duplicates this table; tests/test_char2d_poses.py
    asserts the two stay identical.
    """
    idle = {
        'upperarm01.L': (0.0, 0.0, -40.0),
        'upperarm01.R': (0.0, 0.0, 40.0),
        'lowerarm01.L': (8.0, 0.0, 0.0),
        'lowerarm01.R': (8.0, 0.0, 0.0),
        'wrist.L': (0.0, -IDLE_WRIST_Y, 0.0),
        'wrist.R': (0.0, IDLE_WRIST_Y, 0.0),
    }
    for finger in (2, 3, 4, 5):
        for segment, curl in zip((1, 2, 3), IDLE_CURL):
            fan = FINGER_FAN[finger] if segment == 1 else 0.0
            for side, sign in (('L', 1.0), ('R', -1.0)):
                idle['finger%d-%d.%s' % (finger, segment, side)] = (curl, 0.0, fan * sign)
    for side, sign in (('L', 1.0), ('R', -1.0)):
        idle['finger1-1.%s' % side] = (0.0, IDLE_THUMB_Y * sign, 0.0)
        for segment, curl in zip((2, 3), IDLE_THUMB_CURL):
            idle['finger1-%d.%s' % (segment, side)] = (curl, 0.0, 0.0)
    return idle


def reset_pose(arm):
    for bone in arm.pose.bones:
        bone.rotation_mode = 'XYZ'
        bone.rotation_euler = (0.0, 0.0, 0.0)


def apply_bones(arm, bones):
    """Set {bone: (x, y, z) degrees} on the armature; unknown names are reported."""
    missing = []
    for name, angles in bones.items():
        bone = arm.pose.bones.get(name)
        if bone is None:
            missing.append(name)
            continue
        bone.rotation_euler = tuple(math.radians(float(a)) for a in angles)
    if missing:
        _zyg_log.info('POSE unknown bones ignored: %s' % ', '.join(sorted(missing)))
    bpy.context.view_layer.update()
    return dict(bones)


def apply_idle(arm):
    """Zero every bone, then apply the idle pose."""
    reset_pose(arm)
    return apply_bones(arm, idle_pose())


def apply_pose(arm, pose_path):
    override = {}
    if pose_path:
        with open(pose_path, 'r', encoding='utf-8') as fh:
            override = json.load(fh).get('bones', {})
    combined = dict(idle_pose())
    combined.update(override)
    reset_pose(arm)
    return apply_bones(arm, combined)


# --------------------------------------------------------------------- scene


def setup_world_and_light():
    world = bpy.data.worlds.get('World') or bpy.data.worlds.new('World')
    bpy.context.scene.world = world
    world.use_nodes = True
    bg = world.node_tree.nodes.get('Background')
    if bg is not None:
        bg.inputs['Strength'].default_value = 0.6
    sun_data = bpy.data.lights.new('c2d_sun', type='SUN')
    sun_data.energy = 3.0
    sun = bpy.data.objects.new('c2d_sun', sun_data)
    sun.rotation_euler = (0.8, 0.2, 0.3)
    bpy.context.collection.objects.link(sun)
    return sun


def setup_render(res_wh):
    scene = bpy.context.scene
    scene.render.engine = 'BLENDER_EEVEE_NEXT'
    scene.render.resolution_x, scene.render.resolution_y = res_wh
    scene.render.resolution_percentage = 100
    scene.render.film_transparent = True
    scene.render.image_settings.file_format = 'PNG'
    scene.render.image_settings.color_mode = 'RGBA'
    scene.render.image_settings.color_depth = '8'
    scene.render.use_freestyle = True
    view_layer = bpy.context.view_layer
    view_layer.use_freestyle = True
    for old in list(view_layer.freestyle_settings.linesets):
        view_layer.freestyle_settings.linesets.remove(old)
    lineset = view_layer.freestyle_settings.linesets.new('ink')
    # MANDATORY in background mode: without an explicit linestyle the render dies
    # with "NoneType has no attribute use_chaining".
    style = bpy.data.linestyles.new('ink')
    lineset.linestyle = style
    lineset.select_silhouette = True
    # Crease is off: on a 12 px wide finger the knuckle folds and the nostril /
    # eyelid creases come out as detached ink stubs that break the digit in two.
    # Silhouette + border + contour still draw every outline, including the gap
    # between two fingers, because that gap is a view-dependent silhouette edge.
    lineset.select_crease = False
    lineset.select_border = True
    lineset.select_contour = True
    lineset.select_external_contour = False  # inner contours separate the fingers
    # RELATIVE thickness is scaled by res_y / 480 at render time, so the ink keeps
    # its apparent width when render_still() renders at SUPERSAMPLE x this size.
    style.thickness = INK_PX * INK_RELATIVE_REF / float(res_wh[1])
    style.color = (0.03, 0.03, 0.04)
    scene.render.line_thickness_mode = 'RELATIVE'
    scene.render.line_thickness = style.thickness
    return scene


def render_still(scene, path):
    """Render one still at SUPERSAMPLE x and resample it down with Lanczos."""
    from PIL import Image

    wide, high = scene.render.resolution_x, scene.render.resolution_y
    scene.render.resolution_x = wide * SUPERSAMPLE
    scene.render.resolution_y = high * SUPERSAMPLE
    scene.render.filepath = path
    try:
        bpy.ops.render.render(write_still=True)
    finally:
        scene.render.resolution_x, scene.render.resolution_y = wide, high
    img = Image.open(path)
    img.load()
    img.resize((wide, high), Image.LANCZOS).save(path)
    return path


def make_camera():
    data = bpy.data.cameras.new('c2d_cam')
    data.lens = CAM_LENS
    data.sensor_fit = 'VERTICAL'  # framing must not depend on the aspect
    data.sensor_height = CAM_SENSOR
    cam = bpy.data.objects.new('c2d_cam', data)
    bpy.context.collection.objects.link(cam)
    bpy.context.scene.camera = cam
    return cam


def frame_camera(points, yaws):
    """Camera distance and aim height that fit every view to CAM_FILL of the frame.

    Not simply height/fill: the toes are ~0.3 m nearer the lens than the head, so a
    perspective 85 mm shot of a 1.66 m body overfills a naive framing by ~3 % and
    sits off-centre.  Solve the distance in closed form, then re-centre and repeat.
    """
    half = (CAM_SENSOR / 2.0) / CAM_LENS
    views = [np.array([-math.sin(math.radians(y)), math.cos(math.radians(y)), 0.0]) for y in yaws]
    alongs = [points[:, :3] @ v for v in views]
    centre_z = float((points[:, 2].min() + points[:, 2].max()) / 2.0)
    dist = 0.0
    for _ in range(8):
        dz = np.abs(points[:, 2] - centre_z)
        dist = max(float((dz / (CAM_FILL * half) - along).max()) for along in alongs)
        hi = max(float(((points[:, 2] - centre_z) / ((along + dist) * half)).max()) for along in alongs)
        lo = min(float(((points[:, 2] - centre_z) / ((along + dist) * half)).min()) for along in alongs)
        shift = (hi + lo) / 2.0 * dist * half
        centre_z += shift
        if abs(shift) < 1e-4:
            break
    return dist, centre_z


def place_camera(cam, yaw_deg, dist, centre_z):
    a = math.radians(yaw_deg)
    cam.location = (dist * math.sin(a), -dist * math.cos(a), centre_z)
    cam.rotation_euler = (math.radians(90.0), 0.0, a)
    bpy.context.view_layer.update()


# ------------------------------------------------------------------- anchors


def posed_body_points(body):
    """World coords + per-vertex group flags of the evaluated (posed, masked) mesh."""
    bpy.context.view_layer.update()
    dg = bpy.context.evaluated_depsgraph_get()
    ev = body.evaluated_get(dg)
    mesh = ev.to_mesh()
    mat = ev.matrix_world
    count = len(mesh.vertices)
    flat = np.empty(count * 3, dtype=np.float64)
    mesh.vertices.foreach_get('co', flat)
    rot = np.array(mat.to_3x3()).reshape(3, 3)
    world = flat.reshape(count, 3) @ rot.T + np.array(mat.translation)
    body_idx = body.vertex_groups['body'].index
    flags = np.zeros(count, dtype=bool)
    for vert in mesh.vertices:
        for entry in vert.groups:
            if entry.group == body_idx:
                flags[vert.index] = True
                break
    ev.to_mesh_clear()
    return world, flags


def mouth_points(world, body_flags, jaw_head, chin):
    span = jaw_head.z - chin.z
    lo = chin.z + 0.35 * span
    hi = chin.z + 0.55 * span
    band = world[body_flags & (world[:, 2] >= lo) & (world[:, 2] <= hi)]
    if band.size == 0:
        raise SystemExit('no body vertices in the mouth z band [%.4f %.4f]' % (lo, hi))
    keep = max(4, int(round(len(band) * 0.15)))
    front = band[np.argsort(band[:, 1])[:keep]]  # most negative Y = front-most
    centre = front.mean(axis=0)
    width = float(front[:, 0].max() - front[:, 0].min())
    return Vector(centre), width


def to_pixels(scene, cam, point, res_wh):
    uv = world_to_camera_view(scene, cam, Vector(point))
    return [round(uv.x * res_wh[0], 2), round((1.0 - uv.y) * res_wh[1], 2)]


def alpha_bbox(path):
    img = bpy.data.images.load(path)
    try:
        buf = np.empty(len(img.pixels), dtype=np.float32)
        img.pixels.foreach_get(buf)
        wide, high = img.size
        alpha = buf.reshape(high, wide, 4)[:, :, 3][::-1]  # flip to top-down
        rows = np.nonzero(alpha.max(axis=1) > 0.02)[0]
        cols = np.nonzero(alpha.max(axis=0) > 0.02)[0]
        if not rows.size or not cols.size:
            return None
        return [int(cols[0]), int(rows[0]), int(cols[-1]) + 1, int(rows[-1]) + 1]
    finally:
        bpy.data.images.remove(img)


# ---------------------------------------------------------------------- main


def main():
    args = parse_args()
    brief = load_brief(args.brief)
    out_dir = os.path.abspath(args.out)
    views_dir = os.path.join(out_dir, 'views')
    os.makedirs(views_dir, exist_ok=True)

    clear_scene()
    body, macro_h, height = build_with_height(brief)
    body.name = body.data.name = 'Human'
    arm = add_rig(body)
    print('RIG %s bones=%d' % (arm.name, len(arm.data.bones)))

    world = evaluated_world_coords(body)
    jaw_head, chin, head_top = landmarks(arm)
    print(
        'LANDMARKS jaw_head=%s chin=%s head_top=%s'
        % (tuple(round(v, 4) for v in jaw_head), tuple(round(v, 4) for v in chin), tuple(round(v, 4) for v in head_top))
    )

    vclass, mat_index, show, hidden_hair = classify(body, world, brief, height, jaw_head, chin, head_top)
    apply_materials(body, brief, mat_index)
    shown = apply_show_mask(body, show)
    print('CLASSIFY faces=%d hair_faces_hidden=%d show2d_verts=%d' % (len(mat_index), hidden_hair, shown))

    apply_pose(arm, args.pose)
    setup_world_and_light()
    scene = setup_render(args.res_wh)

    posed, body_flags = posed_body_points(body)
    cam = make_camera()
    dist, centre_z = frame_camera(posed, [YAW[v] for v in args.view_list])
    print(
        'CAMERA dist=%.3f centre_z=%.3f lens=%.0f res=%dx%d'
        % (dist, centre_z, CAM_LENS, args.res_wh[0], args.res_wh[1])
    )

    mouth_centre, mouth_w = mouth_points(posed, body_flags, jaw_head, chin)
    mouth_edge = Vector((mouth_centre.x + mouth_w / 2.0, mouth_centre.y, mouth_centre.z))
    print('MOUTH world=%s width=%.4f' % (tuple(round(v, 4) for v in mouth_centre), mouth_w))

    result = {
        'brief': brief,
        'height_m': round(height, 4),
        'height_macro': round(macro_h, 4),
        'res': list(args.res_wh),
        'views': {},
    }
    for view in args.view_list:
        yaw = YAW[view]
        place_camera(cam, yaw, dist, centre_z)
        rel = 'views/%s.png' % view
        still = render_still(scene, os.path.join(views_dir, '%s.png' % view))
        mouth_px = to_pixels(scene, cam, mouth_centre, args.res_wh)
        edge_px = to_pixels(scene, cam, mouth_edge, args.res_wh)
        entry = {
            'yaw': yaw,
            'file': rel,
            'mouth_px': mouth_px,
            'mouth_w_px': round(abs(edge_px[0] - mouth_px[0]) * 2.0, 2),
            'head_top_px': to_pixels(scene, cam, head_top, args.res_wh),
            'chin_px': to_pixels(scene, cam, chin, args.res_wh),
            'bbox': alpha_bbox(still),
        }
        result['views'][view] = entry
        print(
            'VIEW %-9s yaw=%-5.0f mouth=%s w=%.1f head_top=%s chin=%s bbox=%s'
            % (view, yaw, entry['mouth_px'], entry['mouth_w_px'], entry['head_top_px'], entry['chin_px'], entry['bbox'])
        )

    with open(os.path.join(out_dir, 'views.json'), 'w', encoding='utf-8') as fh:
        json.dump(result, fh, indent=2)

    if not args.no_save:
        blend = os.path.join(out_dir, 'character.blend')
        bpy.ops.wm.save_as_mainfile(filepath=blend)
        print('SAVED %s' % blend)
    print('DONE %s height=%.4f views=%d' % (brief['name'], height, len(args.view_list)))


if __name__ == '__main__':
    main()
