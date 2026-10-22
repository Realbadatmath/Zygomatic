# SPDX-FileCopyrightText: 2026 Zygomatic
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Coverage tests for `zyg_workflows.video_assembly`.

The module is a timeline: it shells out to ffmpeg/ffprobe and streams raw
frames through pipes.  Nothing here runs either binary and nothing here
writes a real video.  `_run`, `subprocess.Popen` and `cv2.VideoCapture` are
replaced by recorders, so what is tested is the arithmetic and the command
lines: the ramp index map, the dive crop window, the xfade offsets, the
receipt, and every error branch that guards them.
"""

import json
import os
import subprocess

import cv2
import numpy as np
import pytest

from zyg_workflows import video_assembly as va

SIZE = [32, 24]
JOIN_SIZE = [64, 48]


# ── fakes and call wrappers ───────────────────────────────────────────────


def _frame(h=24, w=32, fill=7):
    return np.full((h, w, 3), fill, np.uint8)


def _textured(h=240, w=320, seed=0):
    """A high-contrast blocky texture ORB can actually find corners in."""
    rng = np.random.default_rng(seed)
    return cv2.resize(rng.integers(0, 256, (12, 16, 3), dtype=np.uint8), (w, h), interpolation=cv2.INTER_NEAREST)


class FakeStdin:
    def __init__(self, close_raises=False):
        self.chunks = []
        self.closed = False
        self._close_raises = close_raises

    def write(self, data):
        self.chunks.append(data)

    def close(self):
        self.closed = True
        if self._close_raises:
            raise BrokenPipeError('ffmpeg already gone')


class FakeStream:
    def __init__(self, data=b''):
        self._data = data

    def read(self):
        return self._data


class FakePopen:
    """A `subprocess.Popen` stand-in that writes the output file itself."""

    calls = []
    live = []

    def __init__(self, cmd, returncode=0, stderr=b'', close_raises=False):
        FakePopen.calls.append(cmd)
        FakePopen.live.append(self)
        self.returncode = returncode
        self.stdin = FakeStdin(close_raises)
        self.stdout = FakeStream(b'')
        self.stderr = FakeStream(stderr)
        with open(cmd[-1], 'wb') as fh:
            fh.write(b'0' * 2048)

    def wait(self):
        return self.returncode


class FakeCap:
    """A `cv2.VideoCapture` stand-in over a list of frames."""

    def __init__(self, frames, opened=True, count=None):
        self._frames = list(frames)
        self._i = 0
        self._opened = opened
        self._count = len(self._frames) if count is None else count
        self.released = False

    def isOpened(self):  # noqa: N802  (cv2's own spelling)
        return self._opened

    def get(self, _prop):
        return float(self._count)

    def read(self):
        if self._i >= len(self._frames):
            return False, None
        self._i += 1
        return True, self._frames[self._i - 1]

    def release(self):
        self.released = True


class Proc:
    def __init__(self, returncode=0, stdout='', stderr=''):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def _rig_pipe(monkeypatch, frames, opened=True, count=None, **popen_kw):
    """Point cv2 at `frames` and subprocess at a recording pipe."""
    cap = FakeCap(frames, opened=opened, count=count)
    monkeypatch.setattr(va.cv2, 'VideoCapture', lambda _src: cap)
    FakePopen.calls = []
    FakePopen.live = []
    monkeypatch.setattr(subprocess, 'Popen', lambda cmd, **kw: FakePopen(cmd, **popen_kw))
    return cap


def _ramp(out, tail_s=0.0, end_speed=1.0, draft=False, log=None, fps=24):
    return va._speed_ramp(str(out), str(out), SIZE, fps, tail_s, end_speed, draft, log or va._log_noop)


def _dive(out, opts=None, draft=False, log=None, fps=24):
    return va._dive_zoom(str(out), str(out), SIZE, fps, opts or {}, draft, log or va._log_noop)


def _join(out, durations, xfades, fade_in=0.0, fade_out=0.0, color='black'):
    parts = ['p%d.mp4' % i for i in range(len(durations))]
    return va._join_and_fade(
        parts, durations, xfades, str(out), JOIN_SIZE, 24, fade_in, fade_out, color, False, va._log_noop
    )


def _ffmpeg_recorder(monkeypatch):
    """Replace `_ffmpeg` with a recorder; returns the dict it fills in."""
    seen = {}

    def fake(cmd, out_path, what, log):
        seen.update(cmd=cmd, out=out_path, what=what)
        return out_path

    monkeypatch.setattr(va, '_ffmpeg', fake)
    return seen


# ── trivia: the logging sink, the command fragments ───────────────────────


def test_the_default_log_sink_swallows_everything():
    assert va._log_noop('anything') is None


def test_run_hands_subprocess_the_capture_flags(monkeypatch):
    seen = {}
    monkeypatch.setattr(subprocess, 'run', lambda cmd, **kw: seen.update(cmd=cmd, kw=kw) or Proc())
    assert va._run(['x'], cwd='/tmp').returncode == 0
    assert seen['cmd'] == ['x']
    assert seen['kw'] == {'capture_output': True, 'text': True, 'cwd': '/tmp'}


@pytest.mark.parametrize('fps,want', [(24, '24'), (24.0, '24'), (23.976, '23.976000'), (29.97, '29.970000')])
def test_an_integer_fps_is_written_without_a_decimal_tail(fps, want):
    assert va._fps_arg(fps) == want


def test_the_conform_chain_scales_pads_and_pins_the_fps():
    assert va._conform_chain([1920, 1080], 24) == (
        'scale=1920:1080:force_original_aspect_ratio=decrease:flags=bicubic,'
        'pad=1920:1080:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1,fps=24'
    )
    assert 'fps=23.976000' in va._conform_chain([640, 360], 23.976)


def test_draft_trades_crf_and_preset_for_speed_and_the_defaults_are_sane():
    draft, final = va._x264(True), va._x264(False)
    assert draft[draft.index('-crf') + 1] == '26'
    assert draft[draft.index('-preset') + 1] == 'ultrafast'
    assert final[final.index('-crf') + 1] == '16'
    assert final[final.index('-preset') + 1] == 'medium'
    assert draft[:4] == final[:4] == ['-c:v', 'libx264', '-pix_fmt', 'yuv420p']
    assert os.path.basename(va.FFMPEG).startswith('ffmpeg')
    assert os.path.basename(va.FFPROBE).startswith('ffprobe')
    assert va.SHOT_DEFAULTS['xfade_s'] == 0.0
    assert va.LIST_DEFAULTS['size'] == [1920, 1080]
    assert va.DIVE_DEFAULTS['focus'] == [0.5, 0.78]


# ── _ffmpeg ───────────────────────────────────────────────────────────────


def test_ffmpeg_prefixes_the_quiet_flags_and_returns_the_output(tmp_path, monkeypatch):
    out = tmp_path / 'o.mp4'
    logged = []

    def fake_run(cmd):
        out.write_bytes(b'0' * 2048)
        return Proc()

    monkeypatch.setattr(va, '_run', fake_run)
    assert va._ffmpeg(['-i', 'a.mp4', str(out)], str(out), 'conform', logged.append) == str(out)
    assert logged[0].startswith('ffmpeg conform: ')
    assert '-hide_banner -v error -y' in logged[0]


@pytest.mark.parametrize('rc,size', [(1, 2048), (0, 10), (0, 0)])
def test_ffmpeg_refuses_a_bad_exit_a_tiny_file_and_a_missing_one(tmp_path, monkeypatch, rc, size):
    out = tmp_path / 'o.mp4'

    def fake_run(cmd):
        if size:
            out.write_bytes(b'0' * size)
        return Proc(returncode=rc, stderr='boom')

    monkeypatch.setattr(va, '_run', fake_run)
    with pytest.raises(RuntimeError, match='ffmpeg join failed'):
        va._ffmpeg([str(out)], str(out), 'join', va._log_noop)


# ── _probe ────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    'stream,fmt,want',
    [
        # Everything stated outright.
        (
            {'width': '1920', 'height': '1080', 'avg_frame_rate': '24/1', 'duration': '5.0', 'nb_frames': '120'},
            None,
            (1920, 1080, 24.0, 5.0, 120),
        ),
        # No frame count, and the duration only in the container: nb is derived.
        ({'width': 64, 'height': 48, 'avg_frame_rate': '25/1'}, {'duration': '4'}, (64, 48, 25.0, 4.0, 100)),
        # No duration anywhere: it is derived from the frame count.
        ({'width': 2, 'height': 2, 'avg_frame_rate': '30/1', 'nb_frames': 60}, None, (2, 2, 30.0, 2.0, 60)),
        # A rate with a zero denominator leaves the fps — and so the duration — at zero.
        ({'width': 2, 'height': 2, 'avg_frame_rate': '0/0', 'nb_frames': 3}, None, (2, 2, 0.0, 0.0, 3)),
    ],
)
def test_probe_fills_in_whatever_ffprobe_left_out(monkeypatch, stream, fmt, want):
    body = {'streams': [stream]}
    if fmt is not None:
        body['format'] = fmt
    monkeypatch.setattr(va, '_run', lambda cmd: Proc(stdout=json.dumps(body)))
    assert va._probe('a.mp4') == want


@pytest.mark.parametrize(
    'proc,msg',
    [(Proc(returncode=1, stderr='nope'), 'ffprobe failed on a.mp4'), (Proc(stdout='{}'), 'no video stream in a.mp4')],
)
def test_probe_raises_on_a_failed_ffprobe_and_on_a_stream_less_file(monkeypatch, proc, msg):
    monkeypatch.setattr(va, '_run', lambda cmd: proc)
    with pytest.raises(RuntimeError, match=msg):
        va._probe('a.mp4')


# ── _conform_clip / _still_clip ───────────────────────────────────────────


@pytest.mark.parametrize(
    'trim,head',
    [
        # A start seeks before the input, an end becomes a duration after it.
        ([1.5, 4.0], ['-ss', '1.500000', '-i', '/src/a.mp4', '-t', '2.500000']),
        # An open-ended trim only seeks…
        ([2.0, None], ['-ss', '2.000000', '-i', '/src/a.mp4', '-vf']),
        # …a zero start only trims…
        ([0, 3.0], ['-i', '/src/a.mp4', '-t', '3.000000', '-vf']),
        # …and no trim at all does neither.
        (None, ['-i', '/src/a.mp4', '-vf']),
    ],
)
def test_a_trim_becomes_a_seek_before_the_input_and_a_duration_after(monkeypatch, trim, head):
    seen = _ffmpeg_recorder(monkeypatch)
    va._conform_clip('/src/a.mp4', '/o.mp4', JOIN_SIZE, 24, trim, False, va._log_noop)
    assert seen['cmd'][: len(head)] == head
    assert '-an' in seen['cmd']
    assert seen['cmd'][-1] == '/o.mp4'
    assert seen['what'] == 'conform a.mp4'


def test_a_still_is_a_looped_single_frame_held_for_its_seconds(monkeypatch):
    seen = _ffmpeg_recorder(monkeypatch)
    va._still_clip('/img/title.png', '/o.mp4', JOIN_SIZE, 25, 5.0, True, va._log_noop)
    assert seen['cmd'][:6] == ['-loop', '1', '-framerate', '25', '-i', '/img/title.png']
    assert seen['cmd'][6:8] == ['-t', '5.000000']
    assert 'ultrafast' in seen['cmd']
    assert seen['what'] == 'still title.png'


# ── the eases and the ramp map ────────────────────────────────────────────


@pytest.mark.parametrize('p,want', [(-1.0, 0.0), (0.0, 0.0), (0.5, 0.5), (1.0, 1.0), (2.0, 1.0)])
def test_the_smoothstep_is_clamped_and_symmetric(p, want):
    assert va._smoothstep(p) == pytest.approx(want)


@pytest.mark.parametrize(
    'ease,u,want',
    [
        ('linear', 0.25, 0.25),
        ('in', 0.5, 0.25),
        ('out', 0.5, 0.75),
        ('in-out', 0.5, 0.5),
        ('nonsense', 0.5, 0.5),
        ('linear', -3.0, 0.0),
        ('in', 9.0, 1.0),
    ],
)
def test_every_ease_curve_passes_through_its_known_point(ease, u, want):
    assert va._ease_at(u, ease) == pytest.approx(want)


@pytest.mark.parametrize(
    'ease,u,want',
    [('linear', 0.3, 1.0), ('in', 0.3, 0.3), ('out', 0.3, 0.7), ('in-out', 0.5, 1.0), ('other', 0.0, 0.0)],
)
def test_the_eases_rate_peaks_at_one(ease, u, want):
    assert va._ease_rate(u, ease) == pytest.approx(want)
    assert va._ease_rate(-1.0, ease) == pytest.approx(va._ease_rate(0.0, ease))


def test_a_ramp_with_no_tail_or_no_slowdown_is_the_identity_map():
    assert va.ramp_index_map(10, 0, 0.2) == list(range(10))
    assert va.ramp_index_map(10, -5, 0.2) == list(range(10))
    assert va.ramp_index_map(12, 6, 1.0) == list(range(12))


def test_the_tail_yields_more_output_frames_than_it_had_source_frames():
    idx = va.ramp_index_map(48, 24, 0.25)
    assert idx[:25] == list(range(25))  # the head passes through untouched
    assert len(idx) > 48
    assert all(b >= a for a, b in zip(idx, idx[1:]))
    assert max(idx) <= 47


def test_a_tail_longer_than_the_clip_is_clamped_and_a_zero_speed_is_floored():
    idx = va.ramp_index_map(8, 99, 0.0)
    assert idx[0] == 0
    assert max(idx) <= 7
    assert all(b >= a for a, b in zip(idx, idx[1:]))
    # end_speed is floored at 1e-3, so the guard — not the speed — ends the loop.
    assert len(idx) <= int(8 / 1e-3) + 8 + 16


# ── the dive geometry ─────────────────────────────────────────────────────


def test_a_zoom_of_one_or_less_returns_the_very_same_frame_object():
    f = _frame()
    assert va._dive_crop(f, 1.0, 0.5, 0.5, 32, 24) is f
    assert va._dive_crop(f, 0.2, 0.5, 0.5, 32, 24) is f


def test_the_crop_window_is_clamped_inside_the_frame():
    grad = np.tile(np.arange(64, dtype=np.uint8).reshape(1, 64, 1), (48, 1, 3))
    out = va._dive_crop(grad, 2.0, 0.0, 0.0, 64, 48)
    assert out.shape == (48, 64, 3)
    assert int(out[0, 0, 0]) == 0  # focus top-left: the window starts at x=0
    assert int(va._dive_crop(grad, 2.0, 1.0, 1.0, 64, 48)[0, -1, 0]) == 63  # flush with the right edge
    assert va._dive_crop(_frame(8, 8), 4.0, 0.5, 0.5, 8, 8).shape == (8, 8, 3)  # the 8 px floor


def test_the_smear_only_touches_the_lower_part_of_the_frame():
    a = va._dive_blur_alpha(100)
    assert a.shape == (100, 1, 1)
    assert (a[0, 0, 0], a[-1, 0, 0]) == (0.0, 1.0)
    assert np.all(np.diff(a[:, 0, 0]) >= 0)

    f = np.random.default_rng(1).integers(0, 256, (100, 32, 3), dtype=np.uint8)
    out = va._dive_blur(f, 9, a)
    assert out.dtype == np.uint8 and out.shape == f.shape
    assert np.array_equal(out[0], f[0])  # alpha 0 up top
    assert not np.array_equal(out[-1], f[-1])  # alpha 1 at the bottom
    # A kernel under three pixels is not worth a convolution.
    assert va._dive_blur(f, 2, a) is f


# ── orb_scale ─────────────────────────────────────────────────────────────


def test_a_featureless_pair_cannot_be_matched():
    assert va.orb_scale(_frame(240, 320), _frame(240, 320, fill=200)) is None


def test_a_pushed_in_pair_measures_a_scale_above_one():
    a = _textured()
    b = va._dive_crop(a, 1.6, 0.5, 0.5, 320, 240)
    s = va.orb_scale(a, b)
    assert isinstance(s, float)
    assert 1.1 < s < 2.4
    # A grey-scale pair takes the same path with no colour conversion.
    gray = cv2.cvtColor(a, cv2.COLOR_BGR2GRAY), cv2.cvtColor(b, cv2.COLOR_BGR2GRAY)
    assert isinstance(va.orb_scale(*gray), float)


def test_too_few_matches_and_an_unsolvable_fit_both_give_up(monkeypatch):
    class M:
        distance = 1.0
        queryIdx = 0
        trainIdx = 0

    class Few:
        def match(self, _da, _db):
            return [M()] * 4

    monkeypatch.setattr(va.cv2, 'BFMatcher', lambda *args, **kw: Few())
    assert va.orb_scale(_textured(), _textured(seed=3)) is None

    monkeypatch.undo()
    monkeypatch.setattr(va.cv2, 'estimateAffinePartial2D', lambda *args, **kw: (None, None))
    a = _textured()
    assert va.orb_scale(a, va._dive_crop(a, 1.4, 0.5, 0.5, 320, 240)) is None


# ── _speed_ramp ───────────────────────────────────────────────────────────


def test_the_ramp_streams_every_mapped_frame_into_one_raw_pipe(tmp_path, monkeypatch):
    out = tmp_path / 'ramp.mp4'
    cap = _rig_pipe(monkeypatch, [_frame(fill=i) for i in range(12)])
    logged = []
    got, added = _ramp(out, tail_s=0.25, end_speed=0.25, log=logged.append)
    assert got == str(out)
    assert added == len(va.ramp_index_map(12, 6, 0.25)) - 12 > 0
    assert cap.released
    cmd = FakePopen.calls[0]
    assert cmd[0] == va.FFMPEG
    assert cmd[cmd.index('-s') + 1] == '32x24'
    assert cmd[cmd.index('-pix_fmt') + 1] == 'bgr24'
    assert any('ramp: 12 source frames' in m for m in logged)
    assert len(FakePopen.live[0].stdin.chunks) == len(va.ramp_index_map(12, 6, 0.25))


def test_the_ramp_asks_ffprobe_when_opencv_cannot_count_the_frames(tmp_path, monkeypatch):
    _rig_pipe(monkeypatch, [_frame() for _ in range(6)], count=0)
    monkeypatch.setattr(va, '_probe', lambda path: (32, 24, 24.0, 0.25, 6))
    assert _ramp(tmp_path / 'ramp.mp4', tail_s=0.1, end_speed=0.5, draft=True)[1] >= 0


def test_an_off_size_source_frame_is_resized_before_it_is_piped(tmp_path, monkeypatch):
    _rig_pipe(monkeypatch, [_frame(48, 64) for _ in range(4)])
    _ramp(tmp_path / 'ramp.mp4')
    chunks = FakePopen.live[-1].stdin.chunks
    assert len(chunks) == 4
    assert {len(c) for c in chunks} == {32 * 24 * 3}  # every one went through cv2.resize
    assert FakePopen.live[-1].stdin.closed


# ── _dive_zoom ────────────────────────────────────────────────────────────


def test_the_dive_writes_one_output_frame_per_source_frame(tmp_path, monkeypatch):
    out = tmp_path / 'dive.mp4'
    cap = _rig_pipe(monkeypatch, [_textured(24, 32, seed=i) for i in range(10)])
    logged = []
    got, info = _dive(out, {'zoom_end': 2.0, 'start_s': 0.0}, log=logged.append)
    assert got == str(out)
    assert info['zoom_end'] == 2.0
    assert info['frames'] == 10
    assert set(info) == {'zoom_end', 'frames', 's_measured'}
    assert cap.released
    assert len(FakePopen.live[0].stdin.chunks) == 10
    assert any('dive: 10 frames, zoom 1.0 -> 2.000' in m for m in logged)
    assert any('dive: 10 output frames' in m for m in logged)


def test_a_late_start_leaves_the_head_frames_alone_and_blur_can_be_off(tmp_path, monkeypatch):
    _rig_pipe(monkeypatch, [_frame(48, 64, fill=i * 10) for i in range(8)])
    opts = {'zoom_end': 1.5, 'focus': [0.2, 0.9], 'ease': 'linear', 'blur': False, 'start_s': 0.2}
    _, info = _dive(tmp_path / 'dive.mp4', opts, draft=True)
    # start_s 0.2 at 24 fps is frame 5, so only frames 5..7 dive.
    assert (info['frames'], info['zoom_end']) == (3, 1.5)


def test_a_single_dive_frame_reports_no_measured_scale(tmp_path, monkeypatch):
    _rig_pipe(monkeypatch, [_frame()])
    assert _dive(tmp_path / 'dive.mp4')[1] == {'zoom_end': 2.0, 'frames': 1, 's_measured': None}


def test_the_dive_asks_ffprobe_when_opencv_cannot_count_the_frames(tmp_path, monkeypatch):
    _rig_pipe(monkeypatch, [_frame() for _ in range(5)], count=0)
    monkeypatch.setattr(va, '_probe', lambda path: (32, 24, 24.0, 0.2, 5))
    assert _dive(tmp_path / 'dive.mp4', {'zoom_end': 1.2})[1]['frames'] == 5


# ── both streaming stages: the pipe and its error branches ────────────────


@pytest.mark.parametrize('stage', ['ramp', 'dive'], ids=['speed_ramp', 'dive_zoom'])
def test_a_pipe_that_is_already_gone_does_not_mask_the_result(tmp_path, monkeypatch, stage):
    out = tmp_path / 'o.mp4'
    _rig_pipe(monkeypatch, [_frame() for _ in range(3)], close_raises=True)
    got = _ramp(out)[0] if stage == 'ramp' else _dive(out, {'blur': False})[0]
    assert got == str(out)


@pytest.mark.parametrize(
    'stage,frames,rig_kw,msg',
    [
        # Neither stage can work on a file OpenCV refuses to open…
        ('ramp', [], {'opened': False}, 'cv2 cannot open'),
        ('dive', [], {'opened': False}, 'cv2 cannot open'),
        # …nor on one that claims frames and then decodes none…
        ('ramp', [], {'count': 4}, 'cv2 read nothing'),
        ('dive', [], {'count': 3}, 'cv2 read nothing'),
        # …and a non-zero encoder exit is an error, not a silent short file.
        ('ramp', [_frame()] * 4, {'returncode': 1, 'stderr': b'x264 died'}, 'ramp encode failed'),
        ('dive', [_frame()] * 3, {'returncode': 1, 'stderr': b'nope'}, 'dive encode failed'),
    ],
)
def test_the_streaming_stages_refuse_what_they_cannot_read_or_encode(tmp_path, monkeypatch, stage, frames, rig_kw, msg):
    _rig_pipe(monkeypatch, frames, **rig_kw)
    with pytest.raises(RuntimeError, match=msg):
        _ramp(tmp_path / 'o.mp4', tail_s=0.1, end_speed=0.5) if stage == 'ramp' else _dive(tmp_path / 'o.mp4')


# ── _load_record ──────────────────────────────────────────────────────────


def test_an_overlay_can_be_a_dict_a_path_or_nothing(tmp_path):
    rec = {'items': [1, 2]}
    assert va._load_record(rec) is rec
    assert va._load_record(None) is None
    p = tmp_path / 'ov.json'
    p.write_text(json.dumps(rec), encoding='utf-8')
    assert va._load_record(str(p)) == rec


# ── _join_and_fade ────────────────────────────────────────────────────────


def test_every_join_eats_its_crossfade_out_of_the_programme(tmp_path, monkeypatch):
    seen = _ffmpeg_recorder(monkeypatch)
    out = tmp_path / 'joined.mp4'
    total, starts = _join(out, [2.0, 3.0, 4.0], [0.5, 1.0])
    # 2 + 3 + 4 = 9 seconds of material minus 0.5 + 1.0 of overlap.
    assert total == pytest.approx(7.5)
    # Each offset is the cumulative duration SO FAR minus that join's own fade.
    assert starts == pytest.approx([0.0, 1.5, 3.5])
    graph = (tmp_path / 'join_graph.txt').read_text(encoding='utf-8')
    assert '[0:v]settb=AVTB,setpts=PTS-STARTPTS,fps=24,format=yuv420p[c0]' in graph
    assert '[c0][c1]xfade=transition=fade:duration=0.500000:offset=1.500000[x1]' in graph
    assert '[x1][c2]xfade=transition=fade:duration=1.000000:offset=3.500000[x2]' in graph
    assert graph.rstrip().endswith('[x2]format=yuv420p[vout]')
    assert seen['cmd'][:6] == ['-i', 'p0.mp4', '-i', 'p1.mp4', '-i', 'p2.mp4']
    assert '-filter_complex_script' in seen['cmd']
    assert seen['cmd'][-1] == str(out)


def test_a_crossfade_is_clamped_to_the_shorter_of_the_two_shots(tmp_path, monkeypatch):
    _ffmpeg_recorder(monkeypatch)
    total, starts = _join(tmp_path / 'j.mp4', [1.0, 5.0], [9.0])
    # The 9 s crossfade cannot exceed the 1 s left-hand shot.
    assert total == pytest.approx(5.0)
    assert starts == pytest.approx([0.0, 0.0])


def test_the_fades_are_appended_to_the_tail_of_the_graph(tmp_path, monkeypatch):
    _ffmpeg_recorder(monkeypatch)
    assert _join(tmp_path / 'j.mp4', [10.0], [], fade_in=1.0, fade_out=2.0, color='white') == (10.0, [0.0])
    graph = (tmp_path / 'join_graph.txt').read_text(encoding='utf-8')
    assert 'fade=t=in:st=0:d=1.000000:color=white' in graph
    assert 'fade=t=out:st=8.000000:d=2.000000:color=white' in graph


# ── assemble ──────────────────────────────────────────────────────────────


@pytest.fixture
def rig(tmp_path, monkeypatch):
    """Stub every leg `assemble` delegates to and record what it was handed."""
    calls = {'conform': [], 'still': [], 'dive': [], 'ramp': [], 'overlay': [], 'join': [], 'seal': []}
    scratch = tmp_path / 'scratch'
    scratch.mkdir()
    monkeypatch.setattr(va.video_audio, '_scratch', lambda: str(scratch))

    def join(parts, durations, xfades, out, size, fps, fade_in, fade_out, color, draft, log):
        calls['join'].append({'parts': list(parts), 'durations': list(durations), 'xfades': list(xfades)})
        with open(out, 'wb') as fh:
            fh.write(b'0' * 2048)
        return float(sum(durations)), [0.0] * len(parts)

    monkeypatch.setattr(
        va, '_conform_clip', lambda src, out, s, f, trim, d, log: calls['conform'].append((src, trim, d)) or out
    )
    monkeypatch.setattr(
        va, '_still_clip', lambda img, out, s, f, hold, d, log: calls['still'].append((img, hold, d)) or out
    )
    monkeypatch.setattr(
        va,
        '_dive_zoom',
        lambda src, out, s, f, opts, d, log: (
            calls['dive'].append(opts) or out,
            {'zoom_end': 2.0, 'frames': 48, 's_measured': 1.9},
        ),
    )
    monkeypatch.setattr(
        va, '_speed_ramp', lambda src, out, s, f, tail, end, d, log: (calls['ramp'].append((tail, end)) or out, 7)
    )
    monkeypatch.setattr(
        va.video_overlay,
        'composite',
        lambda src, record, out, draft=False, log=None: calls['overlay'].append((record, draft)) or out,
    )
    monkeypatch.setattr(va, '_join_and_fade', join)
    monkeypatch.setattr(va, '_probe', lambda path: (1920, 1080, 24.0, 2.0, 48))
    monkeypatch.setattr(va._seal, 'seal', lambda path, **kw: calls['seal'].append(path))
    return calls


def _clip_on_disk(tmp_path, name='a.mp4'):
    p = tmp_path / name
    p.write_bytes(b'0' * 2048)
    return str(p)


@pytest.mark.parametrize('shotlist', [{'shots': []}, None])
def test_a_shot_list_with_no_shots_is_refused(tmp_path, rig, shotlist):
    with pytest.raises(ValueError, match='shot list has no shots'):
        va.assemble(shotlist, str(tmp_path / 'out.mp4'))


def test_a_missing_clip_and_a_missing_still_name_their_shot(tmp_path, rig):
    with pytest.raises(ValueError, match=r'shot 0: clip not found'):
        va.assemble({'shots': [{'path': str(tmp_path / 'gone.mp4')}]}, str(tmp_path / 'out.mp4'))
    with pytest.raises(ValueError, match=r'shot 1: still not found'):
        va.assemble(
            {'shots': [{'path': _clip_on_disk(tmp_path)}, {'still': str(tmp_path / 'gone.png')}]},
            str(tmp_path / 'out.mp4'),
        )


def test_the_receipt_describes_every_shot_and_the_whole_programme(tmp_path, rig):
    src = _clip_on_disk(tmp_path)
    still = tmp_path / 'title.png'
    still.write_bytes(b'0' * 16)
    out = tmp_path / 'deliver' / 'out.mp4'
    logged = []

    receipt = va.assemble(
        {
            'fps': 24,
            'size': [1920, 1080],
            'fade_in_s': 1.0,
            'fade_out_s': 2.0,
            'shots': [{'path': src, 'trim': [0, 3.0], 'xfade_s': 0.4}, {'still': str(still), 'hold_s': 5.0}],
        },
        str(out),
        log=logged.append,
    )

    assert [r['src'] for r in receipt['shots']] == [src, str(still)]
    assert receipt['shots'][0]['dur_in'] == 2.0  # _probe's duration
    assert receipt['shots'][1]['dur_in'] == 5.0  # the still's hold_s
    assert all(r['dur_out'] == 2.0 for r in receipt['shots'])  # 48 frames / 24 fps
    assert all(r['ramp_added_frames'] == 0 and r['joined_at'] == 0.0 for r in receipt['shots'])
    assert 'dive_zoom' not in receipt['shots'][0]
    assert receipt['total_s'] == 2.0
    assert (receipt['fade_in_s'], receipt['fade_out_s']) == (1.0, 2.0)
    assert receipt['audio'] is None
    assert receipt['out'] == str(out)
    assert (receipt['fps'], receipt['size'], receipt['draft']) == (24.0, [1920, 1080], False)
    assert isinstance(receipt['seconds'], float)

    assert rig['conform'] == [(src, [0, 3.0], False)]
    assert rig['still'] == [(str(still), 5.0, False)]
    assert rig['join'][0]['xfades'] == [0.4, 0.0]
    assert rig['seal'] == [str(out)]
    assert out.exists()  # the joined file was moved into place
    assert any(m.startswith('receipt: ') for m in logged)
    assert 'shot 0: a.mp4  2.000s in -> 2.000s out (+0 ramp frames)' in logged
    assert list((tmp_path / 'scratch').iterdir()) == []  # the scratch tree is always torn down


def test_a_shot_can_dive_then_ramp_then_take_an_overlay(tmp_path, rig):
    overlay = tmp_path / 'ov.json'
    overlay.write_text(json.dumps({'items': ['title']}), encoding='utf-8')
    receipt = va.assemble(
        {
            'shots': [
                {
                    'path': _clip_on_disk(tmp_path),
                    'dive_zoom': {'zoom_end': 2.0},
                    'speed_ramp': {'tail_s': 0.8, 'end_speed': 0.12},
                    'overlay': str(overlay),
                    'overlay_draft': True,
                }
            ]
        },
        str(tmp_path / 'out.mp4'),
    )
    assert rig['dive'] == [{'zoom_end': 2.0}]
    assert rig['ramp'] == [(0.8, 0.12)]
    assert rig['overlay'] == [({'items': ['title']}, True)]
    assert receipt['shots'][0]['dive_zoom'] == {'zoom_end': 2.0, 'frames': 48, 's_measured': 1.9}
    assert receipt['shots'][0]['ramp_added_frames'] == 7
    # The overlay stage is the one that gets joined.
    assert rig['join'][0]['parts'][0].endswith('shot00_over.mp4')


def test_a_blank_ramp_spec_and_an_empty_overlay_record_are_harmless(tmp_path, rig):
    va.assemble(
        {'shots': [{'path': _clip_on_disk(tmp_path), 'speed_ramp': {'tail_s': None}, 'overlay': {}}]},
        str(tmp_path / 'out.mp4'),
        draft=True,
    )
    # A ramp spec with no numbers in it means no tail and full speed.
    assert rig['ramp'] == [(0.0, 1.0)]
    assert rig['overlay'] == []  # an empty record is falsy: no overlay pass is made
    assert rig['conform'][0][2] is True


def test_a_clip_whose_frames_cannot_be_counted_falls_back_to_its_duration(tmp_path, rig, monkeypatch):
    monkeypatch.setattr(va, '_probe', lambda path: (1920, 1080, 24.0, 3.25, 0))
    receipt = va.assemble({'shots': [{'path': _clip_on_disk(tmp_path)}]}, str(tmp_path / 'out.mp4'))
    assert receipt['shots'][0]['dur_out'] == 3.25
    assert receipt['total_s'] == 3.25


def test_an_audio_spec_builds_a_track_and_muxes_it_over_the_join(tmp_path, rig, monkeypatch):
    built = {}
    monkeypatch.setattr(
        va.video_audio,
        'build_track',
        lambda spec, total, wav, log=None: built.update(spec=spec, total=total, wav=wav) or {'beds': 1},
    )
    monkeypatch.setattr(va.video_audio, 'mux', lambda video, wav, out, log=None: built.update(out=out) or True)
    receipt = va.assemble(
        {'shots': [{'path': _clip_on_disk(tmp_path)}], 'audio': {'music': 'calm'}}, str(tmp_path / 'out.mp4')
    )
    assert built['spec'] == {'music': 'calm'}
    assert built['total'] == 2.0
    assert built['wav'].endswith('track.wav')
    assert built['out'] == str(tmp_path / 'out.mp4')
    assert receipt['audio'] == {'beds': 1}

    # …and a mux that produces nothing takes the programme down with it.
    monkeypatch.setattr(va.video_audio, 'mux', lambda *a, **kw: False)
    with pytest.raises(RuntimeError, match='audio mux produced nothing'):
        va.assemble(
            {'shots': [{'path': _clip_on_disk(tmp_path)}], 'audio': {'music': 'calm'}}, str(tmp_path / 'out.mp4')
        )


# ── the selftest helpers ──────────────────────────────────────────────────


def test_frames_yields_every_decoded_frame_and_always_releases(monkeypatch):
    cap = FakeCap([_frame(fill=i) for i in range(3)])
    monkeypatch.setattr(va.cv2, 'VideoCapture', lambda _src: cap)
    got = list(va._frames('/a.mp4'))
    assert [int(f[0, 0, 0]) for f in got] == [0, 1, 2]
    assert cap.released


def test_luma_weights_the_channels_like_rec601():
    assert va._luma(_frame(2, 2, fill=0)) == pytest.approx(0.0)
    assert va._luma(_frame(2, 2, fill=255)) == pytest.approx(255.0)
    red = np.zeros((2, 2, 3), np.uint8)
    red[:, :, 2] = 255
    assert va._luma(red) == pytest.approx(0.299 * 255)
