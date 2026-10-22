# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later
# This module inherits the original top import block of relational.py; the names it does not
# use itself are read THROUGH it by its siblings (spine, body, reference, gate_defs, cli) and
# by the package __init__, so they are declared re-exports in __all__ below, never deleted.

"""relational.py — form predicates about RELATIONSHIPS BETWEEN PARTS, and an honest record
of which of them this cage cannot carry.

WHY THIS MODULE EXISTS
geom/anthro/ asks "is this dimension inside the measured human distribution" and answers it
over ANSUR II. That layer is finished, it works, and it is structurally blind to the defect
class this file is about. A swayback is not a wrong dimension. Every width on the rejected
2026-08-05 female solve was inside its band; what was wrong was the RELATION between the
thoracic and the pelvic segment, and no quotient of two landmark heights can see it. The
same is true of "the butt is wider than the hips" (two widths, each individually fine) and
of parallel eyes (two orientations, each individually forward).

So the predicates here are all of the form "A against B", never "A against a table".

THE TRAP THIS FILE IS BUILT AROUND, and it is not a small one: a form gate that measures
the wrong patch will CONFIDENTLY PASS A DEFORMED BODY. A dimensional gate that anchors
badly produces a number that is visibly out of band and someone investigates. A form gate
that anchors badly produces a serene "opposition holds, margin 12 mm" on a body with a
banana spine. That asymmetry is why every predicate below either resolves on an anchor this
cage demonstrably carries, or is reported UNRESOLVED with the measurement that proves the
anchor is absent — exactly as geom/anthro/landmarks.py does for cervicale, tenth rib,
iliocristale, stylion, patella and lateral malleolus. Three of the predicates asked for
here are unresolved, and saying so is the most useful thing this file does.

WHAT IS RESOLVED, WHAT IS NOT (all measured on the four issued characters, 2026-08-06)

  RESOLVED  lumbar sagittal curvature and the two-chord sagittal opposition, read off the
            POSTERIOR MIDSAGITTAL VERTEX CHAIN — a real edge-connected path of cage
            vertices at |x| <= 0.1 mm, not an envelope. This is the swayback detector and
            it separates the rejected female (lordosis index 25.15) from the shipped one
            (13.11) and from the three male-typed bodies (7.72-7.73).
  RESOLVED  gluteal-vs-trochanteric coronal width, on measure.py's torso-scoped extent
            scan. It passes on everything in the design range, and the falsification sweep
            in this file says exactly how far a body has to be pushed before it fails,
            which is the only thing that makes a never-failing gate worth shipping.
  RESOLVED  eyeball optical-axis divergence — but NOT by the corneal apex, which does not
            exist here (see eye_axes: the vertex furthest from the fitted sphere centre
            points POSTERIOR, out of the back of the skull). The anchor is the eyeball
            shell's own construction axis, and the record proves per body that the shell is
            a rigid-plus-uniform-scale copy of the neutral eye before it reads an
            orientation off it.
  RESOLVED  coronal knee alignment (femorotibial angle) from anny's own joint centres.

  UNRESOLVED  thoracic/pelvic SEGMENT-TILT frames. The resolvable pelvic band is 0.06 of
            stature tall and the segment axis over it swings 10.1 degrees between two
            bodies that share an identical local-morph recipe. Measured, in
            segment_tilt_opposition().
  UNRESOLVED  the clinical Q angle. All three of its landmarks — ASIS, patella centre,
            tibial tuberosity — are absent from this cage and from MakeHuman's whole
            256-label vocabulary. Measured, in q_angle().
  UNRESOLVED  the pelvis width-to-tilt relationship, because the tilt half of it is
            unresolved. The width half is reported so the missing half is visible.

FRAME. Measured by geom.anthro.landmarks.frame_report(), never assumed, and asserted at the
top of every entry point: +x is the subject's LEFT, +y is POSTERIOR, +z is SUPERIOR. Every
sagittal angle in this file is therefore signed as: POSITIVE means the SUPERIOR end lies
POSTERIOR of the inferior end. A lordosis DEPTH is positive when the profile bows ANTERIOR
of its own chord, which is what a hollow back is.

CALIBRATION. A form predicate is not a band over ANSUR, so ANSUR cannot say what fraction
of real people it rejects. The reference sample it is calibrated on is a MONTE-CARLO SAMPLE
OF THE ANNY MORPH SPACE, built by build_reference() and cached under
data/assets/form_reference/: draw the six phenotype macros and the local morphs each
predicate concerns, keep only the draws that pass geom.anthro's own primary plausibility
gate, and measure what fraction each predicate rejects. That rate is directly comparable to
the ANSUR rejection rates gates.py measures, and the same rule applies — a gate may block
only if it rejects at most 1% of its reference sample.

  ONE TRAP IN REUSING gates.py's MACHINERY, stated because the code cannot show it: passing
  these gates to geom.anthro.gates.calibrate_gate() produces a record whose
  'reference_population' field reads "the real ANSUR II sample". That field is hardcoded in
  the CAL_VIOLATION_RATE branch there and it would be a FALSE provenance claim for every
  gate in this file. Use calibrate() below, which is the same policy arithmetic against the
  population these gates were actually measured on.

SOURCES. The predicates implement anatomical FACTS and METHODS, which are not copyrightable
(Baker v. Selden; Feist), from our own data and our own code. Where a public-domain source
covers the point it is cited in preference to anything else: Gray's Anatomy (1918) has
dedicated "Surface Anatomy and Surface Markings" chapters covering landmark visibility, and
the flexicurve construction used by lumbar_curvature() is the ordinary chord-and-depth
method for a spinal curve, not anyone's expression of it.
"""

import argparse
import json
import math
import os
import sys
import time

import numpy as np

from zyg_workflows import paths
from zyg_workflows.geom import mesh_skeletons as MS
from zyg_workflows.geom.anthro import integrity as IG
from zyg_workflows.geom.anthro import landmarks as LMK
from zyg_workflows.geom.anthro import measure as ME
from zyg_workflows.geom.anthro.gates.bands import (
    CAL_UNDECLARED,
    CAL_VIOLATION_RATE,
    SEVERITY_POLICY,
    SEVERITY_REJECTION_CEILING,
)
from zyg_workflows.geom.anthro.gates.engine import run_gates
from zyg_workflows.geom.anthro.gates.gate import Gate, _result, validate_registry
from zyg_workflows.geom.anthro.gates.policy import FAIL, HOUSE, MEASURED, MISSING, PASS

# The re-exports: imports this module does not use itself but its siblings read from it
# (see the note above the import block). Names defined below are reached by name.
__all__ = [
    'argparse',
    'json',
    'math',
    'sys',
    'time',
    'np',
    'MS',
    'IG',
    'LMK',
    'ME',
    'CAL_UNDECLARED',
    'CAL_VIOLATION_RATE',
    'SEVERITY_POLICY',
    'SEVERITY_REJECTION_CEILING',
    'run_gates',
    'Gate',
    '_result',
    'validate_registry',
    'FAIL',
    'HOUSE',
    'MEASURED',
    'MISSING',
    'PASS',
]

SCHEMA = 'geom.form.relational/1'

ROOT = str(paths.PKG_DIR)
REFERENCE_DIR = str(paths.DATA_DIR / 'assets' / 'form_reference')
REFERENCE_FILE = os.path.join(REFERENCE_DIR, 'relational_reference.json')

# The frame this module's every sign convention is written against. NOT assumed: asserted
# per mesh by _frame(), which delegates the measurement to landmarks.frame_report().
FRAME = {
    'subject_left_axis': 'x',
    'subject_left_sign': 1,
    'anterior_axis': 'y',
    'anterior_sign': -1,
    'up_axis': 'z',
    'up_sign': 1,
}
SIGN_CONVENTION = (
    '+x subject LEFT, +y POSTERIOR, +z SUPERIOR (measured per mesh by '
    'landmarks.frame_report). A sagittal tilt is POSITIVE when the SUPERIOR '
    'end of the chord lies POSTERIOR of the inferior end. A lordosis depth '
    'is POSITIVE when the profile bows ANTERIOR of its own chord.'
)

# ---------------------------------------------------------------------------------
# HOUSE constants, each with the measurement that fixes it
# ---------------------------------------------------------------------------------
# The cage's midsagittal vertex column sits at |x| = 0.0000 and 0.0300 mm; the next column
# out is at 0.7307 mm (MEASURED on the issued male, distinct |x| levels below 5 mm:
# 0, 0.0299, 0.0300, 0.7307, 0.7906, ...). 0.1 mm therefore isolates the midline column
# with a 7x margin and is not a tuned number.
MIDLINE_TOL_M = 1e-4

# A midline vertex belongs to the POSTERIOR branch when its outward normal faces posterior.
# MEASURED over the anatomical window used here (buttock landmark to bust ring), the
# retained chain's minimum n_y is 0.848 (female) / 0.935-0.951 (male, abel, cornelis), and
# the anterior branch it excludes has n_y <= -0.8. Any cut between about 0.1 and 0.8
# selects the same vertices; 0.5 is the midpoint of that plateau.
POSTERIOR_NORMAL_MIN = 0.5

# Half-width of the gluteal and trochanteric comparison bands, in stature. MEASURED
# separation between the resolved buttock and trochanterion landmarks on the four issued
# characters, WITH the recipe passed to resolve_landmarks: female 0.0083, male 0.0138,
# cornelis 0.0149, abel 0.0195. The recipe matters and this constant is where it bites —
# resolved from the NEUTRAL joint centres instead, the female reads 0.0196, and a band
# half-width sized on that number silently overlaps by 4 mm on the body it was sized for.
# 0.003 keeps the two bands disjoint on all four (worst gap 0.0023 of stature, 3.9 mm on
# the female); an overlap is REFUSED rather than reported.
BAND_HALF_FRAC = 0.003

# A rigid-plus-uniform-scale map has all three singular values equal. The eyeball shell is
# read as an orientation only when its map from the neutral eye is that close to a
# similarity. MEASURED anisotropy (smax/smin of the least-squares affine map from the
# neutral eye) on the four issued characters: 1.0032 male, 1.0403 female, 1.0194 abel,
# 1.0044 cornelis; and the measured axis agrees with the rotation applied to the neutral
# axis to within 0.016-0.094 degrees. 1.10 is a ceiling with 2.5x headroom over the worst
# issued body, chosen so that a shell squashed enough to move its pole by more than the
# angle being measured is refused instead of read.
EYE_SIMILARITY_MAX_ANISOTROPY = 1.10
EYE_AXIS_AGREEMENT_MAX_DEG = 1.0

# The design-range cap on a local morph. Not this file's constant: geom/fit_reference.py
# LOCAL_BOUND, "hard design-range cap — the swayback came from -1.6".
LOCAL_BOUND = 0.8

_CACHE = {}
