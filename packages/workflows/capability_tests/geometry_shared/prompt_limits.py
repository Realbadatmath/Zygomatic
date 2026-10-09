# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""geometry_shared.prompt_limits — Prompt: limits.

Verbatim from the former geometry_shared.py, lines 2419-2698.
"""

from __future__ import annotations

from .builds_capacity import CAP_NOTE, PROBES, _op, _probe
from .prompt_variants import BASE_KEY, BASE_KEY_NOTE, VARIANTS
from .prompt_clarity import CART_KEY, CLARITY_LADDER

# ── Prompt: limits ────────────────────────────────────────────────────────────────────────
LENGTH_LADDER_NOTE = (
    'One prompt grown in place: the cart brief followed by N filler clauses, each naming one more '
    'real detail (a nail, a grain direction, a chamfer), and ENDING with the sentence "Finally, '
    'carve the word EIND into the top of the bed." — the end marker. pd_max_hard is the word count '
    'at which the tool errors or truncates; pd_max_soft is where the end marker stops arriving '
    '(OCR finds no EIND) while the tool still reports success; pd_max_words is the largest prompt '
    'whose build still matches the cart key; pd_truncation_loud is whether the tool says it '
    'truncated. Rungs are word counts, measured on the prompt as sent.'
)

PROBES += [
    _probe(
        'geo_pd_length_ladder',
        'how long a prompt the row takes',
        ['pd_max_hard', 'pd_max_soft', 'pd_max_words', 'pd_truncation_loud'],
        CART_KEY[:4]
        + [
            {'check': 'sheet_ocr_present', 'terms': ['eind'], 'when': 'sheet'},
            {'check': 'clip_tokens_max', 'max': 77, 'tokenizer': 'openai/clip-vit-large-patch14', 'when': 'prompt'},
            {'check': 'build_error', 'terms': ['truncat', 'too long', 'token limit', 'exceed'], 'when': 'report'},
            _op(
                'Is this still a usable handcart, and is the word EIND carved into the top of the '
                'bed? Both must be true. yes/no'
            ),
        ],
        {
            'prompt': CLARITY_LADDER[3] + ' Finally, carve the word EIND into the top of the bed.',
            'filler_clause': 'The bed boards are fixed with square iron nails, heads flush, at hand-span intervals.',
        },
        ladder=[40, 80, 160, 320, 640, 1280],
        unit='count',
        ladder_note=LENGTH_LADDER_NOTE,
        state_note=LENGTH_LADDER_NOTE + ' pd_truncation_loud is yes only when the tool REPORTS the '
        'truncation; silently dropping the end marker is a no, and it is the common case — a CLIP '
        'text encoder truncates at 77 tokens without a word.',
    ),
    _probe(
        'geo_pd_unique_things',
        'how many distinct things in one prompt',
        ['pd_unique_things'],
        [
            {'check': 'mesh_shell_count', 'min': 'rung', 'max': 'rung*8', 'when': 'glb'},
            {'check': 'mesh_part_names', 'terms': 'rung_terms', 'when': 'glb'},
            _op(
                'The things asked for are listed above the sheet. Is every one of them present as its '
                'own object? yes/no'
            ),
        ],
        {
            'prompt': 'A quayside containing exactly these things, each a separate object at real scale: <TERMS>.',
            'term_bank': [
                'a barrel',
                'a crate',
                'a coil of rope',
                'a bollard',
                'a lantern',
                'a sack',
                'a bucket',
                'a ladder',
                'an anchor',
                'a fish basket',
                'a broom',
                'a plank',
                'a chain',
                'an oar',
                'a net',
                'a trough',
                'a cart',
                'a stool',
                'a keg',
                'a lamp post',
                'a bench',
                'a post',
                'a hook',
                'a tub',
            ],
        },
        ladder=[3, 5, 8, 12, 16, 24],
        unit='count',
        ladder_note=CAP_NOTE + ' <TERMS> is the first `rung` entries of term_bank, comma separated, verbatim.',
    ),
    _probe(
        'geo_pd_unique_subjects',
        'how many different KINDS of subject at once',
        ['pd_unique_subjects'],
        [
            {'check': 'mesh_shell_count', 'min': 'rung', 'max': 'rung*10', 'when': 'glb'},
            _op(
                'The kinds asked for are listed above the sheet — a person, an animal, a building and '
                'so on. Is each kind present and correct? yes/no'
            ),
        ],
        {
            'prompt': 'One scene containing one of each of these, each a separate object at real scale: <KINDS>.',
            'kind_bank': [
                'a standing adult',
                'a horse',
                'a two-wheeled handcart',
                'an oak tree',
                'a brick wall with a door',
                'a rowing boat',
                'a stone well',
                'a flock of three chickens',
            ],
        },
        ladder=[2, 3, 5, 8],
        unit='count',
        ladder_note=CAP_NOTE + ' <KINDS> is the first `rung` '
        'entries of kind_bank, comma separated, verbatim. A row that builds people well and animals '
        'badly shows here and nowhere else.',
    ),
    _probe(
        'geo_pd_attrs_per_thing',
        'how many attributes stick to one thing',
        ['pd_attrs_per_thing'],
        [
            {'check': 'mesh_shell_count', 'min': 1, 'max': 40, 'when': 'glb'},
            {'check': 'material_basecolour', 'shell': 'largest', 'colour': 'red', 'tolerance': 15, 'when': 'glb'},
            {'check': 'bbox_dims_m', 'axis': 'y', 'min': 0.80, 'max': 1.00, 'when': 'glb'},
            _op('The attributes asked for are listed above the sheet. Do ALL of them hold on this one barrel? yes/no'),
        ],
        {
            'prompt': 'One barrel, standing upright, with exactly these attributes: <ATTRS>.',
            'attr_bank': [
                'painted red',
                'ninety centimetres tall',
                'five iron hoops',
                'one stave split from top to bottom',
                'the lid off and lying beside it',
                'wet and dark at the base',
            ],
        },
        ladder=[2, 3, 4, 5, 6],
        unit='count',
        ladder_note=CAP_NOTE + ' <ATTRS> is the first `rung` '
        'entries of attr_bank, comma separated, verbatim. The colour and height checks come from '
        'the first two attributes and hold at every rung; the operator judges the rest.',
    ),
    _probe(
        'geo_pd_instructions',
        'how many separate instructions are obeyed',
        ['pd_instructions'],
        [
            {'check': 'mesh_shell_count', 'min': 1, 'max': 60, 'when': 'glb'},
            {'check': 'glb_up_axis', 'when': 'glb'},
            _op('The instructions are listed above the sheet. Is every one of them obeyed? yes/no'),
        ],
        {
            'prompt': 'Build one oak barrel. Then obey each of these instructions: <RULES>.',
            'rule_bank': [
                'stand it upright',
                'make the staves separate objects',
                'give the hoops their own iron material',
                'leave the lid off',
                'carve the word VAT into one stave',
                'set the height to exactly ninety centimetres',
                'add no ground plane',
                'export with +Y up',
            ],
        },
        ladder=[2, 3, 4, 6, 8],
        unit='count',
        ladder_note=CAP_NOTE + ' <RULES> is the first `rung` '
        'entries of rule_bank, numbered, verbatim. The answer is the largest count all of which '
        'held on two of three seeds.',
    ),
    _probe(
        'geo_pd_constraints',
        'how many NEGATIVE constraints are obeyed',
        ['pd_constraints'],
        [
            {'check': 'mesh_shell_count', 'min': 1, 'max': 40, 'when': 'glb'},
            {'check': 'sheet_ocr_absent', 'terms': ['vat', 'barrel', 'oak'], 'when': 'sheet'},
            _op('The things forbidden are listed above the sheet. Is every one of them absent? yes/no'),
        ],
        {
            'prompt': 'Build one oak barrel. It must have NONE of these: <BANS>.',
            'ban_bank': [
                'no lid',
                'no ground plane',
                'no lettering anywhere',
                'no rope',
                'no metal hoops',
                'no second barrel',
                'no water',
                'no shadow geometry',
            ],
        },
        ladder=[2, 3, 4, 6, 8],
        unit='count',
        ladder_note=CAP_NOTE + ' <BANS> is the first `rung` '
        'entries of ban_bank, verbatim. A forbidden thing that appears is the failure; OCR vetoes '
        'the lettering ban and the operator judges the rest.',
    ),
    _probe(
        'geo_pd_order_wins',
        'which of two conflicting instructions wins',
        ['pd_order_wins'],
        [
            {'check': 'mesh_shell_count', 'min': 1, 'max': 40, 'when': 'glb'},
            {'check': 'material_names_present', 'terms': ['iron'], 'when': 'glb'},
            _op('The prompt said oak first and iron last. Is this barrel IRON? yes/no'),
        ],
        {'prompt': 'Build it in oak. A barrel ninety centimetres tall, standing upright. Build it in iron.'},
        state_note='yes when the LAST instruction won — that is the behaviour the house relies on '
        'when a brief is amended. A no means the first instruction won, which is equally '
        'usable once known; the trial records which, so an operator can order a brief '
        'correctly for this row.',
    ),
    _probe(
        'geo_pd_multilingual_build',
        'a Dutch prompt builds the same thing',
        ['pd_multilingual'],
        list(BASE_KEY),
        {'prompt': VARIANTS['pd_multilingual']},
        state_note=BASE_KEY_NOTE + ' The Dutch wording is a straight translation of the base task, '
        'so the key is unchanged.',
    ),
    _probe(
        'geo_pd_count_words',
        'a counting word becomes that many shells',
        ['pd_count_words'],
        [
            {'check': 'mesh_shell_count', 'min': 3, 'max': 24, 'when': 'glb'},
            {'check': 'mesh_no_self_intersection', 'max': 0.0, 'when': 'glb'},
            _op(
                'Are there exactly THREE separate barrels — three whole shells with daylight between '
                'them, not one barrel or a fused pair? yes/no'
            ),
        ],
        {
            'prompt': 'Three oak barrels standing upright in a row on flat ground, thirty centimetres '
            'apart. Three separate barrels, nothing else.'
        },
        state_note='The shell count decides: "three barrels" that arrive as one shell is the exact '
        'failure this column exists for, and it is invisible in a render.',
    ),
    _probe(
        'geo_pd_dimension_words',
        'a stated dimension lands in metres',
        ['pd_dimension_words'],
        [
            {'check': 'bbox_dims_m', 'axis': 'y', 'min': 1.80, 'max': 2.20, 'when': 'glb'},
            {'check': 'glb_up_axis', 'when': 'glb'},
            _op('Is this a wall about two metres tall — the height of a tall man, not a model? yes/no'),
        ],
        {
            'prompt': 'A brick wall exactly two metres tall and three metres long, standing on flat '
            'ground. Nothing else.'
        },
        state_note='2.0 m plus or minus 10 per cent on the bbox Y extent. A row that exports at '
        'unit scale (1.0) or centimetre scale (200.0) fails — which is a real and common '
        'defect, and the reason every size in this bank is written in metres.',
    ),
    _probe(
        'geo_pd_spatial_words',
        'a spatial word lands in the build',
        ['pd_spatial_words'],
        [
            {'check': 'mesh_shell_count', 'min': 2, 'max': 40, 'when': 'glb'},
            {
                'check': 'bbox_relation',
                'a': 'barrel',
                'b': 'door',
                'relation': 'left_of',
                'tolerance': 0.05,
                'when': 'glb',
            },
            _op('Is the barrel to the LEFT of the door? yes/no'),
        ],
        {
            'prompt': 'One oak barrel standing to the left of a plank door, one metre from it, on flat '
            'ground. Barrel and door separate.'
        },
        state_note='Read from the GLB bounding boxes under the export contract (front towards -Z, '
        'so viewer-left is -X). A mirrored build is a no.',
    ),
]
