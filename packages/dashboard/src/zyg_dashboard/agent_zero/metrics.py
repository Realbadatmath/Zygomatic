# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Agent Zero's permanent per-turn ledger and the Metrics-hub section (CONTRACT F).

Two halves:

* :func:`record_turn` appends exactly one JSON line per finished turn to
  ``data/runtime/zero_metrics.jsonl``. The row shape is fixed -- the same keys, always,
  in the same order -- because this file is the only record that survives a restart and
  a reader three years from now must not have to guess which era wrote a line. The same
  call also feeds the host's token store and the LLM audit log, and neither of those is
  ever allowed to raise into a turn.
* :func:`section_zero` reduces that ledger (plus the tool log and the install log) to
  the dict the Metrics hub's ``zero`` tab renders. Its shape is CONTRACT F: the tab was
  written against these exact keys in parallel with this module.

**API-equivalent dollars.** A subscription turn costs no money -- it spends the Claude
Code seat. It is still priced, with the host's own price table, so the operator can see
what Agent Zero would have cost on the API and compare it with a hosted provider. A
local Ollama turn is 0 by definition. Anything the backend priced itself is trusted.

Reads are cached on the files' mtime and size, so the tab can poll every few seconds
without re-parsing the ledger.
"""

from __future__ import annotations

import datetime as _dt
import json
import logging
import os
import threading
from zoneinfo import ZoneInfo

from . import _host, budget, models

_log = logging.getLogger(__name__)

__all__ = ['ROW_FIELDS', 'metrics_path', 'record_turn', 'section_zero']

TZ = ZoneInfo('Europe/Amsterdam')

METRICS_NAME = 'zero_metrics.jsonl'
TOOL_LOG_NAME = 'zero_tool_log.jsonl'
INSTALL_LOG_NAME = 'zero_installs.jsonl'
BUDGET_STATE_NAME = 'zero_budget_state.json'

#: Every column of a ledger row, in order. A row has these keys and no others.
ROW_FIELDS = (
    'ts',
    'turn_id',
    'session_id',
    'actor',
    'provider',
    'model',
    'backend',
    'stage',
    'input_tokens',
    'output_tokens',
    'cache_read',
    'cache_write',
    'api_usd',
    'latency_ms',
    'ttft_ms',
    'tool_calls',
    'tool_names',
    'tool_errors',
    'danger_calls',
    'confirmations',
    'context_tokens_est',
    'history_turns',
    'compacted',
    'budget_level',
    'budget_reason',
    'stop_reason',
    'error',
    'cancelled',
)

#: Where every number in the tab comes from, named in the tab itself.
NOTES = (
    (
        'One row per turn is appended to data/runtime/zero_metrics.jsonl when the turn ends, '
        'whatever its outcome — finished, cancelled, budget-blocked or failed.'
    ),
    (
        'api_usd is API-EQUIVALENT, not money spent. A subscription turn spends the Claude Code '
        'seat, not the API; it is priced with the host price table so it can be compared with a '
        'hosted provider. A local Ollama turn is 0 by definition.'
    ),
    (
        'Token counts come from the backend when it reports usage; a backend that reports none '
        'leaves the row at 0 rather than guessing.'
    ),
    (
        'by_tool is the tool audit log (data/runtime/zero_tool_log.jsonl), written by '
        'toolmap_exec on every execution, including the ones that failed.'
    ),
    'Latency is wall clock for the whole turn, tool calls included; ttft is the time to the first text_delta.',
)

SOURCES = (
    'data/runtime/zero_metrics.jsonl',
    'data/runtime/zero_tool_log.jsonl',
    'data/runtime/zero_installs.jsonl',
    'data/runtime/zero_budget_state.json',
)

#: How many rows the tab shows under 'recent'.
RECENT_TURNS = 25
RECENT_ERRORS = 10

_LOCK = threading.Lock()
_cache: dict = {}


# ── paths ────────────────────────────────────────────────────────────────────


def metrics_path() -> str:
    """``data/runtime/zero_metrics.jsonl`` -- the permanent per-turn ledger."""
    return os.path.join(_host.runtime_dir(), METRICS_NAME)


def tool_log_path() -> str:
    """``data/runtime/zero_tool_log.jsonl`` -- one line per executed tool."""
    return os.path.join(_host.runtime_dir(), TOOL_LOG_NAME)


def install_log_path() -> str:
    """``data/runtime/zero_installs.jsonl`` -- one line per Ollama install."""
    return os.path.join(_host.runtime_dir(), INSTALL_LOG_NAME)


def _now() -> _dt.datetime:
    return _dt.datetime.now(TZ)


# ── writing one row ──────────────────────────────────────────────────────────


def _price_usd(row: dict) -> float:
    """The API-equivalent dollars of one turn (see the module docstring)."""
    given = row.get('api_usd')
    if given is not None:
        try:
            return round(float(given), 6)
        except (TypeError, ValueError):
            pass
    provider = str(row.get('provider') or '')
    if provider in budget.LOCAL_PROVIDERS:
        return 0.0
    tin = int(row.get('input_tokens') or 0)
    tout = int(row.get('output_tokens') or 0)
    model = str(row.get('model') or '')
    if provider in ('subscription', 'anthropic'):
        meter = _host.quota_meter()
        if meter is None:
            return 0.0
        try:
            return round(
                float(
                    meter.price_tokens(
                        model, tin, tout, int(row.get('cache_write') or 0), int(row.get('cache_read') or 0)
                    )
                    or 0.0
                ),
                6,
            )
        except Exception as exc:  # noqa: BLE001 - pricing is bookkeeping, never fatal
            _log.debug('agent_zero.metrics: price_tokens failed (%s)', exc)
            return 0.0
    return _catalog_usd(provider, model, tin, tout)


def _catalog_usd(provider: str, model: str, tin: int, tout: int) -> float:
    """List price from ``models_catalog.json`` (``price_in``/``price_out`` per 1M)."""
    try:
        entry = next((m for m in models.seed_models(provider) if m.get('id') == model), None)
    except Exception as exc:  # noqa: BLE001 - an unreadable catalogue prices at 0
        _log.debug('agent_zero.metrics: catalogue lookup failed (%s)', exc)
        return 0.0
    if not entry or entry.get('price_in') is None:
        return 0.0
    price_in = float(entry.get('price_in') or 0.0)
    price_out = float(entry.get('price_out') or 0.0)
    return round((tin * price_in + tout * price_out) / 1_000_000.0, 6)


def _normalise(row: dict) -> dict:
    """``row`` -> exactly :data:`ROW_FIELDS`, with every value its declared type."""
    out = {
        'ts': str(row.get('ts') or _now().isoformat(timespec='seconds')),
        'turn_id': str(row.get('turn_id') or ''),
        'session_id': str(row.get('session_id') or ''),
        'actor': str(row.get('actor') or ''),
        'provider': str(row.get('provider') or ''),
        'model': str(row.get('model') or ''),
        'backend': str(row.get('backend') or ''),
        'stage': str(row.get('stage') or 'chat'),
        'input_tokens': int(row.get('input_tokens') or 0),
        'output_tokens': int(row.get('output_tokens') or 0),
        'cache_read': int(row.get('cache_read') or 0),
        'cache_write': int(row.get('cache_write') or 0),
        'api_usd': 0.0,
        'latency_ms': int(row.get('latency_ms') or 0),
        'ttft_ms': int(row['ttft_ms']) if row.get('ttft_ms') is not None else None,
        'tool_calls': int(row.get('tool_calls') or 0),
        'tool_names': [str(n) for n in (row.get('tool_names') or [])],
        'tool_errors': int(row.get('tool_errors') or 0),
        'danger_calls': int(row.get('danger_calls') or 0),
        'confirmations': int(row.get('confirmations') or 0),
        'context_tokens_est': int(row.get('context_tokens_est') or 0),
        'history_turns': int(row.get('history_turns') or 0),
        'compacted': bool(row.get('compacted')),
        'budget_level': str(row.get('budget_level') or ''),
        'budget_reason': str(row.get('budget_reason') or ''),
        'stop_reason': str(row.get('stop_reason') or ''),
        'error': str(row['error']) if row.get('error') else None,
        'cancelled': bool(row.get('cancelled')),
    }
    out['api_usd'] = _price_usd(dict(row, input_tokens=out['input_tokens'], output_tokens=out['output_tokens']))
    return out


def record_turn(row: dict) -> dict:
    """Append one turn to the ledger and mirror it into the host's token stores.

    Returns the row as written. Nothing here raises: a metrics failure must never be
    the reason a chat turn fails.
    """
    written = _normalise(dict(row or {}))
    try:
        with open(metrics_path(), 'a', encoding='utf-8') as fh:
            fh.write(json.dumps(written) + '\n')
    except OSError as exc:
        _log.warning('agent_zero.metrics: cannot append to %s (%s)', METRICS_NAME, exc)
    _mirror_host(written, row or {})
    return written


def _mirror_host(written: dict, raw: dict) -> None:
    """Feed the dashboard's token store and the LLM audit log. Never raises."""
    try:
        _host.record_token_usage(
            written['model'],
            written['input_tokens'],
            written['output_tokens'],
            stage='agent_zero_v2',
        )
    except Exception as exc:  # noqa: BLE001 - host metrics are best effort
        _log.debug('agent_zero.metrics: record_token_usage failed (%s)', exc)
    try:
        audit = _host.llm_audit()
    except Exception as exc:  # noqa: BLE001 - a broken host must never reach a turn
        _log.debug('agent_zero.metrics: llm_audit() failed (%s)', exc)
        return
    if audit is None or not hasattr(audit, 'record'):
        return
    try:
        audit.record(
            source='agent_zero',
            llm=written['model'],
            backend=written['provider'],
            stage='agent_zero_v2',
            input_tokens=written['input_tokens'],
            output_tokens=written['output_tokens'],
            cost_usd=written['api_usd'],
            duration_ms=written['latency_ms'],
            request=str(raw.get('message') or '')[:300],
            response=str(raw.get('text') or '')[:500],
        )
    except Exception as exc:  # noqa: BLE001 - auditing must never break a turn
        _log.debug('agent_zero.metrics: llm_audit.record failed (%s)', exc)


# ── reading the ledgers ──────────────────────────────────────────────────────


def _stat(path: str) -> tuple:
    try:
        info = os.stat(path)
    except OSError:
        return (0, 0.0)
    return (info.st_size, info.st_mtime)


def _read_jsonl(path: str, fresh: bool = False) -> list[dict]:
    """Every parsable row of a JSONL file, cached on (size, mtime)."""
    key = f'jsonl:{path}'
    stamp = _stat(path)
    with _LOCK:
        hit = _cache.get(key)
        if not fresh and hit is not None and hit[0] == stamp:
            return hit[1]
    rows: list[dict] = []
    try:
        with open(path, encoding='utf-8') as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    parsed = json.loads(line)
                except ValueError:
                    continue
                if isinstance(parsed, dict):
                    rows.append(parsed)
    except FileNotFoundError:
        rows = []
    except OSError as exc:
        _log.warning('agent_zero.metrics: cannot read %s (%s)', path, exc)
        rows = []
    with _LOCK:
        _cache[key] = (stamp, rows)
    return rows


def _date_of(value) -> str:
    """``YYYY-MM-DD`` from an ISO string or an epoch float; ``''`` when unusable."""
    if isinstance(value, (int, float)):
        return _dt.datetime.fromtimestamp(float(value), TZ).strftime('%Y-%m-%d')
    text = str(value or '')
    return text[:10] if len(text) >= 10 and text[4] == '-' else ''


def _p(values: list, pct: float) -> int:
    """Nearest-rank percentile of a list of numbers; 0 when there is nothing."""
    numbers = sorted(int(v or 0) for v in values if v is not None)
    if not numbers:
        return 0
    index = max(0, min(len(numbers) - 1, round(pct / 100.0 * len(numbers) + 0.5) - 1))
    return numbers[index]


def _range(days: int, now: _dt.datetime) -> str:
    """The first date included. ``''`` when ``days`` is 0 (all time)."""
    if not days:
        return ''
    return (now.date() - _dt.timedelta(days=max(0, int(days) - 1))).isoformat()


def _in_range(row: dict, field: str, start: str) -> bool:
    date = _date_of(row.get(field))
    if not date:
        return not start
    return not start or date >= start


# ── the Metrics-hub section ──────────────────────────────────────────────────


def _totals(rows: list[dict], tool_rows: list[dict], install_rows: list[dict]) -> dict:
    latencies = [r.get('latency_ms') for r in rows]
    ttfts = [r.get('ttft_ms') for r in rows if r.get('ttft_ms') is not None]
    return {
        'turns': len(rows),
        'sessions': len({str(r.get('session_id') or '') for r in rows if r.get('session_id')}),
        'input_tokens': sum(int(r.get('input_tokens') or 0) for r in rows),
        'output_tokens': sum(int(r.get('output_tokens') or 0) for r in rows),
        'cache_read': sum(int(r.get('cache_read') or 0) for r in rows),
        'cache_write': sum(int(r.get('cache_write') or 0) for r in rows),
        'api_usd': round(sum(float(r.get('api_usd') or 0.0) for r in rows), 6),
        'subscription_turns': sum(1 for r in rows if r.get('provider') == 'subscription'),
        'local_turns': sum(1 for r in rows if r.get('provider') in budget.LOCAL_PROVIDERS),
        'api_turns': sum(
            1 for r in rows if r.get('provider') not in budget.LOCAL_PROVIDERS and r.get('provider') != 'subscription'
        ),
        'tool_calls': sum(int(r.get('tool_calls') or 0) for r in rows),
        'tool_errors': sum(int(r.get('tool_errors') or 0) for r in rows),
        'danger_calls': sum(int(r.get('danger_calls') or 0) for r in rows),
        'confirmations': sum(int(r.get('confirmations') or 0) for r in rows),
        'p50_latency_ms': _p(latencies, 50),
        'p95_latency_ms': _p(latencies, 95),
        'p50_ttft_ms': _p(ttfts, 50),
        'budget_blocks': sum(1 for r in rows if r.get('budget_level') == 'blocked'),
        'errors': sum(1 for r in rows if r.get('error')),
        'cancelled': sum(1 for r in rows if r.get('cancelled')),
        'compactions': sum(1 for r in rows if r.get('stage') == 'compaction' or r.get('compacted')),
        'installs': len(install_rows),
    }


def _by_model(rows: list[dict]) -> list[dict]:
    buckets: dict[tuple, dict] = {}
    for row in rows:
        key = (str(row.get('provider') or ''), str(row.get('model') or ''))
        bucket = buckets.setdefault(
            key,
            {
                'provider': key[0],
                'model': key[1],
                'turns': 0,
                'input_tokens': 0,
                'output_tokens': 0,
                'api_usd': 0.0,
                'p50_latency_ms': 0,
                'tool_calls': 0,
                'errors': 0,
                '_lat': [],
            },
        )
        bucket['turns'] += 1
        bucket['input_tokens'] += int(row.get('input_tokens') or 0)
        bucket['output_tokens'] += int(row.get('output_tokens') or 0)
        bucket['api_usd'] += float(row.get('api_usd') or 0.0)
        bucket['tool_calls'] += int(row.get('tool_calls') or 0)
        bucket['errors'] += 1 if row.get('error') else 0
        bucket['_lat'].append(row.get('latency_ms'))
    out = []
    for bucket in buckets.values():
        bucket['p50_latency_ms'] = _p(bucket.pop('_lat'), 50)
        bucket['api_usd'] = round(bucket['api_usd'], 6)
        out.append(bucket)
    out.sort(key=lambda b: (-b['turns'], b['model']))
    return out


def _by_tool(rows: list[dict]) -> list[dict]:
    buckets: dict[str, dict] = {}
    for row in rows:
        name = str(row.get('tool') or row.get('name') or '')
        if not name:
            continue
        bucket = buckets.setdefault(
            name,
            {'name': name, 'calls': 0, 'errors': 0, 'p50_ms': 0, 'risk': str(row.get('risk') or 'read'), '_ms': []},
        )
        bucket['calls'] += 1
        bucket['errors'] += 0 if row.get('ok') else 1
        bucket['_ms'].append(row.get('ms'))
        if row.get('risk'):
            bucket['risk'] = str(row['risk'])
    out = []
    for bucket in buckets.values():
        bucket['p50_ms'] = _p(bucket.pop('_ms'), 50)
        out.append(bucket)
    out.sort(key=lambda b: (-b['calls'], b['name']))
    return out


def _daily(rows: list[dict], start: str, now: _dt.datetime) -> dict:
    dates = [d for d in (_date_of(r.get('ts')) for r in rows) if d]
    first = start or (min(dates) if dates else now.date().isoformat())
    try:
        cursor = _dt.date.fromisoformat(first)
    except ValueError:
        cursor = now.date()
    last = now.date()
    if dates:
        try:
            last = max(last, _dt.date.fromisoformat(max(dates)))
        except ValueError:
            pass
    keys: list[str] = []
    while cursor <= last and len(keys) < 400:
        keys.append(cursor.isoformat())
        cursor += _dt.timedelta(days=1)
    index = {key: i for i, key in enumerate(keys)}
    series = {
        'input': [0] * len(keys),
        'output': [0] * len(keys),
        'turns': [0] * len(keys),
        'api_usd': [0.0] * len(keys),
    }
    for row in rows:
        slot = index.get(_date_of(row.get('ts')))
        if slot is None:
            continue
        series['input'][slot] += int(row.get('input_tokens') or 0)
        series['output'][slot] += int(row.get('output_tokens') or 0)
        series['turns'][slot] += 1
        series['api_usd'][slot] += float(row.get('api_usd') or 0.0)
    series['api_usd'] = [round(v, 6) for v in series['api_usd']]
    return {
        'keys': keys,
        'bucket': 'day',
        'series': [
            {'id': 'input', 'label': 'Input tokens', 'values': series['input']},
            {'id': 'output', 'label': 'Output tokens', 'values': series['output']},
            {'id': 'turns', 'label': 'Turns', 'values': series['turns']},
            {'id': 'api_usd', 'label': 'API-equivalent $', 'values': series['api_usd']},
        ],
    }


def _recent(rows: list[dict]) -> list[dict]:
    keep = (
        'ts',
        'session_id',
        'provider',
        'model',
        'input_tokens',
        'output_tokens',
        'latency_ms',
        'tool_calls',
        'stop_reason',
        'error',
    )
    return [{key: row.get(key) for key in keep} for row in rows[-RECENT_TURNS:][::-1]]


def _safe(call, default):
    try:
        return call()
    except Exception as exc:  # noqa: BLE001 - the tab must render even when a part fails
        _log.warning('agent_zero.metrics: %s', exc)
        return default


def section_zero(days: int = 30, now=None, fresh: bool = False) -> dict:
    """The Metrics-hub ``zero`` section (CONTRACT F). ``days=0`` means all time."""
    when = now or _now()
    if isinstance(when, (int, float)):
        when = _dt.datetime.fromtimestamp(float(when), TZ)
    start = _range(int(days or 0), when)

    rows = [r for r in _read_jsonl(metrics_path(), fresh) if _in_range(r, 'ts', start)]
    tool_rows = [r for r in _read_jsonl(tool_log_path(), fresh) if _in_range(r, 'ts', start)]
    install_rows = [r for r in _read_jsonl(install_log_path(), fresh) if _in_range(r, 'ts', start)]

    return {
        'totals': _totals(rows, tool_rows, install_rows),
        'by_model': _by_model(rows),
        'by_tool': _by_tool(tool_rows),
        'daily': _daily(rows, start, when),
        'budget': _safe(budget.state, {}),
        'selected': _safe(models.get_selection, {}),
        'recent_turns': _recent(rows),
        'recent_errors': [row for row in rows if row.get('error')][-RECENT_ERRORS:][::-1],
        'installs': install_rows,
        'notes': list(NOTES),
        'sources': list(SOURCES),
    }
