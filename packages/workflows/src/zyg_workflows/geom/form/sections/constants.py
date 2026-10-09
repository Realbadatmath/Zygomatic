# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""sections.constants — the import bootstrap, the statuses, the three calibrated numbers and the sources.

Moved verbatim from geom/form/sections.py; no logic, numbers or comments changed.
"""

# ruff: noqa: F401  this module inherits sections.py's original top import block whole:
# its members are re-imported by the sibling modules and re-exported by the package
# __init__.
import contextlib
import json
import math
import os
import sys

import numpy as np

from zyg_workflows.geom import mesh_skeletons as MS
from zyg_workflows.geom.anthro import landmarks as LMK
from zyg_workflows.geom.anthro import measure as MEA

SCHEMA = 'geom.form.sections/1'

# ---------------------------------------------------------------------------------
# rollback
# ---------------------------------------------------------------------------------
ENV_FLAG = 'ZYG_FORM_SECTIONS'
ENV_FLAG_DEFAULT = '1'


def enabled():
    return os.environ.get(ENV_FLAG, ENV_FLAG_DEFAULT) not in ('0', 'false', 'no', '')


# ---------------------------------------------------------------------------------
# statuses — the vocabulary geom.anthro.gates already uses, so a future registration
# needs no translation layer.
# ---------------------------------------------------------------------------------
PASS = 'pass'  # noqa: S105  gate status constant, not a secret
FAIL = 'fail'
WARN = 'warn'
REPORT = 'report'
UNMEASURABLE = 'unmeasurable'
NOT_APPLICABLE = 'not_applicable'

# provenance vocabulary — see the module docstring. CANON is the plan's §1.3 tag and is
# ranked BELOW MEASURED; GEOMETRY is a theorem and outranks both because it cannot be wrong.
CANON = 'CANON'
MEASURED = 'MEASURED'
GEOMETRY = 'GEOMETRY'
HOUSE = 'HOUSE'

# ---------------------------------------------------------------------------------
# the only three numbers in this file
# ---------------------------------------------------------------------------------
# MEASURED. geom.form.curvature.relief_null(), 298 random patches of radius 0.012 of
# stature over the anny neutral's torso and limb skin: |relief/stature| p99 = 2.45e-3
# (4.13 mm at S = 1.686 m). This is the cage's OWN noise floor. A dip, a bulge or a
# deviation smaller than this is not resolvable on this tessellation and is reported as
# unresolved rather than as absent. It is never used as an anatomical target.
RELIEF_NULL_FRAC = 2.45e-3

# GEOMETRY. The exact isoperimetric ratio 4*pi*A/P^2 of a REGULAR HEXAGON:
#   A = (3*sqrt(3)/2) s^2, P = 6 s  =>  4*pi*A/P^2 = pi*sqrt(3)/6 = 0.9069.
# HeadNeck p.106-107 draws the neck section as a hexagon. The strictest reading of that
# claim with no free parameter is: the section may not be MORE circular than a hexagon.
HEXAGON_CIRCULARITY = math.pi * math.sqrt(3.0) / 6.0

# HOUSE, and inherited rather than invented: geom.anthro.measure.ARM_SKIN_WEIGHT_THRESHOLD.
# A vertex whose majority skinning weight belongs to a segment IS that segment.
SEGMENT_MAJORITY = 0.5

# The polygon orders the neck section is fitted against. 3..12 plus the circle. Every
# member of the family is fitted in the SAME whitened frame with the SAME single free
# parameter (a rotation), so the comparison across N is fair by construction and the
# argmin is an ordering test rather than a tuned selection. See _ngon_residual.
NGON_ORDERS = tuple(range(3, 13))
NGON_THETA_STEPS = 720  # deterministic; no optimiser, no random seed

# ---------------------------------------------------------------------------------
# sources — every claim carries its page, in the style geom.anthro.gates uses.
# ---------------------------------------------------------------------------------
SRC_TORSO = 'Anatomy For Sculptors p.24 (torso cross-sections)'
SRC_LEG = 'Anatomy For Sculptors p.215 (leg counter-curve)'
SRC_CALF = 'Anatomy For Sculptors p.216 (gastrocnemius heads)'
SRC_NECK_HEX = 'Anatomy of the Head and Neck p.106-107 (neck cross-section)'
SRC_NECK_TAPER = 'Anatomy of the Head and Neck p.172 (male neck), p.173 (female neck)'
SRC_NULL = 'geom.form.curvature.relief_null — 298 patches on the anny neutral, |relief/stature| p99 = 2.45e-3'

# The scalars a future gate would band. Named here so the module is self-describing, in the
# same spirit as geom.form.blockout.PREDICATES.
PREDICATES = {
    'torso_width_over_depth': 'section x-extent / y-extent at each torso level; > 1 (sign)',
    'torso_front_back_curvature': 'median normalised Menger curvature of the anterior arc '
    'over that of the posterior arc; < 1 = front flatter',
    'gluteal_concavity_count': 'integer count of hull gaps deeper than the relief null at the buttock level; >= 1',
    'neck_hex_beats_circle': 'sign of (circle residual - hexagon residual) in the whitened frame; > 0 = hexagonal',
    'neck_circularity': '4*pi*A/P^2 of the neck section; <= 0.9069 (a hexagon) required',
    'neck_spine_posterior_mm': 'cervical rig axis minus section centroid, along the in-plane '
    'posterior direction; > 0 required',
    'neck_taper_ratio': 'fitted neck radius at the top of the cervical mask over the radius '
    'at its base; < 1 = conical (female), ~1 = cylindrical (male)',
    'leg_centroid_sign_changes': 'integer count of sign changes of the section-centroid '
    'lateral residual from the endpoint chord; >= 1',
    'calf_medial_lower': 'sign of (lateral apex height - medial apex height); > 0 required',
    'calf_medial_larger': 'sign of (medial bulge amplitude - lateral bulge amplitude); > 0 required',
}
