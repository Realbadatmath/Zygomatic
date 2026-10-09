# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

from __future__ import annotations

from .settings import COND_JUDGE
from .subjects import LADDER_DIR
from .probes_subjects import PROBES

# ── Capacity: ladders whose answer is a COUNT ────────────────────────────────
# A capacity column is never a yes/no. Each entry below is a LADDER of fixtures that
# differ in ONE quantity. Every rung is asked the same fixed question, `repeats` times;
# a rung PASSES when the answer equals that rung's key on at least `state_rule['yes']`
# of the repeats. The column is written as the LAST rung that passed BEFORE the first
# rung that failed (a later rung passing by luck does not raise it), and `unit` says
# what the number counts. A model that fails rung one is written 0 — it is what it did.
LADDER_NOTE = (
    'The column is the last rung that passed before the first failure, not the best rung. '
    'Three repeats per rung, fixed seed, temperature 0; a rung needs 3/3 to pass because a '
    'count answered right twice out of three is a guess. The operator never sees the rung '
    'number, so no rung is read more generously than another.'
)

# column -> (title, question, rung values, fixture stem, unit, what each rung changes, mechanical check)
LADDERS = {
    'cap_people': (
        'People it still counts right',
        'How many people are in this picture? Answer with the number only.',
        [1, 2, 3, 5, 8, 12],
        'people',
        'count',
        'the same quay, the same seed, N dockworkers standing apart, none overlapping',
        {'check': 'person_count', 'note': 'ultralytics person class over the same rung, as the second opinion'},
    ),
    'cap_named': (
        'Named characters held apart',
        'Which of Aeltje, Barend and Cornelis is wearing the red cap? Answer with the name only.',
        [1, 2, 3, 4, 6],
        'named',
        'count',
        'N named sitters in one frame, each with a written attribute sheet the operator holds; only one wears the red cap',
        None,
    ),
    'cap_faces': (
        'Faces it still reads',
        'How many faces can you see in this picture? Answer with the number only.',
        [1, 2, 3, 5, 8],
        'faces',
        'count',
        'N faces at the same scale, front on, evenly spaced, same seed',
        {'check': 'face_count', 'note': 'MediaPipe face mesh in anatomy_qc.py over the same rung'},
    ),
    'cap_hands': (
        'Hands it still reads',
        'How many hands can you see in this picture? Answer with the number only.',
        [1, 2, 4, 6, 8],
        'hands',
        'count',
        'N open hands palm to camera on a plain board, same scale, same seed',
        {
            'check': 'mediapipe_hands',
            'hands': None,
            'note': 'hand_landmarker in anatomy_qc.py; `hands` is the rung value',
        },
    ),
    'cap_objects': (
        'Distinct objects it keeps track of',
        'List every distinct kind of object in this picture as short nouns separated by commas. Nothing else.',
        [2, 4, 6, 9, 12],
        'objects',
        'count',
        'N distinct named props on a table, one of each, laid out without overlap, same seed',
        None,
    ),
    'cap_words': (
        'Words of text it reads',
        'Read the text on the board in this picture. Write exactly what it says, nothing else.',
        [1, 2, 4, 7, 12],
        'words',
        'count',
        'a painted board carrying N Dutch words in one line, same lettering, same seed',
        {'check': 'ocr_equals', 'note': 'the typography OCR judge over the same rung; `text` is the rung key'},
    ),
    'cap_digits': (
        'Digits it gets right',
        'Read the number on the tablet in this picture. Write the digits only.',
        [1, 2, 3, 4, 6],
        'digits',
        'count',
        'a stone tablet carrying an N-digit number, same chisel, same seed',
        {'check': 'ocr_equals', 'note': 'the typography OCR judge over the same rung; `text` is the rung key'},
    ),
    'cap_animals': (
        'Animals it still counts',
        'How many animals are in this picture? Answer with the number only.',
        [1, 2, 3, 5, 8],
        'animals',
        'count',
        'N gulls on the same quay wall, spaced apart, same seed',
        None,
    ),
    'cap_prompt_terms': (
        'Question terms it still honours',
        'Answer each part with yes or no on its own line, in the order asked, nothing else.',
        [1, 2, 4, 6, 9, 12],
        'terms',
        'count',
        'one fixed picture; the question carries N separate clauses, each with a known yes/no key',
        {'check': 'answers_counted', 'note': 'n is the rung value; a short answer is a failed rung, not a partial one'},
    ),
    'cap_questions': (
        'Questions per picture before it drifts',
        'Answer each numbered question with yes or no on its own line, in order, nothing else.',
        [1, 3, 5, 10, 20],
        'questions',
        'count',
        'one fixed picture; N numbered questions in one prompt, each with a known key',
        {'check': 'agreement_min', 'min': 0.9, 'note': 'the same questions asked one at a time are the reference'},
    ),
    'cap_images': (
        'Images in one prompt',
        'For each picture in order, answer yes or no on its own line: is there a barrel in it?',
        [1, 2, 3, 4, 6],
        'images',
        'count',
        'N of the subject fixtures in one call, half of them the negatives, order fixed',
        {
            'check': 'answers_counted',
            'note': 'n is the rung value; an answer for a picture that was not sent fails the rung',
        },
    ),
    'cap_res_judge': (
        'Resolution it can resolve detail at',
        'Look at the hand in this picture. Does it have five fingers? Answer yes or no, one word only.',
        [512, 768, 1024, 1280],
        'res',
        'px',
        'ONE render, downscaled to N px on the long edge with Lanczos; the five-finger hand and the four-finger '
        'negative are the same pair at every rung, so only the pixels change',
        {
            'check': 'mediapipe_hands',
            'hands': 1,
            'fingers': 5,
            'note': 'the detector is run at the same rung, so the comparison is like for like',
        },
    ),
    'cap_moving': (
        'Moving subjects it can follow',
        'How many people move in this clip? Answer with the number only.',
        [1, 2, 3, 5],
        'moving',
        'count',
        'the same 4 s quay clip with N walking figures, same seed, same camera',
        None,
    ),
    'cap_seconds': (
        'Seconds of clip before the verdict drifts',
        'Does the man in the blue coat keep his hat on for the whole clip? Answer yes or no, one word only.',
        [2, 4, 8, 16],
        'seconds',
        's',
        'the same shot cut to N seconds; the hat comes off at 1.5 s in the negative and never in the positive',
        None,
    ),
    'cap_shots': (
        'Shots it can compare in one pass',
        'Is the man in the blue coat the same person in every shot? Answer yes or no, one word only.',
        [2, 3, 5, 8],
        'shots',
        'count',
        'N stills of one scene; the negative swaps the coat colour in the last shot only',
        {
            'check': 'arcface_cosine',
            'min': 0.35,
            'note': 'identity_qc_service.py over the same stills, as the second opinion',
        },
    ),
}

LADDER_VERIFY = (
    'The operator opens the ladder contact sheet once and confirms, rung by rung, that the picture really '
    'holds the number the key claims — counting it by eye, on the render, not on the prompt. A prompt that '
    'asked for eight barrels and produced seven is a fixture bug, and a judge that answers seven would be '
    'marked wrong for being right. Until that pass is recorded the ladder stays verified: False and every '
    'column it blocks is written untested with the note "key unverified".'
)

for _col, (_title, _q, _rungs, _stem, _unit, _what, _mech) in LADDERS.items():
    _checks = [
        {
            'check': 'count_equals_key',
            'transports': ['vlm_ollama', 'vlm_inspector', 'service'],
            'note': 'the answer is normalised (number words to digits, articles stripped) and must equal the rung key exactly',
        }
    ]
    if _col in ('cap_named', 'cap_objects', 'cap_words', 'cap_digits', 'cap_res_judge', 'cap_seconds', 'cap_shots'):
        _checks = [
            {
                'check': 'equals_key',
                'transports': ['vlm_ollama', 'vlm_inspector', 'service'],
                'note': 'each rung carries its own `accept` set; the rung passes only on an exact normalised match',
            }
        ]
    if _mech:
        _checks.append(dict(_mech, transports=['service'], on='the rung fixture, not the answer'))
    _checks.append(
        {
            'check': 'operator',
            'question': 'Shown one anonymised answer and the rung picture side by side: is the answer right for that picture? '
            'Yes or no. A "maybe" is a no.',
            'blind': True,
            'note': 'the operator is not told the rung number, the model or the ladder',
        }
    )
    PROBES.append(
        {
            'id': f'ladder_{_col}',
            'title': _title,
            'feeds': [_col],
            'unit': _unit,
            'inputs': {
                'task': _q,
                'image': [f'{LADDER_DIR}/{_stem}_{_n}.png' for _n in _rungs],
                'fixture': {
                    'path': f'{LADDER_DIR}/{_stem}_<rung>.png',
                    'rungs': list(_rungs),
                    'generated': _what,
                    'key': {str(_n): {'count': _n} for _n in _rungs},
                    'verified': False,
                    'blocks': [_col],
                    'how_to_verify': LADDER_VERIFY,
                },
            },
            'conditions': dict(
                COND_JUDGE,
                ladder=list(_rungs),
                unit=_unit,
                order='rungs are asked in ascending order and the ladder STOPS at the first failed rung',
            ),
            'checks': _checks,
            'grade': 'measured',
            'state_rule': {'yes': 0.9, 'partial': 0.7},
            'state_note': LADDER_NOTE,
        }
    )
