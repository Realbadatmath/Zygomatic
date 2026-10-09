# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""audio_shared: the fixture recordings, the prompt-damage base and the probe helper."""

from __future__ import annotations

from .settings import AMBIENCE, CLAP_MIN, CLAP_NULL_MARGIN, COND_SOUND, SOUNDS

# ── fixtures ──────────────────────────────────────────────────────────────────────────
# Nothing here is created by this module. Every entry says where the file goes and the exact
# recipe that makes it. A fixture whose label a human has not confirmed carries
# `verified: False` and BLOCKS its columns: they ship `untested` with the note "key
# unverified" until the operator listens once and flips the flag.
_HEARS_RECIPE = (
    'pulled from the SFX library slates by label; see project_sfx_library_slates. '
    'Take the highest-rated slate whose label matches, trim to the first 4 s '
    '(12 s for an ambience), peak-normalise to -3 dBFS, resample to 48 kHz mono '
    'with soxr VHQ, write 24-bit WAV. One file per subject, no processing beyond that.'
)
_HEARS_HOWTO = (
    'The operator plays the file once, with the filename hidden, and writes down what '
    "they hear. The fixture is verified only when that answer matches the subject's "
    'label. A slate that turns out to be the wrong sound is replaced, not relabelled.'
)

FIXTURES = {}
for _sid, (_lbl, _pr) in SOUNDS.items():
    FIXTURES[f'sounds/{_sid}.wav'] = {
        'path': f'capability_tests/fixtures/audio/sounds/{_sid}.wav',
        'generated': _HEARS_RECIPE,
        'label': _lbl,
        'seconds': 12 if _sid in AMBIENCE else 4,
        'verified': False,
        'blocks': [f'hear_{_sid}'],
        'how_to_verify': _HEARS_HOWTO,
    }

FIXTURES.update(
    {
        'count/knocks_three.wav': {
            'path': 'capability_tests/fixtures/audio/count/knocks_three.wav',
            'generated': 'record or cut exactly three knuckle knocks on a wooden door, 0.8 s apart, 4 s total, 48 kHz mono, nothing else audible',
            'key': {'count_exact': 3},
            'verified': False,
            'blocks': ['count_exact'],
            'how_to_verify': 'the operator counts the knocks once; librosa onset_detect on the fixture must return 3 as well, and both numbers are written into the fixture record',
        },
        'count/footsteps_fourteen.wav': {
            'path': 'capability_tests/fixtures/audio/count/footsteps_fourteen.wav',
            'generated': 'exactly fourteen footsteps on bare wooden boards, even pace, ~0.55 s apart, 8 s total, 48 kHz mono, no other sound',
            'key': {'count_large': 14},
            'verified': False,
            'blocks': ['count_large'],
            'how_to_verify': 'the operator counts the steps once; librosa onset_detect must return 14; both numbers go into the fixture record',
        },
        'count/voices_five.wav': {
            'path': 'capability_tests/fixtures/audio/count/voices_five.wav',
            'generated': 'five different house voices, one short line each, no overlap, 12 s total, 48 kHz mono, dry, no music',
            'key': {'count_people': 5},
            'verified': False,
            'blocks': ['count_people'],
            'how_to_verify': 'the operator names five distinct speakers; pyannote speaker-diarization-3.1 must also return 5',
        },
        'count/harbour_no_dog.wav': {
            'path': 'capability_tests/fixtures/audio/count/harbour_no_dog.wav',
            'generated': 'harbour ambience with water, rigging and gulls, 12 s, 48 kHz mono, containing NO dog and no bark of any kind',
            'key': {'count_absent': 'no'},
            'verified': False,
            'blocks': ['count_absent'],
            'how_to_verify': 'the operator listens to the whole 12 s and confirms there is no dog; CLAP must rank "a dog barking" outside the top 10 of the 53 labels',
        },
        'count/gulls_and_bell.wav': {
            'path': 'capability_tests/fixtures/audio/count/gulls_and_bell.wav',
            'generated': 'eleven separate gull cries and exactly two church bell strikes over 12 s of quiet harbour, 48 kHz mono',
            'key': {'count_more_less': 'gulls'},
            'verified': False,
            'blocks': ['count_more_less'],
            'how_to_verify': 'the operator counts both and confirms 11 gull cries against 2 bell strikes',
        },
        'judge/clipped.wav': {
            'path': 'capability_tests/fixtures/audio/judge/clipped.wav',
            'generated': 'one good house narration line rendered clean, then digitally clipped by applying +9 dB and hard-limiting at 0 dBFS, so 4 % of samples sit at full scale; 6 s, 48 kHz mono',
            'key': {'clipping': 'yes'},
            'verified': False,
            'blocks': ['pd_question_wording'],
            'how_to_verify': 'the operator confirms the clipping is audible; a meter must report true peak >= 0.0 dBTP and a non-zero clipped-sample count',
        },
        'judge/clean.wav': {
            'path': 'capability_tests/fixtures/audio/judge/clean.wav',
            'generated': 'the SAME narration line as judge/clipped.wav, rendered once and left alone: -18 LUFS integrated, true peak -3.2 dBTP, no clipping, no dropout; 6 s, 48 kHz mono',
            'key': {'clipping': 'no'},
            'verified': False,
            'blocks': ['pd_leading'],
            'how_to_verify': 'the operator confirms the take is clean; the meter must report true peak <= -3 dBTP and zero clipped samples',
        },
        'judge/silence.wav': {
            'path': 'capability_tests/fixtures/audio/judge/silence.wav',
            'generated': '3 s of digital silence (all samples zero), 48 kHz mono — there is nothing in it to judge',
            'key': {'delivery': 'cannot tell'},
            'verified': True,
            'how_to_verify': 'verified by construction: the file is all zeros, which a checksum shows without a listen',
        },
        'judge/balanced_six/': {
            'path': 'capability_tests/fixtures/audio/judge/balanced_six/',
            'generated': (
                'six 6 s narration takes, 48 kHz mono, named 01..06: THREE faulty — 01 clipped '
                '(+9 dB hard-limited), 02 truncated (cut mid-word at 4.1 s), 03 with 1.8 s of '
                'dead air in the middle — and THREE clean at -18 LUFS with no fault of any kind. '
                'The order of the six is fixed and recorded in the fixture record.'
            ),
            'key': {'faulty': ['01', '02', '03'], 'clean': ['04', '05', '06']},
            'verified': False,
            'blocks': ['pd_batched_questions'],
            'how_to_verify': 'the operator listens to all six blind and must arrive at exactly the three faulty ones; a disagreement means the fixture, not the judge, is wrong',
        },
        'judge/quiet_-26lufs.wav': {
            'path': 'capability_tests/fixtures/audio/judge/quiet_-26lufs.wav',
            'generated': 'the SAME narration line as judge/clean.wav, attenuated by a fixed gain to -26.0 LUFS integrated, true peak -11.2 dBTP; 6 s, 48 kHz mono. Nothing else is changed.',
            'key': {'too_quiet': 'yes', 'lufs': -26.0},
            'verified': True,
            'how_to_verify': 'verified by construction and by meter: a BS.1770-4 reading of -26.0 +/- 0.3 LUFS is the whole key, and the house standard (-20 to -14 LUFS) calls that too quiet',
        },
        'judge/truncated.wav': {
            'path': 'capability_tests/fixtures/audio/judge/truncated.wav',
            'generated': 'a deliberately BROKEN file: the 44-byte WAV header of judge/clean.wav with its data-chunk size field left claiming 40 s, followed by only 0.2 s of samples. It is not audio to be judged; it is the malformed input u_failsafe feeds the row.',
            'key': {'malformed': True},
            'verified': True,
            'how_to_verify': 'verified by construction: the header length and the file length disagree, which a 10-line check shows without a listen',
        },
        'layers/': {
            'path': 'capability_tests/fixtures/audio/layers/',
            'generated': (
                'twelve 12 s stems, 48 kHz mono, peak -12 dBFS each, in the fixed order '
                '01 room_tone_interior, 02 door_creak, 03 footstep_wood, 04 cloth_rustle, '
                '05 clock_tick, 06 fire_crackle, 07 rain_roof, 08 paper_rustle, '
                '09 pour_liquid, 10 coins, 11 crowd_murmur, 12 cart_wheels — each cut from '
                "the matching sounds/<id>.wav so the labels are already the bank's labels. "
                'Stem 02 (door_creak) is the TARGET the acap_layers ladder listens for.'
            ),
            'verified': False,
            'blocks': ['acap_layers'],
            'how_to_verify': 'the operator plays stem 02 alone and confirms it is an unmistakable door creak; the other eleven need only match their own label',
        },
        'ref/door_creak_ref.wav': {
            'path': 'capability_tests/fixtures/audio/ref/door_creak_ref.wav',
            'generated': 'a copy of sounds/door_creak.wav trimmed to 2 s — the worked example the pd_example_needed pair offers as a reference',
            'verified': False,
            'blocks': ['pd_example_needed'],
            'how_to_verify': 'the operator confirms it is the same door creak as sounds/door_creak.wav (it is a trim of that file, so a checksum of the first 2 s is enough)',
        },
    }
)

# ── the prompt-damage base: one prompt whose answer a machine can count ────────────────
BASE_PROMPT = 'three slow knocks on a wooden door, then silence, interior, close, no music, no voices'
BASE_LABEL = 'knocking on a wooden door'
BASE_CHECKS = [
    {'check': 'onset_count', 'n': 3, 'tolerance': 0},
    {'check': 'clap_label_min', 'label': BASE_LABEL, 'min': CLAP_MIN, 'margin': CLAP_NULL_MARGIN},
]

# Same meaning as BASE_PROMPT, worse writing. Each is scored with the SAME BASE_CHECKS — the
# answer (three onsets, still a wooden door) must not move.
DAMAGE_VARIANTS = {
    'pd_paraphrase': 'someone raps three times, unhurried, on a door made of wood; then nothing. indoors, near the door, no music, no speech',
    'pd_word_order': 'no voices, no music, close, interior, then silence: three slow knocks on a wooden door',
    'pd_synonym': 'three unhurried raps on a timber door, then quiet, indoors, near, no score, no speech',
    'pd_typo': 'three slwo knocks on a wooden dooor, then silnece, interor, close, no music, no voises',
    'pd_grammar': 'knock wooden door three time slow, after silence, inside near, music no, voice no',
    'pd_punctuation': 'three, slow knocks on a wooden door then, silence; interior close no music no voices',
    'pd_case': 'THREE SLOW KNOCKS ON A WOODEN DOOR, THEN SILENCE, INTERIOR, CLOSE, NO MUSIC, NO VOICES',
    'pd_filler': 'please, very carefully and in a highly detailed professional way, three slow knocks on a wooden door, then silence, interior, close, no music, no voices',
    'pd_repetition': 'three slow knocks on a wooden door, three knocks, knocks, three, then silence, interior, close, no music, no voices',
    'pd_multilingual': 'drie langzame kloppen op een houten deur, daarna stilte, binnen, dichtbij, geen muziek, geen stemmen',
}

# ── the fixed 80-word line every word/lyric ladder is cut from ─────────────────────────
LYRIC_80 = (
    'The tide turns at the yard gate and the gulls go quiet over the water. Cornelis lays '
    'his mallet on the rail and counts the barrels twice. Anna lifts the lantern above the '
    'crates and calls her brother in from the cold. Joost winds the wet rope around his arm '
    'and answers her without a word. The bell above the door stays silent tonight. Tomorrow '
    'the pinas sails for Texel with a full hold and a fair wind behind her.'
)
LYRIC_RULE = (
    'a rung of N words is the FIRST N words of LYRIC_80, cut on a word boundary and '
    'closed with a full stop. Never paraphrased, never re-ordered, never a different line.'
)


def _probe(pid, title, feeds, checks, cond=None, inputs=None, **kw):
    p = {
        'id': pid,
        'title': title,
        'feeds': list(feeds),
        'inputs': dict(inputs or {}),
        'conditions': dict(cond or COND_SOUND),
        'checks': list(checks),
        'grade': 'measured',
    }
    p.update(kw)
    return p


PROBES = []
