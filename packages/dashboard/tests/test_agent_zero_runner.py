# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Unit tests for agent_zero.runner and agent_zero.prompt.

Every turn runs on the deterministic fake backend: ``contracts.BACKEND_FOR`` is extended
with a ``fake`` provider, ``models.get_selection`` returns it, and ``toolmap_exec.execute``
is replaced by a stub that answers ok for ``zero_index`` and ``needs_confirmation`` for
the danger tool. No dashboard, no network, no GPU -- ``_host.data_dir``/``runtime_dir``
point into tmp_path, so the session store, the budget state and the metrics ledger are
all written inside the test's own directory.
"""

import json
import time

import pytest

from zyg_dashboard.agent_zero import (
    _host,
    backends,
    budget,
    contracts,
    memory,
    metrics,
    models,
    prompt,
    runner,
    toolmap_exec,
)

DANGER_TOOL = 'pipeline.stop_all'


# ── fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture
def zero(tmp_path, monkeypatch):
    """A clean runtime: tmp dirs, the fake provider selected, a stubbed tool layer."""
    runtime = tmp_path / 'runtime'
    runtime.mkdir()
    monkeypatch.setattr(_host, 'data_dir', lambda: str(tmp_path))
    monkeypatch.setattr(_host, 'runtime_dir', lambda: str(runtime))
    monkeypatch.setattr(_host, 'record_token_usage', lambda *a, **k: None)
    monkeypatch.setattr(_host, 'llm_audit', lambda: None)
    monkeypatch.setattr(_host, 'quota_meter', lambda: None)

    monkeypatch.setitem(contracts.BACKEND_FOR, 'fake', 'fake')
    monkeypatch.setattr(models, 'get_selection', lambda: {'provider': 'fake', 'model': 'fake-1'})
    monkeypatch.setattr(budget, '_meter_cache', {'ts': 0.0, 'snapshot': None})
    monkeypatch.setattr(metrics, '_cache', {})

    calls = []

    def fake_execute(name, args, cookie='', csrf='', confirmed=False, actor=''):
        calls.append({'name': name, 'args': dict(args or {}), 'confirmed': confirmed, 'actor': actor})
        tool = str((args or {}).get('tool') or '') if name == 'zero_call' else name
        if tool == DANGER_TOOL and not confirmed:
            return {
                'ok': False,
                'text': f'CONFIRMATION REQUIRED: {DANGER_TOOL} — ask the user first.',
                'ms': 3,
                'risk': 'danger',
                'needs_confirmation': True,
                'confirm_id': 'cid-1',
            }
        return {
            'ok': True,
            'text': f'{tool} ran',
            'ms': 7,
            'risk': 'read',
            'needs_confirmation': False,
            'confirm_id': None,
        }

    monkeypatch.setattr(toolmap_exec, 'execute', fake_execute)
    monkeypatch.setattr(toolmap_exec, 'pending_tool', lambda cid: DANGER_TOOL)
    monkeypatch.setattr(
        toolmap_exec,
        'execute_confirmed',
        lambda cid, cookie='', csrf='', actor='': {
            'ok': True,
            'text': f'{DANGER_TOOL} executed after approval ({cid})',
            'ms': 11,
            'risk': 'danger',
            'needs_confirmation': False,
            'confirm_id': None,
        },
    )
    runner.TURNS.clear()
    yield {'runtime': runtime, 'calls': calls}
    runner.TURNS.clear()


def _session():
    return memory.new_session('Ad', 'fake', 'fake-1')['id']


def _drain(turn_id, timeout=10.0):
    """Every event of a turn, waiting until it is done."""
    events, seq, deadline = [], 0, time.time() + timeout
    while time.time() < deadline:
        fresh = runner.wait_events(turn_id, seq, timeout=1.0)
        if fresh:
            events.extend(fresh)
            seq = fresh[-1]['seq']
        if any(e['type'] == 'done' for e in events) and runner.get_turn(turn_id)['done']:
            return events
    raise AssertionError(f'turn {turn_id} did not finish: {events}')


def _ledger():
    with open(metrics.metrics_path(), encoding='utf-8') as fh:
        return [json.loads(line) for line in fh if line.strip()]


# ── the backend registry ─────────────────────────────────────────────────────


def test_backends_get_and_probe(zero):
    from zyg_dashboard.agent_zero.backends import fake

    assert backends.get('fake') is fake
    assert fake.probe()['ok'] is True
    with pytest.raises(ValueError):
        backends.get('nope')
    probes = backends.probe_all()
    assert probes['fake'] == {'ok': True, 'detail': fake.probe()['detail']}
    assert set(probes) >= set(contracts.BACKEND_FOR)


# ── the system prompt ────────────────────────────────────────────────────────


def test_system_prompt_stays_small(zero):
    session = memory.get_session(_session())
    system, messages, est = prompt.build(
        session, 'hello', {'provider': 'fake', 'model': 'fake-1'}, budget.load_config()
    )
    assert contracts.estimate_tokens(prompt.fixed_text('Ad')) <= 450
    assert contracts.estimate_tokens(system) <= 2100
    assert system.startswith('You are Zero,')
    assert 'zero_find' in system and 'STATE SNAPSHOT' in system and 'Budget:' in system
    assert messages == [{'role': 'user', 'content': 'hello'}]
    assert est >= contracts.estimate_tokens(system)


def test_image_message_blocks(zero):
    session = memory.get_session(_session())
    _, png, _ = prompt.build(session, 'what is this', {}, budget.load_config(), image_b64='iVBORw0KGgo=')
    _, jpg, _ = prompt.build(session, 'what is this', {}, budget.load_config(), image_b64='/9j/4AAQSkZJRg==')
    assert png[-1]['content'][0]['media_type'] == 'image/png'
    assert jpg[-1]['content'][0]['media_type'] == 'image/jpeg'
    assert jpg[-1]['content'][1] == {'type': 'text', 'text': 'what is this'}


# ── a plain turn ─────────────────────────────────────────────────────────────


def test_turn_runs_and_is_recorded(zero):
    sid = _session()
    turn_id = runner.start_turn(sid, 'how is the box doing?', actor='ad')['turn_id']
    assert isinstance(turn_id, str) and turn_id

    events = _drain(turn_id)
    kinds = [e['type'] for e in events]
    assert kinds[-1] == 'done'
    assert events[-1]['stop_reason'] == 'end_turn'
    assert 'tool_call' in kinds and 'tool_result' in kinds and 'usage' in kinds
    assert [e['seq'] for e in events] == sorted(e['seq'] for e in events)
    assert runner.events_since(turn_id, events[-2]['seq']) == [events[-1]]

    snap = runner.get_turn(turn_id)
    assert snap['done'] is True and snap['stop_reason'] == 'end_turn' and snap['pending_confirm'] is None

    session = memory.get_session(sid)
    roles = [m['role'] for m in session['messages']]
    assert roles == ['user', 'assistant']
    assert session['messages'][0]['content'] == 'how is the box doing?'
    assert 'Hi done' in session['messages'][1]['content']
    assert 'zero_index' in session['messages'][1]['content']

    rows = _ledger()
    assert len(rows) == 1
    row = rows[0]
    assert tuple(row) == metrics.ROW_FIELDS
    assert row['session_id'] == sid and row['turn_id'] == turn_id and row['actor'] == 'ad'
    assert row['provider'] == 'fake' and row['model'] == 'fake-1' and row['backend'] == 'fake'
    assert row['stage'] == 'chat' and row['stop_reason'] == 'end_turn'
    assert row['output_tokens'] == 5 and row['input_tokens'] > 0
    assert row['tool_calls'] == 1 and row['tool_names'] == ['zero_index'] and row['tool_errors'] == 0
    assert row['danger_calls'] == 0 and row['confirmations'] == 0
    assert row['cancelled'] is False and row['error'] is None and row['compacted'] is False
    assert row['budget_level'] in ('ok', 'warn') and row['context_tokens_est'] > 0
    assert row['latency_ms'] >= 0 and row['ttft_ms'] is not None


# ── the confirmation handshake ───────────────────────────────────────────────


def _danger_script():
    return [
        {'type': 'text_delta', 'text': 'Stopping the pipelines.'},
        {'type': 'tool_call', 'name': 'zero_call', 'args': {'tool': DANGER_TOOL, 'args': {}}},
    ]


def test_danger_tool_ends_in_needs_confirmation(zero):
    sid = _session()
    turn_id = runner.start_turn(sid, 'stop everything', extra={'script': _danger_script()})['turn_id']
    events = _drain(turn_id)

    confirms = [e for e in events if e['type'] == 'confirm']
    assert len(confirms) == 1
    assert confirms[0]['name'] == DANGER_TOOL and confirms[0]['confirm_id'] == 'cid-1'
    assert confirms[0]['risk'] == 'danger'
    assert events[-1] == {'type': 'done', 'stop_reason': 'needs_confirmation', 'seq': events[-1]['seq']}
    assert runner.get_turn(turn_id)['pending_confirm']['confirm_id'] == 'cid-1'

    row = _ledger()[-1]
    assert row['stop_reason'] == 'needs_confirmation'
    assert row['danger_calls'] == 1 and row['confirmations'] == 1 and row['tool_errors'] == 1


def test_confirm_approve_runs_the_tool_and_continues(zero):
    sid = _session()
    first = runner.start_turn(sid, 'stop everything', extra={'script': _danger_script()})['turn_id']
    _drain(first)

    second = runner.confirm(sid, 'cid-1', True, actor='ad')['turn_id']
    assert second != first
    _drain(second)

    session = memory.get_session(sid)
    continuation = [m for m in session['messages'] if m['role'] == 'user'][1]
    assert continuation['content'].startswith('[The user approved')
    assert DANGER_TOOL in continuation['content']
    assert 'executed after approval' in continuation['content']
    assert _ledger()[-1]['stage'] == 'confirm'


def test_confirm_deny_continues_without_the_tool(zero):
    sid = _session()
    _drain(runner.start_turn(sid, 'stop everything', extra={'script': _danger_script()})['turn_id'])
    _drain(runner.confirm(sid, 'cid-1', False)['turn_id'])
    continuation = [m for m in memory.get_session(sid)['messages'] if m['role'] == 'user'][1]
    assert continuation['content'] == f'[The user declined: {DANGER_TOOL}.] Continue without it.'


# ── cancellation and refusal ─────────────────────────────────────────────────


def test_cancel_turn_stops_a_slow_backend(zero):
    sid = _session()
    script = [
        {'type': 'text_delta', 'text': 'thinking'},
        {'type': 'sleep', 'seconds': 30},
        {'type': 'text_delta', 'text': 'never reached'},
    ]
    turn_id = runner.start_turn(sid, 'take your time', extra={'script': script})['turn_id']
    deadline = time.time() + 5
    while not runner.events_since(turn_id) and time.time() < deadline:
        time.sleep(0.02)
    assert runner.cancel_turn(turn_id) is True

    events = _drain(turn_id)
    assert events[-1]['stop_reason'] == 'cancelled'
    assert not any(e.get('text') == 'never reached' for e in events)
    row = _ledger()[-1]
    assert row['cancelled'] is True and row['stop_reason'] == 'cancelled'
    assert runner.cancel_turn(turn_id) is False
    assert runner.cancel_turn('nope') is False


def test_budget_block_raises(zero, monkeypatch):
    sid = _session()
    monkeypatch.setattr(
        budget,
        'check_turn',
        lambda provider, model, est: {
            'allowed': False,
            'level': 'blocked',
            'reason': 'the daily ceiling is spent',
            'state': {'day_tokens': 99},
            'limits': {},
        },
    )
    with pytest.raises(runner.BudgetBlocked) as excinfo:
        runner.start_turn(sid, 'one more thing')
    assert excinfo.value.reason == 'the daily ceiling is spent'
    assert excinfo.value.state == {'day_tokens': 99}

    row = _ledger()[-1]
    assert row['budget_level'] == 'blocked' and row['stop_reason'] == 'blocked'
    assert row['budget_reason'] == 'the daily ceiling is spent'


def test_unknown_session_and_empty_message(zero):
    with pytest.raises(ValueError):
        runner.start_turn('nosuchsession', 'hello')
    with pytest.raises(ValueError):
        runner.start_turn(_session(), '   ')


def test_tool_budget_stops_further_calls(zero, monkeypatch):
    sid = _session()
    monkeypatch.setattr(budget, 'check_tool', lambda n: n < 1)
    script = [
        {'type': 'tool_call', 'name': 'zero_index', 'args': {'group': 'system'}},
        {'type': 'tool_call', 'name': 'zero_index', 'args': {'group': 'agents'}},
    ]
    events = _drain(runner.start_turn(sid, 'look twice', extra={'script': script})['turn_id'])
    results = [e for e in events if e['type'] == 'tool_result']
    assert len(results) == 2
    assert results[0]['ok'] is True
    assert results[1]['ok'] is False and 'budget for this turn is spent' in results[1]['text']


def test_compaction_runs_one_extra_turn(zero, monkeypatch):
    sid = _session()
    for i in range(12):
        memory.append_message(sid, {'role': 'user', 'content': f'q{i} ' + 'x' * 400})
        memory.append_message(sid, {'role': 'assistant', 'content': f'a{i} ' + 'y' * 400})
    cfg = budget.load_config()
    cfg['per_session']['compact_after_tokens'] = 500
    monkeypatch.setattr(budget, 'load_config', lambda: cfg)

    turn_id = runner.start_turn(sid, 'and now?')['turn_id']
    _drain(turn_id)

    session = memory.get_session(sid)
    assert session['summary'] and session['summary_covers'] > 0
    rows = _ledger()
    assert rows[0]['stage'] == 'compaction' and rows[0]['compacted'] is True
    assert rows[-1]['turn_id'] == turn_id and rows[-1]['compacted'] is True


def test_auth_error_when_subscription_has_no_login(zero, monkeypatch):
    sid = _session()
    monkeypatch.setitem(contracts.BACKEND_FOR, 'subscription', 'fake')
    monkeypatch.setattr(_host, 'claude_login_present', lambda: False)
    events = _drain(runner.start_turn(sid, 'hello', provider='subscription', model='claude-opus-5')['turn_id'])
    errors = [e for e in events if e['type'] == 'error']
    assert errors and errors[0]['kind'] == 'auth' and 'claude login' in errors[0]['message']
    assert events[-1]['stop_reason'] == 'error'
    assert _ledger()[-1]['error'].startswith('no Claude Code login')


def test_wait_events_times_out_without_news(zero):
    assert runner.wait_events('nosuchturn', 0, timeout=0.05) == []
    sid = _session()
    turn_id = runner.start_turn(sid, 'hello', extra={'script': [{'type': 'sleep', 'seconds': 1.0}]})['turn_id']
    started = time.time()
    assert runner.wait_events(turn_id, 0, timeout=0.2) == []
    assert time.time() - started >= 0.15
    runner.cancel_turn(turn_id)
    _drain(turn_id)
