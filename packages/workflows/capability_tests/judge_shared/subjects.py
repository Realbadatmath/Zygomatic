# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

from __future__ import annotations

# ── fixtures ──────────────────────────────────────────────────────────────────────────
FIX = 'capability_tests/fixtures/judge'
SUBJ_DIR = FIX + '/subjects'
PAIR_DIR = FIX + '/pairs'
LADDER_DIR = FIX + '/ladders'
PROMPT_DIR = FIX + '/prompt'

# Every subject render uses this stem plus the subject's own clause. Stem is 11 words; no
# clause below is over 30, so no prompt reaches 60 words — SDXL truncates at 77 CLIP tokens
# and says nothing, so the bank stays well inside it.
SUBJECT_PROMPT = 'Seventeenth-century Dutch scene, daylight, plain background, photographic, sharp focus: {clause}'
SUBJECT_NEG_RULE = (
    'the same seed and the same prompt with the subject clause removed, unless the subject '
    'has an entry in NEG — a matched contrast (one person instead of two, the same hand with '
    'four fingers, the same window intact) that a yes-biased judge cannot pass by guessing'
)

# id -> (label asked about, synonyms the Names answer may use, the render clause)
SUBJECTS = {
    # ── People (12) ──
    'person_one': (
        'one person',
        'person|man|woman|figure|dockworker|sailor',
        'one dockworker standing alone on a quay',
    ),
    'person_two': (
        'two people',
        'two people|two men|two figures|pair|couple',
        'two dockworkers standing side by side on a quay',
    ),
    'person_three': (
        'three people',
        'three people|three men|three figures|trio',
        'three dockworkers standing in a row on a quay',
    ),
    'person_group': (
        'a group of five or more people',
        'group|five people|six people|several people|gathering',
        'six dockworkers gathered around a crate on a quay',
    ),
    'person_crowd': (
        'a crowd',
        'crowd|many people|throng|dozens of people|market crowd',
        'a crowd of about forty people filling a market square',
    ),
    'child': ('a child', 'child|boy|girl|kid|young child', 'a child of about eight years old standing on a quay'),
    'infant': ('an infant', 'infant|baby|newborn|swaddled baby', 'a woman holding a swaddled baby in both arms'),
    'teen': (
        'a teenager',
        'teenager|teen|youth|adolescent|young man|young woman',
        'a youth of about fifteen carrying a wicker basket',
    ),
    'elderly': (
        'an elderly person',
        'elderly|old man|old woman|old person|elder',
        'an old man with a white beard seated on a bench',
    ),
    'person_back': (
        'a person seen from behind',
        'person|man|woman|figure|back view|from behind',
        'a man seen from behind walking away along a quay',
    ),
    'person_distant': (
        'a person far from the camera',
        'person|man|woman|figure|distant figure',
        'one small figure far away at the end of a long quay',
    ),
    'person_partial': (
        'a person half out of frame',
        'person|man|woman|figure|partial figure',
        'a man cropped by the frame edge, only his left half in view',
    ),
    # ── The body (19) ──
    'face_front': (
        'a face seen front on',
        'face|head|portrait|man|woman',
        'a head-and-shoulders portrait facing the camera straight on',
    ),
    'face_profile': (
        'a face in profile',
        'face|profile|head|side view',
        'a head-and-shoulders portrait turned fully to the side',
    ),
    'face_three_quarter': (
        'a face three-quarter on',
        'face|three-quarter|head|portrait',
        'a head-and-shoulders portrait turned halfway between front and side',
    ),
    'eyes_pair': (
        'a matched pair of eyes',
        'eyes|pair of eyes|both eyes',
        'a close crop of a face with both eyes open and level',
    ),
    'gaze': (
        'a gaze with a direction',
        'gaze|looking|glance|eyes looking',
        'a close crop of a face looking hard to the left of frame',
    ),
    'teeth': (
        'teeth',
        'teeth|tooth|smile showing teeth',
        'a close crop of a laughing mouth with the upper teeth showing',
    ),
    'ears': ('an ear', 'ear|ears', 'a close crop of the side of a head with the ear uncovered'),
    'hair_long': ('long hair', 'long hair|hair', 'a woman with straight hair falling past her shoulders'),
    'hair_curly': ('curly hair', 'curly hair|curls|ringlets|hair', 'a man with a head of tight dark curls'),
    'beard': ('a beard', 'beard|bearded|whiskers', 'a man with a full grey beard to his collar'),
    'hand_one': ('one hand', 'hand|a hand|one hand', 'one bare hand held open in front of a plank wall'),
    'hand_two': (
        'two hands',
        'hands|two hands|both hands',
        'two bare hands held open side by side before a plank wall',
    ),
    'hand_holding': (
        'a hand holding an object',
        'hand holding|holding|hand with|grasping',
        'a hand holding a caulking mallet by its handle',
    ),
    'hand_gripping': (
        'a hand gripping a rope',
        'gripping|grip|clenched hand|fist on rope',
        'a hand closed tight around a thick tarred rope',
    ),
    'fingers_count': (
        'five countable fingers on one hand',
        'five fingers|fingers|hand',
        'one open hand palm to camera, fingers spread and separate',
    ),
    'feet_bare': ('bare feet', 'bare feet|barefoot|feet', 'a pair of bare feet on wet planking'),
    'feet_shoes': (
        'feet in shoes',
        'shoes|boots|clogs|feet in shoes',
        'a pair of feet in buckled leather shoes on planking',
    ),
    'arms_crossed': (
        'arms crossed',
        'arms crossed|crossed arms|folded arms',
        'a man standing with his arms folded across his chest',
    ),
    'muscle_flex': (
        'a flexed muscle',
        'flexed muscle|muscle|bicep|flexing',
        'a bare forearm and upper arm with the bicep flexed',
    ),
    # ── Food (12) ──
    'food_present': ('food', 'food|meal|provisions|victuals', 'a board with bread, cheese and apples laid on it'),
    'food_bread': ('bread', 'bread|loaf|rye bread|bun', 'a dark round rye loaf on a wooden board'),
    'food_fruit': ('fruit', 'fruit|apples|pears|grapes', 'a bowl of apples and pears on a table'),
    'food_vegetables': (
        'vegetables',
        'vegetables|carrots|cabbage|turnips|onions',
        'carrots, cabbage and onions heaped on a table',
    ),
    'food_meat_raw': ('raw meat', 'raw meat|uncooked meat|meat|raw beef', 'a cut of raw red beef on a butcher block'),
    'food_meat_cooked': (
        'cooked meat',
        'cooked meat|roast|roasted meat|meat',
        'a browned roasted joint of meat on a pewter dish',
    ),
    'food_fish': ('fish as food', 'fish|herring|cod|fish as food', 'three gutted herring laid on a market slab'),
    'food_soup': (
        'soup or stew in a bowl',
        'soup|stew|broth|pottage',
        'an earthenware bowl of thick brown stew with a spoon',
    ),
    'food_plated': (
        'a plated meal',
        'plated meal|plate of food|meal|dinner plate',
        'a pewter plate with meat, bread and greens arranged on it',
    ),
    'food_drink': (
        'a drink in a vessel',
        'drink|beer|wine|tankard|cup of drink',
        'a pewter tankard filled with beer on a table',
    ),
    'food_table': (
        'a laid table',
        'laid table|set table|table laid|dining table',
        'a table laid with plates, knives, bread and a jug',
    ),
    'food_spoiled': (
        'spoiled food',
        'spoiled food|mouldy food|rotten food|mould',
        'a loaf and cheese covered in green and white mould',
    ),
    # ── Damage & wear (18) ──
    'broken_wood': (
        'broken wood',
        'broken wood|splintered wood|cracked plank|split timber',
        'a plank snapped through with splinters standing out',
    ),
    'broken_glass': (
        'broken glass',
        'broken glass|shattered glass|glass shards',
        'shards of clear glass scattered on a stone floor',
    ),
    'broken_window': (
        'a broken window',
        'broken window|smashed window|shattered window',
        'a leaded window with two panes smashed out',
    ),
    'broken_pottery': (
        'broken pottery',
        'broken pottery|shattered pot|broken jug|potsherds',
        'an earthenware jug shattered into pieces on flagstones',
    ),
    'cracked_wall': (
        'a cracked wall',
        'cracked wall|crack|fissure in wall',
        'a plastered wall with a long jagged crack running down it',
    ),
    'torn_cloth': ('torn cloth', 'torn cloth|ripped cloth|tear|rip', 'a length of wool cloth with a long ragged tear'),
    'frayed_rope': (
        'a frayed rope',
        'frayed rope|fraying|worn rope|unravelling rope',
        'a hemp rope unravelling into loose fibres at its end',
    ),
    'rust': ('rust', 'rust|rusty|corrosion|rusted iron', 'an iron hinge covered in orange rust'),
    'rot': ('rot or mould', 'rot|rotten|mould|mildew|decay', 'a damp timber post furred with grey-green mould'),
    'burnt': (
        'burnt or charred material',
        'burnt|charred|scorched|blackened',
        'a charred black beam end with cracked scorched grain',
    ),
    'stain': ('a stain', 'stain|stained|blotch|discolouration', 'a pale linen cloth with a dark brown spreading stain'),
    'mud': ('mud and dirt', 'mud|muddy|dirt|filth', 'a pair of clogs caked in thick wet brown mud'),
    'patina': (
        'wear and patina from use',
        'patina|worn|wear|polished by use|aged surface',
        'a wooden handle darkened and polished smooth by long use',
    ),
    'blood': ('blood', 'blood|bloody|bloodstain', 'a linen bandage with a fresh red bloodstain'),
    'scar': ('a scar or wound', 'scar|wound|gash|cut', 'a forearm with a long pale healed scar across it'),
    'dent': ('a dent in metal', 'dent|dented|dint|hammered metal', 'a pewter tankard with a deep dent in its side'),
    'peeling_paint': (
        'peeling paint',
        'peeling paint|flaking paint|blistered paint',
        'a green painted door with paint curling and flaking off',
    ),
    'wet_surface': (
        'a wet surface',
        'wet|wet surface|soaked|water on the surface',
        'planking soaked dark with water, pooled and reflective',
    ),
    # ── Text & number (13) ──
    'text_letters': (
        'legible letters',
        'letters|lettering|text|writing',
        'a painted shop board with large clear capital letters',
    ),
    'text_word': (
        'the word KATTENBURG',
        'KATTENBURG|word|sign|lettering',
        'a painted shop board reading KATTENBURG in large capitals',
    ),
    'text_sentence': (
        'a whole legible sentence',
        'sentence|line of text|written sentence|notice',
        'a posted paper notice with one full sentence in clear print',
    ),
    'number_digits': ('digits', 'digits|numbers|numerals|figures', 'a painted board showing large clear digits'),
    'number_specific': ('the number 1671', '1671|number|digits', 'a carved stone tablet showing the number 1671'),
    'number_date': ('the date 12 MEI 1671', '12 MEI 1671|date|12 mei', 'a carved stone tablet reading 12 MEI 1671'),
    'number_roman': (
        'the roman numerals MDCLXXI',
        'MDCLXXI|roman numerals|roman numeral',
        'a carved stone tablet reading MDCLXXI',
    ),
    'clock_face': (
        'a clock face reading ten past four',
        'clock|clock face|dial|ten past four',
        'a church clock face with hands at ten minutes past four',
    ),
    'handwriting': (
        'handwriting',
        'handwriting|handwritten|written by hand|script',
        'a page of brown ink handwriting in a ledger',
    ),
    'signage': (
        'a sign or shop board',
        'sign|shop board|signboard|hanging sign',
        'a painted wooden shop board hanging above a doorway',
    ),
    'book_page': (
        'a page of a book',
        'book page|page|open book|book',
        'an open printed book showing one full page of type',
    ),
    'map_labels': (
        'a labelled map or chart',
        'map|chart|labelled map|sea chart',
        'a sea chart with coastline and place names lettered on it',
    ),
    'symbol_crest': (
        'a crest, flag or emblem',
        'crest|coat of arms|emblem|flag|arms',
        'a carved painted coat of arms above a doorway',
    ),
    # ── Objects (16) ──
    'tool_hand': (
        'a hand tool',
        'tool|mallet|chisel|hammer|hand tool',
        'a caulking mallet and a chisel lying on a bench',
    ),
    'furniture': (
        'furniture',
        'furniture|table|chair|bench|cupboard',
        'a heavy oak table with two chairs in a bare room',
    ),
    'container_barrel': (
        'barrels and crates',
        'barrel|barrels|cask|crate|crates',
        'three tarred barrels beside a stack of wooden crates',
    ),
    'rope_rigging': (
        'rope and rigging',
        'rope|rigging|cordage|lines',
        'coils of tarred rope and rigging lines on a quay',
    ),
    'weapon': ('a weapon', 'weapon|sword|musket|pike|blade', 'a sword and a musket propped against a plank wall'),
    'instrument_music': (
        'a musical instrument',
        'instrument|violin|lute|fiddle|musical instrument',
        'a lute lying on a table beside sheet music',
    ),
    'lantern': ('a lantern or candle', 'lantern|candle|lamp|light', 'a lit horn lantern hanging from a hook'),
    'wheel_cart': (
        'a wheel or cart',
        'wheel|cart|wagon|cartwheel',
        'a wooden handcart with two spoked wheels on cobbles',
    ),
    'boat': ('a boat', 'boat|rowing boat|dinghy|skiff', 'a small wooden rowing boat moored at a quay'),
    'ship_rigging': (
        'a ship with rigging',
        'ship|vessel|rigging|masts|pinas',
        'a moored merchant ship with masts and standing rigging',
    ),
    'sail': ('sails', 'sail|sails|canvas', 'a ship under two full set canvas sails'),
    'quill_ink': (
        'a quill and inkpot',
        'quill|pen|inkpot|inkwell|ink',
        'a goose quill standing in a pewter inkpot beside a ledger',
    ),
    'coins': ('coins or money', 'coins|money|silver coins|guilders', 'a scatter of silver coins on a dark table'),
    'basket': ('a basket', 'basket|wicker basket|hamper', 'a woven wicker basket on flagstones'),
    'glassware': (
        'glassware',
        'glass|glassware|goblet|drinking glass|roemer',
        'a green glass roemer goblet on a table',
    ),
    'mirror': (
        'a mirror with a reflection',
        'mirror|looking glass|reflection in a mirror',
        'a framed wall mirror showing a room reflected in it',
    ),
    # ── Animals (10) ──
    'animal_dog': ('a dog', 'dog|hound|mastiff|pup', 'a short-haired brown dog standing on a quay'),
    'animal_cat': ('a cat', 'cat|tomcat|kitten', 'a grey cat sitting on a doorstep'),
    'animal_horse': ('a horse', 'horse|cart horse|mare|nag', 'a harnessed cart horse standing at the end of a quay'),
    'animal_cow': ('cattle', 'cow|cattle|ox|bull|heifer', 'two black and white cows standing in a field'),
    'animal_sheep': ('sheep', 'sheep|ewe|lamb|flock', 'four sheep grazing behind a hurdle fence'),
    'animal_chicken': ('poultry', 'chicken|hen|cock|poultry|fowl', 'a hen and two chicks scratching in a yard'),
    'animal_bird_flying': (
        'a bird in flight',
        'bird|gull|bird in flight|flying bird',
        'a gull in flight with wings spread above a harbour',
    ),
    'animal_fish': ('a fish', 'fish|pike|carp|live fish', 'a live carp in the shallows of a clear canal'),
    'animal_insect': ('an insect', 'insect|fly|bee|beetle|moth', 'a close crop of a beetle on a green leaf'),
    'creature_invented': (
        'an invented creature',
        'creature|beast|monster|invented creature|griffin',
        'a carved griffin with a lion body and an eagle head',
    ),
    # ── Nature & weather (14) ──
    'tree': ('a tree', 'tree|oak|elm|single tree', 'one bare-branched elm standing in an open field'),
    'forest': ('woodland', 'forest|wood|woodland|trees', 'a stand of close-grown beech trees seen from within'),
    'grass_field': ('grass or a field', 'grass|field|meadow|pasture', 'a flat green meadow running to a low horizon'),
    'water_still': (
        'still water',
        'still water|calm water|flat water|canal',
        'a canal with a flat unbroken mirror-still surface',
    ),
    'water_waves': (
        'waves',
        'waves|swell|breaking water|choppy water',
        'open sea with steep breaking white-capped waves',
    ),
    'water_reflection': (
        'a reflection in water',
        'reflection|reflected|mirrored in water',
        'a gabled house reflected whole in a still canal',
    ),
    'rain': ('rain', 'rain|raining|downpour|rainfall', 'heavy rain falling in visible streaks over a wet street'),
    'snow': ('snow', 'snow|snowy|snowfall|snow-covered', 'a street and rooftops under a thick cover of snow'),
    'fire': ('fire', 'fire|flames|blaze|burning', 'a hearth fire with high yellow flames'),
    'smoke': ('smoke', 'smoke|smoky|plume of smoke', 'a thick grey plume of smoke rising from a chimney'),
    'fog': ('fog or mist', 'fog|mist|haze|misty', 'a quay swallowed in dense low fog, shapes barely visible'),
    'sky_clouds': (
        'sky and cloud',
        'sky|clouds|cloudy sky|cloud',
        'a wide sky filled with tall grey and white cumulus',
    ),
    'night': ('night', 'night|nighttime|dark|after dark', 'a canal street at night, dark sky, lit windows'),
    'rock_mountain': (
        'rock and mountain',
        'rock|rocks|mountain|cliff|crag',
        'a bare rock cliff face rising above a shoreline',
    ),
    # ── Built environment (11) ──
    'door': ('a door', 'door|doorway|entrance', 'a studded wooden door set in a brick wall'),
    'window_intact': (
        'an intact window',
        'window|intact window|leaded window|glazing',
        'a leaded window with every pane whole',
    ),
    'roof': ('a roof', 'roof|rooftop|tiled roof|roofline', 'a steep pantiled roof seen against the sky'),
    'stairs': ('stairs', 'stairs|staircase|steps|stairway', 'a narrow wooden staircase rising inside a house'),
    'brick_wall': ('a brick wall', 'brick wall|brickwork|bricks', 'a flat wall of small red bricks in regular courses'),
    'timber_frame': (
        'timber framing',
        'timber frame|half-timbered|timber framing|beams',
        'a half-timbered gable with exposed dark beams',
    ),
    'interior_room': (
        'a room interior',
        'room|interior|indoors|chamber',
        'a plain tiled room with a table, a chair and a window',
    ),
    'street': ('a street', 'street|lane|road|alley', 'a narrow cobbled street between tall brick houses'),
    'bridge': ('a bridge', 'bridge|footbridge|arched bridge', 'a humped stone bridge crossing a canal'),
    'harbour': ('a harbour or quay', 'harbour|quay|dock|wharf|port', 'a stone quay with moored ships and a crane'),
    'church': ('a church', 'church|chapel|kerk|church tower', 'a brick church with a tall square tower'),
    # ── Clothing (7) ──
    'dress_period': (
        'period dress',
        'period dress|seventeenth-century clothing|ruff|doublet|gown',
        'a woman in a dark gown with a white linen collar and cap',
    ),
    'armour': ('armour', 'armour|breastplate|cuirass|helmet|armor', 'a steel breastplate and helmet on a stand'),
    'hat': ('a hat', 'hat|cap|broad-brimmed hat|headwear', 'a man in a tall broad-brimmed black felt hat'),
    'cloak': ('a cloak', 'cloak|mantle|cape', 'a man in a long dark wool cloak to his calves'),
    'cloth_folds': (
        'cloth folds',
        'folds|drapery|creases|folded cloth',
        'a heavy curtain hanging in deep vertical folds',
    ),
    'layered_clothing': (
        'layered clothing',
        'layers|layered clothing|coat over jacket|several layers',
        'a man in a shirt, waistcoat and open overcoat, all three visible',
    ),
    'footwear_period': (
        'period footwear',
        'clogs|buckled shoes|period shoes|footwear',
        'a pair of wooden clogs beside buckled leather shoes',
    ),
}

# Where the generic "same seed, subject clause removed" negative would be too easy or would
# change the whole picture, the negative is a MATCHED CONTRAST instead. A yes-biased judge
# cannot pass these by guessing, and a judge that only counts cannot pass them by counting.
NEG = {
    'person_two': 'one dockworker instead of two, same seed, same quay',
    'person_three': 'two dockworkers instead of three, same seed',
    'person_group': 'three dockworkers instead of six, same seed',
    'person_crowd': 'six people in the same square instead of forty, same seed',
    'child': 'a grown adult of the same build in the same pose, same seed',
    'infant': 'the same woman holding a folded bundle of cloth, same seed',
    'teen': 'a grown man of about forty in the same pose with the same basket',
    'elderly': 'a man of about twenty-five with the same beard and pose',
    'person_back': 'the same man facing the camera, same seed, same quay',
    'person_distant': 'the same man close to the camera, same seed',
    'person_partial': 'the same man fully inside the frame, same seed',
    'face_front': 'the same head turned fully to profile, same seed',
    'face_profile': 'the same head facing the camera straight on, same seed',
    'face_three_quarter': 'the same head facing the camera straight on, same seed',
    'eyes_pair': 'the same face with both eyes shut, same seed',
    'gaze': 'the same face with both eyes shut, same seed',
    'teeth': 'the same mouth closed, lips together, same seed',
    'ears': 'the same head with the ear fully covered by hair and a cap',
    'hair_long': 'the same head cropped short, same seed',
    'hair_curly': 'the same head with dead-straight hair, same seed',
    'beard': 'the same face clean shaven, same seed',
    'hand_two': 'one hand instead of two, same seed, same wall',
    'hand_holding': 'the same open hand with nothing in it, the mallet on the bench behind',
    'hand_gripping': 'the same hand open flat beside the same rope, same seed',
    'fingers_count': 'the same open hand with FOUR fingers — the render defect this column exists for',
    'feet_bare': 'the same feet in buckled leather shoes, same seed',
    'feet_shoes': 'the same feet bare, same seed',
    'arms_crossed': 'the same man with both arms hanging at his sides, same seed',
    'muscle_flex': 'the same arm hanging relaxed, same seed',
    'food_meat_raw': 'the same cut of meat browned and cooked, same seed',
    'food_meat_cooked': 'the same joint raw and red, same seed',
    'food_spoiled': 'the same loaf and cheese fresh and unspoiled, same seed',
    'broken_window': 'the same leaded window with every pane whole, same seed',
    'window_intact': 'the same leaded window with two panes smashed out, same seed',
    'text_word': 'the same board reading VLOOIENBURG instead of KATTENBURG, same seed',
    'number_specific': 'the same tablet showing 1617 instead of 1671, same seed',
    'number_date': 'the same tablet reading 12 MEI 1617, same seed',
    'number_roman': 'the same tablet reading MDCXVII, same seed',
    'clock_face': 'the same clock with hands at twenty to nine, same seed',
    'water_still': 'the same canal with the surface broken into choppy waves, same seed',
    'water_waves': 'the same sea flat and unbroken, same seed',
    'night': 'the same canal street in full daylight, same seed',
    'wet_surface': 'the same planking bone dry, same seed',
    'mud': 'the same clogs clean and dry, same seed',
    'rust': 'the same iron hinge new and clean, same seed',
    'rot': 'the same timber post dry and sound, same seed',
    'peeling_paint': 'the same green door freshly painted and whole, same seed',
    'frayed_rope': 'the same rope whipped and sound at its end, same seed',
    'animal_cat': 'the same doorstep with a folded sack on it and no cat',
    'creature_invented': 'a carved lion with no eagle head and no wings, same seed',
}

# Subjects a machine can also decide, and which detector decides them. Where a subject is in
# this table the mechanical reading is the KEY and the model's answer is scored against it;
# where it is not, the operator's blind pass is the only key (see operator_protocol).
MECHANICAL = {
    'person_one': ('person_count', {'count': 1}),
    'person_two': ('person_count', {'count': 2}),
    'person_three': ('person_count', {'count': 3}),
    'person_group': ('person_count', {'count': 6}),
    'person_distant': ('person_count', {'count': 1}),
    'person_partial': ('person_count', {'count': 1}),
    'person_back': ('person_count', {'count': 1}),
    'child': ('person_count', {'count': 1}),
    'teen': ('person_count', {'count': 1}),
    'elderly': ('person_count', {'count': 1}),
    'face_front': ('face_count', {'count': 1}),
    'face_profile': ('face_count', {'count': 1}),
    'face_three_quarter': ('face_count', {'count': 1}),
    'hand_one': ('mediapipe_hands', {'hands': 1, 'fingers': 5}),
    'hand_two': ('mediapipe_hands', {'hands': 2, 'fingers': 5}),
    'hand_holding': ('mediapipe_hands', {'hands': 1, 'fingers': 5}),
    'hand_gripping': ('mediapipe_hands', {'hands': 1, 'fingers': 5}),
    'fingers_count': ('mediapipe_hands', {'hands': 1, 'fingers': 5}),
    'text_letters': ('ocr_equals', {'text': 'KATTENBURG', 'engine': 'the typography OCR judge'}),
    'text_word': ('ocr_equals', {'text': 'KATTENBURG', 'engine': 'the typography OCR judge'}),
    'text_sentence': (
        'ocr_equals',
        {'text': 'DE POORT SLUIT BIJ ZONSONDERGANG.', 'engine': 'the typography OCR judge'},
    ),
    'number_digits': ('ocr_equals', {'text': '1671', 'engine': 'the typography OCR judge'}),
    'number_specific': ('ocr_equals', {'text': '1671', 'engine': 'the typography OCR judge'}),
    'number_date': ('ocr_equals', {'text': '12 MEI 1671', 'engine': 'the typography OCR judge'}),
    'number_roman': ('ocr_equals', {'text': 'MDCLXXI', 'engine': 'the typography OCR judge'}),
    'clock_face': (
        'ocr_equals',
        {'text': '10:10 past four on the dial', 'engine': 'the typography OCR judge reading the hand angles'},
    ),
    'signage': ('ocr_equals', {'text': 'KATTENBURG', 'engine': 'the typography OCR judge'}),
}


# ── the two questions, asked in the defect bench's wording style: one crop, one question ──
SEE_Q = 'Look at this picture. Is there {label} in it? Answer yes or no, one word only.'
NAME_Q = 'Look at this picture. List the things you can see in it, as short nouns separated by commas. Nothing else.'

HOW_TO_VERIFY = (
    'The operator opens the contact sheet of this subject once (the pos render beside its neg render, '
    'subject id and label printed under the pair) and confirms in writing that the POSITIVE picture shows '
    'the subject its label names and the NEGATIVE picture does not. No VLM is asked — the 2026-09-27 '
    'defect bench is why. Until that confirmation is recorded the fixture stays verified: False and the '
    'columns it blocks are written untested with the note "key unverified".'
)
