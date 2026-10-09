# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Unit tests for the stage 6d helpers extracted from `_crime_stage_6d_assembly`.

Every helper here used to be a closure or an inline block of the 520-line stage, so
these are the first tests that exercise the logic in isolation. No ffmpeg, no GPU and
no network: the renderers are replaced by recorders that return a fake clip path.
"""

import pytest

from zyg_workflows.pipeline_crime.stage6_assembly_steps import (
    _AssetPools,
    _build_segment_timeline,
    _loudnorm_filter,
    _remove_quietly,
    _segment_ctx,
    _select_fallback_visual,
    _select_tagged_visual,
    _sentence_start_times,
    _tag_at_time,
    _text_card_vf_parts,
)


class _Renderer:
    """Stand-in for stage 6c's `_img_to_clip`: records its calls, returns a clip path."""

    def __init__(self):
        self.calls = []

    def __call__(self, path, duration, clip_idx, **kwargs):
        self.calls.append((path, duration, clip_idx, kwargs))
        return f'/tmp/_seg_{clip_idx:04d}.mp4'  # noqa: S108  the path is never written


def _ctx(renderer, *, docs=(), imgs=(), persons=None, locations=None, triggers=None, times=()):
    """A `_SegmentCtx` built straight from literals, bypassing ffprobe and the shuffles."""
    ctx = _segment_ctx(
        list(docs),
        renderer,
        lambda *a, **k: None,
        lambda *a, **k: None,
        dict(triggers or {}),
        set(),
        None,
        None,
        dict(persons or {}),
        {'location_images': dict(locations or {})},
        [],
        list(imgs),
    )
    ctx.sentence_times = list(times)
    return ctx


def test_asset_pools_hand_out_each_entry_in_order_then_cycle():
    pools = _AssetPools(doc_pool=['d0', 'd1'], img_pool=['i0'])
    assert [pools.next_doc(), pools.next_doc(), pools.next_doc()] == ['d0', 'd1', 'd0']
    assert [pools.next_img(), pools.next_img()] == ['i0', 'i0']


def test_asset_pools_return_none_when_a_pool_is_empty():
    pools = _AssetPools(doc_pool=[], img_pool=[])
    assert pools.next_doc() is None
    assert pools.next_img() is None
    assert (pools.doc_cursor, pools.img_cursor) == (0, 0)


def test_sentence_start_times_take_the_timestamp_of_each_sentences_first_word():
    word_timings = [('The', 0.0), ('body', 0.4), ('was', 0.9), ('Police', 2.0), ('arrived', 2.6)]
    tags = [
        {'sentence': 'The body was found.', 'type': 'crime_scene', 'subject': 'cellar'},
        {'sentence': 'Police arrived.', 'type': 'event', 'subject': 'arrest'},
    ]
    assert _sentence_start_times(word_timings, tags) == [
        (0.0, 'crime_scene', 'cellar'),
        (2.0, 'event', 'arrest'),
    ]


def test_sentence_start_times_fall_back_to_the_previous_start_and_handle_empty_inputs():
    word_timings = [('The', 1.5), ('verdict', 1.9)]
    tags = [
        {'sentence': 'The verdict came.', 'type': 'court', 'subject': 'trial'},
        {'sentence': 'Nothing matches here.', 'type': 'generic', 'subject': ''},
        {'sentence': '', 'type': 'person', 'subject': 'Smith'},
    ]
    assert _sentence_start_times(word_timings, tags) == [
        (1.5, 'court', 'trial'),
        (1.5, 'generic', ''),
        (0.0, 'person', 'Smith'),
    ]
    assert _sentence_start_times([], tags) == []
    assert _sentence_start_times(word_timings, []) == []


def test_tag_at_time_returns_the_last_sentence_started_before_t():
    times = [(0.0, 'crime_scene', 'cellar'), (5.0, 'person', 'Smith'), (9.0, 'court', 'trial')]
    assert _tag_at_time(times, 0.0) == ('crime_scene', 'cellar')
    assert _tag_at_time(times, 4.9) == ('crime_scene', 'cellar')
    assert _tag_at_time(times, 5.0) == ('person', 'Smith')
    assert _tag_at_time(times, 120.0) == ('court', 'trial')
    assert _tag_at_time([], 3.0) == ('generic', '')


def test_select_tagged_visual_shows_a_person_photo_once_then_a_doc_card(tmp_path):
    photo = tmp_path / 'smith.jpg'
    photo.write_bytes(b'jpg')
    renderer = _Renderer()
    ctx = _ctx(renderer, docs=['doc0'], persons={'John Smith': {'photo': str(photo)}})

    out, dur = _select_tagged_visual(ctx, 'person', 'john smith', 0)
    assert (out, dur) == ('/tmp/_seg_0000.mp4', 8.0)
    assert renderer.calls[0][:3] == (str(photo), 8.0, 0)
    assert renderer.calls[0][3] == {'shot_type': 'close-up'}

    # Once the info box has been shown for that person, the photo is suppressed
    ctx.shown_persons_set.add('John Smith')
    out, dur = _select_tagged_visual(ctx, 'person', 'john smith', 1)
    assert (out, dur) == ('/tmp/_seg_0001.mp4', 8.0)
    assert renderer.calls[1][:3] == ('doc0', 8.0, 1)


def test_select_tagged_visual_prefers_the_matching_location_image():
    renderer = _Renderer()
    ctx = _ctx(renderer, imgs=['img0'], locations={'Berlin': '/loc/berlin.jpg'})

    assert _select_tagged_visual(ctx, 'location', 'berlin suburb', 3) == ('/tmp/_seg_0003.mp4', 7.0)
    assert renderer.calls[-1][:3] == ('/loc/berlin.jpg', 7.0, 3)
    assert renderer.calls[-1][3] == {'shot_type': 'wide establishing shot'}

    assert _select_tagged_visual(ctx, 'location', 'nowhere', 4) == ('/tmp/_seg_0004.mp4', 7.0)
    assert renderer.calls[-1][:3] == ('img0', 7.0, 4)


def test_select_tagged_visual_gives_court_nine_seconds_and_tension_to_events():
    renderer = _Renderer()
    ctx = _ctx(renderer, docs=['doc0'], imgs=['img0'])

    assert _select_tagged_visual(ctx, 'court', 'trial', 0)[1] == 9.0
    assert renderer.calls[-1][:3] == ('doc0', 9.0, 0)

    # seg_idx 1 is not a multiple of three, so an event takes an image, tense
    assert _select_tagged_visual(ctx, 'event', 'arrest', 1) == ('/tmp/_seg_0001.mp4', 8.0)
    assert renderer.calls[-1][3] == {'emotion': 'tension'}

    # An unknown tag selects nothing and renders nothing
    before = len(renderer.calls)
    assert _select_tagged_visual(ctx, 'generic', '', 2) == (None, 0.0)
    assert len(renderer.calls) == before


def test_select_fallback_visual_cycles_doc_then_image_then_image():
    renderer = _Renderer()
    ctx = _ctx(renderer, docs=['doc0'], imgs=['img0'])
    assert [_select_fallback_visual(ctx, phase, phase)[1] for phase in (0, 1, 2, 3)] == [8.0, 7.0, 7.0, 8.0]
    assert [call[0] for call in renderer.calls] == ['doc0', 'img0', 'img0', 'doc0']


def test_select_fallback_visual_renders_nothing_with_empty_pools():
    renderer = _Renderer()
    ctx = _ctx(renderer)
    assert _select_fallback_visual(ctx, 0, 0) == (None, 0.0)
    assert renderer.calls == []


def test_build_segment_timeline_covers_the_narration_and_appends_in_place():
    renderer = _Renderer()
    ctx = _ctx(renderer, docs=['doc0'], imgs=['img0'], times=[(0.0, 'court', 'trial')])
    seg_files = []

    total = _build_segment_timeline(ctx, seg_files, 20.0)

    assert total >= 20.0
    assert len(seg_files) == len(renderer.calls) >= 3
    assert seg_files[0] == '/tmp/_seg_0000.mp4'


def test_build_segment_timeline_injects_one_info_box_per_triggered_person():
    renderer = _Renderer()
    boxes = []

    def _infobox(name, bio, clip_idx, duration=10.0):
        boxes.append((name, bio, clip_idx, duration))
        return f'/tmp/_box_{clip_idx}.mp4'  # noqa: S108  the path is never written

    ctx = _ctx(renderer, docs=['doc0'], persons={'John Smith': {'dob': '1930'}}, triggers={0.0: 'John Smith'})
    ctx.person_infobox_clip = _infobox
    seg_files = []

    _build_segment_timeline(ctx, seg_files, 25.0)

    assert boxes == [('John Smith', {'dob': '1930'}, 0, 10.0)]
    assert seg_files[0] == '/tmp/_box_0.mp4'
    assert 'John Smith' in ctx.shown_persons and 'John Smith' in ctx.shown_persons_set


def test_build_segment_timeline_stops_at_five_hundred_segments():
    renderer = _Renderer()
    ctx = _ctx(renderer, docs=['doc0'])
    seg_files = []
    # 8 s per segment would need far more than 500 iterations to cover a day of audio
    _build_segment_timeline(ctx, seg_files, 86400.0)
    assert len(seg_files) == 500


def test_text_card_vf_parts_escape_the_case_name_and_time_limit_the_title():
    parts = _text_card_vf_parts("O'Brien: The Case")
    assert parts[0] == 'eq=brightness=-0.05'
    assert "text='CRIME CHRONICLES'" in parts[1]
    assert "text='O\\'Brien\\: The Case'" in parts[2]
    assert "enable='lte(t,10)'" in parts[2]
    assert ','.join(parts).count('drawtext') == 2


def test_loudnorm_filter_uses_the_measurements_and_falls_back_per_field():
    measured = {'input_i': '-18.1', 'input_tp': '-2.4', 'input_lra': '7.3', 'input_thresh': '-28.2'}
    out = _loudnorm_filter(measured)
    assert out.startswith('loudnorm=linear=true:I=-14:TP=-1:LRA=11:')
    assert 'measured_I=-18.1:' in out
    assert 'measured_TP=-2.4:' in out
    assert 'measured_LRA=7.3:' in out
    assert 'measured_thresh=-28.2:' in out
    assert out.endswith('offset=0')  # target_offset absent → the documented default
    assert 'measured_I=-14:' in _loudnorm_filter({})


def test_remove_quietly_deletes_what_exists_and_survives_what_cannot_be_removed(tmp_path):
    gone = tmp_path / 'seg.mp4'
    gone.write_bytes(b'x')
    a_dir = tmp_path / 'not-a-file'
    a_dir.mkdir()

    _remove_quietly([str(gone), str(tmp_path / 'never-existed'), str(a_dir)], 'segment file')

    assert not gone.exists()
    assert a_dir.is_dir()  # os.remove raised OSError on the directory and was logged, not raised


def test_segment_ctx_shuffles_the_image_pool_and_reads_the_pipeline_state(monkeypatch):
    import random

    monkeypatch.setattr(random, 'shuffle', lambda seq: seq.reverse())
    ctx = _ctx(_Renderer(), docs=['d0', 'd1'], imgs=['i0', 'i1'], locations={'Berlin': '/loc/b.jpg'})
    assert ctx.pools.doc_pool == ['d0', 'd1']  # doc order is kept
    assert ctx.pools.img_pool == ['i1', 'i0']  # images are shuffled
    assert ctx.location_images == {'Berlin': '/loc/b.jpg'}


def test_stage6d_orchestrator_is_under_the_three_hundred_line_cap():
    import ast
    import inspect

    from zyg_workflows.pipeline_crime import stage6_assembly

    tree = ast.parse(inspect.getsource(stage6_assembly))
    func = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == '_crime_stage_6d_assembly')
    assert func.end_lineno - func.lineno + 1 <= 300


if __name__ == '__main__':
    raise SystemExit(pytest.main([__file__]))
