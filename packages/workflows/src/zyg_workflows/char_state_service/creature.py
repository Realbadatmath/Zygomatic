# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Creature jobs: state, stage keys and order, external PID, staleness.

Moved verbatim out of the old single-file char_state_service.py (lines 604-777).
"""

import json
import os
import threading
from datetime import datetime, timezone
from zyg_workflows.runtime import (
    _creature_gen_jobs,
    _runtime_path,
)
from zyg_workflows.char_state_service._common import (
    _zyg_log,
)


def _creature_state_path(creature_id: str) -> str:
    safe_id = ''.join(c for c in (creature_id or '') if c.isalnum() or c in '-_')
    return _runtime_path(f'creature_gen_{safe_id or "unknown"}.json')


def _creature_save_state(creature_id: str) -> None:
    try:
        job = _creature_gen_jobs.get(creature_id)
        if not job:
            return
        snapshot = dict(job)
        evs = snapshot.get('debug_events') or []
        if len(evs) > 50:
            snapshot['debug_events'] = evs[-50:]
        os.makedirs(os.path.dirname(_creature_state_path(creature_id)), exist_ok=True)
        tmp_path = _creature_state_path(creature_id) + '.tmp'
        with open(tmp_path, 'w', encoding='utf-8') as _fh:
            json.dump(snapshot, _fh, default=str)
        os.replace(tmp_path, _creature_state_path(creature_id))
    except Exception as _e:
        _zyg_log.info(f'[CREATURE-STATE] save failed for {creature_id}: {_e}')


def _creature_stage_key(stage_name: str) -> str:
    """Stage display name → state key. 2026-08-25: the sheet stages (anchor /
    multi-angle sheet / sheet qc / sheet review) sit between brief and captions;
    the legacy 'reference' key still maps so old state files derive correctly."""
    sl = (stage_name or '').lower()
    if 'brief' in sl:
        return 'creature_brief'
    if 'anchor' in sl:
        return 'anchor'
    if 'preview' in sl:  # before 'review': "p-review" contains it
        return 'preview_render'
    if 'review' in sl:
        return 'sheet_review'
    if 'sheet qc' in sl or 'qc' in sl or 'judge' in sl:
        return 'sheet_qc'
    if 'multi-angle' in sl or 'sheet' in sl:
        return 'sheet'
    if 'reference' in sl or 'image gen' in sl:
        return 'reference_gen'
    if 'caption' in sl:
        return 'captions'
    if 'lora' in sl or 'simpletuner' in sl or 'training' in sl:
        return 'lora_training'
    if 'preview' in sl:
        return 'preview_render'
    if sl in ('done', 'completed'):
        return 'done'
    return sl.replace(' ', '_')[:40] or 'creature_brief'


CREATURE_STAGE_ORDER = (
    'creature_brief',
    'anchor',
    'sheet',
    'sheet_qc',
    'sheet_review',
    'captions',
    'lora_training',
    'preview_render',
    'done',
)


def _creature_derive_pipeline_stage(job: dict) -> str:
    st = (job.get('stage') or '').strip().lower()
    if job.get('status') in ('completed', 'done'):
        return 'done'
    if job.get('status') in ('failed', 'error', 'rejected'):
        return 'done'
    if job.get('status') == 'awaiting_review':
        return 'sheet_review'
    if st in CREATURE_STAGE_ORDER or st == 'reference_gen':
        return st
    cs = (job.get('current_stage') or '').lower()
    if 'preview' in cs:
        return 'preview_render'
    if 'lora' in cs or 'simpletuner' in cs or 'training' in cs:
        return 'lora_training'
    if 'caption' in cs:
        return 'captions'
    if 'review' in cs:
        return 'sheet_review'
    if 'qc' in cs:
        return 'sheet_qc'
    if 'sheet' in cs:
        return 'sheet'
    if 'anchor' in cs:
        return 'anchor'
    if 'reference' in cs:
        return 'reference_gen'
    return st or 'creature_brief'


def _creature_external_pid_alive(job: dict) -> bool:
    """scripts/creature_worker.py runs outside the GUI and records worker.pid."""
    w = job.get('worker') or {}
    pid = w.get('pid')
    if not pid:
        return False
    try:
        os.kill(int(pid), 0)
        return True
    except (OSError, ValueError):
        return False


def _creature_worker_alive(creature_id: str, job: dict | None = None) -> bool:
    if any(t.name == f'creature-train-{creature_id[:8]}' and t.is_alive() for t in threading.enumerate()):
        return True
    job = job if job is not None else _creature_gen_jobs.get(creature_id)
    return bool(job) and _creature_external_pid_alive(job)


def _creature_refresh_external(job: dict) -> dict:
    """A standalone worker owns its state file: re-read it so the board and the
    status API follow the run instead of the first snapshot they hydrated."""
    cid = (job.get('creature_id') or '').strip()
    if not cid or not (job.get('worker') or {}).get('mode') == 'standalone':
        return job
    # Defence in depth (2026-08-26): never swap the registry entry out from under
    # a worker thread running in THIS process — it mutates the dict in place and
    # the replacement orphans every write it has left to make. Only the thread
    # check counts here; _creature_worker_alive would also answer True for a real
    # standalone worker, which is exactly the case this function exists to follow.
    if any(t.name == f'creature-train-{cid[:8]}' and t.is_alive() for t in threading.enumerate()):
        return job
    try:
        with open(_creature_state_path(cid), encoding='utf-8') as fh:
            fresh = json.load(fh)
        _creature_gen_jobs[cid] = fresh
        return fresh
    except Exception:
        return job


def _creature_mark_stale(job: dict) -> bool:
    """A job that says 'running' but has no worker thread in THIS process was
    killed by a GUI restart (2026-08-25). Mark it interrupted so the board and
    the pollers stop waiting; it can be resumed (sheet checkpoints on disk)."""
    cid = (job.get('creature_id') or '').strip()
    if job.get('status') == 'running' and cid and not _creature_worker_alive(cid, job):
        job['status'] = 'interrupted'
        job['error'] = job.get('error') or (
            f'GUI restarted mid-run (no live worker) — resume with scripts/run_creature_sheet.py --resume {cid}'
        )
        job['ended'] = job.get('ended') or datetime.now(timezone.utc).isoformat()
        return True
    return False


def _creature_reload_jobs_from_disk() -> int:
    import glob as _glob_cr

    n = 0
    for path in _glob_cr.glob(os.path.join(_runtime_path(''), 'creature_gen_*.json')):
        try:
            with open(path, encoding='utf-8') as fh:
                job = json.load(fh)
            cid = (job.get('creature_id') or '').strip()
            if cid:
                if cid in _creature_gen_jobs and _creature_worker_alive(cid):
                    continue  # never clobber a live job with a disk snapshot
                _creature_gen_jobs[cid] = job
                if _creature_mark_stale(job):
                    _creature_save_state(cid)
                n += 1
        except Exception as _exc:
            _zyg_log.warning('creature job skipped on reload, state unreadable: %s', _exc)
            continue
    return n
