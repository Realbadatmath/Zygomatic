# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Shared data contracts for Agent Zero v2 (CONTRACT C).

This module is the single source of truth every other part of the package agrees on:
the turn context a backend is handed, the event protocol a backend streams back, the
provider ids, and the one token estimator. It must stay dependency-free (stdlib only)
so that any module -- host seam, routes, backends, budget -- can import it.

Message shape
-------------
``TurnContext.messages`` is a list of ``{'role': 'user'|'assistant', 'content': ...}``
where ``content`` is either a plain string or a list of blocks:

* ``{'type': 'text', 'text': str}``
* ``{'type': 'image', 'media_type': str, 'data': str}`` -- ``data`` is base64
* ``{'type': 'tool_use', 'id': str, 'name': str, 'input': dict}``
* ``{'type': 'tool_result', 'tool_use_id': str, 'content': str, 'is_error': bool}``

``TurnContext.tools`` is a list of ``{'name', 'description', 'input_schema'}`` where
``input_schema`` is a JSON-schema object.

``TurnContext.execute_tool(name, args)`` returns::

    {'ok': bool, 'text': str, 'ms': int,
     'risk': 'read'|'act'|'danger',
     'needs_confirmation': bool, 'confirm_id': str|None}

Event protocol
--------------
A backend is a generator of plain dicts, each carrying a ``'type'``:

* ``text_delta``  ``{'type': 'text_delta', 'text': str}`` -- assistant prose, incremental
* ``thinking``    ``{'type': 'thinking', 'text': str}`` -- extended-thinking prose
* ``tool_call``   ``{'type': 'tool_call', 'id': str, 'name': str, 'args': dict}``
* ``tool_result`` ``{'type': 'tool_result', 'id': str, 'name': str, 'ok': bool,
  'text': str, 'ms': int}``
* ``usage``       ``{'type': 'usage', 'input_tokens': int, 'output_tokens': int,
  'cache_read': int, 'cache_write': int, 'cost_usd': float, 'model': str}``
* ``done``        ``{'type': 'done', 'stop_reason': 'end_turn'|'max_tool_calls'|
  'needs_confirmation'|'cancelled'|'error'}``
* ``error``       ``{'type': 'error', 'message': str,
  'kind': 'limit'|'backend'|'budget'|'auth'}``

Backend module interface
------------------------
Every ``agent_zero/backends/<name>.py`` exports exactly two callables:

* ``run(ctx: TurnContext) -> Iterator[dict]`` -- yields the events above and ends with
  exactly one ``done`` event (an ``error`` event is followed by ``done`` with
  ``stop_reason='error'``). It executes tool calls through ``ctx.execute_tool``, stops
  issuing tool calls once it has made ``ctx.max_tool_calls`` of them (then streams the
  model's final text and yields ``done`` with ``stop_reason='max_tool_calls'``), and
  stops as soon as ``ctx.cancel.is_set()`` (``stop_reason='cancelled'``).
* ``probe() -> dict`` -- ``{'ok': bool, 'detail': str}``, a cheap reachability check
  that must not spend tokens.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

#: Every event type a backend may yield. Consumers must ignore unknown types.
EVENT_TYPES = (
    'text_delta',
    'thinking',
    'tool_call',
    'tool_result',
    'usage',
    'done',
    'error',
)

#: Every provider Agent Zero can talk to. ``subscription`` is the Claude Code login.
PROVIDERS = (
    'subscription',
    'anthropic',
    'openai',
    'google',
    'openrouter',
    'groq',
    'deepseek',
    'mistral',
    'xai',
    'together',
    'ollama',
)

#: provider id -> module name under ``agent_zero.backends``.
BACKEND_FOR = {
    'subscription': 'subscription',
    'anthropic': 'anthropic_api',
    'openai': 'openai_compat',
    'google': 'openai_compat',
    'openrouter': 'openai_compat',
    'groq': 'openai_compat',
    'deepseek': 'openai_compat',
    'mistral': 'openai_compat',
    'xai': 'openai_compat',
    'together': 'openai_compat',
    'ollama': 'ollama',
}


def _noop_execute_tool(name: str, args: dict) -> dict:
    """Default ``execute_tool``: refuses every call, so a tool-less turn is safe."""
    return {
        'ok': False,
        'text': f'no tool runner wired for {name!r}',
        'ms': 0,
        'risk': 'read',
        'needs_confirmation': False,
        'confirm_id': None,
    }


@dataclass
class TurnContext:
    """Everything a backend needs to run one turn of the conversation.

    Defaults are chosen so that ``TurnContext()`` is a valid, inert context: no tools,
    no messages, the subscription provider with the default model, and a fresh cancel
    event that is never set.
    """

    turn_id: str = ''
    session_id: str = ''
    provider: str = 'subscription'
    model: str = 'claude-opus-5'
    system: str = ''
    messages: list[dict] = field(default_factory=list)
    tools: list[dict] = field(default_factory=list)
    execute_tool: Callable[[str, dict], dict] = _noop_execute_tool
    max_output_tokens: int = 8192
    max_tool_calls: int = 24
    thinking_tokens: int = 0
    timeout_s: int = 600
    cookie: str = ''
    csrf: str = ''
    cancel: threading.Event = field(default_factory=threading.Event)
    extra: dict[str, Any] = field(default_factory=dict)


def estimate_tokens(text: str) -> int:
    """The one token estimator the whole package uses: ~4 characters per token."""
    if not text:
        return 1
    return max(1, len(text) // 4)
