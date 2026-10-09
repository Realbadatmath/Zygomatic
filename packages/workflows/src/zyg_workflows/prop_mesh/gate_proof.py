# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""gate_proof.py — Phase 0: prove the gate catches a failure we already rejected by eye.

RUN:
    blender -b -P prop_mesh/gate_proof.py -- --out output/axe_forest/gate_proof

WHY THIS EXISTS BEFORE ANYTHING ELSE IS BUILT.
The whole geometry plan rests on a quality gate. A gate nobody has falsified is decoration.
So the first thing built is not the tree, not the manifest, not the restyle — it is a scene
rendered in TWO configurations that differ in one respect, where we already know by eye
which one is wrong:

    embedded  the hatchet is driven into the trunk, bit buried, poll proud
    flat      the same hatchet translated 50mm toward the camera, so it touches nothing

`flat` is the exact defect from 2026-08-03: "not one axe is actually stuck in the tree, all
axes are just flat against it". If gate.g3b_embedment does not separate these two, the
metric is wrong and nothing downstream is worth building. If it does, we have a check that
would have caught that render before it was ever looked at.

The scars get the same treatment: the trunk is rendered with the boolean cuts on and off,
which is the paired input g3_relief needs.

SIX PASS SETS, one directory each:
    trunk_cut / trunk_plain            G3  — do the cuts survive into depth and normals
    axe_embedded_scene / _alone        G3b — how much of the blade does the wood take
    axe_flat_scene / _alone            G3b — the control; a pasted prop loses nothing

Geometry, lighting and camera are lifted from prop_mesh/axe_render.py unchanged, including
the two axis facts that cost two bad renders to find: the trunk faces -Y so the camera sits
on -Y looking +Y, and the head is a slab in X-Z (broad side to camera), thin in Y.
"""

import math
import os
import random
import sys
import tempfile

import bpy

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pass_lib  # noqa: E402
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
OUT = _opt(ARGS, '--out', os.path.join(tempfile.gettempdir(), 'gate_proof'), str)
W = int(_opt(ARGS, '--w', 1216))
H = int(_opt(ARGS, '--h', 704))
N_CUTS = int(_opt(ARGS, '--cuts', 24))
SEED = int(_opt(ARGS, '--seed', 5))
SAMPLES = int(_opt(ARGS, '--samples', 32))
TRUNK_R = _opt(ARGS, '--trunk-r', 0.42)
CLUSTER_R = _opt(ARGS, '--cluster-r', 0.085)
# how far toward the camera the FLAT configuration moves the axe. 50mm is comfortably more
# than the head's 26mm thickness, so no part of it can be inside the wood.
FLAT_OFFSET = _opt(ARGS, '--flat-offset', 0.050)

os.makedirs(OUT, exist_ok=True)
random.seed(SEED)

bpy.ops.wm.read_factory_settings(use_empty=True)
scene = bpy.context.scene


def _mat(name, rgb, rough=0.85, metallic=0.0):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    b = m.node_tree.nodes['Principled BSDF']
    b.inputs['Base Color'].default_value = (*rgb, 1.0)
    b.inputs['Roughness'].default_value = rough
    b.inputs['Metallic'].default_value = metallic
    return m


MAT_TRUNK = _mat('trunk', (0.50, 0.50, 0.50), 0.88)
MAT_OLD = _mat('cut_old', (0.16, 0.13, 0.10), 0.95)
MAT_FRESH = _mat('cut_fresh', (0.72, 0.60, 0.40), 0.75)
MAT_STEEL = _mat('steel', (0.30, 0.31, 0.33), 0.42, 0.85)
MAT_HAFT = _mat('haft', (0.38, 0.27, 0.17), 0.80)


def _solid(name, verts, faces, mat):
    me = bpy.data.meshes.new(name)
    me.from_pydata(verts, [], faces)
    me.validate()
    me.update()
    ob = bpy.data.objects.new(name, me)
    ob.data.materials.append(mat)
    scene.collection.objects.link(ob)
    return ob


def _box(name, cx, cy, cz, sx, sy, sz, mat, rot_z=0.0, rot_y=0.0):
    hx, hy, hz = sx / 2, sy / 2, sz / 2
    v = [
        (-hx, -hy, -hz),
        (hx, -hy, -hz),
        (hx, hy, -hz),
        (-hx, hy, -hz),
        (-hx, -hy, hz),
        (hx, -hy, hz),
        (hx, hy, hz),
        (-hx, hy, hz),
    ]
    f = [(0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)]
    ob = _solid(name, v, f, mat)
    ob.rotation_euler = (0.0, math.radians(rot_y), math.radians(rot_z))
    ob.location = (cx, cy, cz)
    return ob


def _surface_y(u):
    """Depth of the trunk's front face at horizontal offset u. X across, Z up, Y into."""
    return TRUNK_R - math.sqrt(max(TRUNK_R**2 - u**2, 1e-6))


# ── trunk ───────────────────────────────────────────────────────────────────
bpy.ops.mesh.primitive_cylinder_add(vertices=128, radius=TRUNK_R, depth=3.0, location=(0, TRUNK_R, 0))
trunk = bpy.context.object
trunk.name = 'trunk'
trunk.data.materials.append(MAT_TRUNK)
pass_lib.tag(trunk, 'trunk')

# ── the cut cluster, one boolean modifier per cutter ─────────────────────────
# One modifier PER CUT is the documented requirement — "use multiple Boolean modifiers if
# the cutter contains multiple meshes". Joining disjoint shells into one cutter has no
# coherent inside and subtracts the trunk's whole volume instead of the slots.
cuts = []
for i in range(N_CUTS):
    ang = random.uniform(0, math.tau)
    rad = CLUSTER_R * math.sqrt(random.uniform(0.03, 1.0))
    ux = rad * math.cos(ang)
    vz = rad * math.sin(ang) * 0.85
    ln = random.uniform(0.030, 0.062)
    wd = random.uniform(0.016, 0.032)
    dep = random.uniform(0.030, 0.055)
    tilt = random.uniform(-62, 62)
    mat = MAT_FRESH if (i % 4 == 0) else MAT_OLD
    ob = _box('cut%d' % i, ux, _surface_y(ux) + dep * 0.35, vz, wd, dep, ln, mat)
    ob.rotation_euler = (0.0, math.radians(tilt), 0.0)
    cuts.append(ob)

_bools = []
for ob in cuts:
    bpy.context.view_layer.objects.active = ob
    ob.select_set(True)
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    bpy.ops.object.mode_set(mode='EDIT')
    bpy.ops.mesh.select_all(action='SELECT')
    bpy.ops.mesh.remove_doubles(threshold=1e-5)
    bpy.ops.mesh.normals_make_consistent(inside=False)
    bpy.ops.object.mode_set(mode='OBJECT')
    ob.select_set(False)
    ob.hide_render = True  # cutters are never rendered themselves
    m = trunk.modifiers.new('scarcut_%s' % ob.name, 'BOOLEAN')
    m.operation = 'DIFFERENCE'
    m.object = ob
    m.solver = 'EXACT'
    _bools.append(m)


def set_cuts(on):
    for m in _bools:
        m.show_render = bool(on)


# ── the hatchet ─────────────────────────────────────────────────────────────
AXE_X = AXE_Z = 0.0
_by = _surface_y(AXE_X)
HEAD_W, HEAD_H, HEAD_T = 0.115, 0.078, 0.026
HAFT_L = 0.235

head = _box('axe_head', AXE_X, _by + 0.006, AXE_Z, HEAD_W, HEAD_T, HEAD_H, MAT_STEEL)
head.rotation_euler = (math.radians(-24.0), 0.0, 0.0)
pass_lib.tag(head, 'axe_head')

haft = _box('axe_haft', AXE_X, _by - 0.070, AXE_Z - 0.125, 0.030, 0.032, HAFT_L, MAT_HAFT)
haft.rotation_euler = (math.radians(-24.0), 0.0, math.radians(4.0))
pass_lib.tag(haft, 'axe_haft')

axe = [head, haft]
_axe_home = [tuple(o.location) for o in axe]


def set_axe_flat(flat):
    """FLAT is the defect: the whole hatchet translated toward the camera until no part of
    it is inside the wood. Same object, same light, same camera — only the seating differs."""
    for ob, home in zip(axe, _axe_home):
        ob.location = (home[0], home[1] - (FLAT_OFFSET if flat else 0.0), home[2])


# ── light + camera, unchanged from axe_render.py ────────────────────────────
sun = bpy.data.lights.new('key', 'SUN')
sun.energy = 3.4
sun.angle = math.radians(9.0)
sun_ob = bpy.data.objects.new('key', sun)
sun_ob.rotation_euler = (math.radians(58), math.radians(-6), math.radians(38))
scene.collection.objects.link(sun_ob)

fill = bpy.data.lights.new('fill', 'SUN')
fill.energy = 0.8
fill_ob = bpy.data.objects.new('fill', fill)
fill_ob.rotation_euler = (math.radians(70), 0.0, math.radians(-135))
scene.collection.objects.link(fill_ob)

cam_d = bpy.data.cameras.new('cam')
cam_d.lens = 62.0
cam = bpy.data.objects.new('cam', cam_d)
cam.location = (0.0, -1.55, 0.0)
cam.rotation_euler = (math.radians(90), 0.0, 0.0)
scene.collection.objects.link(cam)
scene.camera = cam

scene.render.engine = 'CYCLES'
scene.cycles.samples = SAMPLES
scene.render.resolution_x = W
scene.render.resolution_y = H
# Data passes need the real surface, so no transparent film and no holdout anywhere.
scene.render.film_transparent = False
try:
    scene.cycles.device = 'CPU'
except AttributeError as _exc:
    _zyg_log.debug('cycles CPU device not set (no cycles settings on this scene): %s', _exc)


def emit(name, cuts_on, axe_on, trunk_on, flat=False):
    set_cuts(cuts_on)
    set_axe_flat(flat)
    trunk.hide_render = not trunk_on
    pass_lib.hide(axe, not axe_on)
    d = pass_lib.render_set(name, OUT, scene=scene, samples=SAMPLES)
    _zyg_log.info('GATE_PROOF_SET %s -> %s' % (name, d))


# G3: the cuts, on and off, axe out of the way
emit('trunk_cut', True, False, True)
emit('trunk_plain', False, False, True)

# G3b: seated vs pasted. The trunk carries no cuts here so the only difference between
# the two configurations is the 50mm of seating.
emit('axe_embedded_scene', False, True, True, flat=False)
emit('axe_embedded_alone', False, True, False, flat=False)
emit('axe_flat_scene', False, True, True, flat=True)
emit('axe_flat_alone', False, True, False, flat=True)

_zyg_log.info('GATE_PROOF_OK %s' % OUT)
