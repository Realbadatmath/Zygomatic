# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Helpers of the Pre-emptive bank Test Data card (`preempt_test_record`). 2026-10-09.

`build_record` was 339 lines that measured the bank, drew three charts, built the table and
the facts and assembled the card in one breath, so none of it could be exercised without the
bank on disk. The split gives it `_targets`, `_measure`, `_chart_progress`, `_chart_cost`,
`_chart_meter`, `_entry_table`, `_facts` and `_verdict`; these tests pin the behaviour each
of them inherited:

the targets fall back to 100/100/90 when the settings refuse; a built entry is annotated with
the meter movement across its recording and a window with no sample spanning it stays None;
both progress lines are carried forward onto one shared axis; the cost chart drops its median
ref when there is no median; the meter chart starts an hour before the first recording and
labels the ceiling; the table is newest first with em-dashes for what is missing; the facts say
so instead of guessing; and the verdict switches when the target is reached.
"""

from datetime import datetime

import pytest

from zyg_dashboard import preempt_test_record as ptr

T0 = datetime.fromisoformat('2026-09-23T10:00:00').timestamp()  # local, exactly as _ts reads it


def _entry(
    eid,
    topic,
    status='ready',
    created='2026-09-23T10:00:00',
    built='2026-09-23T10:30:00',
    turns=11,
    tokens=78000,
    build_s=1800,
    replay=None,
    error='',
):
    return {
        'id': eid,
        'topic': topic,
        'status': status,
        'created_at': created,
        'built_at': built,
        'turns': turns,
        'output_tokens': tokens,
        'build_s': build_s,
        'replay': replay,
        'error': error,
    }


def _sample(ts, week, hour):
    return {'ts': ts, 'seven_day': {'pct': week}, 'five_hour': {'pct': hour}}


def _bank(entries, songs=(), counts=None, songs_counts=None, totals=None, state=None):
    return {
        'entries': list(entries),
        'songs': list(songs),
        'counts': counts or {'built': 2, 'ready': 2, 'claimed': 0, 'consumed': 0},
        'songs_counts': songs_counts or {'built': 1},
        'totals': totals
        or {
            'replay_hits': 9,
            'replay_misses': 1,
            'replay_live': 4,
            'turns': 22,
            'output_tokens': 156000,
            'tokens_saved': 70000,
        },
        'state': state or {'enabled': True, 'paused': False},
    }


def _measured(monkeypatch, bank, samples=(), targets=(100, 100, 90.0)):
    """Run `_measure` with the settings and the quota samples pinned, never reading the disk."""
    monkeypatch.setattr(ptr, '_targets', lambda: targets)
    monkeypatch.setattr(ptr, '_samples', lambda: list(samples))
    return ptr._measure(bank)


class _Settings:
    def __init__(self, values):
        self.values = values

    def get(self, section, key):
        return self.values[(section, key)]


class _Broken:
    def get(self, section, key):
        raise RuntimeError('settings unreadable')


def _pin_settings(monkeypatch, stub):
    import sys

    import zyg_dashboard

    monkeypatch.setattr(zyg_dashboard, 'approval_queue_settings', stub, raising=False)
    monkeypatch.setitem(sys.modules, 'zyg_dashboard.approval_queue_settings', stub)


def test_targets_read_the_queue_settings(monkeypatch):
    _pin_settings(
        monkeypatch,
        _Settings(
            {
                ('preempt', 'documentary_target'): '40',
                ('preempt', 'songs_target'): '7',
                ('preempt', 'quota_ceiling_pct'): '85.5',
            }
        ),
    )
    assert ptr._targets() == (40, 7, 85.5)


def test_targets_fall_back_to_the_defaults_when_the_settings_refuse(monkeypatch):
    _pin_settings(monkeypatch, _Broken())
    assert ptr._targets() == (100, 100, 90.0)


def test_measure_annotates_the_meter_cost_and_leaves_an_unspanned_window_none(monkeypatch):
    spanned = _entry('a', 'Alpha', created='2026-09-23T10:00:00', built='2026-09-23T10:30:00')
    unspanned = _entry('b', 'Beta', created='2026-09-24T10:00:00', built='2026-09-24T10:30:00')
    samples = [_sample(T0 - 60, 10, 2), _sample(T0 + 1800 + 60, 13, 5)]
    m = _measured(monkeypatch, _bank([spanned, unspanned]), samples)

    assert (spanned['week_pct'], spanned['hour_pct']) == (3, 3)
    assert (unspanned['week_pct'], unspanned['hour_pct']) == (None, None)
    assert [r['id'] for r in m.built] == ['a', 'b']  # sorted by built_at
    assert (m.med_week, m.med_hour) == (3, 3)  # the None entry is dropped, not counted as zero
    assert m.med_tok == 78000
    assert m.remaining == 98  # target 100 minus the 2 the counts report built


def test_measure_reports_running_while_either_target_is_short(monkeypatch):
    m = _measured(monkeypatch, _bank([_entry('a', 'Alpha')]))
    assert m.running is True
    assert m.status == 'running'
    assert m.hit_rate == 90.0  # 9 of 10 banked turns


def test_measure_reports_mixed_once_the_targets_are_met_and_an_entry_failed(monkeypatch):
    rows = [_entry('a', 'Alpha'), _entry('z', 'Zeta', status='failed', error='boom')]
    bank = _bank(
        rows,
        counts={'built': 100, 'ready': 100, 'claimed': 0, 'consumed': 0},
        songs_counts={'built': 100},
    )
    m = _measured(monkeypatch, bank)
    assert m.running is False
    assert m.status == 'mixed'
    assert [r['id'] for r in m.failed] == ['z']
    assert m.remaining == 0


def test_chart_progress_carries_both_lines_forward_on_one_shared_axis(monkeypatch):
    rows = [
        _entry('a', 'Alpha', created='2026-09-23T09:00:00', built='2026-09-23T10:00:00'),
        _entry('b', 'Beta', created='2026-09-23T11:00:00', built='2026-09-23T12:00:00'),
    ]
    songs = [{'created_at': '2026-09-23T11:00:00'}]
    chart = ptr._chart_progress(_measured(monkeypatch, _bank(rows, songs)))

    assert chart['x']['values'] == ['2026-09-23T10:00:00', '2026-09-23T11:00:00', '2026-09-23T12:00:00']
    docs, song_line = chart['series']
    assert docs['values'] == [1, 1, 2]
    assert song_line['values'] == [0, 1, 1]
    assert chart['refs'][0]['value'] == 100


def test_chart_cost_drops_its_median_ref_when_nothing_is_banked(monkeypatch):
    empty = ptr._chart_cost(_measured(monkeypatch, _bank([])))
    assert empty['refs'] == []
    assert empty['x']['values'] == []

    one = ptr._chart_cost(_measured(monkeypatch, _bank([_entry('a', 'Alpha', tokens=1234)])))
    assert one['x']['values'] == [1]
    assert one['series'][0]['values'] == [1234]
    assert one['refs'][0] == {'kind': 'baseline', 'value': 1234, 'label': 'median 1,234 output tokens'}


def test_chart_meter_starts_an_hour_before_the_first_recording(monkeypatch):
    samples = [_sample(T0 - 7200, 1, 1), _sample(T0 - 60, 10, 2), _sample(T0 + 3600, 13, 5)]
    m = _measured(monkeypatch, _bank([_entry('a', 'Alpha')]), samples, targets=(100, 100, 85.0))
    chart = ptr._chart_meter(m)

    assert chart['series'][0]['values'] == [10, 13]  # the two-hours-earlier sample is cut
    assert chart['series'][1]['values'] == [2, 5]
    assert len(chart['x']['values']) == 2
    assert chart['refs'][0] == {'kind': 'limit', 'value': 85.0, 'label': 'builder holds at 85 %'}


def test_entry_table_is_newest_first_with_em_dashes_for_what_is_missing(monkeypatch):
    rows = [
        _entry('a', 'Alpha', created='2026-09-23T09:00:00', replay={'hits': 9, 'live': 4}),
        _entry('b', '', created='2026-09-23T11:00:00', build_s=None, status='failed', error='boom'),
    ]
    samples = [_sample(T0 - 60, 10, 2), _sample(T0 + 1800 + 60, 13, 5)]
    table = ptr._entry_table(_measured(monkeypatch, _bank(rows), samples))

    newest, oldest = table['rows']
    assert newest[0] == 'b'  # no topic falls back to the id
    assert newest[4] == '—' and newest[5] == '—' and newest[6] == '—'
    assert newest[7] == 'boom'
    assert oldest[0] == 'Alpha'
    assert oldest[3] == '78,000'
    assert oldest[4] == '30 min'
    assert oldest[6] == '9 replayed / 4 live'
    assert len(table['columns']) == 8


def test_facts_say_so_instead_of_guessing_an_unmeasured_quota(monkeypatch):
    m = _measured(monkeypatch, _bank([_entry('a', 'Alpha')]))  # no samples: no meter cost
    by_label = {f['label']: f for f in ptr._facts(m)}

    assert by_label['Claude week burned per brain']['value'] is None
    assert by_label['Claude week burned per brain']['sub'] == 'no meter sample spans a recording yet'
    assert by_label['Quota still needed for the target']['value'] is None
    assert by_label['Documentary brains banked']['value'] == '2 of 100'
    assert by_label['Median wall time per brain']['value'] == 30.0
    assert by_label['Replay hit rate']['value'] == 90.0


def test_verdict_switches_when_the_target_is_reached(monkeypatch):
    running = _measured(monkeypatch, _bank([_entry('a', 'Alpha')]))
    assert ptr._verdict(running).startswith('Running. 2 of 100 brains and 1 of 100 briefs are banked')

    done = _measured(
        monkeypatch,
        _bank(
            [_entry('a', 'Alpha')],
            counts={'built': 100, 'ready': 100, 'claimed': 0, 'consumed': 0},
            songs_counts={'built': 100},
        ),
    )
    assert ptr._verdict(done) == 'Target reached: 100 brains and 100 briefs banked.'


@pytest.mark.parametrize(
    ('values', 'expected'),
    [([], None), ([3], 3), ([3, 1], 2.0), ([5, 1, 3], 3), ([None, 4], 4)],
)
def test_median_drops_the_holes(values, expected):
    assert ptr._median(values) == expected
