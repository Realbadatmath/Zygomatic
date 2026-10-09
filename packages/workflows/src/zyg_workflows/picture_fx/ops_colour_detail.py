# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Registry entries: SIDE / COLOUR and SIDE / DETAIL."""

from __future__ import annotations

from zyg_workflows.picture_fx.pixel_tone import (
    _filt,
    _px_balance,
    _px_chanswap,
    _px_chroma,
    _px_dither,
    _px_duotone,
    _px_invert,
    _px_motion,
    _px_pixelate,
    _px_sepia,
    _px_solarize,
    _px_splittone,
    _px_threshold,
    _px_tiltshift,
    _px_vibrance,
    b,
    c,
    e,
    f,
    i,
)

from zyg_workflows import creature_fx as cfx

from zyg_workflows.picture_fx.registry import _pix

# ══ SIDE · COLOUR ═══════════════════════════════════════════════════════════

_pix(
    'cl_sat',
    'Saturation',
    'Colour',
    'Saturation — exact and instant, unlike the generative colour ops, which ask the '
    'model to paint differently. Both are useful; they are not the same thing.',
    '<circle cx="9.6" cy="12" r="5.2"/><circle cx="14.4" cy="12" r="5.2"/><path d="M12 6.8v10.4"/>',
    [f('v', 'Saturation', 0, -100, 200, 1)],
    pfn=cfx._px_enh('colour'),
)

_pix(
    'cl_vibrance',
    'Vibrance',
    'Colour',
    'Saturation weighted toward the DULL pixels. A flat saturation slider pushes an '
    'already-vivid mouth into clipping long before it does anything for a muted '
    'background; this curves the S channel so the gain falls away as saturation rises.',
    '<path d="M4 16.6c3.4-8 5.4-11.2 8-11.2s4.6 3.2 8 11.2"/><path d="M4 19.6h16"/>',
    [f('v', 'Vibrance', 30, -100, 100, 1)],
    pfn=_px_vibrance,
)

_pix(
    'cl_hue',
    'Hue',
    'Colour',
    'Hue rotation, in degrees, through HSV. Exact, reversible, and it does not touch alpha.',
    '<circle cx="12" cy="12" r="8.4"/><path d="M12 3.6v8.4l6 4.2"/>',
    [f('a', 'Degrees', 0, -180, 180, 1)],
    pfn=cfx._px_hue,
)

_pix(
    'cl_temp',
    'Temperature',
    'Colour',
    'Warm or cool, as a channel LUT rather than a colour overlay. An overlay would '
    'land on the alpha and fog a cut-out matte.',
    '<path d="M10 13.4V5.4a2 2 0 014 0v8"/><circle cx="12" cy="16.4" r="3.4"/><path d="M17.4 7.4h3M17.4 11h3"/>',
    [f('v', 'Cool ← → warm', 0, -100, 100, 1)],
    pfn=cfx._px_temp,
)

_pix(
    'cl_tint',
    'Tint',
    'Colour',
    "Multiply the picture toward a colour. Useful for matching a subject into a scene's light without re-rendering it.",
    '<path d="M12 3.6c3.4 4.6 5.6 7.8 5.6 10.4a5.6 5.6 0 11-11.2 0c0-2.6 2.2-5.8 5.6-10.4z"/>',
    [c('col', 'Colour', '#ffcc88'), f('a', 'Amount', 40, 0, 100, 1)],
    pfn=cfx._px_tint,
)

_pix(
    'cl_balance',
    'Colour balance',
    'Colour',
    'Per-channel gain — a white balance you set by eye rather than along a single '
    'warm/cool axis. The tool for a green cast a temperature slider cannot reach.',
    '<circle cx="8.6" cy="9.4" r="4.6"/><circle cx="15.4" cy="9.4" r="4.6"/><circle cx="12" cy="15.4" r="4.6"/>',
    [f('r', 'Red', 0, -60, 60, 1), f('g', 'Green', 0, -60, 60, 1), f('b', 'Blue', 0, -60, 60, 1)],
    pfn=_px_balance,
)

_pix(
    'cl_chanswap',
    'Channel swap',
    'Colour',
    'Reorder the RGB channels. A stylisation, and also the fastest possible check '
    'for a channel that has been written wrong upstream — a BGR-as-RGB image '
    'straightens out under exactly one of these ([[project_pose_track_s08]]).',
    '<path d="M4 8h10M14 4.6L17.6 8 14 11.4"/><path d="M20 16H10M10 12.6L6.4 16 10 19.4"/>',
    [e('v', 'Order', 'rgb', ['rgb', 'rbg', 'grb', 'gbr', 'brg', 'bgr'])],
    pfn=_px_chanswap,
)

_pix(
    'cl_mono',
    'Monochrome',
    'Colour',
    'Monochrome, with an optional tone. A picture judged in greyscale is a picture '
    'judged on value alone, which is where a weak silhouette shows up.',
    '<circle cx="12" cy="12" r="8.4"/><path d="M12 3.6v16.8"/>'
    '<path d="M12 3.6a8.4 8.4 0 000 16.8z" fill="currentColor" stroke="none"/>',
    [f('a', 'Amount', 100, 0, 100, 1), b('tint', 'Tone it', False), c('col', 'Tone', '#e8d8b0')],
    pfn=cfx._px_mono,
)

_pix(
    'cl_sepia',
    'Sepia',
    'Colour',
    'The warm print tone, as a colorize between a brown black and a cream white '
    'rather than a flat overlay — an overlay muddies the highlights.',
    '<rect x="3.6" y="4.6" width="16.8" height="14.8" rx="2"/>'
    '<circle cx="9" cy="10" r="2.2"/><path d="M4.4 18l5-5.4 3.4 3 3-2.6 4.6 5"/>',
    [f('a', 'Amount', 85, 0, 100, 1)],
    pfn=_px_sepia,
)

_pix(
    'cl_duotone',
    'Duotone',
    'Colour',
    'Two colours mapped across the value range. A real stylisation, and a legible '
    'one — every tone in the picture becomes a position between the two you pick.',
    '<circle cx="9.4" cy="12" r="6"/><circle cx="14.6" cy="12" r="6"/>',
    [c('dark', 'Shadows', '#12203a'), c('light', 'Highlights', '#f2d9a0'), f('a', 'Amount', 100, 0, 100, 1)],
    pfn=_px_duotone,
)

_pix(
    'cl_split',
    'Split tone',
    'Colour',
    'One colour into the shadows and a different one into the highlights, weighted '
    'by luminance. What a grade does that a single tint cannot.',
    '<path d="M12 3.4v17.2"/><path d="M4 8.4c3.4 0 4.6 7.2 8 7.2s4.6-7.2 8-7.2"/>',
    [c('dark', 'Shadows', '#2a4f6e'), c('light', 'Highlights', '#f0c48a'), f('a', 'Amount', 45, 0, 100, 1)],
    pfn=_px_splittone,
)

_pix(
    'cl_invert',
    'Invert',
    'Colour',
    'Invert the RGB. A stylisation, and the classic way to see banding and edge '
    'artefacts that the eye skates over in the positive.',
    '<circle cx="12" cy="12" r="8.4"/>'
    '<path d="M12 3.6a8.4 8.4 0 010 16.8z" fill="currentColor" stroke="none"/>'
    '<path d="M7 12h10"/>',
    pfn=_px_invert,
)

_pix(
    'cl_post',
    'Posterize',
    'Colour',
    'Bits per channel. A fast way to see the value structure, and a real stylisation at 2–3 bits.',
    '<path d="M3.6 19.4h4V14h4V9.4h4V5h4.8"/>',
    [i('bits', 'Bits', 4, 1, 8, 1)],
    pfn=cfx._px_post,
)

_pix(
    'cl_solarize',
    'Solarize',
    'Colour',
    'Invert everything above a threshold — the darkroom accident, made a knob.',
    '<circle cx="12" cy="12" r="5"/><path d="M12 2v3M12 19v3M2 12h3M19 12h3"/>'
    '<path d="M7 12a5 5 0 015-5" stroke-dasharray="1.8 2"/>',
    [i('thr', 'Threshold', 128, 0, 255, 1)],
    pfn=_px_solarize,
)

_pix(
    'cl_threshold',
    'Threshold',
    'Colour',
    'Hard two-tone at a cut point. Not a look so much as a measurement you can see: '
    'it shows exactly where the value structure sits.',
    '<rect x="3.6" y="4.6" width="16.8" height="14.8" rx="1.6"/>'
    '<path d="M3.6 12h16.8"/><path d="M3.6 4.6h16.8v7.4H3.6z" fill="currentColor" stroke="none"/>',
    [i('thr', 'Threshold', 128, 1, 254, 1)],
    pfn=_px_threshold,
)

_pix(
    'cl_dither',
    'Dither',
    'Colour',
    'Quantise with error diffusion, to a palette or to pure black and white. The '
    'only honest way down to a small palette — a straight quantise bands, this '
    'trades the banding for noise.',
    '<circle cx="6.6" cy="7" r="1"/><circle cx="11" cy="9.4" r="1"/><circle cx="15.4" cy="7" r="1"/>'
    '<circle cx="8.6" cy="13" r="1"/><circle cx="13.4" cy="15.4" r="1"/><circle cx="17.4" cy="12.6" r="1"/>'
    '<rect x="3.4" y="3.4" width="17.2" height="17.2" rx="1.6"/>',
    [e('mode', 'Mode', 'palette', ['palette', 'mono']), i('n', 'Colours', 16, 2, 256, 1)],
    pfn=_px_dither,
)


# ══ SIDE · DETAIL ═══════════════════════════════════════════════════════════

_pix(
    'dt_sharpen',
    'Sharpen',
    'Detail',
    'Unsharp mask — radius, amount and threshold, the three knobs that decide '
    'whether it sharpens the subject or the noise around it.',
    '<path d="M12 3.6l3 6.4 6.4 1-4.6 4.6 1 6.4-5.8-3-5.8 3 1-6.4-4.6-4.6 6.4-1z"/>',
    [f('r', 'Radius', 2, 0.1, 12, 0.1), i('amt', 'Amount %', 120, 0, 400, 5), i('thr', 'Threshold', 3, 0, 40, 1)],
    pfn=cfx._px_usm,
)

_pix(
    'dt_blur',
    'Blur',
    'Detail',
    'Gaussian blur, in pixels at the source resolution — so it means the same thing '
    'on a 512 cell and a 2048 render, which a percentage would not.',
    '<circle cx="12" cy="12" r="7.6" stroke-dasharray="1.6 2.6"/><circle cx="12" cy="12" r="3.4"/>',
    [f('r', 'Radius', 2, 0, 40, 0.1)],
    pfn=cfx._px_blur,
)

_pix(
    'dt_motion',
    'Motion blur',
    'Detail',
    'Directional blur through an explicit line kernel. Four named directions rather '
    'than a free angle, because at this kernel size a free angle quantises to them '
    'anyway and pretending otherwise is a knob that lies.',
    '<path d="M3.4 8.6h13M3.4 12h17.2M3.4 15.4h9"/>',
    [
        e('dir', 'Direction', 'horizontal', ['horizontal', 'vertical', 'diagonal', 'anti-diagonal']),
        i('n', 'Passes', 1, 1, 6, 1),
    ],
    pfn=_px_motion,
)

_pix(
    'dt_tilt',
    'Tilt shift',
    'Detail',
    'Blur everything outside a horizontal band. It is a MASK, not a real defocus — '
    'the falloff follows the frame, not the depth of the scene — and on a subject '
    'that leans out of the band it will blur the near shoulder and not the far one.',
    '<rect x="3" y="4" width="18" height="16" rx="1.6"/><path d="M3 10.4h18M3 13.6h18" stroke-dasharray="2 2"/>',
    [
        f('r', 'Blur', 8, 0, 40, 0.5),
        f('y', 'Band centre %', 50, 0, 100, 1),
        f('band', 'Band height %', 30, 2, 90, 1),
        f('feather', 'Feather %', 18, 1, 60, 1),
    ],
    pfn=_px_tiltshift,
)

_pix(
    'dt_denoise',
    'Denoise',
    'Detail',
    'Median denoise. Cheap, exact and it eats fine hair — which is why the radius is '
    'small and capped rather than a free slider.',
    '<circle cx="12" cy="12" r="8.4"/><path d="M7.4 13.4c1.6-2.4 3-3.4 4.6-3.4s3 1 4.6 3.4"/>',
    [i('n', 'Radius', 3, 3, 9, 2)],
    pfn=cfx._px_median,
)

_pix(
    'dt_smooth',
    'Smooth',
    'Detail',
    'A gentle low-pass. Softer than a blur and cheaper than a denoise — the right '
    'first move on a render with dithering artefacts in a flat area.',
    '<path d="M3.4 15c3-6 5.6-6 8.6-6s5.6 0 8.6 6"/><path d="M3.4 19.4h17.2" stroke-dasharray="2 2"/>',
    [f('a', 'Amount', 100, 0, 100, 1)],
    pfn=_filt('smooth'),
)

_pix(
    'dt_detail',
    'Detail boost',
    'Detail',
    'A fixed high-frequency lift. Blunter than the unsharp mask and unaffected by '
    'radius, which makes it the right check when you cannot tell whether the '
    'softness is in the picture or in your sharpening.',
    '<path d="M4 18l4-8 4 5 3-3.4 5 6.4"/><rect x="3" y="3.4" width="18" height="17.2" rx="1.6"/>',
    [f('a', 'Amount', 100, 0, 100, 1)],
    pfn=_filt('detail'),
)

_pix(
    'dt_edge',
    'Edge enhance',
    'Detail',
    'Push the edges only. It reads as sharpening at a glance, and it is not — it '
    'ignores the surfaces entirely, which is a stylisation on skin.',
    '<path d="M4.6 19.4L12 4.6l7.4 14.8z"/>',
    [f('a', 'Amount', 100, 0, 100, 1)],
    pfn=_filt('edge'),
)

_pix(
    'dt_emboss',
    'Emboss',
    'Detail',
    'The relief filter. Not a lighting model: it reports gradients as height, which '
    'is why a prominence and a pit come back looking the same '
    '([[project_relief_primitive_rejected]]).',
    '<circle cx="12" cy="12" r="8.4"/><path d="M8.6 15.4l6.8-6.8"/><path d="M9.4 9.4h.01"/>',
    [f('a', 'Amount', 100, 0, 100, 1)],
    pfn=_filt('emboss'),
)

_pix(
    'dt_find',
    'Find edges',
    'Detail',
    'The edge map on its own. A stylisation, and the fastest way to see where a compositing seam actually sits.',
    '<path d="M3.4 20.6l6-10 4 5 3-4.6 4.2 9.6z" stroke-dasharray="2.4 1.8"/>',
    [f('a', 'Amount', 100, 0, 100, 1)],
    pfn=_filt('find'),
)

_pix(
    'dt_contour',
    'Contour',
    'Detail',
    'Trace the picture as line work on white.',
    '<path d="M5 19c0-6 3-11 7-11s7 5 7 11"/><path d="M8.4 19c0-4 1.6-7 3.6-7s3.6 3 3.6 7"/>',
    [f('a', 'Amount', 100, 0, 100, 1)],
    pfn=_filt('contour'),
)

_pix(
    'dt_pixelate',
    'Pixelate',
    'Detail',
    'Down and back up with nearest. A stylisation, and the honest way to anonymise '
    'a face in a frame you still want to show — a blur of the same strength can be '
    'partially reversed, this cannot.',
    '<rect x="3.4" y="3.4" width="7" height="7"/><rect x="13.6" y="3.4" width="7" height="7"/>'
    '<rect x="3.4" y="13.6" width="7" height="7"/><rect x="13.6" y="13.6" width="7" height="7"/>',
    [i('n', 'Block px', 12, 2, 80, 1)],
    pfn=_px_pixelate,
)

_pix(
    'dt_chroma',
    'Chromatic aberration',
    'Detail',
    'Push the red and blue channels apart by a pixel or two. A render has none at '
    'all, and that absence is one of the tells that reads as CGI.',
    '<circle cx="10.4" cy="12" r="6.4"/><circle cx="13.6" cy="12" r="6.4"/>',
    [i('n', 'Offset px', 2, 0, 12, 1)],
    pfn=_px_chroma,
)
