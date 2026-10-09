# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""SIDE / COLOUR — the named-colour table, the picker-to-word bridge and the colour ops.

Moved verbatim out of the old single-file creature_fx.py (lines 1489-1831).
"""

from __future__ import annotations

from zyg_workflows.creature_fx.base import _amt, _edit, _pick, c, e, f, i, s


# ══ SIDE · COLOUR ═══════════════════════════════════════════════════════════
# Colour ops name colours in WORDS. A colour picker is offered too, and what it
# sends is the nearest name plus the hex -- because a text encoder cannot read
# #7fd8c8, and a sidecar that recorded only "turquoise" could not reproduce the
# exact swatch the operator picked. Both go in; only the word goes to the model.

_NAMED = [
    ((0, 0, 0), 'black'),
    ((255, 255, 255), 'white'),
    ((128, 128, 128), 'grey'),
    ((190, 30, 30), 'deep red'),
    ((240, 90, 60), 'orange-red'),
    ((240, 170, 60), 'amber'),
    ((250, 225, 120), 'pale gold'),
    ((150, 200, 80), 'yellow-green'),
    ((40, 150, 70), 'green'),
    ((60, 200, 180), 'turquoise'),
    ((70, 160, 230), 'sky blue'),
    ((40, 60, 180), 'deep blue'),
    ((130, 80, 200), 'violet'),
    ((220, 110, 190), 'pink'),
    ((140, 90, 60), 'brown'),
    ((225, 200, 165), 'cream'),
    ((90, 70, 60), 'dark brown'),
    ((200, 200, 210), 'silver'),
]


def colour_word(hexv):
    """Nearest colour NAME to a hex swatch.

    The picker exists because pointing at a colour is faster than spelling one;
    the name exists because the model only reads the name. Recording both is
    what makes a bake reproducible from its sidecar."""
    try:
        r = int(hexv[1:3], 16)
        g = int(hexv[3:5], 16)
        bl = int(hexv[5:7], 16)
    except (ValueError, IndexError):
        return ''
    best, bd = '', 1e9
    for (cr, cg, cb), nm in _NAMED:
        d = (cr - r) ** 2 + (cg - g) ** 2 + (cb - bl) ** 2
        if d < bd:
            best, bd = nm, d
    return best


def _colclause(p, verb, key='col', wkey='word'):
    w = _pick(p, wkey) or colour_word(p.get(key, ''))
    return f'{verb} {w}' if w else ''


_edit(
    'cc_base',
    'Base colour',
    'Colour',
    'Base colour — the dominant colour of the whole creature. The picker and the word '
    'both ride in the recipe; only the word is sent, because that is all a text '
    'encoder can read.',
    '<circle cx="12" cy="12" r="8.4"/><path d="M12 3.6a8.4 8.4 0 000 16.8z" fill="currentColor" stroke="none"/>',
    [c('col', 'Swatch', '#7fd8c8'), s('word', 'Or a word', '', 'overrides the swatch', pat=r"[A-Za-z ,'-]{0,60}")],
    fn=lambda p, x: _colclause(p, 'make the creature'),
)

_edit(
    'cc_second',
    'Secondary',
    'Colour',
    'Secondary colour — the belly, the underside, the second half of a two-tone '
    'animal. Named separately so the base op does not have to describe two things.',
    '<circle cx="12" cy="12" r="8.4"/><path d="M4.4 14.4c4.6 3 10.6 3 15.2 0"/>',
    [
        c('col', 'Swatch', '#f0e2c8'),
        s('word', 'Or a word', '', pat=r"[A-Za-z ,'-]{0,60}"),
        e(
            'where',
            'On',
            'the underside',
            ['the underside', 'the chest and throat', 'the legs', 'the face', 'the back', 'the tail'],
        ),
    ],
    fn=lambda p, x: _colclause(p, f'make {p["where"]}'),
)

_edit(
    'cc_accent',
    'Accent',
    'Colour',
    'Accent colour — the small bright bits: claw tips, horn tips, the inside of the '
    'ears, the eye ring. Too small to survive in a base-colour sentence.',
    '<path d="M12 3.4l2.2 4.6 5 .7-3.6 3.6.9 5-4.5-2.4-4.5 2.4.9-5L4.8 8.7l5-.7z"/>'
    '<circle cx="18.6" cy="18.6" r="2.6"/>',
    [
        c('col', 'Swatch', '#ffb347'),
        s('word', 'Or a word', '', pat=r"[A-Za-z ,'-]{0,60}"),
        e(
            'where',
            'On',
            'the claws and horn tips',
            [
                'the claws and horn tips',
                'the inside of the ears',
                'the eye rings',
                'the spines',
                'the fins',
                'the tail tip',
            ],
        ),
    ],
    fn=lambda p, x: _colclause(p, f'make {p["where"]}'),
)

_edit(
    'cc_grad',
    'Gradient',
    'Colour',
    'Gradient — one colour blending into another along an axis. What "countershaded" '
    'means before it becomes a pattern.',
    '<rect x="4" y="4.4" width="16" height="15.2" rx="2"/>'
    '<path d="M4 12h16" stroke-dasharray="1.6 1.8"/><path d="M4 8h16M4 16h16" opacity=".5"/>',
    [
        s('a', 'From', 'dark', pat=r"[A-Za-z ,'-]{0,40}"),
        s('bcol', 'To', 'pale', pat=r"[A-Za-z ,'-]{0,40}"),
        e('axis', 'Along', 'top to bottom', ['top to bottom', 'head to tail', 'inside to outside']),
    ],
    fn=lambda p, x: (
        f'blend the colour from {p["a"]} to {p["bcol"]} {p["axis"]}' if _pick(p, 'a') and _pick(p, 'bcol') else ''
    ),
)

_edit(
    'cc_counter',
    'Countershading',
    'Colour',
    'Countershading — dark above, pale below. The single most common colour scheme in '
    'nature, and the one that makes a creature read as a real animal.',
    '<ellipse cx="12" cy="12" rx="8.4" ry="6.4"/>'
    '<path d="M3.6 12c4.6 4.6 12.2 4.6 16.8 0" fill="currentColor" stroke="none" opacity=".35"/>'
    '<path d="M3.6 12h16.8"/>',
    [f('a', 'Strength', 60, 0, 100, 1)],
    fn=lambda p, x: f'{_amt(p["a"])} countershaded: darker on the back, paler on the belly' if _amt(p['a']) else '',
)

_edit(
    'cc_stripe',
    'Stripes',
    'Colour',
    'Stripes — count, direction and contrast. Counted, because "striped" comes back '
    'as four stripes on one cell and twenty on the next.',
    '<ellipse cx="12" cy="12" rx="8.6" ry="6.6"/>'
    '<path d="M8.4 6.2c-.6 4-.6 7.6 0 11.6M12 5.6c-.6 4.4-.6 8.4 0 12.8M15.6 6.2c.6 4 .6 7.6 0 11.6"/>',
    [
        i('n', 'Count', 6, 0, 40, 1),
        e('dir', 'Direction', 'vertical', ['vertical', 'horizontal', 'diagonal', 'radiating']),
        s('col', 'Colour', 'dark', pat=r"[A-Za-z ,'-]{0,40}"),
    ],
    fn=lambda p, x: 'no stripes' if p['n'] == 0 else f'give it about {p["n"]} {p["dir"]} {p["col"]} stripes',
)

_edit(
    'cc_spot',
    'Spots',
    'Colour',
    'Spots — size, density and colour. Rosettes are their own option because a leopard '
    'and a dalmatian are not the same pattern at all.',
    '<ellipse cx="12" cy="12" rx="8.6" ry="6.6"/><circle cx="8.6" cy="10" r="1.2"/>'
    '<circle cx="13.4" cy="8.8" r="1.2"/><circle cx="15.6" cy="13" r="1.2"/>'
    '<circle cx="9.8" cy="14.4" r="1.2"/>',
    [
        e(
            'kind',
            'Pattern',
            'spots',
            ['none', 'spots', 'rosettes', 'flecks', 'ocelli, eye spots', 'blotches', 'a reticulated net'],
        ),
        f('dens', 'Density', 50, 0, 100, 1),
        s('col', 'Colour', 'dark', pat=r"[A-Za-z ,'-]{0,40}"),
    ],
    fn=lambda p, x: (
        'an unmarked, plain coat'
        if p['kind'] == 'none' or not _amt(p['dens'])
        else f'cover it in {_amt(p["dens"], ("a few", "scattered", "many", "dense"))} {p["col"]} {p["kind"]}'
    ),
)

_edit(
    'cc_patch',
    'Patches',
    'Colour',
    'Patches — large irregular colour fields rather than a repeating pattern. A piebald '
    'or cow-marked animal, where the shape of each patch is the character.',
    '<ellipse cx="12" cy="12" rx="8.6" ry="6.6"/>'
    '<path d="M6.4 9.4c2.4-1.6 4.4-.6 4 1.6-.4 2.4-4.6 2.6-4.6.4z"/>'
    '<path d="M13.6 13.6c2-2.4 4.4-2 4.6.4.2 2.2-3.4 3-4.6 1.4z"/>',
    [i('n', 'Patches', 4, 0, 20, 1), s('col', 'Colour', 'white', pat=r"[A-Za-z ,'-]{0,40}")],
    fn=lambda p, x: '' if p['n'] == 0 else f'give it about {p["n"]} large irregular {p["col"]} patches',
)

_edit(
    'cc_mask',
    'Face mask',
    'Colour',
    'Face mask — a colour field on the face specifically: a bandit mask, a pale muzzle, '
    "a blaze down the nose. The marking a viewer reads as the creature's expression.",
    '<path d="M3.6 9.4h16.8v3.2c0 1.8-1.4 3.2-3.2 3.2h-1.4l-1.6 2-1.6-2h-3.6l-1.6 2-1.6-2H6.8'
    'A3.2 3.2 0 013.6 12.6z"/><circle cx="8.6" cy="11.4" r="1"/><circle cx="15.4" cy="11.4" r="1"/>',
    [
        e(
            'v',
            'Mask',
            'none',
            [
                'none',
                'a dark bandit mask across the eyes',
                'a pale muzzle',
                'a blaze down the nose',
                'dark tear-lines from the eyes',
                'a pale eye ring',
                'a full contrasting face',
            ],
        )
    ],
    fn=lambda p, x: '' if p['v'] == 'none' else f'give it {p["v"]}',
)

_edit(
    'cc_points',
    'Points',
    'Colour',
    'Points — darker or paler extremities: siamese points, socks, a dipped tail. The '
    'marking most likely to be lost on a downscale, so it is stated as high contrast.',
    '<ellipse cx="12" cy="10.4" rx="6" ry="4.4"/><path d="M8 14.4v4.6M16 14.4v4.6"/>'
    '<path d="M6.6 19h2.8M14.6 19h2.8"/>',
    [
        e(
            'v',
            'Points',
            'none',
            [
                'none',
                'dark points on face, ears, feet and tail',
                'pale socks',
                'a dipped white tail tip',
                'dark ear tips',
            ],
        ),
        f('a', 'Contrast', 70, 0, 100, 1),
    ],
    fn=lambda p, x: (
        ''
        if p['v'] == 'none' or not _amt(p['a'])
        else f'give it {_amt(p["a"], ("subtle", "clear", "strong", "stark"))} {p["v"]}'
    ),
)

_edit(
    'cc_irid',
    'Iridescence',
    'Colour',
    'Iridescence — colour that changes with the viewing angle. It is also the one look '
    'that will NOT match between cells of a sheet, which is a real property of the '
    'material and not a QC failure.',
    '<path d="M3.6 16.4c3-6 6-9 8.4-9s5.4 3 8.4 9"/><path d="M5.4 18.6c2.6-5 5.2-7.4 6.6-7.4s4 2.4 6.6 7.4"/>',
    [f('a', 'Amount', 60, 0, 100, 1), s('hue', 'Shifting toward', 'green and violet', pat=r"[A-Za-z ,'-]{0,60}")],
    fn=lambda p, x: f'give the surface {_amt(p["a"])} iridescence shifting toward {p["hue"]}' if _amt(p['a']) else '',
)

_edit(
    'cc_albino',
    'Morph',
    'Colour',
    'Colour morph — albino, melanistic, leucistic, piebald. One word that resets every '
    'other colour op, which is why it says so in its own tooltip: put it FIRST in the '
    'stack or it will overwrite the ops above it.',
    '<circle cx="12" cy="12" r="8.4"/><path d="M12 3.6v16.8"/>'
    '<path d="M12 3.6a8.4 8.4 0 010 16.8z" fill="currentColor" stroke="none"/>',
    [
        e(
            'v',
            'Morph',
            'none',
            [
                'none',
                'albino, white with red eyes',
                'melanistic, all black',
                'leucistic, pale with dark eyes',
                'piebald',
                'golden',
            ],
        )
    ],
    fn=lambda p, x: '' if p['v'] == 'none' else f'make it {p["v"]}',
)

_edit(
    'cc_sat',
    'Colour intensity',
    'Colour',
    'Colour intensity — said to the MODEL rather than done to the pixels. The Pixel '
    'section has a saturation slider that is exact and instant; this one changes what '
    'gets painted, which is a different thing and survives a re-render.',
    '<circle cx="9.4" cy="12" r="5.4"/><circle cx="14.6" cy="12" r="5.4"/>',
    [f('v', 'Vivid / muted', 40, -100, 100, 1)],
    fn=lambda p, x: (
        f'make the colours {_amt(p["v"])} {"more vivid and saturated" if p["v"] > 0 else "more muted and desaturated"}'
        if _amt(p['v'])
        else ''
    ),
)

_edit(
    'cc_palette',
    'Palette',
    'Colour',
    'Palette — the whole colour scheme in one word, for when you are changing the mood '
    'rather than a part. Applies over every other colour op in the stack.',
    '<path d="M12 3.6a8.4 8.4 0 000 16.8c1 0 1.6-.8 1.4-1.6-.4-1.4.6-2.6 2-2.6h1.6a3.4 3.4 0 003.4-3.4'
    'c0-5-3.8-9.2-8.4-9.2z"/><circle cx="7.6" cy="10.6" r="1.1"/><circle cx="11" cy="7.6" r="1.1"/>'
    '<circle cx="15" cy="8.8" r="1.1"/>',
    [
        e(
            'v',
            'Scheme',
            'as is',
            [
                'as is',
                'earth tones',
                'jewel tones',
                'pastel',
                'monochrome',
                'high contrast black and white',
                'sunset warm',
                'deep sea cold',
                'toxic neon',
                'autumn',
            ],
        )
    ],
    fn=lambda p, x: '' if p['v'] == 'as is' else f'shift the whole palette to {p["v"]}',
)
