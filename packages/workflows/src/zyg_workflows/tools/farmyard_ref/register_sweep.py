# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Ten takes of The Farmyard Sounds Song at LOWER singing registers.

WHY THE FIRST SWEEP CAME OUT SHRILL, measured rather than guessed. The composed
melody sits D4-D5 with a median of A4 = 440 Hz, because the `preschool` age band
is C4-D5 -- a four-to-six-year-old's sing-along tessitura. The ACE leg is
melody-conditioned (a2a, denoise 0.45), so ACE-Step follows that tune into a
child's register and sings it with an adult-female caption. The measured stem
medians of 361-416 Hz are exactly what a D4-D5 tune produces. The caption was
never the lever; the score is.

So this sweep moves the SCORE and holds the seed fixed, which is the opposite of
the first one. One seed for all ten means a register difference cannot be
confused with the seed noise that dominated the caption sweep.

TWO WAYS DOWN, because they are musically different:
  all N   transpose melody, chords and bass together -- the key changes, the
          harmony is intact, and the whole arrangement darkens.
  mel -12 drop only the tune an octave, leaving the accompaniment where it is.
          This is what an adult actually does with a nursery tune, and it stays
          consonant because an octave is the one interval that cannot clash.
A partial transpose of the melody alone by anything BUT an octave would put the
tune in a different key from its own chords, so those combinations are not offered.

THE BASS IS GUARDED. The tuba already sits D2-B2; -12 would put it at D1, under
the useful range of the patch and of most speakers. Any transpose that drops the
bass below A1 gets an octave back, so a low ladder step darkens the tune without
turning the bottom into mud.
"""

import logging as _zyg_logging
import copy
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
OUT = os.path.join(JOB, 'register_sweep')

# Held fixed across all ten: the register is the only thing being asked about,
# and the caption sweep already established that the seed moves the voice more
# than a caption does.
SEED = 1303347561

LOW_WARM = 'clear adult female lead vocal, warm low chest register, relaxed alto, grown-up woman singing'
NURSERY_LOW = 'gentle adult female lead vocal, low warm nursery teacher tone, calm grown-up woman singing softly'
SHIPPED = 'clear adult female lead vocal, warm friendly grown-up woman singing'

NOTE = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']
# ACE-Step is told the key; transposing the score without transposing this would
# hand it a caption that disagrees with the audio it is conditioned on.
KEYSCALE = {
    0: 'D major',
    -2: 'C major',
    -3: 'B major',
    -4: 'A# major',
    -5: 'A major',
    -7: 'G major',
    -9: 'F major',
    -12: 'D major',
}

# (name, semitones on everything, melody-only octave drop, caption, why)
TAKES = [
    ('r00_control', 0, False, SHIPPED, 'unchanged — the anchor the ladder is read against'),
    ('r03_down3', -3, False, LOW_WARM, 'whole song down 3 (B major)'),
    ('r05_down5', -5, False, LOW_WARM, 'whole song down 5 (A major)'),
    ('r05_down5_nurse', -5, False, NURSERY_LOW, 'down 5, softer caption'),
    ('r07_down7', -7, False, LOW_WARM, 'whole song down 7 (G major)'),
    ('r07_down7_nurse', -7, False, NURSERY_LOW, 'down 7, softer caption'),
    ('r09_down9', -9, False, LOW_WARM, 'whole song down 9 (F major)'),
    ('r12_down12', -12, False, LOW_WARM, 'whole song down an octave, bass guarded'),
    ('m12_mel_octave', 0, True, LOW_WARM, 'tune down an octave, accompaniment untouched — the classic fix'),
    ('m12_mel_nurse', 0, True, NURSERY_LOW, 'tune down an octave, softer caption'),
]


def log(msg):
    _zyg_log.info(f'[{time.strftime("%H:%M:%S")}] {msg}')


def transpose(plan, semis, mel_octave):
    """A copy of the plan moved down. Percussion is channel 9 and never moves."""
    p = copy.deepcopy(plan)
    mel_shift = semis - (12 if mel_octave else 0)
    for n in p['melody']:
        n['p'] += mel_shift
    if semis:
        for c in p['chords']:
            c['midi'] = [m + semis for m in c['midi']]
            c['bass'] += semis
        # Bass guard: an octave back if the transpose pushed it under A1.
        if p['chords'] and min(c['bass'] for c in p['chords']) < 33:
            for c in p['chords']:
                c['bass'] += 12
            log('    bass guard: +12 back (would have gone under A1)')
        lo = min(m for c in p['chords'] for m in c['midi'])
        if lo < 40:
            for c in p['chords']:
                c['midi'] = [m + 12 for m in c['midi']]
            log('    pad guard: +12 back (chord tones under E2)')
    pit = [n['p'] for n in p['melody']]
    p['range'] = {'lo': min(pit), 'hi': max(pit)}
    if semis:
        tonic_pc = (p['key']['tonic_pc'] + semis) % 12
        p['key'] = dict(p['key'])
        p['key']['tonic'] = NOTE[tonic_pc]
        p['key']['tonic_pc'] = tonic_pc
        p['key']['label'] = f'{NOTE[tonic_pc]} {p["key"]["mode"].replace("_", " ")}'
        p['key']['ace_keyscale'] = KEYSCALE.get(semis, p['key']['ace_keyscale'])
    return p


def midi_stats(plan):
    pit = sorted(n['p'] for n in plan['melody'])
    med = pit[len(pit) // 2]

    def hz(m):
        return 440.0 * 2 ** ((m - 69) / 12)

    def nm(m):
        return f'{NOTE[m % 12]}{m // 12 - 1}'

    return {
        'lo_midi': pit[0],
        'hi_midi': pit[-1],
        'median_midi': med,
        'lo': nm(pit[0]),
        'hi': nm(pit[-1]),
        'median': nm(med),
        'median_hz': round(hz(med), 1),
    }


def main():
    os.makedirs(OUT, exist_ok=True)
    base = json.load(open(os.path.join(JOB, 'song.json')))
    if not K.ace_available():
        raise SystemExit('ACE-Step leg unavailable')

    band = T.SINGERS['adult_female']['band']
    results = []
    for i, (key, semis, mel_oct, caption, why) in enumerate(TAKES, 1):
        log(f'--- {i}/10  {key}  ({why})')
        plan = transpose(base, semis, mel_oct)
        st = midi_stats(plan)
        log(
            f'    tune {st["lo"]}-{st["hi"]}, median {st["median"]} '
            f'({st["median_hz"]:.0f} Hz)  key {plan["key"]["ace_keyscale"]}'
        )

        # The conditioning audio has to be REBUILT from the transposed score --
        # this is the whole mechanism; reusing the original wav would move the
        # caption and change nothing a model can hear.
        mid = K.write_midi(plan, os.path.join(OUT, f'{key}.mid'), log_fn=log)
        cond = os.path.join(OUT, f'_{key}_cond.wav')
        if not K.render_soundfont(mid, cond, log_fn=log):
            log('    soundfont render failed — skipped')
            continue

        T.SINGERS[key] = {
            'label': key,
            'age_class': 'adult_female',
            'caption': caption,
            'band': band,
            'measured': band,
            'n': 0,
        }
        plan['brief']['singer'] = key

        take = os.path.join(OUT, f'{key}.mp3')
        master = os.path.join(OUT, f'{key}_master.mp3')
        rec = {}
        got = K.ace_render(plan, take, seed=SEED, melody_wav=cond, log_fn=log, info=rec, should_abort=lambda: False)
        row = {
            'key': key,
            'why': why,
            'semitones': semis,
            'melody_octave_down': mel_oct,
            'caption': caption,
            'seed': SEED,
            'keyscale': plan['key']['ace_keyscale'],
            'score': st,
            'ok': bool(got),
            'reason': rec.get('reason', ''),
        }

        if got:
            fed, _ = K.trim_tail(got, os.path.join(OUT, '_trim.wav'), log_fn=log)
            pre = K.prelevel(fed, os.path.join(OUT, '_pre.wav'), target_lufs=-14.0, tp_db=-1.5, log_fn=log)
            norm = {}
            try:
                from zyg_workflows import audio_mix

                mw = os.path.join(OUT, '_master.wav')
                if audio_mix.master(pre, mw, i=-14.0, tp=-1.0, log_fn=log, result=norm):
                    K._mp3(mw, master, log_fn=log, br='256k')
            except Exception as e:  # noqa: BLE001
                log(f'    master failed: {type(e).__name__}: {e}')
            g = K.gate_singer_age(master if os.path.isfile(master) else got, plan, log_fn=log)
            row['gate'] = {
                'status': g['status'],
                'detail': g['detail'],
                'f0_hz': (g.get('checks') or {}).get('f0_median_hz'),
                'vocal_over_mix_db': ((g.get('checks') or {}).get('separation') or {}).get('ratio_db'),
            }
            row['master'] = os.path.basename(master) if os.path.isfile(master) else ''
            log(
                f'    SUNG F0 {row["gate"]["f0_hz"]} Hz '
                f'(score median {st["median_hz"]:.0f} Hz)  [{row["gate"]["status"]}]'
            )
        else:
            log(f'    FAILED: {row["reason"]}')
        results.append(row)
        json.dump(
            {
                'song': 'The Farmyard Sounds Song',
                'job': '0fc29420eb5a',
                'seed_fixed': SEED,
                'cast_band_hz': list(band),
                'takes': results,
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
    log('=== SUMMARY (score median -> sung F0) ===')
    for r in results:
        g = r.get('gate') or {}
        log(
            f'{r["key"]:18s} {r["score"]["median"]:>4s} '
            f'{r["score"]["median_hz"]:6.0f} Hz -> sung {str(g.get("f0_hz")):>6s} Hz '
            f'[{g.get("status", "-")}]'
        )
    return 0


if __name__ == '__main__':
    sys.exit(main())
