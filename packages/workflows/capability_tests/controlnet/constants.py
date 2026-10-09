# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Check kinds, the one control set, the prompt, the conditions and the thresholds.

Moved verbatim out of the old single-file controlnet.py (lines 47-179).
"""

from __future__ import annotations

__name__ = __package__  # the moved code's home module, so `_cond.__module__` is unchanged


# ── check kinds this step needs and the base vocabulary does not have ──────────────────────
CHECK_KINDS = {
    'control_agreement_min': (
        "the row's own control channel is RE-EXTRACTED from the render and compared with the map that was "
        'fed in, over the subject mask: depth = Spearman rho >= `depth_min` (re-extraction by the pinned '
        'Apache-2.0 Depth-Anything-V2-Small, the checkpoint 2026-08-03 settled on); lineart/canny/scribble = '
        'IoU of 3-px-dilated edge maps >= `edge_min`; normal = mean angular error <= `normal_max` degrees; '
        'segmentation = mean per-region IoU >= `seg_min`. The `channel` field names which one this trial scores; '
        'a channel the row has no head for makes the check untested, not a no.'
    ),
    'pose_keypoint_error_max': (
        'MediaPipe pose_landmarker (pinned task file) on the render; the mean L2 distance of the joints the '
        'control map also carries, normalised by image height, is <= `max`. Joints the map does not carry are '
        'excluded rather than scored as zero error. A render with no detected person is a FAIL, not untested — '
        'a pose control that produces no person did not constrain anything.'
    ),
    'control_map_error_max': (
        'the extracted control map is compared with the GROUND TRUTH the renderer wrote for the same frame '
        '(`truth`, the exact Z buffer and joint positions of the mannequin): depth = mean absolute error over '
        'the subject mask <= `depth_max` of the normalised range; pose = mean joint L2 normalised by image '
        'height <= `pose_max`. This measures the EXTRACTOR, not the model, which is why it needs a rendered '
        'subject: a photograph has no truth to compare to.'
    ),
    'monotone_in_ladder': (
        'the quantity named in `metric` (the same number control_agreement_min computes) moves monotonically '
        'across the `ladder` values with Spearman rho >= `min_rho`, AND the span between the lowest and highest '
        'rung is at least `min_span`. A lever that changes the number randomly, or not at all, is not calibrated: '
        'a flat ladder is the ControlNet form of the never-applied defect.'
    ),
    'mask_outside_unchanged': (
        'outside the mask, the mean absolute per-pixel difference between the result and the input image is '
        '<= `max` (8-bit levels). An inpaint conditioning that repaints the whole frame has not respected its '
        'mask, however good the patch looks.'
    ),
}

# ── the one control set everything is measured against ─────────────────────────────────────
FX = 'capability_tests/fixtures/image/controlnet/'
BEAUTY = FX + 'mannequin_beauty.png'
TRUTH = FX + 'mannequin_truth.json'
MAPS = {
    'depth': FX + 'mannequin_depth.png',
    'pose': FX + 'mannequin_pose.png',
    'edge': FX + 'mannequin_lineart.png',
    'normal': FX + 'mannequin_normal.png',
    'seg': FX + 'mannequin_segment.png',
    'scribble': FX + 'mannequin_scribble.png',
}
GARBAGE = FX + 'garbage_depth.png'
MASK = FX + 'mannequin_hand_mask.png'
BROKEN = FX + 'mannequin_broken_hand.png'

NEG = (
    'lowres, blurry, out of focus, jpeg artefacts, extra limbs, extra fingers, fused fingers, '
    'missing fingers, deformed hands, extra heads, duplicated subject, mutated anatomy, cross-eyed, '
    'cartoon, anime, 3d render, cgi, plastic skin, modern clothing, modern buildings, cars, '
    'plastic packaging, neon light'
)

# The one prompt. Deliberately says nothing about the pose: if the prompt describes the pose, the
# probe measures the text encoder and not the control.
PROMPT = (
    'A Dutch shipwright of fifty in a plain linen shirt and leather apron, on the Kattenburg quay '
    'in 1671, overcast daylight, whole body in frame, empty cobbled quay behind him'
)
PROMPT_STYLE = (
    'A Dutch shipwright of fifty on the Kattenburg quay in 1671, Arcane painterly style, dark '
    'teal palette, visible brush texture, whole body in frame'
)

COND = {
    'width': 1024,
    'height': 1024,
    'seeds': [11, 12, 13],
    'repeats': 3,
    'negative': NEG,
    'control_strength': "the row's production default, read out of its workflow JSON at run time and "
    'written into the trial',
    'control_end_percent': "the row's production default, read out of its workflow JSON",
    'lora': None,
    'note': 'same prompt, same negative, same three seeds, same 1024 square, same mannequin plate for '
    'every row; steps/cfg/sampler are whatever the row ships in production so the sheet says '
    'what the house gets. The control map is fed at the render resolution — see res_match.',
}


def _cond(**kw):
    c = dict(COND)
    c.update(kw)
    return c


RULE = {'yes': 0.9, 'partial': 0.5}
RULE_STRICT = {'yes': 1.0, 'partial': 0.6}

# The thresholds. Picked to be passable by a working ControlNet and failable by a decorative one;
# a row that lands between them reads partial, which is the honest state for "it nudges".
DEPTH_MIN, EDGE_MIN, NORMAL_MAX, SEG_MIN = 0.80, 0.45, 25.0, 0.55
POSE_MAX = 0.05  # 5 % of image height: about 51 px at 1024, roughly a wrist's width

OP_POSE = (
    'Does the figure in this picture stand in the same pose as the control map shown beside it — '
    'the same limb directions and the same body turn, not merely a standing person?'
)
OP_LOUD = (
    'Is this picture obviously wrong at a glance — a melted, doubled or impossible figure — rather '
    'than a plausible picture of the wrong thing?'
)


def _p(pid, title, feeds, prompt, checks, cond=None, **kw):
    p = {
        'id': pid,
        'title': title,
        'feeds': list(feeds),
        'inputs': {'prompt': prompt, 'control': cond.get('control') if cond else MAPS['depth']},
        'conditions': cond or _cond(control={'channel': "the row's own", 'map': 'MAPS[channel]'}),
        'checks': list(checks),
        'grade': 'measured',
        'state_rule': dict(RULE),
    }
    p.update(kw)
    return p


AGREE = {
    'check': 'control_agreement_min',
    'channel': "the row's own",
    'depth_min': DEPTH_MIN,
    'edge_min': EDGE_MIN,
    'normal_max': NORMAL_MAX,
    'seg_min': SEG_MIN,
}
