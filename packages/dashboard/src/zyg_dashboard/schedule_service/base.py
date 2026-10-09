# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Unified schedule aggregation for the GPU/CPU resource schedule pages.

Feeds /api/schedule/* in crewai_web_gui.py. Replaces the 2025-era manual-only
Schedule/schedule_data_*.json planning view with live pipeline state + projected
scheduled work, while keeping the legacy files as the store for MANUAL entries.

Design notes (2026-07-15 modernization):
- Live state is passed in from the GUI's in-memory registries when available
  and reconciled with the persisted data/runtime/*.json state files, so the
  module also works standalone (tests, other processes).
- Pipeline bars are RESERVED: manual entries that overlap a reserved window on
  the same device scope are rejected (user decision 2026-07-15).
- All times are Europe/Amsterdam wall-clock; the old pages computed "today" in
  UTC which put them on yesterday's date until 02:00.
"""

from __future__ import annotations

import json
import os
import re
import statistics
import subprocess
import threading
import time
import uuid
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from zyg_dashboard import paths as _dash_paths
from zyg_workflows.bin import MissingExecutable, exe
from zyg_workflows.paths import ZYG_COMFY_URL
import logging as _zyg_logging

# ruff: noqa: F401  (the original module-level import block, used by sibling modules)

# channel kept from the pre-split module
_zyg_log = _zyg_logging.getLogger('zyg_dashboard.schedule_service')


_AMS = ZoneInfo('Europe/Amsterdam')
_BASE = str(_dash_paths.PKG_DIR)
_RUNTIME = str(_dash_paths.DATA_DIR / 'runtime')
_MODELS_JSON = str(_dash_paths.DATA_DIR / 'models.json')
_AGENTS_JSON = str(_dash_paths.DATA_DIR / 'agents.json')
_SCHEDULE_DIR = str(_dash_paths.SCHEDULE_DIR)
_MANUAL_FILES = {
    'gpu': os.path.join(_SCHEDULE_DIR, 'schedule_data_GPU.json'),
    'cpu': os.path.join(_SCHEDULE_DIR, 'schedule_data_CPU.json'),
}
_DURATION_CACHE = os.path.join(_RUNTIME, 'schedule_durations.json')
# Agent-session activity ledger written by agent_activity.py (kanban-server):
# one JSON line per closed span in which a Claude Code session was measurably
# on the GPU or CPU, plus a mirror of the still-open spans (2026-09-05).
_AGENT_LEDGER = os.environ.get('ZYG_AGENT_LEDGER', os.path.join(_RUNTIME, 'agent_sessions_ledger.jsonl'))
_AGENT_OPEN = os.environ.get('ZYG_AGENT_OPEN_SPANS', os.path.join(_RUNTIME, 'agent_sessions_open.json'))
AGENT_MODEL_SLUG = 'claude-code-session'
_DURATION_CACHE_TTL_S = 6 * 3600

_lock = threading.Lock()


# ── time helpers ─────────────────────────────────────────────────────────────


def ams_now() -> datetime:
    return datetime.now(_AMS)


def ams_today() -> str:
    return ams_now().strftime('%Y-%m-%d')


def _hhmm(dt: datetime) -> str:
    return dt.astimezone(_AMS).strftime('%H:%M')


def _parse_iso(s: str) -> datetime | None:
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(str(s).replace('Z', '+00:00'))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=_AMS)
        return dt.astimezone(_AMS)
    except (ValueError, TypeError):
        return None


def _parse_job_start_time(v) -> datetime | None:
    """Parse a job's real 'start_time' field (2026-08-09: LoRA trainer's
    TrainingJob.to_dict() now carries one) into a tz-aware datetime.

    The producer's exact on-wire type isn't pinned down here — accepts an
    ISO string, a datetime, or an epoch number (seconds or milliseconds) —
    and returns None rather than raising on anything unexpected so a caller
    can fall back to the heuristic without crashing."""
    if v is None:
        return None
    if isinstance(v, datetime):
        return v.astimezone(_AMS) if v.tzinfo else v.replace(tzinfo=_AMS)
    if isinstance(v, (int, float)):
        try:
            ts = float(v)
            if ts > 1e12:  # looks like milliseconds, not seconds
                ts /= 1000.0
            return datetime.fromtimestamp(ts, tz=_AMS)
        except (ValueError, OSError, OverflowError):
            return None
    s = str(v).strip()
    if not s:
        return None
    dt = _parse_iso(s)
    if dt is not None:
        return dt
    try:
        ts = float(s)
        if ts > 1e12:
            ts /= 1000.0
        return datetime.fromtimestamp(ts, tz=_AMS)
    except (ValueError, OSError, OverflowError):
        return None


# ── model / agent registry ───────────────────────────────────────────────────

_registry_cache: dict = {'ts': 0.0, 'models': None, 'agents': None}


def _load_json(path: str, default):
    try:
        with open(path, encoding='utf-8') as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return default


def _models_raw() -> dict:
    now = time.time()
    if _registry_cache['models'] is None or now - _registry_cache['ts'] > 30:
        _registry_cache['models'] = _load_json(_MODELS_JSON, {'gpu': {}, 'cpu': {}})
        _registry_cache['agents'] = _load_json(_AGENTS_JSON, {'agents': {}})
        _registry_cache['ts'] = now
    return _registry_cache['models']


def _agents_raw() -> dict:
    _models_raw()
    return _registry_cache['agents'] or {'agents': {}}


def model_registry(scope: str, include_deprecated: bool = False) -> dict:
    """{model_id: {name, slug, vram_required_mb, in_use, deprecated}} for a scope."""
    out = {}
    for mid, info in (_models_raw().get(scope, {}) or {}).items():
        if not isinstance(info, dict):
            continue
        dep = bool(info.get('deprecated'))
        if dep and not include_deprecated:
            continue
        out[str(mid)] = {
            'id': str(mid),
            'name': info.get('name') or str(mid),
            'slug': info.get('slug') or _slugify(info.get('name') or str(mid)),
            'vram_required_mb': info.get('vram_required_mb'),
            'in_use': bool(info.get('in_use', not dep)),
            'deprecated': dep,
        }
    return out


def _slugify(name: str) -> str:
    return re.sub(r'-+', '-', re.sub(r'[^a-z0-9]+', '-', (name or '').lower())).strip('-')


def _slug_to_id(scope: str) -> dict:
    return {m['slug']: mid for mid, m in model_registry(scope, include_deprecated=True).items()}


def agent_slots(scope: str) -> dict:
    """{agent_name: [{model_id, slug, bar_id}]} from data/agents.json."""
    key = 'gpu_models' if scope == 'gpu' else 'cpu_models'
    reg = model_registry(scope, include_deprecated=True)
    out = {}
    agents = _agents_raw().get('agents') or {}
    for name, cfg in agents.items():
        slots = []
        for m in cfg.get(key) or []:
            mid = str(m.get('model') or '')
            info = reg.get(mid)
            if not info:
                continue
            slots.append(
                {
                    'model_id': mid,
                    'slug': info['slug'],
                    'bar_id': m.get('bar_id') or bar_id_for(name, info['slug']),
                }
            )
        if slots:
            out[name] = slots
    return out


def bar_id_for(agent: str, slug: str) -> str:
    return f'{agent}__{slug}'


# ── devices ──────────────────────────────────────────────────────────────────

_device_cache: dict = {'ts': 0.0, 'gpu': None, 'cpu': None}


def devices(scope: str) -> list[str]:
    now = time.time()
    if _device_cache['gpu'] is None or now - _device_cache['ts'] > 300:
        gpus: list[str] = []
        try:
            res = subprocess.run(
                [exe('nvidia-smi'), '--query-gpu=name', '--format=csv,noheader'],
                capture_output=True,
                text=True,
                timeout=5,
            )
            gpus = [ln.strip() for ln in res.stdout.splitlines() if ln.strip()]
        except (OSError, subprocess.SubprocessError, MissingExecutable) as _exc:
            _zyg_log.debug('gpu name probe failed, labelling the lane generically: %s', _exc)
        cpus: list[str] = []
        try:
            with open('/proc/cpuinfo', encoding='utf-8') as fh:
                for ln in fh:
                    if ln.startswith('model name'):
                        cpus = [ln.split(':', 1)[1].strip()]
                        break
        except OSError as _exc:
            _zyg_log.debug('cpu name probe failed, labelling the lane generically: %s', _exc)
        _device_cache.update(ts=now, gpu=gpus or ['GPU 0'], cpu=cpus or ['CPU'])
    return list(_device_cache['gpu' if scope == 'gpu' else 'cpu'])
