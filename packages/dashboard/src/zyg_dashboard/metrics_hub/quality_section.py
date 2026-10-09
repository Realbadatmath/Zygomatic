# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Metrics > Quality — the gates / fallbacks / receipts payload."""

from __future__ import annotations

import os
import time

from .helpers import _iso, _rate, _req_arg
from .runs import _bucket_of, _bucketing, _window, collect_runs
from .quality import _dbg_key, _fb_key, _ledger_rows, _run_class, _test_run_ids
from .detail import quality_detail


def section_quality(days=30, now=None):
    now = now or time.time()
    # `?detail=<token>` rides this endpoint (as `?inspect=` does on capabilities): every
    # number and verdict the tab draws ships the token for the rows behind it.
    want = _req_arg('detail')
    if want:
        return {'mode': 'detail', 'detail': quality_detail(want, days=days, now=now)}
    since = _window(days, now)
    test_ids, test_pids, real_debug = _test_run_ids()
    gates, falls = _ledger_rows()

    # Three populations, never pooled: attributed production runs (pass rate is computed on
    # these only), unattributed "adhoc" rows (record_gate called outside a DebugRun — real
    # gates like licence_provenance, but pytest selftests land here too), and test rows.
    fams: dict = {}
    excluded_test = 0
    gate_days: list = []
    for rid, gate, outcome, _score, _tag, ts in gates:
        if since is not None and (ts or 0) < since:
            continue
        cls = _run_class(rid, test_ids, test_pids)
        fam = (gate or '').split(':', 1)[0] or '(unnamed)'
        f = fams.setdefault(
            fam,
            {
                'pass': 0,
                'fail': 0,
                'shadow_fail': 0,
                'other': 0,
                'runs': set(),
                'last': 0,
                'u_pass': 0,
                'u_fail': 0,
                'u_other': 0,
                'test': 0,
            },
        )
        f['last'] = max(f['last'], ts or 0)
        o = (outcome or '').lower()
        if cls == 'test':
            f['test'] += 1
            excluded_test += 1
        elif cls == 'unattributed':
            f['u_' + (o if o in ('pass', 'fail') else 'other')] += 1
        else:
            f[o if o in ('pass', 'fail', 'shadow_fail') else 'other'] += 1
            f['runs'].add(rid)
            gate_days.append((ts, o))

    earliest = min([g[5] for g in gates if g[5]] + [f[5] for f in falls if f[5]], default=None)
    keys, weekly = _bucketing(since, now, earliest)
    idx = {k: i for i, k in enumerate(keys)}
    gp, gf = [0] * len(keys), [0] * len(keys)
    for ts, o in gate_days:
        i = idx.get(_bucket_of(ts, weekly)) if ts else None
        if i is None:
            continue
        if o == 'pass':
            gp[i] += 1
        elif o == 'fail':
            gf[i] += 1

    comps: dict = {}
    fall_excluded_test = 0
    fall_days = [0] * len(keys)
    for comp, exp, act, _detail, rid, ts in falls:
        cls = _run_class(rid, test_ids, test_pids)
        if cls == 'test':
            fall_excluded_test += 1
            continue
        name = comp or '(unnamed)'
        if name.startswith('lora:'):
            name = 'lora:' + os.path.basename(name[5:])
        c = comps.setdefault((name, exp or '', act or ''), {'window': 0, 'all': 0, 'last': 0, 'unattributed': 0})
        c['all'] += 1
        c['last'] = max(c['last'], ts or 0)
        if since is None or (ts or 0) >= since:
            c['window'] += 1
            c['unattributed'] += 1 if cls == 'unattributed' else 0
            i = idx.get(_bucket_of(ts, weekly)) if ts else None
            if i is not None:
                fall_days[i] += 1

    runs, _meta = collect_runs(now)
    receipts: dict = {}
    vlm: dict = {}
    receipt_runs = 0
    for r in runs:
        if since is not None and r['t'] < since:
            continue
        if r.get('gate_receipts'):
            receipt_runs += 1
            for g, v in r['gate_receipts'].items():
                e = receipts.setdefault(g, {'ran': 0, 'not_ran': 0, 'reasons': {}})
                if v['ran']:
                    e['ran'] += 1
                else:
                    e['not_ran'] += 1
                    e['reasons'][v['reason'] or '(no reason)'] = e['reasons'].get(v['reason'] or '(no reason)', 0) + 1
        for k, v in (r.get('vlm') or {}).items():
            vlm[k] = vlm.get(k, 0) + v

    fam_rows = []
    for fam, f in fams.items():
        decided = f['pass'] + f['fail']
        fam_rows.append(
            {
                'family': fam,
                'detail': 'family:' + fam,
                'pass': f['pass'],
                'fail': f['fail'],
                'shadow_fail': f['shadow_fail'],
                'other': f['other'],
                'pass_rate': _rate(f['pass'], decided),
                'runs': len(f['runs']),
                'unattributed_pass': f['u_pass'],
                'unattributed_fail': f['u_fail'],
                'unattributed_other': f['u_other'],
                'unattributed_pass_rate': _rate(f['u_pass'], f['u_pass'] + f['u_fail']),
                'test_rows': f['test'],
                'last': _iso(f['last']),
            }
        )
    fam_rows.sort(
        key=lambda x: (-(x['pass'] + x['fail'] + x['unattributed_pass'] + x['unattributed_fail']), x['family'])
    )
    total_pass = sum(f['pass'] for f in fam_rows)
    total_fail = sum(f['fail'] for f in fam_rows)
    real_recent = sorted(real_debug, key=lambda r: str(r.get('ts') or ''), reverse=True)
    return {
        'gates': {
            'families': fam_rows,
            'pass': total_pass,
            'fail': total_fail,
            'pass_rate': _rate(total_pass, total_pass + total_fail),
            'unattributed_pass': sum(f['unattributed_pass'] for f in fam_rows),
            'unattributed_fail': sum(f['unattributed_fail'] for f in fam_rows),
            'excluded_test': excluded_test,
            'daily': {'bucket': 'week' if weekly else 'day', 'keys': keys, 'pass': gp, 'fail': gf},
        },
        'fallbacks': {
            'components': [
                {
                    'component': k[0],
                    'expected': k[1],
                    'actual': k[2],
                    'count': v['window'],
                    'count_all_time': v['all'],
                    'unattributed': v['unattributed'],
                    'last': _iso(v['last']),
                    'detail': 'fallback:' + _fb_key(k[0], k[1], k[2]),
                }
                for k, v in sorted(comps.items(), key=lambda kv: (-kv[1]['window'], -kv[1]['last']))
            ],
            'total': sum(v['window'] for v in comps.values()),
            'total_all_time': sum(v['all'] for v in comps.values()),
            'excluded_test': fall_excluded_test,
            'daily': fall_days,
        },
        'receipts': {
            'runs': receipt_runs,
            'gates': [{'gate': g, 'detail': 'receipt:' + g, **v} for g, v in sorted(receipts.items())],
        },
        'vlm_gate_stats': vlm,
        'debug_runs': [
            {
                'name': r.get('name'),
                'run_id': r.get('run_id'),
                'ts': r.get('ts'),
                'detail': 'debug:' + _dbg_key(r),
                'degradations': r.get('degradations'),
                'ok': (r.get('verdict') or {}).get('ok'),
                'blocked': (r.get('verdict') or {}).get('blocked'),
                'failed_checks': (r.get('verdict') or {}).get('failed_checks'),
                'blocking': (r.get('verdict') or {}).get('blocking_failures') or [],
                'warnings': (r.get('verdict') or {}).get('warning_failures') or [],
            }
            for r in real_recent[:15]
        ],
        'notes': [
            'Gate outcomes come from the run ledger (Postgres). Test rows are excluded: pytest runs (debug_run_history '
            'dirs under /tmp), run ids sharing a pytest process id, numeric / self-test / calibration ids.',
            'Pass rate is computed on attributed runs only. Unattributed "adhoc" rows (record_gate outside a '
            'DebugRun) are shown in their own columns: they include real gates such as licence_provenance, '
            'but pytest self-tests that do not set a run id land there too, so they are not pooled.',
            'Fallbacks are silent degrades recorded at the site that degraded; unattributed rows are kept '
            '(the degrade happened regardless of run id), test rows are excluded.',
        ],
    }
