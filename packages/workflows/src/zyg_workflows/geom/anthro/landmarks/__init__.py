# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Anatomical landmarks on the anny 13,718-vertex cage — and an honest record of which
ones are not there at all.

WHY THIS MODULE EXISTS
Every anthropometric ratio is a quotient of two landmark heights, so a landmark that is
5% off silently poisons every gate downstream. The trap is not arithmetic, it is
DEFINITION: "shoulder width" is biacromial or bideltoid or a circumference; "waist" is the
rib-iliac midpoint or the iliac crest or the narrowest coronal section, sites that differ
by up to 10cm in the same person; "leg length" is four different landmarks. So every
landmark here carries the landmark it claims to be, the anchor that produced it, whether
that anchor is ISO-defined / vendor-shipped / ours, and a confidence. Nothing is named
after a survey landmark unless it IS that landmark.

THE SECOND TRAP is guessing vertex numbers. Hard-coded indices are unfalsifiable and rot
the moment the cage changes. Every anchor here is either (a) the support of a NAMED
MakeHuman morph target — the vertex set that target displaces, which is MakeHuman's own
statement about where an anatomical region is — or (b) a coordinate extremum with a
stated geometric definition, or (c) a vertex list shipped by anny itself. Where neither
exists, the landmark is reported UNRESOLVED rather than approximated. Five of the
requested landmarks are unresolved and that is the most useful thing this file says:
this cage has no vertebra prominens, no costal margin, no iliac crest, no radial styloid
and no lateral malleolus. Asking it for those numbers gets you a fabricated body.

THE THIRD TRAP is pose. The cage stands in an A-pose (measured: the hands sit at 0.53 of
stature with a half-span of 0.55m against a 1.69m body). ANSUR arm-landmark HEIGHTS —
wrist 0.4825 of stature — are taken with the arms hanging. Any height of an arm or hand
landmark from this cage is a pose coordinate and must never be compared to those tables.
The affected landmarks say so in their note.

WHAT ISO CONFORMANCE WOULD AND WOULD NOT MEAN HERE
ISO 20685-1 Table 4 bounds a MEAN difference over a validation sample, not a per-mesh
error, and per-mesh 4mm "accuracy" is meaningless anyway next to 14-19mm of diurnal
stature variation in a real person. Nothing in this module claims ISO conformance.
'anchor_kind': 'iso' means only that the landmark NAME and its anatomical definition come
from ISO 7250-1, and that we resolve it by that definition rather than by proxy.

Frame is established by measurement, not assumption — see frame_report(). Measured on
anny 0.5: +x is the subject's LEFT, +y is POSTERIOR, +z is SUPERIOR (an LPS frame), feet
at z minimum, and the cage is bilaterally symmetric to 0.017mm.
"""

# ruff: noqa: F401  this __init__ is a pure re-export surface: it must bind every
# name the pre-split module defined, used here or not.

# The submodules, imported in the original section order so module-level side
# effects (the sys.path bootstrap, the makedirs, the catalog literals) run in
# exactly the pre-split sequence.
from zyg_workflows.geom.anthro.landmarks import (  # noqa: E402
    constants,
    resolvers,
    table,
    validation,
)

from zyg_workflows.geom.anthro.landmarks.constants import (
    json,
    os,
    sys,
    np,
    _paths,
    MS,
    CAGE_VERTS,
    CAGE_FACES,
    REF_MALE,
    REF_FEMALE,
    REFERENCE_FRACTIONS,
    CERVICALE_OVER_SUPRASTERNALE,
    _CACHE,
    _support,
    _support_core,
    _anny_waist_ring,
    _coco,
    _axis_probe,
    frame_report,
    _check_topology,
)
from zyg_workflows.geom.anthro.landmarks.resolvers import (
    _context,
    _mask,
    _AXIS,
    _r_extreme,
    _r_support,
    _r_support_core,
    _r_support_extreme,
    _r_ring_const,
    _coronal_profile,
    _r_coronal_min,
    _mirror,
    _r_suprasternale,
    _r_acromion,
    _r_trochanterion,
    _r_dactylion,
    _r_unresolved,
    _RESOLVERS,
)
from zyg_workflows.geom.anthro.landmarks.table import (
    warm_cache,
    LANDMARK_SPEC,
    _SIDED_LABELS,
    _side_args,
    resolve_landmarks,
    _weights,
)
from zyg_workflows.geom.anthro.landmarks.validation import (
    SCRATCH,
    _ansur_check,
    _cases,
    main,
)
