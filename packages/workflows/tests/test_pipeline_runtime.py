#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""
Pipeline runtime — the Live Tail "⏱ Pipeline Runtime" clock (2026-08-26).

    .venv-test/bin/python -m pytest tests/test_pipeline_runtime.py -q

The clock used to be ``Date.now() - pipeline.started`` in the browser, frozen
only on four hard-coded terminal statuses, so every other resting state
accumulated forever. What is asserted here is exactly what regressed:

* a job parked at a review gate freezes at the moment it parked;
* a job whose worker died freezes at its last recorded activity;
* the dead gap between a crash and a ``resumed`` is not runtime;
* nested/overlapping stage spans are merged, never summed twice;
* a healthy completed run still equals its wall clock;
* a stale snapshot that merely *claims* ``running`` does not tick;
* an explicit ``running=True`` from a live-worker check always ticks.

The reference case is the real 2026-08-25 creature run (d0e44ab002ad): it read
20h11m and climbing in the panel for 4h00m20s of actual work.
"""

import os
import sys
from datetime import datetime, timedelta, timezone

import pytest

_CREWS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _CREWS)

from zyg_workflows.pipeline_runtime import (  # noqa: E402
    BRIDGE_GAP_S,
    card_times,
    compute_runtime,
    format_runtime,
    parse_ts,
    pause_log_line,
    record_pause,
)

TZ = timezone(timedelta(hours=2))  # Europe/Amsterdam, summer


def T(hh, mm, ss=0, day=25):
    return datetime(2026, 8, day, hh, mm, ss, tzinfo=TZ).isoformat(timespec='milliseconds')


def stage(name, start, end=None, status='completed'):
    return {'name': name, 'status': status, 'started_at': start, 'ended_at': end}


NOW = datetime(2026, 8, 26, 11, 35, tzinfo=TZ)  # ~20h after the run started


# ── the reference defect ─────────────────────────────────────────────────────
CREATURE_PARKED = {
    'status': 'awaiting_review',
    'started': '2026-08-25T15:23:16.281+02:00',
    'review_requested': '2026-08-25T23:49:52.827+02:00',
    'resumed': '2026-08-25T22:33:57.089+02:00',
    'worker': {'started': '2026-08-25T22:33:57.089+02:00', 'ended': '2026-08-25T23:49:52.827+02:00'},
    'stage_timeline': [
        stage('Creature Brief', '2026-08-25T15:23:16.296+02:00', '2026-08-25T15:23:24.200+02:00'),
        stage('Reference Anchor', '2026-08-25T15:23:24.202+02:00', '2026-08-25T15:41:39.435+02:00'),
        stage('Multi-Angle Sheet', '2026-08-25T15:41:39.436+02:00', '2026-08-25T16:37:17.740+02:00'),
        stage('Sheet QC', '2026-08-25T16:37:17.740+02:00', '2026-08-25T18:07:40.797+02:00'),
        stage('Sheet Review', '2026-08-25T18:07:40.798+02:00', None, status='running'),
    ],
}


def test_parked_run_freezes_and_excludes_the_crash_gap():
    r = compute_runtime(CREATURE_PARKED, now=NOW)
    assert r['runtime_running'] is False
    # 15:23:16 → 18:07:40 (2h44m24s) plus the resumed worker 22:33:57 → 23:49:52
    assert r['runtime_seconds'] == pytest.approx(4 * 3600 + 20, abs=2)
    assert r['runtime_as_of'].startswith('2026-08-25T23:49:52')
    # The wall span is reported separately, and it is NOT the runtime.
    assert r['runtime_wall_seconds'] == pytest.approx(8 * 3600 + 26 * 60 + 36, abs=2)


def test_parked_run_does_not_accumulate_between_polls():
    """The regression itself: the number must be identical an hour later."""
    a = compute_runtime(CREATURE_PARKED, now=NOW)
    b = compute_runtime(CREATURE_PARKED, now=NOW + timedelta(hours=1))
    assert a['runtime_seconds'] == b['runtime_seconds']


def test_live_run_ticks():
    job = dict(CREATURE_PARKED, status='running')
    job.pop('review_requested')
    job['worker'] = {'started': '2026-08-25T22:33:57.089+02:00', 'ended': None}
    a = compute_runtime(job, running=True, now=NOW)
    b = compute_runtime(job, running=True, now=NOW + timedelta(minutes=10))
    assert b['runtime_seconds'] - a['runtime_seconds'] == pytest.approx(600, abs=1)


# ── the other resting states the old terminal list missed ────────────────────
@pytest.mark.parametrize('status', ['stopped', 'rejected', 'cancelled', 'awaiting_review', 'paused', 'archived'])
def test_every_resting_status_freezes(status):
    job = {'status': status, 'started': T(10, 0), 'stage_timeline': [stage('Stage 1', T(10, 0), T(10, 30))]}
    a = compute_runtime(job, now=NOW)
    b = compute_runtime(job, now=NOW + timedelta(hours=3))
    assert a['runtime_seconds'] == b['runtime_seconds'] == pytest.approx(1800, abs=1)


def test_terminal_run_equals_its_wall_clock():
    """A healthy run must not lose time to the gap-exclusion machinery."""
    job = {
        'status': 'completed',
        'started': T(21, 51, 16),
        'ended': T(22, 33, 55),
        'stage_timeline': [
            stage('Stage 1', T(21, 51, 16), T(21, 52, 49)),
            stage('Stage 3', T(21, 52, 49), T(21, 53, 16)),
            stage('Stage 3.1', T(21, 53, 27), T(22, 10, 0)),  # 11s bookkeeping hole
            stage('Stage 6', T(22, 10, 0), T(22, 33, 55)),
            stage('Color Grade', T(22, 27, 59), T(22, 33, 55)),  # nested inside Stage 6
        ],
    }
    r = compute_runtime(job, now=NOW)
    wall = 42 * 60 + 39
    assert r['runtime_seconds'] == pytest.approx(wall, abs=1)
    assert r['runtime_seconds'] <= r['runtime_wall_seconds']


def test_nested_stages_are_not_double_counted():
    job = {
        'status': 'completed',
        'started': T(10, 0),
        'ended': T(11, 0),
        'stage_timeline': [
            stage('Assembly', T(10, 0), T(11, 0)),
            stage('Color Grade', T(10, 30), T(10, 50)),  # fully inside Assembly
            stage('Subtitle Burn', T(10, 50), T(11, 0)),
        ],
    }
    assert compute_runtime(job, now=NOW)['runtime_seconds'] == pytest.approx(3600, abs=1)


def test_operator_gate_is_a_wait_not_runtime():
    job = {
        'status': 'archived',
        'started': T(21, 41, 0, day=1),
        'stage_timeline': [
            stage('Contact Sheet Generation', T(21, 41, 0, day=1), T(21, 46, 0, day=1)),
            stage('Awaiting Approval', T(21, 46, 0, day=1), T(4, 21, 0, day=3)),
        ],
    }
    r = compute_runtime(job, now=NOW)
    assert r['runtime_seconds'] == pytest.approx(300, abs=1)  # 5 min of work
    assert r['runtime_wall_seconds'] > 24 * 3600  # ...over a 30h span


def test_preview_render_is_not_mistaken_for_a_review_gate():
    """Word boundaries: 'Preview Render' contains the substring 'review'."""
    job = {
        'status': 'completed',
        'started': T(10, 0),
        'ended': T(10, 20),
        'stage_timeline': [stage('Preview Render', T(10, 0), T(10, 20))],
    }
    assert compute_runtime(job, now=NOW)['runtime_seconds'] == pytest.approx(1200, abs=1)


# ── stale snapshots ──────────────────────────────────────────────────────────
def test_stale_snapshot_claiming_running_does_not_tick():
    """pipeline_*_state.json left behind by a GUI restart read 453h."""
    job = {'status': 'running', 'started': T(10, 0), 'stage_timeline': [stage('Stage 1', T(10, 0), T(10, 30))]}
    a = compute_runtime(job, now=NOW)  # sniffed, not verified
    b = compute_runtime(job, now=NOW + timedelta(hours=5))
    assert a['runtime_running'] is False
    assert a['runtime_seconds'] == b['runtime_seconds'] == pytest.approx(1800, abs=1)


def test_explicit_live_worker_overrides_the_staleness_sniff():
    job = {
        'status': 'running',
        'started': T(10, 0),
        'stage_timeline': [stage('Stage 1', T(10, 0), None, status='running')],
    }
    r = compute_runtime(job, running=True, now=NOW)
    assert r['runtime_running'] is True
    assert r['runtime_seconds'] > 3600


def test_crashed_stage_counts_up_to_its_last_recorded_event():
    """A stage left open by a crash has no known end — use its own last event."""
    job = {
        'status': 'stopped',
        'started': T(10, 0),
        'stage_timeline': [stage('Stage 1', T(10, 0), T(10, 30)), stage('Stage 2', T(10, 30), None, status='running')],
        'debug_events': [{'ts': T(10, 45), 'msg': 'last thing it ever said'}],
    }
    r = compute_runtime(job, running=False, now=NOW)
    assert r['runtime_seconds'] == pytest.approx(2700, abs=1)  # 10:00 → 10:45


def test_open_stage_with_no_evidence_counts_nothing():
    job = {
        'status': 'stopped',
        'started': T(10, 0),
        'stage_timeline': [stage('Stage 1', T(10, 0), T(10, 30)), stage('Stage 2', T(10, 30), None, status='running')],
    }
    r = compute_runtime(job, running=False, now=NOW)
    assert r['runtime_seconds'] == pytest.approx(1800, abs=1)


def test_crashed_stage_evidence_never_swallows_the_resume_gap():
    """The refined open-span rule must not resurrect the dead gap."""
    r = compute_runtime(CREATURE_PARKED, now=NOW)
    assert r['runtime_seconds'] == pytest.approx(4 * 3600 + 20, abs=2)


# ── degenerate input ─────────────────────────────────────────────────────────
def test_job_without_bookkeeping_falls_back_to_the_bounded_wall_span():
    job = {'status': 'failed', 'started': T(10, 0), 'ended': T(10, 45)}
    r = compute_runtime(job, now=NOW)
    assert r['runtime_seconds'] == pytest.approx(2700, abs=1)


def test_missing_start_reports_nothing_rather_than_zero():
    r = compute_runtime({'status': 'running'}, now=NOW)
    assert r['runtime_seconds'] is None and r['runtime_as_of'] is None


def test_garbage_input_never_raises():
    for job in (
        {},
        {'started': 'not-a-date'},
        {'started': None},
        {'started': T(10, 0), 'stage_timeline': 'nonsense'},
        {'started': T(10, 0), 'stage_timeline': [None, 3, {}]},
        {'started': T(10, 0), 'worker': 'nope'},
    ):
        compute_runtime(job, now=NOW)


def test_future_start_is_clamped_not_negative():
    job = {'status': 'running', 'started': (NOW + timedelta(hours=2)).isoformat()}
    r = compute_runtime(job, running=True, now=NOW)
    assert r['runtime_seconds'] == 0.0


def test_parse_ts_accepts_every_format_this_codebase_writes():
    assert parse_ts('2026-08-25T15:23:16.281+02:00') is not None
    assert parse_ts('2026-08-25T15:23:16.281Z') is not None
    assert parse_ts('2026-08-25 15:23:16') is not None  # space separator
    assert parse_ts('2026-08-25T15:23:16') is not None  # naive → UTC
    assert parse_ts(1785744672.65) is not None  # VACE logbook epoch
    assert parse_ts('') is None and parse_ts(None) is None and parse_ts('junk') is None


def test_format_runtime():
    assert format_runtime(None) == '—'
    assert format_runtime(0) == '0m 00s'
    assert format_runtime(67) == '1m 07s'
    assert format_runtime(4 * 3600 + 20) == '4h 00m 20s'


def test_bridge_threshold_is_documented_and_sane():
    """Sub-minute bookkeeping holes bridge; a real dead gap must not."""
    assert 30 <= BRIDGE_GAP_S <= 300


# ── freeze accounting: a wall clock longer than the runtime must say why ─────
def test_every_freeze_is_reported_with_a_reason():
    r = compute_runtime(CREATURE_PARKED, now=NOW)
    assert r['runtime_gap_seconds'] > 0
    assert r['runtime_gaps'], 'a wall clock longer than the runtime must be itemised'
    for gap in r['runtime_gaps']:
        assert gap['reason'] and gap['seconds'] > BRIDGE_GAP_S
        assert gap['from'] < gap['to']


def test_runtime_plus_freezes_always_equals_the_wall_clock():
    """The invariant that makes an unexplained gap impossible."""
    for job in (
        CREATURE_PARKED,
        {
            'status': 'completed',
            'started': T(10, 0),
            'ended': T(11, 0),
            'stage_timeline': [stage('S1', T(10, 0), T(10, 20)), stage('S2', T(10, 50), T(11, 0))],
        },
        {
            'status': 'archived',
            'started': T(9, 0),
            'stage_timeline': [stage('Gen', T(9, 0), T(9, 5)), stage('Awaiting Approval', T(9, 5), T(14, 0))],
        },
    ):
        r = compute_runtime(job, now=NOW)
        assert r['runtime_seconds'] + r['runtime_gap_seconds'] == pytest.approx(r['runtime_wall_seconds'], abs=1.5)


def test_healthy_run_reports_no_freeze():
    job = {
        'status': 'completed',
        'started': T(10, 0),
        'ended': T(10, 45),
        'stage_timeline': [stage('S1', T(10, 0), T(10, 45))],
    }
    r = compute_runtime(job, now=NOW)
    assert r['runtime_gap_seconds'] == 0 and r['runtime_gaps'] == []


def test_operator_gate_freeze_names_the_gate():
    job = {
        'status': 'archived',
        'started': T(9, 0),
        'stage_timeline': [stage('Gen', T(9, 0), T(9, 5)), stage('Awaiting Approval', T(9, 5), T(14, 0))],
    }
    gaps = compute_runtime(job, now=NOW)['runtime_gaps']
    assert len(gaps) == 1 and 'Awaiting Approval' in gaps[0]['reason']


# ── record_pause: the stamp a resume path leaves behind ──────────────────────
def test_record_pause_stamps_the_span_and_reason():
    job = {'status': 'awaiting_review', 'started': T(15, 23), 'debug_events': [{'ts': T(18, 7, 40)}]}
    entry = record_pause(job, resumed_at=T(22, 33, 57), reason='operator gate — sheet review')
    assert entry['seconds'] == pytest.approx(4 * 3600 + 26 * 60 + 17, abs=2)
    assert entry['reason'] == 'operator gate — sheet review'
    assert job['runtime_pauses'] == [entry]
    assert 'clock paused' in pause_log_line(job, entry)


def test_record_pause_is_idempotent():
    job = {'status': 'stopped', 'started': T(10, 0), 'debug_events': [{'ts': T(10, 30)}]}
    first = record_pause(job, resumed_at=T(12, 0), reason='x')
    again = record_pause(job, resumed_at=T(12, 0), reason='x')
    assert first is not None and again is None
    assert len(job['runtime_pauses']) == 1


def test_record_pause_ignores_a_trivial_gap():
    job = {'status': 'stopped', 'started': T(10, 0), 'debug_events': [{'ts': T(10, 30)}]}
    assert record_pause(job, resumed_at=T(10, 30, 30), reason='x') is None
    assert pause_log_line(job, None) == ''


def test_recorded_pauses_survive_the_worker_slot_being_overwritten():
    """A resume overwrites job['worker'], destroying the previous segment's
    evidence. The recorded pause is what keeps that work counted."""
    job = {
        'status': 'running',
        'started': T(15, 23),
        # only the LATEST worker survives — the 22:33→23:49 segment is gone
        'worker': {'started': T(11, 52, 0, day=26), 'ended': None},
        'debug_events': [{'ts': T(23, 49, 52)}],
        'stage_timeline': [stage('Sheet QC', T(15, 23), T(18, 7, 40))],
        'runtime_pauses': [
            {'from': T(18, 7, 40), 'to': T(22, 33, 57), 'seconds': 15977.0, 'reason': 'operator gate — sheet review'},
            {
                'from': T(23, 49, 52),
                'to': T(11, 52, 0, day=26),
                'seconds': 43328.0,
                'reason': 'operator gate — sheet review',
            },
        ],
    }
    r = compute_runtime(job, running=True, now=datetime(2026, 8, 26, 11, 56, tzinfo=TZ))
    # 15:23→18:07 (2h44) + 22:33→23:49 (1h16) + 11:52→11:56 (4m) ≈ 4h04
    assert r['runtime_seconds'] == pytest.approx(4 * 3600 + 4 * 60, abs=90)
    assert len(r['runtime_gaps']) == 2
    assert all('sheet review' in g['reason'] for g in r['runtime_gaps'])


# ── per-card clock for the Kanban card dialog ────────────────────────────────
# The dialog's Started and Duration rows read job.created / job.duration, two
# fields the browser initialised to 0 and no code path ever wrote, so every card
# of every board reported "0s ago" and "0s" (2026-08-26).  These assert the
# numbers the server now supplies in their place.

CARD_NOW = datetime(2026, 8, 26, 11, 56, tzinfo=TZ)


def test_card_times_reads_start_and_span_from_the_timeline():
    job = {
        'stage_timeline': [
            stage('Creature Brief', T(15, 23, 16), T(15, 23, 24)),
            stage('Reference Anchor', T(15, 23, 24), T(15, 41, 39)),
        ]
    }
    ct = card_times(job, ['Creature Brief', 'Reference Anchor'], now=CARD_NOW)
    assert ct['Creature Brief']['elapsed_s'] == pytest.approx(8, abs=0.5)
    assert ct['Reference Anchor']['elapsed_s'] == pytest.approx(18 * 60 + 15, abs=0.5)
    assert ct['Creature Brief']['running'] is False
    # "Started ... ago" is measured from now, not from the span
    assert ct['Creature Brief']['since_s'] == pytest.approx(20 * 3600 + 32 * 60 + 44, abs=2)


def test_card_with_no_timeline_row_is_omitted_not_zeroed():
    """A queued card has genuinely not started — the browser must render '—'."""
    job = {'stage_timeline': [stage('Creature Brief', T(15, 23), T(15, 24))]}
    ct = card_times(job, ['Creature Brief', 'LoRA Training'], now=CARD_NOW)
    assert 'LoRA Training' not in ct
    assert ct['Creature Brief']['elapsed_s'] == pytest.approx(60, abs=0.5)


def test_running_card_ticks_to_now_despite_a_stale_ended_at():
    """The live 2026-08-26 creature run: 'Multi-Angle Sheet' was reopened as
    running with the sent-back pass's ended_at still on the row.  Reading that
    end would freeze the card at 16:37 while the stage was still working."""
    job = {
        'stage_timeline': [
            stage('Multi-Angle Sheet', T(15, 41, 39), T(16, 37, 17), status='running'),
        ]
    }
    ct = card_times(job, ['Multi-Angle Sheet'], now=CARD_NOW)
    assert ct['Multi-Angle Sheet']['running'] is True
    assert ct['Multi-Angle Sheet']['ended_at'] is None
    assert ct['Multi-Angle Sheet']['elapsed_s'] == pytest.approx(20 * 3600 + 14 * 60 + 21, abs=2)


def test_re_run_stage_dates_its_newest_attempt():
    """creature_worker now appends a fresh row per attempt; the card must show
    the live pass, not the one the review gate sent back."""
    job = {
        'stage_timeline': [
            stage('Multi-Angle Sheet', T(15, 41), T(16, 37)),
            stage('Sheet Review', T(18, 7), T(22, 33)),
            stage('Multi-Angle Sheet', T(22, 33), None, status='running'),
        ]
    }
    ct = card_times(job, ['Multi-Angle Sheet'], now=CARD_NOW)
    assert ct['Multi-Angle Sheet']['started_at'] == T(22, 33)
    assert ct['Multi-Angle Sheet']['elapsed_s'] == pytest.approx(13 * 3600 + 23 * 60, abs=60)


def test_open_row_on_a_dead_job_does_not_count_up_to_now():
    """A crash left the row open: its true end is unknown, so the card reports
    what the writer recorded rather than a span that keeps growing."""
    job = {
        'stage_timeline': [
            dict(stage('TTS Narration', T(15, 0), None, status='failed'), elapsed_s=42.0),
        ]
    }
    ct = card_times(job, ['TTS Narration'], now=CARD_NOW)
    assert ct['TTS Narration']['elapsed_s'] == 42.0
    assert ct['TTS Narration']['running'] is False


def test_fragment_matcher_binds_a_card_to_the_row_its_status_came_from():
    """The documentary board joins cards to stages by fragment, and passes the
    key it matched so a card cannot show one stage's status beside another
    stage's clock."""
    job = {
        'stage_timeline': [
            stage('Stage 3: Script Prep', T(15, 0), T(15, 30)),
            stage('Stage 4 — TTS Narration', T(15, 30), T(16, 0)),
        ]
    }
    keys = {'Script Generation': 'stage 3: script prep', 'TTS Narration': 'stage 4 — tts narration'}
    ct = card_times(job, keys, now=CARD_NOW, match=lambda card, name: name == keys.get(card))
    assert ct['Script Generation']['elapsed_s'] == pytest.approx(1800, abs=1)
    assert ct['TTS Narration']['elapsed_s'] == pytest.approx(1800, abs=1)


def test_epoch_timestamps_are_normalised_to_iso():
    """pipeline_envfx_runner stamps rows with time.time() floats."""
    epoch = CARD_NOW.timestamp() - 300
    job = {
        'stage_timeline': [
            {'name': 'Scenery Render', 'status': 'running', 'ts': epoch},
        ]
    }
    ct = card_times(job, ['Scenery Render'], now=CARD_NOW)
    assert isinstance(ct['Scenery Render']['started_at'], str)
    assert parse_ts(ct['Scenery Render']['started_at']) is not None
    assert ct['Scenery Render']['elapsed_s'] == pytest.approx(300, abs=1)


def test_job_without_a_timeline_yields_no_clocks():
    assert card_times({}, ['Anything'], now=CARD_NOW) == {}


def test_board_status_settles_which_card_is_running():
    """The live 2026-08-26 creature run had THREE rows claiming 'running' at
    once, its worker having moved on without closing them.  The board shows one
    card running; a queued card must not render beside a ticking clock."""
    job = {
        'stage_timeline': [
            stage('Multi-Angle Sheet', T(15, 41, 39), T(16, 37, 17), status='running'),
            stage('Sheet QC', T(16, 37, 17), T(18, 7, 40), status='running'),
            stage('Sheet Review', T(18, 7, 40), None, status='running'),
        ]
    }
    ct = card_times(job, {'Multi-Angle Sheet': 'running', 'Sheet QC': 'queued', 'Sheet Review': 'queued'}, now=CARD_NOW)
    assert ct['Multi-Angle Sheet']['running'] is True
    assert ct['Multi-Angle Sheet']['ended_at'] is None  # ticks past its stale end
    # Not the running card: its recorded span is reported, frozen.
    assert ct['Sheet QC']['running'] is False
    assert ct['Sheet QC']['elapsed_s'] == pytest.approx(90 * 60 + 23, abs=2)
    # Open row on a card the board is not showing as running: nothing to time.
    assert ct['Sheet Review']['running'] is False
    assert ct['Sheet Review']['elapsed_s'] is None
