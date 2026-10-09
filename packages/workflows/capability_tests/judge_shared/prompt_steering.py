# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

from __future__ import annotations

from .settings import COND_JUDGE, COND_LONG
from .subjects import PROMPT_DIR, SUBJ_DIR
from .probes_subjects import PROBES, _subject_fixture

# ── Prompt: steering ────────────────────────────────────────────────────────
PROBES.append(
    {
        'id': 'steer_small_edit',
        'title': 'A small edit gives a small change',
        'feeds': ['pd_small_edit'],
        'inputs': {
            'task': [
                'Look at this picture. Describe the man on the left in 30 to 40 words.',
                'Look at this picture. Describe the man on the RIGHT in 30 to 40 words.',
            ],
            'image': PROMPT_DIR + '/bleed_caps.png',
            'fixture': {
                'path': PROMPT_DIR + '/bleed_caps.png',
                'generated': 'the damage_bleed fixture; nothing new is rendered',
                'key': {'left': 'wide black hat', 'right': 'bright red knitted cap'},
                'verified': False,
                'blocks': ['pd_small_edit'],
                'how_to_verify': 'the damage_bleed operator pass covers this fixture.',
            },
            'edit': 'one word changed: left -> right',
        },
        'conditions': dict(COND_LONG, repeats=3),
        'checks': [
            {'check': 'word_count', 'min': 30, 'max': 40},
            {'check': 'present', 'terms': ['red'], 'applies_to': 'the RIGHT arm'},
            {'check': 'absent', 'terms': ['red'], 'applies_to': 'the LEFT arm'},
            {
                'check': 'similarity_max',
                'to': 'the LEFT arm',
                'max': 0.85,
                'note': 'the two answers must actually differ; a model that returns the same paragraph for both has not '
                'heard the edit',
            },
            {
                'check': 'similarity_min',
                'to': 'the LEFT arm',
                'min': 0.3,
                'note': 'and they must not be unrelated — a one-word edit that rewrites everything is not steering either',
            },
        ],
        'grade': 'measured',
        'state_rule': {'yes': 0.9, 'partial': 0.7},
        'state_note': 'the column needs BOTH similarity bounds: too similar means deaf, too different means unsteerable.',
    }
)

PROBES.append(
    {
        'id': 'steer_seed_vs_prompt',
        'title': 'The question beats the sampling seed',
        'feeds': ['pd_seed_vs_prompt'],
        'inputs': {
            'task': [
                'Look at this picture. Is the hand anatomically correct? Answer yes or no, one word only.',
                'Look at this picture. Is the hand anatomically WRONG? Answer yes or no, one word only.',
            ],
            'image': [SUBJ_DIR + '/fingers_count_pos.png', SUBJ_DIR + '/fingers_count_neg.png'],
            'fixture': dict(_subject_fixture('fingers_count'), blocks=['pd_seed_vs_prompt']),
        },
        'conditions': dict(
            COND_JUDGE,
            seed=[11, 29, 71],
            note='the ONLY grid in the bank: two question polarities x two pictures x three seeds. '
            'Everything else in this bank is fixed at seed 11.',
        ),
        'checks': [
            {'check': 'identical_runs', 'note': 'per cell, across the three seeds'},
            {
                'check': 'answer_equals_fixture_key',
                'note': 'the inverted question inverts the key; a judge that answers yes to both polarities on the same '
                'picture is answering the seed, not the question',
            },
        ],
        'grade': 'measured',
        'state_rule': {'yes': 0.9, 'partial': 0.7},
        'state_note': (
            'yes when the answer is decided entirely by the wording and not at all by the seed. A judge whose '
            'verdict moves with the seed cannot be put behind a gate at any threshold.'
        ),
    }
)

PROBES.append(
    {
        'id': 'steer_fix',
        'title': 'A named fix lands, and does not break what was right',
        'feeds': ['pd_fix_lands', 'pd_fix_breaks'],
        'inputs': {
            'task': [
                'Look at this picture. Is the hand correct? Answer yes or no, one word only.',
                'Look at this picture. Is the hand correct? Count the digits: a correct hand has four fingers and '
                'one thumb, five in all. Answer yes or no, one word only.',
            ],
            'image': [
                SUBJ_DIR + '/fingers_count_pos.png',
                SUBJ_DIR + '/fingers_count_neg.png',
                SUBJ_DIR + '/hand_two_pos.png',
                SUBJ_DIR + '/hand_two_neg.png',
                SUBJ_DIR + '/hand_gripping_pos.png',
                SUBJ_DIR + '/hand_gripping_neg.png',
            ],
            'fixture': {
                'path': SUBJ_DIR + '/<subject>_pos.png and <subject>_neg.png',
                'subjects': ['fingers_count', 'hand_two', 'hand_gripping'],
                'generated': 'the three hand subject pairs from the Sees band; nothing new is rendered',
                'key': {'pos': {'answer': 'yes'}, 'neg': {'answer': 'no'}},
                'verified': False,
                'blocks': ['pd_fix_lands', 'pd_fix_breaks'],
                'how_to_verify': 'the operator pass over those three subject pairs covers this column.',
            },
            'fix': 'one sentence of counting rubric added to the question — the fix an operator would actually reach for',
        },
        'conditions': dict(COND_JUDGE, note='two arms x three pairs x three repeats'),
        'checks': [
            {
                'check': 'accuracy_delta',
                'with': 'the arm carrying the rubric',
                'without': 'the bare arm',
                'min': 0.05,
                'note': 'measured over the trials the bare arm got WRONG — that is what pd_fix_lands means',
            },
            {
                'check': 'accuracy_delta',
                'with': 'the arm carrying the rubric',
                'without': 'the bare arm',
                'min': -0.02,
                'note': 'measured over the trials the bare arm got RIGHT — that is pd_fix_breaks, and it is written yes '
                'when the fix costs nothing there',
            },
            {
                'check': 'recall_precision_min',
                'recall': 0.9,
                'precision': 0.9,
                'note': 'over the fixed arm; a fix that raises recall by wrecking precision has not landed',
            },
        ],
        'grade': 'measured',
        'state_rule': {'yes': 0.9, 'partial': 0.7},
        'state_note': (
            'the two columns are read from the SAME run, split by whether the bare arm was right. Reporting '
            'only the first is how a fix comes to be believed in; the precision check is why it cannot be.'
        ),
    }
)

PROBES.append(
    {
        'id': 'steer_reusable',
        'title': 'The question works on the next subject',
        'feeds': ['pd_reusable'],
        'inputs': {
            'task': 'Look at this picture. Is the {part} anatomically correct? A correct {part} shows {rule}. '
            'Answer yes or no, one word only.',
            'image': [
                SUBJ_DIR + '/fingers_count_pos.png',
                SUBJ_DIR + '/fingers_count_neg.png',
                SUBJ_DIR + '/feet_bare_pos.png',
                SUBJ_DIR + '/feet_bare_neg.png',
                SUBJ_DIR + '/eyes_pair_pos.png',
                SUBJ_DIR + '/eyes_pair_neg.png',
                SUBJ_DIR + '/teeth_pos.png',
                SUBJ_DIR + '/teeth_neg.png',
            ],
            'fixture': {
                'path': SUBJ_DIR + '/<subject>_pos.png and <subject>_neg.png',
                'subjects': ['fingers_count', 'feet_bare', 'eyes_pair', 'teeth'],
                'slots': {
                    'fingers_count': ('hand', 'five separate digits, four fingers and one thumb'),
                    'feet_bare': ('foot', 'five toes, one heel and one ankle'),
                    'eyes_pair': ('pair of eyes', 'two eyes, level with each other, one pupil in each'),
                    'teeth': ('mouth', 'an even row of teeth, none overlapping, none doubled'),
                },
                'generated': 'four subject pairs from the Sees band; nothing new is rendered',
                'key': {'pos': {'answer': 'yes'}, 'neg': {'answer': 'no'}},
                'verified': False,
                'blocks': ['pd_reusable'],
                'how_to_verify': 'the operator pass over those four subject pairs covers this column.',
            },
        },
        'conditions': dict(
            COND_JUDGE,
            note='ONE template, four subjects, two pictures each, three repeats. The template '
            'was written for the hand and is reused unchanged apart from its two slots.',
        ),
        'checks': [
            {
                'check': 'recall_precision_min',
                'recall': 0.9,
                'precision': 0.9,
                'note': 'per subject; the column is how many of the four hold',
            },
            {
                'check': 'same_as_key_across',
                'variants': ['fingers_count', 'feet_bare', 'eyes_pair', 'teeth'],
                'note': 'the template has to work on all four, not on the one it was written for',
            },
        ],
        'grade': 'measured',
        'state_rule': {'yes': 0.9, 'partial': 0.5},
        'state_note': (
            'yes when all four subjects pass, partial at two or three, no below. A house template that only '
            'works on the subject it was written for is not a template, and this is the column that says so.'
        ),
    }
)
