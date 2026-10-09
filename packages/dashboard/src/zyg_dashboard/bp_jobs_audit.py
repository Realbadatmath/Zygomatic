# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

# Generated 2026-07-17 by the GUI modularization — extracted from crewai_web_gui.py.
# Source lines: see crews_modularization_backups_20260717/MODULARIZATION_CHANGELOG.md
# Contract: this module is imported at the BOTTOM of crewai_web_gui.py, after all
# of main's globals exist; `from crewai_web_gui import X` is therefore safe here.
import logging as _zyg_logging
import json
import os
from flask import Blueprint, jsonify, request, session

bp = Blueprint('jobs_audit', __name__)

from zyg_dashboard.crewai_web_gui import (  # noqa: E402  (late import by design, see contract above)
    app,
    limiter,
)
from zyg_dashboard.gui.runtime_state import _runtime_path, _workflow_jobs  # noqa: E402
from zyg_dashboard.gui.telemetry import (  # noqa: E402
    API_ADAPTER_AVAILABLE,
    create_approval,
    get_schedule_pause_state,
    set_schedule_pause,
)
from zyg_dashboard.gui.timeutil import _parse_iso_to_ams  # noqa: E402
from zyg_dashboard.gui.zero_store import ZERO_AUDIT_PATH  # noqa: E402

_zyg_log = _zyg_logging.getLogger(__name__)


# P-03 (2026-08-25): every "recent runs" listing here sorted the state files
# by FILENAME reversed — 'g' sorts above every hex digit, so the gatecheck-*
# states sat permanently on top — and nothing filtered smoke/gatecheck ids.
# Both now come from pipeline_common (imported lazily: it loads two lines
# after this blueprint at the bottom of crewai_web_gui.py).
def _recent_state_files(pattern, limit=0):
    from zyg_workflows.pipeline_common import recent_state_files

    return recent_state_files(pattern, limit=limit)


def _is_test_pid(pid) -> bool:
    from zyg_workflows.pipeline_common import is_test_pipeline_id

    return is_test_pipeline_id(pid)


@bp.route('/api/approvals/queue')
def api_approvals_queue():
    """GET approval queue — local stub: shows recent pipeline runs as reviewable items.
    No control plane needed; approving a failed job re-queues it."""

    items = []
    seen_ids = set()

    # Live jobs — show failed ones as needing attention
    for pid, job in list(_workflow_jobs.items()):
        seen_ids.add(pid)
        if _is_test_pid(pid):
            continue
        status = job.get('status', 'running')
        if status not in ('failed', 'completed', 'running'):
            continue
        topic = job.get('scholarly_topic') or job.get('directive', '')[:60]
        items.append(
            {
                'id': pid,
                'schedule_request_id': pid,
                'department': job.get('department', 'unknown'),
                'status': 'pending_review' if status == 'failed' else status,
                'created_at': job.get('started', ''),
                'approved_at': job.get('completed_at', '') if status == 'completed' else '',
                'approved_by': 'auto' if status == 'completed' else '',
                'payload': {
                    'topic': topic,
                    'pipeline_status': status,
                    'error': str(job.get('error', ''))[:120] if job.get('error') else '',
                },
            }
        )

    # Recent state files — most recent 30 (by mtime, test runs excluded)
    for sf in _recent_state_files(_runtime_path('pipeline_*_state.json'), 30):
        try:
            with open(sf, 'r', encoding='utf-8') as _f:
                st = json.load(_f)
            pid = st.get('pipeline_id', '')
            if not pid or pid in seen_ids:
                continue
            seen_ids.add(pid)
            _status = 'failed' if st.get('error') else ('completed' if st.get('ended') else 'unknown')
            topic = st.get('scholarly_topic') or st.get('essay_title') or ''
            items.append(
                {
                    'id': pid,
                    'schedule_request_id': pid,
                    'department': st.get('department', 'unknown'),
                    'status': 'pending_review' if _status == 'failed' else _status,
                    'created_at': st.get('started', ''),
                    'approved_at': st.get('ended', '') if _status == 'completed' else '',
                    'approved_by': 'auto' if _status == 'completed' else '',
                    'payload': {
                        'topic': topic,
                        'pipeline_status': _status,
                        'error': str(st.get('error', ''))[:120] if st.get('error') else '',
                    },
                }
            )
        except Exception as _exc:
            _zyg_log.debug('skipping pipeline state that could not be summarised: %s', _exc)

    return jsonify({'items': items})


@bp.route('/api/approvals', methods=['POST'])
@limiter.limit('30/hour')
def api_approvals_create():
    """POST create approval. Admin only; cannot approve own submission."""
    if not API_ADAPTER_AVAILABLE:
        return jsonify({'success': False, 'error': 'Control plane not configured'}), 503
    token = session.get('api_token')
    body = request.get_json() or {}
    req_id = body.get('schedule_request_id')
    if not req_id:
        return jsonify({'success': False, 'error': 'schedule_request_id required'}), 400
    data = create_approval(schedule_request_id=req_id, policy_snapshot=body.get('policy_snapshot'), token=token)
    if data.get('error'):
        st = data.get('status', 403)
        return jsonify({'success': False, 'error': data.get('error')}), st
    return jsonify(data)


@bp.route('/api/audit')
def api_audit():
    """GET audit log — reads from local zero_audit.jsonl + pipeline start/stop events."""

    limit = request.args.get('limit', 100, type=int)
    offset = request.args.get('offset', 0, type=int)
    actor_f = (request.args.get('actor', '') or '').strip().lower()
    action_f = (request.args.get('action', '') or '').strip().lower()
    obj_f = (request.args.get('object_type', '') or '').strip().lower()

    entries = []

    # ── Source 1: zero_audit.jsonl ─────────────────────────────────────────
    if os.path.isfile(ZERO_AUDIT_PATH):
        try:
            with open(ZERO_AUDIT_PATH, 'r', encoding='utf-8') as _f:
                for line in _f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        e = json.loads(line)
                        entries.append(
                            {
                                'id': e.get('timestamp', '')[:19].replace(':', '').replace('-', ''),
                                'timestamp': e.get('timestamp', ''),
                                'actor': e.get('actor', 'Agent Zero'),
                                'action': e.get('action', ''),
                                'object_type': 'pipeline',
                                'object_id': e.get('payload', {}).get('job_id')
                                or e.get('payload', {}).get('pipeline_id', ''),
                                'changes': e.get('payload', {}),
                                'ip': '127.0.0.1',
                            }
                        )
                    except Exception as _exc:
                        _zyg_log.debug('skipping audit row that could not be mapped: %s', _exc)
        except Exception as _exc:
            _zyg_log.warning('zero audit source unreadable, the audit list is missing its entries: %s', _exc)

    # ── Source 2: pipeline state files — start / end events ───────────────
    for sf in _recent_state_files(_runtime_path('pipeline_*_state.json'), 100):
        try:
            with open(sf, 'r', encoding='utf-8') as _f:
                st = json.load(_f)
            pid = st.get('pipeline_id', '')
            dept = st.get('department', 'unknown')
            topic = st.get('scholarly_topic') or st.get('essay_title') or ''
            if st.get('started'):
                entries.append(
                    {
                        'id': f'start-{pid[:8]}',
                        'timestamp': st['started'],
                        'actor': 'Flask pipeline',
                        'action': 'pipeline_start',
                        'object_type': 'pipeline',
                        'object_id': pid,
                        'changes': {'department': dept, 'topic': topic},
                        'ip': '127.0.0.1',
                    }
                )
            if st.get('ended'):
                _act = 'pipeline_failed' if st.get('error') else 'pipeline_completed'
                entries.append(
                    {
                        'id': f'end-{pid[:8]}',
                        'timestamp': st['ended'],
                        'actor': 'Flask pipeline',
                        'action': _act,
                        'object_type': 'pipeline',
                        'object_id': pid,
                        'changes': {'error': str(st.get('error', ''))[:120]} if st.get('error') else {'topic': topic},
                        'ip': '127.0.0.1',
                    }
                )
        except Exception as _exc:
            _zyg_log.debug('skipping pipeline state that could not be turned into events: %s', _exc)

    # ── Filter + sort ──────────────────────────────────────────────────────
    entries.sort(key=lambda x: x.get('timestamp', ''), reverse=True)
    if actor_f:
        entries = [e for e in entries if actor_f in (e.get('actor') or '').lower()]
    if action_f:
        entries = [e for e in entries if action_f in (e.get('action') or '').lower()]
    if obj_f:
        entries = [e for e in entries if obj_f in (e.get('object_type') or '').lower()]

    total = len(entries)
    return jsonify({'items': entries[offset : offset + limit], 'total': total, 'limit': limit, 'offset': offset})


@bp.route('/api/jobs/specs')
def api_jobs_specs():
    """Return pipeline specs from _workflow_jobs + persisted state files."""
    import socket as _sock

    specs = []
    seen_ids = set()
    _hostname = _sock.gethostname()[:16]

    def _rich_desc(d: dict) -> str:
        topic = d.get('scholarly_topic') or d.get('essay_title') or d.get('directive', '')[:60]
        dept = d.get('department', 'unknown')
        if topic and topic not in ('general', 'unknown', ''):
            return f'{dept.capitalize()} — {topic[:80]}'
        return dept.capitalize()

    for pid, job in list(_workflow_jobs.items()):
        seen_ids.add(pid)
        if _is_test_pid(pid):
            continue
        specs.append(
            {
                'id': pid,
                'schedule_request_id': pid,
                'department': job.get('department', 'unknown'),
                'started': job.get('started', ''),
                'status': job.get('status', 'running'),
                'job_description': _rich_desc(job),
                'worker_id': f'{_hostname}-flask-{os.getpid()}',
            }
        )

    for sf in _recent_state_files(_runtime_path('pipeline_*_state.json'), 200):
        try:
            with open(sf, 'r', encoding='utf-8') as _f:
                st = json.load(_f)
            pid = st.get('pipeline_id', '')
            if not pid or pid in seen_ids:
                continue
            seen_ids.add(pid)
            specs.append(
                {
                    'id': pid,
                    'schedule_request_id': pid,
                    'department': st.get('department', 'unknown'),
                    'started': st.get('started', ''),
                    'status': 'failed' if st.get('error') else ('completed' if st.get('ended') else 'unknown'),
                    'job_description': _rich_desc(st),
                    'worker_id': f'{_hostname}-flask',
                }
            )
        except Exception as _exc:
            _zyg_log.debug('skipping pipeline state that could not be turned into a job spec: %s', _exc)

    return jsonify({'items': specs})


@bp.route('/api/jobs/runs')
def api_jobs_runs():
    """Return pipeline runs from _workflow_jobs + persisted state files.
    Maps each pipeline to the job-run schema expected by the Job Lifecycle tab JS."""
    import socket as _sock
    from datetime import timedelta as _td

    status_filter = request.args.get('status_filter', '').strip() or None
    runs = []
    seen_ids = set()
    _hostname = _sock.gethostname()[:16]
    _flask_worker = f'{_hostname}-flask-{os.getpid()}'

    def _lease_ts(started_at: str, completed_at: str = '', status: str = 'running') -> str:
        """Compute lease_expires_at: running jobs = start + 3h, done/failed = completed_at."""
        if completed_at:
            return completed_at[:19]
        if started_at:
            try:
                _s = _parse_iso_to_ams(started_at)
                if _s is not None:
                    return (_s + _td(hours=3)).isoformat()[:19]
            except Exception as _exc:
                _zyg_log.debug('lease start timestamp unparseable, leaving lease_expires_at empty: %s', _exc)
        return ''

    for pid, job in list(_workflow_jobs.items()):
        seen_ids.add(pid)
        if _is_test_pid(pid):
            continue
        status = job.get('status', 'running')
        started = job.get('started', '')
        completed = job.get('completed_at', '')
        # Fall back to state file's 'ended' if in-memory completed_at is empty
        if not completed and status in ('completed', 'failed'):
            _sf = _runtime_path(f'pipeline_{pid}_state.json')
            if os.path.isfile(_sf):
                try:
                    with open(_sf, 'r', encoding='utf-8') as _f2:
                        _st2 = json.load(_f2)
                    completed = _st2.get('ended', '') or _st2.get('completed_at', '')
                except (OSError, ValueError) as _exc:
                    _zyg_log.debug('state file fallback for completed_at failed: %s', _exc)
        run = {
            'id': pid,
            'job_spec_id': pid,
            'status': status,
            'worker_id': _flask_worker,
            'lease_expires_at': _lease_ts(started, completed, status),
            'started_at': started,
            'completed_at': completed,
            'error_message': str(job.get('error', ''))[:200] if job.get('error') else '',
        }
        if not status_filter or status_filter == status:
            runs.append(run)

    for sf in _recent_state_files(_runtime_path('pipeline_*_state.json'), 200):
        try:
            with open(sf, 'r', encoding='utf-8') as _f:
                st = json.load(_f)
            pid = st.get('pipeline_id', '')
            if not pid or pid in seen_ids:
                continue
            seen_ids.add(pid)
            _status = 'failed' if st.get('error') else ('completed' if st.get('ended') else 'unknown')
            started = st.get('started', '')
            completed = st.get('ended', '')
            run = {
                'id': pid,
                'job_spec_id': pid,
                'status': _status,
                'worker_id': f'{_hostname}-flask',
                'lease_expires_at': _lease_ts(started, completed, _status),
                'started_at': started,
                'completed_at': completed,
                'error_message': str(st.get('error', ''))[:200] if st.get('error') else '',
            }
            if not status_filter or status_filter == _status:
                runs.append(run)
        except Exception as _exc:
            _zyg_log.debug('skipping pipeline state that could not be turned into a run: %s', _exc)

    return jsonify({'items': runs})


@bp.route('/api/jobs/events')
def api_jobs_events():
    """GET event timeline for a pipeline run — reads local state files + zero_audit.jsonl."""

    entity_id = (request.args.get('entity_id', '') or '').strip()
    event_type = (request.args.get('event_type', '') or '').strip().lower()
    limit = min(int(request.args.get('limit', 200) or 200), 2000)

    events = []

    # ── 1. pipeline state file ─────────────────────────────────────────────
    _sf_path = _runtime_path(f'pipeline_{entity_id}_state.json') if entity_id else None
    if _sf_path and os.path.isfile(_sf_path):
        try:
            with open(_sf_path, 'r', encoding='utf-8') as _f:
                st = json.load(_f)
            dept = st.get('department', 'unknown')
            topic = st.get('scholarly_topic') or st.get('essay_title') or st.get('topic', '')
            stage = st.get('stage', '')
            error = st.get('error', '')
            if st.get('started'):
                events.append(
                    {
                        'timestamp': st['started'],
                        'event_type': 'pipeline_start',
                        'actor': 'Flask',
                        'entity_type': 'pipeline',
                        'entity_id': entity_id,
                        'payload': {'department': dept, 'topic': topic},
                    }
                )
            if stage:
                events.append(
                    {
                        'timestamp': st.get('stage_started') or st.get('started', ''),
                        'event_type': 'stage_update',
                        'actor': 'Flask',
                        'entity_type': 'pipeline',
                        'entity_id': entity_id,
                        'payload': {'current_stage': stage},
                    }
                )
            if error:
                events.append(
                    {
                        'timestamp': st.get('ended') or st.get('started', ''),
                        'event_type': 'pipeline_failed',
                        'actor': 'Flask',
                        'entity_type': 'pipeline',
                        'entity_id': entity_id,
                        'payload': {'error': str(error)[:300]},
                    }
                )
            elif st.get('ended'):
                events.append(
                    {
                        'timestamp': st['ended'],
                        'event_type': 'pipeline_completed',
                        'actor': 'Flask',
                        'entity_type': 'pipeline',
                        'entity_id': entity_id,
                        'payload': {'department': dept, 'topic': topic},
                    }
                )
        except Exception as _exc:
            _zyg_log.debug('skipping pipeline state that could not be turned into timeline events: %s', _exc)

    # ── 2. in-memory job (running/just finished) ───────────────────────────
    if entity_id and entity_id in _workflow_jobs:
        job = _workflow_jobs[entity_id]
        _jst = job.get('started', '')
        _jend = job.get('completed_at', '') or job.get('ended', '')
        _jerr = str(job.get('error', ''))[:300] if job.get('error') else ''
        _jstage = job.get('stage', '')
        if _jst:
            events.append(
                {
                    'timestamp': _jst,
                    'event_type': 'pipeline_start',
                    'actor': 'Flask',
                    'entity_type': 'pipeline',
                    'entity_id': entity_id,
                    'payload': {'status': job.get('status', 'running')},
                }
            )
        if _jstage:
            events.append(
                {
                    'timestamp': _jst,
                    'event_type': 'stage_update',
                    'actor': 'Flask',
                    'entity_type': 'pipeline',
                    'entity_id': entity_id,
                    'payload': {'current_stage': _jstage},
                }
            )
        if _jerr:
            events.append(
                {
                    'timestamp': _jend or _jst,
                    'event_type': 'pipeline_failed',
                    'actor': 'Flask',
                    'entity_type': 'pipeline',
                    'entity_id': entity_id,
                    'payload': {'error': _jerr},
                }
            )
        elif _jend:
            events.append(
                {
                    'timestamp': _jend,
                    'event_type': 'pipeline_completed',
                    'actor': 'Flask',
                    'entity_type': 'pipeline',
                    'entity_id': entity_id,
                    'payload': {},
                }
            )

    # ── 3. zero_audit.jsonl ────────────────────────────────────────────────
    if os.path.isfile(ZERO_AUDIT_PATH):
        try:
            with open(ZERO_AUDIT_PATH, 'r', encoding='utf-8') as _f:
                for line in _f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        e = json.loads(line)
                        py = e.get('payload', {})
                        _pid = py.get('job_id') or py.get('pipeline_id', '') or ''
                        if entity_id and entity_id not in _pid:
                            continue
                        events.append(
                            {
                                'timestamp': e.get('timestamp', ''),
                                'event_type': e.get('action', 'audit'),
                                'actor': e.get('actor', 'Agent Zero'),
                                'entity_type': 'pipeline',
                                'entity_id': _pid or entity_id,
                                'payload': py,
                            }
                        )
                    except Exception as _exc:
                        _zyg_log.debug('skipping audit row that could not be turned into an event: %s', _exc)
        except Exception as _exc:
            _zyg_log.warning('zero audit source unreadable, the timeline is missing its entries: %s', _exc)

    # ── 4. error log buffers ───────────────────────────────────────────────
    _err_buffers = getattr(app, '_error_log_buffers', {})
    if not _err_buffers:
        try:
            from zyg_dashboard import crewai_web_gui as _m

            _err_buffers = getattr(_m, '_error_log_buffers', {}) or {}
        except ImportError as _exc:
            _zyg_log.debug('error log buffers unavailable: %s', _exc)
    # Walk global scope for the error log dict
    _all_err_lists = []
    for _bname in [
        '_ai_model_fail_log',
        '_gpu_oom_log',
        '_timeout_log',
        '_api_error_log',
        '_high_risk_log',
        '_medium_risk_log',
        '_low_risk_log',
    ]:
        _bl = globals().get(_bname, [])
        if isinstance(_bl, list):
            _all_err_lists.extend(_bl)
    for _entry in _all_err_lists:
        if not isinstance(_entry, dict):
            continue
        _pid = _entry.get('pipeline_id', '')
        if entity_id and entity_id not in _pid:
            continue
        events.append(
            {
                'timestamp': _entry.get('ts', ''),
                'event_type': 'error',
                'actor': 'pipeline',
                'entity_type': 'pipeline',
                'entity_id': _pid or entity_id,
                'payload': {
                    'level': _entry.get('level', ''),
                    'stage': _entry.get('stage', ''),
                    'message': _entry.get('msg', ''),
                },
            }
        )

    # ── sort + filter + limit ──────────────────────────────────────────────
    events.sort(key=lambda x: x.get('timestamp', ''), reverse=False)
    if event_type:
        events = [e for e in events if event_type in (e.get('event_type') or '').lower()]
    seen = set()
    uniq = []
    for e in events:
        _k = (e.get('timestamp', ''), e.get('event_type', ''), str(e.get('payload', {}))[:40])
        if _k not in seen:
            seen.add(_k)
            uniq.append(e)

    return jsonify({'items': uniq[:limit], 'total': len(uniq)})


@bp.route('/api/jobs/runs/expire-leases', methods=['POST'])
@limiter.limit('30/hour')
def api_jobs_expire_leases():
    """No-op for local pipelines (no lease concept). Returns ok so JS can proceed."""
    return jsonify({'ok': True, 'expired': 0})


@bp.route('/api/admin/schedule-pause', methods=['GET'])
def api_schedule_pause_get():
    """GET schedule pause state (circuit breaker). Admin only. Always returns 200 so Integrity Gate tab loads; 4xx/5xx from control plane become fallback."""
    if not API_ADAPTER_AVAILABLE:
        return jsonify({'paused': False, 'reason': '', 'error': 'Control plane not configured'})
    try:
        token = session.get('api_token')
        data = get_schedule_pause_state(token=token)
        if data.get('error'):
            # Always return 200 with fallback so Integrity Gate tab can render (never propagate 4xx/5xx)
            return jsonify({'paused': False, 'reason': '', 'error': data.get('error')})
        return jsonify(
            {
                'paused': data.get('paused', False),
                'reason': data.get('reason', ''),
                'updated_at': data.get('updated_at'),
                'updated_by': data.get('updated_by'),
            }
        )
    except Exception as e:
        return jsonify({'paused': False, 'reason': '', 'error': str(e)})


@bp.route('/api/admin/schedule-pause', methods=['POST'])
@limiter.limit('10/hour')
def api_schedule_pause_post():
    """POST pause or resume schedule. Admin only."""
    if not API_ADAPTER_AVAILABLE:
        return jsonify({'success': False, 'error': 'Control plane not configured'}), 503
    token = session.get('api_token')
    body = request.get_json() or {}
    data = set_schedule_pause(paused=body.get('paused', False), reason=body.get('reason', ''), token=token)
    if data.get('error'):
        return jsonify({'success': False, 'error': data.get('error')}), data.get('status', 403)
    return jsonify(data)
