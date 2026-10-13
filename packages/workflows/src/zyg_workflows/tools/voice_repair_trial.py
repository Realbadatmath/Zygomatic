# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Trial of kids_music_service.repair_take on a real shipped take, outside run().

Usage: python tools/voice_repair_trial.py <job_id> [<job_id> ...]
Reviews <job>/song.mp3 with vocal_analysis.review, prints the problems and the
repaint windows, runs repair_take, and writes
output/kidsmusic/_voice_build/repair_trial/<job>/result.json (+ the spliced wavs).
Nothing in the job folder is modified.
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
os.environ.setdefault('ZYG_COMFY_KEEP_LOADED', '1')

from zyg_workflows import kids_music_service as K  # noqa: E402
from zyg_workflows import kids_music_theory as T  # noqa: E402
from zyg_workflows import vocal_analysis as VA  # noqa: E402

_zyg_log = _zyg_logging.getLogger(__name__)


def log(m):
    _zyg_log.info(f'[{time.strftime("%H:%M:%S")}] {m}')


def slim(rep):
    return {k: rep.get(k) for k in ('ok', 'error', 'severity', 'problems', 'lyrics', 'register', 'key', 'level')} | {
        'lines': [
            {
                k: ln.get(k)
                for k in (
                    'line',
                    'sung',
                    'coverage',
                    'start_s',
                    'end_s',
                    'f0_median_hz',
                    'f0_p95_hz',
                    'in_key_share',
                    'vocal_over_backing_db',
                    'heard',
                )
            }
            for ln in rep.get('lines') or []
        ]
    }


def main(jobs):
    for job in jobs:
        jd = os.path.join(CREWS, 'output/kidsmusic', job)
        wd = os.path.join(CREWS, 'output/kidsmusic/_voice_build/repair_trial', job)
        os.makedirs(wd, exist_ok=True)
        plan = json.load(open(os.path.join(jd, 'song.json')))
        man = json.load(open(os.path.join(jd, 'manifest.json')))
        singer = T.SINGERS[plan['brief'].get('singer') or T.DEFAULT_SINGER]
        take = os.path.join(jd, 'song.mp3')
        t0 = time.time()
        rep = VA.review(take, plan, singer, os.path.join(wd, 'review_original'), log_fn=log)
        log(f'{job} original ({time.time() - t0:.0f}s): {VA.summary_line(rep)}')
        wins = VA.repair_windows(rep, rep.get('problems') or [], seconds=float(plan['seconds']))
        log(f'windows: {wins}')
        prod = man.get('produced') or {}
        info = {
            'seed': prod.get('seed'),
            'lm_seed': None,
            'ace_tags': prod.get('ace_tags'),
            'seconds': float(plan['seconds']),
        }
        t1 = time.time()
        final, frep, recs = K.repair_take(take, plan, singer, rep, info, wd, log_fn=log)
        log(f'{job} repaired ({time.time() - t1:.0f}s): {VA.summary_line(frep)}')
        json.dump(
            {
                'job': job,
                'original': slim(rep),
                'windows': wins,
                'records': recs,
                'final_path': final,
                'final': slim(frep),
                'seconds': {'review': round(t1 - t0, 1), 'repair': round(time.time() - t1, 1)},
            },
            open(os.path.join(wd, 'result.json'), 'w'),
            indent=1,
        )


if __name__ == '__main__':
    main(sys.argv[1:] or ['82b8bc806676'])
