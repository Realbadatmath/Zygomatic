# SPDX-FileCopyrightText: 2026 Zygomatic
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Coverage tests for zyg_zero.nomologin_assistant.

Everything the module reaches for — the Claude Code CLI, the persona browser, the
persona manifest and the on-disk ledger — is replaced by a fake, so the whole file
runs offline: no subprocess is ever spawned and no thread is ever started.
"""

from __future__ import annotations

import json
import os
import threading
from types import SimpleNamespace

import pytest

import zyg_zero
from zyg_zero import nomologin_assistant as mod


@pytest.fixture(scope='module', autouse=True)
def leave_the_package_as_found():
    """Un-cache the submodule attributes importing this file created.

    `from zyg_zero import nomologin_browser as nb` at the top of the module under test
    binds `nomologin_browser` onto the `zyg_zero` package object, which defeats a
    sibling test's `monkeypatch.setitem(sys.modules, …)` fake of that submodule. The
    next genuine import re-creates the attribute, so dropping it costs nothing.
    """
    yield
    for name in ('nomologin', 'nomologin_browser'):
        zyg_zero.__dict__.pop(name, None)


# --------------------------------------------------------------------------- fakes


class FakeThread:
    """threading.Thread stand-in whose start() runs the target inline."""

    instances: list[FakeThread] = []

    def __init__(self, target=None, args=(), daemon=False):
        self.target, self.args, self.daemon = target, args, daemon
        self.started = False
        FakeThread.instances.append(self)

    def start(self):
        self.started = True
        if self.target:
            self.target(*self.args)


class FakeProc:
    """subprocess.Popen stand-in reading from canned stdout/stderr lists."""

    def __init__(self, out_lines=(), err_lines=(), returncode=0, alive=False):
        self.stdout = iter(list(out_lines))
        self.stderr = iter(list(err_lines))
        self.returncode = returncode
        self.stdin = SimpleNamespace(
            written=[],
            write=lambda s: self.stdin.written.append(s),
            flush=lambda: None,
            close=lambda: None,
        )
        self.killed = False
        self._alive = alive

    def kill(self):
        self.killed = True
        self._alive = False

    def poll(self):
        return None if self._alive else self.returncode

    def wait(self, timeout=None):
        return self.returncode


@pytest.fixture
def inline_threads(monkeypatch):
    """Make the module's threading.Thread synchronous, and forget old instances."""
    FakeThread.instances = []
    monkeypatch.setattr(mod, 'threading', SimpleNamespace(Thread=FakeThread, Lock=threading.Lock))
    return FakeThread


@pytest.fixture
def ledger(tmp_path, monkeypatch):
    """Redirect every path the module derives from nl.ROOT into tmp_path."""
    runtime = tmp_path / 'assistant'
    monkeypatch.setattr(mod, 'RUNTIME', str(runtime))
    monkeypatch.setattr(mod, 'CWD', str(runtime / 'cli'))
    monkeypatch.setattr(mod, 'LEDGER', str(runtime / 'conversations'))
    return runtime / 'conversations'


@pytest.fixture(autouse=True)
def clean_jobs():
    mod._JOBS.clear()
    yield
    mod._JOBS.clear()


def _job(jid='j1', **kw):
    """Register a minimal job dict in the module's registry and return it."""
    job = {
        'id': jid,
        'persona': 'ada',
        'text': 'read the notifications',
        'status': 'running',
        'started': 100.0,
        'model': 'test-model',
        'session': None,
        'steps': 0,
        'tools': [],
        'thoughts': [],
        'reply': None,
        'error': None,
        'log': [],
        'usage': {},
    }
    job.update(kw)
    mod._JOBS[jid] = job
    return job


# ------------------------------------------------------------------ small helpers


def test_now_and_day(monkeypatch):
    assert isinstance(mod._now(), float)
    day = mod._day()
    assert len(day) == 10 and day[4] == '-' and day[7] == '-'


@pytest.mark.parametrize(
    ('cli_rc', 'cli_exc', 'shim_ok', 'browser_ok', 'expect_ok', 'expect_cli_ok'),
    [
        (0, None, True, True, True, True),
        (1, None, True, True, False, False),
        (0, None, False, True, False, True),
        (0, None, True, False, False, True),
        (0, OSError('no claude on PATH'), True, True, False, False),
        (0, mod.subprocess.TimeoutExpired('claude', 15), True, True, False, False),
    ],
)
def test_available(monkeypatch, cli_rc, cli_exc, shim_ok, browser_ok, expect_ok, expect_cli_ok):
    def fake_run(argv, **kw):
        assert argv[1] == '--version'
        if cli_exc is not None:
            raise cli_exc
        return SimpleNamespace(stdout=' 2.1.74 \n', returncode=cli_rc)

    monkeypatch.setattr(mod.subprocess, 'run', fake_run)
    monkeypatch.setattr(mod.os.path, 'isfile', lambda p: shim_ok)
    monkeypatch.setattr(mod.nb, 'available', lambda: {'ok': browser_ok})

    out = mod.available()
    assert out['ok'] is expect_ok
    assert out['cli_ok'] is expect_cli_ok
    assert out['shim_ok'] is shim_ok
    assert out['model'] == mod.MODEL
    if cli_exc is None:
        assert out['cli'] == '2.1.74'


def test_env_strips_api_keys(monkeypatch):
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'sk-should-be-dropped')
    monkeypatch.setenv('ANTHROPIC_MODEL', 'nope')
    monkeypatch.setenv('CLAUDECODE', '1')
    monkeypatch.setenv('PATH_MARKER', 'kept')
    monkeypatch.setattr(mod.nl, 'gui_env', lambda base: (dict(base, DISPLAY=':0'), None))

    env = mod._env('ada')
    assert not [k for k in env if k.startswith('ANTHROPIC_')]
    assert 'CLAUDECODE' not in env
    assert env['PATH_MARKER'] == 'kept'
    assert env['NOMOLOGIN_PERSONA'] == 'ada'
    assert env['CLAUDE_CODE_MAX_OUTPUT_TOKENS'] == mod.CLI_MAX_OUTPUT
    assert env['DISPLAY'] == ':0'


def test_mcp_config():
    cfg = json.loads(mod._mcp_config('ada'))
    server = cfg['mcpServers']['nomo']
    assert server['args'] == [mod.SHIM]
    assert server['env'] == {'NOMOLOGIN_PERSONA': 'ada'}
    assert server['command'].endswith('python') or 'python' in server['command']


def test_ledger_write_appends(ledger, monkeypatch):
    monkeypatch.setattr(mod, '_day', lambda: '2026-01-02')
    mod._ledger_write({'event': 'start', 'id': 'a'})
    mod._ledger_write({'event': 'end', 'id': 'a'})
    path = ledger / '2026-01-02.jsonl'
    rows = [json.loads(ln) for ln in path.read_text(encoding='utf-8').splitlines()]
    assert [r['event'] for r in rows] == ['start', 'end']


def test_set_and_log():
    _job()
    mod._set('j1', status='done', reply='hi')
    assert mod._JOBS['j1']['status'] == 'done'
    mod._set('missing', status='done')  # unknown id is a no-op

    mod._log('j1', 'x' * 900)
    assert len(mod._JOBS['j1']['log'][0]) == 500
    for i in range(260):
        mod._log('j1', f'line {i}')
    assert len(mod._JOBS['j1']['log']) == 200
    mod._log('missing', 'nope')


# --------------------------------------------------------------------------- ask


def test_ask_rejects_empty_text(monkeypatch):
    monkeypatch.setattr(mod.nl, 'get_persona', lambda p: {'id': p})
    with pytest.raises(ValueError, match='nothing asked'):
        mod.ask('ada', '   ')


def test_ask_starts_job(ledger, inline_threads, monkeypatch):
    monkeypatch.setattr(mod.nl, 'get_persona', lambda p: {'id': p})
    monkeypatch.setattr(mod, '_day', lambda: '2026-01-02')
    seen = []
    monkeypatch.setattr(mod, '_run', lambda jid, turns: seen.append((jid, turns)))

    out = mod.ask('ada', '  post the thread  ', session='sess-1', max_turns=7)
    assert out['ok'] is True
    assert out['persona'] == 'ada'
    assert out['text'] == 'post the thread'
    assert out['status'] == 'running'
    assert out['session'] == 'sess-1'
    assert seen == [(out['id'], 7)]

    rows = [json.loads(ln) for ln in (ledger / '2026-01-02.jsonl').read_text().splitlines()]
    assert rows[0]['event'] == 'start' and rows[0]['persona'] == 'ada'


def test_ask_defaults_max_turns(ledger, inline_threads, monkeypatch):
    monkeypatch.setattr(mod.nl, 'get_persona', lambda p: {'id': p})
    seen = []
    monkeypatch.setattr(mod, '_run', lambda jid, turns: seen.append(turns))
    mod.ask('ada', 'hello')
    assert seen == [mod.MAX_TURNS]


# -------------------------------------------------------------------------- _run


def _run_setup(monkeypatch, ledger, proc, times=None):
    monkeypatch.setattr(mod.nl, 'gui_env', lambda base: (dict(base), None))
    captured = {}

    def fake_popen(argv, **kw):
        captured['argv'] = argv
        captured['kw'] = kw
        if isinstance(proc, Exception):
            raise proc
        return proc

    monkeypatch.setattr(mod.subprocess, 'Popen', fake_popen)
    if times is not None:
        ticks = iter(times)
        monkeypatch.setattr(mod, '_now', lambda: next(ticks, times[-1]))
    return captured


def test_run_success(ledger, inline_threads, monkeypatch):
    job = _job(session='sess-9')
    events = [
        json.dumps({'type': 'system', 'subtype': 'init', 'session_id': 's2', 'model': 'm', 'apiKeySource': 'none'}),
        'not json at all',
        json.dumps({'type': 'result', 'result': 'done posting', 'usage': {'input_tokens': 3}, 'total_cost_usd': 0.1}),
        '',
    ]
    proc = FakeProc(out_lines=events, err_lines=['a warning'], returncode=0)
    captured = _run_setup(monkeypatch, ledger, proc)

    mod._run('j1', 12)

    assert job['status'] == 'done'
    assert job['reply'] == 'done posting'
    assert job['session'] == 's2'
    assert job['usage'] == {'input_tokens': 3}
    assert '--resume' in captured['argv'] and 'sess-9' in captured['argv']
    assert captured['argv'][captured['argv'].index('--max-turns') + 1] == '12'
    assert captured['kw']['cwd'] == mod.CWD
    assert 'not json at all' in job['log']
    assert os.path.isdir(mod.CWD)
    assert json.loads(proc.stdin.written[0])['message']['content'][0]['text'] == job['text']


def test_run_no_resume_without_session(ledger, inline_threads, monkeypatch):
    _job()
    captured = _run_setup(monkeypatch, ledger, FakeProc(out_lines=[], returncode=0))
    mod._run('j1', 3)
    assert '--resume' not in captured['argv']


def test_run_error_tail_from_stderr(ledger, inline_threads, monkeypatch):
    job = _job()
    proc = FakeProc(out_lines=[], err_lines=['', 'boom one', 'boom two'], returncode=2)
    _run_setup(monkeypatch, ledger, proc)
    mod._run('j1', 3)
    assert job['status'] == 'error'
    assert job['error'] == 'boom one boom two'


def test_run_error_exit_code_only(ledger, inline_threads, monkeypatch):
    job = _job()
    _run_setup(monkeypatch, ledger, FakeProc(out_lines=[], err_lines=[], returncode=3))
    mod._run('j1', 3)
    assert job['error'] == 'exit 3'


def test_run_timeout_kills_process(ledger, inline_threads, monkeypatch):
    job = _job()
    proc = FakeProc(out_lines=['{"type": "result", "result": "late"}'], returncode=0, alive=True)
    # first _now() builds the deadline, the second is past it
    _run_setup(monkeypatch, ledger, proc, times=[0.0, 10**9, 10**9])
    mod._run('j1', 3)
    assert proc.killed is True
    assert job['status'] == 'error'
    assert job['error'].startswith('TimeoutError:')


def test_run_popen_failure(ledger, inline_threads, monkeypatch):
    job = _job()
    _run_setup(monkeypatch, ledger, OSError('no such file'))
    mod._run('j1', 3)
    assert job['status'] == 'error'
    assert job['error'] == 'OSError: no such file'


def test_run_done_without_a_result_event(ledger, inline_threads, monkeypatch):
    job = _job()
    ev = json.dumps({'type': 'assistant', 'message': {'content': [{'type': 'text', 'text': 'posted it'}]}})
    _run_setup(monkeypatch, ledger, FakeProc(out_lines=[ev], returncode=0))
    mod._run('j1', 3)
    assert job['status'] == 'done'
    assert job['reply'] == 'posted it'


def test_run_kills_a_live_process_on_failure(ledger, inline_threads, monkeypatch):
    job = _job()

    class Dying:
        def __iter__(self):
            return self

        def __next__(self):
            raise OSError('pipe died')

    proc = FakeProc(returncode=0, alive=True)
    proc.stdout = Dying()
    _run_setup(monkeypatch, ledger, proc)
    mod._run('j1', 3)
    assert proc.killed is True
    assert job['error'] == 'OSError: pipe died'


def test_drain_err_keeps_last_40():
    errs: list[str] = []
    proc = SimpleNamespace(stderr=iter([''] + [f'e{i}' for i in range(60)]))
    mod._drain_err(proc, errs)
    assert len(errs) == 40
    assert errs[-1] == 'e59'


# ------------------------------------------------------------------------ _event


def test_event_init_sets_session():
    _job()
    mod._event('j1', {'type': 'system', 'subtype': 'init', 'session_id': 'abc', 'model': 'm', 'apiKeySource': 'none'})
    assert mod._JOBS['j1']['session'] == 'abc'
    assert mod._JOBS['j1']['log'][0].startswith('init: model=m')


def test_event_system_other_subtype_ignored():
    _job()
    mod._event('j1', {'type': 'system', 'subtype': 'other'})
    assert mod._JOBS['j1']['session'] is None
    assert mod._JOBS['j1']['log'] == []


def test_event_assistant_blocks():
    job = _job()
    mod._event(
        'j1',
        {
            'type': 'assistant',
            'message': {
                'content': [
                    {'type': 'text', 'text': '   '},
                    {'type': 'text', 'text': 'opened the inbox'},
                    {'type': 'thinking', 'thinking': '  '},
                    {'type': 'thinking', 'thinking': 'which tab?'},
                    {'type': 'tool_use', 'name': 'mcp__nomo__page', 'input': {'tab': 1}},
                    {'type': 'tool_use', 'name': 'mcp__nomo__text'},
                    {'type': 'image'},
                ],
                'usage': {'output_tokens': 11},
            },
        },
    )
    assert job['reply'] == 'opened the inbox'
    assert job['thoughts'] == ['which tab?']
    assert job['steps'] == 2
    assert [t['name'] for t in job['tools']] == ['page', 'text']
    assert job['tools'][1]['input'] == {}
    assert job['usage'] == {'output_tokens': 11}
    assert job['log'] == ['tool page', 'tool text']


def test_event_assistant_trims_tools_and_empty_message():
    job = _job()
    blocks = [{'type': 'tool_use', 'name': f'mcp__nomo__t{i}', 'input': {}} for i in range(70)]
    mod._event('j1', {'type': 'assistant', 'message': {'content': blocks}})
    assert job['steps'] == 70
    assert len(job['tools']) == 60
    mod._event('j1', {'type': 'assistant'})
    assert job['steps'] == 70


def test_event_result_error():
    job = _job()
    mod._event('j1', {'type': 'result', 'is_error': True, 'result': 'rate limited'})
    assert job['status'] == 'error'
    assert job['error'] == 'rate limited'
    assert job['cost_usd'] is None


def test_event_result_without_text():
    job = _job()
    mod._event('j1', {'type': 'result', 'result': '', 'total_cost_usd': 0.5})
    assert job['status'] == 'done'
    assert job['reply'] is None
    assert job['cost_usd'] == 0.5


def test_event_unknown_kind_is_ignored():
    job = _job()
    mod._event('j1', {'type': 'stream_event'})
    assert job['status'] == 'running'


# ----------------------------------------------------------- _finish / view / etc


def test_finish_writes_end_row(ledger, monkeypatch):
    monkeypatch.setattr(mod, '_day', lambda: '2026-01-02')
    monkeypatch.setattr(mod, '_now', lambda: 160.0)
    _job(status='done', reply='posted', steps=2, log=[f'l{i}' for i in range(80)])
    mod._finish('j1')
    row = json.loads((ledger / '2026-01-02.jsonl').read_text().strip())
    assert row['event'] == 'end'
    assert row['status'] == 'done'
    assert row['seconds'] == 60.0
    assert len(row['log']) == 60


def test_finish_unknown_job_is_quiet(ledger):
    mod._finish('nope')
    assert not os.path.isdir(mod.LEDGER)


def test_view_missing_job():
    out = mod.view('nope')
    assert out == {'ok': False, 'error': 'no job nope'}


def test_view_hides_log_and_trims_tools(monkeypatch):
    monkeypatch.setattr(mod, '_now', lambda: 150.5)
    _job(
        log=['secret'],
        tools=[{'name': f't{i}', 'input': {'i': i}, 'at': 1.0} for i in range(40)],
        finished=None,
    )
    out = mod.view('j1')
    assert 'log' not in out
    assert out['seconds'] == 50.5
    assert len(out['tools']) == 30
    assert out['tools'][0] == {'name': 't10', 'input': {'i': 10}}


def test_view_uses_finished_time():
    _job(finished=180.0)
    assert mod.view('j1')['seconds'] == 80.0


def test_active_lists_only_running(monkeypatch):
    monkeypatch.setattr(mod, '_now', lambda: 130.0)
    _job('run1', text='x' * 200, steps=4)
    _job('done1', status='done')
    rows = mod.active()
    assert [r['id'] for r in rows] == ['run1']
    assert len(rows[0]['text']) == 120
    assert rows[0]['seconds'] == 30.0


# ----------------------------------------------------------------- history / boot


def test_history_missing_file(ledger):
    assert mod.history() == []
    assert mod.history(day='2026-01-02') == []


def test_history_filters_and_reverses(ledger, monkeypatch):
    monkeypatch.setattr(mod, '_day', lambda: '2026-01-02')
    os.makedirs(ledger, exist_ok=True)
    lines = [json.dumps({'event': 'start', 'id': 'a'}), '', 'broken {', '']
    lines += [json.dumps({'event': 'end', 'id': f'e{i}'}) for i in range(5)]
    (ledger / '2026-01-02.jsonl').write_text('\n'.join(lines) + '\n', encoding='utf-8')

    rows = mod.history()
    assert [r['id'] for r in rows] == ['e4', 'e3', 'e2', 'e1', 'e0']
    assert [r['id'] for r in mod.history(n=2)] == ['e4', 'e3']


def test_boot_no_ledger(ledger):
    assert mod.boot() == {'closed': 0}


def test_boot_closes_orphans(ledger, monkeypatch):
    monkeypatch.setattr(mod, '_day', lambda: '2026-01-02')
    monkeypatch.setattr(mod, '_now', lambda: 500.0)
    os.makedirs(ledger, exist_ok=True)
    path = ledger / '2026-01-02.jsonl'
    lines = [
        json.dumps({'event': 'start', 'id': 'a', 'persona': 'ada', 'text': 'post'}),
        json.dumps({'event': 'end', 'id': 'a'}),
        json.dumps({'event': 'start', 'id': 'b', 'persona': 'ada', 'text': 'reply'}),
        'broken {',
        json.dumps({'event': 'noise', 'id': 'c'}),
    ]
    path.write_text('\n'.join(lines) + '\n', encoding='utf-8')

    assert mod.boot() == {'closed': 1}
    rows = [json.loads(ln) for ln in path.read_text(encoding='utf-8').splitlines() if ln.strip() != 'broken {']
    killed = [r for r in rows if r.get('status') == 'killed']
    assert len(killed) == 1
    assert killed[0]['id'] == 'b'
    assert killed[0]['error'] == 'the board restarted while the assistant was working'
    assert mod.boot() == {'closed': 0}


def test_system_prompt_states_the_login_rule():
    assert 'You never sign in' in mod.SYSTEM
    assert 'Call `page` before every click' in mod.SYSTEM
