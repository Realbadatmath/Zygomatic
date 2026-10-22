# SPDX-FileCopyrightText: 2026 Zygomatic
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The halves of scholarly_motion that touch ffmpeg and LTX (coverage wave 1).

``tests/test_scholarly_motion.py`` already pins the arithmetic and the prompt.
What was never exercised is everything that would normally need a process or a
server: ``render_move`` (the ffmpeg call and its nvenc→x264 fallback), the
encoder argument helpers, and the body of ``animate_stills`` — the retry, the
Ken Burns accounting, the manifest and the abort path.

Everything here is offline.  ``subprocess.run`` is replaced by a function that
writes a plausible file and reports a return code, and
``zyg_workflows.ltx_hidream_service`` by a stub whose ``ltx_i2v`` returns a
scripted list of outcomes — so a "failed clip" is a list entry, not a GPU.
"""

import contextlib
import importlib
import json
import logging
import os

import pytest


def _reload(**env):
    for k, v in env.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
    from zyg_workflows import scholarly_motion

    return importlib.reload(scholarly_motion)


@pytest.fixture
def sm():
    """The module with a clean environment, restored afterwards."""
    m = _reload(ZYG_SCHOLARLY_CLIP_S=None, ZYG_SCHOLARLY_LTX=None)
    yield m
    _reload(ZYG_SCHOLARLY_CLIP_S=None, ZYG_SCHOLARLY_LTX=None)


# ── clip_seconds: the branch the arithmetic tests never reach ────────────────


@pytest.mark.parametrize('garbage', [None, 'x', object(), [1]])
def test_clip_seconds_falls_back_to_the_target_on_garbage(sm, garbage):
    """A slot length that is not a number is the clip target, not a crash."""
    assert sm.clip_seconds(garbage) == sm.clip_seconds(sm.clip_target_s())


def test_clip_seconds_env_override_is_clamped_to_the_measured_ceiling():
    """ZYG_SCHOLARLY_CLIP_S is read at call time and clamped to CLIP_MAX_S=20."""
    m = _reload(ZYG_SCHOLARLY_CLIP_S='999')
    try:
        assert m.clip_target_s() == m.CLIP_MAX_S == 20.0
        assert m.clip_seconds(None) == int(m.CLIP_MAX_S)
    finally:
        _reload(ZYG_SCHOLARLY_CLIP_S=None)


# ── encoder arguments ────────────────────────────────────────────────────────


def test_encoder_args_name_a_codec_each(sm):
    nv, x264 = sm._nvenc_args(), sm._x264_args()
    assert nv[0] == '-c:v' and 'nvenc' in nv[1]
    assert x264[0] == '-c:v' and x264[1] == 'libx264'


def test_encoder_args_survive_a_missing_encode_utils(sm, stub_module):
    """encode_utils is imported lazily; without it the helpers hardcode a sane set."""
    stub_module('encode_utils', None)
    assert sm._nvenc_args() == ['-c:v', 'h264_nvenc', '-preset', 'p4', '-cq', '21']
    assert sm._x264_args() == ['-c:v', 'libx264', '-crf', '17', '-preset', 'veryfast']


# ── render_move: the camera move, as the ffmpeg command line ─────────────────


class _Run:
    """A stand-in for ``subprocess.run`` that scripts return codes per call."""

    def __init__(self, codes=(0,), *, size=20_000, raises_on=()):
        self.codes = list(codes)
        self.size = size
        self.raises_on = set(raises_on)
        self.cmds = []

    def __call__(self, cmd, **kw):
        self.cmds.append(list(cmd))
        n = len(self.cmds)
        if n in self.raises_on:
            raise OSError('ffmpeg is not installed on this runner')
        rc = self.codes[min(n - 1, len(self.codes) - 1)]
        if rc == 0 and self.size:
            with open(cmd[-1], 'wb') as fh:
                fh.write(b'\0' * self.size)
        return type('R', (), {'returncode': rc, 'stdout': b'', 'stderr': b''})()


@pytest.fixture
def ffmpeg(sm, monkeypatch):
    """Install a scripted subprocess.run and a predictable ffmpeg binary name."""

    def install(run):
        monkeypatch.setattr(sm, 'exe', lambda name: f'/usr/bin/{name}')
        monkeypatch.setattr(sm.subprocess, 'run', run)
        return run

    return install


def _vf(cmd):
    return cmd[cmd.index('-vf') + 1]


def test_render_move_bakes_the_zoompan_move_and_drops_the_audio(sm, ffmpeg, tmp_path):
    run = ffmpeg(_Run([0]))
    dst = tmp_path / 'clip.mp4'
    assert sm.render_move(str(tmp_path / 'raw.mp4'), str(dst), seconds=20.0, index=0) is True
    assert len(run.cmds) == 1  # nvenc took it; x264 was never tried
    cmd = run.cmds[0]
    assert cmd[0] == '/usr/bin/ffmpeg' and '-an' in cmd and cmd[-1] == str(dst)
    vf = _vf(cmd)
    assert 'zoompan=' in vf and 's=1920x1080' in vf and 'setsar=1' in vf
    assert f'scale={sm._WORK_W}:{sm._WORK_H}:flags=lanczos' in vf
    assert 'min(on/600,1)' in vf  # 20 s x 30 fps


@pytest.mark.parametrize(
    ('index', 'start', 'delta'),
    [(0, '1.0000', '+(0.1000)'), (1, '1.1000', '+(-0.1000)'), (2, '1.0000', '+(0.1000)')],
)
def test_render_move_alternates_the_direction(sm, ffmpeg, tmp_path, index, start, delta):
    """Even slots push in, odd slots pull out — a 50-shot episode does not push
    in fifty times.  The direction is visible in the filter, not just move_for."""
    run = ffmpeg(_Run([0]))
    sm.render_move(str(tmp_path / 'r.mp4'), str(tmp_path / f'c{index}.mp4'), seconds=5.0, index=index)
    assert f"zoompan=z='{start}{delta}*min(on/150,1)'" in _vf(run.cmds[0])


@pytest.mark.parametrize('index', range(6))
def test_render_move_never_zooms_below_one(sm, ffmpeg, tmp_path, index):
    """Below 1.0 the crop would need pixels outside the frame."""
    run = ffmpeg(_Run([0]))
    sm.render_move(str(tmp_path / 'r.mp4'), str(tmp_path / f'c{index}.mp4'), seconds=4.0, index=index)
    z0, z1, _ = sm.move_for(index)
    assert min(z0, z1) >= 1.0
    assert f"z='{z0:.4f}+" in _vf(run.cmds[0])


@pytest.mark.parametrize(('zone', 'fx'), [('left', '0.380'), ('center', '0.500'), ('right', '0.620')])
def test_render_move_biases_the_crop_toward_the_focal_zone(sm, ffmpeg, tmp_path, zone, fx):
    run = ffmpeg(_Run([0]))
    sm.render_move(str(tmp_path / 'r.mp4'), str(tmp_path / f'{zone}.mp4'), seconds=4.0, focal_zone=zone)
    assert f"x='(iw-iw/zoom)*{fx}'" in _vf(run.cmds[0])


def test_render_move_honours_an_explicit_frame_size(sm, ffmpeg, tmp_path):
    run = ffmpeg(_Run([0]))
    sm.render_move(str(tmp_path / 'r.mp4'), str(tmp_path / 'c.mp4'), seconds=2.0, w=1280, h=720, fps=24)
    vf = _vf(run.cmds[0])
    assert 's=1280x720' in vf and 'fps=24' in vf and 'min(on/48,1)' in vf


def test_render_move_falls_back_from_nvenc_to_x264(sm, ffmpeg, tmp_path):
    """No GPU on the runner: the nvenc attempt fails and libx264 finishes the job."""
    run = ffmpeg(_Run([1, 0]))
    assert sm.render_move(str(tmp_path / 'r.mp4'), str(tmp_path / 'c.mp4'), seconds=4.0) is True
    assert len(run.cmds) == 2
    assert 'h264_nvenc' in run.cmds[0] and 'libx264' in run.cmds[1]


def test_render_move_reports_failure_when_both_encoders_fail(sm, ffmpeg, tmp_path):
    run = ffmpeg(_Run([1, 1]))
    assert sm.render_move(str(tmp_path / 'r.mp4'), str(tmp_path / 'c.mp4'), seconds=4.0) is False
    assert len(run.cmds) == 2


def test_render_move_rejects_a_truncated_output(sm, ffmpeg, tmp_path):
    """returncode 0 with a 1 KB file is a broken clip, not a clip."""
    ffmpeg(_Run([0], size=200))
    assert sm.render_move(str(tmp_path / 'r.mp4'), str(tmp_path / 'c.mp4'), seconds=4.0) is False


def test_render_move_survives_a_missing_ffmpeg(sm, ffmpeg, tmp_path, caplog):
    """An OSError from the first variant is logged and the next one is tried."""
    run = ffmpeg(_Run([0], raises_on=(1,)))
    with caplog.at_level(logging.WARNING, logger=sm.__name__):
        assert sm.render_move(str(tmp_path / 'r.mp4'), str(tmp_path / 'c.mp4'), seconds=4.0) is True
    assert len(run.cmds) == 2
    assert 'trying the next variant' in caplog.text


# ── animate_stills: the stage, with the server scripted ─────────────────────


class _LtxStub:
    """``ltx_hidream_service`` with no ComfyUI behind it."""

    def __init__(self, *, up=True, results=(True,)):
        self.up = up
        self.results = list(results)
        self.calls = []
        self.leases = 0

    def ensure_up(self, log_fn=None):
        return self.up

    @contextlib.contextmanager
    def gpu_lease(self, abort, log_fn=None):
        self.leases += 1
        yield

    def ltx_i2v(self, src, prompt, raw, **kw):
        self.calls.append({'src': src, 'prompt': prompt, 'raw': raw, **kw})
        ok = self.results[min(len(self.calls) - 1, len(self.results) - 1)]
        if ok:
            with open(raw, 'wb') as fh:
                fh.write(b'\0' * 32)
        return ok


@pytest.fixture
def stage(sm, monkeypatch, stub_module, tmp_path):
    """Wire a scripted LTX stub + render_move, and hand back the log lines."""
    lines = []

    def install(*, results=(True,), moves=(True,), up=True):
        ltx = _LtxStub(up=up, results=results)
        stub_module('ltx_hidream_service', ltx)
        seq = list(moves)
        rendered = []

        def fake_move(src, dst, *, seconds, index=0, focal_zone='center'):
            rendered.append({'src': src, 'dst': dst, 'seconds': seconds, 'index': index, 'zone': focal_zone})
            ok = seq[min(len(rendered) - 1, len(seq) - 1)]
            if ok:
                with open(dst, 'wb') as fh:
                    fh.write(b'\0' * 64)
            return ok

        monkeypatch.setattr(sm, 'render_move', fake_move)
        return ltx, rendered

    install.lines = lines
    install.log = lines.append
    return install


def _images(tmp_path, n, **extra):
    out = []
    for i in range(n):
        p = tmp_path / f'still_{i}.png'
        p.write_bytes(b'PNG')
        out.append({'path': str(p), 'subject': f'subject {i}', **extra})
    return out


def test_a_clip_per_picture_lands_with_a_manifest(sm, stage, tmp_path):
    ltx, rendered = stage()
    out = tmp_path / 'ep'
    rec = sm.animate_stills(
        _images(tmp_path, 3, focal_zone='left'), str(out), durations=[6.0, 7.0, 8.0], log_fn=stage.log, seed=5
    )
    assert (rec['clips'], rec['failed'], rec['retries'], rec['skipped'], rec['kenburns']) == (3, 0, 0, 0, 0)
    assert rec['available'] is True and rec['aborted'] is False
    assert rec['motion_coverage'] == 1.0
    assert rec['clip_seconds_total'] == 7 + 8 + 9
    assert rec['seconds'] >= 0.0 and ltx.leases == 1
    entries = json.loads((out / sm.MANIFEST_REL).read_text(encoding='utf-8'))
    assert rec['manifest'] == str(out / sm.MANIFEST_REL)
    assert [e['index'] for e in entries] == [0, 1, 2]
    assert [e['seconds'] for e in entries] == [7, 8, 9]
    assert [e['slot_s'] for e in entries] == [6.0, 7.0, 8.0]
    assert {e['attempt'] for e in entries} == {1}
    assert all(e['engine'] == 'ltx-2.5-distilled' and os.path.isfile(e['path']) for e in entries)
    assert [r['zone'] for r in rendered] == ['left'] * 3


def test_the_raw_ltx_clip_is_deleted_once_the_move_is_baked(sm, stage, tmp_path):
    stage()
    out = tmp_path / 'ep'
    sm.animate_stills(_images(tmp_path, 2), str(out), total_s=40)
    names = sorted(os.listdir(out / 'ltx_clips'))
    assert names == ['clip_000.mp4', 'clip_001.mp4', 'ltx_manifest.json']


def test_the_prompt_and_the_render_size_reach_the_engine(sm, stage, tmp_path):
    ltx, _ = stage()
    sm.animate_stills(_images(tmp_path, 1), str(tmp_path / 'ep'), durations=[10.0])
    call = ltx.calls[0]
    assert call['seconds'] == 11 and call['aspect'] == sm.LTX_ASPECT
    assert call['megapixels'] == sm.LTX_MEGAPIXELS
    assert call['timeout_s'] == 900.0
    assert 'locked off' in call['prompt'].lower() and 'subject 0' in call['prompt']


def test_slots_come_from_the_narration_when_durations_are_absent(sm, stage, tmp_path):
    ltx, _ = stage()
    sm.animate_stills(_images(tmp_path, 4), str(tmp_path / 'a'), total_s=48.0)
    assert [c['seconds'] for c in ltx.calls] == [13, 13, 13, 13]  # 12 s slot + xfade


def test_a_mismatched_durations_list_is_ignored(sm, stage, tmp_path):
    """Two lengths for four pictures is not a grid — fall back to the narration."""
    ltx, _ = stage()
    sm.animate_stills(_images(tmp_path, 4), str(tmp_path / 'b'), durations=[3.0, 4.0], total_s=48.0)
    assert [c['seconds'] for c in ltx.calls] == [13, 13, 13, 13]


def test_without_a_narration_length_the_slot_is_the_clip_target(sm, stage, tmp_path):
    ltx, _ = stage()
    sm.animate_stills(_images(tmp_path, 2), str(tmp_path / 'c'), total_s=0.0)
    assert [c['seconds'] for c in ltx.calls] == [int(sm.CLIP_MAX_S)] * 2


def test_the_budget_is_announced_before_the_first_clip(sm, stage, tmp_path):
    stage()
    sm.animate_stills(_images(tmp_path, 3), str(tmp_path / 'd'), total_s=60.0, log_fn=stage.log)
    head = stage.lines[0]
    # 20 s a slot, and the clip that covers it is clamped to the 20 s ceiling
    assert '3 picture(s)' in head and '60s of LTX-2.5 video' in head
    assert 'min at the measured 6.5s of wall per second of clip' in head


def test_a_failed_clip_is_retried_once_with_a_fresh_seed(sm, stage, tmp_path):
    ltx, _ = stage(results=[False, True])
    rec = sm.animate_stills(_images(tmp_path, 1), str(tmp_path / 'e'), durations=[5.0], seed=3, log_fn=stage.log)
    assert (rec['clips'], rec['failed'], rec['retries']) == (1, 0, 1)
    seeds = [c['seed'] for c in ltx.calls]
    assert len(seeds) == 2 and seeds[1] - seeds[0] == 1000003
    assert 'picture 0 clip failed (attempt 1)' in '\n'.join(stage.lines)
    entries = json.loads((tmp_path / 'e' / sm.MANIFEST_REL).read_text(encoding='utf-8'))
    assert entries[0]['attempt'] == 2 and entries[0]['seed'] == seeds[1]


def test_two_failures_leave_the_picture_to_ken_burns_and_say_so(sm, stage, tmp_path):
    ltx, _ = stage(results=[False])
    rec = sm.animate_stills(_images(tmp_path, 2), str(tmp_path / 'f'), total_s=40.0, log_fn=stage.log)
    assert (rec['clips'], rec['failed'], rec['retries'], rec['kenburns']) == (0, 2, 4, 2)
    assert rec['motion_coverage'] == 0.0 and rec['available'] is True
    assert len(ltx.calls) == 4  # two attempts per picture
    assert json.loads((tmp_path / 'f' / sm.MANIFEST_REL).read_text(encoding='utf-8')) == []


def test_a_clip_that_will_not_encode_counts_as_failed(sm, stage, tmp_path):
    """LTX delivered, ffmpeg did not: still no clip, still counted."""
    ltx, rendered = stage(results=[True], moves=[False])
    rec = sm.animate_stills(_images(tmp_path, 1), str(tmp_path / 'g'), durations=[5.0])
    assert (rec['clips'], rec['failed'], rec['retries'], rec['kenburns']) == (0, 1, 2, 1)
    assert len(rendered) == 2


def test_the_second_attempt_can_be_the_one_that_encodes(sm, stage, tmp_path):
    stage(results=[True], moves=[False, True])
    rec = sm.animate_stills(_images(tmp_path, 1), str(tmp_path / 'h'), durations=[5.0])
    assert (rec['clips'], rec['failed'], rec['retries']) == (1, 0, 1)


def test_a_picture_with_no_file_is_skipped_not_failed(sm, stage, tmp_path):
    ltx, _ = stage()
    imgs = [*_images(tmp_path, 1), {'path': str(tmp_path / 'gone.png')}, {}, {'path': ''}, None]
    rec = sm.animate_stills(imgs, str(tmp_path / 'i'), total_s=100.0)
    assert (rec['pictures'], rec['clips'], rec['skipped'], rec['failed']) == (5, 1, 4, 0)
    assert rec['kenburns'] == 4
    assert len(ltx.calls) == 1


def test_an_abort_before_the_first_picture_renders_nothing(sm, stage, tmp_path):
    ltx, _ = stage()
    rec = sm.animate_stills(
        _images(tmp_path, 3), str(tmp_path / 'j'), total_s=60.0, should_abort=lambda: True, log_fn=stage.log
    )
    assert rec['aborted'] is True and rec['clips'] == 0 and ltx.calls == []
    assert rec['kenburns'] == 3
    assert 'motion: halt requested after 0 clip(s)' in stage.lines


def test_an_abort_midway_keeps_the_clips_already_made(sm, stage, tmp_path):
    ltx, _ = stage()
    rec = sm.animate_stills(
        _images(tmp_path, 4),
        str(tmp_path / 'k'),
        total_s=80.0,
        should_abort=lambda: len(ltx.calls) >= 2,
        log_fn=stage.log,
    )
    assert rec['aborted'] is True
    assert rec['clips'] == 2 and rec['kenburns'] == 2
    assert 'motion: halt requested after 2 clip(s)' in stage.lines
    assert len(json.loads((tmp_path / 'k' / sm.MANIFEST_REL).read_text(encoding='utf-8'))) == 2


def test_progress_is_logged_every_fifth_picture_and_at_the_end(sm, stage, tmp_path):
    stage()
    sm.animate_stills(_images(tmp_path, 6), str(tmp_path / 'l'), total_s=120.0, log_fn=stage.log)
    joined = '\n'.join(stage.lines)
    assert 'motion: 5/6 done (5 clips, 0 failed)' in joined
    assert 'motion: 6/6 done (6 clips, 0 failed)' in joined
    assert 'motion: 6/6 pictures animated (coverage 1.00, 0 Ken Burns)' in joined


def test_a_failed_raw_cleanup_does_not_lose_the_clip(sm, stage, tmp_path, monkeypatch, caplog):
    stage()
    real = os.remove

    def stubborn(path, *a, **kw):
        if os.path.basename(str(path)).startswith('raw_'):
            raise OSError('held open by the encoder')
        return real(path, *a, **kw)

    monkeypatch.setattr(sm.os, 'remove', stubborn)
    with caplog.at_level(logging.DEBUG, logger=sm.__name__):
        rec = sm.animate_stills(_images(tmp_path, 1), str(tmp_path / 'm'), durations=[5.0])
    assert rec['clips'] == 1
    assert 'cleanup skipped' in caplog.text


def test_a_manifest_that_cannot_be_written_is_reported_not_raised(sm, stage, tmp_path):
    stage()
    out = tmp_path / 'n'
    (out / 'ltx_clips').mkdir(parents=True)
    (out / sm.MANIFEST_REL).mkdir()  # a directory where the JSON belongs
    rec = sm.animate_stills(_images(tmp_path, 1), str(out), durations=[5.0], log_fn=stage.log)
    assert rec['clips'] == 1
    assert any('manifest write failed' in line for line in stage.lines)


def test_a_missing_ltx_module_keeps_ken_burns(sm, stub_module, tmp_path):
    """The service import is lazy, so an absent module is a fallback, not a crash."""
    stub_module('ltx_hidream_service', None)
    lines = []
    rec = sm.animate_stills(_images(tmp_path, 3), str(tmp_path / 'o'), total_s=60.0, log_fn=lines.append)
    assert rec['available'] is False and rec['clips'] == 0 and rec['kenburns'] == 3
    assert 'ltx_hidream_service unavailable' in rec['reason']
    assert any('Ken Burns kept' in line for line in lines)


def test_a_server_that_is_down_never_takes_the_gpu_lease(sm, stage, tmp_path):
    ltx, _ = stage(up=False)
    rec = sm.animate_stills(_images(tmp_path, 2), str(tmp_path / 'p'), total_s=40.0)
    assert rec['available'] is False and ltx.leases == 0 and rec['kenburns'] == 2
    assert not (tmp_path / 'p').exists()  # nothing is created before the server answers


def test_the_default_log_sink_is_silent(sm, stage, tmp_path, capsys):
    """No log_fn means no output — the stage must not print into a pipeline run."""
    stage()
    rec = sm.animate_stills(_images(tmp_path, 1), str(tmp_path / 'q'), durations=[5.0])
    assert rec['clips'] == 1
    assert capsys.readouterr().out == ''
    assert sm._log_noop('anything') is None
