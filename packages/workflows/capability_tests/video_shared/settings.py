# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The settings, detector pins and check kinds every video row shares."""

from __future__ import annotations

# ── check kinds this bank adds (the runner is a table of these) ────────────────────────
CHECK_KINDS = {
    'frames_exact': 'the produced clip decodes to exactly `frames` frames at `fps` (a short clip is a fail, not a partial)',
    'duration_s': 'clip duration in seconds is between `min` and `max`',
    'motion_min': 'mean absolute frame-to-frame luma delta over the whole clip >= `min` (0-255 scale) — proves the clip is not a still',
    'flicker_max': 'mean absolute frame-to-frame luma delta over the whole clip <= `max` (0-255 scale) — the boil/flicker ceiling',
    'flow_region': 'mean Farneback optical-flow magnitude inside the subject mask (SAM2 box prompted with `region`, model pinned in DETECTORS) is between `min` and `max` px/frame',
    'flow_direction': 'the dominant Farneback flow direction over the clip is `direction` (left|right|up|down|in|out|none) with mean magnitude >= `min` px/frame',
    'detector_count': 'the pinned `detector` counts exactly `n` instances of `label` in each frame of `sample`, in >= `share` of them',
    'hand_landmarks_count': 'MediaPipe hand_landmarker finds `hands` hands with 21 landmarks each (and `fingers` extended fingers per hand where set) in >= `share` of the frames in `sample`',
    'identity_cosine_min': 'ArcFace (insightface buffalo_l) cosine between the largest face in frame `a` and in frame `b` >= `min` (a = 0, b = -1 means frame 0 versus the last frame)',
    'identity_cosine_ref': 'ArcFace cosine between the largest face in each frame of `sample` and the reference still `ref` >= `min`',
    'ocr_equals': 'OCR (tesseract 5, `--psm 7`, pinned in DETECTORS) of each frame in `sample` equals `text` after case and whitespace normalisation, in >= `share` of them',
    'ocr_stable': 'the OCR string is identical across every frame in `sample` (lettering does not churn from frame to frame)',
    'named_colour_region': "the median hue inside the mask for `region` is within `tolerance_deg` of the named `colour`'s hue centre (COLOUR_HUES) with saturation >= 0.25, in every frame of `sample`",
    'bbox_frac': 'the subject bounding box height as a fraction of frame height is between `min` and `max` in every frame of `sample`',
    'bbox_left_of': "the bounding box of subject `a` is entirely left of subject `b`'s in >= `share` of the frames in `sample` (both located by the pinned detector)",
    'mask_iou_max': 'no two of the `n` subject masks overlap by more than `max` IoU in any frame of `sample` — the merging failure',
    'shot_cuts': 'PySceneDetect ContentDetector (threshold pinned in DETECTORS) finds exactly `n` cuts in the clip',
    'identical_clips': 'all repeats at the same seed produce an identical list of per-frame md5 hashes',
    'seam_continuity': "at the window seam frame `at`, the frame-to-frame luma delta is <= `max_ratio` times the clip's median frame delta (no jump at the join)",
    'metric_within': "the named quantity `metric` in the row's own output manifest is within `tol` of `target` (unit in `unit`)",
    'part_names_resolved': "every part name in `terms` resolves to a real named element (bone, joint, vertex group, mesh) in the row's output manifest",
    'verdict_equals_key': "the row's yes/no verdict on each fixture equals that fixture's planted key, in >= `share` of the fixtures",
    'verdict_agrees': "the row's verdict under the two phrasings in `phrasings` agrees on >= `share` of the fixtures",
    'abstains_when_unclear': 'on the fixtures listed in `unclear` the row answers "cannot tell" rather than yes or no, in >= `share` of them',
}

# ── fixed settings: the same for every row, every subject, every seed ──────────────────
NEGATIVE = (
    'blurry, low quality, jpeg artifacts, watermark, text overlay, subtitles, extra limbs, '
    'extra fingers, missing fingers, deformed hands, melting, morphing, duplicated subject, '
    'flicker, colour banding, static image'
)

FIXED = {
    'frames': 81,
    'fps': "the row's NATIVE fps, recorded per trial: Wan 2.1 = 16 fps (5.06 s), InfiniteTalk = 25 fps (3.24 s, 81-frame pad). Never resampled before a check.",
    'resolution': '832x480 unless the row is declared a 720p row, then 1280x720. One value per row, recorded.',
    'seeds': [11, 12, 13],
    'steps': 30,
    'cfg': 6.0,
    'sampler': 'uni_pc with the simple scheduler',
    'shift': "the row's PRODUCTION default, recorded into every trial. On Wan, shift is the motion lever — a shift change is a different test [[project_wan_motion_debug]].",
    'negative': NEGATIVE,
    'prompt_rule': (
        'An i2v-type row is driven by the MOTION phrase with `fixtures/video/subjects/<id>.png` as the '
        'input still. A t2v-type row is driven by SUBJECTS[id].prompt + ", " + the motion phrase. A v2v '
        'row is driven by the motion phrase over the same still held for 81 frames. The still, the prompt '
        'and the motion phrase all go into the trial.'
    ),
    'word_budget': (
        'Every still prompt is under 60 words and every motion phrase under 40 words on purpose: SDXL-family '
        "encoders truncate at 77 CLIP tokens SILENTLY, and Wan's umT5 drops tail terms long before it errors. "
        'A prompt that needs more words is a different measurement — see pd_length_ladder.'
    ),
}

COND_CLIP = {
    'seeds': [11, 12, 13],
    'repeats': 3,
    'frames': 81,
    'resolution': '832x480',
    'steps': 30,
    'cfg': 6.0,
    'sampler': 'uni_pc/simple',
    'shift': 'row production default (recorded)',
    'negative': 'NEGATIVE',
}
COND_ONE = dict(COND_CLIP, seeds=[11], repeats=1)

COND_NOTE = (
    "Every row runs the same 81 frames, the same three seeds and the same negative prompt. A row's fps, "
    'resolution and shift are its production defaults and are RECORDED into every trial rather than '
    'forced, because forcing them measures a configuration nobody ships. A comfy row names its workflow '
    '(wan_i2v.json, wan22_i2v.json, wan22_animate.json, infinitetalk_i2v.json); a service row names module '
    'and function (geom/char_vace.py, wan_animate_service.py, lipsync_service.py, rife_service.py, '
    'movement_studio.py); an ffmpeg row names the filter graph; a blender row names the script. A blender '
    'or ffmpeg row has no text prompt at all — see TRANSPORT_NA.'
)

DETECTORS = {
    'yolov8n-coco': 'ultralytics yolov8n.pt, conf 0.35, classes person/bird/dog/cat/horse/cow/sheep/boat/bottle/chair — the count detectors. A thing outside those ten classes is counted by the OPERATOR, never by a stand-in class.',
    'insightface-buffalo_l': 'ArcFace r100 embedding + SCRFD detection; cosine >= 0.35 is the same identity on our own bench',
    'mediapipe-hands': 'hand_landmarker.task, 2 hands max, min_detection_confidence 0.4; extended-finger count from the PIP/TIP y-order',
    'tesseract-5': 'tesseract 5, English + Dutch, --psm 7 for a single line, --psm 6 for a block; uppercase-normalised before compare',
    'sam2-hiera-small': 'box prompt from the region word, one mask per frame; used only to bound a region for flow and colour',
    'pyscenedetect': 'ContentDetector(threshold=27.0) on the decoded clip',
    'farneback': 'cv2.calcOpticalFlowFarneback(0.5, 3, 15, 3, 5, 1.2, 0) on the luma plane, consecutive frames',
}

COLOUR_HUES = {
    'red': 0,
    'orange': 25,
    'yellow': 55,
    'green': 110,
    'blue': 220,
    'purple': 280,
    'brown': 20,
    'grey': None,
    'black': None,
    'white': None,
}

SAMPLE5 = [0, 20, 40, 60, 80]  # the five frames every per-frame mechanical check reads
STATE_3OF3 = {'yes': 1.0, 'partial': 0.6}  # yes at 3/3 seeds, partial at 2/3
