#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""preempt_meter_share.py — how much of the Claude meter's movement is the BANK.

2026-09-23, the operator's question: "does this take into account that I have many other
agents running at the same time? only a small portion would be these calls."

It did not. The 7-day meter is one number for the whole login: every Claude Code session
on this box bills to it. Measured just after the 21:00 reset there were NINE — seven agent
sessions, the architecture assistant, and the bank — so attributing the meter's whole move
to the bank overstated a recording's cost by more than 10x.

Every session writes a transcript under ~/.claude/projects/<cwd-slug>/*.jsonl with usage
per assistant message, so the split is measurable. Two weightings are returned because the
meter's own weighting of cached tokens is not published:

  * `out`  — output tokens only, priced by model. Pessimistic for the bank: it generates a
             lot of output and reads almost no cache.
  * `list` — every token at list price, cache included. Optimistic for the bank: an agent
             session re-reads a huge cached context on every call.

The truth is between them, so callers should carry both rather than pick one.
"""

from __future__ import annotations

import glob
import json
import os
from datetime import datetime
import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)


PROJECTS = os.path.expanduser('~/.claude/projects')
BANK_PROJECT = '-home-zygomatic-Zygomatic-Full-agents-crews-data-runtime-scholarly-llm-cli'
#            in / out / cache-write / cache-read, $ per M tokens
PRICE = {
    'opus': (15.0, 75.0, 18.75, 1.5),
    'fable': (15.0, 75.0, 18.75, 1.5),
    'sonnet': (3.0, 15.0, 3.75, 0.3),
    'haiku': (1.0, 5.0, 1.25, 0.1),
}


def _price(model):
    m = str(model or '').lower()
    for k, v in PRICE.items():
        if k in m:
            return v
    return PRICE['sonnet']


def usage_by_session(since: float, until: float = None) -> dict:
    """{project: {calls, out_tokens, out_value, list_value}} for [since, until]."""
    out = {}
    for path in glob.glob(os.path.join(PROJECTS, '*', '*.jsonl')):
        try:
            if os.path.getmtime(path) < since - 3600:
                continue
            fh = open(path, encoding='utf-8')
        except OSError as _exc:
            _zyg_log.warning('session log %s unreadable, its usage is missing from the share: %s', path, _exc)
            continue
        proj = os.path.basename(os.path.dirname(path))
        with fh:
            for line in fh:
                if '"usage"' not in line:
                    continue
                try:
                    d = json.loads(line)
                except ValueError as _exc:
                    _zyg_log.debug('malformed usage record skipped in %s: %s', path, _exc)
                    continue
                try:
                    t = datetime.fromisoformat(str(d.get('timestamp')).replace('Z', '+00:00')).timestamp()
                except (TypeError, ValueError) as _exc:
                    _zyg_log.debug('usage record without a parsable timestamp skipped in %s: %s', path, _exc)
                    continue
                if t < since or (until and t > until):
                    continue
                m = d.get('message') or {}
                u = m.get('usage') or {}
                if not u:
                    continue
                p = _price(m.get('model'))
                tin = int(u.get('input_tokens') or 0)
                tout = int(u.get('output_tokens') or 0)
                cw = int(u.get('cache_creation_input_tokens') or 0)
                cr = int(u.get('cache_read_input_tokens') or 0)
                r = out.setdefault(proj, {'calls': 0, 'out_tokens': 0, 'out_value': 0.0, 'list_value': 0.0})
                r['calls'] += 1
                r['out_tokens'] += tout
                r['out_value'] += tout * p[1] / 1e6
                r['list_value'] += (tin * p[0] + tout * p[1] + cw * p[2] + cr * p[3]) / 1e6
    return out


def bank_share(since: float, until: float = None) -> dict:
    """The bank's share of everything billed to this login in the window."""
    rows = usage_by_session(since, until)
    bank = rows.get(BANK_PROJECT, {'calls': 0, 'out_tokens': 0, 'out_value': 0.0, 'list_value': 0.0})
    tot_out = sum(r['out_value'] for r in rows.values())
    tot_list = sum(r['list_value'] for r in rows.values())
    return {
        'sessions': len(rows),
        'bank': bank,
        'others': {k: v for k, v in rows.items() if k != BANK_PROJECT},
        'share_out': (bank['out_value'] / tot_out) if tot_out else None,
        'share_list': (bank['list_value'] / tot_list) if tot_list else None,
        'total_out_value': tot_out,
        'total_list_value': tot_list,
    }


if __name__ == '__main__':
    import sys

    hhmm = sys.argv[sys.argv.index('--since') + 1] if '--since' in sys.argv else '21:00'
    since = datetime.now().replace(hour=int(hhmm[:2]), minute=int(hhmm[3:]), second=0, microsecond=0).timestamp()
    s = bank_share(since)
    print(f'{s["sessions"]} sessions billed to this login since {hhmm}\n')
    print('%-46s %7s %10s %10s %10s' % ('session', 'calls', 'out_tok', '$ output', '$ w/ cache'))
    rows = dict(s['others'])
    rows[BANK_PROJECT] = s['bank']
    for proj, r in sorted(rows.items(), key=lambda kv: -kv[1]['out_value']):
        tag = '  <-- THE BANK' if proj == BANK_PROJECT else ''
        print(
            '%-46s %7d %10d %10.2f %10.2f%s'
            % (
                proj.replace('-home-zygomatic-', '~/')[:46],
                r['calls'],
                r['out_tokens'],
                r['out_value'],
                r['list_value'],
                tag,
            )
        )
    print(
        f'\nbank share of the meter: {100 * (s["share_out"] or 0):.1f} % by output, '
        f'{100 * (s["share_list"] or 0):.1f} % with cache counted — the true weighting is between them'
    )
