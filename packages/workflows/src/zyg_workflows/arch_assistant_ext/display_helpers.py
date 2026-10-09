# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""display_helpers — the assistant half of the six Display icons.

No kinds and no drawing tools: this family only declares which icons of
arch_ext/display_helpers.js the model may press through
view_scene_ops.press_button, and says in one paragraph what arguments each of
them takes. The tab accepts a press only because the JS registration carries
`assist: 1` — both sides have to agree.

The settings themselves live in the DRAWING (AR.doc.ext.display_helpers), so
they survive a save, come back with the file, and are visible to the model in
the document it is handed.
"""

KINDS: dict = {}
OPENINGS: list = []

BUTTONS = ['d_bbox', 'd_ground', 'd_labels', 'd_colorby', 'd_transp', 'd_backface']

PROMPT = (
    'Display helpers (viewport only — none of these change the drawing): '
    'press_button("d_bbox", {"on": true|false}) draws a bounding box round every visible object '
    '(amber for the selection, grey for the rest); omit the argument to toggle. '
    'press_button("d_ground", {"on": true|false}) shows or hides the ground plane the shadows land on, '
    'and overrides the Shadows switch — off here stays off even with shadows on. '
    'press_button("d_labels", {"on": true|false}) writes each object\'s name over it in the viewport '
    '(the first 400 objects). '
    'press_button("d_colorby", {"by": "material"|"storey"|"kind"|"tag"|"off"}) recolours every object by '
    'that property with a legend bottom-left — "tag" reads meta.tags[0] and greys the untagged; no argument cycles. '
    'press_button("d_transp", {"mode": "fast"|"sorted"|"dithered"}) sets how glass sorts against what is behind it '
    '("sorted" is the honest look, "dithered" is an order-independent screen door). '
    'press_button("d_backface", {"mode": "double"|"cull"|"normals"}) is the inside-out test: "cull" makes '
    'reversed faces vanish, "normals" draws a cyan 0.3 m normal on every triangle of the SELECTION.'
)

TOOLS: list = []

EXAMPLES = [
    {
        'ask': 'show me the bounding boxes',
        'calls': [{'tool': 'press_button', 'args': {'id': 'd_bbox', 'args': {'on': True}}}],
    },
    {
        'ask': 'colour the model by storey',
        'calls': [{'tool': 'press_button', 'args': {'id': 'd_colorby', 'args': {'by': 'storey'}}}],
    },
    {
        'ask': 'the glass looks wrong through the window — fix the sorting',
        'calls': [{'tool': 'press_button', 'args': {'id': 'd_transp', 'args': {'mode': 'sorted'}}}],
    },
    {
        'ask': 'is that roof inside out?',
        'calls': [{'tool': 'press_button', 'args': {'id': 'd_backface', 'args': {'mode': 'cull'}}}],
    },
    {
        'ask': 'turn the ground plane off',
        'calls': [{'tool': 'press_button', 'args': {'id': 'd_ground', 'args': {'on': False}}}],
    },
    {
        'ask': 'label everything in the viewport',
        'calls': [{'tool': 'press_button', 'args': {'id': 'd_labels', 'args': {'on': True}}}],
    },
]
