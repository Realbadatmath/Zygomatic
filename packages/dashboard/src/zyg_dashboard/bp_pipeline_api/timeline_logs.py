# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

# Moved verbatim out of bp_pipeline_api.py (lines 1350-1782) when that 1,782-line module
# became this package. Zero logic edits: the bodies below are byte-for-byte the original.

import logging as _zyg_logging
import json
import os
from datetime import timedelta
from flask import (
    Response,
    jsonify,
    stream_with_context,
)
from zyg_dashboard import bp_pipeline_api_steps as _steps

from zyg_workflows.pipeline_runtime import format_runtime as _fmt_runtime

from zyg_dashboard.crewai_web_gui import (  # noqa: E402  late: crewai_web_gui imports this blueprint at its bottom, so `bp` must exist first
    _FLUX_LORA_PATH,
    _FLUX_LORA_SCALE,
    limiter,
)
from zyg_dashboard.gui.runtime_state import (  # noqa: E402
    _RUNTIME_DIR,
    _runtime_path,
    _workflow_jobs,
    _workflow_pipeline_worker_alive,
)
from zyg_dashboard.gui.telemetry import _backend_debug  # noqa: E402
from zyg_dashboard.gui.timeutil import _ams_now, _parse_iso_to_ams  # noqa: E402


from zyg_dashboard.bp_pipeline_api import bp  # the Blueprint the package __init__ creates
from zyg_dashboard.bp_pipeline_api.status import _rt_report_line, _runtime_payload

_zyg_log = _zyg_logging.getLogger('zyg_dashboard.bp_pipeline_api')


@bp.route('/api/pipeline/timeline/<pipeline_id>')
@limiter.exempt
def api_pipeline_timeline(pipeline_id):
    """
    Return a structured timeline of all completed and in-progress stages
    for the given pipeline_id.  Used by the Live Tail → Timeline tab.

    Response shape:
    {
      "pipeline_id": "...",
      "department": "scholarly"|"crime"|...,
      "status": "running"|"completed"|"failed",
      "started": "ISO",
      "ended": "ISO"|null,
      "total_elapsed_s": 123.4,
      "current_stage": "Stage 4: TTS Narration",
      "stages": [
        {
          "name": "Stage 1: Topic Setup",
          "status": "completed"|"running"|"pending"|"failed",
          "started_at": "ISO",
          "ended_at": "ISO"|null,
          "elapsed_s": 1.2,
          "extra": { ...stage-specific fields }
        }, ...
      ]
    }
    """
    _backend_debug(f'api_pipeline_timeline: {pipeline_id}')
    job = _workflow_jobs.get(pipeline_id)
    if not job:
        # Try to load from saved state file
        state_file = _runtime_path(f'pipeline_{pipeline_id}_state.json')
        if os.path.exists(state_file):
            try:
                with open(state_file) as _f:
                    saved = json.load(_f)
                # Build synthetic response from saved state. The state file has
                # no ``total_elapsed_s`` key, so this used to be a hard null —
                # compute it from the snapshot's own stage records instead.
                _srt = _runtime_payload(saved, False)
                return jsonify(
                    {
                        'pipeline_id': pipeline_id,
                        'department': saved.get('department', 'unknown'),
                        'status': 'completed',
                        'started': saved.get('started'),
                        'ended': saved.get('ended'),
                        'total_elapsed_s': saved.get('total_elapsed_s') or _srt['runtime_seconds'],
                        'wall_elapsed_s': _srt['runtime_wall_seconds'],
                        'runtime_running': False,
                        'runtime_gap_s': _srt['runtime_gap_seconds'],
                        'runtime_gaps': _srt['runtime_gaps'],
                        'current_stage': None,
                        'stages': saved.get('stage_timeline', []),
                        'debug_events': saved.get('debug_events', []),
                    }
                )
            except Exception as _e:
                _backend_debug(f'api_pipeline_timeline: state load error: {_e}')
        return jsonify({'error': 'Pipeline not found'}), 404

    stage_timeline = job.get('stage_timeline', [])

    # Compute live elapsed for the currently-running stage
    enriched = []
    for entry in stage_timeline:
        e = dict(entry)
        if e.get('status') == 'running' and e.get('started_at'):
            try:
                _started_dt = _parse_iso_to_ams(e['started_at'])
                if _started_dt is not None:
                    elapsed = (_ams_now() - _started_dt).total_seconds()
                    e['elapsed_s'] = round(elapsed, 1)
            except Exception as _exc:
                # Cosmetic: the row simply carries no live elapsed field.
                _zyg_log.debug('live elapsed for stage %s not computable: %s', e.get('name'), _exc)
        enriched.append(e)

    # Total elapsed. NOT ``now - started``: a job without an ``ended`` stamp is
    # not necessarily still running (stopped by a restart, parked at a review
    # gate), and that plain subtraction is what made the Live Tail clock
    # accumulate. pipeline_runtime freezes at the last recorded activity and
    # drops dead gaps; the raw wall span ships alongside it.
    _rt = _runtime_payload(
        job, job.get('status') == 'running' and (not pipeline_id or _workflow_pipeline_worker_alive(pipeline_id))
    )
    total_elapsed = _rt['runtime_seconds']

    return jsonify(
        {
            'pipeline_id': pipeline_id,
            'department': job.get('department', 'unknown'),
            'status': job.get('status', 'running'),
            'started': job.get('started'),
            'ended': job.get('ended'),
            'total_elapsed_s': total_elapsed,
            'wall_elapsed_s': _rt['runtime_wall_seconds'],
            'runtime_running': _rt['runtime_running'],
            'runtime_gap_s': _rt['runtime_gap_seconds'],
            'runtime_gaps': _rt['runtime_gaps'],
            'current_stage': job.get('current_stage'),
            'stages': enriched,
            'debug_events': job.get('debug_events', []),
        }
    )


@bp.route('/api/pipeline/timeline/<pipeline_id>/download')
def api_pipeline_timeline_download(pipeline_id):
    """
    Download the pipeline timeline as a plain-text report.
    The client JS will trigger a browser download → user saves to Desktop.
    """
    _backend_debug(f'api_pipeline_timeline_download: {pipeline_id}')
    job = _workflow_jobs.get(pipeline_id)
    stages = []
    meta = {}

    _rt_meta = {'runtime_gaps': []}
    if job:
        stages = job.get('stage_timeline', [])
        _rt_meta = _runtime_payload(
            job, job.get('status') == 'running' and _workflow_pipeline_worker_alive(pipeline_id)
        )
        meta = {
            'pipeline_id': pipeline_id,
            'department': job.get('department', 'unknown'),
            'status': job.get('status', 'unknown'),
            'started': job.get('started', ''),
            'ended': job.get('ended', ''),
            'topic': job.get('topic', ''),
            'runtime': _rt_report_line(_rt_meta),
        }
    else:
        state_file = _runtime_path(f'pipeline_{pipeline_id}_state.json')
        if os.path.exists(state_file):
            try:
                with open(state_file) as _f:
                    saved = json.load(_f)
                stages = saved.get('stage_timeline', [])
                _rt_meta = _runtime_payload(saved, False)
                meta = {
                    'pipeline_id': pipeline_id,
                    'department': saved.get('department', 'unknown'),
                    'status': 'completed',
                    'started': saved.get('started', ''),
                    'ended': saved.get('ended', ''),
                    'topic': saved.get('scholarly_topic', ''),
                    'runtime': _rt_report_line(_rt_meta),
                }
            except (OSError, ValueError) as _exc:
                _zyg_log.warning('timeline state %s unreadable, reporting no timeline data: %s', state_file, _exc)

    if not stages:
        return jsonify({'error': 'No timeline data'}), 404

    # Build plain-text report
    lines = [
        '═' * 60,
        'ZYGOMATIC PIPELINE TIMELINE REPORT',
        '═' * 60,
        f'Pipeline ID : {meta.get("pipeline_id", pipeline_id)}',
        f'Department  : {meta.get("department", "?")}',
        f'Topic       : {meta.get("topic", "?")}',
        f'Status      : {meta.get("status", "?")}',
        f'Started     : {meta.get("started", "?")}',
        f'Ended       : {meta.get("ended", "?")}',
        f'Runtime     : {meta.get("runtime", "?")}',
        '─' * 60,
        '',
    ]
    # Freezes are itemised, never folded silently into the wall clock.
    if _rt_meta.get('runtime_gaps'):
        lines += ['CLOCK FREEZES (excluded from runtime)', '─' * 60]
        for _g in _rt_meta['runtime_gaps']:
            lines.append(
                f'  {_fmt_runtime(_g["seconds"]):>12}  {_g["from"][11:19]} → {_g["to"][11:19]}  {_g["reason"]}'
            )
        lines += ['']
    lines += [
        'STAGE BREAKDOWN',
        '─' * 60,
    ]

    total_s = 0
    for s in stages:
        elapsed = s.get('elapsed_s')
        elapsed_str = f'{elapsed:.1f}s' if elapsed is not None else 'N/A'
        if elapsed:
            total_s += elapsed
        status_icon = '✓' if s.get('status') == 'completed' else ('✗' if s.get('status') == 'failed' else '⟳')
        lines.append(f'  {status_icon}  {s.get("name", "?"):<45} {elapsed_str:>8}')
        extra = s.get('extra') or {}
        for k, v in extra.items():
            lines.append(f'       {k}: {v}')

    lines += [
        '',
        '─' * 60,
        f'  TOTAL PIPELINE TIME: {total_s:.1f}s ({total_s / 60:.1f} min)',
        '',
        'DEBUG EVENTS',
        '─' * 60,
    ]

    debug_events = job.get('debug_events', []) if job else []
    if debug_events:
        for ev in debug_events[-100:]:  # last 100 debug events
            lines.append(
                f'  [{ev.get("ts", "")}] [{ev.get("level", "?")}] {ev.get("stage", "?")} — {ev.get("msg", "")}'
            )
    else:
        lines.append('  (no debug events recorded)')

    lines += ['', '═' * 60, 'END OF REPORT', '═' * 60]

    txt = '\n'.join(lines)
    from flask import Response

    return Response(
        txt,
        mimetype='text/plain',
        headers={
            'Content-Disposition': f'attachment; filename="zygomatic_timeline_{pipeline_id[:8]}.txt"',
        },
    )


@bp.route('/api/pipeline/murch_debug/<pipeline_id>')
def api_pipeline_murch_debug(pipeline_id):
    """Return murch_engine debug events for the given pipeline (JSON)."""
    _backend_debug(f'api_pipeline_murch_debug: {pipeline_id}')
    job = _workflow_jobs.get(pipeline_id)
    events = []
    if job:
        events = job.get('murch_debug_events', [])
    else:
        state_file = _runtime_path(f'pipeline_{pipeline_id}_state.json')
        if os.path.exists(state_file):
            try:
                with open(state_file) as _f:
                    saved = json.load(_f)
                events = saved.get('murch_debug_events', [])
            except (OSError, ValueError) as _exc:
                _zyg_log.warning('murch debug state %s unreadable, reporting none: %s', state_file, _exc)
    if not events and not job:
        return jsonify({'error': 'Not found'}), 404
    return jsonify(
        {
            'pipeline_id': pipeline_id,
            'count': len(events),
            'events': events,
            'murch_eval': (job or {}).get('murch_eval'),
        }
    )


@bp.route('/api/pipeline/active')
@limiter.exempt
def api_pipeline_active():
    """Return list of all active (running) pipeline IDs across all departments."""
    _backend_debug('api_pipeline_active called')
    active = []
    for pid, job in _workflow_jobs.items():
        if job.get('status') == 'running':
            active.append(
                {
                    'pipeline_id': pid,
                    'department': job.get('department', 'unknown'),
                    'current_stage': job.get('current_stage', ''),
                    'started': job.get('started', ''),
                }
            )
    # Also include recently completed (last 10 minutes)
    cutoff = _ams_now() - timedelta(minutes=10)
    for pid, job in _workflow_jobs.items():
        if job.get('status') in ('completed', 'failed') and job.get('ended'):
            try:
                _ended_dt = _parse_iso_to_ams(job['ended'])
                if _ended_dt is not None and _ended_dt > cutoff:
                    active.append(
                        {
                            'pipeline_id': pid,
                            'department': job.get('department', 'unknown'),
                            'current_stage': job.get('current_stage', ''),
                            'started': job.get('started', ''),
                            'ended': job.get('ended', ''),
                            'status': job.get('status'),
                        }
                    )
            except Exception as _exc:
                # Cosmetic: the job is left out of the recently-completed list.
                _zyg_log.debug('ended stamp of %s not parseable: %s', pid, _exc)
    return jsonify({'pipelines': active})


@bp.route('/api/pipeline/test', methods=['POST'])
def api_pipeline_test():
    """Non-destructive health check for every pipeline component.
    Runs all checks in parallel threads; returns results in ~10s.

    The 31 probes themselves are ``bp_pipeline_api_steps._chk_*``; this route is
    the thread pool, the per-check timing/exception wrapper and the sort order.
    """
    import time as _time
    import concurrent.futures as _cf

    t0 = _time.monotonic()
    checks = []
    lock = __import__('threading').Lock()
    # Guard: if a pipeline job is actively running, skip any check that touches GPU
    # memory directly (torch.cuda.mem_get_info etc.) to avoid VRAM allocation races.
    _gpu_scan_safe = not any(j.get('status') == 'running' for j in _workflow_jobs.values())

    def _check(name, fn):
        ct = _time.monotonic()
        try:
            status, detail = fn()
        except Exception as _e:
            status, detail = 'fail', str(_e)
        elapsed = round((_time.monotonic() - ct) * 1000)
        with lock:
            checks.append({'name': name, 'status': status, 'detail': detail, 'elapsed_ms': elapsed})

    TASKS = _steps.pipeline_test_tasks(
        _gpu_scan_safe,
        _runtime_path,
        _RUNTIME_DIR,
        _FLUX_LORA_PATH,
        _FLUX_LORA_SCALE,
    )

    with _cf.ThreadPoolExecutor(max_workers=8) as ex:
        futs = {ex.submit(_check, name, fn): name for name, fn in TASKS}
        _cf.wait(futs, timeout=30)

    checks.sort(
        key=lambda c: (
            0 if c['status'] == 'fail' else 1 if c['status'] == 'warn' else 2,
            TASKS.index(next((t for t in TASKS if t[0] == c['name']), (c['name'], None))),
        )
    )
    elapsed_ms = round((_time.monotonic() - t0) * 1000)
    return jsonify({'checks': checks, 'elapsed_ms': elapsed_ms})


@bp.route('/api/frontend_log', methods=['POST'])
@limiter.limit('2000/hour')  # Client logs during navigation; higher than default
def frontend_log():
    # No disk write from Flask (optional: re-enable for local debug only).
    return jsonify({'success': True})


@bp.route('/api/live_log')
@limiter.exempt
def live_log():
    """SSE endpoint — streams new agent log entries as they are appended to clipfarm_processing_log.json."""
    import time as _time

    log_path = _runtime_path('clipfarm_processing_log.json')

    def generate():
        last_count = 0
        yield 'data: {"msg":"[Live Tail connected]","level":"SYS"}\n\n'
        while True:
            try:
                if os.path.exists(log_path):
                    with open(log_path) as _lf:
                        try:
                            entries = json.load(_lf)
                        except Exception:
                            entries = []
                    if len(entries) > last_count:
                        for entry in entries[last_count:]:
                            line = json.dumps(
                                {
                                    'msg': f'[{entry.get("stage", "?")}] {entry.get("agent", "?")} — {entry.get("message", "")}',
                                    'level': entry.get('level', 'INFO'),
                                    'ts': entry.get('timestamp', ''),
                                    'pipeline_id': entry.get('pipeline_id', ''),
                                }
                            )
                            yield f'data: {line}\n\n'
                        last_count = len(entries)
            except Exception as _e:
                yield f'data: {{"msg":"[log read error: {str(_e)}]","level":"ERROR"}}\n\n'
            _time.sleep(0.5)

    return Response(
        stream_with_context(generate()),
        mimetype='text/event-stream',
        headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'},
    )


@bp.route('/api/pipeline/flags')
def pipeline_flags():
    """Return deduplicated WARNING and ERROR entries from the last pipeline run."""
    log_path = _runtime_path('clipfarm_processing_log.json')
    try:
        with open(log_path) as _lf:
            entries = json.load(_lf)
    except Exception:
        entries = []
    # Find the most recent pipeline_id
    last_pid = None
    for e in reversed(entries):
        if e.get('pipeline_id'):
            last_pid = e['pipeline_id']
            break
    flags = []
    seen = set()
    for e in entries:
        if e.get('level') not in ('WARNING', 'ERROR'):
            continue
        # Include all flags from current pipeline or recent flags with no pipeline id
        if last_pid and e.get('pipeline_id') and e['pipeline_id'] != last_pid:
            continue
        key = e.get('message', '')[:120]
        if key in seen:
            continue
        seen.add(key)
        flags.append(
            {
                'level': e.get('level'),
                'stage': e.get('stage', '?'),
                'message': e.get('message', ''),
                'ts': e.get('timestamp', ''),
                'pipeline_id': e.get('pipeline_id', ''),
            }
        )
    return jsonify({'flags': flags, 'pipeline_id': last_pid or ''})
