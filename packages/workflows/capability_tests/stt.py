# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Default test — Speech to text (stt). 2026-09-30.

Question the sheet asks: "Is the transcript good enough to gate a take on, and how fast?"
Its recorded limitation is blunt: *no WER has ever been measured on our own material — there
is no reference transcript set in the repo to measure against*, and its `next_tests` line is
*hand-correct 10 minutes of house narration and keep it as the permanent WER reference*.
This test is that reference, reused rather than invented: the SAME three-minute bilingual
narration the subtitles test already owns (capability_tests/fixtures/subtitles/MANIFEST.json)
is the WER fixture here, so the two sheets are measured on one recording and one key.

Shape of the test. Every row is a service that takes a wav and returns words — there is no
prompt to obey. So the test is a set of FIXED recordings, each planted with exactly one
failure mode (an accent, a child, a sung bar, speech under music, two voices at once, sixty
seconds of room tone, an hour-long concatenation), run at fixed settings, and scored
mechanically: word error rate against a verified transcript, word onsets against the
operator's marks, and presence/absence regexes for the planted names and numbers. Nine of the
seventeen domain columns are read off the SAME three narration runs, which is why the call
budget is much smaller than the column count.

What is blocked and why. The narration wav does not exist yet and the MANIFEST's
`verified_words` list is still empty, so eight columns (wer, names, numbers, dutch,
timestamps, punct_out, confidence, vad) are BLOCKED and written `untested — key unverified`
until the operator synthesises the audio and marks the word onsets. The six single-purpose
fixtures below the narration do not exist either; each is declared with the exact command or
recipe that makes it, and each blocks its own column until it has been listened to once.
Nothing here creates a file.

The vocabulary hint is deliberately OFF (`initial_prompt: ''`): the subtitles test measures
what Whisper's `initial_prompt` does, so measuring it again here would be a second
disposition on the same evidence. The names column therefore reports whether the names
survive WITHOUT help, which is the harder and more useful number.
"""

from __future__ import annotations

# ── check kinds this module adds (the runner is a table of these) ──────────────────────
CHECK_KINDS = {
    'output_empty': 'the row returns no word at all: no token at confidence >= `min_conf` (default 0.0) and no non-whitespace text. Any word is a fail — this is the hallucination column, where the only right answer is silence',
    'wer_delta_max': 'WER over the span named by `window` minus WER over the span named by `baseline`, both against the verified transcript, <= `max` (drift over a long file)',
    'transcript_covers_min': "the reported word timestamps span >= `min` of the fixture's total speech seconds — a dropped tail is a fail even when the words that came back are right",
    'sentence_count_range': 'sentences in the output (split on [.!?…] followed by whitespace or end of text) between `min` and `max`',
    'sentence_starts_capital_min': 'share of those sentences whose first letter is an uppercase letter >= `min`',
    'confidence_present': 'every word the row returns carries a numeric confidence or logprob field, none of them null',
    'confidence_discriminates': 'mean confidence of the words the WER alignment marks WRONG is lower than the mean of the correct words by >= `min_delta`, measured over at least `min_wrong` wrong words; fewer wrong words than that is `untested`, not a pass — the row was not given enough errors to discriminate on',
    'lang_detected': 'the set of language codes the row reports (file level, or per segment where it segments) equals `langs`',
    'vad_overlap_min': "intersection-over-union of the reported speech regions with the fixture's scripted speech regions >= `min`, AND no reported speech region falls inside a scripted silence longer than `silence_s` seconds or inside a scripted non-speech segment listed in `not_speech`",
    'completes_under_gpu_pressure': 'with `hold_gb` of VRAM held by a dummy allocation in a SEPARATE process, the call still returns a transcript within `timeout_s` seconds on either device, and the device actually used is recorded in the trial; a raise, a hang or an empty return is a fail',
}

SUBS = 'capability_tests/fixtures/subtitles'
MANIFEST = SUBS + '/MANIFEST.json'
NARRATION = SUBS + '/narration.wav'
FX = 'capability_tests/fixtures/stt'

# ── the settings every row is driven at, identical for all three ──────────────────────
SETTINGS = {
    'repeats': 3,
    'language': None,
    'beam_size': 1,
    'vad': True,
    'word_timestamps': True,
    'initial_prompt': '',
    'sample_rate_in': 16000,
    'channels': 1,
    'note': (
        "beam_size 1, vad True and 16 kHz mono are voice_stt.py's production values, pinned "
        'here so the CUDA and the CPU row are compared at the same beam rather than at their '
        'own defaults. `language: None` is required by the lang_id column — the row must '
        'detect the two languages, not be told them. `word_timestamps: True` is NOT what '
        "voice_stt.py sets; it is the TEST's setting, because timestamps, confidence and vad "
        "cannot be answered by a row that returns segments only. `initial_prompt: ''` is "
        'deliberate: the vocabulary hint is measured on the subtitles sheet (pd_hint).'
    ),
}

COND = {
    'repeats': SETTINGS['repeats'],
    'language': None,
    'beam_size': 1,
    'vad': True,
    'word_timestamps': True,
    'initial_prompt': '',
    'note': 'three runs of the same audio; faster-whisper on CUDA is not bit-deterministic and a row that is will show it',
}

WER_RULE = (
    'the reference is MANIFEST.transcript_verbatim (the concatenation of the twelve '
    'segment texts, SFX segments excluded). Normalisation before alignment: lowercase, '
    'strip punctuation except the intra-word hyphen and apostrophe, collapse whitespace, '
    'keep number WORDS as words (the script spells every number out). Digits are '
    'therefore never counted as WER errors — whether the row writes 1671 or "sixteen '
    'seventy-one" is the `numbers` column\'s question, not this one.'
)

ALL = ['whisper_cuda', 'whisper_cpu', 'transcriber']


def _p(pid, title, feeds, checks, audio, rows=None, **kw):
    p = {
        'id': pid,
        'title': title,
        'feeds': list(feeds),
        'inputs': {'audio': audio, 'fixture': MANIFEST, 'prompt': None, 'settings': dict(SETTINGS)},
        'conditions': dict(COND),
        'checks': list(checks),
        'grade': 'measured',
        'rows': list(rows or ALL),
    }
    p.update(kw)
    return p


PROBES = [
    # ── the nine columns read off the SAME three narration runs ──────────────────────
    _p(
        'wer',
        'Word error rate on the house narration',
        ['wer'],
        [{'check': 'wer_max', 'max': 0.05}],
        NARRATION,
        state_note="the sheet's missing headline number. yes at WER <= 0.05, partial <= 0.12, no above it",
        state_rule={'yes': 0.8, 'partial': 0.4},
        wer_rule=WER_RULE,
    ),
    _p(
        'names',
        'Proper nouns spelled right, with no vocabulary hint',
        ['names'],
        [
            {'check': 'present', 'terms': ['Kattenburg', 'Cornelis', 'Joost', 'Witsen', 'Zeehond']},
            {
                'check': 'regex_absent',
                'pattern': r'\b(Kattenberg|Cattenburg|Cornelius|Whitson|Witson|Zeehont|Seahound|Yoost)\b',
            },
        ],
        NARRATION,
        state_note=(
            'five planted names, `initial_prompt` empty. All five present and no known '
            'mis-spelling -> yes; three or four -> partial. The same five names WITH the hint '
            "are the subtitles sheet's pd_hint probe, so the pair shows what the hint buys."
        ),
    ),
    _p(
        'numbers',
        'Numbers and dates',
        ['numbers'],
        [
            {'check': 'regex_present', 'pattern': r'\b(1671|sixteen seventy[- ]one)\b'},
            {'check': 'regex_present', 'pattern': r'\b(23|twenty[- ]three) barrels\b'},
            {'check': 'regex_present', 'pattern': r'\b(23|drie\u00ebntwintig) tonnen\b'},
            {'check': 'regex_present', 'pattern': r'\b(11|eleven) days\b'},
            {'check': 'regex_absent', 'pattern': r'\b(1617|1761|1971|16 71)\b'},
            {'check': 'regex_absent', 'pattern': r'\b(32|thirty[- ]three) barrels\b'},
        ],
        NARRATION,
        state_note=(
            'EITHER spelling is accepted — digits or words. This column asks whether the '
            "VALUE survived, not the house digits rule (that is the subtitles formatter's "
            'column). "tweeentwintig"/22 is NOT in the absent list: segment 8 really says '
            '"Niet tweeentwintig", so forbidding it would fail a correct transcript.'
        ),
    ),
    _p(
        'dutch',
        'Dutch',
        ['dutch'],
        [{'check': 'wer_max', 'max': 0.08, 'segment': 'nl'}],
        NARRATION,
        state_note='segments 8-10 (Cornelis and Anna, Dutch). 0.08 rather than 0.05: Dutch is the second language of every model on the shelf and the test says so out loud instead of hiding it in one number',
        wer_rule=WER_RULE,
    ),
    _p(
        'timestamps',
        'Word timestamps usable for subtitles',
        ['timestamps'],
        [{'check': 'timing_abs_ms', 'max': 100, 'share': 0.9}],
        NARRATION,
        state_note='the same 100 ms / 90 % standard the subtitles test uses, against the SAME twenty operator-marked onsets in MANIFEST.verified_words — so a row cannot pass here and fail there',
    ),
    _p(
        'punct',
        'Punctuates and capitalises',
        ['punct_out'],
        [
            {'check': 'sentence_count_range', 'min': 13, 'max': 18},
            {'check': 'sentence_starts_capital_min', 'min': 0.9},
            {'check': 'regex_absent', 'pattern': r'\s[,.;:]|[,.;:]{2,}(?!\.)'},
        ],
        NARRATION,
        state_note=(
            'the script holds 15 sentences (1+1+1+1+2+3+2+1+1+2 over segments '
            '1,2,3,5,6,8,9,10,11,12). The window is 13-18 because the planted false start '
            '"I\u2014 I mean, the second tide." may legitimately come out as one sentence or '
            'two. A row that returns one unpunctuated block fails on all three checks.'
        ),
    ),
    _p(
        'confidence',
        'Reports per-word confidence',
        ['confidence'],
        [{'check': 'confidence_present'}, {'check': 'confidence_discriminates', 'min_delta': 0.05, 'min_wrong': 5}],
        NARRATION,
        state_note=(
            'presence alone is half the question: a row that returns 0.99 on every word, '
            'right or wrong, reports a number that cannot be gated on. yes = present AND '
            'discriminating; partial = present but flat; no = absent. Where the row makes '
            'fewer than five errors on the narration the second check writes `untested` '
            'with that reason — the row was not given enough errors to discriminate on, '
            'which is a statement about the fixture and not about the row.'
        ),
    ),
    _p(
        'langid',
        'Detects the language',
        ['lang_id'],
        [{'check': 'lang_detected', 'langs': ['nl', 'en']}],
        NARRATION,
        state_note=(
            'called with `language: None`. Both codes reported (file level for a row that '
            'reports one language, per segment for a row that switches) -> yes; one of the '
            "two -> partial; a third language or none -> no. The key is the segments' own "
            '`lang` fields in the MANIFEST, which is script metadata and needs no waveform '
            'marking, so this column is NOT blocked by the unverified transcript.'
        ),
    ),
    _p(
        'vad',
        'Voice activity detection',
        ['vad'],
        [
            {
                'check': 'vad_overlap_min',
                'min': 0.85,
                'silence_s': 0.4,
                'not_speech': ['segment 4 [bell]', 'segment 7 [dog barks]'],
                'note': 'the eleven scripted silence_after gaps and the two SFX segments are not speech; a reported region there is a false positive and costs IoU',
            }
        ],
        NARRATION,
        state_note='a VAD that marks the church bell or the dog as speech is the failure this fixture was built to catch',
    ),
    # ── one fixture, one failure mode ─────────────────────────────────────────────────
    _p(
        'accent',
        'Accented English',
        ['accent'],
        [{'check': 'wer_max', 'max': 0.12}],
        FX + '/accent_en.wav',
        state_note='0.12 against the 0.05 of the house narrator is the accent penalty this column exists to publish',
    ),
    _p(
        'child',
        'Child speech',
        ['child_voice'],
        [{'check': 'wer_max', 'max': 0.15}],
        FX + '/child_abel.wav',
        state_note="Abel's TTS line. A synthesised child is an easier case than a recorded one and the note must say so: the number is an upper bound on our real child-speech accuracy, not an estimate of it",
    ),
    _p(
        'sung',
        'Sung words',
        ['sung'],
        [{'check': 'wer_max', 'max': 0.30}],
        FX + '/sung_bar.wav',
        state_note='one sung bar from the kids-music leg. 0.30: singing stretches vowels past every ASR language model\'s assumptions, and a threshold set at speech level would report "no" for every row and measure nothing',
    ),
    _p(
        'noise',
        'Speech over music or noise',
        ['noise'],
        [{'check': 'wer_max', 'max': 0.15}],
        FX + '/noise_music_5db.wav',
        state_note="the narration under a house soundtrack at 5 dB SNR. The reference transcript is the narration's own, so this number is directly comparable with the `wer` column: the difference IS the noise penalty",
    ),
    _p(
        'overlap',
        'Two people at once',
        ['overlap'],
        [
            {'check': 'wer_max', 'max': 0.25, 'segment': 'voice_a'},
            {'check': 'wer_max', 'max': 0.25, 'segment': 'voice_b'},
        ],
        FX + '/overlap_two.wav',
        state_note=(
            'both voices scored separately. A row that transcribes one voice cleanly and '
            'drops the other is `partial`, which is the honest verdict and the one a single '
            'merged WER would hide.'
        ),
    ),
    _p(
        'hallucinate',
        'Does not invent speech in silence',
        ['hallucinate'],
        [{'check': 'output_empty', 'min_conf': 0.0}],
        FX + '/room_tone_60s.wav',
        state_note=(
            'the classic Whisper failure: sixty seconds of interior room tone must come back '
            'EMPTY. One invented word is `no` — there is no partial credit on this column, '
            'because a single hallucinated sentence in a transcript is what makes the whole '
            'transcript unusable as a gate.'
        ),
        state_rule={'yes': 0.99, 'partial': 0.98},
    ),
    # ── the two expensive ones, last ──────────────────────────────────────────────────
    _p(
        'vram_gate',
        'Degrades safely when the GPU is busy',
        ['vram_gate'],
        [{'check': 'completes_under_gpu_pressure', 'hold_gb': 21, 'timeout_s': 600}],
        NARRATION,
        code_ref=(
            'zyg_whisper.py:47-62 `_pick_device_compute` — device starts at ("cpu", "int8") '
            'and is only raised to ("cuda", "int8_float16") when torch.cuda.mem_get_info() '
            'reports free bytes >= ZYG_WHISPER_FW_MIN_VRAM_MB (legacy alias '
            'ZYG_WHISPER_MIN_VRAM_MB, default 5000) MB; zyg_whisper.py:120-131 is the CPU '
            'branch, which lowers the model to ZYG_WHISPER_CPU_MODEL (base) and calls '
            '_record_degrade -> run_ledger.record_fallback("whisper", ...) so the fallback '
            "leaves a receipt. voice_stt.py:1-15 says the policy is zyg_whisper's, not "
            "voice_stt's, and that voice_stt only reports which of the two it got."
        ),
        state_note=(
            'the code path above is READ, not trusted: the probe holds 21 GB of the 24 GB '
            'card in a separate process (torch.empty on cuda, no house module imported) so '
            'free VRAM lands under the 5000 MB floor, then calls the row three times. yes = '
            'returns a transcript all three times AND the trial records device "cpu"; '
            'partial = returns but the device recorded is still "cuda" (the gate did not '
            'fire and we were lucky); no = raises, hangs past 600 s, or returns nothing. '
            'The fallback receipt in the run ledger is checked as part of the trial.'
        ),
    ),
    _p(
        'long_file',
        'Handles an hour in one pass',
        ['long_file'],
        [
            {'check': 'transcript_covers_min', 'min': 0.95},
            {'check': 'wer_delta_max', 'max': 0.03, 'window': 'last 60 s', 'baseline': 'first 60 s'},
        ],
        FX + '/long_60min.wav',
        conditions={
            'repeats': 1,
            'language': None,
            'beam_size': 1,
            'vad': True,
            'word_timestamps': True,
            'initial_prompt': '',
            'note': 'ONE repeat: an hour of audio per repeat on three rows is the whole GPU budget of this test, and the question (does it finish, does it drift) is answered by one pass',
        },
        state_note=(
            'twenty copies of the three-minute narration concatenated. Two failures are '
            'being looked for and they are different: a row that returns a transcript of '
            'the first ten minutes and stops (caught by transcript_covers_min) and a row '
            'whose accuracy decays as the context grows (caught by wer_delta_max). Because '
            'every copy is the same audio, the last minute and the first minute have the '
            'SAME reference, so the delta is drift and nothing else.'
        ),
    ),
    # ── `failsafe` is owned here, not by the bank ──────────────────────────────────────
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
        'capability_tests/fixtures/audio/judge/truncated.wav',
        conditions={
            'repeats': 3,
            'seed': 11,
            'note': 'three broken calls, one repeat each; nothing about a broken input is worth averaging',
        },
        inputs={
            'task': (
                'call the row on a DELIBERATELY broken input three ways, exactly as the audio '
                "bank's u_failsafe does, with the audio substituted for the prompt because no "
                'row on this step has one: (1) audio = '
                'capability_tests/fixtures/audio/judge/truncated.wav (a WAV whose header claims '
                '40 s and holds 0.2 s of data); (2) audio = a zero-byte file with a .wav name; '
                '(3) audio = a 0.10 s blob, which is under voice_stt.MIN_SECONDS (0.25) and must '
                'come back as SttError and not as an empty transcript'
            ),
            'audio': 'capability_tests/fixtures/audio/judge/truncated.wav',
            'fixture': MANIFEST,
            'prompt': None,
        },
        state_note=(
            'THIS PROBE IS A LOCAL COPY of audio_shared.u_failsafe, substance unchanged: the '
            'bank carries its fixed input under `inputs.command`, which the step validator '
            'does not count as a fixed input, so a step that merges the bank fails `check` on '
            "the bank's own probe. Owning the column here keeps the test identical and leaves "
            'the bank untouched; when the bank moves that string to `inputs.task`, delete this '
            'probe and the shared version comes back by itself. yes = all three calls returned '
            'or raised something the caller can catch, the process is still up and the VRAM is '
            'released within 30 s. no = any hang past 120 s, any crash of the host process, '
            'any leaked allocation, or a transcript of the third case (an empty string returned '
            'for a 0.10 s blob is a SILENT failure, which is the one this step must not have).'
        ),
    ),
]

ROW_NA_CPU = {
    'vram_gate': 'this row IS the fallback the VRAM gate falls back TO: it holds no VRAM, so there '
    'is nothing to gate and nowhere further to degrade. The gate is measured on '
    'whisper_cuda, whose partial/no states are about reaching this row at all.',
}

TEST = {
    'step': 'stt',
    'version': '2026-09-30.1',
    'title': 'One verified narration plus six planted fixtures, at production settings',
    'purpose': (
        'Give the step the reference transcript its sheet says it has never had, and score '
        'every accuracy and output question mechanically against it: WER on the house '
        'narration, on Dutch, on an accent, on a child, on singing, under music and on two '
        "voices at once; word onsets against the operator's marks; silence against "
        'nothing at all.'
    ),
    'include_shared': 'audio',
    'settings': SETTINGS,
    'wer_rule': WER_RULE,
    'rows': {
        'whisper_cuda': {
            'transport': 'service',
            'where': 'voice_stt.transcribe -> zyg_whisper.transcribe_segments',
            'model': 'faster-whisper large-v3 on CUDA, int8_float16 (zyg_whisper.DEFAULT_MODEL, ZYG_WHISPER_MODEL)',
        },
        'whisper_cpu': {
            'transport': 'service',
            'where': 'voice_stt.transcribe -> zyg_whisper.transcribe_segments with the CUDA path refused',
            'model': 'Whisper base on CPU, int8 (ZYG_WHISPER_CPU_MODEL, default "base") — the fallback',
            'na': ROW_NA_CPU,
            'budget': {'minutes': 46, 'gpu_minutes': 0},
        },
        'transcriber': {
            'transport': 'service',
            'where': 'the Transcriber app (project_transcriber_app), called on the fixture path',
            'model': "the Transcriber app's own resident model, GPU residency policy project_transcriber_gpu_residency",
            'budget': {'minutes': 26, 'gpu_minutes': 24},
        },
    },
    'probes': PROBES,
    'derive': {},
    'lookup': {},
    'wiring': {},
    'na': {},
    'run_order': [
        'hallucinate',
        'wer',
        'names',
        'numbers',
        'dutch',
        'timestamps',
        'punct',
        'confidence',
        'langid',
        'vad',
        'accent',
        'child',
        'sung',
        'noise',
        'overlap',
        'vram_gate',
        'long_file',
    ],
    'fixtures': [
        {
            'path': MANIFEST,
            'verified': False,
            'blocks': ['wer', 'names', 'numbers', 'dutch', 'timestamps', 'punct_out', 'confidence', 'vad'],
            'how_to_verify': (
                'synthesise `audio` with the three MANIFEST voices, check by ear that the '
                'render says the script (in particular the false start in segment 6 and the '
                'spelled-out numbers), then open it in Audacity and set `t` for each of the '
                "twenty entries in MANIFEST.verified_words to the word's onset in seconds "
                '(3 decimals), and set verified = true. This is the operator pass the sheet '
                'asked for in next_tests ("hand-correct 10 minutes of house narration and '
                'keep it as the permanent WER reference") and it is shared with the '
                'subtitles test — doing it once unblocks both sheets.'
            ),
        },
        {
            'path': NARRATION,
            'generated': 'the MANIFEST `audio.assembly` recipe: synthesise the twelve segments with the named voices, concatenate with the given silences, insert bell.wav and dog_bark.wav from the SFX library slates, loudnorm to -16 LUFS after a limiter',
        },
        {
            'path': FX + '/accent_en.wav',
            'verified': False,
            'blocks': ['accent'],
            'generated': (
                'read the English half of the MANIFEST script (segments 1, 2, 3, 11, 12) with a '
                'non-native English voice from the house TTS catalogue (the Dutch-accented '
                'English preset used for the Cornelis narration takes), 48 kHz mono, loudnorm '
                '-16 LUFS; write the wav and an accent_en.txt holding the exact words read'
            ),
            'how_to_verify': "play it once and confirm the accent is audible and the words are the script's; then set verified = true on this entry",
        },
        {
            'path': FX + '/child_abel.wav',
            'verified': False,
            'blocks': ['child_voice'],
            'generated': 'the house TTS with the Abel child voice reading, verbatim: "Cornelis, there are twenty-three barrels on the quay, and one of them is leaking." — 48 kHz mono, loudnorm -16 LUFS, with child_abel.txt holding that sentence as the reference',
            'how_to_verify': 'play it once and confirm the sentence is complete and unclipped; then set verified = true',
        },
        {
            'path': FX + '/sung_bar.wav',
            'verified': False,
            'blocks': ['sung'],
            'generated': "one sung bar from the kids-music leg: the melody_sampler render of the counting style's first line, vocal stem only, 48 kHz mono, with sung_bar.txt holding the sung words as the reference",
            'how_to_verify': 'play it once and write down the words heard; they must equal sung_bar.txt before verified = true',
        },
        {
            'path': FX + '/noise_music_5db.wav',
            'verified': False,
            'blocks': ['noise'],
            'generated': 'ffmpeg -i narration.wav -i <house soundtrack bed> -filter_complex "[1:a]volume=<set so the integrated LUFS of the bed is 5 dB below the narration\'s>[m];[0:a][m]amix=inputs=2:duration=first:normalize=0" -ar 48000 -ac 1 noise_music_5db.wav; the SNR is measured with the audio_qc meters and written into the fixture note, not assumed',
            'how_to_verify': 'confirm with the audio_qc LUFS meter that the bed sits 5 dB (+/- 0.5) below the speech, then set verified = true',
        },
        {
            'path': FX + '/overlap_two.wav',
            'verified': False,
            'blocks': ['overlap'],
            'generated': 'the MANIFEST Cornelis line of segment 8 and the Anna line of segment 9 rendered separately and mixed with a 2.0 s offset so they overlap for ~3 s, equal loudness, 48 kHz mono; overlap_two.json holds the two reference texts as voice_a and voice_b',
            'how_to_verify': 'play it once and confirm both lines are audible and neither is buried; then set verified = true',
        },
        {
            'path': FX + '/room_tone_60s.wav',
            'verified': False,
            'blocks': ['hallucinate'],
            'generated': 'sixty seconds of the room_tone_interior slate from the SFX library (the same label the audio bank uses), trimmed to 60.000 s, 48 kHz mono, NOT normalised — the level must stay where it was recorded',
            'how_to_verify': 'play all sixty seconds end to end and confirm there is no speech, no radio, no distant voice and no music. This is the whole key: the column asks for silence and the operator must have heard that there is silence to hear.',
        },
        {
            'path': FX + '/long_60min.wav',
            'verified': False,
            'blocks': ['long_file'],
            'generated': 'ffmpeg -f concat -safe 0 -i <a list naming narration.wav twenty times> -c copy long_60min.wav (20 x ~3 min = ~60 min); the reference transcript is MANIFEST.transcript_verbatim repeated twenty times',
            'how_to_verify': "inherits the narration's verification: once MANIFEST.verified = true, confirm the concatenation is 20 copies and the duration is >= 59 min, then set verified = true",
        },
    ],
    'budget': {
        'calls': 40,
        'tokens_in': 0,
        'tokens_out': 0,
        'tokens_note': 'every row takes a wav and returns words; no language-model tokens are spent anywhere on this step, and no row on this sheet is a Claude row',
        'minutes': 24,
        'gpu_minutes': 16,
        'operator_minutes': 30,
        'note': (
            'Per row. 22 transcription calls of our own: the narration 3x (nine columns are read '
            'off those SAME three runs, which is why 17 columns cost 3 calls), then accent, '
            'child, sung, noise, overlap, room tone and vram_gate at 3 repeats each = 21, plus '
            'long_file at 1 repeat = 22. Wall clock on whisper_cuda: ~1 min model load + 3 x 3 '
            'min narration at ~0.1 RTF (~1 min) + 21 short-fixture runs of 10-60 s (~3 min) + '
            'the 60-min file at ~0.1 RTF (~6 min) + 3 vram_gate runs that are expected to fall '
            'back to CPU base at ~0.4 RTF (~4 min) = ~15 min, rounded to 16 GPU minutes of 24 '
            'wall. whisper_cpu is the same 22 calls at ~0.4 RTF and holds no GPU: ~46 min, 0 '
            'GPU (row override). The Transcriber app keeps its model resident: ~26 min, 24 on '
            'the GPU (row override). SHARED BANK for this step: the audio bank contributes the '
            '7 Capacity ladders and the 4 Prompt bands (88 of the 105 columns) — no Makes and '
            'no Hears band is asked of stt. Most of its render probes carry applies_to "sound" '
            "and write untested with that reason on an ASR row, so the bank's measurable "
            'residue here is estimated at ~18 further calls and ~8 min per row (the acap_words '
            'and acap_seconds ladders on this same narration) — that estimate is included in '
            'the 40 calls and the 24 minutes above. OPERATOR: 32 operator checks stand on the '
            "merged test and exactly ONE is this module's (the sighted failsafe question); "
            "the other 31 are the bank's. At 3 repeats and ~30 s a decision the ceiling is 93 "
            "decisions = ~47 min per row, but most of the bank's operator checks sit on render "
            'probes whose applies_to is "sound" and are not run on an ASR row at all, so 30 min '
            'is the honest working figure. Two ONE-TIME costs are not in this per-row number '
            'and dominate the whole test: ~30 min marking the twenty verified_words in the '
            'waveform, and ~10 min listening once to each of the six new fixtures. Until both '
            'are done, nine of the seventeen domain columns write untested however much GPU '
            'time is spent.'
        ),
    },
    'notes': [
        "The sheet's recorded limitation was that no WER had ever been measured on our own material. "
        'This test does not fix that by measuring; it fixes it by naming ONE permanent reference and '
        'refusing to score anything until the operator has verified it. The blocked columns are the '
        'point, not a gap.',
        'The fixture is shared with the subtitles test on purpose. subtitles measures the pipeline '
        '(Whisper -> formatter -> burn) and reports what the vocabulary hint buys; stt measures the '
        'three transcription services bare, hint off. Same audio, same twenty marked onsets, same '
        '100 ms / 90 % timing standard, so a row that passes `timestamps` here cannot fail `timing` '
        'there without one of the two tests being wrong.',
        'Numbers are treated as a SEPARATE column from WER and both spellings are accepted, because '
        'the digits rule belongs to the subtitles formatter. An ASR row is not wrong for writing '
        '"sixteen seventy-one".',
        'Thresholds are not one number: 0.05 for the house narrator, 0.08 for Dutch, 0.12 accented, '
        '0.15 child, 0.15 under music, 0.25 per voice on overlap, 0.30 sung. A single WER threshold '
        'would make every row `no` on the hard fixtures and measure nothing. The spread between the '
        'columns is itself the result the sheet wants.',
        'whisper_cuda and whisper_cpu are the SAME code path (voice_stt -> zyg_whisper) at two '
        'devices and two model sizes, so their columns are directly comparable and the difference is '
        'what the VRAM gate costs when it fires. That is why the gate is a probe with a code '
        'reference rather than a wiring cell: the file:line is read, then held to 21 GB of pressure '
        'and made to prove it.',
    ],
}
