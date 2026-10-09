# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""geometry_shared.subjects_food_damage — SUBJECTS: Food (12) and Damage & wear (18).

Verbatim from the former geometry_shared.py, lines 438-681.
"""

from __future__ import annotations

from .constants import _mat
from .subjects_people_body import SUBJECTS


SUBJECTS.update(
    {
        # ── Food (12) ──
        'model_food_present': (
            'food on a board',
            'A plain wooden board with a wedge of cheese, an onion and a crust of bread on it. Board and each item separate.',
            (4, 12),
            ('max', 0.25, 0.60),
            None,
        ),
        'model_food_bread': (
            'a loaf of bread',
            'One round rye loaf with a slashed crust, twenty-five centimetres across, resting on nothing. One object.',
            (1, 3),
            ('max', 0.18, 0.35),
            None,
        ),
        'model_food_fruit': (
            'three apples',
            'Three apples with stalks, each about eight centimetres across, lying in a row and not touching. Three separate objects.',
            (3, 6),
            ('max', 0.22, 0.45),
            None,
        ),
        'model_food_vegetables': (
            'root vegetables',
            'Two carrots with cut tops and one turnip, lying side by side on flat ground, not touching. Three separate objects.',
            (3, 6),
            ('max', 0.18, 0.40),
            None,
        ),
        'model_food_meat_raw': (
            'a raw joint of meat',
            'One raw joint of beef on the bone, cut face exposed, lying on a plain wooden board. Meat and board separate.',
            (2, 5),
            ('max', 0.25, 0.50),
            None,
        ),
        'model_food_meat_cooked': (
            'a roasted bird',
            'One roasted goose, browned and trussed with string, lying on a plain pewter dish. Bird and dish separate.',
            (2, 8),
            ('max', 0.30, 0.60),
            None,
        ),
        'model_food_fish': (
            'a whole fish',
            'One whole herring with scales, fins and a visible eye, lying flat on a plain wooden board. Fish and board separate.',
            (2, 5),
            ('max', 0.22, 0.45),
            None,
        ),
        'model_food_soup': (
            'a bowl of soup',
            'One earthenware bowl filled with soup to two centimetres below the rim, the liquid surface as its own geometry. Bowl and liquid separate.',
            (2, 4),
            ('max', 0.14, 0.30),
            [
                {
                    'check': 'bbox_relation',
                    'a': 'smallest',
                    'b': 'largest',
                    'relation': 'inside',
                    'tolerance': 0.02,
                    'when': 'glb',
                }
            ],
        ),
        'model_food_plated': (
            'a plated meal',
            'One pewter plate with a slice of meat, three boiled potatoes and a spoon laid beside it. Plate, meat, each potato and spoon separate.',
            (6, 14),
            ('max', 0.22, 0.45),
            None,
        ),
        'model_food_drink': (
            'a filled drinking vessel',
            'One pewter tankard filled with beer to two centimetres below the rim, a head of foam on the surface. Tankard, beer and foam separate.',
            (3, 6),
            ('y', 0.10, 0.25),
            None,
        ),
        'model_food_table': (
            'a laid table',
            'A plain oak table one and a half metres long with two pewter plates, two tankards and a bread loaf on it. Every item separate.',
            (6, 20),
            ('max', 1.20, 2.00),
            [{'check': 'bbox_dims_m', 'axis': 'y', 'min': 0.65, 'max': 0.95, 'when': 'glb'}],
        ),
        'model_food_spoiled': (
            'spoiled food',
            'One half-eaten loaf with furry mould patches and a burst rotten apple beside it, on a plain board. Loaf, apple and board separate.',
            (3, 10),
            ('max', 0.20, 0.45),
            None,
        ),
        # ── Damage & wear (18) ──
        'model_broken_wood': (
            'a snapped plank',
            'One oak plank one metre long, snapped in two across the middle, the two pieces lying apart with splintered ends. Two separate pieces.',
            (2, 12),
            ('max', 0.80, 1.40),
            [{'check': 'mesh_shell_count', 'min': 2, 'max': 20, 'when': 'glb'}],
        ),
        'model_broken_glass': (
            'a shattered glass and its shards',
            'One broken drinking glass with the bowl cracked away and five shards lying beside it on flat ground. Glass and each shard separate.',
            (5, 20),
            ('max', 0.12, 0.35),
            None,
        ),
        'model_broken_window': (
            'a broken window',
            'A wooden window frame with four lights, two panes missing, glass shards in the rebate and three shards on the sill. Frame, panes and shards separate.',
            (6, 30),
            ('y', 0.70, 1.50),
            [{'check': 'mesh_shell_count', 'min': 6, 'max': 40, 'when': 'glb'}],
        ),
        'model_broken_pottery': (
            'a smashed pot',
            'One earthenware pot smashed into six pieces lying on flat ground, the pieces curved with sharp edges. Six separate pieces.',
            (5, 15),
            ('max', 0.20, 0.50),
            None,
        ),
        'model_cracked_wall': (
            'a cracked plaster wall',
            'A plaster wall panel two metres wide with a jagged crack running from the top to halfway down, the crack cut into the geometry.',
            (1, 6),
            ('max', 1.60, 2.40),
            None,
        ),
        'model_torn_cloth': (
            'a torn cloth',
            'One square of linen cloth a metre across, hanging from a rod, with a long tear from the bottom edge halfway up and the edges parted.',
            (2, 6),
            ('max', 0.80, 1.40),
            _mat('linen', 'cloth'),
        ),
        'model_frayed_rope': (
            'a frayed rope end',
            'One hemp rope two centimetres thick and a metre long, lying straight, with one end unlaid into three frayed strands.',
            (1, 8),
            ('max', 0.80, 1.30),
            None,
        ),
        'model_rust': (
            'a rusted iron object',
            'One iron hinge thirty centimetres long, heavily rusted, the surface pitted and scaling, lying flat.',
            (1, 4),
            ('max', 0.22, 0.45),
            [
                {
                    'check': 'pbr_value_range',
                    'field': 'roughness',
                    'shell': 'largest',
                    'min': 0.55,
                    'max': 1.0,
                    'when': 'glb',
                }
            ],
        ),
        'model_rot': (
            'a rotten timber',
            'One oak post half a metre long, rotten at one end, the rotten end soft and eaten away with the grain crumbling.',
            (1, 6),
            ('max', 0.40, 0.70),
            None,
        ),
        'model_burnt': (
            'a burnt beam',
            'One oak beam a metre long, charred black over half its length, the charred surface cracked into a scaly pattern.',
            (1, 4),
            ('max', 0.80, 1.30),
            None,
        ),
        'model_stain': (
            'a stained cloth',
            'One square of linen cloth a metre across, laid flat, with a dark irregular wine stain covering a quarter of it.',
            (1, 3),
            ('max', 0.80, 1.30),
            [{'check': 'pbr_maps_present', 'maps': ['basecolour'], 'when': 'glb'}],
        ),
        'model_mud': (
            'a muddy boot',
            'One leather boot, mud caked on the sole and splashed up the side, standing upright on flat ground.',
            (1, 6),
            ('y', 0.20, 0.45),
            None,
        ),
        'model_patina': (
            'a patinated bronze object',
            'One bronze bell thirty centimetres tall, green patina in the recesses and bright metal on the high points, standing upright.',
            (1, 4),
            ('y', 0.22, 0.45),
            _mat('bronze'),
        ),
        'model_blood': (
            'a blood-stained cloth',
            'One square of linen cloth half a metre across, laid flat, with a dark red bloodstain spreading from one corner.',
            (1, 3),
            ('max', 0.40, 0.70),
            None,
        ),
        'model_scar': (
            'a scarred forearm',
            'One bare adult forearm and hand, cut flat at the elbow, a raised healed scar running ten centimetres along the inner forearm.',
            (1, 4),
            ('max', 0.35, 0.60),
            None,
        ),
        'model_dent': (
            'a dented metal vessel',
            'One pewter tankard twenty centimetres tall with three deep dents pushed into one side, standing upright.',
            (1, 4),
            ('y', 0.14, 0.28),
            None,
        ),
        'model_peeling_paint': (
            'peeling paint on a door',
            'One painted wooden door two metres tall, the green paint peeling away in curled flakes over the lower half, bare wood beneath.',
            (1, 40),
            ('y', 1.80, 2.20),
            None,
        ),
        'model_wet_surface': (
            'a wet cobbled ground',
            'A patch of cobbled ground two metres across, wet, with three shallow puddles as separate flat water surfaces above the stones.',
            (2, 30),
            ('max', 1.60, 2.40),
            [
                {
                    'check': 'pbr_value_range',
                    'field': 'roughness',
                    'shell': 'smallest',
                    'min': 0.0,
                    'max': 0.35,
                    'when': 'glb',
                }
            ],
        ),
    }
)
