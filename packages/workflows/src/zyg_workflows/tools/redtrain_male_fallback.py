# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Last resort for a male caption that will not drop the octave on any seed.

Some captions never win the coin flip. m02_bright_tenor measured 292-334 Hz on
SEVEN seeds, four of them within 3 Hz of 293.66 = D4 -- the song's own tonic.
That is the tell: those takes are singing the melody exactly where it was
written (D4-D5, a female tessitura) rather than an octave below it, and
"bright, light tenor" never asks for the drop.

For those arms the octave is moved in the CONDITIONING instead of hoped for in
the sampler: the same a2a graph, the same caption, the same seed, on a melody
pitch-shifted down 12 semitones. That is what a man actually does with a song
written for a woman -- the same tune, an octave lower -- and the probe measured
it at 250.2 Hz on the very caption that would not budge.

The cost is real and is checked, not assumed: the conditioning carries the
ACCOMPANIMENT down an octave too, so every take promoted here is re-measured
with gate_audio and the detected key and tempo are written onto the row. A take
that comes back in the wrong key is not the same song and does not ship.
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

sys.path.insert(0, os.path.join(CREWS, 'tools'))
import rubberband_r3 as RB  # noqa: E402

_zyg_log = _zyg_logging.getLogger(__name__)


JOB = os.path.join(CREWS, 'output/kidsmusic/1ba342d5cd75')
OUT = os.path.join(JOB, 'male_voices')
ATT = os.path.join(OUT, '_attempts')
DOWN = -12
TRIES = 4


def log(m):
    _zyg_log.info(f'[{time.strftime("%H:%M:%S")}] {m}')


def lowered_melody():
    dst = os.path.join(OUT, f'_melody_down{abs(DOWN)}.wav')
    if not os.path.isfile(dst):
        src = os.path.join(OUT, '_melody.wav')
        y, sr = RB._decode(src)
        out, _ver = RB.shift(y, sr, semitones=float(DOWN), formant='follow')
        RB._encode(out, sr, dst)
        log(f'melody lowered {DOWN} st -> {os.path.basename(dst)}')
    return dst


def master_of(src, dst):
    fed, _tr = K.trim_tail(src, os.path.join(ATT, '_trim.wav'), log_fn=None)
    pre = K.prelevel(fed, os.path.join(ATT, '_pre.wav'), target_lufs=-14.0, tp_db=-1.5, log_fn=None)
    try:
        from zyg_workflows import audio_mix

        mw = os.path.join(ATT, '_master.wav')
        if audio_mix.master(pre, mw, i=-14.0, tp=-1.0, log_fn=None, result={}):
            K._mp3(mw, dst, log_fn=None, br='256k')
    except Exception as e:  # noqa: BLE001
        log(f'    master failed: {type(e).__name__}: {e}')


def song_survived(path, plan):
    """Same key, same tempo? A lowered conditioning source could move both."""
    g = K.gate_audio(path, plan, leg='render', want_clap=False, log_fn=None)
    c = g.get('checks') or {}
    return {
        'detected_key': c.get('detected_key'),
        'key_match': c.get('key_match'),
        'detected_bpm': c.get('detected_bpm'),
        'bpm_error': c.get('bpm_error'),
        'bpm_relation': c.get('bpm_relation'),
    }


def main():
    idx = json.load(open(os.path.join(OUT, 'index.json')))
    plan = json.load(open(os.path.join(JOB, 'song.json')))
    male = T.SINGERS['adult_male']
    lo, hi = male['band']
    stuck = [
        t
        for t in idx['takes']
        if not ((t.get('gate') or {}).get('f0_median_hz') is not None and lo <= (t['gate']['f0_median_hz']) <= hi)
    ]
    if not stuck:
        log('every arm is already male — nothing to do')
        return 0
    log(f'{len(stuck)} arm(s) still not male: ' + ', '.join(t['key'] for t in stuck))
    if not K.ace_available():
        raise SystemExit('ACE-Step leg unavailable')
    mel = lowered_melody()

    for t in stuck:
        key = t['key']
        log(f'--- {key}: a2a on the {DOWN} st melody')
        T.SINGERS[key] = dict(male, label=key, caption=t['caption'])
        plan['brief']['singer'] = key
        rng = random.Random(f'redtrain-male-down-{key}')
        seeds = [t['attempts'][0]['seed']] + [rng.randint(0, 2**31 - 1) for _ in range(TRIES - 1)]
        won = None
        tried = []
        for n, seed in enumerate(seeds, 1):
            raw = os.path.join(ATT, f'{key}_down{abs(DOWN)}_s{seed}.mp3')
            rec = {}
            got = (
                raw
                if os.path.isfile(raw) and os.path.getsize(raw) > 10_000
                else K.ace_render(plan, raw, seed=seed, melody_wav=mel, log_fn=None, info=rec)
            )
            if not got:
                log(f'    seed {seed}: render failed — {rec.get("reason")}')
                tried.append({'seed': seed, 'f0': None, 'kept': False})
                continue
            m = os.path.join(ATT, f'{key}_down{abs(DOWN)}_s{seed}_master.mp3')
            master_of(got, m)
            probe = m if os.path.isfile(m) else got
            g = K.gate_singer_age(probe, plan, log_fn=None)
            f0 = (g.get('checks') or {}).get('f0_median_hz')
            ok = f0 is not None and lo <= f0 <= hi
            log(f'    attempt {n}  seed {seed}: {f0} Hz {"MALE — keeping" if ok else "still high"}')
            tried.append({'seed': seed, 'f0': f0, 'kept': ok})
            if ok:
                won = (seed, got, m, g)
                break

        t.setdefault('attempts', []).extend([dict(a, conditioning=f'melody {DOWN} st') for a in tried])
        if not won:
            t['reseed'] = 'exhausted_both'
            log(f'    {key}: still not male after the lowered conditioning too')
            continue
        seed, raw, m, g = won
        survived = song_survived(m if os.path.isfile(m) else raw, plan)
        log(
            f'    key {survived["detected_key"]} ({survived["key_match"]}), '
            f'{survived["detected_bpm"]} bpm ({survived["bpm_relation"]})'
        )
        if survived.get('key_match') not in ('exact', 'relative', 'same'):
            t['reseed'] = 'rejected_key_moved'
            t['song_check'] = survived
            log(f'    {key}: REJECTED — the lowered conditioning moved the key')
            continue
        shutil.copy2(raw, os.path.join(OUT, f'{key}.mp3'))
        if os.path.isfile(m):
            shutil.copy2(m, os.path.join(OUT, f'{key}_master.mp3'))
        c = g.get('checks') or {}
        t.update(
            {
                'seed': seed,
                'reseed': f'replaced_via_melody{DOWN}',
                'conditioning': f'a2a on the melody pitch-shifted {DOWN} semitones',
                'master': f'{key}_master.mp3',
                'song_check': survived,
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

    json.dump(idx, open(os.path.join(OUT, 'index.json'), 'w'), indent=1)
    for tmp in ('_trim.wav', '_pre.wav', '_master.wav'):
        try:
            os.remove(os.path.join(ATT, tmp))
        except OSError as _exc:
            _zyg_log.debug('intermediate take cleanup skipped: %s', _exc)
    log('=== FINAL ===')
    for t in idx['takes']:
        f0 = (t.get('gate') or {}).get('f0_median_hz')
        log(f'{t["key"]:22s} F0={f0} {"male" if f0 and lo <= f0 <= hi else "NOT MALE"}  {t.get("reseed", "")}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
