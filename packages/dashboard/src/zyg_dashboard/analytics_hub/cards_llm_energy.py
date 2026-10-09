# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Cards 8-10: LLM mix local vs paid, subscription burn, energy."""

from __future__ import annotations

from zyg_dashboard import metrics_hub as mh

from .constants import API
from .helpers import _bucket_series, _daily_keys, _daykey, _delta, _fc_bucketed, _forecast


def _card_mix(
    *, bucket, d14, d7, d8, days, fkeys, keys, llm, since, today, total_api, trend_series, weekly, window_sum
):
    # ── 8 LLM mix: local vs paid ──────────────────────────────────────────────
    prov_day: dict = {}
    for c in llm['rows']:
        if not c['ts']:
            continue
        p = (
            'replay'
            if c.get('replayed')
            else 'api'
            if c['provider'] in API
            else (
                'local' if c['provider'] == 'local' else ('claude_code' if c['provider'] == 'claude_code' else 'other')
            )
        )
        prov_day.setdefault(p, {})
        dk = _daykey(c['ts'])
        prov_day[p][dk] = prov_day[p].get(dk, 0) + 1
    mix_series = [
        {'id': p, 'label': lbl, 'values': [int(x) for x in _bucket_series(prov_day.get(p, {}), keys, weekly)]}
        for p, lbl in (
            ('local', 'Local (Ollama) calls'),
            ('api', 'Paid API calls'),
            ('claude_code', 'Claude Code (subscription) calls'),
            ('replay', 'Replayed from the pre-emptive bank (no spend)'),
            ('other', 'Other'),
        )
        if prov_day.get(p)
    ]
    win_calls = [c for c in llm['rows'] if c['ts'] and (since is None or c['ts'] >= since)]
    local_share = mh._rate(sum(1 for c in win_calls if c['provider'] == 'local'), len(win_calls))
    tokens_day: dict = {}
    replay_tokens_day: dict = {}
    for c in llm['rows']:
        if c['ts']:
            dk = _daykey(c['ts'])
            tgt = replay_tokens_day if c.get('replayed') else tokens_day
            tgt[dk] = tgt.get(dk, 0) + (c['tin'] or 0) + (c['tout'] or 0)
    tok_fc = _forecast(trend_series(tokens_day), floor=0.0)
    card_mix = {
        'id': 'llm_mix',
        'lane': 'money',
        'title': 'Local vs paid LLM work',
        'question': 'How much of the language work runs free on the box, and how much is bought?',
        'headline': {
            'value': local_share,
            'fmt': 'pct',
            'label': 'share of LLM calls on local Ollama · ' + ('all time' if not days else f'last {days} days'),
            'sub': f'{sum(1 for c in win_calls if c["provider"] in API)} paid API calls · {sum(1 for c in win_calls if c["provider"] == "claude_code")} Claude Code calls',
        },
        'delta': {
            'pct': _delta(
                sum(1 for c in llm['rows'] if c['ts'] and c['provider'] in API and _daykey(c['ts']) >= d7),
                sum(1 for c in llm['rows'] if c['ts'] and c['provider'] in API and d14 <= _daykey(c['ts']) <= d8),
            ),
            'label': 'paid API calls, last 7 d vs the 7 before',
            'good_when': 'down',
        },
        'chart': {
            'kind': 'columns',
            'bucket': bucket,
            'keys': keys,
            'series': mix_series,
            'y': 'int',
            'stacked': True,
            'title': 'LLM calls per ' + bucket + ' by provider class',
            'forecast': (
                [
                    {
                        'id': 'trend',
                        'label': 'Tokens/day trend (all providers, ÷1000)',
                        **{
                            k: ([x / 1000 for x in v] if k in ('values', 'lo', 'hi') else v)
                            for k, v in _fc_bucketed(tok_fc, fkeys, weekly, 'sum').items()
                        },
                    }
                ]
                if tok_fc
                else []
            ),
        },
        'facts': {
            'historical': [
                {
                    'label': 'Local calls, all time',
                    'value': sum(1 for c in llm['rows'] if c['provider'] == 'local'),
                    'fmt': 'int',
                    'sub': 'only the logged helper; raw posts bypass it',
                },
                {
                    'label': 'Paid API calls, all time',
                    'value': sum(1 for c in llm['rows'] if c['provider'] in API),
                    'fmt': 'int',
                    'sub': f'${total_api:,.2f}',
                },
                {
                    'label': 'Tokens, all time',
                    'value': sum(tokens_day.values()),
                    'fmt': 'int',
                    'sub': 'in + out, every provider — spent only',
                },
                {
                    'label': 'Tokens answered from the bank',
                    'value': sum(replay_tokens_day.values()),
                    'fmt': 'int',
                    'sub': f'{sum(1 for c in llm["rows"] if c.get("replayed"))} replayed calls that cost nothing',
                },
            ],
            'current': [
                {
                    'label': 'Tokens, last 7 days',
                    'value': int(window_sum(tokens_day, d7, today)),
                    'fmt': 'int',
                    'sub': '',
                },
                {
                    'label': 'Local share, last 7 days',
                    'value': mh._rate(
                        sum(1 for c in llm['rows'] if c['ts'] and c['provider'] == 'local' and _daykey(c['ts']) >= d7),
                        sum(1 for c in llm['rows'] if c['ts'] and _daykey(c['ts']) >= d7),
                    ),
                    'fmt': 'pct',
                    'sub': '',
                },
            ],
            'future': (
                [
                    {
                        'label': 'Tokens per day in 30 d (trend)',
                        'value': int(tok_fc['values'][-1]),
                        'fmt': 'int',
                        'sub': f'slope {tok_fc["slope_per_day"]:+.0f}/day · r² {tok_fc["r2"]}',
                    }
                ]
                if tok_fc
                else []
            ),
        },
        'table': {
            'cols': ['Provider class', 'Calls (window)', 'Share'],
            'rows': [
                [
                    lbl,
                    sum(1 for c in win_calls if cls(c)),
                    {'v': mh._rate(sum(1 for c in win_calls if cls(c)), len(win_calls)), 'fmt': 'pct'},
                ]
                for lbl, cls in (
                    ('Local (Ollama)', lambda c: c['provider'] == 'local'),
                    ('Paid API', lambda c: c['provider'] in API),
                    ('Claude Code (subscription)', lambda c: c['provider'] == 'claude_code' and not c.get('replayed')),
                    ('Replayed from the bank', lambda c: bool(c.get('replayed'))),
                    ('Other', lambda c: c['provider'] not in API and c['provider'] not in ('local', 'claude_code')),
                )
            ],
        },
        'notes': [
            'Same rows as the LLM & costs tab (context ledger + llm_audit, duplicates dropped, test calls excluded).',
            'A replayed call is one the pre-emptive bank answered from a recording: it carries the tokens the RECORDING was billed for, so it is counted as saved, never as spent or as money.',
        ],
    }
    return card_mix


def _card_sub(*, bucket, keys, now, weekly):
    # ── 9 subscription burn (Claude quota meter) ──────────────────────────────
    q = mh._quota_meter()
    try:
        samples = q.read_samples()
    except Exception:
        samples = []
    try:
        qcfg = q.load_config()
        weekly_price = (
            float(q.compute(qcfg, samples[-1] if samples else {}, {}, {}, now)['weekly_price']) if samples else None
        )
        cur = qcfg.get('currency', 'EUR')
    except Exception:
        qcfg, weekly_price, cur = {}, None, 'EUR'
    pct_day: dict = {}
    for s in samples:
        ts = s.get('ts')
        pct = (s.get('seven_day') or {}).get('pct')
        if ts and pct is not None:
            dk = _daykey(ts)
            pct_day[dk] = max(pct_day.get(dk, 0), pct)  # the meter's high-water mark that day
    sub_series = [
        {
            'id': 'seven_day',
            'label': 'Weekly meter (% used, daily high)',
            'values': _bucket_series(pct_day, keys, weekly, 'mean'),
        }
    ]
    latest = samples[-1] if samples else None
    latest_pct = (latest or {}).get('seven_day', {}).get('pct')
    consumed = (latest_pct or 0) / 100 * weekly_price if (latest_pct is not None and weekly_price) else None
    card_sub = {
        'id': 'subscription',
        'lane': 'money',
        'title': 'Claude subscription burn',
        'question': 'How fast is the weekly Claude meter being used, and what is that worth?',
        'headline': {
            'value': latest_pct,
            'fmt': 'pct',
            'label': 'weekly meter used now',
            'sub': (
                f'≈ {consumed:.2f} {cur} of {weekly_price:.2f} {cur} per Claude week'
                if consumed is not None
                else 'no meter sample yet'
            ),
        },
        'delta': {'pct': None, 'label': ''},
        'chart': {
            'kind': 'line',
            'bucket': bucket,
            'keys': keys,
            'series': sub_series,
            'y': 'pct',
            'title': 'Claude weekly meter, daily high-water mark (resets each Claude week)',
        },
        'facts': {
            'historical': [
                {
                    'label': 'Meter samples',
                    'value': len(samples),
                    'fmt': 'int',
                    'sub': 'zyg-quota-meter.timer, every 10 min',
                },
                {'label': 'Days with a sample', 'value': len(pct_day), 'fmt': 'int', 'sub': ''},
            ],
            'current': [
                {
                    'label': 'Weekly meter',
                    'value': latest_pct,
                    'fmt': 'pct',
                    'sub': (
                        f'resets {mh._iso((latest or {}).get("seven_day", {}).get("resets_at"))}' if latest else ''
                    ),
                },
                {
                    'label': 'Value consumed this week',
                    'value': round(consumed, 2) if consumed is not None else None,
                    'fmt': 'eur',
                    'sub': f'{cur}, subscription price pro rata',
                },
                {
                    'label': 'Session meter (5 h)',
                    'value': (latest or {}).get('five_hour', {}).get('pct'),
                    'fmt': 'pct',
                    'sub': '',
                },
            ],
            'future': [
                {
                    'label': 'Subscription per month',
                    'value': qcfg.get('subscription_price'),
                    'fmt': 'eur',
                    'sub': f'{qcfg.get("plan_label", "")} — fixed, whatever the meter says',
                },
                {
                    'label': 'Subscription per year',
                    'value': round(float(qcfg.get('subscription_price') or 0) * 12, 2),
                    'fmt': 'eur',
                    'sub': 'fixed cost side of the income card',
                },
            ],
        },
        'table': {
            'cols': ['Day', 'Weekly meter high (%)'],
            'rows': [[k, {'v': v, 'fmt': 'pct'}] for k, v in sorted(pct_day.items(), reverse=True)][:60],
        },
        'notes': [
            "The meter is Claude's own percentage for this login (Quota tab). It is a fixed weekly window, so the line saws: it climbs through the week and drops at the reset.",
            'Nothing here is billed per token; the value is the subscription price spread over the week.',
        ],
    }
    return card_sub


def _card_energy(
    *, active_h, bucket, cfg, done_day, keys, last30_keys, last7_keys, now, scenario_hours, today, util_day, weekly
):
    # ── 10 energy ─────────────────────────────────────────────────────────────
    kwh_day = {k: v['kwh'] for k, v in util_day.items() if v['kwh'] is not None}
    kwh_series = _bucket_series(kwh_day, keys, weekly)
    price = cfg['kwh_price_eur']
    kwh_30 = sum(v for k, v in kwh_day.items() if k in last30_keys)
    done_30 = sum(v for k, v in done_day.items() if k in last30_keys)
    card_energy = {
        'id': 'energy',
        'lane': 'capacity',
        'title': 'GPU energy',
        'question': 'What does the GPU draw, and what does that cost per piece of content?',
        'assumption': True,
        'headline': {
            'value': round(kwh_30, 2),
            'fmt': 'kwh',
            'label': 'GPU kWh, last 30 days (sampled minutes only)',
            'sub': f'≈ €{kwh_30 * price:.2f} at €{price:g}/kWh · '
            + (f'€{kwh_30 * price / done_30:.3f} per completed content' if done_30 else 'no completed content in 30 d'),
        },
        'delta': {
            'pct': _delta(
                sum(v for k, v in kwh_day.items() if k in last7_keys),
                sum(v for k, v in kwh_day.items() if k in _daily_keys(now, 14)[:7]),
            ),
            'label': 'kWh, last 7 d vs the 7 before',
            'good_when': 'down',
        },
        'chart': {
            'kind': 'columns',
            'bucket': bucket,
            'keys': keys,
            'series': [{'id': 'kwh', 'label': 'GPU kWh', 'values': kwh_series}],
            'y': 'kwh',
            'title': 'GPU energy per ' + bucket + ' from power samples',
        },
        'facts': {
            'historical': [
                {
                    'label': 'GPU kWh, all sampled days',
                    'value': round(sum(kwh_day.values()), 1),
                    'fmt': 'kwh',
                    'sub': f'{len(kwh_day)} days with power samples · €{sum(kwh_day.values()) * price:.2f}',
                }
            ],
            'current': [
                {
                    'label': 'Today',
                    'value': round(kwh_day.get(today, 0.0), 3),
                    'fmt': 'kwh',
                    'sub': f'€{kwh_day.get(today, 0.0) * price:.3f}',
                }
            ],
            'future': [
                {
                    'label': 'Per day, every toggle on',
                    'value': round(min(scenario_hours, active_h) * 0.35, 2),
                    'fmt': 'kwh',
                    'sub': 'busy hours × 350 W (a 4090 rendering; idle ≈ 24 W) — a rule of thumb, not a sample',
                }
            ],
        },
        'table': {
            'cols': ['Day', 'kWh', '€', 'Source'],
            'rows': [
                [k, {'v': v, 'fmt': 'kwh'}, {'v': v * price, 'fmt': 'eur'}, util_day[k]['source']]
                for k, v in sorted(kwh_day.items(), reverse=True)
            ][:90],
        },
        'notes': [
            'GPU board power only (nvml), integrated over sampled minutes; CPU, RAM and the rest of the box are not metered. The €/kWh price is an assumption in the Assumptions box.'
        ],
    }
    return card_energy
