# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Default test — Voice conversion (voice_conversion). 2026-09-30.

Question the sheet asks: can we put a fixed singer on a generated sung stem without losing
the melody or the words?

The step is not a chat model and not a renderer: it is a converter (Applio RVC v2, the
trained voice `warm_control_v2`), a GATE that is supposed to say whether the conversion
kept the voice (TitaNet on sung stems), and the thing being replaced (ACE-Step's own
singer, which draws a new voice from the text on every song — the CONTROL). So the test is
four FIXED sung stems from the kids catalogue, converted, and every musical property
measured AGAINST THE SOURCE STEM: a converter that improves a song has still failed, because
the job is to change the timbre and nothing else.

The shape is taken from tools/vc_bench.py, whose criteria were fixed before its run (8
held-out songs: melody 5.4 cents median, octave errors <= 0.05 %, one lyric line lost at
worst, the voice moved toward Warm Control on 7/8). This test re-uses those criteria as
THRESHOLDS and loosens them where the sheet's question is wider than the bench's
(`pitch_track_cents_max` 50, not the ship gate's 25, so a worse converter is still measured
rather than merely refused).

WHAT IS HONESTLY BLOCKED
    identity is the hard one. output/kidsmusic/_voice_build/calibration.json is a NEGATIVE
    result: on sung stems TitaNet's cosine between two halves of the SAME take has p50 0.7182
    and p10 0.5261 (n=106), while two DIFFERENT stock voices on different songs reach p50
    0.4377 and p90 0.6372 (n=605) — the distributions overlap, so no single cosine separates
    "same singer" from "another singer". The one separation that does clear is sex (male vs
    female p50 0.2701, p90 0.3718, n=660). The test therefore keeps `speaker_cosine_min` with
    the null's p90 (0.6372) as the bar, and records `identity_measurable` as a LOOKUP into
    that file so the sheet says out loud that the gate is unreliable on the male sung register
    rather than quietly grading a model against it.

    The lyric keys are not verified. The four stems are generated from output/kidsmusic by the
    recipe in `fixtures`; their transcripts are Whisper's, not a human's. `lyrics` and
    `consonants` are BLOCKED until the operator types the four lyric sheets out by hand, so
    the mechanical WER-against-the-source check below is reported but never graded as truth.

    No local model is asked "does this sound like the same singer" or "is this clipped".
    `artefacts` and the ear half of `sex_transfer` are BLIND operator checks; every other
    column has a detector (RMVPE for F0, librosa for onsets, Whisper for words, TitaNet for
    the embedding, BS.1770-4 for level).

Prompt questions are answered by the shared audio bank for ace_native, which really is
prompted (caption + lyrics). They are `na_bands` on the two rows that have no prompt at all:
RVC takes a stem and two numeric knobs, and the gate takes two stems and returns a cosine.
"""

from __future__ import annotations

# ── check kinds this module adds (the runner is a table of these) ──────────────────────
CHECK_KINDS = {
    'pitch_track_cents_max': "median |F0(converted) - F0(source)| in cents over the frames voiced in BOTH tracks (RMVPE, 10 ms hop, the converter's own f0_method) <= `max`",
    'octave_jump_share_max': 'frames whose |F0(converted) - F0(source)| is 1200 +/- `tolerance` cents, as a share of the frames voiced in both, <= `max`; the raw count is reported beside it',
    'wer_vs_source_max': 'Whisper WER of the converted stem against the Whisper transcript of the SOURCE stem (machine truth, not a human key) <= `max`',
    'onset_align_ms_max': 'median |onset(converted) - onset(source)| over librosa onsets matched nearest-neighbour within 200 ms <= `max` ms, on >= `share` of the source onsets',
    'vibrato_depth_ratio': 'F0 modulation depth in the 4-8 Hz band (converted / source), measured per sustained note >= `min_note_s`, median ratio within 1 +/- `tolerance`',
    'breath_count_delta_max': 'breath events (unvoiced-band inhale detector, >= 120 ms, between sung phrases) differ from the source by at most `max`',
    'speaker_cosine_min': 'TitaNet-L speaker cosine of the converted stem to the target reference >= `min` AND >= the distribution named in `null` by `margin`',
    'speaker_cosine_rises': 'TitaNet-L cosine to the target reference is higher for the converted stem than for its own source stem on >= `share` of the items',
    'pairwise_speaker_cosine_min': 'mean pairwise TitaNet-L cosine ACROSS the items of one row >= `min` (is it one voice on every song, whatever that voice is)',
    'f0_band_within': "share of voiced frames whose F0 lies inside `band` (Hz, the target voice's measured range) >= `min`",
    'f0_median_shift_semitones': 'median F0 over voiced frames moves from the source by >= `min` semitones in the direction `dir` (down|up)',
    'lufs_delta_max': '|integrated loudness(converted) - integrated loudness(source)| (BS.1770-4) <= `max` LU',
}

FX = 'capability_tests/fixtures/audio/stems'
KM = 'output/kidsmusic'

# The four fixed stems. Three are held-out bench songs (tools/vc_bench.py SOURCES) so this
# test and the bench can be read side by side; the fourth is a female take, because
# sex_transfer has no referent without one. All four are separated vocals, 48 kHz mono.
STEMS = [
    FX + '/km_c7284ed06145_vocals.flac',
    FX + '/km_0fc29420eb5a_vocals.flac',
    FX + '/km_37159301a13c_vocals.flac',
    FX + '/km_e2cd9a19ef90_female_vocals.flac',
]
FEMALE = STEMS[3]

# The reference the converted stem is measured toward, and the null it must beat.
TARGET_REF = KM + '/_voice_build/refs/rt_m01_warm_control.flac'
DECOY_REF = KM + '/_voice_build/refs/rt_m08_husky_bass.flac'
CALIB = KM + '/_voice_build/calibration.json'
PROVENANCE = '../../models/vc_applio/PROVENANCE.json'

# Read off CALIB on 2026-09-30. These are the numbers the thresholds below are set from.
NULL = {
    'same_take_halves': {'n': 106, 'p10': 0.5261, 'p50': 0.7182, 'p90': 0.8443},
    'cross_song_stock_stock': {'n': 605, 'p10': 0.2867, 'p50': 0.4377, 'p90': 0.6372},
    'male_vs_female': {'n': 660, 'p10': 0.1585, 'p50': 0.2701, 'p90': 0.3718},
    'read': 'the p90 of cross_song_stock_stock (0.6372) is the bar; the p10 of same_take_halves (0.5261) is BELOW it, which is the whole negative result',
}

# The converter's own settings, as production runs them (kids_music_service.convert_voice).
COND = {
    'repeats': 2,
    'index_rate': 0.5,
    'protect': 0.33,
    'sample_rate': 48000,
    'note': "each stem converted twice with identical settings: RVC is nominally deterministic and the second pass is what the shared bank's `deterministic` column reads",
}

CONV = ['applio_warm']  # the only row that produces converted audio
IDROWS = ['applio_warm', 'titanet_gate', 'ace_native']
EAR = ['applio_warm', 'ace_native']  # rows with audio an operator can listen to


def _p(pid, title, feeds, checks, rows, audio=None, **kw):
    p = {
        'id': pid,
        'title': title,
        'feeds': list(feeds),
        'inputs': {'audio': audio or STEMS, 'target_ref': TARGET_REF, 'prompt': None},
        'conditions': dict(COND),
        'checks': list(checks),
        'grade': 'measured',
        'rows': rows,
    }
    p.update(kw)
    return p


PROBES = [
    _p(
        'melody',
        'The tune survives the timbre change',
        ['melody'],
        [{'check': 'pitch_track_cents_max', 'max': 50.0}],
        CONV,
        state_rule={'yes': 1.0, 'partial': 0.5},
        state_note='every stem must pass; the ship gate in voice_conversion.MAX_MEDIAN_CENTS is 25 cents and the bench measured 5.4 median, so 50 is deliberately wider — a converter that only just fails the gate is still measured here',
    ),
    _p(
        'octave',
        'No octave flips',
        ['octave'],
        [{'check': 'octave_jump_share_max', 'max': 0.02, 'tolerance': 100}],
        CONV,
        state_rule={'yes': 1.0, 'partial': 0.5},
        state_note='voice_conversion.MAX_OCTAVE_SHARE is 0.02 and the bench measured <= 0.05 %; a single audible flip ruins a take, so this one keeps the production threshold',
    ),
    _p(
        'lyrics',
        'The words are still the words',
        ['lyrics'],
        [
            {'check': 'wer_vs_source_max', 'max': 0.10},
            {
                'check': 'wer_max',
                'max': 0.10,
                'against': 'the operator-typed lyric sheet in the fixture record',
                'note': 'BLOCKED until the four lyric sheets are verified',
            },
        ],
        CONV,
        state_note='the mechanical half (converted vs the SOURCE\'s own Whisper transcript) is always available and is what the bench\'s "lines lost <= 1" becomes here; the graded half waits on a human transcript',
    ),
    _p(
        'timing',
        'Nothing slides in time',
        ['timing'],
        [{'check': 'onset_align_ms_max', 'max': 30, 'share': 0.9}],
        CONV,
        state_note='RVC resamples and the worker returns a lag; production already corrects it (`lag_samples` in the conversion record), so the residual after that correction is what is measured',
    ),
    _p(
        'vibrato',
        'Vibrato and phrasing come through',
        ['vibrato'],
        [{'check': 'vibrato_depth_ratio', 'tolerance': 0.30, 'min_note_s': 0.4}],
        CONV,
        state_note='measured only on sustained notes >= 0.4 s; a stem with fewer than five such notes reports untested rather than a ratio over noise',
    ),
    _p(
        'breath',
        'Breaths are kept, not smoothed away',
        ['breath_keep'],
        [{'check': 'breath_count_delta_max', 'max': 1}],
        CONV,
        state_note="RVC's `protect` knob (0.33 in production) exists exactly to keep breathy and unvoiced consonants; this is the column that says whether it works",
    ),
    _p(
        'identity',
        'The voice moves toward the target',
        ['identity'],
        [
            {'check': 'speaker_cosine_min', 'min': 0.6372, 'null': 'cross_song_stock_stock.p90', 'margin': 0.0},
            {'check': 'speaker_cosine_rises', 'share': 0.75},
            {'check': 'pairwise_speaker_cosine_min', 'min': 0.60},
        ],
        IDROWS,
        state_rule={'yes': 0.75, 'partial': 0.35},
        state_note=(
            'the bar is the null\'s p90 from calibration.json, not a chosen number. The bench\'s own criterion was "rises on >= 7/8 songs", which is `speaker_cosine_rises` at 0.875; with four stems 0.75 is 3 of 4. '
            'pairwise is the "one voice on every song" half — the bench moved it 0.45 -> 0.71. READ identity_measurable BEFORE reading this cell: on sung stems the same take\'s own halves fall below this bar 10 % of the time.'
        ),
    ),
    _p(
        'range_fit',
        'The target voice reaches the song',
        ['range_fit'],
        [
            {'check': 'f0_band_within', 'band': [110.0, 330.0], 'min': 0.90},
            {
                'check': 'octave_jump_share_max',
                'max': 0.02,
                'tolerance': 100,
                'note': 'a target that cannot reach the top of the phrase flips down an octave rather than straining',
            },
        ],
        CONV,
        state_note='110-330 Hz is the male sung band read off calibration.json (register_line_median_male p50 219.1, p95 mean 288.8; the high band sits at p50 367.5 — the two modes are 1.7x apart, which is the BIMODAL sung-register finding)',
    ),
    _p(
        'sex_transfer',
        'Female stem to a male target',
        ['sex_transfer'],
        [
            {'check': 'f0_median_shift_semitones', 'min': 5.0, 'dir': 'down'},
            {'check': 'pitch_track_cents_max', 'max': 50.0, 'modulo_octave': True},
            {
                'check': 'operator',
                'blind': True,
                'question': 'Ignoring the pitch, does this take sound like a man singing rather than a woman with a filter on? yes/no',
            },
        ],
        CONV,
        audio=[FEMALE],
        state_rule={'yes': 1.0, 'partial': 0.5},
        state_note='the female stem only. F0 must actually move down (TitaNet cannot be trusted here, but male-vs-female is the ONE separation calibration.json shows clears: p50 0.2701 against 0.7182 same-take) and the melody must survive modulo the octave the transfer costs',
    ),
    _p(
        'consonants',
        'Consonants survive',
        ['consonants'],
        [
            {
                'check': 'wer_vs_source_max',
                'max': 0.15,
                'segment': 'the consonant-dense line marked in the fixture record',
            },
            {
                'check': 'wer_max',
                'max': 0.15,
                'segment': 'the same line, against the operator-typed sheet',
                'note': 'BLOCKED until verified',
            },
        ],
        CONV,
        state_note='one line per stem, chosen for plosives and sibilants; the looser 0.15 is because a consonant-dense line is harder for Whisper on the SOURCE too, and the source is the comparison',
    ),
    _p(
        'realign',
        'It goes back into the mix where it came from',
        ['realign'],
        [
            {
                'check': 'onset_align_ms_max',
                'max': 20,
                'share': 0.95,
                'note': 'after the production lag correction, measured on the remixed master, not on the bare stem',
            },
            {'check': 'lufs_delta_max', 'max': 1.0},
        ],
        CONV,
        state_note="the level half is the one that bites: vc_bench.match_gain_db records RVC's output drifting -6..+5 dB from its source, so a converter without gain matching fails this column even when every musical column passes",
    ),
    _p(
        'artefacts',
        'Nothing rings, buzzes or warbles',
        ['artefacts'],
        [
            {
                'check': 'operator',
                'blind': True,
                'question': 'Listening to this 20-second excerpt once: do you hear a digital artefact — metallic ringing, warbling on a held note, a smeared consonant, a click? yes/no (yes = there IS an artefact, which fails)',
            },
            {
                'check': 'noise_floor_max',
                'max': -55.0,
                'note': "the mechanical half: RVC's HiFi-GAN can leave a hiss floor the ear forgives on one listen",
            },
        ],
        EAR,
        audio=STEMS[:3],
        state_rule={'yes': 0.9, 'partial': 0.5},
        state_note='three 20 s excerpts per row, shuffled with the ace_native control into one unlabelled pile (the operator protocol in the audio bank). The control is in the pile so "can you hear the conversion at all" is answerable: if the unconverted takes are flagged at the same rate, the flags are noise',
    ),
    # `failsafe` is owned here, not by the bank. The bank's u_failsafe declares its input under
    # `inputs.command`, which validate_shared accepts and the step validator does not, so a step
    # that lets the bank answer this column cannot pass `check`. Owning it also makes the broken
    # input the right shape for this step: a converter is broken with a stem, not with a prompt.
    _p(
        'failsafe',
        'Fails without breaking the caller',
        ['failsafe'],
        [
            {
                'check': 'operator',
                'blind': False,
                'question': 'Did the call return a value or raise a catchable exception, leaving the process alive and the VRAM released within 30 s? yes/no',
            },
            {
                'check': 'file_absent',
                'path': 'output/capabilities/failsafe/partial.wav',
                'note': 'a half-written stem left behind is a fail: the caller would ship it',
            },
        ],
        IDROWS,
        audio=[
            "capability_tests/fixtures/audio/judge/truncated.wav (the bank's broken WAV: a header claiming 40 s over 0.2 s of data)",
            'a 0.2 s file of pure silence — no voiced frame for RMVPE or TitaNet to hold on to',
            "a stem at 8 kHz, well under the converter's 40 kHz working rate",
        ],
        conditions={'repeats': 3, 'note': 'three broken inputs, one call each; all three must come back'},
        state_rule={'yes': 1.0, 'partial': 0.34},
        state_note='sighted, not blind — there is nothing to be blind about. no = any hang past 120 s, any crash of the host process, any leaked allocation. The silence case is the one that catches this step: a converter with no voiced frame must refuse, not emit a hiss that ship_check then measures as a melody',
    ),
]

# ── the columns no trial can answer ────────────────────────────────────────────────────
DERIVE = {
    'train_cost': {
        'from': (
            "GPU hours in the training receipt for the row's voice: models/vc_applio/logs/<voice>/train.log start-to-finish, "
            'plus the dataset build that preceded it (tools/vc_warmcontrol_dataset_v2.py writes output/kidsmusic/_voice_build/vc/dataset_v2.json). '
            'Reported as hours to a NEW voice of the same quality, which is the question, not as the hours this one happened to take.'
        ),
        'grade': 'receipt',
        'unit': 'count',
    },
}

LOOKUP = {
    'identity_measurable': {
        'source': CALIB,
        'revision': 'output/kidsmusic/_voice_build/calibration.json as of 2026-09-30',
        'requires': [CALIB],
        'grade': 'receipt',
        'value': NULL,
        'state_note': (
            'NO. On sung stems TitaNet cannot tell two singers apart: same-take halves p50 0.7182 / p10 0.5261 (n=106) against different-stock-voice '
            'cross-song p50 0.4377 / p90 0.6372 (n=605) — the two distributions overlap, so any threshold either passes strangers or fails the same singer. '
            'The only separation that clears is sex (male vs female p50 0.2701, n=660). This is why identity is NOT a per-song ship gate '
            '(voice_conversion.py:21-27) and why the bench measured identity across 8 songs instead of per song. The sung register is BIMODAL '
            '(male line median p50 219.1 Hz, high p50 367.5 Hz), and the male mode is where the gate is worst.'
        ),
    },
    'train_data_need': {
        'source': 'tools/vc_bench.py header + tools/vc_warmcontrol_dataset_v2.py header',
        'revision': 'warm_control v1 2026-09-15, v2 same box',
        'requires': ['tools/vc_bench.py', 'tools/vc_warmcontrol_dataset_v2.py', PROVENANCE],
        'grade': 'receipt',
        'value': {
            'v1_minutes_voiced': 2.93,
            'v1_renditions': 7,
            'note': 'v1: 7 Warm Control renditions of Red Train, 176 s VOICED (2.93 min) — the model that passed the 8-song bench. v2 widened the dataset by a2a denoise x conditioning sweep and kept a take only if it was in the male band with >= 15 s sung; the number to quote on the sheet is minutes of VOICED target audio, not minutes of file.',
        },
    },
}

WIRING = {
    'per_song': {
        'where': 'kids_music_service.py:2736 — `ship, reasons = VC.ship_check({"lyrics": voice.get("lyrics"), "lyrics_bare": voice.get("lyrics_bare")}, after, drift)` inside convert_voice, on the normal song path; voice_conversion.ship_check is the function itself',
        'grade': 'assumed',
        'state_note': (
            "YES for the melody, lyric and intelligibility criteria: ship_check re-applies the bench's per-song thresholds (MAX_MEDIAN_CENTS 25, MAX_OCTAVE_SHARE 0.02, MAX_LINES_LOST 1) to every conversion before it ships, plus MAX_LINES_UNCLEARED 1 (2026-10-03): measured over 16 songs keeping both stems, RVC cost 8.6 points of unprompted line coverage and was worse on 13 of them, which the prompted lyric count could not see — replayed through the new gate, 9 of those 16 conversions are refused. "
            'NO for identity: it is deliberately not a per-song gate, because calibration.json says it cannot be measured per song (see identity_measurable). '
            'A check that could not measure refuses to ship (tests/test_voice_conversion_wiring.py:63-64 pins that).'
        ),
    },
    'fallback': {
        'where': 'kids_music_service.py:2584-2586 (docstring), 2593-2601 (conversion off / no reviewed stem), 2611-2615 (conversion failed), 2626-2629 (ship_check refused) — every branch returns None and the unconverted take ships; 2632-2637 writes BOTH stems/vocals.flac and stems/vocals_unconverted.flac on a shipped conversion',
        'grade': 'assumed',
        'state_note': 'YES, and it is free: the unconverted take is kept beside the song whether or not the conversion ships, so a refused conversion costs nothing but the GPU minutes',
    },
}

# ── rows ───────────────────────────────────────────────────────────────────────────────
PROMPT_BANDS = ['Prompt: damage', 'Prompt: clarity needed', 'Prompt: limits', 'Prompt: steering']

GATE_NA = {
    c: (
        'TitaNet is a speaker-embedding gate: it reads a cosine off a stem and converts nothing, '
        'so it can neither keep nor lose a musical property of the take.'
    )
    for c in ('melody', 'octave', 'lyrics', 'timing', 'vibrato', 'breath_keep', 'consonants')
}
GATE_NA.update(
    {
        'range_fit': "the gate has no target voice to reach a range with; the range that matters belongs to the converter's trained model, not to an embedding.",
        'sex_transfer': 'the gate converts nothing. Its ability to SEE a sex difference is the one thing it can do and is recorded under identity_measurable (male vs female p50 0.2701 against 0.7182 same-take).',
        'realign': 'an embedding gate emits a number, not audio; there is no stem of its own to re-align or level-match into the mix.',
        'artefacts': "there is nothing to listen to: the gate's whole output is a float.",
        'train_cost': 'TitaNet is used as a pretrained off-the-shelf embedder; no voice is trained for it, so there are no training hours to report.',
        'train_data_need': 'no voice is trained for the gate, so no minutes of target audio are needed; the reference take it compares against is one existing stem.',
    }
)

CTRL_NA = {
    c: (
        'the control IS the source stem. Measuring its drift against itself is zero by construction and measures nothing; '
        'this row exists to give the other rows a null and a blind-listening anchor, not to be scored on keeping what it never changed.'
    )
    for c in ('melody', 'octave', 'lyrics', 'timing', 'vibrato', 'breath_keep', 'consonants')
}
CTRL_NA.update(
    {
        'range_fit': 'there is no target voice on the control row: ACE-Step invents a singer from the text on every song, so "does the target reach the range" has no referent here.',
        'sex_transfer': "no conversion runs, so nothing is carried across sex; ACE-Step's singer is whatever the caption produced.",
        'realign': 'the take is already in the mix it was rendered in; there is no converted stem to put back.',
        'per_song': "no conversion runs on this row, so there is no ship_check that could be wired into every song's path.",
        'fallback': 'this row IS the unconverted take the other rows fall back to; it cannot itself have one.',
        'train_cost': 'no voice is trained: ACE-Step draws its singer from the text prompt, which is the entire problem this step exists to solve.',
        'train_data_need': 'no target voice and no training, so no minutes of target audio.',
    }
)

TEST = {
    'step': 'voice_conversion',
    'version': '2026-09-30.1',
    'title': 'Four fixed sung stems, converted, measured against their own sources',
    'purpose': (
        'Re-apply the pre-registered criteria of tools/vc_bench.py to a fixed four-stem set so any new converter is measured '
        'under byte-identical circumstances, and say out loud — from calibration.json — which of those criteria the house can actually measure.'
    ),
    'include_shared': 'audio',
    'calibration': NULL,
    'ship_gate': {
        'max_median_cents': 25.0,
        'max_octave_share': 0.02,
        'max_lines_lost': 1,
        'where': 'voice_conversion.MAX_MEDIAN_CENTS / MAX_OCTAVE_SHARE / MAX_LINES_LOST, applied by ship_check',
        'note': 'the PRODUCTION gate. The probes above are deliberately wider so a failing converter still produces a measurement instead of a refusal.',
    },
    'rows': {
        'applio_warm': {
            'transport': 'service',
            'where': 'voice_conversion.convert_stem — Applio RVC v2 (HiFi-GAN, 40 kHz) in its own venv via tools/vc_applio_worker.py',
            'model': 'warm_control_v2 (models/vc_applio/logs/warm_control_v2), index_rate 0.5, protect 0.33',
            'na_bands': {
                'reason': 'RVC conversion takes a vocal stem and two numeric knobs (index_rate, protect). There is no text prompt anywhere on this path, so no prompt question has a referent on this row.',
                'bands': PROMPT_BANDS,
            },
        },
        'titanet_gate': {
            'transport': 'service',
            'where': 'the TitaNet-L speaker-embedding gate on sung stems; its calibration is output/kidsmusic/_voice_build/calibration.json',
            'model': 'NeMo TitaNet-L speaker verification, cosine over the whole stem',
            'na': GATE_NA,
            'na_bands': {
                'reason': 'the gate takes two stems and returns a cosine; there is no prompt anywhere on its path, and no setting a prompt question could damage.',
                'bands': PROMPT_BANDS,
            },
            'budget': {
                'calls': 24,
                'minutes': 4,
                'gpu_minutes': 3,
                'operator_minutes': 0,
                'note': 'TitaNet-L embeds 4 source stems + 8 converted + 2 references + the 10 cross-song null takes = 24 embeddings at ~2 s, plus ~2 min model load. No renders, no operator.',
            },
        },
        'ace_native': {
            'transport': 'service',
            'where': 'ace_step_service.generate through the resident ComfyUI server (:8188)',
            'model': 'ACE-Step 1.5 turbo AIO (ace_step_1.5_turbo_aio.safetensors, Comfy-Org rev 54b2ef4d8af5) — the CONTROL: no conversion, the singer comes out of the caption',
            'na': CTRL_NA,
            'budget': {
                'calls': 290,
                'minutes': 115,
                'gpu_minutes': 108,
                'operator_minutes': 32,
                'note': (
                    "The CONTROL row is the only one with a prompt, so it is the only one the shared audio bank's 48 prompt and capacity probes really run on: "
                    '~50 prompt variants x 3 seeds = 150 renders plus the 7 capacity ladders at ~6 rungs x 3 seeds = 126 renders, plus 12 identity/artefact takes = ~288 ACE-Step renders '
                    'at ~20 s for a 60 s bed on the turbo checkpoint = ~96 min GPU, +2 min checkpoint load per eviction (~10 min over the run). '
                    "Operator: ~64 blind decisions over the bank's make_* and the artefact pile at 30 s = ~32 min."
                ),
            },
        },
    },
    'probes': PROBES,
    'derive': DERIVE,
    'lookup': LOOKUP,
    'wiring': WIRING,
    'na': {},
    'fixtures': [
        {
            'path': STEMS[0],
            'verified': False,
            'blocks': ['lyrics', 'consonants'],
            'generated': 'python3 tools/demucs_split.py output/kidsmusic/c7284ed06145/master.wav capability_tests/fixtures/audio/stems/_tmp --device cuda, then copy vocals.wav to km_c7284ed06145_vocals.flac at 48 kHz mono',
            'how_to_verify': "type the sung lyric out by hand from the SOURCE stem (not from the song's lyric plan — the take drops lines), mark the consonant-dense line, store both beside the stem, set verified = true",
        },
        {
            'path': STEMS[1],
            'verified': False,
            'blocks': ['lyrics', 'consonants'],
            'generated': 'same recipe on output/kidsmusic/0fc29420eb5a/master.wav',
            'how_to_verify': 'as above',
        },
        {
            'path': STEMS[2],
            'verified': False,
            'blocks': ['lyrics', 'consonants'],
            'generated': 'same recipe on output/kidsmusic/37159301a13c/master.wav',
            'how_to_verify': 'as above',
        },
        {
            'path': FEMALE,
            'verified': False,
            'blocks': ['lyrics', 'consonants'],
            'generated': 'same recipe on output/kidsmusic/e2cd9a19ef90/master.wav — chosen because its take is in the HIGH register mode (calibration.json register_line_median_high p50 367.5 Hz), which is what makes it the sex_transfer stem',
            'how_to_verify': 'as above, and confirm by ear that the source take really is a female voice before it is used as the sex_transfer input',
        },
        {
            'path': TARGET_REF,
            'verified': True,
            'generated': 'the original Warm Control take, already on disk as the bench reference rt_m01_warm_control',
        },
        {
            'path': DECOY_REF,
            'verified': True,
            'generated': 'rt_m08_husky_bass — the same-register DIFFERENT male voice the bench used as its decoy; the null a rise toward the target must beat',
        },
        {'path': CALIB, 'verified': True, 'generated': 'already on disk; written by the sung-voice calibration sweep'},
    ],
    'budget': {
        'calls': 20,
        'tokens_in': 0,
        'tokens_out': 0,
        'tokens_note': 'a converter takes audio and two floats; no language model is called anywhere on this step, so no tokens are spent and no Claude week is touched',
        'minutes': 26,
        'gpu_minutes': 22,
        'operator_minutes': 8,
        'note': (
            'Per row, defaulting to the converter. applio_warm: 4 stems x 2 repeats = 8 RVC conversions at ~25 s for a ~2 min stem = ~4 min, + ~2 min Applio venv and model load. '
            'Measurement on top: Whisper on 4 sources + 8 conversions = 12 transcriptions at ~20 s = 4 min (+1 min load); RMVPE F0 on 12 tracks ~2 min; TitaNet on 12 stems + 2 refs ~1 min '
            '(+2 min load); librosa onsets, BS.1770-4 and the breath detector are CPU seconds. 20 GPU-touching calls, ~22 GPU min, ~26 min wall. '
            'Operator: 3 artefact clips x 2 repeats + 2 sex_transfer decisions = 8 blind decisions at 30 s = 4 min, doubled to 8 for the shuffle and the second listen. '
            "SHARED AUDIO BANK for this step: 48 bank probes fire, but 46 of them are the four Prompt bands and they are na on the two rows with no prompt — the bank's real cost lands "
            "entirely on ace_native and is budgeted in that row's override (~288 renders, ~108 GPU min). Tree total is therefore ~145 GPU min, dominated by the control row. "
            'NOT included and one-time: the operator typing out four lyric sheets (~40 min), without which lyrics and consonants stay BLOCKED.'
        ),
    },
    'run_order': [
        'identity',
        'melody',
        'octave',
        'timing',
        'realign',
        'range_fit',
        'breath',
        'vibrato',
        'lyrics',
        'consonants',
        'sex_transfer',
        'artefacts',
    ],
    'notes': [
        'Every musical column is measured AGAINST THE SOURCE STEM, never against an ideal. The job is to change the timbre and nothing else, so a converter that "improves" the melody has failed.',
        'The thresholds here are wider than the production ship gate on purpose (50 cents against 25). ship_check exists to refuse a take; this test exists to measure one, and a refusal is not a measurement.',
        'identity and identity_measurable must be read together. Reading the identity cell alone, on a sheet whose own calibration says the measurement does not separate singers on sung stems, is exactly the mistake the calibration file was written to prevent.',
        'run_order puts identity and the cheap F0 probes first: they share the same 8 conversions, so a run stopped after the first hour still fills 6 of the 17 domain columns. artefacts is last because it is the only one that cannot finish without the operator.',
        'The female stem is the only one that answers sex_transfer, and the sheet should say n=1 there. Four male stems would have been cheaper and would have left the column unanswered.',
    ],
}
