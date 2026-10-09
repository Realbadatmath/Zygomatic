# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Metrics > Pipelines — the per-family run payload."""

from __future__ import annotations

import time

from .helpers import _iso, _pct, _rate
from .runs import KIND_LABELS, STATUSES, STATUS_RULES, _FAIL, _family, _run_row, _runs_daily, _window, collect_runs
from .llm import collect_llm


def section_pipelines(days=30, now=None, llm=None):
    now = now or time.time()
    runs, meta = collect_runs(now)
    since = _window(days, now)
    win = [r for r in runs if since is None or r['t'] >= since]
    llm = llm if llm is not None else collect_llm(now)
    cost_by_ptype: dict = {}
    for c in llm['rows']:
        if (
            (since is None or (c['ts'] or 0) >= since)
            and c['cost']
            and c['provider'] in ('anthropic_api', 'openai_api')
        ):
            cost_by_ptype[c['ptype']] = cost_by_ptype.get(c['ptype'], 0.0) + c['cost']

    kinds: dict = {}
    for r in win:
        k = kinds.setdefault(
            r['kind'],
            {'total': 0, 'inferred': 0, 'durations': [], 'stages': {}, 'last': None, **{s: 0 for s in STATUSES}},
        )
        k['total'] += 1
        k[r['status']] += 1
        k['inferred'] += 1 if r['inferred'] else 0
        if r['status'] == 'completed' and r['duration_s']:
            k['durations'].append(r['duration_s'])
        for name, el, st in r['stages']:
            s = k['stages'].setdefault(name, {'els': [], 'failed': 0, 'runs': 0})
            s['runs'] += 1
            if el is not None and el >= 0:
                s['els'].append(el)
            if st in _FAIL:
                s['failed'] += 1
        if k['last'] is None:
            k['last'] = r
    out = []
    for kind, k in sorted(kinds.items(), key=lambda kv: -kv[1]['total']):
        decided = k['completed'] + k['failed']
        stages = sorted(k['stages'].items(), key=lambda kv: -sum(kv[1]['els']))[:14]
        out.append(
            {
                'kind': kind,
                'label': KIND_LABELS.get(kind, kind.replace('_', ' ').title()),
                'family': _family(kind),
                'total': k['total'],
                'counts': {s: k[s] for s in STATUSES},
                'inferred': k['inferred'],
                'success_rate': _rate(k['completed'], decided),
                'decided': decided,
                'p50_s': _pct(k['durations'], 0.5),
                'p90_s': _pct(k['durations'], 0.9),
                'timed_runs': len(k['durations']),
                'last_started': _iso(k['last']['t']),
                'last_status': k['last']['status'],
                'api_cost_usd': round(cost_by_ptype.get(kind, 0.0), 4),
                'stages': [
                    {
                        'name': n,
                        'runs': s['runs'],
                        'timed': len(s['els']),
                        'p50_s': _pct(s['els'], 0.5),
                        'avg_s': round(sum(s['els']) / len(s['els']), 1) if s['els'] else None,
                        'failed': s['failed'],
                    }
                    for n, s in stages
                ],
            }
        )
    stale_claims = [_run_row(r) for r in runs if r['claims_running'] and r['status'] == 'stale']
    earliest = min((r['t'] for r in runs), default=None)
    return {
        'kinds': out,
        'daily': _runs_daily(win, since, now, earliest),
        'totals': {s: sum(1 for r in win if r['status'] == s) for s in STATUSES} | {'runs': len(win)},
        'stale_claims': stale_claims,
        'recent_failures': [_run_row(r) for r in win if r['status'] == 'failed'][:15],
        'recent': [_run_row(r) for r in win[:30]],
        'status_rules': STATUS_RULES,
        'excluded_test_runs': meta['excluded_test_runs'],
        'excluded_synthesized': meta['excluded_synthesized'],
        'unreadable': meta['unreadable'],
        'sources': [
            'data/runtime/pipeline_*_state.json',
            'storyteller_*_state.json',
            'char_gen_*.json',
            'creature_gen_*.json',
            'contact_sheet_*.json',
        ],
    }
