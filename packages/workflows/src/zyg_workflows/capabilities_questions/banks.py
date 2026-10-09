# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The shared subject/capacity/reasoning banks and which step is asked which of them."""

from __future__ import annotations

from zyg_workflows.capabilities_questions.core import q


# ═══════════════════════════════════════════════════════════════════════ BANKS
# A five-question sheet flatters everything on it. So does a fifty-question sheet that
# only asks about the things someone already thought of. These banks ask the same concrete
# inventory of SUBJECTS of every tool that has to render, see or model them, so "can it do
# hands" and "can it do a broken window" are asked in the same words in every sheet and the
# answers can be read across steps.
#
# SUBJECTS   one entry per thing that shows up in our footage.
# Applied through subject_bank(): as "renders X correctly" for a generator, as "sees X" and
# "identifies X" for a judge or detector, as "models X" for geometry.

SUBJECTS = [
    # people
    ('person_one', 'One person', 'People'),
    ('person_two', 'Two people together', 'People'),
    ('person_three', 'Three people', 'People'),
    ('person_group', 'A group of five or more', 'People'),
    ('person_crowd', 'A crowd', 'People'),
    ('child', 'A child', 'People'),
    ('infant', 'An infant', 'People'),
    ('teen', 'A teenager', 'People'),
    ('elderly', 'An elderly person', 'People'),
    ('person_back', 'A person from behind', 'People'),
    ('person_distant', 'A person far from camera', 'People'),
    ('person_partial', 'A person half out of frame', 'People'),
    # the body
    ('face_front', 'A face, front on', 'The body'),
    ('face_profile', 'A face in profile', 'The body'),
    ('face_three_quarter', 'A face three-quarter on', 'The body'),
    ('eyes_pair', 'A matched pair of eyes', 'The body'),
    ('gaze', 'A gaze with a direction', 'The body'),
    ('teeth', 'Teeth', 'The body'),
    ('ears', 'Ears', 'The body'),
    ('hair_long', 'Long hair', 'The body'),
    ('hair_curly', 'Curly hair', 'The body'),
    ('beard', 'A beard', 'The body'),
    ('hand_one', 'One hand', 'The body'),
    ('hand_two', 'Two hands', 'The body'),
    ('hand_holding', 'A hand holding an object', 'The body'),
    ('hand_gripping', 'A hand gripping a rope or handle', 'The body'),
    ('fingers_count', 'Five countable fingers', 'The body'),
    ('feet_bare', 'Bare feet', 'The body'),
    ('feet_shoes', 'Feet in shoes', 'The body'),
    ('arms_crossed', 'Arms crossed', 'The body'),
    ('muscle_flex', 'A flexed muscle', 'The body'),
    # food
    ('food_present', 'Food', 'Food'),
    ('food_bread', 'Bread', 'Food'),
    ('food_fruit', 'Fruit', 'Food'),
    ('food_vegetables', 'Vegetables', 'Food'),
    ('food_meat_raw', 'Raw meat', 'Food'),
    ('food_meat_cooked', 'Cooked meat', 'Food'),
    ('food_fish', 'Fish as food', 'Food'),
    ('food_soup', 'Soup or stew in a bowl', 'Food'),
    ('food_plated', 'A plated meal', 'Food'),
    ('food_drink', 'A drink in a vessel', 'Food'),
    ('food_table', 'A laid table', 'Food'),
    ('food_spoiled', 'Spoiled food', 'Food'),
    # damage and wear — the class the operator asked about by name
    ('broken_wood', 'Broken wood', 'Damage & wear'),
    ('broken_glass', 'Broken glass', 'Damage & wear'),
    ('broken_window', 'A broken window', 'Damage & wear'),
    ('broken_pottery', 'Broken pottery', 'Damage & wear'),
    ('cracked_wall', 'A cracked wall', 'Damage & wear'),
    ('torn_cloth', 'Torn cloth', 'Damage & wear'),
    ('frayed_rope', 'A frayed rope', 'Damage & wear'),
    ('rust', 'Rust', 'Damage & wear'),
    ('rot', 'Rot or mould', 'Damage & wear'),
    ('burnt', 'Burnt or charred material', 'Damage & wear'),
    ('stain', 'A stain', 'Damage & wear'),
    ('mud', 'Mud and dirt', 'Damage & wear'),
    ('patina', 'Wear and patina from use', 'Damage & wear'),
    ('blood', 'Blood', 'Damage & wear'),
    ('scar', 'A scar or wound', 'Damage & wear'),
    ('dent', 'A dent in metal', 'Damage & wear'),
    ('peeling_paint', 'Peeling paint', 'Damage & wear'),
    ('wet_surface', 'A wet surface', 'Damage & wear'),
    # text, number and symbol
    ('text_letters', 'Legible letters', 'Text & number'),
    ('text_word', 'A specific word', 'Text & number'),
    ('text_sentence', 'A whole legible sentence', 'Text & number'),
    ('number_digits', 'Digits', 'Text & number'),
    ('number_specific', 'A specific number', 'Text & number'),
    ('number_date', 'A date', 'Text & number'),
    ('number_roman', 'Roman numerals', 'Text & number'),
    ('clock_face', 'A clock face reading a given time', 'Text & number'),
    ('handwriting', 'Handwriting', 'Text & number'),
    ('signage', 'A sign or shop board', 'Text & number'),
    ('book_page', 'A page of a book', 'Text & number'),
    ('map_labels', 'A labelled map or chart', 'Text & number'),
    ('symbol_crest', 'A crest, flag or emblem', 'Text & number'),
    # objects
    ('tool_hand', 'A hand tool', 'Objects'),
    ('furniture', 'Furniture', 'Objects'),
    ('container_barrel', 'Barrels and crates', 'Objects'),
    ('rope_rigging', 'Rope and rigging', 'Objects'),
    ('weapon', 'A weapon', 'Objects'),
    ('instrument_music', 'A musical instrument', 'Objects'),
    ('lantern', 'A lantern or candle', 'Objects'),
    ('wheel_cart', 'A wheel or cart', 'Objects'),
    ('boat', 'A boat', 'Objects'),
    ('ship_rigging', 'A ship with rigging', 'Objects'),
    ('sail', 'Sails', 'Objects'),
    ('quill_ink', 'A quill and inkpot', 'Objects'),
    ('coins', 'Coins or money', 'Objects'),
    ('basket', 'A basket', 'Objects'),
    ('glassware', 'Glassware', 'Objects'),
    ('mirror', 'A mirror with a reflection', 'Objects'),
    # animals
    ('animal_dog', 'A dog', 'Animals'),
    ('animal_cat', 'A cat', 'Animals'),
    ('animal_horse', 'A horse', 'Animals'),
    ('animal_cow', 'Cattle', 'Animals'),
    ('animal_sheep', 'Sheep', 'Animals'),
    ('animal_chicken', 'Poultry', 'Animals'),
    ('animal_bird_flying', 'A bird in flight', 'Animals'),
    ('animal_fish', 'A fish', 'Animals'),
    ('animal_insect', 'An insect', 'Animals'),
    ('creature_invented', 'An invented creature', 'Animals'),
    # nature and weather
    ('tree', 'A tree', 'Nature & weather'),
    ('forest', 'Woodland', 'Nature & weather'),
    ('grass_field', 'Grass or a field', 'Nature & weather'),
    ('water_still', 'Still water', 'Nature & weather'),
    ('water_waves', 'Waves', 'Nature & weather'),
    ('water_reflection', 'A reflection in water', 'Nature & weather'),
    ('rain', 'Rain', 'Nature & weather'),
    ('snow', 'Snow', 'Nature & weather'),
    ('fire', 'Fire', 'Nature & weather'),
    ('smoke', 'Smoke', 'Nature & weather'),
    ('fog', 'Fog or mist', 'Nature & weather'),
    ('sky_clouds', 'Sky and cloud', 'Nature & weather'),
    ('night', 'Night', 'Nature & weather'),
    ('rock_mountain', 'Rock and mountain', 'Nature & weather'),
    # built environment
    ('door', 'A door', 'Built environment'),
    ('window_intact', 'An intact window', 'Built environment'),
    ('roof', 'A roof', 'Built environment'),
    ('stairs', 'Stairs', 'Built environment'),
    ('brick_wall', 'A brick wall', 'Built environment'),
    ('timber_frame', 'Timber framing', 'Built environment'),
    ('interior_room', 'A room interior', 'Built environment'),
    ('street', 'A street', 'Built environment'),
    ('bridge', 'A bridge', 'Built environment'),
    ('harbour', 'A harbour or quay', 'Built environment'),
    ('church', 'A church interior or exterior', 'Built environment'),
    # clothing
    ('dress_period', 'Period dress', 'Clothing'),
    ('armour', 'Armour', 'Clothing'),
    ('hat', 'A hat', 'Clothing'),
    ('cloak', 'A cloak', 'Clothing'),
    ('cloth_folds', 'Cloth folds', 'Clothing'),
    ('layered_clothing', 'Layered clothing', 'Clothing'),
    ('footwear_period', 'Period footwear', 'Clothing'),
]


def subject_bank(mode):
    """One question per subject, phrased for what the step does with it.

    mode 'render'    a generator: does the subject come out right
    mode 'see'       a judge: can it tell the subject is there at all
    mode 'identify'  a judge: can it say WHICH one it is
    mode 'model'     geometry: can it build the subject
    mode 'move'      motion: can the subject be animated
    """
    verb = {'render': 'Renders', 'see': 'Sees', 'identify': 'Names', 'model': 'Models', 'move': 'Animates'}[mode]
    tail = {'render': ' correctly', 'see': '', 'identify': '', 'model': '', 'move': ''}[mode]
    pre = {'render': 'Render', 'see': 'Sees', 'identify': 'Names', 'model': 'Builds', 'move': 'Moves'}[mode]
    out = []
    for cid, label, group in SUBJECTS:
        # lowercase the leading word so it reads as a sentence, unless that word is an
        # acronym ("PBR materials"); `label[:2].isupper()` wrongly protected "A cloak".
        head = label.split(' ', 1)[0]
        first = label if (len(head) > 1 and head.isupper()) else label[0].lower() + label[1:]
        out.append(q(mode + '_' + cid, verb + ' ' + first + tail, '', '', True, pre + ': ' + group))
    return out


def capacity_bank(kind):
    """How much of a thing fits before it breaks. The operator's question — "how many
    characters can be generated in one image without issues" — is a capacity question, and
    every step has its own version of it. A capacity answer is a NUMBER, and the honest
    default is that nobody has counted."""
    common = [
        q('cap_people', 'People in one frame before anatomy breaks', 'counted, not guessed', 'count', True, 'Capacity'),
        q('cap_named', 'NAMED characters held at once', 'each still recognisable', 'count', True, 'Capacity'),
        q('cap_faces', 'Faces that stay clean', '', 'count', True, 'Capacity'),
        q('cap_hands', 'Hands that stay clean', '', 'count', True, 'Capacity'),
        q('cap_objects', 'Distinct objects it keeps track of', '', 'count', True, 'Capacity'),
        q('cap_words', 'Words of legible text', '', 'count', True, 'Capacity'),
        q('cap_digits', 'Digits it gets right', '', 'count', True, 'Capacity'),
        q('cap_animals', 'Animals in one frame', '', 'count', True, 'Capacity'),
        q(
            'cap_prompt_terms',
            'Prompt terms it still honours',
            'where it starts dropping them',
            'count',
            True,
            'Capacity',
        ),
    ]
    if kind == 'image':
        return common + [
            q('cap_res', 'Resolution before it falls apart', '', 'px', True, 'Capacity'),
            q(
                'cap_panels',
                'Storyboard panels in one sheet',
                'a contact sheet or angle sheet',
                'count',
                True,
                'Capacity',
            ),
            q('cap_cells_clean', 'Sheet cells clean in one pass', '', 'count', True, 'Capacity'),
        ]
    if kind == 'video':
        return common + [
            q('cap_seconds', 'Seconds before it degrades', '', 's', True, 'Capacity'),
            q('cap_shots', 'Shots that cut together', '', 'count', True, 'Capacity'),
            q('cap_moving', 'Moving subjects at once', '', 'count', True, 'Capacity'),
        ]
    if kind == 'judge':
        return common + [
            q('cap_questions', 'Questions per picture before it drifts', '', 'count', True, 'Capacity'),
            q('cap_images', 'Images in one prompt', '', 'count', True, 'Capacity'),
            q('cap_res_judge', 'Resolution it can actually resolve detail at', '', 'px', True, 'Capacity'),
        ]
    return common


COUNTING = [
    q('count_exact', 'Counts a small number exactly', 'three barrels means three', '', True, 'Counting & quantity'),
    q('count_large', 'Counts past ten', '', '', True, 'Counting & quantity'),
    q('count_people', 'Counts people correctly', '', '', True, 'Counting & quantity'),
    q('count_fingers', 'Counts fingers correctly', '', '', True, 'Counting & quantity'),
    q('count_legs', 'Counts legs on an animal', '', '', True, 'Counting & quantity'),
    q('count_windows', 'Counts repeated architecture', 'windows, arches, columns', '', True, 'Counting & quantity'),
    q('count_absent', 'Says when a thing is NOT there', 'the harder half of counting', '', True, 'Counting & quantity'),
    q('count_more_less', 'Judges more versus fewer', '', '', True, 'Counting & quantity'),
]

SPATIAL = [
    q('sp_left_right', 'Left and right', '', '', True, 'Space & relation'),
    q('sp_front_behind', 'In front of and behind', '', '', True, 'Space & relation'),
    q('sp_on_under', 'On top of and underneath', '', '', True, 'Space & relation'),
    q('sp_inside', 'Inside and outside', '', '', True, 'Space & relation'),
    q('sp_near_far', 'Near and far', '', '', True, 'Space & relation'),
    q('sp_touching', 'Touching versus apart', '', '', True, 'Space & relation'),
    q('sp_holding_who', 'Which person holds the object', '', '', True, 'Space & relation'),
    q('sp_relative_size', 'Relative size of two things', '', '', True, 'Space & relation'),
    q('sp_occlusion', 'What is hidden behind what', '', '', True, 'Space & relation'),
    q('sp_direction', 'Which way something faces', '', '', True, 'Space & relation'),
]

ATTRIBUTES = [
    q('at_colour_named', 'A named colour lands on the named thing', '', '', True, 'Attributes'),
    q('at_colour_two', 'Two different colours on two things', 'the classic binding failure', '', True, 'Attributes'),
    q('at_material', 'The right material', 'wood, iron, cloth, stone', '', True, 'Attributes'),
    q('at_texture', 'The right surface texture', '', '', True, 'Attributes'),
    q('at_age_object', 'New versus old', '', '', True, 'Attributes'),
    q('at_size', 'The right size', '', '', True, 'Attributes'),
    q('at_state', 'Open versus shut, lit versus dark', '', '', True, 'Attributes'),
    q('at_wet_dry', 'Wet versus dry', '', '', True, 'Attributes'),
    q('at_clean_dirty', 'Clean versus dirty', '', '', True, 'Attributes'),
    q('at_emotion', 'The named emotion on the face', '', '', True, 'Attributes'),
]


# ── which banks each step is asked ───────────────────────────────────────────
# Applied by the migration AFTER the step's own domain questions and before UNIVERSAL, so
# a sheet reads: what this step specifically needs → the shared subject inventory → the
# questions every tool answers.
BANKS = {}


def _banks(*groups):
    out = []
    for g in groups:
        out.extend(g)
    return out


# generators: does the subject come out RIGHT
for _s in ('t2i', 'i2i', 'inpaint'):
    BANKS[_s] = _banks(subject_bank('render'), capacity_bank('image'), COUNTING, SPATIAL, ATTRIBUTES)
for _s in ('i2v', 't2v', 'v2v'):
    BANKS[_s] = _banks(
        subject_bank('render'), subject_bank('move'), capacity_bank('video'), COUNTING, SPATIAL, ATTRIBUTES
    )
# judges and detectors: can it SEE it, and can it say WHICH it is
for _s in ('vlm_judges', 'detectors', 'text_judges', 'identity_gates', 'pixel_gates'):
    BANKS[_s] = _banks(
        subject_bank('see'), subject_bank('identify'), capacity_bank('judge'), COUNTING, SPATIAL, ATTRIBUTES
    )
# geometry: can it BUILD it
for _s in ('mesh_gen', 'mesh_qc', 'render3d', 'arch'):
    BANKS[_s] = _banks(subject_bank('model'), capacity_bank('image'), SPATIAL, ATTRIBUTES)
# motion: can it MOVE it
for _s in ('movement', 'poses', 'gestures', 'facial', 'muscle', 'body_fit', 'rigging'):
    BANKS[_s] = _banks(subject_bank('move'), capacity_bank('video'), SPATIAL)
# the picture-adjacent rest
BANKS['identity'] = _banks(capacity_bank('image'), SPATIAL, ATTRIBUTES)
BANKS['controlnet'] = _banks(subject_bank('render'), capacity_bank('image'), SPATIAL, ATTRIBUTES)
BANKS['lora_train'] = _banks(subject_bank('render'), capacity_bank('image'))
BANKS['upscale'] = _banks(subject_bank('render'), capacity_bank('image'))
BANKS['vfx'] = _banks(subject_bank('render'), capacity_bank('video'), SPATIAL, ATTRIBUTES)
BANKS['grooms'] = _banks(capacity_bank('image'), ATTRIBUTES)
BANKS['interp'] = _banks(capacity_bank('video'))
BANKS['video_assembly'] = _banks(capacity_bank('video'))
# the language steps get the reasoning banks, which is where counting and relation live
for _s in ('llm_script', 'llm_prompt', 'llm_research', 'llm_agents', 'subtitles'):
    BANKS[_s] = _banks(COUNTING, SPATIAL)


# ── the same idea for sound ──────────────────────────────────────────────────
# A visual subject list says nothing about the audio half of the stack, so sound gets its
# own inventory, asked of the generators as "makes it" and of the judges as "hears it".
AUDIO_SUBJECTS = [
    ('footstep_wood', 'Footsteps on wood', 'Human & movement'),
    ('footstep_stone', 'Footsteps on stone', 'Human & movement'),
    ('footstep_mud', 'Footsteps in mud', 'Human & movement'),
    ('cloth_rustle', 'Clothing rustle', 'Human & movement'),
    ('breath', 'Breathing', 'Human & movement'),
    ('effort', 'Effort and strain', 'Human & movement'),
    ('laugh', 'Laughter', 'Human & movement'),
    ('cry', 'Crying', 'Human & movement'),
    ('scream', 'A scream', 'Human & movement'),
    ('cough', 'A cough', 'Human & movement'),
    ('baby_cry', 'A baby crying', 'Human & movement'),
    ('crowd_murmur', 'A crowd murmuring', 'Human & movement'),
    ('chewing', 'Eating and chewing', 'Human & movement'),
    ('door_creak', 'A creaking door', 'Objects & work'),
    ('hammer_wood', 'Hammering wood', 'Objects & work'),
    ('saw_wood', 'Sawing wood', 'Objects & work'),
    ('wood_break', 'Wood breaking', 'Objects & work'),
    ('glass_break', 'Glass breaking', 'Objects & work'),
    ('pottery_smash', 'Pottery smashing', 'Objects & work'),
    ('rope_creak', 'Rope and rigging creaking', 'Objects & work'),
    ('sail_flap', 'Sails flapping', 'Objects & work'),
    ('cart_wheels', 'Cart wheels', 'Objects & work'),
    ('coins', 'Coins', 'Objects & work'),
    ('paper_rustle', 'Paper rustling', 'Objects & work'),
    ('quill_write', 'A quill writing', 'Objects & work'),
    ('pour_liquid', 'Liquid pouring', 'Objects & work'),
    ('sword_clash', 'Metal on metal', 'Objects & work'),
    ('clock_tick', 'A clock ticking', 'Objects & work'),
    ('bell_church', 'A church bell', 'Objects & work'),
    ('water_lap', 'Water lapping', 'Nature & weather'),
    ('waves', 'Waves', 'Nature & weather'),
    ('rain_roof', 'Rain on a roof', 'Nature & weather'),
    ('thunder', 'Thunder', 'Nature & weather'),
    ('wind', 'Wind', 'Nature & weather'),
    ('fire_crackle', 'A crackling fire', 'Nature & weather'),
    ('birdsong', 'Birdsong', 'Nature & weather'),
    ('seagull', 'Seagulls', 'Nature & weather'),
    ('insects', 'Insects', 'Nature & weather'),
    ('dog_bark', 'A dog barking', 'Animals'),
    ('cat', 'A cat', 'Animals'),
    ('horse_hooves', 'Horse hooves', 'Animals'),
    ('horse_whinny', 'A horse whinnying', 'Animals'),
    ('cow', 'Cattle', 'Animals'),
    ('sheep', 'Sheep', 'Animals'),
    ('chicken', 'Poultry', 'Animals'),
    ('room_tone_interior', 'Interior room tone', 'Space & ambience'),
    ('room_tone_church', 'A large stone interior', 'Space & ambience'),
    ('street_ambience', 'Street ambience', 'Space & ambience'),
    ('harbour_ambience', 'Harbour ambience', 'Space & ambience'),
    ('market_ambience', 'A market', 'Space & ambience'),
    ('distance', 'The same sound near and far', 'Space & ambience'),
    ('reverb_space', 'A believable room around the sound', 'Space & ambience'),
    ('off_screen', 'A sound from off screen', 'Space & ambience'),
]


def audio_bank(mode):
    """mode 'make' for a generator or library, 'hear' for a judge."""
    verb = 'Makes' if mode == 'make' else 'Hears'
    pre = 'Makes' if mode == 'make' else 'Hears'
    out = []
    for cid, label, group in AUDIO_SUBJECTS:
        head = label.split(' ', 1)[0]
        first = label if (len(head) > 1 and head.isupper()) else label[0].lower() + label[1:]
        out.append(q(mode + '_' + cid, verb + ' ' + first, '', '', True, pre + ': ' + group))
    return out


AUDIO_CAPACITY = [
    q('acap_layers', 'Sound layers before the mix muddies', '', 'count', True, 'Capacity'),
    q('acap_voices', 'Distinct voices in one scene', '', 'count', True, 'Capacity'),
    q('acap_seconds', 'Seconds before it degrades', '', 's', True, 'Capacity'),
    q('acap_variations', 'Variations of one sound before they repeat', '', 'count', True, 'Capacity'),
    q('acap_words', 'Words per take before drift', '', 'count', True, 'Capacity'),
    q('acap_instruments', 'Instruments held apart', '', 'count', True, 'Capacity'),
    q('acap_concurrent', 'Concurrent jobs that pay off', '', 'count', True, 'Capacity'),
]

for _s in ('sfx_gen', 'sfx_library', 'sfx_process'):
    BANKS[_s] = _banks(audio_bank('make'), AUDIO_CAPACITY)
BANKS['audio_judges'] = _banks(audio_bank('hear'), AUDIO_CAPACITY, COUNTING)
for _s in (
    'tts',
    'voice_clone',
    'voice_direction',
    'voice_conversion',
    'music_gen',
    'melody',
    'stem_split',
    'audio_mix',
    'stt',
    'diarization',
    'lipsync',
):
    BANKS[_s] = _banks(AUDIO_CAPACITY)
