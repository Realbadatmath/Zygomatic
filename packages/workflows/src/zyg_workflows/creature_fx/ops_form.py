# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""SIDE / FORM — the skeleton questions: how big, how heavy, how it is put together.

Moved verbatim out of the old single-file creature_fx.py (lines 260-561).
"""

from __future__ import annotations

from zyg_workflows.creature_fx.base import _amt, _edit, b, e, f, i


# ══ SIDE · FORM ═════════════════════════════════════════════════════════════
# The skeleton questions: how big, how heavy, how it is put together. These are
# the edits most likely to break identity, which is why every one of them is
# scored against the anchor after it renders rather than trusted.

_edit(
    'cf_size',
    'Overall size',
    'Form',
    'Overall size — how massive the creature reads at the same framing. Not a '
    'camera move: the creature itself gets bigger or smaller against its own '
    'proportions, so a positive value reads as bulk and presence rather than a '
    'closer lens.',
    '<path d="M4 20V9.6a3.4 3.4 0 013.4-3.4h9.2A3.4 3.4 0 0120 9.6V20"/>'
    '<path d="M8.6 20v-5.4h6.8V20"/><path d="M12 3.2v2.4"/>',
    [f('v', 'Bigger / smaller', 40, -100, 100, 1)],
    fn=lambda p, x: (
        f'make the creature {_amt(p["v"])} {"larger and more massive" if p["v"] > 0 else "smaller and more compact"}'
        if _amt(p['v'])
        else ''
    ),
)

_edit(
    'cf_bulk',
    'Bulk',
    'Form',
    'Bulk — fat, fluff and mass on the same skeleton. Separate from size: a '
    'creature can be small and round or large and gaunt, and briefs conflate '
    'the two constantly.',
    '<ellipse cx="12" cy="13.4" rx="7.6" ry="6.2"/><path d="M12 7.2V4.2"/><path d="M6.6 9.4c1.6 1.2 9.2 1.2 10.8 0"/>',
    [f('v', 'Plump / lean', 40, -100, 100, 1)],
    fn=lambda p, x: (
        f'make the body {_amt(p["v"])} {"plumper and rounder" if p["v"] > 0 else "leaner and more slender"}'
        if _amt(p['v'])
        else ''
    ),
)

_edit(
    'cf_prop',
    'Proportions',
    'Form',
    'Proportions — the head-to-body ratio, the single strongest cue for how a '
    'creature reads emotionally. A big head on a small body reads young and '
    'appealing; the reverse reads predatory.',
    '<circle cx="12" cy="6.6" r="3.4"/><rect x="8" y="11.6" width="8" height="8.4" rx="2.4"/>',
    [f('v', 'Head : body', 0, -100, 100, 1)],
    fn=lambda p, x: (
        f'make the head {_amt(p["v"])} '
        f'{"larger relative to the body" if p["v"] > 0 else "smaller relative to the body"}'
        if _amt(p['v'])
        else ''
    ),
)

_edit(
    'cf_posture',
    'Posture',
    'Form',
    'Posture — how the creature carries itself when standing still. This is the '
    'silhouette before any pose: upright, hunched, crouched, sprawling.',
    '<circle cx="12" cy="4.4" r="2"/><path d="M12 6.4v7"/><path d="M12 13.4l-3 6.6M12 13.4l3 6.6"/>'
    '<path d="M8.4 9.4h7.2"/>',
    [e('v', 'Carriage', 'upright', ['upright', 'hunched', 'crouched', 'sprawling', 'coiled', 'rearing', 'lowered'])],
    fn=lambda p, x: f'give it an {p["v"]} posture' if p['v'] != 'upright' else 'stand it upright and square',
)

_edit(
    'cf_head',
    'Head shape',
    'Form',
    'Head shape — the skull under the surface. Round, wedge, blunt, elongated. '
    'The one anatomy word a judge can check without seeing the body.',
    '<path d="M5.4 12.6c0-4 3-7 6.6-7s6.6 3 6.6 7c0 3.6-3 6.4-6.6 6.4s-6.6-2.8-6.6-6.4z"/>'
    '<circle cx="9.6" cy="12" r="1"/><circle cx="14.4" cy="12" r="1"/>',
    [
        e(
            'v',
            'Skull',
            'rounded',
            ['rounded', 'wedge-shaped', 'blunt and broad', 'elongated', 'domed', 'flattened', 'angular', 'skull-like'],
        )
    ],
    fn=lambda p, x: f'reshape the head to be {p["v"]}',
)

_edit(
    'cf_muzzle',
    'Muzzle',
    'Form',
    'Muzzle — how far the face projects. A snout is what separates a wolf from '
    'an owl at fifty metres, and it survives every angle of the sheet.',
    '<path d="M4 10.4c3.4-3.4 9-3.4 12.4 0"/><path d="M16.4 10.4L21 12l-4.6 1.8"/>'
    '<path d="M4 10.4v4.2c0 2.4 2.6 4.2 6 4.2"/>',
    [
        e(
            'v',
            'Snout',
            'short',
            ['none, flat face', 'short', 'medium', 'long', 'very long and narrow', 'broad and blunt'],
        ),
        f('a', 'Strength', 60, 0, 100, 1),
    ],
    fn=lambda p, x: f'give it a {p["v"]} muzzle' if _amt(p['a']) else '',
)

_edit(
    'cf_jaw',
    'Jaw',
    'Form',
    'Jaw — the lower half of the face: heavy, slack, underslung, beaked. Changes '
    'the read of the whole head without touching the skull.',
    '<path d="M5 7.4c2.6 8 11.4 8 14 0"/><path d="M6.6 12.6c2 3.4 8.8 3.4 10.8 0"/>',
    [
        e(
            'v',
            'Jaw',
            'normal',
            ['normal', 'heavy and square', 'underslung', 'narrow', 'beaked', 'hooked beak', 'mandibled'],
        )
    ],
    fn=lambda p, x: '' if p['v'] == 'normal' else f'give it a {p["v"]} jaw',
)

_edit(
    'cf_teeth',
    'Teeth',
    'Form',
    'Teeth — count, size and whether they show at rest. A closed mouth hides the '
    'single fastest way to make a creature read dangerous.',
    '<path d="M4.6 8.4h14.8v3.2c0 3.4-3.3 6-7.4 6s-7.4-2.6-7.4-6z"/>'
    '<path d="M8 8.4l1.2 3.4M12 8.4l1.4 4.4M16 8.4l1.2 3.4"/>',
    [
        e(
            'v',
            'Dentition',
            'small teeth',
            [
                'small teeth',
                'prominent fangs',
                'a full set of sharp teeth',
                'tusks',
                'flat herbivore teeth',
                'no visible teeth',
                'a needle-toothed maw',
            ],
        ),
        b('show', 'Visible at rest', True),
    ],
    fn=lambda p, x: f'give it {p["v"]}' + (', visible in the open mouth' if p['show'] else ', mouth closed'),
)

_edit(
    'cf_neck',
    'Neck',
    'Form',
    'Neck — length and thickness. The lever the head sits on: a long neck moves '
    'the whole read toward grazing or serpentine, a short one toward brawling.',
    '<path d="M9.4 20V13c0-3 1.2-5.4 2.6-5.4S14.6 10 14.6 13v7"/><circle cx="12" cy="4.6" r="2.4"/>',
    [
        e(
            'v',
            'Neck',
            'medium',
            ['none, head on body', 'short and thick', 'medium', 'long', 'very long and serpentine'],
        ),
        f('a', 'Strength', 60, 0, 100, 1),
    ],
    fn=lambda p, x: f'give it a {p["v"]} neck' if _amt(p['a']) else '',
)

_edit(
    'cf_torso',
    'Torso',
    'Form',
    'Torso — the barrel: deep-chested, barrel-round, slab-sided, wasp-waisted. '
    'What the limbs hang off and the surface wraps.',
    '<path d="M8 4.6h8l1.4 6.4c.6 2.8-.6 5.6-3 7.2l-2.4 1.6-2.4-1.6c-2.4-1.6-3.6-4.4-3-7.2z"/>',
    [
        e(
            'v',
            'Chest',
            'even',
            [
                'even',
                'deep-chested',
                'barrel-round',
                'slab-sided',
                'wasp-waisted',
                'pot-bellied',
                'flat and streamlined',
            ],
        )
    ],
    fn=lambda p, x: '' if p['v'] == 'even' else f'make the torso {p["v"]}',
)

_edit(
    'cf_spine',
    'Spine',
    'Form',
    'Spine — the top line from skull to tail root. A humped back, a swayed one or '
    'a straight one changes the silhouette from every angle including behind.',
    '<path d="M4 17.4c3-1 4.4-6 8-6s5 5 8 6"/><path d="M6.4 14.2l-.8-2M9.6 12l-.6-2.2M13 11.4l.4-2.2M16.4 13l1-2"/>',
    [e('v', 'Top line', 'level', ['level', 'humped', 'arched', 'swayed', 'ridged', 'crested along the spine'])],
    fn=lambda p, x: '' if p['v'] == 'level' else f'give it a {p["v"]} back',
)

_edit(
    'cf_limbs',
    'Limb count',
    'Form',
    'Limb count — how many legs and arms. THE body-plan question: it is the one '
    'edit the judge is asked about by name on every cell, because a rotation that '
    "invents a fifth leg is the pipeline's classic failure.",
    '<path d="M12 4.4v6"/><path d="M12 10.4l-4.4 3.2M12 10.4l4.4 3.2"/>'
    '<path d="M7.6 13.6V20M16.4 13.6V20"/><path d="M9 7.4H5.2M15 7.4h3.8"/>',
    [i('legs', 'Legs', 2, 0, 12, 1), i('arms', 'Arms', 2, 0, 8, 1), b('strict', 'State the count explicitly', True)],
    fn=lambda p, x: (
        f'the creature has exactly {p["legs"]} legs and {p["arms"]} arms'
        if p['strict']
        else f'give it {p["legs"]} legs and {p["arms"]} arms'
    ),
)

_edit(
    'cf_limblen',
    'Limb length',
    'Form',
    'Limb length — the same limbs, longer or shorter. Stilt-legged reads as wading '
    'or spidery; stubby reads as burrowing or comic.',
    '<path d="M8 4.4v15.2M16 4.4v15.2"/><path d="M5.6 19.6h4.8M13.6 19.6h4.8"/><path d="M8 11.6h8"/>',
    [f('v', 'Long / short', 40, -100, 100, 1)],
    fn=lambda p, x: (
        f'make the limbs {_amt(p["v"])} {"longer" if p["v"] > 0 else "shorter and stubbier"}' if _amt(p['v']) else ''
    ),
)

_edit(
    'cf_digits',
    'Digits',
    'Form',
    'Digits — toes and fingers, counted. Three-toed and five-fingered are different '
    'creatures, and a rotation will happily change its mind between cells.',
    '<path d="M6.4 20v-6.6a2 2 0 014 0"/><path d="M10.4 13.4V7.6a2 2 0 014 0v5.8"/>'
    '<path d="M14.4 13.4V9.4a2 2 0 014 0V20"/>',
    [
        i('n', 'Digits per foot', 3, 1, 8, 1),
        e('kind', 'Kind', 'toes', ['toes', 'fingers', 'claws', 'talons', 'webbed toes']),
    ],
    fn=lambda p, x: f'each foot has exactly {p["n"]} {p["kind"]}',
)

_edit(
    'cf_feet',
    'Feet',
    'Form',
    'Feet — paw, hoof, talon, flipper, or none. What touches the ground decides '
    'what the creature can plausibly stand on in a scene.',
    '<path d="M7 15.6c0-2.6 2.2-4.6 5-4.6s5 2 5 4.6-2.2 4.4-5 4.4-5-1.8-5-4.4z"/>'
    '<circle cx="7.6" cy="8.6" r="1.5"/><circle cx="11" cy="6.6" r="1.5"/>'
    '<circle cx="14.6" cy="7.4" r="1.5"/>',
    [
        e(
            'v',
            'Foot',
            'paws',
            ['paws', 'hooves', 'talons', 'flippers', 'suction pads', 'clawed feet', 'no feet, a serpentine base'],
        )
    ],
    fn=lambda p, x: f'give it {p["v"]}',
)

_edit(
    'cf_symmetry',
    'Symmetry',
    'Form',
    'Symmetry — a deliberate asymmetry, which is otherwise almost impossible to get '
    'and impossible to keep. Warning: it fights the mirror trick the sheet uses for '
    'the opposite profile, so a sheet built after this will not mirror cleanly.',
    '<path d="M12 3.4v17.2" stroke-dasharray="2.6 2.4"/>'
    '<path d="M9.6 6.6L4.4 12l5.2 5.4z"/><path d="M14.4 5.6l6.2 6.4-6.2 6.4"/>',
    [
        e(
            'v',
            'Body',
            'bilaterally symmetric',
            [
                'bilaterally symmetric',
                'one oversized limb on the left',
                'one oversized limb on the right',
                'a lopsided head',
                'asymmetric horns',
                'one missing eye',
            ],
        )
    ],
    fn=lambda p, x: 'keep the body bilaterally symmetric' if p['v'].startswith('bilater') else f'give it {p["v"]}',
)
