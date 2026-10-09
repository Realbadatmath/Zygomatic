# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""geometry_shared.prompt_clarity — Prompt: clarity needed.

Verbatim from the former geometry_shared.py, lines 2259-2418.
"""

from __future__ import annotations

from .builds_capacity import PROBES, _op, _probe

# ── Prompt: clarity needed ────────────────────────────────────────────────────────────────
# One subject, five rungs from a single word to a full brief, run identically. The columns
# differ only in which rung answers them, so the five are never measured against five subjects.
CLARITY_LADDER = [
    'handcart',
    'a wooden handcart',
    'a two-wheeled wooden handcart with a flat bed',
    'A two-wheeled wooden handcart one and a half metres long: two spoked wheels, a flat plank bed '
    'and two shafts at the front, standing level on flat ground.',
    'A two-wheeled wooden handcart, one and a half metres long and one metre wide, standing level '
    'on flat ground. Two spoked wheels of seventy centimetres, each with twelve spokes, a hub and '
    'an iron rim. A flat plank bed of five boards. Two shafts reaching one metre forward. Oak '
    'throughout, iron fittings. Every named part a separate object, real scale, metres.',
]

CART_KEY = [
    {'check': 'mesh_shell_count', 'min': 3, 'max': 60, 'when': 'glb'},
    {'check': 'bbox_dims_m', 'axis': 'max', 'min': 1.10, 'max': 2.20, 'when': 'glb'},
    {'check': 'mesh_no_self_intersection', 'max': 0.0, 'when': 'glb'},
    {'check': 'glb_up_axis', 'when': 'glb'},
    _op(
        'Is this a usable two-wheeled handcart — two round wheels, a flat bed, shafts at the '
        'front, standing level? yes/no'
    ),
]

CLARITY_NOTE = (
    'One ladder, five rungs, same subject, seeds [11, 12, 13], all five scored against the SAME '
    'cart key. pd_clarity_floor is the lowest rung that passes; pd_terse_ok is whether rung 2 '
    'passes; pd_detail_helps is whether the pass rate rises between rung 2 and rung 4; '
    'pd_sweet_spot is the rung with the highest pass rate (ties go to the shorter rung); '
    'pd_min_len is whether rung 1 — a single word — produces anything usable at all.'
)

PROBES.append(
    _probe(
        'geo_pd_clarity_ladder',
        'how much prompt a build needs',
        ['pd_clarity_floor', 'pd_terse_ok', 'pd_detail_helps', 'pd_sweet_spot', 'pd_min_len'],
        list(CART_KEY),
        {'prompt': CLARITY_LADDER[3], 'ladder_prompts': CLARITY_LADDER},
        ladder=[1, 2, 3, 4, 5],
        ladder_note=CLARITY_NOTE,
        state_note=CLARITY_NOTE,
    )
)

PROBES += [
    _probe(
        'geo_pd_prose_ok',
        'prose against a tag list',
        ['pd_prose_ok'],
        list(CART_KEY),
        {
            'prompt': CLARITY_LADDER[3],
            'pair_b': 'handcart, two wheels, spoked, flat bed, two shafts, oak, iron rim, 1.5m, level, separate parts',
        },
        pair_note='Run the prose prompt and the tag prompt; both are scored against the cart key. '
        'yes when PROSE passes at least as often as tags.',
    ),
    _probe(
        'geo_pd_structure_needed',
        'a numbered part list against the same prose',
        ['pd_structure_needed'],
        list(CART_KEY),
        {
            'prompt': CLARITY_LADDER[3],
            'pair_b': 'Build a handcart with these parts:\n1. two spoked wheels, 70 cm\n'
            '2. a flat plank bed, 1.5 m by 1 m\n3. two shafts, 1 m forward\n'
            'Each numbered part a separate object. Real scale in metres.',
        },
        pair_note='yes when the NUMBERED list beats the prose by at least one seed — the row needs '
        'structure. no when prose is as good, which is the better answer for an operator.',
    ),
    _probe(
        'geo_pd_example_needed',
        'a worked example in the prompt',
        ['pd_example_needed'],
        list(CART_KEY),
        {
            'prompt': CLARITY_LADDER[3],
            'pair_b': 'Example of the shape asked for: a farm wagon is a flat bed on '
            'wheels with shafts at the front, every part its own object.\n\n' + CLARITY_LADDER[3],
        },
        pair_note='yes when the example raises the pass rate.',
    ),
    _probe(
        'geo_pd_house_template',
        'the house build brief against plain prose',
        ['pd_house_template'],
        list(CART_KEY),
        {
            'prompt': CLARITY_LADDER[3],
            'pair_b': 'SUBJECT: two-wheeled wooden handcart\nSIZE: 1.5 m long, 1 m '
            'wide, level on the ground\nPARTS (each a separate object): two '
            'spoked wheels 70 cm, flat plank bed of five boards, two shafts '
            '1 m forward\nMATERIALS: oak, iron fittings\nEXPORT: GLB, metres, '
            '+Y up, standing\nEXCLUDE: ground plane, props, lettering',
        },
        pair_note='The house template is the SUBJECT/SIZE/PARTS/MATERIALS/EXPORT/EXCLUDE form. yes '
        'when it passes at least as often as prose; the answer decides whether the house '
        'form is worth teaching for this row.',
    ),
    _probe(
        'geo_pd_jargon_needed',
        'trade words against plain words',
        ['pd_jargon_needed'],
        [
            {'check': 'mesh_shell_count', 'min': 3, 'max': 40, 'when': 'glb'},
            {'check': 'mesh_part_names', 'terms': ['stave', 'hoop'], 'when': 'glb'},
            _op(
                'Is this a barrel built from separate curved staves held by separate hoops — not one '
                'smooth drum with rings drawn on it? yes/no'
            ),
        ],
        {
            'prompt': 'An oak barrel built from twenty curved staves held by five iron hoops, with a '
            'chime and a croze at each end, standing upright.',
            'pair_b': 'A wooden barrel made of separate curved planks held together by five metal '
            'bands, standing upright.',
        },
        pair_note="yes when the COOPER'S words (stave, hoop, chime, croze) beat the plain words. no "
        'means plain language is enough, which is the cheaper answer.',
    ),
    _probe(
        'geo_pd_asks_back',
        'does the row ask when the prompt is underspecified',
        ['pd_asks_back'],
        [
            {
                'check': 'build_error',
                'terms': ['which', 'how', 'what size', 'clarify', 'ambiguous', 'assume'],
                'when': 'report',
            },
            _op(
                'The prompt said only "a wheel" with no size, material or type. Did the tool ask what '
                'was meant, or state the assumption it made, rather than silently guessing? yes/no'
            ),
        ],
        {'prompt': 'A wheel.'},
        state_note='Only a conversational transport (claude_cli) can answer yes here. A generator '
        'that cannot speak is a NO, honestly: it guessed and said nothing. That is the '
        'measured answer, not an exemption.',
    ),
    _probe(
        'geo_pd_part_names',
        'named parts arrive as addressable objects',
        ['pd_part_names'],
        [
            {'check': 'mesh_part_names', 'terms': ['wheel', 'shaft', 'bed'], 'when': 'glb'},
            {'check': 'mesh_shell_count', 'min': 4, 'max': 60, 'when': 'glb'},
            _op('Can you point to two separate wheels, a bed and two shafts as distinct pieces of this model? yes/no'),
        ],
        {'prompt': 'A wooden handcart with two wheels, a flat bed and a shaft. Name each part: wheel, bed, shaft.'},
        state_note='A part is addressable when its name appears as a shell name OR a material name '
        'in the GLB. A cart that is one welded shell fails, however it looks — the next '
        'stage cannot rig or swap a part it cannot select.',
    ),
]
