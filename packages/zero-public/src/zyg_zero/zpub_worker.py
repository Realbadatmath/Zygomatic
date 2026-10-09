# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

# Generated 2026-07-17 by the GUI modularization (split out of zero_public_server.py).
# Source line refs: crews_modularization_backups_20260717/originals/zero_public_server.py

import os
import time
from zyg_zero.zpub_config import _ams_iso
from zyg_zero.zpub_main_api import (
    _classify_prompt,
    _get_pipeline_status,
    _parse_model_family,
    _parse_pipeline_options,
    _start_pipeline,
)
from zyg_zero.zpub_store import (
    _HALT_KEY,
    _QUEUE_KEY,
    _get_redis,
    _load_job,
    _mem_lock,
    _mem_queue,
    _queue_length,
    _save_job,
    _set_running,
    _zpub_log,
)
import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)


# ── Worker thread ──────────────────────────────────────────────────────────────


def _worker_loop() -> None:
    """Single background worker — processes one job at a time from the queue."""
    _zyg_log.info('[ZeroPub] Worker started')
    while True:
        job_id = None
        try:
            # Respect pipeline halt — check Redis flag before dequeuing so halted
            # state survives Flask restarts (flag is set by _halt_all_pipeline_activity
            # and cleared by /api/zero/stop/reset).
            r = _get_redis()
            if r:
                try:
                    if r.exists(_HALT_KEY):
                        time.sleep(2)
                        continue
                except Exception as _exc:
                    _zyg_log.debug('suppressed %s: %s', type(_exc).__name__, _exc)
                result = r.blpop(_QUEUE_KEY, timeout=4)
                if result:
                    _, job_id = result
            else:
                with _mem_lock:
                    if _mem_queue:
                        job_id = _mem_queue.pop(0)
                if not job_id:
                    time.sleep(2)

            if not job_id:
                continue

            job = _load_job(job_id)
            if not job:
                _zyg_log.info(f'[ZeroPub] Worker: job {job_id} missing from store — skipping')
                continue

            _zyg_log.info(f'[ZeroPub] Worker: job {job_id[:8]} → "{job["prompt"][:60]}"')
            _set_running(job_id)
            _zpub_log(
                'job_start',
                job_id=job_id,
                ip=job.get('ip', '?'),
                session_id=(job.get('session_id', '')[:8] + '…'),
                prompt_preview=job['prompt'][:120],
                queue_remaining=_queue_length(),
            )

            job['status'] = 'running'
            job['started_at'] = _ams_iso()
            job['current_stage'] = 'Connecting to Agent Zero…'
            _save_job(job)

            # Classify (skip if style explicitly set to video, intro, or storyteller)
            job_style = job.get('pipeline_style', 'documentary')
            if job_style == 'video':
                pipeline_type = 'video'
            elif job_style == 'intro':
                pipeline_type = 'video'
                # Override settings for intro mode
                job['video_duration_minutes'] = 0.25
                job['narration_enabled'] = False
            elif job_style == 'manga':
                pipeline_type = 'manga'
                job['visual_style'] = 'manga'
            elif job_style == 'creature':
                pipeline_type = 'creature'
            elif job_style == 'storyteller':
                pipeline_type = 'storyteller'
            else:
                pipeline_type = _classify_prompt(job['prompt'])
            job['department'] = pipeline_type
            job['current_stage'] = f'Starting {pipeline_type} pipeline…'
            _save_job(job)

            image_paths = job.get('uploaded_image_paths') or []
            vid_dur_min = job.get('video_duration_minutes', 1)
            narration_en = job.get('narration_enabled', True)
            visual_style = job.get('visual_style', 'cinematic')
            scene_mode = job.get('scene_mode', 'independent')
            ending_text = job.get('ending_text', '')
            storyteller_params = job.get('storyteller_params') or None
            model_family = _parse_model_family(job.get('model_family'))
            pipeline_options = _parse_pipeline_options(job.get('pipeline_options'))
            char_id = (job.get('char_id') or '').strip()
            if job_style == 'documentary' and narration_en:
                pipeline_options['burn_subtitles'] = True

            # Start pipeline (retry up to 3 times if main app is busy)
            pipeline_id = None
            for attempt in range(3):
                pipeline_id = _start_pipeline(
                    pipeline_type,
                    job['prompt'],
                    image_paths=image_paths or None,
                    video_duration_minutes=vid_dur_min,
                    narration_enabled=narration_en,
                    visual_style=visual_style,
                    scene_mode=scene_mode,
                    ending_text=ending_text,
                    storyteller_params=storyteller_params,
                    model_family=model_family,
                    pipeline_options=pipeline_options,
                    char_id=char_id,
                    creature_options=job.get('creature_options'),
                )
                if pipeline_id and not str(pipeline_id).startswith('__rejected__:'):
                    break
                if pipeline_id and str(pipeline_id).startswith('__rejected__:'):
                    break
                if attempt < 2:
                    time.sleep(30)

            if pipeline_id and str(pipeline_id).startswith('__rejected__:'):
                job['status'] = 'failed'
                job['error'] = str(pipeline_id).split(':', 1)[-1]
                job['completed_at'] = _ams_iso()
                _save_job(job)
                _set_running(None)
                _zpub_log('job_failed', job_id=job_id, ip=job.get('ip', '?'), error=job['error'])
                continue

            if not pipeline_id:
                job['status'] = 'failed'
                job['error'] = 'Could not start pipeline — main app may be unavailable or busy.'
                job['completed_at'] = _ams_iso()
                _save_job(job)
                _set_running(None)
                _zpub_log('job_failed', job_id=job_id, ip=job.get('ip', '?'), error=job['error'])
                continue

            job['pipeline_id'] = pipeline_id
            job['current_stage'] = 'Pipeline started — Stage 1…'
            _save_job(job)

            _poll_until_done(job_id, job, pipeline_id)

        except Exception as e:
            import traceback

            _zyg_log.info(f'[ZeroPub] Worker error: {e}\n{traceback.format_exc()}')
            if job_id:
                job = _load_job(job_id) or {}
                job['status'] = 'failed'
                job['error'] = str(e)
                job['completed_at'] = _ams_iso()
                _save_job(job)
                _zpub_log('job_failed', job_id=job_id, ip=job.get('ip', '?'), error=str(e))
            _set_running(None)


def _poll_until_done(job_id: str, job: dict, pipeline_id: str) -> None:
    """Poll the main app until the pipeline completes, updating job state in Redis.

    If the main server becomes unreachable for 5 consecutive polls (25 s) the job
    is immediately marked failed with a 'closed externally' message — prevents the
    UI hanging on "in progress" after a Flask restart or crash.
    """
    po = job.get('pipeline_options') or {}
    try:
        n_sc = max(1, int(po.get('scene_count') or 1))
    except (TypeError, ValueError):
        n_sc = 1
    # Base 75 min + ~45 min per WAN scene beyond the first (short clips finish faster).
    max_polls = max(900, 900 + max(0, n_sc - 1) * 540)
    consecutive_empty = 0
    MAX_EMPTY = 5  # 5 × 5 s = 25 s of silence → assume server is gone

    for _ in range(max_polls):
        time.sleep(5)
        status_data = _get_pipeline_status(pipeline_id)
        if not status_data:
            consecutive_empty += 1
            if consecutive_empty >= MAX_EMPTY:
                job['status'] = 'failed'
                job['error'] = 'Pipeline closed externally — main server unreachable.'
                job['completed_at'] = _ams_iso()
                _save_job(job)
                _set_running(None)
                _zpub_log('job_failed', job_id=job_id, ip=job.get('ip', '?'), error='server unreachable')
                _zyg_log.info(
                    f'[ZeroPub] Job {job_id[:8]} — main server unreachable after {MAX_EMPTY} polls, marking failed'
                )
                return
            continue

        consecutive_empty = 0  # reset on any successful response

        ps = status_data.get('status', 'running')
        job['current_stage'] = status_data.get('current_stage') or job.get('current_stage', 'Processing…')
        job['pipeline_status'] = ps

        if ps == 'awaiting_review':
            # Creature review gate (2026-08-25): the sheet IS the deliverable of
            # this public job; training resumes from the dashboard after approval.
            job['status'] = 'done'
            job['completed_at'] = _ams_iso()
            job['review_pending'] = True
            job['result'] = {
                'sheet_path': status_data.get('sheet_path'),
                'sheet_report': status_data.get('sheet_report'),
                'creature_id': pipeline_id,
                'review_pending': True,
            }
            job['output_dir'] = status_data.get('output_dir', '')
            job['output_files'] = status_data.get('output_files', [])
            job['current_stage'] = 'Sheet ready — awaiting operator review'
            _save_job(job)
            _set_running(None)
            _zpub_log(
                'job_done',
                job_id=job_id,
                ip=job.get('ip', '?'),
                output_files=len(job['output_files']),
                prompt_preview=job.get('prompt', '')[:80],
            )
            _zyg_log.info(f'[ZeroPub] Job {job_id[:8]} sheet ready — awaiting review')
            return

        if ps == 'completed':
            job['status'] = 'done'
            job['completed_at'] = _ams_iso()
            job['result'] = status_data.get('result', '')
            job['output_dir'] = status_data.get('output_dir', '')
            job['output_files'] = status_data.get('output_files', [])
            _save_job(job)
            _set_running(None)
            _zpub_log(
                'job_done',
                job_id=job_id,
                ip=job.get('ip', '?'),
                output_files=len(job['output_files']),
                prompt_preview=job.get('prompt', '')[:80],
            )
            _zyg_log.info(f'[ZeroPub] Job {job_id[:8]} done — {len(job["output_files"])} file(s)')
            # ── Azure cloud hooks (fire-and-forget, budget-guarded, no-op if not configured) ──
            try:
                import sys as _sys

                _az_dir = os.path.dirname(os.path.abspath(__file__))
                if _az_dir not in _sys.path:
                    _sys.path.insert(0, _az_dir)
                from zyg_workflows.azure_integrations import upload_to_blob, publish_job_done_event

                _file_paths = [f.get('path', '') for f in job['output_files'] if isinstance(f, dict)]
                upload_to_blob(job_id, _file_paths)
                publish_job_done_event(job_id, job.get('prompt', ''), job['output_files'])
            except Exception as _az_err:
                _zyg_log.info(f'[ZeroPub] Azure hook error (non-fatal): {_az_err}')
            return

        if ps == 'failed':
            job['status'] = 'failed'
            job['error'] = status_data.get('error', 'Pipeline failed')
            job['completed_at'] = _ams_iso()
            _save_job(job)
            _set_running(None)
            _zpub_log('job_failed', job_id=job_id, ip=job.get('ip', '?'), error=job['error'])
            _zyg_log.info(f'[ZeroPub] Job {job_id[:8]} failed — {job["error"]}')
            return

        if ps == 'stopped':
            job['status'] = 'failed'
            job['error'] = status_data.get('error', 'Stopped by user')
            job['completed_at'] = _ams_iso()
            _save_job(job)
            _set_running(None)
            _zpub_log('job_failed', job_id=job_id, ip=job.get('ip', '?'), error='stopped by user')
            _zyg_log.info(f'[ZeroPub] Job {job_id[:8]} stopped by user')
            return

        if ps == 'interrupted':
            job['status'] = 'failed'
            job['error'] = status_data.get('error', 'Pipeline interrupted — server restarted')
            job['completed_at'] = _ams_iso()
            _save_job(job)
            _set_running(None)
            _zpub_log('job_failed', job_id=job_id, ip=job.get('ip', '?'), error=job['error'])
            _zyg_log.info(f'[ZeroPub] Job {job_id[:8]} interrupted (main app restarted)')
            return

        _save_job(job)

    # Timed out — reconcile once in case pipeline finished after poll budget
    status_data = _get_pipeline_status(pipeline_id)
    if status_data and status_data.get('status') == 'completed':
        job['status'] = 'done'
        job['completed_at'] = _ams_iso()
        job['result'] = status_data.get('result', '')
        job['output_dir'] = status_data.get('output_dir', '')
        job['output_files'] = status_data.get('output_files', [])
        job['error'] = None
        _save_job(job)
        _set_running(None)
        _zpub_log(
            'job_done',
            job_id=job_id,
            ip=job.get('ip', '?'),
            output_files=len(job['output_files']),
            prompt_preview=job.get('prompt', '')[:80],
        )
        _zyg_log.info(f'[ZeroPub] Job {job_id[:8]} reconciled after timeout — output ready')
        return

    job['status'] = 'failed'
    _limit_min = int(max_polls * 5 / 60)
    job['error'] = f'Timed out waiting for pipeline to complete ({_limit_min} min limit).'
    job['completed_at'] = _ams_iso()
    _save_job(job)
    _set_running(None)
    _zpub_log('job_failed', job_id=job_id, ip=job.get('ip', '?'), error='timeout')
