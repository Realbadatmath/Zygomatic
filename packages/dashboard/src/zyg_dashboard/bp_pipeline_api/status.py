# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

# Moved verbatim out of bp_pipeline_api.py (lines 734-1044) when that 1,782-line module
# became this package. Zero logic edits: the bodies below are byte-for-byte the original.

import logging as _zyg_logging
import json
import os
from flask import (
    jsonify,
    request,
    send_from_directory,
)
from zyg_dashboard.cors import apply_cors

from zyg_workflows.char_state_service import (
    _creature_state_path,
)
from zyg_workflows.pipeline_common import (
    _pipeline_current_stage_from_job,
    _resolve_pipeline_public_status,
)
from zyg_workflows.pipeline_runtime import compute_runtime as _compute_runtime
from zyg_workflows.pipeline_runtime import format_runtime as _fmt_runtime

from zyg_dashboard.crewai_web_gui import (  # noqa: E402  late: crewai_web_gui imports this blueprint at its bottom, so `bp` must exist first
    _CLIPFARM_STAGES,
    limiter,
)
from zyg_dashboard.gui.runtime_state import (  # noqa: E402
    _creature_gen_jobs,
    _runtime_path,
    _workflow_jobs,
)


from zyg_dashboard.bp_pipeline_api import bp  # the Blueprint the package __init__ creates
from zyg_dashboard.bp_pipeline_api.creature import _seal_gate_outputs

_zyg_log = _zyg_logging.getLogger('zyg_dashboard.bp_pipeline_api')


@limiter.exempt
@bp.route('/api/internal/pipeline/status/<pipeline_id>')
def api_internal_pipeline_status(pipeline_id):
    """Return status of a pipeline for the zero_public_server."""
    job = _creature_gen_jobs.get(pipeline_id)
    if job:
        from zyg_workflows.char_state_service import (
            _creature_mark_stale as _cr_stale,
            _creature_save_state as _cr_save_st,
            _creature_refresh_external as _cr_fresh,
        )

        job = _cr_fresh(job)
        if _cr_stale(job):
            _cr_save_st(pipeline_id)
        result = job.get('result') or {}
        output_files = []
        lora_path = result.get('lora_path') or job.get('lora_path')
        if lora_path and os.path.isfile(lora_path):
            try:
                output_files.append(
                    {
                        'name': os.path.basename(lora_path),
                        'size_mb': round(os.path.getsize(lora_path) / 1024 / 1024, 1),
                        'kind': 'lora',
                    }
                )
            except OSError as _exc:
                _zyg_log.warning('sizing the LoRA file failed, omitted from the output listing: %s', _exc)
        for prev in result.get('preview_images') or job.get('preview_images') or []:
            if prev and os.path.isfile(prev):
                try:
                    output_files.append(
                        {
                            'name': os.path.basename(prev),
                            'size_mb': round(os.path.getsize(prev) / 1024 / 1024, 1),
                            'kind': 'sheet' if os.path.basename(prev) == 'sheet.png' else 'preview',
                            'path': prev,
                        }
                    )
                except OSError as _exc:
                    _zyg_log.warning('sizing preview %s failed, omitted from the output listing: %s', prev, _exc)
        _sheet_p = job.get('sheet_path') or ''
        if _sheet_p and os.path.isfile(_sheet_p) and not any(f.get('kind') == 'sheet' for f in output_files):
            try:
                output_files.append(
                    {
                        'name': 'sheet.png',
                        'kind': 'sheet',
                        'path': _sheet_p,
                        'size_mb': round(os.path.getsize(_sheet_p) / 1024 / 1024, 1),
                    }
                )
            except OSError as _exc:
                _zyg_log.warning('sizing the contact sheet failed, omitted from the output listing: %s', _exc)
        return jsonify(
            {
                'pipeline_id': pipeline_id,
                'status': job.get('status', 'unknown'),
                'department': 'creature',
                'current_stage': job.get('current_stage') or '',
                'started': job.get('started', ''),
                'ended': job.get('ended', ''),
                'result': result,
                'error': job.get('error', ''),
                'output_dir': job.get('dataset_dir', ''),
                'output_files': output_files,
                'trigger_token': result.get('trigger_token') or job.get('trigger_token'),
                'lora_path': lora_path,
                'sheet_path': job.get('sheet_path'),
                'sheet_report': job.get('sheet_report'),
                'preview_report': job.get('preview_report'),
                'review_pending': job.get('status') == 'awaiting_review',
                'creature_options': job.get('creature_options'),
                'train_family': job.get('train_family'),
            }
        )

    job = _workflow_jobs.get(pipeline_id)
    if not job:
        # Check for persisted state
        state_file = _runtime_path(f'pipeline_{pipeline_id}_state.json')
        if os.path.exists(state_file):
            try:
                with open(state_file) as _sf:
                    saved = json.load(_sf)
                    job = saved
            except (OSError, ValueError) as _exc:
                _zyg_log.warning(
                    'persisted state %s unreadable, reporting the pipeline as not found: %s', state_file, _exc
                )
    if not job:
        try:
            with open(_creature_state_path(pipeline_id), encoding='utf-8') as _cfh:
                job = json.load(_cfh)
                _creature_gen_jobs[pipeline_id] = job
        except Exception:
            job = None
    if job and job.get('creature_id'):
        from zyg_workflows.char_state_service import (
            _creature_mark_stale as _cr_stale2,
            _creature_save_state as _cr_save_st2,
        )

        if _cr_stale2(job):
            _cr_save_st2(pipeline_id)
        result = job.get('result') or {}
        lora_path = result.get('lora_path') or job.get('lora_path')
        return jsonify(
            {
                'pipeline_id': pipeline_id,
                'status': job.get('status', 'unknown'),
                'department': 'creature',
                'current_stage': job.get('current_stage') or '',
                'started': job.get('started', ''),
                'ended': job.get('ended', ''),
                'result': result,
                'error': job.get('error', ''),
                'output_dir': job.get('dataset_dir', ''),
                'output_files': [],
                'trigger_token': result.get('trigger_token') or job.get('trigger_token'),
                'lora_path': lora_path,
                'sheet_path': job.get('sheet_path'),
                'sheet_report': job.get('sheet_report'),
                'preview_report': job.get('preview_report'),
                'review_pending': job.get('status') == 'awaiting_review',
                'creature_options': job.get('creature_options'),
                'train_family': job.get('train_family'),
            }
        )
    if not job:
        return jsonify({'error': 'not found'}), 404

    _pub_status = _resolve_pipeline_public_status(job)
    _err = (job.get('error') or '').strip()
    if _pub_status == 'interrupted':
        _err = _err or 'Pipeline interrupted — server restarted (no live worker)'
    elif _pub_status == 'failed' and not _err:
        _err = 'Pipeline failed'

    output_dir = job.get('output_dir', '')
    output_files = []
    if output_dir and os.path.isdir(output_dir):
        # If the pipeline set an explicit final output file, only expose that one.
        final_file = job.get('final_output_file', '')
        if final_file and os.path.isfile(final_file):
            try:
                output_files.append(
                    {
                        'name': os.path.basename(final_file),
                        'size_mb': round(os.path.getsize(final_file) / 1024 / 1024, 1),
                        'path': final_file,
                    }
                )
            except OSError as _exc:
                _zyg_log.warning('sizing the final output file failed, omitted from the output listing: %s', _exc)
        else:
            # Fallback: scan directory but prefer *_final.* files if any exist
            all_media = [
                f for f in sorted(os.listdir(output_dir)) if f.lower().endswith(('.mp4', '.mp3', '.wav', '.webm'))
            ]
            final_only = [f for f in all_media if '_final' in f.lower()]
            for fname in final_only if final_only else all_media:
                fpath = os.path.join(output_dir, fname)
                try:
                    output_files.append(
                        {
                            'name': fname,
                            'size_mb': round(os.path.getsize(fpath) / 1024 / 1024, 1),
                            'path': fpath,
                        }
                    )
                except OSError as _exc:
                    _zyg_log.warning('sizing output file %s failed, omitted from the listing: %s', fpath, _exc)
    output_files, _withheld = _seal_gate_outputs(output_files)
    payload = {
        'pipeline_id': pipeline_id,
        'status': _pub_status,
        'department': job.get('department', ''),
        'current_stage': _pipeline_current_stage_from_job(job),
        'started': job.get('started', ''),
        'ended': job.get('ended', ''),
        'result': job.get('result', ''),
        'error': _err,
        'output_dir': output_dir,
        'output_files': output_files,
    }
    if _withheld is not None:
        payload['unsealed_withheld'] = _withheld
    return jsonify(payload)


@bp.route('/api/internal/pipeline/download/<pipeline_id>/<path:filename>')
def api_internal_pipeline_download(pipeline_id, filename):
    """Serve an output file for the zero_public_server download route."""
    job = _workflow_jobs.get(pipeline_id)
    if not job:
        return jsonify({'error': 'not found'}), 404
    output_dir = job.get('output_dir', '')
    if not output_dir or not os.path.isdir(output_dir):
        return jsonify({'error': 'output directory not found'}), 404
    safe_name = os.path.basename(filename)
    fpath = os.path.join(output_dir, safe_name)
    if not os.path.isfile(fpath):
        return jsonify({'error': 'file not found'}), 404
    return send_from_directory(output_dir, safe_name, as_attachment=True)


@bp.route('/api/workflow_status/<job_id>')
def workflow_status(job_id):
    """Poll the status of a pipeline job. Includes per-stage, per-agent breakdown."""
    job = _workflow_jobs.get(job_id)
    if not job:
        return jsonify({'error': 'Job not found'}), 404
    # Build a summary for the caller
    stages = job.get('stages', {})
    stage_summary = []
    for stage in _CLIPFARM_STAGES:
        s = stages.get(stage['name'], {})
        agents_done = sum(1 for v in s.values() if isinstance(v, dict) and v.get('status') in ('completed', 'skipped'))
        agents_failed = sum(1 for v in s.values() if isinstance(v, dict) and v.get('status') == 'failed')
        stage_summary.append(
            {
                'stage': stage['name'],
                'parallel': stage['parallel'],
                'total_agents': len(stage['agents']),
                'completed': agents_done,
                'failed': agents_failed,
                'details': s,
            }
        )
    return jsonify(
        {
            'pipeline_id': job_id,
            'status': job.get('status'),
            'current_stage': job.get('current_stage'),
            'started': job.get('started'),
            'result': job.get('result'),
            'error': job.get('error'),
            'stages': stage_summary,
        }
    )


@bp.route('/api/workflow_status/active')
@limiter.exempt
def workflow_status_active():
    """Return metadata for the currently running pipeline (if any).

    This endpoint is used by UI pollers (Kanban/chart overlays). We include
    ``model_family`` so the frontend can show the matching Kanban template
    (FLUX vs SDXL) for the active run.
    """
    active_agents = []
    pipeline_running = False
    model_family = ''
    for job in _workflow_jobs.values():
        if job.get('status') != 'running':
            continue
        pipeline_running = True
        if not model_family:
            model_family = job.get('model_family') or 'flux'
        current_stage = job.get('current_stage', '')
        stage_data = job.get('stages', {}).get(current_stage, {})
        for agent_id, info in stage_data.items():
            if isinstance(info, dict) and info.get('status') == 'running':
                active_agents.append(agent_id)
    # Overseer is always active while any pipeline is running
    if pipeline_running:
        active_agents.append('CLIPFARM-Clipfarm-Overseer-Agent')
    resp = jsonify({'active_agents': active_agents, 'pipeline_running': pipeline_running, 'model_family': model_family})
    apply_cors(resp, request)
    return resp


def _rt_report_line(rt):
    """``4h 04m 20s active · 20h 32m 44s wall · 16h 28m 24s across 2 freezes``."""
    if not rt or rt.get('runtime_seconds') is None:
        return '?'
    out = f'{_fmt_runtime(rt["runtime_seconds"])} active'
    wall = rt.get('runtime_wall_seconds')
    if wall is not None and wall - rt['runtime_seconds'] > 60:
        gaps = rt.get('runtime_gaps') or []
        out += (
            f' · {_fmt_runtime(wall)} wall · '
            f'{_fmt_runtime(rt.get("runtime_gap_seconds") or 0)} across '
            f'{len(gaps)} freeze{"" if len(gaps) == 1 else "s"}'
        )
    return out


def _runtime_payload(job, running):
    """Live Tail ⏱ clock fields for a /api/kanban/status pipeline payload.

    The browser used to derive the clock itself from ``started`` and freeze it
    on four hard-coded terminal statuses, so anything else — a creature parked
    at ``awaiting_review``, a job left ``stopped`` by a GUI restart, a run that
    crashed and was resumed hours later — accumulated forever instead of
    reporting a runtime.  ``running`` must be the SAME truth the caller puts in
    ``pipeline.status`` (a live-worker check, not the job dict's own claim).
    See pipeline_runtime.py for the definition of active runtime.
    """
    try:
        return _compute_runtime(job, running=running)
    except Exception:
        return {
            'runtime_seconds': None,
            'runtime_running': bool(running),
            'runtime_as_of': None,
            'runtime_wall_seconds': None,
        }
