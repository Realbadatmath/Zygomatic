# SPDX-FileCopyrightText: 2026 Zygomatic
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Coverage tests for zyg_zero.zpub_cinema.hls.

Everything here runs offline: ffprobe is replaced by a fake ``_run``, ffmpeg by a
fake ``subprocess.Popen``, the wall clock by a fake ``time`` and every path the
module derives by ``tmp_path``.
"""

import io
import os
import signal
import types

import pytest

from zyg_zero.zpub_cinema import hls
from zyg_zero.zpub_cinema.constants import FFMPEG


# ── doubles ───────────────────────────────────────────────────────────────────
class FakeProc:
    """A stand-in for ``subprocess.Popen`` with a scripted ``poll()``."""

    def __init__(self, polls=(None,), stderr=b'', kill_raises=False):
        self._polls = list(polls)
        self.signals = []
        self.kills = 0
        self.waits = []
        self.stderr = io.BytesIO(stderr)
        self._kill_raises = kill_raises

    def poll(self):
        if len(self._polls) > 1:
            return self._polls.pop(0)
        return self._polls[0]

    def send_signal(self, sig):
        self.signals.append(sig)

    def kill(self):
        self.kills += 1
        if self._kill_raises:
            raise OSError('no such process')

    def wait(self, timeout=None):
        self.waits.append(timeout)
        return 0


class RefusingProc(FakeProc):
    """A process that cannot be signalled — the governor must give up on it."""

    def send_signal(self, sig):
        raise OSError('gone')


class FakeClock:
    """``time`` replacement whose ``sleep`` moves the clock (and may run a hook)."""

    def __init__(self, start=1_000_000.0, on_sleep=None):
        self.now = float(start)
        self.on_sleep = on_sleep
        self.sleeps = []

    def time(self):
        return self.now

    def sleep(self, dt):
        self.sleeps.append(dt)
        self.now += dt
        if self.on_sleep is not None:
            self.on_sleep(self)


class FakeShutil:
    """``shutil`` replacement: scripted ``disk_usage``, recorded ``rmtree``."""

    def __init__(self, free=10**14, raises=False):
        self.free = free
        self.raises = raises
        self.rmtrees = []

    def disk_usage(self, path):
        if self.raises:
            raise OSError('stat failed')
        return types.SimpleNamespace(total=self.free, used=0, free=self.free)

    def rmtree(self, path, ignore_errors=False):
        self.rmtrees.append(path)
        import shutil as _real

        _real.rmtree(path, ignore_errors=ignore_errors)


def _playlist(out_dir, durations):
    """Write an EVENT playlist listing ``durations`` into ``out_dir``."""
    os.makedirs(out_dir, exist_ok=True)
    body = ['#EXTM3U', '#EXT-X-VERSION:7', '#EXT-X-PLAYLIST-TYPE:EVENT']
    for i, d in enumerate(durations):
        body.append(f'#EXTINF:{d:.3f},')
        body.append(f'seg{i:05d}.m4s')
    with open(os.path.join(out_dir, 'index.m3u8'), 'w', encoding='utf-8') as f:
        f.write('\n'.join(body) + '\n')


@pytest.fixture
def hls_dir(tmp_path, monkeypatch):
    """Point the module's session root at tmp_path and give it an empty registry."""
    root = tmp_path / 'hls'
    root.mkdir()
    monkeypatch.setattr(hls, 'HLS_DIR', str(root))
    monkeypatch.setattr(hls, '_HLS', {})
    monkeypatch.setattr(hls, '_FPS_CACHE', {})
    return root


ITEM = {
    'id': 'it1',
    'path': '/library/Movie (2016)/movie.mkv',
    'duration': 7200.5,
    'height': 2160,
    'audio': [{'default': False}, {'default': True}],
    'subs': [],
}


# ── _video_fps ────────────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    ('rc', 'out', 'expected'),
    [
        (0, '24/1,24/1\n', 24.0),
        (0, '30000/1001,30/1\n', pytest.approx(29.97, abs=0.01)),
        (0, '0/0,abc,25/1\n', 25.0),
        (0, '1/1,1000000/1\n', 0.0),
        (0, '\n', 0.0),
        (1, '', 0.0),
    ],
)
def test_video_fps_reads_the_first_sane_frame_rate(monkeypatch, hls_dir, rc, out, expected):
    calls = []

    def fake_run(cmd, timeout=120):
        calls.append((cmd, timeout))
        return rc, out, ''

    monkeypatch.setattr(hls, '_run', fake_run)
    assert hls._video_fps('/library/a.mkv') == expected
    assert calls[0][0][0] == hls.FFPROBE
    assert '-select_streams' in calls[0][0]
    assert calls[0][1] == 30


def test_video_fps_is_cached_after_the_first_probe(monkeypatch, hls_dir):
    calls = []

    def fake_run(cmd, timeout=120):
        calls.append(cmd)
        return 0, '48/1', ''

    monkeypatch.setattr(hls, '_run', fake_run)
    assert hls._video_fps('/library/b.mkv') == 48.0
    assert hls._video_fps('/library/b.mkv') == 48.0
    assert len(calls) == 1


# ── hls_commands / _hls_tail ──────────────────────────────────────────────────
def _hls_cmds(monkeypatch, item, out_dir, fps=25.0, start=0.0, audio_id=None, burn_sub=''):
    monkeypatch.setattr(hls, '_video_fps', lambda path: fps)
    return hls.hls_commands(item, start, audio_id, burn_sub, out_dir)


def test_hls_commands_replaces_the_pipe_tail_with_an_hls_writer(monkeypatch, tmp_path):
    out_dir = str(tmp_path / 'sess')
    cmds = _hls_cmds(monkeypatch, ITEM, out_dir, fps=25.0)
    # No -c:v copy for this item, so the ladder is GPU → CPU+NVENC → libx264.
    assert len(cmds) == 3
    for cmd in cmds:
        assert cmd[0] == FFMPEG
        assert 'pipe:1' not in cmd
        assert '-movflags' not in cmd
        assert cmd[-1] == os.path.join(out_dir, 'index.m3u8')
        assert cmd[cmd.index('-hls_segment_filename') + 1] == os.path.join(out_dir, 'seg%05d.m4s')
        assert cmd[cmd.index('-f') + 1] == 'hls'
        assert cmd[cmd.index('-hls_time') + 1] == str(hls.HLS_SEG_SECONDS)
        assert cmd[cmd.index('-hls_playlist_type') + 1] == 'event'
        assert cmd[cmd.index('-hls_segment_type') + 1] == 'fmp4'
        assert cmd[cmd.index('-hls_fmp4_init_filename') + 1] == 'init.mp4'
        assert cmd[cmd.index('-hls_flags') + 1] == 'independent_segments'
        # 25 fps * 6 s segments = a 150-frame GOP, enforced on both keyint knobs.
        assert cmd[cmd.index('-g') + 1] == '150'
        assert cmd[cmd.index('-keyint_min') + 1] == '150'
    assert '-hwaccel' in cmds[0] and 'h264_nvenc' in cmds[0]
    assert 'h264_nvenc' in cmds[1] and '-hwaccel' not in cmds[1]
    assert 'libx264' in cmds[2]


# fps 0.0 is "unknown" and falls back to 24; fps 1.0 would give a 6-frame GOP, so the
# floor of 24 frames holds instead.
@pytest.mark.parametrize(('fps', 'gop'), [(0.0, '144'), (1.0, '24'), (23.976, '144'), (25.0, '150'), (60.0, '360')])
def test_hls_commands_gop_follows_the_frame_rate_with_a_floor(monkeypatch, tmp_path, fps, gop):
    cmds = _hls_cmds(monkeypatch, ITEM, str(tmp_path / 'g'), fps=fps)
    assert cmds[0][cmds[0].index('-g') + 1] == gop


def test_hls_commands_keeps_the_remux_step_for_a_copyable_item(monkeypatch, tmp_path):
    item = dict(ITEM, video_copy=True, audio_copy=True, height=1080)
    cmds = _hls_cmds(monkeypatch, item, str(tmp_path / 'r'), start=12.0, audio_id=1)
    assert len(cmds) == 4
    assert cmds[0][cmds[0].index('-c:v') + 1] == 'copy'
    assert cmds[0][cmds[0].index('-c:a') + 1] == 'copy'
    assert cmds[0][cmds[0].index('-ss') + 1] == '12.000'
    assert '0:a:1' in cmds[0]
    assert cmds[0][-1].endswith('index.m3u8')


def test_hls_commands_burns_bitmap_subtitles_on_two_steps_only(monkeypatch, tmp_path):
    item = dict(ITEM, subs=[{'id': 'sub3', 'kind': 'embedded', 'stream': 3}])
    cmds = _hls_cmds(monkeypatch, item, str(tmp_path / 'b'), burn_sub='sub3')
    assert len(cmds) == 2
    chain = cmds[0][cmds[0].index('-filter_complex') + 1]
    assert chain.startswith('[0:v][0:s:3]overlay[o];[o]')
    assert 'scale=-2:1080' in chain
    assert all(cmd[-1].endswith('index.m3u8') for cmd in cmds)
    assert 'libx264' in cmds[1]


# ── _hls_read_playlist ────────────────────────────────────────────────────────
def test_read_playlist_sums_the_extinf_durations(tmp_path):
    out_dir = str(tmp_path / 's')
    _playlist(out_dir, [6.0, 6.0, 3.5])
    text, n, produced = hls._hls_read_playlist(out_dir)
    assert '#EXTM3U' in text
    assert n == 3
    assert produced == pytest.approx(15.5)


def test_read_playlist_on_a_missing_playlist_is_empty(tmp_path):
    assert hls._hls_read_playlist(str(tmp_path / 'nope')) == ('', 0, 0.0)


# ── get_hls / note_hls_segment ────────────────────────────────────────────────
def test_get_hls_touches_the_session_and_misses_cleanly(monkeypatch, hls_dir):
    clock = FakeClock(start=500.0)
    monkeypatch.setattr(hls, 'time', clock)
    sess = {'id': 'abc', 'touched': 0.0}
    hls._HLS['abc'] = sess
    assert hls.get_hls('abc') is sess
    assert sess['touched'] == 500.0
    assert hls.get_hls('missing') is None


@pytest.mark.parametrize(('consumed', 'index', 'expected'), [(0.0, 0, 6.0), (0.0, 9, 60.0), (120.0, 1, 120.0)])
def test_note_hls_segment_only_moves_the_watermark_forward(consumed, index, expected):
    sess = {'consumed': consumed}
    hls.note_hls_segment(sess, index)
    assert sess['consumed'] == expected


# ── close_hls ─────────────────────────────────────────────────────────────────
def test_close_hls_on_an_unknown_id_is_a_no_op(hls_dir):
    assert hls.close_hls('not-a-session') is None


def test_close_hls_resumes_then_kills_a_running_session(hls_dir):
    out_dir = hls_dir / 'live'
    out_dir.mkdir()
    proc = FakeProc(polls=(None,))
    hls._HLS['live'] = {'id': 'live', 'dir': str(out_dir), 'proc': proc}
    hls.close_hls('live')
    assert proc.signals == [signal.SIGCONT]
    assert proc.kills == 1
    assert proc.waits == [5]
    assert 'live' not in hls._HLS
    assert not out_dir.exists()


def test_close_hls_tolerates_a_process_that_cannot_be_signalled(hls_dir):
    out_dir = hls_dir / 'stubborn'
    out_dir.mkdir()
    proc = RefusingProc(polls=(None,))
    hls._HLS['stubborn'] = {'id': 'stubborn', 'dir': str(out_dir), 'proc': proc}
    hls.close_hls('stubborn')
    assert proc.kills == 1
    assert not out_dir.exists()


def test_close_hls_tolerates_a_kill_that_fails(hls_dir):
    out_dir = hls_dir / 'zombie'
    out_dir.mkdir()
    proc = FakeProc(polls=(None,), kill_raises=True)
    hls._HLS['zombie'] = {'id': 'zombie', 'dir': str(out_dir), 'proc': proc}
    hls.close_hls('zombie')
    assert proc.waits == []
    assert not out_dir.exists()


def test_close_hls_leaves_an_already_exited_process_alone(hls_dir):
    out_dir = hls_dir / 'done'
    out_dir.mkdir()
    proc = FakeProc(polls=(0,))
    hls._HLS['done'] = {'id': 'done', 'dir': str(out_dir), 'proc': proc}
    hls.close_hls('done')
    assert proc.kills == 0
    assert proc.signals == []
    assert not out_dir.exists()


# ── sweep_hls ─────────────────────────────────────────────────────────────────
def test_sweep_hls_removes_every_directory_no_session_owns(hls_dir):
    for name in ('stale1', 'stale2', 'mine'):
        (hls_dir / name).mkdir()
    hls._HLS['mine'] = {'id': 'mine'}
    assert hls.sweep_hls() == 2
    assert sorted(p.name for p in hls_dir.iterdir()) == ['mine']


def test_sweep_hls_survives_a_missing_root(monkeypatch, tmp_path, hls_dir):
    monkeypatch.setattr(hls, 'HLS_DIR', str(tmp_path / 'gone'))
    assert hls.sweep_hls() == 0


# ── _hls_governor ─────────────────────────────────────────────────────────────
def _governor_session(hls_dir, name, proc, durations=(), consumed=0.0, touched=None, clock=None):
    out_dir = hls_dir / name
    out_dir.mkdir()
    if durations:
        _playlist(str(out_dir), durations)
    sess = {
        'id': name,
        'dir': str(out_dir),
        'proc': proc,
        'item': 'it1',
        'offset': 0.0,
        'touched': (clock.now if touched is None else touched),
        'consumed': consumed,
        'segments': 0,
        'produced': 0.0,
    }
    hls._HLS[name] = sess
    return sess


def test_governor_stops_and_resumes_ffmpeg_around_the_lead_window(monkeypatch, hls_dir):
    # 60 segments of 6 s = 360 s produced, twice the 180 s lead allowance.
    clock = FakeClock()
    monkeypatch.setattr(hls, 'time', clock)
    proc = FakeProc(polls=(None, None, None, 0))
    sess = _governor_session(hls_dir, 'lead', proc, durations=[6.0] * 60, clock=clock)

    def catch_up(_clock):
        # Second tick: the client has pulled everything, so the lead collapses.
        if len(_clock.sleeps) == 2:
            sess['consumed'] = 360.0
        sess['touched'] = _clock.now

    clock.on_sleep = catch_up

    hls._hls_governor(sess)

    assert proc.signals == [signal.SIGSTOP, signal.SIGCONT]
    assert sess['segments'] == 60
    assert sess['produced'] == pytest.approx(360.0)
    assert 'lead' not in hls._HLS
    assert not (hls_dir / 'lead').exists()


def test_governor_closes_a_session_nobody_fetches_from(monkeypatch, hls_dir):
    clock = FakeClock()
    monkeypatch.setattr(hls, 'time', clock)
    proc = FakeProc(polls=(None,))
    sess = _governor_session(
        hls_dir, 'idle', proc, durations=[6.0], touched=clock.now - hls.HLS_IDLE_TIMEOUT - 1, clock=clock
    )
    hls._hls_governor(sess)
    # No throttling happened; the single SIGCONT is close_hls() un-pausing before SIGKILL.
    assert proc.signals == [signal.SIGCONT]
    assert proc.kills == 1
    assert 'idle' not in hls._HLS


def test_governor_gives_up_when_the_process_refuses_a_signal(monkeypatch, hls_dir):
    clock = FakeClock()
    monkeypatch.setattr(hls, 'time', clock)
    proc = RefusingProc(polls=(None,))
    sess = _governor_session(hls_dir, 'refuse', proc, durations=[6.0] * 60, clock=clock)
    clock.on_sleep = lambda c: sess.__setitem__('touched', c.now)
    hls._hls_governor(sess)
    assert len(clock.sleeps) == 1
    assert proc.kills == 1
    assert 'refuse' not in hls._HLS


def test_governor_exits_as_soon_as_ffmpeg_has_exited(monkeypatch, hls_dir):
    clock = FakeClock()
    monkeypatch.setattr(hls, 'time', clock)
    proc = FakeProc(polls=(0,))
    sess = _governor_session(hls_dir, 'exited', proc, clock=clock)
    hls._hls_governor(sess)
    assert clock.sleeps == [1.0]
    assert proc.kills == 0
    assert 'exited' not in hls._HLS


# ── start_hls ─────────────────────────────────────────────────────────────────
def _fake_popen(behaviour, started):
    """Return a Popen replacement; ``behaviour(out_dir, step)`` scripts each step."""

    def popen(cmd, stdout=None, stderr=None):
        out_dir = os.path.dirname(cmd[-1])
        started.append(cmd)
        return behaviour(out_dir, len(started) - 1)

    return popen


@pytest.mark.parametrize(('free', 'raises'), [(hls.HLS_MIN_FREE_BYTES - 1, False), (0, True)])
def test_start_hls_refuses_to_run_without_disk(monkeypatch, hls_dir, free, raises):
    monkeypatch.setattr(hls, 'shutil', FakeShutil(free=free, raises=raises))
    assert hls.start_hls(ITEM) == {'error': 'low_disk'}
    assert hls._HLS == {}
    assert list(hls_dir.iterdir()) == []


def test_start_hls_returns_once_the_first_segment_is_written(monkeypatch, hls_dir):
    clock = FakeClock()
    monkeypatch.setattr(hls, 'time', clock)
    monkeypatch.setattr(hls, 'shutil', FakeShutil())
    monkeypatch.setattr(hls, '_video_fps', lambda path: 24.0)
    governed = []
    monkeypatch.setattr(hls, '_hls_governor', lambda sess: governed.append(sess['id']))
    started = []
    procs = []

    def behaviour(out_dir, step):
        _playlist(out_dir, [6.0, 6.0])
        proc = FakeProc(polls=(None,))
        procs.append(proc)
        return proc

    monkeypatch.setattr(hls.subprocess, 'Popen', _fake_popen(behaviour, started))

    out = hls.start_hls(ITEM, start=30.0, audio_id=1, burn_sub='')

    assert set(out) == {'id', 'offset', 'duration'}
    assert out['offset'] == 30.0
    assert out['duration'] == pytest.approx(7200.5)
    assert len(started) == 1  # the first ladder step succeeded; no fallback ran
    sess = hls._HLS[out['id']]
    assert sess['item'] == 'it1'
    assert sess['dir'] == os.path.join(str(hls_dir), out['id'])
    assert sess['consumed'] == 0.0 and sess['segments'] == 0
    assert hls.get_hls(out['id']) is sess
    # The governor runs on its own thread; give it up to a second to be called.
    for _ in range(100):
        if governed:
            break
        import time as _t

        _t.sleep(0.01)
    assert governed == [out['id']]


def test_start_hls_falls_down_the_ladder_and_reports_failure(monkeypatch, hls_dir, caplog):
    clock = FakeClock()
    monkeypatch.setattr(hls, 'time', clock)
    fake_shutil = FakeShutil()
    monkeypatch.setattr(hls, 'shutil', fake_shutil)
    monkeypatch.setattr(hls, '_video_fps', lambda path: 24.0)
    started = []

    def behaviour(out_dir, step):
        # Litter the directory so the between-steps cleanup has work to do, and
        # include a subdirectory, whose os.remove() raises OSError.
        with open(os.path.join(out_dir, f'junk{step}.m4s'), 'wb') as f:
            f.write(b'0')
        os.makedirs(os.path.join(out_dir, f'subdir{step}'), exist_ok=True)
        return FakeProc(polls=(1,), stderr=b'Unknown encoder h264_nvenc\n')

    monkeypatch.setattr(hls.subprocess, 'Popen', _fake_popen(behaviour, started))

    import logging

    with caplog.at_level(logging.INFO, logger='zyg_zero.zpub_cinema'):
        out = hls.start_hls(ITEM)

    assert out == {'error': 'transcode_failed'}
    assert len(started) == 3  # every ladder step was tried
    assert 'Unknown encoder h264_nvenc' in caplog.text
    assert 'HLS step 3 produced no segment' in caplog.text
    assert hls._HLS == {}
    assert fake_shutil.rmtrees == [os.path.join(str(hls_dir), os.path.basename(fake_shutil.rmtrees[0]))]


def test_start_hls_gives_up_on_a_step_that_hangs_without_a_segment(monkeypatch, hls_dir):
    clock = FakeClock()
    monkeypatch.setattr(hls, 'time', clock)
    monkeypatch.setattr(hls, 'shutil', FakeShutil())
    monkeypatch.setattr(hls, '_video_fps', lambda path: 24.0)
    monkeypatch.setattr(hls, 'hls_commands', lambda *a, **k: [['ffmpeg', '-i', 'x', os.path.join(a[4], 'index.m3u8')]])
    started = []

    def behaviour(out_dir, step):
        # Alive forever, and kill() fails too — the start timeout is the only exit.
        return FakeProc(polls=(None,), kill_raises=True)

    monkeypatch.setattr(hls.subprocess, 'Popen', _fake_popen(behaviour, started))

    assert hls.start_hls(ITEM) == {'error': 'transcode_failed'}
    # 25 s of start timeout polled every 0.15 s.
    assert clock.sleeps == [0.15] * 167
    assert hls._HLS == {}


# ── _norm_title / version_suffixes ────────────────────────────────────────────
@pytest.mark.parametrize(
    ('raw', 'expected'),
    [
        ('Godzilla Vs. Kong', 'godzilla vs kong'),
        ('godzilla vs kong', 'godzilla vs kong'),
        ('  The Thing!! ', 'the thing'),
        ('Blade Runner 2049', 'blade runner 2049'),
        ('', ''),
        (None, ''),
        ('***', ''),
    ],
)
def test_norm_title_ignores_case_and_punctuation(raw, expected):
    assert hls._norm_title(raw) == expected


def test_version_suffixes_labels_only_genuine_duplicates():
    items = [
        {'id': 'a', 'title': 'Gods of Egypt', 'year': 2016, 'width': 1920, 'size': 9, 'filename': 'a.mkv'},
        {'id': 'b', 'title': 'gods of egypt', 'year': 2016, 'width': 3840, 'size': 4, 'filename': 'b.mp4'},
        {'id': 'c', 'title': 'Deadpool', 'year': 2016, 'width': 1920, 'size': 3, 'filename': 'c.mkv'},
        {'id': 'd', 'title': 'Deadpool 2', 'year': 2018, 'width': 1920, 'size': 3, 'filename': 'd.mkv'},
        {'id': 'e', 'title': 'The Thing', 'year': 1982, 'width': 720, 'size': 1, 'filename': 'e.mkv'},
        {'id': 'f', 'title': 'The Thing', 'year': 2011, 'width': 1920, 'size': 2, 'filename': 'f.mkv'},
        {'id': 'g', 'title': 'The Thing', 'kind': 'episode', 'year': 1982, 'width': 1920},
        {'id': 'h', 'title': '', 'year': 1982, 'width': 1920},
        {'id': 'i', 'title': None, 'year': 1982},
    ]
    assert hls.version_suffixes(items) == {'b': 'V1', 'a': 'V2'}


def test_version_suffixes_orders_widest_then_largest_then_by_name():
    items = [
        {'id': 'z', 'title': 'Dune', 'year': 2021, 'width': 1920, 'size': 100, 'filename': 'z.mkv'},
        {'id': 'y', 'title': 'Dune', 'year': 2021, 'width': 1920, 'size': 100, 'filename': 'a.mkv'},
        {'id': 'x', 'title': 'Dune', 'year': 2021, 'width': 3840, 'size': 1, 'filename': 'x.mkv'},
        {'id': 'w', 'title': 'Dune', 'year': 2021, 'width': 1920, 'size': 200, 'filename': 'w.mkv'},
    ]
    assert hls.version_suffixes(items) == {'x': 'V1', 'w': 'V2', 'y': 'V3', 'z': 'V4'}


def test_version_suffixes_tolerates_items_without_any_metadata():
    assert hls.version_suffixes([]) == {}
    assert hls.version_suffixes([{'id': 'only', 'title': 'Solo', 'year': 2018}]) == {}
