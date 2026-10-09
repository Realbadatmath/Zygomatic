#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""
vace_seed_pool.py — pool the VACE plate receipts across seeds, because n=1 decided nothing.

WHY THIS EXISTS. Receipt A (output/vace_receipts/2026-09-03_c3345deb5bde_registry)
measured four arms at ONE seed and returned a FAIL verdict on the edge rows. Then the
static-skeleton delta changed sign between two runs (S01 receipt sections 2 and 4). A
number that flips sign when only the seed moves is render noise being read as an effect,
and no amount of tuning on top of it means anything. So: the same four arms at five
seeds, pooled, with the sign counts printed next to every mean — a mean of five that
hides a 3-2 split is exactly the failure this is here to prevent.

    "…/.venv/bin/python" scripts/vace_seed_pool.py            # the five receipt A seeds
    …                    scripts/vace_seed_pool.py --receipt DIR --receipt DIR --out DIR

FOUR-STATE LEDGER, per measurement, never a silent zero:
    found          — the receipt recorded a number
    not_found      — the receipt exists but this arm was never rendered
    not_detectable — the arm ran and the metric does not exist for it (e.g. edge_corr
                     at frame 80 of a 41-frame clip: carried through from the receipt)
    unmeasurable   — the ledger.json is missing or unreadable

WHAT IT WILL NOT DO. It does not re-score any clip, does not re-render, and does not
weigh arms. It reads ledger.json and nothing else.
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time

_HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

FOUND, NOT_FOUND, NOT_DETECTABLE, UNMEASURABLE = ('found', 'not_found', 'not_detectable', 'unmeasurable')

ARMS = ['neutral', 'correct', 'wrong_supplied', 'skel_on']
BASE = os.path.join('output', 'vace_receipts')
DEFAULT_RECEIPTS = [
    os.path.join(BASE, '2026-09-03_c3345deb5bde_registry'),
    os.path.join(BASE, '2026-09-03_c3345deb5bde_registry_seed11'),
    os.path.join(BASE, '2026-09-03_c3345deb5bde_registry_seed23'),
    os.path.join(BASE, '2026-09-03_c3345deb5bde_registry_seed42'),
    os.path.join(BASE, '2026-09-03_c3345deb5bde_registry_seed101'),
]
DEFAULT_OUT = os.path.join(BASE, '2026-09-03_c3345deb5bde_registry_seedpool')

# The three per-arm numbers the gate is written in, and where they live in a ledger.
METRICS = [
    ('identity_cosine', 'identity cosine (mean over sampled frames)'),
    ('identity_min', 'identity cosine, worst sampled frame'),
    ('edge_last', 'edge_corr, last frame vs frame 0'),
    ('path_px_median', 'track:subject path length, px (median)'),
]


# ---------------------------------------------------------------- reading


def read_receipt(d: str) -> dict:
    """One receipt dir -> {seed, path, state, arms: {arm: {metric: (state, value)}}}."""
    p = os.path.join(d, 'ledger.json')
    out = {'dir': d, 'ledger': p, 'seed': None, 'state': UNMEASURABLE, 'reason': '', 'arms': {}}
    try:
        with open(p, encoding='utf-8') as fh:
            L = json.load(fh)
    except Exception as e:
        out['reason'] = f'{type(e).__name__}: {e}'
        return out
    out['seed'] = L.get('seed')
    out['state'] = FOUND
    out['date'] = L.get('date')
    out['identity_bank_sha256'] = (L.get('identity_bank') or {}).get('sha256')
    arms = L.get('arms') or {}
    for a in ARMS:
        v = arms.get(a)
        if not isinstance(v, dict):
            out['arms'][a] = {k: (NOT_FOUND, None) for k, _ in METRICS}
            continue
        m = {}
        ident = v.get('identity') or {}
        ist = ident.get('state') or NOT_DETECTABLE
        m['identity_cosine'] = (
            (FOUND, float(ident['cosine']))
            if ist == FOUND and ident.get('cosine') is not None
            else (ist if ist != FOUND else NOT_DETECTABLE, None)
        )
        m['identity_min'] = (
            (FOUND, float(ident['cosine_min']))
            if ist == FOUND and ident.get('cosine_min') is not None
            else (ist if ist != FOUND else NOT_DETECTABLE, None)
        )
        # edge_corr states come from the receipt itself and are carried, not re-judged:
        # frame_80/frame_200 really are not_detectable on a 41-frame clip.
        ec = ((v.get('edge_corr') or {}).get('frame_last')) or {}
        est = ec.get('state') or NOT_DETECTABLE
        m['edge_last'] = (
            (FOUND, float(ec['value']))
            if est == FOUND and ec.get('value') is not None
            else (est if est != FOUND else NOT_DETECTABLE, None)
        )
        m['identity_reason'] = (ist, ident.get('reason') or ((ident.get('raw') or {}).get('reason')))
        m['identity_frame_ledger'] = (ist, (ident.get('raw') or {}).get('ledger'))
        pl = (NOT_DETECTABLE, None)
        for c in (v.get('motion') or {}).get('checks') or []:
            if c.get('check') == 'track:subject' and c.get('path_px_median') is not None:
                pl = (FOUND, float(c['path_px_median']))
        m['path_px_median'] = pl
        out['arms'][a] = m
    return out


# ---------------------------------------------------------------- statistics


def describe(vals: list[float]) -> dict:
    if not vals:
        return {'n': 0, 'mean': None, 'sd': None, 'min': None, 'max': None}
    return {
        'n': len(vals),
        'mean': round(statistics.fmean(vals), 4),
        'sd': round(statistics.stdev(vals), 4) if len(vals) > 1 else None,
        'min': round(min(vals), 4),
        'max': round(max(vals), 4),
    }


def paired(receipts: list[dict], arm_a: str, arm_b: str, metric: str) -> dict:
    """arm_a minus arm_b, per seed, only where BOTH are found. Sign count is the point."""
    per, skipped = [], []
    for r in receipts:
        sa, va = r['arms'].get(arm_a, {}).get(metric, (UNMEASURABLE, None))
        sb, vb = r['arms'].get(arm_b, {}).get(metric, (UNMEASURABLE, None))
        if sa == FOUND and sb == FOUND:
            per.append({'seed': r['seed'], 'a': round(va, 4), 'b': round(vb, 4), 'delta': round(va - vb, 4)})
        else:
            skipped.append({'seed': r['seed'], arm_a: sa, arm_b: sb})
    d = [x['delta'] for x in per]
    out = {
        'comparison': f'{arm_a} - {arm_b}',
        'metric': metric,
        'n_pairs': len(d),
        'per_seed': per,
        'skipped': skipped,
        'positive': sum(1 for x in d if x > 0),
        'negative': sum(1 for x in d if x < 0),
        'zero': sum(1 for x in d if x == 0),
        'mean_delta': round(statistics.fmean(d), 4) if d else None,
        'sd_delta': round(statistics.stdev(d), 4) if len(d) > 1 else None,
    }
    out['sign_count'] = f'{out["positive"]}/{len(d)} seeds positive'
    out['tests'] = _tests(d)
    return out


def _tests(d: list[float]) -> dict:
    """Paired t-test and Wilcoxon, with the honest note about what n=5 can reach."""
    t = {'n': len(d)}
    if len(d) < 2 or all(x == 0 for x in d):
        t['note'] = 'too few pairs, or all deltas zero: no test'
        return t
    try:
        from scipy import stats
    except Exception as e:  # pragma: no cover
        t['note'] = f'scipy unavailable ({e}); sign count only'
        return t
    r = stats.ttest_rel(d, [0.0] * len(d))
    t['ttest_rel'] = {'t': round(float(r.statistic), 4), 'p': round(float(r.pvalue), 4)}
    try:
        w = stats.wilcoxon(d)
        t['wilcoxon'] = {'W': round(float(w.statistic), 4), 'p': round(float(w.pvalue), 4)}
    except Exception as e:
        t['wilcoxon'] = {'error': str(e)}
    if len(d) <= 5:
        t['power_note'] = (
            'n=%d: the smallest two-sided Wilcoxon p reachable is %.4f, so this test '
            'CANNOT return p<0.05 however clean the effect. Read the sign count.' % (len(d), 2.0 / (2 ** len(d)))
        )
    return t


def spearman(xs: list[float], ys: list[float]) -> dict:
    if len(xs) < 3:
        return {'n': len(xs), 'rho': None, 'p': None, 'note': 'fewer than 3 pairs: not computed'}
    try:
        from scipy import stats

        r = stats.spearmanr(xs, ys)
        return {'n': len(xs), 'rho': round(float(r.statistic), 4), 'p': round(float(r.pvalue), 4)}
    except Exception as e:  # pragma: no cover
        return {'n': len(xs), 'rho': None, 'p': None, 'note': f'scipy: {e}'}


# ---------------------------------------------------------------- the pool


def build(receipt_dirs: list[str], out_dir: str) -> dict:
    receipts = [read_receipt(d) for d in receipt_dirs]
    ok = [r for r in receipts if r['state'] == FOUND]

    per_arm = {}
    for a in ARMS:
        per_arm[a] = {}
        for metric, _label in METRICS:
            vals, states = [], {}
            for r in ok:
                s, v = r['arms'].get(a, {}).get(metric, (UNMEASURABLE, None))
                states[str(r['seed'])] = s
                if s == FOUND:
                    vals.append(v)
            st = describe(vals)
            st['states'] = states
            st['per_seed'] = {str(r['seed']): (r['arms'].get(a, {}).get(metric, (UNMEASURABLE, None))[1]) for r in ok}
            per_arm[a][metric] = st

    # WHERE IDENTITY WENT MISSING. check_clip returns a mean over the frames it could
    # measure, so a per-arm identity mean quietly becomes conditional on the face being
    # detectable at all — and if detection fails more often in one arm than another, the
    # comparison between them is a selection effect, not an identity effect. It is
    # counted here per arm, next to the mean it qualifies.
    detect = {}
    for a in ARMS:
        rows, lost = [], 0
        for r in ok:
            st, _ = r['arms'].get(a, {}).get('identity_cosine', (UNMEASURABLE, None))
            _, why = r['arms'].get(a, {}).get('identity_reason', (None, None))
            _, fl = r['arms'].get(a, {}).get('identity_frame_ledger', (None, None))
            rows.append({'seed': r['seed'], 'state': st, 'reason': why, 'frame_ledger': fl})
            if st != FOUND:
                lost += 1
        detect[a] = {'n_seeds': len(ok), 'measured': len(ok) - lost, 'lost': lost, 'per_seed': rows}
    n_lost = sum(v['lost'] for v in detect.values())
    n_arms = sum(v['n_seeds'] for v in detect.values())
    detect_note = (
        '%d of %d arms have NO identity number: check_clip found no measurable face in '
        'any sampled frame. Every identity mean above is therefore conditional on '
        'detection, and every identity gate row is evaluated on the seeds that survived '
        'it — %s. Losses per arm: %s.'
        % (
            n_lost,
            n_arms,
            'which is not the same set for every arm' if n_lost else 'all of them',
            ', '.join('%s %d/%d' % (a, detect[a]['lost'], detect[a]['n_seeds']) for a in ARMS),
        )
    )

    # The S01 claim under test: does the static skeleton help identity, and does its
    # sign survive a change of seed? (Receipt A said one thing; the S01 re-run said the
    # opposite. One of those was noise.)
    skel = paired(ok, 'skel_on', 'neutral', 'identity_cosine')
    margins = {
        'correct_vs_neutral_identity': paired(ok, 'correct', 'neutral', 'identity_cosine'),
        'correct_vs_wrong_identity': paired(ok, 'correct', 'wrong_supplied', 'identity_cosine'),
        'correct_vs_neutral_edge_last': paired(ok, 'correct', 'neutral', 'edge_last'),
        'correct_vs_wrong_edge_last': paired(ok, 'correct', 'wrong_supplied', 'edge_last'),
    }

    # S01's motion proxy, re-tested at n=20 instead of n=4: does the last-frame edge
    # correlation track how far the subject actually moved?
    xs, ys, pts, motion_states = [], [], [], []
    for r in ok:
        for a in ARMS:
            se, ve = r['arms'].get(a, {}).get('edge_last', (UNMEASURABLE, None))
            sp, vp = r['arms'].get(a, {}).get('path_px_median', (UNMEASURABLE, None))
            if se == FOUND and sp == FOUND:
                xs.append(vp)
                ys.append(ve)
                pts.append({'seed': r['seed'], 'arm': a, 'path_px': vp, 'edge_last': ve})
            else:
                motion_states.append({'seed': r['seed'], 'arm': a, 'edge_last': se, 'path_px_median': sp})
    sp_res = spearman(xs, ys)
    sp_res['points'] = pts
    sp_res['excluded'] = motion_states

    # The gate rows exactly as S01 wrote them, twice: on the pooled means, and as a
    # count of seeds. A row that passes on the mean but only 3/5 seeds is not a pass.
    gate = []
    for label, hi, lo, metric in [
        ('identity: correct > neutral', 'correct', 'neutral', 'identity_cosine'),
        ('identity: correct > wrong_supplied', 'correct', 'wrong_supplied', 'identity_cosine'),
        ('edge_corr(last): correct > neutral', 'correct', 'neutral', 'edge_last'),
        ('edge_corr(last): correct > wrong_supplied', 'correct', 'wrong_supplied', 'edge_last'),
    ]:
        mh, ml = per_arm[hi][metric]['mean'], per_arm[lo][metric]['mean']
        pr = paired(ok, hi, lo, metric)
        if mh is None or ml is None:
            row = {'check': label, 'state': NOT_DETECTABLE, 'ok': None, 'note': 'a pooled mean is missing'}
        else:
            row = {
                'check': label,
                'state': FOUND,
                'pooled_mean_hi': mh,
                'pooled_mean_lo': ml,
                'ok_on_pooled_mean': bool(mh > ml),
                'seeds_positive': pr['positive'],
                'n_pairs': pr['n_pairs'],
                'ok': bool(mh > ml and pr['positive'] == pr['n_pairs']),
                'note': (
                    'unanimous'
                    if pr['positive'] == pr['n_pairs']
                    else 'unanimous against'
                    if pr['positive'] == 0
                    else 'SPLIT ACROSS SEEDS — the mean is not the finding'
                ),
            }
        gate.append(row)
    passed = [g for g in gate if g.get('ok')]
    verdict = (
        'PASS — every gate row holds on the pooled mean AND on every seed'
        if len(passed) == len(gate)
        else 'FAIL — %d/%d gate rows hold on the pooled mean and unanimously across '
        'seeds. Report it; do not tune against it.' % (len(passed), len(gate))
    )

    pool = {
        'schema': 'zyg.vace_seed_pool/1',
        'built': time.strftime('%Y-%m-%dT%H:%M:%S'),
        'receipts': [
            {
                'dir': r['dir'],
                'seed': r['seed'],
                'state': r['state'],
                'reason': r.get('reason', ''),
                'date': r.get('date'),
                'identity_bank_sha256': r.get('identity_bank_sha256'),
            }
            for r in receipts
        ],
        'seeds': [r['seed'] for r in ok],
        'seeds_unmeasurable': [{'dir': r['dir'], 'reason': r['reason']} for r in receipts if r['state'] != FOUND],
        'arms': ARMS,
        'per_arm': per_arm,
        'identity_detectability': {'per_arm': detect, 'note': detect_note},
        'static_skeleton_delta': skel,
        'margins': margins,
        'edge_vs_path_spearman': sp_res,
        'gate': {'rows': gate, 'verdict': verdict},
        'note': (
            'Pooled from the receipts listed above; nothing was re-scored or '
            're-rendered here. Identity is check_clip per-frame cosine against the '
            "character's bank; edge_corr(last) is frame 40 vs frame 0 under the "
            'receipt mask; path_px_median is the motion track:subject check.'
        ),
    }
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, 'pool.json'), 'w', encoding='utf-8') as fh:
        json.dump(pool, fh, indent=1)
    with open(os.path.join(out_dir, 'POOL.md'), 'w', encoding='utf-8') as fh:
        fh.write(render_md(pool))
    return pool


# ---------------------------------------------------------------- the report


def _f(v, nd=4):
    return '—' if v is None else ('%.*f' % (nd, v))


def render_md(P: dict) -> str:
    L = []
    A = L.append
    A('# VACE receipt A, pooled over seeds\n')
    A('Built %s · arms %s\n' % (P['built'], ', '.join(P['arms'])))
    A('\n## Seeds\n')
    A('| seed | receipt | state | identity_bank sha256 |')
    A('|---|---|---|---|')
    for r in P['receipts']:
        A(
            '| %s | %s | %s | %s |'
            % (r['seed'], os.path.basename(r['dir']), r['state'], (r.get('identity_bank_sha256') or '—')[:12])
        )
    if P['seeds_unmeasurable']:
        A(
            '\n**unmeasurable seeds:** '
            + '; '.join('%s (%s)' % (os.path.basename(u['dir']), u['reason']) for u in P['seeds_unmeasurable'])
        )

    A('\n## Per arm, over seeds\n')
    for metric, label in METRICS:
        A('\n**%s**\n' % label)
        A('| arm | n | mean | sd | min | max | per seed |')
        A('|---|---|---|---|---|---|---|')
        for a in P['arms']:
            s = P['per_arm'][a][metric]
            per = ', '.join(
                '%s:%s' % (k, _f(v, 3)) for k, v in sorted(s['per_seed'].items(), key=lambda kv: int(kv[0]))
            )
            A(
                '| %s | %d | %s | %s | %s | %s | %s |'
                % (a, s['n'], _f(s['mean']), _f(s['sd']), _f(s['min']), _f(s['max']), per)
            )
        bad = {a: {k: v for k, v in P['per_arm'][a][metric]['states'].items() if v != FOUND} for a in P['arms']}
        bad = {a: v for a, v in bad.items() if v}
        if bad:
            A('\nnot found: `%s`' % json.dumps(bad))

    A('\n## Identity detectability (what the identity means are conditional on)\n')
    d = P['identity_detectability']
    A('| arm | seeds measured | seeds lost | detail |')
    A('|---|---|---|---|')
    for a in P['arms']:
        v = d['per_arm'][a]
        det = (
            '; '.join(
                '%s: %s%s' % (x['seed'], x['state'], ' (%s)' % x['reason'] if x['reason'] else '')
                for x in v['per_seed']
                if x['state'] != FOUND
            )
            or 'all measured'
        )
        A('| %s | %d/%d | %d | %s |' % (a, v['measured'], v['n_seeds'], v['lost'], det))
    A('\n%s\n' % d['note'])

    A('\n## The static-skeleton delta (the sign that flipped)\n')
    s = P['static_skeleton_delta']
    A('`skel_on - neutral` on identity cosine, paired per seed.\n')
    A('| seed | skel_on | neutral | delta |')
    A('|---|---|---|---|')
    for x in s['per_seed']:
        A('| %s | %s | %s | %s |' % (x['seed'], _f(x['a']), _f(x['b']), _f(x['delta'])))
    A(
        '\n- mean delta **%s** (sd %s), **%s**, %d negative'
        % (_f(s['mean_delta']), _f(s['sd_delta']), s['sign_count'], s['negative'])
    )
    t = s['tests']
    if 'ttest_rel' in t:
        A('- paired t-test: t=%s, p=%s' % (_f(t['ttest_rel']['t']), _f(t['ttest_rel']['p'])))
    if 'wilcoxon' in t and 'p' in t['wilcoxon']:
        A('- Wilcoxon: W=%s, p=%s' % (_f(t['wilcoxon']['W']), _f(t['wilcoxon']['p'])))
    for k in ('power_note', 'note'):
        if t.get(k):
            A('- %s' % t[k])

    A('\n## Margins\n')
    A('| comparison | metric | n | mean delta | sd | seeds positive | t-test p | Wilcoxon p |')
    A('|---|---|---|---|---|---|---|---|')
    for _key, m in P['margins'].items():
        tt = m['tests'].get('ttest_rel', {})
        ww = m['tests'].get('wilcoxon', {})
        A(
            '| %s | %s | %d | %s | %s | %s | %s | %s |'
            % (
                m['comparison'],
                m['metric'],
                m['n_pairs'],
                _f(m['mean_delta']),
                _f(m['sd_delta']),
                m['sign_count'],
                _f(tt.get('p')),
                _f(ww.get('p')),
            )
        )

    A('\n## Gate (S01 rows, on the pooled means AND per seed)\n')
    A('| check | pooled hi | pooled lo | ok on mean | seeds positive | ok | note |')
    A('|---|---|---|---|---|---|---|')
    for g in P['gate']['rows']:
        A(
            '| %s | %s | %s | %s | %s/%s | %s | %s |'
            % (
                g['check'],
                _f(g.get('pooled_mean_hi')),
                _f(g.get('pooled_mean_lo')),
                g.get('ok_on_pooled_mean'),
                g.get('seeds_positive'),
                g.get('n_pairs'),
                g.get('ok'),
                g.get('note', ''),
            )
        )
    A('\n**VERDICT: %s**\n' % P['gate']['verdict'])

    A('\n## Motion proxy: edge_corr(last) vs track path length\n')
    sp = P['edge_vs_path_spearman']
    A(
        'Pooled over every arm of every seed (n=%d): Spearman rho **%s**, p %s.%s\n'
        % (sp['n'], _f(sp.get('rho')), _f(sp.get('p')), (' ' + sp['note']) if sp.get('note') else '')
    )
    A('| seed | arm | path_px_median | edge_last |')
    A('|---|---|---|---|')
    for pt in sp['points']:
        A('| %s | %s | %s | %s |' % (pt['seed'], pt['arm'], _f(pt['path_px'], 2), _f(pt['edge_last'])))
    if sp['excluded']:
        A('\nexcluded (not both found): `%s`' % json.dumps(sp['excluded']))
    A('\n---\n%s\n' % P['note'])
    return '\n'.join(L) + '\n'


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[1])
    ap.add_argument(
        '--receipt', action='append', default=None, help='a receipt dir containing ledger.json (repeatable)'
    )
    ap.add_argument('--out', default=None)
    a = ap.parse_args(argv)
    os.chdir(_HERE)
    dirs = a.receipt or DEFAULT_RECEIPTS
    P = build(dirs, a.out or DEFAULT_OUT)
    print(render_md(P))
    print('written: %s' % os.path.join(a.out or DEFAULT_OUT, 'POOL.md'))
    return 0


if __name__ == '__main__':
    sys.exit(main())
