# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Default test — Audio judges & gates (audio_judges). 2026-09-30.

Question the sheet asks: does the gate CATCH a bad take — and leave a good one alone?

A judge is only worth its threshold, so this test never asks a row whether a take sounds
good. It plants a KNOWN fault, hands the row the faulty take and its CLEAN TWIN, and reads
two numbers: did the row flag the planted one (recall), and did it keep quiet on the twin
(false alarm). One planted fault per column, thirteen pairs, three repeats. A row that
cannot see a class of fault scores `no` on that column and the cell says so — that is the
finding the sheet is for, not a hole in the test.

Why pairs and not single files: a gate that flags everything has perfect recall and is
useless. `false_alarm_a` is the same thirteen clean twins with the flag count required to
be ZERO, so a row cannot buy recall with paranoia. The two columns are scored off the same
passes.

What this test refuses to assume:

  * THAT A THRESHOLD WAS CALIBRATED. `calibrated` is a lookup that must produce the
    calibration artefact and the pool it was built on. voice_qc has one (16 seed voices,
    2026-08-06, voice_qc.py:44-57, output/kidsmusic/_voice_build/calibration.json).
    audio_qc's -14 LUFS / -1 dBTP is a PLATFORM spec, not a house calibration, and CLAP's
    0.45-0.60 threshold has no calibration receipt at all. The cell says which.
  * THAT A GATE ACTUALLY BLOCKS. `blocks_ship` is wiring, graded assumed and visible as
    assumed, with the file:line where the pipeline refuses the mux — and with the
    environment variable that switches it off (ZYG_AUDIO_QC_ENFORCE, abel_voice.py:369).
    An installed gate that nothing consults is not a gate.
  * THAT THE SUNG REGISTER WORKS. The titanet_sung row carries its own receipt showing the
    figure is BIMODAL on sung stems (kids_music_service.py:3180-3185). It is kept as a row
    because it is wired, and every column it cannot answer is na with the reason.

No local VLM or LLM judges anything here. Every check is a meter, a cosine or a word-error
rate against a verified transcript; the operator appears only where a flag must be believed
(false_alarm_a) or where a refusal must be read (refuses, failsafe).

BLOCKED: the planted faults that only an ear can confirm — truncation, mispronounce,
drift, lyrics, delivery, age, sex, wrong voice — ship `untested — key unverified` until
the operator signs each fixture off. Nothing in this module generates a file.
"""

from __future__ import annotations

FX = 'capability_tests/fixtures/audio/planted'

# Check kinds this step needs and the base vocabulary does not have. The audio and judge
# banks already own the sound-label, capacity and universal kinds; these four are the
# planted-pair vocabulary, and the runner needs exactly them to score this sheet.
CHECK_KINDS = {
    'gate_flags_planted': (
        'for every pair in `pairs` the row must FLAG the planted member and NOT '
        'flag its clean twin, on every repeat. A "flag" is the row\'s own '
        'documented verdict turning negative (ok False, or the figure crossing '
        "the threshold named in `flag_is`) — never the runner's opinion of the "
        'audio. Scored as recall over the planted members >= `recall_min` AND '
        'false-alarm rate over the twins <= `fa_max`; a row that flags both '
        'members scores no, because it has not caught anything'
    ),
    'no_flag_on_clean': (
        'over the `n` clean twins, across every repeat, the row raises at most '
        '`max_flags` flags. Any flag it does raise is recorded with the file name '
        'and goes to the blind operator question before the cell is written'
    ),
    'gate_abstains': (
        'on the input in `on`, too short or too quiet to measure, the row must return '
        'its documented ABSTAIN value (`abstain_is`) — not a pass, not a fail. A '
        'confident figure on unmeasurable input is a no, however the figure reads'
    ),
    'returns_none_not_raise': (
        'for every broken input in `inputs` the row returns its documented failure '
        'value (None, or a dict whose ok is False/None) and NO exception crosses the '
        'module boundary: the runner asserts the call returned, the process exit code '
        'is 0 and stderr carries no traceback'
    ),
}

# Every threshold the rows are read against, with the line it comes from. Nothing here is
# this test's invention except the recall / false-alarm bar, which is stated as such.
HOUSE = {
    'recall_min': 1.0,
    'fa_max': 0.0,
    'repeats': 3,
    'lufs_target': -14.0,
    'lufs_tol': 1.0,
    'true_peak_max': -1.0,
    'silence_tol_ms': 150,
    'unscripted_max_ms': 800,
    'silence_floor_s': 0.25,
    'wpm_min': 125,
    'wpm_max': 165,
    'wpm_min_match': 0.9,
    'clap_threshold': 0.60,
    'clap_threshold_music': 0.45,
    'f0_tol_pct': 18,
    'vtl_tol_cm': 1.0,
    'titanet_cos_min': 0.50,
    'source': (
        'lufs/true peak: audio_qc.qc_lufs(target=-14.0, tol=1.0, tp_max=-1.0) audio_qc.py:127. '
        'silence: audio_qc.qc_silence_map(tol_ms=150, unscripted_max_ms=800) audio_qc.py:173, '
        'detection floor _SILENCE_MIN_S = 0.25 audio_qc.py:52. wpm: _WPM_RANGE_DEFAULT = '
        '(125, 165) audio_qc.py:258, qc_wpm(min_match=0.9) audio_qc.py:261. clap: '
        'audio_qc.qc_clap(threshold=0.6) audio_qc.py:425, and the music leg calls it at 0.45 '
        '(kids_music_service.py:1774) — TWO live thresholds for one detector, which is why '
        '`calibrated` cannot be answered yes for CLAP. voice: F0_TOL_PCT = 18, VTL_TOL_CM = 1.0 '
        "voice_qc.py:42-43. RECALL 1.0 AND FALSE ALARM 0 OVER 3 REPEATS IS THIS TEST'S BAR, "
        'not a production constant: a gate that misses one planted fault in three tries is '
        'not a gate we can ship behind.'
    ),
}

# The bank's conditions, so a judge trial and a sound trial are never scored side by side.
COND = {
    'repeats': 3,
    'seeds': None,
    'sample_rate': 48000,
    'channels': 1,
    'note': (
        '48 kHz mono 24-bit fixtures, byte-identical for every row. Every row here is a '
        'deterministic measurement (meters, Praat, a pinned CLAP checkpoint, a pinned '
        'TitaNet checkpoint), so `seed` is written null and the 3 repeats measure the '
        'install — a row whose three repeats disagree fails `deterministic` in the bank, '
        'and its recall is read off the WORST repeat, never the best.'
    ),
}

ALL = ['audio_qc', 'voice_qc', 'clap_check', 'titanet_sung']

# ── the thirteen planted pairs: (planted file, clean twin, what was done to it) ────────────
PAIR = {
    'clipped': (FX + '/clipped.wav', FX + '/clean/line_adult_male.wav'),
    'dead_air': (FX + '/dead_air.wav', FX + '/clean/line_adult_male.wav'),
    'truncated': (FX + '/truncated.wav', FX + '/clean/line_adult_male.wav'),
    'click_burst': (FX + '/click_burst.wav', FX + '/clean/line_adult_male.wav'),
    'mispron': (FX + '/mispron.wav', FX + '/clean/line_kattenburg.wav'),
    'drift': (FX + '/drift.wav', FX + '/clean/line_adult_male.wav'),
    'monotone': (FX + '/monotone.wav', FX + '/clean/line_adult_male.wav'),
    'wrong_key': (FX + '/wrong_key.wav', FX + '/clean/song_in_key.wav'),
    'wrong_lyric': (FX + '/wrong_lyric.wav', FX + '/clean/song_in_key.wav'),
    'adult_child': (FX + '/adult_for_child.wav', FX + '/clean/line_child.wav'),
    'male_female': (FX + '/male_for_female.wav', FX + '/clean/line_adult_female.wav'),
    'wrong_cast': (FX + '/wrong_cast.wav', FX + '/clean/line_adult_male.wav'),
    'dog_for_bell': (FX + '/dog_for_bell.wav', FX + '/clean/bell_church.wav'),
}


def _pair(pid, title, feeds, key, rows, flag_is, note, extra=()):
    """One planted pair, one column. `flag_is` names the row's own verdict that counts as a
    flag, so the runner never decides for itself what "caught" means."""
    planted, clean = PAIR[key]
    return {
        'id': pid,
        'title': title,
        'feeds': list(feeds),
        'inputs': {'fixture': planted + '  vs  ' + clean, 'audio': planted, 'prompt': None},
        'conditions': dict(COND),
        'checks': [
            {
                'check': 'gate_flags_planted',
                'pairs': [[planted, clean]],
                'recall_min': 1.0,
                'fa_max': 0.0,
                'flag_is': flag_is,
            }
        ]
        + list(extra),
        'grade': 'measured',
        'rows': list(rows),
        'state_note': note,
    }


PROBES = [
    # ── level & timing: a meter decides, cheapest first ───────────────────────────────────
    _pair(
        'catch_clipping',
        'Catches clipping',
        ['clipping_j'],
        'clipped',
        ['audio_qc'],
        'audio_qc.qc_lufs / run_master_gates returns ok False on true peak (tp_max=-1.0, audio_qc.py:127)',
        'the planted take is the clean line at +12 dB written as s16, so a run of exactly-full-scale samples exists and true peak is above 0 dBTP. Mechanically checkable, which is why this fixture needs no ear to verify',
    ),
    _pair(
        'catch_silence',
        'Catches dead air',
        ['silence_j'],
        'dead_air',
        ['audio_qc'],
        'audio_qc.qc_silence_map returns ok False on an unscripted silence (unscripted_max_ms=800, audio_qc.py:173)',
        'a 4000 ms gap spliced mid-line, well over the 800 ms unscripted ceiling and well over the 250 ms detection floor (audio_qc.py:52); the clean twin carries only its scripted pauses',
    ),
    _pair(
        'catch_truncation',
        'Catches a truncated line',
        ['truncation'],
        'truncated',
        ['audio_qc'],
        'audio_qc.qc_wpm transcript match ratio falls below min_match=0.9 (audio_qc.py:261), or qc_runtime reports short',
        'the last word is cut 120 ms into its first syllable: the file still decodes, the loudness is perfect, and only the transcript-against-script comparison can see it. This is the column where a level meter is provably blind',
    ),
    _pair(
        'catch_artefact',
        'Catches synthesis artefacts',
        ['artefact_j'],
        'click_burst',
        ['audio_qc'],
        'audio_qc.run_stem_gates reports ok False (true peak, or the fade/runtime gate) on the burst',
        'six 2 ms full-scale clicks at 1.5 s intervals — the shape a truncated decoder frame makes. A click is a transient, so the true-peak gate is the mechanism; a gate that only measures INTEGRATED loudness will miss it, and that miss is the finding',
    ),
    # ── behaviour: the paranoia and refusal columns ───────────────────────────────────────
    {
        'id': 'clean_takes',
        'title': 'Leaves a good take alone',
        'feeds': ['false_alarm_a'],
        'inputs': {'fixture': FX + '/clean/*.wav (the 13 clean twins)', 'audio': FX + '/clean', 'prompt': None},
        'conditions': dict(COND),
        'checks': [
            {'check': 'no_flag_on_clean', 'n': 13, 'max_flags': 0},
            {
                'check': 'operator',
                'blind': True,
                'question': 'You are hearing one take with no filename. Is there anything wrong with it — a click, a gap, a cut-off word, the wrong voice, a flat delivery? yes/no',
            },
        ],
        'grade': 'measured',
        'rows': ALL,
        'state_note': (
            'the same clean twins the thirteen pairs use, so recall and false alarm are read off one set of '
            'passes and a row cannot trade one for the other. The blind question is asked ONLY about a take the '
            'row flagged: if the operator hears the fault too, the flag was right and the FIXTURE is replaced, '
            'not relabelled — we do not score a gate down for hearing something real.'
        ),
    },
    {
        'id': 'refuses',
        'title': 'Refuses when it cannot measure',
        'feeds': ['refuses'],
        'inputs': {
            'fixture': FX + '/refuse/too_short_0p3s.wav',
            'audio': FX + '/refuse/too_short_0p3s.wav',
            'prompt': None,
        },
        'conditions': dict(COND),
        'checks': [
            {
                'check': 'gate_abstains',
                'on': FX + '/refuse/too_short_0p3s.wav',
                'abstain_is': 'ok is None with a reason (the soft-gate shape of audio_qc.py:8-13), or the documented None/unmeasurable return of the row',
            },
            {
                'check': 'gate_abstains',
                'on': FX + '/refuse/digital_silence_2s.wav',
                'abstain_is': 'ok is None or a silent=True report — NOT a loudness verdict computed against -70 LUFS',
            },
            {
                'check': 'operator',
                'blind': False,
                'question': "Reading the row's output for these two unmeasurable inputs, does it say it could not measure, rather than returning a figure it cannot support? yes/no",
            },
        ],
        'grade': 'measured',
        'rows': ALL,
        'state_note': (
            '0.3 s is below every window these rows use: below the 250 ms silence floor, far below the 3 s '
            'short-term loudness window, below one Praat pitch frame set, below the CLAP input length and below '
            'the TitaNet enrolment minimum. The only honest answer is "I cannot measure this". A row that '
            'returns a confident cosine or a confident LUFS figure on 0.3 s scores no, and the figure it '
            'returned is written into the note as the evidence.'
        ),
    },
    # `failsafe` is a universal column, but these rows carry an explicit never-raise contract
    # at the module boundary (audio_qc.py:8-13), so the step measures it instead of the bank
    # reading it off the code.
    {
        'id': 'failsafe',
        'title': 'Fails without breaking the caller',
        'feeds': ['failsafe'],
        'inputs': {
            'fixture': FX + '/refuse/broken_header.wav',
            'audio': FX + '/refuse/broken_header.wav',
            'prompt': None,
        },
        'conditions': dict(COND),
        'checks': [
            {
                'check': 'returns_none_not_raise',
                'inputs': [
                    'a zero-byte file named .wav',
                    FX + '/refuse/broken_header.wav (header claims 40 s, holds 0.2 s of data)',
                    'a path that does not exist',
                    FX + '/refuse/digital_silence_2s.wav',
                ],
            },
            {
                'check': 'operator',
                'blind': False,
                'question': 'Reading the run log for these four broken inputs, did the row report WHICH input it refused and why, rather than failing quietly? yes/no',
            },
        ],
        'grade': 'measured',
        'rows': ALL,
        'state_note': (
            'the house contract is explicit: an audio_qc gate returns a dict with a measured verdict and never '
            'raises across the module boundary; hard gates fail CLOSED and the soft CLAP gate fails OPEN with '
            'ok=None (audio_qc.py:8-13). voice_qc runs in its own Praat venv as a subprocess, so the failure '
            'mode to measure there is a non-zero exit leaking as an exception into the caller.'
        ),
    },
    # ── identity: a cosine or a formant decides ───────────────────────────────────────────
    _pair(
        'catch_drift',
        'Catches timbre drift mid-render',
        ['drift_j'],
        'drift',
        ['voice_qc', 'clap_check', 'titanet_sung'],
        "voice_qc: the second-half median F0 or VTL leaves the first half's band (F0_TOL_PCT=18 / VTL_TOL_CM=1.0, voice_qc.py:42-43). clap_check: the qc_clap figure is the MINIMUM window score (audio_qc.py:433), so the half rendered by another voice pulls it under threshold. titanet_sung: window-to-window cosine below 0.50",
        'two cast voices concatenated at exactly 50 % of the line, same script, same loudness, no seam click. The whole-file median hides it and the windowed figure does not — which is the point of carrying three rows with three different windows',
    ),
    _pair(
        'catch_age',
        'Catches a wrong age',
        ['age_wrong'],
        'adult_child',
        ['voice_qc', 'titanet_sung'],
        'voice_qc.gate_voice_identity reports the age band wrong: median F0 below the child f0_min (200 Hz) or VTL above the child vtl_max (14.5 cm)',
        "a child's scripted line delivered by an adult cast voice. voice_qc has a calibrated band for exactly this (voice_qc.py:44-57); the caveat in that table is that teen_male OVERLAPS adult_female, so this fixture deliberately uses child-vs-adult, the separation the calibration actually supports",
    ),
    _pair(
        'catch_sex',
        'Catches a wrong sex',
        ['sex_wrong'],
        'male_female',
        ['voice_qc', 'titanet_sung'],
        'voice_qc: median F0 and VTL land in the male band on a line scripted for a female voice. titanet_sung: cosine to the female cast reference below 0.50',
        "the one identity separation that has a measured receipt on sung material as well as speech: male vs female TitaNet cosine 0.27 against 0.45 same-voice (kids_music_service.py:3180-3185). So this column is the titanet row's ONE credible yes and the note says so",
    ),
    _pair(
        'catch_wrong_voice',
        'Catches the wrong voice',
        ['wrong_voice'],
        'wrong_cast',
        ['voice_qc', 'titanet_sung'],
        'voice_qc: |dF0| > 18 % or |dVTL| > 1.0 cm against the cast reference. titanet_sung: cosine to the cast reference below 0.50',
        'the hard case, on purpose: a DIFFERENT cast voice of the same sex and the same age band, same script, same loudness. Every level figure on it is perfect and the age/sex bands do not separate it — only a speaker embedding or a tight F0+VTL band can. A row that catches adult-for-child but not this one gets yes on age_wrong and no here, which is the honest pair of cells',
    ),
    # ── content: CLAP and Whisper decide, the expensive ones last ─────────────────────────
    _pair(
        'catch_semantic',
        'Catches the wrong CONTENT',
        ['semantic'],
        'dog_for_bell',
        ['clap_check'],
        'audio_qc.qc_clap returns ok False: the cosine to the asked caption ("a church bell ringing") falls below threshold=0.6 (audio_qc.py:425)',
        'a dog bark delivered where a church bell was asked for. Both files are library slates whose labels ARE the key, so no ear is needed to verify the fixture. The clean twin is the bell slate against the same caption. Note the live threshold split: 0.6 in audio_qc, 0.45 in the music leg (kids_music_service.py:1774) — the probe runs at 0.6 and records the 0.45 verdict beside it',
    ),
    _pair(
        'catch_key',
        'Catches a wrong key or tempo',
        ['music_key'],
        'wrong_key',
        ['clap_check'],
        'the row reports a key or tempo mismatch against the plan; for clap_check that is the caption cosine to "a song in the key of C at 96 bpm" falling below 0.45 (the music leg\'s threshold, kids_music_service.py:1774)',
        'the clean song resampled by asetrate 1.0595 — exactly one semitone up, tempo dragged with it. NOTHING in the house judges owns a key or tempo estimator, so this column is expected to score no on every row, and that measured no is the reason the column exists: it names a gate we do not have',
    ),
    _pair(
        'catch_lyric',
        'Catches a wrong lyric',
        ['lyrics_j'],
        'wrong_lyric',
        ['audio_qc', 'clap_check'],
        'audio_qc.qc_wpm transcript-to-script match ratio below min_match=0.9 (audio_qc.py:261) with the differing word named; clap_check: caption cosine below threshold',
        'one word of one line swapped for a metrically identical word. A sung line is the hard case for Whisper, so this probe records the transcript verbatim in the trial: a row that fails here because the transcriber could not hear the line at all is a different finding from a row whose comparison was too loose, and the trial text tells them apart',
    ),
    _pair(
        'catch_mispron',
        'Catches a mispronounced name',
        ['mispronounce'],
        'mispron',
        ['audio_qc'],
        'audio_qc.qc_wpm transcript match: the script word "Kattenburg" is absent from the transcript (the match ratio drops by one word on a short line)',
        '"Kattenberg" for "Kattenburg" — a real 1672 Amsterdam island and the exact class of error a Dutch name hits in an English-trained voice. One vowel, one word, in an otherwise perfect take; whether Whisper resolves it at all is itself the measurement',
    ),
    _pair(
        'catch_delivery',
        'Catches a delivery fault',
        ['delivery'],
        'monotone',
        ['audio_qc', 'clap_check'],
        'audio_qc.qc_wpm falls outside (125, 165) WPM (audio_qc.py:258) or the fade/runtime gate reports flat; clap_check: caption cosine to "an expressive dramatic narration" below threshold',
        'a flat monotone read of the same script at the same loudness and the same word count. This is the column where the house has the WEAKEST mechanism: pace is measured, prosody is not. If both rows score no, the cell reads no and the pipeline learns it is shipping delivery on trust',
    ),
]

# Cheap mechanical meters first, so a partial run still fills the level and timing columns;
# the Praat venv and the TitaNet load next; CLAP and Whisper last because they cost the most
# wall clock per pass.
RUN_ORDER = [
    'failsafe',
    'catch_clipping',
    'catch_silence',
    'catch_artefact',
    'refuses',
    'catch_truncation',
    'clean_takes',
    'catch_drift',
    'catch_age',
    'catch_sex',
    'catch_wrong_voice',
    'catch_semantic',
    'catch_key',
    'catch_lyric',
    'catch_mispron',
    'catch_delivery',
]

PROMPT_BANDS = ['Prompt: damage', 'Prompt: clarity needed', 'Prompt: limits', 'Prompt: steering']
HEAR_BANDS = [
    'Hears: Human & movement',
    'Hears: Objects & work',
    'Hears: Nature & weather',
    'Hears: Animals',
    'Hears: Space & ambience',
]

NA_METER_PROMPT = {
    'reason': (
        'a meter takes a file and a threshold, never an instruction. audio_qc, voice_qc and the '
        'TitaNet cosine have no text input at all, so there is no prompt to damage, paraphrase, '
        'shorten or steer — and a prompt column scored on them would be a guess dressed as a cell. '
        'clap_check KEEPS these bands: its caption IS its prompt.'
    ),
    'bands': PROMPT_BANDS,
}
NA_NO_EARS = {
    'reason': (
        'this row produces one number about a voice — a median F0 and vocal tract length, or a speaker '
        'embedding cosine. It encodes no sound class and no quantity, so it cannot hear a footstep, a '
        'gull or three barrels. The rows that can answer these bands are the ones with a caption.'
    ),
    'bands': HEAR_BANDS + ['Counting & quantity'],
}

NA_AUDIO_QC = {
    'music_key': 'audio_qc owns no key or tempo estimator: its gates are loudness, silence map, WPM, runtime, fade and a delegated voice check. There is no figure on this row a key error could move',
    'age_wrong': "audio_qc.qc_voice delegates identity wholesale to voice_qc (audio_qc.py:545), so an age verdict here would be the voice_qc row's cell counted twice under another name",
    'sex_wrong': "audio_qc.qc_voice delegates identity wholesale to voice_qc (audio_qc.py:545), so a sex verdict here would be the voice_qc row's cell counted twice under another name",
    'wrong_voice': 'audio_qc.qc_voice delegates identity wholesale to voice_qc (audio_qc.py:545); the identity claim belongs on the row that computes it, not on the wrapper that calls it',
    'drift_j': 'audio_qc measures whole-file figures (integrated loudness, total words, total runtime); it holds no windowed comparison at all, so a change halfway through cannot register as anything',
    'semantic': 'audio_qc reaches content only through qc_clap, which is the clap_check row measured directly; scoring it here would double-count one detector',
}
NA_VOICE_QC = {
    c: (
        'voice_qc reports a median F0 and a vocal tract length from a Praat analysis in its own venv '
        '(voice_qc.py:42-57). It never looks at sample values, gaps, words or captions, so this class of '
        'fault cannot move either figure — the file it rejects and the file it accepts measure the same'
    )
    for c in [
        'clipping_j',
        'silence_j',
        'truncation',
        'artefact_j',
        'mispronounce',
        'semantic',
        'music_key',
        'lyrics_j',
        'delivery',
    ]
}
NA_CLAP = {
    c: (
        'CLAP scores a caption against audio. It has no sample-level, transcript-level or timing view, so a '
        'clipped sample, a spliced gap, a cut-off word, a click burst or one swapped vowel all leave the '
        'caption cosine where it was — the detector is not blind here, the class is simply not in its output'
    )
    for c in ['clipping_j', 'silence_j', 'truncation', 'artefact_j', 'mispronounce']
}
NA_CLAP.update(
    {
        'age_wrong': 'a zero-shot caption cosine has no calibrated age vocabulary; "a child singing" scores within noise of "a woman singing" on our own material, so any verdict here would be a coin toss reported as a measurement',
        'sex_wrong': 'a zero-shot caption cosine has no calibrated sex vocabulary on our material; the separation that IS measured (TitaNet, cosine 0.27 vs 0.45) belongs on the titanet_sung row',
        'wrong_voice': 'CLAP embeds a sound class, not a person: two cast voices of the same sex and age band reading the same line are the same caption, so the wrong one cannot be distinguished by it',
    }
)
NA_TITANET = {
    c: (
        'a TitaNet-large speaker embedding answers exactly one question — is this the same person. It '
        'carries no level, timing, transcript or caption information, so this class of fault leaves the '
        'cosine unchanged and nothing on this row could report it'
    )
    for c in [
        'clipping_j',
        'silence_j',
        'truncation',
        'artefact_j',
        'mispronounce',
        'semantic',
        'music_key',
        'lyrics_j',
        'delivery',
    ]
}

TEST = {
    'step': 'audio_judges',
    'version': '2026-09-30.1',
    'title': 'Thirteen planted faults and their clean twins, through each gate: recall and false alarm, nothing else',
    'purpose': (
        'Measure whether each audio gate CATCHES a known planted fault and leaves its clean twin alone. One '
        'fault per column, one pair per fault, recall 1.0 and false alarm 0 over 3 repeats. Where the house '
        'owns no mechanism (key, tempo, prosody) the cell is a measured no that names the missing gate.'
    ),
    'include_shared': ['audio', 'judge'],
    'house_standard': HOUSE,
    'run_order': RUN_ORDER,
    'rows': {
        'audio_qc': {
            'transport': 'service',
            'where': 'audio_qc.run_master_gates / run_stem_gates -> qc_lufs, qc_silence_map, qc_wpm, qc_runtime, qc_fade, qc_clap, qc_voice',
            'model': 'audio_qc.py (ffmpeg meters + Whisper on CPU, audio_qc.py:38-40)',
            'na': NA_AUDIO_QC,
            'na_bands': NA_METER_PROMPT,
            'budget': {
                'calls': 60,
                'minutes': 40,
                'gpu_minutes': 0,
                'operator_minutes': 6,
                'note': 'the widest row: 8 pairs plus the 13 clean twins plus refuses and failsafe, and every transcript column costs a Whisper CPU decode at ~50 s — the 40 minutes are almost all decode',
            },
        },
        'voice_qc': {
            'transport': 'service',
            'where': 'voice_qc.gate_voice_identity via audio_qc.qc_voice (audio_qc.py:545), Praat/parselmouth in its own venv as a subprocess',
            'model': 'voice_qc.py (F0 + vocal tract length, calibrated 2026-08-06)',
            'na': NA_VOICE_QC,
            'na_bands': NA_NO_EARS,
            'budget': {
                'calls': 36,
                'minutes': 12,
                'gpu_minutes': 0,
                'operator_minutes': 3,
                'note': '4 identity pairs plus the clean twins plus refuses and failsafe; Praat on a 12 s line is ~2 s, so the 12 minutes are venv startup, not analysis',
            },
        },
        'clap_check': {
            'transport': 'service',
            'where': "audio_qc.qc_clap (audio_qc.py:425, threshold=0.6) and the music leg's call at threshold=0.45 (kids_music_service.py:1774)",
            'model': 'CLAP zero-shot caption scoring, minimum-window figure (audio_qc.py:433)',
            'na': NA_CLAP,
            'budget': {
                'calls': 45,
                'minutes': 25,
                'gpu_minutes': 0,
                'operator_minutes': 3,
                'note': "the only row that keeps the Prompt bands (a caption is a prompt), so it also pays the shared audio bank's 53-label sound pass: ~4 s per label on CPU",
            },
        },
        'titanet_sung': {
            'transport': 'service',
            'where': 'TitaNet-large speaker embeddings, cosine against the cast reference — the sung-stem identity check written up in kids_music_service.py:3180-3185',
            'model': 'NVIDIA TitaNet-large (NeMo), pinned checkpoint',
            'na': NA_TITANET,
            'na_bands': NA_NO_EARS,
            'state_note': (
                'THE SUNG REGISTER IS BIMODAL AND THIS ROW IS NOT RELIABLE ON IT. Measured '
                '2026-09: same caption across songs 0.45, other captions on the same song 0.49, '
                'other captions across songs 0.39 — the paired test separated 1 of 3 '
                '(kids_music_service.py:3180-3185). Male vs female DOES separate at 0.27, so '
                'sex_wrong is the one column this row can answer with a receipt; age_wrong and '
                'wrong_voice on sung material are expected partial at best and the cell must '
                'carry this note beside the number. Speech-register cosines are not affected '
                'and are recorded separately in the trial.'
            ),
            'budget': {
                'calls': 36,
                'minutes': 18,
                'gpu_minutes': 6,
                'operator_minutes': 3,
                'note': 'the ONE row on this sheet that holds the GPU: the TitaNet-large load is ~6 GPU minutes over the run, the rest is CPU cosine arithmetic and file IO',
            },
        },
    },
    'probes': PROBES,
    'derive': {},
    'lookup': {
        'calibrated': {
            'grade': 'receipt',
            'from': (
                'the calibration artefact itself, and the pool it was built on — per row, because the four rows '
                'are not in the same state and a single yes would hide that. voice_qc: YES, with a receipt — '
                'AGE_BANDS and the tolerances F0_TOL_PCT=18 / VTL_TOL_CM=1.0 were set on the 16-voice house seed '
                'pool on 2026-08-06 (voice_qc.py:42-57), artefact at '
                'output/kidsmusic/_voice_build/calibration.json, and the same table carries its own written '
                'caveat that teen_male overlaps adult_female. audio_qc: NO — -14.0 LUFS / -1.0 dBTP is a '
                'PLATFORM delivery spec (audio_qc.py:127) and 125-165 WPM is a house preference; neither was '
                'fitted to our material, so the cell is vendor-grade at best and says so. clap_check: NO — the '
                'detector runs at TWO live thresholds (0.6 audio_qc.py:425, 0.45 kids_music_service.py:1774) '
                'with no document saying which material either was fitted to; two thresholds for one detector '
                'is the proof there is no calibration. titanet_sung: PARTIAL — the 0.50 cosine has a measured '
                'receipt on our own sung stems, and that receipt says it does not work '
                '(kids_music_service.py:3180-3185).'
            ),
            'requires': [
                {
                    'source': 'output/kidsmusic/_voice_build/calibration.json',
                    'url': 'on this box — the voice_qc calibration artefact (present, 3332 bytes)',
                    'pin': 'record its sha256 and mtime with the cell; a threshold whose artefact changed is a different gate',
                },
                {
                    'source': 'voice_qc.py:42-57',
                    'url': 'the AGE_BANDS table and the two tolerance constants in the source',
                    'pin': 'quote the pool size (16 seed voices), the date (2026-08-06) and the written teen_male / adult_female overlap caveat',
                },
                {
                    'source': 'kids_music_service.py:3180-3185',
                    'url': 'the sung-stem TitaNet receipt in the source',
                    'pin': 'quote the four cosine figures and the 1-of-3 paired result verbatim — the receipt is the cell',
                },
            ],
            'note': 'grade receipt, not vendor: every source is OUR OWN artefact or OUR OWN measurement, which is exactly what this column asks for. A vendor number would not answer it',
        },
    },
    'wiring': {
        'blocks_ship': {
            'grade': 'assumed',
            'from': (
                'read off the call sites, not run, and therefore visibly assumed. abel_voice.py:369 reads '
                'enforce = os.environ.get("ZYG_AUDIO_QC_ENFORCE", "1") != "0" and the enforce branches at '
                '379 / 384 / 400 / 405 refuse the mux on a stem-gate fail, an over-runtime, a master-gate fail '
                'and a CLAP bed ok=False (the contract is written out at abel_voice.py:348). '
                'kids_music_service.py:2914 gates the fallback ship on render ok AND _clap ok is True AND mix ok. '
                'audio_qc.run_master_gates (audio_qc.py:578) is the entry point both consult. '
                'THE TWO HOLES, both visible in the code and both recorded in this cell: (1) one environment '
                'variable, ZYG_AUDIO_QC_ENFORCE=0, turns every refusal above into a warning; (2) the CLAP gate '
                'fails OPEN — ok=None never vetoes (audio_qc.py:8-13), so a bed nobody could score ships. '
                'voice_qc blocks only through audio_qc.qc_voice, and titanet_sung blocks NOTHING: it is a '
                'diagnostic written into the manifest, with no branch anywhere refusing a ship on its figure.'
            ),
            'note': 'a wiring cell is assumed by construction; it is here because "which gate blocks what, and what switches it off" is a fact about the code that a probe cannot measure without shipping a bad take on purpose',
        },
    },
    'na': {},
    'fixtures': [
        # ── the clean twins ──────────────────────────────────────────────────────────────
        {
            'path': FX + '/clean/line_adult_male.wav',
            'verified': False,
            'blocks': ['false_alarm_a'],
            'generated': (
                'render capability_tests/fixtures/audio/planted/script_adult_male.txt with the Abel cast voice at '
                'the production settings (abel_voice.py render path, engine chatterbox, CPU), then level it: '
                'ffmpeg -y -i raw.wav -ar 48000 -ac 1 -c:a pcm_s24le t.wav && python3 -c "import audio_mix; '
                "audio_mix.level_to('t.wav','line_adult_male.wav')\" — 12 s, ~150 WPM, one scripted 600 ms "
                'pause, no digits. This file is the clean twin of eight of the thirteen pairs'
            ),
            'how_to_verify': (
                'the operator plays it once against the script and confirms every word is spoken, the only gap '
                'is the scripted one, and the voice is the Abel cast voice. Until then false_alarm_a is '
                'blocked, because a column whose whole claim is "these takes are good" cannot be written '
                'against takes nobody has heard. The catch columns are NOT blocked by this file: a planted '
                'fault that a gate flags is a flag either way'
            ),
        },
        {
            'path': FX + '/clean/line_adult_female.wav',
            'verified': False,
            'blocks': ['sex_wrong'],
            'generated': 'the same script rendered with the female cast voice at the production settings, levelled the same way — the clean twin of the male_for_female pair',
            'how_to_verify': 'the operator confirms it is the female cast voice named in the script header and that the line is complete',
        },
        {
            'path': FX + '/clean/line_child.wav',
            'verified': False,
            'blocks': ['age_wrong'],
            'generated': 'a child-scripted line rendered with the house child voice at the production settings, levelled the same way — the clean twin of the adult_for_child pair',
            'how_to_verify': 'the operator confirms it is the child voice and that voice_qc on it lands inside the child AGE_BAND (f0_min 200 Hz, vtl_max 14.5 cm, voice_qc.py:44-57) — if the clean child take is itself outside the band, the fixture is wrong, not the gate',
        },
        {
            'path': FX + '/clean/line_kattenburg.wav',
            'verified': False,
            'blocks': ['mispronounce'],
            'generated': 'one 6 s line containing the word "Kattenburg" once, rendered with the Abel cast voice, levelled the same way — the clean twin of the mispron pair',
            'how_to_verify': 'BLIND: the operator hears this take and mispron.wav in random order without filenames and must name which one says the island wrong. If the operator cannot hear it, the fixture is too subtle and is replaced, not relabelled',
        },
        {
            'path': FX + '/clean/song_in_key.wav',
            'verified': False,
            'blocks': ['music_key', 'lyrics_j'],
            'generated': 'one 20 s sung section from a house kidsmusic render whose manifest states the key and the tempo (C, 96 bpm), exported at 48 kHz mono 24-bit and levelled with audio_mix.level_to — the clean twin of the wrong_key and wrong_lyric pairs',
            'how_to_verify': 'the operator confirms the manifest key and tempo match what is heard and writes both into the fixture header; the key/tempo claim is the answer key both probes are scored against',
        },
        {
            'path': FX + '/clean/bell_church.wav',
            'verified': True,
            'generated': 'the highest-rated church-bell slate from the house SFX library, trimmed to 6 s, 48 kHz mono 24-bit: ffmpeg -y -i <slate> -t 6 -ar 48000 -ac 1 -c:a pcm_s24le bell_church.wav. Its library label IS the key, so no ear is needed',
        },
        {
            'path': FX + '/script_adult_male.txt',
            'verified': True,
            'generated': 'write by hand: ~30 words of 1672 Dutch-drama narration in English, plain sentences, one deliberate 600 ms pause, no digits (the TTS reads words reliably and digits inconsistently). This text is the transcript key for truncation, mispronounce, lyrics and delivery',
        },
        # ── the planted faults: mechanically checkable, no ear needed ────────────────────
        {
            'path': FX + '/clipped.wav',
            'verified': True,
            'generated': 'ffmpeg -y -i clean/line_adult_male.wav -af "volume=12dB" -ar 48000 -ac 1 -c:a pcm_s16le clipped.wav — +12 dB written to s16 so the clamp produces a run of exactly-full-scale samples',
            'how_to_verify': 'a decode reports samples at >= 1.0 and ffmpeg ebur128 reports a true peak above 0 dBTP; those two numbers ARE the fixture',
        },
        {
            'path': FX + '/dead_air.wav',
            'verified': True,
            'generated': 'ffmpeg -y -i clean/line_adult_male.wav -af "asendcmd=6.0 volume -1 0,volume=1" -ar 48000 -ac 1 out.wav is NOT enough — splice instead: cut the clean line at 6.0 s, insert 4 s of digital silence, concatenate: ffmpeg -y -i clean/line_adult_male.wav -t 6 -c copy a.wav && ffmpeg -y -f lavfi -i anullsrc=r=48000:cl=mono -t 4 -c:a pcm_s24le s.wav && ffmpeg -y -ss 6 -i clean/line_adult_male.wav -c copy b.wav && ffmpeg -y -i "concat:a.wav|s.wav|b.wav" -ar 48000 -ac 1 -c:a pcm_s24le dead_air.wav',
            'how_to_verify': 'ffmpeg silencedetect reports one silence of 4.0 s +-0.05 starting at 6.0 s; that measurement is the fixture',
        },
        {
            'path': FX + '/click_burst.wav',
            'verified': True,
            'generated': 'six 2 ms full-scale clicks at 1.5 s intervals mixed over the clean line: build the click train with ffmpeg -f lavfi -i "sine=frequency=8000:duration=0.002" and adelay per copy, then amix normalize=0 duration=first against clean/line_adult_male.wav, 48 kHz mono 24-bit',
            'how_to_verify': 'the sample index of each click is known by construction and a true-peak measurement finds six transients at those indices',
        },
        {
            'path': FX + '/wrong_key.wav',
            'verified': True,
            'generated': 'ffmpeg -y -i clean/song_in_key.wav -af "asetrate=48000*1.0595,aresample=48000" -ar 48000 -ac 1 -c:a pcm_s24le wrong_key.wav — exactly one semitone up, tempo dragged with it, which is the fault a mis-set render actually makes',
            'how_to_verify': 'the pitch ratio is 2^(1/12) by construction and the duration shortens by the same factor; both are measurable without an ear',
        },
        {
            'path': FX + '/dog_for_bell.wav',
            'verified': True,
            'generated': 'the highest-rated dog-bark slate from the house SFX library, trimmed to 6 s and levelled to match bell_church.wav, 48 kHz mono 24-bit. The caption asked of both files is the same: "a church bell ringing"',
            'how_to_verify': 'the library label is the key; confirm the slate id written into the fixture header matches the library entry',
        },
        # ── the planted faults that need an ear before their column may be written ───────
        {
            'path': FX + '/truncated.wav',
            'verified': False,
            'blocks': ['truncation'],
            'generated': 'cut the clean line 120 ms into the first syllable of its LAST word, then re-level so loudness is unchanged: ffmpeg -y -i clean/line_adult_male.wav -t <t_last_word + 0.12> -ar 48000 -ac 1 -c:a pcm_s24le t.wav then audio_mix.level_to(t.wav, truncated.wav)',
            'how_to_verify': 'the operator listens once and confirms the last word is audibly cut off mid-syllable, and writes the truncated word into the fixture header — the transcript key depends on knowing exactly which word went',
        },
        {
            'path': FX + '/mispron.wav',
            'verified': False,
            'blocks': ['mispronounce'],
            'generated': 'render the same 6 s line with "Kattenburg" respelled as "Kattenberg" in the input text, same voice, same settings, then level to match clean/line_kattenburg.wav — one vowel different, everything else identical',
            'how_to_verify': 'BLIND: random order against the clean twin, no filenames, the operator must name the one that says the island wrong. If it cannot be heard, the fixture is replaced',
        },
        {
            'path': FX + '/drift.wav',
            'verified': False,
            'blocks': ['drift_j'],
            'generated': 'render the first half of the script with the Abel cast voice and the second half with a different cast voice of the same sex and age band, level each to -14 LUFS, then concatenate at exactly 50 % with a 10 ms crossfade so no seam click exists: ffmpeg -y -i h1.wav -i h2.wav -filter_complex acrossfade=d=0.01 -ar 48000 -ac 1 -c:a pcm_s24le drift.wav',
            'how_to_verify': 'the operator listens once and confirms the speaker audibly changes at the halfway point and that no click is audible at the join — a click would let a level gate "catch" the drift for the wrong reason',
        },
        {
            'path': FX + '/monotone.wav',
            'verified': False,
            'blocks': ['delivery'],
            'generated': 'render the same script with the same voice at the flattest available expressiveness setting, matched to the clean take on word count and on WPM (within 5), then levelled to the same -14 LUFS — only the prosody differs',
            'how_to_verify': 'BLIND: random order against the clean take, the operator must name the flat one. Also confirm mechanically that both land inside 125-165 WPM, so pace cannot be what a gate detects',
        },
        {
            'path': FX + '/wrong_lyric.wav',
            'verified': False,
            'blocks': ['lyrics_j'],
            'generated': 'rerender the clean sung section with ONE word of one line swapped for a metrically identical word (same syllable count, same stress), same voice, same key, same tempo, levelled the same way',
            'how_to_verify': 'the operator confirms by ear which word changed and writes both words into the fixture header; without that pair the transcript comparison has no key',
        },
        {
            'path': FX + '/adult_for_child.wav',
            'verified': False,
            'blocks': ['age_wrong'],
            'generated': 'render the CHILD-scripted line with the adult male cast voice at the production settings and level it to match clean/line_child.wav — same words, same loudness, wrong age',
            'how_to_verify': "the operator confirms it is audibly an adult reading a child's line, and that voice_qc on the clean child twin lands inside the child band",
        },
        {
            'path': FX + '/male_for_female.wav',
            'verified': False,
            'blocks': ['sex_wrong'],
            'generated': 'render the female-scripted line with the male cast voice at the production settings and level it to match clean/line_adult_female.wav',
            'how_to_verify': 'the operator confirms the sex is audibly wrong; this is the easiest of the identity fixtures and is the one the titanet_sung row is expected to pass',
        },
        {
            'path': FX + '/wrong_cast.wav',
            'verified': False,
            'blocks': ['wrong_voice'],
            'generated': 'render the SAME script with a DIFFERENT cast voice of the same sex and the same age band, same settings, then level with audio_mix.level_to to -14 LUFS — identical words, identical loudness, wrong person',
            'how_to_verify': 'BLIND: the operator hears this and clean/line_adult_male.wav in random order without filenames and must name which is not the cast voice. If the operator cannot hear it either, the fixture is too subtle and is REPLACED — not relabelled, and not scored',
        },
        {
            'path': FX + '/cast_reference.wav',
            'verified': False,
            'blocks': ['wrong_voice', 'drift_j'],
            'generated': 'the cast identity reference for the Abel voice, the same file the production gates use (ABEL_IDENTITY_REF, abel_voice.py:258-262), copied here at 48 kHz mono 24-bit so the fixture set is self-contained',
            'how_to_verify': 'confirm the copy holds the same audio as the production reference and that it is the voice the script header names',
        },
        # ── the unmeasurable inputs ──────────────────────────────────────────────────────
        {
            'path': FX + '/refuse/too_short_0p3s.wav',
            'verified': True,
            'generated': 'ffmpeg -y -i clean/line_adult_male.wav -ss 2.0 -t 0.3 -ar 48000 -ac 1 -c:a pcm_s24le refuse/too_short_0p3s.wav — 300 ms, below every window these rows use',
        },
        {
            'path': FX + '/refuse/digital_silence_2s.wav',
            'verified': True,
            'generated': 'ffmpeg -y -f lavfi -i anullsrc=r=48000:cl=mono -t 2 -c:a pcm_s24le refuse/digital_silence_2s.wav — ebur128 reports about -70 LUFS, which is the unreachable-target case audio_mix documents as _SILENT_LUFS = -69.0 (audio_mix.py:528)',
        },
        {
            'path': FX + '/refuse/broken_header.wav',
            'verified': True,
            'generated': (
                'ffmpeg -y -f lavfi -i "sine=frequency=440:duration=0.2" -ar 48000 -ac 1 -c:a pcm_s16le tmp.wav '
                'then patch the two length fields so the header lies: python3 -c "import struct; b=bytearray('
                "open('tmp.wav','rb').read()); n=48000*2*40; b[4:8]=struct.pack('<I', n+36); "
                "b[40:44]=struct.pack('<I', n); open('refuse/broken_header.wav','wb').write(b)\" — a WAV "
                'claiming 40 s that holds 0.2 s'
            ),
            'how_to_verify': 'ffprobe reports 40 s and the decoder yields 0.2 s; that disagreement IS the fixture, so no ear is needed',
        },
    ],
    'budget': {
        'calls': 93,
        'tokens_in': 0,
        'tokens_out': 0,
        'tokens_note': 'every row is a meter, a Praat analysis, a caption cosine or a speaker embedding; no language model is called anywhere on this step, so no tokens are spent',
        'minutes': 34,
        'gpu_minutes': 2,
        'operator_minutes': 8,
        'note': (
            'Per row: 13 planted pairs x 2 files x 3 repeats = 78 gate passes, of which the 39 clean-twin passes '
            'ALSO score false_alarm_a (shared, not counted twice); plus refuses 2 inputs x 3 = 6; plus failsafe '
            '4 broken inputs x 3 = 12. Rounded to 93 calls. Wall clock is decided by WHAT the row is: an ffmpeg '
            'meter pass is ~3 s, a Praat pass in its own venv is ~2 s plus ~4 s startup, a CLAP pass is ~8 s on '
            'CPU, a TitaNet cosine is ~1 s after a ~90 s model load, and a Whisper CPU decode of a 12 s line is '
            '~50 s and dominates every transcript column (truncation, mispronounce, lyrics_j, delivery). '
            'Row overrides carry the real figures: audio_qc 40 min, clap_check 25 min, titanet_sung 18 min '
            "(6 of them GPU), voice_qc 12 min. Plus the SHARED BANKS' share for this step: the audio bank's 53 "
            'SOUND_LABELS are asked of the rows that can hear, which after na_bands is clap_check ALONE — one '
            'CLAP pass per label at ~8 s = ~7 min, and the seven acap_* capacity ladders ~5 min; the judge bank '
            'adds its universal probes over the same fixtures at no new render cost. GPU: 2 minutes at test '
            'level and 6 on the titanet_sung row, which is the only row that loads a checkpoint onto the card — '
            'audio_qc pins Whisper to CPU (audio_qc.py:38-40), so this sheet can be scheduled while a GPU render '
            'owns the card. Operator: 3 decisions for refuses, 4 for failsafe, and up to 6 blind questions on '
            'clean takes a row flagged = ~13 decisions at ~30 s = ~7 min, called 8. No claude_cli or '
            'anthropic_api row exists on this step, so nothing here spends the shared Claude week. ONE-TIME '
            'operator cost OUTSIDE this budget: verifying the fourteen fixtures that need an ear (~45 min), '
            'until which truncation, mispronounce, drift, delivery, lyrics_j, music_key, age_wrong, sex_wrong, '
            'wrong_voice and false_alarm_a are BLOCKED and ship untested.'
        ),
    },
    'notes': [
        'Recall without false alarm is meaningless, so the thirteen clean twins are scored as their own column off the same passes. A row cannot reach yes on a catch column by flagging everything.',
        'music_key is expected to score no on every row. The house owns no key or tempo estimator, and the point of the column is to say that out loud in a cell instead of leaving it blank.',
        'delivery is the weakest column on the sheet: pace is measured, prosody is not. If both eligible rows score no, the pipeline is shipping delivery on trust and the sheet now records it.',
        'titanet_sung is kept because it is wired, not because it works. Its state_note carries the measured bimodality receipt, and every column it cannot answer is na with the reason rather than a hopeful partial.',
        'blocks_ship is the only assumed cell here and it is the most important one: it names ZYG_AUDIO_QC_ENFORCE=0 and the fail-open CLAP gate, the two ways every measured yes above stops mattering.',
        "recall 1.0 / false alarm 0 over 3 repeats is this test's bar, not the pipeline's. If the house adopts a looser one, change it in HOUSE and bump the version — a different threshold is a different test.",
    ],
}
