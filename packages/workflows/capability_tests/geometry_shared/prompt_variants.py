# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""geometry_shared.prompt_variants — Prompt: one base task, one key, one variant per column.

Verbatim from the former geometry_shared.py, lines 2017-2258.
"""

from __future__ import annotations

from .builds_capacity import PROBES, _op, _probe

# ── Prompt: one base task, one key, one variant per column ─────────────────────────────────
# The whole prompt-damage band is measured against ONE base task whose result is mechanically
# decidable: a count (three barrels plus a rope = four shells), a named colour on a named shell,
# and a left/right plus above/below relation. Every variant below is scored against the SAME key,
# so a column's answer is "did this wording still produce the same build", never a taste.
BASE_TASK = (
    'Three oak barrels standing in a row on a stone quay, twenty centimetres apart. '
    'The left barrel is painted red. A coil of rope lies on top of the middle barrel.'
)

BASE_KEY = [
    {'check': 'mesh_shell_count', 'min': 4, 'max': 60, 'when': 'glb'},
    {'check': 'material_basecolour', 'shell': 'barrel_left', 'colour': 'red', 'tolerance': 12, 'when': 'glb'},
    {
        'check': 'bbox_relation',
        'a': 'barrel_left',
        'b': 'barrel_middle',
        'relation': 'left_of',
        'tolerance': 0.05,
        'when': 'glb',
    },
    {
        'check': 'bbox_relation',
        'a': 'rope',
        'b': 'barrel_middle',
        'relation': 'above',
        'tolerance': 0.02,
        'when': 'glb',
    },
    {'check': 'mesh_no_self_intersection', 'max': 0.0, 'when': 'glb'},
    _op(
        'Three barrels in a row on a quay, the LEFT one red, a coil of rope on top of the MIDDLE '
        'one. Is that exactly what this is? yes/no'
    ),
]

BASE_KEY_NOTE = (
    'The key is the same for the base task and every variant: four separate shells, the LEFTMOST '
    'barrel red by material base colour, the rope above the middle barrel by bounding box. The '
    'mechanical checks decide; the operator confirms. A variant whose build still matches the key '
    'is a yes for its column — the wording survived.'
)

VARIANTS = {
    'pd_paraphrase': "On a stone quay stand three oak barrels in a line, a hand's width between them. Red paint "
    'covers the leftmost. Rope, coiled, rests upon the centre barrel.',
    'pd_word_order': 'A coil of rope on top of the middle barrel. Painted red, the left barrel. Twenty '
    'centimetres apart, three oak barrels in a row, standing on a stone quay.',
    'pd_synonym': 'Three oaken casks upright in a line on a stone wharf, twenty centimetres between them. The '
    'leftmost cask is painted crimson. A hank of cordage sits atop the centre cask.',
    'pd_typo': 'Three oka barels standing in a rwo on a stone quya, twenty centimetres apart. The lfet '
    'barel is painted redd. A coil of rope lies on tpo of the middel barrel.',
    'pd_grammar': 'Three oak barrel stand in row on stone quay, twenty centimetre apart. Left barrel are '
    'painted red. Coil of rope is lie on top of middle barrel.',
    'pd_punctuation': 'three oak barrels standing in a row on a stone quay twenty centimetres apart the left '
    'barrel is painted red a coil of rope lies on top of the middle barrel',
    'pd_case': 'THREE OAK BARRELS STANDING IN A ROW ON A STONE QUAY, TWENTY CENTIMETRES APART. THE LEFT '
    'BARREL IS PAINTED RED. A COIL OF ROPE LIES ON TOP OF THE MIDDLE BARREL.',
    'pd_filler': 'So, if you would be so kind, and taking your time over it, what we are after here is, '
    'basically, three oak barrels standing in a row on a stone quay, twenty centimetres apart, '
    'and the left barrel is painted red, and a coil of rope lies on top of the middle barrel, '
    'if that makes sense.',
    'pd_repetition': 'Three oak barrels. Three oak barrels standing in a row on a stone quay, twenty centimetres '
    'apart. Three barrels, oak, in a row. The left barrel is painted red, the left one, red. A '
    'coil of rope lies on top of the middle barrel, on the middle one.',
    'pd_multilingual': 'Drie eiken vaten op een rij op een stenen kade, twintig centimeter uit elkaar. Het '
    'linkervat is rood geverfd. Een rol touw ligt boven op het middelste vat.',
}

PROBES.append(
    _probe(
        'geo_pd_damage',
        'does damaged wording change the build at all',
        ['pd_damage'],
        BASE_KEY + [{'check': 'mesh_similarity_min', 'to': 'geo_pd_base', 'max_cd': 0.08, 'when': 'glb'}],
        {'prompt': BASE_TASK, 'variants': VARIANTS},
        variant_note='Run the base task first, then EVERY variant in `variants`, all on seeds '
        '[11, 12, 13]. pd_damage is the share of variants whose build still matches the '
        'key: yes when at least 8 of the 10 survive, partial at 4-7.',
        state_rule={'yes': 0.8, 'partial': 0.4},
        state_note=BASE_KEY_NOTE,
    )
)

PROBES.append(
    _probe(
        'geo_pd_base',
        'the base task, undamaged (the reference build)',
        ['pd_damage_visible'],
        BASE_KEY
        + [
            {
                'check': 'build_error',
                'terms': ['could not', 'unsupported', 'too complex', 'refus'],
                'expect': False,
                'when': 'report',
            }
        ],
        {'prompt': BASE_TASK},
        state_note='pd_damage_visible asks whether a wording failure is LOUD. Compare each failing '
        'variant against this reference build: a yes needs the tool to either report an '
        'error naming what it could not do, or produce a build whose defect the operator '
        'spots without being told (a missing barrel, no red). A build that is subtly wrong '
        'and reported as a success is a no — that is the silent failure this column names.',
    )
)

for _col, _text in VARIANTS.items():
    PROBES.append(
        _probe(
            'geo_' + _col,
            f'wording: {_col[3:].replace("_", " ")}',
            [_col],
            list(BASE_KEY),
            {'prompt': _text},
            state_note=BASE_KEY_NOTE,
        )
    )
del _col, _text

PROBES += [
    _probe(
        'geo_pd_contradiction',
        'two instructions that cannot both hold',
        ['pd_contradiction'],
        [
            {'check': 'mesh_shell_count', 'min': 1, 'max': 6, 'when': 'glb'},
            {'check': 'bbox_dims_m', 'axis': 'y', 'min': 1.80, 'max': 3.30, 'when': 'glb'},
            _op(
                'The prompt asked for a door two metres tall and, in the next sentence, three metres '
                'tall. Is there exactly ONE door here, at one of those two heights? yes/no'
            ),
        ],
        {'prompt': 'A plank door exactly two metres tall, standing upright. The door is exactly three metres tall.'},
        state_note='A yes is one door at one height (the tool resolved the contradiction); building '
        'two doors, or a 2.5 m average, is a no. Which of the two heights it chose is '
        'recorded in the trial and feeds pd_order_wins.',
    ),
    _probe(
        'geo_pd_negation',
        'what the prompt says NOT to build',
        ['pd_negation'],
        [
            {'check': 'mesh_shell_count', 'min': 1, 'max': 10, 'when': 'glb'},
            {'check': 'bbox_dims_m', 'axis': 'y', 'min': 0.35, 'max': 0.70, 'when': 'glb'},
            {'check': 'mesh_part_names', 'terms': ['leg'], 'when': 'glb'},
            _op(
                'A three-legged stool with NO backrest and NO cushion. Are there exactly three legs, '
                'no back and no cushion? yes/no'
            ),
        ],
        {'prompt': 'A wooden stool with three legs. No backrest. No cushion. Nothing on the seat.'},
        state_note='Three legs and nothing forbidden present. A fourth leg, a back or a cushion is a '
        'no — the negation was read as a mention.',
    ),
    _probe(
        'geo_pd_unstated',
        'what the prompt never mentioned',
        ['pd_unstated'],
        [
            {'check': 'mesh_shell_count', 'min': 1, 'max': 8, 'when': 'glb'},
            _op(
                'A single closed wooden crate, nothing else. Is there ONLY a crate — no ground plane, '
                'no rope, no barrel, no props the prompt did not ask for? yes/no'
            ),
        ],
        {'prompt': 'One closed wooden crate, half a metre on each side, standing on nothing. Nothing else at all.'},
        state_note='Invented extras are the failure. A ground plane counts as an invented extra '
        'here, because the prompt says "standing on nothing".',
    ),
    _probe(
        'geo_pd_bleed',
        'an attribute given to the wrong thing',
        ['pd_bleed'],
        [
            {'check': 'mesh_shell_count', 'min': 2, 'max': 20, 'when': 'glb'},
            {'check': 'material_basecolour', 'shell': 'cloak', 'colour': 'red', 'tolerance': 12, 'when': 'glb'},
            {'check': 'material_basecolour', 'shell': 'bench', 'colour': 'grey', 'tolerance': 15, 'when': 'glb'},
            _op(
                'A red cloak lying on a grey stone bench. Is the cloak red and the bench grey, with '
                'neither colour spread onto the other? yes/no'
            ),
        ],
        {'prompt': 'A bright red wool cloak lying folded on a grey stone bench. Cloak and bench as separate objects.'},
        state_note='The failure is a red bench or a grey cloak. Both base colours are measured; the '
        'operator confirms that the red has not bled across the whole build.',
    ),
    _probe(
        'geo_pd_leak',
        'instruction words appearing in the build',
        ['pd_leak'],
        [
            {
                'check': 'sheet_ocr_absent',
                'terms': [
                    'barrel',
                    'oak',
                    'build',
                    'model',
                    'prompt',
                    'high quality',
                    'detailed',
                    'separate',
                    'geometry',
                    'render',
                ],
                'when': 'sheet',
            },
            {'check': 'mesh_shell_count', 'min': 1, 'max': 20, 'when': 'glb'},
            _op(
                'Is there any writing anywhere on this model? There should be none at all. yes/no — '
                'answer yes only if the model is free of lettering.'
            ),
        ],
        {
            'prompt': 'One oak barrel, high quality, detailed, standing upright on flat ground. Build '
            'it as separate geometry. No text anywhere on the model.'
        },
        state_note='OCR of the turntable sheet must find none of the instruction words; the operator '
        'confirms there is no lettering at all, including letters OCR cannot resolve.',
    ),
    _probe(
        'geo_pd_meta_literal',
        'a bracketed note treated as an instruction',
        ['pd_meta_literal'],
        [
            {'check': 'mesh_shell_count', 'min': 1, 'max': 20, 'when': 'glb'},
            {'check': 'sheet_ocr_absent', 'terms': ['reference', 'photo', 'view', 'team'], 'when': 'sheet'},
            _op(
                'Is this just a wooden barrel — with no photograph, no border, no annotation and no '
                'note built into the model? yes/no'
            ),
        ],
        {
            'prompt': '[reference photo, three-quarter view, for the modelling team] A wooden barrel '
            'ninety centimetres tall with iron hoops.'
        },
        state_note='A yes is a barrel. Building a picture frame, a photo border or the words of the '
        'bracketed note is the literal-meta failure.',
    ),
]
