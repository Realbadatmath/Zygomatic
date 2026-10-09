# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Monte-Carlo calibration over the anny morph space, the band fit, and the
synthetic mesh lesions.

Moved verbatim out of the old single-file hands.py (lines 1632-2069).
"""

import json
import math
import os
import time
import numpy as np

from zyg_workflows.geom.form.hands.rig import (
    SCHEMA,
    PREDICATES,
    FAIL,
    HOUSE,
    FINGERS,
    WEBS,
    SAMPLE_FILE,
    CAGE_VERTS,
    DIGIT_BONES,
    RING_W_MIN,
    _side,
    rig,
    _segment_idx,
    _triangulate,
    resolve_hand,
)
from zyg_workflows.geom.form.hands.mesh import (
    _web_axes,
    _mesh_webbing,
    _dp_axis,
    measure_hand_mesh,
    FLOOR_MARGIN,
    _CAL,
)

import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)


# ---------------------------------------------------------------------------------
# Monte-Carlo calibration over the anny morph space
# ---------------------------------------------------------------------------------
# The four hand local morphs. Sampled because a calibration that only moves the six macros
# would measure a hand that barely changes and would produce a threshold with no headroom.
HAND_MORPHS = (
    'hand-fingers-length-incr',
    'hand-fingers-diameter-incr',
    'hand-fingers-distance-incr',
    'hand-scale-incr',
)
# HOUSE, taken from geom.anthro.gates.MORPH_COEFF_ABS_MAX so the sample cannot contain a
# body the metric layer would reject on its morph coefficients alone.
MORPH_ABS_MAX = 0.8
# ANSUR's age coverage, in anny macro units via measure._age_years (0.5 -> 25 y):
# 17 y -> 0.3333, 58 y -> 0.7538. Drawing outside it would fill the sample with bodies
# tier 2 declines to judge, and an acceptance filter that never fires is not a filter.
AGE_MACRO_RANGE = (1.0 / 3.0, 0.753846)


def _draw(rng):
    phen = {
        'gender': float(rng.uniform(0.0, 1.0)),
        'age': float(rng.uniform(*AGE_MACRO_RANGE)),
        'muscle': float(rng.uniform(0.0, 1.0)),
        'weight': float(rng.uniform(0.0, 1.0)),
        'height': float(rng.uniform(0.0, 1.0)),
        'proportions': float(rng.uniform(0.0, 1.0)),
    }
    loc = {}
    for lab in HAND_MORPHS:
        # MIRRORED. measure.py refuses any mesh whose bilateral residual exceeds 10 mm,
        # and drawing l- and r- independently produced 29.0 mm and a hard refusal.
        val = float(rng.uniform(-MORPH_ABS_MAX, MORPH_ABS_MAX))
        loc['l-' + lab] = val
        loc['r-' + lab] = val
    return phen, loc


def _atomic_json(path, doc):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + '.tmp.%d' % os.getpid()
    with open(tmp, 'w') as f:
        json.dump(doc, f, indent=1, sort_keys=True)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def build_sample(n_draw=700, seed=20260806, path=SAMPLE_FILE, progress=True):
    """Draw the morph sample, keep what geom.anthro tier 2 accepts, measure, calibrate.

    ACCEPTANCE. A body is kept when a tier-2 run returns no BLOCKING failure at effective
    severity — which is exactly what "a body our own pipeline would accept" means. It is
    NOT "no tier-2 gate returned fail": measured over 16 draws that criterion accepted
    0/16, for the reason gates.py documents at length (ten independent p5-p95 bands admit
    47% of real men, so a roll-up over several of them admits almost nobody). Both counts
    are recorded.
    """
    from zyg_workflows.geom import mesh_skeletons as MS
    from zyg_workflows.geom.anthro import measure as ME
    from zyg_workflows.geom.anthro.gates.engine import run_gates

    rng = np.random.default_rng(seed)
    t0 = time.time()
    rows, rejected, errors = [], [], []
    any_fail = 0
    for i in range(int(n_draw)):
        phen, loc = _draw(rng)
        try:
            v, faces, _ = MS._build_mesh(phen, loc, None)
            v = np.asarray(v, np.float64)
            spec = {
                'sex': 'female' if phen['gender'] > 0.5 else 'male',
                'sex_source': 'anny gender macro (monte-carlo draw)',
                'ancestry': None,
                'age_years': ME._age_years(phen['age']),
                'age_source': 'anny age macro via measure._age_years',
                'phenotype': phen,
                'local_changes': loc,
                'anatomy_layer': {},
                'bone_scales': {},
                'topology_scope': 'full',
            }
            rep = run_gates((v, faces, spec), tiers=[2], strict=False)
        except Exception as e:  # noqa: BLE001
            errors.append({'draw': i, 'error': '%s: %s' % (type(e).__name__, e)})
            continue
        fails = [r['id'] for r in rep['gates'] if r['status'] == FAIL]
        any_fail += bool(fails)
        if rep['verdict'] == 'FAIL':
            rejected.append({'draw': i, 'blocking': list(rep['blocking'])})
            continue
        obs = {
            'draw': i,
            'phenotype': phen,
            'local_changes': loc,
            'tier2_verdict': rep['verdict'],
            'tier2_fail_ids': fails,
            'sides': {},
        }
        for side in ('L', 'R'):
            try:
                mm = measure_hand_mesh(v, faces, side)
            except Exception as e:  # noqa: BLE001
                errors.append({'draw': i, 'side': side, 'error': '%s: %s' % (type(e).__name__, e)})
                continue
            obs['sides'][side] = {
                'knuckle_arch': mm['knuckle_arch']['value'],
                'middle_finger_ratio': mm['middle_finger_ratio']['value'],
                'webbing': mm['webbing']['value'],
                'thumb_opposition': mm['thumb_opposition']['value'],
                'dorsal_over_palmar': mm['dorsal_over_palmar']['value'],
                'finger_agreement_deg': mm['thumb_opposition']['finger_agreement_deg'],
                'min_anisotropy': min(mm['thumb_opposition']['anisotropy'].values()),
                'hand_length_m': mm['frame']['hand_length_m'],
                'palmar_sign_ratio': mm['frame']['palmar_sign_margin']['ratio'],
            }
        if obs['sides']:
            rows.append(obs)
        if progress and (i + 1) % 25 == 0:
            _zyg_log.info('  %4d/%d drawn, %d accepted, %.0fs' % (i + 1, n_draw, len(rows), time.time() - t0))

    doc = {
        'schema': SCHEMA,
        'built': time.strftime('%Y-%m-%dT%H:%M:%S'),
        'provenance': {
            'seed': int(seed),
            'n_draw': int(n_draw),
            'n_accepted': len(rows),
            'n_rejected': len(rejected),
            'n_error': len(errors),
            'draws_with_any_tier2_fail': int(any_fail),
            'sampling': {
                'macros': {
                    'gender': [0.0, 1.0],
                    'age': list(AGE_MACRO_RANGE),
                    'muscle': [0.0, 1.0],
                    'weight': [0.0, 1.0],
                    'height': [0.0, 1.0],
                    'proportions': [0.0, 1.0],
                },
                'local_morphs': {lab: [-MORPH_ABS_MAX, MORPH_ABS_MAX] for lab in HAND_MORPHS},
                'mirrored': (
                    'l- and r- hand morphs are drawn once and applied to both '
                    'sides; drawn independently they produce a 29.0 mm bilateral '
                    'residual and measure.py refuses the mesh outright'
                ),
                'age_window': (
                    'anny macro %.4f..%.4f = 17..58 y, ANSUR II coverage, so '
                    'the tier-2 acceptance filter actually fires' % AGE_MACRO_RANGE
                ),
            },
            'acceptance': (
                'geom.anthro.gates.run_gates(tiers=[2]) verdict != FAIL, i.e. no BLOCKING failure at effective severity'
            ),
            'elapsed_s': round(time.time() - t0, 1),
            'cage_verts': CAGE_VERTS,
            'ring_weight_min': RING_W_MIN,
        },
        'rejected': rejected[:200],
        'errors': errors[:200],
        'observations': rows,
    }
    doc['predicates'] = _fit_bands(rows)
    _atomic_json(path, doc)
    _CAL.pop(path, None)
    return doc


# Which side of each predicate a violation lies on. Every one of these is a FLOOR
# (a hand fails by having too little arch / too little web / too little opposition), except
# middle_finger_ratio which is a two-sided band because a finger can be too long as well as
# too short.
_PRED_SIDEDNESS = {
    'knuckle_arch': 'lower',
    'middle_finger_ratio': 'both',
    'webbing': 'lower',
    'thumb_opposition': 'lower',
    'dorsal_over_palmar': 'lower',
}

# THE ANATOMICAL SIGN FLOOR — the value at which the predicate stops being a statement
# about anatomy at all. These are not percentiles and not house taste: a knuckle line with
# zero residual IS collinear, a commissure at zero IS at the MCP line, and a finger that is
# not longer from the back than from the web has no web. They are preferred over the
# sample floor whenever the sample says they are safe to block on, because a floor placed
# outside a sample's range is only as meaningful as the sample is wide.
NATURAL_FLOOR = {
    'knuckle_arch': 0.0,
    'webbing': 0.0,
    'dorsal_over_palmar': 1.0,
    'thumb_opposition': None,  # relational, see RELATIONAL_FLOOR below
    'middle_finger_ratio': None,  # a ratio has no anatomical zero
}
NATURAL_FLOOR_WHY = {
    'knuckle_arch': 'a zero residual means the four metacarpal heads ARE collinear',
    'webbing': 'a zero offset means the commissure IS on the MCP line — the V-notch hand',
    'dorsal_over_palmar': (
        'a ratio of 1 means the finger is no longer from the back than '
        'from the web, which is what a hand with no web measures'
    ),
}
# thumb_opposition has no constant floor, because the number it produces is an angle
# between axis estimates that carry their own noise. Its floor is RELATIONAL and per-hand:
# the thumb must sit further from the four fingers' consensus than the four fingers sit
# from each other. Below that the measurement cannot tell opposition from estimator noise.
RELATIONAL_FLOOR = {
    'thumb_opposition': (
        'finger_agreement_deg',
        "the thumb must differ from the fingers' consensus by more than "
        'the fingers differ from each other, or the number is estimator '
        'noise rather than opposition',
    ),
}


def _rate_record(a, lo, hi):
    n = len(a)
    rej = int(
        ((a < lo) if lo is not None else np.zeros(n, bool)).sum()
        + ((a > hi) if hi is not None else np.zeros(n, bool)).sum()
    )
    rate = rej / float(n)
    upper = rate if rej else 3.0 / n
    return {
        'band': [lo, hi],
        'rejected': rej,
        'rejection_rate': rate,
        'rejection_rate_95_upper': upper,
        'severity': ('block' if upper < 0.01 else 'warn'),
        'rate_basis': ('observed' if rej else 'rule of three, 3/n'),
    }


def _fit_bands(rows):
    out = {}
    for pred in PREDICATES:
        vals = [s[pred] for r in rows for s in r['sides'].values() if s.get(pred) is not None]
        n = len(vals)
        if n < 50:
            out[pred] = {
                'band': None,
                'n': n,
                'why': 'only %d observations; a threshold from that few would '
                'have a standard error larger than the 1%% ceiling it is '
                'being compared against' % n,
            }
            continue
        a = np.asarray(vals, np.float64)
        lo_obs, hi_obs = float(a.min()), float(a.max())
        rng_ = hi_obs - lo_obs
        margin = FLOOR_MARGIN * rng_ if rng_ > 0 else abs(lo_obs) * FLOOR_MARGIN
        sided = _PRED_SIDEDNESS[pred]
        s_lo = lo_obs - margin if sided in ('lower', 'both') else None
        s_hi = hi_obs + margin if sided == 'both' else None
        sample = _rate_record(a, s_lo, s_hi)
        sample['source'] = (
            'floor placed %g of the observed range outside the extreme of a Monte-Carlo '
            'sample of the anny morph space filtered to bodies geom.anthro tier 2 accepts '
            '(n=%d hands). A percentile threshold was rejected because it rejects its own '
            'percentile by construction and would be calibrating itself.' % (FLOOR_MARGIN, n)
        )

        nat = NATURAL_FLOOR.get(pred)
        natural = None
        if nat is not None:
            natural = _rate_record(a, nat, None)
            natural['source'] = 'anatomical sign floor: %s. Rate measured on the same sample.' % NATURAL_FLOOR_WHY[pred]

        # The SHIPPED band is the anatomical floor when the sample says it may block,
        # because it is the floor that means something; otherwise the sample floor, which
        # by construction rejects nothing the sample contains.
        if natural is not None and natural['severity'] == 'block':
            chosen, why = natural, 'anatomical sign floor, measured safe on the sample'
        else:
            chosen, why = (
                sample,
                (
                    'sample floor: no anatomical floor for this predicate'
                    if natural is None
                    else 'the anatomical floor rejects %d/%d of the sample and its 95%% upper '
                    'bound is %.2f%% (%s), over the 1%% ceiling, so it may not block'
                    % (natural['rejected'], n, 100.0 * natural['rejection_rate_95_upper'], natural['rate_basis'])
                ),
            )
        rel = RELATIONAL_FLOOR.get(pred)
        rel_rec = None
        if rel:
            key, rwhy = rel
            pairs = [
                (s[pred], s.get(key))
                for r in rows
                for s in r['sides'].values()
                if s.get(pred) is not None and s.get(key) is not None
            ]
            if pairs:
                bad = sum(1 for x, y in pairs if x <= y)
                rate = bad / float(len(pairs))
                rel_rec = {
                    'against': key,
                    'why': rwhy,
                    'n': len(pairs),
                    'rejected': bad,
                    'rejection_rate': rate,
                    'rejection_rate_95_upper': (rate if bad else 3.0 / len(pairs)),
                    'severity': ('block' if (rate if bad else 3.0 / len(pairs)) < 0.01 else 'warn'),
                }

        out[pred] = {
            'band': chosen['band'],
            'n': n,
            'band_choice': why,
            'observed': {
                'min': lo_obs,
                'max': hi_obs,
                'p1': float(np.percentile(a, 1)),
                'p50': float(np.percentile(a, 50)),
                'p99': float(np.percentile(a, 99)),
                'mean': float(a.mean()),
                'sd': float(a.std(ddof=1)),
            },
            'rejected': chosen['rejected'],
            'rejection_rate': chosen['rejection_rate'],
            'rejection_rate_95_upper': chosen['rejection_rate_95_upper'],
            'severity': chosen['severity'],
            'severity_reason': (
                'the floor rejects %d/%d of the accepted morph sample (%.3f%%); the 95%% '
                'upper bound on that rate is %.3f%% (%s), against the house ceiling of 1%%.'
                % (
                    chosen['rejected'],
                    n,
                    100.0 * chosen['rejection_rate'],
                    100.0 * chosen['rejection_rate_95_upper'],
                    chosen['rate_basis'],
                )
            ),
            'calibration_kind': 'monte_carlo_form_sample',
            'provenance': HOUSE,
            'source': chosen['source'],
            'floor_sample': sample,
            'floor_natural': natural,
            'floor_relational': rel_rec,
        }
    return out


# ---------------------------------------------------------------------------------
# Synthetic lesions — the only evidence that a gate which never fires is a gate at all
#
# Every number in the mesh path comes out inside a hair's breadth of the same value on all
# four issued characters, which is exactly what a gate on a healthy population should look
# like and exactly what an inert gate also looks like. These three lesions tell the two
# apart: each destroys one predicate's anatomy on a real character's cage and the predicate
# has to notice. They are TEST FIXTURES and are never applied to an issued body.
# ---------------------------------------------------------------------------------
def _digit_mask(S, d, w_min=0.30):
    w = rig()['weights']
    tot = np.zeros(CAGE_VERTS)
    for b in DIGIT_BONES[d]:
        if b:
            tot += w['%s.%s' % (b, S)]
    return tot > w_min


def lesion_flatten_knuckles(v, faces, side):
    """Slide each finger bodily until its MCP lands on the line through all four.

    This is the fused-knuckle hand: the arch residual goes to zero while every finger keeps
    its own length, so no metric gate anywhere in geom/anthro can see it.
    """
    S = _side(side)
    F = resolve_hand(v, faces, S)
    P = np.array([F['joints'][(d, 'mcp')] for d in FINGERS])
    c = P.mean(0)
    _, _, vt = np.linalg.svd(P - c, full_matrices=False)
    u = vt[0]
    out = v.copy()
    for i, d in enumerate(FINGERS):
        target = c + float(np.dot(P[i] - c, u)) * u
        out[_digit_mask(S, d)] += target - P[i]
    return out


def lesion_fill_web(v, faces, side):
    """Pull each interdigital web proximally to the MCP line — the V-notch hand."""
    S = _side(side)
    v = np.asarray(v, np.float64)
    F = resolve_hand(v, faces, S)
    web = _mesh_webbing(v, _triangulate(faces), F)
    out = v.copy()
    for a, b in WEBS:
        r = web['webs'].get((a, b)) or {}
        if r.get('value') is None:
            continue
        m0, ax, lat, gap, pp = _web_axes(F, a, b)
        rel = out - m0
        t, l = rel @ ax, rel @ lat
        sel = (np.abs(l) < 0.30 * gap) & (t < 0.8 * pp) & (t > -0.5 * pp)
        out[sel] -= (r['commissure_m'] + 0.08 * pp) * ax
    return out


def lesion_unoppose_thumb(v, faces, side):
    """Spin the thumb's distal block about its own long axis onto the fingers' plane."""
    S = _side(side)
    v = np.asarray(v, np.float64)
    dp_t, ax_t, _, _ = _dp_axis(v, S, 'thumb')
    dps = [_dp_axis(v, S, d)[0] for d in FINGERS]
    M = sum(np.outer(x, x) for x in dps)
    _, V = np.linalg.eigh(M)
    target = V[:, -1]

    # rotate about the thumb's long axis by the angle that brings its dorso-palmar axis
    # closest to the fingers' consensus, measured in the plane perpendicular to that axis
    def perp(x):
        y = x - float(np.dot(x, ax_t)) * ax_t
        n = np.linalg.norm(y)
        return y / n if n > 1e-12 else y

    a1, a2 = perp(dp_t), perp(target)
    ang = math.atan2(float(np.dot(np.cross(a1, a2), ax_t)), float(np.dot(a1, a2)))
    K = np.array([[0, -ax_t[2], ax_t[1]], [ax_t[2], 0, -ax_t[0]], [-ax_t[1], ax_t[0], 0]])
    R = np.eye(3) + math.sin(ang) * K + (1 - math.cos(ang)) * (K @ K)
    sel = _segment_idx(S, [x for x in DIGIT_BONES['thumb'][2:] if x])
    c = v[sel].mean(0)
    out = v.copy()
    out[sel] = (out[sel] - c) @ R.T + c
    return out


LESIONS = (
    ('flatten_knuckles', lesion_flatten_knuckles, 'knuckle_arch'),
    ('fill_web', lesion_fill_web, 'webbing'),
    ('unoppose_thumb', lesion_unoppose_thumb, 'thumb_opposition'),
)
