# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Benchmark engine: timed runs with CPU/RAM/GPU sampling, and game detection."""

import logging as _zyg_logging
import os
import subprocess
import threading
import time

from zyg_workflows.bin import exe

from . import benchmark_stages as _bs
from .config import GAMESIM_DIR, GAME_FOLDER_MAP, RECORDINGS_DIR

_zyg_log = _zyg_logging.getLogger(__name__)


# ── Benchmark engine ────────────────────────────────────────────────────
BENCH_DISPLAY = 20  # dedicated virtual display, separate from sim displays

_bench_lock = threading.Lock()
_bench_state = {
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


def _dbg(msg):
    ts = time.strftime('%H:%M:%S')
    line = f'[{ts}] {msg}'
    _zyg_log.info(line)
    with _bench_lock:
        _bench_state['debug_log'].append(line)
        if len(_bench_state['debug_log']) > 500:
            _bench_state['debug_log'] = _bench_state['debug_log'][-500:]


def _proc_rss_mb(pid):
    try:
        with open(f'/proc/{pid}/status') as f:
            for line in f:
                if line.startswith('VmRSS:'):
                    return int(line.split()[1]) / 1024
    except OSError as _exc:
        _zyg_log.debug('rss of pid %s unavailable, reporting 0: %s', pid, _exc)
    return 0.0


def _sys_cpu_pct():
    def _rs():
        with open('/proc/stat') as f:
            p = f.readline().split()
            idle = int(p[4])
            total = sum(int(x) for x in p[1:])
            return idle, total

    try:
        i1, t1 = _rs()
        time.sleep(0.3)
        i2, t2 = _rs()
        dt = t2 - t1
        return round((1 - (i2 - i1) / dt) * 100, 1) if dt else 0.0
    except Exception:
        return 0.0


def _nvidia_smi():
    try:
        r = subprocess.run(
            [exe('nvidia-smi'), '--query-gpu=utilization.gpu,memory.used', '--format=csv,noheader,nounits'],
            capture_output=True,
            text=True,
            timeout=3,
        )
        parts = r.stdout.strip().split(',')
        if len(parts) >= 2:
            return float(parts[0].strip()), float(parts[1].strip())
    except Exception as _exc:
        _zyg_log.debug('nvidia-smi sample failed, reporting zeros: %s', _exc)
    return 0.0, 0.0


def _sample(pids):
    try:
        import psutil

        cpu = psutil.cpu_percent(interval=0.3)
        ram = sum(psutil.Process(p).memory_info().rss / 1024 / 1024 for p in pids if psutil.pid_exists(p))
    except ImportError:
        cpu = _sys_cpu_pct()
        ram = sum(_proc_rss_mb(p) for p in pids)
    gpu, vram = _nvidia_smi()
    return cpu, round(ram, 1), gpu, round(vram, 1)


def _run_benchmark_bg(duration):
    """Benchmark every installed game for *duration* seconds each, in turn.

    Publishes progress into the module-level ``_bench_state`` that ``gamesim.api``
    and ``gamesim_server`` poll, and stops early the moment the operator clears
    ``running``.  The per-game work lives in :mod:`benchmark_stages`; this function
    only owns the sweep and the start/finish log lines.
    """
    games = get_installed_games()
    run = _bs.BenchRun(
        state=_bench_state,
        lock=_bench_lock,
        dbg=_dbg,
        sample=_sample,
        duration=duration,
        display=BENCH_DISPLAY,
    )
    _bs.reset_state(run, games)

    RECORDINGS_DIR.mkdir(parents=True, exist_ok=True)
    _dbg(f'=== BENCHMARK START === {len(games)} installed games: {games}')
    _dbg(f'Duration per game: {duration}s  |  Recordings dir: {RECORDINGS_DIR}')

    for idx, game_name in enumerate(games):
        if not _bs.claim_game(run, game_name, idx):
            _dbg('Benchmark stopped by user')
            break
        _bs.run_one_game(run, game_name, idx)

    _dbg('=== BENCHMARK COMPLETE ===')
    _bs.finish_state(run)


GAME_BINARY_CHECK = {
    'Minecraft': 'paper.jar',
    'Minecraft Build/Mine': 'paper.jar',
    'Minecraft Dig FP': 'paper.jar',
    'Minecraft Build FP': 'paper.jar',
    'CS2 / CS:GO': 'server/game/bin/linuxsteamrt64/cs2',
    'Team Fortress 2': 'server/srcds_run',
    'Valheim': 'server/valheim_server.x86_64',
    'Rust': 'server/RustDedicated',
}

# Limit benchmark to first-person sims
BENCHMARK_ONLY = ['Minecraft Dig FP', 'Minecraft Build FP']


def get_installed_games():
    """Return list of game names that have a verified game binary installed."""
    installed = []
    for name, folder in GAME_FOLDER_MAP.items():
        if BENCHMARK_ONLY and name not in BENCHMARK_ONLY:
            continue
        base = os.path.join(GAMESIM_DIR, folder)
        if not os.path.isdir(base):
            continue
        check = GAME_BINARY_CHECK.get(name)
        if check:
            if os.path.isfile(os.path.join(base, check)):
                installed.append(name)
        else:
            # Games without a binary check are not installable on Linux
            pass
    return installed
