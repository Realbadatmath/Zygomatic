# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Figures of the Pre-emptive bank card (`analytics_hub.preempt_bank_figures`). 2026-10-09.

Pinned: a malformed timestamp is dropped, not raised; the per-day series sums the
rows a selector accepts and falls back from `built_at` to `created_at`; waves
break on a gap longer than 10 minutes; the meter cost is the window's movement
over a wave, times the bank's share, divided by the brains the wave banked, and
a window that RESET is never differenced; the table is the newest 90 days; and
the card still answers with every block the dashboard reads.

`ts_of` and the per-day map were closures inside `preempt_bank_card` until the
split, so this is the first time they are exercised in isolation.
"""

import datetime as _dt

import pytest

from zyg_dashboard.analytics_hub import preempt_bank_figures as pf

DAY = 86400.0
T0 = _dt.datetime.fromisoformat('2026-09-23T10:00:00').timestamp()  # local time, exactly as ts_of reads it


def _entry(created, built=None, status='ready', tokens=100, turns=3, build_s=600):
    return {
        'status': status,
        'created_at': created,
        'built_at': built,
        'output_tokens': tokens,
        'turns': turns,
        'build_s': build_s,
    }


def _iso(ts):
    import datetime as _dt

    return _dt.datetime.fromtimestamp(ts).isoformat()


def test_a_malformed_timestamp_is_dropped_not_raised():
    assert pf.ts_of('2026-09-23T10:00:00') == pytest.approx(T0)
    assert pf.ts_of(None) is None
    assert pf.ts_of('not a date') is None
    assert pf.ts_of('') is None


def test_day_totals_sums_only_the_selected_rows():
    rows = [
        _entry(_iso(T0), _iso(T0), status='ready', tokens=10),
        _entry(_iso(T0), _iso(T0), status='failed', tokens=20),
        _entry(_iso(T0 + DAY), _iso(T0 + DAY), status='consumed', tokens=30),
    ]
    built = pf.day_totals(rows, lambda r: r['status'] in ('ready', 'claimed', 'consumed'))
    assert sorted(built.values()) == [1.0, 1.0]
    assert len(built) == 2
    tokens = pf.day_totals(rows, lambda r: True, lambda r: r['output_tokens'])
    assert sum(tokens.values()) == 60


def test_day_totals_falls_back_to_created_at_and_drops_the_undatable():
    rows = [_entry(_iso(T0), None), _entry(None, None)]
    out = pf.day_totals(rows, lambda r: True)
    assert list(out.values()) == [1.0]  # the row with no timestamp at all is dropped


def test_waves_break_on_a_gap_longer_than_ten_minutes():
    built = [
        _entry(_iso(T0), _iso(T0 + 300)),
        _entry(_iso(T0 + 400), _iso(T0 + 700)),  # 100 s after the previous build — same wave
        _entry(_iso(T0 + 2000), _iso(T0 + 2300)),  # 1300 s later — a new wave
    ]
    waves = pf.split_waves(built)
    assert [len(w) for w in waves] == [2, 1]


def test_waves_are_ordered_and_the_undatable_is_dropped():
    late, early = _entry(_iso(T0 + 5000), _iso(T0 + 5100)), _entry(_iso(T0), _iso(T0 + 100))
    waves = pf.split_waves([late, early, _entry(None, None)])
    assert [w[0]['created_at'] for w in waves] == [early['created_at'], late['created_at']]


def _samples(before_pct, after_pct, t_before, t_after):
    return [
        {'ts': t_before, 'seven_day': {'pct': before_pct}, 'five_hour': {'pct': before_pct}},
        {'ts': t_after, 'seven_day': {'pct': after_pct}, 'five_hour': {'pct': after_pct}},
    ]


def test_meter_cost_divides_the_window_movement_by_the_brains_of_the_wave(monkeypatch):
    monkeypatch.setattr(pf, 'wave_share', lambda t0, t1: 1.0)
    built = [_entry(_iso(T0), _iso(T0 + 300)), _entry(_iso(T0 + 400), _iso(T0 + 700))]
    week_pct, hour_pct, week_n = pf.meter_cost(built, _samples(40.0, 46.0, T0 - 10, T0 + 800))
    assert week_pct == 3.0  # (46 - 40) / 2 brains
    assert hour_pct == 3.0
    assert week_n == 2


def test_meter_cost_charges_only_the_banks_share(monkeypatch):
    monkeypatch.setattr(pf, 'wave_share', lambda t0, t1: 0.25)
    built = [_entry(_iso(T0), _iso(T0 + 300))]
    week_pct, _hour, week_n = pf.meter_cost(built, _samples(40.0, 48.0, T0 - 10, T0 + 400))
    assert week_pct == 2.0  # 8 % * 0.25, one brain
    assert week_n == 1


def test_a_window_that_reset_is_never_differenced(monkeypatch):
    monkeypatch.setattr(pf, 'wave_share', lambda t0, t1: 1.0)
    built = [_entry(_iso(T0), _iso(T0 + 300))]
    week_pct, hour_pct, week_n = pf.meter_cost(built, _samples(90.0, 3.0, T0 - 10, T0 + 400))
    assert week_pct is None and hour_pct is None
    assert week_n == 1  # the recording is still counted, it just has no measurable cost


def test_meter_cost_without_samples_is_unknown():
    assert pf.meter_cost([_entry(_iso(T0), _iso(T0 + 300))], []) == (None, None, 0)
    assert pf.meter_cost([], []) == (None, None, 0)


def test_the_table_is_the_newest_ninety_days_first():
    built = {f'2026-01-{d:02d}': 1.0 for d in range(1, 32)}
    rows = pf.per_day_rows(built, {'2026-02-01': 2.0}, {'2026-01-01': 500.0}, {})
    assert rows[0][0] == '2026-02-01'
    assert rows[0][1:] == [0, 2, 0, 0]
    assert rows[-1] == ['2026-01-01', 1, 0, 500, 0]
    assert len(rows) == 32
    wide = pf.per_day_rows({f'2026-{m:02d}-{d:02d}': 1.0 for m in (1, 2, 3, 4) for d in range(1, 29)}, {}, {}, {})
    assert len(wide) == 90


def test_the_card_answers_with_every_block_the_dashboard_reads(monkeypatch):
    bank = {
        'entries': [_entry(_iso(T0), _iso(T0 + 300), status='ready')],
        'totals': {
            'turns': 3,
            'output_tokens': 100,
            'cache_write_tokens': 1,
            'cache_read_tokens': 2,
            'replay_hits': 0,
            'replay_misses': 0,
            'replay_live': 0,
            'tokens_saved': 0,
        },
        'counts': {'built': 1, 'ready': 1, 'claimed': 0, 'consumed': 0},
        'songs_counts': {'built': 0},
        'songs': [],
        'state': {'enabled': True, 'documentary': {'note': ''}},
    }
    monkeypatch.setattr(pf, 'quota_samples', lambda now: ([], None))
    f = pf.bank_figures(bank, 100, 100, [], 0)
    assert f.remaining == 99
    assert f.on is True
    assert f.pct_done == 1.0
    assert pf.headline_block(f)['value'] == 1
    assert 'builder ON' in pf.headline_block(f)['label']
    assert pf.delta_block(f, 'x', 'a', 'b')['good_when'] == 'up'
    chart = pf.chart_block(f, [], False, 'day', [])
    assert [s['id'] for s in chart['series']] == ['built', 'failed', 'songs']
    facts = pf.facts_block(f)
    assert set(facts) == {'historical', 'current', 'future'}
    assert facts['historical'][4]['sub'] == 'no meter sample spans a recording yet'
    assert facts['future'][-1]['value'] == 1  # the ready entries, always last
    notes = pf.notes_block(f)
    assert notes[0].startswith('Replay so far: 0 of 0')
    assert 'no measured saving on this card' in notes[1]
