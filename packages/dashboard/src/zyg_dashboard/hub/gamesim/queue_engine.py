# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Production queue engine: runs queued schematics one after another."""

import json
import logging as _zyg_logging
import threading
import time
from pathlib import Path

from .schematics import (
    BUILD_FP_GAME,
    QUEUE_STATE_FILE,
    SCHEMATICS,
    _custom_loaded,  # noqa: F401  the load-order guard in _load_queue() reads globals()
    _read_build_status,
    _set_schem_column,
    _write_schematic_file,
)
from .sim_state import _sim_lock, _sim_state, _start_sim_bg, _stop_sim

_zyg_log = _zyg_logging.getLogger(__name__)


# ── Production queue engine ─────────────────────────────────────────────
_queue_lock = threading.Lock()
_queue = {'state': 'stopped', 'items': [], 'current_uid': None}
_queue_uid = [0]


def _save_queue_locked():
    try:
        QUEUE_STATE_FILE.write_text(json.dumps({'state': _queue['state'], 'items': _queue['items']}, indent=1))
    except OSError as _exc:
        _zyg_log.warning('queue state not saved, the queue is lost on restart: %s', _exc)


def _load_queue():
    # Guard the load-order trap: this filters on `in SCHEMATICS`, so custom
    # schematics must already be merged or queued custom builds vanish silently.
    if '_custom_loaded' not in globals():
        raise RuntimeError('load_custom_schematics() must run before _load_queue()')
    try:
        saved = json.loads(QUEUE_STATE_FILE.read_text())
        items = [i for i in saved.get('items', []) if i.get('schematic') in SCHEMATICS]
        for i in items:
            if i.get('status') == 'running':
                i['status'] = 'queued'  # server restarted mid-build — requeue
        _queue['items'] = items
    except (OSError, ValueError, AttributeError) as _exc:
        _zyg_log.warning('queue state unreadable, starting with an empty queue: %s', _exc)


_load_queue()


def _run_queue_item(item):
    schem = SCHEMATICS[item['schematic']]
    _write_schematic_file(schem)
    with _queue_lock:
        item['status'] = 'running'
        item['started_at'] = time.time()
        item.pop('recording', None)
        _queue['current_uid'] = item['uid']
        _save_queue_locked()
    _set_schem_column(schem['id'], 'inproduction')

    _start_sim_bg([BUILD_FP_GAME])  # Xvfb + sim stack + FFmpeg recording

    max_secs = min(2700, schem['est_minutes'] * 180 + 300)
    deadline = time.time() + max_secs
    result = 'timeout'
    while time.time() < deadline:
        time.sleep(3)
        with _queue_lock:
            st = _queue['state']
        if st == 'paused':
            result = 'paused'
            break
        if st == 'stopped':
            result = 'stopped'
            break
        status = _read_build_status()
        if status and status.get('complete'):
            result = 'complete'
            time.sleep(6)  # capture the finished build on video
            break

    with _sim_lock:
        outputs = [i.get('output') for i in _sim_state['instances'] if i.get('output')]
    _stop_sim()

    with _queue_lock:
        item['finished_at'] = time.time()
        if result == 'paused':
            item['status'] = 'queued'  # resumes (from scratch) on next play
            item['started_at'] = None
        elif result == 'stopped':
            item['status'] = 'stopped'
            if outputs:
                item['recording'] = Path(outputs[0]).name
        else:
            item['status'] = 'done'
            item['timed_out'] = result == 'timeout'
            if outputs:
                item['recording'] = Path(outputs[0]).name
        _queue['current_uid'] = None
        _save_queue_locked()

    if result in ('complete', 'timeout'):
        _set_schem_column(schem['id'], 'built')


def _queue_runner():
    while True:
        time.sleep(2)
        with _queue_lock:
            if _queue['state'] != 'playing':
                continue
            item = next((i for i in _queue['items'] if i['status'] == 'queued'), None)
            if item is None:
                _queue['state'] = 'stopped'  # everything processed
                _save_queue_locked()
                continue
        if _sim_state.get('running'):
            continue  # rig busy with a manual run — wait
        try:
            _run_queue_item(item)
        except Exception as exc:
            with _queue_lock:
                item['status'] = 'failed'
                item['error'] = str(exc)
                _queue['current_uid'] = None
                _save_queue_locked()


threading.Thread(target=_queue_runner, daemon=True).start()
