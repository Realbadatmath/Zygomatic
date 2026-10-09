# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

# Generated 2026-07-17 heavy-tranche modularization — extracted from crewai_web_gui.py.
# See crews_modularization_backups_20260717/MODULARIZATION_CHANGELOG.md.
# Contract: imported only at the BOTTOM of crewai_web_gui.py (all main globals exist;
# the running __main__ instance is aliased as `crewai_web_gui` in sys.modules).
import os
import subprocess
import time
import threading
from zyg_workflows.bin import exe
from zyg_workflows.runtime import (
    _agent_log,
    _ams_iso,
    _SUBPROC_LOCK,
    _SUBPROC_REGISTRY,
    _SUBPROC_SYNTHETIC_COUNTER,
)
import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)


def _register_subproc(pid: int, label: str, pipeline_id: str = '', status: str = 'running'):
    with _SUBPROC_LOCK:
        _SUBPROC_REGISTRY[pid] = {
            'pid': pid,
            'label': label,
            'pipeline_id': pipeline_id,
            'started': _ams_iso(),
            'status': status,
            'ended': None,
            'cpu_pct': 0.0,
            'max_cpu_pct': 0.0,
            'gpu_pct': 0.0,
            'max_gpu_pct': 0.0,
            'samples': [],
        }
    return pid


def _register_marker(label: str, pipeline_id: str = '', status: str = 'pipeline') -> int:
    """Register a synthetic (non-OS) pipeline stage marker visible in Tail Subs."""
    with _SUBPROC_LOCK:
        fake_pid = _SUBPROC_SYNTHETIC_COUNTER[0]
        _SUBPROC_SYNTHETIC_COUNTER[0] += 1
        _SUBPROC_REGISTRY[fake_pid] = {
            'pid': fake_pid,
            'label': label,
            'pipeline_id': pipeline_id,
            'started': _ams_iso(),
            'status': status,
            'ended': None,
            'cpu_pct': None,
            'max_cpu_pct': None,
            'gpu_pct': None,
            'max_gpu_pct': None,
            'samples': [],
        }
    return fake_pid


def _update_marker(fake_pid: int, status: str = None, label: str = None):
    with _SUBPROC_LOCK:
        if fake_pid in _SUBPROC_REGISTRY:
            if status:
                _SUBPROC_REGISTRY[fake_pid]['status'] = status
                if status in ('done', 'failed', 'killed'):
                    _SUBPROC_REGISTRY[fake_pid]['ended'] = _ams_iso()
            if label:
                _SUBPROC_REGISTRY[fake_pid]['label'] = label


def _finish_subproc(pid: int, ok: bool = True):
    _mc = _mg = 0
    _lbl = str(pid)
    with _SUBPROC_LOCK:
        if pid in _SUBPROC_REGISTRY:
            info = _SUBPROC_REGISTRY[pid]
            info['status'] = 'done' if ok else 'failed'
            info['ended'] = _ams_iso()
            _mc = info.get('max_cpu_pct', 0)
            _mg = info.get('max_gpu_pct', 0)
            _lbl = info.get('label', str(pid))
    _finish_msg = f'Worker {_lbl} finished — peak CPU: {_mc:.1f}% peak GPU: {_mg:.1f}%'
    if _mc > 0 or _mg > 0:
        _zyg_log.info(f'[SUBPROC] {_finish_msg}')
    # Always log to logbook so it appears in Live Tail
    _pipeline_id = ''
    with _SUBPROC_LOCK:
        _pipeline_id = _SUBPROC_REGISTRY.get(pid, {}).get('pipeline_id', '')
    _agent_log('INFO', 'WORKER', _pipeline_id, 'subprocess', _finish_msg)


def _kill_all_subprocs(pipeline_id: str = ''):
    """Kill all registered running subprocesses (optionally filtered by pipeline_id)."""
    import signal as _sig

    killed = []
    with _SUBPROC_LOCK:
        for pid, info in list(_SUBPROC_REGISTRY.items()):
            if info['status'] != 'running':
                continue
            if pipeline_id and info.get('pipeline_id') != pipeline_id:
                continue
            try:
                os.kill(pid, _sig.SIGKILL)
                info['status'] = 'killed'
                info['ended'] = _ams_iso()
                killed.append(pid)
            except (ProcessLookupError, OSError):
                info['status'] = 'gone'
    return killed


def _subproc_monitor_loop():
    """Daemon thread: sample CPU%/GPU% for every running registered subprocess every 2s."""
    import psutil

    _ps_procs = {}
    while True:
        try:
            with _SUBPROC_LOCK:
                running_pids = [pid for pid, info in _SUBPROC_REGISTRY.items() if info.get('status') == 'running']
            # ── CPU sampling ──────────────────────────────────────────────────
            cpu_count = psutil.cpu_count() or 1
            for pid in running_pids:
                try:
                    if pid not in _ps_procs:
                        _ps_procs[pid] = psutil.Process(pid)
                    pct = _ps_procs[pid].cpu_percent(interval=None) / cpu_count
                    with _SUBPROC_LOCK:
                        if pid in _SUBPROC_REGISTRY:
                            _SUBPROC_REGISTRY[pid]['cpu_pct'] = round(pct, 1)
                            if pct > _SUBPROC_REGISTRY[pid].get('max_cpu_pct', 0):
                                _SUBPROC_REGISTRY[pid]['max_cpu_pct'] = round(pct, 1)
                except psutil.NoSuchProcess:
                    _ps_procs.pop(pid, None)
                except Exception as _exc:
                    _zyg_log.debug('cpu sample skipped for pid %s: %s', pid, _exc)
            # ── GPU sampling via nvidia-smi pmon ─────────────────────────────
            gpu_map = {}
            try:
                _r = subprocess.run(
                    [exe('nvidia-smi'), 'pmon', '-s', 'u', '-c', '1', '--id', '0'],
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                for line in _r.stdout.splitlines():
                    if line.startswith('#') or not line.strip():
                        continue
                    cols = line.split()
                    if len(cols) >= 4:
                        try:
                            gpu_map[int(cols[1])] = int(cols[3])
                        except (ValueError, IndexError) as _exc:
                            _zyg_log.debug('nvidia-smi pmon row ignored: %s', _exc)
            except Exception as _exc:
                _zyg_log.debug('gpu sampling via nvidia-smi skipped: %s', _exc)
            # Apply GPU map and append samples
            for pid in running_pids:
                gpu_pct = float(gpu_map.get(pid, 0))
                with _SUBPROC_LOCK:
                    if pid in _SUBPROC_REGISTRY:
                        _SUBPROC_REGISTRY[pid]['gpu_pct'] = gpu_pct
                        if gpu_pct > _SUBPROC_REGISTRY[pid].get('max_gpu_pct', 0):
                            _SUBPROC_REGISTRY[pid]['max_gpu_pct'] = gpu_pct
                        cpu_pct = _SUBPROC_REGISTRY[pid].get('cpu_pct', 0)
                        samples = _SUBPROC_REGISTRY[pid].setdefault('samples', [])
                        samples.append({'t': _ams_iso(), 'cpu': cpu_pct, 'gpu': gpu_pct})
                        if len(samples) > 120:
                            _SUBPROC_REGISTRY[pid]['samples'] = samples[-120:]
        except Exception as _exc:
            _zyg_log.debug('subprocess monitor pass skipped: %s', _exc)
        time.sleep(2)


_subproc_monitor_thread = threading.Thread(target=_subproc_monitor_loop, name='subproc-monitor', daemon=True)


_subproc_monitor_thread.start()
