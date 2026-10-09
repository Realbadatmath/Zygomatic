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
import time
import threading
from flask import Blueprint, jsonify, request, send_from_directory, session

bp = Blueprint('timeline_legacy', __name__)

from zyg_dashboard.crewai_web_gui import (  # noqa: E402  (late import by design, see contract above)
    _get_gpu_models,
    atexit,
    get_agent_name_by_id,
    glob,
    limiter,
    orchestrator,
    timedelta,
)

# Round-2 split homes (packages/dashboard/docs/gui_split_map.md). gui.controller is
# imported after the line above on purpose: crewai_web_gui.py loads it mid-file, and
# that is the import site that must stay first.
from zyg_dashboard.gui.controller import _ControlPlaneUnavailable  # noqa: E402
from zyg_dashboard.gui.telemetry import (  # noqa: E402
    API_ADAPTER_AVAILABLE,
    _backend_debug,
    _get_gpu_bar_mapping,
    get_active_schedule,
    get_schedule_requests,
    submit_schedule_request,
)
from zyg_dashboard.gui.timeutil import _ams_now  # noqa: E402
from zyg_dashboard.gui.zero_store import block_spectator_mutation  # noqa: E402

_zyg_log = _zyg_logging.getLogger(__name__)


_FLAGGED_JSON = os.path.join(os.path.dirname(__file__), 'Flagged.json')


@bp.route('/api/flagged/save', methods=['POST'])
def save_flagged_element():
    """Save a flagged element to Flagged.json (Command Center flag element)."""
    try:
        data = request.get_json() or {}
        entry = {
            'id': data.get('id', ''),
            'tag': data.get('tag', ''),
            'className': data.get('className', ''),
            'html': data.get('html', '')[:500],
            'timestamp': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
        }
        flagged = []
        if os.path.exists(_FLAGGED_JSON):
            with open(_FLAGGED_JSON, 'r', encoding='utf-8') as f:
                flagged = json.load(f)
        if not isinstance(flagged, list):
            flagged = []
        flagged.append(entry)
        with open(_FLAGGED_JSON, 'w', encoding='utf-8') as f:
            json.dump(flagged, f, indent=2)
        return jsonify({'status': 'ok'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500


@bp.route('/api/restart_dashboard', methods=['POST'])
def restart_dashboard():
    r = block_spectator_mutation()
    if r is not None:
        return r

    def do_restart():
        import time

        time.sleep(1)
        # Exit with code 100 to signal restart
        os._exit(100)

    threading.Thread(target=do_restart).start()
    return jsonify({'status': 'restarting'})


@bp.route('/api/timeline/24h')
def get_24h_timeline():
    _backend_debug('/api/timeline/24h called')
    data = orchestrator.get_combined_timeline_data('24h')
    date = data.get('date')
    entries = data.get('entries', [])
    models = data.get('models', [])
    model_agent_counts = data.get('model_agent_counts', {})
    _backend_debug(f'/api/timeline/24h date: {date} entries: {len(entries)} models: {len(models)}')
    return jsonify({'date': date, 'entries': entries, 'models': models, 'model_agent_counts': model_agent_counts})


# 2026-07-17 modularization: removed dead /api/timeline/{7d,28d,1y,history} (no consumers; superseded
# by /api/schedule/* on 2026-07-15)


def normalize_model_name(name):
    """Normalize model names for robust matching."""
    if not name:
        return ''
    # Remove underscores, dashes, spaces, dots, and lowercase everything
    return ''.join(e for e in name if e.isalnum()).lower()


@bp.route('/api/timeline/add_entry', methods=['POST'])
def add_entry_timeline():
    entry = request.json.get('entry', {})
    date = request.json.get('date', None)

    _backend_debug(f'/api/timeline/add_entry called date={date} entry keys={list(entry.keys()) if entry else []}')
    agent = entry.get('agent')
    model = entry.get('ai_model')
    bar_id = entry.get('bar_id')
    _backend_debug(f'Agent: {agent}, Model: {model}, Bar ID: {bar_id}')

    # Load agent specifications from the new comprehensive file
    specs_path = os.path.join(os.path.dirname(__file__), 'FULL_TASK_SPECIFICATIONS.json')
    with open(specs_path, 'r') as f:
        agent_specs = json.load(f)

    # Find the agent in the specifications
    agent_found = False
    agent_data = None
    for category in agent_specs.values():
        if isinstance(category, dict) and 'agents' in category:
            for agent_info in category['agents']:
                if agent_info.get('name') == agent:
                    agent_found = True
                    agent_data = agent_info
                    break
            if agent_found:
                break

    if not agent_found:
        _backend_debug(f'Agent {agent} not found in specifications')
        return jsonify({'success': False, 'message': f'Agent {agent} not found'}), 404

    # Check if the model is allowed for this agent
    allowed_models = agent_data.get('ai_models', [])
    norm_model = normalize_model_name(model)

    # Check if model is in allowed models (case-insensitive)
    model_allowed = any(normalize_model_name(allowed_model) == norm_model for allowed_model in allowed_models)

    if not model_allowed:
        _backend_debug(f'Model {model} not allowed for agent {agent}')
        return jsonify({'success': False, 'message': f'Model {model} not allowed for agent {agent}'}), 403

    _backend_debug(f'Validation PASSED for Agent {agent}, Model {model}')
    result = orchestrator.add_gpu_schedule_entry(entry, date)
    _backend_debug(f'Add entry result: {result}')
    return jsonify(result)


def _cpu_entries_from_control_plane(date_str, token):
    """Build entries list for CPU 24h from control plane (active + pending) so today's table persists after navigation.
    Raises _ControlPlaneUnavailable if control plane is unreachable (connection refused, etc.) so route can fall back."""

    today = date_str or _ams_now().strftime('%Y-%m-%d')
    entries = []
    # Approved/active entries
    active = get_active_schedule('cpu', token=token)
    if active.get('status') == 0:
        raise _ControlPlaneUnavailable(active.get('error', 'Control plane unreachable'))
    if not active.get('error'):
        want_date = date_str or today
        for e in active.get('entries') or []:
            payload = e.get('payload') or {}
            ent_date = payload.get('date') or today
            if ent_date != want_date:
                continue
            entries.append(
                {
                    'id': e.get('id'),
                    'agent': payload.get('agent') or payload.get('agent_id') or e.get('submitted_by'),
                    'date': ent_date,
                    'start_time': payload.get('start_time', ''),
                    'end_time': payload.get('end_time', ''),
                    'end_date': payload.get('end_date'),
                    'priority': payload.get('priority', ''),
                    'status': 'approved',
                }
            )
    # Pending schedule requests (so they show in today's table and persist after navigate)
    reqs = get_schedule_requests(token=token, status_filter='pending')
    if reqs.get('status') == 0:
        raise _ControlPlaneUnavailable(reqs.get('error', 'Control plane unreachable'))
    if not reqs.get('error'):
        for r in reqs.get('items') or []:
            payload = r.get('payload') or {}
            if (payload.get('scope') or '').lower() != 'cpu':
                continue
            req_date = payload.get('date') or today
            if req_date != (date_str or today):
                continue
            entries.append(
                {
                    'id': r.get('id'),
                    'agent': payload.get('agent') or payload.get('agent_id') or r.get('submitted_by'),
                    'date': req_date,
                    'start_time': payload.get('start_time', ''),
                    'end_time': payload.get('end_time', ''),
                    'end_date': payload.get('end_date'),
                    'priority': payload.get('priority', ''),
                    'status': 'pending',
                }
            )
    return entries


@bp.route('/api/cpu/timeline/24h')
def cpu_timeline_24h():
    _backend_debug('/api/cpu/timeline/24h called')
    date = request.args.get('date')
    token = session.get('api_token')
    if API_ADAPTER_AVAILABLE:
        try:
            entries = _cpu_entries_from_control_plane(date, token)
            data = {'entries': entries}
            return jsonify(data)
        except _ControlPlaneUnavailable as e:
            _backend_debug(f'Control plane unreachable for CPU 24h, using orchestrator: {e}')
        except Exception as e:
            _backend_debug(f'Control plane error for CPU 24h, using orchestrator: {e}')
    data = orchestrator.get_cpu_timeline_data('24h', date=date)
    for entry in data.get('entries', []):
        if 'agent_id' in entry:
            entry['agent'] = get_agent_name_by_id(entry['agent_id'])
    _backend_debug(f'CPU 24h data keys: {list(data.keys())}')
    return jsonify(data)


# 2026-07-17 modularization: removed dead /api/cpu/timeline/{7d,28d,1y,history} (superseded by /api/schedule/*)


@bp.route('/api/cpu/timeline/add_entry', methods=['POST'])
@limiter.limit('60/hour')
def add_entry_cpu_timeline():
    """Mutations only via control plane. No disk fallback — fail closed."""
    if not API_ADAPTER_AVAILABLE:
        return jsonify({'success': False, 'message': 'Control plane required; set CONTROL_PLANE_API_URL'}), 503
    entry = request.json or {}
    if not entry.get('agent') and not entry.get('agent_id'):
        return jsonify({'success': False, 'message': 'Missing required field: agent'}), 400
    if not entry.get('ai_model'):
        return jsonify({'success': False, 'message': 'Missing required field: ai_model'}), 400
    date = entry.get('date', _ams_now().strftime('%Y-%m-%d'))
    if 'agent_id' in entry and 'agent' not in entry:
        entry['agent'] = get_agent_name_by_id(entry['agent_id'])
    token = session.get('api_token')
    payload = {'action': 'CREATE', 'scope': 'cpu', 'date': date, **{k: v for k, v in entry.items() if k != 'date'}}
    result = submit_schedule_request(payload, actor_type='user', token=token, action='CREATE')
    if result.get('error'):
        status_code = result.get('status', 500)
        if status_code == 0:
            status_code = 503
        msg = result.get('error', 'Control plane error')
        if status_code == 503:
            msg = (
                msg
                if 'port 8000' in msg or 'running' in msg
                else 'Control plane is not running. Start the FastAPI server on port 8000 to submit entries.'
            )
        return jsonify({'success': False, 'message': msg}), status_code
    return jsonify({'success': True, 'message': 'Schedule request submitted', 'request_id': result.get('id')})


@bp.route('/api/cpu/timeline/delete_entry', methods=['POST'])
@limiter.limit('60/hour')
def delete_entry_cpu_timeline():
    """Delete as schedule request. No disk fallback — fail closed."""
    if not API_ADAPTER_AVAILABLE:
        return jsonify({'success': False, 'message': 'Control plane required; set CONTROL_PLANE_API_URL'}), 503
    data = request.json or {}
    entry_id = data.get('id')
    date = data.get('date')
    if not entry_id:
        return jsonify({'success': False, 'message': 'Missing entry ID'}), 400
    token = session.get('api_token')
    payload = {'action': 'DELETE', 'target_entry_id': entry_id, 'date': date, 'scope': 'cpu'}
    result = submit_schedule_request(payload, actor_type='user', token=token, action='DELETE', target_entry_id=entry_id)
    if result.get('error'):
        status_code = result.get('status', 500)
        if status_code == 0:
            status_code = 503
        return jsonify({'success': False, 'message': result.get('error', 'Control plane error')}), status_code
    return jsonify({'success': True, 'message': 'Delete schedule request submitted', 'request_id': result.get('id')})


# GPU schedule endpoints
@bp.route('/api/gpu/timeline/24h')
def gpu_timeline_24h():
    _backend_debug('/api/gpu/timeline/24h called')
    date = request.args.get('date')
    _backend_debug(f'/api/gpu/timeline/24h date={date}')
    data = orchestrator.get_gpu_timeline_data('24h', date=date)
    _backend_debug(f'/api/gpu/timeline/24h orchestrator returned keys: {list(data.keys()) if data else []}')
    # Patch: add model_name to each entry
    model_ids = _get_gpu_models()
    for entry in data.get('entries', []):
        model_id = str(entry.get('ai_model', ''))
        entry['model_name'] = model_ids.get(model_id, {}).get('name', model_id)
    # Load model usage counts
    usage_counts_path = os.path.join(os.path.dirname(__file__), 'model_usage_counts.json')
    if os.path.exists(usage_counts_path):
        with open(usage_counts_path, 'r', encoding='utf-8') as f:
            model_usage_counts = json.load(f)
        data['model_usage_counts'] = model_usage_counts
    else:
        data['model_usage_counts'] = {}
    _backend_debug(f'GPU 24h data keys: {list(data.keys())}')
    return jsonify(data)


# 2026-07-17 modularization: removed dead /api/gpu/timeline/{7d,28d,1y,history} (superseded by /api/schedule/*)


@bp.route('/api/gpu/timeline/add_entry', methods=['POST'])
@limiter.limit('60/hour')
def add_gpu_timeline_entry():
    entry = request.get_json()
    _backend_debug(f'/api/gpu/timeline/add_entry entry date={entry.get("date")}')
    date = entry.get('date')
    model_id = entry.get('ai_model')
    agent = entry.get('agent')
    _backend_debug(f'Model ID: {model_id}, Agent: {agent}')
    model_ids = _get_gpu_models()
    _backend_debug(f'model_id in model_ids: {str(model_id) in model_ids}')
    if not model_id or str(model_id) not in model_ids:
        return jsonify({'success': False, 'message': f'Invalid AI model: {model_id}'}), 400
    agent_mapping = _get_gpu_bar_mapping()

    _backend_debug(f'Agent: {agent}, in mapping: {agent in agent_mapping}')

    if agent not in agent_mapping:
        return jsonify({'success': False, 'message': f'Agent {agent} not found'}), 404

    agent_data = agent_mapping[agent]
    allowed_model_ids = set()
    for model_info in agent_data.get('models', []):
        if isinstance(model_info, dict) and 'model' in model_info:
            allowed_model_ids.add(str(model_info['model']))
        elif isinstance(model_info, str):
            allowed_model_ids.add(str(model_info))

    _backend_debug(f'Allowed model IDs for agent: {allowed_model_ids}, check: {str(model_id) in allowed_model_ids}')

    if str(model_id) not in allowed_model_ids:
        return jsonify({'success': False, 'message': f'Model ID {model_id} not allowed for agent {agent}'}), 403
    entry['ai_model'] = str(model_id)
    # Mutations only via control plane. No legacy fallback — fail closed.
    if not API_ADAPTER_AVAILABLE:
        return jsonify({'success': False, 'message': 'Control plane required; set CONTROL_PLANE_API_URL'}), 503
    token = session.get('api_token')
    payload = {
        'action': 'CREATE',
        'date': date,
        'ai_model': entry.get('ai_model'),
        'agent': entry.get('agent'),
        'entry_id': entry.get('id'),
        'duration_hours': entry.get('duration_hours'),
        'start_time': entry.get('start_time'),
        'scope': 'gpu',
    }
    if entry.get('vram_required_mb') is not None:
        payload['vram_required_mb'] = entry['vram_required_mb']
    if entry.get('vram_allowed_mb') is not None:
        payload['vram_allowed_mb'] = entry['vram_allowed_mb']
    result = submit_schedule_request(payload, actor_type='user', token=token, action='CREATE')
    if result.get('error'):
        status_code = result.get('status', 500)
        if status_code == 0:
            status_code = 503  # adapter unreachable
        return jsonify({'success': False, 'message': result.get('error', 'Control plane error')}), status_code
    return jsonify(
        {'success': True, 'entry': entry, 'message': 'Schedule request submitted', 'request_id': result.get('id')}
    )


@bp.route('/api/gpu/timeline/delete_entry', methods=['POST'])
@limiter.limit('60/hour')
def delete_gpu_schedule_entry():
    """Delete as schedule request (same approval flow). No disk write from Flask. Fail closed if control plane down."""
    if not API_ADAPTER_AVAILABLE:
        return jsonify({'success': False, 'message': 'Control plane required; set CONTROL_PLANE_API_URL'}), 503
    data = request.json or {}
    entry_id = data.get('id')
    date = data.get('date')
    if not entry_id:
        return jsonify({'success': False, 'message': 'Missing entry ID'}), 400
    token = session.get('api_token')
    payload = {'action': 'DELETE', 'target_entry_id': entry_id, 'date': date, 'scope': 'gpu'}
    result = submit_schedule_request(payload, actor_type='user', token=token, action='DELETE', target_entry_id=entry_id)
    if result.get('error'):
        status_code = result.get('status', 500)
        if status_code == 0:
            status_code = 503
        return jsonify({'success': False, 'message': result.get('error', 'Control plane error')}), status_code
    return jsonify({'success': True, 'message': 'Delete schedule request submitted', 'request_id': result.get('id')})


# Read-only: nothing in this module writes history any more (see
# save_today_gpu_schedule below — the control plane owns it), so the directory is
# never created here. api_history globs it; a missing directory globs to nothing.
HISTORY_DIR = os.path.join(os.path.dirname(__file__), 'Schedule', 'history')


# --- DAILY HISTORY SAVE SCHEDULER ---
# Disabled: no disk write from Flask. Control plane owns schedule/history.
def save_today_gpu_schedule():
    pass  # no-op


def schedule_daily_save():
    def run():
        while True:
            now = _ams_now()
            # Calculate seconds until 23:59:00 Amsterdam time
            next_save = now.replace(hour=23, minute=59, second=0, microsecond=0)
            if next_save < now:
                next_save += timedelta(days=1)
            wait_seconds = (next_save - now).total_seconds()
            time.sleep(wait_seconds)
            save_today_gpu_schedule()

    t = threading.Thread(target=run, daemon=True)
    t.start()


schedule_daily_save()
atexit.register(save_today_gpu_schedule)


# --- HISTORY API ENDPOINT ---
@bp.route('/api/history')
def api_history():
    month = request.args.get('month')  # format YYYY-MM
    if not month:
        return jsonify({'entries': [], 'months': []})
    # Find all files for the month
    pattern = os.path.join(HISTORY_DIR, f'{month}-*.json')
    files = sorted(glob.glob(pattern))
    all_entries = []
    for fpath in files:
        try:
            with open(fpath, 'r', encoding='utf-8') as f:
                data = json.load(f)
                all_entries.extend(data.get('entries', []))
        except (OSError, json.JSONDecodeError) as e:
            _zyg_log.warning('history file %s unreadable, continuing without its entries: %s', fpath, e)
            continue
    return jsonify({'entries': all_entries})


# Add GPU timeline generation route
@bp.route('/api/gpu/timeline/generate', methods=['GET'])
def generate_gpu_timeline():
    """Generate GPU timeline visualization"""
    try:
        date = request.args.get('date', _ams_now().strftime('%Y-%m-%d'))

        # Initialize timeline with GPU schedule file
        import importlib.util

        spec = importlib.util.spec_from_file_location('timeline_24h', 'Schedule/24_hour_timeline.py')
        timeline_24h = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(timeline_24h)
        Timeline24Hour = timeline_24h.Timeline24Hour
        timeline = Timeline24Hour('Schedule/schedule_data_GPU.json')

        # Generate the visualization
        output_file = f'Schedule/gpu_24_hour_timeline_{date}.png'
        timeline.generate_gpu_timeline_visualization(date, output_file)

        return jsonify({'success': True, 'message': f'GPU timeline generated for {date}', 'file': output_file})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@bp.route('/api/gpu/timeline/image/<date>')
def get_gpu_timeline_image(date):
    """Serve the generated GPU timeline image"""
    try:
        file_path = f'Schedule/gpu_24_hour_timeline_{date}.png'
        if os.path.exists(file_path):
            return send_from_directory('Schedule', f'gpu_24_hour_timeline_{date}.png', mimetype='image/png')
        else:
            return jsonify({'error': 'Timeline image not found'}), 404
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# (2026-07-17 fix: dashboard_config import block moved back to crewai_web_gui.py — it feeds bp_themes_users/bp_safety and main)
