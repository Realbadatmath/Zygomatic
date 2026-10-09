#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""zyg_dashboard.gui — the sections split out of crewai_web_gui.py.

Round-2 of the dashboard god-module split (2026-10-06), same pattern as the
gamesim and video_studio packages: each module here is a VERBATIM move of one
contiguous section of crewai_web_gui.py, and crewai_web_gui.py re-imports every
moved name so the 28 bp_* / pipeline importers still resolve unchanged.
``packages/dashboard/docs/gui_split_map.md`` is the name -> module table.

Re-exported from this package: the five modules with no import-time dependency
back on crewai_web_gui. ``gui.controller`` is deliberately NOT imported here —
it instantiates the process-wide ``controller`` at import time and reaches back
into crewai_web_gui for ``_load_canonical_json`` / ``_get_all_tools``, so it must
be imported from the point in crewai_web_gui.py where the class used to stand.

Acceptance of the split (2026-10-06): ``import zyg_dashboard.crewai_web_gui``
now succeeds with no crewai installed and with no environment variable set at
all. Refusing to run without ``FLASK_SECRET_KEY`` moved to serve time —
``crewai_web_gui.require_flask_secret()``.
"""

# ruff: noqa: F401  this package is a namespace of re-exports; nothing here is used in this file

from zyg_dashboard.gui.runtime_state import (
    _char_gen_jobs,
    _contact_sheet_jobs,
    _creature_gen_jobs,
    _load_json,
    _reconcile_stale_workflow_jobs,
    _RUNTIME_DIR,
    _runtime_path,
    _save_json,
    _workflow_jobs,
    _workflow_pipeline_worker_alive,
)
from zyg_dashboard.gui.scholarly import (
    _start_crime_pipeline_internal,
    _start_scholarly_pipeline_internal,
)
from zyg_dashboard.gui.telemetry import (
    API_ADAPTER_AVAILABLE,
    BACKEND_DEBUG,
    LOGIN_DEBUG,
    PAGE_LOAD_DEBUG,
    SESSION_VALIDITY_TOKEN,
    _backend_debug,
    _get_cpu_bar_mapping,
    _get_gpu_bar_mapping,
    _login_debug,
    _page_load_debug,
    _read_local_telemetry,
)
from zyg_dashboard.gui.timeutil import (
    _AMS_TZ,
    _ams_iso,
    _ams_now,
    _parse_iso_to_ams,
)
from zyg_dashboard.gui.zero_store import (
    AGENT_ZERO_CONFIG_PATH,
    ZERO_AUDIT_PATH,
    ZERO_TASK_STATE_PATH,
    _zero_audit_log,
    _zero_load_config,
    block_spectator_mutation,
)
