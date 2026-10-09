# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""geom.anthro.report — the unrun-blocking-rule and digest self-tests.

Moved out of the old single-file report.py (lines 4536-5034).
"""

from zyg_workflows.geom.anthro.report.constants import (
    FAIL,
    GATE_ERROR,
    PASS,
    _UNRUN_BLOCKING_STATUSES,
)
from zyg_workflows.geom.anthro.report.document import build
from zyg_workflows.geom.anthro.report.renderers import render_provenance, render_text
from zyg_workflows.geom.anthro.report import selftest_rules_digest as _DG


def _selftest_unrun_blocking_rule(doc):
    """THE PRINTED RULE NAMES EXACTLY WHAT THE CODE ENFORCES (re-review N1).

    The defect: `_NO_VERDICT` enforced ('skip', missing, 'unknown', error) while the
    printed `unrun_blocking_rule` said "skip, missing or unknown", and a status that was in
    neither list — 'report' — was consequently invisible on a blocking gate. This test
    fails on ANY divergence between the sentence and the tuple, in either direction, so a
    future status cannot be added to one and not the other.
    """
    # EVERY declared rule reaches the page. A rule that is enforced on every body and
    # readable only in the JSON is the same defect as a rule the code does not match.
    prov = ' '.join(render_provenance(doc).split())  # unwrapped, so line breaks do not
    for k, txt_ in sorted((doc['policy'] or {}).items()):  # make this test lie either way
        if k.endswith('_rule'):
            if not (k in prov and ' '.join(str(txt_).split())[:60] in prov):
                raise AssertionError('policy["%s"] is enforced and never printed' % k)
    rule = doc['policy']['unrun_blocking_rule']
    for st in _UNRUN_BLOCKING_STATUSES:
        if st not in rule:
            raise AssertionError(
                '%r produces no verdict and is escalated on a blocking gate, '
                'but the PRINTED rule does not name it: %r' % (st, rule)
            )
    if GATE_ERROR in _UNRUN_BLOCKING_STATUSES:
        raise AssertionError('a crash has its own rule and its own bucket; it is not an unrun check')
    # A BLOCK-SEVERITY 'report' ROW IS ESCALATED, COUNTED AND NAMED. This is the live shape
    # of N1: t5_pronation_isolation on abel and cornelis was a block-severity gate whose
    # status rolled up to 'report' and which appeared in no list on the page.
    ok = {
        'id': 'g_ok',
        'tier': 'frame',
        'severity': 'block',
        'status': 'pass',
        'observed': 0.5,
        'band': [0.0, 1.0],
        'source': 'HOUSE: fixture',
    }
    noted = {
        'id': 'g_note',
        'tier': 'frame',
        'severity': 'block',
        'status': 'report',
        'source': 'HOUSE: fixture',
        'explanation': 'measured and printed, never gated — on a BLOCKING gate',
    }
    d = build({'tiers': {'frame': [ok, noted]}}, None, name='n1', sex='male')
    row = [g for g in d['gates'] if g['id'] == 'g_note'][0]
    if row['produced_no_verdict'] is not True:
        raise AssertionError('a printed row is not a verdict')
    if row['escalated_unrun_blocking_gate'] is not True:
        raise AssertionError
    if not (row['effective_status'] == 'warn'):
        raise AssertionError(row['effective_status'])
    if row['is_blocking_failure'] is not False:
        raise AssertionError('a note cannot manufacture a FAIL')
    if 'g_note' not in d['unrun_blocking']:
        raise AssertionError(d['unrun_blocking'])
    if not (d['verdict'] != PASS):
        raise AssertionError('a blocking gate with no verdict is not a PASS')
    if 'BLOCKING GATES THAT DID NOT RUN' not in render_text(d):
        raise AssertionError
    if 'g_note' not in render_text(d):
        raise AssertionError
    # Control: the SAME row at a REPORT severity keeps its own bucket and is not escalated.
    low = build({'tiers': {'frame': [ok, dict(noted, severity='report')]}}, None, name='n1c', sex='male')
    lrow = [g for g in low['gates'] if g['id'] == 'g_note'][0]
    if not (lrow['effective_status'] == 'report' and lrow['escalated_unrun_blocking_gate'] is False):
        raise AssertionError('an informational row on an informational gate must stay informational')
    if not (low['unrun_blocking'] == []):
        raise AssertionError(low['unrun_blocking'])

    # WHAT "BLOCKING SEVERITY" MEANS: DECLARED OR CALIBRATED, WHICHEVER IS HIGHER.
    # The row the fixture carries as girths_wide_calibrated, in isolation: the registry
    # declared it blocking, the rejection-rate calibration downgraded it to a warning, and
    # then it produced no verdict. A calibration measures how often a BAND rejects a real
    # body; it may soften a verdict and it may not soften the absence of one.
    cal = {
        'id': 'g_cal',
        'tier': 'frame',
        'severity': 'warn',
        'severity_declared': 'block',
        'severity_calibrated': True,
        'reference_rejection_rate': 0.1197,
        'status': 'skipped',
        'source': 'HOUSE: fixture',
        'explanation': 'no band for this subject',
    }
    c = build({'tiers': {'frame': [ok, cal]}}, None, name='n1d', sex='male')
    crow = [g for g in c['gates'] if g['id'] == 'g_cal'][0]
    if not (crow['severity_class'] == 'low' and crow['severity_declared_class'] == 'high'):
        raise AssertionError
    if crow['blocking_severity'] is not True:
        raise AssertionError
    if not (crow['blocking_severity_by'] == 'declared'):
        raise AssertionError(crow['blocking_severity_by'])
    if crow['escalated_unrun_blocking_gate'] is not True:
        raise AssertionError('a rejection rate is a statement about a verdict; this gate produced none')
    if not (crow['effective_status'] == 'warn'):
        raise AssertionError
    if crow['is_blocking_failure'] is not False:
        raise AssertionError('a skip cannot manufacture a FAIL')
    if 'g_cal' not in c['unrun_blocking']:
        raise AssertionError(c['unrun_blocking'])
    if not (c['unrun_blocking_by_declared_severity'] == ['g_cal']):
        raise AssertionError('the rows escalated on the DECLARED severity alone must be named separately')
    ctxt = render_text(c)
    if not ('BLOCKING GATES THAT DID NOT RUN' in ctxt and 'g_cal' in ctxt):
        raise AssertionError
    if 'downgraded to a warning' not in ' '.join(a['text'] for a in c['policy_alarms']):
        raise AssertionError('the alarm must disclose that these rows were escalated against a downgrade')
    # CONTROL 1: a gate that DECLARED a low severity and was calibrated to a low one is not
    # dragged in. The rule is "declared or calibrated", not "everything that skipped".
    q = build(
        {'tiers': {'frame': [ok, dict(cal, id='g_q', severity_declared='advisory')]}}, None, name='n1e', sex='male'
    )
    if not (q['unrun_blocking'] == [] and q['unrun_blocking_by_declared_severity'] == []):
        raise AssertionError
    if not ([g for g in q['gates'] if g['id'] == 'g_q'][0]['effective_status'] == 'skip'):
        raise AssertionError
    # CONTROL 2: a gate that declares NO second severity is judged on the one it has.
    # _severity_class(None) is 'unrecognised' by design, so reading an absent declaration as
    # a severity would silently escalate every skipped advisory gate in the file.
    n = build(
        {
            'tiers': {
                'frame': [
                    ok,
                    {
                        'id': 'g_n',
                        'tier': 'frame',
                        'severity': 'advisory',
                        'status': 'skipped',
                        'source': 'HOUSE: fixture',
                    },
                ]
            }
        },
        None,
        name='n1f',
        sex='male',
    )
    if not (n['unrun_blocking'] == []):
        raise AssertionError(n['unrun_blocking'])
    nrow = [g for g in n['gates'] if g['id'] == 'g_n'][0]
    if not (nrow['severity_declared_class'] is None and nrow['blocking_severity'] is False):
        raise AssertionError
    # CONTROL 3: the DOWNGRADE direction is untouched. A calibrated-down gate that actually
    # FAILED still gets its failure softened to a warning — that is what a rejection rate is
    # for, and this test must not be read as taking calibration away.
    f = build(
        {'tiers': {'frame': [ok, dict(cal, id='g_f', status='fail', observed=0.9, band=[0.0, 0.5])]}},
        None,
        name='n1g',
        sex='male',
    )
    frow = [g for g in f['gates'] if g['id'] == 'g_f'][0]
    if not (frow['effective_status'] == 'warn' and frow['downgraded_by_severity'] is True):
        raise AssertionError
    if not (frow['is_blocking_failure'] is False and f['verdict'] != FAIL):
        raise AssertionError


def _selftest_digest(doc, fx):
    """A FIELD NAMED stable_sha256 THAT MOVED WITH THE CLOCK (re-review NEW-4).

    THE TEST THAT USED TO BE HERE was called 'digest must not include the clock' and it
    built the fixture twice and compared the two digests. It could only ever see a clock in
    the `volatile` block, because in a fixture built twice in the same second `volatile` is
    the only thing that differs — so when wave 2's evidence passthrough put per-gate
    wall-clock milliseconds inside gates[].evidence, this test passed, twice, through two
    re-reviews, while two real runs of abel with identical statuses on all 60 gates gave
    76889c274ec9 and 086f727a6721. A self-test that structurally cannot observe the defect
    it is named for is worse than no self-test: it blesses the bug.

    So this one does not re-run the clock, it MUTATES it, at the depth the real one lives
    at (gates[].evidence.ms and gates[].evidence.per_side.*.ms), and it fails in BOTH
    directions — a digest that moves with a timer, and a digest that has gone deaf to
    content because the strip grew too greedy.
    """
    sneaky = _DG.sneaky_gate()
    _DG.assert_fixture_is_armed(doc)
    _DG.assert_digest_ignores_the_clock(doc, fx)
    _DG.assert_unknown_clock_name_is_a_defect(sneaky)
    _DG.assert_silent_nonces_are_caught()
    _DG.assert_the_clock_vocabulary()
    _DG.assert_volatile_is_outside_the_digest(doc)
    _DG.assert_declared_content_clocks(sneaky)
    _DG.assert_structural_invariants()
