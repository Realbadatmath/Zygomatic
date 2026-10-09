# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

# ruff: noqa: F401
"""core — core section of pipeline_remixai (verbatim split).

Moved unchanged from pipeline_remixai.py; see the package __init__ for the full docstring.
"""

from __future__ import annotations

import os
import random
import re
import shutil
import subprocess
import threading
import time
import traceback
import uuid

from zyg_workflows import remixai_analyze as RA
from zyg_workflows import remixai_divergence as RD
from zyg_workflows import provenance_seal as _seal
from zyg_workflows import remixai_ingest as RI
from zyg_workflows import runtime
from zyg_workflows import paths
from zyg_workflows.bin import exe
import logging as _zyg_logging

# channel kept from the pre-split module
_zyg_log = _zyg_logging.getLogger('zyg_workflows.pipeline_remixai')


_CREWS = str(paths.PKG_DIR)
_RUNTIME = str(paths.DATA_DIR / 'runtime')
_OUT_ROOT = str(paths.DATA_DIR / 'output' / 'remix_ai')

_FONT = '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf'
_AUDIO_ARGS = ['-c:a', 'aac', '-b:a', '192k', '-ar', '48000', '-ac', '2']

DEPARTMENT = 'remix_ai'

# Stage names — must match KANBAN_STAGE_MAP_REMIXAI keys byte-for-byte.
STAGES = [
    'Source Sweep',
    'Source Download',
    'Frame Analysis',
    'Transcript Analysis',
    'Soundtrack Analysis',
    'Script Regeneration',
    'Title Regeneration',
    'AI Image Generation',
    'TTS Narration',
    'Ken Burns Animation',
    'Video Assembly',
    'Soundtrack Replacement',
    'Subtitle Burn',
    'Delivery',
]


def _env_f(name, default):
    try:
        return float(os.environ.get(name, str(default)) or default)
    except ValueError:
        return float(default)


def _env_i(name, default):
    try:
        return int(os.environ.get(name, str(default)) or default)
    except ValueError:
        return int(default)


# ── runtime accessors ────────────────────────────────────────────────────────
# Read through `runtime` at call time, never bound at import: the dashboard
# registers its implementations after this module is imported.


def _jobs():
    return runtime.workflow_jobs


def _now_iso():
    return runtime.ams_iso()


def _marker(label, pid):
    try:
        from zyg_workflows.subproc_registry import _register_marker

        return _register_marker(label, pipeline_id=pid, status='pipeline')
    except Exception:
        return None


def _marker_update(mid, status=None, label=None):
    if mid is None:
        return
    try:
        from zyg_workflows.subproc_registry import _update_marker

        _update_marker(mid, status=status, label=label)
    except Exception as _exc:
        _zyg_log.debug('subprocess marker update skipped: %s', _exc)


# ── job scaffolding (pipeline_remix.py shape) ───────────────────────────────


def _mk_job(directive, params=None):
    pid = uuid.uuid4().hex[:12]
    _jobs()[pid] = {
        'job_id': pid,
        'pipeline_id': pid,
        'status': 'running',
        'department': DEPARTMENT,
        'mode': 'remix_ai',
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


_LAST_FLUSH = {}
_FLUSH_EVERY_S = 20.0


def _log(pid, level, stage, msg):
    j = _jobs().get(pid)
    entry = {'ts': _now_iso(), 'level': level, 'stage': stage, 'msg': str(msg)[:400]}
    if j is not None:
        j.setdefault('debug_events', []).append(entry)
        if len(j['debug_events']) > 1000:
            j['debug_events'] = j['debug_events'][-700:]
    _zyg_log.info(f'[REMIXAI|{level}|{stage}] {msg}')
    # Persist periodically INSIDE a stage. State used to be written only by
    # _update_stage/_finish, so anything reading the state file during a long
    # stage saw the last transition and nothing since — Frame Analysis sat at
    # '16%, no events' for twenty minutes while it was in fact working through
    # frames, and the only way to tell a working job from a wedged one was to
    # grep flask.log. Throttled so a chatty stage does not write on every line.
    if j is not None:
        now = time.time()
        if now - _LAST_FLUSH.get(pid, 0.0) >= _FLUSH_EVERY_S:
            _LAST_FLUSH[pid] = now
            try:
                _save_state(pid)
            except Exception as _exc:
                _zyg_log.warning('job state flush failed, the state file will lag this run: %s', _exc)


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
    state['department'] = DEPARTMENT
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


# ── disk gate (FAIL CLOSED — shared volume, same policy as remix) ───────────


def disk_ok() -> tuple:
    free_gb = shutil.disk_usage('/').free / 1e9
    min_free = _env_f('ZYG_REMIXAI_MIN_FREE_GB', 100)
    if free_gb < min_free:
        return False, f'free disk {free_gb:.0f} GB < floor {min_free:.0f} GB'
    max_gb = _env_f('ZYG_REMIXAI_MAX_GB', 120)
    used = _tree_gb(_OUT_ROOT)
    if used > max_gb:
        return False, f'remix_ai tree {used:.0f} GB > cap {max_gb:.0f} GB'
    return True, f'free {free_gb:.0f} GB, remix_ai tree {used:.1f} GB'


def _tree_gb(root) -> float:
    total = 0
    for dirpath, _dirs, files in os.walk(root):
        for fn in files:
            try:
                total += os.path.getsize(os.path.join(dirpath, fn))
            except OSError as _exc:
                _zyg_log.debug('disk usage skipped for %s: %s', fn, _exc)
    return total / 1e9


def _run(cmd, timeout=600):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.returncode, r.stdout or '', r.stderr or ''
    except subprocess.TimeoutExpired:
        return -1, '', f'timeout after {timeout}s'
    except Exception as e:
        return -1, '', str(e)


def _duration(path) -> float:
    return RA.probe_duration(path)
