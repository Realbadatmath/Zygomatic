# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""blender_power.constants -- the original module's import block and constants.

Verbatim move of blender_power.py lines 27-253.  The imports are the package's
shared import block: unused here, re-exported to every section module and to
__init__ so that old attribute accesses (blender_power.os, .np, ...) resolve.
"""

# ruff: noqa: F401  (the re-exported shared import block, see the docstring)

from __future__ import annotations

import base64
import hashlib
import json
import math
import os
import re
import subprocess
import time

from zyg_workflows.arch_assistant import (
    Drawing,
    MAX_OBJECTS,
    _num,
    parse_cell,
    cell_centre,
    cell_of,  # noqa: F401
    surface_top,
    deck_tops,
    ground_height,
)  # (MATERIALS: schema enums)
from zyg_workflows import arch_blend_store as BSTORE
import logging as _zyg_logging

# split-only change: __package__ here IS the original module's __name__
# ('zyg_workflows.arch_assistant_ext.blender_power'), so the logger keeps its name.
_zyg_log = _zyg_logging.getLogger(__package__)


# split-only change: one extra dirname() -- this module sits one directory deeper
# than the original blender_power.py, so HERE still resolves to .../zyg_workflows
HERE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BLEND_DIR = os.path.join(HERE, 'data', 'architecture', 'blender')
RENDER_DIR = os.path.join(HERE, 'data', 'architecture', 'renders')
BUILDER = os.path.join(HERE, 'arch_blender_build', '__main__.py')
BLENDER = os.environ.get('BLENDER_BIN', '/usr/local/bin/blender')

BUILD_TIMEOUT = 600
PASS_TIMEOUT = 600


def _env_int(name, dflt, lo, hi):
    try:
        v = int(os.environ.get(name) or dflt)
    except (TypeError, ValueError):
        return int(dflt)
    return max(lo, min(hi, v))


# 2026-09-16 (the hero render): a 4K Cycles frame is minutes, not the seconds a
# 720p EEVEE pass takes, so it gets its own ceiling and its own sample count.
HERO_TIMEOUT = _env_int('ZYG_ARCH_HERO_TIMEOUT', 900, 30, 7200)
BP_CY_SAMPLES = _env_int('ZYG_ARCH_HERO_SAMPLES', 128, 1, 4096)
# 2026-09-16: the operator asked for "a photorealistic 4K render of the building
# as preview picture", and the FIRST picture has to show the WHOLE building. The
# approach camera does not: it stands 30 m out on the door axis at eye height, so
# on the 20-storey tower it frames two storeys of the entrance. 'hero' is the
# three-quarter shot that shows the thing itself, and it comes first.
# 2026-09-16 (the hero set): a hand-over is four frames, not three — the whole
# building, the entrance, the LOBBY (the one room a visitor stands in, lit by
# its own lamps) and the aerial. The lobby is present()'s own lobby camera (4 m
# inside the door, with its retreat rule) at 4K in Cycles.
HERO_VIEWS = ('hero', 'approach', 'lobby', 'aerial')
HERO_W, HERO_H = 3840, 2160
HERO_FOCAL_MM = 24.0  # wide, but not a fisheye: the whole tower at one standpoint
HERO_OFF_AXIS_DEG = 35.0  # off the door axis — two facades, not a flat elevation
HERO_DIST_K = 1.35  # x max(height, plan diagonal): the MINIMUM standoff...
HERO_DIST_MAX_K = 6.0  # ...grown up to this when the envelope will not fit
HERO_HEADROOM = 0.08  # air above the parapet, as a fraction of the frame height
HERO_SUN_MIN = 0.15  # |sun . side normal| below this = the sun cannot choose a side
HERO_JPEG_W = 1600  # the panel copy: a file, but a light one
HERO_JPEG_Q = 85
# the hero pass stands the building on a plane when the drawing has no ground of
# its own — without it a 4K Cycles frame shows a tower floating over the void.
HERO_GROUND_M = 400.0
HERO_GROUND_MAT = 'acg_Asphalt020L'
# EXPOSURE_EV (-1.2) was measured against the FLAT BP_SKY card. A Nishita sky is
# a physical one and puts the same scene about two stops higher: at -1.2 the
# asphalt came back white and the facade sat in Filmic's desaturating shoulder.
# Measured over a -1.2..-7.0 sweep on the live tower's approach (one render,
# re-tonemapped; no clipping at any stop): -3.0 keeps the ground grey and the
# foliage green, -4.0 already crushes the trees. Hero pass only — EEVEE is
# untouched and keeps EXPOSURE_EV.
HERO_EV = -3.0
# ...but that is the EXTERIOR stop. Inside the lobby the same sky arrives only
# through the glass front and the room is otherwise lit by its own 12 W
# downlights: at -3.0 the interior renders as a dark box with a bright doorway.
# A view that stands INSIDE gets its own exposure; two stops back up is the
# difference between "a lit room with furniture in it" and a silhouette.
HERO_EV_VIEW = {'lobby': -1.0}

KINDS: dict = {}
OPENINGS: list = []

# 2026-09-10: 'section' cuts the model open (an ortho camera standing ON the cut
# plane, near clip 0.01, so everything behind the plane is simply not there) and
# 'back'/'left' are the two elevations that were missing — front/right alone
# cannot show a north entrance or a west facade.
VIEWS = ('iso', 'top', 'front', 'back', 'right', 'left', 'section', 'eye', 'aerial')
ORTHO_VIEWS = ('iso', 'top', 'front', 'back', 'right', 'left', 'section')
ENGINES = ('workbench', 'eevee', 'cycles')
# what the MODEL may ask for: cycles is the hero pass's own engine (minutes per
# frame at 4K), reached from hero_render(), never from a tool argument.
TOOL_ENGINES = ('workbench', 'eevee')
SECTION_AXES = ('x', 'z')
# present(): the five views, in the order the reply lists them
PRESENT_VIEWS = ('approach', 'section', 'elevation', 'aerial', 'lobby')
APPROACH_M = 30.0  # how far out on the door axis the approach camera stands
APPROACH_FOCAL_MM = 28.0
LOBBY_INSIDE_M = 1.2  # how far inside the door the lobby camera stands (was 4.0: it then
# stood in the seating group and looked back at the door)
LOBBY_LOOK_M = 9.0  # the aim point is this far INTO the room along the door axis
LOBBY_AIM_H_M = 1.1  # ... at seat height, so the furniture fills the lower half
LOBBY_FOCAL_MM = 24.0  # an interior wants the wide lens
LOBBY_EYE_M = 1.6
# 2026-09-11 (live job 94f5813b): 4 m inside the door of a real tower put the
# lobby camera against the Lobby room's own partition — a blank grey frame that
# the old _bp_framed still counted 14 records into. The camera now probes what
# is in front of it and steps BACK toward the door until it can see.
LOBBY_CLEAR_M = 1.5  # nearer than this ahead = blocked
LOBBY_STEP_M = 0.5  # one step back toward the door
LOBBY_MIN_INSIDE_M = 0.5  # never closer than this to the door plane
BLANK_VIEW_N = 3  # fewer visible records than this = a blank view

# 2026-09-11: present() used to answer in NUMBERS only — the model never saw a
# picture, so a concrete canopy, black marble floors and lamp posts taller than
# the canopy all passed a green presentation. These three views go back to the
# model as real pictures (downscaled JPEGs, small enough to be cheap) with a
# checklist it must answer before done().
MODEL_VIEWS = ('approach', 'aerial', 'lobby')
THUMB_W = 800  # widest a picture handed to the model gets
THUMB_Q = 70  # JPEG quality (dropped further if one is too heavy)
THUMB_MAX_BYTES = 200 * 1024
PRESENT_CHECKLIST = (
    'LOOK at the three pictures and answer in your next message, one line each, before done: '
    '1 canopy: transparent glass yes/no; 2 lamp posts shorter than the canopy yes/no; '
    '3 lobby: a room with furniture, not a wall yes/no; '
    '4 floors/finishes read as the requested materials yes/no; '
    '5 nothing hangs outside the facade yes/no. A no is a fix, not a note.'
)

# the world background colour, shared by EEVEE (the Background node) and Workbench
# (the viewport background). Kept here so the test can name the same three numbers.
SKY_RGB = (0.62, 0.74, 0.85)
SUN_ENERGY = 3.0
SUN_ANGLE_DEG = 2.0
SUN_ELEV_DEG = 35.0  # default: 35 deg above the horizon...
SUN_AZIM_DEG = 225.0  # ...in the south-west (clockwise from north)
EYE_HEIGHT_M = 1.7
EYE_FOV_DEG = 50.0
# the cell camera (2026-09-08): a real lens on a 36 mm sensor, aimed LEVEL at the
# target's plan position with the target lifted into frame by shift_y — the
# two-point perspective an architectural photographer keeps verticals plumb with.
FOCAL_DEFAULT_MM = 35.0
FOCAL_RANGE_MM = (14.0, 135.0)
SENSOR_MM = 36.0
SHIFT_MAX = 0.6
LOOK_HEIGHT_M = 1.5
# a 35 deg sun (3 W/m2) plus a full sky hemisphere is about 4x the irradiance the
# film curve is scaled for, and both AgX and Filmic answer over-exposure by
# desaturating: without this stop-down grass, sand and rock all come back as the
# same pale pastel. -1.2 measured best over a -0.4..-2.4 sweep (see the test's
# colour checks): brighter than -1.6, and the widest per-region channel spread.
EXPOSURE_EV = -1.2
FORMATS = {'obj': '.obj', 'fbx': '.fbx', 'stl': '.stl', 'glb': '.glb', 'usd': '.usdc', 'ply': '.ply'}

PROMPT = (
    'present() is the hand-over: ONE build, five renders — approach (28 mm on the entrance axis 30 m out), section '
    '(cut through the door axis, where a stair through slabs or a shaft without a floor opening shows), elevation, '
    'aerial and lobby (4 m inside the door looking out, stepped back if a wall is in its face) — and it answers in '
    'numbers only: records VISIBLE (by ray cast) of the records in frustum, the tallest visible one, door in frame '
    'yes/no, slabs crossed without an opening, plus every design-check finding. done '
    'requires present() after the LAST drawing change; do not judge your own picture in adjectives.\n'
    'portfolio() is THE HAND-OVER FOLDER, and done() is refused without one of the current drawing '
    '(the operator\'s standing rule, 2026-09-23: "after every drawing … portfolio folder with 40+ images"). '
    'It renders about fifty views in ONE Blender pass into a folder they open: twelve standpoints right round '
    'it and four from above, the six orthographic views, a cut on the centreline and six across it, a plan cut '
    'over EVERY level and two views from inside every level with a 1.75 m figure, two raking shots where a '
    'curve shows whether it runs fair, and close lenses on the ends, the entrance and the decks — each with '
    'the measurement its camera made, and a SURFACE AUDIT beside them: meshes with no material, materials '
    'still on the untouched default, big flat-shaded curves, open edges. LOOK at the contact sheets it hands '
    'back and FIX what they show — a door that is not a hole, a level nothing stands on, a default material '
    'is a defect, not a note. '
    'blender_render(view="section", axis="x"|"z", at=cell|metres) cuts the building open on one plane and drops '
    'everything behind it; the four elevations are front/back/right/left; an INTERIOR shot is from_cell/to_cell with '
    'eye_height.\n'
    'Blender: blender_render(view, engine) gives you a PICTURE of the drawing rebuilt in Blender — use it to check a '
    'result you cannot judge from the parametric numbers (engine: workbench or eevee). Views: iso/top/front/back/'
    'right/left are orthographic drawings; "eye" stands on the ground at the south edge at 1.7 m and looks north (the walk the '
    'operator takes — use it to judge a landscape, a street or a facade the way a person sees it); "aerial" looks down '
    'from 45 degrees in the south-west and frames the whole lot. from_cell/to_cell stand the camera on a cell and '
    'look at another — the way to check an entrance from its approach or a roof from its deck (eye_height above the '
    'surface under from_cell, focal_mm 14..135, look_height above the surface under to_cell; verticals stay plumb). '
    'The picture has a real sky and a 35 degree south-west '
    'sun, so slopes shade and a v3 ground shows its grass/rock/sand/snow vertex colours. '
    'blender_measure() returns a table of per-object bounding boxes, mesh volumes and face counts — use it to verify '
    'sizes and to spot objects that did not build. blender_export(format) writes obj/fbx/stl/glb/usd/ply to disk and '
    'returns the path, for the user to take away. blender_run(script, render, view) runs YOUR OWN bpy Python inside '
    'that Blender: use it only for things the studio kinds cannot express — booleans, bevels, arrays, subdivision, '
    'custom meshes, material tweaks — and set render=true to get a picture back of what your script did. The script '
    'runs as the operator on this machine, so keep it to the scene; edits are SAVED into the .blend and persist to '
    'the next tool call in this request, but they do NOT flow back into the parametric drawing — the studio document '
    'is unchanged, so never use blender_run to "draw" something the user wants in the studio (use the drawing tools). '
    'Every studio record becomes one Blender object named "<kind> <id>" (e.g. "wall o7") carrying the custom property '
    "obj['studio_id'].\n"
    'bpy cheat-sheet:\n'
    '  import bpy, bmesh, math, mathutils\n'
    "  ob = bpy.data.objects['wall o7']          # by name; bpy.data.objects.keys() lists them\n"
    "  [o for o in bpy.data.objects if o.get('studio_id') == 'o7']   # by studio id\n"
    '  ob.location = (x, y, z)                   # blender frame: x = studio x, y = -studio z, z = studio y (up)\n'
    '  ob.rotation_euler = (0, 0, math.radians(30)); ob.scale = (1, 1, 2)\n'
    "  m = ob.modifiers.new('bev', 'BEVEL'); m.width = 0.05; m.segments = 3\n"
    "  m = ob.modifiers.new('arr', 'ARRAY'); m.count = 6; m.relative_offset_displace = (1.2, 0, 0)\n"
    "  m = ob.modifiers.new('sub', 'SUBSURF'); m.levels = 2\n"
    "  m = ob.modifiers.new('bool', 'BOOLEAN'); m.operation = 'DIFFERENCE'; m.object = cutter\n"
    "  bpy.ops.object.select_all(action='DESELECT'); ob.select_set(True)\n"
    "  bpy.context.view_layer.objects.active = ob; bpy.ops.object.modifier_apply(modifier='bev')\n"
    '  bpy.ops.mesh.primitive_cube_add(size=2, location=(0, 0, 1))   # new object = context.active_object\n'
    '  bm = bmesh.new(); bm.from_mesh(ob.data)   # bmesh: bm.verts/.edges/.faces, bm.calc_volume()\n'
    '  bmesh.ops.inset_region(bm, faces=bm.faces[:], thickness=0.1)\n'
    '  bm.to_mesh(ob.data); bm.free(); ob.data.update()\n'
    "  bpy.ops.object.mode_set(mode='EDIT')      # only with an active object; 'OBJECT' to come back\n"
    "  mat = bpy.data.materials.get('mat_glass') or bpy.data.materials.new('mat_glass')\n"
    '  ob.data.materials.clear(); ob.data.materials.append(mat)\n'
    "  mat.use_nodes = True; mat.node_tree.nodes['Principled BSDF'].inputs['Base Color'].default_value = (1,0,0,1)\n"
    '  bpy.data.objects.remove(ob, do_unlink=True)\n'
    '  print(...) — everything you print comes back to you as the tool result.'
)
