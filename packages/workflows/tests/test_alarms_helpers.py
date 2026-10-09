# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Each alarm `_build_alarms` raises, exercised on its own for the first time.

`_build_alarms` was a 311-line def inside which every alarm was an inline `if` block, so
no single alarm had ever been called in isolation: the only way to ask "does a CANON
threshold over a surveyed quantity alarm?" was to render a whole report. The split on
2026-10-09 gave each alarm its own helper, and these tests pin the condition and the
wording of the ones a drifting gate registry actually trips, plus the ORDER
`_build_alarms` prints them in — the renderer prints the list as it stands.
"""

from __future__ import annotations

from zyg_workflows.geom.anthro.report import alarms as A


def gate(gid, **kw):
    """A gate row with the fields the renderer always derives, overridden by **kw."""
    g = {
        'id': gid,
        'effective_status': 'pass',
        'crash_state': 'ran',
        'is_blocking_failure': False,
        'status_raw': 'pass',
        'status_recognised': True,
        'provenance_class': 'HOUSE',
        'malformed': False,
        'severity_class': 'low',
        'has_threshold': True,
    }
    g.update(kw)
    return g


def test_a_counted_status_with_no_column_is_alarmed_on_not_absorbed():
    """A bucket gates.py invented that the banner cannot print must be named, with its gates."""
    gates = [gate('g1', effective_status='mystery'), gate('g2')]
    out = A._stray_bucket_alarm({'PASS': 1, 'mystery': 1}, gates)
    assert out['kind'] == 'unrendered_status_bucket'
    assert out['gates'] == ['g1']
    assert "'mystery'" in out['text']
    assert 'must be taught to render them' in out['text']


def test_only_the_rendered_buckets_raise_no_alarm():
    """Every status the banner has a column for is silent — the alarm is for drift only."""
    assert A._stray_bucket_alarm({'PASS': 3}, [gate('g1')]) is None


def test_a_crash_with_blocking_severity_says_the_verdict_is_fail():
    """A crashed blocking gate checked nothing, and the text must say FAIL and name it."""
    gates = [
        gate('g_block', crash_state=A.CRASHED, is_blocking_failure=True),
        gate('g_warn', crash_state=A.CRASHED),
    ]
    out = A._crashed_alarm(gates, ['g_block', 'g_warn'])
    assert out['kind'] == 'gate_crashed'
    assert out['gates'] == ['g_block', 'g_warn']
    assert 'blocking severity on 1 of them, so the verdict is FAIL: g_block.' in out['text']
    assert 'never softened by a rejection rate' in out['text']


def test_a_crash_without_blocking_severity_is_a_warning_that_still_checked_nothing():
    """No blocking severity means no FAIL — but the sentence must not imply a pass."""
    out = A._crashed_alarm([gate('g_warn', crash_state=A.CRASHED)], ['g_warn'])
    assert 'none of them carries a blocking severity' in out['text']
    assert 'the checks still did not happen' in out['text']


def test_an_unrun_blocking_gate_names_the_ones_a_calibration_had_downgraded():
    """The declared severity is what makes an absent check count, not the rejection rate."""
    out = A._unrun_blocking_alarm(['g_a', 'g_b'], ['g_b'])
    assert out['kind'] == 'blocking_gate_did_not_run'
    assert 'produced NO VERDICT' in out['text']
    assert '1 of them (g_b) carry a blocking severity' in out['text']

    quiet = A._unrun_blocking_alarm(['g_a'], [])
    assert 'carry a blocking severity that the reference' not in quiet['text']


def test_a_canon_threshold_blocks_only_where_a_survey_is_silent():
    """A CANON row clashing with a survey alarms; one over silent ground does not."""
    gates = [
        gate(
            'g_clash',
            provenance_class='CANON',
            severity_class='high',
            threshold_quantities=['stature'],
            threshold_measured_conflict=True,
        ),
        gate(
            'g_silent_ground',
            provenance_class='CANON',
            severity_class='high',
            threshold_quantities=['elbow_angle'],
            threshold_measured_conflict=False,
        ),
        gate('g_mute', provenance_class='CANON', severity_class='unrecognised'),
        gate('g_advisory', provenance_class='CANON', severity_class='low'),
        gate('g_malformed', provenance_class='CANON', severity_class='high', malformed=True),
    ]
    out = A._canon_threshold_alarms(gates)
    assert [a['kind'] for a in out] == ['canon_threshold_blocking', 'canon_threshold_without_quantity']
    assert out[0]['gates'] == ['g_clash']
    assert 'ALREADY ANSWERS' in out[0]['text']
    assert out[1]['gates'] == ['g_mute']
    assert 'may not outrank a survey' in out[1]['text']


def test_a_measured_threshold_without_a_class_and_an_n_is_a_self_assessment():
    """MEASURED is only worth the evidence record behind it: no class or no n alarms."""
    gates = [
        gate('g_no_ev', provenance_class='MEASURED'),
        gate('g_no_n', provenance_class='MEASURED', threshold_evidence={'class': 'ANSUR II'}),
        gate('g_ok', provenance_class='MEASURED', threshold_evidence={'class': 'ANSUR II', 'n': 4082}),
        gate('g_report_only', provenance_class='MEASURED', has_threshold=False),
    ]
    out = A._measured_threshold_alarm(gates)
    assert out['kind'] == 'measured_threshold_without_evidence'
    assert out['gates'] == ['g_no_ev', 'g_no_n']
    assert A._measured_threshold_alarm([gates[2], gates[3]]) is None


def test_the_calibration_alarms_compare_the_severity_class_not_its_spelling():
    """'critical' and 'block' are both high, so a synonym must not be reported as drift."""
    gates = [gate('g_synonym', severity_class='high'), gate('g_real_drift', severity_class='low')]
    cal = {
        'rows': [
            {'id': 'g_uncal', 'kind': 'undeclared', 'effective': 'block'},
            {'id': 'g_synonym', 'effective': 'critical'},
            {'id': 'g_real_drift', 'effective': 'block'},
        ]
    }
    out = A._calibration_alarms(gates, cal)
    assert [a['kind'] for a in out] == ['uncalibrated_blocking_gate', 'severity_calibration_disagreement']
    assert out[0]['gates'] == ['g_uncal']
    assert out[1]['gates'] == ['g_real_drift']


def test_build_alarms_keeps_the_order_the_renderer_prints_and_returns_the_calibration():
    """The orchestrator appends the helpers' alarms in the one order the report expects."""
    gates = [
        gate('g_crash', crash_state=A.CRASHED, effective_status='error', is_blocking_failure=True),
        gate('g_refused', effective_status=A.GATE_ERROR, crash_state=A.RAN, is_blocking_failure=True),
        gate('g_badspell', status_raw='weird', status_recognised=False, effective_status='mystery'),
        gate('g_contested', provenance_class='CONTESTED'),
        gate('g_malformed', malformed=True),
    ]
    cal = {'rows': [{'id': 'g_uncal', 'kind': 'undeclared', 'effective': 'block'}]}
    out, severity_calibration = A._build_alarms(
        {'PASS': 1, 'mystery': 1},
        gates,
        {'severity_calibration': cal},
        ['g_crash'],
        ['g_refused'],
        ['g_undeclared_crash'],
        ['g_badspell'],
        ['g_unrun'],
        [],
    )
    assert [a['kind'] for a in out] == [
        'unrendered_status_bucket',
        'gate_crashed',
        'gate_verdict_refused',
        'crash_flag_not_declared',
        'unrecognised_status',
        'blocking_gate_did_not_run',
        'contested_threshold_shipped',
        'malformed_gate',
        'uncalibrated_blocking_gate',
    ]
    assert severity_calibration is cal


def test_build_alarms_accuses_no_engine_of_a_calibration_promise_it_never_made():
    """No calibration block (or a malformed one) means no calibration alarms and None back."""
    out, severity_calibration = A._build_alarms({'PASS': 1}, [gate('g1')], {}, [], [], [], [], [], [])
    assert out == []
    assert severity_calibration is None

    out, severity_calibration = A._build_alarms(
        {'PASS': 1}, [gate('g1')], {'severity_calibration': 'a string'}, [], [], [], [], [], []
    )
    assert out == []
    assert severity_calibration is None
