# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""
Thin adapter between Flask legacy UI and FastAPI control plane.
Flask NEVER talks to JSON for state; Flask ONLY calls these functions.
All authority (auth, schedules, approvals) lives in FastAPI.
"""

import os
from typing import Any, Optional

import requests
from zyg_workflows.paths import BIND_HOST

# Control plane base URL; override with CONTROL_PLANE_API_URL, otherwise the
# loopback address BIND_HOST names on port 8000.
API_URL = os.environ.get('CONTROL_PLANE_API_URL', f'http://{BIND_HOST}:8000').rstrip('/')

# Dev-only: when True, CONTROL_PLANE_DEV_TOKEN is used when no Bearer token. Must not ship to production.
CONTROL_PLANE_DEV_MODE = os.environ.get('CONTROL_PLANE_DEV_MODE', 'false').lower() in ('1', 'true', 'yes')
# Only used when CONTROL_PLANE_DEV_MODE is True. No default — must be explicitly set.
if CONTROL_PLANE_DEV_MODE:
    DEV_TOKEN = os.environ.get('CONTROL_PLANE_DEV_TOKEN')
    if not DEV_TOKEN:
        raise RuntimeError(
            'CONTROL_PLANE_DEV_MODE is enabled but CONTROL_PLANE_DEV_TOKEN is not set. '
            'Set CONTROL_PLANE_DEV_TOKEN=dev:operator (or dev:admin) or disable dev mode.'
        )
else:
    DEV_TOKEN = None


def _headers(token: Optional[str] = None, include_content_type: bool = True) -> dict:
    """Build request headers with auth. Bearer required unless dev mode and dev token fallback."""
    h = {'Accept': 'application/json'}
    if include_content_type:
        h['Content-Type'] = 'application/json'
    if token:
        h['Authorization'] = f'Bearer {token}'
    elif CONTROL_PLANE_DEV_MODE and DEV_TOKEN:
        h['X-Dev-Token'] = DEV_TOKEN
    # If no token and not dev mode: no auth header (FastAPI will 401)
    return h


def _get(
    path: str, token: Optional[str] = None, params: Optional[dict] = None
) -> tuple[Optional[dict], int, Optional[str]]:
    """GET from control plane. Returns (json_data, status_code, error_message)."""
    try:
        # Omit Content-Type for GET to avoid FastAPI treating empty body as JSON
        r = requests.get(
            f'{API_URL}{path}',
            headers=_headers(token, include_content_type=False),
            params=params or {},
            timeout=30,
        )
        try:
            data = r.json()
        except Exception:
            data = None
        if r.status_code >= 400:
            err = _format_error_detail(data, r.text) if isinstance(data, dict) else r.text
            return data, r.status_code, err
        return data, r.status_code, None
    except requests.RequestException as e:
        return None, 0, _friendly_connection_error(e)


def _format_error_detail(data: dict, fallback: str) -> str:
    """Extract a user-friendly error message from FastAPI 422/4xx response."""
    detail = data.get('detail', fallback)
    if isinstance(detail, str):
        return detail
    if isinstance(detail, list) and detail:
        parts = []
        for d in detail[:3]:  # Limit to first 3
            if isinstance(d, dict):
                loc = d.get('loc', [])
                msg = d.get('msg', 'validation error')
                loc_str = '.'.join(str(x) for x in loc if x != 'body') or 'request'
                parts.append(f'{loc_str}: {msg}')
            else:
                parts.append(str(d))
        return '; '.join(parts) if parts else fallback
    return fallback


def _friendly_connection_error(e: Exception) -> str:
    """Return a short user-facing message instead of the full exception for connection errors."""
    msg = str(e).lower()
    if 'connection' in msg and ('refused' in msg or '10061' in msg or '8000' in msg):
        return 'Control plane is not running. Start the FastAPI server on port 8000 (e.g. run the API before opening Dev Legacy Launcher).'
    if 'timeout' in msg or 'timed out' in msg:
        return 'Control plane did not respond in time. Check that the API on port 8000 is running.'
    return 'Control plane unreachable. Is the FastAPI server running on port 8000?'


def _post(path: str, json_body: dict, token: Optional[str] = None) -> tuple[Optional[dict], int, Optional[str]]:
    """POST to control plane. Returns (json_data, status_code, error_message)."""
    try:
        r = requests.post(
            f'{API_URL}{path}',
            headers=_headers(token),
            json=json_body,
            timeout=30,
        )
        try:
            data = r.json()
        except Exception:
            data = None
        if r.status_code >= 400:
            detail = data.get('detail', r.text) if isinstance(data, dict) else r.text
            return data, r.status_code, detail
        return data, r.status_code, None
    except requests.RequestException as e:
        return None, 0, _friendly_connection_error(e)


def _patch(path: str, json_body: dict, token: Optional[str] = None) -> tuple[Optional[dict], int, Optional[str]]:
    """PATCH to control plane. Returns (json_data, status_code, error_message)."""
    try:
        r = requests.patch(
            f'{API_URL}{path}',
            headers=_headers(token),
            json=json_body,
            timeout=30,
        )
        try:
            data = r.json()
        except Exception:
            data = None
        if r.status_code >= 400:
            detail = data.get('detail', r.text) if isinstance(data, dict) else r.text
            return data, r.status_code, detail
        return data, r.status_code, None
    except requests.RequestException as e:
        return None, 0, _friendly_connection_error(e)


# --- Agents ---


def get_agents(token: Optional[str] = None) -> dict:
    """GET /agents. Returns {"items": [...]} or error shape."""
    data, status, err = _get('/agents', token=token)
    if err:
        return {'items': [], 'error': err, 'status': status}
    return data or {'items': []}


def get_agent(agent_id: str, token: Optional[str] = None) -> dict:
    """GET /agents/{agent_id}."""
    data, status, err = _get(f'/agents/{agent_id}', token=token)
    if err:
        return {'error': err, 'status': status}
    return data or {}


# --- Schedules / Schedule requests ---


def get_schedule_requests(token: Optional[str] = None, status_filter: Optional[str] = None) -> dict:
    """GET /schedules/requests. Returns {"items": [...]}. Use for Requests screen (proposals)."""
    params = {}
    if status_filter:
        params['status_filter'] = status_filter
    data, status, err = _get('/schedules/requests', token=token, params=params or None)
    if err:
        return {'items': [], 'error': err, 'status': status}
    return data or {'items': []}


def get_active_schedule(scope: str, token: Optional[str] = None) -> dict:
    """GET /schedules/active?scope=gpu|cpu. Returns approved+activated entries (what will execute). Use for GPU Schedule / Timeline view."""
    data, status, err = _get('/schedules/active', token=token, params={'scope': scope})
    if err:
        return {'entries': [], 'error': err, 'status': status}
    return data or {'entries': []}


def get_schedule_request(request_id: str, token: Optional[str] = None) -> dict:
    """GET /schedules/requests/{id}."""
    data, status, err = _get(f'/schedules/requests/{request_id}', token=token)
    if err:
        return {'error': err, 'status': status}
    return data or {}


def submit_schedule_request(
    payload: dict,
    actor_type: str = 'user',
    token: Optional[str] = None,
    action: str = 'CREATE',
    target_entry_id: Optional[str] = None,
) -> dict:
    """POST /schedules/requests. Mandated path for any mutation. action: CREATE | UPDATE | DELETE.
    For DELETE/UPDATE, set payload.target_entry_id (and optionally action in payload)."""
    p = dict(payload)
    p['action'] = action
    if target_entry_id is not None:
        p['target_entry_id'] = target_entry_id
    data, status, err = _post(
        '/schedules/requests',
        json_body={'actor_type': actor_type, 'payload': p},
        token=token,
    )
    if err:
        return {'error': err, 'status': status, 'success': False}
    return data or {'success': True}


# --- Approvals ---


def get_approval_queue(token: Optional[str] = None) -> dict:
    """GET /approvals/queue. Pending schedule requests for admin."""
    data, status, err = _get('/approvals/queue', token=token)
    if err:
        return {'items': [], 'error': err, 'status': status}
    return data or {'items': []}


def create_approval(
    schedule_request_id: str, policy_snapshot: Optional[dict] = None, token: Optional[str] = None
) -> dict:
    """POST /approvals. Admin only; cannot approve own submission."""
    data, status, err = _post(
        '/approvals',
        json_body={'schedule_request_id': schedule_request_id, 'policy_snapshot': policy_snapshot or {}},
        token=token,
    )
    if err:
        return {'error': err, 'status': status, 'success': False}
    return data or {'success': True}


# --- Audit ---


def get_audit(
    token: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
    actor: Optional[str] = None,
    action: Optional[str] = None,
    object_type: Optional[str] = None,
) -> dict:
    """GET /audit. List audit log entries. Admin only."""
    params: dict[str, Any] = {'limit': limit, 'offset': offset}
    if actor:
        params['actor'] = actor
    if action:
        params['action'] = action
    if object_type:
        params['object_type'] = object_type
    data, status, err = _get('/audit', token=token, params=params)
    if err:
        return {'items': [], 'total': 0, 'error': err, 'status': status}
    return data or {'items': [], 'total': 0}


# --- Jobs (lifecycle: specs + runs) ---


def get_job_specs(token: Optional[str] = None) -> dict:
    """GET /jobs/specs. Approved job specs."""
    data, status, err = _get('/jobs/specs', token=token)
    if err:
        return {'items': [], 'error': err, 'status': status}
    return data or {'items': []}


def expire_job_leases(token: Optional[str] = None) -> dict:
    """POST /jobs/runs/expire-leases. Find runs with expired lease, mark failed, audit."""
    data, status_code, err = _post('/jobs/runs/expire-leases', json_body={}, token=token)
    if err:
        return {'ok': False, 'error': err, 'status': status_code, 'expired_count': 0, 'run_ids': []}
    return data or {'ok': True, 'expired_count': 0, 'run_ids': []}


def terminate_job_run(run_id: str, reason: str = '', token: Optional[str] = None) -> dict:
    """POST /admin/jobs/runs/{run_id}/terminate. Admin force-fail a running run (full emergency stop)."""
    data, status_code, err = _post(
        f'/admin/jobs/runs/{run_id}/terminate',
        json_body={'reason': reason or 'Safety subsystem emergency terminate'},
        token=token,
    )
    if err:
        return {'ok': False, 'error': err, 'status': status_code}
    return data or {'ok': True, 'run_id': run_id}


def reduce_agent_concurrency(agent_id: str, new_max: int, token: Optional[str] = None) -> dict:
    """Reduce max_concurrent_gpu_jobs for an agent via budget. POST /admin/budgets (upsert)."""
    data, status_code, err = _post(
        '/admin/budgets',
        json_body={
            'id': f'agent:{agent_id}',
            'scope_type': 'agent',
            'scope_id': agent_id,
            'gpu_seconds_per_day': 0.0,
            'max_concurrent_gpu_jobs': max(0, new_max),
        },
        token=token,
    )
    if err:
        return {'success': False, 'error': err, 'status': status_code}
    return data or {'success': True}


def get_job_runs(
    token: Optional[str] = None,
    job_spec_id: Optional[str] = None,
    status_filter: Optional[str] = None,
) -> dict:
    """GET /jobs/runs. Job runs (optionally by spec or status)."""
    params: dict = {}
    if job_spec_id:
        params['job_spec_id'] = job_spec_id
    if status_filter:
        params['status_filter'] = status_filter
    data, status, err = _get('/jobs/runs', token=token, params=params or None)
    if err:
        return {'items': [], 'error': err, 'status': status}
    return data or {'items': []}


def get_job_events(
    token: Optional[str] = None,
    entity_type: Optional[str] = None,
    entity_id: Optional[str] = None,
    event_type: Optional[str] = None,
    limit: int = 100,
) -> dict:
    """GET /jobs/events. Append-only event stream for forensic debugging."""
    params: dict = {'limit': min(limit, 1000)}
    if entity_type:
        params['entity_type'] = entity_type
    if entity_id:
        params['entity_id'] = entity_id
    if event_type:
        params['event_type'] = event_type
    data, status, err = _get('/jobs/events', token=token, params=params)
    if err:
        return {'items': [], 'error': err, 'status': status}
    return data or {'items': []}


# --- Circuit breaker (schedule pause) ---


def get_schedule_pause_state(token: Optional[str] = None) -> dict:
    """GET /admin/schedule-pause. Paused state (anomaly → auto-pause, human resume)."""
    data, status, err = _get('/admin/schedule-pause', token=token)
    if err:
        return {'paused': False, 'reason': '', 'error': err, 'status': status}
    return data or {'paused': False, 'reason': ''}


def set_schedule_pause(paused: bool, reason: str = '', token: Optional[str] = None) -> dict:
    """POST /admin/schedule-pause. Admin only. Pause or resume schedule execution."""
    data, status, err = _post(
        '/admin/schedule-pause',
        json_body={'paused': paused, 'reason': reason or ''},
        token=token,
    )
    if err:
        return {'success': False, 'error': err, 'status': status}
    return data or {'success': True}


def get_integrity_gate(token: Optional[str] = None) -> dict:
    """GET /admin/integrity-gate. Checks passed/failed, blocked reason."""
    data, status, err = _get('/admin/integrity-gate', token=token)
    if err:
        return {'checks': [], 'blocked_reason': None, 'error': err, 'status': status}
    return data or {'checks': [], 'blocked_reason': None}


def get_telemetry(token: Optional[str] = None) -> dict:
    """GET /admin/telemetry. Real CPU/RAM/GPU usage (replaces assigned==usage). Admin only."""
    data, status, err = _get('/admin/telemetry', token=token)
    if err:
        return {'error': err, 'status': status, 'cpu_pct': 0, 'ram_pct': 0, 'gpus': []}
    return data or {'cpu_pct': 0, 'ram_pct': 0, 'gpus': []}


def force_override_integrity_gate(action: str = 'resume', reason: str = '', token: Optional[str] = None) -> dict:
    """POST /admin/integrity-gate/force-override. Admin only."""
    data, status, err = _post(
        '/admin/integrity-gate/force-override',
        json_body={'action': action, 'reason': reason},
        token=token,
    )
    if err:
        return {'success': False, 'error': err, 'status': status}
    return data or {'success': True}


def get_security_controls(token: Optional[str] = None) -> dict:
    """GET /admin/security-controls. Implementation status per stack step (governance)."""
    data, status, err = _get('/admin/security-controls', token=token)
    if err:
        return {'items': [], 'error': err, 'status': status}
    return data or {'items': []}


def update_security_control(
    control_id: str, control_status: str, notes: Optional[str] = None, token: Optional[str] = None
) -> dict:
    """PATCH /admin/security-controls/{id}. Admin only. Updates logged to audit."""
    data, status_code, err = _patch(
        f'/admin/security-controls/{control_id}',
        json_body={'status': control_status, 'notes': notes or ''},
        token=token,
    )
    if err:
        return {'error': err, 'status': status_code, 'success': False}
    return data or {'success': True}


# --- Auth (who am I) ---


def get_me(token: Optional[str] = None) -> dict:
    """GET /auth/me. Current identity (user_id, username, roles)."""
    data, status, err = _get('/auth/me', token=token)
    if err:
        return {'error': err, 'status': status}
    return data or {}
