#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The Agent Zero store seam: config path and loader, the task-state and audit
paths, the audit writer, and the spectator-mutation gate.

Moved verbatim out of crewai_web_gui.py (2026-10-06 round-2 split).
``ZERO_AUDIT_PATH`` and ``_zero_audit_log`` are owned by ``zyg_dashboard.appcore``
since the 2026-10-06 layering pass; this module is the import site for them, next
to the Zero paths it does own.
"""

# ruff: noqa: F401  every name here is a re-export read off this module (and off crewai_web_gui)

import json
import os

# 2026-10-06 layering: DATA_DIR moved to zyg_dashboard.appcore (same directory)
from zyg_dashboard.appcore import DATA_DIR

# 2026-10-06 layering: ZERO_AUDIT_PATH and _zero_audit_log moved to zyg_dashboard.appcore
from zyg_dashboard.appcore import ZERO_AUDIT_PATH, _zero_audit_log

# Internal token for zero_public_server — bypasses session auth on /api/internal/ routes
_ZERO_PUBLIC_TOKEN = os.environ.get('ZERO_PUBLIC_TOKEN', '')


def block_spectator_mutation():
    """No-op: permission checks are done by the control plane. API returns 403 if not allowed."""
    return None


# --- Agent Zero (user-facing chatbot, wake with "z") ---
AGENT_ZERO_CONFIG_PATH = os.path.join(DATA_DIR, 'agent_zero.json')


def _zero_load_config():
    """Load Agent Zero config from dedicated agent_zero.json (not from agents.json)."""
    if os.path.isfile(AGENT_ZERO_CONFIG_PATH):
        with open(AGENT_ZERO_CONFIG_PATH, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {'name': 'Zero', 'role': 'User interface agent', 'goal': 'Bridge user and system'}


ZERO_TASK_STATE_PATH = os.path.join(DATA_DIR, 'zero_task_state.json')
