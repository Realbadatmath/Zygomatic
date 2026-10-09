# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Unit tests for the helpers extracted out of `stage_01_scene_plan`.

Only the pure ones: the nvidia-smi CSV parser, the planner prompt builders, the
planner reply parser and the fallback scene list. No GPU, no Claude, no files.
"""

import pytest

from zyg_workflows.video_stages import stage_01_scene_plan as S


def test_parse_compute_apps_reads_pid_and_megabytes():
    assert S._parse_compute_apps('1234, 2048\n5678, 512\n') == [(1234, 2048), (5678, 512)]


def test_parse_compute_apps_drops_rows_it_cannot_read():
    assert S._parse_compute_apps('1234, 2048\nno-processes-found\n9, [N/A]\n') == [(1234, 2048)]


def test_parse_compute_apps_of_empty_output_is_empty():
    assert S._parse_compute_apps('   \n') == []


def test_parse_scene_plan_takes_the_object_form_with_its_mood():
    scenes, mood = S._parse_scene_plan('{"music_mood": " Epic ", "scenes": [{"a": 1}, {"a": 2}]}', 2)
    assert scenes == [{'a': 1}, {'a': 2}]
    assert mood == 'epic'


def test_parse_scene_plan_strips_a_markdown_fence():
    scenes, mood = S._parse_scene_plan('```json\n{"music_mood": "dark", "scenes": [{"a": 1}]}\n```', 1)
    assert (scenes, mood) == ([{'a': 1}], 'dark')


def test_parse_scene_plan_accepts_the_legacy_plain_array_without_a_mood():
    scenes, mood = S._parse_scene_plan('[{"a": 1}, {"a": 2}]', 2)
    assert (scenes, mood) == ([{'a': 1}, {'a': 2}], '')


def test_parse_scene_plan_trims_a_reply_that_is_too_long():
    scenes, _mood = S._parse_scene_plan('{"scenes": [{"a": 1}, {"a": 2}, {"a": 3}]}', 2)
    assert scenes == [{'a': 1}, {'a': 2}]


def test_parse_scene_plan_refuses_a_reply_that_is_too_short():
    with pytest.raises(ValueError, match='Unexpected scene count: 1'):
        S._parse_scene_plan('{"scenes": [{"a": 1}]}', 3)


def test_fallback_scenes_are_numbered_and_carry_no_props():
    scenes = S._fallback_scenes('a very long directive about ' + 'x' * 90, 3)
    assert len(scenes) == 3
    assert scenes[0]['description'].startswith('Scene 1:')
    assert scenes[2]['narration'].startswith('Scene 3 of the video about ')
    assert all(s['props'] == [] for s in scenes)
    # The directive is quoted at 60 characters, not in full.
    assert 'x' * 61 not in scenes[0]['description']


def test_manga_plan_prompts_ask_for_illustrated_panels():
    system, user = S._manga_plan_prompts('a duel on a rooftop', 4, 6, 'ink and screentone')
    assert 'manga editor' in system
    assert 'MANGA (ink and screentone)' in system
    assert '4-panel manga/comic plan' in user
    assert '"a duel on a rooftop"' in user
    assert 'Each panel is 6 seconds' in user
    assert '"wan_prompt": "" (unused' in user


def test_video_plan_prompts_carry_the_style_the_duration_and_both_prompt_keys():
    system, user = S._video_plan_prompts('the fall of Rome', 3, 8, 'cinematic', 'warm film grain')
    assert 'CINEMATIC (warm film grain)' in system
    assert 'Create a 3-scene video plan' in user
    assert 'Total runtime: 24 seconds (3 scenes × 8s)' in user
    assert 'array of 3 scene objects' in user
    assert '"flux_prompt"' in user and '"wan_prompt"' in user


def test_video_plan_prompts_say_scene_singular_for_one_scene():
    _system, user = S._video_plan_prompts('one long take', 1, 10, 'cinematic', 'warm film grain')
    assert 'Total runtime: 10 seconds (1 scene × 10s)' in user


def test_scene_plan_prompts_pick_the_manga_builder_in_manga_mode():
    _system, user = S._scene_plan_prompts(True, 'a duel', 2, 5, 'cinematic', 'ink and screentone')
    assert '2-panel manga/comic plan' in user


def test_scene_plan_prompts_pick_the_video_builder_otherwise():
    _system, user = S._scene_plan_prompts(False, 'a duel', 2, 5, 'cinematic', 'warm film grain')
    assert 'Create a 2-scene video plan' in user


def test_dsl_scene_metadata_maps_one_planned_scene():
    class _Dsl:
        def dsl_setting_for_scene(self, sc, directive):
            return f'{sc["scene_type"]}:{directive}'

        def dsl_aspect_for_scene(self, sc):
            return '16:9'

    meta = S._dsl_scene_metadata(
        {'description': 'd' * 300, 'shot_type': 'close-up', 'scene_type': 'character'},
        'the fall of Rome',
        'cinematic',
        7,
        _Dsl(),
    )
    assert meta['duration'] == 7.0
    assert len(meta['subject']) == 200
    assert meta['setting'] == 'character:the fall of Rome'
    assert meta['lighting_style'] == 'cool_blue'
    assert meta['aspect_ratio'] == '16:9'
    assert meta['composition'] == 'close-up'
    assert meta['tags'] == ['video', 'cinematic', 'character']


def test_dsl_scene_metadata_leaves_the_lighting_blank_off_cinematic():
    class _Dsl:
        def dsl_setting_for_scene(self, sc, directive):
            return ''

        def dsl_aspect_for_scene(self, sc):
            return '1:1'

    meta = S._dsl_scene_metadata({}, 'topic', 'manga', 4, _Dsl())
    assert meta['lighting_style'] == ''
    assert meta['composition'] == ''
