# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later
# This package re-exports every name relational.py defined; they are declared in __all__
# at the foot of the file.

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

This package replaces the single module relational.py; the import path is unchanged.
Its sections, moved verbatim and imported below in their original order:

  * constants.py — the module header, the original import block, the HOUSE constants and _CACHE (lines 1-96, 97-179)
  * spine.py — frame and context, the posterior midsagittal chain, lumbar curvature and the segment-tilt frames (lines 180-500)
  * body.py — gluteal vs trochanteric, angle kappa, knee alignment, pelvis tilt and the whole-body call (lines 501-1049)
  * reference.py — the form reference sample: ranges, draw, build_reference and the distribution (lines 1050-1309)
  * gate_defs.py — the gates: the binomial bound, rejection_rate, calibrate, the predicates and gate_records (lines 1310-1643)
  * cli.py — the swayback validation sweeps and the CLI (lines 1644-1863)
"""

import argparse
import json
import math
import os
import sys
import time

import numpy as np

from zyg_workflows.geom import mesh_skeletons as MS  # noqa: E402
from zyg_workflows.geom.anthro import integrity as IG  # noqa: E402
from zyg_workflows.geom.anthro import landmarks as LMK  # noqa: E402
from zyg_workflows.geom.anthro import measure as ME  # noqa: E402
from zyg_workflows.geom.anthro.gates.bands import (  # noqa: E402
    CAL_UNDECLARED,
    CAL_VIOLATION_RATE,
    SEVERITY_POLICY,
    SEVERITY_REJECTION_CEILING,
)
from zyg_workflows.geom.anthro.gates.engine import run_gates  # noqa: E402
from zyg_workflows.geom.anthro.gates.gate import Gate, _result, validate_registry  # noqa: E402
from zyg_workflows.geom.anthro.gates.policy import FAIL, HOUSE, MEASURED, MISSING, PASS  # noqa: E402

from zyg_workflows.geom.form.relational import constants as _constants
from zyg_workflows.geom.form.relational import spine as _spine
from zyg_workflows.geom.form.relational import body as _body
from zyg_workflows.geom.form.relational import reference as _reference
from zyg_workflows.geom.form.relational import gate_defs as _gate_defs
from zyg_workflows.geom.form.relational import cli as _cli

from zyg_workflows.geom.form.relational.constants import (
    BAND_HALF_FRAC,
    EYE_AXIS_AGREEMENT_MAX_DEG,
    EYE_SIMILARITY_MAX_ANISOTROPY,
    FRAME,
    LOCAL_BOUND,
    MIDLINE_TOL_M,
    POSTERIOR_NORMAL_MIN,
    REFERENCE_DIR,
    REFERENCE_FILE,
    ROOT,
    SCHEMA,
    SIGN_CONVENTION,
    _CACHE,
)
from zyg_workflows.geom.form.relational.spine import (
    _cage_edges,
    _centroid_axis,
    _context,
    _frame,
    _lm_frac,
    _unresolved,
    lumbar_curvature,
    posterior_midline_chain,
    segment_tilt_opposition,
)
from zyg_workflows.geom.form.relational.body import (
    _eye_components,
    _local_change_labels,
    _neutral_eye,
    _pole_axis,
    _sphere_fit,
    eye_axes,
    gluteal_vs_trochanteric,
    knee_alignment,
    measure_relations,
    pelvis_width_to_tilt,
    q_angle,
    scalars,
)
from zyg_workflows.geom.form.relational.reference import (
    ACCEPTANCE_GATE,
    ACCEPTANCE_STATUS,
    ADULT_AGE_FRAC,
    MACRO_RANGES,
    SAMPLED_LOCALS,
    _distribution,
    _draw_one,
    _worker,
    build_reference,
    form_reference,
    sample_recipe,
)
from zyg_workflows.geom.form.relational.gate_defs import (
    FORM_REFERENCE_POPULATION,
    _binom_upper95,
    _p_eye_not_parallel,
    _p_eye_outward,
    _p_gluteal,
    _p_lordosis,
    _p_opposition,
    calibrate,
    gate_records,
    rejection_rate,
)
from zyg_workflows.geom.form.relational.cli import (
    REJECTED_FEMALE_LOCALS,
    REJECTED_FEMALE_PHEN,
    SWAY_LEVER,
    _build_character,
    _characters,
    falsification_sweep,
    main,
    swayback_sweep,
)

# The re-export surface of the split package: the original top import block, the section
# modules themselves and every name they define, so `relational.<name>` and
# `from ... import <name>` resolve exactly as they did before the split.
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
    '_constants',
    '_spine',
    '_body',
    '_reference',
    '_gate_defs',
    '_cli',
    'BAND_HALF_FRAC',
    'EYE_AXIS_AGREEMENT_MAX_DEG',
    'EYE_SIMILARITY_MAX_ANISOTROPY',
    'FRAME',
    'LOCAL_BOUND',
    'MIDLINE_TOL_M',
    'POSTERIOR_NORMAL_MIN',
    'REFERENCE_DIR',
    'REFERENCE_FILE',
    'ROOT',
    'SCHEMA',
    'SIGN_CONVENTION',
    '_CACHE',
    '_cage_edges',
    '_centroid_axis',
    '_context',
    '_frame',
    '_lm_frac',
    '_unresolved',
    'lumbar_curvature',
    'posterior_midline_chain',
    'segment_tilt_opposition',
    '_eye_components',
    '_local_change_labels',
    '_neutral_eye',
    '_pole_axis',
    '_sphere_fit',
    'eye_axes',
    'gluteal_vs_trochanteric',
    'knee_alignment',
    'measure_relations',
    'pelvis_width_to_tilt',
    'q_angle',
    'scalars',
    'ACCEPTANCE_GATE',
    'ACCEPTANCE_STATUS',
    'ADULT_AGE_FRAC',
    'MACRO_RANGES',
    'SAMPLED_LOCALS',
    '_distribution',
    '_draw_one',
    '_worker',
    'build_reference',
    'form_reference',
    'sample_recipe',
    'FORM_REFERENCE_POPULATION',
    '_binom_upper95',
    '_p_eye_not_parallel',
    '_p_eye_outward',
    '_p_gluteal',
    '_p_lordosis',
    '_p_opposition',
    'calibrate',
    'gate_records',
    'rejection_rate',
    'REJECTED_FEMALE_LOCALS',
    'REJECTED_FEMALE_PHEN',
    'SWAY_LEVER',
    '_build_character',
    '_characters',
    'falsification_sweep',
    'main',
    'swayback_sweep',
]
