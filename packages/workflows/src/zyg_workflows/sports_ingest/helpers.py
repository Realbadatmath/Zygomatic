# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""sports_ingest.helpers — tiny io helpers and the D+2 window.

Verbatim section of the original sports_ingest.py (lines 304-391); no logic changes.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone

from zyg_workflows.sports_ingest.constants import (
    DEFAULT_LEAGUES,
    DEFAULT_SETTINGS,
    _LOCAL_TZ,
    _LOCK,
    _SETTINGS_PATH,
    _zyg_log,
)


# ── tiny io helpers ─────────────────────────────────────────────────────────


def _load(path, default):
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return default() if callable(default) else default


def _save(path, data) -> None:
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        os.replace(tmp, path)
    except (OSError, TypeError) as _exc:
        _zyg_log.warning('state write to %s failed, continuing without it: %s', path, _exc)


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime = None) -> str:
    return (dt or _now_utc()).strftime('%Y-%m-%dT%H:%M:%S%z')


def settings() -> dict:
    with _LOCK:
        s = dict(DEFAULT_SETTINGS)
        s['leagues'] = {k: list(v) for k, v in DEFAULT_LEAGUES.items()}
        stored = _load(_SETTINGS_PATH, {})
        for k, v in (stored or {}).items():
            if k in s:
                s[k] = v
        return s


def update_settings(patch: dict) -> dict:
    with _LOCK:
        s = _load(_SETTINGS_PATH, {})
        allowed = set(DEFAULT_SETTINGS) | {'leagues'}
        for k, v in (patch or {}).items():
            if k in allowed:
                s[k] = v
        _save(_SETTINGS_PATH, s)
    return settings()


# ── the D+2 window ──────────────────────────────────────────────────────────


def window_for(build_day: datetime = None, day_override: str = '') -> 'tuple[datetime, datetime, str]':
    """(utc_from, utc_to, 'YYYY-MM-DD') for the whole local calendar day at D+2.

    Any instant inside that day is at least +24 h and at most +72 h from any
    instant of the build day, which is exactly the operator's rule.

    `day_override` (operator-only, 2026-08-08): an explicit 'YYYY-MM-DD' target
    day, accepted ONLY at D+1 or D+2 — the operator's verbal rule allows "not
    less than 1 day" ahead, and tournament sports (tennis) can have their whole
    remaining card on D+1. Anything outside D+1/D+2 falls back to D+2.
    """
    now_local = (build_day or _now_utc()).astimezone(_LOCAL_TZ)
    target = (now_local + timedelta(days=2)).date()
    if day_override:
        try:
            want = datetime.strptime(day_override.strip(), '%Y-%m-%d').date()
            if want in ((now_local + timedelta(days=1)).date(), target):
                target = want
            else:
                _zyg_log.info(f'[SPORTS] day_override {day_override!r} outside D+1/D+2 — using D+2 {target}')
        except ValueError:
            _zyg_log.info(f'[SPORTS] bad day_override {day_override!r} — using D+2')
    start_local = datetime(target.year, target.month, target.day, 0, 0, 0, tzinfo=_LOCAL_TZ)
    end_local = start_local + timedelta(days=1)
    return start_local.astimezone(timezone.utc), end_local.astimezone(timezone.utc), target.isoformat()


def _z(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
