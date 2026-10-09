#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Bench the per-slot, prompt-derived, crop-based era gate against a confirmed truth set.

    python3 scripts/bench_era_gate.py <frames_dir> --state <pipeline_state.json> \
        [--truth 2,4,18] [--gore 15,28] [--judge local|api] [--no-llm] [--tier resident]

frames_dir : per-slot frames named slot_NNN.jpg (extract from the delivered mp4 with
             ffmpeg -ss i*T/n+3 when flux_images/ has already been cleaned up)
--state    : the run's pipeline_state.json — supplies the era lock and each slot's
             S prompt (essay_images[i].prompt)
--truth    : 0-based slots a panel CONFIRMED carry a modern anachronism
--gore     : 0-based slots confirmed as render-level gore (open wound / bone)
--judge    : 'local' = Qwen3-VL via vlm_inspector (default), 'api' = Anthropic vision
--no-llm   : derive the per-slot checks offline instead of the Haiku extraction

Why this exists (2026-08-25). The global question "does this show anything modern?"
measured yes on 34/40 frames from moondream and 2/8 recall from Qwen3-VL at 1280 px on
the Black Death episode — it missed a full-width motor boat. The anatomy-question
work (bench_vlm_gate_question.py) showed the same lesson twice: an unmeasured gate is
a decoration, and a gate that asks one bundled question cannot be trusted. This gate
asks one atomic yes/no per checkable object on enlarged tiles; this script is what
says whether that is actually better, per question id, before it is allowed to gate
a render.

Writes <frames_dir>/era_bench_<judge>.json with every per-slot verdict.
"""

import argparse
import glob
import json
import os
import sys
import time

CREWS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, CREWS)
os.chdir(CREWS)

_VENV_PY = os.path.join(os.path.dirname(CREWS), '.venv', 'bin', 'python')
if (
    os.path.exists(_VENV_PY)
    and os.path.abspath(sys.prefix) != os.path.abspath(os.path.dirname(_VENV_PY) + '/..')
    and not os.environ.get('ZYG_TEST_NO_REEXEC')
):
    os.execv(_VENV_PY, [_VENV_PY, '-u', os.path.abspath(__file__)] + sys.argv[1:])  # noqa: S606  re-exec under the venv interpreter: no shell, argv is this file's own


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('frames_dir')
    ap.add_argument('--state', required=True)
    ap.add_argument('--truth', default='')
    ap.add_argument('--gore', default='')
    ap.add_argument('--absent', default='', help='0-based slots where the prompted subject is missing')
    ap.add_argument('--judge', default='local', choices=('local', 'api'))
    ap.add_argument('--tier', default='resident')
    ap.add_argument('--no-llm', action='store_true')
    ap.add_argument('--limit', type=int, default=0)
    a = ap.parse_args()

    from zyg_workflows import era_gate as EG

    frames = sorted(glob.glob(os.path.join(a.frames_dir, 'slot_*.jpg')))
    if a.limit:
        frames = frames[: a.limit]
    if not frames:
        sys.exit(f'no slot_*.jpg in {a.frames_dir}')
    st = json.load(open(a.state))
    era = st.get('episode_era') or {}
    imgs = {int(e['index']): e for e in st.get('essay_images', []) if 'index' in e}
    prompts = [str((imgs.get(i) or {}).get('prompt') or '') for i in range(len(frames))]
    truth = {int(x) for x in a.truth.split(',') if x.strip()}
    gore = {int(x) for x in a.gore.split(',') if x.strip()}
    absent = {int(x) for x in a.absent.split(',') if x.strip()}
    api_key = os.environ.get('ANTHROPIC_API_KEY', '')

    print(
        f'{len(frames)} frames | era={era.get("period_label")} | judge={a.judge} tier={a.tier} '
        f'| truth={sorted(truth)} gore={sorted(gore)} absent={sorted(absent)}'
    )
    t0 = time.time()
    checks = EG.extract_checks(prompts, era, api_key='' if a.no_llm else api_key, log=print)
    print(
        f'checks extracted in {time.time() - t0:.1f}s: '
        f'{sum(1 for c in checks if c["source"] == "llm")} llm / '
        f'{sum(1 for c in checks if c["source"] != "llm")} offline\n'
    )

    rows = []
    per_id = {}
    tt = time.time()
    for i, fp in enumerate(frames):
        items = EG.build_items(checks[i], era)
        r = EG.judge_frame(fp, items, era, tier=a.tier, api_key=api_key, prefer=a.judge, log=lambda m: None)
        flags = r.get('flags') or []
        era_flags = [f for f in flags if f['id'] not in ('gore_wound_bone', 'subject_present')]
        gore_flag = any(f['id'] == 'gore_wound_bone' for f in flags)
        subj_flag = any(f['id'] == 'subject_present' for f in flags)
        rows.append(
            {
                'slot': i,
                'judge': r.get('judge'),
                'skipped': r.get('skipped'),
                'seconds': r.get('seconds'),
                'answers': r.get('answers'),
                'flags': flags,
                'unknown': r.get('unknown'),
                'checks': checks[i],
            }
        )
        for f in flags:
            per_id.setdefault(f['id'], []).append(i)
        mark = ('T' if i in truth else ' ') + ('G' if i in gore else ' ') + ('A' if i in absent else ' ')
        ids = ','.join(f'{f["id"]}' + ('*' if f.get('bbox') else '') for f in era_flags)
        print(
            f'slot {i:3d} {mark} era={"YES" if era_flags else "no "} gore={"YES" if gore_flag else "no "} '
            f'subj_missing={"YES" if subj_flag else "no "} unk={len(r.get("unknown") or [])} '
            f'{r.get("seconds")}s  {ids[:110]}'
        )
    print(f'\njudged {len(rows)} frames in {time.time() - tt:.0f}s')

    def score(name, pred, truthset):
        tp = len(pred & truthset)
        fp = len(pred - truthset)
        fn = len(truthset - pred)
        print(
            f'{name:14s} flagged {len(pred):2d} | caught {tp}/{len(truthset)} | false {fp} | missed {sorted(fn_ for fn_ in truthset - pred)}'
        )
        return tp, fp, fn

    era_pred = {
        r['slot'] for r in rows if any(f['id'] not in ('gore_wound_bone', 'subject_present') for f in r['flags'])
    }
    gore_pred = {r['slot'] for r in rows if any(f['id'] == 'gore_wound_bone' for f in r['flags'])}
    subj_pred = {r['slot'] for r in rows if any(f['id'] == 'subject_present' for f in r['flags'])}
    print()
    if truth:
        score('ERA (any id)', era_pred, truth)
    if gore:
        score('GORE', gore_pred, gore)
    if absent:
        score('SUBJECT', subj_pred, absent)
    print('\nper question id: slots flagged' + ('  (T = in truth)' if truth else ''))
    for qid, slots in sorted(per_id.items(), key=lambda kv: -len(kv[1])):
        print(f'  {qid:26s} {len(slots):2d}  ' + ' '.join(f'{s}{"T" if s in truth else ""}' for s in slots))
    out = os.path.join(a.frames_dir, f'era_bench_{a.judge}{"_offline" if a.no_llm else ""}.json')
    json.dump({'era': era, 'truth': sorted(truth), 'gore': sorted(gore), 'rows': rows}, open(out, 'w'), indent=1)
    print(f'\nwrote {out}')


if __name__ == '__main__':
    main()
