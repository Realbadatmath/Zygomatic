# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""system_usage.jsonl sampler, the telemetry CSV cache and run-hour days."""

from __future__ import annotations

import csv
import glob
import json
import os
import time
from datetime import datetime, timedelta
from zyg_dashboard import metrics_hub as mh

from .constants import CACHE_DIR, GPU_BUSY_UTIL, RUNTIME, SYSUSAGE_PATH, TELEMETRY_CACHE, TZ, _zyg_log
from .helpers import _day, _daykey


# ── system usage: sampler + telemetry csv + run intervals ────────────────────

_SYS = {'path': None, 'offset': 0, 'days': {}}


def _sysusage_days():
    """Per-day aggregate of system_usage.jsonl, read incrementally by byte offset."""
    try:
        size = os.path.getsize(SYSUSAGE_PATH)
    except OSError:
        return {}
    if _SYS['path'] != SYSUSAGE_PATH or size < _SYS['offset']:
        _SYS.update(path=SYSUSAGE_PATH, offset=0, days={})
    if size == _SYS['offset']:
        return _SYS['days']
    days = _SYS['days']
    with open(SYSUSAGE_PATH, 'rb') as fh:
        fh.seek(_SYS['offset'])
        chunk = fh.read()
    last_nl = chunk.rfind(b'\n')
    if last_nl < 0:
        return days
    for line in chunk[:last_nl].split(b'\n'):
        try:
            r = json.loads(line)
        except ValueError as _exc:
            _zyg_log.debug('skipping unparseable sysusage row: %s', _exc)
            continue
        ts = r.get('ts')
        if not ts:
            continue
        d = days.setdefault(
            _daykey(ts),
            {
                'minutes': 0,
                'gpu_util_sum': 0.0,
                'gpu_n': 0,
                'busy_min': 0,
                'power_wh': 0.0,
                'power_n': 0,
                'cpu_sum': 0.0,
                'cpu_n': 0,
                'ram_sum': 0.0,
                'ram_n': 0,
                'vram_sum': 0.0,
                'vram_n': 0,
            },
        )
        d['minutes'] += 1
        u = r.get('gpu_util')
        if u is not None:
            d['gpu_util_sum'] += u
            d['gpu_n'] += 1
            d['busy_min'] += 1 if u >= GPU_BUSY_UTIL else 0
        p = r.get('gpu_power_w')
        if p is not None:
            d['power_wh'] += p / 60.0
            d['power_n'] += 1
        for k in ('cpu', 'ram', 'vram'):
            v = r.get(k + '_pct')
            if v is not None:
                d[k + '_sum'] += v
                d[k + '_n'] += 1
    _SYS['offset'] += last_nl + 1
    return days


def _aggregate_csv(path):
    """One telemetry_<pipeline>.csv -> {daykey: {seconds, gpu_util_sum, busy_s, power_wh, cpu_sum, n}}."""
    days: dict = {}
    prev_ts = None
    with open(path, newline='', encoding='utf-8', errors='replace') as fh:
        rd = csv.DictReader(fh)
        for row in rd:
            ts = mh._ts(row.get('timestamp'))
            if not ts:
                continue
            dt = 1.0 if prev_ts is None else max(0.0, min(30.0, ts - prev_ts))
            prev_ts = ts
            d = days.setdefault(
                _daykey(ts),
                {'seconds': 0.0, 'gpu_util_sum': 0.0, 'busy_s': 0.0, 'power_wh': 0.0, 'cpu_sum': 0.0, 'n': 0},
            )
            d['seconds'] += dt
            d['n'] += 1
            u = mh._num(row.get('gpu_util_pct'))
            if u is not None:
                d['gpu_util_sum'] += u * dt
                d['busy_s'] += dt if u >= GPU_BUSY_UTIL else 0.0
            p = mh._num(row.get('gpu_power_w'))
            if p is not None:
                d['power_wh'] += p * dt / 3600.0
            c = mh._num(row.get('cpu_pct_raw'))
            if c is not None:
                d['cpu_sum'] += c * dt
    return days


def telemetry_days(rebuild=False):
    """Daily aggregates of every telemetry_*.csv, cached on disk per file (size+mtime)."""
    files = sorted(glob.glob(os.path.join(RUNTIME, 'telemetry_*.csv')))
    cache = {}
    if not rebuild:
        try:
            cache = mh._read_json(TELEMETRY_CACHE) or {}
        except Exception:
            cache = {}
    entries = cache.get('files') if isinstance(cache.get('files'), dict) else {}
    changed = False
    keep = {}
    for p in files:
        name = os.path.basename(p)
        try:
            st = os.stat(p)
        except OSError as _exc:
            _zyg_log.debug('skipping telemetry file that cannot be stat-ed: %s', _exc)
            continue
        e = entries.get(name)
        if e and e.get('size') == st.st_size and abs(e.get('mtime', 0) - st.st_mtime) < 1:
            keep[name] = e
            continue
        try:
            keep[name] = {'size': st.st_size, 'mtime': st.st_mtime, 'days': _aggregate_csv(p)}
        except Exception as exc:
            keep[name] = {'size': st.st_size, 'mtime': st.st_mtime, 'days': {}, 'error': str(exc)[:120]}
        changed = True
    if changed or set(keep) != set(entries):
        try:
            os.makedirs(CACHE_DIR, exist_ok=True)
            tmp = TELEMETRY_CACHE + '.tmp'
            with open(tmp, 'w', encoding='utf-8') as fh:
                json.dump({'built': time.time(), 'files': keep}, fh)
            os.replace(tmp, TELEMETRY_CACHE)
        except OSError as _exc:
            _zyg_log.warning('telemetry cache write failed, continuing with in-memory aggregates: %s', _exc)
    days: dict = {}
    for e in keep.values():
        for dk, v in (e.get('days') or {}).items():
            d = days.setdefault(
                dk, {'seconds': 0.0, 'gpu_util_sum': 0.0, 'busy_s': 0.0, 'power_wh': 0.0, 'cpu_sum': 0.0, 'n': 0}
            )
            for k in d:
                d[k] += v.get(k, 0)
    return days, len(files)


def _run_hours_by_day(runs):
    """Union of run intervals per day (hours) — the ledger-derived busy time."""
    ivs = [
        (r['started'], r['started'] + r['duration_s'])
        for r in runs
        if r['started'] and r['duration_s'] and r['status'] in ('completed', 'failed')
    ]
    ivs.sort()
    merged = []
    for s, e in ivs:
        if merged and s <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], e)
        else:
            merged.append([s, e])
    hours: dict = {}
    for s, e in merged:
        cur = s
        while cur < e:
            d = _day(cur)
            day_end = datetime.combine(d + timedelta(days=1), datetime.min.time(), TZ).timestamp()
            seg_end = min(e, day_end)
            hours[d.isoformat()] = hours.get(d.isoformat(), 0.0) + (seg_end - cur) / 3600.0
            cur = seg_end
    return hours
