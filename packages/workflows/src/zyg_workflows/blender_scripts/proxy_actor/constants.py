# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

# This module inherits proxy_actor.py's own top import block verbatim, so every name the
# single file exposed as an attribute still resolves. Names used only by sibling sections
# are therefore 'unused' here on purpose.
import json
import math
import os
import sys
import tempfile
import time

import bpy
from mathutils import Matrix, Vector

from zyg_workflows import paths
from zyg_workflows.blender_scripts import motion_authored as MA
from zyg_workflows.blender_scripts import skeleton_bind

# the attribute surface the single file had: the inherited import block first,
# then this module's own constants
__all__ = [
    'json',
    'math',
    'os',
    'sys',
    'tempfile',
    'time',
    'bpy',
    'Matrix',
    'Vector',
    'paths',
    'MA',
    'skeleton_bind',
    'RETARGET_NOTE',
    'HERE',
    'MOTION_ROOT',
    'DEFAULT_OUT',
    'BASE_BODY_ROOT',
    'FIT_GROUPS',
    'FIT_MIN',
    'FIT_MAX',
    'FIT_TOL',
    'BONE_ALIAS',
    'ALIGN_BONES',
    'STRIP_W',
    'STRIP_H',
    'GROUND_TOL',
    'TRACK_GROUPS',
    'TRACK_WEIGHT_MIN',
    'TRACK_TOL',
]

RETARGET_NOTE = (
    'world-space delta: R_bone(t) = [R_bvh(t) . R_bvh(1)^-1] . R_rest_mpfb; '
    'rest pose untouched, roll conventions cancel'
)

# The package root and the three trees inside its data/ that proxy_actor.py reached by
# walking up from its own __file__.
HERE = str(paths.PKG_DIR)
MOTION_ROOT = str(paths.DATA_DIR / 'assets' / 'motion_library')
DEFAULT_OUT = str(paths.DATA_DIR / 'architecture' / 'actors')
BASE_BODY_ROOT = str(paths.DATA_DIR / 'assets' / 'base_body_rig')

# --fit: the bone groups scaled along their own length, and what each one
# measures as a fraction of standing height (see measure_fit).
FIT_GROUPS = {
    'leg': ('LeftUpLeg', 'LeftLeg', 'RightUpLeg', 'RightLeg'),
    'arm': ('LeftArm', 'LeftForeArm', 'RightArm', 'RightForeArm'),
    'torso': ('LowerBack', 'Spine', 'Spine1'),
    'head_neck': ('Neck', 'Neck1', 'Head'),
    'shoulder': ('LeftShoulder', 'RightShoulder'),
}
FIT_MIN, FIT_MAX = 0.80, 1.25  # a fit may not reshape a body beyond this
FIT_TOL = 0.03  # measured must land within 3 % of the clamped target

# MPFB bone name -> BVH joint name, where the two disagree.
BONE_ALIAS = {'LeftHandFinger1': 'LeftHandIndex1', 'RightHandFinger1': 'RightHandIndex1'}

# Bones whose MPFB rest direction is turned to the BVH frame-1 direction before
# baking (route A's first step), so their world pose follows the clip absolutely
# rather than relative to MPFB's A-pose. MPFB's arms rest 40-65 deg away from the
# CMU T-pose, which is too much to carry as an offset.
#
# THE LEGS ARE IN THE LIST FOR THE SAME REASON (2026-09-24). The delta retarget
# keeps whatever the rest pose says a bone does not do, and the A-pose STANDS
# WITH ITS FEET TURNED OUT: measured on the base body, rest thighs 8.7 deg off
# vertical and each Foot bone 19.6 deg lateral, against a clip -- cmu/02_01 --
# whose own stance foot progression angle is 1 deg. So every walk was played by
# an actor with a 40 deg V between its feet, and it read as a weird, splay-footed
# gait (operator, 2026-09-24). Aligning UpLeg / Leg / Foot turns 9.6 / 10.4 /
# 19.2 deg out of the rest pose and hands the clip's own leg angles back.
#
# Everything else is still left alone on purpose: the two rigs' connector bones
# (LHipJoint 50 deg, LeftShoulder 27 deg) and the spine/neck point differently
# because the joints themselves sit elsewhere, so aligning them would displace
# the limbs -- and the anatomical skeleton's clavicle and scapula are fitted to
# the Shoulder bone where it rests, so turning it would carry them out of the
# body. ToeBase is out for the same reason: an 18 mm nub carrying the toe pieces.
ALIGN_BONES = (
    'LeftArm',
    'RightArm',
    'LeftForeArm',
    'RightForeArm',
    'LeftHand',
    'RightHand',
    'LeftUpLeg',
    'RightUpLeg',
    'LeftLeg',
    'RightLeg',
    'LeftFoot',
    'RightFoot',
)

STRIP_W, STRIP_H = 256, 384
GROUND_TOL = 0.08

# "does the mesh follow the rig" is measured on the pelvis/spine/thigh vertices
# only. The mesh bounding-box centre used to stand in for the body, but it
# follows whichever limb reaches furthest: on the base body the long hanging
# arms and hands drag it 0.37 m from the Hips on a sword clip whose bind is
# perfect. These groups deform with the root chain, so their centroid moves
# with the Hips and nothing else.
TRACK_GROUPS = ('Hips', 'LowerBack', 'Spine', 'Spine1', 'LeftUpLeg', 'RightUpLeg')
TRACK_WEIGHT_MIN = 0.5
TRACK_TOL = 0.25
