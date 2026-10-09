# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""
Azure free-tier budget guard.

Tracks monthly usage for each Azure service and blocks calls once 95% of the
free tier limit is reached. Counters auto-reset on the 1st of each month.

All data stored in data/runtime/azure_usage.json — no external dependencies.
"""

import json
import os
import threading
from datetime import datetime, timezone

try:
    from zoneinfo import ZoneInfo

    _AMS_TZ = ZoneInfo('Europe/Amsterdam')
except Exception:
    _AMS_TZ = None
import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)


def _ams_now() -> datetime:
    if _AMS_TZ is not None:
        try:
            return datetime.now(_AMS_TZ)
        except Exception as _exc:
            _zyg_log.debug('Amsterdam timezone unavailable, using UTC: %s', _exc)
    return datetime.now(timezone.utc)


_BUDGET_LOCK = threading.Lock()
_RUNTIME_DIR = os.path.join(os.path.dirname(__file__), 'data', 'runtime')
_USAGE_PATH = os.path.join(_RUNTIME_DIR, 'azure_usage.json')

# Free tier limits + 95% guard thresholds
LIMITS: dict[str, dict] = {
    'blob_uploads': {'free': 50_000, 'guard': 47_500, 'unit': 'operations', 'label': 'Blob Storage — operations'},
    'blob_bytes': {'free': 5 * 1024**3, 'guard': int(4.75 * 1024**3), 'unit': 'bytes', 'label': 'Blob Storage — data'},
    'function_calls': {'free': 1_000_000, 'guard': 950_000, 'unit': 'calls', 'label': 'Azure Functions'},
    'eventgrid_events': {'free': 100_000, 'guard': 95_000, 'unit': 'events', 'label': 'Event Grid'},
    'apim_calls': {'free': 1_000_000, 'guard': 950_000, 'unit': 'calls', 'label': 'API Management'},
}


def _load() -> dict:
    try:
        if os.path.exists(_USAGE_PATH):
            with open(_USAGE_PATH) as f:
                return json.load(f)
    except (OSError, ValueError) as _exc:
        _zyg_log.warning('budget usage file unreadable, starting from an empty ledger: %s', _exc)
    return {}


def _save(data: dict) -> None:
    os.makedirs(_RUNTIME_DIR, exist_ok=True)
    with open(_USAGE_PATH, 'w') as f:
        json.dump(data, f, indent=2)


def _get_state() -> dict:
    """Load usage state, auto-reset if the calendar month changed."""
    now_month = _ams_now().strftime('%Y-%m')
    data = _load()
    if data.get('month') != now_month:
        data = {
            'month': now_month,
            'last_reset': _ams_now().isoformat(timespec='milliseconds'),
        }
        for k in LIMITS:
            data[k] = 0
        _save(data)
    return data


def check_and_increment(service: str, amount: int = 1) -> bool:
    """
    Check budget then atomically increment the counter.
    Returns True if the call should proceed, False if the guard limit is hit.
    Thread-safe — safe to call from multiple concurrent threads.
    """
    if service not in LIMITS:
        return True  # unknown service — allow

    with _BUDGET_LOCK:
        state = _get_state()
        current = state.get(service, 0)
        guard = LIMITS[service]['guard']

        if current >= guard:
            return False  # budget exceeded — caller should skip

        state[service] = current + amount
        _save(state)
        return True


def get_usage() -> dict:
    """
    Return current usage counters with limit / percentage / status for
    every tracked service. Used by the dashboard API.
    """
    with _BUDGET_LOCK:
        state = _get_state()

    services = {}
    for k, meta in LIMITS.items():
        current = state.get(k, 0)
        free = meta['free']
        guard = meta['guard']
        pct = round(current / free * 100, 1) if free else 0.0

        if k == 'blob_bytes':
            current_fmt = f'{current / 1024**3:.2f} GB'
            free_fmt = f'{free / 1024**3:.1f} GB'
            guard_fmt = f'{guard / 1024**3:.2f} GB'
        else:
            current_fmt = f'{current:,}'
            free_fmt = f'{free:,}'
            guard_fmt = f'{guard:,}'

        services[k] = {
            'current': current,
            'current_fmt': current_fmt,
            'guard': guard,
            'guard_fmt': guard_fmt,
            'free': free,
            'free_fmt': free_fmt,
            'unit': meta['unit'],
            'label': meta['label'],
            'pct': pct,
            'status': 'ok' if pct < 80 else ('warn' if pct < 95 else 'blocked'),
        }

    return {
        'month': state.get('month'),
        'last_reset': state.get('last_reset'),
        'services': services,
    }


def reset_service(service: str) -> bool:
    """Manually reset a single service counter (admin action)."""
    if service not in LIMITS and service != 'all':
        return False
    with _BUDGET_LOCK:
        state = _get_state()
        if service == 'all':
            for k in LIMITS:
                state[k] = 0
        else:
            state[service] = 0
        _save(state)
    return True
