# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""``_p`` and the PROBES list — every probe the tts sheet runs, section 5."""

from __future__ import annotations

from .constants import (
    AGED,
    BANDS,
    COND,
    COND_ONE,
    COS_MARGIN,
    COS_MIN,
    COS_TAKES,
    COS_WINDOW,
    F0_PCT,
    LINES,
    OVERLONG,
    PASSAGE,
    VTL_CM,
)


def _p(pid, title, feeds, checks, inputs, cond=None, **kw):
    p = {
        'id': pid,
        'title': title,
        'feeds': list(feeds),
        'inputs': dict(inputs),
        'conditions': dict(cond or COND),
        'checks': list(checks),
        'grade': 'measured',
    }
    p.update(kw)
    return p


_REF_COS = {'check': 'speaker_cosine_min', 'to': 'REFERENCE', 'min': COS_MIN, 'margin': COS_MARGIN}

PROBES = [
    # ── Identity ──
    _p(
        'zero_shot',
        'Clones the reference with no training',
        ['zero_shot'],
        [_REF_COS, {'check': 'f0_vtl_band', 'to': 'REFERENCE', 'f0_pct': F0_PCT, 'vtl_cm': VTL_CM}],
        {'prompt': LINES['ledger_open'], 'audio': 'REFERENCE (first 10.0 s)'},
        run_order=3,
        state_note='both references x three seeds = 6 takes; yes needs 5 of 6 under the default rule',
    ),
    _p(
        'quiet_fail',
        'Fails loudly, never with a silent wav',
        ['quiet_fail'],
        [
            {'check': 'error_surfaced', 'on': 'empty', 'silent_wav_s': 0.5, 'timeout_s': 300},
            {'check': 'error_surfaced', 'on': 'overlong', 'silent_wav_s': 0.5, 'timeout_s': 300},
        ],
        {'prompt': ['', OVERLONG], 'audio': 'REFERENCE (first 10.0 s)'},
        cond=COND_ONE,
        run_order=1,
        state_note=(
            "the cheapest probe in the test and the one the sheet's verdict is about. "
            'Two degenerate inputs: the empty string and a 1800-word single line. yes = '
            'both surface an error the caller can test; partial = one does; no = a wav '
            'comes back that nobody can tell from a good one. A call still running at '
            '300 s is a timeout and scores no.'
        ),
    ),
    _p(
        'similarity',
        'Sounds like the reference across four registers',
        ['similarity'],
        [
            _REF_COS,
            {
                'check': 'operator',
                'blind': True,
                'question': 'A then B: is this the same person speaking in both clips? yes/no',
            },
        ],
        {
            'prompt': [LINES['epigraph'], LINES['modern_plain'], LINES['sibilance'], LINES['dutch_plain']],
            'audio': 'REFERENCE (first 10.0 s)',
        },
        run_order=4,
        state_note=(
            'four lines x two references x three seeds = 24 takes. The operator pair is '
            'the reference clip against the take, presented in random order per trial.'
        ),
    ),
    _p(
        'long_form',
        'Holds the voice over four minutes',
        ['long_form'],
        [
            {'check': 'speaker_cosine_window_min', 'window_s': 30, 'min': COS_WINDOW},
            {'check': 'f0_drift_max', 'window_s': 30, 'max_pct': F0_PCT},
            _REF_COS,
        ],
        {'prompt': PASSAGE + ' (first 600 words)', 'fixture': PASSAGE, 'audio': 'REFERENCE (first 10.0 s)'},
        cond=COND_ONE,
        run_order=9,
        state_note="the last 30 s against the take's OWN first 30 s, so a drift is visible without a reference",
    ),
    _p(
        'across_takes',
        'Same voice in three separate sessions',
        ['across_takes'],
        [{'check': 'speaker_cosine_pairwise_min', 'min': COS_TAKES}, _REF_COS],
        {'prompt': LINES['ledger_open'], 'audio': 'REFERENCE (first 10.0 s)'},
        conditions_override={'sessions': 3, 'seed': 11},
        cond=dict(
            COND,
            seeds=[11],
            repeats=3,
            note='three SEPARATE process starts at the same seed 11 — model reloaded each time, which '
            'is what "today matches last week" actually means; both references',
        ),
        run_order=8,
    ),
    # ── Age & sex ──
    _p(
        'child',
        'Holds a young voice on F0 AND vocal-tract length',
        ['child'],
        [
            {'check': 'f0_median_range', 'min': BANDS['child']['f0'][0], 'max': BANDS['child']['f0'][1]},
            {'check': 'vtl_range', 'min': BANDS['child']['vtl'][0], 'max': BANDS['child']['vtl'][1]},
            {'check': 'f0_vtl_band', 'to': 'abel_identity_reference', 'f0_pct': F0_PCT, 'vtl_cm': VTL_CM},
            {
                'check': 'operator',
                'blind': True,
                'question': 'Is the speaker in this clip a child (roughly under twelve), rather than a teenager, a woman or an adult man in falsetto? yes/no',
            },
        ],
        {'prompt': LINES['epigraph'], 'audio': 'child_reference.wav AND abel_narrator_seed.wav'},
        cond=dict(COND_ONE, references=['child', 'abel']),
        run_order=12,
        state_note=(
            'BLOCKED until fixtures/tts/child_reference.wav is verified. Two legs: the child '
            'reference decides the column; the Abel leg is measured and recorded but CANNOT decide '
            'it, because Abel is teen_male by design (voice_age 14-15, seed 171.9 Hz / 14.64 cm, '
            'Chatterbox render 154.8 Hz / 15.94 cm — the tract grew 1.3 cm). The Abel leg is scored '
            'against the teen_male band and reported in the cell note.'
        ),
    ),
    _p(
        'elderly',
        'Holds an elderly voice',
        ['elderly'],
        [
            {'check': 'f0_vtl_band', 'to': 'elder', 'f0_pct': F0_PCT, 'vtl_cm': VTL_CM},
            {
                'check': 'operator',
                'blind': True,
                'question': 'Does this clip sound like a man in his sixties — weathered, unhurried — rather than a younger man reading slowly? yes/no',
            },
        ],
        {'prompt': LINES['ledger_open'], 'audio': AGED['elder']['wav'] + ' (first 10.0 s)'},
        cond=dict(COND_ONE, references=['elder']),
        run_order=11,
        state_note=(
            'the operator decides. The cornelis bench (2026-08-21) records why: "VTL is unreliable '
            'on worn voices" — rank on render wear and render F0. The f0_vtl_band leg is still '
            'measured, and a disagreement between meter and operator is written into the trial.'
        ),
    ),
    _p(
        'sex',
        "Holds the reference's sex",
        ['sex'],
        [
            {'check': 'f0_vtl_band', 'to': 'REFERENCE', 'f0_pct': F0_PCT, 'vtl_cm': VTL_CM},
            {'check': 'f0_median_range', 'band': 'BY_REFERENCE_SEX'},
            {'check': 'vtl_range', 'band': 'BY_REFERENCE_SEX'},
        ],
        {'prompt': LINES['ledger_open'], 'audio': 'REFERENCE (first 10.0 s)'},
        reuses='zero_shot',
        run_order=5,
        state_note=(
            'scored on the zero_shot renders — same line, same references, same seeds — so it costs '
            'no extra call. The absolute band is adult_male (F0 <= 165 Hz, VTL >= 15.5 cm) for m01 '
            'and adult_female (150-230 Hz, VTL <= 15.5 cm) for f01, from voice_qc.AGE_BANDS.'
        ),
    ),
    _p(
        'age_stable',
        'Does not age the speaker mid-render',
        ['age_stable'],
        [
            {'check': 'f0_drift_max', 'window_s': 30, 'max_pct': F0_PCT},
            {'check': 'speaker_cosine_window_min', 'window_s': 30, 'min': COS_WINDOW},
        ],
        {'prompt': PASSAGE + ' (first 225 words, ~90 s)', 'fixture': PASSAGE, 'audio': 'REFERENCE (first 10.0 s)'},
        cond=COND_ONE,
        run_order=10,
    ),
    # ── Performance ──
    _p(
        'emotion',
        'Takes emotional direction',
        ['emotion'],
        [
            {'check': 'prosody_delta_min', 'min': 2.0},
            {
                'check': 'operator',
                'blind': True,
                'question': 'A then B: do these two readings of the same sentence carry DIFFERENT emotions, and is the second the more urgent of the two? yes/no',
            },
            _REF_COS,
        ],
        {
            'prompt': LINES['ledger_open'],
            'directions': [
                'read it flat, no colour',
                'grieving, barely holding it together',
                'urgent, pressed for time',
                'warm, telling it to a friend',
            ],
        },
        cond=COND_ONE,
        run_order=13,
        state_note=(
            'four directions, each a separate render of the SAME line. prosody_delta_min is measured '
            'between the flat control and each directed take (>= 2 semitones of median F0 or 2 per '
            'cent of rate); the operator pair is flat-vs-urgent. The identity check is there because '
            'a direction that changes the speaker is not direction. A row whose transport takes no '
            'direction field renders the direction as a prefix line and the note records that.'
        ),
    ),
    _p(
        'pace',
        'Takes a pace direction',
        ['pace'],
        [{'check': 'wpm_range', 'wpm': 'ASKED', 'tolerance_pct': 15}],
        {
            'prompt': LINES['ledger_open'],
            'directions': ['120 words per minute', '150 words per minute', '190 words per minute'],
        },
        cond=COND_ONE,
        run_order=6,
        state_note='mechanical and cheap: Whisper word timestamps over the input word count, within 15 % of each ask',
    ),
    _p(
        'emphasis',
        'Emphasises the word we mark',
        ['emphasis'],
        [{'check': 'emphasis_db_min', 'word': 'ledgers', 'min_db': 3.0}],
        {'prompt': LINES['ledger_open'], 'directions': ['stress the word "ledgers"', None]},
        cond=COND_ONE,
        run_order=7,
        state_note=(
            'a pair per seed: marked and unmarked control. The marked take must put the word 3 dB '
            'over its neighbours AND the control must not — an engine that always stresses that word '
            'is not obeying anything.'
        ),
    ),
    _p(
        'whisper_shout',
        'Reaches whisper and shout',
        ['whisper_shout'],
        [
            {'check': 'rms_dbfs_range', 'leg': 'whisper', 'min': -34.0, 'max': -26.0},
            {'check': 'rms_dbfs_range', 'leg': 'shout', 'min': -16.0, 'max': -8.0},
            {'check': 'rms_delta_db', 'louder': 'shout', 'quieter': 'whisper', 'min': 12.0},
            {
                'check': 'operator',
                'blind': True,
                'question': 'Is this a whispered delivery (breathy, unvoiced, close) rather than a quiet normal voice? yes/no',
            },
        ],
        {'prompt': LINES['dynamics'], 'directions': ['whispered, barely audible', 'shouted across the yard']},
        cond=COND_ONE,
        run_order=14,
        state_note=(
            "the targets are the brief's -30 and -12 dBFS with a +/- 4 dB band, on the RAW output "
            'before loudnorm. The operator leg exists because a gain change is not a whisper: an '
            'engine that simply turns down passes the meters and fails the ear.'
        ),
    ),
    _p(
        'breath',
        'Breathes in the right places',
        ['breath'],
        [
            {'check': 'pause_ms', 'after': 'comma', 'min': 150, 'max': 400},
            {
                'check': 'operator',
                'blind': True,
                'question': 'Is there an audible intake of breath at the two commas in this line, and nowhere mid-word? yes/no',
            },
        ],
        {'prompt': LINES['epigraph'], 'audio': 'REFERENCE (first 10.0 s)'},
        reuses='similarity',
        run_order=15,
        state_note=(
            'scored on the similarity renders of the epigraph, so it costs no extra call. No breath '
            'detector exists in the house, and the 2026-09-27 defect bench is why none is improvised: '
            'the operator decides and the comma pause is the only mechanical half.'
        ),
    ),
    _p(
        'wear',
        'Can sound worn or tired',
        ['wear'],
        [
            {
                'check': 'operator',
                'blind': True,
                'question': 'Does this voice sound worn — gravel, breath loss, a tired instrument — rather than merely low or slow? yes/no',
            },
            {'check': 'f0_vtl_band', 'to': 'elder', 'f0_pct': F0_PCT, 'vtl_cm': VTL_CM},
        ],
        {
            'prompt': LINES['ledger_open'],
            'audio': AGED['elder']['wav'] + ' (first 10.0 s)',
            'directions': ['tired, at the end of a long day, worn'],
        },
        cond=dict(COND_ONE, references=['elder']),
        run_order=16,
        state_note=(
            'operator-decided by construction: the cornelis bench states that VTL is unreliable on '
            'worn voices, so no meter is given authority here. The f0_vtl_band leg is recorded only '
            "to show whether the wear direction moved the speaker's identity."
        ),
    ),
    _p(
        'nonverbal',
        'Laughs, sighs, cries',
        ['nonverbal'],
        [
            {
                'check': 'operator',
                'blind': True,
                'question': 'Does this clip contain an actual laugh and an actual sigh, rather than the words "laughs" and "sigh" spoken aloud? yes/no',
            },
            {'check': 'transcript_absent_terms', 'terms': ['laughs', 'sigh', 'square bracket']},
        ],
        {'prompt': LINES['nonverbal'], 'audio': 'REFERENCE (first 10.0 s)'},
        cond=COND_ONE,
        run_order=17,
        state_note=(
            'the bracket tags are the fixed input; an engine with no tag vocabulary will read them '
            'aloud, which the transcript check catches mechanically and which scores no — that is '
            "what the engine did with the test's input."
        ),
    ),
    # ── Text handling ──
    _p(
        'numbers',
        'Reads numbers and dates correctly',
        ['numbers'],
        [
            {'check': 'transcript_contains_terms', 'terms': ['1671', '23', '17 October']},
            {
                'check': 'operator',
                'blind': True,
                'question': 'Was the year read as "sixteen seventy-one" (not digit by digit, not "one thousand six hundred and seventy-one"), the date as "the seventeenth of October", and 4.5 as "four and a half" or "four point five"? yes/no',
            },
        ],
        {'prompt': LINES['numerals_en'], 'audio': 'REFERENCE (first 10.0 s)'},
        cond=COND_ONE,
        run_order=2,
        state_note=(
            'the operator decides, and the transcript is only a screen: faster-whisper RE-FORMATS '
            'numerals, so "sixteen seventy-one" and "one thousand six hundred and seventy-one" both '
            'come back as 1671 and equals_key cannot tell the two spoken forms apart. Recording that '
            'limitation is the point of writing the check down.'
        ),
    ),
    _p(
        'roman',
        'Reads roman numerals',
        ['roman'],
        [
            {'check': 'transcript_absent_terms', 'terms': ['X V I I', 'ex vee', 'XVII']},
            {
                'check': 'operator',
                'blind': True,
                'question': 'Was XVII spoken as "the seventeenth" or "seventeen", rather than as the letters ex-vee-eye-eye? yes/no',
            },
        ],
        {'prompt': [LINES['roman']['in_context'], LINES['roman']['bare']], 'audio': 'REFERENCE (first 10.0 s)'},
        cond=COND_ONE,
        run_order=18,
        state_note=(
            'two legs, and they measure two different things. tts_service.py expands a numeral only '
            'when the preceding word is a real capitalised word of 3+ letters (measured: a bare token '
            'scan is almost all false positives, I x197, C x94, author initials and letter-spaced '
            'headers). So `in_context` ("Pope Sixtus XVII") is expected to pass through the service '
            'expansion and `bare` ("read XVII") is expected NOT to be expanded — a fail there is the '
            "SERVICE's context gate, not the engine's reading, and the cell note must say which leg "
            'failed. The column is yes only when both legs are spoken as a number.'
        ),
    ),
    _p(
        'names_pron',
        'Pronounces Dutch names',
        ['names_pron'],
        [
            {
                'check': 'operator',
                'blind': True,
                'question': 'Is each of these four names pronounced as a Dutch speaker would say it — Cornelis, Joost, Kattenburg, Witsen? Answer per name: yes/no',
            },
            {'check': 'transcript_contains_terms', 'terms': ['Cornelis', 'Joost', 'Kattenburg', 'Witsen']},
            {'check': 'language', 'lang': 'nl', 'min': 0.6},
        ],
        {'prompt': LINES['names_nl'], 'audio': 'REFERENCE (first 10.0 s)'},
        cond=COND_ONE,
        run_order=19,
        state_note=(
            'four blind decisions per take: the runner cuts the four Whisper-timed name spans into '
            'four clips and shuffles them, so the operator never hears the names in the order the '
            'line puts them. The column is the pass rate over (name x repeat) = 12 decisions.'
        ),
    ),
    _p(
        'foreign',
        'Handles a foreign word in an English line',
        ['foreign'],
        [
            {
                'check': 'operator',
                'blind': True,
                'question': 'Are the Dutch words "pinas", "Texel", "Joost" and "schuit" pronounced as Dutch inside this English sentence, rather than read as English spelling? yes/no',
            },
            {'check': 'transcript_contains_terms', 'terms': ['Texel', 'schuit']},
        ],
        {'prompt': LINES['foreign_en'], 'audio': 'REFERENCE (first 10.0 s)'},
        cond=COND_ONE,
        run_order=20,
    ),
    _p(
        'punct_obey',
        'Honours punctuation as timing',
        ['punct_obey'],
        [
            {'check': 'pause_ms', 'after': 'comma', 'min': 150, 'max': 400},
            {'check': 'pause_ms', 'after': 'full_stop', 'min': 350, 'max': 900},
            {'check': 'pause_longer', 'longer': 'full_stop', 'shorter': 'comma', 'min_ms': 120},
        ],
        {'prompt': LINES['epigraph'], 'audio': 'REFERENCE (first 10.0 s)'},
        reuses='similarity',
        run_order=21,
        state_note=(
            'the epigraph carries a comma, a semicolon and two full stops, which is why it is the '
            'punctuation line. Scored on the similarity renders — no extra call. A semicolon is '
            'measured as a full stop and the trial records both numbers separately.'
        ),
    ),
    _p(
        'long_sentence',
        'Survives a sixty-word sentence',
        ['long_sentence'],
        [
            {'check': 'transcript_contains_terms', 'terms': ['Hoorn', 'fathom', 'Witsen', 'four of us']},
            {'check': 'silence_max', 'max': 1.0},
            {'check': 'duration_s', 'min': 14.0, 'max': 40.0},
        ],
        {'prompt': LINES['long_sentence_60'], 'audio': 'REFERENCE (first 10.0 s)'},
        cond=COND_ONE,
        run_order=22,
        state_note=(
            "the line is 58 words and 306 characters, deliberately just under the service's 350-char "
            'chunker (_TTS_MAX_CHARS), so it reaches the engine as ONE utterance. The four terms are '
            'spread across the sentence: a term missing at the end is the truncation this column is '
            'about, and a silence over 1 s in the middle is the dropout.'
        ),
    ),
    # ── Output quality ──
    _p(
        'artefacts',
        'No clicks, cuts or repeats',
        ['artefacts'],
        [
            {'check': 'click_count_max', 'k': 12.0, 'max': 0},
            {
                'check': 'operator',
                'blind': True,
                'question': 'Does this clip repeat a word or syllable, stutter, or cut off, anywhere in it? yes/no (yes = a fault is present)',
            },
        ],
        {
            'prompt': [LINES['sibilance'], PASSAGE + ' (first 600 words)'],
            'fixture': PASSAGE,
            'audio': 'REFERENCE (first 10.0 s)',
        },
        reuses='similarity + long_form',
        run_order=23,
        state_note=(
            "INVERTED operator question — the runner flips the answer before scoring, per the bank's "
            'operator protocol. Scored on the sibilance takes (where a de-esser artefact shows) and '
            "on the four-minute passage (where a cloner's repeat loop shows); no extra render."
        ),
    ),
    _p(
        'noise_floor',
        'Clean noise floor',
        ['noise_floor'],
        [{'check': 'noise_floor_max', 'max': -60.0}, {'check': 'silence_max', 'max': 2.0}],
        {'prompt': LINES['ledger_open'], 'audio': 'REFERENCE (first 10.0 s)'},
        reuses='zero_shot',
        run_order=24,
        state_note=(
            'the quietest 200 ms of the take, which on a line that opens on a consonant is the lead-in '
            'silence. Measured on the RAW output: the -16 LUFS loudnorm raises a noise floor with the '
            'voice and would hide a bad one.'
        ),
    ),
    _p(
        'seed_stable',
        'A seed reproduces a take',
        ['seed_stable'],
        [{'check': 'waveform_corr_min', 'min': 0.99}, {'check': 'audio_similarity_min', 'to': 'first', 'min': 0.98}],
        {'prompt': LINES['ledger_open'], 'audio': 'REFERENCE (first 10.0 s)'},
        cond=dict(COND, seeds=[11], repeats=2, note='seed 11 twice in one process, m01_warm_baritone only'),
        run_order=25,
        state_note=(
            'a sample-level correlation, not a perceptual one: an engine that reproduces the '
            'performance but not the waveform scores no here and the log-mel leg records how close it '
            'came. A row with no seed parameter is `na` and says so.'
        ),
    ),
    # `failsafe` is owned HERE, not by the bank. audio_shared.u_failsafe carries its fixed input
    # under `command`, which the validator does not count as a fixed input, so merging it produces
    # "probe u_failsafe: no fixed input" for every step that includes the audio bank. This probe is
    # the bank's u_failsafe restated with the same substance — three broken calls, the same two
    # checks, the same sighted question — with the inputs declared under `prompt`/`audio`, plus the
    # two broken references that only a cloner can be given.
    _p(
        'tts_failsafe',
        'Fails without breaking the caller',
        ['failsafe'],
        [
            {
                'check': 'operator',
                'blind': False,
                'question': (
                    'Did all four broken calls come back — each returning a value or raising an '
                    'exception the caller caught — with this process still alive and nvidia-smi '
                    'showing the VRAM released within 30 s? yes/no'
                ),
            },
            {
                'check': 'file_absent',
                'path': 'output/capabilities/failsafe/partial.wav',
                'note': 'a half-written take left behind is a fail even if the call returned',
            },
        ],
        {
            'prompt': '(four deliberately broken calls — the four in `variants`, in order)',
            'audio': 'capability_tests/fixtures/audio/judge/truncated.wav',
            'variants': {
                'empty_line': 'the line is the empty string, the reference is m01_warm_baritone',
                'broken_reference': (
                    'the line is LINES["ledger_open"], the reference is '
                    'capability_tests/fixtures/audio/judge/truncated.wav — a WAV whose '
                    'header claims 40 s over 0.2 s of samples'
                ),
                'missing_reference': (
                    'the line is LINES["ledger_open"], the reference is a path that does '
                    'not exist: data/assets/voice_seeds/pool/does_not_exist.wav'
                ),
                'no_reference': 'the line is LINES["ledger_open"] and no reference is passed at all',
            },
        },
        cond=dict(
            COND_ONE,
            repeats=4,
            references=['m01_warm_baritone'],
            note='one repeat per variant, seed 11, m01_warm_baritone. No take is expected; what is '
            'measured is how the call ends, so one reference is enough',
        ),
        run_order=26,
        state_note=(
            'all four must come back. no = any hang past 120 s, any crash of the host process, any '
            'leaked VRAM allocation. Answered SIGHTED — there is nothing to be blind about when the '
            'question is whether the process is still running. `no_reference` is the interesting one '
            'for this step: an engine that silently falls back to a built-in voice instead of '
            'refusing has passed failsafe and failed quiet_fail.'
        ),
        overrides_shared='u_failsafe',
    ),
]

# ── the rows ──────────────────────────────────────────────────────────────────────────
