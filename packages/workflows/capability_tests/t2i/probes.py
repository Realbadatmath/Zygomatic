# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""PROBES — one probe per domain column, in sheet order.

Moved verbatim out of the old single-file t2i.py (lines 165-812).
"""

from __future__ import annotations

from capability_tests.image_shared import COND_RENDER, NEGATIVE, QUAY

from capability_tests.t2i.constants import (
    COND_ONE_SEED,
    LONG_FACTS,
    LONG_NOTE,
    LONG_PROMPT,
    LORA,
    LORA_SCALE,
    STYLE_LABELS,
    _probe,
)


PROBES = [
    # ── [The picture] ──────────────────────────────────────────────────────────────────────
    _probe(
        't_long_prompt',
        'The picture: how much of a 90-word prompt lands',
        ['prompt'],
        LONG_PROMPT,
        [
            {'check': 'detector_count', 'class': 'person', 'count': 1},
            {
                'check': 'operator',
                'question': 'Is there exactly one man in this picture, of about fifty, with a grey beard? yes/no',
            },
            {'check': 'colour_of_thing', 'thing': 'cloak', 'colour': 'red', 'min_share': 0.4},
            {
                'check': 'operator',
                'question': 'Does the cloak have five brass buttons down the front — five, countable, all present? yes/no',
            },
            {'check': 'open_vocab_present', 'terms': ['wide-brimmed felt hat'], 'min_score': 0.3},
            {'check': 'colour_of_thing', 'thing': 'wide-brimmed felt hat', 'colour': 'black', 'min_share': 0.5},
            {'check': 'open_vocab_count', 'query': 'lantern', 'min_score': 0.3, 'count': 1},
            {
                'check': 'operator',
                'question': 'Is the lantern unlit and held in the man LEFT hand — the hand on the viewer right? yes/no',
            },
            {'check': 'open_vocab_count', 'query': 'wooden barrel', 'min_score': 0.3, 'count': 1},
            {
                'check': 'operator',
                'question': 'Is his right hand resting on the barrel, touching it, rather than hanging beside it? yes/no',
            },
            {'check': 'detector_count', 'class': 'bird', 'count': 3},
            {
                'check': 'operator',
                'question': 'Are the gulls standing on a wall behind the man, rather than in the air or in front of him? yes/no',
            },
            {'check': 'open_vocab_count', 'query': 'sailing ship', 'min_score': 0.3, 'count': 1},
            {'check': 'spatial_relation', 'a': 'person', 'b': 'sailing ship', 'relation': 'larger', 'margin_px': 0},
            {
                'check': 'operator',
                'question': 'Are the cobbles plainly wet — dark, reflective or puddled — rather than dry stone? yes/no',
            },
            {'check': 'era_gate_clean'},
        ],
        facts=LONG_FACTS,
        score='share of the twelve facts in LONG_FACTS, averaged over the three seeds',
        state_rule={'yes': 0.75, 'partial': 0.5},
        state_note=LONG_NOTE,
    ),
    _probe(
        't_counts_together',
        'The picture: three stated counts in ONE frame',
        ['prompt_count'],
        'Three wooden barrels, five white gulls and one wooden sailing ship '
        + QUAY
        + ', the barrels standing apart from one another on the cobbles, the gulls on the quay '
        'wall, the ship moored beyond, nobody present.',
        [
            {'check': 'open_vocab_count', 'query': 'wooden barrel', 'min_score': 0.3, 'count': 3},
            {'check': 'detector_count', 'class': 'bird', 'count': 5},
            {'check': 'open_vocab_count', 'query': 'sailing ship', 'min_score': 0.3, 'count': 1},
            {'check': 'detector_count', 'class': 'person', 'count': 0},
        ],
        state_note='Wholly mechanical, and deliberately NOT the bank count_exact probe: that '
        'one asks for a single count in an otherwise empty frame, this asks for '
        'three different counts at once, which is how a house prompt is actually '
        'written. Read the pair together — a row that passes count_exact and fails '
        'here drops counts under load, which is the useful finding.',
    ),
    _probe(
        't_relations_together',
        'The picture: three stated relations in ONE frame',
        ['prompt_spatial'],
        'A red barrel on the left and a blue crate on the right ' + QUAY + '; a wicker basket '
        'stands on top of the crate; a coiled rope lies in front of the barrel, nearer the '
        'camera and partly covering its foot. Nobody present.',
        [
            {
                'check': 'spatial_relation',
                'a': 'wooden barrel',
                'b': 'wooden crate',
                'relation': 'left_of',
                'margin_px': 60,
            },
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
                'b': 'wooden barrel',
                'relation': 'overlaps',
                'margin_px': 0,
            },
            {'check': 'colour_of_thing', 'thing': 'wooden barrel', 'colour': 'red', 'min_share': 0.4},
            {'check': 'colour_of_thing', 'thing': 'wooden crate', 'colour': 'blue', 'min_share': 0.4},
        ],
        state_note='Wholly mechanical: three relations and the two colours that prove the '
        'relations are about the right objects. The bank sp_* probes each ask ONE '
        'relation in an otherwise bare frame; this column is the domain version — '
        'left/right AND on-top-of AND in-front-of, all stated in one prompt, which '
        'is where binding usually breaks.',
    ),
    _probe(
        't_negative_removes',
        'The picture: does a negative remove ONE named thing',
        ['negatives'],
        'A Dutch shipwright stands alone ' + QUAY + ', whole body in frame, facing the camera, '
        'wearing a wide black felt hat, a coiled rope at his feet.',
        [
            {'check': 'detector_count', 'class': 'person', 'count': 1},
            {'check': 'open_vocab_count', 'query': 'coiled rope', 'min_score': 0.3, 'count': 1},
            {
                'check': 'operator',
                'question': 'Is this the same man, in the same pose, on the same quay, with the rope still at his feet — differing from its pair only in whether he wears a hat? yes/no',
            },
        ],
        variants={
            'control': {
                'negative': NEGATIVE,
                'expect': [{'check': 'open_vocab_present', 'terms': ['hat'], 'min_score': 0.3}],
            },
            'suppressed': {
                'negative': NEGATIVE + ', hat',
                'expect': [{'check': 'open_vocab_absent', 'terms': ['hat'], 'min_score': 0.3}],
            },
        },
        pair=['control', 'suppressed'],
        state_note='The measurement is the DIFFERENCE between two renders at the same seed: '
        'the positive prompt asks for the hat in both, and only the negative moves. '
        'yes needs GroundingDINO to find a hat in the control AND find none in the '
        'suppressed frame, on the same seed, 3/3 seeds. A row whose control has no '
        'hat to begin with scores no with the note "the positive was not obeyed, so '
        'the negative could not be measured" — a suppression you cannot see is not '
        'a suppression. One named thing and not a list, because a negative that '
        'removes six things at once cannot say which one it removed.',
    ),
    _probe(
        't_composition',
        'The picture: is the frame composed, not centred',
        ['composition'],
        'A Dutch shipwright stands well off to the left of the frame ' + QUAY + ', his whole '
        'body in frame, the right two thirds of the picture given to the open quay and the '
        'moored ship beyond, nothing in the middle of the frame.',
        [
            {'check': 'detector_count', 'class': 'person', 'count': 1},
            {'check': 'box_centre_offset', 'query': 'person', 'min_score': 0.3, 'min_frac': 0.15, 'max_frac': 0.42},
            {
                'check': 'operator',
                'question': 'Is the man off to one side with the rest of the frame doing something, rather than centred with empty space around him? yes/no',
            },
        ],
        state_note='Mechanical on WHERE the subject sits — the person box centre between 15 % '
        'and 42 % of the frame width from the middle, so a subject shoved half out '
        'of frame does not score as good composition either. The operator decides '
        'whether the rest of the frame is composed or merely empty, which no box '
        'can report. Both must pass. The bank never asks this: every subject prompt '
        'there deliberately centres its subject so the subject is what is measured.',
    ),
    _probe(
        't_depth',
        'The picture: convincing depth',
        ['depth'],
        'A long stone quay at Kattenburg, Amsterdam, 1671, plain daylight, seen down its '
        'length: four wooden barrels stand in a row receding from the camera, the nearest '
        'large and close, each one further and smaller, the furthest small at the far end. '
        'Nobody present.',
        [
            {'check': 'depth_size_gradient', 'query': 'wooden barrel', 'min_score': 0.25, 'count': 4, 'ratio': 0.8},
            {
                'check': 'operator',
                'question': 'Does this picture read as deep space — the far barrel plainly far away, the ground running back consistently — rather than four barrels of different sizes on a flat backdrop? yes/no',
            },
        ],
        state_note='The mechanical half is the box signature of a receding row: four barrels, '
        'each at most 0.8 of the area of the one before, each top edge no lower '
        'than the last. That is a real measurement and it is not depth — a flat '
        'poster of four shrinking barrels passes it. So the operator decides depth '
        'and this cell is openly operator-led; the gradient only keeps a frame with '
        'the wrong number of barrels out of the judgement.',
    ),
    _probe(
        't_light',
        'The picture: one light source, shadows that agree',
        ['light'],
        'Three wooden barrels stand apart from one another on a stone quay at Kattenburg, '
        'Amsterdam, 1671, in hard low sunlight coming from the left of the frame, each barrel '
        'casting one long shadow to the right across the cobbles. Nobody present, no other '
        'light anywhere.',
        [
            {'check': 'open_vocab_count', 'query': 'wooden barrel', 'min_score': 0.3, 'count': 3},
            {
                'check': 'operator',
                'question': 'Does every shadow in this picture fall the same way — to the right — as if from one light on the left? yes/no',
            },
            {
                'check': 'operator',
                'question': 'Is there exactly one light source, with no second set of shadows and no object lit from a direction nothing explains? yes/no',
            },
        ],
        state_note='OPERATOR, said plainly: the house has no shadow-direction detector, and '
        'inventing one for this cell would be a claim about software that does not '
        'exist. Two written questions rather than one, because "the shadows agree" '
        'and "there is only one light" fail separately and the trial should say '
        'which. The barrel count is only there so the operator is judging three '
        'shadows and not one.',
    ),
    # ── [Anatomy & objects] ────────────────────────────────────────────────────────────────
    _probe(
        't_hands',
        'Anatomy: two hands doing something',
        ['hands'],
        'A Dutch shipwright stands ' + QUAY + ', framed from the waist up, holding a wooden '
        'mallet in both hands in front of his chest, both hands and all his fingers clearly '
        'visible and separate.',
        [
            {'check': 'hand_landmarks', 'hands': 2, 'min_tip_px': 12},
            {'check': 'open_vocab_count', 'query': 'mallet', 'min_score': 0.25, 'count': 1},
            {
                'check': 'operator',
                'question': 'Does each hand have exactly five separate fingers, correctly jointed, gripping the mallet — no fused, missing, extra or backwards fingers? yes/no',
            },
        ],
        state_note='The column the house rejects most stills over. MediaPipe hand_landmarker '
        'is authority for TWO hands with 21 landmarks and five fingertips at least '
        '12 px apart; the operator is authority for the sixth finger MediaPipe '
        'merges into its neighbour and for a thumb jointed the wrong way, which the '
        '2026-09-27 defect bench showed no local judge catches (2/8). Both must '
        'pass. Hands ON a task, not a bare palm, because the bank render_hand_* '
        'subjects already cover the easy open hand and the house failure is the '
        'working hand.',
    ),
    _probe(
        't_faces',
        'Anatomy: one face, front on',
        ['faces'],
        'Head and shoulders of a Dutch shipwright, 1671, plain daylight, facing the camera '
        'straight on, his whole face in frame and evenly lit, plain grey wall behind him.',
        [
            {'check': 'detector_count', 'class': 'face', 'count': 1},
            {
                'check': 'operator',
                'question': 'Is this face whole and correct — two eyes, one nose, one mouth, both ears where they belong, nothing melted, doubled or smeared? yes/no',
            },
        ],
        state_note='InsightFace is authority for ONE face being there and no second face '
        'hiding in the background; everything about whether the face is right is '
        'the operator. Said plainly rather than dressed up as measured.',
    ),
    _probe(
        't_eyes',
        'Anatomy: a matched pair of eyes',
        ['eyes'],
        'Close-up of the face of a Dutch woman, 1671, plain daylight, both eyes open, level '
        'with each other and looking straight at the camera, plain grey wall behind her.',
        [
            {'check': 'detector_count', 'class': 'face', 'count': 1},
            {
                'check': 'operator',
                'question': 'Do the two eyes match each other — same size, same shape, same colour, level, both looking the same way? yes/no',
            },
        ],
        state_note='OPERATOR alone. There is no eye-symmetry detector in this house, and the '
        'InsightFace landmarks are fitted to a face model that will place two '
        'plausible eyes on a picture that has one and a half, so quoting them here '
        'would manufacture a measurement. The cell says so.',
    ),
    _probe(
        't_limbs',
        'Anatomy: the right number of limbs',
        ['limbs'],
        'A Dutch dockworker stands alone ' + QUAY + ', plain daylight, his whole body in '
        'frame, arms out from his sides and legs apart, every limb clearly separate against '
        'the empty quay behind him.',
        [
            {'check': 'detector_count', 'class': 'person', 'count': 1},
            {'check': 'hand_landmarks', 'hands': 2, 'min_tip_px': 10},
            {
                'check': 'operator',
                'question': 'Does this person have exactly two arms and two legs, each whole, each attached where it belongs, none doubled and none missing? yes/no',
            },
        ],
        state_note='The pose is spread on purpose so a third arm cannot hide against the body. '
        'MediaPipe confirms two hands, which catches the commonest extra-limb '
        'failure mechanically; the limb count itself is the operator, because no '
        'pose estimator in the house reports a THIRD arm — they fit 17 keypoints to '
        'whatever is there and report success.',
    ),
    _probe(
        't_teeth',
        'Anatomy: teeth that are not a smear',
        ['teeth'],
        'Close-up of a Dutch dockworker laughing, 1671, plain daylight, mouth wide open, his '
        'upper and lower teeth clearly visible and separate, plain grey wall behind him.',
        [
            {'check': 'detector_count', 'class': 'face', 'count': 1},
            {
                'check': 'operator',
                'question': 'Are these individual teeth in two rows, countable and separate, rather than a white smear or one fused block? yes/no',
            },
        ],
        state_note='OPERATOR alone, and cheap to answer: a smear is obvious to a person at a '
        'glance and invisible to every detector the house owns. The face count only '
        'keeps a closed mouth or an empty frame out of the judgement.',
    ),
    _probe(
        't_crowds',
        'Anatomy: background people that hold together',
        ['crowds'],
        'A crowd of about twenty Dutch townspeople fills the quay at Kattenburg, Amsterdam, '
        '1671, plain daylight, seen from a raised viewpoint so heads and bodies are visible, '
        'nobody in the foreground.',
        [
            {'check': 'detector_count', 'class': 'person', 'min': 15},
            {
                'check': 'operator',
                'question': 'Does every figure in this crowd hold together as a person — no melted faces, no bodies merged into one another, no figure with the wrong number of limbs? yes/no',
            },
        ],
        state_note='YOLO is authority for the crowd being a crowd (at least 15 people found, '
        'because the column is about background figures and not about counting — '
        'count_people in the bank does the counting). Whether the figures hold '
        'together is the operator, and this is the question a blind pass is worst '
        'at rushing: the instruction is to look at each figure, not at the crowd.',
    ),
    _probe(
        't_objects',
        'Anatomy: objects whole and single, no duplicated props',
        ['objects'],
        'Exactly three things stand apart from one another ' + QUAY + ': one wooden barrel, '
        'one wicker basket and one iron lantern, each whole and complete, nothing else and '
        'nobody present.',
        [
            {'check': 'open_vocab_count', 'query': 'wooden barrel', 'min_score': 0.3, 'count': 1},
            {'check': 'open_vocab_count', 'query': 'wicker basket', 'min_score': 0.3, 'count': 1},
            {'check': 'open_vocab_count', 'query': 'lantern', 'min_score': 0.3, 'count': 1},
            {'check': 'detector_count', 'class': 'person', 'count': 0},
            {
                'check': 'operator',
                'question': 'Is each of the three objects whole and single — none duplicated, none half-drawn, none merged into another? yes/no',
            },
        ],
        state_note='Mechanical on the duplication (three queries, each exactly one box, which '
        'is what "no duplicated props" means) and operator on wholeness, because a '
        'barrel with no far side is one box to GroundingDINO. Read beside the bank '
        'cap_objects, which climbs the same question to find where N things stop '
        'being N things.',
    ),
    _probe(
        't_text_in_frame',
        'Anatomy: legible lettering when asked',
        ['text_in_frame'],
        'A plain wooden board nailed to a post ' + QUAY + ', the single word HARING painted '
        'across it in large black capitals, no other writing anywhere in the picture, nobody '
        'present.',
        [{'check': 'ocr_equals', 'text': 'HARING'}, {'check': 'detector_count', 'class': 'person', 'count': 0}],
        state_note='WHOLLY MECHANICAL. PaddleOCR must read exactly HARING and no other '
        'lettering anywhere in the frame — a row that paints HARING plus three '
        'lines of invented gibberish has not done what was asked. Six letters on '
        'purpose: the bank cap_words ladder finds how far a row can go, this cell '
        'answers the flat question the sheet asks, and the shared negative carries '
        'no anti-text term so nothing is suppressing lettering here.',
    ),
    # ── [Style & control] ──────────────────────────────────────────────────────────────────
    _probe(
        't_style',
        'Style: holds a painted, non-photographic style',
        ['style'],
        'A Dutch shipwright at his bench in a shipyard shed, 1671, painted as a Dutch golden '
        'age oil painting, thick visible brushwork and impasto, warm chiaroscuro, canvas '
        'texture showing through, nothing photographic.',
        [
            {
                'check': 'clip_style_label',
                'expect': ['an oil painting', 'a watercolour painting'],
                'labels': STYLE_LABELS,
            },
            {'check': 'detector_count', 'class': 'person', 'count': 1},
            {
                'check': 'operator',
                'question': 'Is this a painting — visible brushwork, paint surface, no photographic grain or lens blur — rather than a photograph with a warm filter? yes/no',
            },
        ],
        state_note='CLIP zero-shot over the six STYLE_LABELS is the mechanical half and it is '
        'a weak instrument: it separates painting from photograph well and '
        'painting from 3d render badly. So the operator is authority for whether '
        'the paint is real, and both must pass. Read beside photoreal: a row that '
        'passes both has a style lever; a row that passes only photoreal renders '
        'one look and ignores the instruction.',
    ),
    _probe(
        't_style_consistency',
        'Style: one style across a set of four',
        ['style_consistency'],
        'SET — four prompts sharing one style block, see `set`',
        [
            {'check': 'clip_style_pairwise_max', 'set': ['s1', 's2', 's3', 's4'], 'max': 0.22},
            {'check': 'clip_style_label', 'expect': ['an oil painting'], 'labels': STYLE_LABELS},
            {
                'check': 'operator',
                'question': 'Do these four pictures look like the work of one hand on one day — same palette, same brush, same light, same finish — rather than four different illustrators? yes/no',
            },
        ],
        set=[
            (
                's1',
                'Painted as a Dutch golden age oil painting, dark teal and umber palette, thick visible brushwork, warm chiaroscuro. A Dutch shipwright at his bench in a shipyard shed, 1671.',
            ),
            (
                's2',
                'Painted as a Dutch golden age oil painting, dark teal and umber palette, thick visible brushwork, warm chiaroscuro. A Dutch woman at a table with a ledger and one candle, 1671.',
            ),
            (
                's3',
                'Painted as a Dutch golden age oil painting, dark teal and umber palette, thick visible brushwork, warm chiaroscuro. A wooden sailing ship moored at a stone quay under a grey sky, 1671.',
            ),
            (
                's4',
                'Painted as a Dutch golden age oil painting, dark teal and umber palette, thick visible brushwork, warm chiaroscuro. A dog asleep on the cobbles beside a shipyard bell, 1671.',
            ),
        ],
        state_note='Four different subjects, one character-identical style block, each rendered '
        'on all three seeds: twelve frames. The mechanical half is the pairwise '
        'CLIP image-embedding cosine DISTANCE over the four same-seed frames — <= '
        '0.22 for every one of the six pairs, and the trial keeps the worst pair so '
        'the reader sees which subject broke the set. 0.22 is a threshold this test '
        'FIXES rather than derives: it is loose enough that four different subjects '
        'do not fail on subject alone and tight enough that a photograph among '
        'three paintings cannot pass, and any later change to it is a different '
        'test. The operator question is the real one ("one hand?") and both halves '
        'must pass.',
    ),
    _probe(
        't_photoreal',
        'Style: reaches photoreal when asked',
        ['photoreal'],
        'Documentary photograph of a Dutch shipwright standing ' + QUAY + ', head and '
        'shoulders, natural skin texture with pores and stubble, shallow depth of field, 85mm '
        'lens, plain daylight, nothing painted or illustrated.',
        [
            {'check': 'clip_style_label', 'expect': ['a photograph'], 'labels': STYLE_LABELS},
            {'check': 'detector_count', 'class': 'face', 'count': 1},
            {
                'check': 'operator',
                'question': 'Would this pass as a photograph of a real person — real skin with pores, real lens behaviour, no plastic sheen, no illustration? yes/no',
            },
        ],
        state_note='CLIP decides photograph-versus-painting mechanically; the operator decides '
        'the plastic-skin failure, which CLIP calls a photograph every time. Both '
        'must pass. Read beside style: the pair is the style LEVER, and a row that '
        'only ever does one of the two has no lever.',
    ),
    _probe(
        't_period_look',
        'Style: period-correct dress and setting',
        ['period_look'],
        'A Dutch shipwright and a Dutch woman stand ' + QUAY + ', plain daylight, both whole '
        'bodies in frame, in ordinary working dress of 1671, a wooden sailing ship moored '
        'behind them and the timber houses of Kattenburg beyond.',
        [
            {'check': 'era_gate_clean'},
            {'check': 'detector_count', 'class': 'person', 'count': 2},
            {
                'check': 'open_vocab_absent',
                'terms': ['wristwatch', 'sneakers', 'zipper', 'car', 'streetlight', 'plastic bottle'],
                'min_score': 0.3,
            },
            {
                'check': 'operator',
                'question': 'Is everything in this picture possible in 1671 — every garment, fastening, shoe, hairstyle, boat, building and light? yes/no',
            },
        ],
        state_note='era_gate.py is the mechanical screen and its own docstring says why a '
        'single global VLM question is not: moondream answered yes on 34/40 frames '
        'and Qwen3-VL recalled 2/8, missing a full-width motor boat. era_gate '
        'decomposes the prompt into per-object crop checks instead, which is the '
        'method that works, and it is authority for the objects it derived. The '
        'operator still decides, because the 2020s haircut on an undescribed head '
        'is the failure era_gate was written about and it has no crop to check it '
        'in. Both must pass.',
    ),
    _probe(
        't_lora_effect',
        'Style: does the LoRA lever change the picture at all',
        ['lora_effect'],
        'A Dutch shipwright stands alone ' + QUAY + ', plain daylight, whole body in frame, '
        'facing the camera, empty cobbled quay behind him.',
        [
            {'check': 'render_returned'},
            {'check': 'image_distance', 'metric': 'lpips', 'to': 'lora_off', 'min': 0.15},
            {
                'check': 'operator',
                'question': 'Do these two pictures differ in look — palette, brush, finish — beyond the ordinary wobble between two renders of the same prompt? yes/no',
            },
        ],
        variants={
            'lora_off': {'lora': None, 'expect': [{'check': 'lora_names_in_trial', 'loras': []}]},
            'lora_on': {
                'lora': {'name': LORA, 'strength_model': LORA_SCALE, 'strength_clip': LORA_SCALE},
                'expect': [{'check': 'lora_names_in_trial', 'loras': [LORA]}],
            },
        },
        pair=['lora_off', 'lora_on'],
        state_note='The A/B is the whole measurement and the reason it exists is a stack-wide '
        'bug: until convert_lora.py on 2026-09-23, ComfyUI LoRAs in this house were '
        'NEVER APPLIED — the node loaded, the render came back, and nothing had '
        'changed. So this cell asks only whether the lever is connected: LPIPS >= '
        '0.15 between the two frames at the SAME seed, plus the receipt that the '
        'adapter was in the graph (lora_names_in_trial, empty for off and exactly '
        'one file for on). A row where the receipt shows the LoRA loaded and LPIPS '
        'is under 0.15 is the bug, not a subtle adapter, and the note must say so. '
        'Whether the LoRA is GOOD is the lora_train sheet business, not this one. '
        'The adapter is ' + LORA + ' at ' + str(LORA_SCALE) + ' on every SDXL row: '
        'LORA_PAIRING says it belongs to sd_xl_base_1.0, so on sdxl_jugg and '
        'dynavision the picture will be off-model — which is fine here, because a '
        'visible change on a mismatched base still proves the lever works, and the '
        'mismatch itself is what lora_pairing (the lookup) reports.',
    ),
    _probe(
        't_seed_stable',
        'Style: the same seed reproduces the image',
        ['seed_stable'],
        'A Dutch shipwright stands alone ' + QUAY + ', plain daylight, whole body in frame, '
        'facing the camera, empty cobbled quay behind him.',
        [{'check': 'render_returned'}, {'check': 'identical_images'}],
        conditions=dict(COND_RENDER, seeds=[11, 11, 11], repeats=3),
        state_note='WHOLLY MECHANICAL: seed 11 three times, and the three PNGs must be '
        'byte-identical once PNG metadata is stripped. This is the domain column '
        'the sheet asks ("a seed reproduces the image") and it uses the same '
        'measurement as the universal `deterministic` cell the bank derives from '
        'u_deterministic; they are kept as two columns because the sheet asks them '
        'in two bands, and a run writes the same number into both. Read this cell '
        'first: a row that is not seed-stable makes every A/B on this sheet '
        '(negatives, lora_effect, the steps ladder) unreadable, because the '
        'difference would not be the lever.',
    ),
    _probe(
        't_aspect',
        'Style: non-square aspect ratios',
        ['aspect'],
        'A wooden sailing ship moored at the stone quay at Kattenburg, Amsterdam, 1671, plain '
        'daylight, the whole ship in frame from bow to stern, one Dutch shipwright standing '
        'on the quay beside it, whole body in frame.',
        [
            {'check': 'render_returned'},
            {'check': 'detector_count', 'class': 'person', 'count': 1},
            {'check': 'open_vocab_count', 'query': 'sailing ship', 'min_score': 0.3, 'count': 1},
            {
                'check': 'operator',
                'question': 'Is this frame whole and unstretched — the man normally proportioned, the ship not squashed, no duplicated bow or second mast added to fill the width? yes/no',
            },
        ],
        variants={
            'square': {
                'width': 1024,
                'height': 1024,
                'expect': [{'check': 'image_size', 'width': 1024, 'height': 1024}],
            },
            'landscape': {
                'width': 1344,
                'height': 768,
                'expect': [{'check': 'image_size', 'width': 1344, 'height': 768}],
            },
            'portrait': {
                'width': 768,
                'height': 1344,
                'expect': [{'check': 'image_size', 'width': 768, 'height': 1344}],
            },
        },
        state_note='Three ratios at the row native megapixel count (1024x1024, 1344x768, '
        '768x1344 — 1.05, 1.03 and 1.03 MP, so the test is the RATIO and not the '
        'area). image_size is mechanical and catches the row that silently returns '
        'a square; the operator catches the two real off-square failures, a '
        'stretched figure and the duplicated subject SDXL adds to fill an unusual '
        'width. yes needs all three ratios on 3/3 seeds; the trial records which '
        'ratio failed, because a row that does landscape and not portrait is a '
        'usable row and the sheet should say so.',
    ),
    _probe(
        't_res_high',
        'Style: holds together at 1.5x native',
        ['res_high'],
        'A Dutch shipwright stands alone ' + QUAY + ', plain daylight, whole body in frame, '
        'facing the camera, both hands open and empty at his sides, palms towards the camera.',
        [
            {'check': 'image_size', 'width': 1536, 'height': 1536},
            {'check': 'detector_count', 'class': 'person', 'count': 1},
            {'check': 'hand_landmarks', 'hands': 2, 'min_tip_px': 18},
            {
                'check': 'operator',
                'question': 'Is there exactly one whole person here, with one head and five separate fingers on each hand — no second body, no repeated head or torso anywhere in the frame? yes/no',
            },
        ],
        conditions=dict(COND_RENDER, width=1536, height=1536),
        state_note='1536x1536 is 1.5x the 1024 native square of every row on this sheet. The '
        'failure this column is really about is the DOUBLED subject — SDXL at 1.5x '
        'grows a second head or a second torso — so the checks are one person, two '
        'hands and a written operator question that names the doubling. MediaPipe '
        'runs at 18 px fingertip separation here rather than 12, because the frame '
        'is 1.5x larger and the threshold must scale with it or it would be looser '
        'than the 1024 probes. A row that OOMs at 1536 is a NO with the OOM in the '
        'note, not untested: falling over above native is what the column asks.',
    ),
    _probe(
        't_steps',
        'Style: the steps needed for a clean image',
        ['steps'],
        'A Dutch shipwright stands alone ' + QUAY + ', plain daylight, whole body in frame, '
        'facing the camera, both hands open and empty at his sides, palms towards the camera.',
        [
            {'check': 'render_returned'},
            {'check': 'detector_count', 'class': 'person', 'count': 1},
            {'check': 'hand_landmarks', 'hands': 2, 'min_tip_px': 12},
            {
                'check': 'operator',
                'question': 'Is this picture finished — sharp, resolved, no noise or mush left, nothing half-formed — and would the house ship it? yes/no',
            },
        ],
        conditions=dict(COND_ONE_SEED),
        ladder=[8, 16, 24, 32],
        unit='steps',
        ladder_rule='rung N renders the same prompt at the same seed with steps=N and nothing '
        'else changed; the cell is the LOWEST rung the operator calls finished '
        'and whose mechanical checks pass.',
        row_ladders={
            'flux_schnell': [1, 2, 4, 8],
            'note': 'flux_schnell is a distilled 4-step model and the shared '
            '8/16/24/32 ladder starts above its design point and would read '
            'as "8 steps, clean at the bottom rung" — true and useless. It '
            'climbs 1/2/4/8 instead. The trial records which ladder was used; '
            'the two are NOT comparable as numbers and the sheet must not '
            'read them side by side as if they were.',
        },
        state_rule={'yes': 1.0, 'partial': 0.5},
        state_note='This cell is a NUMBER (the first clean rung), not a yes/no. ONE seed, '
        'seed 11, and one render per rung: the ladder must isolate the step count, '
        'and a second seed would change the picture as well as the steps. That '
        'makes the cell cheap (4 renders) and it makes it fragile — the trial keeps '
        'all four frames so the reader can see the climb, and a row whose seed_stable '
        'cell is a no has an unreadable steps cell, which the note must say. The '
        'mechanical checks keep an obviously broken rung out of the operator '
        'judgement; "would the house ship it" is the operator alone, because '
        '"resolved enough" is exactly the judgement no local VLM makes.',
    ),
]
