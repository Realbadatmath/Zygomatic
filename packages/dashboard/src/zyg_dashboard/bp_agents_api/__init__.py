# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

# Generated 2026-07-17 heavy-tranche modularization — extracted from crewai_web_gui.py.
# See crews_modularization_backups_20260717/MODULARIZATION_CHANGELOG.md.
# Contract: imported only at the BOTTOM of crewai_web_gui.py (all main globals exist;
# the running __main__ instance is aliased as `crewai_web_gui` in sys.modules).
# Pattern A package (2026-10-07 modularization): bp_agents_api.py was 1,137 lines;
# the sections live in agents.py / config.py / workflow.py and this __init__ is the
# re-export shim, so the import path and every attribute access are unchanged. The
# submodules are imported in their original order, which is the order the routes
# register on `bp`.
# ruff: noqa: E402,F401
import logging as _zyg_logging
import json
import os
import time
from flask import (
    Blueprint,
    jsonify,
    request,
    send_from_directory,
    session,
)

from .agents import (
    API_ADAPTER_AVAILABLE,
    USERS_DATA_PATH,
    _AGENT_FACES_BASE,
    _AGENT_FACE_EXTENSIONS,
    _CLIPFARM_STAGES,
    _agent_api_to_legacy_shape,
    _backend_debug,
    _find_agent_face_path,
    _first_list,
    _get_agents_list,
    _get_all_tools,
    _get_cpu_bar_mapping,
    _get_gpu_bar_mapping,
    _load_canonical_json,
    _load_json,
    _main_mod,
    _resolve_agent_display_name,
    _resolve_ai_models_display,
    _runtime_path,
    _workflow_jobs,
    _zero_agent_legacy_shape,
    _zero_load_config,
    _zyg_log,
    api_get_agents,
    apply_cors,
    bp,
    controller,
    get_active_schedule,
    get_agent_face,
    get_agent_name_by_id,
    get_agents,
    get_agents_assigned_to_user,
    get_department_agents,
    get_model_name_by_id,
    get_tier1_agents,
    html_module,
    limiter,
)
from .config import (
    api_prompt_log,
    get_agent_config_by_name,
    get_agent_logbook,
    get_agent_model_bar_mapping,
    get_agents_config,
    get_cpu_agent_model_bar_mapping,
    get_departments,
    get_gpu_schedule,
    release_gpu,
)
from .workflow import (
    _load_feedback_workflow_data,
    agent_model_audit,
    agent_network,
    agent_tree,
    api_tools,
    available_models,
    get_agents_active,
    get_hardware_table,
    get_model_ids,
    get_orchestration_permissions,
    get_workflow_box_ids,
    get_workflow_step_agents,
    pipeline_stages,
)
