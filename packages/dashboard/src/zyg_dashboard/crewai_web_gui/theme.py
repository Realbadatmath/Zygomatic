#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Display names, the icon probes, the theme config, the small API tables.

Lines 4044-4559 of the original module, verbatim: the agent-config name lookups,
the favicon and apple-touch-icon probes, the dashboard config and theme block with
``_theme_version`` and the cache-header ``after_request``, the smoke-test script
table, the HuggingFace ``.env`` path, the channel-data-retrieval probe and the
sports / templates-store / clips-output paths.
"""

# ruff: noqa: E402,F401  verbatim move: the original import order is load-bearing,
# and every name here is read back off zyg_dashboard.crewai_web_gui by the bp_* blueprints.

from zyg_dashboard import paths as _dash_paths
from zyg_dashboard.crewai_web_gui._bootstrap import _zyg_log, app, hashlib, json, os, request, send_from_directory
from zyg_dashboard.crewai_web_gui.security import _get_gpu_models, _load_canonical_json
from zyg_dashboard.crewai_web_gui.claude_clips import _ccl_re


def sanitize_filename(name: str) -> str:
    """Strip filesystem-unsafe characters and collapse whitespace."""
    safe = _ccl_re.sub(r'[^\w\s\-]', '', str(name))
    safe = _ccl_re.sub(r'\s+', '_', safe.strip())
    return safe[:80] or 'clip'


# 2026-07-17 heavy-tranche: _hms_to_seconds moved to bp_claude_clip.py


# 2026-07-17 heavy-tranche: _ccl_log moved to bp_claude_clip.py


# 2026-07-17 heavy-tranche: _ccl_build_srt moved to bp_claude_clip.py


# 2026-07-17 heavy-tranche: _render_clip_direct moved to bp_claude_clip.py


# 2026-07-17 heavy-tranche: analyze_video_for_claude moved to bp_claude_clip.py


# 2026-07-17 heavy-tranche: execute_claude_clip_plan moved to bp_claude_clip.py


# 2026-07-17 heavy-tranche: execute_sfx_plan moved to bp_claude_clip.py


# 2026-07-17 heavy-tranche: execute_caption_plan moved to bp_claude_clip.py


# ── HTTP endpoints so VS Code / Claude can trigger remotely ─────────────────

# 2026-07-17 heavy-tranche: api_analyze_video moved to bp_claude_clip.py


# 2026-07-17 heavy-tranche: api_execute_plan moved to bp_claude_clip.py


# 2026-07-17 heavy-tranche: api_token_usage moved to bp_claude_clip.py


# 2026-07-17 heavy-tranche: zero_decompose moved to bp_zero.py


# 2026-07-17 heavy-tranche: zero_get_task_state moved to bp_zero.py


# 2026-07-17 heavy-tranche: zero_set_task_state moved to bp_zero.py


# 2026-07-17 heavy-tranche: zero_validation_checklist moved to bp_zero.py


# 2026-07-17 heavy-tranche: _zero_change_impact moved to bp_zero.py


# 2026-07-17 heavy-tranche: zero_change_impact moved to bp_zero.py


# 2026-07-17 heavy-tranche: zero_audit_trail moved to bp_zero.py


# 2026-07-17 heavy-tranche: get_orchestration_permissions moved to bp_agents_api.py

# 2026-07-17 modularization: removed /api/gpu_ai_models + /api/cpu_ai_models (only consumers were the
# legacy gpu/cpu_schedule.html templates, dropped in the 2026-10-05 repository split)

# 2026-07-17 heavy-tranche: get_hardware_table moved to bp_agents_api.py

# 2026-07-17 modularization: removed /api/cpu_model_gradient_mapping (legacy cpu_schedule.html only)

# 2026-07-17 heavy-tranche: get_model_ids moved to bp_agents_api.py

# 2026-07-17 modularization: removed /api/canonical_gpu_models + /api/canonical_cpu_models and their
# CANONICAL_*_MODEL_IDS constants (only consumers were legacy gpu/cpu_schedule.html, dropped in the
# 2026-10-05 repository split)

# 2026-07-17 modularization: removed orphaned legacy /dashboard route (dashboard.html dropped in the
# 2026-10-05 repository split)

# 2026-07-17 modularization: lines moved to a bp_* blueprint module (see crews_modularization_backups_20260717)
# Load agent configurations for ID lookup (canonical data/agents.json)
agent_configs = _load_canonical_json('agents.json', 'agent_configurations.json', subkey='agents') or {}


def get_agent_name_by_id(agent_id):
    for agent in agent_configs.values():
        if agent.get('id') == agent_id:
            return agent.get('name')
    return None


# Map seed-style IDs/names (agent-001, Agent 001) to config agent names
def _build_agent_seed_to_config():
    config_names = list(agent_configs.keys())
    m = {}
    for i, name in enumerate(config_names):
        idx = str(i + 1).zfill(3)
        m[f'agent-{idx}'] = name
        m[f'Agent {idx}'] = name
    return m


_AGENT_SEED_TO_CONFIG = _build_agent_seed_to_config()


def _resolve_agent_display_name(api_name, api_id):
    """Return config agent name when API returns seed placeholder (Agent 001, agent-001)."""
    if api_id and api_id in _AGENT_SEED_TO_CONFIG:
        return _AGENT_SEED_TO_CONFIG[api_id]
    if api_name and api_name in _AGENT_SEED_TO_CONFIG:
        return _AGENT_SEED_TO_CONFIG[api_name]
    return api_name or (api_id or '')


# Load model ID -> name for LLM display
_MODEL_ID_TO_NAME = {}
try:
    for mid, data in _get_gpu_models().items():
        if isinstance(data, dict) and data.get('name'):
            _MODEL_ID_TO_NAME[str(mid)] = data['name']
except Exception as _exc:
    _zyg_log.warning('gpu model registry unreadable, model ids stay unresolved in the UI: %s', _exc)


def get_model_name_by_id(model_id):
    """Return human-readable name for model ID (e.g. 1018 -> LLaMA 3 70B Q4)."""
    return _MODEL_ID_TO_NAME.get(str(model_id), str(model_id))


def _resolve_ai_models_display(ai_model_ids):
    """Resolve list of model IDs to display names."""
    if not ai_model_ids:
        return []
    return [get_model_name_by_id(m) for m in ai_model_ids]


# CPU schedule endpoints
# 2026-10-06 round-2 split: class _ControlPlaneUnavailable moved to zyg_dashboard.gui.controller


# 2026-07-17 modularization: lines moved to a bp_* blueprint module (see crews_modularization_backups_20260717)
# 2026-07-17 heavy-tranche: frontend_log moved to bp_pipeline_api.py


# 2026-07-17 heavy-tranche: live_log moved to bp_pipeline_api.py


# 2026-07-17 heavy-tranche: pipeline_flags moved to bp_pipeline_api.py

# 2026-07-17 modularization: lines moved to a bp_* blueprint module (see crews_modularization_backups_20260717)


# 2026-07-17 heavy-tranche: api_tools moved to bp_agents_api.py


@app.route('/favicon.ico')
@app.route('/apple-touch-icon.png')
@app.route('/apple-touch-icon-precomposed.png')
def _root_icon_probe():
    """2026-08-25: root-path icon probes -> the black-Z badge in static/ (source + tiers in
    ~/Documents/favicon-workflows/README.txt). Auth-exempt in require_login(). Explicit
    Cache-Control because /static images get none and browsers then cache heuristically."""
    name = 'favicon.ico' if request.path.endswith('.ico') else 'apple-touch-icon.png'
    resp = send_from_directory(app.static_folder, name)
    resp.headers['Cache-Control'] = 'public, max-age=86400'
    return resp


@app.route('/test_gradients.html')
def test_gradients():
    return send_from_directory(str(_dash_paths.PKG_DIR), 'test_gradients.html')


# 2026-07-17 modularization: removed 3 broken test-page routes (test_diagram_styles/test_arrowhead_u/
# test_diagram_u_setups — target files never existed; routes could only 404)

# 2026-07-17 modularization: lines moved to a bp_* blueprint module (see crews_modularization_backups_20260717)

# --- Dashboard: config and theme ---
try:
    from zyg_dashboard.dashboard_config import (
        BUTTONS_DIR,
        BACKGROUNDS_DIR,
        SIDEBAR_DIR,
        THEME_CONFIG_PATH,
        USERS_DATA_PATH,
        ERROR_LOGS_DATA_PATH,
        JOB_STATUS_DATA_PATH,
        MONITORING_JOBS_PATH,
        SAFETY_THRESHOLDS_PATH,
        SAFETY_AUDIT_LOG_PATH,
        AVATARS_DIR,
        DEFAULT_BUTTON_THEME,
        DEFAULT_BACKGROUND_THEME,
        LANGUAGES_DIR,
        LANGUAGE_LINKS_FILE,
    )

    DASHBOARD_AVAILABLE = True
    try:
        from zyg_workflows.safety_subsystem import init_safety_audit

        init_safety_audit(SAFETY_AUDIT_LOG_PATH)
    except ImportError as _exc:
        _zyg_log.warning('safety audit not initialised, safety events are not written: %s', _exc)
except ImportError:
    DASHBOARD_AVAILABLE = False
    # Fallback constants (2026-07-17): the bp_* blueprints imported at the
    # bottom of this file re-export these names (`from crewai_web_gui import
    # BACKGROUNDS_DIR, ...`). When the dashboard_config import above fails,
    # leaving them undefined turns one bad import into a full startup crash —
    # the 07:52 restart crash-looped 6× on exactly this ImportError. The
    # DASHBOARD_AVAILABLE gate keeps the routes disabled; the constants just
    # need to exist. Values mirror dashboard_config.py.
    _dc_dir = str(_dash_paths.PKG_DIR)
    _dc_project_root = os.path.abspath(os.path.join(_dc_dir, '..', '..'))
    _dc_layouts = os.path.join(_dc_project_root, 'Layouts and Themes')
    BUTTONS_DIR = os.path.join(_dc_layouts, 'Buttons')
    BACKGROUNDS_DIR = os.path.join(_dc_layouts, 'Background')
    SIDEBAR_DIR = os.path.join(_dc_layouts, 'Sidebar')
    THEME_CONFIG_PATH = os.path.join(_dc_dir, 'dashboard_theme_config.json')
    USERS_DATA_PATH = os.path.join(_dc_dir, 'dashboard_users.json')
    ERROR_LOGS_DATA_PATH = os.path.join(_dc_dir, 'dashboard_error_logs.json')
    JOB_STATUS_DATA_PATH = os.path.join(_dc_dir, 'dashboard_job_status.json')
    MONITORING_JOBS_PATH = os.path.join(_dc_dir, 'dashboard_monitoring_jobs.json')
    SAFETY_THRESHOLDS_PATH = os.path.join(_dc_dir, 'safety_thresholds.json')
    SAFETY_AUDIT_LOG_PATH = os.path.join(_dc_dir, 'safety_audit_log.jsonl')
    AVATARS_DIR = os.path.join(_dc_dir, 'static', 'avatars')
    LANGUAGES_DIR = os.path.join(_dc_project_root, 'Languages')
    LANGUAGE_LINKS_FILE = os.path.join(LANGUAGES_DIR, 'Language Links', 'language_links.json')
    DEFAULT_BUTTON_THEME = {'file': 'scaled_steel_buttons_test.html', 'variant': 's18', 'label': 'Scaled 18 Subtle'}
    DEFAULT_BACKGROUND_THEME = {'file': 'soft_backgrounds_test.html', 'variant': 'bg37', 'label': 'Smoky Pearl'}


# 2026-10-06 round-2 split: _load_json and _save_json moved to zyg_dashboard.gui.runtime_state


def _theme_version(data):
    """Generate version for optimistic locking. Used when theme writes are re-enabled."""
    return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()[:16]


# 2026-07-17 modularization: lines moved to a bp_* blueprint module (see crews_modularization_backups_20260717)


# 2026-07-17 heavy-tranche: _hash_password moved to bp_auth.py


# 2026-07-17 heavy-tranche: _check_password moved to bp_auth.py


# 2026-07-17 heavy-tranche: api_login moved to bp_auth.py


# 2026-07-17 heavy-tranche: _logout_clear_cookie moved to bp_auth.py


# 2026-07-17 heavy-tranche: logout_page moved to bp_auth.py


# 2026-07-17 heavy-tranche: api_logout moved to bp_auth.py


# 2026-07-17 heavy-tranche: api_health moved to bp_auth.py


# 2026-07-17 heavy-tranche: api_restart moved to bp_auth.py


# 2026-07-17 heavy-tranche: dashboard_my_account_get moved to bp_auth.py


# 2026-07-17 heavy-tranche: dashboard_my_account_save moved to bp_auth.py


# 2026-07-17 heavy-tranche: api_csrf_token moved to bp_auth.py


# 2026-07-17 modularization: lines moved to a bp_* blueprint module (see crews_modularization_backups_20260717)
# 2026-07-17 heavy-tranche: api_zero_kanban moved to bp_zero.py


# 2026-07-17 heavy-tranche: api_zero_auto_mode moved to bp_zero.py


# 2026-07-17 modularization: lines moved to a bp_* blueprint module (see crews_modularization_backups_20260717)
# 2026-07-17 heavy-tranche: api_frequency_data moved to bp_benchmark.py


# 2026-07-17 heavy-tranche: api_frequency_history moved to bp_benchmark.py


# 2026-07-17 heavy-tranche: api_frequency_history_run moved to bp_benchmark.py


# 2026-07-17 heavy-tranche: api_calibrate_get moved to bp_benchmark.py


# 2026-07-17 heavy-tranche: api_calibrate_post moved to bp_benchmark.py


# 2026-07-17 modularization: lines moved to a bp_* blueprint module (see crews_modularization_backups_20260717)
# 2026-07-17 heavy-tranche: api_integrity_gate moved to bp_integrity_ops.py


# 2026-07-17 heavy-tranche: api_vram_free moved to bp_integrity_ops.py


# 2026-07-17 heavy-tranche: api_telemetry moved to bp_integrity_ops.py


# 2026-07-17 heavy-tranche: api_disk_usage moved to bp_integrity_ops.py


# 2026-07-17 heavy-tranche: api_telemetry_log moved to bp_integrity_ops.py


# 2026-07-17 heavy-tranche: api_security_controls_get moved to bp_integrity_ops.py


# 2026-07-17 heavy-tranche: api_security_controls_patch moved to bp_integrity_ops.py


# 2026-07-17 heavy-tranche: api_integrity_gate_force_override moved to bp_integrity_ops.py


# 2026-07-17 heavy-tranche: dashboard_error_logs moved to bp_integrity_ops.py

# 2026-07-17 heavy-tranche: dashboard_error_logs_save moved to bp_integrity_ops.py

# 2026-07-17 heavy-tranche: dashboard_job_status moved to bp_integrity_ops.py

# 2026-07-17 heavy-tranche: dashboard_job_status_save moved to bp_integrity_ops.py

# 2026-07-17 heavy-tranche: dashboard_monitoring_jobs moved to bp_integrity_ops.py

# 2026-07-17 heavy-tranche: dashboard_monitoring_jobs_save moved to bp_integrity_ops.py


# 2026-07-17 heavy-tranche: dashboard_language_pack_check moved to bp_integrity_ops.py


# 2026-07-17 heavy-tranche: dashboard_language_link moved to bp_integrity_ops.py


# 2026-07-17 modularization: lines moved to a bp_* blueprint module (see crews_modularization_backups_20260717)
@app.after_request
def _add_cache_headers(response):
    """Cache JS/CSS for 1 day so navigation and repeat visits are faster."""
    if request.path.startswith('/static/') and request.path.endswith(('.js', '.css')):
        response.headers.setdefault('Cache-Control', 'public, max-age=86400')
    return response


# ── Azure Cloud API ───────────────────────────────────────────────────────────

# 2026-07-17 heavy-tranche: azure_usage moved to bp_integrity_ops.py


# 2026-07-17 heavy-tranche: azure_config_get moved to bp_integrity_ops.py


# 2026-07-17 heavy-tranche: azure_config_save moved to bp_integrity_ops.py


# 2026-07-17 heavy-tranche: azure_reset_counter moved to bp_integrity_ops.py

# ══════════════════════════════════════════════════════════════════════════════
# Smoke-test runner — launches test scripts as subprocesses, streams output
# ══════════════════════════════════════════════════════════════════════════════
# 2026-07-17 heavy-tranche: _smoke_runs moved to bp_integrity_ops.py

# Smoke-test override: set to a positive int to cap FLUX image count in the scholarly pipeline.
# The smoke test script sets this to 3 to avoid generating 79 images.  0 = production (no cap).
from zyg_workflows.pipeline_config import _SCHOLARLY_SMOKE_MAX_IMAGES  # noqa: E402,F401  kept at the old definition site

_SMOKE_SCRIPTS = {
    'video': 'scripts/test_pipeline_smoke.py',
    'documentary': 'scripts/test_documentary_smoke.py',
    'intro': 'scripts/test_intro_smoke.py',
}


# 2026-07-17 heavy-tranche: smoke_test_run moved to bp_integrity_ops.py


# 2026-07-17 heavy-tranche: smoke_test_status moved to bp_integrity_ops.py


# 2026-07-17 heavy-tranche: smoke_test_list moved to bp_integrity_ops.py


# ══════════════════════════════════════════════════════════════════════════════
# HuggingFace credentials — read/write HF_TOKEN in .env
# ══════════════════════════════════════════════════════════════════════════════
_HF_ENV_PATH = str(_dash_paths.PKG_DIR.parent.parent / '.env')  # packages/dashboard/.env

# 2026-07-17 heavy-tranche: _hf_read_env_token moved to bp_integrity_ops.py


# 2026-07-17 heavy-tranche: _hf_active_token moved to bp_integrity_ops.py

# 2026-07-17 heavy-tranche: _hf_write_env_token moved to bp_integrity_ops.py


# 2026-07-17 heavy-tranche: hf_settings_get moved to bp_integrity_ops.py


# 2026-07-17 heavy-tranche: hf_settings_save moved to bp_integrity_ops.py


# 2026-07-17 heavy-tranche: hf_settings_test moved to bp_integrity_ops.py


# 2026-07-17 heavy-tranche: hf_settings_download moved to bp_integrity_ops.py


# 2026-07-17 heavy-tranche: api_benchmark_pipeline_history moved to bp_benchmark.py


# 2026-07-17 heavy-tranche: api_benchmark_seeds moved to bp_benchmark.py


# 2026-07-17 heavy-tranche: api_benchmark_run_infra moved to bp_benchmark.py


# 2026-07-17 heavy-tranche: api_benchmark_status moved to bp_benchmark.py


# 2026-07-17 heavy-tranche: _bm_infra_worker moved to bp_benchmark.py


# ── Multi-run concurrent benchmark ───────────────────────────────────────

# 2026-07-17 heavy-tranche: _bm_mr_sample moved to bp_benchmark.py


# 2026-07-17 heavy-tranche: _bm_multirun_worker moved to bp_benchmark.py


# 2026-07-17 heavy-tranche: api_benchmark_multirun_start moved to bp_benchmark.py


# 2026-07-17 heavy-tranche: api_benchmark_multirun_status moved to bp_benchmark.py


# 2026-07-17 heavy-tranche: api_benchmark_system moved to bp_benchmark.py


# 2026-07-17 heavy-tranche: api_benchmark moved to bp_benchmark.py


# ── Channel Data Retrieval API ────────────────────────────────────────────────
try:
    from zyg_workflows import channel_data_retrieval as _cdr

    _CDR_OK = True
except Exception as _cdr_e:
    _CDR_OK = False
    _cdr_e_str = str(_cdr_e)


# 2026-07-17 heavy-tranche: api_channel_data_groups moved to bp_assets_media.py


# 2026-07-17 heavy-tranche: api_channel_data_fetch moved to bp_assets_media.py


# ── Sports-video pipeline status (read-only proxy for the dashboard) ─────────
_SV_STATUS_FILE = os.path.expanduser('~/sports-video-pipeline/status.json')


# 2026-07-17 heavy-tranche: sv_status_proxy moved to bp_assets_media.py


# ── Templates store API ───────────────────────────────────────────────────────
_TSTORE_FILE = os.path.join(os.path.expanduser('~/sports-video-pipeline'), 'templates_store.json')


# 2026-07-17 heavy-tranche: _tstore_read moved to bp_assets_media.py


# 2026-07-17 heavy-tranche: _tstore_write moved to bp_assets_media.py


# 2026-07-17 heavy-tranche: api_templates_list moved to bp_assets_media.py


# 2026-07-17 heavy-tranche: api_templates_store moved to bp_assets_media.py


# 2026-07-17 heavy-tranche: api_templates_delete moved to bp_assets_media.py


# ── Templates output board API ────────────────────────────────────────────────
_CLIPS_OUTPUT_DIR = str(_dash_paths.DATA_DIR / 'output' / 'clips')


# 2026-07-17 heavy-tranche: _parse_clip_yaml moved to bp_assets_media.py


# 2026-07-17 heavy-tranche: api_templates_outputs moved to bp_assets_media.py


# 2026-07-17 heavy-tranche: api_templates_thumb moved to bp_assets_media.py


# 2026-07-17 heavy-tranche: asset_manager_templates_board moved to bp_assets_media.py
