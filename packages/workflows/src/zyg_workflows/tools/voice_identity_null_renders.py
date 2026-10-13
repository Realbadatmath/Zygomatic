# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The null for "is this the Warm Control voice": OTHER male voices on the SAME songs.

A voice-embedding similarity between a new take and the Warm Control reference
means nothing on its own — two takes of one song share lyrics, key, tempo and
mix, and an embedding can score that as "same voice". So each bench song gets
three more takes that differ from the stock-caption 'base' take ONLY in the
caption: m05 playful cartoon, m06 folk storyteller (both kept by the operator
on 2026-09-10) and m08 husky bass (the most distinct of the ten). Same plan,
same seed 1669026733, same score conditioning (the bench's cond_base.wav), same
a2a graph.

If the embedding places the stock-caption take closer to the Warm Control
reference than these, paired by song, identity is measurable across songs.
If not, it is not — and the report must say so rather than gate on it.

Output: output/kidsmusic/_voice_build/null_takes/<song>/<caption>.mp3 (resumable).
"""

import json
import logging as _zyg_logging
import os
import sys
import time
from zyg_workflows import paths

CREWS = str(paths.ZYG_CREWS_ROOT)
sys.path.insert(0, CREWS)
if os.path.isdir(CREWS):  # absent on a bare checkout (CI, a fresh clone)
    os.chdir(CREWS)

from zyg_workflows import kids_music_service as K  # noqa: E402
from zyg_workflows import kids_music_theory as T  # noqa: E402

_zyg_log = _zyg_logging.getLogger(__name__)

SEED = 1669026733
BENCH = os.path.join(CREWS, 'output/kidsmusic/_male_octave_bench')
OUT = os.path.join(CREWS, 'output/kidsmusic/_voice_build/null_takes')
RT = json.load(open(os.path.join(CREWS, 'output/kidsmusic/1ba342d5cd75/male_voices/index.json')))
CAPTIONS = {
    t['key']: t['caption']
    for t in RT['takes']
    if t['key'] in ('m05_playful_cartoon', 'm06_folk_storyteller', 'm08_husky_bass')
}
SONGS = [
    '19387e019f27',
    'c7284ed06145',
    '1ba342d5cd75',
    '0fc29420eb5a',
    '1da0a2c6f257',
    '36039a6c117a',
    '37159301a13c',
    '3f2b407846b0',
    '5e42a3574fd4',
    'e2cd9a19ef90',
    'dd194f224b94',
    '6e0a355deadf',
]


def log(m):
    _zyg_log.info(f'[{time.strftime("%H:%M:%S")}] {m}')


def main():
    if not K.ace_available():
        raise SystemExit('ACE-Step leg unavailable')
    male = T.SINGERS['adult_male']
    for sid in SONGS:
        plan = json.load(open(os.path.join(CREWS, 'output/kidsmusic', sid, 'song.json')))
        cond = os.path.join(BENCH, sid, 'cond_base.wav')
        os.makedirs(os.path.join(OUT, sid), exist_ok=True)
        for key, cap in CAPTIONS.items():
            take = os.path.join(OUT, sid, f'{key}.mp3')
            if os.path.isfile(take) and os.path.getsize(take) > 10_000:
                continue
            T.SINGERS[key] = dict(male, label=key, caption=cap)
            plan['brief']['singer'] = key
            t0 = time.time()
            rec = {}
            got = K.ace_render(plan, take, seed=SEED, melody_wav=cond, log_fn=None, info=rec)
            log(f'{sid} {key}: {"ok" if got else "FAILED " + str(rec.get("reason"))} ({time.time() - t0:.1f}s)')
    return 0


if __name__ == '__main__':
    sys.exit(main())
