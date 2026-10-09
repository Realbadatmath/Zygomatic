# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Agent Zero v2 backend for every OpenAI-compatible chat-completions provider.

One module serves openai, google, openrouter, groq, deepseek, mistral, xai and
together: they all speak `/chat/completions`, they differ only in base_url, key
and a handful of quirks collected in `QUIRKS` below. The turn runs the same tool
loop as the Anthropic backend — streamed text, every tool call through
`ctx.execute_tool`, a stop at `ctx.max_tool_calls` and on `ctx.cancel`, one priced
`usage` event and exactly one `done`.

The `openai` SDK is imported lazily inside the functions so that importing this
module costs nothing and the rest of agent_zero stays stdlib-only.
"""

# A backend's whole job is to turn every failure into an event instead of an
# exception, so a blind `except Exception` is the contract here, not a smell.

from __future__ import annotations

import json
import logging
import os
from collections.abc import Iterator
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover - typing only
    from ..contracts import TurnContext

_log = logging.getLogger(__name__)

#: Per-provider quirks of the "OpenAI-compatible" surface, as measured:
#:  * stream_usage: the provider honours stream_options={'include_usage': True}.
#:    Google's compatibility layer rejects the field, so we must not send it and
#:    take the usage from the last chunk if it happens to carry one.
#:  * parallel_tool_calls: False pins the request to one tool call per turn; groq
#:    rejects parallel tool calls on several of its hosted models.
#:  * env: env vars consulted when agent_zero.models cannot hand us a key.
#:  * base_url: fallback endpoint when models_catalog.json has none.
QUIRKS: dict[str, dict] = {
    'openai': {
        'env': ('OPENAI_API_KEY',),
        'base_url': 'https://api.openai.com/v1',
    },
    'google': {
        'env': ('GOOGLE_API_KEY', 'GEMINI_API_KEY'),
        'base_url': 'https://generativelanguage.googleapis.com/v1beta/openai/',
        'stream_usage': False,
    },
    'openrouter': {
        'env': ('OPENROUTER_API_KEY',),
        'base_url': 'https://openrouter.ai/api/v1',
    },
    'groq': {
        'env': ('GROQ_API_KEY',),
        'base_url': 'https://api.groq.com/openai/v1',
        'parallel_tool_calls': False,
    },
    'deepseek': {
        'env': ('DEEPSEEK_API_KEY',),
        'base_url': 'https://api.deepseek.com/v1',
    },
    'mistral': {
        'env': ('MISTRAL_API_KEY',),
        'base_url': 'https://api.mistral.ai/v1',
    },
    'xai': {
        'env': ('XAI_API_KEY', 'GROK_API_KEY'),
        'base_url': 'https://api.x.ai/v1',
    },
    'together': {
        'env': ('TOGETHER_API_KEY',),
        'base_url': 'https://api.together.xyz/v1',
    },
}


# --------------------------------------------------------------------------- #
# host / catalogue access (all optional, all failure-tolerant)
# --------------------------------------------------------------------------- #


def _models_module():
    """agent_zero.models if it is importable, else None."""
    try:
        from .. import models
    except Exception:  # pragma: no cover - exercised only before task 1 lands
        return None
    return models


def _provider_meta(provider: str) -> dict:
    """label / key_env / base_url for one provider id, or {} without the catalogue."""
    models = _models_module()
    if models is None:
        return {}
    try:
        return models.provider_meta(provider) or {}
    except Exception:
        _log.warning('agent_zero.models.provider_meta(%r) failed', provider, exc_info=True)
        return {}


def _catalogue_entry(provider: str, model: str) -> dict:
    """The models_catalog.json row for `model`, or {} when the catalogue has none."""
    models = _models_module()
    if models is None:
        return {}
    try:
        rows = models.seed_models(provider) or []
    except Exception:
        _log.warning('agent_zero.models.seed_models(%r) failed', provider, exc_info=True)
        return {}
    for row in rows:
        if isinstance(row, dict) and row.get('id') == model:
            return row
    return {}


def _base_url(provider: str) -> str | None:
    """The provider's OpenAI-compatible endpoint: catalogue first, QUIRKS second."""
    url = _provider_meta(provider).get('base_url')
    if url:
        return str(url)
    return QUIRKS.get(provider, {}).get('base_url')


def _resolve_key(provider: str) -> str | None:
    """The API key for `provider`: models.provider_key first, env vars as fallback."""
    models = _models_module()
    if models is not None:
        try:
            key = models.provider_key(provider)
        except Exception:
            _log.warning('agent_zero.models.provider_key(%r) failed', provider, exc_info=True)
            key = None
        if key:
            return str(key).strip()
    for env in QUIRKS.get(provider, {}).get('env', ()):
        value = os.environ.get(env)
        if value and value.strip():
            return value.strip()
    return None


def _quota_meter():
    """The host's quota_meter module via _host, or None."""
    try:
        from .. import _host
    except Exception:  # pragma: no cover
        return None
    try:
        return _host.quota_meter()
    except Exception:
        _log.warning('_host.quota_meter() failed', exc_info=True)
        return None


# --------------------------------------------------------------------------- #
# request shaping
# --------------------------------------------------------------------------- #


def _attr(obj: Any, name: str, default: Any = None) -> Any:
    """Read `name` off a dict or an object (the SDK gives objects, fakes give both)."""
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _data_url(block: Any) -> str:
    media = _attr(block, 'media_type', 'image/png') or 'image/png'
    return f'data:{media};base64,{_attr(block, "data", "") or ""}'


def _convert_messages(system: str, messages: list) -> list:
    """CONTRACT C messages -> chat-completions messages.

    Blocks fan out: text/image stay inside the user message's content array, a
    tool_use block becomes the assistant message's `tool_calls`, and every
    tool_result block becomes its own `{'role': 'tool'}` message.
    """
    out: list[dict] = []
    if system:
        out.append({'role': 'system', 'content': system})
    for msg in messages or []:
        role = _attr(msg, 'role', 'user')
        content = _attr(msg, 'content')
        if isinstance(content, str):
            out.append({'role': role, 'content': content})
            continue
        parts: list[dict] = []
        tool_calls: list[dict] = []
        tool_messages: list[dict] = []
        for block in content or []:
            btype = _attr(block, 'type')
            if btype == 'text':
                parts.append({'type': 'text', 'text': _attr(block, 'text', '') or ''})
            elif btype == 'image':
                parts.append({'type': 'image_url', 'image_url': {'url': _data_url(block)}})
            elif btype == 'tool_use':
                tool_calls.append(
                    {
                        'id': _attr(block, 'id', '') or '',
                        'type': 'function',
                        'function': {
                            'name': _attr(block, 'name', '') or '',
                            'arguments': json.dumps(_attr(block, 'input') or {}),
                        },
                    }
                )
            elif btype == 'tool_result':
                tool_messages.append(
                    {
                        'role': 'tool',
                        'tool_call_id': _attr(block, 'tool_use_id', '') or '',
                        'content': str(_attr(block, 'content', '') or ''),
                    }
                )
        if parts or tool_calls:
            entry: dict[str, Any] = {'role': role}
            if role == 'assistant' and tool_calls:
                entry['content'] = ''.join(p['text'] for p in parts if p['type'] == 'text') or None
                entry['tool_calls'] = tool_calls
            else:
                entry['content'] = parts
            out.append(entry)
        out.extend(tool_messages)
    return out


def _convert_tools(tools: list) -> list:
    """CONTRACT C tools -> chat-completions function tools."""
    out = []
    for tool in tools or []:
        out.append(
            {
                'type': 'function',
                'function': {
                    'name': _attr(tool, 'name'),
                    'description': _attr(tool, 'description', '') or '',
                    'parameters': _attr(tool, 'input_schema') or {'type': 'object', 'properties': {}},
                },
            }
        )
    return out


def _build_request(ctx: TurnContext, provider: str) -> dict:
    """The static half of the request (everything but `messages`)."""
    quirks = QUIRKS.get(provider, {})
    req: dict[str, Any] = {
        'model': ctx.model,
        'max_tokens': int(ctx.max_output_tokens),
        'stream': True,
    }
    if quirks.get('stream_usage', True):
        req['stream_options'] = {'include_usage': True}
    tools = _convert_tools(ctx.tools)
    if tools:
        req['tools'] = tools
        req['tool_choice'] = 'auto'
        if quirks.get('parallel_tool_calls') is False:
            req['parallel_tool_calls'] = False
    return req


# --------------------------------------------------------------------------- #
# usage / pricing
# --------------------------------------------------------------------------- #


def _zero_usage() -> dict:
    return {'input_tokens': 0, 'output_tokens': 0, 'cache_read': 0, 'cache_write': 0}


def _add_usage(total: dict, usage: Any) -> None:
    """Accumulate one response's `usage` block into `total`."""
    if usage is None:
        return
    try:
        total['input_tokens'] += int(_attr(usage, 'prompt_tokens', 0) or 0)
        total['output_tokens'] += int(_attr(usage, 'completion_tokens', 0) or 0)
    except (TypeError, ValueError):
        return
    details = _attr(usage, 'prompt_tokens_details')
    if details is not None:
        try:
            total['cache_read'] += int(_attr(details, 'cached_tokens', 0) or 0)
        except (TypeError, ValueError):
            pass


def _price(provider: str, model: str, usage: dict) -> tuple[float, bool]:
    """(cost_usd, priced) — the host's quota_meter first, the catalogue second.

    `prompt_tokens` already includes the cached prefix on every one of these
    providers, so cache_read is reported but never billed twice.
    """
    meter = _quota_meter()
    if meter is not None and hasattr(meter, 'price_tokens'):
        try:
            cost = meter.price_tokens(model, usage['input_tokens'], usage['output_tokens'], 0, 0)
        except Exception:
            _log.warning('quota_meter.price_tokens(%r) failed', model, exc_info=True)
            cost = None
        if cost is not None:
            return float(cost), True
    entry = _catalogue_entry(provider, model)
    price_in, price_out = entry.get('price_in'), entry.get('price_out')
    if price_in is None and price_out is None:
        return 0.0, False
    cost = (usage['input_tokens'] * float(price_in or 0.0) + usage['output_tokens'] * float(price_out or 0.0)) / 1e6
    return cost, True


def _usage_event(provider: str, model: str, usage: dict) -> dict:
    cost, priced = _price(provider, model, usage)
    return {
        'type': 'usage',
        'input_tokens': usage['input_tokens'],
        'output_tokens': usage['output_tokens'],
        'cache_read': usage['cache_read'],
        'cache_write': usage['cache_write'],
        'cost_usd': round(cost, 8),  # a short turn costs well under a tenth of a cent
        'priced': priced,
        'model': model,
    }


def _error_event(message: str, kind: str) -> dict:
    return {'type': 'error', 'message': message, 'kind': kind}


def _finish(provider: str, model: str, usage: dict, stop_reason: str, error: dict | None = None) -> Iterator[dict]:
    """The tail of every turn: at most one usage, at most one error, exactly one done."""
    if any(usage.values()):
        yield _usage_event(provider, model, usage)
    if error is not None:
        yield error
    yield {'type': 'done', 'stop_reason': stop_reason}


def _classify(openai_mod: Any, exc: BaseException) -> str:
    """Map an SDK exception to a CONTRACT C error kind."""
    for attr, kind in (('AuthenticationError', 'auth'), ('PermissionDeniedError', 'auth'), ('RateLimitError', 'limit')):
        cls = getattr(openai_mod, attr, None)
        if isinstance(cls, type) and isinstance(exc, cls):
            return kind
    return 'backend'


# --------------------------------------------------------------------------- #
# streaming
# --------------------------------------------------------------------------- #


class _ToolAccumulator:
    """Collects streamed tool_call fragments, which arrive split by `index`."""

    def __init__(self) -> None:
        self._by_index: dict[int, dict] = {}

    def add(self, fragment: Any) -> None:
        index = _attr(fragment, 'index', 0) or 0
        slot = self._by_index.setdefault(int(index), {'id': '', 'name': '', 'arguments': ''})
        call_id = _attr(fragment, 'id')
        if call_id:
            slot['id'] = call_id
        function = _attr(fragment, 'function')
        if function is None:
            return
        name = _attr(function, 'name')
        if name:
            slot['name'] = name
        arguments = _attr(function, 'arguments')
        if arguments:
            slot['arguments'] += arguments

    def calls(self) -> list[dict]:
        return [self._by_index[i] for i in sorted(self._by_index)]


def _parse_args(call: dict) -> dict:
    raw = call.get('arguments') or '{}'
    try:
        args = json.loads(raw)
    except (TypeError, ValueError):
        _log.warning('tool %r sent unparseable arguments: %r', call.get('name'), raw)
        return {}
    return args if isinstance(args, dict) else {'input': args}


def _stream_turn(ctx: TurnContext, stream: Any, usage: dict, box: dict) -> Iterator[dict]:
    """Iterate one streamed completion. Fills `box` with finish_reason/text/calls."""
    tools = _ToolAccumulator()
    text_parts: list[str] = []
    finish_reason = None
    for chunk in stream:
        if ctx.cancel.is_set():
            box.update(cancelled=True)
            return
        _add_usage(usage, _attr(chunk, 'usage'))
        choices = _attr(chunk, 'choices') or []
        if not choices:
            continue
        choice = choices[0]
        delta = _attr(choice, 'delta')
        reason = _attr(choice, 'finish_reason')
        if reason:
            finish_reason = reason
        if delta is None:
            continue
        reasoning = _attr(delta, 'reasoning_content')
        if reasoning:
            yield {'type': 'thinking', 'text': reasoning}
        text = _attr(delta, 'content')
        if text:
            text_parts.append(text)
            yield {'type': 'text_delta', 'text': text}
        for fragment in _attr(delta, 'tool_calls') or []:
            tools.add(fragment)
    box.update(finish_reason=finish_reason, text=''.join(text_parts), calls=tools.calls())


def _run_tool(ctx: TurnContext, call: dict) -> tuple[dict, dict, dict]:
    """Execute one accumulated tool call -> (tool_call ev, tool_result ev, tool message)."""
    call_id = call.get('id') or ''
    name = call.get('name') or ''
    args = _parse_args(call)
    call_event = {'type': 'tool_call', 'id': call_id, 'name': name, 'args': args}
    try:
        result = ctx.execute_tool(name, args) or {}
    except Exception as exc:
        _log.exception('execute_tool(%r) raised', name)
        result = {'ok': False, 'text': f'{type(exc).__name__}: {exc}', 'ms': 0}
    ok = bool(result.get('ok'))
    text = str(result.get('text') or '')
    result_event = {
        'type': 'tool_result',
        'id': call_id,
        'name': name,
        'ok': ok,
        'text': text,
        'ms': int(result.get('ms') or 0),
    }
    tool_message = {'role': 'tool', 'tool_call_id': call_id, 'content': text}
    return call_event, result_event, tool_message


def _assistant_message(box: dict) -> dict:
    return {
        'role': 'assistant',
        'content': box.get('text') or None,
        'tool_calls': [
            {
                'id': call.get('id') or '',
                'type': 'function',
                'function': {'name': call.get('name') or '', 'arguments': call.get('arguments') or '{}'},
            }
            for call in box.get('calls') or []
        ],
    }


# --------------------------------------------------------------------------- #
# public interface
# --------------------------------------------------------------------------- #


def probe(provider: str = 'openai') -> dict:
    """Readiness without touching the network: key plus a known endpoint."""
    key = _resolve_key(provider)
    if not key:
        envs = ' / '.join(QUIRKS.get(provider, {}).get('env', ())) or 'no env var known'
        return {'ok': False, 'detail': f'no API key for {provider} ({envs})'}
    url = _base_url(provider)
    if not url:
        return {'ok': False, 'detail': f'no base_url for {provider} in models_catalog.json'}
    return {'ok': True, 'detail': f'API key present (…{key[-4:]}) for {url}'}


def run(ctx: TurnContext) -> Iterator[dict]:
    """Run one turn against an OpenAI-compatible provider. Never raises."""
    try:
        yield from _run(ctx)
    except Exception as exc:  # pragma: no cover - last-resort net
        _log.exception('openai_compat.run failed')
        yield _error_event(f'{type(exc).__name__}: {exc}', 'backend')
        yield {'type': 'done', 'stop_reason': 'error'}


def _run(ctx: TurnContext) -> Iterator[dict]:
    usage = _zero_usage()
    model = ctx.model
    provider = getattr(ctx, 'provider', 'openai') or 'openai'
    try:
        import openai
        from openai import OpenAI
    except ImportError as exc:
        yield from _finish(provider, model, usage, 'error', _error_event(f'openai SDK missing: {exc}', 'backend'))
        return

    key = _resolve_key(provider)
    if not key:
        yield from _finish(
            provider, model, usage, 'error', _error_event(f'no API key configured for {provider}', 'auth')
        )
        return
    base_url = _base_url(provider)
    if not base_url:
        yield from _finish(
            provider, model, usage, 'error', _error_event(f'no base_url known for {provider}', 'backend')
        )
        return

    client = OpenAI(api_key=key, base_url=base_url, timeout=ctx.timeout_s, max_retries=2)
    base_request = _build_request(ctx, provider)
    messages = _convert_messages(ctx.system or '', ctx.messages)
    tool_calls_made = 0
    max_tool_calls = int(getattr(ctx, 'max_tool_calls', 0) or 0)

    while True:
        if ctx.cancel.is_set():
            yield from _finish(provider, model, usage, 'cancelled')
            return

        box: dict[str, Any] = {}
        try:
            stream = client.chat.completions.create(**dict(base_request, messages=messages))
            yield from _stream_turn(ctx, stream, usage, box)
        except Exception as exc:
            kind = _classify(openai, exc)
            _log.warning('%s API error (%s): %s', provider, kind, exc)
            yield from _finish(provider, model, usage, 'error', _error_event(f'{type(exc).__name__}: {exc}', kind))
            return

        if box.get('cancelled'):
            yield from _finish(provider, model, usage, 'cancelled')
            return

        calls = box.get('calls') or []
        if box.get('finish_reason') != 'tool_calls' and not calls:
            yield from _finish(provider, model, usage, 'end_turn')
            return

        if tool_calls_made >= max_tool_calls:
            yield from _finish(provider, model, usage, 'max_tool_calls')
            return

        messages = messages + [_assistant_message(box)]
        tool_messages = []
        for call in calls:
            if tool_calls_made >= max_tool_calls:
                break
            call_event, result_event, tool_message = _run_tool(ctx, call)
            yield call_event
            yield result_event
            tool_messages.append(tool_message)
            tool_calls_made += 1

        if len(tool_messages) < len(calls):
            # The budget ran out mid-batch: every declared tool_call must be
            # answered or the next request is invalid, so the turn stops here.
            yield from _finish(provider, model, usage, 'max_tool_calls')
            return

        messages = messages + tool_messages
