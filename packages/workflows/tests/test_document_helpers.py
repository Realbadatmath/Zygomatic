# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""document_parts — the stages geom.anthro.report.document.build() is made of.

`build` was a 541-line function, so not one of these decisions had ever been exercised on
its own: every assertion below used to be reachable only by rendering a whole document and
reading a field out of it. The cases are the ones the old body's comments say it exists
for — the three error-class populations kept apart (W4-1), the declared-roster denominator
(W4-3), the coverage floor (NEW-5), the stricter-of-two verdict reconciliation, and the
volatile block the digest cannot see into (W4-4).
"""

from zyg_workflows.geom.anthro.report.constants import CRASHED, CRASH_UNDECLARED, FAIL, GATE_ERROR, PASS, RAN, WARN
from zyg_workflows.geom.anthro.report import document_parts as dp


def _gate(gid, **over):
    """A gate row in the shape `evidence._read_gate` emits, defaulting to a clean pass."""
    row = {
        'id': gid,
        'tier': 'frame',
        'effective_status': 'pass',
        'crash_state': RAN,
        'status_recognised': True,
        'is_blocking_failure': False,
        'produced_no_verdict': False,
        'malformed': False,
        'blocking_severity': False,
        'blocking_severity_by': None,
        'source': 'HOUSE: test',
        'provenance_class': 'HOUSE',
    }
    row.update(over)
    return row


# ---------------------------------------------------------------------------------
# resolve_identity
# ---------------------------------------------------------------------------------
def test_identity_prefers_the_argument_then_the_measurement_then_the_gate_report():
    """An explicit argument wins; None means read it off the documents, meta first."""
    gr = {'character': 'from-gates', 'sex': 'female', 'ancestry': 'white'}
    meta = {'name': 'from-meta', 'sex_declared': 'male', 'stature_m': '1.85'}

    who = dp.resolve_identity(gr, {'meta': meta}, name=None, sex=None, ancestry=None, stature_m=None)
    assert (who.name, who.sex, who.ancestry) == ('from-meta', 'male', 'white')
    assert who.stature_m == 1.85  # _num() parsed the string the metadata carried

    told = dp.resolve_identity(gr, {'meta': meta}, name='told', sex='told', ancestry='told', stature_m=2.0)
    assert (told.name, told.sex, told.ancestry, told.stature_m) == ('told', 'told', 'told', 2.0)


def test_identity_survives_both_documents_being_absent():
    """A gate report that is not a mapping, and no measurement at all, must not raise."""
    who = dp.resolve_identity('not a dict', None, name=None, sex=None, ancestry=None, stature_m=None)
    assert who.meta == {} and who.gr == {}
    assert (who.name, who.sex, who.ancestry, who.stature_m) == (None, None, None, None)


# ---------------------------------------------------------------------------------
# classify_gates
# ---------------------------------------------------------------------------------
def test_the_three_error_classes_are_kept_apart():
    """W4-1: a gate that RAISED, one whose verdict was refused, and one that declared
    neither are three different facts and never share a list."""
    gates = [
        _gate('raised', effective_status=GATE_ERROR, crash_state=CRASHED),
        _gate('refused', effective_status=GATE_ERROR, crash_state=RAN),
        _gate('undeclared', effective_status=GATE_ERROR, crash_state=CRASH_UNDECLARED),
    ]
    b = dp.classify_gates(gates)
    assert b.crashed == ['raised']
    assert b.errored_no_crash == ['refused']
    assert b.error_crash_undeclared == ['undeclared']
    assert b.counts[GATE_ERROR] == 3


def test_an_unrecognised_status_is_named_and_never_filed_as_a_refusal():
    """A status spelling the renderer does not know arrives with crashed=False and reads as
    RAN; without status_recognised it would land in the "the engine REFUSED this verdict"
    bucket, which would be a claim nothing supports."""
    b = dp.classify_gates([_gate('odd', effective_status=GATE_ERROR, crash_state=RAN, status_recognised=False)])
    assert b.unrecognised_status == ['odd']
    assert b.errored_no_crash == []


def test_unrun_blocking_excludes_failures_and_malformed_rows_and_names_the_declared_subset():
    """A blocking gate that produced no verdict is escalated; a malformed row has no
    severity to call blocking, and a row escalated on the DECLARED severity alone is named
    separately so the change of rule is visible rather than inferable from a bigger count."""
    gates = [
        _gate('skipped', produced_no_verdict=True, blocking_severity=True, blocking_severity_by='calibrated'),
        _gate('downgraded', produced_no_verdict=True, blocking_severity=True, blocking_severity_by='declared'),
        _gate('failed', produced_no_verdict=True, blocking_severity=True, is_blocking_failure=True),
        _gate('garbage', produced_no_verdict=True, blocking_severity=True, malformed=True),
        _gate('soft', produced_no_verdict=True, blocking_severity=False),
    ]
    b = dp.classify_gates(gates)
    assert b.unrun_blocking == ['skipped', 'downgraded']
    assert b.unrun_blocking_by_declared == ['downgraded']
    assert b.blocking == ['failed']


# ---------------------------------------------------------------------------------
# coverage_block
# ---------------------------------------------------------------------------------
def test_the_denominator_is_the_declared_roster_not_the_rows_in_front_of_us():
    """W4-3: three passing gates out of a declared sixty is 5% coverage, not 100%. The
    defect this is named for exited 0 on exactly that document."""
    gates = [_gate('g%d' % i) for i in range(3)]
    roster = {'g%d' % i for i in range(60)}
    cov = dp.coverage_block(gates, roster, 'the test roster', True)
    assert cov.n_declared == 60
    assert cov.n_verdicts == 3
    assert round(cov.cov_fraction, 4) == 0.05
    assert cov.meets_floor is False
    assert len(cov.coverage['gates_declared_but_absent']) == 57
    assert [a['kind'] for a in cov.alarms] == ['declared_gates_absent', 'suite_coverage_below_floor']


def test_a_gate_that_produced_no_verdict_is_not_counted_as_one():
    """NEW-5: counted off the RAW status — an escalated skip renders as a warning but is
    still not a verdict, and a malformed row never produced one either."""
    gates = [_gate('ok'), _gate('skip', produced_no_verdict=True), _gate('junk', malformed=True)]
    cov = dp.coverage_block(gates, set(), 'the gates present', False)
    assert cov.n_declared == 3
    assert cov.n_verdicts == 1
    assert cov.coverage['n_produced_no_verdict'] == 2


def test_a_document_present_but_undeclared_gate_is_reported_rather_than_dropped():
    """A gate nobody declared is not an error, but the reader must be able to see it; the
    same list is what build() puts in doc['extra']."""
    cov = dp.coverage_block([_gate('a'), _gate('b')], {'a'}, 'the test roster', True)
    assert cov.gates_present_but_not_declared == ['b']
    assert cov.coverage['gates_present_but_not_declared'] == ['b']
    assert cov.n_declared == 2


def test_a_claimed_but_unavailable_roster_alarms_and_falls_back_to_the_gates_present():
    """An engine report whose roster could not be read is measured against itself and SAYS
    so: the fraction becomes an upper bound rather than a silent full score."""
    cov = dp.coverage_block([_gate('a')], set(), 'NO DECLARED ROSTER WAS AVAILABLE', True)
    kinds = [a['kind'] for a in cov.alarms]
    assert 'coverage_roster_unavailable' in kinds
    assert cov.n_declared == 1

    hand_built = dp.coverage_block([_gate('a')], set(), 'the gates present in this document', False)
    assert 'coverage_roster_unavailable' not in [a['kind'] for a in hand_built.alarms]


def test_an_empty_document_has_no_fraction_and_cannot_meet_the_floor():
    """No gates at all means no denominator: the fraction is None, not 1.0, and the
    printed alarm says "no gates at all" instead of a percentage."""
    cov = dp.coverage_block([], set(), 'the gates present in this document', False)
    assert cov.cov_fraction is None
    assert cov.meets_floor is False
    assert cov.coverage['floor_gates'] is None
    assert 'no gates at all' in cov.alarms[-1]['text']


# ---------------------------------------------------------------------------------
# initial_verdict / reconcile_declared_verdict
# ---------------------------------------------------------------------------------
def test_a_blocking_failure_is_a_fail_and_a_policy_alarm_alone_is_a_warning():
    """The verdict ladder, including the rule that a clean suite with an alarm on it is
    never a PASS."""
    clean = dp.classify_gates([_gate('a'), _gate('b')])
    assert dp.initial_verdict(clean, [], True) == PASS
    assert dp.initial_verdict(clean, [{'kind': 'anything'}], True) == WARN
    failed = dp.classify_gates([_gate('a', is_blocking_failure=True, effective_status='fail')])
    assert dp.initial_verdict(failed, [], True) == FAIL


def test_below_the_coverage_floor_pass_is_unreachable():
    """Enforced as its own step, not left to the fact that the floor alarm happens to
    force WARN: an all-skipped suite at a non-blocking severity used to render PASS."""
    clean = dp.classify_gates([_gate('a')])
    assert dp.initial_verdict(clean, [], False) == WARN
    assert dp.initial_verdict(clean, [], True) == PASS


def test_a_verdict_disagreement_keeps_the_stricter_of_the_two():
    """Reporting the renderer's own softer verdict is how a crashed blocking gate once
    shipped as PASS-WITH-WARNINGS, so the disagreement is never resolved in the body's
    favour — in either direction."""
    v, alarm = dp.reconcile_declared_verdict(WARN, {'verdict': 'FAIL'})
    assert v == FAIL
    assert alarm['kind'] == 'verdict_disagreement'
    assert "never resolved in the body's favour" in alarm['text']

    v, alarm = dp.reconcile_declared_verdict(FAIL, {'verdict': 'PASS'})
    assert v == FAIL and alarm is not None


def test_a_spelling_of_pass_with_warnings_is_not_a_disagreement():
    """'PASS WITH WARNING' and 'PASSWITHWARNINGS' both normalise onto the house verdict;
    an unknown verdict string and a non-string are ignored rather than guessed at."""
    for spelling in ('PASS WITH WARNING', 'PASSWITHWARNINGS', 'pass-with-warnings'):
        assert dp.reconcile_declared_verdict(WARN, {'verdict': spelling}) == (WARN, None)
    assert dp.reconcile_declared_verdict(PASS, {'verdict': 'SPLENDID'}) == (PASS, None)
    assert dp.reconcile_declared_verdict(PASS, {'verdict': None}) == (PASS, None)
    assert dp.reconcile_declared_verdict(PASS, {}) == (PASS, None)


# ---------------------------------------------------------------------------------
# strip_block / provenance_map / ratio_summary
# ---------------------------------------------------------------------------------
def test_no_measurement_or_no_sex_means_no_strip_and_no_alarm():
    """The strip is the part that shows stylization and must not depend on anything having
    gone wrong — but without a declared sex there is no band to score against."""
    assert dp.strip_block(None, [], PASS, sex='male', ancestry=None, band_width='p5p95', stature_m=None, ref=None) == (
        [],
        [],
        PASS,
    )
    assert dp.strip_block(
        {'ratios': {}}, [], PASS, sex=None, ancestry=None, band_width='p5p95', stature_m=None, ref=None
    ) == (
        [],
        [],
        PASS,
    )


def test_gates_are_associated_to_ratios_by_exact_id_only(monkeypatch):
    """A fuzzy id-to-ratio association would attribute a gate to the wrong measurement,
    which is worse than no association at all. Proved through the strip's own call."""
    seen = {}

    def fake_ratio_rows(ratios, sex, ancestry, **kw):
        seen.update(kw['gates_by_ratio'])
        return []

    monkeypatch.setattr(dp, 'ratio_rows', fake_ratio_rows)
    gates = [_gate('crotch_height_over_stature'), _gate('crotch_height'), _gate('unmeasured')]
    measurement = {'ratios': {'crotch_height_over_stature': 0.45, 'other': 1.0}}
    dp.strip_block(
        measurement, gates, PASS, sex='male', ancestry=None, band_width='p5p95', stature_m=None, ref=object()
    )
    assert seen == {'crotch_height_over_stature': 'crotch_height_over_stature'}


def test_a_strip_that_mostly_failed_to_score_holds_the_verdict_and_says_so(monkeypatch):
    """A per-ratio lookup failure is caught and rendered, which is right for one ratio and
    very wrong for all of them: a bad ancestry would otherwise produce a clean-looking
    report in which nothing was checked."""
    rows = [
        {'ratio': 'a', 'status': 'band-error', 'note_render': 'pack missing'},
        {'ratio': 'b', 'status': 'no-reference'},
        {'ratio': 'c', 'status': 'band-error'},
        {'ratio': 'd', 'status': 'ok', 'percentile': 50},
    ]
    monkeypatch.setattr(dp, 'ratio_rows', lambda *a, **kw: rows)
    got, alarms, v = dp.strip_block(
        {'ratios': {'a': 1}}, [], PASS, sex='male', ancestry='nowhere', band_width='p5p95', stature_m=None, ref=1
    )
    assert got is rows
    assert [a['kind'] for a in alarms] == ['reference_lookup_failing']
    assert '3 of 4 ratios' in alarms[0]['text'] and 'pack missing' in alarms[0]['text']
    assert v == WARN


def test_a_strip_that_could_not_be_built_at_all_alarms_without_failing_the_body(monkeypatch):
    """A missing reference pack is a renderer problem, not a finding about the body: it
    holds PASS at PASS-WITH-WARNINGS and leaves a FAIL alone."""

    def boom(*a, **kw):
        raise RuntimeError('pack missing')

    monkeypatch.setattr(dp, 'ratio_rows', boom)
    rows, alarms, v = dp.strip_block(
        {'ratios': {'a': 1}}, [], PASS, sex='male', ancestry=None, band_width='p5p95', stature_m=None, ref=None
    )
    _, _, kept = dp.strip_block(
        {'ratios': {'a': 1}}, [], FAIL, sex='male', ancestry=None, band_width='p5p95', stature_m=None, ref=None
    )
    assert rows == []
    assert alarms[0]['kind'] == 'strip_unavailable' and 'pack missing' in alarms[0]['text']
    assert v == WARN and kept == FAIL


def test_provenance_groups_by_source_and_leaves_undeclared_gates_out():
    """A gate with no source is reported as UNDECLARED elsewhere; filing it under a source
    literally named "undeclared" would invent a provenance it never had."""
    gates = [
        _gate('a', source='MEASURED: ansur', provenance_class='MEASURED'),
        _gate('b', source='MEASURED: ansur', provenance_class='MEASURED'),
        _gate('c', source='UNDECLARED'),
    ]
    rows = [{'ratio': 'r1', 'source': 'MEASURED: ansur'}, {'ratio': 'r2'}]
    prov = dp.provenance_map(gates, rows, 'UNDECLARED')
    assert prov == {'MEASURED: ansur': {'class': 'MEASURED', 'gates': ['a', 'b', 'strip:r1']}}


def test_ratio_summary_counts_every_way_a_row_can_fail_to_be_scored():
    """n_no_band is the union of the four unscored statuses; a row with a percentile is
    banded whatever else it says."""
    rows = [
        {'percentile': 50, 'status': 'inside'},
        {'percentile': 99, 'status': 'outside'},
        {'status': 'no-band'},
        {'status': 'no-reference'},
        {'status': 'band-error'},
        {'status': 'no-value'},
    ]
    assert dp.ratio_summary(rows) == {'n': 6, 'n_banded': 2, 'n_outside': 1, 'n_no_band': 4}


# ---------------------------------------------------------------------------------
# policy_block / volatile_block / finalise_digest
# ---------------------------------------------------------------------------------
def test_the_printed_coverage_rule_names_the_denominator_it_was_computed_against():
    """The sentence used to say "of the declared gates" while the arithmetic used the gates
    PRESENT. It is generated from the roster source and the two numbers, so it cannot mean
    something the arithmetic did not do."""
    policy = dp.policy_block('the live registry', 60, 3)
    rule = policy['coverage_floor_rule']
    assert 'the live registry' in rule
    assert '60 gate(s), of which 3 are in this document' in rule
    assert policy['class'] == 'HOUSE'
    # The status vocabularies are interpolated from the enforced tuples, never retyped.
    assert 'skip, report, missing, unknown' in policy['unrun_blocking_rule']


def test_the_volatile_block_carries_only_instrumentation():
    """Four keys, all of them a record of when something ran or how long it took — the
    block is dropped from the digest by name, so content here would be invisible twice."""
    vol = dp.volatile_block({'generated': 'gr-clock'}, {'generated': 'm-clock', 'elapsed_s': 2.5})
    assert vol['gate_report_generated'] == 'gr-clock'
    assert vol['measurement_generated'] == 'm-clock'
    assert vol['measurement_elapsed_s'] == 2.5
    assert vol['generated']  # this process's own wall clock
    assert set(vol) == {'generated', 'gate_report_generated', 'measurement_generated', 'measurement_elapsed_s'}
    assert dp.volatile_block(None, {})['gate_report_generated'] is None


def _doc(**over):
    """The smallest document finalise_digest will accept, defaulting to a clean PASS."""
    doc = {
        'verdict': PASS,
        'exit_code': 0,
        'policy_alarms': [],
        'volatile': {'generated': '2026-01-01T00:00:00'},
    }
    doc.update(over)
    return doc


def test_a_clean_document_gets_a_stable_digest_that_it_can_reproduce():
    """The field's NAME makes a claim; `stable` states it as a checkable fact."""
    doc = _doc()
    dp.finalise_digest(doc, doc['policy_alarms'])
    assert doc['digest']['stable'] is True
    assert doc['digest']['unstable_fields'] is None
    assert len(doc['stable_sha256']) == 64
    assert doc['verdict'] == PASS

    twin = _doc(volatile={'generated': 'a completely different clock'})
    dp.finalise_digest(twin, twin['policy_alarms'])
    assert twin['stable_sha256'] == doc['stable_sha256']  # volatile is excluded by name


def test_content_hidden_in_the_volatile_block_is_found_and_costs_the_pass():
    """W4-4: that block is dropped from the hash by name AND the residue detector runs on
    a tree it has already been removed from, so a content field there is invisible twice
    over — the report could change and the digest could not."""
    doc = _doc(volatile={'generated': '2026-01-01T00:00:00', 'stature_m': 1.85})
    dp.finalise_digest(doc, doc['policy_alarms'])
    assert doc['digest']['stable'] is False
    assert doc['digest']['volatile_content_fields'] == ['volatile.stature_m']
    assert [a['kind'] for a in doc['policy_alarms']] == ['volatile_contains_content']
    assert doc['verdict'] == WARN  # a digest that cannot see the report is not a pass


def test_a_clock_that_survived_the_strip_is_named_and_the_alarm_is_inside_the_hash():
    """NEW-4: the per-run clock that made stable_sha256 a nonce. The finding is content, so
    it is raised BEFORE the digest is taken and the inventory is retaken over the document
    that will actually be hashed — doc['stable_sha256'] must equal stable_sha(doc)."""
    from zyg_workflows.geom.anthro.report.digest import stable_sha

    doc = _doc(gates=[{'id': 'a', 'finished_at_unix': 1760000000}])
    dp.finalise_digest(doc, doc['policy_alarms'])
    assert doc['digest']['stable'] is False
    assert doc['digest']['unstable_fields']
    assert [a['kind'] for a in doc['policy_alarms']] == ['digest_includes_the_clock']
    assert doc['verdict'] == WARN
    assert doc['stable_sha256'] == stable_sha(doc)


def test_a_failing_document_is_not_softened_by_a_digest_finding():
    """Only PASS is held; FAIL stays FAIL and keeps its exit code."""
    doc = _doc(verdict=FAIL, exit_code=2, volatile={'generated': 'x', 'stature_m': 1.85})
    dp.finalise_digest(doc, doc['policy_alarms'])
    assert doc['verdict'] == FAIL
    assert doc['digest']['stable'] is False
