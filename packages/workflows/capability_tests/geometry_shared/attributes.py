# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""geometry_shared.attributes — Attributes: colour from the exported material, size from the bbox in metres.

Verbatim from the former geometry_shared.py, lines 1832-2016.
"""

from __future__ import annotations

from .builds_capacity import PROBES, _op, _probe

# ── Attributes: colour from the exported material, size from the bbox in metres ─────────────
ATTR_NOTE = (
    'An attribute is read from the EXPORT, not from a render: colour from the material base '
    'colour (CIEDE2000 against the named colour), material from material names plus the PBR '
    'values a renderer would actually use, size from the bbox in metres. A build that looks right '
    'in a preview but ships an untextured grey mesh with the colour baked into a render is a no.'
)


def _attr(pid, col, prompt, checks, question, shells=(1, 20)):
    return _probe(
        pid,
        f'attribute: {col[3:].replace("_", " ")}',
        [col],
        [{'check': 'mesh_shell_count', 'min': shells[0], 'max': shells[1], 'when': 'glb'}] + checks + [_op(question)],
        {'prompt': prompt},
        attr_note=ATTR_NOTE,
    )


PROBES += [
    _attr(
        'geo_at_colour_named',
        'at_colour_named',
        'One oak barrel painted bright red all over, standing upright on flat ground. Nothing else.',
        [{'check': 'material_basecolour', 'shell': 'largest', 'colour': 'red', 'tolerance': 12, 'when': 'glb'}],
        'Is the barrel RED? yes/no',
    ),
    _attr(
        'geo_at_colour_two',
        'at_colour_two',
        'One oak barrel painted red standing beside one wooden crate painted blue, half a metre '
        'apart on flat ground. Barrel and crate separate.',
        [
            {'check': 'material_basecolour', 'shell': 'barrel', 'colour': 'red', 'tolerance': 12, 'when': 'glb'},
            {'check': 'material_basecolour', 'shell': 'crate', 'colour': 'blue', 'tolerance': 12, 'when': 'glb'},
            {'check': 'material_count_min', 'min': 2, 'when': 'glb'},
        ],
        'Is the barrel RED and the crate BLUE — that way round, not swapped and not both one colour? yes/no',
        shells=(2, 20),
    ),
    _attr(
        'geo_at_material',
        'at_material',
        "One ship's anchor of bare wrought iron, one and a half metres tall, standing on flat ground. Nothing else.",
        [
            {'check': 'material_names_present', 'terms': ['iron'], 'when': 'glb'},
            {
                'check': 'pbr_value_range',
                'field': 'metallic',
                'shell': 'largest',
                'min': 0.6,
                'max': 1.0,
                'when': 'glb',
            },
            {
                'check': 'pbr_value_range',
                'field': 'roughness',
                'shell': 'largest',
                'min': 0.25,
                'max': 0.8,
                'when': 'glb',
            },
        ],
        'Does this read as IRON — metal, not painted wood or plastic? yes/no',
    ),
    _attr(
        'geo_at_texture',
        'at_texture',
        'One rough-sawn oak plank two metres long, lying flat, the saw marks and grain cut into the '
        'surface. Nothing else.',
        [
            {'check': 'pbr_maps_present', 'maps': ['basecolour', 'normal', 'roughness'], 'when': 'glb'},
            {'check': 'has_uv', 'overlap': 0.1, 'when': 'glb'},
        ],
        'Can you see rough-sawn wood grain on the surface, rather than a flat even colour? yes/no',
    ),
    _attr(
        'geo_at_age_object',
        'at_age_object',
        'Two oak barrels side by side on flat ground: the left one brand new with clean pale staves, '
        'the right one old with grey split staves and rusted hoops. Two separate barrels.',
        [
            {'check': 'material_count_min', 'min': 2, 'when': 'glb'},
            {
                'check': 'pbr_value_range',
                'field': 'roughness',
                'shell': 'barrel_old',
                'min': 0.55,
                'max': 1.0,
                'when': 'glb',
            },
            {
                'check': 'pbr_value_range',
                'field': 'roughness',
                'shell': 'barrel_new',
                'min': 0.0,
                'max': 0.55,
                'when': 'glb',
            },
        ],
        'Is the LEFT barrel clearly newer than the right one? yes/no',
        shells=(2, 40),
    ),
    _attr(
        'geo_at_size',
        'at_size',
        'One plank door exactly two metres tall and ninety centimetres wide, standing upright on '
        'flat ground. Nothing else.',
        [
            {'check': 'bbox_dims_m', 'axis': 'y', 'min': 1.80, 'max': 2.20, 'when': 'glb'},
            {'check': 'bbox_dims_m', 'axis': 'x', 'min': 0.81, 'max': 0.99, 'when': 'glb'},
        ],
        'Does this door look like a real two-metre door beside a person, not a model of one? yes/no',
        shells=(1, 30),
    ),
    _attr(
        'geo_at_state',
        'at_state',
        'One plank door in its frame, standing open at forty-five degrees on two hinges, the opening '
        'behind it clear. Door, frame and hinges separate.',
        [
            {
                'check': 'bbox_relation',
                'a': 'door',
                'b': 'frame',
                'relation': 'apart',
                'tolerance': 0.15,
                'when': 'glb',
            },
            {'check': 'mesh_no_self_intersection', 'max': 0.0, 'when': 'glb'},
        ],
        'Is the door OPEN — swung clear of its frame with the gap visible behind it? yes/no',
        shells=(2, 30),
    ),
    _attr(
        'geo_at_wet_dry',
        'at_wet_dry',
        'Two stone flags side by side on flat ground: the left one dry, the right one soaked wet '
        'with a thin film of water on it. Flags and water film separate.',
        [
            {
                'check': 'pbr_value_range',
                'field': 'roughness',
                'shell': 'flag_dry',
                'min': 0.5,
                'max': 1.0,
                'when': 'glb',
            },
            {
                'check': 'pbr_value_range',
                'field': 'roughness',
                'shell': 'flag_wet',
                'min': 0.0,
                'max': 0.3,
                'when': 'glb',
            },
        ],
        'Is the RIGHT flag visibly wet and the left one dry? yes/no',
        shells=(2, 20),
    ),
    _attr(
        'geo_at_clean_dirty',
        'at_clean_dirty',
        'Two linen shirts hanging side by side from pegs: the left one clean and white, the right '
        'one filthy with mud and soot. Two separate garments.',
        [
            {'check': 'material_count_min', 'min': 2, 'when': 'glb'},
            {'check': 'pbr_maps_present', 'maps': ['basecolour'], 'when': 'glb'},
        ],
        'Is the RIGHT shirt visibly dirty and the left one clean? yes/no',
        shells=(2, 20),
    ),
    _attr(
        'geo_at_emotion',
        'at_emotion',
        'One adult human head and neck, no hair, with a clearly angry expression: brows down and '
        'drawn together, mouth set hard. Nothing else.',
        [{'check': 'bbox_dims_m', 'axis': 'y', 'min': 0.20, 'max': 0.32, 'when': 'glb'}],
        'Does this face look ANGRY rather than blank? yes/no',
        shells=(1, 10),
    ),
]
