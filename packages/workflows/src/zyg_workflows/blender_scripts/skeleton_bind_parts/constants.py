# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

# This module inherits skeleton_bind.py's ORIGINAL top import block, which travels
# byte for byte: the siblings import what they need from bpy / mathutils
# themselves, and skeleton_bind.os / .json / .Vector ... are re-exported from here
# so the old module's namespace resolves unchanged.  F401 is therefore expected.
# ruff: noqa: F401

"""Put the CC0 anatomical skeleton mesh inside a base-body actor.

Source: Blender Studio Human Base Meshes v1.4.1 (CC0), collection
"Skeleton - Realistic" -- 135 named MESH objects ``GEO-skeletion.*`` (sic).
Every object's ORIGIN sits on the joint it hangs from, which is what makes a
per-segment fit to the cmu_mb rig cheap and exact.

The 135 pieces are mapped onto the 31-bone cmu_mb rig, placed group by group
(one rigid transform for the trunk + head, a per-segment fit for every limb
bone), joined into ONE mesh named ``skeleton`` skinned rigidly -- every vertex
weight 1.0 in exactly one vertex group, named exactly as its rig bone.

Harness::

    /usr/local/bin/blender -b --factory-startup \\
        --python blender_scripts/skeleton_bind.py -- \\
        --rig male_realistic --out /tmp/claude-1000/skelfit

Always run Blender with ``-b --factory-startup``: the user profile's add-ons
crash and flood background mode.
"""

from __future__ import annotations

import json
import math
import os
import sys
import tempfile

import bpy
from mathutils import Matrix, Quaternion, Vector

from zyg_workflows import paths

# ``HERE`` is the blender_scripts directory skeleton_bind.py used to live in, ``CREWS``
# the package directory above it; SKELETON_BLEND and BASE_BODY_RIG_DIR hang off those.
HERE = str(paths.PKG_DIR / 'blender_scripts')
CREWS = str(paths.PKG_DIR)

SKELETON_BLEND = os.path.join(
    CREWS,
    'data',
    'assets',
    'mesh_packs',
    'blender_human_base',
    'human-base-meshes-bundle-v1.4.1',
    'human_base_meshes_bundle.blend',
)
BASE_BODY_RIG_DIR = os.path.join(CREWS, 'data', 'assets', 'base_body_rig')

PIECE_PREFIX = 'GEO-skeletion.'
SOURCE_CREDIT = 'Blender Studio Human Base Meshes v1.4.1, CC0, Skeleton - Realistic'

SUBSURF_LEVELS = 1  # render level 2 would land at ~1.05 M triangles
TRI_BUDGET_HIGH = 220_000  # above this we decimate
TRI_BUDGET_TARGET = 200_000
TRI_FLOOR = 120_000
AXIS_SCALE_CLAMP = (0.8, 1.25)
INSIDE_MARGIN = 0.025  # 2.5 cm

# Objects created by attach_skeleton, so that callers (the actor build) can
# carry them through scale / pose-as-rest together with the body. Since
# 2026-09-24 the actor build fits the skeleton AFTER the last of those, so the
# list is normally still empty when they run -- deliberately: a rigid mesh
# carried through a bake keeps its shape while the skin changes shape around
# it, and a ribcage tucked inside an A-pose chest ended up 7 mm outside the
# chest the actor actually stands in.
EXTRA_MESHES: list = []
