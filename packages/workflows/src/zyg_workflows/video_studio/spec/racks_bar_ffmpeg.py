# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""RACKS, bottom bar — GRADE, FRAME, FINISH.

Moved verbatim (lines 1932-2586 of the old single-file spec.py). The ffmpeg
chain over the finished frames: colour, geometry, and the finishing pass.
"""

from ..options import _lut_options

_RACKS_BAR_FFMPEG = [
    # ══════════════════════ BOTTOM BAR — what is done to the finished frames
    # The ffmpeg half (grade, geometry, finishing, delivery), the QC probes and
    # the marked NOT BUILT list. Nothing here changes what the sampler makes.
    {
        'id': 'grade',
        'title': 'GRADE',
        'icon': 'ic-grade2',
        'place': 'bar',
        'sub': 'Per-channel colour, one dial at a time — the manual version of the '
        'Grade preset in LOOK. Real ffmpeg filters, applied in this order '
        'inside the finishing chain.',
        'params': [
            {
                'key': 'brightness',
                'type': 'knob',
                'label': 'Brightness',
                'def': 0.0,
                'min': -0.5,
                'max': 0.5,
                'step': 0.01,
                'icon': 'ic-brightness',
                'hint': 'eq=brightness. An additive lift, so it flattens the blacks '
                'rather than exposing up. Use Gamma to open the shadows.',
            },
            {
                'key': 'contrast',
                'type': 'knob',
                'label': 'Contrast',
                'def': 1.0,
                'min': 0.3,
                'max': 2.5,
                'step': 0.01,
                'icon': 'ic-contrast',
                'hint': 'eq=contrast, pivoting on mid grey.',
            },
            {
                'key': 'saturation',
                'type': 'knob',
                'label': 'Saturation',
                'def': 1.0,
                'min': 0.0,
                'max': 3.0,
                'step': 0.01,
                'icon': 'ic-saturation',
                'hint': 'eq=saturation. 0 is monochrome.',
            },
            {
                'key': 'gamma',
                'type': 'knob',
                'label': 'Gamma',
                'def': 1.0,
                'min': 0.3,
                'max': 3.0,
                'step': 0.01,
                'icon': 'ic-gamma',
                'hint': 'eq=gamma. Moves the midtones without touching black or '
                'white — the honest exposure control of the three.',
            },
            {
                'key': 'vibrance',
                'type': 'knob',
                'label': 'Vibrance',
                'def': 0.0,
                'min': -2.0,
                'max': 2.0,
                'step': 0.05,
                'icon': 'ic-vibrance',
                'hint': 'Saturates the muted colours and leaves the already-saturated '
                'ones alone — the safe version of Saturation on skin.',
            },
            {
                'key': 'hue_shift',
                'type': 'knob',
                'label': 'Hue shift',
                'def': 0.0,
                'min': -180.0,
                'max': 180.0,
                'step': 1.0,
                'unit': '°',
                'icon': 'ic-hue',
                'hint': 'hue=h. Rotates every hue in the frame. Small values only, '
                'unless the point is that skin should not be skin-coloured.',
            },
            {
                'key': 'color_temp',
                'type': 'knob',
                'label': 'Colour temp',
                'def': 6500.0,
                'min': 1000.0,
                'max': 40000.0,
                'step': 100.0,
                'unit': 'K',
                'icon': 'ic-temp',
                'hint': 'colortemperature. 6500K is neutral: below warms, above '
                'cools. This tints finished pixels — Light temperature in '
                'LOOK changes what was lit in the first place.',
            },
            {
                'key': 'tint',
                'type': 'knob',
                'label': 'Tint (green / magenta)',
                'def': 0.0,
                'min': -0.5,
                'max': 0.5,
                'step': 0.01,
                'icon': 'ic-tint',
                'hint': 'colorbalance on the green axis. Negative is magenta. The '
                'second half of a white balance, after Colour temp.',
            },
            {
                'key': 'lift',
                'type': 'knob',
                'label': 'Black lift',
                'def': 0.0,
                'min': -0.2,
                'max': 0.3,
                'step': 0.01,
                'icon': 'ic-lift',
                'hint': 'A curves point that raises or crushes the toe. Lifted '
                'blacks are most of what reads as "film" in a faded grade.',
            },
            {
                'key': 'lut',
                'type': 'select',
                'label': '3D LUT',
                'def': '',
                'icon': 'ic-lut',
                'options': _lut_options(),
                'hint': 'Applies a .cube LUT with lut3d. Drop .cube files into '
                'output/video_studio/_luts and they appear here after a '
                'restart. Empty when that folder is empty — which is the '
                'honest state, not a bug.',
            },
            {
                'key': 'deband',
                'type': 'toggle',
                'label': 'Deband',
                'def': False,
                'icon': 'ic-deband',
                'hint': 'Breaks up the stair-stepping that fp16 VAE decode leaves in '
                'flat gradients — skies, walls, fog.',
            },
            {
                'key': 'deflicker',
                'type': 'toggle',
                'label': 'Deflicker',
                'def': False,
                'icon': 'ic-deflicker',
                'hint': 'Averages luminance across neighbouring frames. Fixes the '
                'frame-to-frame exposure pumping Wan leaves on long clips; '
                'it cannot fix flicker that is in the detail.',
            },
            {
                'key': 'chroma_shift',
                'type': 'knob',
                'label': 'Chromatic aberration',
                'def': 0.0,
                'min': 0.0,
                'max': 8.0,
                'step': 0.5,
                'unit': 'px',
                'icon': 'ic-chroma',
                'hint': 'chromashift — offsets the red and blue planes in opposite '
                'directions. A lens artefact, so it reads as "photographed" '
                'in tiny amounts and as broken in large ones.',
            },
            {
                'key': 'bloom',
                'type': 'knob',
                'label': 'Bloom',
                'def': 0.0,
                'min': 0.0,
                'max': 1.0,
                'step': 0.05,
                'icon': 'ic-bloom',
                'hint': 'Screens a blurred copy of the frame over itself, so only '
                'the highlights glow. Runs as its own pass — it is the one '
                'finishing step that cannot live in the main chain.',
            },
        ],
    },
    {
        'id': 'frame',
        'title': 'FRAME',
        'icon': 'ic-crop',
        'place': 'bar',
        'sub': 'Geometry — reframing, movement added in post, and lens shape. '
        'Everything here happens after the render, so it cannot recover '
        'anything outside the frame.',
        'params': [
            {
                'key': 'crop_zoom',
                'type': 'knob',
                'label': 'Punch in',
                'def': 1.0,
                'min': 1.0,
                'max': 2.5,
                'step': 0.01,
                'unit': '×',
                'icon': 'ic-zoom',
                'hint': 'Scale up and crop back to the original size — a post punch-'
                'in. Costs resolution exactly in proportion.',
            },
            {
                'key': 'pan_x',
                'type': 'knob',
                'label': 'Reframe X',
                'def': 0.0,
                'min': -1.0,
                'max': 1.0,
                'step': 0.01,
                'icon': 'ic-panx',
                'hint': 'Where the punch-in sits horizontally. -1 is hard left. Does '
                'nothing at a punch-in of 1.0 — there is no slack to move in.',
            },
            {
                'key': 'pan_y',
                'type': 'knob',
                'label': 'Reframe Y',
                'def': 0.0,
                'min': -1.0,
                'max': 1.0,
                'step': 0.01,
                'icon': 'ic-pany',
                'hint': 'Vertical position of the punch-in. -1 is hard top.',
            },
            {
                'key': 'ken_burns',
                'type': 'select',
                'label': 'Post move',
                'def': 'off',
                'icon': 'ic-kenburns',
                'options': [
                    {'v': 'off', 'l': 'off'},
                    {'v': 'in', 'l': 'push in'},
                    {'v': 'out', 'l': 'pull out'},
                    {'v': 'left', 'l': 'pan left'},
                    {'v': 'right', 'l': 'pan right'},
                    {'v': 'up', 'l': 'tilt up'},
                    {'v': 'down', 'l': 'tilt down'},
                ],
                'hint': 'A zoompan move added in post. It is a genuine camera move '
                'in the frame and a genuine resolution loss — use it to '
                'rescue a clip, not to plan one. Ask the model instead.',
            },
            {
                'key': 'ken_burns_amount',
                'type': 'knob',
                'label': 'Post move amount',
                'def': 0.12,
                'min': 0.02,
                'max': 0.6,
                'step': 0.01,
                'icon': 'ic-kbamount',
                'hint': 'How far the post move travels over the clip, as a fraction of the frame.',
            },
            {
                'key': 'rotate',
                'type': 'knob',
                'label': 'Rotate',
                'def': 0.0,
                'min': -15.0,
                'max': 15.0,
                'step': 0.1,
                'unit': '°',
                'icon': 'ic-rotate',
                'hint': 'Rotates and auto-zooms enough to keep the corners filled. A '
                'post dutch tilt, or a horizon fix.',
            },
            {
                'key': 'flip_h',
                'type': 'toggle',
                'label': 'Flip horizontal',
                'def': False,
                'icon': 'ic-fliph',
                'hint': 'Mirrors the frame. Fixes a subject facing the wrong way for '
                'the cut — and mirrors any text in shot, which is usually '
                'how you find out there was text in shot.',
            },
            {
                'key': 'flip_v',
                'type': 'toggle',
                'label': 'Flip vertical',
                'def': False,
                'icon': 'ic-flipv',
                'hint': 'Mirrors top to bottom.',
            },
            {
                'key': 'lens_distort',
                'type': 'knob',
                'label': 'Lens distortion',
                'def': 0.0,
                'min': -0.4,
                'max': 0.4,
                'step': 0.01,
                'icon': 'ic-distort',
                'hint': 'lenscorrection. Negative barrels (wide-angle bulge), '
                'positive pincushions. Also the way to REMOVE the bulge a '
                'fisheye prompt put in.',
            },
            {
                'key': 'pad_color',
                'type': 'select',
                'label': 'Matte colour',
                'def': 'black',
                'icon': 'ic-padcolor',
                'options': [
                    {'v': 'black', 'l': 'black'},
                    {'v': 'white', 'l': 'white'},
                    {'v': 'gray', 'l': 'mid grey'},
                    {'v': '#0b0b0f', 'l': 'near-black'},
                ],
                'hint': 'The colour behind the Matte bars in FINISH and behind a '
                'rotate. Mid grey is what you want when checking a matte for '
                'alignment; black is what you ship.',
            },
        ],
    },
    {
        'id': 'post',
        'title': 'FINISH',
        'icon': 'ic-magic',
        'place': 'bar',
        'sub': 'The edit and the texture. Order is fixed: hold → trim → reverse → '
        'speed → deflicker → denoise → resample → geometry → grade → LUT → '
        'sharpen → grain → chroma → vignette → matte → interpolate → '
        'watermark → fade → bloom → loop.',
        'params': [
            {
                'key': 'hold_head',
                'type': 'knob',
                'label': 'Hold first frame',
                'def': 0.0,
                'min': 0.0,
                'max': 5.0,
                'step': 0.05,
                'unit': 's',
                'icon': 'ic-holdhead',
                'hint': 'tpad — freeze the opening frame for N seconds before the '
                'motion starts. A held beat before a move reads as intent.',
            },
            {
                'key': 'hold_tail',
                'type': 'knob',
                'label': 'Hold last frame',
                'def': 0.0,
                'min': 0.0,
                'max': 5.0,
                'step': 0.05,
                'unit': 's',
                'icon': 'ic-holdtail',
                'hint': 'Freeze the closing frame. Gives an edit somewhere to cut that is not mid-movement.',
            },
            {
                'key': 'trim_head',
                'type': 'knob',
                'label': 'Trim head',
                'def': 0.0,
                'min': 0.0,
                'max': 5.0,
                'step': 0.05,
                'unit': 's',
                'icon': 'ic-cuthead',
                'hint': "Drop the first N seconds. Wan's first few frames are where "
                'the start-frame hand-off artefact lives.',
            },
            {
                'key': 'trim_tail',
                'type': 'knob',
                'label': 'Trim tail',
                'def': 0.0,
                'min': 0.0,
                'max': 5.0,
                'step': 0.05,
                'unit': 's',
                'icon': 'ic-cuttail',
                'hint': 'Drop the last N seconds.',
            },
            {
                'key': 'reverse',
                'type': 'toggle',
                'label': 'Reverse',
                'def': False,
                'icon': 'ic-reverse',
                'hint': 'Play the clip backwards. Turns a "walks away" into a "walks toward" without a re-render.',
            },
            {
                'key': 'speed',
                'type': 'knob',
                'label': 'Speed',
                'def': 1.0,
                'min': 0.25,
                'max': 2.0,
                'step': 0.05,
                'unit': '×',
                'icon': 'ic-speedo',
                'hint': 'Time remap. Below 1 = slow motion — pair with interpolation '
                'or it judders. For anything faster than 2× use Fast '
                'forward, which multiplies this dial.',
            },
            {
                'key': 'speed_x',
                'type': 'select',
                'label': 'Fast forward',
                'def': 'off',
                'icon': 'ic-fastfwd',
                'options': [
                    {'v': 'off', 'l': 'off'},
                    {'v': '5', 'l': '5×'},
                    {'v': '10', 'l': '10×'},
                    {'v': '20', 'l': '20×'},
                    {'v': '30', 'l': '30×'},
                ],
                'hint': 'The big time-lapse multipliers, on top of the Speed dial — '
                'Speed 1.0 with 20× is 20×, Speed 1.5 with 20× is 30×. '
                'One setpts does both. Above 2× the finished file is '
                'conformed back to the render rate by dropping frames '
                '(unless Output fps or Interpolate already says otherwise), '
                'so it stays a normal-rate clip instead of a 480 fps one '
                'no player will scrub. A 5 s render at 30× is 0.17 s — '
                'these are for a long source, not a clip.',
            },
            {
                'key': 'stabilize',
                'type': 'toggle',
                'label': 'Stabilise',
                'def': False,
                'icon': 'ic-steady',
                'hint': 'Two-pass vidstab. Runs before everything else and crops in '
                'slightly. The right partner for a handheld prompt.',
            },
            {
                'key': 'denoise',
                'type': 'knob',
                'label': 'Denoise',
                'def': 0.0,
                'min': 0.0,
                'max': 1.0,
                'step': 0.05,
                'icon': 'ic-clean',
                'hint': 'hqdn3d. Temporal as well as spatial, so it also calms '
                'boiling texture — and softens real detail with it.',
            },
            {
                'key': 'resample',
                'type': 'select',
                'label': 'Resample',
                'def': 'off',
                'icon': 'ic-expand',
                'options': [
                    {'v': 'off', 'l': 'off'},
                    {'v': '1.5', 'l': '1.5x lanczos'},
                    {'v': '2', 'l': '2x lanczos'},
                    {'v': '3', 'l': '3x lanczos'},
                ],
                'hint': 'Lanczos, not AI. It makes the file bigger and adds no '
                'detail — labelled as what it is on purpose.',
            },
            {
                'key': 'sharpen',
                'type': 'knob',
                'label': 'Sharpen',
                'def': 0.0,
                'min': 0.0,
                'max': 2.0,
                'step': 0.05,
                'icon': 'ic-sharp',
                'hint': 'unsharp. Worth a little after a resample or a denoise, and nothing at all on a clean render.',
            },
            {
                'key': 'upscale',
                'type': 'select',
                'label': 'AI upscale',
                'def': 'off',
                'icon': 'ic-upscale',
                'options': [
                    {'v': 'off', 'l': 'off'},
                    {'v': 'x2', 'l': 'RealESRGAN x2'},
                    {'v': 'x4', 'l': 'RealESRGAN x4plus'},
                ],
                'hint': 'RealESRGAN x2/x4plus through ComfyUI in 33-frame batches, '
                'BEFORE the grade chain so every later op sees the final '
                'pixel size.',
            },
            {
                'key': 'grain',
                'type': 'knob',
                'label': 'Film grain',
                'def': 0.0,
                'min': 0.0,
                'max': 40.0,
                'step': 1.0,
                'icon': 'ic-grain',
                'hint': "Temporal noise. 6–12 is the range that hides Wan's plastic skin without reading as noise.",
            },
            {
                'key': 'vignette',
                'type': 'knob',
                'label': 'Vignette',
                'def': 0.0,
                'min': 0.0,
                'max': 1.0,
                'step': 0.05,
                'icon': 'ic-vignette',
                'hint': 'Lens falloff at the corners.',
            },
            {
                'key': 'letterbox',
                'type': 'select',
                'label': 'Matte',
                'def': 'off',
                'icon': 'ic-bars',
                'options': [
                    {'v': 'off', 'l': 'off'},
                    {'v': '2.39', 'l': '2.39:1 scope'},
                    {'v': '2.0', 'l': '2.0:1'},
                    {'v': '1.85', 'l': '1.85:1'},
                    {'v': '1.6', 'l': '1.6:1'},
                    {'v': '1.0', 'l': '1:1 square'},
                    {'v': '0.5625', 'l': '9:16 vertical'},
                ],
                'hint': 'Crops to the ratio and pads back to the original size, so the file dimensions never change.',
            },
            {
                'key': 'watermark',
                'type': 'text',
                'label': 'Burn-in text',
                'def': '',
                'icon': 'ic-watermark',
                'hint': 'drawtext, in DejaVu Sans. For a review copy or a slate. '
                'This is burned in permanently — there is no removing it '
                'from the rendered file afterwards.',
            },
            {
                'key': 'watermark_pos',
                'type': 'select',
                'label': 'Burn-in position',
                'def': 'br',
                'icon': 'ic-wmpos',
                'options': [
                    {'v': 'tl', 'l': 'top left'},
                    {'v': 'tr', 'l': 'top right'},
                    {'v': 'bl', 'l': 'bottom left'},
                    {'v': 'br', 'l': 'bottom right'},
                    {'v': 'c', 'l': 'centre'},
                ],
                'hint': 'Where the burn-in text sits.',
            },
            {
                'key': 'burn_timecode',
                'type': 'toggle',
                'label': 'Burn timecode',
                'def': False,
                'icon': 'ic-timecode',
                'hint': 'Frame number and seconds in the corner. For talking about a '
                'specific frame with somebody else — never for a delivery.',
            },
            {
                'key': 'fade_in',
                'type': 'knob',
                'label': 'Fade in',
                'def': 0.0,
                'min': 0.0,
                'max': 3.0,
                'step': 0.05,
                'unit': 's',
                'icon': 'ic-fadein',
                'hint': 'Fade up from the fade colour.',
            },
            {
                'key': 'fade_out',
                'type': 'knob',
                'label': 'Fade out',
                'def': 0.0,
                'min': 0.0,
                'max': 3.0,
                'step': 0.05,
                'unit': 's',
                'icon': 'ic-fadeout',
                'hint': 'Fade down at the end. Measured against the duration AFTER trim and speed, not the raw render.',
            },
            {
                'key': 'fade_color',
                'type': 'select',
                'label': 'Fade colour',
                'def': 'black',
                'icon': 'ic-fadecolor',
                'options': [{'v': 'black', 'l': 'black'}, {'v': 'white', 'l': 'white'}],
                'hint': 'What the fades go to and from.',
            },
            {
                'key': 'interpolate',
                'type': 'select',
                'label': 'Interpolate to',
                'def': 'off',
                'icon': 'ic-frames2',
                'options': [
                    {'v': 'off', 'l': 'off'},
                    {'v': '30', 'l': '30 fps'},
                    {'v': '48', 'l': '48 fps'},
                    {'v': '60', 'l': '60 fps'},
                ],
                'hint': 'The delivery frame rate. Interp mode picks who makes the '
                "new frames: ffmpeg's minterpolate, or RIFE. Slow, and "
                'minterpolate will smear fast hands. The partner to Speed '
                'below 1.',
            },
            {
                'key': 'interp_mode',
                'type': 'select',
                'label': 'Interp mode',
                'def': 'mci',
                'icon': 'ic-mci',
                'options': [
                    {'v': 'mci', 'l': 'motion compensated'},
                    {'v': 'blend', 'l': 'blend — safe, soft'},
                    {'v': 'dup', 'l': 'duplicate — no smoothing'},
                    {'v': 'rife', 'l': 'RIFE 2x (neural)'},
                ],
                'hint': 'blend is the one that never tears; mci is the one that '
                'actually looks like more frames. rife is the neural one: '
                'rife-ncnn-vulkan DOUBLES the frame rate in its own pass '
                'before the grade chain, then the result is conformed to '
                'the "Interpolate to" target by dropping frames evenly — '
                'so it needs that target set, and minterpolate is not run '
                'as well.',
            },
            {
                'key': 'loop_mode',
                'type': 'select',
                'label': 'Loop',
                'def': 'off',
                'icon': 'ic-repeat',
                'options': [
                    {'v': 'off', 'l': 'off'},
                    {'v': 'pingpong', 'l': 'ping-pong (forward + reverse)'},
                    {'v': 'crossfade', 'l': 'crossfade the seam'},
                ],
                'hint': 'An EDIT-level loop. For a loop the model itself renders '
                'closed, use End frame = same as start, or the looped window '
                'schedule in LONG CLIP.',
            },
            {
                'key': 'color_match',
                'type': 'toggle',
                'label': 'Match source colour',
                'def': False,
                'icon': 'ic-dropper',
                'hint': 'Measures frame 0 against the injected seed frame and emits '
                'a per-channel lutrgb. Refuses itself when either frame is '
                'nearly flat — a clip that opens on black would otherwise '
                'produce a gain that crushes the whole render.',
            },
        ],
    },
]
