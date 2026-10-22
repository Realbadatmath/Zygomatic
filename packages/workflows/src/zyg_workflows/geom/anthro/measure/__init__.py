# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""measure.py — pull ISO-shaped measurements off an anny cage without inventing any.

WHY THIS MODULE EXISTS
A mesh will hand you a number for anything you ask. The danger is not that the arithmetic
is wrong, it is that the number answers a DIFFERENT QUESTION from the survey table you are
about to compare it to. Four traps produce almost all of the error, and this file is
organised around refusing each one:

 1. THE GIRTH CONVENTION. anny's own Anthropometry.waist_circumference sums straight
    chords along a fixed 46-vertex ring (read the vendor source: torch.roll then a norm
    sum). That is a POLYLINE through mesh vertices. ANSUR II circumferences are a taut
    tape on a live body. SHAPY / A2B / CALVIS and ISO 18825-2 emulate the tape with a
    PLANE SLICE plus the CONVEX HULL of the intersection contour. Three different numbers
    exist for one "waist"; this module computes all three, labels each, and only the hull
    number is ever compared to a survey band.

    THE DIRECTION OF THAT BIAS IS NOT WHAT THE BRIEFING ASSUMED, AND WE MEASURED IT.
    The briefing states hull >= true contour >= polyline. Over 125 site-character
    combinations (25 girth sites on the four issued characters plus the stock anny body)
    both inequalities come out the other way:
      * hull <= contour held 125/125, by 0.0 to 46.9 mm (mean 4.5). This one is a THEOREM,
        not a finding — the convex hull is the shortest closed curve enclosing a plane
        curve, so a section that dips into a concavity is longer than the tape that
        bridges it.
      * hull >= polyline held 1/125. The vendor's own function is the cleanest evidence:
        anny.anthropometry.waist_circumference returns 903.79 mm on the male original
        where our hull at the same ring is 870.75 mm — the vendor polyline is 33.0 mm
        LONGER (and 15.6 / 3.6 / 7.2 / 33.9 mm longer on the stock body, the female, abel
        and cornelis). A vertex ring is inscribed only if it is planar, and a cage ring is
        not: it undulates 8.2-40.2 mm out of the slice plane, and a 3D chord sum charges
        for that undulation. Flattening the same ring into the plane removes most of it
        (mean excess falls from 65.8 mm to 11.6 mm) but not all — the ring sits below the
        cut where the body is often wider — so it is both effects, and
        compare_conventions() separates them.
    The practical rule survives: never compare a MakeHuman/anny girth to a survey
    circumference. But the reason is that it runs LONG on this cage, not short, so a
    pipeline that "corrects" for an assumed underestimate would double the error.

 2. THE PLANE ORIENTATION. ISO 18825-2 takes limb girths PERPENDICULAR TO THE LIMB AXIS
    and torso girths horizontally. On an A-posed arm those are not close: the abduction
    angle enters as 1/cos. Both are computed here for every limb site, both are reported,
    and the survey comparison uses whichever convention the survey used (ANSUR calf and
    thigh girths are horizontal-tape measurements; ISO 18825-2 scan-extracted ones are
    perpendicular). A limb girth without its plane convention is not a measurement.

 3. THE ATTACHED ARMS. A naive "max lateral extent at shoulder height" measures the
    forearm, not the torso — this is the trap that broke this project's earlier
    calibration. Three independent mechanisms guard it here, and 2026-08-05 they were
    measured against each other rather than assumed:

    (a) TOPOLOGY. A horizontal plane through an A-posed body cuts the torso and each arm
        as SEPARATE CLOSED LOOPS, so selecting the torso loop excludes the arms by
        construction, with no magic x-window to tune.
    (b) THE SKINNING-WEIGHT ARM MASK (arm_skin_weights, added 2026-08-05). Every contour
        point carries the summed rig weight of the arm bones — upperarm / lowerarm /
        wrist / hand / finger / thumb / metacarpal, with clavicle and shoulder01 KEPT
        because they carry genuine shoulder breadth — interpolated along its own crossing
        edge, and a point at or above 0.5 is arm and is dropped from every torso and head
        breadth, depth and girth. This is the technique geom/fit_reference.py::_kept_mask
        already uses to keep the reference's lowered arms out of the chamfer fit.
        MEASURED RESULT, AND IT IS A NEGATIVE ONE: across the four issued characters plus
        the stock body the mask drops ZERO points at every torso and head site, because
        (a) had already excluded the arms. The mask therefore changes no number that this
        module currently emits. It is a guarantee that survives a pose or a morph in which
        (a) stops holding, not a correction — and saying otherwise would be a fiction.
    (c) THE MERGE REFUSAL. If arm surface is present in the selected torso loop and both
        arms are NOT accounted for as loops of their own, the arm has fused to the trunk,
        the trunk section is no longer closed, and a GIRTH is undefined there: it is
        REFUSED, never clamped. A breadth or depth is still well defined on the arm-free
        points and is emitted from them.

    WHAT THE ARM MASK DOES NOT FIX, AND THIS IS THE IMPORTANT PART. The arms being out of
    the loop does not put the trunk on the survey's convention. anny's rest pose abducts
    the humerus 39.4-42.3 degrees (measured from the rig, all five bodies), and the
    axillary tissue is partly bound to the humerus — the vertices that set chest breadth
    at thelion carry 0.21-0.23 of arm weight — so abduction stretches the trunk silhouette
    itself sideways. Re-posing the rig to bring each humerus vertical (an actual re-pose,
    not a model) moves the trunk, measured at the same plane on the same body:
        chest breadth at thelion   -6.8 / -10.1 / -18.5 / -36.9 / -44.0 mm
        chest girth  at thelion   -10.3 / -10.6 / -17.1 / -44.3 / -50.4 mm
        chest depth               -0.6 mm or less    waist, buttock: 0.0 mm exactly
    for female / abel / stock / male / cornelis. Against an ISO 20685-1 breadth tolerance
    of 4 mm that is a real convention error, so every horizontal site now carries
    a_pose_bias_mm: a per-mesh, linear-blend-skinning estimate of that shift, computed
    from this cage's own rig weights about anny's own COCO shoulder centres. It was
    validated against the genuine re-pose above and OVER-corrects: the genuine shift is
    79-97% of it on the trunk, so it is an UPPER BOUND ON THE MAGNITUDE and is labelled as
    one (a lower bound was the first thing assumed here and the validation said the
    opposite). At bideltoid level the genuine shift is only 74-80% of the estimate, and
    the estimate would move the male's bideltoid inside the population band where the
    genuine re-pose leaves it outside — which is why bideltoid breadth and shoulder
    circumference are NOT rescued by it and stay NOT SURVEY-COMPARABLE. Nothing here is
    corrected in place: the measured value is the A-posed body, the bias is reported
    beside it, and what to do about it is the gate's decision, not the ruler's.

 4. THE SITE THAT DOES NOT EXIST. "waist" is not one place. WHO/IDF use the rib-iliac
    midpoint, NIH/NHANES the iliac crest, ANSUR the omphalion, and the WHO and NIH sites
    differ by up to 10.1 cm in women. This cage HAS no tenth rib and no iliac crest
    (landmarks.py resolves neither, with the evidence), so the WHO and NIH waists are
    emitted as UNMEASURABLE with the reason attached rather than substituted. Every waist
    that IS emitted carries its site in its name. There is no key called 'waist'.

WHAT ISO 20685-1 DOES AND DOES NOT SAY HERE
Every measurement carries the Table 4 class it would belong to, and the maximum allowed
MEAN difference for that class. Table 4 bounds a mean difference across a validation
sample, NOT a per-mesh error. Applying it per mesh is HOUSE policy and is labelled as
such in every record. It is also worth remembering that a real person's stature varies
14.4-19.3 mm over a day, so "this mesh is anthropometrically accurate to 4 mm" is not a
meaningful claim about a body; "this mesh is within 2 mm of its DECLARED BUILD TARGET" is,
and is a different statement.

NOTHING HERE EVALUATES WHETHER A BODY IS CORRECT. It reports what the mesh measures, on a
stated convention, with the landmark that produced it.
"""

import json
import math
import os
import sys
import time

import numpy as np

# The old measure.py sat one directory higher than this package __init__, so the path
# it inserted is four dirnames up from here and three from there — the same directory.
sys.path.insert(
    0,
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))),
)

from zyg_workflows.geom import mesh_skeletons as MS  # noqa: E402
from zyg_workflows.geom.anthro import landmarks as LMK  # noqa: E402
import logging as _zyg_logging

# The sections of the old single-file measure.py, imported in their original order.
from zyg_workflows.geom.anthro.measure.constants import (
    _zyg_log,
    CAGE_VERTS,
    CAGE_FACES,
    BODY_DENSITY_KG_M3,
    ANNY_VENDOR_DENSITY_KG_M3,
    ISO_20685_1_TABLE4_MM,
    ISO_CAVEAT,
    POSE_HAND_FRAC_STATURE,
    POSE_HALFSPAN_FRAC_STATURE,
    MIRROR_MAP_VALIDITY_MAX_MM,
    MIRROR_MAP_ADVISORY_MM,
    PLANE_NUDGE_M,
    PLANE_DEGENERATE_M,
    SCAN_STEP_FRAC,
    ARM_MASK_LABELS,
    ARM_BONE_SUBSTRINGS,
    ARM_BONE_KEEP_SUBSTRINGS,
    ARM_SKIN_WEIGHT_THRESHOLD,
)
from zyg_workflows.geom.anthro.measure.topology import (
    _TOPO,
    _ARM_SKIN,
    arm_skin_weights,
    _split_arm_points,
    _arm_mask_record,
    _vendor_triangles,
    _topology,
)
from zyg_workflows.geom.anthro.measure.slicing import (
    slice_loops,
    _plane_basis,
    _shoelace,
    loop_metrics,
    polyline_girth,
    _select_loop,
    _arm_merge_check,
)
from zyg_workflows.geom.anthro.measure.anchors import (
    _ring_anchor,
    _ear_top_frac,
    _band,
    _limb_axes,
)
from zyg_workflows.geom.anthro.measure.tables_girth import (
    GIRTH_SITES,
)
from zyg_workflows.geom.anthro.measure.tables_extent import (
    BREADTH_SPEC,
    DEPTH_SPEC,
    HEIGHT_SPEC,
    LENGTH_SPEC,
    UNMEASURABLE,
)
from zyg_workflows.geom.anthro.measure.primitives import (
    _girth_at,
    _scan_girth,
    _extent_scan,
    _rodrigues,
    adducted_copy,
    check_pose_and_frame,
    body_volume,
)
from zyg_workflows.geom.anthro.measure.record import (
    _rec,
    HULL_CONVENTION,
    POLYLINE_CONVENTION,
    _anchor_point,
)
from zyg_workflows.geom.anthro.measure.mesh import (
    measure_mesh,
)
from zyg_workflows.geom.anthro.measure.sites import (
    _girth_site,
    _attach_pose_bias,
    _extent_measure,
)
from zyg_workflows.geom.anthro.measure.ratios import (
    _ratios,
)
from zyg_workflows.geom.anthro.measure.conventions import (
    compare_conventions,
)
from zyg_workflows.geom.anthro.measure.selftest import (
    _selftest_topology,
    _age_years,
    _cases,
    _fmt,
    _arm_mask_summary,
    main,
)

__all__ = [
    'json',
    'math',
    'time',
    'np',
    'MS',
    'LMK',
    '_zyg_logging',
    '_zyg_log',
    'CAGE_VERTS',
    'CAGE_FACES',
    'BODY_DENSITY_KG_M3',
    'ANNY_VENDOR_DENSITY_KG_M3',
    'ISO_20685_1_TABLE4_MM',
    'ISO_CAVEAT',
    'POSE_HAND_FRAC_STATURE',
    'POSE_HALFSPAN_FRAC_STATURE',
    'MIRROR_MAP_VALIDITY_MAX_MM',
    'MIRROR_MAP_ADVISORY_MM',
    'PLANE_NUDGE_M',
    'PLANE_DEGENERATE_M',
    'SCAN_STEP_FRAC',
    'ARM_MASK_LABELS',
    'ARM_BONE_SUBSTRINGS',
    'ARM_BONE_KEEP_SUBSTRINGS',
    'ARM_SKIN_WEIGHT_THRESHOLD',
    '_TOPO',
    '_ARM_SKIN',
    'arm_skin_weights',
    '_split_arm_points',
    '_arm_mask_record',
    '_vendor_triangles',
    '_topology',
    'slice_loops',
    '_plane_basis',
    '_shoelace',
    'loop_metrics',
    'polyline_girth',
    '_select_loop',
    '_arm_merge_check',
    '_ring_anchor',
    '_ear_top_frac',
    '_band',
    '_limb_axes',
    'GIRTH_SITES',
    'BREADTH_SPEC',
    'DEPTH_SPEC',
    'HEIGHT_SPEC',
    'LENGTH_SPEC',
    'UNMEASURABLE',
    '_girth_at',
    '_scan_girth',
    '_extent_scan',
    '_rodrigues',
    'adducted_copy',
    'check_pose_and_frame',
    'body_volume',
    '_rec',
    'HULL_CONVENTION',
    'POLYLINE_CONVENTION',
    '_anchor_point',
    'measure_mesh',
    '_girth_site',
    '_attach_pose_bias',
    '_extent_measure',
    '_ratios',
    'compare_conventions',
    '_selftest_topology',
    '_age_years',
    '_cases',
    '_fmt',
    '_arm_mask_summary',
    'main',
]
