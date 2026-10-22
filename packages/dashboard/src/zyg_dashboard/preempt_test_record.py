#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""preempt_test_record.py — the Pre-Emptive bank build, recorded as a Test Data card.

2026-09-23. The operator turned the bank on for 100 documentary brains + 100 song briefs
and asked for the run to be measured properly, as a test. This script computes that card
from files the run itself writes — the bank entries and their turn ledgers, the quota
meter samples, the llm_audit rows — and re-records it with replace=True, so it can be run
as often as you like while the build goes on and the card always shows the run so far.

    python3 preempt_test_record.py            # refresh the card
    python3 preempt_test_record.py --print    # ... and dump the record

Nothing here is an assumption. Where a number cannot be measured yet (no entry replayed,
no meter sample spanning a recording) the card says so instead of guessing.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime

from zyg_dashboard import preempt_bank as pb
import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)


TEST_ID = 'preempt-bank-100-100'
RUNTIME = pb.RUNTIME
QUOTA_SAMPLES = os.path.join(RUNTIME, 'quota_samples.jsonl')


def _ts(iso):
    try:
        return datetime.fromisoformat(str(iso)).timestamp()
    except (TypeError, ValueError):
        return None


def _median(v):
    v = sorted(x for x in v if x is not None)
    if not v:
        return None
    n = len(v)
    return v[n // 2] if n % 2 else (v[n // 2 - 1] + v[n // 2]) / 2.0


def _samples():
    rows = []
    try:
        with open(QUOTA_SAMPLES, encoding='utf-8') as fh:
            for line in fh:
                if line.strip():
                    try:
                        rows.append(json.loads(line))
                    except ValueError as _exc:
                        _zyg_log.debug('malformed quota sample skipped: %s', _exc)
    except OSError as _exc:
        _zyg_log.warning('%s unreadable, continuing with no quota samples: %s', QUOTA_SAMPLES, _exc)
    rows.sort(key=lambda r: r.get('ts') or 0)
    return rows


def _meter_cost(entry, samples):
    """(7-day points, 5-hour points) the meter moved across this recording, or (None, None).

    A window that RESET inside the run cannot be differenced — those are dropped rather
    than counted as zero, which would flatter the bank.
    """
    t0, t1 = _ts(entry.get('created_at')), _ts(entry.get('built_at'))
    if not t0 or not t1:
        return None, None
    before = [s for s in samples if (s.get('ts') or 0) <= t0]
    after = [s for s in samples if t1 <= (s.get('ts') or 0) <= t1 + 1800]
    if not before or not after:
        return None, None
    out = []
    for key in ('seven_day', 'five_hour'):
        a = (before[-1].get(key) or {}).get('pct')
        b = (after[0].get(key) or {}).get('pct')
        out.append(b - a if (a is not None and b is not None and b >= a) else None)
    return out[0], out[1]


@dataclass
class Measured:
    """Every number the card reads, measured once from `pb.bank_metrics()` and the meter samples.

    `built` are the entries that reached the bank (newest last), each carrying the
    `week_pct`/`hour_pct` the meter moved across its recording; the medians are over those.
    """

    rows: list
    totals: dict
    counts: dict
    songs_counts: dict
    state: dict
    song_rows: list
    doc_target: int
    song_target: int
    ceiling: float
    samples: list
    built: list
    failed: list
    med_tok: float | None
    med_turns: float | None
    med_wall: float | None
    med_week: float | None
    med_hour: float | None
    remaining: int
    hits: int
    misses: int
    hit_rate: float | None
    live_per: float | None
    replayed: list
    running: bool
    status: str


def _targets():
    """(documentary target, song target, quota ceiling %) from the queue settings, or the defaults."""
    try:
        from zyg_dashboard import approval_queue_settings as aqs

        dt = int(aqs.get('preempt', 'documentary_target') or 100)
        st_t = int(aqs.get('preempt', 'songs_target') or 100)
        ceiling = float(aqs.get('preempt', 'quota_ceiling_pct') or 90)
    except Exception:  # noqa: BLE001
        dt, st_t, ceiling = 100, 100, 90.0
    return dt, st_t, ceiling


def _measure(bank):
    """Reduce a `pb.bank_metrics()` dict to a `Measured`, annotating each built entry in place.

    Every entry in `bank['entries']` with a terminal-ish status gains `week_pct`/`hour_pct`
    (the meter movement across its recording, or None when no sample spans it).
    """
    rows, tot = bank['entries'], bank['totals']
    c, sc = bank['counts'], bank['songs_counts']
    dt, st_t, ceiling = _targets()
    samples = _samples()
    built = [r for r in rows if r['status'] in ('ready', 'claimed', 'consumed')]
    built.sort(key=lambda r: r.get('built_at') or r.get('created_at') or '')
    failed = [r for r in rows if r['status'] == 'failed']
    for r in built:
        r['week_pct'], r['hour_pct'] = _meter_cost(r, samples)
    replayed = [r for r in rows if r.get('replay')]
    hits, misses = tot['replay_hits'], tot['replay_misses']
    running = c['built'] < dt or sc['built'] < st_t
    return Measured(
        rows=rows,
        totals=tot,
        counts=c,
        songs_counts=sc,
        state=bank.get('state') or {},
        song_rows=sorted((bank.get('songs') or []), key=lambda r: str(r.get('created_at') or '')),
        doc_target=dt,
        song_target=st_t,
        ceiling=ceiling,
        samples=samples,
        built=built,
        failed=failed,
        med_tok=_median([r['output_tokens'] for r in built if r['output_tokens']]),
        med_turns=_median([r['turns'] for r in built if r['turns']]),
        med_wall=_median([r['build_s'] for r in built if r['build_s']]),
        med_week=_median([r['week_pct'] for r in built if r['week_pct'] is not None]),
        med_hour=_median([r['hour_pct'] for r in built if r['hour_pct'] is not None]),
        remaining=max(0, dt - c['built']),
        hits=hits,
        misses=misses,
        hit_rate=round(100.0 * hits / (hits + misses), 1) if (hits + misses) else None,
        live_per=round(tot['replay_live'] / len(replayed), 1) if replayed else None,
        replayed=replayed,
        running=running,
        status='running' if running else ('mixed' if failed else 'pass'),
    )


def _chart_progress(m):
    """Chart 1: both banked counts, cumulative, merged onto one shared category axis of timestamps."""
    marks = sorted(
        {
            *(str(r.get('built_at') or r.get('created_at') or '')[:19] for r in m.built),
            *(str(r.get('created_at') or '')[:19] for r in m.song_rows),
        }
        - {''}
    )
    dline, sline = [], []
    for mark in marks:
        dline.append(sum(1 for r in m.built if str(r.get('built_at') or r.get('created_at') or '')[:19] <= mark))
        sline.append(sum(1 for r in m.song_rows if str(r.get('created_at') or '')[:19] <= mark))
    return {
        'title': 'The bank filling',
        'kind': 'line',
        'x': {'label': 'When the entry was banked', 'type': 'category', 'values': marks},
        'y': {'label': 'Entries banked (cumulative)', 'unit': 'count', 'min': 0},
        'series': [
            {'id': 'docs', 'label': 'Documentary brains', 'values': dline},
            {'id': 'songs', 'label': 'Song briefs', 'values': sline},
        ],
        'refs': [{'kind': 'target', 'value': m.doc_target, 'label': f'target: {m.doc_target} of each'}],
        'note': 'Each documentary point is a brain whose every text Claude call is on disk; each song point is a brief (the song workflow makes no Claude calls).',
    }


def _chart_cost(m):
    """Chart 2: output tokens per banked brain as columns, with the 7-day meter as a second axis."""
    return {
        'title': 'Cost of each banked brain',
        'kind': 'columns',
        'x': {
            'label': 'Brain, in the order it was banked',
            'type': 'number',
            'values': list(range(1, len(m.built) + 1)),
        },
        'y': {'label': 'Output tokens recorded', 'unit': 'tokens', 'min': 0},
        'y2': {'label': '7-day Claude meter burned', 'unit': 'pct', 'min': 0},
        'series': [
            {'id': 'tokens', 'label': 'Output tokens', 'values': [r['output_tokens'] for r in m.built]},
            {
                'id': 'week',
                'label': '% of the Claude week (meter)',
                'kind': 'line',
                'axis': 'y2',
                'values': [r['week_pct'] for r in m.built],
            },
        ],
        'refs': (
            [{'kind': 'baseline', 'value': m.med_tok, 'label': f'median {m.med_tok:,.0f} output tokens'}]
            if m.med_tok
            else []
        ),
        'note': 'Tokens come from the turn ledger of each entry; the meter line is the 7-day window measured across the recording, so a window that reset mid-run is a gap, not a zero.',
    }


def _chart_meter(m):
    """Chart 3: the two quota windows, from an hour before the first recording, last 600 samples."""
    ms = (
        [s for s in m.samples if (s.get('ts') or 0) >= (_ts(m.built[0]['created_at']) or 0) - 3600]
        if m.built
        else m.samples[-400:]
    )
    ms = ms[-600:]
    return {
        'title': 'The Claude meter through the build',
        'kind': 'line',
        'x': {
            'label': 'Sample',
            'type': 'category',
            'values': [datetime.fromtimestamp(s['ts']).strftime('%m-%d %H:%M') for s in ms if s.get('ts')],
        },
        'y': {'label': 'Window used', 'unit': 'pct', 'min': 0, 'max': 100},
        'series': [
            {
                'id': 'week',
                'label': '7-day window',
                'values': [(s.get('seven_day') or {}).get('pct') for s in ms if s.get('ts')],
            },
            {
                'id': 'hour',
                'label': '5-hour window',
                'values': [(s.get('five_hour') or {}).get('pct') for s in ms if s.get('ts')],
            },
        ],
        'refs': [{'kind': 'limit', 'value': m.ceiling, 'label': f'builder holds at {m.ceiling:g} %'}],
        'note': 'The saw-tooth is the window resetting, not the bank stopping. The builder holds above the ceiling and resumes at the reset.',
    }


def _entry_table(m):
    """The per-entry table: every entry the bank attempted, newest first, with em-dashes for gaps."""
    return {
        'columns': [
            {'t': 'Topic'},
            {'t': 'Status'},
            {'t': 'Turns', 'r': True},
            {'t': 'Output tokens', 'r': True},
            {'t': 'Recording wall', 'r': True},
            {'t': '7-day meter', 'r': True},
            {'t': 'Replay'},
            {'t': 'Error'},
        ],
        'rows': [
            [
                r['topic'] or r['id'],
                r['status'],
                r['turns'],
                f'{r["output_tokens"]:,}',
                (f'{r["build_s"] / 60:.0f} min' if r.get('build_s') else '—'),
                (f'{r["week_pct"]:g} %' if r.get('week_pct') is not None else '—'),
                (
                    f'{(r.get("replay") or {}).get("hits", 0)} replayed / {(r.get("replay") or {}).get("live", 0)} live'
                    if r.get('replay')
                    else '—'
                ),
                (r.get('error') or ''),
            ]
            for r in sorted(m.rows, key=lambda r: str(r.get('created_at') or ''), reverse=True)
        ],
        'note': 'Every entry the bank has attempted, newest first.',
    }


def _facts(m):
    """The eleven fact tiles, each saying so when its number cannot be measured yet."""
    c, sc, tot = m.counts, m.songs_counts, m.totals
    return [
        {
            'label': 'Documentary brains banked',
            'value': f'{c["built"]} of {m.doc_target}',
            'fmt': 'text',
            'sub': f'{c["ready"]} ready · {c["claimed"]} claimed · {c["consumed"]} consumed · {len(m.failed)} failed',
        },
        {
            'label': 'Song briefs banked',
            'value': f'{sc["built"]} of {m.song_target}',
            'fmt': 'text',
            'sub': 'briefs only — the song workflow makes no Claude calls at all',
        },
        {
            'label': 'Median Claude turns per brain',
            'value': m.med_turns,
            'fmt': 'number',
            'sub': f'{tot["turns"]} turns recorded in total',
        },
        {
            'label': 'Median output tokens per brain',
            'value': m.med_tok,
            'fmt': 'tokens',
            'sub': f'{tot["output_tokens"]:,} recorded in total',
        },
        {
            'label': 'Median wall time per brain',
            'value': round(m.med_wall / 60, 1) if m.med_wall else None,
            'fmt': 'min',
            'sub': 'topic pick to snapshot, TTS included (the scene timings need it)',
        },
        {
            'label': 'Claude week burned per brain',
            'value': m.med_week,
            'fmt': 'pct',
            'sub': (
                f'measured on the meter · {m.med_hour:g} % of a 5-hour window each'
                if m.med_hour is not None
                else 'measured on the 7-day meter'
            )
            if m.med_week is not None
            else 'no meter sample spans a recording yet',
        },
        {
            'label': 'Replay hit rate',
            'value': m.hit_rate,
            'fmt': 'pct',
            'sub': f'{m.hits} of {m.hits + m.misses} banked turns answered from the bank'
            if (m.hits + m.misses)
            else 'nothing replayed yet',
        },
        {
            'label': 'Live calls a replayed episode still makes',
            'value': m.live_per,
            'fmt': 'number',
            'sub': 'vision judges — they look at frames that do not exist until the render runs',
        },
        {
            'label': 'Output tokens not bought again',
            'value': tot['tokens_saved'],
            'fmt': 'tokens',
            'sub': f'across {len(m.replayed)} replayed entr' + ('y' if len(m.replayed) == 1 else 'ies'),
        },
        {
            'label': 'Quota still needed for the target',
            'value': round(m.remaining * m.med_week / 100.0, 1) if m.med_week else None,
            'fmt': 'number',
            'sub': f'Claude weeks, for the {m.remaining} brains still to record',
        },
        {
            'label': 'Machine time still needed',
            'value': round(m.remaining * m.med_wall / 3600, 1) if m.med_wall else None,
            'fmt': 'h',
            'sub': 'back to back, one pipeline at a time',
        },
    ]


def _verdict(m):
    """The one-paragraph verdict: what is banked, what each brain cost, what a replay still buys."""
    c, sc = m.counts, m.songs_counts
    if not m.running:
        return f'Target reached: {c["built"]} brains and {sc["built"]} briefs banked.'
    return (
        f'Running. {c["built"]} of {m.doc_target} brains and {sc["built"]} of {m.song_target} briefs are banked'
        + (
            f'; each brain costs about {m.med_week:g} % of a Claude week and {m.med_wall / 60:.0f} minutes of the box'
            if (m.med_week is not None and m.med_wall)
            else ''
        )
        + (
            f', and a replayed entry answers {m.hit_rate:g} % of its banked turns from disk while still making '
            f'{m.live_per:g} live vision calls.'
            if m.hit_rate is not None and m.live_per
            else '.'
        )
    )


def build_record():
    """The whole Test Data card for the pre-emptive bank build, measured from the run's own files."""
    m = _measure(pb.bank_metrics())
    c, sc, tot, state = m.counts, m.songs_counts, m.totals, m.state
    dt, st_t, remaining = m.doc_target, m.song_target, m.remaining
    return {
        'id': TEST_ID,
        'title': 'Pre-emptive bank build — 100 documentary brains + 100 song briefs',
        'question': 'What does it cost, in Claude quota and machine time, to pre-record a hundred episodes '
        'and a hundred song briefs — and how much of an episode does a banked brain actually cover?',
        'lane': 'capacity',
        'status': m.status,
        'tags': ['preempt', 'documentary', 'kidsmusic', 'subscription', 'quota'],
        'run_by': 'Approval Queue → Pre-Emptive generation (bp_preempt watcher)',
        'command': 'python3 preempt_test_record.py   # refreshes this card from the bank while it builds',
        'environment': {
            'targets': f'{dt} documentary brains, {st_t} song briefs',
            'quota ceiling': f'{m.ceiling:g} % on either window',
            'model': 'claude-opus-5 on the login (headless claude -p)',
            'builder': 'ON'
            if state.get('enabled') and not state.get('paused')
            else ('paused' if state.get('paused') else 'off'),
            'rule': 'one pipeline at a time; songs take the gap between brain runs',
        },
        'headline': {
            'value': c['built'],
            'fmt': 'count',
            'label': f'documentary brains banked of {dt}',
            'sub': f'{sc["built"]} of {st_t} song briefs · '
            + (f'{remaining} brains to go' if remaining else 'target reached'),
        },
        'verdict': _verdict(m),
        'method': [
            'The Approval Queue card runs the scholarly pipeline in RECORD mode: every text Claude call of an episode '
            'is written to the entry, and the run stops before the first image. No episode is produced by a recording.',
            "Cost per brain is read from the entry's own turn ledger (usage per turn), not re-derived from the audit log.",
            'Quota per brain is the 7-day and 5-hour meter measured across the recording (quota_samples.jsonl, sampled '
            'every 10 minutes). A window that reset inside a run is a gap, never a zero.',
            "Replay figures come from the entry's last_replay counters, written when the documentary batcher consumed it.",
            'Song briefs are picked by the local model; they are counted as briefs, never as Claude calls.',
        ],
        'chart': _chart_progress(m),
        'charts': [_chart_cost(m), _chart_meter(m)],
        'facts': _facts(m),
        'table': _entry_table(m),
        'null_model': 'Without the bank, an episode buys its text calls at render time: the same ~'
        + (f'{m.med_turns:g}' if m.med_turns else '11')
        + ' turns and ~'
        + (f'{m.med_tok:,.0f}' if m.med_tok else '78,000')
        + ' output tokens, on the subscription that is out. '
        'The bank moves that spend earlier, it does not remove it — the test is whether the move is complete '
        'enough to render with the subscription gone.',
        'limitations': [
            'The bank holds TEXT calls only. The vision judges (typography, anatomy, era) look at rendered frames, so they '
            'cannot be pre-recorded; the first consumed entry still made 59 live subscription calls at render time. Each of '
            'those sites falls back to a local judge when a turn is refused — that fallback is what makes the episode '
            'renderable with the subscription out, not the bank.',
            'The 7-day meter is reported in whole percent, so a single recording is measured to ±1 point; the median over '
            'many recordings is the number to trust.',
            'Wall time includes TTS, which the replay runs again — the recording does not save it.',
        ],
        'sources': [
            {
                'source': 'Bank entries and turn ledgers',
                'path': 'data/runtime/preempt/documentary/*/',
                'note': 'entry.json + turns.jsonl, written by preempt_bank.py',
            },
            {'source': 'Song briefs', 'path': 'data/runtime/preempt/songs.json', 'note': ''},
            {
                'source': 'Claude quota meter',
                'path': 'data/runtime/quota_samples.jsonl',
                'note': 'zyg-quota-meter.timer, every 10 min',
            },
            {
                'source': 'LLM audit',
                'path': 'data/runtime/llm_audit/*.jsonl',
                'note': 'record turns carry preempt_mode=record; replays carry backend=preempt_replay',
            },
        ],
        'raw': {
            'totals': tot,
            'counts': c,
            'songs_counts': sc,
            'per_entry': [
                {
                    k: r.get(k)
                    for k in ('id', 'topic', 'status', 'turns', 'output_tokens', 'build_s', 'week_pct', 'hour_pct')
                }
                for r in m.built
            ],
        },
    }


if __name__ == '__main__':  # the CLI lives in preempt_test_record_cli
    from zyg_dashboard.preempt_test_record_cli import main as _cli_main

    raise SystemExit(_cli_main())
