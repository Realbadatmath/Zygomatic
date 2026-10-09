# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""audio_shared: Makes, Hears, Capacity and Counting — the four sound bands."""

from __future__ import annotations

from .settings import (
    AMBIENCE,
    CLAP_ABSENT_MAX,
    CLAP_MIN,
    CLAP_NULL_MARGIN,
    COND_AMB,
    COND_JUDGE,
    COND_ONE,
    COND_SOUND,
    DISTANCE_PAIR,
    SOUNDS,
    SOUND_EXTRA,
)
from .fixtures import BASE_LABEL, BASE_PROMPT, LYRIC_80, LYRIC_RULE, PROBES, _probe

# ── Makes: 53 columns, one fixed prompt each ───────────────────────────────────────────
# CLAP is the screen; the OPERATOR decides. Both are recorded on the trial.
for _sid, (_lbl, _pr) in SOUNDS.items():
    _checks = [
        {'check': 'clap_label_min', 'label': _lbl, 'min': CLAP_MIN, 'margin': CLAP_NULL_MARGIN},
        {'check': 'operator', 'blind': True, 'question': f'Is this {_lbl}, and only that? yes/no'},
    ]
    _checks += SOUND_EXTRA.get(_sid, [])
    _ins = {'prompt': _pr} if _pr != 'PAIR' else {'prompt': 'PAIR', 'pair': dict(DISTANCE_PAIR)}
    PROBES.append(
        _probe(
            f'make_{_sid}',
            f'Makes: {_lbl}',
            [f'make_{_sid}'],
            _checks,
            cond=COND_AMB if _sid in AMBIENCE else COND_SOUND,
            inputs=_ins,
            state_note=(
                'the OPERATOR decides this column: yes needs a blind yes on all three seeds. '
                'clap_label_min is a SCREEN only — a render that fails CLAP is not played to '
                'the operator at all, and a render that passes CLAP can still be a no. The '
                'CLAP score and the null baseline are written on every trial so the screen '
                'itself can be audited (2026-09-27: correct 0.827, chroma-only 0.279, null 0.252).'
            ),
        )
    )

# ── Hears: the same 53 sounds recognised in a fixture recording ────────────────────────
# Mechanical: the true label must rank FIRST among all 53 labels. No model is asked whether a
# sound is "correct" — the defect-judge bench says it cannot be trusted with that.
for _sid, (_lbl, _pr) in SOUNDS.items():
    PROBES.append(
        _probe(
            f'hear_{_sid}',
            f'Hears: {_lbl}',
            [f'hear_{_sid}'],
            [{'check': 'clap_rank_max', 'label': _lbl, 'among': 'SOUND_LABELS', 'max': 1}],
            cond=dict(COND_ONE, repeats=1),
            inputs={
                'audio': f'capability_tests/fixtures/audio/sounds/{_sid}.wav',
                'task': 'What do you hear? Answer in a few words.',
            },
            fixture_key=f'sounds/{_sid}.wav',
            state_note=(
                'mechanical: the row embeds the fixture and ranks all 53 SOUND_LABELS; yes when '
                'the true label is first, partial when it is in the top 3, no otherwise. The '
                'open question "what do you hear?" is sent as well and the free-text answer is '
                'recorded on the trial for the operator to read, but it is NOT scored: a caption '
                'model that says "wood sounds" is neither right nor wrong. The fixture is '
                'unverified until the operator has listened once, and blocks this column until then.'
            ),
        )
    )

# ── Capacity: seven ladders whose answer is a COUNT ────────────────────────────────────
# The column is not a yes/no: it is the LAST RUNG THAT PASSED, in the unit named. Every rung
# runs at the same three seeds; a rung passes when every check passes on all three.
PROBES += [
    _probe(
        'acap_layers',
        'Capacity ladder: layers before the mix muddies',
        ['acap_layers'],
        [
            {'check': 'clap_rank_max', 'label': 'a creaking wooden door', 'among': 'SOUND_LABELS', 'max': 3},
            {
                'check': 'operator',
                'blind': True,
                'question': 'Can you still pick out the creaking wooden door in this mix? yes/no',
            },
            {'check': 'true_peak_max', 'max': -1.0},
        ],
        inputs={
            'fixture': 'capability_tests/fixtures/audio/layers/',
            'task': 'Mix the first N stems of capability_tests/fixtures/audio/layers/ in their numbered order, each at -12 dBFS peak, no processing beyond a sum and a -1 dBTP ceiling. Stem 02 (the door creak) is always included.',
        },
        cond=dict(COND_AMB, repeats=3),
        unit='count',
        ladder=[1, 2, 3, 5, 8, 12],
        state_note=(
            'the count = the largest rung where the door creak still ranks in the CLAP top 3 '
            'AND the operator hears it, on all three seeds. Stem 02 is in every rung, so the '
            'ladder measures MASKING and nothing else. CLAP ranking is the screen; the '
            'operator decides, because a rank can survive a mix a human can no longer read.'
        ),
    ),
    _probe(
        'acap_voices',
        'Capacity ladder: distinct voices held apart in one scene',
        ['acap_voices'],
        [
            {'check': 'speaker_count', 'n': 'RUNG'},
            {
                'check': 'operator',
                'blind': True,
                'question': 'Is every voice in this take audibly a different person? yes/no',
            },
            {'check': 'transcript_words_max', 'max': 200},
        ],
        inputs={
            'task': 'Render this fixed eight-line scene with N distinct voices, the lines dealt round-robin to the N voices in order, one take, no music, dry, 48 kHz mono.',
            'prompt': (
                'CORNELIS: The seam is open.\nJOOST: Which seam?\n'
                'ANNA: The one you tarred yesterday.\nJOOST: It held this morning.\n'
                'CORNELIS: It held because it was dry.\nANNA: The tide is coming.\n'
                'JOOST: I will fetch the oakum.\nCORNELIS: Fetch the mallet too.'
            ),
        },
        cond=dict(COND_AMB, repeats=3),
        unit='count',
        ladder=[1, 2, 3, 4, 6, 8],
        state_note=(
            'the count = the largest rung where pyannote counts exactly N speakers AND the '
            'operator hears N different people, on all three seeds. pyannote is mechanical '
            'and can be fooled by one voice with two deliveries, which is exactly the failure '
            'the operator catches — so BOTH must pass and the operator decides ties.'
        ),
    ),
    _probe(
        'acap_seconds',
        'Capacity ladder: seconds of coherent output',
        ['acap_seconds'],
        [
            {'check': 'duration_s', 'min': 'RUNG*0.9', 'max': 'RUNG*1.1'},
            {
                'check': 'clap_label_min',
                'label': 'a harbour ambience',
                'min': CLAP_MIN,
                'margin': CLAP_NULL_MARGIN,
                'window': 4,
                'note': 'every non-overlapping 4 s window must pass, not just the whole file',
            },
            {
                'check': 'operator',
                'blind': True,
                'question': 'Does this hold together for its whole length, with no loop, no drift and no collapse? yes/no',
            },
        ],
        inputs={'prompt': SOUNDS['harbour_ambience'][1]},
        cond=dict(COND_SOUND, repeats=3),
        unit='s',
        ladder=[4, 8, 16, 32, 64],
        state_note=(
            'the count = the longest rung, in SECONDS, where every 4 s window still passes the '
            'CLAP screen and the operator marks it coherent, on all three seeds. The operator '
            'is where it falls apart: a loop point and a slow drift both keep the CLAP score.'
        ),
    ),
    _probe(
        'acap_variations',
        'Capacity ladder: distinct variations of one sound',
        ['acap_variations'],
        [
            {'check': 'pairwise_audio_distinct', 'min': 0.15},
            {'check': 'clap_labels_all_min', 'labels': ['footsteps on wooden boards'], 'min': CLAP_MIN},
            {
                'check': 'operator',
                'blind': True,
                'question': 'Is every take in this set audibly a different performance of the same sound? yes/no',
            },
        ],
        inputs={'prompt': SOUNDS['footstep_wood'][1]},
        cond={
            'seeds': 'the first N of 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27, 28, 29, 30, 31, 32, 33, 34, 35, 36, 37, 38, 39, 40, 41, 42',
            'repeats': 1,
            'seconds': 4,
            'sample_rate_out': 48000,
            'channels': 1,
        },
        unit='count',
        ladder=[1, 2, 4, 8, 16, 32],
        state_note=(
            'the count = the largest rung where all N renders are still pairwise distinct '
            '(log-mel cosine distance >= 0.15) AND every one still passes the CLAP screen AND '
            'the operator hears N different performances. Repeats is 1 here because the rung '
            'IS the repeat set: rung N is N renders at N different seeds.'
        ),
    ),
    _probe(
        'acap_words',
        'Capacity ladder: words per take still intelligible',
        ['acap_words'],
        [
            {'check': 'wer_max', 'max': 0.10, 'against': 'the rung text, the first N words of LYRIC_80'},
            {'check': 'transcript_contains_terms', 'terms': ['tide', 'gate']},
            {
                'check': 'operator',
                'blind': True,
                'question': 'Is every word in this take intelligible on one listen, without reading along? yes/no',
            },
        ],
        inputs={'prompt': LYRIC_80, 'task': 'Render the first N words of this line as one take. ' + LYRIC_RULE},
        cond=dict(COND_SOUND, repeats=3, seconds=None),
        unit='count',
        ladder=[10, 20, 40, 80],
        state_note=(
            'the count = the WORD COUNT of the longest rung whose Whisper WER against the '
            'rung text stays <= 0.10 on all three seeds and which the operator marks '
            'intelligible. WER is the mechanical half and it decides the number; the '
            'operator catches the take that transcribes perfectly and still cannot be heard.'
        ),
    ),
    _probe(
        'acap_instruments',
        'Capacity ladder: instruments named and heard',
        ['acap_instruments'],
        [
            {'check': 'clap_labels_all_min', 'labels': 'RUNG_LABELS', 'min': 0.26},
            {
                'check': 'operator',
                'blind': True,
                'question': 'Can you name every instrument asked for in this take, and no instrument that was not asked for? yes/no',
            },
        ],
        inputs={
            'prompt': 'a short instrumental phrase in a minor key, 80 bpm, played by exactly these instruments and no others: {instruments}',
            'task': 'LADDER',
        },
        cond=dict(COND_SOUND, repeats=3, seconds=12),
        unit='count',
        ladder_labels=[
            ['a viola da gamba'],
            ['a viola da gamba', 'a baroque lute'],
            ['a viola da gamba', 'a baroque lute', 'a wooden recorder'],
            ['a viola da gamba', 'a baroque lute', 'a wooden recorder', 'a harpsichord', 'a hand drum'],
            [
                'a viola da gamba',
                'a baroque lute',
                'a wooden recorder',
                'a harpsichord',
                'a hand drum',
                'a shawm',
                'a hurdy-gurdy',
                'a tambourine',
            ],
        ],
        state_note=(
            'the count = the largest rung where EVERY instrument label still scores >= 0.26 '
            'against the render AND the operator can name them all with nothing extra, on all '
            'three seeds. The threshold is lower than CLAP_MIN because a label inside a mix '
            'never reaches a solo score; the operator remains the decision.'
        ),
    ),
    _probe(
        'acap_concurrent',
        'Capacity ladder: concurrent renders before the real-time factor collapses',
        ['acap_concurrent'],
        [
            {'check': 'rtf_max', 'times': 1.3, 'of': 'the 1-stream RTF of this row'},
            {'check': 'onset_count', 'n': 3, 'tolerance': 0},
            {'check': 'clap_label_min', 'label': BASE_LABEL, 'min': CLAP_MIN, 'margin': CLAP_NULL_MARGIN},
        ],
        inputs={'prompt': BASE_PROMPT},
        cond=dict(COND_SOUND, repeats=3),
        unit='count',
        ladder=[1, 2, 4, 8],
        state_note=(
            'the count = the largest rung where total throughput still grew by >= 10 % over '
            'the previous rung AND the per-stream RTF stayed within 1.3 x the 1-stream RTF '
            'AND every render still passed its own checks. Fully mechanical: nothing here '
            'needs the operator. Streams are started together on the SAME card; the '
            'nvidia-smi 1 Hz sample of the whole rung is written on the trial.'
        ),
    ),
]

# ── Counting & quantity: for audio these are COUNTED EVENTS in a fixture ───────────────
# Only the two judge steps (diarization, audio_judges) ask this band, so every probe here is a
# judge reading a fixture — never a generator. The key is the fixture's, and the fixture is
# unverified until the operator has counted it once.
_COUNT_SUFFIX = ' Answer with the single word or number only.'
_COUNT = {
    'count_exact': (
        'count/knocks_three.wav',
        'How many knocks do you hear?',
        ['3', 'three'],
        [
            {
                'check': 'onset_count',
                'n': 3,
                'tolerance': 0,
                'on': 'the fixture, as the mechanical cross-check of the key',
            }
        ],
    ),
    'count_large': (
        'count/footsteps_fourteen.wav',
        'How many footsteps do you hear?',
        ['14', 'fourteen'],
        [
            {
                'check': 'onset_count',
                'n': 14,
                'tolerance': 0,
                'on': 'the fixture, as the mechanical cross-check of the key',
            }
        ],
    ),
    'count_people': (
        'count/voices_five.wav',
        'How many different people speak in this recording?',
        ['5', 'five'],
        [{'check': 'speaker_count', 'n': 5}],
    ),
    'count_absent': (
        'count/harbour_no_dog.wav',
        'Is there a dog barking in this recording?',
        ['no'],
        [{'check': 'clap_absent_max', 'labels': ['a dog barking'], 'max': CLAP_ABSENT_MAX}],
    ),
    'count_more_less': (
        'count/gulls_and_bell.wav',
        'Are there more gull cries or more bell strikes in this recording?',
        ['gulls', 'gull cries', 'the gulls'],
        [],
    ),
}
for _col, (_fx, _q, _accept, _extra) in _COUNT.items():
    PROBES.append(
        _probe(
            _col,
            f'Counting: {_col}',
            [_col],
            [{'check': 'equals_key', 'accept': _accept}] + _extra,
            cond=dict(COND_JUDGE),
            inputs={'audio': f'capability_tests/fixtures/audio/{_fx}', 'task': _q + _COUNT_SUFFIX},
            fixture_key=_fx,
            state_note=(
                "the judge answers the written question about the fixture; the key is the fixture's "
                'own, and the second check re-derives that key from the file with a detector '
                '(librosa onsets / pyannote / CLAP) so a wrong fixture shows up as a failing '
                'cross-check rather than as a failing model. The fixture blocks this column until '
                'the operator has counted it once by ear.'
            ),
        )
    )
