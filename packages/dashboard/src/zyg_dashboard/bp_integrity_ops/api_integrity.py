# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

from zyg_dashboard.bp_integrity_ops.constants import (
    API_ADAPTER_AVAILABLE,
    _OLLAMA_BASE_URL,
    _ams_iso,
    _comfy_vram_used_mb,
    _gpu_work_active,
    _read_local_telemetry,
    _recent_state_files,
    _release_pipeline_vram,
    _runtime_path,
    _steps,
    _workflow_jobs,
    _zero_audit_log,
    apply_cors,
    bp,
    exe,
    get_security_controls,
    get_telemetry,
    json,
    jsonify,
    limiter,
    os,
    paths,
    request,
    send_file,
    session,
    update_security_control,
)


import logging as _zyg_logging

# Bound by ASSIGNMENT (not `from .constants import _zyg_log`) so the moved
# `_zyg_log.debug(...)` calls keep compiling to the same method form.
# channel kept from the pre-split module
_zyg_log = _zyg_logging.getLogger('zyg_dashboard.bp_integrity_ops')


@bp.route('/api/integrity-gate')
def api_integrity_gate():
    """GET full integrity gate — categorized health checks covering every model and service in the pipeline."""
    import time as _time_ig

    _t0 = _time_ig.monotonic()
    _gpu_busy = any(j.get('status') == 'running' for j in _workflow_jobs.values())

    results = _steps.run_checks(_steps.build_tasks(_gpu_busy, _OLLAMA_BASE_URL))
    _stats = _steps.job_stats(_workflow_jobs)
    _cb_state, _recent_alerts = _steps.circuit_breaker()
    _last_pipeline = _steps.last_pipeline(_recent_state_files)
    _overall, _blocked_reason, _n_pass, _n_warn, _n_fail = _steps.summary(results)
    _elapsed = round((_time_ig.monotonic() - _t0) * 1000)

    return jsonify(
        {
            'checks': results,
            'overall': _overall,
            'blocked_reason': _blocked_reason,
            'stats': _stats,
            'circuit_breaker': {
                'state': _cb_state,
                'alerts': _recent_alerts,
            },
            'last_pipeline': _last_pipeline,
            'last_checked': _ams_iso()[:19] + 'Z',
            'elapsed_ms': _elapsed,
            'summary': {
                'pass': _n_pass,
                'warn': _n_warn,
                'fail': _n_fail,
                'total': len(results),
            },
        }
    )


@bp.route('/api/vram/free', methods=['POST'])
@limiter.exempt
def api_vram_free():
    """Evict ComfyUI cached models and in-process GPU globals. Safe when idle."""
    if _gpu_work_active():
        return jsonify(
            {
                'ok': False,
                'error': 'GPU work in progress — try again when pipelines finish',
                'comfy_vram_mb': _comfy_vram_used_mb(),
            }
        ), 409
    try:
        import subprocess as _sp_vf

        _before = _sp_vf.run(
            [exe('nvidia-smi'), '--query-gpu=memory.used,memory.free', '--format=csv,noheader,nounits'],
            capture_output=True,
            timeout=8,
            text=True,
        )
        _bparts = _before.stdout.strip().splitlines()[0].split(',') if _before.stdout.strip() else []
        _used_before = int(_bparts[0].strip()) if _bparts else None
    except Exception:
        _used_before = None
    _release_pipeline_vram('api', log_fn=lambda m: _zyg_log.info(f'[VRAM] {m}'))
    try:
        import subprocess as _sp_vf2

        _after = _sp_vf2.run(
            [exe('nvidia-smi'), '--query-gpu=memory.used,memory.free', '--format=csv,noheader,nounits'],
            capture_output=True,
            timeout=8,
            text=True,
        )
        _aparts = _after.stdout.strip().splitlines()[0].split(',') if _after.stdout.strip() else []
        _used_after = int(_aparts[0].strip()) if _aparts else None
        _free_after = int(_aparts[1].strip()) if len(_aparts) > 1 else None
    except Exception:
        _used_after = _free_after = None
    return jsonify(
        {
            'ok': True,
            'gpu_used_mb_before': _used_before,
            'gpu_used_mb_after': _used_after,
            'gpu_free_mb_after': _free_after,
            'comfy_vram_mb': _comfy_vram_used_mb(),
        }
    )


@bp.route('/api/telemetry')
@limiter.exempt
def api_telemetry():
    """GET real CPU/RAM/GPU usage. Always reads from psutil/pynvml directly — authoritative."""
    local = _read_local_telemetry()
    if API_ADAPTER_AVAILABLE:
        try:
            data = get_telemetry(token=session.get('api_token'))
            if not data.get('error'):
                # Only use control plane for fields local can't provide; local wins for hardware
                if not local.get('gpus') and data.get('gpus'):
                    local['gpus'] = data['gpus']
        except Exception as _exc:
            # Optional enrichment only — psutil/pynvml already answered and wins.
            _zyg_log.debug('control plane telemetry merge skipped: %s', _exc)
    resp = jsonify(local)
    resp.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    resp.headers['Pragma'] = 'no-cache'
    apply_cors(resp, request)
    return resp


@bp.route('/api/disk_usage')
@limiter.exempt
def api_disk_usage():
    """GET disk usage for the home partition."""
    import shutil as _shu

    result = {}
    for label, path in [('home', str(paths.ZYG_HOME)), ('root', '/')]:
        try:
            u = _shu.disk_usage(path)
            # shutil's `used` excludes the ~5% root-reserved blocks while `free` is the
            # user-available space, so used/total disagrees with free/total. Report
            # consistently from the user's point of view: anything not free is "used".
            used_bytes = u.total - u.free
            result[label] = {
                'total_gb': round(u.total / 1024**3, 1),
                'used_gb': round(used_bytes / 1024**3, 1),
                'free_gb': round(u.free / 1024**3, 1),
                'used_pct': round(used_bytes / u.total * 100, 1) if u.total else 0,
            }
        except Exception as e:
            result[label] = {'error': str(e)}
    resp = jsonify(result)
    resp.headers['Cache-Control'] = 'no-store'
    apply_cors(resp, request)
    return resp


@bp.route('/api/telemetry_log/<pipeline_id>')
def api_telemetry_log(pipeline_id):
    """GET CSV logbook of hardware metrics recorded every second during a pipeline run."""
    import re

    if not re.match(r'^[0-9a-f\-]{36}$', pipeline_id):
        return jsonify({'error': 'invalid pipeline_id'}), 400
    log_file = _runtime_path(f'telemetry_{pipeline_id}.csv')
    if not os.path.exists(log_file):
        return jsonify({'error': 'no telemetry log for this run'}), 404

    return send_file(
        log_file, mimetype='text/csv', as_attachment=True, download_name=f'telemetry_{pipeline_id[:8]}.csv'
    )


@bp.route('/api/admin/security-controls')
def api_security_controls_get():
    """GET security control implementation status per stack step. Governance checklist. Admin only."""
    if not API_ADAPTER_AVAILABLE:
        return jsonify({'items': [], 'error': 'Control plane not configured'})
    token = session.get('api_token')
    data = get_security_controls(token=token)
    if data.get('error'):
        return jsonify({'items': [], 'error': data.get('error')})
    return jsonify({'items': data.get('items', [])})


@bp.route('/api/admin/security-controls/<control_id>', methods=['PATCH'])
@limiter.limit('60/hour')
def api_security_controls_patch(control_id):
    """PATCH security control status (implemented|partial|not_implemented). Admin only. Audit logged."""
    if not API_ADAPTER_AVAILABLE:
        return jsonify({'success': False, 'error': 'Control plane not configured'}), 503
    token = session.get('api_token')
    body = request.get_json() or {}
    status_val = body.get('status', 'not_implemented')
    notes = body.get('notes', '')
    data = update_security_control(control_id=control_id, control_status=status_val, notes=notes or None, token=token)
    if data.get('error'):
        return jsonify({'success': False, 'error': data.get('error')}), data.get('status', 403)
    return jsonify(data)


@bp.route('/api/integrity-gate/force-override', methods=['POST'])
@limiter.limit('20/hour')
def api_integrity_gate_force_override():
    """POST force override — locally triggers schedule pause/resume."""
    if session.get('user_role') != 'admins':
        return jsonify({'success': False, 'error': 'Admin only'}), 403
    body = request.get_json() or {}
    action = body.get('action', 'resume')
    reason = body.get('reason', 'Admin force override')
    try:
        _pause_path = _runtime_path('schedule_paused.json')
        _paused = action != 'resume'
        with open(_pause_path, 'w', encoding='utf-8') as _f:
            json.dump({'paused': _paused, 'reason': reason, 'updated_at': _ams_iso(), 'updated_by': 'admin'}, _f)
        _zero_audit_log(f'integrity_gate_{action}', {'reason': reason, 'action': action})
        return jsonify({'success': True, 'paused': _paused, 'action': action, 'reason': reason})
    except Exception as _e:
        return jsonify({'success': False, 'error': str(_e)})
