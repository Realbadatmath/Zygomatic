# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""image_shared.count_space — counting & quantity probes and space & relation probes."""

from __future__ import annotations

from capability_tests.image_shared.probes import PROBES, _probe
from capability_tests.image_shared.steer_capacity import QUAY

# ── Counting & quantity ────────────────────────────────────────────────────────────────────
PROBES += [
    _probe(
        'count_exact',
        'Counting: a small exact number of one thing',
        ['count_exact'],
        'Three wooden barrels stand apart from one another ' + QUAY + ', nobody present, nothing else in frame.',
        [{'check': 'open_vocab_count', 'query': 'wooden barrel', 'min_score': 0.3, 'count': 3}],
        state_note='Wholly mechanical. Three is the number the house asks for most and the '
        'number image models most often turn into two or four.',
    ),
    _probe(
        'count_large',
        'Counting: a number past where models stop counting',
        ['count_large'],
        'Fourteen white gulls stand on the quay wall ' + QUAY + ', nobody present, nothing else in frame.',
        [{'check': 'detector_count', 'class': 'bird', 'count': 14}],
        state_note='Wholly mechanical (YOLO bird). Expected to be a no on every row in the '
        'house; the cell exists so the sheet says so instead of leaving it blank, '
        'and the trial keeps the number that WAS rendered.',
    ),
    _probe(
        'count_people',
        'Counting: an exact number of people',
        ['count_people'],
        'Five Dutch dockworkers stand in a row ' + QUAY + ', all five whole bodies in frame, facing the camera.',
        [
            {'check': 'detector_count', 'class': 'person', 'count': 5},
            {
                'check': 'operator',
                'question': 'Are there exactly five whole separate people, no more and no fewer? yes/no',
            },
        ],
        state_note='YOLO decides the count; the operator catches the half figure at the edge '
        'that the detector counts as a person and the house would not.',
    ),
    _probe(
        'count_fingers',
        'Counting: five fingers on one hand',
        ['count_fingers'],
        'Close-up of one open human right hand, palm to the camera, all five fingers spread '
        'wide and clearly separated, against a plain grey cloth in plain daylight.',
        [
            {'check': 'hand_landmarks', 'hands': 1, 'min_tip_px': 16},
            {
                'check': 'operator',
                'question': 'Does this hand have exactly five fingers, none fused, none missing, none extra? yes/no',
            },
        ],
        state_note='The house sore point. MediaPipe is authority for the count and the '
        'separation of the fingertips; the operator is authority for a sixth '
        'finger the detector merged into a neighbour, which is exactly what the '
        '2026-09-27 defect bench showed no VLM catches.',
    ),
    _probe(
        'count_legs',
        'Counting: four legs on one animal',
        ['count_legs'],
        'One brown draught horse stands in a flat grass field, Holland, 1671, plain daylight, '
        'whole body in frame, seen from the side, all four legs clearly visible and separate.',
        [
            {'check': 'detector_count', 'class': 'horse', 'count': 1},
            {
                'check': 'operator',
                'question': 'Does this horse have exactly four legs, each whole and separate, correctly jointed? yes/no',
            },
        ],
        state_note='There is no leg detector the house trusts, so the count is the operator '
        'and the detector only confirms that ONE horse is there to count the legs '
        'of. Said plainly rather than dressed up as measured.',
    ),
    _probe(
        'count_windows',
        'Counting: an exact number of a repeated building feature',
        ['count_windows'],
        'A brick canal house front, Amsterdam, 1671, plain daylight, seen straight on, with '
        'exactly nine leaded windows in three rows of three, nobody present.',
        [
            {'check': 'open_vocab_count', 'query': 'window', 'min_score': 0.3, 'count': 9},
            {'check': 'operator', 'question': 'Are there exactly nine windows in three even rows of three? yes/no'},
        ],
        state_note='GroundingDINO counts the windows; the operator carries the arrangement, '
        'because nine windows in a scatter is a different failure from nine in a '
        'grid and the sheet should not read them the same.',
    ),
    _probe(
        'count_absent',
        'Counting: zero of a thing the prompt names',
        ['count_absent'],
        'The empty stone quay at Kattenburg, Amsterdam, 1671, plain daylight, no people and '
        'no animals anywhere, only wet cobbles and the harbour water.',
        [
            {'check': 'detector_count', 'class': 'person', 'count': 0},
            {'check': 'open_vocab_absent', 'terms': ['dog', 'cat', 'horse', 'bird'], 'min_score': 0.3},
        ],
        state_note='Wholly mechanical and the hardest count there is: zero. Naming a thing in '
        'order to forbid it is what image models handle worst, which is why '
        'pd_negation and pd_pos_neg_split ask it two more ways.',
    ),
    _probe(
        'count_more_less',
        'Counting: a relative quantity between two kinds of thing',
        ['count_more_less'],
        'Seven wooden crates and three wooden barrels stand ' + QUAY + ', the crates plainly '
        'more numerous than the barrels, nobody present.',
        [
            {'check': 'open_vocab_count', 'query': 'wooden crate', 'min_score': 0.3, 'count': 7},
            {'check': 'open_vocab_count', 'query': 'wooden barrel', 'min_score': 0.3, 'count': 3},
        ],
        state_note='Mechanical, and scored in two steps the trial keeps apart: the exact pair '
        '7/3 (strict), and the weaker claim that crates OUTNUMBER barrels. A row '
        'that gets 6/2 fails the cell but the note records that the relation '
        'held — the useful finding for a house that mostly needs "more of these".',
    ),
]

# ── Space & relation ───────────────────────────────────────────────────────────────────────
_SP_SCENE = ' ' + QUAY + ', nobody present.'
PROBES += [
    _probe(
        'sp_left_right',
        'Space: left and right',
        ['sp_left_right'],
        'A red barrel on the left and a blue crate on the right' + _SP_SCENE,
        [
            {
                'check': 'spatial_relation',
                'a': 'wooden barrel',
                'b': 'wooden crate',
                'relation': 'left_of',
                'margin_px': 60,
            },
            {'check': 'colour_of_thing', 'thing': 'wooden barrel', 'colour': 'red', 'min_share': 0.4},
            {'check': 'colour_of_thing', 'thing': 'wooden crate', 'colour': 'blue', 'min_share': 0.4},
        ],
        state_note='Wholly mechanical: two boxes and 60 px of slack. The colours are in the '
        'checks because a model that swaps the colours has also failed the '
        'relation — it is the pair that was asked for, not two boxes.',
    ),
    _probe(
        'sp_front_behind',
        'Space: in front of and behind',
        ['sp_front_behind'],
        'A red barrel stands in front of a blue crate, the barrel nearer the camera and '
        'partly covering the crate' + _SP_SCENE,
        [
            {
                'check': 'spatial_relation',
                'a': 'wooden barrel',
                'b': 'wooden crate',
                'relation': 'overlaps',
                'margin_px': 0,
            },
            {
                'check': 'spatial_relation',
                'a': 'wooden barrel',
                'b': 'wooden crate',
                'relation': 'larger',
                'margin_px': 0,
            },
            {
                'check': 'operator',
                'question': 'Is the barrel clearly nearer the camera than the crate, overlapping and hiding part of it? yes/no',
            },
        ],
        state_note='Depth cannot be read from two boxes alone, so the mechanical half only '
        'establishes overlap and that the nearer thing is the larger one. The '
        'operator decides depth. Said plainly: this cell is operator-led.',
    ),
    _probe(
        'sp_on_under',
        'Space: on top of and underneath',
        ['sp_on_under'],
        'A wicker basket stands on top of a wooden crate, and a coil of rope lies underneath the crate' + _SP_SCENE,
        [
            {
                'check': 'spatial_relation',
                'a': 'wicker basket',
                'b': 'wooden crate',
                'relation': 'above',
                'margin_px': 20,
            },
            {
                'check': 'spatial_relation',
                'a': 'coiled rope',
                'b': 'wooden crate',
                'relation': 'below',
                'margin_px': 20,
            },
            {
                'check': 'operator',
                'question': 'Is the basket resting on the crate and the rope underneath it, rather than merely higher and lower in the picture? yes/no',
            },
        ],
        state_note='Two mechanical relations plus the operator, because "above in the frame" '
        'and "resting on" are not the same claim and only a person can tell them '
        'apart. Both must pass.',
    ),
    _probe(
        'sp_inside',
        'Space: inside a container',
        ['sp_inside'],
        'Three apples lie inside an open wicker basket' + _SP_SCENE,
        [
            {'check': 'spatial_relation', 'a': 'apple', 'b': 'wicker basket', 'relation': 'inside', 'margin_px': 0},
            {'check': 'open_vocab_count', 'query': 'apple', 'min_score': 0.3, 'count': 3},
        ],
        state_note='Wholly mechanical: every apple box inside the basket box, and exactly '
        'three of them. Containment is the one spatial relation two boxes settle '
        'honestly.',
    ),
    _probe(
        'sp_near_far',
        'Space: near the camera and far from it',
        ['sp_near_far'],
        'A red barrel stands close to the camera in the foreground and a blue crate stands '
        'far away at the end of the quay' + _SP_SCENE,
        [
            {
                'check': 'spatial_relation',
                'a': 'wooden barrel',
                'b': 'wooden crate',
                'relation': 'larger',
                'margin_px': 0,
            },
            {
                'check': 'spatial_relation',
                'a': 'wooden barrel',
                'b': 'wooden crate',
                'relation': 'below',
                'margin_px': 40,
            },
            {
                'check': 'operator',
                'question': 'Is the barrel plainly close to the camera and the crate plainly far away down the quay? yes/no',
            },
        ],
        state_note='The mechanical half is the two things perspective gives a near object in '
        'a level shot: it is larger and it sits lower in the frame. The operator '
        'decides the distance itself.',
    ),
    _probe(
        'sp_touching',
        'Space: touching, not merely adjacent',
        ['sp_touching'],
        'A red barrel and a blue crate stand touching one another, side by side, their sides in contact' + _SP_SCENE,
        [
            {
                'check': 'spatial_relation',
                'a': 'wooden barrel',
                'b': 'wooden crate',
                'relation': 'overlaps',
                'margin_px': 0,
            },
            {
                'check': 'operator',
                'question': 'Are the barrel and the crate actually touching, with no gap and without merging into one object? yes/no',
            },
        ],
        state_note='Operator-led on purpose: overlapping boxes cannot tell a contact from a '
        'merge, and a merge is the failure worth knowing about. Read beside '
        'cap_objects, which asks whether N things stay N things.',
    ),
    _probe(
        'sp_holding_who',
        'Space: which person holds the thing',
        ['sp_holding_who'],
        'Two Dutch dockworkers stand side by side'
        + _SP_SCENE.replace('nobody present.', 'both whole bodies in frame:')
        + ' the man on the left holds an unlit lantern in his right hand, the man on the right '
        'holds nothing at all.',
        [
            {'check': 'detector_count', 'class': 'person', 'count': 2},
            {'check': 'open_vocab_count', 'query': 'lantern', 'min_score': 0.3, 'count': 1},
            {
                'check': 'operator',
                'question': 'Is the lantern held by the LEFT of the two men, in his hand, with the right-hand man holding nothing? yes/no',
            },
        ],
        state_note='The mechanical half establishes two people and one lantern; which of them '
        'holds it is the operator, because no detector in the house binds an object '
        'to a person. This is the single most common house failure and the cell '
        'says openly that it is judged by eye.',
    ),
    _probe(
        'sp_relative_size',
        'Space: one thing larger than another',
        ['sp_relative_size'],
        'A wooden barrel twice the height of the wicker basket beside it, the two standing together' + _SP_SCENE,
        [
            {
                'check': 'spatial_relation',
                'a': 'wooden barrel',
                'b': 'wicker basket',
                'relation': 'larger',
                'margin_px': 0,
            },
            {
                'check': 'operator',
                'question': 'Is the barrel about twice the height of the basket — clearly bigger, but not ten times bigger? yes/no',
            },
        ],
        state_note='Mechanical on which is larger, operator on HOW MUCH larger, because "about '
        'twice" is a judgement and a box ratio on a tilted object is not.',
    ),
    _probe(
        'sp_occlusion',
        'Space: one thing partly hidden by another',
        ['sp_occlusion'],
        'A blue crate stands behind a red barrel, the left half of the crate hidden by the '
        'barrel, its right half visible' + _SP_SCENE,
        [
            {
                'check': 'spatial_relation',
                'a': 'wooden barrel',
                'b': 'wooden crate',
                'relation': 'overlaps',
                'margin_px': 0,
            },
            {'check': 'open_vocab_count', 'query': 'wooden crate', 'min_score': 0.25, 'count': 1},
            {
                'check': 'operator',
                'question': 'Is the crate partly hidden behind the barrel, with the hidden part simply absent rather than shown through the barrel or bent around it? yes/no',
            },
        ],
        state_note='Operator-led. Occlusion fails by the hidden part being drawn anyway or '
        'the object bending round the obstacle, and neither is visible to a box.',
    ),
    _probe(
        'sp_direction',
        'Space: which way the subject faces',
        ['sp_direction'],
        'A Dutch shipwright stands alone'
        + _SP_SCENE.replace('nobody present.', 'his whole body in frame,')
        + ' turned to face the left edge of the picture, in exact side profile, walking that way.',
        [
            {'check': 'detector_count', 'class': 'person', 'count': 1},
            {'check': 'operator', 'question': 'Is the man in side profile facing the LEFT edge of the picture? yes/no'},
        ],
        state_note='Facing is the operator alone; no pose detector in the house reports a '
        'facing direction the sheet could quote. The detector only confirms there '
        'is one person to have a direction.',
    ),
]
