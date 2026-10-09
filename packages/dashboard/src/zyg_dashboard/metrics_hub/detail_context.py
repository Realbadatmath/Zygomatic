# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The shared state behind one ?detail=<token> view, as an object instead of a closure.

`quality_detail` used to carry its window, its ledger snapshot and five nested helpers
(`cls_of`, `in_window`, `gate_rows`, `fall_rows`, `out`) in one 666-line body. They are the
same functions here, as methods on `DetailContext`, so every section module can be handed
one object and every helper can be exercised on its own.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from .quality import (
    _debug_index,
    _fall_row,
    _gate_row,
    _ledger_rows,
    _run_class,
    _test_reason,
    _test_run_ids,
)
from .runs import _window


@dataclass
class DetailContext:
    """One detail request: the parsed token, the window, and the ledger rows it reads.

    Built by `build_detail_context`; the section builders only ever read it.
    `gates` rows are `(run_id, gate, outcome, score, tag, ts)` and `falls` rows are
    `(component, expected, actual, detail, run_id, ts)`, exactly as `_ledger_rows` yields them.
    """

    token: str = ''
    kind: str = ''
    key: str = ''
    days: int = 30
    now: float = 0.0
    since: float | None = None
    window: str = 'all time'
    test_ids: set = field(default_factory=set)
    test_pids: set = field(default_factory=set)
    real_debug: list = field(default_factory=list)
    gates: list = field(default_factory=list)
    falls: list = field(default_factory=list)
    hist: dict = field(default_factory=dict)
    names: dict = field(default_factory=dict)

    def cls_of(self, rid):
        """'real' | 'test' | 'unattributed' for one run id, against this request's test sets."""
        return _run_class(rid, self.test_ids, self.test_pids)

    def test_reason(self, rid):
        """The named rule that made `rid` a test row (for the 'why it was excluded' column)."""
        return _test_reason(rid, self.test_ids, self.test_pids)

    def in_window(self, ts):
        """True when `ts` falls inside the request's window (always True for `days=0`)."""
        return self.since is None or (ts or 0) >= self.since

    def gate_rows(self, pred, windowed=True):
        """-> (drawn gate rows, count) for the ledger gate rows matching `pred`, newest first.

        `pred` sees the enriched tuple `(ts, rid, gate, outcome, score, tag, cls)`.
        """
        rows = [
            (ts, rid, gate, outcome, score, tag, self.cls_of(rid))
            for rid, gate, outcome, score, tag, ts in self.gates
            if (not windowed or self.in_window(ts))
        ]
        rows = [r for r in rows if pred(r)]
        rows.sort(key=lambda r: -(r[0] or 0))
        return [_gate_row(*r, self.names) for r in rows], len(rows)

    def fall_rows(self, pred, windowed=True, link=True):
        """-> (drawn fallback rows, count) for the fallback rows matching `pred`, newest first.

        `pred` sees the enriched tuple `(ts, comp, exp, act, det, rid, cls)`; `link=False`
        drops the per-component drill-down link (the component page links to itself).
        """
        rows = [
            (ts, comp, exp, act, det, rid, self.cls_of(rid))
            for comp, exp, act, det, rid, ts in self.falls
            if (not windowed or self.in_window(ts))
        ]
        rows = [r for r in rows if pred(r)]
        rows.sort(key=lambda r: -(r[0] or 0))
        return [_fall_row(*r, self.names, link) for r in rows], len(rows)

    def out(self, title, subtitle, facts, tables, notes=(), win=None):
        """The detail payload the Quality tab draws; falsy facts and tables are dropped."""
        return {
            'ok': True,
            'token': self.token,
            'kind': self.kind,
            'title': title,
            'subtitle': subtitle,
            'facts': [f for f in facts if f],
            'tables': [t for t in tables if t],
            'notes': list(notes),
            'window_days': self.days,
            'window': self.window if win is None else win,
        }


def build_detail_context(token, days=30, now=None):
    """Parse `token`, resolve the window and load the ledger / debug index for one request."""
    now = now or time.time()
    kind, _, key = str(token or '').partition(':')
    test_ids, test_pids, real_debug = _test_run_ids()
    gates, falls = _ledger_rows()
    hist, names = _debug_index()
    return DetailContext(
        token=token,
        kind=kind,
        key=key,
        days=days,
        now=now,
        since=_window(days, now),
        window=f'last {days} days' if days else 'all time',
        test_ids=test_ids,
        test_pids=test_pids,
        real_debug=real_debug,
        gates=gates,
        falls=falls,
        hist=hist,
        names=names,
    )
