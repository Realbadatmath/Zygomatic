# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Workflow-step agents, the active roster, the audit and the remaining catalogue
endpoints — bp_agents_api part 3."""

from .agents import (
    _CLIPFARM_STAGES,
    _get_all_tools,
    _load_canonical_json,
    _resolve_ai_models_display,
    _workflow_jobs,
    _zyg_log,
    apply_cors,
    bp,
    controller,
    get_model_name_by_id,
    html_module,
    json,
    jsonify,
    limiter,
    os,
    request,
)

# zyg_dashboard/, the directory the single-file bp_agents_api.py lived in: four data paths
# below were written against dirname(__file__) there, and this package is one level deeper.
_PKG_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@bp.route('/api/workflow/steps/agents')
def get_workflow_step_agents():
    """Return agents for a workflow step. Uses Feedback & Workflow stage/role mappings + production_workflow."""
    step_label = request.args.get('step', '').strip()
    chart = (request.args.get('chart') or '').strip()
    if not step_label:
        return jsonify({'agents': [], 'llms': []})
    step_lower = step_label.lower()
    agents_found = []
    llms_seen = set()
    tools_seen = []
    seen_names = set()

    fw = _load_feedback_workflow_data()
    agent_name_exact = fw.get('agent_name_exact', {})
    step_exact = fw.get('step_exact', {})
    step_exact_by_chart = fw.get('step_exact_by_chart', {})
    chart_map = step_exact_by_chart.get(chart, {}) if chart else {}
    role_to_agent = fw.get('role_to_agent', {})
    stage_agents = fw.get('stage_agents', {})

    # 0) Exact step match: one agent per workflow box (prevents multiple agents)
    # 0a) agent_name_exact: maps workflow box agentName (e.g. "2D FX Agent") -> config name (e.g. "2D-Effects-Agent")
    exact_config = None
    if agent_name_exact and step_label in agent_name_exact:
        resolved = agent_name_exact[step_label]
        if resolved in controller.agent_configs:
            exact_config = resolved
    if not exact_config and step_label in controller.agent_configs:
        exact_config = step_label
    if not exact_config:
        exact_config = chart_map.get(step_label)
    if not exact_config:
        for k, v in chart_map.items():
            if k.strip().lower() == step_lower:
                exact_config = v
                break
    if not exact_config:
        exact_config = step_exact.get(step_label)
    if not exact_config:
        for k, v in step_exact.items():
            if k.strip().lower() == step_lower:
                exact_config = v
                break
    if not exact_config and chart:
        stripped = step_label
        for prefix in ('2D ', '3D ', 'AFFIL-CLIPFARM ', 'Distribution ', 'Maintenance '):
            if stripped.startswith(prefix):
                stripped = stripped[len(prefix) :].strip()
                break
        exact_config = chart_map.get(stripped) or step_exact.get(stripped)
    if exact_config and exact_config in controller.agent_configs:
        cfg = controller.agent_configs[exact_config]
        ai_models = cfg.get('ai_models') or []
        agents_found = [
            {
                'name': exact_config,
                'id': cfg.get('id', exact_config),
                'role': cfg.get('role', ''),
                'ai_models': ai_models,
                'ai_models_display': _resolve_ai_models_display(ai_models),
            }
        ]
        llms_seen = {get_model_name_by_id(str(m).strip()) for m in ai_models if m}
        tools_seen = list(cfg.get('tools') or [])
        seen_names = {exact_config}
    else:
        # 1) Match by role: "Translate Agent" -> step "Translate" or "Translation"
        for role_name, config_name in role_to_agent.items():
            role_lower = role_name.lower()
            if step_lower in role_lower or role_lower in step_lower:
                if config_name in controller.agent_configs and config_name not in seen_names:
                    cfg = controller.agent_configs[config_name]
                    ai_models = cfg.get('ai_models') or []
                    agents_found.append(
                        {
                            'name': config_name,
                            'id': cfg.get('id', config_name),
                            'role': cfg.get('role', ''),
                            'ai_models': ai_models,
                            'ai_models_display': _resolve_ai_models_display(ai_models),
                        }
                    )
                    seen_names.add(config_name)
                    for m in ai_models:
                        if m:
                            llms_seen.add(get_model_name_by_id(str(m).strip()))
                    for t in cfg.get('tools') or []:
                        if t and t not in tools_seen:
                            tools_seen.append(t)

        # 2) Match by stage document key (e.g. "Distribution. Stage 4. Languages")
        for stage_key, config_names in stage_agents.items():
            stage_lower = stage_key.lower()
            if step_lower in stage_lower or any(step_lower in cn.lower() for cn in config_names):
                for config_name in config_names:
                    if config_name in controller.agent_configs and config_name not in seen_names:
                        cfg = controller.agent_configs[config_name]
                        ai_models = cfg.get('ai_models') or []
                        agents_found.append(
                            {
                                'name': config_name,
                                'id': cfg.get('id', config_name),
                                'role': cfg.get('role', ''),
                                'ai_models': ai_models,
                                'ai_models_display': _resolve_ai_models_display(ai_models),
                            }
                        )
                        seen_names.add(config_name)
                        for m in ai_models:
                            if m:
                                llms_seen.add(get_model_name_by_id(str(m).strip()))
                        for t in cfg.get('tools') or []:
                            if t and t not in tools_seen:
                                tools_seen.append(t)

        # 3) Fallback: production_workflow step match
        for name, cfg in controller.agent_configs.items():
            if name in seen_names:
                continue
            workflow = cfg.get('production_workflow') or []
            if not isinstance(workflow, list):
                continue
            for wstep in workflow:
                ws = (wstep or '').strip()
                if not ws:
                    continue
                if step_lower in ws.lower() or ws.lower() in step_lower:
                    ai_models = cfg.get('ai_models') or []
                    agents_found.append(
                        {
                            'name': name,
                            'id': cfg.get('id', name),
                            'role': cfg.get('role', ''),
                            'ai_models': ai_models,
                            'ai_models_display': _resolve_ai_models_display(ai_models),
                        }
                    )
                    seen_names.add(name)
                    for m in cfg.get('ai_models') or []:
                        if m:
                            llms_seen.add(get_model_name_by_id(str(m).strip()))
                    for t in cfg.get('tools') or []:
                        if t and t not in tools_seen:
                            tools_seen.append(t)
                    break

    def _escape_html(s):
        return html_module.escape(str(s)) if s is not None else ''

    # Build function description from assigned agents (role, goal, primary_task, tasks)
    function_parts = []
    for a in agents_found:
        cfg = controller.agent_configs.get(a['name'])
        if not cfg:
            continue
        role = (cfg.get('role') or '').strip()
        goal = (cfg.get('goal') or '').strip()
        primary = (cfg.get('primary_task') or '').strip()
        tasks = cfg.get('tasks') or []
        if role:
            function_parts.append('<p><strong>' + _escape_html(a['name']) + '</strong>: ' + _escape_html(role) + '</p>')
        if goal and goal != role:
            function_parts.append('<p>' + _escape_html(goal) + '</p>')
        if primary:
            function_parts.append('<p><em>Primary task:</em> ' + _escape_html(primary) + '</p>')
        if tasks and isinstance(tasks, list):
            task_list = ''.join('<li>' + _escape_html(str(t)) + '</li>' for t in tasks[:5] if t)
            if task_list:
                function_parts.append(
                    '<p><strong>Key tasks:</strong><ul style="margin:0.2em 0 0 1.2em;">' + task_list + '</ul></p>'
                )
    function_html = (
        ''.join(function_parts)
        if function_parts
        else '<p>This workflow step describes part of the agent workflow process. Function details can be configured per deployment.</p>'
    )

    # Enrich with orchestration permissions: role_type, is_execution_only, orchestrated_by
    orch_path = os.path.join(_PKG_DIR, 'orchestration_permissions.json')
    orch = {}
    try:
        with open(orch_path, 'r', encoding='utf-8') as f:
            orch = json.load(f)
    except (OSError, ValueError) as _exc:
        _zyg_log.warning('orchestration permissions unreadable, falling back to default roles: %s', _exc)
    agents_config = orch.get('agents', {})
    default_role = orch.get('default_role', 'Executor')
    orchestrators = [k for k, v in agents_config.items() if v.get('role_type') == 'Orchestrator']
    for a in agents_found:
        perm = agents_config.get(a['name'], {})
        a['role_type'] = perm.get('role_type', default_role)
        a['allowed_actions'] = perm.get(
            'allowed_actions', ['Claim/Heartbeat/Complete'] if a['role_type'] == 'Executor' else []
        )
        a['is_execution_only'] = a['role_type'] == 'Executor'
    # Orchestrated by: infer from chart/step
    orchestrated_by = None
    step_trimmed = (step_label or '').strip()
    dist_orch = fw.get('distribution_orchestrated_by', {}).get('by_step', {}) if fw else {}
    # Scheduling Agent is unified across all charts and orchestrated by Zero
    if step_trimmed == 'Scheduling Agent':
        orchestrated_by = 'Zero'
    # 2D/3D overseers (display labels + agent names + config names) are always orchestrated by Zero
    overseer_labels = {
        'Production Overseer',
        'Media Overseer',
        '2D Pipeline Overseer',
        '2D Output Overseer',
        '3D Pipeline Overseer',
        '3D Output Overseer',
        '2D-Pipeline-Overseer',
        '2D-Output-Overseer',
        '3D-Pipeline-Overseer',
        '3D-Output-Overseer',
    }
    is_2d_3d_overseer = step_trimmed in overseer_labels and (
        not chart or '2d' in (chart or '').lower() or '3d' in (chart or '').lower()
    )
    # Clipfarm: Clip Farm Overseer orchestrated by Zero; all other CLIPFARM agents orchestrated by Clip Farm Overseer
    clipfarm_overseer_labels = {
        'Clip Farm Overseer',
        'CLIPFARM Clipfarm Overseer Agent',
        'CLIPFARM-Clipfarm-Overseer-Agent',
        'AFFIL-CLIPFARM Clipfarm Orchestrator Agent',
    }
    is_clipfarm_chart = chart and 'clipfarm' in (chart or '').lower()
    is_clipfarm_overseer = step_trimmed in clipfarm_overseer_labels or (
        step_trimmed and ('Clipfarm Overseer' in step_trimmed or 'Clip Farm Overseer' in step_trimmed)
    )
    if chart and 'distribution' in chart.lower() and dist_orch and step_label in dist_orch:
        orchestrated_by = dist_orch[step_label]
    elif is_2d_3d_overseer:
        orchestrated_by = 'Zero'
    elif is_clipfarm_chart and is_clipfarm_overseer:
        orchestrated_by = 'Zero'
    elif is_clipfarm_chart and step_trimmed != 'Scheduling Agent':
        orchestrated_by = 'CLIPFARM Clip Farm Overseer'
    elif step_trimmed != 'Scheduling Agent' and chart and '2d' in chart.lower():
        orchestrated_by = (
            '2D Pipeline Overseer'
            if '2D-Pipeline-Overseer' in orchestrators
            else (orchestrators[0] if orchestrators else None)
        )
    elif step_trimmed != 'Scheduling Agent' and chart and '3d' in chart.lower():
        orchestrated_by = (
            '3D Pipeline Overseer'
            if '3D-Pipeline-Overseer' in orchestrators
            else (orchestrators[0] if orchestrators else None)
        )
    elif step_trimmed != 'Scheduling Agent':
        orchestrated_by = orchestrators[0] if orchestrators else None

    resp = jsonify(
        {
            'agents': agents_found,
            'llms': sorted(list(llms_seen)),
            'tools': tools_seen,
            'function': function_html,
            'is_execution_only': any(a.get('is_execution_only') for a in agents_found),
            'orchestrated_by': orchestrated_by,
        }
    )
    return apply_cors(resp, request), 200


@bp.route('/api/agents/active')
@limiter.exempt
def get_agents_active():
    """Return agents currently executing tasks (current_tasks > 0) plus any running in active pipelines."""
    active = []
    # From pipeline stage_status
    running_pipeline_agent_ids = set()
    for job in _workflow_jobs.values():
        if job.get('status') != 'running':
            continue
        current_stage = job.get('current_stage', '')
        stage_data = job.get('stages', {}).get(current_stage, {})
        for agent_id, info in stage_data.items():
            if isinstance(info, dict) and info.get('status') == 'running':
                running_pipeline_agent_ids.add(agent_id)
    for name, config in controller.agent_configs.items():
        raw_tasks = config.get('current_tasks', 0)
        # Some agent configs carry a list of task ids here, others a plain count.
        if isinstance(raw_tasks, (list, tuple, set, dict)):
            current_tasks = len(raw_tasks)
        elif isinstance(raw_tasks, bool):
            current_tasks = int(raw_tasks)
        elif isinstance(raw_tasks, (int, float)):
            current_tasks = int(raw_tasks)
        elif isinstance(raw_tasks, str) and raw_tasks.strip().lstrip('-').isdigit():
            current_tasks = int(raw_tasks.strip())
        else:
            current_tasks = 0
        if current_tasks > 0 or name in running_pipeline_agent_ids:
            active.append(
                {
                    'id': config.get('id') or name,
                    'name': name,
                    'role': config.get('role', ''),
                    'current_tasks': current_tasks,
                    'department': config.get('department', ''),
                }
            )
    return jsonify({'active_agents': active, 'count': len(active)})


@bp.route('/api/available_models')
def available_models():
    """API endpoint to get available AI models (from Ai Models directory)"""
    models_dir = os.path.abspath(os.path.join(_PKG_DIR, '../../Ai Models'))
    if not os.path.exists(models_dir):
        return jsonify([])
    models = [d for d in os.listdir(models_dir) if os.path.isdir(os.path.join(models_dir, d))]
    return jsonify(models)


@bp.route('/api/agent_model_audit')
def agent_model_audit():
    """API endpoint to list all agents and their allowed models"""
    audit = []
    for name, allowed in controller.agent_allowed_models.items():
        audit.append({'agent': name, 'allowed_models': allowed})
    return jsonify(audit)


def _load_feedback_workflow_data():
    """Load from data/workflow.json (canonical) or feedback_workflow/step_to_agents.json."""
    w = _load_canonical_json('workflow.json', 'feedback_workflow/step_to_agents.json')
    if isinstance(w, dict) and 'step_to_agent' in w:
        return w['step_to_agent']
    return w


@bp.route('/api/workflow_box_ids')
@limiter.exempt
def get_workflow_box_ids():
    """Serve workflow_box_ids.json as an API endpoint (mirrors /static/data/workflow_box_ids.json)."""
    path = os.path.join(_PKG_DIR, 'static', 'data', 'workflow_box_ids.json')
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return jsonify(json.load(f))
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@bp.route('/api/agent_tree')
def agent_tree():
    """API endpoint to get the agent hierarchy as a tree"""
    return jsonify(controller.get_agent_tree())


@bp.route('/api/agent_network')
def agent_network():
    """API endpoint to get the agent network for Cytoscape.js"""
    return jsonify(controller.get_agent_network())


@bp.route('/api/pipeline_stages')
def pipeline_stages():
    """Return the static stage definition so the UI can render the pipeline graph."""
    return jsonify(
        [
            {
                'name': s['name'],
                'parallel': s['parallel'],
                'agents': s['agents'],
            }
            for s in _CLIPFARM_STAGES
        ]
    )


@bp.route('/api/hardware_table')
def get_hardware_table():
    """Return Hardware Table from data/models.json (canonical) or legacy files."""
    m = _load_canonical_json('models.json', 'gpu_ai_models.json')
    gpu_data = m.get('gpu', m) if isinstance(m, dict) and 'gpu' in m else m
    cpu_data = _load_canonical_json('models.json', 'cpu_ai_models.json')
    cpu_data = cpu_data.get('cpu', cpu_data) if isinstance(cpu_data, dict) and 'cpu' in cpu_data else {}
    seen_names = set()
    rows = []
    for data, schedule in [(gpu_data or {}, 'GPU'), (cpu_data or {}, 'CPU')]:
        for mid, entry in data.items() if isinstance(data, dict) else []:
            if not isinstance(entry, dict) or 'type' not in entry:
                continue
            name = entry.get('name', '')
            if name in seen_names:
                continue
            seen_names.add(name)
            rows.append(
                {
                    'id': mid,
                    'name': name,
                    'schedule': schedule,
                    'type': entry.get('type', ''),
                    'parameters': entry.get('parameters'),
                    'fp16_gb': entry.get('fp16_gb'),
                    'size_8bit_gb': entry.get('size_8bit_gb'),
                    'size_4bit_gb': entry.get('size_4bit_gb'),
                    'typical_vram': entry.get('typical_vram'),
                    'role': entry.get('role', ''),
                }
            )
    # Sort: LLMs first, then agent framework, benchmark, API, diffusion, TTS
    order = {'LLM': 0, 'agent framework': 1, 'benchmark': 2, 'API model': 3, 'diffusion': 4, 'TTS': 5}
    rows.sort(key=lambda r: (order.get(r['type'] or '', 99), r['name']))
    return jsonify({'models': rows})


@bp.route('/api/model_ids')
def get_model_ids():
    m = _load_canonical_json('models.json', 'gpu_ai_models.json')
    gpu = m.get('gpu', m) if isinstance(m, dict) and 'gpu' in m else m
    return jsonify({'model_ids': gpu or {}})


@bp.route('/api/orchestration/permissions')
def get_orchestration_permissions():
    """Return orchestration permissions (agent role_type and allowed_actions). Merges with agent_configurations so all agents appear."""
    path = os.path.join(_PKG_DIR, 'orchestration_permissions.json')
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except Exception:
        data = {'agents': {}, 'default_role': 'Executor', 'force_override': 'admin_only'}
    orch_agents = data.get('agents', {})
    default_role = data.get('default_role', 'Executor')
    # Merge with agent_configurations so all agents appear; unlisted get default_role
    for name in controller.agent_configs:
        if name not in orch_agents:
            if default_role == 'Executor':
                orch_agents[name] = {'role_type': 'Executor', 'allowed_actions': ['Claim/Heartbeat/Complete']}
            else:
                orch_agents[name] = {'role_type': default_role, 'allowed_actions': []}
    data['agents'] = orch_agents
    return jsonify(data)


@bp.route('/api/tools')
def api_tools():
    """Enumerate the real tool registry so agent tool assignments can be
    validated in the UI (tool strings must exactly match tool-class names)."""
    try:
        names = sorted(_get_all_tools().keys())
    except Exception as _te:
        return jsonify({'tools': [], 'error': str(_te)[:200]}), 500
    return jsonify({'tools': names, 'count': len(names)})
