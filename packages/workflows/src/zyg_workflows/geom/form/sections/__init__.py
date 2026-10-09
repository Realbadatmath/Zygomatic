# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""sections.py — cross-section SIGN and ORDERING gates on the anny cage.

WHY THIS MODULE EXISTS
geom.anthro is a LINEAR engine: 42 gates over lengths, breadths, depths, girths and their
ratios. Every one of them is satisfied by a TUBE. A torso whose every horizontal section is
a smooth ellipse of the right width, the right depth and the right circumference passes
t2_breadths_wide, t2_girths_wide, t3_depths_wide and the joint Mahalanobis gate without a
murmur, because a circumference does not know what shape enclosed it. The same is true of a
neck: neck_circumference cannot tell a hexagonal neck with a nuchal furrow and two
sternocleidomastoid ridges from a drainpipe of the same perimeter, and it cannot see the
male-vs-female taper at all, because taper is a DERIVATIVE of a girth and the gate bands a
single girth.

So this module asks the questions a perimeter cannot: at a cross-section, WHICH WAY ROUND
is it, IN WHAT ORDER do the features sit, and HOW MANY of them are there. Every predicate
here is a sign test, an ordering test or an integer count. That is a deliberate design
constraint, not a stylistic one — see THE CALIBRATION RULE below.

THE CALIBRATION RULE, AND WHY THIS FILE HAS ALMOST NO NUMBERS IN IT
A threshold tuned until our own meshes pass is not a gate, it is a rubber stamp. The house
policy is that a threshold must come from OUTSIDE our assets: a printed number, a clinical
range, a survey (ANSUR II / CDC / NHANES), or — best of all — a sign, ordering or invariance
with NO free parameter at all. Everything in this file is in that last class, with exactly
three exceptions, and all three are declared here rather than buried:

  1. THE RELIEF NULL, 2.45e-3 of stature. Measured, not chosen:
     geom.form.curvature.relief_null seeded 298 random patches over the anny neutral's
     torso and limb skin and found |relief/stature| p99 = 2.45e-3 (4.13 mm at S = 1.686 m).
     It is used here ONLY to decide whether a dip or a deviation is BIG ENOUGH TO BE REAL —
     i.e. as this cage's own measurement noise floor — never as an anatomical target. A
     feature below it is reported as unresolved, not as absent.
  2. THE HEXAGON'S OWN CIRCULARITY, 4*pi*A/P^2 = pi*sqrt(3)/6 = 0.906900. This is not a
     tolerance, it is the exact isoperimetric ratio of a regular hexagon. HeadNeck p.106-107
     says the neck section is a hexagon; the strictest possible reading of that claim is
     "at least as far from a circle as a hexagon is", and that reading has no free parameter
     because the constant is a theorem about hexagons.
  3. THE MAJORITY RULE, 0.5 of a vertex's skinning weight. Taken verbatim from
     geom.anthro.measure.ARM_SKIN_WEIGHT_THRESHOLD, which is already shipped and already
     documented there: a point whose majority weight belongs to a segment IS that segment.
     It is a majority, not a tuned cut.

Nothing else in this file is a number that could be moved to change a verdict.

PROVENANCE, AND THE NEW 'CANON' TAG
The three anatomy references are ARTIST CANON, not anthropometry. The build plan's §1.3
establishes a provenance tag CANON ranked strictly below MEASURED, with the rule that a
CANON threshold may never block-fail a quantity for which a MEASURED source exists. Every
claim in this file is tagged, and the tags are honest about what they are:

  CANON     the claim comes from a book page and nowhere else (AFS p.24, p.215, p.216;
            HeadNeck p.106-107, p.172, p.173).
  MEASURED  the number comes from our own measured null (the relief floor) or from the rig.
  GEOMETRY  the number is a theorem (the hexagon's circularity), not an observation.

geom.anthro.gates.VALID_PROVENANCE is currently (MEASURED, HOUSE) and will REFUSE to
register a CANON gate until the plan's §1.3 change lands there. That is correct and
deliberate: these gates are not registered in the anthro engine by this file, and must not
be until the tag exists. This module is standalone and reports its own verdicts.

WHAT WE MEASURED, STATED UP FRONT BECAUSE IT IS THE POINT OF THE EXERCISE
Run 2026-08-06 on the four issued characters plus the anny neutral as CONTROL (main()):

  PASSES
  * width > depth holds at every resolved torso level on every body, 4 or 5 levels each.
    The one thing the linear engine could already have told us is the one thing that is
    fine.
  * the gluteal concavity IS there and it IS posterior: 1-3 resolved concavities at the
    buttock level on every body, deepest 22.8-38.6 mm against a 3.7-4.5 mm floor.
  * the cervical rig chain IS posterior to the neck section centroid, by 17.6-26.0 mm, on
    all five.

  FAILURES, and all five bodies fail all five of them
  * THE LEG COUNTER-CURVE DOES NOT EXIST ON THIS CAGE. The lateral track of the leg's
    section centroids is single-signed on all five bodies and both legs: the residual from
    the ankle-to-crotch chord never crosses zero, peaking at 11.5-16.4 mm of PURE LATERAL
    bow against a 3.7-4.5 mm noise floor, with 17-22 of 25 stations above that floor. AFS
    p.215's alternation is not there; the leg is one bowed tube. Left and right agree to
    0.1 mm, so this is the cage's geometry, not a morph or a slicer artefact.
  * THE CALF IS ASYMMETRIC THE WRONG WAY. AFS p.216 requires the medial gastrocnemius apex
    to be both LOWER and LARGER than the lateral. The medial bulge is 1.9 to 5.0 times
    SMALLER than the lateral on every body (5.1 vs 22.1 mm on the control, 6.7 vs 33.4 on
    the female, 13.0 vs 31.4 on cornelis). The height half of the claim splits: medial
    HIGHER on the male and abel, medial lower on cornelis, and unresolved on the control
    and the female because the two apexes land on the same scan station.
  * THE NECK IS A CIRCLE. Against the regular-polygon family the circle beats the hexagon
    on 5 of 5 bodies, the best-fitting polygon order is 12 — the far end of the family —
    on 5 of 5, and the section circularity is 0.9745-0.9874 against a hexagon's 0.9069.
    There is no hexagon, no sternocleidomastoid ridge pair and no nuchal flattening in
    this cross-section.
  * THE NECK TAPER CARRIES NO SEX SIGNAL, AND WHAT SIGNAL IT HAS POINTS THE WRONG WAY.
    Flipping only the gender macro on the reference recipe moves the taper ratio from
    0.8745 (male) to 0.9245 (female) — the female neck comes out LESS conical, not more,
    against HeadNeck p.172/p.173. Every body's neck narrows upward (ratios 0.798-0.928),
    so the female character passes the weak per-body form of the claim while the paired
    direction test, which is the form with no threshold in it, fails.
  * front-flatter-than-back fails at most torso levels and at the neck on every body. This
    is the least clean of the five results and is labelled as such: AFS p.24's phrase is
    not sharp, three readings of it are computed, and they do not all agree. See
    _split_front_back.

  REFUSALS
  * the suprasternale torso level is REFUSED on four of five bodies because an arm has
    fused into the trunk loop at that height in the A-pose. On the female it resolves but
    the plane sits above her shoulder joint, so what it sections is the shoulder yoke
    (241 x 116 mm) and not a rib cage (322 x 239 mm one level lower); the record says so
    in section_kind rather than letting the number pass as thoracic.

Most of these are properties of the CONTROL as much as of the characters, which is the
whole reason the control is run: a defect the stock anny body shares is anny's, not ours,
and no amount of morph work on a character will fix it. The leg counter-curve, the calf
asymmetry and the neck's circularity are all in that class — they are cage defects and they
want the sculpt layer of the plan's §2, not a parameter change.

WHAT THIS MODULE DOES NOT DO
It does not slice its own planes. Every contour here comes from geom.anthro.measure's
slice_loops / _select_loop / loop_metrics — the same exact, tolerance-free plane-triangle
tracer that produces every shipped girth, with the same arm-mask and merge-refusal rules.
Duplicating that would mean two slicers that could disagree.

It does not touch measure.py, curvature.py or blockout.py, and it registers nothing in
geom.anthro.gates.

DETERMINISM
No random numbers, no optimiser, no seed: the one search in the file (the polygon rotation)
is a fixed 720-step grid. Measured across OMP_NUM_THREADS=1 and 4 the full --json report is
identical in every status and differs only in the last ULP of rig-derived floats (relative
1e-16), because anny's own parallel skinning reductions are not bit-reproducible across
thread counts. That noise is fourteen orders of magnitude below the smallest floor used
here, and no verdict moves.

ROLLBACK
Everything here is new; nothing that already ships changes behaviour because of this file.
The env flag ZYG_FORM_SECTIONS (default '1' = enabled) exists anyway so that a caller that
starts consuming evaluate() can be switched off without a code edit: with
ZYG_FORM_SECTIONS=0 every gate returns status 'not_applicable' with the flag named in the
explanation, and no geometry is touched.
"""

# ruff: noqa: F401  this __init__ is a re-export surface: it rebinds every name the
# single-file sections.py defined (public and underscore, imports included) so that no
# importer anywhere needs editing, and it imports the section modules in the original
# top-to-bottom order so module-level side effects still run in that order.
from .constants import (
    contextlib,
    json,
    math,
    os,
    sys,
    np,
    MS,
    LMK,
    MEA,
    SCHEMA,
    ENV_FLAG,
    ENV_FLAG_DEFAULT,
    enabled,
    PASS,
    FAIL,
    WARN,
    REPORT,
    UNMEASURABLE,
    NOT_APPLICABLE,
    CANON,
    MEASURED,
    GEOMETRY,
    HOUSE,
    RELIEF_NULL_FRAC,
    HEXAGON_CIRCULARITY,
    SEGMENT_MAJORITY,
    NGON_ORDERS,
    NGON_THETA_STEPS,
    SRC_TORSO,
    SRC_LEG,
    SRC_CALF,
    SRC_NECK_HEX,
    SRC_NECK_TAPER,
    SRC_NULL,
    PREDICATES,
)
from .primitives import (
    _res,
    _plane_xy,
    frame_check,
    _menger_curvature,
    _polygon_area,
    _split_front_back,
    _hull_gaps,
    _ngon_residual,
    _shape_family,
    _frame,
    _RIG,
    bone_ends,
    segment_weight,
    _section,
    _torso_section_valid,
    _ORDER,
    _rollup,
)
from .torso import (
    TORSO_LEVELS,
    t5_torso_sections,
)
from .neck import (
    NECK_BONE_SUBSTRINGS,
    _cervical_axis,
    t5_neck_section,
    neck_taper,
    neck_taper_dimorphism,
)
from .limbs import (
    t5_leg_counter_curve,
    t5_calf_asymmetry,
)
from .entry import (
    evaluate,
    _synth,
    self_test,
)
from .cli import (
    _mark,
    _stdout_to_stderr,
    main,
    _run,
    _print_report,
)
