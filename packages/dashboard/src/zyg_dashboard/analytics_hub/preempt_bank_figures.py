# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The figures and blocks of the Pre-emptive bank card.

`preempt_bank_card` is the orchestrator: it reads the ledger, calls
`bank_figures` once and hands the result to the block builders here. Nothing in
this module reads a clock or a file by itself — every number comes from the
bank ledger or the quota meter samples passed in.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from zyg_dashboard import metrics_hub as mh

from .constants import _zyg_log
from .helpers import _bucket_series, _daykey, _delta, _fc_bucketed, _forecast, _median

WAVE_GAP_S = 600
"""A wave is a run of entries with no gap longer than this between them."""


@dataclass
class BankFigures:
    """Every measured number the Pre-emptive bank card renders.

    Built once by `bank_figures` from the ledger `preempt_bank.bank_metrics()`
    returns plus the quota meter samples; the block builders below only format
    it.
    """

    dt: int
    st_target: int
    state: dict
    counts: dict
    songs_counts: dict
    totals: dict
    built: list
    failed: list
    built_day: dict
    fail_day: dict
    tok_day: dict
    song_day: dict
    fc: Any
    med_build: Any
    med_tok: Any
    med_turns: Any
    remaining: int
    hours_left: Any
    tokens_left: Any
    week_pct: Any
    hour_pct: Any
    week_n: int
    weekly_price: Any
    weeks_needed: Any
    replayed: list
    hits: int
    hit_rate: Any
    live_per: Any
    on: bool
    note: str
    pct_done: Any
    per_day_rows: list = field(default_factory=list)


def ts_of(iso):
    """POSIX timestamp of an ISO-8601 string, or None when it is absent or malformed."""
    try:
        return datetime.fromisoformat(str(iso)).timestamp()
    except (TypeError, ValueError):
        return None


def day_totals(rows, sel, val=lambda r: 1.0, key='built_at'):
    """Sum `val` per day key over the `rows` that `sel` accepts.

    The day comes from `key`, falling back to `created_at`; a row with no usable
    timestamp is dropped.
    """
    m: dict = {}
    for r in rows:
        if not sel(r):
            continue
        t = ts_of(r.get(key) or r.get('created_at'))
        if t:
            dk = _daykey(t)
            m[dk] = m.get(dk, 0.0) + val(r)
    return m


def song_day_totals(songs):
    """Count banked song briefs per day key, from their `created_at`."""
    out: dict = {}
    for r in songs or []:
        t = ts_of(r.get('created_at'))
        if t:
            dk = _daykey(t)
            out[dk] = out.get(dk, 0) + 1
    return out


def split_waves(built):
    """Group the built entries into waves — runs with no gap longer than WAVE_GAP_S.

    Recordings run in parallel, so a single entry's meter movement contains
    every other recording that overlapped it; the wave is the unit that can be
    charged. Entries are read in `created_at` order and ones without a start
    timestamp are dropped.
    """
    waves, cur = [], []
    for r in sorted(built, key=lambda r: ts_of(r.get('created_at')) or 0):
        t0 = ts_of(r.get('created_at'))
        if not t0:
            continue
        if cur and t0 - (ts_of(cur[-1].get('built_at')) or ts_of(cur[-1].get('created_at')) or t0) > WAVE_GAP_S:
            waves.append(cur)
            cur = []
        cur.append(r)
    if cur:
        waves.append(cur)
    return waves


def wave_share(t0, t1):
    """The bank's measured share of everything billed to the login in [t0, t1].

    The meter belongs to the WHOLE login: on 2026-09-23 nine Claude sessions
    were billing to it at once, so charging its movement to the bank overstated
    a recording by more than 10x. Two weightings (output only / with cached
    tokens) bracket it, because the meter's own cache weighting is not
    published. Falls back to 1.0 — the full window — and says so in the log.
    """
    try:
        from zyg_dashboard import preempt_meter_share as _pms

        sh = _pms.bank_share(t0, t1)
        shares = [x for x in (sh.get('share_out'), sh.get('share_list')) if x]
        if shares:
            return sum(shares) / len(shares)
    except Exception as _exc:  # noqa: BLE001
        _zyg_log.warning('bank meter share unavailable, charging the full window share: %s', _exc)
    return 1.0


def quota_samples(now):
    """Return (meter samples, price of a Claude week) — ([], None) when the meter is unreadable."""
    try:
        q = mh._quota_meter()
        qcfg = q.load_config()
        samples = q.read_samples()
        return samples, float(q.compute(qcfg, samples[-1] if samples else {}, {}, {}, now)['weekly_price'])
    except Exception:  # noqa: BLE001
        return [], None


def meter_cost(built, samples):
    """Return (week_pct, hour_pct, recordings) — the meter cost of one banked brain.

    Measured on the meter, not derived from a price list: the 09-20 recording
    moved the 7-day meter 40 -> 43 % while a list-price derivation of the same
    tokens said 7.5 %. Per wave, divided by the brains the wave banked, times
    the bank's share of the window; both windows, because the 5-hour one binds
    first. A window that reset cannot be differenced and is skipped.
    """
    week_n = 0
    try:
        wd, hd = [], []
        for w in split_waves(built):
            t0 = min(ts_of(r.get('created_at')) or 0 for r in w)
            t1 = max(ts_of(r.get('built_at')) or 0 for r in w)
            if not t0 or not t1:
                continue
            before = [x for x in samples if x.get('ts') and x['ts'] <= t0]
            after = [x for x in samples if x.get('ts') and t1 <= x['ts'] <= t1 + 1800]
            if not before or not after:
                continue
            share = wave_share(t0, t1 + 1800)
            for key, acc in (('seven_day', wd), ('five_hour', hd)):
                a = (before[-1].get(key) or {}).get('pct')
                b = (after[0].get(key) or {}).get('pct')
                if a is not None and b is not None and b >= a:
                    acc.append((b - a) * share / len(w))
            week_n += len(w)
        return (
            round(_median(wd), 3) if wd else None,
            round(_median(hd), 3) if hd else None,
            week_n,
        )
    except Exception as _exc:  # noqa: BLE001
        _zyg_log.warning('meter cost estimate failed, week/hour percentages stay unset: %s', _exc)
        return None, None, week_n


def bank_figures(bank, dt, st_target, trend_keys, now) -> BankFigures:
    """Measure the whole card from the bank ledger: per-day series, medians, meter cost, replay.

    `dt`/`st_target` are the documentary and song targets, `trend_keys` the day
    keys the brains/day forecast is fitted over, `now` the moment the quota
    meter is read at.
    """
    rows, tot = bank['entries'], bank['totals']
    state = bank.get('state') or {}
    c, sc = bank['counts'], bank['songs_counts']
    built = [r for r in rows if r['status'] in ('ready', 'claimed', 'consumed')]
    failed = [r for r in rows if r['status'] == 'failed']
    built_day = day_totals(rows, lambda r: r['status'] in ('ready', 'claimed', 'consumed'))
    fail_day = day_totals(rows, lambda r: r['status'] == 'failed', key='created_at')
    tok_day = day_totals(rows, lambda r: True, lambda r: r['output_tokens'])
    song_day = song_day_totals(bank.get('songs'))
    med_build = _median([r['build_s'] for r in built if r['build_s']])
    med_tok = _median([r['output_tokens'] for r in built if r['output_tokens']])
    remaining = max(0, dt - c['built'])
    samples, weekly_price = quota_samples(now)
    week_pct, hour_pct, week_n = meter_cost(built, samples)
    replayed = [r for r in rows if r.get('replay')]
    hits = tot['replay_hits']
    return BankFigures(
        dt=dt,
        st_target=st_target,
        state=state,
        counts=c,
        songs_counts=sc,
        totals=tot,
        built=built,
        failed=failed,
        built_day=built_day,
        fail_day=fail_day,
        tok_day=tok_day,
        song_day=song_day,
        fc=_forecast([built_day.get(k, 0.0) for k in trend_keys], floor=0.0),
        med_build=med_build,
        med_tok=med_tok,
        med_turns=_median([r['turns'] for r in built if r['turns']]),
        remaining=remaining,
        hours_left=round(remaining * med_build / 3600.0, 1) if med_build else None,
        tokens_left=int(remaining * med_tok) if med_tok else None,
        week_pct=week_pct,
        hour_pct=hour_pct,
        week_n=week_n,
        weekly_price=weekly_price,
        weeks_needed=round(remaining * week_pct / 100.0, 1) if (week_pct and remaining) else None,
        replayed=replayed,
        hits=hits,
        hit_rate=mh._rate(hits, hits + tot['replay_misses']),
        live_per=round(tot['replay_live'] / len(replayed), 1) if replayed else None,
        on=bool(state.get('enabled')) and not state.get('paused'),
        note=(state.get('documentary') or {}).get('note') or '',
        pct_done=round(100.0 * min(c['built'], dt) / dt, 1) if dt else None,
        per_day_rows=per_day_rows(built_day, fail_day, tok_day, song_day),
    )


def per_day_rows(built_day, fail_day, tok_day, song_day):
    """The card's table: the most recent 90 days, newest first, as [day, built, failed, tokens, songs]."""
    out = []
    for dk in sorted(set(built_day) | set(fail_day) | set(song_day), reverse=True)[:90]:
        out.append(
            [dk, int(built_day.get(dk, 0)), int(fail_day.get(dk, 0)), int(tok_day.get(dk, 0)), int(song_day.get(dk, 0))]
        )
    return out


def headline_block(f: BankFigures):
    """The headline: brains banked against the target, and whether the builder is running."""
    return {
        'value': f.counts['built'],
        'fmt': 'int',
        'label': f'documentary brains banked of {f.dt} · builder ' + ('ON' if f.on else 'off'),
        'sub': f'{f.songs_counts["built"]} of {f.st_target} song briefs · {f.pct_done:g} % of the documentary target'
        + (f' · {f.note}' if f.note else ''),
    }


def delta_block(f: BankFigures, d7, d14, d8):
    """Brains banked in the last 7 days against the 7 before them."""
    return {
        'pct': _delta(
            sum(v for k, v in f.built_day.items() if k >= d7),
            sum(v for k, v in f.built_day.items() if d14 <= k <= d8),
        ),
        'label': 'brains banked, last 7 d vs the 7 before',
        'good_when': 'up',
    }


def chart_block(f: BankFigures, keys, weekly, bucket, fkeys):
    """Stacked columns of brains/failures/songs per bucket, with the trend and the token row."""
    fc = f.fc
    return {
        'kind': 'columns',
        'bucket': bucket,
        'keys': keys,
        'stacked': True,
        'y': 'int',
        'title': 'Bank filled per ' + bucket,
        'series': [
            {
                'id': 'built',
                'label': 'Documentary brains banked',
                'values': [int(v) for v in _bucket_series(f.built_day, keys, weekly)],
            },
            {
                'id': 'failed',
                'label': 'Failed recordings',
                'values': [int(v) for v in _bucket_series(f.fail_day, keys, weekly)],
            },
            {
                'id': 'songs',
                'label': 'Song briefs banked',
                'values': [int(v) for v in _bucket_series(f.song_day, keys, weekly)],
            },
        ],
        'forecast': (
            [
                {
                    'id': 'trend',
                    'label': 'Brains/day trend',
                    **_fc_bucketed(fc, fkeys, weekly, 'sum'),
                    'slope_per_day': fc['slope_per_day'],
                    'r2': fc['r2'],
                    'n': fc['n'],
                }
            ]
            if fc
            else []
        ),
        'secondary': {
            'label': 'Output tokens recorded (thousands)',
            'kind': 'columns',
            'y': 'num',
            'values': [round(x / 1000.0, 1) for x in _bucket_series(f.tok_day, keys, weekly)],
        },
    }


def _meter_sub(f: BankFigures):
    """The sub-line of the 'Claude week burned per brain' fact — or why there is no number."""
    if not f.week_pct:
        return 'no meter sample spans a recording yet'
    return (
        f"the bank's SHARE of the 7-day meter over each wave ÷ its brains, {f.week_n} recording(s)"
        + ' — the meter is the whole login and several sessions bill to it'
        + (f' · {f.hour_pct:g} % of a 5-hour window each' if f.hour_pct else '')
        + (f' · a Claude week is worth {f.weekly_price:.2f}' if f.weekly_price else '')
    )


def _historical_facts(f: BankFigures):
    """What the bank has recorded so far: entries, turns, tokens, wall time, meter cost."""
    c, sc, tot = f.counts, f.songs_counts, f.totals
    return [
        {
            'label': 'Brains banked, all time',
            'value': len(f.built),
            'fmt': 'int',
            'sub': f'{c["ready"]} ready · {c["claimed"]} claimed · {c["consumed"]} consumed · {len(f.failed)} failed',
        },
        {
            'label': 'Claude turns recorded',
            'value': tot['turns'],
            'fmt': 'int',
            'sub': f'median {f.med_turns:g} turns per brain' if f.med_turns else 'no completed recording yet',
        },
        {
            'label': 'Output tokens recorded',
            'value': tot['output_tokens'],
            'fmt': 'int',
            'sub': f'{tot["cache_write_tokens"]:,} cache-write · {tot["cache_read_tokens"]:,} cache-read · subscription quota, not API dollars',
        },
        {
            'label': 'Median wall time per brain',
            'value': f.med_build,
            'fmt': 'dur',
            'sub': f'median {f.med_tok:,.0f} output tokens' if f.med_tok else '',
        },
        {
            'label': 'Claude week burned per brain',
            'value': f.week_pct,
            'fmt': 'pct',
            'sub': _meter_sub(f),
        },
        {
            'label': 'Song briefs banked',
            'value': sc['built'],
            'fmt': 'int',
            'sub': 'the song workflow makes no Claude calls — briefs only, picked by the local model',
        },
    ]


def _current_facts(f: BankFigures):
    """Where the two banks stand right now, and what the builder is doing."""
    c, sc, state = f.counts, f.songs_counts, f.state
    return [
        {
            'label': 'Documentary bank',
            'value': f.pct_done,
            'fmt': 'pct',
            'sub': f'{c["built"]} of {f.dt} · {f.remaining} to go',
        },
        {
            'label': 'Song bank',
            'value': round(100.0 * min(sc['built'], f.st_target) / f.st_target, 1) if f.st_target else None,
            'fmt': 'pct',
            'sub': f'{sc["built"]} of {f.st_target}',
        },
        {
            'label': 'Builder',
            'value': ('ON' if f.on else ('paused' if state.get('paused') else 'off')),
            'fmt': 'text',
            'sub': f.note or 'no gate held',
        },
        {
            'label': 'Recording in flight',
            'value': ((state.get('documentary') or {}).get('current') or {}).get('topic') or 'none',
            'fmt': 'text',
            'sub': 'one brain run at a time is the house rule',
        },
    ]


def _future_facts(f: BankFigures):
    """What filling the rest of the bank still costs — each entry only when it is measurable."""
    fc = f.fc
    out = []
    if f.hours_left:
        out.append(
            {
                'label': 'Machine hours still to run',
                'value': f.hours_left,
                'fmt': 'hours',
                'sub': f'{f.remaining} brains × median {f.med_build / 60:.0f} min, back to back',
            }
        )
    if f.tokens_left:
        out.append(
            {
                'label': 'Output tokens still to spend',
                'value': f.tokens_left,
                'fmt': 'int',
                'sub': f'{f.remaining} recordings at the median',
            }
        )
    if f.weeks_needed:
        out.append(
            {
                'label': 'Claude weeks of quota still needed',
                'value': f.weeks_needed,
                'fmt': 'num',
                'sub': f'{f.remaining} brains × {f.week_pct:g} % of the 7-day meter — the builder holds at the ceiling and resumes at each reset',
            }
        )
    if fc:
        out.append(
            {
                'label': 'Brains per day at the current rate',
                'value': round(fc['values'][-1], 2),
                'fmt': 'num',
                'sub': f'slope {fc["slope_per_day"]:+.3f}/day · r² {fc["r2"]} · {fc["n"]} days',
            }
        )
    return out + [
        {
            'label': 'Episodes the bank can render with no subscription',
            'value': f.counts['ready'],
            'fmt': 'int',
            'sub': 'ready entries; each is consumed once by the documentary batcher',
        }
    ]


def facts_block(f: BankFigures):
    """The card's three fact columns: what was recorded, where it stands, what is left to pay."""
    return {
        'historical': _historical_facts(f),
        'current': _current_facts(f),
        'future': _future_facts(f),
    }


def _replay_note(f: BankFigures):
    """The replay line: how many banked turns answered from the bank, and the tokens not bought again."""
    tot = f.totals
    return (
        f'Replay so far: {f.hits} of {f.hits + tot["replay_misses"]} banked turns answered from the bank'
        + (f' ({f.hit_rate:.0f} % hit rate)' if f.hit_rate is not None else '')
        + f', {tot["tokens_saved"]:,} output tokens not bought again.'
    )


def _live_calls_note(f: BankFigures):
    """Why a replayed episode still makes live calls — or that nothing has been replayed yet."""
    if not f.live_per:
        return (
            'No entry has been replayed into an episode yet, so there is no measured saving on this card '
            '— only the recording cost.'
        )
    return (
        'Each replayed episode still made '
        + f'{f.live_per:g}'
        + ' live subscription calls on average: the bank holds the TEXT calls of the brain, '
        "while the render's vision judges (typography, anatomy, era) look at frames that do not exist until the render runs. "
        'Those sites fall back to the local judges when a turn is refused.'
    )


def notes_block(f: BankFigures):
    """The footnotes: replay outcome, live calls, and what this card does and does not count."""
    return [
        _replay_note(f),
        _live_calls_note(f),
        'A brain run is charted as its own kind ("Documentary brain (pre-emptive bank)") and is never counted as a finished episode: it stops before the first image.',
        'Tokens here are subscription quota, not billed dollars. The money cards price only paid-API work.',
        'Entry by entry — topic, turns, tokens, wall time and replay outcome — is the "Pre-emptive bank build" card on the Test Data tab.',
    ]
