# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Benchmark stages: the per-game run that ``benchmark._run_benchmark_bg`` drives.

The import graph stays one-way — ``benchmark`` → ``benchmark_stages`` → ``config`` — so
this module never imports its parent.  The shared benchmark state, its lock, the debug
logger and the resource sampler all live in ``benchmark`` and arrive here on a
:class:`BenchRun`, which keeps the single ``_bench_state`` dict that ``gamesim.api`` and
``gamesim_server`` import by name as the one and only copy.
"""

import logging as _zyg_logging
import os
import re
import signal
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from zyg_workflows.bin import exe
from zyg_workflows.paths import tmp_dir

from .config import GAMESIM_DIR, GAME_FOLDER_MAP, RECORDINGS_DIR

# The parent module's channel, kept by name: these lines used to be logged from
# benchmark.py and nothing about them changed but the file they sit in.
_zyg_log = _zyg_logging.getLogger('zyg_dashboard.hub.gamesim.benchmark')

# Minecraft needs an extended wait: Paper server (~90s) + bots spawn + the real
# Minecraft client loads + SpectatorBot joins and is positioned.  start.sh touches a
# per-sim sentinel file when the spectator is set up.  These paths are the contract with
# each sim's start.sh, which is what creates the file; they are read here, never chosen
# here.
_MC_SENTINEL = {
    'minecraft_dig_fp': '/tmp/mc_dig_spectator_ready',  # nosec B108  # noqa: S108  written by the sim's start.sh
    'minecraft_build_fp': '/tmp/mc_build_spectator_ready',  # nosec B108  # noqa: S108  written by the sim's start.sh
    'minecraft': '/tmp/mc_spectator_ready',  # nosec B108  # noqa: S108  written by the sim's start.sh
    'minecraft_build': '/tmp/mc_spectator_ready',  # nosec B108  # noqa: S108  written by the sim's start.sh
}

_SPECTATOR_WAIT_S = 300
_INIT_WAIT_S = 15
_COOLDOWN_S = 5
_STOP_TIMEOUT_S = 6


@dataclass
class BenchRun:
    """One benchmark sweep: the shared state it reports through and its knobs.

    ``state`` is ``benchmark._bench_state`` itself — the same dict ``gamesim.api``
    imported — and ``lock`` is the lock that guards it.  ``dbg`` and ``sample`` are
    ``benchmark._dbg`` and ``benchmark._sample``, passed in so the stages never reach
    back into their parent.
    """

    state: dict
    lock: object
    dbg: Callable[[str], None]
    sample: Callable[[list], tuple]
    duration: float
    display: int


@dataclass
class BenchLogs:
    """The three per-game log files a run tees its child processes into."""

    ffmpeg: Path
    game: Path
    xvfb: Path

    @classmethod
    def for_game(cls, idx: int) -> 'BenchLogs':
        """Open the log paths for game *idx* under the benchmark's scratch directory."""
        root = tmp_dir('gamesim-bench')
        return cls(
            ffmpeg=root / f'bench_ffmpeg_{idx}.log',
            game=root / f'bench_game_{idx}.log',
            xvfb=root / f'bench_xvfb_{idx}.log',
        )


@dataclass
class BenchProcs:
    """The four child processes of one game run, in the order they must be stopped."""

    frames: object = None
    ffmpeg: object = None
    game: object = None
    xvfb: object = None

    def stop_order(self) -> list:
        """``(label, proc)`` pairs: capture first, then the game, then its display."""
        return [
            ('Frames', self.frames),
            ('FFmpeg', self.ffmpeg),
            ('Game', self.game),
            ('Xvfb', self.xvfb),
        ]


@dataclass
class Series:
    """The resource samples collected during one game's timed window."""

    cpu: list = field(default_factory=list)
    ram: list = field(default_factory=list)
    gpu: list = field(default_factory=list)
    vram: list = field(default_factory=list)


# ── Pure helpers ─────────────────────────────────────────────────────────────


def blank_result(game_name: str, folder: str) -> dict:
    """A result record for *game_name* with every field at its failed-run default.

    A run that dies before it samples anything is still reported, which is why the
    status starts at ``'error'`` and the verdict at ``'failed'``.
    """
    return {
        'game': game_name,
        'folder': folder,
        'status': 'error',
        'startup_ms': 0,
        'avg_cpu': 0,
        'peak_cpu': 0,
        'avg_ram': 0,
        'peak_ram': 0,
        'avg_gpu': 0,
        'peak_gpu': 0,
        'avg_vram': 0,
        'peak_vram': 0,
        'ffmpeg_fps': 0,
        'verdict': 'failed',
        'notes': [],
        'debug_lines': [],
        'recording': None,
        'frames_folder': None,
    }


def _avg(values: list) -> float:
    """Mean of *values* to one decimal, or 0.0 when nothing was sampled."""
    return round(sum(values) / len(values), 1) if values else 0.0


def _peak(values: list) -> float:
    """Largest of *values* to one decimal, or 0.0 when nothing was sampled."""
    return round(max(values), 1) if values else 0.0


def verdict_for(status: str, peak_cpu: float, peak_ram: float) -> str:
    """Grade a finished run: ``failed``, ``heavy``, ``acceptable`` or ``smooth``.

    A run that did not reach ``'ok'`` is failed whatever it measured.  Otherwise the
    worse of the CPU and RAM peaks decides, so one hot resource is enough to downgrade.
    """
    if status != 'ok':
        return 'failed'
    if peak_cpu > 90 or peak_ram > 20000:
        return 'heavy'
    if peak_cpu > 65 or peak_ram > 8000:
        return 'acceptable'
    return 'smooth'


def summarise(result: dict, series: Series) -> None:
    """Write the averages, peaks and verdict of *series* into *result* in place."""
    result['avg_cpu'] = _avg(series.cpu)
    result['peak_cpu'] = _peak(series.cpu)
    result['avg_ram'] = _avg(series.ram)
    result['peak_ram'] = _peak(series.ram)
    result['avg_gpu'] = _avg(series.gpu)
    result['peak_gpu'] = _peak(series.gpu)
    result['avg_vram'] = _avg(series.vram)
    result['peak_vram'] = _peak(series.vram)
    result['verdict'] = verdict_for(result['status'], result['peak_cpu'], result['peak_ram'])


def parse_ffmpeg_fps(log_text: str) -> float | None:
    """The last ``fps=`` figure ffmpeg printed, to one decimal, or None if it printed none.

    ffmpeg rewrites its progress line, so the last match is the rate the capture
    finished at rather than the rate it started at.
    """
    hits = re.findall(r'fps=\s*([0-9.]+)', log_text)
    return round(float(hits[-1]), 1) if hits else None


def _game_env(display: int) -> dict:
    """The environment a sim's ``start.sh`` is launched with.

    The display is the benchmark's own, never a simulation one, and the JDK/dotnet roots
    are the ones the sims expect to find rather than whatever is on PATH.
    """
    env = os.environ.copy()
    env['DISPLAY'] = f':{display}'
    env['JAVA'] = os.path.expanduser('~/jdk21/bin/java')
    env['DOTNET_ROOT'] = os.path.expanduser('~/dotnet')
    return env


def _ffmpeg_args(ffmpeg_bin: str, display: int, mp4: str) -> list:
    """The x11grab command that records *display* to *mp4* at 30 fps, 1280x720."""
    return [
        ffmpeg_bin,
        '-f',
        'x11grab',
        '-r',
        '30',
        '-s',
        '1280x720',
        '-i',
        f':{display}',
        '-c:v',
        'libx264',
        '-preset',
        'ultrafast',
        '-crf',
        '28',
        '-y',
        mp4,
    ]


def _frames_args(ffmpeg_bin: str, display: int, pattern: str) -> list:
    """The x11grab command that writes one JPEG every two seconds to *pattern*."""
    return [
        ffmpeg_bin,
        '-f',
        'x11grab',
        '-framerate',
        '0.5',
        '-s',
        '1280x720',
        '-i',
        f':{display}',
        '-q:v',
        '4',
        '-y',
        pattern,
    ]


def _tail(path: Path, n: int) -> list:
    """The last *n* non-empty-stripped lines of *path*; raises if it cannot be read."""
    return path.read_text().strip().splitlines()[-n:]


# ── State transitions ────────────────────────────────────────────────────────


def reset_state(run: BenchRun, games: list) -> None:
    """Arm the shared state for a sweep over *games*, clearing the previous run."""
    with run.lock:
        run.state.update(
            {
                'running': True,
                'phase': 'starting',
                'current_game': None,
                'current_idx': 0,
                'total': len(games),
                'live': {},
                'results': [],
                'started_at': time.time(),
                'debug_log': [],
                'frames_folder': None,
            }
        )


def finish_state(run: BenchRun) -> None:
    """Park the shared state after the last game: not running, phase ``done``."""
    with run.lock:
        run.state['running'] = False
        run.state['phase'] = 'done'
        run.state['current_game'] = None
        run.state['live'] = {}


def claim_game(run: BenchRun, game_name: str, idx: int) -> bool:
    """Mark *game_name* as the current one; return False if a stop was requested.

    The read and the write happen under one lock hold, so a stop that lands between
    them cannot leave the UI pointing at a game that never started.
    """
    with run.lock:
        running = run.state['running']
        if running:
            run.state['current_game'] = game_name
            run.state['current_idx'] = idx
            run.state['phase'] = 'starting'
    return bool(running)


def _still_running(run: BenchRun) -> bool:
    """Whether the operator has not asked the sweep to stop."""
    with run.lock:
        return bool(run.state['running'])


def _append_result(run: BenchRun, result: dict, debug_start: int, phase: str | None = None) -> None:
    """File *result* with the debug lines this game produced, optionally setting *phase*."""
    with run.lock:
        result['debug_lines'] = list(run.state['debug_log'][debug_start:])
        run.state['results'].append(result)
        if phase is not None:
            run.state['phase'] = phase


# ── Process stages ───────────────────────────────────────────────────────────


def _start_display(run: BenchRun, log_path: Path):
    """Start the benchmark's own Xvfb, killing a stale server and its lock first.

    Returns the Xvfb process.  The first lines of its stderr are echoed to the debug
    console because an unusable display is the failure that explains every later one.
    """
    run.dbg(f'  Starting Xvfb :{run.display} ...')
    # /tmp/.X<n>-lock and /tmp/.X11-unix/X<n> are the X server's own fixed
    # paths, not ours to relocate — the display is addressed by them.
    lock_file = Path(f'/tmp/.X{run.display}-lock')  # nosec B108  # noqa: S108  X11 lock path, fixed by the X server
    if lock_file.exists():
        try:
            old_pid = int(lock_file.read_text().strip())
            os.kill(old_pid, signal.SIGKILL)
            run.dbg(f'  Killed stale Xvfb PID={old_pid}')
        except Exception as ke:
            run.dbg(f'  Stale lock cleanup: {ke}')
        try:
            lock_file.unlink()
            Path(f'/tmp/.X11-unix/X{run.display}').unlink(missing_ok=True)  # nosec B108  # noqa: S108  X11 socket path, fixed by the X server
        except Exception as _exc:
            _zyg_log.debug('stale X lock cleanup skipped: %s', _exc)
        time.sleep(0.3)
    with open(str(log_path), 'w') as xlog:
        proc = subprocess.Popen(
            ['Xvfb', f':{run.display}', '-screen', '0', '1280x720x24', '-ac'],
            stdout=subprocess.DEVNULL,
            stderr=xlog,
        )
    run.dbg(f'  Xvfb PID={proc.pid}')
    time.sleep(0.8)

    # Check Xvfb stderr for early errors
    try:
        for line in log_path.read_text().strip().splitlines()[:5]:
            run.dbg(f'  [Xvfb] {line}')
    except Exception as _exc:
        _zyg_log.debug('xvfb log not readable, no early errors shown: %s', _exc)
    return proc


def _start_game(run: BenchRun, game_dir: Path, log_path: Path):
    """Launch the sim's ``start.sh`` in its own session on the benchmark display."""
    run.dbg(f'  Starting game: bash start.sh  cwd={game_dir}')
    with open(str(log_path), 'w') as glog:
        proc = subprocess.Popen(
            [exe('bash'), 'start.sh'],
            cwd=str(game_dir),
            env=_game_env(run.display),
            stdout=glog,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    run.dbg(f'  Game PID={proc.pid}')
    return proc


def _wait_for_init(run: BenchRun, proc, log_path: Path) -> None:
    """Give the game up to 15 s to come up, narrating its log as it does.

    An early exit is reported with the tail of its log — the only place the reason is
    written down — and the wait stops there; at five seconds the head of the log is
    echoed so a game that is merely slow can be told from one that is stuck.
    """
    run.dbg(f'  Waiting for game to initialise (max {_INIT_WAIT_S}s)...')
    for wait_i in range(_INIT_WAIT_S):
        time.sleep(1)
        rc = proc.poll()
        if rc is not None:
            run.dbg(f'  WARN: game exited after {wait_i + 1}s with code {rc}')
            try:
                for line in _tail(log_path, 10):
                    run.dbg(f'  [game-exit] {line}')
            except Exception as _exc:
                _zyg_log.debug('game log not readable after the exit: %s', _exc)
            break
        if wait_i == 4:
            try:
                lines = log_path.read_text().strip().splitlines()[:8]
                run.dbg(f'  Game log (first {len(lines)} lines):')
                for line in lines:
                    run.dbg(f'    {line}')
            except Exception as _exc:
                _zyg_log.debug('game log not readable while starting: %s', _exc)


def _wait_for_spectator(run: BenchRun, folder: str, proc) -> None:
    """For a Minecraft sim, wait up to 300 s for start.sh's spectator-ready sentinel.

    Capturing before the SpectatorBot is positioned records a loading screen, so the
    stale sentinel is removed first and the wait aborts early on a stop request or a
    dead game.  Sims without a sentinel return at once.
    """
    sentinel = _MC_SENTINEL.get(folder)
    if sentinel is None or proc.poll() is not None:
        return
    try:
        Path(sentinel).unlink(missing_ok=True)
    except Exception as _exc:
        _zyg_log.debug('spectator sentinel %s not removable: %s', sentinel, _exc)
    run.dbg(f'  Minecraft: waiting for SpectatorBot ready signal (max {_SPECTATOR_WAIT_S}s)...')
    for waited in range(_SPECTATOR_WAIT_S):
        time.sleep(1)
        if not _still_running(run):
            run.dbg('  Minecraft: stop requested, aborting wait')
            return
        if proc.poll() is not None:
            run.dbg('  WARN: game exited while waiting for spectator')
            return
        if Path(sentinel).exists():
            run.dbg(f'  SpectatorBot ready after {waited}s — starting FFmpeg now')
            time.sleep(2)
            return
    run.dbg(f'  WARN: ready signal not received after {_SPECTATOR_WAIT_S}s, starting FFmpeg anyway')


def _start_capture(run: BenchRun, result: dict, folder: str, procs: BenchProcs, log_path: Path) -> None:
    """Start the video and the frame capture, recording their paths on *result*.

    Both read the same display: the mp4 is the watchable artefact, the 0.5 fps JPEG
    sequence is what the gallery pages through.
    """
    ts = int(time.time())
    mp4 = str(RECORDINGS_DIR / f'{folder}_bench_{ts}.mp4')
    run.dbg(f'  Starting FFmpeg → {mp4}')
    with open(str(log_path), 'w') as flog:
        procs.ffmpeg = subprocess.Popen(
            _ffmpeg_args(exe('ffmpeg'), run.display, mp4),
            stdout=subprocess.DEVNULL,
            stderr=flog,
        )
    run.dbg(f'  FFmpeg PID={procs.ffmpeg.pid}')
    result['recording'] = mp4

    frames_dir = RECORDINGS_DIR / f'{folder}_frames_{ts}'
    frames_dir.mkdir(parents=True, exist_ok=True)
    procs.frames = subprocess.Popen(
        _frames_args(exe('ffmpeg'), run.display, str(frames_dir / '%04d.jpg')),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    run.dbg(f'  Frames capture PID={procs.frames.pid} → {frames_dir.name}/')
    result['frames_folder'] = frames_dir.name
    with run.lock:
        run.state['frames_folder'] = frames_dir.name


def _sample_loop(run: BenchRun, procs: BenchProcs, game_log: Path, series: Series) -> int:
    """Sample CPU/RAM/GPU for the configured duration; return the sample count.

    Every tenth sample is echoed with the elapsed time, new game-log lines are streamed
    through on every tick, and the latest numbers are published to ``state['live']`` for
    the UI.  A stop request ends the window early.
    """
    with run.lock:
        run.state['phase'] = 'testing'

    run.dbg(f'  Sampling for {run.duration}s ...')
    pids = [p for p in [procs.game.pid, procs.xvfb.pid] if p]
    t0 = time.time()
    sample_n = 0
    log_pos = 0

    while time.time() - t0 < run.duration:
        if not _still_running(run):
            run.dbg('  Benchmark stopped mid-game')
            break

        cpu, ram, gpu, vram = run.sample(pids)
        series.cpu.append(cpu)
        series.ram.append(ram)
        series.gpu.append(gpu)
        series.vram.append(vram)
        elapsed = round(time.time() - t0, 1)
        sample_n += 1

        if sample_n % 10 == 0:
            run.dbg(f'  Sample #{sample_n}: cpu={cpu}% ram={ram:.0f}MB gpu={gpu}% vram={vram:.0f}MB  t={elapsed}s')
            if procs.game.poll() is not None:
                run.dbg(f'  WARN: game process died at t={elapsed}s (code={procs.game.poll()})')
        # Stream all new game log lines since last check (every second)
        try:
            with open(str(game_log)) as gf:
                gf.seek(log_pos)
                new = gf.read()
                log_pos = gf.tell()
            for line in new.splitlines():
                if line.strip():
                    run.dbg(f'  [game-live] {line.rstrip()}')
        except Exception as _exc:
            _zyg_log.debug('game log tail unavailable this tick: %s', _exc)

        with run.lock:
            run.state['live'] = {
                'cpu': cpu,
                'ram_mb': ram,
                'gpu': gpu,
                'vram_mb': vram,
                'elapsed': elapsed,
                'target': run.duration,
            }
        time.sleep(1)
    return sample_n


def _teardown(run: BenchRun, result: dict, logs: BenchLogs, procs: BenchProcs) -> None:
    """Stop every child process, then read the fps and the log tails off disk.

    Runs whether the game succeeded or not, which is why nothing here may raise: a
    process that will not die and a log that will not open are both only reported.
    """
    with run.lock:
        run.state['phase'] = 'stopping'

    run.dbg('  Stopping processes ...')
    for label, proc in procs.stop_order():
        if not proc:
            continue
        try:
            proc.terminate()
            rc = proc.wait(timeout=_STOP_TIMEOUT_S)
            run.dbg(f'  {label} PID={proc.pid} exited code={rc}')
        except subprocess.TimeoutExpired:
            run.dbg(f'  {label} PID={proc.pid} timeout — killing')
            try:
                proc.kill()
            except Exception as _exc:
                _zyg_log.warning('%s pid %s survived the kill: %s', label, proc.pid, _exc)
        except Exception as e:
            run.dbg(f'  {label} stop error: {e}')

    # Parse FFmpeg FPS
    try:
        log_txt = logs.ffmpeg.read_text()
        fps = parse_ffmpeg_fps(log_txt)
        if fps is not None:
            result['ffmpeg_fps'] = fps
            run.dbg(f'  FFmpeg captured fps={result["ffmpeg_fps"]}')
        else:
            run.dbg('  WARN: FFmpeg fps not found in log')
        # Log last 5 lines of ffmpeg output
        for line in log_txt.strip().splitlines()[-5:]:
            run.dbg(f'  [ffmpeg] {line}')
    except Exception as e:
        run.dbg(f'  FFmpeg log read error: {e}')

    # Tail final game log
    try:
        lines = _tail(logs.game, 8)
        run.dbg(f'  Game final log ({len(lines)} lines):')
        for line in lines:
            run.dbg(f'    {line}')
    except Exception as _exc:
        _zyg_log.debug('final game log not readable: %s', _exc)


def _run_capture(
    run: BenchRun, result: dict, folder: str, game_dir: Path, logs: BenchLogs, procs: BenchProcs, series: Series
) -> None:
    """Bring the display, the game and the capture up, then sample the timed window.

    Anything that raises here aborts the game and is reported by the caller; the
    processes started so far are stopped by the caller's teardown either way.
    """
    t_start = time.time()
    procs.xvfb = _start_display(run, logs.xvfb)
    procs.game = _start_game(run, game_dir, logs.game)
    with run.lock:
        run.state['game_proc'] = procs.game

    _wait_for_init(run, procs.game, logs.game)
    _wait_for_spectator(run, folder, procs.game)

    result['startup_ms'] = int((time.time() - t_start) * 1000)
    run.dbg(f'  Startup: {result["startup_ms"]}ms  game_alive={procs.game.poll() is None}')

    _start_capture(run, result, folder, procs, logs.ffmpeg)
    sample_n = _sample_loop(run, procs, logs.game, series)
    result['status'] = 'ok'
    run.dbg(f'  Sampling complete — {sample_n} samples collected')


def run_one_game(run: BenchRun, game_name: str, idx: int) -> None:
    """Benchmark one game end to end and file its result, then cool down.

    The whole run is best-effort: a missing folder, a crash during capture and a
    hanging process all produce a filed result rather than an exception, because the
    sweep must reach the next game.
    """
    folder = GAME_FOLDER_MAP[game_name]
    game_dir = Path(GAMESIM_DIR) / folder
    with run.lock:
        debug_start = len(run.state['debug_log'])

    run.dbg(f'--- [{game_name}] START (idx={idx}) ---')
    run.dbg(f'  folder : {game_dir}')
    run.dbg(f'  start.sh: {game_dir / "start.sh"} exists={(game_dir / "start.sh").exists()}')

    result = blank_result(game_name, folder)
    if not game_dir.exists():
        run.dbg(f'  ERROR: game folder missing: {game_dir}')
        result['status'] = 'no_folder'
        result['verdict'] = 'no_folder'
        result['notes'].append('GameSim folder missing')
        _append_result(run, result, debug_start)
        return

    logs = BenchLogs.for_game(idx)
    procs = BenchProcs()
    series = Series()
    try:
        _run_capture(run, result, folder, game_dir, logs, procs, series)
    except Exception as exc:
        import traceback as _tb

        run.dbg(f'  ERROR in [{game_name}]: {exc}')
        for el in _tb.format_exc().strip().splitlines():
            run.dbg(f'  {el}')
        result['notes'].append(str(exc))
    finally:
        _teardown(run, result, logs, procs)

    summarise(result, series)
    run.dbg(
        f'--- [{game_name}] DONE verdict={result["verdict"]} '
        f'cpu_peak={result["peak_cpu"]}% ram_peak={result["peak_ram"]:.0f}MB '
        f'fps={result["ffmpeg_fps"]} ---'
    )
    _append_result(run, result, debug_start, phase='cooldown')

    run.dbg(f'  Cooldown {_COOLDOWN_S}s before next game...')
    time.sleep(_COOLDOWN_S)
