# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""LOAD-BEARING CONSTANTS, and the error every refusal in this package raises.

Moved verbatim out of the old single-file scan_ingest.py (lines 187-396).
"""

SCHEMA = 'geom.scan_ingest/1'

STAGES = ('sfm', 'scale', 'dense', 'align', 'residual', 'emit')

# ----------------------------------------------------------------------------------
# LOAD-BEARING CONSTANTS
# ----------------------------------------------------------------------------------

# THE CUTOFF. This is the number that decides what counts as "proportion" (discarded) and
# what counts as "detail" (kept), and it is derived from two measured length scales rather
# than picked to make anything pass:
#
#   UPPER BOUND — the shortest thing we are willing to call a PROPORTION. The shortest
#   segment in the ANSUR chain we actually gate on is the upper arm (acromion-to-radiale),
#   ~0.18 of stature; the thigh is ~0.25 S. A displacement feature whose wavelength is
#   comparable to a segment length IS a proportion change, and must not survive.
#
#   LOWER BOUND — the widest thing we are willing to call DETAIL. The bony relief features
#   this pipeline exists to recover are, at their widest, the zygomatic arch and the
#   clavicular crest: both under 0.05 S across. Everything narrower (malleolus, olecranon,
#   ulnar head, patellar border) is smaller still.
#
# 0.08 S sits between them with roughly a factor of 1.6 of clearance on each side. At
# S = 1.68 m that is 134 mm. Raising it towards 0.18 S starts admitting real proportion;
# lowering it towards 0.05 S starts cutting into the clavicle we came for.
#
# The value is NOT a promise about the filter — filters are not brick walls. stage_residual
# MEASURES the achieved attenuation at this wavelength on the actual mesh and reports it.
RESIDUAL_CUTOFF_FRAC = 0.08

# Butterworth order for the default separator.
#
# THE FIRST VERSION OF THIS COMMENT OVER-CLAIMED, on one body's evidence, and the
# correction is the useful part. On the FEMALE original, real-field selectivity falls
# monotonically past order 2 (6.46 / 6.27 / 5.97 for n = 2 / 4 / 8) because mid-scale
# leakage climbs faster than detail passage improves — so I wrote that sharper is
# monotonically worse. Re-measured on the MALE original, the effect is not there:
# n=2 gives 6.41 and n=4 gives 6.43, a reversal well inside body-to-body variation.
#
# THE HONEST STATEMENT: orders 2 and 4 are equivalent within the spread between bodies.
# Two is chosen because it is CHEAPER — one complex sparse factorisation instead of two —
# not because it was shown to separate better. One body is not a population, and a
# constant justified from a single subject is a house preference wearing a measurement's
# clothes.
#
# What DOES survive both bodies: order 8 is worse than either (female 5.97), and every
# Butterworth order beats the umbrella path it replaces by roughly 4-9x.
SCAN_BUTTERWORTH_ORDER = 2

# Umbrella-Laplacian diffusion step. 0.5 is the largest value that is unconditionally
# stable on a graph Laplacian normalised by valence (the operator's spectrum is in [0, 2],
# so alpha <= 0.5 keeps |1 - alpha * lambda| <= 1 -- alpha = 1.0 would exactly negate the
# highest mode each step instead of damping it).
LOWPASS_ALPHA = 0.5

# THE ITERATION GUARD, AND WHY IT IS NOT A CONSTANT ANY MORE.
#
# It used to be the flat number 4000, described in this very comment as "a guard, not a
# tuning knob". At DEFAULT_SUBDIV_LEVEL it was a tuning knob, and it tuned in the flattering
# direction. Required iterations scale as (lambda/h)^2, so halving the mean edge quadruples
# them: level 1 (h = 4.62 mm) converges at 2,969, level 2 (h = 2.31 mm) needs ~11.9k and
# level 3 (h = 1.15 mm) ~47k. A flat 4000 therefore CLAMPED the default level-2 path at a
# measured response of 0.6163 instead of 0.5 — an under-smoothed low-pass, which leaves LESS
# in the residual and so makes the honesty number `proportion_leakage` look BETTER (0.1925
# clamped vs 0.2954 converged at level 1). A guard that only ever binds in the direction
# that flatters the result is not a guard.
#
# It is now derived from the analytic estimate for the mesh in hand, so it scales with
# resolution automatically and cannot bind on a legitimate configuration, while still
# stopping a runaway on a degenerate one. The multiplier is set from the measured ratio
# between the analytic estimate and the calibrated answer: 2969 / 59 = 50.3 at level 1 (the
# analytic heat-kernel argument under-counts badly on an irregular mesh, which is the whole
# reason _calibrate_lowpass exists). 4x that ratio is the guard.
LOWPASS_ITER_GUARD_MULT = 200
# ...and an absolute backstop so a pathological mesh cannot ask for an unbounded run. 200k
# umbrella steps on the level-3 cage is ~40 minutes; anything past that is a broken mesh,
# not a fine one. A run that HITS either limit is refused by stage_residual, never reported.
LOWPASS_ITER_HARD_CAP = 200000

# How close the MEASURED response at the cutoff wavelength must get to 0.5 before the
# calibration in _calibrate_lowpass stops. 0.01 is a hundredth of amplitude — far below
# anything that changes which features survive, and reachable in a handful of rounds
# because each round costs 3 probe smooths. The round cap is a non-convergence guard.
CALIBRATION_TOL = 0.01
CALIBRATION_MAX_ROUNDS = 12

# Subdivision level the residual is measured and emitted at. THE MEASURED REASON:
#   cage      13,718 verts, mean edge  9.36 mm at S = 1.680 m -> Nyquist wavelength 18.7 mm
#   subdiv 2 219,368 verts, mean edge  2.31 mm                -> Nyquist wavelength  4.6 mm
#   subdiv 3 877,448 verts
# A clavicular ridge is ~20-30 mm across. At cage resolution that is 2-3 samples per
# period, i.e. exactly at the sampling limit, which is why relief built at cage level
# measured flat. Subdivision 2 widens the representable detail band by ~4x in wavelength
# for ~16x the vertices. Level 2 is also DISPLAY_SUBDIV, so the residual lands on the
# surface the stills are actually rendered from.
DEFAULT_SUBDIV_LEVEL = 2

# Correspondence rejection for the shrinkwrap, in fractions of stature.
#   SUPPORT: no scan sample within this distance of a cage vertex -> that vertex is a
#   COVERAGE HOLE and contributes nothing. Poisson invents surface; this is what stops the
#   invented surface being read back as a measurement. 0.01 S = 16.8 mm at S = 1.68.
SHRINKWRAP_SUPPORT_FRAC = 0.010
#   MAX: a correspondence further than this is a different body, not a detail. It is still
#   USED (the low-pass is what removes it) but it is reported, because a scan where most of
#   the field is this large is telling you the alignment failed.
SHRINKWRAP_MAX_FRAC = 0.050

# Sparse-point quality filter. A 3D point seen in only 2 images has no redundancy and no
# way to detect a wrong match; from 4+ views a bad match becomes a rejectable outlier.
MIN_TRACK_LENGTH = 4
MAX_REPROJ_ERROR_PX = 2.0

# Normal estimation neighbourhood for the oriented point cloud Poisson needs.
NORMAL_KNN = 16

# Dense stereo pair selection.
SGBM_MIN_TRI_ANGLE_DEG = 5.0  # below this the depth is badly conditioned
SGBM_MAX_TRI_ANGLE_DEG = 30.0  # above this the appearance change breaks block matching
SGBM_MIN_SHARED_POINTS = 60  # co-visibility floor from the SfM track graph
SGBM_MAX_PAIRS = 120
SGBM_MAX_IMAGE_PX = 1200  # long edge; SGBM cost is O(W*H*D) on CPU

# How far outside the sparse cloud's robust bounding box a dense point may lie before it
# is treated as a stereo blunder rather than surface. 0.15 is one seventh of the body's
# own extent — wide enough that nothing real is clipped, narrow enough that the arbitrary-
# depth mismatches two-view stereo produces cannot survive.
DENSE_BBOX_MARGIN = 0.15

# Minimum |Tx| / |T| for a stereo pair to be usable: cv2.StereoSGBM searches along image
# rows only. 0.8 keeps pairs whose rectification is unambiguously horizontal.
SGBM_MIN_HORIZONTAL_BASELINE = 0.8

# Widest disparity search SGBM is allowed. Cost is O(W*H*D) on CPU; a pair whose predicted
# disparity range exceeds this is a wide-baseline pair that block matching would handle
# badly anyway, so it is skipped rather than made expensive.
SGBM_MAX_DISPARITY_PX = 512

# cv2.stereoRectify alpha. 0 crops to the all-valid rectangle, which on cross-ring pairs
# cropped so hard that fewer than 30 sparse points survived on screen and 36 of 62 pairs
# were rejected for 'no_sparse_support'. -1 is OpenCV's default scaling and keeps the
# subject in frame; the invalid border costs nothing because SGBM finds no match there.
SGBM_RECTIFY_ALPHA = -1

# Global ceiling on the dense cloud. Cost is dominated by the k-NN normal estimation and
# by Poisson, both roughly linear in points but with large constants; 62 usable pairs at
# 40k points each is ~2.5e6, well past the point where extra points add information
# rather than time. Subsampling is deterministic (fixed seed) so a re-run reproduces.
DENSE_MAX_POINTS = 1200000

# Whether the Poisson mesh may be used as the scan surface. FALSE on this machine — see
# _scan_points_m for the measured reasons (FLT_MAX sentinel vertices, non-finite entries,
# a degenerate origin blob, and an ICP that converged to 7 micrometres against it).
USE_POISSON_MESH_AS_SCAN = False

# Worst nearest-neighbour distance allowed when matching mesh_skeletons._subdivide vertex
# order to relief_subdiv.subdivide vertex order (see stage_emit). The two subdividers agree
# on the limit surface to 3.4e-8 m measured on the female cage at level 1 — that is
# float64 round-off on a 1.68 m body, not a geometric difference. 1e-5 m (10 micrometres)
# is three orders of magnitude above the observed round-off and four below the 2.31 mm mean
# edge at subdiv 2, so it cannot accidentally accept a neighbouring vertex.
PERM_MATCH_TOL_M = 1e-5

VALID_SCALE_KINDS = ('stature_m', 'point_pair_m', 'camera_baseline_m', 'explicit_factor')

CONSENT_REQUIRED_KEYS = (
    'subject',
    'granted_by',
    'date',
    'licence',
    'licence_evidence',
    'document',
    'recognisable_likeness_permitted',
)

# Shortest string that can plausibly be a record of anything. 'x' is not a subject name and
# '.' is not a date; this stops a placeholder passing the type check. It is deliberately
# small — the gate's job is to refuse nulls and stubs, not to parse English.
CONSENT_MIN_FIELD_CHARS = 3

# Third-party licences, read off the installed distributions in this venv on 2026-08-07.
# House rule: commercial publication requires Apache-2.0 / MIT / BSD / CC0 / public domain.
SOFTWARE_LICENCES = {
    'pycolmap': {
        'licence': 'BSD-3-Clause',
        'evidence': "installed dist-info METADATA 'License: BSD-3-Clause'; the "
        "bundled LICENSE.txt opens 'The COLMAP library is licensed "
        "under the new BSD license.'",
    },
    'opencv-python': {
        'licence': 'Apache-2.0',
        'evidence': "installed dist-info METADATA 'License: Apache 2.0' + "
        "classifier 'License :: OSI Approved :: Apache Software "
        "License'",
    },
    'trimesh': {
        'licence': 'MIT',
        'evidence': "installed dist-info METADATA 'The MIT License (MIT)' + "
        "classifier 'License :: OSI Approved :: MIT License'",
    },
    'numpy': {'licence': 'BSD-3-Clause', 'evidence': "classifier 'License :: OSI Approved :: BSD License'"},
    'scipy': {'licence': 'BSD-3-Clause', 'evidence': "classifier 'License :: OSI Approved :: BSD License'"},
}


class ScanIngestError(Exception):
    """Raised when the ingest cannot proceed on evidence it has. Never softened into a
    default: every path that would have to guess a number instead raises here."""
