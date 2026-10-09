# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

from zyg_dashboard.bp_integrity_ops.constants import (
    DASHBOARD_AVAILABLE,
    ERROR_LOGS_DATA_PATH,
    LANGUAGES_DIR,
    LANGUAGE_LINKS_FILE,
    _ams_now,
    _is_test_pid,
    _load_json,
    _parse_iso_to_ams,
    _recent_state_files,
    _runtime_path,
    _workflow_jobs,
    bp,
    json,
    jsonify,
    limiter,
    os,
)


import logging as _zyg_logging

# Bound by ASSIGNMENT (not `from .constants import _zyg_log`) so the moved
# `_zyg_log.debug(...)` calls keep compiling to the same method form.
# channel kept from the pre-split module
_zyg_log = _zyg_logging.getLogger('zyg_dashboard.bp_integrity_ops')


@bp.route('/api/dashboard/error_logs')
def dashboard_error_logs():
    default = {
        'ai_model_fails': [],
        'gpu_memory_overflows': [],
        'timeouts': [],
        'api_errors': [],
        'high_risk_errors': [],
        'medium_risk_errors': [],
        'low_risk_errors': [],
    }
    if not DASHBOARD_AVAILABLE:
        return jsonify(default)
    data = _load_json(ERROR_LOGS_DATA_PATH, default)
    for k in default:
        if k not in data:
            data[k] = default[k]
    return jsonify(data)


@bp.route('/api/dashboard/error_logs', methods=['POST'])
def dashboard_error_logs_save():
    # No disk write: error logs replaced by control plane audit.
    return jsonify({'success': False, 'message': 'Error logs are read-only; use control plane audit.'}), 501


@bp.route('/api/dashboard/job_status')
def dashboard_job_status():
    """Build job status counts live from _workflow_jobs + completed state files on disk."""

    running_list, completed_list, failed_list, retried_list = [], [], [], []
    total_retried = 0

    def _job_description_from_state(st: dict) -> str:
        topic = st.get('scholarly_topic') or st.get('essay_title') or ''
        dept = st.get('department', 'unknown')
        stage = st.get('current_stage') or ''
        if topic and topic not in ('general', 'unknown', ''):
            return f'{dept.capitalize()} — {topic[:60]}'
        return f'{dept.capitalize()}' + (f' — {stage}' if stage else '')

    # Live in-memory jobs
    seen_ids = set()
    for pid, job in list(_workflow_jobs.items()):
        seen_ids.add(pid)
        if _is_test_pid(pid):
            continue
        status = job.get('status', 'running')
        rc = job.get('retried_count', 0)
        total_retried += rc
        entry = {
            'pipeline_id': pid,
            'department': job.get('department', 'unknown'),
            'started': job.get('started', ''),
            'current_stage': job.get('current_stage') or '',
            'agent': f'{job.get("department", "?").upper()} pipeline',
            'start_time': (job.get('started', '')[:19] or '').replace('T', ' '),
            'end_time': (job.get('completed_at', '')[:19] or '').replace('T', ' ') or '—',
            'duration': '—',
            'error_message': str(job.get('error', ''))[:120] if job.get('error') else '—',
            'job_description': _job_description_from_state(job),
        }
        if status == 'completed':
            entry['completed_at'] = job.get('completed_at', '')
            completed_list.append(entry)
        elif status == 'failed':
            entry['error'] = str(job.get('error', ''))[:200]
            failed_list.append(entry)
        else:
            running_list.append(entry)
        if rc > 0:
            retried_list.append({**entry, 'retried_count': rc})

    # Completed jobs from persisted state files (survive Flask restart)
    for sf in _recent_state_files(_runtime_path('pipeline_*_state.json'), 200):
        try:
            with open(sf, 'r', encoding='utf-8') as _f:
                st = json.load(_f)
            pid = st.get('pipeline_id', '')
            if not pid or pid in seen_ids:
                continue
            seen_ids.add(pid)
            rc = st.get('retried_count', 0)
            total_retried += rc
            started = st.get('started', '')
            ended = st.get('ended', '')
            entry = {
                'pipeline_id': pid,
                'department': st.get('department', 'unknown'),
                'started': started,
                'completed_at': ended,
                'agent': f'{st.get("department", "?").upper()} pipeline',
                'start_time': (started[:19] or '').replace('T', ' '),
                'end_time': (ended[:19] or '').replace('T', ' ') or '—',
                'duration': '—',
                'error_message': str(st.get('error', ''))[:120] if st.get('error') else '—',
                'job_description': _job_description_from_state(st),
            }
            if st.get('error') or st.get('status') == 'failed':
                entry['error'] = str(st.get('error', 'unknown error'))[:200]
                failed_list.append(entry)
            else:
                completed_list.append(entry)
            if rc > 0:
                retried_list.append({**entry, 'retried_count': rc})
        except Exception as _exc:
            # The run silently vanishes from the counts the dashboard shows, so
            # name the file. Broad on purpose: a state file with an unexpected
            # value type raises TypeError/AttributeError in the body above.
            _zyg_log.warning('job status: skipping unreadable state file %s: %s', sf, _exc)

    return jsonify(
        {
            'running': len(running_list),
            'completed': len(completed_list),
            'failed': len(failed_list),
            'retried': total_retried,
            'running_list': running_list,
            'completed_list': completed_list,
            'failed_list': failed_list,
            'retried_list': retried_list,
        }
    )


@bp.route('/api/dashboard/job_status', methods=['POST'])
def dashboard_job_status_save():
    # No disk write: job status owned by control plane.
    return jsonify({'success': False, 'message': 'Job status is read-only; use control plane.'}), 501


@bp.route('/api/dashboard/monitoring_jobs')
@limiter.exempt
def dashboard_monitoring_jobs():
    """Return active/finished/planned jobs from _workflow_jobs + persisted state files."""

    active, finished, planned = [], [], []
    seen_ids = set()

    def _dur(started, ended=None):
        try:
            _s = _parse_iso_to_ams(started)
            _e = _parse_iso_to_ams(ended) if ended else _ams_now()
            if _s is None or _e is None:
                return '—'
            secs = int((_e - _s).total_seconds())
            return f'{secs // 60}m {secs % 60}s'
        except Exception:
            return '—'

    def _rich_description(job_or_state: dict) -> str:
        """Build a rich job description from topic/stage/department."""
        topic = (
            job_or_state.get('scholarly_topic')
            or job_or_state.get('essay_title')
            or job_or_state.get('directive', '')[:60]
        )
        dept = job_or_state.get('department', 'unknown')
        stage = job_or_state.get('current_stage') or ''
        parts = [f'{dept.capitalize()} pipeline']
        if topic and topic not in ('general', 'unknown', ''):
            parts.append(f'"{topic[:60]}"')
        if stage:
            parts.append(f'[{stage}]')
        return ' — '.join(parts)

    for pid, job in list(_workflow_jobs.items()):
        seen_ids.add(pid)
        if _is_test_pid(pid):
            continue
        dept = job.get('department', 'unknown')
        started = job.get('started', '')
        status = job.get('status', 'running')
        entry = {
            'agent': f'{dept.upper()} pipeline',
            'start_time': started[:19].replace('T', ' ') if started else '—',
            'end_time': job.get('completed_at', '')[:19].replace('T', ' ') or '—',
            'duration': _dur(started, job.get('completed_at')),
            'error_message': str(job.get('error', ''))[:120] if job.get('error') else '—',
            'job_description': _rich_description(job),
            'pipeline_id': pid,
            'status': status,
        }
        if status == 'queued':
            planned.append(entry)
        elif status in ('completed', 'failed'):
            finished.append(entry)
        else:
            active.append(entry)

    # Persisted completed jobs (survive restart)
    for sf in _recent_state_files(_runtime_path('pipeline_*_state.json'), 150):
        try:
            with open(sf, 'r', encoding='utf-8') as _f:
                st = json.load(_f)
            pid = st.get('pipeline_id', '')
            if not pid or pid in seen_ids:
                continue
            seen_ids.add(pid)
            dept = st.get('department', 'unknown')
            started = st.get('started', '')
            ended = st.get('ended', '')
            finished.append(
                {
                    'agent': f'{dept.upper()} pipeline',
                    'start_time': started[:19].replace('T', ' ') if started else '—',
                    'end_time': ended[:19].replace('T', ' ') if ended else '—',
                    'duration': _dur(started, ended) if ended else '—',
                    'error_message': str(st.get('error', ''))[:120] if st.get('error') else '—',
                    'job_description': _rich_description(st),
                    'pipeline_id': pid,
                    'status': 'failed' if st.get('error') else 'completed',
                }
            )
        except Exception as _exc:
            # Same as job_status: a skipped file is a job missing from the
            # monitoring tab, which the operator must be able to explain.
            _zyg_log.warning('monitoring jobs: skipping unreadable state file %s: %s', sf, _exc)

    return jsonify({'active': active, 'finished': finished, 'planned': planned})


@bp.route('/api/dashboard/monitoring_jobs', methods=['POST'])
def dashboard_monitoring_jobs_save():
    # No disk write: monitoring jobs owned by control plane.
    return jsonify({'success': False, 'message': 'Monitoring jobs are read-only; use control plane.'}), 501


@bp.route('/api/dashboard/language_pack/<language_name>')
def dashboard_language_pack_check(language_name):
    """Check if a language pack exists in the Languages folder. language_name is URL-encoded display name e.g. English."""
    if not DASHBOARD_AVAILABLE:
        return jsonify({'exists': False})
    import urllib.parse

    name = urllib.parse.unquote(language_name).strip()
    if not name:
        return jsonify({'exists': False})
    # Check for folder or file with that name (sanitize)
    safe = ''.join(c for c in name if c.isalnum() or c in ' -_')
    pack_path = os.path.join(LANGUAGES_DIR, safe)
    exists = os.path.isdir(pack_path) or os.path.isfile(pack_path)
    return jsonify({'exists': exists, 'language': name})


@bp.route('/api/dashboard/language_link/<language_name>')
def dashboard_language_link(language_name):
    """Get download URL for a language from Language Links. Returns url or null if not found."""
    if not DASHBOARD_AVAILABLE:
        return jsonify({'url': None})
    import urllib.parse

    name = urllib.parse.unquote(language_name).strip()
    if not name:
        return jsonify({'url': None})
    try:
        if os.path.isfile(LANGUAGE_LINKS_FILE):
            with open(LANGUAGE_LINKS_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
            url = data.get(name) if isinstance(data, dict) else None
            return jsonify({'url': url})
    except Exception as _exc:
        # The caller cannot tell "no link for this language" from "the link file
        # is broken" — the log has to. Broad on purpose: LANGUAGE_LINKS_FILE is
        # a tolerant getattr binding and may be None here (TypeError).
        _zyg_log.warning('language link file unreadable, answering url=null for %r: %s', name, _exc)
    return jsonify({'url': None})
