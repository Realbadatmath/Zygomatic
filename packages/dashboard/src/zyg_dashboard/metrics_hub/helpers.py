# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Small helpers (timestamps, percentiles, JSON readers) and the parse / memo caches."""

from __future__ import annotations

import json
import os
import re
import threading
import time
from zyg_workflows.net import safe_urlopen
from datetime import datetime

from .constants import TZ, _zyg_log

# ── small helpers ────────────────────────────────────────────────────────────


def _is_test_id(pid) -> bool:
    """pipeline_common.is_test_pipeline_id, imported lazily (keeps import order safe)."""
    global _is_test_id_impl
    if _is_test_id_impl is None:
        try:
            from zyg_workflows.pipeline_common import is_test_pipeline_id as impl
        except Exception:
            prefixes = ('docsmoke-', 'gatecheck-', 'introsmoke-', 'smoke')

            def impl(p):
                return isinstance(p, str) and p.strip().lower().startswith(prefixes)

        _is_test_id_impl = impl
    return bool(_is_test_id_impl(pid))


_is_test_id_impl = None


def _ts(v):
    """Any timestamp shape in data/runtime -> epoch seconds (naive = Amsterdam)."""
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v) if v > 1e9 else None
    s = str(v).strip()
    if not s or s in ('None', 'null'):
        return None
    try:
        dt = datetime.fromisoformat(s.replace('Z', '+00:00'))
    except ValueError:
        try:
            dt = datetime.strptime(s[:19], '%Y-%m-%d %H:%M:%S')
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=TZ)
    return dt.timestamp()


def _iso(ts):
    return datetime.fromtimestamp(ts, TZ).isoformat(timespec='seconds') if ts else None


def _pct(values, q):
    v = sorted(x for x in values if x is not None)
    if not v:
        return None
    k = (len(v) - 1) * q
    lo = int(k)
    hi = min(lo + 1, len(v) - 1)
    return round(v[lo] + (v[hi] - v[lo]) * (k - lo), 2)


def _short(v, n=160):
    if not v:
        return ''
    s = v if isinstance(v, str) else json.dumps(v, default=str)
    return re.sub(r'\s+', ' ', s).strip()[:n]


def _num(v):
    try:
        return float(v) if v is not None and v != '' else None
    except (TypeError, ValueError):
        return None


def _rate(num, den):
    return round(num / den * 100, 1) if den else None


def _req_arg(name):
    """One query argument when a Flask request is in flight, else None. Keeps this module
    import-safe and CLI-runnable: `?detail=` rides the section endpoint, no new route."""
    try:
        from flask import has_request_context, request

        if has_request_context():
            v = request.args.get(name)
            return v.strip() if v else None
    except Exception as _exc:
        _zyg_log.debug('no flask request context, query arg %r unavailable: %s', name, _exc)
    return None


def _read_json(path):
    with open(path, encoding='utf-8', errors='replace') as fh:
        return json.load(fh)


def _iter_jsonl(path):
    with open(path, encoding='utf-8', errors='replace') as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except ValueError as _exc:
                _zyg_log.debug('malformed jsonl row skipped in %s: %s', path, _exc)
                continue
            if isinstance(row, dict):
                yield row


def _http_json(url, timeout=1.5):
    try:
        with safe_urlopen(url, timeout=timeout) as resp:
            return json.loads(resp.read().decode('utf-8', 'replace'))
    except Exception as exc:
        return {'_error': f'{type(exc).__name__}: {exc}'[:120]}


# ── caches ───────────────────────────────────────────────────────────────────
# Per-file parse cache keyed on (mtime_ns, size): a state file is parsed once and
# re-parsed only when it changes. Loaders return SMALL summaries, never the full
# state (scholarly states carry essays and word timings).

_CACHE: dict = {}
_UNREADABLE: dict = {}
_LOCK = threading.Lock()


def _cached(path, loader):
    try:
        st = os.stat(path)
    except OSError:
        return None
    key = (path, loader.__name__)
    sig = (st.st_mtime_ns, st.st_size)
    hit = _CACHE.get(key)
    if hit is not None and hit[0] == sig:
        return hit[1]
    try:
        val = loader(path)
        _UNREADABLE.pop(path, None)
    except Exception as exc:
        val = None
        _UNREADABLE[path] = f'{type(exc).__name__}: {exc}'[:120]
    with _LOCK:
        _CACHE[key] = (sig, val)
    return val


def _prune(loader, live_paths):
    name, live = loader.__name__, set(live_paths)
    with _LOCK:
        for key in [k for k in _CACHE if k[1] == name and k[0] not in live]:
            del _CACHE[key]


_MEMO: dict = {}


def _memo(key, ttl, fn, fresh=False):
    now = time.time()
    hit = _MEMO.get(key)
    if hit and not fresh and now - hit[0] < ttl:
        return hit[1]
    val = fn()
    _MEMO[key] = (time.time(), val)
    return val
