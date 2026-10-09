# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""ACTIONS — the standalone action icons the GUI puts in the bars.

Moved verbatim (lines 3728-3798 of the old single-file spec.py).
"""

# Standalone action icons the GUI puts in the bars alongside the parameters.
# These are not parameters — the client wires each to its own handler.
ACTIONS = [
    {
        'id': 'inject',
        'label': 'Inject source clip',
        'icon': 'ic-inject',
        'place': 'rail',
        'hint': 'Pick an existing rendered clip. Its frame seeds this render.',
    },
    {
        'id': 'prompt',
        'label': 'Preview built prompt',
        'icon': 'ic-eye',
        'place': 'rail',
        'hint': 'Show the exact positive and negative prompt these settings produce, before spending a render on them.',
    },
    {
        'id': 'render',
        'label': 'Render',
        'icon': 'ic-play',
        'place': 'rail',
        'hint': 'Start the render with the current settings.',
    },
    {
        'id': 'vfx_draft',
        'label': 'VFX draft (seconds)',
        'icon': 'ic-bolt',
        'place': 'bar',
        'hint': 'Composite the VFX place rack onto the clip on screen at 320p and '
        'show it. Same camera solve and same filtergraph the render bakes '
        'at full quality, so where it lands here is where it lands there.',
    },
    {
        'id': 'assemble',
        'label': 'Assemble shots',
        'icon': 'ic-assemble',
        'place': 'bar',
        'hint': 'Cut the SHOTS shot list together into one mp4 — conform, trims, '
        'speed ramps, crossfades, top-and-tail fades, and the AUDIO rack '
        'under it. Its own job, separate from a render.',
    },
    {
        'id': 'preset_save',
        'label': 'Save preset',
        'icon': 'ic-save',
        'place': 'bar',
        'hint': 'Store the whole dial state under a name.',
    },
    {
        'id': 'preset_load',
        'label': 'Load preset',
        'icon': 'ic-folder',
        'place': 'bar',
        'hint': 'Recall a saved dial state.',
    },
    {
        'id': 'reset',
        'label': 'Reset all',
        'icon': 'ic-reset',
        'place': 'bar',
        'hint': 'Return every option to its default.',
    },
    {
        'id': 'history',
        'label': 'Render history',
        'icon': 'ic-history',
        'place': 'bar',
        'hint': 'Recent jobs from this session, with the settings each one used.',
    },
]
