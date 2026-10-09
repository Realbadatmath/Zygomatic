# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The receipt, VLM-counter, chart-bucket and single-run halves of the ?detail=<token> view.

One builder per token kind, each taking the `DetailContext` that `detail.quality_detail`
built and returning the payload the Quality tab draws (or the `{'ok': False, 'error': …}`
refusal the original function returned in that branch).
"""

from __future__ import annotations

from .helpers import _iso, _rate
from .quality import _FALL_COLS, _GATE_COLS, _fact, _tbl
from .runs import _bucket_of, _bucketing, collect_runs

_RUN_STATUS_TONE = {'completed': 'good', 'failed': 'critical'}


def verdict_label(v):
    """The one word the tab prints for a filed verdict dict: Blocked / Passed / Checks failed."""
    if v.get('blocked'):
        return 'Blocked'
    if v.get('ok'):
        return 'Passed'
    if v.get('ok') is False:
        return 'Checks failed'
    return 'Unrecorded'


def verdict_tone(v):
    """The tone that goes with `verdict_label` — critical / good / warning / neutral."""
    if v.get('blocked'):
        return 'critical'
    if v.get('ok'):
        return 'good'
    if v.get('ok') is False:
        return 'warning'
    return 'neutral'


def _run_cells(r, trailing):
    """The shared run columns (started, id, kind, title, status) plus `trailing` cells."""
    return [
        _iso(r['t']) or '—',
        r['id'][:36],
        r['kind'],
        {'v': r['title'] or '—', 'muted': not r['title']},
        {'v': r['status'], 'tone': _RUN_STATUS_TONE.get(r['status'])},
        *trailing,
    ]


def receipt_rows(ctx, gate):
    """-> (ran rows, did-not-run rows, {reason: runs}) for one gate's receipts, newest first."""
    runs, _meta = collect_runs(ctx.now)
    ran_rows, not_rows = [], []
    reasons: dict = {}
    for r in runs:
        rec = (r.get('gate_receipts') or {}).get(gate)
        if rec is None or not ctx.in_window(r['t']):
            continue
        cells = _run_cells(r, [{'v': rec['reason'] or '—', 'muted': not rec['reason']}])
        if rec['ran']:
            ran_rows.append(cells)
        else:
            not_rows.append(cells)
            reasons[rec['reason'] or '(no reason)'] = reasons.get(rec['reason'] or '(no reason)', 0) + 1
    ran_rows.sort(key=lambda c: c[0], reverse=True)
    not_rows.sort(key=lambda c: c[0], reverse=True)
    return ran_rows, not_rows, reasons


def receipt_section(ctx):
    """receipt:<gate> — which runs asked for this gate, which skipped it and why."""
    ran_rows, not_rows, reasons = receipt_rows(ctx, ctx.key)
    if not ran_rows and not not_rows:
        return {'ok': False, 'error': f'no receipts for gate {ctx.key!r} in this range'}
    cols = [{'t': 'Started'}, {'t': 'Run'}, {'t': 'Kind'}, {'t': 'Title'}, {'t': 'Run status'}, {'t': 'Reason'}]
    led, _n = ctx.gate_rows(lambda r: ((r[2] or '').split(':', 1)[0] or '') == ctx.key or (r[2] or '') == ctx.key)
    return ctx.out(
        f'Gate receipt · {ctx.key}',
        f'Which runs asked for this gate, {ctx.window}.',
        [
            _fact('Ran', f'{len(ran_rows):,}'),
            _fact('Did not run', f'{len(not_rows):,}'),
            _fact('Runs seen', f'{len(ran_rows) + len(not_rows):,}'),
            _fact('Ledger rows', f'{_n:,}', 'outcomes this gate actually recorded'),
        ],
        [
            _tbl(
                'Why it did not run',
                [{'t': 'Reason'}, {'t': 'Runs', 'r': True}],
                [[r, str(c)] for r, c in sorted(reasons.items(), key=lambda kv: -kv[1])],
                'It ran in every run that filed a receipt.',
                limit=None,
            ),
            _tbl('Runs where it did not run', cols, not_rows, 'None.'),
            _tbl('Runs where it ran', cols, ran_rows, 'None.'),
            _tbl(
                'Outcomes this gate recorded in the ledger',
                _GATE_COLS,
                led,
                'This gate filed receipts but recorded no outcome in the ledger.',
            ),
        ],
        ['A receipt says whether the pipeline reached the gate. "Did not run" is not a pass: nothing was checked.'],
    )


def vlm_rows(ctx, counter):
    """-> (rows newest first, total, largest single run) for one vlm_gate_stats counter."""
    runs, _meta = collect_runs(ctx.now)
    rows, total, biggest = [], 0, 0
    for r in runs:
        v = (r.get('vlm') or {}).get(counter)
        if v is None or not ctx.in_window(r['t']):
            continue
        total += v
        biggest = max(biggest, v)
        rows.append(_run_cells(r, [f'{v:,}']))
    rows.sort(key=lambda c: c[0], reverse=True)
    return rows, total, biggest


def vlm_section(ctx):
    """vlm:<counter> — the runs that added to one VLM-gate counter, summed from their states."""
    rows, total, biggest = vlm_rows(ctx, ctx.key)
    if not rows:
        return {'ok': False, 'error': f'no run recorded the counter {ctx.key!r} in this range'}
    return ctx.out(
        'VLM counter · ' + ctx.key.replace('_', ' '),
        f'Runs that added to this counter, {ctx.window}.',
        [
            _fact('Total', f'{total:,}'),
            _fact('Runs', f'{len(rows):,}'),
            _fact('Largest single run', f'{biggest:,}'),
        ],
        [
            _tbl(
                'Per run, newest first',
                [
                    {'t': 'Started'},
                    {'t': 'Run'},
                    {'t': 'Kind'},
                    {'t': 'Title'},
                    {'t': 'Run status'},
                    {'t': ctx.key.replace('_', ' '), 'r': True},
                ],
                rows,
                'None.',
            )
        ],
        [
            'These counters are summed from each run state file (vlm_gate_stats); they count '
            'what the VLM gate did, not gate outcomes.'
        ],
    )


def day_section(ctx):
    """day:<bucket> — the attributed gate rows and fallbacks inside one chart bucket."""
    earliest = min([g[5] for g in ctx.gates if g[5]] + [f[5] for f in ctx.falls if f[5]], default=None)
    keys, weekly = _bucketing(ctx.since, ctx.now, earliest)
    if ctx.key not in keys:
        return {'ok': False, 'error': f'{ctx.key} is not a bucket in this range'}
    rows, n = ctx.gate_rows(lambda r: r[6] == 'real' and r[0] and _bucket_of(r[0], weekly) == ctx.key)
    frows, fn = ctx.fall_rows(lambda r: r[6] != 'test' and r[0] and _bucket_of(r[0], weekly) == ctx.key)
    passes = sum(1 for r in rows if r[2]['v'].lower() == 'pass')
    fails = sum(1 for r in rows if r[2]['v'].lower() == 'fail')
    return ctx.out(
        ('Week of ' if weekly else '') + ctx.key,
        'Attributed gate rows and fallbacks in this bucket.',
        [
            _fact('Pass', f'{passes:,}'),
            _fact('Fail', f'{fails:,}'),
            _fact('Pass rate', '—' if not (passes + fails) else f'{_rate(passes, passes + fails)} %'),
            _fact('Fallbacks', f'{fn:,}'),
        ],
        [
            _tbl('Gate rows in this bucket', _GATE_COLS, rows, 'No attributed gate rows.'),
            _tbl('Fallbacks in this bucket', _FALL_COLS, frows, 'No fallbacks.'),
        ],
    )


def verdict_facts(rec, ledger_facts):
    """-> the filed-verdict facts, with `ledger_facts` (run id, attribution, counts) appended."""
    v = rec.get('verdict') or {}
    return [
        _fact('Verdict', verdict_label(v), rec.get('name') or ''),
        _fact('Failed checks', v.get('failed_checks')),
        _fact('Passed checks', v.get('passed_checks')),
        _fact('Unknown checks', v.get('unknown_checks')),
        _fact('Degradations', rec.get('degradations')),
        _fact('Shadow failures', v.get('shadow_failed')),
        _fact('Gate mode', v.get('gate_mode') or ('enforcing' if v.get('enforcement') else '—')),
        _fact('Coverage score', v.get('coverage_score')),
        _fact('Finished', v.get('finished') or rec.get('ts')),
        _fact('Debug dir', rec.get('dir') or '—'),
    ] + ledger_facts


def verdict_named_table(v):
    """-> the 'What the verdict named' table: blocking / warning / shadow failures, then tags."""
    named = (
        [('Blocking failure', x, 'critical') for x in (v.get('blocking_failures') or [])]
        + [('Warning failure', x, 'warning') for x in (v.get('warning_failures') or [])]
        + [('Shadow failure', x, 'warning') for x in (v.get('shadow_failed_checks') or [])]
        + [('Tag', x, 'neutral') for x in (v.get('tags') or [])]
        + [('Shadow tag', x, 'neutral') for x in (v.get('shadow_tags') or [])]
    )
    return _tbl(
        'What the verdict named',
        [{'t': 'Kind'}, {'t': 'Check or tag'}],
        [[{'v': k, 'tone': t}, x] for k, x, t in named],
        'The verdict named no failing check or tag — only a count.',
        limit=None,
    )


def coverage_table(v):
    """-> the defect-class coverage table, or None when the verdict recorded no coverage dict."""
    cov = v.get('coverage') if isinstance(v.get('coverage'), dict) else {}
    if not cov:
        return None
    covered = sum(1 for x in cov.values() if x == 'covered')
    return _tbl(
        'Defect-class coverage',
        [{'t': 'Class'}, {'t': 'Covered'}],
        [[c, {'v': x, 'tone': 'good' if x == 'covered' else 'warning'}] for c, x in sorted(cov.items())],
        'No coverage recorded.',
        limit=None,
        note=f'{covered} of {len(cov)} defect classes were checked at all',
    )


def siblings_table(siblings, key):
    """-> the 'Verdicts filed under this run id' table; the row for `key` itself is not a link."""
    return _tbl(
        'Verdicts filed under this run id',
        [
            {'t': 'Time'},
            {'t': 'Name'},
            {'t': 'Verdict'},
            {'t': 'Failed checks', 'r': True},
            {'t': 'Degradations', 'r': True},
            {'t': 'Debug dir'},
        ],
        [
            {
                'cells': [
                    str(r.get('ts') or '—'),
                    str(r.get('name') or '—'),
                    {
                        'v': verdict_label(r.get('verdict') or {}),
                        'tone': verdict_tone(r.get('verdict') or {}),
                    },
                    str((r.get('verdict') or {}).get('failed_checks') or 0),
                    str(r.get('degradations') or 0),
                    {'v': str(r.get('dir') or '—'), 'muted': True},
                ],
                'detail': None if k == key else 'debug:' + k,
            }
            for k, r in siblings
        ],
        'No verdict was filed under this run id.',
        limit=None,
        note='A probe and the render it belongs to file separate verdicts under one run id.',
    )


def run_siblings(ctx, rid):
    """-> the debug-history rows filed under `rid` as (row key, row), newest `ts` first."""
    return sorted(
        ((k, r) for k, r in ctx.hist.items() if str(r.get('run_id')) == rid),
        key=lambda kr: str(kr[1].get('ts') or ''),
        reverse=True,
    )


def run_section(ctx):
    """run:<run id> / debug:<row key> — one run's ledger side and the verdicts filed under it."""
    rec = ctx.hist.get(ctx.key) if ctx.kind == 'debug' else None
    if ctx.kind == 'debug' and rec is None:
        return {'ok': False, 'error': 'that verdict is no longer in debug_run_history.jsonl'}
    rid = str(rec.get('run_id')) if rec else ctx.key
    grows, gn = ctx.gate_rows(lambda r: r[1] == rid, windowed=False)
    frows, fn = ctx.fall_rows(lambda r: r[5] == rid, windowed=False)
    siblings = run_siblings(ctx, rid)
    facts = [
        _fact('Run id', rid),
        _fact('Attribution', ctx.cls_of(rid)),
        _fact('Ledger gate rows', f'{gn:,}'),
        _fact('Ledger fallbacks', f'{fn:,}'),
    ]
    tables = []
    if rec:
        v = rec.get('verdict') or {}
        facts = verdict_facts(rec, facts)
        tables.append(verdict_named_table(v))
        cov = coverage_table(v)
        if cov:
            tables.append(cov)
    elif not siblings:
        facts.append(
            _fact('Debug run', 'not in debug_run_history.jsonl', 'the ledger recorded rows under this id anyway')
        )
    if siblings and (ctx.kind == 'run' or len(siblings) > 1):
        tables.append(siblings_table(siblings, ctx.key))
    tables.append(
        _tbl(
            'Gate rows this run recorded',
            _GATE_COLS,
            grows,
            'This run recorded no gate outcome in the run ledger (Postgres).',
        )
    )
    tables.append(_tbl('Fallbacks this run recorded', _FALL_COLS, frows, 'This run recorded no silent fallback.'))
    title = str(rec.get('name') or rid) if rec else (ctx.names.get(rid) or rid)
    return ctx.out(
        'Run · ' + title,
        rid,
        facts,
        tables,
        [
            'The verdict comes from debug_run_history.jsonl; the gate and fallback rows come from '
            'the run ledger (Postgres).'
        ],
        win='all time — a run is one event, not a window',
    )
