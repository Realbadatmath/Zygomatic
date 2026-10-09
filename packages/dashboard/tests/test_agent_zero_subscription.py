# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Unit tests for Agent Zero's subscription backend and its MCP bridge.

No dashboard, no Claude login and no quota are touched: every turn runs against a
FAKE `claude` binary written into tmp_path that reads one stream-json line from
stdin and prints a scripted exchange back. subprocess.Popen is wrapped so the test
can assert on the argv and the spawn environment — the two things that decide
whether a turn is billed to the subscription or to an API key.

The bridge (routes_mcp) is tested on a bare Flask app that registers agent_zero.bp
with a stubbed runner.TURNS entry, so the 40 s dashboard import is not needed.
"""

import json
import subprocess
import sys
import threading
import time
import types

import pytest

from zyg_dashboard.agent_zero import _host
from zyg_dashboard.agent_zero.backends import subscription
from zyg_dashboard.agent_zero.contracts import TurnContext

GOOD_LINES = [
    {
        'type': 'system',
        'subtype': 'init',
        'model': 'claude-opus-5',
        'session_id': 's1',
        'mcp_servers': [{'name': 'zero', 'status': 'connected'}],
    },
    {
        'type': 'stream_event',
        'event': {'type': 'content_block_delta', 'index': 0, 'delta': {'type': 'text_delta', 'text': 'Checking'}},
    },
    {
        'type': 'stream_event',
        'event': {'type': 'content_block_delta', 'index': 0, 'delta': {'type': 'text_delta', 'text': ' the GPU.'}},
    },
    {
        'type': 'assistant',
        'message': {
            'content': [
                {'type': 'text', 'text': 'Checking the GPU.'},
                {'type': 'tool_use', 'id': 'tu1', 'name': 'mcp__zero__zero_call', 'input': {'target': 'gpu.status'}},
            ]
        },
    },
    {
        'type': 'user',
        'message': {
            'content': [
                {
                    'type': 'tool_result',
                    'tool_use_id': 'tu1',
                    'content': [{'type': 'text', 'text': 'GPU idle'}],
                    'is_error': False,
                }
            ]
        },
    },
    {'type': 'assistant', 'message': {'content': [{'type': 'text', 'text': 'The GPU is idle.'}]}},
    {
        'type': 'result',
        'subtype': 'success',
        'result': 'The GPU is idle.',
        'session_id': 's1',
        'num_turns': 3,
        'duration_ms': 4200,
        'total_cost_usd': 0.0123,
        'usage': {
            'input_tokens': 120,
            'output_tokens': 34,
            'cache_read_input_tokens': 7,
            'cache_creation_input_tokens': 3,
        },
    },
]


def _fake_cli(tmp_path, body: str, name: str = 'claude') -> str:
    """An executable stand-in for the Claude Code binary. It always drains stdin
    first, exactly as the real CLI does with --input-format stream-json.

    The interpreter is reached through a /bin/sh wrapper, not a shebang: this
    checkout's venv lives under 'Zygomatic Full' and the kernel splits a shebang
    at the first space, so `#!<sys.executable>` is unrunnable here.
    """
    impl = tmp_path / (name + '_impl.py')
    impl.write_text('import json, os, sys, time\nsys.stdin.read()\n' + body, encoding='utf-8')
    path = tmp_path / name
    path.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{impl}" "$@"\n', encoding='utf-8')
    path.chmod(0o755)
    return str(path)


def _script_cli(tmp_path, lines, name='claude', exit_code=0) -> str:
    """A fake CLI that replays `lines` as stream-json, one JSON object per line."""
    feed = tmp_path / (name + '_lines.json')
    feed.write_text(json.dumps([json.dumps(x) for x in lines]), encoding='utf-8')
    body = (
        f'for line in json.load(open({str(feed)!r})):\n'
        '    sys.stdout.write(line + "\\n")\n'
        '    sys.stdout.flush()\n'
        f'raise SystemExit({exit_code})\n'
    )
    return _fake_cli(tmp_path, body, name)


class _Spawns:
    """Records every Popen the backend makes, then delegates to the real one."""

    def __init__(self):
        self.calls = []
        self._real = subprocess.Popen

    def __call__(self, cmd, **kw):
        self.calls.append({'argv': list(cmd), 'env': dict(kw.get('env') or {}), 'cwd': kw.get('cwd')})
        return self._real(cmd, **kw)


@pytest.fixture
def spawns(monkeypatch):
    rec = _Spawns()
    monkeypatch.setattr(subscription.subprocess, 'Popen', rec)
    return rec


@pytest.fixture
def host(monkeypatch, tmp_path):
    monkeypatch.setattr(_host, 'claude_login_present', lambda: True)
    monkeypatch.setattr(_host, 'runtime_dir', lambda: str(tmp_path / 'runtime'))
    return _host


def _ctx(**kw):
    base = {
        'turn_id': 't-1',
        'session_id': 's-1',
        'provider': 'subscription',
        'model': 'claude-opus-5',
        'system': 'You are Agent Zero.',
        'messages': [{'role': 'user', 'content': 'What is on the GPU?'}],
        'max_output_tokens': 8000,
        'max_tool_calls': 12,
        'thinking_tokens': 2048,
        'timeout_s': 30,
        'cookie': 'cookie-value',
        'csrf': 'csrf-value',
        'cancel': threading.Event(),
        'extra': {},
    }
    base.update(kw)
    return TurnContext(**base)


def _argv_pair(argv, flag):
    i = argv.index(flag)
    return argv[i + 1]


# ── the happy turn ───────────────────────────────────────────────────────────


def test_turn_streams_text_tool_call_result_usage_and_done(host, spawns, monkeypatch, tmp_path):
    monkeypatch.setattr(_host, 'claude_cli_bin', lambda: _script_cli(tmp_path, GOOD_LINES))
    executed = []
    ctx = _ctx(
        execute_tool=lambda name, args: (
            executed.append((name, args))
            or {'ok': True, 'text': 'x', 'ms': 1, 'risk': 'read', 'needs_confirmation': False, 'confirm_id': None}
        )
    )
    events = list(subscription.run(ctx))
    kinds = [e['type'] for e in events]
    assert kinds == ['text_delta', 'text_delta', 'tool_call', 'tool_result', 'text_delta', 'usage', 'done'], events
    assert [e['text'] for e in events if e['type'] == 'text_delta'] == ['Checking', ' the GPU.', 'The GPU is idle.']
    call = events[2]
    assert call['id'] == 'tu1' and call['name'] == 'zero_call' and call['args'] == {'target': 'gpu.status'}
    res = events[3]
    assert res == {'type': 'tool_result', 'id': 'tu1', 'name': 'zero_call', 'ok': True, 'text': 'GPU idle', 'ms': 0}
    assert events[5] == {
        'type': 'usage',
        'input_tokens': 120,
        'output_tokens': 34,
        'cache_read': 7,
        'cache_write': 3,
        'cost_usd': 0.0123,
        'model': 'claude-opus-5',
    }
    assert events[6] == {'type': 'done', 'stop_reason': 'end_turn'}
    # the bridge executed the tool, so the backend must not execute it a second time
    assert executed == []
    assert len(spawns.calls) == 1


def test_spawn_argv_and_env_never_carry_an_api_key(host, spawns, monkeypatch, tmp_path):
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'sk-should-be-stripped')
    monkeypatch.setenv('CLAUDECODE', '1')
    monkeypatch.setattr(_host, 'claude_cli_bin', lambda: _script_cli(tmp_path, GOOD_LINES))
    ctx = _ctx(thinking_tokens=1234, max_tool_calls=7)
    list(subscription.run(ctx))
    argv, env = spawns.calls[0]['argv'], spawns.calls[0]['env']
    assert not [k for k in env if k.startswith('ANTHROPIC_')], sorted(env)
    assert 'CLAUDECODE' not in env
    assert env['MAX_THINKING_TOKENS'] == str(ctx.thinking_tokens) == '1234'
    assert _argv_pair(argv, '--allowedTools') == 'mcp__zero'
    assert _argv_pair(argv, '--tools') == ''
    assert _argv_pair(argv, '--model') == 'claude-opus-5'
    assert _argv_pair(argv, '--permission-mode') == 'dontAsk'
    assert _argv_pair(argv, '--max-turns') == '9'  # max_tool_calls + headroom
    assert '--strict-mcp-config' in argv
    assert _argv_pair(argv, '--setting-sources') == ''
    cfg = json.loads(_argv_pair(argv, '--mcp-config'))['mcpServers']['zero']
    assert cfg['command'] == sys.executable
    assert cfg['args'] == [subscription.SHIM]
    assert cfg['env']['ZERO_MCP_TURN'] == 't-1'
    assert cfg['env']['ZERO_MCP_COOKIE'] == 'cookie-value'
    assert cfg['env']['ZERO_MCP_CSRF'] == 'csrf-value'
    assert cfg['env']['ZERO_MCP_TOKEN'] == ctx.extra['mcp_token']
    assert len(cfg['env']['ZERO_MCP_TOKEN']) >= 24


def test_no_login_yields_auth_error_without_spawning(host, spawns, monkeypatch, tmp_path):
    monkeypatch.setattr(_host, 'claude_login_present', lambda: False)
    monkeypatch.setattr(_host, 'claude_cli_bin', lambda: _script_cli(tmp_path, GOOD_LINES))
    events = list(subscription.run(_ctx()))
    assert events[0]['type'] == 'error' and events[0]['kind'] == 'auth'
    assert 'claude login' in events[0]['message']
    assert events[-1] == {'type': 'done', 'stop_reason': 'error'}
    assert spawns.calls == []


# ── refusals, timeouts, cancellation ────────────────────────────────────────


def test_limit_refusal_is_not_retried(host, spawns, monkeypatch, tmp_path):
    cli = _fake_cli(tmp_path, 'sys.stderr.write("You\'ve hit your limit · resets 9pm\\n")\nraise SystemExit(1)\n')
    monkeypatch.setattr(_host, 'claude_cli_bin', lambda: cli)
    events = list(subscription.run(_ctx()))
    assert [e['type'] for e in events] == ['error', 'done']
    assert events[0]['kind'] == 'limit'
    assert events[0]['message'] == subscription.LIMIT_MSG
    assert events[1] == {'type': 'done', 'stop_reason': 'error'}
    assert len(spawns.calls) == 1, 'a limit must never be retried'


def test_cut_stream_is_retried_once(host, spawns, monkeypatch, tmp_path):
    cli = _fake_cli(tmp_path, 'sys.stderr.write("connection reset\\n")\nraise SystemExit(1)\n')
    monkeypatch.setattr(_host, 'claude_cli_bin', lambda: cli)
    events = list(subscription.run(_ctx()))
    assert [e['type'] for e in events] == ['error', 'done']
    assert events[0]['kind'] == 'backend' and 'connection reset' in events[0]['message']
    assert len(spawns.calls) == 2, 'exactly one retry on a cut stream'


def test_timeout_kills_the_process_and_ends_the_turn(host, spawns, monkeypatch, tmp_path):
    monkeypatch.setattr(_host, 'claude_cli_bin', lambda: _fake_cli(tmp_path, 'time.sleep(5)\n'))
    t0 = time.time()
    events = list(subscription.run(_ctx(timeout_s=1)))
    elapsed = time.time() - t0
    assert elapsed < 3, f'the watchdog did not kill the turn in time ({elapsed:.1f}s)'
    assert [e['type'] for e in events] == ['error', 'done']
    assert events[0]['kind'] == 'backend' and 'timeout' in events[0]['message']
    assert len(spawns.calls) == 1, 'a timeout must not be retried'


def test_cancel_ends_the_turn_as_cancelled(host, spawns, monkeypatch, tmp_path):
    monkeypatch.setattr(_host, 'claude_cli_bin', lambda: _fake_cli(tmp_path, 'time.sleep(5)\n'))
    ctx = _ctx(timeout_s=30)
    threading.Timer(0.4, ctx.cancel.set).start()
    t0 = time.time()
    events = list(subscription.run(ctx))
    assert time.time() - t0 < 3
    assert events == [{'type': 'done', 'stop_reason': 'cancelled'}]


def test_max_turns_subtype_becomes_max_tool_calls(host, spawns, monkeypatch, tmp_path):
    lines = list(GOOD_LINES)
    lines[-1] = dict(lines[-1], subtype='error_max_turns')
    monkeypatch.setattr(_host, 'claude_cli_bin', lambda: _script_cli(tmp_path, lines))
    events = list(subscription.run(_ctx()))
    assert events[-1] == {'type': 'done', 'stop_reason': 'max_tool_calls'}
    assert events[-2]['type'] == 'usage'


def test_error_during_execution_is_a_backend_error(host, spawns, monkeypatch, tmp_path):
    lines = list(GOOD_LINES)
    lines[-1] = dict(lines[-1], subtype='error_during_execution', result='')
    monkeypatch.setattr(_host, 'claude_cli_bin', lambda: _script_cli(tmp_path, lines))
    events = list(subscription.run(_ctx()))
    assert events[-2]['type'] == 'error' and events[-2]['kind'] == 'backend'
    assert events[-1] == {'type': 'done', 'stop_reason': 'error'}


# ── probe + dry run ─────────────────────────────────────────────────────────


def test_probe_reports_the_login_and_the_cli(host, monkeypatch, tmp_path):
    cli = _script_cli(tmp_path, GOOD_LINES)
    monkeypatch.setattr(_host, 'claude_cli_bin', lambda: cli)
    out = subscription.probe()
    assert out['ok'] is True
    assert 'login present' in out['detail'] and cli in out['detail']
    monkeypatch.setattr(_host, 'claude_login_present', lambda: False)
    assert subscription.probe()['ok'] is False


def test_dry_run_prints_argv_and_mcp_config(capsys):
    assert subscription._dry_run() == 0
    out = capsys.readouterr().out
    assert 'argv:' in out and '--strict-mcp-config' in out
    assert '"ZERO_MCP_TOKEN": "REDACTED"' in out


# ── the MCP bridge ──────────────────────────────────────────────────────────

TOOL_SPECS = [
    {'name': 'zero_index', 'description': 'the index', 'input_schema': {'type': 'object'}},
    {'name': 'zero_call', 'description': 'call one', 'input_schema': {'type': 'object'}},
    {'name': 'zero_shell', 'description': 'run one', 'input_schema': {'type': 'object'}},
]


class _Turn:
    def __init__(self, ctx):
        self.ctx = ctx


@pytest.fixture
def bridge(monkeypatch):
    """A bare Flask app carrying agent_zero.bp, with runner and toolmap stubbed."""
    import flask

    from zyg_dashboard import agent_zero

    toolmap = types.ModuleType('zyg_dashboard.agent_zero.toolmap')
    toolmap.tool_specs = lambda: list(TOOL_SPECS)
    monkeypatch.setitem(sys.modules, 'zyg_dashboard.agent_zero.toolmap', toolmap)
    # ``routes_mcp`` reaches the module as ``from . import toolmap``, which reads the
    # package attribute, not sys.modules: without this the real tool map answers.
    monkeypatch.setattr(agent_zero, 'toolmap', toolmap, raising=False)
    calls = []
    ctx = _ctx(
        execute_tool=lambda name, args: (
            calls.append((name, args))
            or {
                'ok': True,
                'text': f'ran {name}',
                'ms': 3,
                'risk': 'read',
                'needs_confirmation': False,
                'confirm_id': None,
            }
        )
    )
    ctx.extra['mcp_token'] = 'tok-good'
    runner = types.ModuleType('zyg_dashboard.agent_zero.runner')
    runner.TURNS = {'t-1': _Turn(ctx)}
    monkeypatch.setitem(sys.modules, 'zyg_dashboard.agent_zero.runner', runner)
    monkeypatch.setattr(agent_zero, 'runner', runner, raising=False)
    from zyg_dashboard.agent_zero import routes_mcp  # noqa: F401  import-for-side-effect: registers the routes

    app = flask.Flask('zero-bridge-test')
    app.register_blueprint(agent_zero.bp)
    return types.SimpleNamespace(client=app.test_client(), app=app, calls=calls)


def _rule(app, suffix: str, turn_id: str) -> str:
    for rule in app.url_map.iter_rules():
        if rule.endpoint.endswith(suffix):
            return rule.rule.replace('<turn_id>', turn_id)
    raise AssertionError(f'no route ending in {suffix}: {[r.endpoint for r in app.url_map.iter_rules()]}')


def test_bridge_lists_the_meta_tools_for_a_good_token(bridge):
    url = _rule(bridge.app, 'zero_mcp_tools', 't-1')
    r = bridge.client.get(url + '?token=tok-good')
    assert r.status_code == 200
    body = r.get_json()
    assert body['ok'] is True
    assert [t['name'] for t in body['tools']] == ['zero_index', 'zero_call', 'zero_shell']
    assert all('input_schema' in t for t in body['tools'])


def test_bridge_refuses_a_bad_token_an_unknown_turn_and_a_remote_caller(bridge):
    url = _rule(bridge.app, 'zero_mcp_tools', 't-1')
    bad = bridge.client.get(url + '?token=tok-wrong')
    assert bad.status_code == 403 and bad.get_json() == {'ok': False, 'error': 'refused'}
    unknown = bridge.client.get(_rule(bridge.app, 'zero_mcp_tools', 'nope') + '?token=tok-good')
    assert unknown.status_code == 403
    remote = bridge.client.get(url + '?token=tok-good', environ_base={'REMOTE_ADDR': '10.1.2.3'})
    assert remote.status_code == 403


def test_bridge_call_strips_the_prefix_and_returns_the_executor_dict(bridge):
    url = _rule(bridge.app, 'zero_mcp_call', 't-1')
    r = bridge.client.post(
        url, json={'token': 'tok-good', 'name': 'mcp__zero__zero_call', 'args': {'target': 'gpu.status'}}
    )
    assert r.status_code == 200
    assert r.get_json() == {
        'ok': True,
        'text': 'ran zero_call',
        'ms': 3,
        'risk': 'read',
        'needs_confirmation': False,
        'confirm_id': None,
    }
    assert bridge.calls == [('zero_call', {'target': 'gpu.status'})]


def test_bridge_call_refuses_a_bad_token(bridge):
    url = _rule(bridge.app, 'zero_mcp_call', 't-1')
    r = bridge.client.post(url, json={'token': 'nope', 'name': 'zero_call', 'args': {}})
    assert r.status_code == 403 and r.get_json() == {'ok': False, 'error': 'refused'}
    assert bridge.calls == []
