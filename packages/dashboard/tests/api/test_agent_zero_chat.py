# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later
"""In-process route tests for the Agent Zero v2 chat contract (CONTRACT G).

What these tests prove: the chat window's whole HTTP contract answers, on the *real*
dashboard app, with the dashboard's own gates in front of it -- an anonymous caller gets
401, a body method without ``X-CSRF-Token`` gets 403, and only then does a route run.

Nothing here spends a token or touches the operator's data. An autouse fixture points
``_host.runtime_dir``/``data_dir`` at ``tmp_path``, pins the model selection to a
``fake`` provider wired to :mod:`agent_zero.backends.fake`, and replaces
``toolmap_exec.execute`` with a stub, so a turn runs end to end -- SSE stream, session
transcript, metrics -- entirely inside the process.

Two notes on the harness:

* ``agent_zero.bp`` is **not** registered in ``crewai_web_gui`` yet (a later task of
  this tree owns that file), so the fixture registers it on the imported app itself.
  Flask refuses a blueprint after the app's first request, so the flag is cleared for
  the duration of that one call.
* ``contracts.BACKEND_FOR`` values are module names *relative to*
  ``agent_zero.backends`` (``backends.get`` does ``import_module(f'{__name__}.{name}')``),
  so the fake provider maps to ``'fake'``, not to a dotted path.
"""

import json
import time

import pytest

from zyg_dashboard import agent_zero
from zyg_dashboard.agent_zero import _host, budget, contracts, memory, models, runner, toolmap_exec
from zyg_dashboard.agent_zero.backends import fake

pytestmark = [pytest.mark.api, pytest.mark.timeout(180)]

STREAM_TIMEOUT_S = 20


@pytest.fixture(scope='session', autouse=True)
def zero_blueprint(dash_app):
    """Register ``agent_zero.bp`` on the imported dashboard app (task 13 owns the host)."""
    app = dash_app.app
    if 'zero_v2' not in app.blueprints:
        first = app._got_first_request
        app._got_first_request = False
        try:
            app.register_blueprint(agent_zero.bp)
        finally:
            app._got_first_request = first
    return app


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    """No live data, no live provider, no real tool: a turn that stays in the process."""
    monkeypatch.setattr(_host, 'runtime_dir', lambda: str(tmp_path))
    monkeypatch.setattr(_host, 'data_dir', lambda: str(tmp_path))
    monkeypatch.setattr(models, 'get_selection', lambda: {'provider': 'fake', 'model': 'fake-1'})
    monkeypatch.setitem(contracts.BACKEND_FOR, 'fake', 'fake')
    monkeypatch.setattr(
        toolmap_exec,
        'execute',
        lambda name, args, cookie='', csrf='', confirmed=False, actor='': {
            'ok': True,
            'text': f'stub ran {name}',
            'ms': 1,
            'risk': 'read',
            'needs_confirmation': False,
            'confirm_id': None,
        },
    )
    runner.TURNS.clear()
    yield
    runner.TURNS.clear()


def _new_session(client) -> dict:
    r = client.post('/api/zero/v2/sessions', json={}, headers=client.csrf)
    assert r.status_code == 201, r.get_data(as_text=True)
    return r.get_json()['session']


def _stream_until_done(client, turn_id: str) -> str:
    """Read the SSE stream until the ``done`` event, or fail after the deadline."""
    deadline = time.time() + STREAM_TIMEOUT_S
    chunks = []
    r = client.get(f'/api/zero/v2/turns/{turn_id}/events?from=0')
    assert r.status_code == 200, r.get_data(as_text=True)
    assert r.headers['Content-Type'].startswith('text/event-stream'), r.headers['Content-Type']
    assert r.headers['Cache-Control'] == 'no-store'
    assert r.headers['X-Accel-Buffering'] == 'no'
    for raw in r.response:
        chunks.append(raw.decode('utf-8') if isinstance(raw, bytes) else str(raw))
        if 'event: done' in chunks[-1]:
            break
        assert time.time() < deadline, f'no done event in {STREAM_TIMEOUT_S}s: {"".join(chunks)!r}'
    body = ''.join(chunks)
    assert 'event: done' in body, body
    return body


def _wait_booked(turn_id: str, timeout: float = 15.0) -> dict:
    """Block until the runner has booked the turn.

    The ``done`` *event* is emitted by the backend loop; ``turn['done']`` is only set
    after :func:`agent_zero.runner._book` has appended the assistant message, billed the
    usage and written the metrics row. A client that closes the stream on ``done`` is
    therefore microseconds ahead of the transcript -- which is exactly what a test that
    asserts on the transcript has to wait for.
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        snapshot = runner.get_turn(turn_id)
        if snapshot is not None and snapshot['done']:
            return snapshot
        time.sleep(0.02)
    raise AssertionError(f'turn {turn_id} was not booked within {timeout}s')


# ── the gates ───────────────────────────────────────────────────────────────


def test_greeting_needs_a_session(dash):
    assert dash.get('/api/zero/v2/greeting').status_code == 401


def test_greeting_is_the_exact_sentence(dash_admin):
    body = dash_admin.get('/api/zero/v2/greeting').get_json()
    assert body['text'] == 'Hi apitest, how can I help you?'
    assert body['user'] == 'apitest'
    assert body['selected'] == {'provider': 'fake', 'model': 'fake-1'}


def test_a_turn_without_the_csrf_header_is_refused(dash_admin):
    session = _new_session(dash_admin)
    r = dash_admin.post(f'/api/zero/v2/sessions/{session["id"]}/turn', json={'message': 'hello'})
    assert r.status_code == 403, r.get_data(as_text=True)
    # The handler never ran: no turn was created.
    assert runner.TURNS == {}


# ── sessions ────────────────────────────────────────────────────────────────


def test_sessions_round_trip(dash_admin):
    session = _new_session(dash_admin)
    assert session['user'] == 'apitest'
    assert (session['provider'], session['model']) == ('fake', 'fake-1')

    listed = dash_admin.get('/api/zero/v2/sessions?limit=50').get_json()['sessions']
    assert [row['id'] for row in listed] == [session['id']]
    assert set(listed[0]) >= {'id', 'title', 'updated', 'turns', 'provider', 'model'}

    r = dash_admin.post(
        f'/api/zero/v2/sessions/{session["id"]}/rename', json={'title': 'Renamed'}, headers=dash_admin.csrf
    )
    assert r.get_json() == {'ok': True, 'title': 'Renamed'}

    fetched = dash_admin.get(f'/api/zero/v2/sessions/{session["id"]}').get_json()['session']
    assert fetched['title'] == 'Renamed'
    assert fetched['messages'] == []

    assert dash_admin.get('/api/zero/v2/sessions/nope').status_code == 404

    r = dash_admin.delete(f'/api/zero/v2/sessions/{session["id"]}', headers=dash_admin.csrf)
    assert r.get_json() == {'ok': True}
    assert dash_admin.get('/api/zero/v2/sessions').get_json()['sessions'] == []


def test_pin_and_unpin_a_fact(dash_admin):
    session = _new_session(dash_admin)
    url = f'/api/zero/v2/sessions/{session["id"]}'
    assert dash_admin.post(f'{url}/pin', json={'text': 'always ask first'}, headers=dash_admin.csrf).get_json()[
        'pinned'
    ] == ['always ask first']
    assert (
        dash_admin.post(f'{url}/unpin', json={'text': 'always ask first'}, headers=dash_admin.csrf).get_json()['pinned']
        == []
    )


def test_a_long_tool_result_is_truncated_on_the_wire_only(dash_admin):
    session = _new_session(dash_admin)
    long_text = 'x' * 9000
    memory.append_message(
        session['id'],
        {
            'role': 'user',
            'content': [{'type': 'tool_result', 'tool_use_id': 'tu_1', 'content': long_text, 'is_error': False}],
        },
    )
    block = dash_admin.get(f'/api/zero/v2/sessions/{session["id"]}').get_json()['session']['messages'][0]['content'][0]
    assert len(block['content']) == 4000
    on_disk = memory.get_session(session['id'])['messages'][0]['content'][0]
    assert len(on_disk['content']) == 9000


# ── one whole turn ──────────────────────────────────────────────────────────


def test_a_turn_streams_and_lands_in_the_transcript(dash_admin):
    session = _new_session(dash_admin)
    r = dash_admin.post(
        f'/api/zero/v2/sessions/{session["id"]}/turn', json={'message': 'hello there'}, headers=dash_admin.csrf
    )
    assert r.status_code == 202, r.get_data(as_text=True)
    accepted = r.get_json()
    assert accepted['session_id'] == session['id']
    assert accepted['provider'] == 'fake' and accepted['model'] == 'fake-1'
    turn_id = accepted['turn_id']
    assert turn_id

    body = _stream_until_done(dash_admin, turn_id)
    assert 'event: text_delta' in body, body
    assert 'id: 1\n' in body, body
    first = json.loads(body.split('data: ', 1)[1].split('\n', 1)[0])
    assert first['type'] == 'text_delta' and first['seq'] == 1

    _wait_booked(turn_id)
    snapshot = dash_admin.get(f'/api/zero/v2/turns/{turn_id}').get_json()
    assert snapshot['done'] is True
    assert snapshot['events_count'] >= 3
    assert snapshot['stop_reason'] == 'end_turn'

    messages = dash_admin.get(f'/api/zero/v2/sessions/{session["id"]}').get_json()['session']['messages']
    assert [m['role'] for m in messages] == ['user', 'assistant']
    assert messages[0]['content'] == 'hello there'
    assert 'Hi' in messages[1]['content']


def test_an_empty_turn_and_an_unknown_turn_are_refused(dash_admin):
    session = _new_session(dash_admin)
    r = dash_admin.post(f'/api/zero/v2/sessions/{session["id"]}/turn', json={'message': '  '}, headers=dash_admin.csrf)
    assert r.status_code == 400
    assert r.get_json()['error'] == 'message is required'
    assert dash_admin.get('/api/zero/v2/turns/nope').status_code == 404
    assert dash_admin.get('/api/zero/v2/turns/nope/events').status_code == 404


def test_a_second_turn_while_one_runs_is_409(dash_admin, monkeypatch):
    """A scripted slow backend keeps turn one alive long enough to collide with it."""

    def slow_run(ctx):
        yield {'type': 'text_delta', 'text': 'thinking'}
        for _ in range(200):
            if ctx.cancel.is_set():
                break
            time.sleep(0.05)
        yield {'type': 'usage', 'input_tokens': 1, 'output_tokens': 1, 'model': ctx.model}
        yield {'type': 'done', 'stop_reason': 'cancelled' if ctx.cancel.is_set() else 'end_turn'}

    monkeypatch.setattr(fake, 'run', slow_run)
    session = _new_session(dash_admin)
    url = f'/api/zero/v2/sessions/{session["id"]}/turn'
    first = dash_admin.post(url, json={'message': 'one'}, headers=dash_admin.csrf)
    assert first.status_code == 202, first.get_data(as_text=True)
    running = first.get_json()['turn_id']

    second = dash_admin.post(url, json={'message': 'two'}, headers=dash_admin.csrf)
    assert second.status_code == 409, second.get_data(as_text=True)
    assert second.get_json() == {'error': 'turn in progress', 'turn_id': running}

    cancelled = dash_admin.post(f'/api/zero/v2/turns/{running}/cancel', headers=dash_admin.csrf)
    assert cancelled.get_json() == {'ok': True}
    assert _wait_booked(running)['stop_reason'] == 'cancelled'


def test_a_blocked_budget_answers_429(dash_admin, monkeypatch):
    def blocked(*args, **kwargs):
        raise runner.BudgetBlocked('the daily ceiling is spent', {'day_turns': 99})

    monkeypatch.setattr(runner, 'start_turn', blocked)
    session = _new_session(dash_admin)
    r = dash_admin.post(
        f'/api/zero/v2/sessions/{session["id"]}/turn', json={'message': 'hello'}, headers=dash_admin.csrf
    )
    assert r.status_code == 429, r.get_data(as_text=True)
    body = r.get_json()
    assert body['error'] == 'the daily ceiling is spent'
    assert body['kind'] == 'budget'
    assert body['budget'] == {'day_turns': 99}


def test_an_unknown_confirmation_is_404(dash_admin):
    session = _new_session(dash_admin)
    r = dash_admin.post(
        f'/api/zero/v2/sessions/{session["id"]}/confirm',
        json={'confirm_id': 'cf_nope', 'approve': True},
        headers=dash_admin.csrf,
    )
    assert r.status_code == 404, r.get_data(as_text=True)
    assert 'cf_nope' in r.get_json()['error']


# ── budget and tools ────────────────────────────────────────────────────────


def test_budget_get_returns_state_config_and_doc(dash_admin):
    body = dash_admin.get('/api/zero/v2/budget').get_json()
    assert body['config'] == budget.load_config()
    assert body['doc'] == budget.CONFIG_DOC
    assert 'day_turns' in body['state']


def test_budget_patch_and_override(dash_admin):
    r = dash_admin.post('/api/zero/v2/budget', json={'per_day': {'max_turns': 42}}, headers=dash_admin.csrf)
    assert r.status_code == 200, r.get_data(as_text=True)
    assert r.get_json()['config']['per_day']['max_turns'] == 42

    bad = dash_admin.post('/api/zero/v2/budget', json={'nope': {'x': 1}}, headers=dash_admin.csrf)
    assert bad.status_code == 400
    assert 'nope' in bad.get_json()['error']

    granted = budget.load_config()['policy']['override_turns_granted']
    r = dash_admin.post('/api/zero/v2/budget/override', json={}, headers=dash_admin.csrf)
    assert r.get_json() == {'ok': True, 'override_turns_left': granted}
    r = dash_admin.post('/api/zero/v2/budget/override', json={'turns': 3}, headers=dash_admin.csrf)
    assert r.get_json() == {'ok': True, 'override_turns_left': 3}


def test_tools_index_group_and_search(dash_admin):
    body = dash_admin.get('/api/zero/v2/tools').get_json()
    assert body['count'] > 0
    assert body['index']
    assert 'group' not in body and 'results' not in body

    found = dash_admin.get('/api/zero/v2/tools?q=health').get_json()
    assert found['results'], found
    assert any('health' in str(hit).lower() for hit in found['results'])
