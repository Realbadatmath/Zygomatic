# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""entry — entry section of pipeline_remixai (verbatim split).

Moved unchanged from pipeline_remixai.py; see the package __init__ for the full docstring.
"""

from __future__ import annotations

from .core import _OUT_ROOT, _env_f, _jobs, _mk_job, _tree_gb, _zyg_log, disk_ok, os, runtime, shutil, threading, time
from .pipeline import _run_pipeline


# ── public entry points ─────────────────────────────────────────────────────


def _gpu_busy() -> bool:
    try:
        return bool(runtime.gpu_work_active())
    except Exception:
        return False


def start_remix_ai(video_id: str = '', directive: str = '', force: bool = False) -> dict:
    """Start one Remix Ai job. Returns {'pipeline_id': …} or {'error': …}."""
    if not force and _gpu_busy():
        return {'error': 'pipeline_busy'}
    ok, why = disk_ok()
    if not ok and not force:
        return {'error': f'disk gate: {why}'}
    pid = _mk_job(directive or f'Remix Ai — {video_id or "top candidate"}', params={'video_id': video_id})
    os.makedirs(os.path.join(_OUT_ROOT, pid), exist_ok=True)
    t = threading.Thread(target=_run_pipeline, args=(pid, video_id, force), name=f'remixai-{pid}', daemon=True)
    t.start()
    return {'pipeline_id': pid, 'job_id': pid, 'status': 'running'}


def stop_remix_ai(pid: str) -> dict:
    j = _jobs().get(pid)
    if not j:
        return {'error': 'unknown pipeline'}
    ev = j.get('stop_event')
    if ev is not None:
        ev.set()
    return {'stopped': True, 'pipeline_id': pid}


def retention_sweep(log=None) -> dict:
    """Delete delivered jobs older than the TTL and any crashed-job residue."""
    ttl_h = _env_f('ZYG_REMIXAI_TTL_H', 168)  # 7 days
    now, removed, freed = time.time(), 0, 0.0
    if not os.path.isdir(_OUT_ROOT):
        return {'removed': 0, 'freed_gb': 0.0}
    for d in os.listdir(_OUT_ROOT):
        p = os.path.join(_OUT_ROOT, d)
        if not os.path.isdir(p):
            continue
        try:
            age_h = (now - os.path.getmtime(p)) / 3600.0
        except OSError as _exc:
            _zyg_log.debug('age of %s unreadable, skipped by the TTL sweep: %s', p, _exc)
            continue
        if age_h < ttl_h:
            # still within the window — but a crashed job's work dir can go
            w = os.path.join(p, 'work')
            if os.path.isdir(w) and age_h > 6 and not _pid_running(d):
                freed += _tree_gb(w)
                shutil.rmtree(w, ignore_errors=True)
            continue
        freed += _tree_gb(p)
        shutil.rmtree(p, ignore_errors=True)
        removed += 1
    if log and removed:
        log(f'retention: removed {removed} job dir(s), freed {freed:.1f} GB')
    return {'removed': removed, 'freed_gb': round(freed, 2)}


def _pid_running(pid: str) -> bool:
    for t in threading.enumerate():
        if t.name == f'remixai-{pid}' and t.is_alive():
            return True
    return False
