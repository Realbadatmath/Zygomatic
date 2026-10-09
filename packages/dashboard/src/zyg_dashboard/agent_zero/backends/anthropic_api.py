# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Agent Zero v2 backend for Anthropic's own Messages API.

Selected when the operator picks the `anthropic` provider in the model picker: the
same tool loop as the Claude Code subscription backend, but billed per token
against an API key instead of a login. Streams assistant text, runs every
`tool_use` block through `ctx.execute_tool`, stops at `ctx.max_tool_calls` and on
`ctx.cancel`, and always ends with exactly one `done` event preceded by a single
priced `usage` event. No exception is ever allowed to escape `run()`.

The `anthropic` SDK is imported lazily inside the functions so that importing this
module costs nothing and the rest of agent_zero stays stdlib-only.
"""

# A backend's whole job is to turn every failure into an event instead of an
# exception, so a blind `except Exception` is the contract here, not a smell.

from __future__ import annotations

import logging
import os
from collections.abc import Iterator
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover - typing only
    from ..contracts import TurnContext

_log = logging.getLogger(__name__)

PROVIDER = 'anthropic'

#: Env vars consulted when agent_zero.models cannot hand us a key.
_ENV_KEYS = ('ANTHROPIC_API_KEY', 'CLAUDE_API_KEY')

#: Anthropic's own cache multipliers against the base input price: a 1-hour cache
#: write costs 2x, a 5-minute write 1.25x, a cache read 0.1x. We cannot tell the
#: two write TTLs apart from `cache_creation_input_tokens` alone, so the cheaper
#: 5-minute multiplier is used (agent_zero writes the default ephemeral cache).
_CACHE_WRITE_MULT = 1.25
_CACHE_READ_MULT = 0.1


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


def _catalogue_entry(model: str) -> dict:
    """The models_catalog.json row for `model`, or {} when the catalogue has none."""
    models = _models_module()
    if models is None:
        return {}
    try:
        rows = models.seed_models(PROVIDER) or []
    except Exception:
        _log.warning('agent_zero.models.seed_models(%r) failed', PROVIDER, exc_info=True)
        return {}
    for row in rows:
        if isinstance(row, dict) and row.get('id') == model:
            return row
    return {}


def _resolve_key(provider: str = PROVIDER) -> str | None:
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
    for env in _ENV_KEYS:
        value = os.environ.get(env)
        if value and value.strip():
            return value.strip()
    return None


# --------------------------------------------------------------------------- #
# small shape helpers
# --------------------------------------------------------------------------- #


def _attr(obj: Any, name: str, default: Any = None) -> Any:
    """Read `name` off a dict or an object (the SDK gives objects, fakes give both)."""
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _block_to_dict(block: Any) -> dict:
    """An SDK content block (or a fake) as a plain JSON-safe dict."""
    if isinstance(block, dict):
        return dict(block)
    dump = getattr(block, 'model_dump', None)
    if callable(dump):
        try:
            dumped: Any = dump()
            return dict(dumped)
        except Exception:
            _log.warning('content block model_dump() failed', exc_info=True)
    out: dict[str, Any] = {}
    for name in ('type', 'text', 'id', 'name', 'input', 'thinking', 'signature'):
        value = getattr(block, name, None)
        if value is not None:
            out[name] = value
    return out


def _convert_messages(messages: list) -> list:
    """CONTRACT C messages -> Messages-API messages (the blocks map 1:1 bar images)."""
    out = []
    for msg in messages or []:
        content = _attr(msg, 'content')
        role = _attr(msg, 'role', 'user')
        if isinstance(content, str):
            out.append({'role': role, 'content': content})
            continue
        blocks = []
        for block in content or []:
            btype = _attr(block, 'type')
            if btype == 'image':
                blocks.append(
                    {
                        'type': 'image',
                        'source': {
                            'type': 'base64',
                            'media_type': _attr(block, 'media_type', 'image/png'),
                            'data': _attr(block, 'data', ''),
                        },
                    }
                )
            else:
                blocks.append(dict(block) if isinstance(block, dict) else _block_to_dict(block))
        out.append({'role': role, 'content': blocks})
    return out


def _convert_tools(tools: list) -> list:
    """CONTRACT C tools -> Messages-API tools (identical field names)."""
    out = []
    for tool in tools or []:
        out.append(
            {
                'name': _attr(tool, 'name'),
                'description': _attr(tool, 'description', '') or '',
                'input_schema': _attr(tool, 'input_schema') or {'type': 'object', 'properties': {}},
            }
        )
    return out


def _build_request(ctx: TurnContext) -> dict:
    """The static half of the Messages request (everything but `messages`)."""
    req: dict[str, Any] = {
        'model': ctx.model,
        'max_tokens': int(ctx.max_output_tokens),
        # The system prompt is the one stable prefix of a turn, so it carries the
        # cache breakpoint; every later turn of the session reads it back.
        'system': [{'type': 'text', 'text': ctx.system or '', 'cache_control': {'type': 'ephemeral'}}],
    }
    tools = _convert_tools(ctx.tools)
    if tools:
        req['tools'] = tools
        # Forced tool_choice (`any`/`tool`) is rejected by the 5.5-family models.
        req['tool_choice'] = {'type': 'auto'}
    thinking_tokens = int(getattr(ctx, 'thinking_tokens', 0) or 0)
    if thinking_tokens > 0:
        # Thinking on the 5-family models is adaptive and steered by effort, not by
        # a token budget; when the operator asked for none we omit the key entirely
        # (there is no 'disabled' type that these models accept).
        req['thinking'] = {'type': 'adaptive'}
        req['output_config'] = {'effort': 'low' if thinking_tokens < 4096 else 'medium'}
    return req


# --------------------------------------------------------------------------- #
# usage / pricing
# --------------------------------------------------------------------------- #


def _zero_usage() -> dict:
    return {'input_tokens': 0, 'output_tokens': 0, 'cache_read': 0, 'cache_write': 0}


def _add_usage(total: dict, usage: Any) -> None:
    """Accumulate one iteration's `message.usage` into `total`."""
    if usage is None:
        return
    pairs = (
        ('input_tokens', 'input_tokens'),
        ('output_tokens', 'output_tokens'),
        ('cache_read', 'cache_read_input_tokens'),
        ('cache_write', 'cache_creation_input_tokens'),
    )
    for ours, theirs in pairs:
        try:
            total[ours] += int(_attr(usage, theirs, 0) or 0)
        except (TypeError, ValueError):
            continue


def _price(model: str, usage: dict) -> tuple[float, bool]:
    """(cost_usd, priced) — the host's quota_meter first, the catalogue second."""
    meter = _quota_meter()
    if meter is not None and hasattr(meter, 'price_tokens'):
        try:
            cost = meter.price_tokens(
                model,
                usage['input_tokens'],
                usage['output_tokens'],
                usage['cache_write'],
                usage['cache_read'],
            )
        except Exception:
            _log.warning('quota_meter.price_tokens(%r) failed', model, exc_info=True)
            cost = None
        if cost is not None:
            return float(cost), True
    entry = _catalogue_entry(model)
    price_in, price_out = entry.get('price_in'), entry.get('price_out')
    if price_in is None and price_out is None:
        return 0.0, False
    billed_in = (
        usage['input_tokens'] + usage['cache_write'] * _CACHE_WRITE_MULT + usage['cache_read'] * _CACHE_READ_MULT
    )
    cost = (billed_in * float(price_in or 0.0) + usage['output_tokens'] * float(price_out or 0.0)) / 1e6
    return cost, True


def _usage_event(model: str, usage: dict) -> dict:
    cost, priced = _price(model, usage)
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


def _finish(model: str, usage: dict, stop_reason: str, error: dict | None = None) -> Iterator[dict]:
    """The tail of every turn: at most one usage, at most one error, exactly one done."""
    if any(usage.values()):
        yield _usage_event(model, usage)
    if error is not None:
        yield error
    yield {'type': 'done', 'stop_reason': stop_reason}


# --------------------------------------------------------------------------- #
# streaming
# --------------------------------------------------------------------------- #


def _events_from(event: Any) -> Iterator[dict]:
    """One SDK stream event -> zero or more CONTRACT C events.

    Only the SDK's *convenience* events are read. `MessageStream` also re-yields the
    raw `content_block_delta` events, so handling both would emit every token twice.
    """
    etype = _attr(event, 'type')
    if etype == 'text':
        text = _attr(event, 'text') or ''
        if text:
            yield {'type': 'text_delta', 'text': text}
    elif etype == 'thinking':
        text = _attr(event, 'thinking') or _attr(event, 'text') or ''
        if text:
            yield {'type': 'thinking', 'text': text}


def _run_tool(ctx: TurnContext, block: Any) -> tuple[dict, dict, dict]:
    """Execute one tool_use block -> (tool_call event, tool_result event, result block)."""
    call_id = _attr(block, 'id') or ''
    name = _attr(block, 'name') or ''
    args = _attr(block, 'input') or {}
    if not isinstance(args, dict):
        args = {'input': args}
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
    result_block = {
        'type': 'tool_result',
        'tool_use_id': call_id,
        'content': text,
        'is_error': not ok,
    }
    return call_event, result_event, result_block


def _error_event(message: str, kind: str) -> dict:
    return {'type': 'error', 'message': message, 'kind': kind}


def _classify(anthropic_mod: Any, exc: BaseException) -> str:
    """Map an SDK exception to a CONTRACT C error kind."""
    for attr, kind in (('AuthenticationError', 'auth'), ('PermissionDeniedError', 'auth'), ('RateLimitError', 'limit')):
        cls = getattr(anthropic_mod, attr, None)
        if isinstance(cls, type) and isinstance(exc, cls):
            return kind
    return 'backend'


# --------------------------------------------------------------------------- #
# public interface
# --------------------------------------------------------------------------- #


def probe() -> dict:
    """Readiness without touching the network: do we have a key at all?"""
    key = _resolve_key()
    if not key:
        return {'ok': False, 'detail': 'no Anthropic API key (ANTHROPIC_API_KEY)'}
    return {'ok': True, 'detail': f'API key present (…{key[-4:]})'}


def run(ctx: TurnContext) -> Iterator[dict]:
    """Run one turn against the Anthropic Messages API. Never raises."""
    try:
        yield from _run(ctx)
    except Exception as exc:  # pragma: no cover - last-resort net
        _log.exception('anthropic_api.run failed')
        yield _error_event(f'{type(exc).__name__}: {exc}', 'backend')
        yield {'type': 'done', 'stop_reason': 'error'}


def _run(ctx: TurnContext) -> Iterator[dict]:
    usage = _zero_usage()
    model = ctx.model
    try:
        import anthropic
    except ImportError as exc:
        yield from _finish(model, usage, 'error', _error_event(f'anthropic SDK missing: {exc}', 'backend'))
        return

    key = _resolve_key(getattr(ctx, 'provider', PROVIDER) or PROVIDER)
    if not key:
        yield from _finish(model, usage, 'error', _error_event('no Anthropic API key configured', 'auth'))
        return

    client = anthropic.Anthropic(api_key=key, timeout=ctx.timeout_s, max_retries=2)
    base_request = _build_request(ctx)
    messages = _convert_messages(ctx.messages)
    tool_calls_made = 0
    max_tool_calls = int(getattr(ctx, 'max_tool_calls', 0) or 0)

    while True:
        if ctx.cancel.is_set():
            yield from _finish(model, usage, 'cancelled')
            return

        request = dict(base_request, messages=messages)
        cancelled = False
        try:
            with client.messages.stream(**request) as stream:
                for event in stream:
                    if ctx.cancel.is_set():
                        cancelled = True
                        break
                    yield from _events_from(event)
                if cancelled:
                    yield from _finish(model, usage, 'cancelled')
                    return
                message = stream.get_final_message()
        except Exception as exc:
            kind = _classify(anthropic, exc)
            _log.warning('Anthropic API error (%s): %s', kind, exc)
            yield from _finish(model, usage, 'error', _error_event(f'{type(exc).__name__}: {exc}', kind))
            return

        _add_usage(usage, _attr(message, 'usage'))
        content = [_block_to_dict(b) for b in (_attr(message, 'content') or [])]
        messages = messages + [{'role': 'assistant', 'content': content}]
        stop_reason = _attr(message, 'stop_reason') or 'end_turn'

        if stop_reason == 'refusal':
            details = _attr(message, 'stop_details')
            suffix = f' ({details})' if details else ''
            yield from _finish(model, usage, 'error', _error_event(f'the model refused to continue{suffix}', 'backend'))
            return

        if stop_reason != 'tool_use':
            yield from _finish(model, usage, 'end_turn')
            return

        if tool_calls_made >= max_tool_calls:
            yield from _finish(model, usage, 'max_tool_calls')
            return

        requested = [b for b in content if b.get('type') == 'tool_use']
        if not requested:  # stop_reason says tool_use but no block carries one
            yield from _finish(model, usage, 'end_turn')
            return
        result_blocks = []
        for block in requested:
            if tool_calls_made >= max_tool_calls:
                break
            call_event, result_event, result_block = _run_tool(ctx, block)
            yield call_event
            yield result_event
            result_blocks.append(result_block)
            tool_calls_made += 1

        if len(result_blocks) < len(requested):
            # The budget ran out mid-batch: every tool_use block must be answered
            # or the next request is invalid, so the turn stops here.
            yield from _finish(model, usage, 'max_tool_calls')
            return

        messages = messages + [{'role': 'user', 'content': result_blocks}]
