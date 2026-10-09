# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Unit tests for the steps ``generate_scene`` was split into.

The 399-line per-scene pass could only ever be exercised by a full FLUX run on
a GPU, so none of these decisions had a test: which framing phrase a shot type
earns, what carries over from the previous scene (and where the sanitised public
``extra_prompt`` is injected), which rescue rung fires when strict QC never
passed, whether a failed scene gets a slate or loses its snapshot, and what the
image-meta list Stage 3.6 repairs ends up holding. The steps take a plain
context stand-in, so each is tested on the CPU with no model, no service and no
network."""

import os
import types

import pytest

from zyg_workflows.storyteller import stage_035_scene_loop_steps as steps
from zyg_workflows.storyteller.stage_035_scene_loop_steps import (
    RenderOutcome,
    ScenePrompt,
    animated_package,
    continuity_prefix,
    finalize_scene_file,
    record_failed_scene,
    record_scene_meta,
    rescue_scene,
    reset_ipadapter,
    scene_bible,
    shot_keyword,
    tint_copy,
)


def _ctx(pipeline_state=None, **extra):
    """A context stand-in that collects the log lines the step emits."""
    lines = []
    ctx = types.SimpleNamespace(
        pipeline_state=pipeline_state if pipeline_state is not None else {},
        char_id='',
        job={},
        n_scenes=4,
        scenes=[],
        log_lines=lines,
        _log=lambda level, stage, msg: lines.append((level, stage, msg)),
    )
    for k, v in extra.items():
        setattr(ctx, k, v)
    return ctx


def _sp(img_path):
    """A composed-prompt value object pointing at *img_path*."""
    return ScenePrompt(prompt='a prompt', shot_type='medium', emotion='calm', img_path=img_path)


def _png(path, colour=(1, 2, 3)):
    """Write a tiny real PNG at *path* and return it."""
    from PIL import Image

    Image.new('RGB', (8, 8), colour).save(path)
    return str(path)


# ── shot_keyword ─────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ('shot_type', 'expected'),
    [
        ('medium', 'medium shot, waist up, '),
        ('wide', 'wide establishing shot, full body visible, '),
        ('establishing', 'wide establishing shot, environment prominent, '),
        ('over-the-shoulder', 'over-the-shoulder shot, background visible, '),
    ],
)
def test_shot_keyword_maps_each_known_shot_type(shot_type, expected):
    assert shot_keyword(shot_type) == expected


def test_shot_keyword_close_up_asks_for_head_and_shoulders_not_a_macro_crop():
    # 2026-07-24 r3: 'close-up portrait, face in frame' made FLUX render
    # eyes-and-forehead macro crops that measured near-zero sharpness.
    assert shot_keyword('close-up') == 'head and shoulders close-up portrait, natural camera distance, '


def test_shot_keyword_of_an_unknown_shot_type_adds_nothing():
    assert shot_keyword('dutch-angle') == ''
    assert shot_keyword('') == ''


# ── continuity_prefix ────────────────────────────────────────────────────────


def test_continuity_prefix_of_the_first_scene_has_nothing_to_carry_over():
    assert continuity_prefix([{'character_state': {'hair': 'braided'}}], 0, {}) == ''


def test_continuity_prefix_carries_at_most_two_values_from_the_previous_scene():
    scenes = [
        {'character_state': {'clothing': 'red coat', 'hair': 'braided', 'lighting': 'dusk'}},
        {},
    ]
    assert continuity_prefix(scenes, 1, {}) == 'red coat, braided, '


def test_continuity_prefix_skips_empty_values_and_truncates_at_forty_characters():
    scenes = [{'character_state': {'clothing': None, 'hair': 'x' * 60, 'lighting': 'dusk'}}, {}]
    prefix = continuity_prefix(scenes, 1, {})
    assert prefix == 'x' * 40 + ', '


def test_continuity_prefix_ignores_a_previous_scene_with_no_usable_state():
    assert continuity_prefix([{'character_state': {}}, {}], 1, {}) == ''
    assert continuity_prefix([{'character_state': 'braided'}, {}], 1, {}) == ''


def test_continuity_prefix_injects_the_sanitised_extra_prompt_after_the_continuity():
    # The PUBLIC extra_prompt belongs HERE, not in the prompt tail where it
    # would outweigh the character's own identity clauses.
    scenes = [{'character_state': {'clothing': 'red coat'}}, {}]
    state = {'_st_extra_prompt_clean': 'holding a lantern'}
    assert continuity_prefix(scenes, 1, state) == 'red coat, holding a lantern, '


def test_continuity_prefix_is_the_extra_prompt_alone_on_the_first_scene():
    assert continuity_prefix([{}], 0, {'_st_extra_prompt_clean': 'holding a lantern'}) == 'holding a lantern, '


# ── scene_bible / animated_package ───────────────────────────────────────────


def test_scene_bible_comes_from_the_pipeline_state_when_it_is_there():
    bible = {'trigger_token': 'zygchar'}
    assert scene_bible({'character_bible': bible}, 'abc123') is bible


def test_scene_bible_is_none_without_a_state_dict_or_a_character():
    assert scene_bible(None, '') is None
    assert scene_bible({}, '') is None


def test_animated_package_forces_the_toon_render_style_on_a_copy():
    bible = {'style_profile': {'render_style': 'photoreal', 'palette': 'warm'}}
    pkg = animated_package(bible)
    assert pkg['style_profile']['render_style'] == 'animated'
    assert pkg['style_profile']['palette'] == 'warm'
    # the run's own bible must not be mutated by a per-scene prompt decision
    assert bible['style_profile']['render_style'] == 'photoreal'


def test_animated_package_of_no_bible_is_a_bare_animated_profile():
    assert animated_package(None) == {'style_profile': {'render_style': 'animated'}}


# ── tint_copy ────────────────────────────────────────────────────────────────


def test_tint_copy_writes_a_720p_frame_and_cycles_the_tint(tmp_path):
    from PIL import Image

    src = _png(tmp_path / 'master.png', colour=(120, 120, 120))
    dest = tmp_path / 'scene_003.png'
    tint = tint_copy(src, str(dest), 3)
    assert tint == 0.96  # index 3 of the seven-step cycle
    with Image.open(dest) as img:
        assert img.size == (1280, 720)


def test_tint_copy_gives_consecutive_scenes_different_tints(tmp_path):
    src = _png(tmp_path / 'master.png')
    tints = {tint_copy(src, str(tmp_path / f'scene_{i:03d}.png'), i) for i in range(1, 5)}
    assert len(tints) == 4


# ── rescue_scene ─────────────────────────────────────────────────────────────


def test_rescue_scene_prefers_a_positively_ranked_best_attempt(tmp_path):
    # 2026-07-24: a real render always beats a tinted reference still.
    sp = _sp(str(tmp_path / 'scene_002.png'))
    ctx = _ctx({'_st_scene0_master': _png(tmp_path / 'scene_000.png')})
    outcome = RenderOutcome(best_snap=_png(tmp_path / 'best.png', colour=(9, 9, 9)), best_qc_score=4.2)
    rescue_scene(ctx, types.SimpleNamespace(_st_blender_ds=False), 2, sp, outcome)
    assert outcome.generated is True
    assert ctx.pipeline_state['_st_rescued_scenes'] == [3]
    assert '_st_fallback_scenes' not in ctx.pipeline_state
    assert os.path.isfile(sp.img_path)
    assert ('WARNING', 'Stage 3.5', 'Scene 3: strict QC failed — using best attempt (score=4.2)') in ctx.log_lines


def test_rescue_scene_falls_back_to_the_scene_zero_master(tmp_path):
    sp = _sp(str(tmp_path / 'scene_002.png'))
    ctx = _ctx({'_st_scene0_master': _png(tmp_path / 'scene_000.png')})
    # best_qc_score <= 0 means every attempt read as greybox/dark/unreadable
    outcome = RenderOutcome(best_snap=_png(tmp_path / 'best.png'), best_qc_score=-3.0)
    rescue_scene(ctx, types.SimpleNamespace(_st_blender_ds=False), 2, sp, outcome)
    assert outcome.generated is True
    assert ctx.pipeline_state['_st_fallback_scenes'] == [3]
    assert '_st_rescued_scenes' not in ctx.pipeline_state
    assert 'scene_000 master fallback (tint 1.08)' in ctx.log_lines[0][2]


def test_rescue_scene_never_ships_a_character_portrait_as_a_story_frame(tmp_path):
    # ZYG_ST_PORTRAIT_FRAME_FALLBACK defaults to 0: a resized portrait is not a
    # story frame, and when the reference was a bogus preview it was a portrait
    # of the WRONG PERSON. The scene must fail instead.
    sp = _sp(str(tmp_path / 'scene_002.png'))
    ctx = _ctx({'char_reference_image': _png(tmp_path / 'portrait.png')})
    outcome = RenderOutcome(best_snap=str(tmp_path / 'absent.png'))
    rescue_scene(ctx, types.SimpleNamespace(_st_blender_ds=False), 2, sp, outcome)
    assert outcome.generated is False
    assert '_st_fallback_scenes' not in ctx.pipeline_state
    assert not os.path.exists(sp.img_path)


def test_rescue_scene_uses_the_portrait_only_behind_the_rollback_flag(tmp_path, monkeypatch):
    monkeypatch.setenv('ZYG_ST_PORTRAIT_FRAME_FALLBACK', '1')
    sp = _sp(str(tmp_path / 'scene_002.png'))
    ctx = _ctx({'char_reference_image': _png(tmp_path / 'portrait.png')})
    outcome = RenderOutcome(best_snap=str(tmp_path / 'absent.png'))
    rescue_scene(ctx, types.SimpleNamespace(_st_blender_ds=False), 2, sp, outcome)
    assert outcome.generated is True
    assert ctx.pipeline_state['_st_fallback_scenes'] == [3]
    assert 'ZYG_ST_PORTRAIT_FRAME_FALLBACK=1' in ctx.log_lines[0][2]


def test_rescue_scene_leaves_a_blender_dataset_run_alone(tmp_path, monkeypatch):
    monkeypatch.setenv('ZYG_ST_PORTRAIT_FRAME_FALLBACK', '1')
    sp = _sp(str(tmp_path / 'scene_002.png'))
    ctx = _ctx({'char_reference_image': _png(tmp_path / 'portrait.png')})
    outcome = RenderOutcome(best_snap=str(tmp_path / 'absent.png'))
    rescue_scene(ctx, types.SimpleNamespace(_st_blender_ds=True), 2, sp, outcome)
    assert outcome.generated is False


# ── record_failed_scene ──────────────────────────────────────────────────────


def test_record_failed_scene_counts_the_scene_toward_the_degradation_gate():
    ctx = _ctx()
    record_failed_scene(ctx, 0)
    record_failed_scene(ctx, 4)
    assert ctx.pipeline_state['_st_failed_scenes'] == [1, 5]
    assert [lvl for lvl, _s, _m in ctx.log_lines] == ['ERROR', 'ERROR']
    assert 'no portrait substitution' in ctx.log_lines[0][2]


# ── finalize_scene_file ──────────────────────────────────────────────────────


def test_finalize_scene_file_writes_a_slate_for_a_scene_with_no_frame_at_all(tmp_path, monkeypatch):
    from PIL import Image

    monkeypatch.setattr(steps, 'scene_quality_ok', lambda *_a: False)
    sp = _sp(str(tmp_path / 'scene_001.png'))
    ctx = _ctx()
    finalize_scene_file(ctx, None, 1, sp, RenderOutcome(best_snap=str(tmp_path / 'absent.png')))
    with Image.open(sp.img_path) as img:
        assert img.size == (1280, 720)
        assert img.getpixel((0, 0)) == (10, 10, 15)


def test_finalize_scene_file_removes_the_rejected_snapshot(tmp_path, monkeypatch):
    monkeypatch.setattr(steps, 'scene_quality_ok', lambda *_a: False)
    sp = _sp(_png(tmp_path / 'scene_001.png'))
    snap = _png(tmp_path / 'scene_001.png.best_attempt.png')
    outcome = RenderOutcome(best_snap=snap, generated=True)
    finalize_scene_file(_ctx(), None, 1, sp, outcome)
    assert not os.path.exists(snap)
    assert os.path.isfile(sp.img_path)


def test_finalize_scene_file_locks_scene_zero_as_the_photoreal_master(tmp_path, monkeypatch):
    monkeypatch.setattr(steps, 'scene_quality_ok', lambda *_a: True)
    sp = _sp(_png(tmp_path / 'scene_000.png'))
    ctx = _ctx()
    finalize_scene_file(ctx, None, 0, sp, RenderOutcome(best_snap=str(tmp_path / 'absent.png'), generated=True))
    assert ctx.pipeline_state['_st_scene0_master'] == sp.img_path
    assert 'Scene 0 locked as photoreal master' in ctx.log_lines[0][2]


def test_finalize_scene_file_does_not_lock_a_scene_zero_that_failed_qc(tmp_path, monkeypatch):
    monkeypatch.setattr(steps, 'scene_quality_ok', lambda *_a: False)
    sp = _sp(_png(tmp_path / 'scene_000.png'))
    ctx = _ctx()
    finalize_scene_file(ctx, None, 0, sp, RenderOutcome(best_snap=str(tmp_path / 'absent.png'), generated=True))
    assert '_st_scene0_master' not in ctx.pipeline_state


# ── reset_ipadapter ──────────────────────────────────────────────────────────


def test_reset_ipadapter_does_nothing_when_nothing_was_conditioned():
    calls = []
    svc = types.SimpleNamespace(reset_conditioning=lambda pipe: calls.append(pipe))
    reset_ipadapter(_ctx(), types.SimpleNamespace(_ipa_svc_st=svc), False)
    assert calls == []


def test_reset_ipadapter_reports_a_broken_service_instead_of_failing_silently(monkeypatch):
    from zyg_workflows import gui_state

    monkeypatch.setattr(gui_state, '_FLUX_DEV_PIPELINE_CACHE', object(), raising=False)

    def _broken(_pipe):
        raise AttributeError('no reset_conditioning')

    ctx = _ctx()
    reset_ipadapter(ctx, types.SimpleNamespace(_ipa_svc_st=types.SimpleNamespace(reset_conditioning=_broken)), True)
    assert ctx.log_lines[0][0] == 'WARNING'
    assert 'reset_conditioning failed' in ctx.log_lines[0][2]


# ── record_scene_meta ────────────────────────────────────────────────────────


def test_record_scene_meta_scores_the_delivered_file_and_advances_progress():
    ctx = _ctx()
    st = types.SimpleNamespace(
        img_paths=[],
        _st_image_meta=[],
        _hand_qa_fn=lambda path: (0.87654, ['one hand occluded']),
    )
    sp = _sp('/out/scene_001.png')
    record_scene_meta(ctx, st, 1, {'description': 'd' * 100}, sp)
    assert st.img_paths == ['/out/scene_001.png']
    assert st._st_image_meta == [
        {
            'path': '/out/scene_001.png',
            'index': 1,
            'prompt': 'a prompt',
            'qa_score': 0.877,
            'qa_issues': ['one hand occluded'],
            'subject': 'd' * 60,
        }
    ]
    assert ctx.job['progress_pct'] == 45  # 30 + (2/4)*30


def test_record_scene_meta_keeps_an_unknown_score_unknown():
    # r4: 0.0 is a real score; None means QC could not judge the frame, and the
    # 0.0 sentinel used to send fallback frames into Stage 3.6 repair.
    ctx = _ctx()
    st = types.SimpleNamespace(img_paths=[], _st_image_meta=[], _hand_qa_fn=lambda path: (None, []))
    record_scene_meta(ctx, st, 3, {}, _sp('/out/scene_003.png'))
    assert st._st_image_meta[0]['qa_score'] is None
    assert st._st_image_meta[0]['subject'] == ''
    assert ctx.job['progress_pct'] == 60
