# SPDX-FileCopyrightText: 2026 Zygomatic
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Helpers of the Stage 3.5 prompt builder (`prompt_builder_parts`). 2026-10-09.

Pinned: a slot's text is the words spoken in its audio window (not an even
sentence split); the emotion is the peak of the curve slice and a run of five hot
slots is broken by a relief beat unless the slot is the climax; a named entity is
preferred over the essay title and deduped against the last three images; the
shot-diversity enforcer compares framing SIZE and the intensity dial bars it from
rotating into a wide/aerial shot; the mood row has two gates (0.70 standard, 0.55
intense) and the hook always carries its own; a prebuilt prompt keeps the batch
text and only gains footers; and every murch_engine call degrades to the legacy
behaviour instead of raising.

All of this was one 489-line closure inside `stage_10_flux_image_generation`
until the split, so this is the first time it is exercised without a pipeline,
an ollama or a GPU.
"""

import pytest

from zyg_workflows import murch_engine
from zyg_workflows.scholarly.stages_19_36 import prompt_builder_parts as pp
from zyg_workflows.scholarly.stages_19_36.prompt_helpers import _make_shot_size_of

SENTS = [
    'one two three four five.',
    'six seven eight nine ten.',
    'eleven twelve thirteen fourteen fifteen.',
    'sixteen seventeen eighteen nineteen twenty.',
]
SCRIPT = ' '.join(SENTS)


def even_bounds(idx, n_total):
    """The word window of slot `idx` under a constant speech rate."""
    n_words = len(SCRIPT.split())
    return idx * n_words // n_total, (idx + 1) * n_words // n_total


def boom(*_args, **_kwargs):
    """Stand in for a murch_engine entry point that fails."""
    raise RuntimeError('murch_engine unavailable')


# ── the slot window ──────────────────────────────────────────────────────────


def test_slot_text_is_the_words_spoken_in_the_slot_window():
    seg = pp.slot_segment(even_bounds, SCRIPT, 1, 4, SENTS)
    assert seg.text == 'six seven eight nine ten.'
    assert (seg.start, seg.end) == (1, 2)
    assert seg.sentences == [SENTS[1]]


def test_a_slot_window_spanning_two_sentences_covers_both():
    seg = pp.slot_segment(lambda idx, n: (3, 12), SCRIPT, 0, 2, SENTS)
    assert seg.text == 'four five. six seven eight nine ten. eleven twelve'
    assert (seg.start, seg.end) == (0, 3)
    assert seg.sentences == SENTS[:3]


def test_a_window_past_the_end_falls_back_to_the_last_sentence():
    seg = pp.slot_segment(lambda idx, n: (100, 200), SCRIPT, 0, 1, SENTS)
    assert seg.text == ''
    assert (seg.start, seg.end) == (3, 4)


# ── emotion ──────────────────────────────────────────────────────────────────

CURVE = [
    {'emotion': 'calm', 'intensity': 0.1},
    {'emotion': 'grief', 'intensity': 0.4},
    {'emotion': 'shock', 'intensity': 0.9},
    {'emotion': 'calm', 'intensity': 0.2},
]


def test_slot_emotion_is_the_peak_of_the_curve_slice():
    assert pp.slot_emotion(CURVE, pp.SlotSegment('t', 1, 3, []), 4) == ('shock', 0.9)


def test_an_empty_curve_leaves_the_slot_calm():
    assert pp.slot_emotion([], pp.SlotSegment('t', 1, 3, []), 4) == ('calm', 0.2)


def test_a_zero_width_slice_still_reads_one_curve_entry():
    assert pp.slot_emotion(CURVE, pp.SlotSegment('t', 2, 2, []), 4) == ('shock', 0.9)


def test_five_hot_slots_force_a_relief_beat():
    recent = ['shock', 'grief', 'tension', 'shock', 'fear']
    assert pp.enforce_emotion_diversity(recent, {'calm', 'mystery'}, 'shock', 0.9, 'rising') == ('mystery', 0.45)
    assert recent[-1] == 'mystery'


def test_the_climax_is_never_broken_by_a_relief_beat():
    recent = ['shock', 'grief', 'tension', 'shock', 'fear']
    assert pp.enforce_emotion_diversity(recent, {'calm', 'mystery'}, 'shock', 0.9, 'climax') == ('shock', 0.9)
    assert recent[-1] == 'shock'


def test_a_recent_relief_beat_leaves_the_emotion_alone():
    recent = ['shock', 'calm', 'tension', 'shock', 'fear']
    assert pp.enforce_emotion_diversity(recent, {'calm', 'mystery'}, 'awe', 0.8, 'rising') == ('awe', 0.8)


def test_the_emotion_window_keeps_the_last_ten():
    recent = ['shock'] * 10
    pp.enforce_emotion_diversity(recent, {'calm'}, 'awe', 0.3, 'climax')
    assert len(recent) == 10
    assert recent[-1] == 'awe'


# ── subject, seed, event tag ─────────────────────────────────────────────────


def test_a_named_entity_beats_the_essay_title():
    used = []
    assert pp.slot_subject(lambda t: 'Cripplegate', used, 'the plague came', 'black death') == ('Cripplegate', True)
    assert used == ['Cripplegate']


def test_an_entity_used_in_the_last_three_images_is_replaced():
    used = ['Cripplegate', 'London', 'Thomas']
    subject, is_entity = pp.slot_subject(
        lambda t: 'Cripplegate', used, 'the carts left Smithfield at dawn', 'black death'
    )
    assert (subject, is_entity) == ('Smithfield', True)
    assert used[-1] == 'Smithfield'


def test_the_title_fallback_is_never_reported_as_an_entity():
    used = []
    assert pp.slot_subject(lambda t: '', used, 'the carts left at dawn', 'black death') == ('black death', False)
    assert used == []


def test_the_entity_seed_is_stable_per_run_and_salted_between_runs():
    assert pp.entity_seed('Cripplegate', 'run-1') == pp.entity_seed('Cripplegate', 'run-1')
    assert pp.entity_seed('Cripplegate', 'run-1') != pp.entity_seed('Cripplegate', 'run-2')


def test_no_seed_when_the_engine_cannot_give_one(monkeypatch):
    monkeypatch.setattr(murch_engine, 'get_entity_seed', boom)
    assert pp.entity_seed('Cripplegate', 'run-1') is None


def test_the_event_tag_is_the_first_sentence_level_tag():
    tag = pp.slot_event_tag(lambda s: 'battle' if 'siege' in s else '', lambda s: 'portrait', ['a dawn', 'a siege'])
    assert tag == 'battle'


def test_without_a_sentence_level_tag_the_modal_sentence_tag_wins():
    tag = pp.slot_event_tag(lambda s: '', lambda s: 'portrait' if s.startswith('a') else 'map', ['a', 'a', 'b'])
    assert tag == 'portrait'


def test_an_empty_slot_still_gets_a_tag():
    assert pp.slot_event_tag(lambda s: '', lambda s: 'portrait', []) == 'historical archive'


# ── arc zone, weights, composition: the murch_engine fallbacks ───────────────


@pytest.mark.parametrize(
    ('start', 'zone'),
    [(0, 'exposition'), (6, 'rising'), (10, 'climax'), (15, 'falling'), (19, 'resolution')],
)
def test_the_arc_zone_falls_back_to_a_fractional_split(monkeypatch, start, zone):
    monkeypatch.setattr(murch_engine, 'get_arc_zone', boom)
    assert pp.slot_arc_zone(pp.SlotSegment('t', start, start + 1, []), [], 20) == zone


def test_scene_weights_fall_back_to_the_profile_passed_in(monkeypatch):
    monkeypatch.setattr(murch_engine, 'classify_scene_type', boom)
    weights = {'emotion': 1.0}
    assert pp.scene_weight_profile('a siege at dawn', weights, []) is weights


def test_a_slot_is_framed_without_a_constraint_when_the_engine_fails(monkeypatch):
    monkeypatch.setattr(murch_engine, 'get_composition_constraint', boom)
    assert pp.composition_constraint('left', 'shock', 'climax', []) == ''


# ── shot grammar ─────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ('idx', 'intensity', 'zone', 'hook', 'alternate', 'expected'),
    [
        (0, 0.1, 'exposition', True, False, 'extreme close-up, tight crop, raw arresting detail'),
        (1, 0.1, 'exposition', False, True, 'medium shot, cinematic, something at stake in frame'),
        (2, 0.1, 'exposition', False, True, 'close-up, tight focus, charged detail'),
        (2, 0.9, 'climax', False, False, 'extreme close-up, tight crop'),
        (2, 0.7, 'rising', False, False, 'medium shot, dramatic angle'),
        (2, 0.5, 'rising', False, False, 'medium wide shot, cinematic'),
        (2, 0.2, 'falling', False, False, 'wide establishing shot'),
    ],
)
def test_the_legacy_shot_ladder_takes_over_when_the_grammar_fails(
    monkeypatch, idx, intensity, zone, hook, alternate, expected
):
    monkeypatch.setattr(murch_engine, 'get_shot_type_grammar', boom)
    shot = pp.slot_shot_type(
        idx,
        'shock',
        intensity,
        zone,
        pp.DEFAULT_SCENE_WEIGHTS,
        'Cripplegate',
        '',
        [],
        hook_slot=hook,
        exposition_alternate=alternate,
    )
    assert shot == expected


ROTATION = ['wide establishing shot, cinematic', 'close-up, tight focus', 'extreme close-up, raw detail']


def rotate(sizes, types, shot, zone, *, flat_half=False):
    """Run the diversity enforcer over one shot with the stage's real size map."""
    return pp.enforce_shot_diversity(sizes, types, ROTATION, _make_shot_size_of(), shot, zone, flat_half=flat_half)


def test_the_same_framing_three_times_running_is_rotated_away():
    sizes, types = [], []
    medium = 'medium shot, cinematic'
    assert rotate(sizes, types, medium, 'rising') == medium
    assert rotate(sizes, types, 'medium shot, somber', 'rising') == 'medium shot, somber'
    assert rotate(sizes, types, medium, 'rising') == 'wide establishing shot, cinematic'
    assert sizes == ['ms', 'ms', 'ws']
    assert types[-1] == 'wide establishing shot, cinematic'


def test_the_intensity_dial_bars_a_rotation_into_a_wide_shot():
    sizes, types = [], []
    for _ in range(2):
        rotate(sizes, types, 'medium shot, cinematic', 'rising', flat_half=True)
    assert rotate(sizes, types, 'medium shot, cinematic', 'rising', flat_half=True) == 'close-up, tight focus'


def test_repetition_at_the_climax_is_left_alone():
    sizes, types = [], []
    medium = 'medium shot, cinematic'
    for _ in range(2):
        rotate(sizes, types, medium, 'climax')
    assert rotate(sizes, types, medium, 'climax') == medium
    assert sizes == ['ms', 'ms', 'ms']


def test_the_shot_windows_keep_the_last_six():
    sizes, types = [], []
    for i in range(8):
        rotate(sizes, types, f'wide establishing shot {i}', 'climax')
    assert len(sizes) == 6
    assert len(types) == 6


# ── the prompt rows ──────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ('prev', 'intensity', 'expected'),
    [
        ('', 0.9, ''),
        ('wide establishing shot of the fields', 0.6, ', dramatic contrast with preceding calm, sudden visual shift'),
        ('wide establishing shot of the fields', 0.59, ''),
        ('the battle at the gate', 0.4, ', reflective aftermath, quiet desolation, emotional release'),
        ('the battle at the gate', 0.41, ''),
    ],
)
def test_the_kuleshov_clause_reads_against_the_previous_slot(prev, intensity, expected):
    assert pp.kuleshov_modifier(prev, intensity) == expected


def test_the_style_row_follows_the_arc_zone_then_the_flat_rotation():
    styles = [f', s{i}' for i in range(6)]
    arc = {'climax': [2, 5]}
    assert pp.style_suffix(arc, styles, 'climax', 0) == ', s2'
    assert pp.style_suffix(arc, styles, 'climax', 1) == ', s5'
    assert pp.style_suffix(arc, styles, 'rising', 3) == ', s3'


@pytest.mark.parametrize(
    ('emotion', 'intensity', 'intense', 'expected'),
    [
        ('shock', 0.70, False, ', ' + pp.EMOTION_MOOD_MAP['shock']),
        ('shock', 0.69, False, ''),
        ('shock', 0.55, True, ', ' + pp.EMOTION_MOOD_MAP_INTENSE['shock']),
        ('shock', 0.54, True, ''),
        ('fear', 0.9, False, ''),  # the standard row has no 'fear' entry
        ('fear', 0.9, True, ', ' + pp.EMOTION_MOOD_MAP_INTENSE['fear']),
        ('calm', 0.9, True, ''),
    ],
)
def test_the_mood_row_has_a_gate_per_dial_setting(emotion, intensity, intense, expected):
    assert pp.emotion_mood(emotion, intensity, intense=intense, hook_slot=False) == expected


def test_the_hook_always_carries_its_own_mood_row():
    assert pp.emotion_mood('calm', 0.1, intense=False, hook_slot=True) == pp.HOOK_MOOD
    assert pp.emotion_mood('shock', 0.9, intense=True, hook_slot=True) == pp.HOOK_MOOD


def test_the_hook_takes_the_level_above_the_episode():
    dial = {'level': 'standard', 'hook_level': 'high'}
    assert pp.intensity_suffix(dial, hook_slot=False) == ''
    assert pp.intensity_suffix(dial, hook_slot=True) != ''


def test_a_prebuilt_prompt_keeps_the_batch_text_and_gains_the_footers():
    out = pp.prebuilt_prompt(
        [{'standard': 'a cart of bodies', 'counterpoint': 'an empty market'}],
        0,
        quality_footer=', 8k',
        suffix=', charged',
        era_suffix=', medieval',
        anatomy_hint='two hands',
    )
    assert out == 'a cart of bodies, 8k, charged, medieval, two hands'


def test_a_prebuilt_prompt_may_also_be_a_plain_string():
    out = pp.prebuilt_prompt(['a cart of bodies'], 0, quality_footer='', suffix='', era_suffix='', anatomy_hint='')
    assert out == 'a cart of bodies'


@pytest.mark.parametrize('prebuilt', [[], ['only one'], None])
def test_no_prebuilt_prompt_for_this_slot_is_reported_as_none(prebuilt):
    assert pp.prebuilt_prompt(prebuilt, 1, quality_footer='', suffix='', era_suffix='', anatomy_hint='') is None


def test_the_scene_description_needs_four_words_to_be_used():
    state = {'visual_tags': [{'scene_desc': 'a cart of bodies in a street'}, {'scene_desc': 'a cart'}]}
    assert pp.fallback_scene_desc(state, 0, 'black death') == 'a cart of bodies in a street'
    assert pp.fallback_scene_desc(state, 1, 'black death') == 'black death'
    assert pp.fallback_scene_desc({}, 0, 'black death') == 'black death'


def test_the_prompt_rows_are_joined_in_the_order_flux_reads_them():
    out = pp.assemble_fallback_prompt(
        'a cart of bodies',
        'close-up, tight focus',
        mood=', raw emotion',
        style=', woodcut',
        kuleshov=', quiet desolation',
        era_suffix=', medieval',
        suffix=', charged',
        composition='subject on left third',
        anatomy_hint='two hands',
    )
    assert out == (
        'a cart of bodies, close-up, tight focus, raw emotion, woodcut, quiet desolation'
        ', medieval, charged, subject on left third, two hands'
    )


def test_the_composition_and_anatomy_rows_are_optional():
    out = pp.assemble_fallback_prompt(
        'a cart of bodies',
        'wide establishing shot',
        mood='',
        style=', woodcut',
        kuleshov='',
        era_suffix='',
        suffix='',
        composition='',
        anatomy_hint='',
    )
    assert out == 'a cart of bodies, wide establishing shot, woodcut'
