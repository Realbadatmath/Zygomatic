# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""capability_tests/t2v.py — the default test for step `t2v` (text to video). 2026-09-30.

One row: Wan2.1 T2V 14B fp8, driven from a prompt alone with no input still anywhere in the
test. That absence is the whole point of the step and of this module: everything i2v gets for
free from an approved still — who the person is, what they are wearing, what the room looks
like — this step has to produce from words, and the honest answer to several of these columns
is expected to be `no`. `identity` is written as a real measurement of a NEGATIVE: the same
named character is asked for on three seeds and the ArcFace cosine BETWEEN the seeds is read.
A cell that says "no, cosine 0.11 across seeds" is worth a great deal more to the reader than
an empty cell or a hedged note, so the probe is written to produce that number rather than to
be avoided.

The shared video bank (`video_shared.py`) covers 385 of the 399 columns this sheet asks — the
subject bank, capacity, counting and spatial, the prompt bands, universal. This module disposes
the fourteen it leaves: prompt, identity, motion, physics, camera_ctl, scene_ctl, style_video,
length, flicker, morph, hands_video, continuity_shot, period_video, res_video.

Two facts about this row that every trial records, because they change what a number means:
  * There is NO workflow JSON for T2V in `_comfy_workflows/` (2026-09-30). The graph is declared
    below as `generated` — wan_i2v.json with the image node dropped — and must exist before the
    first run. Nothing in this task creates it.
  * `wan_video_service._CLIP_FPS = 17` while the model card says 16, so a "3-second" clip is
    81 frames either way and its real duration depends on which number you believe. `res_video`
    records the pair; every length statement here is in FRAMES, never in seconds.
"""

from __future__ import annotations

# Check kinds the base runner does not have yet. The validator unions these into the test.
CHECK_KINDS = {
    'identity_cosine_across': 'ArcFace (`detector`) cosine between the SAME frame index of two trials '
    'listed in `across` >= `min`; a frame with no face detected is a fail '
    'for that pair and the trial records how many pairs were scorable',
    'identity_cosine_min': 'ArcFace (`detector`) cosine between frame `a` and frame `b` of the one '
    'clip >= `min` (negative indices count from the end)',
    'ssim_min': 'SSIM between frame `a` of trial `a_of` and frame `b` of trial `b_of` '
    '(both default to this trial) >= `min`',
    'flow_mean_range': 'mean Farneback flow magnitude in px/frame over the whole clip is between `min` and `max`',
    'flow_direction': 'the dominant Farneback flow direction over the clip agrees with '
    '`expect` (left|right|up|down|in|out|none) for >= `share` of frame pairs, '
    'measured on the BACKGROUND (outside the SAM2 subject mask) so a walking '
    'actor cannot be mistaken for a pan',
    'flicker_max': 'mean absolute luma delta between consecutive frames, after global '
    'brightness is normalised out, <= `max`',
    'bbox_stable': 'the YOLO box for `label` is present in every sampled frame and its '
    'centre moves no more than `max_jump` of frame width between samples',
    'era_gate_clean': 'era_gate.py on the frames in `sample` reports no anachronism for period '
    '`period` on >= `share` of them; the cell records every object it flagged',
    'operator_choice': 'BLIND forced choice out of `options` per trial; scores 1 only when the '
    'answer equals `answer`, so a viewer who cannot tell scores 0',
}

DET_ARC = 'insightface-buffalo_l'
DET_YOLO = 'yolov8n-coco'
DET_HANDS = 'mediapipe-hands'
DET_SAM = 'sam2-hiera-small'
DET_FLOW = 'farneback'

# Shared with the bank so a t2v clip here is the same object as a t2v clip there.
NEGATIVE = (
    'blurry, low quality, watermark, text, jpeg artifacts, extra limbs, deformed hands, '
    'flickering, morphing, duplicate frames'
)

COND = {
    'seeds': [11, 12, 13],
    'repeats': 3,
    'frames': 81,
    'resolution': '832x480',
    'steps': 30,
    'cfg': 6.0,
    'sampler': 'uni_pc/simple',
    'shift': 'row production default (recorded in the trial)',
    'negative': 'NEGATIVE',
}
COND_ONE = dict(COND, seeds=[11], repeats=1)

SAMPLE5 = [0, 20, 40, 60, 80]
S3 = {'yes': 1.0, 'partial': 0.6}  # 3/3 seeds = yes, 2/3 = partial
LADDER = {'yes': 1.0, 'partial': 0.6}

# The one subject this module reuses everywhere a person is needed, written out once so the
# runner cannot paraphrase it and so two columns are never measured on two different men.
MAARTEN = (
    'a 40-year-old Dutch harbour master, weathered face, short dark beard, wearing a dark '
    'brown leather coat over a dull red waistcoat and a flat black cap'
)


def _op(q, for_=None):
    c = {'check': 'operator', 'blind': True, 'question': q}
    if for_:
        c['for'] = for_
    return c


def _p(pid, title, feeds, prompt, checks, cond=None, **kw):
    p = {
        'id': pid,
        'title': title,
        'feeds': list(feeds),
        'inputs': {'prompt': prompt, 'negative': NEGATIVE},
        'conditions': dict(cond or COND),
        'checks': list(checks),
        'grade': 'measured',
        'state_rule': S3,
    }
    p.update(kw)
    return p


PROBES = [
    # ── the instruction itself ───────────────────────────────────────────────────────────
    _p(
        'prompt_obeyed',
        'Everything the prompt asked for is on screen',
        ['prompt'],
        'a 17th-century Dutch quay at dawn, three wooden barrels stacked on the left, a single '
        'moored fishing boat on the right, a grey-haired man in a blue coat walking from the '
        'barrels towards the boat, still water, no other people',
        [
            {'check': 'bbox_stable', 'label': 'person', 'sample': SAMPLE5, 'max_jump': 0.25, 'detector': DET_YOLO},
            {
                'check': 'operator',
                'blind': True,
                'question': 'This clip was asked for: a quay at dawn, THREE stacked barrels on the left, '
                'ONE moored boat on the right, ONE grey-haired man in a blue coat walking '
                'from the barrels towards the boat, still water, nobody else. Is every one of '
                'those seven things true for the whole clip? yes/no',
            },
            {
                'check': 'operator',
                'blind': True,
                'question': 'Does anyone or anything appear in this clip that the description above did '
                'NOT ask for? Answer yes if something extra appears.',
                'for': 'invert',
            },
        ],
        state_note=(
            'The second question is INVERTED — a yes there is a fail — and the runner flips it '
            'before scoring, which the trial records so it is not flipped twice. Six '
            'countable things in one prompt is deliberate: the bank measures counting on '
            'single objects, and what a quay shot actually needs is several instructions '
            'held at once.'
        ),
    ),
    # ── identity from words alone: a measured negative ───────────────────────────────────
    _p(
        'id_from_words',
        'The same named character, measured across seeds',
        ['identity'],
        MAARTEN + ', standing at a harbour railing looking out at the water, head and shoulders, '
        'he turns his head slowly to his left and back',
        [
            {
                'check': 'identity_cosine_across',
                'across': ['id_from_words@11', 'id_from_words@12', 'id_from_words@13'],
                'frame': 0,
                'min': 0.35,
                'detector': DET_ARC,
            },
            {'check': 'identity_cosine_min', 'a': 0, 'b': -1, 'min': 0.35, 'detector': DET_ARC},
            {
                'check': 'operator_choice',
                'options': ['the same man three times', 'three different men', 'cannot tell'],
                'answer': 'the same man three times',
                'blind': True,
                'question': 'Here are the opening frames of three clips made from one identical written '
                'description. Choose one: the same man three times / three different men / '
                'cannot tell.',
            },
        ],
        state_rule={'yes': 1.0, 'partial': 0.34},
        state_note=(
            'This is written to MEASURE an expected no, not to avoid it. The cross-seed cosine '
            'is the number the sheet has never carried: a prompt is not an identity, and 0.35 '
            'is the house same-person threshold (insightface buffalo_l, identity_qc_service). '
            'The WITHIN-clip check is scored separately in the same probe so the cell can say '
            'the honest thing — the face may well hold for 81 frames while being a different '
            'man on every seed. 1/3 checks = partial is deliberate: holding within a clip is '
            'a real, partial capability. A forced three-way choice replaces a yes/no because '
            '"is this the same man?" tells the viewer the answer.'
        ),
    ),
    # ── motion, physics ─────────────────────────────────────────────────────────────────
    _p(
        'motion_verb',
        'The verb in the prompt is performed',
        ['motion'],
        'VARIANT',
        [
            {'check': 'flow_mean_range', 'min': 0.8, 'max': 40.0, 'detector': DET_FLOW},
            _op(
                'The written instruction for this clip is shown beside it. Is the action in that '
                'instruction actually performed — begun, carried out and finished — rather than merely '
                'suggested by a small movement or a pan across a still figure? yes/no'
            ),
        ],
        variants={
            'v_walk': 'a fisherman in a brown coat walks the length of a wooden quay away from the '
            'camera, past three barrels',
            'v_lift': 'a fisherman lifts a heavy wooden crate from the quay stones up onto his '
            'shoulder, both hands under it',
            'v_open': 'a woman in a grey dress pushes a heavy wooden door open and steps through it',
            'v_pour': 'a man tips a metal jug and pours water into a wooden bucket until it is full',
            'v_turn': 'a seated man in a dark coat turns from facing the window to facing the camera',
            'v_throw': 'a man on a quay throws a coiled rope towards a moored boat and it uncoils through the air',
        },
        state_note=(
            'Six verbs x 3 seeds = 18 clips. The flow floor of 0.8 px/frame only rejects a '
            'clip that is effectively a still; the upper bound rejects a strobe. WHETHER the '
            'verb happened is an operator question, because no detector in the house scores '
            '"did he finish lifting it" — the 2026-09-27 defect bench put the best local VLM '
            'at 2/8 on hard cases and this is harder than those. Pouring and throwing are in '
            'the list because they are where a video model usually shows the beginning of an '
            'action and then loops it.'
        ),
    ),
    _p(
        'physics_p',
        'Weight, water and cloth behave',
        ['physics'],
        'VARIANT',
        [
            _op(
                'Watch only the physical behaviour, not the picture quality. Does everything in this '
                'clip move the way it would in the world — weight falls, water flows downward and '
                'settles, cloth and rope hang and swing from where they are held, nothing floats, '
                'slides or springs back on its own? yes/no'
            ),
            _op(
                'Does anything in this clip move in a way that is physically impossible? Answer yes if it does.',
                for_='invert',
            ),
        ],
        variants={
            'p_drop': "a wooden crate slips from a man's hands and falls to the quay stones, static camera",
            'p_water': 'water pours from a tipped bucket onto flat stones and spreads outward, '
            'static camera, close shot',
            'p_cloth': "a heavy woollen cloak hangs from a man's shoulders as he walks into a "
            'steady wind from his left',
        },
        state_note=(
            'Operator only, with no mechanical half, and the module says so plainly rather '
            'than inventing a detector: there is no physics scorer in this repo, and a flow '
            'statistic cannot tell a falling crate from a rising one. Three seeds each. The '
            'inverted second question catches the failures the first question\'s "everything" '
            'phrasing lets a generous viewer wave through.'
        ),
    ),
    # ── the two control levers ──────────────────────────────────────────────────────────
    _p(
        'camera_p',
        'A named camera move is executed',
        ['camera_ctl'],
        'VARIANT',
        [
            {'check': 'flow_direction', 'expect': 'EXPECT', 'share': 0.7, 'detector': DET_FLOW, 'mask': DET_SAM},
            _op(
                'The camera move this clip was asked for is shown beside it. Was that move performed — '
                'that move, in that direction, and no other? yes/no'
            ),
        ],
        variants={
            'c_left': 'static wide shot of a Dutch quay with three barrels, the camera pans slowly to the left',
            'c_in': 'a Dutch quay with three barrels and a moored boat, the camera pushes slowly in '
            'towards the barrels',
            'c_up': 'the brick facade of a canal house, the camera tilts slowly upward from the door to the gable',
            'c_lock': 'a locked-off static shot of a Dutch quay, the camera does not move at all, a '
            'gull walks across the stones',
        },
        variant_expect={'c_left': 'right', 'c_in': 'in', 'c_up': 'down', 'c_lock': 'none'},
        state_note=(
            'Flow is measured on the BACKGROUND, outside the SAM2 subject mask, so the gull '
            'in c_lock cannot be read as a pan. The expected flow direction is the OPPOSITE '
            'of the camera move for a pan or tilt (a camera panning left pushes the scene '
            'right), which is why variant_expect looks inverted and is written out per '
            'variant instead of derived. Endpoint ORB affine is deliberately not used: on '
            'house measurements it reports the wrong SIGN on a push-in or a dive once frame '
            '0 and the last frame stop overlapping. c_lock is the control — a row that '
            'drifts when told to lock off cannot be trusted on any of the other three.'
        ),
    ),
    _p(
        'scene_p',
        'The place the prompt names is built and held',
        ['scene_ctl'],
        'VARIANT',
        [
            {
                'check': 'operator',
                'blind': True,
                'question': 'The place this clip was asked for is written beside it — the setting, the time '
                'of day and the weather. Are all three right, and do they stay the same from '
                'the first frame to the last? yes/no',
            },
            {'check': 'ssim_min', 'a': 0, 'b': -1, 'min': 0.35},
        ],
        variants={
            's_interior': 'the interior of a 17th-century Dutch tavern at night, lit by candles and '
            'a fire, rain on the small windows, nobody in the room',
            's_exterior': 'a 17th-century Dutch harbour at midday in bright summer sun, calm water, '
            'moored fishing boats, nobody on the quay',
            's_weather': 'a 17th-century Dutch quay in heavy rain and grey overcast light, puddles '
            'on the stones, nobody on the quay',
        },
        state_note=(
            'Every variant is deliberately EMPTY of people so the column measures the place '
            'and not a performance. SSIM 0.35 between the first and last frame is a loose '
            'floor and is only there to catch a clip that changes location mid-way — rain '
            'and firelight legitimately drive SSIM down, so a tight bar here would punish '
            'the very weather the prompt asked for.'
        ),
    ),
    _p(
        'style_p',
        'A named visual style is applied without breaking the scene',
        ['style_video'],
        'VARIANT',
        [
            {
                'check': 'operator_choice',
                'options': ['oil painting', 'ink drawing', 'photographic', 'none of these'],
                'answer': 'ANSWER',
                'blind': True,
                'question': 'Which of these best describes how this clip looks? oil painting / ink drawing '
                '/ photographic / none of these.',
            },
            _op(
                'Whatever its style, does this clip still show the scene the prompt described, with the '
                'style applied evenly and steadily rather than drifting or flickering between looks? '
                'yes/no'
            ),
        ],
        variants={
            'st_oil': 'a 17th-century Dutch quay with three barrels, in the style of a Dutch Golden '
            'Age oil painting, visible brushwork, warm varnished tones',
            'st_ink': 'a 17th-century Dutch quay with three barrels, as a black ink line drawing on '
            'cream paper, no colour',
            'st_photo': 'a 17th-century Dutch quay with three barrels, photorealistic, natural '
            'daylight, shot on a 35mm lens',
        },
        variant_answer={'st_oil': 'oil painting', 'st_ink': 'ink drawing', 'st_photo': 'photographic'},
        state_note=(
            'A forced choice out of four, not "is this an oil painting?" — the yes/no form '
            'hands the viewer the answer and every style scores yes. "none of these" is an '
            'available answer so a clip that landed in no recognisable style scores 0 rather '
            'than being forced into the nearest box. The second check is what stops a row '
            'winning the column by abandoning the quay to make a pretty painting.'
        ),
    ),
    # ── the envelope ────────────────────────────────────────────────────────────────────
    _p(
        'len_ladder',
        'How many frames stay usable',
        ['length'],
        'a fisherman in a brown coat walks slowly along a wooden quay past three barrels, static '
        'camera, grey morning light',
        [
            _op(
                'Does this clip stay usable all the way to its final frame — the man still one man, the '
                'quay still the same quay, no collapse, no loop back to the start, no freeze? yes/no'
            ),
            {'check': 'flicker_max', 'max': 0.035},
            {'check': 'identity_cosine_min', 'a': 0, 'b': -1, 'min': 0.35, 'detector': DET_ARC},
        ],
        inputs_ladder=True,
        conditions=dict(COND, ladder=[81, 121, 161], repeats=3, note='one clip per rung per seed; frames is the rung'),
        state_rule=LADDER,
        state_note=(
            'The answer is the LAST RUNG that passes, in FRAMES — 81, 121, 161 or none — not a '
            'yes/no, and all three rungs are kept so the reader sees where it went. Frames '
            'and not seconds because the house writes 17 fps into the container while the '
            'card says 16 (see res_video); a rung expressed in seconds would mean two '
            'different lengths depending on which you believed. 161 frames is two chained '
            'windows on this path, so a failure at 161 that passes at 121 is a seam finding '
            'and the trial says which frame it appeared at.'
        ),
    ),
    _p(
        'coherence',
        'Nothing flickers and nothing morphs',
        ['flicker', 'morph'],
        MAARTEN + ', walking slowly towards the camera along a wooden quay, grey morning light, static camera',
        [
            {'check': 'flicker_max', 'max': 0.035, 'for': 'flicker'},
            _op(
                'Watch the flat areas — the coat, the stones, the sky. Does the brightness or texture '
                'buzz, pulse or crawl from frame to frame? Answer yes if it does.',
                for_='invert',
            ),
            {'check': 'identity_cosine_min', 'a': 0, 'b': -1, 'min': 0.35, 'detector': DET_ARC, 'for': 'morph'},
            _op(
                'Does any object or body part in this clip change into something else, swap places, '
                'grow, shrink, or drift into a different shape as the clip runs? Answer yes if it does.',
                for_='invert',
            ),
        ],
        state_note=(
            'Two columns from one clip, read differently: the first pair is per-frame-pair '
            'luma (flicker), the second is across the whole clip (morph). The 0.035 flicker '
            'ceiling is on luma delta after global brightness is normalised out, so a '
            'legitimate change of light is not counted as buzz. Both operator questions are '
            'inverted on purpose and the runner flips them once.'
        ),
    ),
    _p(
        'hands_p',
        'Hands survive motion',
        ['hands_video'],
        "close shot of a fisherman's hands coiling a thick rope on a wooden quay, both hands "
        'visible throughout, daylight',
        [
            {
                'check': 'operator',
                'blind': True,
                'question': 'Look only at the hands. Across this whole clip, does every visible hand keep '
                'five fingers, with no finger fusing into another, no extra finger appearing '
                'and no hand melting into the rope? yes/no',
            },
            {
                'check': 'operator',
                'blind': True,
                'question': "Pause on any single frame of this clip. Is that frame's hand anatomy correct "
                'on its own? yes/no',
            },
        ],
        detectors_note=(
            'MediaPipe hand_landmarker (anatomy_qc.py) runs on the five frames in '
            'SAMPLE5 and its per-frame landmark count and finger-separation figures are '
            "written into the trial beside the operator's answers. It is NOT a check "
            'here and does not score the column: on the 2026-09-27 bench the detectors '
            'found 2/8 of the hard fused-finger cases, so the operator decides and the '
            'detector output is evidence the reader can weigh. The second question is '
            'asked separately because a clip can be right in every still frame and wrong '
            'in motion, and the cell should be able to say which.'
        ),
        state_note='3 clips, 3 seeds. Both questions must pass for the column to read yes.',
    ),
    # ── two columns nothing else can answer ─────────────────────────────────────────────
    _p(
        'continuity',
        'Two consecutive prompts cut together',
        ['continuity_shot'],
        'PAIR',
        [
            {'check': 'ssim_min', 'a': -1, 'a_of': 'continuity#A', 'b': 0, 'b_of': 'continuity#B', 'min': 0.45},
            {
                'check': 'identity_cosine_across',
                'across': ['continuity#A', 'continuity#B'],
                'frame': -1,
                'min': 0.35,
                'detector': DET_ARC,
            },
            {
                'check': 'operator',
                'blind': True,
                'question': 'These two clips are meant to be consecutive shots of one scene, cut together '
                'at the join. Watching them play through the cut: is it the same man, in the '
                'same clothes, in the same place, at the same time of day? yes/no',
            },
        ],
        pair={
            'A': MAARTEN + ', standing at the end of a wooden quay in grey morning light, looking out '
            'at the water, he turns to face the camera',
            'B': MAARTEN + ', standing at the end of a wooden quay in grey morning light, facing the '
            'camera, he walks towards it and past it',
        },
        conditions=dict(COND, note='clip A and clip B at the same seed; 3 seeds = 3 pairs = 6 clips'),
        state_note=(
            'The two prompts are byte-identical up to the action, which is the easiest form '
            'of this task — if a row cannot hold continuity here it cannot hold it anywhere. '
            "The mechanical pair is A's LAST frame against B's FIRST (SSIM 0.45, a loose "
            'bar for two independent samplings of one description) plus an ArcFace cosine '
            'between the two faces. The operator decides, because same-place is a judgement '
            'no house detector makes.'
        ),
    ),
    _p(
        'period_p',
        'No anachronism in a period scene',
        ['period_video'],
        'a busy 17th-century Dutch quay in the morning, fishermen unloading crates from a moored '
        'boat, barrels and coiled rope on the stones, brick warehouses behind',
        [
            {'check': 'era_gate_clean', 'period': '17th-century Dutch', 'sample': SAMPLE5, 'share': 1.0},
            {
                'check': 'operator',
                'blind': True,
                'question': 'This clip is meant to be a 17th-century Dutch harbour. Is there anything in it '
                'that did not exist then — printed lettering or signage, modern clothing, '
                'plastic, metal railings, a vehicle, a wire, a wristwatch? Answer yes if there '
                'is.',
                'for': 'invert',
            },
        ],
        state_note=(
            'era_gate.py crops each sampled frame and spends ONE Haiku call per batch to list '
            'the checkable objects before judging them, so this is the only probe in the '
            'module that costs language tokens and the only reason this test touches the '
            'shared Claude week at all — the budget counts it. share 1.0 means a single '
            'flagged frame fails the trial: an anachronism in one frame of five is in the '
            'clip. The operator question runs anyway because the gate only judges what its '
            'extraction step happened to name.'
        ),
    ),
]

TEST = {
    'step': 't2v',
    'version': '2026-09-30.1',
    'title': 'One engine, no input still: what a prompt alone can and cannot hold',
    'purpose': (
        'Measure the fourteen columns the shared video bank leaves to this step on the one '
        'T2V row, including the ones expected to fail — identity from a written description '
        'is measured as a cross-seed ArcFace cosine rather than left blank, so the sheet '
        'carries the number instead of the assumption.'
    ),
    'include_shared': 'video',
    'rows': {
        'wan21_t2v': {
            'transport': 'comfy',
            'where': (
                'ComfyUI diffusion_models/Wan2_1-T2V-14B_fp8_e4m3fn.safetensors at 832x480 '
                '(wan_video_service._WIDTH/_HEIGHT defaults, ZYG_WAN_ATTENTION=sdpa, the '
                'production default). Workflow: see `fixtures` — there is no T2V graph in '
                '_comfy_workflows/ as of 2026-09-30 and one must be made before the run.'
            ),
            'model': 'Wan2.1 T2V 14B, fp8_e4m3fn quantisation',
            'note': (
                'Text-to-video only: no image node, no reference, no LoRA. ZYG_WAN_TIMEOUT_S '
                'defaults to 900 s and a 161-frame rung at 30 steps will exceed it, so it must '
                'be raised before len_ladder runs or those clips are interrupted mid-sampler '
                'and the GPU time is lost with nothing written.'
            ),
        },
    },
    'probes': PROBES,
    'derive': {},
    'lookup': {
        'res_video': {
            'grade': 'receipt',
            'requires': (
                'four things, all recorded in the cell: (1) the resolutions the T2V 14B '
                'checkpoint was trained at, from the model card at a pinned revision; (2) '
                'the ZYG_WAN_WIDTH / ZYG_WAN_HEIGHT the row actually ran with (832x480 by '
                'default, wan_video_service._WIDTH/_HEIGHT); (3) ffprobe width x height '
                'and frame count on a clip this test produced; (4) the frame rate written '
                'into that container.'
            ),
            'note': (
                '(4) is the trap this cell exists to publish: the card says 16 fps and '
                'wan_video_service._CLIP_FPS is 17 (line 39, labelled "WAN native generation '
                'framerate"), so an 81-frame clip is 5.06 s or 4.76 s depending on which you '
                'believe. Both numbers with their source go in the cell. Every length '
                'statement elsewhere in this test is in frames for exactly this reason.'
            ),
        },
    },
    'wiring': {},
    'na': {},
    'fixtures': [
        {
            'path': '_comfy_workflows/wan_t2v.json',
            'verified': False,
            'blocks': [
                'prompt',
                'identity',
                'motion',
                'physics',
                'camera_ctl',
                'scene_ctl',
                'style_video',
                'length',
                'flicker',
                'morph',
                'hands_video',
                'continuity_shot',
                'period_video',
            ],
            'generated': (
                'copy _comfy_workflows/wan_i2v.json to wan_t2v.json and remove the image '
                'branch: the LoadImage node, the WanImageToVideo (or CLIPVisionEncode + '
                'image embed) node and the image input on the sampler, leaving the T2V '
                'checkpoint loader, the two CLIPTextEncode nodes (positive and the NEGATIVE '
                'string in this module), the empty latent at 832x480x81, the KSampler at 30 '
                'steps / cfg 6.0 / uni_pc+simple, the VAE decode and the video save. Swap '
                'the checkpoint to Wan2_1-T2V-14B_fp8_e4m3fn.safetensors. Nothing in the '
                'task that wrote this test created the file.'
            ),
            'how_to_verify': (
                'queue the graph once at seed 11 on the shortest prompt in this module '
                'and confirm: it completes without a node error, the output is 81 frames '
                'at 832x480, no image node remains in the graph JSON, and the negative '
                'prompt in the saved workflow is byte-identical to NEGATIVE here. Then '
                "set verified = true and record the graph's sha256 — every trial cites "
                'it, and a changed graph is a different test.'
            ),
            'blocks_note': (
                'every probe column is blocked, because without the graph there is no way '
                'to run this row at all. res_video is not blocked: it is a lookup whose '
                'card and code halves can be filled before anything renders, and its '
                'ffprobe half is written when the first clip exists.'
            ),
        },
    ],
    'budget': {
        'calls': 1055,
        'tokens_in': 4500,
        'tokens_out': 1500,
        'minutes': 15900,
        'gpu_minutes': 15825,
        'operator_minutes': 706,
        'note': (
            'CLIPS = 1055 for the one row. The SHARED VIDEO BANK is 958 of them: 396 subject clips '
            '(132 subjects x 3 seeds — ONE clip answers BOTH render_<id> and move_<id>, read at '
            "frame 0 and the last frame for render and across the clip for move; the bank's own "
            'SUBJ_NOTE says so, which is why this is 396 and not 792), 288 ladder rungs, 27 '
            'prompt-grid cells, 223 scene and prompt-variant clips and ~24 second clips for the '
            'paired probes. THIS MODULE adds 97: prompt_obeyed 3, id_from_words 3, motion_verb 18 '
            '(6 verbs x 3), physics_p 9 (3 x 3), camera_p 12 (4 x 3), scene_p 9 (3 x 3), style_p 9 '
            '(3 x 3), len_ladder 9 (3 rungs x 3), coherence 3, hands_p 3, continuity 6 (3 pairs), '
            'period_p 3, and 10 clips of headroom for re-renders when a clip comes back empty. '
            'TIME PER CLIP at 832x480 / 81 frames / 30 steps: ~15 min. That is arithmetic from a '
            'house measurement, not a guess — 53 frames at 832x480 and 20 steps took 390 s and 45 '
            'frames took 330 s (2026-09-15), i.e. 0.368 s per frame per step, so 81 x 30 x 0.368 = '
            '894 s; Wan attention is quadratic in frames so 894 s is a FLOOR and the 161-frame '
            'rungs cost more than proportionally. 1055 x 15 min = 15,825 GPU minutes = 264 GPU '
            'HOURS, i.e. ELEVEN DAYS of one 24 GB card held continuously, plus ~75 min of wall '
            'clock for model loads and queue. ZYG_WAN_ATTENTION=sageattn would cut ~35-40 % to '
            '~165 h but sdpa is what ships and this test measures what ships. The commissioning '
            'estimate for this step was 10-20 GPU hours at 90-180 s per clip; the measured figure '
            "is ~15x that, and the only honest levers are the bank's seed count or its subject "
            'count — both of which change the test hash and make the result incomparable to i2v. '
            'Quietly dropping steps is not a lever. `run_order` exists so that a run stopped early '
            'has still filled whole columns. TOKENS: era_gate.py alone, one Haiku call per batch of '
            'crops, 3 clips x 5 frames = 15 crops in ~3 batches per seed set, ~1,500 in / ~500 out '
            'per batch = ~4,500 in / ~1,500 out for the row. That is small but it is NOT zero and '
            'it spends the SHARED CLAUDE WEEK: if the week is exhausted, period_video is untested '
            'with the quota refusal as its note and no other column is affected. OPERATOR: 1,291 '
            'blind decisions from the bank (2 per subject clip = 792, one per ladder rung = 288, '
            'the rest from scenes and prompt variants) plus ~121 from this module (two questions on '
            'several probes, and a three-way forced choice on id_from_words and style_p) = ~1,412 '
            'at 30 s = 706 minutes = ~11.8 operator hours. ONE-OFF, not per clip: building and '
            'verifying wan_t2v.json, ~20 min, and until it is done every probe column is BLOCKED.'
        ),
    },
    'run_order': [
        'period_p',
        'coherence',
        'hands_p',
        'prompt_obeyed',
        'id_from_words',
        'continuity',
        'style_p',
        'scene_p',
        'camera_p',
        'physics_p',
        'motion_verb',
        'len_ladder',
        'shared:counting',
        'shared:spatial',
        'shared:attributes',
        'shared:prompt',
        'shared:capacity',
        'shared:subjects',
        'ORDER RULE: the cheapest and most diagnostic first. period_p, coherence and hands_p are 3 '
        'clips each and will expose a broken wan_t2v.json in the first hour; prompt_obeyed and '
        'id_from_words are the two columns this sheet is actually about and are 3 clips each, so '
        'they are answered before a day of GPU has been spent. The multi-variant probes follow in '
        'ascending clip count, len_ladder is last of this module because its 161-frame rungs are '
        'the most expensive clips in the test, and the 396-clip subject bank is last of all. A run '
        'stopped anywhere down this list has filled whole columns instead of a scatter of cells.',
    ],
    'notes': [
        'identity is expected to read `no` and is written to produce the NUMBER anyway. A prompt is '
        'not an identity: the same description on three seeds gives three faces, and the cell that '
        'says "no, cross-seed cosine 0.11, within-clip 0.62" tells a reader both that this step '
        'cannot cast a character and that it can hold one for 81 frames. That is why the within- '
        'and across-seed checks live in one probe with state_rule partial at 1/3.',
        'There is no T2V workflow JSON in the repo as of 2026-09-30. It is declared as a fixture '
        'with the exact edit that makes it, verified False, and it blocks every probe column until '
        'someone builds it and records its sha256. Nothing in the task that wrote this test created '
        'any file under _comfy_workflows.',
        'Lengths are in FRAMES throughout, never seconds, because wan_video_service._CLIP_FPS = 17 '
        "disagrees with the model card's 16 fps. res_video publishes the pair; until that is "
        'settled, a "5-second clip" is not a well-defined object in this house.',
        'physics is operator-only and the module says so instead of dressing a flow statistic up as '
        'a physics scorer. There is no physics detector in this repo, mean optical flow cannot tell '
        'a falling crate from a rising one, and the 2026-09-27 defect bench put the best local VLM '
        'at 2/8 on hard cases. Where only a human can decide, the check is blind, the question is '
        'written here, and the cell is honest about which one decided.',
        'Where a viewer could be led by the question, the check is a forced choice out of N '
        '(operator_choice) rather than yes/no: "is this the same man?" and "is this an oil '
        'painting?" both agree with themselves. Four inverted yes/no questions exist as well, and '
        'the runner flips each exactly once and records that it did.',
        'The camera column uses background flow outside a SAM2 subject mask, not endpoint ORB '
        'affine. On house measurements the endpoint method reports the wrong sign on a push-in or a '
        'dive as soon as frame 0 and the last frame stop overlapping — a 23 % push-in measured '
        '1.0352 endpoint against 1.2267 accumulated, and a dive measured +0.744 against -0.6801.',
    ],
}
