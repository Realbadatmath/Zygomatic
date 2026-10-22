# SPDX-FileCopyrightText: 2026 Zygomatic
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Coverage tests for the ffmpeg wrappers in `video_studio.ffmpeg_finish`.

Everything in that module shells out to ffmpeg/ffprobe, so none of it had ever
been exercised — `test_ffmpeg_finish_helpers.py` covers the pure filtergraph
builders in the sibling `ffmpeg_finish_post`. Here `subprocess.run` and the
module's own `_run_ff` are fakes that record the argv they were handed and
return canned exit codes, so every branch is asserted on the command it builds
and the log line it writes, offline and with no ffmpeg installed.
"""

import json
import os
import types

import numpy as np
import pytest
from PIL import Image

from zyg_workflows import video_studio
from zyg_workflows.video_studio import ffmpeg_finish as mod


def _p(**over):
    """A sanitised Video Studio parameter dict with the named dials changed."""
    return video_studio.sanitize(dict(over))


def _done(returncode=0, stdout=b'', stderr=b''):
    return types.SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)


def _png(path, flat=False):
    """An 8x8 RGB png: flat grey (std 0) or half-bright (std well over 3)."""
    a = np.full((8, 8, 3), 128, dtype=np.uint8)
    if not flat:
        a[:, :4] = 20
    Image.fromarray(a).save(str(path))
    return str(path)


def _recorder(returncode=0, stdout=b'', stderr=b''):
    """A subprocess.run stand-in that records argv and returns a fixed result."""
    seen = []

    def run(args, **kw):
        seen.append(list(args))
        return _done(returncode, stdout, stderr)

    return seen, run


# ── _color_match_filter ────────────────────────────────────────────────────
def test_color_match_filter_emits_a_lutrgb_per_channel(monkeypatch, tmp_path):
    ref = _png(tmp_path / 'seed.png')
    clip = str(tmp_path / 'clip.mp4')
    seen = []

    def run(args, **kw):
        seen.append(list(args))
        _png(args[-1])
        return _done(0)

    monkeypatch.setattr(mod.subprocess, 'run', run)
    lines = []
    out = mod._color_match_filter(ref, clip, lines.append)
    assert seen[0][1:6] == ['-y', '-v', 'error', '-i', clip]
    assert seen[0][-3:-1] == ['-frames:v', '1']
    assert out.startswith('lutrgb=')
    assert [part.split('=')[0] for part in out[len('lutrgb=') :].split(':')] == ['r', 'g', 'b']
    assert 'clip(val*' in out
    assert lines[0].startswith('colour match to the seed frame: ')
    assert not os.path.isfile(clip + '.f0.png'), 'the probe frame is removed again'


def test_color_match_filter_still_matches_when_the_probe_frame_will_not_delete(monkeypatch, tmp_path):
    ref = _png(tmp_path / 'seed.png')

    def run(args, **kw):
        _png(args[-1])
        # patched only after the probe frame exists, so the read still succeeds
        monkeypatch.setattr(os, 'remove', lambda path: (_ for _ in ()).throw(OSError('read-only')))
        return _done(0)

    monkeypatch.setattr(mod.subprocess, 'run', run)
    lines = []
    assert mod._color_match_filter(ref, str(tmp_path / 'clip.mp4'), lines.append).startswith('lutrgb=')
    assert lines[0].startswith('colour match to the seed frame: ')


def test_color_match_filter_skips_when_frame_zero_cannot_be_read(monkeypatch, tmp_path):
    monkeypatch.setattr(mod.subprocess, 'run', lambda args, **kw: _done(1))
    lines = []
    assert mod._color_match_filter(_png(tmp_path / 'seed.png'), str(tmp_path / 'clip.mp4'), lines.append) == ''
    assert lines == ['colour match skipped — could not read frame 0 of the render']


def test_color_match_filter_refuses_to_match_against_a_near_flat_frame(monkeypatch, tmp_path):
    ref = _png(tmp_path / 'seed.png', flat=True)

    def run(args, **kw):
        _png(args[-1], flat=True)
        return _done(0)

    monkeypatch.setattr(mod.subprocess, 'run', run)
    lines = []
    assert mod._color_match_filter(ref, str(tmp_path / 'clip.mp4'), lines.append) == ''
    assert len(lines) == 1
    assert lines[0].startswith('colour match skipped — the seed frame')


def test_color_match_filter_swallows_an_unreadable_seed_frame(monkeypatch, tmp_path):
    def run(args, **kw):
        _png(args[-1])
        return _done(0)

    monkeypatch.setattr(mod.subprocess, 'run', run)
    lines = []
    assert mod._color_match_filter(str(tmp_path / 'absent.png'), str(tmp_path / 'clip.mp4'), lines.append) == ''
    assert lines[0].startswith('colour match skipped (')


# ── _probe ────────────────────────────────────────────────────────────────
def test_probe_reads_the_size_and_the_duration_off_ffprobe_json(monkeypatch):
    payload = json.dumps({'streams': [{'width': 1920, 'height': 1080}], 'format': {'duration': '6.25'}}).encode()
    seen, run = _recorder(stdout=payload)
    monkeypatch.setattr(mod.subprocess, 'run', run)
    assert mod._probe('/a/clip.mp4') == {'w': 1920, 'h': 1080, 'dur': 6.25}
    assert seen[0][0].endswith('ffprobe')
    assert seen[0][-1] == '/a/clip.mp4'
    assert 'stream=width,height:format=duration' in seen[0]


def test_probe_defaults_every_field_an_empty_report_omits(monkeypatch):
    _s, run = _recorder(stdout=b'{}')
    monkeypatch.setattr(mod.subprocess, 'run', run)
    assert mod._probe('/a/clip.mp4') == {'w': 0, 'h': 0, 'dur': 0.0}


def test_probe_returns_nothing_when_ffprobe_printed_no_json(monkeypatch):
    _s, run = _recorder(stdout=b'not json at all')
    monkeypatch.setattr(mod.subprocess, 'run', run)
    assert mod._probe('/a/clip.mp4') == {}


def test_probe_returns_nothing_when_ffprobe_is_missing(monkeypatch):
    def run(args, **kw):
        raise OSError('No such file or directory: ffprobe')

    monkeypatch.setattr(mod.subprocess, 'run', run)
    assert mod._probe('/a/clip.mp4') == {}


# ── _run_ff ───────────────────────────────────────────────────────────────
def test_run_ff_is_true_and_silent_on_a_clean_exit(monkeypatch):
    seen, run = _recorder()
    monkeypatch.setattr(mod.subprocess, 'run', run)
    lines = []
    assert mod._run_ff(['ffmpeg', '-y'], lines.append, 'tag') is True
    assert (seen, lines) == ([['ffmpeg', '-y']], [])


def test_run_ff_logs_only_the_last_two_stderr_lines(monkeypatch):
    err = b'first\nsecond\nthird\nfourth\n'
    _s, run = _recorder(returncode=234, stderr=err)
    monkeypatch.setattr(mod.subprocess, 'run', run)
    lines = []
    assert mod._run_ff(['ffmpeg'], lines.append, 'bloom') is False
    assert lines == ['bloom failed (rc=234): third | fourth']


def test_run_ff_reports_the_exception_rather_than_raising(monkeypatch):
    def run(args, **kw):
        raise mod.subprocess.TimeoutExpired('ffmpeg', 900)

    monkeypatch.setattr(mod.subprocess, 'run', run)
    lines = []
    assert mod._run_ff(['ffmpeg'], lines.append, 'stabilise') is False
    assert lines[0].startswith('stabilise error: ')


# ── _stabilize ────────────────────────────────────────────────────────────
def test_stabilize_runs_detect_then_transform_and_cleans_the_trf(monkeypatch, tmp_path):
    src, dst = str(tmp_path / 'in.mp4'), str(tmp_path / 'out.mp4')
    open(src + '.trf', 'w').close()
    seen = []
    monkeypatch.setattr(mod, '_run_ff', lambda args, log, tag, **kw: seen.append((tag, args)) or True)
    assert mod._stabilize(src, dst, print) is True
    assert [tag for tag, _a in seen] == ['stabilise (detect)', 'stabilise (transform)']
    assert f'vidstabdetect=shakiness=6:accuracy=12:result={src}.trf' in seen[0][1]
    assert f'vidstabtransform=input={src}.trf:zoom=1:smoothing=24,unsharp=5:5:0.3' in seen[1][1]
    assert seen[1][1][-1] == dst
    assert not os.path.isfile(src + '.trf')


def test_stabilize_survives_a_trf_that_was_never_written(monkeypatch, tmp_path):
    src = str(tmp_path / 'in.mp4')
    monkeypatch.setattr(mod, '_run_ff', lambda *a, **kw: True)
    assert mod._stabilize(src, str(tmp_path / 'out.mp4'), print) is True


def test_stabilize_does_not_transform_when_the_detect_pass_failed(monkeypatch, tmp_path):
    seen = []
    monkeypatch.setattr(mod, '_run_ff', lambda args, log, tag, **kw: seen.append(tag) or False)
    assert mod._stabilize(str(tmp_path / 'in.mp4'), str(tmp_path / 'out.mp4'), print) is False
    assert seen == ['stabilise (detect)']


# ── _loop_pass ────────────────────────────────────────────────────────────
def test_loop_pass_pingpong_reverses_then_concats_and_cleans_up(monkeypatch, tmp_path):
    src, dst = str(tmp_path / 'in.mp4'), str(tmp_path / 'out.mp4')
    seen, lists = [], []

    def run_ff(args, log, tag, **kw):
        seen.append((tag, args))
        if tag == 'ping-pong (concat)':
            lists.append(open(args[args.index('-i') + 1]).read())
        return True

    monkeypatch.setattr(mod, '_run_ff', run_ff)
    assert mod._loop_pass(src, dst, 'pingpong', print) is True
    assert [tag for tag, _a in seen] == ['ping-pong (reverse)', 'ping-pong (concat)']
    assert seen[0][1][-1] == str(tmp_path / '_pp_rev.mp4')
    assert lists == [f"file '{src}'\nfile '{tmp_path / '_pp_rev.mp4'}'\n"]
    assert not os.path.isfile(tmp_path / '_pp_list.txt'), 'the concat list is removed again'


def test_loop_pass_pingpong_stops_when_the_reverse_failed(monkeypatch, tmp_path):
    monkeypatch.setattr(mod, '_run_ff', lambda *a, **kw: False)
    assert mod._loop_pass(str(tmp_path / 'in.mp4'), str(tmp_path / 'out.mp4'), 'pingpong', print) is False
    assert not os.path.isfile(tmp_path / '_pp_list.txt')


@pytest.mark.parametrize(('mode', 'repeats'), [('x2', 2), ('x3', 3)])
def test_loop_pass_concats_the_clip_n_times(monkeypatch, tmp_path, mode, repeats):
    src, dst = str(tmp_path / 'in.mp4'), str(tmp_path / 'out.mp4')
    bodies = []

    def run_ff(args, log, tag, **kw):
        bodies.append((tag, open(args[args.index('-i') + 1]).read()))
        return True

    monkeypatch.setattr(mod, '_run_ff', run_ff)
    assert mod._loop_pass(src, dst, mode, print) is True
    assert bodies == [('loop (concat)', f"file '{src}'\n" * repeats)]
    assert not os.path.isfile(tmp_path / '_loop_list.txt')


def test_loop_pass_refuses_a_mode_that_is_not_a_loop(monkeypatch, tmp_path):
    monkeypatch.setattr(mod, '_run_ff', lambda *a, **kw: pytest.fail('nothing to loop'))
    assert mod._loop_pass(str(tmp_path / 'in.mp4'), str(tmp_path / 'out.mp4'), 'off', print) is False


def test_loop_pass_keeps_going_when_the_concat_list_vanished(monkeypatch, tmp_path):
    def run_ff(args, log, tag, **kw):
        os.remove(args[args.index('-i') + 1])
        return True

    monkeypatch.setattr(mod, '_run_ff', run_ff)
    assert mod._loop_pass(str(tmp_path / 'in.mp4'), str(tmp_path / 'out.mp4'), 'x2', print) is True


# ── _esc_dt / _grade_chain ────────────────────────────────────────────────
def test_esc_dt_escapes_every_character_drawtext_parses():
    assert mod._esc_dt(r"a:b'c%d\e") == r'a\:b\'c\%d\\\\e'
    assert mod._esc_dt('') == ''
    assert mod._esc_dt('plain text') == 'plain text'
    # the backslash has to be escaped first: were it done last, the escape this
    # colon just grew would itself be doubled and drawtext would read a literal.
    assert mod._esc_dt('\\:') == r'\\\\\:'


def test_grade_chain_is_empty_at_the_defaults():
    assert mod._grade_chain(_p()) == ([], [])


def test_grade_chain_orders_the_rack_the_way_a_colourist_works(monkeypatch, tmp_path):
    monkeypatch.setattr(mod, '_LUT_DIR', str(tmp_path))
    (tmp_path / 'look.cube').write_text('LUT_3D_SIZE 2\n')
    dials = dict(color_temp=4000.0, tint=0.2, lift=0.1, brightness=0.1, contrast=1.2, saturation=1.3)
    dials.update(gamma=0.9, vibrance=0.4, hue_shift=30.0, lut='look.cube')
    chain, notes = mod._grade_chain({**_p(), **dials})
    assert chain == [
        'colortemperature=temperature=4000',
        'colorbalance=gm=0.200:gs=0.100:gh=0.100',
        "curves=all='0/0.100 1/1'",
        'eq=brightness=0.100:contrast=1.200:saturation=1.300:gamma=0.900',
        'vibrance=intensity=0.400',
        'hue=h=30.0',
        'lut3d=file=' + str(tmp_path / 'look.cube'),
    ]
    assert notes == [
        'temp 4000K',
        'tint +0.20',
        'lift +0.10',
        'brightness 0.1',
        'contrast 1.2',
        'saturation 1.3',
        'gamma 0.9',
        'vibrance 0.4',
        'hue 30deg',
        'lut look.cube',
    ]


def test_grade_chain_clamps_the_lift_at_half_and_takes_the_basename_of_the_lut(monkeypatch, tmp_path):
    monkeypatch.setattr(mod, '_LUT_DIR', str(tmp_path))
    (tmp_path / 'look.cube').write_text('LUT_3D_SIZE 2\n')
    chain, _n = mod._grade_chain({**_p(), 'lift': 0.9, 'lut': '/etc/passwd/../look.cube'})
    assert chain[0] == "curves=all='0/0.500 1/1'"
    assert chain[1] == 'lut3d=file=' + str(tmp_path / 'look.cube'), 'the LUT can only come from _LUT_DIR'


def test_grade_chain_skips_a_lut_that_is_not_on_disk(monkeypatch, tmp_path):
    monkeypatch.setattr(mod, '_LUT_DIR', str(tmp_path))
    assert mod._grade_chain({**_p(), 'lut': 'absent.cube'}) == ([], [])


# ── _bloom_pass ───────────────────────────────────────────────────────────
def test_bloom_pass_splits_the_stream_and_screens_the_blur_back(monkeypatch):
    seen = []
    monkeypatch.setattr(mod, '_run_ff', lambda args, log, tag, **kw: seen.append((tag, args)) or True)
    assert mod._bloom_pass('/a/in.mp4', '/a/out.mp4', 0.4, print, crf=14) is True
    tag, args = seen[0]
    assert tag == 'bloom'
    graph = args[args.index('-filter_complex') + 1]
    assert graph == 'split[a][b];[b]gblur=sigma=10.0[bb];[a][bb]blend=all_mode=screen:all_opacity=0.400'
    assert args[args.index('-crf') + 1] == '14'
    assert args[-1] == '/a/out.mp4'


# ── _detect ───────────────────────────────────────────────────────────────
def test_detect_keeps_only_the_lines_its_own_filter_printed(monkeypatch):
    err = (
        '[blackdetect @ 0x1] black_start:0 black_end:1.2 black_duration:1.2\n'
        '[Parsed_blackdetect_0 @ 0x2] lavfi something else\n'
        '[Parsed_blackdetect_0] unrelated chatter\n'
        'frame=  120 fps=0.0 q=-1.0\n'
    )
    seen = []

    def run(args, **kw):
        seen.append(list(args))
        return _done(0, stdout='', stderr=err)

    monkeypatch.setattr(mod.subprocess, 'run', run)
    out = mod._detect('/a/clip.mp4', 'blackdetect=d=0.1:pix_th=0.10', print)
    assert out == [
        '[blackdetect @ 0x1] black_start:0 black_end:1.2 black_duration:1.2',
        '[Parsed_blackdetect_0 @ 0x2] lavfi something else',
    ]
    assert seen[0][-3:] == ['-f', 'null', '-'], 'the null muxer writes nothing; the measurement is the stderr'
    assert 'blackdetect=d=0.1:pix_th=0.10' in seen[0]


def test_detect_logs_the_filter_name_when_ffmpeg_could_not_run(monkeypatch):
    def run(args, **kw):
        raise OSError('ffmpeg not found')

    monkeypatch.setattr(mod.subprocess, 'run', run)
    lines = []
    assert mod._detect('/a/clip.mp4', 'scdet=threshold=10', lines.append) == []
    assert lines == ['qc: scdet failed: ffmpeg not found']


# ── _side_exports ─────────────────────────────────────────────────────────
def _writing_run_ff(seen):
    """A _run_ff stand-in that pretends ffmpeg wrote its output file."""

    def run_ff(args, log, tag, **kw):
        seen.append((tag, list(args)))
        open(args[-1], 'wb').close()
        return True

    return run_ff


def test_side_exports_writes_nothing_at_the_defaults(monkeypatch):
    monkeypatch.setattr(mod, '_probe', lambda path: {'w': 0, 'h': 0, 'dur': 4.0})
    monkeypatch.setattr(mod, '_run_ff', lambda *a, **kw: pytest.fail('no side export is on'))
    assert mod._side_exports('/a/clip.mp4', _p(), print) == []


def test_side_exports_writes_and_names_every_deliverable(monkeypatch, tmp_path):
    clip = str(tmp_path / 'clip.mp4')
    base = str(tmp_path / 'clip')
    monkeypatch.setattr(mod, '_probe', lambda path: {'w': 1920, 'h': 1080, 'dur': 4.0})
    seen = []
    monkeypatch.setattr(mod, '_run_ff', _writing_run_ff(seen))
    lines = []
    on = dict(gif_export=True, webp_export=True, poster_frame=True, contact_sheet=True, probe_report=True)
    wrote = mod._side_exports(clip, {**_p(), **on, 'scope_export': 'waveform'}, lines.append)
    assert wrote == [
        base + '.gif',
        base + '.webp',
        base + '.poster.png',
        base + '.sheet.png',
        base + '.waveform.png',
        base + '.probe.json',
    ]
    assert [tag for tag, _a in seen] == ['gif palette', 'gif', 'webp', 'poster', 'contact sheet', 'scope']
    assert not os.path.isfile(base + '.pal.png'), 'the palette is an intermediate, not a deliverable'
    assert seen[1][1][seen[1][1].index('-lavfi') + 1].endswith('[x];[x][1:v]paletteuse')
    assert seen[3][1][seen[3][1].index('-ss') + 1] == '2.000', 'the poster is the middle frame'
    assert seen[4][1][seen[4][1].index('-vf') + 1] == 'fps=2.5000,scale=320:-1,tile=5x2'
    assert seen[5][1][seen[5][1].index('-vf') + 1] == 'waveform=intensity=0.1:mirror=1:display=overlay'
    assert lines == ['qc: probe report written']
    assert json.loads(open(base + '.probe.json').read()) == {'w': 1920, 'h': 1080, 'dur': 4.0}


@pytest.mark.parametrize('scope', ['vectorscope', 'histogram'])
def test_side_exports_picks_the_scope_the_dial_names(monkeypatch, tmp_path, scope):
    monkeypatch.setattr(mod, '_probe', lambda path: {'dur': 2.0})
    seen = []
    monkeypatch.setattr(mod, '_run_ff', _writing_run_ff(seen))
    wrote = mod._side_exports(str(tmp_path / 'clip.mp4'), {**_p(), 'scope_export': scope}, print)
    assert wrote == [str(tmp_path / f'clip.{scope}.png')]
    assert seen[0][1][seen[0][1].index('-vf') + 1].startswith(scope)


def test_side_exports_names_no_file_a_failed_ffmpeg_did_not_write(monkeypatch, tmp_path):
    monkeypatch.setattr(mod, '_probe', lambda path: {'dur': 4.0})
    seen = []
    monkeypatch.setattr(mod, '_run_ff', lambda args, log, tag, **kw: seen.append(tag) or False)
    on = dict(gif_export=True, webp_export=True, poster_frame=True, contact_sheet=True, scope_export='histogram')
    assert mod._side_exports(str(tmp_path / 'clip.mp4'), {**_p(), **on}, print) == []
    assert seen == ['gif palette', 'webp', 'poster', 'contact sheet', 'scope'], 'no palette, no gif attempt'


def test_side_exports_drops_the_gif_when_only_the_second_pass_failed(monkeypatch, tmp_path):
    monkeypatch.setattr(mod, '_probe', lambda path: {'dur': 4.0})
    seen = []

    def run_ff(args, log, tag, **kw):
        seen.append(tag)
        return tag == 'gif palette'

    monkeypatch.setattr(mod, '_run_ff', run_ff)
    assert mod._side_exports(str(tmp_path / 'clip.mp4'), {**_p(), 'gif_export': True}, print) == []
    assert seen == ['gif palette', 'gif']


def test_side_exports_floors_the_duration_so_the_sheet_fps_is_finite(monkeypatch, tmp_path):
    monkeypatch.setattr(mod, '_probe', lambda path: {'dur': 0.0})
    seen = []
    monkeypatch.setattr(mod, '_run_ff', _writing_run_ff(seen))
    mod._side_exports(str(tmp_path / 'clip.mp4'), {**_p(), 'contact_sheet': True}, print)
    assert seen[0][1][seen[0][1].index('-vf') + 1] == 'fps=100.0000,scale=320:-1,tile=5x2'


def test_side_exports_logs_a_probe_report_it_could_not_write(monkeypatch, tmp_path):
    monkeypatch.setattr(mod, '_probe', lambda path: {'dur': 4.0})
    lines = []
    clip = str(tmp_path / 'absent' / 'clip.mp4')
    assert mod._side_exports(clip, {**_p(), 'probe_report': True}, lines.append) == []
    assert len(lines) == 1
    assert lines[0].startswith('qc: probe report failed: ')


# ── _motion_series ────────────────────────────────────────────────────────
def test_motion_series_writes_the_per_frame_curve_beside_the_clip(monkeypatch, tmp_path):
    out = (
        'frame:0 pts:0 pts_time:0\n'
        'lavfi.signalstats.YAVG=25.5\n'
        'frame:1 pts:1 pts_time:0.04\n'
        'lavfi.signalstats.YAVG=51.0\n'
        'lavfi.signalstats.YAVG=not-a-number\n'
    )
    seen = []

    def run(args, **kw):
        seen.append(list(args))
        return _done(0, stdout=out, stderr='')

    monkeypatch.setattr(mod.subprocess, 'run', run)
    clip = str(tmp_path / 'clip.mp4')
    lines = []
    series = mod._motion_series(clip, lines.append)
    assert series == [0.1, 0.2]
    assert 'tblend=all_mode=difference,signalstats' in seen[0][seen[0].index('-vf') + 1]
    written = json.loads((tmp_path / 'clip.motion.json').read_text())
    assert written == {
        'per_frame_abs_diff': [0.1, 0.2],
        'mean': 0.15,
        'min': 0.1,
        'max': 0.2,
        'min_at_frame': 1,
        'frames': 3,
    }
    assert lines == ['qc: motion log written — mean 0.1500, quietest frame 1 at 0.1000']


def test_motion_series_says_so_when_ffmpeg_reported_no_frames(monkeypatch, tmp_path):
    monkeypatch.setattr(mod.subprocess, 'run', lambda args, **kw: _done(0, stdout='', stderr=''))
    lines = []
    assert mod._motion_series(str(tmp_path / 'clip.mp4'), lines.append) == []
    assert lines == ['qc: motion log — ffmpeg reported no frames']
    assert not os.path.isfile(tmp_path / 'clip.motion.json')


def test_motion_series_still_returns_the_curve_it_could_not_save(monkeypatch, tmp_path):
    monkeypatch.setattr(
        mod.subprocess, 'run', lambda args, **kw: _done(0, stdout='lavfi.signalstats.YAVG=12.75\n', stderr='')
    )
    lines = []
    assert mod._motion_series(str(tmp_path / 'absent' / 'clip.mp4'), lines.append) == [0.05]
    assert lines[-1].startswith('qc: motion log failed: ')


def test_motion_series_logs_an_ffmpeg_that_would_not_start(monkeypatch, tmp_path):
    def run(args, **kw):
        raise mod.subprocess.SubprocessError('boom')

    monkeypatch.setattr(mod.subprocess, 'run', run)
    lines = []
    assert mod._motion_series(str(tmp_path / 'clip.mp4'), lines.append) == []
    assert lines == ['qc: motion log failed: boom']


# ── _audio_spec ───────────────────────────────────────────────────────────
def test_audio_spec_is_empty_with_neither_a_bed_nor_a_cue():
    assert mod._audio_spec(_p()) == {}


def test_audio_spec_puts_the_bed_file_override_over_the_library_pick():
    spec = mod._audio_spec({**_p(), 'audio_bed_path': ' /a/bed.wav ', 'audio_bed': 'rain'})
    assert spec['bed']['file'] == '/a/bed.wav'
    assert spec['bed']['gain_db'] == -8.0
    assert spec['bed']['fade_in_s'] == 0.5
    assert spec['bed']['loop'] is True
    assert spec['cues'] == []
    assert spec['target_lufs'] == -14.0


def test_audio_spec_falls_back_on_the_library_dropdown():
    assert mod._audio_spec({**_p(), 'audio_bed': 'rain'})['bed']['file'] == 'rain'


def test_audio_spec_bed_fade_out_of_zero_follows_the_picture():
    spec = mod._audio_spec({**_p(), 'audio_bed': 'rain', 'audio_fade_out': 0.0, 'fade_out': 1.5})
    assert spec['bed']['fade_out_s'] == 1.5
    own = mod._audio_spec({**_p(), 'audio_bed': 'rain', 'audio_fade_out': 2.5, 'fade_out': 1.5})
    assert own['bed']['fade_out_s'] == 2.5


def test_audio_spec_keeps_the_cues_without_a_bed():
    spec = mod._audio_spec({**_p(), 'audio_cues': '[{"file": "door.wav", "at": 1.0}, 7]'})
    assert spec == {'cues': [{'file': 'door.wav', 'at': 1.0}], 'target_lufs': -14.0}
    assert 'bed' not in spec, 'nothing to bed, so no bed block'


@pytest.mark.parametrize('cues', ['{not json', '{"a": 1}', '7', None])
def test_audio_spec_treats_an_unusable_cue_list_as_no_cues(cues):
    assert mod._audio_spec({**_p(), 'audio_cues': cues}) == {}


# ── _post_process, the running order ──────────────────────────────────────
def _stub_post(monkeypatch, calls, ok=True, alt='/a/clip.h265.mp4', sides=()):
    """Replace every stage _post_process calls with a recorder."""
    from zyg_workflows.video_studio import ffmpeg_finish_post as fp

    plan = types.SimpleNamespace(master_crf=12)
    monkeypatch.setattr(fp, 'pre_passes', lambda path, p, log: calls.append('pre_passes') or True)
    monkeypatch.setattr(mod, '_probe', lambda path: {'w': 1920, 'h': 1080, 'dur': 6.0})
    monkeypatch.setattr(
        fp, 'filter_chain', lambda *a: calls.append('filter_chain') or (['hflip'], ['flip h'], 1920, 1080, 5.0)
    )
    monkeypatch.setattr(fp, 'encode_master', lambda *a: calls.append('encode_master') or (plan, ok))
    for name in ('bloom_and_loop', 'vfx_pass', 'overlay_pass', 'audio_pass'):
        monkeypatch.setattr(fp, name, (lambda n: lambda *a: calls.append(n))(name))
    monkeypatch.setattr(fp, 'delivery_encode', lambda *a: calls.append('delivery_encode') or alt)
    monkeypatch.setattr(mod, '_side_exports', lambda path, p, log: calls.append('side_exports') or list(sides))
    return plan


def test_post_process_runs_every_stage_in_order_and_seals_the_master(monkeypatch):
    calls, sealed, derived = [], [], []
    sides = ['/a/clip.gif', '/a/clip.probe.json', '']
    _stub_post(monkeypatch, calls, sides=sides)
    monkeypatch.setattr(mod._seal, 'seal', lambda path, **kw: sealed.append((path, kw.get('run_id'))) or {})
    monkeypatch.setattr(mod._seal, 'seal_derived', lambda path, master, **kw: derived.append((path, master)) or {})
    mod._post_process('/a/clip.mp4', _p(), print, pre_filter='lutrgb=r=val', run_id='run-7')
    order = 'pre_passes filter_chain encode_master bloom_and_loop vfx_pass overlay_pass audio_pass delivery_encode'
    assert calls == order.split() + ['side_exports']
    assert sealed == [('/a/clip.mp4', 'run-7')]
    assert derived == [
        ('/a/clip.h265.mp4', '/a/clip.mp4'),
        ('/a/clip.gif', '/a/clip.mp4'),
    ], 'the .json side report is not a media deliverable, and the empty alt is skipped'


def test_post_process_stops_and_seals_nothing_when_the_master_encode_failed(monkeypatch):
    calls = []
    _stub_post(monkeypatch, calls, ok=False)
    monkeypatch.setattr(mod._seal, 'seal', lambda *a, **kw: pytest.fail('nothing was finished'))
    mod._post_process('/a/clip.mp4', _p(), print)
    assert calls == ['pre_passes', 'filter_chain', 'encode_master']
