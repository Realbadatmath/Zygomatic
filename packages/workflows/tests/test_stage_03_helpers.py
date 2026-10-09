# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The steps of scholarly stage 3, exercised on their own for the first time.

`stage_03_script_preparation` was a 680-line def: the only way to ask "does a
narration that opens on a journal masthead get refused?" was to run a whole
documentary pipeline, Claude call and all. The 2026-10-09 split moved each step
into `stage_03_prep` / `stage_03_llm`, and the tests below pin the behaviours
the stage used to hide — the response parser, the title-echo stripper, the
publishable-prose gate, the duration budget, the prompt assembly and the final
pipeline-state write.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from zyg_workflows.scholarly.stages_01_18 import stage_03_llm as LLM
from zyg_workflows.scholarly.stages_01_18 import stage_03_prep as P


def fake_ctx(**kw):
    """A stand-in `RunContext` with the few fields stage 3's helpers read.

    `_log` appends to `ctx.logs` and `_save` counts its calls, so a test can
    assert on what the stage reported as well as on what it computed.
    """
    ctx = SimpleNamespace(
        topic='topic',
        directive='',
        essay_text='',
        narration_script='',
        pipeline_id='abcdef123456',
        pipeline_state={},
        _sch_duration_targets={},
        _stage3_llm_model=None,
        _wiki_source_block='',
        logs=[],
        saves=0,
    )
    ctx._log = lambda level, stage, msg: ctx.logs.append((level, stage, msg))
    ctx._save = lambda: setattr(ctx, 'saves', ctx.saves + 1)
    for name, value in kw.items():
        setattr(ctx, name, value)
    return ctx


# ── _parse_stage3_resp: narration / [VISUAL_SCENES] / [YOUTUBE_META] ──────────


def test_parser_splits_narration_scenes_and_youtube_meta():
    raw = (
        'The river froze that winter.\n\n'
        '[VISUAL_SCENES]\n'
        '["wide shot of a frozen river at dawn, mist over black ice"]\n'
        '[/VISUAL_SCENES]\n'
        '[YOUTUBE_META]\n'
        '{"title": "The Winter The River Stopped", "tags": ["rivers", "winter"]}\n'
        '[/YOUTUBE_META]'
    )
    text, scenes, meta = LLM._parse_stage3_resp(raw)
    assert text == 'The river froze that winter.'
    assert scenes == ['wide shot of a frozen river at dawn, mist over black ice']
    assert meta['title'] == 'The Winter The River Stopped'
    assert meta['tags'] == ['rivers', 'winter']


def test_parser_strips_the_code_fences_the_model_adds():
    raw = 'Narration.\n[VISUAL_SCENES]\n```json\n["a scene"]\n```\n[/VISUAL_SCENES]'
    text, scenes, meta = LLM._parse_stage3_resp(raw)
    assert (text, scenes, meta) == ('Narration.', ['a scene'], {})


def test_parser_keeps_the_narration_when_the_scene_json_is_broken():
    raw = 'Narration.\n[VISUAL_SCENES]\n["unterminated\n[/VISUAL_SCENES]'
    text, scenes, meta = LLM._parse_stage3_resp(raw)
    assert text == 'Narration.'
    assert scenes == []
    assert meta == {}


def test_parser_survives_unparsable_youtube_meta_without_losing_the_script():
    raw = 'Narration.\n[YOUTUBE_META]\nnot json at all\n[/YOUTUBE_META]'
    text, scenes, meta = LLM._parse_stage3_resp(raw)
    assert text == 'Narration.'
    assert meta == {}
    assert scenes == []


def test_parser_returns_a_bare_narration_unchanged():
    assert LLM._parse_stage3_resp('  Just the story.  ') == ('Just the story.', [], {})


# ── _drop_title_echoes: the heading read aloud as a sentence ──────────────────


def test_title_echo_sentence_is_dropped_but_the_paragraph_survives():
    script = 'The Sikh Empire. For fifty years, it stood.'
    out, removed = P._drop_title_echoes(script, 'The Sikh Empire')
    assert out == 'For fifty years, it stood.'
    assert removed == ['The Sikh Empire.']


def test_a_paragraph_that_is_only_the_title_is_left_alone():
    script = 'The Sikh Empire.'
    out, removed = P._drop_title_echoes(script, 'The Sikh Empire')
    assert out == script
    assert removed == []


def test_a_sentence_repeating_the_previous_paragraph_is_dropped():
    script = 'And how it fell. This is the Sikh Empire.\n\nThis is the Sikh Empire. It began in 1799.'
    out, removed = P._drop_title_echoes(script, 'something else entirely')
    assert out.split('\n\n')[1] == 'It began in 1799.'
    assert removed == ['This is the Sikh Empire.']


def test_ordinary_prose_keeps_every_sentence():
    script = 'In 1799 a young commander took Lahore. The city never forgot him.'
    out, removed = P._drop_title_echoes(script, 'The Sikh Empire')
    assert (out, removed) == (script, [])


# ── _prose_gate_failure: provenance first, furniture second ───────────────────


def test_prose_gate_passes_a_clean_llm_script():
    assert P._prose_gate_failure('word ' * 200, 'claude-sonnet-4-6') == ''


def test_prose_gate_refuses_anything_the_regex_fallback_forwarded():
    why = P._prose_gate_failure('word ' * 200, 'regex')
    assert 'regex fallback' in why
    assert 'llm=regex' in why


def test_prose_gate_names_none_when_no_model_wrote_the_script():
    assert 'llm=none' in P._prose_gate_failure('word ' * 200, '')


def test_prose_gate_catches_a_journal_masthead_from_any_model():
    script = 'Heliyon 7 (2021) e06580 Contents lists available at ScienceDirect. ' + 'word ' * 200
    why = P._prose_gate_failure(script, 'claude-sonnet-4-6')
    assert 'research-paper furniture' in why
    assert '2 marker(s)' in why


def test_prose_gate_stays_quiet_on_a_short_script_the_word_gate_owns():
    assert P._prose_gate_failure('doi: 10.1000/xyz ' * 2, 'regex') == ''


# ── _duration_targets: the word budget and the prompt rules it implies ────────


def test_long_form_targets_come_from_the_pipeline_targets():
    ctx = fake_ctx(
        _sch_duration_targets={
            'min_words': 3000,
            'target_words': 4000,
            'max_words': 5000,
            'min_word_gate': 2500,
        }
    )
    t = P._duration_targets(ctx)
    assert (t.min_words, t.target_words, t.max_words, t.word_gate) == (3000, 4000, 5000, 2500)
    assert t.duration_capped is False
    assert t.retry_words == 2680  # max(800, 4000 * 0.67)
    assert t.accept_words == 2125  # max(600, 2500 * 0.85)
    assert t.hard_cap_rule == ''
    assert '10 sections' in t.structure_block
    assert ctx.logs == []


def test_short_doc_targets_add_the_hard_cap_and_the_short_structure():
    ctx = fake_ctx(
        pipeline_state={
            'scholarly_duration_targets': {
                'min_words': 120,
                'target_words': 150,
                'max_words': 180,
                'min_word_gate': 100,
                'duration_capped': True,
            }
        }
    )
    t = P._duration_targets(ctx)
    assert t.duration_capped is True
    assert t.retry_words == 90  # max(50, 150 * 0.6)
    assert t.accept_words == 90  # max(80, 120 * 0.75)
    assert 'CRITICAL HARD CAP' in t.hard_cap_rule
    assert 'absolute maximum 180 words' in t.hard_cap_rule
    assert 'short documentary' in t.structure_block
    assert '10 sections' not in t.structure_block
    assert ctx.logs[0][2].startswith('Short-doc mode: target 150 words')


def test_pipeline_state_targets_win_over_the_context_default():
    ctx = fake_ctx(
        _sch_duration_targets={'min_words': 1, 'target_words': 1, 'max_words': 1, 'min_word_gate': 1},
        pipeline_state={
            'scholarly_duration_targets': {
                'min_words': 900,
                'target_words': 1000,
                'max_words': 1100,
                'min_word_gate': 800,
            }
        },
    )
    assert P._duration_targets(ctx).max_words == 1100


# ── _build_script_prompt: what the model is actually asked ────────────────────


def targets(**kw):
    """A `Stage03Targets` with a long-form default, overridden by **kw."""
    base = {
        'min_words': 3000,
        'target_words': 4000,
        'max_words': 5000,
        'word_gate': 2500,
        'duration_capped': False,
        'retry_words': 2680,
        'accept_words': 2125,
        'hard_cap_rule': '',
        'structure_block': 'STRUCTURE\n',
    }
    base.update(kw)
    return P.Stage03Targets(**base)


def test_the_prompt_asks_for_the_requested_topic_not_the_essay_title():
    ctx = fake_ctx(directive='Build a documentary about the Sikh Empire', topic='essay topic', essay_text='SOURCE.')
    prompt = LLM._build_script_prompt(ctx, targets(), 'FRAMEWORK\n')
    assert 'documentary about: "Build a documentary about the Sikh Empire"' in prompt
    assert 'documentary of 3000 to 5000 words (target ~4000)' in prompt
    assert prompt.endswith('3000 to 5000 words, then [VISUAL_SCENES] and [YOUTUBE_META].')


def test_the_prompt_closes_the_source_excerpt_and_restates_the_task():
    # 2026-09-20: a prompt that ENDED on the truncated essay made the model
    # continue the essay instead of writing a script.
    ctx = fake_ctx(topic='rivers', essay_text='X' * 9000)
    prompt = LLM._build_script_prompt(ctx, targets(), 'FRAMEWORK\n')
    assert 'ADDITIONAL SOURCE MATERIAL:\n' + 'X' * 6000 in prompt
    assert 'X' * 6001 not in prompt
    assert '[END OF SOURCE MATERIAL' in prompt
    assert prompt.index('[END OF SOURCE MATERIAL') < prompt.index('Now write the documentary narration')


def test_the_prompt_carries_the_wikipedia_block_only_when_one_was_fetched():
    ctx = fake_ctx(topic='rivers', essay_text='SOURCE.')
    assert 'VERIFIED SOURCE MATERIAL — Wikipedia' not in LLM._build_script_prompt(ctx, targets(), 'F\n')
    ctx._wiki_source_block = '[VERIFIED SOURCE MATERIAL — Wikipedia]\nfacts\n[/VERIFIED SOURCE MATERIAL]'
    assert ctx._wiki_source_block in LLM._build_script_prompt(ctx, targets(), 'F\n')


def test_the_prompt_carries_the_hard_cap_and_the_structure_block():
    ctx = fake_ctx(topic='rivers', essay_text='SOURCE.')
    prompt = LLM._build_script_prompt(
        ctx, targets(hard_cap_rule='CAP RULE\n\n', structure_block='SHORT STRUCTURE\n'), 'FRAMEWORK\n'
    )
    assert 'CAP RULE\n\nSHORT STRUCTURE\n\nFRAMEWORK\n' in prompt


# ── _finalise_script_state: what the next stages read ─────────────────────────


def test_finalise_publishes_the_script_the_count_and_the_youtube_meta():
    ctx = fake_ctx(narration_script='word ' * 100, _stage3_llm_model='claude-sonnet-4-6')
    meta = {'title': 'A Title', 'description': 'A description.', 'tags': ['a', 'b'], 'language': '', 'audience': ''}
    P._finalise_script_state(ctx, meta)
    assert ctx.pipeline_state['script'] == ctx.narration_script
    assert ctx.pipeline_state['word_count'] == 100
    assert ctx.pipeline_state['youtube_title'] == 'A Title'
    assert ctx.pipeline_state['youtube_tags'] == ['a', 'b']
    # Empty strings fall back to the defaults the uploader needs.
    assert ctx.pipeline_state['youtube_language'] == 'en'
    assert ctx.pipeline_state['youtube_audience'] == 'general'
    assert ctx.saves == 1


def test_finalise_leaves_youtube_keys_untouched_without_meta():
    ctx = fake_ctx(narration_script='word ' * 100, _stage3_llm_model='bench_replay')
    ctx.pipeline_state['youtube_title'] = 'from the replay'
    P._finalise_script_state(ctx, {})
    assert ctx.pipeline_state['youtube_title'] == 'from the replay'
    assert 'youtube_language' not in ctx.pipeline_state


def test_finalise_truncates_at_ten_thousand_words():
    ctx = fake_ctx(narration_script='word ' * 10500, _stage3_llm_model='claude-sonnet-4-6')
    P._finalise_script_state(ctx, {})
    assert ctx.pipeline_state['word_count'] == 10000
    assert any('> 10000 — truncating' in msg for _l, _s, msg in ctx.logs)


def test_finalise_refuses_a_script_cleaning_emptied():
    ctx = fake_ctx(narration_script='only a few words left', _stage3_llm_model='claude-sonnet-4-6')
    with pytest.raises(RuntimeError, match='narration script empty after cleaning'):
        P._finalise_script_state(ctx, {})
    assert ctx.pipeline_state['word_count'] == 5


# ── _enforce_word_gate: the abort that protects TTS ───────────────────────────


def test_word_gate_passes_a_long_enough_script_without_touching_the_db():
    ctx = fake_ctx(narration_script='word ' * 3000)
    P._enforce_word_gate(ctx, targets())
    assert ctx.logs == []


def test_word_gate_aborts_and_says_how_short_the_script_was():
    ctx = fake_ctx(narration_script='word ' * 10, _selected_essay_id=None)
    with pytest.raises(RuntimeError, match='cleaned narration only 10 words'):
        P._enforce_word_gate(ctx, targets())
    assert 'Story too short (10 words < 2500)' in ctx.logs[0][2]


def test_the_scene_list_the_parser_returns_round_trips_as_json():
    # Stage 3b reads `_stage3_scene_list` back out of the saved pipeline state.
    scenes = ['a frozen river at dawn', 'a commander on the walls of Lahore']
    raw = 'Narration.\n[VISUAL_SCENES]\n' + json.dumps(scenes) + '\n[/VISUAL_SCENES]'
    assert LLM._parse_stage3_resp(raw)[1] == scenes


# ── _reject_disallowed_topic: whole words only ────────────────────────────────


def test_an_anatomy_topic_is_rejected_and_names_the_keyword():
    ctx = fake_ctx(directive='The anatomy of the human knee')
    with pytest.raises(RuntimeError, match='disallowed keyword "anatomy"'):
        P._reject_disallowed_topic(ctx)
    assert 'Anatomy/medical topics are not supported' in ctx.logs[0][2]


def test_uranus_is_not_an_anatomy_topic():
    # 2026-09-23: a substring match on the keyword list rejected "Voyager 2:
    # First Spacecraft to Visit Uranus" because Uranus contains "anus".
    ctx = fake_ctx(directive='Voyager 2: First Spacecraft to Visit Uranus')
    P._reject_disallowed_topic(ctx)
    assert ctx.logs == []


def test_the_topic_is_checked_when_no_directive_was_given():
    ctx = fake_ctx(directive='', topic='vaginal microbiome research')
    with pytest.raises(RuntimeError, match='disallowed keyword "vaginal"'):
        P._reject_disallowed_topic(ctx)


# ── _tidy_narration: the three clean-ups, in order ────────────────────────────


def test_short_doc_narration_is_truncated_to_the_word_ceiling():
    ctx = fake_ctx(narration_script='word ' * 300)
    P._tidy_narration(ctx, targets(duration_capped=True, max_words=180))
    assert len(ctx.narration_script.split()) == 180
    assert 'Short-doc script 300 words > 180 — truncating' in ctx.logs[0][2]


def test_long_form_narration_keeps_every_word():
    ctx = fake_ctx(narration_script='word ' * 300)
    P._tidy_narration(ctx, targets(max_words=180))
    assert len(ctx.narration_script.split()) == 300
    assert ctx.logs == []


def test_markdown_rules_are_stripped_but_the_paragraph_break_survives():
    # IndexTTS-2 vocalised "---" as a syllable per dash and the SRT burned it in.
    ctx = fake_ctx(narration_script='First beat.\n\n---\n\nSecond beat.\n\n***\n\nThird beat.')
    P._tidy_narration(ctx, targets())
    assert ctx.narration_script == 'First beat.\n\nSecond beat.\n\nThird beat.'
    assert 'Removed 2 markdown separator(s)' in ctx.logs[0][2]


def test_a_title_echo_is_stripped_using_the_published_essay_title():
    ctx = fake_ctx(narration_script='The Sikh Empire. For fifty years, it stood.')
    ctx.pipeline_state['essay_title'] = 'The Sikh Empire'
    P._tidy_narration(ctx, targets())
    assert ctx.narration_script == 'For fifty years, it stood.'
    assert 'Removed 1 title-echo sentence(s)' in ctx.logs[0][2]


# ── _apply_bench_replay: the cached script instead of a Claude call ───────────


def test_without_a_replay_record_nothing_is_injected(monkeypatch):
    monkeypatch.setattr(P, '_bench_replay_get', lambda _stage: None)
    ctx = fake_ctx()
    assert P._apply_bench_replay(ctx) is None
    assert ctx.narration_script == ''
    assert ctx._stage3_llm_model is None
    assert ctx.pipeline_state == {}


def test_a_replay_record_supplies_the_script_the_scenes_and_the_youtube_meta(monkeypatch):
    record = {
        'script': 'word ' * 40,
        'scene_list': ['a frozen river'],
        'youtube_title': 'A Replayed Title',
        'youtube_description': 'A replayed description.',
        'youtube_tags': ['rivers'],
    }
    monkeypatch.setattr(P, '_bench_replay_get', lambda stage: record if stage == 'stage_3' else None)
    ctx = fake_ctx()
    assert P._apply_bench_replay(ctx) is record
    assert ctx.narration_script == record['script']
    assert ctx._stage3_llm_model == 'bench_replay'
    assert ctx.pipeline_state['_stage3_scene_list'] == ['a frozen river']
    assert ctx.pipeline_state['youtube_title'] == 'A Replayed Title'
    assert ctx.pipeline_state['youtube_tags'] == ['rivers']
    assert '[bench_replay] script=40w scene_list=1 entries' in ctx.logs[0][2]


def test_a_replay_record_without_youtube_meta_leaves_those_keys_unset(monkeypatch):
    monkeypatch.setattr(P, '_bench_replay_get', lambda _stage: {'script': 'a script'})
    ctx = fake_ctx()
    P._apply_bench_replay(ctx)
    assert ctx.pipeline_state['_stage3_scene_list'] == []
    assert 'youtube_title' not in ctx.pipeline_state
