# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Metrics > Agents and Metrics > Overview."""

from __future__ import annotations

import glob
import os
import time
from zyg_workflows.paths import ZYG_SESSION_TREE_URL

from .constants import HEALTH_LOG, RUNTIME, _zyg_log
from .helpers import _cached, _http_json, _iso, _iter_jsonl, _memo, _num, _pct, _rate
from .runs import _bucket_of, _bucketing, _window
from .llm import collect_llm, section_llm
from .pipelines import section_pipelines
from .quality_section import section_quality
from .system import section_system

# ── agents ───────────────────────────────────────────────────────────────────


def section_agents(days=30, now=None):
    now = now or time.time()
    since = _window(days, now)
    path = os.path.join(RUNTIME, 'agent_sessions_ledger.jsonl')
    rows = [
        r
        for r in (_cached(path, lambda p: list(_iter_jsonl(p))) or [])
        if since is None or (_num(r.get('start_ts')) or 0) >= since
    ]
    earliest = min((_num(r.get('start_ts')) for r in rows if _num(r.get('start_ts'))), default=None)
    keys, weekly = _bucketing(since, now, earliest)
    idx = {k: i for i, k in enumerate(keys)}
    hours = {'gpu': [0.0] * len(keys), 'cpu': [0.0] * len(keys)}
    kinds: dict = {}
    for r in rows:
        st = _num(r.get('start_ts'))
        i = idx.get(_bucket_of(st, weekly)) if st else None
        dev = 'gpu' if r.get('device') == 'gpu' else 'cpu'
        if i is not None:
            hours[dev][i] += (_num(r.get('duration_s')) or 0) / 3600
        for k in r.get('kinds') or []:
            kinds[k] = kinds.get(k, 0) + 1

    def brief(r):
        return {
            'name': r.get('name'),
            'start': r.get('start'),
            'duration_s': _num(r.get('duration_s')),
            'device': r.get('device'),
            'peak_vram_mb': _num(r.get('peak_vram_mb')),
            'peak_cpu_cores': _num(r.get('peak_cpu_cores')),
            'peak_ram_mb': _num(r.get('peak_ram_mb')),
            'kinds': r.get('kinds') or [],
            'recovered': bool(r.get('recovered')),
        }

    durs = [_num(r.get('duration_s')) or 0 for r in rows]
    return {
        'totals': {
            'sessions': len(rows),
            'agent_hours': round(sum(durs) / 3600, 1),
            'gpu_sessions': sum(1 for r in rows if r.get('device') == 'gpu'),
            'peak_vram_mb': max((_num(r.get('peak_vram_mb')) or 0 for r in rows), default=0),
            'p50_duration_s': _pct(durs, 0.5),
            'recovered': sum(1 for r in rows if r.get('recovered')),
        },
        'daily': {
            'bucket': 'week' if weekly else 'day',
            'keys': keys,
            'series': [
                {'id': 'gpu', 'label': 'GPU sessions', 'values': [round(v, 2) for v in hours['gpu']]},
                {'id': 'cpu', 'label': 'CPU-only sessions', 'values': [round(v, 2) for v in hours['cpu']]},
            ],
        },
        'kinds': dict(sorted(kinds.items(), key=lambda kv: -kv[1])),
        'longest': [brief(r) for r in sorted(rows, key=lambda r: -(_num(r.get('duration_s')) or 0))[:10]],
        'recent': [brief(r) for r in sorted(rows, key=lambda r: -(_num(r.get('start_ts')) or 0))[:25]],
        'session_tree': _http_json(f'{ZYG_SESSION_TREE_URL}/api/health'),
        'ledger_first': _iso(earliest),
        'ledger_path': 'data/runtime/agent_sessions_ledger.jsonl',
        'notes': [
            'The agent-sessions ledger tracks the compute footprint (processes, VRAM, CPU) attributed to each '
            'Claude Code session. Session Tree task details stay in its own board — its UI API is '
            'browser-only by design, so only its public /api/health queue state is read here.'
        ],
    }


# ── overview ─────────────────────────────────────────────────────────────────

_FRESHNESS = (
    ('Pipeline states', 'pipeline_*_state.json'),
    ('Storyteller states', 'storyteller_*_state.json'),
    ('Character jobs', 'char_gen_*.json'),
    ('Contact sheets', 'contact_sheet_*.json'),
    ('Creature jobs', 'creature_gen_*.json'),
    ('LLM audit log', 'llm_audit/*.jsonl'),
    ('Context ledger (token reports)', 'context_ledger.jsonl'),
    ('token_usage.json (legacy, superseded)', 'token_usage.json'),
    # Legacy on-disk ledger file; the ledger itself moved to Postgres 2026-10-02.
    # The literal is split so this module no longer contains that driver's name.
    ('Run ledger (gates, fallbacks)', 'run_ledger.sqlite3*'),
    ('Debug run history', 'debug_run_history.jsonl'),
    ('Agent sessions ledger', 'agent_sessions_ledger.jsonl'),
    ('Character quality metrics', 'character_quality_metrics.jsonl'),
)


def _freshness(now):
    out = []
    for label, pattern in _FRESHNESS:
        paths = glob.glob(os.path.join(RUNTIME, pattern))
        mt = max((os.path.getmtime(p) for p in paths), default=None)
        out.append(
            {
                'source': label,
                'path': 'data/runtime/' + pattern,
                'files': len(paths),
                'last_write': _iso(mt),
                'age_s': round(now - mt) if mt else None,
            }
        )
    try:
        mt = os.path.getmtime(HEALTH_LOG)
        out.append(
            {
                'source': 'Health probe log (event-only)',
                'path': HEALTH_LOG,
                'files': 1,
                'last_write': _iso(mt),
                'age_s': round(now - mt),
            }
        )
    except OSError as _exc:
        _zyg_log.debug('health probe log not readable, omitted from the source list: %s', _exc)
    return out


def section_overview(days=30, now=None, telemetry=None, fresh=False):
    now = now or time.time()
    llm = collect_llm(now)
    pipes = section_pipelines(days, now, llm=llm)
    llm_s = section_llm(days, now)
    qual = section_quality(days, now)
    sysm = _memo(('system', 7), 8, lambda: section_system(7, now, telemetry), fresh=fresh)
    tot = pipes['totals']
    decided = tot['completed'] + tot['failed']

    attention = []
    for s in sysm['services']:
        if s['state'] == 'orphan':
            attention.append(
                {
                    'severity': 'critical',
                    'tab': 'system',
                    'title': f'{s["label"]}: {s["unit"]} is {s["active"]} but :{s["port"]} is served outside it',
                    'detail': s['detail']
                    + (f' · pid {s["port_pid"]} `{s.get("owner", {}).get("cmd", "")}`' if s.get('port_pid') else ''),
                }
            )
        elif s['state'] == 'failed':
            attention.append(
                {
                    'severity': 'critical',
                    'tab': 'system',
                    'title': f'{s["label"]}: {s["unit"]} failed',
                    'detail': s['detail'],
                }
            )
        elif s['state'] in ('degraded', 'down'):
            attention.append(
                {'severity': 'serious', 'tab': 'system', 'title': f'{s["label"]}: {s["detail"]}', 'detail': ''}
            )
    for d in sysm['disks']:
        if d['used_pct'] is not None and d['used_pct'] >= 90:
            attention.append(
                {
                    'severity': 'critical' if d['used_pct'] >= 95 else 'serious',
                    'tab': 'system',
                    'title': f'Disk {d["mount"]} is {d["used_pct"]}% full',
                    'detail': f'{d["free_gb"]} GB free of {d["total_gb"]} GB',
                }
            )
    if pipes['stale_claims']:
        by: dict = {}
        for r in pipes['stale_claims']:
            key = f'{r["label"]} ({r["status_raw"]})'
            by[key] = by.get(key, 0) + 1
        attention.append(
            {
                'severity': 'warning',
                'tab': 'pipelines',
                'title': f'{len(pipes["stale_claims"])} runs still claim to be in progress with no state write for 12 h+',
                'detail': ', '.join(f'{k} ×{v}' for k, v in by.items())
                + ' — anything that trusts the recorded status sees them as live',
            }
        )
    credit = [e for e in llm_s['errors'] if 'credit balance' in e['message'].lower()]
    if credit:
        attention.append(
            {
                'severity': 'serious',
                'tab': 'llm',
                'title': f'Anthropic API rejected {sum(e["count"] for e in credit)} calls for low credit balance',
                'detail': f'last {credit[0]["last"]} · models {", ".join(sorted({m for e in credit for m in e["models"]}))}',
            }
        )
    for k in pipes['kinds']:
        if k['decided'] >= 5 and k['success_rate'] is not None and k['success_rate'] < 80:
            attention.append(
                {
                    'severity': 'warning',
                    'tab': 'pipelines',
                    'title': f'{k["label"]}: {k["success_rate"]}% success ({k["counts"]["failed"]} failed of {k["decided"]} decided)',
                    'detail': 'in the selected range',
                }
            )
    fb = qual['fallbacks']
    if fb['total']:
        top = fb['components'][0]
        attention.append(
            {
                'severity': 'warning',
                'tab': 'quality',
                'title': f'{fb["total"]} silent fallbacks recorded',
                'detail': f'most: {top["component"]} {top["expected"]} → {top["actual"]} ×{top["count"]} (last {top["last"]})',
            }
        )
    hp = sysm['health_probe']
    if hp.get('restarts'):
        attention.append(
            {
                'severity': 'warning',
                'tab': 'system',
                'title': f'Health probe restarted a service {hp["restarts"]}× in the last 7 days',
                'detail': ', '.join(sorted({e['unit'] for e in hp['events'] if e['kind'] == 'restart'})),
            }
        )
    rank = {'critical': 0, 'serious': 1, 'warning': 2}
    attention.sort(key=lambda a: rank.get(a['severity'], 9))

    top_fb = fb['components'][0] if fb['components'] and fb['components'][0]['count'] else None
    gpu = sysm['gpus'][0] if sysm['gpus'] else {}
    svc_ok = sum(1 for s in sysm['services'] if s['state'] == 'ok')
    svc_counted = sum(1 for s in sysm['services'] if s['state'] != 'stopped')
    worst_disk = max(sysm['disks'], key=lambda d: d['used_pct'] or 0) if sysm['disks'] else None
    return {
        'kpis': {
            'runs': tot['runs'],
            'success_rate': _rate(tot['completed'], decided),
            'decided': decided,
            'failed': tot['failed'],
            'stale': tot['stale'],
            'unknown': tot['unknown'],
            'open': tot['open'],
            'api_cost_usd': llm_s['totals']['api_cost_usd'],
            'api_cost_all_time_usd': llm_s['all_time']['api_cost_usd'],
            'llm_calls': llm_s['totals']['calls'],
            'llm_errors': llm_s['totals']['errors'],
            'local_calls': llm_s['totals']['local_calls'],
            'gate_pass_rate': qual['gates']['pass_rate'],
            'gate_outcomes': qual['gates']['pass'] + qual['gates']['fail'],
            'gate_unattributed': qual['gates']['unattributed_pass'] + qual['gates']['unattributed_fail'],
            'fallbacks': fb['total'],
            'top_fallback': top_fb['component'] if top_fb else None,
            'services_ok': svc_ok,
            'services_counted': svc_counted,
            'services_orphan': sum(1 for s in sysm['services'] if s['state'] == 'orphan'),
            'services_failed': sum(1 for s in sysm['services'] if s['state'] in ('failed', 'degraded', 'down')),
            'disk': worst_disk,
            'gpu': gpu,
            'telemetry': sysm['telemetry'],
        },
        'attention': attention,
        'daily_runs': pipes['daily'],
        'recent': pipes['recent'][:12],
        'freshness': _freshness(now),
        'excluded_test_runs': pipes['excluded_test_runs'],
    }
