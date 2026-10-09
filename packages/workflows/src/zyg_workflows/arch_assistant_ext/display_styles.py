# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""display_styles — the assistant half of the Display-styles icon family.

Six switches in the tab's Display group, all pressable by the model through
view_scene_ops.press_button (the JS registrations carry ``assist: 1``):

    d_tex      textures on/off
    d_shaded   solid faces, materials off (neutral grey)
    d_mono     white model
    d_hidden   hidden line — the drafting view
    d_edges    edge outlines, weight 1-3
    d_sketchy  hand-drawn wobble on the outlines

No kinds, no geometry and no server-side twin: the styles are a property of the
VIEW, not of the drawing's objects, and the only place a view exists is the
tab. What they leave behind IS in the document — ``doc.ext.display_styles`` —
so a saved drawing opens in the style it was saved in, and the assistant reads
that back with the rest of ``d.ext``.

Standard library only.
"""

KINDS: dict = {}
OPENINGS: list = []

BUTTONS = ['d_tex', 'd_shaded', 'd_mono', 'd_hidden', 'd_edges', 'd_sketchy']

PROMPT = (
    'Display styles (how the model is DRAWN, not what it is made of; saved in doc.ext.display_styles). Each is a '
    'switch taking {"on": true|false}: "d_tex" off drops the photographs for preset colours; "d_shaded" is '
    'neutral grey, "d_mono" the white-model view, "d_hidden" the drafting view — those three are mutually '
    'exclusive and texture-less. Independently "d_edges" {"weight": 1|2|3} outlines every solid and "d_sketchy" '
    'adds a hand-drawn wobble. explain("display styles") has the detail.'
)

TOOLS: list = []

EXAMPLES = [
    {
        'ask': 'show me the white model, no textures',
        'calls': [{'tool': 'press_button', 'args': {'id': 'd_mono', 'args': {'on': True}}}],
    },
    {
        'ask': 'make it look like a hand sketch with heavy outlines',
        'calls': [
            {'tool': 'press_button', 'args': {'id': 'd_edges', 'args': {'on': True, 'weight': 3}}},
            {'tool': 'press_button', 'args': {'id': 'd_sketchy', 'args': {'on': True}}},
        ],
    },
    {
        'ask': 'give me the drafting view',
        'calls': [{'tool': 'press_button', 'args': {'id': 'd_hidden', 'args': {'on': True}}}],
    },
    {
        'ask': 'put the textures back',
        'calls': [{'tool': 'press_button', 'args': {'id': 'd_tex', 'args': {'on': True}}}],
    },
]
