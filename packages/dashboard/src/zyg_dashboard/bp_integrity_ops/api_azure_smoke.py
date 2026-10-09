# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

from zyg_dashboard.bp_integrity_ops.constants import (
    _SMOKE_SCRIPTS,
    _ams_iso,
    _require_csrf,
    _smoke_runs,
    _smoke_runs_persist,
    block_spectator_mutation,
    bp,
    jsonify,
    limiter,
    os,
    request,
    sys,
    uuid,
)
from zyg_dashboard import paths as dashboard_paths


@bp.route('/api/azure/usage')
@limiter.exempt
def azure_usage():
    """Return current Azure free-tier usage counters for the dashboard."""
    try:
        from zyg_workflows.azure_budget import get_usage

        return jsonify({'success': True, 'usage': get_usage()})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@bp.route('/api/azure/config', methods=['GET'])
def azure_config_get():
    """Return current Azure config — secrets masked as ****."""
    r = block_spectator_mutation()
    if r is not None:
        return r
    try:
        from zyg_workflows.azure_integrations import load_config

        cfg = load_config()
        _SECRET_FIELDS = ('blob_connection_string', 'eventgrid_key', 'function_key', 'speech_key')
        masked = {}
        for k, v in cfg.items():
            if k in _SECRET_FIELDS and v:
                masked[k] = '****'
            else:
                masked[k] = v
        return jsonify({'success': True, 'config': masked})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@bp.route('/api/azure/config', methods=['POST'])
def azure_config_save():
    """Save Azure config. Only fields explicitly sent are updated; masked **** values are kept as-is."""
    r = block_spectator_mutation()
    if r is not None:
        return r
    csrf_err = _require_csrf()
    if csrf_err:
        return csrf_err
    try:
        from zyg_workflows.azure_integrations import load_config, save_config

        data = request.get_json() or {}
        current = load_config()
        _SECRET_FIELDS = ('blob_connection_string', 'eventgrid_key', 'function_key', 'speech_key')
        for k, v in data.items():
            if k in _SECRET_FIELDS and v == '****':
                continue  # keep existing secret — don't overwrite with masked placeholder
            current[k] = v
        save_config(current)
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@bp.route('/api/azure/reset_counter', methods=['POST'])
def azure_reset_counter():
    """Reset a specific Azure usage counter (admin action)."""
    r = block_spectator_mutation()
    if r is not None:
        return r
    csrf_err = _require_csrf()
    if csrf_err:
        return csrf_err
    try:
        from zyg_workflows.azure_budget import reset_service

        service = (request.get_json() or {}).get('service', '')
        ok = reset_service(service)
        return jsonify({'success': ok})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@bp.route('/api/smoke-test/run', methods=['POST'])
def smoke_test_run():
    """Launch a smoke-test script in a background subprocess."""
    r = block_spectator_mutation()
    if r is not None:
        return r
    data = request.get_json() or {}
    pipeline = data.get('pipeline', '').strip().lower()
    if pipeline not in _SMOKE_SCRIPTS:
        return jsonify({'error': f'Unknown pipeline: {pipeline!r}. Valid: {list(_SMOKE_SCRIPTS)}'}), 400

    script_rel = _SMOKE_SCRIPTS[pipeline]
    # The smoke scripts are named relative to zyg_dashboard/, where the
    # pre-split module lived and from where this path was built.
    script_abs = os.path.join(str(dashboard_paths.PKG_DIR), script_rel)
    if not os.path.isfile(script_abs):
        return jsonify({'error': f'Script not found: {script_abs}'}), 404

    run_id = f'{pipeline}-{uuid.uuid4().hex[:8]}'
    entry = {
        'run_id': run_id,
        'pipeline': pipeline,
        'script': script_abs,
        'status': 'running',
        'output': [],
        'started': _ams_iso(),
        'finished': None,
        'exit_code': None,
    }
    _smoke_runs[run_id] = entry

    import subprocess as _sp_smoke
    import threading as _thr_smoke

    def _stream(proc, ent):
        try:
            for raw in iter(proc.stdout.readline, b''):
                line = raw.decode('utf-8', errors='replace').rstrip('\n')
                ent['output'].append(line)
                if len(ent['output']) > 4000:
                    ent['output'] = ent['output'][-4000:]
            proc.wait()
            ent['exit_code'] = proc.returncode
            ent['status'] = 'passed' if proc.returncode == 0 else 'failed'
            ent['finished'] = _ams_iso()
        except Exception as _se:
            ent['status'] = 'error'
            ent['finished'] = _ams_iso()
            ent['output'].append(f'[runner error] {_se}')
        _smoke_runs_persist()  # result survives a GUI restart

    crews_dir = str(dashboard_paths.PKG_DIR)
    # P-01 latent (2026-08-25): the child inherits the GUI's env. Without these
    # flags the harness's `import crewai_web_gui` starts a SECOND market/sports
    # scheduler inside the test process; ZYG_NO_DELIVERY keeps the render off
    # the Desktop and ZYG_SMOKE_RUN tells the pipeline it is a test.
    proc = _sp_smoke.Popen(
        [sys.executable, script_abs],
        stdout=_sp_smoke.PIPE,
        stderr=_sp_smoke.STDOUT,
        cwd=crews_dir,
        env={
            **os.environ,
            'PYTHONUNBUFFERED': '1',
            'ZYG_SPORTS_SCHEDULER': '0',
            'ZYG_MARKET_SCHEDULER': '0',
            'ZYG_NO_DELIVERY': '1',
            'ZYG_SMOKE_RUN': '1',
            # A smoke child must never SIGTERM its own parent GUI (P-01).
            'ZYG_KILL_SIBLING_FLASK': '0',
        },
    )
    entry['pid'] = proc.pid
    _smoke_runs_persist()  # a crash mid-run still leaves a record
    _thr_smoke.Thread(target=_stream, args=(proc, entry), daemon=True, name=f'smoke-{run_id}').start()

    return jsonify({'run_id': run_id, 'status': 'running', 'pid': proc.pid})


@bp.route('/api/smoke-test/status/<run_id>')
def smoke_test_status(run_id):
    """Poll smoke-test run: returns status + all output lines so far."""
    entry = _smoke_runs.get(run_id)
    if not entry:
        return jsonify({'error': 'run not found'}), 404
    return jsonify(
        {
            'run_id': run_id,
            'pipeline': entry['pipeline'],
            'status': entry['status'],
            'output': entry['output'],
            'exit_code': entry['exit_code'],
            'started': entry['started'],
            'finished': entry['finished'],
        }
    )


@bp.route('/api/smoke-test/list')
def smoke_test_list():
    """Return summary of all smoke-test runs (newest first)."""
    runs = sorted(_smoke_runs.values(), key=lambda r: r['started'], reverse=True)
    return jsonify(
        [
            {
                'run_id': r['run_id'],
                'pipeline': r['pipeline'],
                'status': r['status'],
                'started': r['started'],
                'finished': r['finished'],
                'exit_code': r['exit_code'],
            }
            for r in runs[:20]
        ]
    )
