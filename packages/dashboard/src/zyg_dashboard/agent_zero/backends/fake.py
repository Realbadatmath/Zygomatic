# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later
"""A deterministic backend that never leaves the process (CONTRACT C).

Every test in the Agent Zero v2 suite runs its turns through this module. It exists so
the runner, the prompt, the budget gate, the confirmation handshake and the metrics
ledger can be proven end to end without a GPU, an API key or a network: no model is
loaded, no token is spent, and the same input always produces the same events.

Two modes
---------
* **Scripted** -- ``ctx.extra['script']`` is a list of events to replay. Plain events
  (``text_delta``, ``thinking``, ``error`` ...) are yielded verbatim; a ``tool_call``
  entry is actually executed through ``ctx.execute_tool`` and answered with a real
  ``tool_result``; a ``{'type': 'sleep', 'seconds': n}`` entry waits (in short slices,
  watching ``ctx.cancel``) so a cancellation can be proven; a ``done`` entry ends the
  replay with its own ``stop_reason``.
* **Default** -- ``text_delta 'Hi'``, one ``zero_index(group='system')`` call when the
  context carries tools, then ``text_delta ' done'``.

Both modes obey the two rules every backend obeys: stop calling tools once
``ctx.max_tool_calls`` have been made, and stop entirely once ``ctx.cancel`` is set.
The stream always ends with exactly one ``usage`` event and one ``done`` event.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Iterator

from ..contracts import TurnContext, estimate_tokens

_log = logging.getLogger(__name__)

__all__ = ['probe', 'run']

#: Output tokens reported for a fake turn. A constant keeps the metrics tests exact.
FAKE_OUTPUT_TOKENS = 5

#: Granularity of a scripted ``sleep``: short enough that a cancel is noticed at once.
_SLEEP_SLICE_S = 0.02


def probe() -> dict:
    """Always reachable -- the fake backend is this process."""
    return {'ok': True, 'detail': 'fake backend (in process, deterministic)'}


def _default_script(ctx: TurnContext) -> list[dict]:
    """The scripted turn used when the caller supplied none."""
    script: list[dict] = [{'type': 'text_delta', 'text': 'Hi'}]
    if ctx.tools:
        script.append({'type': 'tool_call', 'name': 'zero_index', 'args': {'group': 'system'}})
    script.append({'type': 'text_delta', 'text': ' done'})
    return script


def _input_tokens(ctx: TurnContext) -> int:
    """Estimated prompt size with the one estimator of CONTRACT C."""
    total = estimate_tokens(ctx.system or '')
    for msg in ctx.messages or []:
        content = msg.get('content')
        if isinstance(content, str):
            total += estimate_tokens(content)
            continue
        for block in content or []:
            if isinstance(block, dict):
                total += estimate_tokens(str(block.get('text') or block.get('data') or ''))
            else:
                total += estimate_tokens(str(block))
    for tool in ctx.tools or []:
        total += estimate_tokens(str(tool.get('name') or '') + str(tool.get('description') or ''))
    return total


def _usage_event(ctx: TurnContext) -> dict:
    return {
        'type': 'usage',
        'input_tokens': _input_tokens(ctx),
        'output_tokens': FAKE_OUTPUT_TOKENS,
        'cache_read': 0,
        'cache_write': 0,
        'cost_usd': 0.0,
        'model': ctx.model,
    }


def _sleep(ctx: TurnContext, seconds: float) -> bool:
    """Wait ``seconds``, watching the cancel flag. False when the turn was cancelled."""
    deadline = time.time() + max(0.0, float(seconds or 0.0))
    while time.time() < deadline:
        if ctx.cancel.is_set():
            return False
        time.sleep(_SLEEP_SLICE_S)
    return not ctx.cancel.is_set()


def _execute(ctx: TurnContext, call: dict) -> dict:
    """Run one tool call; a tool that raises becomes a failed result, never a crash."""
    try:
        result = ctx.execute_tool(call['name'], call['args'])
    except Exception as exc:  # noqa: BLE001 - a broken tool is a result, not a crash
        _log.warning('fake: tool %s raised (%s)', call['name'], exc)
        return {'ok': False, 'text': f'tool {call["name"]} failed: {exc}', 'ms': 0}
    return result if isinstance(result, dict) else {'ok': False, 'text': 'tool returned no result', 'ms': 0}


def _tool_result_event(call: dict, result: dict) -> dict:
    return {
        'type': 'tool_result',
        'id': call['id'],
        'name': call['name'],
        'ok': bool(result.get('ok')),
        'text': str(result.get('text') or ''),
        'ms': int(result.get('ms') or 0),
    }


def run(ctx: TurnContext) -> Iterator[dict]:
    """Replay the scripted (or default) turn as CONTRACT C events."""
    script = ctx.extra.get('script') if isinstance(ctx.extra, dict) else None
    if not isinstance(script, list):
        script = _default_script(ctx)

    stop_reason = 'end_turn'
    calls_made = 0
    usage_sent = False

    for item in script:
        if not isinstance(item, dict):
            continue
        if ctx.cancel.is_set():
            stop_reason = 'cancelled'
            break
        kind = item.get('type')

        if kind == 'sleep':
            if not _sleep(ctx, item.get('seconds') or 0):
                stop_reason = 'cancelled'
                break
            continue

        if kind == 'done':
            stop_reason = str(item.get('stop_reason') or 'end_turn')
            break

        if kind == 'usage':
            usage_sent = True
            yield dict(item)
            continue

        if kind != 'tool_call':
            yield dict(item)
            continue

        if calls_made >= ctx.max_tool_calls:
            stop_reason = 'max_tool_calls'
            break
        call = {
            'type': 'tool_call',
            'id': str(item.get('id') or f'fake_tc_{calls_made}'),
            'name': str(item.get('name') or ''),
            'args': dict(item.get('args') or {}),
        }
        yield call
        result = _execute(ctx, call)
        calls_made += 1
        yield _tool_result_event(call, result)
        if result.get('needs_confirmation'):
            stop_reason = 'needs_confirmation'
            break

    if ctx.cancel.is_set() and stop_reason == 'end_turn':
        stop_reason = 'cancelled'
    if not usage_sent:
        yield _usage_event(ctx)
    yield {'type': 'done', 'stop_reason': stop_reason}
