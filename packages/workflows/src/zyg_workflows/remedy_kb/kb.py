# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""kb — kb section of remedy_kb (verbatim split).

Moved unchanged from remedy_kb.py; see the package __init__ for the full docstring.
"""

from __future__ import annotations

from .core import (
    MISSING,
    _DEFAULT_SEVERITY_WEIGHTS,
    _fmt,
    _log_noop,
    _num,
    _resolve,
    json,
    kb_path,
    learned_path,
    normalize_signature,
    os,
    state_path,
)
from .evaluator import _bindings_from, _fired, evaluate, explain

# ── KB loading ───────────────────────────────────────────────────────────────

_cache = {'key': None, 'kb': None}


def _read_json(path, log_fn=None):
    try:
        with open(path, encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        return None
    except Exception as e:
        if log_fn:
            log_fn(f'[remedy_kb] unreadable {path}: {e}')
        return None


def _write_json_atomic(path, obj, log_fn=None):
    try:
        d = os.path.dirname(path)
        if d:
            os.makedirs(d, exist_ok=True)
        tmp = f'{path}.tmp.{os.getpid()}'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(obj, f, indent=1, sort_keys=False)
        os.replace(tmp, path)
        return True
    except Exception as e:
        if log_fn:
            log_fn(f'[remedy_kb] write failed {path}: {e}')
        return False


def load_state(log_fn=None):
    """{remedy_id: {attempts, successes, confidence, last_run, history:[...]}}"""
    st = _read_json(state_path(), log_fn)
    return st if isinstance(st, dict) else {}


def _save_state(state, log_fn=None):
    return _write_json_atomic(state_path(), state, log_fn)


def _mtime(path):
    try:
        return os.stat(path).st_mtime_ns
    except OSError:
        return 0


def load_kb(force=False, log_fn=None):
    """Load authored + learned rules, overlay persisted state, return the KB dict.

    {'ok', 'remedies': [...], 'severity_weights': {...}, 'sources': {...},
     'error'?}. Cached on the (mtime, mtime, mtime) of the three files so a long-lived
     Flask process picks up an edited KB without a restart. Fail-safe: a missing or
     corrupt authored file yields {'ok': False, 'remedies': []} — no advice, no crash."""
    key = (kb_path(), _mtime(kb_path()), _mtime(learned_path()), _mtime(state_path()))
    if not force and _cache['key'] == key and _cache['kb'] is not None:
        return _cache['kb']

    authored = _read_json(kb_path(), log_fn)
    if not isinstance(authored, dict):
        kb = {
            'ok': False,
            'error': f'authored KB unreadable at {kb_path()}',
            'remedies': [],
            'severity_weights': dict(_DEFAULT_SEVERITY_WEIGHTS),
            'sources': {},
        }
        _cache['key'], _cache['kb'] = key, kb
        return kb

    weights = authored.get('severity_weights')
    weights = dict(weights) if isinstance(weights, dict) else dict(_DEFAULT_SEVERITY_WEIGHTS)

    remedies, seen = [], set()
    for src, blob in (('authored', authored), ('learned', _read_json(learned_path(), log_fn))):
        if not isinstance(blob, dict):
            continue
        for r in blob.get('remedies') or []:
            if not isinstance(r, dict) or not r.get('id'):
                continue
            rid = str(r['id'])
            if rid in seen:  # authored wins over learned on id clash
                if log_fn:
                    log_fn(f'[remedy_kb] duplicate remedy id {rid!r} in {src} — authored kept')
                continue
            seen.add(rid)
            rec = dict(r)
            rec['source'] = src
            remedies.append(rec)

    state = load_state(log_fn)
    for r in remedies:
        st = state.get(r['id'])
        r['authored_confidence'] = _cf(r.get('confidence'), 0.5)
        r['prior_weight'] = max(0.0, _cf(r.get('prior_weight'), 2.0))
        if isinstance(st, dict):
            r['attempts'] = int(st.get('attempts') or 0)
            r['successes'] = int(st.get('successes') or 0)
            r['last_run'] = st.get('last_run')
        else:
            r['attempts'] = int(r.get('attempts') or 0)
            r['successes'] = int(r.get('successes') or 0)
        r['confidence'] = posterior_confidence(
            r['authored_confidence'], r['prior_weight'], r['attempts'], r['successes']
        )
    kb = {
        'ok': True,
        'remedies': remedies,
        'severity_weights': weights,
        'sources': {'authored': kb_path(), 'learned': learned_path(), 'state': state_path()},
        'updated': authored.get('_updated'),
    }
    _cache['key'], _cache['kb'] = key, kb
    return kb


def _cf(v, default):
    n = _num(v)
    return default if n is MISSING else n


def posterior_confidence(prior, prior_weight, attempts, successes):
    """THE UPDATE RULE, in one place so it can be audited and unit-tested.

        confidence = (successes + p0 * w0) / (attempts + w0)

    the mean of a Beta(p0*w0, (1-p0)*w0) prior updated by observed attempts. Zero
    attempts reproduces the authored confidence exactly; w0 sets how many real
    outcomes it takes to overrule the author. Clamped to [0.01, 0.99] — a rule is
    never certain and never worthless, both of which would stop the loop learning."""
    p0 = min(max(_cf(prior, 0.5), 0.0), 1.0)
    w0 = max(0.0, _cf(prior_weight, 2.0))
    na, ns = _num(attempts), _num(successes)  # total: junk counts as zero
    a = max(0, int(na)) if na is not MISSING else 0
    s = min(max(0, int(ns)) if ns is not MISSING else 0, a)
    denom = a + w0
    if denom <= 0:
        return round(p0, 4)
    return round(min(max((s + p0 * w0) / denom, 0.01), 0.99), 4)


def severity_weight(sev, weights=None):
    """Named severity -> rank multiplier; a numeric severity is used directly."""
    w = weights or _DEFAULT_SEVERITY_WEIGHTS
    n = _num(sev)
    if n is not MISSING:
        return min(max(n, 0.0), 1.0)
    return _cf(w.get(str(sev).lower()), 0.4)


# ── matching ─────────────────────────────────────────────────────────────────


def match(signature, kb=None, include_unproven=True, min_rank=0.0, log_fn=None):
    """Ranked list of remedies whose precondition fires on this signature.

    Rank = posterior confidence * severity weight, so a proven critical rule outranks
    an unproven minor one even when both fire. Each returned remedy is a COPY carrying:
        'rank_score', 'confidence', 'severity_weight'
        'match': {'trace', 'clauses', 'bindings', 'action_preview', 'explanation'}
        'resolved_action': the branch selected for this signature, with placeholders
                           already substituted from the bindings
    Never raises; on any internal error it returns [] and logs."""
    log = log_fn or _log_noop
    try:
        kb = kb or load_kb(log_fn=log_fn)
        sig, notes = normalize_signature(signature)
        for n in notes:
            log(f'[remedy_kb] signature: {n}')
        weights = kb.get('severity_weights') or _DEFAULT_SEVERITY_WEIGHTS
        out = []
        for r in kb.get('remedies') or []:
            if not include_unproven and str(r.get('status', '')).lower() in ('unproven', 'refuted'):
                continue
            ok, trace = evaluate(r.get('precondition'), sig)
            if not ok:
                continue
            rec = dict(r)
            bindings = _bindings_from(trace)
            sw = severity_weight(rec.get('severity'), weights)
            rec['severity_weight'] = round(sw, 3)
            rec['rank_score'] = round(_cf(rec.get('confidence'), 0.5) * sw, 4)
            resolved = _resolve_action(rec.get('action'), sig, bindings)
            rec['resolved_action'] = resolved
            rec['match'] = {
                'trace': trace,
                'clauses': [('  ' * d) + t for d, t in _fired(trace)],
                'bindings': {k: v[0] for k, v in bindings.items()},
                'action_preview': {'set': resolved.get('set') or {}, 'remove': resolved.get('remove') or []},
            }
            rec['match']['explanation'] = explain(rec)
            if rec['rank_score'] >= min_rank:
                out.append(rec)
        out.sort(key=lambda x: (-x['rank_score'], str(x.get('id'))))
        return out
    except Exception as e:
        log(f'[remedy_kb] match failed (no advice): {e}')
        return []


def diagnose(signature, **kw):
    """Fail-safe dict wrapper around match() for callers that want the house
    {'ok', ...} contract plus the signature-normalization audit notes."""
    try:
        sig, notes = normalize_signature(signature)
        ranked = match(signature, **kw)
        return {
            'ok': True,
            'notes': notes,
            'n': len(ranked),
            'ranked': [
                {
                    'id': r['id'],
                    'rank_score': r['rank_score'],
                    'confidence': r['confidence'],
                    'severity': r.get('severity'),
                    'status': r.get('status'),
                    'action': r['match']['action_preview'],
                    'explanation': r['match']['explanation'],
                }
                for r in ranked
            ],
            'signature_keys': sorted(sig.keys()),
        }
    except Exception as e:
        return {'ok': False, 'error': str(e)[:300], 'ranked': []}


# ── actions ──────────────────────────────────────────────────────────────────


def _subst(value, sig, bindings):
    """Placeholder substitution in an action.

    '{$p._key}' anywhere in a string is replaced by the bound value. When the string
    is EXACTLY one placeholder the RAW resolved object is returned instead of its text,
    so an action can carry a box list ('{$p.box}' -> [0.495, 0.7, 0.825, 0.92]) and not
    a stringified one. Unresolvable placeholders are left verbatim so a broken template
    is visible in the diff instead of silently becoming 'None'."""
    if isinstance(value, dict):
        return {_subst(k, sig, bindings): _subst(v, sig, bindings) for k, v in value.items()}
    if isinstance(value, list):
        return [_subst(v, sig, bindings) for v in value]
    if not isinstance(value, str) or '{$' not in value:
        return value
    whole = value.strip()
    if whole.startswith('{$') and whole.endswith('}') and whole.count('{') == 1:
        r = _resolve(whole[1:-1], sig, bindings)
        return value if r is MISSING else r
    out, i = [], 0
    while i < len(value):
        j = value.find('{$', i)
        if j < 0:
            out.append(value[i:])
            break
        k = value.find('}', j)
        if k < 0:
            out.append(value[i:])
            break
        out.append(value[i:j])
        r = _resolve(value[j + 1 : k], sig, bindings)
        out.append(value[j : k + 1] if r is MISSING else _fmt(r).strip("'"))
        i = k + 1
    return ''.join(out)


def _resolve_action(action, sig, bindings):
    """Pick the applicable branch of an action and substitute its placeholders.

    An action is either a plain {'set': {...}, 'remove': [...], 'because': str} or a
    {'branches': [{'when': <predicate>, 'set': ...}, ..., {'set': ...}]} where the
    LAST branch may omit 'when' and acts as the default. Branching exists because a
    correct remedy is sometimes conditional: freeing a frozen occluder means dropping
    the paste-back when the pinned props are independently stable, and switching to a
    per-frame keep-mask when they are not."""
    if not isinstance(action, dict):
        return {'set': {}, 'remove': [], 'because': ''}
    if isinstance(action.get('branches'), list):
        chosen = None
        for br in action['branches']:
            if not isinstance(br, dict):
                continue
            if 'when' not in br:
                chosen = br
                break
            ok, _t = evaluate(br['when'], sig, bindings)
            if ok:
                chosen = br
                break
        if chosen is None:
            return {'set': {}, 'remove': [], 'because': 'no branch applied'}
        action = chosen
    return {
        'set': _subst(action.get('set') or {}, sig, bindings),
        'remove': _subst(action.get('remove') or [], sig, bindings),
        'because': _subst(action.get('because') or '', sig, bindings),
    }


def _set_dotted(root, path, value):
    parts = str(path).split('.')
    cur = root
    for p in parts[:-1]:
        nxt = cur.get(p)
        if not isinstance(nxt, dict):
            nxt = {}
            cur[p] = nxt
        cur = nxt
    cur[parts[-1]] = value


def _del_dotted(root, path):
    parts = str(path).split('.')
    cur = root
    for p in parts[:-1]:
        cur = cur.get(p)
        if not isinstance(cur, dict):
            return False
    return cur.pop(parts[-1], MISSING) is not MISSING


def apply(remedy, params, signature=None, log_fn=None):
    """PURE: return a new params dict with the remedy's action applied.

    `params` is deep-copied and never mutated, so a caller can preview several
    remedies against the same baseline before committing to one. Action keys are
    DOTTED ('probe.context_windows' -> params['probe']['context_windows']); 'remove'
    deletes dotted keys. Uses the branch already resolved by match() when present,
    otherwise resolves against `signature`. Fail-safe: on any error the ORIGINAL
    params are returned unchanged (never a half-applied config)."""
    log = log_fn or _log_noop
    try:
        base = json.loads(json.dumps(params if isinstance(params, dict) else {}, default=str))
        act = remedy.get('resolved_action') if isinstance(remedy, dict) else None
        if act is None:
            sig, _n = normalize_signature(signature or {})
            bindings = {}
            if isinstance(remedy, dict) and remedy.get('precondition') is not None:
                ok, trace = evaluate(remedy.get('precondition'), sig)
                if ok:
                    bindings = _bindings_from(trace)
            act = _resolve_action((remedy or {}).get('action'), sig, bindings)
        for k, v in (act.get('set') or {}).items():
            _set_dotted(base, k, v)
            log(f'[remedy_kb] set {k} = {json.dumps(v, default=str)}')
        for k in act.get('remove') or []:
            if _del_dotted(base, k):
                log(f'[remedy_kb] removed {k}')
            else:
                log(f'[remedy_kb] remove {k}: not present (no-op)')
        return base
    except Exception as e:
        log(f'[remedy_kb] apply failed (params unchanged): {e}')
        return params if isinstance(params, dict) else {}
