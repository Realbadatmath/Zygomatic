# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Training data for a Warm Control voice-conversion model.

Warm Control is (stock male caption, seed 1669026733) on Red Train — ONE 57 s
take. RVC needs minutes. New songs cannot supply them: new lyrics are a new LM
draw, which is exactly the voice drift the conversion is meant to remove. So
every take here keeps the TEXT side identical (caption, lyrics, bpm, key, seed,
LM temperature) and varies only what the sampler starts from:

  rt_m01            the original Warm Control take (male_voices/m01_warm_control.mp3)
  bench base/rb12/mid12/lead12
                    yesterday's bench renders on Red Train at the same seed, four
                    melody conditionings (score / rubberband -12 / all tracks -12 /
                    melody -12)
  d035..d055        new: the score conditioning at a2a denoise 0.35/0.40/0.50/0.55

Each is split with demucs and kept only if its vocal median sits in the male band
(110-285 Hz) and it has >= 15 s voiced. Stems -> models/vc_applio/datasets/warm_control/.
Record: output/kidsmusic/_voice_build/vc/dataset.json
"""

import json
import logging as _zyg_logging
import os
import shutil
import sys
import time
from zyg_workflows import paths

CREWS = str(paths.ZYG_CREWS_ROOT)
sys.path.insert(0, CREWS)
os.chdir(CREWS)

from zyg_workflows import kids_music_service as K  # noqa: E402
from zyg_workflows import kids_music_theory as T  # noqa: E402
from zyg_workflows import vocal_analysis as VA  # noqa: E402

_zyg_log = _zyg_logging.getLogger(__name__)

SEED = 1669026733
RT = os.path.join(CREWS, 'output/kidsmusic/1ba342d5cd75')
BENCH = os.path.join(CREWS, 'output/kidsmusic/_male_octave_bench/1ba342d5cd75')
OUT = os.path.join(CREWS, 'output/kidsmusic/_voice_build/vc/dataset_takes')
DATASET = str(paths.ZYG_LEGACY_MODELS / 'vc_applio' / 'datasets' / 'warm_control')


def log(m):
    _zyg_log.info(f'[{time.strftime("%H:%M:%S")}] {m}')


def main():
    os.makedirs(OUT, exist_ok=True)
    os.makedirs(DATASET, exist_ok=True)
    plan = json.load(open(os.path.join(RT, 'song.json')))
    plan['brief']['singer'] = 'adult_male'
    male = T.SINGERS['adult_male']
    takes = {'rt_m01': os.path.join(RT, 'male_voices', 'm01_warm_control.mp3')}
    for arm in ('base', 'rb12', 'mid12', 'lead12'):
        takes[f'bench_{arm}'] = os.path.join(BENCH, f'{arm}.mp3')
    cond = os.path.join(BENCH, 'cond_base.wav')
    for d in (0.35, 0.40, 0.50, 0.55):
        key = f'd{int(d * 100):03d}'
        dst = os.path.join(OUT, f'{key}.mp3')
        if not os.path.isfile(dst):
            K.A2A_DENOISE = d
            rec = {}
            got = K.ace_render(plan, dst, seed=SEED, melody_wav=cond, log_fn=None, info=rec)
            log(f'{key}: {"rendered" if got else "FAILED " + str(rec.get("reason"))}')
        takes[key] = dst
    rows = []
    lo, hi = male['band']
    for key, path in takes.items():
        if not os.path.isfile(path):
            rows.append({'take': key, 'kept': False, 'reason': 'missing'})
            continue
        sd = os.path.join(OUT, 'stems', key)
        voc = os.path.join(sd, 'vocals.wav')
        if not os.path.isfile(voc):
            sep = VA.separate(path, sd)
            if not sep.get('ok'):
                rows.append({'take': key, 'kept': False, 'reason': f'separation: {sep.get("error")}'})
                continue
        tr = VA.pitch_track(voc)
        f0 = tr['f0'][tr['voiced']]
        med = float(sorted(f0)[len(f0) // 2]) if len(f0) else None
        voiced_s = round(float(tr['voiced'].sum()) * VA.HOP_S, 1)
        kept = bool(med and lo <= med <= hi and voiced_s >= 15.0)
        rows.append(
            {
                'take': key,
                'source': path,
                'f0_median_hz': round(med, 1) if med else None,
                'voiced_s': voiced_s,
                'kept': kept,
                'reason': '' if kept else 'outside the male band or too little singing',
            }
        )
        if kept:
            shutil.copyfile(voc, os.path.join(DATASET, f'{key}.wav'))
        log(f'{key}: median {rows[-1]["f0_median_hz"]} Hz, voiced {voiced_s}s -> {"KEPT" if kept else "dropped"}')
    json.dump(
        {
            'seed': SEED,
            'song': '1ba342d5cd75',
            'rows': rows,
            'kept_voiced_s': round(sum(r['voiced_s'] for r in rows if r.get('kept')), 1),
        },
        open(os.path.join(os.path.dirname(OUT), 'dataset.json'), 'w'),
        indent=1,
    )
    log(
        f'dataset: {sum(1 for r in rows if r.get("kept"))} takes, '
        f'{sum(r["voiced_s"] for r in rows if r.get("kept")):.0f}s voiced'
    )


if __name__ == '__main__':
    main()
