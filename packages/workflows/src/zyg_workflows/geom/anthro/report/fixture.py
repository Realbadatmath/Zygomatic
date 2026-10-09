# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""geom.anthro.report — the contract fixture.

Moved out of the old single-file report.py (lines 3819-4163).
"""

import time


# ---------------------------------------------------------------------------------
# the contract fixture
# ---------------------------------------------------------------------------------
def contract_fixture(character='fixture', sex='male'):
    """A gate report in the shape gates.py is documented to emit.

    This is NOT a measurement and NOT a set of thresholds to use. It exists so the
    renderer can be exercised — including on the awkward rows: an absent status, a
    DECLARED-missing status, an unrecognised severity, a malformed entry, a one-sided
    band, a CONTESTED gate, a gate whose severity was taken away by measurement, and a
    gate with no provenance at all. Every document it produces carries synthetic=True and
    every rendering of it prints a banner saying so, so that a fixture can never be
    mistaken for a verdict about a body.
    """
    return {
        'character': character,
        'sex': sex,
        'synthetic': True,
        'generated': time.strftime('%Y-%m-%dT%H:%M:%S'),
        'severity_calibration': _severity_calibration(),
        'tiers': {
            'frame': _frame_gates(),
            'heights': _height_gates(),
            'breadths': _breadth_gates(),
            'integrity': _integrity_gates(),
        },
    }


def _severity_calibration():
    """The severity-calibration block, in the shape gates.py emits it.

    Takes nothing. Returns the dict that sits under `severity_calibration`: the policy
    sentence, the 1 % ceiling, the reference sample, the per-sex independent-band
    admission fractions, one `rows` entry per calibrated gate (admitted / downgraded /
    not-applicable) and the `downgraded` id list. The numbers are the real measured ones
    so that the fixture demonstrates the actual policy, but they are still a fixture and
    are labelled SYNTHETIC in every rendering.
    """
    return {
        'policy': "a gate may carry severity 'block' only if it would reject at most "
        '1.0% of the real ANSUR II reference sample.',
        'ceiling': 0.01,
        'reference': 'per-subject ANSUR II 2012 public working databases (male n=4082, female n=1986)',
        'independent_bands_admission': {
            'male': {
                'method': 'fraction of the real sample inside ALL 10 independent p5-p95 bands',
                'admitted_fraction': 0.4716,
            },
            'female': {
                'method': 'fraction of the real sample inside ALL 10 independent p5-p95 bands',
                'admitted_fraction': 0.4600,
            },
        },
        'rows': [
            {
                'id': 'joint_plausibility_mahalanobis',
                'tier': 'frame',
                'declared': 'block',
                'effective': 'block',
                'rejection_rate': 0.01004,
                'basis': 'measured',
                'kind': 'empirical_percentile',
                'downgraded': False,
                'reason': 'rejects 1.004% of the real reference sample, within the 1.0% '
                'ceiling (+0.024% for the 1/n granularity of an empirical '
                'percentile on n=4082), so it may block.',
            },
            {
                'id': 'bideltoid_breadth_over_stature',
                'tier': 'breadths',
                'declared': 'block',
                'effective': 'warn',
                'rejection_rate': 0.1197,
                'basis': 'measured',
                'kind': 'ratio_bands',
                'downgraded': True,
                'reason': 'DOWNGRADED block -> warn: rejects 11.97% of the real '
                'reference sample, 12.0x the 1.0% ceiling.',
                'explain': '5 band(s) at p1p99; each single band excludes 2.0% by construction.',
            },
            {
                'id': 'volume_height_index',
                'tier': 'integrity',
                'declared': 'block',
                'effective': 'block',
                'rejection_rate': None,
                'basis': 'not_applicable',
                'kind': 'caller_declared_band',
                'downgraded': False,
                'reason': 'the band is declared by the caller; no survey publishes '
                'volume/stature^2, so there is no reference sample to reject a '
                'fraction of.',
            },
        ],
        'downgraded': ['bideltoid_breadth_over_stature'],
    }


def _frame_gates():
    """The `frame` tier rows. Takes nothing; returns the list of gate dicts.

    A passing stature check — carrying the per-gate wall clock in exactly the shape
    gates.py stamps into `detail`, nested per-side copies included, because that field is
    what made `stable_sha256` a per-run nonce and `_selftest_digest` is written to run
    against the real shape — and a joint-plausibility gate warning between p95 and p99.
    """
    return [
        {
            'id': 'stature_declared_vs_built',
            'tier': 'frame',
            'severity': 'critical',
            'status': 'pass',
            'observed': 1.8501,
            'band': {'lo': 1.848, 'hi': 1.852, 'units': 'm'},
            'source': 'HOUSE: +/-2 mm against the DECLARED BUILD TARGET, which is a '
            'reproducibility check on our own build, not an anthropometric '
            'accuracy claim',
            'explanation': 'built stature matches the recipe',
            # PER-GATE WALL CLOCK, in exactly the shape gates.py stamps it into
            # `detail` and the evidence passthrough copies into gates[].evidence —
            # including the nested per-side copies. This is the field that made
            # `stable_sha256` a per-run nonce (re-review NEW-4), and it is in the
            # fixture so that _selftest_digest runs against the real shape rather than
            # against a mock of it. Removing it from here disarms that test, which is
            # why the test asserts it is present before it asserts anything else.
            'detail': {
                'ms': 0.417,
                'target_m': 1.85,
                'per_side': {'L': {'ms': 0.19, 'value': 1}, 'R': {'ms': 0.22, 'value': 1}},
            },
        },
        {
            'id': 'joint_plausibility_mahalanobis',
            'tier': 'frame',
            'severity': 'critical',
            'status': 'warn',
            'observed': {'value': 22.41, 'units': 'D^2'},
            'band': {'lo': 0.0, 'hi': 20.09, 'width': 'empirical p99'},
            'source': 'MEASURED: ANSUR II 2012 public, male pooled, n=4082, '
            'empirical p99 of D^2 over the 10-ratio frame vector',
            'explanation': 'inside p99 is the pass condition; this body is between '
            'p95 and p99 — unusual but real, surface it, do not '
            'reject it',
        },
    ]


def _height_gates():
    """The `heights` tier rows. Takes nothing; returns the list of gate dicts.

    One failing ratio with a `population` caveat and a dict band, and one passing ratio
    whose band is a two-element LIST rather than a dict — both band shapes must render.
    """
    return [
        {
            'id': 'crotch_height_over_stature',
            'tier': 'heights',
            'severity': 'major',
            'status': 'fail',
            'observed': 0.4501,
            'band': {'lo': 0.4612, 'hi': 0.4990, 'width': 'p5p95'},
            'source': 'MEASURED: ANSUR II 2012 public, male pooled, n=4082',
            'population': 'US Army personnel male, pooled across DODRace groups. NOT a civilian population.',
            'explanation': 'legs short for this stature against the POOLED band; '
            'ancestry was not declared and the male group spread on '
            'this ratio is .024',
        },
        {
            'id': 'acromial_height_over_stature',
            'tier': 'heights',
            'severity': 'major',
            'status': 'pass',
            'observed': 0.8175,
            'band': [0.8050, 0.8320],
            'source': 'MEASURED: ANSUR II 2012 public, male pooled, n=4082',
        },
    ]


def _breadth_gates():
    """The `breadths` tier rows. Takes nothing; returns the list of gate dicts.

    The calibration-downgraded failure, the downgraded gate that then produced no verdict
    at all (the disclosed ambiguity in the unrun rule), and a CONTESTED one-sided band.
    """
    return [
        # Severity 'warn' is the EFFECTIVE severity: the registry declared 'block'
        # and the calibration took it away. Exercises both arithmetic paths at
        # once — the calibration downgrade of the SEVERITY, and this renderer's
        # own downgrade of the failing STATUS on the resulting low severity.
        {
            'id': 'bideltoid_breadth_over_stature',
            'tier': 'breadths',
            'severity': 'warn',
            'severity_declared': 'block',
            'severity_calibrated': True,
            'reference_rejection_rate': 0.1197,
            'severity_reason': 'DOWNGRADED block -> warn: rejects 11.97% of the real '
            'reference sample, 12.0x the 1.0% ceiling. A gate '
            'stricter than the population is a gate that rejects '
            'people who exist.',
            'severity_calibration': {'kind': 'ratio_bands', 'basis': 'measured', 'rate': 0.1197},
            'status': 'fail',
            'observed': 0.2712,
            'band': {'lo': 0.2410, 'hi': 0.2690, 'width': 'p5p95'},
            'source': 'MEASURED: ANSUR II 2012 public, male pooled, n=4082; stature '
            'predicts bideltoid at r=0.31, RMSE 30.9 mm, so this gate is '
            'WIDE by construction',
            'explanation': 'wide shoulders; a breadth is never gated against a stature-derived point',
        },
        # A BLOCKING GATE THE CALIBRATION DOWNGRADED, WHICH THEN PRODUCED NO
        # VERDICT — the live shape of the disclosed ambiguity in the unrun rule.
        # Seven instances shipped (t2_mahalanobis, t2_heights_tight,
        # t2_breadths_wide, t2_girths_wide, t3_depths_wide on abel; t2_breadths_wide
        # and t5_canthal_tilt on anny-neutral): declared 'block', calibrated to
        # 'warn' on their reference rejection rate, then skipped — and the rule
        # tested only the CALIBRATED severity, so not one of them was escalated,
        # counted or named while the printed rule said blocking-severity gates are.
        {
            'id': 'girths_wide_calibrated',
            'tier': 'breadths',
            'severity': 'warn',
            'severity_declared': 'block',
            'severity_calibrated': True,
            'reference_rejection_rate': 0.1197,
            'status': 'skipped',
            'source': 'HOUSE: fixture',
            'explanation': 'no band is available for this subject, so no judgement is '
            'possible — on a gate the REGISTRY declared blocking',
        },
        {
            'id': 'shoulder_waist_adonis',
            'tier': 'breadths',
            'severity': 'advisory',
            'status': 'fail',
            'observed': 1.42,
            'band': {'lo': 1.618, 'hi': None},
            'provenance_class': 'CONTESTED',
            'source': 'CONTESTED: the "Adonis index" 1.618 has no primary source and '
            'the commonly cited 2023 IJSM study does not exist',
            'explanation': 'present ONLY to prove the renderer alarms on a contested threshold',
        },
    ]


def _integrity_gates_judged():
    """The `integrity` rows for gates that reached a judgement (or declared none).

    Takes nothing; returns the first half of the integrity list: a passing mirror-symmetry
    check, a gate with its status field deliberately ABSENT, a gate that ran and found no
    caller-declared band (MISSING with a reason, not an unreadable row), a failure under
    an unrecognised severity, and a gate with no provenance field at all.
    """
    return [
        {
            'id': 'mirror_symmetry_morph_space',
            'tier': 'integrity',
            'severity': 'critical',
            'status': 'pass',
            'observed': {'value': 0.0, 'units': 'mm'},
            'band': {'lo': 0.0, 'hi': 0.05, 'units': 'mm'},
            'source': 'HOUSE: a mesh from a symmetric morph space has expected '
            'asymmetry of exactly 0, so the gate is at floating-point '
            'tolerance. This is NOT the realism-asymmetry check (0-10 mm, '
            'population mean 5.2 mm), which is a separate gate.',
        },
        {
            'id': 'watertight',
            'tier': 'integrity',
            'severity': 'critical',
            'status': None,
            'explanation': 'status deliberately absent: a missing field must render '
            'as unknown and count as a warning, never as a pass',
        },
        # The distinction Finding 5 turned on: this gate RAN and reached a
        # conclusion — the caller never declared the band it was supposed to check
        # against. That is a MISSING row with a reason, not an unreadable '????'.
        {
            'id': 'volume_height_index',
            'tier': 'integrity',
            'severity': 'block',
            'severity_declared': 'block',
            'status': 'missing',
            'observed': 21.4,
            'band': None,
            'severity_calibration': {'kind': 'caller_declared_band', 'basis': 'not_applicable', 'rate': None},
            'source': 'HOUSE: no survey on disk publishes volume/stature^2, so a VHI '
            'band cannot be derived and must be declared by the caller',
            'explanation': 'VHI = 21.40 L/m^2 but no band is declared. This gate '
            'will not invent one — declare spec["vhi_band"] for the '
            'character type.',
        },
        {
            'id': 'no_self_intersection',
            'tier': 'integrity',
            'severity': 'catastrophic',
            'status': 'fail',
            'observed': 3,
            'band': {'hi': 0},
            'source': 'HOUSE: any self-intersecting pair is a broken cage',
            'explanation': 'severity is deliberately not in the recognised '
            'vocabulary: an unrecognised severity must keep the '
            'failure, not downgrade it',
        },
        {
            'id': 'gate_without_provenance',
            'tier': 'integrity',
            'severity': 'minor',
            'status': 'pass',
            'observed': 1.0,
            'band': [0.0, 2.0],
            'explanation': 'no source field at all: must be reported as UNDECLARED',
        },
    ]


def _integrity_gates_disclosed():
    """The `integrity` rows an engine produced rather than a gate. Takes nothing.

    Returns the second half of the integrity list: the gate callable that RAISED
    (`crashed=True`), the gate that ran and whose verdict the engine replaced
    (`crashed=False`, same status — the whole point), a blocking gate that did not run,
    and the stray string that is not a gate at all.
    """
    return [
        # THE CRASHED BLOCKING GATE. gates.py runs strict=False in production, so
        # this row is what a raising gate actually looks like in the artifact. It
        # must render as ERROR in its own bucket, appear in doc['blocking'], and
        # take the verdict to FAIL — never be folded into 'unknown' and counted as
        # a warning, which shipped a body whose containment check never ran with
        # an amber "0 blocking" chip.
        {
            'id': 'shell_containment',
            'tier': 'integrity',
            'severity': 'block',
            'severity_declared': 'block',
            'status': 'error',
            'band': {'hi': 0},
            # THE PRODUCER'S FLAG (W4-1). This row is the genuine article: the gate
            # callable raised and the engine caught it. The flag is what says so —
            # the status no longer can, because the row below carries the same status
            # and did not raise.
            'crashed': True,
            'source': 'HOUSE: a shell that is not contained by the body is a broken '
            'cage; there is no population to measure a rejection rate '
            'against, so this gate blocks structurally',
            'explanation': 'gate raised IndexError: index 226 is out of bounds for '
            'axis 0 with size 226 — this gate checked NOTHING on this '
            'body',
        },
        # THE OTHER ERROR: A GATE THAT RAN AND WHOSE VERDICT THE ENGINE REFUSED
        # (W4-1). Modelled on the live t5_patellar_ligament row. It carries the
        # SAME status as the crash above and the OPPOSITE crashed flag, which is
        # the whole point: a renderer that reads `status == 'error'` prints "THIS
        # GATE RAISED. It checked nothing on this body" over a measured, blocking
        # anatomical failure — the patella-to-tuberosity distance drifting -15.54%
        # at 120 degrees, i.e. the ligament is not modelled — and files it as
        # infrastructure. Without this row in the fixture, _selftest_crash builds
        # only genuine crashes and cannot see the defect it is named for.
        {
            'id': 'patellar_ligament_provenance',
            'tier': 'integrity',
            'severity': 'block',
            'severity_declared': 'block',
            'status': 'error',
            'crashed': False,
            'observed': {'max_abs_drift': 0.1554, 'flexion_deg': 120},
            'band': {'max_abs_drift': 0.02},
            'source': 'HOUSE: the patella tracks the tuberosity through flexion; the '
            'distance between them is a ligament length and does not '
            'stretch',
            'explanation': 'PROVENANCE DISAGREEMENT, UNSAFE DIRECTION — AND THIS GATE '
            'DID NOT CRASH: it ran, it measured this body, and the '
            'engine replaced the verdict it produced because the form '
            'module tags the threshold CANON where the registry ships '
            'it HOUSE. THE VERDICT THIS ERROR REPLACES, which stands '
            "as the gate's own finding: fail — max_abs_drift 0.1554 "
            'against a band of 0.02, i.e. THE LIGAMENT IS NOT MODELLED',
            'detail': {
                'status_the_gate_would_have_returned': 'fail',
                'explain_the_gate_would_have_returned': 'patella-to-tuberosity distance drifts -15.54% at 120 deg',
                'module_provenance': 'CANON',
                'gate_crashed': False,
                'gate_ran_and_produced_a_verdict': True,
                'max_abs_drift': 0.1554,
            },
        },
        # A BLOCKING GATE THAT DID NOT RUN. Different from the crash: it reached a
        # definite "no judgement is possible", so it cannot manufacture a FAIL —
        # but it is escalated, named in doc['unrun_blocking'] and printed in the
        # banner, because "0 blocking" beside it would be a false statement.
        {
            'id': 'volume_plausibility',
            'tier': 'integrity',
            'severity': 'block',
            'severity_declared': 'block',
            'status': 'not_applicable',
            'band': None,
            'source': 'HOUSE: density-derived mass has no survey to check against for a non-adult body',
            'explanation': 'subject is outside the reference population, so no '
            'plausibility judgement is possible on this quantity',
        },
        'this string is not a gate at all',
    ]


def _integrity_gates():
    """The whole `integrity` tier, in rendering order. Takes nothing; returns the list.

    The judged rows first, then the engine-produced ones — the order is behaviour.
    """
    return [*_integrity_gates_judged(), *_integrity_gates_disclosed()]
