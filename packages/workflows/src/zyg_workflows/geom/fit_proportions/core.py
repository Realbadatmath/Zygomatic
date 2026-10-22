# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""fit_proportions.py — the imports, the in-graph constraint, the constants, the crotch spec and the steering decision (lines 190-199, 200-595 of the pre-split file, verbatim)."""

import argparse
import ast
import json
import math
import os
import subprocess
import sys
import tempfile

import numpy as np

from zyg_workflows.geom import fit_reference as FR
from zyg_workflows.geom import mesh_skeletons as MS
from zyg_workflows.geom.anthro.reference import reference
import logging as _zyg_logging

# channel kept from the pre-split module
_zyg_log = _zyg_logging.getLogger('zyg_workflows.geom.fit_proportions')

# The original top import block: these names are re-imported through this module by the
# siblings that use them — baking.py takes argparse/ast/json/os/subprocess/sys/tempfile,
# fit_sex_stages.py takes FR. Nothing in this file reads them.
__all__ = [
    'argparse',
    'ast',
    'json',
    'os',
    'subprocess',
    'sys',
    'tempfile',
    'FR',
]


SCHEMA = 'geom.fit_proportions/2'

# ---------------------------------------------------------------------------
# THE IN-GRAPH CONSTRAINT. MEASURED provenance (ANSUR II 2012 public working database).
INNER_TARGET = 'crotch_height_over_stature'
TARGET_Z = 0.0
# The constraint is only honoured if the residual clears this. 0.05 sd is 0.7 mm of
# stature on a 1.85 m body — two orders below the 0.5 mm build tolerance matters at.
RATIO_Z_TOL = 0.05

# ---------------------------------------------------------------------------
# THE OUTER TOLERANCE IS DERIVED, NOT CHOSEN. A constraint solved tighter than the body's
# own stature is solved is being solved to noise, so the outer targets are held to the
# same millimetre budget the build holds stature to: gates.BUILD_TARGET_STATURE_TOL_MM.
# Converted per ratio, tol_z = mm / (sd * stature_mm), which is why it is not a knob.
OUTER_TOL_MM = 2.0
_OUTER_TOL_SOURCE = (
    'geom.anthro.gates.BUILD_TARGET_STATURE_TOL_MM — the tolerance the build itself holds delivered stature to'
)

PRIMARY = 'PRIMARY'  # a candidate for steering: released only by steer_decision()
HOLD = 'HOLD'  # currently good: carried in the least squares, must stay in band

OUTER = {
    'male': {
        'candidates': (
            {
                'ratio': 'suprasternale_height_over_stature',
                'levers': ('head-scale-vert-incr',),
                'why': (
                    'At pinned stature with the legs held at the survey median, the only '
                    'place the torso can get height back from is the head, and '
                    'head-scale-vert-incr is the only whole-head vertical lever that is '
                    'not itself an eye-approved silhouette parameter. MEASURED, '
                    'survey_comparable, landmark_confidence "high", no window caveat, no '
                    'A-pose bias — so if this one is outside its band it is allowed to '
                    'drive. Dropping bony_relief is expected to put it back inside.'
                ),
            },
            {
                'ratio': 'chest_circumference_over_stature',
                'levers': (),
                'why': (
                    'Outside the band by 7.8 mm while carrying a -55.5 mm A-pose bias '
                    '(arms-down estimate z +1.12, inside the band). Test 4 refuses it: '
                    'the pose convention, not the chest, is what is out of band. No '
                    'lever is declared because the only levers are eye-approved girth '
                    'morphs and this pass will not re-open them for a pose artefact.'
                ),
            },
        ),
        'hold': (),
    },
    'female': {
        'candidates': (
            {
                'ratio': 'chest_breadth_over_stature',
                'levers': ('torso-vshape-incr', 'torso-scale-depth-incr'),
                'why': (
                    'p99.2, 17.8 mm past the band edge against a -7.8 mm A-pose bias '
                    '(arms-down still z +2.27), so the excess is real geometry. Her '
                    'chest is broad AND shallow (depth p29), so the correction is a '
                    'breadth->depth rotation at constant girth — which is why '
                    'chest_circumference (already z -0.026) and chest_depth ride in the '
                    'same least squares as HOLD targets instead of being left to drift.'
                ),
            },
            {
                'ratio': 'suprasternale_height_over_stature',
                'levers': (),
                'why': (
                    'p95.4, but only 0.7 mm past the band edge — smaller than '
                    'OUTER_TOL_MM, i.e. inside the resolution the build holds stature '
                    'to. Test 3 refuses it. Note the SIGN: hers is HIGH where the '
                    "male's was low, so the male's head fix must never be applied to "
                    'her.'
                ),
            },
        ),
        'hold': ('chest_circumference_over_stature', 'chest_depth_over_stature'),
    },
}

# ---------------------------------------------------------------------------
# NEVER a free parameter, in either loop, for any constraint, on either body. Hands and
# feet grew as free-riders on the fourth issue's `proportions` move (no objective
# constrains them: fit_reference masks arms/hands/feet out of the chamfer by skinning
# weight, and no ratio was steering them), and hand_length_over_stature is now p98.6.
# It is ALSO survey_comparable=False, so it could not be a target even if it were wanted.
# Asserted against every free set by _assert_locked() rather than left as a comment.
LOCKED_SUBSTRINGS = ('hand', 'finger', 'foot', 'toe')

# free set — see the module docstring
FREE_PHEN = ('proportions',)
FREE_LOCALS = (
    'measure-upperleg-height-incr',
    'measure-lowerleg-height-incr',
    'measure-napetowaist-dist-incr',
    'measure-waisttohip-dist-incr',
    'torso-scale-vert-incr',
    'measure-neck-height-incr',
)
# head morphs held out of BOTH loops, and why each one is held
HELD_HEAD = {
    'head-scale-depth-incr': (
        'head_length_over_stature is survey_comparable=False AND at_window_endpoint=True — a search-window artefact'
    ),
    'head-scale-horiz-incr': (
        'head_breadth_over_stature is p63.9 (fine) and is also '
        'survey_comparable=False — measured over hair, cage is bald'
    ),
}

# The anatomy layer this issue ships. bony_relief is REMOVED from both bodies.
#
# EVIDENCE, all of it measured, none of it inferred:
#   * isolating the layer on the FOURTH-issue male gave 4/20 landmarks resolving WITHOUT
#     it and 2/20 WITH it. It destroyed epicondyle_med, turning a +8.04 mm prominence
#     (ridge, contrast 4.3) into a -12.85 mm hollow (point_only, contrast -5.0), and did
#     the same to deltopectoral_triangle (-9.76 furrow -> -21.75 point_only);
#   * on the female it gained nothing and lost nothing: 3/20 either way;
#   * an independent re-measurement of the relief null across 7 RNG seeds found the
#     shipped seed to be the unique minimum on both axes — 1 draw in 7 — and at the modal
#     threshold the entire gain is zero on both bodies.
# geom/relief.py IS NOT DELETED and is not disabled: the module stays on disk, imported
# and working, _apply_bony_relief() still honours the key, and ZYG_BONY_RELIEF still
# works. These two bodies simply stop asking for it, which is exactly the per-character
# contract ORIGINAL_ANATOMY was built for — derived/abel and derived/cornelis carry their
# own keys and are untouched.
ISSUE_ANATOMY = {
    'male': {'abs_definition': 1.7, 'abs_pattern': 'ABS_PATTERN_V2'},
    'female': {'toe_declash': 0.0454},
}
ANATOMY_SYMBOLIC = {'abs_pattern': {'ABS_PATTERN_V2': MS.ABS_PATTERN_V2}}
ANATOMY_DROPPED = ('bony_relief',)

REF_GLB = {
    'male': 'data/assets/mesh_packs/blender_human_base/glb/coll_body_male_realistic.glb',
    'female': ('data/assets/mesh_packs/blender_human_base/glb/coll_body_female_realistic.glb'),
}

OUTER_ROUNDS = 4
INNER_ITERS = 220
LR = 0.05
FD_STEP = 0.12  # finite-difference step for the outer jacobian, in morph units


# ===========================================================================
# landmark / measurement plumbing
# ===========================================================================

_CROTCH_SPEC = None


def crotch_spec():
    """The crotch landmark's own region + axis, taken from the landmark table."""
    global _CROTCH_SPEC
    if _CROTCH_SPEC is None:
        from zyg_workflows.geom.anthro import landmarks as LM

        for d in LM.LANDMARK_SPEC:
            if d.get('name') == 'crotch':
                _CROTCH_SPEC = d['args']
                break
        if _CROTCH_SPEC is None:
            raise RuntimeError('no crotch entry in the landmark table')
    return _CROTCH_SPEC


def crotch_index(v):
    """The vertex the gate resolves as `crotch`, by the landmark table's own rule:
    minimum z of the midsagittal strip between two fractions of stature."""
    a = crotch_spec()
    reg = a['region']
    v = np.asarray(v, np.float64)
    zmin = float(v[:, 2].min())
    H = float(v[:, 2].max()) - zmin
    fz = (v[:, 2] - zmin) / H
    lo, hi = reg['fz']
    xlo, xhi = reg['xabs']
    ax = np.abs(v[:, 0]) / H
    m = (fz >= lo) & (fz <= hi) & (ax >= xlo) & (ax <= xhi)
    idx = np.nonzero(m)[0]
    if not len(idx):
        raise RuntimeError('crotch region empty')
    # _r_extreme's own rule: maximise (coordinate * sign), so sign=-1 is a minimum
    return int(idx[int(np.argmax(v[idx, 2] * float(a['sign'])))])


def crotch_frac(v):
    i = crotch_index(v)
    v = np.asarray(v, np.float64)
    zmin = float(v[:, 2].min())
    return float((v[i, 2] - zmin) / (float(v[:, 2].max()) - zmin))


def cloud_crotch_frac(pts):
    """The same rule applied to a sampled point cloud, so the reference body's own leg
    proportion is MEASURED with the construction the gate uses rather than assumed."""
    a = crotch_spec()
    reg = a['region']
    p = np.asarray(pts, np.float64)
    zmin = float(p[:, 2].min())
    H = float(p[:, 2].max()) - zmin
    fz = (p[:, 2] - zmin) / H
    lo, hi = reg['fz']
    xlo, xhi = reg['xabs']
    ax = np.abs(p[:, 0]) / H
    m = (fz >= lo) & (fz <= hi) & (ax >= xlo) & (ax <= xhi)
    idx = np.nonzero(m)[0]
    if not len(idx):
        raise RuntimeError('reference crotch region empty')
    j = int(idx[int(np.argmax(p[idx, 2] * float(a['sign'])))])
    return float((p[j, 2] - zmin) / H)


def _atanh_of(value, lo, hi):
    """Inverse of fit_reference's bounded() so the optimiser STARTS on the approved
    recipe instead of at the centre of the box."""
    t = 2.0 * (float(value) - lo) / (hi - lo) - 1.0
    t = min(max(t, -0.999999), 0.999999)
    return math.atanh(t)


def delivered_mesh(sex, phen, locs, anat):
    """The cage that SHIPS: morph solve, then the anatomy layer, then the height axis
    re-solved against TARGET_HEIGHT_M exactly the way build_originals() does it.

    The outer loop measures THIS, not the pre-anatomy cage, because this is what the gate
    measures. The inner torch loop necessarily works on the pre-anatomy cage (the layers
    are not differentiable); the crotch residual is therefore re-checked here, on the
    delivered mesh, before the recipe is allowed out.
    """
    target_h = float(MS.TARGET_HEIGHT_M[sex])
    hv, achieved = MS._calibrate_height({**phen, 'height': phen.get('height', 0.5)}, target_h, locals_=locs)
    p = {**phen, 'height': round(float(hv), 6)}
    v, faces, _ = MS._build_mesh(p, locs)
    v = MS._apply_anatomy(v, faces, dict(anat), phenotype=p, local_changes=locs)
    return p, v, faces, float(achieved)


def measure_ratios(sex, v, faces, phen, locs):
    from zyg_workflows.geom.anthro import measure as ME

    M = ME.measure_mesh(v, faces, sex=sex, phenotype=phen, local_changes=locs)
    return M


def ratio_z(M, sex, name, ref=None):
    ref = ref or reference()
    rec = (M.get('ratios') or {}).get(name) or {}
    x = rec.get('value')
    if x is None:
        raise RuntimeError('ratio %s did not resolve on this mesh' % name)
    b = ref.band(name, sex)
    mu, sd = float(b['mean']), float(b['sd'])
    return float((float(x) - mu) / sd), float(x), mu, sd, b


# ===========================================================================
# provenance gate on the targets — enforced in code, on the delivered mesh
# ===========================================================================


def steer_decision(sex, M, stature_mm, ref_obj=None):
    """Decide, from the delivered mesh alone, which levers this pass is allowed to move.

    Returns (receipt, steered_ratios, active_levers). See the module docstring for the
    four tests; every one of them is computed off the measurement record or the reference
    pack, so the decision is data, not judgement. A candidate that passes every test but
    declares no lever RAISES — a failing MEASURED ratio is never silently dropped.
    """
    ref_obj = ref_obj or reference()
    receipt, steered, levers = [], [], []
    for cand in OUTER[sex]['candidates']:
        name = cand['ratio']
        rat = (M.get('ratios') or {}).get(name) or {}
        src = rat.get('from')
        meas = (M.get('measurements') or {}).get(src) or {}
        b = ref_obj.band(name, sex)
        x = rat.get('value')
        rec = {
            'ratio': name,
            'from': src,
            'levers': list(cand['levers']),
            'why': cand['why'],
            'value': x,
            'band': [float(b['lo']), float(b['hi'])],
            'z': None if x is None else (float(x) - float(b['mean'])) / float(b['sd']),
            'percentile': None if x is None else float(ref_obj.percentile(name, float(x), sex)),
            'survey_comparable': rat.get('survey_comparable'),
            'numerator_provenance': meas.get('provenance'),
            'at_window_endpoint': rat.get('at_window_endpoint'),
            'landmark_confidence': meas.get('landmark_confidence'),
            'a_pose_bias_mm': meas.get('a_pose_bias_mm'),
        }
        refuse = []
        if x is None:
            refuse.append('test 1: the ratio did not resolve on this mesh')
        else:
            if rat.get('survey_comparable') is not True:
                refuse.append(
                    'test 1: survey_comparable=%r (%s)'
                    % (rat.get('survey_comparable'), rat.get('survey_not_comparable_because'))
                )
            if meas.get('provenance') != 'MEASURED':
                refuse.append('test 1: numerator provenance=%r, not MEASURED' % meas.get('provenance'))
            if rat.get('at_window_endpoint'):
                refuse.append(
                    'test 1: at_window_endpoint — the number is a property of the search window, not of the body'
                )
            lo, hi = float(b['lo']), float(b['hi'])
            excess = max(lo - float(x), float(x) - hi)
            rec['band_excess_frac'] = excess
            if excess <= 0:
                refuse.append('test 2: inside the p5-p95 band (%.4f..%.4f)' % (lo, hi))
            elif not name.endswith('_over_stature'):
                refuse.append(
                    'test 3/4: %s is not a stature-relative ratio, so its band '
                    'excess has no millimetre form and tests 3 and 4 cannot be '
                    'evaluated; it is reported, not steered' % name
                )
            else:
                mm = excess * stature_mm
                rec['band_excess_mm'] = mm
                if mm <= OUTER_TOL_MM:
                    refuse.append(
                        'test 3: %.1f mm past the band edge is inside the '
                        "build's own stature resolution (%.1f mm, %s)" % (mm, OUTER_TOL_MM, _OUTER_TOL_SOURCE)
                    )
                bias = meas.get('a_pose_bias_mm')
                if bias is not None and abs(float(bias)) >= mm:
                    refuse.append(
                        'test 4: the A-pose bias on this measurement is '
                        '%.1f mm and the band excess is only %.1f mm, so the '
                        'POSE convention and not the geometry is what is out '
                        'of band' % (abs(float(bias)), mm)
                    )
        rec['steered'] = not refuse
        rec['refused_because'] = refuse
        if rec['steered']:
            if not cand['levers']:
                raise RuntimeError(
                    '%s: %s passes every steering test (%.1f mm past the band edge) but '
                    'declares NO lever. A failing MEASURED ratio may not be silently '
                    'dropped — declare a lever or record why one cannot exist.'
                    % (sex, name, rec.get('band_excess_mm', float('nan')))
                )
            steered.append(name)
            for k in cand['levers']:
                if k not in levers:
                    levers.append(k)
        receipt.append(rec)
    return receipt, steered, levers


def _assert_locked(*param_groups):
    """Hands and feet are never free parameters. Checked, not commented."""
    for group in param_groups:
        for k in group:
            kl = str(k).lower()
            for sub in LOCKED_SUBSTRINGS:
                if sub in kl:
                    raise RuntimeError(
                        'LOCKED parameter %r appeared in a free set. Hands and feet may '
                        'never be free parameters for a proportion constraint (see '
                        'LOCKED_SUBSTRINGS).' % k
                    )


def declared_levers(sex):
    out = []
    for cand in OUTER[sex]['candidates']:
        for k in cand['levers']:
            if k not in out:
                out.append(k)
    return tuple(out)


def _assert_held(sex):
    for k in HELD_HEAD:
        if k in FREE_LOCALS or k in declared_levers(sex):
            raise RuntimeError('%s is HELD (%s) but appears in a free set' % (k, HELD_HEAD[k]))
