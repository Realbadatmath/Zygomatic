# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""SIDE / GEAR — worn, not grown: everything that can come off between shots.

Moved verbatim out of the old single-file creature_fx.py (lines 2055-2242).
"""

from __future__ import annotations

from zyg_workflows.creature_fx.base import _edit, _pick, b, e, s


# ══ SIDE · GEAR ═════════════════════════════════════════════════════════════
# Worn, not grown. Everything here can come off between shots, which is exactly
# why it is not in Surface: a saddle in the anchor trains a creature that always
# has a saddle.

_edit(
    'cg_collar',
    'Collar',
    'Gear',
    "Collar — the domestication signal. One band changes a wild animal into somebody's "
    'animal, which is a story decision more than a design one.',
    '<ellipse cx="12" cy="10.4" rx="7" ry="3.4"/><path d="M12 13.8v3.4"/><circle cx="12" cy="18.6" r="1.8"/>',
    [
        e(
            'v',
            'Collar',
            'none',
            [
                'none',
                'a plain leather collar',
                'a studded collar',
                'a rope collar',
                'a metal band',
                'a collar with a tag',
                'a bell collar',
            ],
        )
    ],
    fn=lambda p, x: '' if p['v'] == 'none' else f'it wears {p["v"]}',
)

_edit(
    'cg_harness',
    'Harness',
    'Gear',
    "Harness — straps over the body: a working animal's kit. Sits across the surface "
    'ops, so it goes late in the stack.',
    '<path d="M8 4.6v14.8M16 4.6v14.8"/><path d="M8 9.4h8M8 14.6h8"/><circle cx="12" cy="9.4" r="1.4"/>',
    [
        e(
            'v',
            'Harness',
            'none',
            ['none', 'a leather harness', 'a rope harness', 'a buckled chest harness', 'a war harness with rings'],
        )
    ],
    fn=lambda p, x: '' if p['v'] == 'none' else f'fit it with {p["v"]}',
)

_edit(
    'cg_saddle',
    'Saddle',
    'Gear',
    'Saddle — a mount point, which implies a rider even when there is not one. Says '
    'nobody is on it unless you ask, because a rider is a second subject and the judge '
    'fails cells with two.',
    '<path d="M5.4 13.4c2.4-2.4 11-2.4 13.2 0l-1.6 4.4H7z"/><path d="M8.4 17.8v2.6M15.6 17.8v2.6"/>',
    [
        e(
            'v',
            'Saddle',
            'none',
            ['none', 'a simple saddle', 'a howdah', 'a saddle and stirrups', 'a saddle with packs'],
        ),
        b('empty', 'No rider', True),
    ],
    fn=lambda p, x: '' if p['v'] == 'none' else f'fit it with {p["v"]}' + (', with no rider' if p['empty'] else ''),
    neg='rider, person on the creature',
)

_edit(
    'cg_armour',
    'Worn armour',
    'Gear',
    'Worn armour — barding, plates strapped on, a chamfron. Distinct from the Plating '
    'surface op: this is metal on top of the animal, not part of it.',
    '<path d="M12 3.4l7 2.6v5.6c0 4.6-3 8-7 9.4-4-1.4-7-4.8-7-9.4V6z"/><path d="M12 6.4v12"/>',
    [
        e(
            'v',
            'Armour',
            'none',
            ['none', 'leather barding', 'plate barding', 'a chamfron', 'chainmail', 'scale barding'],
        ),
        s('col', 'Finish', 'blackened steel', pat=r"[A-Za-z ,'-]{0,50}"),
    ],
    fn=lambda p, x: '' if p['v'] == 'none' else f'fit it with {p["col"]} {p["v"]}',
)

_edit(
    'cg_jewel',
    'Jewellery',
    'Gear',
    'Jewellery — rings, chains, hung charms, horn caps. Small, bright and reflective, '
    'which makes it the gear most likely to be lost at cell resolution.',
    '<circle cx="12" cy="8.4" r="3.4"/><path d="M9.4 11.4l-1.6 8.4M14.6 11.4l1.6 8.4"/>'
    '<circle cx="8" cy="20.4" r="1.2"/><circle cx="16" cy="20.4" r="1.2"/>',
    [s('v', 'Jewellery', 'gold rings on the horns', pat=r"[A-Za-z0-9 ,'-]{0,90}")],
    fn=lambda p, x: f'it wears {p["v"]}' if _pick(p) else '',
)

_edit(
    'cg_bandage',
    'Bandage',
    'Gear',
    'Bandage — care, applied by someone. Pairs with Fresh wounds to say the creature '
    'is being looked after rather than just hurt.',
    '<path d="M5.4 12l6.6-6.6a4.6 4.6 0 016.6 6.6L12 18.6A4.6 4.6 0 015.4 12z"/><path d="M9 9l6 6M9 15l6-6"/>',
    [e('where', 'On', 'one leg', ['one leg', 'the head', 'the torso', 'the tail', 'one eye'])],
    fn=lambda p, x: f'a clean bandage wrapped around {p["where"]}',
)

_edit(
    'cg_pack',
    'Pack',
    'Gear',
    'Pack — bags, bedrolls, panniers. A creature carrying cargo reads as travelling, '
    'which is a whole scene implied by one prop.',
    '<rect x="6.4" y="8.4" width="11.2" height="9.2" rx="1.8"/>'
    '<path d="M9.4 8.4V6.6a2.6 2.6 0 015.2 0v1.8M6.4 12.4h11.2"/>',
    [
        e(
            'v',
            'Cargo',
            'saddlebags',
            ['saddlebags', 'a bedroll', 'panniers', 'crates', 'a woven basket', 'rolled canvas'],
        )
    ],
    fn=lambda p, x: f'it carries {p["v"]}',
)

_edit(
    'cg_rope',
    'Restraint',
    'Gear',
    'Restraint — rope, chain, a muzzle. The narrative op: a restrained creature is a scene, not a design.',
    '<path d="M4.4 12a3.4 3.4 0 016.8 0 3.4 3.4 0 006.8 0"/>'
    '<circle cx="7.8" cy="12" r="3.4"/><circle cx="16.2" cy="12" r="3.4"/>',
    [
        e(
            'v',
            'Restraint',
            'none',
            [
                'none',
                'a rope around the neck',
                'heavy chains',
                'a muzzle',
                'shackled legs',
                'a broken chain still attached',
            ],
        )
    ],
    fn=lambda p, x: '' if p['v'] == 'none' else f'it is fitted with {p["v"]}',
)

_edit(
    'cg_paint',
    'Markings applied',
    'Gear',
    'Applied markings — warpaint, dye, a brand, a sigil. Colour that somebody PUT on '
    'the creature, which reads completely differently from a natural pattern.',
    '<path d="M6.4 20.4c-1.6-1.6-1.6-4 0-5.6l8.4-8.4a2.4 2.4 0 013.4 3.4l-8.4 8.4z"/>'
    '<path d="M4.4 20.4h4"/><path d="M14 6.4l3.6 3.6"/>',
    [
        e(
            'kind',
            'Kind',
            'warpaint',
            ['warpaint', 'dyed patterns', 'a brand', 'a painted sigil', 'handprints', 'ritual stripes'],
        ),
        s('col', 'Colour', 'white', pat=r"[A-Za-z ,'-]{0,40}"),
    ],
    fn=lambda p, x: f'{p["col"]} {p["kind"]} applied to its hide',
)

_edit(
    'cg_free',
    'Other gear',
    'Gear',
    'Other gear — the free slot, written as a sentence, for everything an option list '
    'cannot hold. It goes into the instruction verbatim.',
    '<path d="M3.6 12h4.8M15.6 12h4.8"/><circle cx="12" cy="12" r="3.6"/><path d="M12 3.6v4.8M12 15.6v4.8"/>',
    [s('v', 'Gear', '', 'e.g. a lantern hung from one horn')],
    fn=lambda p, x: f'it has {p["v"]}' if _pick(p) else '',
)
