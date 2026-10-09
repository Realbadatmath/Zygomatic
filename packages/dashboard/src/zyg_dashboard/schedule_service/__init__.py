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

# ruff: noqa: E402,F401
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

from zyg_workflows.bin import MissingExecutable, exe
from zyg_workflows.paths import ZYG_COMFY_URL
import logging as _zyg_logging

from .base import (  # noqa: F401
    AGENT_MODEL_SLUG,
    _AGENTS_JSON,
    _AGENT_LEDGER,
    _AGENT_OPEN,
    _AMS,
    _BASE,
    _DURATION_CACHE,
    _DURATION_CACHE_TTL_S,
    _MANUAL_FILES,
    _MODELS_JSON,
    _RUNTIME,
    _SCHEDULE_DIR,
    _agents_raw,
    _device_cache,
    _hhmm,
    _load_json,
    _lock,
    _models_raw,
    _parse_iso,
    _parse_job_start_time,
    _registry_cache,
    _slug_to_id,
    _slugify,
    _zyg_log,
    agent_slots,
    ams_now,
    ams_today,
    bar_id_for,
    devices,
    model_registry,
)
from .durations import (  # noqa: F401
    DEFAULT_DURATIONS,
    PIPELINE_AGENT,
    _PIPELINE_FALLBACK_MODEL,
    _STAGE_MODEL_RULES,
    _STATE_FILE_TYPES,
    _TEST_ID_PREFIXES_FALLBACK,
    _is_test_state,
    _pipeline_total,
    _stage_model,
    get_duration_table,
)
from .live import (  # noqa: F401
    _CS_STAGE_ORDER,
    _TERMINAL,
    _comfy_q_cache,
    _entry,
    _forecast_from_job,
    _history_from_timeline,
    _is_terminal,
    _live_from_job,
    _remaining_stages,
    build_live_entries,
    comfy_queue_depth,
)
from .planning import (  # noqa: F401
    _parse_day,
    _write_manual,
    add_manual_entry,
    build_upcoming_entries,
    check_conflict,
    delete_manual_entry,
    manual_entries_for,
    reserved_windows,
)
from .history import (  # noqa: F401
    _HISTORY_CACHE,
    _agent_mem,
    _agent_spans,
    _agent_what,
    _archive_entries_for,
    _build_history_index,
    _days_of,
    _file_sig,
    _history_index,
    _history_mem,
    _history_signature,
    agent_entries_for,
    history_entries_for,
)
from .payloads import (  # noqa: F401
    _WINDOW_DAYS,
    live_payload,
    meta_payload,
    model_pipelines,
    telemetry_window_stats,
    upcoming_payload,
)


# --- monkeypatch bridge -------------------------------------------------------
# `schedule_service` was one module: a test (or production code) that rebinds an
# attribute on it — monkeypatch.setattr(ss, '_RUNTIME', ...) — used to change the
# value every function saw. Across modules a plain setattr would only touch the
# package, so the package writes a rebinding through to every section module whose
# globals hold that name.
import sys as _sys
from types import ModuleType as _ModuleType

_SECTIONS = tuple(
    _sys.modules[f'{__name__}.{_n}'] for _n in ('base', 'durations', 'live', 'planning', 'history', 'payloads')
)


class _ScheduleServiceModule(_ModuleType):
    def __setattr__(self, name, value):
        _ModuleType.__setattr__(self, name, value)
        for _m in self.__dict__.get('_SECTIONS') or ():
            if name in _m.__dict__:
                _m.__dict__[name] = value

    def __delattr__(self, name):
        _ModuleType.__delattr__(self, name)
        for _m in self.__dict__.get('_SECTIONS') or ():
            _m.__dict__.pop(name, None)


_sys.modules[__name__].__class__ = _ScheduleServiceModule
