# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

# this module IS the re-export namespace of the pre-split fit_proportions.py.

"""fit_proportions.py — re-fit the ORIGINALS against the ANSUR-II ratios that are
FAILING, without giving up the reference-cloud surface fit.

    python -m zyg_workflows.geom.fit_proportions --sex male --sex female --out /path/fit.json
    python -m zyg_workflows.geom.fit_proportions --bake /path/fit.json          # writes the recipes

WHY THIS EXISTS.  The third issue of the originals (geom/fit_reference.py, a trimmed
chamfer fit against the Blender Studio CC0 realistic bodies) landed both originals with
legs too short for the survey:

    crotch_height_over_stature   male 0.4553 (z -1.86, p2.7)   female 0.4485 (z -2.10, p1.5)

The FOURTH issue fixed that (male z -0.02, female z -0.04) and was blamed for breaking
other things.  The blame was partly misplaced, and the arithmetic is worth stating because
it is real: STATURE IS PINNED.  The male's crotch went 842.49 -> 890.29 mm, so the 1007.8
mm above it had to become 959.8 mm.  Forty-eight millimetres had to come out of the upper
body; that amount was never negotiable, only where it came from.  The fourth issue took it
from the neck and the torso — measure-napetowaist-dist -0.42, measure-waisttohip-dist
-0.45, torso-scale-vert -0.32, measure-neck-height -0.15.

BUT THE MEASUREMENT DOES NOT SUPPORT THE STORY THAT THIS IS WHAT CRASHED THE MALE'S
TORSO HEIGHTS.  The fourth issue also introduced the bony_relief layer, which the third
issue did not carry, and that layer is what moved the landmark.  Measured on the fourth-
issue recipe, changing NOTHING except dropping the layer:

    suprasternale_height_over_stature   0.8082 (z -1.54, p6.4)  ->  0.8159 (z -0.45, p32.5)
    cervicale_height_over_stature       0.8530 (z -1.64, p5.0)  ->  0.8607 (z -0.48, p32.2)

That is +1.09 sd, or 14.2 mm of suprasternale height, from the layer alone.  The third
issue sat at p40.9.  So of the 34-percentile fall, roughly 1.09 sd came from bony_relief
depressing the jugular-notch landmark and roughly 0.22 sd from the torso morph cuts —
a 5:1 split the other way round from the diagnosis this pass was handed.

THE FIFTH ISSUE therefore: keeps the leg fix, drops bony_relief from both bodies, stops
letting the chamfer vote on leg length at all, and moves a shape lever ONLY where a
survey-comparable MEASURED ratio is genuinely outside its band by more than the build's own
resolution.  On the male that turns out to be nowhere: the relief drop restores his torso
heights on its own, and no head morph moves.  On the female it is chest_breadth.

  * KEPT: crotch_height_over_stature at the ANSUR population MEAN (z = 0).  Not "just
    inside the band" — tuning a body until it clears a threshold by a hair is the same
    defect as tuning the threshold.  The population median is the only non-arbitrary
    point on the distribution, and it is the target for every constraint in this file.
  * NOT TARGETED, deliberately: head count / heads-tall.  It has no survey source
    (measure.py says so at head_height_vertex_menton: "HOUSE CONSTANT WITH NO SURVEY
    SOURCE"); it is CANON, and CANON may not drive a blocking change.  Whatever the head
    count becomes is a consequence and is reported as one.

=========================  THE PROVENANCE GATE ON THE TARGETS  =========================

A change may be DRIVEN only by a MEASURED ratio that is failing.  `steer_decision()`
enforces that IN CODE, on the delivered mesh, before a single parameter moves.  A lever is
released only if its target passes FOUR tests, none of which is a taste knob:

  1. survey_comparable is True, the numerator's provenance is MEASURED, and the record
     carries no at_window_endpoint flag;
  2. the value is OUTSIDE the p5-p95 band of the reference pack;
  3. the band excess, in mm at delivered stature, is larger than OUTER_TOL_MM — the
     tolerance the build itself holds stature to (gates.BUILD_TARGET_STATURE_TOL_MM,
     2.0 mm).  A failure smaller than that is inside the build's own resolution;
  4. the band excess is larger than the |a_pose_bias_mm| the measurement itself reports.
     If it is not, then the POSE CONVENTION and not the geometry is what is outside the
     band, and sculpting the body would be correcting the wrong thing.

Test 4 is what separates the two chest failures.  The male's chest_circumference is 7.8 mm
past the band edge and carries a -55.5 mm A-pose bias (arms-down estimate z +1.12, well
inside the band): not steered.  The female's chest_breadth is 17.8 mm past the edge and
carries a -7.8 mm A-pose bias (arms-down z +2.27, still outside): steered.

Four quantities that this pass was handed as evidence do NOT clear test 1, and the
measurement layer is the one saying so:

  head_length_over_stature   male 0.1241, p98.3.  survey_comparable=FALSE — "ANSUR head
      length is measured over hair; this cage is bald, and the maximum AP extent over the
      cranial band is only a HOUSE stand-in for the glabella-occiput line".  Worse, its
      own scan profile is monotonically DECREASING from the band floor (229.53 mm at
      0.96036 of stature down to 116.57 mm at 0.99436) and the record carries
      at_window_endpoint=True with "NO INTERIOR MAXIMUM ... this number is the extent AT
      the band floor and is a property of the window, not of the body".  The band floor is
      itself derived from the ear morph support, so ANY head morph moves the window.
      Targeting it would be sculpting a skull to move a search-window artefact.
      => head-scale-depth-incr is NOT a lever.  head_length is reported, never targeted.

  cervicale_height_over_stature   male p5.0.  The direct landmark is UNMEASURABLE on this
      cage ("the posterior midline profile is monotone from 0.76 to 0.92 of stature with
      no vertebra prominens").  What is measured is cervicale_height_house =
      suprasternale + 0.0448 of stature, provenance HOUSE.  It is not a second, INDEPENDENT
      witness to the short torso — it is suprasternale plus a constant, which is why its z
      tracks suprasternale's to within 0.10 sd everywhere in the jacobian and why both
      recovered by the same 1.09 sd when bony_relief came off.
      => reported as a consequence, never targeted.

  head_breadth_over_stature   survey_comparable=FALSE — "measured over hair; this cage is
      bald".  It is p63.9 and fine anyway.  => head-scale-horiz-incr is not a lever.

  hand_length_over_stature   male 0.1205, p98.6.  survey_comparable=FALSE — "the proximal
      end is a girth-ring centroid, not the stylion line where ANSUR hand length starts,
      so part of the excess is definitional and cannot be separated from a genuinely long
      hand".  This is an independent, measurement-layer confirmation of the standing
      instruction that hands and feet are never free parameters: see LOCKED_SUBSTRINGS,
      which is asserted against every free set in this file.

=========================  THE FREE SETS  =========================

INNER (torch, differentiable, chamfer + crotch) — unchanged from the fourth issue:

    phenotype  proportions
    locals     measure-upperleg-height-incr, measure-lowerleg-height-incr,
               measure-napetowaist-dist-incr, measure-waisttohip-dist-incr,
               torso-scale-vert-incr, measure-neck-height-incr

OUTER (derivative-free, solved against the REAL gate measurement of the DELIVERED mesh).
Each candidate declares its own levers, and those levers move ONLY if steer_decision()
releases them:

    male     suprasternale_height_over_stature  <- head-scale-vert-incr
             chest_circumference_over_stature   <- (no lever declared: see below)
    female   chest_breadth_over_stature         <- torso-vshape-incr, torso-scale-depth-incr
             suprasternale_height_over_stature  <- (no lever declared)
             held in the same least squares: chest_circumference, chest_depth

Lever selection is measured, not chosen by taste.  For the female, three morphs move chest
breadth; the one used is the most breadth-SELECTIVE of them, i.e. the largest
d(chest_breadth z) per unit of d(chest_circumference z), because chest_circumference is
already at z -0.026 and must not be spent:

    torso-vshape-incr      2.042 / 0.498 = 4.10      <- used
    torso-muscle-dorsi     3.011 / 1.074 = 2.80
    torso-scale-horiz      2.966 / 1.077 = 2.75      (also needs -0.88, past the +/-0.8 cap)

A candidate with no declared lever is a candidate this pass has decided it cannot fix
without re-opening geometry that is out of scope; if steer_decision() ever releases one,
the run RAISES rather than silently ignoring a failing MEASURED ratio.  That is the point:
the refusal is recorded and checked, not assumed.

=========================  THE DO-NO-HARM GUARD  =========================

band_regressions() is the contract of a repair pass: no survey-comparable MEASURED ratio
that was INSIDE its p5-p95 band before the fit may be outside it after.  It is checked on
the delivered mesh, and if it trips, the unrestricted solve is DECLINED — the run re-solves
with the whole leg/torso free set frozen at its issued value and only the released outer
levers moving, then checks again, and raises if that still fails.

This is not hypothetical.  On the female, the unrestricted re-fit improves the surface fit
(full-body chamfer 11.16 -> 10.96 mm forward) and puts chest_breadth exactly on the mean,
but it also relaxes the leg-length morphs by 0.17-0.22, which drops the height axis, which
shrinks the FEET — and foot_length_over_stature crosses from p9 to outside the band.  Feet
and hands are in no objective at all (fit_reference masks them out of the chamfer by
skinning weight, and no ratio steers them), and this pass may not make them free
parameters, so the only correct answer is to decline the improvement.  Her recipe is
therefore the fourth issue's leg/torso set, unchanged, plus the chest correction.  The
male's unrestricted re-fit passes the guard and is kept.

Everything else stays at the value fit_reference produced and the operator approved by
eye.  Girths, breadths, the pectoral and shoulder nudges, the breast block: untouched.

=========================  THE CHAMFER'S LEG-LENGTH AXIS  =========================

The chamfer reference is WRONG on leg length and this file does not trust it there.
Measured on the CC0 Blender Studio bodies with the landmark table's own crotch rule, they
score crotch_height_over_stature 0.4320 male (z -3.51, p0.02) and 0.4637 female (z -1.09).
The fourth issue needed an 8x constraint weight to overcome a surface objective that was
actively pulling the male's legs AWAY from the survey.

NEUTRALISATION, exactly: every vertex of ours below OUR crotch, and every reference point
below the REFERENCE's own crotch, is dropped from both chamfer terms.  The objective
therefore sees the whole upper body at true unit-height scale — torso length and head size
included, so nothing about the part of the body this pass is repairing is hidden from it —
and sees nothing at all about how long the legs are.  Leg length is governed by the ANSUR
constraint alone.  No warp, no reweighting, no anisotropy: a region is either in the
objective or it is not.  The only free parameters acting below the crotch are the two leg
LENGTH morphs, whose axis is the distrusted one; every leg girth (thigh, calf, knee,
upperleg-scale) is held at its eye-approved value and so loses no objective it was using.
The full-body chamfer is still MEASURED and reported at every snapshot, so the price of the
fix stays comparable with the numbers recorded for the third and fourth issues.

HEIGHT.  build_originals() re-solves the height axis by binary search after the morphs are
baked, and the MakeHuman height macro is not a uniform scale — it moves the leg/torso ratio
itself.  So the fit is run inside an OUTER loop: calibrate height for the current recipe,
fit the subspace at that fixed height, measure the delivered mesh, step the outer levers,
repeat.  Nothing here bakes anything by accident: it emits JSON, and `--bake` is a separate
command that writes geom/mesh_skeletons.py and then re-parses it off disk (ast for the
literals, a fresh subprocess import for the semantics) and asserts equality with the JSON.
"""

import argparse
import ast
import json
import math
import os
import subprocess
import sys
import tempfile

import numpy as np

from zyg_workflows.geom import fit_reference as FR
from zyg_workflows.geom import mesh_skeletons as MS
from zyg_workflows.geom.anthro.reference import reference
import logging as _zyg_logging

from .core import (
    _zyg_log,
    SCHEMA,
    INNER_TARGET,
    TARGET_Z,
    RATIO_Z_TOL,
    OUTER_TOL_MM,
    _OUTER_TOL_SOURCE,
    PRIMARY,
    HOLD,
    OUTER,
    LOCKED_SUBSTRINGS,
    FREE_PHEN,
    FREE_LOCALS,
    HELD_HEAD,
    ISSUE_ANATOMY,
    ANATOMY_SYMBOLIC,
    ANATOMY_DROPPED,
    REF_GLB,
    OUTER_ROUNDS,
    INNER_ITERS,
    LR,
    FD_STEP,
    _CROTCH_SPEC,
    crotch_spec,
    crotch_index,
    crotch_frac,
    cloud_crotch_frac,
    _atanh_of,
    delivered_mesh,
    measure_ratios,
    ratio_z,
    steer_decision,
    _assert_locked,
    declared_levers,
    _assert_held,
)
from .fit import (
    band_regressions,
    fit_sex,
    snapshot_at,
    REPORT_RATIOS,
    report_ratios,
)
from .baking import (
    print_delta,
    _fmt_dict,
    _literal_by_sex,
    _replace_assign,
    _module_dicts,
    bake,
    main,
)

__all__ = [
    'argparse',
    'ast',
    'json',
    'math',
    'os',
    'subprocess',
    'sys',
    'tempfile',
    'np',
    'FR',
    'MS',
    'reference',
    '_zyg_logging',
    '_zyg_log',
    'SCHEMA',
    'INNER_TARGET',
    'TARGET_Z',
    'RATIO_Z_TOL',
    'OUTER_TOL_MM',
    '_OUTER_TOL_SOURCE',
    'PRIMARY',
    'HOLD',
    'OUTER',
    'LOCKED_SUBSTRINGS',
    'FREE_PHEN',
    'FREE_LOCALS',
    'HELD_HEAD',
    'ISSUE_ANATOMY',
    'ANATOMY_SYMBOLIC',
    'ANATOMY_DROPPED',
    'REF_GLB',
    'OUTER_ROUNDS',
    'INNER_ITERS',
    'LR',
    'FD_STEP',
    '_CROTCH_SPEC',
    'crotch_spec',
    'crotch_index',
    'crotch_frac',
    'cloud_crotch_frac',
    '_atanh_of',
    'delivered_mesh',
    'measure_ratios',
    'ratio_z',
    'steer_decision',
    '_assert_locked',
    'declared_levers',
    '_assert_held',
    'band_regressions',
    'fit_sex',
    'snapshot_at',
    'REPORT_RATIOS',
    'report_ratios',
    'print_delta',
    '_fmt_dict',
    '_literal_by_sex',
    '_replace_assign',
    '_module_dicts',
    'bake',
    'main',
]
