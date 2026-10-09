# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Prompt: limits — the length ladder and the instruction/constraint banks."""

from __future__ import annotations

from .settings import (
    NEGATIVE,
    SAMPLE5,
    STATE_3OF3,
)
from .probes import (
    PROBES,
    _probe,
)
from .capacity import (
    LADDER_NOTE,
    NAMED,
    NAMED_STILL,
    TERMS,
    _ladder,
)
from .scenes import (
    FR2,
    _op,
)
from .prompt_bands import (
    VBASE,
    VKEY,
    VMOTION,
)

# ── Prompt: limits ─────────────────────────────────────────────────────────────────────
# The length ladder. Every rung is the base scene padded with TRUE, non-contradicting sentences
# about the same scene, and every rung ENDS with the same tail instruction, which is checkable
# by a detector. If the tail stops landing, the tail was dropped — that is the whole method.
PROMPT_TAIL = 'A single white goose stands at the far right of the frame.'
PROMPT_PAD = (
    'Padding rule, applied verbatim: sentences are added from PAD_SENTENCES in order, each one true of the '
    "same scene and contradicting nothing, until the rung's word count is reached; then PROMPT_TAIL is "
    'appended as the LAST sentence. No rung ever changes an earlier sentence. The tail is the same at '
    'every rung, so "the tail did not land" can only mean the tail was not read.'
)
PAD_SENTENCES = [
    'The quay is wet basalt cobble.',
    'The water is brown harbour water with a slow chop.',
    'The light is flat North Sea overcast.',
    'Her cloak is coarse wool dyed madder red.',
    'The board is sawn oak.',
    'The letters are brushed in black lamp-black paint.',
    'The gulls are adult herring gulls in summer plumage.',
    'A hemp rope lies coiled on the stones.',
    'A wooden bollard stands at the quay edge.',
    'Brick house fronts rise behind her.',
    'The house windows are leaded in small panes.',
    'A slate roof line crosses the upper frame.',
    'A barrel of salt stands against the wall.',
    'A fishing net hangs drying on a frame.',
    'Her linen cap is tied under the chin.',
    'Her shoes are black leather with a low heel.',
    'The camera is at eye height.',
    'Nothing modern appears anywhere in frame.',
    'The air is still apart from a slow breeze off the water.',
    'A tin lantern hangs unlit by a doorway.',
]

PROBES.append(
    _probe(
        'pd_length_ladder',
        'prompt limits: the length ladder (hard stop, soft stop, usable length, loudness, 77 tokens)',
        ['pd_max_hard', 'pd_max_soft', 'pd_max_words', 'pd_truncation_loud', 'pd_clip77'],
        {
            'prompt': 'per rung, built by the padding rule below and recorded VERBATIM in the trial',
            'motion': VMOTION,
            'negative': NEGATIVE,
            'rungs_words': [20, 60, 120, 250, 500],
            'base': VBASE,
            'tail': PROMPT_TAIL,
            'padding_rule': PROMPT_PAD,
            'pad_sentences': PAD_SENTENCES,
            'measured_against': 'the key of pd_base_damage PLUS the tail check',
        },
        VKEY('the length columns')
        + [
            {
                'check': 'detector_count',
                'detector': 'yolov8n-coco',
                'label': 'bird',
                'n': 3,
                'sample': FR2,
                'share': 1.0,
                'for': 'pd_max_soft',
                'note': 'two gulls plus the tail goose = 3 birds. Back to 2 means the tail was dropped.',
            },
            {
                'check': 'clip_tokens_max',
                'max': 77,
                'tokenizer': 'openai/clip-vit-large-patch14',
                'for': 'pd_clip77',
                'note': "recorded per rung. Rung 1 is inside the window; rungs 2 upwards are past it. The row's own "
                'encoder is also recorded (Wan uses umT5, which has a longer window and drops tail terms quietly).',
            },
            {
                'check': 'log_contains',
                'path': "the row's own run log for this trial",
                'pattern': '(?i)truncat|token limit|max_length|dropped|exceed',
                'for': 'pd_truncation_loud',
            },
            _op(
                'The prompt for this rung ended with "A single white goose stands at the far right of the frame." Is '
                'that goose in the clip, at the right of frame? yes/no'
            ),
        ],
        state_rule=STATE_3OF3,
        state_note=(
            'Five rungs at three seeds. The five fed columns read the same five results:\n'
            '  pd_max_hard        the shortest rung at which the call ERRORS or returns nothing (a transport '
            'failure, recorded as a word count). No rung erroring is the best answer: report 500+.\n'
            '  pd_max_soft        the shortest rung at which the TAIL stops landing (bird count back to 2, or '
            'the operator says no goose) while the call still succeeds — reported in words.\n'
            '  pd_max_words       the longest rung where the whole base key AND the tail land at 3/3 — the '
            'usable length, in words.\n'
            '  pd_truncation_loud yes when the log check fires at exactly the rungs where the tail was dropped; '
            'partial when it fires somewhere but not everywhere; no when the tail vanished in silence.\n'
            '  pd_clip77          yes when the tail lands at a rung whose CLIP token count is above 77 — it read '
            'past the window. no when the tail only ever lands inside 77 tokens.'
        ),
        unit='words',
    )
)

PROBES.append(
    _ladder(
        'pd_unique_things_ladder',
        'prompt limits: unique things describable at once',
        'pd_unique_things',
        [
            {
                'n': n,
                'prompt': 'On a stone quay, all different, no two alike: ' + ', '.join(TERMS[:n]) + '.',
                'motion': 'the camera pans slowly left to right across the quay',
            }
            for n in (2, 4, 8, 12, 20)
        ],
        lambda r: [
            _op(
                'This list is shown: ' + '; '.join(TERMS[: r['n']]) + f'. Are all {r["n"]} present AND all '
                'DIFFERENT from each other — nothing duplicated to fill the frame, nothing merged into a '
                'neighbour? yes/no'
            ),
            {
                'check': 'named_colour_region',
                'region': 'the cloak',
                'colour': 'red',
                'tolerance_deg': 25,
                'sample': FR2,
                'note': 'term 1 is checked mechanically at every rung',
            },
        ],
        note=(
            'The answer is the highest rung at which everything was present and DISTINCT at all three seeds. It '
            'differs from cap_objects, which asks only whether each thing is there: this column fails a rung that '
            'pads the frame with copies. ' + LADDER_NOTE
        ),
    )
)

PROBES.append(
    _ladder(
        'pd_unique_subjects_ladder',
        'prompt limits: named subjects held apart',
        'pd_unique_subjects',
        [
            {
                'n': n,
                'prompt': 'On a stone quay in 1671, standing apart from each other: '
                + ', '.join(
                    f'{nm} in a {c} cloak' for nm, c in list(zip(NAMED[4], ['red', 'blue', 'green', 'brown']))[:n]
                )
                + '. Full body, daylight.',
                'motion': 'they walk past one another and keep walking',
            }
            for n in (2, 3, 4)
        ],
        lambda r: [
            {
                'check': 'identity_cosine_ref',
                'ref': [NAMED_STILL.format(name=nm) for nm in NAMED[4][: r['n']]],
                'min': 0.35,
                'detector': 'insightface-buffalo_l',
                'sample': SAMPLE5,
            },
            {'check': 'mask_iou_max', 'n': r['n'], 'max': 0.1, 'sample': SAMPLE5, 'detector': 'sam2-hiera-small'},
            _op(
                f'These {r["n"]} people are named with different cloak colours and walk PAST each other. Does each '
                'one keep their own face and their own cloak colour all the way through — nobody swapping, '
                'nobody blending as they cross? yes/no'
            ),
        ],
        note=(
            'The answer is the most named subjects kept apart at all three seeds. cap_named asks whether they can be '
            'held at once; this column asks whether they stay DISTINCT while they interact. ' + LADDER_NOTE
        ),
    )
)

ATTRS = ['red', 'wool', 'hooded', 'patched at the shoulder', 'soaked with rain']
PROBES.append(
    _ladder(
        'pd_attrs_per_thing_ladder',
        'prompt limits: attributes per thing that stay bound',
        'pd_attrs_per_thing',
        [
            {
                'n': n,
                'prompt': 'A Dutch woman on a stone quay wearing a cloak that is '
                + ', '.join(ATTRS[:n])
                + '. Everything else plain grey stone. Full body, daylight, 1671.',
                'motion': 'she turns once on the spot and stops',
            }
            for n in (1, 2, 3, 4, 5)
        ],
        lambda r: [
            {
                'check': 'named_colour_region',
                'region': 'the cloak',
                'colour': 'red',
                'tolerance_deg': 25,
                'sample': SAMPLE5,
            },
            _op(
                'The cloak was asked to be: '
                + ', '.join(ATTRS[: r['n']])
                + f'. Are ALL {r["n"]} of those true of the CLOAK — and did none of them land on something else '
                '(the stones soaked instead of the cloak, the patch on her cap)? yes/no'
            ),
        ],
        note='The answer is the most attributes that stayed bound to the one thing, at all three seeds. ' + LADDER_NOTE,
    )
)

INSTRUCTIONS = [
    'she turns the board towards the camera',
    'she takes one step forward',
    'she lowers the board to her waist',
    'she looks left at the gulls',
    'she raises her free hand to her cap',
]
PROBES.append(
    _ladder(
        'pd_instructions_ladder',
        'prompt limits: separate instructions obeyed at once',
        'pd_instructions',
        [{'n': n, 'prompt': VBASE, 'motion': '; '.join(INSTRUCTIONS[:n])} for n in (1, 2, 3, 5)],
        lambda r: [
            _op(
                'These instructions were given: '
                + '; '.join(INSTRUCTIONS[: r['n']])
                + f'. Did ALL {r["n"]} happen in the clip? Order does not matter for this question. yes/no'
            ),
            {'check': 'motion_min', 'min': 0.6},
        ],
        note="The answer is the most instructions all obeyed at all three seeds. Order is pd_action_count's question, not this one. "
        + LADDER_NOTE,
    )
)

CONSTRAINTS = [
    'exactly one person in frame',
    'no lettering anywhere except HAVEN on the board',
    'the camera does not move',
    'no modern object anywhere in frame',
]
PROBES.append(
    _ladder(
        'pd_constraints_ladder',
        'prompt limits: hard constraints honoured together',
        'pd_constraints',
        [
            {'n': n, 'prompt': VBASE + ' Hard constraints: ' + '; '.join(CONSTRAINTS[:n]) + '.', 'motion': VMOTION}
            for n in (1, 2, 3, 4)
        ],
        lambda r: (
            [
                {
                    'check': 'detector_count',
                    'detector': 'yolov8n-coco',
                    'label': 'person',
                    'n': 1,
                    'sample': SAMPLE5,
                    'share': 1.0,
                }
            ]
            + (
                [
                    {
                        'check': 'ocr_equals',
                        'text': 'HAVEN',
                        'detector': 'tesseract-5',
                        'sample': SAMPLE5,
                        'share': 0.8,
                        'note': 'psm 6 over the whole frame',
                    }
                ]
                if r['n'] >= 2
                else []
            )
            + (
                [
                    {
                        'check': 'flow_direction',
                        'direction': 'none',
                        'min': 0.0,
                        'note': 'a static camera: global flow below the noise floor while the subject still moves',
                    }
                ]
                if r['n'] >= 3
                else []
            )
            + [
                _op(
                    'These hard constraints were given: '
                    + '; '.join(CONSTRAINTS[: r['n']])
                    + f'. Were ALL {r["n"]} honoured for the whole clip? yes/no'
                )
            ]
        ),
        note=(
            'The answer is the most constraints honoured TOGETHER at all three seeds. Three of the four have a '
            "mechanical check; the fourth (no modern object) is the operator's. " + LADDER_NOTE
        ),
    )
)

NEG_TERMS = [
    'blurry',
    'watermark',
    'text overlay',
    'extra fingers',
    'deformed hands',
    'melting',
    'morphing',
    'duplicated subject',
    'flicker',
    'colour banding',
    'jpeg artifacts',
    'low quality',
    'subtitles',
    'modern clothing',
    'plastic',
    'wristwatch',
    'car',
    'street lamp',
    'traffic sign',
    'sunglasses',
    'lens flare',
    'bokeh',
    'oversaturated',
    'cartoon',
    'anime',
    'painting',
    'sketch',
    'grain',
    'vignette',
    'chromatic aberration',
    'motion blur',
    'double exposure',
    'tilt shift',
    'fisheye',
    'wide angle distortion',
    'text',
    'logo',
    'signature',
    'frame border',
    'letterbox',
    'noise',
    'posterisation',
    'halo',
    'ringing',
    'smear',
    'ghosting',
    'stutter',
    'tearing',
    'banding',
    'crush',
    'clipping',
    'washed out',
    'muddy',
    'flat',
    'dull',
    'plastic skin',
    'waxy skin',
    'doll face',
    'dead eyes',
    'crossed eyes',
]
assert len(NEG_TERMS) == 60
PROBES.append(
    _ladder(
        'pd_negative_len_ladder',
        'prompt limits: usable negative-prompt length',
        'pd_negative_len',
        [{'n': n, 'prompt': VBASE, 'motion': VMOTION, 'negative': ', '.join(NEG_TERMS[:n])} for n in (5, 15, 30, 60)],
        lambda r: [
            {
                'check': 'ocr_equals',
                'text': 'HAVEN',
                'detector': 'tesseract-5',
                'sample': SAMPLE5,
                'share': 0.8,
                'note': '"text overlay", "subtitles", "logo" and "signature" are all in the negative from rung 1 on; '
                'any second piece of lettering means the negative stopped biting',
            },
            {'check': 'flicker_max', 'max': 12.0, 'note': '"flicker" is in the negative from rung 1 on'},
            _op(
                'The negative prompt listed ' + str(r['n']) + ' things to avoid. Is the clip free of the ones you '
                'can see — no watermark, no caption, no melting, no duplicated subject, no modern object — and is '
                'the asked-for scene (woman, red cloak, HAVEN board, two gulls) still intact? yes/no'
            ),
        ],
        note=(
            'The answer is the longest negative prompt at which the negative still BITES and the positive still '
            'lands, at all three seeds. The failure this catches is the long negative that quietly stops working, or '
            'starts eating the subject. ' + LADDER_NOTE
        ),
    )
)

PROBES.append(
    _ladder(
        'pd_weight_range_ladder',
        'prompt limits: usable emphasis range',
        'pd_weight_range',
        [
            {'n': w, 'prompt': VBASE.replace('a red wool cloak', f'a (red wool cloak:{w})'), 'motion': VMOTION}
            for w in (0.5, 0.8, 1.0, 1.4, 2.0)
        ],
        lambda r: [
            {
                'check': 'named_colour_region',
                'region': 'the cloak',
                'colour': 'red',
                'tolerance_deg': 25,
                'sample': SAMPLE5,
            },
            _op(
                f'The cloak term was weighted {r["n"]}. Is the cloak red, the rest of the scene unharmed, and '
                'nothing burned out, over-saturated or smeared by the emphasis? yes/no'
            ),
            {
                'check': 'ocr_equals',
                'text': 'HAVEN',
                'detector': 'tesseract-5',
                'sample': SAMPLE5,
                'share': 0.8,
                'note': 'a weight that wrecks the rest of the prompt shows up first in the lettering',
            },
        ],
        unit='weight',
        note=(
            'The answer is the WIDEST contiguous span of weights that all passed at three seeds, written as '
            'low-high (for example 0.8-1.4). A row whose prompt syntax has no weights at all is untested here '
            'through TRANSPORT_NA. A rung that errors on the syntax is the edge of the range, not a defect.'
        ),
    )
)

ACTIONS = [
    'she turns the board towards the camera',
    'then she sets the board down',
    'then she takes one step back',
    'then she raises her hand to her cap',
]
PROBES.append(
    _ladder(
        'pd_action_count_ladder',
        'prompt limits: sequential actions in one prompt',
        'pd_action_count',
        [{'n': n, 'prompt': VBASE, 'motion': ', '.join(ACTIONS[:n])} for n in (1, 2, 3, 4)],
        lambda r: [
            _op(
                'These actions were asked for, IN THIS ORDER: '
                + '; '.join(ACTIONS[: r['n']])
                + f'. Did all {r["n"]} happen, in that order, in one clip? yes/no'
            ),
            {'check': 'motion_min', 'min': 0.6},
            {
                'check': 'frames_exact',
                'frames': 81,
                'note': 'the actions must fit the fixed clip length; a row that needs longer answers its truth here',
            },
        ],
        note=(
            'The answer is the most actions performed IN ORDER at all three seeds. Right actions in the wrong order '
            'is a failed rung and the trial says so — that is the difference from pd_instructions. ' + LADDER_NOTE
        ),
    )
)

PROBES += [
    _probe(
        'pd_order_wins',
        'prompt limits: which end of the prompt wins',
        ['pd_order_wins'],
        {
            'prompt': 'per rung, verbatim in `pair`',
            'motion': VMOTION,
            'negative': NEGATIVE,
            'pair': [
                {
                    'id': 'front',
                    'prompt': 'A RED wool cloak. '
                    + VBASE.replace('a red wool cloak', 'a wool cloak')
                    + ' Her cloak is blue.',
                },
                {'id': 'back', 'prompt': VBASE.replace('a red wool cloak', 'a blue wool cloak') + ' Her cloak is red.'},
            ],
        },
        [
            {
                'check': 'named_colour_region',
                'region': 'the cloak',
                'colour': 'red',
                'tolerance_deg': 25,
                'sample': SAMPLE5,
                'for': 'pd_order_wins',
            },
            {
                'check': 'named_colour_region',
                'region': 'the cloak',
                'colour': 'blue',
                'tolerance_deg': 25,
                'sample': SAMPLE5,
                'for': 'pd_order_wins',
            },
            _op(
                'Two clips are shown. In each, the prompt asked for a red cloak at one end and a blue cloak at the '
                'other. For THIS clip, which colour won — red or blue? (Answer yes if you can name one clearly; no '
                'if it is a blend or it changes.)'
            ),
        ],
        state_rule=STATE_3OF3,
        state_note=(
            'The answer is "front", "back" or "neither", not a yes/no: the state is yes when the SAME end '
            'wins in both rungs at all three seeds (the row has a consistent order rule, and the trial '
            'names it), partial when it wins at two seeds, no when the winner changes with the seed — '
            'which means prompt order is not a lever on this row at all.'
        ),
    ),
    _probe(
        'pd_count_words',
        'prompt limits: a counted feature renders that count',
        ['pd_count_words'],
        {
            'prompt': 'Four herring gulls stand in a row on a stone quay wall, side view, overcast daylight.',
            'motion': 'the gulls shuffle a step and settle',
            'negative': NEGATIVE,
        },
        [
            {
                'check': 'detector_count',
                'detector': 'yolov8n-coco',
                'label': 'bird',
                'n': 4,
                'sample': SAMPLE5,
                'share': 1.0,
                'for': 'pd_count_words',
            },
            _op(
                'The prompt said FOUR gulls. Are there exactly four — not three, not five — from the first frame to '
                'the last? yes/no'
            ),
        ],
        state_rule=STATE_3OF3,
        state_note=(
            'The counted word here is a number written as a WORD ("four"), which is the form a house '
            'prompt uses. count_exact asks the same of a digit-free scene with a different subject; both '
            'are kept because a row can pass one and fail the other, and the sheet shows which.'
        ),
    ),
]
