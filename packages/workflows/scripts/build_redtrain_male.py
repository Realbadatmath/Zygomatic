#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Register the Red Train male takes the operator kept (KEEP) as an audition bench in the Voices tab.

Same contract as build_farmyard_natural.py and build_farmyard_singers.py: a
manifest under voice_seeds/benches/, picked up by voice_studio._load_bench_voices()
on the next kanban-server start. No code change — a bench is fully described by
its manifest.

Two clips per row, because "is this a male voice?" and "does this male voice
carry the song?" are different questions: the isolated vocal stem is the seed,
and the mastered take is offered beside it.

reference_only stays TRUE on every row, for the same reason as both farmyard
benches: these are SUNG ACE-Step takes, not clonable voice-bank seeds. What
actually ships is the pair (caption, seed) carried on the row, against the plan
at output/kidsmusic/1ba342d5cd75/song.json.

The ids are prefixed `rt_` rather than reusing the bare sweep keys: these land in
one flat VOICES dict beside ~290 others, and `m01_warm_control` says nothing
about which song it came from when it turns up in a picker.
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

SRC = os.path.join(_HERE, 'output/kidsmusic/1ba342d5cd75/male_voices')
BENCH = os.path.join(_HERE, 'data/assets/voice_seeds/benches/redtrain_male')
# Pruned 2026-09-10: the operator kept these three by ear and removed the other
# seven from the library. Their takes stay in SRC; a rerun registers only these.
# m01 is the kids-music default male voice (kids_music_theory.SINGERS).
KEEP = ('m01_warm_control', 'm05_playful_cartoon', 'm06_folk_storyteller')
LINES = [
    {
        'id': 'redtrain',
        'label': 'The Red Train to the Sea (sung take)',
        'why': 'a sung ACE-Step take, not a spoken clone — the words are the song',
        'text': 'Little red train starts to go, toot toot.',
    }
] + VS.DEFAULT_LINES


def log(m):
    _zyg_log.info(f'[{time.strftime("%H:%M:%S")}] {m}')


def main():
    idx = json.load(open(os.path.join(SRC, 'index.json')))
    os.makedirs(BENCH, exist_ok=True)
    rows = []
    for t in idx['takes']:
        key = t['key']
        if key not in KEEP:
            continue
        song = os.path.join(SRC, t.get('master') or f'{key}.mp3')
        if not os.path.isfile(song):
            log(f'{key}: missing — skipped')
            continue
        vid = f'rt_{key}'
        stem_wav = os.path.join(BENCH, f'{vid}.wav')
        if not os.path.isfile(stem_wav):
            sep = K.separate_vocal(song, os.path.join(BENCH, '_sep', vid), log_fn=None)
            if not sep.get('ok'):
                log(f'{key}: separation failed — {sep.get("error")}')
                continue
            if not K._ff(['-i', sep['vocals'], '-ac', '1', '-ar', '24000', '-c:a', 'pcm_s16le', stem_wav], log_fn=None):
                log(f'{key}: stem convert failed')
                continue
        shutil.copy2(song, os.path.join(BENCH, f'{vid}_song.mp3'))
        m = VS.measure(stem_wav, age_class='adult_male')
        g = t.get('gate') or {}
        sc = t.get('song_check') or {}
        tries = t.get('attempts_used') or len([a for a in (t.get('attempts') or []) if a.get('f0') is not None]) or 1
        how = (
            'a2a on the melody pitch-shifted -12 semitones — this caption '
            'measured 292-334 Hz on seven seeds and never dropped the octave'
            if str(t.get('reseed', '')).startswith('replaced_via_melody')
            else f'a2a on the score render at denoise 0.45, {tries} seed(s) to land in the male band'
        )
        rows.append(
            {
                'name': vid,
                'display': t['display'],
                'role': t.get('why', ''),
                'wav': stem_wav,
                'seed_label': 'the voice (isolated)',
                'song_mp3': os.path.join(BENCH, f'{vid}_song.mp3'),
                'gender': 'm',
                'age_class': 'adult_male',
                'bench': 'redtrain_male',
                'family': 'ace_step',
                'ace_caption': t['caption'],
                'ace_seed': t['seed'],
                'conditioning': how,
                'seeds_tried': tries,
                # From sung_pitch (RMVPE) on the separated stem, via
                # kids_music_service.gate_singer_age — the meter the male band is
                # being RE-measured on, not the Praat one it was set on.
                'sung_f0_median_hz': g.get('f0_median_hz'),
                'sung_f0_p10_hz': g.get('f0_p10_hz'),
                'sung_f0_p90_hz': g.get('f0_p90_hz'),
                'vocal_over_mix_db': g.get('vocal_over_mix_db'),
                'song_key': sc.get('detected_key'),
                'song_bpm': sc.get('detected_bpm'),
                # voice_qc's Praat figure on the stem. Recorded, NOT ranked on: the
                # meter is SPEECH-calibrated and this is singing, which is the whole
                # reason gate_singer_age stopped using it on 2026-09-06.
                'stem_f0_hz_UNRELIABLE': m.get('f0_hz'),
                'reference_only': True,
                'note': (
                    f'ACE-Step sung take on "The Red Train to the Sea" '
                    f'(D major, 117 bpm). Reproduce with caption '
                    f'"{t["caption"]}" at seed {t["seed"]}, {how}. '
                    f'Audition only — not a clonable voice-bank seed. Wholly '
                    f'synthetic: no human was recorded.'
                ),
            }
        )
        log(f'{key}: registered as {vid}')
    shutil.rmtree(os.path.join(BENCH, '_sep'), ignore_errors=True)

    man = {
        'purpose': 'Three male singers kept, by ear, from ten auditioned on The '
        'Red Train to the Sea — audition only, see how_to_read',
        'bench': 'redtrain_male',
        'built': time.strftime('%Y-%m-%d'),
        'source_song': 'output/kidsmusic/1ba342d5cd75 (The Red Train to the Sea)',
        'measured_on': 'the separated vocal stem of each mastered take; the sung '
        'figures come from kids_music_service.gate_singer_age '
        '(RMVPE), the stem_f0_hz_UNRELIABLE figure from voice_qc',
        'how_to_read': 'Every take is the SAME song — same melody, lyrics, D major, 117 bpm '
        'and arrangement, through the melody-conditioned ACE-Step graph at '
        'denoise 0.45, mastered to -14 LUFS so they compare at equal '
        'loudness. Only the singer clause in the caption and the seed differ. '
        'All ten auditioned takes were verified back as D major (exact) at 117.5 bpm before '
        'they were registered. RANK BY EAR, and read the F0 as a MODE, not a '
        'ranking: across the 31 renders this bench was drawn from, ACE-Step '
        'landed either 194-250 Hz or 290-439 Hz and NOTHING in between, and '
        'which mode a take falls in is decided by the seed rather than by the '
        'caption — so a 194 Hz take is not "more male" than a 250 Hz one, '
        'they are the same mode. `seeds_tried` is the honest difficulty '
        'column: an arm that landed first time asks for the low octave, one '
        'that needed five or six was fighting for it. Every row carries the '
        'pair (caption, seed) that reproduces it exactly.',
        'test_lines': LINES,
        'voices': rows,
    }
    with open(os.path.join(BENCH, 'manifest.json'), 'w', encoding='utf-8') as f:
        json.dump(man, f, indent=1, ensure_ascii=False)
    log(f'wrote {len(rows)} rows -> {BENCH}/manifest.json')
    return 0 if len(rows) == len(KEEP) else 1


if __name__ == '__main__':
    sys.exit(main())
