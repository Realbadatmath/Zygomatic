#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Scorecard for one Architecture-Assistant job, read back from the conversations ledger.

The ledger is data/runtime/arch_assistant/conversations/<date>.jsonl, one JSON object
per line.  The 'end' event of a job carries everything this scores: the drawing-call
budget, the design_check results echoed into 'log', the tool calls the model made,
the summary it signed off with and the token/cost usage.

    python3 arch_live_score.py                      # newest ledger, last job
    python3 arch_live_score.py --job 94f5813b       # that job in the newest ledger
    python3 arch_live_score.py --file X --job Y
    python3 arch_live_score.py ... --expect-red     # invert: 0 when at least one RED

Exit 0 when no signal is RED, 1 otherwise (--expect-red inverts).  UNKNOWN never
decides the exit code.
"""

from __future__ import annotations

import glob
import json
import os
import re
import sys
import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)


LEDGER_DIR = os.path.join('data', 'runtime', 'arch_assistant', 'conversations')

GREEN, RED, UNKNOWN = 'GREEN', 'RED', 'UNKNOWN'

# '  design check: 3 errors, 11 warnings' / '  design check: 1 error, 11 warnings'
RE_DESIGN_CHECK = re.compile(r'^\s*design check:\s+(\d+)\s+errors?\b', re.I)
RE_DESIGN_CLEAN = re.compile(r'^\s*design check:\s+no findings\b', re.I)
# 'prompt: 22 families in, 56 out, 41k chars'
RE_PROMPT = re.compile(r'^\s*prompt:\s*(\d+)\s+families in,\s*(\d+)\s+out(?:,\s*(\S+)\s+chars)?', re.I)
# 'present: 5 pictures handed to the model'
RE_PICTURES = re.compile(r'^\s*present:\s*(\d+)\s+pictures? handed to the model', re.I)
# a call, as logged: 'name(args)'
RE_CALL = re.compile(r'^([A-Za-z_][A-Za-z0-9_]*)\((.*)\)\s*$', re.S)

# the families a tower cannot be drawn without
TOWER_FAMILIES = ('floor_plans',)


def load_ledger(path):
    rows = []
    with open(path, encoding='utf-8') as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except ValueError as _exc:
                _zyg_log.debug('non-JSON ledger line skipped: %s', _exc)
                continue
    return rows


def newest_ledger():
    files = sorted(glob.glob(os.path.join(LEDGER_DIR, '*.jsonl')))
    if not files:
        sys.exit('no ledger files under %s' % LEDGER_DIR)
    return files[-1]


def pick_end_event(rows, job=None):
    ends = [r for r in rows if r.get('event') == 'end']
    if not ends:
        sys.exit('no "end" event in this ledger')
    if job:
        ends = [r for r in ends if str(r.get('id', '')).startswith(job)]
        if not ends:
            sys.exit('no "end" event whose id starts with %r' % job)
    return ends[-1]


def log_lines(end):
    """The log, flattened: entries carry embedded newlines (design_check detail)."""
    out = []
    for entry in end.get('log') or []:
        for part in str(entry).split('\n'):
            out.append(part)
    return out


def split_call(call):
    """'add_beach_set(cells=[...], name=x)' -> ('add_beach_set', 'cells=[...], name=x')."""
    m = RE_CALL.match(str(call).strip())
    if not m:
        return str(call).strip(), ''
    return m.group(1), m.group(2)


def arg_value(args, key):
    """Value of key= in a logged arg string, top level only, quotes/brackets stripped."""
    depth = 0
    token = ''
    tokens = []
    for ch in args:
        if ch in '([{':
            depth += 1
        elif ch in ')]}':
            depth -= 1
        if ch == ',' and depth == 0:
            tokens.append(token)
            token = ''
        else:
            token += ch
    tokens.append(token)
    for tok in tokens:
        if '=' not in tok:
            continue
        k, _, v = tok.partition('=')
        if k.strip() != key:
            continue
        return v.strip().strip('\'"')
    return None


def find_replacements(tool_calls):
    """delete(which=X) followed later by add_*(… name=X) — one re-placement each."""
    parsed = [split_call(c) for c in tool_calls or []]
    deletes = []  # (index, target)
    adds = []  # (index, name)
    for i, (name, args) in enumerate(parsed):
        if name == 'delete':
            target = arg_value(args, 'which')
            if target:
                deletes.append((i, target))
        elif name.startswith('add_'):
            nm = arg_value(args, 'name')
            if nm:
                adds.append((i, nm))
    pairs = []
    used = set()
    for di, target in deletes:
        for j, (ai, nm) in enumerate(adds):
            if j in used or ai <= di or nm != target:
                continue
            used.add(j)
            pairs.append(target)
            break
    return pairs


def design_check_errors(lines):
    """(count of design_check result lines, errors reported by the LAST one)."""
    counts = []
    for line in lines:
        if RE_DESIGN_CLEAN.match(line):
            counts.append(0)
            continue
        m = RE_DESIGN_CHECK.match(line)
        if m:
            counts.append(int(m.group(1)))
    return counts


def score(end):
    """-> (list of (state, label, detail), )"""
    lines = log_lines(end)
    tool_calls = end.get('tool_calls') or []
    parsed_names = [split_call(c)[0] for c in tool_calls]
    summary = str(end.get('summary') or '')
    rows = []

    # 1 — cap reached
    draw_calls, budget = end.get('draw_calls'), end.get('budget')
    if draw_calls is None or budget is None:
        rows.append((UNKNOWN, 'cap reached', 'this ledger carries no draw_calls/budget'))
    elif draw_calls >= budget:
        rows.append((RED, 'cap reached', '%s/%s drawing calls — the model ran out of budget' % (draw_calls, budget)))
    else:
        rows.append((GREEN, 'cap reached', '%s/%s drawing calls' % (draw_calls, budget)))

    # 2 — errors at exit
    dc_counts = design_check_errors(lines)
    last_errors = dc_counts[-1] if dc_counts else None
    why = []
    if last_errors:
        why.append('last design check: %d error(s)' % last_errors)
    if summary.startswith('UNFINISHED'):
        why.append('summary starts UNFINISHED')
    if 'Design check: [error]' in summary:
        why.append('summary carries "Design check: [error]"')
    if why:
        rows.append((RED, 'errors at exit', '; '.join(why)))
    elif last_errors == 0:
        rows.append((GREEN, 'errors at exit', 'last design check: 0 errors'))
    else:
        rows.append((UNKNOWN, 'errors at exit', 'no design check result in the log'))

    # 3 — job incomplete flag
    incomplete = end.get('incomplete')
    stop = end.get('stop')
    detail = 'incomplete=%r status=%r stop=%r' % (incomplete, end.get('status'), stop)
    rows.append(((RED if incomplete else GREEN), 'job incomplete flag', detail))

    # 4 — design_check calls
    n_checks = parsed_names.count('design_check')
    rows.append(
        ((GREEN if n_checks else RED), 'design_check calls', '%d call(s)' % n_checks if n_checks else 'never called')
    )

    # 5 — re-placements
    pairs = find_replacements(tool_calls)
    n_rep = len(pairs)
    detail = '%d (%s)' % (n_rep, ', '.join(pairs)) if pairs else '0'
    rows.append(((RED if n_rep >= 2 else GREEN), 're-placements', detail))

    # 6 — present called
    presented = 'present' in parsed_names
    present_log = any(
        re.match(r'^\s*present', line, re.I) or re.match(r'^\s*presented\b', line, re.I) for line in lines
    )
    if presented or present_log:
        rows.append((GREEN, 'present called', 'yes'))
    else:
        rows.append((RED, 'present called', 'the job never presented'))

    # 7 — pictures handed to the model
    pics = None
    for line in lines:
        m = RE_PICTURES.match(line)
        if m:
            pics = int(m.group(1))
    if pics is not None:
        rows.append(((GREEN if pics else RED), 'pictures handed to the model', '%d picture(s)' % pics))
    elif presented or present_log:
        rows.append(
            (
                RED,
                'pictures handed to the model',
                'present ran but the log has no "present: N pictures handed to the model" line',
            )
        )
    else:
        rows.append((UNKNOWN, 'pictures handed to the model', 'nothing was presented'))

    # 8 — families dropped
    fam = None
    for line in lines:
        m = RE_PROMPT.match(line)
        if m:
            fam = m.groups()
    if fam:
        detail = (
            '%s families in, %s out%s — the ledger carries counts only, not the kept '
            'list, so %s cannot be confirmed'
            % (fam[0], fam[1], (', %s chars' % fam[2]) if fam[2] else '', '/'.join(TOWER_FAMILIES))
        )
        rows.append((UNKNOWN, 'families dropped', detail))
    else:
        rows.append((UNKNOWN, 'families dropped', 'no "prompt: N families in" line in the log'))

    # 9 — turns and cost
    usage = end.get('usage') or {}
    turns = usage.get('turns')
    cost = usage.get('cost_usd')
    rows.append(
        (
            GREEN,
            'turns and cost',
            'turns=%s out=%s cache_read=%s cost=$%s elapsed=%ss model=%s auth=%s'
            % (
                turns,
                usage.get('out'),
                usage.get('cache_read'),
                cost,
                end.get('elapsed'),
                end.get('model'),
                end.get('auth'),
            ),
        )
    )

    return rows


if __name__ == '__main__':  # the CLI lives in arch_live_score_cli
    from zyg_workflows.arch_live_score_cli import main as _cli_main

    raise SystemExit(_cli_main())
