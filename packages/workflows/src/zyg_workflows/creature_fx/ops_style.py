# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""SIDE / STYLE — restyles, the ops most likely to cost the creature its identity.

Moved verbatim out of the old single-file creature_fx.py (lines 3004-3168).
"""

from __future__ import annotations

from zyg_workflows.creature_fx.base import _amt, _edit, _pick, e, f, s


# ══ SIDE · STYLE ════════════════════════════════════════════════════════════
# How it is rendered, not what it is. Style is baked into a LoRA at train time
# ([[project_arcane_restyle]]), so changing it here changes what the NEXT
# training run learns -- which is the point, and also the risk.

_edit(
    'cl_style',
    'Render style',
    'Style',
    'Render style — the medium. This is what a restyle bakes into the LoRA, so a change '
    'here on a training tile is a change to the character, not to one picture.',
    '<path d="M4.4 19.6c-1-4.4.6-9 4-12.4 3.4-3.4 8-4.6 12.2-3.4"/>'
    '<path d="M12 12.4a3.4 3.4 0 105.4 4"/><path d="M4.4 19.6l3.6-1.4"/>',
    [
        e(
            'v',
            'Style',
            'as is',
            [
                'as is',
                '3D animated film render',
                'photoreal wildlife photograph',
                'painterly concept art',
                'anime',
                'Arcane painted style',
                'claymation',
                'plush toy',
                'ink line art',
                'watercolour',
                'pencil study',
                'stop-motion puppet',
            ],
        )
    ],
    fn=lambda p, x: '' if p['v'] == 'as is' else f'render it as {p["v"]}',
)

_edit(
    'cl_strength',
    'Style strength',
    'Style',
    'Style strength — how far to push the style before it starts eating the identity. '
    'The number that decides whether a restyle is a look or a different creature.',
    '<path d="M4.4 18.6h15.2"/><path d="M7.4 18.6V9.4M12 18.6V5.4M16.6 18.6v-6"/>',
    [f('v', 'Strength', 60, 0, 100, 1)],
    fn=lambda p, x: (
        f'apply the style {_amt(p["v"], ("lightly", "clearly", "strongly", "completely"))}' if _amt(p['v']) else ''
    ),
)

_edit(
    'cl_detail',
    'Detail level',
    'Style',
    'Detail level — how much information is in the picture overall. Distinct from the '
    'Surface micro-detail op: this is the whole rendering, including the background.',
    '<circle cx="12" cy="12" r="8.4"/><path d="M12 3.6v16.8M3.6 12h16.8"/>'
    '<path d="M6.2 6.2l11.6 11.6M17.8 6.2L6.2 17.8"/>',
    [f('v', 'Detailed / simple', 30, -100, 100, 1)],
    fn=lambda p, x: (
        f'render it {_amt(p["v"])} {"more detailed and intricate" if p["v"] > 0 else "more simply, with fewer details"}'
        if _amt(p['v'])
        else ''
    ),
)

_edit(
    'cl_line',
    'Linework',
    'Style',
    'Linework — whether there is an outline, and how heavy. The single change that '
    'moves a render from film to illustration.',
    '<path d="M4.4 12a7.6 7.6 0 1115.2 0 7.6 7.6 0 01-15.2 0z" stroke-width="2.6"/><circle cx="12" cy="12" r="3"/>',
    [e('v', 'Lines', 'none', ['none', 'thin clean outlines', 'bold outlines', 'sketchy lines', 'coloured lines'])],
    fn=lambda p, x: '' if p['v'] == 'none' else f'drawn with {p["v"]}',
)

_edit(
    'cl_shade',
    'Shading',
    'Style',
    'Shading — smooth, cel, hatched, flat. Independent of the medium: cel shading in a '
    '3D render is a real and common choice.',
    '<circle cx="12" cy="12" r="8.4"/>'
    '<path d="M12 3.6a8.4 8.4 0 010 16.8z" fill="currentColor" stroke="none" opacity=".3"/>'
    '<path d="M12 3.6v16.8"/>',
    [
        e(
            'v',
            'Shading',
            'smooth',
            ['smooth', 'cel shaded', 'hatched', 'flat, no shading', 'painterly', 'high contrast'],
        )
    ],
    fn=lambda p, x: '' if p['v'] == 'smooth' else f'{p["v"]}',
)

_edit(
    'cl_grain',
    'Film look',
    'Style',
    'Film look — grain, halation, a filmic curve, said to the MODEL. The Pixel section '
    'has a real grain op that is exact and instant; this one asks for the whole look to '
    'be rendered that way instead.',
    '<rect x="3.6" y="5.4" width="16.8" height="13.2" rx="1.6"/>'
    '<path d="M3.6 8.4h16.8M3.6 15.6h16.8"/><circle cx="8" cy="12" r="1"/>'
    '<circle cx="12.4" cy="12" r="1"/><circle cx="16.4" cy="12" r="1"/>',
    [e('v', 'Look', 'none', ['none', '35mm film', '16mm grain', 'vintage photograph', 'technicolor', 'bleach bypass'])],
    fn=lambda p, x: '' if p['v'] == 'none' else f'with a {p["v"]} look',
)

_edit(
    'cl_era',
    'Reference era',
    'Style',
    'Reference era — the visual tradition to borrow from: natural history plate, '
    'creature-feature poster, field guide, bestiary woodcut. A whole set of conventions '
    'in one phrase.',
    '<path d="M4.4 5.4h15.2v13.2H4.4z"/><path d="M4.4 8.6h15.2"/><path d="M7.4 12h4M7.4 15h9.2"/>',
    [
        e(
            'v',
            'Tradition',
            'none',
            [
                'none',
                'a Victorian natural history plate',
                'a field guide illustration',
                'a bestiary woodcut',
                'a creature-feature poster',
                'a museum diorama',
                'a scientific specimen photograph',
            ],
        )
    ],
    fn=lambda p, x: '' if p['v'] == 'none' else f'in the tradition of {p["v"]}',
)

_edit(
    'cl_free',
    'Free instruction',
    'Style',
    'Free instruction — a sentence of your own, appended last so it wins any argument '
    'with the ops above it. Everything this toolbox does is ultimately this, with the '
    'phrasing already worked out.',
    '<path d="M4.4 17.6l9.6-9.6a2.6 2.6 0 013.8 3.8l-9.6 9.6H4.4z"/>'
    '<path d="M14.4 6.4l3.2 3.2"/><path d="M17.6 3.4l1.2 1.2"/>',
    [s('v', 'Say', '', 'appended to the end of the instruction, verbatim')],
    fn=lambda p, x: _pick(p),
)

_edit(
    'cl_neg',
    'Forbid',
    'Style',
    'Forbid — what must NOT appear, added to the negative prompt. The pipeline already '
    'forbids people, text and second creatures on every creature render; this is for the '
    'ones specific to yours.',
    '<circle cx="12" cy="12" r="8.4"/><path d="M6.2 17.8L17.8 6.2"/>',
    [s('v', 'Never show', '', 'e.g. hooves, feathers')],
    fn=lambda p, x: '',
    neg='{v}',
)
