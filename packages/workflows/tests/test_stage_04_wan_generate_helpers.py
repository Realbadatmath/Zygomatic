# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Unit tests for the helpers extracted from `generate_wan_clips`.

The 622-line original could only ever be exercised by a full GPU run, so none of
this logic had a test. Every helper here is driven with plain values, fake
services and tmp files: no GPU, no network, no local service.
"""

from __future__ import annotations

import os
import sys
import types
from pathlib import Path

import pytest
import zyg_workflows
from zyg_workflows.video_stages import stage_04_wan_generate_polish as polish
from zyg_workflows.video_stages import stage_04_wan_generate_steps as steps


class RecordingLog:
    """Stand-in for `ctx._log`: keeps every (level, stage, message) triple."""

    def __init__(self):
        self.lines = []

    def __call__(self, level, stage, message):
        self.lines.append((level, stage, message))

    def levels(self):
        return [level for level, _stage, _msg in self.lines]

    def messages(self):
        return [msg for _level, _stage, msg in self.lines]


def make_run(log=None, **over):
    """A `WanClipRun` whose every field is a harmless default, overridable."""
    fields = {
        'log': log if log is not None else RecordingLog(),
        'set_stage': lambda name: None,
        'complete_stage': lambda name: None,
        'sp_video': None,
        'vscfg': {},
        'images_dir': '/nonexistent/images',
        'job': {},
        'n_scenes': 0,
        'out_dir': '/nonexistent/out',
        'scene_images': [],
        'scenes': [],
        'visual_style': 'cinematic',
        'wan_svc': None,
        'wan_n_chained': 0,
        'wan_test_frames': None,
        'wan_test_steps': None,
    }
    fields.update(over)
    return steps.WanClipRun(**fields)


# ── detect_emotion ───────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ('desc', 'expected'),
    [
        ('Two armies clash on the plain', 'anger'),
        ('The king stands victorious on the wall', 'triumph'),
        ('A sweeping landscape at dawn', 'awe'),
        ('Grief over the fallen soldiers', 'grief'),
        ('A tense standoff in the courtyard', 'tension'),
        ('A man walks through a doorway', 'neutral'),
        ('', 'neutral'),
    ],
)
def test_detect_emotion_maps_keywords_to_tags(desc, expected):
    assert steps.detect_emotion(desc) == expected


def test_detect_emotion_is_case_insensitive_and_ordered():
    # 'battle' (anger) wins over 'triumph' because anger is tested first.
    assert steps.detect_emotion('TRIUMPH AFTER THE BATTLE') == 'anger'


# ── build_wan_meta ───────────────────────────────────────────────────────────


def test_build_wan_meta_adds_photorealism_and_keeps_claudes_prompt():
    scenes = [
        {'description': 'a wolf howls', 'wan_prompt': 'slow push in on the wolf'},
        {'description': 'the pack runs', 'wan_prompt': 'tracking shot, photorealistic'},
    ]
    meta = steps.build_wan_meta(scenes, ['/img/0.png', '/img/1.png'], 5.0)

    assert [m['index'] for m in meta] == [0, 1]
    assert meta[0]['wan_prompt'] == (
        'slow push in on the wolf. Photorealistic, not animated, not cartoon, '
        'not illustrated, wildlife photography quality.'
    )
    # A prompt that already says photorealistic is used verbatim.
    assert meta[1]['wan_prompt'] == 'tracking shot, photorealistic'
    assert [m['path'] for m in meta] == ['/img/0.png', '/img/1.png']
    assert [m['slot_seconds'] for m in meta] == [0.0, 5.0]


def test_build_wan_meta_defaults_shot_type_and_missing_still():
    scenes = [{'description': 'd0'}, {'description': 'd1'}, {'description': 'd2'}, {'description': 'd3'}]
    meta = steps.build_wan_meta(scenes, ['/img/0.png'], 2.0)

    # Every third scene is wide, the rest medium; a scene past the stills is pathless.
    assert [m['shot_type'] for m in meta] == [
        'wide cinematic shot',
        'medium shot',
        'medium shot',
        'wide cinematic shot',
    ]
    assert [m['path'] for m in meta] == ['/img/0.png', '', '', '']
    assert all(m['camera_motion'] == '' and m['tag'] == 'neutral' for m in meta)
    assert all(0 <= m['seed'] < 2**32 for m in meta)


def test_build_wan_meta_falls_back_to_a_synthetic_description():
    meta = steps.build_wan_meta([{}], [], 1.0)
    assert meta[0]['prompt'] == 'cinematic scene 0'
    assert meta[0]['subject'] == 'cinematic scene 0'
    assert meta[0]['scene_type'] == ''


# ── the blank-FLUX guard ─────────────────────────────────────────────────────


def _still(tmp_path, name, size):
    path = tmp_path / name
    path.write_bytes(b'\0' * size)
    return str(path)


def test_blank_flux_images_only_counts_small_existing_files(tmp_path):
    good = _still(tmp_path, 'good.png', steps.BLANK_THRESH + 1)
    bad = _still(tmp_path, 'bad.png', 8 * 1024)
    meta = [{'path': good}, {'path': bad}, {'path': '/nonexistent/x.png'}, {'path': ''}]

    assert steps.blank_flux_images(meta) == [bad]


def test_guard_aborts_wan_when_every_still_is_blank(tmp_path):
    log = RecordingLog()
    meta = [{'path': _still(tmp_path, f'{i}.png', 8 * 1024)} for i in range(3)]

    assert steps.apply_blank_image_guard(meta, log) is True
    assert log.levels() == ['ERROR']
    assert 'All 3/3 FLUX images are blank/OOM fallbacks' in log.messages()[0]


def test_guard_only_warns_when_some_stills_are_blank(tmp_path):
    log = RecordingLog()
    meta = [
        {'path': _still(tmp_path, 'ok.png', steps.BLANK_THRESH + 1)},
        {'path': _still(tmp_path, 'blank.png', 8 * 1024)},
    ]

    assert steps.apply_blank_image_guard(meta, log) is False
    assert log.levels() == ['WARNING']
    assert '1/2 FLUX images appear blank' in log.messages()[0]


def test_guard_is_silent_when_no_still_is_blank(tmp_path):
    log = RecordingLog()
    meta = [{'path': _still(tmp_path, 'ok.png', steps.BLANK_THRESH)}]

    assert steps.apply_blank_image_guard(meta, log) is False
    assert log.lines == []


# ── make_wan_log / note_wan_unavailable ──────────────────────────────────────


def test_make_wan_log_raises_failure_keywords_to_warning():
    log = RecordingLog()
    wan_log = steps.make_wan_log(log)

    wan_log('Rendering clip 1/4')
    wan_log('CUDA out of memory while decoding')
    wan_log('Traceback (most recent call last)')

    assert log.levels() == ['INFO', 'WARNING', 'WARNING']
    assert {stage for _l, stage, _m in log.lines} == {'Stage 4'}


def test_note_wan_unavailable_warns_the_job_exactly_once():
    log, job = RecordingLog(), {}

    steps.note_wan_unavailable(log, job)
    steps.note_wan_unavailable(log, job)

    assert job['wan_fallback'] is True
    assert len(job['warnings']) == 1
    assert 'WAN video generation skipped' in job['warnings'][0]
    assert log.levels() == ['WARNING', 'WARNING']


# ── build_chain_prompt ───────────────────────────────────────────────────────


def test_build_chain_prompt_wraps_the_scene_in_the_style_config():
    run = make_run(
        vscfg={'prefix': 'oil painting', 'suffix': 'warm light'},
        scenes=[{'flux_prompt': 'a lighthouse'}],
    )
    assert steps.build_chain_prompt(run, 0) == 'oil painting, a lighthouse, warm light'


def test_build_chain_prompt_falls_back_through_description_then_style():
    run = make_run(scenes=[{'description': 'a harbour'}], visual_style='noir')

    assert steps.build_chain_prompt(run, 0) == (
        'cinematic photograph, a harbour, photorealistic, dramatic lighting, 16:9 composition, film grain'
    )
    # Scene 7 does not exist: the style-and-index fallback is used.
    assert 'noir scene 7' in steps.build_chain_prompt(run, 7)


# ── animate_scenes_chained / animate_scenes_batched ──────────────────────────


class FakeWanService:
    """`wan_video_service` stand-in: returns one result dict per meta entry."""

    def __init__(self, fail_on=()):
        self.calls = []
        self.fail_on = set(fail_on)

    def generate(self, meta, out_dir, **kw):
        self.calls.append((meta, out_dir, kw))
        results = []
        for m in meta:
            if m['index'] in self.fail_on:
                raise RuntimeError(f'wan blew up on {m["index"]}')
            results.append({'index': m['index'], 'path': f'/clips/{m["index"]}.mp4', 'last_frame': None})
        return results


def test_animate_scenes_chained_animates_one_scene_at_a_time():
    svc = FakeWanService()
    log = RecordingLog()
    run = make_run(log=log, n_scenes=2, wan_svc=svc, scene_images=['/img/0.png', '/img/1.png'], wan_n_chained=3)
    meta = [{'index': 0, 'path': ''}, {'index': 1, 'path': ''}]
    wan_by_idx = {}

    results = steps.animate_scenes_chained(run, meta, lambda m: None, wan_by_idx)

    assert [r['index'] for r in results] == [0, 1]
    assert wan_by_idx == {0: '/clips/0.mp4', 1: '/clips/1.mp4'}
    # Step B rewrote each meta path from the (possibly chained) still.
    assert [m['path'] for m in meta] == ['/img/0.png', '/img/1.png']
    assert [len(call[0]) for call in svc.calls] == [1, 1]
    assert svc.calls[0][2]['n_chained'] == 3
    assert 'WAN chained complete: 2/2 clips generated' in log.messages()[-1]


def test_animate_scenes_chained_survives_one_failed_clip():
    svc = FakeWanService(fail_on=(0,))
    log = RecordingLog()
    run = make_run(log=log, n_scenes=2, wan_svc=svc, scene_images=['/img/0.png', '/img/1.png'])
    wan_by_idx = {}

    results = steps.animate_scenes_chained(run, [{'index': 0}, {'index': 1}], lambda m: None, wan_by_idx)

    assert [r['index'] for r in results] == [1]
    assert wan_by_idx == {1: '/clips/1.mp4'}
    assert 'WAN chained clip 0 failed: wan blew up on 0' in log.messages()
    assert 'WARNING' in log.levels()


def test_animate_scenes_batched_makes_one_call_for_every_scene():
    svc = FakeWanService()
    log = RecordingLog()
    run = make_run(log=log, n_scenes=2, wan_svc=svc, out_dir='/out', visual_style='noir')
    meta = [{'index': 0}, {'index': 1}]

    results = steps.animate_scenes_batched(run, meta, lambda m: None)

    assert [r['path'] for r in results] == ['/clips/0.mp4', '/clips/1.mp4']
    (sent_meta, out_dir, kw) = svc.calls[0]
    assert sent_meta is meta and out_dir == '/out'
    assert kw['n_clips'] == 2 and kw['visual_style'] == 'noir'
    assert log.messages() == ['WAN generated 2/2 clips']


# ── the prop-persistence sweep ───────────────────────────────────────────────


class FakeSam3:
    """`sam3_service` stand-in for the prop sweep."""

    def __init__(self, report=None, boom=False):
        self.report = report
        self.boom = boom

    def prop_persistence(self, clip, props, log_fn=None):
        if self.boom:
            raise RuntimeError('sam3 worker died')
        return self.report


def test_record_prop_verdict_measures_presence_per_prop():
    log = RecordingLog()
    run = make_run(log=log, scenes=[{'props': ['sword', 'shield']}])
    sam3 = FakeSam3({'sword': {'presence_frac': 0.9, 'persistent': True}, '_frames': 48})
    state = {}

    polish.record_prop_verdict(run, sam3, state, {'index': 0, 'path': '/clips/0.mp4'})

    assert state[0]['status'] == 'measured'
    assert state[0]['verdicts'] == {'sword': {'presence_frac': 0.9, 'persistent': True}}
    assert 'all persistent' in log.messages()[0]


def test_record_prop_verdict_reports_a_prop_that_drops_out():
    log = RecordingLog()
    run = make_run(log=log, scenes=[{'props': ['lantern']}])
    sam3 = FakeSam3({'lantern': {'presence_frac': 0.2, 'persistent': False}})
    state = {}

    polish.record_prop_verdict(run, sam3, state, {'index': 0, 'path': '/clips/0.mp4'})

    assert state[0]['verdicts']['lantern']['persistent'] is False
    assert 'NOT persistent: lantern' in log.messages()[0]


def test_record_prop_verdict_is_unverified_when_sam3_fails():
    log = RecordingLog()
    run = make_run(log=log, scenes=[{'props': ['crown']}])
    state = {}

    polish.record_prop_verdict(run, FakeSam3(boom=True), state, {'index': 0, 'path': ''})

    assert state[0] == {'status': 'unverified', 'props': ['crown']}
    assert 'prop_persistence failed for scene 1' in log.messages()[0]
    assert 'no clip): unverified' in log.messages()[1]


@pytest.mark.parametrize(
    'result',
    [
        {'index': 'nope', 'path': '/clips/x.mp4'},  # unparseable index
        {'index': 9, 'path': '/clips/x.mp4'},  # index past the scene list
        {'index': 1, 'path': '/clips/x.mp4'},  # a scene with no props
    ],
)
def test_record_prop_verdict_skips_results_it_cannot_place(result):
    run = make_run(scenes=[{'props': ['sword']}, {'props': []}])
    state = {}

    polish.record_prop_verdict(run, FakeSam3({}), state, result)

    assert state == {}


def test_sweep_prop_persistence_is_skipped_when_the_gate_is_off(monkeypatch):
    monkeypatch.setenv('ZYG_PROP_GATE', '0')
    log = RecordingLog()
    run = make_run(log=log, scenes=[{'props': ['sword']}], job={})

    polish.sweep_prop_persistence(run, [{'index': 0, 'path': '/clips/0.mp4'}])

    assert log.messages() == ['Prop-persistence gate disabled (ZYG_PROP_GATE=0) — sweep skipped']
    assert '_prop_persistence' not in run.job


def _install_fake_sam3(monkeypatch, module):
    """Make `from zyg_workflows import sam3_service` resolve to `module`."""
    monkeypatch.setitem(sys.modules, 'zyg_workflows.sam3_service', module)
    monkeypatch.setattr(zyg_workflows, 'sam3_service', module, raising=False)


def test_sweep_prop_persistence_records_unverified_without_sam3(monkeypatch):
    monkeypatch.setenv('ZYG_PROP_GATE', '1')
    fake = types.ModuleType('zyg_workflows.sam3_service')
    fake.available = lambda: (False, 'checkpoint missing')
    _install_fake_sam3(monkeypatch, fake)
    log = RecordingLog()
    run = make_run(log=log, scenes=[{'props': ['sword', 'shield']}], job={})

    polish.sweep_prop_persistence(run, [{'index': 0, 'path': '/clips/0.mp4'}])

    assert run.job['_prop_persistence'][0] == {'status': 'unverified', 'props': ['sword', 'shield']}
    assert 'SAM3 unavailable (checkpoint missing)' in log.messages()[0]


def test_sweep_prop_persistence_measures_every_result_when_sam3_is_ready(monkeypatch):
    monkeypatch.setenv('ZYG_PROP_GATE', '1')
    fake = types.ModuleType('zyg_workflows.sam3_service')
    fake.available = lambda: (True, 'ok')
    fake.prop_persistence = lambda clip, props, log_fn=None: {
        p: {'presence_frac': 1.0, 'persistent': True} for p in props
    }
    _install_fake_sam3(monkeypatch, fake)
    run = make_run(scenes=[{'props': ['sword']}, {'props': ['shield']}], job={})

    polish.sweep_prop_persistence(
        run,
        [{'index': 0, 'path': '/clips/0.mp4'}, {'index': 1, 'path': '/clips/1.mp4'}],
    )

    state = run.job['_prop_persistence']
    assert sorted(state) == [0, 1]
    assert state[0]['verdicts']['sword']['persistent'] is True
    assert state[1]['verdicts']['shield']['persistent'] is True


def test_sweep_prop_persistence_does_nothing_without_prop_scenes(monkeypatch):
    monkeypatch.setenv('ZYG_PROP_GATE', '1')
    run = make_run(scenes=[{'description': 'no props here'}], job={})

    polish.sweep_prop_persistence(run, [{'index': 0, 'path': '/clips/0.mp4'}])

    assert run.job == {}


# ── stage 4b / 4c: a missing service is never fatal ──────────────────────────


def _stage_recorder():
    """(stages list, set_stage, complete_stage) that log their calls in order."""
    stages = []
    return stages, stages.append, lambda name: stages.append(f'done:{name}')


def test_run_object_tracking_survives_a_missing_service(monkeypatch):
    monkeypatch.setitem(sys.modules, 'zyg_workflows.object_track_service', None)
    log = RecordingLog()
    stages, set_stage, complete_stage = _stage_recorder()
    run = make_run(log=log, set_stage=set_stage, complete_stage=complete_stage)
    results = [{'index': 0, 'path': '/clips/0.mp4'}]

    after = polish.run_object_tracking(run, results, [], {0: '/clips/0.mp4'})

    assert stages == ['Object Tracking', 'done:Object Tracking']
    assert after == {0: '/clips/0.mp4'}  # the index survives the skip
    assert results == [{'index': 0, 'path': '/clips/0.mp4'}]  # clips untouched
    assert log.levels() == ['WARNING']
    assert 'object_track_service unavailable' in log.messages()[0]


def test_run_object_tracking_rebuilds_the_index_from_the_service(monkeypatch):
    fake = types.ModuleType('zyg_workflows.object_track_service')
    fake.process_clips = lambda res, meta, out_dir, log_fn=None: [
        {'index': 0, 'path': '/clips/0_tracked.mp4', 'tracked': True}
    ]
    monkeypatch.setitem(sys.modules, 'zyg_workflows.object_track_service', fake)
    monkeypatch.setattr(zyg_workflows, 'object_track_service', fake, raising=False)
    log = RecordingLog()
    run = make_run(log=log)
    results = [{'index': 0, 'path': '/clips/0.mp4'}]

    after = polish.run_object_tracking(run, results, [], {0: '/clips/0.mp4'})

    assert after == {0: '/clips/0_tracked.mp4'}
    assert results[0]['tracked'] is True  # replaced in place
    assert log.messages() == ['Object tracking: 1/1 clip(s) processed']


def test_run_temporal_repair_survives_a_missing_service(monkeypatch):
    monkeypatch.setitem(sys.modules, 'zyg_workflows.rife_service', None)
    log = RecordingLog()
    stages, set_stage, complete_stage = _stage_recorder()
    run = make_run(log=log, set_stage=set_stage, complete_stage=complete_stage)

    after = polish.run_temporal_repair(run, [{'index': 0, 'path': '/clips/0.mp4'}], {0: '/clips/0.mp4'})

    assert stages == ['Temporal Repair', 'done:Temporal Repair']
    assert after == {0: '/clips/0.mp4'}
    assert 'rife_service unavailable' in log.messages()[0]


def test_run_temporal_repair_counts_only_interpolated_clips(monkeypatch):
    fake = types.ModuleType('zyg_workflows.rife_service')
    fake.interpolate_clips = lambda res, out_dir, log_fn=None: [
        {'index': 0, 'path': '/clips/0_rife.mp4', 'rife_pass': 'done'},
        {'index': 1, 'path': '/clips/1.mp4', 'rife_pass': 'skipped'},
    ]
    monkeypatch.setitem(sys.modules, 'zyg_workflows.rife_service', fake)
    monkeypatch.setattr(zyg_workflows, 'rife_service', fake, raising=False)
    log = RecordingLog()
    run = make_run(log=log)
    results = [{'index': 0, 'path': '/clips/0.mp4'}, {'index': 1, 'path': '/clips/1.mp4'}]

    after = polish.run_temporal_repair(run, results, {})

    assert after == {0: '/clips/0_rife.mp4', 1: '/clips/1.mp4'}
    assert log.messages() == ['Temporal repair: 1/2 clip(s) interpolated']


# ── stage 4d: the ESRGAN per-clip pass ───────────────────────────────────────


class FakeProc:
    """Minimal `subprocess.CompletedProcess` stand-in."""

    def __init__(self, returncode):
        self.returncode = returncode


class FakeSpVideo:
    """`_sp_video` stand-in: records argv and hands back a canned returncode."""

    def __init__(self, returncode=0):
        self.returncode = returncode
        self.argv = []

    def run(self, args, **kw):
        self.argv.append(args)
        return FakeProc(self.returncode)


def test_extract_clip_frames_raises_when_ffmpeg_fails(tmp_path):
    run = make_run(sp_video=FakeSpVideo(returncode=1))

    with pytest.raises(RuntimeError, match='frame extraction failed'):
        polish.extract_clip_frames(run, '/clips/0.mp4', str(tmp_path))


def test_extract_clip_frames_asks_ffmpeg_for_a_numbered_png_sequence(tmp_path):
    sp = FakeSpVideo(returncode=0)
    run = make_run(sp_video=sp)

    polish.extract_clip_frames(run, '/clips/0.mp4', str(tmp_path))

    argv = sp.argv[0]
    assert argv[1:4] == ['-y', '-i', '/clips/0.mp4']
    assert argv[-1] == os.path.join(str(tmp_path), 'frame_%05d.png')


def test_reencode_frames_builds_the_x264_command(tmp_path):
    sp = FakeSpVideo(returncode=0)
    run = make_run(sp_video=sp)

    proc = polish.reencode_frames(run, str(tmp_path), '/clips/0.mp4_esr.mp4')

    assert proc.returncode == 0
    argv = sp.argv[0]
    assert '-framerate' in argv and argv[argv.index('-framerate') + 1] == '24'
    assert argv[argv.index('-c:v') + 1] == 'libx264'
    assert argv[argv.index('-crf') + 1] == '17'
    assert argv[-1] == '/clips/0.mp4_esr.mp4'


def test_enhance_frames_writes_one_1080p_png_per_extracted_frame(tmp_path, monkeypatch):
    cv2 = pytest.importorskip('cv2')
    frames_dir, out_dir = tmp_path / 'in', tmp_path / 'out'
    frames_dir.mkdir()
    out_dir.mkdir()
    np = pytest.importorskip('numpy')
    for i in range(2):
        cv2.imwrite(str(frames_dir / f'frame_{i:05d}.png'), np.zeros((48, 83, 3), dtype=np.uint8))
    # Fake upscaler: ESRGAN's contract is (image, scale) -> (bigger image, mode)
    upscaler = types.SimpleNamespace(enhance=lambda img, outscale=4: (cv2.resize(img, (332, 192)), None))

    written = polish.enhance_frames(upscaler, str(frames_dir), str(out_dir))

    assert written == 2
    produced = sorted(p.name for p in out_dir.iterdir())
    assert produced == ['frame_00000.png', 'frame_00001.png']
    assert cv2.imread(str(out_dir / 'frame_00000.png')).shape == (1080, 1920, 3)


def test_upscale_one_clip_cleans_up_and_reports_failure(tmp_path):
    clip = tmp_path / 'clip.mp4'
    clip.write_bytes(b'original')
    log = RecordingLog()
    run = make_run(log=log, sp_video=FakeSpVideo(returncode=1))

    assert polish.upscale_one_clip(run, None, str(clip)) is False
    assert clip.read_bytes() == b'original'  # never replaced on failure
    assert not os.path.exists(str(clip) + '_esr_frames')
    assert not os.path.exists(str(clip) + '_esr_out')
    assert log.levels() == ['WARNING']
    assert 'ESRGAN failed for clip clip.mp4: frame extraction failed' in log.messages()[0]


def test_upscale_one_clip_replaces_the_clip_on_success(tmp_path, monkeypatch):
    clip = tmp_path / 'clip.mp4'
    clip.write_bytes(b'original')
    log = RecordingLog()
    run = make_run(log=log, sp_video=FakeSpVideo(returncode=0))

    def fake_reencode(run_, frames_dir, dest):
        Path(dest).write_bytes(b'x' * 2000)
        return FakeProc(0)

    monkeypatch.setattr(polish, 'extract_clip_frames', lambda run_, wclip, d: None)
    monkeypatch.setattr(polish, 'enhance_frames', lambda up, src, dst: 0)
    monkeypatch.setattr(polish, 'reencode_frames', fake_reencode)

    assert polish.upscale_one_clip(run, None, str(clip)) is True
    assert clip.read_bytes() == b'x' * 2000
    assert log.lines == []


def test_run_esrgan_upscale_skips_when_the_model_is_absent(monkeypatch):
    monkeypatch.setattr(polish.paths, 'ZYG_REALESRGAN_ROOT', Path('/nonexistent/esrgan'))
    log = RecordingLog()
    stages, set_stage, complete_stage = _stage_recorder()
    run = make_run(log=log, set_stage=set_stage, complete_stage=complete_stage)

    after = polish.run_esrgan_upscale(run, [{'index': 0, 'path': '/clips/0.mp4'}], {0: '/clips/0.mp4'})

    assert stages == ['ESRGAN Upscale', 'done:ESRGAN Upscale']
    assert after == {0: '/clips/0.mp4'}
    assert log.levels() == ['WARNING']
    assert 'ESRGAN model not found at' in log.messages()[0]
