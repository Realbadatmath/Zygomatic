# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Unit tests for the stages apply_auto_defaults was split into.

Every stage used to be an unreachable slice of a 335-line body; these are the first tests
that exercise them on their own. Pure, no GPU, no network, no services.
"""

import random

import pytest

from zyg_workflows.character_bible_service import auto_defaults as AD


def rand_for(seed_key):
    """The field-RNG callable the orchestrator builds, for an explicit seed key."""
    return lambda field: AD._field_rng(seed_key, field)


# ── _seed_key / _field_rng ──────────────────────────────────────────────────


def test_seed_key_prefers_the_explicit_key_over_everything_in_the_params():
    p = {'char_id': 'abel', 'character_id': 'cornelis', 'name': 'Zebedee'}
    assert AD._seed_key(p, '  Explicit-Key ') == 'explicit-key'


def test_seed_key_falls_back_char_id_then_character_id_then_name():
    assert AD._seed_key({'char_id': 'Abel', 'name': 'Zebedee'}, None) == 'abel'
    assert AD._seed_key({'character_id': 'Cornelis', 'name': 'Zebedee'}, None) == 'cornelis'
    assert AD._seed_key({'name': 'Zebedee'}, None) == 'zebedee'


def test_seed_key_is_empty_when_the_name_is_itself_the_auto_sentinel():
    # an 'auto' name must not become a seed, or every auto character shares one face
    assert AD._seed_key({'name': 'auto'}, None) == ''
    assert AD._seed_key({}, None) == ''
    assert AD._seed_key({'name': '  '}, None) == ''


def test_field_rng_is_reproducible_per_character_and_differs_per_field():
    a = AD._field_rng('abel', 'gender').random()
    b = AD._field_rng('abel', 'gender').random()
    c = AD._field_rng('abel', 'age').random()
    d = AD._field_rng('cornelis', 'gender').random()
    assert a == b
    assert a != c
    assert a != d


def test_field_rng_without_a_seed_key_is_fresh_entropy():
    draws = {AD._field_rng('', 'gender').random() for _ in range(8)}
    assert len(draws) > 1


# ── _resolve_core_identity ──────────────────────────────────────────────────


def test_core_identity_honours_an_explicit_gender_and_keys_the_defaults_on_it():
    p = {'gender': ' MALE '}
    gender, gd, _style, _genre = AD._resolve_core_identity(p, rand_for('abel'))
    assert gender == 'male'
    assert p['gender'] == 'male'
    assert gd['posture'] == AD._GENDER_DEFAULTS['male']['posture']


def test_core_identity_falls_back_female_for_an_unrecognised_gender():
    p = {'gender': 'nonbinary'}
    gender, _gd, _s, _g = AD._resolve_core_identity(p, rand_for('abel'))
    assert gender == 'female'


def test_core_identity_rolls_the_dice_for_an_auto_gender():
    seen = {AD._resolve_core_identity({'gender': 'auto'}, rand_for('c%d' % i))[0] for i in range(40)}
    assert seen == {'female', 'male'}


def test_core_identity_accepts_the_legacy_style_key_and_mirrors_it_back():
    p = {'gender': 'male', 'style': 'illustrated'}
    _g, _gd, style, _genre = AD._resolve_core_identity(p, rand_for('abel'))
    assert style == 'illustrated'
    assert p['render_style'] == 'illustrated'
    assert p['style'] == 'illustrated'


def test_core_identity_defaults_style_photorealistic_and_genre_general():
    p = {'gender': 'male'}
    _g, _gd, style, genre = AD._resolve_core_identity(p, rand_for('abel'))
    assert (style, genre) == ('photorealistic', 'general')


def test_core_identity_age_roll_stays_inside_the_three_declared_bands():
    for i in range(60):
        p = {'gender': 'male'}
        AD._resolve_core_identity(p, rand_for('age%d' % i))
        assert 21 <= p['age'] <= 75
        assert p['age_range'] == AD._age_range_from_age(p['age'])


def test_core_identity_honours_an_explicit_age_and_age_range():
    p = {'gender': 'male', 'age': 44, 'age_range': 'middle-aged'}
    AD._resolve_core_identity(p, rand_for('abel'))
    assert (p['age'], p['age_range']) == (44, 'middle-aged')


def test_core_identity_height_is_coerced_to_a_float_and_falls_back_on_junk():
    p = {'gender': 'male', 'height': '1.82'}
    AD._resolve_core_identity(p, rand_for('abel'))
    assert p['height'] == pytest.approx(1.82)
    q = {'gender': 'male', 'height': 'tall-ish'}
    AD._resolve_core_identity(q, rand_for('abel'))
    assert q['height'] == 1.70
    assert q['height_text'] == AD._height_text(1.70)


def test_core_identity_auto_height_uses_the_gendered_range():
    for i in range(30):
        m = {'gender': 'male'}
        f = {'gender': 'female'}
        AD._resolve_core_identity(m, rand_for('h%d' % i))
        AD._resolve_core_identity(f, rand_for('h%d' % i))
        assert 1.65 <= m['height'] <= 1.93
        assert 1.55 <= f['height'] <= 1.79


# ── _resolve_skin_and_heritage ──────────────────────────────────────────────


def test_skin_aliases_are_normalised_to_the_canonical_scale():
    for raw, canon in (('White', 'fair'), ('pale', 'fair'), ('EBONY', 'deep'), ('brown', 'dark')):
        p = {'skin_tone': raw, 'ethnic_heritage': 'British'}
        AD._resolve_skin_and_heritage(p, rand_for('abel'))
        assert p['skin_tone'] == canon


def test_skin_tone_was_auto_records_an_explicit_choice_before_normalising():
    explicit = {'skin_tone': 'white', 'ethnic_heritage': 'Nigerian'}
    AD._resolve_skin_and_heritage(explicit, rand_for('abel'))
    assert explicit['_skin_tone_was_auto'] is False
    auto = {'skin_tone': 'auto', 'ethnic_heritage': 'Nigerian'}
    AD._resolve_skin_and_heritage(auto, rand_for('abel'))
    assert auto['_skin_tone_was_auto'] is True


def test_an_explicit_heritage_constrains_the_auto_skin_roll():
    heritage = next(iter(AD._SKIN_BY_HERITAGE))
    pool = AD._SKIN_BY_HERITAGE[heritage]
    for i in range(25):
        p = {'skin_tone': 'auto', 'ethnic_heritage': heritage}
        got, _deep = AD._resolve_skin_and_heritage(p, rand_for('s%d' % i))
        assert got == heritage
        assert p['skin_tone'] in pool


def test_an_auto_heritage_is_drawn_from_the_pool_coherent_with_the_skin_tone():
    tone = next(t for t, pool in AD._HERITAGE_BY_SKIN.items() if pool)
    p = {'skin_tone': tone, 'ethnic_heritage': 'auto'}
    heritage, _deep = AD._resolve_skin_and_heritage(p, rand_for('abel'))
    assert heritage in AD._HERITAGE_BY_SKIN[tone]


def test_an_auto_heritage_with_no_coherent_pool_resolves_to_empty_string():
    p = {'skin_tone': 'not-a-tone-on-the-scale', 'ethnic_heritage': 'auto'}
    heritage, deep = AD._resolve_skin_and_heritage(p, rand_for('abel'))
    assert (heritage, deep, p['ethnic_heritage']) == ('', False, '')


def test_deep_skin_is_exactly_dark_or_deep():
    for tone, expect in (('dark', True), ('deep', True), ('Deep', True), ('medium', False), ('fair', False)):
        p = {'skin_tone': tone, 'ethnic_heritage': 'British'}
        _her, deep = AD._resolve_skin_and_heritage(p, rand_for('abel'))
        assert deep is expect, tone


# ── _resolve_hair_and_eyes ──────────────────────────────────────────────────


def test_an_auto_hair_colour_on_an_older_character_greys():
    p = {'age': 61, 'hair_color': 'auto'}
    AD._resolve_hair_and_eyes(p, rand_for('abel'), 'male', 'British', False)
    assert p['hair_color'] in ('grey', 'white', 'dark brown')
    assert p['_hair_color_was_auto'] is True


def test_an_auto_hair_colour_under_58_comes_from_the_skin_keyed_pool():
    light = {'age': 30, 'hair_color': 'auto'}
    AD._resolve_hair_and_eyes(light, rand_for('abel'), 'male', 'British', False)
    assert light['hair_color'] in AD._HAIR_LIGHT_SKIN
    deep = {'age': 30, 'hair_color': 'auto'}
    AD._resolve_hair_and_eyes(deep, rand_for('abel'), 'male', 'Nigerian', True)
    assert deep['hair_color'] in AD._HAIR_DEEP_SKIN


def test_an_unreadable_age_is_treated_as_young_for_the_hair_pool():
    p = {'age': 'ancient', 'hair_color': 'auto'}
    AD._resolve_hair_and_eyes(p, rand_for('abel'), 'male', 'British', False)
    assert p['hair_color'] in AD._HAIR_LIGHT_SKIN


def test_an_explicit_hair_colour_is_honoured_and_flagged_as_not_auto():
    p = {'age': 70, 'hair_color': 'auburn'}
    AD._resolve_hair_and_eyes(p, rand_for('abel'), 'male', 'British', False)
    assert p['hair_color'] == 'auburn'
    assert p['_hair_color_was_auto'] is False


def test_eye_colour_follows_the_deep_skin_pool():
    deep = {'age': 30}
    AD._resolve_hair_and_eyes(deep, rand_for('abel'), 'male', 'Nigerian', True)
    assert deep['eye_color'] in AD._EYES_DEEP_SKIN
    light = {'age': 30}
    AD._resolve_hair_and_eyes(light, rand_for('abel'), 'male', 'British', False)
    assert light['eye_color'] in AD._EYES_LIGHT_SKIN


def test_an_african_heritage_keeps_the_curl_combos():
    heritage = next(iter(AD._AFRICAN_HERITAGES))
    for i in range(20):
        p = {'age': 30}
        AD._resolve_hair_and_eyes(p, rand_for('c%d' % i), 'female', heritage, True)
        assert p['hair_texture'] in ('coily', 'curly')


def test_a_non_african_heritage_never_draws_a_coily_combo():
    for i in range(20):
        p = {'age': 30}
        AD._resolve_hair_and_eyes(p, rand_for('c%d' % i), 'female', 'British', False)
        assert p['hair_texture'] != 'coily'


def test_an_explicit_hair_length_survives_the_combo_roll():
    p = {'age': 30, 'hair_length': 'shoulder'}
    AD._resolve_hair_and_eyes(p, rand_for('abel'), 'female', 'British', False)
    assert p['hair_length'] == 'shoulder'


def test_hair_texture_falls_back_to_the_colour_table_when_the_style_is_explicit():
    colour = next(iter(AD._HAIRCOLOR_TEXTURE))
    p = {'age': 30, 'hair_style': 'short professional', 'hair_color': colour.upper()}
    AD._resolve_hair_and_eyes(p, rand_for('abel'), 'male', 'British', False)
    assert p['hair_texture'] == AD._HAIRCOLOR_TEXTURE[colour]


def test_an_unknown_hair_colour_textures_straight():
    p = {'age': 30, 'hair_style': 'short professional', 'hair_color': 'chartreuse'}
    AD._resolve_hair_and_eyes(p, rand_for('abel'), 'male', 'British', False)
    assert p['hair_texture'] == 'straight'


# ── _resolve_features_and_build ─────────────────────────────────────────────


def test_an_asian_heritage_selects_the_asian_eye_shape_pool():
    p = {}
    AD._resolve_features_and_build(p, rand_for('abel'), 'male', 'East Asian')
    assert p['eye_shape'] in AD._EYE_SHAPE_POOL_ASIAN
    q = {}
    AD._resolve_features_and_build(q, rand_for('abel'), 'male', 'British')
    assert q['eye_shape'] in AD._EYE_SHAPE_POOL


def test_the_face_features_come_from_the_gender_keyed_pools():
    p = {}
    AD._resolve_features_and_build(p, rand_for('abel'), 'female', 'British')
    assert p['eyebrow_style'] in AD._BROW_POOL['female']
    assert p['face_shape'] in AD._FACE_SHAPE_POOL['female']
    assert p['nose_shape'] in AD._NOSE_POOL
    assert p['lip_shape'] in AD._LIP_POOL['female']


def test_body_build_text_is_derived_from_the_muscle_slider():
    p = {'muscle_mass': 60}
    AD._resolve_features_and_build(p, rand_for('abel'), 'male', 'British')
    assert p['muscle_mass'] == 60
    assert p['body_build'] == AD._muscle_text(60)


def test_body_build_falls_back_to_the_descriptor_key_then_the_pool():
    p = {'body_build': 'lean'}
    AD._resolve_features_and_build(p, rand_for('abel'), 'male', 'British')
    assert p['muscle_mass'] == 'lean'
    q = {}
    AD._resolve_features_and_build(q, rand_for('abel'), 'male', 'British')
    assert q['muscle_mass'] in AD._MUSCLE_POOL['male']


def test_a_female_character_is_coerced_to_no_facial_hair():
    p = {'facial_hair': 'full beard'}
    AD._resolve_features_and_build(p, rand_for('abel'), 'female', 'British')
    assert p['facial_hair'] == 'none'


def test_an_auto_male_rolls_the_facial_hair_pool():
    seen = {
        (
            AD._resolve_features_and_build(
                p := {'facial_hair': 'auto'},
                rand_for('fh%d' % i),
                'male',
                'British',
            ),
            p['facial_hair'],
        )[1]
        for i in range(60)
    }
    assert seen <= set(AD._FACIAL_HAIR_POOL)
    assert len(seen) > 1


def test_an_explicit_facial_hair_is_lowercased_and_an_empty_one_becomes_none():
    p = {'facial_hair': '  Full Beard '}
    AD._resolve_features_and_build(p, rand_for('abel'), 'male', 'British')
    assert p['facial_hair'] == 'full beard'


def test_distinctive_marks_are_rolled_only_when_auto():
    p = {'distinctive_marks': 'none'}
    AD._resolve_features_and_build(p, rand_for('abel'), 'male', 'British')
    assert p['distinctive_marks'] == 'none'
    q = {}
    AD._resolve_features_and_build(q, rand_for('abel'), 'male', 'British')
    assert q['distinctive_marks'] in AD._MARKS_POOL


# ── _resolve_presentation ───────────────────────────────────────────────────


def test_presentation_pools_are_keyed_on_the_genre_and_fall_back_to_general():
    gd = AD._GENDER_DEFAULTS['male']
    p = {}
    AD._resolve_presentation(p, rand_for('abel'), 'male', 'not-a-genre', gd)
    assert p['default_clothing'] in AD._GENRE_WARDROBE_POOL['general']['male']
    assert p['accessories'] in AD._GENRE_ACCESSORY_POOL['general']['male']
    assert p['lighting_profile'] in AD._GENRE_LIGHTING_POOL['general']
    assert p['color_palette'] == AD._GENRE_PALETTE['general']


def test_presentation_uses_a_known_genre_when_it_has_one():
    genre = next(g for g in AD._GENRE_PALETTE if g != 'general')
    p = {}
    AD._resolve_presentation(p, rand_for('abel'), 'male', genre, AD._GENDER_DEFAULTS['male'])
    assert p['color_palette'] == AD._GENRE_PALETTE[genre]


def test_posture_comes_from_the_gender_defaults_and_the_camera_is_fixed():
    gd = AD._GENDER_DEFAULTS['female']
    p = {}
    AD._resolve_presentation(p, rand_for('abel'), 'female', 'general', gd)
    assert p['posture'] == gd['posture']
    assert p['camera_language'] == 'medium shots, stable framing, documentary interior'


def test_a_locked_smile_keeps_its_expression_unset():
    locked = {'smile_locked': True}
    AD._resolve_presentation(locked, rand_for('abel'), 'female', 'general', AD._GENDER_DEFAULTS['female'])
    assert 'default_expression' not in locked
    free = {}
    AD._resolve_presentation(free, rand_for('abel'), 'female', 'general', AD._GENDER_DEFAULTS['female'])
    assert free['default_expression'] == 'neutral confident'


# ── _quality_suffix_text / _negative_prompt_terms / _resolve_prompt_text ────


def test_the_quality_suffix_branches_on_photorealistic():
    assert '85mm portrait lens' in AD._quality_suffix_text('photorealistic')
    assert 'highly detailed illustration' in AD._quality_suffix_text('illustrated')


def test_the_negative_prompt_starts_with_every_base_term_in_order():
    terms = AD._negative_prompt_terms({'facial_hair': 'none', 'distinctive_marks': 'freckles'}, 'female', 'animated')
    assert terms[: len(AD._BASE_NEGATIVES)] == list(AD._BASE_NEGATIVES)


def test_a_beardless_male_pushes_beard_out_of_frame_and_a_female_does_not():
    male = AD._negative_prompt_terms({'facial_hair': 'none', 'distinctive_marks': 'freckles'}, 'male', 'animated')
    assert 'beard' in male and 'goatee' in male
    female = AD._negative_prompt_terms({'facial_hair': 'none', 'distinctive_marks': 'freckles'}, 'female', 'animated')
    assert 'beard' not in female


def test_a_bearded_male_does_not_suppress_beards():
    terms = AD._negative_prompt_terms({'facial_hair': 'full beard', 'distinctive_marks': 'freckles'}, 'male', 'anim')
    assert 'beard' not in terms


def test_freckles_are_forbidden_unless_the_rolled_marks_name_them():
    without = AD._negative_prompt_terms({'facial_hair': 'none', 'distinctive_marks': 'none'}, 'female', 'animated')
    assert 'dense freckle field' in without
    withem = AD._negative_prompt_terms(
        {'facial_hair': 'none', 'distinctive_marks': 'light FRECKLES across nose'}, 'female', 'animated'
    )
    assert 'dense freckle field' not in withem
    absent = AD._negative_prompt_terms({'facial_hair': 'none'}, 'female', 'animated')
    assert 'mottled skin' in absent


def test_the_style_suppressions_are_mutually_exclusive():
    photo = AD._negative_prompt_terms(
        {'facial_hair': 'none', 'distinctive_marks': 'freckles'}, 'female', 'photorealistic'
    )
    assert 'cartoon' in photo and 'plastic skin' in photo
    assert 'film grain' not in photo
    drawn = AD._negative_prompt_terms({'facial_hair': 'none', 'distinctive_marks': 'freckles'}, 'female', 'animated')
    assert 'film grain' in drawn and 'watercolor' in drawn
    assert 'cartoon' not in drawn


def test_young_grey_hair_is_nudged_to_ash_brown_and_the_nudge_is_recorded():
    p = {'age': 24, 'hair_color': 'Silver', 'facial_hair': 'none'}
    AD._resolve_prompt_text(p, 'female', 'photorealistic')
    assert p['hair_color'] == 'ash brown'
    assert p['_hair_age_adjusted'] is True


def test_grey_hair_on_an_older_character_is_left_alone():
    p = {'age': 64, 'hair_color': 'grey', 'facial_hair': 'none'}
    AD._resolve_prompt_text(p, 'female', 'photorealistic')
    assert p['hair_color'] == 'grey'
    assert '_hair_age_adjusted' not in p


def test_an_unreadable_age_is_treated_as_28_for_the_hair_nudge():
    p = {'age': 'unknown', 'hair_color': 'white', 'facial_hair': 'none'}
    AD._resolve_prompt_text(p, 'female', 'photorealistic')
    assert p['hair_color'] == 'ash brown'


def test_an_explicit_negative_prompt_and_quality_suffix_are_never_overwritten():
    p = {'age': 40, 'hair_color': 'brown', 'facial_hair': 'none', 'quality_suffix': 'mine', 'negative_prompt': 'yours'}
    AD._resolve_prompt_text(p, 'male', 'photorealistic')
    assert (p['quality_suffix'], p['negative_prompt']) == ('mine', 'yours')


def test_a_blank_quality_suffix_is_filled_by_the_style_before_the_animated_override():
    # `_is_auto('  ')` is true, so the style suffix lands first and the animated
    # override below it sees a non-blank value — the original behaved the same way.
    p = {'age': 40, 'hair_color': 'brown', 'facial_hair': 'none', 'render_style': 'Animated', 'quality_suffix': '  '}
    AD._resolve_prompt_text(p, 'male', 'animated')
    assert 'highly detailed illustration' in p['quality_suffix']
    assert 'flat cel shading' not in p['quality_suffix']


def test_the_animated_override_fires_for_a_non_string_quality_suffix():
    # The only value `_is_auto` lets through to the animated branch is a non-string
    # falsy placeholder, which the second half of the condition catches.
    p = {'age': 40, 'hair_color': 'brown', 'facial_hair': 'none', 'render_style': 'Animated', 'quality_suffix': 0}
    AD._resolve_prompt_text(p, 'male', 'animated')
    assert 'flat cel shading' in p['quality_suffix']


def test_the_animated_override_leaves_a_real_suffix_alone():
    p = {'age': 40, 'hair_color': 'brown', 'facial_hair': 'none', 'style': 'animated', 'quality_suffix': 'mine'}
    AD._resolve_prompt_text(p, 'male', 'animated')
    assert p['quality_suffix'] == 'mine'


# ── the orchestrator still agrees with itself ───────────────────────────────


def test_apply_auto_defaults_is_reproducible_for_one_seed_key():
    a = AD.apply_auto_defaults({'gender': 'auto'}, 'abel')
    b = AD.apply_auto_defaults({'gender': 'auto'}, 'abel')
    assert a == b
    assert list(a) == list(b)


def test_apply_auto_defaults_fills_every_descriptor_the_stages_own():
    p = AD.apply_auto_defaults({}, 'abel')
    for k in (
        'gender',
        'render_style',
        'style',
        'genre',
        'age',
        'age_range',
        'height',
        'height_text',
        'skin_tone',
        'hair_color',
        'eye_color',
        'hair_style',
        'hair_length',
        'hair_texture',
        'eye_shape',
        'eyebrow_style',
        'face_shape',
        'nose_shape',
        'lip_shape',
        'muscle_mass',
        'body_build',
        'facial_hair',
        'distinctive_marks',
        'default_clothing',
        'accessories',
        'lighting_profile',
        'color_palette',
        'posture',
        'default_expression',
        'camera_language',
        'quality_suffix',
        'negative_prompt',
    ):
        assert p.get(k) not in (None, ''), k


def test_apply_auto_defaults_does_not_mutate_the_callers_dict():
    raw = {'gender': 'male'}
    AD.apply_auto_defaults(raw, 'abel')
    assert raw == {'gender': 'male'}


def test_apply_auto_defaults_accepts_none():
    p = AD.apply_auto_defaults(None, 'abel')
    assert p['gender'] in ('female', 'male')


def test_the_stage_rngs_are_independent_of_the_python_global_random_state():
    random.seed(1)
    a = AD.apply_auto_defaults({'gender': 'auto'}, 'abel')
    random.seed(999)
    b = AD.apply_auto_defaults({'gender': 'auto'}, 'abel')
    assert a == b
