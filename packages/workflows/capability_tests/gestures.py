# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Default test — Gestures & hands (gestures). 2026-09-30.

Question the sheet asks: "Can we direct the hands, and can we tell when they came out wrong?"
Two questions, and the sheet's own verdict already answers the second one badly:

    "Directing hands is untested; DETECTING bad hands is measured, and the measurement says
     landmark geometry cannot do it — MediaPipe fits its 21-landmark topology onto any hand,
     so every known-bad hand scored clean."

That receipt is the spine of this test. On run 6278904c the hand gate returned 1.00 on twelve
defective frames because every call to the removed `mp.solutions` API raised and a blanket
`except` swallowed it; landmark-geometry scoring was then evaluated for the rebuild and
REJECTED for the same reason on its merits (hand_qc_service.py, anatomy_qc.py docstrings).
So the checking half of this test is built to REPRODUCE that failure if it is still there:
`bad_hand_recall` on ten known-bad hands is the column that matters, a gate that passes
everything scores 0.00 on it, and `good_hand_specificity` beside it stops a row buying recall
by failing every hand it sees.

The directing half is eight named gestures, one verbatim brief each, run through the two rows
that can be asked for a hand — the char2d gesture bench (authored Euler angles on the MPFB rig)
and the movement_studio `_HANDS` prompt table. For prompt_hands the renderer is HELD FIXED and
named in the manifest: the only thing that varies is the `_HANDS` value, so a `no` means the
clause does not move the renderer, not that the renderer cannot make a hand.

HONEST JUDGING (the standing rule). No local VLM and no landmark score decides whether a hand
is right; the operator checks BY EYE before any tree consumes a gesture
([[project_ledger_permanent_route]]). Every directing probe therefore carries a blind operator
question AND the mechanical detector, and the `state_note` says the operator decides. MediaPipe
is used only where it measures something that is NOT the template: how many hands were found,
and whether two hands stayed two ([[project_hand_phalanx_correction]]).

WHAT IS BLOCKED. Neither fixture set exists. The 20 detection frames need operator-drawn hand
boxes and the 10 known-bad / 10 known-good hands need an operator-written defect label each;
until both are verified, `detects`, `judges`, `count_check`, `fused_check`, `joint_check` and
`lr_check` are written `untested — key unverified`.
"""

from __future__ import annotations

# Check kinds this step's runner must implement. Named for what is measured and against what.
CHECK_KINDS = {
    'finger_count_equals': 'MediaPipe hand_landmarker: the number of EXTENDED fingers on each detected hand — a finger counts as '
    'extended when the distance from the wrist landmark to its TIP exceeds the distance to its PIP by more '
    'than `extend_margin` (default 1.15) — equals `n`, in >= `share` of the trials',
    'hand_detect_recall': "the share of the fixture's operator-drawn hand boxes for which the row returns a box at IoU >= `iou` "
    '(default 0.5) is >= `min`; `max_false` caps the boxes returned in frames the fixture marks as having none',
    'bad_hand_recall': "the share of the fixture's KNOWN-BAD hands that the row marks defective (ok is False, not None) is "
    '>= `min` — the receipt this column exists for is that the gate on run 6278904c scored 0.00 here',
    'good_hand_specificity': "the share of the fixture's KNOWN-GOOD hands that the row marks clean is >= `min` — read only together "
    'with bad_hand_recall, because a row that rejects every hand is not a judge either',
    'defect_label_equals': 'for each fixture hand the defect the row NAMES (one of fused | extra_digit | missing_digit | '
    "reversed_joint | none, restricted to `labels` where set) equals the fixture's operator-written label, "
    'in >= `share` of the hands it marked defective',
    'handedness_correct': "the left/right label the row puts on each hand equals the fixture's operator-verified truth in "
    '>= `share` of the hands the row detected (undecided counts as wrong)',
}

FX = 'capability_tests/fixtures/gestures'
MANIFEST = FX + '/MANIFEST.json'
HANDS_SET = FX + '/hand_judgement_set'  # 10 known-bad + 10 known-good hands, labelled
FRAMES_SET = FX + '/detection_frames'  # 20 frames with operator-drawn hand boxes

# The eight named gestures, verbatim. `bench` names the authored char2d gesture file where one
# exists; `hands_value` names the movement_studio._HANDS key the prompt row is driven with.
GESTURES = {
    'g1_point_forward': {
        'brief': 'The character points straight ahead with the index finger of the right hand, arm extended at shoulder height, the other three fingers and the thumb folded into the palm. Left arm relaxed at the side.',
        'bench': 'data/char2d/gestures/03_point.json',
        'hands_value': 'gesturing',
    },
    'g2_grip_rope': {
        'brief': 'The character grips a thick rope in the right hand at chest height, all four fingers wrapped round it and the thumb closed over them. Left arm relaxed at the side.',
        'bench': 'data/char2d/gestures/10_beat_fist.json (adapted: fist closed round a prop)',
        'hands_value': 'holding something',
    },
    'g3_open_palm': {
        'brief': 'The character holds the right hand out towards the viewer at waist height, palm up and open, fingers together and slightly curved, thumb relaxed. Left arm relaxed at the side.',
        'bench': 'data/char2d/gestures/01_open_palm.json',
        'hands_value': 'open palms',
    },
    'g4_write_quill': {
        'brief': 'The character holds a quill between the thumb, index and middle finger of the right hand and writes on a sheet of paper on a table, the ring and little fingers curled back, the left hand flat on the paper holding it still.',
        'bench': 'to be authored: data/char2d/gestures/11_write_quill.json',
        'hands_value': 'holding something',
    },
    'g5_count_three': {
        'brief': 'The character holds the right hand up at shoulder height, palm towards the viewer, showing exactly three fingers — index, middle and ring extended, little finger and thumb folded down. Left arm relaxed at the side.',
        'bench': 'data/char2d/gestures/04_count.json',
        'hands_value': 'gesturing',
    },
    'g6_two_hand_different': {
        'brief': 'The character points ahead with the right index finger at shoulder height while the left hand is held out to the side at waist height, palm up and open. The two hands are doing different things at the same time.',
        'bench': 'to be authored: data/char2d/gestures/12_two_hand_split.json',
        'hands_value': 'gesturing',
    },
    'g7_hand_to_cheek': {
        'brief': 'The character rests the open right hand against the right cheek, fingers together and pointing up towards the temple, the palm touching the face. Left arm relaxed at the side.',
        'bench': 'data/char2d/gestures/08_hand_to_chest.json (adapted: contact moved to the cheek)',
        'hands_value': 'gesturing',
    },
    'g8_fist_beat': {
        'brief': 'The character brings the closed right fist down onto a table top, all four fingers curled into the palm and the thumb across them. Left arm relaxed at the side.',
        'bench': 'data/char2d/gestures/10_beat_fist.json',
        'hands_value': 'clenched',
    },
}

COND = {
    'repeats': 3,
    'seeds': [11, 12, 13],
    'resolution': '1024x1024',
    'note': 'three seeds per gesture; a hand that only lands on one seed is a partial. The checking rows are deterministic and their three repeats measure the tool, not the seed.',
}
COND_JUDGE = {
    'repeats': 3,
    'seeds': [0, 0, 0],
    'resolution': "the fixture's own",
    'note': 'the judging rows are run three times on the identical fixture set: a gate whose verdict moves between runs on the same pixels is reporting noise, and identical_clips beside the recall figure is what shows it.',
}

MAKE = ['prompt_hands', 'gesture_bench']  # the rows that can be ASKED for a hand
JUDGE = ['mediapipe_hand']  # the rows that can JUDGE one

FIVE = {
    'check': 'hand_landmarks_count',
    'hands': 1,
    'fingers': 5,
    'share': 0.8,
    'note': 'a floor, never a pass: MediaPipe fits its 21-landmark template onto any hand, so this only proves a hand-shaped thing is there',
}
HARD = {'yes': 1.0, 'partial': 0.6}  # one gesture x 3 seeds: yes only at 3/3


def _g(pid, title, feeds, gid, checks, rows, **kw):
    p = {
        'id': pid,
        'title': title,
        'feeds': list(feeds),
        'inputs': {'prompt': GESTURES[gid]['brief'], 'fixture': MANIFEST + '#' + gid},
        'conditions': dict(COND),
        'checks': list(checks),
        'grade': 'measured',
        'rows': list(rows),
        'gesture': gid,
        'bench_file': GESTURES[gid]['bench'],
        'hands_value': GESTURES[gid]['hands_value'],
    }
    p.update(kw)
    return p


def _j(pid, title, feeds, fixture, checks, **kw):
    p = {
        'id': pid,
        'title': title,
        'feeds': list(feeds),
        'inputs': {'fixture': fixture, 'prompt': None},
        'conditions': dict(COND_JUDGE),
        'checks': list(checks),
        'grade': 'measured',
        'rows': list(JUDGE),
    }
    p.update(kw)
    return p


PROBES = [
    # ── Directing ────────────────────────────────────────────────────────────────────
    _g(
        'gp_directed',
        'All eight named gestures',
        ['directed'],
        'g1_point_forward',
        [
            {
                'check': 'operator',
                'blind': True,
                'question': 'Here is the brief that was given and here is what came out. Is the hand doing what the brief describes — the named fingers in the named places, the right hand and not the left? yes/no',
            },
            dict(FIVE),
        ],
        MAKE,
        pack=list(GESTURES),
        state_note=(
            'eight gestures x 3 seeds = 24 trials per row, default state rule. The OPERATOR decides; '
            'hand_landmarks_count only proves a hand was found. This is the column the sheet currently '
            'calls "untested" and it is the first thing a run fills.'
        ),
    ),
    _g(
        'gp_point',
        'Pointing',
        ['point'],
        'g1_point_forward',
        [
            {'check': 'finger_count_equals', 'n': 1, 'share': 0.8},
            {
                'check': 'operator',
                'blind': True,
                'question': 'Is exactly ONE finger extended, is it the index finger, and is it on the right hand? yes/no',
            },
        ],
        MAKE,
        state_rule=dict(HARD),
    ),
    _g(
        'gp_grip',
        'Gripping an object',
        ['grip'],
        'g2_grip_rope',
        [
            {
                'check': 'finger_count_equals',
                'n': 0,
                'share': 0.8,
                'note': 'a closed grip extends no finger; a hand reported with extended fingers is not gripping',
            },
            {
                'check': 'operator',
                'blind': True,
                'question': 'Do the fingers CLOSE ROUND the rope — wrapped, with the thumb over them — rather than the rope passing through the hand or the hand hovering beside it? yes/no',
            },
        ],
        MAKE,
        state_rule=dict(HARD),
        state_note='the contact question is the whole point and no detector answers it: a hand that intersects the prop scores clean on every landmark test there is.',
    ),
    _g(
        'gp_open_palm',
        'Open palm',
        ['open_palm'],
        'g3_open_palm',
        [
            {'check': 'finger_count_equals', 'n': 5, 'share': 0.8},
            {
                'check': 'operator',
                'blind': True,
                'question': 'Is the palm turned UP and open towards the viewer, with all five digits present, none fused and none extra? yes/no',
            },
        ],
        MAKE,
        state_rule=dict(HARD),
    ),
    _g(
        'gp_write',
        'Writing or drawing',
        ['write'],
        'g4_write_quill',
        [
            {'check': 'hand_landmarks_count', 'hands': 2, 'fingers': 5, 'share': 0.8},
            {
                'check': 'operator',
                'blind': True,
                'question': 'Is the quill held in a writing grip — between thumb, index and middle finger, nib on the paper — rather than clenched in a fist or floating? yes/no',
            },
        ],
        MAKE,
        state_rule=dict(HARD),
        state_note='the hardest of the eight: a tool grip needs three named digits in three named places and a contact point, and no mechanical check on this box measures any of them.',
    ),
    _g(
        'gp_count_fingers',
        'Showing a number of fingers',
        ['count_fingers'],
        'g5_count_three',
        [
            {'check': 'finger_count_equals', 'n': 3, 'share': 0.8},
            {
                'check': 'operator',
                'blind': True,
                'question': 'Count the extended fingers. Is it exactly three, and are they the index, middle and ring? yes/no',
            },
        ],
        MAKE,
        state_rule=dict(HARD),
        state_note=(
            'this step CLAIMS the column back from the shared video bank, which answers it with a generic counting '
            'scene. The honest warning is written here: finger_count_equals reads the landmark template, and the '
            'template has five fingers whatever the picture shows (hand_qc_service.py, 2026-07-24). The operator '
            'decides; a disagreement between the two is the finding, and it goes in the cell note.'
        ),
    ),
    _g(
        'gp_two_hand',
        'Two hands doing different things',
        ['two_hand'],
        'g6_two_hand_different',
        [
            {'check': 'hand_landmarks_count', 'hands': 2, 'fingers': 5, 'share': 0.8},
            {
                'check': 'mask_iou_max',
                'n': 2,
                'max': 0.05,
                'share': 0.9,
                'note': 'the two hand masks must not overlap: a single blob fitted twice is the merging failure',
            },
            {
                'check': 'operator',
                'blind': True,
                'question': 'Is the RIGHT hand pointing ahead and the LEFT hand open and palm up at the same moment — two different actions, not the same one mirrored? yes/no',
            },
        ],
        MAKE,
        state_rule=dict(HARD),
    ),
    _g(
        'gp_hand_to_face',
        'Hand to face without merging',
        ['hand_to_face'],
        'g7_hand_to_cheek',
        [
            {
                'check': 'hand_landmarks_count',
                'hands': 2,
                'fingers': 5,
                'share': 0.8,
                'note': 'both hands must still resolve with 21 landmarks each while one of them is against the face',
            },
            {'check': 'mask_iou_max', 'n': 2, 'max': 0.05, 'share': 0.9},
            {
                'check': 'operator',
                'blind': True,
                'question': 'Where the hand touches the cheek, is there a clear edge between hand and face — rather than the fingers melting into the skin or a finger passing through the jaw? yes/no',
            },
        ],
        MAKE,
        state_rule=dict(HARD),
        state_note="the classic contact failure. anatomy_qc's strict pass must find the hand in the same region as the permissive one, or the result is None (unknown) and None is never clean.",
    ),
    # ── Checking ─────────────────────────────────────────────────────────────────────
    _j(
        'gp_detects',
        'Finds the hands in the frame',
        ['detects'],
        FRAMES_SET,
        [
            {'check': 'hand_detect_recall', 'iou': 0.5, 'min': 0.9, 'max_false': 2},
            {'check': 'identical_runs', 'note': 'the same 20 frames three times must return the same boxes'},
        ],
        state_note=(
            '20 fixture frames with operator-drawn boxes, spanning the measured hard range: whole-frame renders at '
            '1664x960 where anatomy_qc reports 0 detections at 0.5 confidence and 2 at 0.2, head-sized crops where '
            'it resolves immediately, and stylised Arcane cells the photoreal detector was never trained on. '
            'Recall is reported per bucket as well as overall, because one number over those three hides the answer.'
        ),
    ),
    _j(
        'gp_judges',
        'Tells a good hand from a bad one',
        ['judges'],
        HANDS_SET,
        [
            {'check': 'bad_hand_recall', 'min': 0.8},
            {'check': 'good_hand_specificity', 'min': 0.8},
            {
                'check': 'operator',
                'blind': True,
                'question': "Here is one hand and the gate's verdict on it, with the model hidden. Ignoring the verdict, is this hand anatomically possible — five digits, joints bending the right way, no fusing? Then: did the gate agree with you? yes/no",
            },
        ],
        state_rule={'yes': 0.8, 'partial': 0.4},
        state_note=(
            'THE column of this sheet. The standing receipt is bad_hand_recall = 0.00 on run 6278904c: every one of '
            'twelve known-bad hands scored 1.00 clean, first because the removed mp.solutions API raised into a '
            'blanket except, and second because landmark geometry fits the template onto anything. anatomy_qc was '
            'built to score the fit RESIDUAL instead — degenerate fingertip clusters, reversed joint chains, '
            'bone-length ratios outside human range, undecidable handedness — and this probe is the first '
            'measurement of whether that worked. A row cannot pass on recall alone: specificity is in the same '
            'probe so that "everything is bad" is not a strategy.'
        ),
    ),
    _j(
        'gp_count_check',
        'Counts digits correctly',
        ['count_check'],
        HANDS_SET,
        [
            {'check': 'defect_label_equals', 'labels': ['extra_digit', 'missing_digit', 'none'], 'share': 0.8},
            {
                'check': 'finger_count_equals',
                'n': 'fixture.digits',
                'share': 0.8,
                'note': "n is read per hand from the fixture's operator-written digit count, not fixed at five",
            },
        ],
        state_note='the fixture set is built with a known digit count per hand, including two six-fingered and two four-fingered hands, so a template that always answers five is visible as a flat 0.6 rather than as a pass.',
    ),
    _j(
        'gp_fused_check',
        'Spots fused fingers',
        ['fused_check'],
        HANDS_SET,
        [
            {'check': 'defect_label_equals', 'labels': ['fused', 'none'], 'share': 0.8},
            {'check': 'bad_hand_recall', 'min': 0.8, 'subset': 'fused'},
        ],
        state_note='the hard case on the 2026-09-27 defect bench: the best local judge scored 2 of 8 on fused fingers. Any row above 0.5 here is a genuine result and must be re-measured before it is believed.',
    ),
    _j(
        'gp_joint_check',
        'Spots backwards joints',
        ['joint_check'],
        HANDS_SET,
        [
            {'check': 'defect_label_equals', 'labels': ['reversed_joint', 'none'], 'share': 0.8},
            {'check': 'bad_hand_recall', 'min': 0.8, 'subset': 'reversed_joint'},
        ],
        state_note='reversed joint chains are the one defect anatomy_qc claims to measure from the fit residual rather than from the template, so this is the probe that tests its central claim.',
    ),
    _j(
        'gp_lr_check',
        'Tells left hand from right',
        ['lr_check'],
        HANDS_SET,
        [{'check': 'handedness_correct', 'share': 0.9}],
        state_note='anatomy_qc calls undecidable handedness its STRONGEST defect signal, so this column is read twice: as an accuracy figure, and as the input to gp_judges. Undecided counts as wrong here and as a defect flag there.',
    ),
]

NA_PROMPT = {
    'point': 'movement_studio._HANDS holds six values — relaxed at the sides, gesturing, clenched, open palms, holding something, hidden from view — and none of them names a finger; pointing cannot be requested through this lever at all',
    'write': 'no _HANDS value describes a tool grip; "holding something" is the nearest and it says nothing about which digits hold it or where the nib goes',
    'count_fingers': 'a number of fingers cannot be asked for through a six-value enumeration; the clause table has no count in it anywhere',
    'two_hand': 'the _HANDS clause is one phrase for BOTH hands ("hands gesturing"); the vocabulary cannot give the two hands different jobs',
    'hand_to_face': 'no _HANDS value places a hand anywhere on the body; contact with the face is outside what this table can say',
    'detects': 'this row is a prompt-clause table; it looks at no pixels and finds nothing',
    'judges': 'a phrase generator returns no verdict about a hand and never sees one',
    'count_check': 'nothing here counts anything: the row emits a clause and stops',
    'fused_check': 'nothing here inspects a rendered hand, so a fused finger is invisible to it',
    'joint_check': 'nothing here inspects a rendered hand, so a reversed joint is invisible to it',
    'lr_check': 'the clause table does not distinguish the two hands at all, so it cannot label one of them',
    'repair_loop': 'repair runs on pixels; a clause table has nothing to repair and is not in that path',
}
NA_BENCH = {
    'detects': 'the char2d bench AUTHORS a pose and renders it; it runs no detector and returns no boxes',
    'judges': "the bench ships the render with its authored angles; the verdict on the result is anatomy_qc's job and the operator's",
    'count_check': 'the bench knows how many digits it posed because it posed them; counting its own rig is not a measurement of a picture',
    'fused_check': 'no defect detector runs in the char2d path; the anatomy_qc gate is a separate stage downstream',
    'joint_check': 'char2d_poses REFUSES an angle outside the measured ROM instead of detecting one afterwards — prevention, which is not what this column asks',
    'lr_check': 'left and right are authored explicitly in the gesture file and never mirrored (char2d_poses.py docstring), so the row is told which hand it is and cannot be measured on telling',
    'repair_loop': 'a bad char2d pose is fixed by editing the gesture JSON and re-rendering; the HandFixer inpaint loop is not wired to this row',
}
NA_MPHAND = {
    'directed': 'anatomy_qc reads a hand; it never makes one, so there is nothing to direct',
    'point': 'a detector cannot be asked for a pointing finger',
    'grip': 'a detector cannot be asked for a grip',
    'open_palm': 'a detector cannot be asked for an open palm',
    'write': 'a detector cannot be asked for a writing grip',
    'two_hand': 'a detector cannot be asked to give the two hands different jobs',
    'hand_to_face': 'a detector cannot be asked to place a hand on a face',
    'repair_loop': 'anatomy_qc is the gate in front of the repair, not the repair; detect_hand_boxes_strict RAISES so the caller skips rather than inpaints blind',
}

TEST = {
    'step': 'gestures',
    'version': '2026-09-30.1',
    'title': 'Eight named gestures, and the known-bad hand set the old gate passed',
    'purpose': 'Measure whether a hand can be directed at all, and whether any row on this box can tell a bad hand from a good one — against a set whose defects the operator wrote down first.',
    'include_shared': 'video',
    'gestures': GESTURES,
    'rows': {
        'prompt_hands': {
            'transport': 'service',
            'where': 'movement_studio.py — the _HANDS clause table (6 values) through _clauses(), with the renderer HELD FIXED and named in MANIFEST.renderer',
            'na': NA_PROMPT,
            'budget': {
                'calls': 12,
                'minutes': 14,
                'gpu_minutes': 12,
                'operator_minutes': 6,
                'note': 'only 4 of the 8 gestures are expressible as an _HANDS value (g1/g3/g5/g6 collapse onto "gesturing" and "open palms"); 4 x 3 seeds = 12 renders through the fixed renderer at ~60 s each.',
            },
            'state_note': 'this row measures the PROMPT LEVER, not the renderer. The renderer is identical across the three seeds and across the four expressible values; a `no` means the clause did not move it.',
        },
        'gesture_bench': {
            'transport': 'service',
            'where': 'char2d_poses.py + blender_scripts/char2d_render_pose.py — the authored gesture bench at output/char2d/_gesture_bench (11 gestures + 00_idle, apex_sheet.png)',
            'na': NA_BENCH,
            'budget': {
                'calls': 24,
                'minutes': 12,
                'gpu_minutes': 0,
                'operator_minutes': 12,
                'note': '8 gestures x 3 seeds = 24 headless Blender renders at ~25 s plus a ~15 s startup amortised over the batch; CPU only (Freestyle + EEVEE software path), no GPU held.',
            },
            'state_note': 'two of the eight gestures do not exist yet and must be authored first (g4_write_quill, g6_two_hand_split); the ROM validator refuses any angle outside the measured joint limits, so authoring them is itself part of the result.',
        },
        'mediapipe_hand': {
            'transport': 'service',
            'where': 'anatomy_qc.py — MediaPipe hand_landmarker (Apache-2.0), qc_hands_frame + detect_hand_boxes_strict, two-pass permissive/strict with tiled escalation',
            'na': NA_MPHAND,
            'budget': {
                'calls': 120,
                'minutes': 6,
                'gpu_minutes': 0,
                'operator_minutes': 20,
                'note': '(20 detection frames + 20 judgement hands) x 3 runs = 120 CPU calls at ~1 s each including the tiled escalation pass; zero VRAM by design.',
            },
            'state_note': 'tri-state contract: True = measured clean, False = measured defective, None = UNKNOWN. None is NEVER clean, and a run that returns None on the whole set scores 0.00 on bad_hand_recall rather than passing.',
        },
        'hand_yolo': {
            'transport': 'retired',
            'model': 'ADetailer hand_yolov8s via ultralytics',
            'skip': (
                'REPLACED 2026-07-30 by MediaPipe hand_landmarker in anatomy_qc. The ultralytics runtime is AGPL-3.0 and cannot ship in a '
                'commercial deliverable, so the whole hand path was moved to the Apache-2.0 MediaPipe bundle (hand_qc_service._select_backend, '
                'ZYG_HANDS_BACKEND). Kept for the licence receipt and because it is the count-only detector whose blind spot anatomy_qc was '
                'built to cover.'
            ),
        },
        'legacy_qc': {
            'transport': 'retired',
            'model': 'mediapipe mp.solutions.hands legacy API',
            'skip': (
                'REMOVED UPSTREAM in mediapipe 0.10.35 and deliberately kept as a row. Every call raised AttributeError, a blanket except '
                'returned a PERFECT 1.00, and run 6278904c shipped twelve defective frames at hand=1.00. A gate that returns 1.00 because '
                'every call throws is the worst failure mode on this tab, and deleting the row would delete the lesson — the sheet note says '
                'so in as many words (2026-07-24 HandFixer rebuild).'
            ),
        },
    },
    'probes': PROBES,
    'derive': {
        'speed': {
            'from': 'wall clock per gesture for the making rows, per hand for the judging row',
            'grade': 'measured',
            'unit': 's',
        },
        'throughput': {
            'from': 'hands judged per hour sustained (the judging row) and gestures rendered per hour (the making rows)',
            'grade': 'measured',
            'unit': 'count',
        },
        'deterministic': {
            'from': 'the three runs on the identical fixture set: same verdict per hand for the judging row (a moving verdict on fixed pixels is noise), same render hash for the authored bench',
            'grade': 'measured',
        },
        'first_take': {'from': 'share of probes whose FIRST seed passed, before any reroll', 'grade': 'measured'},
        'retries': {
            'from': 'seeds drawn until the first pass, over probes that eventually passed',
            'grade': 'measured',
            'unit': 'count',
        },
        'failsafe': {
            'from': 'detect_hand_boxes_strict RAISES by design and qc_hands_* never raises across the module boundary; the column is measured by feeding a corrupt image to each entry point and recording what came back',
            'grade': 'measured',
        },
        'silent_fail': {
            'from': 'the defining column of this step: share of the known-bad hands that passed the row WITHOUT any signal — the run 6278904c figure was 12 of 12',
            'grade': 'measured',
        },
        'receipts': {
            'from': 'the run leaves every hand crop, the boxes, the verdict, the named defect and the confidence thresholds used next to the fixture set',
            'grade': 'receipt',
        },
    },
    'lookup': {
        'repair_loop': {
            'requires': 'the HandFixer path on disk: _comfy_workflows/hand_fixer_qwen_inpaint.json, scripts/ensure_handfixer_ready.py and scripts/hand_fixer_regression.py, with hand_qc_service.detect_hand_boxes as its fail-closed entry gate',
            'grade': 'receipt',
            'note': (
                'A failed hand CAN be repaired: the HandFixer crops the detected box and re-inpaints it (Qwen inpaint workflow), and there is a '
                'standing regression script for it. The receipt that matters is the CONTRACT, not the existence: detect_hand_boxes is FAIL-CLOSED '
                'and raises, so a caller must SKIP the repair when detection is unavailable and must never inpaint blind. The honest cell is '
                '"yes, gated" — the loop exists and refuses to run when it cannot see.'
            ),
        },
    },
    'wiring': {
        'by_eye': {
            'from': (
                'read off the code path, not run. There is no line of code that enforces a human look: anatomy_qc returns a tri-state and '
                'hand_qc_service raises, but neither blocks a pipeline on an operator. The enforcement is the STANDING RULE — the operator '
                'checks hands by eye before any tree consumes a gesture ([[project_ledger_permanent_route]]) — and it lives in the ledger '
                'route, not in the code. The honest cell is therefore `assumed`: the practice is real and documented, the gate is not. '
                'Where the tri-state None is returned, the caller is REQUIRED to treat it as unknown and escalate, and that much is in the code.'
            ),
            'grade': 'assumed',
        },
    },
    'na': {},
    'fixtures': [
        {
            'path': HANDS_SET,
            'verified': False,
            'blocks': ['judges', 'count_check', 'fused_check', 'joint_check', 'lr_check'],
            'generated': (
                'pull the ten known-bad hands from the run 6278904c stills the ledger already holds — the twelve frames that shipped at '
                'hand=1.00 — and ten known-good hands from the same runs, crop each to a hand box, and write them into '
                'MANIFEST.judgement_set as {id, image, truth: good|bad, digits: <int>, defect: fused|extra_digit|missing_digit|reversed_joint|none, '
                'handedness: left|right}'
            ),
            'how_to_verify': (
                'the operator looks at each of the twenty crops, writes the digit count, the defect name and the handedness by eye, and sets '
                'verified = true. The ten bad ones must cover all four defect names, with at least two fused and two reversed_joint, or '
                'gp_fused_check and gp_joint_check have no subset to score. This set is the receipt for the whole sheet and nobody may '
                'grade a gate against a label they did not write themselves.'
            ),
        },
        {
            'path': FRAMES_SET,
            'verified': False,
            'blocks': ['detects'],
            'generated': (
                'collect 20 frames into MANIFEST.detection_frames in three buckets the measurement already names: 8 whole-frame renders at '
                '1664x960 (where anatomy_qc measured 0 detections at 0.5 confidence and 2 at 0.2), 6 head-and-hand-sized crops (where it '
                'resolves immediately), and 6 stylised Arcane cells; include 2 frames with NO hand in them for the max_false term'
            ),
            'how_to_verify': 'the operator draws a box round every hand in every frame into MANIFEST.detection_frames[<id>].boxes (x, y, w, h in original-image pixels), marks the two empty frames as boxes: [], and sets verified = true',
        },
        {
            'path': MANIFEST,
            'verified': False,
            'blocks': ['directed'],
            'generated': (
                'write the eight briefs above into MANIFEST.gestures verbatim with their bench file and _HANDS value, and pin the fixed renderer '
                '(checkpoint, workflow, resolution, steps, cfg, sampler, negative) into MANIFEST.renderer — prompt_hands is only a measurement of '
                'the PROMPT if the renderer never moves'
            ),
            'how_to_verify': 'the operator confirms the pinned renderer is the one production actually uses for this step, and that the two unauthored gesture files (g4, g6) have been written and pass the char2d_poses ROM validator, then sets verified = true',
        },
    ],
    'budget': {
        'calls': 24,
        'tokens_in': 0,
        'tokens_out': 0,
        'tokens_note': 'no language model is called on this step: a clause table concatenates strings, a rig takes Euler angles and a landmarker takes pixels',
        'minutes': 12,
        'gpu_minutes': 0,
        'operator_minutes': 12,
        'note': (
            'Per row: 8 gestures x 3 seeds = 24 directing trials, and 20 fixture hands + 20 detection frames x 3 runs = 120 judging calls. '
            'The default above is gesture_bench (24 headless Blender renders, ~25 s each, CPU, 12 min); prompt_hands overrides down to 12 '
            'renders but UP to 12 GPU minutes because it must go through the pinned renderer; mediapipe_hand overrides to 120 CPU calls in '
            '6 min at zero VRAM. Operator: gesture_bench 8 blind questions x 3 seeds = 24 decisions at 30 s = 12 min; mediapipe_hand 20 hands '
            'x 2 questions = 40 decisions = 20 min; prompt_hands 4 x 3 = 12 decisions = 6 min. ONE-TIME, and the real bill: ~60 min for the '
            'operator to label the twenty-hand judgement set and ~40 min to box the twenty detection frames — until both are done, six of the '
            'fifteen domain columns are BLOCKED. SHARED BANK: include_shared video covers 236 of the 251 columns with 220 probes at 3 repeats '
            '= 660 clips of 81 frames at 832x480, roughly 5 min a clip on this box = ~55 GPU-HOURS for a row that is a video generator. NOT ONE '
            "of these five rows is: two are retired, one emits a string, one renders a still through Blender and one reads pixels, so the bank's "
            'Moves probes come back transport-exempt or untested and the real bill for this sheet is the ~30 min plus ~100 operator minutes '
            'above. No claude_cli or anthropic_api row exists here, so nothing on this step spends the shared Claude week.'
        ),
    },
    'run_order': [
        'gp_lr_check',
        'gp_detects',
        'gp_judges',
        'gp_count_check',
        'gp_fused_check',
        'gp_joint_check',
        'gp_directed',
        'gp_point',
        'gp_open_palm',
        'gp_count_fingers',
        'gp_grip',
        'gp_two_hand',
        'gp_hand_to_face',
        'gp_write',
    ],
    'notes': [
        'The judging probes run FIRST and they are free: 120 CPU calls at zero VRAM on fixtures that already exist once the operator has '
        'labelled them. A partial run therefore answers the question the sheet exists to answer — can anything on this box tell a bad hand '
        'from a good one — before a single render is queued.',
        'gp_judges is the column to read first and the one most likely to come back 0.00. That is not a broken test; it is the standing '
        'receipt reproduced. A row that scores well here is the news, and it must be re-measured on a second set before it is believed.',
        'This step CLAIMS count_fingers back from the shared video bank. The bank answers it with a generic counting scene and a '
        'hand_landmarks_count check; here it is one of the eight named gestures with a blind operator beside the landmark count, because '
        'the landmark count reads the template.',
        'The two retired rows are load-bearing. legacy_qc records the 1.00-because-everything-raised failure and hand_yolo records the '
        'AGPL licence block; both are kept as receipts and both write na on every column with the reason attached.',
        'Nothing in this test asks a VLM whether a hand is right. On the 2026-09-27 defect bench the best local model scored 34/40 on a '
        'global question and 2/8 on the hard cases, which is the measurement that put the operator in this test and kept the VLM out.',
    ],
}
