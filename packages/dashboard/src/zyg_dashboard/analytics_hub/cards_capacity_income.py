# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Cards 4-5: capacity (run hours vs the day) and gross income on assumed views."""

from __future__ import annotations

from datetime import datetime, timedelta
from zyg_dashboard import metrics_hub as mh

from .constants import CONTENT_KINDS, DAY
from .helpers import _bucket_series, _day, _delta, _fc_bucketed, _week_start
from .sysusage import _run_hours_by_day


def _card_capacity(
    *,
    active_h,
    bucket,
    completed,
    content,
    fkeys,
    keys,
    now,
    runs,
    scenario_hours,
    scenario_missing,
    scenario_per_day,
    times_by_kind,
    toggles,
    weekly,
):
    # ── 4 capacity ────────────────────────────────────────────────────────────
    cap_rows = []
    for t in times_by_kind:
        if not t['is_content'] or not t['p50_recent_s']:
            continue
        per_day = active_h * 3600 / t['p50_recent_s']
        recent_done = sum(1 for r in completed if r['kind'] == t['kind'] and r['t'] >= now - 30 * DAY)
        cap_rows.append(
            {
                'kind': t['kind'],
                'label': t['label'],
                'unit_s': t['p50_recent_s'],
                'per_day': round(per_day, 1),
                'per_month': round(per_day * 30.44),
                'per_year': round(per_day * 365.25),
                'actual_30d_per_day': round(recent_done / 30, 2),
                'used_pct': round(recent_done / 30 / per_day * 100, 1) if per_day else None,
            }
        )
    run_hours = _run_hours_by_day(content + [r for r in runs if r['is_asset']])
    run_hours_series = _bucket_series(run_hours, keys, weekly)
    scen_util = scenario_hours / active_h * 100 if active_h else None
    card_capacity = {
        'id': 'capacity',
        'lane': 'capacity',
        'title': 'Capacity per day / month / year',
        'question': 'How much could this machine produce if it ran one pipeline back to back?',
        'headline': {
            'value': cap_rows[0]['per_day'] if cap_rows else None,
            'fmt': 'num',
            'label': (cap_rows[0]['label'] + ' per day at recent median time') if cap_rows else 'no timed content runs',
            'sub': f'{active_h:g} active hours per day (assumption)',
        },
        'delta': {'pct': None, 'label': ''},
        'chart': {
            'kind': 'columns',
            'bucket': bucket,
            'keys': keys,
            'y': 'hours',
            'stacked': False,
            'title': 'Hours of pipeline work per '
            + bucket
            + ' (union of run intervals) vs the '
            + f'{active_h:g} h/day'
            + ' ceiling',
            'series': [{'id': 'run_hours', 'label': 'Hours of pipeline work', 'values': run_hours_series}],
            'ceiling': {'label': 'Ceiling', 'value': active_h * (7 if weekly else 1)},
            'forecast': [
                {
                    'id': 'scenario',
                    'label': 'Every toggle on (hours/day needed)',
                    'keys': fkeys
                    if not weekly
                    else sorted({_week_start(datetime.fromisoformat(k).date()).isoformat() for k in fkeys}),
                    'values': [round(scenario_hours * (7 if weekly else 1), 2)]
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
                    'label': c['label'],
                    'value': c['actual_30d_per_day'],
                    'fmt': 'num',
                    'sub': f'actually completed per day, last 30 d · {c["used_pct"]} % of its solo capacity',
                }
                for c in cap_rows
            ],
            'current': [
                {
                    'label': c['label'] + ' per day',
                    'value': c['per_day'],
                    'fmt': 'num',
                    'sub': f'one every {mh._pct([c["unit_s"]], 0.5) and round(c["unit_s"] / 60, 1)} min · {c["per_month"]} / month · {c["per_year"]:,} / year',
                }
                for c in cap_rows
            ],
            'future': [
                {
                    'label': 'Every toggle on needs',
                    'value': round(scenario_hours, 2),
                    'fmt': 'hours',
                    'sub': f'{scen_util:.0f} % of a {active_h:g} h day'
                    + (f' · no unit time yet for {", ".join(scenario_missing)}' if scenario_missing else ''),
                },
                {
                    'label': 'Fits in a day?',
                    'value': 'yes'
                    if scenario_hours <= active_h
                    else f'no — {scenario_hours - active_h:.1f} h carry over daily',
                    'fmt': 'text',
                    'sub': 'pipelines run one at a time on the single GPU slot',
                },
                {
                    'label': 'Content per day, every toggle on',
                    'value': scenario_per_day,
                    'fmt': 'num',
                    'sub': 'as scheduled; the machine delivers at most what fits in the day',
                },
            ],
        },
        'table': {
            'cols': ['Pipeline', 'Median time (90 d)', 'Per day', 'Per month', 'Per year', 'Actual/day (30 d)', 'Used'],
            'rows': [
                [
                    c['label'],
                    {'v': c['unit_s'], 'fmt': 'dur'},
                    c['per_day'],
                    c['per_month'],
                    c['per_year'],
                    c['actual_30d_per_day'],
                    {'v': c['used_pct'], 'fmt': 'pct'},
                ]
                for c in cap_rows
            ]
            + [
                [
                    t['label'] + ' (toggle)',
                    {'v': t['unit_s'], 'fmt': 'dur'},
                    t['per_day'],
                    '',
                    '',
                    '',
                    {'v': (t['hours_per_day'] or 0) / active_h * 100 if t['unit_s'] else None, 'fmt': 'pct'},
                ]
                for t in toggles
            ],
        },
        'notes': [
            f'Capacity = {active_h:g} active hours ÷ the recent median wall time of that pipeline, one run at a time (the GPU queue has one heavy slot). Mixed production shares the same hours.',
            'Hours of pipeline work = union of every run interval (content and assets) per day from the run ledgers, so overlapping runs are not double-counted.',
            'Pipelines whose runs record no duration have no capacity row; the Production times card lists them as untimed.',
        ],
    }
    return card_capacity, run_hours, scen_util


def _card_income(
    *,
    api_day,
    bucket,
    cfg,
    completed,
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
    scenario_per_day,
    today,
    total_api,
    vol_fc,
    weekly,
    win_done,
    window_sum,
):
    # ── 5 gross income (assumed views) ────────────────────────────────────────
    v = cfg['views_per_content']
    rpm = cfg['rpm_usd']
    per_content_usd = v / 1000.0 * rpm
    inc_day = {k: n * per_content_usd for k, n in done_day.items()}
    inc_series = []
    for kind in families:
        vals = _bucket_series(
            daily_map([r for r in completed if r['kind'] == kind], lambda r: per_content_usd), keys, weekly
        )
        if any(vals):
            inc_series.append({'id': kind, 'label': CONTENT_KINDS[kind], 'values': vals})
    inc_fc = (
        {
            'values': [x * per_content_usd for x in vol_fc['values']],
            'lo': [x * per_content_usd for x in vol_fc['lo']],
            'hi': [x * per_content_usd for x in vol_fc['hi']],
        }
        if vol_fc
        else None
    )
    inc_fc_b = _fc_bucketed(inc_fc, fkeys, weekly, 'sum') if inc_fc else None
    cum = []
    run = 0.0
    for k in keys:
        run += sum(s['values'][keys.index(k)] for s in inc_series)
        cum.append(round(run, 2))
    sens = []
    for r_ in cfg['rpm_scenarios']:
        pc = v / 1000.0 * r_
        sens.append(
            {
                'rpm': r_,
                'per_content': round(pc, 3),
                'all_time': round(len(completed) * pc, 2),
                'last_30d': round(
                    sum(n for k, n in done_day.items() if k >= (_day(now) - timedelta(days=29)).isoformat()) * pc, 2
                ),
                'trend_30d': round(sum(vol_fc['values']) * pc, 2) if vol_fc else None,
                'scenario_day': round(scenario_per_day * pc, 2),
                'scenario_month': round(scenario_per_day * 30.44 * pc, 2),
                'scenario_year': round(scenario_per_day * 365.25 * pc, 2),
            }
        )
    eur = cfg['eur_per_usd']
    card_income = {
        'id': 'income',
        'lane': 'money',
        'title': 'Gross income at the views floor',
        'question': f'If every piece of content averaged {v:,} views, what would production gross at RPM ${rpm:g}?',
        'assumption': True,
        'headline': {
            'value': round(len(win_done) * per_content_usd, 2),
            'fmt': 'usd',
            'label': 'gross · ' + ('all time' if not days else f'last {days} days') + f' · {v:,} views × ${rpm:g} RPM',
            'sub': f'≈ €{len(win_done) * per_content_usd * eur:,.2f} at {eur:g} EUR/USD · ${per_content_usd:.3f} per content',
        },
        'delta': {
            'pct': _delta(window_sum(inc_day, d7, today), window_sum(inc_day, d14, d8)),
            'label': 'gross, last 7 d vs the 7 before',
            'good_when': 'up',
        },
        'chart': {
            'kind': 'columns',
            'bucket': bucket,
            'keys': keys,
            'series': inc_series,
            'y': 'usd',
            'stacked': True,
            'title': f'Assumed gross per {bucket} ({v:,} views × ${rpm:g} RPM per content)',
            'line': {'label': 'Cumulative', 'values': cum},
            'forecast': ([{'id': 'trend', 'label': 'Trend', **inc_fc_b, 'style': 'forecast'}] if inc_fc_b else [])
            + [
                {
                    'id': 'scenario',
                    'label': 'Every toggle on',
                    'keys': (inc_fc_b['keys'] if inc_fc_b else (fkeys if not weekly else [])),
                    'values': [round(scenario_per_day * per_content_usd * (7 if weekly else 1), 2)]
                    * (len(inc_fc_b['keys']) if inc_fc_b else (len(fkeys) if not weekly else 0)),
                    'style': 'scenario',
                }
            ],
        },
        'facts': {
            'historical': [
                {
                    'label': 'All content ever completed',
                    'value': len(completed),
                    'fmt': 'int',
                    'sub': f'× ${per_content_usd:.3f} = ${len(completed) * per_content_usd:,.2f} gross',
                },
                {
                    'label': 'Gross all time (assumed)',
                    'value': round(len(completed) * per_content_usd, 2),
                    'fmt': 'usd',
                    'sub': f'€{len(completed) * per_content_usd * eur:,.2f}',
                },
                {
                    'label': 'Paid tokens all time',
                    'value': round(total_api, 2),
                    'fmt': 'usd',
                    'sub': 'API spend, the direct cost side',
                },
            ],
            'current': [
                {
                    'label': 'Gross, last 30 days',
                    'value': round(
                        sum(n for k, n in done_day.items() if k >= (_day(now) - timedelta(days=29)).isoformat())
                        * per_content_usd,
                        2,
                    ),
                    'fmt': 'usd',
                    'sub': 'assumed',
                },
                {
                    'label': 'Views needed to cover API spend (30 d)',
                    'value': round(
                        window_sum(api_day, (_day(now) - timedelta(days=29)).isoformat(), today) / rpm * 1000
                    )
                    if rpm
                    else None,
                    'fmt': 'int',
                    'sub': f'at ${rpm:g} RPM',
                },
            ],
            'future': (
                [
                    {
                        'label': 'Next 30 days (trend)',
                        'value': round(sum(inc_fc['values']), 2),
                        'fmt': 'usd',
                        'sub': 'volume trend × assumed value per content',
                    }
                ]
                if inc_fc
                else []
            )
            + [
                {
                    'label': 'Per month, every toggle on',
                    'value': round(scenario_per_day * 30.44 * per_content_usd, 2),
                    'fmt': 'usd',
                    'sub': f'{scenario_per_day * 30.44:.0f} items',
                },
                {
                    'label': 'Per year, every toggle on',
                    'value': round(scenario_per_day * 365.25 * per_content_usd, 2),
                    'fmt': 'usd',
                    'sub': f'≈ €{scenario_per_day * 365.25 * per_content_usd * eur:,.0f}',
                },
            ],
        },
        'table': {
            'cols': [
                'RPM $',
                'Per content',
                'All time',
                'Last 30 d',
                'Next 30 d (trend)',
                'Toggles on / day',
                '/ month',
                '/ year',
            ],
            'rows': [
                [
                    s['rpm'],
                    {'v': s['per_content'], 'fmt': 'usd'},
                    {'v': s['all_time'], 'fmt': 'usd'},
                    {'v': s['last_30d'], 'fmt': 'usd'},
                    {'v': s['trend_30d'], 'fmt': 'usd'},
                    {'v': s['scenario_day'], 'fmt': 'usd'},
                    {'v': s['scenario_month'], 'fmt': 'usd'},
                    {'v': s['scenario_year'], 'fmt': 'usd'},
                ]
                for s in sens
            ],
        },
        'notes': [
            f'This is an assumption, not a measurement: every completed content item is valued at {v:,} views × ${rpm:g} per 1 000 views (RPM). '
            'Real RPM depends on niche, geography and monetisation; the sensitivity table shows the same volumes at other RPMs.',
            'Real views exist only for channels with a saved YouTube account (Creator Nexus reads DocuDocu through the Data API). '
            'The tab shows them beside this card when reachable; they are not folded into the figures here.',
            'Edit the assumptions in the Assumptions box; they are stored in data/runtime/analytics_config.json and shipped with every payload.',
        ],
    }
    return card_income
