# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""evaluator — evaluator section of remedy_kb (verbatim split).

Moved unchanged from remedy_kb.py; see the package __init__ for the full docstring.
"""

from __future__ import annotations

from .core import MISSING, _MAX_DEPTH, _box, _fmt, _is_num, _num, _overlap, _resolve, json, normalize_signature

# ── the evaluator ────────────────────────────────────────────────────────────


def _T(op, ok, text, children=None, bad=False):
    """One trace node. `bad` marks STRUCTURAL invalidity (malformed node, unknown
    operator, depth blown) as opposed to an honest measured False.

    The distinction is load-bearing: 'not' over an honest False is True, but 'not'
    over a MALFORMED child must stay False, or a single corrupt KB entry would
    invert into a rule that fires on every run. Badness therefore propagates up
    through all/any/not."""
    t = {'op': op, 'ok': bool(ok), 'text': text, 'children': children or []}
    if bad:
        t['bad'] = True
    return t


def _bad(trace):
    """True when this node or any child is structurally malformed."""
    if not isinstance(trace, dict):
        return True
    if trace.get('bad'):
        return True
    return any(_bad(k) for k in (trace.get('children') or []))


def _eval(pred, sig, bindings=None, depth=0):
    """Evaluate a predicate node -> (bool, trace).

    TOTAL by construction: unknown operator, malformed node, missing path,
    non-numeric comparison or excessive depth all return (False, trace-with-reason).
    Nothing here raises, so a corrupt KB entry costs one non-matching rule rather
    than a crashed pipeline. `bindings` accumulates down the tree so an inner
    quantifier can compare against an outer one's bound item."""
    bindings = bindings if bindings is not None else {}
    if depth > _MAX_DEPTH:
        return False, _T('depth', False, f'nesting deeper than {_MAX_DEPTH} — refused', bad=True)

    if isinstance(pred, bool):
        return pred, _T('lit', pred, f'literal {pred}')
    if not isinstance(pred, dict) or len(pred) != 1:
        return False, _T('malformed', False, f'not a single-operator object: {_fmt(pred)}', bad=True)

    op, arg = next(iter(pred.items()))

    # ── logic ────────────────────────────────────────────────────────────────
    if op in ('all', 'any'):
        if not isinstance(arg, list):
            return False, _T(op, False, f'{op} expects a list, got {_fmt(arg)}', bad=True)
        kids = [_eval(p, sig, bindings, depth + 1) for p in arg]
        traces = [t for _v, t in kids]
        vals = [v for v, _t in kids]
        broken = any(_bad(t) for t in traces)
        ok = (all(vals) if op == 'all' else any(vals)) and not broken
        return ok, _T(
            op,
            ok,
            f'{op} of {len(vals)} clause(s)' + (' — contains a MALFORMED clause, forced false' if broken else ''),
            traces,
            bad=broken,
        )

    if op == 'not':
        v, t = _eval(arg, sig, bindings, depth + 1)
        if _bad(t):  # never let a corrupt clause INVERT into a match
            return False, _T('not', False, 'not of a MALFORMED clause — forced false', [t], bad=True)
        return (not v), _T('not', not v, 'not', [t])

    # ── comparisons ──────────────────────────────────────────────────────────
    if op in ('lt', 'lte', 'gt', 'gte'):
        if not isinstance(arg, list) or len(arg) != 2:
            return False, _T(op, False, f'{op} expects [a, b], got {_fmt(arg)}', bad=True)
        ra, rb = _resolve(arg[0], sig, bindings), _resolve(arg[1], sig, bindings)
        a, b = _num(ra), _num(rb)
        if a is MISSING or b is MISSING:
            return False, _T(
                op, False, f'{_desc(arg[0])} {_SYM[op]} {_desc(arg[1])} — not comparable ({_fmt(ra)} vs {_fmt(rb)})'
            )
        ok = {'lt': a < b, 'lte': a <= b, 'gt': a > b, 'gte': a >= b}[op]
        return ok, _T(op, ok, f'{_side(arg[0], a)} {_SYM[op]} {_side(arg[1], b)}')

    if op in ('eq', 'ne'):
        if not isinstance(arg, list) or len(arg) != 2:
            return False, _T(op, False, f'{op} expects [a, b], got {_fmt(arg)}', bad=True)
        ra, rb = _resolve(arg[0], sig, bindings), _resolve(arg[1], sig, bindings)
        if ra is MISSING or rb is MISSING:
            # FAIL CLOSED on ignorance: 'ne' must not become true just because a
            # field is absent, or every rule fires on an empty signature.
            return False, _T(
                op, False, f'{_desc(arg[0])} {_SYM[op]} {_desc(arg[1])} — unknown ({_fmt(ra)} vs {_fmt(rb)})'
            )
        if _is_num(ra) and _is_num(rb):
            same = abs(float(ra) - float(rb)) <= 1e-9
        else:
            same = ra == rb
        ok = same if op == 'eq' else (not same)
        return ok, _T(op, ok, f'{_side(arg[0], ra)} {_SYM[op]} {_side(arg[1], rb)}')

    # ── membership / presence ────────────────────────────────────────────────
    if op == 'in':
        if not isinstance(arg, list) or len(arg) != 2:
            return False, _T(op, False, f'in expects [needle, haystack], got {_fmt(arg)}', bad=True)
        needle = _resolve(arg[0], sig, bindings)
        hay = _resolve(arg[1], sig, bindings)
        if needle is MISSING or hay is MISSING:
            return False, _T(op, False, f'{_desc(arg[0])} in {_desc(arg[1])} — unknown ({_fmt(needle)} in {_fmt(hay)})')
        try:
            if isinstance(hay, dict):
                ok = needle in hay
            elif isinstance(hay, (list, tuple, set)):
                ok = needle in hay
            elif isinstance(hay, str):
                ok = isinstance(needle, str) and needle in hay
            else:
                ok = False
        except TypeError:  # unhashable needle vs set, etc.
            ok = False
        return ok, _T(op, ok, f'{_fmt(needle)} in {_desc(arg[1])} {_fmt(hay)}')

    if op in ('present', 'absent'):
        v = _resolve(arg, sig, bindings)
        there = not (v is MISSING or v is None)
        ok = there if op == 'present' else (not there)
        return ok, _T(op, ok, f'{_desc(arg)} is {"present" if there else "absent"} ({_fmt(v)})')

    # ── quantifiers ──────────────────────────────────────────────────────────
    if op in ('exists', 'forall'):
        return _eval_quant(op, arg, sig, bindings, depth)

    # ── geometry builtin ─────────────────────────────────────────────────────
    if op == 'boxes_overlap':
        return _eval_overlap(arg, sig, bindings)

    return False, _T(op, False, f'unknown operator {op!r} — ignored', bad=True)


_SYM = {'lt': '<', 'lte': '<=', 'gt': '>', 'gte': '>=', 'eq': '==', 'ne': '!='}


def _desc(operand):
    """How an operand is NAMED in trace text (paths keep their name, literals show
    their value) — this is what makes explain() read like a measurement."""
    if isinstance(operand, str):
        return operand
    if isinstance(operand, dict) and 'path' in operand:
        return str(operand['path'])
    if isinstance(operand, dict) and 'lit' in operand:
        return _fmt(operand['lit'])
    return _fmt(operand)


def _side(operand, value):
    """One side of a comparison as trace text: 'name value' for a path, just 'value'
    for a literal — so a clause reads 'flow_mean 0.08 < min_flow 0.12', never the
    duplicated '0.9 0.9' a literal would otherwise produce."""
    name, val = _desc(operand), _fmt(value)
    return val if name == val else f'{name} {val}'


def _items_of(coll):
    """(key, value) pairs of a mapping, or (index-as-str, value) of a sequence."""
    if isinstance(coll, dict):
        return list(coll.items())
    if isinstance(coll, (list, tuple)):
        return [(str(i), v) for i, v in enumerate(coll)]
    return []


def _eval_quant(op, arg, sig, bindings, depth):
    """exists / forall over a signature collection.

    min_count is the vacuous-truth guard: 'ALL character regions are frozen' must be
    FALSE when the signature contains no character regions at all, otherwise an empty
    or partial signature satisfies every universal rule in the KB."""
    if not isinstance(arg, dict):
        return False, _T(op, False, f'{op} expects an object, got {_fmt(arg)}', bad=True)
    src = arg.get('in')
    name = arg.get('as')
    where = arg.get('where')
    filt = arg.get('filter')
    try:
        min_count = int(arg.get('min_count', 1))
    except (TypeError, ValueError):
        min_count = 1
    if not isinstance(name, str) or not name or where is None:
        return False, _T(op, False, f'{op} needs "as" and "where"', bad=True)

    coll = _resolve(src, sig, bindings)
    if coll is MISSING:
        return False, _T(op, False, f'{op} over {_desc(src)} — collection missing')
    items = _items_of(coll)
    if not items:
        return False, _T(op, False, f'{op} over {_desc(src)} — collection empty')

    considered, satisfied, kid_traces, first_hit = 0, 0, [], None
    for key, val in items:
        b2 = dict(bindings)
        b2[name] = (key, val)
        if filt is not None:
            fv, _ft = _eval(filt, sig, b2, depth + 2)
            if not fv:
                continue
        considered += 1
        v, t = _eval(where, sig, b2, depth + 1)
        # wrap in an 'item' node so the bound name survives _fired()'s flattening of
        # all/any — otherwise the report says "1/3 satisfied" without ever naming
        # WHICH region, which is the one thing the reader needs.
        kid_traces.append(_T('item', v, f'{name}={key}', [t], bad=_bad(t)))
        if v:
            satisfied += 1
            if first_hit is None:
                first_hit = (key, val)

    if considered < min_count:
        return False, _T(
            op,
            False,
            f'{op} over {_desc(src)} — only {considered} item(s) passed the '
            f'filter, need >= {min_count} (vacuous-truth guard)',
            kid_traces,
        )

    if op == 'exists':
        ok = satisfied >= min_count
        text = f'exists {name} in {_desc(src)}: {satisfied}/{considered} satisfied (need >= {min_count})'
    else:
        ok = (satisfied == considered) and considered >= min_count
        text = f'forall {name} in {_desc(src)}: {satisfied}/{considered} satisfied (need all, min {min_count})'

    broken = any(_bad(t) for t in kid_traces)
    if broken:
        ok = False
        text += ' — contains a MALFORMED clause, forced false'
    tr = _T(op, ok, text, [t for t in kid_traces if t.get('ok')] or kid_traces, bad=broken)
    if ok and first_hit is not None:
        tr['binding'] = {name: first_hit[0]}
        tr['bound'] = {name: first_hit}
    return ok, tr


def _eval_overlap(arg, sig, bindings):
    """boxes_overlap — the one geometric builtin. Box containment decides whether a
    pinned keep rectangle can freeze a moving region, and that cannot be expressed
    with comparisons over scalars."""
    if not isinstance(arg, dict):
        return False, _T('boxes_overlap', False, f'expects an object, got {_fmt(arg)}', bad=True)
    ra, rb = _resolve(arg.get('a'), sig, bindings), _resolve(arg.get('b'), sig, bindings)
    a, b = _box(ra), _box(rb)
    if a is MISSING or b is MISSING:
        return False, _T(
            'boxes_overlap',
            False,
            f'{_desc(arg.get("a"))} / {_desc(arg.get("b"))} — not both boxes ({_fmt(ra)} vs {_fmt(rb)})',
        )
    min_frac = _num(arg.get('min_frac', 0.05))
    min_frac = 0.05 if min_frac is MISSING else min_frac
    min_iou = _num(arg.get('min_iou')) if arg.get('min_iou') is not None else MISSING
    _inter, frac, iou = _overlap(a, b)
    ok = frac >= min_frac and (min_iou is MISSING or iou >= min_iou)
    return ok, _T(
        'boxes_overlap',
        ok,
        f'{_desc(arg.get("a"))} {_fmt(a)} vs {_desc(arg.get("b"))} {_fmt(b)}: '
        f'{frac * 100:.0f}% of A covered (need >= {min_frac * 100:.0f}%), '
        f'IoU {iou:.2f}',
    )


def evaluate(precondition, signature, bindings=None):
    """Public, fail-safe wrapper: (bool, trace). A KB entry that blows up evaluates
    to 'does not match' — a knowledge base is advice, and broken advice is silence."""
    try:
        return _eval(precondition, signature if isinstance(signature, dict) else {}, dict(bindings or {}), 0)
    except Exception as e:  # never raise upward
        return False, _T('error', False, f'evaluator error (treated as no-match): {e}', bad=True)


# ── trace -> human explanation ───────────────────────────────────────────────


def _fired(trace, depth=0, out=None):
    """Collect the CONTRIBUTING true clauses of a satisfied trace.

    Only walks branches that actually carried the result: under a true 'all' every
    child contributed, under a true 'any' only the true children did. That is what
    makes explain() name the clauses that fired rather than dumping the whole tree."""
    out = [] if out is None else out
    if not isinstance(trace, dict) or not trace.get('ok'):
        return out
    op = trace.get('op')
    kids = trace.get('children') or []
    if op in ('all', 'any'):
        for k in kids:
            if op == 'all' or k.get('ok'):
                _fired(k, depth, out)
        return out
    out.append((depth, trace.get('text', '')))
    for k in kids:
        if k.get('ok'):
            _fired(k, depth + 1, out)
    return out


def _bindings_from(trace, acc=None):
    """Every quantifier binding captured by a satisfied trace, outermost first —
    this is what lets an action say 'drop keep_boxes.{$p._key}'."""
    acc = {} if acc is None else acc
    if not isinstance(trace, dict) or not trace.get('ok'):
        return acc
    for k, v in (trace.get('bound') or {}).items():
        acc.setdefault(k, tuple(v))
    for k in trace.get('children') or []:
        _bindings_from(k, acc)
    return acc


def explain(remedy, signature=None):
    """Human string naming WHICH precondition clauses fired, with their numbers.

    Accepts either a raw remedy or one returned by match() (which already carries its
    trace, so no re-evaluation is needed). Never raises."""
    try:
        if not isinstance(remedy, dict):
            return 'explain: not a remedy'
        rid = remedy.get('id', '?')
        trace = (remedy.get('match') or {}).get('trace')
        if trace is None:
            sig, _notes = normalize_signature(signature or {})
            _ok, trace = evaluate(remedy.get('precondition'), sig)
        if not trace or not trace.get('ok'):
            lines = [f'{rid}: DID NOT FIRE — unsatisfied clause(s):']
            if trace:
                for d, t in _why_not(trace):
                    lines.append('  ' * (d + 1) + '- ' + t)
            return '\n'.join(lines)
        lines = [f'{rid}: FIRED because']
        for d, t in _fired(trace):
            lines.append('  ' + '  ' * d + '- ' + t)
        act = remedy.get('resolved_action') or remedy.get('action')
        because = act.get('because') if isinstance(act, dict) else None
        if because:
            lines.append(f'  => {because}')
        diff = (remedy.get('match') or {}).get('action_preview')
        if diff:
            lines.append(f'  => action: {json.dumps(diff, sort_keys=True)}')
        return '\n'.join(lines)
    except Exception as e:
        return f'explain failed (ignored): {e}'


def _why_not(trace, depth=0, out=None):
    """The FALSE leaves of an unsatisfied trace — the audit trail for 'why did the KB
    stay silent', which matters as much as why it spoke."""
    out = [] if out is None else out
    if not isinstance(trace, dict):
        return out
    kids = trace.get('children') or []
    if trace.get('ok'):
        return out
    if trace.get('op') in ('all', 'any') and kids:
        for k in kids:
            if not k.get('ok'):
                _why_not(k, depth, out)
        return out
    out.append((depth, trace.get('text', '')))
    return out
