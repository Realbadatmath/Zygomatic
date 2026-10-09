# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""
Blender headless character generation script.

Called by blender_character_service.py via:
    blender --background --python generate_character.py -- \
        --hair-color auburn --eye-color blue --gender female \
        --height 1.70 --style animated --hair-style long_wavy \
        --output-dir /tmp/char_abc

Renders ~56 training images with lighting and camera diversity:
  14 full-body turntable angles × 3 lighting presets (warm/neutral/cool) = 42 images
  4 wide shots (distance=2.2, lens=35) + 4 portrait (waist-up) + 6 face close-ups = 14 images
  Total ~56 diverse images — varied pose, lighting, and camera distance for LoRA generalization.
Toon shader for animated style; Principled BSDF for photorealistic.
Hair geometry is driven by --hair-style; short/medium/long/bun/ponytail/braid variants.
"""

import bpy
import importlib.util
import json
import math
import os
import sys
import tempfile
import argparse
import logging as _zyg_logging

# The body geometry lives next to this file in generate_character_body.py: the
# hair buckets (_BALD_STYLES, _SHAVED_STYLES, _SHORT_AFRO_STYLES), the
# FACIAL_HAIR ladder, the muscle-mass interpolation (_mm_sw, _mm_aw) and one
# builder per part.  The package import is the normal one; Blender loads this
# script BY PATH, with no package context and no zyg_workflows on sys.path, so
# there the sibling is loaded straight from its file.
try:
    from zyg_workflows.blender_scripts import generate_character_body as _body
except ImportError:
    _spec = importlib.util.spec_from_file_location(
        'generate_character_body',
        os.path.join(os.path.dirname(os.path.abspath(__file__)), 'generate_character_body.py'),
    )
    _body = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(_body)

_zyg_log = _zyg_logging.getLogger(__name__)


# ── Parse args after '--' separator ────────────────────────────────────────────
argv = sys.argv
if '--' in argv:
    argv = argv[argv.index('--') + 1 :]
else:
    argv = []

parser = argparse.ArgumentParser()
parser.add_argument('--hair-color', default='brown', help='Hair color name or hex')
parser.add_argument('--eye-color', default='brown', help='Eye color name or hex')
parser.add_argument('--skin-tone', default='medium', help='light/medium/dark/custom-hex')
parser.add_argument('--gender', default='female', choices=['male', 'female', 'neutral'])
parser.add_argument('--height', default='1.70', help='Character height in metres (1.50–2.00)')
parser.add_argument('--style', default='animated', choices=['animated', 'photorealistic'])
parser.add_argument(
    '--output-dir', default=os.path.join(tempfile.gettempdir(), 'storyteller_char'), help='Output directory'
)
parser.add_argument('--resolution', default='768', help='Render resolution (square)')
parser.add_argument('--hair-style', default='auto', help='Hair style name (auto=use gender default)')
parser.add_argument('--facial-hair', default='none', help='Facial hair style for male characters')
parser.add_argument('--muscle-mass', default='2', help='Muscle mass level 1-5 (1=slim, 5=very muscular)')
args = parser.parse_args(argv)

OUTPUT_DIR = args.output_dir
STYLE = args.style
GENDER = args.gender
RESOLUTION = int(args.resolution)
HAIR_STYLE = (args.hair_style or 'auto').strip().lower()
FACIAL_HAIR = (args.facial_hair or 'none').strip().lower()
try:
    MUSCLE_MASS = max(1, min(100, int(args.muscle_mass or '20')))
except ValueError:
    MUSCLE_MASS = 20

try:
    HEIGHT_M = float(args.height)
except ValueError:
    HEIGHT_M = 1.70
HEIGHT_M = max(1.50, min(2.00, HEIGHT_M))

os.makedirs(OUTPUT_DIR, exist_ok=True)

# ── Colour mapping ──────────────────────────────────────────────────────────────
_HAIR_COLOURS = {
    'blonde': (0.9, 0.78, 0.45, 1),
    'golden blonde': (0.85, 0.72, 0.35, 1),
    'light brown': (0.45, 0.28, 0.15, 1),
    'brown': (0.30, 0.18, 0.08, 1),
    'dark brown': (0.18, 0.10, 0.04, 1),
    'auburn': (0.42, 0.15, 0.07, 1),
    'red': (0.55, 0.12, 0.04, 1),
    'ginger': (0.70, 0.28, 0.08, 1),
    'black': (0.04, 0.03, 0.03, 1),
    'grey': (0.60, 0.60, 0.60, 1),
    'white': (0.90, 0.90, 0.90, 1),
    'silver': (0.80, 0.82, 0.85, 1),
    'blue': (0.10, 0.25, 0.80, 1),
    'pink': (0.90, 0.45, 0.60, 1),
    'purple': (0.45, 0.15, 0.75, 1),
    'green': (0.15, 0.55, 0.25, 1),
}
_EYE_COLOURS = {
    'blue': (0.15, 0.40, 0.85, 1),
    'light blue': (0.30, 0.60, 0.95, 1),
    'green': (0.20, 0.60, 0.30, 1),
    'hazel': (0.50, 0.38, 0.15, 1),
    'brown': (0.35, 0.20, 0.08, 1),
    'dark brown': (0.18, 0.10, 0.04, 1),
    'grey': (0.50, 0.52, 0.55, 1),
    'amber': (0.80, 0.55, 0.10, 1),
    'violet': (0.55, 0.20, 0.75, 1),
}
_SKIN_TONES = {
    'light': (0.95, 0.82, 0.72, 1),
    'fair': (0.98, 0.88, 0.80, 1),
    'medium': (0.85, 0.65, 0.50, 1),
    'olive': (0.72, 0.58, 0.40, 1),
    'tan': (0.62, 0.45, 0.30, 1),
    'dark': (0.40, 0.27, 0.17, 1),
    'deep': (0.25, 0.16, 0.10, 1),
}


def _parse_colour(name: str, palette: dict, fallback) -> tuple:
    """Return RGBA tuple for a colour name or #hex string."""
    name = name.strip().lower()
    if name in palette:
        return palette[name]
    if name.startswith('#') and len(name) in (7, 9):
        try:
            r = int(name[1:3], 16) / 255
            g = int(name[3:5], 16) / 255
            b = int(name[5:7], 16) / 255
            a = int(name[7:9], 16) / 255 if len(name) == 9 else 1.0
            return (r, g, b, a)
        except ValueError as _exc:
            _zyg_log.debug('colour not parsable as hex, using the fallback: %s', _exc)
    return fallback


HAIR_COLOR = _parse_colour(args.hair_color, _HAIR_COLOURS, (0.30, 0.18, 0.08, 1))
EYE_COLOR = _parse_colour(args.eye_color, _EYE_COLOURS, (0.35, 0.20, 0.08, 1))
SKIN_COLOR = _parse_colour(args.skin_tone, _SKIN_TONES, (0.85, 0.65, 0.50, 1))

# Height scale relative to 1.70 m baseline
HEIGHT_SCALE = HEIGHT_M / 1.70

# ── Scene reset ─────────────────────────────────────────────────────────────────
bpy.ops.object.select_all(action='SELECT')
bpy.ops.object.delete()

# ── World background ────────────────────────────────────────────────────────────
world = bpy.context.scene.world
if world is None:
    world = bpy.data.worlds.new('World')
    bpy.context.scene.world = world
world.use_nodes = True
bg_node = world.node_tree.nodes.get('Background')
if bg_node:
    # Neutral light-grey background for all styles — opaque renders only.
    # Keeps training images bright and character clearly visible for LoRA training.
    bg_node.inputs['Color'].default_value = (0.70, 0.70, 0.72, 1)
    bg_node.inputs['Strength'].default_value = 1.2


# ── Material factory ─────────────────────────────────────────────────────────────
def make_material(
    name: str, color: tuple, metallic: float = 0, roughness: float = 0.7, emission=None
) -> bpy.types.Material:
    mat = bpy.data.materials.new(name=name)
    mat.use_nodes = True
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    nodes.clear()

    out = nodes.new('ShaderNodeOutputMaterial')

    if STYLE == 'animated':
        # Diffuse BSDF — works in both EEVEE and Cycles (BsdfToon is Cycles-only)
        diff = nodes.new('ShaderNodeBsdfDiffuse')
        diff.inputs['Color'].default_value = color
        diff.inputs['Roughness'].default_value = 1.0  # flat/toon-like shading
        if emission:
            em = nodes.new('ShaderNodeEmission')
            em.inputs['Color'].default_value = emission
            em.inputs['Strength'].default_value = 0.25
            mix = nodes.new('ShaderNodeMixShader')
            mix.inputs['Fac'].default_value = 0.15
            links.new(diff.outputs['BSDF'], mix.inputs[1])
            links.new(em.outputs['Emission'], mix.inputs[2])
            links.new(mix.outputs['Shader'], out.inputs['Surface'])
        else:
            links.new(diff.outputs['BSDF'], out.inputs['Surface'])
    else:
        # Photorealistic: Principled BSDF
        bsdf = nodes.new('ShaderNodeBsdfPrincipled')
        bsdf.inputs['Base Color'].default_value = color
        bsdf.inputs['Metallic'].default_value = metallic
        bsdf.inputs['Roughness'].default_value = roughness
        bsdf.inputs['Specular IOR Level'].default_value = 0.5
        if name == 'skin':
            try:
                bsdf.inputs['Subsurface Weight'].default_value = 0.18
                bsdf.inputs['Subsurface Radius'].default_value = (0.8, 0.4, 0.2)
            except (KeyError, TypeError) as _exc:
                _zyg_log.debug('subsurface inputs not present on this Principled BSDF: %s', _exc)
        if emission:
            bsdf.inputs['Emission Color'].default_value = emission
            bsdf.inputs['Emission Strength'].default_value = 0.3
        links.new(bsdf.outputs['BSDF'], out.inputs['Surface'])

    return mat


# ── Pre-build materials ──────────────────────────────────────────────────────────
mat_skin = make_material('skin', SKIN_COLOR, roughness=0.55)
mat_hair = make_material('hair', HAIR_COLOR, roughness=0.80)
mat_eyes = make_material('eyes', EYE_COLOR, roughness=0.10, metallic=0.05)
mat_eyewhite = make_material('eyewhite', (0.95, 0.95, 0.95, 1), roughness=0.30)
mat_cloth_top = make_material('cloth_top', (0.20, 0.30, 0.50, 1), roughness=0.85)
mat_cloth_bot = make_material('cloth_bot', (0.15, 0.15, 0.20, 1), roughness=0.85)
mat_shoes = make_material('shoes', (0.08, 0.06, 0.05, 1), roughness=0.65)
mat_lips = make_material('lips', (0.70, 0.35, 0.30, 1), roughness=0.50)


# ── Helper: set material ────────────────────────────────────────────────────────
assign_material = _body.assign_material


# ── Build character ──────────────────────────────────────────────────────────────
def build_character():
    """Build every character mesh, in creation order, and return the list.

    The geometry itself is in generate_character_body.py; this only assembles the
    build context (scale, identity, materials, proportions) and calls one builder
    per part in the order the renders expect.
    """
    ctx = _body.CharacterBuild(
        s=HEIGHT_SCALE,  # uniform scale
        gender=GENDER,
        hair_style=HAIR_STYLE,
        facial_hair=FACIAL_HAIR,
        mats=_body.CharacterMaterials(
            skin=mat_skin,
            hair=mat_hair,
            eyes=mat_eyes,
            eyewhite=mat_eyewhite,
            cloth_top=mat_cloth_top,
            cloth_bot=mat_cloth_bot,
            shoes=mat_shoes,
            lips=mat_lips,
        ),
        prop=_body.body_proportions(GENDER, MUSCLE_MASS),
    )
    _body.add_head(ctx)
    _body.add_hair(ctx)
    _body.add_facial_hair(ctx)
    _body.add_eyes(ctx)
    _body.add_trunk(ctx)
    _body.add_arms(ctx)
    _body.add_legs(ctx)
    return ctx.objs


character_objects = build_character()

# ── Smoothing for photorealistic ─────────────────────────────────────────────────
if STYLE == 'photorealistic':
    for obj in character_objects:
        if obj.type == 'MESH':
            bpy.context.view_layer.objects.active = obj
            bpy.ops.object.shade_smooth()


# ── Lighting ────────────────────────────────────────────────────────────────────
def add_light(name, type_, location, energy, color=(1, 1, 1)):
    light_data = bpy.data.lights.new(name=name, type=type_)
    light_data.energy = energy
    light_data.color = color
    obj = bpy.data.objects.new(name, light_data)
    bpy.context.collection.objects.link(obj)
    obj.location = location
    return obj


if STYLE == 'animated':
    add_light('Key', 'SUN', (3, -4, 5), energy=4.0, color=(1.00, 0.98, 0.92))
    add_light('Fill', 'AREA', (-3, 2, 3), energy=400, color=(0.85, 0.90, 1.00))
    add_light('Rim', 'SPOT', (0, 3, 4), energy=300, color=(1.00, 1.00, 1.00))
else:
    add_light('Key', 'SUN', (3, -4, 6), energy=2.5, color=(1.00, 0.96, 0.88))
    add_light('Fill', 'AREA', (-4, 2, 4), energy=250, color=(0.80, 0.88, 1.00))
    add_light('Rim', 'POINT', (1, 3, 5), energy=350, color=(1.00, 0.95, 0.80))
    add_light('Under', 'AREA', (0, -1, 0), energy=100, color=(0.60, 0.65, 0.80))

# ── Render settings ──────────────────────────────────────────────────────────────
scene = bpy.context.scene
if STYLE == 'photorealistic':
    scene.render.engine = 'CYCLES'
    scene.cycles.samples = 64
    scene.cycles.use_denoising = True
    scene.cycles.device = 'GPU'
    try:
        prefs = bpy.context.preferences.addons['cycles'].preferences
        prefs.compute_device_type = 'CUDA'
        prefs.get_devices()
        for d in prefs.devices:
            d.use = True
    except Exception:
        scene.cycles.device = 'CPU'
        scene.cycles.samples = 48
else:
    scene.render.engine = 'BLENDER_EEVEE_NEXT'
    scene.eevee.taa_render_samples = 16
scene.render.resolution_x = RESOLUTION
scene.render.resolution_y = RESOLUTION
scene.render.resolution_percentage = 100
scene.render.image_settings.file_format = 'PNG'
scene.render.image_settings.color_mode = 'RGB'
scene.render.film_transparent = False  # solid background so LoRA trains on visible character, not black void

# ── Camera helper ────────────────────────────────────────────────────────────────
cam_data = bpy.data.cameras.new('Camera')
cam_data.lens = 50  # 50mm lens
cam_obj = bpy.data.objects.new('Camera', cam_data)
bpy.context.collection.objects.link(cam_obj)
scene.camera = cam_obj


def set_camera(distance: float, height: float, angle_deg: float, target_z: float = 0.9, lens: float = 50):
    """Position camera on a circle around the character."""
    rad = math.radians(angle_deg)
    cam_obj.location.x = distance * math.sin(rad)
    cam_obj.location.y = -distance * math.cos(rad)
    cam_obj.location.z = height
    cam_data.lens = lens
    # Blender XYZ Euler: M = Rz(Z) * Ry(Y) * Rx(X).
    # Camera forward = M*(0,0,-1) = (-sin(Z)*sin(X), cos(Z)*sin(X), -cos(X))
    # For X=pi/2 (horizontal look): forward = (-sin(Z), cos(Z), 0)
    # Solve for Z so forward == (dx, dy)/horiz:  Z = atan2(-dx, dy)
    dx = -cam_obj.location.x
    dy = -cam_obj.location.y
    dz = target_z - cam_obj.location.z
    horiz = math.sqrt(dx * dx + dy * dy)
    cam_obj.rotation_euler = (
        math.pi / 2 + math.atan2(-dz, horiz),  # X: 90° base + vertical tilt
        0,  # Y: no roll
        math.atan2(-dx, dy),  # Z: yaw toward target
    )


# ── Render angles ────────────────────────────────────────────────────────────────
# Layout (targeting ~60 high-quality varied images):
#   - 14 full-body turntable angles (every ~26°) × 3 lighting presets  = 42 images
#   - 4 wide-shot angles (different camera distance)                    =  4 images
#   - 6 face close-ups (front + three sides)                            =  6 images
#   - 4 medium/portrait shots                                           =  4 images
# Total: 56 images — varied pose, lighting, and camera distance for LoRA generalization

# 14 evenly-spaced turntable angles
_full_body_angles = [i * (360 / 14) for i in range(14)]

# 3 lighting presets: warm daylight / cool neutral / bright high-key
_LIGHTING_PRESETS = [
    ('warm', (0.90, 0.78, 0.60, 1), 1.4),  # warm golden tone
    ('neutral', (0.72, 0.72, 0.74, 1), 1.2),  # clean neutral grey
    ('cool', (0.65, 0.72, 0.85, 1), 1.1),  # cool soft blue-white
]

renders = []

# ── Full-body turntable × 3 lighting presets ────────────────────────────────────
for _preset_name, _preset_color, _preset_strength in _LIGHTING_PRESETS:
    if bg_node:
        bg_node.inputs['Color'].default_value = _preset_color
        bg_node.inputs['Strength'].default_value = _preset_strength
    for i, ang in enumerate(_full_body_angles):
        set_camera(distance=1.6, height=0.85 * HEIGHT_SCALE, angle_deg=ang, target_z=0.95 * HEIGHT_SCALE, lens=50)
        path = os.path.join(OUTPUT_DIR, f'full_{_preset_name}_{i:02d}_{int(ang):03d}deg.png')
        scene.render.filepath = path
        bpy.ops.render.render(write_still=True)
        renders.append(path)

# Reset to neutral lighting for remaining shots
if bg_node:
    bg_node.inputs['Color'].default_value = (0.72, 0.72, 0.74, 1)
    bg_node.inputs['Strength'].default_value = 1.2

# ── Wide shots — different camera distance for distance-framing diversity ────────
_wide_angles = [0, 90, 180, 270]
for i, ang in enumerate(_wide_angles):
    set_camera(distance=2.2, height=0.80 * HEIGHT_SCALE, angle_deg=ang, target_z=0.90 * HEIGHT_SCALE, lens=35)
    path = os.path.join(OUTPUT_DIR, f'wide_{i:02d}_{int(ang):03d}deg.png')
    scene.render.filepath = path
    bpy.ops.render.render(write_still=True)
    renders.append(path)

# ── Medium / portrait shots (waist-up framing) ───────────────────────────────────
_portrait_angles = [0, 45, 180, 315]
for i, ang in enumerate(_portrait_angles):
    set_camera(distance=1.4, height=1.30 * HEIGHT_SCALE, angle_deg=ang, target_z=1.35 * HEIGHT_SCALE, lens=70)
    path = os.path.join(OUTPUT_DIR, f'portrait_{i:02d}_{int(ang):03d}deg.png')
    scene.render.filepath = path
    bpy.ops.render.render(write_still=True)
    renders.append(path)

# ── Face close-ups ───────────────────────────────────────────────────────────────
_face_angles = [0, 45, 90, 180, 270, 315]
for i, ang in enumerate(_face_angles):
    set_camera(distance=0.55, height=1.62 * HEIGHT_SCALE, angle_deg=ang, target_z=1.62 * HEIGHT_SCALE, lens=85)
    path = os.path.join(OUTPUT_DIR, f'face_{i:02d}_{int(ang):03d}deg.png')
    scene.render.filepath = path
    bpy.ops.render.render(write_still=True)
    renders.append(path)

# Write manifest so the service wrapper knows what was produced
manifest_path = os.path.join(OUTPUT_DIR, 'manifest.json')
with open(manifest_path, 'w') as mf:
    json.dump(
        {
            'style': STYLE,
            'gender': GENDER,
            'hair_color': args.hair_color,
            'hair_style': HAIR_STYLE,
            'eye_color': args.eye_color,
            'skin_tone': args.skin_tone,
            'height_m': HEIGHT_M,
            'facial_hair': FACIAL_HAIR,
            'muscle_mass': MUSCLE_MASS,
            'images': renders,
            'total': len(renders),
        },
        mf,
        indent=2,
    )

_zyg_log.info(
    f'[generate_character] Rendered {len(renders)} images (42 full-body×3 lights + 4 wide + 4 portrait + 6 face) → {OUTPUT_DIR}'
)
