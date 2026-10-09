# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Quality: run classification, the gate ledger, and the row/table builders behind every detail view."""

from __future__ import annotations

import hashlib
import os
import re
from zyg_workflows import pgdb
import time

from .constants import RUNTIME
from .helpers import _CACHE, _LOCK, _cached, _is_test_id, _iso, _iter_jsonl, _short

# ── quality: gates, fallbacks, receipts ──────────────────────────────────────


def _test_run_ids():
    """-> (test run ids, test process pids, real debug-run rows) from debug_run_history.jsonl.

    DebugRun ids end in the pid of the process that made them ("gates-20260906-021634-1900003").
    A pytest session makes several runs from ONE process, and only some of them show a /tmp
    dir in the history — its sibling "t-20260906-021634-1900003" does not — so a run id sharing
    a known test pid is a test run too."""
    path = os.path.join(RUNTIME, 'debug_run_history.jsonl')

    def load_debug_history(p):
        test, pids, real = set(), set(), []
        for r in _iter_jsonl(p):
            d = str(r.get('dir') or '')
            # A recorded cwd is compared, not opened: runs under the scratch dir or pytest
            # are test rows. The literal is what past runs wrote down, so it stays literal.
            if d.startswith('/tmp/') or 'pytest' in d:  # nosec B108  # noqa: S108  match on a recorded path, nothing is created
                test.add(r.get('run_id'))
                m = re.search(r'-(\d{3,})$', str(r.get('run_id') or ''))
                if m:
                    pids.add(m.group(1))
            else:
                real.append(r)
        return (
            test,
            pids,
            [
                r
                for r in real
                if not re.search(r'-(\d{3,})$', str(r.get('run_id') or ''))
                or re.search(r'-(\d{3,})$', str(r.get('run_id'))).group(1) not in pids
            ],
        )

    return _cached(path, load_debug_history) or (set(), set(), [])


def _run_class(rid, test_ids, test_pids):
    if not rid or rid == 'adhoc':
        return 'unattributed'
    low = rid.lower()
    m = re.search(r'-(\d{3,})$', rid)
    if (
        rid in test_ids
        or (m and m.group(1) in test_pids)
        or low.isdigit()
        or _is_test_id(rid)
        or any(t in low for t in ('selftest', 'pytest', 'calib', 'test_', '_test', 'smoke', 'gatecheck'))
    ):
        return 'test'
    return 'real'


def _ledger_rows():
    sig = int(time.time() // 60)  # 60 s cache (no file mtime to watch any more)
    hit = _CACHE.get(('pg', 'ledger'))
    if hit and hit[0] == sig:
        return hit[1]
    try:
        gates = pgdb.tuples('SELECT run_id, gate, outcome, score, tag, ts FROM gates')
        falls = pgdb.tuples('SELECT component, expected, actual, detail, run_id, ts FROM fallbacks')
    except Exception:
        return [], []
    with _LOCK:
        _CACHE[('pg', 'ledger')] = (sig, (gates, falls))
    return gates, falls


# ── quality detail: the rows behind one metric or verdict ────────────────────
# Every number and verdict on the Quality tab is a link: the tab hands the token
# it shipped with that row back on the same endpoint (?detail=<token>), and this
# builds the rows it was computed from. Shapes, so the tab only has to draw:
#   {ok, token, title, subtitle, facts:[{label,value,sub}], tables:[...], notes:[]}
#   table  = {title, note, columns:[{t,r}], rows:[...], empty, limited}
#   row    = [cell, ...]  |  {cells:[...], detail:<token>}
#   cell   = "text"       |  {v, tone:good|critical|warning|serious|neutral, muted, detail}

_DETAIL_ROWS = 400
_OUTCOME_TONE = {'pass': 'good', 'fail': 'critical', 'shadow_fail': 'warning'}


def _fb_name(comp):
    """The component name as the Fallbacks table shows it (lora paths collapse to a basename)."""
    name = comp or '(unnamed)'
    return 'lora:' + os.path.basename(name[5:]) if name.startswith('lora:') else name


def _fb_key(name, exp, act):
    """Opaque id for one (component, expected, actual) triple — the token the tab sends back."""
    return hashlib.sha1(
        '\x1f'.join((name or '', exp or '', act or '')).encode('utf-8'), usedforsecurity=False
    ).hexdigest()[:12]


def _dbg_key(row):
    """Per-ROW id for debug_run_history.jsonl. A run id is not unique there — a probe and
    the render it belongs to file two verdicts under the same id — so the token carries
    the row, not just the id."""
    seed = '\x1f'.join(str(row.get(k) or '') for k in ('run_id', 'name', 'ts', 'dir'))
    return hashlib.sha1(seed.encode('utf-8'), usedforsecurity=False).hexdigest()[:12]


def _debug_index():
    """-> ({row key: history row}, {run_id: names seen}) over every debug run, test rows included."""
    path = os.path.join(RUNTIME, 'debug_run_history.jsonl')

    def load_debug_index(p):
        rows, names = {}, {}
        for r in _iter_jsonl(p):
            rid = str(r.get('run_id') or '')
            if not rid:
                continue
            rows[_dbg_key(r)] = r
            n = str(r.get('name') or '')
            if n and n not in names.setdefault(rid, []):
                names[rid].append(n)
        return rows, {k: ' / '.join(v) for k, v in names.items()}

    return _cached(path, load_debug_index) or ({}, {})


def _test_reason(rid, test_ids, test_pids):
    """Why _run_class called this row a test row — named, not just asserted."""
    low = (rid or '').lower()
    m = re.search(r'-(\d{3,})$', rid or '')
    if rid in test_ids:
        return 'debug dir under /tmp or pytest'
    if m and m.group(1) in test_pids:
        return 'shares pytest process id ' + m.group(1)
    if low.isdigit():
        return 'numeric run id'
    if _is_test_id(rid):
        return 'test-shaped id'
    for t in ('selftest', 'pytest', 'calib', 'test_', '_test', 'smoke', 'gatecheck'):
        if t in low:
            return f'id contains "{t}"'
    return 'classified test'


def _tbl(title, columns, rows, empty='Nothing recorded.', note='', limit=_DETAIL_ROWS):
    shown = rows[:limit] if limit else rows
    return {
        'title': title,
        'columns': columns,
        'rows': shown,
        'empty': empty,
        'note': note,
        'limited': (len(rows) - len(shown)) or None,
        'total': len(rows),
    }


def _fact(label, value, sub=''):
    return {'label': label, 'value': '—' if value is None else str(value), 'sub': sub}


def _run_cell(rid, names):
    if not rid or rid == 'adhoc':
        return {'v': 'adhoc — no run id', 'muted': True}
    return {'v': rid, 'detail': 'run:' + rid, 'sub': names.get(rid, '')}


_GATE_COLS = [
    {'t': 'Time'},
    {'t': 'Gate'},
    {'t': 'Outcome'},
    {'t': 'Score', 'r': True},
    {'t': 'Tag'},
    {'t': 'Attribution'},
    {'t': 'Run'},
]


def _gate_row(ts, rid, gate, outcome, score, tag, cls, names):
    o = (outcome or '').lower()
    return [
        _iso(ts) or '—',
        gate or '(unnamed)',
        {'v': outcome or '—', 'tone': _OUTCOME_TONE.get(o, 'neutral')},
        '—' if score is None else str(round(float(score), 4)),
        tag or '—',
        {'v': cls, 'muted': cls != 'real'},
        _run_cell(rid, names),
    ]


_FALL_COLS = [
    {'t': 'Time'},
    {'t': 'Component'},
    {'t': 'Expected → actual'},
    {'t': 'Detail'},
    {'t': 'Attribution'},
    {'t': 'Run'},
]


def _fall_row(ts, comp, exp, act, detail, rid, cls, names, link=True):
    name = _fb_name(comp)
    return [
        _iso(ts) or '—',
        {'v': name, 'detail': ('fallback:' + _fb_key(name, exp or '', act or '')) if link else None},
        (exp or '?') + ' → ' + (act or '?'),
        {'v': _short(detail, 200) or '—', 'muted': not detail},
        {'v': cls, 'muted': cls != 'real'},
        _run_cell(rid, names),
    ]
