# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

# Generated 2026-07-17 heavy-tranche modularization — extracted from crewai_web_gui.py.
# See crews_modularization_backups_20260717/MODULARIZATION_CHANGELOG.md.
# Contract: imported only at the BOTTOM of crewai_web_gui.py (all main globals exist;
# the running __main__ instance is aliased as `crewai_web_gui` in sys.modules).

# bp_zero.py (2,028 lines) became this package on 2026-10-06, modularization wave 3.5.
# Every section was moved BYTE-FOR-BYTE into a submodule; this __init__ re-does the
# original top import block so attribute access like bp_zero.os still resolves, imports
# the submodules in the original section order so the module-level side effects (route
# registration, the two worker threads) still fire in that order, and re-exports every
# name the old module defined. The import path is unchanged: no importer was edited.
#
#   constants.py   lines    5-94    top imports, the blueprint, runtime-conditional names
#   classify.py    lines   95-443   classify / model pick / governance / status routes
#   chat.py        lines  444-745   /api/zero/chat and the internal classify endpoint
#   topics.py      lines  746-1231  topic discovery, filtering, the bank, batch launch
#   kanban.py      lines 1232-1670  kanban store, batch creation, the two tick loops
#   api.py         lines 1671-2028  task state, remaining routes, approvals, the threads
#
# ruff: noqa: E402, F401

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

from zyg_dashboard.bp_zero import constants
from zyg_dashboard.bp_zero import classify
from zyg_dashboard.bp_zero import chat
from zyg_dashboard.bp_zero import topics
from zyg_dashboard.bp_zero import kanban
from zyg_dashboard.bp_zero import api

# Every name bp_zero.py itself defined, re-exported in declaration order.
from zyg_dashboard.bp_zero.constants import (
    _zyg_log,
    bp,
    API_ADAPTER_AVAILABLE,
    OLLAMA_AVAILABLE,
    Ollama,
    _dsl,
    get_approval_queue,
    get_integrity_gate,
    get_schedule_pause_state,
    get_telemetry,
)
from zyg_dashboard.bp_zero.classify import (
    _zero_classify_task,
    _zero_get_model,
    _zero_load_governance,
    _zero_gather_context,
    _zero_required_llms,
    _zero_ollama_tags,
    zero_workflow_health,
    zero_workflow_override,
    zero_context,
    get_zero_llms_status,
    zero_install_llms,
    _zero_extract_image_base64,
)
from zyg_dashboard.bp_zero.chat import (
    zero_chat,
    api_internal_zero_classify,
)
from zyg_dashboard.bp_zero.topics import (
    _zero_pending_save,
    _zero_pending_load,
    _zero_fetch_trending_raw,
    _sports_pre_filter,
    _zero_filter_documentary_topics,
    _zero_produced_topics,
    _aq_get,
    _aq_topics_per_batch,
    _aq_bank,
    _zero_next_batch_topics,
    _zero_pipeline_options_for,
    _zero_bank_settle,
    _zero_stop_job,
    _zero_auto_mode_set,
    _zero_pause,
    _zero_abort,
    _zero_fetch_pool_topics,
    _zero_find_topics_handler,
    _zero_compute_batch_publish_slots,
    _zero_launch_topic_documentaries,
)
from zyg_dashboard.bp_zero.kanban import (
    _ZERO_KANBAN_ARCHIVE_PATH,
    _zero_kanban_load,
    _zero_kanban_save,
    _zero_kanban_completed_at,
    _zero_kanban_retire_if_stale,
    _zero_auto_mode_load,
    _zero_auto_mode_save,
    _zero_kanban_pipeline_outcome,
    _zero_kanban_create_batch,
    _mem_available_gb,
    _zero_batch_release_models,
    _zero_kanban_tick,
    _zero_auto_scheduler_tick,
    _zero_kanban_watcher,
)
from zyg_dashboard.bp_zero.api import (
    _zero_read_task_state,
    _zero_write_task_state,
    zero_stop,
    zero_stop_reset,
    zero_decompose,
    zero_get_task_state,
    zero_set_task_state,
    zero_validation_checklist,
    _zero_change_impact,
    zero_change_impact,
    zero_audit_trail,
    api_zero_kanban,
    api_zero_auto_mode,
    _zero_evaluate_approval,
    _process_pending_approvals,
    _approval_worker,
)
