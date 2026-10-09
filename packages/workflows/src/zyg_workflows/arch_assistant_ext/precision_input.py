# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""precision_input — the assistant half of the Precision icons (2026-09-07).

Five dock icons of the Precision group, wired for real in
``arch_ext/precision_input.js``: angle snap, axis lock, work plane, "type it"
and guides. There are no new kinds and no server work, so this file only
declares which icons the model may press and what arguments each one takes;
every registration in the JS carries ``assist: 1``, which is the other half of
that agreement.

No TOOLS twin: none of these icons produces a report the model would read — they
change how the NEXT drawing action lands, and the model already draws through
the ordinary drawing tools. The one exception worth knowing is press_button
("pr_coord", {"len": ..., "angle": ...}), which finishes a run that is already
open in the tab; the model cannot open one, so it is there for a person's draft.
"""

KINDS: dict = {}
OPENINGS: list = []
BUTTONS = ['pr_angle', 'pr_axis', 'pr_plane', 'pr_coord', 'pr_guide']
PROMPT = (
    'Precision input: press_button("pr_angle", {"deg": 45}) sets the angle-snap increment — '
    'wall/line/beam runs round their direction to it and a rotate drag lands on it '
    '(deg 0 turns drafting snap off, 15 is the studio default). '
    'press_button("pr_axis", {"axis": "x"|"z"|"y"|"off"}) locks the next draft and the next '
    'move drag to one axis; pressing with no args cycles off→x→z→y. '
    'press_button("pr_plane", {"rec": "<object id>", "face": "top"}) moves the drawing plane '
    "onto that object's top face so the next thing drawn sits on it; with no args and nothing "
    'selected it arms a click-to-pick mode, and pressing it again returns the plane to the ground. '
    'press_button("pr_coord", {"len": 5, "angle": 90}) finishes a run the person has open at an '
    'exact length and angle (0° = +X, 90° = −Z), or {"x": .., "z": ..} for an exact point. '
    'press_button("pr_guide", {"mode": "show"|"hide"|"clear"}) shows, hides or deletes every '
    'guide line and circle in the drawing.'
)
TOOLS: list = []
EXAMPLES = [
    {
        'ask': 'snap angles to 45 degrees',
        'calls': [{'tool': 'press_button', 'args': {'id': 'pr_angle', 'args': {'deg': 45}}}],
    },
    {
        'ask': 'lock the next move to the X axis',
        'calls': [{'tool': 'press_button', 'args': {'id': 'pr_axis', 'args': {'axis': 'x'}}}],
    },
    {
        'ask': 'draw on top of the slab instead of the ground',
        'calls': [{'tool': 'press_button', 'args': {'id': 'pr_plane', 'args': {'rec': 'o12', 'face': 'top'}}}],
    },
    {
        'ask': 'hide the guides',
        'calls': [{'tool': 'press_button', 'args': {'id': 'pr_guide', 'args': {'mode': 'hide'}}}],
    },
]
