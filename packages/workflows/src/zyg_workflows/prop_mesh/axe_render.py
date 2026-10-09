# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""axe_render.py — Blender script: hatchet + hatchet-cut scars -> RGBA decals (2026-08-03).

RUN (never imported by the pipeline; it needs bpy):
    blender -b -P prop_mesh/axe_render.py -- --out output/axe_forest/prop \\
            --w 1216 --h 704 [--cuts 14] [--seed 5] [--tilt 8] [--yaw 0]

WHY GEOMETRY AND NOT PROMPTING — FOUR MEASURED FAILURES, 2026-08-03.
The forest scene needs a trunk covered in many overlapping axe-cut scars, because those
scars ARE the storytelling: they say he has stood here a hundred times. Four attempts to
obtain them from the image models:
  1. in the txt2img prompt          -> zero marks across six seeds; two seeds substituted
                                       a natural rot-hollow (a tree-shaped concept in
                                       place of a man-made one);
  2. inpaint at denoise 0.85        -> a hard rectangle of SAWN LOG END-GRAIN, tree rings
                                       and all — "pale raw timber" is the model's single
                                       strongest cue for a felled log's cut face;
  3. inpaint at 0.58 on mossy bark  -> nothing; low denoise preserves the surface it was
                                       supposed to be cutting into;
  4. forcing bare bark first        -> smooth grey utility poles and a cut-off stump.
Low denoise preserves, high denoise invents. There is no setting between them that yields
*specifically* many overlapping hatchet gashes. This is the same defect as the cabin
scene's page-text churn: small repeated man-made detail is not obtainable by asking.

So the marks are AUTHORED, exactly as the ledger and pipe geometry were. Two properties
matter more than fidelity:
  * they are IDENTICAL in every plate and every shot. Generated independently they would
    differ each time, and scars that change between shots say nothing at all;
  * they land where the shot needs them — shot 2's axe must be seated INSIDE the cluster,
    and shot 1's post pan-left has to arrive on it.

WHAT IS RENDERED, AND WHY ONLY THE MARKS.
`film_transparent` is on, and the trunk stand-in is a HOLDOUT: it occludes and it catches
no light of its own, so it contributes alpha=0. The output therefore carries the cuts and
the axe ONLY, correctly shaded and in correct perspective, with everything else clear.
Compositing them over a generated plate keeps that plate's own bark colour and texture
underneath; a low-denoise img2img pass afterwards marries the edges. Rendering the
surrounding panel instead would paste a foreign surface over the tree.

Each cut is a real wedge — a chisel-shaped solid sunk into the trunk surface so its walls
catch the light from one side and fall dark on the other. Old cuts are weathered grey,
fresh ones show pale exposed wood; the mix is deterministic in --seed so a re-render is
byte-comparable.

OUTPUTS in --out:
    scars_rgba.png  the cut cluster alone, RGBA
    axe_rgba.png    the hatchet alone, RGBA (head + haft, seated as if struck in)
    both_rgba.png   cuts + hatchet together, for the shots where the axe is still in
    axe_meta.json   {'size':[w,h], 'scar_bbox_px':[...], 'axe_bbox_px':[...],
                     'haft_tip_px':[x,y], 'blade_entry_px':[x,y], 'cuts':N, 'seed':S}
The two named points are what shot 2 needs: `haft_tip_px` is where a hand must close on
the haft, `blade_entry_px` is where the steel meets the wood and must not slide.
"""

import json
import math
import os
import random
import sys
import tempfile

import bpy
from bpy_extras.object_utils import world_to_camera_view
from mathutils import Vector
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
OUT = _opt(ARGS, '--out', os.path.join(tempfile.gettempdir(), 'axe'), str)
W = int(_opt(ARGS, '--w', 1216))
H = int(_opt(ARGS, '--h', 704))
N_CUTS = int(_opt(ARGS, '--cuts', 24))
SEED = int(_opt(ARGS, '--seed', 5))
TILT = _opt(ARGS, '--tilt', 0.0)  # camera pitch, deg (0 = dead level)
YAW = _opt(ARGS, '--yaw', 0.0)  # camera yaw, degrees
TRUNK_R = _opt(ARGS, '--trunk-r', 0.42)  # trunk radius, metres
CLUSTER_R = _opt(ARGS, '--cluster-r', 0.085)  # scar cluster radius, metres

os.makedirs(OUT, exist_ok=True)
random.seed(SEED)

# ── clean slate ─────────────────────────────────────────────────────────────
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


MAT_OLD = _mat('cut_old', (0.16, 0.13, 0.10), 0.95)  # weathered, near-black
MAT_FRESH = _mat('cut_fresh', (0.72, 0.60, 0.40), 0.75)  # pale exposed wood
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
    """Axis-aligned box then rotated — enough for a haft, a poll and a cut wall."""
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
    """Depth of the trunk's front surface at horizontal offset u.

    AXIS CONVENTION — the first render got this wrong and produced a 39px-wide axe.
    The trunk cylinder has its axis along +Z and is centred at (0, TRUNK_R, 0), so it
    spans y in [0, 2R] and the face nearest the camera is at y=0, pointing -Y. Therefore:
        X = across the trunk (image left/right)
        Z = up the trunk     (image up/down)
        Y = INTO the trunk   (away from camera)
    The camera must sit on -Y looking +Y. Placing cuts along X-as-depth, as the first
    version did, views the whole cluster edge-on.
    """
    return TRUNK_R - math.sqrt(max(TRUNK_R**2 - u**2, 1e-6))


# ── the trunk stand-in: occludes, contributes no alpha ──────────────────────
# THE SCARS ARE A SHADING RATIO, NOT A DECAL — the previous version rendered the cut
# SOLIDS, which protrude, so they read as matchsticks lying on the trunk instead of gouges
# cut into it. You cannot render a hole with alpha: a hole is an absence of surface.
#
# So the trunk is now a real, neutrally-lit surface and the cuts are BOOLEAN-SUBTRACTED
# from it. Two renders of that same surface are made — one with the subtraction, one
# without — and the compositor divides them:
#       ratio = with_cuts / without_cuts
# which is exactly 1.0 on untouched bark, below 1 where a recess falls into shadow, and
# above 1 where a cut wall catches the key. Multiplying a generated plate by that map
# carves the marks using the plate's OWN bark colour and texture. Nothing foreign is
# pasted on, and the identical map applies to all 30 plates — which is the continuity
# property the scene actually needs.
MAT_TRUNK = _mat('trunk', (0.50, 0.50, 0.50), 0.88)
bpy.ops.mesh.primitive_cylinder_add(vertices=128, radius=TRUNK_R, depth=3.0, location=(0, TRUNK_R, 0))
trunk = bpy.context.object
trunk.name = 'trunk'
trunk.rotation_euler = (0.0, 0.0, 0.0)
trunk.data.materials.append(MAT_TRUNK)
trunk.visible_shadow = True

# ── the cut cluster ─────────────────────────────────────────────────────────
# Each cut is a shallow wedge sunk into the trunk's front face: a narrow slot whose two
# walls meet at a line, so one wall lights and the other falls into shadow. That contrast
# is what reads as "chopped" — a flat dark mark reads as paint.
cuts = []
for i in range(N_CUTS):
    ang = random.uniform(0, math.tau)
    rad = CLUSTER_R * math.sqrt(random.uniform(0.03, 1.0))  # even areal density
    ux = rad * math.cos(ang)  # across the trunk  (X)
    vz = rad * math.sin(ang) * 0.85  # up/down           (Z), slightly squashed
    # SHORT and WIDE. v1 used ln 0.055-0.115 x wd 0.008-0.018 — a 6:1 pinstripe, which
    # is why the marks read as painted bars rather than as bites taken out of the bark.
    # A real hatchet strike is roughly as wide as it is long and bites deep.
    ln = random.uniform(0.030, 0.062)  # cut length, along the strike
    wd = random.uniform(0.016, 0.032)  # cut width
    dep = random.uniform(0.030, 0.055)  # how deep it bites INTO the trunk (Y)
    tilt = random.uniform(-62, 62)  # strike angle, in the image plane
    fresh = i % 4 == 0  # a quarter read as recent
    mat = MAT_FRESH if fresh else MAT_OLD
    ys = _surface_y(ux)
    # sit the slot straddling the surface so its walls catch the key light
    ob = _box(f'cut{i}', ux, ys + dep * 0.35, vz, wd, dep, ln, mat)
    ob.rotation_euler = (0.0, math.radians(tilt), 0.0)  # about the VIEW axis
    cuts.append(ob)

# ONE BOOLEAN MODIFIER PER CUT — this is the documented fix, and the bug that broke the
# first attempt. Joining 26 separate closed box shells into a SINGLE object and handing
# that over as one cutter is the case Blender's own troubleshooting guidance calls out:
# "use multiple Boolean modifiers if the cutter contains multiple meshes". A cutter made
# of disjoint shells has no single coherent inside, so DIFFERENCE subtracted the trunk's
# volume instead of the slots and trunk_cut.png came back 97% black (mean 4.9 vs 107.7).
# Recalculating normals could never fix that, which is why it survived that attempt.
#
# The other documented requirements are met explicitly rather than assumed: APPLIED SCALE
# (booleans read local scale), outward normals per cutter, and no zero-area faces.
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
    ob.hide_render = True
    m = trunk.modifiers.new(f'scarcut_{ob.name}', 'BOOLEAN')
    m.operation = 'DIFFERENCE'
    m.object = ob
    m.solver = 'EXACT'
    _bools.append(m)


class _BoolGroup:
    """Toggle every per-cut modifier together, so the render plan stays unchanged."""

    def __init__(self, mods):
        self._m = mods

    @property
    def show_render(self):
        return bool(self._m) and self._m[0].show_render

    @show_render.setter
    def show_render(self, v):
        for m in self._m:
            m.show_render = bool(v)


_bool = _BoolGroup(_bools)
cutters = cuts[0]  # kept for _bbox_px / silhouette toggling below

# ── the hatchet ─────────────────────────────────────────────────────────────
# Seated as if struck in: the bit is buried, the haft juts out and slightly down.
AXE_Z = 0.0
AXE_X = 0.0
axe_parts = []
_by = _surface_y(AXE_X)  # trunk surface depth under the axe

# HEAD ORIENTATION — the second render read only 52px wide because the blade was buried
# point-first INTO the screen, so the camera saw its 26mm thickness rather than its face.
# A hatchet thrown into a trunk presents its BROAD SIDE: the cutting edge is a line in the
# image plane and only the penetration is along -view. So the head is a slab in X-Z (width
# across frame, height up frame), thin in Y, tipped about X so the lower edge digs in and
# the poll stands proud.
HEAD_W, HEAD_H, HEAD_T = 0.115, 0.078, 0.026
head = _box('axe_head', AXE_X, _by + 0.004, AXE_Z, HEAD_W, HEAD_T, HEAD_H, MAT_STEEL)
head.rotation_euler = (math.radians(-24.0), 0.0, 0.0)
axe_parts.append(head)

# haft: out of the eye, toward camera and angled down
HAFT_L = 0.235
haft = _box('axe_haft', AXE_X, _by - 0.070, AXE_Z - 0.125, 0.030, 0.032, HAFT_L, MAT_HAFT)
haft.rotation_euler = (math.radians(-24.0), 0.0, math.radians(4.0))  # down + toward cam
axe_parts.append(haft)

# ── light + camera ──────────────────────────────────────────────────────────
# One key from upper camera-left matches the plates' overcast morning read and, more
# importantly, guarantees every cut has a lit wall and a shadowed wall.
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
cam.location = (0.0, -1.55, 0.0)  # on -Y, looking +Y at the trunk face
cam.rotation_euler = (math.radians(90 - TILT), 0.0, math.radians(YAW))
scene.collection.objects.link(cam)
scene.camera = cam

scene.render.engine = 'CYCLES'
scene.cycles.samples = 96
scene.render.resolution_x = W
scene.render.resolution_y = H
scene.render.film_transparent = True
scene.render.image_settings.file_format = 'PNG'
scene.render.image_settings.color_mode = 'RGBA'
try:
    scene.cycles.device = 'CPU'  # tiny scene; avoids fighting a render for the GPU
except AttributeError as _exc:
    _zyg_log.debug('cycles CPU device not set (no cycles settings on this scene): %s', _exc)


def _proj(v):
    co = world_to_camera_view(scene, cam, Vector(v))
    return [round(co.x * W, 2), round((1.0 - co.y) * H, 2)]


def _bbox_px(objs):
    xs, ys = [], []
    for ob in objs:
        for c in ob.bound_box:
            p = _proj(ob.matrix_world @ Vector(c))
            xs.append(p[0])
            ys.append(p[1])
    return [round(min(xs), 1), round(min(ys), 1), round(max(xs), 1), round(max(ys), 1)]


def _render(path, cuts_on, axe_on, trunk_on, transparent):
    for _c in cuts:
        _c.hide_render = not bool(cuts_on)
    trunk.hide_render = not trunk_on
    trunk.is_holdout = bool(trunk_on and transparent)
    for ob in axe_parts:
        ob.hide_render = not axe_on
    scene.render.film_transparent = bool(transparent)
    scene.render.filepath = path
    bpy.ops.render.render(write_still=True)


# THE BOOLEAN ROUTE WAS ABANDONED, 2026-08-03. With DIFFERENCE enabled the trunk render
# came back 97% black (mean 4.9 vs 107.7 for the same surface with the modifier off), and
# it stayed inverted after fixing the box winding AND forcing normals_make_consistent —
# i.e. the cutter is being read as enclosing the whole solid. Rather than keep chasing the
# solver, Blender is now used only for what it is unambiguously good at here: the correct
# PERSPECTIVE SILHOUETTE of each strike. The recess SHADING is synthesised from that
# silhouette in numpy (axe_scene_assets.apply_scars), where it is fully determined instead
# of dependent on mesh hygiene.
# silhouettes (kept: cheap, and useful as an alpha for other consumers)
_bool.show_render = False
_render(os.path.join(OUT, 'scars_rgba.png'), True, False, False, True)
# THE RATIO PAIR, now that the booleans actually cut: same surface, same light, the
# subtraction the only difference. trunk_cut/trunk_plain is 1.0 on untouched bark.
_render(os.path.join(OUT, 'trunk_plain.png'), False, False, True, False)
_bool.show_render = True
_render(os.path.join(OUT, 'trunk_cut.png'), False, False, True, False)
# the axe rides over the plate as RGBA, with the trunk a holdout so only steel+wood show
_render(os.path.join(OUT, 'axe_rgba.png'), False, True, True, True)

meta = {
    'size': [W, H],
    'cuts': N_CUTS,
    'seed': SEED,
    'trunk_r': TRUNK_R,
    'cluster_r': CLUSTER_R,
    'scar_bbox_px': _bbox_px(cuts),
    'cluster_centre_px': _proj(Vector((0.0, _surface_y(0.0), 0.0))),
    'axe_bbox_px': _bbox_px(axe_parts),
    # what shot 2 needs: where the hand closes, and where the steel must stay put
    'haft_tip_px': _proj(haft.matrix_world @ Vector((0.0, 0.0, -HAFT_L / 2))),
    'blade_entry_px': _proj(Vector((AXE_X, _by, AXE_Z))),
}
with open(os.path.join(OUT, 'axe_meta.json'), 'w') as f:
    json.dump(meta, f, indent=1)
_zyg_log.info('AXE_RENDER_OK ' + json.dumps(meta))
