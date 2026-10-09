# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Arguments, the Blender scene helpers and the CC0 base body — base_body_rig sections 1-4.

Holds the original module's own import block, so every path constant
(``HERE``, ``CREWS``, ``SRC_BLEND``, ``DEFAULT_OUT``) and the ``proxy_actor``
import with its argv guard execute here, first and once.
"""

# ruff: noqa: F401  # the original top import block is re-exported to the siblings

import argparse
import bisect
import json
import math
import os
import sys
import tempfile
import time

import bpy
from mathutils import Matrix, Vector
from mathutils.bvhtree import BVHTree

from zyg_workflows import paths

import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)

# ``HERE`` is the blender_scripts directory base_body_rig.py used to live in — the
# Blender scripts are also imported flat, by name, off that directory (see the
# ``proxy_actor`` import below) — and ``CREWS`` is the package directory above it.
HERE = str(paths.PKG_DIR / 'blender_scripts')
CREWS = str(paths.PKG_DIR)
SRC_BLEND = os.path.join(
    CREWS,
    'data',
    'assets',
    'mesh_packs',
    'blender_human_base',
    'human-base-meshes-bundle-v1.4.1',
    'human_base_meshes_bundle.blend',
)
DEFAULT_OUT = os.path.join(CREWS, 'data', 'assets', 'base_body_rig')

# The flat-script bootstrap Blender needs: proxy_actor is imported by its bare name here
# and imports motion_authored / skeleton_bind by theirs, so blender_scripts/ must be on
# sys.path. Kept deliberately — this is the by-path entry convention, not split residue.
sys.path.insert(0, HERE)
# proxy_actor.py calls main() at import time; --list-motions is its only
# side-effect-free path. We only want its MPFB helpers.
_REAL_ARGV = list(sys.argv)
# argv[0] is only the prog name argparse prints; keep the real one (the Blender binary).
sys.argv = [_REAL_ARGV[0], '--', '--list-motions']
try:
    import proxy_actor as PA  # noqa: E402
finally:
    sys.argv = _REAL_ARGV

BODIES = {
    'male_realistic': {'object': 'GEO-body_male_realistic', 'gender': 1.0},
    'female_realistic': {'object': 'GEO-body_female_realistic', 'gender': 0.0},
}

# MPFB cmu_mb spelling -> CMU BVH / motion_library.CMU_MB_JOINTS spelling.
BONE_RENAME = {'LeftHandFinger1': 'LeftHandIndex1', 'RightHandFinger1': 'RightHandIndex1'}

CENTRE_BONES = ('Hips', 'LowerBack', 'Spine', 'Spine1', 'Neck', 'Neck1', 'Head')
MIRROR_PAIRS = [('LHipJoint', 'RHipJoint'), ('LThumb', 'RThumb')] + [
    ('Left' + s, 'Right' + s)
    for s in ('UpLeg', 'Leg', 'Foot', 'ToeBase', 'Shoulder', 'Arm', 'ForeArm', 'Hand', 'FingerBase', 'HandIndex1')
]

# Bones whose TAIL is allowed to sit up to 5 mm proud of the surface: they end at
# the tip of a toe or a finger, where the mesh is thinner than the tolerance.
TIP_TAILS = ('LeftToeBase', 'RightToeBase', 'LThumb', 'RThumb', 'LeftHandIndex1', 'RightHandIndex1')

HEIGHT_FRACTIONS = {
    'Hips': (0.50, 0.58),
    'LeftLeg': (0.25, 0.32),
    'LeftFoot': (0.03, 0.09),
    'LeftArm': (0.78, 0.86),
    'Head': (0.84, 0.92),
}

# Bands the finished arm must land in, all four measured off these two meshes
# once the arm-axis transfer was in (male / female):
#   arm_fraction 0.2820 / 0.2931, arm_length_fraction 0.2896 / 0.3007,
#   forearm_ratio 0.9616 / 0.8834, elbow 0.6636 / 0.6466, wrist 0.5399 / 0.5238.
# The textbook shoulder-to-wrist figure is 0.30-0.36 H, but that is an arm
# measured STRAIGHT; these bodies stand in an A-pose with a bent elbow, so the
# straight line shoulder->wrist is a chord ~2.5 % shorter than the arm itself.
# arm_length_fraction (the two bone segments summed, which is what --fit scales
# and is pose-independent) does land at 0.29-0.30. The girth profile printed by
# build_arm_axes is the evidence the joints are on the right spots: the base
# mesh's own wrist -- the narrowest cross-section of the arm, 0.058 m on the
# male -- sits at u 0.70 along the arm centre line and the donor puts
# LeftHand.head at u 0.692. The arm is short because the mesh's arm is short,
# not because the joint is misplaced.
ARM_FRACTION = (0.27, 0.33)  # |shoulder -> wrist| / standing height
ARM_LENGTH_FRACTION = (0.27, 0.34)  # (upper arm + forearm) / standing height
FOREARM_RATIO = (0.75, 1.05)  # forearm / upper arm
ELBOW_FRACTION = (0.61, 0.69)  # LeftForeArm.head z / height
WRIST_FRACTION = (0.50, 0.57)  # LeftHand.head z / height

SLICE_BAND = 0.01  # +/- 1 cm around the joint's height
CLUSTER_GAP = 0.04  # x-gap that separates an arm from the torso
UV_MARGIN = 0.06  # how far inside the slice a clamped joint is kept
ARM_SLICE_FRAC = 0.05  # +/- this much of the arm length makes a cross-section
MIRROR_TOL = 0.01
GROUND_TOL = 0.01
INSIDE_MARGIN = 0.004  # how far past the surface a nudged joint is pushed
VIEW_W, VIEW_H = 512, 768
MAX_BLEND_MB = 40.0


# ----------------------------------------------------------------- arguments


def parse_args(argv):
    p = argparse.ArgumentParser(prog='base_body_rig.py')
    p.add_argument('--body', choices=sorted(BODIES), default='male_realistic')
    p.add_argument('--out', default=DEFAULT_OUT)
    p.add_argument('--no-render', action='store_true')
    return p.parse_args(argv)


# --------------------------------------------------------------------- scene


def clear_scene():
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj, do_unlink=True)
    for act in list(bpy.data.actions):
        bpy.data.actions.remove(act)


def activate(obj):
    bpy.ops.object.select_all(action='DESELECT')
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj


def apply_transforms(obj):
    activate(obj)
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)


def local_verts(obj):
    """Vertex coordinates. Every object here carries an identity transform."""
    return [v.co.copy() for v in obj.data.vertices]


def bbox(points):
    lo = Vector((1e9, 1e9, 1e9))
    hi = Vector((-1e9, -1e9, -1e9))
    for p in points:
        for i in range(3):
            lo[i] = min(lo[i], p[i])
            hi[i] = max(hi[i], p[i])
    return lo, hi


# ---------------------------------------------------------------- base body


def append_objects(names):
    with bpy.data.libraries.load(SRC_BLEND, link=False) as (src, dst):
        missing = [n for n in names if n not in src.objects]
        if missing:
            raise SystemExit('not in %s: %s' % (SRC_BLEND, missing))
        dst.objects = list(names)
    out = []
    for obj in dst.objects:
        bpy.context.scene.collection.objects.link(obj)
        out.append(obj)
    return out


def tag_group(obj, name):
    group = obj.vertex_groups.new(name=name)
    group.add([v.index for v in obj.data.vertices], 1.0, 'REPLACE')


def facing_sign(points):
    """+1 when the toes point to +Y, -1 when they point to -Y.

    Measured off the feet: a foot slice is far longer in the toe direction than
    behind the ankle, and the toe half is the wider one. Both halves of the y
    range are compared by x-width, which is symmetric in left/right and so works
    on any standing body."""
    feet = [p for p in points if 0.004 <= p.z <= 0.030]
    if not feet:
        return 1
    ys = [p.y for p in feet]
    y0, y1 = min(ys), max(ys)
    span = y1 - y0
    if span < 1e-4:
        return 1
    front = [p for p in feet if p.y >= y1 - 0.2 * span]
    back = [p for p in feet if p.y <= y0 + 0.2 * span]
    width = lambda sel: (max(p.x for p in sel) - min(p.x for p in sel)) if sel else 0.0
    return 1 if width(front) >= width(back) else -1


def prepare_base(body_id):
    """Append the body + its two eyes, join them, weld, face -Y, feet on z = 0."""
    spec = BODIES[body_id]
    base_name = spec['object']
    names = [base_name, base_name + '.eye.L', base_name + '.eye.R']
    objs = append_objects(names)
    body, eyes = objs[0], objs[1:]
    for obj in objs:
        apply_transforms(obj)
    verts_body = len(body.data.vertices)
    for eye in eyes:
        tag_group(eye, 'EYES')

    bpy.ops.object.select_all(action='DESELECT')
    for eye in eyes:
        eye.select_set(True)
    body.select_set(True)
    bpy.context.view_layer.objects.active = body
    bpy.ops.object.join()
    joined = len(body.data.vertices)

    body.name = body.data.name = body_id

    # Weld BEFORE bone heat: split vertices make it fail silently.
    activate(body)
    bpy.ops.object.mode_set(mode='EDIT')
    bpy.ops.mesh.select_all(action='SELECT')
    bpy.ops.mesh.remove_doubles(threshold=1e-4)
    bpy.ops.object.mode_set(mode='OBJECT')
    welded = len(body.data.vertices)

    sign = facing_sign(local_verts(body))
    if sign > 0:  # toes to +Y: turn it around
        for vert in body.data.vertices:
            vert.co.x = -vert.co.x
            vert.co.y = -vert.co.y
    body.data.update()

    lo, hi = bbox(local_verts(body))
    shift = Vector((-(lo.x + hi.x) * 0.5, 0.0, -lo.z))
    for vert in body.data.vertices:
        vert.co += shift
    body.data.update()
    lo, hi = bbox(local_verts(body))
    height = hi.z - lo.z
    _zyg_log.info(
        '[rig] base %s: %d + eyes -> %d verts, welded %d, facing_sign %+d, '
        'height %.4f m, min z %+.5f' % (body_id, verts_body, joined, welded, sign, height, lo.z)
    )
    return (
        body,
        height,
        {'source_verts': verts_body, 'joined_verts': joined, 'welded_verts': welded, 'turned_around': bool(sign > 0)},
    )
