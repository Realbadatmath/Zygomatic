# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""image_shared.subjects — the 132 subject prompts, verbatim, one per render_* column."""

from __future__ import annotations

SUBJECTS: dict = {}  # render_* column -> (the thing a detector looks for, the verbatim prompt)

SUBJECTS.update(
    {
        # ── Render: People ──
        'render_person_one': (
            'person',
            'A Dutch shipwright stands alone on the Kattenburg quay, 1671, plain daylight, whole body in frame, facing the camera, empty cobbled quay behind him.',
        ),
        'render_person_two': (
            'person',
            'Two Dutch dockworkers stand side by side on the Kattenburg quay, 1671, plain daylight, both whole bodies in frame, facing the camera, empty quay behind them.',
        ),
        'render_person_three': (
            'person',
            'Three Dutch dockworkers stand in a row on the Kattenburg quay, 1671, plain daylight, all three whole bodies in frame, facing the camera, empty quay behind them.',
        ),
        'render_person_group': (
            'person',
            'A group of five Dutch shipwrights stands together on the Kattenburg quay, 1671, plain daylight, every body whole and in frame, facing the camera.',
        ),
        'render_person_crowd': (
            'person',
            'A crowd of at least twenty Dutch townspeople fills the Kattenburg quay, 1671, plain daylight, seen from a raised viewpoint so heads and bodies are visible.',
        ),
        'render_child': (
            'person',
            'A Dutch boy of about seven stands alone in a farmhouse yard, 1671, plain daylight, whole body in frame, facing the camera, nobody else present.',
        ),
        'render_infant': (
            'person',
            'A Dutch woman holds a swaddled infant in a farmhouse doorway, 1671, plain daylight, the infant face and head clearly visible, nobody else present.',
        ),
        'render_teen': (
            'person',
            'A Dutch girl of about fifteen stands alone on the Kattenburg quay, 1671, plain daylight, whole body in frame, facing the camera, empty quay behind her.',
        ),
        'render_elderly': (
            'person',
            'An elderly Dutch man of about eighty stands alone in a farmhouse yard, 1671, plain daylight, whole body in frame, facing the camera, lined face clearly visible.',
        ),
        'render_person_back': (
            'person',
            'A Dutch shipwright stands alone on the Kattenburg quay, 1671, plain daylight, seen entirely from behind, his back to the camera, no face visible.',
        ),
        'render_person_distant': (
            'person',
            'A single Dutch figure stands far away at the end of a long empty cobbled quay, 1671, plain daylight, small in the frame, nothing else in view.',
        ),
        'render_person_partial': (
            'person',
            'A Dutch dockworker on the Kattenburg quay, 1671, plain daylight, framed from the waist up, the lower body outside the frame, nobody else present.',
        ),
    }
)

SUBJECTS.update(
    {
        # ── Render: The body ──
        'render_face_front': (
            'face',
            'Head and shoulders of a Dutch shipwright, 1671, plain daylight, facing the camera straight on, whole face in frame, plain grey wall behind him.',
        ),
        'render_face_profile': (
            'face',
            'Head and shoulders of a Dutch shipwright, 1671, plain daylight, in exact side profile, one ear and one eye visible, plain grey wall behind him.',
        ),
        'render_face_three_quarter': (
            'face',
            'Head and shoulders of a Dutch shipwright, 1671, plain daylight, head turned three quarters away from the camera, plain grey wall behind him.',
        ),
        'render_eyes_pair': (
            'face',
            'Close-up of a Dutch woman face, 1671, plain daylight, both eyes open and level, looking at the camera, plain grey wall behind her.',
        ),
        'render_gaze': (
            'face',
            'Head and shoulders of a Dutch woman, 1671, plain daylight, head facing the camera but both eyes looking far to her left, plain grey wall behind her.',
        ),
        'render_teeth': (
            'face',
            'Close-up of a Dutch dockworker laughing, 1671, plain daylight, mouth open, upper and lower teeth visible, plain grey wall behind him.',
        ),
        'render_ears': (
            'face',
            'Close-up of the left side of a Dutch man head, 1671, plain daylight, hair tied back so the whole ear is visible, plain grey wall behind him.',
        ),
        'render_hair_long': (
            'person',
            'Head and shoulders of a Dutch woman with long straight hair loose to her waist, 1671, plain daylight, facing the camera, plain grey wall behind her.',
        ),
        'render_hair_curly': (
            'person',
            'Head and shoulders of a Dutch man with thick curly shoulder-length hair, 1671, plain daylight, facing the camera, plain grey wall behind him.',
        ),
        'render_beard': (
            'face',
            'Head and shoulders of a Dutch sailor with a full dark beard, 1671, plain daylight, facing the camera, plain grey wall behind him.',
        ),
        'render_hand_one': (
            'hand',
            'Close-up of one open human right hand, palm towards the camera, fingers spread apart, against a plain grey cloth in plain daylight, nothing else in frame.',
        ),
        'render_hand_two': (
            'hand',
            'Close-up of two open human hands side by side, palms towards the camera, fingers spread apart, against a plain grey cloth in plain daylight.',
        ),
        'render_hand_holding': (
            'hand',
            'Close-up of one human hand holding a small brass key, palm up, against a plain grey cloth in plain daylight, nothing else in frame.',
        ),
        'render_hand_gripping': (
            'hand',
            'Close-up of one human hand gripping the wooden handle of a hammer, fingers closed around it, against a plain grey cloth in plain daylight.',
        ),
        'render_fingers_count': (
            'hand',
            'Close-up of one open human left hand, palm towards the camera, all five fingers spread wide and clearly separated, against a plain grey cloth in plain daylight.',
        ),
        'render_feet_bare': (
            'person',
            'Close-up of two bare human feet standing on a cobbled quay in plain daylight, both feet whole and in frame, ten toes visible, nothing else in frame.',
        ),
        'render_feet_shoes': (
            'person',
            'Close-up of two feet in black leather buckled shoes, 1671, standing on a cobbled quay in plain daylight, both shoes whole and in frame.',
        ),
        'render_arms_crossed': (
            'person',
            'A Dutch shipwright stands alone on the Kattenburg quay, 1671, plain daylight, arms folded across his chest, whole upper body in frame, facing the camera.',
        ),
        'render_muscle_flex': (
            'person',
            'A bare-armed Dutch blacksmith raises one arm and tenses it, 1671, plain daylight, the forearm and upper arm clearly visible, plain grey wall behind him.',
        ),
    }
)

SUBJECTS.update(
    {
        # ── Render: Food ──
        'render_food_present': (
            'food',
            'A plain wooden table in a Dutch farmhouse kitchen, 1671, plain daylight, a simple meal of bread and cheese set out on it, nobody present.',
        ),
        'render_food_bread': (
            'bread',
            'A single round dark rye loaf on a plain wooden board, Dutch farmhouse kitchen, 1671, plain daylight, nothing else on the board.',
        ),
        'render_food_fruit': (
            'fruit',
            'Five apples and three pears in a shallow earthenware dish on a plain wooden table, Dutch farmhouse kitchen, 1671, plain daylight.',
        ),
        'render_food_vegetables': (
            'vegetable',
            'A heap of raw carrots, turnips and onions on a plain wooden table, Dutch farmhouse kitchen, 1671, plain daylight, nothing cooked.',
        ),
        'render_food_meat_raw': (
            'meat',
            'A raw cut of beef on a plain wooden butcher block, Dutch kitchen, 1671, plain daylight, plainly uncooked, nothing else on the block.',
        ),
        'render_food_meat_cooked': (
            'meat',
            'A roasted joint of meat, browned and carved open, on a pewter dish on a plain wooden table, Dutch kitchen, 1671, plain daylight.',
        ),
        'render_food_fish': (
            'fish',
            'Three whole raw herring laid side by side on a plain wooden board, Dutch kitchen, 1671, plain daylight, heads and tails on.',
        ),
        'render_food_soup': (
            'bowl',
            'A pewter bowl of thick pea soup on a plain wooden table, Dutch farmhouse kitchen, 1671, plain daylight, a spoon resting in the bowl.',
        ),
        'render_food_plated': (
            'plate',
            'One pewter plate set with bread, cheese and herring, arranged neatly, on a plain wooden table, Dutch farmhouse kitchen, 1671, plain daylight.',
        ),
        'render_food_drink': (
            'cup',
            'A single pewter tankard of beer on a plain wooden table, Dutch tavern, 1671, plain daylight, foam on the beer, nothing else on the table.',
        ),
        'render_food_table': (
            'table',
            'A laid table for four in a Dutch farmhouse, 1671, plain daylight, bread, cheese, herring, apples and four pewter plates, nobody seated.',
        ),
        'render_food_spoiled': (
            'bread',
            'A spoiled rye loaf on a plain wooden board, Dutch kitchen, 1671, plain daylight, green and white mould across its crust, plainly rotten.',
        ),
    }
)

SUBJECTS.update(
    {
        # ── Render: Damage & wear ──
        'render_broken_wood': (
            'wood',
            'A snapped oak plank on the Kattenburg yard floor, 1671, plain daylight, the break splintered and open, nothing else in frame.',
        ),
        'render_broken_glass': (
            'glass',
            'A shattered drinking glass on a plain wooden table, Dutch tavern, 1671, plain daylight, the shards lying where they fell.',
        ),
        'render_broken_window': (
            'window',
            'A leaded farmhouse window with two panes smashed out, 1671, plain daylight, seen straight on from outside, the lead cames bent.',
        ),
        'render_broken_pottery': (
            'pottery',
            'A broken earthenware jug on a stone floor, Dutch kitchen, 1671, plain daylight, the pieces lying beside the base.',
        ),
        'render_cracked_wall': (
            'wall',
            'A brick wall with one long crack running down it, Amsterdam, 1671, plain daylight, seen straight on, nothing else in frame.',
        ),
        'render_torn_cloth': (
            'cloth',
            'A length of grey woollen cloth with a long ragged tear across it, spread flat on a plain wooden table in plain daylight.',
        ),
        'render_frayed_rope': (
            'rope',
            'A thick hemp rope on the Kattenburg quay, 1671, plain daylight, one end frayed open into loose strands, nothing else in frame.',
        ),
        'render_rust': (
            'iron',
            'A heavily rusted iron door hinge on weathered wood, 1671, plain daylight, orange-brown rust across the whole hinge, seen close up.',
        ),
        'render_rot': (
            'wood',
            'A rotted fence post in a farmhouse yard, 1671, plain daylight, the base soft and crumbling, dark with damp.',
        ),
        'render_burnt': (
            'wood',
            'A charred roof beam lying in a farmhouse yard, 1671, plain daylight, black and flaking, plainly burnt, nothing else in frame.',
        ),
        'render_stain': (
            'cloth',
            'A white linen apron spread flat on a plain wooden table in plain daylight, one dark brown stain spread across its front.',
        ),
        'render_mud': (
            'boot',
            'A pair of leather boots caked in wet brown mud, standing on a farmhouse yard floor, 1671, plain daylight.',
        ),
        'render_patina': (
            'brass',
            'A brass ship bell on the Kattenburg quay, 1671, plain daylight, its surface dulled green with age, seen close up.',
        ),
        'render_blood': (
            'cloth',
            'A white linen bandage on a plain wooden table in plain daylight, one dark red bloodstain soaked through its centre.',
        ),
        'render_scar': (
            'face',
            'Head and shoulders of a Dutch sailor, 1671, plain daylight, one long old scar across his left cheek, facing the camera, plain grey wall behind him.',
        ),
        'render_dent': (
            'metal',
            'A pewter tankard on a plain wooden table in plain daylight, one deep dent pushed into its side, nothing else on the table.',
        ),
        'render_peeling_paint': (
            'door',
            'A wooden door with green paint peeling off in curls, Amsterdam, 1671, plain daylight, seen straight on, nothing else in frame.',
        ),
        'render_wet_surface': (
            'stone',
            'Wet cobblestones on the Kattenburg quay after rain, 1671, plain daylight, the stones dark and shining, puddles between them.',
        ),
    }
)

SUBJECTS.update(
    {
        # ── Render: Text & number ──
        'render_text_letters': (
            'sign',
            'A weathered wooden board nailed to a brick wall, Amsterdam, 1671, plain daylight, the single word KATTENBURG painted on it in plain black capitals, nothing else written.',
        ),
        'render_text_word': (
            'sign',
            'A wooden crate on the Kattenburg quay, 1671, plain daylight, the single word HARING stencilled on its side in plain black capitals, nothing else written.',
        ),
        'render_text_sentence': (
            'sign',
            'A painted wooden notice board on the Kattenburg quay, 1671, plain daylight, reading DE WERF IS GESLOTEN in plain black capitals on one line, nothing else written.',
        ),
        'render_number_digits': (
            'sign',
            'A plain white painted board on a brick wall, Amsterdam, 1671, plain daylight, the digits 12345 painted on it in plain black, nothing else written.',
        ),
        'render_number_specific': (
            'sign',
            'A small enamelled house number plate beside a door, Amsterdam, 1671, plain daylight, the number 47 on it in plain black on white, nothing else written.',
        ),
        'render_number_date': (
            'stone',
            'A carved date stone set in a brick gable, Amsterdam, 1671, plain daylight, the year 1671 cut into it in plain numerals, nothing else carved.',
        ),
        'render_number_roman': (
            'stone',
            'A carved stone tablet on a church wall, Amsterdam, 1671, plain daylight, the roman numerals MDCLXXI cut into it, nothing else carved.',
        ),
        'render_clock_face': (
            'clock',
            'A church tower clock face, Amsterdam, 1671, plain daylight, seen straight on, roman hour numerals around the dial, both hands pointing clearly.',
        ),
        'render_handwriting': (
            'paper',
            'A sheet of paper on a plain wooden desk, Dutch office, 1671, plain daylight, four lines of neat brown ink handwriting on it, seen straight on.',
        ),
        'render_signage': (
            'sign',
            'A hanging painted tavern sign on an iron bracket, Amsterdam, 1671, plain daylight, reading DE GOUDEN LEEUW in plain black capitals, nothing else written.',
        ),
        'render_book_page': (
            'book',
            'An open printed book on a plain wooden desk, Dutch office, 1671, plain daylight, seen straight down, both pages full of printed lines of text.',
        ),
        'render_map_labels': (
            'map',
            'A printed sea chart of the Dutch coast on a plain wooden table, 1671, plain daylight, seen straight down, the names TEXEL and VLIELAND printed on it.',
        ),
        'render_symbol_crest': (
            'crest',
            'A carved and painted heraldic crest on a stone wall, Amsterdam, 1671, plain daylight, seen straight on, a shield with a rampant lion, no lettering.',
        ),
    }
)

SUBJECTS.update(
    {
        # ── Render: Objects ──
        'render_tool_hand': (
            'tool',
            'A shipwright adze lying on a plain wooden bench, Kattenburg yard, 1671, plain daylight, the whole tool in frame, nothing else on the bench.',
        ),
        'render_furniture': (
            'chair',
            'A single plain oak chair standing alone on a stone floor, Dutch farmhouse, 1671, plain daylight, the whole chair in frame, all four legs visible.',
        ),
        'render_container_barrel': (
            'barrel',
            'One wooden barrel standing upright on the Kattenburg quay, 1671, plain daylight, iron hoops around it, nothing else in frame.',
        ),
        'render_rope_rigging': (
            'rope',
            'Coiled hemp rope looped over an iron cleat on the Kattenburg quay, 1671, plain daylight, the coils neat and separate.',
        ),
        'render_weapon': (
            'sword',
            'A single naval cutlass lying on a plain wooden table, 1671, plain daylight, the whole blade and hilt in frame, nothing else on the table.',
        ),
        'render_instrument_music': (
            'violin',
            'A single baroque violin and its bow lying on a plain wooden table, 1671, plain daylight, the whole instrument in frame, four strings visible.',
        ),
        'render_lantern': (
            'lantern',
            'One iron and horn hand lantern standing on the Kattenburg quay, 1671, plain daylight, unlit, the whole lantern in frame.',
        ),
        'render_wheel_cart': (
            'wheel',
            'A wooden handcart standing alone in a farmhouse yard, 1671, plain daylight, both spoked wheels fully visible, nothing loaded on it.',
        ),
        'render_boat': (
            'boat',
            'A small wooden rowing boat moored alone at the Kattenburg quay, 1671, plain daylight, seen from the side, the whole hull in frame.',
        ),
        'render_ship_rigging': (
            'boat',
            'The rigging of a moored Dutch merchant ship, Kattenburg, 1671, plain daylight, masts, shrouds and ratlines seen from the quay against a plain sky.',
        ),
        'render_sail': (
            'sail',
            'One canvas sail set on a small Dutch boat, 1671, plain daylight, seen from the side on open water, the whole sail filled by the wind.',
        ),
        'render_quill_ink': (
            'pen',
            'A goose quill pen and an open stoneware inkpot on a plain wooden desk, Dutch office, 1671, plain daylight, nothing else on the desk.',
        ),
        'render_coins': (
            'coin',
            'Seven silver Dutch guilders lying scattered on a plain wooden table, 1671, plain daylight, each coin separate and fully visible.',
        ),
        'render_basket': (
            'basket',
            'One empty woven willow basket standing on the Kattenburg quay, 1671, plain daylight, the weave clearly visible, nothing inside it.',
        ),
        'render_glassware': (
            'glass',
            'One clear glass wine goblet standing on a plain wooden table, Dutch interior, 1671, plain daylight, empty, nothing else on the table.',
        ),
        'render_mirror': (
            'mirror',
            'A small framed looking glass hanging on a plain plastered wall, Dutch interior, 1671, plain daylight, seen at a slight angle so it reflects the room.',
        ),
    }
)

SUBJECTS.update(
    {
        # ── Render: Animals ──
        'render_animal_dog': (
            'dog',
            'One brown farm dog standing in a farmhouse yard, Holland, 1671, plain daylight, whole body in frame, seen from the side, nothing else present.',
        ),
        'render_animal_cat': (
            'cat',
            'One grey cat sitting on the Kattenburg quay, 1671, plain daylight, whole body in frame, seen from the side, nothing else present.',
        ),
        'render_animal_horse': (
            'horse',
            'One brown draught horse standing in a farmhouse yard, Holland, 1671, plain daylight, whole body in frame, seen from the side, unharnessed.',
        ),
        'render_animal_cow': (
            'cow',
            'One black and white dairy cow standing in a flat grass field, Holland, 1671, plain daylight, whole body in frame, seen from the side.',
        ),
        'render_animal_sheep': (
            'sheep',
            'Three sheep standing together in a flat grass field, Holland, 1671, plain daylight, all three whole bodies in frame, seen from the side.',
        ),
        'render_animal_chicken': (
            'bird',
            'One brown hen standing on the bare earth of a farmhouse yard, Holland, 1671, plain daylight, whole body in frame, seen from the side.',
        ),
        'render_animal_bird_flying': (
            'bird',
            'One herring gull in flight over the Kattenburg quay, 1671, plain daylight, wings fully spread, seen from the side against a plain sky.',
        ),
        'render_animal_fish': (
            'fish',
            'One live pike underwater in a clear Dutch canal, daylight from above, whole fish in frame, seen from the side, nothing else in view.',
        ),
        'render_animal_insect': (
            'insect',
            'One honeybee on a single white flower in a farmhouse garden, Holland, 1671, plain daylight, seen close up from the side, wings and legs visible.',
        ),
        'render_creature_invented': (
            'creature',
            'One invented creature stands alone in a farmhouse yard, Holland, 1671, plain daylight: a goat-sized animal with the head of a heron and six legs, whole body in frame.',
        ),
    }
)

SUBJECTS.update(
    {
        # ── Render: Nature & weather ──
        'render_tree': (
            'tree',
            'One bare elm tree standing alone in a flat Dutch field, 1671, plain daylight, the whole tree in frame, nothing else in view.',
        ),
        'render_forest': (
            'tree',
            'A dense stand of oak and beech trees in daylight, Holland, 1671, seen from inside the wood, no people and no buildings.',
        ),
        'render_grass_field': (
            'field',
            'A flat open Dutch meadow of long green grass, 1671, plain daylight, a low horizon, no animals, no people, no buildings.',
        ),
        'render_water_still': (
            'water',
            'The flat unbroken surface of an Amsterdam canal at dawn, 1671, plain daylight, no wind, no boats, no people, seen from the quayside.',
        ),
        'render_water_waves': (
            'water',
            'Open sea with steep breaking waves under plain daylight, Dutch coast, 1671, no boats and no land in view, seen from just above the water.',
        ),
        'render_water_reflection': (
            'water',
            'A brick canal house reflected in the still water of an Amsterdam canal, 1671, plain daylight, the reflection clearly visible below the house.',
        ),
        'render_rain': (
            'rain',
            'Heavy rain falling on the Kattenburg quay, 1671, daylight, the cobbles wet and splashing, visible rain streaks in the air, nobody present.',
        ),
        'render_snow': (
            'snow',
            'Fresh snow lying over a flat Dutch field and a bare hedge, 1671, plain daylight, snow still falling, no people and no animals.',
        ),
        'render_fire': (
            'fire',
            'An open log fire burning in a Dutch farmhouse hearth, 1671, flames clearly alight, nobody present, nothing else in frame.',
        ),
        'render_smoke': (
            'smoke',
            'Grey smoke rising in a thick column from a farmhouse chimney, Holland, 1671, plain daylight, against a plain pale sky, nobody present.',
        ),
        'render_fog': (
            'fog',
            'Thick fog over an Amsterdam canal at first light, 1671, the far bank barely visible through it, no boats and no people.',
        ),
        'render_sky_clouds': (
            'sky',
            'A wide Dutch sky of tall white cumulus clouds over a low flat horizon, 1671, plain daylight, no buildings and no people.',
        ),
        'render_night': (
            'night',
            'The Kattenburg quay at night, 1671, lit only by a full moon, the cobbles and the moored hulls just visible, nobody present.',
        ),
        'render_rock_mountain': (
            'rock',
            'A bare grey rock outcrop rising from open moorland, plain daylight, the whole outcrop in frame, no people and no buildings.',
        ),
    }
)

SUBJECTS.update(
    {
        # ── Render: Built environment ──
        'render_door': (
            'door',
            'A single studded oak front door in a brick house front, Amsterdam, 1671, plain daylight, seen straight on, closed, nothing else in frame.',
        ),
        'render_window_intact': (
            'window',
            'One leaded farmhouse window, whole and unbroken, 1671, plain daylight, seen straight on from outside, every pane intact.',
        ),
        'render_roof': (
            'roof',
            'The red pantile roof of a Dutch farmhouse, 1671, plain daylight, seen from below at an angle, the whole roof slope in frame.',
        ),
        'render_stairs': (
            'stairs',
            'A narrow wooden staircase inside a Dutch canal house, 1671, plain daylight from a window, seen from the bottom looking up, every tread visible.',
        ),
        'render_brick_wall': (
            'wall',
            'A plain Dutch brick wall in daylight, 1671, seen straight on, the courses and mortar joints clearly visible, nothing else in frame.',
        ),
        'render_timber_frame': (
            'building',
            'The exposed oak frame of a half-built Dutch barn, 1671, plain daylight, the posts, beams and braces clearly visible, nobody present.',
        ),
        'render_interior_room': (
            'room',
            'The inside of a Dutch farmhouse room, 1671, daylight through one window, a table, two chairs and a tiled floor, nobody present.',
        ),
        'render_street': (
            'street',
            'A narrow Amsterdam street of brick canal houses, 1671, plain daylight, seen along its length, nobody present, no boats.',
        ),
        'render_bridge': (
            'bridge',
            'One arched brick bridge over an Amsterdam canal, 1671, plain daylight, seen from the side along the water, nobody on it.',
        ),
        'render_harbour': (
            'boat',
            'The Kattenburg harbour, 1671, plain daylight, several Dutch merchant ships moored along a stone quay, seen from across the water.',
        ),
        'render_church': (
            'church',
            'A Dutch brick church with a tall tower, 1671, plain daylight, seen whole from across an open square, nobody present.',
        ),
    }
)

SUBJECTS.update(
    {
        # ── Render: Clothing ──
        'render_dress_period': (
            'person',
            'A Dutch woman stands alone in a farmhouse yard, 1671, plain daylight, in a black wool bodice, grey skirt, white linen collar and cap, whole body in frame.',
        ),
        'render_armour': (
            'person',
            'A Dutch soldier stands alone in an open square, 1671, plain daylight, in a steel breastplate and helmet over a buff coat, whole body in frame.',
        ),
        'render_hat': (
            'hat',
            'A Dutch shipwright stands alone on the Kattenburg quay, 1671, plain daylight, wearing one black wide-brimmed felt hat, head and shoulders in frame.',
        ),
        'render_cloak': (
            'person',
            'A Dutch merchant stands alone on the Kattenburg quay, 1671, plain daylight, in a long dark wool cloak fastened at the throat, whole body in frame.',
        ),
        'render_cloth_folds': (
            'cloth',
            'A heavy grey wool curtain hanging from an iron rod, Dutch interior, 1671, daylight from one side, deep folds running down its length.',
        ),
        'render_layered_clothing': (
            'person',
            'A Dutch dockworker stands alone on the Kattenburg quay, 1671, plain daylight, in a linen shirt, a wool waistcoat and an open coat over both, whole body in frame.',
        ),
        'render_footwear_period': (
            'shoe',
            'One pair of black leather buckled shoes standing on a stone floor, Dutch interior, 1671, plain daylight, seen from the side, nothing else in frame.',
        ),
    }
)

assert len(SUBJECTS) == 132, len(SUBJECTS)
