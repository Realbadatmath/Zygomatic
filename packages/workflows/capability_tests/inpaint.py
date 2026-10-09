# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Default test — Inpaint / repair (inpaint). 2026-09-30.

Question the sheet asks: can we fix a hand or remove an object inside a finished frame? The
sheet's own note is the shape of this test: "a repair is only as good as its MASK and its
GATE — both recorded failures here were a correct model driven by a wrong mask or checked in
the wrong place." So the six repair columns are measured on SIX KNOWN-BAD HANDS from the
Second Ledger intro, and the eleven mask/join columns are measured on the mask and the gate,
not on the model.

What the receipts already decided, and what this test reproduces
---------------------------------------------------------------
* fix_hand.py (2026-09-26, p1's fingerless mitten): SDXL+LoRA inpaint at denoise 0.90 gave
  1 usable hand in 4 seeds — one seed painted TWO hands, one ERASED the hand. Qwen over the
  whole BOX: perfect anatomy, hand 2x too big. Qwen under a mask fitted to the hand's OWN
  silhouette (skin blob grown 10 px): right anatomy at the right scale, first seed. That is
  the `mask_source` finding and the recipe every repair row is driven with here.
* patch_gate.py (2026-09-27): every repaired hand was anatomically right and looked worse,
  because it was photographic against the brushwork. dab <= 4.5 is the HARD bound (each
  rejected hand measured 5.74-10.97; the painted controls 4.38 and 2.63). tex >= 0.80 is a
  FLAG only — p4's page hand scored 1.29 and still read photographic — so it is advisory
  here and the eye stays the judge of brushwork.
* tone_membrane.py (take 5): an SDXL fill carries its own low-frequency tone, so the plate
  steps from fill tone to painting tone at the feather — a figure-shaped outline, |step|
  p50 4.5 / p90 14.3 / 47 % of the flat rim, where the painting's OWN contour measures
  1.8 / 5.4 / 12 %. cv2.seamlessClone cannot remove it (the offset varies along the rim).
  Those painting numbers are the thresholds for `tone_match` and `colour_match`.
* harmonise_fill.py: a generative fill comes back SMOOTH — 57-64 % of the surrounding
  high-frequency energy — and asked for more texture it invents OBJECTS instead (123 %).
  That is `grain_match`, and per the take-4 finding the bands are scaled to the figure's
  AREA, because a fixed band under-samples a small figure and over-samples a large one.
* the take-5 plate law: fill inside 12 px of matte_raw, untouched painting beyond 18 px,
  6 px feather between. It is the band `seams` and `check_band` are measured in, and the
  guarantee `no_drift` checks.

Honest judging. MediaPipe hand_landmarker decides finger counts, PaddleOCR decides lettering,
GroundingDINO decides whether the object went away, the identity worker decides the face, and
the four numeric gates above decide the join. "Does this repair look like part of the picture"
is a BLIND OPERATOR question, worded here.

Blocked. The six bad hands, the three bad faces and the ledger page word are answer keys
nobody has verified for this bench, so `hands`, `faces_fix`, `text_fix` and `mask_auto` ship
`untested` until the operator flips MANIFEST.json's `verified`. Nothing is generated in this
task: every fixture carries the exact command that makes it.
"""

from __future__ import annotations

import os

from capability_tests.image_shared import COND_RENDER
from zyg_workflows.paths import ZYG_HOME

# Check kinds this step adds — the join, the mask and the gate. The base vocabulary is in
# capability_tests/__init__.py and the image detectors in image_shared.CHECK_KINDS.
CHECK_KINDS = {
    'seam_band_max': 'on the rim band of the mask (fill inside `fill_px` of the mask, painting beyond `keep_px`, feather between '
    '— the take-5 plate law), the per-channel |local mean step| across the feather has p50 <= `p50_max` and '
    'p90 <= `p90_max` levels, and the share of rim points above `p90_max` is <= `share_max`',
    'rim_tone_step': "tone_membrane.py's measurement: on the flat points of the rim of dilate(mask, `fill_px`), delta = local mean "
    '(31 px window) of the PAINTING 3..12 px outside minus the local mean of the FILL 3..12 px inside, per BGR '
    'channel; |mean over channels| has p50 <= `p50_max` and p90 <= `p90_max` levels, and with `max_channel_spread` '
    'set, max-min across the three channels at each rim point is <= that (a tone match that is not a colour match)',
    'grain_energy_ratio': 'high-pass std (gaussian sigma 3, measure_fill.py hf_energy) inside the mask divided by the same in the plate '
    'beside it, measured in horizontal bands whose height is `band_frac` x sqrt(figure matte AREA) — the take-4 '
    "finding that grain must scale with figure area — and every band's ratio must lie in [`min`, `max`]",
    'patch_chroma_dab': "LAB (a,b) distance between the mean SKIN chroma of the region named in `region` and that of the picture's own "
    'painted face box (patch_gate.py `dab`, the shared HSV skin rule) is <= `max`; a box with no skin is reported '
    'no_skin and does not fail',
    'patch_texture_ratio': 'high-pass std (sigma 3) of the skin in `region` divided by the same on the face skin (patch_gate.py `tex`) '
    'is >= `min`',
    'outside_mask_identical': 'every pixel outside dilate(`mask`, `tolerance_px`) is byte-identical to the source; a row that re-encodes or '
    're-tones the whole frame fails even when the patch itself is good',
    'mask_matches_frame': 'the mask the run was driven with has IoU >= `min` with the silhouette the named detector finds in THIS '
    'picture (`detector`: skin_blob | sam3 | mediapipe_hand) — the check that a stale silhouette from an earlier '
    'still cannot pass',
    'gate_band_covers_seam': 'the band the gate actually measured overlaps the rim band (distance 0..`keep_px` from the mask) on at least '
    '`min_share` of its pixels — a gate can be arithmetically right and look in the wrong place',
    'frame_grew': 'the output is exactly `sides` pixels larger on each named side than the source, and the source region inside '
    'it is byte-identical to the source within `tolerance_px`',
    'identity_cosine_source': 'the house identity worker (_identity_embed_worker.py, AuraFace, insightface root pinned in id_score.py) '
    'cosine between the largest face in the OUTPUT and the largest face in `source` is >= `min`; `floor` records '
    "the character tiles' same-pose baseline (id_score.py --refs)",
}

# ── the fixed plates ───────────────────────────────────────────────────────────────────────
#: The Second Ledger intro tree the plates and id_score.py come from; $ZYG_LEDGER_INTRO overrides it.
LEDGER_INTRO = os.environ.get('ZYG_LEDGER_INTRO') or str(ZYG_HOME / 'zygomatics-zero' / 'ledger_intro')
SRC = LEDGER_INTRO + '/intro/stills_v5'
SHOT8 = LEDGER_INTRO + '/shot8'
FIX = 'capability_tests/fixtures/image/bad_hands'
PLATES = ['p1_v5.png', 'p2_v5.png', 'p3_v5.png', 'p4_v5.png', 'p5_v5.png']

# The five regions the operator rejected on stills v5, with patch_gate's measured numbers, plus
# p1's fingerless mitten from fix_hand.py's 2026-09-26 receipt — six known-bad hands.
BAD_HANDS = [
    ('p1_v5.png', 'the rail hand (patch_gate dab 10.97 / tex 0.85) — fix_hand.py calls it a fingerless mitten'),
    ('p3_v5.png', "Cornelis's hand (dab 9.56 / tex 0.94)"),
    ('p3_v5.png', 'the Abel body+hands region (dab 8.12 / tex 0.73)'),
    ('p4_v5.png', 'the quill hand (dab 7.86 / tex 0.90)'),
    ('p4_v5.png', 'the page hand (dab 5.74 / tex 1.29 — right anatomy, still photographic)'),
    ('p2_v5.png', 'the second hand on p2, unmeasured — the operator confirms it is bad when verifying MANIFEST.json'),
]
CONTROL = (
    'p5_v5.png',
    'the APPROVED page hand (dab 2.63 / tex 1.85) — the control that must PASS every gate '
    'unrepaired; a run that "improves" it has failed no_drift',
)

STYLE_TAIL = 'arcane style, painterly 2D animation, muted earthy palette, confident oil brushwork'
TRIGGER = 'ZYG_CHAR_C3345D'
LORA = 'abel_arcane_v2_sdxl_kohya.safetensors'
NEG_HAND = (
    'extra fingers, six fingers, fused fingers, missing fingers, mitten, glove, claw, deformed hand, '
    'mutated hand, banded fingers, watermark, text'
)

COND = dict(COND_RENDER)
COND['repeats'] = 3
COND['negative'] = NEG_HAND
COND['region'] = 1024
COND['grow_px'] = 10
COND['denoise'] = "the row's production default for the masked pass, read from its workflow JSON"
COND['note'] = (
    'the plate is inpainted at its own resolution with the masked region taken to 1024 on the long side '
    "(fix_hand.py --grow 10, region 1024); width/height above are the bank's t2i frame and apply to the "
    'subject bank only'
)

# The plate law, one place.
LAW = {
    'fill_px': 12,
    'keep_px': 18,
    'feather_px': 6,
    'note': 'take-5 plate law: fill inside 12 px of the raw matte, untouched painting beyond 18, 6 px feather',
}
PAINTING_RIM = {
    'p50_max': 1.8,
    'p90_max': 5.4,
    'share_max': 0.12,
    'note': "the PAINTING's own contour numbers; an SDXL fill measured 4.5 / 14.3 / 47 %",
}
ADVISORY = (
    "recorded in the trial and never changes the state: patch_gate's own calibration says texture is not "
    'evidence either way (p4 page hand tex 1.29 and still photographic)'
)

ACTION = (
    "a teenage boy's right hand gripping the top of a wooden rail, four fingers curled over the far edge, "
    'thumb along the near edge'
)


def _probe(pid, title, feeds, prompt, fixtures, checks, **kw):
    p = {
        'id': pid,
        'title': title,
        'feeds': list(feeds),
        'inputs': {'prompt': prompt, 'fixture': fixtures, 'negative': NEG_HAND, 'style_tail': STYLE_TAIL},
        'conditions': dict(COND),
        'checks': list(checks),
        'grade': 'measured',
    }
    p.update(kw)
    return p


PROBES = [
    _probe(
        'ip_hands',
        'R1 — six known-bad hands through the fix_hand recipe',
        ['hands'],
        'ACTION, per hand, from MANIFEST.json — action-first, no character trigger on the Qwen pass; '
        f'the LoRA restyle pass adds {TRIGGER} and: {STYLE_TAIL}',
        [f'{FIX}/{n}' for n, _ in BAD_HANDS] + [f'{FIX}/{CONTROL[0]}'],
        [
            {
                'check': 'hand_landmarks',
                'hands': 1,
                'min_tip_px': 6,
                'note': 'exactly ONE hand in the box: the measured SDXL failure painted TWO, and another erased the hand',
            },
            {'check': 'patch_chroma_dab', 'region': 'the repaired hand box', 'max': 4.5},
            {
                'check': 'patch_texture_ratio',
                'region': 'the repaired hand box',
                'min': 0.80,
                'advisory': True,
                'note': ADVISORY,
            },
            {'check': 'outside_mask_identical', 'mask': 'the fitted hand mask', 'tolerance_px': 0},
            {
                'check': 'operator',
                'question': 'Does this hand have exactly five fingers, in a shape a hand can make, doing what the caption says?',
            },
            {
                'check': 'operator',
                'question': 'Does this hand look painted in the same brushwork as the face above it, rather than photographic?',
            },
        ],
        conditions=dict(
            COND, denoise=0.40, grow_px=10, region=1024, seeds=[7, 11, 12], restyle_denoise=0.40, lora=LORA
        ),
        state_rule={'yes': 0.85, 'partial': 0.5},
        state_note=(
            'the ladder is the measured one: Qwen under a silhouette-fitted mask for STRUCTURE, then the '
            'character LoRA at denoise 0.40 for SURFACE (0.47 bands the fingers, 0.55 breaks them, 0.65 '
            'destroys the hand without a depth control image). yes needs 0.85 because the receipt for the '
            'rejected path was 1 usable hand in 4 seeds — 0.25 — and anything near that must not read as '
            'partial. The CONTROL hand is run too and must come back unchanged.'
        ),
    ),
    _probe(
        'ip_faces',
        'R2 — three faces repaired without becoming someone else',
        ['faces_fix'],
        f"the character's face, {TRIGGER}, {STYLE_TAIL}",
        [f'{FIX}/{n}' for n in ('p1_v5.png', 'p3_v5.png', 'p4_v5.png')],
        [
            {'check': 'identity_cosine_source', 'source': 'the plate', 'min': 0.327, 'floor': 0.327},
            {'check': 'patch_chroma_dab', 'region': 'the face box', 'max': 4.5},
            {'check': 'outside_mask_identical', 'mask': 'the face mask', 'tolerance_px': 0},
            {
                'check': 'operator',
                'question': 'Is this the same person as in the picture beside it, with two matched eyes and no melted feature?',
            },
        ],
        conditions=dict(COND, seeds=[11, 12, 13]),
        state_note='a face repair that raises the cosine is as interesting as one that drops it; the number is '
        'written into the cell either way and the floor is the same 0.327 baseline the i2i sheet uses',
    ),
    _probe(
        'ip_remove',
        'R3 — two objects removed and gone',
        ['objects'],
        'empty wooden deck planking, nothing on it; ' + STYLE_TAIL,
        [f'{FIX}/p4_v5.png', f'{FIX}/shot8_bgn_23.png'],
        [
            {'check': 'open_vocab_absent', 'terms': 'the removed object query from MANIFEST.json', 'min_score': 0.30},
            {'check': 'outside_mask_identical', 'mask': 'the removal mask', 'tolerance_px': 0},
            {'check': 'seam_band_max', 'mask': 'the removal mask', **LAW, **PAINTING_RIM},
            {
                'check': 'operator',
                'question': 'Is the place the object used to be indistinguishable from the surface around it?',
            },
        ],
        conditions=dict(COND, seeds=[11, 12, 13]),
        state_note='the two removals are the white feather the sampler invented on p4 (hand_restyle_cn, 2026-09-27) '
        'and the rope coil plus cleat harmonise_fill measured the generator inventing on shot8 — both '
        'are real objects the house wanted gone, not made-up test targets',
    ),
    _probe(
        'ip_add',
        'R4 — two objects added that belong',
        ['add_object'],
        'SET',
        [f'{FIX}/p5_v5.png', f'{FIX}/shot8_bgn_23.png'],
        [
            {
                'check': 'open_vocab_count',
                'query': 'the added object query from MANIFEST.json',
                'count': 1,
                'min_score': 0.30,
            },
            {'check': 'outside_mask_identical', 'mask': 'the addition mask', 'tolerance_px': 0},
            {'check': 'patch_chroma_dab', 'region': 'the addition mask', 'max': 4.5},
            {
                'check': 'operator',
                'question': 'Does this object belong in this picture — right size, right light, right paint — and is there exactly one of it?',
            },
        ],
        set=[
            'a single pewter candlestick standing on the desk, one lit candle, ' + STYLE_TAIL,
            'a single coiled tarred rope lying on the deck planking, ' + STYLE_TAIL,
        ],
        conditions=dict(COND, seeds=[11, 12, 13]),
    ),
    _probe(
        'ip_extend',
        'R5 — the frame extended (outpaint)',
        ['extend'],
        'more of the same quay and sky, nothing new in it; ' + STYLE_TAIL,
        [f'{FIX}/p1_v5.png', f'{FIX}/shot8_bgn_23.png'],
        [
            {'check': 'frame_grew', 'sides': {'left': 256, 'right': 256, 'top': 0, 'bottom': 0}, 'tolerance_px': 0},
            {'check': 'seam_band_max', 'mask': 'the original frame rectangle', **LAW, **PAINTING_RIM},
            {
                'check': 'open_vocab_absent',
                'terms': ['a person', 'a face', 'a hand', 'a boat', 'lettering'],
                'min_score': 0.35,
                'note': 'an outpaint that invents a second figure is the failure mode, not a shortfall of imagination',
            },
            {
                'check': 'operator',
                'question': 'Could this whole picture have been photographed or painted in one piece, with no visible join down the left or right?',
            },
        ],
        conditions=dict(COND, seeds=[11, 12, 13]),
        state_note='256 px each side on a 1024-wide plate is one SDXL tile — the amount the house actually asks for '
        'when a shot needs a wider crop',
    ),
    _probe(
        'ip_text',
        'R6 — the lettering on the ledger page repaired',
        ['text_fix'],
        'a handwritten ledger page reading KATTENBURG 1671 in brown iron-gall ink; ' + STYLE_TAIL,
        [f'{FIX}/p5_v5.png'],
        [
            {'check': 'ocr_equals', 'text': 'KATTENBURG 1671'},
            {'check': 'outside_mask_identical', 'mask': 'the page mask', 'tolerance_px': 0},
            {
                'check': 'operator',
                'question': 'Does this page read KATTENBURG 1671, with no extra or invented letters?',
            },
        ],
        conditions=dict(COND, seeds=[11, 12, 13]),
        state_note='ocr_equals is the deciding check and the operator answers the same question blind; a repair '
        'that produces legible but different words is a `no`, which is what lettering repair does',
    ),
    _probe(
        'ip_join',
        'R7 — the join: seam, tone, colour, grain, style',
        ['seams', 'tone_match', 'colour_match', 'grain_match', 'style'],
        f"the patch in the picture's own paint; {TRIGGER}, {STYLE_TAIL}",
        [f'{FIX}/p1_v5.png', f'{FIX}/p4_v5.png', f'{FIX}/shot8_bgn_23.png'],
        [
            {'check': 'seam_band_max', 'mask': 'the patch mask', **LAW, **PAINTING_RIM, 'col': 'seams'},
            {
                'check': 'rim_tone_step',
                'mask': 'the patch mask',
                'fill_px': 12,
                'p50_max': 1.8,
                'p90_max': 5.4,
                'col': 'tone_match',
                'note': 'the fill measured 4.5 / 14.3; seamlessClone cannot fix it because the offset varies along the rim',
            },
            {
                'check': 'rim_tone_step',
                'mask': 'the patch mask',
                'fill_px': 12,
                'p50_max': 2.5,
                'p90_max': 7.0,
                'max_channel_spread': 3.0,
                'col': 'colour_match',
                'note': 'colour_match is the per-channel SPREAD of the same delta: a patch can match tone and still be '
                'pinker, which is exactly how the purple doublet and the Qwen skin read',
            },
            {
                'check': 'grain_energy_ratio',
                'mask': 'the patch mask',
                'band_frac': 0.25,
                'min': 0.85,
                'max': 1.15,
                'col': 'grain_match',
                'note': 'the generator measured 0.57-0.64 (smooth) and 1.23 when pushed for texture (it invented objects); '
                'band height scales with sqrt(figure area) — the take-4 finding',
            },
            {'check': 'patch_chroma_dab', 'region': 'the patch mask', 'max': 4.5, 'col': 'style'},
            {
                'check': 'patch_texture_ratio',
                'region': 'the patch mask',
                'min': 0.80,
                'advisory': True,
                'col': 'style',
                'note': ADVISORY,
            },
            {
                'check': 'operator',
                'question': 'Is this patch painted in the same hand as the rest of the picture?',
                'col': 'style',
            },
            {'check': 'operator', 'question': 'Can you find the edge of the repair?', 'expect': 'no', 'col': 'seams'},
        ],
        conditions=dict(COND, seeds=[11, 12, 13]),
        state_note='one probe, five columns, one set of renders: the join is one event and measuring it five times '
        'would be five times the GPU for the same pictures. Each `col` check writes its own column',
    ),
    _probe(
        'ip_mask_source',
        "R8 — this picture's own mask against a stale silhouette",
        ['mask_source'],
        f'ACTION from MANIFEST.json; {TRIGGER}, {STYLE_TAIL}',
        [f'{FIX}/p1_v5.png', f'{FIX}/p4_v5.png'],
        [
            {'check': 'mask_matches_frame', 'detector': 'skin_blob', 'min': 0.6},
            {'check': 'hand_landmarks', 'hands': 1, 'min_tip_px': 6},
            {
                'check': 'operator',
                'question': 'Is the repaired part the right size and in the right place for this picture?',
            },
        ],
        set=[
            'the mask derived from THIS picture (fix_hand.py skin blob in the box, grown 10 px)',
            'the silhouette saved from the PREVIOUS still of the same shot (stills_v4), re-imposed unchanged',
        ],
        conditions=dict(COND, seeds=[11, 12, 13]),
        state_note=(
            'mask_source is `yes` only when the own-mask variant passes AND the stale-silhouette variant '
            'FAILS — a row that gets the same answer from either mask is not reading the picture, it is '
            'painting the whole box (the measured Qwen-over-the-whole-box failure: right anatomy, hand 2x '
            'too big). Both variants are recorded so the cell can be read.'
        ),
    ),
    _probe(
        'ip_mask_soft',
        'R9 — three feathers: 0, 6 and 16 px',
        ['mask_soft'],
        f'ACTION from MANIFEST.json; {TRIGGER}, {STYLE_TAIL}',
        [f'{FIX}/p1_v5.png'],
        [
            {'check': 'seam_band_max', 'mask': 'the fitted hand mask', **LAW, **PAINTING_RIM},
            {
                'check': 'outside_mask_identical',
                'mask': 'the fitted hand mask',
                'tolerance_px': 18,
                'note': "the plate law's guarantee: beyond 18 px of the raw matte nothing may change, whatever the feather",
            },
            {'check': 'operator', 'question': 'Can you find the edge of the repair?', 'expect': 'no'},
        ],
        conditions=dict(COND, feather_ladder=[0, 6, 16], seeds=[11, 12, 13]),
        state_note="soft masks work when the 6 px feather (the plate law's own) passes the rim band AND the 18 px "
        'guarantee holds at every feather; 0 px shows the hard edge and 16 px shows whether the row '
        'smears past its own mask — both are part of the answer, not noise',
    ),
    _probe(
        'ip_mask_auto',
        'R10 — the mask derived without a human drawing it',
        ['mask_auto'],
        'no prompt: the mask is derived from the picture',
        [f'{FIX}/{n}' for n, _ in BAD_HANDS],
        [
            {'check': 'mask_matches_frame', 'detector': 'skin_blob', 'min': 0.6},
            {'check': 'mask_matches_frame', 'detector': 'mediapipe_hand', 'min': 0.5},
            {'check': 'operator', 'question': 'Does this outline cover the hand and nothing else?'},
        ],
        conditions=dict(
            COND,
            repeats=1,
            grow_px=10,
            note='deterministic OpenCV/MediaPipe, so one repeat; the trial records the mask PNG',
        ),
        state_note=(
            'measured against the hand-drawn mask in MANIFEST.json, IoU >= 0.6 for the skin blob and >= 0.5 '
            'for the MediaPipe hull. fix_hand.py already says when the auto route cannot work — a hand '
            'under a cuff or in shadow is not skin-coloured and needs --mask — so a row scoring 4 of 6 is '
            '`partial`, which is the honest answer, not a failure'
        ),
    ),
    _probe(
        'ip_check_band',
        'R11 — the gate looks where the seam is',
        ['check_band'],
        'no prompt: the gate is run over the ip_hands and ip_join outputs',
        ['the ip_hands and ip_join outputs, at every plate and seed'],
        [
            {'check': 'gate_band_covers_seam', 'keep_px': 18, 'min_share': 0.9},
            {
                'check': 'seam_band_max',
                'mask': 'the patch mask',
                **LAW,
                **PAINTING_RIM,
                'note': 'run TWICE per output: in the rim band, and in a band of the same area 40 px away from the mask',
            },
        ],
        conditions=dict(
            COND,
            repeats=1,
            band_offsets=[0, 40],
            note='no renders: the two band placements are measured on pictures ip_hands and ip_join already produced',
        ),
        state_note=(
            "check_band is `yes` when the band the row's own gate reports overlaps the rim band by >= 90 % "
            'AND the verdict CHANGES between the rim band and the 40 px-away band. A gate that gives the '
            "same answer in both places is not measuring the seam — that is the sheet's second recorded "
            'failure, a correct model checked in the wrong place.'
        ),
    ),
    _probe(
        'ip_no_drift',
        'R12 — nothing outside the mask moved',
        ['no_drift'],
        'no prompt: measured on the ip_hands, ip_join and ip_remove outputs',
        ['the ip_hands, ip_join and ip_remove outputs, at every plate and seed'],
        [
            {'check': 'outside_mask_identical', 'mask': 'the mask that run was driven with', 'tolerance_px': 0},
            {
                'check': 'image_distance',
                'metric': 'pixel',
                'to': 'the plate',
                'max': 0,
                'region': 'beyond 18 px of the raw matte',
                'note': "the plate law's guarantee, stated as a distance",
            },
        ],
        conditions=dict(COND, repeats=1, note='no renders: measured on pictures the repair probes already produced'),
        state_note=(
            'byte-identical, not "close": hand_restyle_cn.py pastes a feathered rectangle and everything '
            'outside it is identical BY CONSTRUCTION, so any drift means the row re-encoded or re-toned '
            'the whole frame. The APPROVED p5 control hand is in this set and must come back untouched.'
        ),
    ),
]

RUN_ORDER = [
    'ip_mask_auto',
    'ip_mask_source',
    'ip_hands',
    'ip_join',
    'ip_check_band',
    'ip_no_drift',
    'ip_mask_soft',
    'ip_faces',
    'ip_remove',
    'ip_add',
    'ip_text',
    'ip_extend',
    'the shared image bank (capacity, counting, spatial, attributes, prompt bands) LAST',
    'the 132-subject bank absolutely last — it is 396 of the 483 renders',
]

FIXTURES = (
    [
        {
            'path': f'{FIX}/MANIFEST.json',
            'verified': False,
            'blocks': ['hands', 'faces_fix', 'text_fix', 'mask_auto'],
            'generated': (
                'write by hand from the stills_v5 receipts: per plate the face box (face_pass_arcane.face_bbox), '
                'each bad-hand box with 40 px of context and its patch_gate dab/tex from the 2026-09-27 '
                'calibration, the ACTION sentence for each hand, a hand-drawn reference mask per hand, the removed '
                'and added object queries, the page text KATTENBURG 1671, and `identity_floor` from `python3 '
                f'{LEDGER_INTRO}/id_score.py --refs <the reference tiles>`'
            ),
            'how_to_verify': (
                'the operator opens each of the six hands at 3x with the counting protocol and confirms it IS '
                'bad (and that the p5 control hand is good), checks each box holds the hand, checks the page '
                'really reads KATTENBURG 1671, and confirms the identity floor came from the same worker '
                "revision the test will run — then sets verified: True. p2's hand is the one nobody has "
                'measured; if the operator finds it acceptable it is dropped to five hands and the version '
                'of this test changes.'
            ),
        },
    ]
    + [{'path': f'{FIX}/{n}', 'generated': f'mkdir -p {FIX} && cp {SRC}/{n} {FIX}/{n}'} for n in PLATES]
    + [
        {
            'path': f'{FIX}/shot8_bgn_23.png',
            'generated': f'mkdir -p {FIX} && cp {SHOT8}/bgn_23.png {FIX}/shot8_bgn_23.png',
        },
        {
            'path': f'{FIX}/shot8_bgn_23_inpaintmask.png',
            'generated': f'mkdir -p {FIX} && cp {SHOT8}/bgn_23_inpaintmask.png {FIX}/shot8_bgn_23_inpaintmask.png',
            'note': 'the mask the shot8 fill was actually driven with — the measured fill case (harmonise_fill.py: 57-64 % '
            'of the surrounding high-frequency energy)',
        },
    ]
)

MEMBRANE_REASON = (
    'tone_membrane.py is a deterministic tone step, not a generator: it takes a plate, a fill and the '
    'raw matte and nulls the fill-vs-painting tone step along the hole rim. It has no prompt, paints '
    'nothing, invents nothing and cannot repair anything — so this question has nothing to measure on '
    'this row. It is kept as a row because it is the only thing in the house that fixes the rim step '
    'cv2.seamlessClone could not, and the sheet needs that receipt.'
)
MEMBRANE_BANDS = [
    'Render: People',
    'Render: The body',
    'Render: Food',
    'Render: Damage & wear',
    'Render: Text & number',
    'Render: Objects',
    'Render: Animals',
    'Render: Nature & weather',
    'Render: Built environment',
    'Render: Clothing',
    'Capacity',
    'Counting & quantity',
    'Space & relation',
    'Attributes',
    'Prompt: damage',
    'Prompt: clarity needed',
    'Prompt: limits',
    'Prompt: steering',
]
MEMBRANE_NA = [
    'hands',
    'faces_fix',
    'objects',
    'add_object',
    'extend',
    'text_fix',
    'style',
    'grain_match',
    'mask_source',
    'mask_soft',
    'mask_auto',
    'init',
]

TEST = {
    'step': 'inpaint',
    'version': '2026-09-30.1',
    'title': 'Six known-bad hands, one repair recipe, and the mask and the gate measured separately from the model',
    'purpose': (
        "Measure whether a repair fixes what it was pointed at, in the picture's own paint, without moving "
        'anything else — with the four numbers the Ledger intro proved were the real gates (patch_gate dab '
        '<= 4.5, the take-5 rim step 1.8/5.4, the grain energy ratio 0.85-1.15 scaled to figure area, and '
        "the plate law's outside-18 px byte-identity) and with the MASK and the GATE as columns in their "
        'own right, because both recorded failures on this sheet were a correct model driven by a wrong mask '
        'or checked in the wrong place.'
    ),
    'include_shared': 'image',
    'run_order': RUN_ORDER,
    'rows': {
        'flux_fill': {
            'transport': 'comfy',
            'model': '_comfy_workflows/hand_fixer_flux_fill.json (and flux_fill_inpaint.json for the '
            'whole-region variant)',
            'where': 'flux_fill_service.py Tier B — FluxFillPipeline / the Comfy graph',
            'note': 'black-forest-labs/FLUX.1-Fill-dev is under the BFL Non-Commercial License and '
            'licence_provenance.flux_paused() pauses it on a monetised channel, so this row may be '
            'unrunnable by policy rather than by capability; a licence pause writes `untested` with '
            'that as the reason, never `no`.',
            'budget': {
                'minutes': 240,
                'gpu_minutes': 240,
                'note': 'FLUX-Fill at 1024 is ~30 s a call on this box: 483 x 30 s = ~240 min',
            },
        },
        'qwen_inpaint': {
            'transport': 'comfy',
            'model': '_comfy_workflows/hand_fixer_qwen_inpaint.json',
            'where': 'flux_fill_service.py Tier A — Qwen-Image-2512 + InstantX ControlNet-Inpainting, '
            'both Apache-2.0; the licence-clean default and the engine every receipt above was '
            'measured on',
            'budget': {
                'minutes': 200,
                'gpu_minutes': 200,
                'note': 'Qwen inpaint measured ~25 s a call in the intro work: 483 x 25 s = ~200 min',
            },
        },
        'sdxl_fill': {
            'transport': 'comfy',
            'model': '_comfy_workflows/sdxl_img2img_lora.json driven as the SDXL inpaint path '
            '(inpaint_figure over the box, the route fix_hand.py uses for its restyle pass)',
            'where': f'sd_xl_base_1.0.safetensors + {LORA}, masked, over a Telea init',
            'note': 'the measured baseline to beat: at denoise 0.90 this path gave 1 usable hand in 4 seeds '
            '(one seed painted two hands, one erased the hand). At 0.40 over a Qwen-repaired hand '
            'it is the restyle pass and keeps every finger. The row is run at its production '
            'default and the trial records the denoise, so the cell can be read against that.',
        },
        'membrane': {
            'transport': 'builtin',
            'model': 'ledger_intro/intro/tone_membrane.py (harmonic rim-delta extension)',
            'where': 'tone_membrane.main on --bg / --picture / --matte-raw, no prompt',
            'na_bands': {'reason': MEMBRANE_REASON, 'bands': MEMBRANE_BANDS},
            'na': {c: MEMBRANE_REASON for c in MEMBRANE_NA},
            'note': 'the columns this row DOES answer are the ones it exists for: seams, tone_match, '
            'colour_match, check_band and no_drift. It is the only row whose rim step is ~0 by '
            'construction, and the only one whose no_drift is a proof rather than a measurement '
            '(beyond 18 px of the raw matte the field is multiplied by zero).',
            'budget': {
                'calls': 8,
                'minutes': 4,
                'gpu_minutes': 0,
                'operator_minutes': 6,
                'note': 'the five v5 plates + shot8 + the p5 control + one repeat = 8 CPU calls at '
                '~30 s each (numpy/OpenCV, a laplace solve on one rectangle); no GPU, no '
                'subject bank (every Render band is na on this row), 12 blind decisions',
            },
        },
    },
    'probes': PROBES,
    'derive': {},
    'lookup': {},
    'wiring': {
        'init': {
            'from': (
                'read off flux_fill_service.py: Tier C is OpenCV TELEA (deterministic, CPU, instant) and it '
                'is what seeds the masked region before the SDXL fill — a black or noise init on this path '
                'produces a grey blob at low denoise. The cell records, per row, which init its workflow '
                "JSON actually wires: Telea, the plate's own pixels, latent noise, or nothing."
            ),
            'grade': 'assumed',
            'note': 'wiring, not a probe: an init is a code path, and running a render would measure the '
            'sampler, not the init. The standing fact is that SDXL fill needs a Telea init.',
        },
    },
    'na': {},
    'fixtures': FIXTURES,
    'budget': {
        'calls': 483,
        'tokens_in': 0,
        'tokens_out': 0,
        'tokens_note': 'every row is an image-in / image-out graph or a deterministic CPU step: the instructions are '
        'fixed strings in this file, no language model is called and no Claude week is spent',
        'minutes': 95,
        'gpu_minutes': 95,
        'operator_minutes': 260,
        'note': (
            'DOMAIN 87 calls: ip_hands 7 hands (6 bad + 1 control) x 3 seeds = 21, ip_faces 3 x 3 = 9, '
            'ip_remove 2 x 3 = 6, ip_add 2 x 3 = 6, ip_extend 2 x 3 = 6, ip_text 1 x 3 = 3, ip_join 3 plates x 3 '
            '= 9, ip_mask_source 2 masks x 2 plates x 3 = 12, ip_mask_soft 3 feathers x 3 = 9, ip_mask_auto 6 x 1 '
            '= 6 (CPU only), ip_check_band 0 and ip_no_drift 0 (both measured on pictures the probes above '
            'already made) = 87. SHARED BANK: 132 subjects x 3 seeds = 396 renders plus the capacity and prompt '
            'probes the bank already counts. 87 + 396 = 483 calls per row at ~12 s for a 1024 masked SDXL pass = '
            '~95 min wall, all on the GPU (per-row overrides: Qwen ~25 s, FLUX-Fill ~30 s, membrane 8 CPU calls '
            "in 4 min). OPERATOR: the bank's 396 subject decisions + ~124 domain decisions (ip_hands 2 questions "
            'x 21 = 42, ip_join 2 x 9 = 18, ip_mask_source 12, ip_mask_soft 9, ip_faces 9, ip_mask_auto 6, '
            'ip_remove 6, ip_add 6, ip_extend 6, ip_text 3, and the paired plates counted once) = ~520 decisions '
            'x 30 s = ~260 min. No Claude meter is touched by any row.'
        ),
    },
    'notes': [
        'The six bad hands are not invented test material: they are the five regions the operator rejected on stills '
        "v5 with patch_gate's measured dab/tex beside each, plus p2's unmeasured hand. The APPROVED p5 page hand "
        '(dab 2.63 / tex 1.85) is run as a CONTROL through the same recipe and must come back unchanged — a row that '
        '"improves" a hand nobody asked about has failed no_drift, which is a thing a repair service does.',
        "patch_gate's texture ratio is ADVISORY everywhere in this test. Its own calibration says so: p4's page hand "
        'measured tex 1.29 and still read photographic to the operator. The chroma bound is the gate; the eye is the '
        'judge of brushwork.',
        'mask_source and check_band are the two columns this sheet exists for. Both of the failures already on it were '
        'a correct model with a wrong mask or a gate looking 40 px away from the seam, and neither is visible in any '
        'cell about the model. They are measured by CHANGING the mask and MOVING the band, not by reading the code.',
        'grain_match is the one threshold that needed a decision rather than a receipt: the receipts give 0.57-0.64 '
        'for a smooth fill and 1.23 for a fill pushed into inventing objects, so [0.85, 1.15] is the band between '
        'them. It is stated here so the next author can move it on evidence rather than by feel.',
        'The `membrane` row is na on twelve of the seventeen domain columns and on every Render band. That is not '
        'twelve failures: it is a deterministic tone step with no prompt, kept on the sheet because it is the only '
        'thing that removed the rim step seamlessClone could not.',
    ],
}
