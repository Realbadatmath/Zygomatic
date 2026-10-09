#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Register the Farmyard Sounds voice sweep as an audition bench.

The Voices tab loads any bench under voice_seeds/benches/<bench>/ straight from
its manifest, so this is a builder run and not a code change -- the same
contract build_cast_voices.py uses.

WHAT A ROW IS HERE, AND WHY IT IS THE STEM AND NOT THE SONG. A bench row's `wav`
is two things at once: the clip the tab auditions, and the reference the render
loop would clone from. Registering the full mixes would make the first work and
the second nonsense -- IndexTTS2 handed a clarinet, a tuba and a nylon guitar
does not return a voice. So the stem is what gets registered, and the mastered
song sits beside it in the same folder under _song.mp3 for context.

Separating also removes a real bias from the comparison: measured across the ten
takes the vocal sits between -2.4 and -8.9 dB over the backing, so auditioning
the mixes would rank them partly on how far ACE-Step happened to bury the singer
rather than on the voice.

REFERENCE_ONLY IS SET ON EVERY ROW, and it is not a quality judgement. These are
ACE-Step song vocals, not voice-bank seeds: nothing in this repo can clone a
singing take into a speaking voice, and singable_voices() is the server-side
vocabulary for what may reach published audio. A row that sat there unflagged
would offer these to the first consumer of that list as if they were bank
voices. What actually ships from this bench is the RECIPE -- the caption and the
seed, both carried on every row -- fed back to kids_music_service.
"""

import json
import logging as _zyg_logging
import os
import shutil
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
os.chdir(_HERE)

from zyg_workflows import kids_music_service as K  # noqa: E402
from zyg_workflows import voice_studio as VS  # noqa: E402

_zyg_log = _zyg_logging.getLogger(__name__)

SWEEP = os.path.join(_HERE, 'output/kidsmusic/0fc29420eb5a/voice_sweep')
BENCH = os.path.join(_HERE, 'data/assets/voice_seeds/benches/farmyard_singers')

# What the operator is actually choosing between, in plain words. Keyed on the
# sweep's take name; the caption and seed come from the sweep's own index.json
# so this file cannot drift from what was rendered.
EDITORIAL = {
    'v01_warm_control': (
        'Warm — the current voice',
        'The shipped caption, re-rolled. The anchor: every other row is a step away from this one.',
    ),
    'v02_bright_soprano': ('Bright soprano', 'Light and forward, the highest-sitting of the clear tones.'),
    'v03_rich_mezzo': ('Rich mezzo', 'The lowest passing take — rounded, closest to a speaking register.'),
    'v04_soft_breathy': (
        'Soft & breathy',
        'Close-mic, gentle. Highest F0 of the ten and the second most forward in the mix.',
    ),
    'v05_playful_cartoon': (
        'Playful cartoon',
        'Animated and characterful. The most forward vocal of the ten — the words cut through the band hardest.',
    ),
    'v06_folk_storyteller': (
        'Folk storyteller',
        'Plain and unaffected. Sits furthest BACK in the mix of the ten, which is the thing to listen for.',
    ),
    'v07_theatre_belt': ('Theatre belt', 'Projected and confident, but the arrangement covers it.'),
    'v08_husky_alto': (
        'Husky alto  [failed the cast gate]',
        'Landed at 293.5 Hz, inside the deliberate 285-295 Hz gap where '
        'the gate refuses to call a voice male or female. Kept so the '
        'edge of the instrument is audible, not because it is shippable.',
    ),
    'v09_nursery_teacher': ('Nursery teacher', 'Kind and calm; close to the control but softer in delivery.'),
    'v10_clean_pop': ('Clean pop', 'Polished and controlled, the most produced-sounding of the ten.'),
}

LINES = [
    {
        'id': 'farmyard',
        'label': 'The Farmyard Sounds Song (sung take)',
        'why': 'what this bench is: a sung ACE-Step take, not a spoken clone',
        'text': 'A cow says moo in the green grass today. A duck says quack and swims away to play.',
    }
] + VS.DEFAULT_LINES


def log(m):
    _zyg_log.info(f'[{time.strftime("%H:%M:%S")}] {m}')


def main():
    idx = json.load(open(os.path.join(SWEEP, 'index.json')))
    os.makedirs(BENCH, exist_ok=True)
    rows = []
    for t in idx['takes']:
        key = t['key']
        if not t.get('ok'):
            log(f'{key}: take failed to render — skipped')
            continue
        master = os.path.join(SWEEP, f'{key}_master.mp3')
        if not os.path.isfile(master):
            log(f'{key}: no master on disk — skipped')
            continue

        stem_wav = os.path.join(BENCH, f'{key}.wav')
        if not os.path.isfile(stem_wav):
            sep = K.separate_vocal(master, os.path.join(BENCH, '_sep', key), log_fn=log)
            if not sep.get('ok'):
                log(f'{key}: separation failed — {sep.get("error")} — skipped')
                continue
            # 24 kHz mono, matching every other seed in the bank: seed_chain
            # resamples from whatever it is given, and a 48 kHz stereo stem
            # would be the only row in the studio that is not already in the
            # shape the render chain wants.
            if not K._ff(['-i', sep['vocals'], '-ac', '1', '-ar', '24000', '-c:a', 'pcm_s16le', stem_wav], log_fn=log):
                log(f'{key}: could not convert the stem — skipped')
                continue
        shutil.copy2(master, os.path.join(BENCH, f'{key}_song.mp3'))

        m = VS.measure(stem_wav, age_class='adult_female')
        g = t.get('gate') or {}
        disp, role = EDITORIAL.get(key, (key, ''))
        rows.append(
            {
                'name': key,
                'display': disp,
                'role': role,
                'wav': stem_wav,
                # Both clips the card offers, named for the question each answers:
                # the stem is the voice on its own, the song is that voice against
                # the clarinet, tuba and nylon guitar it has to carry over.
                'seed_label': 'the voice (isolated)',
                'song_mp3': os.path.join(BENCH, f'{key}_song.mp3'),
                # The delivered fix. Generation cannot steer the sung register on
                # this graph (measured: transposing the score a full octave moved the
                # vocal 0 semitones), so the register is set afterwards, exactly,
                # with a formant-preserving downward shift.
                'extras': [{'label': 'lowered 4 semitones', 'path': os.path.join(BENCH, f'{key}_low4.mp3')}],
                'gender': 'f',
                'age_class': 'adult_female',
                'bench': 'farmyard_singers',
                'family': 'ace_step',
                # The recipe. This, not the wav, is what reproduces the voice.
                'ace_caption': t['caption'],
                'ace_seed': t['seed'],
                'ace_workflow': t.get('workflow', ''),
                'ace_denoise': t.get('a2a_denoise'),
                # Measured on the MIX by the shipping gate, during the sweep.
                'mix_f0_hz': g.get('f0_hz'),
                'mix_vocal_over_backing_db': g.get('vocal_over_mix_db'),
                'cast_gate': g.get('status'),
                'cast_gate_detail': g.get('detail', ''),
                # Measured again here, on the separated stem.
                'stem_f0_hz': m.get('f0_hz'),
                'stem_vtl_cm': m.get('vtl_cm'),
                'stem_verdict': m.get('verdict', ''),
                'reference_only': True,
                'note': (
                    f'ACE-Step sung take, not a voice-bank seed — audition only. '
                    f'Reproduce with caption "{t["caption"]}" at seed {t["seed"]} '
                    f'through kids_music_service. The full mastered song is '
                    f'{key}_song.mp3 beside this stem. Wholly synthetic: no human '
                    f'was recorded.'
                ),
            }
        )
        log(f'{key}: stem {m.get("f0_hz")} Hz  (mix {g.get("f0_hz")} Hz)')

    shutil.rmtree(os.path.join(BENCH, '_sep'), ignore_errors=True)
    man = {
        'purpose': 'Ten female singers auditioned on The Farmyard Sounds Song — audition only, see how_to_read',
        'bench': 'farmyard_singers',
        'built': time.strftime('%Y-%m-%d'),
        'source_song': 'output/kidsmusic/0fc29420eb5a (The Farmyard Sounds Song)',
        'measured_on': 'the separated vocal stem of each mastered take; the mix '
        'figures come from kids_music_service.gate_singer_age',
        'how_to_read': 'Every take is the SAME song — same melody, lyrics, key, tempo and '
        'arrangement, through the melody-conditioned ACE-Step graph at denoise '
        '0.45. Only the singer clause in the caption and the seed differ. '
        'Rank on what you hear, not on F0: six of the ten sit within 361-376 Hz, '
        'and re-rolling the control caption at its own original seed moved it '
        '298.5 -> 370.5 Hz, so the seed moves the voice further than most of '
        'these captions do and no single take can be attributed to its caption. '
        'The column that does separate them is mix_vocal_over_backing_db '
        '(-2.4 to -8.9 dB): how far the words cut through the band, which for a '
        'preschool song matters more than timbre. VTL is only estimable below '
        '300 Hz. Every row is reference_only because these are SUNG ACE-Step '
        'takes, not clonable voice-bank seeds — what ships is the caption and '
        'seed carried on each row.',
        'voices': rows,
    }
    with open(os.path.join(BENCH, 'manifest.json'), 'w', encoding='utf-8') as f:
        json.dump(man, f, indent=1, ensure_ascii=False)
    log(f'wrote {len(rows)} rows -> {BENCH}/manifest.json')
    return 0


if __name__ == '__main__':
    sys.exit(main())
