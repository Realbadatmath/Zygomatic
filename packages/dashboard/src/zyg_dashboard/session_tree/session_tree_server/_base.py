# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Imports, path constants, the default config and the global lock.

Moved verbatim from session_tree_server.py lines 42-128.
"""

# ruff: noqa: F401

import glob
import ipaddress
import json
import os
import re
import shutil
import subprocess
import threading
import time
import uuid
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs
import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)


BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(BASE, 'data')
ACTIVE = os.path.join(DATA, 'active')
PLANNED = os.path.join(DATA, 'planned')
FINISHED = os.path.join(DATA, 'finished')
SUGGESTED = os.path.join(DATA, 'suggested')  # modularization trees awaiting the operator's accept/reject
AUDIT = os.path.join(DATA, 'audit.jsonl')
CONFIG_PATH = os.path.join(BASE, 'config.json')
# Loopback unless the operator opts in to LAN exposure with BIND_HOST=0.0.0.0.
BIND_HOST = os.environ.get('BIND_HOST', '').strip() or '127.0.0.1'
# The address a client ON THIS MACHINE dials to reach this server: the bind address,
# except that a wildcard bind is not a dialable host and maps back to loopback.
# `is_unspecified` is asked of ipaddress rather than compared to a literal so the
# wildcard address appears nowhere in this file.
try:
    SELF_HOST = '127.0.0.1' if ipaddress.ip_address(BIND_HOST).is_unspecified else BIND_HOST
except ValueError:  # a hostname rather than an IP — dial it as given
    SELF_HOST = BIND_HOST
STATIC = os.path.join(BASE, 'static')
CLAUDE_PROJECTS = os.path.expanduser('~/.claude/projects')

DEFAULT_CONFIG = {
    'port': 7100,
    'creator_models': ['claude-fable'],
    'executor_models': ['claude-opus'],
    'max_tasks_per_tree': 30,
    'heavy_slots': 1,
    'light_slots': 3,
    'lease_minutes': 90,
    'max_tasks_per_session': 1,
    'vram_reserve_gb': 2.0,
    'ram_reserve_gb': 6.0,
    'gpu_busy_util_pct': 60,
    'verify_timeout_s': 180,
    'min_summary_chars': 40,
    'min_fail_reason_chars': 10,
    'queue_wait_stale_minutes': 10,
    # ── spawner: the board launches its own executors ──
    'auto_spawn': True,  # off = job board only (operator opens executors by hand)
    'max_executors': 30,  # live executor sessions at once (spawned + hand-opened)
    'executor_model': 'claude-opus-5',
    'spawn_permission_mode': 'auto',  # claude -p --permission-mode; a print session cannot answer prompts
    'spawn_budget_usd': 0,  # >0 → --max-budget-usd per spawned session; 0 = no cap
    'spawn_sweep_s': 20,  # how often the spawner looks for ready tasks
    'spawn_reserve_minutes': 15,  # a spawned session must claim its task within this, or it is killed
    'spawn_cooldown_s': 120,  # after a spawn exits without claiming, wait before re-spawning that task
    'spawn_brake_after': 5,  # N consecutive no-claim exits → auto-spawn pauses …
    'spawn_brake_minutes': 10,  # … for this long (audit line says so)
    'spawn_linger_s': 300,  # a spawned session that no longer holds/reserves a task is killed after this
    'spawn_starve_s': 600,  # a ready todo task not spawned for this long gets a spawn:starved audit line
    'spawn_auth_retry_s': 900,  # executor login broken ("does not have access to Claude"): retry ONE spawn this often
    'settle_archive_minutes': 20,  # a tree with NOTHING left the board can run (every task finished, failed,
    # stale, or todo behind one of those) auto-archives after this many quiet
    # minutes, so the planned queue promotes without an operator. 0 = off
    'spawn_cwd_default': os.path.expanduser('~/zygomatics-zero'),
    'operator_notify': True,  # a task fails / a tree archives while NO creator session is alive → desktop
    # notification (notify-send) to the operator. 2026-09-23: take-6 tree 69b6d6
    # failed at 22:41 with the creator session gone; nobody heard until the operator asked
    # ── Claude usage timer: the board reads the login's own meter (GET /api/oauth/usage — the
    # numbers `/usage` in the CLI and the VS Code status bar show) ──
    'usage_poll_s': 300,  # re-read the meter this often (0 = only when an executor reports the limit)
    'usage_hold_pct': 100,  # a window at/above this % puts auto-spawn on HOLD until its resets_at
    'usage_hold_margin_s': 90,  # resume this long after the reset, so the first spawn lands in the new window
}

LOCK = threading.RLock()
