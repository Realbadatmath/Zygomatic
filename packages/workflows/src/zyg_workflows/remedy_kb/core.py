# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""core — core section of remedy_kb (verbatim split).

Moved unchanged from remedy_kb.py; see the package __init__ for the full docstring.
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time
import logging as _zyg_logging

from zyg_workflows import paths

# channel kept from the pre-split module
_zyg_log = _zyg_logging.getLogger('zyg_workflows.remedy_kb')

# ── re-export surface ────────────────────────────────────────────────────────
# Two names of the inherited top import block are not used in this file: the
# siblings re-import them off this module — cli.py takes ``sys``
# (``from .core import _infer_role, json, normalize_signature, sys``) and
# learning.py takes ``time``. Declaring them is what makes the re-export
# deliberate rather than an unused import; nothing does ``import *`` from here,
# so __all__ changes no behaviour.
__all__ = [
    'sys',
    'time',
]


KB_PATH = paths.ZYG_REMEDY_KB
LEARNED_PATH = paths.ZYG_REMEDY_KB_LEARNED
STATE_PATH = paths.ZYG_REMEDY_KB_STATE

_LOCK = threading.Lock()
_MAX_DEPTH = 24

# Production calibration (mirrors pipeline_debug's measured constants). Used ONLY by
# normalize_signature() to fill gaps a partial signature leaves, never to invent a
# measurement — every fill is reported in the returned notes.
_FLOW_MIN_HANDS = 0.12
_FLOW_MIN_HEAD = 0.06
_CHURN_MAX = 0.55
_PROP_NCC_MIN = 0.70

_DEFAULT_SEVERITY_WEIGHTS = {'critical': 1.0, 'major': 0.7, 'minor': 0.4, 'info': 0.2}


def _log_noop(_m):
    pass


def kb_path():
    """Active authored-KB path (re-read from env so tests can redirect it)."""
    return os.environ.get('ZYG_REMEDY_KB') or KB_PATH


def learned_path():
    return os.environ.get('ZYG_REMEDY_KB_LEARNED') or LEARNED_PATH


def state_path():
    return os.environ.get('ZYG_REMEDY_KB_STATE') or STATE_PATH


# ── MISSING sentinel ─────────────────────────────────────────────────────────


class _Missing:
    """Absence of a value. Distinct from None (which is a value the signature may
    legitimately carry) and from False. Every operator treats it as 'unknown' and
    fails closed rather than guessing."""

    __slots__ = ()

    def __repr__(self):
        return '<missing>'

    def __bool__(self):
        return False


MISSING = _Missing()


def _is_num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _num(v):
    """Coerce to float, or MISSING. Bools are NOT numbers here — True must never
    silently compare as 1.0 against a measured threshold."""
    if _is_num(v):
        return float(v)
    if isinstance(v, str):
        try:
            return float(v.strip())
        except (TypeError, ValueError):
            return MISSING
    return MISSING


def _fmt(v):
    """Short, stable rendering of a resolved operand for trace text."""
    if v is MISSING:
        return 'MISSING'
    if isinstance(v, float):
        return f'{v:g}'
    if isinstance(v, str):
        return repr(v)
    if isinstance(v, (list, tuple)):
        if len(v) > 6:
            return '[' + ', '.join(_fmt(x) for x in list(v)[:6]) + f', ...+{len(v) - 6}]'
        return '[' + ', '.join(_fmt(x) for x in v) + ']'
    if isinstance(v, dict):
        return '{' + ', '.join(sorted(map(str, v.keys()))[:6]) + ('...' if len(v) > 6 else '') + '}'
    return str(v)


# ── dotted lookup ────────────────────────────────────────────────────────────


def _child(cur, key):
    """One step of a dotted lookup. Mappings by key, sequences by integer index."""
    if isinstance(cur, dict):
        return cur[key] if key in cur else MISSING
    if isinstance(cur, (list, tuple)):
        try:
            i = int(key)
        except (TypeError, ValueError):
            return MISSING
        return cur[i] if -len(cur) <= i < len(cur) else MISSING
    return MISSING


def _lookup(obj, path):
    """Dotted lookup with LONGEST-KEY-FIRST resolution.

    Gate and region names in this pipeline contain dots and colons
    ('region_flow:a_hand', 'props.book.raw_min_ncc'), so a naive split('.') walk
    would lose them. At each level the longest remaining joined key that actually
    exists wins, then resolution continues from there. Returns MISSING for any
    path that does not fully resolve — never raises."""
    if not isinstance(path, str) or not path:
        return MISSING
    parts = path.split('.')
    cur, i, n = obj, 0, len(parts)
    while i < n:
        if cur is MISSING or cur is None:
            return MISSING
        hit = MISSING
        for j in range(n, i, -1):
            nxt = _child(cur, '.'.join(parts[i:j]))
            if nxt is not MISSING:
                hit, i = nxt, j
                break
        if hit is MISSING:
            return MISSING
        cur = hit
    return cur


def _resolve_binding(token, bindings):
    """Resolve '$name' / '$name._key' / '$name.sub.path' against the binding chain.

    Bindings map name -> (key, value): '$r' is the bound value, '$r._key' its key in
    the enclosing mapping (which is how an action can name WHICH region or prop
    fired), anything else is a dotted lookup inside the bound value."""
    body = token[1:]
    if not body:
        return MISSING
    name, _, rest = body.partition('.')
    if name not in bindings:
        return MISSING
    key, val = bindings[name]
    if not rest:
        return val
    if rest == '_key':
        return key
    return _lookup(val, rest)


def _resolve(operand, sig, bindings):
    """Resolve one operand to a value or MISSING. See config/remedy_kb.json
    '_predicate_language.operands' for the (identical) authored contract."""
    if isinstance(operand, str):
        if operand.startswith('$'):
            return _resolve_binding(operand, bindings)
        return _lookup(sig, operand)
    if isinstance(operand, dict):
        if 'lit' in operand:
            return operand['lit']
        if 'path' in operand:
            p = operand['path']
            return _lookup(sig, p) if isinstance(p, str) else MISSING
        return MISSING  # a bare dict is not a valid operand
    if isinstance(operand, (list, tuple)):
        return list(operand)  # bare list = literal list, unresolved
    if _is_num(operand) or isinstance(operand, bool) or operand is None:
        return operand
    return MISSING


# ── geometry builtin ─────────────────────────────────────────────────────────


def _box(v):
    """[x0,y0,x1,y1] floats with the corners ordered, or MISSING."""
    if not isinstance(v, (list, tuple)) or len(v) != 4:
        return MISSING
    vals = [_num(x) for x in v]
    if any(x is MISSING for x in vals):
        return MISSING
    x0, y0, x1, y1 = vals
    return [min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)]


def _overlap(a, b):
    """(inter_area, frac_of_a, iou) for two ordered boxes."""
    ix0, iy0 = max(a[0], b[0]), max(a[1], b[1])
    ix1, iy1 = min(a[2], b[2]), min(a[3], b[3])
    iw, ih = max(0.0, ix1 - ix0), max(0.0, iy1 - iy0)
    inter = iw * ih
    area_a = max(0.0, a[2] - a[0]) * max(0.0, a[3] - a[1])
    area_b = max(0.0, b[2] - b[0]) * max(0.0, b[3] - b[1])
    union = area_a + area_b - inter
    return (inter, (inter / area_a) if area_a > 0 else 0.0, (inter / union) if union > 0 else 0.0)


# ── signature normalization ──────────────────────────────────────────────────

_ROLE_HINTS = (
    ('character_hand', ('hand', 'hands', 'fist', 'arm', 'wrist')),
    ('character_head', ('head', 'face', 'mouth', 'lips')),
    ('prop', ('pipe', 'book', 'candle', 'quill', 'bowl', 'ledger', 'page', 'cup', 'prop')),
    ('background', ('bg', 'background', 'set', 'wall', 'room')),
)


def _infer_role(name):
    """Deterministic role from a region name. Documented and auditable rather than
    clever: self_improve.py SHOULD send an explicit role, and every inference this
    makes is reported in normalize_signature()'s notes."""
    n = str(name).lower()
    for role, words in _ROLE_HINTS:
        for w in words:
            if w in n.replace('-', '_').split('_') or n.endswith('_' + w) or n == w:
                return role
    for role, words in _ROLE_HINTS:
        if any(w in n for w in words):
            return role
    return 'character' if n[:2] in ('a_', 'c_') else 'unknown'


def normalize_signature(signature):
    """(signature_copy, notes) — fill the DERIVABLE gaps a partial signature leaves.

    Fills only what is defined by production calibration and reports every fill:
      * regions[*].role      inferred from the region name (see _ROLE_HINTS)
      * regions[*].min_flow  0.12 hands/props, 0.06 heads (pipeline_debug constants)
      * regions[*].max_churn 0.55
      * props[*].ncc_min     0.70
      * props[*].pinned      true when the prop has a keep box of the same name
    It NEVER invents a measurement (flow, NCC, boxes): a rule that needs an unmeasured
    number must stay silent, so the loop's conclusions trace back to real pixels.
    Fail-safe: on any error the ORIGINAL signature is returned with an error note."""
    notes = []
    try:
        if not isinstance(signature, dict):
            return {}, ['signature is not a dict — treated as empty']
        sig = json.loads(json.dumps(signature, default=str))  # deep copy, JSON-safe
        keep = sig.get('keep_boxes') if isinstance(sig.get('keep_boxes'), dict) else {}

        regions = sig.get('regions')
        if isinstance(regions, dict):
            for name, r in regions.items():
                if not isinstance(r, dict):
                    continue
                if not r.get('role'):
                    r['role'] = _infer_role(name)
                    notes.append(f"regions.{name}.role inferred '{r['role']}' from the name")
                if r.get('min_flow') is None:
                    dflt = _FLOW_MIN_HEAD if r.get('role') == 'character_head' else _FLOW_MIN_HANDS
                    r['min_flow'] = dflt
                    notes.append(f'regions.{name}.min_flow defaulted to {dflt} (calibrated for {r.get("role")})')
                if r.get('max_churn') is None:
                    r['max_churn'] = _CHURN_MAX
                if r.get('ok') is None and _is_num(r.get('flow_mean')):
                    r['ok'] = bool(float(r['flow_mean']) >= float(r['min_flow']))
                    notes.append(f'regions.{name}.ok derived from flow_mean vs min_flow')

        props = sig.get('props')
        if isinstance(props, dict):
            for name, p in props.items():
                if not isinstance(p, dict):
                    continue
                if p.get('ncc_min') is None:
                    p['ncc_min'] = _PROP_NCC_MIN
                    notes.append(f'props.{name}.ncc_min defaulted to {_PROP_NCC_MIN}')
                if p.get('pinned') is None:
                    p['pinned'] = name in keep
                    notes.append(f'props.{name}.pinned derived from keep_boxes membership ({p["pinned"]})')
                if p.get('box') is None and name in keep:
                    p['box'] = keep[name]
                    notes.append(f'props.{name}.box taken from keep_boxes.{name}')
        return sig, notes
    except Exception as e:
        return (signature if isinstance(signature, dict) else {}, [f'normalize failed (signature used as-is): {e}'])
