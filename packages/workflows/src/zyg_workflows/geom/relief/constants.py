# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

# ruff: noqa: F401
# F401: this module inherited the original top import block of relief.py. Every name
# in it is re-exported by the package __init__ and imported by the sibling
# sections, so nothing here may be pruned as unused.
"""constants — a verbatim section of the pre-split relief.py.

The module docstring that documented the whole layer lives in the package
__init__.py; nothing in this file was rewritten, renamed or retuned.
"""

import sys

import numpy as np
import logging as _zyg_logging

# channel kept from the pre-split module
_zyg_log = _zyg_logging.getLogger('zyg_workflows.geom.relief')


SCHEMA = 'geom.relief/1'

# The key in a character's anatomy dict. Same convention as 'abs_definition': a float
# scale, absent or <= 0 meaning the layer does not run at all.
ANATOMY_KEY = 'bony_relief'

# ---------------------------------------------------------------------------------
# geometry constants — all in FRACTIONS OF STATURE unless the name says otherwise
# ---------------------------------------------------------------------------------

# Compact support radius of every feature's falloff. Set strictly inside
# ridge.RIDGE_GAP_FRAC (0.008) — the inner edge of the collar that ridge_relief and
# region_relief measure a feature AGAINST — so the layer physically cannot raise its own
# reference surface. 13.9 mm at 1.85 m, 12.6 mm at 1.68 m. Checked at import by
# _check_falloff_inside_collar().
FALLOFF_FRAC = 0.0075

# A bone anchor is put on the skin by PROJECTING ALONG ITS ASPECT, not by taking the
# nearest vertex in 3D. "The skin over the clavicle" is the surface the antero-superior
# ray from the bone hits; the nearest vertex in 3D to a bone that is 53 mm deep is often
# on a different structure entirely, and that is how a clavicle predicate ends up on the
# trapezius. Two independent limits, both reported per seed:
#   TISSUE_MAX_FRAC  how far along the aspect the skin is allowed to be. 0.075 of stature
#                    = 139 mm at 1.85 m. Generous, because the sternoclavicular end of
#                    this rig's clavicle measures 53 mm deep and the sacrum more.
#   PERP_MAX_FRAC    how far the ray is allowed to MISS the vertex it lands on, sideways.
#                    0.020 of stature = 37 mm at 1.85 m, which is about 1.5 cage edges in
#                    the torso (median torso edge 20-27 mm). Beyond this the ray did not
#                    hit the surface near the landmark and the seed is REFUSED, not moved.
# A small negative t is admitted so an anchor that is ALREADY on the surface — the iliac
# crest stations are taken as surface points by construction — can seed itself.
TISSUE_MAX_FRAC = 0.075
PERP_MAX_FRAC = 0.020
TISSUE_MIN_FRAC = -0.004

# Mirror pairing tolerance, in fractions of stature. Same constant _apply_anatomy uses:
# 1.0 mm on a 1.85 m body, ~16x above the 0.0632 mm real mirror residual of the issued
# male cage and well under the 0.2517 mm closest-distinct-vertex spacing.
MIRROR_TOL_FRAC = 5.4e-4

# Newell-normal mirror residual we require before trusting the direction field. Measured
# 2.4e-3 on this cage (against 1.168 for the corner-(0,1,2) normals). This is a guard on
# the mesh, not a tunable: a cage that fails it is not mirror-symmetric and the layer
# says so instead of quietly producing an asymmetric body.
NEWELL_MIRROR_MAX = 0.05

# HOW DENSELY AN ANCHOR CURVE IS SAMPLED, and why this is not a free parameter.
# Stations sit 0.6 of the falloff radius apart, so consecutive falloff discs overlap at
# about half amplitude — the crest is continuous, and it is not OVER-sampled. Oversampling
# is not harmless: it ALIASES. Measured on originals/male, sampling the clavicle at 30
# stations (4.0 mm, well under the 14.6 mm median cage edge in that window) made the
# aspect ray wobble between two adjacent vertex ROWS, so both rows were seeded and the
# crest came out a plateau — clavicle_shaft measured ridge/run 2, +8.25 mm at contrast 4.6
# (RESOLVES) at 8.3 mm spacing and point_only/run 1, +7.76 mm at contrast 3.6 (does not)
# at 4.0 mm. The rule below is written against the falloff, not against a body, so it
# adapts to curve length and stature without anybody choosing a number per feature.
STATION_SPACING_FRAC = 0.6 * FALLOFF_FRAC  # 8.3 mm at 1.85 m, 7.6 mm at 1.68 m

# THE FACET OPERATOR. A Laplacian/umbrella smoother was tried first and measurably does
# not do the job: it removes high-frequency curvature, and what makes a shank not a facet
# is the LIMB'S OWN CYLINDER curvature (measured max |k| 55 1/m on the strip). Four
# umbrella passes moved planarity_ratio from 0.04496 to 0.04468 — nothing. So the facet is
# a least-squares PLANE PROJECTION instead: in the strip's own (arc, aspect) frame the
# surface offset h is fitted as h = alpha + beta*arc — a RULED plane, which lets the tibial
# surface taper distally as it really does — and each vertex is pulled toward that fit,
# capped so the operator can never gouge.
FACET_CAP_FRAC = 0.004


# ---------------------------------------------------------------------------------
# amplitudes — the priority ladder, in fractions of stature
# ---------------------------------------------------------------------------------
# Sign is the anatomy: + is a prominence, - is a fossa/pit. Nothing here is tuned against
# our own bodies; the values are the brief's ladder, which sits on the three landmarks
# this cage actually resolves (patella 5.3e-3 > epicondyle_lat 4.0e-3 > epicondyle_med
# 2.7e-3, null 2.45e-3). Where a delivered amplitude lands below the null after its
# conditional is applied, THAT IS REPORTED AS A FINDING and the threshold is not moved.
AMP = {
    'clavicle_ridge': +3.0e-3,
    'infraclavicular_fossa': -2.5e-3,
    'jugular_notch': -4.0e-3,
    'supraclavicular_fossa': -3.0e-3,
    'acromion': +2.4e-3,
    'olecranon': +4.0e-3,
    'ulnar_head': +2.8e-3,
    'ulnar_border': +1.6e-3,
    'malleolus_med': +3.2e-3,
    'malleolus_lat': +2.6e-3,
    'asis': +3.2e-3,
    'iliac_crest': +2.2e-3,
    'psis': -2.2e-3,
    'c7': +3.0e-3,
    'nuchal_furrow': -2.0e-3,
}

# The medial malleolus apex sits this much HIGHER than the lateral one. The single most
# taught malleolar fact in figure drawing and currently absent: the two sides of this
# cage differ by 0.9 mm, inside its own noise.
MALLEOLUS_HEIGHT_OFFSET_FRAC = 6.0e-3
# ...and the lateral malleolus is set POSTERIOR of the medial one by this much.
MALLEOLUS_LAT_POSTERIOR_FRAC = 6.0e-3

# PSIS dimple separation from the midline. From the brief; the sacral window of this cage
# holds 5 vertices on the male original, so whether the tessellation can carry a pair of
# pits at this separation is an open question the report answers with a measurement.
PSIS_HALF_SEPARATION_FRAC = 0.020
# PSIS height below iliocristale. HOUSE: the posterior superior iliac spines sit at about
# the S2 level, roughly a fifth of the pelvic height below the crest. Nothing on this cage
# confirms it.
PSIS_BELOW_CREST_FRAC = 0.045

# Iliac crest arc: azimuth sweep about the pelvic axis, measured from ANTERIOR toward
# LATERAL, and the crest's own height profile. The crest is highest at the tubercle
# (mid-lateral) and drops to the ASIS in front and to the PSIS behind. Drops are HOUSE.
CREST_AZIMUTH_DEG = (18.0, 158.0)
CREST_DROP_ANTERIOR_FRAC = 0.020
CREST_DROP_POSTERIOR_FRAC = 0.028
CREST_N_STATIONS = 40

# These counts sample the anchor curve's SHAPE densely; _resample() then reduces every
# curve to the station spacing above before any of it touches the mesh. Shape fidelity and
# seeding density are different questions and are set separately.
# Clavicle S-curve: peak deviation of the crest line from the bone's own chord, and the
# arc fraction at which the deviation changes sign. AFS: medial two thirds convex
# anteriorly, lateral third concave anteriorly — ONE anterior-posterior sign change, at
# about two thirds of the shaft. The deviation amplitude is HOUSE (9.3 mm at 1.85 m).
CLAVICLE_S_AMPLITUDE_FRAC = 0.005
CLAVICLE_S_CROSSING = 0.62
CLAVICLE_N_STATIONS = 60

# Ulnar border: stations between the olecranon and the head of the ulna. The reference
# makes CONTINUITY the gate for this one and explicitly says polarity is not — it reads
# as a ridge or as a furrow depending on rotation — so it is built as a ridge and probed
# with polarity='either'.
ULNAR_BORDER_N_STATIONS = 60

# Nuchal furrow: midline channel from the external occipital protuberance down to C7.
NUCHAL_N_STATIONS = 40

# The anteromedial tibial FACET. A plane, not a ridge: |curvature| <= 0.5e-3 of stature is
# the target the brief sets, and the fibula shaft opposite it is the NEGATIVE CONTROL that
# must show zero relief.
# NOTE, MEASURED: the strip's half-width is NOT a free constant here — it is FALLOFF_FRAC,
# because that is where the displacement field is allowed to reach. 13.9 mm at 1.85 m, so
# the facet is ~28 mm wide, and a 28 mm patch on a ~40 mm-radius shank is already planar to
# about 2.5 mm. That is why the projection has almost nothing to correct; see (c) in the
# module docstring.
TIBIAL_FACET_CURVATURE_TARGET_FRAC = 0.5e-3

# Aspect gates. A landmark is subcutaneous on ONE aspect of the body; a seed snapped to
# the far side of the same limb would be a different landmark. Each entry is a direction
# in anny's frame (x lateral, +x = LEFT; y anterior-posterior, -y = ANTERIOR; z up) and
# the minimum dot a candidate vertex's outward normal must have with it.
ASPECT_MIN_DOT = 0.15


# ---------------------------------------------------------------------------------
# conditionality — what makes this a gate rather than a constant
# ---------------------------------------------------------------------------------
# Every conditional returns (scale, provenance). None of them is fitted to our bodies;
# each implements a direction the reference states, at a HOUSE slope, and the DELIVERED
# amplitude after scaling is reported per body so a reader can see where it landed
# relative to the null.


def cond_clavicle(macros):
    """Clavicular relief falls as the muscle macro rises — the pectoral and deltoid mass
    rolls over the bone. But the reference also says the clavicle is visible on every body
    in every arms-down pose and stays visible even on an obese scan, so the mechanism is
    mostly the SURROUND rising, not the crest shrinking: the crest itself takes the small
    slope here and cond_infraclavicular() takes the large one."""
    mu = float(macros.get('muscle', 0.5))
    s = 1.0 + 0.20 * (0.5 - mu) / 0.5
    return max(0.0, s), (
        'HOUSE. crest amplitude x (1 + 0.20*(0.5-muscle)/0.5), i.e. +20% '
        'on an unmuscled body and -20% at muscle=1.0. Direction from the '
        'reference; slope is HOUSE and deliberately SMALL because the same '
        'reference asserts the clavicle stays visible at any build.'
    )


def cond_infraclavicular(macros):
    """The infraclavicular fossa is where the pectoral mass actually goes. This carries the
    steep half of the muscle conditional: at muscle=1.0 the fossa is 45% shallower."""
    mu = float(macros.get('muscle', 0.5))
    s = 1.0 + 0.45 * (0.5 - mu) / 0.5
    return max(0.0, s), (
        'HOUSE. fossa depth x (1 + 0.45*(0.5-muscle)/0.5). This is the '
        '"pec rolls over it" term: the bone does not move, the hollow '
        'beside it fills in.'
    )


def cond_psis(macros):
    """PSIS dimples are FAT-conditional: required on a lean body, absent on a fat one. The
    thresholds are HOUSE — the reference gives the direction and the fact that there is a
    threshold, not a number."""
    w = float(macros.get('weight', 0.5))
    lo, hi = 0.62, 0.78
    s = float(np.clip((hi - w) / (hi - lo), 0.0, 1.0))
    return s, (
        'HOUSE. full depth at weight <= %.2f, fading linearly to ZERO at weight >= '
        '%.2f. The reference makes the dimples fat-conditional (required below a '
        'threshold, forbidden above); both threshold values are HOUSE.' % (lo, hi)
    )


def cond_asis(macros):
    """The ASIS and the anterior iliac crest read MORE on the female — male flank muscle
    buries them. gender is anny's macro, 0.0 = MALE, 1.0 = FEMALE (measured convention,
    see mesh_skeletons.ORIGINAL_SPEC)."""
    g = float(macros.get('gender', 0.0))
    mu = float(macros.get('muscle', 0.5))
    s = (1.0 + 0.35 * g) * (1.0 - 0.20 * max(0.0, mu - 0.5) / 0.5)
    return max(0.0, s), (
        'HOUSE. x (1 + 0.35*gender) x (1 - 0.20*max(0,muscle-0.5)/0.5). '
        'Both directions are from the reference — the female reads more, '
        'male flank muscle buries it; the slopes are HOUSE.'
    )


def cond_none(macros):
    return 1.0, 'unconditional'


CONDITIONALS = {
    'clavicle_ridge': cond_clavicle,
    'supraclavicular_fossa': cond_clavicle,
    'infraclavicular_fossa': cond_infraclavicular,
    'psis': cond_psis,
    'asis': cond_asis,
    'iliac_crest': cond_asis,
}
