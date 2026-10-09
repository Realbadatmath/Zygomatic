# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Prompt bands: one base prompt and one damaged variant per pd_* column."""

from __future__ import annotations

from .settings import (
    COND_ONE,
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

# ── Prompt bands: ONE base prompt with a mechanically checkable key, then one damaged ──────
# VARIANT per column, measured against the SAME key. This mirrors text_shared's extraction
# task: the only thing that changes between the base and a variant is the damage under test,
# so a difference in the result is that damage and nothing else.
VBASE = (
    'A Dutch woman in a red wool cloak stands on a stone quay holding a wooden board painted HAVEN. '
    'Two herring gulls stand on the wall to her left. Daylight, 1671.'
)
VMOTION = 'she turns the board towards the camera and holds it still'


def VKEY(scored='the prompt'):
    """The key the base and EVERY variant are measured against, written out. Four mechanical
    checks and one operator question; all five must pass for a trial to count as obeyed."""
    return [
        {'check': 'ocr_equals', 'text': 'HAVEN', 'detector': 'tesseract-5', 'sample': SAMPLE5, 'share': 0.8},
        {'check': 'detector_count', 'detector': 'yolov8n-coco', 'label': 'person', 'n': 1, 'sample': FR2, 'share': 1.0},
        {'check': 'detector_count', 'detector': 'yolov8n-coco', 'label': 'bird', 'n': 2, 'sample': FR2, 'share': 1.0},
        {'check': 'named_colour_region', 'region': 'the cloak', 'colour': 'red', 'tolerance_deg': 25, 'sample': FR2},
        {
            'check': 'operator',
            'question': 'One woman in a red cloak, a board reading HAVEN turned towards the camera '
            'by the end, and two gulls on the wall to HER left. Are all four true of '
            'this clip, on a woman who stays whole throughout? yes/no',
            'note': 'scored for ' + scored,
        },
    ]


VAR_NOTE = (
    'The variant is measured against the SAME key as the base (probe `pd_base_damage`, rung "strong"). '
    'The column is yes when the variant scores as well as the base at all three seeds, partial at two, '
    'no below — so this measures the DAMAGE, not the model. A variant that scores BETTER than the base '
    'is still a yes, with the difference in the trial: it means the base wording was not the best one, '
    'which is worth knowing.'
)

PROBES.append(
    _probe(
        'pd_base_damage',
        'prompt damage: how badly a weak prompt hurts the output',
        ['pd_damage'],
        {
            'prompt': VBASE,
            'motion': VMOTION,
            'negative': NEGATIVE,
            'pair': [
                {'rung': 'strong', 'prompt': VBASE, 'motion': VMOTION},
                {'rung': 'weak', 'prompt': 'woman on a quay with a sign and some birds', 'motion': 'she moves'},
            ],
        },
        VKEY('pd_damage'),
        state_rule=STATE_3OF3,
        state_note=(
            'Both rungs are rendered at all three seeds against the same key. pd_damage reads the DROP: yes '
            '(= the prompt matters little) when the weak rung scores within one check of the strong one; '
            'partial when it loses two or three; no when the weak rung collapses. The strong rung is also the '
            'reference every variant probe below is compared against, so it is rendered once and reused.'
        ),
    )
)

VARIANTS = [
    (
        'pd_paraphrase',
        'survives a paraphrase',
        'On a stone quay in 1671, a Dutch woman wearing a red wool cloak holds up a wooden board with HAVEN painted on it, '
        'and two herring gulls stand on the wall to her left, in daylight.',
    ),
    (
        'pd_word_order',
        'word order does not decide the result',
        'Daylight, 1671. Two herring gulls stand on the wall to her left. A wooden board painted HAVEN is held by a Dutch '
        'woman in a red wool cloak, standing on a stone quay.',
    ),
    (
        'pd_synonym',
        'treats synonyms as the same thing',
        'A Netherlandish female in a crimson woollen mantle stands on a stone wharf holding a timber plank lettered HAVEN. '
        'Two seagulls stand on the parapet to her left. Sunlight, 1671.',
    ),
    (
        'pd_typo',
        'survives a typo',
        'A Dutch womn in a red wool claok stands on a stone quay holding a wooden boadr painted HAVEN. Two herring gulls '
        'stand on the wall to her leftt. Daylight, 1671.',
    ),
    (
        'pd_grammar',
        'survives broken grammar',
        'Dutch woman red wool cloak stand stone quay, she holding wooden board paint HAVEN, two herring gull stand on wall '
        'her left side, daylight, 1671 year.',
    ),
    (
        'pd_punctuation',
        'punctuation does not change the parse',
        'A Dutch woman in a red wool cloak stands on a stone quay holding a wooden board painted HAVEN two herring gulls '
        'stand on the wall to her left daylight 1671',
    ),
    (
        'pd_case',
        'capitalisation changes nothing',
        'a dutch woman in a RED WOOL CLOAK stands on a STONE QUAY holding a wooden board painted haven. two HERRING GULLS '
        'stand on the wall to her LEFT. daylight, 1671.',
    ),
    (
        'pd_filler',
        'ignores filler words',
        'Please could you kindly show, if possible, a really quite beautiful Dutch woman in a red wool cloak who stands '
        'there on a stone quay just holding a wooden board painted HAVEN, and also two herring gulls that stand on the '
        'wall to her left, in nice daylight, 1671, thank you very much.',
    ),
    (
        'pd_repetition',
        'repeating a term is safe',
        'A Dutch woman in a red, red, red wool cloak stands on a stone quay holding a wooden board painted HAVEN, HAVEN. '
        'Two herring gulls, two gulls, stand on the wall to her left. Daylight, daylight, 1671.',
    ),
    (
        'pd_multilingual',
        'a non-English prompt works as well',
        'Een Nederlandse vrouw in een rode wollen mantel staat op een stenen kade en houdt een houten bord vast waarop '
        'HAVEN is geschilderd. Twee zilvermeeuwen staan op de muur aan haar linkerkant. Daglicht, 1671.',
    ),
]

for _col, _what, _prompt in VARIANTS:
    PROBES.append(
        _probe(
            'pdv_' + _col[3:],
            'prompt damage: ' + _what,
            [_col],
            {
                'prompt': _prompt,
                'motion': VMOTION,
                'negative': NEGATIVE,
                'measured_against': 'the key of pd_base_damage, unchanged',
            },
            VKEY(_col),
            state_rule=STATE_3OF3,
            state_note=VAR_NOTE,
        )
    )

# The seven damage questions that are not a variant of the base wording but a different prompt.
PROBES += [
    _probe(
        'pdv_contradiction',
        'prompt damage: handles a contradiction predictably',
        ['pd_contradiction'],
        {
            'prompt': VBASE.replace('a red wool cloak', 'a red wool cloak, and her cloak is blue'),
            'motion': VMOTION,
            'negative': NEGATIVE,
        },
        [
            {
                'check': 'named_colour_region',
                'region': 'the cloak',
                'colour': 'red',
                'tolerance_deg': 25,
                'sample': SAMPLE5,
                'for': 'pd_contradiction',
                'note': 'EITHER this OR the blue reading passes; the failure is neither',
            },
            {
                'check': 'named_colour_region',
                'region': 'the cloak',
                'colour': 'blue',
                'tolerance_deg': 25,
                'sample': SAMPLE5,
                'for': 'pd_contradiction',
            },
            {'check': 'flicker_max', 'max': 12.0, 'for': 'pd_contradiction'},
            _op(
                'The prompt asked for a cloak that is both red and blue. Does the clip settle on ONE of the two and '
                'hold it for the whole clip, rather than a purple blend, a half-and-half cloak, or a cloak that '
                'changes colour as it goes? yes/no'
            ),
        ],
        state_rule=STATE_3OF3,
        state_note=(
            '"Predictably" means it picks one reading and keeps it — which one does not matter and is '
            'recorded in the trial. A yes needs the operator question AND exactly ONE of the two colour '
            'checks passing at all five sampled frames. Both failing, or the two swapping between '
            'frames, is a no.'
        ),
    ),
    _probe(
        'pdv_negation',
        'prompt damage: understands a negation in the prompt',
        ['pd_negation'],
        {
            'prompt': VBASE + ' There is NO dog anywhere in this scene and NO boat on the water.',
            'motion': VMOTION,
            'negative': NEGATIVE,
        },
        [
            {
                'check': 'detector_count',
                'detector': 'yolov8n-coco',
                'label': 'dog',
                'n': 0,
                'sample': SAMPLE5,
                'share': 1.0,
                'for': 'pd_negation',
            },
            {
                'check': 'detector_count',
                'detector': 'yolov8n-coco',
                'label': 'boat',
                'n': 0,
                'sample': SAMPLE5,
                'share': 1.0,
                'for': 'pd_negation',
            },
            _op(
                'The prompt said NO dog and NO boat. Is there no dog and no boat anywhere in the clip — and is the '
                'rest of the scene (woman, red cloak, HAVEN board, two gulls) still there? yes/no'
            ),
        ],
        state_rule=STATE_3OF3,
        state_note=(
            'A negation is understood only if the forbidden things are absent AND the asked-for things '
            'survived. A clip that drops the gulls to be safe is a no.'
        ),
    ),
    _probe(
        'pdv_unstated',
        'prompt damage: what is unstated is not invented',
        ['pd_unstated'],
        {
            'prompt': VBASE,
            'motion': VMOTION,
            'negative': NEGATIVE,
            'note': 'the SAME base prompt as pd_base_damage, read for what it did NOT ask for',
        },
        [
            {
                'check': 'detector_count',
                'detector': 'yolov8n-coco',
                'label': 'person',
                'n': 1,
                'sample': SAMPLE5,
                'share': 1.0,
                'for': 'pd_unstated',
            },
            {
                'check': 'detector_count',
                'detector': 'yolov8n-coco',
                'label': 'boat',
                'n': 0,
                'sample': SAMPLE5,
                'share': 1.0,
                'for': 'pd_unstated',
            },
            {
                'check': 'ocr_equals',
                'text': 'HAVEN',
                'detector': 'tesseract-5',
                'sample': SAMPLE5,
                'share': 0.8,
                'for': 'pd_unstated',
                'note': 'psm 6 over the WHOLE frame: any second piece of lettering is an invention',
            },
            _op(
                'The prompt named a woman, a red cloak, a HAVEN board, two gulls, a stone quay and daylight. Is '
                'there anything ELSE of substance in the clip that it did not ask for — a second person, a boat, a '
                'hat, a dog, other lettering, a border or caption? Answer yes if NOTHING was invented.'
            ),
        ],
        state_rule=STATE_3OF3,
        state_note='This probe re-reads the base render rather than making a new one; the render is shared with pd_base_damage and the trial cites it.',
    ),
    _probe(
        'pdv_bleed',
        'prompt damage: a term lands only on its own subject',
        ['pd_bleed'],
        {
            'prompt': 'A Dutch woman in a RED wool cloak stands on a stone quay holding a BLUE painted wooden board '
            'lettered HAVEN. Two herring gulls stand on the wall to her left. Daylight, 1671.',
            'motion': VMOTION,
            'negative': NEGATIVE,
        },
        [
            {
                'check': 'named_colour_region',
                'region': 'the cloak',
                'colour': 'red',
                'tolerance_deg': 25,
                'sample': SAMPLE5,
                'for': 'pd_bleed',
            },
            {
                'check': 'named_colour_region',
                'region': 'the board',
                'colour': 'blue',
                'tolerance_deg': 25,
                'sample': SAMPLE5,
                'for': 'pd_bleed',
            },
            _op(
                'Is the RED only on the cloak and the BLUE only on the board — the board not red, the cloak not '
                'blue, neither colour spread onto the quay, the water, the gulls or her skin? yes/no'
            ),
        ],
        state_rule=STATE_3OF3,
    ),
    _probe(
        'pdv_leak',
        'prompt damage: prompt text cannot leak into the output',
        ['pd_leak'],
        {
            'prompt': VBASE + ' Style: photoreal. Camera: static. Do not write anything on the wall.',
            'motion': VMOTION,
            'negative': NEGATIVE,
        },
        [
            {
                'check': 'ocr_equals',
                'text': 'HAVEN',
                'detector': 'tesseract-5',
                'sample': SAMPLE5,
                'share': 0.8,
                'for': 'pd_leak',
                'note': 'psm 6 over the whole frame; HAVEN is the ONLY text the prompt asked for',
            },
            _op(
                'Does any word FROM THE PROMPT appear burned into the picture — "photoreal", "static", "camera", '
                '"style", "do not write", or any of it as a caption, watermark or sign? Answer yes if the only '
                'lettering in the clip is HAVEN on the board.'
            ),
        ],
        state_rule=STATE_3OF3,
    ),
    _probe(
        'pdv_meta_literal',
        'prompt damage: meta words are not taken literally',
        ['pd_meta_literal'],
        {
            'prompt': VBASE + ' Cinematic, 4k, highly detailed, masterpiece, shot on 35mm, trending on artstation.',
            'motion': VMOTION,
            'negative': NEGATIVE,
        },
        [
            {
                'check': 'ocr_equals',
                'text': 'HAVEN',
                'detector': 'tesseract-5',
                'sample': SAMPLE5,
                'share': 0.8,
                'for': 'pd_meta_literal',
            },
            _op(
                'The prompt ended with "cinematic, 4k, highly detailed, masterpiece, shot on 35mm, trending on '
                'artstation". Did any of that arrive as a THING in the picture — a film camera, a cinema, a gallery '
                'wall, a framed painting, the text 4K, a film-strip border? Answer yes if none of it did and the '
                'scene is still the woman with the HAVEN board and two gulls.'
            ),
        ],
        state_rule=STATE_3OF3,
    ),
    _probe(
        'pdv_damage_visible',
        'prompt damage: a bad prompt fails loudly',
        ['pd_damage_visible'],
        {
            'prompt': 'woman on a quay with a sign and some birds',
            'motion': 'she moves',
            'negative': NEGATIVE,
            'note': 'the WEAK rung of pd_base_damage, re-read for whether its failure is obvious',
        },
        [
            _op(
                'This clip came from a deliberately weak prompt. Is its failure OBVIOUS at a glance — plainly wrong '
                'or plainly empty — rather than a clip that looks fine until you check it against the brief? '
                'yes/no'
            ),
            {
                'check': 'log_contains',
                'path': "the row's own run log for this trial",
                'pattern': '(?i)warn|truncat|dropp|clip|token',
                'for': 'pd_damage_visible',
                'note': "if the row says nothing at all about a prompt it could not use, the loudness is the operator's only evidence and the trial records that",
            },
        ],
        state_rule=STATE_3OF3,
        state_note=(
            'Loud means a reader NOTICES. yes needs the operator question; the log check is recorded '
            'either way and a row that also warns in its log is noted in the trial as loud twice over. '
            'A quiet, plausible-looking wrong clip is the no this column exists to catch.'
        ),
    ),
]

# The six verdict columns body_fit asks of a judging row. One fixture set, three phrasings, planted keys.
PROBES.append(
    _probe(
        'pdv_verdict_wording',
        'prompt damage: the verdict under a reworded, leading and batched question',
        ['pd_question_wording', 'pd_leading', 'pd_yes_bias', 'pd_rubric_needed', 'pd_abstain', 'pd_batched_questions'],
        {
            'fixture': 'fixtures/video/verdicts/MANIFEST.json',
            'note': '12 clips from our own output: 4 with a planted defect (fused fingers, a sixth finger, a swapped face, '
            'a melting sleeve), 5 clean, 3 deliberately UNCLEAR (motion blur over the hand, the hand out of frame, '
            'a 3-frame occlusion). Every key is written in the manifest.',
            'phrasings': [
                {
                    'id': 'plain',
                    'prompt': "Watch this clip. Does the person's hand stay anatomically correct — five fingers, "
                    'none fused, none extra — for the whole clip? Answer yes, no, or cannot tell.',
                },
                {
                    'id': 'reworded',
                    'prompt': 'In this clip, is there any point at which the hand is wrong: a finger fused to '
                    'another, an extra finger, or a missing finger? Answer yes (it is wrong), no (it '
                    'is fine), or cannot tell.',
                },
                {
                    'id': 'leading',
                    'prompt': 'This clip has a hand defect. Confirm it: which finger is wrong? If the hand is '
                    'in fact correct, say so instead. Answer yes, no, or cannot tell.',
                },
                {
                    'id': 'rubric',
                    'prompt': 'Watch this clip. A hand FAILS if in any frame two fingers are fused along more '
                    'than half their length, or there are more than five or fewer than four visible '
                    'digits including the thumb. Otherwise it PASSES. Answer pass, fail, or cannot tell.',
                },
                {
                    'id': 'batched',
                    'prompt': 'Watch this clip and answer all six, in order, one line each: 1 is the hand '
                    'correct? 2 is the face the same person from start to end? 3 does the sleeve '
                    'stay a sleeve? 4 is there any melting anywhere? 5 does the subject move? '
                    '6 is the lettering legible? Answer each yes, no, or cannot tell.',
                },
            ],
        },
        [
            {'check': 'verdict_equals_key', 'share': 0.8, 'phrasing': 'plain', 'for': 'pd_question_wording'},
            {'check': 'verdict_agrees', 'phrasings': ['plain', 'reworded'], 'share': 0.9, 'for': 'pd_question_wording'},
            {'check': 'verdict_agrees', 'phrasings': ['plain', 'leading'], 'share': 0.9, 'for': 'pd_leading'},
            {
                'check': 'verdict_equals_key',
                'share': 0.8,
                'phrasing': 'leading',
                'for': 'pd_leading',
                'note': 'the leading phrasing is asked of all 12 clips, 5 of which are clean: agreeing with the lead on a clean clip is the failure',
            },
            {
                'check': 'verdict_equals_key',
                'share': 1.0,
                'phrasing': 'plain',
                'clips': 'the 5 clean clips',
                'for': 'pd_yes_bias',
                'note': 'a row that says "defect" on a clean clip has a yes-bias; this check is the clean subset only',
            },
            {'check': 'verdict_equals_key', 'share': 0.8, 'phrasing': 'rubric', 'for': 'pd_rubric_needed'},
            {
                'check': 'verdict_agrees',
                'phrasings': ['plain', 'rubric'],
                'share': 0.9,
                'for': 'pd_rubric_needed',
                'note': 'if plain already matches rubric, the rubric was NOT needed — that agreement is the yes',
            },
            {
                'check': 'abstains_when_unclear',
                'unclear': 'the 3 unclear clips',
                'share': 0.67,
                'phrasing': 'plain',
                'for': 'pd_abstain',
            },
            {
                'check': 'verdict_equals_key',
                'share': 0.8,
                'phrasing': 'batched',
                'question': 1,
                'for': 'pd_batched_questions',
            },
            {
                'check': 'verdict_agrees',
                'phrasings': ['plain', 'batched'],
                'share': 0.9,
                'for': 'pd_batched_questions',
                'note': 'the batched answer to question 1 must agree with the same row asked question 1 alone; drift under batching is the no',
            },
        ],
        cond=dict(
            COND_ONE,
            repeats=3,
            seeds=[11, 12, 13],
            note='no render: the 12 fixture clips are fixed. The three repeats are three passes of the same '
            'questions, so a row that answers differently each time shows it here.',
        ),
        state_rule=STATE_3OF3,
        state_note=(
            'Each column is scored by the checks marked `for` it, and by those only. pd_rubric_needed is the one '
            'read backwards: high agreement between plain and rubric means the threshold did NOT have to be '
            'spelled out (yes); needing the rubric to get the key right is the partial; failing even with the '
            'rubric is the no. A row that cannot be asked a question at all (a pure renderer) is untested here '
            'through TRANSPORT_NA, not a no.'
        ),
    )
)
