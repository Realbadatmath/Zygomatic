# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""angles.py — ANGLES WITH PRINTED BANDS, and an honest record of which of them this cage
cannot carry.

WHY THIS MODULE EXISTS
geom/anthro/ is linear-only by design: every one of its 42 gates is a length, a breadth, a
girth or a quotient of two of those. geom/form/relational.py opened a six-predicate
beachhead into angles, but every threshold in it is a PERCENTILE OF OUR OWN MORPH SPACE —
the file says so itself ("a threshold here is a PERCENTILE OF THE FORM SAMPLE"). That is
the correct answer when nobody has published a number, and it is the wrong answer when
somebody has. The three anatomy references supply a dozen angles WITH NUMBERS, which is
exactly the evidence class we lacked, and this file is where those numbers live.

PROVENANCE: EVERY BAND IN THIS FILE IS 'CANON'.
A CANON threshold is a number printed in an artist-anatomy reference. It ranks BELOW
'MEASURED' (ANSUR II / CDC / NHANES survey data) and the ranking has teeth: a CANON
threshold may never block-fail a quantity for which a MEASURED source exists. None of the
seven angles here has a MEASURED source on disk — ANSUR II is entirely linear — so CANON is
the best evidence available for all of them, and that is stated per band rather than
assumed. Book and page are carried in the code beside every number.

THE RESOLUTION TEST, AND WHY IT HAS NO FREE PARAMETER
The trap this file is built around is the one relational.py names: "a form gate that
measures the wrong patch will CONFIDENTLY PASS A DEFORMED BODY". An angle is worse than a
length in this respect, because an angle can be constructed several defensible ways from
the same mesh and the constructions need not agree. So every angle here is computed by TWO
OR MORE independent operationalisations, and the rule is:

    AN ANGLE IS RESOLVED ONLY IF THE SPREAD BETWEEN ITS OPERATIONALISATIONS IS SMALLER
    THAN THE WIDTH OF THE NARROWEST PRINTED BAND FOR THAT QUANTITY.

That threshold comes from OUTSIDE our assets — it is the book's own band width — and it has
exactly the right meaning: our construction ambiguity must be smaller than the distinction
the book is asking us to make. If four ways of locating gonion put the gonial angle
anywhere from 74 to 153 degrees, no amount of averaging turns that into a 100-120 versus
120-140 sex call, and reporting a number would be fabrication. Nothing here is ever widened
to make our own bodies pass; when our mesh fails, that is the finding.

WHAT RESOLVED AND WHAT DID NOT (measured on the anny neutral plus the four issued
characters, 2026-08-06 — reproduce with `python -m zyg_workflows.geom.form.angles --characters`)

  RESOLVED  canthal tilt (medial -> lateral canthus, coronal), on all five bodies, at an
            operationalisation spread of 0.01-2.55 degrees against a 10 degree tolerance.
            Anchored on MakeHuman's own two eye-corner targets, whose supports MEASURE as
            one lateral (|x| 38.2-51.0 mm) and one medial (|x| 7.8-28.0 mm) — so which is
            which is a measurement, not a reading of the label. Measured: neutral -0.11,
            female +1.60, male +4.87, abel +1.06, cornelis +2.56 degrees. The CEILING half
            of HeadNeck p.43 (<= +10) resolves and passes on every body with at least a
            factor of two in hand. The SIGN half ("slightly positive") does NOT resolve on
            the neutral, where the two anchor conventions straddle zero by 2.55 degrees;
            that is reported rather than settled by picking the flattering convention.
  RESOLVED  ear-axis / nose-dorsum parallelism (HeadNeck p.69), on all five bodies, spread
            3.14-5.84 against an 8 degree tolerance. Two independent ear SCALE targets agree
            to 0.01 degrees on the ear's long axis, and the nose dorsum is the chord between
            two turning points of the midsagittal profile. It resolves AND IT FAILS on every
            body we ship — see the finding below.
  RESOLVED  the sagittal profile turning points themselves (pronasale, subnasale, labiale
            superius, nasion, glabella), on all five bodies, with prominences of 1.7-20.9 mm
            so none of them is a single vertex of noise. They are the first head landmarks
            in this repo that are neither morph supports nor coordinate extrema but the
            profile's OWN local maxima and minima, in the manner lumbar_curvature() reads a
            spine.

  UNRESOLVED  GONIAL ANGLE — and this is the expensive one, because HeadNeck p.15 and
            FacialExpr p.26 print it independently and its adult male and female bands touch
            only at 120, which would have made it the sharpest sex gate in the corpus. There
            is no mandible on this cage. MakeHuman's 'jaw' bone is a SINGLE midline hinge
            segment from the temporomandibular pivot straight to the chin: it carries the
            condylion-menton CHORD and no gonial corner at all. The skinning weight that
            names "the jaw" reaches 54 mm BELOW menton on the midline at its loosest cut,
            i.e. it contains upper-neck skin, so sweeping its threshold walks gonion across
            the neck and the angle over 74.3-153.2 degrees on the neutral (spread 78.9
            against a 15 degree band width) and 45.6-70.2 on the four characters. Measured,
            in gonial_angle().
  UNRESOLVED  SUBCOSTAL ANGLE (AFS p.13, M ~90 / F ~60 — a 30 degree dimorphism signal).
            It needs a costal margin. landmarks.py already reports tenth_rib UNRESOLVED
            because "this cage has no costal margin"; this module re-derives that from the
            other direction with a relief sweep of the subcostal window — MEASURED, 0 of
            346 probed vertices clear the cage's own relief p99 on the neutral, the
            strongest being +1.14 mm at contrast 1.11 against a required +4.13 mm and 3.70,
            and the same sweep returns 0 of 348 on the female and 0 of 325 on abel — and
            adds the vocabulary measurement: of anny's 256 local-change labels, 'costal',
            'rib', 'xiph', 'sternum' and 'thorax' match ZERO targets.
  UNRESOLVED  CARRYING ANGLE (AFS p.176, 5-15 degrees, F > M) as an ABSOLUTE band, for two
            preconditions this cage fails and one it cannot report: the elbow is FLEXED
            38.3 degrees in the A-pose (the angle is defined at extension), the forearm's
            pronation state is unreadable (regions.py measured that), and the elbow flexion
            axis is only resolvable to about 11 degrees, which flips the SIGN of the
            decomposed value: the two operationalisations read +3.93 and -6.99 degrees on
            the neutral. The DIRECTION half (female > male) is reported instead, because
            every body we issue shares one rest pose so the error is common-mode — and it
            DISAGREES WITH ITSELF across the two operationalisations on the one female we
            have, which is itself a finding and is in the report below.
  UNRESOLVED  NASOLABIAL ANGLE (HeadNeck p.77, M 92-98 / F 95-105). Subnasale and labiale
            superius both resolve cleanly as profile turning points; the COLUMELLA does not
            exist as a feature here. The defensible columella references between subnasale
            and pronasale spread the angle over 26.8-41.8 degrees on the five bodies,
            against a 6 degree printed band — four to seven band widths.
  UNRESOLVED  ORBITAL LONG AXIS vs horizontal (FacialExpr p.20, 20 degrees). That is the
            axis of the BONY ORBITAL APERTURE. anny's vocabulary contains no target matching
            'orbit', and a relief patch over the orbital margin is not an aperture — an axis
            needs a ring. The palpebral fissure axis IS measurable and is reported beside
            it under its own name, in the way landmarks.py ships neck_breadth_min beside the
            unresolved cervicale, precisely so nobody calls one the other.

THE FINDING ABOUT OUR OWN CHARACTERS
The one printed band that both resolves and discriminates says OUR EARS ARE WRONG, on every
body, including the stock anny neutral used as a control. HeadNeck p.69 requires the ear's
long axis to sit within about 8 degrees of the nose dorsum. MEASURED:

    body           ear axis   dorsum axis   difference   band
    anny-neutral     +1.98       +26.33        24.36     <= 8   FAIL
    female           +2.56       +23.95        21.39     <= 8   FAIL
    male             +1.96       +25.27        23.30     <= 8   FAIL
    abel (12 y)      +0.86       +27.28        26.42     <= 8   FAIL
    cornelis         +1.84       +25.78        23.94     <= 8   FAIL

The ear stands essentially vertical on all five while the dorsum leans back about 25
degrees, so every body fails by two to three times the tolerance. The failure is a property
of the ANNY BASE MESH and not of any character's morphs: the ear axis varies by 1.7 degrees
across a 12-year-old and three adults built from different recipes, and the control fails
identically. falsification_sweep() adds the corollary that no single lever in the 256-label
vocabulary brings the difference inside 8 degrees anywhere in +/-5, which is six times
geom/fit_reference.py's design cap. Fixing this is a base-asset job, not a per-character
one, and until it is fixed every render of every character carries an ear that the reference
says reads wrong.

Two smaller observations, both reported without a band because no book prints one:
  * The condylion-menton chord — the one part of the mandible this cage does carry — is
    MUCH more horizontal on abel (-62.6 degrees from vertical) than on the three adults
    (-26.1, -32.5, -42.9) or the neutral (-39.4). Read it as a lead, not a verdict: it is a
    rig quantity with no printed band, it moves with the head macros, and gonion — the thing
    that would turn it into a mandibular angle — is exactly what this cage does not have.
  * The carrying-angle DIRECTION test cannot be called on the cast we have. The coronal
    operationalisation puts the one female BELOW the four male-typed bodies (+2.40 against a
    male mean of +3.54, direction FAILS) and the decomposed one puts her above (-3.45
    against -8.25, direction HOLDS). One female is not a sample, and the two constructions
    disagree, so AFS p.176's sex term is recorded as untested rather than as passed or
    failed.

FRAME. Measured per mesh by geom.anthro.landmarks.frame_report(), never assumed, and
asserted at every entry point: +x is the subject's LEFT, +y is POSTERIOR, +z is SUPERIOR.
Sagittal tilts in this file are POSITIVE when the SUPERIOR end lies POSTERIOR of the
inferior end, which is the convention relational.py already writes its signs against.

ROLLBACK. ZYG_FORM_ANGLES_STRICT, default 1. At 1 the resolution test above governs: an
angle whose operationalisations disagree by more than its own printed band width reports
resolved=False and value_deg=None, with every operationalisation still in the record as
evidence. At 0 the primary operationalisation is reported as the value regardless. The
evidence is identical either way; only the refusal changes. Default is the refusing side.

THE FLAG GOVERNS THE SPREAD TEST AND NOTHING ELSE, which matters because three of the seven
angles are refused for a reason no flag can undo. gonial, subcostal and orbital have NO
ANCHOR on this cage, and carrying is out of its band's POSE DOMAIN; those four stay
unresolved at either setting. Measured at ZYG_FORM_ANGLES_STRICT=0, the only angle that
changes is nasolabial, which then reports its subnasale-to-pronasale variant (121.45 on the
neutral, above the 92-98 band) — a number no one should act on, which is why the default is
1.

SOURCES. The angles implement anatomical FACTS and METHODS, which are not copyrightable
(Baker v. Selden; Feist). Each band cites the book and page it is printed on so the number
can be checked against its source; no expression is reproduced.
"""

# The original top import block, so angles.os / angles.np / angles.LMK still resolve.
# Every name this package re-exports is declared in __all__ at the foot of the file.
import argparse
import json
import math
import os
import sys
import time

import numpy as np

from zyg_workflows.geom import mesh_skeletons as MS
from zyg_workflows.geom.anthro import integrity as IG
from zyg_workflows.geom.anthro import landmarks as LMK
from zyg_workflows.geom.anthro import measure as ME
from zyg_workflows.geom.form import curvature as CV
import logging as _zyg_logging

# Sections, in the original declaration order, so module-level side effects run in
# the same order they did in angles.py.
from zyg_workflows.geom.form.angles.base import (
    _zyg_log,
    SCHEMA,
    CANON,
    HOUSE,
    FRAME,
    SIGN_CONVENTION,
    BANDS,
    _strict,
    MIDLINE_TOL_M,
    OCCLUSION_HEIGHT_FRAC,
    OCCLUSION_SPLIT_FLOOR,
    OCCLUSION_MIN_GAP_FACTOR,
    JAW_WEIGHT_CUTS,
    FEATURE_MIN_FRAC,
    FEATURE_MIN_CONTRAST,
    FEATURE_PROBE_RADIUS,
    _CACHE,
    _frame,
    _context,
    _skin_mask,
    _unresolved,
    _bone_weight,
    _bone_head,
    _target_displacement,
    _spread,
    _verdict,
    _band_for,
)
from zyg_workflows.geom.form.angles.face import (
    face_profile,
    _occlusion_cut,
    _lm_frac,
    gonial_angle,
)
from zyg_workflows.geom.form.angles.trunk_limb import (
    subcostal_angle,
    _relief_sweep,
    _local_change_labels,
    carrying_angle,
    _adjacency,
)
from zyg_workflows.geom.form.angles.eyes import (
    _canthi,
    canthal_tilt,
    orbital_long_axis,
)
from zyg_workflows.geom.form.angles.nose_ear import (
    nasolabial_angle,
    _ear_axis,
    ear_nose_parallelism,
)
from zyg_workflows.geom.form.angles.aggregate import (
    measure_angles,
    scalars,
    falsification_sweep,
    _cases,
    _build,
    main,
)

# The re-export surface of the split package: the original top import block plus every
# name the section modules define, so `angles.<name>` and `from ... import <name>`
# resolve exactly as they did before the split.
__all__ = [
    'argparse',
    'json',
    'math',
    'os',
    'sys',
    'time',
    'np',
    'MS',
    'IG',
    'LMK',
    'ME',
    'CV',
    '_zyg_logging',
    '_zyg_log',
    'SCHEMA',
    'CANON',
    'HOUSE',
    'FRAME',
    'SIGN_CONVENTION',
    'BANDS',
    '_strict',
    'MIDLINE_TOL_M',
    'OCCLUSION_HEIGHT_FRAC',
    'OCCLUSION_SPLIT_FLOOR',
    'OCCLUSION_MIN_GAP_FACTOR',
    'JAW_WEIGHT_CUTS',
    'FEATURE_MIN_FRAC',
    'FEATURE_MIN_CONTRAST',
    'FEATURE_PROBE_RADIUS',
    '_CACHE',
    '_frame',
    '_context',
    '_skin_mask',
    '_unresolved',
    '_bone_weight',
    '_bone_head',
    '_target_displacement',
    '_spread',
    '_verdict',
    '_band_for',
    'face_profile',
    '_occlusion_cut',
    '_lm_frac',
    'gonial_angle',
    'subcostal_angle',
    '_relief_sweep',
    '_local_change_labels',
    'carrying_angle',
    '_adjacency',
    '_canthi',
    'canthal_tilt',
    'orbital_long_axis',
    'nasolabial_angle',
    '_ear_axis',
    'ear_nose_parallelism',
    'measure_angles',
    'scalars',
    'falsification_sweep',
    '_cases',
    '_build',
    'main',
]
