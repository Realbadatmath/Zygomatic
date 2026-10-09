# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""geometry_shared.subjects_animals_nature — SUBJECTS: Animals (10), Nature & weather (14), Built environment (11), Clothing (7).

Verbatim from the former geometry_shared.py, lines 901-1214.
"""

from __future__ import annotations

from .constants import _maps, _mat
from .subjects_people_body import SUBJECTS


SUBJECTS.update(
    {
        # ── Animals (10) — leg count and limb separation are what fail, so the size band is tight ──
        'model_animal_dog': (
            'a dog',
            'One short-haired dog standing on all four legs, head up, tail down, on flat ground. Four legs clearly separate.',
            (1, 8),
            ('max', 0.55, 1.20),
            None,
        ),
        'model_animal_cat': (
            'a cat',
            'One cat standing on all four legs, tail raised, head forward, on flat ground. Four legs clearly separate.',
            (1, 8),
            ('max', 0.35, 0.80),
            None,
        ),
        'model_animal_horse': (
            'a horse',
            'One draught horse standing square on all four legs, head forward, mane and tail as separate geometry, on flat ground.',
            (2, 12),
            ('y', 1.35, 1.85),
            None,
        ),
        'model_animal_cow': (
            'a cow',
            'One dairy cow standing on all four legs with a full udder and two horns, head forward, on flat ground.',
            (1, 12),
            ('y', 1.20, 1.65),
            None,
        ),
        'model_animal_sheep': (
            'a sheep',
            'One woolly sheep standing on all four legs, head down as if grazing, fleece as its own geometry, on flat ground.',
            (1, 10),
            ('y', 0.60, 1.00),
            None,
        ),
        'model_animal_chicken': (
            'a chicken',
            'One hen standing on two legs with a comb, wattles and folded wings, head up, on flat ground.',
            (1, 10),
            ('y', 0.25, 0.55),
            None,
        ),
        'model_animal_bird_flying': (
            'a bird in flight',
            'One gull in flight with both wings spread wide and level, feet tucked, tail fanned, off the ground.',
            (1, 10),
            ('max', 0.90, 1.60),
            [{'check': 'bbox_aspect', 'axis': 'max', 'over': 'y', 'min': 2.0, 'max': 12.0, 'when': 'glb'}],
        ),
        'model_animal_fish': (
            'a fish',
            'One herring with a forked tail, dorsal and pectoral fins as separate geometry, and a visible eye, level and straight.',
            (1, 10),
            ('max', 0.20, 0.40),
            None,
        ),
        'model_animal_insect': (
            'an insect',
            'One honey bee four centimetres long with six legs, two pairs of wings and a segmented body, wings spread.',
            (1, 16),
            ('max', 0.02, 0.08),
            None,
        ),
        'model_creature_invented': (
            'an invented creature',
            'One invented four-legged creature the size of a dog with a long neck, three eyes in a row and a plated back ridge, standing on flat ground.',
            (1, 16),
            ('max', 0.55, 1.40),
            None,
        ),
        # ── Nature & weather (14) — the honest question is whether volumetrics become geometry at all ──
        'model_tree': (
            'a tree',
            'One oak tree eight metres tall with a trunk, four main boughs and a leaf canopy, standing on flat ground. Trunk and canopy separate.',
            (2, 200),
            ('y', 6.00, 11.00),
            None,
        ),
        'model_forest': (
            'a stand of trees',
            'Eight oak trees of differing heights spread over flat ground twenty metres across, none touching another. Each tree a separate object.',
            (8, 400),
            ('max', 15.0, 28.0),
            None,
        ),
        'model_grass_field': (
            'a patch of grass',
            'A patch of flat ground two metres across covered in individual grass blades ten centimetres tall standing as real geometry, not a texture.',
            (1, 5000),
            ('max', 1.60, 2.40),
            None,
        ),
        'model_water_still': (
            'a still water surface',
            'A flat square pond four metres across, the water a level surface two centimetres below a stone kerb. Water and kerb separate.',
            (2, 10),
            ('max', 3.50, 5.00),
            _mat('water'),
        ),
        'model_water_waves': (
            'a choppy water surface',
            'A square of sea four metres across with half-metre choppy waves modelled into the surface, crests and troughs as real geometry.',
            (1, 6),
            ('max', 3.50, 5.00),
            None,
        ),
        'model_water_reflection': (
            'a water surface set up to reflect',
            'A flat square pond four metres across with a stone post standing in the middle of it, the water surface smooth and mirror-flat.',
            (2, 8),
            ('max', 3.50, 5.00),
            [
                {
                    'check': 'pbr_value_range',
                    'field': 'roughness',
                    'shell': 'largest',
                    'min': 0.0,
                    'max': 0.2,
                    'when': 'glb',
                }
            ],
        ),
        'model_rain': (
            'falling rain',
            'Falling rain over a patch of ground two metres across: individual rain streaks as separate thin geometry between two and three metres up.',
            (1, 3000),
            ('y', 1.50, 3.50),
            None,
        ),
        'model_snow': (
            'snow on the ground',
            'A patch of ground two metres across under ten centimetres of settled snow, the snow a separate drifted surface above the ground.',
            (2, 10),
            ('max', 1.60, 2.40),
            None,
        ),
        'model_fire': (
            'a fire',
            'A small wood fire: four crossed logs half a metre across with flame shapes half a metre tall above them. Logs and flames separate.',
            (3, 40),
            ('y', 0.40, 1.20),
            None,
        ),
        'model_smoke': (
            'a column of smoke',
            'A column of smoke rising two metres from a point on the ground, widening as it rises, built as volume geometry.',
            (1, 40),
            ('y', 1.50, 3.00),
            None,
        ),
        'model_fog': (
            'a bank of fog',
            'A bank of fog filling a box four metres across and two metres tall, built as volume geometry above flat ground.',
            (1, 20),
            ('max', 3.00, 5.00),
            None,
        ),
        'model_sky_clouds': (
            'clouds',
            'Three separate cumulus clouds, each about twenty metres across, sitting level at the same height with clear space between them.',
            (3, 60),
            ('max', 30.0, 90.0),
            None,
        ),
        'model_night': (
            'a night scene lit by one lantern',
            'A patch of cobbled ground three metres across at night with one lit lantern standing on it, the lantern as a separate object.',
            (2, 40),
            ('max', 2.50, 4.00),
            None,
        ),
        'model_rock_mountain': (
            'a rocky outcrop',
            'One rocky outcrop four metres tall with layered strata and three loose boulders at its foot, on flat ground. Outcrop and boulders separate.',
            (4, 20),
            ('y', 3.00, 6.00),
            None,
        ),
        # ── Built environment (11) — real-world dimensions are the point, so every bbox band is tight ──
        'model_door': (
            'a door in its frame',
            'One plank door two metres tall and ninety centimetres wide, shut, in a wooden frame, with two iron hinges and a ring handle. Every part separate.',
            (4, 20),
            ('y', 2.00, 2.35),
            [{'check': 'bbox_dims_m', 'axis': 'x', 'min': 0.85, 'max': 1.20, 'when': 'glb'}],
        ),
        'model_window_intact': (
            'an intact window',
            'One wooden window frame a metre tall with four whole glass panes, a sill and a central mullion. Frame, mullion, panes and sill separate.',
            (5, 20),
            ('y', 0.90, 1.35),
            _mat('glass', 'wood'),
        ),
        'model_roof': (
            'a tiled roof',
            'A pitched roof four metres wide at forty degrees, clay pantiles in overlapping courses as separate geometry, with a ridge tile course.',
            (2, 400),
            ('max', 3.50, 5.00),
            None,
        ),
        'model_stairs': (
            'a flight of stairs',
            'A straight flight of eight oak stairs rising to one and a half metres, each tread and riser as separate geometry, with a plain handrail.',
            (9, 40),
            ('y', 1.40, 1.90),
            [{'check': 'mesh_shell_count', 'min': 8, 'max': 60, 'when': 'glb'}],
        ),
        'model_brick_wall': (
            'a brick wall',
            'A brick wall three metres long and two metres tall in stretcher bond, individual bricks as separate geometry, with a mortar course between them.',
            (2, 600),
            ('y', 1.80, 2.30),
            _mat('brick'),
        ),
        'model_timber_frame': (
            'a timber frame',
            'A timber frame bay three metres wide and three tall: two posts, a sill beam, a head beam and two diagonal braces. Each timber separate.',
            (6, 20),
            ('y', 2.70, 3.40),
            [{'check': 'mesh_shell_count', 'min': 6, 'max': 30, 'when': 'glb'}],
        ),
        'model_interior_room': (
            'an interior room',
            'One empty room four metres square and three tall with a plank floor, four plastered walls, a ceiling and one doorway opening.',
            (4, 40),
            ('y', 2.80, 3.60),
            [{'check': 'bbox_dims_m', 'axis': 'max', 'min': 3.60, 'max': 4.80, 'when': 'glb'}],
        ),
        'model_street': (
            'a street',
            'A cobbled street six metres wide and twenty long with a three-storey brick facade down each side. Ground and each facade separate.',
            (3, 200),
            ('max', 18.0, 26.0),
            None,
        ),
        'model_bridge': (
            'an arched bridge',
            'One stone bridge twelve metres long with a single semicircular arch, a parapet on each side and steps at both ends.',
            (3, 200),
            ('max', 10.0, 15.0),
            None,
        ),
        'model_harbour': (
            'a harbour quay',
            'A stone quay twenty metres long with three mooring bollards, a flight of steps down to the water and a flat water surface alongside.',
            (5, 100),
            ('max', 18.0, 28.0),
            None,
        ),
        'model_church': (
            'a church',
            'One brick church twenty-five metres long with a nave, a pitched roof, a west tower thirty metres tall and five arched windows a side.',
            (4, 300),
            ('y', 25.0, 40.0),
            None,
        ),
        # ── Clothing (7) — the test is whether cloth is its own shell, not a painted body ──
        'model_dress_period': (
            'a period dress',
            "One seventeenth-century woman's dress on a standing figure: long skirt, fitted bodice, white collar and cuffs. Each garment piece separate.",
            (3, 20),
            ('y', 1.55, 1.90),
            None,
        ),
        'model_armour': (
            'a suit of armour',
            'One steel breastplate, two pauldrons, two vambraces and a helmet arranged as worn on a standing figure. Each piece separate.',
            (6, 30),
            ('y', 1.55, 2.00),
            _mat('steel'),
        ),
        'model_hat': (
            'a wide-brimmed hat',
            'One wide-brimmed black felt hat forty centimetres across with a tall crown and a band, sitting upright on nothing.',
            (1, 6),
            ('max', 0.32, 0.55),
            None,
        ),
        'model_cloak': (
            'a hanging cloak',
            'One wool cloak hanging from a peg, falling one and a half metres, gathered at the neck by a clasp, with soft folds. Cloak and clasp separate.',
            (2, 8),
            ('y', 1.30, 1.90),
            _mat('wool'),
        ),
        'model_cloth_folds': (
            'draped cloth with folds',
            'One square of heavy linen a metre and a half across, thrown over a plain box, hanging in deep folds. Cloth and box separate.',
            (2, 8),
            ('max', 1.20, 1.80),
            _maps('normal'),
        ),
        'model_layered_clothing': (
            'layered clothing',
            'One standing figure in three layers: a shirt, a waistcoat over it and an open long coat over that. Each layer a separate garment shell.',
            (4, 20),
            ('y', 1.55, 2.00),
            [{'check': 'mesh_shell_count', 'min': 4, 'max': 24, 'when': 'glb'}],
        ),
        'model_footwear_period': (
            'period footwear',
            'One pair of seventeenth-century buckled leather shoes, a left and a right, standing side by side on flat ground, buckles separate.',
            (4, 12),
            ('max', 0.24, 0.45),
            _mat('leather'),
        ),
    }
)
