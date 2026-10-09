#!/usr/bin/env python

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""face_restore_receipt.py — run ONE real VACE face restore and prove the two
things S03 wired but never exercised: the `<out>.identity.json` sidecar, and the
ZYG_FACE_RESTORE_REQUIRE_GAIN=1 refusal, on a TRUE pair (the same clip in and
its own restored candidate out) rather than two unrelated published renders.

Modes (one process each, so the flag can differ between runs):

    columns   identity_bank.check_clip per character per column — which character
              sits in which half of the two-hander. Cheap, no GPU model load.
    null      score_identity_delta(clip, clip, ...) — the calibration. Scoring a
              clip against ITSELF must give delta 0.000; a non-zero here means the
              instrument is noisy and every other delta below is unreadable.
    run       restore_faces() once. --flag on|off sets ZYG_FACE_RESTORE_REQUIRE_GAIN
              in this process before the module reads it. Records the return value
              (a path = published, None = refused/failed), wall time and whether a
              .stage.mp4 was left behind.
    verify    score_identity_delta(input, restored_flagoff.mp4) taken independently
              and compared to the sidecar restore_faces wrote, to 3 decimals.
    receipt   fold every artifact above into receipt.json + RECEIPT.md. Reads only
              files already on disk; takes no new measurement.

Usage:
    "${ZYG_SERVER_PYTHON:-$HOME/Zygomatic Full/agents/.venv/bin/python}" \
        scripts/face_restore_receipt.py <mode> [--flag on|off]
"""

import argparse
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

CLIP_IN = os.path.join(HERE, 'output/multichar_seated/FINAL_seated_vace_dualLoRA.mp4')
OUTDIR = os.path.join(HERE, 'output/face_restore_receipt')
# Left-to-right, as established by the `columns` mode (see RECEIPT.md).
CHAR_IDS = ['0015c8a3f2e3', 'c3345deb5bde']  # Cornelis | Abel
COLUMNS = [(0.0, 0.0, 0.5, 1.0), (0.5, 0.0, 1.0, 1.0)]


def _w(name, obj):
    p = os.path.join(OUTDIR, name)
    with open(p, 'w') as fh:
        json.dump(obj, fh, indent=2, default=str)
    print(f'wrote {p}')


def mode_columns():
    from zyg_workflows import identity_bank as ib

    res = {}
    for cid in CHAR_IDS:
        for name, box in (('left', COLUMNS[0]), ('right', COLUMNS[1])):
            r = ib.check_clip(cid, 'arcane', CLIP_IN, roi=box, mode='perframe', stride=6, record=False, tag='colorder')
            r.pop('series', None)
            res[f'{cid}:{name}'] = r
            print(
                f'{cid} {name}: cosine={r.get("cosine")} p10={r.get("cosine_p10")} '
                f'pass_frac={r.get("pass_frac")} ok={r.get("ok")}'
            )
    _w('columns.json', res)


def mode_null():
    from zyg_workflows import wan_face_restore as FR

    t0 = time.time()
    r = FR.score_identity_delta(CLIP_IN, CLIP_IN, CHAR_IDS, rois=COLUMNS, log_fn=print)
    r['wall_s'] = round(time.time() - t0, 1)
    _w('null_selfscore.json', r)
    print('NULL delta_mean=%s delta_min=%s' % (r.get('delta_mean'), r.get('delta_min')))


def mode_run(flag, extra_prompt='', tag=None):
    os.environ['ZYG_FACE_RESTORE_REQUIRE_GAIN'] = '1' if flag == 'on' else '0'
    from zyg_workflows import wan_face_restore as FR

    assert FR._require_gain() == (flag == 'on'), 'flag did not take'
    tag = tag or ('flagon' if flag == 'on' else 'flagoff')
    out_path = os.path.join(OUTDIR, f'restored_{tag}.mp4')
    stage = out_path + '.stage.mp4'
    for p in (out_path, stage):
        if os.path.exists(p):
            os.remove(p)
    t0 = time.time()
    ret = FR.restore_faces(
        CLIP_IN,
        CHAR_IDS,
        out_path,
        steps=25,
        cfg=6.0,
        shift=5.0,
        seed=11,
        vace_strength=0.9,
        lora_strength=0.9,
        extra_prompt=extra_prompt,
        log_fn=print,
    )
    wall = round(time.time() - t0, 1)
    rec = {
        'flag': flag,
        'require_gain': flag == 'on',
        'seed': 11,
        'steps': 25,
        'tag': tag,
        'extra_prompt': extra_prompt,
        'returned': ret,
        'published': bool(ret),
        'wall_s': wall,
        'out_exists': os.path.isfile(out_path),
        'stage_leaked': os.path.isfile(stage),
        'sidecar_exists': os.path.isfile(out_path + '.identity.json'),
    }
    _w(f'run_{tag}.json', rec)
    print(json.dumps(rec, indent=2))


def mode_verify():
    from zyg_workflows import wan_face_restore as FR

    out_path = os.path.join(OUTDIR, 'restored_flagoff.mp4')
    side = json.load(open(out_path + '.identity.json'))
    boxes = [tuple(b) if b else None for b in side.get('boxes') or []]
    r = FR.score_identity_delta(CLIP_IN, out_path, CHAR_IDS, rois=boxes, log_fn=print)
    cmp = {'sidecar_boxes': side.get('boxes'), 'independent': r, 'match': {}}
    ok = True
    for cid in CHAR_IDS:
        s = (side.get('identity', {}).get('chars', {}) or {}).get(cid, {})
        m = r['chars'].get(cid, {})
        row = {}
        for k in ('delta', 'delta_p10'):
            a, b = s.get(k), m.get(k)
            row[k] = {
                'sidecar': a,
                'independent': b,
                'same_3dp': (a is None and b is None)
                or (a is not None and b is not None and round(a, 3) == round(b, 3)),
            }
            ok = ok and row[k]['same_3dp']
        for side_key in ('before', 'after'):
            a = (s.get(side_key) or {}).get('cosine')
            b = (m.get(side_key) or {}).get('cosine')
            row[side_key + '_cosine'] = {
                'sidecar': a,
                'independent': b,
                'same_3dp': (a is not None and b is not None and round(a, 3) == round(b, 3)),
            }
            ok = ok and row[side_key + '_cosine']['same_3dp']
        cmp['match'][cid] = row
    cmp['all_match_3dp'] = ok
    _w('verify_flagoff.json', cmp)
    print('MATCH 3dp:', ok)


def _load(name, default=None):
    p = os.path.join(OUTDIR, name)
    if not os.path.isfile(p):
        return default
    try:
        return json.load(open(p))
    except Exception:
        return default


def _vram_peak():
    p = os.path.join(OUTDIR, 'vram_samples.csv')
    vals, ts = [], []
    if os.path.isfile(p):
        for ln in open(p):
            a = ln.strip().split(',')
            if len(a) == 2 and a[1].isdigit():
                ts.append(int(a[0]))
                vals.append(int(a[1]))
    return {
        'peak_mib': max(vals) if vals else None,
        'min_mib': min(vals) if vals else None,
        'samples': len(vals),
        'interval_s': 5,
        'span_s': (max(ts) - min(ts)) if ts else None,
    }


def mode_receipt():
    cols = _load('columns.json', {})
    null = _load('null_selfscore.json', {})
    r1 = _load('run_flagoff.json', {})
    r2 = _load('run_flagon.json', {})
    ver = _load('verify_flagoff.json', {})
    side_off = _load('restored_flagoff.mp4.identity.json', {})
    side_on = _load('restored_flagon.mp4.identity.json', {})

    names = {'0015c8a3f2e3': 'Cornelis', 'c3345deb5bde': 'Abel'}
    col_ev = {}
    for cid in CHAR_IDS:
        col_ev[cid] = {
            c: {
                k: (cols.get(f'{cid}:{c}') or {}).get(k)
                for k in ('cosine', 'cosine_p10', 'pass_frac', 'ok', 'found', 'sampled')
            }
            for c in ('left', 'right')
        }

    def per_char(side):
        out = {}
        for cid in CHAR_IDS:
            c = ((side.get('identity') or {}).get('chars') or {}).get(cid) or {}
            b, a = c.get('before') or {}, c.get('after') or {}
            out[cid] = {
                'name': names.get(cid, cid),
                'roi': c.get('roi'),
                'before': {
                    'mean': b.get('cosine'),
                    'p10': b.get('cosine_p10'),
                    'pass_frac': b.get('pass_frac'),
                    'ok': b.get('ok'),
                    'ledger': b.get('ledger'),
                    'found': b.get('found'),
                    'sampled': b.get('sampled'),
                    'floor': b.get('floor'),
                },
                'after': {
                    'mean': a.get('cosine'),
                    'p10': a.get('cosine_p10'),
                    'pass_frac': a.get('pass_frac'),
                    'ok': a.get('ok'),
                    'ledger': a.get('ledger'),
                    'found': a.get('found'),
                    'sampled': a.get('sampled'),
                    'floor': a.get('floor'),
                },
                'delta': c.get('delta'),
                'delta_p10': c.get('delta_p10'),
                'measurable': c.get('measurable'),
            }
        return out

    stage_glob = [f for f in sorted(os.listdir(OUTDIR)) if f.endswith('.stage.mp4')]
    if r2.get('published'):
        branch = 'PUBLISH (delta was a gain: ok is not False, os.replace ran)'
    elif r2.get('sidecar_exists') and not r2.get('out_exists'):
        branch = 'REFUSE (ZYG_FACE_RESTORE_REQUIRE_GAIN=1 and identity fell: stage deleted, None returned)'
    else:
        branch = 'NEITHER — restore_faces returned None before the gain check (see run_flagon.json)'

    rec = {
        'generated': time.strftime('%Y-%m-%dT%H:%M:%S%z'),
        'clip_in': CLIP_IN,
        'char_ids_left_to_right': CHAR_IDS,
        'char_names': [names[c] for c in CHAR_IDS],
        'column_order_evidence': col_ev,
        'null_calibration': {
            'delta_mean': null.get('delta_mean'),
            'delta_min': null.get('delta_min'),
            'per_char': {c: (null.get('chars') or {}).get(c, {}).get('delta') for c in CHAR_IDS},
            'passes': null.get('delta_mean') == 0.0,
        },
        'run1_flag_off': {
            **r1,
            'identity': per_char(side_off),
            'sidecar_delta_mean': ((side_off.get('identity') or {}).get('delta_mean')),
            'sidecar_delta_min': ((side_off.get('identity') or {}).get('delta_min')),
            'sidecar_ok': (side_off.get('identity') or {}).get('ok'),
            'boxes': side_off.get('boxes'),
        },
        'run2_flag_on': {
            **r2,
            'identity': per_char(side_on),
            'sidecar_delta_mean': ((side_on.get('identity') or {}).get('delta_mean')),
            'sidecar_delta_min': ((side_on.get('identity') or {}).get('delta_min')),
            'sidecar_ok': (side_on.get('identity') or {}).get('ok'),
            'boxes': side_on.get('boxes'),
        },
        'branch_that_fired': branch,
        'independent_rescore_matches_sidecar_3dp': ver.get('all_match_3dp'),
        'independent_rescore': ver.get('match'),
        'stage_files_left_behind': stage_glob,
        'stage_leaked': bool(stage_glob),
        'render_reproducibility': {
            'note': (
                'same seed 11, same steps/cfg/shift/strengths in both runs, but the '
                'two renders are NOT identical — so RUN 1 vs RUN 2 is not a clean A/B '
                'of the flag alone, and the run-to-run spread is the real noise floor '
                'for a single delta.'
            ),
            'per_char': {
                c: {
                    'run1_delta': (((side_off.get('identity') or {}).get('chars') or {}).get(c, {}).get('delta')),
                    'run2_delta': (((side_on.get('identity') or {}).get('chars') or {}).get(c, {}).get('delta')),
                }
                for c in CHAR_IDS
            },
            'delta_mean_run1': (side_off.get('identity') or {}).get('delta_mean'),
            'delta_mean_run2': (side_on.get('identity') or {}).get('delta_mean'),
        },
        'vram': _vram_peak(),
        'wall_s': {'run1': r1.get('wall_s'), 'run2': r2.get('wall_s')},
    }
    _w('receipt.json', rec)

    def ledger_row(l):
        l = l or {}
        return (
            f'found {l.get("found")} / not_found {l.get("not_found")} / '
            f'not_detectable {l.get("not_detectable")} / '
            f'unmeasurable {l.get("unmeasurable")}'
        )

    L = []
    L.append('# Face-restore receipt — one real VACE restore on a true pair')
    L.append('')
    L.append(
        f'Generated {rec["generated"]} · input `{os.path.relpath(CLIP_IN, HERE)}` '
        f'(992x720, 89 frames, 24 fps) · seed 11, 25 steps, cfg 6.0, shift 5.0, '
        f'vace 0.9, lora 0.9 — identical in both runs.'
    )
    L.append('')
    L.append('## 1. Column order (which character is in which half)')
    L.append('')
    L.append('`identity_bank.check_clip`, perframe, stride 6, floor 0.42, backend facenet.')
    L.append('')
    L.append('| character | left ROI 0,0,0.5,1 | right ROI 0.5,0,1,1 | verdict |')
    L.append('|---|---|---|---|')
    for cid in CHAR_IDS:
        lft, rgt = col_ev[cid]['left'], col_ev[cid]['right']
        win = 'LEFT' if (lft['cosine'] or 0) > (rgt['cosine'] or 0) else 'RIGHT'
        L.append(
            f'| {names[cid]} `{cid}` | {lft["cosine"]} (p10 {lft["cosine_p10"]}, '
            f'pass {lft["pass_frac"]}) | {rgt["cosine"]} (p10 {rgt["cosine_p10"]}, '
            f'pass {rgt["pass_frac"]}) | {win} |'
        )
    L.append('')
    L.append(f'**Left-to-right order used: {" , ".join(names[c] + " " + c for c in CHAR_IDS)}.**')
    L.append('')
    L.append('## 2. Null calibration')
    L.append('')
    L.append(
        '`score_identity_delta(clip, clip, ...)` — the same clip on both sides. A '
        'delta that is not exactly 0 would mean the instrument is noisy and every '
        'number below is unreadable.'
    )
    L.append('')
    for cid in CHAR_IDS:
        c = (null.get('chars') or {}).get(cid, {})
        L.append(
            f'- {names[cid]}: before {(c.get("before") or {}).get("cosine")} · '
            f'after {(c.get("after") or {}).get("cosine")} · **delta '
            f'{c.get("delta")}** (p10 {c.get("delta_p10")})'
        )
    L.append('')
    L.append(
        f'delta_mean **{null.get("delta_mean")}** · delta_min '
        f'**{null.get("delta_min")}** → null '
        f'{"PASSES" if null.get("delta_mean") == 0.0 else "FAILS"}.'
    )
    L.append('')
    for title, run, side in (
        ('3. RUN 1 — ZYG_FACE_RESTORE_REQUIRE_GAIN unset (0)', r1, side_off),
        ('4. RUN 2 — ZYG_FACE_RESTORE_REQUIRE_GAIN=1', r2, side_on),
    ):
        L.append('## ' + title)
        L.append('')
        L.append(
            f'returned `{run.get("returned")}` · published **{run.get("published")}** '
            f'· wall {run.get("wall_s")} s · output file on disk '
            f'{run.get("out_exists")} · sidecar written {run.get("sidecar_exists")} '
            f'· `.stage.mp4` left behind **{run.get("stage_leaked")}**'
        )
        L.append('')
        pc = per_char(side)
        L.append(
            '| character | before mean | before p10 | before pass_frac | after mean '
            '| after p10 | after pass_frac | delta | delta p10 |'
        )
        L.append('|---|---|---|---|---|---|---|---|---|')
        for cid in CHAR_IDS:
            d = pc.get(cid, {})
            b, a = d.get('before') or {}, d.get('after') or {}
            L.append(
                f'| {names[cid]} | {b.get("mean")} | {b.get("p10")} | '
                f'{b.get("pass_frac")} | {a.get("mean")} | {a.get("p10")} | '
                f'{a.get("pass_frac")} | **{d.get("delta")}** | {d.get("delta_p10")} |'
            )
        L.append('')
        L.append(
            f'sidecar delta_mean {(side.get("identity") or {}).get("delta_mean")} · '
            f'delta_min {(side.get("identity") or {}).get("delta_min")} · '
            f'ok `{(side.get("identity") or {}).get("ok")}`'
        )
        L.append('')
        L.append('Four-state ledger (per character, before / after):')
        L.append('')
        for cid in CHAR_IDS:
            d = pc.get(cid, {})
            L.append(f'- {names[cid]} before — {ledger_row((d.get("before") or {}).get("ledger"))}')
            L.append(f'- {names[cid]} after  — {ledger_row((d.get("after") or {}).get("ledger"))}')
        L.append('')
        L.append(f'Face boxes the detector derived (fractions, x0,y0,x1,y1): `{side.get("boxes")}`')
        L.append('')
    L.append('## 5. Which branch fired')
    L.append('')
    L.append(f'**{branch}**')
    L.append('')
    L.append('## 5b. Same seed, two different renders — the real noise floor')
    L.append('')
    L.append(
        'Both runs used seed 11 and identical steps/cfg/shift/vace/lora strengths, '
        'and both scored the SAME input clip (before = 0.7726 / 0.8193 in both). The '
        'deltas still differ, so the two runs are not a controlled A/B of the flag '
        'alone: what changed between them is the render, not only the env var.'
    )
    L.append('')
    L.append('| character | RUN 1 delta | RUN 2 delta | spread |')
    L.append('|---|---|---|---|')
    for cid in CHAR_IDS:
        d1 = ((side_off.get('identity') or {}).get('chars') or {}).get(cid, {}).get('delta')
        d2 = ((side_on.get('identity') or {}).get('chars') or {}).get(cid, {}).get('delta')
        sp = None if (d1 is None or d2 is None) else round(abs(d1 - d2), 4)
        L.append(f'| {names[cid]} | {d1} | {d2} | {sp} |')
    dm1 = (side_off.get('identity') or {}).get('delta_mean')
    dm2 = (side_on.get('identity') or {}).get('delta_mean')
    L.append(
        f'| **delta_mean** | {dm1} | {dm2} | {None if (dm1 is None or dm2 is None) else round(abs(dm1 - dm2), 4)} |'
    )
    L.append('')
    L.append(
        'The null in section 2 calibrates the INSTRUMENT (same clip twice = exactly '
        '0.0000); it says nothing about the RENDER. This table is the render null, '
        'and it is the number a single reported delta has to beat.'
    )
    L.append('')
    L.append('## 6. Independent re-score vs the sidecar (RUN 1)')
    L.append('')
    L.append(
        '`score_identity_delta(input, restored_flagoff.mp4)` run again from this '
        'script, with the same ROIs the sidecar recorded.'
    )
    L.append('')
    L.append('| character | quantity | sidecar | independent | same to 3 dp |')
    L.append('|---|---|---|---|---|')
    for cid in CHAR_IDS:
        for k, row in (ver.get('match') or {}).get(cid, {}).items():
            L.append(
                f'| {names[cid]} | {k} | {row.get("sidecar")} | {row.get("independent")} | {row.get("same_3dp")} |'
            )
    L.append('')
    L.append(f'**All quantities match to 3 decimals: {ver.get("all_match_3dp")}**')
    L.append('')
    L.append('## 7. Staging hygiene, cost')
    L.append('')
    L.append(f'`.stage.mp4` files left in the output folder: `{stage_glob or "none"}` → leaked **{bool(stage_glob)}**')
    v = rec['vram']
    L.append('')
    L.append(
        f'Wall time: RUN 1 {r1.get("wall_s")} s, RUN 2 {r2.get("wall_s")} s. '
        f'VRAM (whole-GPU `nvidia-smi memory.used`, sampled every 5 s, '
        f'{v.get("samples")} samples over {v.get("span_s")} s): peak '
        f'**{v.get("peak_mib")} MiB**, floor {v.get("min_mib")} MiB.'
    )
    L.append('')
    L.append('## 8. What this receipt does NOT prove')
    L.append('')
    L.append(
        '- **The refusal branch never fired.** Both renders came out marginally '
        'ABOVE the input, so `ok` was True and `REQUIRE_GAIN=1` published. The '
        "refusal path (delete the stage, return None, keep the caller's clip) is "
        'still unexercised by a real identity loss on a true pair. What RUN 2 proves '
        'is only that the flag does not block a gain.'
    )
    L.append(
        '- **The gain is at or under the render noise floor.** Abel moved +0.0007 in '
        'one render and +0.0002 in the other; the run-to-run spread of delta_mean '
        "(0.0047) is six times Abel's larger delta. Nothing here supports a claim "
        'that the restore improved Abel. Cornelis is positive in both renders '
        '(+0.0151, +0.0063) but varies by 2.4x between them.'
    )
    L.append(
        '- **The column test is not clean for Cornelis.** His score in the OTHER '
        "character's column (0.4653) sits above the 0.42 floor, so the same-clip "
        'impostor is not rejected outright; only the margin (0.763 vs 0.4653) and '
        "Abel's failure on the left (0.2361, pass_frac 0) make the assignment "
        'unambiguous.'
    )
    L.append('')
    with open(os.path.join(OUTDIR, 'RECEIPT.md'), 'w') as fh:
        fh.write('\n'.join(L) + '\n')
    print('wrote ' + os.path.join(OUTDIR, 'RECEIPT.md'))


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('mode', choices=['columns', 'null', 'run', 'verify', 'receipt'])
    ap.add_argument('--flag', choices=['on', 'off'], default='off')
    ap.add_argument(
        '--extra-prompt',
        dest='extra_prompt',
        default='',
        help='appended verbatim to the VACE prompt (restore_faces extra_prompt); use it to force a real identity loss',
    )
    ap.add_argument(
        '--tag',
        default=None,
        help='names the outputs restored_<tag>.mp4 / run_<tag>.json (default: flagon/flagoff from --flag)',
    )
    a = ap.parse_args()
    os.makedirs(OUTDIR, exist_ok=True)
    os.chdir(HERE)
    {
        'columns': mode_columns,
        'null': mode_null,
        'run': lambda: mode_run(a.flag, a.extra_prompt, a.tag),
        'verify': mode_verify,
        'receipt': mode_receipt,
    }[a.mode]()
