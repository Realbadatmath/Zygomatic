# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Default test — Character identity / adapters (identity). 2026-09-30.

Question the sheet asks: which adapter keeps the same face across stills, and how is that
measured? The sheet's own limitation says there has never been an adapter-versus-adapter bench
on one character — InstantID is the de-facto reference only because the Ledger work measured
against it. This test is that bench: ONE reference picture of Abel, byte-identical for every
row, and the house instrument (identity_qc_service, AuraFace/glintr100 via the ComfyUI venv)
scoring every still at the service's OWN calibrated thresholds.

Shape of the test
-----------------
Eighteen domain columns, nineteen probes, one derive. Every cosine threshold below is READ OFF
identity_qc_service.py rather than chosen here: auraface frontal 0.465, oblique 0.317, profile
0.206, full body 0.18 (quantile-matched on 630 same-person / 6.9K cross-person pairs,
data/runtime/auraface_calibration.json, 2026-08-09). Moving a threshold to flatter a row would
make this sheet incomparable with the contact-sheet gate that ships.

Three standing facts are built into the probes, not left to the runner:
  * A HIGH COSINE IS NOT A SANE PICTURE. Two half-people from a misaligned grid slice scored
    0.44 and entered a training set. So `content_truth` pairs the cosine with the service's own
    content-truth verdicts (multi_face / face_cut / mislabeled_angle) AND a blind operator
    question — the 2026-09-27 defect bench (best local VLM 34/40 global, 2/8 on the hard cases)
    is why no VLM appears anywhere in this file.
  * EMBEDDINGS CARRY NO BACK-OF-HEAD INFORMATION. `back` therefore has no cosine check at all:
    it is a blind operator question plus the assertion that the gate correctly exempts the tile
    (no_face_expected). A cosine on a back view would be a number that means nothing.
  * COMFYUI LoRAs WERE A SILENT NO-OP STACK-WIDE until convert_lora.py (2026-09-23). Every
    probe that turns a lever on carries a `lora_applied` check, and `never_applied` is an A/B:
    adapter on and adapter off must produce DIFFERENT pictures, or the lever is not connected.

What is blocked and why
-----------------------
`fixtures/image/identity/abel_ref.png` is the single reference every cosine is measured against
and NOBODY HAS VERIFIED IT YET. It blocks the fourteen cosine-bearing columns: we do not grade
a model against an answer we have not checked ourselves. `never_applied`, `content_truth`,
`age_lock` and `quality_cost` are NOT blocked — they need a reference to exist, not to be the
right one.

The `arcface` row is the INSTRUMENT, not a generator. It answers `measured_against`,
`content_truth` and `never_applied` (a gate that passes everything is the same defect as a LoRA
that was never applied) and is na on everything that needs a picture to be made, with the
reason on each cell.
"""

from __future__ import annotations

# ── check kinds this step needs and the base vocabulary does not have ──────────────────────
CHECK_KINDS = {
    'identity_cosine_house': (
        'identity_qc_service.score_tile cosine between this still and `ref` is >= `min`, computed '
        'by the HOUSE instrument (pack ZYG_IDQC_PACK, default auraface: glintr100 recogniser, '
        "scrfd_10g_bnkps detection, 1k3d68 landmarks, run in the ComfyUI venv) — not the bank's "
        "buffalo_l. When `min` is absent the tile's `angle` label selects the service threshold "
        '(frontal 0.465, oblique 0.317, profile 0.206, fullbody 0.18) and the check records which.'
    ),
    'idqc_verdict_in': (
        'identity_qc_service.score_tile verdict for this still is in `expect` — one of pass, fail, '
        'multi_face, face_cut, mislabeled_angle, no_face, no_face_expected. This is the CONTENT-TRUTH '
        'layer, independent of the cosine: a tile can pass the cosine and fail here.'
    ),
    'identity_pair_assign': (
        'every face the detector finds in the frame is assigned to its nearest reference in `refs` by '
        'house cosine; the assignment must be a bijection (no reference used twice, no face left over), '
        "each face's cosine to its own reference >= `min`, and its cosine to the other reference lower "
        'by at least `margin`. Two faces that both look like reference A is a FAIL, not a half pass.'
    ),
    'lora_applied': (
        'the ComfyUI log for this render shows the file in `lora` both LOADED and APPLIED (a non-zero '
        'weight delta on the sampled model), not merely requested — the 2026-09-23 stack-wide silent '
        'no-op. A render whose LoRA was requested and not applied is untested, not a no.'
    ),
}

# ── the reference and the fixed render settings ────────────────────────────────────────────
REF = 'capability_tests/fixtures/image/identity/abel_ref.png'
REF_BLUR = 'capability_tests/fixtures/image/identity/abel_ref_blur.png'
REF_ANNA = 'capability_tests/fixtures/image/identity/anna_ref.png'
REF_SET = [
    REF,
    'capability_tests/fixtures/image/identity/abel_ref_b.png',
    'capability_tests/fixtures/image/identity/abel_ref_c.png',
    'capability_tests/fixtures/image/identity/abel_ref_d.png',
]
TILES_BAD = 'capability_tests/fixtures/image/identity/content_truth_tiles/'
DEPTH_MAP = 'capability_tests/fixtures/image/identity/mannequin_depth.png'

# identity_qc_service.py thresholds, copied verbatim so the sheet says which gate it used.
T_FRONTAL, T_OBLIQUE, T_PROFILE, T_FULLBODY = 0.465, 0.317, 0.206, 0.18

NEG = (
    'lowres, blurry, out of focus, jpeg artefacts, extra limbs, extra fingers, fused fingers, '
    'missing fingers, deformed hands, extra heads, duplicated subject, mutated anatomy, cross-eyed, '
    'cartoon, anime, 3d render, cgi, plastic skin, modern clothing, modern buildings, cars, '
    'plastic packaging, neon light'
)

COND = {
    'width': 1024,
    'height': 1024,
    'seeds': [11, 12, 13],
    'repeats': 3,
    'negative': NEG,
    'reference': REF,
    'adapter_weight': "the row's production default, read out of its workflow "
    'JSON at run time and written into the trial',
    'lora': None,
    'note': 'same size, same three seeds, same negative, same single reference for every row; '
    "steps/cfg/sampler come from the row's own workflow JSON so the sheet says what the "
    'house gets, not what a test-writer preferred',
}


def _cond(**kw):
    c = dict(COND)
    c.update(kw)
    return c


RULE = {'yes': 0.9, 'partial': 0.5}
RULE_STRICT = {'yes': 1.0, 'partial': 0.6}

# The six stills of the same_face set. Fixed wording, under 60 words each (SDXL truncates at 77
# CLIP tokens without warning, so a longer prompt would measure truncation instead of identity).
SIX = [
    'Abel, a boy of nine, head and shoulders, facing the camera, plain grey background, flat daylight',
    'Abel, a boy of nine, head and shoulders, facing the camera, a dark farmhouse loft behind him, one candle',
    'Abel, a boy of nine, standing on a cobbled quay in 1671, whole body in frame, overcast daylight',
    'Abel, a boy of nine, sitting at a table with a ledger open in front of him, window light from the left',
    'Abel, a boy of nine, in a red wool cloak on a wooden jetty, grey sky, whole body in frame',
    'Abel, a boy of nine, head and shoulders, wet hair, rain on his face, harbour behind him',
]

OP = 'Is this the same child as the reference picture shown beside it — the same person, not merely a similar-looking boy?'
OP_SANE = (
    'Is this one whole person, correctly framed: exactly one head, one body, no second partial '
    'figure, nothing sliced off at the tile edge?'
)


def _p(pid, title, feeds, prompt, checks, cond=None, **kw):
    p = {
        'id': pid,
        'title': title,
        'feeds': list(feeds),
        'inputs': {'prompt': prompt, 'reference': REF},
        'conditions': cond or _cond(),
        'checks': list(checks),
        'grade': 'measured',
        'state_rule': dict(RULE),
    }
    p.update(kw)
    return p


PROBES = [
    # ── the core bench: one child, six stills, the house gate ──
    _p(
        'id_same_face',
        'Six stills of Abel, scored by the house gate at its own thresholds',
        ['same_face'],
        SIX,
        [
            {
                'check': 'identity_cosine_house',
                'ref': REF,
                'min': T_FRONTAL,
                'angle': 'frontal',
                'note': 'stills 1, 2, 4 and 6 are head-and-shoulders: the frontal gate applies',
            },
            {
                'check': 'identity_cosine_house',
                'ref': REF,
                'min': T_FULLBODY,
                'angle': 'fullbody',
                'note': 'stills 3 and 5 are whole-body: clean full-body cells measured 0.21-0.39 on the '
                '2026-07-16 runs, so the frontal gate would flag them — the 0.18 floor is the honest one',
            },
            {'check': 'operator', 'question': OP},
        ],
        run_order=3,
        state_note='18 trials (6 stills x 3 seeds). yes at >= 90 % of trials over BOTH the cosine and the '
        'blind operator; the two disagree often and the sheet records both rates in the note. '
        'The cosine decides the state; the operator rate is the receipt that says whether the '
        'cosine can be trusted on this row.',
    ),
    _p(
        'id_angles',
        'Off-frontal: the 48-angle sheet at 45 degrees',
        ['angles'],
        [
            'Abel, a boy of nine, head and shoulders, turned 45 degrees to his left, plain grey background, flat daylight',
            'Abel, a boy of nine, head and shoulders, turned 45 degrees to his right, plain grey background, flat daylight',
        ],
        [
            {'check': 'identity_cosine_house', 'ref': REF, 'min': T_OBLIQUE, 'angle': 'oblique'},
            {
                'check': 'idqc_verdict_in',
                'expect': ['pass'],
                'note': 'an oblique label with |yaw| under 12 degrees is under-rotated content on a 45 label '
                '(OBLIQUE_LABEL_MIN_YAW) and the service calls it mislabeled_angle — that is a fail here too',
            },
            {'check': 'operator', 'question': OP},
        ],
        run_order=4,
    ),
    _p(
        'id_profile',
        'Profile: the same sheet at 90 degrees',
        ['profile'],
        [
            'Abel, a boy of nine, head and shoulders, full profile facing left, plain grey background, flat daylight',
            'Abel, a boy of nine, head and shoulders, full profile facing right, plain grey background, flat daylight',
        ],
        [
            {'check': 'identity_cosine_house', 'ref': REF, 'min': T_PROFILE, 'angle': 'profile'},
            {'check': 'idqc_verdict_in', 'expect': ['pass']},
            {'check': 'operator', 'question': OP},
        ],
        run_order=5,
        state_note='0.206 is the AuraFace profile operating point and it is the weakest gate in the service: '
        "FAR 0.61 against glintr100's 0.34, measured on 82 same-person pairs (2026-08-09). The "
        'operator rate on this probe is therefore the load-bearing number, not the cosine.',
    ),
    _p(
        'id_back',
        'Back of the head at 180 degrees — no cosine is possible',
        ['back'],
        [
            'Abel, a boy of nine, seen from directly behind, head and shoulders, plain grey background, flat daylight',
            'Abel, a boy of nine, seen from directly behind, whole body, on a cobbled quay in 1671, overcast daylight',
        ],
        [
            {
                'check': 'idqc_verdict_in',
                'expect': ['no_face_expected'],
                'note': 'the gate must EXEMPT this tile. A face found on a back label with |yaw| under 45 degrees '
                '(BACK_LABEL_MIN_YAW) is frontal content on a back label and the service calls it '
                'mislabeled_angle — which is a fail of the render, not of the gate',
            },
            {
                'check': 'operator',
                'question': 'Is this the same child as the reference, judged on hair colour, '
                'hair cut, build and costume only — and is the head actually turned '
                'away from the camera?',
            },
        ],
        run_order=6,
        state_note='NO COSINE CHECK. ArcFace embeddings carry no back-of-head information, so a number here '
        'would be noise dressed as a measurement. The operator decides; the gate is only asked to '
        'exempt the tile. The LoRA flywheel is what actually covers back views.',
    ),
    _p(
        'id_child',
        'The reference is a child: does the adapter hold a child face at all',
        ['child_face'],
        [
            'Abel, a boy of nine, head and shoulders, facing the camera, plain grey background, flat daylight, '
            'smooth young skin, no facial hair, child proportions'
        ],
        [
            {'check': 'identity_cosine_house', 'ref': REF, 'min': T_FRONTAL, 'angle': 'frontal'},
            {
                'check': 'operator',
                'question': 'Is the person in this picture a child of about nine, not a small adult and not a toddler?',
            },
        ],
        run_order=7,
        state_note='Abel IS the reference age — the child case is the default here, not a stress test. An '
        'adapter trained on adult faces typically ages the subject up while keeping a high cosine, '
        'which is exactly why the operator question asks about age and the cosine does not.',
    ),
    _p(
        'id_age_lock',
        'Does the character stay nine when the prompt does not say so',
        ['age_lock'],
        [
            'Abel on the Kattenburg quay at dusk, 1671, holding a lit lantern, whole body in frame',
            'Abel in a red wool cloak at the yard gate at dawn, 1671, whole body in frame',
            'Abel beside a moored wooden sailing ship, morning mist, 1671, whole body in frame',
        ],
        [
            {
                'check': 'operator',
                'question': 'Is the person in this picture about nine years old — not a teenager and not an adult?',
            }
        ],
        run_order=8,
        state_note='OPERATOR ONLY, deliberately. No mechanical age estimator in this house has been benched '
        'against a verified age, and the cosine is indifferent to age drift: an adapter that ages '
        'Abel to fifteen keeps scoring above the frontal gate. The prompts name no age on purpose.',
    ),
    _p(
        'id_expression',
        'Identity survives a changed expression',
        ['expression_free'],
        [
            'Abel, a boy of nine, head and shoulders, laughing with his mouth open, plain grey background, flat daylight',
            'Abel, a boy of nine, head and shoulders, crying, plain grey background, flat daylight',
            'Abel, a boy of nine, head and shoulders, shouting, plain grey background, flat daylight',
        ],
        [
            {'check': 'identity_cosine_house', 'ref': REF, 'min': T_FRONTAL, 'angle': 'frontal'},
            {'check': 'operator', 'question': OP},
        ],
        run_order=9,
    ),
    _p(
        'id_style',
        'Identity survives the Arcane restyle LoRA at weight 0.4',
        ['style_transfer'],
        [
            'Abel, a boy of nine, head and shoulders, facing the camera, Arcane painterly style, dark teal '
            'palette, visible brush texture'
        ],
        [
            {
                'check': 'lora_applied',
                'lora': 'the Arcane restyle LoRA the arcane_restyle.py path ships, at weight 0.4',
            },
            {
                'check': 'identity_cosine_house',
                'ref': REF,
                'min': T_OBLIQUE,
                'angle': 'oblique',
                'note': 'a restyled face is measured at the OBLIQUE floor, not the frontal one: the recogniser was '
                'trained on photographs and a painterly render costs cosine without costing likeness',
            },
            {'check': 'operator', 'question': OP},
        ],
        cond=_cond(lora={'name': 'arcane restyle', 'weight': 0.4}),
        run_order=11,
        state_note='The lora_applied check comes FIRST for a reason: before 2026-09-23 this probe would have '
        'measured an unstyled render and called the row a pass. A trial whose LoRA did not apply '
        'is untested, not a no.',
    ),
    _p(
        'id_two_people',
        'Two named characters in one frame, each matching its own reference',
        ['two_people'],
        [
            'Abel, a boy of nine, and Anna, a woman of thirty, standing side by side on the Kattenburg quay in '
            '1671, both faces visible, whole bodies in frame, overcast daylight'
        ],
        [
            {'check': 'identity_pair_assign', 'refs': [REF, REF_ANNA], 'min': T_OBLIQUE, 'margin': 0.08},
            {
                'check': 'idqc_verdict_in',
                'expect': ['multi_face'],
                'note': 'the contact-sheet gate is SUPPOSED to reject two faces (MAX_FACES=1). Recording multi_face '
                'here is the receipt that the instrument is unchanged, not a failure of the render',
            },
            {
                'check': 'operator',
                'question': 'Are there exactly two people, and is the boy on the left the same '
                'child as reference A while the woman on the right is the same '
                'person as reference B?',
            },
        ],
        cond=_cond(reference=[REF, REF_ANNA]),
        state_rule=dict(RULE_STRICT),
        run_order=12,
        state_note='Strict rule: both faces must be assigned correctly on every seed. One face matching both '
        'references, or both faces matching Abel, is the classic identity-bleed failure and is a NO.',
    ),
    _p(
        'id_ref_count',
        'How many references it needs: the 1 / 2 / 4 ladder',
        ['ref_count'],
        [SIX[0]],
        [
            {'check': 'identity_cosine_house', 'ref': REF, 'min': T_FRONTAL, 'angle': 'frontal'},
            {'check': 'operator', 'question': OP},
        ],
        cond=_cond(
            reference_ladder=[REF_SET[:1], REF_SET[:2], REF_SET[:4]],
            note='three rungs, the same prompt and the same three seeds on each: 1 reference, 2, then 4',
        ),
        run_order=13,
        state_note='9 trials (3 rungs x 3 seeds). The reported value is the SMALLEST rung whose cosine rate '
        'reaches the yes threshold; yes when one reference is enough, partial when two or four are '
        'needed, no when even four do not reach the gate. A row that takes exactly one reference by '
        'construction reports 1 and says so in the note.',
    ),
    _p(
        'id_ref_quality',
        'Survives a poor reference: the same picture, blurred',
        ['ref_quality'],
        [SIX[0]],
        [
            {
                'check': 'identity_cosine_house',
                'ref': REF,
                'min': T_FRONTAL,
                'angle': 'frontal',
                'note': 'scored against the SHARP reference, not the blurred one — the question is whether the '
                'adapter still finds the right person, not whether it copies the blur',
            },
            {'check': 'operator', 'question': OP},
        ],
        cond=_cond(reference=REF_BLUR),
        run_order=14,
    ),
    _p(
        'id_stack',
        'Stacks with a style LoRA',
        ['stack'],
        ['Abel, a boy of nine, head and shoulders, facing the camera, in the house storybook style'],
        [
            {'check': 'lora_applied', 'lora': 'the house storybook style LoRA at its production weight'},
            {'check': 'identity_cosine_house', 'ref': REF, 'min': T_OBLIQUE, 'angle': 'oblique'},
            {'check': 'operator', 'question': OP},
        ],
        cond=_cond(lora={'name': 'house storybook style', 'weight': 'production default'}),
        run_order=15,
    ),
    _p(
        'id_control_stack',
        'Stacks with a depth ControlNet',
        ['control_stack'],
        [
            'Abel, a boy of nine, standing in the pose of the control map, on a cobbled quay in 1671, '
            'whole body in frame, overcast daylight'
        ],
        [
            {'check': 'identity_cosine_house', 'ref': REF, 'min': T_FULLBODY, 'angle': 'fullbody'},
            {
                'check': 'operator',
                'question': 'Does this figure stand in the same pose as the control map shown '
                'beside it, AND is the face the same child as the reference?',
            },
        ],
        cond=_cond(control={'channel': 'depth', 'map': DEPTH_MAP, 'strength': 0.6}),
        run_order=16,
        state_note='The control map is the mannequin depth plate, the same file the controlnet sheet uses, so '
        'the two sheets can be read together. Full-body floor applies: the face is small here.',
    ),
    _p(
        'id_quality_cost',
        'Does the adapter cost picture quality',
        ['quality_cost'],
        [SIX[0], SIX[2]],
        [
            {
                'check': 'operator',
                'question': 'Of these two pictures, is the LEFT one at least as good as the '
                'right one in skin texture, hair detail and sharpness — ignoring '
                'who the person is?',
            },
            {
                'check': 'image_distance',
                'metric': 'lpips',
                'to': 'id_quality_cost_off',
                'min': 0.10,
                'note': 'the pair must actually differ, or the operator is comparing a picture with itself',
            },
        ],
        cond=_cond(
            ab={
                'on': "the row's adapter at its production weight",
                'off': 'the same workflow with the adapter node bypassed, everything else byte-identical',
            },
            note='A/B, shuffled and anonymised before the operator sees either side',
        ),
        run_order=17,
        state_note='BLIND A/B on quality alone. The operator is never told which side carries the adapter and '
        'the identity question is deliberately excluded from the wording — an adapter that keeps '
        'the face and destroys the skin is a partial, and this is the column that says so.',
    ),
    _p(
        'id_drift_long',
        'Holds across a long set: 24 stills in one session',
        ['drift_long'],
        [
            'the 24-still Abel sequence: the six SIX prompts, each rendered at four consecutive seeds '
            '(11, 12, 13, 14), queued in one ComfyUI session without reloading the adapter'
        ],
        [
            {
                'check': 'identity_cosine_house',
                'ref': REF,
                'angle': 'per-still label',
                'note': "threshold from the still's own angle label, as the service does it",
            },
            {'check': 'operator', 'question': OP},
        ],
        cond=_cond(
            seeds=[11, 12, 13, 14],
            repeats=1,
            note='24 renders, one pass, no reload — drift is what the 24th still does that the first did not',
        ),
        run_order=18,
        state_note='The reported number is the cosine rate over all 24 AND the slope of cosine against position '
        'in the set. A row that passes the first six and fails the last six is a partial with the '
        'slope in the note, not a yes.',
    ),
    # ── the lever really is connected ──
    _p(
        'id_ab_adapter',
        'A/B: adapter on and adapter off must produce DIFFERENT pictures',
        ['never_applied'],
        [SIX[0]],
        [
            {
                'check': 'image_distance',
                'metric': 'lpips',
                'to': 'id_ab_adapter_off',
                'min': 0.15,
                'note': 'the whole point. A distance near zero means the adapter node ran and changed nothing — the '
                '2026-09-23 stack-wide finding, in a check',
            },
            {'check': 'identity_cosine_house', 'ref': REF, 'min': T_FRONTAL, 'angle': 'frontal'},
        ],
        cond=_cond(
            ab={
                'on': "the row's adapter at its production weight",
                'off': 'the same workflow with the adapter node bypassed, same seed, same prompt',
            }
        ),
        state_rule=dict(RULE_STRICT),
        run_order=1,
        state_note='RUNS FIRST and strictly: 3/3 seeds must differ. If this probe is a no, every other column '
        'on the row is measuring a bare checkpoint and the run should stop rather than fill a sheet '
        'with numbers about nothing.',
    ),
    {
        'id': 'id_gate_bites',
        'title': 'The gate rejects what it is supposed to reject',
        'feeds': ['never_applied'],
        'inputs': {
            'fixture': TILES_BAD,
            'note': 'six fixed tiles: the two-half-people slice that scored 0.44, a tile with two faces, '
            'a tile whose face is cut by the edge, a frontal face on a "back of head" label, a '
            'tile rotated 90 degrees, and one clean control tile',
        },
        'conditions': {'repeats': 1, 'note': 'a pure function of the tile — one call each, no seed, no GPU sampler'},
        'checks': [
            {
                'check': 'idqc_verdict_in',
                'expect': ['fail', 'multi_face', 'face_cut', 'mislabeled_angle', 'bad_orientation'],
                'note': 'FAIL_CLASS in identity_qc_service.py. The five corrupt tiles must land in it',
            },
            {
                'check': 'idqc_verdict_in',
                'expect': ['pass'],
                'tile': 'the clean control tile',
                'note': 'and the clean tile must NOT — a gate that rejects everything is as useless as one '
                'that rejects nothing',
            },
        ],
        'grade': 'measured',
        'state_rule': dict(RULE_STRICT),
        'run_order': 2,
        'state_note': 'This is `never_applied` for the arcface row: an instrument that passes a corrupt tile is '
        'a lever that is not connected. On a generator row it runs too and is the receipt that the '
        'gate scoring the other probes was working on the day of the run.',
    },
    # ── a high score is not a sane picture ──
    _p(
        'id_content_truth',
        'Among the stills the cosine PASSED, how many are sane pictures',
        ['content_truth'],
        SIX,
        [
            {
                'check': 'idqc_verdict_in',
                'expect': ['pass'],
                'note': "the content-truth layer on the row's own renders: multi_face, face_cut, mislabeled_angle "
                'and bad_orientation are all failures of the picture, whatever the cosine said',
            },
            {'check': 'operator', 'question': OP_SANE},
        ],
        run_order=10,
        state_note='SAME RENDERS as id_same_face, scored on a different question, so the two rates can be read '
        'against each other: the gap between them IS this column. A row whose cosine rate is high '
        'and whose sanity rate is low is the two-half-people failure repeating.',
    ),
    {
        'id': 'id_ct_tiles',
        'title': 'The known corrupt tiles must not score as sane',
        'feeds': ['content_truth'],
        'inputs': {
            'fixture': TILES_BAD,
            'note': 'the same six tiles as id_gate_bites, judged here on sanity rather than on the verdict',
        },
        'conditions': {'repeats': 1, 'note': 'fixed tiles, one pass each'},
        'checks': [
            {'check': 'operator', 'question': OP_SANE},
            {
                'check': 'identity_cosine_house',
                'ref': REF,
                'min': T_FRONTAL,
                'angle': 'frontal',
                'note': 'RECORDED, NOT SCORED as a pass: the receipt is that the two-half-people tile scores '
                '0.44 and would clear a 0.42 gate. The trial keeps the number so the sheet can show '
                'the operator saying no where the cosine said yes',
            },
        ],
        'grade': 'measured',
        'run_order': 2,
        'state_note': 'The purpose of this probe is to keep the 2026 receipt reproducible: the cell that says '
        '"a high score means the tile is sane" must be answered by the operator on tiles we already '
        'know are not sane.',
    },
]

# ── rows ───────────────────────────────────────────────────────────────────────────────────
QC_ONLY = (
    'identity_qc_service is the INSTRUMENT this whole sheet is scored with, not a generator: it takes a '
    'finished tile and an anchor and returns a cosine and a verdict. It renders nothing, so this column '
    "has no picture of its own to be about. The service's angle-aware gate (frontal 0.465 / oblique "
    '0.317 / profile 0.206 / fullbody 0.18) is the receipt that covers the angle questions.'
)
QC_BANDS = (
    'This row renders nothing and takes no prompt: it is called as a function on a tile. A band about '
    'what a picture contains, or about how a prompt is written, has nothing to measure here.'
)

TEST = {
    'step': 'identity',
    'version': '2026-09-30.1',
    'title': 'One child, one reference, the house gate at its own thresholds',
    'purpose': (
        'Settle the adapter-versus-adapter bench the sheet says has never been run: four identity '
        'paths and the QC service, measured on ONE reference picture of Abel with '
        "identity_qc_service's own calibrated cosine gates, every cosine paired with the blind "
        'operator because a high score has already been shown not to mean a sane picture.'
    ),
    'include_shared': 'image',
    'rows': {
        'instantid': {
            'transport': 'comfy',
            'model': 'InstantID (SDXL)',
            'where': '_comfy_workflows/sdxl_character_instantid.json',
            'note': 'models.json 2007, in_use, 4 GB. The de-facto reference only because the Ledger '
            'work measured against it — this test is what replaces that assumption',
        },
        'pulid': {
            'transport': 'comfy',
            'model': 'PuLID-FLUX',
            'where': '_comfy_workflows/flux_pulid_cell.json',
            'note': 'models.json 2006, in_use, 3 GB',
            'budget': {
                'minutes': 200,
                'gpu_minutes': 195,
                'note': 'FLUX sampling is roughly 2x SDXL per still at 1024 square, so the same '
                '753 renders cost about 200 minutes on this row rather than 155',
            },
        },
        'ipadapter': {
            'transport': 'comfy',
            'model': 'XLabs IP-Adapter for FLUX',
            'where': '_comfy_workflows/flux_character_ipadapter.json',
            'budget': {
                'minutes': 200,
                'gpu_minutes': 195,
                'note': 'FLUX again: the same render count at roughly twice the SDXL cost per '
                'still, so about 200 minutes of wall clock for this row',
            },
        },
        'lora_char': {
            'transport': 'comfy',
            'model': 'a zygchar_*.safetensors character LoRA on SDXL',
            'where': '_comfy_workflows/sdxl_txt2img.json + the character LoRA at its production weight',
            'na': {
                'ref_count': 'A trained character LoRA takes no reference picture at render time '
                'at all — the references were the training set. The ladder has no '
                'rung to move on this row; dataset_size on the lora_train sheet is '
                'the column that asks this question of a LoRA.',
                'ref_quality': 'Same reason: there is no reference at render time to degrade. '
                'A blurred training image is a lora_train dataset_quality question.',
            },
            'note': 'the row the 2026-09-23 convert_lora.py finding lands hardest on: every likeness '
            'claim recorded for a ComfyUI LoRA before that date has to be re-run, not re-read. '
            'id_ab_adapter runs first here on purpose',
        },
        'arcface': {
            'transport': 'service',
            'model': 'identity_qc_service.score_tile (AuraFace/glintr100 via the ComfyUI venv, ZYG_IDQC_PACK=auraface)',
            'where': 'identity_qc_service.py',
            'na_bands': {
                'reason': QC_BANDS,
                'bands': [
                    'Capacity',
                    'Space & relation',
                    'Attributes',
                    'Prompt: damage',
                    'Prompt: clarity needed',
                    'Prompt: limits',
                    'Prompt: steering',
                ],
            },
            'na': {
                'same_face': QC_ONLY,
                'angles': QC_ONLY,
                'profile': QC_ONLY,
                'back': QC_ONLY,
                'child_face': QC_ONLY,
                'age_lock': QC_ONLY,
                'expression_free': QC_ONLY,
                'style_transfer': QC_ONLY,
                'two_people': QC_ONLY,
                'ref_count': QC_ONLY,
                'ref_quality': QC_ONLY,
                'stack': QC_ONLY,
                'control_stack': QC_ONLY,
                'quality_cost': QC_ONLY,
                'drift_long': QC_ONLY,
            },
            'budget': {
                'calls': 12,
                'minutes': 4,
                'gpu_minutes': 2,
                'operator_minutes': 6,
                'note': '12 fixture-tile calls (id_gate_bites and id_ct_tiles, six tiles each), '
                'no sampler: the insightface subprocess holds the GPU for about 2 minutes '
                'of model load and inference. 12 blind sanity decisions at 30 s = 6 min.',
            },
            'note': 'the instrument, kept as a row so the sheet carries its receipt: measured_against, '
            'content_truth and never_applied are real capabilities OF A GATE',
        },
    },
    'probes': PROBES,
    'derive': {
        'measured_against': {
            'from': (
                "the run's own manifest: every trial records the sha256 of the reference image it was "
                'given. yes when one digest covers every trial of every row and it is the digest of '
                + REF
                + '; partial when the rows used different references (the sheet is then not an '
                'adapter comparison); no when a trial recorded no reference at all. The arcface row '
                'records the anchor digest it scored against, which must be the same file.'
            ),
            'grade': 'receipt',
            'unit': 'sha256',
            'note': 'This column is a receipt, not a picture: it asks whether a reference EXISTS and is the '
            "SAME one everywhere, which is exactly what the sheet's limitation says was missing. "
            'Whether that reference is really Abel is the fixture verification below, and it blocks '
            'this column until someone checks it.',
        },
    },
    'lookup': {},
    'wiring': {},
    'na': {},
    'fixtures': [
        {
            'path': REF,
            'verified': False,
            'generated': (
                "python3 -c \"import contact_sheet_pipeline as C; C.export_reference(character='abel', "
                "angle=0, out='capability_tests/fixtures/image/identity/abel_ref.png')\" — the frontal "
                'head-and-shoulders cell of the APPROVED Abel contact sheet, cropped square to 1024 and '
                'saved without metadata'
            ),
            'blocks': [
                'same_face',
                'measured_against',
                'angles',
                'profile',
                'child_face',
                'expression_free',
                'style_transfer',
                'two_people',
                'ref_count',
                'ref_quality',
                'stack',
                'control_stack',
                'drift_long',
            ],
            'how_to_verify': (
                'The operator opens abel_ref.png beside the approved Abel character-bible sheet and '
                'answers three questions in writing: (1) is this the same child as the bible, (2) is '
                'he about nine in it, (3) is it a clean single frontal face with nothing cut off. '
                'Then sets verified: True and records the date and the sha256 here. Until then every '
                'cosine column is written untested "key unverified": we do not grade four adapters '
                'against a reference nobody has looked at.'
            ),
        },
        {
            'path': REF_BLUR,
            'verified': False,
            'generated': (
                'python3 -c "from PIL import Image, ImageFilter; '
                "Image.open('capability_tests/fixtures/image/identity/abel_ref.png')"
                '.filter(ImageFilter.GaussianBlur(6)).save('
                "'capability_tests/fixtures/image/identity/abel_ref_blur.png')\" — radius 6 on the 1024 "
                'square, which is about the sharpness of a phone snapshot of a printed sheet'
            ),
            'blocks': ['ref_quality'],
            'how_to_verify': 'Derived from abel_ref.png: it is verified when its source is, plus a look that the '
            'face is still recognisable to a human at all (an unrecognisable blur would measure '
            'nothing).',
        },
        {
            'path': REF_ANNA,
            'verified': False,
            'generated': (
                "python3 -c \"import contact_sheet_pipeline as C; C.export_reference(character='anna', "
                "angle=0, out='capability_tests/fixtures/image/identity/anna_ref.png')\" — the frontal "
                'cell of the approved Anna sheet, same crop and size as abel_ref.png'
            ),
            'blocks': ['two_people'],
            'how_to_verify': 'Same three written questions as abel_ref.png, asked of the Anna bible, plus one more: '
            'is she unmistakably a different person from Abel (a pair test on two references that '
            'look alike measures nothing).',
        },
        {
            'path': REF_SET[1],
            'verified': False,
            'blocks': ['ref_count'],
            'generated': 'the 45-degree left cell of the same approved Abel sheet, exported the same way',
            'how_to_verify': 'as abel_ref.png, with "is he turned about 45 degrees" instead of "is it frontal".',
        },
        {
            'path': REF_SET[2],
            'verified': False,
            'blocks': ['ref_count'],
            'generated': 'the 45-degree right cell of the same approved Abel sheet, exported the same way',
            'how_to_verify': 'as abel_ref.png, with "is he turned about 45 degrees" instead of "is it frontal".',
        },
        {
            'path': REF_SET[3],
            'verified': False,
            'blocks': ['ref_count'],
            'generated': 'the three-quarter down-lit cell of the same approved Abel sheet, exported the same way',
            'how_to_verify': 'as abel_ref.png; this rung exists to test whether a fourth reference adds anything.',
        },
        {
            'path': TILES_BAD,
            'verified': False,
            'generated': (
                'python3 scripts/build_identity_ct_tiles.py — six 1024 tiles assembled from tiles the '
                '2026-07-16 contact-sheet audit already rejected: the misaligned grid slice with two '
                'half-people (cosine 0.44), a two-face tile, an edge-cut face, a frontal face saved on a '
                '"back of head" label, a 90-degree-rotated portrait, and one clean frontal control tile. '
                'The script copies and crops existing rejected tiles; it generates no new pixels'
            ),
            'blocks': [],
            'how_to_verify': (
                'The operator confirms in writing, tile by tile, which defect each one carries and '
                'that the control tile has none. NOT LISTED AS BLOCKING: content_truth and '
                'never_applied are answered by the operator looking at these tiles and by the '
                "service's verdict on them, so the answer is produced at run time rather than read "
                'from a key. What verification adds here is the guarantee that the set still holds '
                'one of each defect.'
            ),
        },
        {
            'path': DEPTH_MAP,
            'verified': False,
            'blocks': ['control_stack'],
            'generated': (
                'python3 -m zyg_workflows.geom.conditioning <mannequin pass set dir> -o '
                'capability_tests/fixtures/image/identity/ then rename depth.png to mannequin_depth.png '
                '— the SAME mannequin plate the controlnet sheet uses, so the two sheets can be read '
                'together. Rendered depth, not an estimate: no Depth-Anything checkpoint is involved'
            ),
            'how_to_verify': 'The operator confirms the plate shows one standing figure, near = white, the whole '
            'body inside the frame, and that it is the same file path the controlnet test names.',
        },
    ],
    'budget': {
        'calls': 753,
        'tokens_in': 0,
        'tokens_out': 0,
        'tokens_note': 'No language model is called anywhere in this test: every row is a ComfyUI workflow or a '
        'python function on a tile, and the prompts are fixed strings this file stores, not '
        'anything a model is asked to write.',
        'minutes': 155,
        'gpu_minutes': 150,
        'operator_minutes': 90,
        'note': (
            '111 domain renders per row: same_face 6x3=18, angles 2x3=6, profile 2x3=6, back 2x3=6, child 3, '
            'age_lock 3x3=9, expression 3x3=9, style 3, two_people 3, ref_count 3 rungs x3=9, ref_quality 3, '
            'stack 3, control_stack 3, quality_cost A/B 2x3=6 (the two off-renders are shared with '
            'id_ab_adapter), drift_long 24x1=24, ab_adapter A/B 2x3=6 — content_truth adds none, it rescores '
            'the same_face renders, and the two fixture probes are 12 service calls with no sampler. '
            'THE SHARED IMAGE BANK IS THE BULK: 214 probes x 3 seeds = 642 renders per row, which is where '
            '85 % of this number lives. 753 renders at about 12 s of SDXL sampling = 150 GPU minutes, plus '
            'about 5 minutes of adapter and checkpoint loading = 155 wall. Operator: 129 domain blind '
            'decisions (18 same_face + 18 content_truth + 24 drift + 9 expression + 9 ref_count + 9 age_lock '
            "+ 6 angles + 6 profile + 6 back + 6 quality_cost + 12 tiles + 6 the rest) plus the bank's own "
            'share, at 30 s each = about 90 minutes. No Claude or API meter is touched by this test.'
        ),
    },
    'run_order': [
        'id_ab_adapter',
        'id_gate_bites',
        'id_ct_tiles',
        'id_same_face',
        'id_content_truth',
        'id_angles',
        'id_profile',
        'id_back',
        'id_child',
        'id_age_lock',
        'id_expression',
        'id_style',
        'id_two_people',
        'id_ref_count',
        'id_ref_quality',
        'id_stack',
        'id_control_stack',
        'id_quality_cost',
        'id_drift_long',
        'the shared image bank last',
    ],
    'notes': [
        'RUN ORDER IS LOAD-BEARING. id_ab_adapter and the two fixture probes are cheap and mechanical and they '
        'decide whether the rest is worth running: if the adapter is a no-op or the gate does not bite, every '
        'later number is about a bare checkpoint. The 642-render shared bank goes last, so a partial run still '
        'fills the eighteen columns this sheet exists for.',
        "Every threshold in this file is identity_qc_service.py's, not this test's. If the service is "
        'recalibrated, this test changes hash and the old sheets must not be read beside the new ones — which '
        'is the point of the hash.',
        'No local VLM judges anything here. The 2026-09-27 defect bench measured the best local model at 34/40 '
        'on a global question and 2/8 on the hard cases, and "is this the same child" is a hard case. Where a '
        'human decides, the question is written above word for word so the same question can be asked of the '
        'next adapter in a year.',
        'Identity on video is NOT this sheet. Continuity in a clip comes from the pixels of the previous frame, '
        'not from a reference spread, and an adapter that scores well on six stills says nothing about it.',
    ],
}
