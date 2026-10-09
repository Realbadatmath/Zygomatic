# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Re-seed the male takes that came back in female register, until they are male.

PASS 1 rendered ten male captions and only two landed in the male band: the
other eight measured 290-439 Hz. The four-arm probe (male_voices/_probe) says
why, and says it is NOT what it first looked like:

    same caption, same seed, melody as-is        438.7 Hz
    same caption, same seed, melody down  7 st   277.4 Hz  pass
    same caption, same seed, melody down 12 st   250.2 Hz  pass
    same caption, same seed, no melody at all    185.4 Hz  pass
    same caption, SAME MELODY, one new seed      219.8 Hz  pass

The last row is the load-bearing one. Lowering the a2a source moves the octave,
but so does changing nothing except the seed — so the composed tune's D4-D5
tessitura does not PIN the register, it makes it a coin flip, and the caption
loses that flip more often than it wins. Had the probe stopped after the two
transposed arms the conclusion would have been "transpose the conditioning",
which would have re-rendered the whole arrangement an octave down to fix a
sampling problem.

So the lever used here is the seed, and nothing else: the melody, the caption,
the arrangement and the denoise are all the ones pass 1 used, and each failing
arm is re-rendered on fresh seeds until its vocal measures inside the cast band.
Every attempt is recorded on the row -- a take that needed four seeds is a
weaker arm than one that landed first time, and that is worth knowing when the
operator picks.
"""

import json
import logging as _zyg_logging
import os
import random
import shutil
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
ATT = os.path.join(OUT, '_attempts')
MAX_ATTEMPTS = 6


def log(m):
    _zyg_log.info(f'[{time.strftime("%H:%M:%S")}] {m}')


def master_of(src, dst):
    """The delivered song's chain, so every take compares at equal loudness."""
    fed, trimmed = K.trim_tail(src, os.path.join(ATT, '_trim.wav'), log_fn=None)
    pre = K.prelevel(fed, os.path.join(ATT, '_pre.wav'), target_lufs=-14.0, tp_db=-1.5, log_fn=None)
    norm = {}
    try:
        from zyg_workflows import audio_mix

        mw = os.path.join(ATT, '_master.wav')
        if audio_mix.master(pre, mw, i=-14.0, tp=-1.0, log_fn=None, result=norm):
            K._mp3(mw, dst, log_fn=None, br='256k')
    except Exception as e:  # noqa: BLE001
        log(f'    master failed: {type(e).__name__}: {e}')
    return norm.get('normalization_type'), trimmed


def main():
    os.makedirs(ATT, exist_ok=True)
    idx = json.load(open(os.path.join(OUT, 'index.json')))
    plan = json.load(open(os.path.join(JOB, 'song.json')))
    melody_wav = os.path.join(OUT, '_melody.wav')
    male = T.SINGERS['adult_male']
    lo, hi = male['band']

    if not K.ace_available():
        raise SystemExit('ACE-Step leg unavailable')

    for t in idx['takes']:
        key = t['key']
        f0 = (t.get('gate') or {}).get('f0_median_hz')
        if f0 is not None and lo <= f0 <= hi:
            t.setdefault('attempts', [{'seed': t['seed'], 'f0': f0, 'kept': True}])
            log(f'{key}: already male at {f0} Hz — kept')
            continue
        log(f'--- {key}: {f0} Hz is outside {lo:.0f}-{hi:.0f} — re-seeding')
        T.SINGERS[key] = dict(male, label=key, caption=t['caption'])
        plan['brief']['singer'] = key
        # Deterministic per arm, so a rerun retries the same seeds in the same
        # order rather than wandering off to a different answer.
        rng = random.Random(f'redtrain-male-{key}')
        attempts = [{'seed': t['seed'], 'f0': f0, 'kept': False}]
        won = None
        for n in range(1, MAX_ATTEMPTS + 1):
            seed = rng.randint(0, 2**31 - 1)
            raw = os.path.join(ATT, f'{key}_s{seed}.mp3')
            rec = {}
            got = (
                raw
                if os.path.isfile(raw) and os.path.getsize(raw) > 10_000
                else K.ace_render(plan, raw, seed=seed, melody_wav=melody_wav, log_fn=None, info=rec)
            )
            if not got:
                log(f'    seed {seed}: render failed — {rec.get("reason")}')
                attempts.append({'seed': seed, 'f0': None, 'reason': rec.get('reason', ''), 'kept': False})
                continue
            m = os.path.join(ATT, f'{key}_s{seed}_master.mp3')
            master_of(got, m)
            g = K.gate_singer_age(m if os.path.isfile(m) else got, plan, log_fn=None)
            c = g.get('checks') or {}
            got_f0 = c.get('f0_median_hz')
            ok = got_f0 is not None and lo <= got_f0 <= hi
            log(f'    attempt {n}  seed {seed}: {got_f0} Hz {"MALE — keeping" if ok else "still high"}')
            attempts.append({'seed': seed, 'f0': got_f0, 'kept': ok})
            if ok:
                won = (seed, got, m, g)
                break

        t['attempts'] = attempts
        t['attempts_used'] = len([a for a in attempts if a.get('f0') is not None])
        if not won:
            t['reseed'] = 'exhausted'
            log(f'    {key}: {MAX_ATTEMPTS} seeds, none landed male — left as pass 1')
            continue
        seed, raw, m, g = won
        shutil.copy2(raw, os.path.join(OUT, f'{key}.mp3'))
        if os.path.isfile(m):
            shutil.copy2(m, os.path.join(OUT, f'{key}_master.mp3'))
        c = g.get('checks') or {}
        t.update(
            {
                'seed': seed,
                'reseed': 'replaced',
                'master': f'{key}_master.mp3',
                'gate': {
                    'status': g['status'],
                    'detail': g['detail'],
                    'enforced': g.get('enforced'),
                    'f0_median_hz': c.get('f0_median_hz'),
                    'f0_p10_hz': c.get('f0_p10_hz'),
                    'f0_p90_hz': c.get('f0_p90_hz'),
                    'sharpness_acum': c.get('sharpness_acum'),
                    'hf_ratio_2k8k': c.get('hf_ratio_2k8k'),
                    'agreement_cents': c.get('agreement_cents'),
                    'tracker': c.get('tracker'),
                    'vocal_over_mix_db': (c.get('separation') or {}).get('ratio_db'),
                },
            }
        )
        json.dump(idx, open(os.path.join(OUT, 'index.json'), 'w'), indent=1)

    idx['reseed'] = {
        'ran': time.strftime('%Y-%m-%dT%H:%M:%S'),
        'max_attempts': MAX_ATTEMPTS,
        'lever': 'seed only — melody, caption, arrangement and denoise unchanged',
        'evidence': 'male_voices/_probe/probe.json',
    }
    json.dump(idx, open(os.path.join(OUT, 'index.json'), 'w'), indent=1)
    for tmp in ('_trim.wav', '_pre.wav', '_master.wav'):
        try:
            os.remove(os.path.join(ATT, tmp))
        except OSError as _exc:
            _zyg_log.debug('intermediate take cleanup skipped: %s', _exc)

    log('=== AFTER RE-SEED ===')
    for t in idx['takes']:
        g = t.get('gate') or {}
        f0 = g.get('f0_median_hz')
        log(
            f'{t["key"]:22s} seed={t["seed"]:<11} F0={f0} '
            f'{"male" if f0 and lo <= f0 <= hi else "NOT MALE"} '
            f'(attempts {t.get("attempts_used", 1)})'
        )
    return 0


if __name__ == '__main__':
    sys.exit(main())
