# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Default test — Image to image / restyle (i2i). 2026-09-30.

Question the sheet asks: can we restyle a finished frame without losing the costume, the
colours or the person? The sheet's own verdict (2026-09-24..27, the Second Ledger intro)
already answers half of it: the FULL-FRAME restyle is dead for our use — it recoloured the
doublet purple and dropped identity to 0.226 against a 0.327 floor — and restyle now runs as
a masked patch under a depth ControlNet, gated on chroma (patch_gate.py, dab <= 4.5).

So this test is not "is the picture pretty". It is the two measurements that killed the
full-frame path and the two that let the patch path ship:
  * identity, before vs after, on the house identity worker, against the character's own
    same-pose baseline (id_score.py's floor) — full_frame, identity, iterate;
  * the costume colour, inside the garment matte, hue and colour share — colour, verbatim
    (the receipt: the instruction must be VERBATIM or the costume recolours);
  * pixels outside the mask byte-identical, and the seam band measured where the seam is —
    patch, mask_edge;
  * the strength ladder, because denoise is the lever for style AND for structure
    (hand_restyle_cn.py: 0.40 keeps fingers, 0.47 bands them, 0.55 breaks them, 0.65
    destroys the hand — unless a depth ControlNet pins the structure, and then 0.65 works).

Honest judging. No local VLM sees a second feather or a fused finger (defect-judge bench
2026-09-27: 2/8 on the hard cases). MediaPipe decides hands, MediaPipe pose decides the pose,
the identity worker decides the face, the colour bands decide the costume; brushwork, age and
"does the style read" are BLIND OPERATOR questions with the wording fixed here. patch_gate's
texture ratio is recorded as ADVISORY only — its own calibration says texture is not evidence
either way (p4's page hand scored 1.29 and still read photographic).

What is blocked. The identity FLOOR and the six plates' own faults are keys nobody has
verified for this bench, so `full_frame`, `identity`, `iterate`, `colour` and `verbatim` ship
`untested` until the operator flips MANIFEST.json's `verified`. Nothing here is generated in
this task: every fixture carries the exact command that makes it.
"""

from __future__ import annotations

import os

from capability_tests.image_shared import COND_RENDER, NEGATIVE
from zyg_workflows.paths import ZYG_HOME

# Check kinds this step adds. The base vocabulary is capability_tests/__init__.py, the image
# detectors are image_shared.CHECK_KINDS; these are the before/after rules an i2i run needs.
CHECK_KINDS = {
    'identity_cosine_source': 'the house identity worker (_identity_embed_worker.py, AuraFace, insightface root pinned in id_score.py) '
    'cosine between the largest face in the OUTPUT and the largest face in `source` is >= `min`; `floor` records '
    'the same-person same-pose baseline the character tiles give (id_score.py --refs), so the cell can say '
    'above or below the floor rather than quoting a bare number',
    'identity_cosine_drop': 'identity_cosine_source on this trial is no more than `max_drop` below the same measurement on the trial '
    'named in `to` (an earlier probe id at the same picture and seed) — the compounding test',
    'colour_survives': 'inside the matte named in `region`, the circular mean HUE of the output is within `max_hue_deg` of the '
    "source's AND the share of pixels inside image_shared.COLOUR_BANDS[`colour`] is >= `min_share`",
    'pose_keypoint_distance': 'MediaPipe pose_landmarker (pinned task file) on source and output; the mean euclidean distance of the '
    'landmarks visible in BOTH, normalised by the source shoulder width, is <= `max_norm`',
    'outside_mask_identical': 'every pixel outside dilate(`mask`, `tolerance_px`) is byte-identical to the source; a row that re-encodes '
    'or re-tones the whole frame fails even when the patch itself is good',
    'box_iou_min': 'the GroundingDINO box (pinned revision, `min_score`) for `query` in the output has IoU >= `min` with the '
    'box for the same query in the source',
    'light_side_delta': 'mean luma of the left half of the subject matte minus the right half keeps the SIGN it has in the source '
    'and changes by <= `max_levels` (the single-source lighting direction, 0-255 levels)',
    'patch_chroma_dab': "LAB (a,b) distance between the mean SKIN chroma of the region named in `region` and that of the picture's "
    'own painted face box (patch_gate.py `dab`, HSV skin rule) is <= `max`',
    'patch_texture_ratio': 'high-pass std (gaussian sigma 3) of the skin in `region` divided by the same on the face skin '
    '(patch_gate.py `tex`) is >= `min`; with `tiles` set the ratio is taken per tile and max-min <= `max_spread`',
    'seam_band_max': 'on the rim band of the mask (fill inside `fill_px` of the mask, painting beyond `keep_px`, feather between '
    '— the take-5 plate law), the per-channel |local mean step| across the feather has p50 <= `p50_max` and '
    'p90 <= `p90_max` levels, and the share of rim points above `p90_max` is <= `share_max`',
}

# ── the fixed plates ───────────────────────────────────────────────────────────────────────
#: The Second Ledger intro tree the plates and id_score.py come from; $ZYG_LEDGER_INTRO overrides it.
LEDGER_INTRO = os.environ.get('ZYG_LEDGER_INTRO') or str(ZYG_HOME / 'zygomatics-zero' / 'ledger_intro')
SRC = LEDGER_INTRO + '/intro/stills_v5'
SHOT8 = LEDGER_INTRO + '/shot8'
FIX = 'capability_tests/fixtures/image/ledger'
PLATES = ['p1_before.png', 'p2_before.png', 'p3_before.png', 'p4_before.png', 'p5_before.png']

STYLE_TAIL = 'arcane style, painterly 2D animation, muted earthy palette, confident oil brushwork'
TRIGGER = 'ZYG_CHAR_C3345D'
LORA = 'abel_arcane_v2_sdxl_kohya.safetensors'

# The three plates the receipts actually measured (patch_gate calibration 2026-09-27).
MEASURED = ['p1_before.png', 'p3_before.png', 'p4_before.png']

COND = dict(COND_RENDER)
COND['repeats'] = 3
COND['negative'] = NEGATIVE
COND['denoise'] = "the row's production default read from its workflow JSON, except where a probe sets a ladder"
COND['note'] = (
    "every trial takes its plate at the plate's own resolution — an i2i run that rescales the source is "
    "measured as it ships; width/height above are the bank's t2i frame and apply to the subject bank only"
)

ADVISORY = (
    "recorded in the trial and never changes the state: patch_gate's own calibration says texture is not "
    'evidence either way (p4 page hand tex 1.29 and still photographic)'
)


def _probe(pid, title, feeds, prompt, fixtures, checks, **kw):
    p = {
        'id': pid,
        'title': title,
        'feeds': list(feeds),
        'inputs': {'prompt': prompt, 'fixture': fixtures, 'negative': NEGATIVE, 'style_tail': STYLE_TAIL},
        'conditions': dict(COND),
        'checks': list(checks),
        'grade': 'measured',
    }
    p.update(kw)
    return p


RESTYLE = (
    'Restyle this picture in the Arcane painterly style, muted earthy palette, confident oil brushwork. '
    'Keep the person, the costume and every costume colour exactly as they are.'
)

PROBES = [
    _probe(
        'ff_full_frame',
        'F1 — the whole frame restyled (the path the sheet calls dead)',
        ['full_frame'],
        RESTYLE,
        [f'{FIX}/{n}' for n in MEASURED],
        [
            {
                'check': 'identity_cosine_source',
                'source': 'the plate',
                'min': 0.327,
                'floor': 0.327,
                'note': 'the measured full-frame result was 0.226 — this probe exists to say whether a new row still does that',
            },
            {
                'check': 'colour_survives',
                'region': 'garment matte from MANIFEST.json',
                'colour': 'brown',
                'max_hue_deg': 18,
                'min_share': 0.45,
                'note': 'the doublet came back purple: hue moved, share of brown collapsed',
            },
            {
                'check': 'operator',
                'question': 'Is this the same person, in the same clothes, as the other picture beside it?',
            },
        ],
        state_rule={'yes': 0.9, 'partial': 0.5},
        state_note='full_frame is yes only when identity stays above the floor AND the costume hue holds AND the '
        'operator says same person, on 9 of 9 trials at 0.9 — a restyle that keeps the person two times '
        'in three is not a frame the house ships',
    ),
    _probe(
        'ff_patch',
        'F2 — the masked patch under a depth ControlNet (the path that ships)',
        ['patch', 'mask_edge'],
        "a hand in the picture's own brushwork; " + STYLE_TAIL + f', {TRIGGER}',
        [f'{FIX}/{n}' for n in MEASURED],
        [
            {
                'check': 'outside_mask_identical',
                'mask': 'the hand box from MANIFEST.json, pad 1.5',
                'tolerance_px': 0,
                'col': 'patch',
                'note': 'hand_restyle_cn.py pastes a feathered rect: everything outside is byte-identical by construction',
            },
            {
                'check': 'patch_chroma_dab',
                'region': 'the hand box',
                'max': 4.5,
                'col': 'patch',
                'note': 'patch_gate HARD bound; every un-toned Qwen hand measured >= 5.74, the two painted controls 4.38 and 2.63',
            },
            {
                'check': 'seam_band_max',
                'mask': 'the hand box',
                'fill_px': 12,
                'keep_px': 18,
                'p50_max': 1.8,
                'p90_max': 5.4,
                'share_max': 0.12,
                'col': 'mask_edge',
                'note': "the take-5 plate law band; thresholds are the PAINTING's own contour numbers (1.8 / 5.4 / 12 %)",
            },
            {'check': 'patch_texture_ratio', 'region': 'the hand box', 'min': 0.80, 'advisory': True, 'note': ADVISORY},
            {
                'check': 'operator',
                'question': 'Can you see where this picture was repaired?',
                'expect': 'no',
                'col': 'patch',
            },
        ],
        conditions=dict(
            COND,
            denoise=0.65,
            cn='controlnet-depth-sdxl.safetensors',
            cn_strength=0.8,
            pad=1.5,
            res=1024,
            seeds=[3, 11, 12],
        ),
        state_note="the settings are hand_restyle_cn.py's measured ones (denoise 0.65, cn 0.8, pad 1.5, res 1024); "
        'a row without a depth ControlNet input runs the same probe with its own default denoise and the '
        'trial records that it had no control image',
    ),
    _probe(
        'ff_verbatim',
        'F3 — the instruction word-for-word against a paraphrase',
        ['verbatim'],
        'SET',
        [f'{FIX}/p3_before.png'],
        [
            {
                'check': 'colour_survives',
                'region': 'doublet matte',
                'colour': 'brown',
                'max_hue_deg': 18,
                'min_share': 0.45,
            },
            {'check': 'identity_cosine_source', 'source': 'the plate', 'min': 0.327, 'floor': 0.327},
        ],
        set=[
            RESTYLE,
            'Give this picture an Arcane look — painterly, earthy, brushy. Keep the character and the outfit recognisable.',
        ],
        state_note='verbatim is yes only when BOTH wordings keep the costume colour. The receipt is that the '
        'paraphrase recolours it, so a row that passes the first and fails the second is `no` on '
        'verbatim with the two trials side by side in the Inspect document — that is the finding, not a bug',
    ),
    _probe(
        'ff_strength',
        'F4 — the denoise ladder 0.3 / 0.5 / 0.7 / 0.9',
        ['strength'],
        RESTYLE,
        [f'{FIX}/p3_before.png'],
        [
            {'check': 'identity_cosine_source', 'source': 'the plate', 'min': 0.327, 'floor': 0.327},
            {'check': 'hand_landmarks', 'hands': 2, 'min_tip_px': 6},
            {
                'check': 'operator',
                'question': 'Does this picture carry visible oil brushwork rather than a smooth airbrushed surface?',
            },
        ],
        conditions=dict(COND, ladder=[0.3, 0.5, 0.7, 0.9], seeds=[11, 12, 13]),
        state_note='strength is `yes` when identity falls MONOTONICALLY with denoise (a lever that is calibrated) '
        'and at least one rung has identity above the floor and the operator saying brushwork; `partial` '
        'when a rung works but the curve is not monotone (the lever is a lottery); `no` when no rung '
        'gives both. Receipts predict 0.40-0.50 without a control image and 0.65 with depth at 0.8',
    ),
    _probe(
        'ff_survival',
        'F5 — one restyle per plate: what survived it',
        [
            'identity',
            'pose_keep',
            'composition_keep',
            'props_keep',
            'background_keep',
            'lighting_keep',
            'age_keep',
            'style_applied',
            'style_even',
            'hands_after',
            'texture',
        ],
        RESTYLE,
        [f'{FIX}/{n}' for n in PLATES],
        [
            {'check': 'identity_cosine_source', 'source': 'the plate', 'min': 0.327, 'floor': 0.327, 'col': 'identity'},
            {'check': 'pose_keypoint_distance', 'max_norm': 0.06, 'col': 'pose_keep'},
            {'check': 'box_iou_min', 'query': 'the person', 'min': 0.85, 'min_score': 0.35, 'col': 'composition_keep'},
            {
                'check': 'operator',
                'question': 'Is everything in this picture in the same place as in the picture beside it?',
                'col': 'composition_keep',
            },
            {
                'check': 'box_iou_min',
                'query': 'the props named for this plate in MANIFEST.json',
                'min': 0.75,
                'min_score': 0.30,
                'col': 'props_keep',
            },
            {
                'check': 'open_vocab_present',
                'terms': 'the props named for this plate in MANIFEST.json',
                'min_score': 0.30,
                'col': 'props_keep',
            },
            {
                'check': 'image_distance',
                'metric': 'pixel',
                'to': 'the plate',
                'max': 12,
                'region': 'outside the figure matte',
                'col': 'background_keep',
                'note': "12 levels is the plate law's own fill bound; a restyle that repaints the quay is a different picture",
            },
            {'check': 'light_side_delta', 'max_levels': 10, 'col': 'lighting_keep'},
            {
                'check': 'operator',
                'question': 'Is the light in this picture coming from the same side as in the picture beside it?',
                'col': 'lighting_keep',
            },
            {
                'check': 'operator',
                'question': 'Is this person the same age as the person in the picture beside it, to within five years?',
                'col': 'age_keep',
            },
            {
                'check': 'operator',
                'question': 'Does this picture read as a painted Arcane frame rather than a photograph?',
                'col': 'style_applied',
            },
            {
                'check': 'patch_texture_ratio',
                'region': 'the figure matte',
                'min': 0.80,
                'advisory': True,
                'col': 'style_applied',
                'note': ADVISORY,
            },
            {
                'check': 'operator',
                'question': 'Is the painted look the same strength everywhere in this picture, with no smooth or photographic area left?',
                'col': 'style_even',
            },
            {
                'check': 'patch_texture_ratio',
                'region': 'the whole frame',
                'tiles': [3, 3],
                'max_spread': 0.9,
                'min': 0.5,
                'col': 'style_even',
            },
            {
                'check': 'hand_landmarks',
                'hands': 'the count MANIFEST.json records for this plate',
                'min_tip_px': 6,
                'col': 'hands_after',
            },
            {
                'check': 'operator',
                'question': 'Does every hand in this picture have five fingers and no extra thumb?',
                'col': 'hands_after',
            },
            {
                'check': 'operator',
                'question': 'Is the surface of this picture brushwork — visible facets and strokes — rather than airbrush?',
                'col': 'texture',
            },
        ],
        state_note='each `col` check writes ITS column over 5 plates x 3 seeds = 15 trials. Where an operator '
        "question and a detector both carry a `col`, BOTH must pass for that trial to count (the bank's "
        'operator_protocol: the detector is authority for what it measures, the operator for the rest)',
    ),
    _probe(
        'ff_colour',
        'F6 — four named costume colours through the same restyle',
        ['colour'],
        RESTYLE,
        [f'{FIX}/{n}' for n in PLATES],
        [
            {
                'check': 'colour_survives',
                'region': 'the garment matte named in MANIFEST.json',
                'colour': 'SET',
                'max_hue_deg': 18,
                'min_share': 0.45,
            },
            {
                'check': 'operator',
                'question': 'Is the main garment in this picture the same colour as in the picture beside it?',
            },
        ],
        set=['brown', 'red', 'blue', 'white'],
        state_note='the four colours are the ones the intro costumes actually carry and the ones COLOUR_BANDS can '
        'measure; white is in the set because a restyle that tints everything earthy fails there first',
    ),
    _probe(
        'ff_iterate',
        'F7 — a second pass over the first pass',
        ['iterate'],
        RESTYLE,
        ['the ff_survival output at the same plate and seed'],
        [
            {'check': 'identity_cosine_drop', 'to': 'ff_survival', 'max_drop': 0.03},
            {'check': 'hand_landmarks', 'hands': 'the count MANIFEST.json records for this plate', 'min_tip_px': 6},
            {
                'check': 'operator',
                'question': 'Is this picture as clean as the picture beside it, with no new smearing or melted detail?',
            },
        ],
        conditions=dict(COND, passes=2, seeds=[11, 12, 13]),
        state_note='iterate is about COMPOUNDING, so it is measured as a drop against pass 1 at the same plate and '
        'seed, not against the plate: 0.03 of cosine is the width of the same-pose baseline in id_score.py',
    ),
]

RUN_ORDER = [
    'ff_patch',
    'ff_full_frame',
    'ff_verbatim',
    'ff_strength',
    'ff_survival',
    'ff_colour',
    'ff_iterate',
    'the shared image bank (capacity, counting, spatial, attributes, prompt bands) LAST',
    'the 132-subject bank absolutely last — it is 396 of the 477 renders',
]

FIXTURES = (
    [
        {
            'path': f'{FIX}/MANIFEST.json',
            'verified': False,
            'blocks': ['full_frame', 'identity', 'iterate', 'colour', 'verbatim'],
            'generated': (
                'write by hand from the stills_v5 receipts: for each of the six plates the face box (the identity '
                "worker's, as face_pass_arcane.face_bbox gives it), the hand box(es) and the hand COUNT, the "
                'garment matte path and its COLOUR_BANDS colour, the prop queries, and `identity_floor` from '
                f'`python3 {LEDGER_INTRO}/id_score.py --refs <the Abel/Cornelis '
                'reference tiles>` (the 2026-09-24 run '
                'reported a 0.327 same-pose floor)'
            ),
            'how_to_verify': (
                'the operator opens each plate at 3x beside its matte and confirms: the face box holds the '
                'face, the hand boxes hold the hands, the hand count is right, the garment matte covers the '
                'garment and nothing else, and the identity floor was produced by the same worker revision '
                'that will run the test — then sets verified: True'
            ),
        },
    ]
    + [{'path': f'{FIX}/{n}', 'generated': f'mkdir -p {FIX} && cp {SRC}/{n} {FIX}/{n}'} for n in PLATES]
    + [
        {
            'path': f'{FIX}/shot8_bgn_23.png',
            'generated': f'mkdir -p {FIX} && cp {SHOT8}/bgn_23.png {FIX}/shot8_bgn_23.png',
            'note': 'the measured fill/texture plate (harmonise_fill.py: the repainted water carried 57-64 % of the '
            'surrounding high-frequency energy); used here only by background_keep as a non-figure control',
        },
    ]
)

TEST = {
    'step': 'i2i',
    'version': '2026-09-30.1',
    'title': 'Six Ledger plates, one restyle instruction, identity and costume measured before and after',
    'purpose': (
        'Measure whether a restyle keeps the person, the costume colour and the pixels it was not asked to '
        'touch — the four measurements that killed the full-frame path (identity 0.226 vs a 0.327 floor, a '
        'purple doublet) and the three that let the masked-patch path ship (dab <= 4.5, the plate-law seam '
        'band, outside-mask byte-identity).'
    ),
    'include_shared': 'image',
    'run_order': RUN_ORDER,
    'rows': {
        'qwen_edit': {
            'transport': 'comfy',
            'model': '_comfy_workflows/qwen_edit_angle.json',
            'where': 'Qwen-Image-Edit through the house comfy client',
            'budget': {
                'minutes': 200,
                'gpu_minutes': 200,
                'note': 'Qwen-Image at 1024 measured ~25 s a render in the intro work: 477 x 25 s = ~200 min',
            },
            'na': {
                'strength': 'qwen_edit_angle.json is instruction-driven and exposes no denoise or '
                'strength input — there is no ladder to calibrate on this row, the '
                'instruction wording is the only lever (and ff_verbatim measures that)'
            },
        },
        'sdxl_i2i': {
            'transport': 'comfy',
            'model': '_comfy_workflows/sdxl_img2img.json',
            'where': 'sd_xl_base_1.0.safetensors, no LoRA — the baseline the arcane_lora row is read against',
        },
        'flux_i2i': {
            'transport': 'comfy',
            'model': '_comfy_workflows/flux_img2img.json',
            'where': 'FLUX img2img; the licence gate (data/runtime/model_licences_pending) decides whether '
            'this row may run on a monetised channel at all',
            'budget': {
                'minutes': 240,
                'gpu_minutes': 240,
                'note': 'FLUX at 1024 is ~30 s a render on this box: 477 x 30 s = ~240 min',
            },
        },
        'klein_i2i': {
            'transport': 'comfy',
            'model': '_comfy_workflows/klein_pose_i2i.json',
            'where': 'the Klein pose-conditioned i2i graph',
            'note': 'klein_pose_i2i.json drives a POSE reference, so pose_keep is partly satisfied by '
            'construction on this row; the trial records the control image so the cell can be read '
            'with that in mind',
        },
        'arcane_lora': {
            'transport': 'comfy',
            'model': '_comfy_workflows/sdxl_img2img_lora.json',
            'where': f'the same graph as sdxl_i2i with {LORA} loaded and {TRIGGER} in the prompt',
            'note': "this row measures the LoRA's EFFECT, so the run must first prove the LoRA is "
            'applied at all: ComfyUI LoRAs were silently never applied stack-wide until '
            '2026-09-23 (convert_lora.py). The trial records the ComfyUI log line for the '
            'LoraLoader and a pixel distance against the sdxl_i2i trial at the same plate and '
            'seed; identical pixels mean the LoRA did not load and every cell on this row is '
            'untested, not `no`.',
        },
    },
    'probes': PROBES,
    'derive': {},
    'lookup': {},
    'wiring': {},
    'na': {},
    'fixtures': FIXTURES,
    'budget': {
        'calls': 477,
        'tokens_in': 0,
        'tokens_out': 0,
        'tokens_note': 'every row is a ComfyUI image-in / image-out graph: the instruction is a fixed string in this '
        'file, not a language-model call, so no token meter moves and no Claude week is spent',
        'minutes': 80,
        'gpu_minutes': 80,
        'operator_minutes': 340,
        'note': (
            'DOMAIN 81 renders: ff_patch 3 plates x 3 seeds = 9, ff_full_frame 9, ff_verbatim 2 wordings x 3 = 6, '
            'ff_strength 4 rungs x 3 = 12, ff_mask_edge is folded into ff_patch (0), ff_survival 5 plates x 3 = 15, '
            'ff_colour 4 colours x 3 = 12, ff_iterate 3 plates x 3 = 9 (pass 2 over ff_survival outputs) = 81. '
            'SHARED BANK: 132 subjects x 3 seeds = 396 renders plus the capacity/prompt probes already counted in '
            'the bank. 81 + 396 = 477 calls per row at ~10 s for SDXL 1024 = ~80 min wall, all of it on the GPU '
            "(per-row overrides for Qwen ~25 s and FLUX ~30 s). OPERATOR: the bank's 396 subject decisions + the "
            "domain's 288 blind decisions (ff_survival 7 questions x 15 trials = 105, ff_patch 9, ff_full_frame 9, "
            'ff_strength 12, ff_colour 15, ff_iterate 9, and the paired side-by-side plates counted once each) = '
            '~684 decisions x 30 s = ~340 min. No Claude meter is touched by any row.'
        ),
    },
    'notes': [
        'The sheet already carries the finding this test is built to reproduce: full-frame restyle at identity 0.226 '
        'against a 0.327 floor, with a purple doublet. ff_full_frame is kept as a live probe and not written off as '
        '`na`, because "the new model still does this" and "the new model fixed this" are both answers the sheet needs.',
        "patch_gate's chroma bound (dab <= 4.5) is the only mechanical gate in the house that caught the real defect "
        'the operator rejected — a repaired region that is anatomically right and photographic against brushwork. It '
        'is the deciding check on `patch`. Its texture ratio is advisory by its own calibration.',
        'Every operator question here is answered BESIDE the source plate, which is the one place this step differs '
        "from the bank's blind protocol: a restyle can only be judged against what it was given. The pair is still "
        'anonymised and shuffled, and the operator is never told the row, the seed or the denoise.',
        'The `strength` column is a curve, not a number: a row whose identity does not fall monotonically with '
        'denoise has an uncalibrated lever even if one rung looks good, and that is what `partial` says here.',
    ],
}
