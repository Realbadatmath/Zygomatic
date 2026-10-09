# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""voice_direction — the default test. "When we write a direction on a take, does the
delivered audio change?" (2026-09-30)

WHY THIS TEST HAS A NULL IN IT
------------------------------
The sheet's own note is the reason this module exists: named character recipes are in
production, but "does the direction change the take" has never been measured against a
NULL — the same line, same seed, same reference, with no direction written on it. Without
that null every answer here is an assertion. So the null is not one probe among many: it
is a VARIANT of every probe, rendered first, and every mechanical check is a comparison
against it. A take that is byte-adjacent to its null did not respond to the note, whatever
it sounds like to the person who asked for it.

THE SHAPE
---------
  Does it work   responds / repeatable / range / intelligible / takes / identity_survives
                 — mechanical where a machine can decide (cross-correlation against the
                   null, WER, speaker cosine), derived where the answer is a count.
  Directions     the nine named emotions, plus scream, blend and arc. Each named emotion is
                 a BLIND FORCED CHOICE: the operator hears one anonymised take and picks
                 one label from the same list of nine. Guessing scores 1/9, so "the
                 operator could tell" is a real claim and not a courtesy.

WHY THE ROWS DISAGREE SO MUCH
-----------------------------
Only ONE row on this sheet has a WRITTEN emotion channel. IndexTTS-2 takes `emo_text` and
`emo_alpha` per call (tts_service._indextts_segments, 2026-08-07), so a direction is text
the model reads. Everything else is a different kind of thing wearing the same word:

  abel       a FROZEN SEED cloned by Chatterbox (abel_voice.py). Chatterbox's only handle is
             the scalar `--exaggeration` (0.3). A scalar can be turned up; it cannot be told
             WHICH of nine emotions to be. So abel answers "does the take move, repeatably,
             intelligibly, still as Abel" and nothing about named emotions.
  worn       the worn-voice treatment: a seed_k RESAMPLE (k<1) frozen into the wav
             (build_cast_voices.freeze), measured by voice_texture.wear. It is a fixed
             recipe, not a note — but it is the ONE row whose direction has a mechanical
             detector, so `exhaustion` is a probe here and an operator choice nowhere else.
  cornelis   a seed_k / seed_m bench frozen on disk (build_cast_voices.py, bench 'cornelis').
  teen       the same, ten seeds under data/assets/voice_seeds/teens (build_teen_voices.py).

For those three the "direction" IS the recipe and the null is the UNRESHAPED source seed.
That comparison is honest and worth having; calling it emotional range would not be. Every
column they cannot answer is `na` with the reason written out, never a blank.

WHAT THIS TEST CANNOT SAY
-------------------------
Nothing about whether a direction is the RIGHT one for a scene, nothing about a director's
taste, and nothing about a direction written in Dutch (all nine notes are English — the
lines they are spoken over are Dutch-register but English text). `takes` counts takes to a
usable one under THIS ladder, on THIS line; it is not a production rate.
"""

from __future__ import annotations

# ── check kinds this step adds (never added to capability_tests/__init__.py) ──
CHECK_KINDS = {
    'waveform_correlation_max': 'peak normalised cross-correlation (lag searched +/- 200 ms, both takes resampled to '
    '48 kHz mono and loudnorm-ed to -23 LUFS first) between this take and the variant '
    'named in `to` is STRICTLY LESS than `max` — the take is not the null wearing a label',
    'waveform_correlation_pairwise_min': 'every pair of repeats of this trial has peak normalised cross-correlation (same '
    'preparation as above) >= `min` — the same note twice gives the same take',
    'feature_moves': 'at least `count` of the features in `features` differ from the variant named in `to` '
    "by >= that feature's threshold, in the sign given by `expect` (+1 up, -1 down, 0 "
    'either). Features and thresholds are fixed in FEATURES; F0 and HNR come from the '
    'voice_qc Praat venv, RMS/centroid/rate from librosa on the same take',
    'operator_choice': 'BLIND FORCED CHOICE: the runner plays ONE anonymised take (order shuffled across the '
    'whole sheet) and the operator picks exactly one label from `choices`; the trial passes '
    'when the pick equals `expect`. Chance is 1/len(choices). `question` is read to the '
    'operator verbatim; no other information about the take is shown',
    'operator_choice_both': 'BLIND FORCED CHOICE, TWO LABELS: the operator picks exactly two labels from `choices`; '
    'the trial passes when the SET of picks equals the set in `expect`. Chance is 1/36',
    'scream_features': 'RMS (dBFS) and spectral flatness of the loudest 500 ms window are each within the '
    'tolerance in `band` of the reference recording at `reference` — a real scream, not a '
    'loud reading. Both must hold; a take that clips (true peak > -0.1 dBTP) fails',
    'arc_direction': 'the feature `feature`, measured over the first and second half of the take separately '
    '(split at the midpoint of voiced frames), differs by >= `delta` with sign `sign` '
    '(+1 = second half higher) — the take changes DURING the line, not between takes',
    'speaker_cosine_min': 'cosine similarity of the pinned speaker embedding (pyannote/wespeaker-voxceleb-'
    'resnet34-LM, the model shipped with speaker-diarization-3.1) between this take and '
    'the variant named in `to` is >= `min` — still the same person under the direction',
}

# ── the eight fixed lines, verbatim. A runner may not shorten, translate or re-punctuate. ──
LINES = {
    'null': 'Cornelis, the barrels came off the quay before dawn, and not one of them was ours.',
    'scream': 'The rope went \u2014 get back from the edge!',
    'blend': 'I have not slept, and the tide will not wait for either of us.',
    'arc': 'I asked once, quietly, and then I asked again, and now I am done asking.',
    'clear': 'Joost signed for fourteen crates on the twelfth of March, sixteen seventy-one, at seven in the morning.',
    'long': 'Anna stood at the warehouse door with the ledger open in her hands, and she read the columns twice before she said anything at all about the missing weight.',
    'repeat': 'Say it again, slowly.',
    'subtext': 'Of course you did. Of course.',
}

# The nine directions, verbatim, and the label list the operator chooses from.
DIRECTIONS = {
    'anger': 'angry \u2014 cold, controlled fury, not shouting',
    'grief': 'grieving \u2014 the voice catches, close to tears',
    'fear': 'frightened \u2014 breath shallow and high',
    'warmth': 'warm \u2014 affectionate, unhurried',
    'authority': 'commanding \u2014 this is an order, not a request',
    'exhaustion': 'exhausted \u2014 no energy left, the words cost effort',
    'urgency': 'urgent \u2014 fast, pressing, no time',
    'tenderness': 'tender \u2014 very quiet, spoken to someone loved',
    'sarcasm': 'sarcastic \u2014 the words mean their opposite',
}
EMOTIONS = ('anger', 'grief', 'fear', 'warmth', 'authority', 'exhaustion', 'urgency', 'tenderness', 'sarcasm')
CHOICES = list(EMOTIONS)
# Sarcasm is the one emotion that needs subtext, so it is asked over the one line that has
# any; the other eight are asked over the same neutral line, which is what makes them
# comparable to each other and to the null.
EMO_LINE = {e: 'null' for e in EMOTIONS}
EMO_LINE['sarcasm'] = 'subtext'

SCREAM_NOTE = 'screaming in real fear \u2014 a full-voice scream, not a loud reading'
BLEND_NOTE = 'exhausted AND urgent at the same time \u2014 no energy left, and no time left either'
ARC_NOTE = 'start calm and quiet, and end in open anger \u2014 the change happens inside the line'

# ── thresholds: in the test, never in the runner ──
CORR_CHANGED = 0.90  # responds: directed vs null must fall BELOW this
CORR_SAME = 0.95  # repeatable: pairs of repeats must sit AT OR ABOVE this
WER_MAX = 0.05  # intelligible, under every direction including the null
COS_IDENTITY = 0.60  # identity_survives, directed take vs its own null
FEATURES = {
    'f0_median_hz': 6.0,  # Hz, voice_qc Praat venv
    'f0_range_semitones': 1.5,  # semitones between the 10th and 90th percentile
    'rms_dbfs': 2.0,  # dB, after loudnorm is DISABLED for this measure
    'speech_rate_syl_s': 0.5,  # syllables/s over voiced frames
    'hnr_db': 1.5,  # dB, voice_qc Praat venv
    'spectral_centroid_hz': 150.0,
}
SCREAM_BAND = {'rms_dbfs': 3.0, 'spectral_flatness': 0.05, 'true_peak_max_dbtp': -0.1}
ARC = {'f0_median_hz': 8.0, 'rms_dbfs': 3.0}

THRESHOLD_NOTE = (
    "CORR_CHANGED 0.90 and CORR_SAME 0.95 are THIS TEST'S standard, not a house receipt: "
    'no cross-correlation of a directed against an undirected take has ever been run here '
    '(that is the gap the sheet records). They are set where a same-seed re-render of the '
    'SAME prompt is expected to sit (near 1.0) against any audible change of delivery. The '
    'first run must publish the observed null-vs-null and null-vs-directed distributions in '
    'its Inspect document; if a same-seed re-render does not clear 0.95, REPLACE these two '
    'numbers with the measured figures and bump the test version \u2014 do not widen a '
    'threshold to make a row pass. COS_IDENTITY 0.60 is deliberately above the 0.55 used '
    'for clone-vs-donor (voice_clone.py): these two takes share a recording chain, a '
    'reference and a seed, so only the delivery differs.'
)

COND = {
    'seeds': [11, 12, 13],
    'repeats': 3,
    'sample_rate_out': 48000,
    'channels': 1,
    'reference': "the row's own reference/seed wav (rows.<rid>.reference) \u2014 never re-picked per trial",
    'null_first': True,
    'note': (
        'Every trial renders its NULL variant first, from the same seed, same reference and '
        'byte-identical line, with the direction field EMPTY (IndexTTS-2: emo_text off, '
        'emo_alpha at the module default 0.6; Chatterbox: exaggeration at the shipped 0.3). '
        'Loudness is normalised to -23 LUFS for correlation and cosine only; the rms_dbfs '
        'feature and the scream band are measured on the UNNORMALISED take, or the '
        'measurement is circular.'
    ),
}

DIRECTABLE = ['indextts2_dir']  # the only row with a written emotion channel


def _p(pid, title, feeds, checks, line, direction=None, order=0, **kw):
    """A probe. `line` names the key in LINES; `direction` is the verbatim note (None = null)."""
    p = {
        'id': pid,
        'title': title,
        'feeds': feeds,
        'run_order': order,
        'inputs': {
            'prompt': direction or '(no direction \u2014 the null)',
            'audio': 'rows.<rid>.reference',
            'line_key': line,
            'line': LINES[line],
        },
        'conditions': dict(COND),
        'checks': checks,
        'grade': 'measured',
    }
    p.update(kw)
    return p


_MOVE = {
    'check': 'feature_moves',
    'to': 'null',
    'count': 1,
    'features': FEATURES,
    'expect': 0,
    'note': 'a direction that moves NO feature at all did not arrive, whatever the correlation says',
}

PROBES = (
    [
        # ── mechanical first: WER and correlation cost no operator minutes ──
        _p(
            'dir_intelligible',
            'Stays intelligible under every direction',
            ['intelligible'],
            [
                {
                    'check': 'wer_max',
                    'max': WER_MAX,
                    'transcript': 'faster-whisper large-v3, language forced to en, no VAD trim',
                    'against': 'LINES[clear], verbatim, as the reference transcript',
                }
            ],
            'clear',
            order=1,
            repeats_note='one render per variant, no repeats: WER is deterministic given the take',
            inputs_note='rendered once under the null and once under each of the nine directions',
            conditions=dict(COND, repeats=1, variants=['null'] + list(EMOTIONS)),
            state_rule={'yes': 1.0, 'partial': 0.7},
            state_note='the column asks "under EVERY direction", so all ten variants must clear WER 0.05; '
            '7 of 10 is partial and says which direction broke it',
        ),
        _p(
            'dir_repeatable',
            'The same note twice gives the same take',
            ['repeatable'],
            [{'check': 'waveform_correlation_pairwise_min', 'min': CORR_SAME}],
            'repeat',
            DIRECTIONS['anger'],
            order=2,
            conditions=dict(COND, repeats=3, seeds=[11, 11, 11]),
            state_note='the seed is held FIXED across the three repeats on purpose: this asks whether the '
            'pipeline is deterministic under a written note, not whether it varies by seed',
        ),
        _p(
            'dir_responds',
            'The take changes with the note, measured against a no-direction null',
            ['responds'],
            [{'check': 'waveform_correlation_max', 'to': 'null', 'max': CORR_CHANGED}, _MOVE],
            'null',
            DIRECTIONS['anger'],
            order=3,
            conditions=dict(COND, repeats=3, variants=['null', 'anger', 'tenderness', 'urgency']),
            state_note='three directions far apart on the plane plus the null; a row that fails this fails '
            'the whole sheet and the nine operator probes need not be paid for',
        ),
        _p(
            'dir_identity',
            'The voice stays the same person under direction',
            ['identity_survives'],
            [{'check': 'speaker_cosine_min', 'to': 'null', 'min': COS_IDENTITY}],
            'null',
            DIRECTIONS['anger'],
            order=4,
            conditions=dict(COND, repeats=3, variants=list(EMOTIONS)),
            state_note="all nine directions against the row's own null; the note records the LOWEST "
            'cosine and which direction produced it \u2014 that is the one that broke the voice',
        ),
        _p(
            'dir_arc',
            'A direction that changes mid-line',
            ['arc'],
            [
                {'check': 'arc_direction', 'feature': 'f0_median_hz', 'delta': ARC['f0_median_hz'], 'sign': 1},
                {'check': 'arc_direction', 'feature': 'rms_dbfs', 'delta': ARC['rms_dbfs'], 'sign': 1},
                {'check': 'waveform_correlation_max', 'to': 'null', 'max': CORR_CHANGED},
            ],
            'arc',
            ARC_NOTE,
            order=5,
            conditions=dict(COND, repeats=3),
            state_note='both halves are measured on the same take; a take that is merely angry throughout '
            'fails the split even though it would pass `anger`',
        ),
        _p(
            'dir_worn_wear',
            'The worn treatment reads as exhaustion on the wear index',
            ['exhaustion'],
            [
                {
                    'check': 'feature_moves',
                    'to': 'null',
                    'count': 2,
                    'features': {'hnr_db': 1.5, 'f0_median_hz': 6.0, 'spectral_centroid_hz': 150.0},
                    'expect': -1,
                    'note': 'HNR down, F0 down, centroid down is what voice_texture.wear reads as rougher',
                },
                {'check': 'waveform_correlation_max', 'to': 'null', 'max': CORR_CHANGED},
            ],
            'null',
            'the worn-voice treatment: seed_k resample below 1.0, frozen into the wav',
            order=6,
            rows=['worn'],
            conditions=dict(
                COND,
                repeats=1,
                seeds=[11],
                note='deterministic ffmpeg DSP \u2014 one render is the whole population; the null '
                'is the UNRESHAPED source seed, which is what build_cast_voices.freeze reshapes',
            ),
            state_rule={'yes': 1.0, 'partial': 0.5},
            state_note="the ONE named emotion on this sheet with a mechanical detector (voice_texture.py's "
            'four Praat measures, population from the 2026-08-12 donation-bank scan). It is scored '
            "for the `worn` row only \u2014 no other row's direction has a detector, and an index "
            'is not an opinion, so this cell and the operator cells must not be read as one number',
        ),
        # ── the nine named directions: blind forced choice, 1-in-9 by chance ──
    ]
    + [
        _p(
            'dir_emo_' + e,
            'Direction asked for: ' + e,
            [e],
            [
                {
                    'check': 'operator_choice',
                    'choices': CHOICES,
                    'expect': e,
                    'blind': True,
                    'question': (
                        'Listen once. Which ONE of these nine was this take directed to be? '
                        'anger, grief, fear, warmth, authority, exhaustion, urgency, tenderness, '
                        'sarcasm. Pick one. Do not listen twice and do not skip.'
                    ),
                }
            ],
            EMO_LINE[e],
            DIRECTIONS[e],
            order=10 + i,
            rows=DIRECTABLE,
            conditions=dict(COND, repeats=3),
            state_rule={'yes': 0.66, 'partial': 0.33},
            state_note='pass = the operator picks this emotion on 2 of 3 takes. Chance is 1/9, so 2 of 3 is '
            'not a coin flip. The nine probes are shuffled together with every other operator '
            'trial on the sheet before anything is played, so the operator never hears the nine '
            'in a block and cannot answer by elimination',
        )
        for i, e in enumerate(EMOTIONS)
    ]
    + [
        _p(
            'dir_blend',
            'Two directions at once \u2014 tired AND urgent',
            ['blend'],
            [
                {
                    'check': 'operator_choice_both',
                    'choices': CHOICES,
                    'expect': ['exhaustion', 'urgency'],
                    'blind': True,
                    'question': (
                        'Listen once. This take was directed to be TWO of these nine at the '
                        'same time. Which two? anger, grief, fear, warmth, authority, '
                        'exhaustion, urgency, tenderness, sarcasm. Pick exactly two.'
                    ),
                },
                {'check': 'waveform_correlation_max', 'to': 'null', 'max': CORR_CHANGED},
            ],
            'blend',
            BLEND_NOTE,
            order=20,
            rows=DIRECTABLE,
            conditions=dict(COND, repeats=3),
            state_rule={'yes': 0.66, 'partial': 0.33},
            state_note='both labels must be picked \u2014 a take that is only tired, or only urgent, is a '
            'fail, because the question is whether two notes SURVIVE each other',
        ),
        _p(
            'dir_failsafe',
            'Fails without breaking the caller',
            ['failsafe'],
            [
                {
                    'check': 'operator',
                    'blind': False,
                    'question': (
                        'Did all three broken calls come back \u2014 each returning a value '
                        'or raising an exception the caller caught \u2014 with this process '
                        'still alive and nvidia-smi showing the VRAM released within 30 s? '
                        'yes/no'
                    ),
                },
                {
                    'check': 'file_absent',
                    'path': 'output/capabilities/failsafe/partial.wav',
                    'note': 'a half-written take left behind is a fail even if the call returned',
                },
            ],
            'repeat',
            order=7,
            inputs={
                'prompt': '(three deliberately broken calls \u2014 the three in `variants`, in order)',
                'audio': 'capability_tests/fixtures/audio/judge/truncated.wav',
                'variants': {
                    'empty_line': "the line is the empty string, the reference is the row's own valid seed",
                    'broken_reference': (
                        'the line is LINES[repeat], the reference is '
                        'capability_tests/fixtures/audio/judge/truncated.wav \u2014 a WAV '
                        'whose header claims 40 s over 0.2 s of samples'
                    ),
                    'missing_reference': (
                        'the line is LINES[repeat], the reference is a path that does '
                        'not exist: data/assets/voice_seeds/does_not_exist.wav'
                    ),
                },
            },
            conditions=dict(
                COND, repeats=3, seeds=[11, 11, 11], note='no take is expected; what is measured is how the call ends'
            ),
            state_note=(
                'all three must come back. no = any hang past 120 s, any crash of the host process, '
                'any leaked VRAM allocation. Answered SIGHTED \u2014 there is nothing to be blind '
                'about when the question is whether the process is still running.'
            ),
            overrides_shared='u_failsafe',
        ),
        _p(
            'dir_scream',
            'A real scream',
            ['scream'],
            [
                {
                    'check': 'scream_features',
                    'band': SCREAM_BAND,
                    'reference': 'capability_tests/fixtures/voice_direction/scream_reference.wav',
                },
                {
                    'check': 'operator_choice',
                    'choices': ['a real scream', 'a loud reading'],
                    'expect': 'a real scream',
                    'blind': True,
                    'question': 'Listen once. Is this a real scream, or a loud reading? Pick one.',
                },
            ],
            'scream',
            SCREAM_NOTE,
            order=21,
            rows=DIRECTABLE,
            conditions=dict(COND, repeats=3),
            state_rule={'yes': 0.66, 'partial': 0.33},
            state_note='the features are a SCREEN (a take can hit the band and still read as shouting); the '
            'operator decides, which is why both checks must pass',
        ),
    ]
)

DERIVE = {
    'range': {
        'question': 'Range of emotions reachable',
        'from': ['dir_emo_' + e for e in EMOTIONS],
        'rule': 'count the nine emotion columns whose state came out `yes`',
        'unit': 'count',
        'grade': 'measured',
        'state_rule_note': 'reported as a count out of 9, and stated as yes at >= 7, partial at >= 4, '
        'else no \u2014 the count is the answer, the state is a summary of it',
        'note': 'derived, not asked separately: a second probe over the same nine takes would be the '
        'same measurement counted twice, and the validator would see two dispositions.',
    },
    'takes': {
        'question': 'Takes needed for a usable one',
        'from': ['dir_emo_' + e for e in EMOTIONS] + ['dir_blend', 'dir_scream'],
        'rule': 'for every operator trial group that reached `yes`, the 1-based index of the FIRST '
        'repeat the operator named correctly; the answer is the MEDIAN of those indices, and '
        'the note carries the worst case. A group that never reached `yes` contributes '
        '"more than 3", which is reported as > 3 and never averaged in as 3',
        'unit': 'count',
        'grade': 'measured',
        'note': 'read off the operator ladder that is already being paid for, so this column costs '
        'nothing extra. It answers "on this line, under this test" \u2014 not a studio rate.',
    },
}

# ── rows ──
# The 14 columns a row without a written direction channel cannot answer. Each reason says
# what is missing, not that the row is bad.
_NO_CHANNEL = tuple(EMOTIONS) + ('range', 'blend', 'arc', 'scream', 'takes')


def _na_scalar():
    why = (
        'Chatterbox exposes one scalar (--exaggeration, shipped at 0.3) and no text channel, so a '
        'direction can be turned UP but cannot be told which of nine to be; there is nothing here '
        'for the operator to name.'
    )
    out = {c: why for c in EMOTIONS}
    out['range'] = (
        'Range counts the nine named emotions, none of which can be asked of a single '
        'scalar; a count of columns that are themselves na would be a fabricated number.'
    )
    out['blend'] = (
        'Two notes at once needs two notes; one scalar cannot carry a pair, so there is no blend to deliver or to fail.'
    )
    out['arc'] = (
        'The scalar is set once per call and cannot change inside a line, so a mid-line '
        'arc is not something this row can be asked for.'
    )
    out['scream'] = (
        'A scream is a named direction and this row has no way to receive one; raising '
        'the scalar makes the take more emphatic, not a scream.'
    )
    out['takes'] = (
        'Takes to a usable one is derived from the operator ladder over the named '
        'directions, and this row has no named directions to ladder through.'
    )
    return out


def _na_recipe(what):
    why = (
        'This row is a FROZEN RECIPE, not a direction channel: ' + what + '. The reshape is already '
        'in the wav, there is no per-take note to write, and so no named emotion can be asked of it.'
    )
    out = {c: why for c in EMOTIONS}
    out['range'] = (
        'Range counts named emotions, and a frozen reshape receives none; the honest '
        'answer is that the question does not reach this row.'
    )
    out['blend'] = (
        'A blend needs two notes on one take; this row has no notes at all, only the '
        'recipe that is already baked into the seed.'
    )
    out['arc'] = (
        'The reshape is a single constant applied to the whole file, so nothing can change '
        'inside a line by construction.'
    )
    out['scream'] = (
        'A scream must be performed, and this row does not perform \u2014 it reshapes a '
        'take that was already performed elsewhere.'
    )
    out['takes'] = (
        'The recipe is deterministic: it produces exactly one take, every time, so '
        '"takes to a usable one" has no ladder to count.'
    )
    return out


_REF = 'data/assets/voice_seeds/'
ROWS = {
    'indextts2_dir': {
        'transport': 'service',
        'module': 'tts_service.py',
        'function': '_indextts_segments(segments, work_dir, ref_wav, log, emo_alpha=, emo_text=)',
        'reference': _REF + 'pool/m04_british_crisp.wav',
        'direction_channel': (
            'emo_text (the direction, verbatim, as text) with emo_alpha 0.6 \u2014 the '
            'module defaults, per-call since 2026-08-07. The null sets emo_text off.'
        ),
        'note': 'the only row on this sheet whose direction is READ; it answers all 18 columns.',
    },
    'worn': {
        'transport': 'service',
        'module': 'build_cast_voices.py',
        'function': 'freeze(src_vid, k, m, out_wav) with k < 1.0; measured by voice_texture.measure/wear',
        'reference': _REF + 'benches/cornelis/cg01.wav',
        'direction_channel': (
            'none. The treatment is a seed_k resample (k<1: F0 down, vocal tract '
            'GROWS, and the resample carries the glottal roughness through \u2014 '
            'which is why k and not m). The null is the unreshaped source seed.'
        ),
        'note': (
            'There is no "worn voice pass" module: the treatment is the k<1 rung of the '
            'build_cast_voices ladder, and voice_texture.py is the measurement, not the effect. '
            'Recorded here so nobody goes looking for a file that does not exist.'
        ),
        # `exhaustion` is deliberately NOT na here: it is the one named direction on this sheet with
        # a mechanical detector, and dir_worn_wear scores it for this row only.
        'na': {
            c: r
            for c, r in _na_recipe(
                'a seed_k resample below 1.0, frozen into the wav by build_cast_voices.freeze'
            ).items()
            if c != 'exhaustion'
        },
        'budget': {
            'calls': 6,
            'minutes': 3,
            'gpu_minutes': 0.5,
            'operator_minutes': 2,
            'note': (
                'the reshape is ffmpeg on the CPU, not a render: 1 unreshaped null + 1 '
                'reshaped take for responds/exhaustion, +1 repeat, +3 for the ASR pass on '
                'intelligible and the cosine = 6 calls. The only GPU is faster-whisper, '
                '~30 s. Operator: the sighted failsafe check plus two sanity listens.'
            ),
        },
    },
    'abel': {
        'transport': 'service',
        'module': 'abel_voice.py',
        'function': 'Chatterbox worker subprocess (isolated venv) cloning the frozen seed',
        'reference': _REF + 'abel_narrator_seed.wav',
        'direction_channel': (
            '--exaggeration, a scalar, shipped at 0.3 (tts_service '
            '_chatterbox_segments). The null uses 0.3; the directed take uses 0.9.'
        ),
        'note': (
            'Two-stage asset: Maya1 DESIGNED the voice once and the identity lives in the frozen '
            'abel_narrator_seed.wav, not in a preset. IndexTTS-2 is the documented fallback tier '
            'for the same seed \u2014 if the runner falls back, the row is untested, not scored, '
            "because it would then be measuring indextts2_dir under Abel's reference."
        ),
        'na': _na_scalar(),
        'budget': {
            'calls': 18,
            'minutes': 8,
            'gpu_minutes': 6,
            'operator_minutes': 3,
            'note': (
                'answers 4 of the 18 domain columns, so: intelligible 2 variants '
                '(exaggeration 0.3 and 0.9) + repeatable 3 + responds 3 directed and 3 '
                'null + identity 3 and 3 + 1 spare null = 18 Chatterbox renders in the '
                'isolated venv, ~6 GPU minutes. No operator emotion trials at all.'
            ),
        },
    },
    'cornelis': {
        'transport': 'service',
        'module': 'build_cast_voices.py',
        'function': "build('cornelis') / freeze(src_vid, k, m, out_wav)",
        'reference': _REF + 'benches/cornelis/cg01.wav',
        'direction_channel': 'none. A seed_k / seed_m bench of ten, frozen on disk; the knobs arrive at defaults.',
        'na': _na_recipe(
            "the 'cornelis' elder-gravel bench: ten frozen seed_k / seed_m candidates "
            'under data/assets/voice_seeds/benches/cornelis'
        ),
        'budget': {
            'calls': 6,
            'minutes': 3,
            'gpu_minutes': 0.5,
            'operator_minutes': 2,
            'note': (
                'same arithmetic as the `worn` row: the frozen candidate against its '
                'unreshaped source, 6 ffmpeg/ASR calls, the GPU held only for whisper. '
                'Answers 4 of the 18 domain columns.'
            ),
        },
    },
    'teen': {
        'transport': 'service',
        'module': 'build_teen_voices.py',
        'function': 'the bench builder; ten seeds under data/assets/voice_seeds/teens',
        'reference': _REF + 'teens/teen01.wav',
        'direction_channel': 'none. Ten frozen teenage-male seeds; the shaping is already in the wav.',
        'note': (
            "The module's own measurements say the adult-male pool cannot be reshaped into a "
            'teenager (m above 1.0 collapses the tract to an eight-year-old), which is why this '
            'is a separate bench and not a knob.'
        ),
        'na': _na_recipe('ten frozen teenage-male seeds reshaped with seed_k / seed_m by build_teen_voices.py'),
        'budget': {
            'calls': 6,
            'minutes': 3,
            'gpu_minutes': 0.5,
            'operator_minutes': 2,
            'note': (
                'same arithmetic as the `worn` row: teen01.wav against the source it was '
                'reshaped from, 6 ffmpeg/ASR calls, whisper is the only GPU. Answers 4 of '
                'the 18 domain columns.'
            ),
        },
    },
}

FIXTURES = [
    {
        'path': 'capability_tests/fixtures/voice_direction/scream_reference.wav',
        'generated': (
            'Copy ONE human scream out of the house Vocal FX library and record its library id '
            'in the sidecar: `python3 -c "import asset_library_service as A; '
            "print([r for r in A.list_items('vocal_fx') if 'scream' in (r.get('tags') or '')][:20])\"`, "
            'pick one, then `ffmpeg -i <src> -ac 1 -ar 48000 -c:a pcm_s16le '
            'capability_tests/fixtures/voice_direction/scream_reference.wav`. Write a sidecar '
            '.json beside it with the library id, the licence line and the date.'
        ),
        'verified': False,
        'blocks': ['scream'],
        'how_to_verify': (
            'An operator listens to the chosen file and confirms three things in the '
            'sidecar: it is ONE human scream (not a layered design), it is not clipped '
            '(true peak <= -0.1 dBTP), and its licence permits MEASUREMENT. The Vocal FX '
            'pack licences forbid AI TRAINING, which this is not \u2014 the file is a '
            'yardstick, never an input to a model. Flip `verified` to True only after the '
            'sidecar names the library id, and until then the `scream` column ships '
            'untested with the note "key unverified", not as a fail.'
        ),
        'note': 'no binary is created by writing this test; the recipe above is the only way it appears.',
    },
    {
        'path': 'data/assets/voice_seeds/abel_narrator_seed.wav',
        'verified': True,
        'note': "on disk. The frozen Maya1 design Chatterbox clones; abel's identity and its null both come from it.",
    },
    {
        'path': 'data/assets/voice_seeds/teens/teen01.wav',
        'verified': True,
        'note': 'on disk, with teen01.json beside it carrying the k/m provenance the null needs.',
    },
    {
        'path': 'data/assets/voice_seeds/benches/cornelis/cg01.wav',
        'verified': True,
        'note': 'on disk, with cg01.json carrying seed_k / seed_m \u2014 the unreshaped source is the null.',
    },
]

TEST = {
    'step': 'voice_direction',
    'version': '2026-09-30.1',
    'title': 'Does a written direction change the take?',
    'purpose': (
        'Measure every take against a no-direction NULL rendered from the same seed, the same '
        'reference and a byte-identical line \u2014 the comparison the sheet records as never '
        'having been made. Mechanical where a machine can decide; a blind forced choice out of '
        'nine, where only a person can.'
    ),
    'include_shared': 'audio',
    'thresholds': {
        'corr_changed': CORR_CHANGED,
        'corr_same': CORR_SAME,
        'wer_max': WER_MAX,
        'cos_identity': COS_IDENTITY,
        'features': FEATURES,
        'scream_band': SCREAM_BAND,
        'arc': ARC,
        'note': THRESHOLD_NOTE,
    },
    'detectors': {
        'speaker': 'pyannote/wespeaker-voxceleb-resnet34-LM (ships with speaker-diarization-3.1), pinned',
        'asr': 'faster-whisper large-v3, language forced to en, no VAD trim',
        'f0_hnr': 'the voice_qc Praat/parselmouth venv over subprocess + JSON (never imported in-process)',
        'texture': 'voice_texture.measure / wear \u2014 HNR, jitter, shimmer, CPPS, with the noise-floor guard ON',
        'spectral': 'librosa on the unnormalised take for centroid, flatness and RMS',
    },
    'lines': LINES,
    'directions': DIRECTIONS,
    'choices': CHOICES,
    'rows': ROWS,
    'probes': PROBES,
    'derive': DERIVE,
    'lookup': {},
    'wiring': {},
    'na': {},
    'fixtures': FIXTURES,
    'budget': {
        'calls': 96,
        'tokens_in': 0,
        'tokens_out': 0,
        'tokens_note': (
            'No language model is prompted on this step. A direction is a field on a TTS '
            'call, not a chat turn, so there are no prompt or completion tokens to count; '
            'the cost here is GPU seconds and operator minutes.'
        ),
        'minutes': 34,
        'gpu_minutes': 26,
        'operator_minutes': 19,
        'note': (
            'Per row, renders: intelligible 10 variants x 1 = 10; repeatable 3; responds 4 '
            'variants x 3 = 12; identity 9 variants x 3 = 27 (the nulls are shared with '
            'responds, so 27 directed + 1 null); arc 3; nine emotions 9 x 3 = 27; blend 3; '
            'scream 3; plus 8 nulls held for the correlation and cosine comparisons = 96 renders. '
            'At ~16 s per 4-second take on the house TTS path that is ~26 GPU minutes, ~34 '
            'wall minutes with model load. Operator: 27 emotion trials + 3 blend + 3 scream + 3 '
            'null-vs-directed sanity listens = 36 blind decisions at ~30 s = 18 min, rounded to '
            "19 for the shuffle. This figure is indextts2_dir's, the only row that answers all "
            '18 columns; the other four carry their own `budget` (abel 18 calls, worn/cornelis/'
            'teen 6 each) because they answer 4 columns and three of them never touch the GPU '
            'beyond the ASR pass \u2014 so the sheet costs 132 calls and ~33 GPU minutes in '
            'total, not 5 x 96. ON TOP of every row sits the '
            'shared audio bank for this step: ~380 renders and ~80 GPU minutes for the 88 bank '
            'columns, which dwarfs the domain probes and should be scheduled first if the GPU is '
            'contended. No claude_cli or anthropic_api row on this step, so nothing here spends '
            'the shared Claude week.'
        ),
    },
    'notes': [
        (
            'The sheet\'s own words: "does the direction change the take has never been measured against '
            'a null". Every mechanical check in this module is that comparison. If a runner ever skips '
            'the null variant to save renders, the whole sheet becomes an assertion again and must be '
            'thrown away, not patched.'
        ),
        (
            "operator_choice is a FORCED CHOICE, which is not the yes/no the shared audio bank's operator "
            'protocol describes. The runner must implement it as: one take, one play, one pick out of the '
            'listed labels, no replay, shuffled in with every other operator trial on the sheet. Read as '
            'yes/no ("did this sound angry?") the nine columns would inflate, because a listener told the '
            'answer agrees with it.'
        ),
        (
            '`range` and `takes` are DERIVED from the nine emotion probes on purpose. Asking them as '
            'probes would measure the same takes twice, cost another 27 renders and 14 operator minutes, '
            'and \u2014 since the validator counts dispositions per column \u2014 would be refused.'
        ),
        (
            'Four of the five rows have no direction channel at all, and 14 of their 18 columns are `na` '
            'with a written reason. That is the honest state of this sheet, not a gap in the test: the '
            'sheet asks "what happens when we write a direction", and only IndexTTS-2 can be written to. '
            'The four columns they DO answer (responds, repeatable, intelligible, identity_survives) are '
            'real measurements of the recipe against its unreshaped source.'
        ),
        (
            '`exhaustion` carries a probe for `worn` and an operator choice for indextts2_dir. Two probes '
            'may feed one column, but the two cells are NOT the same measurement \u2014 one is '
            "voice_texture's wear index, one is a person naming an emotion \u2014 and the Inspect "
            'document must show both trials so nobody averages them.'
        ),
        (
            'This step OWNS `failsafe` (probe dir_failsafe) instead of letting the shared audio bank '
            'answer it, and the reason is a defect in code this test may not edit, recorded here so it '
            "can be fixed rather than forgotten: the bank's u_failsafe carries its fixed input as "
            '`inputs.command`, which validate_shared accepts (line ~502 allows command/image/video/mesh) '
            'but the per-step validator refuses (line ~320 allows only prompt/task/fixture/audio). Every '
            'step that includes the audio bank therefore fails on u_failsafe until one of those two lists '
            'is widened. dir_failsafe asks the SAME question over the same truncated.wav fixture with the '
            'three broken calls named in `inputs.variants`; when the bank and the validator agree again, '
            'DELETE dir_failsafe and let the bank answer, so the column is measured identically on every '
            'audio step.'
        ),
        (
            'Not answered here: whether a direction written in Dutch works (all nine notes are English); '
            'whether two directions in sequence across a scene hold; and whether a direction survives the '
            'audio_mix chain, which is measured on the mix sheets, not this one.'
        ),
    ],
}
