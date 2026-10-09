# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Default test — VLM defect judges (vlm_judges). 2026-09-30.

Question the sheet asks: can a local vision model be trusted to REJECT a bad picture, and
which faults does each one actually see?

Shape of the test. This sheet is GENERATED, never typed: every cell on it came out of the
defect bench of 2026-09-27 23:38
($ZYG_LEDGER_INTRO/intro/defect_bench/sheet.json — 6 pictures,
16 crops, 55 questions, 5 local models). The default test is therefore THAT BENCH, fixed:
the six input pictures and the sixteen crops are the fixtures, the 55 questions are the
probes VERBATIM, and each question is scored against the operator's own `expected`, which
was written into spec.py BEFORE any model ran so the bench could not be tuned to a result.
Every other column of this sheet — the 132 Sees, the 132 Names, capacity, counting, space,
attributes, the four Prompt bands and the 27 universal ones — is the shared judge bank's;
this module owns only the 24 the bank leaves, and there are 0 domain columns.

What is blocked, and why. The two EXTRA bands are named for the truth: "Defect classes not
benched" and "Untested conditions". The bench showed an EXTRA DIGIT, not a fusion; a purple
doublet, not a wristwatch; a photographic hand in a painting, not a broken vanishing point.
So every class the bench has no picture for carries a `generated` fixture that is
`verified: False` and BLOCKS its column — the sheet then reads "no picture yet" instead of
claiming a measurement nobody made. `localise` and `severity` run on the benched pictures
but against keys (the region of each fault, the operator's 1-5 grade) that have never been
written down, so `keys_unverified` blocks them too. `frontier` is `na`: a paid judge is not
a row of this sheet.

Honest judging. No local VLM on this box sees a specific defect reliably — the bench
measured the best model at 34/40 on a global "is anything wrong here" question and 2/8 on
the hard classes, and moondream returned a null answer on all 44 scored questions. Nothing
here lets a VLM verify its own fixture: the keys are the operator's, written by eye.
Nothing in this file is executed; it is inputs, conditions, checks and thresholds.
"""

from __future__ import annotations

import os

from zyg_workflows.paths import ZYG_HOME

# ── check kinds this module adds (the validator unions them; the runner implements them) ──
CHECK_KINDS = {
    'bench_expected': 'the answer normalises to yes or no (yes|y|true|ja -> yes; no|n|false|nee -> no) and equals the `expected` of the defect-bench question named in `bench_q`; a null, empty, hedged or descriptive answer is WRONG, which is exactly how moondream scored 0/44 on 2026-09-27',
    'phrasing_agrees': "the two bench questions named in `pair` are asked about the SAME crop; the trial passes only when both normalised yes/no answers agree with each other AND with the pair's shared `expected`. The OR of the two is recorded separately as `or_recall` so the pipeline's real two-phrasing use can be read off the same run",
    'names_region': "the free-form answer names WHERE the fault is: it contains one of the region key's `accept` phrases for that picture (word boundary, case-insensitive) and none of `reject`; a correct verdict with no region named is a fail of this check only",
    'severity_rank_corr': "the model grades each picture of `set` 1-5 for how bad the worst fault is; Spearman rank correlation against the operator's own 1-5 grades over the same set is >= `min`",
    'reject_agreement': 'one "would you reject this frame" yes/no per picture, compared with the OR of that picture\'s per-defect answers: agreement >= `min` over the set, AND a yes on the approved control picture named in `control` is a hard fail however well the rest agreed',
}

# ── the bench, pinned ────────────────────────────────────────────────────────────────
#: The Second Ledger intro tree the bench lives in; $ZYG_LEDGER_INTRO overrides it.
LEDGER_INTRO = os.environ.get('ZYG_LEDGER_INTRO') or str(ZYG_HOME / 'zygomatics-zero' / 'ledger_intro')
BENCH = LEDGER_INTRO + '/intro/defect_bench'
CROPS = BENCH + '/crops'
SHOTS = LEDGER_INTRO + '/intro/shots'
RUN_ID = 'defect_bench 2026-09-27 23:38 (sheet.json, 5 models x 44 scored questions)'

# id -> (source picture, the operator's written truth — the ground the keys come from)
PICTURES = {
    'p4_restyle': (
        SHOTS + '/p4/_t12_restyle_s3.png',
        'Full-frame Qwen restyle: doublet recoloured PURPLE (should be brown), face/identity drifted '
        '(look-gate 0.226 vs floor 0.327), hands cel-smooth.',
    ),
    'p4_feather': (
        SHOTS + '/p4/_t12_hands_d0.70_s3.png',
        'Hand repaint candidate: a SECOND feather quill invented lying on the near page (only one quill '
        'exists in the scene).',
    ),
    'p3_sixdigit': (
        SHOTS + '/p3/_t12_arm_d0.55_s23.png',
        'Arm repaint candidate rejected by eye: a curled C-shaped extra digit in the palm (six digits by '
        'honest count), white cuff split by a hard dark seam.',
    ),
    'p1_v5': (
        SHOTS + '/p1/picture_v5.png',
        'Rejected v5: cyan/teal smudge in the sea beside the hand, olive smear on the rail, hand reads as '
        'an airbrushed PHOTOGRAPH inside a painting.',
    ),
    'p3_v5': (
        SHOTS + '/p3/picture_v5.png',
        "Rejected v5: both figures' hands PHOTOGRAPHIC against the brushwork (skin chroma 14.1/16.9/12.9 "
        'vs face, bound 4.5); flat water band; mushy bricks.',
    ),
    'p5_ok': (SHOTS + '/p5/picture_v4.png', 'APPROVED control picture: no known defect.'),
}
CROP_FILES = [
    'p1_v5__full.png',
    'p1_v5__hand.png',
    'p1_v5__sea.png',
    'p3_sixdigit__full.png',
    'p3_sixdigit__hand.png',
    'p3_v5__abel_hands.png',
    'p3_v5__cornelis_hand.png',
    'p3_v5__full.png',
    'p4_feather__full.png',
    'p4_feather__hands.png',
    'p4_restyle__face.png',
    'p4_restyle__full.png',
    'p4_restyle__ref_face.png',
    'p4_restyle__torso.png',
    'p5_ok__full.png',
    'p5_ok__hands.png',
]

# The five question texts the bench repeats across its six pictures, verbatim.
Q_HAND = 'Is there a hand anywhere in this picture with the wrong number of fingers, fused fingers, or an extra digit?'
Q_OBJ = 'Is there an object in this picture that is duplicated or does not belong in the scene?'
Q_COL = 'Is there a patch or garment whose colour is clearly wrong for this scene, such as a cyan smudge or a purple garment?'
Q_STY = 'Does any part of this painted picture look like a photograph pasted into the painting?'
Q_OPEN = 'List every visual defect you can find in this picture: hands and fingers, objects, colours, anatomy. Be brief and concrete.'

COND = {
    'temperature': 0.0,
    'seed': 11,
    'max_tokens': 80,
    'repeats': 3,
    'image_format': 'png sRGB at the bench crop size, no runner-side resize',
    'note': 'the bench asked one crop, one question, one call — never a batch. vlm_ollama takes temperature and '
    'seed through options; vlm_inspector takes the tier and the question text and runs in its own venv.',
}
COND_LONG = dict(COND, max_tokens=500)

# (bench id, crop image(s), question text, expected, column fed)
BENCH_Q = [
    ('q00', ['p4_restyle__full.png'], Q_HAND, 'no', 'fused_finger'),
    ('q01', ['p4_feather__full.png'], Q_HAND, None, 'fused_finger'),
    ('q02', ['p3_sixdigit__full.png'], Q_HAND, 'yes', 'fused_finger'),
    ('q03', ['p1_v5__full.png'], Q_HAND, 'no', 'fused_finger'),
    ('q04', ['p3_v5__full.png'], Q_HAND, 'no', 'fused_finger'),
    ('q05', ['p5_ok__full.png'], Q_HAND, 'no', 'fused_finger'),
    ('q06', ['p4_restyle__full.png'], Q_OBJ, 'no', 'anachronism_judge'),
    ('q07', ['p4_feather__full.png'], Q_OBJ, 'yes', 'anachronism_judge'),
    ('q08', ['p3_sixdigit__full.png'], Q_OBJ, 'no', 'anachronism_judge'),
    ('q09', ['p1_v5__full.png'], Q_OBJ, 'no', 'anachronism_judge'),
    ('q10', ['p3_v5__full.png'], Q_OBJ, 'no', 'anachronism_judge'),
    ('q11', ['p5_ok__full.png'], Q_OBJ, 'no', 'anachronism_judge'),
    ('q12', ['p4_restyle__full.png'], Q_COL, 'yes', 'costume_judge'),
    ('q13', ['p4_feather__full.png'], Q_COL, 'no', 'costume_judge'),
    ('q14', ['p3_sixdigit__full.png'], Q_COL, 'no', 'costume_judge'),
    ('q15', ['p1_v5__full.png'], Q_COL, 'yes', 'seam_judge'),
    ('q16', ['p3_v5__full.png'], Q_COL, 'no', 'costume_judge'),
    ('q17', ['p5_ok__full.png'], Q_COL, 'no', 'costume_judge'),
    ('q18', ['p4_restyle__full.png'], Q_STY, 'no', 'seam_judge'),
    ('q19', ['p4_feather__full.png'], Q_STY, 'no', 'seam_judge'),
    ('q20', ['p3_sixdigit__full.png'], Q_STY, 'no', 'seam_judge'),
    ('q21', ['p1_v5__full.png'], Q_STY, 'yes', 'seam_judge'),
    ('q22', ['p3_v5__full.png'], Q_STY, 'yes', 'seam_judge'),
    ('q23', ['p5_ok__full.png'], Q_STY, 'no', 'seam_judge'),
    ('q24', ['p4_restyle__full.png'], Q_OPEN, None, 'explains_judge'),
    ('q25', ['p4_feather__full.png'], Q_OPEN, None, 'explains_judge'),
    ('q26', ['p3_sixdigit__full.png'], Q_OPEN, None, 'explains_judge'),
    ('q27', ['p1_v5__full.png'], Q_OPEN, None, 'explains_judge'),
    ('q28', ['p3_v5__full.png'], Q_OPEN, None, 'explains_judge'),
    ('q29', ['p5_ok__full.png'], Q_OPEN, None, 'explains_judge'),
    ('q30', ['p4_restyle__torso.png'], "Is the boy's jacket purple or violet?", 'yes', 'costume_judge'),
    ('q31', ['p4_restyle__torso.png'], "Is the boy's jacket brown?", 'no', 'costume_judge'),
    (
        'q32',
        ['p4_restyle__face.png', 'p4_restyle__ref_face.png'],
        'Here are two face crops. Are they the same person?',
        'no',
        'face_melt',
    ),
    (
        'q33',
        ['p4_feather__hands.png'],
        'Is there more than one feather quill in this crop?',
        'yes',
        'anachronism_judge',
    ),
    (
        'q34',
        ['p4_feather__hands.png'],
        'Is there a feather lying on the page, separate from the one held in the hand?',
        'yes',
        'anachronism_judge',
    ),
    ('q35', ['p4_feather__hands.png'], 'Is there an inkpot in this crop?', 'no', 'anachronism_judge'),
    (
        'q36',
        ['p4_feather__hands.png'],
        'Does the writing hand holding the quill have exactly five digits?',
        None,
        'fused_finger',
    ),
    ('q37', ['p3_sixdigit__hand.png'], 'Does this hand have exactly five digits?', 'no', 'fused_finger'),
    (
        'q38',
        ['p3_sixdigit__hand.png'],
        'Is there a curled extra finger or digit inside the palm of this hand?',
        'yes',
        'fused_finger',
    ),
    (
        'q39',
        ['p3_sixdigit__hand.png'],
        'Is the white cuff one single unbroken band around the wrist?',
        'no',
        'seam_judge',
    ),
    ('q40', ['p3_sixdigit__hand.png'], 'Is the hand wearing a ring?', 'no', 'anachronism_judge'),
    (
        'q41',
        ['p1_v5__hand.png'],
        'Is there a cyan or teal coloured smudge in the water next to the hand?',
        'yes',
        'seam_judge',
    ),
    ('q42', ['p1_v5__sea.png'], 'Is there a cyan or teal coloured patch in this water?', 'yes', 'seam_judge'),
    ('q43', ['p1_v5__hand.png'], 'Does the hand look like a photograph rather than a painting?', 'yes', 'seam_judge'),
    ('q44', ['p1_v5__hand.png'], 'Is the hand holding a rope?', 'no', 'anachronism_judge'),
    ('q45', ['p1_v5__hand.png'], 'Does this hand have exactly five digits?', None, 'fused_finger'),
    (
        'q46',
        ['p3_v5__cornelis_hand.png'],
        'Does the hand look like a photograph pasted into a painting?',
        'yes',
        'seam_judge',
    ),
    ('q47', ['p3_v5__cornelis_hand.png'], 'Does this hand have exactly five digits?', None, 'fused_finger'),
    (
        'q48',
        ['p3_v5__abel_hands.png'],
        'Do these hands look like photographs rather than painted?',
        'yes',
        'seam_judge',
    ),
    ('q49', ['p3_v5__abel_hands.png'], 'Are the trousers brown?', 'yes', 'costume_judge'),
    ('q50', ['p3_v5__abel_hands.png'], 'Does each hand have exactly five digits?', None, 'fused_finger'),
    ('q51', ['p5_ok__hands.png'], 'Does the hand on the book have exactly five digits?', 'yes', 'fused_finger'),
    (
        'q52',
        ['p5_ok__hands.png'],
        'Is there a colour patch or smudge that does not belong in this crop?',
        'no',
        'seam_judge',
    ),
    (
        'q53',
        ['p5_ok__hands.png'],
        'Is there an object that does not belong, such as a second book or an extra feather?',
        'no',
        'anachronism_judge',
    ),
    ('q54', ['p5_ok__hands.png'], 'Does the hand look like a photograph pasted into the painting?', 'no', 'seam_judge'),
]

UNSCORED = (
    'the bench left this question WITHOUT an expected answer (spec.py, expected: null) because the operator '
    'could not decide it from the crop by eye. It is therefore an operator question here, never a key: the '
    'answer is read blind and the trial only scores when the operator can say yes or no themselves.'
)

PROBES = []
for _qid, _imgs, _q, _exp, _col in BENCH_Q:
    _open = _q == Q_OPEN
    _p = {
        'id': 'b_' + _qid,
        'title': f'{_qid}: ' + _q[:64],
        'feeds': [_col],
        'inputs': {
            'task': _q,
            'image': [CROPS + '/' + i for i in _imgs],
            'fixture': {
                'path': CROPS + '/' + _imgs[0],
                'bench_q': _qid,
                'run': RUN_ID,
                'key': {'expected': _exp},
                'verified': True,
            },
        },
        'conditions': dict(COND_LONG if _open else COND),
        'grade': 'measured',
    }
    if _open:
        _p['checks'] = [
            {
                'check': 'regex_present',
                'pattern': r'(?i)(hand|finger|digit|colour|color|face|object|seam|photo)',
                'note': 'an open defect list that names no part of the picture is not a defect list',
            },
            {
                'check': 'operator',
                'blind': True,
                'question': "Shown this list beside the operator's own rejection reason for the picture: does the list "
                'name the real fault, in words a reviewer could act on, without burying it in invented ones? '
                'Yes or no. A maybe is a no.',
            },
        ]
        _p['state_note'] = (
            'the bench scored yes/no only and never read the explanations (sheet limitation 4). This '
            'probe is what fills that gap: the open list is read blind against the operator reason.'
        )
    elif _exp is None:
        _p['checks'] = [
            {
                'check': 'operator',
                'blind': True,
                'question': f'Looking at this crop yourself: {_q} Then: did the model give the same answer? '
                'Yes or no. If you cannot tell from the crop, the trial is not scored.',
            }
        ]
        _p['state_note'] = UNSCORED
    else:
        _p['checks'] = [{'check': 'bench_expected', 'bench_q': _qid, 'expected': _exp}]
    PROBES.append(_p)

# ── the classes the bench never showed a picture of ───────────────────────────────────
DEF_DIR = 'capability_tests/fixtures/judge/defects'
# column -> (question asked of both halves, what the POSITIVE picture must contain, how it is made)
UNBENCHED = {
    'fused_finger': (
        'Are any two fingers on this hand fused together into a single finger?',
        'a hand whose ring and little fingers merge into one mass',
        'the hand-repaint sweep already run for p3/p4 produces fusions at denoise >= 0.8; pick one take '
        'that MediaPipe hand_landmarker reads as 4 landmarked fingers where the plate has 5, and the '
        'matched negative is the accepted take of the same shot and seed',
    ),
    'limb_count': (
        'Does the person in this picture have exactly two arms and two legs?',
        'a figure with a third arm or a missing leg',
        'a WAN/Qwen full-body take from the Ledger sweep whose ultralytics pose read returns more than one '
        'left elbow; negative = the accepted take of the same shot',
    ),
    'face_melt': (
        'Is this face cleanly drawn, rather than melted, smeared or ghosted?',
        'a face that has smeared into the background',
        'a restyle take at denoise >= 0.9 on the p4 face crop, chosen where look_gate scores below 0.20 '
        '(the p4_restyle drift of 0.226 is the mildest example we have); negative = the same crop at 0.55',
    ),
    'eye_mismatch': (
        "Are this person's two eyes a matched pair — the same size, the same shape, looking the same way?",
        'a face whose eyes differ in size or point in different directions',
        'a face crop from the repaint sweep where the MediaPipe face mesh eye-landmark areas differ by '
        'more than 25 %; negative = the plate face of the same character',
    ),
    'teeth_judge': (
        'Are the teeth in this mouth an ordinary, evenly spaced row?',
        'a smiling mouth with merged or doubled teeth',
        'render the cast smile prompt at three seeds and keep the take the operator rejects by eye; '
        'negative = the take they accept, same seed family',
    ),
    'anachronism_judge': (
        'Is there an object in this seventeenth-century Dutch scene that did not exist in 1671?',
        'a period scene holding one modern object',
        'take the accepted p5 plate and inpaint ONE modern object (a wristwatch on the wrist) with '
        'the house fill service at a fixed seed; the negative is the untouched plate',
    ),
    'text_judge': (
        'Is every word of lettering visible in this picture spelled correctly?',
        'a shop board or ledger page with one misspelled word',
        'render the quay signage prompt, then OCR every take with the typography judge and keep one whose '
        'OCR string differs from the prompt word; negative = a take whose OCR matches exactly',
    ),
    'perspective_judge': (
        'Do the straight lines of this room or street meet at one consistent vanishing point?',
        'an interior whose floor and ceiling lines disagree',
        'a generated interior the operator rejects for perspective; negative = the Blender scene '
        'render of the same room, which is correct by construction',
    ),
    'light_judge': (
        'Do all the objects in this picture cast their shadows in the same direction?',
        'a scene with two contradictory shadow directions',
        'composite an inpainted figure lit from the left into a plate lit from the right; the negative is '
        'the same composite with the figure relit to match',
    ),
    'scale_judge': (
        'Is the barrel in this picture the right size next to the person standing beside it?',
        'an object at plainly the wrong scale beside a person',
        'a Blender scene render with one prop scaled to 2.5x, and the same frame at 1.0x as the negative — '
        'the only difference is the scale, so nothing else can explain a verdict',
    ),
    'dupe_person': (
        'Does the same person appear twice in this picture?',
        'one character rendered twice in one frame',
        'a crowd take from the Ledger sweep where ArcFace (identity_qc_service.py) finds two faces above '
        'the 0.45 cosine of the same cast reference; negative = a take with no such pair',
    ),
    'crowd_judge': (
        'Are the people in the background of this picture drawn as whole, correct figures?',
        'background figures with melted faces or missing limbs',
        'a market-square take at 1024 where the operator rejects the background crowd; negative = the '
        'same prompt rendered at 1536 where the background holds up',
    ),
    'video_frames': (
        Q_HAND,
        'eight consecutive frames of a clip whose hand breaks in the middle',
        'ffmpeg -vf "select=not(mod(n\\,6))" over an existing WAN take from the Ledger intro, eight PNGs '
        'per clip, one clip with a hand defect and one without; every number on this sheet is from '
        'stills, so this pair is what makes the column answerable at all',
    ),
    'temporal_judge': (
        'Watching these frames in order: does anything change between them that should not change — a '
        'hand swapping shape, a hat appearing, a garment changing colour?',
        'a clip whose garment colour flips between frames',
        'the same eight-frame extraction over a take the operator rejected for temporal drift; the '
        'negative is a take that holds. NOTE the judge design rule in vlm_inspector.py: temporal '
        'defects are deliberately left to the pixel metrics, so a `no` here is an expected answer',
    ),
    'photoreal_src': (
        Q_HAND,
        'a photograph, not a painted frame',
        'six CC0 photographs of hands at the bench crop sizes, three with a visible anatomical fault, '
        'three without; the sheet limitation says nothing here transfers to photographic material, and '
        'this is the pair that would test it',
    ),
    'other_style': (
        Q_HAND,
        'a picture in a house style other than the Ledger intro',
        'the same six defect classes rendered in the kids 2D flat style and in the photoreal character '
        "style, positives and negatives matched; one art style and one scene family is the bench's "
        'largest single limitation',
    ),
}

for _col, (_q, _pos, _recipe) in UNBENCHED.items():
    PROBES.append(
        {
            'id': 'x_' + _col,
            'title': 'unbenched class: ' + _col,
            'feeds': [_col],
            'inputs': {
                'task': _q,
                'image': [f'{DEF_DIR}/{_col}/pos.png', f'{DEF_DIR}/{_col}/neg.png'],
                'fixture': {
                    'path': f'{DEF_DIR}/{_col}/',
                    'generated': _recipe,
                    'verified': False,
                    'blocks': [_col],
                    'positive': _pos,
                    'how_to_verify': 'the operator opens the pair once, confirms by eye that the positive '
                    'shows the fault and the negative does not, writes the key from what '
                    'is in the picture (never from the prompt), and flips verified',
                },
            },
            'conditions': dict(COND),
            'checks': [
                {
                    'check': 'answer_equals_fixture_key',
                    'note': 'each half carries its own key: yes on the positive, no on the negative',
                },
                {'check': 'recall_precision_min', 'recall': 0.8, 'precision': 0.8},
            ],
            'grade': 'measured',
            'state_rule': {'yes': 0.8, 'partial': 0.5},
            'state_note': (
                'BLOCKED until the pair exists and the operator has verified it. Until then this column is '
                'written untested "no picture yet", which is the honest state — the band is called "Defect '
                'classes not benched" because that is what the 2026-09-27 run was.'
            ),
        }
    )

# ── the four protocols the bench itself said were the next tests ──────────────────────
PROBES.append(
    {
        'id': 'u_two_phrasing',
        'title': 'The same defect asked two ways, scored on the agreement and on the OR',
        'feeds': ['two_phrasing'],
        'inputs': {
            'task': 'three pairs of bench questions, each pair about ONE crop, asked in two wordings',
            'pairs': [
                {'pair': ['q33', 'q34'], 'image': CROPS + '/p4_feather__hands.png', 'expected': 'yes'},
                {
                    'pair': ['q30', 'q31'],
                    'image': CROPS + '/p4_restyle__torso.png',
                    'expected': 'yes',
                    'note': 'q31 is the inverted wording: its bench expected is `no`, which is the same fact',
                },
                {
                    'pair': ['q37', 'q38'],
                    'image': CROPS + '/p3_sixdigit__hand.png',
                    'expected': 'yes',
                    'note': 'q37 expected `no` (not five digits) and q38 expected `yes` (a curled extra one)',
                },
            ],
            'fixture': {
                'path': CROPS,
                'run': RUN_ID,
                'verified': True,
                'key': {'source': "the bench's own expected values for the six question ids"},
            },
        },
        'conditions': dict(COND),
        'checks': [
            {'check': 'phrasing_agrees', 'pair': ['q33', 'q34'], 'expected': 'yes'},
            {'check': 'phrasing_agrees', 'pair': ['q30', 'q31'], 'expected': 'yes'},
            {'check': 'phrasing_agrees', 'pair': ['q37', 'q38'], 'expected': 'yes'},
        ],
        'grade': 'measured',
        'state_rule': {'yes': 0.8, 'partial': 0.4},
        'state_note': (
            'this is bench note 3 turned into a test: no model said yes to "is there more than one quill", but '
            'half said yes to "is there a feather lying on the page" about the SAME crop. A judge question is '
            'part of the judge. The cell records both the agreement rate (the column) and the OR recall (how '
            'the pipeline would really use two phrasings), so the two are never confused.'
        ),
    }
)

PROBES.append(
    {
        'id': 'u_localise',
        'title': 'Does the answer say WHERE the fault is',
        'feeds': ['localise'],
        'inputs': {
            'task': Q_OPEN + ' For each defect, say where in the picture it is.',
            'image': [CROPS + '/' + p + '__full.png' for p in PICTURES],
            'fixture': {
                'path': CROPS,
                'run': RUN_ID,
                'verified': True,
                'region_key': {
                    'p4_restyle': {
                        'accept': ['jacket', 'doublet', 'torso', 'chest', 'face'],
                        'reject': ['hand', 'sky', 'floor'],
                    },
                    'p4_feather': {
                        'accept': ['page', 'desk', 'table', 'near the hand', 'beside the hand'],
                        'reject': ['face', 'window'],
                    },
                    'p3_sixdigit': {'accept': ['palm', 'hand', 'wrist', 'cuff'], 'reject': ['face', 'wall']},
                    'p1_v5': {'accept': ['water', 'sea', 'rail', 'beside the hand'], 'reject': ['face', 'sky']},
                    'p3_v5': {'accept': ['hands', 'hand', 'water', 'bricks', 'wall'], 'reject': ['sky', 'hat']},
                    'p5_ok': {
                        'accept': [],
                        'reject': [],
                        'note': 'the approved control: any named region is a false alarm',
                    },
                },
            },
        },
        'conditions': dict(COND_LONG),
        'checks': [{'check': 'names_region', 'note': 'scored per picture against the region key above'}],
        'grade': 'measured',
        'state_rule': {'yes': 0.8, 'partial': 0.4},
        'state_note': (
            "the pictures are the bench's and are verified; the REGION key is new and was written from the "
            "operator's truth strings by the author of this test, so it is blocked until the operator confirms "
            'it. A model that is right about the defect and silent about the place fails this column only.'
        ),
    }
)

PROBES.append(
    {
        'id': 'u_severity',
        'title': "Does its 1-5 grade track the operator's",
        'feeds': ['severity'],
        'inputs': {
            'task': 'Grade the worst defect in this picture from 1 (barely noticeable) to 5 (unusable). Answer '
            'with the number alone.',
            'image': [CROPS + '/' + p + '__full.png' for p in PICTURES],
            'fixture': {
                'path': CROPS,
                'run': RUN_ID,
                'verified': True,
                'key': {
                    'operator_grades': 'NOT WRITTEN YET — one 1-5 grade per picture, by the operator, '
                    'before any model is run'
                },
            },
        },
        'conditions': dict(COND, max_tokens=8),
        'checks': [{'check': 'severity_rank_corr', 'set': list(PICTURES), 'min': 0.6}],
        'grade': 'measured',
        'state_rule': {'yes': 0.8, 'partial': 0.4},
        'state_note': (
            'six pictures is a thin rank; the column reads partial at best until the set grows. The bench '
            'scored yes/no and never graded severity at all, so the operator grades are the missing half.'
        ),
    }
)

PROBES.append(
    {
        'id': 'u_reject_only',
        'title': 'One reject/keep verdict per frame, against the per-defect answers',
        'feeds': ['reject_only'],
        'inputs': {
            'task': 'Would you reject this frame from a finished film for a visual defect? Answer yes or no.',
            'image': [CROPS + '/' + p + '__full.png' for p in PICTURES],
            'fixture': {
                'path': CROPS,
                'run': RUN_ID,
                'verified': True,
                'key': {
                    'reject': ['p4_restyle', 'p4_feather', 'p3_sixdigit', 'p1_v5', 'p3_v5'],
                    'keep': ['p5_ok'],
                    'source': "the operator's own written truth for each picture (PICTURES above): "
                    'five carry a named defect, p5_ok is the APPROVED control',
                },
            },
        },
        'conditions': dict(COND),
        'checks': [
            {'check': 'reject_agreement', 'min': 0.8, 'control': 'p5_ok'},
            {
                'check': 'bench_expected',
                'bench_q': 'q29',
                'expected': 'no',
                'note': 'the control cross-check: the open question on p5_ok must also find nothing',
            },
        ],
        'grade': 'measured',
        'state_rule': {'yes': 0.8, 'partial': 0.5},
        'state_note': (
            "the sheet's standing rule is that a VLM may ADD a rejection and never grant a pass. This column "
            'measures whether the single reject verdict is worth anything on its own, and a yes on the '
            'approved control is a hard fail — qwen3.6_35b flagged that control in the 2026-09-27 run.'
        ),
    }
)

FIXTURES = [
    {
        'path': p,
        'verified': True,
        'run': RUN_ID,
        'truth': t,
        'blocks': [],
        'how_to_verify': 'built and rejected/approved by the operator by eye before the bench ran; the truth '
        'string above is theirs, written into spec.py before any model saw the picture',
    }
    for p, t in PICTURES.values()
]
FIXTURES += [
    {
        'path': CROPS + '/' + c,
        'verified': True,
        'run': RUN_ID,
        'blocks': [],
        'how_to_verify': 'cut from the verified source picture by make_crops.py at the box recorded in '
        'sheet.json; a crop of a verified picture needs no second judgement',
    }
    for c in CROP_FILES
]
FIXTURES += [p['inputs']['fixture'] for p in PROBES if p['id'].startswith('x_')]

TEST = {
    'step': 'vlm_judges',
    'version': '2026-09-30.1',
    'title': 'The 2026-09-27 defect bench, fixed as the default test',
    'purpose': 'Run every judge through the operator-built defect bench under byte-identical conditions, and say '
    'plainly which defect classes have no picture yet rather than claiming a number for them.',
    'include_shared': 'judge',
    'rows': {
        'qwen3vl_8b': {
            'transport': 'vlm_inspector',
            'model': 'Qwen3-VL 8B Instruct FP8',
            'where': 'vlm_inspector.py tier="resident" (ZYG_VLM_RESIDENT_MODEL), isolated venv subprocess',
            'budget': {
                'minutes': 47,
                'gpu_minutes': 47,
                'note': '1750 calls x 1.5 s measured on the bench + 3 min model load',
            },
            'note': 'fastest and quietest: bench accuracy 0.64, recall 0.24, specificity 0.89 — it misses '
            'most defects and almost never false-alarms',
        },
        'qwen3vl_32b': {
            'transport': 'vlm_inspector',
            'model': 'Qwen3-VL 32B',
            'where': 'vlm_inspector.py tier="boundary" (ZYG_VLM_BOUNDARY_MODEL), run alone behind '
            'comfy_offload.gpu_exclusive — it may never run while ComfyUI is sampling',
            'budget': {
                'minutes': 93,
                'gpu_minutes': 93,
                'note': '1750 x 3.0 s measured + 3 min load; the ComfyUI offload/reload swap costs '
                'another 1-3 min at each end and is not counted here',
            },
            'note': 'bench accuracy 0.66, recall 0.47, specificity 0.78',
        },
        'qwen3.5_9b': {
            'transport': 'vlm_ollama',
            'model': 'qwen3.5:9b',
            'note': 'the default row: bench accuracy 0.66, recall 0.47, specificity 0.78 at 5.9 s',
        },
        'qwen3.6_35b': {
            'transport': 'vlm_ollama',
            'model': 'qwen3.6:35b-a3b',
            'budget': {
                'minutes': 429,
                'gpu_minutes': 429,
                'note': '1750 x 14.6 s measured on the bench + 3 min load = ~7 h on the GPU',
            },
            'note': 'best recall (0.82) and worst specificity (0.48): the only model that ever saw the '
            'curled extra digit, and it also claimed a sixth finger on a picture with none',
        },
        'moondream': {
            'transport': 'vlm_ollama',
            'model': 'moondream:latest',
            'budget': {
                'minutes': 516,
                'gpu_minutes': 516,
                'tokens_out': 0,
                'tokens_note': 'it returned no answer at all on any scored question of the bench',
                'note': '1750 x 17.6 s measured + 3 min load; it is slow AND silent',
            },
            'note': 'returned a null answer on all 44 scored questions (acc 0.00, none 44). That is a '
            'MEASURED no on every column it is asked, not untested: it was heard and said nothing.',
        },
    },
    'probes': PROBES,
    'derive': {},
    'lookup': {},
    'wiring': {},
    'na': {
        'frontier': (
            'a frontier API judge is not a row of this sheet — every row here is a local model on this box. '
            'Pricing the gap needs an anthropic_api or github_models row added to the sheet first, which is '
            'a change to the sheet, not a cell of it. The bench named it as its own next test.'
        ),
    },
    'fixtures': FIXTURES,
    'keys_unverified': [
        {
            'id': "region key for localise (written by this test's author from the operator truth strings)",
            'blocks': ['localise'],
            'how_to_verify': 'open each of the six pictures, confirm the accept/reject region words in u_localise name '
            'where the fault actually is, then set the probe fixture verified and bump version',
        },
        {
            'id': 'operator 1-5 severity grades for the six bench pictures (do not exist)',
            'blocks': ['severity'],
            'how_to_verify': 'the operator grades each of the six pictures 1-5 for its worst defect, blind to any model '
            'output, and writes the six numbers into u_severity before the test is run',
        },
    ],
    'run_order': [
        'b_q30',
        'b_q31',
        'b_q37',
        'b_q38',
        'b_q39',
        'b_q41',
        'b_q42',
        'b_q33',
        'b_q34',
        'b_q35',
        'the remaining 45 bench questions',
        'u_two_phrasing',
        'u_reject_only',
        'u_localise',
        'u_severity',
        'the 16 unbenched-class probes (they will report blocked until their pairs exist)',
        'the shared judge bank last — its 1584 subject calls are the bulk of the cost',
    ],
    'budget': {
        'calls': 1750,
        'tokens_in': 2450000,
        'tokens_out': 79000,
        'minutes': 175,
        'gpu_minutes': 175,
        'operator_minutes': 14,
        'note': (
            '55 bench questions x 3 repeats = 165 calls, plus the shared judge bank: 132 subjects x 2 halves '
            '(positive and negative) x 3 repeats x 2 bands (Sees and Names) = 1584, so 1749 ~ 1750 calls per '
            'row. A 1024x1024 crop is ~1400 vision tokens plus a ~30-token question: 1750 x 1400 = ~2.45M in; '
            'answers average ~45 tokens (the open ones ~200): 1750 x 45 = ~79k out. Wall clock is 1750 x the '
            "row's own measured seconds per question from the 2026-09-27 bench (1.5 / 3.0 / 5.9 / 14.6 / 17.6 s "
            '-> 47 / 93 / 175 / 429 / 516 min, overridden per row), all of it on the GPU. Operator per row: the '
            '5 unscored bench questions x 3 repeats plus the 6 open lists x 3 = 33 blind decisions at ~30 s = '
            '~14 min (the bank adds its own on top). ONE-TIME, not per row: verifying the 16 unbenched pairs '
            '(~60 min once they exist), writing the six severity grades (~5 min) and confirming the region key '
            '(~10 min). No claude_cli or anthropic_api row is in this test, so the shared Claude week is not '
            'touched; the whole cost is GPU hours on this box.'
        ),
    },
    'notes': [
        'This sheet is generated from the bench, so the default test IS the bench, pinned by run id and by the six '
        'source pictures. A rerun with different pictures is a different test and must carry a different hash.',
        "Ground truth is the operator's own rejection reason per picture, written into spec.py BEFORE any model ran. "
        'Nothing in this test lets a VLM verify a fixture — the models being asked are the models being tested.',
        '16 of the 24 columns are blocked on a picture that does not exist yet. That is not a gap in the test: the '
        'two bands are literally named "Defect classes not benched" and "Untested conditions", and a blocked column '
        'is the honest reading of them. The recipes in UNBENCHED are what would unblock each one.',
        'moondream is the reason an empty answer must be a `no` and not `untested`: it was reachable, it was asked 44 '
        'times, and it returned nothing. Its transport did not fail; the model did.',
    ],
}
