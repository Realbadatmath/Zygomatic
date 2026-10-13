# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Why did eight of ten male captions come back in female register?

One arm (m02_bright_tenor, the worst at 438.7 Hz), four conditions, one seed
held across all four so the only thing moving is the CONDITIONING:

  A  a2a on the melody shifted DOWN 12 semitones
  B  a2a on the melody shifted DOWN  7 semitones
  C  text-to-music — no melody conditioning at all
  D  a2a on the melody as-is, second seed (the re-seed control)

The hypothesis under test is that the a2a latent, not the caption, sets the
octave: the composed tune lives D4-D5, which is a female tessitura, and the
sampler starting from that latent at denoise 0.45 has nowhere male to go. D is
what separates "the conditioning pins it" from "seed noise, try again".
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
os.environ['ZYG_KIDSMUSIC_SINGER_ENFORCE'] = '0'

from zyg_workflows import kids_music_service as K  # noqa: E402
from zyg_workflows import kids_music_theory as T  # noqa: E402

sys.path.insert(0, os.path.join(CREWS, 'tools'))
import rubberband_r3 as RB  # noqa: E402

_zyg_log = _zyg_logging.getLogger(__name__)

JOB = os.path.join(CREWS, 'output/kidsmusic/1ba342d5cd75')
OUT = os.path.join(JOB, 'male_voices', '_probe')
CAPTION = 'bright adult male lead vocal, light tenor, crisp cheerful grown-up man singing'
SEED = 314159265  # the seed that produced 438.7 Hz


def log(m):
    _zyg_log.info(f'[{time.strftime("%H:%M:%S")}] {m}')


def shifted_melody(src, st):
    dst = os.path.join(OUT, f'_melody_m{abs(st)}.wav')
    if not os.path.isfile(dst):
        y, sr = RB._decode(src)
        # shift() returns (audio, engine_version) — the version is not audio.
        out, _ver = RB.shift(y, sr, semitones=float(st), formant='follow')
        RB._encode(out, sr, dst)
    return dst


def main():
    os.makedirs(OUT, exist_ok=True)
    plan = json.load(open(os.path.join(JOB, 'song.json')))
    base = os.path.join(JOB, 'male_voices', '_melody.wav')
    if not os.path.isfile(base):
        K._ff(
            ['-i', os.path.join(JOB, 'melody.mp3'), '-ar', '48000', '-ac', '2', '-c:a', 'pcm_s16le', base], log_fn=log
        )

    male = T.SINGERS['adult_male']
    T.SINGERS['probe'] = dict(male, label='probe', caption=CAPTION)
    plan['brief']['singer'] = 'probe'

    arms = [
        ('A_a2a_down12', shifted_melody(base, -12), SEED),
        ('B_a2a_down7', shifted_melody(base, -7), SEED),
        ('C_text_only', None, SEED),
        ('D_a2a_reseed', base, 987654321),
    ]
    rows = []
    for key, mel, seed in arms:
        take = os.path.join(OUT, f'{key}.mp3')
        log(f'--- {key}  seed={seed}  melody={os.path.basename(mel) if mel else "none"}')
        rec = {}
        got = (
            take
            if os.path.isfile(take) and os.path.getsize(take) > 10_000
            else K.ace_render(plan, take, seed=seed, melody_wav=mel, log_fn=log, info=rec)
        )
        row = {
            'arm': key,
            'seed': seed,
            'ok': bool(got),
            'melody': os.path.basename(mel) if mel else '',
            'mode': rec.get('mode'),
            'reason': rec.get('reason', ''),
        }
        if got:
            g = K.gate_singer_age(got, plan, log_fn=log)
            c = g.get('checks') or {}
            row.update(
                f0=c.get('f0_median_hz'),
                p10=c.get('f0_p10_hz'),
                p90=c.get('f0_p90_hz'),
                status=g['status'],
                vocal_db=(c.get('separation') or {}).get('ratio_db'),
            )
            log(f'    F0 {row["f0"]} Hz  [{row["status"]}]')
        rows.append(row)
        json.dump(
            {'question': 'does the a2a latent set the octave?', 'caption': CAPTION, 'arms': rows},
            open(os.path.join(OUT, 'probe.json'), 'w'),
            indent=1,
        )

    log('=== PROBE ===')
    for r in rows:
        log(f'{r["arm"]:16s} F0={r.get("f0")} {r.get("status", "-")} ({r["mode"]}, vocal {r.get("vocal_db")} dB)')
    return 0


if __name__ == '__main__':
    sys.exit(main())
