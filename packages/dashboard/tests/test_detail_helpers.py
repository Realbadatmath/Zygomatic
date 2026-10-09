# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Unit tests for the helpers the 666-line `quality_detail` was split into.

Every name tested here used to be a nested `def` or an inline block of that one function,
so these are the first tests that exercise the logic in isolation: the five former closures
(now `DetailContext` methods), the per-tile builders, the gate-family tally, the fallback
detail tally, the receipt / VLM row builders and the verdict label-and-tone pair.
"""

from __future__ import annotations

import pytest

from zyg_dashboard.metrics_hub import detail as D
from zyg_dashboard.metrics_hub import detail_context as DC
from zyg_dashboard.metrics_hub import detail_runs as DR


from zyg_dashboard.metrics_hub import detail_tiles as DT
from zyg_dashboard.metrics_hub.helpers import _iso
from zyg_dashboard.metrics_hub.quality import _fb_key, _fb_name


@pytest.fixture(autouse=True, scope='module')
def _close_postgres_pools():
    """The run readers open a Postgres pool on first use; close it so no pool thread outlives the module.

    The API harness asserts at session end that no background thread leaked.
    """
    yield
    from zyg_workflows import pgdb

    pgdb.close_all()


DAY = 86400.0
NOW = 1760000000.0  # a fixed clock; every expected timestamp below is derived from it

RID_REAL = 'gates-20260101-101010-4242'
RID_REAL2 = 'gates-20260102-101010-4243'
RID_TEST = 'pytest-session-999999'
RID_TMP = 'gates-20260103-101010-777'  # a run whose debug dir was under /tmp

# (run_id, gate, outcome, score, tag, ts) — exactly the shape _ledger_rows yields.
GATES = [
    (RID_REAL, 'licence:provenance', 'pass', 0.9, 'ok', NOW - 1 * DAY),
    (RID_REAL, 'licence:attest', 'fail', None, '', NOW - 2 * DAY),
    (RID_REAL2, 'licence:attest', 'shadow_fail', 0.1, '', NOW - 3 * DAY),
    (RID_REAL2, '', 'weird', None, None, NOW - 4 * DAY),
    ('adhoc', 'licence:provenance', 'pass', 0.5, '', NOW - 5 * DAY),
    (RID_TEST, 'licence:attest', 'pass', 0.7, '', NOW - 6 * DAY),
    (RID_TMP, 'licence:attest', 'fail', 0.2, '', NOW - 7 * DAY),
    (RID_REAL, 'licence:provenance', 'pass', 0.8, '', NOW - 200 * DAY),  # outside a 30-day window
]

# (component, expected, actual, detail, run_id, ts)
FALLS = [
    ('lora:/models/lora/foo.safetensors', 'foo', 'none', 'file missing', RID_REAL, NOW - 1 * DAY),
    ('lora:/models/lora/foo.safetensors', 'foo', 'none', 'file missing', 'adhoc', NOW - 2 * DAY),
    ('lora:/models/lora/foo.safetensors', 'foo', 'none', '', RID_REAL2, NOW - 3 * DAY),
    ('tts', 'xtts', 'piper', 'no gpu', RID_TEST, NOW - 4 * DAY),
]

FB_KEY = _fb_key(_fb_name(FALLS[0][0]), 'foo', 'none')


def ctx(*, days=30, kind='tile', key='pass_rate', gates=None, falls=None, hist=None, names=None):
    """A DetailContext over the fixture ledger, with the window `days` resolves to."""
    return DC.DetailContext(
        token=f'{kind}:{key}',
        kind=kind,
        key=key,
        days=days,
        now=NOW,
        since=(NOW - days * DAY) if days else None,
        window=f'last {days} days' if days else 'all time',
        test_ids={RID_TMP},
        test_pids={'999999'},
        gates=list(GATES if gates is None else gates),
        falls=list(FALLS if falls is None else falls),
        hist=dict(hist or {}),
        names=dict(names or {RID_REAL: 'render / probe'}),
    )


# ── the five former closures, now DetailContext methods ──────────────────────


def test_in_window_is_inclusive_at_the_edge_and_rejects_a_missing_timestamp():
    c = ctx(days=30)
    assert c.in_window(NOW - 30 * DAY) is True
    assert c.in_window(NOW - 30 * DAY - 1) is False
    assert c.in_window(None) is False


def test_in_window_accepts_everything_when_the_window_is_all_time():
    c = ctx(days=0)
    assert c.since is None
    assert c.in_window(None) is True
    assert c.in_window(NOW - 5000 * DAY) is True


def test_cls_of_separates_real_adhoc_and_the_two_kinds_of_test_row():
    c = ctx()
    assert c.cls_of(RID_REAL) == 'real'
    assert c.cls_of('adhoc') == 'unattributed'
    assert c.cls_of('') == 'unattributed'
    assert c.cls_of(RID_TEST) == 'test'
    assert c.cls_of(RID_TMP) == 'test'


def test_test_reason_names_the_rule_that_dropped_the_row():
    c = ctx()
    assert c.test_reason(RID_TMP) == 'debug dir under /tmp or pytest'
    assert c.test_reason('some-run-999999') == 'shares pytest process id 999999'
    assert c.test_reason('12345') == 'numeric run id'


def test_gate_rows_windows_filters_and_sorts_newest_first():
    c = ctx(days=30)
    rows, n = c.gate_rows(lambda r: r[6] == 'real')
    assert n == 4  # the 200-day-old row is out of range, three rows are test/unattributed
    assert [r[0] for r in rows] == [_iso(NOW - d * DAY) for d in (1, 2, 3, 4)]
    assert rows[0][1] == 'licence:provenance'
    assert rows[0][2] == {'v': 'pass', 'tone': 'good'}
    assert rows[3][1] == '(unnamed)'  # an empty gate name is drawn, not dropped


def test_gate_rows_unwindowed_also_returns_the_old_row_and_the_attribution_cell():
    rows, n = ctx(days=30).gate_rows(lambda r: r[1] == RID_REAL, windowed=False)
    assert n == 3
    assert rows[-1][0] == _iso(NOW - 200 * DAY)
    assert rows[0][5] == {'v': 'real', 'muted': False}
    assert rows[0][6]['detail'] == 'run:' + RID_REAL


def test_fall_rows_links_the_component_unless_link_is_false():
    c = ctx()
    linked, n = c.fall_rows(lambda r: r[6] != 'test')
    assert n == 3
    assert linked[0][1] == {'v': 'lora:foo.safetensors', 'detail': 'fallback:' + FB_KEY}
    plain, _ = c.fall_rows(lambda r: r[6] != 'test', link=False)
    assert plain[0][1] == {'v': 'lora:foo.safetensors', 'detail': None}
    assert plain[0][2] == 'foo → none'


def test_out_drops_falsy_facts_and_tables_and_reports_the_window():
    c = ctx(days=7, kind='family', key='licence')
    payload = c.out('T', 'S', [{'label': 'a'}, None], [{'title': 'x'}, None], notes=('n',))
    assert payload['ok'] is True
    assert payload['token'] == 'family:licence'
    assert payload['kind'] == 'family'
    assert payload['facts'] == [{'label': 'a'}]
    assert payload['tables'] == [{'title': 'x'}]
    assert payload['notes'] == ['n']
    assert (payload['window_days'], payload['window']) == (7, 'last 7 days')


def test_out_lets_one_section_override_the_window_text():
    got = ctx().out('T', 'S', [], [], win='all time — a run is one event, not a window')
    assert got['window'] == 'all time — a run is one event, not a window'
    assert got['window_days'] == 30


def test_build_detail_context_parses_the_token_and_resolves_the_window(monkeypatch):
    monkeypatch.setattr(DC, '_test_run_ids', lambda: ({'t'}, {'9'}, ['r']))
    monkeypatch.setattr(DC, '_ledger_rows', lambda: (list(GATES), list(FALLS)))
    monkeypatch.setattr(DC, '_debug_index', lambda: ({'k': {}}, {RID_REAL: 'n'}))
    c = DC.build_detail_context('run:abc:def', days=30, now=NOW)
    assert (c.kind, c.key) == ('run', 'abc:def')  # only the FIRST colon splits
    assert (c.since, c.window) == (NOW - 30 * DAY, 'last 30 days')
    assert (c.test_ids, c.test_pids, c.real_debug) == ({'t'}, {'9'}, ['r'])
    assert c.gates == GATES and c.falls == FALLS
    assert c.hist == {'k': {}} and c.names == {RID_REAL: 'n'}


def test_build_detail_context_with_days_zero_has_no_lower_bound():
    c = DC.build_detail_context('', days=0, now=NOW)
    assert (c.kind, c.key, c.since, c.window) == ('', '', None, 'all time')


# ── tiles ────────────────────────────────────────────────────────────────────


def test_outcome_count_counts_only_windowed_rows_of_one_attribution():
    c = ctx(days=30)
    assert DT._outcome_count(c, 'real', 'pass') == 1  # the second pass is 200 days old
    assert DT._outcome_count(c, 'real', 'fail') == 1
    assert DT._outcome_count(c, 'unattributed', 'pass') == 1
    assert DT._outcome_count(c, 'test', 'fail') == 1
    assert DT._outcome_count(c, 'real', 'shadow_fail') == 1
    assert DT._outcome_count(c, 'real', 'nothing') == 0


def test_outcome_count_is_case_insensitive_on_the_recorded_outcome():
    c = ctx(gates=[(RID_REAL, 'g', 'PASS', None, '', NOW)])
    assert DT._outcome_count(c, 'real', 'pass') == 1


def test_tile_section_refuses_a_tile_it_does_not_know():
    assert DT.tile_section(ctx(key='nonesuch')) == {'ok': False, 'error': "unknown tile 'nonesuch'"}


def test_tile_attributed_titles_itself_from_the_token_and_pools_only_real_rows():
    for key, title in (('pass_rate', 'Gate pass rate'), ('attributed', 'Attributed gate outcomes')):
        got = DT._tile_attributed(ctx(key=key))
        assert got['title'] == title
        facts = {f['label']: f['value'] for f in got['facts']}
        assert facts == {
            'Pass rate': '50.0 %',
            'Pass': '1',
            'Fail': '1',
            'Rows': '4',
            'Gate families': '2',  # 'licence' and the '(unnamed)' empty gate name
        }


def test_tile_unattributed_keeps_its_own_rate_and_says_it_is_not_pooled():
    got = DT._tile_unattributed(ctx(key='unattributed'))
    facts = {f['label']: (f['value'], f['sub']) for f in got['facts']}
    assert facts['Rows'][0] == '1'
    assert facts['Pass'][0] == '1'
    assert facts['Pass rate'] == ('100.0 %', 'not pooled with the attributed rate')


def test_tile_unattributed_rate_is_a_dash_when_nothing_passed_or_failed():
    got = DT._tile_unattributed(ctx(key='unattributed', gates=[]))
    assert {f['label']: f['value'] for f in got['facts']}['Pass rate'] == '—'


def test_test_gate_table_names_the_exclusion_rule_in_the_last_column():
    rows, table = DT._test_gate_table(ctx(key='test_rows'))
    assert len(rows) == len(table) == 2
    assert [r[0] for r in table] == [_iso(NOW - 6 * DAY), _iso(NOW - 7 * DAY)]
    assert table[0][-1] == {'v': 'shares pytest process id 999999', 'muted': True}
    assert table[1][-1] == {'v': 'debug dir under /tmp or pytest', 'muted': True}


def test_test_fall_table_draws_only_the_test_fallback_rows():
    table = DT._test_fall_table(ctx(key='test_rows'))
    assert len(table) == 1
    assert table[0][1] == 'tts'
    assert table[0][2] == 'xtts → piper'
    assert table[0][3] == {'v': RID_TEST, 'muted': True}


def test_receipt_run_row_counts_the_gates_that_ran_and_names_those_that_did_not():
    run = {
        'id': 'run-aaaaaaaa',
        't': NOW,
        'kind': 'scholarly',
        'title': '',
        'gate_receipts': {
            'vlm': {'ran': True, 'reason': ''},
            'licence': {'ran': False, 'reason': 'no assets'},
            'anatomy': {'ran': False, 'reason': ''},
        },
    }
    cells = DT._receipt_run_row(run)['cells']
    assert cells[3] == {'v': '—', 'muted': True}  # an untitled run is drawn muted
    assert cells[4] == '1'
    assert cells[5] == {'v': '2', 'tone': 'warning'}
    assert cells[6] == {'v': 'anatomy, licence', 'muted': True}


def test_receipt_run_row_has_no_warning_tone_when_every_gate_ran():
    run = {'id': 'r', 't': NOW, 'kind': 'k', 'title': 'T', 'gate_receipts': {'vlm': {'ran': True, 'reason': ''}}}
    cells = DT._receipt_run_row(run)['cells']
    assert cells[5] == {'v': '0', 'tone': None}
    assert cells[6] == {'v': '—', 'muted': True}


# ── one gate family ──────────────────────────────────────────────────────────


def test_family_of_takes_everything_before_the_first_colon():
    assert DT._family_of('licence:attest:v2') == 'licence'
    assert DT._family_of('vlm') == 'vlm'
    assert DT._family_of('') == '(unnamed)'
    assert DT._family_of(None) == '(unnamed)'


def test_family_tally_buckets_by_attribution_and_remembers_the_newest_row():
    per = DT.family_tally(ctx(kind='family', key='licence'), 'licence')
    assert set(per) == {'licence:provenance', 'licence:attest'}
    assert per['licence:provenance'] == {
        'pass': 1,
        'fail': 0,
        'shadow_fail': 0,
        'other': 0,
        'unattributed': 1,
        'test': 0,
        'last': NOW - 1 * DAY,
    }
    assert per['licence:attest'] == {
        'pass': 0,
        'fail': 1,
        'shadow_fail': 1,
        'other': 0,
        'unattributed': 0,
        'test': 2,
        'last': NOW - 2 * DAY,
    }


def test_family_tally_sends_an_unknown_outcome_to_other_and_names_the_empty_gate():
    per = DT.family_tally(ctx(kind='family', key='(unnamed)'), '(unnamed)')
    assert per == {
        '(unnamed)': {
            'pass': 0,
            'fail': 0,
            'shadow_fail': 0,
            'other': 1,
            'unattributed': 0,
            'test': 0,
            'last': NOW - 4 * DAY,
        }
    }


def test_family_breakdown_orders_by_pass_plus_fail_then_alphabetically():
    per = {
        'b': {'pass': 1, 'fail': 1, 'shadow_fail': 0, 'other': 0, 'unattributed': 0, 'test': 0, 'last': 0},
        'a': {'pass': 1, 'fail': 1, 'shadow_fail': 0, 'other': 0, 'unattributed': 0, 'test': 0, 'last': NOW},
        'c': {'pass': 0, 'fail': 0, 'shadow_fail': 3, 'other': 0, 'unattributed': 2, 'test': 1, 'last': 0},
    }
    out = DT.family_breakdown(per)
    assert [r[0] for r in out] == ['a', 'b', 'c']
    assert out[0][3] == {'v': '50.0 %', 'tone': None}
    assert out[0][7] == _iso(NOW)
    assert out[2][3] == {'v': '—', 'tone': None}  # no pass and no fail is not 0 %
    assert out[2][4:8] == ['3', '2', '1', '—']


def test_family_section_refuses_a_family_with_no_rows_in_range():
    got = DT.family_section(ctx(kind='family', key='nothere'))
    assert got == {'ok': False, 'error': "no gate rows for family 'nothere' in this range"}


# ── one fallback component ───────────────────────────────────────────────────


def test_fallback_detail_tally_counts_distinct_details_and_skips_the_empty_ones():
    assert DT.fallback_detail_tally(FALLS) == {'file missing': 2, 'no gpu': 1}


def test_fallback_detail_tally_collapses_whitespace_and_clips_at_200_chars():
    rows = [('c', 'e', 'a', 'a\n  b', 'r', NOW), ('c', 'e', 'a', 'x' * 250, 'r', NOW)]
    tally = DT.fallback_detail_tally(rows)
    assert tally['a b'] == 1
    assert tally['x' * 200] == 1


def test_fallback_section_refuses_a_component_key_it_never_recorded():
    got = DT.fallback_section(ctx(kind='fallback', key='deadbeef'))
    assert got == {'ok': False, 'error': 'unknown fallback component'}


# ── receipts, VLM counters, chart buckets ────────────────────────────────────

RUNS = [
    {
        'id': 'run-aaaaaaaa',
        't': NOW - 1 * DAY,
        'kind': 'scholarly',
        'title': 'A film',
        'status': 'completed',
        'gate_receipts': {'vlm': {'ran': True, 'reason': ''}, 'licence': {'ran': False, 'reason': 'no assets'}},
        'vlm': {'frames_checked': 12},
    },
    {
        'id': 'run-bbbbbbbb',
        't': NOW - 2 * DAY,
        'kind': 'kidsmusic',
        'title': '',
        'status': 'failed',
        'gate_receipts': {'vlm': {'ran': False, 'reason': 'disabled'}},
        'vlm': {'frames_checked': 40},
    },
    {
        'id': 'run-cccccccc',
        't': NOW - 3 * DAY,
        'kind': 'remix',
        'title': 'C',
        'status': 'running',
        'gate_receipts': {'vlm': {'ran': False, 'reason': 'disabled'}},
    },
    {'id': 'run-dddddddd', 't': NOW - 400 * DAY, 'kind': 'remix', 'title': 'D', 'status': 'completed'},
]


@pytest.fixture
def runs_on_disk(monkeypatch):
    """Both section modules read the run ledger through their own `collect_runs` name."""
    monkeypatch.setattr(DR, 'collect_runs', lambda now: ([dict(r) for r in RUNS], {}))
    monkeypatch.setattr(DT, 'collect_runs', lambda now: ([dict(r) for r in RUNS], {}))
    return RUNS


def test_run_cells_draws_the_shared_run_columns_and_tones_the_status():
    cells = DR._run_cells(RUNS[0], ['tail'])
    assert cells == [
        _iso(NOW - 1 * DAY),
        'run-aaaaaaaa',
        'scholarly',
        {'v': 'A film', 'muted': False},
        {'v': 'completed', 'tone': 'good'},
        'tail',
    ]
    assert DR._run_cells(RUNS[1], [])[4] == {'v': 'failed', 'tone': 'critical'}
    assert DR._run_cells(RUNS[2], [])[4] == {'v': 'running', 'tone': None}


def test_receipt_rows_splits_ran_from_did_not_and_tallies_the_reasons(runs_on_disk):
    ran, notrun, reasons = DR.receipt_rows(ctx(kind='receipt', key='vlm'), 'vlm')
    assert [r[1] for r in ran] == ['run-aaaaaaaa']
    assert [r[1] for r in notrun] == ['run-bbbbbbbb', 'run-cccccccc']  # newest first
    assert reasons == {'disabled': 2}
    assert ran[0][5] == {'v': '—', 'muted': True}
    assert notrun[0][5] == {'v': 'disabled', 'muted': False}


def test_receipt_rows_ignores_runs_outside_the_window_and_runs_without_the_gate(runs_on_disk):
    ran, notrun, reasons = DR.receipt_rows(ctx(kind='receipt', key='licence'), 'licence')
    assert (ran, [r[1] for r in notrun], reasons) == ([], ['run-aaaaaaaa'], {'no assets': 1})
    assert DR.receipt_rows(ctx(kind='receipt', key='nope'), 'nope') == ([], [], {})


def test_receipt_section_refuses_a_gate_no_run_filed_a_receipt_for(runs_on_disk):
    got = DR.receipt_section(ctx(kind='receipt', key='nope'))
    assert got == {'ok': False, 'error': "no receipts for gate 'nope' in this range"}


def test_vlm_rows_totals_the_counter_and_reports_the_largest_single_run(runs_on_disk):
    rows, total, biggest = DR.vlm_rows(ctx(kind='vlm', key='frames_checked'), 'frames_checked')
    assert [r[1] for r in rows] == ['run-aaaaaaaa', 'run-bbbbbbbb']
    assert (total, biggest) == (52, 40)
    assert rows[0][5] == '12'


def test_vlm_rows_of_an_unrecorded_counter_is_empty_and_the_section_refuses(runs_on_disk):
    assert DR.vlm_rows(ctx(kind='vlm', key='nope'), 'nope') == ([], 0, 0)
    got = DR.vlm_section(ctx(kind='vlm', key='nope'))
    assert got == {'ok': False, 'error': "no run recorded the counter 'nope' in this range"}


def test_day_section_refuses_a_bucket_outside_the_range():
    got = DR.day_section(ctx(kind='day', key='1999-01-01'))
    assert got == {'ok': False, 'error': '1999-01-01 is not a bucket in this range'}


# ── one run: the verdict side ────────────────────────────────────────────────


@pytest.mark.parametrize(
    ('verdict', 'label', 'tone'),
    [
        ({'blocked': True, 'ok': False}, 'Blocked', 'critical'),
        ({'blocked': True, 'ok': True}, 'Blocked', 'critical'),
        ({'ok': True}, 'Passed', 'good'),
        ({'ok': False}, 'Checks failed', 'warning'),
        ({}, 'Unrecorded', 'neutral'),
        ({'ok': None}, 'Unrecorded', 'neutral'),
    ],
)
def test_verdict_label_and_tone_agree_on_every_recorded_shape(verdict, label, tone):
    assert DR.verdict_label(verdict) == label
    assert DR.verdict_tone(verdict) == tone


def test_verdict_facts_puts_the_verdict_first_and_keeps_the_ledger_facts_last():
    rec = {
        'name': 'render',
        'ts': '2026-01-01T09:00:00',
        'dir': '/data/debug/a',
        'degradations': 2,
        'verdict': {'ok': False, 'blocked': True, 'failed_checks': 3, 'enforcement': True},
    }
    facts = DR.verdict_facts(rec, [{'label': 'Run id', 'value': 'x', 'sub': ''}])
    labels = [f['label'] for f in facts]
    assert labels[0] == 'Verdict' and labels[-1] == 'Run id'
    by = {f['label']: (f['value'], f['sub']) for f in facts}
    assert by['Verdict'] == ('Blocked', 'render')
    assert by['Degradations'] == ('2', '')
    assert by['Passed checks'] == ('—', '')  # an absent count is a dash, not 0
    assert by['Gate mode'] == ('enforcing', '')  # derived from `enforcement` when unnamed
    assert by['Finished'] == ('2026-01-01T09:00:00', '')  # falls back to the row's own ts


def test_verdict_named_table_keeps_the_blocking_warning_shadow_tag_order():
    tbl = DR.verdict_named_table(
        {
            'blocking_failures': ['hands'],
            'warning_failures': ['teeth'],
            'shadow_failed_checks': ['eyes'],
            'tags': ['t1', 't2'],
            'shadow_tags': ['s1'],
        }
    )
    assert [(r[0]['v'], r[1]) for r in tbl['rows']] == [
        ('Blocking failure', 'hands'),
        ('Warning failure', 'teeth'),
        ('Shadow failure', 'eyes'),
        ('Tag', 't1'),
        ('Tag', 't2'),
        ('Shadow tag', 's1'),
    ]
    assert tbl['rows'][0][0]['tone'] == 'critical'
    assert tbl['limited'] is None  # the table is never clipped


def test_verdict_named_table_of_a_bare_verdict_is_empty_with_its_own_note():
    tbl = DR.verdict_named_table({})
    assert tbl['rows'] == []
    assert tbl['empty'] == 'The verdict named no failing check or tag — only a count.'


def test_coverage_table_sorts_the_classes_and_counts_the_covered_ones():
    tbl = DR.coverage_table({'coverage': {'teeth': 'uncovered', 'hands': 'covered'}})
    assert [r[0] for r in tbl['rows']] == ['hands', 'teeth']
    assert tbl['rows'][0][1] == {'v': 'covered', 'tone': 'good'}
    assert tbl['rows'][1][1] == {'v': 'uncovered', 'tone': 'warning'}
    assert tbl['note'] == '1 of 2 defect classes were checked at all'


def test_coverage_table_is_absent_when_no_coverage_was_recorded():
    assert DR.coverage_table({}) is None
    assert DR.coverage_table({'coverage': {}}) is None
    assert DR.coverage_table({'coverage': 'not a dict'}) is None


def test_run_siblings_finds_every_verdict_under_one_run_id_newest_first():
    hist = {
        'k1': {'run_id': RID_REAL, 'ts': '2026-01-01T09:00:00'},
        'k2': {'run_id': RID_REAL, 'ts': '2026-01-01T10:10:10'},
        'k3': {'run_id': RID_REAL2, 'ts': '2026-01-02T09:00:00'},
    }
    assert [k for k, _ in DR.run_siblings(ctx(hist=hist), RID_REAL)] == ['k2', 'k1']
    assert DR.run_siblings(ctx(hist=hist), 'never-seen') == []


def test_siblings_table_links_every_row_except_the_one_being_viewed():
    siblings = [
        ('k2', {'ts': 'b', 'name': 'probe', 'verdict': {'ok': True}, 'degradations': 0, 'dir': '/d'}),
        ('k1', {'ts': 'a', 'name': '', 'verdict': {'ok': False, 'failed_checks': 3}, 'degradations': 2}),
    ]
    tbl = DR.siblings_table(siblings, 'k2')
    assert [r['detail'] for r in tbl['rows']] == [None, 'debug:k1']
    assert tbl['rows'][0]['cells'][2] == {'v': 'Passed', 'tone': 'good'}
    assert tbl['rows'][1]['cells'][1] == '—'
    assert tbl['rows'][1]['cells'][2] == {'v': 'Checks failed', 'tone': 'warning'}
    assert tbl['rows'][1]['cells'][3:6] == ['3', '2', {'v': '—', 'muted': True}]


def test_run_section_refuses_a_debug_token_that_left_the_history():
    got = DR.run_section(ctx(kind='debug', key='deadbeef'))
    assert got == {'ok': False, 'error': 'that verdict is no longer in debug_run_history.jsonl'}


# ── the orchestrator's dispatch table ────────────────────────────────────────


def test_every_token_kind_the_docstring_names_has_a_builder():
    assert set(D._SECTIONS) == {'tile', 'family', 'fallback', 'receipt', 'vlm', 'day', 'run', 'debug'}
    assert D._SECTIONS['run'] is D._SECTIONS['debug'] is DR.run_section


def test_quality_detail_refuses_an_unknown_token_kind(monkeypatch):
    monkeypatch.setattr(DC, '_test_run_ids', lambda: (set(), set(), []))
    monkeypatch.setattr(DC, '_ledger_rows', lambda: ([], []))
    monkeypatch.setattr(DC, '_debug_index', lambda: ({}, {}))
    assert D.quality_detail('nope:x', days=30, now=NOW) == {'ok': False, 'error': "unknown detail token 'nope:x'"}
    assert D.quality_detail('', days=30, now=NOW) == {'ok': False, 'error': "unknown detail token ''"}


@pytest.fixture
def ledger_on_disk(monkeypatch):
    """The fixture ledger behind `build_detail_context`, for the end-to-end dispatch tests."""
    monkeypatch.setattr(DC, '_test_run_ids', lambda: ({RID_TMP}, {'999999'}, []))
    monkeypatch.setattr(DC, '_ledger_rows', lambda: (list(GATES), list(FALLS)))
    monkeypatch.setattr(DC, '_debug_index', lambda: ({}, {RID_REAL: 'render / probe'}))


def test_quality_detail_dispatches_a_tile_token_to_the_tile_builder(ledger_on_disk):
    got = D.quality_detail('tile:pass_rate', days=30, now=NOW)
    assert (got['ok'], got['kind'], got['token']) == (True, 'tile', 'tile:pass_rate')
    assert got['title'] == 'Gate pass rate'
    assert {f['label']: f['value'] for f in got['facts']}['Pass rate'] == '50.0 %'
    assert got['tables'][0]['title'] == 'Attributed rows, newest first'


def test_quality_detail_dispatches_a_family_token_and_keeps_the_window_text(ledger_on_disk):
    got = D.quality_detail('family:licence', days=7, now=NOW)
    assert got['title'] == 'Gate family “licence”'
    assert (got['window_days'], got['window']) == (7, 'last 7 days')
    assert [t['title'] for t in got['tables']] == ['Gates in this family', 'Rows, newest first']


def test_quality_detail_dispatches_a_fallback_token_to_the_component_page(ledger_on_disk):
    got = D.quality_detail(f'fallback:{FB_KEY}', days=30, now=NOW)
    assert got['title'] == 'Fallback · lora:foo.safetensors'
    assert got['subtitle'] == 'foo → none'
    by = {f['label']: f['value'] for f in got['facts']}
    assert (by['In range'], by['All time'], by['Unattributed']) == ('3', '3', '1')
    assert by['Full component'] == FALLS[0][0]  # the clipped name links, the full one is a fact


# ── the section success paths ────────────────────────────────────────────────


def test_tile_fallbacks_separates_the_window_count_from_the_all_time_count():
    got = DT._tile_fallbacks(ctx(key='fallbacks'))
    assert got['title'] == 'Silent fallbacks'
    by = {f['label']: f['value'] for f in got['facts']}
    assert (by['In range'], by['All time'], by['Unattributed']) == ('3', '3', '1')
    assert got['tables'][0]['total'] == 3


def test_tile_test_rows_draws_the_gate_and_the_fallback_table_in_that_order():
    got = DT._tile_test_rows(ctx(key='test_rows'))
    assert got['title'] == 'Excluded test rows'
    assert {f['label']: f['value'] for f in got['facts']} == {'Gate rows': '2', 'Fallback rows': '1'}
    assert [t['title'] for t in got['tables']] == ['Gate rows excluded', 'Fallback rows excluded']


def test_tile_receipt_runs_lists_only_the_runs_that_filed_receipts_in_range(runs_on_disk):
    got = DT._tile_receipt_runs(ctx(key='receipt_runs'))
    assert {f['label']: f['value'] for f in got['facts']} == {'Runs': '3'}
    assert [r['cells'][1] for r in got['tables'][0]['rows']] == ['run-aaaaaaaa', 'run-bbbbbbbb', 'run-cccccccc']


def test_receipt_section_reports_the_ran_and_did_not_run_split(runs_on_disk):
    got = DR.receipt_section(ctx(kind='receipt', key='vlm'))
    assert got['title'] == 'Gate receipt · vlm'
    by = {f['label']: f['value'] for f in got['facts']}
    assert (by['Ran'], by['Did not run'], by['Runs seen']) == ('1', '2', '3')
    assert [t['title'] for t in got['tables']] == [
        'Why it did not run',
        'Runs where it did not run',
        'Runs where it ran',
        'Outcomes this gate recorded in the ledger',
    ]


def test_vlm_section_names_the_counter_in_its_title_and_its_last_column(runs_on_disk):
    got = DR.vlm_section(ctx(kind='vlm', key='frames_checked'))
    assert got['title'] == 'VLM counter · frames checked'
    assert {f['label']: f['value'] for f in got['facts']} == {
        'Total': '52',
        'Runs': '2',
        'Largest single run': '40',
    }
    assert got['tables'][0]['columns'][-1] == {'t': 'frames checked', 'r': True}


def test_day_section_counts_the_bucket_the_newest_rows_fall_in():
    from zyg_dashboard.metrics_hub.runs import _bucket_of, _bucketing

    c = ctx(kind='day')
    _keys, weekly = _bucketing(c.since, c.now, min(g[5] for g in GATES))
    bucket = _bucket_of(NOW - 1 * DAY, weekly)
    got = DR.day_section(ctx(kind='day', key=bucket))
    assert got['ok'] is True
    assert got['title'].endswith(bucket)
    assert {f['label']: f['value'] for f in got['facts']}['Fallbacks'] == '1'


def test_run_section_of_a_debug_token_puts_the_verdict_before_the_ledger_facts():
    hist = {
        'k1': {
            'run_id': RID_REAL,
            'ts': '2026-01-01T09:00:00',
            'name': 'render',
            'dir': '/data/debug/a',
            'degradations': 1,
            'verdict': {
                'ok': False,
                'failed_checks': 2,
                'blocking_failures': ['hands'],
                'coverage': {'hands': 'covered'},
            },
        }
    }
    got = DR.run_section(ctx(kind='debug', key='k1', hist=hist))
    assert got['title'] == 'Run · render'
    assert got['subtitle'] == RID_REAL
    assert got['window'] == 'all time — a run is one event, not a window'
    labels = [f['label'] for f in got['facts']]
    assert labels[0] == 'Verdict'
    assert labels[-4:] == ['Run id', 'Attribution', 'Ledger gate rows', 'Ledger fallbacks']
    assert [t['title'] for t in got['tables']] == [
        'What the verdict named',
        'Defect-class coverage',
        'Gate rows this run recorded',
        'Fallbacks this run recorded',
    ]


def test_run_section_of_a_run_token_says_when_the_id_is_not_in_the_history():
    got = DR.run_section(ctx(kind='run', key=RID_REAL))
    by = {f['label']: f['value'] for f in got['facts']}
    assert by['Run id'] == RID_REAL
    assert by['Attribution'] == 'real'
    assert by['Ledger gate rows'] == '3'  # unwindowed: the 200-day-old row counts too
    assert by['Debug run'] == 'not in debug_run_history.jsonl'
    assert got['title'] == 'Run · render / probe'  # the name the debug index knows it by
