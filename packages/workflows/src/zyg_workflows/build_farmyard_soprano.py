#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Register the soprano pitch/formant grid as an audition bench.

Ten settings of ONE voice, not ten voices: the operator picked this singer and
the remaining question is only how far to lower her and how much of that the
formants should follow. Each card plays the treated voice alone, the treated
song, and the untouched original for reference.
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

JOB = os.path.join(_HERE, 'output/kidsmusic/0fc29420eb5a')
SRC = os.path.join(JOB, 'soprano_grid')
ORIG = os.path.join(JOB, 'voice_sweep/v02_bright_soprano_master.mp3')
BENCH = os.path.join(_HERE, 'data/assets/voice_seeds/benches/farmyard_soprano')
LINES = [
    {
        'id': 'farmyard',
        'label': 'The Farmyard Sounds Song',
        'why': 'the picked soprano, lowered — a sung take, not a spoken clone',
        'text': 'A cow says moo in the green grass today.',
    }
] + VS.DEFAULT_LINES


def log(m):
    _zyg_log.info(f'[{time.strftime("%H:%M:%S")}] {m}')


def main():
    idx = json.load(open(os.path.join(SRC, 'index.json')))
    ver = {}
    vp = os.path.join(SRC, 'pitch_verification.json')
    if os.path.isfile(vp):
        v = json.load(open(vp))
        ver = {t['key']: t for t in v['takes']}
        orig = v.get('original', {})
    else:
        orig = {}
    os.makedirs(BENCH, exist_ok=True)
    shutil.copy2(ORIG, os.path.join(BENCH, 'original.mp3'))
    rows = []
    for t in idx['takes']:
        song = os.path.join(SRC, t['file'])
        if not os.path.isfile(song):
            continue
        key = t['key']
        stem = os.path.join(BENCH, f'{key}.wav')
        if not os.path.isfile(stem):
            sep = K.separate_vocal(song, os.path.join(BENCH, '_sep', key), log_fn=None)
            if not sep.get('ok'):
                log(f'{key}: separation failed')
                continue
            if not K._ff(['-i', sep['vocals'], '-ac', '1', '-ar', '24000', '-c:a', 'pcm_s16le', stem], log_fn=None):
                continue
        shutil.copy2(song, os.path.join(BENCH, f'{key}_song.mp3'))
        m = ver.get(key, {})
        T, F = t['drop_semitones'], t['formant_follow']
        rows.append(
            {
                'name': key,
                'display': f'Down {T} · formants follow {F}',
                'role': (
                    f'median {m.get("med", "?")} Hz, p95 {m.get("p95", "?")} Hz, '
                    f'{m.get("over500", "?")}% of voiced time over 500 Hz'
                ),
                'wav': stem,
                'seed_label': 'the voice (isolated)',
                'song_mp3': os.path.join(BENCH, f'{key}_song.mp3'),
                'extras': [{'label': 'the untouched original', 'path': os.path.join(BENCH, 'original.mp3')}],
                'gender': 'f',
                'age_class': 'adult_female',
                'bench': 'farmyard_soprano',
                'family': 'ace_step',
                'drop_semitones': T,
                'formant_follow': F,
                'pitch_median_hz': m.get('med'),
                'pitch_p95_hz': m.get('p95'),
                'pct_voiced_over_500hz': m.get('over500'),
                'reference_only': True,
                'note': (
                    f'The picked bright-soprano take with the vocal pitch lowered '
                    f'{T} semitones while the formants follow only {F}, so she '
                    f'reads as the same woman singing lower rather than as a '
                    f'larger one. Backing transposed the full {T} to stay in tune. '
                    f'Original: median {orig.get("med", "?")} Hz, '
                    f'{orig.get("over500", "?")}% over 500 Hz. Audition only.'
                ),
            }
        )
        log(f'{key}: registered')
    shutil.rmtree(os.path.join(BENCH, '_sep'), ignore_errors=True)
    man = {
        'purpose': 'One picked soprano at ten pitch/formant settings — audition only',
        'bench': 'farmyard_soprano',
        'built': time.strftime('%Y-%m-%d'),
        'source': 'voice_sweep/v02_bright_soprano_master.mp3',
        'measured_on': 'librosa.pyin pitch track of each separated vocal stem',
        'how_to_read': 'The operator picked this singer twice and asked only that she stop being '
        'high "at moments". A pitch TRACK (not the medians quoted earlier, which '
        'cannot see a moment) found the fault: median 409 Hz but p95 600 Hz, a '
        "peak of 1158 Hz (D6, an octave over the tune's top note) and 24.5% of "
        'voiced time above 500 Hz. The 3.5-5.5 kHz band measures LOW, so this is '
        'the fundamental and not a shrill EQ. Two earlier judgements bracket the '
        'cure: formants held at -4 sounded unnatural, formants following fully at '
        '-5 sounded male -- so formant follow is a separate axis here, built by '
        'chaining a resample (moves both) with a formant-preserved shift (moves '
        'pitch only). Drop 5 is where time-over-500 Hz collapses from 24.5% to '
        '0.2%; drops of 6 and 7 buy little more pitch relief and cost warmth. '
        'Pick the FORMANT column by ear. Note the reported peak is the least '
        'reliable figure -- pyin octave-doubles on a few frames, which is why '
        'p95 and the over-500 fraction are the ranking columns.',
        'voices': rows,
    }
    json.dump(man, open(os.path.join(BENCH, 'manifest.json'), 'w', encoding='utf-8'), indent=1, ensure_ascii=False)
    log(f'wrote {len(rows)} rows')
    return 0


if __name__ == '__main__':
    sys.exit(main())
