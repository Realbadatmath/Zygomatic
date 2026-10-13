# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Warm Control dataset v2 — more renditions, kept only when they ARE the voice.

v1 (7 renditions, 176 s voiced) trained a model whose conversions sounded far
more alike across songs (pairwise 0.45 -> 0.71) but landed closer to the
original Warm Control take on only 6 of 8 bench songs — the model learned the
AVERAGE of its renditions, and on the bumblebee (already sung by the Warm
Control recipe) the average sat further from the reference than the source did.

v2, same text side (caption, lyrics, bpm, key, seed 1669026733, LM temperature):
  * renders a2a denoise {0.50, 0.55, 0.60, 0.65} x conditioning {score, melody -12,
    all tracks -12, rubberband -12} on Red Train (the v1 takes are reused)
  * keeps a take only if it is in the male band with >= 15 s sung AND its TitaNet
    voice embedding is at least as close to the original take (rt_m01) as the
    median kept take — selection on TRAINING renditions only; the 8 bench songs
    are never looked at
  * the original take is included three times (weight: it IS the chosen voice)
Stems -> models/vc_applio/datasets/warm_control_v2/. Record: _voice_build/vc/dataset_v2.json
"""

import json
import logging as _zyg_logging
import os
import shutil
import sys
import time

import numpy as np
from zyg_workflows import paths

CREWS = str(paths.ZYG_CREWS_ROOT)
sys.path.insert(0, CREWS)
if os.path.isdir(CREWS):  # absent on a bare checkout (CI, a fresh clone)
    os.chdir(CREWS)

from zyg_workflows import kids_music_service as K  # noqa: E402
from zyg_workflows import kids_music_theory as T  # noqa: E402
from zyg_workflows import vocal_analysis as VA  # noqa: E402

_zyg_log = _zyg_logging.getLogger(__name__)

SEED = 1669026733
RT = os.path.join(CREWS, 'output/kidsmusic/1ba342d5cd75')
BENCH = os.path.join(CREWS, 'output/kidsmusic/_male_octave_bench/1ba342d5cd75')
V1 = os.path.join(CREWS, 'output/kidsmusic/_voice_build/vc/dataset_takes')
OUT = os.path.join(CREWS, 'output/kidsmusic/_voice_build/vc/dataset_v2_takes')
DATASET = str(paths.ZYG_LEGACY_MODELS / 'vc_applio' / 'datasets' / 'warm_control_v2')
CONDS = {'score': 'cond_base.wav', 'lead12': 'cond_lead12.wav', 'mid12': 'cond_mid12.wav', 'rb12': 'cond_rb12.wav'}


def log(m):
    _zyg_log.info(f'[{time.strftime("%H:%M:%S")}] {m}')


def main():
    os.makedirs(OUT, exist_ok=True)
    plan = json.load(open(os.path.join(RT, 'song.json')))
    plan['brief']['singer'] = 'adult_male'
    lo, hi = T.SINGERS['adult_male']['band']

    takes = {'rt_m01': os.path.join(RT, 'male_voices', 'm01_warm_control.mp3')}
    for arm in ('base', 'rb12', 'mid12', 'lead12'):
        takes[f'd045_{arm}'] = os.path.join(BENCH, f'{arm}.mp3')
    for d in (0.50, 0.55, 0.60, 0.65):
        for cname, cfile in CONDS.items():
            key = f'd{int(round(d * 100)):03d}_{cname}'
            v1 = os.path.join(V1, f'd{int(round(d * 100)):03d}.mp3') if cname == 'score' else ''
            if v1 and os.path.isfile(v1):
                takes[key] = v1
                continue
            dst = os.path.join(OUT, f'{key}.mp3')
            if not os.path.isfile(dst):
                K.A2A_DENOISE = d
                rec = {}
                got = K.ace_render(plan, dst, seed=SEED, melody_wav=os.path.join(BENCH, cfile), log_fn=None, info=rec)
                log(f'{key}: {"rendered" if got else "FAILED " + str(rec.get("reason"))}')
            takes[key] = dst

    rows, clips = {}, {}
    for key, path in takes.items():
        if not os.path.isfile(path):
            rows[key] = {'kept': False, 'reason': 'missing'}
            continue
        sd = os.path.join(OUT, 'stems', key)
        voc = os.path.join(sd, 'vocals.wav')
        if not os.path.isfile(voc):
            sep = VA.separate(path, sd)
            if not sep.get('ok'):
                rows[key] = {'kept': False, 'reason': f'separation: {sep.get("error")}'}
                continue
        tr = VA.pitch_track(voc)
        f0 = tr['f0'][tr['voiced']]
        med = float(np.median(f0)) if f0.size else None
        voiced_s = round(float(tr['voiced'].sum()) * VA.HOP_S, 1)
        rows[key] = {
            'source': path,
            'vocals': voc,
            'f0_median_hz': round(med, 1) if med else None,
            'voiced_s': voiced_s,
            'in_band': bool(med and lo <= med <= hi and voiced_s >= 15.0),
        }
        if rows[key]['in_band']:
            clips[key] = VA.voiced_clip(voc, os.path.join(sd, 'clip.wav'), track=tr)['path']
    emb = VA.embed(clips, log_fn=log)
    ref = emb.get('rt_m01')
    for key in clips:
        if ref is not None and key in emb:
            rows[key]['cos_to_rt_m01'] = round(VA.cosine(ref, emb[key]), 4)
    sims = [rows[k]['cos_to_rt_m01'] for k in clips if k != 'rt_m01' and 'cos_to_rt_m01' in rows[k]]
    cut = float(np.median(sims)) if sims else 1.0
    if os.path.isdir(DATASET):
        shutil.rmtree(DATASET)
    os.makedirs(DATASET)
    kept_s = 0.0
    for key, r in rows.items():
        keep = bool(r.get('in_band') and (key == 'rt_m01' or r.get('cos_to_rt_m01', -1) >= cut))
        r['kept'] = keep
        if not keep:
            r.setdefault(
                'reason',
                'outside the male band / too little singing'
                if not r.get('in_band')
                else f'further from rt_m01 than the median ({cut:.3f})',
            )
            continue
        copies = 3 if key == 'rt_m01' else 1
        for c in range(copies):
            shutil.copyfile(r['vocals'], os.path.join(DATASET, f'{key}_{c}.wav'))
        kept_s += r['voiced_s'] * copies
        log(f'{key}: {r["f0_median_hz"]} Hz, {r["voiced_s"]}s, cos {r.get("cos_to_rt_m01")} -> KEPT x{copies}')
    for key, r in rows.items():
        if not r.get('kept'):
            log(f'{key}: dropped — {r.get("reason")} (f0 {r.get("f0_median_hz")}, cos {r.get("cos_to_rt_m01")})')
    json.dump(
        {'cut_cos_to_rt_m01': round(cut, 4), 'rows': rows, 'kept_voiced_s': round(kept_s, 1)},
        open(os.path.join(os.path.dirname(OUT), 'dataset_v2.json'), 'w'),
        indent=1,
    )
    log(
        f'dataset v2: {sum(1 for r in rows.values() if r.get("kept"))} takes, {kept_s:.0f}s voiced '
        f'(with rt_m01 x3), cut {cut:.3f}'
    )


if __name__ == '__main__':
    main()
