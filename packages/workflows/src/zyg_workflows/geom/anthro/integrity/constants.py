# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""integrity.constants — Tolerances, shell-containment thresholds, topology scopes and the two timing helpers."""

import time


# ---------------------------------------------------------------------------------
# Tolerances. Read the provenance tag before changing one of these.
# ---------------------------------------------------------------------------------

# HOUSE. Duplicate-vertex radius, 1 micron. Rationale: the cage is stored float32, whose
# coordinate quantum at body scale (|x| ~ 0.5 m) is ~6e-8 m, so 1e-6 m sits ~17x above
# representational noise; and it is four orders below the 4mm ISO 20685-1 Table 4 height
# figure, so it can never mask a defect any anthropometric gate would care about.
EPS_DUPLICATE_M = 1e-6

# HOUSE. Zero-area face threshold, 1e-12 m^2. Calibrated against the issued cage: the
# SMALLEST triangle on the male original measures 6.737e-08 m^2 (measured 2026-08-05),
# five orders of magnitude above this line, so the threshold cannot produce a false
# positive on legitimate anny geometry.
EPS_AREA_M2 = 1e-12

# HOUSE. Numerical guard only, NOT a geometric tolerance: a signed plane distance below
# 1 nanometre is treated as exactly zero when classifying which side of a plane a vertex
# lies on. Below the float32 coordinate quantum, so it only ever snaps genuine ties.
EPS_PLANE_M = 1e-9

# HOUSE. Degenerate-normal guard for the triangle-triangle test: a triangle whose
# unnormalised normal is shorter than this has no well-defined plane. Such pairs are
# COUNTED AND REPORTED, never silently skipped.
EPS_NORMAL = 1e-20

# HOUSE, calibrated on MEASURED values. Morph-correctness symmetry gate.
#
# RE-CALIBRATED 2026-08-05 after the defect this gate was first tuned against was fixed.
# The original 0.05 mm was set to separate pure-morph bodies (0.0014-0.0229 mm) from the
# asymmetric abs_definition sculpt (2.93-3.76 mm). That sculpt is now symmetric by
# construction, which exposed the real floor underneath it: ANNY'S OWN LOCAL-MORPH TARGET
# DATA IS NOT BIT-MIRROR-SYMMETRIC. Measured over six bodies with the sculpt layer off —
# stock male/female 0.0167 mm, female original 0.0014, abel 0.0229, cornelis 0.0600,
# male original 0.0632 — the floor is 0.0632 mm and it rises with the number of fitted
# measure-* locals applied, i.e. it is the vendor data, not our geometry.
#
# 0.15 mm therefore clears that floor with ~2.4x headroom while still catching the defect
# that motivated the gate by ~25x. Setting it BELOW the floor (as 0.05 mm did) fails
# bodies that have nothing wrong with them, which is the failure mode that gets a gate
# switched off.
SYM_MORPH_TOL_MM = 0.15

# Radius quantiles for the self-intersection broad phase. HOUSE, tuned by measurement:
# on the issued cage these four bins cut the candidate-pair count from 22,560,245 to
# 1,804,258 (12.5x) with byte-identical narrow-phase input. Purely a cost knob — the
# result cannot depend on it, because every bin pair is queried at the sum of the two
# bins' true maximum radii.
_BROAD_BINS = (50.0, 90.0, 99.0)

SELF_INTERSECTION_NOTE = (
    'Broad phase: triangles binned by circumradius at percentiles %s; every bin pair '
    'queried at rmax_i + rmax_j, which is conservative by construction. Narrow phase: '
    'exact Moller interval-overlap triangle-triangle test. Pairs sharing >=1 vertex are '
    'excluded, which removes edge-adjacent and fan-adjacent neighbours. Pairs are then '
    'split by connected component: INTRA-component pairs are the shell penetrating '
    'ITSELF (a defect); INTER-component pairs are two different shells meeting, which on '
    'this cage is an eyeball in its socket and is not a defect at all.' % (_BROAD_BINS,)
)

# ---------------------------------------------------------------------------------
# Shell containment. Thresholds for deciding whether a separate shell sits inside the
# body, in a pocket of the body, or loose in the air outside it.
# ---------------------------------------------------------------------------------

# HOUSE, and it is not really a tolerance. For a closed, consistently wound shell the
# generalised winding number is exactly 1 inside and exactly 0 outside, so 0.5 is the
# midpoint of a gap that nothing legitimately occupies. MEASURED 2026-08-05 over all
# 1,480 non-body vertices of the four issued cages: every value came back within 1e-4 of
# 0 or 1, so the cut never had to adjudicate anything.
WINDING_INSIDE = 0.5

# HOUSE. Values inside this guard band around neither 0 nor 1 are INDETERMINATE — the
# point is on the surface, or the shell is not closed enough for the question to have an
# answer — and are reported as such rather than forced to a side.
WINDING_GUARD = 0.25

# DERIVED in one direction, HOUSE POLICY in the other, and the reason this file no longer
# ships a tuned "cavity" escape fraction. Let K = conv(body).
#
#   THE PROOF. For any point p outside K there is a hyperplane through p with all of K
#   strictly on one side, so every direction from p that meets the body lies in one OPEN
#   half-space: occluded < 1/2, escape > 1/2, for every body, every pose, every scale.
#   That is the direction used to CROSS-CHECK a defect call — an envelope-exterior point
#   whose measured escape does not exceed 1/2 is a warning that the ray sample and the
#   hull disagree, and it is recorded. It is NOT allowed to overturn the defect: the
#   envelope test is exact and the escape fraction is a SKY_DIRECTIONS-ray sample.
#
#   THE POLICY. The converse is NOT a theorem: a point inside K can still see sky in most
#   directions (a wide-open concavity is inside the hull). So for an envelope-INTERIOR
#   shell the bound is used as a requirement rather than a proof — a shell that reaches
#   open sky in MORE than half of all directions is not "in a pocket of the body" in any
#   ordinary sense, and this file refuses to call it one. It reports UNRESOLVED, which is
#   a defect state, rather than either benign verdict.
#
# MEASURED separation 2026-08-05, 12 cases on the issued male cage — envelope-interior
# shells that are genuinely in pockets (tongue; eyeball at bone_scale 0.55/0.70/0.80,
# 22-30 mm inside the envelope) escape 0.000-0.066, an order of magnitude below the line;
# envelope-exterior placements (tongue +120 mm anterior 0.79, +2 m 1.00, adrift between
# the thighs 0.57, adrift behind the knee 0.77) all exceed it. Nothing measured sits near
# 1/2, which is what a discriminator calibrated on ONE example (the retired 0.05, cleared
# by a legitimate recessed eyeball at 0.055) could not say.
ENVELOPE_ESCAPE_MAX_FRACTION = 0.5

# HOUSE, numerical guards for the convex-envelope test, both in metres and both far below
# any geometric feature on a body. A vertex counts as outside the envelope only beyond
# HULL_MARGIN_EPS_M (1 micron, the same duplicate-vertex quantum used above, ~17x the
# float32 coordinate quantum at body scale), and the hull is REJECTED as unusable unless
# it contains every body vertex to within HULL_VERIFY_TOL_M — qhull is not trusted on its
# own word, it is verified against the input it was built from.
HULL_MARGIN_EPS_M = 1e-6
HULL_VERIFY_TOL_M = 1e-9

# HOUSE, cost knobs. 32 Fibonacci directions from up to 8 evenly-strided vertices per
# shell: deterministic (no RNG anywhere in this file), and a sample, which the payload says
# out loud. Raising them costs linear time. 32 directions resolve the escape fraction to
# 0.031; the only line it is ever compared against is the derived 1/2 above, and the
# measured gap around that line is 0.066 vs 0.51 (see ENVELOPE_ESCAPE_MAX_FRACTION), i.e.
# ~14 rays wide on either side.
SKY_DIRECTIONS = 32
SKY_PROBE_VERTICES = 8

# HOUSE, ODD ON PURPOSE. Directions for the ray-parity cross-check of the winding number.
# A single ray can graze an edge or strike a vertex and come back with the wrong parity,
# so the verdict is a majority vote; an odd count makes a tie impossible.
PARITY_DIRECTIONS = 9

# HOUSE. Winding number is O(points x faces), so a pathological input (a cage that
# fragments into thousands of shells) must not turn a 1.5 s check into an hour. Both caps
# are recorded in the payload whenever they bind, so a truncated analysis can never be
# mistaken for a complete one.
MAX_SHELLS_ANALYSED = 32
MAX_CONTAINMENT_PROBE_VERTICES = 512

# HOUSE. "The body" is the component with the largest BOUNDING-BOX DIAGONAL: the biggest
# object in the file is the person. Vertex count is the wrong signal and was tried first —
# a densely tessellated shell can outnumber a body it would fit inside, and on a plain
# two-sphere test a shell at 1/5 the size already carried 1/4 of the vertices. Size is the
# question being asked, so measure size.
#
# The identification is only safe while it is unambiguous, so if a second face-bearing
# component reaches 1/N of the body's diagonal, this check REFUSES to classify rather than
# guessing which shell is the person — two bodies in one file is a real thing that happens
# and silently measuring one of them would be worse than saying nothing.
BODY_DOMINANCE_MIN_RATIO = 2.0

# MEASURED 2026-08-05 on the four issued cages. Signatures used to put a name on a shell.
# A name here is a convenience for the operator, never an input to a gate: every entry
# carries the evidence that matched and a confidence, and an unmatched shell is reported
# as unidentified with its geometry rather than guessed at.
SHELL_SIGNATURES = (
    {
        'name': 'tongue',
        'vertices': 226,
        'z_frac': (0.85, 0.92),
        'midline': True,
        'provenance': 'MEASURED 2026-08-05, n=4 issued cages: 226 v, midline, z 0.874-0.893 of stature',
    },
    {
        'name': 'eyeball',
        'vertices': 72,
        'z_frac': (0.90, 0.96),
        'midline': False,
        'provenance': 'MEASURED 2026-08-05, n=4 issued cages: two mirrored 72 v shells, z 0.918-0.941 of stature',
    },
)

# HOUSE. A shell counts as ON THE MIDLINE when its centroid sits within this fraction of
# stature of the sagittal plane. 0.5% of stature is 8-9 mm on these bodies; the tongue
# measures |cx| < 1e-4 m and the eyeballs 29-33 mm, so the two populations are nowhere
# near the line.
MIDLINE_FRAC_OF_STATURE = 0.005

# ---------------------------------------------------------------------------------
# Topology scopes. The anny/MakeHuman cage ships eyes and a tongue as separate closed
# shells, so "how many vertices does the body have" has more than one right answer and
# the caller MUST say which one it means.
# ---------------------------------------------------------------------------------
TOPOLOGY_SCOPES = {
    # MEASURED 2026-08-05 on data/assets/mesh_skeletons/{originals,derived}/*/skeleton_*.glb,
    # all four issued meshes identical: anny create_fullbody_model(local_changes='all').
    'full': {
        'vertices': 13718,
        'faces_quad': 13710,
        'faces_tri': 27420,
        'components': 4,
        'provenance': 'MEASURED 2026-08-05, n=4 issued meshes (male, female, abel, cornelis) — body + tongue + 2 eyes',
    },
    # MEASURED 2026-08-05: the largest connected component of the same cage, i.e. the
    # body shell with tongue and eyes dropped.
    'body': {
        'vertices': 13348,
        'faces_quad': 13346,
        'faces_tri': 26692,
        'components': 1,
        'provenance': 'MEASURED 2026-08-05 — largest connected component of the issued '
        'cage (tongue 226v + 2 eyes 72v each = 370v removed)',
    },
    # DECLARED in the research briefing as the "excluding tongue+eyes" scope. It is NOT
    # what this cage produces: measurement gives 13348/13346, not 13380/13378 — a
    # difference of exactly 32 vertices and 32 quads. The figure is kept so a caller who
    # declares it gets a loud, specific failure instead of a silent mismatch, but it must
    # NOT be treated as describing our asset until someone reconciles it.
    'makehuman_base_excl': {
        'vertices': 13380,
        'faces_quad': 13378,
        'faces_tri': 26756,
        'components': None,
        'provenance': 'DECLARED (research briefing) — NOT REPRODUCED by measurement on '
        'our cage, which gives 13348/13346. Do not rely on this scope.',
    },
}


def _now():
    return time.perf_counter()


def _ms(t0):
    return round((_now() - t0) * 1000.0, 3)
