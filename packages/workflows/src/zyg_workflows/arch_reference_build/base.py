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

import contextlib
import io
import json
import math
import os
import sys
import traceback

import bpy  # noqa: E402
import bmesh  # noqa: E402
import mathutils  # noqa: E402
import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger('zyg_workflows.arch_reference_build')


LOG = []


def log(msg):
    LOG.append(str(msg)[:400])
    _zyg_log.info('[refbuild] ' + str(msg)[:400])


def argv():
    a = sys.argv
    return a[a.index('--') + 1 :] if '--' in a else []


def arg(name, default=''):
    a = argv()
    return a[a.index(name) + 1] if name in a and a.index(name) + 1 < len(a) else default


def flag(name):
    return name in argv()


# ── the view table (mirrors arch_reference.ROLES; kept here so the script that
#    runs inside Blender never has to import the server's modules) ────────────
ORIENT = {
    'view_side': ((0.5, 0.0, 0.0), (0.0, -1.0, 0.0)),
    'view_side_other': ((0.5, 0.0, 1.0), (0.0, 1.0, 0.0)),
    'view_front': ((0.5, 0.0, 0.5), (1.0, 0.0, 0.0)),
    'view_back': ((0.5, 0.0, -0.5), (-1.0, 0.0, 0.0)),
    'view_top': ((0.0, 0.0, 0.0), (0.0, 0.0, 1.0)),
    'view_bottom': ((0.0, 1.0, 0.0), (0.0, 0.0, -1.0)),
    'section': ((0.5, 0.0, 0.5), (1.0, 0.0, 0.0)),
}
# which measured dimension spans a view's WIDTH on screen
ACROSS = {
    'view_side': 'length_m',
    'view_side_other': 'length_m',
    'view_top': 'length_m',
    'view_bottom': 'length_m',
    'view_front': 'beam_m',
    'view_back': 'beam_m',
    'section': 'beam_m',
}

REF = {}
_REF_OBJS = []


def _num(v, d=0.0):
    try:
        return float(v)
    except (TypeError, ValueError):
        return d


# This module inherited the original file's whole import block, and the
# sibling modules of this package re-import from it what they need; nothing
# here is unused, so the autofix must not delete any of it — the package
# __init__ re-exports every one of these names from here.
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
    'REF',
    '_REF_OBJS',
    '_num',
]
