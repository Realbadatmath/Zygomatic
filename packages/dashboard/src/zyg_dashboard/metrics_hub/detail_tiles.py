# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The tile, gate-family and fallback-component halves of the ?detail=<token> view.

One builder per token kind, each taking the `DetailContext` that `detail.quality_detail`
built and returning the payload the Quality tab draws (or the `{'ok': False, 'error': …}`
refusal the original function returned in that branch).
"""

from __future__ import annotations

from .helpers import _iso, _rate, _short
from .quality import (
    _FALL_COLS,
    _GATE_COLS,
    _OUTCOME_TONE,
    _fact,
    _fb_key,
    _fb_name,
    _tbl,
)
from .runs import collect_runs


def _outcome_count(ctx, cls, outcome):
    """How many windowed gate rows of attribution `cls` carry `outcome` (case-insensitive)."""
    return sum(
        1
        for rid, _gate, out, _score, _tag, ts in ctx.gates
        if ctx.in_window(ts) and ctx.cls_of(rid) == cls and (out or '').lower() == outcome
    )


def _tile_attributed(ctx):
    """The pass_rate / attributed tiles: every gate row attributed to a real DebugRun."""
    rows, n = ctx.gate_rows(lambda r: r[6] == 'real')
    passes = _outcome_count(ctx, 'real', 'pass')
    fails = _outcome_count(ctx, 'real', 'fail')
    fam_seen = sorted(
        {
            (g[1] or '').split(':', 1)[0] or '(unnamed)'
            for g in ctx.gates
            if ctx.in_window(g[5]) and ctx.cls_of(g[0]) == 'real'
        }
    )
    return ctx.out(
        'Gate pass rate' if ctx.key == 'pass_rate' else 'Attributed gate outcomes',
        f'Every attributed gate row in the run ledger (Postgres), {ctx.window}.',
        [
            _fact(
                'Pass rate',
                '—' if not (passes + fails) else f'{_rate(passes, passes + fails)} %',
                'pass / (pass + fail)',
            ),
            _fact('Pass', f'{passes:,}'),
            _fact('Fail', f'{fails:,}'),
            _fact('Rows', f'{n:,}', 'includes shadow_fail and other outcomes'),
            _fact('Gate families', len(fam_seen)),
        ],
        [_tbl('Attributed rows, newest first', _GATE_COLS, rows, 'No attributed gate rows in this range.')],
        [
            'Pass rate is computed on attributed rows only — a row whose run id is a real '
            'DebugRun. adhoc and test rows are counted in their own tiles and never pooled here.'
        ],
    )


def _tile_unattributed(ctx):
    """The unattributed tile: record_gate calls made outside a DebugRun."""
    rows, n = ctx.gate_rows(lambda r: r[6] == 'unattributed')
    passes = _outcome_count(ctx, 'unattributed', 'pass')
    fails = _outcome_count(ctx, 'unattributed', 'fail')
    return ctx.out(
        'Unattributed gate rows',
        f'record_gate called outside a DebugRun, {ctx.window}.',
        [
            _fact('Rows', f'{n:,}'),
            _fact('Pass', f'{passes:,}'),
            _fact('Fail', f'{fails:,}'),
            _fact(
                'Pass rate',
                '—' if not (passes + fails) else f'{_rate(passes, passes + fails)} %',
                'not pooled with the attributed rate',
            ),
        ],
        [_tbl('Unattributed rows, newest first', _GATE_COLS, rows, 'No unattributed gate rows in this range.')],
        [
            'These are real gate calls — licence_provenance runs here — but pytest self-tests '
            'that never set a run id land here too, so the two cannot be separated and the '
            'rows are reported on their own.'
        ],
    )


def _test_gate_table(ctx):
    """-> the excluded-gate-row cells, newest first, each naming why it was dropped."""
    rows = [
        (ts, rid, gate, outcome, score, tag)
        for rid, gate, outcome, score, tag, ts in ctx.gates
        if ctx.in_window(ts) and ctx.cls_of(rid) == 'test'
    ]
    rows.sort(key=lambda r: -(r[0] or 0))
    table = [
        [
            _iso(ts) or '—',
            gate or '(unnamed)',
            {'v': outcome or '—', 'tone': _OUTCOME_TONE.get((outcome or '').lower(), 'neutral')},
            {'v': rid or '—', 'muted': True},
            {'v': ctx.test_reason(rid), 'muted': True},
        ]
        for ts, rid, gate, outcome, score, tag in rows
    ]
    return rows, table


def _test_fall_table(ctx):
    """-> the excluded-fallback-row cells, newest first, each naming why it was dropped."""
    return [
        [
            _iso(ts) or '—',
            _fb_name(comp),
            (exp or '?') + ' → ' + (act or '?'),
            {'v': rid or '—', 'muted': True},
            {'v': ctx.test_reason(rid), 'muted': True},
        ]
        for comp, exp, act, det, rid, ts in sorted(
            (f for f in ctx.falls if ctx.in_window(f[5]) and ctx.cls_of(f[4]) == 'test'),
            key=lambda f: -(f[5] or 0),
        )
    ]


def _tile_test_rows(ctx):
    """The test_rows tile: the gate and fallback rows dropped as test traffic, with the rule."""
    rows, table = _test_gate_table(ctx)
    fall_t = _test_fall_table(ctx)
    return ctx.out(
        'Excluded test rows',
        f'Gate and fallback rows dropped as test traffic, {ctx.window}.',
        [_fact('Gate rows', f'{len(rows):,}'), _fact('Fallback rows', f'{len(fall_t):,}')],
        [
            _tbl(
                'Gate rows excluded',
                [
                    {'t': 'Time'},
                    {'t': 'Gate'},
                    {'t': 'Outcome'},
                    {'t': 'Run id'},
                    {'t': 'Why it is a test row'},
                ],
                table,
                'No test gate rows in this range.',
            ),
            _tbl(
                'Fallback rows excluded',
                [
                    {'t': 'Time'},
                    {'t': 'Component'},
                    {'t': 'Expected → actual'},
                    {'t': 'Run id'},
                    {'t': 'Why it is a test row'},
                ],
                fall_t,
                'No test fallback rows in this range.',
            ),
        ],
        [
            'The rule that dropped each row is named in the last column — nothing is excluded '
            'without a reason on the page.'
        ],
    )


def _tile_fallbacks(ctx):
    """The fallbacks tile: every degrade recorded at the site that degraded."""
    rows, n = ctx.fall_rows(lambda r: r[6] != 'test')
    allt = sum(1 for f in ctx.falls if ctx.cls_of(f[4]) != 'test')
    return ctx.out(
        'Silent fallbacks',
        f'Every degrade recorded at the site that degraded, {ctx.window}.',
        [
            _fact('In range', f'{n:,}'),
            _fact('All time', f'{allt:,}'),
            _fact(
                'Unattributed',
                f'{sum(1 for r in ctx.falls if ctx.in_window(r[5]) and ctx.cls_of(r[4]) == "unattributed"):,}',
                'kept — the degrade happened regardless of run id',
            ),
        ],
        [_tbl('Fallback rows, newest first', _FALL_COLS, rows, 'No fallbacks in this range.')],
        [
            'A fallback is silent by definition: the run carried on with the actual value. '
            'Click a component to see only its rows.'
        ],
    )


def _receipt_run_row(r):
    """One row of the receipt_runs tile: the run, how many gates ran, and which did not."""
    rec = r['gate_receipts']
    ran = sum(1 for v in rec.values() if v['ran'])
    return {
        'cells': [
            _iso(r['t']) or '—',
            r['id'][:36],
            r['kind'],
            {'v': r['title'] or '—', 'muted': not r['title']},
            str(ran),
            {'v': str(len(rec) - ran), 'tone': 'warning' if len(rec) - ran else None},
            {'v': ', '.join(sorted(g for g, v in rec.items() if not v['ran'])) or '—', 'muted': True},
        ]
    }


def _tile_receipt_runs(ctx):
    """The receipt_runs tile: the runs whose state file records which gates ran."""
    runs, _meta = collect_runs(ctx.now)
    rows = []
    for r in runs:
        if not r.get('gate_receipts') or not ctx.in_window(r['t']):
            continue
        rows.append(_receipt_run_row(r))
    rows.sort(key=lambda x: x['cells'][0], reverse=True)
    return ctx.out(
        'Runs with gate receipts',
        f'Runs whose state file records which gates ran, {ctx.window}.',
        [_fact('Runs', f'{len(rows):,}')],
        [
            _tbl(
                'Runs filing receipts, newest first',
                [
                    {'t': 'Started'},
                    {'t': 'Run'},
                    {'t': 'Kind'},
                    {'t': 'Title'},
                    {'t': 'Gates ran', 'r': True},
                    {'t': 'Did not run', 'r': True},
                    {'t': 'Which'},
                ],
                rows,
                'No run in this range filed gate receipts.',
            )
        ],
        [
            'A receipt is written by the pipeline, not the ledger: a gate with no receipt was '
            'never asked to run, which is different from running and passing.'
        ],
    )


def tile_section(ctx):
    """tile:<id> — the rows behind one Quality-tab tile, or an unknown-tile refusal."""
    if ctx.key in ('pass_rate', 'attributed'):
        return _tile_attributed(ctx)
    if ctx.key == 'unattributed':
        return _tile_unattributed(ctx)
    if ctx.key == 'test_rows':
        return _tile_test_rows(ctx)
    if ctx.key == 'fallbacks':
        return _tile_fallbacks(ctx)
    if ctx.key == 'receipt_runs':
        return _tile_receipt_runs(ctx)
    return {'ok': False, 'error': f'unknown tile {ctx.key!r}'}


def _family_of(gate):
    """The family part of a gate name — everything before the first ':'."""
    return (gate or '').split(':', 1)[0] or '(unnamed)'


def family_tally(ctx, fam):
    """-> {gate name: counts} over the windowed rows of family `fam`.

    Each entry counts pass / fail / shadow_fail / other for attributed rows, keeps test and
    unattributed rows in their own buckets, and remembers the newest timestamp as `last`.
    """
    per: dict = {}
    for rid, gate, outcome, _score, _tag, ts in ctx.gates:
        if not ctx.in_window(ts) or _family_of(gate) != fam:
            continue
        e = per.setdefault(
            gate or '(unnamed)',
            {'pass': 0, 'fail': 0, 'shadow_fail': 0, 'other': 0, 'unattributed': 0, 'test': 0, 'last': 0},
        )
        e['last'] = max(e['last'], ts or 0)
        c, o = ctx.cls_of(rid), (outcome or '').lower()
        if c == 'test':
            e['test'] += 1
        elif c == 'unattributed':
            e['unattributed'] += 1
        else:
            e[o if o in ('pass', 'fail', 'shadow_fail') else 'other'] += 1
    return per


def family_breakdown(per):
    """-> the 'Gates in this family' cells, busiest (pass+fail) first then alphabetical."""
    return [
        [
            g,
            str(v['pass']),
            str(v['fail']),
            {
                'v': '—' if not (v['pass'] + v['fail']) else f'{_rate(v["pass"], v["pass"] + v["fail"])} %',
                'tone': None,
            },
            str(v['shadow_fail']),
            str(v['unattributed']),
            str(v['test']),
            _iso(v['last']) or '—',
        ]
        for g, v in sorted(per.items(), key=lambda kv: (-(kv[1]['pass'] + kv[1]['fail']), kv[0]))
    ]


def family_section(ctx):
    """family:<gate family> — every row whose gate name starts with that family."""
    fam = ctx.key
    rows, n = ctx.gate_rows(lambda r: _family_of(r[2]) == fam)
    per = family_tally(ctx, fam)
    breakdown = family_breakdown(per)
    p = sum(v['pass'] for v in per.values())
    f_ = sum(v['fail'] for v in per.values())
    if not per:
        return {'ok': False, 'error': f'no gate rows for family {fam!r} in this range'}
    return ctx.out(
        f'Gate family “{fam}”',
        f'Every row whose gate name starts with “{fam}”, {ctx.window}.',
        [
            _fact('Pass rate', '—' if not (p + f_) else f'{_rate(p, p + f_)} %', 'attributed rows only'),
            _fact('Pass', f'{p:,}'),
            _fact('Fail', f'{f_:,}'),
            _fact('Distinct gates', len(per)),
            _fact('Rows', f'{n:,}'),
        ],
        [
            _tbl(
                'Gates in this family',
                [
                    {'t': 'Gate'},
                    {'t': 'Pass', 'r': True},
                    {'t': 'Fail', 'r': True},
                    {'t': 'Pass rate', 'r': True},
                    {'t': 'Shadow fail', 'r': True},
                    {'t': 'Unattributed', 'r': True},
                    {'t': 'Test rows', 'r': True},
                    {'t': 'Last'},
                ],
                breakdown,
                'No gates recorded.',
                limit=None,
            ),
            _tbl('Rows, newest first', _GATE_COLS, rows, 'No rows in this range.'),
        ],
    )


def fallback_detail_tally(rows):
    """-> {detail text (clipped to 200 chars): rows}, skipping the rows that recorded none."""
    details: dict = {}
    for f in rows:
        d = _short(f[3], 200)
        if d:
            details[d] = details.get(d, 0) + 1
    return details


def fallback_section(ctx):
    """fallback:<id> — one (component, expected, actual) triple, in range and all time."""
    match = [
        (comp, exp, act)
        for comp, exp, act, det, rid, ts in ctx.falls
        if _fb_key(_fb_name(comp), exp or '', act or '') == ctx.key
    ]
    if not match:
        return {'ok': False, 'error': 'unknown fallback component'}
    comp0, exp0, act0 = match[0]
    name = _fb_name(comp0)

    def same(r):
        return _fb_key(_fb_name(r[1]), r[2] or '', r[3] or '') == ctx.key

    rows, n = ctx.fall_rows(same, link=False)
    allrows, alln = ctx.fall_rows(same, windowed=False, link=False)
    allt = [f for f in ctx.falls if _fb_key(_fb_name(f[0]), f[1] or '', f[2] or '') == ctx.key]
    firsts = [f[5] for f in allt if f[5]]
    details = fallback_detail_tally(allt)
    return ctx.out(
        f'Fallback · {name}',
        f'{exp0 or "?"} → {act0 or "?"}',
        [
            _fact('In range', f'{n:,}', ctx.window),
            _fact('All time', f'{alln:,}'),
            _fact('Unattributed', f'{sum(1 for f in allt if ctx.cls_of(f[4]) == "unattributed"):,}'),
            _fact('First seen', _iso(min(firsts)) if firsts else '—'),
            _fact('Last seen', _iso(max(firsts)) if firsts else '—'),
            _fact('Full component', comp0 or '(unnamed)'),
        ],
        [
            _tbl(
                'Distinct details recorded at the degrade site',
                [{'t': 'Detail'}, {'t': 'Rows', 'r': True}],
                [[d, str(c)] for d, c in sorted(details.items(), key=lambda kv: -kv[1])],
                'The site recorded no detail with these rows.',
                limit=None,
            ),
            _tbl('Every row, all time', _FALL_COLS, allrows, 'No rows.'),
        ],
        [
            'Test rows are excluded here exactly as they are on the tab; the run column says '
            'whether the row was attributed to a DebugRun.'
        ],
    )
