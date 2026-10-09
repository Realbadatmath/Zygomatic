# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

from __future__ import annotations

from .settings import COND_JSON, COND_JUDGE, RESOLUTION
from .subjects import PROMPT_DIR, SUBJ_DIR
from .probes_subjects import PROBES, _subject_fixture
from .prompt_damage import BASE_IMAGE

# ── Prompt: clarity needed ──────────────────────────────────────────────────
# One ladder of five rungs over the SAME picture pair, rising only in how much the question
# spells out. Four columns are read off the one ladder, so they cannot disagree with each
# other: the floor is the first rung that passes, terse_ok is whether rung 1 or 2 passed,
# detail_helps is whether accuracy was still rising at rung 5, sweet_spot is the word count
# of the first passing rung.
CLARITY_LADDER = [
    (1, 'Is this hand right?'),
    (2, 'Is the hand in this picture correct? Answer yes or no.'),
    (3, 'Look at the hand in this picture. Is it anatomically correct? Answer yes or no, one word only.'),
    (
        4,
        'Look at the hand in this picture. Count its fingers. Is it anatomically correct? '
        'Answer yes or no, one word only.',
    ),
    (
        5,
        'Look at the hand in this picture. A hand is correct when it has exactly five digits: four fingers and one '
        'thumb, each separate, none fused, none missing, none extra, and each with three visible segments. '
        'Count them. Is this hand correct? Answer yes or no, one word only.',
    ),
]

PROBES.append(
    {
        'id': 'clarity_ladder',
        'title': 'How clear the question has to be',
        'feeds': ['pd_clarity_floor', 'pd_terse_ok', 'pd_detail_helps', 'pd_sweet_spot'],
        'inputs': {
            'task': [_t for _n, _t in CLARITY_LADDER],
            'image': [SUBJ_DIR + '/fingers_count_pos.png', SUBJ_DIR + '/fingers_count_neg.png'],
            'fixture': _subject_fixture('fingers_count'),
        },
        'conditions': dict(
            COND_JUDGE,
            ladder=[_n for _n, _t in CLARITY_LADDER],
            note='five rungs x two pictures x three repeats = 30 trials; rungs are run in order and ALL '
            'five are run, because pd_detail_helps needs the top of the ladder even when rung 1 passed',
        ),
        'checks': [
            {
                'check': 'recall_precision_min',
                'recall': 0.9,
                'precision': 0.9,
                'note': 'per rung, over its own pos/neg pair; a rung passes only when both numbers hold',
            },
            {
                'check': 'accuracy_delta',
                'with': 'rung 5',
                'without': 'rung 3',
                'min': 0.05,
                'note': 'this is what pd_detail_helps reads: yes when the rubric rung is at least 5 points better than the '
                'plain rung, no when the extra words bought nothing',
            },
        ],
        'grade': 'measured',
        'state_rule': {'yes': 0.9, 'partial': 0.7},
        'state_note': (
            'pd_clarity_floor is written as the first rung that passed (text: "rung 3 — names the part and '
            'asks for one word"); pd_terse_ok is yes when rung 1 or 2 passed; pd_sweet_spot is the WORD COUNT '
            'of the first passing rung, unit count; pd_detail_helps is the rung 5 minus rung 3 delta. If no '
            'rung passes, the floor is written "none of five" and the other three are no.'
        ),
    }
)

PROSE_Q = (
    'Look at this picture and tell me, in plain sentences, whether the hand is correct, how many barrels you '
    'can see, and what the board says.'
)
TAGS_Q = (
    'image question. hand correct? yes/no. barrels: count. board: text. answer as: hand=<yes|no>, '
    'barrels=<n>, board=<text>'
)
HOUSE_Q = (
    'You are a picture judge. Answer with one JSON object and nothing else.\n'
    'Keys, exactly these three: "hand" (yes or no — is the hand anatomically correct, five separate digits), '
    '"barrels" (a number), "board" (the words on the board, exactly).\n'
    'If you cannot tell, write "cannot tell" for that key. Do not explain.'
)

PROBES.append(
    {
        'id': 'clarity_form',
        'title': 'Prose, tags or the house template',
        'feeds': ['pd_prose_ok', 'pd_structure_needed', 'pd_house_template'],
        'inputs': {
            'task': [PROSE_Q, TAGS_Q, HOUSE_Q],
            'image': PROMPT_DIR + '/form_quay.png',
            'fixture': {
                'path': PROMPT_DIR + '/form_quay.png',
                'generated': (
                    'the image bank renders: "Seventeenth-century Dutch quay, daylight, photographic, sharp '
                    'focus: a dockworker holding up one open hand palm to camera beside two tarred barrels, a '
                    'painted board reading KATTENBURG behind him." Seed 11, ' + RESOLUTION + '. One picture '
                    'carries all three answers so the three forms are asked the same thing.'
                ),
                'key': {'hand': 'yes', 'barrels': 2, 'board': 'KATTENBURG'},
                'verified': False,
                'blocks': ['pd_prose_ok', 'pd_structure_needed', 'pd_house_template'],
                'how_to_verify': (
                    'The operator opens the picture once, counts the fingers and the barrels and reads the '
                    'board, and writes the key from the render. Until then the three columns are untested '
                    'with the note "key unverified".'
                ),
            },
        },
        'conditions': dict(COND_JSON, note='three forms, same picture, same seed, three repeats each'),
        'checks': [
            {
                'check': 'equals_key',
                'note': 'all three fields must be right, whatever the form; a form that gets two of '
                'three is a failed form',
            },
            {
                'check': 'json_valid',
                'applies_to': 'the house-template form only',
                'note': 'the house form additionally has to parse, because that is what the house form is for',
            },
            {
                'check': 'accuracy_delta',
                'with': 'the house template form',
                'without': 'the prose form',
                'min': 0.05,
                'note': 'this is what pd_structure_needed reads',
            },
        ],
        'grade': 'measured',
        'state_rule': {'yes': 0.9, 'partial': 0.7},
        'state_note': (
            'pd_prose_ok is yes when the prose form alone gets all three fields right on 3/3 repeats. '
            'pd_structure_needed is yes when the tags or house form beats prose by 5 points or more. '
            'pd_house_template is yes when the house form passes AND at least one of the other two did not — '
            'that is what "reliable only through the house template" means, and a model where all three pass '
            'is written no on it, which is the good outcome.'
        ),
    }
)

PROBES.append(
    {
        'id': 'clarity_example',
        'title': 'Needs an example to obey',
        'feeds': ['pd_example_needed'],
        'inputs': {
            'task': [
                HOUSE_Q,
                HOUSE_Q + '\nHere is a worked answer for a different picture, so you can see the shape:\n'
                '{"hand": "no", "barrels": 5, "board": "VLOOIENBURG"}',
            ],
            'image': PROMPT_DIR + '/form_quay.png',
            'fixture': {
                'path': PROMPT_DIR + '/form_quay.png',
                'generated': 'the same fixture as clarity_form; nothing new is rendered',
                'key': {'hand': 'yes', 'barrels': 2, 'board': 'KATTENBURG'},
                'verified': False,
                'blocks': ['pd_example_needed'],
                'how_to_verify': 'the clarity_form operator pass covers this fixture.',
            },
            'note': "the worked example carries a DIFFERENT picture's answers on purpose, so a model that copies it is "
            'measurably wrong rather than accidentally right',
        },
        'conditions': dict(COND_JSON, note='two forms of the same question, three repeats each'),
        'checks': [
            {'check': 'json_valid'},
            {'check': 'equals_key'},
            {
                'check': 'absent',
                'terms': ['VLOOIENBURG'],
                'note': "copying the example's board text is a failed trial in both arms",
            },
            {
                'check': 'accuracy_delta',
                'with': 'the arm that carries the example',
                'without': 'the bare arm',
                'min': 0.05,
            },
        ],
        'grade': 'measured',
        'state_rule': {'yes': 0.9, 'partial': 0.7},
        'state_note': 'yes when the example buys 5 points or more; a model that is already right without it is written no, which is better.',
    }
)

PROBES.append(
    {
        'id': 'clarity_jargon',
        'title': 'Needs domain vocabulary',
        'feeds': ['pd_jargon_needed'],
        'inputs': {
            'task': [
                'Look at this picture. Is the rigging right for a seventeenth-century Dutch fluyt? '
                'Answer yes or no, one word only.',
                'Look at this picture. A fluyt carries a square course and topsail on fore and main, a lateen '
                'mizzen, and ratlines on the shrouds. Does this ship show that rig? Answer yes or no, one word only.',
            ],
            'image': [SUBJ_DIR + '/ship_rigging_pos.png', SUBJ_DIR + '/ship_rigging_neg.png'],
            'fixture': _subject_fixture('ship_rigging'),
        },
        'conditions': dict(COND_JUDGE, note='two wordings x the pos/neg pair x three repeats'),
        'checks': [
            {'check': 'recall_precision_min', 'recall': 0.9, 'precision': 0.9, 'note': 'per wording'},
            {
                'check': 'accuracy_delta',
                'with': 'the wording that spells the rig out',
                'without': 'the wording that only names the ship type',
                'min': 0.05,
            },
        ],
        'grade': 'measured',
        'state_rule': {'yes': 0.9, 'partial': 0.7},
        'state_note': (
            'yes means the model only judges the rig once the rig is described to it — useful to know before '
            'anyone asks a judge a period question in period vocabulary.'
        ),
    }
)

PROBES.append(
    {
        'id': 'clarity_asks_back',
        'title': 'Says it is unsure instead of guessing',
        'feeds': ['pd_asks_back'],
        'inputs': {
            'task': "Look at this picture. Is the third man's left hand correct? Answer yes or no, one word only, or "
            'say what you would need in order to tell.',
            'image': PROMPT_DIR + '/ambiguous_hands.png',
            'fixture': {
                'path': PROMPT_DIR + '/ambiguous_hands.png',
                'generated': (
                    'the image bank renders: "Seventeenth-century Dutch quay, daylight, photographic: three '
                    'dockworkers walking away from camera, all hands out of frame behind them." Seed 11, '
                    + RESOLUTION
                    + '. No hand is visible at all, so no yes and no no can be right.'
                ),
                'key': {
                    'answer': 'cannot tell',
                    'note': 'the question is answerable only by saying it is not answerable. Both yes and no are '
                    'inventions, and yes is the one a compliant judge gives.',
                },
                'verified': False,
                'blocks': ['pd_asks_back'],
                'how_to_verify': (
                    'The operator opens the picture once and confirms NO hand is visible. If a hand crept '
                    'into frame the fixture is rerendered, because the column measures the abstention and '
                    'nothing else.'
                ),
            },
        },
        'conditions': dict(COND_JUDGE, repeats=5),
        'checks': [
            {'check': 'abstains'},
            {
                'check': 'regex_absent',
                'pattern': r'^\s*(yes|no)\b',
                'note': 'a bare yes or no about a hand that is not in the picture is the failure',
            },
        ],
        'grade': 'measured',
        'state_rule': {'yes': 0.9, 'partial': 0.6},
        'state_note': 'five repeats, because an abstention that happens once in five is not a behaviour a gate can rely on.',
    }
)

PROBES.append(
    {
        'id': 'clarity_rubric',
        'title': 'Needs the threshold spelled out',
        'feeds': ['pd_rubric_needed'],
        'inputs': {
            'task': [
                'Look at this picture. Is the brickwork good enough to ship? Answer yes or no, one word only.',
                'Look at this picture. Brickwork ships when the courses are straight, the bond pattern is '
                'consistent across the whole wall, and no brick is smeared into its neighbour. Judge against '
                'exactly those three tests. Answer yes or no, one word only.',
            ],
            'image': [SUBJ_DIR + '/brick_wall_pos.png', SUBJ_DIR + '/brick_wall_neg.png'],
            'fixture': _subject_fixture('brick_wall'),
        },
        'conditions': dict(COND_JUDGE, note='two wordings x the pos/neg pair x three repeats'),
        'checks': [
            {'check': 'recall_precision_min', 'recall': 0.9, 'precision': 0.9, 'note': 'per wording'},
            {
                'check': 'accuracy_delta',
                'with': 'the wording carrying the three tests',
                'without': 'the bare "good enough to ship" wording',
                'min': 0.05,
            },
            {
                'check': 'operator',
                'blind': True,
                'question': 'Shown the wall and one anonymised verdict: does the verdict match the three written tests? '
                'Yes or no. A "maybe" is a no.',
                'note': 'the operator judges against the SAME rubric the model was given, so "good enough" is not decided '
                'twice by two different standards',
            },
        ],
        'grade': 'measured',
        'state_rule': {'yes': 0.9, 'partial': 0.7},
        'state_note': (
            'yes means the bare quality word is not usable and every house gate must carry its threshold in '
            'the prompt. That is the single most actionable thing this band can report.'
        ),
    }
)

PROBES.append(
    {
        'id': 'clarity_abstain',
        'title': 'Can answer "cannot tell"',
        'feeds': ['pd_abstain'],
        'inputs': {
            'task': 'Look at this picture. Is there a dog in it? Answer yes, no, or cannot tell — one of those three, '
            'nothing else.',
            'image': [PROMPT_DIR + '/abstain_visible.png', PROMPT_DIR + '/abstain_hidden.png', BASE_IMAGE],
            'fixture': {
                'path': PROMPT_DIR + '/abstain_<case>.png',
                'generated': (
                    'three cases from the image bank, seed 11, ' + RESOLUTION + ': abstain_visible — the base '
                    'quay with a dog clearly in frame (key yes); abstain_hidden — the same quay with a heavy '
                    'fog bank where the dog would be, nothing animal discernible (key cannot tell); and the '
                    'base quay itself, dogless and clear (key no).'
                ),
                'key': {
                    'abstain_visible': {'answer': 'yes'},
                    'abstain_hidden': {'answer': 'cannot tell'},
                    'base_quay': {'answer': 'no'},
                },
                'verified': False,
                'blocks': ['pd_abstain'],
                'how_to_verify': (
                    'The operator opens all three once and confirms that the hidden case really is '
                    'undecidable by eye — if the operator can tell, the model is not being asked to '
                    'abstain and the fixture is rerendered.'
                ),
            },
        },
        'conditions': dict(COND_JUDGE),
        'checks': [
            {
                'check': 'answer_equals_fixture_key',
                'note': 'three cases, three different right answers; a model that never uses the third option cannot pass',
            },
            {'check': 'abstains', 'applies_to': 'the hidden case only'},
        ],
        'grade': 'measured',
        'state_rule': {'yes': 0.9, 'partial': 0.7},
        'state_note': (
            'the clear cases are in the test so that a model which answers "cannot tell" to everything scores '
            'one of three, not three of three. An abstention is only worth having when it is selective.'
        ),
    }
)
