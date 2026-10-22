# SPDX-FileCopyrightText: 2026 Zygomatic
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Coverage tests for :mod:`zyg_workflows.video_overlay`.

Nothing here runs ffmpeg or ffprobe: ``video_overlay._run`` is the module's
single process door, so a fake that answers ffprobe with canned JSON and
ffmpeg with a return code exercises the whole compositor offline.  The only
real decoder used is cv2's pure-array side, over synthetic numpy frames.
"""

from __future__ import annotations

import json
import os
from fractions import Fraction
from types import SimpleNamespace

import cv2
import numpy as np
import pytest
from PIL import Image

from zyg_workflows import video_overlay as vov


# ---- fakes ---------------------------------------------------------------


class _Proc:
    """Stand-in for a finished subprocess.CompletedProcess."""

    def __init__(self, returncode=0, stdout='', stderr=''):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def _probe_payload(audio=False, fmt_duration='2.0', **over):
    """An ffprobe -of json payload; a ``None`` override drops that key entirely."""
    stream = {
        'codec_type': 'video',
        'width': 640,
        'height': 360,
        'r_frame_rate': '24/1',
        'avg_frame_rate': '24/1',
        'duration': '2.0',
        'nb_frames': '48',
        'pix_fmt': 'yuv420p',
    }
    stream.update(over)
    streams = [{k: v for k, v in stream.items() if v is not None}]
    if audio:
        streams.append({'codec_type': 'audio'})
    return {'streams': streams, 'format': {} if fmt_duration is None else {'duration': fmt_duration}}


class _FakeRun:
    """Answer ffprobe with JSON, ffmpeg with a return code; record every call."""

    def __init__(self, payload=None, ffmpeg_rc=0, ffmpeg_stderr=''):
        self.stdout = json.dumps(payload if payload is not None else _probe_payload())
        self.ffmpeg_rc = ffmpeg_rc
        self.ffmpeg_stderr = ffmpeg_stderr
        self.calls = []

    def __call__(self, cmd, **kw):
        self.calls.append(list(cmd))
        if cmd[0] == vov.FFPROBE:
            return _Proc(0, self.stdout)
        return _Proc(self.ffmpeg_rc, '', self.ffmpeg_stderr)

    @property
    def ffmpeg_cmd(self):
        return [c for c in self.calls if c[0] == vov.FFMPEG][-1]


class _FakeCap:
    """Minimal cv2.VideoCapture over a list of numpy frames."""

    def __init__(self, frames, fps=24.0, opened=True):
        self._frames = list(frames)
        self._fps = fps
        self._opened = opened
        self.released = False

    def isOpened(self):
        return self._opened

    def get(self, _prop):
        return self._fps

    def read(self):
        return (True, self._frames.pop(0)) if self._frames else (False, None)

    def release(self):
        self.released = True


@pytest.fixture
def lab(tmp_path, monkeypatch):
    """A base video, three element kinds, a fake _run and a log sink."""
    lab = SimpleNamespace()
    for attr, name in (('base', 'base.mp4'), ('mov', 'dust.mov'), ('webm', 'dust.webm')):
        (tmp_path / name).write_bytes(b'')
        setattr(lab, attr, str(tmp_path / name))
    lab.seq = str(tmp_path / 'seq')
    os.makedirs(lab.seq)
    for n in (1, 2, 3):
        Image.new('RGBA', (64, 32), (1, 2, 3, 4)).save(os.path.join(lab.seq, 'dust%04d.png' % n))
    lab.out = str(tmp_path / 'out.mp4')
    lab.lines = []
    lab.say = lab.lines.append
    lab.run = _FakeRun()
    monkeypatch.setattr(vov, '_run', lab.run)
    lab.graph = lambda: [t for t in lab.lines if t.startswith('filtergraph:')][0]
    return lab


# ---- _run and the pure maths -------------------------------------------------


def test_run_captures_text_output(monkeypatch):
    seen = []
    monkeypatch.setattr(vov.subprocess, 'run', lambda cmd, **kw: seen.append((cmd, kw)) or 'done')
    assert vov._run(['ffprobe', '-x'], cwd='/tmp') == 'done'
    assert seen == [(['ffprobe', '-x'], {'capture_output': True, 'text': True, 'cwd': '/tmp'})]


@pytest.mark.parametrize(
    ('anchor', 'expected'),
    [
        ('top-left', (10, 40)),
        ('center', (5, 30)),
        ('bottom-center', (5, 20)),
        ('nonsense-falls-back', (5, 20)),
    ],
)
def test_anchor_xy(anchor, expected):
    assert vov._anchor_xy(anchor, 100, 200, 0.1, 0.2, 10, 20) == expected


@pytest.mark.parametrize(
    ('anchor', 'expected'),
    [
        ('top-left', ('W*0.1', 'H*0.2')),
        ('center', ('W*0.1-w/2', 'H*0.2-h/2')),
        ('bottom-center', ('W*0.1-w/2', 'H*0.2-h')),
    ],
)
def test_anchor_expr_matches_anchor_xy_shape(anchor, expected):
    assert vov._anchor_expr(anchor, 0.1, 0.2) == expected


@pytest.mark.parametrize('n', [0, 1, 2, 3, 4, 5, 7, 36.4])
def test_even_is_even_and_near(n):
    got = vov._even(n)
    assert got % 2 == 0
    assert abs(got - n) <= 1


def test_esc_escapes_filtergraph_specials():
    assert vov._esc("/tmp/a:b'c\\d") == "/tmp/a\\:b\\'c\\\\d"


# ---- _probe_video ------------------------------------------------------------


def test_probe_video_reads_geometry_rate_and_audio(monkeypatch):
    run = _FakeRun(_probe_payload(audio=True))
    monkeypatch.setattr(vov, '_run', run)
    got = vov._probe_video('/x/base.mp4')
    assert (got['width'], got['height']) == (640, 360)
    assert got['fps'] == Fraction(24)
    assert got['duration'] == 2.0
    assert got['nb_frames'] == 48
    assert got['has_audio'] is True
    assert got['pix_fmt'] == 'yuv420p'
    assert run.calls[0][0] == vov.FFPROBE
    assert run.calls[0][-1] == '/x/base.mp4'


@pytest.mark.parametrize(
    ('payload', 'field', 'expected'),
    [
        # r_frame_rate of 0 falls back to avg_frame_rate, and its absence to 24
        (_probe_payload(r_frame_rate='0/1', avg_frame_rate='30000/1001'), 'fps', Fraction(30000, 1001)),
        (_probe_payload(r_frame_rate=None, avg_frame_rate=None), 'fps', Fraction(24)),
        # the duration comes from the stream, then the container, then the frames
        (_probe_payload(duration=None), 'duration', 2.0),
        (_probe_payload(duration=None, fmt_duration='3.5'), 'duration', 3.5),
        (_probe_payload(duration=None, fmt_duration=None), 'duration', 2.0),
        (_probe_payload(duration='N/A', fmt_duration=None, nb_frames='N/A'), 'duration', None),
        (_probe_payload(nb_frames=None), 'nb_frames', None),
    ],
)
def test_probe_video_reads_rate_and_duration_defensively(monkeypatch, payload, field, expected):
    monkeypatch.setattr(vov, '_run', _FakeRun(payload))
    assert vov._probe_video('b.mp4')[field] == expected


@pytest.mark.parametrize(
    ('run', 'match'),
    [
        (lambda cmd, **kw: _Proc(1, '', 'boom  '), 'ffprobe failed on b.mp4: boom'),
        (_FakeRun({'streams': [{'codec_type': 'audio'}], 'format': {}}), 'no video stream'),
    ],
)
def test_probe_video_rejects_what_it_cannot_use(monkeypatch, run, match):
    monkeypatch.setattr(vov, '_run', run)
    with pytest.raises(RuntimeError, match=match):
        vov._probe_video('b.mp4')


# ---- _probe_png_dir / _element_facts -------------------------------------


def test_probe_png_dir_builds_a_printf_pattern(lab):
    Image.new('RGBA', (8, 8)).save(os.path.join(lab.seq, 'other05.png'))  # decoy: wrong stem
    got = vov._probe_png_dir(lab.seq, 24)
    assert (got['width'], got['height']) == (64, 32)
    assert got['fps'] == Fraction(24)
    assert got['nb_frames'] == 3
    assert got['duration'] == pytest.approx(0.125)
    assert got['first_index'] == 1
    assert got['has_audio'] is False
    assert got['pattern'] == os.path.join(lab.seq, 'dust%04d.png')


@pytest.mark.parametrize(
    ('names', 'match'),
    [((), 'no PNGs in element dir'), (('frame.png',), 'not a numbered sequence')],
)
def test_probe_png_dir_rejects_a_dir_it_cannot_read(tmp_path, names, match):
    d = tmp_path / 'elem'
    d.mkdir()
    for name in names:
        Image.new('RGBA', (4, 4)).save(d / name)
    with pytest.raises(RuntimeError, match=match):
        vov._probe_png_dir(str(d), 24)


def test_element_facts_labels_each_kind(lab):
    assert vov._element_facts(lab.seq, 24)['kind'] == 'dir'
    assert vov._element_facts(lab.webm, 24)['kind'] == 'webm'
    assert vov._element_facts(lab.mov, 24)['kind'] == 'video'


def test_element_facts_raises_on_a_missing_element(tmp_path):
    with pytest.raises(RuntimeError, match='element not found'):
        vov._element_facts(str(tmp_path / 'gone.mov'), 24)


# ---- _horizon_track ----------------------------------------------------------


def _structured_frame(shift=0):
    """A 200x100 BGR frame whose horizon band carries real structure."""
    g = np.zeros((100, 200, 3), np.uint8)
    for col in range(0, 200, 20):
        g[:, (col + shift) % 200 : (col + shift) % 200 + 6] = 220
    return g


def test_horizon_track_measures_absolute_displacement(monkeypatch):
    cap = _FakeCap([_structured_frame(0), _structured_frame(4), _structured_frame(8)])
    monkeypatch.setattr(cv2, 'VideoCapture', lambda _p: cap)
    lines = []
    track = vov._horizon_track('/x/base.mp4', log=lines.append)
    assert len(track) == 3
    assert track[0] == (0.0, 0.0, 0.0)
    assert track[1][0] == pytest.approx(1 / 24.0)
    assert track[2][0] == pytest.approx(2 / 24.0)
    assert all(len(t) == 3 for t in track)
    assert cap.released is True
    assert lines and lines[0].startswith('horizon track: 3 frames')


def test_horizon_track_without_a_log_is_silent(monkeypatch):
    cap = _FakeCap([_structured_frame(0)], fps=0.0)
    monkeypatch.setattr(cv2, 'VideoCapture', lambda _p: cap)
    assert vov._horizon_track('/x/base.mp4') == [(0.0, 0.0, 0.0)]


def test_horizon_track_raises_when_cv2_cannot_open(monkeypatch):
    monkeypatch.setattr(cv2, 'VideoCapture', lambda _p: _FakeCap([], opened=False))
    with pytest.raises(RuntimeError, match='cv2 could not open'):
        vov._horizon_track('/x/base.mp4')


# ---- composite: record handling ----------------------------------------------


def test_composite_reads_the_record_from_a_json_file(lab):
    rec = os.path.join(os.path.dirname(lab.base), 'placement.json')
    with open(rec, 'w', encoding='utf-8') as fh:
        json.dump({'layers': []}, fh)
    receipt = vov.composite(lab.base, rec, lab.out, log=lab.say)
    assert receipt['layers'] == []
    assert receipt['out'] == os.path.abspath(lab.out)
    assert receipt['draft'] is False
    assert (receipt['width'], receipt['height'], receipt['fps']) == (640, 360, 24.0)
    assert receipt['frames'] == 48
    assert isinstance(receipt['seconds'], float)


@pytest.mark.parametrize('record', [['not', 'a', 'dict'], '/does/not/exist.json', 7])
def test_composite_rejects_a_non_dict_record(lab, record):
    with pytest.raises(TypeError, match='record must be a dict'):
        vov.composite(lab.base, record, lab.out)


def test_composite_without_a_log_still_renders(lab):
    assert vov.composite(lab.base, {'layers': []}, lab.out)['frames'] == 48
    assert lab.lines == []


# ---- composite: the filtergraph a layer produces -----------------------------


def test_composite_builds_every_colour_stage_for_a_rich_layer(lab):
    layer = {
        'element': lab.mov,
        'x': 0.25,
        'y': 0.75,
        'anchor': 'center',
        'height': 0.5,
        'start_s': 0.5,
        'end_s': 1.5,
        'element_offset_s': 0.25,
        'loop': True,
        'speed': 2.0,
        'opacity': 0.5,
        'saturation': 1.5,
        'flip_h': True,
        'tint': [0.9, 0.7, 0.45],
        'warm': [1.0, 0.93, 0.8],
        'blur': 2.0,
    }
    receipt = vov.composite(lab.base, {'layers': [layer]}, lab.out, log=lab.say)
    graph = lab.graph()
    assert 'setpts=PTS/2.0' in graph
    assert 'premultiply=inplace=1' in graph
    assert 'unpremultiply=inplace=1' in graph
    assert 'hflip' in graph
    assert graph.count('colorchannelmixer=') == 3  # saturation, tint, warm+opacity
    assert 'gblur=sigma=2.0' in graph
    assert 'setpts=PTS+0.5/TB' in graph
    assert "enable='between(t,0.5,1.5)'" in graph
    assert 'overlay@L1=x=W*0.25-w/2:y=H*0.75-h/2' in graph
    assert '[b1]format=yuv420p[vout]' in graph

    cmd = lab.run.ffmpeg_cmd
    assert cmd[:5] == [vov.FFMPEG, '-hide_banner', '-v', 'error', '-y']
    assert cmd[cmd.index('-stream_loop') + 1] == '-1'
    assert cmd[cmd.index('-ss') + 1] == '0.250000'
    assert cmd[cmd.index('-i', cmd.index('-ss')) + 1] == lab.mov
    assert ['-c:v', 'libx264'] == cmd[cmd.index('-c:v') : cmd.index('-c:v') + 2]
    assert ['-crf', '14', '-preset', 'medium'] == cmd[cmd.index('-crf') : cmd.index('-crf') + 4]
    assert cmd[cmd.index('-frames:v') + 1] == '50'
    assert cmd[-1] == lab.out
    assert '-an' in cmd

    (one,) = receipt['layers']
    assert one['element'] == lab.mov
    assert one['visible'] == [0.5, 1.5]
    assert one['blend'] == 'normal'
    assert one['tracked'] is False
    assert one['height_px_end'] is None
    assert one['element_fps'] == 24.0
    x, y, w, h = one['placed_px']
    assert (w, h) == (320, 180)
    assert (x, y) == (0, 180)


def test_composite_leaves_a_plain_layer_unfiltered(lab):
    layer = {'element': lab.mov, 'speed': 0.0, 'start_s': 0.0, 'end_s': None}
    vov.composite(lab.base, {'layers': [layer]}, lab.out, log=lab.say)
    graph = lab.graph()
    assert 'setpts' not in graph  # speed 0 is read as 1.0, start_s 0 adds no shift
    assert 'colorchannelmixer' not in graph
    assert 'gblur' not in graph
    assert 'hflip' not in graph
    assert "enable='between(t,0.0,2.0)'" in graph  # end_s None -> base duration


def test_composite_loops_a_png_sequence_from_an_offset_frame(lab):
    layer = {'element': lab.seq, 'fps': 12, 'element_offset_s': 0.5, 'loop': True}
    receipt = vov.composite(lab.base, {'layers': [layer]}, lab.out, log=lab.say)
    cmd = lab.run.ffmpeg_cmd
    assert cmd[cmd.index('-loop') + 1] == '1'
    assert cmd[cmd.index('-framerate') + 1] == '12'
    assert cmd[cmd.index('-start_number') + 1] == '7'  # first_index 1 + 0.5 s * 12 fps
    assert cmd[cmd.index('-start_number') + 2 : cmd.index('-start_number') + 4] == [
        '-i',
        os.path.join(lab.seq, 'dust%04d.png'),
    ]
    assert receipt['layers'][0]['element_fps'] == 12.0


def test_composite_does_not_loop_a_sequence_when_asked_not_to(lab):
    vov.composite(lab.base, {'layers': [{'element': lab.seq, 'loop': False}]}, lab.out, log=lab.say)
    assert '-loop' not in lab.run.ffmpeg_cmd
    assert '-stream_loop' not in lab.run.ffmpeg_cmd


def test_composite_forces_the_vp9_decoder_before_a_webm_input(lab):
    vov.composite(lab.base, {'layers': [{'element': lab.webm, 'loop': False}]}, lab.out, log=lab.say)
    cmd = lab.run.ffmpeg_cmd
    assert cmd[cmd.index('-c:v', 0) : cmd.index('-c:v', 0) + 2] == ['-c:v', 'libvpx-vp9']
    assert cmd.index('-c:v') < cmd.index('-i', cmd.index('-c:v'))


# ---- composite: screen blend, ramps, tracking, draft, audio ------------------

# A screen blend is only kept for a fixed-size element wholly inside the frame.
_SCREEN_FIT = {'anchor': 'top-left', 'x': 0.0, 'y': 0.0, 'height': 0.25, 'blend': 'screen'}


def test_composite_pads_and_blends_a_fitting_screen_layer(lab):
    layer = dict(_SCREEN_FIT, element=lab.mov, start_s=0.5)
    receipt = vov.composite(lab.base, {'layers': [layer]}, lab.out, log=lab.say)
    graph = lab.graph()
    assert 'pad=640:360:0:0:color=0x00000000' in graph
    assert 'blend@L1=all_mode=screen:shortest=0:' in graph
    assert 'overlay@L1' not in graph
    assert receipt['layers'][0]['blend'] == 'screen'
    assert not [t for t in lab.lines if 'falling back' in t]


@pytest.mark.parametrize(
    ('extra', 'why'),
    [
        ({'anchor': 'center', 'x': 0.0, 'y': 0.0}, 'element hangs off the frame'),
        ({'height_end': 0.5}, 'a ramp has no fixed size'),
    ],
)
def test_composite_falls_back_from_screen_to_overlay(lab, extra, why):
    layer = {'element': lab.mov, 'blend': 'screen', 'height': 0.25, 'start_s': 0.0, 'end_s': 2.0}
    layer.update(extra)
    receipt = vov.composite(lab.base, {'layers': [layer]}, lab.out, log=lab.say)
    assert [t for t in lab.lines if 'falling back' in t], why
    assert receipt['layers'][0]['blend'] == 'normal'
    assert 'blend@L1' not in lab.graph()
    assert 'overlay@L1' in lab.graph()


def test_composite_ramps_the_height_at_the_end_of_the_chain(lab):
    layer = {'element': lab.mov, 'height': 0.25, 'height_end': 0.5, 'start_s': 0.5, 'end_s': 1.5}
    receipt = vov.composite(lab.base, {'layers': [layer]}, lab.out, log=lab.say)
    graph = lab.graph()
    assert 'scale=-2:180' in graph  # premultiplied pass uses the LARGEST size
    assert "h='trunc(max(2,90.0+(90.0)*clip((t-0.5)/1.0,0,1))/2)*2':eval=frame" in graph
    assert graph.index('eval=frame') > graph.index('setpts=PTS+0.5/TB')
    assert receipt['layers'][0]['height_px_end'] == 180


def test_composite_ignores_a_ramp_without_a_window(lab):
    layer = {'element': lab.mov, 'height': 0.25, 'height_end': 0.5, 'start_s': 1.0, 'end_s': 1.0}
    receipt = vov.composite(lab.base, {'layers': [layer]}, lab.out, log=lab.say)
    assert 'eval=frame' not in lab.graph()
    assert receipt['layers'][0]['height_px_end'] is None


def test_composite_tracks_a_horizon_layer_with_sendcmd(lab, monkeypatch):
    cap = _FakeCap([_structured_frame(0), _structured_frame(3)])
    monkeypatch.setattr(cv2, 'VideoCapture', lambda _p: cap)
    layer = {'element': lab.mov, 'track': 'horizon', 'anchor': 'top-left', 'x': 0.1, 'y': 0.1}
    receipt = vov.composite(lab.base, {'layers': [layer]}, lab.out, log=lab.say)
    graph = lab.graph()
    assert "sendcmd=f='" in graph
    assert 'track.cmd' in graph
    assert receipt['layers'][0]['tracked'] is True
    assert [t for t in lab.lines if t.startswith('horizon track:')]


def test_composite_refuses_screen_blend_on_a_tracked_layer(lab, monkeypatch):
    """A tracked layer keeps its track and loses the screen blend, never the reverse."""
    monkeypatch.setattr(cv2, 'VideoCapture', lambda _p: _FakeCap([_structured_frame(0)]))
    layer = dict(_SCREEN_FIT, element=lab.mov, track='horizon')
    receipt = vov.composite(lab.base, {'layers': [layer]}, lab.out, log=lab.say)
    assert [t for t in lab.lines if 'falling back' in t]
    assert receipt['layers'][0]['blend'] == 'normal'
    assert receipt['layers'][0]['tracked'] is True


def test_composite_draft_scales_the_base_and_uses_a_fast_preset(lab):
    record = {'layers': [{'element': lab.mov}], 'draft': {'width': 300, 'fps': 10}}
    receipt = vov.composite(lab.base, record, lab.out, draft=True, log=lab.say)
    assert 'scale=300:168' in lab.graph()
    assert 'fps=10,format=rgba' in lab.graph()
    cmd = lab.run.ffmpeg_cmd
    assert ['-crf', '28', '-preset', 'ultrafast'] == cmd[cmd.index('-crf') : cmd.index('-crf') + 4]
    assert cmd[cmd.index('-frames:v') + 1] == '22'
    assert receipt['draft'] is True


def test_composite_uses_the_default_draft_geometry(lab):
    vov.composite(lab.base, {'layers': []}, lab.out, draft=True, log=lab.say)
    assert 'scale=480:270' in lab.graph()
    assert 'fps=12,format=rgba' in lab.graph()


def test_composite_copies_the_base_audio_when_there_is_some(lab, monkeypatch):
    run = _FakeRun(_probe_payload(audio=True))
    monkeypatch.setattr(vov, '_run', run)
    vov.composite(lab.base, {'layers': []}, lab.out, log=lab.say)
    cmd = run.ffmpeg_cmd
    second = cmd.index('-map', cmd.index('-map') + 1)
    assert cmd[second : second + 4] == ['-map', '0:a', '-c:a', 'copy']
    assert '-an' not in cmd


def test_composite_stacks_three_layers_onto_one_chain(lab):
    layers = [{'element': lab.mov}, {'element': lab.webm}, {'element': lab.seq}]
    receipt = vov.composite(lab.base, {'layers': layers}, lab.out, log=lab.say)
    graph = lab.graph()
    assert '[b0][L1]' in graph
    assert '[b1][L2]' in graph
    assert '[b2][L3]' in graph
    assert '[b3]format=yuv420p[vout]' in graph
    assert len(receipt['layers']) == 3


def test_composite_raises_when_ffmpeg_fails(lab, monkeypatch):
    monkeypatch.setattr(vov, '_run', _FakeRun(ffmpeg_rc=1, ffmpeg_stderr='  no such filter  '))
    with pytest.raises(RuntimeError, match='ffmpeg failed'):
        vov.composite(lab.base, {'layers': [{'element': lab.mov}]}, lab.out, log=lab.say)


def test_composite_cleans_up_its_tempdir(lab, monkeypatch):
    seen = []
    real = vov.tempfile.mkdtemp
    monkeypatch.setattr(vov.tempfile, 'mkdtemp', lambda **kw: seen.append(real(**kw)) or seen[-1])
    vov.composite(lab.base, {'layers': [{'element': lab.mov}]}, lab.out, log=lab.say)
    assert seen and not os.path.exists(seen[0])


# ---- selftest helpers --------------------------------------------------------


def test_frame_at_returns_a_float_rgb_array(tmp_path, monkeypatch):
    png = str(tmp_path / 'f.png')
    calls = []

    def fake(cmd, **kw):
        calls.append(cmd)
        Image.new('RGB', (4, 3), (10, 20, 30)).save(cmd[-1])
        return _Proc(0)

    monkeypatch.setattr(vov, '_run', fake)
    arr = vov._frame_at('/x/base.mp4', 1.5, png)
    assert arr.shape == (3, 4, 3)
    assert arr.dtype == np.float32
    assert arr[0, 0].tolist() == [10.0, 20.0, 30.0]
    assert calls[0][calls[0].index('-ss') + 1] == '1.500'
    assert calls[0][calls[0].index('-frames:v') + 1] == '1'


@pytest.mark.parametrize('rc', [1, 0])
def test_frame_at_raises_without_a_frame(tmp_path, monkeypatch, rc):
    monkeypatch.setattr(vov, '_run', lambda cmd, **kw: _Proc(rc, '', 'seek past end'))
    with pytest.raises(RuntimeError, match='frame extract failed at t=2.0'):
        vov._frame_at('/x/base.mp4', 2.0, str(tmp_path / 'missing.png'))


@pytest.mark.parametrize(
    ('element', 'forced'),
    [('/x/dust.webm', True), ('/x/dust.mov', False)],
)
def test_ref_box_diff_composites_one_element_frame(tmp_path, monkeypatch, element, forced):
    calls = []

    def fake(cmd, **kw):
        calls.append(cmd)
        Image.new('RGBA', (8, 8), (255, 0, 0, 255)).save(cmd[-1])
        return _Proc(0)

    monkeypatch.setattr(vov, '_run', fake)
    got = vov._ref_box_diff(element, 0.25, (0, 0, 4, 4), 0.0, [1.0, 1.0, 1.0], str(tmp_path / 'r.png'))
    assert got == pytest.approx(85.0)
    assert ('libvpx-vp9' in calls[0]) is forced
    assert calls[0][calls[0].index('-ss') + 1] == '0.2500'
    assert calls[0][calls[0].index('-pix_fmt') + 1] == 'rgba'


def test_ref_box_diff_raises_when_the_decode_fails(tmp_path, monkeypatch):
    monkeypatch.setattr(vov, '_run', lambda cmd, **kw: _Proc(2, '', 'bad element'))
    with pytest.raises(RuntimeError, match='reference decode failed: bad element'):
        vov._ref_box_diff('/x/e.mov', 0.0, (0, 0, 2, 2), 0.0, [1.0, 1.0, 1.0], str(tmp_path / 'r.png'))


def test_module_constants_point_at_the_vfx_library():
    assert vov.VFX.endswith(os.path.join('asset_libraries', 'vfx_volumes'))
    assert vov.GRENADE_MOV.endswith('grenadedustimpactvdb_4k.mov')
    assert vov.GRENADE_WEBM.endswith('grenadedustimpactvdb_4k.webm')
    assert (vov.MIN_BOX_DIFF, vov.REF_TOL) == (5.0, 0.15)
    assert vov.DRAFT_DEFAULTS == {'width': 480, 'fps': 12}
