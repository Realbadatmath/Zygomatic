# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later
"""bp_zero — task state, the remaining routes, approval auto-evaluation and the worker threads.

Moved verbatim out of bp_zero.py (original lines 1671-2028) by the 2026-10-06
modularization wave; zero logic edits.
"""

from zyg_dashboard.bp_zero.constants import (
    DOCS_DIR,
    OLLAMA_AVAILABLE,
    Ollama,
    ZERO_AUDIT_PATH,
    ZERO_TASK_STATE_PATH,
    ZYG_OLLAMA_URL,
    _APPROVAL_REQ_FILE,
    _APPROVAL_STORE_FILE,
    _ams_iso,
    _clear_pipeline_halt,
    _halt_all_pipeline_activity,
    _zero_audit_log,
    _zyg_log,
    _zyg_pkg_dir,
    bp,
    json,
    jsonify,
    limiter,
    os,
    request,
    threading,
    time,
)
from zyg_dashboard.bp_zero.topics import (
    _zero_auto_mode_set,
)
from zyg_dashboard.bp_zero.kanban import (
    _zero_auto_mode_load,
    _zero_kanban_load,
    _zero_kanban_watcher,
)

# ── re-export surface ────────────────────────────────────────────────────────
# This module inherits the pre-split top import block. `_zyg_pkg_dir` is the
# only name in it this file does not read itself; it is kept here because the
# package's modules re-import the block off each other. Declaring it is what
# makes the re-export deliberate rather than an unused import; nothing does
# ``import *`` from here, so __all__ changes no behaviour.
__all__ = [
    '_zyg_pkg_dir',
]


def _zero_read_task_state() -> dict:
    """Load persistent task memory for Zero."""
    if os.path.isfile(ZERO_TASK_STATE_PATH):
        try:
            with open(ZERO_TASK_STATE_PATH, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as _exc:
            _zyg_log.warning('%s unreadable, starting from an empty task state: %s', ZERO_TASK_STATE_PATH, _exc)
    return {'phase': None, 'open_issues': [], 'blocked': [], 'current_goal': None, 'subtasks': [], 'updated_at': None}


def _zero_write_task_state(state: dict) -> None:
    """Persist task state."""
    state['updated_at'] = _ams_iso()
    try:
        with open(ZERO_TASK_STATE_PATH, 'w', encoding='utf-8') as f:
            json.dump(state, f, indent=2)
    except Exception as _exc:
        _zyg_log.warning('task state not persisted, Zero forgets this update: %s', _exc)


@bp.route('/api/zero/stop', methods=['POST'])
def zero_stop():
    """Manual safety stop — Zero chat 'stop' command. Halts all pipeline activity."""
    summary = _halt_all_pipeline_activity('Stopped by user via Zero')
    stopped = summary['stopped_jobs']
    killed_pids = summary['killed_pids']
    n = len(stopped)
    return jsonify(
        {
            'success': True,
            'stopped_jobs': stopped,
            'killed_pids': killed_pids,
            'comfy_interrupted': summary.get('comfy_interrupted'),
            'message': (
                f'All pipeline activity halted. {n} job(s) stopped. '
                f'{len(killed_pids)} subprocess(es) killed. '
                f'{summary.get("workers_stopped", 0)} worker(s) stopped.'
                + (' ComfyUI interrupted.' if summary.get('comfy_interrupted') else '')
            ),
        }
    )


@bp.route('/api/zero/stop/reset', methods=['POST'])
def zero_stop_reset():
    """Clear the manual stop flag so new pipelines can start (Agent Zero / Clipfarm)."""
    _clear_pipeline_halt()
    return jsonify({'success': True, 'message': 'Stop flag cleared — you can start a new run.'})


@limiter.limit('30/hour')
@bp.route('/api/zero/decompose', methods=['POST'])
def zero_decompose():
    """Task decomposition: turn a goal into backend, UI, schema, test, migration, audit subtasks with specialist routing."""
    data = request.get_json(silent=True) or {}
    goal = (data.get('goal') or data.get('message') or '').strip()
    if not goal:
        return jsonify({'error': 'Provide a goal.', 'subtasks': []}), 400
    specialists = [
        {'id': 'backend', 'scope': 'APIs, jobs, schedules, DB, crewai_web_gui routes'},
        {'id': 'ui', 'scope': 'Templates, JS, CSS, dashboard tabs'},
        {'id': 'db_schema', 'scope': 'Migrations, models, tables'},
        {'id': 'safety_audit', 'scope': 'Thresholds, audit log, integrity gate'},
        {'id': 'docs', 'scope': 'Specs, constitution, blueprint'},
        {'id': 'test', 'scope': 'Unit tests, integration, fixtures'},
    ]
    subtasks = []
    goal_lower = goal.lower()
    if any(w in goal_lower for w in ['api', 'endpoint', 'route', 'backend']):
        subtasks.append(
            {'type': 'backend', 'description': f'Implement backend for: {goal[:80]}', 'specialist': 'backend'}
        )
    if any(w in goal_lower for w in ['ui', 'dashboard', 'tab', 'button', 'form', 'page']):
        subtasks.append({'type': 'ui', 'description': f'Implement UI for: {goal[:80]}', 'specialist': 'ui'})
    if any(w in goal_lower for w in ['schema', 'migration', 'table', 'model', 'db']):
        subtasks.append(
            {'type': 'schema', 'description': f'Schema/migration for: {goal[:80]}', 'specialist': 'db_schema'}
        )
    if any(w in goal_lower for w in ['safety', 'audit', 'threshold', 'integrity']):
        subtasks.append(
            {'type': 'safety_audit', 'description': f'Safety/audit for: {goal[:80]}', 'specialist': 'safety_audit'}
        )
    if any(w in goal_lower for w in ['document', 'doc', 'spec', 'readme']):
        subtasks.append({'type': 'docs', 'description': f'Documentation for: {goal[:80]}', 'specialist': 'docs'})
    if not subtasks:
        subtasks.append({'type': 'backend', 'description': f'Implement: {goal[:80]}', 'specialist': 'backend'})
    subtasks.append({'type': 'test', 'description': 'Add tests for implementation', 'specialist': 'test'})
    out = {'goal': goal, 'subtasks': subtasks, 'specialists': specialists}
    _zero_audit_log('decompose', {'goal': goal[:200], 'subtask_count': len(subtasks)})
    # Persist to task memory so Governance can show current build state
    state = _zero_read_task_state()
    state['current_goal'] = goal[:200]
    state['subtasks'] = [{'type': t.get('type'), 'description': t.get('description', '')[:150]} for t in subtasks]
    state['phase'] = state.get('phase') or 'planning'
    _zero_write_task_state(state)
    return jsonify(out)


@bp.route('/api/zero/task-state', methods=['GET'])
def zero_get_task_state():
    """Get persistent task memory: current phase, open issues, blocked items."""
    return jsonify(_zero_read_task_state())


@limiter.limit('30/hour')
@bp.route('/api/zero/task-state', methods=['POST'])
def zero_set_task_state():
    """Update persistent task memory. Call when phase changes or issues are tracked."""
    data = request.get_json(silent=True) or {}
    state = _zero_read_task_state()
    for k in ('phase', 'open_issues', 'blocked', 'current_goal', 'subtasks'):
        if k in data:
            state[k] = data[k]
    _zero_write_task_state(state)
    _zero_audit_log('task_state_update', {'phase': state.get('phase'), 'goal': state.get('current_goal', '')[:100]})
    return jsonify(state)


@bp.route('/api/zero/validation-checklist', methods=['GET'])
def zero_validation_checklist():
    """Return validation checklist for pre-merge review. From project constitution."""
    checklist = [
        {'id': 'no_dup', 'label': 'No endpoint duplication', 'category': 'routes'},
        {'id': 'ownership', 'label': 'New data model has ownership defined', 'category': 'data'},
        {'id': 'audit', 'label': 'Dangerous actions go to audit', 'category': 'safety'},
        {'id': 'secrets', 'label': 'No hardcoded secrets', 'category': 'security'},
        {'id': 'orchestration', 'label': 'Orchestration rules respected (agents ≠ orchestrators)', 'category': 'rules'},
        {'id': 'lease', 'label': 'Lease expiry present for any claim-like flow', 'category': 'jobs'},
        {'id': 'constitution', 'label': 'Changes match project constitution', 'category': 'governance'},
    ]
    return jsonify({'checklist': checklist, 'source': 'docs/project-constitution.md'})


def _zero_change_impact(file_path: str) -> dict:
    """Analyze change impact for a file. Uses repo manifest and ownership map."""
    path = file_path.replace('\\', '/').strip()
    if not path:
        return {'file': path, 'error': 'No file path provided'}
    # Normalize: strip leading repo-relative prefixes
    for prefix in ('zyg-orchestrator/', 'legacy/flask_dashboard/', 'services/api/src/zyg_api/'):
        if path.lower().startswith(prefix):
            path = path[len(prefix) :].lstrip('/')
            break
    out = {
        'file': path,
        'module': None,
        'imports': [],
        'data_entities': [],
        'route_impact': False,
        'safety_impact': False,
        'notes': [],
    }
    manifest_path = os.path.join(DOCS_DIR, 'repo-manifest.json')
    if not os.path.isfile(manifest_path):
        out['notes'].append('Repo manifest not found')
        return out
    try:
        with open(manifest_path, 'r', encoding='utf-8') as f:
            manifest = json.load(f)
    except Exception:
        out['notes'].append('Could not load manifest')
        return out
    for mod in manifest.get('modules', []):
        mod_path = (mod.get('path') or '').replace('\\', '/')
        key_files = mod.get('key_files') or []
        matches = (
            path.startswith(mod_path)
            or (mod_path and path.startswith(mod_path.split('/')[0]))
            or any(kf in path or path.endswith(kf) or path.endswith(kf.split('/')[-1]) for kf in key_files)
        )
        if matches:
            out['module'] = mod.get('name')
            out['notes'].append(f'Owned by module: {mod.get("name")}')
            break
    # Data entity mapping (path -> ownership entity)
    data_map = [
        ('agents.json', 'Agent configs'),
        ('agent_zero.json', 'Agent Zero config'),
        ('workflow.json', 'Workflow mappings'),
        ('models.json', 'Model inventory'),
        ('schedules.json', 'Approved schedules'),
        ('schedule_requests', 'Schedule requests'),
        ('job_runs', 'Job runs'),
        ('audit_events', 'Audit events'),
        ('orchestration_permissions.json', 'Orchestration permissions'),
    ]
    for key, entity in data_map:
        if key in path:
            out['data_entities'].append(entity)
            out['notes'].append(f'Touches canonical entity: {entity}')
    # Route impact
    route_files = ['crewai_web_gui.py', 'main.py', 'routers/', 'routers\\']
    if any(rf in path for rf in route_files):
        out['route_impact'] = True
        out['notes'].append('File defines or modifies routes; check for endpoint duplication')
    # Safety impact
    safety_keywords = ['safety', 'audit', 'integrity', 'threshold', 'emergency']
    if any(sk in path.lower() for sk in safety_keywords):
        out['safety_impact'] = True
        out['notes'].append('Affects safety, audit, or integrity gate')
    return out


@bp.route('/api/zero/change-impact', methods=['GET', 'POST'])
def zero_change_impact():
    """Change impact analysis: imports, data entities, routes, safety. Per project constitution §10."""
    if request.method == 'POST':
        data = request.get_json(silent=True) or {}
        paths = data.get('paths') or data.get('files') or []
        if isinstance(paths, str):
            paths = [paths]
        if not paths:
            return jsonify({'error': 'Provide paths or files array', 'results': []}), 400
        results = [_zero_change_impact(p) for p in paths]
        return jsonify({'results': results})
    path = request.args.get('path') or request.args.get('file') or ''
    if not path:
        return jsonify({'error': 'Provide path or file query param', 'result': None}), 400
    return jsonify({'result': _zero_change_impact(path)})


@bp.route('/api/zero/audit-trail', methods=['GET'])
def zero_audit_trail():
    """Read Zero audit trail (append-only). Paginated. Why a change was made, by whom, what it touched."""
    limit = min(int(request.args.get('limit', 50) or 50), 200)
    offset = int(request.args.get('offset', 0) or 0)
    action_filter = (request.args.get('action') or '').strip() or None
    if not os.path.isfile(ZERO_AUDIT_PATH):
        return jsonify({'entries': [], 'total': 0, 'path': ZERO_AUDIT_PATH})
    entries = []
    try:
        with open(ZERO_AUDIT_PATH, 'r', encoding='utf-8') as f:
            lines = f.readlines()
        for line in reversed(lines):
            if not line.strip():
                continue
            try:
                entry = json.loads(line)
                if action_filter and entry.get('action') != action_filter:
                    continue
                entries.append(entry)
            except json.JSONDecodeError as _exc:
                _zyg_log.debug('malformed audit line skipped: %s', _exc)
                continue
        total = len(entries)
        entries = entries[offset : offset + limit]
    except Exception as e:
        return jsonify({'entries': [], 'total': 0, 'error': str(e)}), 500
    return jsonify({'entries': entries, 'total': total, 'path': ZERO_AUDIT_PATH})


@bp.route('/api/zero/kanban')
def api_zero_kanban():
    """GET current kanban batch + auto-mode state for the production queue UI."""
    batch = _zero_kanban_load()
    auto_mode = _zero_auto_mode_load()
    return jsonify({'batch': batch or None, 'auto_mode': auto_mode})


@bp.route('/api/zero/auto_mode', methods=['GET', 'POST'])
def api_zero_auto_mode():
    """GET or POST Zero auto-mode state (enabled, next_run_utc, last_run_at)."""
    if request.method == 'GET':
        return jsonify(_zero_auto_mode_load())
    data = request.get_json() or {}
    enabled = bool(data.get('enabled'))
    # Fire immediately on enable: today's batch is built (bank first, then pools) and
    # pipeline 1 starts now; next_run_utc stays None until the batch completes.
    try:
        _zero_auto_mode_set(enabled)
    except Exception as _ae:
        return jsonify({'ok': False, 'error': f'Topic fetch failed: {_ae}'}), 500
    return jsonify({'ok': True, 'enabled': enabled, 'state': _zero_auto_mode_load()})


def _zero_evaluate_approval(action_desc: str, risk_level: str) -> str:
    """Ask Zero's LLM whether to approve a pipeline action. Returns 'approve' or 'deny'."""
    if not OLLAMA_AVAILABLE or Ollama is None:
        # No LLM: auto-approve low/medium risk, deny high
        return 'approve' if risk_level in ('low', 'medium') else 'deny'
    prompt = (
        f'You are Agent Zero, the Zygomatic system overseer. '
        f'A pipeline agent is requesting approval for the following action:\n\n'
        f'Action: {action_desc}\nRisk level: {risk_level}\n\n'
        f'If this is a normal, expected pipeline operation, reply only with the word APPROVE. '
        f'If this seems dangerous, unusual, or out of scope, reply only with the word DENY. '
        f'Reply with one word only.'
    )
    for model in ['gpt-oss:20b', 'qwen3.6:35b-a3b', 'mistral:7b']:
        try:
            llm = Ollama(model=f'ollama/{model}', base_url=ZYG_OLLAMA_URL, temperature=0.0)
            resp = llm.call([{'role': 'user', 'content': prompt}])
            text = (resp if isinstance(resp, str) else getattr(resp, 'content', str(resp))).strip().upper()
            return 'approve' if 'APPROVE' in text else 'deny'
        except Exception as _exc:
            _zyg_log.warning('approval model %s unreachable, trying the next one: %s', model, _exc)
            continue
    return 'approve'  # safe default for pipeline ops


def _process_pending_approvals():
    """Read pending Zero approval requests, evaluate with LLM, write decisions back."""
    if not os.path.exists(_APPROVAL_REQ_FILE):
        return
    with open(_APPROVAL_REQ_FILE) as f:
        requests_list = json.load(f)

    # Load approval store
    approvals = {}
    if os.path.exists(_APPROVAL_STORE_FILE):
        with open(_APPROVAL_STORE_FILE) as f:
            approvals = json.load(f)

    changed = False
    for req in requests_list:
        job_id = req.get('job_id') or req.get('id', '')
        if not job_id:
            continue
        # Skip already decided
        if approvals.get(job_id, {}).get('status') in ('approved', 'denied'):
            continue
        action_desc = req.get('action', req.get('action_description', ''))
        risk_level = req.get('risk_level', 'medium')
        decision = _zero_evaluate_approval(action_desc, risk_level)
        approvals[job_id] = {
            'status': 'approved' if decision == 'approve' else 'denied',
            'decision': decision,
            'decided_by': 'Agent Zero (auto)',
            'decided_at': _ams_iso(),
            'action': action_desc,
            'risk_level': risk_level,
        }
        _zero_audit_log(
            'approval_decision', {'job_id': job_id, 'decision': decision, 'action': action_desc, 'risk': risk_level}
        )
        changed = True

    if changed:
        os.makedirs(os.path.dirname(_APPROVAL_STORE_FILE), exist_ok=True)
        with open(_APPROVAL_STORE_FILE, 'w') as f:
            json.dump(approvals, f, indent=2)


def _approval_worker():
    """Background thread: polls approval requests every 15 s and auto-evaluates."""
    while True:
        time.sleep(15)
        try:
            _process_pending_approvals()
        except Exception as _exc:
            _zyg_log.warning('approval sweep failed, retrying in 15 s: %s', _exc)


threading.Thread(target=_approval_worker, daemon=True, name='zero-approval-worker').start()


threading.Thread(target=_zero_kanban_watcher, daemon=True, name='zero-kanban-watcher').start()
