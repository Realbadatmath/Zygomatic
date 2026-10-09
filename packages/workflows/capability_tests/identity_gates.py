# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Default test — Identity & continuity gates (identity_gates). 2026-09-30.

Question the sheet asks: "Can we prove it is still the same character, and the same set?"
The note already on the sheet is the warning this test is built to honour: "Both retired
approaches on this sheet failed the same way: a metric that was high for a reason unrelated
to the thing being checked. That is the failure mode to look for when reading any green cell
on this tab."

Shape of the test. Every row is a GATE, so every domain column is the same question asked of
a different fault: does the gate CATCH a planted fault and LEAVE the matched clean twin
alone? Twelve twin sets are planted in the approved Second Ledger stills and in the clip
continuity_qc was calibrated on. Eight of them are face faults (wrong person, an insane tile
at a high cosine, the three-angle ladder, two faces, a face on the tile edge, a mislabelled
angle, Abel the child, the Arcane restyle); four are world faults across a context-window
seam (a prop inflated 1.3x with its texture untouched, the lantern in the wrong actor's
hand, the set re-derived, and one clip that changes costume, flips the key light and jumps
at the stride seam).

The two metrics-that-were-high-for-the-wrong-reason are in the test by name. `content` plants
the insane tile — two half-people from a misaligned grid slice, the kind that scored 0.44 and
entered a training set — at a cosine ABOVE threshold: look_gate is expected to score `no`
there, because a whole-candidate AuraFace cosine has no content layer at all, and the test
says so rather than leaving the cell empty. `gameable_gate` plants a prop inflated 1.3x with
its clay texture unchanged: that is precisely what defeated the NCC prop gate and shipped an
inflated pipe bowl, which is why the fourth row, `ncc_prop`, is `transport: retired` and
carries its reason instead of a score.

`angle_aware` is measured, not looked up: identity_qc_service publishes an AuraFace table
(frontal 0.465, oblique 0.317, profile 0.206, full-body 0.18) that was quantile-matched on
630 same-person and 6.9K cross-person pairs, and the probe runs the SAME person at 0, 45 and
90 degrees to see whether the row's verdicts actually follow it. The table is pinned as a
lookup helper so the probe is graded against a written source.

What is blocked. Nothing here has been rendered. The twelve twin sets are declared with the
exact recipe that makes them and are `verified: False`: until the operator has confirmed
that the wrong-person twin really is a different person, that the insane tile really scores
above threshold, and that the inflated prop really is 1.3x, the columns they feed are
written `untested — key unverified`.
"""

from __future__ import annotations

import os

from zyg_workflows.paths import ZYG_CREWS_ROOT, ZYG_HOME, ZYG_STORYTELLER_CHARS

# ── check kinds this module adds (the runner implements exactly these) ───────────────
CHECK_KINDS = {
    'gate_flags_planted': 'the gate run on the PLANTED twin returns a rejecting verdict (identity_qc: a verdict in FAIL_CLASS; continuity_qc: ok False on the named object or background; look_gate: exit 1) AND the same gate on the matched CLEAN twin returns a pass; both halves must hold',
    'gate_passes_clean': 'the gate run on a CLEAN twin returns a passing verdict; every rejection of a clean twin is a false alarm and fails the trial',
    'gate_verdict_equals': "the gate's verdict string for the trial equals `verdict` exactly (identity_qc: pass | fail | multi_face | face_cut | mislabeled_angle | no_face | no_face_expected) — catching a fault under the WRONG name is not a catch",
    'gate_rejects_gamed': 'the gate run on the GAMED twin (the measured quantity held constant while the thing being checked is changed — an inflated prop with unchanged texture, an insane tile at a high cosine) REJECTS it; passing the gamed twin fails the trial, so the column reads with its caption: yes = cannot be gamed',
    'threshold_follows_table': "over the angle ladder, each angle's accept/reject decision is the one the pinned threshold table predicts for that angle, and a SINGLE global threshold would have produced a different decision on at least one rung — a row that uses one number for every angle scores no even when every rung happens to pass",
    'report_contains': "the gate's report has the key `field` and its value matches `pattern` (regex, case-insensitive); the number and the threshold the decision was taken on are in the OUTPUT, not only in the source",
    'seam_frames_checked': "the gate's report names the context-window seam frame indices it examined and that set contains the fixture key's `seams` (for the 57-frame stride: 57, 114, 171, …); a suite that averages over the whole clip and never looks at a seam scores no",
}

# ── sources ──────────────────────────────────────────────────────────────────────────
#: The Second Ledger intro tree the twins are cut from; $ZYG_LEDGER_INTRO overrides it.
LEDGER_INTRO = os.environ.get('ZYG_LEDGER_INTRO') or str(ZYG_HOME / 'zygomatics-zero' / 'ledger_intro')
LEDGER = LEDGER_INTRO + '/intro'
CREWS = str(ZYG_CREWS_ROOT)
ABEL = ZYG_STORYTELLER_CHARS + '/c3345deb5bde/arcane_instantid'
CORNELIS = ZYG_STORYTELLER_CHARS + '/0015c8a3f2e3/arcane_instantid'
CLIP = CREWS + '/output/multichar_seated/scene20_v7/pasted17.mp4'

FX = 'capability_tests/fixtures/gates/identity'
MAKER = FX + '/make_identity_twins.py'
MANIFEST = FX + '/MANIFEST.json'
TWINS = FX + '/twins'
CLEAN = FX + '/clean'

RECIPE = (
    'python3 ' + MAKER + ' --out ' + FX + ' --all. Pure PIL + OpenCV + numpy + one ffmpeg mux, over the '
    'approved Second Ledger masters (' + LEDGER + '/shots/p{1..5}/picture_v6.png, composed.png), the cast '
    'anchor cells (' + ABEL + '/cell_*.png for Abel, ' + CORNELIS + '/cell_*.png for Cornelis) and the clip '
    'continuity_qc was calibrated on (' + CLIP + ', 832x480, 17 fps, 341 frames). Twelve twin SETS, each a '
    'planted file plus the untouched clean file it was copied from, with the planted `region` box (or frame '
    'range) written into MANIFEST.json. '
    '(1) wrong_person — crop the Cornelis face from p3/picture_v6.png (box 467,177,746,520) and paste it, '
    'resized, into the Abel face box of p4/picture_v6.png (667,141,933,470) with a 9 px feathered alpha; the '
    'clean twin is p4/picture_v6.png untouched. '
    '(2) insane_tile — take two 512x512 halves from DIFFERENT Abel cells (cell_00 left half, cell_02 right '
    'half) and butt them together, the misaligned-grid-slice fault that measured cosine 0.44 and entered a '
    'training set; the clean twin is cell_00 whole. '
    '(3) angle_ladder — three tiles of Cornelis at yaw 0, 45 and 90 degrees, taken from the existing '
    'arcane_instantid cells and labelled frontal / oblique / profile in the MANIFEST; no clean twin (the '
    'ladder IS the trial). '
    '(4) multi_face — composite the Abel face crop into the empty upper-left quadrant of a Cornelis frontal '
    'cell so the tile holds two faces; the clean twin is the same cell untouched. '
    '(5) face_cut — translate a Cornelis frontal cell so the face centre sits 5 % from the right edge (inside '
    'the 8 % EDGE_CENTER_PCT band) and pad with edge replication; clean twin = centred. '
    '(6) mislabel — the 45-degree tile of set (3) written into the MANIFEST with label "profile" (90); the '
    'clean twin is the same tile with its true label. '
    '(7) child_abel — an Abel frontal cell against the Abel anchor (clean) and against the Cornelis anchor '
    '(planted): a child face must still be separated. '
    '(8) styled_arcane — an Arcane-restyled Cornelis cell against the Cornelis anchor (clean) and a restyle of '
    'a DIFFERENT man from p1/picture_v6.png against the same anchor (planted). '
    '(9) prop_inflate — from the clip, cut two 81-frame context windows around the stride seam at frame 57 and '
    'in the SECOND window scale the pipe-bowl region by 1.3x about its centre with cv2.INTER_CUBIC, leaving the '
    'clay texture untouched (the NCC-gameable fault); the clean twin is the unscaled pair. '
    '(10) action_wrong_actor — in the second window, translate the lantern region so its box overlaps the BOY '
    'instead of the MAN, inpainting the vacated box with cv2.INPAINT_TELEA; clean twin = untouched. '
    '(11) set_rederived — in the second window, replace the inverse-mask background with the background of '
    'p2/composed.png resized to 832x480; clean twin = untouched. '
    '(12) window_faults — three one-fault clips from the same pair of windows: costume (the doublet region '
    "hue-shifted 40 degrees from frame 57 on), lighting (the second window's key flipped by mirroring the "
    'luminance gradient left-right), seam_jump (frames 57..80 replaced by frames 200..223, a hard cut exactly '
    'at the stride seam); clean twin = the untouched clip. '
    'Every clip is remuxed with ffmpeg -framerate 17 -c:v libx264 -crf 12 -pix_fmt yuv420p. The CLEAN set is a '
    'byte copy of the untouched source of each set.'
)

# Fixed run conditions. None of these rows takes a temperature or a prompt; the repeats are
# here to catch a gate that is not reproducible (ArcFace and DINOv2 both are; GroundingDINO's
# device choice is not, which is what `deterministic` records).
COND = {
    'repeats': 3,
    'temperature': None,
    'seed': 'n/a (deterministic service)',
    'resolution': 'stills at the cell resolution the cast anchors carry; clips at 832x480, the calibration resolution',
    'image_format': 'png sRGB for stills, h264 yuv420p for clips; the runner never resizes',
    'note': 'three identical runs per twin; continuity_qc is pinned to device="cpu" for the test so a busy GPU cannot change a verdict mid-run',
}

COND_CLIP = dict(
    COND,
    sample_fps=2,
    stride=57,
    shadow=False,
    note='clip trials run continuity_qc.analyze_clip with shadow=False so `block` is populated and blocks_ship can be read off a real report; sample_fps 2 and stride 57 are the calibration settings',
)

LOOK, IDQC, CONT = ['look_gate'], ['identity_qc'], ['continuity']
FACE_ROWS = LOOK + IDQC


def _p(pid, title, feeds, fault, checks, rows, clip=False, **kw):
    p = {
        'id': pid,
        'title': title,
        'feeds': list(feeds),
        'inputs': {
            'fixture': MANIFEST + '#' + fault,
            'planted': TWINS + '/' + fault,
            'clean': CLEAN + '/' + fault,
            'prompt': None,
        },
        'conditions': dict(COND_CLIP if clip else COND),
        'checks': list(checks),
        'grade': 'measured',
        'rows': rows,
    }
    p.update(kw)
    return p


FLAG = [{'check': 'gate_flags_planted'}]

PROBES = [
    # ── Person (8) ──
    _p(
        'identity',
        'Catches the wrong person',
        ['identity'],
        'wrong_person',
        [
            {'check': 'gate_flags_planted'},
            {'check': 'report_contains', 'field': 'cosine', 'pattern': r'^-?\d+(\.\d+)?$'},
        ],
        FACE_ROWS,
        state_note="the Cornelis face on an Abel plate must fall below the row's own frontal band (identity_qc AuraFace 0.465) while the untouched plate stays above it",
    ),
    _p(
        'content',
        'The tile is sane',
        ['content'],
        'insane_tile',
        [
            {'check': 'gate_rejects_gamed'},
            {
                'check': 'gate_verdict_equals',
                'verdict': 'fail',
                'rows': ['identity_qc'],
                'note': 'identity_qc may also reject it as multi_face or face_cut; the check records which name it came out under',
            },
        ],
        FACE_ROWS,
        state_rule={'yes': 1.0, 'partial': 0.5},
        state_note=(
            'the misaligned grid slice at a HIGH cosine — the tile that scored 0.44 and entered a training set. '
            'look_gate is expected to score NO: it returns one whole-candidate AuraFace cosine and has no content '
            'layer, so a corrupt tile that happens to embed close to the anchor passes it. identity_qc has the '
            'layer (multi_face / face_cut / mislabeled_angle) and is expected to catch it. Recording that split is '
            'the point of the column.'
        ),
    ),
    _p(
        'angle_aware',
        'Thresholds vary by angle',
        ['angle_aware'],
        'angle_ladder',
        [
            {'check': 'threshold_follows_table', 'table': 'angle_thresholds'},
            {'check': 'report_contains', 'field': 'threshold', 'pattern': r'0\.(465|317|206|18)'},
        ],
        FACE_ROWS,
        conditions=dict(COND, angles=[0, 45, 90], repeats=3),
        state_note=(
            'the same person at 0, 45 and 90 degrees. A single global threshold flags every clean profile — '
            'frontal-vs-frontal typically sits above 0.5 and frontal-vs-profile drops to 0.2-0.35 — so passing all '
            'three rungs is not enough: the check also requires that one number would NOT have produced the same '
            'three decisions. The table is pinned in lookup `angle_thresholds`.'
        ),
    ),
    _p(
        'multi_face',
        'Rejects more than one face',
        ['multi_face'],
        'multi_face',
        [
            {'check': 'gate_flags_planted'},
            {'check': 'gate_verdict_equals', 'verdict': 'multi_face', 'rows': ['identity_qc']},
        ],
        FACE_ROWS,
        state_note='MAX_FACES is 1 in identity_qc_service; the twin puts a second face in an empty quadrant so the first face is untouched and only the count changes',
    ),
    _p(
        'face_cut',
        'Rejects a face on the tile edge',
        ['face_cut'],
        'face_cut',
        [
            {'check': 'gate_flags_planted'},
            {'check': 'gate_verdict_equals', 'verdict': 'face_cut', 'rows': ['identity_qc']},
        ],
        FACE_ROWS,
        state_note='the face centre is planted at 5 % from the edge, inside the 8 % EDGE_CENTER_PCT band; the clean twin is the same face centred, so only the position changes',
    ),
    _p(
        'mislabel',
        'Rejects a mislabelled angle',
        ['mislabel'],
        'mislabel',
        [
            {'check': 'gate_flags_planted'},
            {'check': 'gate_verdict_equals', 'verdict': 'mislabeled_angle', 'rows': ['identity_qc']},
        ],
        FACE_ROWS,
        state_note='a 45-degree tile delivered on a 90-degree label: |yaw| 45 is below PROFILE_LABEL_MIN_YAW-style expectation for a profile and the head-yaw check is what must catch it, not the cosine',
    ),
    _p(
        'child_gate',
        'Works on a child face',
        ['child_gate'],
        'child_abel',
        [{'check': 'gate_flags_planted'}],
        FACE_ROWS,
        state_note='Abel, the second-ledger child. The planted half scores the Abel cell against the CORNELIS anchor; the clean half scores it against the Abel anchor. A gate calibrated on adult faces only will fail one half or the other, and which half it fails is the useful number.',
    ),
    _p(
        'styled',
        'Works on a restyled face',
        ['styled'],
        'styled_arcane',
        [{'check': 'gate_flags_planted'}],
        FACE_ROWS,
        state_note="the Arcane restyle. look_gate measures identity against the character's own STYLED Arcane cells and never against the photoreal training tiles, which is exactly the property this column asks about; an identity_qc row anchored on photoreal tiles is expected to score lower here.",
    ),
    # ── World (8) ──
    _p(
        'props',
        'Props stay the same size and shape',
        ['props'],
        'prop_inflate',
        [{'check': 'gate_flags_planted'}, {'check': 'report_contains', 'field': 'area_drift_pct', 'pattern': r'\d'}],
        CONT,
        clip=True,
        state_note="the pipe bowl scaled 1.3x across the frame-57 seam, texture untouched. continuity_qc's area_drift_pct_max is 45 % and box_iou_min 0.45, so a 1.3x area change (+69 %) must cross it.",
    ),
    _p(
        'action',
        'The right actor owns the action',
        ['action'],
        'action_wrong_actor',
        [{'check': 'gate_flags_planted'}, {'check': 'report_contains', 'field': 'own_overlap', 'pattern': r'\d'}],
        CONT,
        clip=True,
        state_note='action_ownership: the prop box must overlap the MAN, not the BOY, with own_overlap_min 0.12 and own_margin_min 0.05. The comparative-CLIP gate this replaced passed whenever anybody held the prop, which is the failure the twin reproduces.',
    ),
    _p(
        'sets',
        'The set is not re-derived between windows',
        ['sets'],
        'set_rederived',
        [{'check': 'gate_flags_planted'}, {'check': 'report_contains', 'field': 'bg_seam_cos', 'pattern': r'\d'}],
        CONT,
        clip=True,
        state_note='inverse-mask background consistency: bg_seam_cos_min 0.78 across the seam and bg_anchor_min 0.55 to frame 0. Swapping the background wholesale must break the first; a slow grade creep would only break the second.',
    ),
    _p(
        'costume_gate',
        'Costume stays the same',
        ['costume_gate'],
        'window_faults/costume',
        [{'check': 'gate_flags_planted'}, {'check': 'report_contains', 'field': 'dino_seam_cos', 'pattern': r'\d'}],
        CONT,
        clip=True,
        state_note='the doublet hue shifted 40 degrees from the seam on; the DINOv2 across-the-boundary crop cosine (dino_seam_cos_min 0.80) is the PRIMARY gate and a costume change is what it was calibrated to see',
    ),
    _p(
        'lighting_gate',
        'Lighting stays consistent',
        ['lighting_gate'],
        'window_faults/lighting',
        [
            {'check': 'gate_flags_planted'},
            {
                'check': 'operator',
                'blind': True,
                'question': 'Playing the two clips unlabelled, does the key light jump from one side to the other at any point in either? yes/no',
            },
        ],
        CONT,
        clip=True,
        state_note='the key flipped left-right in the second window. This is the honest hard case for an appearance embedding: DINOv2 may absorb a lighting flip as appearance drift or may not move at all, so the blind operator question stands beside the number.',
    ),
    _p(
        'window_seam_gate',
        'Checks the context-window seams',
        ['window_seam_gate'],
        'window_faults/seam_jump',
        [{'check': 'seam_frames_checked', 'seams': [57, 114, 171, 228, 285]}, {'check': 'gate_flags_planted'}],
        CONT,
        clip=True,
        state_note="a hard cut planted exactly at frame 57, the render recipe's stride (context 81, overlap 24). The first check is the one that matters: a suite that averages over the clip and never names a seam frame scores no even if it happens to flag the clip.",
    ),
    _p(
        'gameable_gate',
        'Cannot be gamed by texture',
        ['gameable_gate'],
        'prop_inflate',
        [
            {'check': 'gate_rejects_gamed'},
            {
                'check': 'operator',
                'blind': True,
                'question': 'Comparing the two windows side by side with no labels, is the object visibly larger in the second? yes/no',
            },
        ],
        LOOK + IDQC + CONT,
        clip=True,
        state_note=(
            'POLARITY, written out because the column caption is the authority: yes = CANNOT be gamed. The trial '
            'passes when the gate REJECTS the inflated-prop twin whose texture is unchanged. That twin is the exact '
            'fault that defeated the NCC prop gate and shipped an inflated pipe bowl, which is why `ncc_prop` is on '
            'this sheet as a retired row. look_gate and identity_qc are expected to score no here: a face cosine '
            "says nothing about a prop's size, and the na reason on their other world columns says so."
        ),
    ),
]

# ── the pinned table angle_aware is measured against (a helper, not a column) ────────
ANGLE_TABLE = {
    'feeds_derive': True,
    'grade': 'receipt',
    'source': CREWS + '/identity_qc_service.py:69-79 (_CAL / THRESH_* constants, pack auraface)',
    'value': {
        'frontal': 0.465,
        'oblique': 0.317,
        'profile': 0.206,
        'fullbody': 0.18,
        'back_views': 'exempt — an embedding carries no back-of-head information',
        'min_det_score': 0.40,
    },
    'requires': [
        CREWS + '/identity_qc_service.py (the AuraFace threshold block and its 2026-08-09 note)',
        CREWS
        + '/data/runtime/auraface_calibration.json (the quantile match: 630 same-person and 6.9K cross-person pairs from 11 library characters at each production operating point)',
    ],
    'note': (
        'AuraFace is the default on LICENCE grounds, not on scores: the insightface pretrained packs state they are '
        'for non-commercial research only and this channel is monetised. Measured at matched sensitivity, frontal '
        'is a slight improvement (FAR 0.329 vs 0.354), oblique is mildly worse and PROFILE is markedly worse '
        '(0.61 vs 0.34) on the smallest sample in the set (82 same-person pairs). The profile cost is accepted, not '
        'solved — read the profile rung of angle_aware against that, not as a clean pass.'
    ),
}

# ── what each row cannot be asked ────────────────────────────────────────────────────
_WORLD_NA_FACE = (
    "a face gate embeds a face and returns a cosine; it never sees a prop, an actor's hands, a "
    'background or a context-window seam, and has no notion of two frames belonging to one clip. The '
    "world half of this sheet is the grounded suite's, and it is measured there."
)
_FACE_NA_CONT = (
    'the grounded continuity suite grounds boxes, propagates masks and compares appearance embeddings '
    'across window seams; it holds no face-recognition model and no per-angle identity threshold, so it '
    'cannot say whether a face is the right person or whether a tile is labelled correctly.'
)

_LOOK_NA = dict(
    {c: _WORLD_NA_FACE for c in ('props', 'action', 'sets', 'costume_gate', 'lighting_gate', 'window_seam_gate')},
    **{
        'angle_aware': "look_gate compares a candidate with the character's styled cells at whatever angle both happen to be; it publishes no per-angle threshold table and reads no head yaw, so there is nothing here to measure against",
        'multi_face': 'look_gate embeds the candidate and returns one cosine; it does not count faces, so a second face simply moves the number and is never named',
        'face_cut': 'there is no detection-geometry layer in look_gate — no face box, no tile-edge test — so a cut face is invisible to it as a class of fault',
        'mislabel': 'look_gate is given no angle label at all; a candidate is a candidate, so there is no label for it to contradict',
        'cap_people': 'an identity cosine is one number for one candidate; it counts nobody',
        'cap_objects': 'look_gate recognises no objects, so there is no count of them to reach a limit',
        'cap_words': 'there is no text path in look_gate; it reads no lettering at any size',
        'cap_digits': 'there is no text path in look_gate; it reads no digits at any size',
        'cap_animals': 'look_gate recognises no subjects at all, animal or otherwise',
        'cap_hands': 'look_gate has no hand detector; hands are counted on the detectors sheet where a hand model is a row',
        'cap_faces': 'look_gate embeds whatever face the worker finds and returns one cosine; it never reports how many faces stayed clean',
    },
)

# The 50 prompt-damage columns the judge bank probes on a `service` row. identity_qc takes NO
# prompt: the caller hands it a tile, an anchor and an angle LABEL, and it returns a cosine and a
# verdict. There is no sentence anywhere in the chain to paraphrase, misspell, lengthen or reorder,
# so every one of these is na rather than a manufactured cell. (look_gate gets the same exemption
# from the bank's own TRANSPORT_NA['builtin']; continuity keeps them, because GroundingDINO really
# is driven by a text phrase and a damaged phrase really can ground a different box.)
_NO_PROMPT_IDQC = (
    'pd_damage',
    'pd_paraphrase',
    'pd_word_order',
    'pd_synonym',
    'pd_typo',
    'pd_grammar',
    'pd_punctuation',
    'pd_case',
    'pd_filler',
    'pd_repetition',
    'pd_contradiction',
    'pd_negation',
    'pd_unstated',
    'pd_bleed',
    'pd_leak',
    'pd_meta_literal',
    'pd_damage_visible',
    'pd_question_wording',
    'pd_leading',
    'pd_yes_bias',
    'pd_clarity_floor',
    'pd_terse_ok',
    'pd_detail_helps',
    'pd_sweet_spot',
    'pd_prose_ok',
    'pd_structure_needed',
    'pd_example_needed',
    'pd_house_template',
    'pd_jargon_needed',
    'pd_asks_back',
    'pd_rubric_needed',
    'pd_max_hard',
    'pd_max_soft',
    'pd_max_words',
    'pd_truncation_loud',
    'pd_min_len',
    'pd_unique_things',
    'pd_unique_subjects',
    'pd_attrs_per_thing',
    'pd_instructions',
    'pd_constraints',
    'pd_order_wins',
    'pd_negative_len',
    'pd_multilingual',
    'pd_batched_questions',
    'pd_small_edit',
    'pd_seed_vs_prompt',
    'pd_fix_lands',
    'pd_fix_breaks',
    'pd_reusable',
)
_NO_PROMPT_NA = (
    'the identity worker is handed a tile, an anchor embedding and an angle label — never a '
    'sentence. There is no prompt in the chain to damage, paraphrase, lengthen or reorder, so '
    'this column has nothing to vary and any number here would be manufactured.'
)

_IDQC_NA = dict(
    {c: _WORLD_NA_FACE for c in ('props', 'action', 'sets', 'costume_gate', 'lighting_gate', 'window_seam_gate')},
    **{c: _NO_PROMPT_NA for c in _NO_PROMPT_IDQC},
    **{
        'cap_people': 'the worker embeds ONE face crop per call and refuses a tile with more (MAX_FACES = 1); it counts no crowd and never reports how many people stayed clean',
        'cap_named': 'a cosine against one anchor is not open-vocabulary naming; the gate is told whose anchor it is and answers only near/far',
        'cap_faces': 'the gate is the opposite of a face counter: above MAX_FACES = 1 it returns the verdict multi_face and stops, so there is no ladder of faces to climb',
        'cap_objects': 'ArcFace embeds a face crop; it recognises no objects and therefore reaches no limit on them',
        'cap_words': 'there is no OCR anywhere in the identity worker',
        'cap_digits': 'there is no OCR anywhere in the identity worker',
        'cap_animals': 'the detector is a human face detector (scrfd); an animal is simply no face to it',
        'cap_hands': 'the identity worker loads detection, landmarks and recognition for faces only — there is no hand model in the chain',
    },
)

_CONT_NA = dict(
    {
        c: _FACE_NA_CONT
        for c in ('identity', 'content', 'angle_aware', 'multi_face', 'face_cut', 'mislabel', 'child_gate', 'styled')
    },
    **{
        'cap_words': 'GroundingDINO grounds a phrase to a box; it does not read lettering, and the typography OCR judge is the row that does',
        'cap_digits': 'GroundingDINO grounds a phrase to a box; it reads no digits',
    },
)

NA_BANDS_FACE = {
    'reason': (
        'a face gate takes one crop and returns one number against one anchor. It answers no question, names no '
        'subject, counts nothing and judges no relation or attribute — asking it the 132-subject bank would '
        'manufacture empty cells. The recognition half of this sheet is answered by the grounded row, which '
        'really is open-vocabulary, and by the vlm_judges sheet.'
    ),
    'bands': [
        'Sees: People',
        'Sees: The body',
        'Sees: Food',
        'Sees: Damage & wear',
        'Sees: Text & number',
        'Sees: Objects',
        'Sees: Animals',
        'Sees: Nature & weather',
        'Sees: Built environment',
        'Sees: Clothing',
        'Names: People',
        'Names: The body',
        'Names: Food',
        'Names: Damage & wear',
        'Names: Text & number',
        'Names: Objects',
        'Names: Animals',
        'Names: Nature & weather',
        'Names: Built environment',
        'Names: Clothing',
        'Counting & quantity',
        'Space & relation',
        'Attributes',
    ],
}

TEST = {
    'step': 'identity_gates',
    'version': '2026-09-30.1',
    'title': 'Twelve planted identity and continuity faults, and their clean twins',
    'purpose': (
        'Prove each gate on this tab catches the fault it claims and leaves the matched clean twin alone — and '
        'plant, on purpose, the two faults that made the retired rows look green for the wrong reason: a corrupt '
        'tile at a high cosine, and a prop inflated 1.3x with its texture untouched.'
    ),
    'include_shared': 'judge',
    'rows': {
        'look_gate': {
            'transport': 'builtin',
            'where': LEDGER + '/look_gate.py  (--char abel|cornelis --cand <png> --json out.json)',
            'model': 'AuraFace identity cosine via id_score.embed against the character\'s own STYLED Arcane cells, plus a palette band; the local VLM costume read is advisory and can only hard-fail "is this a painting"',
            'na': _LOOK_NA,
            'na_bands': NA_BANDS_FACE,
            'budget': {
                'calls': 96,
                'minutes': 22,
                'gpu_minutes': 18,
                'operator_minutes': 3,
                'note': 'the eight face twin sets x 2 halves x 3 repeats = 48, the angle ladder 3 x 3 = 9, the clean sweep 12 x 3 = 36, plus 3 on the gamed clip frame pair = 96. AuraFace cold load ~40 s, ~1.5 s per candidate, plus one advisory qwen3.5:9b call each: ~22 min, ~18 of them on the GPU. No world column runs on this row.',
            },
        },
        'identity_qc': {
            'transport': 'service',
            'where': CREWS
            + '/identity_qc_service.py  (the contact-sheet entry point, pack auraface, worker _identity_embed_worker.py in the ComfyUI venv)',
            'model': 'AuraFace/glintr100 ArcFace cosine with angle-aware thresholds (frontal 0.465 / oblique 0.317 / profile 0.206 / full-body 0.18) plus the content-truth layer: multi_face, face_cut, mislabeled_angle, bad_orientation',
            'na': _IDQC_NA,
            'na_bands': NA_BANDS_FACE,
            'budget': {
                'calls': 96,
                'minutes': 14,
                'gpu_minutes': 10,
                'operator_minutes': 3,
                'note': 'the same 96 face trials as look_gate. The worker is a subprocess in the ComfyUI venv: ~50 s cold for scrfd + 1k3d68 + the recogniser, then ~0.6 s per tile including the yaw/roll pass. ~14 min, ~10 on the GPU. No world column and no prompt-damage column runs on this row (na_bands plus _NO_PROMPT_IDQC), so the 132-subject bank and the 50 prompt variants cost this row nothing.',
            },
        },
        'continuity': {
            'transport': 'service',
            'where': CREWS
            + '/continuity_qc.py  (analyze_clip and action_ownership, device="cpu" pinned for the test, shadow=False)',
            'model': 'GroundingDINO SwinT-OGC (open-vocabulary boxes) + SAM2.1 hiera base_plus (mask propagation) + DINOv2 ViT-S/14 (appearance, VBench protocol); thresholds box_iou_min 0.45, area_drift_pct_max 45, dino_seam_cos_min 0.80, bg_seam_cos_min 0.78, own_overlap_min 0.12',
            'na': _CONT_NA,
            'budget': {
                'calls': 834,
                'minutes': 395,
                'gpu_minutes': 0,
                'operator_minutes': 32,
                'note': 'THE EXPENSIVE ROW, honestly: 6 world twin sets x 2 halves x 3 repeats = 36 clip analyses at ~7.5 min each (the measured 448 s for a 20 s 832x480 clip at sample_fps 2 — 43 sampled frames, 6 windows, 3 props + 2 actor masks — on 24 CPU cores) = ~270 min, PLUS the judge bank: 132 subjects x 2 halves x 3 repeats = 792 single-frame GroundingDINO+DINOv2 calls at ~9 s = ~119 min. 828 + 6 gameable = 834 calls, ~395 min. It is CPU by the GPU-floor rule, so it does not queue behind a render, but it must be scheduled overnight. Operator: 2 blind questions x 3 repeats plus the 132-subject bank verification share = ~32 min.',
            },
        },
        'ncc_prop': {
            'transport': 'retired',
            'where': 'the NCC prop gate — normalised cross-correlation of a prop crop at a fixed rectangle across frames',
            'model': 'retired',
            'skip': (
                'Retired and superseded by the grounded continuity suite (continuity_qc.py, 2026-07-30). The '
                'scene20_v7 post-mortem showed NCC is texture-gameable: a pipe bowl can INFLATE while NCC stays '
                'high because the clay texture is unchanged, and an inflated prop shipped on exactly that green '
                'cell. The row is kept so the sheet keeps its receipt for why the replacement exists; it is never '
                'run and every column is na with this reason.'
            ),
        },
    },
    'probes': PROBES,
    'derive': {
        'speed': {
            'from': 'wall clock per trial — one tile for the face rows, one two-window clip for the grounded row',
            'grade': 'measured',
            'unit': 's',
        },
        'throughput': {
            'from': 'trials per hour at steady state, model load paid once',
            'grade': 'measured',
            'unit': 'count',
        },
        'first_take': {
            'from': "share of probes whose FIRST of three repeats already gave the trial's verdict",
            'grade': 'measured',
        },
        'retries': {
            'from': 'runs until the verdict stopped changing, over the probes that eventually passed',
            'grade': 'measured',
            'unit': 'count',
        },
        'silent_fail': {
            'from': 'share of the twelve planted faults the row passed while writing nothing in its report that would let a reader notice — the shape both retired approaches failed in',
            'grade': 'measured',
        },
        'receipts': {
            'from': 'the run leaves the per-twin verdict JSON, the cosines or seam numbers, the thresholds used, the sha256 of both twins and, for the grounded row, the run_ledger.record_gate entries',
            'grade': 'receipt',
        },
        'degrades': {
            'from': "the grounded row's own device rule: pick_device takes CUDA only when nvidia-smi reports >= 8 GB free and falls back to CPU at ~10x — measured by running one clip trial with the GPU deliberately occupied",
            'grade': 'measured',
        },
    },
    'lookup': {
        'angle_thresholds': ANGLE_TABLE,
    },
    'wiring': {
        'blocks_ship': {
            'grade': 'assumed',
            'from': (
                'read off the code paths, never run. identity_qc_service.py:109 FAIL_CLASS = (fail, multi_face, '
                'face_cut, mislabeled_angle, bad_orientation) and identity_qc_service.py:627 counts them to drive '
                'regeneration and dataset exclusion — that row DOES block. look_gate.py:266 `sys.exit(1)` gives a '
                'non-zero exit the shot scripts read. continuity_qc.py:509 defaults shadow=True and '
                'continuity_qc.py:723 sets out["block"] = (not out["ok"]) and not shadow — SO, AS WIRED, THE '
                'GROUNDED SUITE BLOCKS NOTHING: it reports and writes run_ledger gates only. ncc_prop is retired '
                'and blocks nothing by definition.'
            ),
            'note': 'assumed, not measured: this test never runs a ship. The honest reading for the continuity row is that its blocking exists in the code and is switched off by the default it ships with.',
        },
    },
    'na': {},
    'fixtures': [
        {
            'path': MAKER,
            'generated': RECIPE,
            'note': 'the generator is named here and its operations are written out; this task created no binaries',
        },
        {
            'path': MANIFEST,
            'generated': 'written by ' + MAKER + ' --all',
            'verified': False,
            'blocks': ['identity', 'content', 'child_gate', 'styled', 'props', 'gameable_gate'],
            'how_to_verify': (
                'run the maker, open ' + TWINS + '/contact.jpg once and confirm per set: the wrong_person twin '
                'carries a face that is visibly not Abel; the insane_tile twin is visibly two half-people AND '
                'measures AuraFace cosine ABOVE 0.465 against the Abel anchor (record it in '
                'MANIFEST.insane_tile.cosine — if it does not, the twin is not the fault we mean and must be '
                'remade from a different cell pair); the child and styled twins are the right pairings; and '
                'the prop in prop_inflate window 2 measures 1.3x the window-1 box on both axes. Then set '
                'verified = true.'
            ),
        },
        {
            'path': TWINS,
            'generated': 'python3 ' + MAKER + ' --all',
            'verified': False,
            'blocks': [
                'multi_face',
                'face_cut',
                'mislabel',
                'angle_aware',
                'action',
                'sets',
                'costume_gate',
                'lighting_gate',
                'window_seam_gate',
            ],
            'how_to_verify': (
                'confirm the geometry the planted faults claim: two faces in multi_face, the face centre inside '
                '5 % of the edge in face_cut, the true yaw of each angle rung measured with the worker and '
                'written into MANIFEST.angle_ladder (0/45/90 +-8 degrees), the lantern overlapping the boy in '
                'action_wrong_actor, a different background in set_rederived, and the costume / lighting / '
                'seam_jump clips each carrying ONE change and it starting at frame 57. Then set verified = true.'
            ),
        },
        {
            'path': CLEAN,
            'generated': 'python3 ' + MAKER + ' --clean',
            'verified': True,
            'note': 'byte copies of the approved masters and of the untouched calibration clip '
            + CLIP
            + ' — no new judgement is claimed for them',
        },
    ],
    'budget': {
        'calls': 96,
        'tokens_in': 0,
        'tokens_out': 0,
        'tokens_note': "a face embedder and a grounded detector take pictures and thresholds, not prompts; no language model is scored on this step and look_gate's advisory VLM line is counted in its minutes only",
        'minutes': 14,
        'gpu_minutes': 10,
        'operator_minutes': 3,
        'note': (
            'The test-level numbers are the FACE rows: 8 face twin sets x 2 halves x 3 repeats = 48, the angle '
            'ladder 3 rungs x 3 = 9, the 12 clean twins x 3 = 36, plus 3 on the gamed pair = 96 calls, ~14 min with '
            '~10 on the GPU (the worker subprocess). look_gate overrides to 22 min because it adds an advisory VLM '
            'call per candidate; identity_qc keeps the default. The grounded row overrides to 834 calls and ~395 '
            'min and is the only reason this test needs scheduling: 36 two-window clip analyses at the measured '
            '448 s each (~270 min) PLUS the SHARED JUDGE BANK, which this row does run — 132 subjects x 2 halves x '
            '3 repeats = 792 single-frame calls at ~9 s = ~119 min. The two face rows and the retired row run none '
            'of the bank (na_bands / skip), so it is charged once. ncc_prop is 0: it is retired and skipped. No '
            'claude_cli or anthropic_api row exists on this step, so the shared Claude week is untouched. Operator: '
            '2 blind questions x 3 repeats = 3 min on the face rows, ~32 min on the grounded row including its '
            'share of the bank, PLUS a one-time ~40 min verifying the twelve twin sets, until which identity, '
            'content, child_gate, styled, props, gameable_gate, multi_face, face_cut, mislabel, angle_aware, '
            'action, sets, costume_gate, lighting_gate and window_seam_gate are BLOCKED.'
        ),
    },
    'run_order': [
        'multi_face',
        'face_cut',
        'mislabel',
        'angle_aware',
        'identity',
        'content',
        'child_gate',
        'styled',
        'props',
        'gameable_gate',
        'action',
        'sets',
        'window_seam_gate',
        'costume_gate',
        'lighting_gate',
    ],
    'notes': [
        'Cheap and mechanical first: the five identity_qc geometry probes are seconds each and need no clip; every clip '
        'probe is ~7.5 min per trial, so a partial run still fills the Person half of the sheet.',
        'The rows split the sheet cleanly — the face rows own the Person band, the grounded row owns the World band — and '
        'the na reasons say which, so a fault that shipped lands on the gate that should have caught it.',
        'Two columns are expected to come out NO and that is the finding, not a gap: look_gate on `content` (a whole-'
        'candidate cosine has no content layer) and both face rows on `gameable_gate` (a face cosine says nothing about a '
        'prop). The sheet note — "a metric that was high for a reason unrelated to the thing being checked" — is what '
        'those two cells record.',
        'blocks_ship is assumed for every row and, for the grounded row, the honest reading is that it blocks nothing as '
        'shipped: shadow=True is the default at continuity_qc.py:509.',
        'continuity_qc is pinned to device="cpu" for this test. Its own rule takes CUDA only above an 8 GB free floor, so '
        'an unpinned run would give different wall times, and possibly different verdicts, depending on what else was '
        'rendering.',
    ],
}
