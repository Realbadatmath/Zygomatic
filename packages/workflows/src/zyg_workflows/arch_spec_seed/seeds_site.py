# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""arch_spec_seed.seeds_site — furniture, parking and the open air — bed, kitchen_counter, parking_bay,
ramp, fire_escape, balcony, canopy, roof_deck, pool, tree, lamp_post,
curtain_wall.

Moved verbatim out of the 1,179-line arch_spec_seed.py; original lines 424-784.
"""

from __future__ import annotations

SEEDS_SITE = [
    {
        'key': 'bed',
        'title': 'Bed',
        'aliases': ['bed', 'double bed', 'single bed'],
        'kinds': ['bed_double', 'bed_single'],
        'tools': ['place_asset', 'furnish_room'],
        'what': 'The object a bedroom is planned around: the mattress plus the room to make it and to get into it.',
        'looks': 'Double 1.4-1.8 x 2.0 m, single 0.9 x 2.0 m, 0.5 m high with the head against a solid wall.',
        'how': 'place_asset(cell, query="double bed") or furnish_room(use="bedroom"), head to a party wall not a window.',
        'avoid': [
            'A double bed with one side against a wall',
            'A bed under a window in a bedroom with only one window',
            'A wardrobe door that cannot open past the bed',
        ],
        'quality': [
            '0.7 m clear both sides of a double, 0.9 m at the foot',
            'Head against a solid wall, not glass',
            'A bedroom is 9 m2 minimum for a single, 12 m2 for a double',
        ],
        'space': {
            'w': [0.9, 2.0],
            'd': [1.9, 2.2],
            'clear_r': 0.7,
            'host': 'floor',
            'severity': 'warn',
            'note': '0.7 m each side to make the bed, 0.9 m at the foot to pass',
        },
        'source': 'seeded',
    },
    {
        'key': 'kitchen_counter',
        'title': 'Kitchen run',
        'aliases': ['kitchen', 'counter', 'worktop', 'keuken'],
        'kinds': ['kitchen_counter', 'kitchen_island'],
        'tools': ['furnish_kitchen', 'place_asset'],
        'what': 'A continuous 0.6 m deep run at 0.9 m high carrying sink, hob and storage, with a working strip in '
        'front of it that nothing may stand in.',
        'looks': 'One or two straight runs, or a run and an island; appliances flush in the line, not scattered.',
        'how': 'furnish_kitchen(cell_from, cell_to, storey, layout="galley"|"l"|"u"|"island").',
        'avoid': [
            'Two runs closer than 1.2 m — the doors of opposite units collide',
            'An island closer than 1.0 m to the run behind it',
            'Sink, hob and fridge not forming a triangle',
        ],
        'quality': [
            '1.2 m between opposing runs, 1.5 m where two people cook',
            '0.6 m of worktop each side of the hob and 0.4 m beside the sink',
            'Real appliances and a library worktop material',
        ],
        'space': {
            'd': [0.6, 0.7],
            'clear_front': 1.2,
            'facing': '+z',
            'host': 'floor',
            'severity': 'warn',
            'note': '1.2 m of working strip in front of the run, 1.5 m for two cooks',
        },
        'source': 'seeded',
    },
    {
        'key': 'parking_bay',
        'title': 'Parking bay',
        'aliases': ['parking', 'car park', 'bay', 'parkeerplaats'],
        'kinds': ['parking_bay'],
        'tools': ['add_parking', 'park_cars', 'draw_parking_garage'],
        'what': "One car's footprint plus the aisle it has to reverse into. The aisle is part of the bay, not a "
        'separate thing to add later.',
        'looks': '2.5 x 5.0 m marked bays in rows either side of a 6.0 m aisle.',
        'how': 'add_parking(cell_from, cell_to, rows, aisle=6.0) or draw_parking_garage(decks=N); park_cars() puts '
        'real vehicles in a few of them for a render.',
        'avoid': [
            'An aisle under 6.0 m for 90-degree bays — the car cannot turn in',
            'Accessible bays at the far end from the entrance',
            'A row of bays with no way out at the end',
        ],
        'quality': [
            '2.5 x 5.0 m standard, 3.6 m wide for an accessible bay with its hatched stripe',
            '6.0 m aisle at 90 degrees, 4.5 m at 45 degrees',
            '2.1 m clear height in a garage; 2.6 m where a van must enter',
            'Fill only some bays with cars — a full deck reads as a car showroom',
        ],
        'space': {
            'w': [2.4, 3.6],
            'd': [4.8, 6.0],
            'clear_front': 6.0,
            'facing': '+z',
            'host': 'floor',
            'severity': 'error',
            'note': 'the 6 m aisle in front of the bay is part of the requirement',
        },
        'source': 'seeded',
    },
    {
        'key': 'ramp',
        'title': 'Ramp',
        'aliases': ['slope', 'accessible ramp', 'helling'],
        'kinds': ['ramp'],
        'tools': ['add_object', 'add_utility'],
        'what': 'The sloped route that makes a level change usable by a wheelchair, a trolley or a car.',
        'looks': 'A straight run with a flat landing at each end; a person-ramp is visibly gentler than a car ramp.',
        'how': 'add_object(kind="ramp", ...) between two levels, with flat landings top and bottom, or add_utility for '
        'a service ramp. Beside the entrance, never instead of it.',
        'avoid': [
            'Steeper than 1:12 for people (1:15 is better), 1:8 to 1:6 for cars',
            'A run longer than 10 m with no landing',
            'A ramp that lands on a door swing',
            'A ramp with no guarding on an open side',
        ],
        'quality': [
            '1.5 m x 1.5 m landing at both ends and every 10 m',
            '1.2 m clear width minimum for a person-ramp',
            'Handrails both sides at 0.9-1.0 m',
        ],
        'space': {
            'w': [1.2, 6.0],
            'clear_front': 1.5,
            'facing': '+z',
            'host': 'ground',
            'severity': 'warn',
            'note': '1:12 max for people; a 1.5 m level landing top and bottom is part of the ramp',
        },
        'source': 'seeded',
    },
    {
        'key': 'fire_escape',
        'title': 'Escape stair / second exit',
        'aliases': ['fire escape', 'escape stair', 'second stair', 'egress'],
        'kinds': ['fire_stair_exterior'],
        'tools': ['add_fire_escape', 'egress_check'],
        'what': 'The second way down, remote from the first, so a fire in one does not close both.',
        'looks': 'A protected stair in its own enclosure, or an external stair on the far facade from the main core.',
        'how': 'add_fire_escape(cell, storeys, width=1.2) on the opposite side of the plan from the main core, then '
        'egress_check(max=30) to prove every room reaches one.',
        'avoid': [
            'Both stairs in the same core — that is one escape drawn twice',
            'An escape route through a room that can be locked',
            'A travel distance over 30 m to the nearest exit',
            'A second stair that stops before the ground',
        ],
        'quality': [
            'Put the two stairs at opposite ends of the plate',
            '1.2 m minimum width, and the same width all the way down',
            'Run egress_check() after the layout, not after the render',
        ],
        'space': {
            'w': [1.0, 2.4],
            'headroom': 2.0,
            'host': 'floor',
            'severity': 'error',
            'note': 'remote from the main core; travel distance to a stair under 30 m',
        },
        'source': 'seeded',
    },
    {
        'key': 'balcony',
        'title': 'Balcony',
        'aliases': ['terrace', 'loggia', 'balkon'],
        'kinds': ['balcony', 'railing'],
        'tools': ['add_balconies'],
        'what': 'A private outdoor slab hung off the facade of a dwelling, with guarding on every open side.',
        'looks': 'One per unit, repeating up the facade; deep enough that a table and two chairs fit, or it is a ledge.',
        'how': 'add_balconies(walls, storeys, depth=1.8, railing=True) on the residential facade.',
        'avoid': [
            'Under 1.5 m deep — nothing but a plant fits',
            'A balcony with no guarding, or guarding under 1.1 m',
            'Balconies on an office facade: they read as apartments',
        ],
        'quality': [
            '1.8-2.2 m deep so a table and two chairs fit',
            'Guarding 1.1 m, gaps under 0.1 m (guarding_check)',
            'Line them up vertically; a scattered pattern reads as damage',
        ],
        'space': {
            'd': [1.5, 3.0],
            'host': 'wall',
            'severity': 'warn',
            'note': '1.5 m is the minimum useful depth; 1.8-2.2 m fits a table',
        },
        'source': 'seeded',
    },
    {
        'key': 'canopy',
        'title': 'Canopy / porte-cochère',
        'aliases': ['porte cochere', 'awning', 'entrance canopy', 'luifel'],
        'kinds': ['canopy', 'awning'],
        'tools': ['add_canopy'],
        'what': 'A plate over the arrival point so people leave a car dry. Its columns carry it and are exactly as '
        'tall as its soffit.',
        'looks': 'A horizontal plate 3.5-4.5 m over the drive, deep enough to cover a car door opening.',
        'how': 'add_canopy(wall_id, width, depth=4..6, height=3.5..4.5, columns=4, column_material=...). Never a '
        'separate add_colonnade of a different height underneath it.',
        'avoid': [
            'A soffit under 2.7 m on a tower — a 2.4 m plate is a shop awning',
            'Columns of a different height from the soffit: they pierce the plate',
            'A canopy over no drive',
            'A canopy narrower than the doors it covers',
        ],
        'quality': [
            'Soffit 3.5-4.5 m, depth 4-6 m so a car and its open door fit under it',
            'Columns under the OUTER edge of the plate, evenly spaced',
            'A real material on the soffit — it is the surface everyone stands under',
        ],
        'space': {
            'w': [4.0, 20.0],
            'd': [3.0, 8.0],
            'headroom': 2.7,
            'host': 'wall',
            'severity': 'error',
            'note': "columns exactly soffit-tall, under the plate's outer edge; 4.5 m clear for a vehicle",
        },
        'source': 'seeded',
    },
    {
        'key': 'roof_deck',
        'title': 'Roof deck / terrace',
        'aliases': ['roof terrace', 'rooftop', 'deck', 'dakterras'],
        'kinds': ['roof_flat', 'slab'],
        'tools': ['add_roof', 'add_parapet'],
        'what': 'The walkable TOP of a flat roof. The roof record is a solid: its deck is its y plus its thickness.',
        'looks': 'A flat surface with a parapet round it, plant and the lift overrun on it, and furniture standing ON '
        'it — not sunk into it.',
        'how': 'Leave base_height OUT and the tools land on the deck by themselves; or pass storey=<top>. '
        'add_parapet(...) round the edge; add_rooftop_plant for the machinery.',
        'avoid': [
            "Passing base_height = the roof record's y — that is 0.3 m INSIDE the slab",
            'A roof terrace with no parapet',
            'A flat roof with nothing on it: no plant, no overrun, no parapet reads as a massing model',
        ],
        'quality': [
            'Parapet 1.1 m on any accessible roof',
            'Lift overrun and plant enclosure — a real building has both',
            'A real deck material (travertine, teak) not a flat preset',
        ],
        'space': {
            'headroom': 2.4,
            'host': 'deck',
            'severity': 'warn',
            'note': 'the deck is roof y + thickness; deck_top() does this for you when base_height is omitted',
        },
        'source': 'seeded',
    },
    {
        'key': 'pool',
        'title': 'Swimming pool',
        'aliases': ['swimming pool', 'infinity pool', 'rooftop pool', 'roof pool', 'infinity edge', 'weir', 'zwembad'],
        'kinds': ['pool'],
        'tools': ['add_infinity_pool', 'add_pool'],
        # 2026-09-12: rewritten from the operator's five reference pictures (Marina Bay Sands, One GT Grand
        # Cayman, Noa Rooftop Alanya, two stock renders); the long form is explain("infinity pool").
        'what': 'A basin of water. On a roof the CORRECT one is deck-level: the water meets the walking surface, the tank hangs into the storey below with the balance tank and plant. Raised is the fallback when that storey must stay habitable.',
        'looks': 'Water level with the deck; glass weir on the VIEW side only, trough under it; frameless glass balustrade 1.1 m OUTBOARD of the trough (the weir is never the building edge); steps on the deck side; deep-blue small tile; loungers facing the view, parasols behind, palms at the ends.',
        'how': 'add_infinity_pool(cell_from, cell_to, view="south", storey=<top>) builds ALL of it. add_pool(infinity=, steps=, sunk=true) is the basin alone.',
        'avoid': [
            "base_height = the roof record's y (inside the slab)",
            'the weir as the roof edge with no guard outboard',
            'a solid parapet on the view side',
            'steps or a rail on the weir side',
            '"infinity" as a word with no weir built',
        ],
        'quality': [
            '1.2-1.5 m deep uniform; short side 4 m or more; 20-25 m for laps',
            'weir crest dead level, lip sloped outward',
            'balance tank + edge pumps on their own loop in the plant zone below',
            'loungers 2.4 m apart, 1.2 m off the coping, facing the view',
            'warm underwater light on the deck side, none on the weir',
            'tile over floor, walls and weir; teak or pale stone deck',
        ],
        'space': {
            'clear_r': 1.2,
            'host': 'deck',
            'severity': 'warn',
            'note': 'glass guard >= 1.1 m outboard of the weir (design_check inf_guard)',
        },
        'source': 'seeded',
    },
    {
        'key': 'tree',
        'title': 'Tree',
        'aliases': ['trees', 'planting', 'boom', 'baum'],
        'kinds': ['tree_deciduous', 'tree', 'tree_conifer', 'tree_palm'],
        'tools': ['plant_trees', 'plant_tree_line'],
        'what': 'A real plant with a crown 5-8 m across at maturity — which is what decides how far apart two of them '
        'may stand before they read as one green blob.',
        'looks': 'A trunk, a clear stem to 2-2.5 m, and a crown you can see the building through in the gaps.',
        'how': 'plant_trees(cell_from, cell_to, count, height, model="real") — real models by default. The tool '
        'REFUSES a block too small for the count; take the block it names rather than another tool.',
        'avoid': [
            'Two trees closer than one crown apart',
            'Trees on the entrance axis',
            'Sphere-on-a-cylinder placeholders in a presentation',
            'plant_tree_line as a way around a refusal from plant_trees',
        ],
        'quality': [
            'One crown width between trunks, minimum',
            'A real model scaled 0.6-1.6 to the asked height, never 8 m of primitive',
            'Flank the entrance at 6 m off the axis, do not block it',
        ],
        'space': {
            'clear_r': 3.0,
            'host': 'ground',
            'severity': 'warn',
            'note': 'trunks at least one crown width apart; 6 m off any entrance axis',
        },
        'source': 'seeded',
    },
    {
        'key': 'lamp_post',
        'title': 'Lamp post',
        'aliases': ['street light', 'lighting column', 'lantaarnpaal'],
        'kinds': ['lamp_post'],
        'tools': ['add_street_furniture'],
        'what': 'A lit column along a route, spaced so the pools of light overlap.',
        'looks': '4-6 m tall on a drive, 3-4 m on a footpath; a real model, not a cylinder with a sphere.',
        'how': 'add_street_furniture(cells, kind="lamp_post", height=5) — real models by default.',
        'avoid': [
            'Spacing over 12 m: the light between them dies',
            'A post in the walking width of the path',
            'Posts on the entrance axis',
        ],
        'quality': [
            '8-12 m apart along an approach, on both edges',
            '0.6 m back from the kerb, clear of the walking width',
            'The same height and model along one route',
        ],
        'space': {
            'clear_r': 0.6,
            'host': 'ground',
            'severity': 'warn',
            'note': '8-12 m apart; outside the clear walking width of the path',
        },
        'source': 'seeded',
    },
    {
        'key': 'curtain_wall',
        'title': 'Curtain wall / glazed facade',
        'aliases': ['glass facade', 'glazing', 'gevel', 'facade'],
        'kinds': ['curtain_wall'],
        'tools': ['add_curtain_wall', 'add_facade_bands'],
        'what': 'A non-loadbearing glass skin hung in front of the structure. Because it hangs in FRONT, it hides the '
        'floor slab edges — which is what makes a glass tower read as hollow.',
        'looks': 'Mullions at 1.35-1.5 m, a spandrel or string course at every floor line, reflections that change '
        'per storey.',
        'how': 'add_curtain_wall(walls, storeys) then add_facade_bands(kind="string_course") on every glazed storey '
        'so the floor line reads.',
        'avoid': [
            'Glazing every storey with no band at the floor line — the tower looks empty',
            'Glass where a core or a stair is behind it',
            'A single sheet with no mullion pattern',
        ],
        'quality': [
            'Mullions at 1.35-1.5 m centres',
            'A 0.6-1.0 m spandrel or string course at every floor',
            'A library glass material with real reflectance, not the flat preset, on a presentation',
        ],
        'space': {
            'host': 'wall',
            'severity': 'warn',
            'note': 'add a string course per glazed storey or check_floors will read the building as hollow',
        },
        'source': 'seeded',
    },
]
