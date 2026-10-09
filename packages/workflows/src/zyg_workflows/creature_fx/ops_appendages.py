# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""SIDE / APPENDAGES — everything that sticks out, and what a front-view anchor hides.

Moved verbatim out of the old single-file creature_fx.py (lines 562-911).
"""

from __future__ import annotations

from zyg_workflows.creature_fx.base import _amt, _edit, _pick, b, e, f, i, s


# ══ SIDE · APPENDAGES ═══════════════════════════════════════════════════════
# Everything that sticks out. These are what a front-view anchor HIDES, which is
# why the body-plan lock exists at all: a rotation invents whatever it cannot
# see ([[project_creature_body_plan_lock]]).

_edit(
    'ca_tail',
    'Tail',
    'Appendages',
    'Tail — the appendage a front anchor cannot see and every rotation therefore '
    'invents. Say what it is here and it goes into the instruction, the caption and '
    'the judge question together.',
    '<path d="M3.4 8.4c5.4 0 8.6 2.6 10 6.2 1 2.6 3.4 4.4 6.6 4"/><path d="M17.4 15.4L21 18l-4.4 1.2"/>',
    [
        e(
            'kind',
            'Tail',
            'one long tail',
            [
                'no tail at all',
                'one short tail',
                'one long tail',
                'one thick tapering tail',
                'a segmented tail',
                'a tufted tail',
                'a prehensile tail',
                'a fan of tails',
                'a whip-thin tail',
                'a flat paddle tail',
            ],
        ),
        f('len', 'Length', 0, -100, 100, 1),
    ],
    fn=lambda p, x: (
        f'the creature has {p["kind"]}'
        + (f', {_amt(p["len"])} {"longer" if p["len"] > 0 else "shorter"}' if _amt(p['len']) else '')
    ),
)

_edit(
    'ca_tailtip',
    'Tail tip',
    'Appendages',
    'Tail tip — the last 20% of the tail, which is where a tail gets its character: '
    'a tuft, a blade, a rattle, a bioluminescent lure.',
    '<path d="M3.6 15.4c5 .6 8.6-1.4 10.6-5"/><path d="M14.2 10.4l3.6-3.2"/><circle cx="19" cy="5.4" r="2.4"/>',
    [
        e(
            'v',
            'Tip',
            'plain',
            [
                'plain',
                'a tuft of fur',
                'a spade',
                'a blade',
                'a rattle',
                'a glowing lure',
                'a barbed stinger',
                'a bony club',
                'a feathered fan',
            ],
        )
    ],
    fn=lambda p, x: '' if p['v'] == 'plain' else f'the tail ends in {p["v"]}',
)

_edit(
    'ca_wings',
    'Wings',
    'Appendages',
    'Wings — kind and whether they are present at all. A wing type carries a whole '
    'animal class with it: membrane reads reptile, feathered reads bird, chitin '
    'reads insect.',
    '<path d="M12 19.4c-2-6-6-9-10-9 1 4 4 7 8 8.4"/>'
    '<path d="M12 19.4c2-6 6-9 10-9-1 4-4 7-8 8.4"/><path d="M12 19.4v-8"/>',
    [
        e(
            'kind',
            'Wings',
            'none',
            [
                'none',
                'feathered wings',
                'membrane wings',
                'insect wings',
                'four insect wings',
                'vestigial wings',
                'finned wings',
                'energy wings',
            ],
        ),
        f('span', 'Span', 0, -100, 100, 1),
    ],
    fn=lambda p, x: (
        'the creature has no wings'
        if p['kind'] == 'none'
        else f'give it {p["kind"]}'
        + (f', {_amt(p["span"])} {"wider" if p["span"] > 0 else "smaller"}' if _amt(p['span']) else '')
    ),
)

_edit(
    'ca_wingpose',
    'Wing set',
    'Appendages',
    'Wing set — folded, half-open, spread, beating. Separate from the wings '
    'themselves because the same wings folded and spread are two silhouettes and '
    'only one of them fits a portrait framing.',
    '<path d="M12 20V8"/><path d="M12 9.4C9.4 6.6 6.4 5.4 3.6 5.4c.6 3.4 3.4 6 8.4 7"/>'
    '<path d="M12 9.4c2.6-2.8 5.6-4 8.4-4-.6 3.4-3.4 6-8.4 7"/>',
    [
        e(
            'v',
            'Set',
            'folded',
            [
                'folded against the body',
                'half open',
                'fully spread',
                'mid-beat, raised',
                'mid-beat, lowered',
                'wrapped around the body',
            ],
        )
    ],
    fn=lambda p, x: f'the wings are {p["v"]}',
)

_edit(
    'ca_horns',
    'Horns',
    'Appendages',
    'Horns — count, shape and where they sit. The most reliable single silhouette '
    'change on a head, and the one a judge can count.',
    '<path d="M9 20.6c-.8-4.4.4-9 3-13"/><path d="M15 20.6c.8-4.4-.4-9-3-13"/><path d="M12 7.6V3.4"/>',
    [
        i('n', 'Count', 2, 0, 8, 1),
        e(
            'shape',
            'Shape',
            'curved',
            [
                'curved',
                'straight',
                'spiralled',
                'swept back',
                'ram-curled',
                'branched',
                'blunt nubs',
                'crown of spikes',
            ],
        ),
        f('len', 'Length', 0, -100, 100, 1),
    ],
    fn=lambda p, x: (
        'the creature has no horns'
        if p['n'] == 0
        else f'give it exactly {p["n"]} {p["shape"]} horns'
        + (f', {_amt(p["len"])} {"longer" if p["len"] > 0 else "shorter"}' if _amt(p['len']) else '')
    ),
)

_edit(
    'ca_antler',
    'Antlers',
    'Appendages',
    'Antlers — branched, tined, and counted by points. Distinct from horns: antlers '
    'fork, horns do not, and models mix the two unless told.',
    '<path d="M12 20.6v-8"/><path d="M12 12.6L8.4 8.4 6 9.4M8.4 8.4L7.4 5"/>'
    '<path d="M12 12.6l3.6-4.2 2.4 1M15.6 8.4l1-3.4"/>',
    [
        i('pts', 'Points per side', 3, 0, 10, 1),
        e('spread', 'Spread', 'wide', ['wide', 'narrow and upright', 'sweeping back', 'palmate']),
    ],
    fn=lambda p, x: (
        'no antlers' if p['pts'] == 0 else f'give it {p["spread"]} branched antlers with {p["pts"]} points on each side'
    ),
)

_edit(
    'ca_spikes',
    'Spikes',
    'Appendages',
    'Spikes — a row of them, and where the row runs. Along the spine is the default '
    'because that is the line a side view sells.',
    '<path d="M3.6 19.4h16.8"/><path d="M5.4 19.4l2-6 2 6M11 19.4l2-7.4 2 7.4"/><path d="M16.4 19.4l1.8-5 1.8 5"/>',
    [
        e(
            'where',
            'Along',
            'the spine',
            ['the spine', 'the neck', 'the tail', 'the shoulders', 'the whole back and tail', 'the jaw'],
        ),
        f('a', 'Prominence', 60, 0, 100, 1),
    ],
    fn=lambda p, x: (
        f'give it a row of {_amt(p["a"], ("small", "clear", "large", "huge"))} spikes along {p["where"]}'
        if _amt(p['a'])
        else ''
    ),
)

_edit(
    'ca_quills',
    'Quills',
    'Appendages',
    'Quills — a coat of them rather than a row. Porcupine, echidna, sea urchin: a surface that is also a weapon.',
    '<circle cx="12" cy="13.4" r="5"/><path d="M12 8.4V4.6M16.4 10.4l2.8-2.4M18 14.6h3.4M6.4 14.6H3M7.4 10.2L4.8 8"/>',
    [f('a', 'Density', 60, 0, 100, 1), e('len', 'Length', 'medium', ['short', 'medium', 'long'])],
    fn=lambda p, x: (
        f'cover it in {_amt(p["a"], ("a few", "many", "dense", "a thicket of"))} {p["len"]} quills'
        if _amt(p['a'])
        else ''
    ),
)

_edit(
    'ca_fins',
    'Fins',
    'Appendages',
    'Fins — dorsal, pectoral, tail fin, or a full aquatic set. Also the fastest way '
    'to move a land creature into water without redrawing it.',
    '<path d="M4 16.6c4-1 7-4.4 8.4-8.6 1.6 3.4 4 5.6 7.6 6.6"/><path d="M4 16.6c4.6 2.4 11.4 2.4 16-2.6"/>',
    [
        e(
            'v',
            'Fins',
            'none',
            ['none', 'a dorsal fin', 'pectoral fins', 'a full set of fins', 'a fluked tail fin', 'webbed frills'],
        )
    ],
    fn=lambda p, x: '' if p['v'] == 'none' else f'give it {p["v"]}',
)

_edit(
    'ca_tent',
    'Tentacles',
    'Appendages',
    'Tentacles — count and where they anchor. The appendage most likely to come back '
    'as a different count on every cell, so it is stated as a number.',
    '<path d="M8 4.4c-2.6 4-3 8.4-1.4 12.6"/><path d="M12 4c-.6 5-.4 9.6 1 13.4"/>'
    '<path d="M16 4.4c2.4 4 2.6 8.6 1 12.6"/><path d="M5.4 18.6c4 2.4 9.2 2.4 13.2 0"/>',
    [
        i('n', 'Count', 4, 0, 12, 1),
        e(
            'from',
            'From',
            'the head',
            ['the head', 'the mouth', 'the back', 'the underside', 'where the arms would be'],
        ),
    ],
    fn=lambda p, x: 'no tentacles' if p['n'] == 0 else f'give it exactly {p["n"]} tentacles from {p["from"]}',
)

_edit(
    'ca_claws',
    'Claws',
    'Appendages',
    'Claws — size and kind on whatever the feet are. Retracted or out is a mood change as much as an anatomy one.',
    '<path d="M5.4 5.4c1 5 3.4 9 7 12"/><path d="M9.4 4.6c.6 5 2.4 9 5.6 12.4"/><path d="M13.6 5c0 5 1 8.8 3.4 12"/>',
    [
        e('v', 'Claws', 'small', ['none', 'small', 'prominent', 'hooked', 'scythe-like', 'retracted']),
        b('front', 'Front limbs only', False),
    ],
    fn=lambda p, x: (
        'no claws'
        if p['v'] == 'none'
        else f'give it {p["v"]} claws' + (' on the front limbs only' if p['front'] else '')
    ),
)

_edit(
    'ca_ant',
    'Antennae',
    'Appendages',
    'Antennae — insectile or feathered, and how many. Small in silhouette, enormous '
    'in what they say about the animal class.',
    '<path d="M9.6 12.4C8.4 8.4 6.6 6 4.4 4.8"/><path d="M14.4 12.4c1.2-4 3-6.4 5.2-7.6"/>'
    '<circle cx="4" cy="4.2" r="1.4"/><circle cx="20" cy="4.2" r="1.4"/>'
    '<ellipse cx="12" cy="16.4" rx="4.4" ry="4"/>',
    [i('n', 'Count', 2, 0, 6, 1), e('kind', 'Kind', 'thin', ['thin', 'feathered', 'clubbed', 'segmented', 'curling'])],
    fn=lambda p, x: 'no antennae' if p['n'] == 0 else f'give it {p["n"]} {p["kind"]} antennae',
)

_edit(
    'ca_crest',
    'Crest',
    'Appendages',
    'Crest — a frill, a fan, a hood or a mane of skin. Raised or lowered is the '
    'display state, and it changes the head silhouette more than any horn.',
    '<path d="M12 20V12"/><path d="M12 12c-2.6-2.6-3.4-5.6-3-8.6 2.6 1 4.6 3.4 6 6.6"/>'
    '<path d="M12 12c2.6-2.6 4.4-4.6 6.6-5.6-.4 3-1.8 5.4-4 7.6"/>',
    [
        e(
            'kind',
            'Crest',
            'none',
            ['none', 'a bony crest', 'a skin frill', 'a feathered crest', 'a fan of spines', 'a hood'],
        ),
        b('up', 'Raised', True),
    ],
    fn=lambda p, x: (
        '' if p['kind'] == 'none' else f'give it {p["kind"]}, {"raised and displayed" if p["up"] else "folded flat"}'
    ),
)

_edit(
    'ca_shell',
    'Shell',
    'Appendages',
    'Shell — a carried structure rather than a surface: a carapace, a snail shell, a '
    'plated dome. Read as a separate object the creature lives in.',
    '<path d="M4 16.4a8 8 0 1116 0"/><path d="M4 16.4h16"/><path d="M8 16.4a4 4 0 018 0"/><path d="M12 8.4v8"/>',
    [
        e(
            'v',
            'Shell',
            'none',
            ['none', 'a domed carapace', 'a spiral shell', 'a plated shell', 'a ridged turtle shell', 'a spiked shell'],
        )
    ],
    fn=lambda p, x: '' if p['v'] == 'none' else f'give it {p["v"]} on its back',
)

_edit(
    'ca_extra',
    'Extra parts',
    'Appendages',
    'Extra parts — the free slot: a second head, a stinger, a lure, gills, an eye '
    'stalk. Written as a sentence because the option list can never be long enough.',
    '<path d="M12 3.6v16.8M3.6 12h16.8"/><circle cx="12" cy="12" r="8.4" stroke-dasharray="2.6 2.6"/>',
    [s('v', 'Add', '', 'e.g. a bioluminescent lure on a stalk above the head')],
    fn=lambda p, x: f'add {p["v"]}' if _pick(p) else '',
)

_edit(
    'ca_remove',
    'Remove part',
    'Appendages',
    'Remove a part — the counterpart, and the harder direction. A negative prompt '
    'alone rarely removes anatomy; saying it in the instruction as well is what '
    'actually works.',
    '<path d="M4.6 12h14.8"/><circle cx="12" cy="12" r="8.4" stroke-dasharray="2.6 2.6"/>',
    [s('v', 'Remove', '', 'e.g. the wings')],
    fn=lambda p, x: f'remove {p["v"]} completely; the creature does not have {p["v"]}' if _pick(p) else '',
    neg='{v}',
)
