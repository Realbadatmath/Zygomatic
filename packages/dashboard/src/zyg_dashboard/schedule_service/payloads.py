# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

from __future__ import annotations

from .base import (
    AGENT_MODEL_SLUG,
    _AMS,
    _RUNTIME,
    _parse_iso,
    agent_slots,
    ams_now,
    ams_today,
    datetime,
    devices,
    model_registry,
    os,
    timedelta,
)
from .durations import _PIPELINE_FALLBACK_MODEL, _STAGE_MODEL_RULES
from .live import build_live_entries, comfy_queue_depth
from .planning import _parse_day, build_upcoming_entries, manual_entries_for
from .history import agent_entries_for, history_entries_for
import logging as _zyg_logging_split

_zyg_log = _zyg_logging_split.getLogger('zyg_dashboard.schedule_service')

# ── telemetry window stats ───────────────────────────────────────────────────


def telemetry_window_stats(from_iso: str, to_iso: str) -> dict:
    """min/avg/max of RAM and VRAM (MB) across all per-run telemetry CSVs
    whose 1-second samples fall inside [from, to]. RAM exists only in CSVs
    written after 2026-07-15 (column added then)."""
    import csv as _csv
    import glob as _glob

    t0 = _parse_iso(from_iso)
    t1 = _parse_iso(to_iso)
    if not t0 or not t1 or t1 <= t0:
        return {'samples': 0, 'vram_mb': None, 'ram_mb': None, 'error': 'invalid window'}
    if (t1 - t0) > timedelta(hours=26):
        t1 = t0 + timedelta(hours=26)
    vram: list[float] = []
    ram: list[float] = []
    n = 0
    for f in _glob.glob(os.path.join(_RUNTIME, 'telemetry_*.csv')):
        try:
            if datetime.fromtimestamp(os.path.getmtime(f), _AMS) < t0:
                continue  # file finished before the window started
            with open(f, encoding='utf-8') as fh:
                reader = _csv.DictReader(fh)
                first = next(reader, None)
                if not first:
                    continue
                fts = _parse_iso(first.get('timestamp', ''))
                if fts and fts > t1:
                    continue  # file starts after the window ends
                for row in [first] + list(reader):
                    ts = _parse_iso(row.get('timestamp', ''))
                    if not ts or not (t0 <= ts <= t1):
                        continue
                    n += 1
                    try:
                        v = float(row.get('gpu_mem_used_mb') or 0)
                        if v > 0:
                            vram.append(v)
                    except (TypeError, ValueError) as _exc:
                        _zyg_log.debug('non-numeric gpu_mem_used_mb skipped in %s: %s', f, _exc)
                    try:
                        r = float(row.get('ram_used_mb') or 0)
                        if r > 0:
                            ram.append(r)
                    except (TypeError, ValueError) as _exc:
                        _zyg_log.debug('non-numeric ram_used_mb skipped in %s: %s', f, _exc)
        except (OSError, ValueError) as _exc:
            _zyg_log.debug('telemetry csv %s unreadable, skipped: %s', f, _exc)
            continue

    def _stats(vals: list[float]) -> dict | None:
        if not vals:
            return None
        return {
            'min': round(min(vals), 1),
            'avg': round(sum(vals) / len(vals), 1),
            'max': round(max(vals), 1),
        }

    return {'samples': n, 'vram_mb': _stats(vram), 'ram_mb': _stats(ram)}


# ── top-level API payloads ───────────────────────────────────────────────────


def live_payload(scope: str, registries: dict | None = None) -> dict:
    entries = [e for e in build_live_entries(registries) if e['device'] == scope]
    return {
        'scope': scope,
        'now': ams_now().isoformat(timespec='seconds'),
        'today': ams_today(),
        'entries': entries,
        'comfy_queue': comfy_queue_depth() if scope == 'gpu' else None,
    }


_WINDOW_DAYS = {'24h': 1, '7d': 7, '28d': 28, 'month': 31, '1y': 367}


def upcoming_payload(
    scope: str, window: str = '24h', start_day: str | None = None, registries: dict | None = None
) -> dict:
    days_n = _WINDOW_DAYS.get(window, 1)
    day0 = _parse_day(start_day) or ams_now().date()
    days = [(day0 + timedelta(days=i)).strftime('%Y-%m-%d') for i in range(days_n)]
    w_start = days[0]
    w_end = (day0 + timedelta(days=days_n)).strftime('%Y-%m-%d')

    def _in_window(e: dict) -> bool:
        # interval overlap on ISO date strings (lexical compare is correct):
        # keeps entries that span the whole window, not just those whose
        # endpoints land inside it.
        return e['date'] < w_end and e['end_iso'][:10] >= w_start

    upcoming = [e for e in build_upcoming_entries(days_n, days[0]) if e['device'] == scope and _in_window(e)]
    live = [e for e in build_live_entries(registries) if e['device'] == scope and _in_window(e)]
    manual = manual_entries_for(scope, days)
    history = history_entries_for(scope, days)
    agents = agent_entries_for(scope, days)
    return {
        'scope': scope,
        'window': window,
        'days': days,
        'now': ams_now().isoformat(timespec='seconds'),
        'today': ams_today(),
        'entries': live + upcoming + manual + history + agents,
    }


def model_pipelines(scope: str) -> dict:
    """{model_slug: [pipeline, ...]} — which pipelines use each model on this
    device scope. Drives the FIXED slot skeleton of the 24h grid: every model
    bracket always renders one sub-column per pipeline (like the original
    page's pre-declared agent bars), whether or not entries exist that day."""
    out: dict[str, list] = {}

    def _add(slug: str, dev: str, ptype: str) -> None:
        if dev != scope:
            return
        lanes = out.setdefault(slug, [])
        if ptype not in lanes:
            lanes.append(ptype)

    for ptype, rules in _STAGE_MODEL_RULES.items():
        for _needle, slug, dev in rules:
            _add(slug, dev, ptype)
    # virtual/owner pipelines that only appear via fallbacks
    for ptype in ('training', 'batch', 'publish'):
        slug, dev = _PIPELINE_FALLBACK_MODEL[ptype]
        _add(slug, dev, ptype)
    # stage rules put contact-sheet cells on qwen, but its anchor cells render
    # on FLUX-dev — the bracket should show the lane
    _add('flux-1-dev', 'gpu', 'contact_sheet')
    # agent sessions (Claude Code) get their own bracket on both pages
    _add(AGENT_MODEL_SLUG, scope, 'agent')
    return out


def meta_payload(scope: str) -> dict:
    reg = model_registry(scope)
    return {
        'scope': scope,
        'today': ams_today(),
        'timezone': 'Europe/Amsterdam',
        'models': sorted(reg.values(), key=lambda m: m['name'].lower()),
        'agent_slots': agent_slots(scope),
        'model_pipelines': model_pipelines(scope),
        'devices': devices(scope),
    }
