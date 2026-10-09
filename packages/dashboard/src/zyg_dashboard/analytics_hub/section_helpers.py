# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The stages of `section_analytics`, extracted so each one can be read and tested alone.

`build_context` does everything the payload derives before the first card exists — the
window, the run cohorts, the day keys, the per-kind unit times, the Approval-Queue
toggles and the three series callables every card builder takes. The `add_*` stages then
build the cards in the original order onto that same context object, and `envelope`
assembles the response. Nothing here changes behaviour: the stages are the sections of
the old single function, in the same sequence, with their intermediate series carried on
the context instead of in locals.
"""

from __future__ import annotations

import time
from datetime import timedelta
from types import SimpleNamespace

from zyg_dashboard import metrics_hub as mh

from .approval import approval_queue
from .arch_studio import arch_studio_card
from .cards_capacity_income import _card_capacity, _card_income
from .cards_llm_energy import _card_energy, _card_mix, _card_sub
from .cards_production import _card_cost, _card_times, _card_volume
from .cards_system import _card_system, _card_yield
from .config import load_config
from .constants import ASSET_KINDS, CONTENT_KINDS, DAY, HORIZON_DAYS, TREND_DAYS
from .helpers import _bucket_series, _daily_keys, _day, _daykey, _forecast_keys, _median
from .preempt_bank import preempt_bank_card
from .runs import enrich_runs
from .sources import _sources, _version

import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)

LANES = [
    {'id': 'production', 'label': 'Production'},
    {'id': 'money', 'label': 'Cost & income'},
    {'id': 'capacity', 'label': 'Capacity & system'},
    {'id': 'quality', 'label': 'Quality'},
]


def _daily_map(rows, val=lambda r: 1.0, key='t'):
    """Sum `val(row)` per calendar day: rows → {'YYYY-MM-DD': float}.

    `key` names the row field holding the epoch timestamp; `val` defaults to counting.
    """
    m: dict = {}
    for r in rows:
        dk = _daykey(r[key])
        m[dk] = m.get(dk, 0.0) + val(r)
    return m


def _trend_series(m, trend_keys):
    """A daily map read out along `trend_keys`, missing days as 0.0 — the forecast input."""
    return [m.get(k, 0.0) for k in trend_keys]


def _window_sum(m, d0, d1):
    """Total of a daily map over the inclusive day-key range `d0`..`d1`."""
    return sum(v for k, v in m.items() if d0 <= k <= d1)


def unit_times(runs, d90):
    """Per-kind wall times: (unit_s, times_by_kind).

    `unit_s` is {kind: recent p50 seconds} — the number the Approval-Queue scenario
    plans with; `times_by_kind` is one row per kind that has at least one timed
    completed run, carrying recent and all-time percentiles, the duration-basis
    histogram and the count of completed-but-untimed runs. Kinds with no timed run at
    all are absent from both. `d90` is the epoch cutoff for "recent"; a kind with no
    recent run falls back to its whole history rather than dropping out.
    """
    unit_s, times_by_kind = {}, []
    for kind, label in list(CONTENT_KINDS.items()) + list(ASSET_KINDS.items()):
        rs = [r for r in runs if r['kind'] == kind and r['status'] == 'completed' and r['duration_s']]
        if not rs:
            continue
        recent = [r['duration_s'] for r in rs if r['t'] >= d90] or [r['duration_s'] for r in rs]
        p50_recent = _median(recent)
        unit_s[kind] = p50_recent
        basis = {}
        for r in rs:
            basis[r['duration_basis']] = basis.get(r['duration_basis'], 0) + 1
        times_by_kind.append(
            {
                'kind': kind,
                'label': label,
                'is_content': kind in CONTENT_KINDS,
                'timed': len(rs),
                'p50_recent_s': p50_recent,
                'p90_recent_s': mh._pct(recent, 0.9),
                'recent_n': len(recent),
                'p50_all_s': _median([r['duration_s'] for r in rs]),
                'basis': basis,
                'untimed_completed': sum(
                    1 for r in runs if r['kind'] == kind and r['status'] == 'completed' and not r['duration_s']
                ),
            }
        )
    return unit_s, times_by_kind


def build_context(days=30, now=None):
    """Everything the payload derives before the first card: the shared card context.

    Reads the config, the enriched runs and the LLM ledger once, then derives the
    bucketing window (`since`, `keys`, `weekly`, `bucket`), the comparison day keys
    (`d7`/`d8`/`d14` for week-over-week, `d90` for "recent"), the run cohorts
    (`win`, `content`, `completed`, `families`), the per-kind unit times and the
    Approval-Queue toggles with their scenario totals. The three series callables
    (`daily_map`, `trend_series`, `window_sum`) are bound here because the card
    builders take them as arguments. Returns a SimpleNamespace the `add_*` stages
    extend in place.
    """
    now = now or time.time()
    cfg = load_config()
    runs, meta, llm = enrich_runs(now)
    since = mh._window(days, now)
    earliest = min((r['t'] for r in runs), default=None)
    keys, weekly = mh._bucketing(since, now, earliest)
    trend_keys = _daily_keys(now, TREND_DAYS)
    content = [r for r in runs if r['is_content']]
    completed = [r for r in content if r['status'] == 'completed']
    d90 = now - 90 * DAY
    unit_s, times_by_kind = unit_times(runs, d90)
    toggles = approval_queue(unit_s)
    return SimpleNamespace(
        now=now,
        days=days,
        cfg=cfg,
        runs=runs,
        meta=meta,
        llm=llm,
        since=since,
        earliest=earliest,
        keys=keys,
        weekly=weekly,
        bucket='week' if weekly else 'day',
        trend_keys=trend_keys,
        fkeys=_forecast_keys(now),
        today=_daykey(now),
        win=[r for r in runs if since is None or r['t'] >= since],
        content=content,
        completed=completed,
        families=sorted({r['kind'] for r in completed}, key=lambda k: -sum(1 for r in completed if r['kind'] == k)),
        d7=(_day(now) - timedelta(days=6)).isoformat(),
        d14=(_day(now) - timedelta(days=13)).isoformat(),
        d8=(_day(now) - timedelta(days=7)).isoformat(),
        d90=d90,
        unit_s=unit_s,
        times_by_kind=times_by_kind,
        toggles=toggles,
        scenario_per_day=sum(t['per_day'] for t in toggles),
        scenario_hours=sum(t['hours_per_day'] or 0 for t in toggles),
        scenario_missing=[t['label'] for t in toggles if t['hours_per_day'] is None],
        active_h=cfg['active_hours_per_day'],
        daily_map=_daily_map,
        trend_series=lambda m: _trend_series(m, trend_keys),
        window_sum=_window_sum,
    )


def add_production_cards(c):
    """Build the times, cost and volume cards onto the context, in that order.

    Also carries forward the series the later lanes reuse: `api_day` and `done_day`
    (daily cost and completions), `total_api`, `win_done` and the volume forecast
    `vol_fc`.
    """
    c.card_times = _card_times(
        bucket=c.bucket,
        completed=c.completed,
        d14=c.d14,
        d7=c.d7,
        d8=c.d8,
        days=c.days,
        families=c.families,
        fkeys=c.fkeys,
        keys=c.keys,
        scenario_hours=c.scenario_hours,
        scenario_per_day=c.scenario_per_day,
        times_by_kind=c.times_by_kind,
        toggles=c.toggles,
        trend_keys=c.trend_keys,
        weekly=c.weekly,
        win=c.win,
    )
    c.api_day, c.card_cost, c.done_day, c.total_api, c.win_done = _card_cost(
        bucket=c.bucket,
        completed=c.completed,
        content=c.content,
        d14=c.d14,
        d7=c.d7,
        d8=c.d8,
        d90=c.d90,
        daily_map=c.daily_map,
        days=c.days,
        families=c.families,
        fkeys=c.fkeys,
        keys=c.keys,
        llm=c.llm,
        today=c.today,
        toggles=c.toggles,
        trend_keys=c.trend_keys,
        trend_series=c.trend_series,
        weekly=c.weekly,
        win=c.win,
        window_sum=c.window_sum,
    )
    c.card_volume, c.vol_fc = _card_volume(
        bucket=c.bucket,
        completed=c.completed,
        content=c.content,
        d14=c.d14,
        d7=c.d7,
        d8=c.d8,
        daily_map=c.daily_map,
        days=c.days,
        done_day=c.done_day,
        families=c.families,
        fkeys=c.fkeys,
        keys=c.keys,
        now=c.now,
        runs=c.runs,
        scenario_per_day=c.scenario_per_day,
        today=c.today,
        toggles=c.toggles,
        trend_series=c.trend_series,
        weekly=c.weekly,
        win_done=c.win_done,
        window_sum=c.window_sum,
    )


def add_capacity_income_cards(c):
    """Build the capacity card (and its `run_hours` / `scen_util` readouts) then income.

    Order matters: income reports the scenario's cost against the capacity the
    capacity card just measured, and the envelope reports `scen_util`.
    """
    c.card_capacity, c.run_hours, c.scen_util = _card_capacity(
        active_h=c.active_h,
        bucket=c.bucket,
        completed=c.completed,
        content=c.content,
        fkeys=c.fkeys,
        keys=c.keys,
        now=c.now,
        runs=c.runs,
        scenario_hours=c.scenario_hours,
        scenario_missing=c.scenario_missing,
        scenario_per_day=c.scenario_per_day,
        times_by_kind=c.times_by_kind,
        toggles=c.toggles,
        weekly=c.weekly,
    )
    c.card_income = _card_income(
        api_day=c.api_day,
        bucket=c.bucket,
        cfg=c.cfg,
        completed=c.completed,
        d14=c.d14,
        d7=c.d7,
        d8=c.d8,
        daily_map=c.daily_map,
        days=c.days,
        done_day=c.done_day,
        families=c.families,
        fkeys=c.fkeys,
        keys=c.keys,
        now=c.now,
        scenario_per_day=c.scenario_per_day,
        today=c.today,
        total_api=c.total_api,
        vol_fc=c.vol_fc,
        weekly=c.weekly,
        win_done=c.win_done,
        window_sum=c.window_sum,
    )


def add_system_cards(c):
    """Build system, yield, mix, subscription and energy — in that order.

    The system card is first because it owns the day-key sets (`last7_keys`,
    `last30_keys`) and the utilisation series the energy card bills against, and it
    reports the sysusage/telemetry day coverage the envelope quotes.
    """
    (
        c.card_system,
        c.last30_keys,
        c.last7_keys,
        c.sys_days,
        c.tel_days,
        c.util_day,
    ) = _card_system(
        active_h=c.active_h,
        bucket=c.bucket,
        days=c.days,
        earliest=c.earliest,
        fkeys=c.fkeys,
        keys=c.keys,
        now=c.now,
        run_hours=c.run_hours,
        scen_util=c.scen_util,
        scenario_hours=c.scenario_hours,
        since=c.since,
        today=c.today,
        trend_keys=c.trend_keys,
        weekly=c.weekly,
    )
    c.card_yield = _card_yield(
        bucket=c.bucket,
        content=c.content,
        d14=c.d14,
        d7=c.d7,
        d8=c.d8,
        daily_map=c.daily_map,
        days=c.days,
        fkeys=c.fkeys,
        keys=c.keys,
        toggles=c.toggles,
        trend_keys=c.trend_keys,
        weekly=c.weekly,
        win=c.win,
    )
    c.card_mix = _card_mix(
        bucket=c.bucket,
        d14=c.d14,
        d7=c.d7,
        d8=c.d8,
        days=c.days,
        fkeys=c.fkeys,
        keys=c.keys,
        llm=c.llm,
        since=c.since,
        today=c.today,
        total_api=c.total_api,
        trend_series=c.trend_series,
        weekly=c.weekly,
        window_sum=c.window_sum,
    )
    c.card_sub = _card_sub(
        bucket=c.bucket,
        keys=c.keys,
        now=c.now,
        weekly=c.weekly,
    )
    c.card_energy = _card_energy(
        active_h=c.active_h,
        bucket=c.bucket,
        cfg=c.cfg,
        done_day=c.done_day,
        keys=c.keys,
        last30_keys=c.last30_keys,
        last7_keys=c.last7_keys,
        now=c.now,
        scenario_hours=c.scenario_hours,
        today=c.today,
        util_day=c.util_day,
        weekly=c.weekly,
    )


def backlog_card(c):
    """Card 11 — what the three Approval-Queue toggles have queued, and for how long.

    Reads only the toggles and the completed runs: the headline counts scheduled plus
    in-production items and prices them at each toggle's recent median wall time, the
    chart stacks completions per bucket by the pipeline each toggle drives, and the
    table repeats the batch counters the Approval Queue board writes.
    """
    queued_items = sum(t['batch']['scheduled'] + t['batch']['in_production'] for t in c.toggles)
    queued_hours = sum(
        (t['batch']['scheduled'] + t['batch']['in_production']) * (t['unit_s'] or 0) / 3600 for t in c.toggles
    )
    return {
        'id': 'backlog',
        'lane': 'production',
        'title': 'Approval Queue backlog',
        'question': 'What is queued right now, and how long will the machine need for it?',
        'headline': {
            'value': queued_items,
            'fmt': 'int',
            'label': 'items scheduled or in production across the three toggles',
            'sub': f'≈ {queued_hours:.1f} h of pipeline time at recent median wall times',
        },
        'delta': {'pct': None, 'label': ''},
        'chart': {
            'kind': 'columns',
            'bucket': c.bucket,
            'keys': c.keys,
            'stacked': True,
            'y': 'int',
            'title': 'Completed per ' + c.bucket + ' by the pipelines the toggles drive',
            'series': [
                {
                    'id': t['kind'],
                    'label': t['label'],
                    'values': [
                        int(x)
                        for x in _bucket_series(
                            c.daily_map([r for r in c.completed if r['kind'] == t['kind']]), c.keys, c.weekly
                        )
                    ],
                }
                for t in c.toggles
            ],
        },
        'facts': {
            'historical': [
                {
                    'label': t['label'],
                    'value': sum(1 for r in c.completed if r['kind'] == t['kind']),
                    'fmt': 'int',
                    'sub': 'completed all time',
                }
                for t in c.toggles
            ],
            'current': [
                {
                    'label': t['label'],
                    'value': 'ON' if t['enabled'] else 'off',
                    'fmt': 'text',
                    'sub': f'batch: {t["batch"]["scheduled"]} scheduled · {t["batch"]["in_production"]} running · {t["batch"]["done"]} done · {t["batch"]["failed"]} failed',
                }
                for t in c.toggles
            ],
            'future': [
                {
                    'label': t['label'] + ' per day while on',
                    'value': t['per_day'],
                    'fmt': 'num',
                    'sub': f'{t["hours_per_day"]} h/day' if t['hours_per_day'] is not None else 'no unit time',
                }
                for t in c.toggles
            ],
        },
        'table': {
            'cols': ['Toggle', 'State', 'Scheduled', 'In production', 'Done', 'Failed', 'Unit time', 'Queued hours'],
            'rows': [
                [
                    t['label'],
                    'ON' if t['enabled'] else 'off',
                    t['batch']['scheduled'],
                    t['batch']['in_production'],
                    t['batch']['done'],
                    t['batch']['failed'],
                    {'v': t['unit_s'], 'fmt': 'dur'},
                    {
                        'v': (t['batch']['scheduled'] + t['batch']['in_production']) * (t['unit_s'] or 0) / 3600,
                        'fmt': 'hours',
                    },
                ]
                for t in c.toggles
            ],
        },
        'notes': [
            'Toggle state and batches are read from the same files the Approval Queue board writes, on every refresh; flip a toggle there and this card follows within one poll.'
        ],
    }


def add_optional_cards(c):
    """Build the two cards that are allowed to fail: arch_studio, then preempt_bank.

    Both read foreign state (the Arch Studio run tree, the pre-emption bank ledger), so
    one of them raising must not take the whole board down: the failure is printed and
    the card becomes None, which drops it from the lane.
    """
    args = (c.now, c.days, c.since, c.keys, c.weekly, c.bucket, c.trend_keys, c.fkeys, c.d7, c.d14, c.d8, c.today)
    try:
        c.card_arch = arch_studio_card(*args)
    except Exception as exc:  # noqa: BLE001 — one broken card must not take the board down
        _zyg_log.info(f'[ANALYTICS] arch_studio card failed: {exc}')
        c.card_arch = None
    try:
        c.card_preempt = preempt_bank_card(*args)
    except Exception as exc:  # noqa: BLE001 — one broken card must not take the board down
        _zyg_log.info(f'[ANALYTICS] preempt_bank card failed: {exc}')
        c.card_preempt = None


def envelope(c):
    """The response: the lanes, the cards in board order, and the payload's own metadata.

    Card order is the board's reading order (volume, times, backlog, the two optional
    cards, then the money / capacity / quality lanes); `data_version` is the stamp the
    front end polls on, and `coverage` says how much of the run history the numbers
    actually rest on.
    """
    sources = _sources(c.now)
    cards = (
        [c.card_volume, c.card_times, c.card_backlog]
        + ([c.card_preempt] if c.card_preempt else [])
        + ([c.card_arch] if c.card_arch else [])
        + [
            c.card_cost,
            c.card_income,
            c.card_mix,
            c.card_sub,
            c.card_capacity,
            c.card_system,
            c.card_energy,
            c.card_yield,
        ]
    )
    return {
        'lanes': [dict(lane) for lane in LANES],
        'cards': cards,
        'config': c.cfg,
        'toggles': c.toggles,
        'scenario': {
            'per_day': c.scenario_per_day,
            'hours_per_day': round(c.scenario_hours, 2),
            'missing_unit_times': c.scenario_missing,
            'utilisation_pct': round(c.scen_util, 1) if c.scen_util is not None else None,
        },
        'bucket': c.bucket,
        'keys': c.keys,
        'forecast_keys': c.fkeys,
        'horizon_days': HORIZON_DAYS,
        'trend_days': TREND_DAYS,
        'sources': sources,
        'data_version': _version(sources, c.cfg, c.toggles),
        'coverage': {
            'runs': len(c.runs),
            'content_runs': len(c.content),
            'completed_content': len(c.completed),
            'excluded_test_runs': c.meta['excluded_test_runs'],
            'excluded_synthesized': c.meta['excluded_synthesized'],
            'llm_rows': len(c.llm['rows']),
            'sysusage_days': len(c.sys_days),
            'telemetry_days': len(c.tel_days),
        },
    }
