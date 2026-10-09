# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The Architecture Studio card (2026-09-18)."""

from __future__ import annotations

import glob
import json
import os
from datetime import datetime
from zyg_dashboard import metrics_hub as mh

from .constants import CREWS, RUNTIME, TZ, _zyg_log
from .helpers import _bucket_series, _daykey, _delta, _fc_bucketed, _forecast, _median


# ── Architecture Studio (2026-09-18) ─────────────────────────────────────────
# The studio has no income yet and none is expected, so this card carries production only:
# assistant builds from the conversations ledger, saved drawings, versions, exports and 4K
# hero renders from the studio's own folders, and the subscription tokens the builds cost.
ARCH_DIR = os.path.join(CREWS, 'data', 'architecture')
ARCH_LEDGER = os.path.join(RUNTIME, 'arch_assistant', 'conversations')
ARCH_SOURCES = [
    ('Architecture assistant ledger', os.path.join(ARCH_LEDGER, '*.jsonl')),
    ('Architecture saved drawings', os.path.join(ARCH_DIR, 'projects', '*.json')),
    ('Architecture drawing versions', os.path.join(ARCH_DIR, 'versions', '*')),
    ('Architecture exports (2D/3D proofs)', os.path.join(ARCH_DIR, 'exports', '*')),
    ('Architecture 4K renders', os.path.join(ARCH_DIR, 'renders', '*')),
]
ARCH_TEST_TEXTS = ('route probe', 'ledger probe')
ARCH_CLASSES = (
    ('completed', 'Completed (done, 0 errors)'),
    ('unfinished', 'Unfinished (handed over with open errors / out of turns)'),
    ('failed', 'Failed or killed'),
)


def _arch_ts(s):
    try:
        return datetime.fromisoformat(str(s)).replace(tzinfo=TZ).timestamp()
    except (TypeError, ValueError):
        return None


def _arch_builds():
    """One row per assistant job from the conversations ledger. The LAST non-killed end row
    wins: an out-of-process import of arch_assistant writes a false 'killed' row while a job
    is still running (seen 2026-09-17). The probe rows the test suite writes are excluded and
    counted, never pooled."""
    starts, ends, excluded = {}, {}, 0
    for f in sorted(glob.glob(os.path.join(ARCH_LEDGER, '*.jsonl'))):
        try:
            fh = open(f, encoding='utf-8', errors='replace')
        except OSError as _exc:
            _zyg_log.warning('conversations ledger file unreadable, its jobs are missing from the totals: %s', _exc)
            continue
        with fh:
            for line in fh:
                try:
                    r = json.loads(line)
                except ValueError as _exc:
                    _zyg_log.debug('skipping unparseable conversations ledger line: %s', _exc)
                    continue
                ev, jid = r.get('event'), r.get('id')
                if not jid:
                    continue
                if ev == 'start':
                    starts[jid] = r
                elif ev == 'end':
                    prev = ends.get(jid)
                    if prev is None or prev.get('status') == 'killed' or r.get('status') != 'killed':
                        ends[jid] = r
    rows = []
    for jid, e in ends.items():
        s = starts.get(jid, {})
        text = str(s.get('text') or e.get('text') or '').strip().lower()
        if text in ARCH_TEST_TEXTS or '/nonexistent/claude' in str(e.get('error') or ''):
            excluded += 1
            continue
        ts = _arch_ts(e.get('ts')) or _arch_ts(s.get('ts'))
        if not ts:
            continue
        st = e.get('status')
        if st == 'done':
            cls = 'unfinished' if e.get('incomplete') else 'completed'
        elif st in ('error', 'killed'):
            cls = 'failed'
        else:
            cls = 'other'  # a question parked for the user, etc.
        u = e.get('usage') or {}
        rows.append(
            {
                'id': jid,
                't': ts,
                'cls': cls,
                'status': st,
                'elapsed': mh._num(e.get('elapsed')),
                'draw_calls': mh._num(e.get('draw_calls')),
                'added': int(e.get('added') or 0),
                'model': str(e.get('model') or ''),
                'tok_in': int(u.get('in') or 0) + int(u.get('cache_read') or 0) + int(u.get('cache_write') or 0),
                'tok_out': int(u.get('out') or 0),
                'drawing': str(s.get('drawing') or ''),
            }
        )
    rows.sort(key=lambda r: r['t'])
    return rows, excluded


def _arch_outputs():
    """Files the studio produced, by day of their mtime: saved drawings, version folders,
    exports, and 4K hero renders counted per job (four frames = one render pass)."""

    def by_day(paths):
        m: dict = {}
        for p in paths:
            try:
                dk = _daykey(os.path.getmtime(p))
            except OSError as _exc:
                _zyg_log.debug('skipping studio output with unreadable mtime: %s', _exc)
                continue
            m[dk] = m.get(dk, 0) + 1
        return m

    projects = glob.glob(os.path.join(ARCH_DIR, 'projects', '*.json'))
    versions = [p for p in glob.glob(os.path.join(ARCH_DIR, 'versions', '*')) if os.path.isdir(p)]
    exports = [p for p in glob.glob(os.path.join(ARCH_DIR, 'exports', '*')) if os.path.isfile(p)]
    hero: dict = {}
    for p in glob.glob(os.path.join(ARCH_DIR, 'renders', '*-hero-*')):
        jid = os.path.basename(p).split('-hero-')[0]
        try:
            hero[jid] = min(hero.get(jid, 1e18), os.path.getmtime(p))
        except OSError as _exc:
            _zyg_log.debug('skipping hero render with unreadable mtime: %s', _exc)
    hero_day: dict = {}
    for t in hero.values():
        dk = _daykey(t)
        hero_day[dk] = hero_day.get(dk, 0) + 1
    ext: dict = {}
    for p in exports:
        e = os.path.splitext(p)[1].lower().lstrip('.') or 'other'
        ext[e] = ext.get(e, 0) + 1
    return {
        'projects': by_day(projects),
        'versions': by_day(versions),
        'exports': by_day(exports),
        'hero': hero_day,
        'n_projects': len(projects),
        'n_versions': len(versions),
        'n_exports': len(exports),
        'n_hero': len(hero),
        'export_ext': ext,
    }


def arch_studio_card(now, days, since, keys, weekly, bucket, trend_keys, fkeys, d7, d14, d8, today):
    builds, excluded = _arch_builds()
    outs = _arch_outputs()

    def dmap(rows, val=lambda r: 1.0):
        m: dict = {}
        for r in rows:
            dk = _daykey(r['t'])
            m[dk] = m.get(dk, 0.0) + val(r)
        return m

    def wsum(m, d0, d1):
        return sum(v for k, v in m.items() if d0 <= k <= d1)

    by_cls = {c: [r for r in builds if r['cls'] == c] for c, _ in ARCH_CLASSES}
    win = [r for r in builds if since is None or r['t'] >= since]
    win_cls = {c: [r for r in win if r['cls'] == c] for c, _ in ARCH_CLASSES}
    all_day = dmap(builds)
    tok_day = dmap(builds, lambda r: r['tok_in'])
    out_day = dmap(builds, lambda r: r['tok_out'])
    obj_day = dmap(builds, lambda r: r['added'])
    series = [
        {'id': c, 'label': lbl, 'values': [int(x) for x in _bucket_series(dmap(by_cls[c]), keys, weekly)]}
        for c, lbl in ARCH_CLASSES
    ]
    fc = _forecast([all_day.get(k, 0.0) for k in trend_keys], floor=0.0)
    tok_fc = _forecast([tok_day.get(k, 0.0) / 1e6 for k in trend_keys], floor=0.0)
    forecast = (
        [
            {
                'id': 'trend',
                'label': 'Builds/day trend',
                **_fc_bucketed(fc, fkeys, weekly, 'sum'),
                'slope_per_day': fc['slope_per_day'],
                'r2': fc['r2'],
                'n': fc['n'],
                'level_14d': fc['level_14d'],
            }
        ]
        if fc
        else []
    )

    def rate(rows):
        n_done = sum(1 for r in rows if r['cls'] == 'completed')
        n_all = sum(1 for r in rows if r['cls'] in ('completed', 'unfinished', 'failed'))
        return mh._rate(n_done, n_all)

    def med(rows, key):
        return _median([r[key] for r in rows if r.get(key)])

    last7 = [r for r in builds if _daykey(r['t']) >= d7]
    prev7 = [r for r in builds if d14 <= _daykey(r['t']) <= d8]
    completed_win = win_cls['completed']
    last_model = next((r['model'] for r in reversed(builds) if r['model']), '')
    per_day_rows = []
    for dk in sorted(
        {_daykey(r['t']) for r in builds} | set(outs['projects']) | set(outs['exports']) | set(outs['hero']),
        reverse=True,
    )[:90]:
        rs = [r for r in builds if _daykey(r['t']) == dk]
        per_day_rows.append(
            [
                dk,
                sum(1 for r in rs if r['cls'] == 'completed'),
                sum(1 for r in rs if r['cls'] == 'unfinished'),
                sum(1 for r in rs if r['cls'] == 'failed'),
                {'v': med(rs, 'elapsed'), 'fmt': 'dur'},
                med(rs, 'draw_calls'),
                int(obj_day.get(dk, 0)),
                {'v': round(tok_day.get(dk, 0) / 1e6, 2), 'fmt': 'num'},
                int(out_day.get(dk, 0)),
                outs['projects'].get(dk, 0),
                outs['exports'].get(dk, 0),
                outs['hero'].get(dk, 0),
            ]
        )
    label_win = 'all time' if not days else f'last {days} days'
    return {
        'id': 'arch_studio',
        'lane': 'production',
        'title': 'Architecture Studio',
        'question': 'What does the studio produce — assistant builds, drawings, exports, renders — and what do the builds cost in tokens?',
        'headline': {
            'value': len(completed_win),
            'fmt': 'int',
            'label': 'assistant builds completed clean · ' + label_win,
            'sub': f'{len(win_cls["unfinished"])} unfinished · {len(win_cls["failed"])} failed/killed · clean finish rate '
            + (f'{rate(win):.0f} %' if rate(win) is not None else '—')
            + ' · no income expected (nothing here is monetised)',
        },
        'delta': {
            'pct': _delta(len(last7), len(prev7)),
            'label': 'assistant builds, last 7 d vs the 7 before',
            'good_when': 'up',
        },
        'chart': {
            'kind': 'columns',
            'bucket': bucket,
            'keys': keys,
            'series': series,
            'y': 'int',
            'stacked': True,
            'title': 'Assistant builds per ' + bucket + ' by outcome',
            'forecast': forecast,
            'secondary': {
                'label': 'Subscription tokens processed by the builds (millions)',
                'values': [round(x / 1e6, 2) for x in _bucket_series(tok_day, keys, weekly)],
                'y': 'num',
                'kind': 'columns',
            },
        },
        'facts': {
            'historical': [
                {
                    'label': 'Assistant builds, all time',
                    'value': len(builds),
                    'fmt': 'int',
                    'sub': ' · '.join(f'{len(by_cls[c])} {c}' for c, _ in ARCH_CLASSES)
                    + (f' · {excluded} probe rows excluded' if excluded else ''),
                },
                {
                    'label': 'Objects placed by the assistant',
                    'value': sum(r['added'] for r in builds),
                    'fmt': 'int',
                    'sub': 'records added, all builds',
                },
                {
                    'label': 'Median wall time, completed build',
                    'value': med(by_cls['completed'], 'elapsed'),
                    'fmt': 'dur',
                    'sub': f'p90 {mh._pct([r["elapsed"] for r in by_cls["completed"] if r["elapsed"]], 0.9) or 0:.0f} s · median {med(by_cls["completed"], "draw_calls") or 0:g} drawing calls',
                },
                {
                    'label': 'Saved drawings',
                    'value': outs['n_projects'],
                    'fmt': 'int',
                    'sub': f'{outs["n_versions"]} version folders',
                },
                {
                    'label': 'Exports (2D/3D proofs)',
                    'value': outs['n_exports'],
                    'fmt': 'int',
                    'sub': ', '.join(
                        f'{k} ×{v}' for k, v in sorted(outs['export_ext'].items(), key=lambda kv: -kv[1])[:5]
                    ),
                },
                {
                    'label': '4K hero render passes',
                    'value': outs['n_hero'],
                    'fmt': 'int',
                    'sub': 'one pass = up to four Cycles frames of one build',
                },
                {
                    'label': 'Subscription tokens processed',
                    'value': sum(r['tok_in'] for r in builds),
                    'fmt': 'int',
                    'sub': f'{sum(r["tok_out"] for r in builds):,} output tokens · login quota, not API dollars (Quota tab)',
                },
            ],
            'current': [
                {
                    'label': 'Builds, last 7 days',
                    'value': len(last7),
                    'fmt': 'int',
                    'sub': ' · '.join(f'{sum(1 for r in last7 if r["cls"] == c)} {c}' for c, _ in ARCH_CLASSES),
                },
                {
                    'label': 'Clean finish rate, last 7 days',
                    'value': rate(last7),
                    'fmt': 'pct',
                    'sub': 'completed ÷ (completed + unfinished + failed)',
                },
                {
                    'label': 'Median wall time, last 7 days',
                    'value': med(last7, 'elapsed'),
                    'fmt': 'dur',
                    'sub': f'median {med(last7, "draw_calls") or 0:g} drawing calls · {int(sum(r["added"] for r in last7))} objects',
                },
                {
                    'label': 'Tokens processed, last 7 days',
                    'value': int(wsum(tok_day, d7, today)),
                    'fmt': 'int',
                    'sub': f'{int(wsum(out_day, d7, today)):,} output tokens',
                },
                {
                    'label': 'Drawings saved / exports / renders, last 7 days',
                    'value': f'{wsum(outs["projects"], d7, today):g} / {wsum(outs["exports"], d7, today):g} / {wsum(outs["hero"], d7, today):g}',
                    'fmt': 'text',
                    'sub': 'by file time',
                },
                {
                    'label': 'Model of the last build',
                    'value': last_model or '—',
                    'fmt': 'text',
                    'sub': 'the tab runs Sonnet by rule; headless contest runs may show others',
                },
            ],
            'future': (
                [
                    {
                        'label': 'Builds per day in 30 d (trend)',
                        'value': round(fc['values'][-1], 2),
                        'fmt': 'num',
                        'sub': f'slope {fc["slope_per_day"]:+.3f}/day · r² {fc["r2"]} · {fc["n"]} days',
                    }
                ]
                if fc
                else []
            )
            + (
                [
                    {
                        'label': 'Tokens per day in 30 d (trend)',
                        'value': int(tok_fc['values'][-1] * 1e6),
                        'fmt': 'int',
                        'sub': f'r² {tok_fc["r2"]}',
                    }
                ]
                if tok_fc
                else []
            )
            + [
                {
                    'label': 'Income',
                    'value': 'none expected',
                    'fmt': 'text',
                    'sub': 'the studio is not monetised; this card has no revenue line by design',
                }
            ],
        },
        'table': {
            'cols': [
                'Day',
                'Completed',
                'Unfinished',
                'Failed/killed',
                'Median wall',
                'Median draw calls',
                'Objects placed',
                'Tokens (M)',
                'Output tokens',
                'Drawings saved',
                'Exports',
                'Render passes',
            ],
            'rows': per_day_rows,
        },
        'notes': [
            "Builds are the assistant's conversations ledger (data/runtime/arch_assistant/conversations): one row per job, the last non-killed end row wins. "
            'Completed = done accepted with 0 design errors; unfinished = handed over with open errors or out of turns; failed/killed = error, server restart, or an out-of-process import that closed the job.',
            f'Test-suite probe rows are excluded and counted ({excluded}). Headless contest runs (2026-09-17, six planner→worker pairs) are real builds and are included.',
            'Tokens are the Claude login subscription (input + cache reads + cache writes), not API dollars; the Quota tab holds the meter. Drawings, versions, exports and renders are counted by file time in data/architecture.',
            'No income is expected from the studio, so this card carries no revenue, views or RPM figures.',
        ],
    }
