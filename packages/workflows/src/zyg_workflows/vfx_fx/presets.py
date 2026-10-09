# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Presets and the payload the page renders its rails from (vfx_fx.py lines 3626-3853)."""

from __future__ import annotations

import json
import os
import time

from zyg_workflows.vfx_fx.constants import (
    _zyg_log,
    PRESETS,
    LUTDIR,
    FFMPEG,
)
from zyg_workflows.vfx_fx.registry import (
    OPS,
)
from zyg_workflows.vfx_fx.chain import (
    normalise_stack,
    VIEWS,
    SCOPES,
)
from zyg_workflows.vfx_fx.render import (
    FORMATS,
    _slug,
)

# ── presets ─────────────────────────────────────────────────────────────────
# A preset is the RECIPE, not the picture: it names ops and parameters, so it
# applies to any element.  The built-ins are here rather than in a data file
# because they are documentation -- each one is a worked example of what a
# section of the rail is actually for, and they are the answer to "where do I
# start" on an element you have never used before.
BUILTIN_PRESETS = [
    {
        'id': 'b_black_key',
        'lb': 'Key off black',
        'builtin': True,
        'note': 'The one every fire, explosion and spark plate shot on black needs: '
        'luma key, blur the matte a hair, choke it back in, unpremultiply.',
        'stack': [
            {'op': 'lumakey', 'p': {'threshold': 0.04, 'tolerance': 0.14, 'softness': 0.25}},
            {'op': 'mblur', 'p': {'sigma': 1.4}},
            {'op': 'mchoke', 'p': {'amount': -1}},
            {'op': 'unpremul', 'p': {}},
        ],
    },
    {
        'id': 'b_green_key',
        'lb': 'Green screen',
        'builtin': True,
        'note': 'Chroma key, despill, choke and soften — in that order, because '
        'despilling after a choke leaves the spill on the pixels you kept.',
        'stack': [
            {'op': 'chromakey', 'p': {'color': '#00b140', 'similarity': 0.18, 'blend': 0.06}},
            {'op': 'despill', 'p': {'type': 'green', 'mix': 0.55, 'expand': 0.2}},
            {'op': 'mchoke', 'p': {'amount': -1}},
            {'op': 'mblur', 'p': {'sigma': 1.0}},
        ],
    },
    {
        'id': 'b_warm_fire',
        'lb': 'Hotter fire',
        'builtin': True,
        'note': 'Push an orange element hotter without clipping it: exposure up, '
        'temperature down, vibrance rather than saturation, then bloom.',
        'stack': [
            {'op': 'exposure', 'p': {'e': 0.45}},
            {'op': 'temp', 'p': {'temperature': 4200, 'mix': 0.7, 'pl': 1}},
            {'op': 'vibrance', 'p': {'intensity': 0.55}},
            {'op': 'glow', 'p': {'thr': 0.62, 'sigma': 22, 'amount': 0.7}},
        ],
    },
    {
        'id': 'b_blue_plasma',
        'lb': 'Blue plasma',
        'builtin': True,
        'note': 'The recolour that turns a fire element into an energy one — hue '
        'range first so the smoke around it does not come with.',
        'stack': [
            {
                'op': 'huesat',
                'p': {
                    'h': 150,
                    's': 0.25,
                    'strength': 3,
                    'r': True,
                    'y': True,
                    'g': False,
                    'cy': False,
                    'bl': False,
                    'm': False,
                },
            },
            {'op': 'glow', 'p': {'thr': 0.5, 'sigma': 30, 'amount': 0.85}},
            {'op': 'streak', 'p': {'thr': 0.7, 'angle': 0, 'length': 60, 'amount': 0.45}},
        ],
    },
    {
        'id': 'b_smoke_dirty',
        'lb': 'Dirty the smoke',
        'builtin': True,
        'note': 'Grey CG smoke into something kicked up off a real floor: tint it '
        'the colour of the ground, drop the contrast, add grain.',
        'stack': [
            {'op': 'colorize', 'p': {'hue': 32, 'saturation': 0.28, 'lightness': 0.5, 'mix': 0.55}},
            {'op': 'bc', 'p': {'contrast': 0.88, 'brightness': -0.03}},
            {'op': 'noise', 'p': {'alls': 10, 't': True}},
        ],
    },
    {
        'id': 'b_plate_match',
        'lb': 'Match to a plate',
        'builtin': True,
        'note': 'The four moves that marry a clean element to real footage: soften '
        "it to the plate's detail, add its grain, its lens fringing and its "
        'vignette. Nothing here is a look — it is all camouflage.',
        'stack': [
            {'op': 'unsharp', 'p': {'la': -0.35}},
            {'op': 'noise', 'p': {'alls': 9, 't': True}},
            {'op': 'chromab', 'p': {'rh': 1, 'bh': -1}},
            {'op': 'vignette', 'p': {'angle': 0.35}},
        ],
    },
    {
        'id': 'b_film',
        'lb': 'Film emulation',
        'builtin': True,
        'note': 'S-curve, halation, grain, gate vignette — the four things that '
        'separate film from a clean digital render.',
        'stack': [{'op': 'filmlook', 'p': {}}, {'op': 'halation', 'p': {'thr': 0.7, 'sigma': 20, 'amount': 0.45}}],
    },
    {
        'id': 'b_seamless',
        'lb': 'Seamless tile',
        'builtin': True,
        'note': 'Mirror-quad then tile: the result repeats without a visible seam '
        'by construction, which is the only reliable way to get one.',
        'stack': [{'op': 'kaleido', 'p': {'quad': 'tl'}}, {'op': 'tileop', 'p': {'nx': 2, 'ny': 2}}],
    },
    {
        'id': 'b_heat',
        'lb': 'Heat haze',
        'builtin': True,
        'note': 'Turbulence at a large scale and a small amount. Over-driven this '
        'reads as underwater; the trick is that it should be almost '
        'invisible until you A/B it.',
        'stack': [{'op': 'turb', 'p': {'amount': 12, 'scale': 26}}],
    },
    {
        'id': 'b_slowmo',
        'lb': 'Slow motion',
        'builtin': True,
        'note': 'Half speed with the in-between frames INVENTED rather than '
        'repeated. Check it on fast smoke before you trust it — flow '
        'tearing is what this fails at.',
        'stack': [{'op': 'oflow', 'p': {'fps': 60}}, {'op': 'speed', 'p': {'rate': 0.5, 'keepfps': True}}],
    },
    {
        'id': 'b_diag',
        'lb': 'Look for banding',
        'builtin': True,
        'note': 'A diagnostic, not a look: stretch the range hard so any banding, '
        'blocking or clipping in the source becomes impossible to miss.',
        'stack': [
            {
                'op': 'levels',
                'p': {'rimin': 0.35, 'gimin': 0.35, 'bimin': 0.35, 'rimax': 0.65, 'gimax': 0.65, 'bimax': 0.65},
            },
            {'op': 'pseudo', 'p': {'preset': 'turbo'}},
        ],
    },
]


def load_presets():
    user = []
    if os.path.exists(PRESETS):
        try:
            with open(PRESETS, encoding='utf-8') as fh:
                user = json.load(fh) or []
        except (OSError, ValueError):
            user = []
    return {'builtin': BUILTIN_PRESETS, 'user': user}


def save_preset(name, stack, note=''):
    name = str(name or '').strip()[:60]
    if not name:
        return {'ok': False, 'error': 'a preset needs a name'}
    st, dropped = normalise_stack(stack, 'video')
    if not st:
        return {'ok': False, 'error': 'nothing in the stack to save'}
    user = load_presets()['user']
    pid = 'u_' + _slug(name)
    row = {
        'id': pid,
        'lb': name,
        'note': str(note or '')[:400],
        'stack': [{'op': o['op'], 'p': o['p']} for o in st],
        'saved': int(time.time()),
    }
    user = [u for u in user if u.get('id') != pid] + [row]
    os.makedirs(os.path.dirname(PRESETS), exist_ok=True)
    tmp = PRESETS + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as fh:
        json.dump(user, fh, indent=1)
    os.replace(tmp, PRESETS)
    return {'ok': True, 'id': pid, 'dropped': dropped}


def delete_preset(pid):
    user = [u for u in load_presets()['user'] if u.get('id') != str(pid)]
    tmp = PRESETS + '.tmp'
    os.makedirs(os.path.dirname(PRESETS), exist_ok=True)
    with open(tmp, 'w', encoding='utf-8') as fh:
        json.dump(user, fh, indent=1)
    os.replace(tmp, PRESETS)
    return {'ok': True}


# ── the payload the page renders its rails from ─────────────────────────────
def ops_payload():
    """Everything the browser needs to draw and drive both bars.

    The page holds NO op list of its own -- this is the single source of truth
    for what exists, what it is called, what it does, what it looks like and
    what knobs it has.  Add an op above and it appears in the rail with its
    icon and its panel, without touching a line of the page."""
    secs, order = {}, []
    for o in OPS:
        key = (o['bar'], o['sec'])
        if key not in secs:
            secs[key] = []
            order.append(key)
        secs[key].append({k: v for k, v in o.items() if k != 'fn'})
    luts = []
    try:
        luts = sorted(f for f in os.listdir(LUTDIR) if f.lower().endswith(('.cube', '.3dl')))
    except OSError as _exc:
        _zyg_log.warning('LUT directory unreadable, offering no LUTs: %s', _exc)
    return {
        'sections': [{'bar': bar, 'sec': sec, 'items': secs[(bar, sec)]} for bar, sec in order],
        'formats': [{'k': k, **{kk: vv for kk, vv in v.items() if kk != 'args'}} for k, v in FORMATS.items()],
        'views': sorted(VIEWS),
        'scopes': sorted(SCOPES),
        'presets': load_presets(),
        'luts': luts,
        'counts': {
            'side': sum(1 for o in OPS if o['bar'] == 'side'),
            'dock': sum(1 for o in OPS if o['bar'] == 'dock'),
            'total': len(OPS),
        },
        'ffmpeg': FFMPEG,
    }
