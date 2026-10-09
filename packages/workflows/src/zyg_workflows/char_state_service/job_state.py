# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Character job reconcile/derive/mark/reload and stale-running orphaning.

Moved verbatim out of the old single-file char_state_service.py (lines 1522-1665, 2172-2243).
"""

import json
import os
from zyg_workflows.runtime import (
    _ams_iso,
    _char_gen_jobs,
    _runtime_path,
)
from zyg_workflows.char_state_service._common import (
    _CHARS_DATASETS,
    _zyg_log,
)
from zyg_workflows.char_state_service.char_state import (
    _char_save_state,
)
from zyg_workflows.char_state_service.lora_discovery import (
    _normalize_char_model_family,
)
from zyg_workflows.char_state_service.preview_reference import (
    _have_usable_char_preview,
)


def _char_reconcile_job_state(job: dict) -> dict:
    """Repair stale char_gen state (e.g. status=running after completion)."""
    if not job:
        return job
    if job.get('status') != 'running':
        return job

    cid = (job.get('char_id') or '').strip()
    params = job.get('params') or {}
    mf = _normalize_char_model_family(job.get('model_family'), params, {})
    ds = params.get('dataset_dir') or (str(_CHARS_DATASETS / cid) if cid else '')
    has_previews = _have_usable_char_preview(ds, mf, params, {}) if cid else False

    tl = job.get('stage_timeline') or []
    _1d_ok = any('1d' in (e.get('name') or '').lower() and e.get('status') == 'completed' for e in tl)
    _1d_failed = any('1d' in (e.get('name') or '').lower() and e.get('status') == 'failed' for e in tl)

    for ev in reversed((job.get('debug_events') or [])[-30:]):
        msg = str(ev.get('msg', '')).lower()
        if 'generation complete' in msg:
            if has_previews or _1d_ok:
                job['status'] = 'done'
                job['stage'] = 'done'
                job['current_stage'] = 'done'
                job.setdefault('ended', ev.get('ts'))
            elif _1d_failed or job.get('lora_failed'):
                job['status'] = 'error'
                job['stage'] = 'error'
                job['current_stage'] = 'error'
                job.setdefault('error', job.get('error') or 'preview generation failed')
                job.setdefault('ended', ev.get('ts'))
            return job

    if _1d_ok or (has_previews and not _1d_failed):
        if has_previews and job.get('preview_quality_ok') is False:
            job['status'] = 'error'
            job['stage'] = 'error'
            job['current_stage'] = 'error'
            job.setdefault(
                'error',
                job.get('preview_warning') or 'preview quality check failed',
            )
        else:
            job['status'] = 'done'
            job['stage'] = 'done'
            job['current_stage'] = 'done'
            for e in reversed(tl):
                if e.get('ended_at'):
                    job.setdefault('ended', e.get('ended_at'))
                    break
    elif _1d_failed and not has_previews:
        job['status'] = 'error'
        job['stage'] = 'error'
        job['current_stage'] = 'error'
        job.setdefault('error', job.get('error') or 'preview generation failed')
    return job


def _char_derive_pipeline_stage(job: dict) -> str:
    """Map live job dict → kanban stage key (blender_render … done)."""
    job = _char_reconcile_job_state(dict(job))
    st = (job.get('stage') or '').strip().lower()
    if job.get('status') in ('done', 'error'):
        return 'done' if job.get('status') == 'done' else st or 'error'
    cs = (job.get('current_stage') or '').lower()
    if '1d' in cs or 'preview render' in cs:
        return 'preview_render'
    if '1c' in cs or 'lora training' in cs:
        return 'lora_training'
    if 'sdxl lora' in cs or 'flux lora' in cs:
        return 'lora_training'
    if '1b' in cs or 'caption' in cs:
        return 'captions'
    if st in ('blender_render', 'flux_fallback', 'captions', 'lora_training', 'preview_render', 'done'):
        return st
    return st or 'blender_render'


def _char_mark_done(char_id: str, job: dict | None = None) -> None:
    job = _char_gen_jobs.get(char_id) or job
    if not job:
        return
    job['status'] = 'done'
    job['stage'] = 'done'
    job['current_stage'] = 'done'
    job['ended'] = _ams_iso()
    _char_save_state(char_id)


def _char_mark_error(char_id: str, error: str, job: dict | None = None) -> None:
    job = _char_gen_jobs.get(char_id) or job
    if not job:
        return
    job['status'] = 'error'
    job['stage'] = 'error'
    job['current_stage'] = 'error'
    job['error'] = (error or '')[:500]
    job['ended'] = _ams_iso()
    _char_save_state(char_id)


def _char_reload_jobs_from_disk() -> int:
    """Hydrate _char_gen_jobs from data/runtime/char_gen_*.json (survives restarts).

    Any job still marked ``running`` cannot have a live worker after process
    restart — those are finalized via :func:`_char_orphan_stale_running_job`.
    """
    import glob as _glob

    n = 0
    n_orphan = 0
    runtime_dir = _runtime_path('')
    for path in _glob.glob(os.path.join(runtime_dir, 'char_gen_*.json')):
        try:
            with open(path, encoding='utf-8') as fh:
                job = json.load(fh)
            cid = (job.get('char_id') or '').strip()
            if not cid:
                continue
            if not job.get('model_family'):
                _mf = ((job.get('params') or {}).get('model_family') or '').strip().lower()
                if _mf in ('flux', 'sdxl', 'qwen', 'klein'):
                    job['model_family'] = _mf
            _before = job.get('status')
            job = _char_reconcile_job_state(job)
            _orphaned = False
            if job.get('status') == 'running':
                job, _orphaned = _char_orphan_stale_running_job(job)
                if _orphaned:
                    n_orphan += 1
            _char_gen_jobs[cid] = job
            if _orphaned or job.get('status') != _before:
                _char_save_state(cid)
            n += 1
        except Exception as _exc:
            _zyg_log.warning('character job skipped on restart, state unreadable: %s', _exc)
            continue
    if n_orphan:
        _zyg_log.info(f'[CHAR-STATE] Orphaned {n_orphan} stale running character job(s) on restart')
    return n


def _char_close_running_timeline(job: dict, final_status: str) -> None:
    """Close any stage_timeline rows left open as ``running``."""
    tl = job.setdefault('stage_timeline', [])
    now = _ams_iso()
    for entry in tl:
        if entry.get('status') == 'running':
            entry['status'] = final_status
            entry['ended_at'] = now


def _char_orphan_stale_running_job(job: dict) -> tuple[dict, bool]:
    """Finalize disk-hydrated jobs that still say ``running`` after server restart.

    No background ``char-gen-*`` thread survives a process restart, so these are
    orphans.  Promote to ``done`` when completion evidence exists on disk;
    otherwise mark ``error`` so Kanban does not show a fake live pipeline.
    """
    job = dict(job)
    cid = (job.get('char_id') or '').strip()
    if job.get('status') != 'running':
        return job, False

    job = _char_reconcile_job_state(job)
    if job.get('status') != 'running':
        return job, True

    params = job.get('params') or {}
    mf = _normalize_char_model_family(job.get('model_family'), params, {})
    ds = params.get('dataset_dir') or str(_CHARS_DATASETS / cid)

    if _have_usable_char_preview(ds, mf, params, {}):
        if job.get('preview_quality_ok') is False:
            job['status'] = 'error'
            job['stage'] = 'error'
            job['current_stage'] = 'error'
            job.setdefault(
                'error',
                job.get('preview_warning') or 'preview quality check failed',
            )
            job['orphan_note'] = 'finalized on restart (previews on disk, quality failed)'
            _char_close_running_timeline(job, 'failed')
        else:
            job['status'] = 'done'
            job['stage'] = 'done'
            job['current_stage'] = 'done'
            job.setdefault('ended', _ams_iso())
            job['orphan_note'] = 'finalized on restart (previews on disk)'
            _char_close_running_timeline(job, 'completed')
        return job, True

    tl = job.get('stage_timeline') or []
    _1c_done = any('1c' in (e.get('name') or '').lower() and e.get('status') == 'completed' for e in tl)
    _1d_done = any('1d' in (e.get('name') or '').lower() and e.get('status') == 'completed' for e in tl)
    if _1d_done or _1c_done:
        job['status'] = 'done'
        job['stage'] = 'done'
        job['current_stage'] = 'done'
        job.setdefault('ended', _ams_iso())
        job['orphan_note'] = 'finalized on restart (stage timeline complete)'
        _char_close_running_timeline(job, 'completed')
        return job, True

    stage_hint = job.get('current_stage') or job.get('stage') or 'unknown'
    job['status'] = 'error'
    job['stage'] = 'error'
    job['current_stage'] = 'error'
    job['error'] = f'Orphaned on server restart (was: {stage_hint})'
    job['ended'] = _ams_iso()
    job['orphan_note'] = 'marked error on restart (no live worker)'
    _char_close_running_timeline(job, 'failed')
    return job, True
