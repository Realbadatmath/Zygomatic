# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Global pipeline halt + scoped pause registry.

Shared by crewai_web_gui, the Comfy client, and training services so low-level
modules can check "should I stop / should I pause?" without importing
crewai_web_gui (which would be a circular import).

Two distinct mechanisms live here:

* **halt** — the emergency stop. A single process-wide boolean meaning "abort
  everything and discard the run". ``halt_check`` raisers turn this into a
  RuntimeError that unwinds the worker thread; the run is thrown away.

* **pause** — the soft, *resumable* stop. Scoped (per ``char_id``, or the broad
  scopes ``'production'`` / ``'scheduled'``) and persisted to disk so it
  survives a Flask restart. A paused run frees its VRAM and parks at the last
  completed stage; ``resume`` relaunches it and it skips the finished stages.
  ``PipelinePaused`` (a *BaseException*, so ``except Exception`` blocks inside a
  pipeline never swallow it) is the signal a halt_check raises to unwind a
  worker into the parked state instead of the discarded state.
"""

from __future__ import annotations

import json
import os
import threading
import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)


# ── Emergency stop (discard) ────────────────────────────────────────────────
_lock = threading.Lock()
_halt_requested = False
_halt_reason = ''


def request_halt(reason: str = 'Stopped by user') -> None:
    global _halt_requested, _halt_reason
    with _lock:
        _halt_requested = True
        _halt_reason = reason or 'Stopped by user'


def clear_halt() -> None:
    global _halt_requested, _halt_reason
    with _lock:
        _halt_requested = False
        _halt_reason = ''


def halt_requested() -> bool:
    with _lock:
        return _halt_requested


def halt_reason() -> str:
    with _lock:
        return _halt_reason


# ── Pause / resume (soft, scoped, persistent) ───────────────────────────────
class PipelinePaused(BaseException):
    """Raised by a halt_check to unwind a worker into a *resumable* parked state.

    Subclasses BaseException (not Exception) on purpose: the contact-sheet
    pipeline wraps identity-QC and angle-expansion in ``except Exception``
    degrade-gracefully guards, and a pause must sail through those untouched.
    """

    def __init__(self, scope: str = '', reason: str = ''):
        self.scope = scope
        self.reason = reason or 'Paused by user'
        super().__init__(f'pipeline paused ({scope}): {self.reason}')


# Broad scopes that gate whole classes of work, distinct from any char_id.
SCOPE_PRODUCTION = 'production'  # every running production pipeline
SCOPE_SCHEDULED = 'scheduled'  # queued / scheduled runs not yet started

_pause_lock = threading.RLock()
_paused: dict[str, str] = {}  # scope -> reason
_PAUSE_STATE_PATH = os.path.join(
    os.path.dirname(__file__),
    'data',
    'runtime',
    'pipeline_pause.json',
)


def _load_pause_state() -> None:
    global _paused
    try:
        with open(_PAUSE_STATE_PATH, encoding='utf-8') as fh:
            data = json.load(fh)
        if isinstance(data, dict):
            _paused = {str(k): str(v) for k, v in data.items()}
    except Exception:
        _paused = {}


def _save_pause_state() -> None:
    try:
        os.makedirs(os.path.dirname(_PAUSE_STATE_PATH), exist_ok=True)
        tmp = _PAUSE_STATE_PATH + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as fh:
            json.dump(_paused, fh)
        os.replace(tmp, _PAUSE_STATE_PATH)
    except Exception as _exc:
        _zyg_log.warning(
            'pause state not persisted to %s, a restart would un-pause this work: %s', _PAUSE_STATE_PATH, _exc
        )


# Hydrate persisted pauses on import so a Flask restart doesn't silently
# un-pause work the operator paused before the restart.
_load_pause_state()


def pause(scope: str, reason: str = 'Paused by user') -> None:
    scope = (scope or '').strip()
    if not scope:
        return
    with _pause_lock:
        _paused[scope] = reason or 'Paused by user'
        _save_pause_state()


def resume(scope: str) -> None:
    scope = (scope or '').strip()
    with _pause_lock:
        if scope in _paused:
            del _paused[scope]
            _save_pause_state()


def is_paused(scope: str) -> bool:
    with _pause_lock:
        return (scope or '').strip() in _paused


def pause_reason(scope: str) -> str:
    with _pause_lock:
        return _paused.get((scope or '').strip(), '')


def paused_scopes() -> dict[str, str]:
    with _pause_lock:
        return dict(_paused)


def is_paused_for_run(char_id: str) -> bool:
    """True when a specific run should pause — its own char_id is paused, or the
    broad 'production' scope is paused (which pauses every running pipeline)."""
    with _pause_lock:
        return SCOPE_PRODUCTION in _paused or (char_id or '').strip() in _paused


def run_pause_reason(char_id: str) -> str:
    with _pause_lock:
        return _paused.get((char_id or '').strip()) or _paused.get(SCOPE_PRODUCTION) or ''
