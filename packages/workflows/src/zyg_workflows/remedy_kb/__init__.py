# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""remedy_kb.py — the learned knowledge base: MEASURED failure -> CONCRETE parameter change.

2026-07-30. Born from the scene20 paste-back investigation, whose real lesson was not
about paste-back at all:

    a_hand flow 0.254 (raw render)  ->  0.080 (after a static paste-back)  ->  0.364 (fix)

Two runs (v7, v8a) were written off by HUMANS as "frozen Abel" and "the prompt didn't
give him an action". Both diagnoses were wrong, and the numbers that disproved them
already existed. What was missing was a machine that reads measurements and SELECTS the
explanation. That is this module. It deliberately holds no narrative: every rule lives
as DATA in config/remedy_kb.json, keyed on measurements, and the same rule that explains
scene20 must fire on any run whose numbers look like scene20's.

    from zyg_workflows import remedy_kb
    ranked = remedy_kb.match(signature)            # signature built by self_improve.py
    print(remedy_kb.explain(ranked[0], signature)) # which clauses fired, with numbers
    new_params = remedy_kb.apply(ranked[0], params)
    remedy_kb.record_attempt(ranked[0]['id'], run_id, new_params)
    ...render...
    remedy_kb.record_outcome(ranked[0]['id'], run_id,
                             'regions.a_hand.flow_mean', 0.080, 0.364, threshold=0.12)

WHY A PREDICATE LANGUAGE INSTEAD OF PYTHON RULES
Preconditions must be auditable by reading a JSON file and must survive being written by
a future run of this pipeline. So they are a tiny JSON AST — and/or/not, numeric
comparisons, membership, existential and universal quantifiers over the signature's
mappings, plus one geometric builtin (boxes_overlap) — evaluated by _eval() below. There
is no eval(), no exec(), no import, no attribute access and no arithmetic: the worst a
malformed or hostile precondition can do is evaluate to False. Every node is TOTAL — a
missing path, a non-numeric comparison or an unknown operator yields False and a trace
note, never an exception. A rule must never fire out of ignorance, so eq/ne both fail
CLOSED when either side is missing, and forall carries a min_count that kills vacuous
truth ("all character regions are frozen" is false when there are no character regions).

THREE FILES, THREE JOBS (so learning never rewrites the authored rules):
    config/remedy_kb.json                  authored rules      (hand-written, diffable)
    data/runtime/remedy_kb_learned.json    rules added at runtime by add_remedy()
    data/runtime/remedy_kb_state.json      attempts/successes/posterior confidence

CONFIDENCE UPDATE RULE (documented because a hidden update rule is not learning):
posterior confidence is the mean of a Beta prior centred on the AUTHORED confidence,

    confidence = (successes + p0 * w0) / (attempts + w0)

with p0 the authored confidence and w0 the authored prior_weight (default 2.0 pseudo-
observations). Zero attempts reproduces the authored value exactly; each real outcome
moves it, and an authored 0.92 rule needs sustained failure to fall — which is the
correct asymmetry for a rule backed by a measured before/after. SUCCESS is defined as
THE TARGETED METRIC CROSSING ITS THRESHOLD, not as "the number got better": a metric
that improves 0.080 -> 0.110 against a 0.12 gate still ships a broken clip and is
recorded as a failure.

Every public call is fail-safe in house style: it returns a value or an {'ok': False,
'error': ...} dict and never raises across the module boundary, because a broken
knowledge base must degrade to "no advice", never to a broken render.
"""

from __future__ import annotations

from .core import (
    json,
    os,
    sys,
    threading,
    time,
    _zyg_logging,
    paths,
    _zyg_log,
    KB_PATH,
    LEARNED_PATH,
    STATE_PATH,
    _LOCK,
    _MAX_DEPTH,
    _FLOW_MIN_HANDS,
    _FLOW_MIN_HEAD,
    _CHURN_MAX,
    _PROP_NCC_MIN,
    _DEFAULT_SEVERITY_WEIGHTS,
    _log_noop,
    kb_path,
    learned_path,
    state_path,
    _Missing,
    MISSING,
    _is_num,
    _num,
    _fmt,
    _child,
    _lookup,
    _resolve_binding,
    _resolve,
    _box,
    _overlap,
    _ROLE_HINTS,
    _infer_role,
    normalize_signature,
)
from .evaluator import (
    _T,
    _bad,
    _eval,
    _SYM,
    _desc,
    _side,
    _items_of,
    _eval_quant,
    _eval_overlap,
    evaluate,
    _fired,
    _bindings_from,
    explain,
    _why_not,
)
from .kb import (
    _cache,
    _read_json,
    _write_json_atomic,
    load_state,
    _save_state,
    _mtime,
    load_kb,
    _cf,
    posterior_confidence,
    severity_weight,
    match,
    diagnose,
    _subst,
    _resolve_action,
    _set_dotted,
    _del_dotted,
    apply,
)
from .learning import _ledger, record_attempt, record_outcome, _authored_prior, _small, add_remedy, format_ranked
from .cli import _main, _selftest

# Re-export surface: every name below is imported above and not used in this
# module. Nothing does ``import *`` from here, so __all__ changes no behaviour;
# it declares the inherited namespace public so ruff does not read it as dead.
__all__ = [
    'json',
    'os',
    'sys',
    'threading',
    'time',
    '_zyg_logging',
    'paths',
    '_zyg_log',
    'KB_PATH',
    'LEARNED_PATH',
    'STATE_PATH',
    '_LOCK',
    '_MAX_DEPTH',
    '_FLOW_MIN_HANDS',
    '_FLOW_MIN_HEAD',
    '_CHURN_MAX',
    '_PROP_NCC_MIN',
    '_DEFAULT_SEVERITY_WEIGHTS',
    '_log_noop',
    'kb_path',
    'learned_path',
    'state_path',
    '_Missing',
    'MISSING',
    '_is_num',
    '_num',
    '_fmt',
    '_child',
    '_lookup',
    '_resolve_binding',
    '_resolve',
    '_box',
    '_overlap',
    '_ROLE_HINTS',
    '_infer_role',
    'normalize_signature',
    '_T',
    '_bad',
    '_eval',
    '_SYM',
    '_desc',
    '_side',
    '_items_of',
    '_eval_quant',
    '_eval_overlap',
    'evaluate',
    '_fired',
    '_bindings_from',
    'explain',
    '_why_not',
    '_cache',
    '_read_json',
    '_write_json_atomic',
    'load_state',
    '_save_state',
    '_mtime',
    'load_kb',
    '_cf',
    'posterior_confidence',
    'severity_weight',
    'match',
    'diagnose',
    '_subst',
    '_resolve_action',
    '_set_dotted',
    '_del_dotted',
    'apply',
    '_ledger',
    'record_attempt',
    'record_outcome',
    '_authored_prior',
    '_small',
    'add_remedy',
    'format_ranked',
    '_main',
    '_selftest',
]
