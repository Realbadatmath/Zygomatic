# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Departments, the GPU schedule, the agent config files, the logbook, the prompt
log and the model-bar mappings — bp_agents_api part 2."""

from .agents import (
    API_ADAPTER_AVAILABLE,
    _get_cpu_bar_mapping,
    _get_gpu_bar_mapping,
    _resolve_ai_models_display,
    _runtime_path,
    _zero_load_config,
    bp,
    controller,
    get_active_schedule,
    json,
    jsonify,
    request,
    session,
    time,
)


@bp.route('/api/departments')
def get_departments():
    """API endpoint to get all departments"""
    departments = set()
    for config in controller.agent_configs.values():
        if config.get('department'):
            departments.add(config['department'])
    return jsonify(list(departments))


@bp.route('/api/gpu/schedule')
def get_gpu_schedule():
    """GPU Schedule / Timeline view: active schedule (approved+activated), not requests. Fail closed if control plane unreachable."""
    token = session.get('api_token')
    if API_ADAPTER_AVAILABLE:
        data = get_active_schedule('gpu', token=token)
        if data.get('error'):
            status_code = data.get('status', 503)
            if status_code == 0:
                status_code = 503  # unreachable
            return jsonify({'error': data.get('error', 'Control plane unavailable')}), status_code
        entries = data.get('entries') or []
        gpu_data = {'total_allocated': 0, 'allocations': {}}
        for e in entries:
            payload = e.get('payload') or {}
            agent_id = payload.get('agent') or payload.get('agent_id') or e.get('submitted_by', '')
            if agent_id:
                gpu_data['allocations'][agent_id] = {
                    'gpu_percent': payload.get('max_gpu_percent', 0),
                    'duration_hours': payload.get('duration_hours', 0) or payload.get('estimated_duration_hours', 0),
                    'start_time': time.time() * 1000,
                }
                gpu_data['total_allocated'] += payload.get('max_gpu_percent', 0)
        return jsonify(gpu_data)
    # No adapter: must not show stale JSON. Fail closed.
    return jsonify({'error': 'Control plane required; set CONTROL_PLANE_API_URL'}), 503


@bp.route('/api/gpu/release', methods=['POST'])
def release_gpu():
    """API endpoint to release GPU allocation for an agent"""
    data = request.json
    agent_name = data.get('agent', '')

    # Mock GPU release - in a real implementation, this would update GPU allocation
    return jsonify({'success': True, 'message': f'GPU released for {agent_name}'})


@bp.route('/api/agents/config')
def get_agents_config():
    """Return agent configs (role, goal, backstory, tasks, workflow, etc.) for enriching mapping-based agent lists. Includes Zero from agent_zero.json."""
    configs = {}
    for name, cfg in controller.agent_configs.items():
        ai_models = cfg.get('ai_models', [])
        configs[name] = {
            'id': cfg.get('id'),
            'role': cfg.get('role', ''),
            'goal': cfg.get('goal', ''),
            'backstory': cfg.get('backstory', ''),
            'primary_task': cfg.get('primary_task', ''),
            'department': cfg.get('department', ''),
            'tier': cfg.get('tier'),
            'tasks': cfg.get('tasks', []),
            'production_workflow': cfg.get('production_workflow', []),
            'performance_metrics': cfg.get('performance_metrics', []),
            'ai_models': ai_models,
            'ai_models_display': _resolve_ai_models_display(ai_models),
            'capabilities': cfg.get('capabilities', cfg.get('skills', [])),
            'permissions': cfg.get('permissions', cfg.get('capabilities', cfg.get('skills', []))),
            'collaboration_protocols': cfg.get('collaboration_protocols', []),
            'tools': cfg.get('tools', []),
        }
    # Add Zero from agent_zero.json (not in agents.json)
    zcfg = _zero_load_config()
    llms = zcfg.get('llms') or {}
    configs['Zero'] = {
        'id': zcfg.get('id', 'zero'),
        'role': zcfg.get('role', ''),
        'goal': zcfg.get('goal', ''),
        'backstory': zcfg.get('backstory', ''),
        'primary_task': zcfg.get('goal', ''),
        'department': zcfg.get('department', 'System'),
        'tier': zcfg.get('tier', 0),
        'tasks': [],
        'production_workflow': [],
        'performance_metrics': [],
        'ai_models': list(llms.values()) if isinstance(llms, dict) else [],
        'ai_models_display': list(llms.values()) if isinstance(llms, dict) else [],
        'capabilities': zcfg.get('capabilities', []),
        'permissions': zcfg.get('capabilities', []),
        'collaboration_protocols': [],
    }
    return jsonify(configs)


@bp.route('/api/agents/config/<path:agent_name>')
def get_agent_config_by_name(agent_name):
    """Return full config for a single agent by name. Used by Agent Overview dialog. Zero comes from agent_zero.json."""
    if (agent_name or '').strip().lower() in ('zero', 'agent zero'):
        cfg = _zero_load_config()
        llms = cfg.get('llms') or {}
        return jsonify(
            {
                'id': cfg.get('id', 'zero'),
                'name': cfg.get('name', 'Zero'),
                'role': cfg.get('role', ''),
                'goal': cfg.get('goal', ''),
                'backstory': cfg.get('backstory', ''),
                'primary_task': cfg.get('goal', ''),
                'department': cfg.get('department', 'System'),
                'tier': cfg.get('tier', 0),
                'tasks': [],
                'production_workflow': [],
                'performance_metrics': [],
                'ai_models': list(llms.values()) if isinstance(llms, dict) else [],
                'ai_models_display': list(llms.values()) if isinstance(llms, dict) else [],
                'capabilities': cfg.get('capabilities', []),
                'llms': llms,
            }
        )
    cfg = controller.agent_configs.get(agent_name)
    resolved_name = agent_name
    if not cfg:
        for name, c in controller.agent_configs.items():
            if str(c.get('id', '')) == str(agent_name):
                cfg = c
                resolved_name = name
                break
    if not cfg:
        return jsonify({'error': 'Agent not found'}), 404
    ai_models = cfg.get('ai_models', [])
    result = {
        'id': cfg.get('id'),
        'name': resolved_name,
        'role': cfg.get('role', ''),
        'goal': cfg.get('goal', ''),
        'backstory': cfg.get('backstory', ''),
        'primary_task': cfg.get('primary_task', ''),
        'department': cfg.get('department', ''),
        'tier': cfg.get('tier'),
        'tasks': cfg.get('tasks', []),
        'production_workflow': cfg.get('production_workflow', []),
        'performance_metrics': cfg.get('performance_metrics', []),
        'ai_models': ai_models,
        'ai_models_display': _resolve_ai_models_display(ai_models),
        'capabilities': cfg.get('capabilities', cfg.get('skills', [])),
        'permissions': cfg.get('permissions', cfg.get('capabilities', cfg.get('skills', []))),
        'collaboration_protocols': cfg.get('collaboration_protocols', []),
        'supervisor': cfg.get('supervisor'),
        'subordinates': cfg.get('subordinates', []),
        'tools': cfg.get('tools', []),
        'skills': cfg.get('skills', []),
    }
    return jsonify(result)


@bp.route('/api/agents/<path:agent_name>/logbook')
def get_agent_logbook(agent_name):
    """Return pipeline runs where this agent participated, from the logbook."""
    log_path = _runtime_path('clipfarm_processing_log.json')
    try:
        with open(log_path) as f:
            all_entries = json.load(f)
    except Exception:
        all_entries = []

    name_lower = agent_name.lower()
    relevant = [e for e in all_entries if name_lower in (e.get('agent') or '').lower()]

    runs = {}
    for e in relevant:
        pid = e.get('pipeline_id', 'unknown')
        if pid not in runs:
            runs[pid] = {
                'pipeline_id': pid,
                'entries': [],
                'has_error': False,
                'first_ts': e.get('timestamp', ''),
                'last_ts': e.get('timestamp', ''),
            }
        runs[pid]['entries'].append(e)
        if e.get('level') == 'ERROR':
            runs[pid]['has_error'] = True
        if e.get('timestamp', '') < runs[pid]['first_ts']:
            runs[pid]['first_ts'] = e.get('timestamp', '')
        if e.get('timestamp', '') > runs[pid]['last_ts']:
            runs[pid]['last_ts'] = e.get('timestamp', '')

    run_list = sorted(runs.values(), key=lambda r: r['last_ts'], reverse=True)
    return jsonify({'runs': run_list})


@bp.route('/api/prompt_log')
def api_prompt_log():
    """Return all logged AI prompts (FLUX images, Wan video, scripts, Claude/GPT/Ollama).
    Optional query params: pipeline_id, type, direction (sent/received/template), llm, limit (default 200)."""
    log_path = _runtime_path('prompt_log.json')
    try:
        with open(log_path) as _pf:
            entries = json.load(_pf)
    except Exception:
        entries = []
    pid_filter = request.args.get('pipeline_id', '').strip()
    type_filter = request.args.get('type', '').strip()
    dir_filter = request.args.get('direction', '').strip()
    llm_filter = request.args.get('llm', '').strip()
    limit = int(request.args.get('limit', 500))
    if pid_filter:
        entries = [e for e in entries if e.get('pipeline_id') == pid_filter]
    if type_filter:
        entries = [e for e in entries if e.get('type') == type_filter]
    if dir_filter:
        entries = [e for e in entries if e.get('direction') == dir_filter]
    if llm_filter:
        entries = [e for e in entries if e.get('llm') == llm_filter]
    entries = entries[-limit:]
    entries.reverse()  # newest first
    # Build summary stats
    sent_count = sum(1 for e in entries if e.get('direction') == 'sent')
    received_count = sum(1 for e in entries if e.get('direction') == 'received')
    template_count = sum(1 for e in entries if e.get('direction') == 'template')
    return jsonify(
        {
            'count': len(entries),
            'sent_count': sent_count,
            'received_count': received_count,
            'template_count': template_count,
            'entries': entries,
        }
    )


@bp.route('/api/agent_model_bar_mapping')
def get_agent_model_bar_mapping():
    try:
        return jsonify(_get_gpu_bar_mapping())
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@bp.route('/api/cpu/agent_model_bar_mapping')
def get_cpu_agent_model_bar_mapping():
    try:
        return jsonify(_get_cpu_bar_mapping())
    except Exception as e:
        return jsonify({'error': str(e)}), 500
