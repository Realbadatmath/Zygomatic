# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""SIDE / CONDITION — the same creature at a different point in its life or its day.

Moved verbatim out of the old single-file creature_fx.py (lines 1832-2054).
"""

from __future__ import annotations

from zyg_workflows.creature_fx.base import _amt, _edit, b, e, f, i


# ══ SIDE · CONDITION ════════════════════════════════════════════════════════
# The same creature, at a different point in its life or its day. These are the
# edits that DO NOT change the body plan -- which is exactly why they are the
# safest ones to run on a trained creature.

_edit(
    'cn_age',
    'Age',
    'Condition',
    'Age — hatchling to ancient. Age moves proportions as well as surface (a juvenile '
    'has a bigger head on a smaller body), so it is one op rather than three.',
    '<path d="M4.6 19.4c0-4 3.4-7.2 7.4-7.2s7.4 3.2 7.4 7.2"/><circle cx="12" cy="7.4" r="3.6"/>'
    '<path d="M17.4 5.4l2.4-1.4M18.4 9.4l2.8.4"/>',
    [e('v', 'Age', 'adult', ['newborn', 'juvenile', 'adolescent', 'adult', 'old', 'ancient'])],
    fn=lambda p, x: (
        '' if p['v'] == 'adult' else f'make it {p["v"]}, with the proportions and surface that go with that age'
    ),
)

_edit(
    'cn_health',
    'Condition',
    'Condition',
    'Condition — thriving, gaunt, sick, starving. The body under the coat rather than the coat itself.',
    '<path d="M12 20.4l-6.6-6.6a4.4 4.4 0 016.6-5.8 4.4 4.4 0 016.6 5.8z"/>'
    '<path d="M4.6 12.4h3l1.4-2.4 2 4.6 1.6-3 1.2 1.8h5.6"/>',
    [
        e(
            'v',
            'Condition',
            'healthy',
            ['healthy and thriving', 'lean', 'gaunt', 'sickly', 'starving', 'overfed', 'freshly moulted'],
        )
    ],
    fn=lambda p, x: f'the creature looks {p["v"]}',
)

_edit(
    'cn_scar',
    'Scars',
    'Condition',
    'Scars — healed damage. Where and how many; a scar is a history the creature '
    'carries into every later render, so it goes on the anchor or nowhere.',
    '<path d="M8.4 3.6l7.2 16.8"/><path d="M6.6 8.4l4-2M9 13.4l4-2M11.4 18l4-2"/>',
    [
        i('n', 'Scars', 2, 0, 12, 1),
        e(
            'where',
            'Where',
            'the face',
            ['the face', 'the flank', 'across one eye', 'the shoulders', 'the muzzle', 'the legs'],
        ),
    ],
    fn=lambda p, x: '' if p['n'] == 0 else f'give it {p["n"]} healed scars on {p["where"]}',
)

_edit(
    'cn_wound',
    'Fresh wounds',
    'Condition',
    'Fresh wounds — open damage, in a stated intensity. Deliberately separate from '
    'scars, and dial-guarded: intensity here means "arresting", not gore '
    '([[project_documentary_intensity]]).',
    '<path d="M12 4.4c2 4 3.4 7 3.4 9.4a3.4 3.4 0 11-6.8 0c0-2.4 1.4-5.4 3.4-9.4z"/>'
    '<path d="M6.6 17.4l-2.4 2.6M17.4 17.4l2.4 2.6"/>',
    [
        e(
            'v',
            'Damage',
            'none',
            ['none', 'grazes', 'a bleeding cut', 'torn ear', 'a deep gash', 'battle damage across the body'],
        ),
        f('a', 'Intensity', 40, 0, 100, 1),
    ],
    fn=lambda p, x: (
        ''
        if p['v'] == 'none' or not _amt(p['a'])
        else f'show {_amt(p["a"], ("slight", "clear", "heavy", "severe"))} {p["v"]}'
    ),
)

_edit(
    'cn_dirt',
    'Dirt',
    'Condition',
    'Dirt — mud, dust, soot, sand. What the creature has been walking through, and the '
    'cheapest way to place it in a world without changing the background.',
    '<path d="M4.4 18.6c2-3 4.4-4 7.6-4s5.6 1 7.6 4z"/>'
    '<circle cx="8.4" cy="8.6" r="1.2"/><circle cx="13.4" cy="6.6" r="1"/>'
    '<circle cx="16.4" cy="10.4" r="1.4"/>',
    [e('kind', 'Kind', 'mud', ['mud', 'dust', 'soot', 'sand', 'ash', 'clay']), f('a', 'Amount', 50, 0, 100, 1)],
    fn=lambda p, x: (
        f'{_amt(p["a"], ("lightly", "visibly", "heavily", "completely"))} covered in {p["kind"]}'
        if _amt(p['a'])
        else ''
    ),
)

_edit(
    'cn_wet',
    'Wet',
    'Condition',
    'Wet — soaked fur clumps, water beading on scales, dripping. Changes the '
    'silhouette of a furred creature more than any grooming op.',
    '<path d="M8 3.6c2.4 3.4 3.6 5.8 3.6 7.4a3.6 3.6 0 11-7.2 0c0-1.6 1.2-4 3.6-7.4z"/>'
    '<path d="M16.4 10.4c1.6 2.4 2.4 4 2.4 5a2.4 2.4 0 11-4.8 0c0-1 .8-2.6 2.4-5z"/>',
    [f('a', 'Wetness', 60, 0, 100, 1), b('drip', 'Dripping', False)],
    fn=lambda p, x: (
        (
            f'{_amt(p["a"], ("damp", "wet", "soaked", "drenched"))}, '
            f'with the coat clumped and water on the surface' + (', water dripping off it' if p['drip'] else '')
        )
        if _amt(p['a'])
        else ''
    ),
)

_edit(
    'cn_frost',
    'Frost',
    'Condition',
    'Frost and snow — ice on the coat, snow on the back, breath in the air. A weather '
    'op that lives on the creature rather than in the scene.',
    '<path d="M12 3.6v16.8M4.6 7.8l14.8 8.4M19.4 7.8L4.6 16.2"/>'
    '<path d="M12 7.4l-2 2M12 7.4l2 2M12 16.6l-2-2M12 16.6l2-2"/>',
    [f('a', 'Amount', 50, 0, 100, 1), b('breath', 'Visible breath', True)],
    fn=lambda p, x: (
        (
            f'{_amt(p["a"])} frosted, with ice in the coat and snow on its back'
            + (', breath steaming in the cold air' if p['breath'] else '')
        )
        if _amt(p['a'])
        else ''
    ),
)

_edit(
    'cn_moult',
    'Moulting',
    'Condition',
    'Moulting — a coat half shed, scales peeling, feathers in pin. The transitional '
    'state, which is where a creature looks most alive and least like a toy.',
    '<path d="M6.6 20.4c-1.4-4 0-8.4 3.4-11.4"/><path d="M17.4 3.6c1.4 4 0 8.4-3.4 11.4"/>'
    '<path d="M4.6 12.6l3.4 1M19.4 11.4l-3.4-1"/>',
    [f('a', 'How far along', 50, 0, 100, 1)],
    fn=lambda p, x: f'{_amt(p["a"])} mid-moult, the old coat shedding in patches' if _amt(p['a']) else '',
)

_edit(
    'cn_muscle',
    'Musculature',
    'Condition',
    'Musculature — how much of the body reads as muscle under the surface. Separate '
    'from bulk: a creature can be heavy and soft or light and corded.',
    '<path d="M5.4 14.4c2-4 4.4-6 7-6 3.4 0 5.4 2.4 6.2 6"/>'
    '<path d="M7.6 19.4c1.4-2 2.8-3 4.4-3s3 1 4.4 3"/><path d="M12 8.4V4.6"/>',
    [f('v', 'Defined / soft', 30, -100, 100, 1)],
    fn=lambda p, x: (
        f'make it {_amt(p["v"])} '
        f'{"more muscular, with defined muscle under the surface" if p["v"] > 0 else "softer, with no visible muscle definition"}'
        if _amt(p['v'])
        else ''
    ),
)

_edit(
    'cn_grav',
    'Gravid',
    'Condition',
    'Gravid — carrying eggs or young. A body-shape change with a story attached, and one a brief almost never covers.',
    '<ellipse cx="12" cy="13.6" rx="6.4" ry="6"/><circle cx="12" cy="5.4" r="2.4"/><circle cx="12" cy="13.6" r="2.4"/>',
    [b('on', 'Gravid', True), f('a', 'How far along', 60, 0, 100, 1)],
    fn=lambda p, x: f'the creature is {_amt(p["a"])} gravid, its belly swollen' if p['on'] and _amt(p['a']) else '',
)

_edit(
    'cn_missing',
    'Missing part',
    'Condition',
    'Missing part — a lost limb, ear or eye, healed over. The hardest edit to keep '
    'stable across a sheet, because every rotation wants to put it back.',
    '<circle cx="12" cy="12" r="8.4" stroke-dasharray="3 3"/><path d="M8.4 8.4l7.2 7.2M15.6 8.4l-7.2 7.2"/>',
    [
        e('v', 'Missing', 'none', ['none', 'one ear', 'one eye', 'part of the tail', 'one front limb', 'several toes']),
        b('healed', 'Long healed', True),
    ],
    fn=lambda p, x: (
        ''
        if p['v'] == 'none'
        else f'the creature is missing {p["v"]}' + (', long healed over' if p['healed'] else ', recently lost')
    ),
)

_edit(
    'cn_mood',
    'Mood',
    'Condition',
    'Mood — the read, not the muscles. Expression sets the face; this sets the whole '
    'body, the ears, the tail and the light together.',
    '<circle cx="12" cy="12" r="8.6"/><path d="M8 15c2.4 2 5.6 2 8 0"/><path d="M7.6 9.6l2.4-1.4M16.4 9.6L14 8.2"/>',
    [
        e(
            'v',
            'Mood',
            'neutral',
            [
                'neutral',
                'calm',
                'playful',
                'wary',
                'aggressive',
                'frightened',
                'proud',
                'exhausted',
                'menacing',
                'gentle',
            ],
        )
    ],
    fn=lambda p, x: '' if p['v'] == 'neutral' else f'the whole animal reads as {p["v"]}',
)
