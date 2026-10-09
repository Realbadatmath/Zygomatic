# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""fit_proportions.py — the band regressions, fit_sex, snapshot_at and the ratio report.

Lines 596-1145 of the pre-split file; everything except `fit_sex()` is still
verbatim. `fit_sex()`'s six closures were lifted into fit_sex_stages.py, which
shares them one `FitSexRun`, and what is left here is their call order.
"""

import logging as _zyg_logging
from .core import (
    reference,
    OUTER_ROUNDS,
    INNER_ITERS,
    LR,
    delivered_mesh,
    measure_ratios,
    steer_decision,
)

# channel kept from the pre-split module
_zyg_log = _zyg_logging.getLogger('zyg_workflows.geom.fit_proportions')


# ===========================================================================
# the fit
# ===========================================================================


def band_regressions(before_rows, after_rows):
    """THE DO-NO-HARM GUARD, and the whole contract of a repair pass in one function.

    No survey-comparable MEASURED ratio that was INSIDE its p5-p95 band before the fit may
    be outside it afterwards. Nothing else is asserted — a re-fit necessarily moves every
    ratio a little, and demanding that none of them move away from the mean would forbid
    any fit at all. Crossing a band edge is the one thing a repair may not do.

    Note what the baseline is: `before` is measured with the anatomy layer THIS ISSUE
    ships, i.e. with bony_relief already dropped. The layer removal is separately
    justified and is not the fit's to defend; what the fit must not do is add harm on top
    of it.
    """
    out = []
    for name, a in after_rows.items():
        b = before_rows.get(name)
        if not b or a.get('survey_comparable') is not True:
            continue
        if a['outside_band'] and not b['outside_band']:
            out.append(
                {
                    'ratio': name,
                    'before': b['value'],
                    'after': a['value'],
                    'z_before': b['z'],
                    'z_after': a['z'],
                    'percentile_before': b['percentile'],
                    'percentile_after': a['percentile'],
                    'band': [a['p5'], a['p95']],
                }
            )
    return out


def fit_sex(
    sex, phen0, locals0, anat0, iters=INNER_ITERS, rounds=OUTER_ROUNDS, lr=LR, verbose=True, freeze_inner=False
):
    """Returns a record with the re-fitted recipe and the measured before/after for every
    quantity this fit could have moved.

    freeze_inner=True holds the whole leg/torso free set at its issued value and lets only
    the released outer levers move. It is the fallback the caller reaches for when the
    unrestricted solve trips band_regressions(): a repair pass that cannot improve the
    surface fit without pushing a MEASURED ratio out of band must decline the improvement,
    not the guard.

    The stages live in fit_sex_stages.py and share one FitSexRun; this is their call order.
    """
    from . import fit_sex_stages as ST

    run = ST.build_run(sex, phen0, locals0, anat0, iters, rounds, lr, verbose, freeze_inner)

    # ---- the outer, measured loop ----------------------------------------
    _p0, _v0, _f0, before, M0 = ST.snapshot(run, 'before')
    # THE STEERING DECISION IS TAKEN ON THE DELIVERED MESH THIS ISSUE SHIPS, i.e. with the
    # anatomy layer this issue carries. That ordering is load-bearing: bony_relief moved
    # the male's suprasternale landmark by 14.2 mm, so deciding to steer it from a
    # relief-on measurement would be steering at a defect the same run is removing.
    receipt, steered, levers = steer_decision(sex, M0, before['stature_m'] * 1000.0, run.ref_obj)
    tgts = ST.outer_targets(sex, steered, levers)
    if verbose:
        ST.print_before(run, before, receipt, levers)

    K, trail, stepped = ST.run_outer_loop(run, tgts, levers)

    # A lever step invalidates the surface fit and the leg constraint that were solved at
    # the PREVIOUS lever values, so the run may never end on one: if the round budget ran
    # out immediately after a step, the inner fit is re-solved before anything is measured
    # or written. (Without this the delivered mesh is a body nothing was solved on — it is
    # how the first draft of this loop reported crotch z +0.146 as a result.)
    if stepped:
        if verbose:
            _zyg_log.info(
                '    round budget exhausted right after a lever step — re-solving the '
                'inner fit so the delivered mesh is one the constraints were solved on'
            )
        ST.inner(run, K)
    run.phen, _v, _faces, after, M = ST.snapshot(run, 'after')
    run.n_meas += 1

    # ---- the assertions --------------------------------------------------
    r, tol = ST.check_result(run, after, M, tgts)
    regressions = band_regressions(before['ratios'], after['ratios'])
    if verbose and regressions:
        ST.print_regressions(regressions)

    return ST.build_record(run, tgts, levers, receipt, before, after, trail, tol, regressions, K)


def snapshot_at(sex, phen, locs, anat, ref_obj):
    """A delivered-mesh probe with no side effects, for the finite-difference jacobian."""
    p, v, faces, achieved = delivered_mesh(sex, phen, locs, anat)
    M = measure_ratios(sex, v, faces, p, locs)
    return p, v, faces, {'stature_m': achieved}, M


# ===========================================================================
# reporting
# ===========================================================================

REPORT_RATIOS = (
    'crotch_height_over_stature',
    'trochanterion_height_over_stature',
    'buttock_height_over_stature',
    'tibiale_height_over_stature',
    'suprasternale_height_over_stature',
    'cervicale_height_over_stature',
    'acromial_height_over_stature',
    'sitting_height_over_stature',
    'head_length_over_stature',
    'head_breadth_over_stature',
    'head_circumference_over_stature',
    'cephalic_index',
    'wrist_circumference_over_stature',
    'chest_breadth_over_stature',
    'chest_depth_over_stature',
    'chest_circumference_over_stature',
    'hand_length_over_stature',
    'foot_length_over_stature',
    'hip_breadth_over_stature',
    'waist_over_stature',
    'bmi',
    'waist_hip_circumference',
    'neck_circumference_over_stature',
    'shoulder_hip_skeletal',
    'span_over_stature',
)


def report_ratios(sex, M, ref_obj=None):
    ref_obj = ref_obj or reference()
    out = {}
    for name in REPORT_RATIOS:
        rat = (M.get('ratios') or {}).get(name)
        if not rat or rat.get('value') is None:
            continue
        try:
            b = ref_obj.band(name, sex)
        except Exception as _exc:  # noqa: BLE001
            _zyg_log.debug('no reference band for ratio %s: %s', name, _exc)
            continue
        x = float(rat['value'])
        mu, sd = float(b['mean']), float(b['sd'])
        pc = float(ref_obj.percentile(name, x, sex))
        lo, hi = float(b['lo']), float(b['hi'])
        src = rat.get('from')
        meas = (M.get('measurements') or {}).get(src) or {}
        out[name] = {
            'value': x,
            'mean': mu,
            'sd': sd,
            'z': (x - mu) / sd,
            'percentile': pc,
            'p5': lo,
            'p95': hi,
            'outside_band': bool(not (lo <= x <= hi)),
            'survey_comparable': rat.get('survey_comparable'),
            'survey_not_comparable_because': rat.get('survey_not_comparable_because'),
            'at_window_endpoint': rat.get('at_window_endpoint'),
            'numerator_provenance': meas.get('provenance'),
            'a_pose_bias_mm': meas.get('a_pose_bias_mm'),
        }
    return out
