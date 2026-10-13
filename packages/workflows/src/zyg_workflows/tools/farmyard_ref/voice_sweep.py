# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Re-render ONE finished kids song with ten different female voices.

The song, the melody, the lyrics, the key, the tempo and the arrangement are
held fixed -- the a2a melody-conditioned graph that produced the shipped master
is the one that runs, at the same denoise -- so the only thing that moves
between takes is the singer clause at the head of the ACE-Step caption, plus
that take's own seed.

A "voice" here is therefore the PAIR (caption, seed) and both are recorded, so
whichever one the operator picks can be reproduced exactly.

Every take is measured by the shipping gate (demucs stem -> F0) and mastered
through the same prelevel + audio_mix.master chain as the delivered song, so
they can be compared at equal loudness rather than by whichever came out
loudest.
"""

import logging as _zyg_logging
import json
import os
import sys
import time
from zyg_workflows import paths

_zyg_log = _zyg_logging.getLogger(__name__)

CREWS = str(paths.ZYG_CREWS_ROOT)
sys.path.insert(0, CREWS)
if os.path.isdir(CREWS):  # absent on a bare checkout (CI, a fresh clone)
    os.chdir(CREWS)

from zyg_workflows import kids_music_service as K  # noqa: E402
from zyg_workflows import kids_music_theory as T  # noqa: E402

JOB = os.path.join(CREWS, 'output/kidsmusic/0fc29420eb5a')
OUT = os.path.join(JOB, 'voice_sweep')

# Ten female singer clauses. Each keeps "adult female ... grown-up woman" so the
# caption cannot drift towards a child voice (the one thing gate_singer_age
# documents it CANNOT separate), and varies only the timbre words after it.
# v01 is the shipped caption, unchanged, as the control.
VOICES = [
    ('v01_warm_control', 'clear adult female lead vocal, warm friendly grown-up woman singing'),
    ('v02_bright_soprano', 'bright adult female lead vocal, light soprano, crisp cheerful grown-up woman singing'),
    (
        'v03_rich_mezzo',
        'rich adult female lead vocal, warm mezzo-soprano, rounded lower register, grown-up woman singing',
    ),
    (
        'v04_soft_breathy',
        'soft adult female lead vocal, breathy and gentle, grown-up woman singing close to the microphone',
    ),
    (
        'v05_playful_cartoon',
        'playful adult female lead vocal, animated cartoon character tone, grown-up woman singing with a smile',
    ),
    (
        'v06_folk_storyteller',
        'clear adult female lead vocal, plain unaffected folk storyteller tone, grown-up woman singing',
    ),
    (
        'v07_theatre_belt',
        'strong adult female lead vocal, musical theatre belt, projected and confident grown-up woman singing',
    ),
    ('v08_husky_alto', 'husky adult female lead vocal, smoky low alto, slightly raspy grown-up woman singing'),
    ('v09_nursery_teacher', 'sweet adult female lead vocal, kind nursery teacher tone, calm grown-up woman singing'),
    (
        'v10_clean_pop',
        'polished adult female lead vocal, clean modern pop tone, tight controlled grown-up woman singing',
    ),
]
# Fixed per take so the whole sweep is reproducible. 1303347561 is the seed the
# shipped master was rendered with, kept on the control arm.
SEEDS = [1303347561, 214748301, 998877221, 40391177, 776650012, 1200034477, 88123456, 1729384756, 55501234, 631442890]


def log(msg):
    _zyg_log.info(f'[{time.strftime("%H:%M:%S")}] {msg}')


def main():
    os.makedirs(OUT, exist_ok=True)
    plan = json.load(open(os.path.join(JOB, 'song.json')))

    # The a2a leg needs a wav; the job kept the melody as mp3.
    melody_wav = os.path.join(OUT, '_melody.wav')
    if not os.path.isfile(melody_wav):
        if not K._ff(
            ['-i', os.path.join(JOB, 'melody.mp3'), '-ar', '48000', '-ac', '2', '-c:a', 'pcm_s16le', melody_wav],
            log_fn=log,
        ):
            raise SystemExit('could not decode melody.mp3')
    log(f'melody staged: {melody_wav}')

    if not K.ace_available():
        raise SystemExit('ACE-Step leg unavailable (ComfyUI down or checkpoint missing)')

    band = T.SINGERS['adult_female']['band']
    results = []
    for i, ((key, caption), seed) in enumerate(zip(VOICES, SEEDS), 1):
        take = os.path.join(OUT, f'{key}.mp3')
        master = os.path.join(OUT, f'{key}_master.mp3')
        log(f'--- {i}/10  {key}  seed={seed}')
        log(f'    caption: {caption}')

        # Inject this take's caption as a singer the plan casts. ace_prompt and
        # gate_singer_age both read T.SINGERS, so one edit steers both.
        T.SINGERS[key] = {
            'label': key,
            'age_class': 'adult_female',
            'caption': caption,
            'band': band,
            'measured': band,
            'n': 0,
        }
        plan['brief']['singer'] = key

        rec = {}
        t0 = time.time()
        got = None
        if os.path.isfile(take) and os.path.getsize(take) > 10_000:
            log('    take already on disk — reusing')
            got = take
            rec = {'ran': True, 'reason': 'reused existing file'}
        else:
            got = K.ace_render(
                plan, take, seed=seed, melody_wav=melody_wav, log_fn=log, info=rec, should_abort=lambda: False
            )
        row = {
            'key': key,
            'caption': caption,
            'seed': seed,
            'render_s': round(time.time() - t0, 1),
            'ace_tags': rec.get('ace_tags', ''),
            'workflow': rec.get('workflow', ''),
            'melody_conditioned': rec.get('melody_conditioned'),
            'a2a_denoise': rec.get('a2a_denoise'),
            'ok': bool(got),
            'reason': rec.get('reason', ''),
        }

        if got:
            # Same master chain as the delivered song, so the ten compare at
            # equal loudness.
            fed, trimmed = K.trim_tail(got, os.path.join(OUT, '_trim.wav'), log_fn=log)
            pre = K.prelevel(fed, os.path.join(OUT, '_pre.wav'), target_lufs=-14.0, tp_db=-1.5, log_fn=log)
            norm = {}
            try:
                from zyg_workflows import audio_mix

                mw = os.path.join(OUT, '_master.wav')
                if audio_mix.master(pre, mw, i=-14.0, tp=-1.0, log_fn=log, result=norm):
                    K._mp3(mw, master, log_fn=log, br='256k')
            except Exception as e:  # noqa: BLE001
                log(f'    master failed: {type(e).__name__}: {e}')
            row['master'] = os.path.basename(master) if os.path.isfile(master) else ''
            row['loudnorm'] = norm.get('normalization_type')
            row['trimmed_s'] = trimmed

            g = K.gate_singer_age(master if os.path.isfile(master) else got, plan, log_fn=log)
            row['gate'] = {
                'status': g['status'],
                'detail': g['detail'],
                'f0_hz': (g.get('checks') or {}).get('f0_median_hz'),
                'vtl_cm': (g.get('checks') or {}).get('vtl_cm'),
                'vocal_over_mix_db': ((g.get('checks') or {}).get('separation') or {}).get('ratio_db'),
            }
            log(f'    F0 {row["gate"]["f0_hz"]} Hz  [{row["gate"]["status"]}]')
        else:
            log(f'    FAILED: {row["reason"]}')

        results.append(row)
        json.dump(
            {'song': 'The Farmyard Sounds Song', 'job': '0fc29420eb5a', 'band_hz': list(band), 'takes': results},
            open(os.path.join(OUT, 'index.json'), 'w'),
            indent=1,
        )

    for tmp in ('_trim.wav', '_pre.wav', '_master.wav'):
        try:
            os.remove(os.path.join(OUT, tmp))
        except OSError as _exc:
            _zyg_log.debug('intermediate render cleanup skipped: %s', _exc)
    try:
        os.remove(
            os.path.join(
                str(paths.ZYG_COMFY_INPUT),
                f'kidsmusic_melody_{os.getpid()}.wav',
            )
        )
    except OSError as _exc:
        _zyg_log.debug('staged melody cleanup skipped: %s', _exc)

    log('=== SUMMARY ===')
    for r in results:
        g = r.get('gate') or {}
        log(
            f'{r["key"]:22s} seed={r["seed"]:<11d} '
            f'{"OK " if r["ok"] else "FAIL"} '
            f'F0={g.get("f0_hz")} {g.get("status", "-")}'
        )
    return 0


if __name__ == '__main__':
    sys.exit(main())
