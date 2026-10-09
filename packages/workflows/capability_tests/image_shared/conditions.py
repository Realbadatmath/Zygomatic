# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""image_shared.conditions — the fixed conditions every image row and subject runs under."""

from __future__ import annotations

# Check kinds this bank adds. The base vocabulary is in capability_tests/__init__.py; these
# are the image-specific ones, and the runner must implement exactly these rules.
CHECK_KINDS = {
    'hand_landmarks': 'MediaPipe hand_landmarker (pinned task file) finds exactly `hands` hands, each with 21 landmarks and 5 fingertips no closer than `min_tip_px` to one another',
    'detector_count': 'a closed-set detector counts `class` (person|face|dog|cat|horse|cow|sheep|bird|boat) — InsightFace for face, YOLOv8x-COCO otherwise — and the count equals `count`, or is >= `min`',
    'open_vocab_count': 'GroundingDINO (pinned revision) boxes for `query` above `min_score` number exactly `count`, or >= `min`',
    'open_vocab_present': 'GroundingDINO finds at least one box above `min_score` for every term in `terms`',
    'open_vocab_absent': 'GroundingDINO finds no box above `min_score` for any term in `terms`',
    'spatial_relation': 'the boxes for `a` and `b` stand in `relation` (left_of|right_of|above|below|inside|overlaps|larger|apart) with at least `margin_px` of slack',
    'colour_of_thing': 'inside the box for `thing`, the share of pixels within COLOUR_BANDS[`colour`] is >= `min_share` (or <= `max_share` when that is the one given)',
    'ocr_equals': 'PaddleOCR text in the frame, upper-cased and whitespace-collapsed, contains `text` exactly once and no other lettering',
    'ocr_contains': 'every term in `terms` appears in the OCR text (upper-cased, whitespace-collapsed)',
    'ocr_absent': 'no term in `terms` appears in the OCR text',
    'ocr_lines_min': 'OCR finds at least `min` text lines of at least `min_chars` characters each (legible writing, content not judged)',
    'face_emotion_top': 'the top label of the pinned face-expression classifier on the largest face is in `expect`',
    'identity_cosine_min': 'ArcFace (buffalo_l) cosine between the largest face here and the face in `ref` is >= `min`',
    'identical_images': 'every repeat is byte-identical after stripping PNG metadata',
    'image_distance': '`metric` (lpips|pixel) distance to the render named in `to` is <= `max`, or >= `min` when that is the one given',
    'image_size': 'the returned PNG is exactly `width` x `height` pixels',
    'render_returned': 'the queue returned a PNG at all (no error, no empty result) — the check a truncation probe needs',
    'log_warns': 'the ComfyUI log for this render contains `pattern` (the truncation warning, the OOM notice)',
}

# ── fixed conditions, identical for every row and every subject ────────────────────────────
NEGATIVE = (
    'lowres, blurry, out of focus, jpeg artefacts, extra limbs, extra fingers, fused fingers, '
    'missing fingers, deformed hands, extra heads, duplicated subject, mutated anatomy, '
    'cross-eyed, cartoon, anime, 3d render, cgi, plastic skin, modern clothing, '
    'modern buildings, cars, plastic packaging, neon light'
)
NEGATIVE_NOTE = (
    'ONE negative prompt for every subject in every image step, so two models differ by the '
    'model and not by what someone typed. It carries NO anti-text term (no "text", no '
    '"watermark", no "signature", no "letters"): the thirteen Render: Text & number subjects '
    'exist to measure lettering, and suppressing lettering would answer them by hand. It '
    'names the anatomy defects because the house rows are period portraits and the defects '
    'are what the operator is asked about — a model that needs the negative to hold its hands '
    'together still fails the hand subjects, which is the point.'
)

COND_RENDER = {
    'width': 1024,
    'height': 1024,
    'seeds': [11, 12, 13],
    'repeats': 3,
    'negative': NEGATIVE,
    'steps': "the row's production default, read from its workflow JSON and copied into the trial",
    'cfg': "the row's production default, read from its workflow JSON and copied into the trial",
    'sampler': "the row's production default, read from its workflow JSON and copied into the trial",
    'scheduler': "the row's production default, read from its workflow JSON and copied into the trial",
    'lora': 'none, unless the step is lora_train or identity (where the LoRA IS the subject)',
    'batch_size': 1,
    'clip_skip': "the row's production default, recorded into the trial",
}
COND_NOTE = (
    'Every probe in this bank runs at 1024x1024 on seeds [11, 12, 13], one render per seed, '
    'with the shared negative prompt and no LoRA. A row whose native square is not 1024 (an '
    'upscale row, a 512 legacy checkpoint) renders at its native square and the trial records '
    'it; nothing else moves. steps / cfg / sampler / scheduler / clip_skip are NOT chosen '
    'here: they are whatever the row ships in production, read out of its workflow JSON at run '
    'time and written into the trial, because a sheet is meant to say what the house gets, not '
    'what a test-writer preferred. Two rows are comparable because the prompt, the negative, '
    'the size, the seeds and the scoring are byte-identical; where their samplers differ, the '
    'trial says so.'
)
PROMPT_NOTE = (
    'Every subject prompt is under 60 words. SDXL truncates at 77 CLIP tokens WITHOUT warning, '
    'so a 90-word prompt measures truncation instead of the subject. The runner asserts '
    'clip_tokens_max 77 on every prompt in SUBJECTS before it queues anything; pd_clip77 and '
    'pd_length_ladder are the only probes allowed past the window.'
)

# HSV bands `colour_of_thing` measures against. Written here so a colour cell cannot be argued.
COLOUR_BANDS = {
    'red': {'h': [[0, 12], [168, 180]], 's': [90, 255], 'v': [50, 255]},
    'blue': {'h': [[100, 130]], 's': [80, 255], 'v': [40, 255]},
    'green': {'h': [[40, 85]], 's': [70, 255], 'v': [40, 255]},
    'yellow': {'h': [[22, 34]], 's': [90, 255], 'v': [80, 255]},
    'brown': {'h': [[8, 22]], 's': [60, 200], 'v': [30, 160]},
    'white': {'h': [[0, 180]], 's': [0, 40], 'v': [190, 255]},
    'black': {'h': [[0, 180]], 's': [0, 90], 'v': [0, 55]},
    'grey': {'h': [[0, 180]], 's': [0, 35], 'v': [70, 185]},
}

# The picture the image-IN steps (i2i, inpaint, controlnet, upscale, identity) feed a subject
# probe. One descriptor for all 132; the runner fills <id>.
SUBJECT_FIXTURES = {
    'path': 'capability_tests/fixtures/image/subjects/<render_id>.png',
    'generated': 'the t2i default test, row sdxl_base, seed 11, the frame the operator passed',
    'verified': False,
    'blocks': 'every render_* column on i2i, inpaint, controlnet, upscale and identity',
    'how_to_verify': (
        'Run the t2i default test on row sdxl_base. For each render_* id, take the seed-11 '
        'frame the operator passed, crop nothing, save it as fixtures/image/subjects/<id>.png, '
        'and set verified: True only once all 132 exist and each one plainly shows its subject '
        '— a fixture that is already wrong makes every image-in step look broken. Until then '
        'those columns are written untested with the note "subject fixtures unverified".'
    ),
}
