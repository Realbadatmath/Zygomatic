# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""image_shared.probes — the subject checks, the probe helpers, and the prompt-damage ladder."""

from __future__ import annotations

from capability_tests.image_shared.conditions import COND_RENDER, SUBJECT_FIXTURES
from capability_tests.image_shared.subjects import SUBJECTS

# The mechanical check beside the operator, where a detector for the subject exists. A subject
# absent from this table is judged by the operator alone and its probe says so.
SUBJECT_CHECKS = {
    'render_person_one': [{'check': 'detector_count', 'class': 'person', 'count': 1}],
    'render_person_two': [{'check': 'detector_count', 'class': 'person', 'count': 2}],
    'render_person_three': [{'check': 'detector_count', 'class': 'person', 'count': 3}],
    'render_person_group': [{'check': 'detector_count', 'class': 'person', 'count': 5}],
    'render_person_crowd': [{'check': 'detector_count', 'class': 'person', 'min': 20}],
    'render_child': [{'check': 'detector_count', 'class': 'person', 'count': 1}],
    'render_infant': [{'check': 'detector_count', 'class': 'face', 'count': 2}],
    'render_teen': [{'check': 'detector_count', 'class': 'person', 'count': 1}],
    'render_elderly': [{'check': 'detector_count', 'class': 'person', 'count': 1}],
    'render_person_back': [
        {'check': 'detector_count', 'class': 'person', 'count': 1},
        {'check': 'detector_count', 'class': 'face', 'count': 0},
    ],
    'render_person_distant': [{'check': 'detector_count', 'class': 'person', 'count': 1}],
    'render_person_partial': [{'check': 'detector_count', 'class': 'person', 'count': 1}],
    'render_face_front': [{'check': 'detector_count', 'class': 'face', 'count': 1}],
    'render_face_profile': [{'check': 'detector_count', 'class': 'face', 'count': 1}],
    'render_face_three_quarter': [{'check': 'detector_count', 'class': 'face', 'count': 1}],
    'render_eyes_pair': [{'check': 'detector_count', 'class': 'face', 'count': 1}],
    'render_gaze': [{'check': 'detector_count', 'class': 'face', 'count': 1}],
    'render_teeth': [{'check': 'detector_count', 'class': 'face', 'count': 1}],
    'render_ears': [{'check': 'open_vocab_count', 'query': 'human ear', 'min_score': 0.3, 'count': 1}],
    'render_beard': [{'check': 'detector_count', 'class': 'face', 'count': 1}],
    'render_scar': [{'check': 'detector_count', 'class': 'face', 'count': 1}],
    'render_hand_one': [{'check': 'hand_landmarks', 'hands': 1, 'min_tip_px': 12}],
    'render_hand_two': [{'check': 'hand_landmarks', 'hands': 2, 'min_tip_px': 12}],
    'render_hand_holding': [
        {'check': 'hand_landmarks', 'hands': 1, 'min_tip_px': 12},
        {'check': 'open_vocab_present', 'terms': ['key'], 'min_score': 0.3},
    ],
    'render_hand_gripping': [
        {'check': 'hand_landmarks', 'hands': 1, 'min_tip_px': 12},
        {'check': 'open_vocab_present', 'terms': ['hammer'], 'min_score': 0.3},
    ],
    'render_fingers_count': [{'check': 'hand_landmarks', 'hands': 1, 'min_tip_px': 16}],
    'render_feet_bare': [{'check': 'open_vocab_count', 'query': 'bare human foot', 'min_score': 0.3, 'count': 2}],
    'render_feet_shoes': [{'check': 'open_vocab_count', 'query': 'leather shoe', 'min_score': 0.3, 'count': 2}],
    'render_footwear_period': [{'check': 'open_vocab_count', 'query': 'leather shoe', 'min_score': 0.3, 'count': 2}],
    'render_hat': [{'check': 'open_vocab_count', 'query': 'wide brimmed hat', 'min_score': 0.3, 'count': 1}],
    'render_animal_dog': [{'check': 'detector_count', 'class': 'dog', 'count': 1}],
    'render_animal_cat': [{'check': 'detector_count', 'class': 'cat', 'count': 1}],
    'render_animal_horse': [{'check': 'detector_count', 'class': 'horse', 'count': 1}],
    'render_animal_cow': [{'check': 'detector_count', 'class': 'cow', 'count': 1}],
    'render_animal_sheep': [{'check': 'detector_count', 'class': 'sheep', 'count': 3}],
    'render_animal_chicken': [{'check': 'detector_count', 'class': 'bird', 'count': 1}],
    'render_animal_bird_flying': [{'check': 'detector_count', 'class': 'bird', 'count': 1}],
    'render_animal_fish': [{'check': 'open_vocab_count', 'query': 'fish', 'min_score': 0.3, 'count': 1}],
    'render_animal_insect': [{'check': 'open_vocab_count', 'query': 'bee', 'min_score': 0.3, 'count': 1}],
    'render_food_fish': [{'check': 'open_vocab_count', 'query': 'whole raw fish', 'min_score': 0.3, 'count': 3}],
    'render_food_fruit': [{'check': 'open_vocab_count', 'query': 'apple', 'min_score': 0.3, 'count': 5}],
    'render_coins': [{'check': 'open_vocab_count', 'query': 'silver coin', 'min_score': 0.3, 'count': 7}],
    'render_container_barrel': [{'check': 'open_vocab_count', 'query': 'wooden barrel', 'min_score': 0.3, 'count': 1}],
    'render_boat': [{'check': 'detector_count', 'class': 'boat', 'count': 1}],
    'render_harbour': [{'check': 'detector_count', 'class': 'boat', 'min': 3}],
    'render_furniture': [{'check': 'open_vocab_count', 'query': 'wooden chair', 'min_score': 0.3, 'count': 1}],
    'render_lantern': [{'check': 'open_vocab_count', 'query': 'lantern', 'min_score': 0.3, 'count': 1}],
    'render_glassware': [{'check': 'open_vocab_count', 'query': 'wine goblet', 'min_score': 0.3, 'count': 1}],
    'render_basket': [{'check': 'open_vocab_count', 'query': 'wicker basket', 'min_score': 0.3, 'count': 1}],
    'render_instrument_music': [{'check': 'open_vocab_count', 'query': 'violin', 'min_score': 0.3, 'count': 1}],
    'render_wheel_cart': [{'check': 'open_vocab_count', 'query': 'spoked wooden wheel', 'min_score': 0.3, 'count': 2}],
    'render_tree': [{'check': 'open_vocab_count', 'query': 'tree', 'min_score': 0.35, 'count': 1}],
    'render_window_intact': [{'check': 'open_vocab_count', 'query': 'window', 'min_score': 0.3, 'count': 1}],
    'render_door': [{'check': 'open_vocab_count', 'query': 'door', 'min_score': 0.3, 'count': 1}],
    'render_broken_window': [{'check': 'open_vocab_present', 'terms': ['broken window'], 'min_score': 0.25}],
    'render_wet_surface': [{'check': 'open_vocab_present', 'terms': ['wet cobblestones'], 'min_score': 0.25}],
    'render_mud': [{'check': 'colour_of_thing', 'thing': 'boot', 'colour': 'brown', 'min_share': 0.25}],
    'render_blood': [{'check': 'colour_of_thing', 'thing': 'bandage', 'colour': 'red', 'min_share': 0.05}],
    'render_rust': [{'check': 'colour_of_thing', 'thing': 'iron hinge', 'colour': 'brown', 'min_share': 0.3}],
    'render_night': [{'check': 'ocr_absent', 'terms': ['SUN']}],
    # ── lettering: the OCR key IS the answer ──
    'render_text_letters': [{'check': 'ocr_equals', 'text': 'KATTENBURG'}],
    'render_text_word': [{'check': 'ocr_equals', 'text': 'HARING'}],
    'render_text_sentence': [{'check': 'ocr_equals', 'text': 'DE WERF IS GESLOTEN'}],
    'render_number_digits': [{'check': 'ocr_equals', 'text': '12345'}],
    'render_number_specific': [{'check': 'ocr_equals', 'text': '47'}],
    'render_number_date': [{'check': 'ocr_equals', 'text': '1671'}],
    'render_number_roman': [{'check': 'ocr_equals', 'text': 'MDCLXXI'}],
    'render_signage': [{'check': 'ocr_equals', 'text': 'DE GOUDEN LEEUW'}],
    'render_clock_face': [{'check': 'ocr_contains', 'terms': ['XII', 'III', 'VI', 'IX']}],
    'render_map_labels': [{'check': 'ocr_contains', 'terms': ['TEXEL', 'VLIELAND']}],
    'render_handwriting': [{'check': 'ocr_lines_min', 'min': 3, 'min_chars': 8}],
    'render_book_page': [{'check': 'ocr_lines_min', 'min': 8, 'min_chars': 12}],
    'render_symbol_crest': [{'check': 'ocr_absent', 'terms': ['A', 'E', 'O']}],
}

# 3/3 seeds -> yes, 2/3 -> partial. A subject that only lands on one seed in three is not a
# capability, it is luck, and the sheet must not read as though the model can do it.
SUBJECT_STATE_RULE = {'yes': 1.0, 'partial': 0.6}

SUBJECT_QUESTION = (
    'Is the {thing} in this picture whole, single and correct — no extra parts, no missing '
    'parts, no impossible geometry, and plainly the thing named? yes/no'
)


# ── probe helpers ──────────────────────────────────────────────────────────────────────────
def _probe(pid, title, feeds, prompt, checks, **kw):
    p = {
        'id': pid,
        'title': title,
        'feeds': list(feeds),
        'inputs': {'prompt': prompt},
        'conditions': dict(COND_RENDER),
        'checks': [dict(c) for c in checks],
        'grade': 'measured',
    }
    p.update(kw)
    return p


_SUBJECT_NOTE = (
    'The blind operator answers the written question; where a detector is listed it is the '
    'authority for the thing it measures (the count, the lettering, the fingertips) and BOTH '
    'must pass for the seed to count. 3/3 seeds is yes, 2/3 partial — a subject that lands '
    'once in three is luck, not a capability. `inputs.image` is the fixture the image-in steps '
    '(i2i, inpaint, controlnet, upscale, identity) feed this subject; it is UNUSED for t2i, '
    'which renders from the prompt alone.'
)


def _subject(col):
    thing, prompt = SUBJECTS[col]
    checks = [{'check': 'operator', 'question': SUBJECT_QUESTION.format(thing=thing)}]
    checks += list(SUBJECT_CHECKS.get(col, ()))
    p = _probe(
        'sub_' + col[7:],
        'Render ' + thing + ' — ' + col,
        [col],
        prompt,
        checks,
        state_rule=dict(SUBJECT_STATE_RULE),
        state_note=_SUBJECT_NOTE,
    )
    p['inputs']['image'] = SUBJECT_FIXTURES['path'].replace('<render_id>', col)
    p['fixture'] = dict(SUBJECT_FIXTURES, path=SUBJECT_FIXTURES['path'].replace('<render_id>', col))
    return p


PROBES = [_subject(c) for c in SUBJECTS]

# ── Prompt: damage — ONE base picture, mechanically checkable, one variant per column ───────
PD_BASE = (
    'A red barrel on the left and a blue crate on the right stand on a stone quay in plain '
    'daylight. Three white gulls sit on the quay wall behind them. The word HARING is painted '
    'in black capitals on the crate.'
)
PD_CHECKS = [
    {'check': 'open_vocab_count', 'query': 'wooden barrel', 'min_score': 0.3, 'count': 1},
    {'check': 'open_vocab_count', 'query': 'wooden crate', 'min_score': 0.3, 'count': 1},
    {'check': 'detector_count', 'class': 'bird', 'count': 3},
    {'check': 'colour_of_thing', 'thing': 'wooden barrel', 'colour': 'red', 'min_share': 0.4},
    {'check': 'colour_of_thing', 'thing': 'wooden crate', 'colour': 'blue', 'min_share': 0.4},
    {'check': 'spatial_relation', 'a': 'wooden barrel', 'b': 'wooden crate', 'relation': 'left_of', 'margin_px': 40},
    {'check': 'ocr_equals', 'text': 'HARING'},
]
PD_KEY_NOTE = (
    'Seven mechanical facts, the SAME seven for every variant: one barrel, one crate, three '
    'birds, the barrel red, the crate blue, the barrel left of the crate, the lettering exactly '
    'HARING. Nothing here is an operator decision, so a damage cell cannot be argued. A variant '
    'is scored only against this key — never against how good the picture looks.'
)

PD_VARIANTS = {
    'pd_damage': ('the undamaged control', PD_BASE),
    'pd_paraphrase': (
        'every clause reworded, nothing added or removed',
        'On a stone quay in plain daylight there stands a crate of blue to the right and, to '
        'its left, a barrel painted red. Behind the pair of them three gulls, white, are '
        'perched upon the quay wall. HARING is lettered on the crate in black capitals.',
    ),
    'pd_word_order': (
        'the same three sentences, last first',
        'The word HARING is painted in black capitals on the crate. Three white gulls sit on '
        'the quay wall behind them. A red barrel on the left and a blue crate on the right '
        'stand on a stone quay in plain daylight.',
    ),
    'pd_synonym': (
        'every noun swapped for a synonym',
        'A scarlet cask on the left and an azure box on the right stand on a flagstone wharf in '
        'plain daylight. Three white seagulls perch on the wharf wall behind them. The word '
        'HARING is lettered in black capitals on the box.',
    ),
    'pd_typo': (
        'six misspellings, the key words among them',
        'A red barrle on the left and a blue crat on the right stand on a stoen quay in plian '
        'daylight. Three white gulls sit on the quay wall behnid them. The word HARING is '
        'painted in black capitals on the crat.',
    ),
    'pd_grammar': (
        'articles dropped, verbs and plurals wrong',
        'Red barrel on left and blue crate on right stands on stone quay in plain daylight, '
        'three white gull sits on the quay wall behind them, the word HARING are painted in '
        'black capital on the crate.',
    ),
    'pd_punctuation': (
        'not one mark of punctuation',
        'A red barrel on the left and a blue crate on the right stand on a stone quay in plain '
        'daylight three white gulls sit on the quay wall behind them the word HARING is painted '
        'in black capitals on the crate',
    ),
    'pd_case': (
        'all lower case, the lettering included',
        'a red barrel on the left and a blue crate on the right stand on a stone quay in plain '
        'daylight. three white gulls sit on the quay wall behind them. the word haring is '
        'painted in black capitals on the crate.',
    ),
    'pd_filler': (
        'padded with courtesies that say nothing',
        'Please note that a red barrel on the left and a blue crate on the right stand, as it '
        'were, on a stone quay in plain daylight. Three white gulls sit on the quay wall behind '
        'them. The word HARING is painted in black capitals on the crate, if you would.',
    ),
    'pd_repetition': (
        'the two key clauses said twice',
        'A red barrel on the left, a red barrel on the left, and a blue crate on the right '
        'stand on a stone quay in plain daylight. Three white gulls, three white gulls, sit on '
        'the quay wall behind them. HARING is painted in black capitals on the crate.',
    ),
    'pd_multilingual': (
        'the same prompt in Dutch',
        'Een rood vat links en een blauwe kist rechts staan op een stenen kade in gewoon '
        'daglicht. Drie witte meeuwen zitten op de kademuur erachter. Het woord HARING staat '
        'in zwarte kapitalen op de kist.',
    ),
}

for _col, (_label, _prompt) in PD_VARIANTS.items():
    PROBES.append(
        _probe(
            'pd_' + _col[3:],
            'Prompt damage: ' + _label,
            [_col],
            _prompt,
            PD_CHECKS,
            state_note=PD_KEY_NOTE + ' Variant: ' + _label + '. Read this cell '
            'against pd_damage, the same key on the undamaged prompt — a variant '
            'that scores what the control scores means the damage did not matter.',
            key_note='the same seven facts as pd_damage',
        )
    )

PROBES += [
    _probe(
        'pd_contradiction',
        'Prompt damage: the prompt names two colours for one barrel',
        ['pd_contradiction'],
        'A red barrel on the left and a blue crate on the right stand on a stone quay in '
        'plain daylight. The barrel is blue. Three white gulls sit on the quay wall behind '
        'them. The word HARING is painted in black capitals on the crate.',
        [
            {'check': 'open_vocab_count', 'query': 'wooden barrel', 'min_score': 0.3, 'count': 1},
            {
                'check': 'operator',
                'question': 'Is the barrel ONE flat colour rather than a blend or a two-tone barrel, and is there only one barrel? yes/no',
            },
            {'check': 'detector_count', 'class': 'bird', 'count': 3},
            {'check': 'ocr_equals', 'text': 'HARING'},
        ],
        state_note='A picture cannot ask which colour was meant, so the measurement is '
        'whether it PICKS one and leaves the rest of the key intact. Two barrels, '
        'or a purple barrel, is a no; the operator decides the blend, the '
        'detector decides the count and the lettering.',
    ),
    _probe(
        'pd_negation',
        'Prompt damage: a thing the prompt forbids',
        ['pd_negation'],
        'A red barrel on the left and a blue crate on the right stand on a stone quay in '
        'plain daylight. There is no hat anywhere in the picture. Three white gulls sit on '
        'the quay wall behind them.',
        [
            {'check': 'open_vocab_absent', 'terms': ['hat', 'cap'], 'min_score': 0.3},
            {'check': 'open_vocab_count', 'query': 'wooden barrel', 'min_score': 0.3, 'count': 1},
            {'check': 'detector_count', 'class': 'bird', 'count': 3},
        ],
        state_note='Wholly mechanical: a hat above 0.3 is a no. Read beside '
        'pd_pos_neg_split, which asks the same thing through the negative prompt.',
    ),
    _probe(
        'pd_unstated',
        'Prompt damage: what the model invents where the prompt is silent',
        ['pd_unstated'],
        'A Dutch shipwright stands behind a workbench on the Kattenburg quay, 1671, plain '
        'daylight, seen from the front, his arms hidden below the bench top.',
        [
            {'check': 'hand_landmarks', 'hands': 0, 'min_tip_px': 12},
            {'check': 'detector_count', 'class': 'person', 'count': 1},
            {
                'check': 'operator',
                'question': 'Are both of the man arms out of sight below the bench, with no hand, finger or forearm visible anywhere? yes/no',
            },
        ],
        state_note='Hands are the house sore point, so the silence is about hands. MediaPipe '
        'finding a hand is a no regardless of what the operator thinks; the '
        'operator catches a forearm the detector misses.',
    ),
    _probe(
        'pd_bleed',
        'Prompt damage: does one colour term stain the rest of the frame',
        ['pd_bleed'],
        'A woman in a bright red cloak stands in front of a plain whitewashed wall on the '
        'Kattenburg quay, 1671, plain daylight, whole body in frame.',
        [
            {'check': 'colour_of_thing', 'thing': 'whitewashed wall', 'colour': 'white', 'min_share': 0.7},
            {'check': 'colour_of_thing', 'thing': 'whitewashed wall', 'colour': 'red', 'max_share': 0.05},
            {'check': 'colour_of_thing', 'thing': 'cloak', 'colour': 'red', 'min_share': 0.5},
        ],
        state_note='Mechanical and two-sided: the cloak must BE red and the wall must not '
        'become red. Bleed is the failure the house sees most on SDXL, and it is '
        'measured here as pixels inside two boxes, not as an impression.',
    ),
    _probe(
        'pd_leak',
        'Prompt damage: are style words drawn as words',
        ['pd_leak'],
        'A red barrel on a stone quay in plain daylight, photorealistic, 85mm lens, shot on '
        'Kodak Portra, highly detailed, masterpiece.',
        [
            {
                'check': 'ocr_absent',
                'terms': ['PHOTOREALISTIC', 'KODAK', 'PORTRA', 'MASTERPIECE', '85MM', 'DETAILED', 'LENS'],
            },
            {'check': 'open_vocab_count', 'query': 'wooden barrel', 'min_score': 0.3, 'count': 1},
        ],
        state_note='Wholly mechanical: OCR either finds the style word painted in the frame '
        'or it does not. The barrel count keeps a blank grey frame from passing.',
    ),
    _probe(
        'pd_meta_literal',
        'Prompt damage: is the camera instruction drawn as a camera',
        ['pd_meta_literal'],
        'A close-up photograph of a red barrel on a stone quay in plain daylight, taken with '
        'a 35mm camera on a wooden tripod.',
        [
            {'check': 'open_vocab_absent', 'terms': ['camera', 'tripod'], 'min_score': 0.3},
            {'check': 'open_vocab_count', 'query': 'wooden barrel', 'min_score': 0.3, 'count': 1},
            {'check': 'ocr_absent', 'terms': ['35MM']},
        ],
        state_note='Mechanical. The instruction is about the camera; a camera IN the frame '
        'means the model read the instruction as content.',
    ),
    _probe(
        'pd_damage_visible',
        'Prompt damage: can the damage be SEEN in the picture',
        ['pd_damage_visible'],
        'the eleven PD_VARIANTS renders, anonymised and shuffled together with the pd_damage '
        'control renders; the operator is not told which is which',
        [
            {
                'check': 'operator',
                'question': 'Was this picture made from a damaged instruction — a typo, bad grammar, no punctuation, a reworded or reordered brief? yes/no',
            }
        ],
        conditions=dict(COND_RENDER, repeats=3, note='no new renders: this probe re-reads the PD_VARIANTS frames'),
        state_note='An image model has no channel to say "I did not understand", so '
        '"visible" can only mean: an operator who has never seen the prompt can '
        'tell a damaged run from a clean one. yes here is BAD for the model — the '
        'runner inverts the pass rate before applying the state rule, and the '
        'trial records both numbers. This probe consumes the frames the variant '
        'probes already made; it queues nothing.',
    ),
    _probe(
        'pd_style_vs_content',
        'Prompt damage: does a heavy style clause cost the content',
        ['pd_style_vs_content'],
        PD_BASE + ' Painted as a Dutch golden age oil painting, heavy chiaroscuro, thick impasto, dramatic side light.',
        PD_CHECKS
        + [
            {
                'check': 'operator',
                'question': 'Does this picture look like an oil painting with strong side light, rather than a plain photograph? yes/no',
            }
        ],
        pair=['pd_damage', 'pd_style_vs_content'],
        state_note='The pair is the measurement: the same seven content facts with and '
        'without the style clause. yes needs the content key to survive AND the '
        'style to arrive — a model that keeps the barrel by ignoring the style, '
        'or gets the style by losing the crate, is partial at best. The style '
        'half is the operator; the content half is mechanical.',
    ),
]
