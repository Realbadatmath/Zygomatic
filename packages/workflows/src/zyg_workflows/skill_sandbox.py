# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""skill_sandbox.py — HTTP client for the dedicated sandbox server.

The sandbox logic lives in the standalone server at:
    $ZYG_HOME/sandbox-server/
    Binds to http://$BIND_HOST:5555 (loopback only)

Start the server before using this module:
    cd $ZYG_HOME/sandbox-server && ./start.sh

Public API (unchanged — callers need no modifications):
    run_check(skill_id, skill_data, code=None)  ->  SandboxResult dict
    get_result(skill_id)                         ->  SandboxResult dict | None
    get_all_results()                            ->  dict[skill_id, SandboxResult]
    sandbox_ready()                              ->  dict with tool availability
"""

import json
import os
import threading
import urllib.error
from datetime import datetime, timezone

from zyg_workflows import http_json
from zyg_workflows import paths

_STATUS_URL = f'http://{paths.BIND_HOST}:5555'  # public port — read-only status/results
_EXEC_URL = f'http://{paths.BIND_HOST}:5556'  # exec port — POST /check only (loopback only)
_CHECK_TIMEOUT = 120  # seconds — behavioral probe alone can take up to 30s
_DEFAULT_TIMEOUT = 10
_START_SH = str(paths.ZYG_HOME / 'sandbox-server' / 'start.sh')

# ── Inbound result store (from skill_proxy.py — stays local, not sandbox logic) ─
_HERE = os.path.dirname(os.path.abspath(__file__))
_DATA_DIR = os.path.join(_HERE, 'data', 'runtime')
_INBOUND_FILE = os.path.join(_DATA_DIR, 'skill_inbound.json')
_INBOUND_LOCK = threading.Lock()


def _http_post(path: str, payload: dict, timeout: int = _DEFAULT_TIMEOUT) -> dict:
    return http_json.post_json(_EXEC_URL + path, payload, timeout=timeout)


def _http_get(path: str, timeout: int = _DEFAULT_TIMEOUT) -> dict:
    return http_json.request_json(_STATUS_URL + path, timeout=timeout)


def _server_offline_result(skill_id: str, reason: str) -> dict:
    msg = f'Sandbox exec server offline (port 5556) — start {_START_SH} ({reason})'
    return {
        'skill_id': skill_id,
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'verdict': 'PENDING',
        'static': {'ok': True, 'issues': [], 'summary': msg},
        'deps': {'ok': True, 'vulns': [], 'scanned': [], 'summary': msg},
        'behavioral': {
            'ok': None,
            'network_block': False,
            'completed': False,
            'timed_out': False,
            'stdout': '',
            'stderr': '',
            'error': msg,
            'summary': msg,
        },
    }


# ── Public API ────────────────────────────────────────────────────────────────


def run_check(skill_id: str, skill_data: dict, code: str | None = None) -> dict:
    try:
        return _http_post(
            '/check',
            {
                'skill_id': skill_id,
                'skill_data': skill_data,
                'code': code,
            },
            timeout=_CHECK_TIMEOUT,
        )
    except urllib.error.URLError as e:
        return _server_offline_result(skill_id, str(e))


def get_result(skill_id: str) -> dict | None:
    try:
        return _http_get(f'/result/{skill_id}')
    except Exception:
        return None


def get_all_results() -> dict:
    try:
        return _http_get('/results')
    except Exception:
        return {}


def sandbox_ready() -> dict:
    try:
        return _http_get('/ready')
    except urllib.error.URLError as e:
        return {
            'bandit': False,
            'pip_audit': False,
            'pyseccomp': False,
            'runner': False,
            'all_ready': False,
            'error': f'Sandbox server not running: {e} — start {_START_SH} (needs both :5555 and :5556)',
        }


# ── Inbound result store (from skill_proxy.py) ───────────────────────────────


def _load_inbound() -> dict:
    try:
        with open(_INBOUND_FILE, 'r') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _save_inbound(data: dict) -> None:
    os.makedirs(_DATA_DIR, exist_ok=True)
    with open(_INBOUND_FILE, 'w') as f:
        json.dump(data, f, indent=2)


def store_inbound(skill_id: str, payload: dict) -> None:
    with _INBOUND_LOCK:
        store = _load_inbound()
        if skill_id not in store:
            store[skill_id] = []
        store[skill_id].append(payload)
        store[skill_id] = store[skill_id][-50:]
        _save_inbound(store)


def get_inbound(skill_id: str) -> list:
    with _INBOUND_LOCK:
        return _load_inbound().get(skill_id, [])
