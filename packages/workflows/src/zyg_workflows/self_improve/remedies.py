# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The remedy KB: the real one if importable, a general-rule fallback if not.

Split verbatim out of zyg_workflows/self_improve.py; see docs/self_improve_split_map.md.
"""

import json
import os
import re
import time
import logging as _zyg_logging

from zyg_workflows.self_improve.base import _DIR, _jsonable, _mklog, _read_json, _write_json

_zyg_log = _zyg_logging.getLogger('zyg_workflows.self_improve')


# ══════════════════════════════════════════════════════════════════════════════
# 8.  REMEDY KB — the real one if it exists, a general-rule fallback if not
# ══════════════════════════════════════════════════════════════════════════════
#
# CONTRACT (remedy_kb, built in parallel):
#     match(signature)  -> ranked [remedy]
#     apply(remedy, params) -> params
#     record_attempt(...) / record_outcome(...) / explain(...)
# We bind to it lazily and fall back to _FallbackKB so the loop is never dead.
#
# THE FALLBACK'S RULES ARE GENERAL.  None of them mentions Abel, a hand, a book,
# scene20 or paste-back-by-name.  They are conditioned on MEASURED facts, and the
# facts are what pick the remedy.  If the fallback ever "gets the right answer",
# it is because build_signature measured its way there.

_FALLBACK_REMEDIES = [
    {
        'id': 'postprocess.drop_destructive_step',
        'title': 'Drop the post-process step that is destroying the motion',
        # primary fact first — it supplies the binding for {step}
        'when': [
            'chain.step_destructive_pinning',
            'motion.lost_in_postprocess',
            'keep.contains_motion',
            'keep.pin_unnecessary',
        ],
        'unless': [],
        'targets': 'region_flow',
        'patch': {'{param_key}': '{disable_value}'},
        'prior': [3.0, 2.0],
        'rationale': (
            'A step measurably pushed a region across its motion gate; the '
            'pin it applies covers content that is moving on the raw render; '
            'and the same pin is not buying any stability the raw render did '
            'not already have. A step with a measured cost and no measured '
            'benefit is removed, not tuned.'
        ),
    },
    {
        'id': 'postprocess.make_keep_mask_occluder_aware',
        'title': 'Keep the step but subtract moving occluders from the keep mask per frame',
        'when': ['chain.step_destructive_pinning', 'motion.lost_in_postprocess', 'keep.contains_motion'],
        'unless': ['variant.tried_and_failed'],
        'targets': 'region_flow',
        'patch': {'{param_key}': 'dynamic'},
        'prior': [2.0, 2.0],
        'rationale': (
            'The pin is justified (it holds a prop the raw render cannot hold '
            'by itself) but it also covers moving content, so the keep mask '
            'must be per-frame: static_keep MINUS dilated(moving occluders).'
        ),
    },
    {
        'id': 'postprocess.shrink_keep_box',
        'title': 'Shrink the pinned box so it stops covering the moving region',
        'when': ['keep.covers_failing_region', 'motion.lost_in_postprocess'],
        'unless': [],
        'targets': 'region_flow',
        'patch': {'post.keep_box_override.{keep}': '{shrink_to}'},
        'prior': [1.5, 2.0],
        'rationale': (
            'A cheaper variant of the occluder-aware mask: if the moving '
            'region only clips one edge of the pin, the pin can simply be cut '
            'back to the strips that contain no motion.'
        ),
    },
    {
        'id': 'postprocess.review_lossy_step',
        'title': 'Review a non-pinning post-process step that measurably costs motion',
        'when': ['chain.step_destructive'],
        'unless': [],
        'targets': 'region_flow',
        'patch': {'post.review.{step}': 'MEASURED_MOTION_LOSS'},
        'prior': [1.0, 3.0],
        'rationale': (
            'This link measurably lowers region flow but reads no keep mask, '
            'so no pin evidence can indict it. Upscalers and interpolators '
            'legitimately smooth flow; flagged for review, not for removal.'
        ),
    },
    {
        'id': 'render.raise_shift',
        'title': 'Raise the sampler shift — the primary motion lever at 480p',
        'when': ['motion.frozen_at_source'],
        'unless': [],
        'targets': 'region_flow',
        'patch': {'render.shift': '+1.0'},
        'prior': [2.0, 2.0],
        'rationale': (
            'The region is already frozen on the RAW render, so no '
            'post-process can be blamed. At 480p, shift is the measured '
            'motion lever (720p stiffens instead).'
        ),
    },
    {
        'id': 'render.strengthen_action_prompt',
        'title': 'Give the frozen subject an explicit, continuous physical action',
        'when': ['motion.frozen_at_source'],
        'unless': [],
        'targets': 'region_flow',
        'patch': {'render.prompt_action.{region}': 'REQUIRED'},
        'prior': [1.5, 2.5],
        'rationale': (
            'A region frozen at the source with an otherwise healthy render '
            'is usually under-specified in the prompt rather than under-'
            'sampled.'
        ),
    },
    {
        'id': 'render.increase_context_overlap',
        'title': 'Increase context overlap so props survive the window seam',
        'when': ['prop.morph_at_seam'],
        'unless': [],
        'targets': 'prop_ncc',
        'patch': {'render.context_overlap': '+8'},
        'prior': [2.0, 2.0],
        'rationale': (
            'Prop identity collapses exactly at a context-window boundary; '
            'more overlap gives the next window more of the prop to copy.'
        ),
    },
    {
        'id': 'prop.pin_morphing_prop',
        'title': 'Pin the morphing prop — but only over pixels with no measured motion',
        'when': ['prop.morph_at_seam'],
        'unless': ['keep.contains_motion'],
        'targets': 'prop_ncc',
        'patch': {'post.paste_back': 'dynamic', 'post.pin_prop.{prop}': 'REQUIRED'},
        'prior': [1.5, 2.5],
        'rationale': (
            'Pinning fixes a morphing prop directly, but the `unless` clause '
            'blocks it whenever a pin has already been measured to cover '
            'moving content — that is the failure mode this whole module '
            'exists to stop repeating.'
        ),
    },
]


class _FallbackKB:
    """Minimal, general-rule remedy KB used only until remedy_kb.py lands.

    Persistence: data/runtime/remedy_kb_fallback.json — per-remedy Beta(a, b)
    counts. confidence = a / (a + b) (posterior mean).  record_outcome moves the
    counts, which is the entire learning mechanism: a remedy whose target metric
    keeps failing to cross its threshold sinks in the ranking on its own."""

    name = 'fallback'

    def __init__(self, path=None):
        self.path = path or os.path.join(_DIR, 'data', 'runtime', 'remedy_kb_fallback.json')
        self.state = _read_json(self.path, {}) or {}

    # -- persistence ---------------------------------------------------------
    def _rec(self, rid):
        r = self.state.setdefault(rid, {})
        base = next((x['prior'] for x in _FALLBACK_REMEDIES if x['id'] == rid), [1.0, 1.0])
        r.setdefault('alpha', float(base[0]))
        r.setdefault('beta', float(base[1]))
        r.setdefault('attempts', 0)
        r.setdefault('successes', 0)
        r.setdefault('history', [])
        return r

    def _save(self):
        _write_json(self.path, self.state)

    def confidence(self, rid):
        r = self._rec(rid)
        return round(r['alpha'] / max(1e-9, r['alpha'] + r['beta']), 3)

    # -- matching ------------------------------------------------------------
    @staticmethod
    def _by_ns(signature):
        idx = {}
        for f in signature.get('facts') or []:
            idx.setdefault(f['ns'], []).append(f)
        return idx

    def match(self, signature, log_fn=None):
        """Rank remedies whose `when` namespaces are ALL present and whose
        `unless` namespaces are absent.  Score =
            confidence * (1 + 0.25 * extra matched facts) * severity
        where severity is how far the targeted metric sits below its gate."""
        log = _mklog(log_fn)
        idx = self._by_ns(signature)
        out = []
        for spec in _FALLBACK_REMEDIES:
            need = spec['when']
            if any(ns not in idx for ns in need):
                continue
            primary_facts = idx[need[0]]
            for pf in primary_facts:
                binds = dict(pf['args'])
                binds.update(
                    {
                        k: v
                        for k, v in (pf.get('evidence') or {}).items()
                        if isinstance(v, (str, int, float, bool, list)) or v is None
                    }
                )
                # `unless` is checked AFTER binding so a blocker only blocks the
                # candidate it is actually about (a failed paste_back alternative
                # must not veto an unrelated family's remedy).
                blocked = None
                for ns in spec.get('unless') or []:
                    for c in idx.get(ns) or []:
                        if all(binds.get(k) in (None, v) for k, v in c['args'].items()):
                            blocked = c
                            break
                    if blocked:
                        break
                matched = [pf]
                consistent = True
                for ns in need[1:]:
                    cands = idx[ns]
                    pick = None
                    for c in cands:
                        if all(binds.get(k) in (None, v) for k, v in c['args'].items()):
                            pick = c
                            break
                    if pick is None:
                        pick = cands[0]
                        consistent = False
                    for k, v in pick['args'].items():
                        binds.setdefault(k, v)
                    for k, v in (pick.get('evidence') or {}).items():
                        if isinstance(v, (str, int, float, bool, list)):
                            binds.setdefault(k, v)
                    matched.append(pick)
                if blocked is not None:
                    # blocked remedies are still REPORTED (with why), never applied
                    out.append(self._mk(spec, binds, matched, signature, 0.0, blocked=blocked))
                    continue
                sev = self._severity(spec, binds, signature)
                score = self.confidence(spec['id']) * (1.0 + 0.25 * (len(matched) - 1)) * (1.0 + sev)
                if not consistent:
                    score *= 0.7
                out.append(self._mk(spec, binds, matched, signature, round(score, 4)))
        out.sort(key=lambda r: (r['blocked_by'] is not None, -r['score']))
        log(f'[self_improve] KB(fallback) matched {len(out)} remedy candidate(s)')
        return out

    @staticmethod
    def _severity(spec, binds, signature):
        if spec['targets'] == 'region_flow':
            worst = 0.0
            for f in signature.get('failures') or []:
                if not f['gate'].startswith('region_flow'):
                    continue
                if binds.get('region') and f['region'] != binds['region']:
                    continue
                thr = max(1e-6, f['threshold'])
                worst = max(worst, (thr - f['value']) / thr)
            return round(min(1.0, worst), 3)
        return 0.3

    def _mk(self, spec, binds, matched, signature, score, blocked=None):
        patch = {}
        for k, v in (spec.get('patch') or {}).items():
            kk = self._fmt(k, binds)
            vv = self._fmt(v, binds)
            if kk is None or '{' in str(kk):
                continue
            patch[kk] = vv
        return {
            'id': spec['id'],
            'title': spec['title'],
            'score': score,
            'confidence': self.confidence(spec['id']),
            'rationale': spec['rationale'],
            'targets': spec['targets'],
            'params_patch': patch,
            'bindings': _jsonable(
                {
                    k: v
                    for k, v in binds.items()
                    if k in ('region', 'keep', 'step', 'prop', 'param_key', 'disable_value')
                }
            ),
            'matched_facts': [m['fact'] for m in matched],
            'clauses': [
                {'ns': m['ns'], 'fact': m['fact'], 'note': m['note'], 'evidence': m['evidence']} for m in matched
            ],
            'blocked_by': (blocked['fact'] if blocked else None),
            'blocked_note': (blocked['note'] if blocked else None),
            'source': 'fallback_kb',
        }

    @staticmethod
    def _fmt(t, binds):
        """Substitute {name} from the bindings.

        A template that is EXACTLY one placeholder yields the bound value with its
        type intact (so a box list stays a list of floats rather than becoming the
        string '[0.495, 0.7, ...]'); mixed templates fall back to string interp."""
        if not isinstance(t, str):
            return t
        m = re.fullmatch(r'\{([A-Za-z_][A-Za-z0-9_]*)\}', t)
        if m and m.group(1) in binds:
            return binds[m.group(1)]
        out = t
        for k, v in binds.items():
            out = out.replace('{' + k + '}', str(v))
        if out in ('True', 'False'):
            return out == 'True'
        return out

    # -- application ---------------------------------------------------------
    def apply(self, remedy, params, log_fn=None):
        log = _mklog(log_fn)
        p = dict(params or {})
        for k, v in (remedy.get('params_patch') or {}).items():
            if isinstance(v, str) and re.match(r'^[+-]\d+(\.\d+)?$', v):
                try:
                    p[k] = round(float(p.get(k, 0)) + float(v), 4)
                except Exception:
                    p[k] = v
            else:
                p[k] = v
            log(f'[self_improve]   {remedy["id"]}: {k} = {p[k]!r}')
        return p

    # -- learning ------------------------------------------------------------
    # Signatures deliberately mirror remedy_kb's published ones so callers need
    # no branch: record_attempt(remedy_id, run_id, applied_params) and
    # record_outcome(remedy_id, run_id, metric, before, after, threshold, ...).
    def record_attempt(self, remedy_id, run_id, applied_params=None, log_fn=None):
        r = self._rec(remedy_id)
        r['attempts'] += 1
        r['history'].append(
            {
                'when': time.strftime('%Y-%m-%d %H:%M:%S'),
                'event': 'attempt',
                'run_id': str(run_id),
                'params': _jsonable(applied_params),
            }
        )
        self._save()
        return {'ok': True, 'remedy_id': remedy_id, 'attempts': r['attempts'], 'successes': r['successes']}

    def record_outcome(
        self, remedy_id, run_id, metric, before, after, threshold=None, direction='up', success=None, log_fn=None
    ):
        """Success = CROSSING the gate, not merely improving (0.080 → 0.110 against
        a 0.12 gate is still a failed clip)."""
        log = _mklog(log_fn)
        r = self._rec(remedy_id)
        if success is None:
            if threshold is not None and before is not None and after is not None:
                success = (after >= threshold) if before < threshold else (after <= threshold)
            elif before is not None and after is not None:
                success = (after > before) if direction == 'up' else (after < before)
            else:
                success = False
        if success:
            r['alpha'] += 1.0
            r['successes'] += 1
        else:
            r['beta'] += 1.0
        r['history'].append(
            {
                'when': time.strftime('%Y-%m-%d %H:%M:%S'),
                'event': 'outcome',
                'ok': bool(success),
                'run_id': str(run_id),
                'metric': metric,
                'before': before,
                'after': after,
                'threshold': threshold,
            }
        )
        self._save()
        log(
            f'[self_improve] KB learn: {remedy_id} → '
            f'{"CONFIRMED" if success else "REFUTED"} '
            f'(confidence {self.confidence(remedy_id)})'
        )
        return {'ok': True, 'remedy_id': remedy_id, 'success': bool(success), 'confidence': self.confidence(remedy_id)}

    def explain(self, remedy, log_fn=None):
        lines = [
            f'{remedy["id"]} — {remedy["title"]}',
            f'  score {remedy["score"]}  confidence {remedy["confidence"]}'
            f'  ({self._rec(remedy["id"])["successes"]}/'
            f'{self._rec(remedy["id"])["attempts"]} confirmed)',
        ]
        if remedy.get('blocked_by'):
            lines.append(f'  BLOCKED by {remedy["blocked_by"]}: {remedy["blocked_note"]}')
        lines.append('  selected because ALL of these were MEASURED:')
        for c in remedy['clauses']:
            lines.append(f'    · [{c["ns"]}] {c["note"]}')
        lines.append(f'  rule: {remedy["rationale"]}')
        if remedy.get('params_patch'):
            lines.append(f'  patch: {json.dumps(_jsonable(remedy["params_patch"]))}')
        return '\n'.join(lines)


_kb_singleton = None


def kb(log_fn=None):
    """The real remedy_kb if importable, else the general-rule fallback.

    Re-checked on every call so a remedy_kb.py that lands mid-session is picked
    up without a restart."""
    global _kb_singleton
    log = _mklog(log_fn)
    try:
        from zyg_workflows import remedy_kb as RK

        if all(hasattr(RK, a) for a in ('match', 'apply', 'record_outcome')):
            return RK
        log('[self_improve] remedy_kb present but incomplete — using fallback KB')
    except ImportError as _exc:
        _zyg_log.debug('remedy_kb not importable, using the fallback KB: %s', _exc)
    except Exception as e:
        log(f'[self_improve] remedy_kb import error ({e}) — using fallback KB')
    if _kb_singleton is None:
        _kb_singleton = _FallbackKB()
    return _kb_singleton


def _kb_call(obj, name, *a, **kw):
    """Call a KB method tolerantly — the real remedy_kb may not take log_fn."""
    fn = getattr(obj, name, None)
    if fn is None:
        return None
    try:
        return fn(*a, **kw)
    except TypeError:
        kw.pop('log_fn', None)
        try:
            return fn(*a, **kw)
        except Exception:
            return None
    except Exception:
        return None


# Which measurable family a remedy's ACTION belongs to, keyed by substrings of the
# param paths it writes.  Inferred from the patch rather than from tags because the
# patch is what actually changes, and it is what verify_attempt must re-measure.
_PATCH_TARGET_HINTS = (
    ('prop_restore', 'prop_ncc'),
    ('context_overlap', 'prop_ncc'),
    ('pasteback', 'region_flow'),
    ('paste_back', 'region_flow'),
    ('keep_box', 'region_flow'),
    ('shift', 'region_flow'),
    ('lora', 'region_flow'),
)


def _normalize_remedy(r, sig):
    """remedy_kb's remedy shape → the internal shape plan/verify/report use.

    The real KB returns {'id','title','rank_score','confidence','severity',
    'resolved_action':{'set','remove','because'},'match':{'clauses','bindings',...}}.
    The fallback already returns the internal shape and passes through untouched."""
    if not isinstance(r, dict):
        return None
    if r.get('source') == 'fallback_kb':
        return r
    m = r.get('match') or {}
    act = r.get('resolved_action') or r.get('action') or {}
    patch = dict(act.get('set') or {})
    for k in act.get('remove') or []:
        patch[k] = '<REMOVE>'
    regions = (sig or {}).get('regions') or {}
    props = (sig or {}).get('props') or {}
    keeps = (sig or {}).get('keep_boxes') or {}
    binds = {}
    for _var, key in (m.get('bindings') or {}).items():
        if not isinstance(key, str):
            continue
        if key in regions:
            binds.setdefault('region', key)
        elif key in props:
            binds.setdefault('prop', key)
        if key in keeps:
            binds.setdefault('keep', key)
    targets = None
    for needle, fam in _PATCH_TARGET_HINTS:
        if any(needle in str(k) for k in patch):
            targets = fam
            break
    if targets is None:
        targets = 'prop_ncc' if (binds.get('prop') and not binds.get('region')) else 'region_flow'
    if targets == 'region_flow' and not binds.get('region'):
        worst = None
        for gname, g in ((sig or {}).get('gates') or {}).items():
            if gname.startswith('region_flow:') and not g.get('ok'):
                margin = (g.get('score') or 0) - (g.get('threshold') or 0)
                if worst is None or margin < worst[1]:
                    worst = (gname.split(':', 1)[1], margin)
        if worst:
            binds['region'] = worst[0]
    clauses = [
        {'ns': 'precondition', 'fact': c.strip(), 'note': c.strip(), 'evidence': {}} for c in (m.get('clauses') or [])
    ]
    return {
        'id': r.get('id'),
        'title': r.get('title'),
        'score': r.get('rank_score', r.get('confidence')),
        'confidence': r.get('confidence'),
        'severity': r.get('severity'),
        'status': r.get('status'),
        'rationale': act.get('because') or r.get('rationale') or '',
        'targets': targets,
        'params_patch': patch,
        'bindings': binds,
        'matched_facts': [c.strip() for c in (m.get('clauses') or [])],
        'clauses': clauses,
        'blocked_by': None,
        'blocked_note': None,
        'source': 'remedy_kb',
        '_raw': r,
    }


def kb_match(kbo, sig, log_fn=None):
    """match() on whichever KB is live, normalised to the internal remedy shape."""
    raw = _kb_call(kbo, 'match', sig, log_fn=log_fn) or []
    out = [x for x in (_normalize_remedy(r, sig) for r in raw) if x]
    out.sort(key=lambda r: (r.get('blocked_by') is not None, -(r.get('score') or 0)))
    return out


def _kb_confidence(kbo, rid):
    """Posterior confidence for a remedy id, whichever KB is live.

    The fallback exposes .confidence(); remedy_kb exposes load_kb/load_state plus
    posterior_confidence(prior, prior_weight, attempts, successes)."""
    try:
        if hasattr(kbo, 'confidence'):
            return kbo.confidence(rid)
    except Exception as _exc:
        _zyg_log.debug('kb confidence() unavailable for %s, computing it here: %s', rid, _exc)
    try:
        data = kbo.load_kb()
        entry = next((x for x in (data.get('remedies') or []) if x.get('id') == rid), {})
        row = (kbo.load_state() or {}).get(rid) or {}
        # MUST be authored_confidence, not confidence: remedy_kb.load_kb() has
        # ALREADY replaced r['confidence'] with posterior_confidence(...) by the
        # time we see it (remedy_kb.py:813). Feeding that back in as the prior
        # applied the posterior twice and let it feed on itself — remedy_kb's own
        # _authored() carries the warning ("straight from the FILES, never from
        # the state — otherwise the posterior would feed on itself and drift")
        # and this call site was the one place that ignored it.
        prior = entry.get('authored_confidence')
        if prior is None:
            prior = entry.get('confidence', 0.5)
        return round(
            float(
                kbo.posterior_confidence(
                    prior, entry.get('prior_weight', 2.0), int(row.get('attempts') or 0), int(row.get('successes') or 0)
                )
            ),
            3,
        )
    except Exception:
        return None


def _kb_writes_ledger(kbo):
    """remedy_kb.record_outcome already writes gate 'remedy:<id>' into run_ledger;
    the fallback does not.  Used to avoid a double entry."""
    return getattr(kbo, 'name', None) != 'fallback'


def _explain(kbo, remedy):
    """Prose naming the clauses that fired.

    The fallback KB's explain() is already self-contained (it prints its own
    header and rule line), so it is returned verbatim; only remedy_kb's
    trace-only output needs the identifying header wrapped around it."""
    if remedy.get('source') == 'fallback_kb':
        return _FallbackKB().explain(remedy)
    txt = _kb_call(kbo, 'explain', remedy.get('_raw') or remedy)
    if isinstance(txt, str) and txt.strip() and 'not a remedy' not in txt:
        bits = [f'score {remedy.get("score")}', f'confidence {remedy.get("confidence")}']
        for k in ('severity', 'status'):
            if remedy.get(k):
                bits.append(f'{k} {remedy[k]}')
        return f'{remedy.get("id")} — {remedy.get("title")}\n  ' + '  '.join(bits) + '\n' + txt
    return _FallbackKB().explain(remedy)
