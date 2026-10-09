# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Unit tests for agent_zero.backends.ollama (no server, no app import).

requests.post/get are monkeypatched with fakes that replay scripted ``iter_lines``
transcripts recorded from the real Ollama 0.17.7 on this box, so the whole event
protocol -- native tool loop, JSON fallback, usage numbers, cancel, max_tool_calls and
the two operator-facing error messages -- is asserted without touching the GPU.
"""

import json
import threading

import pytest

from zyg_dashboard.agent_zero.backends import ollama
from zyg_dashboard.agent_zero.contracts import TurnContext

URL = 'http://localhost:11434'
_dumps = json.dumps


class FakeResponse:
    """Minimal stand-in for a streaming ``requests`` response."""

    def __init__(self, chunks, status_code=200, text=''):
        self._chunks = chunks
        self.status_code = status_code
        self.text = text
        self.closed = False

    def iter_lines(self):
        for chunk in self._chunks:
            yield json.dumps(chunk).encode() if isinstance(chunk, dict) else chunk

    def json(self):
        return json.loads(self.text) if self.text else {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise AssertionError(f'HTTP {self.status_code}')

    def close(self):
        self.closed = True


def done_chunk(prompt_eval=11, eval_count=7, content=''):
    chunk = {
        'done': True,
        'done_reason': 'stop',
        'total_duration': 1234567,
        'prompt_eval_count': prompt_eval,
        'eval_count': eval_count,
    }
    if content:
        chunk['message'] = {'role': 'assistant', 'content': content}
    return chunk


def text_chunk(text):
    return {'message': {'role': 'assistant', 'content': text}, 'done': False}


def tool_chunk(name, args):
    return {
        'message': {
            'role': 'assistant',
            'content': '',
            'tool_calls': [{'function': {'name': name, 'arguments': args}}],
        },
        'done': False,
    }


@pytest.fixture(autouse=True)
def _no_capability_cache():
    ollama._capabilities.clear()
    yield
    ollama._capabilities.clear()


@pytest.fixture
def wire(monkeypatch):
    """Install fake transports; returns the recorder of every request made."""

    calls = {'post': [], 'get': [], 'chat_bodies': []}

    def install(chat_responses, capabilities=('completion', 'tools')):
        queue = list(chat_responses)

        def fake_post(url, json=None, stream=False, timeout=None, **kwargs):
            # `json` is requests' keyword for the body, so the module is reached as _dumps.
            calls['post'].append((url, json))
            if url.endswith('/api/show'):
                return FakeResponse([], text=_dumps({'capabilities': list(capabilities)}))
            assert url.endswith('/api/chat'), url
            calls['chat_bodies'].append(json)
            return queue.pop(0)

        def fake_get(url, timeout=None, **kwargs):
            calls['get'].append(url)
            return FakeResponse([], text='{"version": "0.17.7"}')

        monkeypatch.setattr(ollama.requests, 'post', fake_post)
        monkeypatch.setattr(ollama.requests, 'get', fake_get)
        return calls

    return install


def make_ctx(**kwargs):
    tool_log = kwargs.pop('tool_log', [])

    def execute_tool(name, args):
        tool_log.append((name, args))
        return {
            'ok': True,
            'text': f'{name} ok',
            'ms': 3,
            'risk': 'read',
            'needs_confirmation': False,
            'confirm_id': None,
        }

    params = {
        'turn_id': 't1',
        'provider': 'ollama',
        'model': 'qwen3.5:9b',
        'system': 'you are zero',
        'messages': [{'role': 'user', 'content': 'how much vram is free?'}],
        'tools': [{'name': 'zero_find', 'description': 'search', 'input_schema': {'type': 'object'}}],
        'execute_tool': execute_tool,
        'max_tool_calls': 4,
        'timeout_s': 30,
    }
    params.update(kwargs)
    return TurnContext(**params)


def types(events):
    return [event['type'] for event in events]


# ------------------------------------------------------------------ native tool loop


def test_native_tool_loop_events_messages_and_usage(wire):
    calls = wire(
        [
            FakeResponse([tool_chunk('zero_find', {'query': 'vram'}), done_chunk(prompt_eval=40, eval_count=12)]),
            FakeResponse([text_chunk('11 GiB '), text_chunk('is in use.'), done_chunk(prompt_eval=60, eval_count=9)]),
        ]
    )
    log = []
    ctx = make_ctx(tool_log=log)

    events = list(ollama.run(ctx))

    assert types(events) == ['tool_call', 'tool_result', 'text_delta', 'text_delta', 'usage', 'done']
    assert events[0] == {'type': 'tool_call', 'id': 'ollama_tc_0', 'name': 'zero_find', 'args': {'query': 'vram'}}
    assert events[1] == {
        'type': 'tool_result',
        'id': 'ollama_tc_0',
        'name': 'zero_find',
        'ok': True,
        'text': 'zero_find ok',
        'ms': 3,
    }
    assert log == [('zero_find', {'query': 'vram'})]
    assert events[-2] == {
        'type': 'usage',
        'input_tokens': 100,
        'output_tokens': 21,
        'cache_read': 0,
        'cache_write': 0,
        'cost_usd': 0.0,
        'model': 'qwen3.5:9b',
        'local': True,
        'total_duration': 2469134,
    }
    assert events[-1] == {'type': 'done', 'stop_reason': 'end_turn'}

    # The capability probe is one POST /api/show, cached for the rest of the turn.
    assert [url for url, _ in calls['post']].count(f'{URL}/api/show') == 1

    first, second = calls['chat_bodies']
    assert first['messages'][0] == {'role': 'system', 'content': 'you are zero'}
    assert first['stream'] is True and first['think'] is False and first['keep_alive'] == '10m'
    assert first['options'] == {'num_ctx': 32768, 'num_predict': 8192, 'temperature': 0.2}
    assert first['tools'] == [
        {
            'type': 'function',
            'function': {'name': 'zero_find', 'description': 'search', 'parameters': {'type': 'object'}},
        }
    ]
    assert second['messages'][-2] == {
        'role': 'assistant',
        'content': '',
        'tool_calls': [{'function': {'name': 'zero_find', 'arguments': {'query': 'vram'}}}],
    }
    assert second['messages'][-1] == {'role': 'tool', 'content': 'zero_find ok', 'tool_name': 'zero_find'}


def test_thinking_only_reply_becomes_the_answer(wire):
    wire(
        [
            FakeResponse(
                [{'message': {'role': 'assistant', 'thinking': 'the user wants vram'}, 'done': False}, done_chunk()]
            )
        ]
    )

    events = list(ollama.run(make_ctx(thinking_tokens=1024)))

    assert types(events) == ['thinking', 'text_delta', 'usage', 'done']
    assert events[1] == {'type': 'text_delta', 'text': 'the user wants vram'}
    assert events[-1]['stop_reason'] == 'end_turn'


def test_images_ride_on_the_user_message(wire):
    calls = wire([FakeResponse([text_chunk('a duck'), done_chunk()])])
    ctx = make_ctx(
        tools=[],
        messages=[
            {
                'role': 'user',
                'content': [
                    {'type': 'text', 'text': 'what is this?'},
                    {'type': 'image', 'media_type': 'image/png', 'data': 'QUJD'},
                ],
            }
        ],
    )

    list(ollama.run(ctx))

    body = calls['chat_bodies'][0]
    assert body['messages'][-1] == {'role': 'user', 'content': 'what is this?', 'images': ['QUJD']}
    assert 'tools' not in body
    # No tools in the turn means no capability probe at all.
    assert [url for url, _ in calls['post']] == [f'{URL}/api/chat']


def test_max_tool_calls_respected(wire):
    calls = wire(
        [
            FakeResponse([tool_chunk('zero_find', {'query': 'a'}), done_chunk()]),
            FakeResponse([tool_chunk('zero_find', {'query': 'b'}), text_chunk('done then.'), done_chunk()]),
        ]
    )
    log = []

    events = list(ollama.run(make_ctx(max_tool_calls=1, tool_log=log)))

    assert types(events).count('tool_call') == 1
    assert log == [('zero_find', {'query': 'a'})]
    assert events[-1] == {'type': 'done', 'stop_reason': 'max_tool_calls'}
    # The capped final request carries no tools, so the model has to answer.
    assert 'tools' in calls['chat_bodies'][0]
    assert 'tools' not in calls['chat_bodies'][1]


def test_cancel_before_the_first_request(wire):
    calls = wire([])
    cancel = threading.Event()
    cancel.set()

    events = list(ollama.run(make_ctx(cancel=cancel)))

    assert types(events) == ['usage', 'done']
    assert events[-1] == {'type': 'done', 'stop_reason': 'cancelled'}
    assert calls['chat_bodies'] == []


def test_cancel_during_the_stream_stops_the_loop(wire):
    cancel = threading.Event()

    class CancellingResponse(FakeResponse):
        def iter_lines(self):
            yield json.dumps(text_chunk('thinking about it')).encode()
            cancel.set()
            yield json.dumps(done_chunk(prompt_eval=5, eval_count=2)).encode()

    wire([CancellingResponse([])])

    events = list(ollama.run(make_ctx(cancel=cancel)))

    assert types(events) == ['text_delta', 'usage', 'done']
    assert events[-1] == {'type': 'done', 'stop_reason': 'cancelled'}


def test_needs_confirmation_stops_after_the_tool_result(wire):
    wire([FakeResponse([tool_chunk('zero_restart', {}), done_chunk()])])

    def execute_tool(name, args):
        return {
            'ok': False,
            'text': 'confirm?',
            'ms': 1,
            'risk': 'danger',
            'needs_confirmation': True,
            'confirm_id': 'c1',
        }

    events = list(ollama.run(make_ctx(execute_tool=execute_tool)))

    assert types(events) == ['tool_call', 'tool_result', 'usage', 'done']
    assert events[-1] == {'type': 'done', 'stop_reason': 'needs_confirmation'}


# -------------------------------------------------------------------- JSON fallback


def test_json_fallback_executes_the_tool_and_loops(wire):
    calls = wire(
        [
            FakeResponse([text_chunk('{"tool":"zero_find","args":{"query":"vram"}}'), done_chunk()]),
            FakeResponse([text_chunk('11 GiB is in use.'), done_chunk()]),
        ],
        capabilities=('completion', 'vision'),
    )
    log = []

    events = list(ollama.run(make_ctx(tool_log=log)))

    assert types(events) == ['tool_call', 'tool_result', 'text_delta', 'usage', 'done']
    assert events[0]['name'] == 'zero_find' and events[0]['args'] == {'query': 'vram'}
    assert log == [('zero_find', {'query': 'vram'})]
    assert events[2] == {'type': 'text_delta', 'text': '11 GiB is in use.'}
    assert events[-1] == {'type': 'done', 'stop_reason': 'end_turn'}

    first, second = calls['chat_bodies']
    assert 'tools' not in first
    system = first['messages'][0]['content']
    assert system.startswith('you are zero')
    assert '- zero_find: search' in system
    assert 'reply with ONLY a JSON object' in system
    assert second['messages'][-2] == {'role': 'assistant', 'content': '{"tool":"zero_find","args":{"query":"vram"}}'}
    assert second['messages'][-1] == {'role': 'user', 'content': '[tool result for zero_find]: zero_find ok'}


def test_json_fallback_plain_text_is_the_answer(wire):
    wire([FakeResponse([text_chunk('just prose'), done_chunk()])], capabilities=('completion',))

    events = list(ollama.run(make_ctx()))

    assert types(events) == ['text_delta', 'usage', 'done']
    assert events[0] == {'type': 'text_delta', 'text': 'just prose'}
    assert events[-1]['stop_reason'] == 'end_turn'


def test_json_fallback_tool_call_after_prose(wire):
    wire(
        [
            FakeResponse(
                [text_chunk('Let me look.\n{"tool": "zero_index", "args": {"group": "system"}}'), done_chunk()]
            ),
            FakeResponse([text_chunk('indexed.'), done_chunk()]),
        ],
        capabilities=('completion',),
    )

    events = list(ollama.run(make_ctx()))

    assert types(events) == ['text_delta', 'tool_call', 'tool_result', 'text_delta', 'usage', 'done']
    assert events[0] == {'type': 'text_delta', 'text': 'Let me look.'}
    assert events[1]['name'] == 'zero_index' and events[1]['args'] == {'group': 'system'}


def test_json_fallback_respects_max_tool_calls(wire):
    wire(
        [
            FakeResponse([text_chunk('{"tool":"zero_find","args":{}}'), done_chunk()]),
            FakeResponse([text_chunk('{"tool":"zero_find","args":{}}'), done_chunk()]),
        ],
        capabilities=('completion',),
    )
    log = []

    events = list(ollama.run(make_ctx(max_tool_calls=1, tool_log=log)))

    assert types(events).count('tool_call') == 1
    assert len(log) == 1
    assert events[-1] == {'type': 'done', 'stop_reason': 'max_tool_calls'}


# -------------------------------------------------------------------------- failures


def test_missing_model_is_an_install_hint(monkeypatch):
    def fake_post(url, json=None, stream=False, timeout=None, **kwargs):
        return FakeResponse([], status_code=404, text='{"error": "model \'nope:1b\' not found"}')

    monkeypatch.setattr(ollama.requests, 'post', fake_post)

    events = list(ollama.run(make_ctx(model='nope:1b')))

    assert types(events) == ['error', 'done']
    assert events[0] == {
        'type': 'error',
        'message': 'model nope:1b is not installed — open Select Model to install it',
        'kind': 'backend',
    }
    assert events[-1] == {'type': 'done', 'stop_reason': 'error'}


def test_connection_refused_says_ollama_is_not_running(monkeypatch):
    def fake_post(url, json=None, stream=False, timeout=None, **kwargs):
        raise ollama.requests.exceptions.ConnectionError('refused')

    monkeypatch.setattr(ollama.requests, 'post', fake_post)

    events = list(ollama.run(make_ctx()))

    assert types(events) == ['error', 'done']
    assert events[0]['message'] == f'Ollama is not running on {URL}'
    assert events[0]['kind'] == 'backend'


def test_error_chunk_mid_stream_ends_the_turn(wire):
    wire([FakeResponse([text_chunk('half an answer'), {'error': 'model runner has unexpectedly stopped'}])])

    events = list(ollama.run(make_ctx()))

    assert types(events) == ['text_delta', 'error', 'done']
    assert 'model runner' in events[1]['message']
    assert events[-1]['stop_reason'] == 'error'


def test_probe_reports_version_and_offline(monkeypatch):
    monkeypatch.setattr(
        ollama.requests, 'get', lambda url, timeout=None, **kw: FakeResponse([], text='{"version": "0.17.7"}')
    )
    assert ollama.probe() == {'ok': True, 'detail': f'ollama 0.17.7 at {URL}'}

    def boom(url, timeout=None, **kwargs):
        raise ollama.requests.exceptions.ConnectionError('refused')

    monkeypatch.setattr(ollama.requests, 'get', boom)
    probed = ollama.probe()
    assert probed['ok'] is False and probed['detail'].startswith('offline:')
