# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""proxy_actor.py — a rigged MPFB human playing a motion clip, as a .blend.

    flock /tmp/claude-1000/arch_ext_blender.lock /usr/local/bin/blender -b \
        --python blender_scripts/proxy_actor.py -- \
        --name abel --height 1.52 --age 13 --gender 0.9 --motion cmu/02_01

Two motion sources, selected by the ``--motion`` id and listed together by
``--list-motions``: ``cmu/*`` are retargeted BVH clips, ``auth/*`` are the
keyframed actions in blender_scripts/motion_authored.py (fly, drive, scream —
the verbs the CMU library does not cover).  Both end up as an action named
``motion`` on the same ``cmu_mb`` rig, so nothing downstream can tell them apart.

The proxy is a DRIVER for depth / matte / skeleton plates, not the final image:
silhouette and joint positions matter, looks do not. Body from MPFB (CC0 base
mesh), rig from MPFB's own `cmu_mb` skeleton — 31 bones named exactly like the
CMU MotionBuilder BVH joints — motion from data/assets/motion_library.

Retarget (see RETARGET_NOTE below): world-space delta. Every bone is given the
rotation the BVH bone actually performs between frame 1 and frame t, applied on
top of the MPFB rest orientation. The brief's route A (align the MPFB rest pose
to the BVH frame-1 T-pose, then Copy Rotation in WORLD space) transfers the roll
convention as well, and the two rigs' rolls disagree by up to 181 deg on the
thighs / 251 deg on the thumbs — baking that into the rest pose wrings the mesh
around the limb axis. The delta is roll-convention-free and is what route A
would give if the rolls agreed. What a delta cannot fix is a rest pose that
holds a limb where the clip never puts it, so the bones of ``ALIGN_BONES`` --
the arms and, since 2026-09-24, the legs -- have their rest DIRECTION turned to
the BVH's frame 1 first (``align_rest``, direction only, roll kept).

MPFB is an EXTENSION in Blender 4.3: import bl_ext.user_default.mpfb.*, never
`mpfb` (project memory).

Two bodies under that one skeleton, selected by ``--body``:
    mpfb    the MPFB-generated mesh, macros from --gender/--age/--weight/...
    base    the rigged CC0 clay base body of data/assets/base_body_rig
            (Blender Studio Human Base Meshes v1.4.1, the body every character
            preview shows), appended whole — mesh, cmu_mb rig and weights.
``--fit FIT_JSON`` then scales the bone groups of either body along their own
length until five measured proportions (leg, arm, torso, head_neck, shoulder,
each a fraction of standing height) match a zyg.body_metrics/1 record. It runs
BEFORE the uniform height scale, so --height stays exact.

Output, under --out/<name>/ — the EXPORTER CONTRACT the scene builder reads:
    <name>.blend        collection 'actor': actor_root (empty, ground origin)
                        -> armature (custom props) -> mesh; action 'motion'
    <name>.json         {name, height_m, motion, frames, fps, bones, mapping}
    <name>_strip.png    3 x 256x384 CPU workbench frames (1, mid, last)

Armature custom properties:
    actor_name, actor_height_m, motion_id, mapping ('cmu_mb')
    root_offset_z   metres the scene builder must LIFT actor_root above the
                    path point before keying it (scene_build.place_actor adds
                    it to the z of SS.to_blender(st['p'])).  0.0 for a clip
                    that stands on the ground; 1.2 x height for auth/fly;
                    the seat height for auth/drive.  Also in <name>.json, with
                    'seat_offset' when the motion is one that rides a vehicle.
"""

# proxy_actor.py became this package on 2026-10-07; every section moved verbatim. The flat
# import path is unchanged (`import proxy_actor as PA`, with blender_scripts/ on sys.path),
# and the original top import block is re-done here so attribute accesses like
# proxy_actor.bpy / proxy_actor.MA still resolve.
# ruff: noqa: E402,F401
import json
import math
import os
import sys
import tempfile
import time

import bpy
from mathutils import Matrix, Vector

# Submodules in the original section order.
from zyg_workflows.blender_scripts.proxy_actor import constants as constants
from zyg_workflows.blender_scripts.proxy_actor import args_scene as args_scene
from zyg_workflows.blender_scripts.proxy_actor import body as body
from zyg_workflows.blender_scripts.proxy_actor import fit as fit
from zyg_workflows.blender_scripts.proxy_actor import motion as motion
from zyg_workflows.blender_scripts.proxy_actor import output as output
from zyg_workflows.blender_scripts.proxy_actor import actor_build as actor_build

from zyg_workflows.blender_scripts import motion_authored as MA
from zyg_workflows.blender_scripts import skeleton_bind

from zyg_workflows.blender_scripts.proxy_actor.constants import (
    ALIGN_BONES,
    BASE_BODY_ROOT,
    BONE_ALIAS,
    DEFAULT_OUT,
    FIT_GROUPS,
    FIT_MAX,
    FIT_MIN,
    FIT_TOL,
    GROUND_TOL,
    HERE,
    MOTION_ROOT,
    RETARGET_NOTE,
    STRIP_H,
    STRIP_W,
    TRACK_GROUPS,
    TRACK_TOL,
    TRACK_WEIGHT_MIN,
)
from zyg_workflows.blender_scripts.proxy_actor.args_scene import (
    age_macro,
    all_motions,
    clear_scene,
    evaluated_bbox,
    evaluated_points,
    find_clip,
    load_library,
    parse_args,
    standing_height,
)
from zyg_workflows.blender_scripts.proxy_actor.body import (
    ARM_CHAIN,
    ARM_RATIO_HI,
    ARM_RATIO_LO,
    CLAVICLE_BONES,
    CLAVICLE_FAR,
    CLAVICLE_HOST,
    CLAVICLE_NEAR,
    TRUNK_CORE,
    _point_segment,
    add_rig,
    apply_pose_as_rest,
    bake_pose_as_rest,
    base_body_id,
    bound_arm_chain,
    bound_clavicles,
    build_body,
    load_base_body,
    strip_helpers,
)
from zyg_workflows.blender_scripts.proxy_actor.fit import fit_rig, load_fit_spec, measure_fit, scale_actor
from zyg_workflows.blender_scripts.proxy_actor.motion import (
    align_rest,
    face_minus_y,
    ground,
    hierarchy_order,
    import_bvh,
    per_frame_stats,
    retarget,
    sample_bvh,
    track_vertex_indices,
)
from zyg_workflows.blender_scripts.proxy_actor.output import make_collection, render_strip, run_checks, stitch
from zyg_workflows.blender_scripts.proxy_actor.actor_build import build, check_blend, main, skeleton_meta

# proxy_actor.py ran main() at import time -- base_body_rig.py relies on it (it fakes
# `-- --list-motions` around its `import proxy_actor`). Kept as the package's last statement,
# so it still runs after every section is defined.
main()
