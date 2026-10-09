# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Default test — Melody & composition (melody). 2026-09-30.

Question the sheet asks: does the symbolic plan hold up as MUSIC before anything renders it?

This step is the opposite of music_gen. There is no model: kids_music_theory.py constructs the
melody under hard constraints out of the standard library alone, melody_sampler.py plays that
plan with 66,028 recorded instrument one-shots, and the register sweep re-renders one finished
song with ten different singers. So nothing here is a text-to-audio guess and almost everything
is checkable ON THE PLAN, symbolically, before a single sample is written — which is exactly why
the step exists and why its columns are theory questions (harmony, voice leading, prosody,
rhyme, range) rather than "does it sound right".

Shape of the test: ONE fixed brief — a 60 s preschool storytime song in D major at 96 BPM, 4/4,
with the four-line lyric and the stress marks written out here — composed at seed 11 and again at
seed 12 (that second plan is the whole of `variety`), plus a THIRD brief identical to the first
except that it asks for a modulation to G at bar 21. Every plan column is measured on the plan's
own note data; the three columns that need sound (key as RENDERED, singable as rendered, age_fit)
are measured on the sampler's render; `register` is a LOOKUP against the farmyard sweep receipts,
because a sung register was measured there once and properly (RMVPE + SwiftF0, confidence-weighted
median with p10/p90) and re-guessing it from a fresh listen would be worse evidence, not better.

What is blocked and why: nothing. Every input of this test is text in this module and every
artefact is the row's own output, so there is no answer key for an operator to verify first. The
honest gaps are written as `na` with their reasons, per row: the sampler is a PLAYER and is not
asked whether the tune it was handed rhymes, and the register sweep holds the plan fixed by
construction, so the plan columns would score the planner twice if they were read off it.
"""

from __future__ import annotations

# ── check kinds this module adds (the runner is a table of these) ──────────────────────
CHECK_KINDS = {
    'pitch_range_within': 'every sung note of the plan (and of the vocal stem, where there is one: RMVPE median per note) lies between MIDI `low` and `high` inclusive, and the total span is <= `max_semitones`',
    'key_equals': "the key named by Krumhansl-Schmuckler profile correlation — on the plan's pitch-class histogram for a symbolic row, on the whole-file CQT chroma for a rendered one — equals `key` and `mode`, enharmonic spellings accepted",
    'melody_edit_distance_min': "Levenshtein distance between the two runs' SCALE-DEGREE sequences (the plan's own integer scale indices, duration ignored), divided by the length of the longer sequence, >= `min`",
    'rest_every_bars': 'in the sung body, a rest of >= `min_beats` quarter-note beats occurs at least once in every window of `max_bars` bars',
    'stress_on_beat_min': 'share of the syllables marked stressed in `stress` that land on a strong beat of their bar (0.0 and 2.0 in 4/4; 0.0 and 1.5 in 6/8) >= `min`',
    'rhyme_scheme': 'the last words of the lyric lines rhyme according to `scheme`: same CMUdict rhyme tail (final stressed vowel onward) for letters that match, a different tail for letters that do not; orthographic tail as the fallback for a word CMUdict does not hold',
    'syllables_per_bar': 'for each lyric line, the syllable count equals the number of sung notes across the bars that line occupies, within +/- `tolerance`',
    'parallel_fifths_count': "consecutive parallel perfect fifths or perfect octaves between any two voices of the plan's voicing, counted over every pair of adjacent chord changes, <= `max`",
    'max_leap_semitones': 'no melodic interval between consecutive notes of one voice exceeds `max` semitones',
    'modulation_at_bar': 'the key estimate of the `window_bars`-bar window after bar `bar` differs from the window before it by exactly `semitones` semitones of tonic, in the direction asked',
    'distinct_durations_min': 'the number of distinct note-duration values in the sung body >= `min`',
    'instrument_range_ok': "every note assigned to a voice lies inside that instrument's WRITTEN range in `ranges` (MIDI low/high per voice key); a note outside it is counted and the count must be 0",
    'parses_as': 'EXTENDS the base kind with the score formats and changes nothing about srt|vtt: the file parses as `format` — srt|vtt with a strict subtitle parser, midi with mido, musicxml with music21 — and is non-empty',
}

# ── the brief: one plan, composed twice, plus a modulation variant ─────────────────────
BRIEF = {
    'age_band': 'preschool',
    'mood': 'bright',
    'style': 'storytime',
    'family': 'children',
    'tonic': 'D',
    'mode': 'major',
    'bpm': 96,
    'meter': '4/4',
    'seconds': 60,
    'voices': {'lead': 'recorder', 'pad': 'guitar_nylon', 'bass': 'double_bass_pizz'},
    'note': (
        'the same brief kids_music_theory.compose(brief, seed=...) takes. `family` is given '
        'explicitly because "storytime" exists in BOTH the children and the cinematic style '
        'table and the default family would silently compose the preschool song either way — '
        'this test wants the preschool song and says so.'
    ),
}
BRIEF_MOD = dict(
    BRIEF,
    modulate_to='G',
    modulate_at_bar=21,
    note='identical to BRIEF except for the modulation request; nothing else moves',
)

SEEDS = [11, 12]

LYRIC = (
    'The lantern on the harbour wall\n'
    'is shining for the boats that call\n'
    'The water taps against the stone\n'
    'and no one has to sail alone'
)
# 1-based syllable index per line. The TEST's fixed reading of the lyric — a runner may not
# re-scan it, and the same marks are used on the music_gen sheet so the two steps agree.
STRESS = {1: [2, 6, 8], 2: [2, 6, 8], 3: [2, 4, 6, 8], 4: [2, 4, 6, 8]}
LYRIC_FACTS = {
    'lines': 4,
    'syllables_per_line': 8,
    'rhyme_scheme': 'AABB',
    'rhymes': {'A': ['wall', 'call'], 'B': ['stone', 'alone']},
    'bars': 'one line per TWO bars — the budget kids_music_theory._syllable_targets uses',
}

# The SINGABLE band. The TEST's fixed standard, as the subtitles test fixes its cue durations:
# C4-D5, span at most 14 semitones. kids_music_theory's own docstring pins a toddler group at
# roughly C4-C5 and the module's AGE_BANDS holds the live numbers; where they disagree with these,
# the TEST's numbers decide the column and the sheet note records the module's value, so a change
# in the module shows up as a failure rather than as a silently moved goalpost.
SINGABLE = {'band': 'preschool', 'low': 60, 'high': 74, 'max_semitones': 14, 'low_name': 'C4', 'high_name': 'D5'}

# Written instrument ranges, MIDI low/high, for the three voices the brief names.
RANGES = {
    'recorder': [72, 98],  # soprano recorder C5-D7
    'guitar_nylon': [40, 83],  # nylon-string guitar E2-B5, written pitch
    'double_bass_pizz': [28, 55],  # double bass E1-G3
    'note': 'written ranges, not sounding: the guitar and the bass are notated an octave above their sound and the check compares written to written',
}

COND = {
    'seeds': SEEDS,
    'repeats': 2,
    'seconds': 60,
    'sample_rate_out': 48000,
    'channels': 1,
    'note': 'the brief composed at seeds 11 and 12; repeats = 2 because the planner is deterministic per seed and a third identical plan buys nothing',
}
COND_ONE = dict(COND, seeds=[11], repeats=1)
COND_MOD = dict(COND_ONE, note='the modulation brief, one composition at seed 11')

ALL = ['theory', 'sampler', 'registers']


def _p(pid, title, feeds, checks, cond=None, inputs=None, **kw):
    p = {
        'id': pid,
        'title': title,
        'feeds': list(feeds),
        'inputs': dict(
            inputs
            or {'task': 'compose(BRIEF, seed=<seed>) and measure the plan it returns', 'brief': BRIEF, 'lyric': LYRIC}
        ),
        'conditions': dict(cond or COND),
        'checks': list(checks),
        'grade': 'measured',
        'rows': list(ALL),
    }
    p.update(kw)
    return p


PROBES = [
    _p(
        'singable',
        'Sits in a singable range',
        ['singable'],
        [
            {
                'check': 'pitch_range_within',
                'low': SINGABLE['low'],
                'high': SINGABLE['high'],
                'max_semitones': SINGABLE['max_semitones'],
                'band': 'preschool',
            }
        ],
        state_note=(
            "measured on the plan's note data for the planner and on the RMVPE per-note median of "
            'the vocal stem for a rendered row. Both seeds inside C4-D5 with a span of at most 14 '
            "semitones = yes; one seed outside = partial. The band is the TEST's fixed standard "
            "(see SINGABLE) and the module's own AGE_BANDS value goes in the sheet note."
        ),
    ),
    _p(
        'key',
        'Key and mode are correct',
        ['key'],
        [{'check': 'key_equals', 'key': 'D', 'mode': 'major'}],
        state_note=(
            "the brief asks for D major. For the planner the estimate runs on the plan's "
            'pitch-class histogram (it is diatonic by construction, so this is the control that '
            'says the measurement works); for the sampler and the sweep it runs on the render, '
            'which is where a varispeed or a pitch-shift error would show.'
        ),
    ),
    _p(
        'variety',
        'Two runs are not the same tune',
        ['variety'],
        [
            {'check': 'melody_edit_distance_min', 'min': 0.35, 'against': 'the seed 12 plan'},
            {'check': 'melody_edit_distance_min', 'min': 0.15, 'against': 'the seed 12 plan'},
        ],
        state_note=(
            'seed 11 against seed 12, same brief. Normalised scale-degree edit distance >= 0.35 = '
            'yes, >= 0.15 = partial, below that the seed is decoration. The two thresholds are '
            'written as TWO checks on the one comparison so the partial band is mechanical: both '
            'pass = yes (2/2), only the 0.15 check passes = partial (1/2), neither = no. Note that '
            'a CONSTRAINED composer is allowed to be less various than a model — the constraints '
            'are the point — so a partial here is a fact about the search space, and the sheet '
            'note must say so.'
        ),
        state_rule={'yes': 1.0, 'partial': 0.5},
    ),
    _p(
        'phrase',
        'Phrases breathe',
        ['phrase'],
        [{'check': 'rest_every_bars', 'min_beats': 0.5, 'max_bars': 4}],
        state_note="a singer must get a breath at least every four bars, and half a beat is the shortest thing that counts as one. Measured on the sung body only — intro and outro are excluded, as they are in the module's own density budget.",
    ),
    _p(
        'prosody',
        'Stress lands on the right syllable',
        ['prosody'],
        [{'check': 'stress_on_beat_min', 'min': 0.80, 'stress': STRESS}],
        state_note="the stress marks are STRESS in this module, not a runner's scan of the lyric. 80 % of marked syllables on a strong beat = yes; this is the column that catches a tune written to the notes and fitted to the words afterwards.",
    ),
    _p(
        'rhyme',
        'Rhyme scheme holds',
        ['rhyme'],
        [{'check': 'rhyme_scheme', 'scheme': 'AABB', 'lines': 4}],
        state_note='wall/call and stone/alone. A planner that does not touch the lyric it was given passes this trivially, and that trivial pass is the honest answer: the column asks whether the scheme SURVIVES, not whether the row invented it.',
    ),
    _p(
        'syllables',
        'Syllable count fits the bar',
        ['syllables'],
        [{'check': 'syllables_per_bar', 'tolerance': 1, 'lines': 4, 'syllables_per_line': 8}],
        state_note=(
            'eight syllables per line over two bars. The house already knows where this breaks: '
            '_syllable_targets budgets one lyric line per TWO BARS regardless of metre, so a 2/4 '
            'brief lands at twice the notes per second of a 4/4 one and fails the density gate at '
            'every tempo above 84 BPM. This test asks 4/4 and the note records that 2/4 is a known no.'
        ),
    ),
    _p(
        'harmony',
        'Harmony is correct',
        ['harmony'],
        [{'check': 'parallel_fifths_count', 'max': 0}],
        state_note='zero parallel fifths or octaves between any two voices of the voicing. A count above zero is a no with the bar numbers on the trial, which is a repairable fact rather than a verdict.',
    ),
    _p(
        'voice_leading',
        'Voice leading is clean',
        ['voice_leading'],
        [{'check': 'max_leap_semitones', 'max': 12}],
        state_note='no leap larger than an octave in any voice. The planner searches with stepwise motion as the cheapest move, so this is another positive control: a failure here means the search was overridden, not that the rule is hard.',
    ),
    _p(
        'modulation',
        'Can modulate',
        ['modulation'],
        [{'check': 'modulation_at_bar', 'bar': 21, 'semitones': 5, 'window_bars': 4, 'direction': 'up'}],
        cond=COND_MOD,
        inputs={
            'task': 'compose(BRIEF_MOD, seed=11) — the same brief with a modulation to G at bar 21',
            'brief': BRIEF_MOD,
            'lyric': LYRIC,
        },
        state_note=(
            'D to G is +5 semitones of tonic, asked at bar 21 (the bridge). If the row has no '
            'modulation field at all the call either raises or silently ignores the key, and BOTH '
            'of those are a `no` on this column — "it cannot modulate" is a measurement of the '
            'capability, not a broken test. A raise is recorded on the trial verbatim so the '
            'sheet note can say which of the two happened.'
        ),
    ),
    _p(
        'rhythm',
        'Rhythmic interest',
        ['rhythm'],
        [{'check': 'distinct_durations_min', 'min': 3}],
        state_note='at least three distinct note durations in the sung body. Two (all crotchets and one minim) is the shape a constraint search falls into and is a partial, not a no.',
    ),
    _p(
        'instrument_range',
        "Stays in each instrument's range",
        ['instrument_range'],
        [{'check': 'instrument_range_ok', 'ranges': {k: v for k, v in RANGES.items() if k != 'note'}}],
        state_note=(
            'the three voices the brief names, against the written ranges in RANGES. This is the '
            'column the sampler can genuinely fail: it picks the nearest recorded pitch and '
            'varispeeds to the asked note, so a note below the lowest sample in a pack comes out '
            'as a stretched impostor rather than as an error.'
        ),
    ),
    _p(
        'export',
        'Exports usable score data',
        ['export'],
        [{'check': 'parses_as', 'format': 'midi'}, {'check': 'parses_as', 'format': 'musicxml'}],
        cond=COND_ONE,
        state_note='text column: "midi+musicxml" | "midi" | "musicxml" | "neither". MIDI through mido, MusicXML through music21; an empty part list is a no even when the file parses.',
    ),
    _p(
        'age_fit',
        'Fits the target age group',
        ['age_fit'],
        [
            {
                'check': 'operator',
                'blind': True,
                'question': 'Could a room of four- to six-year-olds sing this back after hearing it twice? yes/no',
            }
        ],
        state_note=(
            'the OPERATOR decides, on the sampler render. No local model is asked: the defect-judge '
            'bench of 2026-09-27 (best model 34/40 on a global question, 2/8 on the hard cases) is '
            'why. The mechanical halves of the same worry — range, phrase length, note density — '
            "are singable, phrase and the module's own score_plan density gate, and all three "
            'numbers go on the trial beside the human answer.'
        ),
    ),
    _p(
        'failsafe',
        'Fails without breaking the caller',
        ['failsafe'],
        [
            {
                'check': 'operator',
                'blind': False,
                'question': 'Did the call return a value or raise a caught exception, leaving the process alive and the GPU free? yes/no',
            },
            {
                'check': 'file_absent',
                'path': 'output/capabilities/failsafe/partial.wav',
                'note': 'a half-written file left behind is a fail',
            },
        ],
        cond=dict(COND_ONE, repeats=3),
        inputs={
            'task': (
                'call the row on a DELIBERATELY broken input three ways, exactly as the audio '
                "bank's u_failsafe does: (1) prompt (or brief) = the empty string; (2) audio = "
                'capability_tests/fixtures/audio/judge/truncated.wav; (3) seconds = 0. For the '
                'planner rows the first case is compose({}), which is the call that found the '
                'cinematic KeyError on 2026-09-06'
            )
        },
        state_note=(
            'THIS PROBE IS A LOCAL COPY of audio_shared.u_failsafe, word for word: the bank carries '
            'its fixed input under `inputs.command`, which the validator does not count as a fixed '
            "input, so a step that merges the bank fails `check` on the bank's own probe. Owning "
            'the column here keeps the test identical in substance and leaves the bank untouched. '
            'When the bank moves that string to `inputs.task`, delete this probe and the shared '
            'version comes back automatically.'
        ),
    ),
]

# ── what a row cannot answer, with the reason written out ──────────────────────────────
NA_BANDS_PLAN = {
    'reason': (
        'this row is handed a plan OBJECT — a dict of key, metre, tempo, sections, '
        'notes and voices — and not a written prompt: there is no text to damage, '
        'shorten, translate, re-order or weight, and inventing one would measure the '
        'test rather than the row. The one prompt-shaped question that does apply, '
        'whether the brief is recorded with the plan, is the `receipts` column'
    ),
    'bands': ['Prompt: damage', 'Prompt: clarity needed', 'Prompt: limits', 'Prompt: steering'],
}

_PLAN_ONLY = (
    'this is a property of the PLAN the row is handed, not of the row: it plays (or re-sings) '
    'whatever notes it receives, so reading this column off its output would score the planner '
    "a second time under another row's name"
)
SAMPLER_NA = {
    c: _PLAN_ONLY
    for c in ('variety', 'phrase', 'prosody', 'rhyme', 'syllables', 'harmony', 'voice_leading', 'modulation', 'rhythm')
}
SAMPLER_NA['export'] = (
    'melody_sampler.render_plan writes a wav and a manifest; it has no score writer, '
    'so there is no MIDI or MusicXML of its own to parse'
)
REG_NA = {
    c: _PLAN_ONLY
    for c in ('variety', 'phrase', 'prosody', 'rhyme', 'syllables', 'harmony', 'voice_leading', 'modulation', 'rhythm')
}
REG_NA['export'] = 'the sweep re-renders finished audio; it produces no score data of any kind to export'
REG_NA['instrument_range'] = (
    'the sweep moves the SINGER and nothing else — the instruments, the notes '
    'and the arrangement are held fixed by construction, so the instrument '
    'ranges it reports are the ones the sampler row already answered'
)

TEST = {
    'step': 'melody',
    'version': '2026-09-30.1',
    'title': 'One brief, composed twice, measured on the plan before anything renders it',
    'purpose': (
        'Measure the symbolic plan as MUSIC — range, key, phrasing, prosody, rhyme, syllable fit, '
        'harmony, voice leading, modulation, rhythmic variety, instrument ranges and export — on '
        "the plan's own note data, mechanically, and keep the three questions that need sound "
        '(the rendered key, the rendered range, and whether a five-year-old could sing it back) '
        'on the render where they belong.'
    ),
    'include_shared': 'audio',
    'brief': {
        'plan': BRIEF,
        'modulation': BRIEF_MOD,
        'seeds': SEEDS,
        'lyric': LYRIC,
        'stress': STRESS,
        'lyric_facts': LYRIC_FACTS,
        'singable': SINGABLE,
        'ranges': RANGES,
    },
    'rows': {
        'theory': {
            'transport': 'service',
            'model': 'kids_music_theory.compose / compose_best / score_plan — a deterministic '
            'constraint search in the standard library: no weights, no licence surface',
            'na': {
                'register': (
                    'the planner writes notes, not a singer: the sung register is cast '
                    'at render time by the ACE-Step caption, so this column belongs to '
                    'the rows that render a voice'
                ),
                'age_fit': (
                    'there is nothing to listen to — the planner emits a plan. The '
                    'mechanical halves of the question (range, phrase length, note '
                    "density) are singable, phrase and the module's own score_plan "
                    'density gate, all of which this row does answer'
                ),
            },
            'na_bands': NA_BANDS_PLAN,
            'budget': {
                'calls': 232,
                'minutes': 2,
                'gpu_minutes': 0,
                'operator_minutes': 6,
                'note': 'pure python: a compose() call is milliseconds, so ~232 plan builds is under 2 minutes of CPU and no GPU at all. Only the failsafe probe asks the operator anything.',
            },
        },
        'sampler': {
            'transport': 'service',
            'model': 'melody_sampler.render_plan / render_events / arrange_cinematic — 66,028 '
            'licence-clean instrument one-shots (data/asset_libraries/instruments, '
            '48 kHz PCM_16), nearest-pitch pick plus varispeed, no time-stretch',
            'na': SAMPLER_NA,
            'na_bands': NA_BANDS_PLAN,
            'budget': {
                'calls': 235,
                'minutes': 25,
                'gpu_minutes': 0,
                'operator_minutes': 25,
                'note': 'CPU DSP at roughly 3x real time: ~235 renders averaging ~6 s of audio is ~25 min with no GPU. The operator hears the age_fit take and the capacity ladders, ~50 decisions.',
            },
        },
        'registers': {
            'transport': 'service',
            'model': 'the register / voice sweeps — tools/farmyard_ref/voice_sweep.py '
            '(project_farmyard_voice_sweep) and build_farmyard_singers.py: one '
            'finished song re-rendered with ten singer clauses through the a2a '
            'melody-conditioned ACE-Step graph, each take gated and mastered',
            'na': REG_NA,
            'budget': {
                'calls': 40,
                'minutes': 95,
                'gpu_minutes': 88,
                'operator_minutes': 30,
                'note': '10 singer clauses x 3 takes = 30 a2a renders of a full song at ~2.5 min each plus demucs stemming and the F0 gate per take = ~88 GPU minutes; the prompt bands DO apply to this row (the caption is a real prompt) and add ~10 short renders.',
            },
        },
    },
    'probes': PROBES,
    'derive': {},
    'lookup': {
        'register': {
            'question': (
                'What sung register did this row actually produce, measured — median F0 '
                'with p10/p90, not a mean, and not a listen?'
            ),
            'requires': [
                'the sweep receipts under output/kidsmusic/<id>/voice_sweep/ — the '
                'picked take, its caption and its seed, both recorded so the take can '
                'be reproduced exactly (tools/farmyard_ref/voice_sweep.py: a "voice" is '
                'the PAIR (caption, seed))',
                'the sung_pitch.py report for that take: RMVPE (rmvpe-onnx, MIT) '
                'confidence-weighted median with p10/p90, cross-checked by SwiftF0 with '
                'the disagreement in cents, plus the sharpness/brightness axis',
                'the date the sweep was run and the graph revision it ran on',
            ],
            'grade': 'receipt',
            'note': (
                'a LOOKUP and not a probe, deliberately. The register was already measured '
                'properly once: the picked Farmyard take reads median ~406 Hz, p95 736 Hz '
                'and a 1162 Hz peak, which is precisely the material that broke the ordinary '
                'Praat meter (pitch_ceiling 550 Hz censored whole frame sets and made the '
                'median move NON-MONOTONICALLY under pitch shift, so -3 st once read higher '
                'than -2 st). A fresh listen or a fresh Praat pass would be worse evidence '
                'than the receipt. The column is `no` for any row with no such receipt — '
                'that is what "measured, not assumed" means here.'
            ),
        },
    },
    'wiring': {
        'shared_plan': {
            'reads': (
                'the call graph from one compose() result outward: '
                'kids_music_theory.compose(brief) -> plan, then '
                'kids_music_service.py lines 1-21 (the docstring contract: "Two audio '
                'legs from ONE symbolic plan", leg A render_soundfont and leg B ACE-Step '
                'given the SAME bpm, time signature, key and lyrics), then '
                'melody_sampler.py lines 28-34 (render_plan(plan, out_wav, voices=...) '
                'in the fixed public API), and finally the video leg — grep for the plan '
                'or brief dict reaching kids_video_service (reassemble / the style keys '
                'it carries forward)'
            ),
            'rule': (
                'yes when ONE plan object reaches every leg and no leg re-derives the '
                'key, tempo, metre or lyric for itself; partial when a leg is handed '
                'scalar fields copied out of the plan instead of the plan (a copy can '
                'drift); no when a leg composes or re-parses its own. Recorded as READ, '
                'never run, and graded assumed — the honest measurement would be to '
                'change one field in the plan and watch which legs move, which is a '
                'whole-pipeline run and belongs on the workflow sheet, not here'
            ),
            'grade': 'assumed',
        },
    },
    'na': {},
    'fixtures': [],
    'run_order': [
        'key',
        'singable',
        'phrase',
        'rhythm',
        'syllables',
        'harmony',
        'voice_leading',
        'prosody',
        'rhyme',
        'instrument_range',
        'export',
        'variety',
        'modulation',
        'failsafe',
        'age_fit',
        'shared:audio',
    ],
    'run_order_note': (
        'every symbolic probe first — they are milliseconds of CPU on a plan that is '
        'already in memory, so a run that dies after ten seconds has still filled eleven '
        'columns. The second seed (variety) and the modulation brief come next, the '
        'operator listens last, and the shared bank — ~228 short renders for the capacity '
        'ladders and, on the registers row only, the prompt bands — is the tail.'
    ),
    'budget': {
        'calls': 235,
        'tokens_in': 0,
        'tokens_out': 0,
        'tokens_note': 'a constraint search and a sampler take a plan dict and a voice key, not chat turns; no language-model tokens are spent on this step and no Claude meter is touched',
        'minutes': 25,
        'gpu_minutes': 0,
        'operator_minutes': 25,
        'note': (
            'Per row: 14 domain calls (2 seeds of the brief, 1 modulation brief, 1 export, 3 broken '
            'failsafe calls, and the renders the sound columns need), plus the SHARED AUDIO BANK for '
            'this step — the same 48 bank probes that run on music_gen (7 capacity ladders at ~5 '
            'rungs x 3 seeds = 105, and 41 prompt/universal probes x 3 seeds = ~123) = ~228 short '
            'items: 235 calls. The test-level numbers are the SAMPLER row (CPU DSP at ~3x real time, '
            '~25 min, no GPU, ~50 operator decisions at 30 s). The other two override it: theory is '
            'milliseconds per plan (~2 min, 0 GPU) and registers is the only GPU row (30 a2a song '
            'renders at ~2.5 min = ~88 GPU minutes). Sum over the rows as the loader reports it: '
            '~122 min wall, 88 of them on the GPU. No Claude week is spent — there is no claude_cli '
            'or anthropic_api row on this step. NOT in these numbers, because it is not per row: the '
            'register LOOKUP is already paid for, its receipt exists.'
        ),
    },
    'notes': [
        'This step has NO model and no weights: kids_music_theory is plain python and the standard '
        'library. That is why almost every column is measured symbolically and why `deterministic` is '
        'expected to be a real yes rather than a GPU maybe — and why a failure anywhere here is a bug '
        "with a line number, not a model's bad day.",
        'The style tables are two, never merged: STYLES (11 children\'s styles, family "children") and '
        'CINEMATIC_STYLES (13, family "cinematic"). "storytime" is in BOTH and the default family is '
        '"children", so BRIEF names family explicitly. A runner that drops that key composes a different '
        'song and the whole sheet moves.',
        '2/4 is effectively uncomposable for a sung band on this row and it is a known, measured no: '
        '_syllable_targets budgets one lyric line per TWO BARS regardless of metre, so a toddler 2/4 brief '
        'at 110 BPM lands at 2.29 notes/s against a 1.80 cap on all 48 seeds and the first passing tempo '
        'is 84 BPM. This test asks 4/4 on purpose; the `syllables` note carries the 2/4 fact so nobody '
        'reads a pass here as a pass there.',
        "The licence seam of the score leg: melody_sampler's `philharmonia` pack is "
        'royalty-free-verified and carries no_ai_training = True. Rendering it is ordinary DSP and is '
        "fine; feeding the result to ACE-Step as audio conditioning is NOT. The bank's `ai_training` and "
        "`licence` lookups must read render_plan()['packs'] for the sampler row, not a vendor page.",
        'The audio bank exempts the whole `service` transport from pd_tag_vocab, meant for the DSP rack '
        'rows. It is correct for theory and sampler (both take a plan object) and WRONG for registers, '
        "whose singer clause is a real ACE-Step tag caption — that row must answer the column. The bank's "
        'own note says so; the runner has to honour it per row, not per transport.',
    ],
}
