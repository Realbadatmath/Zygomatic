# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

from __future__ import annotations

from zyg_workflows.paths import ZYG_HOME
import os

#: The Second Ledger intro tree the defect bench the receipts quote lives in; $ZYG_LEDGER_INTRO overrides it.
LEDGER_INTRO = os.environ.get('ZYG_LEDGER_INTRO') or str(ZYG_HOME / 'zygomatics-zero' / 'ledger_intro')

# ── check kinds this bank adds to capability_tests.__init__.CHECK_KINDS ───────────────
# One line each: what is measured, against what, which threshold fields carry it. The
# runner is a table of these and nothing else.
CHECK_KINDS = {
    # ── a yes/no verdict against a matched pair ──
    'answer_yes_no': "the first word of the answer normalises to yes or no (yes|y|true|ja -> yes; no|n|false|nee -> no) and equals the FIXTURE key's `answer`; a hedge, a description or an empty answer counts as WRONG on that fixture",
    'recall_precision_min': "over the probe's positive and negative fixtures x repeats: recall = correct yes / positives, precision = correct yes / all yes answers; the probe passes only when recall >= `recall` AND precision >= `precision`",
    'yes_rate_near': "|share of yes answers over the probe's balanced (equal true-yes and true-no) fixture set - `target`| <= `tol`",
    'abstains': 'the answer is one of the abstain forms (cannot tell | unclear | not visible | unknown | I do not know) rather than a yes, a no or a guess',
    'answer_agrees': 'the normalised answer equals the answer of trial `to` on the SAME fixture (same key, other wording); a flip is a fail',
    'answer_equals_fixture_key': 'the normalised answer is in the `accept` set of the FIXTURE the trial ran on — each half of a pair carries its own key, so one answer cannot be right on both',
    # ── naming, unprompted ──
    'names_label_present': "the free-form answer contains the fixture's label or one of `accept` (case-insensitive, word boundary) on the POSITIVE fixture and contains none of them on the NEGATIVE one; both halves must hold",
    'open_vocab_label': 'an open-vocabulary detector given the subject label as its prompt returns a detection with confidence >= `conf` over the subject region on the positive fixture and none on the negative one',
    # ── detectors: a box or a mask, not a sentence ──
    'detector_finds': "the transport returns at least one detection with confidence >= `conf` whose box IoU with the fixture key's `region` is >= `iou` on the positive fixture, and no such detection on the negative one",
    # ── counting, read mechanically where a detector exists ──
    'count_equals_key': "the single integer in the answer (number words -> digits) equals the fixture key's `count` exactly",
    'count_within': "the integer in the answer is within `tol` of the fixture key's `count`",
    'person_count': 'the house person detector (ultralytics person class, continuity_qc.py) counts `count` people in the fixture — this, not the render prompt, is the key the model is scored against',
    'face_count': 'the MediaPipe face mesh in anatomy_qc.py counts `count` faces in the fixture',
    'mediapipe_hands': "MediaPipe hand_landmarker (anatomy_qc.py) on the fixture returns `hands` hands and, per hand, `fingers` extended fingers; the model's answer is scored against THAT reading",
    'arcface_cosine': 'ArcFace cosine (identity_qc_service.py) between the named cast reference and the face the judge named is >= `min`',
    'ocr_equals': "OCR (the typography judge's engine, pinned in `engine`) of the fixture's lettering region equals the fixture key's `text` after case and whitespace normalisation",
    # ── question load ──
    'answers_counted': 'the output holds exactly `n` answers, one per question asked, in the order asked, each parseable as yes/no or a single number',
    'agreement_min': 'the batched answers agree with the same questions asked one at a time in >= `min` of cases',
    'accuracy_delta': 'accuracy on the `with` arm minus accuracy on the `without` arm; the column records the delta and passes when it is >= `min`',
}

# ── fixed run settings — the SAME for every row, every repeat ─────────────────────────
# A judge is asked ONE question about ONE picture at a time (the defect bench's wording
# style: one crop, one question, yes/no). Temperature 0 and seed 11 wherever the transport
# has them; 1024x1024 PNG, sRGB, no resize by the runner.
RESOLUTION = '1024x1024'
COND_JUDGE = {
    'temperature': 0.0,
    'seed': 11,
    'max_tokens': 80,
    'repeats': 3,
    'resolution': RESOLUTION,
    'image_format': 'png sRGB, no runner-side resize',
}
COND_JSON = {
    'temperature': 0.0,
    'seed': 11,
    'max_tokens': 250,
    'repeats': 3,
    'resolution': RESOLUTION,
    'image_format': 'png sRGB, no runner-side resize',
}
COND_LONG = {
    'temperature': 0.0,
    'seed': 11,
    'max_tokens': 900,
    'repeats': 3,
    'resolution': RESOLUTION,
    'image_format': 'png sRGB, no runner-side resize',
}

COND_NOTE = (
    'Every judge trial is one image plus one question at ' + RESOLUTION + ', temperature 0, seed 11, '
    '3 repeats. vlm_ollama takes both through `options`; vlm_inspector (Qwen3-VL 8B FP8 resident / '
    '32B boundary) takes the seed but runs in-process, so its rows carry the resident model id on every '
    'trial; a `service` row (hand_yolov8s, MediaPipe, GroundingDINO+SAM2+DINOv2, ArcFace, era_gate, the '
    'typography OCR judge) takes a fixture and a threshold, not a temperature — its seed field is written '
    '"n/a (deterministic service)" on the trial; a `builtin` row (look_gate, patch_gate, fill_check, '
    'plate_law) is arithmetic over a pair of pictures and answers none of the recognition bands at all '
    '(see transport_na). RECEIPTS: the 2026-09-27 defect-judge bench is the model for what a trial must '
    'carry — question text, image sha256 and the raw answer, one row per trial '
    f'({LEDGER_INTRO}/intro/defect_bench/sheet.json: 6 pictures, 55 '
    'questions, 5 models; best global-question model 34/40, 2/8 on fused fingers / extra digits / second '
    'feather; era_gate moondream 34/40 vs Qwen3-VL 2/8). That bench is WHY no VLM verifies a fixture here '
    'and why every recognition probe carries a mechanical cross-check where a detector exists.'
)
