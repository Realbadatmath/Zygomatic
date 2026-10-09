# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Cards 1-3: production times, token cost per content, production volume."""

from __future__ import annotations

from datetime import timedelta
from zyg_dashboard import metrics_hub as mh

from .constants import API, CONTENT_KINDS, TREND_DAYS
from .helpers import _bucket_series, _day, _daykey, _delta, _fc_bucketed, _forecast, _median


def _card_times(
    *,
    bucket,
    completed,
    d14,
    d7,
    d8,
    days,
    families,
    fkeys,
    keys,
    scenario_hours,
    scenario_per_day,
    times_by_kind,
    toggles,
    trend_keys,
    weekly,
    win,
):
    # ── 1 production times ────────────────────────────────────────────────────
    pt_series, pt_fc = [], []
    for kind in families[:6]:
        rs = [r for r in completed if r['kind'] == kind and r['duration_s']]
        by_bucket: dict = {}
        for r in rs:
            by_bucket.setdefault(mh._bucket_of(r['t'], weekly), []).append(r['duration_s'] / 60.0)
        vals = [round(_median(by_bucket[k]), 1) if by_bucket.get(k) else None for k in keys]
        if any(v is not None for v in vals):
            pt_series.append({'id': kind, 'label': CONTENT_KINDS[kind], 'values': vals, 'unit': 'min'})
        # trend from daily medians over TREND_DAYS
        dm: dict = {}
        for r in rs:
            dm.setdefault(_daykey(r['t']), []).append(r['duration_s'] / 60.0)
        fc = _forecast([_median(dm[k]) if k in dm else None for k in trend_keys], floor=0.5)
        if fc:
            pt_fc.append(
                {
                    'id': kind,
                    'label': CONTENT_KINDS[kind],
                    **_fc_bucketed(fc, fkeys, weekly, 'mean'),
                    'slope_per_day': fc['slope_per_day'],
                    'r2': fc['r2'],
                    'n': fc['n'],
                    'level_14d': fc['level_14d'],
                }
            )
    timed_win = [r for r in win if r['is_content'] and r['status'] == 'completed' and r['duration_s']]
    all_p50_win = _median([r['duration_s'] for r in timed_win])
    prev7 = [r['duration_s'] for r in completed if r['duration_s'] and d14 <= _daykey(r['t']) <= d8]
    last7 = [r['duration_s'] for r in completed if r['duration_s'] and _daykey(r['t']) >= d7]
    basis_counts: dict = {}
    for r in completed:
        basis_counts[r['duration_basis']] = basis_counts.get(r['duration_basis'], 0) + 1
    card_times = {
        'id': 'production_times',
        'lane': 'production',
        'title': 'Production times',
        'question': 'How long does one piece of content take, and where is that heading?',
        'headline': {
            'value': all_p50_win,
            'fmt': 'dur',
            'label': 'median wall time per content · ' + ('all time' if not days else f'last {days} days'),
        },
        'delta': {
            'pct': _delta(_median(last7), _median(prev7)),
            'label': 'median, last 7 d vs the 7 before',
            'good_when': 'down',
        },
        'chart': {
            'kind': 'line',
            'bucket': bucket,
            'keys': keys,
            'series': pt_series,
            'y': 'min',
            'forecast': pt_fc,
            'title': 'Median wall time per content, by pipeline (minutes)',
        },
        'facts': {
            'historical': [
                {
                    'label': t['label'],
                    'value': t['p50_all_s'],
                    'fmt': 'dur',
                    'sub': f'all-time median · {t["timed"]} timed runs',
                }
                for t in times_by_kind
                if t['is_content']
            ],
            'current': [
                {
                    'label': t['label'],
                    'value': t['p50_recent_s'],
                    'fmt': 'dur',
                    'sub': f'median of the last 90 d ({t["recent_n"]} runs) · p90 {mh._pct([t["p90_recent_s"]], 0.5) and round(t["p90_recent_s"])} s',
                }
                for t in times_by_kind
                if t['is_content']
            ],
            'future': [
                {
                    'label': f['label'],
                    'value': f['values'][-1] * 60 if f['values'] else None,
                    'fmt': 'dur',
                    'sub': f'trend in 30 d · slope {f["slope_per_day"]:+.2f} min/day · r² {f["r2"]}',
                }
                for f in pt_fc
            ]
            + [
                {
                    'label': "Tomorrow's approval batch, every toggle on",
                    'value': scenario_hours * 3600,
                    'fmt': 'dur',
                    'sub': f'{scenario_per_day:g} items · '
                    + (', '.join(f'{t["per_day"]:g}× {t["kind"]}' for t in toggles)),
                }
            ],
        },
        'table': {
            'cols': [
                'Pipeline',
                'Timed runs',
                'Median (recent)',
                'p90 (recent)',
                'Median (all)',
                'Untimed completed',
                'Duration basis',
            ],
            'rows': [
                [
                    t['label'],
                    t['timed'],
                    {'v': t['p50_recent_s'], 'fmt': 'dur'},
                    {'v': t['p90_recent_s'], 'fmt': 'dur'},
                    {'v': t['p50_all_s'], 'fmt': 'dur'},
                    t['untimed_completed'],
                    ', '.join(f'{k} ×{v}' for k, v in t['basis'].items()),
                ]
                for t in times_by_kind
            ],
        },
        'notes': [
            'Wall time = recorded stage timings or end stamp where the run wrote them; otherwise inferred from '
            'the last state write minus the start (kids music: start minus the first output file, because that '
            'state is written once, at the end). The basis is counted per pipeline in the table.',
            'Duration basis over completed content: ' + ', '.join(f'{k} ×{v}' for k, v in basis_counts.items()) + '.',
            'Forecast: '
            + (pt_fc[0]['label'] + ' — ' if pt_fc else '')
            + f'OLS trend on daily medians over the last {TREND_DAYS} days; the band is the 80 % residual interval. A trend with r² near 0 is a flat line with noise, not a prediction.',
        ],
    }
    return card_times


def _card_cost(
    *,
    bucket,
    completed,
    content,
    d14,
    d7,
    d8,
    d90,
    daily_map,
    days,
    families,
    fkeys,
    keys,
    llm,
    today,
    toggles,
    trend_keys,
    trend_series,
    weekly,
    win,
    window_sum,
):
    # ── 2 token cost per content ──────────────────────────────────────────────
    cost_day = daily_map([r for r in content], lambda r: r['api_cost_usd'])
    done_day = daily_map(completed)
    api_rows_all = [c for c in llm['rows'] if c['provider'] in API and c['cost'] and c['ts']]
    api_day: dict = {}
    for c in api_rows_all:
        dk = _daykey(c['ts'])
        api_day[dk] = api_day.get(dk, 0.0) + c['cost']
    attributed = sum(cost_day.values())
    total_api = sum(api_day.values())
    cpc_series, cpc_fc = [], []
    for kind in families[:6]:
        rs = [r for r in completed if r['kind'] == kind]
        bc: dict = {}
        for r in rs:
            b = bc.setdefault(mh._bucket_of(r['t'], weekly), [0.0, 0])
            b[0] += r['api_cost_usd']
            b[1] += 1
        vals = [round(bc[k][0] / bc[k][1], 4) if bc.get(k) else None for k in keys]
        if any(v for v in vals if v):
            cpc_series.append({'id': kind, 'label': CONTENT_KINDS[kind], 'values': vals})
        dm: dict = {}
        for r in rs:
            b = dm.setdefault(_daykey(r['t']), [0.0, 0])
            b[0] += r['api_cost_usd']
            b[1] += 1
        daily_cpc = [(dm[k][0] / dm[k][1]) if k in dm else None for k in trend_keys]
        fc = _forecast(daily_cpc, floor=0.0)
        if fc and any(v for v in fc['values']):
            cpc_fc.append(
                {
                    'id': kind,
                    'label': CONTENT_KINDS[kind],
                    **_fc_bucketed(fc, fkeys, weekly, 'mean'),
                    'slope_per_day': fc['slope_per_day'],
                    'r2': fc['r2'],
                    'n': fc['n'],
                    'level_14d': fc['level_14d'],
                }
            )
    per_kind_cost = []
    for kind in families:
        rs = [r for r in completed if r['kind'] == kind]
        rec = [r for r in rs if r['t'] >= d90] or rs
        per_kind_cost.append(
            {
                'kind': kind,
                'label': CONTENT_KINDS[kind],
                'n': len(rs),
                'avg_usd': round(sum(r['api_cost_usd'] for r in rs) / len(rs), 4) if rs else None,
                'recent_avg_usd': round(sum(r['api_cost_usd'] for r in rec) / len(rec), 4) if rec else None,
                'priced_runs': sum(1 for r in rs if r['api_cost_usd']),
                'tokens_avg': round(sum(r['llm_tokens'] for r in rs) / len(rs)) if rs else None,
            }
        )
    win_done = [r for r in win if r['is_content'] and r['status'] == 'completed']
    win_cpc = (sum(r['api_cost_usd'] for r in win_done) / len(win_done)) if win_done else None
    cost_fc = _forecast(trend_series(api_day), floor=0.0)
    scen_cost_day = sum(
        t['per_day'] * (next((k['recent_avg_usd'] for k in per_kind_cost if k['kind'] == t['kind']), 0) or 0)
        for t in toggles
    )
    toggle_volumes = ', '.join(f'{t["per_day"]:g}/day {t["kind"]}' for t in toggles)
    card_cost = {
        'id': 'token_cost',
        'lane': 'money',
        'title': 'Token cost per content',
        'question': 'What does one piece of content cost in paid LLM tokens, historically and ahead?',
        'headline': {
            'value': win_cpc,
            'fmt': 'usd',
            'label': 'API $ per completed content · ' + ('all time' if not days else f'last {days} days'),
        },
        'delta': {
            'pct': _delta(window_sum(api_day, d7, today), window_sum(api_day, d14, d8)),
            'label': 'API spend, last 7 d vs the 7 before',
            'good_when': 'down',
        },
        'chart': {
            'kind': 'line',
            'bucket': bucket,
            'keys': keys,
            'series': cpc_series,
            'y': 'usd',
            'forecast': cpc_fc,
            'title': 'API $ per completed content, by pipeline',
            'secondary': {
                'label': 'API spend (all calls)',
                'values': _bucket_series(api_day, keys, weekly),
                'y': 'usd',
                'kind': 'columns',
            },
        },
        'facts': {
            'historical': [
                {
                    'label': k['label'],
                    'value': k['avg_usd'],
                    'fmt': 'usd',
                    'sub': f'avg over {k["n"]} completed · {k["priced_runs"]} with attributed calls · ~{mh._num(k["tokens_avg"]) and int(k["tokens_avg"]):,} tokens',
                }
                for k in per_kind_cost
            ]
            + [
                {
                    'label': 'API spend, all time',
                    'value': round(total_api, 2),
                    'fmt': 'usd',
                    'sub': f'{round(attributed, 2)} attributed to a run id; the rest is unlabelled or ad-hoc calls',
                }
            ],
            'current': [
                {'label': k['label'], 'value': k['recent_avg_usd'], 'fmt': 'usd', 'sub': 'avg per content, last 90 d'}
                for k in per_kind_cost
            ]
            + [
                {
                    'label': 'API spend, last 7 days',
                    'value': round(window_sum(api_day, d7, today), 2),
                    'fmt': 'usd',
                    'sub': 'all Anthropic/OpenAI calls',
                }
            ],
            'future': (
                [
                    {
                        'label': 'API spend, next 30 d (trend)',
                        'value': round(sum(cost_fc['values']), 2),
                        'fmt': 'usd',
                        'sub': f'{cost_fc["method"]} · r² {cost_fc["r2"]}',
                    }
                ]
                if cost_fc
                else []
            )
            + [
                {
                    'label': 'API spend per day, every toggle on',
                    'value': round(scen_cost_day, 2),
                    'fmt': 'usd',
                    'sub': 'per-day volumes × recent avg $ per content of that pipeline',
                },
                {
                    'label': 'API spend per month, every toggle on',
                    'value': round(scen_cost_day * 30.44, 2),
                    'fmt': 'usd',
                    'sub': '30.44 days',
                },
                {
                    'label': 'API spend per year, every toggle on',
                    'value': round(scen_cost_day * 365.25, 2),
                    'fmt': 'usd',
                    'sub': '365.25 days',
                },
            ]
            + [
                {
                    'label': f['label'] + ' in 30 d (trend)',
                    'value': f['values'][-1],
                    'fmt': 'usd',
                    'sub': f'slope {f["slope_per_day"]:+.4f} $/day · r² {f["r2"]}',
                }
                for f in cpc_fc
            ],
        },
        'table': {
            'cols': ['Pipeline', 'Completed', 'Avg $ (all)', 'Avg $ (90 d)', 'Runs with priced calls', 'Avg tokens'],
            'rows': [
                [
                    k['label'],
                    k['n'],
                    {'v': k['avg_usd'], 'fmt': 'usd'},
                    {'v': k['recent_avg_usd'], 'fmt': 'usd'},
                    k['priced_runs'],
                    k['tokens_avg'],
                ]
                for k in per_kind_cost
            ],
        },
        'notes': [
            'Cost is attributed to a run when the LLM call carried its pipeline id (context ledger / llm_audit); '
            'local Ollama calls cost $0 and Claude Code (login) calls are subscription, not API — see the Quota tab. '
            'A pipeline whose stages run on local models shows $0 per content honestly, not cheaply.',
            'Prices are Anthropic/OpenAI list prices with no cache discount (the logs carry no cache hits).',
            f'"Every toggle on" = the Approval Queue volumes ({toggle_volumes}) × the recent average cost of that pipeline.',
        ],
    }
    return api_day, card_cost, done_day, total_api, win_done


def _card_volume(
    *,
    bucket,
    completed,
    content,
    d14,
    d7,
    d8,
    daily_map,
    days,
    done_day,
    families,
    fkeys,
    keys,
    now,
    runs,
    scenario_per_day,
    today,
    toggles,
    trend_series,
    weekly,
    win_done,
    window_sum,
):
    # ── 3 production volume ───────────────────────────────────────────────────
    vol_series = []
    for kind in families:
        rs = [r for r in completed if r['kind'] == kind]
        vals = _bucket_series(daily_map(rs), keys, weekly)
        if any(vals):
            vol_series.append({'id': kind, 'label': CONTENT_KINDS[kind], 'values': [int(v) for v in vals]})
    assets_done = [r for r in runs if r['is_asset'] and r['status'] == 'completed']
    asset_vals = _bucket_series(daily_map(assets_done), keys, weekly)
    vol_fc = _forecast(trend_series(done_day), floor=0.0)
    vol_fc_b = _fc_bucketed(vol_fc, fkeys, weekly, 'sum') if vol_fc else None
    scen_vals = [scenario_per_day * (7 if weekly else 1)] * len(
        fkeys if not weekly else (vol_fc_b['keys'] if vol_fc_b else [])
    )
    win_content_done = len(win_done)
    card_volume = {
        'id': 'production_volume',
        'lane': 'production',
        'title': 'Production volume',
        'question': 'How much content is actually finished per day, and how much would the approval queue make?',
        'headline': {
            'value': win_content_done,
            'fmt': 'int',
            'label': 'completed content · ' + ('all time' if not days else f'last {days} days'),
            'sub': f'{len(assets_done)} assets (characters, creatures, sheets) all time',
        },
        'delta': {
            'pct': _delta(window_sum(done_day, d7, today), window_sum(done_day, d14, d8)),
            'label': 'completed, last 7 d vs the 7 before',
            'good_when': 'up',
        },
        'chart': {
            'kind': 'columns',
            'bucket': bucket,
            'keys': keys,
            'series': vol_series,
            'y': 'int',
            'stacked': True,
            'title': 'Completed content per ' + bucket + ', by pipeline',
            'forecast': (
                [
                    {
                        'id': 'trend',
                        'label': 'Trend (all content)',
                        **vol_fc_b,
                        'slope_per_day': vol_fc['slope_per_day'],
                        'r2': vol_fc['r2'],
                        'n': vol_fc['n'],
                    }
                ]
                if vol_fc_b
                else []
            )
            + [
                {
                    'id': 'scenario',
                    'label': 'Every toggle on',
                    'keys': (vol_fc_b['keys'] if vol_fc_b else (fkeys if not weekly else [])),
                    'values': scen_vals,
                    'style': 'scenario',
                }
            ],
            'extra_series': [{'id': 'assets', 'label': 'Assets (not content)', 'values': [int(v) for v in asset_vals]}],
        },
        'facts': {
            'historical': [
                {
                    'label': CONTENT_KINDS[k],
                    'value': sum(1 for r in completed if r['kind'] == k),
                    'fmt': 'int',
                    'sub': 'completed, all time',
                }
                for k in families
            ]
            + [
                {
                    'label': 'Failed content runs, all time',
                    'value': sum(1 for r in content if r['status'] == 'failed'),
                    'fmt': 'int',
                    'sub': f'{sum(1 for r in content if r["status"] == "stale")} stale, {sum(1 for r in content if r["status"] == "unknown")} unrecorded',
                }
            ],
            'current': [
                {
                    'label': 'Completed, last 7 days',
                    'value': int(window_sum(done_day, d7, today)),
                    'fmt': 'int',
                    'sub': f'{window_sum(done_day, d7, today) / 7:.2f} per day',
                },
                {
                    'label': 'Completed, last 30 days',
                    'value': int(
                        sum(v for k, v in done_day.items() if k >= (_day(now) - timedelta(days=29)).isoformat())
                    ),
                    'fmt': 'int',
                    'sub': 'per-day average '
                    + f'{sum(v for k, v in done_day.items() if k >= (_day(now) - timedelta(days=29)).isoformat()) / 30:.2f}',
                },
                {
                    'label': 'Approval Queue right now',
                    'value': sum(1 for t in toggles if t['enabled']),
                    'fmt': 'int',
                    'sub': 'toggles on of 3 · '
                    + ', '.join(f'{t["id"]} {"ON" if t["enabled"] else "off"}' for t in toggles),
                },
            ],
            'future': (
                [
                    {
                        'label': 'Next 30 days (trend)',
                        'value': round(sum(vol_fc['values']), 1),
                        'fmt': 'num',
                        'sub': f'{vol_fc["method"]} · slope {vol_fc["slope_per_day"]:+.3f}/day · r² {vol_fc["r2"]}',
                    }
                ]
                if vol_fc
                else []
            )
            + [
                {
                    'label': 'Per day, every toggle on',
                    'value': scenario_per_day,
                    'fmt': 'num',
                    'sub': ' + '.join(f'{t["per_day"]:g} {t["kind"]}' for t in toggles),
                },
                {
                    'label': 'Per month, every toggle on',
                    'value': round(scenario_per_day * 30.44, 1),
                    'fmt': 'num',
                    'sub': 'if the machine keeps up — see Capacity',
                },
                {
                    'label': 'Per year, every toggle on',
                    'value': round(scenario_per_day * 365.25),
                    'fmt': 'num',
                    'sub': 'same caveat',
                },
            ],
        },
        'table': {
            'cols': ['Toggle', 'State', 'Per day while on', 'Rule', 'Batch now'],
            'rows': [
                [
                    t['label'],
                    'ON' if t['enabled'] else 'off',
                    t['per_day'],
                    t['rule'],
                    f'{t["batch"]["items"]} items: {t["batch"]["scheduled"]} scheduled, {t["batch"]["in_production"]} in production, {t["batch"]["done"]} done, {t["batch"]["failed"]} failed',
                ]
                for t in toggles
            ],
        },
        'notes': [
            'Content = a publishable output (documentaries, storyteller episodes, kids music videos, TokiToki, Remix AI…). '
            'Characters, creatures and contact sheets are assets and are charted separately.',
            'Completed means the run record says so (or a video path proves it); stale, cancelled and unrecorded runs are counted in the facts, never as output.',
            'The scenario line is the Approval Queue at full tilt: the volume each toggle produces per day while ON, whether or not it is on now.',
        ],
    }
    return card_volume, vol_fc
