# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""arch_spec_seed.seeds_rooms — rooms and circulation — entrance, lobby, elevator, stair, corridor, door,
wc, apartment, office_floor, meeting_room, dining_table, desk.

Moved verbatim out of the 1,179-line arch_spec_seed.py; original lines 30-423.
"""

from __future__ import annotations

SEEDS_ROOMS = [
    {
        'key': 'entrance',
        'title': 'Building entrance',
        'aliases': ['front door', 'main entrance', 'arrival', 'entree', 'porte cochere', 'porte-cochère'],
        'kinds': ['double_door', 'door_sliding'],
        'tools': ['add_canopy', 'add_windows'],
        'what': 'The one place a visitor is meant to arrive at: a door on the axis a person walks in on, made obvious '
        'by what is around it — a taller opening, a recess or a projecting cover, and a clear approach.',
        'looks': 'From 20 m out you see it before you see the door: a break in the facade, a cover overhead, light '
        'behind the glass. The door is centred on that composition, not offset by a metre.',
        'how': 'add_windows(kind="double_door") or a wide opening in the ground-storey wall, then add_canopy(wall_id, '
        'width, depth, height=3.5..4.5, columns=N) for a covered arrival, lamp posts down the approach with '
        'add_street_furniture(kind="lamp_post"), and a drive that actually reaches the canopy.',
        'avoid': [
            'A door that is not on the axis of the approach — it reads as a fire exit',
            'Trees, poles or planters on the approach strip: keep 12 m clear and flank at 6 m off the axis',
            'A canopy soffit under 2.7 m on anything bigger than a shop — 2.4 m is an awning',
            'An entrance with no lit interior behind it: at night it disappears',
        ],
        'quality': [
            'Make the opening at least 1.5 storeys tall on a building over 4 storeys',
            'Give the reveal depth — a recess of 0.5-1.5 m reads as an entrance in any light',
            'Land the paving, the canopy and the door on the SAME centre line',
            'Real lamp posts and real paving materials (search_materials), never flat presets',
        ],
        'space': {
            'w': [1.8, 6.0],
            'clear_front': 12.0,
            'facing': '+z',
            'host': 'wall',
            'severity': 'warn',
            'note': 'the approach stays clear for 12 m and 4 m wide; flanking planting starts 6 m off the axis',
        },
        'source': 'seeded',
    },
    {
        'key': 'lobby',
        'title': 'Entrance lobby',
        'aliases': ['foyer', 'entrance hall', 'reception'],
        'kinds': ['zone'],
        'tools': ['add_room', 'add_atrium'],
        'what': 'The room behind the entrance that receives people and hands them to the lifts and stairs. It absorbs '
        'the arrival crowd so the door is never the queue.',
        'looks': 'Wider than it is deep on a small building, double-height on a tall one; the lift doors visible from '
        'the entrance door without turning a corner.',
        'how': 'add_room(cell_from, cell_to, storey=0, name="Lobby", partitions=True) inside the footprint, on the '
        'entrance axis, with the core (add_elevator + add_stair) at its far end; add_atrium for a double height.',
        'avoid': [
            'A lobby you enter and cannot see the lifts from',
            'Making it the leftover space after the lettable area is set out',
            'A single door into a lobby serving more than 100 people',
        ],
        'quality': [
            'Line of sight door → reception → lift in one straight move',
            'Ceiling at least 3 m, and taller than the corridors it feeds',
            'One real material on the floor and one on the lift wall, not eight',
        ],
        'space': {
            'w': [4.0, 30.0],
            'd': [4.0, 30.0],
            'headroom': 3.0,
            'host': 'floor',
            'severity': 'warn',
            'per': {'unit': 'occupants of the building', 'n': 100},
            'note': 'about 0.2 m2 per occupant of the floors it serves, never under 15 m2',
        },
        'source': 'seeded',
    },
    {
        'key': 'elevator',
        'title': 'Passenger lift',
        'aliases': ['lift', 'elevator', 'aufzug', 'ascenseur'],
        'kinds': ['elevator_car', 'elevator_shaft'],
        'tools': ['add_elevator'],
        'what': 'A vertical shaft with a car in it, running the full height of the building, landing at every storey '
        'it serves. A building of three storeys or more needs one; four or more is not arguable.',
        'looks': 'From outside, a blank shaft that runs to the top and usually 1-2 m past it (the overrun). From '
        'inside, a pair of doors on every landing, in a lobby wide enough to wait in.',
        'how': 'add_elevator(cell, from_storey=0, to_storey=<top>, w=1.8, depth=2.0, car=True) INSIDE the plan, next to '
        'add_stair — the two together are the core. Run it to the top storey, not to the storey below it.',
        'avoid': [
            'A shaft that stops one storey short of the top',
            'Lift doors opening straight into a corridor with no waiting space',
            'A car under 1.1 x 1.4 m — that is a goods hoist, and no wheelchair turns in it',
            'A lift with no stair beside it: a core is both or it is neither',
        ],
        'quality': [
            'Two lifts above 8 storeys or 60 apartments, side by side, sharing one lobby',
            'Lobby depth at least the car depth, 1.8 m minimum',
            'Show the overrun on the roof — a flat roof with no plant reads as a model',
        ],
        'space': {
            'w': [1.1, 2.4],
            'd': [1.4, 2.6],
            'clear_front': 1.8,
            'facing': '+z',
            'headroom': 2.1,
            'host': 'floor',
            'severity': 'error',
            'per': {'unit': 'occupants', 'n': 200},
            'note': 'the landing in front of the doors is at least as deep as the car, minimum 1.8 m',
        },
        'source': 'seeded',
    },
    {
        'key': 'stair',
        'title': 'Staircase',
        'aliases': ['stairs', 'staircase', 'trap', 'treppe', 'escalier'],
        'kinds': ['stair_straight', 'stair_l', 'stair_u', 'stair_spiral', 'stair_winder', 'stair_landing'],
        'tools': ['add_stair'],
        'what': 'The way up that works when the power is off, and the way out in a fire. Every storey above ground '
        'needs one reaching it; a building deeper than a single escape allows needs two.',
        'looks': 'A flight of equal risers between landings; a U or L stair fits a core, a straight stair needs 5-6 m '
        'of run per storey and eats plan.',
        'how': 'add_stair(cell, from_storey=0, to_storey=<top>, kind="u"|"l"|"straight"|"spiral", width=1.2) inside the '
        'core next to add_elevator. Check it with stair_check() and headroom_check().',
        'avoid': [
            'A stair 0.8 m wide in anything but a house — 1.2 m is the working minimum',
            'Landing straight onto a door swing',
            'A spiral stair as the only stair of a building',
            'Forgetting the storey it lands on has a floor slab to land on',
        ],
        'quality': [
            'Riser 0.15-0.19 m, going 0.25-0.30 m, and the same all the way up',
            'A landing every 16 risers',
            '2.0 m clear headroom on the diagonal, which headroom_check measures',
            'Guarding 1.1 m with gaps under 0.1 m (guarding_check)',
        ],
        'space': {
            'w': [1.0, 3.0],
            'headroom': 2.0,
            'host': 'floor',
            'severity': 'error',
            'note': 'flight 1.2 m wide for a public building, 0.9 m inside a dwelling; landing at least as long '
            'as the flight is wide',
        },
        'source': 'seeded',
    },
    {
        'key': 'corridor',
        'title': 'Corridor',
        'aliases': ['hallway', 'passage', 'circulation', 'pathway', 'gang', 'flur', 'couloir'],
        'kinds': [],
        'tools': ['add_corridor', 'subdivide_floor'],
        'what': 'The walking space that connects the core to every room on a floor. It is sized by how many people '
        'walk it and by what must pass in it, never by what is left over.',
        'looks': 'A straight run with doors down both sides, lit at the ends; a dead end longer than about 7 m is a '
        'planning fault, not a style.',
        'how': 'add_corridor(cell_from, cell_to, storey, width=1.5, direction="x"|"z") makes the two partitions; put '
        'the rooms either side with add_room, or let layout_floor() cut the whole floor in one call.',
        'avoid': [
            'Under 1.2 m clear — two people cannot pass and a wheelchair cannot turn',
            'Door swings that open into the walking width',
            'A dead-end leg over 7 m with only one way out',
            'Radiators, cabinets and pipes narrowing the clear width below the minimum',
        ],
        'quality': [
            '1.5 m is the comfortable width; 1.8 m where it also serves as a waiting space',
            'A 1.5 m turning circle at every dead end and at the lift landing',
            'Daylight at the end of the run',
            'Run egress_check(max=30) once the layout is in',
        ],
        'space': {
            'w': [1.2, 3.0],
            'headroom': 2.1,
            'host': 'floor',
            'severity': 'error',
            'note': 'clear width 1.2 m absolute minimum, 1.5 m preferred; door swings and furniture do not count '
            'as part of it',
        },
        'source': 'seeded',
    },
    {
        'key': 'door',
        'title': 'Door',
        'aliases': ['deur', 'tuer', 'porte', 'doorway'],
        'kinds': ['door', 'double_door', 'door_sliding', 'door_french'],
        'tools': ['add_windows', 'add_opening'],
        'what': 'A hole in a wall with a leaf in it, sized by what has to pass through and by who has to open it.',
        'looks': 'Head height consistent across a floor; a door in a 2.7 m storey sits with 0.6-0.9 m of wall over it.',
        'how': 'add_windows(walls, kind="door"|"double_door", width, height, sill=0) or add_opening for a bare hole. '
        "The opening is cut from the wall automatically; it must sit inside that wall's height band.",
        'avoid': [
            'A leaf under 0.8 m on any route a wheelchair uses',
            'Two doors whose swings collide',
            'A door in a wall that is not there yet — cut it after the wall exists',
            'Doors at different head heights on the same wall',
        ],
        'quality': [
            '0.9 m leaf as the standard, 1.0 m on a main route',
            '0.3-0.5 m of wall on the latch side so a wheelchair user can reach the handle',
            'Double doors only where the traffic is real',
        ],
        'space': {
            'w': [0.8, 2.4],
            'clear_front': 1.2,
            'facing': '+z',
            'host': 'wall',
            'severity': 'warn',
            'note': 'keep the swing clear on the pull side: 1.2 m deep and 0.3 m past the latch edge',
        },
        'source': 'seeded',
    },
    {
        'key': 'wc',
        'title': 'Toilet / washroom',
        'aliases': ['toilet', 'restroom', 'bathroom', 'wc', 'sanitair'],
        'kinds': ['toilet', 'washbasin', 'shower', 'bathtub'],
        'tools': ['furnish_bathroom', 'add_room'],
        'what': 'The sanitary room. In an office or public building the count follows occupancy; in a dwelling it '
        'follows bedrooms. Every building with people in it for more than an hour needs one.',
        'looks': 'A small room off the circulation, never off a habitable room in a public building; an accessible '
        'cubicle is visibly bigger and has a clear turning circle.',
        'how': 'add_room(...) then furnish_bathroom(cell_from, cell_to, storey) for the fittings.',
        'avoid': [
            'A WC opening straight onto a dining or working space',
            'An accessible WC under 1.5 x 2.2 m — the turning circle does not fit',
            'One WC per floor in a building of more than 20 people',
        ],
        'quality': [
            'One accessible WC per floor of a public building, on the same route as the lift',
            '0.75 m clear in front of every fitting',
            'Group them at the core so the drainage stacks line up',
        ],
        'space': {
            'w': [0.9, 4.0],
            'd': [1.5, 6.0],
            'clear_front': 0.75,
            'host': 'floor',
            'severity': 'warn',
            'per': {'unit': 'occupants', 'n': 20},
            'note': 'accessible cubicle 1.5 x 2.2 m with a 1.5 m turning circle clear of the door swing',
        },
        'source': 'seeded',
    },
    {
        'key': 'apartment',
        'title': 'Apartment / dwelling unit',
        'aliases': ['flat', 'dwelling', 'unit', 'woning', 'wohnung'],
        'kinds': ['zone'],
        'tools': ['add_room', 'subdivide_floor', 'draw_apartment_block'],
        'what': "One household's share of a floor: an entrance hall off the common corridor, a living/kitchen space "
        'on the facade, bedrooms on the facade, and the wet rooms inland against the party wall.',
        'looks': 'From the corridor, one front door per unit; from outside, one balcony or window group per unit, '
        'repeating on every typical floor.',
        'how': 'layout_floor(use="residential") cuts a whole floor of them; add_room for one at a time. Depth 10-14 m '
        'from facade to corridor is what makes the daylight work.',
        'avoid': [
            'A bedroom with no window on the facade',
            'A unit deeper than 14 m from its only facade — the back half is dark',
            'The front door opening straight into the living room in anything but a studio',
            'Wet rooms scattered so no two stacks line up between floors',
        ],
        'quality': [
            'Living space on the best facade, bedrooms on the quiet one',
            'A 1.5 m turning circle inside the entrance hall',
            'Stack kitchens and bathrooms vertically between storeys',
            'One balcony per unit on a residential facade — a blank one reads as an office',
        ],
        'space': {
            'w': [3.0, 20.0],
            'd': [6.0, 14.0],
            'headroom': 2.4,
            'host': 'floor',
            'severity': 'warn',
            'note': 'studio from 30 m2, 1-bed 45-55 m2, 2-bed 65-80 m2, 3-bed 85-100 m2',
        },
        'source': 'seeded',
    },
    {
        'key': 'office_floor',
        'title': 'Office floor',
        'aliases': ['office', 'workplace', 'open plan', 'kantoor', 'buro'],
        'kinds': ['zone', 'desk'],
        'tools': ['layout_floor', 'subdivide_floor', 'draw_office_tower'],
        'what': 'A lettable floor plate around a core: desks in the daylight, meeting rooms and stores against the '
        'core, circulation between them.',
        'looks': 'A ring of workspace 6-9 m deep around a solid core; the facade is glass and the core is not.',
        'how': 'draw_office_tower for the shell, then layout_floor(use="office", storey=N) for the plate, then '
        'repeat_floor to carry it up the typical storeys.',
        'avoid': [
            'A core against one facade on a deep plate — half the floor becomes unusable',
            'Desks more than 9 m from a window',
            'Meeting rooms on the best facade and desks facing the core',
            'A floor with no second stair once the plate is over about 500 m2',
        ],
        'quality': [
            '6-9 m from core to facade is the workable band',
            '2.7 m floor-to-floor minimum, 3.3-3.6 m where the ceiling is exposed',
            '8-12 m2 per person for open plan; occupancy() will tell you the count',
            'Meeting rooms and stores as the buffer between core and desks',
        ],
        'space': {
            'd': [6.0, 12.0],
            'headroom': 2.6,
            'host': 'floor',
            'severity': 'warn',
            'per': {'unit': 'm2 per person', 'n': 10},
            'note': 'core-to-facade 6-9 m; deeper needs a second source of daylight',
        },
        'source': 'seeded',
    },
    {
        'key': 'meeting_room',
        'title': 'Meeting room',
        'aliases': ['conference room', 'boardroom', 'vergaderzaal'],
        'kinds': ['zone', 'dining_table'],
        'tools': ['add_room', 'place_furniture_set'],
        'what': 'An enclosed room with a table, sized by the seat count and the room to get behind a pushed-out chair.',
        'looks': 'One table centred, chairs all round, a clear wall for the screen at the short end.',
        'how': 'add_room(...) then place_furniture_set / place_asset a real table and chairs. Size it from the seats: '
        'seats x 0.7 m of table edge, plus 1.0 m of circulation all round the table.',
        'avoid': [
            'A table so big the chairs cannot be pulled out',
            'The door opening into the chair zone',
            'A screen wall with a window behind it',
        ],
        'quality': [
            '1.0 m clear between the table edge and any wall, 1.2 m on the entry side',
            '0.7 m of table edge per seat',
            'Real chairs and a real table (search_assets, [real, life-size PBR])',
        ],
        'space': {
            'w': [2.4, 12.0],
            'd': [2.4, 12.0],
            'clear_r': 1.0,
            'headroom': 2.4,
            'host': 'floor',
            'severity': 'warn',
            'note': 'the 1.0 m ring around the table is the room, not a luxury',
        },
        'source': 'seeded',
    },
    {
        'key': 'dining_table',
        'title': 'Table (dining or meeting)',
        'aliases': ['table', 'dining table', 'eettafel', 'tisch'],
        'kinds': ['dining_table', 'coffee_table'],
        'tools': ['place_asset', 'place_furniture_set', 'furnish_room'],
        'what': 'A top on legs that people sit around — so the object is the table AND the ring of space the chairs '
        'and the people behind them occupy.',
        'looks': '0.75 m high; 0.9 m wide for four, 1.0-1.1 m for six or more so two plates and a dish fit across.',
        'how': 'place_asset(cell, query="dining table") with a [real, life-size PBR] result; put the chairs with the '
        'same call or place_furniture_set. Check the ring before you place anything else near it.',
        'avoid': [
            'Pushing the table against a wall on the side people sit',
            'Less than 1.0 m between the table edge and the next fixed object',
            'A toy-kit table: it is 20 % undersized and reads as a doll house',
        ],
        'quality': [
            '0.75 m to pull a chair out, plus 0.35 m to walk behind it = 1.1 m clear all round',
            '0.6-0.7 m of edge per seat',
            'Centre it on the room or on the window, not on the leftover space',
        ],
        'space': {
            'w': [0.8, 3.2],
            'd': [0.8, 1.4],
            'clear_r': 1.0,
            'host': 'floor',
            'severity': 'warn',
            'note': 'a chair pulled out takes 0.75 m; walking behind it takes another 0.35 m',
        },
        'source': 'seeded',
    },
    {
        'key': 'desk',
        'title': 'Desk / workstation',
        'aliases': ['workstation', 'bureau', 'schreibtisch'],
        'kinds': ['desk'],
        'tools': ['place_asset', 'furnish_room'],
        'what': "One person's work surface plus the chair zone behind it and the way past it.",
        'looks': '1.4-1.8 m wide, 0.8 m deep, 0.73 m high; in a row, backs to backs with a shared circulation strip.',
        'how': 'place_asset(cell, query="office desk") or furnish_room(use="office"); array() to repeat a bay.',
        'avoid': [
            'Chair zone overlapping the corridor',
            'Desks facing a blank wall when the window is behind them',
            'A row with no way out at one end',
        ],
        'quality': [
            '1.0 m of chair zone behind the desk, plus 0.8 m to walk past = 1.8 m between back-to-back rows',
            '8-12 m2 per person including circulation',
            'Within 9 m of a window',
        ],
        'space': {
            'w': [1.2, 2.0],
            'd': [0.7, 0.9],
            'clear_front': 1.0,
            'facing': '+z',
            'host': 'floor',
            'severity': 'warn',
            'note': '1.0 m chair zone behind, 0.8 m circulation past it',
        },
        'source': 'seeded',
    },
]
