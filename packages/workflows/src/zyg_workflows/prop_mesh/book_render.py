# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""book_render.py — Blender script: parametric open book -> VACE control plate (2026-08-01).

RUN (never imported by the pipeline; it needs bpy):
    blender -b -P prop_mesh/book_render.py -- --out /tmp/book --w 832 --h 480 \
            [--open 0.34] [--thick 0.11] [--tilt 12]

WHY THIS EXISTS — MEASURED, NOT ASSUMED.
The ledger and the pipe sit 95.4% and 100% inside the VACE *generate* mask, and
wan_vace_service.py:1539-1541 fills the control frame under that mask with a CONSTANT:

    grey = np.full_like(s_arr, 127.0)
    ctrl = s_arr * (1.0 - m_arr) + grey * m_arr

One still, repeated for all 341 frames, flat grey where the props are. So VACE gets
ZERO geometric guidance for them and re-invents both objects in each of six context
windows from the text plus a small reference image. Text pins semantics, not geometry:
"an open bound book" fixes neither thickness nor page count, and nothing at all
guarantees the pipe still exists in window four. Measured on scene20_v15's delivered
clip, edge-correlation against frame 0 was 0.164 for the book and 0.201 for the pipe,
and by t=13 the pipe had degenerated into a red outline with no hand.

THE BOOK IS THE RIGHT FIRST TARGET, for three reasons that are properties of the shot:
  1. It is WORLD-STATIC. It rests on the table and never moves, so ONE render serves
     all 341 control frames — no animation, no tracking, no per-frame Blender cost.
  2. The camera is locked off ('static shot, fixed camera, locked-off tripod shot'),
     so a single viewpoint is correct for the whole clip.
  3. It is barely occluded — only the writing hand crosses it. The pipe, by contrast,
     lives in a mouth and a fist and needs occlusion handling first.

ALIGNMENT IS BY HOMOGRAPHY, NOT BY EYE.
Camera intrinsics for the original shot do not exist — the plate came out of a
generator. So this script does NOT try to reconstruct that camera. It renders the book
from a convenient viewpoint and reports the exact projected 2D coordinates of the RIGHT
PAGE's four corners (via world_to_camera_view, so they are exact, not traced from the
image). prop_control.py then solves the homography that maps those four points onto the
shot's own `page_quad` from shot_metadata.json and warps the whole plate through it.
That guarantees the rendered page lands exactly where the real page already is.

OUTPUTS in --out:
    book_rgb.png    the shaded plate (RGBA; alpha = where the book is)
    book_meta.json  {'page_quad_render': [[x,y] x4 in PIXELS, TL,TR,BR,BL], 'size': [w,h]}
"""

import json
import math
import os
import sys
import tempfile

import bpy
from bpy_extras.object_utils import world_to_camera_view
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
OUT = _opt(ARGS, '--out', os.path.join(tempfile.gettempdir(), 'book'), str)
RW = int(_opt(ARGS, '--w', 832))
RH = int(_opt(ARGS, '--h', 480))
OPEN_A = _opt(ARGS, '--open', 0.34)  # how far the pages lift from flat (radians)
THICK = _opt(ARGS, '--thick', 0.11)  # half text-block thickness
TILT = math.radians(_opt(ARGS, '--tilt', 12.0))  # camera elevation over the table

os.makedirs(OUT, exist_ok=True)

# ── clean scene ──────────────────────────────────────────────────────────────
bpy.ops.wm.read_factory_settings(use_empty=True)
scene = bpy.context.scene


def _mat(name, rgb, rough=0.85):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    b = m.node_tree.nodes.get('Principled BSDF')
    if b:
        b.inputs['Base Color'].default_value = (*rgb, 1.0)
        if 'Roughness' in b.inputs:
            b.inputs['Roughness'].default_value = rough
    return m


PAPER = _mat('paper', (0.92, 0.88, 0.78))
COVER = _mat('cover', (0.22, 0.13, 0.09))
BLOCK = _mat('block', (0.86, 0.82, 0.70))

# MUST match what prop_camera solved for. The camera pose is only valid for the page
# geometry it was fitted against, so rendering with a different PAGE_L silently offsets
# the whole book (measured: 22-38px of vertical drift when the solver said 0.30 and the
# render still used the 0.66 default).
PAGE_W = _opt(ARGS, '--pagew', 0.95)
PAGE_L = _opt(ARGS, '--pagel', 0.66)  # half-length along the spine
Z0 = THICK  # spine valley height above the table
RISE = PAGE_W * math.sin(OPEN_A)  # how far the OUTER edge lifts above the valley

# Built from EXPLICIT vertices rather than primitive+rotate. The first attempt offset each
# page by half its width and then rotated it about the object origin, which left the pages
# detached from their text blocks and a visible gap either side of the spine — it rendered
# as two lidded boxes, not a book. Stating the corners directly is both shorter and exact,
# and it makes the four page corners trivially readable for the homography below.


def _quad_solid(name, top_quad, mat, drop_to=0.0):
    """A top face plus vertical side walls down to z=drop_to (a page + its text block)."""
    mesh = bpy.data.meshes.new(name)
    obj = bpy.data.objects.new(name, mesh)
    scene.collection.objects.link(obj)
    top = list(top_quad)
    bot = [(x, y, drop_to) for (x, y, _z) in top]
    verts = top + bot
    faces = [(0, 1, 2, 3)]  # top
    for i in range(4):
        j = (i + 1) % 4
        faces.append((i, j, 4 + j, 4 + i))  # side wall
    faces.append((7, 6, 5, 4))  # bottom
    mesh.from_pydata(verts, [], faces)
    mesh.update()
    obj.data.materials.append(mat)
    return obj


def _page_top(sign):
    """Four corners of one page's top surface, ordered far-inner, far-outer,
    near-outer, near-inner so the winding is consistent for both sides."""
    return [
        (0.0, +PAGE_L, Z0),
        (sign * PAGE_W, +PAGE_L, Z0 + RISE),
        (sign * PAGE_W, -PAGE_L, Z0 + RISE),
        (0.0, -PAGE_L, Z0),
    ]


right_page = _quad_solid('page_R', _page_top(+1), PAPER, drop_to=0.0)
left_page = _quad_solid('page_L', _page_top(-1), PAPER, drop_to=0.0)

# the spine valley: a narrow dark strip bridging the two page roots
spine = _quad_solid(
    'spine', [(-0.07, +PAGE_L, Z0), (0.07, +PAGE_L, Z0), (0.07, -PAGE_L, Z0), (-0.07, -PAGE_L, Z0)], COVER, drop_to=0.0
)

# ── camera ───────────────────────────────────────────────────────────────────
# --cam FILE takes a pose recovered by prop_camera.solve_camera_auto (planar PnP against
# the shot's own page_quad). That is the ONLY way the rest of the book lands in correct
# perspective: fitting a homography to the page alone aligned the page and sheared
# everything else into a wedge across half the frame. Without --cam we fall back to the
# hand-set tilt, which is only useful for eyeballing the mesh itself.
CAM_FILE = _opt(ARGS, '--cam', '', str)
cam_data = bpy.data.cameras.new('cam')
cam = bpy.data.objects.new('cam', cam_data)
scene.collection.objects.link(cam)
scene.camera = cam
if CAM_FILE and os.path.isfile(CAM_FILE):
    cj = json.load(open(CAM_FILE))
    cam.location = tuple(float(v) for v in cj['location'])
    cam.rotation_mode = 'XYZ'
    cam.rotation_euler = tuple(float(v) for v in cj['rotation_euler_xyz'])
    cam_data.lens = float(cj.get('lens_mm', 50.0))
    cam_data.sensor_width = float(cj.get('sensor_mm', 36.0))
    _zyg_log.info(f'[book_render] camera from {CAM_FILE}: lens {cam_data.lens:.1f}mm reproj {cj.get("reproj_px")}')
else:
    cam_data.lens = 50
    dist = 4.2
    cam.location = (0.0, -dist * math.cos(TILT), dist * math.sin(TILT) + THICK)
    cam.rotation_euler = (math.pi / 2.0 - TILT, 0.0, 0.0)
    _zyg_log.info('[book_render] camera: hand-set tilt fallback (no --cam)')

# ── light: flat and even. This is a STRUCTURE plate, not a beauty render ─────
sun = bpy.data.lights.new('sun', type='SUN')
sun.energy = 3.2
so = bpy.data.objects.new('sun', sun)
so.rotation_euler = (math.radians(35), math.radians(15), 0.0)
scene.collection.objects.link(so)
world = bpy.data.worlds.new('w')
world.use_nodes = True
world.node_tree.nodes['Background'].inputs[0].default_value = (0.35, 0.35, 0.35, 1)
world.node_tree.nodes['Background'].inputs[1].default_value = 1.1
scene.world = world

# ── render settings ──────────────────────────────────────────────────────────
# Engine name moved between Blender versions (EEVEE -> BLENDER_EEVEE_NEXT in 4.2+), and
# introspecting RenderEngine.__subclasses__() is not a reliable way to ask — in 4.3 that
# list contains addon classes with no .identifier and it raises. Just try each in order.
for _eng in ('BLENDER_EEVEE_NEXT', 'BLENDER_EEVEE', 'BLENDER_WORKBENCH'):
    try:
        scene.render.engine = _eng
        break
    except (TypeError, ValueError) as _exc:
        _zyg_log.debug('render engine %r unavailable, trying next: %s', _eng, _exc)
        continue
_zyg_log.info(' '.join(str(a) for a in ('[book_render] engine =', scene.render.engine)))
scene.render.resolution_x = RW
scene.render.resolution_y = RH
scene.render.resolution_percentage = 100
scene.render.film_transparent = True  # alpha = where the book is
scene.render.image_settings.file_format = 'PNG'
scene.render.image_settings.color_mode = 'RGBA'
scene.render.filepath = os.path.join(OUT, 'book_rgb')

bpy.context.view_layer.update()

# ── EXACT projected corners of the RIGHT PAGE, in pixels ─────────────────────
# world_to_camera_view returns normalised (0..1, origin bottom-left); flip Y for image
# space. These four points are the homography source in prop_control.py — reading them
# from the mesh is what makes the alignment exact instead of traced by hand.
mw = right_page.matrix_world
# _quad_solid writes the TOP quad as vertices 0-3 and the dropped floor as 4-7, so the
# page surface is exactly verts[:4]. (bound_box is not usable here: it would give the
# eight corners of the axis-aligned box around a TILTED page, which are not on the page.)
pts_world = [mw @ right_page.data.vertices[i].co for i in range(4)]
if len(right_page.data.vertices) != 8:
    raise RuntimeError(f'page solid should have 8 verts, has {len(right_page.data.vertices)}')


def _proj(v):
    co = world_to_camera_view(scene, cam, v)
    return [co.x * RW, (1.0 - co.y) * RH]


proj = [_proj(v) for v in pts_world]
# order TL, TR, BR, BL by angle about the centroid
cx = sum(p[0] for p in proj) / len(proj)
cy = sum(p[1] for p in proj) / len(proj)
proj.sort(key=lambda p: math.atan2(p[1] - cy, p[0] - cx))
# atan2 order starts at -pi (left, slightly up) and runs CCW in image space; rotate so
# the first point is the top-left-most
start = min(range(len(proj)), key=lambda i: proj[i][0] + proj[i][1])
proj = proj[start:] + proj[:start]

bpy.ops.render.render(write_still=True)

meta = {
    'page_quad_render': proj,
    'size': [RW, RH],
    'params': {'open': OPEN_A, 'thick': THICK, 'tilt_deg': math.degrees(TILT), 'page_w': PAGE_W, 'page_l': PAGE_L},
    'engine': scene.render.engine,
}
with open(os.path.join(OUT, 'book_meta.json'), 'w') as f:
    json.dump(meta, f, indent=1)
_zyg_log.info(' '.join(str(a) for a in ('[book_render] wrote', os.path.join(OUT, 'book_rgb.png'))))
_zyg_log.info(' '.join(str(a) for a in ('[book_render] page_quad_render', json.dumps(proj))))
