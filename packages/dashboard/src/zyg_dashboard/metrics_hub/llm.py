# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""LLM calls & cost: the price table, the audit readers and the Claude quota meter."""

from __future__ import annotations

import glob
import json
import os
import re
import sys
import time

from .constants import CREWS, RUNTIME
from .helpers import _cached, _is_test_id, _iso, _iter_jsonl, _num, _pct, _prune, _short, _ts
from .runs import _bucket_of, _bucketing, _window

import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)

# ── LLM calls & cost ─────────────────────────────────────────────────────────
# Anthropic first-party list prices per 1M tokens (in, out), from the claude-api
# reference cached 2026-06-24; older / OpenAI ids at their published list price.
# Neither log records cache hits for SDK calls, so cost is an estimate at the
# uncached input rate. Claude Code rows carry tokens AND the CLI's own cost_usd; since
# 2026-09-17 they are re-priced from the tokens (quota_meter.PRICING) because the installed
# CLI 2.1.74 prices Sonnet 5 / Opus 5 / Fable at its unknown-model fallback (Opus rates).
PRICING = (
    ('claude-fable-5', 10.0, 50.0),
    ('claude-mythos-5', 10.0, 50.0),
    ('claude-opus-5', 5.0, 25.0),
    ('claude-opus-4-8', 5.0, 25.0),
    ('claude-opus-4-7', 5.0, 25.0),
    ('claude-opus-4-6', 5.0, 25.0),
    ('claude-opus-4-5', 5.0, 25.0),
    ('claude-opus-4', 15.0, 75.0),
    ('claude-3-opus', 15.0, 75.0),
    ('claude-sonnet-5', 2.0, 10.0),
    ('claude-sonnet-4', 3.0, 15.0),
    ('claude-3-7-sonnet', 3.0, 15.0),
    ('claude-3-5-sonnet', 3.0, 15.0),
    ('claude-haiku-4-5', 1.0, 5.0),
    ('claude-3-5-haiku', 0.8, 4.0),
    ('claude-3-haiku', 0.25, 1.25),
    ('gpt-4o-mini', 0.15, 0.60),
    ('gpt-4o', 2.50, 10.0),
)
_PRICING_BY_LEN = sorted(PRICING, key=lambda p: -len(p[0]))
PROVIDER_LABELS = {
    'anthropic_api': 'Anthropic API',
    'local': 'Local (Ollama)',
    'claude_code': 'Claude Code (login)',
    'openai_api': 'OpenAI API',
    'other': 'Other',
}


def _model_key(m):
    return re.sub(r'-20\d{6}$', '', str(m or '').strip()) or 'unknown'


def _price(model):
    ml = model.lower()
    for prefix, pin, pout in _PRICING_BY_LEN:
        if ml.startswith(prefix):
            return pin, pout
    return None


def _int(v):
    try:
        return int(v) if v is not None and v != '' else None
    except (TypeError, ValueError):
        return None


def _err_message(e):
    if not e:
        return ''
    s = e if isinstance(e, str) else json.dumps(e, default=str)
    m = re.search(r"'message':\s*'([^']+)'", s) or re.search(r'"message":\s*"([^"]+)"', s)
    return _short(m.group(1) if m else s, 110)


def _load_audit_file(path):
    rows = []
    for r in _iter_jsonl(path):
        direction = r.get('direction') or ''
        if direction == 'sent':  # prompt-only lines (image prompts) — not model calls
            continue
        src = r.get('source') or ''
        model = _model_key(r.get('llm') or r.get('model'))
        cost = None
        if src == 'ollama':
            provider, tin, tout = 'local', _int(r.get('prompt_eval_count')), _int(r.get('eval_count'))
        elif src == 'claude_code':
            provider, tin, tout = 'claude_code', _int(r.get('input_tokens')), _int(r.get('output_tokens'))
            cost = _num(r.get('cost_usd'))
            if model == 'unknown':
                model = 'claude-code'
        elif src == 'sdk':
            provider = 'anthropic_api' if model.startswith('claude') else 'other'
            tin, tout = _int(r.get('input_tokens')), _int(r.get('output_tokens'))
        else:
            provider, tin, tout = 'other', _int(r.get('input_tokens')), _int(r.get('output_tokens'))
        el = _num(r.get('elapsed_s'))
        if el is None and _num(r.get('duration_ms')) is not None:
            el = _num(r.get('duration_ms')) / 1000.0
        err = r.get('error') or (direction == 'error' and 'error')
        # The arch-assistant test suite's route probes run against a fake CLI path and land in the
        # production log (33 rows by 2026-09-10): "CLI not found at /nonexistent/claude".
        is_test = r.get('request') == 'route probe' or '/nonexistent/' in str(r.get('error') or '')
        # A pre-emptive REPLAY answers from the bank: the row carries the tokens the
        # recording was billed for so the saving can be measured, but nothing was spent
        # on it — it must never be repriced as money or added to tokens used (2026-09-23).
        backend = str(r.get('backend') or '')
        replayed = backend in ('preempt_replay', 'preempt_resume')
        rows.append(
            {
                'ts': _ts(r.get('ts')),
                'src': src,
                'provider': provider,
                'model': model,
                'test': is_test,
                'ptype': str(r.get('pipeline_type') or '') or 'unlabelled',
                'pid': str(r.get('pipeline_id') or ''),
                'stage': _short(r.get('stage'), 48) or '—',
                'tin': tin,
                'tout': tout,
                'cache_read': _int(r.get('cache_read_input_tokens')),
                'cache_write': _int(r.get('cache_creation_input_tokens')),
                'reported_cost': cost,
                'el': el,
                'err': _err_message(err) if err else '',
                'caveman': '',
                'backend': backend,
                'replayed': replayed,
                'preempt': str(r.get('preempt_entry') or ''),
                'preempt_mode': str(r.get('preempt_mode') or ('replay' if replayed else '')),
            }
        )
    return rows


def _load_context_ledger(path):
    rows = []
    for r in _iter_jsonl(path):
        model = _model_key(r.get('model'))
        provider = (
            'anthropic_api'
            if model.startswith('claude')
            else ('openai_api' if model.startswith(('gpt', 'o1', 'o3')) else 'other')
        )
        rows.append(
            {
                'ts': _ts(r.get('timestamp')),
                'src': 'ledger',
                'provider': provider,
                'model': model,
                'ptype': str(r.get('pipeline_type') or '') or 'unlabelled',
                'pid': str(r.get('pipeline_id') or r.get('vid_id') or ''),
                'stage': _short(r.get('stage'), 48) or '—',
                'tin': _int(r.get('prompt_tokens')),
                'tout': _int(r.get('completion_tokens')),
                'cache_read': None,
                'reported_cost': None,
                'el': None,
                'err': '',
                'caveman': str(r.get('caveman_mode') or ''),
            }
        )
    return rows


def collect_llm(now=None):
    audit_dir = os.path.join(RUNTIME, 'llm_audit')
    paths = glob.glob(os.path.join(audit_dir, '*.jsonl'))
    _prune(_load_audit_file, paths)
    audit = []
    for p in paths:
        audit.extend(_cached(p, _load_audit_file) or [])
    ledger = _cached(os.path.join(RUNTIME, 'context_ledger.jsonl'), _load_context_ledger) or []
    # llm_audit patches the Anthropic SDK once at GUI start (installed 2026-08-20). From its
    # first SDK row on, every Anthropic call that ALSO reports to the context ledger is in
    # both logs (checked per run: 7033208f 66 ledger / 67 audit) — keep the audit copy.
    cutover = min((r['ts'] for r in audit if r['src'] == 'sdk' and r['ts']), default=None)
    rows, dupes, tests = [], 0, 0
    for r in ledger:
        if cutover and r['provider'] == 'anthropic_api' and r['ts'] and r['ts'] >= cutover:
            dupes += 1
            continue
        rows.append(r)
    rows.extend(audit)
    kept = []
    for r in rows:
        if r.get('test') or _is_test_id(r['pid']):
            tests += 1
            continue
        r = dict(r)
        if r.get('replayed'):
            # Its own model row, so a tab that counts calls per model does not report a
            # recording that was answered from disk as another Opus call that was bought.
            r['cost'], r['basis'] = 0.0, 'replayed from the pre-emptive bank (nothing spent)'
            r['model'] = f'{r["model"]} · bank replay'
            kept.append(r)
            continue
        if r['provider'] == 'claude_code':
            # 2026-09-17: the CLI that ran the job (2.1.74) prices Sonnet 5 / Opus 5 / Fable at its
            # unknown-model fallback (Opus rates, flat 1.25x cache write) — a Sonnet 5 job read 2.2x
            # too high. The rows carry their tokens, so price them at list (quota_meter.PRICING);
            # the CLI's own figure only stands in when the model has no list price.
            listed = None
            if r['tin'] is not None or r['tout'] is not None:
                listed = _quota_meter().price_tokens(
                    r['model'], r['tin'], r['tout'], r.get('cache_write'), r['cache_read']
                )
            if listed is not None:
                r['cost'], r['basis'] = listed, 'list (repriced)'
            else:
                r['cost'], r['basis'] = r['reported_cost'], 'reported'
        elif r['provider'] == 'local':
            r['cost'], r['basis'] = 0.0, 'local'
        else:
            price = _price(r['model'])
            if price and (r['tin'] is not None or r['tout'] is not None):
                r['cost'] = ((r['tin'] or 0) * price[0] + (r['tout'] or 0) * price[1]) / 1e6
                r['basis'] = 'list'
            else:
                r['cost'], r['basis'] = None, ('unpriced' if not price else 'no tokens')
        kept.append(r)
    kept.sort(key=lambda r: r['ts'] or 0)
    return {
        'rows': kept,
        'ledger_rows': len(ledger),
        'audit_rows': len(audit),
        'cutover': cutover,
        'dupes_dropped': dupes,
        'excluded_test_calls': tests,
    }


def section_llm(days=30, now=None):
    now = now or time.time()
    llm = collect_llm(now)
    since = _window(days, now)
    win = [r for r in llm['rows'] if since is None or (r['ts'] or 0) >= since]
    api = ('anthropic_api', 'openai_api')

    def api_cost(rows):
        return round(sum(r['cost'] or 0 for r in rows if r['provider'] in api), 4)

    by_model: dict = {}
    by_stage: dict = {}
    errors: dict = {}
    for r in win:
        m = by_model.setdefault(
            (r['provider'], r['model']),
            {'calls': 0, 'errors': 0, 'tin': 0, 'tout': 0, 'cost': 0.0, 'priced': 0, 'els': [], 'basis': r['basis']},
        )
        m['calls'] += 1
        m['errors'] += 1 if r['err'] else 0
        m['tin'] += r['tin'] or 0
        m['tout'] += r['tout'] or 0
        if r['cost'] is not None:
            m['cost'] += r['cost']
            m['priced'] += 1
        if r['el'] is not None and not r['err']:
            m['els'].append(r['el'])
        s = by_stage.setdefault((r['ptype'], r['stage']), {'calls': 0, 'cost': 0.0, 'tokens': 0, 'providers': set()})
        s['calls'] += 1
        s['cost'] += (r['cost'] or 0) if r['provider'] in api else 0
        s['tokens'] += (r['tin'] or 0) + (r['tout'] or 0)
        s['providers'].add(r['provider'])
        if r['err']:
            e = errors.setdefault((r['provider'], r['err']), {'count': 0, 'last': 0, 'models': set()})
            e['count'] += 1
            e['last'] = max(e['last'], r['ts'] or 0)
            e['models'].add(r['model'])

    earliest = min((r['ts'] for r in llm['rows'] if r['ts']), default=None)
    keys, weekly = _bucketing(since, now, earliest)
    idx = {k: i for i, k in enumerate(keys)}
    providers = ('anthropic_api', 'local', 'claude_code', 'openai_api', 'other')
    calls = {p: [0] * len(keys) for p in providers}
    spend = [0.0] * len(keys)
    for r in win:
        if not r['ts']:
            continue
        i = idx.get(_bucket_of(r['ts'], weekly))
        if i is None:
            continue
        calls[r['provider']][i] += 1
        if r['provider'] in api:
            spend[i] += r['cost'] or 0

    tagged = [r for r in llm['rows'] if r['src'] == 'ledger' and r['caveman']]
    untagged = [r for r in llm['rows'] if r['src'] == 'ledger' and not r['caveman']]

    def avg_out(rows):
        v = [r['tout'] for r in rows if r['tout'] is not None]
        return round(sum(v) / len(v)) if v else None

    cc = [r for r in win if r['provider'] == 'claude_code']
    return {
        'totals': {
            'calls': len(win),
            'errors': sum(1 for r in win if r['err']),
            'tokens_in': sum(r['tin'] or 0 for r in win),
            'tokens_out': sum(r['tout'] or 0 for r in win),
            'api_cost_usd': api_cost(win),
            'api_calls': sum(1 for r in win if r['provider'] in api),
            'local_calls': sum(1 for r in win if r['provider'] == 'local'),
            'claude_code_calls': len(cc),
            'claude_code_cost_usd': round(sum(r['cost'] or 0 for r in cc), 4),
            'unpriced_calls': sum(1 for r in win if r['basis'] in ('unpriced', 'no tokens') and r['provider'] in api),
        },
        'all_time': {
            'calls': len(llm['rows']),
            'api_cost_usd': api_cost(llm['rows']),
            'first': _iso(earliest),
            'last': _iso(max((r['ts'] for r in llm['rows'] if r['ts']), default=None)),
        },
        'daily': {
            'bucket': 'week' if weekly else 'day',
            'keys': keys,
            'calls': [{'id': p, 'label': PROVIDER_LABELS[p], 'values': calls[p]} for p in providers if any(calls[p])],
            'spend_usd': [round(v, 4) for v in spend],
        },
        'by_model': [
            {
                'provider': p,
                'provider_label': PROVIDER_LABELS[p],
                'model': m,
                'calls': v['calls'],
                'errors': v['errors'],
                'tokens_in': v['tin'],
                'tokens_out': v['tout'],
                'cost_usd': round(v['cost'], 4) if v['priced'] else None,
                'basis': v['basis'],
                'p50_s': _pct(v['els'], 0.5),
                'p95_s': _pct(v['els'], 0.95),
            }
            for (p, m), v in sorted(by_model.items(), key=lambda kv: (-(kv[1]['cost']), -kv[1]['calls']))
        ],
        'by_stage': [
            {
                'pipeline': pt,
                'stage': st,
                'calls': v['calls'],
                'tokens': v['tokens'],
                'api_cost_usd': round(v['cost'], 4),
                'providers': sorted(PROVIDER_LABELS[p] for p in v['providers']),
            }
            for (pt, st), v in sorted(by_stage.items(), key=lambda kv: (-kv[1]['cost'], -kv[1]['calls']))
        ][:30],
        'errors': [
            {
                'provider': PROVIDER_LABELS[p],
                'message': msg,
                'count': v['count'],
                'last': _iso(v['last']),
                'models': sorted(v['models']),
            }
            for (p, msg), v in sorted(errors.items(), key=lambda kv: -kv[1]['last'])
        ][:15],
        'recent': [
            {
                'ts': _iso(r['ts']),
                'provider': PROVIDER_LABELS[r['provider']],
                'model': r['model'],
                'pipeline': r['ptype'],
                'stage': r['stage'],
                'tokens_in': r['tin'],
                'tokens_out': r['tout'],
                'cost_usd': round(r['cost'], 5) if r['cost'] is not None else None,
                'basis': r['basis'],
                'elapsed_s': r['el'],
                'error': r['err'],
            }
            for r in reversed(win[-40:])
        ],
        'pricing': [{'model_prefix': p, 'input_per_mtok': i, 'output_per_mtok': o} for p, i, o in PRICING],
        'coverage': {
            'context_ledger_rows': llm['ledger_rows'],
            'llm_audit_rows': llm['audit_rows'],
            'audit_cutover': _iso(llm['cutover']),
            'duplicate_ledger_rows_dropped': llm['dupes_dropped'],
            'excluded_test_calls': llm['excluded_test_calls'],
            'notes': [
                'Claude Code (login) rows are re-priced from their tokens at Anthropic list price (basis "list '
                '(repriced)"): the installed CLI 2.1.74 prices Sonnet 5 / Opus 5 / Fable at its unknown-model '
                'fallback. Nothing in those rows is billed per token — see the Quota tab for the subscription side.',
                'Before the audit cutover only call sites that reported tokens to the context ledger are counted.',
                'From the cutover on, every Anthropic SDK call made inside the GUI process is counted; the ledger '
                'copy of the same call is dropped.',
                'Local Ollama calls are counted only where they go through the logged helper '
                '(scripts/check_llm_logging.py lists the raw posts that bypass it).',
                'API cost is estimated at list price with no cache discount (neither log records cache hits '
                'for SDK calls). Claude Code rows use the CLI-reported cost; they run on the login, not the API key.',
            ],
        },
        'caveman': {
            'tagged_calls': len(tagged),
            'untagged_calls': len(untagged),
            'avg_completion_tagged': avg_out(tagged),
            'avg_completion_untagged': avg_out(untagged),
            'note': 'Tagged and untagged calls come from different call sites with different prompts, so the '
            'difference in averages is not a measured saving.',
        },
    }


_QUOTA_MOD = {'mod': None, 'mtime': 0.0}


def _quota_meter():
    """quota_meter, re-imported when its file changes (same hot-reload rule as this module)."""
    from zyg_workflows.devreload import maybe_reload

    mod = _QUOTA_MOD['mod']
    if mod is None:
        sys.path.insert(0, CREWS) if CREWS not in sys.path else None
        from zyg_dashboard import quota_meter as mod
    try:
        mtime = os.path.getmtime(mod.__file__)
        if _QUOTA_MOD['mod'] is not None and mtime != _QUOTA_MOD['mtime']:
            mod = maybe_reload(mod)
        _QUOTA_MOD.update(mod=mod, mtime=mtime)
    except Exception as exc:  # noqa: BLE001
        _zyg_log.info(f'[METRICS-HUB] quota_meter reload failed, keeping loaded module: {exc}')
    return mod
