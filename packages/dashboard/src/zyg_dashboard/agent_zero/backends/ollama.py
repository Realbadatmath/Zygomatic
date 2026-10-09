# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Agent Zero backend for a LOCAL model served by Ollama (CONTRACT C).

When the operator picks a local model, the turn runs here: a streaming
``POST /api/chat`` against the Ollama system service on this box (0.17.7, base URL
from ``_host.ollama_url()``), with the same event protocol every other backend speaks,
so nothing above the backend seam has to know the turn never left the machine.

Two tool strategies, chosen per model
-------------------------------------
``POST /api/show`` reports a model's ``capabilities`` list (cached per model for the
life of the process). A model that advertises ``'tools'`` -- gpt-oss:20b is
``['completion', 'tools', 'thinking']``, qwen3.5:9b is ``['completion', 'vision',
'tools', 'thinking']`` -- gets real OpenAI-style function specs in the request and the
native tool loop. A model without it (moondream is ``['completion', 'vision']``) gets
the JSON fallback: the tool catalogue plus a one-line protocol is appended to the
system prompt, and a reply that is -- or ends with -- ``{"tool": name, "args": {...}}``
is executed and fed back as a plain user message. Both loops respect
``ctx.max_tool_calls`` and ``ctx.cancel``.

Notes on the local server
-------------------------
* ``OLLAMA_MAX_LOADED_MODELS=1`` on this box: loading a model EVICTS the previously
  loaded one, so the first turn after a model switch pays the full load time (and a
  concurrent turn on another local model will fight over the GPU). ``keep_alive`` is
  10 minutes, which keeps a conversation warm without pinning VRAM forever.
* ``/api/show`` is POST-only (a GET returns ``405 method not allowed``), unlike
  ``/api/version`` which is the GET used by :func:`probe`.
* Thinking models route their whole answer into ``message.thinking`` and leave
  ``message.content`` empty often enough (qwen3.5 does, see
  ``llm_audit.ollama_generate``) that the thinking text is used as the answer when the
  content is empty at ``done``.
* A local turn is free: the single ``usage`` event carries ``cost_usd`` 0.0 and
  ``'local': True`` alongside Ollama's own ``prompt_eval_count`` / ``eval_count``.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Iterator

import requests

from .. import _host
from ..contracts import TurnContext

_log = logging.getLogger(__name__)

#: Connect timeout; the read timeout is the turn's own ``ctx.timeout_s``.
_CONNECT_TIMEOUT_S = 10
#: How long Ollama keeps the model resident after the turn.
_KEEP_ALIVE = '10m'
_NUM_CTX = 32768
_TEMPERATURE = 0.2
_AUDIT_STAGE = 'agent_zero_v2'

#: The tool protocol handed to models that cannot do native tool calling.
_FALLBACK_PROTOCOL = (
    'To use a tool reply with ONLY a JSON object {"tool": name, "args": {...}} on its '
    'own line; otherwise answer normally.'
)

#: model -> capabilities list, from ``/api/show``. One lookup per model per process.
_capabilities: dict[str, list] = {}


class _OllamaError(RuntimeError):
    """Any error the Ollama server itself reported (HTTP status or error chunk)."""


class _ModelMissing(_OllamaError):
    """The requested model is not pulled on this box."""

    def __init__(self, model: str) -> None:
        super().__init__(f'model {model} is not installed')
        self.model = model


# --------------------------------------------------------------------------- probing


def _url() -> str:
    return _host.ollama_url()


def probe() -> dict:
    """Cheap reachability check: ``GET /api/version``."""
    url = _url()
    try:
        rsp = requests.get(f'{url}/api/version', timeout=_CONNECT_TIMEOUT_S)
        rsp.raise_for_status()
        version = (rsp.json() or {}).get('version') or '?'
    except Exception as exc:  # noqa: BLE001 - a probe never raises, it reports
        return {'ok': False, 'detail': f'offline: {exc}'}
    return {'ok': True, 'detail': f'ollama {version} at {url}'}


def capabilities(model: str, url: str | None = None) -> list:
    """The model's ``capabilities`` list from ``POST /api/show``, cached per model."""
    if model in _capabilities:
        return _capabilities[model]
    base = url or _url()
    rsp = requests.post(f'{base}/api/show', json={'model': model}, timeout=_CONNECT_TIMEOUT_S)
    if rsp.status_code == 404:
        raise _ModelMissing(model)
    if rsp.status_code >= 400:
        raise _OllamaError(f'/api/show returned HTTP {rsp.status_code}: {rsp.text[:200]}')
    caps = (rsp.json() or {}).get('capabilities') or []
    caps = [str(cap) for cap in caps]
    _capabilities[model] = caps
    return caps


def _supports_tools(model: str, url: str) -> bool:
    return 'tools' in capabilities(model, url)


# ------------------------------------------------------------------ request building


def _tool_specs(tools: list) -> list:
    """CONTRACT C tools -> the OpenAI-style function specs Ollama accepts."""
    specs = []
    for tool in tools or []:
        specs.append(
            {
                'type': 'function',
                'function': {
                    'name': tool.get('name') or '',
                    'description': tool.get('description') or '',
                    'parameters': tool.get('input_schema') or {'type': 'object', 'properties': {}},
                },
            }
        )
    return specs


def _to_ollama_messages(messages: list) -> list:
    """CONTRACT C messages -> Ollama's shape.

    Text blocks are joined, image blocks become the message's ``images`` base64 list,
    and a replayed tool exchange becomes an assistant message carrying ``tool_calls``
    plus one ``{'role': 'tool'}`` message per result.
    """
    out: list[dict] = []
    names: dict[str, str] = {}
    for msg in messages or []:
        role = str(msg.get('role') or 'user')
        content = msg.get('content')
        if isinstance(content, str):
            out.append({'role': role, 'content': content})
            continue
        texts: list[str] = []
        images: list[str] = []
        calls: list[dict] = []
        results: list[dict] = []
        for block in content or []:
            if isinstance(block, str):
                texts.append(block)
                continue
            if not isinstance(block, dict):
                continue
            kind = block.get('type')
            if kind == 'text':
                texts.append(str(block.get('text') or ''))
            elif kind == 'image':
                images.append(str(block.get('data') or ''))
            elif kind == 'tool_use':
                names[str(block.get('id') or '')] = str(block.get('name') or '')
                calls.append(
                    {
                        'function': {
                            'name': str(block.get('name') or ''),
                            'arguments': block.get('input') or {},
                        }
                    }
                )
            elif kind == 'tool_result':
                results.append(
                    {
                        'role': 'tool',
                        'content': _result_text(block.get('content')),
                        'tool_name': names.get(str(block.get('tool_use_id') or ''), ''),
                    }
                )
        if texts or images or calls or not results:
            entry: dict = {'role': role, 'content': '\n'.join(t for t in texts if t)}
            if images:
                entry['images'] = images
            if calls:
                entry['tool_calls'] = calls
            out.append(entry)
        out.extend(results)
    return out


def _result_text(content) -> str:
    """Flatten a ``tool_result`` block's content (str or list of text blocks)."""
    if isinstance(content, str):
        return content
    parts = []
    for block in content or []:
        if isinstance(block, str):
            parts.append(block)
        elif isinstance(block, dict):
            parts.append(str(block.get('text') or ''))
    return '\n'.join(p for p in parts if p)


def _payload(ctx: TurnContext, messages: list, system: str, specs: list | None) -> dict:
    body: dict = {
        'model': ctx.model,
        'messages': ([{'role': 'system', 'content': system}] if system else []) + messages,
        'stream': True,
        'think': bool(ctx.thinking_tokens and ctx.thinking_tokens > 0),
        'keep_alive': _KEEP_ALIVE,
        'options': {
            'num_ctx': _NUM_CTX,
            'num_predict': int(ctx.max_output_tokens or 0) or None,
            'temperature': _TEMPERATURE,
        },
    }
    if body['options']['num_predict'] is None:
        del body['options']['num_predict']
    if specs:
        body['tools'] = specs
    return body


# ----------------------------------------------------------------------- one exchange


def _stream_once(ctx: TurnContext, url: str, body: dict, out: dict, emit_text: bool = True) -> Iterator[dict]:
    """POST one ``/api/chat`` request, yield its events, and fill ``out``.

    ``out`` collects ``content``, ``thinking``, ``tool_calls`` and this exchange's
    ``prompt_eval_count`` / ``eval_count`` / ``total_duration``. ``emit_text`` is False
    on the JSON-fallback path, where the reply has to be buffered: it cannot be streamed
    to the operator before we know whether it is prose or a tool call.
    """
    started = time.time()
    texts: list[str] = []
    thinking: list[str] = []
    calls: list[dict] = []
    out.update({'content': '', 'thinking': '', 'tool_calls': calls, 'input': 0, 'output': 0, 'duration_ns': 0})
    rsp = requests.post(
        f'{url}/api/chat',
        json=body,
        stream=True,
        timeout=(_CONNECT_TIMEOUT_S, ctx.timeout_s),
    )
    try:
        status = getattr(rsp, 'status_code', 200)
        if status == 404:
            raise _ModelMissing(str(body.get('model') or ''))
        if status >= 400:
            raise _OllamaError(f'/api/chat returned HTTP {status}: {rsp.text[:200]}')
        for raw in rsp.iter_lines():
            if not raw:
                continue
            line = raw.decode('utf-8', 'replace') if isinstance(raw, bytes) else str(raw)
            try:
                chunk = json.loads(line)
            except ValueError:
                _log.debug('ollama: unparsable stream line %r', line[:200])
                continue
            if chunk.get('error'):
                raise _OllamaError(str(chunk['error']))
            message = chunk.get('message') or {}
            delta = str(message.get('content') or '')
            if delta:
                texts.append(delta)
                if emit_text:
                    yield {'type': 'text_delta', 'text': delta}
            thought = str(message.get('thinking') or '')
            if thought:
                thinking.append(thought)
                yield {'type': 'thinking', 'text': thought}
            for index, call in enumerate(message.get('tool_calls') or []):
                calls.append(_tool_call_event(call, len(calls) + index))
            if chunk.get('done'):
                out['input'] = int(chunk.get('prompt_eval_count') or 0)
                out['output'] = int(chunk.get('eval_count') or 0)
                out['duration_ns'] = int(chunk.get('total_duration') or 0)
                out['done_reason'] = chunk.get('done_reason')
            if ctx.cancel.is_set():
                break
    finally:
        rsp.close()
        out['content'] = ''.join(texts)
        out['thinking'] = ''.join(thinking)
        _audit(body, out, time.time() - started)


def _tool_call_event(call: dict, index: int) -> dict:
    """One Ollama ``tool_calls`` entry -> a CONTRACT C ``tool_call`` event.

    Ollama sends tool calls complete (not token by token) and gives them no id, so the
    id is synthesised; ``arguments`` is a dict but older builds send a JSON string.
    """
    function = (call or {}).get('function') or {}
    args = function.get('arguments')
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except ValueError:
            args = {}
    return {
        'type': 'tool_call',
        'id': f'ollama_tc_{index}',
        'name': str(function.get('name') or ''),
        'args': args if isinstance(args, dict) else {},
    }


def _audit(body: dict, out: dict, elapsed_s: float) -> None:
    """Record the exchange through the host's llm_audit. Never raises."""
    audit = _host.llm_audit()
    if audit is None:
        return
    try:
        prompt = '\n\n'.join(str(m.get('content') or '') for m in body.get('messages') or [])
        extra = {}
        if out.get('thinking'):
            extra['thinking_tail'] = out['thinking'][-2000:]
            extra['thinking_chars'] = len(out['thinking'])
        if out.get('tool_calls'):
            extra['tool_calls'] = [(call.get('name'), call.get('args')) for call in out['tool_calls']][:12]
        if out.get('done_reason'):
            extra['done_reason'] = out['done_reason']
        audit.record(
            source='ollama',
            direction='exchange',
            llm=str(body.get('model') or ''),
            stage=_AUDIT_STAGE,
            pipeline_type='agent_zero',
            prompt=prompt,
            response=out.get('content') or out.get('thinking') or '',
            prompt_eval_count=out.get('input'),
            eval_count=out.get('output'),
            elapsed_s=round(elapsed_s, 2),
            **extra,
        )
    except Exception as exc:  # noqa: BLE001 - auditing must never break a turn
        _log.warning('ollama: audit record failed (%s)', exc)


def _add(totals: dict, out: dict) -> None:
    totals['input'] += int(out.get('input') or 0)
    totals['output'] += int(out.get('output') or 0)
    totals['duration_ns'] += int(out.get('duration_ns') or 0)


def _usage_event(model: str, totals: dict) -> dict:
    return {
        'type': 'usage',
        'input_tokens': totals['input'],
        'output_tokens': totals['output'],
        'cache_read': 0,
        'cache_write': 0,
        'cost_usd': 0.0,
        'model': model,
        'local': True,
        'total_duration': totals['duration_ns'],
    }


def _answer(out: dict) -> str:
    """The assistant's answer: its content, or its thinking when content is empty."""
    return out.get('content') or out.get('thinking') or ''


# ------------------------------------------------------------------ the native tool loop


def _run_native(ctx: TurnContext, url: str, totals: dict) -> Iterator[dict]:
    """Tool loop for a model that advertises the ``tools`` capability."""
    messages = _to_ollama_messages(ctx.messages)
    specs = _tool_specs(ctx.tools)
    calls_made = 0
    while True:
        if ctx.cancel.is_set():
            yield from _finish(ctx.model, totals, 'cancelled')
            return
        capped = bool(specs) and calls_made >= ctx.max_tool_calls
        out: dict = {}
        yield from _stream_once(ctx, url, _payload(ctx, messages, ctx.system, None if capped else specs), out)
        _add(totals, out)
        if not out['content'] and out['thinking']:
            # A thinking model that never reached its answer: the reasoning IS the answer.
            yield {'type': 'text_delta', 'text': out['thinking']}
        calls = list(out['tool_calls'])
        if ctx.cancel.is_set():
            yield from _finish(ctx.model, totals, 'cancelled')
            return
        if not calls or capped:
            yield from _finish(ctx.model, totals, 'max_tool_calls' if capped else 'end_turn')
            return
        messages.append({'role': 'assistant', 'content': _answer(out), 'tool_calls': _as_tool_calls(calls)})
        for call in calls:
            if calls_made >= ctx.max_tool_calls:
                break
            if ctx.cancel.is_set():
                yield from _finish(ctx.model, totals, 'cancelled')
                return
            yield call
            result = _execute(ctx, call)
            calls_made += 1
            yield _tool_result_event(call, result)
            messages.append({'role': 'tool', 'content': str(result.get('text') or ''), 'tool_name': call['name']})
            if result.get('needs_confirmation'):
                yield from _finish(ctx.model, totals, 'needs_confirmation')
                return


def _as_tool_calls(calls: list) -> list:
    """``tool_call`` events -> the assistant message's ``tool_calls`` list."""
    return [{'function': {'name': call['name'], 'arguments': call['args']}} for call in calls]


def _execute(ctx: TurnContext, call: dict) -> dict:
    try:
        result = ctx.execute_tool(call['name'], call['args'])
    except Exception as exc:  # noqa: BLE001 - a broken tool is a tool result, not a crash
        _log.warning('ollama: tool %s raised (%s)', call['name'], exc)
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


def _finish(model: str, totals: dict, stop_reason: str) -> Iterator[dict]:
    """The tail of every turn: exactly one usage event, then exactly one done."""
    yield _usage_event(model, totals)
    yield {'type': 'done', 'stop_reason': stop_reason}


# -------------------------------------------------------------------- the JSON fallback


def _fallback_system(ctx: TurnContext) -> str:
    """The system prompt plus the tool catalogue and the JSON tool protocol."""
    parts = [ctx.system] if ctx.system else []
    if ctx.tools:
        catalogue = '\n'.join(f'- {tool.get("name")}: {tool.get("description") or ""}'.rstrip() for tool in ctx.tools)
        parts.append(f'Tools available to you:\n{catalogue}')
    parts.append(_FALLBACK_PROTOCOL)
    return '\n\n'.join(parts)


def _parse_json_tool_call(text: str) -> tuple[dict | None, str]:
    """Find a ``{"tool": ..., "args": {...}}`` object in a reply.

    Returns ``(call, prose)`` where ``call`` is ``{'name', 'args'}`` (or None when the
    reply is plain prose) and ``prose`` is whatever text preceded the object.
    """
    body = (text or '').strip()
    if body.startswith('```'):
        body = body.split('\n', 1)[1] if '\n' in body else ''
        body = body.rsplit('```', 1)[0].strip()
    starts = [0]
    last_line = body.rfind('\n')
    if last_line >= 0:
        starts.append(last_line + 1)
    brace = body.rfind('{')
    if brace > 0:
        starts.append(brace)
    for start in starts:
        candidate = body[start:].strip()
        if not candidate.startswith('{'):
            continue
        try:
            obj = json.loads(candidate)
        except ValueError:
            continue
        if isinstance(obj, dict) and isinstance(obj.get('tool'), str):
            args = obj.get('args')
            return {'name': obj['tool'], 'args': args if isinstance(args, dict) else {}}, body[:start].strip()
    return None, body


def _run_json_fallback(ctx: TurnContext, url: str, totals: dict) -> Iterator[dict]:
    """Tool loop for a model WITHOUT the ``tools`` capability (prompt protocol)."""
    messages = _to_ollama_messages(ctx.messages)
    system = _fallback_system(ctx)
    calls_made = 0
    while True:
        if ctx.cancel.is_set():
            yield from _finish(ctx.model, totals, 'cancelled')
            return
        out: dict = {}
        yield from _stream_once(ctx, url, _payload(ctx, messages, system, None), out, emit_text=False)
        _add(totals, out)
        reply = _answer(out)
        if ctx.cancel.is_set():
            yield from _finish(ctx.model, totals, 'cancelled')
            return
        parsed, prose = _parse_json_tool_call(reply)
        if parsed is None:
            if reply:
                yield {'type': 'text_delta', 'text': reply}
            yield from _finish(ctx.model, totals, 'end_turn')
            return
        if calls_made >= ctx.max_tool_calls:
            yield from _finish(ctx.model, totals, 'max_tool_calls')
            return
        if prose:
            yield {'type': 'text_delta', 'text': prose}
        call = {'type': 'tool_call', 'id': f'ollama_tc_{calls_made}', 'name': parsed['name'], 'args': parsed['args']}
        yield call
        result = _execute(ctx, call)
        calls_made += 1
        yield _tool_result_event(call, result)
        messages.append({'role': 'assistant', 'content': reply})
        messages.append({'role': 'user', 'content': f'[tool result for {call["name"]}]: {result.get("text") or ""}'})
        if result.get('needs_confirmation'):
            yield from _finish(ctx.model, totals, 'needs_confirmation')
            return


# ------------------------------------------------------------------------------- entry


def _describe_failure(exc: BaseException, model: str, url: str) -> tuple[str, str]:
    """Turn a transport/server failure into an ``error`` event's message and kind."""
    if isinstance(exc, _ModelMissing) or 'not found' in str(exc).lower():
        return (f'model {model} is not installed — open Select Model to install it', 'backend')
    if isinstance(exc, requests.exceptions.ConnectionError):
        return (f'Ollama is not running on {url}', 'backend')
    if isinstance(exc, requests.exceptions.Timeout):
        return (f'Ollama timed out on {model} ({url})', 'backend')
    return (f'ollama: {exc}', 'backend')


def run(ctx: TurnContext) -> Iterator[dict]:
    """Run one turn against Ollama, yielding CONTRACT C events."""
    url = _url()
    totals = {'input': 0, 'output': 0, 'duration_ns': 0}
    try:
        native = _supports_tools(ctx.model, url) if ctx.tools else True
        yield from (_run_native if native else _run_json_fallback)(ctx, url, totals)
    except Exception as exc:  # noqa: BLE001 - every failure is one error + one done
        message, kind = _describe_failure(exc, ctx.model, url)
        _log.warning('ollama: turn %s failed (%s)', ctx.turn_id, exc)
        if totals['input'] or totals['output']:
            yield _usage_event(ctx.model, totals)
        yield {'type': 'error', 'message': message, 'kind': kind}
        yield {'type': 'done', 'stop_reason': 'error'}
