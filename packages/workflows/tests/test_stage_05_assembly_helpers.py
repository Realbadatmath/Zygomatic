# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Unit tests for the helpers extracted from `stage_05_assembly`.

    cd packages/workflows && pytest -q tests/test_stage_05_assembly_helpers.py

`video_stages/stage_05_assembly.py` held one 604-line function: the whole
assembly tail of the video pipeline, with two closures inside it. Nothing in it
had ever been exercised in isolation — it needs a job, ffmpeg, the GPU and the
audio service. The 2026-10-09 split moved every phase into
`stage_05_assembly_steps` (colour, concat, music) and
`stage_05_assembly_finish` (ending card, trim, 4K master, thumbnail, prop
advisory) as plain functions whose every input is a parameter, so each one is
callable here with a recording stub runner: no ffmpeg is ever executed, no GPU
is touched and no service is reached.

What each test pins is a behaviour the old function had — the keyword families
of the music mood, the clamp on the colour gains, the 3 %/1 kB/10 kB
thresholds, the filter escaping of the title card, the demuxer fallback for a
video with no audio stream, the 0.25 s trim deadband, the clean-up of a failed
master, and the exact text and order of the log lines and the prop advisory.
"""

import io
import os
import subprocess
import types

import numpy as np
import pytest
from PIL import Image

from zyg_workflows.video_stages import stage_05_assembly_finish as FIN
from zyg_workflows.video_stages import stage_05_assembly_steps as ST


class Runner:
    """A recording stand-in for the driver's `subprocess` alias.

    `calls` holds every argv. `stdout_for` maps a substring of the joined argv
    to the bytes ffprobe/ffmpeg would have written; `rc` is the return code and
    `write` the size of the file to create at the last argv element (0 = none).

    Only an `ffmpeg` argv writes that file: `ffprobe` reads its input and
    produces nothing, so a probe must never clobber the video it measures —
    which is the whole point of the trim and master steps keeping the source.
    """

    def __init__(self, *, rc=0, write=2_000_000, stdout_for=None, png=None):
        self.calls = []
        self.rc = rc
        self.write = write
        self.stdout_for = stdout_for or {}
        self.png = png

    def run(self, argv, **kw):
        argv = [str(a) for a in argv]
        self.calls.append(argv)
        joined = ' '.join(argv)
        out = b''
        for needle, value in self.stdout_for.items():
            if needle in joined:
                out = value
                break
        if self.png is not None and 'image2pipe' in joined:
            out = self.png
        rc = self.rc(argv) if callable(self.rc) else self.rc
        write = self.write(argv) if callable(self.write) else self.write
        if write and argv[0] == 'ffmpeg' and argv[-1] != '-':
            with open(argv[-1], 'wb') as fh:
                fh.write(b'\0' * write)
        return types.SimpleNamespace(returncode=rc, stdout=out, stderr=b'the stderr tail')


class Log:
    """The driver's `_log` closure: records (level, stage, message)."""

    def __init__(self):
        self.lines = []

    def __call__(self, level, stage, message):
        self.lines.append((level, stage, message))

    def messages(self, level=None):
        return [m for lv, _st, m in self.lines if level in (None, lv)]


@pytest.fixture(autouse=True)
def _no_real_executables(monkeypatch):
    """`exe` resolves to the bare name, so argv is assertable and ffmpeg is never needed."""
    monkeypatch.setattr(ST, 'exe', lambda name, **kw: name)
    monkeypatch.setattr(FIN, 'exe', lambda name, **kw: name)


def png(rgb, size=(8, 8)):
    """A flat-colour PNG, as ffmpeg's `image2pipe` hands one back."""
    buf = io.BytesIO()
    Image.new('RGB', size, rgb).save(buf, 'PNG')
    return buf.getvalue()


# ── _bgm_emotion: the music mood of the joined scene descriptions ───────────


@pytest.mark.parametrize(
    ('description', 'expected'),
    [
        ('a brutal clash of shields', 'anger'),
        ('standing victorious on the ridge', 'triumph'),
        ('a vast sweeping coast at sunset', 'awe'),
        ('the fallen, and the grief after', 'grief'),
        ('a tense standoff in the pass', 'tension'),
        ('a man walks into a room', 'neutral'),
        ('', 'neutral'),
    ],
)
def test_bgm_emotion_maps_each_keyword_family(description, expected):
    assert ST._bgm_emotion(description) == expected


def test_bgm_emotion_is_case_insensitive():
    assert ST._bgm_emotion('BATTLE OF THERMOPYLAE') == 'anger'


def test_bgm_emotion_tries_the_families_in_order():
    """Anger wins over triumph, triumph over awe, awe over grief, grief over tension."""
    assert ST._bgm_emotion('a triumph after the battle') == 'anger'
    assert ST._bgm_emotion('triumph over the vast landscape') == 'triumph'
    assert ST._bgm_emotion('a vast landscape of the dead') == 'awe'
    assert ST._bgm_emotion('the dead in a tense pass') == 'grief'


# ── _channel_gains: the colour-consistency correction ───────────────────────


def test_channel_gains_is_the_plain_ratio_inside_the_band():
    assert ST._channel_gains([110.0, 100.0, 90.0], [100.0, 100.0, 100.0]) == [1.1, 1.0, 0.9]


def test_channel_gains_clamps_to_the_thirty_percent_band():
    assert ST._channel_gains([255.0, 10.0, 100.0], [100.0, 100.0, 100.0]) == [1.30, 0.70, 1.0]


def test_channel_gains_leaves_a_channel_at_the_noise_floor_alone():
    """A clip mean of 2.0 or darker is never amplified — the ratio would be meaningless."""
    assert ST._channel_gains([120.0, 120.0, 120.0], [2.0, 1.0, 0.0]) == [1.0, 1.0, 1.0]


# ── _clip_mean_rgb: the per-clip colour estimate ────────────────────────────


def _mean_rgb(runner):
    return ST._clip_mean_rgb('clip.mp4', runner, io, np, Image)


def test_clip_mean_rgb_averages_the_three_sample_frames():
    runner = Runner(stdout_for={'stream=nb_frames': b'30\n'}, png=png((60, 120, 180)))
    assert list(_mean_rgb(runner)) == [60.0, 120.0, 180.0]


def test_clip_mean_rgb_falls_back_to_mid_grey_when_no_frame_decodes():
    runner = Runner(stdout_for={'stream=nb_frames': b'30\n'})
    assert list(_mean_rgb(runner)) == [128.0, 128.0, 128.0]


def test_clip_mean_rgb_samples_ten_fifty_and_ninety_percent():
    runner = Runner(stdout_for={'stream=nb_frames': b'30\n'}, png=png((1, 1, 1)))
    _mean_rgb(runner)
    selects = [a for call in runner.calls for a in call if a.startswith('select=')]
    assert selects == ['select=eq(n\\,3)', 'select=eq(n\\,15)', 'select=eq(n\\,27)']


def test_clip_mean_rgb_defaults_to_thirty_frames_when_ffprobe_says_nothing():
    runner = Runner(png=png((1, 1, 1)))
    _mean_rgb(runner)
    selects = [a for call in runner.calls for a in call if a.startswith('select=')]
    assert selects == ['select=eq(n\\,3)', 'select=eq(n\\,15)', 'select=eq(n\\,27)']


def test_clip_mean_rgb_skips_an_undecodable_frame_without_failing():
    runner = Runner(stdout_for={'stream=nb_frames': b'30\n', 'image2pipe': b'not a png'})
    assert list(_mean_rgb(runner)) == [128.0, 128.0, 128.0]


# ── _normalize_clip_colors and the grade ────────────────────────────────────


def _two_clips(tmp_path, first, second):
    paths = []
    for name, rgb in (('a.mp4', first), ('b.mp4', second)):
        p = tmp_path / name
        p.write_bytes(b'clip')
        paths.append((str(p), rgb))
    return paths


def _normalize(tmp_path, monkeypatch, clips, *, write=2_000_000):
    """Drive `_normalize_clip_colors` with a recording `subprocess.run`."""
    rgb = dict(clips)
    log = Log()

    def run(argv, **kw):
        argv = [str(a) for a in argv]
        joined = ' '.join(argv)
        out = b''
        if 'stream=nb_frames' in joined:
            out = b'30\n'
        elif 'image2pipe' in joined:
            out = png(rgb[argv[argv.index('-i') + 1]])
        elif write:
            with open(argv[-1], 'wb') as fh:
                fh.write(b'\0' * write)
        return types.SimpleNamespace(returncode=0, stdout=out, stderr=b'')

    monkeypatch.setattr(subprocess, 'run', run)
    return ST._normalize_clip_colors([p for p, _ in clips], log), log


def test_normalize_skips_a_clip_whose_deviation_is_under_three_percent(tmp_path, monkeypatch):
    clips = _two_clips(tmp_path, (100, 100, 100), (101, 101, 101))
    out, log = _normalize(tmp_path, monkeypatch, clips)
    assert out == [p for p, _ in clips]
    assert log.lines == []


def test_normalize_keeps_the_mixer_copy_when_the_encode_landed(tmp_path, monkeypatch):
    clips = _two_clips(tmp_path, (150, 100, 100), (100, 100, 100))
    out, log = _normalize(tmp_path, monkeypatch, clips)
    assert out == [clips[0][0], clips[1][0].replace('.mp4', '_cc.mp4')]
    assert log.messages('INFO') == ['Color normalized clip 1: R×1.30 G×1.00 B×1.00']


def test_normalize_keeps_the_original_when_the_encode_produced_nothing(tmp_path, monkeypatch):
    clips = _two_clips(tmp_path, (150, 100, 100), (100, 100, 100))
    out, log = _normalize(tmp_path, monkeypatch, clips, write=0)
    assert out == [p for p, _ in clips]
    assert log.lines == []


def test_normalize_warns_and_returns_the_clips_unchanged_on_failure(tmp_path, monkeypatch):
    def boom(argv, **kw):
        raise OSError('ffprobe exploded')

    monkeypatch.setattr(subprocess, 'run', boom)
    log = Log()
    assert ST._normalize_clip_colors(['a.mp4', 'b.mp4'], log) == ['a.mp4', 'b.mp4']
    assert log.messages('WARNING') == ['Color consistency pass skipped: ffprobe exploded']


def test_cinematic_grade_counts_only_the_clips_that_changed(monkeypatch):
    monkeypatch.setattr(ST, '_apply_color_grade', lambda p, s, i, log_fn=None: p if p == 'b.mp4' else p + '!')
    log = Log()
    assert ST._cinematic_grade(['a.mp4', 'b.mp4'], 'cinematic', 'id', log) == ['a.mp4!', 'b.mp4']
    assert log.messages('INFO') == ['Cinematic grade applied (cinematic LUT + unsharp) to 1/2 clips']


def test_cinematic_grade_says_nothing_when_no_clip_changed(monkeypatch):
    monkeypatch.setattr(ST, '_apply_color_grade', lambda p, s, i, log_fn=None: p)
    log = Log()
    assert ST._cinematic_grade(['a.mp4'], 'cinematic', 'id', log) == ['a.mp4']
    assert log.lines == []


def test_cinematic_grade_warns_and_returns_the_input_on_failure(monkeypatch):
    def boom(*a, **kw):
        raise RuntimeError('no LUT')

    monkeypatch.setattr(ST, '_apply_color_grade', boom)
    log = Log()
    assert ST._cinematic_grade(['a.mp4'], 'noir', 'id', log) == ['a.mp4']
    assert log.messages('WARNING') == ['Color grade pass skipped: no LUT']


def test_color_passes_skips_the_normalisation_for_a_single_clip(monkeypatch):
    seen = []
    monkeypatch.setattr(ST, '_normalize_clip_colors', lambda clips, log: seen.append(clips) or clips)
    monkeypatch.setattr(ST, '_apply_color_grade', lambda p, s, i, log_fn=None: p)
    assert ST.color_passes(['only.mp4'], 'cinematic', 'id', Log()) == ['only.mp4']
    assert seen == []
    ST.color_passes(['a.mp4', 'b.mp4'], 'cinematic', 'id', Log())
    assert seen == [['a.mp4', 'b.mp4']]


# ── concat_clips ────────────────────────────────────────────────────────────


def test_concat_clips_writes_one_quoted_file_line_per_clip(tmp_path):
    runner = Runner()
    ST.concat_clips(runner, str(tmp_path), 'abcdefghijklmnop', ['/a b.mp4', '/c.mp4'])
    assert (tmp_path / 'concat.txt').read_text() == "file '/a b.mp4'\nfile '/c.mp4'\n"


def test_concat_clips_names_the_output_after_the_first_twelve_id_characters(tmp_path):
    final, err = ST.concat_clips(Runner(), str(tmp_path), 'abcdefghijklmnop', ['/a.mp4'])
    assert os.path.basename(final) == 'video_abcdefghijkl.mp4'
    assert err is None


def test_concat_clips_stream_copies_through_the_demuxer(tmp_path):
    runner = Runner()
    ST.concat_clips(runner, str(tmp_path), 'id', ['/a.mp4'])
    argv = runner.calls[0]
    assert argv[0] == 'ffmpeg'
    assert argv[argv.index('-f') + 1] == 'concat'
    assert argv[argv.index('-i') + 1] == str(tmp_path / 'concat.txt')
    assert argv[argv.index('-c:v') + 1] == 'copy'
    assert argv[argv.index('-c:a') + 1] == 'copy'


def test_concat_clips_returns_the_stderr_tail_when_ffmpeg_failed(tmp_path):
    _final, err = ST.concat_clips(Runner(rc=1), str(tmp_path), 'id', ['/a.mp4'])
    assert err == 'the stderr tail'


def test_concat_clips_treats_an_output_under_ten_kilobytes_as_a_failure(tmp_path):
    _final, err = ST.concat_clips(Runner(write=9_999), str(tmp_path), 'id', ['/a.mp4'])
    assert err == 'the stderr tail'


def test_concat_clips_treats_a_missing_output_as_a_failure(tmp_path):
    _final, err = ST.concat_clips(Runner(write=0), str(tmp_path), 'id', ['/a.mp4'])
    assert err == 'the stderr tail'


# ── mix_background_music ────────────────────────────────────────────────────


class AudioSvc:
    """The three members of `audio_service` the music step calls."""

    def __init__(self, *, track='bed.mp3', mix_ok=True):
        self.track = track
        self.mix_ok = mix_ok
        self.asked = None
        self.mixed = None

    def get_music_for_topic(self, topic, emotion, **kw):
        self.asked = (topic, emotion, kw['duration_s'], kw['out_dir'], kw['music_mood'])
        return self.track

    def mix_bgm_into_video(self, src, music, dst, **kw):
        self.mixed = (src, music, dst, kw['music_vol'])
        if self.mix_ok:
            with open(dst, 'wb') as fh:
                fh.write(b'mixed')
        return self.mix_ok

    def _pick_mood(self, topic, emotion):
        return f'picked:{emotion}'


@pytest.fixture
def _ace(stub_module):
    """ACE-Step, stubbed: the real module would try to reach ComfyUI."""
    unloaded = []
    stub_module('ace_step_service', types.SimpleNamespace(unload=lambda: unloaded.append(True)))
    return unloaded


def _mix(tmp_path, svc, log, done, *, mood=None):
    final = tmp_path / 'video_abcdefghijkl.mp4'
    final.write_bytes(b'video')
    ST.mix_background_music(
        svc,
        'Thermopylae',
        [{'description': 'a brutal battle'}, {}],
        2,
        4,
        str(tmp_path),
        'abcdefghijklmnop',
        str(final),
        mood,
        log,
        done.append,
    )
    return final


def test_mix_background_music_asks_for_the_dominant_emotion_and_the_full_duration(tmp_path, _ace):
    svc = AudioSvc(track=str(tmp_path / 'bed.mp3'))
    (tmp_path / 'bed.mp3').write_bytes(b'mp3')
    _mix(tmp_path, svc, Log(), [])
    topic, emotion, duration, out_dir, mood = svc.asked
    assert (topic, emotion, duration, mood) == ('Thermopylae', 'anger', 8, None)
    assert out_dir == str(tmp_path / 'music')


def test_mix_background_music_moves_the_mix_over_the_video(tmp_path, _ace):
    svc = AudioSvc(track=str(tmp_path / 'bed.mp3'))
    (tmp_path / 'bed.mp3').write_bytes(b'mp3')
    log = Log()
    final = _mix(tmp_path, svc, log, [])
    assert final.read_bytes() == b'mixed'
    assert svc.mixed[2] == str(tmp_path / 'video_abcdefghijkl_bgm.mp4')
    assert svc.mixed[3] == 0.12
    assert not os.path.exists(svc.mixed[2])
    # [-1] is the ACE-Step unload, which the step always logs last.
    assert log.messages('INFO')[-2] == 'BGM mixed in — mood: picked:anger, track: bed.mp3'


def test_mix_background_music_reports_the_mood_claude_chose_when_there_is_one(tmp_path, _ace):
    svc = AudioSvc(track=str(tmp_path / 'bed.mp3'))
    (tmp_path / 'bed.mp3').write_bytes(b'mp3')
    log = Log()
    _mix(tmp_path, svc, log, [], mood='elegiac')
    assert log.messages('INFO')[-2] == 'BGM mixed in — mood: elegiac, track: bed.mp3'


def test_mix_background_music_leaves_the_video_alone_when_the_mix_failed(tmp_path, _ace):
    svc = AudioSvc(track=str(tmp_path / 'bed.mp3'), mix_ok=False)
    log = Log()
    final = _mix(tmp_path, svc, log, [])
    assert final.read_bytes() == b'video'
    assert log.messages('WARNING') == ['BGM mix failed — video without background music']


def test_mix_background_music_warns_when_no_track_was_available(tmp_path, _ace):
    log = Log()
    _mix(tmp_path, AudioSvc(track=None), log, [])
    assert log.messages('WARNING') == ['No music track available (all tiers failed) — skipping BGM']


def test_mix_background_music_warns_and_carries_on_when_the_service_raises(tmp_path, _ace):
    class Boom(AudioSvc):
        def get_music_for_topic(self, topic, emotion, **kw):
            raise RuntimeError('ACE-Step is down')

    log = Log()
    done = []
    _mix(tmp_path, Boom(), log, done)
    assert log.messages('WARNING') == ['BGM step error: ACE-Step is down — skipping']
    assert done == ['Background Music']


def test_mix_background_music_completes_the_stage_before_unloading_ace_step(tmp_path, _ace):
    order = []
    log = Log()
    _mix(tmp_path, AudioSvc(track=None), log, order)
    assert order == ['Background Music']
    assert _ace == [True]
    assert log.messages('INFO')[-1] == 'ACE-Step unloaded — VRAM freed for next run'


def test_mix_background_music_survives_an_ace_step_that_cannot_unload(tmp_path, stub_module):
    def boom():
        raise RuntimeError('no such model')

    stub_module('ace_step_service', types.SimpleNamespace(unload=boom))
    log = Log()
    _mix(tmp_path, AudioSvc(track=None), log, [])
    assert 'ACE-Step unloaded — VRAM freed for next run' not in log.messages('INFO')


# ── The ending title card ───────────────────────────────────────────────────


def test_title_card_vf_escapes_the_filter_syntax():
    vf = FIN._title_card_vf("O'Brien: 20:30 \\ end")
    assert vf.startswith("drawtext=text='O\\'Brien\\: 20\\:30 / end':fontcolor=white:fontsize=48")


def test_title_card_vf_centres_the_text_and_fades_both_ends():
    vf = FIN._title_card_vf('Studio')
    assert ':x=(w-text_w)/2:y=(h-text_h)/2,' in vf
    assert vf.endswith('fade=type=in:start_time=0:duration=0.5,fade=type=out:start_time=2.5:duration=0.5')


def test_render_title_card_builds_a_three_second_black_card_with_silence(tmp_path):
    runner = Runner()
    card = str(tmp_path / 'card.mp4')
    FIN._render_title_card(runner, card, 'drawtext=…')
    argv = runner.calls[0]
    assert argv.count('lavfi') == 2
    assert 'color=c=black:s=1920x1080:r=30:d=3' in argv
    assert 'anullsrc=channel_layout=stereo:sample_rate=44100' in argv
    assert argv[argv.index('-t') + 1] == '3'
    assert argv[argv.index('-vf') + 1] == 'drawtext=…'
    assert argv[-1] == card


@pytest.mark.parametrize(('stdout', 'expected'), [(b'audio\n', True), (b'', False), (b'   \n', False)])
def test_main_video_has_audio_reads_the_codec_type_probe(stdout, expected):
    runner = Runner(stdout_for={'stream=codec_type': stdout})
    assert FIN._main_video_has_audio(runner, '/out/v.mp4') is expected
    assert runner.calls[0][0] == 'ffprobe'
    assert runner.calls[0][runner.calls[0].index('-select_streams') + 1] == 'a'


def test_concat_title_card_uses_the_filter_graph_when_the_video_has_audio(tmp_path):
    runner = Runner()
    titled = str(tmp_path / 't.mp4')
    FIN._concat_title_card(runner, str(tmp_path), '/v.mp4', '/c.mp4', titled, True)
    argv = runner.calls[0]
    assert argv[argv.index('-filter_complex') + 1] == '[0:v][0:a][1:v][1:a]concat=n=2:v=1:a=1[outv][outa]'
    assert not (tmp_path / 'concat_title.txt').exists()


def test_concat_title_card_falls_back_to_the_demuxer_without_audio(tmp_path):
    runner = Runner()
    titled = str(tmp_path / 't.mp4')
    FIN._concat_title_card(runner, str(tmp_path), '/v.mp4', '/c.mp4', titled, False)
    assert (tmp_path / 'concat_title.txt').read_text() == "file '/v.mp4'\nfile '/c.mp4'\n"
    argv = runner.calls[0]
    assert '-filter_complex' not in argv
    assert argv[argv.index('-i') + 1] == str(tmp_path / 'concat_title.txt')


def _card(tmp_path, runner):
    final = tmp_path / 'video.mp4'
    final.write_bytes(b'\0' * 2_000_000)
    log, stages, done = Log(), [], []
    FIN.append_ending_card('Zygomatic', str(final), str(tmp_path), 'abcdefgh', runner, log, stages.append, done.append)
    return final, log, stages, done


def test_append_ending_card_moves_the_titled_video_over_the_original(tmp_path):
    runner = Runner(write=lambda argv: 2_000_000)
    final, log, stages, done = _card(tmp_path, runner)
    assert stages == ['Ending Title Card'] and done == ['Ending Title Card']
    assert log.messages('INFO') == [
        'Appending studio card: "Zygomatic"',
        'Studio card appended: "Zygomatic"',
    ]
    assert not (tmp_path / 'title_card_abcdefgh.mp4').exists()
    assert not (tmp_path / 'video_titled.mp4').exists()
    assert final.exists()


def test_append_ending_card_leaves_the_video_alone_when_the_card_render_failed(tmp_path):
    final, log, _stages, done = _card(tmp_path, Runner(rc=1, write=0))
    assert final.read_bytes() == b'\0' * 2_000_000
    assert log.messages('WARNING') == ['Render failed — video unchanged: the stderr tail']
    assert done == ['Ending Title Card']


def test_append_ending_card_leaves_the_video_alone_when_the_concat_failed(tmp_path):
    def rc(argv):
        return 0 if 'title_card_abcdefgh.mp4' in argv[-1] else 1

    final, log, _stages, done = _card(tmp_path, Runner(rc=rc))
    assert final.read_bytes() == b'\0' * 2_000_000
    assert log.messages('WARNING') == ['Concat failed — video unchanged: the stderr tail']
    assert done == ['Ending Title Card']


def test_append_ending_card_warns_and_never_completes_the_stage_when_it_raises(tmp_path):
    class Boom(Runner):
        def run(self, argv, **kw):
            raise OSError('ffmpeg is gone')

    final, log, stages, done = _card(tmp_path, Boom())
    assert stages == ['Ending Title Card'] and done == []
    assert log.messages('WARNING') == ['Title card error: ffmpeg is gone']
    assert final.exists()


# ── The duration trim and the 4K master ─────────────────────────────────────


@pytest.mark.parametrize(('stdout', 'expected'), [(b'9.25\n', 9.25), (b'', 0.0), (b'  \n', 0.0)])
def test_probe_duration_reads_the_container_duration(stdout, expected):
    runner = Runner(stdout_for={'format=duration': stdout})
    assert FIN._probe_duration(runner, '/v.mp4') == expected


@pytest.fixture
def _wan(stub_module):
    """`wan_video_service`, stubbed to a fixed trim target."""

    def target(value):
        stub_module('wan_video_service', types.SimpleNamespace(final_trim_target_sec=lambda *a: value))

    return target


def _trim(tmp_path, runner, log):
    final = tmp_path / 'video.mp4'
    final.write_bytes(b'\0' * 2_000_000)
    FIN.trim_to_target(8.0, 4, 2, str(final), runner, log)
    return final


def test_trim_to_target_cuts_the_video_and_logs_both_durations(tmp_path, _wan):
    _wan(7.0)
    runner = Runner(stdout_for={'format=duration': b'9.00\n'})
    log = Log()
    final = _trim(tmp_path, runner, log)
    assert log.messages('INFO') == ['Trimmed final video to 7.00s (was 9.00s; requested 8.0s)']
    assert final.read_bytes() == b'\0' * 2_000_000
    assert not (tmp_path / 'video_trim.mp4').exists()
    argv = runner.calls[-1]
    assert argv[argv.index('-t') + 1] == '7.0'


def test_trim_to_target_leaves_a_video_inside_the_deadband_alone(tmp_path, _wan):
    """9.20 s against a 9.00 s target is within 0.25 s — never 3.8 down to 3.5."""
    _wan(9.0)
    runner = Runner(stdout_for={'format=duration': b'9.20\n'})
    log = Log()
    _trim(tmp_path, runner, log)
    assert log.lines == []
    assert len(runner.calls) == 1


def test_trim_to_target_does_nothing_when_there_is_no_target(tmp_path, _wan):
    _wan(0.0)
    runner = Runner()
    _trim(tmp_path, runner, Log())
    assert runner.calls == []


def test_trim_to_target_keeps_the_original_when_the_trim_came_out_tiny(tmp_path, _wan):
    _wan(7.0)
    runner = Runner(stdout_for={'format=duration': b'9.00\n'}, write=9_999)
    log = Log()
    final = _trim(tmp_path, runner, log)
    assert log.lines == []
    assert final.read_bytes() == b'\0' * 2_000_000


def test_trim_to_target_warns_when_the_service_is_unavailable(tmp_path, stub_module):
    stub_module('wan_video_service', None)
    log = Log()
    _trim(tmp_path, Runner(), log)
    assert log.messages('WARNING') and log.messages('WARNING')[0].startswith('Duration trim skipped: ')


def test_encode_master_upscales_to_4k_with_slow_crf15(tmp_path):
    final = tmp_path / 'video.mp4'
    final.write_bytes(b'\0' * 2_000_000)
    runner = Runner(write=11_000)
    log = Log()
    FIN.encode_master(str(final), 30.0, runner, log)
    argv = runner.calls[0]
    assert argv[argv.index('-vf') + 1] == 'scale=3840:2160:flags=lanczos'
    assert argv[argv.index('-preset') + 1] == 'slow'
    assert argv[argv.index('-crf') + 1] == '15'
    assert argv[-1] == str(tmp_path / 'video_master.mp4')
    assert log.messages('INFO') == [
        'Final encode: 4K upscale + slow/CRF15 for YouTube…',
        'Master ready: 3840×2160 slow/CRF15 — 0 MB',
    ]
    assert final.read_bytes() == b'\0' * 11_000
    assert not (tmp_path / 'video_master.mp4').exists()


def test_encode_master_scales_its_timeout_off_the_narration_length(tmp_path):
    runner = Runner(write=11_000)
    captured = {}
    original = runner.run

    def run(argv, **kw):
        captured.update(kw)
        return original(argv, **kw)

    final = tmp_path / 'video.mp4'
    final.write_bytes(b'x')
    FIN.encode_master(str(final), 30.0, types.SimpleNamespace(run=run), Log())
    assert captured['timeout'] == 840


def test_encode_master_keeps_the_lossless_source_and_cleans_up_on_failure(tmp_path):
    final = tmp_path / 'video.mp4'
    final.write_bytes(b'lossless')
    runner = Runner(rc=1, write=500)
    log = Log()
    FIN.encode_master(str(final), 30.0, runner, log)
    assert final.read_bytes() == b'lossless'
    assert not (tmp_path / 'video_master.mp4').exists()
    assert log.messages('WARNING') == ['4K encode failed — keeping lossless source: the stderr tail']


# ── The thumbnail ───────────────────────────────────────────────────────────


def _still(path, side, rgb=(10, 20, 30)):
    Image.new('RGB', (side, side), rgb).save(path)
    return str(path)


def test_save_thumbnail_letterboxes_the_richest_still_into_1280x720(tmp_path):
    small = _still(tmp_path / 'a.png', 64)
    big = _still(tmp_path / 'b.png', 1400, rgb=(200, 10, 10))
    log = Log()
    FIN.save_thumbnail(str(tmp_path), [small, big], log)
    out = tmp_path / '_thumbnail.jpg'
    with Image.open(out) as im:
        assert im.size == (1280, 720)
        assert im.getpixel((2, 2)) == (0, 0, 0)
    assert log.messages('INFO') == ['Saved _thumbnail.jpg from b.png']


def test_save_thumbnail_falls_back_to_the_largest_small_still(tmp_path):
    tiny = _still(tmp_path / 'a.png', 8)
    bigger = _still(tmp_path / 'b.png', 40)
    log = Log()
    FIN.save_thumbnail(str(tmp_path), [tiny, bigger], log)
    assert log.messages('INFO') == ['Saved _thumbnail.jpg from b.png']


def test_save_thumbnail_never_overwrites_an_existing_thumbnail(tmp_path):
    (tmp_path / '_thumbnail.jpg').write_bytes(b'kept')
    FIN.save_thumbnail(str(tmp_path), [_still(tmp_path / 'a.png', 64)], Log())
    assert (tmp_path / '_thumbnail.jpg').read_bytes() == b'kept'


def test_save_thumbnail_does_nothing_without_scene_images(tmp_path):
    log = Log()
    FIN.save_thumbnail(str(tmp_path), [], log)
    assert not (tmp_path / '_thumbnail.jpg').exists()
    assert log.lines == []


def test_save_thumbnail_warns_when_the_still_is_not_an_image(tmp_path):
    broken = tmp_path / 'a.png'
    broken.write_bytes(b'not an image')
    log = Log()
    FIN.save_thumbnail(str(tmp_path), [str(broken)], log)
    assert log.messages('WARNING') and log.messages('WARNING')[0].startswith('Thumbnail generation skipped: ')


# ── The prop-persistence advisory ───────────────────────────────────────────


def test_report_prop_persistence_lists_the_failing_props_per_scene_in_key_order():
    job = {
        '_prop_persistence': {
            1: {'verdicts': {'lantern': {'persistent': False}, 'sword': {'persistent': True}}},
            0: {'verdicts': {'helm': {'persistent': False}}},
        }
    }
    log = Log()
    FIN.report_prop_persistence(job, log)
    note = (
        '⚠️ ADVISORY: prop persistence below threshold — '
        'scene 1: helm; scene 2: lantern — '
        'planned prop(s) not visible across the clip (non-fatal, video kept).'
    )
    assert job['warnings'] == [note]
    assert log.lines == [('WARNING', 'Stage 6', note)]


def test_report_prop_persistence_says_nothing_when_every_prop_held():
    job = {'_prop_persistence': {0: {'verdicts': {'helm': {'persistent': True}}}}}
    log = Log()
    FIN.report_prop_persistence(job, log)
    assert 'warnings' not in job
    assert log.lines == []


def test_report_prop_persistence_appends_to_warnings_that_are_already_there():
    job = {'warnings': ['earlier'], '_prop_persistence': {0: {'verdicts': {'helm': {'persistent': False}}}}}
    FIN.report_prop_persistence(job, Log())
    assert len(job['warnings']) == 2 and job['warnings'][0] == 'earlier'


def test_report_prop_persistence_is_a_no_op_without_a_record():
    log = Log()
    FIN.report_prop_persistence({}, log)
    assert log.lines == []


def test_report_prop_persistence_warns_instead_of_raising_on_a_malformed_record():
    log = Log()
    FIN.report_prop_persistence({'_prop_persistence': {'not a number': {'verdicts': {'x': {}}}}}, log)
    assert log.messages('WARNING')[0].startswith('Prop-persistence report aggregation failed: ')
