# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Unit tests for the stages `section_analytics` was split into.

Every helper here used to be a closure or an inline block of the 381-line
`section_analytics`, so these are the first tests that exercise the logic in isolation:
the three series callables the card builders take, the per-kind unit-time table, the
Approval-Queue backlog card, the two cards that are allowed to fail, and the envelope.
"""

import logging
from types import SimpleNamespace

from zyg_dashboard.analytics_hub import section_helpers as sh
from zyg_dashboard.analytics_hub.helpers import _daykey

DAY = 86400.0
T0 = 1760000000.0  # a fixed clock: the day keys below are derived from it, never hardcoded
K0 = _daykey(T0)
K1 = _daykey(T0 + DAY)
K2 = _daykey(T0 + 2 * DAY)


def test_daily_map_counts_rows_per_day_by_default():
    rows = [{'t': T0}, {'t': T0 + 60}, {'t': T0 + DAY}]
    assert sh._daily_map(rows) == {K0: 2.0, K1: 1.0}


def test_daily_map_sums_a_value_and_reads_the_named_time_field():
    rows = [{'t': T0, 'usd': 1.5}, {'t': T0, 'usd': 0.25}]
    assert sh._daily_map(rows, lambda r: r['usd']) == {K0: 1.75}
    assert sh._daily_map([{'finished': T0 + DAY}], key='finished') == {K1: 1.0}


def test_daily_map_of_nothing_is_an_empty_map():
    assert sh._daily_map([]) == {}


def test_trend_series_reads_a_daily_map_in_key_order_and_zero_fills_gaps():
    assert sh._trend_series({K0: 3.0, K2: 1.0}, [K0, K1, K2]) == [3.0, 0.0, 1.0]


def test_window_sum_is_inclusive_on_both_ends():
    m = {K0: 1.0, K1: 2.0, K2: 4.0}
    assert sh._window_sum(m, K0, K2) == 7.0
    assert sh._window_sum(m, K1, K1) == 2.0
    assert sh._window_sum(m, K2, K0) == 0.0


def _run(kind, t, duration_s, status='completed', basis='measured'):
    return {
        'kind': kind,
        't': t,
        'duration_s': duration_s,
        'status': status,
        'duration_basis': basis,
        'is_content': True,
    }


def test_unit_times_takes_the_recent_median_and_counts_the_basis():
    runs = [
        _run('crime', T0, 100.0),
        _run('crime', T0, 300.0),
        _run('crime', T0, 200.0, basis='estimated'),
        _run('crime', T0, None),  # completed but untimed: counted, never in the median
    ]
    unit_s, rows = sh.unit_times(runs, T0 - 90 * DAY)
    assert unit_s == {'crime': 200.0}
    (row,) = rows
    assert (row['kind'], row['label']) == ('crime', 'Crime documentary')
    assert (row['timed'], row['recent_n'], row['untimed_completed']) == (3, 3, 1)
    assert row['p50_recent_s'] == 200.0
    assert row['p50_all_s'] == 200.0
    assert row['basis'] == {'measured': 2, 'estimated': 1}
    assert row['is_content'] is True


def test_unit_times_falls_back_to_all_time_when_nothing_is_recent():
    runs = [_run('crime', T0 - 400 * DAY, 50.0), _run('crime', T0 - 300 * DAY, 150.0)]
    unit_s, rows = sh.unit_times(runs, T0 - 90 * DAY)
    assert unit_s == {'crime': 100.0}
    assert rows[0]['recent_n'] == 2


def test_unit_times_skips_kinds_with_no_timed_completed_run():
    runs = [_run('crime', T0, None), _run('manga', T0, 10.0, status='failed')]
    assert sh.unit_times(runs, T0 - 90 * DAY) == ({}, [])


def test_unit_times_reports_assets_as_not_content():
    unit_s, rows = sh.unit_times([_run('character', T0, 20.0)], T0 - 90 * DAY)
    assert unit_s == {'character': 20.0}
    assert rows[0]['is_content'] is False


def _toggle(kind, label, scheduled, running, unit_s, enabled=True, per_day=2):
    return {
        'kind': kind,
        'label': label,
        'enabled': enabled,
        'per_day': per_day,
        'hours_per_day': 1.0,
        'unit_s': unit_s,
        'batch': {'scheduled': scheduled, 'in_production': running, 'done': 4, 'failed': 1},
    }


def _backlog_ctx():
    return SimpleNamespace(
        bucket='day',
        keys=[K0, K1],
        weekly=False,
        daily_map=sh._daily_map,
        completed=[_run('crime', T0, 10.0), _run('crime', T0 + DAY, 10.0), _run('manga', T0, 10.0)],
        toggles=[_toggle('crime', 'Crime documentary', 2, 1, 3600.0), _toggle('manga', 'Manga', 0, 0, None)],
    )


def test_backlog_card_prices_the_queue_at_the_recent_median():
    card = sh.backlog_card(_backlog_ctx())
    assert card['id'] == 'backlog'
    assert card['lane'] == 'production'
    assert card['headline']['value'] == 3  # 2 scheduled + 1 in production, the other toggle is empty
    assert '3.0 h' in card['headline']['sub']  # 3 items x 3600 s; the toggle with no unit time adds nothing


def test_backlog_card_stacks_one_series_per_toggle_over_the_bucket_keys():
    card = sh.backlog_card(_backlog_ctx())
    assert card['chart']['stacked'] is True
    assert [s['id'] for s in card['chart']['series']] == ['crime', 'manga']
    assert card['chart']['series'][0]['values'] == [1, 1]
    assert card['chart']['series'][1]['values'] == [1, 0]


def test_backlog_card_table_carries_the_batch_counters_and_queued_hours():
    rows = sh.backlog_card(_backlog_ctx())['table']['rows']
    assert rows[0][:6] == ['Crime documentary', 'ON', 2, 1, 4, 1]
    assert rows[0][7] == {'v': 3.0, 'fmt': 'hours'}
    assert rows[1][7] == {'v': 0.0, 'fmt': 'hours'}  # no unit time: no hours, not a crash


def test_backlog_card_reports_a_disabled_toggle_as_off():
    ctx = _backlog_ctx()
    ctx.toggles[1]['enabled'] = False
    card = sh.backlog_card(ctx)
    assert [f['value'] for f in card['facts']['current']] == ['ON', 'off']
    assert card['facts']['historical'][0]['value'] == 2  # crime completions, all time


def _optional_ctx():
    return SimpleNamespace(
        now=T0,
        days=30,
        since=None,
        keys=[K0],
        weekly=False,
        bucket='day',
        trend_keys=[K0],
        fkeys=[K1],
        d7=K0,
        d14=K0,
        d8=K0,
        today=K0,
    )


def test_optional_cards_survive_a_card_that_raises(monkeypatch, caplog):
    def boom(*_a):
        raise RuntimeError('ledger unreadable')

    monkeypatch.setattr(sh, 'arch_studio_card', boom)
    monkeypatch.setattr(sh, 'preempt_bank_card', boom)
    ctx = _optional_ctx()
    with caplog.at_level(logging.INFO, logger=sh.__name__):
        sh.add_optional_cards(ctx)
    assert (ctx.card_arch, ctx.card_preempt) == (None, None)
    out = caplog.text
    assert 'arch_studio card failed: ledger unreadable' in out
    assert 'preempt_bank card failed: ledger unreadable' in out


def test_optional_cards_keep_what_was_built(monkeypatch):
    monkeypatch.setattr(sh, 'arch_studio_card', lambda *a: {'id': 'arch'})
    monkeypatch.setattr(sh, 'preempt_bank_card', lambda *a: {'id': 'preempt'})
    ctx = _optional_ctx()
    sh.add_optional_cards(ctx)
    assert (ctx.card_arch['id'], ctx.card_preempt['id']) == ('arch', 'preempt')


def _envelope_ctx(**over):
    ctx = SimpleNamespace(
        now=T0,
        cfg={'active_hours_per_day': 8},
        toggles=[],
        scenario_per_day=3,
        scenario_hours=2.345,
        scenario_missing=['Manga'],
        scen_util=41.27,
        bucket='day',
        keys=[K0],
        fkeys=[K1],
        runs=[1, 2, 3],
        content=[1, 2],
        completed=[1],
        meta={'excluded_test_runs': 7, 'excluded_synthesized': 2},
        llm={'rows': [1, 2, 3, 4]},
        sys_days=[K0, K1],
        tel_days=[K0],
        card_backlog={'id': 'backlog'},
        card_arch=None,
        card_preempt=None,
    )
    for name in ('volume', 'times', 'cost', 'income', 'mix', 'sub', 'capacity', 'system', 'energy', 'yield'):
        setattr(ctx, f'card_{name}', {'id': name})
    for k, val in over.items():
        setattr(ctx, k, val)
    return ctx


def test_envelope_orders_the_cards_and_drops_the_optional_ones_when_absent():
    env = sh.envelope(_envelope_ctx())
    assert [c['id'] for c in env['cards']] == [
        'volume',
        'times',
        'backlog',
        'cost',
        'income',
        'mix',
        'sub',
        'capacity',
        'system',
        'energy',
        'yield',
    ]
    assert [lane['id'] for lane in env['lanes']] == ['production', 'money', 'capacity', 'quality']


def test_envelope_inserts_preempt_before_arch_when_both_are_built():
    env = sh.envelope(_envelope_ctx(card_preempt={'id': 'preempt'}, card_arch={'id': 'arch'}))
    assert [c['id'] for c in env['cards']][:5] == ['volume', 'times', 'backlog', 'preempt', 'arch']


def test_envelope_rounds_the_scenario_and_counts_the_coverage():
    env = sh.envelope(_envelope_ctx())
    assert env['scenario'] == {
        'per_day': 3,
        'hours_per_day': 2.35,
        'missing_unit_times': ['Manga'],
        'utilisation_pct': 41.3,
    }
    assert env['coverage'] == {
        'runs': 3,
        'content_runs': 2,
        'completed_content': 1,
        'excluded_test_runs': 7,
        'excluded_synthesized': 2,
        'llm_rows': 4,
        'sysusage_days': 2,
        'telemetry_days': 1,
    }


def test_envelope_reports_no_utilisation_when_capacity_could_not_measure_it():
    assert sh.envelope(_envelope_ctx(scen_util=None))['scenario']['utilisation_pct'] is None


def test_envelope_hands_out_fresh_lane_dicts():
    first = sh.envelope(_envelope_ctx())['lanes']
    first[0]['label'] = 'mutated'
    assert sh.envelope(_envelope_ctx())['lanes'][0]['label'] == 'Production'
