# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""icon_probe — the assistant half of the ICON seam's worked example.

No kinds, no drawing tools: it declares which icons of arch_ext/icon_probe.js
the model may press through view_scene_ops.press_button (BUTTONS), and says so
in one prompt paragraph. The tab accepts the press only because the JS
registration carries `assist: 1` — both sides must agree.
"""

KINDS: dict = {}
OPENINGS: list = []
BUTTONS = ['s_last']
PROMPT = 'Selection history: press_button("s_last") restores the previous selection (press again to come forward).'
TOOLS: list = []
EXAMPLES = [
    {'ask': 'go back to what I had selected before', 'calls': [{'tool': 'press_button', 'args': {'id': 's_last'}}]}
]
