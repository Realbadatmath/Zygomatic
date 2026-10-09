# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later
"""bp_zero — task classification, model pick, governance/context gathering and the status/LLM routes.

Moved verbatim out of bp_zero.py (original lines 95-443) by the 2026-10-06
modularization wave; zero logic edits.
"""

# ruff: noqa: F401
#   F401: this module also holds imports its siblings in this package re-import.
from zyg_dashboard.bp_zero.constants import (
    API_ADAPTER_AVAILABLE,
    DOCS_DIR,
    ZYG_OLLAMA_URL,
    _RUNTIME_DIR,
    _check_workflow_health,
    _get_cpu_models,
    _get_gpu_models,
    _load_workflow_overrides,
    _runtime_path,
    _safety_error_logs_fn,
    _safety_job_status_fn,
    _safety_schedule_pause_fn,
    _safety_telemetry_fn,
    _zero_load_config,
    _zpub_pending_load,
    _zyg_log,
    _zyg_pkg_dir,
    base64,
    bp,
    controller,
    get_approval_queue,
    get_dependencies_status,
    get_integrity_gate,
    get_schedule_pause_state,
    get_telemetry,
    json,
    jsonify,
    limiter,
    os,
    request,
    requests,
    session,
)


def _zero_classify_task(msg: str, has_image: bool = False) -> str:
    """Classify user message to pick the right LLM: brain, code, vision, utility."""
    m = (msg or '').lower().strip()
    if has_image or any(
        w in m
        for w in (
            'screenshot',
            'image',
            'picture',
            'photo',
            'ui ',
            'visual',
            'what do you see',
            'look at',
            'show me the',
            'analyze the screen',
            'describe the',
        )
    ):
        return 'vision'
    if any(
        w in m
        for w in (
            'code',
            'script',
            'api',
            'function',
            'fix ',
            'debug',
            'write a',
            'implement',
            'sql',
            'python',
            'javascript',
            'json',
            'yaml',
            'config',
            'endpoint',
            'bug ',
            'error in code',
        )
    ):
        return 'code'
    if len(m.split()) <= 4 and any(
        w in m for w in ('status', 'how many', 'yes', 'no', 'ok', '?', 'pause', 'resume', 'list')
    ):
        return 'utility'
    return 'brain'


def _zero_get_model(cfg: dict, task_type: str) -> str:
    """Resolve model name from config. Fallback to brain if missing."""
    llms = cfg.get('llms') or {}
    return llms.get(task_type) or llms.get('brain') or 'qwen3.6:35b-a3b'


def _zero_load_governance():
    """Load project constitution, ownership map, repo manifest for Agent Zero. Used to enforce rules."""
    out = {'constitution': '', 'ownership_summary': '', 'repo_manifest': None}
    constitution_path = os.path.join(DOCS_DIR, 'project-constitution.md')
    if os.path.isfile(constitution_path):
        with open(constitution_path, 'r', encoding='utf-8') as f:
            out['constitution'] = f.read()[:6000]
    ownership_path = os.path.join(DOCS_DIR, 'canonical-data-ownership.md')
    if os.path.isfile(ownership_path):
        with open(ownership_path, 'r', encoding='utf-8') as f:
            out['ownership_summary'] = f.read()[:3000]
    manifest_path = os.path.join(DOCS_DIR, 'repo-manifest.json')
    if os.path.isfile(manifest_path):
        with open(manifest_path, 'r', encoding='utf-8') as f:
            out['repo_manifest'] = json.load(f)
    return out


def _zero_gather_context():
    """Aggregate app state for Zero: metrics, agents, schedules, telemetry, safety, governance."""
    ctx = {'agents_count': len(controller.agent_configs), 'agent_names': list(controller.agent_configs.keys())[:30]}
    metrics_list = []
    for name, cfg in controller.agent_configs.items():
        for m in cfg.get('performance_metrics') or []:
            if isinstance(m, str):
                metrics_list.append({'name': m, 'agent': name})
    ctx['metrics'] = metrics_list[:50]
    ctx['gpu_models_count'] = len(_get_gpu_models() or {})
    ctx['cpu_models_count'] = len(_get_cpu_models() or {})
    if API_ADAPTER_AVAILABLE:
        token = session.get('api_token')
        try:
            t = get_telemetry(token=token)
            if t and not t.get('error'):
                ctx['telemetry'] = {
                    'cpu_pct': t.get('cpu_pct', 0),
                    'ram_pct': t.get('ram_pct', 0),
                    'gpus': t.get('gpus', []),
                }
            else:
                ctx['telemetry'] = {'error': t.get('error', 'unavailable')}
        except Exception:
            ctx['telemetry'] = {'error': 'unavailable'}
        try:
            q = get_approval_queue(token=token)
            ctx['approval_queue_count'] = len(q.get('items') or [])
        except Exception:
            ctx['approval_queue_count'] = 0
        try:
            ps = get_schedule_pause_state(token=token)
            ctx['schedule_paused'] = ps.get('paused', False)
            ctx['schedule_pause_reason'] = ps.get('reason', '')
        except Exception:
            ctx['schedule_paused'] = False
        try:
            ig = get_integrity_gate(token=token)
            ctx['integrity_blocked'] = bool(ig.get('blocked_reason'))
            ctx['integrity_checks'] = ig.get('checks', [])
        except Exception:
            ctx['integrity_blocked'] = False
    else:
        ctx['control_plane'] = 'unavailable'
    try:
        from zyg_workflows.safety_subsystem import get_safety_status as _get_safety_status

        try:
            from zyg_dashboard.dashboard_config import SAFETY_THRESHOLDS_PATH as _thresh
        except ImportError:
            _thresh = os.path.join(_zyg_pkg_dir, 'safety_thresholds.json')
        safety = _get_safety_status(
            thresholds_path=_thresh,
            telemetry_fn=_safety_telemetry_fn,
            job_status_fn=_safety_job_status_fn,
            schedule_pause_fn=_safety_schedule_pause_fn,
            error_logs_fn=_safety_error_logs_fn,
        )
        ctx['safety'] = {'level': safety.get('protection_level', 0), 'label': safety.get('protection_label', 'Normal')}
    except Exception:
        ctx['safety'] = {'level': 0, 'label': 'Unknown'}
    try:
        deps = get_dependencies_status()
        ctx['dependencies'] = deps.get('status', 'unknown')
        ctx['parts_missing'] = deps.get('parts_missing', [])
    except Exception:
        ctx['dependencies'] = 'unknown'
    try:
        gov = _zero_load_governance()
        ctx['governance'] = gov
    except Exception:
        ctx['governance'] = {}
    return ctx


def _zero_required_llms():
    """Return list of LLM model names Zero requires from agent_zero.json."""
    cfg = _zero_load_config()
    llms = cfg.get('llms') or {}
    return list(llms.values()) if isinstance(llms, dict) else []


def _zero_ollama_tags():
    """Fetch list of installed Ollama models. Returns {'models': [{'name': '...'}]} or empty on error."""
    host = os.environ.get('OLLAMA_HOST', ZYG_OLLAMA_URL)
    try:
        r = requests.get(f'{host.rstrip("/")}/api/tags', timeout=10)
        if r.status_code == 200:
            return r.json()
    except requests.RequestException as _exc:
        _zyg_log.debug('ollama tag list unavailable, reporting no models: %s', _exc)
    return {'models': []}


@bp.route('/api/zero/workflow-health', methods=['GET'])
def zero_workflow_health():
    """Return workflow health issues and whether each has been resolved by the user."""
    overrides = _load_workflow_overrides()
    issues = _check_workflow_health()
    for issue in issues:
        if issue.get('auto_resolved'):
            issue['resolved'] = True
            issue['resolution'] = 'auto'
        elif issue['id'] in overrides:
            issue['resolved'] = True
            issue['resolution'] = overrides[issue['id']]
        else:
            issue['resolved'] = False
            issue['resolution'] = None
    unresolved = sum(1 for i in issues if not i['resolved'])
    return jsonify({'issues': issues, 'unresolved_count': unresolved})


@bp.route('/api/zero/workflow-override', methods=['POST'])
def zero_workflow_override():
    """Store a user decision (skip/ignore) for a workflow issue."""
    data = request.get_json(silent=True) or {}
    issue_id = (data.get('issue_id') or '').strip()
    action = (data.get('action') or '').strip()
    if not issue_id or action not in ('skip', 'ignore'):
        return jsonify({'success': False, 'error': 'issue_id and action (skip|ignore) required'}), 400
    overrides_file = _runtime_path('clipfarm_workflow_overrides.json')
    overrides = {}
    if os.path.exists(overrides_file):
        try:
            with open(overrides_file) as f:
                overrides = json.load(f)
        except Exception as _exc:
            _zyg_log.warning('%s unreadable, it is rewritten with this override alone: %s', overrides_file, _exc)
    overrides[issue_id] = action
    with open(overrides_file, 'w') as f:
        json.dump(overrides, f, indent=2)
    # If upload skipped, pre-create output folder (clipfarm's no-upload skip path;
    # clipfarm now writes to output/clipfarm/ — 2026-07-25).
    if issue_id == 'no_upload_platforms' and action == 'skip':
        out_dir = os.path.join(os.path.dirname(_RUNTIME_DIR), 'output', 'clipfarm')
        os.makedirs(out_dir, exist_ok=True)
    return jsonify({'success': True, 'issue_id': issue_id, 'action': action})


@bp.route('/api/zero/context', methods=['GET'])
def zero_context():
    """Return active pipeline state and pending approval count for Zero's contextual greeting."""
    pipeline_info = None
    try:
        jobs_file = _runtime_path('clipfarm_pipeline_jobs.json')
        if os.path.exists(jobs_file):
            with open(jobs_file) as f:
                jobs = json.load(f)
            active = [j for j in jobs.values() if isinstance(j, dict) and j.get('status') == 'running']
            if active:
                j = active[0]
                pipeline_info = {
                    'active': True,
                    'job_id': j.get('pipeline_id') or j.get('job_id', ''),
                    'stage_name': j.get('current_stage', 'In progress'),
                }
    except Exception as _exc:
        _zyg_log.warning('active pipeline probe failed, reporting no pipeline: %s', _exc)
    pending = 0
    try:
        req_file = _runtime_path('clipfarm_zero_approval_requests.json')
        store_file = _runtime_path('clipfarm_zero_approval_store.json')
        if os.path.exists(req_file):
            with open(req_file) as f:
                reqs = json.load(f)
            store = {}
            if os.path.exists(store_file):
                with open(store_file) as f:
                    store = json.load(f)
            pending = sum(1 for k in reqs if k not in store)
    except Exception as _exc:
        _zyg_log.warning('approval request probe failed, reporting 0 pending: %s', _exc)
    # Count pending manual-permission requests from Zero public
    pending_manual = 0
    try:
        mp = _zpub_pending_load()
        pending_manual = sum(1 for r in mp if r.get('status') == 'pending')
    except Exception as _exc:
        _zyg_log.warning('zero public pending probe failed, reporting 0 manual requests: %s', _exc)
    return jsonify({'pipeline': pipeline_info, 'pending_approvals': pending, 'pending_manual': pending_manual})


@bp.route('/api/zero/llms-status', methods=['GET'])
def get_zero_llms_status():
    """Return whether Zero's required LLMs are installed. For first-open flow: show install prompt if not ready."""
    required = _zero_required_llms()
    if not required:
        return jsonify({'ready': True, 'installed': [], 'missing': [], 'message': 'No LLMs configured'})
    data = _zero_ollama_tags()
    installed_names = {m.get('name', '').split(':')[0] or m.get('name', '') for m in (data.get('models') or [])}
    installed_full = {m.get('name', '') for m in (data.get('models') or [])}
    missing = []
    installed = []
    for m in required:
        m_base = m.split(':')[0] if ':' in m else m
        if m in installed_full or m_base in installed_names or any(m_base in n for n in installed_full):
            installed.append(m)
        else:
            missing.append(m)
    ready = len(missing) == 0
    return jsonify(
        {
            'ready': ready,
            'installed': installed,
            'missing': missing,
            'required': required,
        }
    )


@limiter.limit('10/hour')
@bp.route('/api/zero/install-llms', methods=['POST'])
def zero_install_llms():
    """Install Zero's required LLMs via Ollama. Pulls missing models. Returns when first model completes (or errors)."""
    required = _zero_required_llms()
    if not required:
        return jsonify({'success': True, 'message': 'No LLMs to install', 'pulled': []})
    data = _zero_ollama_tags()
    installed_full = {m.get('name', '') for m in (data.get('models') or [])}
    missing = [m for m in required if m not in installed_full and not any(m.split(':')[0] in n for n in installed_full)]
    if not missing:
        return jsonify({'success': True, 'message': 'All LLMs already installed', 'pulled': []})
    host = os.environ.get('OLLAMA_HOST', ZYG_OLLAMA_URL).rstrip('/')
    pulled = []
    for model in missing:
        try:
            r = requests.post(f'{host}/api/pull', json={'model': model, 'stream': False}, timeout=3600)
            if r.status_code == 200:
                pulled.append(model)
        except requests.RequestException as e:
            return jsonify(
                {
                    'success': False,
                    'message': str(e),
                    'pulled': pulled,
                    'failed': model,
                }
            ), 500
    return jsonify(
        {
            'success': True,
            'message': f'Installed {len(pulled)} model(s)' if pulled else 'Install completed',
            'pulled': pulled,
        }
    )


def _zero_extract_image_base64(data: dict, files) -> str | None:
    """Extract base64 image from request. Handles image, image_base64, image_url (data URI), or file upload."""
    # JSON: image_base64 (raw), image (data URI or base64), image_url (data URI)
    for key in ('image_base64', 'image', 'image_url'):
        val = data.get(key)
        if not val or not isinstance(val, str):
            continue
        val = val.strip()
        if val.startswith('data:'):
            # data:image/png;base64,iVBORw0...
            if ';base64,' in val:
                return val.split(';base64,', 1)[1]
            continue
        if len(val) > 100:
            return val  # assume raw base64
    # Multipart file
    f = files.get('image') if files else None
    if f and f.filename:
        try:
            return base64.b64encode(f.read()).decode('utf-8')
        except Exception as _exc:
            _zyg_log.warning('uploaded image could not be read, continuing without it: %s', _exc)
    return None
