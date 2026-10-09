# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""relational/gate_defs.py — the gates: the binomial bound, rejection_rate, calibrate, the predicates and gate_records.

Moved verbatim out of relational.py (lines 1310-1643).
"""

from zyg_workflows.geom.form.relational.constants import (
    CAL_UNDECLARED,
    CAL_VIOLATION_RATE,
    FAIL,
    Gate,
    HOUSE,
    MEASURED,
    MISSING,
    PASS,
    SEVERITY_POLICY,
    SEVERITY_REJECTION_CEILING,
    _result,
    math,
)
from zyg_workflows.geom.form.relational.body import (
    measure_relations,
    scalars,
)
from zyg_workflows.geom.form.relational.reference import (
    ACCEPTANCE_GATE,
    form_reference,
)


# ---------------------------------------------------------------------------------
# gates
# ---------------------------------------------------------------------------------
def _binom_upper95(k, n):
    """One-sided 95% upper bound on a binomial rate. Exact (Clopper-Pearson) when scipy is
    there, the rule of three when k=0, and a normal approximation as the last resort — the
    bound is what decides whether a gate may block, so which one produced it is recorded."""
    if n <= 0:
        return None, 'no sample'
    try:
        from scipy.stats import beta

        if k >= n:
            return 1.0, 'Clopper-Pearson (one-sided, 95%)'
        return float(beta.ppf(0.95, k + 1, n - k)), 'Clopper-Pearson (one-sided, 95%)'
    except Exception:  # noqa: BLE001
        if k == 0:
            return 3.0 / n, 'rule of three (k=0)'
        p = k / float(n)
        return p + 1.645 * math.sqrt(p * (1 - p) / n), 'normal approximation'


def rejection_rate(predicate, pack=None):
    """What fraction of the form reference sample this predicate rejects."""
    pack = pack or form_reference()
    rows = pack['rows']
    n = 0
    bad = 0
    unmeasurable = 0
    for r in rows:
        s = r.get('scalars') or {}
        verdict = predicate(s)
        if verdict is None:
            unmeasurable += 1
            continue
        n += 1
        bad += 0 if verdict else 1
    upper, how = _binom_upper95(bad, n)
    return {
        'kind': CAL_VIOLATION_RATE,
        'rate': (bad / float(n)) if n else None,
        'basis': 'measured' if n else 'not_measured',
        'rejected': bad,
        'evaluated': n,
        'unmeasurable': unmeasurable,
        'reference_n': n,
        'rate_upper95': upper,
        'rate_upper95_method': how,
        'reference_population': FORM_REFERENCE_POPULATION,
        'per_band_by_construction': None,
        'cells': [],
        'source': 'MEASURED on the form reference sample built by '
        'geom.form.relational.build_reference (seed %s, n=%s, drawn %s, '
        'acceptance %s)' % (pack.get('seed'), pack.get('n_accepted'), pack.get('n_drawn'), ACCEPTANCE_GATE),
    }


FORM_REFERENCE_POPULATION = (
    'a Monte-Carlo sample of the anny morph space, filtered to the draws that pass '
    "geom.anthro's primary joint-plausibility gate (%s) — NOT the ANSUR II sample" % ACCEPTANCE_GATE
)


def calibrate(gate, pack=None):
    """The measured severity record for one FORM gate, on the FORM sample.

    NOT geom.anthro.gates.calibrate_gate(). That function's CAL_VIOLATION_RATE branch
    hardcodes reference_population to the ANSUR II sample, which for every gate in this
    file would be a false provenance claim about where the rate came from. The POLICY is
    identical and is imported rather than restated: a gate may carry 'block' only if its
    measured rejection rate on its own reference sample is at or below
    SEVERITY_REJECTION_CEILING.
    """
    spec = dict(gate.calibration or {})
    pred = spec.get('predicate')
    if pred is None:
        rec = {
            'kind': CAL_UNDECLARED,
            'rate': None,
            'basis': 'not_measured',
            'reference_n': None,
            'reference_population': None,
            'source': None,
            'explain': 'this gate declares no predicate, so no rate exists',
        }
    else:
        rec = rejection_rate(pred, pack)
        rec['explain'] = (
            'MEASURED on the form reference sample: %d of %d accepted bodies rejected '
            '(%.4f%%, one-sided 95%% upper bound %.4f%% by %s). %s'
            % (
                rec['rejected'],
                rec['evaluated'],
                100.0 * (rec['rate'] or 0.0),
                100.0 * (rec['rate_upper95'] or 0.0),
                rec['rate_upper95_method'],
                spec.get('why') or '',
            )
        )
    rec['gate'] = gate.id
    rec['severity_declared'] = gate.severity
    rec['policy'] = SEVERITY_POLICY
    rec['ceiling'] = SEVERITY_REJECTION_CEILING
    rec['spec'] = {k: v for k, v in spec.items() if k != 'predicate'}
    n = rec.get('reference_n')
    rec['granularity'] = (1.0 / n) if n else 0.0
    rec['ceiling_effective'] = SEVERITY_REJECTION_CEILING + rec['granularity']
    if gate.severity != 'block':
        rec['severity_effective'] = gate.severity
        rec['governs_severity'] = False
        rec['reason'] = 'declared %r, which the ceiling never raises' % gate.severity
    elif rec['rate'] is None:
        rec['severity_effective'] = 'warn'
        rec['governs_severity'] = True
        rec['reason'] = (
            'declared block but no rejection rate could be measured on %s, so '
            'the block is not earned' % FORM_REFERENCE_POPULATION
        )
    else:
        # The BOUND decides, not the point estimate: a 0/600 gate whose true rate could be
        # 0.5% is inside the ceiling, and a gate whose bound exceeds it has not shown that
        # it is.
        ok = rec['rate_upper95'] <= rec['ceiling_effective']
        rec['severity_effective'] = 'block' if ok else 'warn'
        rec['governs_severity'] = True
        rec['reason'] = 'measured %.4f%% (95%% upper bound %.4f%%) against a ceiling of %.4f%% on %s: %s' % (
            100.0 * rec['rate'],
            100.0 * rec['rate_upper95'],
            100.0 * rec['ceiling_effective'],
            FORM_REFERENCE_POPULATION,
            'block stands' if ok else 'downgraded to warn',
        )
    return rec


def _p_lordosis(thresh):
    def f(s):
        v = s.get('lordosis_index')
        return None if v is None else bool(v <= thresh)

    return f


def _p_opposition(s):
    v = s.get('opposition_physiological')
    return None if v is None else bool(v)


def _p_gluteal(s):
    v = s.get('gluteal_margin_mm')
    return None if v is None else bool(v > 0.0)


def _p_eye_outward(s):
    v = s.get('eye_outward')
    d = s.get('eye_divergence_transverse_deg')
    return None if (v is None or d is None) else bool(v and d > 0.0)


def _p_eye_not_parallel(thresh):
    def f(s):
        d = s.get('eye_divergence_transverse_deg')
        return None if d is None else bool(d >= thresh)

    return f


# A KNEE-SYMMETRY GATE IS DELIBERATELY ABSENT, and the reason is a limit of the reference
# sample rather than a judgement about the predicate. The sample ties every l/r morph pair
# to one draw, because drawing them apart pushes the bilateral residual past
# measure.check_pose_and_frame's 10 mm contract and the body is refused before it can be
# measured (see SAMPLED_LOCALS). So the sample is bilaterally symmetric BY CONSTRUCTION:
# knee asymmetry over it measures 0.0 to 7.8e-10 degrees, and its p99 is 7.7e-10, which is
# a floating-point residue and not a threshold. Calibrating a gate on that would be
# manufacturing a blocking claim out of rounding. Bilateral asymmetry is already gated
# structurally upstream by integrity.mirror_symmetry / t1 mirror_symmetry_morph, which is
# where it belongs. knee_alignment() still REPORTS the per-side numbers.


def gate_records(pack=None):
    """The form-relational gate registry, with every threshold taken from the sample.

    A threshold here is a PERCENTILE OF THE FORM SAMPLE, never a number someone liked, and
    the record says which percentile and on what n. Building the registry therefore
    requires the sample to exist; there is no default.
    """
    pack = pack or form_reference()
    d = pack['distribution']
    n = pack['n_accepted']
    src = 'percentile of the form reference sample (seed %s, n=%s accepted of %s drawn, acceptance gate %s)' % (
        pack.get('seed'),
        n,
        pack.get('n_drawn'),
        ACCEPTANCE_GATE,
    )
    lord99 = d['lordosis_index']['p99']
    # The BLOCKING lordosis threshold is the sample MAXIMUM, not a percentile, and that is
    # a consequence of gates.py's severity policy rather than a preference: a p99 threshold
    # rejects 1% of its own sample BY CONSTRUCTION and therefore can never clear a 1%
    # ceiling, so a percentile gate is condemned to warn however good it is. A threshold at
    # the maximum rejects 0 of n by construction, whose 95% upper bound is 3/n, and at
    # n=600 that is 0.50% — inside the ceiling with a factor of two to spare. What it costs
    # is stated rather than hidden: this gate says only "no body the plausibility filter
    # accepted got this far", so it fires on a swayback and is silent on everything short
    # of one. The p99 gate beside it is the one that flags the approach.
    lord_max = d['lordosis_index']['max']
    eye_p01 = d['eye_divergence_transverse_deg']['p01']

    def _fn(pred, key, band):
        def f(subject):
            rel = measure_relations(
                subject.v,
                subject.faces,
                phenotype=subject.spec.get('phenotype'),
                local_changes=subject.spec.get('local_changes'),
            )
            s = scalars(rel)
            verdict = pred(s)
            if verdict is None:
                return _result(MISSING, 'unresolved on this body: %s' % '; '.join(rel['unresolved']), observed=None)
            return _result(
                PASS if verdict else FAIL,
                '%s = %r' % (key, s.get(key)),
                observed=s.get(key),
                band=band,
                source=src,
            )

        return f

    return [
        Gate(
            id='form_lumbar_lordosis',
            tier=2,
            severity='warn',
            title='lumbar lordosis is not a swayback',
            threshold=round(float(lord99), 4),
            provenance=MEASURED,
            source=src,
            fn=_fn(_p_lordosis(lord99), 'lordosis_index', [None, float(lord99)]),
            calibration={
                'kind': CAL_VIOLATION_RATE,
                'predicate': _p_lordosis(lord99),
                'why': 'the p99 of the form sample, so it rejects 1% of it by '
                'construction — the ceiling is exactly met and not '
                'cleared, which is why this gate warns',
                'source': src,
            },
        ),
        Gate(
            id='form_lumbar_swayback',
            tier=2,
            severity='block',
            title='the lumbar curve is a swayback',
            threshold=round(float(lord_max), 4),
            provenance=MEASURED,
            source='the MAXIMUM lordosis index over the form reference sample; ' + src,
            fn=_fn(_p_lordosis(lord_max), 'lordosis_index', [None, float(lord_max)]),
            calibration={
                'kind': CAL_VIOLATION_RATE,
                'predicate': _p_lordosis(lord_max),
                'why': 'the sample maximum, so it rejects 0 of n by construction and its upper bound is 3/n',
                'source': src,
            },
        ),
        Gate(
            id='form_sagittal_opposition',
            tier=2,
            severity='block',
            title='the lumbar curve opposes: sacral chord rises anteriorly, thoracic chord rises posteriorly',
            threshold='lower_chord_tilt < 0 < upper_chord_tilt',
            provenance=HOUSE,
            source='the sign structure of a lordotic lumbar curve; both chords the '
            'same sign is a flat or reversed lumbar spine. ' + src,
            fn=_fn(_p_opposition, 'opposition_physiological', None),
            calibration={
                'kind': CAL_VIOLATION_RATE,
                'predicate': _p_opposition,
                'why': 'a sign predicate, calibrated by how often the form sample violates it',
                'source': src,
            },
        ),
        Gate(
            id='form_gluteal_not_wider_than_trochanteric',
            tier=2,
            severity='block',
            title='the butt is never wider than the hips',
            threshold='trochanteric max coronal width > gluteal max coronal width',
            provenance=HOUSE,
            source='anatomical claim, implemented over resolved buttock and trochanterion bands. ' + src,
            fn=_fn(_p_gluteal, 'gluteal_margin_mm', [0.0, None]),
            calibration={
                'kind': CAL_VIOLATION_RATE,
                'predicate': _p_gluteal,
                'why': 'measured on the form sample; see falsification_sweep() for what it takes to fail it',
                'source': src,
            },
        ),
        Gate(
            id='form_eye_axes_bow_outward',
            tier=2,
            severity='block',
            title='the optical axes bow outward — parallel eyes read cross-eyed',
            threshold='divergence_transverse > 0 and outward',
            provenance=HOUSE,
            source='angle kappa is positive (temporal) in the anatomical literature; '
            'the anny neutral measures 5.036 deg per eye. ' + src,
            fn=_fn(_p_eye_outward, 'eye_outward', None),
            calibration={
                'kind': CAL_VIOLATION_RATE,
                'predicate': _p_eye_outward,
                'why': 'measured on the form sample',
                'source': src,
            },
        ),
        Gate(
            id='form_eye_axes_not_parallel',
            tier=2,
            severity='warn',
            title='the optical axes are not the rig default (parallel)',
            threshold=round(float(eye_p01), 4),
            provenance=MEASURED,
            source=src,
            fn=_fn(_p_eye_not_parallel(eye_p01), 'eye_divergence_transverse_deg', [float(eye_p01), None]),
            calibration={
                'kind': CAL_VIOLATION_RATE,
                'predicate': _p_eye_not_parallel(eye_p01),
                'why': 'the p01 of the form sample, so 1% of it is below by construction',
                'source': src,
            },
        ),
    ]
