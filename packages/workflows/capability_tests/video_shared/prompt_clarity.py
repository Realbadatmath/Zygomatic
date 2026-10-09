# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Prompt: clarity needed."""

from __future__ import annotations

from .settings import (
    NEGATIVE,
    STATE_3OF3,
)
from .probes import (
    PROBES,
    _probe,
)
from .scenes import (
    FR2,
    _op,
)
from .prompt_bands import (
    VBASE,
    VKEY,
    VMOTION,
)

# ── Prompt: clarity needed ─────────────────────────────────────────────────────────────
CLARITY_RUNGS = [
    {'rung': 1, 'words': 3, 'prompt': 'a quay'},
    {'rung': 2, 'words': 9, 'prompt': 'a woman in a red cloak on a stone quay'},
    {
        'rung': 3,
        'words': 17,
        'prompt': 'A Dutch woman in a red wool cloak on a stone quay, holding a wooden board painted HAVEN.',
    },
    {'rung': 4, 'words': 38, 'prompt': VBASE},
    {
        'rung': 5,
        'words': 92,
        'prompt': VBASE + ' The cloak is coarse undyed wool dyed madder red, the board is sawn oak '
        'with the letters brushed in black lamp-black paint, the quay is wet '
        'basalt cobble, the gulls are adult herring gulls in summer plumage, the '
        'light is flat north-sea overcast an hour before noon, the water is '
        'brown harbour water with a slow chop, shot on a 50mm lens at eye '
        'height, no modern object anywhere in frame.',
    },
]

PROBES.append(
    _probe(
        'pd_clarity_ladder',
        'prompt clarity: how clear the prompt must be, in five rungs',
        ['pd_clarity_floor', 'pd_terse_ok', 'pd_detail_helps', 'pd_sweet_spot', 'pd_min_len'],
        {
            'prompt': 'per rung, verbatim in `ladder`',
            'ladder': CLARITY_RUNGS,
            'motion': VMOTION,
            'negative': NEGATIVE,
            'measured_against': 'the key of pd_base_damage, unchanged, for every rung',
        },
        VKEY('all five clarity columns')
        + [
            {
                'check': 'clip_tokens_max',
                'max': 77,
                'tokenizer': 'openai/clip-vit-large-patch14',
                'for': 'pd_sweet_spot',
                'note': 'recorded per rung, not a pass/fail: rung 5 is past 77 tokens on purpose so the sweet spot can be '
                'compared against the window',
            }
        ],
        state_rule=STATE_3OF3,
        state_note=(
            'Five rungs, same key, all three seeds. Each fed column reads the SAME five scores differently:\n'
            '  pd_clarity_floor  the LOWEST rung that passes the whole key at 3/3 seeds (a count of words, '
            "unit words) — the answer is that rung's word count.\n"
            '  pd_terse_ok       yes when rung 2 (one line, 9 words) passes the key at 3/3, partial at 2/3.\n'
            '  pd_detail_helps   yes when the score RISES from rung 3 to 4 to 5 and never falls; partial when it '
            'rises then plateaus; no when rung 5 scores below rung 4 (more detail hurts).\n'
            '  pd_sweet_spot     the rung with the highest score, ties broken by the shorter prompt — reported as '
            'its word count (unit words).\n'
            '  pd_min_len        the shortest rung at which the clip is recognisably the asked-for SCENE at all '
            '(the operator question alone, mechanical checks ignored) — reported as a word count. This is a '
            'weaker bar than pd_clarity_floor on purpose, and pd_min_len <= pd_clarity_floor always.'
        ),
        unit='words',
    )
)

PROBES.append(
    _probe(
        'pd_prose_vs_tags',
        'prompt clarity: prose, tag list, or the house template',
        ['pd_prose_ok', 'pd_structure_needed', 'pd_house_template'],
        {
            'prompt': 'per form, verbatim in `forms`',
            'motion': VMOTION,
            'negative': NEGATIVE,
            'measured_against': 'the key of pd_base_damage, unchanged',
            'forms': [
                {'id': 'prose', 'prompt': VBASE},
                {
                    'id': 'tags',
                    'prompt': 'dutch woman, red wool cloak, stone quay, wooden board, HAVEN lettering, two herring '
                    'gulls, wall to her left, daylight, 1671',
                },
                {
                    'id': 'house',
                    'prompt': 'SUBJECT: a Dutch woman in a red wool cloak. ACTION: she turns a wooden board '
                    'painted HAVEN towards the camera and holds it still. SETTING: a stone quay, a '
                    'Dutch harbour town, 1671. OTHER: two herring gulls on the wall to her left. '
                    'LIGHT: flat daylight. CAMERA: static, eye height.',
                },
            ],
        },
        VKEY('all three form columns'),
        state_rule=STATE_3OF3,
        state_note=(
            'Three forms of ONE scene, same key, all three seeds.\n'
            '  pd_prose_ok          yes when the prose form passes the key at 3/3.\n'
            '  pd_structure_needed  yes when the tag form or the house form beats prose by two checks or more; '
            'partial when it beats it by one; no when prose is as good (structure was not needed).\n'
            '  pd_house_template    yes ONLY when the house form passes and BOTH other forms fail — the column '
            'means "reliable only through the template". Partial when the house form is the best of the three '
            'but prose also passes. no when the template gains nothing.'
        ),
    )
)

PROBES += [
    _probe(
        'pd_example_needed',
        'prompt clarity: needs an example to obey',
        ['pd_example_needed'],
        {
            'prompt': VBASE,
            'motion': VMOTION,
            'negative': NEGATIVE,
            'pair': [
                {'id': 'words_only', 'prompt': VBASE, 'image': None},
                {
                    'id': 'with_example',
                    'prompt': VBASE,
                    'image': 'fixtures/video/subjects/person_woman_cloak.png',
                    'note': 'the approved subject still of exactly this woman in exactly this cloak, given as the '
                    'input still or reference image the row supports',
                },
            ],
        },
        VKEY('pd_example_needed'),
        state_rule=STATE_3OF3,
        state_note=(
            'Two rungs, same key. yes when words_only FAILS and with_example PASSES at 3/3 — an example '
            'was needed. partial when the example gains one check. no when words alone were enough. A row '
            'that cannot take a reference image at all is untested here through TRANSPORT_NA, not a no.'
        ),
    ),
    _probe(
        'pd_jargon_needed',
        'prompt clarity: needs domain vocabulary',
        ['pd_jargon_needed'],
        {
            'prompt': 'per rung, verbatim in `pair`',
            'negative': NEGATIVE,
            'pair': [
                {
                    'id': 'plain',
                    'prompt': VBASE,
                    'motion': 'the camera moves slowly towards her while she stays the same size in frame',
                },
                {
                    'id': 'jargon',
                    'prompt': VBASE,
                    'motion': 'dolly in on a 35mm lens with a matching zoom out, static subject, eye-height, '
                    'shallow depth of field',
                },
            ],
        },
        VKEY('pd_jargon_needed')
        + [
            {
                'check': 'flow_direction',
                'direction': 'in',
                'min': 0.4,
                'for': 'pd_jargon_needed',
                'note': 'both rungs ask for the same physical camera move; only the words differ',
            },
            {
                'check': 'bbox_frac',
                'subject': 'the woman',
                'min': 0.5,
                'max': 0.95,
                'sample': FR2,
                'detector': 'sam2-hiera-small',
                'for': 'pd_jargon_needed',
                'note': 'she must stay the same size in frame — the dolly-zoom the jargon rung names by its trade name',
            },
        ],
        state_rule=STATE_3OF3,
        state_note=(
            'yes when the JARGON rung lands the move and the plain rung does not, at 3/3 — the trade '
            'vocabulary was needed. no when plain words worked as well, which is the better answer for '
            'us. partial when the jargon rung gains one check.'
        ),
    ),
    _probe(
        'pd_part_names',
        'prompt clarity: part vocabulary is understood',
        ['pd_part_names'],
        {
            'prompt': 'One Dutch dockworker seen from behind, bare to the waist, on a stone quay, daylight, 1671.',
            'motion': 'his left scapula rotates outward and his right deltoid lifts as he raises the right forearm, '
            'wrist straight, knuckles forward',
            'negative': NEGATIVE,
            'terms': ['scapula', 'deltoid', 'forearm', 'wrist', 'knuckles'],
        },
        [
            {
                'check': 'part_names_resolved',
                'terms': ['scapula', 'deltoid', 'forearm', 'wrist', 'knuckles'],
                'for': 'pd_part_names',
                'note': 'for a row that emits a rig or joint manifest (rigging, movement, poses). A row that emits only '
                'pixels has no manifest and this check is recorded not-applicable; the operator question then '
                'decides alone.',
            },
            _op(
                'The prompt named five body parts: the LEFT scapula rotating out, the RIGHT deltoid lifting, the '
                'right forearm raised, the wrist straight, the knuckles forward. Did the clip move THOSE parts, on '
                'the named side, and not others? yes/no'
            ),
        ],
        state_rule=STATE_3OF3,
    ),
]
