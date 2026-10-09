# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""audio_shared: Prompt — limits. Ladders that answer a NUMBER."""

from __future__ import annotations

from .settings import CLAP_ABSENT_MAX, CLAP_MIN, CLAP_NULL_MARGIN, COND_AMB, COND_JUDGE, COND_SOUND
from .fixtures import BASE_CHECKS, PROBES, _probe

# ── Prompt: limits — ladders that answer a NUMBER ──────────────────────────────────────
# The length ladder is one sentence grown by appending clauses; the FIRST clause is always the
# subject, so a rung's key never changes and "which terms dropped" is measurable.
LEN_CLAUSES = [
    'three slow knocks on a wooden door',  # the subject, always rung 1
    'then silence',
    'interior, close, dry',
    'no music, no voices',
    'a small room with a low ceiling and a stone floor',
    'the door is heavy oak with iron hinges and a worn lower panel',
    'the knocks are made with a bare knuckle, not a fist and not a ring',
    'the room has no furniture and no soft surfaces anywhere in it',
    'recorded from one metre away on a single microphone at chest height',
    'nothing else happens before, between or after the three knocks at all',
]
LEN_RUNGS = [8, 12, 20, 32, 64, 128, 256, 512]
LEN_RULE = (
    'a rung of N words is the clauses of LEN_CLAUSES joined with ", " and then REPEATED '
    'from the start until the word count reaches N, cut on a word boundary. The subject '
    'clause is therefore always first and the key is always three onsets on wood.'
)
PROBES.append(
    _probe(
        'pd_length_ladder',
        'Prompt: the length ladder (8 - 512 words, one key)',
        ['pd_max_hard', 'pd_max_soft', 'pd_max_words', 'pd_truncation_loud'],
        list(BASE_CHECKS)
        + [{'check': 'present', 'terms': ['knock'], 'on': "the row's echoed prompt, when it echoes one"}],
        cond=dict(COND_SOUND),
        inputs={'prompt': 'LADDER', 'task': 'render each rung verbatim'},
        ladder=LEN_RUNGS,
        ladder_rule=LEN_RULE,
        unit='count',
        state_note=(
            'one ladder, four columns:\n'
            '  pd_max_hard       the first rung that ERRORS or returns nothing, in words '
            '(`unit: count`); no rung errors -> "> 512"\n'
            '  pd_max_soft       the first rung where the key stops holding while the call '
            'still succeeds, in words\n'
            '  pd_max_words      the largest rung that passes, in words — the number an '
            'operator may actually write\n'
            '  pd_truncation_loud  yes when a rung that lost terms SAID so (a warning, a '
            'token-count error, a recorded truncation); no when it silently dropped them. This '
            "is read from the row's own stderr/telemetry, not from the audio."
        ),
    )
)

PROBES += [
    _probe(
        'pd_unique_things',
        'Prompt: unique things describable at once',
        ['pd_unique_things'],
        [
            {'check': 'clap_labels_all_min', 'labels': 'RUNG_LABELS', 'min': 0.24},
            {
                'check': 'operator',
                'blind': True,
                'question': 'How many of the listed sounds can you actually hear in this recording? '
                'Answer with a number. (The list is shown with the trial.)',
            },
        ],
        cond=dict(COND_AMB),
        inputs={'prompt': 'a quiet harbour at dusk containing exactly these sounds and no others: {things}'},
        unit='count',
        ladder_labels=[
            ['water lapping against wood'],
            ['water lapping against wood', 'a seagull calling'],
            ['water lapping against wood', 'a seagull calling', 'rope creaking'],
            ['water lapping against wood', 'a seagull calling', 'rope creaking', 'a distant church bell'],
            [
                'water lapping against wood',
                'a seagull calling',
                'rope creaking',
                'a distant church bell',
                'footsteps on wooden boards',
            ],
            [
                'water lapping against wood',
                'a seagull calling',
                'rope creaking',
                'a distant church bell',
                'footsteps on wooden boards',
                'a cart on cobbles',
                'a dog barking',
                'a crowd murmuring',
            ],
        ],
        state_note=(
            'the answer is a COUNT: the largest rung where the operator hears ALL the '
            "listed sounds and CLAP scores every label above 0.24. The operator's number "
            'decides; CLAP is the screen and disagreements are recorded in the trial.'
        ),
    ),
    _probe(
        'pd_unique_subjects',
        'Prompt: named subjects held apart',
        ['pd_unique_subjects'],
        [
            {'check': 'speaker_count', 'n': 'RUNG'},
            {'check': 'transcript_contains_terms', 'terms': 'RUNG_NAMES', 'min_share': 1.0, 'applies_to': 'speech'},
            {
                'check': 'operator',
                'blind': True,
                'question': 'How many DIFFERENT people can you hear? Answer with a number.',
            },
        ],
        cond=dict(COND_SOUND),
        inputs={
            'prompt': 'CORNELIS: The seam is open.\nJOOST: Which seam?\nANNA: The one under the rail.\n'
            'PIETER: I told you yesterday.\nMAARTEN: Fetch the pitch.\nGRIETJE: There is none left.',
            'task': 'Render the first N lines, one distinct voice per named speaker, in the order written.',
        },
        unit='count',
        ladder=[1, 2, 3, 4, 5, 6],
        ladder_names=['Cornelis', 'Joost', 'Anna', 'Pieter', 'Maarten', 'Grietje'],
        state_note=(
            'the answer is a COUNT: the largest rung where pyannote counts exactly N '
            'speakers AND the operator hears N different people. pyannote decides the '
            "number on the sheet; the operator's count is recorded beside it and a "
            'disagreement of more than one makes the column partial. A row that cannot '
            'speak takes this column from the step module.'
        ),
    ),
    _probe(
        'pd_attrs_per_thing',
        'Prompt: attributes per thing that stay bound',
        ['pd_attrs_per_thing'],
        [
            {
                'check': 'operator',
                'blind': True,
                'question': 'How many of the attributes listed with this trial are true of the sound '
                'you hear? Answer with a number.',
            },
            {'check': 'clap_label_min', 'label': 'a creaking door', 'min': CLAP_MIN, 'margin': CLAP_NULL_MARGIN},
            {'check': 'duration_s', 'min': 3.4, 'max': 4.4},
        ],
        cond=dict(COND_SOUND),
        inputs={'prompt': 'a door {attrs}'},
        unit='count',
        ladder_attrs=[
            ['creaking'],
            ['creaking', 'opening slowly'],
            ['creaking', 'opening slowly', 'heavy oak'],
            ['creaking', 'opening slowly', 'heavy oak', 'iron hinges'],
            ['creaking', 'opening slowly', 'heavy oak', 'iron hinges', 'in a small dry room'],
            [
                'creaking',
                'opening slowly',
                'heavy oak',
                'iron hinges',
                'in a small dry room',
                'one metre away',
                'stopping halfway',
            ],
        ],
        state_note=(
            'ONE thing, more and more attributes on it. The answer is a COUNT: the '
            'largest rung where the operator confirms ALL the attributes. The operator '
            'decides — no detector hears "iron hinges". CLAP and the duration check only '
            'prove a door of about the right length is there at all.'
        ),
    ),
    _probe(
        'pd_instructions',
        'Prompt: separate instructions obeyed at once',
        ['pd_instructions', 'pd_constraints'],
        [
            {'check': 'onset_count', 'n': 3, 'tolerance': 0},
            {'check': 'duration_s', 'min': 5.7, 'max': 6.3},
            {'check': 'lufs_range', 'min': -20.0, 'max': -14.0},
            {'check': 'true_peak_max', 'max': -1.0},
            {
                'check': 'pause_ms',
                'at': 'the tail, after the last onset',
                'min': 1000,
                'max': 3000,
                'note': 'the prompt asks for at least a second of silence after the knocks',
            },
            {'check': 'clap_absent_max', 'labels': ['music', 'a person speaking'], 'max': CLAP_ABSENT_MAX},
            {
                'check': 'operator',
                'blind': True,
                'question': 'Are the three knocks slow and even, with a clear second of silence at the end? yes/no',
            },
        ],
        cond=dict(COND_SOUND),
        inputs={
            'prompt': 'three slow knocks on a wooden door, interior, close',
            'task': 'Obey all six: (1) exactly three knocks; (2) exactly 6.0 seconds long; '
            '(3) at least 1.0 second of silence at the end; (4) integrated loudness '
            'between -20 and -14 LUFS; (5) true peak at or below -1.0 dBTP; '
            '(6) no music and no voices.',
        },
        state_note=(
            'SIX numbered instructions, each with its own mechanical check. Two columns '
            'come off one trial:\n'
            '  pd_instructions  the share of the six that held, averaged over repeats\n'
            '  pd_constraints   yes only when ALL SIX held in the SAME take (they are '
            'constraints, and a constraint that holds only on its own is not honoured)\n'
            'The operator check is a sanity read on the two the detectors judge worst '
            '(evenness, a tail a human would call silent) and does not decide either '
            'column on its own.'
        ),
    ),
    _probe(
        'pd_order_wins',
        'Prompt: which end of the prompt wins',
        ['pd_order_wins'],
        [
            {
                'check': 'clap_label_min',
                'label': 'a church bell',
                'min': CLAP_MIN,
                'margin': CLAP_NULL_MARGIN,
                'note': 'scored per variant; what matters is WHICH end the render followed',
            },
            {
                'check': 'operator',
                'blind': True,
                'question': 'Is this mainly a church bell, or mainly a dog barking? Answer bell/dog.',
            },
        ],
        cond=dict(COND_SOUND),
        inputs={
            'prompt': 'a church bell ringing, close, interior. a dog barking, close, interior.',
            'variants': {
                'bell_first': 'a church bell ringing, close, interior. a dog barking, close, interior.',
                'dog_first': 'a dog barking, close, interior. a church bell ringing, close, interior.',
            },
        },
        state_note=(
            'two mutually exclusive subjects, order swapped. The operator names the '
            'winner blind in each variant; the column reports WHICH END wins, not a '
            'pass:\n  both variants follow the FIRST subject -> "front", yes\n'
            '  both follow the LAST -> "back", yes\n'
            '  the winner does not track the order -> "neither", no (nothing is '
            'steerable by position)\n'
            "CLAP's two label scores are recorded per variant as the screen."
        ),
    ),
    _probe(
        'pd_negative_len',
        'Prompt: usable negative-prompt length',
        ['pd_negative_len'],
        [
            {'check': 'clap_absent_max', 'labels': 'RUNG_LABELS', 'max': CLAP_ABSENT_MAX},
            {'check': 'clap_label_min', 'label': 'rain on a roof', 'min': CLAP_MIN, 'margin': CLAP_NULL_MARGIN},
            {
                'check': 'operator',
                'blind': True,
                'question': 'Is anything from the list shown with this trial audible in the recording? '
                'yes/no (a YES is a FAIL of this rung)',
            },
        ],
        cond=dict(COND_SOUND),
        inputs={'prompt': 'heavy rain on a tiled roof', 'negative': 'NEGATIVE_LADDER'},
        unit='count',
        ladder_labels=[
            ['music'],
            ['music', 'a person speaking'],
            ['music', 'a person speaking', 'thunder', 'birds chirping'],
            ['music', 'a person speaking', 'thunder', 'birds chirping', 'a dog barking', 'traffic', 'wind', 'a bell'],
            [
                'music',
                'a person speaking',
                'thunder',
                'birds chirping',
                'a dog barking',
                'traffic',
                'wind',
                'a bell',
                'footsteps',
                'a crowd',
                'singing',
                'a synthesizer',
                'applause',
                'a car horn',
                'a telephone',
                'a gunshot',
            ],
        ],
        state_note=(
            'the answer is a COUNT: the longest negative list (in terms) that still '
            'keeps every one of its terms out while the subject survives. A row with no '
            'negative-prompt field takes the transport `na` below instead. The operator '
            "decides (inverted question); CLAP's absence scores are the screen."
        ),
    ),
    _probe(
        'pd_batched_questions',
        'Prompt: questions per prompt before it drifts',
        ['pd_batched_questions'],
        [
            {'check': 'json_valid'},
            {'check': 'json_keys', 'keys': 'RUNG_KEYS'},
            {'check': 'equals_key', 'accept': 'RUNG_ANSWERS', 'per_key': True},
        ],
        cond=dict(COND_JUDGE),
        inputs={
            'audio': 'capability_tests/fixtures/audio/judge/balanced_six/',
            'task': 'Answer the first N questions about this recording. Reply with one JSON '
            'object, one key per question id, each value a single word. No prose.',
        },
        unit='count',
        ladder_questions=[
            {'q1': 'Does this recording clip? yes/no'},
            {'q1': 'Does this recording clip? yes/no', 'q2': 'Is there speech in it? yes/no'},
            {
                'q1': 'Does this recording clip? yes/no',
                'q2': 'Is there speech in it? yes/no',
                'q3': 'Is there music in it? yes/no',
                'q4': 'Is it quieter than -20 LUFS? yes/no',
            },
            {
                'q1': 'Does this recording clip? yes/no',
                'q2': 'Is there speech in it? yes/no',
                'q3': 'Is there music in it? yes/no',
                'q4': 'Is it quieter than -20 LUFS? yes/no',
                'q5': 'Is there more than one speaker? yes/no',
                'q6': 'Is there a dog barking? yes/no',
                'q7': 'Does it end in silence? yes/no',
                'q8': 'Is it mono? yes/no',
            },
        ],
        fixture_key='judge/balanced_six/',
        state_note=(
            'the answer is a COUNT: the largest rung where EVERY answer in the batch '
            "still equals the fixture's key. The fixture set is built so the true "
            'answers are half yes and half no, which is what makes drift visible rather '
            'than rewarding a model that answers all-no. Fully mechanical.'
        ),
    ),
]
