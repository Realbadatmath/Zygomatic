# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Default test — Subtitles & captions (subtitles). 2026-09-28.

Question the sheet asks: can we produce broadcast-correct subtitles without a human pass?
The rows are a pipeline, not a chat model: Whisper word timings feed the house formatter.
So the test is one fixed FIXTURE — a scripted three-minute bilingual narration with the
things that break subtitles planted in it (spelled-out numbers, names, a false start, two
speakers, a bell and a dog, one very long sentence) — run through the pipeline as it is
wired in production, and measured against a transcript and word timings the operator has
verified by hand.

The fixture audio does not exist yet. capability_tests/fixtures/subtitles/MANIFEST.json holds
the script, the voices to synthesise it with, the ffmpeg command for the cut-list video, and
an empty `verified_words` list. Until the operator fills that list from the waveform, the
timing columns are BLOCKED and written `untested — key unverified`.

Prompt-damage, counting and spatial questions do not apply to a transcriber or a formatter
and are `na` with the reason on each cell — except the four prompt questions Whisper's
`initial_prompt` vocabulary hint can actually answer.
"""

from __future__ import annotations

FX = 'capability_tests/fixtures/subtitles'
MANIFEST = FX + '/MANIFEST.json'

HOUSE = {
    'max_lines': 2,
    'max_cpl': 42,
    'max_cps': 17,
    'min_dur': 1.0,
    'max_dur': 7.0,
    'gap': 0.083,
    'numerals': 'digits',
    'lead_in': 0.083,
    'note': "max_lines and max_cpl are the values in pipeline_video._burn_subtitles; min/max duration, cps and gap are set HERE as the test's fixed standard because the pipeline does not define them — the sheet note says so",
}

COND = {
    'repeats': 3,
    'note': 'the same audio three times; Whisper is not deterministic on GPU, and a formatter that is will show it',
}

WH = ['whisper_align']
HR = ['house_rules']


def _p(pid, title, feeds, checks, rows, **kw):
    p = {
        'id': pid,
        'title': title,
        'feeds': list(feeds),
        'inputs': {'audio': MANIFEST + '#audio', 'fixture': MANIFEST, 'prompt': None},
        'conditions': dict(COND),
        'checks': list(checks),
        'grade': 'measured',
        'rows': rows,
    }
    p.update(kw)
    return p


PROBES = [
    _p(
        'timing',
        'Word timing against the verified words',
        ['timing'],
        [{'check': 'timing_abs_ms', 'max': 100, 'share': 0.9}],
        WH,
        state_note="yes when ≥ 90 % of the verified words start within 100 ms of the operator's mark",
    ),
    _p(
        'drift',
        'No drift over the file',
        ['drift'],
        [
            {'check': 'timing_abs_ms', 'max': 100, 'share': 0.9, 'window': 'last 60 s'},
            {
                'check': 'operator',
                'blind': False,
                'question': 'derived: mean signed offset in the last minute minus the first minute is within ±60 ms',
            },
        ],
        WH,
    ),
    _p(
        'verbatim',
        'Matches what was said',
        ['verbatim'],
        [
            {'check': 'wer_max', 'max': 0.03},
            {
                'check': 'regex_present',
                'pattern': r'I—|I -|I, I mean|I… I mean|I\.\.\. I mean',
                'note': 'the planted false start survives; silent tidying fails',
            },
        ],
        WH,
    ),
    _p(
        'names',
        'Proper nouns spelled right',
        ['names'],
        [
            {'check': 'present', 'terms': ['Kattenburg', 'Cornelis', 'Joost', 'Witsen', 'Zeehond']},
            {
                'check': 'regex_absent',
                'pattern': r'\b(Kattenberg|Cattenburg|Cornelius|Joost?e|Whitson|Witson|Zeehont|Seahound)\b',
            },
        ],
        WH,
        state_note='the initial_prompt vocabulary hint is ON, as in production; the note records whether names pass WITHOUT it too (pd_damage)',
    ),
    _p(
        'lang',
        'Dutch and English in one file',
        ['lang'],
        [{'check': 'wer_max', 'max': 0.05, 'segment': 'nl'}, {'check': 'wer_max', 'max': 0.03, 'segment': 'en'}],
        WH,
    ),
    _p(
        'speaker',
        'Marks who is speaking',
        ['speaker'],
        [{'check': 'regex_present', 'pattern': r'(?m)^[-–] .+\n[-–] .+', 'note': 'dash dialogue in a two-speaker cue'}],
        HR,
        state_note='the two-speaker exchange at 1:41 must come out as dash-dialogue or name tags; a merged unmarked cue fails',
    ),
    _p(
        'sfx_cue',
        'Marks non-speech sound',
        ['sfx_cue'],
        [
            {'check': 'regex_present', 'pattern': r'(?i)\[(bell|bell rings|church bell)\]'},
            {'check': 'regex_present', 'pattern': r'(?i)\[(dog barks?|dog barking|barking)\]'},
        ],
        HR,
    ),
    _p(
        'numerals',
        'Numerals follow house style',
        ['numerals'],
        [
            {'check': 'regex_present', 'pattern': r'\b23 barrels\b'},
            {'check': 'regex_present', 'pattern': r'\b1671\b'},
            {'check': 'regex_present', 'pattern': r'\b23 tonnen\b'},
            {
                'check': 'regex_absent',
                'pattern': r'(?i)\b(twenty-three|sixteen seventy-one|drieëntwintig|zestienhonderd)\b',
            },
        ],
        HR,
        state_note='the standing rule: digits ([[feedback_subtitle_numerals]]); the spoken words are spelled out in the SCRIPT so TTS says them right and the formatter must convert',
    ),
    _p(
        'breaks',
        'Line breaks read naturally',
        ['breaks', 'two_line', 'cps'],
        [
            {'check': 'cue_rule', 'max_lines': 2, 'max_cpl': 42, 'max_cps': 17},
            {
                'check': 'regex_absent',
                'pattern': r'(?im)\b(the|a|an|of|to|in|on|de|het|een|van|op|en)\s*\n',
                'note': 'no line ends on an article or preposition',
            },
            {
                'check': 'operator',
                'blind': True,
                'question': 'Reading the cues for the long sentence at 0:52, do the breaks fall on sense (phrase boundaries) rather than on width? yes/no',
            },
        ],
        HR,
        state_note='two_line and cps are the cue_rule parts; breaks = the regex plus the operator',
    ),
    _p(
        'punct',
        'Punctuation is correct',
        ['punct'],
        [
            {'check': 'regex_absent', 'pattern': r'  |\s[,.;:]|[,.;:]{2,}(?!\.)'},
            {
                'check': 'regex_present',
                'pattern': r'(?m)[.!?…]\s*$',
                'note': 'sentence-final cues end with punctuation',
            },
        ],
        HR,
    ),
    _p(
        'timing_rules',
        'Minimum duration and gap',
        ['min_dur', 'gap'],
        [{'check': 'cue_rule', 'min_dur': 1.0, 'max_dur': 7.0, 'gap': 0.083}],
        HR,
    ),
    _p(
        'shot_change',
        'Does not cross a cut',
        ['shot_change'],
        [{'check': 'cue_no_cross', 'cuts': 'MANIFEST.cuts', 'tolerance': 0.25}],
        HR,
        state_note='the cut-list video is generated by the MANIFEST ffmpeg command; a cue may straddle a cut by at most 6 frames',
    ),
    _p(
        'formats',
        'Exports srt and vtt',
        ['formats'],
        [{'check': 'parses_as', 'format': 'srt'}, {'check': 'parses_as', 'format': 'vtt'}],
        HR,
        state_note='text column: "srt+vtt" | "srt" | "vtt" | "neither"',
    ),
    _p(
        'burn',
        'Burn-in matches the sidecar',
        ['burn'],
        [{'check': 'ocr_matches', 'sample': 10, 'share': 0.9}],
        HR,
        state_note='the house burn filter on the cut-list video; OCR at ten cue midpoints via the typography OCR judge ([[project_typography_ocr_judge]])',
    ),
    # the four prompt questions Whisper's initial_prompt can answer
    _p(
        'pd_hint',
        'The vocabulary hint (Whisper initial_prompt) as a prompt',
        ['pd_damage', 'pd_typo', 'pd_multilingual'],
        [{'check': 'present', 'terms': ['Kattenburg', 'Cornelis', 'Joost', 'Witsen', 'Zeehond']}],
        WH,
        grid={
            'initial_prompt': [
                '',
                'Kattenburg, Cornelis, Joost, Witsen, Zeehond',
                'Kattenberg, Cornelius, Joost, Witson, Zeehont',
                'Nederlands en Engels. Kattenburg, Cornelis, Joost, Witsen, Zeehond',
            ]
        },
        state_note=(
            'pd_damage = names pass with the hint but not without (the hint is doing work); pd_typo = a misspelled hint does NOT produce the misspelling in the '
            'output; pd_multilingual = the bilingual hint does not degrade the English WER; pd_recorded = the hint used is in the run receipt'
        ),
    ),
]

NA_BANDS_WH = {
    'reason': "a transcriber takes audio and a formatter takes rules, not an instruction; Whisper's initial_prompt is a vocabulary hint and the three questions it can answer are measured in pd_hint",
    'bands': [
        'Prompt: damage',
        'Prompt: clarity needed',
        'Prompt: limits',
        'Prompt: steering',
        'Counting & quantity',
        'Space & relation',
    ],
}
NA_BANDS_HR = {
    'reason': 'the house formatter is a rule set over word timings; it has no prompt and does not reason about content',
    'bands': [
        'Prompt: damage',
        'Prompt: clarity needed',
        'Prompt: limits',
        'Prompt: steering',
        'Counting & quantity',
        'Space & relation',
    ],
}
STAGE_NA_WH = {
    c: 'this property is set by the formatter stage, not by the timing source'
    for c in [
        'speaker',
        'sfx_cue',
        'numerals',
        'breaks',
        'two_line',
        'cps',
        'punct',
        'min_dur',
        'gap',
        'shot_change',
        'formats',
        'burn',
    ]
}
STAGE_NA_HR = {
    c: 'this property comes from the ASR timing source, not from the formatter'
    for c in ['timing', 'drift', 'verbatim', 'names', 'lang']
}

TEST = {
    'step': 'subtitles',
    'version': '2026-09-28.1',
    'title': 'One planted narration through the real pipeline',
    'purpose': 'Run the production subtitle path on a fixed bilingual fixture whose transcript and word timings the operator verified, and score every house rule mechanically.',
    'include_shared': 'text',
    'house_standard': HOUSE,
    'rows': {
        'whisper_align': {
            'transport': 'pipeline',
            'model': 'zyg_whisper (voice_stt.py) word timings, initial_prompt on',
            'na': STAGE_NA_WH,
        },
        'house_rules': {
            'budget': {'minutes': 1, 'gpu_minutes': 0},
            'transport': 'pipeline',
            'model': 'pipeline_video._burn_subtitles formatter + _subtitle_digits',
            'na': STAGE_NA_HR,
            'na_bands': NA_BANDS_HR,
        },
    },
    'na_bands': NA_BANDS_WH,
    'probes': PROBES,
    'derive': {
        'speed': {'from': 'seconds of wall clock per minute of audio, per stage', 'grade': 'measured', 'unit': 's'},
        'throughput': {'from': 'minutes of audio per hour, single stream', 'grade': 'measured', 'unit': 'count'},
        'deterministic': {
            'from': 'three runs on the same audio: identical srt for the formatter (yes expected); identical word timings for Whisper (the GPU makes this a measured maybe)',
            'grade': 'measured',
        },
        'first_take': {'from': 'share of probes whose FIRST run passed', 'grade': 'measured'},
        'retries': {
            'from': 'runs until first pass, over probes that eventually passed',
            'grade': 'measured',
            'unit': 'count',
        },
        'silent_fail': {
            'from': 'a wrong cue that parses is silent; the column = share of failed probes a parser or rule check caught',
            'grade': 'measured',
        },
        'receipts': {
            'from': 'the run leaves the srt, the vtt, the word-timing json and the settings used next to the video',
            'grade': 'receipt',
        },
        'pd_recorded': {'from': 'the initial_prompt used is in that receipt', 'grade': 'receipt'},
        'cost': {'from': 'GPU seconds × the tariff in the shared lookup', 'grade': 'lowest of inputs', 'unit': 'eur'},
    },
    'lookup': {},
    'wiring': {},
    'na': {
        'pd_portable': 'there is no sibling model to carry a prompt to; both rows are stages of one pipeline',
        'pd_retries': 'no prompt is rewritten on this step; retries is the reruns column',
        'concurrency': 'one narration at a time is how the pipeline is wired; measured on the stt sheet where it is a lever',
        'batch': 'the pipeline runs per episode; one audio file per call by design',
        'previewable': 'the sidecar is text; there is nothing cheaper than the run itself to look at first',
        'ai_training': 'no output of this step is training material; the question is asked of models, not of a formatter',
    },
    'fixtures': [
        {
            'path': MANIFEST,
            'verified': False,
            'blocks': ['timing', 'drift', 'verbatim', 'lang', 'names'],
            'how_to_verify': 'synthesise the audio with the MANIFEST voices, open it in Audacity, mark the start of each word in MANIFEST.verified_words (20 words, both languages, both halves of the file), set verified = true',
        },
        {'path': FX + '/cutlist.mp4', 'generated': 'ffmpeg command in MANIFEST.video', 'verified': True},
    ],
    'budget': {
        'calls': 15,
        'tokens_in': 0,
        'tokens_out': 0,
        'tokens_note': 'Whisper takes audio and the formatter takes rules; no language-model tokens are spent on this step',
        'minutes': 8,
        'gpu_minutes': 8,
        'operator_minutes': 5,
        'note': (
            'The ~3-minute fixture through Whisper 3 times + the pd_hint grid (4 hints x 3) = 12 Whisper runs at ~30 s + 1 min model '
            'load = ~7 min on the GPU, plus 3 formatter runs (seconds). The formatter row (house_rules) is CPU and takes ~1 min (override). '
            'Operator: 3 blind questions x 3 repeats = 9 decisions = ~5 min per row, PLUS a one-time ~30 min marking the 20 verified_words '
            'in the waveform (until then the timing columns are BLOCKED).'
        ),
    },
    'notes': [
        "This test measures the PIPELINE as wired (Whisper → formatter → burn). A row's na cells say which stage owns each property, so a failing cue lands on the stage that caused it.",
        "The minimum duration, maximum duration, cps and gap are the TEST's fixed standard, not the pipeline's (it has none). If the house adopts different values, change them here and bump the version.",
        'The fixture script spells numbers out on purpose: TTS reads words right and digits inconsistently, and the formatter must convert (the standing digits rule).',
    ],
}
