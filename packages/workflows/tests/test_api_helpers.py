# SPDX-FileCopyrightText: 2026 Zygomatic
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Unit tests for the helpers wan_video_service.generate() was split into.

Every behaviour asserted here used to live inside the 423-line ``generate`` body or
inside one of its closures, where none of it could be exercised without a GPU, a
diffusers pipeline and a FLUX still on disk.  Only the pure parts are covered: the
candidate choice, the sampler-knob derivation, the negative prompt, the result record
and the manifest write.
"""

import json

import pytest

from zyg_workflows.wan_video_service import api as _api
from zyg_workflows.wan_video_service import api_passes as _ap
from zyg_workflows.wan_video_service.constants import (
    _CLIP_FRAMES,
    _EMOTION_PRIORITY,
    _GUIDANCE,
    _HEIGHT,
    _HUMAN_SUBJECT_KW,
    _INFER_STEPS,
    _WIDTH,
)


def _meta(**kw):
    """One flux_image_meta entry with the keys generate() always reads."""
    entry = {
        'prompt': 'a shot of something',
        'subject': 'something',
        'tag': 't',
        'slot_seconds': 2.0,
        'index': 0,
        'path': '',
        'emotion': 'neutral',
    }
    entry.update(kw)
    return entry


# ── pick_candidates ──────────────────────────────────────────────────────────


def test_candidates_are_ranked_by_emotion_priority_and_capped():
    metas = [
        _meta(index=0, emotion='calm'),
        _meta(index=1, emotion='shock'),
        _meta(index=2, emotion='tension'),
    ]
    picked = _ap.pick_candidates(metas, 2, _EMOTION_PRIORITY)
    assert [c['index'] for c in picked] == [1, 2]


def test_an_unknown_emotion_ranks_lowest_and_ties_keep_input_order():
    metas = [
        _meta(index=0, emotion='brand_new_feeling'),
        _meta(index=1, emotion='anger'),
        _meta(index=2, emotion='awe'),
    ]
    picked = _ap.pick_candidates(metas, 3, _EMOTION_PRIORITY)
    # anger and awe both score 7; the qa_score-descending input order breaks the tie.
    assert [c['index'] for c in picked] == [1, 2, 0]


# ── split_scene_types ────────────────────────────────────────────────────────


def test_pure_action_scenes_go_to_the_t2v_pass_only():
    metas = [
        _meta(index=0, scene_type='dialogue'),
        _meta(index=1, scene_type='PURE_ACTION'),
        _meta(index=2),
    ]
    i2v, t2v = _ap.split_scene_types(metas)
    assert [c['index'] for c in i2v] == [0, 2]
    assert [c['index'] for c in t2v] == [1]


# ── clip_knobs ───────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ('shot_type', 'flow_shift', 'steps'),
    [
        ('extreme close-up', 2.0, 30),
        ('close-up', 2.0, 30),
        ('wide establishing', 3.5, _INFER_STEPS),
        ('aerial', 3.5, _INFER_STEPS),
        ('medium', 2.5, _INFER_STEPS),
        ('', 2.5, _INFER_STEPS),
    ],
)
def test_the_shot_type_decides_flow_shift_and_step_count(shot_type, flow_shift, steps):
    knobs = _ap.clip_knobs(
        _meta(shot_type=shot_type),
        steps_default=_INFER_STEPS,
        guidance_default=_GUIDANCE,
    )
    assert knobs.flow_shift == flow_shift
    assert knobs.steps == steps
    assert knobs.shot_label == (shot_type or 'medium')


@pytest.mark.parametrize('emotion', ['anger', 'triumph', 'tension'])
def test_action_emotions_raise_the_guidance_scale(emotion):
    knobs = _ap.clip_knobs(_meta(emotion=emotion), steps_default=_INFER_STEPS, guidance_default=_GUIDANCE)
    assert knobs.guidance == 7.5


def test_a_quiet_emotion_keeps_the_default_guidance():
    knobs = _ap.clip_knobs(_meta(emotion='calm'), steps_default=_INFER_STEPS, guidance_default=_GUIDANCE)
    assert knobs.guidance == _GUIDANCE


# ── negative_prompt ──────────────────────────────────────────────────────────


def test_a_human_subject_adds_the_anatomy_clause():
    neg = _ap.negative_prompt(_meta(subject='Roman legionnaire'), _HUMAN_SUBJECT_KW, style_block=True)
    assert 'extra fingers' in neg
    assert 'morphing face' in neg


def test_a_non_human_subject_omits_the_anatomy_clause():
    neg = _ap.negative_prompt(
        _meta(subject='storm clouds', prompt='rain over an empty valley'),
        _HUMAN_SUBJECT_KW,
        style_block=True,
    )
    assert 'extra fingers' not in neg
    assert neg.endswith('no movement')


def test_the_t2v_pass_drops_the_2d_art_style_block():
    cand = _meta(subject='a lone archer')
    i2v = _ap.negative_prompt(cand, _HUMAN_SUBJECT_KW, style_block=True)
    t2v = _ap.negative_prompt(cand, _HUMAN_SUBJECT_KW, style_block=False)
    assert 'cel shading' in i2v
    assert 'cel shading' not in t2v
    # Everything else is identical between the two passes.
    assert i2v.replace('cel shading, stylized, 2D art, flat colors, ', '') == t2v


# ── records and the manifest ─────────────────────────────────────────────────


def test_a_clip_record_carries_the_fields_stage_6_reads():
    rec = _ap._clip_record(_meta(index=3, path='/tmp/still.png', subject='a guard'), 3, '/tmp/c.mp4', 'go', 'FRAME')
    assert rec == {
        'path': '/tmp/c.mp4',
        'source_image': '/tmp/still.png',
        'index': 3,
        'slot_seconds': 2.0,
        'subject': 'a guard',
        'prompt': 'go',
        'last_frame': 'FRAME',
    }


def test_the_manifest_drops_the_in_memory_last_frame(tmp_path):
    lines: list = []
    results = [_ap._clip_record(_meta(index=0), 0, '/tmp/a.mp4', 'p', object())]
    _ap.write_manifest(str(tmp_path), results, lines.append)

    written = json.loads((tmp_path / 'wan_manifest.json').read_text())
    assert written == [{k: v for k, v in results[0].items() if k != 'last_frame'}]
    assert 'last_frame' not in written[0]
    assert lines == [f'WAN: 1 clip(s) saved → {tmp_path}']
    # The in-memory record keeps its frame for the next clip in the chain.
    assert 'last_frame' in results[0]


# ── the pass object ──────────────────────────────────────────────────────────


def test_the_pass_carries_the_render_sizes_the_smoke_scripts_patch():
    pass_obj = _api._build_pass('/tmp/wan', 7, print, None, 'noir', None)
    assert (pass_obj.frames, pass_obj.width, pass_obj.height) == (_CLIP_FRAMES, _WIDTH, _HEIGHT)
    assert (pass_obj.steps_default, pass_obj.guidance_default) == (_INFER_STEPS, _GUIDANCE)
    assert pass_obj.chain == 7
    assert pass_obj.visual_style == 'noir'
    # torch is filled in by the orchestrator once a pipeline has loaded.
    assert pass_obj.torch is None
