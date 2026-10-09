# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""learning — learning section of remedy_kb (verbatim split).

Moved unchanged from remedy_kb.py; see the package __init__ for the full docstring.
"""

from __future__ import annotations

from .core import MISSING, _LOCK, _fmt, _log_noop, _num, _zyg_log, json, kb_path, learned_path, time
from .evaluator import evaluate
from .kb import _cf, _read_json, _save_state, _write_json_atomic, apply, load_kb, load_state, posterior_confidence

# ── learning ─────────────────────────────────────────────────────────────────


def _ledger(log_fn=None):
    """Lazy run_ledger import — the KB records its own hit-rate as gates so
    run_ledger.trends() can show a remedy quietly ceasing to work. Absent ledger is
    fine; learning must not depend on it."""
    try:
        from zyg_workflows import run_ledger

        return run_ledger
    except Exception as e:
        if log_fn:
            log_fn(f'[remedy_kb] run_ledger unavailable (ignored): {e}')
        return None


def record_attempt(remedy_id, run_id, applied_params=None, log_fn=None):
    """Record that a remedy was APPLIED to a run (before the outcome is known).

    Attempts and successes are counted separately on purpose: a remedy that is applied
    ten times and never verified must not look like a remedy that works. Returns the
    updated state row, or {'ok': False, 'error': ...}."""
    log = log_fn or _log_noop
    try:
        rid = str(remedy_id)
        with _LOCK:
            state = load_state(log_fn)
            row = state.get(rid) if isinstance(state.get(rid), dict) else {}
            row['attempts'] = int(row.get('attempts') or 0) + 1
            row['successes'] = int(row.get('successes') or 0)
            row['last_run'] = str(run_id)
            row['last_applied'] = time.strftime('%Y-%m-%d %H:%M:%S')
            hist = row.get('history') if isinstance(row.get('history'), list) else []
            hist.append(
                {'event': 'attempt', 'run_id': str(run_id), 'ts': row['last_applied'], 'params': _small(applied_params)}
            )
            row['history'] = hist[-200:]
            state[rid] = row
            _save_state(state, log_fn)
        log(f'[remedy_kb] attempt #{row["attempts"]} of {rid} on run {run_id}')
        return {'ok': True, 'remedy_id': rid, **{k: row[k] for k in ('attempts', 'successes')}}
    except Exception as e:
        log(f'[remedy_kb] record_attempt failed (ignored): {e}')
        return {'ok': False, 'error': str(e)[:200]}


def record_outcome(remedy_id, run_id, metric, before, after, threshold=None, direction='up', success=None, log_fn=None):
    """Record the MEASURED result of a remedy and update its confidence.

    SUCCESS (in priority order):
      1. an explicit success=True/False from the caller;
      2. otherwise, if `threshold` is given: the metric CROSSED it — for a minimum
         gate (before < threshold) success means after >= threshold; for a maximum
         gate (before > threshold) success means after <= threshold. Crossing, not
         improving: 0.080 -> 0.110 against a 0.12 gate is still a failed clip;
      3. otherwise: movement in `direction` ('up' | 'down').

    Confidence is recomputed by posterior_confidence(). The outcome is also written to
    run_ledger as gate 'remedy:<id>' so a decaying remedy shows up in trends(days).
    Returns {'ok', 'success', 'confidence', 'attempts', 'successes', 'reason'}."""
    log = log_fn or _log_noop
    try:
        rid = str(remedy_id)
        b, a = _num(before), _num(after)
        thr = _num(threshold) if threshold is not None else MISSING
        if success is not None:
            ok = bool(success)
            reason = f'caller asserted success={ok}'
        elif thr is not MISSING and b is not MISSING and a is not MISSING:
            if b <= thr:  # was below a MINIMUM gate
                ok = a >= thr
                reason = f'{metric} {b:g} -> {a:g} vs minimum gate {thr:g}: {"CROSSED" if ok else "still below"}'
            else:  # was above a MAXIMUM gate
                ok = a <= thr
                reason = f'{metric} {b:g} -> {a:g} vs maximum gate {thr:g}: {"CROSSED" if ok else "still above"}'
        elif b is not MISSING and a is not MISSING:
            ok = (a > b) if str(direction) != 'down' else (a < b)
            reason = f'{metric} {b:g} -> {a:g} moving {direction}: {"better" if ok else "not better"}'
        else:
            ok = False
            reason = f'{metric}: before/after not both numeric ({_fmt(before)} -> {_fmt(after)})'

        with _LOCK:
            state = load_state(log_fn)
            row = state.get(rid) if isinstance(state.get(rid), dict) else {}
            attempts = int(row.get('attempts') or 0)
            outcomes = int(row.get('outcomes') or 0)
            if outcomes >= attempts:  # outcome without a recorded attempt
                attempts += 1  # (e.g. a remedy applied by hand)
            row['attempts'] = attempts
            row['outcomes'] = outcomes + 1
            row['successes'] = int(row.get('successes') or 0) + (1 if ok else 0)
            row['last_run'] = str(run_id)
            row['last_outcome'] = time.strftime('%Y-%m-%d %H:%M:%S')
            hist = row.get('history') if isinstance(row.get('history'), list) else []
            hist.append(
                {
                    'event': 'outcome',
                    'run_id': str(run_id),
                    'metric': str(metric),
                    'before': None if b is MISSING else b,
                    'after': None if a is MISSING else a,
                    'threshold': None if thr is MISSING else thr,
                    'success': ok,
                    'reason': reason,
                    'ts': row['last_outcome'],
                }
            )
            row['history'] = hist[-200:]
            state[rid] = row
            _save_state(state, log_fn)

        authored = _authored_prior(rid, log_fn)
        conf = posterior_confidence(authored[0], authored[1], row['attempts'], row['successes'])
        with _LOCK:
            state = load_state(log_fn)
            if isinstance(state.get(rid), dict):
                state[rid]['confidence'] = conf
                _save_state(state, log_fn)
        load_kb(force=True, log_fn=log_fn)  # invalidate the cache

        led = _ledger(log_fn)
        if led is not None:
            try:
                led.record_gate(
                    run_id,
                    f'remedy:{rid}',
                    'pass' if ok else 'fail',
                    score=None if a is MISSING else a,
                    tag='remedy_outcome',
                )
            except Exception as _exc:
                _zyg_log.warning('ledger gate record for remedy %s failed, outcome kept in the kb only: %s', rid, _exc)
        log(f'[remedy_kb] outcome {rid} on {run_id}: {"SUCCESS" if ok else "FAILURE"} ({reason}) -> confidence {conf}')
        return {
            'ok': True,
            'remedy_id': rid,
            'success': ok,
            'reason': reason,
            'confidence': conf,
            'attempts': row['attempts'],
            'successes': row['successes'],
        }
    except Exception as e:
        log(f'[remedy_kb] record_outcome failed (ignored): {e}')
        return {'ok': False, 'error': str(e)[:200]}


def _authored_prior(remedy_id, log_fn=None):
    """(authored_confidence, prior_weight) straight from the FILES, never from the
    state — otherwise the posterior would feed on itself and drift."""
    for path in (kb_path(), learned_path()):
        blob = _read_json(path, log_fn)
        if not isinstance(blob, dict):
            continue
        for r in blob.get('remedies') or []:
            if isinstance(r, dict) and str(r.get('id')) == str(remedy_id):
                return (_cf(r.get('confidence'), 0.5), max(0.0, _cf(r.get('prior_weight'), 2.0)))
    return (0.5, 2.0)


def _small(obj, limit=1200):
    try:
        s = json.dumps(obj, default=str, sort_keys=True)
        return json.loads(s) if len(s) <= limit else s[:limit] + '…'
    except Exception:
        return None


def add_remedy(remedy, log_fn=None):
    """Persist a NEWLY LEARNED rule to data/runtime/remedy_kb_learned.json.

    Learned rules go to their own file so config/remedy_kb.json stays hand-authored
    and diffable — a machine that rewrites the file humans audit is not auditable.
    The precondition is validated by evaluating it against an EMPTY signature: a
    well-formed rule must return False there (no match, no exception). A rule that
    fires on an empty signature would fire on everything and is REJECTED.
    Returns {'ok', 'id'} or {'ok': False, 'error'}."""
    log = log_fn or _log_noop
    try:
        if not isinstance(remedy, dict) or not remedy.get('id'):
            return {'ok': False, 'error': 'remedy needs an id'}
        rid = str(remedy['id'])
        if remedy.get('precondition') is None:
            return {'ok': False, 'error': 'remedy needs a precondition'}
        fires_on_nothing, _t = evaluate(remedy['precondition'], {})
        if fires_on_nothing:
            return {
                'ok': False,
                'error': 'precondition fires on an EMPTY signature — it would match every run; rejected',
            }
        rec = dict(remedy)
        rec.setdefault('severity', 'minor')
        rec.setdefault('status', 'unproven')
        rec.setdefault('confidence', 0.3)
        rec.setdefault('prior_weight', 2.0)
        rec.setdefault('attempts', 0)
        rec.setdefault('successes', 0)
        rec.setdefault('evidence', [])
        rec.setdefault('tags', [])
        rec['learned_at'] = time.strftime('%Y-%m-%d %H:%M:%S')
        with _LOCK:
            blob = _read_json(learned_path(), log_fn)
            if not isinstance(blob, dict):
                blob = {
                    '_doc': 'Rules LEARNED at runtime by remedy_kb.add_remedy(). '
                    'Authored rules live in config/remedy_kb.json and are '
                    'never rewritten by the machine.',
                    'remedies': [],
                }
            rem = [r for r in (blob.get('remedies') or []) if not (isinstance(r, dict) and str(r.get('id')) == rid)]
            rem.append(rec)
            blob['remedies'] = rem
            blob['_updated'] = rec['learned_at']
            _write_json_atomic(learned_path(), blob, log_fn)
        load_kb(force=True, log_fn=log_fn)
        log(f'[remedy_kb] learned remedy {rid} persisted')
        return {'ok': True, 'id': rid, 'path': learned_path()}
    except Exception as e:
        log(f'[remedy_kb] add_remedy failed (ignored): {e}')
        return {'ok': False, 'error': str(e)[:200]}


# ── reporting ────────────────────────────────────────────────────────────────


def format_ranked(ranked, params=None):
    """Fixed-width, pasteable rendering of match() — the thing a human reads to check
    the machine's reasoning without re-deriving it."""
    if not ranked:
        return 'remedy_kb: NO REMEDY MATCHED this signature.'
    L = [f'remedy_kb: {len(ranked)} remedy(ies) matched, ranked by confidence x severity', '']
    for i, r in enumerate(ranked, 1):
        L.append(
            f'{i}. {r["id"]}   rank={r["rank_score"]}  '
            f'(confidence {r["confidence"]} x severity {r.get("severity")} '
            f'{r["severity_weight"]})  status={r.get("status")}  '
            f'attempts={r.get("attempts")} successes={r.get("successes")}'
        )
        L.append(f'   {r.get("title", "")}')
        for c in r['match']['clauses']:
            L.append(f'     - {c}')
        act = r['match']['action_preview']
        if act.get('set'):
            L.append(f'   ACTION set    : {json.dumps(act["set"], sort_keys=True)}')
        if act.get('remove'):
            L.append(f'   ACTION remove : {json.dumps(act["remove"])}')
        because = (r.get('resolved_action') or {}).get('because')
        if because:
            L.append(f'   WHY    : {because}')
        if params is not None:
            L.append(f'   PARAMS : {json.dumps(apply(r, params), sort_keys=True)}')
        L.append('')
    return '\n'.join(L)
