# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Registry entries: SIDE / SCENE and SIDE / STYLE — the generative clauses."""

from __future__ import annotations

from zyg_workflows.picture_fx.pixel_tone import (
    e,
    f,
    s,
)

from zyg_workflows.picture_fx.registry import _amt, _edit, _pick

# ══ SIDE · SCENE (generative) ═══════════════════════════════════════════════
# What is AROUND the subject, and where the camera is. A scene op and a camera
# op stacked together are two instructions about the same frame; the receipt
# prints both so you can see them arguing before you spend a render.

_edit(
    'sc_bg',
    'Background',
    'Scene',
    'Replace what is behind the subject. Say what should be there — a blank instruction '
    'gets a blank studio wall, which is a decision the model made and not one you did.',
    '<rect x="3" y="4.6" width="18" height="14.8" rx="2"/>'
    '<path d="M3 15l5-4.6 3.4 3 3-2.4 6.6 5.6"/><circle cx="8.4" cy="9" r="1.6"/>',
    [s('v', 'Background', '', 'e.g. "a dim workshop with tools on the wall"')],
    fn=lambda p, x: f'replace the background with {_pick(p)}, keeping the subject exactly as it is' if _pick(p) else '',
)

_edit(
    'sc_bgblur',
    'Background blur',
    'Scene',
    'Throw the background out of focus generatively — a real depth-of-field falloff '
    "rather than the Detail section's band mask, which follows the frame instead of the "
    'scene.',
    '<circle cx="9" cy="12" r="4.6"/><circle cx="17" cy="9" r="2.6" stroke-dasharray="1.4 2"/>'
    '<circle cx="18" cy="16" r="2" stroke-dasharray="1.4 2"/>',
    [f('v', 'Strength', 60, 10, 100, 1)],
    fn=lambda p, x: (
        f'throw the background {_amt(p["v"])} out of focus with a shallow depth of field, keeping the subject sharp'
    ),
)

_edit(
    'sc_relight',
    'Relight',
    'Scene',
    'Re-light the whole frame. Qwen relights unprompted whenever it edits, so pinning '
    'the light explicitly is how a two-shot composite stays consistent '
    '([[project_split_style_composite]]).',
    '<path d="M12 2.6v2.6M4.6 12H2M22 12h-2.6M6.4 6.4L4.6 4.6M17.6 6.4l1.8-1.8"/>'
    '<path d="M9 15.4a4.6 4.6 0 116 0c-.8.8-1 1.6-1 2.6h-4c0-1-.2-1.8-1-2.6z"/>'
    '<path d="M10 20.6h4"/>',
    [
        e(
            'v',
            'Light',
            'soft key from the left',
            [
                'soft key from the left',
                'soft key from the right',
                'hard key from the left',
                'hard key from the right',
                'flat frontal light',
                'rim light from behind',
                'top light',
                'underlight',
                'window light',
                'candlelight',
                'firelight',
                'overcast daylight',
                'golden hour',
                'blue hour',
                'moonlight',
                'neon',
            ],
        ),
        f('v2', 'Contrast', 50, 0, 100, 1),
    ],
    fn=lambda p, x: (
        f'light the scene with {p["v"]}, at '
        f'{"high" if p["v2"] > 66 else ("moderate" if p["v2"] > 33 else "low")} contrast'
    ),
)

_edit(
    'sc_time',
    'Time of day',
    'Scene',
    'Move the frame through the day. A light change and a colour change at once — stack '
    'it with Relight and the two argue.',
    '<circle cx="12" cy="12" r="4"/><path d="M12 2.6v2.6M12 18.8v2.6M2.6 12h2.6M18.8 12h2.6"/>'
    '<path d="M5.6 5.6l1.8 1.8M16.6 16.6l1.8 1.8"/>',
    [
        e(
            'v',
            'When',
            'midday',
            ['dawn', 'early morning', 'midday', 'afternoon', 'golden hour', 'dusk', 'twilight', 'night'],
        )
    ],
    fn=lambda p, x: f'set the scene at {p["v"]}',
)

_edit(
    'sc_weather',
    'Weather',
    'Scene',
    'Weather in the frame. It lands on the light as much as on the air, so a weather op '
    'and a relight op are usually one too many.',
    '<path d="M7.4 15.4a3.8 3.8 0 01.4-7.6 5 5 0 019.4-1 3.6 3.6 0 01.4 7.2z"/>'
    '<path d="M8.6 18.4l-1 2.2M12.4 18.4l-1 2.2M16.2 18.4l-1 2.2"/>',
    [
        e(
            'v',
            'Weather',
            'clear',
            ['clear', 'overcast', 'light rain', 'heavy rain', 'storm', 'fog', 'mist', 'snow', 'wind', 'dust'],
        )
    ],
    fn=lambda p, x: f'set the weather to {p["v"]}' if p['v'] != 'clear' else 'make the weather clear',
)

_edit(
    'sc_env',
    'Environment',
    'Scene',
    'Move the whole scene somewhere else — interior, exterior, a named place. Bigger than '
    'a background swap: it relights and reframes with it.',
    '<path d="M3.4 10.6L12 3.4l8.6 7.2"/><path d="M5.6 9.4v11h12.8v-11"/><path d="M10 20.4v-5.6h4v5.6"/>',
    [s('v', 'Where', '', 'e.g. "a cold stone chapel"')],
    fn=lambda p, x: f'place the subject in {_pick(p)}' if _pick(p) else '',
)

_edit(
    'sc_props',
    'Props',
    'Scene',
    'Put things in the scene around the subject. The anachronism gate reads what comes '
    'back, so a period scene is where this needs checking.',
    '<rect x="3.4" y="9.4" width="7.2" height="7.2" rx="1"/>'
    '<circle cx="17" cy="8.4" r="3.4"/><path d="M13.4 13.4h7.2v7.2h-7.2z"/>',
    [s('v', 'Props', '')],
    fn=lambda p, x: f'add {_pick(p)} to the scene around the subject' if _pick(p) else '',
)

_edit(
    'sc_camera',
    'Camera angle',
    'Scene',
    'Move the camera rather than the subject. On a character with a locked front anchor '
    'this is the op that loses the identity check, because the anchor cannot see the '
    'new view ([[project_creature_body_plan_lock]]).',
    '<path d="M3.4 7.4h11v9.2h-11z"/><path d="M14.4 11l6.2-3.6v9.2L14.4 13z"/>',
    [
        e(
            'v',
            'Angle',
            'eye level',
            [
                'eye level',
                'low angle',
                'high angle',
                'overhead',
                'dutch tilt',
                'three-quarter left',
                'three-quarter right',
                'profile',
                'from behind',
                'over the shoulder',
            ],
        )
    ],
    fn=lambda p, x: f'shoot the subject from {p["v"]}',
)

_edit(
    'sc_shot',
    'Shot size',
    'Scene',
    'How much of the subject is in frame. A reframe, so anything the current crop already '
    'decided is decided again by the model.',
    '<rect x="3" y="4.6" width="18" height="14.8" rx="1.6"/><rect x="7.4" y="8" width="9.2" height="11.4" rx="1"/>',
    [
        e(
            'v',
            'Shot',
            'medium shot',
            [
                'extreme close-up',
                'close-up',
                'medium close-up',
                'medium shot',
                'medium long shot',
                'full shot',
                'wide shot',
                'extreme wide shot',
            ],
        )
    ],
    fn=lambda p, x: f'reframe as a {p["v"]}',
)

_edit(
    'sc_lens',
    'Lens',
    'Scene',
    'The focal length look — compression, falloff and how the face is shaped by it. A '
    '24mm and an 85mm are two different faces on the same person.',
    '<circle cx="12" cy="12" r="8.4"/><circle cx="12" cy="12" r="4"/><path d="M12 3.6v2.4M12 18v2.4"/>',
    [
        e(
            'v',
            'Lens',
            '50mm',
            ['16mm ultra wide', '24mm wide', '35mm', '50mm', '85mm portrait', '135mm telephoto', '200mm long lens'],
        )
    ],
    fn=lambda p, x: f'render as if shot on a {p["v"]} lens, with the compression and depth falloff that lens gives',
)

_edit(
    'sc_atmos',
    'Atmosphere',
    'Scene',
    'Haze, smoke, godrays, dust in the air. Depth cues that a clean render has none of, '
    'and the cheapest way to stop a background sitting flat against the subject.',
    '<path d="M3.4 8.6h8M13.4 8.6h7.2M3.4 12.4h5.6M11.4 12.4h9.2M5.4 16.2h9.2M17 16.2h3.6"/>',
    [
        e(
            'v',
            'Atmosphere',
            'light haze',
            ['light haze', 'heavy haze', 'smoke', 'dust motes', 'godrays', 'steam', 'sea spray', 'none'],
        ),
        f('v2', 'Strength', 50, 0, 100, 1),
    ],
    fn=lambda p, x: (
        f'add {_amt(p["v2"])} {p["v"]} to the air of the scene'
        if p['v'] != 'none'
        else 'clear the air of haze and atmosphere'
    ),
)


# ══ SIDE · STYLE (generative) ═══════════════════════════════════════════════
# How the picture is RENDERED, as opposed to what is in it. One style op per
# stack: two of them is a prompt asking for an average of two styles, which is
# a third style nobody chose.


def _style(id_, lb, tip, svg, phrase):
    return _edit(
        id_,
        lb,
        'Style',
        tip,
        svg,
        [f('v', 'Strength', 70, 10, 100, 1)],
        fn=lambda p, x, _ph=phrase: f'render the image {_amt(p["v"])} in the style of {_ph}',
    )


_style(
    'st_photo',
    'Photoreal',
    'Push toward a photograph: real lens behaviour, real skin, no illustration cues. The '
    "style the character pipeline's FLUX half already targets.",
    '<rect x="3" y="6" width="18" height="13" rx="2"/><circle cx="12" cy="12.4" r="4"/>'
    '<path d="M8.6 6l1.4-2.4h4l1.4 2.4"/>',
    'a sharp, naturally lit photograph',
)

_style(
    'st_arcane',
    'Arcane',
    'The painterly Arcane look this pipeline already trains per character — which means '
    'a character with an Arcane LoRA does NOT need this op, it needs its own weights '
    '([[project_arcane_restyle]]).',
    '<path d="M12 3.4l2.6 5.4 5.8.8-4.2 4.2 1 5.8-5.2-2.8-5.2 2.8 1-5.8L3.6 9.6l5.8-.8z"/>',
    'the Arcane animated series: painterly brushwork, heavy rim light, desaturated teal and amber palette',
)

_style(
    'st_anime',
    'Anime',
    'Cel-shaded anime. The SDXL half of this pipeline is the twin built for exactly this, '
    'so on a character that has one, use the twin ([[project_sdxl_animated]]).',
    '<circle cx="12" cy="12" r="8.4"/><path d="M8 10.4c.8-1 1.8-1 2.6 0M13.4 10.4c.8-1 1.8-1 2.6 0"/>'
    '<path d="M9.6 15.4c1.4 1.2 3.4 1.2 4.8 0"/>',
    'cel-shaded anime illustration with clean line art and flat colour',
)

_style(
    'st_oil',
    'Oil painting',
    'Visible brushwork and canvas tooth. It restructures fine detail by construction, so '
    'a face will come back a slightly different face.',
    '<path d="M12 3.4c4.8 0 8.6 3.4 8.6 7.6 0 2.6-2 3.6-3.6 3.6h-1.6c-1.2 0-2 .8-2 1.8 0 .6.3 1 .6 1.4.3.4.6.8.6 1.4 0 1-.9 1.6-2 1.6-4.8 0-8.6-3.8-8.6-8.6S7.2 3.4 12 3.4z"/>'
    '<circle cx="8.4" cy="10" r="1"/><circle cx="12" cy="7.6" r="1"/><circle cx="15.6" cy="10" r="1"/>',
    'an oil painting with visible brushwork and canvas texture',
)

_style(
    'st_water',
    'Watercolour',
    'Wet edges, bloom and paper grain. The palest of the style ops — it drops contrast '
    'hard, so it wants a levels op after it.',
    '<path d="M12 3.4c3.4 4.6 5.6 7.8 5.6 10.4a5.6 5.6 0 11-11.2 0c0-2.6 2.2-5.8 5.6-10.4z"/>'
    '<path d="M6.4 16.6c2 1.4 4 1.4 5.6.4s3.6-1 5.6.4"/>',
    'a loose watercolour painting with wet edges and paper grain',
)

_style(
    'st_ink',
    'Ink drawing',
    'Line and hatching only. It throws away every value that is not carried by a line, '
    'which is a real test of whether the composition works.',
    '<path d="M14.5 3.5a2.1 2.1 0 013 3L8 16l-4.5 1.5L5 13z"/><path d="M12 6l3 3"/><path d="M4 20.6h16"/>',
    'a pen-and-ink drawing with cross-hatching and no colour',
)

_style(
    'st_comic',
    'Comic',
    'Bold outlines, flat inks, halftone. Legible at thumbnail size, which is the whole point of the look.',
    '<rect x="3.4" y="3.4" width="17.2" height="17.2" rx="2"/><path d="M3.4 12h17.2M12 3.4v17.2"/>',
    'a comic book panel with bold outlines, flat inking and halftone shading',
)

_style(
    'st_3d',
    '3D render',
    'A clean CG render look — subsurface skin, soft studio HDRI, no film artefacts. The '
    'opposite direction to the Grade section, and stacking both cancels out.',
    '<path d="M12 3.4l8.6 4.8v8.8L12 21.4 3.4 17V8.2z"/><path d="M12 12.2l8.6-4M12 12.2v9.2M12 12.2L3.4 8.2"/>',
    'a clean 3D render with subsurface skin shading and soft studio lighting',
)

_style(
    'st_noir',
    'Film noir',
    'Hard key, deep black, high contrast monochrome. The Colour section reaches the same '
    'place deterministically and instantly — this one restructures the LIGHT to get there.',
    '<circle cx="12" cy="12" r="8.4"/><path d="M12 3.6a8.4 8.4 0 000 16.8z" fill="currentColor" stroke="none"/>'
    '<path d="M16 6.6l2.4-2.4"/>',
    'high-contrast black and white film noir with hard shadows and deep blacks',
)

_style(
    'st_pixel',
    'Pixel art',
    "A real pixel-art restyle, not a downsample. The Detail section's pixelate is the "
    'deterministic version and it is instant — try that first.',
    '<rect x="4" y="4" width="4" height="4"/><rect x="10" y="4" width="4" height="4"/>'
    '<rect x="16" y="10" width="4" height="4"/><rect x="4" y="16" width="4" height="4"/>'
    '<rect x="10" y="10" width="4" height="4"/>',
    'low-resolution pixel art with a limited palette and hard pixel edges',
)

_style(
    'st_poster',
    'Poster',
    'Graphic, flattened, print-ready. It will simplify the subject, which on a face is a loss of identity by design.',
    '<rect x="4.6" y="3" width="14.8" height="18" rx="1.6"/>'
    '<path d="M4.6 15l4.4-4 3 2.6 2.6-2 4.8 4.4"/><path d="M7.6 18.6h8.8"/>',
    'a graphic screen-printed poster with flat colour and simplified shapes',
)

_edit(
    'st_custom',
    'Custom style',
    'Style',
    'Your own style sentence, sent verbatim. Nothing here interprets it — which is the '
    "point, and also why a vague one comes back as the model's house style.",
    '<path d="M12 3.4l2.6 5.4 5.8.8-4.2 4.2 1 5.8-5.2-2.8-5.2 2.8 1-5.8L3.6 9.6l5.8-.8z"/>'
    '<path d="M18.6 17l1 2 2 1-2 1-1 2-1-2-2-1 2-1z"/>',
    [s('v', 'Style', ''), f('v2', 'Strength', 70, 10, 100, 1)],
    fn=lambda p, x: f'render the image {_amt(p["v2"])} in the style of {_pick(p)}' if _pick(p) else '',
)
