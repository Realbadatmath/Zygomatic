# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Unit tests for the Stage 2a helpers split out of ``stage_02a_sonnet_story``.

Every helper exercised here is pure — prompt text assembly, JSON parsing, the
word arithmetic and the in-place narration fold — so no Anthropic client, no
network and no pipeline context is built. ``run_sonnet_story_call`` and the two
rewrite round-trips are not covered: they exist only to make one streaming API
call each.
"""

import re

from zyg_workflows.storyteller.stages_02_story_script_sonnet import (
    apply_rewritten_narrations,
    build_sonnet_prompts,
    fallback_scenes,
    narration_word_count,
    parse_rewrite_array,
    parse_story_scenes,
    scene_budget_list,
)


def _silent_log(*_args, **_kwargs):
    """A ``_log`` stand-in that swallows the line the helper would have logged."""


# ── build_sonnet_prompts ──────────────────────────────────────────────────────


def test_the_prompt_names_the_scene_count_the_budget_and_the_character():
    _sys, user = build_sonnet_prompts(
        'a 30-year-old woman, brown hair',
        3.0,
        'present day',
        6,
        [40, 55, 70, 70, 55, 40],
        'The Long Way Home',
        'cinematic',
        330,
        'narration',
    )
    assert 'a 30-year-old woman, brown hair' in _sys
    assert '- Exactly 6 scenes' in user
    assert 'approximately 330 words' in user
    assert '[40, 55, 70, 70, 55, 40]' in user
    # the hard ceiling is the largest budget plus ten
    assert 'NOT exceed 80 words' in user
    assert 'The Long Way Home' in user
    assert 'present day' in user


def test_more_than_eight_scenes_previews_eight_budgets_and_names_the_total():
    _sys, user = build_sonnet_prompts(
        'a man',
        5.0,
        'the 1920s',
        11,
        list(range(50, 61)),
        'A Tale',
        'noir',
        600,
        'narration',
    )
    assert '[50, 51, 52, 53, 54, 55, 56, 57, … (total 11 values)]' in user


def test_character_voice_adds_the_first_person_block_narration_does_not():
    args = ('a child', 2.0, 'now', 4, [50, 50, 50, 50], 'Small Things', 'animated', 200)
    sys_c, user_c = build_sonnet_prompts(*args, 'character')
    sys_n, user_n = build_sonnet_prompts(*args, 'narration')
    assert 'VOICE MODE: CHARACTER' in user_c
    assert '(long pause)' in user_c
    assert '(sighs)' in user_c
    assert 'VOICE MODE' not in user_n
    # the voice mode changes only the user prompt
    assert sys_c == sys_n


# ── parse_story_scenes ────────────────────────────────────────────────────────


def test_a_clean_reply_yields_its_scenes_and_title():
    raw = 'Here you go:\n{"title":"Dusk","scenes":[{"scene_number":1,"narration":"One two three."}]}'
    scenes, title = parse_story_scenes(raw, re, 'fallback title', _silent_log)
    assert title == 'Dusk'
    assert [s['scene_number'] for s in scenes] == [1]


def test_a_reply_without_a_title_keeps_the_default():
    raw = '{"scenes":[{"scene_number":1,"narration":"Hi."}]}'
    scenes, title = parse_story_scenes(raw, re, 'fallback title', _silent_log)
    assert title == 'fallback title'
    assert len(scenes) == 1


def test_a_reply_with_no_json_at_all_yields_no_scenes():
    scenes, title = parse_story_scenes('I am sorry, I cannot.', re, 'fallback title', _silent_log)
    assert scenes == []
    assert title == 'fallback title'


def test_a_trailing_comma_is_repaired_rather_than_losing_the_script():
    raw = '{"title":"Fixed","scenes":[{"scene_number":1,"narration":"Hi.",}]}'
    scenes, title = parse_story_scenes(raw, re, 'fallback title', _silent_log)
    assert title == 'Fixed'
    assert len(scenes) == 1


# ── fallback_scenes ──────────────────────────────────────────────────────────


def test_the_stock_script_has_the_asked_for_count_and_renderable_fields():
    scenes = fallback_scenes(9, 'a tall man', 'the far future', 'zygtok')
    assert len(scenes) == 9
    assert [s['scene_number'] for s in scenes] == list(range(1, 10))
    for s in scenes:
        assert s['narration']
        assert s['visual_concept'].startswith('a tall man ')
        assert s['flux_prompt'].startswith('zygtok a tall man ')
        assert 'the far future' in s['flux_prompt']
        assert s['shot_type']
        assert s['focal_zone'] in ('center', 'left', 'right')


def test_the_stock_script_is_not_nine_copies_of_one_scene():
    scenes = fallback_scenes(9, 'a tall man', 'now', 'tok')
    assert len({s['visual_concept'] for s in scenes}) > 1
    assert len({s['narration'] for s in scenes}) > 1
    # the arc runs from the opening beat to the closing one
    assert 'begins' in scenes[0]['narration']
    assert 'end' in scenes[-1]['narration']


def test_a_single_scene_script_does_not_divide_by_zero():
    scenes = fallback_scenes(1, 'a man', 'now', 'tok')
    assert len(scenes) == 1


# ── narration_word_count ─────────────────────────────────────────────────────


def test_words_are_counted_across_every_scene():
    scenes = [{'narration': 'one two three'}, {'narration': 'four five'}]
    assert narration_word_count(scenes) == 5


def test_a_scene_with_no_narration_counts_as_zero_rather_than_raising():
    assert narration_word_count([{'narration': 'a b'}, {'scene_number': 2}]) == 2
    assert narration_word_count([]) == 0


# ── scene_budget_list ────────────────────────────────────────────────────────


def test_trimming_picks_the_longest_scenes_first():
    scenes = [{'scene_number': i + 1, 'narration': ' '.join(['w'] * n)} for i, n in enumerate([10, 90, 50])]
    picked = scene_budget_list(scenes, [40, 40, 40], longest_first=True)
    assert [p['scene_number'] for p in picked] == [2, 3, 1]


def test_expanding_picks_the_shortest_scenes_first():
    scenes = [{'scene_number': i + 1, 'narration': ' '.join(['w'] * n)} for i, n in enumerate([10, 90, 50])]
    picked = scene_budget_list(scenes, [40, 40, 40], longest_first=False)
    assert [p['scene_number'] for p in picked] == [1, 3, 2]


def test_at_most_eight_scenes_are_ever_sent_for_rewriting():
    scenes = [{'scene_number': i + 1, 'narration': ' '.join(['w'] * (i + 1))} for i in range(20)]
    assert len(scene_budget_list(scenes, [50] * 20, longest_first=True)) == 8


def test_an_index_past_the_budget_list_gets_the_default_budget():
    scenes = [{'scene_number': 1, 'narration': 'a b'}, {'scene_number': 2, 'narration': 'c d e'}]
    picked = scene_budget_list(scenes, [33], longest_first=True)
    by_num = {p['scene_number']: p['target_words'] for p in picked}
    assert by_num[1] == 33
    assert by_num[2] == 60


def test_a_scene_with_an_empty_narration_is_not_offered_for_rewriting():
    scenes = [{'scene_number': 1, 'narration': ''}, {'scene_number': 2, 'narration': 'a b'}]
    picked = scene_budget_list(scenes, [50, 50], longest_first=True)
    assert [p['scene_number'] for p in picked] == [2]


# ── parse_rewrite_array ──────────────────────────────────────────────────────


def test_a_rewrite_array_is_parsed_out_of_surrounding_prose():
    raw = 'Sure:\n[{"scene_number":2,"narration":"Shorter now."}]\nHope that helps.'
    assert parse_rewrite_array(raw, re) == [{'scene_number': 2, 'narration': 'Shorter now.'}]


def test_a_reply_with_no_array_is_none_so_the_caller_keeps_the_original():
    assert parse_rewrite_array('I could not do that.', re) is None


def test_a_broken_rewrite_array_is_repaired():
    raw = '[{"scene_number":2,"narration":"Shorter now.",},]'
    assert parse_rewrite_array(raw, re) == [{'scene_number': 2, 'narration': 'Shorter now.'}]


# ── apply_rewritten_narrations ───────────────────────────────────────────────


def test_a_shorter_rewrite_is_taken_when_shorter_was_asked_for():
    scenes = [{'scene_number': 1, 'narration': 'one two three four'}]
    n = apply_rewritten_narrations(scenes, [{'scene_number': 1, 'narration': 'one two'}], want_shorter=True)
    assert n == 1
    assert scenes[0]['narration'] == 'one two'


def test_a_longer_rewrite_is_refused_when_shorter_was_asked_for():
    scenes = [{'scene_number': 1, 'narration': 'one two'}]
    n = apply_rewritten_narrations(scenes, [{'scene_number': 1, 'narration': 'one two three four'}], want_shorter=True)
    assert n == 0
    assert scenes[0]['narration'] == 'one two'


def test_a_longer_rewrite_is_taken_when_longer_was_asked_for():
    scenes = [{'scene_number': 1, 'narration': 'one two'}]
    n = apply_rewritten_narrations(scenes, [{'scene_number': 1, 'narration': 'one two three'}], want_shorter=False)
    assert n == 1
    assert scenes[0]['narration'] == 'one two three'


def test_an_equal_length_rewrite_is_refused_in_both_directions():
    for shorter in (True, False):
        scenes = [{'scene_number': 1, 'narration': 'one two'}]
        n = apply_rewritten_narrations(scenes, [{'scene_number': 1, 'narration': 'ONE TWO'}], want_shorter=shorter)
        assert n == 0
        assert scenes[0]['narration'] == 'one two'


def test_scenes_the_reply_did_not_mention_are_left_alone():
    scenes = [
        {'scene_number': 1, 'narration': 'one two three'},
        {'scene_number': 2, 'narration': 'four five six'},
    ]
    n = apply_rewritten_narrations(scenes, [{'scene_number': 2, 'narration': 'four'}], want_shorter=True)
    assert n == 1
    assert scenes[0]['narration'] == 'one two three'
    assert scenes[1]['narration'] == 'four'


def test_an_empty_rewrite_narration_is_skipped_rather_than_blanking_the_scene():
    scenes = [{'scene_number': 1, 'narration': 'one two three'}]
    n = apply_rewritten_narrations(scenes, [{'scene_number': 1, 'narration': ''}], want_shorter=True)
    assert n == 0
    assert scenes[0]['narration'] == 'one two three'
