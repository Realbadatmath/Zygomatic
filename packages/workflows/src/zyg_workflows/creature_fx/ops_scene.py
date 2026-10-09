# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""SIDE / SCENE — around the creature, and why a trained tile defaults to a plain studio.

Moved verbatim out of the old single-file creature_fx.py (lines 2766-3003).
"""

from __future__ import annotations

from zyg_workflows.creature_fx.base import _amt, _edit, b, e, f, s


# ══ SIDE · SCENE ════════════════════════════════════════════════════════════
# Around the creature. The default for anything that will be TRAINED ON is a
# plain studio background -- a habitat baked into every tile teaches the LoRA
# the habitat as part of the creature. The rail says so on the op.

_edit(
    'cx_bg',
    'Background',
    'Scene',
    'Background — plain is the default and it is not a style choice: a habitat in every '
    'training tile teaches the LoRA that the habitat is PART of the creature. Use a '
    'scene for beauty renders, plain for anything that will train.',
    '<rect x="3.6" y="4.6" width="16.8" height="14.8" rx="1.8"/><path d="M3.6 15.4l4.6-5 3.4 3.4 3-2.6 5.8 5"/>',
    [
        e(
            'v',
            'Background',
            'neutral grey studio',
            [
                'neutral grey studio',
                'white studio',
                'black',
                'soft gradient',
                'blurred natural setting',
                'full environment',
            ],
        ),
        b('clean', 'No text, no people, no props', True),
    ],
    fn=lambda p, x: (
        f'place it against a {p["v"]} background' + (', no text, no people and no other objects' if p['clean'] else '')
    ),
    neg='text, watermark, people',
)

_edit(
    'cx_habitat',
    'Habitat',
    'Scene',
    'Habitat — where the creature lives, written out. Only reaches the image when the '
    'Background op is set to an environment; otherwise it is recorded in the recipe and '
    'nothing else, which is deliberate rather than a bug.',
    '<path d="M3.6 18.6h16.8"/><path d="M4.4 18.6l4.6-8 3.4 5 2.4-3.4 4.8 6.4"/><circle cx="17.6" cy="6.6" r="2.4"/>',
    [
        e(
            'v',
            'Habitat',
            'forest',
            [
                'forest',
                'desert',
                'tundra',
                'wetland',
                'deep ocean',
                'cave system',
                'volcanic',
                'alien world',
                'ruins',
                'grassland',
                'canopy',
                'abyssal trench',
            ],
        )
    ],
    fn=lambda p, x: f'in a {p["v"]} setting',
)

_edit(
    'cx_time',
    'Time of day',
    'Scene',
    "Time of day — which is really a light-colour op wearing a scene's clothes. Golden "
    'hour warms every surface in the frame, including the ones you spent an hour '
    'colour-matching.',
    '<circle cx="12" cy="13.4" r="3.6"/><path d="M3.6 18.6h16.8"/><path d="M12 5.4v2.4M6.4 8l1.6 1.6M17.6 8L16 9.6"/>',
    [e('v', 'Time', 'neutral', ['neutral', 'dawn', 'morning', 'midday', 'golden hour', 'dusk', 'night', 'moonlit'])],
    fn=lambda p, x: '' if p['v'] == 'neutral' else f'lit as {p["v"]}',
)

_edit(
    'cx_weather',
    'Weather',
    'Scene',
    'Weather — rain, snow, fog, wind. It lands on the creature as well as around it, so '
    'it overlaps Wet and Frost on purpose: use those for the animal, this for the air.',
    '<path d="M6.6 13.4a3.6 3.6 0 01.6-7.2 5 5 0 019.4 1 3 3 0 01-.6 6.2z"/>'
    '<path d="M8 17l-1 3M12 17l-1 3M16 17l-1 3"/>',
    [
        e(
            'v',
            'Weather',
            'clear',
            ['clear', 'rain', 'heavy rain', 'snow', 'fog', 'dust storm', 'strong wind', 'falling ash'],
        )
    ],
    fn=lambda p, x: '' if p['v'] == 'clear' else f'in {p["v"]}',
)

_edit(
    'cx_key',
    'Key light',
    'Scene',
    'Key light — the main source: where it comes from and how hard it is. Hard light '
    'shows surface, soft light shows form, and a sheet needs the same one on every cell.',
    '<circle cx="8.6" cy="8.6" r="3.4"/><path d="M8.6 3.4v1.8M4 8.6H2.2M12 12.4l1.4 1.4"/>'
    '<path d="M13.4 19.4c0-3.4 2.4-6 5.4-6"/>',
    [
        e('dir', 'From', 'front left', ['front', 'front left', 'front right', 'the side', 'behind', 'above', 'below']),
        e('q', 'Quality', 'soft', ['soft', 'hard', 'very hard, single source']),
        f('a', 'Strength', 60, 0, 100, 1),
    ],
    fn=lambda p, x: f'lit by a {p["q"]} key light from {p["dir"]}' if _amt(p['a']) else '',
)

_edit(
    'cx_rim',
    'Rim light',
    'Scene',
    'Rim light — the edge separation that lifts a creature off its background. On a '
    'furred creature it is also the only light that shows the coat depth at all.',
    '<circle cx="12" cy="12" r="6.4"/><path d="M17.6 8.4a6.4 6.4 0 010 7.2" stroke-width="2.6"/>',
    [s('col', 'Colour', 'cool white', pat=r"[A-Za-z ,'-]{0,40}"), f('a', 'Strength', 60, 0, 100, 1)],
    fn=lambda p, x: (
        f'a {_amt(p["a"], ("subtle", "clear", "strong", "blazing"))} {p["col"]} rim light along its edge'
        if _amt(p['a'])
        else ''
    ),
)

_edit(
    'cx_fill',
    'Fill',
    'Scene',
    'Fill — how dark the shadow side goes. Low fill is dramatic and hides half the '
    'anatomy, which is fine for a poster and fatal for a reference plate.',
    '<circle cx="12" cy="12" r="7.4"/>'
    '<path d="M12 4.6a7.4 7.4 0 000 14.8z" fill="currentColor" stroke="none" opacity=".35"/>',
    [f('v', 'Fill', 50, 0, 100, 1)],
    fn=lambda p, x: (
        f'{_amt(100 - p["v"], ("open", "moderate", "deep", "near-black"))} shadows'
        if _amt(100 - p['v'])
        else 'evenly filled, open shadows'
    ),
)

_edit(
    'cx_back',
    'Practical light',
    'Scene',
    'Practical light — a source that is IN the picture: a lantern, a fire, glowing '
    'water. It motivates the colour of the light and lets a scene be lit by its own '
    'contents.',
    '<path d="M9.4 20.4h5.2"/><path d="M10.4 17.4h3.2"/>'
    '<path d="M12 3.6c2.4 3 4 5.4 4 7.4a4 4 0 11-8 0c0-2 1.6-4.4 4-7.4z"/>',
    [
        e(
            'v',
            'Source',
            'none',
            [
                'none',
                'a lantern',
                'firelight',
                'glowing water',
                'bioluminescent plants',
                'lightning',
                'a shaft of sunlight',
            ],
        )
    ],
    fn=lambda p, x: '' if p['v'] == 'none' else f'lit from within the scene by {p["v"]}',
)

_edit(
    'cx_fog',
    'Atmosphere',
    'Scene',
    'Atmosphere — haze, god rays, floating particles. Depth without geometry, and the '
    'cheapest way to stop a creature looking pasted onto its background.',
    '<path d="M4.4 9.4h15.2M6.4 13h11.2M4.4 16.6h15.2"/><path d="M9.4 5.4l1.6-2M14.6 5.4l1.6-2"/>',
    [
        e('kind', 'Kind', 'none', ['none', 'haze', 'god rays', 'floating dust', 'mist', 'drifting embers', 'spores']),
        f('a', 'Amount', 50, 0, 100, 1),
    ],
    fn=lambda p, x: '' if p['kind'] == 'none' or not _amt(p['a']) else f'{_amt(p["a"])} {p["kind"]} in the air',
)

_edit(
    'cx_shadow',
    'Shadow',
    'Scene',
    'Shadow — the one it casts, separately from the light that casts it. A creature with '
    'no shadow floats, and a plain-background plate is where that is most obvious.',
    '<ellipse cx="12" cy="18" rx="7.4" ry="2.4"/><path d="M12 4.4v10"/><path d="M9 8.4l3-4 3 4"/>',
    [
        e(
            'v',
            'Shadow',
            'soft contact shadow',
            [
                'none',
                'soft contact shadow',
                'hard cast shadow',
                'long raking shadow',
                'shadow falling toward the camera',
            ],
        )
    ],
    fn=lambda p, x: 'no shadow at all' if p['v'] == 'none' else f'a {p["v"]} under it',
)

_edit(
    'cx_scale_ref',
    'Scale cue',
    'Scene',
    'Scale cue — something in frame that says how big the creature actually is. Without '
    'one, every creature is the size of the frame, and a brief that says "the size of a '
    'horse" is unfalsifiable.',
    '<path d="M3.6 20.4h16.8"/><rect x="5" y="12.4" width="4" height="8" rx="1"/>'
    '<path d="M13 20.4V8.4a3.4 3.4 0 016.8 0v12"/>',
    [
        e(
            'v',
            'Cue',
            'none',
            ['none', 'a human figure for scale', 'a tree', 'a doorway', 'a hand', 'a small bird', 'a boulder'],
        ),
        b('far', 'Keep it small and distant', True),
    ],
    fn=lambda p, x: (
        ''
        if p['v'] == 'none'
        else f'include {p["v"]} in the background for scale'
        + (', small and far off, not a second subject' if p['far'] else '')
    ),
)
