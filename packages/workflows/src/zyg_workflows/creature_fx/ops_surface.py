# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""SIDE / SURFACE — what the light hits: the material, never just a word.

Moved verbatim out of the old single-file creature_fx.py (lines 1190-1488).
"""

from __future__ import annotations

from zyg_workflows.creature_fx.base import _amt, _edit, _pick, b, e, f, s


# ══ SIDE · SURFACE ══════════════════════════════════════════════════════════
# What the light hits. Surface is what a LoRA learns most readily and what a
# restyle destroys first, so each of these says the material, not just a word.

_edit(
    'cs_fur',
    'Fur',
    'Surface',
    'Fur — the coat itself: length, density and how it lies. The pufferball is fur '
    'from silhouette to shading, and "soft white fur" is the single phrase its whole '
    'sheet is built on.',
    '<path d="M4.4 18.4c1.4-2.4 1-5.4-.6-7 2.4.6 4.4-.4 5.4-2.4 1 2.4 3 3.4 5.4 2.8'
    '-1 2.4-.4 4.8 1.4 6.2"/><path d="M3.4 19.6h17.2"/>',
    [
        e('len', 'Length', 'medium', ['none', 'short', 'medium', 'long', 'very long and shaggy']),
        e('kind', 'Coat', 'soft', ['soft', 'coarse', 'woolly', 'silky', 'matted', 'curly', 'bristly', 'downy']),
        f('dens', 'Density', 0, -100, 100, 1),
    ],
    fn=lambda p, x: (
        'the creature is hairless'
        if p['len'] == 'none'
        else f'cover it in {p["len"]} {p["kind"]} fur'
        + (f', {_amt(p["dens"])} {"thicker" if p["dens"] > 0 else "sparser"}' if _amt(p['dens']) else '')
    ),
)

_edit(
    'cs_mane',
    'Mane',
    'Surface',
    'Mane — longer hair in one place: neck, spine, tail, ankles. Reads as a separate '
    'feature from the coat and survives a restyle better than coat length does.',
    '<path d="M12 20.4a6 6 0 100-12 6 6 0 000 12z"/>'
    '<path d="M12 8.4c-3-1-4.6-3-5-5.4 2 .6 3.6 0 5-1.4 1.4 1.4 3 2 5 1.4-.4 2.4-2 4.4-5 5.4z"/>',
    [
        e(
            'where',
            'Mane on',
            'the neck',
            ['the neck', 'the spine', 'the tail', 'the ankles', 'the shoulders', 'the whole head'],
        ),
        f('a', 'Volume', 60, 0, 100, 1),
    ],
    fn=lambda p, x: (
        f'give it a {_amt(p["a"], ("slight", "full", "thick", "enormous"))} mane along {p["where"]}'
        if _amt(p['a'])
        else ''
    ),
)

_edit(
    'cs_scales',
    'Scales',
    'Surface',
    'Scales — size, overlap and finish. Fine scales read as skin at sheet resolution; '
    'large plated ones survive every downscale the pipeline does.',
    '<path d="M3.6 8.4c1.6-2 4.4-2 6 0 1.6-2 4.4-2 6 0 1.6-2 4.4-2 5.4 0"/>'
    '<path d="M3.6 14c1.6-2 4.4-2 6 0 1.6-2 4.4-2 6 0 1.6-2 4.4-2 5.4 0"/>'
    '<path d="M3.6 19.4c1.6-2 4.4-2 6 0 1.6-2 4.4-2 6 0"/>',
    [
        e('sz', 'Scale size', 'medium', ['none', 'fine', 'medium', 'large plated', 'overlapping shields']),
        e('fin', 'Finish', 'matte', ['matte', 'glossy', 'iridescent', 'wet', 'dusty', 'metallic']),
    ],
    fn=lambda p, x: '' if p['sz'] == 'none' else f'cover it in {p["sz"]} {p["fin"]} scales',
)

_edit(
    'cs_feath',
    'Feathers',
    'Surface',
    'Feathers — down, contour or full plumage, and where. Feathers and fur read '
    'differently under a rim light, which is why they are separate ops.',
    '<path d="M17.6 4.4c-6 .6-10 4.6-11.4 10.4l-2 4.6"/>'
    '<path d="M17.6 4.4c1 5.4-1.6 9.4-6.6 11.4l-4 1.4"/><path d="M11.4 6.6l1.6 3.4"/>',
    [
        e(
            'kind',
            'Plumage',
            'none',
            ['none', 'downy', 'contour feathers', 'full plumage', 'scaled feathers', 'ragged feathers'],
        ),
        e('where', 'Where', 'the whole body', ['the whole body', 'the wings only', 'the neck and head', 'the tail']),
    ],
    fn=lambda p, x: '' if p['kind'] == 'none' else f'give it {p["kind"]} on {p["where"]}',
)

_edit(
    'cs_skin',
    'Skin',
    'Surface',
    'Bare skin — the finish where there is no coat. Smooth, leathery, wrinkled, '
    'porous. This is what a "waxy skin" complaint is actually about '
    '([[project_waxy_skin_diagnosis]]).',
    '<circle cx="12" cy="12" r="8.4"/><circle cx="9.4" cy="10" r="1"/>'
    '<circle cx="14.4" cy="11" r="1"/><circle cx="11.4" cy="15" r="1"/>',
    [
        e(
            'v',
            'Skin',
            'smooth',
            ['smooth', 'leathery', 'wrinkled', 'pebbled', 'rubbery', 'translucent', 'cracked', 'porous and natural'],
        ),
        b('nowax', 'Fight the waxy look', True),
    ],
    fn=lambda p, x: (
        f'the bare skin is {p["v"]}' + (', with natural surface texture, not smooth plastic' if p['nowax'] else '')
    ),
    neg='waxy, plastic skin, airbrushed',
)

_edit(
    'cs_plate',
    'Plating',
    'Surface',
    'Plating — armour that is part of the animal: bony plates, chitin, bark, stone. '
    'Distinct from Gear, which is worn and can come off.',
    '<path d="M12 2.6 20 5.4v5.8c0 5.2-3.4 8.8-8 10.6-4.6-1.8-8-5.4-8-10.6V5.4z"/>'
    '<path d="M8 9.4l4-2.4 4 2.4M8 13.4l4-2.4 4 2.4"/>',
    [
        e(
            'v',
            'Plating',
            'none',
            [
                'none',
                'bony plates',
                'chitin',
                'bark-like bark plates',
                'stone slabs',
                'metal plates',
                'crystalline shards',
            ],
        ),
        e(
            'where',
            'Where',
            'the back and shoulders',
            ['the back and shoulders', 'the whole body', 'the head', 'the limbs', 'the chest'],
        ),
    ],
    fn=lambda p, x: '' if p['v'] == 'none' else f'armour {p["where"]} with {p["v"]}',
)

_edit(
    'cs_slime',
    'Slime',
    'Surface',
    'Slime — a wet coating over whatever is underneath. Changes every specular in the '
    'frame, so it is the surface op most visible after a relight.',
    '<path d="M12 3.6c3.4 4.4 5.4 7.6 5.4 10.4a5.4 5.4 0 11-10.8 0c0-2.8 2-6 5.4-10.4z"/>'
    '<path d="M9.6 14.4a2.4 2.4 0 002.4 2.4"/>',
    [f('a', 'Wetness', 60, 0, 100, 1), b('drip', 'Dripping', False)],
    fn=lambda p, x: (
        (
            f'coat it in {_amt(p["a"], ("a sheen of", "clear", "thick", "heavy"))} '
            f'slime' + (', dripping' if p['drip'] else '')
        )
        if _amt(p['a'])
        else ''
    ),
)

_edit(
    'cs_moss',
    'Overgrowth',
    'Surface',
    'Overgrowth — moss, lichen, barnacles, fungus, vines. An age signal that does not '
    'touch the anatomy: the same creature, older and left alone.',
    '<path d="M12 20.4V11"/><path d="M12 14.4c-2.6 0-4.6-2-4.6-4.4 2.6 0 4.6 2 4.6 4.4z"/>'
    '<path d="M12 12.4c2.6 0 4.6-2 4.6-4.4-2.6 0-4.6 2-4.6 4.4z"/><path d="M6.6 20.4h10.8"/>',
    [
        e('v', 'Growth', 'moss', ['moss', 'lichen', 'barnacles', 'fungus', 'vines', 'coral']),
        f('a', 'Coverage', 50, 0, 100, 1),
    ],
    fn=lambda p, x: (
        f'grow {_amt(p["a"], ("a little", "patches of", "thick", "dense"))} {p["v"]} over it' if _amt(p['a']) else ''
    ),
)

_edit(
    'cs_crystal',
    'Crystal',
    'Surface',
    'Crystal or mineral growth — shards, geode faces, gemstone inclusions. The one '
    'surface that also emits, so it pairs with Bioluminescence.',
    '<path d="M12 3.4l5.4 5.6-2.4 9.4H9L6.6 9z"/><path d="M12 3.4V18.4M6.6 9h10.8"/>',
    [
        e(
            'v',
            'Mineral',
            'none',
            ['none', 'crystal shards', 'geode faces', 'gemstone inclusions', 'obsidian', 'raw ore'],
        ),
        f('a', 'Coverage', 50, 0, 100, 1),
    ],
    fn=lambda p, x: (
        ''
        if p['v'] == 'none' or not _amt(p['a'])
        else f'grow {p["v"]} from its {"back and shoulders" if p["a"] < 60 else "whole body"}'
    ),
)

_edit(
    'cs_metal',
    'Metal',
    'Surface',
    'Metal — parts of the creature that are worked metal rather than tissue. The '
    'boundary between the two is the whole point, so it names where.',
    '<circle cx="12" cy="12" r="7.6"/><path d="M12 4.4v15.2M4.4 12h15.2"/><circle cx="12" cy="12" r="2.4"/>',
    [
        e(
            'where',
            'Metal on',
            'none',
            ['none', 'one limb', 'the face', 'the spine', 'the whole body', 'plates over the shoulders'],
        ),
        e(
            'fin',
            'Finish',
            'brushed steel',
            ['brushed steel', 'blackened iron', 'brass', 'gold', 'copper, oxidised', 'chrome'],
        ),
    ],
    fn=lambda p, x: '' if p['where'] == 'none' else f'make {p["where"]} {p["fin"]}',
)

_edit(
    'cs_trans',
    'Translucency',
    'Surface',
    'Translucency — light passing through the body, and subsurface scatter in the '
    'thin parts. What makes an ear glow red against a backlight.',
    '<circle cx="12" cy="12" r="7.4" stroke-dasharray="3.4 2.6"/><path d="M12 4.6v14.8"/><path d="M4.6 12h14.8"/>',
    [f('a', 'Amount', 50, 0, 100, 1), b('sss', 'Subsurface scatter in ears and fins', True)],
    fn=lambda p, x: (
        (
            f'make the body {_amt(p["a"])} translucent'
            + (', with light scattering through the thin parts' if p['sss'] else '')
        )
        if _amt(p['a'])
        else ''
    ),
)

_edit(
    'cs_glowsurf',
    'Bioluminescence',
    'Surface',
    'Bioluminescence — the creature emits light itself. Distinct from a rim light: '
    'this one lights what is next to it and survives a black background.',
    '<circle cx="12" cy="12" r="4"/><path d="M12 2.6v3.2M12 18.2v3.2M2.6 12h3.2M18.2 12h3.2'
    'M5.4 5.4l2.2 2.2M16.4 16.4l2.2 2.2M18.6 5.4l-2.2 2.2M7.6 16.4l-2.2 2.2"/>',
    [
        s('col', 'Glow colour', 'cyan', pat=r"[A-Za-z ,'-]{0,40}"),
        e(
            'where',
            'Glowing',
            'markings',
            ['markings', 'the eyes', 'the underside', 'veins under the skin', 'the tail tip', 'spots along the flanks'],
        ),
        f('a', 'Intensity', 60, 0, 100, 1),
    ],
    fn=lambda p, x: (
        f'give it {_amt(p["a"], ("faintly", "clearly", "brightly", "blindingly"))} glowing {p["col"]} {p["where"]}'
        if _amt(p['a']) and _pick(p, 'col')
        else ''
    ),
)

_edit(
    'cs_pores',
    'Micro detail',
    'Surface',
    'Micro detail — pores, grain, individual hairs. The level below texture: it is '
    'what a 1024 cell can hold and what an upscale invents when it is missing.',
    '<circle cx="12" cy="12" r="8.4"/><circle cx="8.6" cy="9.4" r=".9"/>'
    '<circle cx="12.4" cy="8.4" r=".9"/><circle cx="15.4" cy="11.4" r=".9"/>'
    '<circle cx="9.4" cy="14.4" r=".9"/><circle cx="13.4" cy="15" r=".9"/>',
    [f('v', 'Detail', 40, -100, 100, 1)],
    fn=lambda p, x: (
        f'render the surface with {_amt(p["v"])} '
        f'{"more fine detail, individual hairs and visible grain" if p["v"] > 0 else "less fine detail, simplified and smoother"}'
        if _amt(p['v'])
        else ''
    ),
)

_edit(
    'cs_worn',
    'Wear',
    'Surface',
    'Wear — the surface used: scuffed plates, split scales, a coat rubbed thin. Age '
    'on the material rather than on the animal.',
    '<path d="M4.4 19.6l4-11 3.6 6.6 2.4-4 5.2 8.4z"/><path d="M8.4 8.6l-1-4"/>',
    [f('a', 'Wear', 50, 0, 100, 1)],
    fn=lambda p, x: f'make the surface {_amt(p["a"])} worn, scuffed and used' if _amt(p['a']) else '',
)
