#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The timeline orchestrator, the tool catalogue, the controller, the root pages.

Lines 819-1182 of the original module, verbatim: the dual orchestrator, the
CPU/GPU model lists loaded out of ``ai_model_agent_mapping``, ``_load_all_tools``,
the ``gui.controller`` import at the point where ``class CrewAIController`` used to
stand, the ``/login`` and ``/`` routes, the dashboard-tab renderer and the
restore-jobs-from-disk startup pass.
"""

# ruff: noqa: E402,F401  verbatim move: the original import order is load-bearing,
# and every name here is read back off zyg_dashboard.crewai_web_gui by the bp_* blueprints.

from zyg_dashboard import paths as _dash_paths
from zyg_dashboard.crewai_web_gui._bootstrap import (
    _RUNTIME_DIR,
    _backend_debug,
    _page_load_debug,
    _workflow_jobs,
    _zyg_log,
    app,
    gui_state,
    importlib,
    json,
    os,
    redirect,
    render_template,
    request,
    session,
    sys,
    url_for,
)
from zyg_dashboard.crewai_web_gui.security import DATA_DIR, _ensure_csrf_token
from zyg_workflows.pipeline_common import _pipeline_current_stage_from_job, _resolve_pipeline_public_status

# --- Timeline Orchestrator Integration ---
SCHEDULE_DIR = str(_dash_paths.SCHEDULE_DIR)
GPU_SCHEDULE_FILE = os.path.join(SCHEDULE_DIR, 'schedule_data_GPU.json')
CPU_SCHEDULE_FILE = os.path.join(SCHEDULE_DIR, 'schedule_data_CPU.json')

_backend_debug(f'Using GPU schedule file: {GPU_SCHEDULE_FILE}')
_backend_debug(f'Using CPU schedule file: {CPU_SCHEDULE_FILE}')

# The orchestrator is a module of this package; the Schedule/ directory never had to
# go on sys.path for the import below to resolve.
from zyg_dashboard.Schedule.timeline_orchestrator_dual import DualTimelineOrchestrator  # noqa: E402  kept at the old import site
from zyg_workflows import skill_sandbox as _skill_sandbox  # noqa: E402  kept at the old import site

# Initialize the dual orchestrator with absolute paths
orchestrator = DualTimelineOrchestrator(cpu_schedule_file=CPU_SCHEDULE_FILE, gpu_schedule_file=GPU_SCHEDULE_FILE)

# Load CPU and GPU model lists from ai_model_agent_mapping.py, which the monorepo
# split moved next to zyg_workflows — resolve it from the package, not from here.
import zyg_workflows as _zyg_workflows_pkg  # noqa: E402  re-export: the package __init__ reads it off this module
from zyg_workflows import paths as _zyg_workflows_paths

mapping_path = str(_zyg_workflows_paths.PKG_DIR / 'ai_model_agent_mapping.py')
spec = importlib.util.spec_from_file_location('ai_model_agent_mapping', mapping_path)
ai_model_agent_mapping = importlib.util.module_from_spec(spec)
sys.modules['zyg_workflows.ai_model_agent_mapping'] = ai_model_agent_mapping
spec.loader.exec_module(ai_model_agent_mapping)
CPU_MODELS = set(ai_model_agent_mapping.CPU_MODELS)
# Update GPU_MODELS to use mapping file names
GPU_MODELS = [
    'Stable_Diffusion_1.5___XL',
    'DreamShaper___RealisticVision',
    'AnimateDiff',
    'Stable_Video_Diffusion',
    'ControlNet',
    'RealESRGAN',
    'Bark',
    'Tortoise_TTS',
    'Blender_(bpy)',
    'Kandinsky_2.2',
    'Deforum',
    'ComfyUI',
    'Dreambooth',
    'LoRA',
    'VAE',
    'Davinci_Resolve',
    'ffmpeg',
    'pyDub',
    'CLIP',
    'Claude_3',
    'GPT-4',
    'LLaMA_3',
    'Mistral___Mixtral',
    'HumanEval',
    'CrewAI___OpenAgents',
    'LangChain___Llamalend',
    'Plotly',
    'FastAPI',
    'AI_QC_Engine',
    'Whisper',
    'librosa',
    'AssemblyAI',
    'Deepgram',
]

# Helper to filter schedule data by model type


def filter_schedule_by_model_type(schedule_data, allowed_models):
    filtered = {}
    for date, entries in schedule_data.items():
        filtered_entries = [e for e in entries if isinstance(e, dict) and e.get('ai_model') in allowed_models]
        if filtered_entries:
            filtered[date] = filtered_entries
    return filtered


def _load_all_tools():
    """Load all tool instances from the tools/ package, keyed by tool.name."""
    tool_map = {}
    try:
        import importlib

        modules = [
            'pipeline_tools',
            'infrastructure_tools',
            'data_tools',
            'nlp_tools',
            'speech_tools',
            'vision_tools',
            'audio_tools',
            'ffmpeg_tools',
        ]
        for mod_name in modules:
            try:
                mod = importlib.import_module(f'tools.{mod_name}')
                for attr_name in dir(mod):
                    cls = getattr(mod, attr_name)
                    if isinstance(cls, type) and hasattr(cls, 'name') and attr_name[0].isupper():
                        try:
                            instance = cls()
                            if hasattr(instance, 'name') and isinstance(instance.name, str):
                                tool_map[instance.name] = instance
                        except Exception as _exc:
                            _zyg_log.debug('tool %s could not be instantiated, skipped: %s', attr_name, _exc)
            except Exception as e:
                _backend_debug(f'Could not load tool module {mod_name}: {e}')
    except Exception as e:
        _backend_debug(f'Tool loading failed: {e}')
    _backend_debug(f'Loaded {len(tool_map)} tool instances: {list(tool_map.keys())[:5]}...')
    return tool_map


gui_state._ALL_TOOLS = None


def _get_all_tools():
    pass  # (global stmt removed: names moved to gui_state)
    if gui_state._ALL_TOOLS is None:
        gui_state._ALL_TOOLS = _load_all_tools()
    return gui_state._ALL_TOOLS


# ── 2026-10-06 round-2 split: the controller section lives in gui/controller.py ──
# Everything from _PREFERRED_MODELS through the infrastructure_tools registration —
# the Ollama probe, the two model pickers, class CrewAIController, the single
# `controller` instance and class _ControlPlaneUnavailable — moved VERBATIM there.
# The import sits HERE, not at the top of the file, because gui/controller.py
# instantiates `controller` at import time and CrewAIController.setup_agents reaches
# back for _load_canonical_json and _get_all_tools: both are defined above this line.
from zyg_dashboard.gui.controller import (  # noqa: E402,F401  re-exports, read off this module
    Agent,
    Crew,
    CrewAILLM,
    CrewAIController,
    OLLAMA_AVAILABLE,
    Ollama,
    Process,
    Task,
    _ControlPlaneUnavailable,
    _HEAVY_REASONING_KEYWORDS,
    _OLLAMA_BASE_URL,
    _PREFERRED_MODELS,
    _pick_model_for_agent,
    _pick_ollama_model,
    controller,
)


@app.route('/login')
def login_page():
    """Login page – redirect to dashboard only if already logged in as admin/operator (never for spectator)."""
    role = session.get('user_role')
    _page_load_debug(f'login_page role={role!r}')
    if role and role != 'spectators':
        _page_load_debug(f'  -> redirect to dashboard (already {role})')
        return redirect(url_for('index'))
    _page_load_debug('  -> render login page')
    return render_template('login.html')


def _render_dashboard_tab(template_name, initial_tab, current_tab, **kwargs):
    """Render dashboard template with optional initial/current tab for multi-URL navigation."""
    user_role = session.get('user_role')
    user_id = session.get('user_id')
    user_name = session.get('user_name') or session.get('username') or user_id or 'User'
    if not user_role:
        return redirect(url_for('login_page'))
    _ensure_csrf_token()
    _page_load_debug(f'dashboard render path={request.path!r} initial_tab={initial_tab!r} current_tab={current_tab!r}')
    from flask import make_response as _make_response

    resp = _make_response(
        render_template(
            template_name,
            agents=kwargs.get('agents', controller.agents),
            user_role=user_role or '',
            user_id=user_id or '',
            user_name=user_name or '',
            initial_tab=initial_tab,
            current_tab=current_tab,
            csrf_token=session.get('_csrf_token', ''),
            **{k: v for k, v in kwargs.items() if k not in ('agents', 'user_role', 'user_id', 'user_name')},
        )
    )
    resp.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate'
    resp.headers['Pragma'] = 'no-cache'
    return resp


@app.route('/')
def index():
    """Main dashboard page. No query = blank welcome. ?tab=agent_overview = Agent Overview."""
    tab = request.args.get('tab') or request.args.get('initial_tab')
    if tab and tab.strip():
        current = tab.strip()
        return _render_dashboard_tab('enhanced_dashboard.html', current, current, agents=controller.agents)
    return _render_dashboard_tab('enhanced_dashboard.html', 'welcome', 'welcome', agents=controller.agents)


# 2026-07-17 modularization: lines moved to a bp_* blueprint module (see crews_modularization_backups_20260717)
def _first_list(*vals):
    """Return the first value that is a list, or []."""
    for v in vals:
        if isinstance(v, list):
            return v
    return []


# 2026-07-17 heavy-tranche: _agent_api_to_legacy_shape moved to bp_agents_api.py


# 2026-07-17 heavy-tranche: get_agents moved to bp_agents_api.py

# 2026-07-17 heavy-tranche: get_tier1_agents moved to bp_agents_api.py

# 2026-07-17 heavy-tranche: get_department_agents moved to bp_agents_api.py

# 2026-07-17 heavy-tranche: _get_agents_list moved to bp_agents_api.py


# Agent face images from Zygomatic Origin/Agent Appearences/Faces (by agent id or name)
_AGENT_FACES_BASE = os.environ.get('AGENT_FACES_DIR')
if not _AGENT_FACES_BASE:
    _here = str(_dash_paths.PKG_DIR)
    _AGENT_FACES_BASE = os.path.normpath(
        os.path.join(_here, '..', '..', '..', '..', 'Zygomatic Origin', 'Agent Appearences', 'Faces')
    )

_AGENT_FACE_EXTENSIONS = ('.png', '.jpg', '.jpeg', '.webp')

# 2026-07-17 heavy-tranche: _find_agent_face_path moved to bp_agents_api.py

# 2026-07-17 heavy-tranche: get_agent_face moved to bp_agents_api.py

# 2026-07-17 heavy-tranche: get_agents_assigned_to_user moved to bp_agents_api.py

# 2026-07-17 heavy-tranche: get_departments moved to bp_agents_api.py

# 2026-07-17 heavy-tranche: get_gpu_schedule moved to bp_agents_api.py

# 2026-07-17 heavy-tranche: release_gpu moved to bp_agents_api.py

# 2026-07-17 heavy-tranche: run_task moved to bp_pipeline_api.py

# 2026-07-17 heavy-tranche: run_single_agent moved to bp_pipeline_api.py

# 2026-07-17 heavy-tranche: start_clipfarm_workflow moved to bp_pipeline_api.py


# The job registry is owned by zyg_workflows.runtime: the pipelines mutate it
# without importing this module, and this name is the very same dict object.
# 2026-10-06 round-2 split: its dashboard-side import site is zyg_dashboard.gui.runtime_state


# 2026-10-05 layering: _workflow_pipeline_worker_alive moved to zyg_workflows.runtime


# 2026-07-17 heavy-tranche: _resolve_pipeline_public_status moved to pipeline_common.py


# 2026-07-17 heavy-tranche: _pipeline_current_stage_from_job moved to pipeline_common.py


# ── Restore recent pipeline jobs from disk on startup ────────────────────────
# After a Flask restart _workflow_jobs is empty, so the Kanban board can't
# show card statuses from the last run.  Load the 5 most-recent state files.
def _restore_jobs_from_disk():
    # The window used to be the 5 most-recent state files full stop. Six songs
    # and a documentary ran on 2026-10-02; the documentary was 7th by mtime, so
    # after a restart it was not merely shown as stopped — it was absent from
    # _workflow_jobs entirely, and the board could not report it at all. Scan a
    # wider window and keep the 5 most recent PLUS anything that still looks
    # live, so an unfinished run can never fall off the end. The window stays
    # bounded because there are ~577 of these files and they reach 800 KB.
    import glob as _g

    _scanned = sorted(
        _g.glob(os.path.join(_RUNTIME_DIR, 'pipeline_*_state.json')),
        key=os.path.getmtime,
        reverse=True,
    )[:30]
    _state_files = list(_scanned[:5])
    for _sf in _scanned[5:]:
        try:
            with open(_sf) as _fh:
                if _resolve_pipeline_public_status(json.load(_fh)) == 'running':
                    _state_files.append(_sf)
        except Exception as _exc:
            _zyg_log.debug('pipeline state %s unreadable, not counted as running: %s', _sf, _exc)
    for _sf in _state_files:
        try:
            with open(_sf) as _fh:
                _st = json.load(_fh)
            _pid = _st.get('pipeline_id', '')
            if not _pid or _pid in _workflow_jobs:
                continue
            # Determine pipeline type & status (no live worker after restart → not running)
            _dept = _st.get('department', 'scholarly')
            _pub = _resolve_pipeline_public_status(_st)
            _status = (
                'completed'
                if _pub == 'completed'
                else 'failed'
                if _pub in ('failed', 'stopped', 'interrupted')
                else ('running' if _pub == 'running' else 'unknown')
            )
            _workflow_jobs[_pid] = {
                'pipeline_id': _pid,
                'department': _dept,
                'status': _status,
                'started': _st.get('started', ''),
                'ended': _st.get('ended', ''),
                'current_stage': _pipeline_current_stage_from_job(_st) or None,
                'stages': {},  # flat stage name → {'status': 'completed'}
                'stage_timeline': _st.get('stage_timeline', []),
                'debug_events': _st.get('debug_events', []),
                'error': _st.get('error', ''),
            }
            # Populate stages from stage_timeline so both lookup paths work
            for _entry in _st.get('stage_timeline', []):
                _workflow_jobs[_pid]['stages'][_entry['name']] = {
                    'status': _entry.get('status', 'completed'),
                }
        except Exception as _exc:
            _zyg_log.warning('pipeline state %s unreadable, the job is not restored to the board: %s', _sf, _exc)


_restore_jobs_from_disk()


# 2026-10-06 round-2 split: _reconcile_stale_workflow_jobs is re-imported from
# zyg_dashboard.gui.runtime_state at the top of this file


# ─────────────────────────────────────────────────────────────────────────────

_APPROVAL_REQ_FILE = os.path.join(DATA_DIR, 'runtime', 'clipfarm_zero_approval_requests.json')
_APPROVAL_STORE_FILE = os.path.join(DATA_DIR, 'runtime', 'clipfarm_approvals.json')


# 2026-10-05 layering: _CLIPFARM_STAGES moved to zyg_workflows.pipeline_config
# Stage 7 (Analytics/Feedback) intentionally removed — it requires clips to already be live
# on a platform with analytics data available, which is not the case during production.


from zyg_workflows.pipeline_config import _SAFETY_THRESHOLDS_PATH  # noqa: E402,F401  kept at the old definition site

gui_state._hw_block_active = False  # Set True by monitor when critical threshold is exceeded
gui_state._hw_block_reason = ''
gui_state._pipeline_stop_flag = False  # Set True by Zero "stop" command — halts all pipeline stages immediately

# ── Calibration hard limits ─────────────────────────────────────────────────
# These are enforced as hard ceilings: stages block until hardware is under limit.
# max_gpu_watts is also applied to the GPU driver via nvidia-smi --power-limit on startup
# and whenever the value is changed via POST /api/calibrate.
gui_state._CALIBRATION: dict = {
    'max_vram_gb': 48.0,  # VRAM ceiling in GB — caps _get_free_vram_gb() so stages wait
    'max_gpu_watts': 400.0,  # GPU wattage ceiling — enforced at driver level + stage gate
    'max_cpu_pct': 80.0,  # CPU % ceiling — stages block until CPU drops below
    'max_ram_gb': 56.0,  # RAM ceiling in GB — stages block if used GB >= this
}
