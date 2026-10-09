# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""glossary_examples.examples_nl_de_fr — the Dutch, German and French half of EXAMPLES."""

from zyg_workflows.arch_assistant_ext.glossary_examples.examples_en import EXAMPLES

EXAMPLES += [
    # ── Dutch ────────────────────────────────────────────────────────────────
    {
        'lang': 'nl',
        'ask': 'bouw een rijtjeshuis van 6 bij 10 meter op C4, twee verdiepingen',
        'calls': [
            {'tool': 'draw_house', 'args': {'cell_from': 'C4', 'cell_to': 'H13', 'storeys': 2, 'style': 'rowhouse'}}
        ],
    },
    {
        'lang': 'nl',
        'ask': 'maak een vloer op de eerste verdieping van C4 tot H13',
        'calls': [{'tool': 'add_slab', 'args': {'cell_from': 'C4', 'cell_to': 'H13', 'storey': 1, 'thickness': 0.22}}],
    },
    {
        'lang': 'nl',
        'ask': 'zet een trap van de begane grond naar de eerste verdieping op E6',
        'calls': [{'tool': 'add_stair', 'args': {'cell': 'E6', 'from_storey': 0, 'to_storey': 1, 'kind': 'straight'}}],
    },
    {
        'lang': 'nl',
        'ask': 'een gracht langs de kade van C40 tot Z40',
        'calls': [{'tool': 'add_canal', 'args': {'cells': ['C40', 'Z40'], 'width': 10, 'depth': 2.5}}],
    },
    {
        'lang': 'nl',
        'ask': 'plaats een molen op de dijk bij AB60',
        'calls': [{'tool': 'add_landmark', 'args': {'kind': 'windmill', 'cell': 'AB60', 'size': 14}}],
    },
    {
        'lang': 'nl',
        'ask': 'een dakgoot en regenpijpen op de schuur',
        'calls': [
            {'tool': 'add_gutters', 'args': {'group': 'schuur'}},
            {'tool': 'add_downpipes', 'args': {'group': 'schuur', 'count': 2}},
        ],
    },
    {'lang': 'nl', 'ask': 'wat betekent "kolom"?', 'calls': [{'tool': 'translate', 'args': {'word': 'kolom'}}]},
    {
        'lang': 'nl',
        'ask': 'plant een rij bomen langs de oprit',
        'calls': [
            {
                'tool': 'plant_trees',
                'args': {'cell_from': 'B18', 'cell_to': 'N18', 'spacing': 5, 'kind': 'tree_deciduous'},
            }
        ],
    },
    {
        'lang': 'nl',
        'ask': 'zet een hek om de tuin',
        'calls': [
            {'tool': 'add_fence', 'args': {'cells': ['C20', 'K20', 'K28', 'C28'], 'kind': 'fence', 'height': 1.8}}
        ],
    },
    {
        'lang': 'nl',
        'ask': 'een zwembad achter de villa',
        'calls': [{'tool': 'add_pool', 'args': {'cell_from': 'N24', 'cell_to': 'U27', 'depth': 1.4}}],
    },
    {'lang': 'nl', 'ask': 'hoe groot is het gebouw?', 'calls': [{'tool': 'bounds', 'args': {'which': 'all'}}]},
    {
        'lang': 'nl',
        'ask': 'zet ramen in de voorgevel, om de drie meter',
        'calls': [
            {
                'tool': 'add_windows',
                'args': {'walls': 'new', 'spacing': 3, 'sides': ['south'], 'width': 1.2, 'height': 1.4, 'sill': 0.9},
            }
        ],
    },
    # ── German ───────────────────────────────────────────────────────────────
    {
        'lang': 'de',
        'ask': 'baue ein Haus mit zwei Geschossen auf C4 bis H13',
        'calls': [
            {'tool': 'draw_house', 'args': {'cell_from': 'C4', 'cell_to': 'H13', 'storeys': 2, 'style': 'modern'}}
        ],
    },
    {
        'lang': 'de',
        'ask': 'setze Fenster in jede zweite Etage',
        'calls': [{'tool': 'add_windows', 'args': {'walls': 'new', 'every_n_storeys': 2}}],
    },
    {
        'lang': 'de',
        'ask': 'eine Treppe vom Erdgeschoss ins erste Obergeschoss',
        'calls': [{'tool': 'add_stair', 'args': {'cell': 'E6', 'from_storey': 0, 'to_storey': 1, 'kind': 'straight'}}],
    },
    {
        'lang': 'de',
        'ask': 'ein Mansarddach auf den Block C4 bis H13',
        'calls': [
            {
                'tool': 'add_roof_special',
                'args': {'cell_from': 'C4', 'cell_to': 'H13', 'storey': 2, 'kind': 'mansard', 'height': 2.4},
            }
        ],
    },
    {
        'lang': 'de',
        'ask': 'was heisst "Dachrinne" auf Englisch?',
        'calls': [{'tool': 'translate', 'args': {'word': 'Dachrinne'}}],
    },
    {
        'lang': 'de',
        'ask': 'stelle einen Kran neben die Baustelle',
        'calls': [
            {
                'tool': 'add_construction_site',
                'args': {'cell_from': 'P4', 'cell_to': 'X12', 'crane': True, 'crane_height': 28},
            }
        ],
    },
    # ── French ───────────────────────────────────────────────────────────────
    {
        'lang': 'fr',
        'ask': 'un escalier du rez-de-chaussee au premier etage en E6',
        'calls': [{'tool': 'add_stair', 'args': {'cell': 'E6', 'from_storey': 0, 'to_storey': 1}}],
    },
    {'lang': 'fr', 'ask': 'que veut dire "toiture" ?', 'calls': [{'tool': 'translate', 'args': {'word': 'toiture'}}]},
    {
        'lang': 'fr',
        'ask': 'un batiment de 4 etages sur C4 a L13',
        'calls': [{'tool': 'draw_box', 'args': {'cell_from': 'C4', 'cell_to': 'L13', 'storeys': 4, 'roof': 'flat'}}],
    },
    # ── the landscape families ───────────────────────────────────────────────
    {
        'ask': 'a whole mountain landscape over A1 to T20',
        'calls': [{'tool': 'compose_landscape', 'args': {'cell_from': 'A1', 'cell_to': 'T20', 'scene': 'alpine'}}],
    },
    {
        'lang': 'nl',
        'ask': 'maak een kustlandschap van A1 tot T20',
        'calls': [{'tool': 'compose_landscape', 'args': {'cell_from': 'A1', 'cell_to': 'T20', 'scene': 'coast'}}],
    },
    {'ask': 'what landscape is already in this drawing?', 'calls': [{'tool': 'describe_landscape', 'args': {}}]},
    {
        'lang': 'nl',
        'ask': 'ik wil zoiets als bergen met een meer, welk landschap is dat?',
        'calls': [{'tool': 'suggest_scene', 'args': {'words': 'bergen met een meer'}}],
    },
    {
        'ask': 'a single snow-capped peak 300 m across at P30',
        'calls': [{'tool': 'add_mountain', 'args': {'centre': 'P30', 'radius': 150, 'height': 220, 'style': 'peak'}}],
    },
    {
        'lang': 'de',
        'ask': 'ein Gebirge mit 5 Gipfeln von A1 bis Z40',
        'calls': [
            {'tool': 'add_mountain_range', 'args': {'cell_from': 'A1', 'cell_to': 'Z40', 'height': 180, 'peaks': 5}}
        ],
    },
    {
        'ask': 'scoop a U-shaped valley 20 m deep from C4 to L40 running along z',
        'calls': [
            {
                'tool': 'add_valley',
                'args': {
                    'cell_from': 'C4',
                    'cell_to': 'L40',
                    'depth': 20,
                    'direction': 'z',
                    'profile': 'u',
                    'floor_width': 4,
                },
            }
        ],
    },
    {
        'lang': 'nl',
        'ask': 'een rivier van C4 via H20 naar M40, 12 m breed',
        'calls': [
            {'tool': 'add_river', 'args': {'cells': ['C4', 'H20', 'M40'], 'width': 12, 'depth': 2, 'meander': 6}}
        ],
    },
    {
        'ask': 'a lake 40 m across at P30',
        'calls': [{'tool': 'add_lake', 'args': {'centre': 'P30', 'radius': 20, 'depth': 3, 'irregularity': 0.3}}],
    },
    {
        'lang': 'de',
        'ask': 'ein Wald von A1 bis T20, Nadelbaume',
        'calls': [
            {
                'tool': 'plant_forest',
                'args': {'cell_from': 'A1', 'cell_to': 'T20', 'density': 0.04, 'mix': 'conifer', 'height': 16},
            }
        ],
    },
    # a block is two OPPOSITE CORNERS: the letter changes as well as the number,
    # or the wood is one metre wide (DV85 -> DV120 is a hedge, not a forest)
    {
        'ask': 'a wood on the slope around DV85, about 40 by 36 metres',
        'calls': [
            {
                'tool': 'plant_forest',
                'args': {'cell_from': 'DV85', 'cell_to': 'FI120', 'density': 0.04, 'mix': 'mixed', 'height': 12},
            }
        ],
    },
    {
        'lang': 'nl',
        'ask': 'een rij populieren langs C4 tot C30',
        'calls': [
            {'tool': 'plant_tree_line', 'args': {'cells': ['C4', 'C30'], 'spacing': 6, 'kind': 'poplar', 'height': 18}}
        ],
    },
    {
        'lang': 'fr',
        'ask': 'une falaise de 15 m de C4 a C30',
        'calls': [{'tool': 'add_cliff', 'args': {'cells': ['C4', 'C30'], 'height': 15, 'depth': 12}}],
    },
    {
        'ask': 'scatter forty boulders over A1 to T20',
        'calls': [{'tool': 'scatter_rocks', 'args': {'cell_from': 'A1', 'cell_to': 'T20', 'count': 40, 'size': 1.5}}],
    },
    {
        'ask': 'a coast from A1 to T20 with the sea to the north',
        'calls': [{'tool': 'make_coast', 'args': {'cell_from': 'A1', 'cell_to': 'T20', 'sea_side': 'north'}}],
    },
    {
        'lang': 'nl',
        'ask': 'een eiland met een strand, straal 40 m, op P30',
        'calls': [{'tool': 'add_island', 'args': {'centre': 'P30', 'radius': 40, 'height': 6, 'beach': 6}}],
    },
    {
        'lang': 'nl',
        'ask': 'een polder met gras van A1 tot T20',
        'calls': [
            {
                'tool': 'make_polder',
                'args': {'cell_from': 'A1', 'cell_to': 'T20', 'ditch_width': 3, 'crop': 'grass', 'depth': 1.2},
            }
        ],
    },
    {
        'lang': 'de',
        'ask': 'eine Wiese mit Blumen von C4 bis L13',
        'calls': [{'tool': 'add_meadow', 'args': {'cell_from': 'C4', 'cell_to': 'L13', 'flowers': 200}}],
    },
]
