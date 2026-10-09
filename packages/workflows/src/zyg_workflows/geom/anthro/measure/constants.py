# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The constants that carry an assumption rather than a measurement.

Moved verbatim out of the old single-file measure.py (lines 140-247).
"""

import logging as _zyg_logging

from zyg_workflows.geom.anthro import landmarks as LMK

_zyg_log = _zyg_logging.getLogger(__name__)

CAGE_VERTS = LMK.CAGE_VERTS
CAGE_FACES = LMK.CAGE_FACES


# ---------------------------------------------------------------------------------
# constants that carry an assumption rather than a measurement
# ---------------------------------------------------------------------------------
# HOUSE (task-specified). Whole-body density is an ASSUMPTION, never a property of this
# mesh: the cage has no lungs, no gut gas and no fat/lean split, so there is nothing in
# the geometry that could determine it. anny's own vendor code uses 980 kg/m^3 with the
# source comment "Assuming density of 980 kg/m^3 for simplicity"
# (anny/anthropometry.py, Apache-2.0). A 5% error in this constant is a 5% error in every
# derived mass and BMI, which is larger than any gate downstream — which is why mass and
# BMI are tagged 'derived-with-an-assumption' and never 'MEASURED'.
BODY_DENSITY_KG_M3 = 985.0
ANNY_VENDOR_DENSITY_KG_M3 = 980.0

# MEASURED, ISO 20685-1:2018 Table 4 — maximum allowed MEAN difference between a
# scan-extracted and a manually taken dimension, over a validation sample. Mirrored from
# the reference pack when it is present so the two cannot drift; this literal is the
# fallback for a process that has no pack built.
ISO_20685_1_TABLE4_MM = {
    'segment_length': 5,
    'height': 4,
    'circumference_large': 9,
    'circumference_small': 4,
    'breadth': 4,
    'depth': 5,
    'head_without_hair': 1,
    'head_with_hair': 2,
    'hand': 1,
    'foot': 2,
}
ISO_CAVEAT = (
    'ISO 20685-1 Table 4 bounds a MEAN difference across a validation sample, '
    'not a per-mesh error. Per-mesh use is HOUSE policy.'
)

# HOUSE. The A-pose acceptance window, chosen with margin around what the four issued
# characters actually measure (hand-support centroid at 0.529-0.562 of stature, half-span
# 0.307-0.370 of stature — measured 2026-08-05 on anny-neutral, male, female, abel,
# cornelis). It exists to reject a T-pose (half-span near 0.50) or an arms-down rest pose
# (half-span near 0.13), where the loop-separation argument for excluding the arms and the
# limb-axis girth planes both stop holding.
POSE_HAND_FRAC_STATURE = (0.45, 0.65)
POSE_HALFSPAN_FRAC_STATURE = (0.25, 0.45)
# HOUSE. THIS IS NOT A SYMMETRY GATE and must not be used as one. The only thing this
# file needs from symmetry is that landmarks.py's MIRROR MAP still pairs a left landmark
# with its true right twin, because every _r landmark is produced by that map. 10 mm is
# the ceiling of the realism-asymmetry band the reference pack describes (population mean
# 5.2 mm), i.e. the largest left-right difference that could still be a body rather than a
# broken build.
#
# The morph-correctness symmetry check — expected value EXACTLY zero, gated at 0.05 mm —
# belongs to geom.anthro.integrity.mirror_symmetry and is deliberately NOT duplicated
# here; the reference pack is explicit that the two checks answer different questions and
# must stay separate. Measured 2026-08-05 for the record: the raw morph output is
# symmetric to 0.0014-0.0632 mm on all four characters, but MS._apply_anatomy's
# abs_definition sculpt is NOT mirror-equivariant and pushes the male original to
# 3.7648 mm and cornelis to 2.9324 mm. That is a build defect for integrity.py to rule
# on, not a reason to refuse to measure.
MIRROR_MAP_VALIDITY_MAX_MM = 10.0
MIRROR_MAP_ADVISORY_MM = 0.05

# HOUSE. Plane offset used only when a slicing plane lands exactly on a vertex, which
# would otherwise emit a degenerate one-vertex loop. 1 picometre is 10^-9 of a body.
PLANE_NUDGE_M = 1e-9
PLANE_DEGENERATE_M = 1e-12

# HOUSE. Height step for the scans that look for a maximum or minimum girth. 0.002 of
# stature is 3.7 mm on the 1.85 m male, comfortably finer than the 9 mm ISO class of a
# large circumference.
SCAN_STEP_FRAC = 0.002

# Morph targets whose supports define "this vertex belongs to an arm". The deltoid
# targets are excluded on purpose: the deltoid is arm tissue but sits over the shoulder,
# and including it would flag every chest slice.
#
# THIS MASK IS A DETECTOR, NOT A DECIDER. Measured on the male original, the mask reaches
# in to |x| = 225 mm while the torso's own chest silhouette reaches 242 mm, so a few
# axillary triangles land inside a perfectly clean torso loop and "any arm triangle in the
# torso loop" as a rule refuses a measurement that is fine (it refused chest circumference
# on the male). The rule that actually works is topological and lives in _arm_merge_check:
# if both arms are present as their own loops in the same plane, the torso loop cannot
# contain an arm, whatever the mask says.
ARM_MASK_LABELS = (
    'l-upperarm-scale-vert-incr',
    'r-upperarm-scale-vert-incr',
    'l-lowerarm-scale-vert-incr',
    'r-lowerarm-scale-vert-incr',
    'l-hand-scale-incr',
    'r-hand-scale-incr',
)

# The SECOND arm mask, and the one that actually decides. Bone-name substrings whose
# skinning weight makes a vertex arm rather than trunk. This is the same rule
# geom/fit_reference.py::_kept_mask uses to keep the reference body's lowered arms out of
# the chamfer fit, minus the foot/toe entries it needs and this module does not.
#
# CLAVICLE AND SHOULDER01 ARE DELIBERATELY ABSENT and must stay absent: they carry genuine
# shoulder breadth, and masking them would delete the trunk's own shoulder from every
# breadth taken above the axilla. Measured on this cage: 48 of the 163 bones match, and
# 4,246 of 13,718 vertices reach the 0.5 threshold.
ARM_BONE_SUBSTRINGS = ('upperarm', 'lowerarm', 'wrist', 'hand', 'finger', 'thumb', 'metacarpal')
ARM_BONE_KEEP_SUBSTRINGS = ('clavicle', 'shoulder01')
# HOUSE, inherited from _kept_mask: a vertex whose masked-bone weights sum to at least
# this is arm. Half the vertex belongs to the arm bones, so the arm moves it more than the
# trunk does. Deliberately NOT tuned: the sensitivity was measured (see the module
# docstring) and no threshold below 0.5 reproduces a genuine re-pose — on the male the
# error against the re-posed trunk swings from +20.4 mm at 0.1 to -54.1 mm at 0.05 — so a
# lower cut would be a fudge fitted to one body, not an arm/not-arm decision.
ARM_SKIN_WEIGHT_THRESHOLD = 0.5
