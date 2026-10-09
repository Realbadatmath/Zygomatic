# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""upscale — the default test. 2026-09-30.

The sheet's own limitation, written before this test existed: "The upscaler is used in
production but has never been scored against an original at full resolution, so 'invents
nothing' is untested rather than assumed safe." That sentence is the whole design here.

The shape
---------
Every picture question is asked as a COMPARISON against something that already exists, never
as a judgement of a lone output:
  * `up_invention` is the one that closes the sheet's limitation. A 2048 original is BOX
    DOWNSAMPLED to 1024, the row upscales it x2 back to 2048, and the result is scored against
    the original it was made from. There is a ground truth for every pixel, so SSIM/PSNR mean
    something, and `restoration_qc`'s own residual-against-LANCZOS delta runs beside them.
  * Every other picture probe carries a LANCZOS arm at the same output size. LANCZOS is the
    null hypothesis: an upscaler that only softens is worse than free, and "adds real detail"
    means "beats LANCZOS on edge rise", not "looks big".
  * Nothing is judged by a VLM. The defect-judge bench of 2026-09-27 scored 2/8 on the defects
    that matter, and the defects an upscaler makes — a waxy cheek, a ringed rope, an invented
    brick — are exactly that class. Where a detector exists it runs; the rest is an OPERATOR
    blind decision on a 200 % crop, question written here, asked word for word.

The two rows are not two upscalers
----------------------------------
`realesrgan` is the house upscaler (BSD-3-Clause, x2 in `image_esrgan_upscale.json`, and the
same weights per chunk in `video_finish.esrgan_clip`). `restoration_qc` UPSCALES NOTHING: it
is the gate that reads a (source, upscaled) pair and says whether the upscale invented. Its
cells therefore answer a different question in the same column — DOES THE GATE CATCH IT — and
its checks read a verdict, not pixels. Every Render band and the Capacity band are `na` on
that row with the reason written out: it returns a number, not a picture. Where the gate has
no opinion at all (grain, waxiness, scale factors, flicker) the column is `na` and says why,
because a gate that cannot see a thing must not be scored as if it passed it.

Neither row has a prompt. ESRGAN is a convolution on an image and the QC is a function on two
files, so the four Prompt bands are `na_bands` at STEP level with one reason: there is no text
on either path to damage, lengthen, reorder or weight.

Determinism
-----------
ESRGAN is deterministic — same file in, same file out — so repeats here are FIXTURE FRAMES,
not seeds. Every probe's `repeats` is the number of distinct frames it runs on and the
`conditions` say so, because three passes over one frame would be one measurement written
three times.

WHAT IS HONESTLY BLOCKED
    Nine fixtures do not exist yet. Each is declared with the exact recipe that cuts it from
    approved house output and `verified: False`, so the columns it feeds are written untested
    "key unverified" until an operator has looked at the frames. The ground-truth set is the
    load-bearing one: if a "2048 original" is itself an upscale, `up_invention` measures
    nothing and would look like a pass.
"""

from __future__ import annotations

# Kinds this module adds. Named for what they measure, not for the column they serve.
CHECK_KINDS = {
    'ssim_min': 'SSIM (gaussian window 11, sigma 1.5, luma) between the output and the ground-truth original at the same size >= `min`',
    'psnr_min': 'PSNR in dB between the output and the ground-truth original at the same size >= `min`',
    'restoration_delta_max': 'restoration_qc.measure_pair(source, output)["delta"] — residual against the LANCZOS control arm — <= `max`',
    'edge_rise_ratio_max': 'mean 10-90 % rise width across the strongest `edges` edges, output divided by the LANCZOS arm at the same size, <= `max` (a real sharpening narrows the rise)',
    'edge_overshoot_max': 'across the strongest `edges` edges, the largest excursion beyond the local source min/max as a fraction of the edge amplitude, <= `max` (ringing)',
    'grain_ratio_range': 'radially averaged power spectrum of the luma inside `band` (cycles per SOURCE pixel), output resampled to the source size, energy ratio out/in within [`min`, `max`]',
    'identity_cosine_pair_min': 'ArcFace (buffalo_l) cosine between the largest face in the output and the largest face in the SOURCE frame >= `min`',
    'landmark_shift_max_px': 'MediaPipe hand_landmarker on both frames: every one of the 21 landmarks of each matched hand moves <= `max` pixels measured in SOURCE pixels',
    'seam_energy_max': 'mean gradient magnitude inside a `width`-px band centred on every `tile`-px tile border of the output, divided by the median gradient magnitude of the whole output, <= `max`',
    'temporal_flicker_max': 'mean |frame - previous frame| over the clip, output series mean divided by the LANCZOS series mean, <= `max`',
    'judge_verdict_equals': 'restoration_qc.judge(source, output)["verdict"] equals `expect` (pass|fail|unknown)',
    'judge_separates': "over the trial's two arms, every clean pair's delta is below every planted pair's delta (no overlap) and the gap is >= `gap`",
}

FX = 'capability_tests/fixtures/upscale'
GT2048 = FX + '/gt_2048'  # the ground truth. Nothing else on this sheet matters as much.
SRC1024 = FX + '/src_1024'  # GT box-downsampled x2 — the input every invention probe takes
FACES = FX + '/faces_1024'
HANDS = FX + '/hands_1024'
TEXT = FX + '/text_1024'
PAINT = FX + '/painting_1024'
GRAIN = FX + '/grain_1024'
DEGRADED = FX + '/degraded_1024'
CLIP10 = FX + '/clip_10f'
PLANTED = FX + '/planted_pairs'  # (source, upscale-with-a-planted-invention) for the gate row

# The house path under test, read off the workflow and the video leg — copied into every trial.
RUN = {
    'workflow': '_comfy_workflows/image_esrgan_upscale.json',
    'graph': 'LoadImage(10) -> UpscaleModelLoader(11) -> ImageUpscaleWithModel(12) -> SaveImage(50)',
    'model': 'RealESRGAN_x2.pth',
    'video': 'video_finish.esrgan_clip(src, dst, scale=2) — CHUNK_FRAMES 33, CRF 12, same weights',
    'control': 'LANCZOS resize of the SAME source to the SAME output size (PIL Image.LANCZOS), written beside every output',
    'note': (
        'the LANCZOS arm is the instrument, not a courtesy. Without it "adds detail" cannot be told from '
        '"made bigger", and restoration_qc\'s own delta is defined against exactly this arm.'
    ),
}

LANCZOS_NOTE = 'the LANCZOS arm is produced from the same source at the same output size and measured identically'
DETERMINISTIC = (
    'ESRGAN is deterministic: repeats here are distinct fixture FRAMES, one pass each, never the same frame twice'
)

ROWS = ['realesrgan', 'restoration_qc']
UP = ['realesrgan']
QC = ['restoration_qc']

CROP200 = (
    'the operator is shown a 200 % crop of the same 512x512 region of both frames, side by side, '
    'unlabelled and in random order; metadata stripped; maybe counts as no'
)


def _p(pid, title, feeds, checks, rows, fixture, repeats, **kw):
    p = {
        'id': pid,
        'title': title,
        'feeds': list(feeds),
        'inputs': {'fixture': fixture, 'run': dict(RUN)},
        'conditions': {'repeats': repeats, 'note': DETERMINISTIC + '; ' + LANCZOS_NOTE},
        'checks': list(checks),
        'grade': 'measured',
        'rows': list(rows),
    }
    p.update(kw)
    return p


PROBES = [
    # ── The result ────────────────────────────────────────────────────────────────────────
    _p(
        'up_invention',
        'Invents nothing that was not in the original',
        ['invention'],
        [
            {'check': 'ssim_min', 'min': 0.90},
            {'check': 'psnr_min', 'min': 28.0},
            {'check': 'restoration_delta_max', 'max': 0.018911},
            {
                'check': 'operator',
                'blind': True,
                'question': 'Left is the original photograph, right is a machine enlargement of a shrunken copy of it. Is there anything in the right picture — a brick, a strand of hair, a letter, a highlight — that is NOT in the left one? yes/no (yes = it invented)',
            },
        ],
        UP,
        SRC1024,
        6,
        state_rule={'yes': 1.0, 'partial': 0.5},
        state_note=(
            'THE COLUMN THIS SHEET WAS MISSING. All six frames must hold: one invented window pane in six '
            'frames is an upscaler that invents. 0.018911 is restoration_qc.DEFAULT_DELTA_FLOOR, the house '
            "floor set at the incumbent's worst measured residual x 1.5 — a delta above it is signal that "
            'does not survive a box downsample, which is the definition of invention here. The operator arm '
            'exists because an invention can be perfectly self-consistent and cost almost no SSIM.'
        ),
    ),
    _p(
        'up_detail',
        'Adds real detail',
        ['detail'],
        [
            {'check': 'edge_rise_ratio_max', 'edges': 200, 'max': 0.80},
            {
                'check': 'operator',
                'blind': True,
                'question': 'These two 200 % crops are the same picture enlarged two different ways. Does one of them show detail the other does not — real surface, weave, grain, rope fibre — rather than just being sharper at the edges? yes/no, and which',
            },
        ],
        UP,
        SRC1024,
        6,
        conditions={'repeats': 6, 'note': DETERMINISTIC + '; ' + CROP200},
        state_note=(
            'the mechanical arm asks only that edges rise in 80 % of the LANCZOS width — that is sharpening, '
            'which is necessary and not sufficient. The operator decides DETAIL, because sharpening an empty '
            'gradient produces a crisp edge and no information. Both arms must pass.'
        ),
    ),
    _p(
        'up_faces',
        'Does not alter a face',
        ['faces'],
        [
            {'check': 'identity_cosine_pair_min', 'min': 0.70},
            {
                'check': 'operator',
                'blind': True,
                'question': 'These two 200 % crops are the same face before and after enlargement. Has the FACE changed — different nose width, different eye shape, skin turned to wax, a new mole, teeth redrawn? yes/no (yes = it altered the face)',
            },
        ],
        UP,
        FACES,
        4,
        conditions={'repeats': 4, 'note': DETERMINISTIC + '; ' + CROP200},
        state_rule={'yes': 1.0, 'partial': 0.5},
        state_note=(
            'ArcFace cosine between the SAME face before and after must be >= 0.70 — far above the 0.45 '
            'used for a generated still against a reference set, because this is one face against itself and '
            'anything that moves it that far has redrawn it. The operator arm catches what ArcFace is blind '
            'to: wax skin, redrawn teeth, an erased pore field on a face whose geometry never moved.'
        ),
    ),
    _p(
        'up_hands',
        'Does not alter hands',
        ['hands_keep'],
        [
            {'check': 'hand_landmarks', 'hands': 2, 'min_tip_px': 12},
            {'check': 'landmark_shift_max_px', 'max': 4},
            {
                'check': 'operator',
                'blind': True,
                'question': 'These two 200 % crops are the same pair of hands before and after enlargement. Count the fingers on each hand in BOTH pictures. Is the count the same, and is every finger still separate? yes/no (no = the enlargement fused or grew a finger)',
            },
        ],
        UP,
        HANDS,
        4,
        conditions={'repeats': 4, 'note': DETERMINISTIC + '; ' + CROP200},
        state_rule={'yes': 1.0, 'partial': 0.5},
        state_note=(
            'the landmark arm is measured in SOURCE pixels so the x2 does not inflate it; 4 px is a finger '
            'that has not moved. MediaPipe is authority for "five distinct fingertips"; the operator is '
            'authority for fusion, because the landmarker happily reports 21 points on a mitten.'
        ),
    ),
    _p(
        'up_text',
        'Keeps lettering readable',
        ['text_keep'],
        [
            {'check': 'ocr_contains', 'terms': ['DE GOUDEN LEEUW', '1671', 'ANNO']},
            {'check': 'ocr_lines_min', 'min': 2, 'min_chars': 4},
            {
                'check': 'operator',
                'blind': True,
                'question': 'Read the lettering in this 200 % crop out loud. Does it read as the SAME words as the crop beside it, with no letter turned into a different letter? yes/no',
            },
        ],
        UP,
        TEXT,
        4,
        conditions={'repeats': 4, 'note': DETERMINISTIC + '; ' + CROP200},
        state_note=(
            'the terms are the lettering painted into the fixture frames and pinned in its recipe, so the '
            'check is "the same words survive", not "OCR is confident". An upscaler that redraws a 6 as an 8 '
            'passes every pixel metric on this sheet and fails here — that is the point of the column.'
        ),
    ),
    _p(
        'up_artefacts',
        'No ringing or waxiness',
        ['artefacts'],
        [
            {'check': 'edge_overshoot_max', 'edges': 200, 'max': 0.08},
            {
                'check': 'operator',
                'blind': True,
                'question': 'In this 200 % crop, look along the hard edges — a mast against sky, a window frame. Is there a bright or dark halo running beside the edge, or has any surface gone smooth and plastic? yes/no (yes = ringing or waxiness)',
            },
        ],
        UP,
        SRC1024,
        6,
        conditions={'repeats': 6, 'note': DETERMINISTIC + '; ' + CROP200},
        state_note=(
            '8 % overshoot is the point at which a halo becomes visible at 100 % on the house monitor. Only '
            'ringing is mechanical here; WAXINESS has no detector the house trusts, so the operator arm is '
            'the only measurement of it and the cell cannot be yes without it.'
        ),
    ),
    _p(
        'up_texture',
        'Keeps brushwork as brushwork',
        ['texture_keep'],
        [
            {'check': 'grain_ratio_range', 'band': [0.10, 0.25], 'min': 0.70, 'max': 1.60},
            {
                'check': 'operator',
                'blind': True,
                'question': 'This 200 % crop is from a painting. Is it still plainly a painting — canvas weave, brush marks, paint edges — or has it been turned into a photograph of the thing depicted? yes/no (yes = still a painting)',
            },
        ],
        UP,
        PAINT,
        4,
        conditions={'repeats': 4, 'note': DETERMINISTIC + '; ' + CROP200},
        state_note=(
            'the mid band 0.10-0.25 cy/px is where brush marks live at 1024. A ratio under 0.70 is brushwork '
            'erased, over 1.60 is brushwork invented as texture. The operator decides "photo-ified", which is '
            'a change of KIND that a power spectrum can miss entirely.'
        ),
    ),
    _p(
        'up_grain',
        'Keeps film grain',
        ['grain_keep'],
        [
            {'check': 'grain_ratio_range', 'band': [0.25, 0.50], 'min': 0.70, 'max': 1.40},
            {
                'check': 'operator',
                'blind': True,
                'question': 'These two 200 % crops are the same grainy frame before and after enlargement. Does the grain still look like grain, in the same amount, or has it been smoothed away or replaced by a regular pattern? yes/no (yes = grain kept)',
            },
        ],
        UP,
        GRAIN,
        4,
        conditions={'repeats': 4, 'note': DETERMINISTIC + '; ' + CROP200},
        state_note=(
            'band 0.25-0.50 cy/px measured on the SOURCE scale, so the x2 does not move the grain into a '
            'different band by arithmetic. Under 0.70 is denoise the operator did not ask for; over 1.40 is '
            'grain the model added. Both are a no, and the direction is written into the cell.'
        ),
    ),
    # ── Range ─────────────────────────────────────────────────────────────────────────────
    _p(
        'up_max_out',
        'Largest usable output',
        ['max_out'],
        [
            {'check': 'render_returned'},
            {'check': 'image_size', 'width': "the rung's expected width", 'height': "the rung's expected height"},
            {'check': 'log_warns', 'pattern': '(?i)out of memory|allocation failed|tiled'},
            {
                'check': 'operator',
                'blind': True,
                'question': 'Does this output show a grid of square patches that do not match at their borders? yes/no (yes = it only got there by tiling and the tiling shows)',
            },
        ],
        UP,
        SRC1024,
        4,
        conditions={
            'repeats': 4,
            'note': 'four rungs, one frame each: 1024->2048, 2048->4096, 4096->8192, 8192->16384. The ladder stops at the first rung that errors or OOMs and the cell reports the last rung that returned a clean frame',
        },
        state_rule={'yes': 0.75, 'partial': 0.25},
        state_note=(
            '"usable" is not "did not crash": a rung counts only if the frame comes back, is exactly the '
            'expected size, and shows no seam grid. The log arm is there because ComfyUI tiles silently when '
            'VRAM runs short, which turns a max_out answer into a tiling answer without saying so.'
        ),
    ),
    _p(
        'up_tiling',
        'Tiles without seams',
        ['tiling'],
        [
            {'check': 'seam_energy_max', 'tile': 512, 'width': 3, 'max': 1.25},
            {
                'check': 'operator',
                'blind': True,
                'question': 'Look along the horizontal and vertical lines that cut this picture into equal squares. Can you see any of those lines — a step in brightness, a break in a plank or a rope? yes/no',
            },
        ],
        UP,
        SRC1024,
        6,
        state_rule={'yes': 1.0, 'partial': 0.5},
        state_note=(
            '1.25 means the 3-px band over a tile border may carry at most 25 % more gradient than the '
            "picture's median — a real seam runs 2-4x. Six frames, all must hold: a seam that shows on one "
            'frame in six is a seam. The tile size is 512 because that is what the house graph falls back to '
            'under VRAM pressure.'
        ),
    ),
    _p(
        'up_video',
        'Stable across video frames',
        ['video_frames'],
        [
            {'check': 'temporal_flicker_max', 'max': 1.15},
            {
                'check': 'operator',
                'blind': True,
                'question': 'Play these ten frames as a loop. Does any surface — a wall, a sail, a face — shimmer, crawl or change texture from frame to frame while the camera barely moves? yes/no (yes = it flickers)',
            },
        ],
        UP,
        CLIP10,
        1,
        conditions={
            'repeats': 1,
            'note': 'ONE clip of ten consecutive frames through video_finish.esrgan_clip; the ten frames ARE the measurement, so a second pass would repeat it, not extend it',
        },
        state_rule={'yes': 1.0, 'partial': 0.5},
        state_note=(
            'per-frame difference energy no more than 15 % above the LANCZOS arm on the same ten frames. A '
            'per-frame upscaler with no temporal term is expected to fail this; the cell exists so the sheet '
            'says so in a number instead of in a habit. The operator arm decides, because slow crawl can sit '
            'under the ratio and still be unwatchable.'
        ),
    ),
    _p(
        'up_restore',
        'Repairs a degraded source',
        ['restore'],
        [
            {'check': 'ssim_min', 'min': 0.80},
            {
                'check': 'operator',
                'blind': True,
                'question': 'This picture was made from a small, heavily compressed copy. Are the blocky squares and mosquito noise of that compression gone, without the picture having become a smooth cartoon of itself? yes/no',
            },
        ],
        UP,
        DEGRADED,
        4,
        state_rule={'yes': 0.75, 'partial': 0.5},
        state_note=(
            'scored against the CLEAN original the degraded copy was made from, at 0.80 rather than the 0.90 '
            'of up_invention: the input has genuinely lost information here and demanding the same fidelity '
            'would be demanding invention. Three of four frames is a yes.'
        ),
    ),
    # ── the gate row: does restoration_qc CATCH it ────────────────────────────────────────
    _p(
        'rq_invention',
        'The gate catches an invented detail',
        ['invention'],
        [{'check': 'judge_verdict_equals', 'expect': 'fail'}, {'check': 'judge_separates', 'gap': 0.010}],
        QC,
        PLANTED,
        8,
        conditions={
            'repeats': 8,
            'note': 'four CLEAN pairs (source, honest x2) and four PLANTED pairs (the same honest x2 with one 64x64 region redrawn); the gate is given all eight in random order and never told which is which',
        },
        state_rule={'yes': 1.0, 'partial': 0.5},
        state_note=(
            'the column on this row means "would this gate have stopped it". All four planted pairs must '
            'come back fail and all four clean pairs pass — and the two populations must not touch, with at '
            'least 0.010 of delta between the highest clean and the lowest planted. A gate whose populations '
            'overlap has a threshold, not a measurement, which is why restoration_qc reports tile separation '
            'beside its verdict in the first place.'
        ),
    ),
    _p(
        'rq_detail',
        'The gate does not cry wolf on real detail',
        ['detail'],
        [{'check': 'judge_verdict_equals', 'expect': 'pass'}],
        QC,
        SRC1024,
        6,
        conditions={
            'repeats': 6,
            'note': 'the six honest x2 outputs of up_invention, each judged against the source they were made from',
        },
        state_rule={'yes': 1.0, 'partial': 0.5},
        state_note=(
            'a gate that fails an honest upscale is worse than no gate, because it is switched off within a '
            'week. This cell is the false-positive rate, measured on the same six frames the upscaler row '
            'passes. It does NOT say the gate can see detail — the gate sees only what fails to survive a '
            'box downsample — and the cell text must say that.'
        ),
    ),
    _p(
        'rq_faces',
        'The gate catches an altered face',
        ['faces'],
        [{'check': 'judge_verdict_equals', 'expect': 'fail'}],
        QC,
        PLANTED,
        4,
        conditions={
            'repeats': 4,
            'note': 'four pairs whose PLANTED region is the face: eye shape, nose width, teeth redrawn (the recipe pins which)',
        },
        state_rule={'yes': 1.0, 'partial': 0.5},
        state_note=(
            'the honest expectation is that it does NOT: a face alteration is small in area and the residual '
            'is a whole-frame mean, so this is the cell that tells an operator whether the gate protects '
            'faces or only large areas. A `no` here is a finding, not a defect in the test.'
        ),
    ),
    _p(
        'rq_text',
        'The gate catches redrawn lettering',
        ['text_keep'],
        [{'check': 'judge_verdict_equals', 'expect': 'fail'}],
        QC,
        PLANTED,
        4,
        conditions={
            'repeats': 4,
            'note': 'four pairs whose PLANTED region is the signboard, one glyph changed (6 -> 8 in the date, E -> F in the name)',
        },
        state_rule={'yes': 1.0, 'partial': 0.5},
        state_note=(
            'one glyph is the smallest alteration that matters in production and the hardest for a mean '
            'residual to see. Measured, not assumed, for the same reason as rq_faces.'
        ),
    ),
    _p(
        'rq_tiling',
        'The gate sees a seam',
        ['tiling'],
        [{'check': 'judge_separates', 'gap': 0.005}],
        QC,
        PLANTED,
        8,
        conditions={
            'repeats': 8,
            'note': 'four seamless pairs and four whose x2 was produced in 512 tiles with the borders left unblended; restoration_qc.tile_separation is read beside the delta',
        },
        state_rule={'yes': 1.0, 'partial': 0.5},
        state_note=(
            'restoration_qc already reports tile separation, and it reports it BECAUSE the two populations '
            'overlapped when it was calibrated. This cell re-measures that on planted seams so the sheet '
            'says how far apart they are today rather than repeating the calibration note.'
        ),
    ),
    _p(
        'rq_restore',
        'The gate reads a repaired source honestly',
        ['restore'],
        [{'check': 'judge_verdict_equals', 'expect': 'unknown'}],
        QC,
        DEGRADED,
        4,
        conditions={
            'repeats': 4,
            'note': 'the four repaired frames of up_restore, judged against the DEGRADED source they were repaired from',
        },
        state_rule={'yes': 0.75, 'partial': 0.5},
        state_note=(
            'a repair legitimately adds signal the degraded source cannot account for, so a gate calibrated '
            'on faithful upscales must say `unknown` rather than `fail`. If it says fail, the gate cannot be '
            'used on the restoration path at all, and that is the sentence the cell must carry.'
        ),
    ),
]

LOOKUP = {
    'factor': {
        'source': 'video_finish.ESRGAN_MODELS and the weights on disk under the ComfyUI upscale_models store',
        'revision': '_comfy_workflows/image_esrgan_upscale.json pins RealESRGAN_x2.pth in UpscaleModelLoader(11), as of 2026-09-30',
        'requires': ['_comfy_workflows/image_esrgan_upscale.json', 'video_finish.py'],
        'grade': 'receipt',
        'value': {
            'wired': [2, 4],
            'default': 2,
            'mapping': 'ESRGAN_MODELS = {2: RealESRGAN_x2.pth, 4: RealESRGAN_x4plus.pth}',
            'note': (
                'the factor is the WEIGHTS, not a parameter: there is no arbitrary scale on this path. '
                'Anything other than x2 or x4 is a resize after the fact and must not be written into '
                'this cell as if the model produced it.'
            ),
        },
        'state_note': 'a receipt for what is wired in the house graph, not a claim about what upstream Real-ESRGAN ships. x2 is what production runs; x4 is present but unused by the still path.',
    },
    'denoise_side': {
        'source': 'the workflow graph itself — LoadImage -> UpscaleModelLoader -> ImageUpscaleWithModel -> SaveImage',
        'revision': '_comfy_workflows/image_esrgan_upscale.json, 4 nodes, as of 2026-09-30',
        'requires': ['_comfy_workflows/image_esrgan_upscale.json'],
        'grade': 'receipt',
        'value': {
            'lever': False,
            'reading': (
                'there is no denoise input on this path: ImageUpscaleWithModel takes an image and a '
                'model and nothing else. Whatever denoising the weights do is baked in and cannot be '
                'turned down, so "denoise is optional" is NO on this row as wired.'
            ),
        },
        'state_note': (
            'a NO that is a receipt, not a failure to measure. The upstream dni interpolation between '
            'x4plus and x4plus-anime would give a lever, but it is not in this graph and the cell must '
            'not imply that it is.'
        ),
    },
}

# The gate row cannot be scored on these at all. Every reason says what the instrument is blind to.
QC_NA = {
    'hands_keep': 'restoration_qc measures one whole-frame residual against a box downsample; it has no hand model, no landmarks and no notion of a finger, so it cannot be asked whether hands were preserved.',
    'artefacts': 'ringing and waxiness are edge-local and shape-free; the gate returns a single mean residual number, which a halo barely moves and a waxed surface LOWERS. Scoring it here would read as a pass for the wrong reason.',
    'texture_keep': 'the gate has no notion of medium. A painting turned into a photograph can be perfectly faithful under a box downsample, so this column would be a pass on an output the operator would reject.',
    'grain_keep': 'grain is exactly the signal a box downsample destroys in BOTH arms, so it cancels out of the residual. The gate is structurally blind to whether grain survived.',
    'factor': 'this row does not scale anything: it reads a pair of files that already exist. There is no scale factor on this path to report.',
    'max_out': 'the gate has no output size of its own — it returns a number. The largest frame it can READ is a numpy memory question and not what this column asks.',
    'denoise_side': "there is no denoise lever on a measurement function; the column is about an upscaler's controls and this row is not an upscaler.",
    'video_frames': 'restoration_qc.measure_pair takes exactly one (source, upscaled) pair and carries no previous frame, so flicker — which only exists between frames — is invisible to it.',
}

QC_BANDS = {
    'reason': (
        'restoration_qc renders nothing. It reads a source and an upscaled frame and returns a residual, a '
        'tile separation and a verdict, so every "renders X correctly" question and every capacity question '
        'would be scoring a picture this row never produced. The column is not unmeasured; there is nothing '
        'here for it to be about.'
    ),
    'bands': [
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
    ],
}

NO_PROMPT = {
    'reason': (
        'nothing on this sheet takes text. RealESRGAN is a convolution on an image (LoadImage -> '
        'ImageUpscaleWithModel, no CLIP node in the graph) and restoration_qc is a function on two files, so '
        'there is no instruction to damage, lengthen, reorder or weight. The column is not unmeasured; there '
        'is no prompt on either path for it to be about.'
    ),
    'bands': ['Prompt: damage', 'Prompt: clarity needed', 'Prompt: limits', 'Prompt: steering'],
}

TEST = {
    'step': 'upscale',
    'version': '2026-09-30.1',
    'title': 'The default test for the upscale step',
    'purpose': (
        'score an upscaler against an ORIGINAL at full resolution — the thing the sheet says has never been '
        'done — and score the gate that is supposed to catch it when the upscaler invents.'
    ),
    'include_shared': 'image',
    'na_bands': NO_PROMPT,
    'run': RUN,
    'rows': {
        'realesrgan': {
            'transport': 'comfy',
            'where': '_comfy_workflows/image_esrgan_upscale.json (RealESRGAN_x2.pth) for stills; video_finish.esrgan_clip for the video leg',
            'model': 'RealESRGAN x2 — the house upscaler, BSD-3-Clause',
            'budget': {
                'calls': 470,
                'minutes': 78,
                'gpu_minutes': 52,
                'operator_minutes': 32,
                'note': 'the shared bank is 132 subjects x 3 seeds = 396 upscales of the stored subject frames at ~4 s = ~27 min, + 36 capacity upscales ~3 min; this module adds ~62 passes (6+6+4+4+4+6+4+4 pictures, 4 max_out rungs, 6 tiling, 10 video frames, 4 restore) with a LANCZOS arm each at ~4 s = ~9 min, + ~39 min of load, queue and metric time. 64 blind decisions here at 30 s = 32 min; the bank charges its own ~500 separately.',
            },
        },
        'restoration_qc': {
            'transport': 'service',
            'where': 'restoration_qc.py — measure_pair / judge / tile_separation, DEFAULT_DELTA_FLOOR 0.018911',
            'model': 'restoration_qc: the in-house invention gate (residual against a LANCZOS control arm), not an upscaler',
            'na': QC_NA,
            'na_bands': QC_BANDS,
            'budget': {
                'calls': 34,
                'minutes': 5,
                'gpu_minutes': 0,
                'operator_minutes': 0,
                'note': '34 measure_pair calls on frames the realesrgan row has already produced, in numpy on the CPU at ~4 s a pair for a 2048 frame including the LANCZOS control = ~3 min, + ~2 min of fixture reads. No blind decisions: every check on this row reads a verdict the module returns.',
            },
        },
    },
    'probes': PROBES,
    'derive': {},
    'lookup': LOOKUP,
    'wiring': {},
    'na': {},
    'fixtures': [
        {
            'path': GT2048,
            'verified': False,
            'blocks': ['invention', 'detail', 'artefacts', 'tiling', 'max_out', 'restore'],
            'generated': (
                'six 2048x2048 frames that are ORIGINALS, never upscales: the six operator-passed seed-11 '
                'frames of the t2i default test rendered at 2048 native (render_person_one, render_hand_two, '
                'render_broken_wood, render_food_table, render_built_quay, render_nature_sky), copied here '
                'as 000.png..005.png with a MANIFEST.json holding each source render id and its sha256.'
            ),
            'how_to_verify': (
                'THE LOAD-BEARING ONE. For each frame confirm from the run ledger that it was RENDERED at '
                '2048 and not enlarged from 1024 — an upscaled "original" makes up_invention score an '
                'upscale against an upscale and pass. Then look at all six at 100 %: sharp, no ESRGAN '
                'halo, no tile grid. Set verified = true only then.'
            ),
        },
        {
            'path': SRC1024,
            'verified': False,
            'blocks': ['invention', 'detail', 'artefacts', 'tiling', 'max_out'],
            'generated': (
                'each frame of ' + GT2048 + ' box-downsampled by exactly 2 (PIL Image.BOX, 2048 -> 1024) and '
                'saved as PNG under the same stem. BOX, not LANCZOS: the downsample must be the exact '
                'inverse restoration_qc uses, or the residual measures the resampler and not the upscaler.'
            ),
            'how_to_verify': 'confirm each file is exactly 1024x1024, that its stem matches a ground-truth frame, and that re-running the downsample reproduces the same sha256 (it is deterministic).',
        },
        {
            'path': FACES,
            'verified': False,
            'blocks': ['faces'],
            'generated': (
                'four 1024x1024 frames, each with ONE face at least 256 px across: the operator-passed '
                'seed-11 frames of render_face_front, render_face_three_quarter, render_elderly and '
                'render_child from the t2i default test, box-downsampled to 1024 if larger.'
            ),
            'how_to_verify': 'run ArcFace on each: exactly one face must be found, at least 256 px wide. A frame with two faces makes "the largest face" ambiguous and the cosine meaningless.',
        },
        {
            'path': HANDS,
            'verified': False,
            'blocks': ['hands_keep'],
            'generated': (
                'four 1024x1024 frames showing TWO hands with all ten fingers separate and visible: the '
                'operator-passed frames of render_hand_two, render_hand_holding, render_hand_gripping and '
                'render_fingers_count.'
            ),
            'how_to_verify': 'MediaPipe must already find 2 hands x 21 landmarks with 5 distinct fingertips on the SOURCE of each frame. A source the landmarker cannot read makes the shift check unmeasurable and the column would silently be about the fixture.',
        },
        {
            'path': TEXT,
            'verified': False,
            'blocks': ['text_keep'],
            'generated': (
                'four 1024x1024 frames of painted signboards and carved dates in the house world, whose '
                'lettering is exactly DE GOUDEN LEEUW, ANNO 1671, the same in every frame at four different '
                'sizes (the smallest letters ~14 px tall, the largest ~80). Cut from the render_text_* '
                'frames of the t2i sheet or photographed from the set dressing, never typed on afterwards.'
            ),
            'how_to_verify': 'PaddleOCR on each SOURCE must already return those exact words. If OCR cannot read the source, the column measures OCR and not the upscaler; note the per-frame letter height in MANIFEST.json so a failure can be read as "it broke below N px".',
        },
        {
            'path': PAINT,
            'verified': False,
            'blocks': ['texture_keep'],
            'generated': (
                'four 1024x1024 crops of PAINTED surface with visible brushwork and canvas weave — the '
                'approved arcane_restyle output and the house painted-backdrop plates, at 1024 native.'
            ),
            'how_to_verify': 'at 200 % every frame must show individual brush marks or weave to the naked eye. A smooth digital painting has no brushwork to lose and would pass the column by having nothing to measure.',
        },
        {
            'path': GRAIN,
            'verified': False,
            'blocks': ['grain_keep'],
            'generated': (
                'four 1024x1024 frames carrying real film grain: four of the ' + GT2048 + ' frames '
                "box-downsampled to 1024 and passed through documentary_film_look's grain pass at its "
                'production strength, with the strength and seed written into MANIFEST.json.'
            ),
            'how_to_verify': 'measure the 0.25-0.50 cy/px band energy of each frame and record it in MANIFEST.json — that number is the denominator of every grain_keep ratio, so it must be pinned before any run, not recomputed per run.',
        },
        {
            'path': DEGRADED,
            'verified': False,
            'blocks': ['restore'],
            'generated': (
                'four of the ' + GT2048 + ' frames reduced to 512x512 (PIL BOX) and written as JPEG quality '
                '30, 4:2:0, then decoded back to PNG at 512. The CLEAN 2048 original stays the reference '
                'for ssim_min; the 512 JPEG is the input.'
            ),
            'how_to_verify': 'confirm the blocking is plainly visible at 100 % and that the pairing to the clean original is recorded by sha256 in MANIFEST.json — the ssim of this column is against the ORIGINAL, and a mispaired frame would score as a catastrophic failure.',
        },
        {
            'path': CLIP10,
            'verified': False,
            'blocks': ['video_frames'],
            'generated': (
                'ten CONSECUTIVE frames, 000.png..009.png at 1024x1024, extracted with ffmpeg from an '
                'approved house clip over a passage where the camera barely moves (a held shot, not a pan), '
                'with the source clip path and the frame numbers in MANIFEST.json.'
            ),
            'how_to_verify': 'play the ten as a loop BEFORE any upscale: the source itself must not shimmer. Source flicker would be measured as upscaler flicker and the column would be wrong in the direction that flatters nobody.',
        },
        {
            'path': PLANTED,
            'verified': False,
            'blocks': ['invention', 'faces', 'text_keep', 'tiling'],
            'generated': (
                'for each of the six honest x2 outputs: a CLEAN pair (source, output) and a PLANTED pair — '
                'the same output with one 64x64 region redrawn by hand. The recipe pins the region and the '
                'alteration per frame: an added window pane, a new rope strand, eye shape, nose width, teeth, '
                '6 -> 8 in the date, E -> F in the name. Plus four pairs whose x2 was produced in 512 tiles '
                'with the borders left unblended. Every pair is listed in MANIFEST.json with its planted '
                'region, its alteration and both sha256.'
            ),
            'how_to_verify': (
                'open each planted frame beside its clean twin and confirm the alteration is visible and '
                'is the ONLY difference — an edit that also changed exposure would be caught by the gate '
                'for the wrong reason and rq_invention would report a sensitivity the gate does not have.'
            ),
        },
    ],
    'budget': {
        'calls': 470,
        'tokens_in': 0,
        'tokens_out': 0,
        'tokens_note': 'no language model is called anywhere on this step: an upscaler is a convolution on an image and the gate is numpy on two files, so there is no prompt and no completion to count.',
        'minutes': 78,
        'gpu_minutes': 52,
        'operator_minutes': 32,
        'note': (
            'per row: the shared image bank is 396 subject upscales + 36 capacity upscales of the stored '
            'subject frames (~30 min at ~4 s each), this module adds ~62 passes each with its LANCZOS '
            'arm (~9 min) and ~39 min of model load, queue wait and metric computation (SSIM, LPIPS, '
            'ArcFace, MediaPipe, PaddleOCR and two FFTs per frame are most of it). 64 blind operator '
            "decisions at ~30 s = 32 min for this module; the bank's own ~500 decisions are charged in "
            'the bank. The restoration_qc row overrides all of it: 34 CPU calls, no GPU, no operator.'
        ),
    },
    'run_order': [
        'factor',
        'denoise_side',
        'rq_detail',
        'rq_invention',
        'rq_faces',
        'rq_text',
        'rq_tiling',
        'rq_restore',
        'up_invention',
        'up_detail',
        'up_artefacts',
        'up_tiling',
        'up_text',
        'up_faces',
        'up_hands',
        'up_grain',
        'up_texture',
        'up_restore',
        'up_max_out',
        'up_video',
    ],
    'notes': [
        'READ up_invention FIRST. It is the column the sheet says has never been answered, and every other picture cell is easier to read once it is known whether this upscaler adds things that were not there. It is also the cheapest real answer on the sheet: six frames, one pass each.',
        'restoration_qc is a gate, not an upscaler, and its cells answer "would this have been caught". A `no` on rq_faces or rq_text is a finding about the gate\'s blind spots, not a defect in the test — the gate was calibrated on whole-frame residuals and a 64x64 alteration is 0.1 % of a 2048 frame.',
        "run_order puts the two lookups and the whole gate row first: they need no GPU at all and the gate row runs on frames the upscaler row has to produce anyway, so a run stopped early still leaves the sheet with the two Range receipts and the gate's own sensitivity.",
        'On this step the shared bank is not a generation test. The row is handed the STORED subject frame (image_shared.subject_fixtures) and upscales it, so "renders one person correctly" reads as "the person is still correct after the enlargement". Those 132 columns are blocked until the t2i run has produced and an operator has passed the subject fixtures.',
        'SeedVR2 is deliberately NOT a row. It was tried and rejected, and a rejected candidate on a sheet of production tools reads as an option. Its receipt belongs in the sheet notes, not in a row that would be scored as if it were available.',
    ],
}
