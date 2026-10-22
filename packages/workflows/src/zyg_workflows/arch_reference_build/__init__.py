# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""arch_reference_build — build ONE asset inside headless Blender from a
reference model's pictures and plans (2026-09-23).

Run by ``arch_assistant_ext/reference_model.build_reference_asset``:

    blender -b --factory-startup --python arch_reference_build.py -- \
        --ref <model.json> --script <user.py> --out <base> \
        [--views iso,plan_right] [--check] [--engine workbench|eevee]
        [--width 1280] [--height 720] [--inspect [N|names]] [--inspect-engine E]

It prints one JSON line last: {ok, blend, glb, images, inspect, objects, tris,
dims, script_error, log}.

``--inspect`` adds THE INSPECTION SET: ten pictures of the finished asset —
four standpoints around it, one from above, two cut planes and three from
INSIDE it, each one carrying the measurement its camera made (the surface it
stands on, the headroom over it, the clear distance ahead) and a 1.75 m figure
for scale in the interiors. One iso view cannot show a deck floating over the
sheer or a mast stepped in mid-air; these can.

WHAT THIS GIVES THE SCRIPT THAT PLAIN ``blender_run`` DOES NOT

``blender_run`` opens the drawing's .blend and lets a script loose in it. That
is the wrong room for an asset: the asset is a NEW thing, at its own origin, at
its own real size, and it must not inherit the building. So this starts from a
factory-empty scene and hands the script the reference material as geometry it
can model against:

    REF                     the reference record (absolute image paths)
    ref_images(role=None)   the pictures, filtered by role
    ref_path(role_or_id)    one picture's file
    ref_plane(role, width_m=None, at=0.0)   an image plane laid into that view
    ref_empty(role, ...)    the same as a viewport-only image empty
    ref_clear()             remove every reference object
    mirror(obj, axis='y')   a Mirror modifier — a hull is symmetric, so half
                            the modelling is free and the halves cannot drift
    ORIENT                  {role: (euler, normal axis)} if you want it by hand

THE FRAME, once, so nothing has to guess: Blender Z-up, +X east, +Y north,
+Z up — the same frame arch_blender_build.py maps the studio into ((x, -z, y)).
A front elevation is therefore seen from -Y, and its image u runs along +X and
its v along +Z. Every entry in arch_reference.ROLES was derived that way, not
guessed: right = cross(forward, up), u -> right, v -> up.

SCALE is the reference model's job, not the script's guess. ref_plane sizes a
plan so its image spans the measured length (or beam, for a front/back view).
When nothing is measured it falls back to 10 m and SAYS SO in the log, because
a model built at an invented size looks exactly like one built at a real size.

Reference objects are tagged ``ob['zyg_ref'] = 1`` and are never exported, never
saved into the asset .blend, and never counted in its dimensions — they are
scaffolding, and scaffolding that ships is a defect.

Licence: runs inside Blender (GPL) as a subprocess script; imports nothing but
bpy and the stdlib.
"""

# Every name the single file exported, re-exported from the module that now
# holds it, in the original section order. Two are deliberately absent:
#   REF   — rebound at runtime by main(); see api._LiveRef. Re-exporting it
#           by value would freeze the empty dict.
#   main  — the function. ``arch_reference_build.main`` must stay the MODULE,
#           or ``import arch_reference_build.main`` (what entry.py and the
#           smoke test do) resolves to the function. Call it as
#           ``arch_reference_build.main.main()``.

from .base import (
    contextlib,
    io,
    json,
    math,
    os,
    sys,
    traceback,
    bpy,
    bmesh,
    mathutils,
    _zyg_logging,
    _zyg_log,
    LOG,
    log,
    argv,
    arg,
    flag,
    ORIENT,
    ACROSS,
    _REF_OBJS,
    _num,
)

from .api import (
    ref_images,
    ref_path,
    ref_width,
    _tag,
    _img_for,
    ref_plane,
    ref_empty,
    ref_clear,
    mirror,
    asset_objects,
    asset_meshes,
)

from .scene import (
    _empty_scene,
    _bounds,
    _tris,
    DIRS,
    ROLE_DIR,
    _aim,
    _setup,
    _ortho_span,
    _projected,
    _make_cam,
    _shoot,
    _render,
    _overlay,
    _mix,
    _engines,
    _sun,
    _world,
    _photo_look,
    _export_glb,
)

from .inspection import (
    INSPECT_ALL,
    INSPECT_N,
    PORTRAIT_VIEWS,
    INSPECT_FOCAL,
    INSPECT_FOCAL_IN,
    INSPECT_SENSOR,
    EYE_M,
    FIG_H,
    HEAD_M,
    HOLD_M,
    CLEAR_M,
    _cast,
    _floor_like,
    _floors,
    _standpoints,
    _clear_ahead,
    _sphere,
    _fit_dist,
    _CLOUD,
    _cloud,
    _fit_bbox,
    _cam_persp,
    _cam_ortho,
    _figure,
    cam_and,
    _frame,
    _body_bounds,
    _inspect_shots,
    _inspect,
    _shoot_set,
)

from .portfolio import (
    PORTFOLIO_N,
    ORBIT_N,
    HIGH_N,
    STATIONS,
    DECK_LEVELS,
    MERGE_M,
    DETAIL_FOCAL,
    RAKE_FOCAL,
    PORTRAIT_COS,
    _cloud_extreme,
    _levels,
    _inside_shot,
    _portfolio_shots,
    _trim,
    _portfolio,
)

from .audit import (
    SHARP_RAD,
    CREASE_RAD,
    FLAT_FACES,
    DEFAULT_GREY,
    _mat_row,
    _audit,
)

from . import main

# the re-export surface, in the section order above
__all__ = [
    'contextlib',
    'io',
    'json',
    'math',
    'os',
    'sys',
    'traceback',
    'bpy',
    'bmesh',
    'mathutils',
    '_zyg_logging',
    '_zyg_log',
    'LOG',
    'log',
    'argv',
    'arg',
    'flag',
    'ORIENT',
    'ACROSS',
    '_REF_OBJS',
    '_num',
    'ref_images',
    'ref_path',
    'ref_width',
    '_tag',
    '_img_for',
    'ref_plane',
    'ref_empty',
    'ref_clear',
    'mirror',
    'asset_objects',
    'asset_meshes',
    '_empty_scene',
    '_bounds',
    '_tris',
    'DIRS',
    'ROLE_DIR',
    '_aim',
    '_setup',
    '_ortho_span',
    '_projected',
    '_make_cam',
    '_shoot',
    '_render',
    '_overlay',
    '_mix',
    '_engines',
    '_sun',
    '_world',
    '_photo_look',
    '_export_glb',
    'INSPECT_ALL',
    'INSPECT_N',
    'PORTRAIT_VIEWS',
    'INSPECT_FOCAL',
    'INSPECT_FOCAL_IN',
    'INSPECT_SENSOR',
    'EYE_M',
    'FIG_H',
    'HEAD_M',
    'HOLD_M',
    'CLEAR_M',
    '_cast',
    '_floor_like',
    '_floors',
    '_standpoints',
    '_clear_ahead',
    '_sphere',
    '_fit_dist',
    '_CLOUD',
    '_cloud',
    '_fit_bbox',
    '_cam_persp',
    '_cam_ortho',
    '_figure',
    'cam_and',
    '_frame',
    '_body_bounds',
    '_inspect_shots',
    '_inspect',
    '_shoot_set',
    'PORTFOLIO_N',
    'ORBIT_N',
    'HIGH_N',
    'STATIONS',
    'DECK_LEVELS',
    'MERGE_M',
    'DETAIL_FOCAL',
    'RAKE_FOCAL',
    'PORTRAIT_COS',
    '_cloud_extreme',
    '_levels',
    '_inside_shot',
    '_portfolio_shots',
    '_trim',
    '_portfolio',
    'SHARP_RAD',
    'CREASE_RAD',
    'FLAT_FACES',
    'DEFAULT_GREY',
    '_mat_row',
    '_audit',
    'main',
]
