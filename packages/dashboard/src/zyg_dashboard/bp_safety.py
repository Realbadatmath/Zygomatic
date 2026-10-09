# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

# Generated 2026-07-17 by the GUI modularization — extracted from crewai_web_gui.py.
# Source lines: see crews_modularization_backups_20260717/MODULARIZATION_CHANGELOG.md
# Contract: this module is imported at the BOTTOM of crewai_web_gui.py, after all
# of main's globals exist; `from crewai_web_gui import X` is therefore safe here.
import logging as _zyg_logging
import os
from flask import Blueprint, jsonify, request, session

bp = Blueprint('safety', __name__)

from zyg_dashboard.crewai_web_gui import (  # noqa: E402  (late import by design, see contract above)
    DASHBOARD_AVAILABLE,
    ERROR_LOGS_DATA_PATH,
    JOB_STATUS_DATA_PATH,
    SAFETY_THRESHOLDS_PATH,
    _halt_all_pipeline_activity,
    limiter,
)
from zyg_dashboard.gui.runtime_state import _load_json  # noqa: E402
from zyg_dashboard.gui.telemetry import (  # noqa: E402
    API_ADAPTER_AVAILABLE,
    _read_local_telemetry,
    get_job_runs,
    get_schedule_pause_state,
    get_telemetry,
    set_schedule_pause,
    terminate_job_run,
)
from zyg_dashboard.gui.timeutil import _ams_iso, _ams_now  # noqa: E402

_zyg_log = _zyg_logging.getLogger(__name__)


def _safety_telemetry_fn():
    if not API_ADAPTER_AVAILABLE:
        return _read_local_telemetry()
    try:
        data = get_telemetry(token=session.get('api_token'))
        # If control plane returned no GPU data, supplement with local pynvml
        if not data.get('gpus') and not data.get('error'):
            local = _read_local_telemetry()
            data.setdefault('gpus', local.get('gpus', []))
        return data
    except Exception:
        return _read_local_telemetry()


def _safety_job_status_fn():
    if not DASHBOARD_AVAILABLE:
        return {'running_list': [], 'failed_list': []}
    return _load_json(JOB_STATUS_DATA_PATH, {'running_list': [], 'failed_list': []})


def _safety_schedule_pause_fn():
    if not API_ADAPTER_AVAILABLE:
        return {'paused': False}
    return get_schedule_pause_state(token=session.get('api_token'))


def _safety_error_logs_fn():
    if not DASHBOARD_AVAILABLE:
        return {}
    return _load_json(
        ERROR_LOGS_DATA_PATH, {'gpu_memory_overflows': [], 'ai_model_fails': [], 'timeouts': [], 'api_errors': []}
    )


@bp.route('/api/safety/status')
def get_safety_status():
    """System Safety & Protection status. Full subsystem: guards, telemetry, circuit breaker."""
    try:
        from zyg_workflows.safety_subsystem import get_safety_status as _get_safety_status

        path = (
            SAFETY_THRESHOLDS_PATH
            if DASHBOARD_AVAILABLE
            else os.path.join(os.path.dirname(__file__), 'safety_thresholds.json')
        )
        data = _get_safety_status(
            thresholds_path=path,
            telemetry_fn=_safety_telemetry_fn,
            job_status_fn=_safety_job_status_fn,
            schedule_pause_fn=_safety_schedule_pause_fn,
            error_logs_fn=_safety_error_logs_fn,
        )
        return jsonify(data)
    except ImportError:
        return jsonify(
            {
                'protection_level': 0,
                'protection_label': 'Normal',
                'protection_desc': 'Safety subsystem not available.',
                'circuit_breaker_active': False,
                'emergency_stop_active': False,
                'hardware': {},
                'stability': {},
                'control': {},
                'audit_events': [],
                'thresholds': {},
            }
        )
    except Exception as e:
        return jsonify(
            {
                'protection_level': 0,
                'protection_label': 'Normal',
                'protection_desc': 'Safety telemetry unavailable.',
                'circuit_breaker_active': False,
                'emergency_stop_active': False,
                'hardware': {},
                'stability': {},
                'control': {},
                'audit_events': [{'ts': _ams_iso(), 'event': str(e), 'level': 'error'}],
                'thresholds': {},
            }
        )


@bp.route('/api/safety/emergency_stop', methods=['POST'])
def post_safety_emergency_stop():
    """Emergency stop — immediately kills all local pipelines + browser processes.
    Also pauses remote schedule if API adapter is available."""
    actor = session.get('user_id') or session.get('user_role') or 'unknown'

    # ── Local stop: always works, regardless of API adapter ──────────────────
    _halt_summary = _halt_all_pipeline_activity('Emergency stop')
    stopped = [j['id'] for j in _halt_summary.get('stopped_jobs') or []]
    killed_pids = _halt_summary.get('killed_pids') or []

    # ── Remote stop: best-effort, non-blocking ────────────────────────────────
    remote_msg = ''
    if API_ADAPTER_AVAILABLE:
        try:
            from zyg_workflows.safety_subsystem import audit_log

            data = set_schedule_pause(
                paused=True, reason='Emergency stop from Safety Switch', token=session.get('api_token')
            )
            if not data.get('error'):
                remote_msg = ' Remote schedule paused.'
            audit_log('Emergency stop activated', level='warning', extra={'actor': actor})
        except Exception as _exc:
            _zyg_log.warning('remote schedule pause / audit for the emergency stop failed: %s', _exc)

    return jsonify(
        {
            'success': True,
            'message': f'Emergency stop: {len(stopped)} job(s) halted, {len(killed_pids)} worker(s) killed.{remote_msg}',
            'stopped_jobs': stopped,
            'killed_pids': killed_pids,
            'audit_id': _ams_now().strftime('%Y%m%d%H%M%S'),
        }
    )


@bp.route('/api/safety/emergency_stop_full', methods=['POST'])
@limiter.limit('5/hour')
def post_safety_emergency_stop_full():
    """Full emergency stop: kill all local pipelines + browsers + pause remote schedule."""
    if session.get('user_role') not in ('admin', 'admins'):
        return jsonify({'success': False, 'error': 'Admin role required'}), 403

    actor = session.get('user_id') or session.get('user_role') or 'unknown'

    # ── Local stop ────────────────────────────────────────────────────────────
    _halt_summary = _halt_all_pipeline_activity('Full emergency stop')
    stopped = [j['id'] for j in _halt_summary.get('stopped_jobs') or []]
    killed_pids = _halt_summary.get('killed_pids') or []

    # ── Remote stop: best-effort ──────────────────────────────────────────────
    terminated = []
    if API_ADAPTER_AVAILABLE:
        try:
            from zyg_workflows.safety_subsystem import audit_log

            token = session.get('api_token')
            set_schedule_pause(paused=True, reason='Full emergency stop from Safety Switch', token=token)
            runs_data = get_job_runs(token=token, status_filter='running')
            for r in runs_data.get('items') or []:
                rid = r.get('id')
                if rid:
                    t = terminate_job_run(rid, reason='Full emergency stop', token=token)
                    if t.get('ok'):
                        terminated.append(rid)
            audit_log(
                'Full emergency stop activated',
                level='warning',
                actor=actor,
                extra={'stopped': len(stopped), 'killed': len(killed_pids)},
            )
        except Exception as _exc:
            _zyg_log.warning('remote job termination / audit for the full emergency stop failed: %s', _exc)

    return jsonify(
        {
            'success': True,
            'message': f'Full emergency stop: {len(stopped)} job(s) halted, {len(killed_pids)} worker(s) killed, {len(terminated)} remote run(s) terminated.',
            'stopped_jobs': stopped,
            'killed_pids': killed_pids,
            'terminated_count': len(terminated),
            'terminated_run_ids': terminated,
        }
    )


@bp.route('/api/safety/confirm_recovery', methods=['POST'])
@limiter.limit('20/hour')
def post_safety_confirm_recovery():
    """Admin confirms L3 recovery or advances L4 staged recovery. Required before resume when protection level 3/4."""
    if session.get('user_role') not in ('admin', 'admins'):
        return jsonify({'success': False, 'error': 'Admin role required'}), 403
    try:
        from zyg_workflows.safety_subsystem import confirm_recovery

        body = request.get_json() or {}
        level = body.get('level')
        if level not in (3, 4):
            return jsonify({'success': False, 'error': 'level must be 3 or 4'}), 400
        actor = session.get('user_id') or session.get('user_role') or 'unknown'
        reason = body.get('reason', '')
        stage = body.get('stage')  # Required for L4
        if level == 4 and not stage:
            return jsonify(
                {'success': False, 'error': 'L4 requires stage: ui, scheduler, agents, or heavy_models'}
            ), 400
        success, err = confirm_recovery(level=level, actor=actor, reason=reason, stage=stage)
        if success:
            return jsonify({'success': True, 'message': 'Recovery confirmed'})
        return jsonify({'success': False, 'error': err or 'Confirm failed'}), 400
    except ImportError:
        return jsonify({'success': False, 'error': 'Safety subsystem not available'}), 503
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@bp.route('/api/safety/thresholds', methods=['GET'])
def get_safety_thresholds():
    """GET threshold configuration. Admin only for sensitive view."""
    try:
        from zyg_workflows.safety_subsystem import _load_thresholds

        path = (
            SAFETY_THRESHOLDS_PATH
            if DASHBOARD_AVAILABLE
            else os.path.join(os.path.dirname(__file__), 'safety_thresholds.json')
        )
        return jsonify(_load_thresholds(path))
    except ImportError:
        return jsonify({})
    except Exception:
        return jsonify({})


@bp.route('/api/safety/thresholds', methods=['PATCH'])
@limiter.limit('20/hour')
def patch_safety_thresholds():
    """PATCH threshold configuration. Admin only. Audited."""
    if session.get('user_role') not in ('admin', 'admins'):
        return jsonify({'success': False, 'error': 'Admin role required'}), 403
    try:
        from zyg_workflows.safety_subsystem import update_thresholds

        path = (
            SAFETY_THRESHOLDS_PATH
            if DASHBOARD_AVAILABLE
            else os.path.join(os.path.dirname(__file__), 'safety_thresholds.json')
        )
        body = request.get_json() or {}
        actor = session.get('user_id') or session.get('user_role') or 'unknown'
        success, err = update_thresholds(path, body, actor=actor)
        if success:
            return jsonify({'success': True, 'message': 'Thresholds updated'})
        return jsonify({'success': False, 'error': err or 'Update failed'}), 400
    except ImportError:
        return jsonify({'success': False, 'error': 'Safety subsystem not available'}), 503
