# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""pose_limits.py — joint range of motion and kinematic plausibility on the anny rig, and
an honest record of which of the requested constraints this rig cannot carry.

WHY THIS MODULE EXISTS
We have 163 bones, a ControlNet pose channel, a VACE retarget path and a fitted pose
library on disk, and until this file there was not one joint-limit or kinematic check
anywhere in the geometry stack. geom/anthro/ measures a body STANDING STILL — every one of
its 42 gates is a linear measure or a ratio taken on the rest mesh — and geom/form/ measures
SHAPE. Neither can see a wrist bent 120 degrees backwards, a neck that does all its
extension at C7, a forearm that pronates by rolling the shoulder, or a patella riveted to
the femur. Those are not wrong dimensions and they are not wrong shapes; they are wrong
MOTION, and motion is what the pose channel actually ships.

WHAT IS IN HERE, AND WHERE EVERY NUMBER CAME FROM
Six gates. Three of them carry a printed number and three carry no number at all:

  t5_joint_rom            wrist extension 0-45 natural / 45-90 forced, flexion 0-50 /
                          50-90, ulnar deviation <=40, radial deviation <=20 and flagged
                          unnatural            (Anatomy For Sculptors p.181-182)
                          cervical extension <=85 total, 15-20 per joint C3-C7
                                               (Form of the Head and Neck p.161)
                          >=50% of head pitch and yaw at the occiput-C2 joint
                                               (Form of the Head and Neck p.171)
  t5_pose_stiffness       a DIVERSITY statistic over a pose SET, not an anatomy gate. The
                          one printed number in it is AFS p.16's transverse-tilt stdev
                          > 2 degrees with shoulder and hip tilts of OPPOSITE sign.
  t5_pronation_isolation  driving forearm pronation must produce EXACTLY ZERO humerus
                          rotation (AFS p.149) and the twist gradient along the forearm
                          must be monotonic with its maximum at the wrist (AFS p.150).
                          Zero is zero and monotonicity has no free parameter.
  t5_scapula_static       scapula rotation ~= 0 below 90 degrees of humeral abduction
                          (AFS p.90).
  t5_elbow_owner          the olecranon patch must be rigid in the FOREARM frame, not the
                          upper-arm frame (AFS p.156). A comparative residual: the gate
                          asks which of two frames explains the patch better and there is
                          nothing to tune. Its PASS is CONDITIONED on a negative control —
                          the same comparator must call the epicondyles humerus-owned —
                          because on this cage it does not, and an unconditioned pass here
                          would be produced whether or not the claim were true (D7).
  t5_patellar_ligament    distance(patella, tibial tuberosity) invariant to within 2%
                          across every posed frame (AFS p.208).

CALIBRATION POLICY, and it is the reason this file contains no tuned constant.
Every threshold above is either a printed degree count or an exact zero / ordering /
invariance. Nothing here was chosen by looking at our own meshes, and if one of our
characters fails, that is a FINDING about the character or the rig — never a reason to
widen the band. The two windows in this file that ARE ours (the wrist's search geometry
and the ERECT classification window in the stiffness statistic) are marked HOUSE, are
reported at three widths so their sensitivity is visible, and neither can produce a
blocking verdict.

PROVENANCE, AND THE 'CANON' RANK. geom.anthro.gates admits two provenance tags, MEASURED
(survey microdata: ANSUR II, CDC, NHANES) and HOUSE (ours, stated as such). The degrees in
this file are neither: they are printed in anatomy-for-artists books, which is a real
source but a weaker one than a survey, so they carry a third tag, CANON, ranked below
MEASURED. The rule that makes the rank mean something is enforced by machinery in
canon_may_block(): a CANON threshold may only block a quantity for which NO measured source
exists. It is allowed to block here, and the reason is checked at run time rather than
asserted — ansur_rom_columns() searches the ANSUR II microdata column list for any range-of-
motion column and finds none (ANSUR II is 93 linear measurements and 15 demographic
fields; it contains no angle at all). Were a goniometry survey ever added to the reference
packs, canon_may_block() would start returning False for these gates on its own.

THE RIG, ENUMERATED RATHER THAN ASSUMED — and this is the first thing this file says.
MEASURED on anny 0.5 (163 bones, rig preset 'default', bone_orientation
'blender-rootidentity'), by rig_report():

  PRESENT   root, pelvis.L/R, upperleg01/02, lowerleg01/02, foot, 28 toe bones,
            spine01..spine05, breast.L/R, clavicle.L/R, shoulder01.L/R,
            upperarm01/02, lowerarm01/02, wrist, 8 metacarpals, 30 finger bones,
            neck01, neck02, neck03, head, jaw, tongue00..07, and 40 facial bones.
  ABSENT    scapula. ribs. patella. radius. ulna. There is no bone whose name contains
            'scapula', 'rib', 'patella', 'radius' or 'ulna', and no hip, sternum,
            occiput, atlas or axis bone either.

Three consequences follow directly and are reported as UNRESOLVED rather than approximated:

  * t5_scapula_static CANNOT be run as written. Scapular rotation needs a scapula, and
    there is none. What CAN be measured, and is, is the complement: because no bone of the
    shoulder girdle rotates with humeral abduction on this rig, the girdle rotation is
    EXACTLY ZERO at every abduction angle. Below 90 degrees that is what AFS p.90 asks
    for; above 90 degrees the same page asks for the opposite and the rig cannot supply
    it. Reported as a two-sided finding, not as a pass.
  * PRONATION HAS NO ANATOMICAL SUBSTRATE. There is no radius and no ulna, so there is no
    radius rolling around a fixed ulna. Forearm pronation on this rig is a twist of
    lowerarm01/lowerarm02 about their own long axes, which is a RIG OPERATION that
    imitates the anatomical one. The zero-humerus-rotation half of AFS p.149 is still a
    real test of the retarget; the "radius rolls around the ulna" half is not testable
    here and says so.
  * THE PATELLA IS A SKIN PATCH, NOT A BONE. t5_patellar_ligament runs on geom.form.
    regions' frozen `patella` and `tibial_tuberosity` groups, both of which that module
    publishes with claim='surface_aspect' — the front of the knee and the front of the
    shank, positionally right, with no bony signature measured under either. The gate is
    still worth running, and the reason is the skinning: MEASURED here, the patella patch
    is 82.0% weighted to upperleg02 (the FEMUR) and the tuberosity patch is 95.0% weighted
    to lowerleg01 (the TIBIA). Two different bones drive them, so the invariance AFS p.208
    asserts is a real prediction on this rig and not an artefact of both patches riding the
    same rigid body. The gate reports that overlap every time so a vacuous pass can never
    be mistaken for a real one.

FRAME AND SIGN, MEASURED FROM THE RIG ITSELF.
Nothing in this file assumes a world axis convention. Every anatomical direction is derived
from the rig's own geometry at rest — superior from the spine chain, anterior from the eye
bones relative to the head bone, subject-left from eye.L minus eye.R — so the same code
reads an incoming skeleton in any frame. anatomical_frame() reports what it measured; on
anny it comes out as +x subject LEFT, +y POSTERIOR, +z SUPERIOR, which is the frame
geom.anthro.landmarks.frame_report() independently measures.

Angle signs, stated once:
  wrist       + extension (dorsiflexion), - flexion;  + ulnar deviation, - radial.
  cervical    + extension (the head's long axis tips POSTERIOR), - flexion.
              + yaw turns the face toward the subject's RIGHT.
  elbow       the INCLUDED angle at the joint, 180 = straight. Flexion decreases it.
  twist       + is the right-hand rule about the distal direction of the segment.

THE ENTRY POINT A GATE REGISTRY MUST CALL IS pose_layer(), NOT run_character().
run_character() measures the shipped REST A-POSE and nothing else. On that pose the wrists
sit within ~6 degrees of anatomical neutral and the whole cervical chain is at zero, so
t5_joint_rom's PASS there is a property of the rest configuration rather than of anything
the pose channel ships. pose_layer() evaluates every subject each pose gate DECLARES —
the rest rig and the fitted pose library — publishes each subject's verdict separately
(`rest_only_status`, `library_only_status`) and rolls them up by a written-down rule
(ROLLUP_RANK). Its exact returned dict is POSE_LAYER_CONTRACT, a printable module constant
(`python geom/pose_limits.py contract`). Measured consequence on the shipped assets:

  t5_joint_rom            rest A-pose PASS "0 of 11 ROM sub-checks failed"; the SAME gate
                          on abel's own 44 fitted poses fails 44 of 44 and on cornelis's
                          43 of 43, i.e. violation_rate 1.0 against the printed AFS
                          p.181-182 / HeadNeck p.161 / p.171 bands. Rolled up: NOT a pass.
  t5_pronation_isolation  rest A-pose PASS at 1.7e-06 deg of humeral rotation, and that
                          pass is CONSTRUCTIVE; over the fitted library the mean humeral
                          twist is 7.28 deg (abel) and 13.62 deg (cornelis) with a Pearson
                          r of -0.58 against forearm twist (abel). Rolled up: REPORT, with
                          those numbers, because no printed source gives a coupling
                          threshold and inventing one to force a FAIL would be the mirror
                          image of widening a band to force a PASS.

That 100% rate is a FINDING ABOUT OUR POSE LIBRARY. It is not a reason to widen a printed
band, and nothing in this file can widen one.

A LIBRARY THAT LOST FILES IS NOT A COMPLETE LIBRARY. scan_pose_library() accounts for every
file the glob matched, names every file it could not read and publishes `complete`;
pose_library_report() carries that accounting and raises its own status to at least WARN
when the denominator shrank, because a rate over a silently shrunken denominator is a
fabricated rate. load_pose_library() still returns only the records — for the callers that
only want poses — and now writes any drop to stderr so it cannot be lost by accident.

TWO SOURCES OF POSE, ONE GATE.
skeleton_from_rig() poses anny and reads bone frames back; skeleton_from_pose_aa() does
the same from a recorded 163x3 axis-angle pose, which is the format geom/anny_fit.py
writes and geom/anny_animate.py interpolates; skeleton_from_blazepose() takes the
33-point detection geom/keypoints.py returns. All three produce the same Skeleton record
and the same gates run on all three. What differs is what they can answer, and the
skeleton says so rather than guessing:

  frame='metric3d'   the rig. Everything is measurable.
  frame='pseudo3d'   BlazePose x, y and its per-landmark z. MediaPipe's z is in roughly
                     image-width units and hip-relative, i.e. it is NOT the same scale as
                     x and y, so an angle computed from it is biased by an unknown
                     anisotropy. Reported, never gated.
  frame='image2d'    x and y only. A 3D angle is NOT recoverable from its projection, and
                     the projection can be LARGER as well as smaller than the true angle
                     (two vectors 10 degrees apart in space project to 180 degrees when the
                     viewing direction lies between them), so a projected angle cannot even
                     bound the real one. Every angular gate returns UNMEASURABLE, with that
                     reason attached. This is the honest answer for a raw ControlNet pose
                     image, and it is why the useful path for incoming pose data is to lift
                     it through anny_fit first.

WHAT THIS FILE FOUND, on the shipped assets (measured, see main() and demo_broken()):

  * THE PATELLAR LIGAMENT IS NOT MODELLED, on every body including the control.
    dist(patella, tibial tuberosity) is supposed to be invariant to 2% through the knee
    range (AFS p.208). MEASURED it drifts 10.2% to 27.3%: anny-neutral +16.9% at 75 deg of
    flexion, female +27.3% at 90, male -10.2% at 120, abel -15.5% at 120, cornelis +16.4%
    at 75. The cause is in the same record: the patella patch is skinned 82.0% to
    upperleg02 (the FEMUR) and the tuberosity 95.0% to lowerleg01 (the tibia), so the front
    of the knee rides the thigh and slides away from the shin as the knee bends. Neither
    vacuous nor an artefact of the metric: the same measurement on two patches that DO
    share a bone reads 0.31%.

  * OUR ENTIRE FITTED POSE LIBRARY PUTS THE HEAD ROTATION IN THE WRONG JOINT. 87 of 87
    poses fail t5_joint_rom and almost all of it is one check, the occiput-C2 share.
    HeadNeck p.171 wants at least half of head pitch and yaw at the top joint; the fit
    delivers a quarter or less, spreading the rotation down a chain the optimiser treats as
    four interchangeable hinges. These are not numerical dust — binned by how much rotation
    was being apportioned, 35 of Abel's 44 yaw failures and 36 of Cornelis's 42 pitch
    failures sit above 15 degrees of total cervical rotation.

  * geom/anny_fit.py's bone-restriction mask is DEAD. It reads the roster from
    `m.bones`, an attribute the anny model does not have (it publishes `bone_labels`;
    geom/mesh_skeletons._bone_names exists precisely to accept either), so the guard falls
    through to `torch.ones(n_bones)` and ALL 163 BONES are free in the fit. The 87 fitted
    poses on disk therefore carry non-zero rotations on 71 bones the fit's own allow-list
    excludes, including both knees, both wrists, every metacarpal and the whole facial
    block, driven by 17 body keypoints. This module does not fix that — anny_fit.py is not
    this file's to edit — but t5_joint_rom measures its consequences, which is what a ROM
    gate is for.

  * WE CANNOT SAY WHETHER THE RIG PASSES AFS p.156, and this file used to say it did.
    RETRACTED 2026-08-06 (D7). The measurement itself stands: the olecranon patch is rigid
    in the FOREARM frame at every flexion angle on every body, at a residual ratio of about
    0.02 against the upper-arm frame, and the patch is skinned 95.1% to lowerarm01. What
    was wrong was reading that as "MakeHuman gets the elbow's ownership right". Handed the
    LATERAL EPICONDYLE — a prominence of the distal humerus — the identical comparator
    answers lowerarm01 too, at 0.0 mm against 54.75 mm, and the medial epicondyle likewise.
    The rig skins the entire elbow joint-line ring to the forearm, so a "forearm" answer
    there is what this cage returns for every patch at that joint and carries no
    information about the olecranon specifically. t5_elbow_owner now runs that control
    inside the gate and reports UNRESOLVED on all five bodies instead of PASS. The
    comparator is not broken — a patch carried rigidly by the humerus, synthetic or real
    (a >90% upperarm02 skin patch at the same joint), is correctly named humerus-owned and
    FAILS the gate.

  * OUR FITTED POSE LIBRARIES FAIL THE SECOND HALF OF AFS p.16. The page asks for a
    transverse-tilt standard deviation above 2 deg WITH SHOULDER AND HIP TILTS OF OPPOSITE
    SIGN. The standard deviations are comfortable (abel 11.79/9.50 deg, cornelis
    20.58/9.24). The sign opposition is not: 22 of abel's 44 poses and 23 of cornelis's 43
    tilt shoulders and hips the SAME way, and it is not numerical dust — requiring both
    tilts to exceed 2 deg still leaves 11 of 23 and 17 of 33. Until 2026-08-06 this gate
    scored only the standard deviation and both bodies rendered as a clean pass (R1).
    Separately, 10 of abel's 44 poses hold both forearms parallel within 5 deg, one of the
    three pose errors AFS p.175 names.

  * THE SHIPPED A-POSE IS ESSENTIALLY AT ANATOMICAL NEUTRAL AT THE WRIST on all five
    bodies: -2.9 to -3.8 deg of extension and -4.5 to -7.4 deg of ulnar deviation, well
    inside every printed band. Rest elbow flexion is 135-142 deg and rest knee 167-171 deg.

LICENCE. Joint ranges of motion are anatomical facts, not expression: facts and methods
are not copyrightable (Baker v. Selden; Feist). Every number is cited to the page it was
read on so a reviewer can check it, and no text is reproduced.
"""

# The original top import block, re-done here so every attribute access the single-file
# module answered (pose_limits.os, pose_limits.np, pose_limits.MS, ...) still resolves.
# The sys.path bootstrap it fed runs in .base, which is imported first below.
import fractions
import glob
import json
import os
import sys

import numpy as np

from zyg_workflows import paths as _paths
from zyg_workflows.geom import mesh_skeletons as MS
import logging as _zyg_logging

# The submodules, IN THE ORIGINAL SECTION ORDER, so module-level side effects run in
# the order the single file ran them.
from zyg_workflows.geom.pose_limits.base import (
    _zyg_log,
    SCHEMA,
    ROOT,
    SCRATCH,
    _flag,
    enabled,
    strict_wrist,
    _threads,
    _set_threads,
    MEASURED,
    CANON,
    HOUSE,
    PROVENANCE_RANK,
    PASS,
    WARN,
    FAIL,
    REPORT,
    UNMEASURABLE,
    UNRESOLVED,
    SKIP,
    ERROR,
    STATUSES,
    GATES_STATUS_MAP,
    ROLLUP_RANK,
    rollup,
)
from zyg_workflows.geom.pose_limits.printed import (
    AFS,
    HEADNECK,
    WRIST_EXTENSION_NATURAL_DEG,
    WRIST_EXTENSION_FORCED_DEG,
    WRIST_FLEXION_NATURAL_DEG,
    WRIST_FLEXION_FORCED_DEG,
    WRIST_ULNAR_MAX_DEG,
    WRIST_RADIAL_MAX_DEG,
    WRIST_SOURCE,
    CERVICAL_EXTENSION_TOTAL_MAX_DEG,
    CERVICAL_PER_JOINT_DEG,
    CERVICAL_SOURCE,
    CERVICAL_RIG_JOINTS,
    CERVICAL_MAPPING_NOTE,
    OCCIPUT_C2_MIN_SHARE,
    OCCIPUT_SOURCE,
    SCAPULA_STATIC_BELOW_DEG,
    SCAPULA_SOURCE,
    PRONATION_HUMERUS_ROTATION_MAX_DEG,
    PRONATION_SOURCE,
    ELBOW_OWNER_SOURCE,
    ELBOW_HUMERAL_CONTROL_PATCHES,
    PATELLAR_LIGAMENT_MAX_DRIFT,
    PATELLAR_SOURCE,
    TRANSVERSE_TILT_STDEV_MIN_DEG,
    STIFFNESS_SOURCE,
    TILT_OPPOSITION_REQUIRED_FRACTION,
    TILT_SIGN_ZERO_FLOOR_DEG,
    TILT_SIGN_SENSITIVITY_FLOORS_DEG,
    TILT_OPPOSITION_CANON_FRACTION,
    TILT_OPPOSITION_PROBE_DENOMINATORS,
    _required_opposition,
    opposition_verdict,
    max_same_sign_allowed,
    opposition_rule_drift,
    STIFF_ELBOW_WINDOWS_DEG,
    STIFF_PARALLEL_WINDOWS_DEG,
    ERECT_TRUNK_WINDOWS_DEG,
    ERECT_KNEE_WINDOW_DEG,
    TWIST_STATION_COUNTS,
    ansur_rom_columns,
    canon_may_block,
)
from zyg_workflows.geom.pose_limits.rig import (
    RIG_REQUIREMENTS,
    RIG_EXPECTED_ABSENT,
    bone_roster,
    rig_report,
    rotmat,
    nearest_rotation,
    rot_angle_deg,
    unit,
    signed_angle_deg,
    swing_twist,
    kabsch,
    _RIG,
    _model_index,
    bone_index,
    pose_from_local,
    rig_state,
    rig_numerical_floor,
    local_axis,
    _LONG,
    _joint_ref_axes,
    joint_delta,
    anatomical_frame,
)
from zyg_workflows.geom.pose_limits.skeleton import (
    METRIC3D,
    PSEUDO3D,
    IMAGE2D,
    FRAME_NOTES,
    POSE_JOINTS,
    _RIG_JOINT_MAP,
    _RIG_MIDLINE_MAP,
    Skeleton,
    _rig_joints,
    skeleton_from_rig,
    skeleton_from_pose_aa,
    _blaze_names,
    _BLAZE_MAP,
    skeleton_from_blazepose,
)
from zyg_workflows.geom.pose_limits.rom import (
    _hand_frame,
    wrist_angles,
    elbow_angle,
    knee_angle,
    cervical_angles,
    _res,
    t5_joint_rom,
)
from zyg_workflows.geom.pose_limits.stiffness import (
    _trunk_tilts,
    _p175_error,
    t5_pose_stiffness,
)
from zyg_workflows.geom.pose_limits.pronation import (
    _forearm_skin,
    _twist_profile,
    t5_pronation_isolation,
    pronation_coupling_in_pose,
)
from zyg_workflows.geom.pose_limits.joint_gates import (
    t5_scapula_static,
    _region_group,
    _patch_ownership,
    _frame_residuals,
    _rigid_carry,
    _elbow_owner_rows,
    t5_elbow_owner,
    t5_patellar_ligament,
)
from zyg_workflows.geom.pose_limits.characters import (
    NEUTRAL,
    characters,
    POSE_LIBRARY_ROOT,
    POSE_LIBRARY_CHARACTERS,
    DROP_REASONS,
    _cell_source_image,
    LIBRARY_COMPLETENESS_RULE,
    scan_pose_library,
    load_pose_library,
    fit_mask_defect,
    _check_limit_and_exceedance,
    pose_library_report,
    run_character,
)
from zyg_workflows.geom.pose_limits.pose_layer import (
    POSE_LAYER_SCHEMA,
    POSE_LAYER_SUBJECTS,
    POSE_LAYER_CONTRACT,
    POSE_LAYER_KEYS,
    POSE_LAYER_GATE_KEYS,
    POSE_LAYER_LIBRARY_KEYS,
    POSE_LIBRARY_INTEGRITY_KEYS,
    PoseLayerContractError,
    verify_contract,
    pose_layer,
    run_all,
)
from zyg_workflows.geom.pose_limits.falsification import (
    demo_broken,
    _tilt_control_pose,
    _OPPOSITION_CONTROL_POSES,
    _OPPOSITION_CONTROL_EXPECT,
    _opposition_constant_controls,
)
from zyg_workflows.geom.pose_limits.cli import (
    _fmt_status,
    render_text,
    _jsonable,
    main,
)


__all__ = [
    'fractions',
    'glob',
    'json',
    'os',
    'sys',
    'np',
    '_paths',
    'MS',
    '_zyg_logging',
    '_zyg_log',
    'SCHEMA',
    'ROOT',
    'SCRATCH',
    '_flag',
    'enabled',
    'strict_wrist',
    '_threads',
    '_set_threads',
    'MEASURED',
    'CANON',
    'HOUSE',
    'PROVENANCE_RANK',
    'PASS',
    'WARN',
    'FAIL',
    'REPORT',
    'UNMEASURABLE',
    'UNRESOLVED',
    'SKIP',
    'ERROR',
    'STATUSES',
    'GATES_STATUS_MAP',
    'ROLLUP_RANK',
    'rollup',
    'AFS',
    'HEADNECK',
    'WRIST_EXTENSION_NATURAL_DEG',
    'WRIST_EXTENSION_FORCED_DEG',
    'WRIST_FLEXION_NATURAL_DEG',
    'WRIST_FLEXION_FORCED_DEG',
    'WRIST_ULNAR_MAX_DEG',
    'WRIST_RADIAL_MAX_DEG',
    'WRIST_SOURCE',
    'CERVICAL_EXTENSION_TOTAL_MAX_DEG',
    'CERVICAL_PER_JOINT_DEG',
    'CERVICAL_SOURCE',
    'CERVICAL_RIG_JOINTS',
    'CERVICAL_MAPPING_NOTE',
    'OCCIPUT_C2_MIN_SHARE',
    'OCCIPUT_SOURCE',
    'SCAPULA_STATIC_BELOW_DEG',
    'SCAPULA_SOURCE',
    'PRONATION_HUMERUS_ROTATION_MAX_DEG',
    'PRONATION_SOURCE',
    'ELBOW_OWNER_SOURCE',
    'ELBOW_HUMERAL_CONTROL_PATCHES',
    'PATELLAR_LIGAMENT_MAX_DRIFT',
    'PATELLAR_SOURCE',
    'TRANSVERSE_TILT_STDEV_MIN_DEG',
    'STIFFNESS_SOURCE',
    'TILT_OPPOSITION_REQUIRED_FRACTION',
    'TILT_SIGN_ZERO_FLOOR_DEG',
    'TILT_SIGN_SENSITIVITY_FLOORS_DEG',
    'TILT_OPPOSITION_CANON_FRACTION',
    'TILT_OPPOSITION_PROBE_DENOMINATORS',
    '_required_opposition',
    'opposition_verdict',
    'max_same_sign_allowed',
    'opposition_rule_drift',
    'STIFF_ELBOW_WINDOWS_DEG',
    'STIFF_PARALLEL_WINDOWS_DEG',
    'ERECT_TRUNK_WINDOWS_DEG',
    'ERECT_KNEE_WINDOW_DEG',
    'TWIST_STATION_COUNTS',
    'ansur_rom_columns',
    'canon_may_block',
    'RIG_REQUIREMENTS',
    'RIG_EXPECTED_ABSENT',
    'bone_roster',
    'rig_report',
    'rotmat',
    'nearest_rotation',
    'rot_angle_deg',
    'unit',
    'signed_angle_deg',
    'swing_twist',
    'kabsch',
    '_RIG',
    '_model_index',
    'bone_index',
    'pose_from_local',
    'rig_state',
    'rig_numerical_floor',
    'local_axis',
    '_LONG',
    '_joint_ref_axes',
    'joint_delta',
    'anatomical_frame',
    'METRIC3D',
    'PSEUDO3D',
    'IMAGE2D',
    'FRAME_NOTES',
    'POSE_JOINTS',
    '_RIG_JOINT_MAP',
    '_RIG_MIDLINE_MAP',
    'Skeleton',
    '_rig_joints',
    'skeleton_from_rig',
    'skeleton_from_pose_aa',
    '_blaze_names',
    '_BLAZE_MAP',
    'skeleton_from_blazepose',
    '_hand_frame',
    'wrist_angles',
    'elbow_angle',
    'knee_angle',
    'cervical_angles',
    '_res',
    't5_joint_rom',
    '_trunk_tilts',
    '_p175_error',
    't5_pose_stiffness',
    '_forearm_skin',
    '_twist_profile',
    't5_pronation_isolation',
    'pronation_coupling_in_pose',
    't5_scapula_static',
    '_region_group',
    '_patch_ownership',
    '_frame_residuals',
    '_rigid_carry',
    '_elbow_owner_rows',
    't5_elbow_owner',
    't5_patellar_ligament',
    'NEUTRAL',
    'characters',
    'POSE_LIBRARY_ROOT',
    'POSE_LIBRARY_CHARACTERS',
    'DROP_REASONS',
    '_cell_source_image',
    'LIBRARY_COMPLETENESS_RULE',
    'scan_pose_library',
    'load_pose_library',
    'fit_mask_defect',
    '_check_limit_and_exceedance',
    'pose_library_report',
    'run_character',
    'POSE_LAYER_SCHEMA',
    'POSE_LAYER_SUBJECTS',
    'POSE_LAYER_CONTRACT',
    'POSE_LAYER_KEYS',
    'POSE_LAYER_GATE_KEYS',
    'POSE_LAYER_LIBRARY_KEYS',
    'POSE_LIBRARY_INTEGRITY_KEYS',
    'PoseLayerContractError',
    'verify_contract',
    'pose_layer',
    'run_all',
    'demo_broken',
    '_tilt_control_pose',
    '_OPPOSITION_CONTROL_POSES',
    '_OPPOSITION_CONTROL_EXPECT',
    '_opposition_constant_controls',
    '_fmt_status',
    'render_text',
    '_jsonable',
    'main',
]
