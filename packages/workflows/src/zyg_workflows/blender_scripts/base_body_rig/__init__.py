# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""base_body_rig.py — the cmu_mb skeleton inside the CC0 Blender Studio base body.

    flock /tmp/claude-1000/arch_ext_blender.lock /usr/local/bin/blender -b \
        --python blender_scripts/base_body_rig.py -- --body male_realistic

ONE skeleton runs through the whole movement stack: MPFB's ``cmu_mb`` rig, 31
bones named like the CMU MotionBuilder BVH joints (``motion_library.CMU_MB_JOINTS``).
Until now the body under it was an MPFB-generated mesh (proxy_actor.py). This
script puts the same skeleton inside the Character Studio clay base body —
Blender Studio Human Base Meshes v1.4.1, CC0 — so Movement Studio shows the body
every character preview already shows.

BONE NAMES. MPFB's cmu_mb calls the two index-finger bones ``LeftHandFinger1`` /
``RightHandFinger1``; the CMU BVH files (and ``motion_library.CMU_MB_JOINTS``)
call them ``LeftHandIndex1`` / ``RightHandIndex1`` — proxy_actor bridges the two
with its BONE_ALIAS table. The rig written here uses the BVH/library spelling, so
the bone set is byte-equal to CMU_MB_JOINTS and no alias table is needed
downstream. Nothing else is renamed.

JOINT PLACEMENT — donor method. An MPFB human of the same sex is built with
proxy_actor's own helpers and scaled to the base body's standing height; MPFB
locates every cmu_mb joint from its `joint-*` helper cubes, so the donor carries
the anatomy. Each donor joint P is then re-expressed on the base body:

    take the donor's horizontal slice at z = P.z (+/- 1 cm),
    split it into clusters separated by an x-gap > 4 cm (at hand height the
        slice is three clusters: right arm, torso, left arm),
    pick the cluster whose centroid is nearest P,
    write P as normalised (u, v) inside that cluster's xy bounding box,
    read (u, v) back out of the base body's slice at the same z, same cluster
        rank — and when the base slice has a different cluster count (the hands
        hang at a different height), the nearest z that has the right count,
        which the sidecar records as a fallback.

z is never changed, so the donor's height fractions (hips, knee, ankle,
shoulder) survive the transfer. MPFB's bone rolls are kept verbatim.

ARMS ARE THE EXCEPTION. The two bodies hang their arms at very different angles
— the donor's A-pose is open, the base body's is nearly vertical — so at the
donor wrist's height the base body is still showing its upper arm, and a
z-preserving transfer parks the wrist near the elbow: shoulder-to-wrist came out
at 0.21 of standing height where a human is 0.30-0.36. Everything from the elbow
outwards is therefore carried by its FRACTION ALONG THE ARM instead: each body's
arm is isolated from the armpit down (``arm_region``), its axis runs from the
shoulder joint to the farthest vertex of that region — the fingertip — and a
joint at fraction s of the donor's axis is written at fraction s of the base
body's, centred in the cross-section there (``ArmFrame``). Shoulders, legs,
torso and head keep the height-preserving method.

WEIGHTS. Blender bone heat (``parent_set(type='ARMATURE_AUTO')``) — but the mesh
is welded first: split vertices make bone heat fail silently and leave EMPTY
vertex groups (project memory, measured 2026-09-05). The eye spheres are joined
into the body and pinned 1.0 to ``Head``.

Output, under --out/<id>/:
    <id>.blend      mesh '<id>' parented to armature '<id>_rig', identity
                    transforms, feet on z = 0
    <id>.json       schema zyg.base_body_rig/1 — bones, weights, checks
    <id>_rest.png   2 x 512x768 workbench views (front, side) of the rest pose
                    with the skeleton drawn over the body
"""

# ruff: noqa: E402,F401  # Pattern A re-export shim: the package IS the old module.

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

# The sections, imported in their original order so every module-level side
# effect (sys.path, the proxy_actor import, the bare main() call) runs exactly
# where it ran in the single file.
from .scene import (
    ARM_FRACTION,
    ARM_LENGTH_FRACTION,
    ARM_SLICE_FRAC,
    BODIES,
    BONE_RENAME,
    CENTRE_BONES,
    CLUSTER_GAP,
    CREWS,
    DEFAULT_OUT,
    ELBOW_FRACTION,
    FOREARM_RATIO,
    GROUND_TOL,
    HEIGHT_FRACTIONS,
    HERE,
    INSIDE_MARGIN,
    MAX_BLEND_MB,
    MIRROR_PAIRS,
    MIRROR_TOL,
    PA,
    SLICE_BAND,
    SRC_BLEND,
    TIP_TAILS,
    UV_MARGIN,
    VIEW_H,
    VIEW_W,
    WRIST_FRACTION,
    _REAL_ARGV,
    activate,
    append_objects,
    apply_transforms,
    bbox,
    clear_scene,
    facing_sign,
    local_verts,
    parse_args,
    prepare_base,
    tag_group,
)
from .transfer import (
    ARM_CHAIN,
    ArmAxis,
    ArmFrame,
    DonorArgs,
    ZIndex,
    arm_region,
    arm_side,
    build_arm_axes,
    build_donor,
    clamp_into,
    cluster_box,
    cluster_centroid,
    half_width,
    pick_cluster,
    transfer_point,
)
from .rig import (
    RAYS,
    arm_measures,
    bind,
    bone_sticks,
    bone_table,
    hit_count,
    is_inside,
    load_png,
    nudge_inside,
    pin_eyes,
    rename_bones,
    render_rest,
    run_checks,
    save_png,
    surface_distance,
    symmetrise,
    unweighted,
    write_bones,
)
from .pipeline import build, main
