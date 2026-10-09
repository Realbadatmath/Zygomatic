#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Debug toggles, the debug loggers, the control-plane adapter probe and the
telemetry/bar-mapping readers.

Moved verbatim out of crewai_web_gui.py (2026-10-06 round-2 split): the
``API_ADAPTER_AVAILABLE`` block, the ``*_DEBUG`` toggles with their three
``_*_debug`` printers, ``_read_local_telemetry`` and the two agent-to-model bar
mappings. Every name is re-imported by crewai_web_gui.py, so the bp_* blueprints
still read them off that module.
"""

# ruff: noqa: F401  the api_adapter re-exports are read off this module and off crewai_web_gui

import logging as _zyg_logging
import os

from zyg_workflows import runtime

from zyg_dashboard.gui.timeutil import _ams_now

try:
    from zyg_dashboard.api_adapter import (
        get_agents as api_get_agents,
        get_schedule_requests,
        get_active_schedule,
        submit_schedule_request,
        get_approval_queue,
        create_approval,
        get_job_runs,
        terminate_job_run,
        get_schedule_pause_state,
        set_schedule_pause,
        get_integrity_gate,
        get_telemetry,
        get_security_controls,
        update_security_control,
        DEV_TOKEN as API_DEV_TOKEN,
        CONTROL_PLANE_DEV_MODE as API_DEV_MODE,
    )

    API_ADAPTER_AVAILABLE = True
except ImportError:
    API_ADAPTER_AVAILABLE = False
    API_DEV_TOKEN = None
    API_DEV_MODE = False


# Debug toggles: LOGIN_DEBUG=1 for login/session (default off); PAGE_LOAD_DEBUG=1 for page load/navigation (default on); BACKEND_DEBUG=1 for timeline/API
LOGIN_DEBUG = os.environ.get('CREWAI_LOGIN_DEBUG', '0').lower() in ('1', 'true', 'yes')
PAGE_LOAD_DEBUG = os.environ.get('CREWAI_PAGE_LOAD_DEBUG', '1').lower() in ('1', 'true', 'yes')
BACKEND_DEBUG = os.environ.get('CREWAI_BACKEND_DEBUG', '0').lower() in ('1', 'true', 'yes')

# Token that changes every server start; spectator sessions from a previous run have the old token and are rejected
SESSION_VALIDITY_TOKEN = os.urandom(16).hex()


def _login_debug(msg):
    """Log only when CREWAI_LOGIN_DEBUG=1 (default on) for tracing auto-login / session."""
    if LOGIN_DEBUG:
        ts = _ams_now().strftime('%H:%M:%S.%f')[:-3]
        _zyg_log.info(f'[LOGIN_DEBUG {ts}] {msg}')


def _backend_debug(msg):
    """Log only when CREWAI_BACKEND_DEBUG=1 (default off) to hide timeline/entry debug noise."""
    if BACKEND_DEBUG:
        _zyg_log.info(f'[BACKEND_DEBUG] {msg}')


runtime.register(backend_debug=_backend_debug)


def _page_load_debug(msg):
    """Log when CREWAI_PAGE_LOAD_DEBUG=1 (default on): page loads, navigation, what loads after login."""
    if PAGE_LOAD_DEBUG:
        ts = _ams_now().strftime('%H:%M:%S.%f')[:-3]
        _zyg_log.info(f'[PAGE_LOAD {ts}] {msg}')


def _read_local_telemetry():
    """Read CPU/RAM/GPU from the background cache — returns instantly, no blocking."""
    return dict(_TELEMETRY_CACHE)


# ── Background telemetry sampler ─────────────────────────────────────────────
# Samples hardware every 2s on its own daemon thread so Flask requests never
# block waiting on psutil or pynvml, even under 100% CPU load.
from zyg_workflows.runtime import TELEMETRY_CACHE as _TELEMETRY_CACHE  # noqa: E402  kept at the old definition site

_zyg_log = _zyg_logging.getLogger(__name__)


def _get_gpu_bar_mapping():
    """GPU agent→model bar mapping from data/agents.json or legacy file."""
    from zyg_dashboard.crewai_web_gui import _load_canonical_json

    data = _load_canonical_json('agents.json', 'Schedule/agent_model_bar_mapping.json')
    if data.get('agents'):
        return {
            n: {'agent_id': c.get('id', ''), 'tier': c.get('tier', 1), 'models': c.get('gpu_models', [])}
            for n, c in data['agents'].items()
        }
    return data


def _get_cpu_bar_mapping():
    """CPU agent→model bar mapping from data/agents.json or legacy file."""
    from zyg_dashboard.crewai_web_gui import _load_canonical_json

    data = _load_canonical_json('agents.json', 'Schedule/cpu_agent_model_bar_mapping.json')
    if data.get('agents'):
        return {
            n: {'agent_id': c.get('id', ''), 'tier': c.get('tier', 1), 'models': c.get('cpu_models', [])}
            for n, c in data['agents'].items()
        }
    return data
