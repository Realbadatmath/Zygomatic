# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Default test — Voice cloning (voice_clone). 2026-09-30.

Question the sheet asks: "How close does a cloned voice get, and may we legally use the donor?"

The sheet's own limitation is the reason this test exists: *"Speaker-verification similarity
has never been run on SPOKEN clones here. The one measurement we have is a negative on SUNG
stems."* So the test is a speaker-verification bench: FOUR fixed donor seeds out of the house
16-voice pool, SIX fixed lines, and a cosine against the donor — plus the two things a cosine
cannot see (accent, and whether the donor may be used at all).

SHAPE
    Fidelity   one cosine per (donor, line, seed) against the donor reference, with the
               IMPOSTOR baseline (the same clone against the other three donors) written on
               every trial, so the margin is auditable and not a bare number. Age/sex and
               timbre are voice_qc's F0 and VTL — the two markers that fail differently
               (pitch is fakeable, vocal-tract length is the size cue a listener hears).
    Inputs     three ladders: how short a reference still works, how noisy, how much.
    Rights     SIX columns that are NOT measurable and must never be probed: they are
               LOOKUPS against a voice-pool registry row. There is no such registry today —
               data/assets/voice_seeds/pool/manifest.json carries name / gender / description
               / wav / duration_s / maya_seed / transcript and nothing about consent. A donor
               without a registry row is therefore a `no`, not an `untested`.

WHAT IS BLOCKED AND WHY
    Every generated fixture (the trimmed references, the 10 dB-SNR noisy reference, the
    concatenated multi-reference) is declared with the exact command that makes it and is
    unverified until the operator has heard one of each, so ref_len / ref_quality / ref_count
    are BLOCKED until then. Nothing in this module creates audio.

WHAT THIS TEST CANNOT SAY
    Two of the four rows do not synthesise at all: `kyutai` is the harvest that imports CC0
    donation wavs as seeds, and `pool` is the seed-pick library. Their ten fidelity and input
    columns are `na` with the reason on each cell — they are the rows that answer the Rights
    columns, which is why they are in the sheet.
"""

from __future__ import annotations

import os

from zyg_workflows.paths import ZYG_CREWS_ROOT, ZYG_VOICE_ANALYSIS_DIR

#: The Chatterbox fallback cloner's isolated installation, beside the crews tree's other
#: models; $ZYG_CHATTERBOX_DIR overrides it.
CHATTERBOX_DIR = os.environ.get('ZYG_CHATTERBOX_DIR') or str(ZYG_CREWS_ROOT.parents[1] / 'models' / 'tts_chatterbox')

# ── check kinds this module adds (the runner is a table of these) ──────────────────────
# Speaker verification is a real mechanical detector with a published operating point, which
# is why identity here is measured and not left to a listener. The embedding is PINNED:
# pyannote/wespeaker-voxceleb-resnet34-LM, which ships with speaker-diarization-3.1 — already
# the bank's `speakers` detector, so no second model arrives for this step.
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
    'speaker_cosine_drop_max': (
        'the mean speaker cosine of this trial is at most `max_drop` below the '
        'mean cosine of the trial `to` (the same row, same donor, easier text)'
    ),
    'f0_vtl_band': (
        'voice_qc.py (Praat/parselmouth in its own venv) median F0 within `f0_pct` per cent '
        'and vocal-tract length within `vtl_cm` cm of the values measured on the donor '
        'reference — BOTH must hold, because pitch alone is fakeable'
    ),
    'timbre_match': (
        'mean spectral centroid of the take within `centroid_pct` per cent of the donor '
        'reference AND voice_qc VTL within `vtl_cm` cm; median F0 is deliberately NOT part '
        'of this decision, so a pitch-shifted impostor cannot pass it'
    ),
}

SEEDS = 'data/assets/voice_seeds/pool'

# ── the four fixed donors ─────────────────────────────────────────────────────────────
# Chosen for two reasons and nothing else: every one is >= 20.3 s long, so the 20 s rung of
# the ref_len ladder is actually reachable from the donor wav, and the set spans both sexes,
# one marked accent and one young voice. All 16 pool seeds are Maya1 output (apache-2.0,
# `maya_seed` in the manifest) — wholly synthetic, no human was recorded.
DONORS = {
    'm04_british_crisp': {'wav': SEEDS + '/m04_british_crisp.wav', 'sex': 'm', 'seconds': 23.98},
    'm06_young_earnest': {'wav': SEEDS + '/m06_young_earnest.wav', 'sex': 'm', 'seconds': 20.31},
    'f02_bright_clear': {'wav': SEEDS + '/f02_bright_clear.wav', 'sex': 'f', 'seconds': 24.32},
    'f08_crisp_journalist': {'wav': SEEDS + '/f08_crisp_journalist.wav', 'sex': 'f', 'seconds': 22.44},
}

# ── the fixed lines ───────────────────────────────────────────────────────────────────
# Six for similarity, verbatim, in the register the donor transcripts are written in (the
# manifest stores each donor's own transcript, so the phoneme inventory is comparable).
LINES = [
    'The tide turns at the yard gate and the gulls go quiet over the water.',
    'He laid the mallet on the rail and counted the barrels a second time.',
    'Nobody had told her the ship was leaving before the bell.',
    'I will write it down tonight, and you will not read it until spring.',
    'The rope was wet through and it took both hands to hold.',
    'There is a seam open below the waterline, and the tide is coming in.',
]
# A line the donors never said, and deliberately outside their phoneme inventory: Dutch
# proper nouns, a spelled-out year, and one long compound.
UNSEEN = (
    'In the year sixteen seventy-two the Kattenburg quaymaster, Cornelis Witsen, '
    'refused the scheepsbouwmeester twenty-three barrels of pitch.'
)
# The Dutch line for lang_transfer — the same content, so only the language changes.
DUTCH = (
    'In het jaar zestienhonderdtweeënzeventig weigerde de havenmeester van Kattenburg '
    'drieëntwintig tonnen pek aan de scheepsbouwmeester.'
)

# ── thresholds: declared HERE, with the reason, because the house has no receipt yet ───
COS_MIN = 0.55  # the resnet34-LM verification operating point; see THRESHOLD_NOTE
COS_MARGIN = 0.15  # over the impostor mean, so a generically-similar voice cannot pass
COS_TAKES = 0.75  # same row, same donor, three takes: a much easier bar than donor-match
THRESHOLD_NOTE = (
    "No spoken-clone cosine has ever been measured on this box (the sheet's own limitation), "
    "so 0.55 is the TEST's declared standard and not a house receipt: it is the usual "
    'same-speaker side of the wespeaker-voxceleb-resnet34-LM operating point. The number is '
    'only half the rule — every trial also carries the IMPOSTOR mean (this take against the '
    'other three donor references) and must clear it by 0.15, which is the part that cannot be '
    'gamed by a model that simply sounds like a plausible narrator. When the first full run '
    'lands, replace 0.55 with the measured same-donor / impostor distributions and bump the '
    'version — the margin rule stays.'
)

COND = {
    'seeds': [11, 12, 13],
    'repeats': 3,
    'sample_rate_out': 48000,
    'channels': 1,
    'donors': list(DONORS),
    'note': "the bank's conditions: three seeds, three repeats, 48 kHz mono. "
    'Every probe runs on all four donors and the column is the pass '
    'rate over (donor x seed).',
}

CLONERS = ['indextts2', 'chatterbox']


def _p(pid, title, feeds, checks, inputs, **kw):
    p = {
        'id': pid,
        'title': title,
        'feeds': list(feeds),
        'inputs': dict(inputs),
        'conditions': dict(COND),
        'checks': list(checks),
        'grade': 'measured',
        'rows': list(CLONERS),
    }
    p.update(kw)
    return p


PROBES = [
    _p(
        'clone_similarity',
        'Cosine against the donor over six fixed lines',
        ['similarity'],
        [{'check': 'speaker_cosine_min', 'to': 'DONOR', 'min': COS_MIN, 'margin': COS_MARGIN}],
        {
            'prompt': 'LINES',
            'task': 'Clone the donor reference wav and read each of the six LINES verbatim, one take per line per seed, no direction, dry, 48 kHz mono.',
            'lines': list(LINES),
        },
        run_order=1,
        unit='cosine',
        state_note=(
            'the pass rate is over 4 donors x 6 lines x 3 seeds = 72 takes; >= 0.8 -> yes, '
            '>= 0.4 -> partial. ' + THRESHOLD_NOTE
        ),
    ),
    _p(
        'clone_stability',
        'Three takes of one line: does it stay the same voice',
        ['stability'],
        [
            {'check': 'speaker_cosine_pairwise_min', 'min': COS_TAKES},
            {'check': 'speaker_cosine_min', 'to': 'DONOR', 'min': COS_MIN, 'margin': COS_MARGIN},
        ],
        {
            'prompt': LINES[0],
            'task': 'Render LINES[0] three times per donor at the three seeds; compare the takes with each other, not only with the donor.',
        },
        run_order=2,
        unit='cosine',
        state_note=(
            'stability is the PAIRWISE bar: a row can sit at a healthy donor cosine and still '
            'wander between takes, which is the failure that makes a long narration sound like '
            'two people. 0.75 is the same-recording-conditions bar, deliberately higher than the '
            'donor-match bar, because nothing changes between these three takes but the seed.'
        ),
    ),
    _p(
        'clone_age_sex',
        "Keeps the donor's age and sex (voice_qc F0 and VTL)",
        ['age_sex'],
        [{'check': 'f0_vtl_band', 'f0_pct': 18, 'vtl_cm': 1.0, 'to': 'DONOR'}],
        {
            'prompt': 'LINES',
            'task': 'Measure the clone_similarity takes with voice_qc; no new render.',
            'lines': list(LINES),
        },
        run_order=3,
        state_note=(
            "the tolerances are voice_qc.py's own, calibrated 2026-08-06 against this seed pool "
            '(|dF0| <= 18 %, |dVTL| <= 1.0 cm; the adult male and female seed groups are 2.9 cm '
            'apart, so 1.0 cm stays well inside one person). BOTH markers must hold: a render '
            'that keeps F0 and grows VTL is an adult in falsetto, and a pitch-only check cannot '
            'see it. No render of its own — it measures the clone_similarity takes.'
        ),
    ),
    _p(
        'clone_accent',
        "Keeps the donor's accent (blind operator, three pairs)",
        ['accent'],
        [
            {
                'check': 'operator',
                'blind': True,
                'question': "You will hear A then B. Is the speaker's ACCENT the same in both — the same region, not merely the same sex and age? yes/no",
            }
        ],
        {
            'prompt': 'LINES',
            'task': 'Present three A/B pairs per donor: A = the donor reference, B = a clone_similarity take (lines 1, 3 and 6), order randomised per pair.',
            'lines': [LINES[0], LINES[2], LINES[5]],
        },
        run_order=7,
        state_note=(
            'accent is an OPERATOR column and is not probed mechanically: no meter on this box '
            'measures region. m04_british_crisp is the donor that makes the question answerable '
            'at all — it is the one marked accent in the pool. 12 decisions per row '
            '(4 donors x 3 pairs); the pass rate is over those 12.'
        ),
    ),
    _p(
        'clone_timbre',
        'Keeps timbre, not just pitch',
        ['timbre'],
        [{'check': 'timbre_match', 'centroid_pct': 15, 'vtl_cm': 1.0, 'to': 'DONOR'}],
        {
            'prompt': 'LINES',
            'task': 'Measure the clone_similarity takes: mean spectral centroid and voice_qc VTL against the donor reference; no new render.',
            'lines': list(LINES),
        },
        run_order=4,
        state_note=(
            'this column exists because F0 is the cheap answer: a resample lands the pitch and '
            'moves the body with it (build_cast_voices measured seed_k doing exactly that). So '
            'F0 is excluded here on purpose and the decision is brightness + tract size. 15 % on '
            "the centroid is the TEST's declared band, wide enough for line-to-line variation "
            "and narrower than the pool's own spread between neighbouring voices."
        ),
    ),
    _p(
        'clone_unseen',
        'Holds on text the donor never said',
        ['unseen_text'],
        [
            {'check': 'speaker_cosine_min', 'to': 'DONOR', 'min': COS_MIN, 'margin': COS_MARGIN},
            {'check': 'speaker_cosine_drop_max', 'to': 'clone_similarity', 'max_drop': 0.08},
        ],
        {'prompt': UNSEEN, 'task': 'Render the UNSEEN line verbatim, one take per donor per seed.'},
        run_order=5,
        state_note=(
            'every pool donor\'s own transcript is in the manifest, so "unseen" is made real '
            "rather than assumed: this line is outside the donor's register AND its phoneme "
            'inventory (Dutch proper nouns, a spelled-out year, one long compound). The second '
            'check is the honest one — the cosine may not fall more than 0.08 below the same '
            "row's clone_similarity mean, because an absolute pass on easy text and a collapse "
            'on hard text is the failure this column is for.'
        ),
    ),
    _p(
        'ref_len_ladder',
        'The shortest reference that still clones',
        ['ref_len'],
        [{'check': 'speaker_cosine_min', 'to': 'DONOR', 'min': COS_MIN, 'margin': COS_MARGIN}],
        {
            'fixture': 'capability_tests/fixtures/voice_clone/ref_len/',
            'prompt': LINES[0],
            'task': 'For each rung N in the ladder, clone from the FIRST N seconds of the donor wav (cut on a sample boundary, no fade, no loudness change) and read LINES[0].',
        },
        ladder=[3, 5, 10, 20],
        unit='s',
        run_order=8,
        state_note=(
            'the answer is the SHORTEST rung that reaches the threshold on all three seeds — the '
            'count convention is inverted here, and the runner must not report the last passing '
            'rung. Every donor is >= 20.3 s so all four rungs are reachable; the reference is '
            'always the HEAD of the donor wav, never a hand-picked good passage. The three '
            'elder seeds in the pool are 15-18.4 s and are excluded from this test for that '
            'reason alone.'
        ),
    ),
    _p(
        'ref_noisy',
        'Survives a noisy reference (street noise at 10 dB SNR)',
        ['ref_quality'],
        [
            {'check': 'speaker_cosine_min', 'to': 'DONOR', 'min': COS_MIN, 'margin': COS_MARGIN},
            {'check': 'speaker_cosine_drop_max', 'to': 'clone_similarity', 'max_drop': 0.10},
            {
                'check': 'noise_floor_max',
                'max': -45.0,
                'note': 'the OUTPUT must not inherit the reference noise; a clone that re-synthesises the street is a fail even at a passing cosine',
            },
        ],
        {
            'fixture': 'capability_tests/fixtures/voice_clone/ref_noisy/',
            'prompt': LINES[0],
            'task': "Clone from the noisy reference (donor wav + the bank's street ambience mixed at 10 dB SNR) and read LINES[0].",
        },
        run_order=9,
        state_note=(
            'the cosine is measured against the CLEAN donor reference, never against the noisy '
            'one — the question is whether the voice survived the noise, not whether the clone '
            'matches its own degraded input. The third check catches the other failure mode: '
            'engines that clone the room along with the speaker.'
        ),
    ),
    _p(
        'ref_count_ladder',
        'Do more references help',
        ['ref_count'],
        [{'check': 'speaker_cosine_min', 'to': 'DONOR', 'min': COS_MIN, 'margin': COS_MARGIN}],
        {
            'fixture': 'capability_tests/fixtures/voice_clone/ref_count/',
            'prompt': LINES[0],
            'task': 'For each rung N in (1, 2, 4), clone from N non-overlapping 4 s segments of the donor wav, concatenated in order with 200 ms of silence between them, and read LINES[0].',
        },
        ladder=[1, 2, 4],
        unit='count',
        run_order=10,
        state_note=(
            "the house interface takes exactly ONE reference wav (tts_service._tts_shared's "
            '`seed_wav`), so "more references" can only mean a longer concatenated reference — '
            'that is what is tested, and the sheet note must say so. The answer is the rung with '
            'the highest mean cosine, and `no` when 4 is not better than 1: this column asks '
            'whether the extra audio BUYS anything. The segments come from one recording, so a '
            'true multi-SESSION reference test is out of reach of the pool as it stands (16 '
            'voices, one wav each) and is listed in the notes as not answered.'
        ),
    ),
    _p(
        'lang_transfer',
        'An English donor speaking the Dutch line',
        ['lang_transfer'],
        [
            {'check': 'speaker_cosine_min', 'to': 'DONOR', 'min': COS_MIN, 'margin': COS_MARGIN},
            {'check': 'language', 'lang': 'nl', 'min': 0.6},
            {
                'check': 'transcript_contains_terms',
                'terms': ['Kattenburg', 'havenmeester', 'scheepsbouwmeester'],
                'note': 'Whisper with language=nl; the three hard compounds must come back',
            },
            {
                'check': 'operator',
                'blind': True,
                'question': 'Is this understandable Dutch — a Dutch listener would not have to guess at a word? yes/no',
            },
        ],
        {'prompt': DUTCH, 'task': 'Clone each (English-speaking) donor and read the DUTCH line verbatim.'},
        run_order=6,
        state_note=(
            'two different failures, so two kinds of check: the cosine says the voice survived '
            'the language switch, the Whisper terms and the blind listen say the Dutch is '
            'usable. A row can pass the cosine and be unusable — an English speaker reading '
            'Dutch phonetically scores well on identity. The operator decides the column when '
            "the two disagree, per the bank's protocol."
        ),
    ),
    _p(
        'clone_failsafe',
        'Fails without breaking the caller',
        ['failsafe'],
        [
            {
                'check': 'operator',
                'blind': False,
                'question': (
                    'Did all three broken calls come back — each returning a value or raising an '
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
            'prompt': '(three deliberately broken calls — the three in `variants`, in order)',
            'audio': 'capability_tests/fixtures/audio/judge/truncated.wav',
            'variants': {
                'empty_line': 'the line is the empty string, the reference is a valid donor wav',
                'broken_reference': (
                    'the line is LINES[0], the reference is '
                    'capability_tests/fixtures/audio/judge/truncated.wav — a WAV whose '
                    'header claims 40 s over 0.2 s of samples'
                ),
                'missing_reference': (
                    'the line is LINES[0], the reference is a path that does not exist: '
                    'data/assets/voice_seeds/pool/does_not_exist.wav'
                ),
            },
        },
        run_order=11,
        rows=['indextts2', 'chatterbox', 'kyutai', 'pool'],
        conditions=dict(
            COND,
            repeats=3,
            seeds=[11, 11, 11],
            donors=[list(DONORS)[0]],
            note='no take is expected; what is measured is how the call ends, so one donor is enough',
        ),
        state_note=(
            'all three must come back. no = any hang past 120 s, any crash of the host process, '
            'any leaked VRAM allocation. Answered SIGHTED — there is nothing to be blind about '
            'when the question is whether the process is still running. The `pool` row is a '
            'library lookup, so its broken calls are an empty query and a donor id that is not '
            'in the pool.'
        ),
        overrides_shared='u_failsafe',
    ),
]

# ── the Rights columns: lookups against a registry row that does not exist yet ─────────
_REG = [
    'the voice-pool registry row for this donor, by seed id',
    'the file and line that holds it',
    'the date the row was written and by whom',
]
_REG_NOTE = (
    'There is no consent registry today: data/assets/voice_seeds/pool/manifest.json holds '
    'name / gender / description / wav / duration_s / maya_seed / transcript and no rights '
    'field at all, and data/assets/voice_seeds/kyutai/manifest.json holds licence + '
    'provenance but no per-donor consent row. So the honest answer for a donor without a '
    'registry row is NO — not untested. The two families differ and the registry must keep '
    'them apart: the 16 pool seeds are Maya1 output from a written description (apache-2.0, '
    '`maya_seed` present, no human recorded), while the kyutai seeds are REAL people who '
    'donated to the Unmute Voice Donation Project (CC0-1.0, 228 of 374 submissions verified, '
    'June 2025 - February 2026).'
)


def _lk(question, note):
    return {'question': question, 'requires': ['registry_row'] + _REG, 'grade': 'receipt', 'note': note}


LOOKUP = {
    'consent': _lk('Is there a registry row naming this donor and the consent text they gave?', _REG_NOTE),
    'consent_scope': _lk(
        'Does that consent cover THIS use — a monetised channel, and this named character speaking these words?',
        'A CC0 licence is not consent scope. The kyutai donors consented to a SPEECH '
        'MODEL, which is not the same as consenting to a named character in a '
        'commercial film; the registry row must say which of the two it is. ' + _REG_NOTE,
    ),
    'revoke': _lk(
        'Is there a written path by which the donor can withdraw, and is the voice then '
        'actually retired from the pool and from the shipped episodes?',
        'CC0 is irrevocable by construction, which is a licence fact and not an answer to '
        'this question: the question is whether OUR path exists. Today it does not, so the '
        'column is a no for every donor until the registry row names the path.',
    ),
    'real_person': _lk(
        'Is this donor a real, identifiable person — and if so, a public one?',
        'This is the one column with a real house receipt already. The pool seeds are '
        'wholly synthetic (Maya1 from a written description) and the answer for them is '
        'a clean "not a real person". The kyutai seeds ARE a real person\'s timbre, and '
        'house practice (cornelis_broken.json, build_cast_voices.py) is that a '
        'donor-derived seed is always RESHAPED before a character speaks with it, so an '
        "identifiable person is never put in a character's mouth. The registry row must "
        'record the reshape (kr01 is flagged reference_only for exactly this reason).',
    ),
    'disclosure': _lk(
        'Is the synthetic origin of the delivered audio recorded, and where does a viewer or a platform see it?',
        'Two halves, and only the first is close to done: the run receipt records the '
        'engine and the seed, but nothing writes a synthetic-origin flag into the '
        "delivered file's metadata or into the episode's disclosure text. Partial at "
        'best until the registry row names both.',
    ),
    'pool': _lk(
        'Is this donor registered in the voice pool — present in the manifest AND carrying a rights row?',
        'Presence in the manifest is mechanical and true for all 16 pool seeds; that is the '
        'easy half and on its own it is a PARTIAL, because "registered" on this sheet means '
        'the rights row too. ' + _REG_NOTE,
    ),
}

# ── rows ───────────────────────────────────────────────────────────────────────────────
_FIDELITY = [
    'similarity',
    'stability',
    'age_sex',
    'accent',
    'timbre',
    'unseen_text',
    'ref_len',
    'ref_quality',
    'ref_count',
    'lang_transfer',
]
_NOT_A_CLONER = {
    c: (
        'this row does not synthesise speech: it delivers reference wavs for a cloner to '
        'use, so a cloning-fidelity measurement here would be scoring IndexTTS-2 or '
        "Chatterbox under another row's name. It is in the sheet for the Rights columns."
    )
    for c in _FIDELITY
}

TEST = {
    'step': 'voice_clone',
    'version': '2026-09-30.1',
    'title': 'Four donors, six lines, one cosine — and the six rights columns that are not measurable',
    'purpose': (
        'Measure how close a cloned voice gets with a pinned speaker-verification embedding and '
        'an impostor baseline on every trial, and force the donor-rights questions to name a '
        'registry row instead of an opinion.'
    ),
    'include_shared': 'audio',
    'thresholds': {
        'speaker_cosine_min': COS_MIN,
        'impostor_margin': COS_MARGIN,
        'pairwise_min': COS_TAKES,
        'f0_pct': 18,
        'vtl_cm': 1.0,
        'centroid_pct': 15,
        'note': THRESHOLD_NOTE,
    },
    'detectors': {
        'speaker': 'pyannote/wespeaker-voxceleb-resnet34-LM (ships with '
        "speaker-diarization-3.1, the bank's `speakers` detector), revision "
        'pinned in the run receipt',
        'f0_vtl': f'voice_qc.py -> {ZYG_VOICE_ANALYSIS_DIR} (Praat/parselmouth) '
        'over subprocess+JSON; the GUI process never imports it',
        'transcript': 'faster-whisper large-v3, language given, as in the bank',
    },
    'donors': DONORS,
    'lines': {'similarity': list(LINES), 'unseen': UNSEEN, 'dutch': DUTCH},
    'rows': {
        'indextts2': {
            'transport': 'service',
            'model': 'IndexTTS-2 (house primary since 2026-08-06)',
            'where': 'tts_service._tts_shared -> _indextts_segments, seed_wav = the donor wav, '
            'emo_text/emo_alpha left at the process defaults (1 / 0.6)',
        },
        'chatterbox': {
            'transport': 'service',
            'model': 'Chatterbox (MIT, isolated venv) — the fallback cloner',
            'where': f'tts_service fallback -> {CHATTERBOX_DIR}/'
            '.venv chatterbox_worker.py, exaggeration 0.3 / cfg_weight 0.4 / temperature 0.7',
            'budget': {
                'minutes': 34,
                'gpu_minutes': 30,
                'note': "the lighter engine: ~8 s a line against IndexTTS-2's ~12 s, same call count",
            },
        },
        'kyutai': {
            'transport': 'service',
            'model': 'the Kyutai CC0 donation harvest (wavs only; the '
            ".safetensors voice embeddings are pinned to Kyutai's "
            'withheld encoder and are useless here)',
            'where': 'voice_harvest_kyutai.py',
            'na': dict(_NOT_A_CLONER),
            'budget': {
                'calls': 1,
                'minutes': 2,
                'gpu_minutes': 0,
                'operator_minutes': 0,
                'note': 'the harvest is a fetch and a Praat measurement of the SOURCE wav, not a render; its columns are the Rights lookups',
            },
        },
        'pool': {
            'transport': 'library',
            'model': 'the 16-voice seed pool (Maya1, apache-2.0) and the gender-filtered deterministic seed pick',
            'where': 'voice_pool._seed_pool / _voice_seed_for over data/assets/voice_seeds/pool/manifest.json',
            'na': dict(_NOT_A_CLONER),
            'budget': {
                'calls': 1,
                'minutes': 1,
                'gpu_minutes': 0,
                'operator_minutes': 0,
                'note': 'a manifest read and a deterministic md5 pick; there is nothing to render on this row',
            },
        },
    },
    'probes': PROBES,
    'derive': {},
    'lookup': LOOKUP,
    'wiring': {},
    'na': {},
    'fixtures': [
        {
            'path': SEEDS + '/manifest.json',
            'verified': True,
            'note': '16 voices, all with duration_s and maya_seed; the four DONORS are read from here',
        },
        {'path': DONORS['m04_british_crisp']['wav'], 'verified': True},
        {'path': DONORS['m06_young_earnest']['wav'], 'verified': True},
        {'path': DONORS['f02_bright_clear']['wav'], 'verified': True},
        {'path': DONORS['f08_crisp_journalist']['wav'], 'verified': True},
        {
            'path': 'capability_tests/fixtures/voice_clone/ref_len/',
            'verified': False,
            'blocks': ['ref_len'],
            'generated': 'for each donor D and each N in (3, 5, 10, 20): '
            'ffmpeg -i <D.wav> -t N -c:a pcm_s16le ref_len/<D>_<N>s.wav  (head of the file, no fade, no loudnorm)',
            'how_to_verify': 'listen to one 3 s cut per donor and confirm it is speech from the first word, '
            'not a cut that starts mid-syllable or in the lead-in silence; then set verified = true',
        },
        {
            'path': 'capability_tests/fixtures/voice_clone/ref_noisy/',
            'verified': False,
            'blocks': ['ref_quality'],
            'generated': 'for each donor D: measure the RMS of <D.wav> and of '
            'capability_tests/fixtures/audio/sounds/street_ambience.wav, then '
            'ffmpeg -i <D.wav> -i <street, gain set so speech RMS - noise RMS = 10.0 dB> '
            '-filter_complex amix=inputs=2:duration=first:normalize=0 ref_noisy/<D>_snr10.wav',
            'how_to_verify': 'measure the realised SNR of one file with the same RMS method and confirm it '
            'is 10.0 +/- 0.5 dB, and that the speech is still fully intelligible; then set verified = true',
        },
        {
            'path': 'capability_tests/fixtures/voice_clone/ref_count/',
            'verified': False,
            'blocks': ['ref_count'],
            'generated': 'for each donor D and each N in (1, 2, 4): cut N non-overlapping 4 s segments from '
            'D.wav at 0 s, 5 s, 10 s and 15 s, concatenate them in that order with 200 ms of '
            'silence between (ffmpeg concat + anullsrc) -> ref_count/<D>_<N>ref.wav',
            'how_to_verify': 'confirm each segment starts and ends on a word boundary (no clipped syllable '
            'at a join) and that the 4-segment file is ~16.6 s; then set verified = true',
        },
    ],
    'budget': {
        'calls': 204,
        'tokens_in': 0,
        'tokens_out': 0,
        'tokens_note': 'a zero-shot cloner takes a reference wav and a line of text; no language model is called, so no tokens are spent on any row of this step',
        'minutes': 46,
        'gpu_minutes': 42,
        'operator_minutes': 14,
        'note': (
            'DOMAIN renders per cloner row, all on 4 donors x 3 seeds = 12 combinations: similarity '
            '6 lines x 12 = 72; stability 12 (3 takes is the 3 seeds); unseen 12; lang_transfer 12; '
            'ref_len 4 rungs x 12 = 48; ref_noisy 12; ref_count 3 rungs x 12 = 36 — that is 204 '
            'renders. age_sex, timbre and accent add NO renders: they measure or replay the '
            'similarity takes. At ~12 s a one-line render on IndexTTS-2 plus ~60 s model load once, '
            '204 x 12 s = 41 min + 1 min load = ~42 GPU minutes. Operator: 12 blind accent pairs + '
            '12 Dutch listens + 4 blind spot checks = 28 decisions x 30 s = 14 min per cloner row. '
            'The SHARED AUDIO BANK adds its own cost on top for this step — 88 of the 104 columns '
            "are the bank's, and for voice_clone they are the 7 Capacity ladders (37 rungs x 3 "
            'seeds = 111 renders) plus the four Prompt bands (~57 damage variants x 3 = 171, the '
            '5-rung clarity ladder x 3 = 15, the 8-rung length ladder x 3 = 24, and the four '
            'distinct-things ladders ~60) = ~380 renders, about 80 further GPU minutes per cloner '
            "row; the bank's own budget is authoritative for those. The kyutai and pool rows "
            'override this to ~0 (a fetch and a manifest read; no GPU, no operator). No claude_cli '
            'or anthropic_api row on this step, so nothing here spends the shared Claude week.'
        ),
    },
    'notes': [
        "The sheet's limitation is the whole reason for this test: speaker-verification similarity has "
        'never been run on SPOKEN clones here, and the one measurement on record is a NEGATIVE on sung '
        'stems. Until this test runs, every Fidelity cell is honestly empty.',
        'The Rights columns must never become probes. There is nothing to measure: the answer is a '
        'registry row or it is a no. Writing a partial there because "the licence is CC0" is the exact '
        'mistake the consent half of voice_harvest_kyutai.py was written to avoid — a CC0 corpus '
        'recorded for speech recognition clears the legal bar and fails the consent one.',
        'This step OWNS `failsafe` (probe clone_failsafe) instead of letting the shared audio bank '
        'answer it, and the reason is a defect in code this test may not edit, recorded here so it can '
        "be fixed rather than forgotten: the bank's u_failsafe carries its fixed input as "
        '`inputs.command`, which validate_shared accepts (line ~502 allows command/image/video/mesh) '
        'but the per-step validator refuses (line ~320 allows only prompt/task/fixture/audio). Every '
        'step that includes the audio bank therefore fails on u_failsafe until one of those two lists '
        'is widened. clone_failsafe asks the SAME question over the same truncated.wav fixture with the '
        'three broken calls named in `inputs.variants`; when the bank and the validator agree again, '
        'DELETE clone_failsafe and let the bank answer, so the column is measured identically on every '
        'audio step.',
        'Not answered by this test, on purpose: a true multi-SESSION reference (the pool holds one wav '
        'per voice, so ref_count concatenates segments of one recording), and any elder donor at the '
        '20 s rung (m03_elder_gravel is 18.43 s, f04_elder_gentle 15.02 s — no elder seed reaches 20 s).',
        'Identity is checked against a known-good RENDER and not against a DSP-shaped seed wherever a '
        'row has one: abel_voice.py measured its own seed at 13.87 cm VTL against 11.99 cm for the '
        'render of it, so gating a render on a pitch-shifted seed fails a voice that is actually right. '
        'The four DONORS here are unshaped Maya1 output, which is why they can be the reference directly.',
    ],
}
