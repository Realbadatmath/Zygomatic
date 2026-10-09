# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later
"""bp_zero — the original top import block, the blueprint and the runtime-conditional names.

Moved verbatim out of bp_zero.py (original lines 5-94) by the 2026-10-06
modularization wave; zero logic edits.
"""

# ruff: noqa: F401
#   F401: this module also holds imports its siblings in this package re-import.

# Generated 2026-07-17 heavy-tranche modularization — extracted from crewai_web_gui.py.
# See crews_modularization_backups_20260717/MODULARIZATION_CHANGELOG.md.
# Contract: imported only at the BOTTOM of crewai_web_gui.py (all main globals exist;
# the running __main__ instance is aliased as `crewai_web_gui` in sys.modules).
import base64
import json
import os
import re
import time
import threading
from flask import (
    Blueprint,
    jsonify,
    request,
    session,
)
from zyg_workflows import gui_state
from zyg_workflows.paths import ZYG_OLLAMA_URL
from zyg_dashboard import paths as _zyg_paths
from zyg_dashboard.bp_claude_clip import _record_token_usage
from zyg_dashboard.bp_integrity_ops import get_dependencies_status
from zyg_dashboard.bp_safety import (
    _safety_error_logs_fn,
    _safety_job_status_fn,
    _safety_schedule_pause_fn,
    _safety_telemetry_fn,
)
from zyg_dashboard.bp_zero_public_store import _zpub_pending_load
from zyg_workflows.pipeline_common import _resolve_pipeline_public_status
from zyg_workflows.stage_runner import _check_workflow_health, _load_workflow_overrides
from zyg_dashboard.crewai_web_gui import (
    DOCS_DIR,
    _APPROVAL_REQ_FILE,
    _APPROVAL_STORE_FILE,
    _SPORTS_KEYWORD_BLOCKLIST,
    _ZERO_AUTO_MODE_PATH,
    _ZERO_BATCH_SCHEDULE_PATH,
    _ZERO_KANBAN_LOCK,
    _ZERO_KANBAN_PATH,
    _ZERO_POOL_LABELS,
    _ZERO_POOL_PICK_COUNT,
    _ZERO_PUB_TIMES,
    _ZERO_TOPICS_PENDING,
    _ZERO_TOPICS_PENDING_PATH,
    _ZERO_TOPICS_TTL,
    _ZERO_TOPIC_POOLS_PATH,
    _caveman_kw,
    _clear_pipeline_halt,
    _get_cpu_models,
    _get_gpu_models,
    _halt_all_pipeline_activity,
    _start_clipfarm_internal,
    limiter,
    requests,
)
from zyg_dashboard import crewai_web_gui as _main_mod

# Round-2 split homes (packages/dashboard/docs/gui_split_map.md). gui.controller is
# imported after crewai_web_gui on purpose: crewai_web_gui.py loads it mid-file, and
# that is the import site that must stay first.
from zyg_dashboard.gui import controller as _gui_controller
from zyg_dashboard.gui import telemetry as _gui_telemetry
from zyg_dashboard.gui.controller import controller
from zyg_dashboard.gui.runtime_state import _RUNTIME_DIR, _runtime_path, _workflow_jobs
from zyg_dashboard.gui.scholarly import _start_scholarly_pipeline_internal
from zyg_dashboard.gui.timeutil import _AMS_TZ, _ams_iso, _ams_now
from zyg_dashboard.gui.zero_store import (
    ZERO_AUDIT_PATH,
    ZERO_TASK_STATE_PATH,
    _zero_audit_log,
    _zero_load_config,
)
import logging as _zyg_logging

# The zyg_dashboard package directory, named once here and imported by the siblings:
# bp_zero's packaged files sit next to the pre-split bp_zero.py, i.e. directly in it.
_zyg_pkg_dir = str(_zyg_paths.PKG_DIR)

# channel kept from the pre-split module
_zyg_log = _zyg_logging.getLogger('zyg_dashboard.bp_zero')

# import_name kept from the pre-split module: Flask derives the blueprint's root_path from it
bp = Blueprint('zero', 'zyg_dashboard.bp_zero')


# runtime-conditional names (bound inside try/except in the module that owns them —
# tolerant binding, matching the original graceful-degradation semantics). Read off
# the owning module, not crewai_web_gui: the api_adapter probe moved to gui.telemetry
# and the crewai/Ollama probe to gui.controller.
API_ADAPTER_AVAILABLE = getattr(_gui_telemetry, 'API_ADAPTER_AVAILABLE', None)
OLLAMA_AVAILABLE = getattr(_gui_controller, 'OLLAMA_AVAILABLE', None)
Ollama = getattr(_gui_controller, 'Ollama', None)
_dsl = getattr(_main_mod, '_dsl', None)
get_approval_queue = getattr(_gui_telemetry, 'get_approval_queue', None)
get_integrity_gate = getattr(_gui_telemetry, 'get_integrity_gate', None)
get_schedule_pause_state = getattr(_gui_telemetry, 'get_schedule_pause_state', None)
get_telemetry = getattr(_gui_telemetry, 'get_telemetry', None)
