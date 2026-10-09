# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Is every promoted take still THE RED TRAIN TO THE SEA?

The re-seed pass changed only the seed and the fallback changed the conditioning,
but neither is a reason to assume the song survived: a different seed on the same
a2a latent can still drift the key, and the fallback deliberately fed the graph an
octave-lowered arrangement. gate_audio measures the delivered file's key and tempo
against the plan, which is the same check the shipped master passed.

Recorded on every row, not just the one that looked risky -- the arm that was
never suspected is exactly the one nobody would re-check.
"""

import json
import logging as _zyg_logging
import os
import sys
import time
from zyg_workflows import paths

CREWS = str(paths.ZYG_CREWS_ROOT)
sys.path.insert(0, CREWS)
os.chdir(CREWS)
os.environ['ZYG_KIDSMUSIC_SINGER_ENFORCE'] = '0'
from zyg_workflows import kids_music_service as K  # noqa: E402
from zyg_workflows import kids_music_theory as T  # noqa: E402

_zyg_log = _zyg_logging.getLogger(__name__)

JOB = os.path.join(CREWS, 'output/kidsmusic/1ba342d5cd75')
OUT = os.path.join(JOB, 'male_voices')


def log(m):
    _zyg_log.info(f'[{time.strftime("%H:%M:%S")}] {m}')


def main():
    idx = json.load(open(os.path.join(OUT, 'index.json')))
    plan = json.load(open(os.path.join(JOB, 'song.json')))
    lo, hi = T.SINGERS['adult_male']['band']
    bad = []
    for t in idx['takes']:
        p = os.path.join(OUT, t.get('master') or f'{t["key"]}.mp3')
        if not os.path.isfile(p):
            log(f'{t["key"]}: NO FILE'), bad.append(t['key'])
            continue
        g = K.gate_audio(p, plan, leg='render', want_clap=False, log_fn=None)
        c = g.get('checks') or {}
        chk = {
            'detected_key': c.get('detected_key'),
            'key_match': c.get('key_match'),
            'detected_bpm': c.get('detected_bpm'),
            'bpm_error': c.get('bpm_error'),
            'bpm_relation': c.get('bpm_relation'),
            'duration_s': c.get('duration_s'),
            'lufs': c.get('lufs'),
            'peak_dbfs': c.get('peak_dbfs'),
        }
        t['song_check'] = chk
        f0 = (t.get('gate') or {}).get('f0_median_hz')
        male = f0 is not None and lo <= f0 <= hi
        same = chk['key_match'] in ('exact', 'relative', 'same') and chk['bpm_relation'] in ('same', 'exact')
        if not (male and same):
            bad.append(t['key'])
        log(
            f'{t["key"]:22s} F0={f0:<6} {"male" if male else "NOT MALE"}  '
            f'{chk["detected_key"]} ({chk["key_match"]})  '
            f'{chk["detected_bpm"]} bpm ({chk["bpm_relation"]})  '
            f'{chk["lufs"]} LUFS  {chk["duration_s"]}s'
        )
    idx['verified'] = {'ran': time.strftime('%Y-%m-%dT%H:%M:%S'), 'all_male': not bad, 'failures': bad}
    json.dump(idx, open(os.path.join(OUT, 'index.json'), 'w'), indent=1)
    log('ALL TEN OK' if not bad else f'PROBLEMS: {bad}')
    return 0 if not bad else 1


if __name__ == '__main__':
    sys.exit(main())
