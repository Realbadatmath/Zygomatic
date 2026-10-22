# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

# ruff: noqa: E402
#   E402: the original module already imported crewai_web_gui *after* `bp` (the circular
#         import below), and the submodule re-exports must come after that too. All five
#         section modules do `from zyg_dashboard.bp_pipeline_api import bp`, so `bp` must
#         be bound before they are imported.
# Everything this module imports is a re-export — the package IS the old namespace — and
# the re-exported names are declared in __all__ at the bottom.

# Generated 2026-07-17 heavy-tranche modularization — extracted from crewai_web_gui.py.
# See crews_modularization_backups_20260717/MODULARIZATION_CHANGELOG.md.
# Contract: imported only at the BOTTOM of crewai_web_gui.py (all main globals exist;
# the running __main__ instance is aliased as `crewai_web_gui` in sys.modules).
import logging as _zyg_logging
import json
import os
import re
from datetime import timedelta
from flask import (
    Blueprint,
    Response,
    jsonify,
    request,
    send_file,
    send_from_directory,
    session,
    stream_with_context,
)
from zyg_dashboard import bp_pipeline_api_steps as _steps
from zyg_dashboard.cors import apply_cors
from zyg_workflows import gui_state
from zyg_workflows import provenance_seal as _seal

from zyg_workflows.char_state_service import (
    _char_reconcile_job_state,
    _char_reload_jobs_from_disk,
    _contact_sheet_reload_jobs_from_disk,
    _contact_sheet_worker_alive,
    _creature_reload_jobs_from_disk,
    _creature_state_path,
)
from zyg_workflows.pipeline_common import (
    _normalize_pipeline_options,
    _parse_pipeline_model_family,
    _pipeline_current_stage_from_job,
    _resolve_pipeline_public_status,
)
from zyg_workflows.pipeline_runtime import compute_runtime as _compute_runtime
from zyg_workflows.pipeline_runtime import card_times as _card_times
from zyg_workflows.pipeline_runtime import format_runtime as _fmt_runtime
from zyg_workflows.vram_manager import _workflow_job_gpu_active

bp = Blueprint('pipeline_api', __name__)

from zyg_dashboard.crewai_web_gui import (  # noqa: E402  late: crewai_web_gui imports this blueprint at its bottom, so `bp` must exist first
    _CLIPFARM_STAGES,
    _FLUX_LORA_PATH,
    _FLUX_LORA_SCALE,
    _SUBPROC_LOCK,
    _SUBPROC_REGISTRY,
    _VALID_VISUAL_STYLES,
    _start_clipfarm_internal,
    _start_creature_pipeline_internal,
    _start_manga_pipeline_internal,
    _start_storyteller_pipeline_internal,
    _start_video_pipeline_internal,
    limiter,
)
from zyg_dashboard.gui.controller import Crew, Process, Task, controller  # noqa: E402
from zyg_dashboard.gui.runtime_state import (  # noqa: E402
    _RUNTIME_DIR,
    _char_gen_jobs,
    _contact_sheet_jobs,
    _creature_gen_jobs,
    _runtime_path,
    _workflow_jobs,
    _workflow_pipeline_worker_alive,
)
from zyg_dashboard.gui.scholarly import _start_scholarly_pipeline_internal  # noqa: E402
from zyg_dashboard.gui.telemetry import _backend_debug  # noqa: E402
from zyg_dashboard.gui.timeutil import _ams_iso, _ams_now, _parse_iso_to_ams  # noqa: E402
from zyg_dashboard.gui.zero_store import _zero_audit_log, block_spectator_mutation  # noqa: E402

_zyg_log = _zyg_logging.getLogger(__name__)


# The children's-music and cinematic wired-style tables moved to
# bp_pipeline_api_steps with the board pick that is their only reader.


# The sections above moved into submodules when bp_pipeline_api.py (1,782 lines) became
# this package. They are imported here in the original section order, so module-level
# side effects (every @bp.route registration) still happen in the same sequence.
from zyg_dashboard.bp_pipeline_api.run_start import (
    api_internal_pipeline_start,
    run_single_agent,
    run_task,
    start_clipfarm_workflow,
)
from zyg_dashboard.bp_pipeline_api.creature import (
    _read_creature_brief_name,
    _seal_gate_outputs,
    api_internal_creature_approve,
    api_internal_creature_reject,
    api_internal_creature_resume,
    api_internal_creature_sheet,
    approve_creature_review,
    reject_creature_review,
)
from zyg_dashboard.bp_pipeline_api.status import (
    _rt_report_line,
    _runtime_payload,
    api_internal_pipeline_download,
    api_internal_pipeline_status,
    workflow_status,
    workflow_status_active,
)
from zyg_dashboard.bp_pipeline_api.kanban import (
    api_subprocesses,
    get_subprocess_by_pid,
    kanban_clear_errors,
    kanban_status,
)
from zyg_dashboard.bp_pipeline_api.timeline_logs import (
    api_pipeline_active,
    api_pipeline_murch_debug,
    api_pipeline_test,
    api_pipeline_timeline,
    api_pipeline_timeline_download,
    frontend_log,
    live_log,
    pipeline_flags,
)


# ── re-export surface ────────────────────────────────────────────────────────
# Every name below is imported above and NOT used in this module: it is read off this
# module by its importers. Declaring them is what makes the re-export deliberate rather
# than an unused import; nothing does ``import *`` from here, so __all__ changes no
# behaviour.
__all__ = [
    'json',
    'os',
    're',
    'timedelta',
    'Response',
    'jsonify',
    'request',
    'send_file',
    'send_from_directory',
    'session',
    'stream_with_context',
    '_steps',
    'apply_cors',
    'gui_state',
    '_seal',
    '_char_reconcile_job_state',
    '_char_reload_jobs_from_disk',
    '_contact_sheet_reload_jobs_from_disk',
    '_contact_sheet_worker_alive',
    '_creature_reload_jobs_from_disk',
    '_creature_state_path',
    '_normalize_pipeline_options',
    '_parse_pipeline_model_family',
    '_pipeline_current_stage_from_job',
    '_resolve_pipeline_public_status',
    '_compute_runtime',
    '_card_times',
    '_fmt_runtime',
    '_workflow_job_gpu_active',
    '_CLIPFARM_STAGES',
    '_FLUX_LORA_PATH',
    '_FLUX_LORA_SCALE',
    '_SUBPROC_LOCK',
    '_SUBPROC_REGISTRY',
    '_VALID_VISUAL_STYLES',
    '_start_clipfarm_internal',
    '_start_creature_pipeline_internal',
    '_start_manga_pipeline_internal',
    '_start_storyteller_pipeline_internal',
    '_start_video_pipeline_internal',
    'limiter',
    'Crew',
    'Process',
    'Task',
    'controller',
    '_RUNTIME_DIR',
    '_char_gen_jobs',
    '_contact_sheet_jobs',
    '_creature_gen_jobs',
    '_runtime_path',
    '_workflow_jobs',
    '_workflow_pipeline_worker_alive',
    '_start_scholarly_pipeline_internal',
    '_backend_debug',
    '_ams_iso',
    '_ams_now',
    '_parse_iso_to_ams',
    '_zero_audit_log',
    'block_spectator_mutation',
    'api_internal_pipeline_start',
    'run_single_agent',
    'run_task',
    'start_clipfarm_workflow',
    '_read_creature_brief_name',
    '_seal_gate_outputs',
    'api_internal_creature_approve',
    'api_internal_creature_reject',
    'api_internal_creature_resume',
    'api_internal_creature_sheet',
    'approve_creature_review',
    'reject_creature_review',
    '_rt_report_line',
    '_runtime_payload',
    'api_internal_pipeline_download',
    'api_internal_pipeline_status',
    'workflow_status',
    'workflow_status_active',
    'api_subprocesses',
    'get_subprocess_by_pid',
    'kanban_clear_errors',
    'kanban_status',
    'api_pipeline_active',
    'api_pipeline_murch_debug',
    'api_pipeline_test',
    'api_pipeline_timeline',
    'api_pipeline_timeline_download',
    'frontend_log',
    'live_log',
    'pipeline_flags',
]
