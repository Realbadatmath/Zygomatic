# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Prompt: steering."""

from __future__ import annotations

from .settings import (
    COND_CLIP,
    NEGATIVE,
    SAMPLE5,
    STATE_3OF3,
)
from .probes import (
    PROBES,
    _probe,
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

# ── Prompt: steering ───────────────────────────────────────────────────────────────────
PROBES.append(
    _probe(
        'pd_edit_chain',
        'prompt steering: a small edit, a named fix, and what the fix broke',
        ['pd_small_edit', 'pd_fix_lands', 'pd_fix_breaks'],
        {
            'prompt': 'per step, verbatim in `chain`',
            'motion': VMOTION,
            'negative': NEGATIVE,
            'chain': [
                {'step': 'A', 'prompt': VBASE, 'why': 'the base. Same seed as every other step in the chain.'},
                {
                    'step': 'B',
                    'prompt': VBASE.replace('a red wool cloak', 'a green wool cloak'),
                    'why': 'the SMALL edit: one adjective, nothing else. A small change should follow.',
                },
                {
                    'step': 'C',
                    'prompt': VBASE + ' Her left hand is out of shot behind her back.',
                    'why': 'the FIX, aimed at the commonest defect in step A (a wrong second hand). One added sentence.',
                },
            ],
        },
        [
            {
                'check': 'similarity_min',
                'to': 'A',
                'min': 0.7,
                'for': 'pd_small_edit',
                'note': 'frame-0 perceptual similarity between step B and step A at the same seed: a one-word edit must not '
                'reroll the scene. Measured on the 8x8 DCT hash distance, reported as a ratio.',
            },
            {
                'check': 'named_colour_region',
                'region': 'the cloak',
                'colour': 'green',
                'tolerance_deg': 25,
                'sample': SAMPLE5,
                'for': 'pd_small_edit',
                'note': 'the edit must also LAND, or "no change" would score as a pass',
            },
            {
                'check': 'operator',
                'question': 'Two clips from the same seed are shown. The only prompt difference is the '
                'cloak colour (red, then green). Is the SECOND clip the same scene with a '
                'different cloak — same woman, same pose, same quay, same gulls — rather than '
                'a new scene? yes/no',
                'for': 'pd_small_edit',
            },
            {
                'check': 'hand_landmarks_count',
                'hands': 1,
                'fingers': 5,
                'sample': SAMPLE5,
                'share': 0.8,
                'for': 'pd_fix_lands',
                'note': 'step C asked for one visible hand; the fix landed if exactly one clean hand is found',
            },
            {
                'check': 'operator',
                'question': 'The prompt for this clip added "Her left hand is out of shot behind her '
                'back". Is exactly one hand visible, and is it correct — five fingers, none '
                'fused, none extra? yes/no',
                'for': 'pd_fix_lands',
            },
            {
                'check': 'similarity_min',
                'to': 'A',
                'min': 0.7,
                'for': 'pd_fix_breaks',
                'note': 'the fix must not reroll the scene either',
            },
            {
                'check': 'ocr_equals',
                'text': 'HAVEN',
                'detector': 'tesseract-5',
                'sample': SAMPLE5,
                'share': 0.8,
                'for': 'pd_fix_breaks',
            },
            {
                'check': 'detector_count',
                'detector': 'yolov8n-coco',
                'label': 'bird',
                'n': 2,
                'sample': FR2,
                'share': 1.0,
                'for': 'pd_fix_breaks',
            },
            {
                'check': 'operator',
                'question': 'Compare this clip with the base clip from the same seed. The prompt added one '
                'sentence about the left hand. Did anything ELSE change for the worse — the '
                'lettering, the gulls, the cloak, her face, the light? Answer yes if nothing '
                'else got worse.',
                'for': 'pd_fix_breaks',
            },
        ],
        cond=dict(COND_CLIP, note='all three steps at the SAME seed, so a difference is the edit and not the roll'),
        state_rule=STATE_3OF3,
        state_note=(
            'One chain, three steps, one seed set. pd_small_edit reads A versus B; pd_fix_lands reads C alone; '
            'pd_fix_breaks reads C against A. A row that rerolls the whole scene on a one-word edit is a no on '
            'pd_small_edit even when the edit landed — the column is about proportion, not obedience.'
        ),
    )
)

PROBES += [
    _probe(
        'pd_seed_vs_prompt',
        'prompt steering: prompt beats seed',
        ['pd_seed_vs_prompt'],
        {
            'prompt': 'the grid in `grid`, verbatim',
            'motion': VMOTION,
            'negative': NEGATIVE,
            'grid': {
                'prompts': [
                    VBASE,
                    VBASE.replace('a red wool cloak', 'a green wool cloak'),
                    VBASE.replace('a red wool cloak', 'a black wool cloak'),
                ],
                'seeds': [11, 12, 13],
                'note': '3 prompts x 3 seeds = 9 clips. The cloak colour is the only thing that varies in the '
                'prompt; the seed varies everything the model is free to choose.',
            },
        },
        [
            {
                'check': 'named_colour_region',
                'region': 'the cloak',
                'colour': 'per prompt (red, green, black)',
                'tolerance_deg': 25,
                'sample': FR2,
                'for': 'pd_seed_vs_prompt',
                'note': 'the asked-for colour must win in all 9 cells; black is checked as low value, not a hue',
            },
            {
                'check': 'pairwise_similarity_max',
                'max': 0.98,
                'for': 'pd_seed_vs_prompt',
                'note': 'across seeds at one prompt the clips must actually differ, or the grid proves nothing',
            },
            _op(
                'Nine clips are shown in a 3x3 grid, three cloak colours down and three seeds across. Does the '
                'COLOUR follow the row it is in (the prompt) rather than the column (the seed) — every clip in a row '
                "showing that row's colour? yes/no"
            ),
        ],
        cond=dict(COND_CLIP, repeats=9, note='3 prompts x 3 seeds, all nine clips kept'),
        state_rule={'yes': 1.0, 'partial': 0.67},
        state_note=(
            'yes when the prompted colour lands in all 9 cells; partial when it lands in 6 or more; no '
            'below that — at which point the seed is deciding and the prompt is a suggestion. The '
            'pairwise check is a guard: if the three seeds produce identical clips the row is not seeded '
            'at all and the trial is recorded untested, not a yes.'
        ),
    ),
    _probe(
        'pd_reusable',
        'prompt steering: the prompt works on the next subject',
        ['pd_reusable'],
        {
            'prompt': 'the same sentence with the SUBJECT swapped, verbatim in `pair`',
            'motion': VMOTION,
            'negative': NEGATIVE,
            'pair': [
                {'id': 'woman', 'prompt': VBASE},
                {
                    'id': 'man',
                    'prompt': VBASE.replace('A Dutch woman', 'A Dutch man').replace('to her left', 'to his left'),
                },
                {
                    'id': 'boy',
                    'prompt': VBASE.replace('A Dutch woman', 'A Dutch boy of about ten').replace(
                        'to her left', 'to his left'
                    ),
                },
            ],
        },
        VKEY('pd_reusable')
        + [
            _op(
                'The same prompt was used for a woman, a man and a boy. Did all three clips obey it equally — '
                'board turned and readable, two gulls to their left, red cloak — with no version where the swap '
                'broke the rest of the scene? yes/no'
            )
        ],
        cond=dict(COND_CLIP, repeats=9, note='3 subjects x 3 seeds'),
        state_rule={'yes': 1.0, 'partial': 0.67},
        state_note=(
            'yes when all three subjects pass the key at all three seeds; partial when two of three '
            'subjects do; no when the prompt only works on the subject it was written for. The person '
            'count check is read as "exactly one person", whichever it is.'
        ),
    ),
    _probe(
        'pd_motion_words',
        'prompt steering: motion verbs actually drive motion',
        ['pd_motion_words'],
        {
            'prompt': 'One Dutch dockworker in a brown wool coat stands on a stone quay, full body, daylight, 1671.',
            'negative': NEGATIVE,
            'pair': [
                {'id': 'still', 'motion': 'he stands completely still and does not move'},
                {'id': 'walk', 'motion': 'he walks briskly from the left of frame to the right of frame'},
                {'id': 'run', 'motion': 'he runs from the right of frame to the left of frame'},
            ],
        },
        [
            {
                'check': 'flow_direction',
                'direction': 'right',
                'min': 0.8,
                'for': 'pd_motion_words',
                'note': 'the WALK rung: the subject mask must travel left to right',
            },
            {
                'check': 'flow_direction',
                'direction': 'left',
                'min': 1.2,
                'for': 'pd_motion_words',
                'note': 'the RUN rung: the same but faster and the other way, so "run" must differ from "walk"',
            },
            {
                'check': 'flow_region',
                'region': 'the dockworker',
                'min': 0.0,
                'max': 0.6,
                'detector': 'sam2-hiera-small',
                'for': 'pd_motion_words',
                'note': 'the STILL rung: near-zero flow inside his own mask',
            },
            {
                'check': 'motion_min',
                'min': 0.6,
                'for': 'pd_motion_words',
                'note': 'the walk and run rungs must both actually move',
            },
            _op(
                'Three clips from one prompt with three motion phrases: stand still, walk left-to-right, run '
                'right-to-left. Does each clip do what its phrase said, in the named direction, with the run clearly '
                'faster than the walk? yes/no'
            ),
        ],
        cond=dict(COND_CLIP, repeats=9, note='3 motion phrases x 3 seeds'),
        state_rule={'yes': 1.0, 'partial': 0.67},
        state_note=(
            'yes when all three phrases land at all three seeds. On Wan, a failure here is usually the '
            "SHIFT and not the words — the trial records the row's shift so the reader can tell an "
            'unmoving model from an unread verb [[project_wan_motion_debug]].'
        ),
    ),
    _probe(
        'pd_camera_words',
        'prompt steering: camera language is obeyed',
        ['pd_camera_words'],
        {
            'prompt': VBASE,
            'negative': NEGATIVE,
            'pair': [
                {'id': 'static', 'motion': 'the camera does not move; she turns the board towards it'},
                {'id': 'push', 'motion': 'the camera pushes slowly in towards her; she holds the board still'},
                {'id': 'pan_left', 'motion': 'the camera pans steadily to the left; she holds the board still'},
            ],
        },
        [
            {
                'check': 'flow_direction',
                'direction': 'none',
                'min': 0.0,
                'for': 'pd_camera_words',
                'note': 'the STATIC rung: global flow at the frame edges below the noise floor',
            },
            {
                'check': 'flow_direction',
                'direction': 'in',
                'min': 0.4,
                'for': 'pd_camera_words',
                'note': 'the PUSH rung: outward radial flow at the edges',
            },
            {
                'check': 'flow_direction',
                'direction': 'left',
                'min': 0.6,
                'for': 'pd_camera_words',
                'note': 'the PAN rung: uniform horizontal flow at the edges',
            },
            {
                'check': 'bbox_frac',
                'subject': 'the woman',
                'min': 0.35,
                'max': 0.95,
                'sample': FR2,
                'detector': 'sam2-hiera-small',
                'for': 'pd_camera_words',
                'note': 'on the push rung she must grow in frame; recorded for all three',
            },
            _op(
                'Three clips: static camera, slow push in, pan left. Does each clip do the named camera move and '
                'only that move — no drift on the static one, no pan on the push, no zoom on the pan? yes/no'
            ),
        ],
        cond=dict(COND_CLIP, repeats=9, note='3 camera phrases x 3 seeds'),
        state_rule={'yes': 1.0, 'partial': 0.67},
    ),
    _probe(
        'pd_prompt_vs_plate',
        'prompt steering: the prompt still matters beside the plate',
        ['pd_prompt_vs_plate'],
        {
            'image': 'fixtures/video/subjects/person_woman_cloak.png',
            'prompt': 'per rung, verbatim in `pair`',
            'negative': NEGATIVE,
            'pair': [
                {
                    'id': 'plate_only',
                    'prompt': '',
                    'motion': VMOTION,
                    'note': 'the input still with an empty positive prompt',
                },
                {
                    'id': 'plate_plus',
                    'prompt': 'She lowers the board and looks to her left at two gulls on the wall.',
                    'motion': 'she lowers the board and looks left at the gulls',
                },
                {
                    'id': 'plate_against',
                    'prompt': 'Her cloak is green.',
                    'motion': VMOTION,
                    'note': 'a prompt that CONTRADICTS the plate, where the plate should win',
                },
            ],
        },
        [
            {
                'check': 'detector_count',
                'detector': 'yolov8n-coco',
                'label': 'bird',
                'n': 2,
                'sample': [80],
                'share': 1.0,
                'for': 'pd_prompt_vs_plate',
                'note': 'the plate_plus rung: the gulls the prompt added must appear by the last frame',
            },
            {
                'check': 'named_colour_region',
                'region': 'the cloak',
                'colour': 'red',
                'tolerance_deg': 25,
                'sample': SAMPLE5,
                'for': 'pd_prompt_vs_plate',
                'note': 'the plate_against rung: the PLATE is red and should win over the word green',
            },
            _op(
                'Three clips from one input still: no prompt, a prompt adding an action, and a prompt contradicting '
                'the still. Did the added action land in the second, and did the still (not the word) decide the '
                'cloak colour in the third? yes/no'
            ),
        ],
        cond=dict(COND_CLIP, repeats=9, note='3 rungs x 3 seeds'),
        state_rule={'yes': 1.0, 'partial': 0.67},
        state_note=(
            'This column has two halves and both must hold: the prompt must be able to ADD (rung 2) and '
            'must not be able to OVERWRITE the pixels it was given (rung 3). A row that ignores the '
            'prompt entirely fails the first; a row that repaints the plate fails the second. A t2v row '
            'takes no plate and is untested here through TRANSPORT_NA.'
        ),
    ),
    _probe(
        'pd_dimension_words',
        'prompt steering: named dimensions are honoured',
        ['pd_dimension_words'],
        {
            'prompt': 'A wooden board exactly two metres long and twenty centimetres wide leans against a stone quay '
            'wall beside a barrel one metre high. A 30 cm ruler lies on the stones in front of them. '
            'Daylight, 1671.',
            'motion': 'the camera tracks slowly along the board from end to end',
            'negative': NEGATIVE,
        },
        [
            {
                'check': 'metric_within',
                'metric': 'board length in ruler lengths',
                'target': 6.7,
                'tol': 1.5,
                'unit': 'ruler lengths',
                'for': 'pd_dimension_words',
                'note': 'the 30 cm ruler in frame is the scale bar: a 2 m board is 6.7 rulers long. Measured from the '
                'SAM2 masks of board and ruler, which is why the ruler is in the prompt.',
            },
            _op(
                'The prompt said the board is two metres long and twenty centimetres wide, the barrel one metre '
                'high, and there is a 30 cm ruler on the stones. Using the ruler as the scale, are the board and '
                'the barrel about the sizes asked for — the board roughly ten times its own width, the barrel half '
                "the board's length? yes/no"
            ),
        ],
        state_rule=STATE_3OF3,
        state_note=(
            'A dimension is only checkable against something in frame, so the ruler is part of the fixed '
            'input. The mechanical check is the ratio; the operator sees whether the scene is absurd in a '
            'way the ratio misses. Both must pass.'
        ),
    ),
    _probe(
        'pd_spatial_words',
        'prompt steering: placement language is obeyed',
        ['pd_spatial_words'],
        {
            'prompt': 'On a stone quay: a red barrel in the LEFT THIRD of the frame, a blue crate in the RIGHT THIRD, '
            'and a coil of rope BETWEEN them in the centre, nearer the camera than both. Wide shot, daylight.',
            'motion': 'the camera holds still while gulls cross the sky behind',
            'negative': NEGATIVE,
        },
        [
            {
                'check': 'bbox_left_of',
                'a': 'the red barrel',
                'b': 'the blue crate',
                'share': 1.0,
                'sample': FR2,
                'detector': 'sam2-hiera-small',
                'for': 'pd_spatial_words',
            },
            {
                'check': 'named_colour_region',
                'region': 'the left-third object',
                'colour': 'red',
                'tolerance_deg': 25,
                'sample': FR2,
                'for': 'pd_spatial_words',
            },
            {
                'check': 'named_colour_region',
                'region': 'the right-third object',
                'colour': 'blue',
                'tolerance_deg': 25,
                'sample': FR2,
                'for': 'pd_spatial_words',
            },
            _op(
                'The prompt placed a red barrel in the left third, a blue crate in the right third and a rope coil '
                'between them nearer the camera. Are all three where they were asked to be, in both the first and '
                'the last frame? yes/no'
            ),
        ],
        state_rule=STATE_3OF3,
    ),
]
