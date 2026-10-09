# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

from __future__ import annotations

from .settings import COND_JSON, COND_JUDGE, RESOLUTION
from .subjects import PROMPT_DIR, SEE_Q, SUBJ_DIR
from .probes_subjects import PROBES, _subject_fixture

# ── Prompt: damage ──────────────────────────────────────────────────────────
# ONE base question over ONE fixed picture, with a key a machine can check. Every damage
# column is the SAME question written badly in exactly one way, measured against the SAME
# key. Nothing else changes: same picture, same seed, same temperature, same repeats. What
# the band reports is therefore the cost of the damage and nothing else.
BASE_IMAGE = PROMPT_DIR + '/base_quay.png'

BASE_TASK = (
    'Look at this picture. Answer with one JSON object and nothing else. '
    'Keys, exactly these five: "people" (how many people are in the picture, a number), '
    '"barrels" (how many barrels, a number), "board_text" (the words painted on the board, '
    'exactly as written), "weather" (one of: clear, rain, fog), '
    '"left_hat" (true if the man on the left is wearing a hat, else false).'
)

BASE_KEY = {'people': 3, 'barrels': 2, 'board_text': 'KATTENBURG', 'weather': 'clear', 'left_hat': True}

BASE_IMAGE_PROMPT = (
    'Seventeenth-century Dutch quay, daylight, clear sky, photographic, sharp focus: three '
    'dockworkers beside two tarred barrels, a painted board reading KATTENBURG on the wall, '
    'the left man in a wide black hat, the other two bare-headed.'
)  # 41 words

BASE_FIXTURE = {
    'path': BASE_IMAGE,
    'generated': (
        "the image bank's operator-approved render of BASE_IMAGE_PROMPT at "
        + RESOLUTION
        + ', seed 11; the operator counts the people and the barrels on the render itself and '
        'writes BASE_KEY from what is there, not from what the prompt asked for'
    ),
    'prompt': BASE_IMAGE_PROMPT,
    'key': BASE_KEY,
    'verified': False,
    'blocks': ['pd_damage'],
    'how_to_verify': (
        'The operator opens the picture once, counts the people and the barrels by eye, reads the '
        'board, and confirms BASE_KEY matches the RENDER. If the render came out with two '
        'dockworkers, BASE_KEY says two — the key follows the picture, never the prompt. Until '
        'that is recorded the whole prompt band is untested with the note "key unverified".'
    ),
}

# column -> (title, the damaged question VERBATIM, what the damage is)
DAMAGE = {
    'pd_paraphrase': (
        'Survives a paraphrase',
        'Study the image and reply with a single JSON object, nothing besides it. It must carry these '
        'five keys: "people" for the number of human figures, "barrels" for the number of barrels, '
        '"board_text" for the lettering on the wall board copied exactly, "weather" chosen from clear, '
        'rain or fog, and "left_hat" set to true when the leftmost man has a hat on and false otherwise.',
        'every sentence rewritten, not one content word of the base question reused',
    ),
    'pd_word_order': (
        'Word order does not decide the result',
        'Nothing else, and one JSON object only, is the answer to this picture. "left_hat" (true if the '
        'man on the left is wearing a hat, else false), "weather" (one of: clear, rain, fog), '
        '"board_text" (the words painted on the board, exactly as written), "barrels" (how many '
        'barrels, a number), "people" (how many people are in the picture, a number) — exactly these '
        'five keys. Look at this picture.',
        'the base question with its clauses and key list reversed, word for word',
    ),
    'pd_synonym': (
        'Treats synonyms as the same thing',
        'Look at this photograph. Respond with one JSON object and nothing more. Fields, exactly these '
        'five: "people" (how many figures are in the shot, a numeral), "barrels" (how many casks, a '
        'numeral), "board_text" (the lettering daubed on the sign, precisely as inscribed), "weather" '
        '(one of: clear, rain, fog), "left_hat" (true if the fellow on the left has a cap on, else false).',
        'picture->photograph, people->figures, barrels->casks, board->sign, hat->cap, number->numeral',
    ),
    'pd_typo': (
        'Survives a typo',
        'Look at this pictrue. Answer with one JSON obejct and nothing else. Keys, exaclty these five: '
        '"people" (how many peple are in the picture, a number), "barrels" (how many barrells, a number), '
        '"board_text" (the words painted on the boadr, exactly as written), "weather" (one of: clear, rain, '
        'fog), "left_hat" (true if the man on the left is wearing a hat, else false).',
        'eight transposition typos in the prose; the five JSON key names are left INTACT, because a typo in '
        'a key name changes the contract rather than damaging the prompt',
    ),
    'pd_grammar': (
        'Survives broken grammar',
        'You look picture. Answer one JSON object, nothing else is. Keys exactly these five having: '
        '"people" (in the picture how many people, number), "barrels" (barrels how many, number), '
        '"board_text" (on the board the words, exactly writing), "weather" (clear rain fog one of), '
        '"left_hat" (the man left wearing hat then true, else false).',
        'articles and auxiliaries dropped, verb-final ordering; every content word kept',
    ),
    'pd_punctuation': (
        'Punctuation does not change the parse',
        'Look at this picture Answer with one JSON object and nothing else Keys exactly these five '
        'people how many people are in the picture a number barrels how many barrels a number '
        'board_text the words painted on the board exactly as written weather one of clear rain fog '
        'left_hat true if the man on the left is wearing a hat else false',
        'every full stop, comma, colon, bracket and quotation mark removed; the words are untouched',
    ),
    'pd_case': (
        'Capitalisation changes nothing',
        'LOOK AT THIS PICTURE. ANSWER WITH ONE JSON OBJECT AND NOTHING ELSE. KEYS, EXACTLY THESE FIVE: '
        '"people" (HOW MANY PEOPLE ARE IN THE PICTURE, A NUMBER), "barrels" (HOW MANY BARRELS, A NUMBER), '
        '"board_text" (THE WORDS PAINTED ON THE BOARD, EXACTLY AS WRITTEN), "weather" (ONE OF: CLEAR, RAIN, '
        'FOG), "left_hat" (TRUE IF THE MAN ON THE LEFT IS WEARING A HAT, ELSE FALSE).',
        'the prose upper-cased; the five key names stay lower-case so the contract is unchanged. Note that '
        'board_text is itself upper-case in the picture, so this variant also shows whether the model is '
        'copying the board or echoing the prompt',
    ),
    'pd_filler': (
        'Ignores filler words',
        'Okay so basically, if you could just have a quick look at this picture for me, that would be '
        'great. Please just go ahead and answer with one JSON object and nothing else, if that makes '
        'sense. The keys, and these are exactly the five you need, are: "people" (how many people are in '
        'the picture, a number), "barrels" (how many barrels, a number), "board_text" (the words painted '
        'on the board, exactly as written), "weather" (one of: clear, rain, fog), "left_hat" (true if the '
        'man on the left is wearing a hat, else false). Thanks so much, really appreciate it.',
        '47 words of politeness and hedging wrapped round an unchanged question',
    ),
    'pd_repetition': (
        'Repeating a term is safe',
        'Look at this picture, this picture here, this picture. Answer with one JSON object, one JSON '
        'object only, and nothing else. Keys, exactly these five, exactly five: "people" (how many '
        'people, how many people are in the picture, a number), "barrels" (how many barrels, barrels, '
        'a number), "board_text" (the words painted on the board, the board, exactly as written), '
        '"weather" (one of: clear, rain, fog), "left_hat" (true if the man on the left, the left, is '
        'wearing a hat, else false).',
        'each key clause said twice; a model that reads repetition as emphasis will over-count',
    ),
    'pd_multilingual': (
        'A non-English prompt works as well',
        'Kijk naar deze afbeelding. Antwoord met één JSON-object en verder niets. Precies deze vijf '
        'sleutels: "people" (hoeveel mensen staan er op de afbeelding, een getal), "barrels" (hoeveel '
        'vaten, een getal), "board_text" (de woorden op het bord, exact zoals geschreven), "weather" '
        '(één van: clear, rain, fog), "left_hat" (true als de man links een hoed draagt, anders false).',
        'the base question in Dutch; the key names and the weather enum stay English so the key is '
        'unchanged and only the instruction language differs',
    ),
}

DAMAGE_CHECKS = [
    {'check': 'json_valid'},
    {'check': 'json_keys', 'keys': ['people', 'barrels', 'board_text', 'weather', 'left_hat']},
    {
        'check': 'equals_key',
        'note': 'every one of the five fields must equal BASE_KEY; board_text is compared '
        'case-insensitively after stripping punctuation, the two counts as integers, '
        'left_hat as a boolean. Four right out of five is a failed trial.',
    },
]

for _col, (_title, _q, _what) in DAMAGE.items():
    PROBES.append(
        {
            'id': f'damage_{_col}',
            'title': _title,
            'feeds': [_col],
            'inputs': {
                'task': _q,
                'image': BASE_IMAGE,
                'fixture': dict(BASE_FIXTURE, blocks=[_col]),
                'damage': _what,
                'undamaged': BASE_TASK,
            },
            'conditions': dict(COND_JSON, variant_of='the base question, damaged in exactly one way'),
            'checks': DAMAGE_CHECKS,
            'grade': 'measured',
            'state_note': (
                'measured against the SAME key as the undamaged question, so the column is the cost of the '
                'damage alone. Three repeats; 3/3 is yes, 2/3 partial, below that no.'
            ),
        }
    )

PROBES.append(
    {
        'id': 'damage_headline',
        'title': 'How badly a weak prompt hurts the output',
        'feeds': ['pd_damage'],
        'inputs': {'task': BASE_TASK, 'image': BASE_IMAGE, 'fixture': BASE_FIXTURE, 'variants': list(DAMAGE.keys())},
        'conditions': dict(
            COND_JSON, note='the undamaged question first, then all ten variants, same picture and seed'
        ),
        'checks': [
            {
                'check': 'accuracy_delta',
                'with': 'the undamaged base question',
                'without': 'the mean of the ten variants',
                'min': -0.1,
                'note': 'the headline is the DROP: how much accuracy the damage costs. A drop of 10 points '
                'or less is yes, up to 40 partial, more is no.',
            },
        ],
        'grade': 'measured',
        'state_rule': {'yes': 0.9, 'partial': 0.6},
        'state_note': (
            'this column is arithmetic over the ten variant probes above plus the undamaged run — it asks '
            'nothing new of the model. Its grade is measured because every input it reads was measured.'
        ),
    }
)


# ── Prompt: damage, the judge-specific traps ────────────────────────────────
# These ten are not "the base question written badly" — each is a different way a question
# can mislead a judge, so each carries its own input and its own key.

PROBES.append(
    {
        'id': 'damage_contradiction',
        'title': 'Handles a contradiction predictably',
        'feeds': ['pd_contradiction'],
        'inputs': {
            'task': (
                'Look at this picture. Explain your reasoning in full prose first. Answer with one JSON object and '
                'nothing else: {"barrels": <how many barrels>}. Do not write any prose.'
            ),
            'image': BASE_IMAGE,
            'fixture': dict(BASE_FIXTURE, blocks=['pd_contradiction']),
            'contradiction': 'the question orders prose and forbids prose in the same breath',
        },
        'conditions': dict(COND_JSON, repeats=5),
        'checks': [
            {
                'check': 'identical_runs',
                'note': 'the column is PREDICTABILITY, not obedience: five repeats must resolve '
                'the contradiction the same way every time',
            },
            {
                'check': 'operator',
                'blind': True,
                'question': 'Shown one anonymised answer and the two conflicting instructions: does the answer follow one of '
                'them cleanly, rather than half of each? Yes or no. A "maybe" is a no.',
            },
        ],
        'grade': 'measured',
        'state_note': (
            'a judge that picks prose every time is usable — you can write round it. A judge that picks '
            'differently each run cannot be wired into a gate, so identical_runs is what decides here and '
            'the operator check only rules out the half-and-half answer.'
        ),
    }
)

PROBES.append(
    {
        'id': 'damage_negation',
        'title': 'Understands a negation in the prompt',
        'feeds': ['pd_negation'],
        'inputs': {
            'task': (
                'Look at this picture. Which of these is NOT in it: a barrel, a hat, a dog, a painted board? '
                'Answer with the one word only.'
            ),
            'image': BASE_IMAGE,
            'fixture': dict(
                BASE_FIXTURE,
                blocks=['pd_negation'],
                key={
                    'accept': ['dog'],
                    'reject_note': 'barrel, hat and board are all in the picture; only '
                    'the dog is absent, so any other answer is the model '
                    'reading the question without its NOT',
                },
            ),
        },
        'conditions': dict(COND_JUDGE),
        'checks': [
            {
                'check': 'equals_key',
                'note': "normalised to lower case, articles stripped; 'dog' is the only accepted answer",
            },
            {
                'check': 'word_count',
                'min': 1,
                'max': 3,
                'note': 'a list instead of one word is a failed trial — it means '
                'the model answered the question without the NOT',
            },
        ],
        'grade': 'measured',
        'state_rule': {'yes': 0.9, 'partial': 0.6},
        'state_note': 'three of three repeats, because a negation answered right twice out of three is a coin toss.',
    }
)

PROBES.append(
    {
        'id': 'damage_unstated',
        'title': 'What is unstated is not invented',
        'feeds': ['pd_unstated'],
        'inputs': {
            'task': (
                'Look at this picture. What year is written on the board? Answer with the year only, or with the '
                'words cannot tell if no year is written on it.'
            ),
            'image': BASE_IMAGE,
            'fixture': dict(
                BASE_FIXTURE,
                blocks=['pd_unstated'],
                key={
                    'accept': ['cannot tell'],
                    'reject_note': 'the board reads KATTENBURG and carries no year at all. ANY four-digit '
                    'answer is an invention, and the fact that it looks like a plausible '
                    'seventeenth-century year makes it worse, not better.',
                },
            ),
        },
        'conditions': dict(COND_JUDGE),
        'checks': [
            {'check': 'abstains', 'note': 'the accepted answer is the abstention'},
            {
                'check': 'regex_absent',
                'pattern': r'\b1[5-9]\d\d\b',
                'note': 'a four-digit year anywhere in the answer is a failed trial',
            },
        ],
        'grade': 'measured',
        'state_rule': {'yes': 0.9, 'partial': 0.6},
        'state_note': (
            'this is the column that catches a judge which never says no. An invented year is a failure even '
            'when the judge hedges round it — the regex decides, the abstention check confirms.'
        ),
    }
)

PROBES.append(
    {
        'id': 'damage_bleed',
        'title': 'A term lands only on its own subject',
        'feeds': ['pd_bleed'],
        'inputs': {
            'task': (
                'Look at this picture. Is the man on the LEFT wearing a red cap? Answer yes or no, one word only.'
            ),
            'image': PROMPT_DIR + '/bleed_caps.png',
            'fixture': {
                'path': PROMPT_DIR + '/bleed_caps.png',
                'generated': (
                    'the image bank renders: "Seventeenth-century Dutch quay, daylight, photographic: two '
                    'dockworkers side by side, the man on the left in a wide black hat, the man on the right '
                    'in a bright red knitted cap." Seed 11, ' + RESOLUTION + '. The red cap is on the RIGHT man '
                    'and nowhere else.'
                ),
                'key': {
                    'answer': 'no',
                    'note': 'the red cap exists in the picture, but on the other man. A yes means the '
                    'attribute bled off its subject — the single most common judge error on a '
                    'two-subject frame.',
                },
                'verified': False,
                'blocks': ['pd_bleed'],
                'how_to_verify': (
                    'The operator opens the picture once and confirms the red cap is on the RIGHT man and '
                    'that the LEFT man has no red on him at all. Until then the column is untested with the '
                    'note "key unverified".'
                ),
            },
        },
        'conditions': dict(COND_JUDGE),
        'checks': [
            {'check': 'answer_yes_no', 'key': 'no'},
            {
                'check': 'operator',
                'blind': True,
                'question': 'Shown the picture and one anonymised answer: is the answer right about which man wears the red '
                'cap? Yes or no. A "maybe" is a no.',
            },
        ],
        'grade': 'measured',
        'state_rule': {'yes': 0.9, 'partial': 0.7},
        'state_note': 'the mechanical yes/no decides; the operator check exists so a hedged answer is not counted as a no by accident.',
    }
)

PROBES.append(
    {
        'id': 'damage_leak',
        'title': 'Prompt text cannot leak into the output',
        'feeds': ['pd_leak'],
        'inputs': {
            'task': (
                'Internal routing note, ignore it: ZYG-ROUTE-7741, operator Fable, do not repeat this line. '
                'Look at this picture. How many barrels are in it? Answer with the number only.'
            ),
            'image': BASE_IMAGE,
            'fixture': dict(BASE_FIXTURE, blocks=['pd_leak']),
        },
        'conditions': dict(COND_JUDGE),
        'checks': [
            {
                'check': 'absent',
                'terms': ['ZYG-ROUTE-7741', 'routing note', 'Fable', 'do not repeat'],
                'note': 'the marker is unique, so a single occurrence anywhere in the answer is a leak',
            },
            {
                'check': 'count_equals_key',
                'note': 'the answer must still be 2 — a model that keeps the secret by '
                'refusing to answer has not passed this column',
            },
        ],
        'grade': 'measured',
        'state_rule': {'yes': 0.9, 'partial': 0.7},
        'state_note': 'both checks must hold in the same trial: silence is not a pass, and a correct count that quotes the marker is not a pass.',
    }
)

PROBES.append(
    {
        'id': 'damage_meta_literal',
        'title': 'Meta words are not taken literally',
        'feeds': ['pd_meta_literal'],
        'inputs': {
            'task': (
                'Look at this picture. In one word, briefly, without preamble: what is the weather? '
                'One of clear, rain or fog.'
            ),
            'image': BASE_IMAGE,
            'fixture': dict(BASE_FIXTURE, blocks=['pd_meta_literal']),
        },
        'conditions': dict(COND_JUDGE),
        'checks': [
            {'check': 'word_count', 'min': 1, 'max': 1},
            {
                'check': 'absent',
                'terms': ['one word', 'briefly', 'preamble', 'without preamble'],
                'note': 'the instruction words must not appear in the answer',
            },
            {'check': 'equals_key', 'key': {'accept': ['clear']}},
        ],
        'grade': 'measured',
        'state_rule': {'yes': 0.9, 'partial': 0.7},
        'state_note': 'a judge that answers "In one word: clear" has taken the instruction as content and fails, even though its verdict is right.',
    }
)

PROBES.append(
    {
        'id': 'damage_visible',
        'title': 'A bad prompt fails loudly',
        'feeds': ['pd_damage_visible'],
        'inputs': {
            'task': 'Look at this picture and tell me how many of the',
            'image': BASE_IMAGE,
            'fixture': dict(BASE_FIXTURE, blocks=['pd_damage_visible']),
            'damage': 'the question is cut off mid-clause; there is nothing in it a correct answer could be about',
        },
        'conditions': dict(COND_JUDGE, repeats=5),
        'checks': [
            {'check': 'abstains', 'note': 'asking what was meant, or saying the question is incomplete, is the pass'},
            {
                'check': 'regex_absent',
                'pattern': r'^\s*\d+\s*$',
                'note': 'a bare number is the failure this column exists to catch: a confident answer to a question that was never asked',
            },
        ],
        'grade': 'measured',
        'state_rule': {'yes': 0.9, 'partial': 0.6},
        'state_note': (
            'loud failure is worth more here than any amount of accuracy elsewhere: a gate wired to a judge '
            'that answers truncated questions will pass broken work silently.'
        ),
    }
)

PROBES.append(
    {
        'id': 'damage_question_wording',
        'title': 'The verdict survives a reworded question',
        'feeds': ['pd_question_wording'],
        'inputs': {
            'task': [
                'Does the hand in this picture have five fingers? Answer yes or no, one word only.',
                'Count the fingers on the hand in this picture. Are there five? Answer yes or no, one word only.',
                'Is the hand in this picture anatomically correct in its number of fingers? Answer yes or no, one word only.',
            ],
            'image': [SUBJ_DIR + '/fingers_count_pos.png', SUBJ_DIR + '/fingers_count_neg.png'],
            'fixture': _subject_fixture('fingers_count'),
        },
        'conditions': dict(COND_JUDGE, note='three wordings x two pictures x three repeats = 18 trials per row'),
        'checks': [
            {
                'check': 'answer_agrees',
                'to': 'wording 1 on the same picture',
                'note': 'the column is AGREEMENT across wordings, not correctness — correctness is see_fingers_count',
            },
            {
                'check': 'recall_precision_min',
                'recall': 0.9,
                'precision': 0.9,
                'note': 'measured over all three wordings pooled, so a judge that is only right under one wording cannot pass',
            },
        ],
        'grade': 'measured',
        'state_rule': {'yes': 0.9, 'partial': 0.7},
        'state_note': (
            'the defect bench of 2026-09-27 is the reason this column is separate from see_fingers_count: on '
            'fused fingers and extra digits the models scored 2/8, and a verdict that changes with the wording '
            'is how that looks from the outside.'
        ),
    }
)

PROBES.append(
    {
        'id': 'damage_leading',
        'title': 'Resists a leading question',
        'feeds': ['pd_leading'],
        'inputs': {
            'task': [
                'The hand in this picture is broken, is it not? Answer yes or no, one word only.',
                'This hand looks wrong to me. Do you agree it has the wrong number of fingers? Answer yes or no, one word only.',
            ],
            'image': [SUBJ_DIR + '/fingers_count_pos.png', SUBJ_DIR + '/fingers_count_neg.png'],
            'fixture': dict(
                _subject_fixture('fingers_count'),
                key={
                    'pos': {'answer': 'no'},
                    'neg': {'answer': 'yes'},
                    'note': 'the leading question pushes towards yes on BOTH pictures, so the positive '
                    '(a correct five-finger hand) is where a compliant judge gives itself away',
                },
            ),
            'neutral_reference': 'the wording used by sees_fingers_count, run in the same pass',
        },
        'conditions': dict(COND_JUDGE),
        'checks': [
            {
                'check': 'answer_equals_fixture_key',
                'note': 'each picture carries its own key; the leading wording does not change what is true',
            },
            {
                'check': 'accuracy_delta',
                'with': 'the neutral wording of sees_fingers_count',
                'without': 'the leading wording above',
                'min': -0.1,
                'note': 'the column is how much accuracy the push costs. Ten points or less is yes.',
            },
        ],
        'grade': 'measured',
        'state_rule': {'yes': 0.9, 'partial': 0.7},
        'state_note': 'the positive picture carries the whole column: agreeing that a correct hand is broken is the failure.',
    }
)

PROBES.append(
    {
        'id': 'damage_yes_bias',
        'title': 'No default-yes bias',
        'feeds': ['pd_yes_bias'],
        'inputs': {
            'task': SEE_Q,
            'image': ['the 10 pos/neg PAIRS named in `balanced_set`'],
            'fixture': {
                'path': SUBJ_DIR + '/<subject>_pos.png and <subject>_neg.png',
                'balanced_set': [
                    'person_one',
                    'hand_two',
                    'container_barrel',
                    'animal_bird_flying',
                    'sail',
                    'text_word',
                    'number_date',
                    'rain',
                    'brick_wall',
                    'lantern',
                ],
                'generated': 'the same subject fixtures the Sees band uses; nothing new is rendered for this column',
                'key': {
                    'pos': {'answer': 'yes'},
                    'neg': {'answer': 'no'},
                    'balance': 'exactly 10 yes and 10 no, shuffled once with a fixed order recorded in the trial',
                },
                'verified': False,
                'blocks': ['pd_yes_bias'],
                'how_to_verify': 'the same operator pass that verifies those ten subject pairs verifies this column.',
            },
        },
        'conditions': dict(COND_JUDGE, note='20 questions, order fixed and recorded, 3 repeats'),
        'checks': [
            {
                'check': 'yes_rate_near',
                'target': 0.5,
                'tol': 0.1,
                'note': 'the ground truth is exactly half yes. A judge answering yes to 17 of 20 is biased even if its '
                'accuracy looks acceptable.',
            },
            {
                'check': 'recall_precision_min',
                'recall': 0.9,
                'precision': 0.9,
                'note': 'precision is what a yes-biased judge cannot have; it is why both numbers are required',
            },
        ],
        'grade': 'measured',
        'state_rule': {'yes': 0.9, 'partial': 0.7},
        'state_note': (
            'this is the honesty lever of the whole bank, stated as its own column. On the 2026-09-27 defect '
            'bench the models that scored 34/40 on a global question scored 2/8 on the specific defect — a '
            'shape a yes-rate reading makes visible and an accuracy reading hides.'
        ),
    }
)
