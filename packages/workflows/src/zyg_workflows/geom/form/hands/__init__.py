# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

# ruff: noqa: E402,F401
# E402: the re-export block has to sit below the original top import block, because the
# sys.path bootstrap there still has to run first, exactly as it did in hands.py.
# F401: every name below is re-exported so that `zyg_workflows.geom.form.hands.<name>`
# keeps resolving for every importer of the old single file.
"""hands.py — the hand FORM-plausibility pack, in mesh space and in image space.

WHY THIS EXISTS. geom/anthro measures whether a body's proportions sit inside a real
anthropometric distribution. No band in it can see a hand: ANSUR ships hand LENGTH and
hand BREADTH and nothing about whether the knuckles arch, whether there is a web between
the fingers, or whether the thumb is opposed. Hands are simultaneously our most visible
generated-output failure and our least gated region, and every hand defect we have shipped
would have passed every metric gate we own. This module implements the FORM predicates —
the ones that ask "does this read as a hand" — on the anny cage and, with the same
vocabulary, on MediaPipe's 21-point landmarks so that a mesh verdict and a render verdict
are directly comparable.

WHERE THE RULES COME FROM. The predicates are anatomical FACTS and METHODS, which are not
copyrightable (Baker v. Selden; Feist), implemented here from our own measurements on our
own cage. Preferred citations are public domain: Gray's Anatomy (1918) "Surface Anatomy of
the Upper Extremity" for the metacarpal heads forming the knuckles and for the first
metacarpal lying in a different plane from the other four; Bridgman, Constructive Anatomy
(1920), for the knuckle arch and the two-thirds/one-half block-out of the hand. The
anatomy4sculptors blog states the same facts (the knuckles never align; the middle finger
is about half the hand; the spaces between the fingers are not V-shaped because of
webbing; the thumbnail faces a different direction from the other four) and none of their
expression, images or meshes is used.

THE FIVE TRAPS THIS FILE IS BUILT AROUND. Each was measured on this cage, not assumed.

  1. AN INVENTED ANCHOR IS THE ONE UNFORGIVABLE OUTCOME. Every anchor here is either an
     existing geom.anthro.landmarks landmark (wrist_ring, dactylion) or a vertex set
     defined by anny's OWN rig — the 163-bone roster is enumerated at import and the hand
     bones are looked up by name, never by a guessed vertex range. An MCP centre is the
     weighted centroid of the cage ring that the rig skins across a metacarpal-to-phalanx
     joint. Measured against the rig's true joint on the neutral male, that centroid sits
     1.5-8.9 mm away, which is REPORTED (see frame['mcp_ring_note']) rather than hidden:
     it is a ring centre, not a joint centre, and the calibration measures the predicate
     through this same estimator so the threshold is in the estimator's own units.

  2. THE FIVE-MCP COLLINEARITY TEST IS DOMINATED BY THE THUMB AND CANNOT SEE THE DEFECT.
     Measured on the male original: the line residual over all five MCPs is 18.78 mm, over
     the four finger MCPs 2.50 mm — 7.5x. A gate on the five-point residual would pass a
     hand whose four knuckles had been flattened onto a straight line, because the thumb
     alone keeps the number large. The GATED statistic is therefore the four finger MCPs;
     the five-point number is reported beside it and gates nothing.

  3. "THE MOST PROXIMAL SHARED-WEIGHT VERTEX" IS NOT THE COMMISSURE. That definition finds
     the proximal edge of the skinning blend, and measured on the male original it lands
     at -0.48 to -0.41 of proximal-phalanx length, i.e. PROXIMAL to the MCP line, which is
     anatomically impossible for a web apex. The commissure is found instead by an EXACT
     plane-mesh intersection of the inter-digital mid-plane against the delivered
     triangulation, which puts it at +0.30 to +0.43 — distal, as it must be.

  4. DORSAL-VS-PALMAR LENGTH MEASURED FROM A COMMON TRANSVERSE PLANE INVERTS. Measured
     that way the ratio comes out 0.62-0.85 on all four characters, because the palmar
     profile dives into the palm hollow before it reaches the finger. The anatomical
     definition is used instead: the dorsal length runs from the knuckle (the MCP
     transverse plane), the palmar length from the web. That is the same fact the webbing
     predicate reports, measured a second and independent way, and this file says so
     rather than presenting two views of one measurement as two pieces of evidence.

  5. A PREDICATE WITH NO LANDMARK IS UNMEASURABLE, NOT APPROXIMATED. MediaPipe's 21-point
     topology has no commissure point and no surface, so `webbing` and `dorsal_over_palmar`
     come back status='unmeasurable' from the image path with the reason attached. The
     thumb's own web is likewise UNRESOLVED in mesh space: the rig blends only 2 cage
     vertices between the thumb and index proximal phalanges at weight>0.01 and 0 at
     weight>0.05, so there is no first-web-space signature to measure.

HOW THE THRESHOLDS ARE CALIBRATED. Form predicates are not bands over ANSUR, so they get
their own reference sample: a Monte-Carlo draw over the anny morph space (the 6 phenotype
macros plus the four hand local morphs, mirrored L/R because measure.py refuses a body
whose bilateral residual exceeds 10 mm), keeping only bodies that geom.anthro's tier-2 run
would ACCEPT — no blocking failure at effective severity. Every predicate's rejection rate
against that accepted sample is then exactly comparable to the ANSUR rejection rates
gates.py measures, and the same house rule applies: a form gate may block only if it
rejects under 1% of the reference sample. Because a percentile threshold taken from the
sample rejects its own percentile by construction, the thresholds here are FLOORS set
outside the whole observed range by a stated margin; the measured rate is then 0/N and
what is reported is the 95% rule-of-three upper bound 3/N.

WHAT THIS BUYS ON THIS CAGE, STATED PLAINLY. The anny hand barely changes shape across the
morph space — the four-MCP arch residual is 0.0185-0.0202 of hand length on all four
issued characters, a 9% spread. In mesh space these gates are therefore a REGRESSION
check: they catch a hand that a sculpt layer, a bone scale or a fitted mesh has damaged,
not a hand the morph sliders got wrong. The discriminating power is in the image path,
where diffusion output actually fails.

THE DIGIT PACK (second half of the file, added 2026-08-06): t5_digit_chains and
t5_phalanx_ratio, plus the child-hand directions. Where the five predicates above measure
the SKIN, these measure the SKELETON, and unlike the five they carry EXTERNAL thresholds
and therefore gate on this machine whether or not a morph sample has been built.

PROVENANCE, AND THE ONE TAG THAT WAS WRONG. Three classes, ranked MEASURED > CANON >
HOUSE, and the ranking is why the tag matters: whatever a record claims here is what the
gate row prints as its evidence class.
  MEASURED  a named survey of real people WITH A SAMPLE SIZE, measured on bodies that are
            not ours. In this file: phalanx_ratio only — Buryanov & Kotiuk 2010 (n=66) and
            Hamilton & Dunsmuir 2002 (n=197).
  CANON     a number printed in an anatomy-for-artists text. A page, plate or figure.
  HOUSE     ours: a threshold off our own Monte-Carlo morph sample, or a scope decision.
2026-08-06 RE-TAG. `digit_chains` shipped MEASURED while its only citation was AFS p.179
and p.188 — two book pages, which is CANON. The gate registry had already been corrected;
this module had not, so the stale string travelled into every gate row and into the text
report, claiming survey evidence for a book number in the flattering direction. The record
is now CANON, nothing about the check moved (same assertions, same threshold of 0, same
block severity, every anny body still FAILS it), and `_rec` now REFUSES to emit a MEASURED
record whose source names no sample size, so the two cannot drift apart again.

THE HEADLINE FINDING, AND IT IS ABOUT THE RIG RATHER THAN ABOUT ANY CHARACTER. anny's
finger has the right TOTAL length and the wrong JOINTS. Measured on the neutral against
Buryanov & Kotiuk 2010 (n=66) the index finger's whole skeleton comes out 77.33 mm
against a published 77.98, and the metacarpal 71.28 against 68.12 — both within a few
percent. But the PIP joint sits at 0.342 of the way from the knuckle to the fingertip
where two independent radiographic series put it at 0.486 and 0.500, and the DIP at
0.650 against 0.760 and 0.783. The two surveys disagree with EACH OTHER by 0.014 and
both disagree with anny by 0.14-0.16, a ten-fold separation. Every one of the four
fingers is off in the same direction on every one of the five bodies, and the deviation
does not move with the age macro (index mid/prox 0.8913-0.8984 from 5.8 y to 90 y), so
this is baked into the rig and cannot be morphed away. The practical consequence is that
anny's middle phalanx is about a third too long and its distal segment about a third too
long at the proximal phalanx's expense: bend that finger and the creases fall in the
wrong places.

None of this is visible to geom.anthro, and that is the point of the gate. `hand_length`
is wrist_ring -> dactylion; it does not care where the knuckles inside it fall. The
--digit-lesion demo drives all four fingers to the survey means and back out again while
holding the summed finger length at 257.9412 mm to four decimal places in every variant.
"""

import argparse
import glob
import json
import math
import os
import re
import sys
import time

# MEASURED 2026-08-06: `python geom/form/hands.py --digits` from any cwd but the repo root
# raised `ModuleNotFoundError: No module named 'geom'` at hands.py:2791, because every
# `from geom import mesh_skeletons` in this file is a LAZY import inside a function — the
# module imports clean and only fails once a digit gate is actually asked for. ridge.py,
# angles.py, sections.py and pose_limits.py all carry this three-line bootstrap already;
# hands.py was the one that did not, and geom/mesh_skeletons.py::_ensure_repo_importable
# exists for exactly this failure mode. Idempotent: re-inserting an existing entry is
# harmless, and the path is only consulted when `geom` is not already importable.
#
# PACKAGE SPLIT 2026-10-06: this file was geom/form/hands.py and is now
# geom/form/hands/__init__.py — one directory deeper — so the dirname chain takes one
# more step to land on exactly the directory it always did (the parent of `geom`). The
# inserted path is identical to the one the single file inserted.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))

import numpy as np
import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)


from zyg_workflows.geom.form.hands.rig import (
    SCHEMA,
    PREDICATES,
    DIGIT_PREDICATES,
    PASS,
    WARN,
    FAIL,
    REPORT,
    UNMEASURABLE,
    NOT_IMPLEMENTABLE,
    UNRESOLVED,
    ERROR,
    MEASURED,
    HOUSE,
    CANON,
    DIGITS,
    FINGERS,
    WEBS,
    _ROOT,
    FORM_REFERENCE_DIR,
    SAMPLE_FILE,
    CAGE_VERTS,
    DIGIT_BONES,
    FOREARM_BONE,
    WRIST_BONE,
    RING_W_MIN,
    SEGMENT_W_MIN,
    WEB_FACE_W_MIN,
    RIDGE_SLAB_FRAC,
    RIDGE_BINS,
    DP_AXIS_MIN_ANISOTROPY,
    _RIG,
    _RING,
    _side,
    _model,
    rig,
    verify_rig,
    _ring_idx,
    _segment_idx,
    _joint,
    _unit,
    _line_residuals,
    _line_angle,
    _vec_angle,
    _principal_axes,
    _triangulate,
    _plane_cut,
    resolve_hand,
)
from zyg_workflows.geom.form.hands.provenance import (
    _SURVEY_N_RE,
    _CITATION_RE,
    _CANON_BOOK_NAMES,
    _MIN_SURVEY_N,
    _BOOK_MIRROR_CHECKED,
    _canon_books_named,
    _assert_book_mirror,
    _assert_provenance,
    _PROVENANCE_CONTROLS,
    provenance_rule_controls,
    _run_provenance_controls_at_import,
    _rec,
    _judge,
)
from zyg_workflows.geom.form.hands.mesh import (
    _mesh_knuckle_arch,
    _mesh_middle_finger_ratio,
    _web_axes,
    _mesh_webbing,
    _dp_axis,
    _mesh_thumb_opposition,
    _mesh_dorsal_over_palmar,
    measure_hand_mesh,
    FLOOR_MARGIN,
    _CAL,
    calibration,
    _band_for,
    check_hand_mesh,
)
from zyg_workflows.geom.form.hands.unresolved import (
    MESH_UNRESOLVED,
    IMAGE_UNRESOLVED,
    DIGIT_UNRESOLVED_FOOT_RATIO,
    DIGIT_UNRESOLVED,
)
from zyg_workflows.geom.form.hands.image import (
    MP,
    MP_MCP,
    MP_TIP,
    MIN_HAND_PX,
    MIN_CHAIN_BEND,
    IMAGE_NOT_GATED,
    _chain_plane,
    _image_predicates,
    _detect_hands_raw,
    _hand_crops,
    check_hand_image,
)
from zyg_workflows.geom.form.hands.sample import (
    HAND_MORPHS,
    MORPH_ABS_MAX,
    AGE_MACRO_RANGE,
    _draw,
    _atomic_json,
    build_sample,
    _PRED_SIDEDNESS,
    NATURAL_FLOOR,
    NATURAL_FLOOR_WHY,
    RELATIONAL_FLOOR,
    _rate_record,
    _fit_bands,
    _digit_mask,
    lesion_flatten_knuckles,
    lesion_fill_web,
    lesion_unoppose_thumb,
    LESIONS,
)
from zyg_workflows.geom.form.hands.digits_rig import (
    _env_flag,
    DIGIT_GATES_FLAG,
    TOE_BONES,
    TOES,
    LESSER_TOES,
    FOOT_BONE,
    SHANK_BONE,
    SKELETAL_COUNTS,
    BK2010,
    BK2010_SOURCE,
    HD2002,
    HD2002_SOURCE,
    AFS_P178_PARTS,
    AFS_P178_SOURCE,
    ORDERING_GATED,
    _ratio_band,
    _BONEW,
    _SKEL,
    _bone_weight,
    skeleton,
    _blen,
)
from zyg_workflows.geom.form.hands.digit_chains import (
    _RE_FINGER,
    _RE_METACARPAL,
    _RE_TOE,
    digit_roster,
    metapodial_test,
    chain_continuity,
    surface_support,
    measure_digit_chains,
    check_digit_chains,
    measure_phalanx_ratio,
    check_phalanx_ratio,
)
from zyg_workflows.geom.form.hands.child_hand import (
    CHILD_AGE_MAX_Y,
    ADULT_AGE_MACRO,
    _finger_thickness,
    _knuckle_relief,
    _hand_over_head,
    _child_channels,
    CHILD_HAND_ASSERTIONS,
    measure_child_hand,
    check_child_hand,
)
from zyg_workflows.geom.form.hands.digits import (
    check_digits,
    phalanx_scale_recipe,
    survey_mean_targets,
)
from zyg_workflows.geom.form.hands.cli import (
    _fmt,
    _report_mesh,
    _digit_cases,
    _cli_digits,
    _cli_digit_lesion,
    main,
)

# The provenance rule, demonstrated on hostile strings before this module can be used.
_run_provenance_controls_at_import()
