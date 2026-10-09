# SPDX-FileCopyrightText: 2026 Zygomatic
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Unit tests for the helpers extracted out of `stage_10_flux_image_generation`.

Each one used to be a block in the middle of a 452-line stage function, so these
are the first tests that exercise any of them in isolation. No GPU, no network,
no services: every helper below is a pure function of its arguments or writes
only into the `pipeline_state` dict it is handed.
"""

import types

from zyg_workflows.scholarly.stages_19_36 import flux_image_generation_setup as fs


def _state(**kw):
    """A `pipeline_state` dict with just the keys a test cares about."""
    return dict(kw)


def test_the_negative_prompt_keeps_gore_blocked_below_extreme():
    at_high = fs.build_flux_negative({'rank': 1})
    assert 'gore, ' in at_high
    assert 'mutilated' in at_high
    assert 'amputation' in at_high
    # The nudity block and the figure-quality block are unconditional.
    assert at_high.startswith('nude, nudity, naked, explicit, nsfw')
    assert 'poorly drawn hands' in at_high


def test_the_negative_prompt_relaxes_only_at_extreme():
    at_extreme = fs.build_flux_negative({'rank': 2})
    assert 'gore, ' not in at_extreme
    assert 'mutilated' not in at_extreme
    assert 'amputation' not in at_extreme
    assert at_extreme.endswith('disfigured, malformed')
    # Relaxing the gore block must not touch the nudity block.
    assert 'nsfw' in at_extreme


def test_a_modern_episode_gets_the_documentary_era_suffixes():
    variants = fs.era_variants_for({'is_historical': False, 'anchors': ['ignored']}, 'history', True)
    assert variants is fs.ERA_CONTEXT_DOCUMENTARY


def test_a_historical_episode_prefers_its_own_script_anchors():
    anchors = ['1801 Lahore durbar, Sikh court dress']
    assert fs.era_variants_for({'is_historical': True, 'anchors': anchors}, 'history', False) == anchors


def test_a_historical_episode_without_anchors_falls_back_to_the_topic_table():
    assert fs.era_variants_for({'is_historical': True}, 'war', False) is fs.ERA_CONTEXT['war']
    assert fs.era_variants_for({'is_historical': True, 'anchors': []}, 'general', False) is fs.ERA_CONTEXT_DEFAULT


def test_the_fallback_subject_strips_filler_and_caps_at_six_words():
    assert fs.build_fallback_subject('An Analysis of the Fall of the Roman Empire', 'history') == 'Fall Roman Empire'
    long_title = 'Alpha Beta Gamma Delta Epsilon Zeta Eta Theta'
    assert fs.build_fallback_subject(long_title, 'history') == 'Alpha Beta Gamma Delta Epsilon Zeta'


def test_the_fallback_subject_is_the_topic_when_nothing_survives_the_strip():
    assert fs.build_fallback_subject('A Study of the Research Paper', 'general') == 'general'


def test_narration_is_split_on_sentence_ends_and_short_fragments_are_dropped():
    script = (
        'Too short. This first sentence is comfortably longer than twenty characters. Who knows? '
        'And this closing sentence is also long enough to survive the filter!'
    )
    assert fs.split_narration_sentences(script) == [
        'This first sentence is comfortably longer than twenty characters.',
        'And this closing sentence is also long enough to survive the filter!',
    ]


def test_an_advanced_settings_cap_wins_the_image_count(monkeypatch):
    monkeypatch.setattr(fs, '_smoke_cap', lambda: 0)
    monkeypatch.setattr(fs, '_scholarly_motion', types.SimpleNamespace(enabled=lambda: False))
    state = _state(word_count=2000, tts_duration=300.0, scholarly_duration_targets={'n_flux_images': 8})
    plan = fs.resolve_image_count(state, {}, lambda *a: None)
    assert plan.n_flux_images == 8
    assert plan.est_duration == 300.0
    assert plan.n_images_source == 'Advanced Settings cap (8)'
    assert state['n_flux_images'] == 8
    assert state['n_flux_images_source'] == 'Advanced Settings cap (8)'


def test_the_time_locked_count_wins_when_no_cap_was_set(monkeypatch):
    monkeypatch.setattr(fs, '_smoke_cap', lambda: 0)
    monkeypatch.setattr(
        fs, '_scholarly_motion', types.SimpleNamespace(enabled=lambda: False, clip_target_s=lambda: 8.0)
    )
    monkeypatch.setattr(fs, '_scholarly_n_images', lambda d: 11)
    state = _state(tts_duration=300.0, _tls_n_images=27)
    plan = fs.resolve_image_count(state, {'target_words': 2000}, lambda *a: None)
    assert plan.n_flux_images == 27
    assert plan.n_images_source == 'time-locked scenes from tts_duration (27)'


def test_the_motion_floor_raises_a_cap_that_would_outrun_its_ltx_clip(monkeypatch):
    monkeypatch.setattr(fs, '_smoke_cap', lambda: 0)
    monkeypatch.setattr(fs, '_scholarly_n_images', lambda d: 28)
    monkeypatch.setattr(fs, '_scholarly_motion', types.SimpleNamespace(enabled=lambda: True, clip_target_s=lambda: 8.0))
    said = []
    state = _state(tts_duration=221.8, scholarly_duration_targets={'n_flux_images': 8})
    plan = fs.resolve_image_count(state, {}, lambda lvl, stage, msg: said.append(msg))
    assert plan.n_flux_images == 28
    assert plan.n_images_source.endswith('raised to 28 so no slot outruns its LTX clip')
    assert said and said[0].startswith('Picture count raised 8 → 28:')


def test_the_smoke_cap_is_the_last_word_on_the_image_count(monkeypatch):
    monkeypatch.setattr(fs, '_smoke_cap', lambda: 2)
    monkeypatch.setattr(fs, '_scholarly_motion', types.SimpleNamespace(enabled=lambda: False))
    state = _state(tts_duration=300.0, scholarly_duration_targets={'n_flux_images': 24})
    plan = fs.resolve_image_count(state, {}, lambda *a: None)
    assert plan.n_flux_images == 2
    assert plan.n_images_source == 'smoke cap 2 (would have been 24)'


def test_the_generation_estimate_is_never_zero_or_negative(monkeypatch):
    monkeypatch.setattr(fs, '_load_flux_seconds_per_image_estimate', lambda default, family: 7.5)
    state = _state(flux_seconds_per_image_estimate=0.0)
    plan = fs.ImageCountPlan(word_count_est=2000, est_duration=300.0, n_flux_images=10, n_images_source='test')
    said = []
    fs.log_generation_estimate(state, plan, 'qwen', 'Qwen-Image-2512', lambda lvl, stage, msg: said.append(msg))
    assert state['flux_seconds_per_image_estimate'] == 10.0
    assert said == [
        'Target: 10 images for ~300s narration (count from: test — '
        'est. gen time ~1.7min @ ~10.0s/image on Qwen-Image-2512)'
    ]


def test_a_run_without_a_character_gets_no_bible_and_no_reference():
    state = _state(character_bible='stale')
    fs.prepare_character_bible(state, '', lambda *a: None)
    assert state['character_bible'] is None
    assert 'char_reference_image' not in state


def test_every_arc_style_row_indexes_a_real_style_suffix():
    assert len(fs.STYLE_SUFFIXES) == 20
    for table in (fs.ARC_STYLE_MAP_HISTORICAL, fs.ARC_STYLE_MAP_MODERN):
        assert set(table) == {'exposition', 'rising', 'climax', 'falling', 'resolution', 'hook'}
        for row in table.values():
            assert all(0 <= i < len(fs.STYLE_SUFFIXES) for i in row)


def test_every_prompt_template_takes_the_subject_placeholder():
    for tag, template in fs.FLUX_PROMPT_TEMPLATES.items():
        assert '{subject}' in template, tag
    assert '{subject}' in fs.DEFAULT_FLUX_PROMPT
