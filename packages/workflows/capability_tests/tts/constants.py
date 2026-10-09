# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Check kinds, the two fixed references, the thresholds, the twelve lines and
the run conditions — the tts sheet's inputs, sections 1-4."""

from __future__ import annotations

# ── check kinds this module adds ───────────────────────────────────────────────────────
# The first four are worded IDENTICALLY to capability_tests/voice_clone.py on purpose: one
# runner implementation must serve both sheets, or the two are not comparable.
CHECK_KINDS = {
    'speaker_cosine_min': (
        'cosine of the wespeaker-voxceleb-resnet34-LM speaker embedding of the take '
        'against the reference named by `to` (a donor id or a trial id) >= `min`, AND '
        '>= the impostor mean for that take (its cosine against the OTHER donor '
        'references of this test) + `margin`'
    ),
    'speaker_cosine_pairwise_min': (
        'every pair of takes in the trial set has speaker-embedding cosine >= `min` (the same-voice-across-takes test)'
    ),
    'f0_vtl_band': (
        'voice_qc.py (Praat/parselmouth in its own venv) median F0 within `f0_pct` per cent '
        'and vocal-tract length within `vtl_cm` cm of the values measured on the reference '
        'named by `to` — BOTH must hold, because pitch alone is fakeable'
    ),
    'speaker_cosine_window_min': (
        'speaker-embedding cosine of the LAST `window_s` seconds of the take '
        'against its own FIRST `window_s` seconds >= `min` — drift inside one '
        'render, measured without any reference'
    ),
    'f0_median_range': (
        'voice_qc median F0 of the take between `min` and `max` Hz — an ABSOLUTE band '
        'from the 2026-08-06 calibration (voice_qc.AGE_BANDS), not a comparison'
    ),
    'vtl_range': (
        'voice_qc vocal-tract length between `min` and `max` cm — the size cue that decides '
        'whether a listener hears a child; the second half of every age or sex claim'
    ),
    'f0_drift_max': (
        'median F0 of the LAST `window_s` s differs from the FIRST `window_s` s by at most '
        '`max_pct` per cent, and the per-30-s medians have no monotone trend larger than '
        '`max_pct` end to end (the speaker must not age mid-render)'
    ),
    'error_surfaced': (
        'the service call on a degenerate input (`on`: empty|overlong) either raises, or '
        'returns a falsy/error object the caller can test — and does NOT return a wav. '
        'A returned wav shorter than `silent_wav_s` seconds, or with no voiced frame, is '
        'the SILENT FAILURE this check exists to catch and scores no. A call that has '
        'not returned after `timeout_s` s is recorded as a timeout, which is also no.'
    ),
    'wpm_range': (
        'words per minute from the faster-whisper word timestamps (first word start to last '
        'word end, over the word count of the input text) within `tolerance_pct` per cent of '
        '`wpm`'
    ),
    'emphasis_db_min': (
        'RMS of the Whisper-timed span of the word named by `word` exceeds the mean RMS '
        'of its two neighbouring words by >= `min_db` dB in the MARKED take, and by less '
        'than `min_db` in the unmarked control take'
    ),
    'rms_dbfs_range': (
        'RMS of the voiced frames of the take between `min` and `max` dBFS, measured '
        'BEFORE any loudness normalisation (the raw engine output, not the -16 LUFS file)'
    ),
    'click_count_max': (
        'count of samples where the second difference of the waveform exceeds `k` times '
        'the median absolute second difference of the file, grouped into events at least '
        '5 ms apart, <= `max`'
    ),
    'waveform_corr_min': (
        "Pearson correlation of the two takes' float32 sample vectors (zero-padded to "
        'the longer, no alignment search) >= `min`'
    ),
}

# ── fixed references ──────────────────────────────────────────────────────────────────
SEEDS_DIR = 'data/assets/voice_seeds'
POOL = SEEDS_DIR + '/pool'
FX = 'capability_tests/fixtures/tts'

REF_SECONDS = 10.0
REFS = {
    'm01_warm_baritone': {
        'wav': POOL + '/m01_warm_baritone.wav',
        'sex': 'm',
        'seconds': 14.85,
        'note': "adult male, warm baritone — the pool's documentary narrator",
    },
    'f01_warm_alto': {
        'wav': POOL + '/f01_warm_alto.wav',
        'sex': 'f',
        'seconds': 14.17,
        'note': 'adult female, warm alto — the sex counterpart on the same recipe',
    },
}
REF_NOTE = (
    'The reference handed to every engine is the FIRST 10.0 s of the wav, cut on a sample '
    'boundary, unprocessed. Both seeds are Maya1 output (apache-2.0, `maya_seed` in the pool '
    'manifest): wholly synthetic, so no human consent question rides on this test — consent is '
    "the voice_clone sheet's column. Two references, not four, because every probe here runs "
    'the whole line set and the sheet asks 27 domain columns; the impostor mean for the '
    'speaker_cosine margin is taken against the OTHER reference plus the elder and Abel '
    'references, which gives four impostors per take.'
)

AGED = {
    'elder': {
        'wav': POOL + '/m03_elder_gravel.wav',
        'note': 'male sixties, weathered and gravelly — the source of the cornelis wear bench',
    },
    'abel': {
        'wav': SEEDS_DIR + '/abel_narrator_seed.wav',
        'identity_ref': SEEDS_DIR + '/abel_identity_reference.wav',
        'note': 'voice_age 14-15, age_class teen_male. Gated against the identity REFERENCE '
        '(a known-good render), never against the seed: the seed is DSP-shifted audio '
        'whose formants measure differently from what a model re-synthesises '
        '(13.87 cm seed vs 11.99 cm render, abel_voice.py 2026-08-06)',
    },
    'child': {'wav': FX + '/child_reference.wav', 'note': 'does not exist yet — see fixtures'},
}

# ── thresholds, with the receipt or the reason ────────────────────────────────────────
COS_MIN = 0.55  # the wespeaker resnet34-LM same-speaker operating point
COS_MARGIN = 0.15  # over the impostor mean
COS_TAKES = 0.75  # same row, same reference, three takes — an easier bar than reference-match
COS_WINDOW = 0.75  # last 30 s against the take's own first 30 s
F0_PCT = 18  # voice_qc.F0_TOL_PCT
VTL_CM = 1.0  # voice_qc.VTL_TOL_CM

THRESHOLD_NOTE = (
    'F0_PCT and VTL_CM are the house gates, read off voice_qc.py (ZYG_VOICE_QC_F0_TOL_PCT=18, '
    'ZYG_VOICE_QC_VTL_TOL_CM=1.0), calibrated 2026-08-06 against this same 16-voice pool: adult male '
    '17.30 cm / 90 Hz, adult female 14.44 cm / 174 Hz. The cosine numbers are NOT a house receipt — no '
    "engine-versus-engine clone cosine has ever been measured here (the sheet's own limitation) — so "
    "0.55 is the test's declared standard, the usual same-speaker side of the resnet34-LM operating "
    'point, and it is only half the rule: every trial also carries its IMPOSTOR mean and must clear it '
    'by 0.15. That half cannot be gamed by an engine that merely sounds like a plausible narrator. '
    'Replace 0.55 with the measured distributions after the first full run and bump the version; the '
    'margin rule stays.'
)
BANDS = {
    'child': {'f0': (200.0, 400.0), 'vtl': (0.0, 14.5)},
    'teen_male': {'f0': (140.0, 200.0), 'vtl': (14.0, 16.8)},
    'adult_male': {'f0': (0.0, 165.0), 'vtl': (15.5, 25.0)},
    'adult_female': {'f0': (150.0, 230.0), 'vtl': (0.0, 15.5)},
}
BANDS_NOTE = (
    'Straight from voice_qc.AGE_BANDS, open ends closed with physical rails. The `child` band '
    'is F0 >= 200 Hz AND VTL <= 14.5 cm — NOT a 250-400 Hz pitch window: an adult in falsetto '
    'passes a pitch-only check, which is the whole reason this column is separate from '
    "zero_shot. voice_qc's own caveat stands and is repeated on the sheet: teen_male and "
    'adult_female genuinely overlap on F0+VTL, so those two are never separated by the meter '
    'alone and the operator decides.'
)

# ── the twelve fixed lines, verbatim ──────────────────────────────────────────────────
# 1-5 are voice_studio.DEFAULT_LINES, copied character for character: every bench on disk
# (teens, cornelis, farmyard, redtrain) measured on DEFAULT_LINES[0], so a take here can be
# read against those numbers. 10 is capability_tests/voice_clone.py's DUTCH line, same reason.
LINES = {
    'ledger_open': (
        'Five hundred and ninety three days. That is how long we have been '
        'at sea. I am tasked with upkeep of the ledgers, and with writing a '
        'journal of our voyage. The men are tired and malnourished. Our ship '
        'is broken. Yet home is far away, like a distant memory. It is '
        'likely we will not return.'
    ),
    'epigraph': (
        'What we speak is not to be written. What we write is not to be '
        'spoken; therefore, I will tread carefully in the telling of our '
        'journey.'
    ),
    'modern_plain': (
        "I'll be honest with you. I read it twice, and I still don't know "
        "what they want us to do, or who's supposed to decide."
    ),
    'sibilance': (
        'She spoke softly, six or seven sentences at most, and then stopped, '
        'and the whole street seemed to stop with her.'
    ),
    'dynamics': ('Listen. Not a sound now, not one, until I say so. And then, all at once, everything.'),
    'numerals_en': (
        'On 17 October 1671 the yard took in 23 barrels of pitch at 4.5 guilders '
        'each, and the tide turned at half past four.'
    ),
    'roman': {
        'in_context': 'Pope Sixtus XVII signed the charter, and Chapter XVII records it.',
        'bare': 'The mark cut into the beam read XVII, and nobody could say who put it there.',
    },
    'names_nl': 'Cornelis en Joost liepen van Kattenburg naar het huis van Witsen.',
    'foreign_en': 'The pinas sailed for Texel, and Joost called her a schuit, which she was not.',
    'dutch_plain': (
        'In het jaar zestienhonderdtweeënzeventig weigerde de havenmeester van Kattenburg '
        'drieëntwintig tonnen pek aan de scheepsbouwmeester.'
    ),
    'long_sentence_60': (
        'When the second consignment of oak was sold out from under the yard by a broker '
        'in Hoorn who had never set foot on a slip, and the ropewalk sent word that it '
        'wanted payment before it would spin another fathom, Witsen came down from the '
        'office with his figures and read them to the four of us.'
    ),
    'nonverbal': (
        '[laughs] I told him the tide would not wait. [sigh] He did not believe me, and then '
        'the water came up over the sill.'
    ),
}
LINES_NOTE = (
    'Twelve ids. `roman` holds two variants because the SERVICE decides that column as much as '
    'the engine does. Marked positions are named by the probes and never written into the text: '
    'the emphasis word is `ledgers` in ledger_open, the breath points are the two commas in '
    'epigraph, and the whisper/shout directions run on dynamics. No probe may paraphrase, '
    'shorten, re-punctuate or translate a line.'
)

PASSAGE = FX + '/passage_600.txt'
PASSAGE_RULE = (
    'the FIRST 600 words of passage_600.txt (the file holds 674), cut on a word boundary with '
    'the trailing comma replaced by a full stop — about 4 minutes of audio. The age_stable leg '
    'is the first 225 words (~90 s). Never paraphrased, never re-ordered.'
)
OVERLONG = (
    'the first 600 words of passage_600.txt repeated three times and joined with single spaces into '
    "ONE line with no sentence-final punctuation added — 1800 words, ~10 kB, against the service's "
    '350-character chunker (_TTS_MAX_CHARS)'
)

COND = {
    'seeds': [11, 12, 13],
    'repeats': 3,
    'sample_rate_out': 48000,
    'channels': 1,
    'references': list(REFS),
    'note': "the audio bank's conditions: three seeds, three repeats, delivered 48 kHz mono. Each "
    'engine renders at its NATIVE rate (IndexTTS-2 24 kHz, Chatterbox 24 kHz, edge-tts 24 kHz '
    'mp3) and the runner records `native_rate` on the trial, then resamples with soxr VHQ for '
    'the detectors — the same resampler for every row. Every other generation setting is the '
    'engine default, recorded verbatim. Levels are measured on the RAW engine output, before '
    "the service's -16 LUFS loudnorm (_TTS_LOUDNORM I=-16:TP=-1.5:LRA=11), or a whisper and "
    'a shout arrive at the meter at the same level.',
}
COND_ONE = dict(
    COND,
    seeds=[11],
    repeats=3,
    note='three repeats at seed 11 on m01_warm_baritone only — the cheap legs, where a second reference buys nothing',
)
