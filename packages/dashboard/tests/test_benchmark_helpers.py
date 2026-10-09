# SPDX-FileCopyrightText: 2026 Zygomatic
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Unit tests for the helpers gamesim._run_benchmark_bg was split into.

The 420-line original drove Xvfb, a game server, two ffmpeg captures and a sampling
loop, so none of its grading, parsing or state handling could be reached from a test.
These cover the pure parts of ``benchmark_stages`` plus the state transitions against a
throwaway state dict — never the real ``_bench_state``.
"""

import threading

import pytest

from zyg_dashboard.hub.gamesim import benchmark_stages as bs


@pytest.fixture
def run():
    """A BenchRun over a private state dict, collecting its debug lines in a list."""
    state = {
        'running': False,
        'phase': 'idle',
        'current_game': None,
        'current_idx': 0,
        'total': 0,
        'live': {},
        'results': [],
        'started_at': None,
        'debug_log': [],
        'frames_folder': None,
    }
    obj = bs.BenchRun(
        state=state,
        lock=threading.Lock(),
        dbg=lambda msg: state['debug_log'].append(msg),
        sample=lambda pids: (0.0, 0.0, 0.0, 0.0),
        duration=1,
        display=99,
    )
    return obj


# ── verdict_for ──────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ('status', 'peak_cpu', 'peak_ram', 'verdict'),
    [
        ('error', 5.0, 100.0, 'failed'),
        ('no_folder', 5.0, 100.0, 'failed'),
        ('ok', 95.0, 100.0, 'heavy'),
        ('ok', 5.0, 25000.0, 'heavy'),
        ('ok', 70.0, 100.0, 'acceptable'),
        ('ok', 5.0, 9000.0, 'acceptable'),
        ('ok', 65.0, 8000.0, 'smooth'),
        ('ok', 0.0, 0.0, 'smooth'),
    ],
)
def test_the_worse_of_the_two_peaks_decides_the_verdict(status, peak_cpu, peak_ram, verdict):
    assert bs.verdict_for(status, peak_cpu, peak_ram) == verdict


# ── summarise ────────────────────────────────────────────────────────────────


def test_summarise_writes_averages_peaks_and_the_verdict_in_place():
    series = bs.Series(cpu=[10.0, 20.0, 31.0], ram=[100.0, 300.0], gpu=[5.0], vram=[1.0, 2.0])
    result = bs.blank_result('Minecraft Dig FP', 'minecraft_dig_fp')
    result['status'] = 'ok'

    bs.summarise(result, series)

    assert result['avg_cpu'] == 20.3
    assert result['peak_cpu'] == 31.0
    assert result['avg_ram'] == 200.0
    assert result['peak_ram'] == 300.0
    assert result['avg_gpu'] == 5.0
    assert result['avg_vram'] == 1.5
    assert result['verdict'] == 'smooth'


def test_a_run_that_sampled_nothing_summarises_to_zeros_and_stays_failed():
    result = bs.blank_result('Minecraft Build FP', 'minecraft_build_fp')

    bs.summarise(result, bs.Series())

    assert result['peak_cpu'] == 0.0
    assert result['avg_ram'] == 0.0
    assert result['verdict'] == 'failed'


def test_a_blank_result_starts_failed_with_the_game_named():
    result = bs.blank_result('Minecraft', 'minecraft')
    assert result['game'] == 'Minecraft'
    assert result['folder'] == 'minecraft'
    assert result['status'] == 'error'
    assert result['verdict'] == 'failed'
    assert result['notes'] == []
    assert result['recording'] is None


# ── parse_ffmpeg_fps ─────────────────────────────────────────────────────────


def test_the_last_fps_figure_ffmpeg_printed_wins():
    log = 'frame=1 fps=0.0 q=28.0\nframe=30 fps= 12.4 q=28.0\nframe=900 fps=29.97 q=-1.0\n'
    assert bs.parse_ffmpeg_fps(log) == 30.0


def test_a_log_without_an_fps_figure_parses_to_none():
    assert bs.parse_ffmpeg_fps('ffmpeg version 6.0\nNo such device\n') is None


# ── process arguments and environment ────────────────────────────────────────


def test_the_capture_commands_read_the_benchmark_display():
    video = bs._ffmpeg_args('/usr/bin/ffmpeg', 20, '/out/run.mp4')
    frames = bs._frames_args('/usr/bin/ffmpeg', 20, '/out/%04d.jpg')
    assert video[0] == '/usr/bin/ffmpeg'
    assert ':20' in video
    assert video[-1] == '/out/run.mp4'
    assert '30' == video[video.index('-r') + 1]
    assert '0.5' == frames[frames.index('-framerate') + 1]
    assert frames[-1] == '/out/%04d.jpg'


def test_the_game_environment_pins_the_display_and_the_runtimes():
    env = bs._game_env(20)
    assert env['DISPLAY'] == ':20'
    assert env['JAVA'].endswith('jdk21/bin/java')
    assert env['DOTNET_ROOT'].endswith('dotnet')


def test_the_processes_are_stopped_capture_first_then_game_then_display():
    procs = bs.BenchProcs(frames='F', ffmpeg='V', game='G', xvfb='X')
    assert procs.stop_order() == [('Frames', 'F'), ('FFmpeg', 'V'), ('Game', 'G'), ('Xvfb', 'X')]


# ── state transitions ────────────────────────────────────────────────────────


def test_reset_state_arms_the_sweep_and_clears_the_previous_run(run):
    run.state['results'] = [{'game': 'old'}]
    run.state['debug_log'] = ['old line']

    bs.reset_state(run, ['Minecraft Dig FP', 'Minecraft Build FP'])

    assert run.state['running'] is True
    assert run.state['phase'] == 'starting'
    assert run.state['total'] == 2
    assert run.state['results'] == []
    assert run.state['debug_log'] == []
    assert run.state['started_at'] is not None


def test_finish_state_parks_the_sweep(run):
    run.state.update({'running': True, 'current_game': 'Minecraft', 'live': {'cpu': 9}})

    bs.finish_state(run)

    assert run.state['running'] is False
    assert run.state['phase'] == 'done'
    assert run.state['current_game'] is None
    assert run.state['live'] == {}


def test_claim_game_takes_the_next_game_while_the_sweep_runs(run):
    run.state['running'] = True

    assert bs.claim_game(run, 'Minecraft Dig FP', 3) is True
    assert run.state['current_game'] == 'Minecraft Dig FP'
    assert run.state['current_idx'] == 3
    assert run.state['phase'] == 'starting'


def test_claim_game_refuses_and_changes_nothing_after_a_stop_request(run):
    run.state['running'] = False

    assert bs.claim_game(run, 'Minecraft Dig FP', 3) is False
    assert run.state['current_game'] is None
    assert run.state['current_idx'] == 0
    assert run.state['phase'] == 'idle'


def test_a_filed_result_carries_only_the_debug_lines_of_its_own_game(run):
    run.state['debug_log'] = ['a previous game', 'and another']
    start = len(run.state['debug_log'])
    run.dbg('--- [Minecraft Dig FP] START ---')
    run.dbg('  Startup: 1200ms')
    result = bs.blank_result('Minecraft Dig FP', 'minecraft_dig_fp')

    bs._append_result(run, result, start, phase='cooldown')

    assert result['debug_lines'] == ['--- [Minecraft Dig FP] START ---', '  Startup: 1200ms']
    assert run.state['results'] == [result]
    assert run.state['phase'] == 'cooldown'


def test_still_running_reads_the_shared_stop_flag(run):
    assert bs._still_running(run) is False
    run.state['running'] = True
    assert bs._still_running(run) is True
