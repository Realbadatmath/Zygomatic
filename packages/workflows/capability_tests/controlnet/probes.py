# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""PROBES — the fifteen measured probes, in sheet order.

Moved verbatim out of the old single-file controlnet.py (lines 181-597).
"""

from __future__ import annotations

from capability_tests.controlnet.constants import (
    AGREE,
    BEAUTY,
    BROKEN,
    DEPTH_MIN,
    EDGE_MIN,
    GARBAGE,
    MAPS,
    MASK,
    NORMAL_MAX,
    OP_LOUD,
    OP_POSE,
    POSE_MAX,
    PROMPT,
    PROMPT_STYLE,
    RULE_STRICT,
    SEG_MIN,
    TRUTH,
    _cond,
    _p,
)


PROBES = [
    # ── does it constrain at all ──
    _p(
        'cn_constrains',
        'The mannequin plate, re-extracted from the render and compared with itself',
        ['constrains'],
        PROMPT,
        [
            dict(AGREE),
            {
                'check': 'pose_keypoint_error_max',
                'max': POSE_MAX,
                'note': 'scored on every row, not only the pose rows: a depth plate of a standing figure fixes the '
                'limb positions too, and MediaPipe gives the same ruler for all five rows',
            },
            {'check': 'operator', 'question': OP_POSE},
        ],
        cond=_cond(
            control={'channel': "the row's own", 'map': 'the matching plate in MAPS', 'strength': 'production default'}
        ),
        run_order=3,
        state_note="THE column of this sheet. 3 seeds x the row's own channel. The mechanical number decides the "
        'state; the blind operator rate goes in the note beside it, because a render can hit 0.82 '
        'Spearman on depth and still not read as the same pose to a human, and the sheet should show '
        'when the two disagree rather than pick one.',
    ),
    _p(
        'cn_garbage_in',
        'A control extracted from an old low-quality picture — the standing lesson',
        ['garbage_in'],
        PROMPT,
        [
            dict(AGREE),
            {'check': 'pose_keypoint_error_max', 'max': POSE_MAX},
            {'check': 'operator', 'question': OP_POSE},
            {'check': 'operator', 'question': OP_LOUD},
        ],
        cond=_cond(control={'channel': 'depth', 'map': GARBAGE, 'strength': 'production default'}),
        run_order=4,
        state_note='The sheet already records this as a measured NO and the fix that followed was to rebuild the '
        'source pictures, not to tune the control. Two operator questions, deliberately: a row that '
        'fails LOUDLY (a visibly broken figure a gate would catch) is a partial, and a row that '
        'produces a plausible picture of the wrong pose is a NO — the expensive failure. A yes here '
        'would be news and would need the trials read by hand before anyone believed it.',
    ),
    _p(
        'cn_strength',
        'The strength lever: is it calibrated or decorative',
        ['strength'],
        PROMPT,
        [
            {
                'check': 'monotone_in_ladder',
                'metric': "control_agreement_min on the row's own channel",
                'ladder': [0.2, 0.4, 0.6, 0.8, 1.0],
                'min_rho': 0.8,
                'min_span': 0.25,
            },
            {
                'check': 'operator',
                'question': 'Laid out left to right, do these five pictures move steadily from '
                'loosely following the control map towards following it closely — '
                'rather than jumping about or all looking the same?',
            },
        ],
        cond=_cond(
            control={
                'channel': "the row's own",
                'map': 'the matching plate in MAPS',
                'strength_ladder': [0.2, 0.4, 0.6, 0.8, 1.0],
            },
            seeds=[11],
            repeats=3,
            note='ONE seed across the ladder: the rungs must differ because of the lever, not because of '
            'the noise. Three repeats of the whole ladder at that seed.',
        ),
        state_rule=dict(RULE_STRICT),
        run_order=5,
        state_note='15 renders (5 rungs x 3 repeats). Strict: the ladder must be monotone in all 3 repeats. A '
        "flat ladder is this step's form of the 2026-09-23 never-applied defect and reads no, with "
        'the measured span in the note so the operator can see how flat.',
    ),
    _p(
        'cn_end_step',
        'The end-step lever: where the control lets go',
        ['end_step'],
        PROMPT,
        [
            {
                'check': 'monotone_in_ladder',
                'metric': "control_agreement_min on the row's own channel",
                'ladder': [0.2, 0.4, 0.6, 0.8, 1.0],
                'min_rho': 0.8,
                'min_span': 0.20,
            },
            {
                'check': 'operator',
                'question': 'Laid out left to right, do these five pictures move steadily from '
                'loosely following the control map towards following it closely?',
            },
        ],
        cond=_cond(
            control={
                'channel': "the row's own",
                'map': 'the matching plate in MAPS',
                'strength': 'production default',
                'end_percent_ladder': [0.2, 0.4, 0.6, 0.8, 1.0],
            },
            seeds=[11],
            repeats=3,
            note='one seed, the strength held at the production default, only end_percent moves',
        ),
        state_rule=dict(RULE_STRICT),
        run_order=6,
        state_note="The span threshold is lower than the strength ladder's on purpose: releasing the control "
        'late in the schedule legitimately changes the picture less than halving its weight. A row '
        'whose workflow exposes no end-step control at all is a transport failure on this probe and '
        'the runner writes untested with that error, which is the true answer.',
    ),
    _p(
        'cn_combine',
        'Depth and pose together',
        ['combine'],
        PROMPT,
        [
            {
                'check': 'control_agreement_min',
                'channel': 'depth',
                'depth_min': DEPTH_MIN,
                'edge_min': EDGE_MIN,
                'normal_max': NORMAL_MAX,
                'seg_min': SEG_MIN,
            },
            {
                'check': 'pose_keypoint_error_max',
                'max': POSE_MAX,
                'note': 'BOTH must hold at once. A stack that honours depth and loses the pose is a partial, and the '
                'note records which channel was dropped — that is the useful half of this column',
            },
            {'check': 'operator', 'question': OP_POSE},
        ],
        cond=_cond(
            control={
                'channels': ['depth', 'pose'],
                'maps': [MAPS['depth'], MAPS['pose']],
                'strength': 'production default on each, unchanged from the single-control trials',
            }
        ),
        state_rule=dict(RULE_STRICT),
        run_order=7,
        state_note='Two ControlNet nodes in one workflow for the SDXL rows (the depth checkpoint and the pose '
        'checkpoint stacked); two modes of one model for the union row. The comparison across rows is '
        'therefore between architectures, and the note must say which arrangement ran.',
    ),
    # ── which conditions ──
    _p(
        'cn_depth_ok',
        'Depth conditioning',
        ['depth_ok'],
        PROMPT,
        [
            {
                'check': 'control_agreement_min',
                'channel': 'depth',
                'depth_min': DEPTH_MIN,
                'edge_min': EDGE_MIN,
                'normal_max': NORMAL_MAX,
                'seg_min': SEG_MIN,
            },
            {'check': 'operator', 'question': OP_POSE},
        ],
        cond=_cond(control={'channel': 'depth', 'map': MAPS['depth'], 'strength': 'production default'}),
        run_order=8,
        state_note='The plate is RENDERED depth (near = white, normalised over the object range, not the whole '
        'frame — sky at 1e10 would otherwise crush everything into one value), so there is no '
        'estimator error in the input to explain a poor score away with.',
    ),
    _p(
        'cn_pose_ok',
        'Pose conditioning',
        ['pose_ok'],
        PROMPT,
        [{'check': 'pose_keypoint_error_max', 'max': POSE_MAX}, {'check': 'operator', 'question': OP_POSE}],
        cond=_cond(control={'channel': 'pose', 'map': MAPS['pose'], 'strength': 'production default'}),
        run_order=9,
        state_note="The plate is the house cascade's 33-point skeleton drawn in the OpenPose colour convention "
        '(geom/char_control.py). No NC OpenPose model is loaded to make it and none is loaded to '
        'score it: MediaPipe pose_landmarker re-extracts the joints from the render.',
    ),
    _p(
        'cn_edge_ok',
        'Edge / canny / lineart conditioning',
        ['edge_ok'],
        PROMPT,
        [
            {
                'check': 'control_agreement_min',
                'channel': 'edge',
                'depth_min': DEPTH_MIN,
                'edge_min': EDGE_MIN,
                'normal_max': NORMAL_MAX,
                'seg_min': SEG_MIN,
            },
            {
                'check': 'operator',
                'question': 'Do the outlines in this picture follow the lines of the control map shown beside it?',
            },
        ],
        cond=_cond(control={'channel': 'edge', 'map': MAPS['edge'], 'strength': 'production default'}),
        run_order=10,
        state_note='The lineart plate is edges from DEPTH AND NORMAL DISCONTINUITY, not image gradients: an '
        'image-space detector fires on bark texture and on the boundary between a light and a dark '
        'patch of one flat surface, a geometric one only where the surface actually turns or steps.',
    ),
    _p(
        'cn_normal_ok',
        'Normal-map conditioning',
        ['normal_ok'],
        PROMPT,
        [
            {
                'check': 'control_agreement_min',
                'channel': 'normal',
                'depth_min': DEPTH_MIN,
                'edge_min': EDGE_MIN,
                'normal_max': NORMAL_MAX,
                'seg_min': SEG_MIN,
            },
            {
                'check': 'operator',
                'question': 'Do the surfaces in this picture face the way the normal map beside '
                'it says they do — is the body turned the same way?',
            },
        ],
        cond=_cond(control={'channel': 'normal', 'map': MAPS['normal'], 'strength': 'production default'}),
        run_order=11,
        state_note='Camera-space, (n * 0.5 + 0.5) * 255, the ControlNet/normalBAE convention. NO ESTIMATOR IN '
        'THIS PIPELINE PROVIDES NORMALS AT ALL, which is why the rendered plate is the only way this '
        'column can be asked honestly.',
    ),
    _p(
        'cn_seg_ok',
        'Segmentation conditioning',
        ['seg_ok'],
        PROMPT,
        [
            {
                'check': 'control_agreement_min',
                'channel': 'seg',
                'depth_min': DEPTH_MIN,
                'edge_min': EDGE_MIN,
                'normal_max': NORMAL_MAX,
                'seg_min': SEG_MIN,
            },
            {
                'check': 'operator',
                'question': 'Do the parts of this picture sit where the coloured regions of the '
                'map beside it say they sit?',
            },
        ],
        cond=_cond(control={'channel': 'seg', 'map': MAPS['seg'], 'strength': 'production default'}),
        run_order=12,
        state_note='One flat colour per object index, from the IndexOB pass — a region map, not a person-blob.',
    ),
    _p(
        'cn_scribble_ok',
        'Scribble conditioning',
        ['scribble_ok'],
        PROMPT,
        [
            {
                'check': 'control_agreement_min',
                'channel': 'scribble',
                'depth_min': DEPTH_MIN,
                'edge_min': 0.25,
                'normal_max': NORMAL_MAX,
                'seg_min': SEG_MIN,
                'note': 'a LOWER edge IoU than cn_edge_ok on purpose: a scribble is a loose sketch and a render that '
                'traced it exactly would mean the model had stopped interpreting',
            },
            {
                'check': 'operator',
                'question': 'Does the figure in this picture have the same rough shape and limb '
                'layout as the sketch beside it?',
            },
        ],
        cond=_cond(control={'channel': 'scribble', 'map': MAPS['scribble'], 'strength': 'production default'}),
        run_order=13,
    ),
    _p(
        'cn_inpaint_ok',
        'Inpaint conditioning: the masked hand, and only the masked hand',
        ['inpaint_ok'],
        'the right hand of a Dutch shipwright, five fingers, gripping a wooden mallet handle, 1671',
        [
            {
                'check': 'mask_outside_unchanged',
                'max': 2.0,
                'note': '2 levels out of 255 is VAE round-trip noise; anything more is a repaint of the frame',
            },
            {
                'check': 'hand_landmarks',
                'hands': 1,
                'note': 'MediaPipe hand_landmarker: exactly one hand, 21 landmarks, 5 fingertips. The only mechanical '
                'fingers detector this house trusts — and on the 2026-09-27 bench the local VLMs scored 2/8 '
                'on exactly this question, which is why it is not asked of one',
            },
            {
                'check': 'operator',
                'question': 'Does this hand have five fingers, none fused or missing, and does '
                'the patch join the arm without a visible seam?',
            },
        ],
        cond=_cond(control={'channel': 'inpaint', 'image': BROKEN, 'mask': MASK, 'strength': 'production default'}),
        run_order=14,
        state_note='The fixture is the mannequin render with a deliberately broken hand and the hand mask the '
        'hand_qc path produces. Three checks, three different failures: repainting the frame, getting '
        'the fingers wrong, and a visible seam — each on its own so the note says which one happened.',
    ),
    _p(
        'cn_ref_ok',
        'Reference conditioning',
        ['ref_ok'],
        PROMPT,
        [
            {
                'check': 'image_distance',
                'metric': 'lpips',
                'to': BEAUTY,
                'max': 0.45,
                'note': 'close to the reference in structure and palette, and not a copy of it: the pair-must-differ '
                'floor is the second check',
            },
            {
                'check': 'image_distance',
                'metric': 'lpips',
                'to': BEAUTY,
                'min': 0.05,
                'note': 'a reference control that returns the reference has conditioned nothing',
            },
            {
                'check': 'operator',
                'question': 'Does this picture look like it came from the same scene, light and '
                'palette as the reference beside it, without being a copy of it?',
            },
        ],
        cond=_cond(control={'channel': 'reference', 'image': BEAUTY, 'strength': 'production default'}),
        run_order=15,
        state_note='Two thresholds on one distance, which is how a band is written as checks: 2/2 = yes, 1/2 = '
        'partial (either too far from the reference or too close to it), 0/2 = no.',
    ),
    # ── the inputs ──
    _p(
        'cn_extract_quality',
        "Is the extracted control itself accurate — measured against the renderer's truth",
        ['extract_quality'],
        PROMPT,
        [
            {
                'check': 'control_map_error_max',
                'truth': TRUTH,
                'depth_max': 0.03,
                'pose_max': 0.02,
                'note': 'the renderer wrote the exact Z buffer and the exact joint positions for this frame, so the '
                'extractor can be measured rather than believed',
            },
            {
                'check': 'operator',
                'question': 'Laid beside the beauty render, does this control map describe the '
                'same figure in the same position — nothing missing, nothing added?',
            },
        ],
        cond=_cond(
            control={'channel': "the row's own", 'map': 'the matching plate in MAPS', 'truth': TRUTH},
            repeats=3,
            note="the extraction is deterministic, so the three repeats test the extractor's stability, "
            "not the sampler's",
        ),
        run_order=1,
        state_note='RUNS FIRST and costs no sampler: it decides whether the ruler is straight. For the rows whose '
        'control comes from geom/conditioning.py the map is read out of render passes and the error '
        'should be near zero; a row whose production path ESTIMATES its control from a picture is '
        'measured here against the same truth and that gap is the finding.',
    ),
    _p(
        'cn_overpower',
        'Does the control flatten the style',
        ['overpower'],
        PROMPT_STYLE,
        [
            {
                'check': 'operator',
                'question': 'Does this picture still carry the painterly style — teal palette, '
                'visible brush texture — or does it look like a plain rendering that '
                'happens to be in the right pose?',
            },
            {
                'check': 'image_distance',
                'metric': 'lpips',
                'to': 'cn_overpower_nostyle',
                'min': 0.20,
                'note': 'the styled render at strength 1.0 must still differ from the unstyled render at strength 1.0, '
                'or the control has eaten the style entirely',
            },
            dict(AGREE),
        ],
        cond=_cond(
            control={'channel': "the row's own", 'map': 'the matching plate in MAPS', 'strength': 1.0},
            ab={'styled': PROMPT_STYLE, 'nostyle': PROMPT},
            note='strength pinned at 1.0 — the worst case, where a control is most likely to flatten everything else',
        ),
        run_order=16,
        state_note='At strength 1.0 on purpose. The agreement check is included so a row cannot win this column '
        'by ignoring the control: keeping the style AND the pose is the yes, keeping the style by '
        'dropping the pose is a no with that reason in the note.',
    ),
]
