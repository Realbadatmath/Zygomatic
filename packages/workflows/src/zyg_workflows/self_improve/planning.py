# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""plan_next_attempt.

Split verbatim out of zyg_workflows/self_improve.py; see docs/self_improve_split_map.md.
"""

import json
import os
import time

from zyg_workflows.self_improve.base import _jsonable, _mklog, _read_json, _write_json
from zyg_workflows.self_improve.remedies import _kb_call, kb


# ══════════════════════════════════════════════════════════════════════════════
# 11.  plan_next_attempt
# ══════════════════════════════════════════════════════════════════════════════


def plan_next_attempt(diagnosis, base_params=None, max_remedies=3, record_attempts=False, log_fn=None):
    """Turn ranked remedies into ONE concrete recipe a driver can consume verbatim.

    Conflicting remedies (two patches to the same param key) are resolved by
    score — the loser is recorded in `skipped` with the reason, so the plan is
    auditable rather than mysterious.  Blocked remedies never apply.

    ATTEMPT BOOKKEEPING — WHY THIS DEFAULTS TO OFF.  remedy_kb lowers a remedy's
    confidence for attempts that never produce a verified success (correctly: a
    fix applied ten times and never confirmed is not a fix).  But WRITING A PLAN
    IS NOT ATTEMPTING ANYTHING — no render has run.  If planning counted as an
    attempt, simply re-reading an old run would quietly discredit a working rule,
    and the loop would punish curiosity.  So:

        plan_next_attempt(...)                 free, non-committal (default)
        plan_next_attempt(record_attempts=True) a driver committing to run it
        verify_attempt(...)                    back-fills the attempt it verifies

    When it IS recorded it is idempotent per (run_dir, remedy, patch), tracked in
    <run_dir>/.self_improve_attempts.json.

    Returns {'params','applied','skipped','expected','notes'} and writes it to
    <run_dir>/next_attempt.json."""
    log = _mklog(log_fn)
    sig = diagnosis.get('signature') or {}
    remedies = diagnosis.get('remedies') or []
    kbo = kb(log_fn=log)
    params = dict(base_params or sig.get('params') or {})
    plan = {
        'ok': False,
        'run_dir': sig.get('run_dir'),
        'based_on_clip': sig.get('clip'),
        'raw_clip': sig.get('raw_clip'),
        'when': time.strftime('%Y-%m-%d %H:%M:%S'),
        'params': params,
        'applied': [],
        'skipped': [],
        'expected': [],
        'notes': [],
    }
    seen_path = os.path.join(sig.get('run_dir') or '.', '.self_improve_attempts.json')
    seen = _read_json(seen_path, {}) or {}
    try:
        claimed = {}
        for r in remedies:
            if r.get('blocked_by'):
                plan['skipped'].append({'id': r['id'], 'reason': 'blocked', 'detail': r.get('blocked_note')})
                continue
            if len(plan['applied']) >= max_remedies:
                plan['skipped'].append(
                    {'id': r['id'], 'reason': 'budget', 'detail': f'>{max_remedies} remedies per attempt'}
                )
                continue
            patch = r.get('params_patch') or {}
            clash = [k for k in patch if k in claimed]
            if clash:
                plan['skipped'].append(
                    {
                        'id': r['id'],
                        'reason': 'conflict',
                        'detail': f'{clash} already set by {claimed[clash[0]]} (higher score)',
                    }
                )
                continue
            before = dict(params)
            # `or` would be wrong here: a remedy that only REMOVES keys can
            # legitimately return an empty dict, which is falsy but correct.
            applied_params = _kb_call(kbo, 'apply', r.get('_raw') or r, params, signature=sig, log_fn=log)
            if applied_params is None:
                applied_params = _kb_call(kbo, 'apply', r.get('_raw') or r, params, log_fn=log)
            if applied_params is None:
                log(f'[self_improve] apply({r["id"]}) failed — params left unchanged')
            else:
                params = applied_params
            for k in patch:
                claimed[k] = r['id']
            plan['applied'].append(
                {
                    'id': r['id'],
                    'title': r['title'],
                    'score': r.get('score'),
                    'confidence': r.get('confidence'),
                    'severity': r.get('severity'),
                    'patch': patch,
                    'targets': r.get('targets'),
                    'bindings': r.get('bindings'),
                    'params_before': before,
                    'matched_facts': r.get('matched_facts'),
                }
            )
            # dedupe by metric: two remedies may target the same gate; the
            # higher-ranked one owns the pass condition (and keeps its predicted
            # value, which is the measured one).
            have = {e['metric'] for e in plan['expected']}
            for e in _expected_for(r, sig):
                if e['metric'] in have:
                    owner = next((x['remedy'] for x in plan['expected'] if x['metric'] == e['metric']), None)
                    plan['skipped'].append(
                        {
                            'id': r['id'],
                            'reason': 'expectation_owned',
                            'metric': e['metric'],
                            'owner': owner,
                            'detail': f'{e["metric"]} pass condition already owned by '
                            f'{owner} — both remedies ship in this attempt, so '
                            f'credit for that metric is SHARED and cannot be '
                            f'separated by measurement',
                        }
                    )
                    continue
                have.add(e['metric'])
                e['remedy'] = r['id']
                plan['expected'].append(e)
            fp = json.dumps(_jsonable(patch), sort_keys=True)
            if not record_attempts:
                pass
            elif seen.get(r['id']) == fp:
                log(f'[self_improve] attempt for {r["id"]} already recorded for this run+patch — not double-counting')
            else:
                _kb_call(kbo, 'record_attempt', r['id'], _run_id_of(sig), applied_params=patch, log_fn=log)
                seen[r['id']] = fp
        plan['params'] = params
        if not plan['applied']:
            plan['notes'].append(
                'no remedy matched — the measured signature contains '
                'no fact combination any rule covers. Add a rule or '
                'widen the measurement, do not guess.'
            )
        plan['ok'] = True
        if sig.get('run_dir'):
            _write_json(os.path.join(sig['run_dir'], 'next_attempt.json'), plan, log)
            if record_attempts:
                _write_json(seen_path, seen, log)
        log(f'[self_improve] plan: {[a["id"] for a in plan["applied"]]} ({len(plan["skipped"])} skipped)')
    except Exception as e:
        plan['error'] = str(e)[:250]
        log(f'[self_improve] plan_next_attempt failed: {e}')
    return plan


def _expected_for(remedy, sig):
    """What the remedy PROMISES, in measurable terms.

    Where the run dir already contains an artifact showing the post-remedy state
    (e.g. the raw render for 'drop the destructive step'), the prediction is that
    measured number rather than a hopeful one."""
    out = []
    binds = remedy.get('bindings') or {}
    # A remedy that REMOVES a chain step reverts the clip to that step's input,
    # and that artifact is usually already on disk — so the prediction is a
    # measured number, not a hope. `drops_a_step` is read off the patch.
    patch = remedy.get('params_patch') or {}
    drops_a_step = any(
        (str(v).lower() in ('none', 'false', '<remove>', '0')) or v is False for v in patch.values()
    ) or any('keep_box' in str(k) for k in patch)
    if remedy.get('targets') == 'region_flow':
        regions = (
            [binds['region']]
            if binds.get('region')
            else [f['region'] for f in (sig.get('failures') or []) if f['gate'].startswith('region_flow')]
        )
        for rname in regions:
            d = (sig.get('region_deltas') or {}).get(rname) or {}
            pred = d['raw'] if (drops_a_step and d.get('raw') is not None) else None
            out.append(
                {
                    'metric': f'region_flow:{rname}',
                    'kind': 'flow_norm',
                    'threshold': d.get('gate'),
                    'current': d.get('delivered'),
                    'direction': '>=',
                    'predicted': pred,
                    'evidence': 'measured on the raw render this remedy reverts to'
                    if pred is not None
                    else 'rule prior',
                }
            )
    elif remedy.get('targets') == 'prop_ncc':
        props = (
            [binds['prop']]
            if binds.get('prop')
            else [k for k, v in (sig.get('props') or {}).items() if not v.get('ok')]
        )
        for p in props:
            pv = (sig.get('props') or {}).get(p, {})
            out.append(
                {
                    'metric': f'prop_ncc:{p}',
                    'kind': 'ncc_min',
                    'threshold': pv.get('ncc_min'),
                    'current': pv.get('min_ncc'),
                    'direction': '>=',
                    'predicted': None,
                    'evidence': 'rule prior',
                }
            )
    return out


def _run_id_of(sig):
    """The ledger run_id when the run has one, else the run directory name."""
    return (sig.get('ledger') or {}).get('run_id') or sig.get('run_name') or os.path.basename(sig.get('run_dir') or '?')
