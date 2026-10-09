# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""glossary_examples.examples_en — the English half of EXAMPLES (every family, >= 2 each).

The list is opened here and extended in place by examples_nl_de_fr; both halves are the
original lines unchanged, only the bracket that closed the literal moved.
"""

# ── worked examples: every family, four languages ────────────────────────────
EXAMPLES = [
    # glossary_examples (this family)
    {'ask': 'what does "gevel" mean?', 'calls': [{'tool': 'translate', 'args': {'word': 'gevel'}}]},
    {'ask': 'how do I ask you for a roof?', 'calls': [{'tool': 'explain', 'args': {'topic': 'roofs'}}]},
    {'ask': 'the building should be 30 feet high', 'calls': [{'tool': 'units', 'args': {'text': '30 feet'}}]},
    # ground_v3 — the one sculpted ground, and shaping it
    {
        'ask': 'lay the ground over the whole site first, A1 to CV200, rolling country',
        'calls': [
            {'tool': 'make_ground', 'args': {'cell_from': 'A1', 'cell_to': 'CV200', 'style': 'rolling', 'seed': 3}}
        ],
    },
    {
        'ask': 'raise a 90 m peak on the block K20 to CG116',
        'calls': [
            {'tool': 'raise_ground', 'args': {'cell_from': 'K20', 'cell_to': 'CG116', 'height': 90, 'shape': 'peak'}}
        ],
    },
    {
        'ask': 'dig a valley 25 m deep from A60 to EL90 for the river to run down',
        'calls': [
            {'tool': 'lower_ground', 'args': {'cell_from': 'A60', 'cell_to': 'EL90', 'depth': 25, 'shape': 'valley'}}
        ],
    },
    {
        'lang': 'nl',
        'ask': 'maak de bouwplaats D40 tot N50 vlak voor de boerderij',
        'calls': [{'tool': 'level_ground', 'args': {'cell_from': 'D40', 'cell_to': 'N50'}}],
    },
    {'lang': 'de', 'ask': 'wie hoch wird das Gelände?', 'calls': [{'tool': 'describe_ground', 'args': {}}]},
    # water_v3 — a bed cut into that ground, with water on it
    {
        'ask': 'fill a lake 60 m across in the bottom of the valley at BF75',
        'calls': [{'tool': 'fill_lake', 'args': {'centre': 'BF75', 'radius': 30, 'depth': 4, 'irregularity': 0.3}}],
    },
    {
        'lang': 'fr',
        'ask': "creuse une riviere de 10 m de large de B2 par E30 jusqu'a J60",
        'calls': [{'tool': 'carve_river', 'args': {'cells': ['B2', 'E30', 'J60'], 'width': 10, 'depth': 2}}],
    },
    {
        'ask': 'put the sea along the west edge, A1 to L60',
        'calls': [{'tool': 'fill_sea', 'args': {'cell_from': 'A1', 'cell_to': 'L60', 'depth': 8}}],
    },
    # base tools
    {
        'ask': 'build 10 by 10 squares, 5 storeys, starting at C4',
        'calls': [{'tool': 'draw_box', 'args': {'cell_from': 'C4', 'cell_to': 'L13', 'storeys': 5, 'roof': 'flat'}}],
    },
    {
        'ask': 'glass windows on every second floor of what you just drew',
        'calls': [{'tool': 'add_windows', 'args': {'walls': 'new', 'every_n_storeys': 2, 'material': 'mat_glass'}}],
    },
    {
        'ask': 'a front door in the middle of wall o3',
        'calls': [
            {
                'tool': 'add_opening',
                'args': {'wall_id': 'o3', 'kind': 'door', 'at': 'middle', 'width': 0.9, 'height': 2.1},
            }
        ],
    },
    # assets_search
    {
        'ask': 'find me a bicycle rack in the asset packs',
        'calls': [{'tool': 'search_assets', 'args': {'query': 'bicycle rack', 'limit': 5}}],
    },
    {
        'ask': 'put an oak tree asset on H12',
        'calls': [{'tool': 'place_asset', 'args': {'query_or_id': 'oak tree', 'cell': 'H12', 'scale': 1.2}}],
    },
    {
        'ask': 'line lamp assets along D4, E4 and F4',
        'calls': [
            {'tool': 'place_assets_along', 'args': {'cells': ['D4', 'E4', 'F4'], 'query': 'street lamp', 'spacing': 4}}
        ],
    },
    {'ask': 'which asset packs are installed?', 'calls': [{'tool': 'list_asset_packs', 'args': {'limit': 20}}]},
    # balconies_facade
    {
        'ask': 'balconies on every second floor of the new block, 3 m wide',
        'calls': [{'tool': 'add_balconies', 'args': {'walls': 'new', 'every_n_storeys': 2, 'width': 3, 'depth': 1.4}}],
    },
    {
        'ask': 'a 1 m parapet around the roof of the group "office"',
        'calls': [{'tool': 'add_parapet', 'args': {'group': 'office', 'height': 1.0, 'cap': True}}],
    },
    {
        'ask': 'a canopy over the entrance in wall o12',
        'calls': [
            {
                'tool': 'add_canopy',
                'args': {'wall_id': 'o12', 'at': 'middle', 'width': 2.4, 'depth': 1.2, 'kind': 'canopy'},
            }
        ],
    },
    {
        'ask': 'put a cornice line on every second storey of "office"',
        'calls': [
            {
                'tool': 'add_facade_bands',
                'args': {'group': 'office', 'every_n_storeys': 2, 'kind': 'cornice', 'depth': 0.15},
            }
        ],
    },
    # blender_power
    {
        'ask': 'render the drawing in Blender from above',
        'calls': [{'tool': 'blender_render', 'args': {'view': 'top', 'engine': 'eevee', 'width': 1280, 'height': 720}}],
    },
    {
        'ask': 'export the model as a glb file',
        'calls': [{'tool': 'blender_export', 'args': {'format': 'glb', 'name': 'row houses'}}],
    },
    {'ask': 'how many polygons is the built mesh?', 'calls': [{'tool': 'blender_measure', 'args': {}}]},
    # civil_infrastructure
    {
        'ask': 'a beam bridge from B20 to M20, 8 m wide, piers every 10 m',
        'calls': [
            {
                'tool': 'draw_bridge',
                'args': {'cell_from': 'B20', 'cell_to': 'M20', 'width': 8, 'kind': 'beam', 'piers_every': 10},
            }
        ],
    },
    {
        'ask': 'a quay wall along C30 to H30',
        'calls': [{'tool': 'draw_quay', 'args': {'cells': ['C30', 'D30', 'E30', 'F30', 'G30', 'H30'], 'height': 2.5}}],
    },
    {
        'ask': 'a road tunnel from A40 to N40',
        'calls': [{'tool': 'draw_tunnel', 'args': {'cell_from': 'A40', 'cell_to': 'N40', 'width': 7, 'height': 5}}],
    },
    # curved_walls
    {
        'ask': 'a curved glass wall around F8, radius 7, half a circle',
        'calls': [
            {
                'tool': 'draw_curved_wall',
                'args': {'centre': 'F8', 'radius': 7, 'start_deg': 0, 'end_deg': 180, 'material': 'mat_glass'},
            }
        ],
    },
    {
        'ask': 'a round brick tower on P30, 5 m across, 4 storeys, dome on top',
        'calls': [
            {
                'tool': 'draw_round_tower',
                'args': {'centre': 'P30', 'radius': 2.5, 'storeys': 4, 'roof': 'dome', 'material': 'mat_brick'},
            }
        ],
    },
    {
        'ask': 'a wall that curves from D10 through F8 to H10',
        'calls': [{'tool': 'draw_wall_through', 'args': {'cell_a': 'D10', 'cell_b': 'F8', 'cell_c': 'H10'}}],
    },
    # editing_ops
    {'ask': 'move the new walls two cells east', 'calls': [{'tool': 'move', 'args': {'which': 'new', 'dx_cells': 2}}]},
    {
        'ask': 'repeat the shed five times, three cells apart',
        'calls': [{'tool': 'array', 'args': {'which': 'shed', 'count': 5, 'step_x_cells': 3}}],
    },
    {
        'ask': 'turn the garage a quarter turn',
        'calls': [{'tool': 'rotate', 'args': {'which': 'garage', 'degrees': 90}}],
    },
    {
        'ask': 'make the tower ten storeys instead of six',
        'calls': [{'tool': 'set_height', 'args': {'which': 'tower', 'storeys': 10}}],
    },
    # furniture_kitchen_bath
    {
        'ask': 'fit a kitchen with an island in C4 to F7',
        'calls': [
            {'tool': 'furnish_kitchen', 'args': {'cell_from': 'C4', 'cell_to': 'F7', 'island': True, 'side': 'north'}}
        ],
    },
    {
        'ask': 'a bathroom with a bath and a shower in G4 to H6 on the first floor',
        'calls': [
            {
                'tool': 'furnish_bathroom',
                'args': {'cell_from': 'G4', 'cell_to': 'H6', 'storey': 1, 'bath': True, 'shower': True},
            }
        ],
    },
    {
        'ask': 'a utility room with the washing machine and boiler in J4 to K6',
        'calls': [{'tool': 'add_utility', 'args': {'cell_from': 'J4', 'cell_to': 'K6', 'side': 'east'}}],
    },
    # furniture_living
    {
        'ask': 'furnish D10 to G13 as a living room with the door on the south',
        'calls': [
            {
                'tool': 'furnish_room',
                'args': {'cell_from': 'D10', 'cell_to': 'G13', 'room': 'living', 'door_side': 'south'},
            }
        ],
    },
    {
        'ask': 'a dining set for six on K8',
        'calls': [{'tool': 'place_furniture_set', 'args': {'cell': 'K8', 'set': 'dining_6'}}],
    },
    # interior_rooms
    {
        'ask': 'split the ground floor of C4 to L13 into 3 by 2 rooms with a corridor',
        'calls': [
            {
                'tool': 'subdivide_floor',
                'args': {
                    'cell_from': 'C4',
                    'cell_to': 'L13',
                    'cols': 3,
                    'rows': 2,
                    'storey': 0,
                    'corridor': 'x',
                    'doors': True,
                },
            }
        ],
    },
    {
        'ask': 'a 1.5 m corridor along the first floor from D5 to K5',
        'calls': [
            {
                'tool': 'add_corridor',
                'args': {'cell_from': 'D5', 'cell_to': 'K5', 'storey': 1, 'width': 1.5, 'direction': 'x'},
            }
        ],
    },
    {
        'ask': 'a suspended ceiling over the office floor',
        'calls': [
            {
                'tool': 'add_ceiling',
                'args': {'cell_from': 'C4', 'cell_to': 'L13', 'storey': 0, 'kind': 'suspended_ceiling', 'tiles': True},
            }
        ],
    },
    # landmarks_special
    {
        'ask': 'a lighthouse at the end of the pier on Z40',
        'calls': [{'tool': 'add_landmark', 'args': {'kind': 'lighthouse', 'cell': 'Z40', 'size': 12}}],
    },
    {
        'ask': 'a water tower next to the farm',
        'calls': [{'tool': 'add_landmark', 'args': {'kind': 'water_tower', 'cell': 'S22', 'size': 18}}],
    },
    # massing_morph
    {
        'ask': 'a 20-storey tapering massing block on C4 to L13',
        'calls': [
            {
                'tool': 'draw_massing',
                'args': {'cell_from': 'C4', 'cell_to': 'L13', 'storeys': 20, 'style': 'taper', 'amount': 0.4},
            }
        ],
    },
    {
        'ask': 'give the tower a slight twist',
        'calls': [{'tool': 'morph', 'args': {'which': 'new', 'op': 'twist', 'amount': 0.3}}],
    },
    # measure_analyse
    {'ask': 'how far is it from C4 to L13?', 'calls': [{'tool': 'measure', 'args': {'cell_a': 'C4', 'cell_b': 'L13'}}]},
    {'ask': 'what is the floor area of the house?', 'calls': [{'tool': 'floor_area', 'args': {'which': 'house'}}]},
    {'ask': 'give me a bill of materials for everything', 'calls': [{'tool': 'bom', 'args': {'which': 'all'}}]},
    # mep_services
    {
        'ask': 'solar panels on the roof of the warehouse',
        'calls': [{'tool': 'add_solar', 'args': {'group': 'warehouse', 'rows': 4, 'cols': 10, 'tilt': 25}}],
    },
    {
        'ask': 'gutters and downpipes on the row houses',
        'calls': [
            {'tool': 'add_gutters', 'args': {'group': 'row houses'}},
            {'tool': 'add_downpipes', 'args': {'group': 'row houses', 'count': 4}},
        ],
    },
    {
        'ask': 'a chimney on the north side of the farmhouse',
        'calls': [{'tool': 'add_chimney', 'args': {'group': 'farmhouse', 'side': 'north', 'height': 2.0}}],
    },
    # openings_special
    {
        'ask': 'arched windows on the new church walls',
        'calls': [
            {
                'tool': 'add_special_openings',
                'args': {'walls': 'new', 'kind': 'window_arch', 'per_wall': 4, 'width': 1.2, 'height': 2.4},
            }
        ],
    },
    {
        'ask': 'a glass curtain wall on the front of the tower',
        'calls': [
            {'tool': 'add_curtain_wall', 'args': {'walls': 'new', 'mullion': 1.5, 'transom': 2.7, 'storeys': 10}}
        ],
    },
    {
        'ask': 'a garage door in wall o8',
        'calls': [{'tool': 'add_garage', 'args': {'wall_id': 'o8', 'width': 2.6, 'height': 2.2, 'panels': 4}}],
    },
    # polygon_footprints
    {
        'ask': 'a building on the footprint C4, H4, H10, C10',
        'calls': [
            {
                'tool': 'draw_polygon_building',
                'args': {'cells': ['C4', 'H4', 'H10', 'C10'], 'storeys': 3, 'roof': 'flat'},
            }
        ],
    },
    {
        'ask': 'an L-shaped house on C4 to L13 with the notch H9 to L13',
        'calls': [
            {
                'tool': 'draw_l_building',
                'args': {'cell_from': 'C4', 'cell_to': 'L13', 'notch_from': 'H9', 'notch_to': 'L13', 'storeys': 2},
            }
        ],
    },
    {
        'ask': 'a hexagonal pavilion around M20',
        'calls': [
            {
                'tool': 'draw_regular_building',
                'args': {'centre': 'M20', 'sides': 6, 'radius': 5, 'storeys': 1, 'roof': 'pyramid'},
            }
        ],
    },
    # roofs_advanced
    {
        'ask': 'a mansard roof on C4 to L13 at storey 2',
        'calls': [
            {
                'tool': 'add_roof_special',
                'args': {
                    'cell_from': 'C4',
                    'cell_to': 'L13',
                    'storey': 2,
                    'kind': 'mansard',
                    'height': 2.6,
                    'overhang': 0.4,
                },
            }
        ],
    },
    {
        'ask': 'four skylights in the new roof',
        'calls': [{'tool': 'add_skylights', 'args': {'roof': 'new', 'count': 4, 'w': 1.2, 'd': 0.8}}],
    },
    # site_landscape
    {
        'ask': 'a row of trees from B18 to N18',
        'calls': [
            {
                'tool': 'plant_trees',
                'args': {'cell_from': 'B18', 'cell_to': 'N18', 'spacing': 6, 'kind': 'tree_deciduous', 'height': 7},
            }
        ],
    },
    {
        'ask': 'a 6 m asphalt road from A30 to T30',
        'calls': [{'tool': 'add_road', 'args': {'cells': ['A30', 'T30'], 'width': 6, 'material': 'mat_asphalt'}}],
    },
    {
        'ask': 'parking bays behind the shop',
        'calls': [
            {
                'tool': 'add_parking',
                'args': {'cell_from': 'P14', 'cell_to': 'X20', 'bay_w': 2.5, 'bay_d': 5, 'direction': 'x'},
            }
        ],
    },
    # stairs_vertical
    {
        'ask': 'a straight stair from the ground floor to the first floor at E6',
        'calls': [
            {
                'tool': 'add_stair',
                'args': {'cell': 'E6', 'from_storey': 0, 'to_storey': 1, 'kind': 'straight', 'width': 1.0},
            }
        ],
    },
    {
        'ask': 'a lift from the ground floor to the tenth at F6',
        'calls': [{'tool': 'add_elevator', 'args': {'cell': 'F6', 'from_storey': 0, 'to_storey': 10, 'car': True}}],
    },
    # structure_frames
    {
        'ask': 'a column grid every 6 m in C4 to L13, three storeys',
        'calls': [
            {
                'tool': 'add_column_grid',
                'args': {
                    'cell_from': 'C4',
                    'cell_to': 'L13',
                    'spacing_x': 6,
                    'spacing_z': 6,
                    'storeys': 3,
                    'kind': 'column_round',
                },
            }
        ],
    },
    {
        'ask': 'steel portal frames in the warehouse, four of them',
        'calls': [
            {
                'tool': 'add_portal_frames',
                'args': {'cell_from': 'C4', 'cell_to': 'X20', 'count': 4, 'direction': 'x', 'eaves': 6, 'rise': 1.5},
            }
        ],
    },
    {
        'ask': 'a pergola over the terrace D20 to H24',
        'calls': [{'tool': 'add_pergola', 'args': {'cell_from': 'D20', 'cell_to': 'H24', 'height': 2.4, 'post': 0.12}}],
    },
    # terrain
    {
        'ask': 'gentle hills over the site A1 to AZ60',
        'calls': [
            {
                'tool': 'make_terrain',
                'args': {'cell_from': 'A1', 'cell_to': 'AZ60', 'style': 'gentle', 'amplitude': 2, 'seed': 7},
            }
        ],
    },
    {
        'ask': 'a retaining wall along the back of the plot',
        'calls': [
            {
                'tool': 'add_retaining_wall',
                'args': {'cells': ['C28', 'K28'], 'height': 1.8, 'thickness': 0.3, 'batter': 0.1},
            }
        ],
    },
    {
        'ask': 'level the building plot first',
        'calls': [{'tool': 'flatten_pad', 'args': {'cell_from': 'C4', 'cell_to': 'L13', 'material': 'mat_gravel'}}],
    },
    # typologies_commercial
    {
        'ask': 'a 25-storey glass office tower on C4 to N15',
        'calls': [
            {
                'tool': 'draw_office_tower',
                'args': {'cell_from': 'C4', 'cell_to': 'N15', 'storeys': 25, 'glass': True, 'core': True},
            }
        ],
    },
    {
        'ask': 'a warehouse with six doors and skylights',
        'calls': [
            {
                'tool': 'draw_warehouse',
                'args': {'cell_from': 'C4', 'cell_to': 'AP23', 'height_m': 8, 'doors': 6, 'skylights': True},
            }
        ],
    },
    {
        'ask': 'a brick church with a tower on D10 to K25',
        'calls': [
            {
                'tool': 'draw_church',
                'args': {'cell_from': 'D10', 'cell_to': 'K25', 'tower': True, 'material': 'mat_brick'},
            }
        ],
    },
    # typologies_residential
    {
        'ask': 'a Dutch row house on C4 to G13, two storeys',
        'calls': [
            {
                'tool': 'draw_house',
                'args': {'cell_from': 'C4', 'cell_to': 'G13', 'storeys': 2, 'style': 'rowhouse', 'door_side': 'south'},
            }
        ],
    },
    {
        'ask': 'a terrace of eight row houses starting at C4',
        'calls': [
            {
                'tool': 'draw_row_houses',
                'args': {'cell_from': 'C4', 'cell_to': 'G13', 'count': 8, 'storeys': 2, 'style': 'rowhouse'},
            }
        ],
    },
    {
        'ask': 'a villa with a pool on M20 to U28',
        'calls': [{'tool': 'draw_villa', 'args': {'cell_from': 'M20', 'cell_to': 'U28', 'storeys': 2, 'pool': True}}],
    },
    # vehicles_props
    {
        'ask': 'park three cars on the drive at E14, F14, G14',
        'calls': [{'tool': 'park_cars', 'args': {'cells': ['E14', 'F14', 'G14'], 'kind': 'car', 'rotation_deg': 90}}],
    },
    {
        'ask': 'a construction site with a tower crane next to the block',
        'calls': [
            {
                'tool': 'add_construction_site',
                'args': {'cell_from': 'P4', 'cell_to': 'X12', 'crane': True, 'containers': 3, 'crane_height': 30},
            }
        ],
    },
    # view_scene_ops
    {'ask': 'show me the top view', 'calls': [{'tool': 'set_view', 'args': {'view': 'top'}}]},
    {
        'ask': 'zoom to the new tower and turn the cell labels on',
        'calls': [{'tool': 'focus', 'args': {'which': 'new'}}, {'tool': 'show_cells', 'args': {'on': True}}],
    },
    {'ask': 'set the sun to five in the afternoon', 'calls': [{'tool': 'set_sun', 'args': {'hour': 17}}]},
    # water_leisure
    {
        'ask': 'a swimming pool 8 by 4 behind the villa',
        'calls': [{'tool': 'add_pool', 'args': {'cell_from': 'N24', 'cell_to': 'U27', 'depth': 1.5, 'coping': True}}],
    },
    {
        'ask': 'a tennis court on the lawn',
        'calls': [
            {
                'tool': 'add_sports_court',
                'args': {'cell_from': 'D30', 'cell_to': 'M48', 'sport': 'tennis', 'lines': True},
            }
        ],
    },
    {
        'ask': 'a fountain in the middle of the square',
        'calls': [{'tool': 'add_fountain', 'args': {'centre': 'K35', 'radius': 3, 'tiers': 2, 'height': 2.5}}],
    },
]
