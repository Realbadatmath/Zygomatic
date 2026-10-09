#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The helpers `stage_04_clip_mux.mux_clips` was split into.

    scripts/run_tests.sh tests/test_stage_04_clip_mux_helpers.py

Until 2026-10-09 every one of these was a branch inside one 420-line loop, so
none of them had ever been exercised on its own: the only way to reach the
ping-pong loop or the Ken Burns wide-shot pan was a full video run with a GPU.
These tests drive them with plain values and a recording stand-in for
`subprocess`, so no ffmpeg runs and nothing is rendered.
"""

import json
import os

import pytest

from zyg_workflows.bin import exe
from zyg_workflows.video_stages import stage_04_clip_mux_build as B

FFMPEG = exe('ffmpeg', required=False)
FFPROBE = exe('ffprobe', required=False)


class _Res:
    """What subprocess.run returns, as much of it as the stage reads."""

    def __init__(self, returncode=0, stdout=b''):
        self.returncode = returncode
        self.stdout = stdout


class _Recorder:
    """A `subprocess` stand-in: records every call and writes a plausible output.

    The stage decides an encode worked by stat-ing the last argument, so the
    recorder writes 2 kB there — just over the stage's 1 kB stub threshold.
    """

    def __init__(self, returncode=0, stdout=b'', write_output=True):
        self.calls = []
        self._rc = returncode
        self._stdout = stdout
        self._write = write_output

    def run(self, args, **kwargs):
        self.calls.append((list(args), kwargs))
        # '-y' marks an ffmpeg encode: only those have an output path to write.
        if self._write and '-y' in args:
            with open(args[-1], 'wb') as fh:
                fh.write(b'\0' * 2048)
        return _Res(self._rc, self._stdout)


class _Raiser:
    """A `subprocess` stand-in whose every call fails — the probe fallbacks."""

    def run(self, args, **kwargs):
        raise OSError('no ffprobe on this machine')


def _log_sink():
    """A `ctx._log` stand-in; returns (log_fn, recorded_calls)."""
    seen = []

    def _log(level, stage, msg):
        seen.append((level, stage, msg))

    return _log, seen


# ── durations ────────────────────────────────────────────────────────────────


def test_tts_duration_comes_from_the_probe(tmp_path):
    """A readable narration file is measured, not assumed."""
    tts = tmp_path / 'line.mp3'
    tts.write_bytes(b'\0')
    sp = _Recorder(stdout=json.dumps({'format': {'duration': '7.25'}}).encode(), write_output=False)
    assert B.measure_tts_duration(sp, json, str(tts), 4.0) == 7.25
    assert sp.calls[0][0][1:] == ['-v', 'quiet', '-show_format', '-of', 'json', str(tts)]


def test_tts_duration_falls_back_to_the_planned_duration(tmp_path):
    """No narration file, and a failing probe, both keep the planned duration."""
    assert B.measure_tts_duration(_Recorder(), json, None, 4.0) == 4.0
    assert B.measure_tts_duration(_Recorder(), json, str(tmp_path / 'nope.mp3'), 4.0) == 4.0
    tts = tmp_path / 'line.mp3'
    tts.write_bytes(b'\0')
    assert B.measure_tts_duration(_Raiser(), json, str(tts), 4.0) == 4.0


def test_clip_duration_reads_the_bare_ffprobe_number():
    """-show_entries prints the seconds alone; an unreadable clip counts as 0 s."""
    assert B.measure_clip_duration(_Recorder(stdout=b'3.500000\n', write_output=False), '/x.mp4') == 3.5
    assert B.measure_clip_duration(_Recorder(stdout=b'\n', write_output=False), '/x.mp4') == 0.0
    assert B.measure_clip_duration(_Raiser(), '/x.mp4') == 0.0


# ── the pure command builders ────────────────────────────────────────────────


@pytest.mark.skipif(not FFMPEG, reason='ffmpeg is not installed on this machine')
def test_trim_args_cut_to_the_narration_and_letterbox():
    """The simple case: the narration fits, so the clip is only cut and padded."""
    assert B.trim_args('/in.mp4', 6.25, '/out.mp4') == [
        FFMPEG,
        '-y',
        '-i',
        '/in.mp4',
        '-t',
        '6.25',
        '-vf',
        B.SCALE_PAD_1080,
        '-c:v',
        'libx264',
        '-preset',
        'ultrafast',
        '-crf',
        '0',
        '-pix_fmt',
        'yuv420p',
        '-an',
        '/out.mp4',
    ]


@pytest.mark.skipif(not FFMPEG, reason='ffmpeg is not installed on this machine')
def test_stream_loop_args_repeat_until_the_narration_is_covered():
    """-stream_loop -1 with -t is what fills a long narration from a short clip."""
    args = B.stream_loop_args('/in.mp4', 12.0, '/out.mp4')
    assert args[:6] == [FFMPEG, '-y', '-stream_loop', '-1', '-i', '/in.mp4']
    assert args[6:10] == ['-t', '12.0', '-vf', B.SCALE_PAD_1080]
    assert args[-1] == '/out.mp4'


@pytest.mark.skipif(not FFMPEG, reason='ffmpeg is not installed on this machine')
def test_manga_panel_args_hold_the_page_at_one_frame_a_second():
    """A comic panel is held flat: -r 1, no zoompan, no camera move."""
    args = B.manga_panel_args('/page.png', 3.0, '/out.mp4')
    assert args[:6] == [FFMPEG, '-y', '-loop', '1', '-i', '/page.png']
    assert ['-r', '1'] == args[args.index('-r') : args.index('-r') + 2]
    assert 'zoompan' not in ' '.join(args)


@pytest.mark.skipif(not FFMPEG, reason='ffmpeg is not installed on this machine')
def test_kenburns_args_hold_the_input_longer_than_the_output():
    """The still is held half a second longer so zoompan never runs dry."""
    args = B.kenburns_args('/still.png', 4.0, 'VF', '/out.mp4')
    assert args[4:6] == ['-t', '4.5']
    assert args[args.index('-vf') + 1] == 'VF'
    # The *output* -t is the narration length, and it comes after the -vf.
    assert args[args.index('-vf') + 2 :][:2] == ['-t', '4.0']


@pytest.mark.skipif(not FFMPEG, reason='ffmpeg is not installed on this machine')
def test_mux_audio_args_copy_the_video_and_let_the_audio_set_the_length():
    """-c:v copy keeps the lossless intermediate; -shortest makes audio the clock."""
    args = B.mux_audio_args('/v.mp4', '/a.mp3', '/out.mp4')
    assert args == [
        FFMPEG,
        '-y',
        '-i',
        '/v.mp4',
        '-i',
        '/a.mp3',
        '-map',
        '0:v:0',
        '-map',
        '1:a:0',
        '-c:v',
        'copy',
        '-c:a',
        'aac',
        '-b:a',
        '192k',
        '-shortest',
        '/out.mp4',
    ]


def test_crossfade_filter_dissolves_the_tail_over_the_head():
    """The xfade starts at clip_dur - xf_dur and the tail is trimmed from there."""
    vf = B.crossfade_filter(10.0, 0.8)
    assert 'trim=start=9.2' in vf
    assert 'xfade=transition=fade:duration=0.8:offset=9.2' in vf
    assert vf.endswith('[outv]')


def test_crossfade_filter_never_trims_before_the_start():
    """A cross-fade longer than the clip clamps the trim at 0, not a negative seek."""
    assert 'trim=start=0.0' in B.crossfade_filter(0.5, 2.0)


# ── the pure strategy choices ────────────────────────────────────────────────


@pytest.mark.parametrize(
    ('meta', 'expected'),
    [
        ({'shot_type': 'close-up'}, True),
        ({'shot_type': 'extreme close'}, True),
        ({'shot_type': 'portrait'}, True),
        ({'scene_type': 'character'}, True),
        ({'shot_type': 'wide', 'scene_type': 'environment'}, False),
        ({'shot_type': 'aerial establishing'}, False),
        ({}, False),
    ],
)
def test_loop_strategy_follows_the_shot(meta, expected):
    """Close reads of a face get the cross-fade; wider shots get the ping-pong."""
    assert B.wants_crossfade_loop(meta) is expected


def test_kenburns_pushes_in_on_the_upper_third_for_a_close_shot():
    """A close-up zooms to 1.3 max and frames the eyes, not the centre."""
    vf = B.kenburns_filter(0, {'shot_type': 'close-up', 'scene_type': 'character'}, 2.0)
    assert ',1.3)' in vf
    assert "y='ih/5-ih/zoom/5'" in vf
    assert 'd=60:' in vf  # 2 s at 30 fps


def test_kenburns_pans_wide_shots_in_alternating_directions():
    """Two neighbouring wides must not drift the same way, so the index flips it."""
    even = B.kenburns_filter(0, {'shot_type': 'wide'}, 1.0)
    odd = B.kenburns_filter(1, {'shot_type': 'wide'}, 1.0)
    assert "x='min(iw*" in even
    assert "x='max(iw*" in odd
    assert "z='1.08'" in even and "z='1.08'" in odd


def test_kenburns_speed_comes_from_the_scene_type():
    """'action' maps to tension (1.4x), 'character' to calm (0.70x) — different deltas."""
    tense = B.kenburns_filter(0, {'scene_type': 'action'}, 1.0)
    calm = B.kenburns_filter(0, {'scene_type': 'character'}, 1.0)
    assert tense != calm
    assert '%.6f' % (0.0003 * 1.4) in tense
    assert '%.6f' % (0.0003 * 0.70) in calm


def test_kenburns_always_renders_at_least_one_frame():
    """A zero-length narration must not ask zoompan for d=0."""
    assert 'd=1:' in B.kenburns_filter(0, {}, 0.0)


# ── the video source for one scene ───────────────────────────────────────────


@pytest.mark.skipif(not FFPROBE or not FFMPEG, reason='ffmpeg/ffprobe are not installed on this machine')
def test_a_narration_shorter_than_the_clip_is_a_plain_trim(tmp_path):
    """One ffprobe and one ffmpeg: no loop intermediate is written at all."""
    sp = _Recorder(stdout=b'10.0\n')
    out = B.build_looped_clip(sp, str(tmp_path), 3, '/wan.mp4', 4.0, {})
    assert out == str(tmp_path / 'clip_0003_looped.mp4')
    assert len(sp.calls) == 2
    assert '-stream_loop' not in sp.calls[1][0]


@pytest.mark.skipif(not FFPROBE or not FFMPEG, reason='ffmpeg/ffprobe are not installed on this machine')
def test_a_long_narration_crossfades_a_close_shot_then_loops_it(tmp_path):
    """Probe, cross-fade intermediate, stream-loop — and the scratch is cleaned up."""
    sp = _Recorder(stdout=b'5.0\n')
    out = B.build_looped_clip(sp, str(tmp_path), 0, '/wan.mp4', 20.0, {'shot_type': 'close-up'})
    assert out == str(tmp_path / 'clip_0000_looped.mp4')
    assert len(sp.calls) == 3
    assert 'xfade' in ' '.join(sp.calls[1][0])
    assert '-stream_loop' in sp.calls[2][0]
    assert not os.path.exists(str(tmp_path / 'clip_0000_looped.mp4_xftmp.mp4'))


@pytest.mark.skipif(not FFPROBE or not FFMPEG, reason='ffmpeg/ffprobe are not installed on this machine')
def test_a_long_narration_pingpongs_a_wide_shot(tmp_path):
    """A wide shot gets the palindrome, and the loop reads the palindrome back."""
    sp = _Recorder(stdout=b'5.0\n')
    B.build_looped_clip(sp, str(tmp_path), 0, '/wan.mp4', 20.0, {'shot_type': 'wide'})
    assert B.PINGPONG_FILTER in sp.calls[1][0]
    assert sp.calls[2][0][sp.calls[2][0].index('-i') + 1].endswith('_pp.mp4')


@pytest.mark.skipif(not FFPROBE or not FFMPEG, reason='ffmpeg/ffprobe are not installed on this machine')
def test_a_failed_encode_yields_no_clip(tmp_path):
    """A non-zero ffmpeg means this scene has no WAN source; the caller falls back."""
    assert B.build_looped_clip(_Recorder(returncode=1, stdout=b'10.0\n'), str(tmp_path), 0, '/w.mp4', 1.0, {}) is None


@pytest.mark.skipif(not FFMPEG, reason='ffmpeg is not installed on this machine')
def test_a_manga_page_is_held_flat_only_when_the_panel_fps_says_so(tmp_path):
    """manga_panel_fps <= 1 is the held page; anything else still gets a camera move."""
    job = {'pipeline_options': {'manga_panel_fps': 1}}
    sp = _Recorder()
    B.build_static_clip(sp, str(tmp_path), 0, '/p.png', 2.0, {}, job, True)
    assert 'zoompan' not in ' '.join(sp.calls[0][0])

    sp = _Recorder()
    B.build_static_clip(sp, str(tmp_path), 0, '/p.png', 2.0, {}, {'pipeline_options': {}}, True)
    assert 'zoompan' in ' '.join(sp.calls[0][0])


# ── narration, foley, mux ────────────────────────────────────────────────────


class _Audio:
    """An audio service stand-in: whatever foley it is told to find, and a flag."""

    def __init__(self, foley=(), ok=True):
        self.foley = list(foley)
        self.ok = ok
        self.mixed = []

    def get_foley_for_scene(self, desc, max_foley=2, log_fn=None):
        return self.foley

    def mix_foley_into_audio(self, tts, foley, out, dur, log_fn=None):
        self.mixed.append(('audio', tts, out))
        return self.ok

    def mix_foley_into_video(self, video, foley, out, dur, log_fn=None):
        self.mixed.append(('video', video, out))
        return self.ok


def test_foley_over_narration_returns_the_mixed_track(tmp_path):
    """A successful mix replaces the narration path and names the files it used."""
    log, seen = _log_sink()
    svc = _Audio(foley=[('/sfx/rain.wav', 0.3)])
    out = B.foley_over_narration(svc, 'rain on a roof', '/tts.mp3', 6.0, str(tmp_path), 2, log)
    assert out == str(tmp_path / 'tts_0002_foley.mp3')
    assert ('INFO', 'Stage 4', "Scene 2 foley: ['rain.wav']") in seen


def test_foley_over_narration_keeps_plain_tts_when_there_is_nothing_to_mix(tmp_path):
    """No service, no description and no match all leave the narration alone, silently."""
    log, seen = _log_sink()
    assert B.foley_over_narration(None, 'desc', '/tts.mp3', 6.0, str(tmp_path), 0, log) == '/tts.mp3'
    assert B.foley_over_narration(_Audio(), '', '/tts.mp3', 6.0, str(tmp_path), 0, log) == '/tts.mp3'
    assert B.foley_over_narration(_Audio(), 'desc', '/tts.mp3', 6.0, str(tmp_path), 0, log) == '/tts.mp3'
    assert seen == []


def test_foley_over_narration_warns_and_keeps_plain_tts_when_the_mix_fails(tmp_path):
    """A failed mix is a warning, not a dropped scene."""
    log, seen = _log_sink()
    svc = _Audio(foley=[('/sfx/rain.wav', 0.3)], ok=False)
    assert B.foley_over_narration(svc, 'rain', '/tts.mp3', 6.0, str(tmp_path), 1, log) == '/tts.mp3'
    assert seen == [('WARNING', 'Stage 4', 'Scene 1 foley mix failed — using plain TTS')]


@pytest.mark.skipif(not FFMPEG, reason='ffmpeg is not installed on this machine')
def test_a_failed_mux_ships_the_video_only_clip(tmp_path):
    """A silent scene is a defect; a missing scene is a hole. Ship the video."""
    log, seen = _log_sink()
    out = B.mux_narrated_clip(_Recorder(returncode=1), str(tmp_path), 5, '/v.mp4', '/a.mp3', log)
    assert out == '/v.mp4'
    assert seen == [('WARNING', 'Stage 4', 'Audio mux failed scene 5 — using video-only clip')]


@pytest.mark.skipif(not FFMPEG, reason='ffmpeg is not installed on this machine')
def test_a_good_mux_ships_the_muxed_clip(tmp_path):
    """The happy path delivers clip_<n>.mp4 and says nothing."""
    log, seen = _log_sink()
    out = B.mux_narrated_clip(_Recorder(), str(tmp_path), 5, '/v.mp4', '/a.mp3', log)
    assert out == str(tmp_path / 'clip_0005.mp4')
    assert seen == []


def test_foley_only_clip_is_none_when_there_is_nothing_to_lay_in(tmp_path):
    """Without a service, a description, a video or a match there is no foley clip."""
    log, _ = _log_sink()
    video = tmp_path / 'v.mp4'
    video.write_bytes(b'\0')
    assert B.foley_only_clip(None, str(tmp_path), 0, str(video), 'desc', 1.0, log) is None
    assert B.foley_only_clip(_Audio(), str(tmp_path), 0, str(video), '', 1.0, log) is None
    assert B.foley_only_clip(_Audio(), str(tmp_path), 0, '/gone.mp4', 'desc', 1.0, log) is None
    assert B.foley_only_clip(_Audio(), str(tmp_path), 0, str(video), 'desc', 1.0, log) is None


def test_foley_only_clip_returns_the_mixed_video(tmp_path):
    """With narration absent the foley goes straight onto the video's audio track."""
    log, seen = _log_sink()
    video = tmp_path / 'v.mp4'
    video.write_bytes(b'\0')
    svc = _Audio(foley=[('/sfx/wind.wav', 0.2)])
    out = B.foley_only_clip(svc, str(tmp_path), 7, str(video), 'wind', 1.0, log)
    assert out == str(tmp_path / 'clip_0007_foley.mp4')
    assert svc.mixed == [('video', str(video), out)]
    assert ('INFO', 'Stage 4', "Scene 7 foley (no-TTS): ['wind.wav']") in seen
