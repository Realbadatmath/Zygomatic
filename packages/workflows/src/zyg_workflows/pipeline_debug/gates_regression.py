# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""qc_regression_vs — same regions, new clip against a named baseline, signed
deltas: "what did I break since <baseline>"."""

import os
import time
from .gates_beats import _REGRESSION_WORSE_WHEN
from .gates_charbal_detect import (
    _CHARBAL_DIR_STEP,
    _CHARBAL_FLOW_STEP,
    _REGRESSION_FLOOR,
    _REGRESSION_TOLERANCE,
    _perpix_stats,
    _valid_box,
)
from .gates_motion import _MOTION_COHERENCE_FLOOR, _motion_vector_stats, _region_flow_vectors
from .gates_v7 import _record_qc


def qc_regression_vs(
    clip_path,
    baseline_path,
    regions,
    tolerance=None,
    worse_when=None,
    metrics=None,
    step_flow=None,
    step_dir=None,
    baseline_name=None,
    tag=None,
    log_fn=None,
    fail_open=True,
):
    """Same regions, new clip vs a named baseline, every metric that moved — SIGNED.

    The one-command "what did I break". Born 2026-08-01 out of v12: a global graded pin was
    added, every per-region gate still passed, and the thing it actually did — collapse
    Cornelis's face gestures by 63% while lifting the candle flicker the operator wanted —
    was only visible by putting two runs side by side.

    regions: {name: (fx0,fy0,fx1,fy1)} measured IDENTICALLY on both clips. When the two
    renders moved the composition, use boxes that contain the subject in BOTH or the diff
    measures your box, not your change.

    metrics: default ('flow_median','flow_mean','reversals_per_s','net_path'). Flow metrics
    come from a sample_every=step_flow pass, direction metrics from step_dir=2 (their
    calibration). tolerance: relative move that counts, default 0.15.

    worse_when: {metric: 'down'|'up'} — which DIRECTION is a regression. Default: flow and
    coherence dropping, reversals rising. Only regressions set ok=False; improvements are
    reported with the same detail and do not fail, because a diff that fails on every change
    is a diff nobody runs.

    Direction metrics are skipped for a region that is below the coherence floor on either
    clip — reversals on a still region are a noise reading and qc_motion_quality does not
    gate them either.

    Guards the v12 filing incident directly: identical realpaths are refused, and two files
    with the SAME BASENAME from different directories raise a provenance check, because that
    is exactly how FINAL_scene20_v11.mp4 came to exist twice and get compared against itself.

    Returns {'ok', 'regions': {...}, 'moved': [...] sorted by |rel|, 'checks': [...]}."""
    log = log_fn or (lambda _m: None)
    base_id = baseline_name or os.path.basename(os.path.dirname(baseline_path) or '') or os.path.basename(baseline_path)
    out = {
        'tag': tag or f'regression:{os.path.basename(clip_path)}_vs_{base_id}',
        'kind': 'regression',
        'path': clip_path,
        'baseline': baseline_path,
        'baseline_name': base_id,
        'ok': True,
        'regions': {},
        'moved': [],
        'checks': [],
        'reasons': [],
    }
    try:
        tol = float(_REGRESSION_TOLERANCE if tolerance is None else tolerance)
        sf = int(step_flow or _CHARBAL_FLOW_STEP)
        sd = int(step_dir or _CHARBAL_DIR_STEP)
        mets = tuple(metrics or ('flow_median', 'flow_mean', 'reversals_per_s', 'net_path'))
        ww = dict(_REGRESSION_WORSE_WHEN)
        ww.update(worse_when or {})
        out.update({'tolerance': tol, 'step_flow': sf, 'step_dir': sd, 'metrics': list(mets)})

        prov = {'ok': True, 'notes': []}
        for label, p in (('new', clip_path), ('baseline', baseline_path)):
            try:
                st = os.stat(p)
                prov[label] = {
                    'path': p,
                    'size': st.st_size,
                    'mtime': time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(st.st_mtime)),
                }
            except OSError as e:
                prov['ok'] = False
                prov['notes'].append(f'{label} unreadable: {e}')
        if os.path.realpath(clip_path) == os.path.realpath(baseline_path):
            out['error'] = 'new and baseline resolve to the SAME FILE — nothing to compare; THIS GATE DID NOT RUN'
            prov['ok'] = False
            prov['notes'].append(out['error'])
            out['reasons'].append(out['error'])
            out['checks'].append({'check': 'regression:provenance', 'ok': False, 'note': out['error']})
            out['provenance'] = prov
            log(f'[qc_regression_vs] {out["error"]}')
            _record_qc(out)
            return out
        if os.path.basename(clip_path) == os.path.basename(baseline_path):
            msg = (
                f'both files are named {os.path.basename(clip_path)!r} in different '
                f'directories. That is the 2026-07-31 v12 incident verbatim: a driver '
                f'copied from v11 changed its OUT dir but not its output FILENAME '
                f'constant, so two renders shipped under one name and were compared as '
                f'if both were v11. Derive version, directory and filename from ONE '
                f'constant. Sizes: {prov.get("new", {}).get("size")} vs '
                f'{prov.get("baseline", {}).get("size")}'
            )
            prov['ok'] = False
            prov['notes'].append(msg)
            out['reasons'].append(msg)
            log(f'[qc_regression_vs] PROVENANCE WARNING: {msg}')
        out['provenance'] = prov
        out['checks'].append({'check': 'regression:provenance', 'ok': prov['ok'], 'note': '; '.join(prov['notes'])})

        regions = {k: v for k, v in (regions or {}).items() if _valid_box(v)}
        if not regions:
            out['error'] = 'no valid regions supplied — THIS GATE DID NOT RUN'
            out['reasons'].append(out['error'])
            log(f'[qc_regression_vs] {out["error"]}')
            _record_qc(out)
            return out

        def _measure(p):
            fps, vf, pf = _region_flow_vectors(p, regions, step=sf)
            vd = vf if sd == sf else _region_flow_vectors(p, regions, step=sd)[1]
            rec = {}
            for n in regions:
                ps = _perpix_stats(pf.get(n))
                ds = _motion_vector_stats(vd.get(n), fps, sd)
                m = dict(ps or {})
                if ds:
                    m.update(
                        {
                            'reversals_per_s': ds['reversals_per_s'],
                            'net_path': ds['net_path'],
                            'vec_mean': ds['flow_mean'],
                        }
                    )
                rec[n] = m
            return rec

        new = _measure(clip_path)
        old = _measure(baseline_path)
        for n in regions:
            rrec = {'box': list(regions[n]), 'metrics': {}}
            still = (
                new[n].get('vec_mean') is not None
                and old[n].get('vec_mean') is not None
                and min(new[n]['vec_mean'], old[n]['vec_mean']) < _MOTION_COHERENCE_FLOOR
            )
            for m in mets:
                b, a = old[n].get(m), new[n].get(m)
                if b is None or a is None:
                    rrec['metrics'][m] = {
                        'baseline': b,
                        'new': a,
                        'comparable': False,
                        'note': 'not measured on one of the clips',
                    }
                    continue
                if m in ('reversals_per_s', 'net_path') and still:
                    rrec['metrics'][m] = {
                        'baseline': round(float(b), 4),
                        'new': round(float(a), 4),
                        'comparable': False,
                        'note': 'region below the coherence floor on one clip — direction '
                        'is a noise reading, not compared',
                    }
                    continue
                delta = float(a) - float(b)
                denom = max(abs(float(b)), _REGRESSION_FLOOR)
                rel = delta / denom
                moved = abs(rel) > tol
                direction = ww.get(m)
                worse = bool(moved and ((direction == 'down' and delta < 0) or (direction == 'up' and delta > 0)))
                # ── COHERENCE VETO (2026-08-01) ──────────────────────────────
                # 'reversals rising' is only jitter when the path does NOT become
                # more coherent. A region that genuinely moves MORE also changes
                # direction more often, so the raw rule condemns real animation.
                # Measured on v15 vs v14 (FINAL clips), this rule alone reported
                # four REGRESSIONS that were the opposite:
                #     pipe    reversals 0.908 -> 2.471 (+172%)  net_path 0.317 -> 0.539
                #     c_hands reversals 0.807 -> 2.672 (+231%)  net_path 0.547 -> 0.670
                #     c_face  reversals 1.008 -> 2.672 (+165%)  net_path 0.084 -> 0.239
                # Every one paired MORE direction changes with a MORE coherent
                # path, i.e. more movement. This is the same discriminator that
                # settled the v6-vs-v10 "faster or slower" argument: magnitude
                # and reversal COUNT both lie on their own; net/path is the one
                # that tracks what the eye calls motion. So a reversals rise is
                # vetoed when net_path improved by more than the same tolerance.
                veto = ''
                if worse and m == 'reversals_per_s':
                    b_np, a_np = old[n].get('net_path'), new[n].get('net_path')
                    if b_np is not None and a_np is not None:
                        np_rel = (float(a_np) - float(b_np)) / max(abs(float(b_np)), _REGRESSION_FLOOR)
                        if np_rel > tol:
                            worse = False
                            veto = (
                                f'reversals rose {rel * 100:+.1f}% BUT net_path rose '
                                f'{np_rel * 100:+.1f}% ({float(b_np):.4f} -> '
                                f'{float(a_np):.4f}) — more direction changes with a '
                                f'MORE coherent path is more movement, not jitter; '
                                f'not counted as a regression'
                            )
                rrec['metrics'][m] = {
                    'baseline': round(float(b), 4),
                    'new': round(float(a), 4),
                    'delta': round(delta, 4),
                    'rel': round(rel, 4),
                    'comparable': True,
                    'moved': moved,
                    'regression': worse,
                    'worse_when': direction,
                    'coherence_veto': veto or None,
                    'floored': abs(float(b)) < _REGRESSION_FLOOR,
                }
                if moved:
                    out['moved'].append(
                        {
                            'region': n,
                            'metric': m,
                            'baseline': round(float(b), 4),
                            'new': round(float(a), 4),
                            'delta': round(delta, 4),
                            'rel': round(rel, 4),
                            'regression': worse,
                        }
                    )
                note = ''
                if worse:
                    note = (
                        f'{n}.{m} {b:.4f} -> {a:.4f} ({rel * 100:+.1f}%) — moved in the '
                        f'REGRESSION direction ({direction}) by more than '
                        f'{tol * 100:.0f}%'
                    )
                elif veto:
                    note = f'{n}.{m} {veto}'
                elif moved:
                    note = (
                        f'{n}.{m} {b:.4f} -> {a:.4f} ({rel * 100:+.1f}%) — improvement '
                        f'or neutral move, reported not gated'
                    )
                out['checks'].append(
                    {
                        'check': f'regression:{n}.{m}',
                        'ok': not worse,
                        'delta': round(delta, 4),
                        'rel': round(rel, 4),
                        'baseline': round(float(b), 4),
                        'new': round(float(a), 4),
                        'note': note,
                    }
                )
            out['regions'][n] = rrec
        out['moved'].sort(key=lambda d: abs(d['rel']), reverse=True)
        # Same silent-pass hole as the balance gate: an unreadable clip yields nothing
        # comparable, no per-metric checks are emitted, and 'ok' stays True by default.
        comparable = sum(1 for r in out['regions'].values() for m in r['metrics'].values() if m.get('comparable'))
        out['comparisons'] = comparable
        if not comparable:
            msg = (
                f'{len(regions)} region(s) x {len(mets)} metric(s) requested and NOT ONE '
                f'was comparable — one of the two clips is unreadable or too short; '
                f'THIS GATE DID NOT RUN'
            )
            out['error'] = msg
            out['reasons'].append(msg)
            out['checks'].append({'check': 'regression:measured', 'ok': False, 'comparisons': 0, 'note': msg})
            log(f'[qc_regression_vs] WARNING: {msg}')
        out['ok'] = all(c.get('ok', True) for c in out['checks'])
        log(
            f'[qc_regression_vs] {os.path.basename(clip_path)} vs {base_id}: '
            f'{len(out["moved"])} metric(s) moved > {tol * 100:.0f}%, '
            f'{sum(1 for m in out["moved"] if m["regression"])} in the regression direction'
        )
        for m in out['moved']:
            log(
                f'[qc_regression_vs]   {"REGRESSION" if m["regression"] else "changed   "} '
                f'{m["region"]}.{m["metric"]}: {m["baseline"]} -> {m["new"]} '
                f'({m["rel"] * 100:+.1f}%)'
            )
    except Exception as e:
        out['error'] = str(e)[:200]
        out['ok'] = bool(fail_open)
        log(f'[qc_regression_vs] ERROR (fail-{"open" if fail_open else "CLOSED"}): {e}')
    _record_qc(out)
    return out
