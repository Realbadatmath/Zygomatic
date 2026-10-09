# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Ten LOWER-REGISTER samples of The Farmyard Sounds Song, made deterministically.

WHY NOT BY GENERATION. Measured across a ten-take ladder (register_sweep), moving
the score does NOT move the sung register: the composed melody was transposed
across a full octave (median 440 Hz down to 220 Hz) and the sung F0 stayed inside
298-421 Hz throughout, landing at 376 Hz for BOTH octave-down variants -- the
highest scores and the lowest scores produced the same voice. ACE-Step re-sings
in its own preferred female register and the a2a conditioning at denoise 0.45
does not constrain it. Caption wording moved it too, but not consistently: the
same two captions swapped order between the down-5 and down-7 pairs.

So the register is not steerable at generation time on this graph, and the honest
fix is a post-process, which is exact and repeatable.

WHAT THIS DOES. `rubberband=pitch=2^(-n/12):formant=preserved` on the FINISHED
master -- the whole mix, not the vocal alone. Pitching only the vocal would put
the singer in a different key from the clarinet, tuba and nylon guitar behind
her; moving everything keeps the arrangement internally consistent and simply
puts the song in a lower key, with duration untouched (rubberband is not a
resample).

WHY FORMANT=PRESERVED IS RIGHT HERE AND ONLY HERE. voice_studio's measurement
(2026-08-11) is that this ffmpeg build preserves formants in ONE direction only:
pitching DOWN really does hold the vocal tract, pitching UP silently does not.
Every shift below is downward, which is the direction that works -- so the singer
keeps her own timbre and simply sings lower, instead of turning into a larger
person.
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
os.chdir(CREWS)

from zyg_workflows import kids_music_service as K  # noqa: E402
from zyg_workflows import kids_music_theory as T  # noqa: E402

JOB = os.path.join(CREWS, 'output/kidsmusic/0fc29420eb5a')
OUT = os.path.join(JOB, 'pitch_fix')

# Two bases at opposite ends of what the generator produced, so the ladder covers
# the whole comfortable range rather than five neighbours of one take.
BASES = [
    ('warm', os.path.join(JOB, 'voice_sweep/v01_warm_control_master.mp3'), 370.5, 'the shipped warm caption'),
    (
        'cartoon',
        os.path.join(JOB, 'voice_sweep/v05_playful_cartoon_master.mp3'),
        374.4,
        'the most forward vocal of the first sweep',
    ),
]
STEPS = [2, 3, 4, 5, 6]  # semitones down


def log(m):
    _zyg_log.info(f'[{time.strftime("%H:%M:%S")}] {m}')


def shift(src, dst, semis):
    """Whole-mix pitch shift DOWN by `semis`, duration preserved."""
    ratio = 2.0 ** (-abs(semis) / 12.0)
    return K._ff(
        ['-i', src, '-af', f'rubberband=pitch={ratio:.6f}:formant=preserved', '-ar', '48000', '-c:a', 'pcm_s16le', dst],
        log_fn=log,
    )


def main():
    os.makedirs(OUT, exist_ok=True)
    plan = json.load(open(os.path.join(JOB, 'song.json')))
    # The cast band is what this whole exercise is questioning, so the gate is
    # asked for NUMBERS, not for a verdict: a take that reads 250 Hz is the goal
    # here and the shipped band would call it a failure.
    T.SINGERS['probe'] = {
        'label': 'probe',
        'age_class': 'adult_female',
        'caption': '',
        'band': (80.0, 600.0),
        'measured': (80.0, 600.0),
        'n': 0,
    }
    plan['brief']['singer'] = 'probe'

    rows = []
    for bname, src, base_f0, why in BASES:
        if not os.path.isfile(src):
            log(f'{bname}: base missing — skipped')
            continue
        for n in STEPS:
            key = f'{bname}_down{n}'
            log(f'--- {key}  ({why}, -{n} semitones)')
            wav = os.path.join(OUT, f'_{key}.wav')
            if not shift(src, wav, n):
                log('    shift failed')
                continue
            mp3 = os.path.join(OUT, f'{key}.mp3')
            pre = K.prelevel(wav, os.path.join(OUT, '_pre.wav'), target_lufs=-14.0, tp_db=-1.5, log_fn=log)
            norm = {}
            try:
                from zyg_workflows import audio_mix

                mw = os.path.join(OUT, '_master.wav')
                if audio_mix.master(pre, mw, i=-14.0, tp=-1.0, log_fn=log, result=norm):
                    K._mp3(mw, mp3, log_fn=log, br='256k')
            except Exception as e:  # noqa: BLE001
                log(f'    master failed: {type(e).__name__}: {e}')
            if not os.path.isfile(mp3):
                continue
            g = K.gate_singer_age(mp3, plan, log_fn=log)
            f0 = (g.get('checks') or {}).get('f0_median_hz')
            want = base_f0 * 2.0 ** (-n / 12.0)
            rows.append(
                {
                    'key': key,
                    'base': bname,
                    'base_file': os.path.basename(src),
                    'semitones_down': n,
                    'base_f0_hz': base_f0,
                    'predicted_f0_hz': round(want, 1),
                    'measured_f0_hz': f0,
                    'vocal_over_mix_db': ((g.get('checks') or {}).get('separation') or {}).get('ratio_db'),
                    'file': os.path.basename(mp3),
                }
            )
            log(f'    F0 {f0} Hz (predicted {want:.0f})')
            json.dump(
                {
                    'song': 'The Farmyard Sounds Song',
                    'job': '0fc29420eb5a',
                    'method': 'rubberband pitch down, formant=preserved, whole mix',
                    'takes': rows,
                },
                open(os.path.join(OUT, 'index.json'), 'w'),
                indent=1,
            )

    for f in os.listdir(OUT):
        if f.startswith('_') and f.endswith('.wav'):
            try:
                os.remove(os.path.join(OUT, f))
            except OSError as _exc:
                _zyg_log.debug('intermediate render cleanup skipped: %s', _exc)
    log('=== SUMMARY ===')
    for r in rows:
        log(
            f'{r["key"]:16s} -{r["semitones_down"]} st  '
            f'predicted {r["predicted_f0_hz"]:5.0f}  measured {r["measured_f0_hz"]}'
        )
    return 0


if __name__ == '__main__':
    sys.exit(main())
