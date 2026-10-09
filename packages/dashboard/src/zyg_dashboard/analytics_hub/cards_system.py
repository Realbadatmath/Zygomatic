# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Cards 6-7: system utilisation (sysusage + telemetry) and yield / wasted compute."""

from __future__ import annotations

from datetime import datetime
from zyg_dashboard import metrics_hub as mh

from .constants import CONTENT_KINDS, DAY, GPU_BUSY_UTIL
from .helpers import _bucket_series, _daily_keys, _day, _daykey, _delta, _fc_bucketed, _forecast, _week_start
from .sysusage import _sysusage_days, telemetry_days


def _card_system(
    *,
    active_h,
    bucket,
    days,
    earliest,
    fkeys,
    keys,
    now,
    run_hours,
    scen_util,
    scenario_hours,
    since,
    today,
    trend_keys,
    weekly,
):
    # ── 6 system utilisation ──────────────────────────────────────────────────
    sys_days = _sysusage_days()
    tel_days, tel_files = telemetry_days()
    util_day: dict = {}  # daykey -> {gpu_hours, busy_hours, cpu_mean, source, coverage_h, kwh}
    all_days = set(sys_days) | set(tel_days) | set(run_hours)
    for dk in all_days:
        s = sys_days.get(dk)
        t = tel_days.get(dk)
        rh = run_hours.get(dk, 0.0)
        if s and s['gpu_n']:
            util_day[dk] = {
                'gpu_hours': s['gpu_util_sum'] / 100 / 60,
                'busy_hours': s['busy_min'] / 60,
                'coverage_h': s['minutes'] / 60,
                'cpu_mean': s['cpu_sum'] / s['cpu_n'] if s['cpu_n'] else None,
                'ram_mean': s['ram_sum'] / s['ram_n'] if s['ram_n'] else None,
                'kwh': s['power_wh'] / 1000,
                'run_hours': rh,
                'source': 'sampler',
            }
        elif t and t['seconds']:
            util_day[dk] = {
                'gpu_hours': t['gpu_util_sum'] / 100 / 3600,
                'busy_hours': t['busy_s'] / 3600,
                'coverage_h': t['seconds'] / 3600,
                'cpu_mean': t['cpu_sum'] / t['seconds'] if t['seconds'] else None,
                'ram_mean': None,
                'kwh': t['power_wh'] / 1000,
                'run_hours': rh,
                'source': 'telemetry csv',
            }
        else:
            util_day[dk] = {
                'gpu_hours': None,
                'busy_hours': rh,
                'coverage_h': 0.0,
                'cpu_mean': None,
                'ram_mean': None,
                'kwh': None,
                'run_hours': rh,
                'source': 'run ledgers',
            }

    def util_pct(dks):
        """% of the period's hours the GPU was busy (busy hours / 24 h per day)."""
        if not dks:
            return None
        return round(sum((util_day.get(k) or {}).get('busy_hours') or 0 for k in dks) / (24 * len(dks)) * 100, 1)

    def gpu_load_pct(dks):
        vals = [
            (util_day[k]['gpu_hours'], util_day[k]['coverage_h'])
            for k in dks
            if k in util_day and util_day[k]['gpu_hours'] is not None
        ]
        if not vals:
            return None
        cov = sum(c for _, c in vals)
        return round(sum(g for g, _ in vals) / cov * 100, 1) if cov else None

    days_in_window = [
        k
        for k in _daily_keys(now, days if days else max(1, (int((now - earliest) / DAY) + 1) if earliest else 1))
        if k in util_day or True
    ]
    busy_series = _bucket_series({k: v['busy_hours'] for k, v in util_day.items()}, keys, weekly)
    gpu_series = _bucket_series(
        {k: v['gpu_hours'] for k, v in util_day.items() if v['gpu_hours'] is not None}, keys, weekly
    )
    cov_series = _bucket_series({k: v['coverage_h'] for k, v in util_day.items()}, keys, weekly)
    src_counts: dict = {}
    for k in days_in_window:
        src = (util_day.get(k) or {}).get('source', 'no data')
        src_counts[src] = src_counts.get(src, 0) + 1
    last7_keys = _daily_keys(now, 7)
    last30_keys = _daily_keys(now, 30)
    this_week = [k for k in last7_keys]
    month_keys = [k for k in _daily_keys(now, _day(now).day)]
    busy_fc = _forecast(
        [util_day.get(k, {}).get('busy_hours') if k in util_day else 0.0 for k in trend_keys], floor=0.0, cap=24.0
    )
    card_system = {
        'id': 'system_usage',
        'lane': 'capacity',
        'title': 'System utilisation',
        'question': "What share of the machine's hours is actually working — per day, week, month — and what would the approval queue need?",
        'headline': {
            'value': util_pct(last7_keys),
            'fmt': 'pct',
            'label': 'GPU busy share, last 7 days',
            'sub': f'today {util_pct([today])} % · this month {util_pct(month_keys)} % · load while busy {gpu_load_pct(last7_keys)} %',
        },
        'delta': {
            'pct': _delta(util_pct(last7_keys), util_pct(_daily_keys(now, 14)[:7])),
            'label': 'busy share, last 7 d vs the 7 before',
            'good_when': 'up',
        },
        'chart': {
            'kind': 'columns',
            'bucket': bucket,
            'keys': keys,
            'y': 'hours',
            'stacked': False,
            'title': 'GPU busy hours per '
            + bucket
            + f' (mean utilisation ≥ {GPU_BUSY_UTIL:g} %), with the measured GPU-hours and the coverage of the samples',
            'series': [{'id': 'busy', 'label': 'GPU busy hours', 'values': busy_series}],
            'lines': [
                {'id': 'gpu_hours', 'label': 'GPU-hours (utilisation-weighted)', 'values': gpu_series},
                {'id': 'coverage', 'label': 'Hours with samples', 'values': cov_series, 'style': 'thin'},
            ],
            'ceiling': {'label': 'Hours in the period', 'value': 24 * (7 if weekly else 1)},
            'forecast': (
                [
                    {
                        'id': 'trend',
                        'label': 'Busy hours trend',
                        **_fc_bucketed(busy_fc, fkeys, weekly, 'sum'),
                        'style': 'forecast',
                        'slope_per_day': busy_fc['slope_per_day'],
                        'r2': busy_fc['r2'],
                        'n': busy_fc['n'],
                    }
                ]
                if busy_fc
                else []
            )
            + [
                {
                    'id': 'scenario',
                    'label': 'Every toggle on',
                    'keys': (
                        fkeys
                        if not weekly
                        else sorted({_week_start(datetime.fromisoformat(k).date()).isoformat() for k in fkeys})
                    ),
                    'values': [round(min(scenario_hours, active_h) * (7 if weekly else 1), 2)]
                    * (
                        len(fkeys)
                        if not weekly
                        else len({_week_start(datetime.fromisoformat(k).date()).isoformat() for k in fkeys})
                    ),
                    'style': 'scenario',
                }
            ],
        },
        'facts': {
            'historical': [
                {
                    'label': 'Busy share, last 30 days',
                    'value': util_pct(last30_keys),
                    'fmt': 'pct',
                    'sub': f'{sum((util_day.get(k) or {}).get("busy_hours") or 0 for k in last30_keys):.1f} busy h of {24 * 30} h',
                },
                {
                    'label': 'Busy share, selected range (' + ('all time' if not days else f'{days} d') + ')',
                    'value': util_pct(days_in_window),
                    'fmt': 'pct',
                    'sub': 'source per day: '
                    + ', '.join(f'{k} ×{n}' for k, n in sorted(src_counts.items(), key=lambda kv: -kv[1])),
                },
                {
                    'label': 'Telemetry CSV days',
                    'value': len(tel_days),
                    'fmt': 'int',
                    'sub': f'{tel_files} per-run CSV files, 2026-03 .. 2026-08, written only while a pipeline ran',
                },
            ],
            'current': [
                {
                    'label': 'Today',
                    'value': util_pct([today]),
                    'fmt': 'pct',
                    'sub': f'{(util_day.get(today) or {}).get("busy_hours") or 0:.2f} busy h so far · source {(util_day.get(today) or {}).get("source", "no data")}',
                },
                {
                    'label': 'This week (7 d)',
                    'value': util_pct(this_week),
                    'fmt': 'pct',
                    'sub': f'mean GPU load while sampled {gpu_load_pct(this_week)} %',
                },
                {
                    'label': 'This month',
                    'value': util_pct(month_keys),
                    'fmt': 'pct',
                    'sub': f'{len(month_keys)} days so far',
                },
                {
                    'label': 'CPU mean, last 7 d',
                    'value': (lambda v: round(sum(v) / len(v), 1) if v else None)(
                        [
                            util_day[k]['cpu_mean']
                            for k in last7_keys
                            if k in util_day and util_day[k]['cpu_mean'] is not None
                        ]
                    ),
                    'fmt': 'pct',
                    'sub': 'of 24 cores, sampled minutes only',
                },
                {
                    'label': 'Sampler minutes today',
                    'value': (sys_days.get(today) or {}).get('minutes', 0),
                    'fmt': 'int',
                    'sub': 'zyg-sysusage.service, one row per minute',
                },
            ],
            'future': [
                {
                    'label': 'Every toggle on',
                    'value': round(scen_util, 1) if scen_util is not None else None,
                    'fmt': 'pct',
                    'sub': f'{scenario_hours:.1f} h of pipeline work per day'
                    + (' — more than a day: the queue carries over' if scenario_hours > active_h else ''),
                },
                {
                    'label': 'Per week, every toggle on',
                    'value': round(min(scenario_hours, active_h) * 7, 1),
                    'fmt': 'hours',
                    'sub': 'capped at the day',
                },
                {
                    'label': 'Per month, every toggle on',
                    'value': round(min(scenario_hours, active_h) * 30.44, 1),
                    'fmt': 'hours',
                    'sub': 'capped at the day',
                },
            ]
            + (
                [
                    {
                        'label': 'Busy hours per day in 30 d (trend)',
                        'value': busy_fc['values'][-1],
                        'fmt': 'hours',
                        'sub': f'slope {busy_fc["slope_per_day"]:+.3f} h/day · r² {busy_fc["r2"]}',
                    }
                ]
                if busy_fc
                else []
            ),
        },
        'table': {
            'cols': [
                'Day',
                'Busy h',
                'GPU-hours',
                'Sampled h',
                'CPU mean',
                'RAM mean',
                'kWh (GPU)',
                'Run-ledger h',
                'Source',
            ],
            'rows': [
                [
                    k,
                    {'v': u['busy_hours'], 'fmt': 'hours'},
                    {'v': u['gpu_hours'], 'fmt': 'hours'},
                    {'v': u['coverage_h'], 'fmt': 'hours'},
                    {'v': u['cpu_mean'], 'fmt': 'pct'},
                    {'v': u['ram_mean'], 'fmt': 'pct'},
                    {'v': u['kwh'], 'fmt': 'kwh'},
                    {'v': u['run_hours'], 'fmt': 'hours'},
                    u['source'],
                ]
                for k, u in sorted(util_day.items(), reverse=True)
                if (since is None or mh._ts(k + 'T12:00:00') >= since)
            ][:120],
        },
        'notes': [
            f"A minute is busy when the GPU's mean utilisation is ≥ {GPU_BUSY_UTIL:g} % (zyg-sysusage.service, one row per minute since 2026-09-18). "
            'GPU-hours weight every minute by its utilisation: 24 h at 50 % = 12 GPU-hours.',
            "Before the sampler: the GUI's telemetry CSVs, written per second but only while a clipfarm / crime / scholarly pipeline ran, so those days show the busy time of those runs and nothing about the idle rest. "
            'Days with neither source fall back to the run ledgers (union of run intervals), which miss agent sessions and ad-hoc GPU work.',
            'Utilisation of the machine, not of a quota: the Claude subscription meter is its own card.',
        ],
    }
    return card_system, last30_keys, last7_keys, sys_days, tel_days, util_day


def _card_yield(*, bucket, content, d14, d7, d8, daily_map, days, fkeys, keys, toggles, trend_keys, weekly, win):
    # ── 7 yield & wasted compute ──────────────────────────────────────────────
    decided = [r for r in content if r['status'] in ('completed', 'failed')]
    succ_series = []
    bc: dict = {}
    for r in decided:
        b = bc.setdefault(mh._bucket_of(r['t'], weekly), [0, 0])
        b[0] += 1 if r['status'] == 'completed' else 0
        b[1] += 1
    succ_series.append(
        {
            'id': 'success',
            'label': 'Success rate',
            'values': [round(bc[k][0] / bc[k][1] * 100, 1) if bc.get(k) else None for k in keys],
        }
    )
    failed = [r for r in content if r['status'] == 'failed']
    wasted_h = daily_map(failed, lambda r: (r['duration_s'] or 0) / 3600)
    wasted_usd = daily_map(failed, lambda r: r['api_cost_usd'])
    dm: dict = {}
    for r in decided:
        b = dm.setdefault(_daykey(r['t']), [0, 0])
        b[0] += 1 if r['status'] == 'completed' else 0
        b[1] += 1
    succ_fc = _forecast([dm[k][0] / dm[k][1] * 100 if k in dm else None for k in trend_keys], floor=0.0, cap=100.0)
    by_kind_fail = []
    for kind in CONTENT_KINDS:
        rs = [r for r in decided if r['kind'] == kind]
        if not rs:
            continue
        f = [r for r in rs if r['status'] == 'failed']
        by_kind_fail.append(
            {
                'label': CONTENT_KINDS[kind],
                'decided': len(rs),
                'failed': len(f),
                'rate': round((len(rs) - len(f)) / len(rs) * 100, 1),
                'wasted_h': round(sum((r['duration_s'] or 0) for r in f) / 3600, 2),
                'wasted_usd': round(sum(r['api_cost_usd'] for r in f), 3),
            }
        )
    win_dec = [r for r in win if r['is_content'] and r['status'] in ('completed', 'failed')]
    card_yield = {
        'id': 'yield',
        'lane': 'quality',
        'title': 'Yield and wasted compute',
        'question': 'How much of what starts actually finishes, and what do the failures burn?',
        'headline': {
            'value': mh._rate(sum(1 for r in win_dec if r['status'] == 'completed'), len(win_dec)),
            'fmt': 'pct',
            'label': 'content success rate · ' + ('all time' if not days else f'last {days} days'),
            'sub': f'{sum(wasted_h.values()):.1f} h and ${sum(wasted_usd.values()):.2f} in failed runs, all time',
        },
        'delta': {
            'pct': _delta(
                mh._rate(
                    sum(1 for r in decided if r['status'] == 'completed' and _daykey(r['t']) >= d7),
                    sum(1 for r in decided if _daykey(r['t']) >= d7),
                ),
                mh._rate(
                    sum(1 for r in decided if r['status'] == 'completed' and d14 <= _daykey(r['t']) <= d8),
                    sum(1 for r in decided if d14 <= _daykey(r['t']) <= d8),
                ),
            ),
            'label': 'success rate, last 7 d vs the 7 before',
            'good_when': 'up',
        },
        'chart': {
            'kind': 'line',
            'bucket': bucket,
            'keys': keys,
            'series': succ_series,
            'y': 'pct',
            'title': 'Content success rate per ' + bucket + ' (completed ÷ decided)',
            'forecast': (
                [
                    {
                        'id': 'trend',
                        'label': 'Trend',
                        **_fc_bucketed(succ_fc, fkeys, weekly, 'mean'),
                        'slope_per_day': succ_fc['slope_per_day'],
                        'r2': succ_fc['r2'],
                        'n': succ_fc['n'],
                    }
                ]
                if succ_fc
                else []
            ),
            'secondary': {
                'label': 'Hours lost in failed runs',
                'values': _bucket_series(wasted_h, keys, weekly),
                'y': 'hours',
                'kind': 'columns',
            },
        },
        'facts': {
            'historical': [
                {
                    'label': k['label'],
                    'value': k['rate'],
                    'fmt': 'pct',
                    'sub': f'{k["failed"]} failed of {k["decided"]} decided · {k["wasted_h"]} h · ${k["wasted_usd"]}',
                }
                for k in by_kind_fail
            ],
            'current': [
                {
                    'label': 'Decided in the window',
                    'value': len(win_dec),
                    'fmt': 'int',
                    'sub': f'{sum(1 for r in win_dec if r["status"] == "failed")} failed',
                },
                {
                    'label': 'Stale claims (content)',
                    'value': sum(1 for r in content if r['status'] == 'stale'),
                    'fmt': 'int',
                    'sub': 'still claim to run, no write for 12 h+',
                },
            ],
            'future': (
                [
                    {
                        'label': 'Success rate in 30 d (trend)',
                        'value': round(succ_fc['values'][-1], 1),
                        'fmt': 'pct',
                        'sub': f'slope {succ_fc["slope_per_day"]:+.2f} pts/day · r² {succ_fc["r2"]}',
                    }
                ]
                if succ_fc
                else []
            )
            + [
                {
                    'label': 'Expected loss per day, every toggle on',
                    'value': round(
                        sum(
                            t['per_day']
                            * (
                                1
                                - (
                                    next(
                                        (k['rate'] for k in by_kind_fail if k['label'] == CONTENT_KINDS.get(t['kind'])),
                                        100,
                                    )
                                    or 100
                                )
                                / 100
                            )
                            for t in toggles
                        ),
                        2,
                    ),
                    'fmt': 'num',
                    'sub': "items per day expected to fail at each pipeline's all-time rate",
                }
            ],
        },
        'table': {
            'cols': ['Pipeline', 'Decided', 'Failed', 'Success', 'Hours lost', 'API $ lost'],
            'rows': [
                [
                    k['label'],
                    k['decided'],
                    k['failed'],
                    {'v': k['rate'], 'fmt': 'pct'},
                    {'v': k['wasted_h'], 'fmt': 'hours'},
                    {'v': k['wasted_usd'], 'fmt': 'usd'},
                ]
                for k in by_kind_fail
            ],
        },
        'notes': [
            'Success = completed ÷ (completed + failed). Stale, cancelled and unrecorded runs are neither, and are listed beside it.',
            'Hours lost = the wall time of failed runs (recorded or inferred); $ lost = API calls attributed to them.',
        ],
    }
    return card_yield
