#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Register the natural-register voices as an audition bench.

Same contract as build_farmyard_singers.py: a manifest under
voice_seeds/benches/, picked up by _load_bench_voices() on restart.

Each row auditions from three clips -- the isolated voice, the finished song,
and the untreated take it was made from -- because the operator's question here
is partly "is this natural?", and the raw take is the thing the treatment has to
be judged against.

reference_only stays true on every row for the same reason as the first bench:
these are SUNG ACE-Step takes, not clonable voice-bank seeds. What ships is the
caption, the seed and the -5 semitone treatment, all carried on the row.
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

SRC = os.path.join(_HERE, 'output/kidsmusic/0fc29420eb5a/natural_voices')
BENCH = os.path.join(_HERE, 'data/assets/voice_seeds/benches/farmyard_natural')
LINES = [
    {
        'id': 'farmyard',
        'label': 'The Farmyard Sounds Song (sung take)',
        'why': 'a sung ACE-Step take, lowered 5 semitones — not a spoken clone',
        'text': 'A cow says moo in the green grass today.',
    }
] + VS.DEFAULT_LINES


def log(m):
    _zyg_log.info(f'[{time.strftime("%H:%M:%S")}] {m}')


def main():
    idx = json.load(open(os.path.join(SRC, 'index.json')))
    os.makedirs(BENCH, exist_ok=True)
    rows = []
    for v in idx['voices']:
        song = os.path.join(SRC, v['file'])
        raw = os.path.join(SRC, v['raw_file'])
        if not os.path.isfile(song):
            log(f'{v["key"]}: missing — skipped')
            continue
        stem_wav = os.path.join(BENCH, f'{v["key"]}.wav')
        if not os.path.isfile(stem_wav):
            sep = K.separate_vocal(song, os.path.join(BENCH, '_sep', v['key']), log_fn=None)
            if not sep.get('ok'):
                log(f'{v["key"]}: separation failed — {sep.get("error")}')
                continue
            if not K._ff(['-i', sep['vocals'], '-ac', '1', '-ar', '24000', '-c:a', 'pcm_s16le', stem_wav], log_fn=None):
                log(f'{v["key"]}: stem convert failed')
                continue
        shutil.copy2(song, os.path.join(BENCH, f'{v["key"]}_song.mp3'))
        if os.path.isfile(raw):
            shutil.copy2(raw, os.path.join(BENCH, f'{v["key"]}_raw.mp3'))
        m = VS.measure(stem_wav, age_class='adult_female')
        rows.append(
            {
                'name': v['key'],
                'display': v['display'],
                'role': v['why'],
                'wav': stem_wav,
                'seed_label': 'the voice (isolated)',
                'song_mp3': os.path.join(BENCH, f'{v["key"]}_song.mp3'),
                'extras': [{'label': 'before lowering (raw take)', 'path': os.path.join(BENCH, f'{v["key"]}_raw.mp3')}],
                'gender': 'f',
                'age_class': 'adult_female',
                'bench': 'farmyard_natural',
                'family': 'ace_step',
                'ace_caption': v['caption'],
                'ace_seed': v['seed'],
                'semitones_down': v['semitones_down'],
                'treatment': 'rubberband pitch down, formants moving WITH the pitch',
                # Recorded, NOT used to rank: this meter failed calibration on sung
                # mixes (see the farmyard voice-sweep memory). The shift itself was
                # verified spectrally at -5.00 on all ten.
                'stem_f0_hz_UNRELIABLE': m.get('f0_hz'),
                'reference_only': True,
                'note': (
                    f'ACE-Step sung take lowered {v["semitones_down"]} semitones with '
                    f'the formants moving with the pitch, so the singer reads as a '
                    f'larger woman rather than a processed small one. Reproduce with '
                    f'caption "{v["caption"]}" at seed {v["seed"]}. Audition only — '
                    f'not a clonable voice-bank seed. Wholly synthetic: no human '
                    f'was recorded.'
                ),
            }
        )
        log(f'{v["key"]}: registered')
    shutil.rmtree(os.path.join(BENCH, '_sep'), ignore_errors=True)
    man = {
        'purpose': 'Ten natural-register female singers — lowered 5 semitones, audition only',
        'bench': 'farmyard_natural',
        'built': time.strftime('%Y-%m-%d'),
        'source_song': 'output/kidsmusic/0fc29420eb5a',
        'measured_on': 'the separated stem of each lowered take',
        'how_to_read': 'Built after the operator picked "bright soprano" but found it too high '
        'and not natural. Two changes: the captions drop soprano/bright/light in '
        'favour of natural, chest, mezzo, alto; and the lowering lets the FORMANTS '
        'travel with the pitch instead of holding them, so the singer becomes a '
        'genuinely larger woman rather than a small one pitched down — that '
        'formant hold is what made the earlier -4 set sound synthetic. Every take '
        'was verified spectrally at exactly -5.00 semitones. Do NOT rank these on '
        'f0: the demucs+voice_qc meter failed calibration on sung mixes and the '
        'number is carried only as f0_hz_UNRELIABLE. Rank by ear; each card also '
        'plays the untreated take so the treatment can be judged.',
        'voices': rows,
    }
    with open(os.path.join(BENCH, 'manifest.json'), 'w', encoding='utf-8') as f:
        json.dump(man, f, indent=1, ensure_ascii=False)
    log(f'wrote {len(rows)} rows -> {BENCH}/manifest.json')
    return 0


if __name__ == '__main__':
    sys.exit(main())
