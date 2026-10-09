# SPDX-FileCopyrightText: 2026 Zygomatic
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Unit tests for the helpers `stage_15_video_assembly` was split into.

Every one of these was a block — or a closure — inside a 671-line stage
function and had never been exercised on its own. Nothing here touches a GPU,
a network or a service: the camera move, the per-frame geometry, the encoder
command line, the timing grid, the mood resampling, the slot bookkeeping and
the filter graph are all pure enough to call with plain values.
"""

import os

from zyg_workflows.scholarly.stages_19_36 import video_assembly_kenburns as kb
from zyg_workflows.scholarly.stages_19_36 import video_assembly_slides as vs


def _slot(**kw):
    """A `KenBurnsSlot` with sane defaults; keywords override one field at a time."""
    base = {
        'index': 0,
        'img_path': '/nowhere/img.jpg',
        'out_path': '/nowhere/kb_000.mp4',
        'duration': 4.0,
        'fps': 30,
        'shot_type': '',
        'emotion': 'calm',
        'focal_zone': 'center',
    }
    base.update(kw)
    return kb.KenBurnsSlot(**base)


def _recorder():
    """A (calls, log) pair standing in for the stage's `_log` / `_debug`."""
    calls = []

    def log(*args, **kwargs):
        calls.append((args, kwargs))

    return calls, log


# ── kenburns.plan_move ────────────────────────────────────────────────────


def test_shot_type_picks_the_motion_and_emotion_its_speed():
    assert kb.plan_move(_slot(shot_type='extreme close-up')).motion == 'push_in'
    assert kb.plan_move(_slot(shot_type='wide establishing', index=0)).motion == 'pan_r'
    assert kb.plan_move(_slot(shot_type='wide establishing', index=1)).motion == 'pan_l'
    assert kb.plan_move(_slot(shot_type='overhead drone')).motion == 'drift'
    # No shot type: every third slot pulls out instead of pushing in.
    assert kb.plan_move(_slot(shot_type='', index=2)).motion == 'pull_out'
    assert kb.plan_move(_slot(shot_type='', index=3)).motion == 'push_in'

    # 'close' is 0.10 × the emotion speed, and shock moves 1.5 / calm 0.7.
    assert kb.plan_move(_slot(shot_type='close', emotion='shock')).z_delta == 0.10 * 1.5
    assert kb.plan_move(_slot(shot_type='close', emotion='calm')).z_delta == 0.10 * 0.7
    # An unknown emotion falls back to 1.0, not to zero motion.
    assert kb.plan_move(_slot(shot_type='close', emotion='baffled')).z_delta == 0.10


def test_focal_zone_moves_the_anchor_off_centre():
    assert kb.plan_move(_slot(focal_zone='left')).ax == 0.25
    assert kb.plan_move(_slot(focal_zone='right')).ax == 0.75
    assert kb.plan_move(_slot(focal_zone='top')).ay == 0.20
    assert kb.plan_move(_slot(focal_zone='bottom')).ay == 0.80
    # Centre-framed slots rotate through the anchor ring so consecutive
    # pushes never land on the identical point of the frame.
    ring = {kb.plan_move(_slot(index=i)).ax for i in range(len(kb._KB_CENTRE_ANCHORS))}
    assert len(ring) > 1
    assert kb.plan_move(_slot(index=0)).ax == kb.plan_move(_slot(index=len(kb._KB_CENTRE_ANCHORS))).ax
    # z_max is always the zoom the move ends on.
    move = kb.plan_move(_slot(shot_type='close'))
    assert move.z_max == 1.0 + move.z_delta


# ── kenburns.view_at ──────────────────────────────────────────────────────


def _clip(move, **kw):
    """A `KenBurnsClip` with no film look, so `view_at` is pure arithmetic."""
    base = {
        'img': None,
        'dfl': None,
        'slot_idx': 0,
        'move': move,
        'film_plan': None,
        'overlay': None,
        'frames': 11,
        'fps': 30,
        'src_w': 4000,
        'src_h': 2000,
        'affine': None,
        'bicubic': None,
        'out_path': '/nowhere/kb_000.mp4',
        'wait_s': 60,
    }
    base.update(kw)
    return kb.KenBurnsClip(**base)


def test_push_in_shrinks_the_viewport_from_the_full_frame():
    clip = _clip(kb.plan_move(_slot(shot_type='close', emotion='awe')))
    _, tsec0, cx0, cy0, vw0, vh0, roll0 = kb.view_at(clip, 0)
    _, tsecN, _, _, vwN, _, _ = kb.view_at(clip, clip.frames - 1)
    assert tsec0 == 0.0
    assert tsecN == (clip.frames - 1) / 30.0
    assert roll0 == 0.0
    # First frame is zoom 1.0 — the viewport is the whole source.
    assert vw0 == clip.src_w
    assert vh0 == clip.src_h
    # …and it has closed in by z_delta at the end.
    assert vwN < vw0
    assert round(vwN, 6) == round(clip.src_w / (1.0 + clip.move.z_delta), 6)
    # The anchor is clamped back inside the frame on the un-zoomed frame.
    assert cx0 == clip.src_w / 2
    assert cy0 == clip.src_h / 2


def test_pan_right_sweeps_the_viewport_across_the_source():
    clip = _clip(kb.plan_move(_slot(shot_type='wide establishing', index=0)))
    _, _, cx0, _, vw0, _, _ = kb.view_at(clip, 0)
    _, _, cxN, _, _, _, _ = kb.view_at(clip, clip.frames - 1)
    assert cx0 == vw0 / 2
    assert round(cxN, 6) == round(clip.src_w - vw0 / 2, 6)
    # A pan is a fixed zoom: the viewport never changes size.
    assert kb.view_at(clip, 5)[4] == vw0


def test_a_single_frame_clip_does_not_divide_by_zero():
    prog, tsec, _, _, _, _, _ = kb.view_at(_clip(kb.plan_move(_slot(shot_type='close')), frames=1), 0)
    assert (prog, tsec) == (0.0, 0.0)


def test_drift_alternates_direction_by_slot_parity():
    move = kb.plan_move(_slot(shot_type='aerial'))
    assert move.motion == 'drift'
    # An even slot drifts rightwards from the left edge, an odd one leftwards
    # from the right edge; both meet in the middle at the end of the move.
    _, _, even_cx, _, vw, _, _ = kb.view_at(_clip(move, slot_idx=0), 0)
    _, _, odd_cx, _, _, _, _ = kb.view_at(_clip(move, slot_idx=1), 0)
    assert even_cx == vw / 2
    assert round(odd_cx, 6) == round(4000 - vw / 2, 6)
    assert even_cx < odd_cx
    # Fixed zoom, so a drift never changes the viewport size.
    assert kb.view_at(_clip(move, slot_idx=0), 10)[4] == vw


# ── kenburns.encode_commands ──────────────────────────────────────────────


def test_encode_commands_pipe_raw_frames_and_double_the_wait_for_filters():
    slot = _slot(out_path='/tmp/kb_007.mp4', fps=25)
    nvenc, x264, wait = kb.encode_commands(slot, '')
    for cmd in (nvenc, x264):
        assert cmd[-1] == slot.out_path
        assert cmd[1:8] == ['-y', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-s', f'{kb._SLIDE_W}x{kb._SLIDE_H}']
        assert cmd[8:12] == ['-r', '25', '-i', 'pipe:0']
        assert '-vf' not in cmd
    assert 'ultrafast' in x264

    nvenc_fx, x264_fx, wait_fx = kb.encode_commands(slot, 'eq=contrast=1.02')
    assert nvenc_fx[12:14] == ['-vf', 'eq=contrast=1.02']
    assert x264_fx[12:14] == ['-vf', 'eq=contrast=1.02']
    # Filters run on CPU ahead of the encoder, so the pipe gets twice the room.
    assert wait_fx == wait * 2


# ── kenburns.slot_tasks / ordered_clips ───────────────────────────────────


def _plan(n):
    return vs.SlidePlan(
        durations=[float(i + 1) for i in range(n)],
        emotions=['calm'] * n,
        shot_types=['wide'] * n,
    )


def test_a_picture_with_a_motion_clip_gets_no_ken_burns_task():
    paths = ['/i/a.jpg', '/i/b.jpg', '/i/c.jpg']
    tasks, wan = kb.slot_tasks(
        paths,
        _plan(3),
        [{'focal_zone': 'left'}, {}],
        {'/i/b.jpg': '/clips/b.mp4'},
        '/tmp/kbdir',
    )
    assert sorted(tasks) == [0, 2]
    assert wan == {1: '/clips/b.mp4'}
    assert tasks[0].focal_zone == 'left'
    assert tasks[0].out_path == os.path.join('/tmp/kbdir', 'kb_000.mp4')
    assert tasks[0].duration == 1.0
    assert tasks[0].fps == kb._KB_FPS
    # Slot 2 has no metadata entry at all — it falls back to a centred crop.
    assert tasks[2].focal_zone == 'center'
    assert tasks[2].out_path == os.path.join('/tmp/kbdir', 'kb_002.mp4')


def test_a_failed_render_falls_back_to_its_static_image():
    paths = ['/i/a.jpg', '/i/b.jpg', '/i/c.jpg']
    plan = _plan(3)
    tasks, wan = kb.slot_tasks(paths, plan, [], {'/i/c.jpg': '/clips/c.mp4'}, '/tmp/kbdir')
    calls, log = _recorder()
    clips = kb.ordered_clips(3, paths, plan, tasks, wan, {0: True, 1: False}, log)
    assert clips == [
        ('pil', os.path.join('/tmp/kbdir', 'kb_000.mp4'), 1.0),
        ('static', '/i/b.jpg', 2.0),
        ('wan', '/clips/c.mp4', 3.0),
    ]
    assert any('render failed slot 1' in c[0][2] for c in calls)
    assert any('rendered 1/3 clips (1 WAN, 1 static fallback)' in c[0][2] for c in calls)


# ── slides.essay_image_paths ──────────────────────────────────────────────


def test_only_images_still_on_disk_survive_and_the_rest_are_reported(tmp_path):
    here = tmp_path / 'one.jpg'
    here.write_bytes(b'x')
    calls, log = _recorder()
    paths = vs.essay_image_paths(
        [{'path': str(here)}, {'path': str(tmp_path / 'gone.jpg')}, {}],
        log,
    )
    assert paths == [str(here)]
    assert len(calls) == 1
    assert calls[0][0][0] == 'WARNING'
    assert '2 of 3 essay image paths missing' in calls[0][0][2]


def test_nothing_is_logged_when_every_image_is_present(tmp_path):
    here = tmp_path / 'one.jpg'
    here.write_bytes(b'x')
    calls, log = _recorder()
    assert vs.essay_image_paths([{'path': str(here)}], log) == [str(here)]
    assert calls == []


# ── slides.locked_grid_durations ──────────────────────────────────────────


def test_the_time_locked_grid_puts_each_image_in_its_own_audio_window(tmp_path):
    imgs = []
    for i in range(4):
        p = tmp_path / f'{i}.jpg'
        p.write_bytes(b'x')
        imgs.append({'path': str(p), 'index': i})
    calls, log = _recorder()
    durations = vs.locked_grid_durations({'n_flux_images': 4}, [i['path'] for i in imgs], imgs, 120.0, log)
    assert durations == [30.0, 30.0, 30.0, 30.0]
    assert sum(durations) == 120.0
    assert 'Time-locked slideshow: 4 images on uniform 30.0s grid' in calls[0][0][2]


def test_a_missing_slot_folds_into_the_previous_image_window(tmp_path):
    imgs = []
    for i in (0, 2, 3):
        p = tmp_path / f'{i}.jpg'
        p.write_bytes(b'x')
        imgs.append({'path': str(p), 'index': i})
    _, log = _recorder()
    durations = vs.locked_grid_durations({'n_flux_images': 4}, [i['path'] for i in imgs], imgs, 120.0, log)
    # Slot 1 is absent, so slot 0 holds both its own window and slot 1's.
    assert durations == [60.0, 30.0, 30.0]
    assert sum(durations) == 120.0


def test_unusable_slot_indices_hand_the_timing_back_to_the_legacy_planner(tmp_path):
    p = tmp_path / 'a.jpg'
    p.write_bytes(b'x')
    _, log = _recorder()
    # No index at all.
    assert vs.locked_grid_durations({}, [str(p)], [{'path': str(p)}], 60.0, log) is None
    # Out of order.
    two = tmp_path / 'b.jpg'
    two.write_bytes(b'x')
    entries = [{'path': str(p), 'index': 1}, {'path': str(two), 'index': 0}]
    assert vs.locked_grid_durations({'n_flux_images': 2}, [str(p), str(two)], entries, 60.0, log) is None
    # Index past the end of the grid.
    assert vs.locked_grid_durations({'n_flux_images': 1}, [str(p)], [{'path': str(p), 'index': 5}], 60.0, log) is None
    # No images on disk at all.
    assert vs.locked_grid_durations({'n_flux_images': 1}, [], [{'path': '/gone.jpg', 'index': 0}], 60.0, log) is None


# ── slides.slot_moods ─────────────────────────────────────────────────────


def test_the_emotion_curve_is_resampled_onto_the_slot_count():
    state = {
        'emotion_curve': [{'emotion': 'calm'}, {'emotion': 'shock'}],
        'essay_images': [{'shot_type': 'wide'}, {'shot_type': 'close'}, {}],
    }
    emotions, shots = vs.slot_moods(state, 4)
    assert emotions == ['calm', 'calm', 'shock', 'shock']
    assert shots == ['wide', 'close', '', '']


def test_without_an_emotion_curve_every_slot_is_calm():
    emotions, shots = vs.slot_moods({}, 3)
    assert emotions == ['calm', 'calm', 'calm']
    assert shots == ['', '', '']
    assert vs.slot_moods({}, 0) == ([], [])


# ── slides.ffmpeg_input_args ──────────────────────────────────────────────


def test_each_clip_kind_gets_its_own_ffmpeg_input_run():
    args = vs.ffmpeg_input_args(
        [
            ('wan', '/c/a.mp4', 3.5),
            ('pil', '/c/b.mp4', 2.25),
            ('static', '/c/c.jpg', 4.0),
        ]
    )
    assert args == [
        # A motion clip is looped to cover its whole slot…
        '-stream_loop',
        '-1',
        '-t',
        '3.5',
        '-i',
        '/c/a.mp4',
        # …a PIL render already has the duration baked in and is only trimmed…
        '-t',
        '2.250',
        '-i',
        '/c/b.mp4',
        # …and a still is held for the slot.
        '-loop',
        '1',
        '-t',
        '4.0',
        '-i',
        '/c/c.jpg',
    ]
    assert vs.ffmpeg_input_args([]) == []


# ── slides.build_slideshow_filter ─────────────────────────────────────────


def test_the_scale_prefix_labels_every_input_for_the_xfade_graph(monkeypatch):
    calls, debug = _recorder()
    graph, use_xfade = vs.build_slideshow_filter(2, _plan(2), lambda *a, **k: None, debug)
    assert f'[0:v]scale={kb._SLIDE_W}:{kb._SLIDE_H}:flags=lanczos,setsar=1[vs0];' in graph
    assert '[1:v]scale=' in graph
    if use_xfade:
        # murch_engine built a graph: the inputs are relabelled onto [vs*].
        assert '[0:v]' not in graph.split('[vs1];', 1)[1]
    else:
        assert graph.endswith('[vs0][vs1]concat=n=2:v=1:a=0[vout]')


def test_a_failing_transition_engine_falls_back_to_hard_cuts(monkeypatch):
    import sys
    import types

    broken = types.ModuleType('zyg_workflows.murch_engine')

    def _boom(*args, **kwargs):
        raise RuntimeError('no transitions today')

    broken.build_xfade_filter_graph = _boom
    monkeypatch.setitem(sys.modules, 'zyg_workflows.murch_engine', broken)
    import zyg_workflows

    monkeypatch.setattr(zyg_workflows, 'murch_engine', broken, raising=False)

    logs, log = _recorder()
    debugs, debug = _recorder()
    graph, use_xfade = vs.build_slideshow_filter(3, _plan(3), log, debug)
    assert use_xfade is False
    assert graph.endswith('[vs0][vs1][vs2]concat=n=3:v=1:a=0[vout]')
    assert 'xfade build failed' in logs[0][0][2]
    assert debugs[0][1] == {'level': 'ERROR'}


# ── slides.load_motion_clip_map ───────────────────────────────────────────


def test_the_ltx_manifest_only_substitutes_clips_that_exist(tmp_path):
    import json

    from zyg_workflows import scholarly_motion

    clip = tmp_path / 'moving.mp4'
    clip.write_bytes(b'x')
    manifest = tmp_path / scholarly_motion.MANIFEST_REL
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text(
        json.dumps(
            [
                {'source_image': '/i/a.jpg', 'path': str(clip)},
                {'source_image': '/i/b.jpg', 'path': str(tmp_path / 'gone.mp4')},
                {'source_image': '', 'path': str(clip)},
            ]
        )
    )
    calls, log = _recorder()
    assert vs.load_motion_clip_map(str(tmp_path), {'wan_enabled': False}, log) == {'/i/a.jpg': str(clip)}
    assert any('LTX-2.5 clips: substituting 1 moving picture(s)' in c[0][2] for c in calls)


def test_disabling_wan_is_said_out_loud_and_no_manifest_is_read(tmp_path):
    calls, log = _recorder()
    assert vs.load_motion_clip_map(str(tmp_path), {'wan_enabled': False}, log) == {}
    assert calls[0][0][2] == 'WAN substitution disabled for this run'


def test_a_corrupt_manifest_is_a_warning_not_a_crash(tmp_path):
    from zyg_workflows import scholarly_motion

    manifest = tmp_path / scholarly_motion.MANIFEST_REL
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text('{not json')
    calls, log = _recorder()
    assert vs.load_motion_clip_map(str(tmp_path), {'wan_enabled': False}, log) == {}
    assert 'LTX manifest read failed' in calls[0][0][2]


# ── slides.inflate_for_xfade ──────────────────────────────────────────────


def test_the_durations_grow_by_the_overlap_the_transitions_will_eat(monkeypatch):
    import sys
    import types

    fake = types.ModuleType('zyg_workflows.murch_engine')
    fake.build_xfade_filter_graph = lambda durations, emotions, **kw: (
        '',
        [{'transition': 'dissolve', 'duration': 2.0}, {'transition': 'cut', 'duration': 9.0}],
    )
    monkeypatch.setitem(sys.modules, 'zyg_workflows.murch_engine', fake)
    import zyg_workflows

    monkeypatch.setattr(zyg_workflows, 'murch_engine', fake, raising=False)

    calls, debug = _recorder()
    # 2.0s of dissolve on a 100s narration -> ×1.02; the 'cut' row is free.
    assert vs.inflate_for_xfade([50.0, 50.0], ['calm', 'calm'], ['', ''], 100.0, debug) == [51.0, 51.0]
    assert 'Duration inflation: ×1.020' in calls[0][0][1]


def test_an_overlap_under_a_second_is_not_worth_compensating(monkeypatch):
    import sys
    import types

    fake = types.ModuleType('zyg_workflows.murch_engine')
    fake.build_xfade_filter_graph = lambda durations, emotions, **kw: (
        '',
        [{'transition': 'dissolve', 'duration': 0.5}],
    )
    monkeypatch.setitem(sys.modules, 'zyg_workflows.murch_engine', fake)
    import zyg_workflows

    monkeypatch.setattr(zyg_workflows, 'murch_engine', fake, raising=False)

    _, debug = _recorder()
    assert vs.inflate_for_xfade([50.0, 50.0], ['calm', 'calm'], ['', ''], 100.0, debug) == [50.0, 50.0]


# ── the stage still resolves everything it needs ──────────────────────────


def test_the_stage_reads_its_three_env_flags_itself(monkeypatch):
    from zyg_workflows.scholarly.stages_19_36 import video_assembly as va

    monkeypatch.setenv('ZYG_KB_MAX_WORKERS', '3')
    monkeypatch.delenv('ZYG_DOC_FILMLOOK_DUST', raising=False)
    monkeypatch.delenv('ZYG_DOC_FILMLOOK_GRAIN', raising=False)
    env = va._kb_env()
    assert (env.worker_cap, env.dust_on, env.grain_on) == (3, True, False)

    monkeypatch.setenv('ZYG_DOC_FILMLOOK_DUST', 'no')
    monkeypatch.setenv('ZYG_DOC_FILMLOOK_GRAIN', 'temporal')
    env = va._kb_env()
    assert (env.dust_on, env.grain_on) == (False, True)
