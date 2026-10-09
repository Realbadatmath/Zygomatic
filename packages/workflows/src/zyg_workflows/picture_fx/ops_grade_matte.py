# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Registry entries: SIDE / GRADE, SIDE / MATTE and SIDE / ENHANCE."""

from __future__ import annotations

from zyg_workflows import creature_fx as cfx
from zyg_workflows.picture_fx.pixel_tone import (
    _px_bleach,
    _px_cartoon,
    _px_cross,
    _px_halation,
    _px_scanlines,
    _px_sketch,
    c,
    e,
    f,
    i,
)
from zyg_workflows.picture_fx.pixel_frame import (
    _px_alpha_choke,
    _px_alpha_feather,
    _px_alpha_invert,
    _px_dropshadow,
    _px_glow,
    _px_ground_grad,
    _px_outline,
)

from zyg_workflows.picture_fx.registry import _act, _pix, _svc

# ══ SIDE · GRADE ════════════════════════════════════════════════════════════
# Film-print behaviours. None of these is corrective: each one is a specific
# artefact of a specific process, added back on purpose.

_pix(
    'gr_grain',
    'Grain',
    'Grade',
    'Film grain — SEEDED, so the preview and the bake carry the same grain. An '
    'unseeded grain would make every re-render a different file for no reason.',
    '<rect x="3.6" y="5.4" width="16.8" height="13.2" rx="1.6"/>'
    '<circle cx="8" cy="10" r=".9"/><circle cx="13" cy="9" r=".9"/><circle cx="16.4" cy="13" r=".9"/>'
    '<circle cx="9.4" cy="14.4" r=".9"/><circle cx="13.6" cy="15.4" r=".9"/>',
    [f('a', 'Amount', 12, 0, 60, 1), i('seed', 'Seed', 7, 0, 99999, 1)],
    pfn=cfx._px_grain,
)

_pix(
    'gr_vignette',
    'Vignette',
    'Grade',
    'Darken toward the corners, multiplied into RGB only. Drawn into the alpha it '
    'would silently eat the edge of a cut-out.',
    '<rect x="3.4" y="4.6" width="17.2" height="14.8" rx="2"/><ellipse cx="12" cy="12" rx="6.4" ry="5"/>',
    [f('a', 'Amount', 45, 0, 100, 1), f('f', 'Feather', 60, 5, 100, 1)],
    pfn=cfx._px_vig,
)

_pix(
    'gr_halation',
    'Halation',
    'Grade',
    'The red bleed film gets around a blown highlight, as a bloom biased into the '
    'red channel rather than a neutral one. It is the difference between "bright" '
    'and "photographed bright".',
    '<circle cx="12" cy="12" r="3.6"/><circle cx="12" cy="12" r="7" stroke-dasharray="1.2 2.4"/>'
    '<circle cx="12" cy="12" r="9.6" stroke-dasharray="1 3"/>',
    [i('thr', 'Threshold', 200, 60, 254, 1), f('r', 'Radius', 18, 1, 70, 0.5), f('a', 'Amount', 40, 0, 100, 1)],
    pfn=_px_halation,
)

_pix(
    'gr_bleach',
    'Bleach bypass',
    'Grade',
    'The luminance overlaid back on a desaturated base — the silver-retention look. '
    'High contrast, low colour, and it stays legible in a way a raw contrast push '
    'does not.',
    '<path d="M12 3.4l6.4 6.4a9 9 0 11-12.8 0z"/>',
    [f('a', 'Amount', 65, 0, 100, 1)],
    pfn=_px_bleach,
)

_pix(
    'gr_cross',
    'Cross process',
    'Grade',
    'The three channels curved against each other, which is the whole of what the '
    'look is: cyan shadows, yellow highlights, and a contrast that comes from the '
    'divergence rather than from a contrast knob.',
    '<path d="M4.6 19.4C4.6 11 8 4.6 12 4.6"/><path d="M12 19.4c4 0 7.4-6.4 7.4-14.8"/>'
    '<path d="M3.4 12h17.2" stroke-dasharray="2 2"/>',
    [f('a', 'Amount', 60, 0, 100, 1)],
    pfn=_px_cross,
)

_pix(
    'gr_scanlines',
    'Scan lines',
    'Grade',
    'Darken every nth row. A CRT artefact, and a legitimate way to age a frame that '
    'is meant to read as archive footage.',
    '<rect x="3" y="4.6" width="18" height="14.8" rx="1.6"/><path d="M3 8h18M3 11h18M3 14h18M3 17h18"/>',
    [i('n', 'Every nth row', 3, 2, 12, 1), f('a', 'Darkness', 35, 0, 100, 1)],
    pfn=_px_scanlines,
)

_pix(
    'gr_sketch',
    'Pencil sketch',
    'Grade',
    'Colour-dodge of the blurred inverse — the pencil construction, exact and '
    'instant. Worth knowing before you spend four minutes asking a diffusion model '
    'for the same thing.',
    '<path d="M14.5 3.5a2.1 2.1 0 013 3L8 16l-4.5 1.5L5 13z"/><path d="M12 6l3 3"/>',
    [f('r', 'Softness', 8, 1, 40, 0.5), f('a', 'Amount', 100, 0, 100, 1)],
    pfn=_px_sketch,
)

_pix(
    'gr_cartoon',
    'Cel shade',
    'Grade',
    'Posterised colour multiplied by its own edge map. A deterministic cel look — '
    'not a style transfer, and it will not restructure anything, which is both its '
    'limit and the reason it never changes the subject.',
    '<path d="M4 12a8 8 0 1116 0v6.4a2 2 0 01-2 2H6a2 2 0 01-2-2z"/><path d="M8.6 11.4h.01M15.4 11.4h.01"/>',
    [i('bits', 'Colour bits', 3, 1, 8, 1), i('edge', 'Edge strength', 40, 0, 200, 5), f('a', 'Amount', 100, 0, 100, 1)],
    pfn=_px_cartoon,
)


# ══ SIDE · MATTE ════════════════════════════════════════════════════════════
# The alpha channel: cutting one, cleaning one, and putting something behind it.

_pix(
    'mt_key',
    'Key background',
    'Matte',
    'Key out a FLAT background by colour distance from a sampled corner. Exact on '
    'the studio plates this pipeline makes; wrong on a photograph — it is a keyer, '
    'not a segmentation, and the difference shows on a hair edge. Use Remove '
    'background for a real matte.',
    '<path d="M14.4 9.6a3.4 3.4 0 10-3.4 3.4l-1 1-2 .4-.4 2-2 .4-.4 2.4 3.4-.4.4-2 2-.4.4-2 2.6-2.6z"/>',
    [
        e('pick', 'Sample', 'corner', ['corner', 'top-left', 'top-right', 'colour']),
        c('col', 'Colour', '#ffffff'),
        i('tol', 'Tolerance', 18, 1, 120, 1),
        i('soft', 'Softness', 14, 1, 120, 1),
        f('feather', 'Feather', 1.0, 0, 12, 0.1),
    ],
    pfn=cfx._px_bg,
)

_pix(
    'mt_feather',
    'Feather matte',
    'Matte',
    'Blur the alpha. Softens a hard cut so it stops reading as a sticker.',
    '<circle cx="12" cy="12" r="7.4" stroke-dasharray="1.4 2.4"/><circle cx="12" cy="12" r="4"/>',
    [f('r', 'Radius', 1.5, 0, 20, 0.1)],
    pfn=_px_alpha_feather,
    needs='alpha',
)

_pix(
    'mt_choke',
    'Choke matte',
    'Matte',
    'Pull the matte IN by a pixel or two. What kills the light halo a keyer leaves '
    'around a subject cut off a bright plate.',
    '<circle cx="12" cy="12" r="8"/><circle cx="12" cy="12" r="5" stroke-dasharray="2 2"/>'
    '<path d="M12 4v2.6M12 17.4V20M4 12h2.6M17.4 12H20"/>',
    [i('n', 'Pixels', 1, 0, 8, 1)],
    pfn=_px_alpha_choke,
    needs='alpha',
)

_pix(
    'mt_invert',
    'Invert matte',
    'Matte',
    'Swap what is kept for what is cut. The fastest way to check that a matte is actually where you think it is.',
    '<circle cx="12" cy="12" r="8.4" stroke-dasharray="2.4 2"/>'
    '<path d="M12 3.6a8.4 8.4 0 010 16.8z" fill="currentColor" stroke="none"/>',
    pfn=_px_alpha_invert,
    needs='alpha',
)

_pix(
    'mt_outline',
    'Outline',
    'Matte',
    'A stroke that follows the MATTE, grown out of the alpha itself rather than drawn round the bounding box.',
    '<path d="M12 3.4l8.6 5v7.2L12 20.6 3.4 15.6V8.4z"/>'
    '<path d="M12 7l5 2.8v4.4L12 17l-5-2.8V9.8z" stroke-dasharray="2 2"/>',
    [i('n', 'Width px', 3, 1, 24, 1), c('col', 'Colour', '#ffffff')],
    pfn=_px_outline,
    needs='alpha',
)

_pix(
    'mt_glow',
    'Outer glow',
    'Matte',
    'A soft coloured halo grown out of the alpha. Reads as light coming off the '
    'subject rather than a border drawn around it.',
    '<circle cx="12" cy="12" r="4.6"/><circle cx="12" cy="12" r="8.4" stroke-dasharray="1.2 2.6"/>',
    [f('r', 'Radius', 12, 1, 60, 0.5), f('a', 'Strength', 70, 0, 100, 1), c('col', 'Colour', '#66d9ff')],
    pfn=_px_glow,
    needs='alpha',
)

_pix(
    'mt_shadow',
    'Drop shadow',
    'Matte',
    'A blurred, offset copy of the matte behind the subject. It grows the canvas '
    'rather than clipping the shadow at the old edge — a shadow cut off at the frame '
    'is worse than no shadow.',
    '<rect x="3.4" y="3.4" width="12" height="12" rx="1.6"/>'
    '<path d="M8.6 20.6h9a3 3 0 003-3v-9" stroke-dasharray="2.4 2"/>',
    [
        i('off', 'Offset px', 10, -60, 60, 1),
        f('r', 'Blur', 8, 0, 60, 0.5),
        f('a', 'Opacity %', 55, 0, 100, 1),
        c('col', 'Colour', '#000000'),
    ],
    pfn=_px_dropshadow,
    needs='alpha',
)

_pix(
    'mt_flat',
    'Flatten',
    'Matte',
    'Composite onto a solid ground — the honest inverse of the keyer, and what a '
    'trainer tile needs, since a transparent PNG trains as black.',
    '<rect x="3.6" y="3.6" width="16.8" height="16.8" rx="2"/><path d="M3.6 14.4l5-4.6 3.4 3 3-2.4 5.4 4.6"/>',
    [c('col', 'Ground', '#808080')],
    pfn=cfx._px_flat,
)

_pix(
    'mt_gradient',
    'Gradient ground',
    'Matte',
    'Composite over a vertical two-colour ground. What to reach for when a flat '
    'colour behind a cut-out reads as a sticker.',
    '<rect x="3.6" y="3.6" width="16.8" height="16.8" rx="2"/>'
    '<path d="M3.6 8h16.8M3.6 12h16.8M3.6 16h16.8" stroke-dasharray="2 2"/>',
    [c('top', 'Top', '#1b2733'), c('bot', 'Bottom', '#63707e')],
    pfn=_px_ground_grad,
)


# ══ SIDE · ENHANCE ══════════════════════════════════════════════════════════
# Model-backed, but not diffusion edits: these have a right answer and are only
# here because they need seconds and a GPU rather than a millisecond of
# arithmetic. They cannot be previewed, and the banner over the picture says so
# rather than showing a frame that quietly omits them.

_svc(
    'en_upscale',
    'Upscale',
    'Enhance',
    'ESRGAN upscale through ComfyUI, falling back to a PIL LANCZOS resize when Comfy '
    'is not reachable — and the job log says WHICH ran, because those two are not the '
    'same picture. Going up from a small source enlarges the detail that is there; '
    'the model hallucinates the rest.',
    '<path d="M4 14v6h6M20 10V4h-6M20 4l-7 7M4 20l7-7"/>',
    [e('scale', 'Scale', '2', ['2', '3', '4'])],
    svc='upscale',
)

_svc(
    'en_nobg',
    'Remove background',
    'Enhance',
    'Matte the subject out with u2net and keep the result as transparency. A real '
    'segmentation, unlike the deterministic keyer — it works on a photograph, and it '
    'costs a model load.',
    '<rect x="3" y="3" width="18" height="18" rx="2.4" stroke-dasharray="3 2.4"/><circle cx="12" cy="12" r="4.6"/>',
    svc='bg_remove',
)

_svc(
    'en_faceup',
    'Face restore',
    'Enhance',
    'Re-render the face region at full resolution through the same Qwen edit graph, '
    'asked only to restore detail. It is a generative pass on the face and nothing '
    'else — the identity check on the bake is what tells you whether it stayed the '
    'same person.',
    '<circle cx="12" cy="9.4" r="4.2"/><path d="M4.6 20.6c0-4 3.3-7.2 7.4-7.2s7.4 3.2 7.4 7.2"/>'
    '<path d="M18.4 4.6l1 2.2 2.2 1-2.2 1-1 2.2-1-2.2-2.2-1 2.2-1z"/>',
    [f('strength', 'Strength', 0.45, 0.1, 1.0, 0.05)],
    svc='face_restore',
    needs='comfy',
)

_act(
    'en_repair',
    'Repair area',
    'Enhance',
    'Paint over an area on the preview and have Qwen repaint just that region — the '
    'mask travels with the job, so nothing outside what you painted is touched. The '
    'tool for a melted hand or a stray artefact that no global op can reach '
    '([[project_hand_repair_arcane]]).',
    '<path d="M14.5 3.5a2.1 2.1 0 013 3L8 16l-4.5 1.5L5 13z"/><path d="M12 6l3 3"/>'
    '<path d="M19 14.6c1.4 1.6 2 2.8 2 3.8a2 2 0 11-4 0c0-1 .6-2.2 2-3.8z"/>',
    bar='side',
    needs='comfy',
)
