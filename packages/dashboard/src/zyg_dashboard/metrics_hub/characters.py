# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Metrics > Characters — the character / creature / contact-sheet payload."""

from __future__ import annotations

import os
import time

from .constants import RUNTIME
from .helpers import _cached, _iso, _iter_jsonl, _pct, _rate
from .runs import STATUSES, _run_row, _window, collect_runs

# ── characters ───────────────────────────────────────────────────────────────


def section_characters(days=30, now=None):
    now = now or time.time()
    runs, meta = collect_runs(now)
    since = _window(days, now)
    win = [r for r in runs if r['family'] == 'characters' and (since is None or r['t'] >= since)]
    chars = [r for r in win if r['kind'] == 'character']
    lora = {'attempts': 0, 'ok': 0, 'flux': [], 'sdxl': [], 'other': [], 'steps': []}
    stage_els: dict = {}
    families: dict = {}
    render_modes: dict = {}
    for r in chars:
        families[r.get('model_family') or 'unknown'] = families.get(r.get('model_family') or 'unknown', 0) + 1
        render_modes[r.get('render_mode') or 'unknown'] = render_modes.get(r.get('render_mode') or 'unknown', 0) + 1
        for raw, el, st, steps in r.get('lora') or []:
            lora['attempts'] += 1
            if st == 'completed':
                lora['ok'] += 1
                bucket = 'flux' if 'FLUX' in raw.upper() else 'sdxl' if 'SDXL' in raw.upper() else 'other'
                if el:
                    lora[bucket].append(el)
                if steps:
                    lora['steps'].append(steps)
        for name, el, st in r['stages']:
            if el is not None and st == 'completed':
                stage_els.setdefault(name, []).append(el)

    def counts(rows):
        return {s: sum(1 for r in rows if r['status'] == s) for s in STATUSES} | {'total': len(rows)}

    sheets = [r for r in win if r['kind'] == 'contact_sheet']
    char_counts = counts(chars)
    timed = [r['duration_s'] for r in chars if r['status'] == 'completed' and r['duration_s']]
    return {
        'characters': char_counts
        | {
            'success_rate': _rate(char_counts['completed'], char_counts['completed'] + char_counts['failed']),
            'synthesized_all_time': meta['excluded_synthesized'],
            'p50_s': _pct(timed, 0.5),
            'p90_s': _pct(timed, 0.9),
            'timed_runs': len(timed),
            'model_families': dict(sorted(families.items(), key=lambda kv: -kv[1])),
            'render_modes': dict(sorted(render_modes.items(), key=lambda kv: -kv[1])),
        },
        'lora': {
            'attempts': lora['attempts'],
            'completed': lora['ok'],
            'success_rate': _rate(lora['ok'], lora['attempts']),
            'flux_p50_s': _pct(lora['flux'], 0.5),
            'flux_runs': len(lora['flux']),
            'sdxl_p50_s': _pct(lora['sdxl'], 0.5),
            'sdxl_runs': len(lora['sdxl']),
            'steps_p50': _pct(lora['steps'], 0.5),
        },
        'stages': [
            {'name': n, 'runs': len(v), 'p50_s': _pct(v, 0.5), 'p90_s': _pct(v, 0.9)}
            for n, v in sorted(stage_els.items(), key=lambda kv: -sum(kv[1]))
        ][:14],
        'contact_sheets': counts(sheets)
        | {
            'cells_done': sum(r.get('cells_done') or 0 for r in sheets),
            'cells_total': sum(r.get('cells_total') or 0 for r in sheets),
        },
        'creatures': counts([r for r in win if r['kind'] == 'creature']),
        'recent': [_run_row(r) | {'model_family': r.get('model_family')} for r in win[:20]],
        'quality': _character_quality(),
        'notes': [
            f'{meta["excluded_synthesized"]} character records predate job-state persistence and were '
            'synthesized from character bibles (backfilled=true, status assumed done, bible timestamps). '
            'The characters exist, but those records are not observed runs, so they are excluded from '
            'every count, success rate and duration here.'
        ],
    }


def _character_quality(limit=30):
    path = os.path.join(RUNTIME, 'character_quality_metrics.jsonl')
    rows = list(_cached(path, lambda p: list(_iter_jsonl(p))) or [])[-limit:] if os.path.exists(path) else []
    alerts = []
    for r in rows:
        if r.get('qc_ran') is False:
            alerts.append({'char_id': r.get('char_id'), 'alert': 'QC skipped', 'ts': r.get('ts')})
        if (r.get('valve_verdict') or '') in ('fail', 'error'):
            alerts.append({'char_id': r.get('char_id'), 'alert': f'valve {r["valve_verdict"]}', 'ts': r.get('ts')})
        dd = r.get('anchor_dedup_max_sim')
        if isinstance(dd, (int, float)) and dd > 0.45:
            alerts.append({'char_id': r.get('char_id'), 'alert': f'anchor dedup similarity {dd}', 'ts': r.get('ts')})
    return {'rows': rows[::-1], 'alerts': alerts, 'last_write': _iso(os.path.getmtime(path)) if rows else None}
