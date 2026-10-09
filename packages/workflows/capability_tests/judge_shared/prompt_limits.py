# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

from __future__ import annotations

from .settings import COND_JSON, COND_JUDGE, COND_LONG, RESOLUTION
from .subjects import LADDER_DIR, PROMPT_DIR
from .probes_subjects import PROBES
from .probes_ladders import LADDER_VERIFY
from .prompt_damage import BASE_FIXTURE, BASE_IMAGE, BASE_TASK

# ── Prompt: limits ──────────────────────────────────────────────────────────
# Two ladders and four single trials. A limit is only ever read as the LAST rung that
# passed before the first failure; nothing here is a yes/no dressed up as a number.
LENGTH_RUNGS = [50, 150, 400, 1000, 2500, 6000]

PROBES.append(
    {
        'id': 'limits_length',
        'title': 'How long the question may be',
        'feeds': ['pd_max_hard', 'pd_max_soft', 'pd_max_words', 'pd_truncation_loud'],
        'inputs': {
            'task': BASE_TASK,
            'image': BASE_IMAGE,
            'fixture': dict(BASE_FIXTURE, blocks=['pd_max_hard', 'pd_max_soft', 'pd_max_words', 'pd_truncation_loud']),
            'padding': (
                'the base question, then N words of 1671 harbour-regulation prose taken from the fixture file '
                'capability_tests/fixtures/judge/prompt/padding.txt, then the base question repeated verbatim. '
                'The question therefore appears at BOTH ends, so a model that reads only the head or only the '
                'tail can still answer and the ladder measures capacity, not attention position.'
            ),
            'probe_term': (
                'one extra key, "lantern" (true if a lantern hangs on the wall, else false), is planted in '
                'the MIDDLE of the padding. It is the soft-limit tell: the rung where "lantern" stops '
                'appearing in the answer is where terms begin to drop, long before anything errors.'
            ),
        },
        'conditions': dict(
            COND_JSON,
            ladder=LENGTH_RUNGS,
            unit='tokens',
            note="rungs are words of padding; the trial records the transport's own token count so "
            'pd_max_hard and pd_max_soft can be written in tokens and pd_max_words in words',
        ),
        'checks': [
            {'check': 'json_valid'},
            {'check': 'json_keys', 'keys': ['people', 'barrels', 'board_text', 'weather', 'left_hat', 'lantern']},
            {'check': 'equals_key', 'note': 'the five base fields plus lantern, against the verified key'},
            {
                'check': 'operator',
                'blind': True,
                'question': 'Shown the transport error text from the first rung that failed: does it name the length as the '
                'reason, in words an operator could act on? Yes or no. A "maybe" is a no.',
                'note': 'this is what pd_truncation_loud reads; a rung that silently returns a short answer scores no here '
                'even though nothing crashed',
            },
        ],
        'grade': 'measured',
        'state_rule': {'yes': 0.9, 'partial': 0.7},
        'state_note': (
            'pd_max_hard is the token count of the last rung that returned anything at all. pd_max_soft is the '
            'token count of the last rung where "lantern" was still answered — the two are usually far apart '
            'and the gap is the whole point of having both. pd_max_words is the same figure in words. '
            'pd_truncation_loud is the operator reading above, and is written no when the transport truncated '
            'without saying so.'
        ),
    }
)

PROBES.append(
    {
        'id': 'limits_min',
        'title': 'Shortest question that still steers',
        'feeds': ['pd_min_len'],
        'inputs': {
            'task': [
                'barrels?',
                'how many barrels?',
                'How many barrels are in this picture?',
                'How many barrels are in this picture? Answer with the number only.',
            ],
            'image': BASE_IMAGE,
            'fixture': dict(BASE_FIXTURE, blocks=['pd_min_len']),
        },
        'conditions': dict(
            COND_JUDGE,
            ladder=[1, 3, 7, 11],
            unit='count',
            note='four rungs, ascending by word count; the ladder runs DOWNWARDS from the full wording '
            'and stops at the first rung that fails',
        ),
        'checks': [
            {'check': 'count_equals_key', 'note': 'the answer must be 2 at every rung it is credited with'},
            {
                'check': 'word_count',
                'min': 1,
                'max': 6,
                'note': 'a rung that answers correctly inside a paragraph has not steered; the short question has to buy '
                'the short answer too',
            },
        ],
        'grade': 'measured',
        'state_rule': {'yes': 0.9, 'partial': 0.7},
        'state_note': 'pd_min_len is the word count of the SHORTEST rung that passed both checks on 3/3 repeats, unit count.',
    }
)

THINGS_RUNGS = [2, 4, 6, 9, 12, 16]

PROBES.append(
    {
        'id': 'limits_things',
        'title': 'Distinct things, subjects and attributes held at once',
        'feeds': ['pd_unique_things', 'pd_unique_subjects', 'pd_attrs_per_thing'],
        'inputs': {
            'task': (
                'Look at this picture. Answer with one JSON object and nothing else: a key for each thing named in '
                'the question below, whose value is a JSON object of the attributes asked for that thing. '
                'Ask nothing back, answer only what is asked.'
            ),
            'image': LADDER_DIR + '/things_<n>.png',
            'fixture': {
                'path': LADDER_DIR + '/things_<n>.png',
                'rungs': THINGS_RUNGS,
                'generated': (
                    'the image bank renders N distinct named props laid out on one plain table, no overlap, '
                    'one of each, seed 11, ' + RESOLUTION + '. Each prop carries TWO fixed attributes '
                    '(colour and material) recorded in the key. The same render serves all three columns: '
                    'things = the props, subjects = the three NAMED sitters behind the table in the '
                    'subjects_<n> variant, attributes = the per-prop attribute count asked for.'
                ),
                'key': {str(_n): {'things': _n, 'attrs': 2} for _n in THINGS_RUNGS},
                'verified': False,
                'blocks': ['pd_unique_things', 'pd_unique_subjects', 'pd_attrs_per_thing'],
                'how_to_verify': LADDER_VERIFY,
            },
        },
        'conditions': dict(
            COND_JSON,
            ladder=THINGS_RUNGS,
            unit='count',
            note='three arms over the same ladder: things only, three named subjects holding the things, '
            'and 1/2/3/4 attributes per thing at a fixed 6 things',
        ),
        'checks': [
            {'check': 'json_valid'},
            {
                'check': 'json_schema',
                'schema': 'an object with exactly `things` keys, each an object with exactly '
                '`attrs` keys, all values strings',
            },
            {
                'check': 'equals_key',
                'note': 'every attribute must match the key; one wrong colour fails the rung, '
                'because an attribute bound to the wrong thing is the failure this measures',
            },
        ],
        'grade': 'measured',
        'state_rule': {'yes': 0.9, 'partial': 0.7},
        'state_note': (
            'pd_unique_things is the last things-rung that passed; pd_unique_subjects the last rung where all '
            'three named sitters kept their own things; pd_attrs_per_thing the highest attribute count that '
            'stayed bound at six things. All three unit count.'
        ),
    }
)

INSTR_RUNGS = [1, 2, 4, 6, 9]

PROBES.append(
    {
        'id': 'limits_instructions',
        'title': 'Instructions and hard constraints obeyed at once',
        'feeds': ['pd_instructions', 'pd_constraints'],
        'inputs': {
            'task': (
                'Look at this picture and describe it. Obey every instruction below.\n'
                '1. Answer in English.\n'
                '2. Write between 40 and 60 words.\n'
                '3. Do not begin with the word "The".\n'
                '4. Name the number of barrels as a digit.\n'
                '5. Do not use the word "image" or the word "picture".\n'
                '6. Write one paragraph, no line breaks.\n'
                '7. Name the weather.\n'
                '8. Do not mention the board.\n'
                '9. End with the word "quay".'
            ),
            'image': BASE_IMAGE,
            'fixture': dict(BASE_FIXTURE, blocks=['pd_instructions', 'pd_constraints']),
        },
        'conditions': dict(
            COND_LONG,
            ladder=INSTR_RUNGS,
            unit='count',
            note='rung N gives the first N instructions, in the order above; every instruction is '
            'mechanically checkable, so nothing here needs an opinion',
        ),
        'checks': [
            {'check': 'language', 'lang': 'en', 'min': 0.6},
            {'check': 'word_count', 'min': 40, 'max': 60},
            {'check': 'starts_clean', 'banned': ['The']},
            {'check': 'regex_present', 'pattern': r'\b2\b'},
            {'check': 'absent', 'terms': ['image', 'picture']},
            {'check': 'line_count', 'min': 1, 'max': 1},
            {'check': 'present_any', 'terms': ['clear', 'cloudless', 'bright', 'sunny']},
            {'check': 'absent', 'terms': ['board', 'sign', 'KATTENBURG']},
            {
                'check': 'ends_clean',
                'banned': ['.', '!', '?'],
                'note': 'instruction 9 is read as: the last word is "quay"; trailing punctuation is stripped first',
            },
        ],
        'grade': 'measured',
        'state_rule': {'yes': 0.9, 'partial': 0.7},
        'state_note': (
            'pd_instructions is the last rung where ALL of its instructions held on 3/3 repeats. '
            'pd_constraints is the same ladder read over the three NEGATIVE instructions only (3, 5, 8) — '
            'a prohibition is harder than a request and is worth its own number.'
        ),
    }
)

PROBES.append(
    {
        'id': 'limits_order',
        'title': 'Which end of the question wins',
        'feeds': ['pd_order_wins'],
        'inputs': {
            'task': [
                'Answer in Dutch. Look at this picture. How many barrels are in it? Answer in English.',
                'Answer in English. Look at this picture. How many barrels are in it? Answer in Dutch.',
            ],
            'image': BASE_IMAGE,
            'fixture': dict(BASE_FIXTURE, blocks=['pd_order_wins']),
            'note': 'the two arms are the same conflict with the ends swapped, so the answer cannot be a preference for '
            'either language',
        },
        'conditions': dict(
            COND_JUDGE,
            max_tokens=40,
            note='the answer is asked as a short sentence, not a bare numeral, so the language is readable',
        ),
        'checks': [
            {
                'check': 'language',
                'lang': 'nl',
                'min': 0.6,
                'applies_to': 'whichever arm ends in Dutch, if the tail wins',
            },
            {
                'check': 'language',
                'lang': 'en',
                'min': 0.6,
                'applies_to': 'whichever arm ends in English, if the tail wins',
            },
            {
                'check': 'count_equals_key',
                'note': 'the count must still be 2 in both arms; a model that obeys the '
                'language and loses the answer has not passed',
            },
        ],
        'grade': 'measured',
        'state_rule': {'yes': 0.9, 'partial': 0.7},
        'state_note': (
            'written as text: "tail" when both arms follow the last instruction, "head" when both follow the '
            'first, "unstable" when the two arms disagree. Unstable is the only bad answer — head and tail '
            'are both usable once you know which.'
        ),
    }
)

PROBES.append(
    {
        'id': 'limits_exclusions',
        'title': 'How long an exclusion list still holds',
        'feeds': ['pd_negative_len'],
        'inputs': {
            'task': (
                'Look at this picture. List every object you can see, as short nouns separated by commas, nothing '
                'else. Do not list any of the following, even if you can see it: {excluded}'
            ),
            'image': PROMPT_DIR + '/form_quay.png',
            'fixture': {
                'path': PROMPT_DIR + '/form_quay.png',
                'generated': 'the clarity_form fixture; the exclusion list names things that ARE in it',
                'key': {
                    'excluded': [
                        'barrel',
                        'hand',
                        'board',
                        'rope',
                        'stone',
                        'water',
                        'sky',
                        'coat',
                        'hat',
                        'shadow',
                        'plank',
                        'wall',
                    ],
                    'note': 'every excluded term is genuinely present, so ignoring the list is measurable. '
                    'Rung N uses the first N terms.',
                },
                'verified': False,
                'blocks': ['pd_negative_len'],
                'how_to_verify': (
                    'The operator confirms once that all twelve excluded things really are in the picture. '
                    'An exclusion for something absent measures nothing.'
                ),
            },
        },
        'conditions': dict(COND_JUDGE, ladder=[1, 2, 4, 6, 9, 12], unit='count', max_tokens=200),
        'checks': [
            {
                'check': 'absent',
                'terms': "the rung's excluded terms",
                'note': 'one excluded noun in the list fails the rung',
            },
            {
                'check': 'word_count',
                'min': 3,
                'max': 120,
                'note': 'an empty answer is not obedience; something must still be listed',
            },
        ],
        'grade': 'measured',
        'state_rule': {'yes': 0.9, 'partial': 0.7},
        'state_note': 'pd_negative_len is the last rung where every excluded term stayed out on 3/3 repeats, unit count.',
    }
)

PROBES.append(
    {
        'id': 'limits_batched',
        'title': 'Questions per prompt before the answers drift',
        'feeds': ['pd_batched_questions'],
        'inputs': {
            'task': (
                'Answer each numbered question below with yes or no, one per line, in the order asked, nothing '
                'else. {questions}'
            ),
            'image': BASE_IMAGE,
            'fixture': {
                'path': PROMPT_DIR + '/batched_questions.json',
                'generated': (
                    'twenty yes/no questions about the base quay picture, ten with key yes and ten with key '
                    'no, written by the operator against the RENDER and stored in this JSON alongside their '
                    'keys and their fixed order'
                ),
                'key': {'balance': '10 yes, 10 no', 'order': 'fixed and recorded'},
                'verified': False,
                'blocks': ['pd_batched_questions'],
                'how_to_verify': 'the operator answers all twenty by eye once and stores those answers as the key.',
            },
        },
        'conditions': dict(
            COND_JSON,
            ladder=[1, 3, 5, 10, 20],
            unit='count',
            max_tokens=400,
            note='the SAME questions are also asked one at a time in the same pass; that run is the '
            'reference this column is measured against',
        ),
        'checks': [
            {'check': 'answers_counted', 'note': 'n is the rung; a short or over-long list fails the rung outright'},
            {
                'check': 'agreement_min',
                'min': 0.9,
                'note': 'batched answers against the one-at-a-time answers for the same questions. This column is DRIFT, '
                'not accuracy — cap_questions is the accuracy reading and the two are deliberately separate.',
            },
            {
                'check': 'yes_rate_near',
                'target': 0.5,
                'tol': 0.15,
                'note': 'a long batch is where a tired judge starts answering yes down the page',
            },
        ],
        'grade': 'measured',
        'state_rule': {'yes': 0.9, 'partial': 0.7},
        'state_note': 'the last rung where all three checks held; unit count.',
    }
)
