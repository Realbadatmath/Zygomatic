# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""movement_studio.params — the assembled RACKS/ACTIONS spec and the
defaults()/sanitize()/nondefault() dial-state helpers."""

from zyg_workflows.movement_studio.racks_bar_language import _RACKS_BAR_LANGUAGE
from zyg_workflows.movement_studio.racks_bar_motion import _RACKS_BAR_MOTION
from zyg_workflows.movement_studio.racks_rail import _RACKS_RAIL

RACKS = _RACKS_BAR_MOTION + _RACKS_BAR_LANGUAGE + _RACKS_RAIL


# Standalone action icons the GUI puts in the bars alongside the parameters.
# Not parameters — the client wires each to its own handler.
ACTIONS = [
    {
        'id': 'inject',
        'label': 'Inject subject',
        'lb': 'Inject',
        'icon': 'mv-inject',
        'place': 'bar',
        'hint': 'Pick a character, creature or object to move.',
    },
    {
        'id': 'prompt',
        'label': 'Preview the prompt',
        'lb': 'Preview',
        'icon': 'mv-preview',
        'place': 'bar',
        'hint': 'The exact motion sentence these dials produce, before spending a render on it.',
    },
    {
        'id': 'probe',
        'label': 'Probe render',
        'icon': 'mv-probe',
        'place': 'bar',
        'hint': 'Same dials, 33 frames — check the motion before paying for the full clip.',
    },
    {
        'id': 'render',
        'label': 'Render',
        'icon': 'mv-play',
        'place': 'bar',
        'hint': 'Start the render at the chosen length.',
    },
    {
        'id': 'stop',
        'label': 'Stop',
        'icon': 'mv-stop',
        'place': 'bar',
        'hint': 'Write the ABORT file the render watchdog polls.',
    },
    {
        'id': 'library',
        'label': 'Movement library',
        'lb': 'Library',
        'icon': 'mv-library',
        'place': 'rail',
        'hint': 'Every clip rendered here, newest first — load one back to modify it.',
    },
    {
        'id': 'recall',
        'label': "Recall this clip's dials",
        'lb': 'Recall',
        'icon': 'mv-recall',
        'place': 'rail',
        'hint': 'Put the settings a finished clip was rendered with back on the bars.',
    },
    {
        'id': 'preset_save',
        'label': 'Save preset',
        'icon': 'mv-save',
        'place': 'rail',
        'hint': 'Store the whole dial state under a name.',
    },
    {
        'id': 'preset_load',
        'label': 'Load preset',
        'icon': 'mv-open',
        'place': 'rail',
        'hint': 'Recall a saved dial state.',
    },
    {
        'id': 'dice',
        'label': 'Roll the seed',
        'lb': 'Seed',
        'icon': 'mv-dice',
        'place': 'rail',
        'hint': 'New random seed — the take hunt.',
    },
    {
        'id': 'recipe',
        'label': 'Recipe',
        'icon': 'mv-recipe',
        'place': 'rail',
        'hint': 'The non-default dials as JSON, and the exact kwargs the render will use.',
    },
    {
        'id': 'plate',
        'label': 'Plate check',
        'lb': 'Plate',
        'icon': 'mv-plates',
        'place': 'rail',
        'hint': 'The control map the PROP PLATES rack would paint in, and where — read '
        "off the asset's manifest, not rendered. Says why there is no plate "
        'when there is none.',
    },
    {
        'id': 'track',
        'label': 'Extract track from driver clip',
        'lb': 'Track',
        'icon': 'mv-track',
        'place': 'rail',
        'hint': 'Ask for a subject description ("the young man in the red coat" — the phrase '
        'SAM 3 segments, and the only reason masks exist), then run geom.pose_track '
        'over the Driver clip, rasterise the track into VACE control plates with '
        'geom.track_plates, and fill Control frames with the composite plate folder '
        'and Mask frames with the tracked masks. Starts a background job and polls '
        'it, so the page can be left alone while it runs.',
    },
    {
        'id': 'reset',
        'label': 'Reset all',
        'icon': 'mv-reset',
        'place': 'rail',
        'hint': 'Return every option to its default.',
    },
    {
        'id': 'log',
        'label': 'Render log',
        'icon': 'mv-log',
        'place': 'rail',
        'hint': 'The live log of the running or last render.',
    },
]

_PARAMS = {p['key']: p for r in RACKS for p in r['params']}


def defaults() -> dict:
    return {k: p['def'] for k, p in _PARAMS.items()}


def sanitize(params: dict) -> dict:
    """Clamp/coerce a caller-supplied dict onto the spec — unknown keys dropped,
    missing keys take their default. Same contract as video_studio.sanitize().

    Select membership is compared as STRINGS: an HTML <select> posts its value
    as text, so a numeric option ('65') would otherwise never match its own
    entry and would silently fall back to the default."""
    out = defaults()
    for k, v in (params or {}).items():
        spec = _PARAMS.get(k)
        if not spec:
            continue
        t = spec['type']
        try:
            if t == 'select':
                match = next((o['v'] for o in spec['options'] if str(o['v']) == str(v)), None)
                out[k] = spec['def'] if match is None else match
            elif t == 'toggle':
                out[k] = bool(v) if not isinstance(v, str) else v.strip().lower() not in ('0', 'false', 'no', 'off', '')
            elif t == 'int':
                out[k] = int(max(spec['min'], min(spec['max'], int(float(v)))))
            elif t == 'text':
                out[k] = str(v or '')[:1200]
            else:
                out[k] = float(max(spec['min'], min(spec['max'], float(v))))
        except (TypeError, ValueError):
            out[k] = spec['def']
    return out


def nondefault(params: dict) -> dict:
    """Only the keys a caller moved off their default — what the GUI marks with a
    dot on the icon, and the only part of a dial state worth storing or logging.
    With this many icons the dot is the only way to see what you actually changed."""
    d = defaults()
    return {k: v for k, v in (params or {}).items() if k in d and str(v) != str(d[k])}
