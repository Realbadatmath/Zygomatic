# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""geometry_shared.prompt_steering — Prompt: steering.

Verbatim from the former geometry_shared.py, lines 2699-2842.
"""

from __future__ import annotations

from .builds_capacity import PROBES, _op, _probe
from .prompt_variants import BASE_TASK

# ── Prompt: steering ──────────────────────────────────────────────────────────────────────
PROBES += [
    _probe(
        'geo_pd_small_edit',
        'a small edit changes only what it names',
        ['pd_small_edit'],
        [
            {'check': 'mesh_similarity_min', 'to': 'geo_pd_base', 'max_cd': 0.02, 'when': 'glb'},
            {'check': 'material_basecolour', 'shell': 'barrel_left', 'colour': 'blue', 'tolerance': 12, 'when': 'glb'},
            {'check': 'mesh_shell_count', 'min': 4, 'max': 60, 'when': 'glb'},
            _op(
                'Beside the first build, the left barrel is now blue. Is EVERYTHING ELSE unchanged — '
                'same three barrels in the same places, same rope? yes/no'
            ),
        ],
        {'prompt': BASE_TASK, 'edit': 'Make the left barrel blue instead of red. Change nothing else at all.'},
        chain_note='Build the base task on seed 11, then send the edit on the SAME seed and compare '
        'the two GLBs. yes needs the colour changed AND chamfer distance under 2 cm — a '
        'tool that rebuilds the whole model from scratch fails, however good the rebuild.',
    ),
    _probe(
        'geo_pd_fix_lands',
        'a stated fix corrects the named defect',
        ['pd_fix_lands'],
        [
            {'check': 'mesh_shell_count', 'min': 4, 'max': 60, 'when': 'glb'},
            {
                'check': 'bbox_relation',
                'a': 'rope',
                'b': 'barrel_middle',
                'relation': 'above',
                'tolerance': 0.02,
                'when': 'glb',
            },
            _op(
                'The fix asked for the rope to be moved from the ground onto the middle barrel. Is the '
                'rope now on top of the middle barrel? yes/no'
            ),
        ],
        {
            'prompt': 'Three oak barrels standing in a row on a stone quay, twenty centimetres apart. '
            'The left barrel is painted red. A coil of rope lies on the ground beside them.',
            'edit': 'Move the coil of rope onto the top of the middle barrel. Change nothing else.',
        },
        chain_note='The first build deliberately puts the rope on the ground, so there is a real '
        'defect to fix. yes when the fix lands on two of three seeds.',
    ),
    _probe(
        'geo_pd_fix_breaks',
        'does a fix break something else',
        ['pd_fix_breaks'],
        [
            {'check': 'mesh_similarity_min', 'to': 'geo_pd_fix_lands', 'max_cd': 0.05, 'when': 'glb'},
            {'check': 'material_basecolour', 'shell': 'barrel_left', 'colour': 'red', 'tolerance': 12, 'when': 'glb'},
            {'check': 'mesh_no_self_intersection', 'max': 0.0, 'when': 'glb'},
            _op(
                'After the fix, is the rest of the build still right — three barrels, the left one '
                'still red, nothing newly broken? yes/no'
            ),
        ],
        {
            'prompt': 'Three oak barrels standing in a row on a stone quay, twenty centimetres apart. '
            'The left barrel is painted red. A coil of rope lies on the ground beside them.',
            'edit': 'Move the coil of rope onto the top of the middle barrel. Change nothing else.',
        },
        state_note='This column is the COST of the fix, measured on the same chain as pd_fix_lands: '
        'yes means nothing else moved or lost its colour. A fix that lands and breaks the '
        'red barrel is a yes on pd_fix_lands and a no here, and both are true.',
    ),
    _probe(
        'geo_pd_seed_vs_prompt',
        'seed against prompt: which moves the build more',
        ['pd_seed_vs_prompt'],
        [
            {'check': 'pairwise_mesh_distinct', 'min_cd': 0.01, 'when': 'glb'},
            {'check': 'mesh_similarity_max', 'to': 'geo_pd_base', 'min_cd': 0.02, 'when': 'glb'},
            _op(
                'Two grids are shown: one is the same prompt on three seeds, the other three different '
                'prompts on one seed. Does the PROMPT grid vary more than the SEED grid? yes/no'
            ),
        ],
        {
            'prompt': BASE_TASK,
            'grid': {
                'seeds': [11, 12, 13],
                'prompts': [
                    BASE_TASK,
                    BASE_TASK.replace('left barrel is painted red', 'left barrel is painted blue'),
                    BASE_TASK.replace('Three oak barrels', 'Four oak barrels'),
                ],
            },
        },
        state_note='Mean pairwise chamfer distance across the seed row against the prompt row. yes '
        'when the prompt row is the larger — the prompt is the steering wheel. no means '
        'the seed dominates and the prompt is advice, which is worth knowing before '
        'anyone spends a week wording briefs for this row.',
    ),
    _probe(
        'geo_pd_reusable',
        'does one wording work across subjects',
        ['pd_reusable'],
        [
            {'check': 'mesh_shell_count', 'min': 2, 'max': 60, 'when': 'glb'},
            {'check': 'glb_up_axis', 'when': 'glb'},
            {'check': 'mesh_no_self_intersection', 'max': 0.0, 'when': 'glb'},
            _op('Is this a usable model of the subject printed above the sheet, with its named parts separate? yes/no'),
        ],
        {
            'prompt': 'SUBJECT: <SUBJECT>\nSIZE: <SIZE>\nPARTS (each a separate object): <PARTS>\n'
            'MATERIALS: <MATERIALS>\nEXPORT: GLB, metres, +Y up, standing\n'
            'EXCLUDE: ground plane, props, lettering',
            'subjects': [
                {
                    'SUBJECT': 'two-wheeled wooden handcart',
                    'SIZE': '1.5 m long',
                    'PARTS': 'two spoked wheels, flat plank bed, two shafts',
                    'MATERIALS': 'oak, iron fittings',
                },
                {
                    'SUBJECT': 'oak barrel',
                    'SIZE': '0.9 m tall',
                    'PARTS': 'staves, five hoops, lid',
                    'MATERIALS': 'oak, iron',
                },
                {
                    'SUBJECT': 'plank door in its frame',
                    'SIZE': '2.0 m tall, 0.9 m wide',
                    'PARTS': 'door, frame, two hinges, ring handle',
                    'MATERIALS': 'oak, iron',
                },
                {
                    'SUBJECT': 'iron lantern',
                    'SIZE': '0.3 m tall',
                    'PARTS': 'frame, four glass panes, hinged top, carrying ring',
                    'MATERIALS': 'iron, glass',
                },
            ],
        },
        state_note='The house template with four different subjects poured into it. yes when at '
        'least three of the four pass — the wording is a template, not a lucky prompt.',
    ),
]
