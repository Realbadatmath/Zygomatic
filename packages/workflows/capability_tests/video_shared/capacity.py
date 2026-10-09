# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Capacity: twelve ladders whose answer is a count."""

from __future__ import annotations

from .settings import (
    NEGATIVE,
    SAMPLE5,
)
from .probes import (
    PROBES,
    _probe,
)

# ── Capacity: twelve LADDERS whose answer is a count ───────────────────────────────────
# Every rung is a fixed prompt. The runner renders the rungs in order, at all three seeds, and
# the column's answer is the LAST rung that passed at every seed — a number, not a yes/no.
LADDER_NOTE = (
    'The answer is the highest rung that passed at ALL THREE seeds; the rungs above it are '
    'rendered too and their failures go in the trial, so the reader can see where it broke '
    'and how. A rung fails on its mechanical check OR on the operator question — both must '
    'pass. Rung 1 failing means the column is 0, which is a real answer.'
)
CAP_STATE = {'yes': 1.0, 'partial': 0.6}


def _ladder(pid, title, col, rungs, checks_for, unit='count', note=None, cond=None, extra=None):
    """A capacity/limit ladder. `rungs` is a list of {'n', 'prompt', 'motion'} and `checks_for(rung)`
    returns the checks for that rung (the mechanical one plus the operator question)."""
    rr = []
    for r in rungs:
        rr.append({'n': r['n'], 'prompt': r['prompt'], 'motion': r['motion'], 'checks': checks_for(r)})
    p = _probe(
        pid,
        title,
        [col],
        {'prompt': 'per rung, verbatim in `ladder`', 'ladder': rr, 'negative': NEGATIVE, 'unit': unit},
        [
            {
                'check': 'operator',
                'question': "see each rung's own checks in `inputs.ladder`",
                'for': col,
                'note': 'the runner scores rung by rung; this entry exists so the check list is never empty',
            }
        ],
        cond=cond,
        state_rule=CAP_STATE,
        state_note=(note or LADDER_NOTE),
        unit=unit,
    )
    if extra:
        p['checks'].extend(extra)
    return p


def _people_rung(r):
    return [
        {
            'check': 'detector_count',
            'detector': 'yolov8n-coco',
            'label': 'person',
            'n': r['n'],
            'sample': SAMPLE5,
            'share': 1.0,
        },
        {
            'check': 'operator',
            'question': f'Are there exactly {r["n"]} people, and is EVERY one of them '
            'anatomically whole through the whole clip — no extra or missing '
            'limb, no fused pair, no face melting? yes/no',
        },
    ]


def _quay(n, what, motion):
    return {
        'n': n,
        'prompt': f'{what} on a stone quay in a Dutch harbour town, full body, daylight, 1671.',
        'motion': motion,
    }


PROBES.append(
    _ladder(
        'cap_people_ladder',
        'capacity: people in one frame before anatomy breaks',
        'cap_people',
        [
            _quay(1, 'One dockworker in a brown wool coat stands', 'he walks four steps along the quay and stops'),
            _quay(2, 'Two dockworkers in brown wool coats stand', 'both walk four steps along the quay and stop'),
            _quay(
                3, 'Three dockworkers in brown wool coats stand', 'all three walk four steps along the quay and stop'
            ),
            _quay(5, 'Five dockworkers in brown wool coats stand', 'all five walk four steps along the quay and stop'),
            _quay(
                8, 'Eight dockworkers in brown wool coats stand', 'all eight walk four steps along the quay and stop'
            ),
            _quay(
                12, 'Twelve dockworkers in brown wool coats stand', 'all twelve walk four steps along the quay and stop'
            ),
        ],
        _people_rung,
    )
)

# cap_named — the four named characters, each with a reference still the operator approved.
NAMED = {
    1: ['Maarten'],
    2: ['Maarten', 'Griet'],
    3: ['Maarten', 'Griet', 'Joost'],
    4: ['Maarten', 'Griet', 'Joost', 'Neeltje'],
}
NAMED_STILL = 'fixtures/video/named/{name}.png'


def _named_rung(r):
    names = NAMED[r['n']]
    return [
        {
            'check': 'identity_cosine_ref',
            'ref': [NAMED_STILL.format(name=n) for n in names],
            'min': 0.35,
            'detector': 'insightface-buffalo_l',
            'sample': SAMPLE5,
            'note': 'each named face in the clip must match ITS OWN reference still and no other',
        }
    ] + [
        {
            'check': 'operator',
            'question': f'The {r["n"]} reference portraits are shown. Are all {r["n"]} of '
            'these people present in the clip, each recognisably themselves from '
            'first frame to last, and never swapped or blended with another? yes/no',
        }
    ]


PROBES.append(
    _ladder(
        'cap_named_ladder',
        'capacity: named characters held at once',
        'cap_named',
        [
            {
                'n': n,
                'prompt': 'A group of '
                + ('one Dutch dockworker' if n == 1 else f'{n} named Dutch townspeople')
                + ' stands on a stone quay, full body, daylight, 1671.',
                'motion': 'they turn to face the camera one after another and hold still',
            }
            for n in (1, 2, 3, 4)
        ],
        _named_rung,
    )
)


def _faces_rung(r):
    return [
        {
            'check': 'detector_count',
            'detector': 'insightface-buffalo_l',
            'label': 'face',
            'n': r['n'],
            'sample': SAMPLE5,
            'share': 1.0,
        },
        {
            'check': 'operator',
            'question': f'Are all {r["n"]} faces intact through the clip — two eyes, one '
            'mouth, no smearing, no sliding features, no face turning into '
            'another face? yes/no',
        },
    ]


PROBES.append(
    _ladder(
        'cap_faces_ladder',
        'capacity: faces that stay clean',
        'cap_faces',
        [
            {
                'n': n,
                'prompt': f'{n} Dutch townspeople stand shoulder to shoulder facing the camera, waist up, daylight, 1671.',
                'motion': 'they all look slowly from left to right',
            }
            for n in (1, 2, 3, 5, 8)
        ],
        _faces_rung,
    )
)


def _hands_rung(r):
    return [
        {
            'check': 'hand_landmarks_count',
            'hands': min(r['n'], 2),
            'sample': SAMPLE5,
            'share': 0.8,
            'note': "MediaPipe reads at most 2 hands; above rung 2 the count is the operator's, the landmarker only confirms the two nearest",
        },
        {
            'check': 'operator',
            'question': f'Are all {r["n"]} hands visible with exactly five fingers each, no '
            'fused, missing, extra or bending-backwards finger, at any point in '
            'the clip? yes/no',
        },
    ]


PROBES.append(
    _ladder(
        'cap_hands_ladder',
        'capacity: hands that stay clean',
        'cap_hands',
        [
            {
                'n': n,
                'prompt': f'{n} bare human hands rest on a plain oak table, close-up, palms down, soft daylight.',
                'motion': 'the hands spread their fingers wide and then close',
            }
            for n in (1, 2, 3, 4)
        ],
        _hands_rung,
    )
)

OBJECTS = [
    'a pewter tankard',
    'a clay pipe',
    'a folded chart',
    'a brass compass',
    'a coil of rope',
    'a leather glove',
    'a tin lantern',
    'a wooden mallet',
    'an iron key',
    'a glass bottle',
    'a linen cap',
    'a copper coin',
]


def _objects_rung(r):
    items = OBJECTS[: r['n']]
    return [
        {
            'check': 'operator',
            'question': 'This list is shown: '
            + '; '.join(items)
            + f'. Are ALL {r["n"]} of them present and identifiable in the clip, '
            'each one separate, none merged with another and none missing? yes/no',
        },
        {'check': 'flicker_max', 'max': 12.0, 'note': 'objects that churn between frames are not "kept track of"'},
    ]


PROBES.append(
    _ladder(
        'cap_objects_ladder',
        'capacity: distinct objects it keeps track of',
        'cap_objects',
        [
            {
                'n': n,
                'prompt': 'On a plain oak table, laid out in a row: '
                + ', '.join(OBJECTS[:n])
                + '. Daylight, close-up.',
                'motion': 'the camera pans slowly left to right across the table',
            }
            for n in (2, 3, 5, 8, 12)
        ],
        _objects_rung,
    )
)

WORDS = [
    'HAVEN',
    'HAVEN WERF',
    'HAVEN WERF ZOUT',
    'HAVEN WERF ZOUT TOUW KAAI',
    'HAVEN WERF ZOUT TOUW KAAI SCHIP ANKER WIND',
]


def _words_rung(r):
    return [
        {'check': 'ocr_equals', 'text': r['text'], 'detector': 'tesseract-5', 'sample': SAMPLE5, 'share': 0.8},
        {'check': 'ocr_stable', 'sample': SAMPLE5},
        {
            'check': 'operator',
            'question': f'Does the board read exactly "{r["text"]}" — every letter correct, '
            'no invented letter, no missing word — in every frame? yes/no',
        },
    ]


PROBES.append(
    _ladder(
        'cap_words_ladder',
        'capacity: words of legible text',
        'cap_words',
        [
            {
                'n': i + 1,
                'text': w,
                'prompt': f'A wooden board painted with the words "{w}" in black capitals, close-up, daylight.',
                'motion': 'the board is lifted into frame and held still',
            }
            for i, w in enumerate(WORDS)
        ],
        _words_rung,
    )
)

DIGITS = ['7', '16', '167', '1671', '167145']


def _digits_rung(r):
    return [
        {'check': 'ocr_equals', 'text': r['text'], 'detector': 'tesseract-5', 'sample': SAMPLE5, 'share': 0.8},
        {
            'check': 'operator',
            'question': f'Does the carved date read exactly "{r["text"]}" in every frame — '
            'right digits, right order, none added or dropped? yes/no',
        },
    ]


PROBES.append(
    _ladder(
        'cap_digits_ladder',
        'capacity: digits it gets right',
        'cap_digits',
        [
            {
                'n': len(d),
                'text': d,
                'prompt': f'A stone lintel with the number {d} carved into it, close-up, raking daylight.',
                'motion': 'the camera pushes slowly in on the carved number',
            }
            for d in DIGITS
        ],
        _digits_rung,
    )
)


def _animals_rung(r):
    return [
        {
            'check': 'detector_count',
            'detector': 'yolov8n-coco',
            'label': 'bird',
            'n': r['n'],
            'sample': SAMPLE5,
            'share': 1.0,
        },
        {
            'check': 'operator',
            'question': f'Are there exactly {r["n"]} gulls, each with two wings, two legs and '
            'one head, none fused to another and none flickering in and out? yes/no',
        },
    ]


PROBES.append(
    _ladder(
        'cap_animals_ladder',
        'capacity: animals in one frame',
        'cap_animals',
        [
            {
                'n': n,
                'prompt': f'{n} herring gulls stand on a stone quay wall, side view, overcast daylight.',
                'motion': 'the gulls shuffle a step and flap once',
            }
            for n in (1, 2, 3, 5, 8)
        ],
        _animals_rung,
    )
)

# cap_prompt_terms — 45 short visual terms, in a fixed order. Rung n uses the first n.
TERMS = [
    'a red wool cloak',
    'a wooden board painted HAVEN',
    'two herring gulls',
    'a coil of tarred rope',
    'a stone quay',
    'overcast daylight',
    'a brass compass',
    'a clay pipe',
    'a pewter tankard',
    'a leather glove',
    'a tin lantern',
    'a wooden mallet',
    'an iron key',
    'a glass bottle',
    'a linen cap',
    'a copper coin',
    'a moored fishing boat',
    'a folded chart',
    'a barrel of salt',
    'a fishing net',
    'a wet cobblestone',
    'a rusted hinge',
    'a cracked plank',
    'a brick wall',
    'a leaded window',
    'a slate roof',
    'a chimney',
    'a wooden crate',
    'a hemp sack',
    'a brown horse',
    'a black dog',
    'a white goose',
    'a bare tree',
    'low grey cloud',
    'a puddle',
    'a gust of wind',
    'a wooden bollard',
    'an anchor',
    "a ship's bell",
    'a stack of planks',
    'a hand cart',
    'a broom',
    'a bucket',
    'a length of chain',
    'a lit candle',
]
assert len(TERMS) == 45


def _terms_rung(r):
    items = TERMS[: r['n']]
    return [
        {
            'check': 'operator',
            'question': 'This list is shown: '
            + '; '.join(items)
            + f'. How many of these {r["n"]} are visibly present in the clip? '
            f'The rung passes only if ALL {r["n"]} are. yes/no',
            'note': "the operator also writes the number present; that number is the trial's evidence",
        },
        {
            'check': 'named_colour_region',
            'region': 'the cloak',
            'colour': 'red',
            'tolerance_deg': 25,
            'sample': SAMPLE5,
            'note': 'term 1 is checked mechanically at every rung, so a rung never passes on a kind operator alone',
        },
    ]


PROBES.append(
    _ladder(
        'cap_prompt_terms_ladder',
        'capacity: prompt terms it still honours',
        'cap_prompt_terms',
        [
            {
                'n': n,
                'prompt': 'A Dutch harbour quay in 1671 containing: ' + ', '.join(TERMS[:n]) + '.',
                'motion': 'the camera pans slowly left to right across the quay',
            }
            for n in (5, 10, 20, 30, 45)
        ],
        _terms_rung,
        note=(
            'The answer is the highest rung where ALL terms landed at all three seeds. This is the one ladder '
            'that deliberately breaks FIXED["word_budget"]: from rung 3 on it is past 77 CLIP tokens, which is '
            'the point — it measures where the encoder stops listening. The trial records the token count.'
        ),
    )
)

# cap_seconds — one scene extended by 81-frame windows, each seeded from the previous last frame.
PROBES.append(
    _ladder(
        'cap_seconds_ladder',
        'capacity: seconds before it degrades',
        'cap_seconds',
        [
            {
                'n': s,
                'prompt': 'One Dutch dockworker in a brown wool coat walks along a stone quay, full body, daylight, 1671.',
                'motion': 'he walks steadily along the quay, passing moored boats, and does not stop',
            }
            for s in (2, 5, 10, 20, 40)
        ],
        lambda r: [
            {
                'check': 'duration_s',
                'min': r['n'] - 0.2,
                'max': r['n'] + 0.2,
                'note': 'frames = round(row fps × seconds), produced as 81-frame windows chained from the previous last frame',
            },
            {'check': 'seam_continuity', 'at': 'every window seam', 'max_ratio': 2.5},
            {'check': 'flicker_max', 'max': 12.0},
            {'check': 'identity_cosine_min', 'a': 0, 'b': -1, 'min': 0.35, 'detector': 'insightface-buffalo_l'},
            {
                'check': 'operator',
                'question': f'Over these {r["n"]} seconds, is it the same man in the same coat in the '
                'same place throughout, walking plausibly, with no jump, no drift in '
                'colour or style, and no moment where he melts or restarts? yes/no',
            },
        ],
        unit='s',
        note=(
            'The answer is the longest rung that held at all three seeds, in SECONDS. A row that cannot be '
            'extended at all answers 5 (its own clip length) and `resumable` is its no. ' + LADDER_NOTE
        ),
    )
)

# cap_shots — n shots of one scene, rendered separately at the same seed and concatenated.
SHOTS = [
    'wide, the whole quay',
    'medium, the dockworker waist up',
    'close, his hands on the rope',
    'wide from the water, the quay behind him',
]
PROBES.append(
    _ladder(
        'cap_shots_ladder',
        'capacity: shots that cut together',
        'cap_shots',
        [
            {
                'n': n,
                'prompt': 'One Dutch dockworker in a brown wool coat coils rope on a stone quay, daylight, 1671. Shot: '
                '<one of ' + ' | '.join(SHOTS[:n]) + '>',
                'motion': 'he coils the rope steadily',
                'shots': SHOTS[:n],
            }
            for n in (1, 2, 3, 4)
        ],
        lambda r: [
            {
                'check': 'shot_cuts',
                'n': r['n'] - 1,
                'detector': 'pyscenedetect',
                'note': 'the concatenation of n shots must read as exactly n-1 cuts; a shot that does not differ from its neighbour is not a shot',
            },
            {
                'check': 'identity_cosine_ref',
                'ref': 'shot 1, frame 0',
                'min': 0.35,
                'detector': 'insightface-buffalo_l',
                'sample': [0],
                'note': 'skipped on the close shot of the hands, where there is no face — recorded as not-applicable in the trial',
            },
            {
                'check': 'operator',
                'question': f'These {r["n"]} shots are shown cut together. Do they read as the same '
                'man, the same coat, the same quay and the same light — a sequence rather '
                'than unrelated clips? yes/no',
            },
        ],
        note=(
            'The answer is the most shots that still cut together at all three seeds. Each shot is its own render '
            'at the SAME seed from the same still; nothing is re-prompted between shots. ' + LADDER_NOTE
        ),
    )
)

# cap_moving — n subjects moving independently in one frame.
PROBES.append(
    _ladder(
        'cap_moving_ladder',
        'capacity: moving subjects at once',
        'cap_moving',
        [
            {
                'n': n,
                'prompt': f'{n} Dutch dockworkers in brown wool coats on a stone quay, spaced apart, full body, daylight, 1671.',
                'motion': 'each one walks in a different direction at the same time',
            }
            for n in (1, 2, 3, 5)
        ],
        lambda r: [
            {'check': 'mask_iou_max', 'n': r['n'], 'max': 0.1, 'sample': SAMPLE5, 'detector': 'sam2-hiera-small'},
            {
                'check': 'detector_count',
                'detector': 'yolov8n-coco',
                'label': 'person',
                'n': r['n'],
                'sample': SAMPLE5,
                'share': 1.0,
            },
            {'check': 'motion_min', 'min': 0.6},
            {
                'check': 'operator',
                'question': f'Do all {r["n"]} people move independently — different directions, no two '
                'sliding together, none frozen, none merging into another as they '
                'pass? yes/no',
            },
        ],
    )
)
