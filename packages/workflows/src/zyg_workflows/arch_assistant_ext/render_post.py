# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""render_post — the assistant half of the Render ▸ post-processing icons.

No kinds and no records: every icon here changes how the viewport is DRAWN, not
what the drawing IS. The model presses them through view_scene_ops.press_button;
the tab accepts the press only because arch_ext/render_post.js registers each id
with `assist: 1`.

Six icons: r_preset (quality preset), r_ao (ambient occlusion), r_bloom,
r_dof (depth of field), r_aa (anti-alias) and r_res (output resolution).

Licences: the passes the JS loads are three.js r144 examples (MIT), vendored in
vendor/three/. Nothing new on the Python side.
"""

from __future__ import annotations

KINDS: dict = {}
OPENINGS: list = []

BUTTONS = ['r_preset', 'r_ao', 'r_bloom', 'r_dof', 'r_aa', 'r_res']

PRESETS = ('draft', 'presentation', 'print')
SCALES = (0.5, 0.75, 1, 1.5, 2)

PROMPT = (
    'Render quality (post-processing, viewport + snapshots — no records change): '
    'press_button("r_preset", {"preset": "draft"|"presentation"|"print"}) sets occlusion, bloom, '
    'depth of field, anti-alias, output resolution and shadows in one go (no args = cycle to the next '
    'preset; draft is everything off at 0.75x with shadows off, presentation is occlusion + anti-alias '
    '+ low bloom at 1x with 2048 shadows, print is occlusion + anti-alias at 2x with 4096 shadows). '
    'The four switches take {"on": true|false} (no args = flip): press_button("r_ao", {"on": true}) '
    'ambient occlusion, press_button("r_bloom", {"on": true}) bloom, press_button("r_dof", {"on": true}) '
    'depth of field focused on the selection (or on what the camera is looking at), '
    'press_button("r_aa", {"on": true}) SMAA anti-aliasing. '
    'press_button("r_res", {"scale": 0.5|0.75|1|1.5|2}) sets the render resolution as a multiple of the '
    'viewport pixels — use it before f_shot when someone asks for a big picture. '
    'Pressing any of the four switches or r_res by hand drops the preset to "custom". '
    'With every effect off the studio goes back to its plain, fast render path.'
)

TOOLS: list = []

EXAMPLES = [
    {
        'ask': 'make this look like a presentation render',
        'calls': [{'tool': 'press_button', 'args': {'id': 'r_preset', 'args': {'preset': 'presentation'}}}],
    },
    {
        'ask': 'turn on ambient occlusion',
        'calls': [{'tool': 'press_button', 'args': {'id': 'r_ao', 'args': {'on': True}}}],
    },
    {
        'ask': 'give me a print-quality snapshot of the whole model',
        'calls': [
            {'tool': 'press_button', 'args': {'id': 'r_preset', 'args': {'preset': 'print'}}},
            {'tool': 'press_button', 'args': {'id': 'v_selfit'}},
            {'tool': 'press_button', 'args': {'id': 'f_shot'}},
        ],
    },
    {
        'ask': 'blur the background behind what I have selected',
        'calls': [{'tool': 'press_button', 'args': {'id': 'r_dof', 'args': {'on': True}}}],
    },
    {
        'ask': 'render at double resolution',
        'calls': [{'tool': 'press_button', 'args': {'id': 'r_res', 'args': {'scale': 2}}}],
    },
    {
        'ask': 'the viewport is crawling, drop the quality',
        'calls': [{'tool': 'press_button', 'args': {'id': 'r_preset', 'args': {'preset': 'draft'}}}],
    },
]
