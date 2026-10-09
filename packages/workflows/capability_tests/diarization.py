# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Default test — Speaker diarization & identity (diarization). 2026-09-30.

Question the sheet asks: "Can we tell who spoke when, and whether two recordings are the same
person?" Its recorded verdict is a measured negative worth keeping: *speaker identity works on
SPEECH and fails on SINGING — TitaNet could not separate voices on sung stems, which is why the
kids-music leg has no per-song identity gate* (receipt: output/kidsmusic/_voice_build/
calibration.json). This test is built so that that negative is reproducible rather than
remembered, and so that the threshold behind it is a lookup with a receipt instead of a number
somebody once typed.

Shape of the test. The sheet holds TWO KINDS of row and the difference decides which checks a
row is even asked:

    row_kind 'turns'      the row returns who spoke when — a turn list (sortformer)
    row_kind 'embedding'  the row returns one vector per clip and nothing else (titanet)
    row_kind 'turns+embedding'  both (pyannote 3.1 with return_embeddings=True)

Every check carries `row_kind`; a row runs a check when its own kind string contains that
value. A check a row's kind does not name is not run and never scores a `no` — the columns a
whole row cannot answer are `na` on that row instead, with the reason written out. So `der`,
`speech`, `overlap`, `short_turn` and `boundaries` are na on the embedding row, and
`same_person`, `synthetic` and `enrol` are na on the turn-only row.

There is no prompt anywhere on this step: all three rows take a wav and return turns or
vectors. The four Prompt bands are therefore `na_bands` with one written reason, including the
three judging-prompt columns the audio bank owns for audio_judges — you cannot reword,
lead or yes-bias a question you never asked.

What is blocked and why. Everything that needs an exact turn TIME is blocked until the
operator marks the turns: der, speech, boundaries, short_turn, overlap and long_file. Everything
that needs only the ROSTER — who is in the file at all — is verified by construction, because
the fixtures are synthesised from named voices and the recipe fixes the answer; that is stated
on each fixture rather than assumed. No file is created here: every fixture that does not exist
carries the exact command or recipe that makes it.
"""

from __future__ import annotations

import os

from zyg_workflows.paths import ZYG_MODELS_DIR

#: The speaker-verification worker's own venv; $ZYG_SPEAKER_VERIFY_VENV overrides it.
SPEAKER_VERIFY_VENV = os.environ.get('ZYG_SPEAKER_VERIFY_VENV') or str(ZYG_MODELS_DIR / 'speaker_verify' / '.venv')

# ── check kinds this module adds (the runner is a table of these) ──────────────────────
CHECK_KINDS = {
    'der_max': "diarization error rate (missed speech + false alarm + confusion, over total speech, NIST scoring with a `collar` of 0.25 s and overlap INCLUDED) against the fixture's verified turn list <= `max`; scored over the span named by `region` when one is given",
    'der_delta_max': 'DER over the span named by `window` minus DER over the span named by `baseline`, same fixture, <= `max` (drift over a long file)',
    'speaker_count_equals': 'the number of distinct speaker labels the row returns == `n` exactly; a label holding less than `min_speech_s` seconds of speech in total is dropped before counting, and that threshold is part of the test, not the runner',
    'overlap_labelled_min': "share of the fixture's overlap seconds that the row labels with BOTH speakers >= `min`; a row that returns one speaker through the overlap scores 0 here even when its DER is good",
    'short_turn_found': 'the one-word interjection at `at` seconds is returned as its OWN turn, attributed to the interjecting speaker, with its start within `tolerance_ms` of the verified onset; a turn swallowed into a neighbour is a fail',
    'boundary_abs_ms': 'for the verified turn edges, |reported edge - truth| <= `max` ms for >= `share` of them',
    'speaker_pair_decision': 'with the threshold from the `threshold` lookup, cosine of the two embeddings is >= it for EVERY same-donor pair in `same` and < it for EVERY different-donor pair in `different`; the raw cosines go on the trial so the margin is visible and not just the verdict',
    'enrol_seconds_min': 'the SHORTEST rung in `rungs` (seconds of enrolment audio) at which speaker_pair_decision still holds for every pair; the column reports that number of seconds, and `no` means it failed at every rung',
    'abstains': 'on the input named by `on` the row returns an explicit cannot-measure signal (an insufficient-audio error, a null result, or a confidence the caller can gate on) and NOT a speaker label or a similarity number; a returned verdict is a fail however plausible it is',
    'turns_cover_min': "the reported turns span >= `min` of the fixture's total speech seconds — a dropped tail is a fail even when the turns that came back are right",
}

SUBS = 'capability_tests/fixtures/subtitles'
SUBS_MANIFEST = SUBS + '/MANIFEST.json'
NARRATION = SUBS + '/narration.wav'
FX = 'capability_tests/fixtures/diarization'
MANIFEST = FX + '/MANIFEST.json'

TWO = FX + '/two_speakers.wav'
FOUR = FX + '/four_speakers.wav'
OVERLAP = FX + '/overlap_two.wav'
SUNG = FX + '/two_singers.wav'
CHILD = FX + '/child_adult.wav'
SHORT = FX + '/half_second.wav'
LONG = FX + '/long_60min.wav'
PAIRS = FX + '/identity_pairs.json'

ROW_KINDS = {
    'sortformer': 'turns',
    'titanet': 'embedding',
    'pyannote': 'turns+embedding',
}
ROW_KIND_RULE = (
    'every check carries `row_kind`. A row runs the check when ROW_KINDS[row] '
    'CONTAINS that string, so "turns+embedding" runs both and "embedding" runs only '
    "the embedding half. A check the row's kind does not name is NOT run and is NOT "
    'scored — where that leaves a column with no evidence at all for a row, the row '
    'carries an `na` for it with the reason. This is the same idea as the audio '
    "bank's `applies_to` on a check, keyed on the row instead of on the medium, "
    'because this one sheet holds a diarizer and an embedding model side by side.'
)

COND = {
    'repeats': 3,
    'seed': 11,
    'note': 'three runs of the same audio. Sortformer and pyannote are neural and clustered, so their labels can move between runs; the embedding row is expected to be deterministic and a run that is not will show it',
}

DER_RULE = (
    'NIST md-eval conventions, collar 0.25 s, OVERLAP INCLUDED (not forgiven). Excluding '
    'overlap is the common way to publish a flattering DER and it would hide exactly the '
    'failure the overlap column exists for. The reference is the verified turn list in '
    f'{MANIFEST}; scoring is over the whole file unless a probe names a `region`.'
)

ALL = ['sortformer', 'titanet', 'pyannote']
TURNS = ['sortformer', 'pyannote']
EMB = ['titanet', 'pyannote']


def _p(pid, title, feeds, checks, audio, rows=None, **kw):
    p = {
        'id': pid,
        'title': title,
        'feeds': list(feeds),
        'inputs': {'audio': audio, 'fixture': MANIFEST, 'prompt': None},
        'conditions': dict(COND),
        'checks': list(checks),
        'grade': 'measured',
        'rows': list(rows or ALL),
    }
    p.update(kw)
    return p


PROBES = [
    # ── who spoke when ────────────────────────────────────────────────────────────────
    _p(
        'der',
        'Diarization error rate',
        ['der'],
        [{'check': 'der_max', 'max': 0.15, 'row_kind': 'turns'}],
        TWO,
        TURNS,
        state_note='the headline number, on the two-speaker reference fixture. yes at DER <= 0.15, partial <= 0.25, no above. Overlap is included in the score, so this number is comparable with nothing published by a vendor — it is ours',
        der_rule=DER_RULE,
    ),
    _p(
        'speech',
        'Separates speakers on speech',
        ['speech'],
        [
            {'check': 'der_max', 'max': 0.20, 'row_kind': 'turns'},
            {'check': 'speaker_count_equals', 'n': 3, 'min_speech_s': 2.0, 'row_kind': 'turns'},
            {
                'check': 'speaker_pair_decision',
                'same': ['cornelis_a/cornelis_b'],
                'different': ['cornelis_a/anna_a'],
                'row_kind': 'embedding',
            },
        ],
        NARRATION,
        ALL,
        state_note=(
            'the three-speaker house narration (NARRATOR English, CORNELIS and ANNA Dutch) — '
            'harder than the reference fixture because one speaker switches language and the '
            'bell and the dog sit between turns. 0.20 rather than 0.15 is the price of the '
            'third speaker and of the two SFX segments, and the gap to `der` is informative. '
            'For the embedding row the same column is the clean-speech pair decision on cuts '
            'of this file, which is what "separates speakers on speech" means for a vector.'
        ),
    ),
    _p(
        'sung',
        'Separates singers on sung stems',
        ['sung'],
        [
            {'check': 'der_max', 'max': 0.25, 'row_kind': 'turns'},
            {
                'check': 'speaker_pair_decision',
                'same': ['singer_a_v1/singer_a_v2'],
                'different': ['singer_a_v1/singer_b_v1'],
                'row_kind': 'embedding',
            },
        ],
        SUNG,
        ALL,
        state_note=(
            "THE SHEET'S RECORDED NEGATIVE, made reproducible: TitaNet could not separate "
            'voices on sung stems, and that is why the kids-music leg has no per-song '
            'identity gate. The expected result on the embedding row is `no`, and the test '
            'exists to confirm it is still `no` and to say by how much — the cosines go on '
            'the trial, so a future model that fixes this is visible as a margin and not as '
            "somebody's impression. A test whose expected answer is a failure is still a "
            'test; deleting it would turn a measurement back into a memory.'
        ),
    ),
    _p(
        'count',
        'Gets the number of speakers right',
        ['count'],
        [
            {'check': 'speaker_count_equals', 'n': 2, 'min_speech_s': 2.0, 'on': TWO, 'row_kind': 'turns'},
            {'check': 'speaker_count_equals', 'n': 3, 'min_speech_s': 2.0, 'on': NARRATION, 'row_kind': 'turns'},
            {'check': 'speaker_count_equals', 'n': 4, 'min_speech_s': 2.0, 'on': FOUR, 'row_kind': 'turns'},
        ],
        TWO,
        TURNS,
        state_note=(
            'three fixtures, three exact answers: 2, 3 and 4. All three right -> yes; two -> '
            'partial; fewer -> no. The `min_speech_s` floor of 2 s is in the test because a '
            'clusterer that returns a fifth speaker holding 0.3 s of a door hinge has not '
            'found five speakers, and a runner must not be left to decide that. The rosters '
            "are fixed by the fixtures' own recipes (named TTS voices), so this column is "
            'NOT blocked by the unverified turn times.'
        ),
    ),
    _p(
        'overlap',
        'Handles overlapping speech',
        ['overlap'],
        [
            {'check': 'der_max', 'max': 0.30, 'region': 'overlap', 'row_kind': 'turns'},
            {'check': 'overlap_labelled_min', 'min': 0.5, 'row_kind': 'turns'},
        ],
        OVERLAP,
        TURNS,
        state_note=(
            'the two Dutch lines mixed with a 2 s offset, ~3 s of genuine overlap. Two '
            'different failures: a bad DER through the overlap, and returning a single '
            'speaker through it (pyannote 3.1 does emit overlap; a single-label pipeline '
            'scores 0 on the second check and `partial` at best on the column). Half the '
            'overlap seconds correctly double-labelled is the yes threshold, which is low '
            'on purpose — overlap detection at 50 % is already useful and demanding 90 % '
            'would report `no` for every row on the shelf.'
        ),
    ),
    _p(
        'short_turn',
        'Catches a one-word turn',
        ['short_turn'],
        [{'check': 'short_turn_found', 'at': 'MANIFEST.short_turn_t', 'tolerance_ms': 300, 'row_kind': 'turns'}],
        TWO,
        TURNS,
        state_note='the planted one-word interjection ("Joost!") inside the other speaker\'s line. A turn list that swallows it into the neighbouring turn is the normal behaviour and scores `no`; this column exists so that behaviour is on the sheet instead of being discovered in an edit',
    ),
    _p(
        'boundaries',
        'Turn boundaries are tight',
        ['boundaries'],
        [{'check': 'boundary_abs_ms', 'max': 250, 'share': 0.9, 'row_kind': 'turns'}],
        TWO,
        TURNS,
        state_note='250 ms for 90 % of the verified edges. Looser than the subtitles standard (100 ms on a word onset) because a turn edge sits in a silence and has a real ambiguity a word onset does not; the collar in DER_RULE is the same 0.25 s, so the two numbers agree',
    ),
    # ── identity ──────────────────────────────────────────────────────────────────────
    _p(
        'same_person',
        'Says two files are the same person',
        ['same_person'],
        [
            {
                'check': 'speaker_pair_decision',
                'same': ['cornelis_a/cornelis_b', 'anna_a/anna_b'],
                'different': ['cornelis_a/anna_a', 'cornelis_b/anna_b'],
                'row_kind': 'embedding',
            }
        ],
        PAIRS,
        EMB,
        state_note=(
            'two files per donor and two donors: two same-pairs must land above the '
            'threshold and two different-pairs below it. All four right -> yes; three -> '
            'partial; fewer -> no. The threshold is NOT a free parameter of this probe — it '
            'is the `threshold` lookup, so a row cannot be made to pass by moving it.'
        ),
    ),
    _p(
        'child_adult',
        'Works on children',
        ['child_adult'],
        [
            {'check': 'der_max', 'max': 0.20, 'row_kind': 'turns'},
            {
                'check': 'speaker_pair_decision',
                'same': ['abel_a/abel_b'],
                'different': ['abel_a/cornelis_a'],
                'row_kind': 'embedding',
            },
        ],
        CHILD,
        ALL,
        state_note=(
            'Abel (child) and Cornelis (adult) in one recording. For a turn row the question '
            'is whether the child is separated from the adult; for an embedding row it is '
            'whether two takes of the child land on the same person while the child and the '
            'adult do not. Both are needed: a model can diarize a child correctly and still '
            'fail to recognise her across files.'
        ),
    ),
    _p(
        'synthetic',
        'Works on synthesised voices',
        ['synthetic'],
        [
            {
                'check': 'speaker_pair_decision',
                'same': ['tts_v1_take1/tts_v1_take2'],
                'different': ['tts_v1_take1/tts_v2_take1'],
                'row_kind': 'embedding',
            }
        ],
        PAIRS,
        EMB,
        state_note=(
            'everything the house makes is synthesised, so this is not a curiosity: two takes '
            'of ONE TTS voice must be the same person and two different TTS voices must not. '
            'A model that collapses all synthetic voices onto one embedding would pass '
            'same_person on donors and be useless to us, and only this column would catch it.'
        ),
    ),
    _p(
        'enrol',
        'Enrols a new speaker cheaply',
        ['enrol'],
        [
            {
                'check': 'enrol_seconds_min',
                'rungs': [3, 5, 10],
                'same': ['cornelis_a/cornelis_b'],
                'different': ['cornelis_a/anna_a'],
                'row_kind': 'embedding',
            }
        ],
        PAIRS,
        EMB,
        state_note=(
            "a LADDER whose answer is a COUNT, like the bank's capacity columns: the column "
            'reports the shortest rung in seconds at which the pair decision still holds. '
            '3 s -> yes, 5 s -> partial, 10 s -> partial, failing at 10 s -> no. The rungs '
            'are cut from the HEAD of each enrolment file so the cut is reproducible, and '
            "the 3 s rung matches speaker_verify_worker.py's own documented figure (~150 ms "
            'per embedding of a 3 s clip), which is what the house already assumes.'
        ),
    ),
    _p(
        'refuses',
        'Refuses when it cannot measure',
        ['refuses'],
        [
            {'check': 'abstains', 'on': SHORT, 'row_kind': 'turns'},
            {'check': 'abstains', 'on': SHORT, 'row_kind': 'embedding'},
        ],
        SHORT,
        ALL,
        state_note=(
            'a 0.5 s clip. The right answer is "cannot measure"; a speaker label or a '
            'similarity number computed from half a second is a guess with a decimal point '
            'on it. This is the column that decides whether any of these rows may stand in '
            'front of a delivery: a check that cannot measure must not ship. Note that both '
            'row kinds are asked, because both can guess.'
        ),
    ),
    _p(
        'long_file',
        'Handles an hour in one pass',
        ['long_file'],
        [
            {'check': 'turns_cover_min', 'min': 0.95, 'row_kind': 'turns'},
            {
                'check': 'der_delta_max',
                'max': 0.05,
                'window': 'last 5 min',
                'baseline': 'first 5 min',
                'row_kind': 'turns',
            },
        ],
        LONG,
        TURNS,
        conditions={
            'repeats': 1,
            'seed': 11,
            'note': 'ONE repeat: an hour of audio per repeat is the whole GPU budget of this test, and the question (does it finish, does the clustering drift) is answered by one pass',
        },
        state_note=(
            'twenty copies of the two-speaker fixture concatenated. Two failures are being '
            'looked for: a row that returns turns for the first ten minutes and stops '
            '(turns_cover_min) and a row whose clustering decays as the number of segments '
            'grows, typically by splitting one speaker into several (der_delta_max). Because '
            'every copy is the same audio, the last five minutes and the first five have the '
            'SAME reference, so the delta is drift and nothing else. A row that returns 40 '
            'speakers for two people fails der_delta_max, which is the intended catch.'
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
                'path': 'output/capabilities/failsafe/partial.json',
                'note': 'a half-written result left behind is a fail',
            },
        ],
        'capability_tests/fixtures/audio/judge/truncated.wav',
        ALL,
        conditions={
            'repeats': 3,
            'seed': 11,
            'note': 'three broken calls, one each; nothing about a broken input is worth averaging',
        },
        inputs={
            'task': (
                'call the row on a DELIBERATELY broken input three ways, exactly as the audio '
                "bank's u_failsafe does, with the audio substituted for the prompt because no "
                'row on this step has one: (1) audio = '
                'capability_tests/fixtures/audio/judge/truncated.wav (a WAV whose header claims '
                '40 s and holds 0.2 s of data); (2) audio = a zero-byte file with a .wav name; '
                '(3) audio = capability_tests/fixtures/audio/judge/silence.wav (3 s of digital '
                'silence, no speech to cluster at all)'
            ),
            'audio': 'capability_tests/fixtures/audio/judge/truncated.wav',
            'fixture': MANIFEST,
            'prompt': None,
        },
        state_note=(
            'THIS PROBE IS A LOCAL COPY of audio_shared.u_failsafe, substance unchanged: the '
            'bank carries its fixed input under `inputs.command`, which the step validator '
            'does not count as a fixed input, so a step that merges the bank fails `check` on '
            "the bank's own probe. Owning the column here keeps the test identical and "
            'leaves the bank untouched; when the bank moves that string to `inputs.task`, '
            'delete this probe and the shared version comes back by itself. yes = all three '
            'calls returned or raised something the caller can catch, the process is still up '
            'and the VRAM is released within 30 s. no = any hang past 120 s, any crash of the '
            'host process, any leaked allocation, or a speaker label invented for the silent '
            'file (which `refuses` measures on purpose and this probe also refuses to excuse). '
            'The titanet row runs in its own venv as a subprocess, so "the process" here is '
            "the WORKER, and the caller surviving the worker's death is the thing measured."
        ),
    ),
]

# ── whole bands no row on this step can answer ────────────────────────────────────────
NA_BANDS = {
    'reason': (
        'no row on this step takes a prompt: all three are handed a wav and return a turn '
        'list or a 192-d vector, and there is no text field anywhere on the call. That '
        'covers the three judging-prompt columns the audio bank owns for audio_judges too '
        '(pd_question_wording, pd_leading, pd_yes_bias) — a diarizer is not a model you ask '
        'a question of, so there is no wording to reword, no question to lead and no yes to '
        'be biased towards. The one question in these bands that does have an audio answer '
        'here — whether the row abstains instead of guessing — is measured by the `refuses` '
        'probe on a 0.5 s clip, and answering it a second time under pd_abstain would be two '
        'dispositions on one piece of evidence.'
    ),
    'bands': ['Prompt: damage', 'Prompt: clarity needed', 'Prompt: limits', 'Prompt: steering'],
}

NA_SORTFORMER = {
    'same_person': 'Sortformer labels speakers WITHIN one recording; speaker 1 of file A and '
    'speaker 1 of file B are unrelated labels, so there is no cross-file identity '
    'decision to measure. The column belongs to the embedding rows.',
    'threshold': 'a turn-only row has no similarity score and therefore no threshold to calibrate. '
    "The lookup on this column is about the embedding rows' threshold, and claiming "
    "it for this row would be borrowing another row's receipt.",
    'synthetic': 'this column asks whether one voice is RECOGNISED across takes, which needs a '
    'cross-file embedding. Sortformer has none. Whether it diarizes synthesised '
    'voices at all is answered by `speech` and `count`, whose fixtures are entirely '
    'TTS — so the synthetic case is covered, just not by this column.',
    'enrol': 'there is nothing to enrol into: the model clusters one file and forgets it. An '
    'enrolment ladder would be measuring a store this row does not have.',
}

NA_TITANET = {
    'der': 'an ECAPA embedding of a clip is one 192-d vector, not a turn list: there is no '
    'who-spoke-when output to score a diarization error rate against. This row answers the '
    'identity half of the sheet and the diarizers answer this half.',
    'speech': 'covered for this row by the pair decision inside the `speech` probe (the embedding '
    'half); the DER half of that probe is not run here for the same reason as `der`.',
    'overlap': 'an embedding of a window containing two voices is one vector that is neither '
    'speaker; the row has no way to say "both", so there is nothing to score. What the '
    'overlap costs this row shows up as a failed pair decision, not as a number here.',
    'short_turn': 'finding a one-word turn requires segmentation. This row is handed the clip it '
    'is to embed; it does not choose the boundaries and cannot find a turn.',
    'boundaries': 'same reason: the row does not produce turn edges, so there are no edges to be '
    'tight. The caller chooses the windows.',
    'count': 'the row returns one vector per call and never a speaker count. Counting by '
    "clustering a file's windows with this row's embeddings would be measuring a "
    'clusterer we wrote, not this row.',
    'long_file': 'an hour in one pass is a question about a pipeline that must hold state across a '
    'long file. This row embeds a clip of a few seconds in ~150 ms and is called once '
    "per clip by design; the honest statement is that the hour is the caller's "
    'problem, and that is what this na says.',
}

TEST = {
    'step': 'diarization',
    'version': '2026-09-30.1',
    'title': 'Verified turns on synthesised fixtures, and one threshold with a receipt',
    'purpose': (
        "Make the sheet's two claims reproducible: that we can tell who spoke when (DER, "
        'counts, boundaries, overlap, a one-word turn) and that two recordings are the same '
        'person (pairs of donors, a child, TTS voices, an enrolment ladder) — and keep the '
        'measured negative that identity fails on singing as a running test rather than a '
        'remembered verdict.'
    ),
    'include_shared': ['audio', 'judge'],
    'row_kinds': ROW_KINDS,
    'row_kind_rule': ROW_KIND_RULE,
    'der_rule': DER_RULE,
    'rows': {
        'sortformer': {
            'transport': 'service',
            'where': 'the diarize_sortformer worker, called on the fixture path',
            'model': 'NVIDIA Sortformer end-to-end diarization (4-speaker), own venv, GPU',
            'na': NA_SORTFORMER,
        },
        'titanet': {
            'transport': 'service',
            'where': 'speaker_verify_worker.py, op "embed" on a wav path (JSON lines on stdin/stdout)',
            'model': f'speechbrain/spkrec-ecapa-voxceleb, 192-d, CPU, own venv ({SPEAKER_VERIFY_VENV})',
            'na': NA_TITANET,
            'budget': {'calls': 34, 'minutes': 4, 'gpu_minutes': 0},
        },
        'pyannote': {
            'transport': 'service',
            'where': 'pyannote.audio Pipeline("pyannote/speaker-diarization-3.1"), called with return_embeddings=True',
            'model': 'pyannote speaker-diarization-3.1 (segmentation-3.0 + wespeaker embeddings)',
        },
    },
    'probes': PROBES,
    'derive': {},
    'lookup': {
        'threshold': {
            'grade': 'receipt',
            'source': 'output/kidsmusic/_voice_build/calibration.json — the house cosine threshold, '
            "set on OUR material and not on the paper's: the same file is the sheet's "
            'recorded source for the sung-stem negative.',
            'requires': [
                'output/kidsmusic/_voice_build/calibration.json — the threshold value and '
                'the date and material it was set on, read off the file and quoted in the '
                'cell (not summarised)',
                'speaker_verify_worker.py — the embedding that threshold belongs to '
                '(speechbrain/spkrec-ecapa-voxceleb, 192-d), so a threshold is never '
                'carried across to a different embedding space',
            ],
            'note': (
                'the column asks "its threshold is calibrated HERE — on our material, not the '
                'paper\'s", so the honest disposition is a lookup with the calibration file as '
                'its receipt, not a probe. Every speaker_pair_decision check in this test takes '
                'its threshold from this cell, which is why moving the number is visible as a '
                'new test hash and cannot be done quietly to make a row pass. If the file no '
                'longer holds a threshold for the installed embedding, the cell is `untested` '
                'with that as the reason — a threshold we cannot point at is an opinion.'
            ),
        },
        'licence': {
            'grade': 'receipt',
            'source': "the LICENSE file or model card shipped with each row's weights, revision recorded",
            'requires': [
                'pyannote.audio — MIT for the CODE, but the segmentation-3.0 and '
                'speaker-diarization-3.1 WEIGHTS are gated on Hugging Face behind a user '
                'agreement that must be accepted per account before the pipeline will '
                'load. The cell must state BOTH, because "MIT" alone is the wrong answer '
                'for this row and the one a reader would assume.',
                'NVIDIA Sortformer — the model card on its Hugging Face page, for the '
                'commercial-use clause and the attribution requirement',
                'speechbrain/spkrec-ecapa-voxceleb — the package licence AND the '
                'VoxCeleb data terms behind it, which are not the same document',
                'data/runtime/model_licences.json — the house record, where each of the '
                'above is pinned with the revision actually installed',
            ],
            'note': (
                'declared at FILE level rather than left to the bank because the interesting '
                'fact is row-specific and a generic licence cell hides it: code licence and '
                'weights licence differ on the pyannote row, and the gate is an access '
                'condition, not a usage one. A cell that says "MIT" for pyannote is wrong even '
                'though pyannote.audio is MIT.'
            ),
        },
        'weights_pinned': {
            'grade': 'receipt',
            'source': 'data/runtime/model_licences.json plus the revision hash the loader actually resolved',
            'requires': [
                'data/runtime/model_licences.json — the recorded revision per model',
                'the run receipt of the diarization call, which must name the resolved '
                'Hugging Face revision and not just the repo id: "speaker-diarization-3.1" '
                'is a moving pointer and a gated one, so a name without a revision is not '
                'a pin',
            ],
            'note': (
                'same reason as `licence`: this is the column the gated pyannote weights make '
                'interesting. A revision that can only be fetched by an account that accepted '
                'an agreement is pinned to that account as much as to the hash, and the cell '
                'must say so.'
            ),
        },
    },
    'wiring': {},
    'na': {},
    'na_bands': NA_BANDS,
    'run_order': [
        'refuses',
        'failsafe',
        'same_person',
        'synthetic',
        'enrol',
        'child_adult',
        'sung',
        'count',
        'der',
        'boundaries',
        'short_turn',
        'overlap',
        'speech',
        'long_file',
    ],
    'fixtures': [
        {
            'path': MANIFEST,
            'verified': False,
            'blocks': ['der', 'speech', 'boundaries', 'short_turn', 'overlap', 'long_file'],
            'generated': (
                'a JSON in the shape of the subtitles MANIFEST, holding for each wav below: '
                'the ordered turn list as {speaker, t_start, t_end} with every t null, the '
                'donor roster, `short_turn_t` for the planted interjection, and '
                'verified: false. Write it by hand from the render script of each fixture — '
                'the speakers and the order are known from the recipe; only the TIMES need '
                'the operator.'
            ),
            'how_to_verify': (
                'open each wav in Audacity, mark the start and end of every turn (and the '
                'onset of the one-word interjection) to 3 decimals, fill them in, set '
                'verified = true. Six columns are written `untested — key unverified` '
                'until then. Estimated ~40 min for the two-, three- and four-speaker '
                'files; the 60-minute file inherits the two-speaker marks because it is '
                'twenty copies of it.'
            ),
        },
        {
            'path': TWO,
            'verified': True,
            'generated': (
                'the two-speaker reference: render the MANIFEST(subtitles) CORNELIS and ANNA '
                'lines of segments 8, 9 and 10 plus four further exchanges of the same two '
                'voices to reach ~2 min, concatenate in strict alternation with 0.3-0.8 s '
                'gaps, and plant ONE one-word interjection — ANNA saying "Joost!" — 1.5 s '
                'into a CORNELIS line so the two overlap for that word only. 48 kHz mono, '
                'loudnorm -16 LUFS. Record the exact turn order in the MANIFEST.'
            ),
            'note': 'verified TRUE as a roster: two named TTS voices and nothing else is in the file, which is what `count` needs. The turn TIMES are a separate key and live in the MANIFEST above, which is not verified',
        },
        {
            'path': NARRATION,
            'verified': True,
            'generated': 'the subtitles MANIFEST `audio.assembly` recipe (shared fixture — the same three-minute bilingual narration the subtitles and stt tests use)',
            'note': 'verified TRUE as a roster: the script names exactly three speakers (NARRATOR, CORNELIS, ANNA) plus two SFX segments, so the count key is fixed by construction. Its word-level verification (MANIFEST.verified_words) is a different key and is only needed by the stt and subtitles tests',
        },
        {
            'path': FOUR,
            'verified': True,
            'generated': 'four named house voices (NARRATOR, CORNELIS, ANNA, ABEL) each reading two of the MANIFEST segment texts in rotation, strict alternation, 0.3-0.8 s gaps, ~2 min, 48 kHz mono, loudnorm -16 LUFS',
            'note': 'verified TRUE as a roster: four voices by construction. Only used by `count`, which needs the roster and not the times',
        },
        {
            'path': OVERLAP,
            'verified': False,
            'blocks': ['overlap'],
            'generated': 'the same file the stt test declares at capability_tests/fixtures/stt/overlap_two.wav: the CORNELIS line of segment 8 and the ANNA line of segment 9 rendered separately and mixed with a 2.0 s offset so they overlap for ~3 s, equal loudness, 48 kHz mono. Copy or symlink it here rather than rendering a second one — one overlap fixture, two sheets',
            'how_to_verify': 'mark the exact start and end of the overlapping span to 3 decimals in the MANIFEST turn list, confirm both lines are audible and neither is buried, then set verified = true',
        },
        {
            'path': SUNG,
            'verified': True,
            'blocks': [],
            'generated': 'two sung stems from the kids-music leg: the melody_sampler vocal stem of one line sung by two DIFFERENT house singer voices, and a second take of the first singer. Vocal stems only, no backing, 48 kHz mono. identity_pairs.json names the three files as singer_a_v1, singer_a_v2, singer_b_v1',
            'note': 'verified TRUE as a roster: which singer sang which stem is fixed by the render call. The der half of the sung probe uses the concatenation of the three stems in a known order, so its turn times come from the render and not from a human mark',
        },
        {
            'path': CHILD,
            'verified': False,
            'blocks': ['child_adult'],
            'generated': 'Abel (child voice) and Cornelis (adult) alternating six short lines from the MANIFEST script, 0.5 s gaps, ~40 s, 48 kHz mono, loudnorm -16 LUFS; plus two further Abel takes for the pair decision, named abel_a and abel_b in identity_pairs.json',
            'how_to_verify': 'mark the six turn edges in the MANIFEST and confirm by ear that the child take is not clipped or sped up, then set verified = true',
        },
        {
            'path': SHORT,
            'verified': True,
            'generated': 'ffmpeg -i two_speakers.wav -ss 12.0 -t 0.5 -ar 48000 -ac 1 half_second.wav — half a second cut from the middle of a CORNELIS line',
            'note': 'verified TRUE and it needs no mark: the column asks for a refusal, so the only property the fixture must have is that it is 0.5 s long, which the command guarantees',
        },
        {
            'path': LONG,
            'verified': False,
            'blocks': ['long_file'],
            'generated': 'ffmpeg -f concat -safe 0 -i <a list naming two_speakers.wav twenty times> -c copy long_60min.wav (20 x ~2 min = ~40 min; repeat thirty times for a full hour if the hour is wanted literally — the column is about holding up, and the note records which was used)',
            'how_to_verify': 'inherits the two-speaker marks: once the MANIFEST turn list for two_speakers.wav is verified, the reference for this file is that list offset by the copy index, which the runner computes. Set verified = true at that point',
        },
        {
            'path': PAIRS,
            'verified': True,
            'generated': (
                'a JSON naming every identity pair used by speaker_pair_decision and '
                'enrol_seconds_min, as {pair_id: [wav_a, wav_b, same|different]}: '
                'cornelis_a/cornelis_b, anna_a/anna_b, cornelis_a/anna_a, cornelis_b/anna_b, '
                'abel_a/abel_b, abel_a/cornelis_a, tts_v1_take1/tts_v1_take2, '
                'tts_v1_take1/tts_v2_take1, singer_a_v1/singer_a_v2, '
                'singer_a_v1/singer_b_v1. The two tts_* voices are any two catalogue voices '
                'not already used above, each rendering the SAME sentence twice.'
            ),
            'note': 'verified TRUE by construction: which donor a rendered file came from is decided by the render call, so the same/different key needs no human judgement. This is the one identity key that is NOT blocked, and it is why the identity half of the sheet can be run before the turn marks exist',
        },
        {
            'path': 'capability_tests/fixtures/audio/judge/truncated.wav',
            'verified': True,
            'generated': 'declared by the audio bank (a WAV header claiming 40 s over 0.2 s of samples); reused by the failsafe probe here, not re-made',
        },
    ],
    'budget': {
        'calls': 46,
        'tokens_in': 0,
        'tokens_out': 0,
        'tokens_note': 'every row takes a wav and returns turns or a vector; no language-model tokens are spent anywhere on this step, and no row on this sheet is a Claude row',
        'minutes': 26,
        'gpu_minutes': 18,
        'operator_minutes': 20,
        'note': (
            'Per row, for a turn row. Own calls: der 3, speech 3, sung 3, count 3x3 = 9 '
            "(three fixtures), overlap 3, short_turn shares der's runs (0), boundaries shares "
            "der's runs (0), child_adult 3, refuses 3, failsafe 3, long_file 1 = 31 "
            'diarization calls. Wall clock on sortformer: ~1.5 min model load + 28 calls on '
            'clips of 0.5 s to 3 min (~6 min at roughly real-time/6) + the ~40-min '
            'concatenation in one pass (~7 min) = ~15 min, ~13 of them on the GPU. pyannote is '
            'the same 31 calls plus the embedding half of five probes and is slower per file: '
            '~26 min wall, ~18 GPU — that is the row this budget is written for. titanet is '
            'CPU only and cheap: 34 embeddings (17 pair files x 2 for the 3/5/10 s enrolment '
            'rungs) at ~150 ms each plus a 20 s model load = ~4 min, 0 GPU (row override). '
            'SHARED BANK for this step: the audio bank contributes 89 of the 103 columns and '
            'the judge bank is included after it, so it contributes nothing that audio already '
            "owns; the four Prompt bands are na_bands here, which removes most of the bank's "
            'render probes from this sheet entirely, and what is left is the 7 Capacity '
            'ladders and the universal columns — estimated ~15 further calls and ~10 min per '
            'row, included in the 46 calls and the 26 minutes above. OPERATOR: only ONE '
            "operator check on the merged test is this module's (the sighted failsafe "
            "question, 3 repeats = ~2 min); the rest of the 20 minutes is the bank's "
            'remaining sighted universal checks. Every domain check on this step is mechanical '
            '— DER, counts, cosines, coverage — which is the whole point: a human cannot hear '
            'a 250 ms boundary error. Two ONE-TIME costs are NOT in this per-row number: ~40 '
            'min marking the turn edges of the two-, three- and four-speaker fixtures, and ~15 '
            'min rendering the fixture set. Until the marks exist, six of the fourteen domain '
            'columns write untested.'
        ),
    },
    'notes': [
        'speaker_verify_worker.py loads speechbrain/spkrec-ecapa-voxceleb — a 192-d ECAPA embedding, '
        'NOT TitaNet. The row id `titanet` and the sung-stem calibration receipt are historical and '
        'the id is kept because column and row ids are permanent; the `model` field on the row says '
        'what actually runs. Anyone reading the sheet needs that written down, because a threshold '
        "calibrated for ECAPA means nothing in TitaNet's embedding space and vice versa.",
        "The sheet's verdict (identity works on speech, fails on singing) is kept as a TEST whose "
        'expected result on the embedding row is `no`. That is deliberate: the negative is the '
        'reason a whole gate was not built, so it has to keep being true, and the cosines on the '
        'trial say how close it is to changing.',
        'DER is scored with overlap INCLUDED and a 0.25 s collar. Excluding overlap is the usual way '
        'to publish a better number and it would hide the exact failure the overlap column exists '
        'for, so the convention is fixed here and a runner may not relax it.',
        'The identity half of this sheet can be run BEFORE the turn marks exist: identity_pairs.json '
        'is verified by construction (the render call decides which donor a file came from), so '
        'same_person, synthetic, enrol, threshold and the embedding half of sung and child_adult are '
        'not blocked. run_order puts them first for that reason — a partial run fills the identity '
        'columns and leaves the turn columns honestly untested.',
        'Two fixtures are shared rather than re-rendered: the three-minute narration (with the '
        'subtitles and stt tests) and the two-voice overlap mix (with the stt test). One recording '
        'measured on three sheets is comparable; three similar recordings are not.',
    ],
}
