# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Registry entries: SIDE / FRAME and SIDE / LIGHT."""

from __future__ import annotations

from zyg_workflows import creature_fx as cfx
from zyg_workflows.picture_fx.pixel_tone import (
    _px_auto,
    _px_bloom,
    _px_border,
    _px_clarity,
    _px_curve,
    _px_equalize,
    _px_faded,
    _px_highlights,
    _px_round,
    _px_shadows,
    b,
    c,
    e,
    f,
    i,
)
from zyg_workflows.picture_fx.pixel_frame import (
    _px_aspect,
    _px_extend,
    _px_letterbox,
    _px_longedge,
    _px_mirror_half,
    _px_straighten,
)

from zyg_workflows.picture_fx.registry import _ASPECTS, _pix

# ══ SIDE · FRAME ════════════════════════════════════════════════════════════
# Where the edges are. Every one of these is arithmetic, so the preview is the
# answer and there is nothing to render.

_pix(
    'fr_crop',
    'Crop',
    'Frame',
    'Crop — in percentages of the source, so the same crop survives a change of '
    'resolution. Deterministic: what the preview shows is what bakes.',
    '<path d="M6.5 2.5v13a2 2 0 002 2h13"/><path d="M2.5 6.5h13a2 2 0 012 2v13"/>',
    [
        f('x', 'X %', 0, 0, 99, 0.5),
        f('y', 'Y %', 0, 0, 99, 0.5),
        f('w', 'Width %', 100, 1, 100, 0.5),
        f('h', 'Height %', 100, 1, 100, 0.5),
    ],
    pfn=cfx._px_crop,
)

_pix(
    'fr_aspect',
    'Aspect crop',
    'Frame',
    'Crop to a named aspect, biased where you want the loss taken. A portrait '
    'centred by default loses the chin, which is why the bias slider is here and '
    'not a fixed centre.',
    '<rect x="3" y="6" width="18" height="12" rx="1.6"/>'
    '<rect x="7.6" y="3.4" width="8.8" height="17.2" rx="1.6" stroke-dasharray="2.4 2"/>',
    [e('v', 'Aspect', '1:1', _ASPECTS), f('bias', 'Bias %', 50, 0, 100, 1)],
    pfn=_px_aspect,
)

_pix(
    'fr_letterbox',
    'Fit to aspect',
    'Frame',
    'PAD to a named aspect instead of cropping to it — nothing leaves the frame. '
    'The right tool when the aspect is a delivery requirement and the composition '
    'is already final.',
    '<rect x="2.6" y="7" width="18.8" height="10" rx="1.4"/>'
    '<path d="M2.6 4h18.8M2.6 20h18.8" stroke-dasharray="2.4 2"/>',
    [e('v', 'Aspect', '16:9', _ASPECTS), c('col', 'Bars', '#000000'), f('a', 'Opacity %', 100, 0, 100, 1)],
    pfn=_px_letterbox,
)

_pix(
    'fr_resize',
    'Resize',
    'Frame',
    'Resize by percentage, with the filter named. Nearest keeps pixel art crisp; '
    'lanczos is right for a render. Going UP from a small source invents nothing — '
    'it only makes the same detail bigger.',
    '<rect x="3.4" y="12.6" width="8" height="8" rx="1.2"/><path d="M14 10L20.6 3.4"/>'
    '<path d="M20.6 3.4h-5M20.6 3.4v5"/>',
    [
        f('s', 'Size %', 100, 5, 400, 1),
        f('sy', 'Height %', 100, 5, 400, 1),
        b('lock', 'Lock aspect', True),
        e('flt', 'Filter', 'lanczos', ['lanczos', 'bicubic', 'bilinear', 'nearest']),
    ],
    pfn=cfx._px_scale,
)

_pix(
    'fr_longedge',
    'Long edge',
    'Frame',
    'Resize by the LONG EDGE, in pixels. The only resize that means the same thing '
    'for a portrait and a landscape — and what every downstream size limit is '
    'actually written in.',
    '<path d="M3.4 20.6L20.6 3.4"/><path d="M3.4 15.6v5h5"/><path d="M20.6 8.4v-5h-5"/>',
    [
        i('n', 'Long edge px', 1024, 128, 4096, 32),
        e('flt', 'Filter', 'lanczos', ['lanczos', 'bicubic', 'bilinear', 'nearest']),
    ],
    pfn=_px_longedge,
)

_pix(
    'fr_rot',
    'Rotate',
    'Frame',
    'Rotate about the centre, filling with transparency rather than black. '
    '"Expand" grows the canvas so the corners are not clipped.',
    '<path d="M20.2 12a8.2 8.2 0 11-2.7-6.1"/><path d="M20.4 3.6v4.6h-4.6"/>',
    [f('a', 'Degrees', 0, -180, 180, 0.5), b('expand', 'Expand canvas', True)],
    pfn=cfx._px_rot,
)

_pix(
    'fr_straighten',
    'Straighten',
    'Frame',
    'A small rotation that KEEPS the canvas rectangular: rotate without expanding, '
    'then crop in far enough that no transparent wedge survives. The wedge is the '
    'whole reason a plain rotate is the wrong tool for a horizon two degrees off.',
    '<path d="M3 17.4L21 9"/><path d="M3 20.6h18"/><path d="M5.4 12.6l2 2"/>',
    [f('a', 'Degrees', 0, -12, 12, 0.1), b('refit', 'Refit to original size', True)],
    pfn=_px_straighten,
)

_pix(
    'fr_fliph',
    'Flip H',
    'Frame',
    'Flip horizontally. Free extra coverage on a symmetric subject — and a lie on '
    'anything with a parting, a scar or lettering, which is exactly what the '
    'Mirror check is for.',
    '<path d="M12 2.6v18.8" stroke-dasharray="2.6 2.4"/><path d="M9.2 6.6L3.6 12l5.6 5.4z"/>'
    '<path d="M14.8 6.6L20.4 12l-5.6 5.4z"/>',
    pfn=cfx._px_flip('h'),
)

_pix(
    'fr_flipv',
    'Flip V',
    'Frame',
    'Flip vertically.',
    '<path d="M2.6 12h18.8" stroke-dasharray="2.6 2.4"/><path d="M6.6 9.2L12 3.6l5.4 5.6z"/>'
    '<path d="M6.6 14.8L12 20.4l5.4-5.6z"/>',
    pfn=cfx._px_flip('v'),
)

_pix(
    'fr_mirror',
    'Mirror half',
    'Frame',
    'Mirror one half of the picture onto the other. A symmetry CHECK, not a beauty '
    'filter: a face that only looks right one way round is a face the model built '
    'out of two different references.',
    '<path d="M12 2.6v18.8"/><path d="M4 7.4h5v9.2H4z"/><path d="M15 7.4h5v9.2h-5z"/>',
    [e('v', 'Keep', 'left', ['left', 'right'])],
    pfn=_px_mirror_half,
)

_pix(
    'fr_pad',
    'Pad',
    'Frame',
    'Add margin around the picture, transparent by default. The counterpart to Crop '
    'when a cell clipped a tail tip or the top of a head.',
    '<rect x="2.6" y="2.6" width="18.8" height="18.8" rx="2" stroke-dasharray="2.4 2.4"/>'
    '<rect x="7" y="7" width="10" height="10" rx="1.2"/>',
    [f('m', 'Margin %', 10, 0, 100, 0.5), c('col', 'Colour', '#000000'), f('a', 'Opacity %', 0, 0, 100, 1)],
    pfn=cfx._px_pad,
)

_pix(
    'fr_extend',
    'Extend edges',
    'Frame',
    'Grow the canvas by MIRRORING the edges outward. It invents no detail — it '
    'reflects what is already there — which makes it the right plate to hand an '
    'outpaint, and an honest fix on its own for a background that was cropped tight.',
    '<rect x="8" y="8" width="8" height="8" rx="1"/>'
    '<path d="M8 4.4h8M8 19.6h8M4.4 8v8M19.6 8v8" stroke-dasharray="2 2"/>',
    [f('m', 'Margin %', 12, 0, 45, 0.5)],
    pfn=_px_extend,
)

_pix(
    'fr_square',
    'Square up',
    'Frame',
    "Pad to a square canvas — what a trainer's aspect buckets want, and what stops "
    'a tall subject being letterboxed by the bucketer instead.',
    '<rect x="4.4" y="4.4" width="15.2" height="15.2" rx="1.6"/>'
    '<path d="M4.4 12h15.2M12 4.4v15.2" stroke-dasharray="2 2.4"/>',
    [c('col', 'Ground', '#808080'), f('a', 'Opacity %', 0, 0, 100, 1)],
    pfn=cfx._px_square,
)

_pix(
    'fr_trim',
    'Trim bars',
    'Frame',
    'Trim flat letterbox bars off the edges. A Qwen edit adds them whenever it '
    'decides the composition wants them, and every later crop then treats them as '
    'part of the picture.',
    '<rect x="3.6" y="7.4" width="16.8" height="9.2" rx="1.2"/>'
    '<path d="M3.6 4.4h16.8M3.6 19.6h16.8" stroke-dasharray="2.4 2.4"/>',
    [i('tol', 'Tolerance', 10, 1, 60, 1)],
    pfn=cfx._px_trim,
)

_pix(
    'fr_border',
    'Border',
    'Frame',
    'A solid border, sized as a percentage of the short edge so it reads the same on a cell and on a 4K plate.',
    '<rect x="2.6" y="2.6" width="18.8" height="18.8" rx="1.6"/>'
    '<rect x="6.4" y="6.4" width="11.2" height="11.2" rx="1"/>',
    [f('n', 'Width %', 3, 0, 25, 0.25), c('col', 'Colour', '#ffffff')],
    pfn=_px_border,
)

_pix(
    'fr_round',
    'Round corners',
    'Frame',
    'Round the corners into the ALPHA, not by painting a colour over them — a '
    'painted corner is wrong the moment the picture lands on anything but the '
    'colour it was painted with.',
    '<path d="M3.4 9.4a6 6 0 016-6h5.2a6 6 0 016 6v5.2a6 6 0 01-6 6H9.4a6 6 0 01-6-6z"/>',
    [f('r', 'Radius %', 8, 0, 50, 0.5)],
    pfn=_px_round,
)


# ══ SIDE · LIGHT ════════════════════════════════════════════════════════════
# Tone. All of it lands on RGB and puts the alpha back untouched, because a
# grade that reaches the alpha silently fogs a cut-out's matte.

_pix(
    'lt_exposure',
    'Exposure',
    'Light',
    'Exposure — a straight multiply on the RGB, alpha untouched.',
    '<circle cx="12" cy="12" r="4"/><path d="M12 2.6v3M12 18.4v3M2.6 12h3M18.4 12h3'
    'M5.4 5.4l2.2 2.2M16.4 16.4l2.2 2.2M18.6 5.4l-2.2 2.2M7.6 16.4l-2.2 2.2"/>',
    [f('v', 'Exposure', 0, -90, 200, 1)],
    pfn=cfx._px_enh('bright'),
)

_pix(
    'lt_contrast',
    'Contrast',
    'Light',
    'Contrast — about mid grey.',
    '<circle cx="12" cy="12" r="8.4"/><path d="M12 3.6a8.4 8.4 0 010 16.8z" fill="currentColor" stroke="none"/>',
    [f('v', 'Contrast', 0, -90, 200, 1)],
    pfn=cfx._px_enh('contrast'),
)

_pix(
    'lt_curve',
    'S-curve',
    'Light',
    'The film response a straight contrast multiply does not have: it steepens the '
    'midtones and eases both ends instead of clipping them. This is what a linear '
    'render is missing when it reads plastic.',
    '<path d="M3.4 20.6C8 20.6 8 12 12 12s4-8.6 8.6-8.6"/><path d="M3.4 20.6h17.2"/>',
    [f('v', 'Amount', 30, -100, 100, 1)],
    pfn=_px_curve,
)

_pix(
    'lt_shadows',
    'Shadows',
    'Light',
    'Open or crush the shadow half only, on a cosine weight so the midtones do not band where the lift stops.',
    '<path d="M12 3.4a8.6 8.6 0 100 17.2"/><path d="M12 3.4a8.6 8.6 0 010 17.2z" fill="currentColor" stroke="none"/>',
    [f('v', 'Amount', 0, -100, 100, 1)],
    pfn=_px_shadows,
)

_pix(
    'lt_highlights',
    'Highlights',
    'Light',
    'Recover or push the highlight half only. Pulling highlights down is what gets '
    'detail back into a blown cheek without flattening the whole frame.',
    '<circle cx="12" cy="12" r="4.4"/><path d="M12 2.4v2.6M12 19v2.6M2.4 12H5M19 12h2.6"/>',
    [f('v', 'Amount', 0, -100, 100, 1)],
    pfn=_px_highlights,
)

_pix(
    'lt_gamma',
    'Gamma',
    'Light',
    'Gamma — midtones without moving black or white. The right knob when a render '
    'is correctly exposed but reads muddy.',
    '<path d="M3.6 19.4c6-1 9-6 10-14"/><path d="M3.6 19.4h16.8"/>',
    [f('g', 'Gamma', 1.0, 0.2, 3.0, 0.01)],
    pfn=cfx._px_gamma,
)

_pix(
    'lt_levels',
    'Levels',
    'Light',
    'Black point and white point. Setting the black point on a render that never '
    'reaches zero is what makes it stop looking flat.',
    '<path d="M3.6 19.4V8.4M8 19.4V4.6M12.4 19.4v-9M16.8 19.4V6.4M21 19.4v-4"/>',
    [f('lo', 'Black point', 0, 0, 200, 1), f('hi', 'White point', 255, 55, 255, 1)],
    pfn=cfx._px_levels,
)

_pix(
    'lt_auto',
    'Auto contrast',
    'Light',
    'Stretch the histogram to the full range, ignoring the given percentage at each '
    'end. Fast and usually right — and wrong in exactly one case, a picture whose '
    'flat background IS the black or white point.',
    '<path d="M4 19.4V12M8.4 19.4V7.4M12.8 19.4V4.6M17.2 19.4V9.4M21 19.4v-4"/><path d="M3 21.4h18"/>',
    [f('cut', 'Ignore %', 1, 0, 12, 0.25)],
    pfn=_px_auto,
)

_pix(
    'lt_equalize',
    'Equalize',
    'Light',
    'Flatten the histogram outright. A blunt instrument and rarely a finish — but '
    'the fastest way to see whether there is anything at all in a crushed shadow.',
    '<rect x="3.4" y="9" width="3.4" height="10.4"/><rect x="8.6" y="5.4" width="3.4" height="14"/>'
    '<rect x="13.8" y="11.4" width="3.4" height="8"/><rect x="19" y="7" width="1.8" height="12.4"/>',
    [f('a', 'Amount', 100, 0, 100, 1)],
    pfn=_px_equalize,
)

_pix(
    'lt_faded',
    'Lift blacks',
    'Light',
    'A faded print never reaches zero, and the absence of that lift is one of the tells that reads as digital.',
    '<path d="M3.4 20.4h17.2"/><path d="M3.4 15.4c5.4 0 6-9 8.6-9s3.2 6 8.6 6"/>',
    [f('v', 'Lift', 18, 0, 100, 1)],
    pfn=_px_faded,
)

_pix(
    'lt_clarity',
    'Clarity',
    'Light',
    'Local contrast — a wide, low-amount unsharp mask. Not sharpening: it works on '
    'the shapes rather than the edges, and it is what makes a render read as having '
    'been photographed.',
    '<circle cx="12" cy="12" r="8.4"/><path d="M12 3.6v16.8"/><path d="M7 12h10"/>',
    [f('r', 'Radius', 24, 4, 90, 1), i('v', 'Amount %', 45, 0, 200, 5)],
    pfn=_px_clarity,
)

_pix(
    'lt_bloom',
    'Bloom',
    'Light',
    'Screen a blurred bright-pass back over the picture. Light spilling off a '
    'highlight is a lens behaviour a clean render has none of.',
    '<circle cx="12" cy="12" r="3.4"/><circle cx="12" cy="12" r="7.6" stroke-dasharray="1.4 2.6"/>'
    '<path d="M12 1.6v2M12 20.4v2M1.6 12h2M20.4 12h2"/>',
    [i('thr', 'Threshold', 190, 60, 254, 1), f('r', 'Radius', 14, 1, 60, 0.5), f('a', 'Amount', 45, 0, 100, 1)],
    pfn=_px_bloom,
)
