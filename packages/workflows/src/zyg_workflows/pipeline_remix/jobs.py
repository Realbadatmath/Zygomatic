# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""pipeline_remix.jobs — job scaffolding, state, the stop flag and the disk gates.

Lines 112-250 of the original pipeline_remix.py, moved verbatim
(2026-10-06 split). No logic changed.
"""

from __future__ import annotations

import logging as _zyg_logging
import os
import shutil
import threading
import uuid

from zyg_workflows import remix_ingest as RI

from .constants import _OUT_ROOT, _RUNTIME, _env_f, _jobs, _now_iso

# Bound by assignment (never `from . import`), to __package__ — which IS the
# old module's own __name__, whichever route it is imported by. The logger a
# moved line writes to must not be renamed by the move.
_zyg_log = _zyg_logging.getLogger(__package__)


# ── job scaffolding ──────────────────────────────────────────────────────────


def _mk_job(mode, directive, params=None):
    pid = uuid.uuid4().hex[:12]
    _jobs()[pid] = {
        'job_id': pid,
        'pipeline_id': pid,
        'status': 'running',
        'department': 'remix',
        'mode': mode,
        'stop_event': threading.Event(),
        'current_stage': None,
        'started': _now_iso(),
        'directive': (directive or '').strip(),
        'params': params or {},
        'stages': {},
        'stage_timeline': [],
        'debug_events': [],
        'result': None,
        'error': None,
        'output_dir': os.path.join(_OUT_ROOT, pid),
    }
    return pid


def _log(pid, level, stage, msg):
    j = _jobs().get(pid)
    entry = {'ts': _now_iso(), 'level': level, 'stage': stage, 'msg': str(msg)[:400]}
    if j is not None:
        j.setdefault('debug_events', []).append(entry)
        if len(j['debug_events']) > 1000:
            j['debug_events'] = j['debug_events'][-700:]
    _zyg_log.info(f'[REMIX|{level}|{stage}] {msg}')


def _update_stage(pid, stage, pct=None):
    j = _jobs().get(pid)
    if j is None:
        return
    j['current_stage'] = stage
    if pct is not None:
        j['progress_pct'] = pct
    tl = j.setdefault('stage_timeline', [])
    for e in tl:
        if e.get('status') == 'running':
            e['status'] = 'completed'
            e.setdefault('ended_at', _now_iso())
    existing = next((e for e in tl if e.get('name') == stage), None)
    if existing is not None:
        existing['status'] = 'running'
    else:
        tl.append({'name': stage, 'status': 'running', 'started_at': _now_iso()})
    _log(pid, 'INFO', stage, f'▶ {stage}')
    _save_state(pid)


def _finish(pid, ok, result=None, error=None):
    j = _jobs().get(pid)
    if j is None:
        return
    for e in j.get('stage_timeline') or []:
        if e.get('status') == 'running':
            e['status'] = 'completed' if ok else 'failed'
            e.setdefault('ended_at', _now_iso())
    j['status'] = 'completed' if ok else 'failed'
    j['ended'] = _now_iso()
    j['current_stage'] = None
    j['result'] = result
    j['error'] = error
    _save_state(pid)


def _save_state(pid):
    j = _jobs().get(pid)
    if j is None:
        return
    state = {k: v for k, v in j.items() if k not in ('stop_event',)}
    state['department'] = 'remix'
    RI._save(os.path.join(_RUNTIME, f'pipeline_{pid}_state.json'), state)


def _stopped(pid) -> bool:
    j = _jobs().get(pid) or {}
    ev = j.get('stop_event')
    if ev is not None and ev.is_set():
        return True
    try:
        from zyg_workflows import gui_state

        if getattr(gui_state, '_pipeline_stop_flag', False):
            return True
    except Exception as _exc:
        _zyg_log.debug('gui_state stop flag unreadable: %s', _exc)
    try:
        from zyg_workflows import pipeline_control as _pc

        if _pc.halt_requested():
            return True
    except Exception as _exc:
        _zyg_log.debug('pipeline halt flag unreadable: %s', _exc)
    return False


class _Stopped(Exception):
    pass


def _check_stop(pid):
    if _stopped(pid):
        raise _Stopped('Pipeline stopped by user')


# ── disk gates (FAIL CLOSED — 309 GB shared volume, no media retention elsewhere) ──


def disk_ok(log=None) -> tuple:
    free_gb = shutil.disk_usage('/').free / 1e9
    min_free = _env_f('ZYG_REMIX_MIN_FREE_GB', 100)
    if free_gb < min_free:
        return False, f'free disk {free_gb:.0f} GB < floor {min_free:.0f} GB'
    max_gb = _env_f('ZYG_REMIX_MAX_GB', 150)
    used = _tree_gb(_OUT_ROOT)
    if used > max_gb:
        return False, f'remix tree {used:.0f} GB > cap {max_gb:.0f} GB'
    return True, f'free {free_gb:.0f} GB, remix tree {used:.1f} GB'


def _tree_gb(root) -> float:
    total = 0
    for dirpath, _dirs, files in os.walk(root):
        for fn in files:
            try:
                total += os.path.getsize(os.path.join(dirpath, fn))
            except OSError as _exc:
                _zyg_log.debug('disk usage skipped for %s: %s', fn, _exc)
    return total / 1e9
