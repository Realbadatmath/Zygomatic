# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

from __future__ import annotations

from .settings import COND_JUDGE
from .subjects import PAIR_DIR, SUBJECT_PROMPT
from .probes_subjects import PROBES

# ── Counting, space and attributes: one MATCHED A/B pair per column ──────────────────
# Each half carries its own key, so the same answer cannot be right on both and a judge with
# a favourite number or a favourite side scores 0.5, not 1.0. A = the picture the column is
# named for, B = the matched contrast.
# column -> (title, question, A clause, A accept, B clause, B accept, mechanical check or None)
PAIRS = {
    # ── Counting & quantity (8) ──
    'count_exact': (
        'Counts a small number exactly',
        'How many barrels are in this picture? Answer with the number only.',
        'three tarred barrels in a row on a quay, nothing else',
        ['3', 'three'],
        'five tarred barrels in a row on the same quay, same seed',
        ['5', 'five'],
        {
            'check': 'count_equals_key',
            'note': 'the operator counts the barrels once on the contact sheet; the render prompt is not the key',
        },
    ),
    'count_large': (
        'Counts past ten',
        'How many gulls are sitting on the roof ridge? Answer with the number only.',
        'fourteen gulls sitting along a roof ridge',
        ['14', 'fourteen'],
        'nine gulls sitting along the same ridge, same seed',
        ['9', 'nine'],
        {'check': 'count_within', 'tol': 0, 'note': 'exact; tol is written 0 so a later relaxation is a visible edit'},
    ),
    'count_people': (
        'Counts people correctly',
        'How many people are in this picture? Answer with the number only.',
        'five people standing on a quay',
        ['5', 'five'],
        'two people standing on the same quay, same seed',
        ['2', 'two'],
        {
            'check': 'person_count',
            'count': 5,
            'note': 'the ultralytics person class decides; a disagreement with the operator count blocks the column',
        },
    ),
    'count_fingers': (
        'Counts fingers correctly',
        'How many fingers, thumbs included, are on the hand in this picture? Answer with the number only.',
        'one open hand palm to camera, five fingers spread',
        ['5', 'five'],
        'the same hand with four fingers, same seed',
        ['4', 'four'],
        {
            'check': 'mediapipe_hands',
            'hands': 1,
            'fingers': 5,
            'note': 'the defect bench scored 2/8 on fused fingers and extra digits — MediaPipe hand_landmarker decides here, the VLM is scored against it',
        },
    ),
    'count_legs': (
        'Counts legs on an animal',
        'How many legs does the dog in this picture have? Answer with the number only.',
        'a short-haired dog standing in profile with four legs',
        ['4', 'four'],
        'the same dog with three legs, one hind leg missing, same seed',
        ['3', 'three'],
        None,
    ),
    'count_windows': (
        'Counts repeated architecture',
        'How many windows does the house in this picture have? Answer with the number only.',
        'a gabled brick house with nine windows, four per floor and one in the gable',
        ['9', 'nine'],
        'the same house with six windows, same seed',
        ['6', 'six'],
        None,
    ),
    'count_absent': (
        'Says when a thing is NOT there',
        'Is there a cat in this picture? Answer yes or no, one word only.',
        'a grey cat sitting beside a bowl in a doorway',
        ['yes'],
        'the same doorway and bowl with no cat, same seed',
        ['no'],
        None,
    ),
    'count_more_less': (
        'Judges more versus fewer',
        'Are there more crates or more barrels in this picture? Answer with one word, crates or barrels.',
        'seven crates stacked beside three barrels',
        ['crates'],
        'seven barrels beside three crates, same seed',
        ['barrels'],
        None,
    ),
    # ── Space & relation (10) ──
    'sp_left_right': (
        'Left and right',
        'Is the woman with the lantern on the left or on the right of the man with the mallet? Answer left or right.',
        'a man holding a mallet with a woman holding a lantern standing to his left',
        ['left'],
        'the same two with the woman on his right, same seed',
        ['right'],
        None,
    ),
    'sp_front_behind': (
        'In front of and behind',
        'Are the crates in front of the barrels or behind them? Answer in front or behind.',
        'three barrels with a stack of crates behind them on a quay',
        ['behind'],
        'the same crates in front of the same barrels, same seed',
        ['in front', 'front'],
        None,
    ),
    'sp_on_under': (
        'On top of and underneath',
        'Is the bell above the door or below it? Answer above or below.',
        'a bell hanging above a studded door',
        ['above'],
        'the same bell mounted below the same door, same seed',
        ['below'],
        None,
    ),
    'sp_inside': (
        'Inside and outside',
        'Is the bowl inside the doorway or outside it on the street? Answer inside or outside.',
        'an earthenware bowl standing inside a doorway',
        ['inside'],
        'the same bowl on the street outside the same doorway, same seed',
        ['outside'],
        None,
    ),
    'sp_near_far': (
        'Near and far',
        'Which is nearer to the camera, the barrels or the cart horse? Answer barrels or horse.',
        'barrels in the foreground, a cart horse far down the quay',
        ['barrels', 'the barrels'],
        'the cart horse in the foreground, the barrels far down the quay, same seed',
        ['horse', 'the horse', 'cart horse'],
        None,
    ),
    'sp_touching': (
        'Touching versus apart',
        'Is the hand touching the rail, or is there a gap between them? Answer touching or apart.',
        'a hand resting flat on a wooden rail',
        ['touching'],
        'the same hand held a clear hand-width above the same rail, same seed',
        ['apart'],
        None,
    ),
    'sp_holding_who': (
        'Which person holds the object',
        'Who is holding the lantern, the man or the woman? Answer man or woman.',
        'a woman holding a lantern beside a man holding a mallet',
        ['woman'],
        'the man holding the lantern and the woman the mallet, same seed',
        ['man'],
        None,
    ),
    'sp_relative_size': (
        'Relative size of two things',
        'Is the gable window larger or smaller than the windows below it? Answer larger or smaller.',
        'a gable with one small window above four larger windows',
        ['smaller'],
        'the same gable with the gable window larger than the four below, same seed',
        ['larger'],
        None,
    ),
    'sp_occlusion': (
        'What is hidden behind what',
        "Is the church tower hidden behind the ship's mast, or is the mast behind the tower? Answer tower hidden or mast hidden.",
        "a ship's mast standing directly in front of a distant church tower",
        ['tower hidden', 'tower'],
        'the same mast standing behind the same church tower, same seed',
        ['mast hidden', 'mast'],
        None,
    ),
    'sp_direction': (
        'Which way something faces',
        'Is the seated man facing the water or facing away from it? Answer towards or away.',
        'a man seated on a barrel facing the water',
        ['towards', 'toward', 'facing the water'],
        'the same man seated facing away from the water, same seed',
        ['away'],
        None,
    ),
    # ── Attributes (10) ──
    'at_colour_named': (
        'A named colour lands on the named thing',
        'What colour is the cloak in this picture? Answer with one colour word.',
        'a man in a red wool cloak against a plain wall',
        ['red'],
        'the same man in a green wool cloak, same seed',
        ['green'],
        None,
    ),
    'at_colour_two': (
        'Two different colours on two things',
        'What colour is the cloak and what colour is the hat? Answer as cloak-colour, hat-colour.',
        'a man in a red cloak and a blue hat',
        ['red, blue', 'red blue'],
        'the same man in a blue cloak and a red hat, same seed',
        ['blue, red', 'blue red'],
        {
            'check': 'answer_equals_fixture_key',
            'note': 'the classic binding failure: a judge that reads both colours but swaps them is WRONG on both halves',
        },
    ),
    'at_material': (
        'The right material',
        'What is the bucket in this picture made of? Answer with one word.',
        'a bucket made of iron, riveted bands, plain background',
        ['iron', 'metal'],
        'the same bucket made of staved wood, same seed',
        ['wood', 'wooden', 'timber'],
        None,
    ),
    'at_texture': (
        'The right surface texture',
        'Is the surface of the plank rough or smooth? Answer rough or smooth.',
        'a sawn plank with a raw splintered rough face',
        ['rough'],
        'the same plank planed glass-smooth, same seed',
        ['smooth'],
        None,
    ),
    'at_age_object': (
        'New versus old',
        'Is the rope in this picture new or old? Answer new or old.',
        'a clean pale hemp rope, freshly laid, tight and unworn',
        ['new'],
        'the same rope grey, furred and frayed with age, same seed',
        ['old', 'worn'],
        None,
    ),
    'at_size': (
        'The right size',
        'Is the barrel taller than the man beside it or shorter? Answer taller or shorter.',
        'a barrel standing taller than the man beside it',
        ['taller'],
        "the same barrel reaching only to the man's knee, same seed",
        ['shorter'],
        None,
    ),
    'at_state': (
        'Open versus shut, lit versus dark',
        'Is the lantern in this picture lit or unlit? Answer lit or unlit.',
        'a horn lantern hanging lit, flame visible inside',
        ['lit'],
        'the same lantern dark and unlit, same seed',
        ['unlit', 'dark', 'not lit'],
        None,
    ),
    'at_wet_dry': (
        'Wet versus dry',
        'Is the planking in this picture wet or dry? Answer wet or dry.',
        'planking soaked dark with water, pooled and reflective',
        ['wet'],
        'the same planking bone dry and pale, same seed',
        ['dry'],
        None,
    ),
    'at_clean_dirty': (
        'Clean versus dirty',
        'Is the linen shirt in this picture clean or dirty? Answer clean or dirty.',
        'a white linen shirt, freshly washed and unmarked',
        ['clean'],
        'the same shirt smeared with mud and tar, same seed',
        ['dirty', 'soiled'],
        None,
    ),
    'at_emotion': (
        'The named emotion on the face',
        'What is the man in this picture feeling? Answer with one word.',
        'a close portrait of a man with a wide-eyed frightened face',
        ['fear', 'frightened', 'afraid', 'scared'],
        'the same man with a broad laughing happy face, same seed',
        ['happy', 'joy', 'happiness', 'laughing'],
        None,
    ),
}

for _col, (_title, _q, _a_clause, _a_accept, _b_clause, _b_accept, _mech) in PAIRS.items():
    _ck = [
        {
            'check': 'answer_equals_fixture_key',
            'transports': ['vlm_ollama', 'vlm_inspector'],
            'accept_a': _a_accept,
            'accept_b': _b_accept,
        }
    ]
    if _mech:
        _ck.append(dict(_mech, transports=['service', 'vlm_ollama', 'vlm_inspector']))
    PROBES.append(
        {
            'id': f'pair_{_col}',
            'title': _title,
            'feeds': [_col],
            'inputs': {
                'task': _q,
                'image': [f'{PAIR_DIR}/{_col}_a.png', f'{PAIR_DIR}/{_col}_b.png'],
                'fixture': {
                    'path': f'{PAIR_DIR}/{_col}_a.png',
                    'negative_path': f'{PAIR_DIR}/{_col}_b.png',
                    'generated': (
                        'the image bank renders A from SUBJECT_PROMPT with the A clause and B '
                        'from the SAME seed with the B clause — one matched change, nothing else'
                    ),
                    'prompt': SUBJECT_PROMPT.format(clause=_a_clause),
                    'negative_prompt': SUBJECT_PROMPT.format(clause=_b_clause),
                    'key': {'a': {'accept': _a_accept}, 'b': {'accept': _b_accept}},
                    'verified': False,
                    'blocks': [_col],
                    'how_to_verify': (
                        'the operator opens the A/B pair once and writes down, per half, the '
                        'answer to the question above; those two written answers ARE the key. '
                        'No VLM is asked (defect bench 2026-09-27).'
                    ),
                },
            },
            'conditions': dict(COND_JUDGE),
            'checks': _ck,
            'grade': 'measured',
            'state_rule': {'yes': 0.9, 'partial': 0.7},
            'state_note': (
                'both halves x 3 repeats; the column is yes only when the judge is right on A AND on B. '
                'Being right on one half is what a judge with a favourite answer scores, so 0.5 lands '
                'on `no`.' + ('' if not _mech else ' The mechanical reading decides where the two disagree.')
            ),
        }
    )
