# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Unit tests for the two Agent Zero v2 API backends.

No network: `anthropic.Anthropic` and `openai.OpenAI` are monkeypatched with fakes
built from `types.SimpleNamespace`, scripted to ask for a tool on the first turn
and to finish on the second. What is asserted is the contract the rest of
agent_zero depends on — the event order, the parsed tool arguments, the
max_tool_calls and cancel stops, the error kinds, and the exact request shape
(cache_control on the Anthropic system prompt, function tools on the OpenAI side,
base64 data URLs for images).
"""

import json
import threading
import types

import httpx
import pytest

from zyg_dashboard.agent_zero.backends import anthropic_api, openai_compat

# The fakes are installed by patching attributes ON the vendor modules, so both SDKs have to
# be importable even though no request ever leaves the process. They are optional extras of
# the dashboard package; a core checkout skips this module instead of erroring in every test.
pytest.importorskip('anthropic', reason='the anthropic SDK is the optional [llm] extra')
pytest.importorskip('openai', reason='the openai SDK is an optional extra')

MODEL = 'claude-opus-5'
OAI_MODEL = 'gpt-5'


# --------------------------------------------------------------------------- #
# shared fixtures / helpers
# --------------------------------------------------------------------------- #


def make_ctx(provider, model, **over):
    """A duck-typed TurnContext (the real dataclass when task 1's module is present)."""
    calls = []

    def execute_tool(name, args):
        calls.append((name, args))
        return {
            'ok': True,
            'text': f'{name} ok',
            'ms': 12,
            'risk': 'read',
            'needs_confirmation': False,
            'confirm_id': None,
        }

    base = {
        'turn_id': 'turn-1',
        'session_id': 'sess-1',
        'provider': provider,
        'model': model,
        'system': 'You are Zero.',
        'messages': [{'role': 'user', 'content': [{'type': 'text', 'text': 'hi'}]}],
        'tools': [
            {
                'name': 'read_file',
                'description': 'read a file',
                'input_schema': {'type': 'object', 'properties': {'path': {'type': 'string'}}},
            }
        ],
        'execute_tool': execute_tool,
        'max_output_tokens': 512,
        'max_tool_calls': 4,
        'thinking_tokens': 0,
        'timeout_s': 30,
        'cookie': '',
        'csrf': '',
        'cancel': threading.Event(),
        'extra': {},
    }
    base.update(over)
    try:
        from zyg_dashboard.agent_zero.contracts import TurnContext

        ctx = TurnContext(**base)
    except Exception:  # noqa: BLE001 - contracts.py may not exist yet
        ctx = types.SimpleNamespace(**base)
    ctx.tool_calls_seen = calls
    return ctx


def types_of(events):
    return [e['type'] for e in events]


def _http_error(cls, status):
    request = httpx.Request('POST', 'https://example.invalid/v1/x')
    response = httpx.Response(status, request=request)
    return cls('nope', response=response, body=None)


@pytest.fixture(autouse=True)
def _keys(monkeypatch):
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'sk-ant-test-key')
    monkeypatch.setenv('OPENAI_API_KEY', 'sk-oai-test-key')


# --------------------------------------------------------------------------- #
# Anthropic fake SDK
# --------------------------------------------------------------------------- #


def usage_obj(tin=10, tout=5, cache_read=0, cache_write=0):
    return types.SimpleNamespace(
        input_tokens=tin,
        output_tokens=tout,
        cache_read_input_tokens=cache_read,
        cache_creation_input_tokens=cache_write,
    )


def text_event(text):
    return types.SimpleNamespace(type='text', text=text, snapshot=text)


def tool_use_turn(call_id='call-1', name='read_file', args=None):
    return types.SimpleNamespace(
        stop_reason='tool_use',
        content=[
            {
                'type': 'tool_use',
                'id': call_id,
                'name': name,
                'input': args if args is not None else {'path': 'notes.txt'},
            }
        ],
        usage=usage_obj(cache_write=7),
    )


def end_turn(text='all done'):
    return types.SimpleNamespace(
        stop_reason='end_turn', content=[{'type': 'text', 'text': text}], usage=usage_obj(tin=20, tout=8, cache_read=7)
    )


class FakeStream:
    def __init__(self, events, final):
        self._events = events
        self._final = final

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def __iter__(self):
        return iter(self._events)

    def get_final_message(self):
        return self._final


def install_fake_anthropic(monkeypatch, script, raises=None):
    """script = [(events, final_message), ...]; raises = exception for the Nth call."""
    import anthropic

    requests = []
    state = {'i': 0}

    class FakeMessages:
        def stream(self, **req):
            requests.append(req)
            index = state['i']
            state['i'] += 1
            if raises is not None and index == raises[0]:
                raise raises[1]
            events, final = script[min(index, len(script) - 1)]
            return FakeStream(events, final)

    class FakeAnthropic:
        def __init__(self, **kwargs):
            requests.append({'_client_kwargs': kwargs})
            self.messages = FakeMessages()

    monkeypatch.setattr(anthropic, 'Anthropic', FakeAnthropic)
    return requests


# --------------------------------------------------------------------------- #
# OpenAI fake SDK
# --------------------------------------------------------------------------- #


def chunk(content=None, tool_calls=None, finish_reason=None, usage=None, reasoning=None):
    delta = types.SimpleNamespace(content=content, tool_calls=tool_calls, reasoning_content=reasoning)
    choice = types.SimpleNamespace(delta=delta, finish_reason=finish_reason, index=0)
    return types.SimpleNamespace(choices=[choice], usage=usage)


def usage_chunk(prompt=11, completion=4, cached=0):
    usage = types.SimpleNamespace(
        prompt_tokens=prompt,
        completion_tokens=completion,
        prompt_tokens_details=types.SimpleNamespace(cached_tokens=cached),
    )
    return types.SimpleNamespace(choices=[], usage=usage)


def tool_fragment(index=0, call_id=None, name=None, arguments=None):
    function = types.SimpleNamespace(name=name, arguments=arguments)
    return types.SimpleNamespace(index=index, id=call_id, type='function', function=function)


def oai_tool_turn():
    """Text, then one tool call whose arguments arrive split over two chunks."""
    return [
        chunk(content='looking'),
        chunk(tool_calls=[tool_fragment(call_id='call-1', name='read_file', arguments='{"path":')]),
        chunk(tool_calls=[tool_fragment(arguments=' "notes.txt"}')]),
        chunk(finish_reason='tool_calls'),
        usage_chunk(),
    ]


def oai_end_turn(text='all done'):
    return [chunk(content=text), chunk(finish_reason='stop'), usage_chunk(prompt=20, completion=6, cached=11)]


def install_fake_openai(monkeypatch, script, raises=None):
    import openai

    requests = []
    state = {'i': 0}

    class FakeCompletions:
        def create(self, **req):
            requests.append(req)
            index = state['i']
            state['i'] += 1
            if raises is not None and index == raises[0]:
                raise raises[1]
            return iter(script[min(index, len(script) - 1)])

    class FakeOpenAI:
        def __init__(self, **kwargs):
            requests.append({'_client_kwargs': kwargs})
            self.chat = types.SimpleNamespace(completions=FakeCompletions())

    monkeypatch.setattr(openai, 'OpenAI', FakeOpenAI)
    return requests


# --------------------------------------------------------------------------- #
# the happy path, both backends
# --------------------------------------------------------------------------- #


def test_anthropic_tool_loop_event_order(monkeypatch):
    install_fake_anthropic(
        monkeypatch,
        [
            ([text_event('looking')], tool_use_turn()),
            ([text_event('all done')], end_turn()),
        ],
    )
    ctx = make_ctx('anthropic', MODEL)
    events = list(anthropic_api.run(ctx))

    assert types_of(events) == ['text_delta', 'tool_call', 'tool_result', 'text_delta', 'usage', 'done']
    assert events[-1]['stop_reason'] == 'end_turn'
    assert ctx.tool_calls_seen == [('read_file', {'path': 'notes.txt'})]
    assert events[1]['name'] == 'read_file' and events[1]['args'] == {'path': 'notes.txt'}
    assert events[2]['ok'] is True and events[2]['ms'] == 12
    usage = events[4]
    assert (usage['input_tokens'], usage['output_tokens']) == (30, 13)
    assert (usage['cache_read'], usage['cache_write']) == (7, 7)
    assert usage['model'] == MODEL
    # Priced through the host's quota_meter (its table covers the Claude families).
    assert usage['priced'] is True and usage['cost_usd'] > 0


def test_openai_tool_loop_event_order(monkeypatch):
    requests = install_fake_openai(monkeypatch, [oai_tool_turn(), oai_end_turn()])
    ctx = make_ctx('openai', OAI_MODEL)
    events = list(openai_compat.run(ctx))

    assert types_of(events) == ['text_delta', 'tool_call', 'tool_result', 'text_delta', 'usage', 'done']
    assert events[-1]['stop_reason'] == 'end_turn'
    assert ctx.tool_calls_seen == [('read_file', {'path': 'notes.txt'})]
    usage = events[4]
    assert (usage['input_tokens'], usage['output_tokens']) == (31, 10)
    assert usage['cache_read'] == 11
    # gpt-5 is in models_catalog.json at 1.25 / 10.00 per MTok: 31 in + 10 out.
    assert usage['priced'] is True
    assert usage['cost_usd'] == pytest.approx((31 * 1.25 + 10 * 10.0) / 1e6)

    second = [r for r in requests if 'messages' in r][1]
    roles = [m['role'] for m in second['messages']]
    assert roles == ['system', 'user', 'assistant', 'tool']
    assert second['messages'][2]['tool_calls'][0]['function']['name'] == 'read_file'
    assert json.loads(second['messages'][2]['tool_calls'][0]['function']['arguments']) == {'path': 'notes.txt'}
    assert second['messages'][3] == {'role': 'tool', 'tool_call_id': 'call-1', 'content': 'read_file ok'}


# --------------------------------------------------------------------------- #
# request shape
# --------------------------------------------------------------------------- #


def test_anthropic_request_shape_and_image_block(monkeypatch):
    requests = install_fake_anthropic(monkeypatch, [([text_event('hi')], end_turn('hi'))])
    ctx = make_ctx(
        'anthropic',
        MODEL,
        thinking_tokens=2048,
        messages=[
            {
                'role': 'user',
                'content': [
                    {'type': 'text', 'text': 'what is this'},
                    {'type': 'image', 'media_type': 'image/jpeg', 'data': 'QUJD'},
                ],
            },
        ],
    )
    list(anthropic_api.run(ctx))

    client_kwargs = requests[0]['_client_kwargs']
    assert client_kwargs['api_key'] == 'sk-ant-test-key'
    assert client_kwargs['timeout'] == 30 and client_kwargs['max_retries'] == 2

    req = requests[1]
    assert req['system'] == [{'type': 'text', 'text': 'You are Zero.', 'cache_control': {'type': 'ephemeral'}}]
    assert req['model'] == MODEL and req['max_tokens'] == 512
    assert req['tool_choice'] == {'type': 'auto'}
    assert req['tools'][0]['input_schema']['properties']['path']['type'] == 'string'
    assert req['thinking'] == {'type': 'adaptive'}
    assert req['output_config'] == {'effort': 'low'}
    assert req['messages'][0]['content'][1] == {
        'type': 'image',
        'source': {'type': 'base64', 'media_type': 'image/jpeg', 'data': 'QUJD'},
    }


def test_anthropic_omits_thinking_when_budget_is_zero(monkeypatch):
    requests = install_fake_anthropic(monkeypatch, [([text_event('hi')], end_turn('hi'))])
    list(anthropic_api.run(make_ctx('anthropic', MODEL, thinking_tokens=0)))
    req = requests[1]
    assert 'thinking' not in req and 'output_config' not in req


def test_anthropic_effort_medium_above_4k(monkeypatch):
    requests = install_fake_anthropic(monkeypatch, [([text_event('hi')], end_turn('hi'))])
    list(anthropic_api.run(make_ctx('anthropic', MODEL, thinking_tokens=8192)))
    assert requests[1]['output_config'] == {'effort': 'medium'}


def test_openai_request_shape_and_image_block(monkeypatch):
    requests = install_fake_openai(monkeypatch, [oai_end_turn('hi')])
    ctx = make_ctx(
        'openai',
        OAI_MODEL,
        messages=[
            {
                'role': 'user',
                'content': [
                    {'type': 'text', 'text': 'what is this'},
                    {'type': 'image', 'media_type': 'image/jpeg', 'data': 'QUJD'},
                ],
            },
        ],
    )
    list(openai_compat.run(ctx))

    client_kwargs = requests[0]['_client_kwargs']
    assert client_kwargs['api_key'] == 'sk-oai-test-key'
    assert client_kwargs['base_url'] == 'https://api.openai.com/v1'
    assert client_kwargs['timeout'] == 30 and client_kwargs['max_retries'] == 2

    req = requests[1]
    assert req['stream'] is True and req['stream_options'] == {'include_usage': True}
    assert req['tools'][0]['type'] == 'function'
    assert req['tools'][0]['function']['name'] == 'read_file'
    assert req['tools'][0]['function']['parameters']['properties']['path']['type'] == 'string'
    assert req['messages'][0] == {'role': 'system', 'content': 'You are Zero.'}
    assert req['messages'][1]['content'][1] == {
        'type': 'image_url',
        'image_url': {'url': 'data:image/jpeg;base64,QUJD'},
    }


def test_openai_provider_quirks(monkeypatch):
    monkeypatch.setenv('GOOGLE_API_KEY', 'goog-test')
    requests = install_fake_openai(monkeypatch, [oai_end_turn('hi')])
    list(openai_compat.run(make_ctx('google', 'gemini-3-pro')))
    google_req = requests[1]
    assert 'stream_options' not in google_req
    assert 'parallel_tool_calls' not in google_req
    assert requests[0]['_client_kwargs']['base_url'] == 'https://generativelanguage.googleapis.com/v1beta/openai'

    monkeypatch.setenv('GROQ_API_KEY', 'gsk-test')
    requests = install_fake_openai(monkeypatch, [oai_end_turn('hi')])
    list(openai_compat.run(make_ctx('groq', 'llama-3.3-70b')))
    assert requests[1]['parallel_tool_calls'] is False
    assert requests[1]['stream_options'] == {'include_usage': True}


# --------------------------------------------------------------------------- #
# stops: max_tool_calls, cancel
# --------------------------------------------------------------------------- #


def test_anthropic_stops_at_max_tool_calls(monkeypatch):
    install_fake_anthropic(monkeypatch, [([text_event('again')], tool_use_turn())])
    ctx = make_ctx('anthropic', MODEL, max_tool_calls=1)
    events = list(anthropic_api.run(ctx))

    assert events[-1] == {'type': 'done', 'stop_reason': 'max_tool_calls'}
    assert len(ctx.tool_calls_seen) == 1
    assert [e['type'] for e in events].count('tool_call') == 1


def test_openai_stops_at_max_tool_calls(monkeypatch):
    install_fake_openai(monkeypatch, [oai_tool_turn()])
    ctx = make_ctx('openai', OAI_MODEL, max_tool_calls=1)
    events = list(openai_compat.run(ctx))

    assert events[-1] == {'type': 'done', 'stop_reason': 'max_tool_calls'}
    assert len(ctx.tool_calls_seen) == 1


def test_anthropic_cancel_before_second_iteration(monkeypatch):
    install_fake_anthropic(
        monkeypatch,
        [
            ([text_event('looking')], tool_use_turn()),
            ([text_event('never')], end_turn()),
        ],
    )
    ctx = make_ctx('anthropic', MODEL)
    inner = ctx.execute_tool

    def cancelling(name, args):
        result = inner(name, args)
        ctx.cancel.set()
        return result

    ctx.execute_tool = cancelling
    events = list(anthropic_api.run(ctx))

    assert events[-1] == {'type': 'done', 'stop_reason': 'cancelled'}
    assert types_of(events) == ['text_delta', 'tool_call', 'tool_result', 'usage', 'done']


def test_openai_cancel_before_second_iteration(monkeypatch):
    install_fake_openai(monkeypatch, [oai_tool_turn(), oai_end_turn('never')])
    ctx = make_ctx('openai', OAI_MODEL)
    inner = ctx.execute_tool

    def cancelling(name, args):
        result = inner(name, args)
        ctx.cancel.set()
        return result

    ctx.execute_tool = cancelling
    events = list(openai_compat.run(ctx))

    assert events[-1] == {'type': 'done', 'stop_reason': 'cancelled'}
    assert 'text_delta' in types_of(events)


# --------------------------------------------------------------------------- #
# errors
# --------------------------------------------------------------------------- #


def test_anthropic_auth_error(monkeypatch):
    import anthropic

    install_fake_anthropic(monkeypatch, [([], end_turn())], raises=(0, _http_error(anthropic.AuthenticationError, 401)))
    events = list(anthropic_api.run(make_ctx('anthropic', MODEL)))

    assert types_of(events) == ['error', 'done']
    assert events[0]['kind'] == 'auth'
    assert events[1]['stop_reason'] == 'error'


def test_anthropic_rate_limit_and_status_errors(monkeypatch):
    import anthropic

    install_fake_anthropic(monkeypatch, [([], end_turn())], raises=(0, _http_error(anthropic.RateLimitError, 429)))
    assert next(iter(anthropic_api.run(make_ctx('anthropic', MODEL))))['kind'] == 'limit'

    install_fake_anthropic(monkeypatch, [([], end_turn())], raises=(0, _http_error(anthropic.APIStatusError, 500)))
    assert next(iter(anthropic_api.run(make_ctx('anthropic', MODEL))))['kind'] == 'backend'


def _no_stored_keys(monkeypatch):
    """Blind the key store so 'no key' does not depend on this box's saved keys."""
    from zyg_dashboard.agent_zero import models

    monkeypatch.setattr(models, 'provider_key', lambda provider: '')


def test_anthropic_missing_key_is_auth_error(monkeypatch):
    _no_stored_keys(monkeypatch)
    monkeypatch.delenv('ANTHROPIC_API_KEY', raising=False)
    monkeypatch.delenv('CLAUDE_API_KEY', raising=False)
    events = list(anthropic_api.run(make_ctx('anthropic', MODEL)))
    assert types_of(events) == ['error', 'done']
    assert events[0]['kind'] == 'auth'
    assert anthropic_api.probe()['ok'] is False


def test_anthropic_refusal_is_backend_error(monkeypatch):
    refusal = types.SimpleNamespace(stop_reason='refusal', content=[], usage=usage_obj(), stop_details='policy')
    install_fake_anthropic(monkeypatch, [([text_event('hm')], refusal)])
    events = list(anthropic_api.run(make_ctx('anthropic', MODEL)))

    assert types_of(events) == ['text_delta', 'usage', 'error', 'done']
    assert events[2]['kind'] == 'backend' and 'policy' in events[2]['message']
    assert events[3]['stop_reason'] == 'error'


def test_openai_auth_error(monkeypatch):
    import openai

    install_fake_openai(monkeypatch, [oai_end_turn()], raises=(0, _http_error(openai.AuthenticationError, 401)))
    events = list(openai_compat.run(make_ctx('openai', OAI_MODEL)))

    assert types_of(events) == ['error', 'done']
    assert events[0]['kind'] == 'auth'
    assert events[1]['stop_reason'] == 'error'


def test_openai_rate_limit_and_status_errors(monkeypatch):
    import openai

    install_fake_openai(monkeypatch, [oai_end_turn()], raises=(0, _http_error(openai.RateLimitError, 429)))
    assert next(iter(openai_compat.run(make_ctx('openai', OAI_MODEL))))['kind'] == 'limit'

    install_fake_openai(monkeypatch, [oai_end_turn()], raises=(0, _http_error(openai.APIStatusError, 503)))
    assert next(iter(openai_compat.run(make_ctx('openai', OAI_MODEL))))['kind'] == 'backend'


def test_openai_unknown_model_is_reported_unpriced(monkeypatch):
    install_fake_openai(monkeypatch, [oai_end_turn('hi')])
    events = list(openai_compat.run(make_ctx('openai', 'no-such-model-42')))
    usage = next(e for e in events if e['type'] == 'usage')
    assert usage['priced'] is False and usage['cost_usd'] == 0.0


def test_openai_missing_key_is_auth_error(monkeypatch):
    _no_stored_keys(monkeypatch)
    monkeypatch.delenv('OPENAI_API_KEY', raising=False)
    events = list(openai_compat.run(make_ctx('openai', OAI_MODEL)))
    assert types_of(events) == ['error', 'done']
    assert events[0]['kind'] == 'auth'
    assert openai_compat.probe('openai')['ok'] is False


def test_openai_reasoning_deltas_become_thinking_events(monkeypatch):
    monkeypatch.setenv('DEEPSEEK_API_KEY', 'ds-test')
    install_fake_openai(
        monkeypatch,
        [
            [
                chunk(reasoning='weighing it up'),
                chunk(content='answer'),
                chunk(finish_reason='stop'),
                usage_chunk(),
            ]
        ],
    )
    events = list(openai_compat.run(make_ctx('deepseek', 'deepseek-reasoner', max_tool_calls=0, tools=[])))
    assert types_of(events)[:2] == ['thinking', 'text_delta']
    assert events[0]['text'] == 'weighing it up'
    assert events[-1]['stop_reason'] == 'end_turn'


def test_execute_tool_exception_becomes_failed_tool_result(monkeypatch):
    install_fake_anthropic(
        monkeypatch,
        [
            ([text_event('looking')], tool_use_turn()),
            ([text_event('all done')], end_turn()),
        ],
    )

    def boom(name, args):
        raise RuntimeError('tool exploded')

    ctx = make_ctx('anthropic', MODEL, execute_tool=boom)
    events = list(anthropic_api.run(ctx))

    result = next(e for e in events if e['type'] == 'tool_result')
    assert result['ok'] is False and 'tool exploded' in result['text']
    assert events[-1]['stop_reason'] == 'end_turn'
