# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Contact-sheet jobs: state, timeline, worker, VRAM release, resume.

Moved verbatim out of the old single-file char_state_service.py (lines 154-602).
"""

import json
import os
import threading
from zyg_workflows.vram_manager import _release_pipeline_vram
from zyg_workflows.pipeline_config import (
    _CONTACT_SHEET_STATE_FMT,
)
from zyg_workflows.runtime import (
    _ams_iso,
    _ams_now,
    _contact_sheet_jobs,
    _contact_sheet_push_review_pending,
    _parse_iso_to_ams,
    _runtime_path,
)
from zyg_workflows.char_state_service._common import (
    _zyg_log,
)
from zyg_workflows.char_state_service.lora_training import (
    _char_train_lora_for_family,
)


def _contact_sheet_state_path(char_id: str) -> str:
    safe_id = ''.join(c for c in (char_id or '') if c.isalnum() or c in '-_')
    return _runtime_path(_CONTACT_SHEET_STATE_FMT.format(char_id=safe_id or 'unknown'))


def _contact_sheet_save_state(char_id: str) -> None:
    try:
        job = _contact_sheet_jobs.get(char_id)
        if not job:
            return
        snapshot = dict(job)
        evs = snapshot.get('debug_events') or []
        if len(evs) > 50:
            snapshot['debug_events'] = evs[-50:]
        os.makedirs(os.path.dirname(_contact_sheet_state_path(char_id)), exist_ok=True)
        tmp = _contact_sheet_state_path(char_id) + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as fh:
            json.dump(snapshot, fh, default=str)
        os.replace(tmp, _contact_sheet_state_path(char_id))
    except Exception as _e:
        try:
            _zyg_log.info(f'[CONTACT-SHEET-STATE] save failed for {char_id}: {_e}')
        except Exception as _exc:
            _zyg_log.debug('console echo of the save failure skipped: %s', _exc)


def _contact_sheet_emit(char_id: str, msg: str, *, level: str = 'INFO', stage: str = '') -> None:
    job = _contact_sheet_jobs.get(char_id)
    if not job:
        return
    ev = {
        'ts': _ams_iso(),
        'level': level,
        'stage': stage or job.get('current_stage') or job.get('stage') or 'contact_sheet',
        'msg': msg,
    }
    job.setdefault('debug_events', []).append(ev)
    _contact_sheet_save_state(char_id)


def _contact_sheet_stage_start(char_id: str, name: str) -> None:
    job = _contact_sheet_jobs.get(char_id)
    if not job:
        return
    tl = job.setdefault('stage_timeline', [])
    now = _ams_iso()
    for entry in tl:
        if entry.get('name') == name:
            entry['status'] = 'running'
            if not entry.get('started_at'):
                entry['started_at'] = now
            entry['ended_at'] = None
            _contact_sheet_save_state(char_id)
            return
    tl.append(
        {
            'name': name,
            'status': 'running',
            'started_at': now,
            'ended_at': None,
            'elapsed_s': None,
            'extra': {},
        }
    )
    job['current_stage'] = name
    _contact_sheet_save_state(char_id)


def _contact_sheet_stage_end(char_id: str, name: str, status: str = 'completed', extra: dict | None = None) -> None:
    job = _contact_sheet_jobs.get(char_id)
    if not job:
        return
    tl = job.setdefault('stage_timeline', [])
    now = _ams_iso()
    for entry in tl:
        if entry.get('name') == name:
            entry['status'] = status
            entry['ended_at'] = now
            if extra:
                entry.setdefault('extra', {}).update(
                    {k: v for k, v in extra.items() if isinstance(v, (str, int, float, bool)) or v is None}
                )
            _contact_sheet_save_state(char_id)
            return
    _contact_sheet_save_state(char_id)


def _contact_sheet_derive_stage(job: dict) -> str:
    st = (job.get('stage') or 'sheet_generate').strip().lower()
    if job.get('status') in ('done', 'error'):
        return 'done' if job.get('status') == 'done' else st
    return st


def _contact_sheet_worker_alive(char_id: str) -> bool:
    """True when a live ``contact-sheet-*`` daemon thread is processing this char."""
    cid = (char_id or '').strip()
    if not cid:
        return False
    import threading as _th_cs

    needle = f'contact-sheet-{cid[:8]}'
    return any(t.name == needle and t.is_alive() for t in _th_cs.enumerate())


def _contact_sheet_close_running_timeline(job: dict, final_status: str) -> None:
    tl = job.setdefault('stage_timeline', [])
    now = _ams_iso()
    for entry in tl:
        if entry.get('status') == 'running':
            entry['status'] = final_status
            entry['ended_at'] = now


def _contact_sheet_orphan_stale_running_job(job: dict) -> tuple[dict, bool]:
    """Finalize contact-sheet jobs still ``running`` after restart with no live worker.

    Awaiting-approval jobs with a sheet on disk become ``paused`` so Kanban does not
    hijack an active storyteller/documentary run; approve API still works via ``stage``.
    """
    job = dict(job)
    cid = (job.get('char_id') or '').strip()
    if job.get('status') != 'running' or not cid:
        return job, False
    if _contact_sheet_worker_alive(cid):
        return job, False

    from zyg_workflows import contact_sheet_pipeline as _csp_oc

    stage = (job.get('stage') or 'sheet_generate').strip().lower()
    if job.get('status') == 'done' or stage == 'done':
        job['status'] = 'done'
        job['stage'] = 'done'
        job.setdefault('ended', _ams_iso())
        job['orphan_note'] = 'finalized on restart (already done)'
        _contact_sheet_close_running_timeline(job, 'completed')
        return job, True

    if stage == 'awaiting_approval' or (stage == 'sheet_generate' and _csp_oc.master_sheet_exists(cid)):
        job['status'] = 'paused'
        job['stage'] = 'awaiting_approval'
        job['orphan_note'] = 'paused on restart (awaiting approval — no live worker)'
        _contact_sheet_close_running_timeline(job, 'completed')
        return job, True

    if stage in (
        'tile_crop',
        'identity_qc',
        'captions',
        'lora_training',
        'angle_expansion',
        'lora_refine',
    ):
        _manifest = _csp_oc.load_manifest(cid) or {}
        _has_tiles = bool(_manifest.get('tiles')) or (
            os.path.isdir(_csp_oc.tiles_dir(cid))
            and any(f.lower().endswith(('.png', '.jpg', '.jpeg', '.webp')) for f in os.listdir(_csp_oc.tiles_dir(cid)))
        )
        if _has_tiles:
            job['status'] = 'paused'
            job['stage'] = stage
            job['orphan_note'] = f'paused on restart (was {stage} — resume via approve/restart)'
            _contact_sheet_close_running_timeline(job, 'completed')
            return job, True

    job['status'] = 'error'
    job['stage'] = 'error'
    job['error'] = f'Orphaned on server restart (was: {stage})'
    job['ended'] = _ams_iso()
    job['orphan_note'] = 'marked error on restart (no live worker)'
    _contact_sheet_close_running_timeline(job, 'failed')
    return job, True


def _contact_sheet_reload_jobs_from_disk() -> int:
    """Hydrate contact-sheet jobs from disk; orphan stale ``running`` rows. Returns count loaded."""
    import glob as _glob_cs

    n = 0
    n_orphan = 0
    for path in _glob_cs.glob(os.path.join(_runtime_path(''), 'contact_sheet_*.json')):
        try:
            with open(path, encoding='utf-8') as fh:
                job = json.load(fh)
            cid = (job.get('char_id') or '').strip()
            if not cid:
                continue
            if cid in _contact_sheet_jobs and _contact_sheet_worker_alive(cid):
                # A live worker thread owns the in-memory dict — replacing it
                # with a disk snapshot severs stage/approval updates from it.
                continue
            _before = job.get('status')
            job, _orphaned = _contact_sheet_orphan_stale_running_job(job)
            # Zombie sweep: an approval request whose worker is dead and that is
            # older than 48h can never be satisfied — archive it instead of
            # letting the UI demand an approval nobody can give. (QC-valve parks
            # with a live waiting worker are skipped by the guard above.)
            if job.get('stage') == 'awaiting_approval' and not _contact_sheet_worker_alive(cid):
                try:
                    from datetime import timedelta as _td_z

                    _st = _parse_iso_to_ams(job.get('started') or '')
                    _stale = _st is None or (_ams_now() - _st) > _td_z(hours=48)
                except Exception:
                    _stale = True
                if _stale:
                    job['status'] = 'archived'
                    job['stage'] = 'archived'
                    job['orphan_note'] = 'auto-archived: stale approval request, no live worker'
                    _orphaned = True
            _contact_sheet_jobs[cid] = job
            if _orphaned or job.get('status') != _before:
                _contact_sheet_save_state(cid)
            if _orphaned:
                n_orphan += 1
            n += 1
        except Exception as _exc:
            _zyg_log.warning('contact-sheet job skipped on reload, state unreadable: %s', _exc)
            continue
    if n_orphan:
        _zyg_log.info(f'[CONTACT-SHEET] Orphaned {n_orphan} stale running contact-sheet job(s) on reload')
    return n


def _bg_contact_sheet_pipeline(char_id: str) -> None:
    from zyg_workflows import contact_sheet_pipeline as _csp

    job = _contact_sheet_jobs.get(char_id) or {}
    stage_labels = {
        'sheet_generate': 'Contact Sheet Generation',
        'awaiting_approval': 'Awaiting Approval',
        'tile_crop': 'Tile Crop',
        'identity_qc': 'Identity QC (ArcFace)',
        'captions': 'Caption Generation',
        'lora_training': 'LoRA Training',
        'angle_expansion': 'Angle Expansion (LoRA v1)',
        'lora_refine': 'LoRA Refine (v2)',
        'done': 'Done',
    }
    last_stage = None

    def _on_stage(st: str) -> None:
        nonlocal last_stage
        label = stage_labels.get(st, st.replace('_', ' ').title())
        if last_stage and last_stage != st:
            prev = stage_labels.get(last_stage, last_stage)
            _contact_sheet_stage_end(char_id, prev, 'completed')
        if st != last_stage:
            _contact_sheet_stage_start(char_id, label)
            last_stage = st
        if st == 'awaiting_approval':
            # Surface the sheet review in the Agent Zero approval queue so the
            # operator can approve outside the wizard (Allow → manifest flag).
            try:
                _contact_sheet_push_review_pending(char_id)
            except Exception as _rp_exc:
                _contact_sheet_emit(char_id, f'Review queue push failed: {_rp_exc}', level='WARN')
        _contact_sheet_save_state(char_id)

    from zyg_workflows import pipeline_control as _pc_cs

    try:

        def _halt() -> None:
            # Pause (soft, resumable) is checked before halt (hard, discard) so a
            # paused run unwinds via PipelinePaused into the parked state instead
            # of the error state.
            if _pc_cs.is_paused_for_run(char_id):
                raise _pc_cs.PipelinePaused(char_id, _pc_cs.run_pause_reason(char_id))
            if _pc_cs.halt_requested():
                raise RuntimeError('Pipeline halt requested')

        def _log(msg: str, level: str = 'INFO', stage: str = '') -> None:
            _contact_sheet_emit(char_id, msg, level=level, stage=stage)

        def _save_cell_progress(_done: int, _total: int) -> None:
            _contact_sheet_save_state(char_id)

        _csp.run_pipeline(
            job,
            train_lora_fn=_char_train_lora_for_family,
            log_fn=_log,
            halt_check=_halt,
            on_stage=_on_stage,
            on_cell_progress=_save_cell_progress,
        )
        job['ended'] = _ams_iso()
        # Successful completion clears the resume flags so a later fresh run for
        # this char_id regenerates from scratch instead of reusing old cells.
        job.pop('resume', None)
        job.pop('resume_from', None)
        job.pop('paused_at_stage', None)
        job.pop('paused_reason', None)
        _contact_sheet_emit(char_id, f'Contact sheet pipeline complete for {char_id}')
        _contact_sheet_release_vram_on_done(char_id)
    except _pc_cs.PipelinePaused as _pz:
        # Soft pause: park at the current stage, free this run's VRAM, keep every
        # artifact on disk. A later /resume relaunches and skips finished stages.
        job['status'] = 'paused'
        job['paused_at_stage'] = job.get('stage')
        job['paused_reason'] = getattr(_pz, 'reason', 'Paused by user')
        job['paused_ts'] = _ams_iso()
        _contact_sheet_emit(
            char_id,
            f'Pipeline paused at stage "{job.get("stage")}" — releasing GPU/VRAM',
            level='WARN',
        )
        try:
            _contact_sheet_release_run_vram(char_id)
        except Exception as _vex:
            _contact_sheet_emit(char_id, f'VRAM release warning on pause: {_vex}', level='WARN')
    except Exception as exc:
        job['status'] = 'error'
        job['error'] = str(exc)[:500]
        job['stage'] = 'error'
        _contact_sheet_emit(char_id, f'Pipeline failed: {exc}', level='ERROR')
        _contact_sheet_release_vram_on_done(char_id)
    finally:
        _contact_sheet_save_state(char_id)


def _contact_sheet_release_vram_on_done(char_id: str) -> None:
    """Fully unload ComfyUI models once a contact-sheet run reaches a terminal
    state (done/error) — an idle ComfyUI held ~43 GB for hours after 'done'
    (2026-07-16). Unlike the pause path this never interrupts, and it skips the
    unload entirely when ComfyUI is busy with another pipeline's work: models
    must not be yanked from under a concurrent run (they would reload, slowly
    but safely — so busy = leave it alone).
    """
    try:
        from zyg_workflows import _comfy_client as _cc

        if _cc.server_reachable(timeout_s=1.0):
            if _cc.queue_is_busy():
                _contact_sheet_emit(
                    char_id,
                    'VRAM release skipped — ComfyUI busy with other work',
                )
            elif _cc.free_vram():
                _contact_sheet_emit(
                    char_id,
                    'Run finished — ComfyUI models unloaded, VRAM released',
                )
    except Exception as _vex:
        _contact_sheet_emit(char_id, f'VRAM release warning on completion: {_vex}', level='WARN')
    try:
        _release_pipeline_vram(
            'contact-sheet done',
            log_fn=lambda m: _zyg_log.info(f'[DONE] {m}'),
            wait_comfy=False,
        )
    except Exception as _exc:
        _zyg_log.debug('vram release after the contact sheet skipped: %s', _exc)


def _contact_sheet_release_run_vram(char_id: str) -> None:
    """Free the GPU/VRAM held by a just-paused contact-sheet run.

    Reuses the same primitives the emergency-stop path uses (interrupt the
    in-flight Comfy prompt, then /free VRAM) but scoped to a pause — it does NOT
    set the global halt flag, so other pipelines keep running.
    """
    try:
        from zyg_workflows import _comfy_client as _cc

        if _cc.server_reachable(timeout_s=1.0):
            _cc.interrupt_execution()
            _cc.free_vram()
    except Exception as _exc:
        _zyg_log.debug('comfy interrupt and vram release skipped: %s', _exc)
    try:
        _release_pipeline_vram(
            'pause',
            log_fn=lambda m: _zyg_log.info(f'[PAUSE] {m}'),
            wait_comfy=False,
        )
    except Exception as _exc:
        _zyg_log.debug('pipeline vram release on pause skipped: %s', _exc)


def _contact_sheet_resume_run(char_id: str) -> tuple[dict, int]:
    """Relaunch a paused contact-sheet run, resuming at its parked stage."""
    job = _contact_sheet_jobs.get(char_id)
    if not job:
        try:
            with open(_contact_sheet_state_path(char_id), encoding='utf-8') as fh:
                job = json.load(fh)
            _contact_sheet_jobs[char_id] = job
        except Exception:
            return {'char_id': char_id, 'ok': False, 'error': 'no run found'}, 404
    if job.get('status') == 'running' and _contact_sheet_worker_alive(char_id):
        return {'char_id': char_id, 'ok': False, 'error': 'already running'}, 409
    if job.get('status') != 'paused':
        return {
            'char_id': char_id,
            'ok': False,
            'error': f'run not paused (status={job.get("status")})',
        }, 400

    from zyg_workflows import pipeline_control as _pc

    # Clear this run's pause scope so the worker's halt_check doesn't immediately
    # re-park it. The broad 'production' scope is left as-is on purpose: resuming
    # one run shouldn't silently un-pause a global production hold.
    _pc.resume(char_id)
    if _pc.is_paused(_pc.SCOPE_PRODUCTION):
        return {
            'char_id': char_id,
            'ok': False,
            'error': 'production is globally paused — resume production first',
        }, 409

    resume_stage = job.get('paused_at_stage') or job.get('stage') or 'sheet_generate'
    job['resume'] = True
    job['resume_from'] = resume_stage
    job['status'] = 'running'
    job['stage'] = resume_stage
    _paused_reason = job.get('paused_reason')
    job.pop('paused_reason', None)
    job['resumed_ts'] = _ams_iso()
    # The runtime clock excludes the span this resume ends — record it so the
    # gap between wall clock and runtime is always accounted for.
    try:
        from zyg_workflows.pipeline_runtime import pause_log_line, record_pause

        _pause = record_pause(job, resumed_at=job['resumed_ts'], reason=str(_paused_reason or 'pipeline paused'))
    except Exception:
        _pause = None
    _contact_sheet_save_state(char_id)
    if _pause:
        _contact_sheet_emit(char_id, pause_log_line(job, _pause), level='WARN', stage='Runtime')
    _contact_sheet_emit(char_id, f'Resuming pipeline from stage "{resume_stage}"')
    t = threading.Thread(
        target=_bg_contact_sheet_pipeline,
        args=(char_id,),
        daemon=True,
        name=f'contact-sheet-{char_id[:8]}',
    )
    t.start()
    return {
        'char_id': char_id,
        'ok': True,
        'status': 'running',
        'resumed_from': resume_stage,
    }, 200
