# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""verify_attempt — THE LEARNING STEP.

Split verbatim out of zyg_workflows/self_improve.py; see docs/self_improve_split_map.md.
"""

import json
import os
import time

from zyg_workflows.self_improve.base import _jsonable, _mklog, _read_json, _write_json
from zyg_workflows.self_improve.chain import detect_chain
from zyg_workflows.self_improve.measure import _find_clip, load_qc_spec, measure_clip
from zyg_workflows.self_improve.remedies import _kb_call, _kb_confidence, _kb_writes_ledger, kb
from zyg_workflows.self_improve.signature import _ledger_view
from zyg_workflows.self_improve.planning import _run_id_of


# ══════════════════════════════════════════════════════════════════════════════
# 12.  verify_attempt — THE LEARNING STEP
# ══════════════════════════════════════════════════════════════════════════════


def verify_attempt(prev_run_dir, new_run_dir, prev_clip=None, new_clip=None, plan=None, log_fn=None):
    """Did the remedies applied in prev→new actually move their target metrics?

    Reads <prev_run_dir>/next_attempt.json for what was applied and promised,
    re-measures BOTH clips with the same gates and the same geometry
    normalisation, and calls remedy_kb.record_outcome for every remedy — the only
    write-back in the system that makes the KB better than its priors.

    prev_clip / new_clip override which artifact represents each side, which is
    how an A/B inside a single run directory is verified.

    Writes <new_run_dir>/verification.json. Returns that dict."""
    log = _mklog(log_fn)
    prev_run_dir = os.path.abspath(prev_run_dir)
    new_run_dir = os.path.abspath(new_run_dir)
    out = {
        'ok': False,
        'prev_run_dir': prev_run_dir,
        'new_run_dir': new_run_dir,
        'when': time.strftime('%Y-%m-%d %H:%M:%S'),
        'results': [],
        'learned': [],
    }
    try:
        plan = plan or _read_json(os.path.join(prev_run_dir, 'next_attempt.json'))
        if not plan:
            out['error'] = f'no next_attempt.json in {prev_run_dir} — run `diagnose`/`plan` on it first'
            log(f'[self_improve] {out["error"]}')
            _write_json(os.path.join(new_run_dir, 'verification.json'), out, log)
            return out
        out['plan'] = {'applied': plan.get('applied'), 'expected': plan.get('expected')}

        spec_prev = load_qc_spec(prev_run_dir, log_fn=log)
        spec_new = load_qc_spec(new_run_dir, log_fn=log)
        regions = {k: tuple(v) for k, v in (spec_new.get('regions') or spec_prev.get('regions') or {}).items()}
        chain_prev = detect_chain(prev_run_dir, log_fn=None)
        chain_new = detect_chain(new_run_dir, log_fn=None)
        pclip = prev_clip or plan.get('based_on_clip') or _find_clip(prev_run_dir, chain_prev)
        nclip = new_clip or _find_clip(new_run_dir, chain_new)
        out['prev_clip'], out['new_clip'] = pclip, nclip
        log(f'[self_improve] verify: {os.path.basename(pclip)} → {os.path.basename(nclip)}')

        prop_boxes = dict(spec_new.get('prop_boxes') or spec_prev.get('prop_boxes') or {})
        mp = measure_clip(
            pclip,
            regions,
            spec_prev.get('min_flow'),
            spec_prev.get('max_churn'),
            prop_boxes,
            cache_dir=prev_run_dir,
            log_fn=log,
        )
        mn = measure_clip(
            nclip,
            regions,
            spec_new.get('min_flow'),
            spec_new.get('max_churn'),
            prop_boxes,
            cache_dir=new_run_dir,
            log_fn=log,
        )
        out['measured'] = {'prev': mp, 'new': mn}
        if not (mp.get('ok') and mn.get('ok')):
            out['error'] = 'measurement failed on one side'
            _write_json(os.path.join(new_run_dir, 'verification.json'), out, log)
            return out

        kbo = kb(log_fn=log)
        # Learning must reflect DISTINCT evidence. Re-verifying the same
        # (prev_clip → new_clip) pair is the same measurement read twice, so the
        # outcome is reported again but NOT taught again.
        taught_path = os.path.join(new_run_dir, '.self_improve_verified.json')
        taught = _read_json(taught_path, {}) or {}
        attempted_path = os.path.join(prev_run_dir, '.self_improve_attempts.json')
        attempted = _read_json(attempted_path, {}) or {}
        pair_fp = f'{os.path.basename(pclip)}→{os.path.basename(nclip)}'
        for applied in plan.get('applied') or []:
            rid = applied['id']
            targets = [e for e in (plan.get('expected') or []) if _expected_belongs(e, applied, plan)]
            shared = False
            if not targets:
                # its pass condition was transferred to a higher-ranked remedy
                # that shipped in the SAME attempt — verify against that metric
                # but flag the credit as shared rather than inventing a target.
                mine = {
                    s.get('metric')
                    for s in (plan.get('skipped') or [])
                    if s.get('id') == rid and s.get('reason') == 'expectation_owned' and s.get('metric')
                }
                targets = [e for e in (plan.get('expected') or []) if e.get('metric') in mine]
                shared = bool(targets)
            rows = []
            for e in targets:
                metric = e.get('metric', '')
                if metric.startswith('region_flow:'):
                    rn = metric.split(':', 1)[1]
                    b = (mp['regions'] or {}).get(rn)
                    a = (mn['regions'] or {}).get(rn)
                    if not (a and b):
                        continue
                    thr = e.get('threshold') or a['gate_min_flow']
                    rows.append(
                        {
                            'metric': metric,
                            'kind': 'flow_norm',
                            'threshold': thr,
                            'before': b['flow_norm'],
                            'after': a['flow_norm'],
                            'before_px': b['flow_mean'],
                            'after_px': a['flow_mean'],
                            'before_geometry': mp['geometry'],
                            'after_geometry': mn['geometry'],
                            'predicted': e.get('predicted'),
                            'crossed': bool(b['flow_norm'] < thr <= a['flow_norm']),
                            'improved': bool(a['flow_norm'] > b['flow_norm']),
                            'now_ok': bool(a['flow_norm'] >= thr),
                        }
                    )
                elif metric.startswith('prop_ncc:'):
                    pn = metric.split(':', 1)[1]
                    b = (mp['props'] or {}).get(pn) or (mp['props'] or {}).get('keep:' + pn)
                    a = (mn['props'] or {}).get(pn) or (mn['props'] or {}).get('keep:' + pn)
                    if not (a and b):
                        continue
                    thr = e.get('threshold') or a['gate_ncc_min']
                    rows.append(
                        {
                            'metric': metric,
                            'kind': 'ncc_min',
                            'threshold': thr,
                            'before': b['ncc_min'],
                            'after': a['ncc_min'],
                            'predicted': e.get('predicted'),
                            'crossed': bool((b['ncc_min'] or 0) < thr <= (a['ncc_min'] or 0)),
                            'improved': bool((a['ncc_min'] or 0) > (b['ncc_min'] or 0)),
                            'now_ok': bool((a['ncc_min'] or 0) >= thr),
                        }
                    )
            ok = bool(rows) and all(r['now_ok'] for r in rows)
            verdict = (
                'NO TARGET METRIC MEASURABLE'
                if not rows
                else (
                    ('CONFIRMED (shared credit)' if shared else 'CONFIRMED')
                    if ok
                    else ('REFUTED (shared credit)' if shared else 'REFUTED')
                )
            )
            before_c = _kb_confidence(kbo, rid)
            # The metric that DEFINES the outcome is the one that was failing, not
            # merely the first — a remedy must not be credited for a gate that was
            # already green.
            key = next((r for r in rows if r['before'] < (r['threshold'] or 0)), rows[0] if rows else None)
            new_run_id = _run_id_of(
                {'run_dir': new_run_dir, 'run_name': os.path.basename(new_run_dir), 'ledger': _ledger_view(new_run_dir)}
            )
            already = taught.get(rid) == pair_fp
            if already:
                log(
                    f'[self_improve] {rid}: this exact clip pair was already taught '
                    f'to the KB — reporting, not re-learning'
                )
            else:
                # A verification PROVES the attempt actually happened, so back-fill
                # the attempt here if planning did not record it (planning is
                # non-committal by default — see plan_next_attempt).
                fp = json.dumps(_jsonable(applied.get('patch') or {}), sort_keys=True)
                if attempted.get(rid) != fp:
                    _kb_call(kbo, 'record_attempt', rid, new_run_id, applied_params=applied.get('patch'), log_fn=log)
                    attempted[rid] = fp
                _kb_call(
                    kbo,
                    'record_outcome',
                    rid,
                    new_run_id,
                    (key or {}).get('metric'),
                    (key or {}).get('before'),
                    (key or {}).get('after'),
                    threshold=(key or {}).get('threshold'),
                    direction='up',
                    success=ok,
                    log_fn=log,
                )
                taught[rid] = pair_fp
            after_c = _kb_confidence(kbo, rid)
            out['results'].append(
                {
                    'remedy': rid,
                    'title': applied.get('title'),
                    'verdict': verdict,
                    'ok': ok,
                    'shared_credit': shared,
                    'decided_by': (key or {}).get('metric'),
                    'metrics': rows,
                }
            )
            out['learned'].append(
                {
                    'remedy': rid,
                    'ok': ok,
                    'confidence_before': before_c,
                    'confidence_after': after_c,
                    'taught': not already,
                    'kb': getattr(kbo, 'name', getattr(kbo, '__name__', '?')),
                }
            )
            for r in rows:
                log(
                    f'[self_improve] {rid}: {r["metric"]} {r["before"]} → {r["after"]} '
                    f'(gate {r["threshold"]}) → '
                    f'{"CROSSED" if r["crossed"] else ("still ok" if r["now_ok"] else "STILL FAILING")}'
                )
            if not _kb_writes_ledger(kbo):
                _ledger_record_verification(new_run_dir, rid, ok, rows, log_fn=log)

        if not (plan.get('applied') or []):
            out['note'] = 'the previous plan applied NO remedies, so there is nothing to verify — this is not a pass'
            log(f'[self_improve] {out["note"]}')
        out['ok'] = True
        _write_json(taught_path, taught, log)
        _write_json(attempted_path, attempted, log)
        _write_json(os.path.join(new_run_dir, 'verification.json'), out, log)
        log(f'[self_improve] verification written → {new_run_dir}/verification.json')
    except Exception as e:
        import traceback

        out['error'] = str(e)[:300]
        out['traceback'] = traceback.format_exc()[-1200:]
        log(f'[self_improve] verify_attempt failed: {e}')
    return out


def _expected_belongs(expected, applied, _plan):
    """Which pass conditions this particular remedy is answerable for.

    plan_next_attempt stamps `remedy` onto each expectation it keeps, so this is
    normally an exact match; the binding/target checks are the fallback for plans
    written before that field existed."""
    if expected.get('remedy'):
        return expected['remedy'] == applied.get('id')
    b = applied.get('bindings') or {}
    m = expected.get('metric', '')
    if b.get('region') and m.endswith(':' + str(b['region'])):
        return True
    if b.get('prop') and m.endswith(':' + str(b['prop'])):
        return True
    return applied.get('targets') and m.startswith(str(applied['targets']).split('_')[0])


def _ledger_record_verification(run_dir, remedy_id, ok, rows, log_fn=None):
    """Write the verification back into the run ledger so `trends()` sees remedy
    outcomes alongside ordinary QC gates — cross-run memory in one place."""
    try:
        from zyg_workflows import run_ledger as RL

        rep = _read_json(os.path.join(run_dir, 'debug', 'report.json'), {}) or {}
        rid = (rep.get('verdict') or {}).get('run_id') or os.path.basename(run_dir)
        RL.record_gate(
            rid,
            f'remedy:{remedy_id}',
            'pass' if ok else 'fail',
            score=(rows[0]['after'] if rows else None),
            tag='self-improve',
            log_fn=None,
        )
    except Exception as e:
        _mklog(log_fn)(f'[self_improve] ledger write skipped: {e}')
