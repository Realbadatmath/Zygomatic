# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Simulation state: starting, recording and stopping game instances."""

import logging as _zyg_logging
import os
import signal
import subprocess
import threading
import time
from pathlib import Path

from zyg_workflows.bin import exe

from .config import DISPLAY_BASE, GAMESIM_DIR, GAME_FOLDER_MAP, RECORDINGS_DIR
from .schematics import BUILD_FP_GAME, _ensure_schematic_file

_zyg_log = _zyg_logging.getLogger(__name__)


# ── Simulation state ────────────────────────────────────────────────────
_sim_lock = threading.Lock()
_sim_state = {'running': False, 'instances': [], 'started_at': None}


def _kill_pid(pid):
    try:
        os.kill(pid, signal.SIGTERM)
    except OSError as _exc:
        _zyg_log.debug('pid %s already gone, nothing to terminate: %s', pid, _exc)


def _start_sim_bg(game_list):
    """Runs in a background thread. Starts Xvfb + game + FFmpeg per instance."""
    RECORDINGS_DIR.mkdir(parents=True, exist_ok=True)

    with _sim_lock:
        _sim_state['running'] = True
        _sim_state['instances'] = []
        _sim_state['started_at'] = time.time()

    name_count = {}

    for i, game_name in enumerate(game_list):
        display = DISPLAY_BASE + i
        name_count[game_name] = name_count.get(game_name, 0) + 1
        instance_id = name_count[game_name]

        folder = GAME_FOLDER_MAP.get(game_name)
        game_dir = Path(GAMESIM_DIR) / folder if folder else None

        entry = {
            'game': game_name,
            'instance': instance_id,
            'display': display,
            'xvfb_pid': None,
            'game_pid': None,
            'ffmpeg_pid': None,
            'output': None,
            'status': 'error',
        }

        if not folder or not game_dir.exists():
            entry['status'] = 'no_folder'
            with _sim_lock:
                _sim_state['instances'].append(entry)
            continue

        if game_name == BUILD_FP_GAME:
            _ensure_schematic_file()

        try:
            # 1 — Virtual display
            xvfb = subprocess.Popen(
                ['Xvfb', f':{display}', '-screen', '0', '1280x720x24'],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            entry['xvfb_pid'] = xvfb.pid
            time.sleep(0.6)

            # 2 — Game process
            env = os.environ.copy()
            env['DISPLAY'] = f':{display}'
            game_proc = subprocess.Popen(
                [exe('bash'), 'start.sh'],
                cwd=str(game_dir),
                env=env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            entry['game_pid'] = game_proc.pid
            time.sleep(2.5)  # let game initialise before capture starts

            # 3 — FFmpeg recording
            safe = folder.replace(' ', '_').lower()
            ts = int(time.time())
            output = str(RECORDINGS_DIR / f'{safe}_inst{instance_id}_{ts}.mp4')
            ffmpeg = subprocess.Popen(
                [
                    exe('ffmpeg'),
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
                    'fast',
                    '-crf',
                    '28',
                    '-movflags',
                    'frag_keyframe+empty_moov+default_base_moof',
                    '-y',
                    output,
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            entry['ffmpeg_pid'] = ffmpeg.pid
            entry['output'] = output
            entry['status'] = 'recording'

        except Exception as exc:
            entry['status'] = f'error: {exc}'

        with _sim_lock:
            _sim_state['instances'].append(entry)


def _stop_sim():
    with _sim_lock:
        instances = list(_sim_state['instances'])

    # Step 1: send SIGINT to ffmpeg so it can write the moov atom and finalize
    for inst in instances:
        pid = inst.get('ffmpeg_pid')
        if pid:
            try:
                os.kill(pid, signal.SIGINT)
            except OSError as _exc:
                _zyg_log.warning('could not SIGINT ffmpeg pid %s, its recording may stay unfinalised: %s', pid, _exc)

    # Wait up to 10s for ffmpeg processes to finish writing
    deadline = time.time() + 10
    for inst in instances:
        pid = inst.get('ffmpeg_pid')
        if not pid:
            continue
        while time.time() < deadline:
            try:
                os.kill(pid, 0)
                time.sleep(0.25)
            except ProcessLookupError:
                break

    # Step 2: kill game processes and Xvfb
    with _sim_lock:
        for inst in _sim_state['instances']:
            for key in ('ffmpeg_pid', 'game_pid', 'xvfb_pid'):
                if inst.get(key):
                    _kill_pid(inst[key])
        _sim_state['running'] = False
        _sim_state['instances'] = []
        _sim_state['started_at'] = None


FOLDER_TO_GAME = {v: k for k, v in GAME_FOLDER_MAP.items()}
