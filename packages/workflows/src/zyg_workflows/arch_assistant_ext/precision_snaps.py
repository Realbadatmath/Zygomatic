# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""precision_snaps — the assistant half of the object-snapping family.

No kinds and no drawing tools: the seven Precision icons wired by
arch_ext/precision_snaps.js are SWITCHES, so the model turns them on and off
through view_scene_ops.press_button. Each takes one argument, {"on": true|false};
pressed without arguments an icon toggles. The tab accepts the press only
because every registration carries `assist: 1` — both sides must agree.

Standard library only.
"""

KINDS: dict = {}
OPENINGS: list = []

BUTTONS = ['pr_end', 'pr_mid', 'pr_cen', 'pr_int', 'pr_perp', 'pr_tan', 'pr_near']

PROMPT = (
    'Precision object snaps (each an independent switch, any combination, persisted with the drawing): '
    'press_button("pr_end", {"on": true}) snaps clicks to endpoints (wall/beam ends, slab and roof corners), '
    '"pr_mid" to edge midpoints, "pr_cen" to centres (columns, circles, any object\'s centre), '
    '"pr_int" to where two wall or guide lines cross, "pr_perp" to the foot of the perpendicular from the '
    'first point of the current draft, "pr_tan" to the tangent points from that first point to a circle, and '
    '"pr_near" to the closest point on the nearest edge; pass {"on": false} to switch one off, or no args to '
    'toggle. They run after grid snap within 12 screen pixels of the pointer and resolve ties in the order '
    'endpoint > intersection > midpoint > centre > perpendicular > tangent > nearest.'
)

TOOLS: list = []

EXAMPLES = [
    {
        'ask': 'snap to the ends and corners of what is already drawn',
        'calls': [{'tool': 'press_button', 'args': {'id': 'pr_end', 'args': {'on': True}}}],
    },
    {
        'ask': 'turn on endpoint and midpoint snapping and switch the nearest-point snap off',
        'calls': [
            {'tool': 'press_button', 'args': {'id': 'pr_end', 'args': {'on': True}}},
            {'tool': 'press_button', 'args': {'id': 'pr_mid', 'args': {'on': True}}},
            {'tool': 'press_button', 'args': {'id': 'pr_near', 'args': {'on': False}}},
        ],
    },
    {
        'ask': 'I want the next wall to land exactly where those two guides cross',
        'calls': [{'tool': 'press_button', 'args': {'id': 'pr_int', 'args': {'on': True}}}],
    },
]
