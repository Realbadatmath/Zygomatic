# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""angles.py imports, the printed CANON bands, the HOUSE constants and the
frame/context helpers every section below is built on."""

# ruff: noqa: F401
#   F401: this module inherits angles.py's original top import block byte-for-byte;
#         argparse/json/math/time are re-imported by the sibling sections that use
#         them, and deleting them here would edit a range promised byte-for-byte.

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

# channel kept from the pre-split module
_zyg_log = _zyg_logging.getLogger('zyg_workflows.geom.form.angles')


SCHEMA = 'geom.form.angles/1'

# Provenance tag for a number printed in an artist-anatomy reference. Ranked BELOW
# geom.anthro.gates.MEASURED (survey microdata) and above HOUSE. The ranking is enforced by
# BANDS[...]['blocks_over_measured'] being False everywhere in this file: no CANON band may
# block-fail a quantity for which a MEASURED source exists. None of these seven quantities
# has one — ANSUR II, CDC and NHANES are entirely linear — which is why CANON is the best
# evidence available here and is recorded as such rather than silently promoted.
CANON = 'CANON'
# Ours, and said so. Used by subcostal_angle, whose printed CENTRES are CANON but whose
# band WIDTH is this package's own — see that row.
HOUSE = 'HOUSE'

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
    'landmarks.frame_report). A SAGITTAL tilt is POSITIVE when the SUPERIOR '
    'end lies POSTERIOR of the inferior end. A CORONAL tilt is POSITIVE when '
    'the LATERAL end lies SUPERIOR to the medial end.'
)

# ---------------------------------------------------------------------------------
# THE PRINTED BANDS. Every one of them is CANON.
# ---------------------------------------------------------------------------------
# 'width_deg' is the number the resolution test is run against and it is ALWAYS the book's
# own: the width of the narrowest band the source prints for that quantity, or, for a
# one-sided rule, the size of the tolerance itself. It is never chosen by us and never
# adjusted to admit one of our meshes.
BANDS = {
    # HeadNeck p.15 prints the mandibular (gonial) angle by sex and by age, and FacialExpr
    # p.26 prints the same numbers independently — the only cross-book-confirmed quantity
    # in the corpus. The adult male and female bands touch only at 120 degrees, which is
    # what would have made this the sharpest sex gate available, and the newborn-to-adult
    # progression is monotone, which is what a 12-year-old needs.
    'gonial_angle': {
        'quantity': 'mandibular (gonial) angle, ramus against body, sagittal projection',
        'provenance': CANON,
        'source': 'HeadNeck p.15 AND, independently, FacialExpr p.26',
        'bands': {
            'male_adult': (100.0, 120.0),
            'female_adult': (120.0, 140.0),
            'newborn': (135.0, 150.0),
            'elderly_edentate': (125.0, 145.0),
        },
        'floor_deg': 90.0,
        'width_deg': 15.0,  # narrowest printed band (newborn, 135-150)
        'skeletal': True,
        'note': 'a SKELETAL angle, read off a dry mandible or a lateral cephalogram. Any '
        'surface construction measures the SOFT-TISSUE jaw angle instead, which '
        'carries masseter and subcutaneous fat over the mandibular angle and is a '
        'different quantity with an unmeasured offset. Ordering claims (male below '
        'female, child above adult) survive that offset; the absolute band does '
        'not.',
    },
    # AFS p.13 contrasts the male and female thorax at the xiphoid: the angle between the
    # two costal margins is about 90 degrees on the male and about 60 on the female. A 30
    # degree separation is a real dimorphism signal, and it is the reason the costal margin
    # is worth a sculpt layer (plan section 2, priority 7).
    'subcostal_angle': {
        'quantity': 'subcostal angle, between the costal margins at the xiphoid',
        # HOUSE ON CANON CENTRES, corrected 2026-08-08 to match the registry, which
        # adjudicated this row and was right. AFS p.13 prints two SINGLE VALUES, ~90 deg
        # male and ~60 deg female, and no dispersion whatever; the +/-12 deg half-width
        # that turns them into [78,102] and [48,72] came from this package's own plan
        # document, so citing "the plan" for it is a circular citation and under rule 5
        # it has no external source at all. The centres are CANON, the WIDTH is ours, and
        # a composite is tagged at the weaker of its two provenances.
        #
        # This row used to emit CANON on the threshold key. That outranks the registry's
        # HOUSE, so the engine refused the gate as POLICY_ERROR on every body — and the
        # refusal was doing real damage, because it replaced a genuine UNRESOLVED finding
        # (the costal margin does not exist on this cage: 0 of 325-348 probed vertices
        # clear the cage's own null p99) with a paperwork error.
        'provenance': HOUSE,
        'claim_provenance': CANON,
        'source': 'AFS p.13',
        'bands': {'male_adult': (78.0, 102.0), 'female_adult': (48.0, 72.0)},
        'width_deg': 24.0,
        'note': 'the book prints single values, ~90 male and ~60 female. The bands above '
        'are those values carried at the +/-12 degree spread the plan records for '
        'this row; the WIDTH used by the resolution test is that band width, and '
        'the 30 degree male-female separation is the discriminating quantity. The '
        'centres are CANON (claim_provenance); the width, and therefore the '
        'composite, is HOUSE.',
    },
    # AFS p.176. The sex term is a DIRECTION, not a threshold: female greater than male.
    'carrying_angle': {
        'quantity': 'carrying angle, humerus against forearm, elbow extended and forearm supinated',
        'provenance': CANON,
        'source': 'AFS p.176',
        'bands': {'both': (5.0, 15.0)},
        'width_deg': 10.0,
        'direction': 'female > male',
        'note': 'DEFINED AT FULL EXTENSION with the forearm supinated. Both preconditions '
        'are properties of the POSE, so a mesh in any other pose is out of the '
        "band's domain no matter what number the geometry yields.",
    },
    # HeadNeck p.43. A one-sided rule: the tilt is slightly positive and does not exceed
    # about +10 degrees. The tolerance IS the width.
    'canthal_tilt': {
        'quantity': 'canthal tilt, medial canthus to lateral canthus, coronal',
        'provenance': CANON,
        'source': 'HeadNeck p.43',
        'bands': {'both': (0.0, 10.0)},
        'width_deg': 10.0,
        'note': 'two claims in one line: a SIGN (slightly positive, lateral canthus above '
        'medial) and a CEILING (+10 degrees). They are reported separately because '
        'this cage resolves the ceiling and does not resolve the sign.',
    },
    # FacialExpr p.20. The long axis of the BONY orbital aperture, about 20 degrees from
    # horizontal. Printed as a single value with no tolerance.
    'orbital_long_axis': {
        'quantity': 'long axis of the bony orbital aperture, against horizontal',
        'provenance': CANON,
        'source': 'FacialExpr p.20',
        'bands': {'both': (20.0, 20.0)},
        'width_deg': None,  # a point value: the resolution test cannot run on it
        'note': 'a point value with no printed tolerance, so the operationalisation-spread '
        'test has nothing to run against and resolution rests entirely on whether '
        'an anchor exists. It does not.',
    },
    # HeadNeck p.77.
    'nasolabial_angle': {
        'quantity': 'nasolabial angle, columella tangent against the upper lip, at subnasale',
        'provenance': CANON,
        'source': 'HeadNeck p.77',
        'bands': {'male_adult': (92.0, 98.0), 'female_adult': (95.0, 105.0)},
        'width_deg': 6.0,  # narrowest printed band (male, 92-98)
        'note': 'the vertex is subnasale and the two rays are the COLUMELLA TANGENT and the '
        'upper lip line. The columella is the reference this cage does not carry.',
    },
    # HeadNeck p.69: the ear's long axis runs parallel to the dorsum of the nose. The
    # printed tolerance is about 8 degrees and it IS the width.
    'ear_nose_parallelism': {
        'quantity': 'absolute difference between the ear long axis and the nose dorsum, sagittal',
        'provenance': CANON,
        'source': 'HeadNeck p.69',
        'bands': {'both': (0.0, 8.0)},
        'width_deg': 8.0,
        'note': 'a parallelism tolerance, so the measured quantity is a DIFFERENCE and the band is one-sided at zero.',
    },
}


def _strict():
    """ZYG_FORM_ANGLES_STRICT — default 1 (on). At 1 an angle whose operationalisations
    disagree by more than its own printed band width reports resolved=False and
    value_deg=None. At 0 the primary operationalisation is reported as the value regardless.
    The per-operationalisation evidence is written into the record either way; only the
    refusal changes."""
    return os.environ.get('ZYG_FORM_ANGLES_STRICT', '1').strip().lower() not in ('0', 'false', 'no', 'off', '')


# ---------------------------------------------------------------------------------
# HOUSE constants, each with the measurement that fixes it
# ---------------------------------------------------------------------------------
# Same midline column and the same justification as relational.MIDLINE_TOL_M: the cage's
# midsagittal vertex column sits at |x| = 0.0000 and 0.0300 mm and the next column out is at
# 0.7307 mm, so 0.1 mm isolates the midline with a 7x margin.
MIDLINE_TOL_M = 1e-4

# The occlusion filter that keeps the ORAL CAVITY out of the facial profile. The midline
# column runs through the inside of the mouth as well as the outside of the face, and those
# interior vertices carry ANTERIOR-facing normals (measured n_y = -0.995, -0.964, -0.546),
# so no normal test separates them. What does separate them is that each one has a facial
# vertex at practically the same height with a large gap in front of it.
#
# THE HEIGHT WINDOW IS NOT FREE: it has to be at least +/-0.002 of stature (3.4 mm) or the
# interlopers escape. MEASURED on the anny neutral, the oral vertex whose nearest facial
# neighbour is furthest away is v693 at z = 597.78 mm, with facial vertices at 595.94 and
# 600.52 mm, i.e. 1.84 mm away; a window narrower than that leaves it in the profile.
#
# THE DEPTH CUT IS NOT A CONSTANT, and a fixed one does not survive contact with the issued
# bodies. The occlusion depths are BIMODAL and the two modes are far apart but they MOVE:
# MEASURED, the oral interlopers sit at 0.053-0.068 of stature on both the neutral and the
# issued female, while the deepest LEGITIMATE self-occlusion of the facial profile is 0.0099
# on the neutral (the underside of the chin, where two vertices 3.1 mm apart in height
# differ by 16.6 mm in depth) and 0.0153 on the female. A cut placed at the neutral's
# midpoint (0.025) leaves the female only a factor of 1.6 of headroom, which is not a
# separation, it is a coincidence waiting to end.
#
# So the cut is DERIVED PER BODY as the geometric midpoint of the LARGEST MULTIPLICATIVE GAP
# in that body's own sorted occlusion depths. That is parameter-free where it matters, and
# it comes with its own falsifier: the gap factor is reported, and a body whose two
# populations are not separated by at least OCCLUSION_MIN_GAP_FACTOR is REFUSED rather than
# split at a boundary that does not exist. Measured gap factors: 5.4 (neutral), 3.5
# (female).
#
# OCCLUSION_SPLIT_FLOOR exists for one job only: to stop the gap-finder splitting INSIDE the
# legitimate population on a body that has no oral interlopers at all, where the largest
# multiplicative gap would be some accident among small numbers. It sits between the two
# measured populations (deepest legitimate 0.0153, shallowest interloper 0.0533) and it
# never decides which side a vertex falls on — the gap does.
OCCLUSION_HEIGHT_FRAC = 0.002
OCCLUSION_SPLIT_FLOOR = 0.020
OCCLUSION_MIN_GAP_FACTOR = 2.0

# Jaw skinning-weight cuts swept by gonial_angle(). Not a tuning grid: it is the
# operationalisation set whose disagreement is the evidence, and it spans the whole usable
# range of the weight (below 0.05 the support is mostly neck, above 0.5 it is 45 vertices of
# chin).
JAW_WEIGHT_CUTS = (0.05, 0.10, 0.20, 0.30, 0.50)

# The relief cuts a bony feature must clear before this module will say it exists — the p99
# of the cage's OWN relief null, imported from curvature.py rather than restated, exactly as
# regions.py does. Not a number picked so something resolves.
FEATURE_MIN_FRAC = CV.RELIEF_NULL_P99['min_frac_stature']
FEATURE_MIN_CONTRAST = CV.RELIEF_NULL_P99['min_contrast']
FEATURE_PROBE_RADIUS = 0.012  # of stature; the radius the null was measured at

_CACHE = {}


# ---------------------------------------------------------------------------------
# frame, context, small helpers
# ---------------------------------------------------------------------------------
def _frame(v, faces):
    """Assert the measured frame is the one every sign in this file is written against."""
    if 'frame' not in _CACHE:
        _CACHE['frame'] = LMK.frame_report(v, faces)
    fr = _CACHE['frame']
    for k, want in FRAME.items():
        if fr[k] != want:
            raise RuntimeError(
                'frame_report measures %s = %r on this cage, but every sign in '
                'geom.form.angles is written against %r. Signs would be inverted silently, '
                'so this refuses. Measured convention: %s' % (k, fr[k], want, fr['convention'])
            )
    return fr


def _context(v, faces, landmarks=None, phenotype=None, local_changes=None):
    v = np.asarray(v, np.float64)
    if len(v) != LMK.CAGE_VERTS:
        raise ValueError(
            'geom.form.angles is indexed against the %d-vertex anny cage; got %d' % (LMK.CAGE_VERTS, len(v))
        )
    faces = np.asarray(faces)
    _frame(v, faces)
    zmin = float(v[:, 2].min())
    S = float(v[:, 2].max()) - zmin
    if S <= 0:
        raise ValueError('degenerate mesh: zero stature')
    return {
        'v': v,
        'faces': faces,
        'zmin': zmin,
        'S': S,
        'fz': (v[:, 2] - zmin) / S,
        'n': CV.vertex_normals(v, faces),
        'lm': landmarks if landmarks is not None else LMK.resolve_landmarks(v, faces, phenotype, local_changes),
        'phenotype': phenotype,
        'local_changes': local_changes,
    }


def _skin_mask(v, faces):
    """The main connected component. The cage ships four: the body shell, a 226-vertex oral
    component (teeth and tongue) and the two 72-vertex eyeball shells. Any profile taken
    without this mask reads the teeth."""
    key = ('skin', len(v), int(np.asarray(faces).shape[0]))
    if key in _CACHE:
        return _CACHE[key]
    ncomp, lab = IG._components(v, IG.triangulate_quads(faces))
    sizes = np.bincount(lab, minlength=ncomp)
    _CACHE[key] = lab == int(np.argmax(sizes))
    return _CACHE[key]


def _unresolved(reason, **evidence):
    rec = {'resolved': False, 'value_deg': None, 'reason': reason, 'claim': None}
    rec.update(evidence)
    return rec


def _bone_weight(name):
    """Total skinning weight of one rig bone, per vertex. Topology-fixed, so cached.

    This is MakeHuman's own statement about which skin a bone drives. It is used here for
    the jaw and it is used to PROVE A NEGATIVE, not to make a claim: see gonial_angle().
    """
    if ('bw', name) in _CACHE:
        return _CACHE[('bw', name)]
    m = MS._model()
    labels = [str(x) for x in MS._bone_names(m)]
    if name not in labels:
        raise KeyError(
            'this rig has no bone named %r; the %d it does have include %s' % (name, len(labels), ', '.join(labels[:8]))
        )
    b = labels.index(name)
    vbi = np.asarray(m.vertex_bone_indices)
    vbw = np.asarray(m.vertex_bone_weights, np.float64)
    w = np.zeros(vbi.shape[0])
    for k in range(vbi.shape[1]):
        w += np.where(vbi[:, k] == b, vbw[:, k], 0.0)
    _CACHE[('bw', name)] = w
    return w


def _bone_head(name, phenotype=None, local_changes=None):
    """The rest position of one bone's HEAD, in mesh coordinates, for one recipe.

    A bone's head is its joint with its parent. The 'jaw' bone's parent is 'head'
    (MEASURED), so the jaw head IS the temporomandibular pivot the rig turns the mandible
    about. It is a MIDLINE point — the rig carries one jaw bone, not a pair of condyles — so
    it is usable in the SAGITTAL PROJECTION, which is where a gonial angle is read anyway,
    and nowhere else.
    """
    import torch

    m = MS._model()
    labels = [str(x) for x in MS._bone_names(m)]
    kw = {'phenotype_kwargs': dict(phenotype or LMK.REF_MALE)}
    if local_changes:
        kw['local_changes_kwargs'] = dict(local_changes)
    with torch.no_grad():
        out = m(**kw)
    return np.asarray(out['rest_bone_heads'][0], np.float64)[labels.index(name)]


def _target_displacement(label, phenotype=None):
    """Per-vertex displacement of one MakeHuman target at unit strength, at one recipe.

    A morph target is a fixed displacement table, so this is topology-fixed at a fixed
    phenotype. Used for POINT anchors: on a target named for a corner, the vertex the target
    moves FURTHEST is the corner, which is a stronger anchor than the support centroid
    because a centroid smears a corner across the patch that surrounds it.
    """
    phen = dict(phenotype or LMK.REF_MALE)
    key = ('disp', label, tuple(sorted(phen.items())))
    if key in _CACHE:
        return _CACHE[key]
    v0, _, _ = MS._build_mesh(phen, None)
    v1, _, _ = MS._build_mesh(phen, {label: 1.0})
    d = np.asarray(v1, np.float64) - np.asarray(v0, np.float64)
    if not np.isfinite(d).all() or np.linalg.norm(d, axis=1).max() <= 0:
        raise RuntimeError(
            'morph target %r has EMPTY displacement at %r — the local-changes vocabulary is not loaded' % (label, phen)
        )
    _CACHE[key] = d
    return d


def _spread(values):
    vals = [x for x in values if x is not None and np.isfinite(x)]
    return (max(vals) - min(vals)) if len(vals) > 1 else 0.0


def _verdict(value, lo, hi):
    if value is None:
        return 'unresolved'
    if lo is not None and value < lo:
        return 'below_band'
    if hi is not None and value > hi:
        return 'above_band'
    return 'in_band'


def _band_for(key, sex, age_years):
    """The printed band that applies to one subject, or None with the reason.

    A CHILD is never scored against an adult band. gates.py rule 3 refuses to score a child
    against ANSUR for the same reason, and the gonial row is the one place the books DO
    publish an age curve, so a child gets the interpolated child expectation reported as a
    separate field rather than being silently handed the adult numbers.
    """
    spec = BANDS[key]
    bands = spec['bands']
    if 'both' in bands:
        return bands['both'], 'both'
    if age_years is not None and age_years < 17.0:
        return None, (
            'no printed band for age %.1f: %s publishes adult bands (and, for the '
            'gonial angle, a newborn band); interpolating between them would be '
            "our arithmetic, not the source's" % (age_years, spec['source'])
        )
    name = 'female_adult' if sex == 'female' else 'male_adult'
    if name not in bands:
        return None, 'no printed band for sex=%r' % sex
    return bands[name], name
