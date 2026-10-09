# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Agent Zero v2 -- the per-turn ledger and the Metrics-hub section (CONTRACT F).

Synthetic rows are written straight into a temporary runtime dir, so nothing here
touches the live dashboard, the network or a GPU.
"""

from __future__ import annotations

import datetime as _dt
import json
import os

import pytest

from zyg_dashboard.agent_zero import _host, metrics

TZ = metrics.TZ
NOW = _dt.datetime(2026, 10, 8, 12, 0, 0, tzinfo=TZ)


def _ts(days_ago: int, hour: int = 9) -> str:
    return (NOW - _dt.timedelta(days=days_ago)).replace(hour=hour).isoformat(timespec='seconds')


@pytest.fixture
def runtime(tmp_path, monkeypatch):
    """A tmp runtime dir with five turn rows, three tool rows and two installs."""
    monkeypatch.setattr(_host, 'runtime_dir', lambda: str(tmp_path))
    monkeypatch.setattr(_host, 'data_dir', lambda: str(tmp_path))
    monkeypatch.setattr(_host, 'record_token_usage', lambda *a, **k: None)
    monkeypatch.setattr(_host, 'llm_audit', lambda: None)
    monkeypatch.setattr(_host, 'quota_meter', lambda: None)
    monkeypatch.setattr(metrics, '_cache', {})

    rows = [
        # four rows inside the 7-day window
        {
            'ts': _ts(0),
            'turn_id': 't1',
            'session_id': 's1',
            'provider': 'subscription',
            'model': 'claude-opus-5',
            'backend': 'claude_cli',
            'stage': 'chat',
            'input_tokens': 1000,
            'output_tokens': 100,
            'api_usd': 0.5,
            'latency_ms': 1000,
            'ttft_ms': 200,
            'tool_calls': 2,
            'tool_names': ['zero_index', 'zero_find'],
            'tool_errors': 1,
            'danger_calls': 0,
            'confirmations': 0,
            'stop_reason': 'end_turn',
        },
        {
            'ts': _ts(1),
            'turn_id': 't2',
            'session_id': 's1',
            'provider': 'subscription',
            'model': 'claude-opus-5',
            'backend': 'claude_cli',
            'stage': 'chat',
            'input_tokens': 2000,
            'output_tokens': 200,
            'api_usd': 1.0,
            'latency_ms': 2000,
            'ttft_ms': 400,
            'tool_calls': 1,
            'tool_names': ['zero_call'],
            'danger_calls': 1,
            'confirmations': 1,
            'stop_reason': 'needs_confirmation',
        },
        {
            'ts': _ts(2),
            'turn_id': 't3',
            'session_id': 's2',
            'provider': 'ollama',
            'model': 'qwen3.5:9b',
            'backend': 'ollama',
            'stage': 'chat',
            'input_tokens': 500,
            'output_tokens': 50,
            'latency_ms': 3000,
            'tool_calls': 0,
            'stop_reason': 'end_turn',
            'cancelled': True,
        },
        {
            'ts': _ts(3),
            'turn_id': 't4',
            'session_id': 's2',
            'provider': 'ollama',
            'model': 'qwen3.5:9b',
            'backend': 'ollama',
            'stage': 'compaction',
            'input_tokens': 300,
            'output_tokens': 30,
            'latency_ms': 4000,
            'stop_reason': 'error',
            'error': 'backend exploded',
            'budget_level': 'blocked',
        },
        # one row OUTSIDE the 7-day window
        {
            'ts': _ts(30),
            'turn_id': 't5',
            'session_id': 's3',
            'provider': 'openai',
            'model': 'gpt-5',
            'backend': 'openai_compat',
            'stage': 'chat',
            'input_tokens': 9000,
            'output_tokens': 900,
            'api_usd': 2.0,
            'latency_ms': 5000,
            'stop_reason': 'end_turn',
        },
    ]
    # a real ledger is appended to, so it is in chronological order
    rows.sort(key=lambda r: r['ts'])
    path = os.path.join(str(tmp_path), metrics.METRICS_NAME)
    with open(path, 'w', encoding='utf-8') as fh:
        fh.writelines(json.dumps(metrics._normalise(row)) + '\n' for row in rows)

    tools = [
        {'ts': _ts(0), 'actor': 'ad', 'tool': 'zero_index', 'risk': 'read', 'ok': True, 'ms': 10},
        {'ts': _ts(0), 'actor': 'ad', 'tool': 'zero_index', 'risk': 'read', 'ok': False, 'ms': 30},
        {'ts': _ts(1), 'actor': 'ad', 'tool': 'pipeline.stop_all', 'risk': 'danger', 'ok': True, 'ms': 200},
        {'ts': _ts(30), 'actor': 'ad', 'tool': 'zero_find', 'risk': 'read', 'ok': True, 'ms': 5},
    ]
    with open(os.path.join(str(tmp_path), metrics.TOOL_LOG_NAME), 'w', encoding='utf-8') as fh:
        fh.writelines(json.dumps(row) + '\n' for row in tools)

    installs = [
        {'ts': (NOW - _dt.timedelta(days=1)).timestamp(), 'model': 'qwen3.5:9b', 'status': 'done', 'seconds': 42},
        {'ts': (NOW - _dt.timedelta(days=30)).timestamp(), 'model': 'gpt-oss:20b', 'status': 'done', 'seconds': 99},
    ]
    with open(os.path.join(str(tmp_path), metrics.INSTALL_LOG_NAME), 'w', encoding='utf-8') as fh:
        fh.writelines(json.dumps(row) + '\n' for row in installs)

    return tmp_path


# ── writing ──────────────────────────────────────────────────────────────────


def test_record_turn_writes_exactly_the_contract_columns(tmp_path, monkeypatch):
    monkeypatch.setattr(_host, 'runtime_dir', lambda: str(tmp_path))
    monkeypatch.setattr(_host, 'record_token_usage', lambda *a, **k: None)
    monkeypatch.setattr(_host, 'llm_audit', lambda: None)
    monkeypatch.setattr(_host, 'quota_meter', lambda: None)

    written = metrics.record_turn(
        {
            'turn_id': 'x1',
            'session_id': 's9',
            'provider': 'ollama',
            'model': 'qwen3.5:9b',
            'input_tokens': 7,
            'output_tokens': 3,
            'message': 'hello',
            'text': 'hi',
        }
    )
    assert tuple(written) == metrics.ROW_FIELDS
    assert written['api_usd'] == 0.0  # local is free by definition
    assert written['ttft_ms'] is None
    assert written['error'] is None
    assert written['stage'] == 'chat'

    with open(os.path.join(str(tmp_path), metrics.METRICS_NAME), encoding='utf-8') as fh:
        lines = [json.loads(line) for line in fh if line.strip()]
    assert len(lines) == 1
    assert tuple(lines[0]) == metrics.ROW_FIELDS


def test_record_turn_mirrors_into_the_host(tmp_path, monkeypatch):
    seen: dict = {}

    class _Audit:
        def record(self, **kw):
            seen['audit'] = kw

    monkeypatch.setattr(_host, 'runtime_dir', lambda: str(tmp_path))
    monkeypatch.setattr(_host, 'record_token_usage', lambda *a, **k: seen.setdefault('tokens', (a, k)))
    monkeypatch.setattr(_host, 'llm_audit', lambda: _Audit())
    monkeypatch.setattr(_host, 'quota_meter', lambda: None)

    metrics.record_turn(
        {
            'turn_id': 'x2',
            'provider': 'ollama',
            'model': 'qwen3.5:9b',
            'input_tokens': 11,
            'output_tokens': 5,
            'message': 'm' * 600,
            'text': 't' * 900,
        }
    )
    assert seen['tokens'][0] == ('qwen3.5:9b', 11, 5)
    assert seen['tokens'][1] == {'stage': 'agent_zero_v2'}
    assert seen['audit']['source'] == 'agent_zero'
    assert seen['audit']['stage'] == 'agent_zero_v2'
    assert len(seen['audit']['request']) == 300
    assert len(seen['audit']['response']) == 500


def test_a_broken_host_never_breaks_a_turn(tmp_path, monkeypatch):
    def _boom(*a, **k):
        raise RuntimeError('host is down')

    monkeypatch.setattr(_host, 'runtime_dir', lambda: str(tmp_path))
    monkeypatch.setattr(_host, 'record_token_usage', _boom)
    monkeypatch.setattr(_host, 'llm_audit', _boom)
    monkeypatch.setattr(_host, 'quota_meter', lambda: None)

    written = metrics.record_turn({'turn_id': 'x3', 'provider': 'ollama', 'model': 'm'})
    assert written['turn_id'] == 'x3'


# ── reading: CONTRACT F ──────────────────────────────────────────────────────


def test_section_zero_has_the_contract_shape(runtime):
    section = metrics.section_zero(7, now=NOW, fresh=True)
    assert set(section) == {
        'totals',
        'by_model',
        'by_tool',
        'daily',
        'budget',
        'selected',
        'recent_turns',
        'recent_errors',
        'installs',
        'notes',
        'sources',
    }
    assert set(section['totals']) == {
        'turns',
        'sessions',
        'input_tokens',
        'output_tokens',
        'cache_read',
        'cache_write',
        'api_usd',
        'subscription_turns',
        'local_turns',
        'api_turns',
        'tool_calls',
        'tool_errors',
        'danger_calls',
        'confirmations',
        'p50_latency_ms',
        'p95_latency_ms',
        'p50_ttft_ms',
        'budget_blocks',
        'errors',
        'cancelled',
        'compactions',
        'installs',
    }
    assert set(section['by_model'][0]) == {
        'provider',
        'model',
        'turns',
        'input_tokens',
        'output_tokens',
        'api_usd',
        'p50_latency_ms',
        'tool_calls',
        'errors',
    }
    assert set(section['by_tool'][0]) == {'name', 'calls', 'errors', 'p50_ms', 'risk'}
    assert set(section['daily']) == {'keys', 'bucket', 'series'}
    assert section['daily']['bucket'] == 'day'
    assert [s['id'] for s in section['daily']['series']] == ['input', 'output', 'turns', 'api_usd']
    assert [s['label'] for s in section['daily']['series']] == [
        'Input tokens',
        'Output tokens',
        'Turns',
        'API-equivalent $',
    ]
    assert list(section['sources']) == list(metrics.SOURCES)
    assert section['notes']


def test_section_zero_totals_add_up(runtime):
    totals = metrics.section_zero(7, now=NOW, fresh=True)['totals']
    assert totals['turns'] == 4  # the 30-day-old row is out of the window
    assert totals['sessions'] == 2
    assert totals['input_tokens'] == 1000 + 2000 + 500 + 300
    assert totals['output_tokens'] == 100 + 200 + 50 + 30
    assert totals['api_usd'] == 1.5
    assert totals['subscription_turns'] == 2
    assert totals['local_turns'] == 2
    assert totals['api_turns'] == 0
    assert totals['tool_calls'] == 3
    assert totals['tool_errors'] == 1
    assert totals['danger_calls'] == 1
    assert totals['confirmations'] == 1
    assert totals['errors'] == 1
    assert totals['cancelled'] == 1
    assert totals['compactions'] == 1
    assert totals['budget_blocks'] == 1
    assert totals['installs'] == 1  # the 30-day-old install is out of the window
    assert totals['p50_latency_ms'] in (2000, 3000)
    assert totals['p95_latency_ms'] == 4000
    assert totals['p50_ttft_ms'] in (200, 400)


def test_by_model_and_by_tool(runtime):
    section = metrics.section_zero(7, now=NOW, fresh=True)
    by_model = section['by_model']
    assert len(by_model) == 2
    assert [b['turns'] for b in by_model] == sorted([b['turns'] for b in by_model], reverse=True)
    claude = next(b for b in by_model if b['model'] == 'claude-opus-5')
    assert claude['provider'] == 'subscription'
    assert claude['turns'] == 2
    assert claude['input_tokens'] == 3000
    assert claude['output_tokens'] == 300
    assert claude['api_usd'] == 1.5
    assert claude['tool_calls'] == 3
    assert claude['errors'] == 0
    local = next(b for b in by_model if b['model'] == 'qwen3.5:9b')
    assert local['errors'] == 1
    assert local['api_usd'] == 0.0

    by_tool = section['by_tool']
    assert [b['name'] for b in by_tool] == ['zero_index', 'pipeline.stop_all']
    index = by_tool[0]
    assert index['calls'] == 2
    assert index['errors'] == 1
    assert index['risk'] == 'read'
    assert index['p50_ms'] in (10, 30)
    assert by_tool[1]['risk'] == 'danger'


def test_daily_series_lands_on_the_right_days(runtime):
    daily = metrics.section_zero(7, now=NOW, fresh=True)['daily']
    assert len(daily['keys']) == 7
    assert daily['keys'][-1] == NOW.date().isoformat()
    assert daily['keys'][0] == (NOW.date() - _dt.timedelta(days=6)).isoformat()
    series = {s['id']: s['values'] for s in daily['series']}
    assert all(len(values) == 7 for values in series.values())
    assert sum(series['turns']) == 4
    assert sum(series['input']) == 3800
    assert sum(series['output']) == 380
    assert round(sum(series['api_usd']), 6) == 1.5
    assert series['turns'][-1] == 1  # today
    assert series['input'][-1] == 1000


def test_recent_rows_are_newest_first(runtime):
    section = metrics.section_zero(7, now=NOW, fresh=True)
    recent = section['recent_turns']
    assert len(recent) == 4
    assert set(recent[0]) == {
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
    }
    assert recent[0]['ts'] > recent[-1]['ts']
    assert len(section['recent_errors']) == 1
    assert section['recent_errors'][0]['error'] == 'backend exploded'
    assert len(section['installs']) == 1
    assert section['installs'][0]['model'] == 'qwen3.5:9b'


def test_days_zero_is_all_time(runtime):
    seven = metrics.section_zero(7, now=NOW, fresh=True)
    everything = metrics.section_zero(0, now=NOW, fresh=True)

    assert seven['totals']['turns'] == 4
    assert everything['totals']['turns'] == 5
    assert everything['totals']['api_turns'] == 1
    assert everything['totals']['input_tokens'] == seven['totals']['input_tokens'] + 9000
    assert everything['totals']['installs'] == 2

    assert {b['model'] for b in seven['by_model']} == {'claude-opus-5', 'qwen3.5:9b'}
    assert {b['model'] for b in everything['by_model']} == {'claude-opus-5', 'qwen3.5:9b', 'gpt-5'}
    assert 'zero_find' not in {b['name'] for b in seven['by_tool']}
    assert 'zero_find' in {b['name'] for b in everything['by_tool']}
    assert len(everything['daily']['keys']) == 31


def test_empty_runtime_still_renders(tmp_path, monkeypatch):
    monkeypatch.setattr(_host, 'runtime_dir', lambda: str(tmp_path))
    monkeypatch.setattr(metrics, '_cache', {})
    section = metrics.section_zero(7, now=NOW, fresh=True)
    assert section['totals']['turns'] == 0
    assert section['by_model'] == []
    assert section['by_tool'] == []
    assert section['recent_turns'] == []
    assert len(section['daily']['keys']) == 7
    assert all(sum(s['values']) == 0 for s in section['daily']['series'])


def test_reads_are_cached_on_mtime(runtime):
    first = metrics.section_zero(7, now=NOW, fresh=True)['totals']['turns']
    path = os.path.join(str(runtime), metrics.METRICS_NAME)
    before = os.stat(path)
    with open(path, 'a', encoding='utf-8') as fh:
        fh.write(json.dumps(metrics._normalise({'ts': _ts(0), 'turn_id': 't6', 'session_id': 's4'})) + '\n')
    os.utime(path, (before.st_atime, before.st_mtime))  # same mtime, bigger file

    # size changed, so the cache key changed and the new row is seen
    assert metrics.section_zero(7, now=NOW)['totals']['turns'] == first + 1
