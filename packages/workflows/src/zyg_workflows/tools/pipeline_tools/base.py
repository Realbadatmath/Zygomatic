# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""
Pipeline/custom logic tools: registries, schedulers, queues, monitors, scorers,
emitters, gates, and all internal CLIPFARM pipeline utilities.
All tools use only stdlib + sqlalchemy/redis where available; pure-Python fallbacks
ensure they run even without those services.
"""

import importlib.util
import json
import os
import time
import hashlib
import threading
from datetime import datetime, timezone
from collections import defaultdict
from zyg_workflows.bin import exe

try:
    from zoneinfo import ZoneInfo

    _AMS_TZ = ZoneInfo('Europe/Amsterdam')
except Exception:
    _AMS_TZ = None
import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger('zyg_workflows.tools.pipeline_tools')


def _ams_now() -> datetime:
    """Return timezone-aware now() in Europe/Amsterdam (UTC fallback)."""
    if _AMS_TZ is not None:
        try:
            return datetime.now(_AMS_TZ)
        except Exception as _exc:
            _zyg_log.debug('Amsterdam timezone unavailable, falling back to UTC: %s', _exc)
    return datetime.now(timezone.utc)


def _ams_iso(timespec: str = 'milliseconds') -> str:
    """Tz-aware ISO timestamp in Europe/Amsterdam, including ``+HH:MM`` offset."""
    try:
        return _ams_now().isoformat(timespec=timespec)
    except TypeError:
        return _ams_now().isoformat()


try:
    from langchain.tools import BaseTool
except ImportError:
    try:
        from langchain_core.tools import BaseTool
    except ImportError:

        class BaseTool:
            name: str = ''
            description: str = ''

            def _run(self, *args, **kwargs):
                raise NotImplementedError


# Persistent runtime directory — survives reboots unlike /tmp/
_RUNTIME_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), '..', 'data', 'runtime')
os.makedirs(_RUNTIME_DIR, exist_ok=True)


def _runtime_path(filename: str) -> str:
    """Return absolute path inside the persistent runtime dir for a clipfarm state file."""
    basename = os.path.basename(filename)
    return os.path.join(_RUNTIME_DIR, basename)


# Shared in-memory stores (used as fallback when no persistent DB)
_STORES: dict = defaultdict(dict)
_LOCKS: dict = defaultdict(threading.Lock)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _store_get(namespace: str, key: str, default=None):
    return _STORES[namespace].get(key, default)


def _store_set(namespace: str, key: str, value):
    _STORES[namespace][key] = value


def _store_all(namespace: str) -> dict:
    return dict(_STORES[namespace])


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# importlib / json / time / hashlib / exe are imported here on behalf of the whole
# package: the sibling section modules do `from .base import json, os, ...` so that
# they share the exact objects the single-file pipeline_tools.py bound at module level.
__all__ = [
    'importlib',
    'json',
    'time',
    'hashlib',
    'exe',
]
