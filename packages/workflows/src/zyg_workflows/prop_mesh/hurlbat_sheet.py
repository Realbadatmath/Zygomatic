# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""hurlbat_sheet.py — the weapon alone, large, from several angles (2026-08-04).

RUN:
    blender -b -P prop_mesh/hurlbat_sheet.py -- --out output/axe_forest/hurlbat

WHY THIS EXISTS. In the forest plate the hurlbat occupies about 170x270px, seen obliquely,
dark against busy bark — and it reads as a folded shape. That could be a bad ASSET or bad
STAGING, and those need completely different fixes: remodel versus reframe. Iterating on the
scene cannot tell them apart, because every change moves both at once.

So the weapon is rendered by itself, filling the frame, on a neutral ground, from the three
angles that matter: face-on (is the silhouette right?), three-quarter (does the plate read
as a plate?), and edge-on (is the 6mm thickness and its grind correct?). Whatever is wrong
is unambiguous here.

Lit the way metal is actually lit — a soft key on the reflection side plus a rim — rather
than by the scene's overcast dome, because the question here is what the OBJECT looks like,
not what this shot does to it.
"""

import math
import os
import sys
import tempfile

import bpy

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import hurlbat  # noqa: E402
import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)


def _argv():
    a = sys.argv
    return a[a.index('--') + 1 :] if '--' in a else []


def _opt(args, name, default, cast=float):
    if name in args:
        try:
            return cast(args[args.index(name) + 1])
        except Exception:
            return default
    return default


ARGS = _argv()
OUT = _opt(ARGS, '--out', os.path.join(tempfile.gettempdir(), 'hurlbat_sheet'), str)
W = int(_opt(ARGS, '--w', 720))
H = int(_opt(ARGS, '--h', 900))
SAMPLES = int(_opt(ARGS, '--samples', 128))
os.makedirs(OUT, exist_ok=True)

bpy.ops.wm.read_factory_settings(use_empty=True)
scene = bpy.context.scene

mat = bpy.data.materials.new('steel')
mat.use_nodes = True
b = mat.node_tree.nodes['Principled BSDF']
b.inputs['Base Color'].default_value = (0.32, 0.33, 0.35, 1.0)
b.inputs['Metallic'].default_value = 1.0
b.inputs['Roughness'].default_value = 0.30

ob = hurlbat.build(mat, scene)

world = bpy.data.worlds.new('w')
world.use_nodes = True
world.node_tree.nodes['Background'].inputs['Color'].default_value = (0.16, 0.17, 0.19, 1)
world.node_tree.nodes['Background'].inputs['Strength'].default_value = 1.0
scene.world = world


def area(name, loc, energy, size, target=(0, 0, 0)):
    ld = bpy.data.lights.new(name, 'AREA')
    ld.energy = energy
    ld.size = size
    o = bpy.data.objects.new(name, ld)
    o.location = loc
    from mathutils import Vector

    d = (Vector(target) - Vector(loc)).normalized()
    o.rotation_mode = 'QUATERNION'
    o.rotation_quaternion = d.to_track_quat('-Z', 'Y')
    scene.collection.objects.link(o)
    return o


area('key', (-1.3, -1.6, 1.5), 900, 2.4)
area('fill', (1.7, -1.1, 0.2), 260, 2.0)
area('rim', (0.9, 1.6, 1.1), 500, 1.6)

cam_d = bpy.data.cameras.new('cam')
cam_d.lens = 85.0
cam = bpy.data.objects.new('cam', cam_d)
scene.collection.objects.link(cam)
scene.camera = cam

scene.render.engine = 'CYCLES'
scene.cycles.samples = SAMPLES
scene.render.resolution_x = W
scene.render.resolution_y = H
scene.render.film_transparent = False
try:
    scene.cycles.device = 'CPU'
except AttributeError as _exc:
    _zyg_log.debug('cycles CPU device not set (no cycles settings on this scene): %s', _exc)

# yaw about the shaft axis: 0 = face-on to the plate, 90 = edge-on
for name, yaw in (('face_on', 0.0), ('three_quarter', 38.0), ('edge_on', 84.0)):
    a = math.radians(yaw)
    r = 0.85
    cam.location = (r * math.sin(a), -r * math.cos(a), 0.02)
    cam.rotation_euler = (math.radians(90), 0.0, a)
    scene.render.filepath = os.path.join(OUT, name)
    bpy.ops.render.render(write_still=True)
    _zyg_log.info('HURLBAT_VIEW %s -> %s.png' % (name, os.path.join(OUT, name)))

_zyg_log.info('HURLBAT_SHEET_OK %s' % OUT)
