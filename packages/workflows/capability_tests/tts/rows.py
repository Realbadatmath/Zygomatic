# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The engine ROWS and the TEST dict the runner loads — sections 6-7."""

from __future__ import annotations

from .constants import (
    AGED,
    BANDS,
    BANDS_NOTE,
    COND,
    COS_MARGIN,
    COS_MIN,
    COS_TAKES,
    COS_WINDOW,
    F0_PCT,
    LINES,
    LINES_NOTE,
    OVERLONG,
    PASSAGE,
    PASSAGE_RULE,
    REF_NOTE,
    REFS,
    THRESHOLD_NOTE,
    VTL_CM,
)
from .probes import PROBES

_NOT_A_SYNTH = (
    'voice_harvest_kyutai.py does not synthesise anything: it downloads the CC0 donation wavs, '
    'measures them through Praat and registers them as seeds. Kyutai withheld the voice encoder '
    'that makes its own embeddings, so their TTS can only ever speak in voices they shipped and '
    'could never say a house line in a house voice (module docstring, 2026-08-11). The row is '
    'kept because its Licence and Rights columns are real and are what the harvest is for.'
)
_NOT_A_SYNTH_NA = {c: _NOT_A_SYNTH for p in PROBES for c in p['feeds']}
_NOT_A_SYNTH_NA.update({'sr': _NOT_A_SYNTH, 'rtf': _NOT_A_SYNTH})

_EDGE_NO_REF = (
    'edge-tts speaks a fixed Microsoft catalogue voice named by id; the CLI takes no reference '
    'wav, so there is nothing for it to clone and nothing for the take to be measured against.'
)
_EDGE_NO_STYLE = (
    'the edge-tts CLI exposes --rate, --volume and --pitch and nothing else: there is no style, '
    'emotion, emphasis or tag field for a direction to land in.'
)
EDGE_NA = {
    'zero_shot': _EDGE_NO_REF,
    'similarity': _EDGE_NO_REF,
    'child': _EDGE_NO_REF + ' The catalogue has no child voice either.',
    'elderly': _EDGE_NO_REF + ' The catalogue has no elderly voice either.',
    'wear': _EDGE_NO_STYLE + ' A worn voice is not in the catalogue and cannot be asked for.',
    'emotion': _EDGE_NO_STYLE,
    'emphasis': _EDGE_NO_STYLE,
    'nonverbal': _EDGE_NO_STYLE,
    'whisper_shout': (
        '--volume is a gain, not a delivery: the level changes and the performance does not, so '
        'the meters would pass a take that is plainly not a whisper.'
    ),
    'breath': _EDGE_NO_STYLE + ' Where the catalogue voice breathes is fixed and cannot be directed.',
    'seed_stable': (
        'edge-tts has no seed parameter — it is a hosted synthesiser. Whether the same text comes '
        'back the same is the `deterministic` column, which the bank measures.'
    ),
}

_RETIRED_BARK = (
    'retired: data/models.json gpu/1007 carries deprecated = true, in_use = false, and '
    'tts_service.py has no Bark code path at all (only IndexTTS-2 and Chatterbox). Nothing in '
    'production has called it; the row is kept for the receipt that it was evaluated and dropped.'
)
_RETIRED_TORTOISE = (
    'retired: data/models.json gpu/1008 carries deprecated = true, in_use = false, and '
    'tts_service.py has no Tortoise code path. Superseded by the two cloners in the live '
    'stack; the row is kept so the sheet keeps its receipt rather than a blank column.'
)

ROWS = {
    'indextts2': {
        'transport': 'service',
        'model': 'IndexTTS-2 (data/models.json gpu/2015, in_use, 20 GB VRAM)',
        'where': 'tts_service.py — the house primary since 2026-08-06, isolated venv + subprocess worker',
    },
    'chatterbox': {
        'transport': 'service',
        'model': 'Chatterbox (data/models.json gpu/2016, in_use, 4.5 GB VRAM)',
        'where': "tts_service.py — the TTS fallback, and the engine Abel's seed was frozen against",
        'budget': {
            'minutes': 34,
            'gpu_minutes': 32,
            'note': "the lighter engine: ~8 s a line against IndexTTS-2's ~12 s, same call count",
        },
    },
    'kyutai': {
        'transport': 'service',
        'model': 'the Kyutai CC0 voice-donation harvest (wavs only; the .safetensors '
        "embeddings are pinned to Kyutai's withheld encoder)",
        'where': 'voice_harvest_kyutai.py — download / measure_all / classify / build',
        'na': _NOT_A_SYNTH_NA,
        'budget': {
            'calls': 1,
            'minutes': 2,
            'gpu_minutes': 0,
            'operator_minutes': 0,
            'note': 'a fetch and a Praat measurement of the SOURCE wavs, not a render; every column '
            "this test owns is na and what is left are the bank's Rights lookups",
        },
    },
    'edge_tts': {
        'transport': 'service',
        'model': 'edge-tts (data/models.json cpu/2104, in_use, tts-api) — the voices '
        'used here are en-GB-RyanNeural (m) and en-GB-SoniaNeural (f)',
        'where': 'the edge-tts CLI over the network; no local weights, licence is the Microsoft ToS',
        'na': EDGE_NA,
        'budget': {
            'calls': 74,
            'minutes': 12,
            'gpu_minutes': 0,
            'operator_minutes': 12,
            'note': 'a web service: no model load, no GPU, ~4 s a line over the network, and 11 of the '
            '27 domain columns are na (no reference input, no style field), so ~70 calls plus '
            'the four broken tts_failsafe calls',
        },
    },
    'bark': {
        'transport': 'retired',
        'model': 'Bark (data/models.json gpu/1007, deprecated)',
        'skip': _RETIRED_BARK,
        'budget': {
            'calls': 1,
            'minutes': 1,
            'gpu_minutes': 0,
            'operator_minutes': 0,
            'note': 'the runner skips a retired row and writes the skip reason on every column; the '
            'one call is the receipt line it writes',
        },
    },
    'tortoise': {
        'transport': 'retired',
        'model': 'Tortoise TTS (data/models.json gpu/1008, deprecated)',
        'skip': _RETIRED_TORTOISE,
        'budget': {
            'calls': 1,
            'minutes': 1,
            'gpu_minutes': 0,
            'operator_minutes': 0,
            'note': 'the runner skips a retired row and writes the skip reason on every column; the '
            'one call is the receipt line it writes',
        },
    },
}

TEST = {
    'step': 'tts',
    'version': '2026-09-30.1',
    'title': 'Twelve fixed lines and a 600-word passage, two synthetic references, measured not judged',
    'purpose': (
        'Render byte-identical text from byte-identical references on every engine and measure the '
        'take: speaker embedding against the reference and against four impostors, Praat F0 and '
        'vocal-tract length against the house calibration, Whisper timings for pace and pauses, '
        'level meters for whisper and shout, and a blind operator wherever no detector exists.'
    ),
    'include_shared': 'audio',
    'references': REFS,
    'reference_note': REF_NOTE,
    'aged_references': AGED,
    'lines': LINES,
    'lines_note': LINES_NOTE,
    'passage': {'path': PASSAGE, 'rule': PASSAGE_RULE, 'words_in_file': 674, 'words_used': 600},
    'overlong_input': OVERLONG,
    'thresholds': {
        'speaker_cosine_min': COS_MIN,
        'impostor_margin': COS_MARGIN,
        'pairwise_min': COS_TAKES,
        'window_min': COS_WINDOW,
        'f0_pct': F0_PCT,
        'vtl_cm': VTL_CM,
        'bands': BANDS,
        'note': THRESHOLD_NOTE,
        'bands_note': BANDS_NOTE,
    },
    'conditions': COND,
    'rows': ROWS,
    'probes': PROBES,
    'derive': {
        'sr': {
            'from': 'the native sample rate and bit depth the engine returned, read off the un-resampled '
            'file the worker wrote, plus whether the delivery path resampled it to 48 kHz',
            'grade': 'measured',
            'unit': 'count',
        },
        'rtf': {
            'from': 'render seconds divided by output audio seconds, over every take of the run, reported '
            'as the median and the worst case; model load excluded and reported separately',
            'grade': 'measured',
            'unit': 's',
        },
    },
    'lookup': {},
    'wiring': {},
    'na': {},
    'fixtures': [
        {
            'path': PASSAGE,
            'verified': True,
            'how_to_verify': 'plain text written into the test; verified by reading it. The word count (674 in '
            'the file, first 600 used) is checked by `wc -w`, which is the whole key.',
        },
        {
            'path': REFS['m01_warm_baritone']['wav'],
            'verified': True,
            'how_to_verify': 'the pool manifest records it as Maya1 output with its own transcript and '
            'duration_s 14.85; the 2026-08-06 voice_qc calibration measured this pool',
        },
        {
            'path': REFS['f01_warm_alto']['wav'],
            'verified': True,
            'how_to_verify': 'as above, duration_s 14.17 in data/assets/voice_seeds/pool/manifest.json',
        },
        {
            'path': AGED['elder']['wav'],
            'verified': True,
            'how_to_verify': 'the pool manifest names it "male sixties, weathered and gravelly" and the '
            'cornelis bench (2026-08-21) was built from this exact file',
        },
        {
            'path': AGED['abel']['identity_ref'],
            'verified': True,
            'how_to_verify': 'abel_narrator_seed.json records the frozen design and the rendered measurement '
            '(154.8 Hz / 15.94 cm, match 1.0); the identity reference is the known-good render',
        },
        {
            'path': AGED['child']['wav'],
            'verified': False,
            'blocks': ['child'],
            'generated': (
                'NOT a render of an adult. Either (a) a CC0 child recording whose consent covers '
                'speech synthesis — none is in the house and the Kyutai donations are adults — or '
                '(b) a Maya1 design pass in its own venv aimed at F0 >= 250 Hz AND VTL <= 13.5 cm, '
                "auditioned exactly as Abel's seed was, then frozen to this path with a sidecar "
                'json in the abel_narrator_seed.json shape. The Abel design notes are the warning: '
                'VTL saturates around 14.4 cm at large pitch shifts, so the obvious pitch-shift '
                'recipe lands in adult-female territory instead of in a child.'
            ),
            'how_to_verify': (
                "the operator listens once, blind, and answers the child probe's own question "
                '("is this a child rather than a teenager, a woman or a man in falsetto?"); '
                'voice_qc must also put it in the child band (F0 >= 200 Hz, VTL <= 14.5 cm). '
                'Both must agree before the flag is flipped.'
            ),
        },
    ],
    'budget': {
        'calls': 117,
        'tokens_in': 0,
        'tokens_out': 0,
        'tokens_note': 'a TTS engine takes fixed text and a reference wav; no language model is called, so no '
        'prompt or completion tokens are spent anywhere in this test',
        'minutes': 45,
        'gpu_minutes': 43,
        'operator_minutes': 30,
        'note': (
            'Per cloner row (indextts2 at ~12 s a short line): zero_shot 2 refs x 3 seeds = 6, similarity '
            '4 lines x 2 x 3 = 24, across_takes 2 x 3 sessions = 6, quiet_fail 2 x 3 = 6, child 2 refs x '
            '3 = 6, elderly 3, wear 3, emotion 4 x 3 = 12, pace 3 x 3 = 9, emphasis 2 x 3 = 6, '
            'whisper_shout 2 x 3 = 6, nonverbal 3, numbers 3, roman 2 x 3 = 6, names_pron 3, foreign 3, '
            'long_sentence 3, long_form 3, age_stable 3, seed_stable 2, tts_failsafe 4 broken calls '
            '= 117 calls. sex, breath, '
            'punct_obey, artefacts and noise_floor score EXISTING takes (`reuses`) and add nothing. '
            'Wall: ~100 short renders x 12 s = 20 min, long_form 3 x 240 s of audio at RTF 0.5 = 6 min, '
            'age_stable 3 x 90 s = 2 min, the 1800-word overlong leg capped at 300 s x 3 = up to 15 min, '
            'model load 2 min => ~45 min, 43 of them on the GPU. Operator: ~60 blind decisions at 30 s '
            '(names_pron alone is 12, emotion 12, artefacts 6) = 30 min per cloner row. SHARED BANK on '
            'top of this, per row: 53 Makes x 3 seeds = 159 renders, the 53 Hears fixtures, the seven '
            "Capacity ladders and the four Prompt bands — the bank's own budget states that cost and it "
            'dwarfs this one; schedule the bank separately. NO Claude row: nothing here touches the '
            'shared anthropic/claude_cli week. One-time, not per row: ~30 min for the operator to build '
            'and verify child_reference.wav, until which `child` is blocked.'
        ),
    },
    'run_order_note': (
        '`run_order` on every probe: the mechanical, cheap and short legs first (quiet_fail, '
        'numbers, zero_shot, sex, pace, emphasis), the reused scorings in the middle, and the '
        'minutes-long renders last (long_form, age_stable) with the operator-only columns after '
        'them. A run stopped halfway has filled the columns that cost least.'
    ),
    'notes': [
        'The sheet asks for a CHILD column and the house cannot answer it honestly yet. Abel is the only '
        'young reference on disk and he is teen_male by deliberate operator choice (story age 12, voice age '
        '14-15, "the 12-year-old render read too young for narration this grave"). Scoring that take as a '
        "child would be the silent-wrong-answer the sheet's verdict warns about, so `child` is BLOCKED and "
        'the Abel leg is reported for what it is.',
        'Every level is read off the RAW engine output. The service normalises to -16 LUFS '
        '(_TTS_LOUDNORM I=-16:TP=-1.5:LRA=11) and a run dd36662e measured -26.8 LUFS before that fix — so a '
        'meter on the delivered file measures the normaliser, not the engine.',
        'roman and numbers measure the SERVICE as much as the engine: tts_service.py expands roman numerals '
        'for the voice only, gated on a preceding capitalised word of 3+ letters, and subtitles never pass '
        'through it (the standing digits rule). A cell that fails there must name the leg.',
        'The two references are synthetic (Maya1, apache-2.0). That is deliberate: it keeps the consent and '
        'real-person questions on the voice_clone sheet where they are asked, and keeps this sheet about '
        'whether the engine holds a voice.',
        "edge_tts is a WEB service. It is off-box by construction (the bank's `offline` column records it), "
        'its licence is the Microsoft ToS rather than a weights licence, and 11 of the 27 domain columns are '
        'na because the CLI has no reference input and no style field.',
    ],
}
