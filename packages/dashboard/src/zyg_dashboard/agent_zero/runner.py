# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later
"""One turn, end to end: the engine between the HTTP layer and the backends.

:func:`start_turn` does everything that must happen *before* a token is spent -- load
the session, resolve the model, append the user message, compact the history if it has
grown too big, assemble the prompt and ask :mod:`agent_zero.budget` whether the turn may
run at all -- and then hands the work to a daemon thread. The HTTP request returns a
``turn_id`` immediately; the stream is read afterwards with :func:`events_since` or
:func:`wait_events` (the SSE route blocks on the latter).

A turn lives in :data:`TURNS` as a plain dict with its own growing event buffer. Every
event carries a monotonic ``seq``, so a reconnecting browser asks for everything after
the last sequence number it saw and loses nothing.

Three behaviours are worth knowing about:

* **Confirmations are a handshake, not a flag.** A danger tool refuses and answers
  ``needs_confirmation``; the backend sees the refusal text and asks the user. The turn
  ends with ``stop_reason='needs_confirmation'`` and a ``confirm`` event. The user's yes
  arrives at :func:`confirm`, which fires the stored call and starts a *new* turn whose
  first user message carries the result. The model never confirms its own danger call.
* **Cancellation is cooperative.** :func:`cancel_turn` sets the context's event; every
  backend checks it between chunks and between tool calls.
* **The turn is always booked.** Whatever the outcome -- finished, cancelled, refused by
  the budget, crashed -- the assistant message is appended to the session, the usage is
  booked and one row goes into the metrics ledger. A turn that vanishes without a trace
  is a turn nobody can bill, debug or trust.
"""

from __future__ import annotations

import logging
import threading
import time
import uuid

from . import (
    _host,
    backends,
    budget,
    memory,
    metrics,
    models,
    prompt,
    toolmap,
    toolmap_exec,
)
from .contracts import PROVIDERS, TurnContext

_log = logging.getLogger(__name__)

__all__ = [
    'TURNS',
    'BudgetBlocked',
    'cancel_turn',
    'confirm',
    'events_since',
    'get_turn',
    'run_turn',
    'start_turn',
    'wait_events',
]

#: turn_id -> Turn. Turns are kept after they finish so a late poll still finds them.
TURNS: dict[str, dict] = {}

#: Guards :data:`TURNS` and every turn's event buffer; also the SSE wake-up signal.
_LOCK = threading.RLock()
_COND = threading.Condition(_LOCK)

#: Finished turns kept in memory before the oldest are dropped.
MAX_TURNS = 200

#: The compaction turn's system prompt. No tools, one job, a hard output ceiling.
SUMMARY_SYSTEM = (
    'Summarise this conversation for your own future reference in at most 400 words. '
    'Keep: facts established, decisions taken, open items, and the user preferences you '
    'learned. Drop pleasantries. Write plain prose, no headings.'
)
SUMMARY_MAX_TOKENS = 600

#: How much of a confirmed tool result is quoted back into the continuation message.
CONFIRM_RESULT_CHARS = 2000


class BudgetBlocked(Exception):
    """A ceiling refused this turn. ``reason`` is shown to the user verbatim."""

    def __init__(self, reason: str, state: dict | None = None) -> None:
        super().__init__(reason)
        self.reason = str(reason)
        self.state = state or {}


class _AuthError(RuntimeError):
    """The selected provider has no usable credential."""


# ── the turn buffer ──────────────────────────────────────────────────────────


def _append(turn: dict, event: dict) -> dict:
    """Add one event to a turn's buffer and wake everybody waiting on it."""
    with _COND:
        turn['seq'] += 1
        stamped = dict(event, seq=turn['seq'])
        turn['events'].append(stamped)
        _COND.notify_all()
    return stamped


def _finish(turn: dict) -> None:
    with _COND:
        turn['done'] = True
        _COND.notify_all()


def _reap() -> None:
    """Drop the oldest finished turns once the table grows past :data:`MAX_TURNS`."""
    if len(TURNS) <= MAX_TURNS:
        return
    finished = sorted((t for t in TURNS.values() if t['done']), key=lambda t: t['started'])
    for turn in finished[: len(TURNS) - MAX_TURNS]:
        TURNS.pop(turn['id'], None)


def get_turn(turn_id: str) -> dict | None:
    """A snapshot of one turn's state, or ``None`` when the id is unknown."""
    with _COND:
        turn = TURNS.get(str(turn_id or ''))
        if turn is None:
            return None
        return {
            'id': turn['id'],
            'done': bool(turn['done']),
            'seq': int(turn['seq']),
            'stop_reason': turn.get('stop_reason'),
            'pending_confirm': turn.get('pending_confirm'),
        }


def events_since(turn_id: str, seq: int = 0) -> list[dict]:
    """Every event of a turn after sequence number ``seq``."""
    with _COND:
        turn = TURNS.get(str(turn_id or ''))
        if turn is None:
            return []
        return [event for event in turn['events'] if event['seq'] > int(seq or 0)]


def wait_events(turn_id: str, seq: int = 0, timeout: float = 25.0) -> list[dict]:
    """Block until the turn has events after ``seq`` -- or is done, or ``timeout``.

    This is the SSE route's heartbeat: an empty list means "nothing new yet, still
    running", and a caller that gets events ending in ``done`` closes the stream.
    """
    deadline = time.time() + max(0.0, float(timeout))
    with _COND:
        while True:
            turn = TURNS.get(str(turn_id or ''))
            if turn is None:
                return []
            fresh = [event for event in turn['events'] if event['seq'] > int(seq or 0)]
            if fresh or turn['done']:
                return fresh
            remaining = deadline - time.time()
            if remaining <= 0:
                return []
            _COND.wait(remaining)


def cancel_turn(turn_id: str) -> bool:
    """Ask a running turn to stop. False when the id is unknown or already finished."""
    with _COND:
        turn = TURNS.get(str(turn_id or ''))
        if turn is None or turn['done']:
            return False
        turn['cancel'].set()
        _COND.notify_all()
        return True


# ── starting a turn ──────────────────────────────────────────────────────────


def _selection(provider: str | None, model: str | None) -> tuple[str, str]:
    if provider and model:
        return str(provider), str(model)
    chosen = models.get_selection() or {}
    return str(provider or chosen.get('provider') or ''), str(model or chosen.get('model') or '')


def _auth_error(provider: str) -> str:
    """The reason this provider cannot run a turn right now, or ``''``."""
    if provider == 'subscription':
        if not _host.claude_login_present():
            return 'no Claude Code login found — run `claude login`, or pick another model'
        return ''
    if provider not in PROVIDERS or provider == 'ollama':
        return ''
    try:
        status, detail = models.provider_status(provider)
    except Exception as exc:  # noqa: BLE001 - an unreadable status is not a block
        _log.warning('agent_zero.runner: provider_status(%s) failed (%s)', provider, exc)
        return ''
    return '' if status == 'ready' else f'{provider} is not usable: {detail}'


def start_turn(
    session_id: str,
    message: str,
    image_b64: str | None = None,
    provider: str | None = None,
    model: str | None = None,
    cookie: str = '',
    csrf: str = '',
    actor: str = '',
    confirm: dict | None = None,
    extra: dict | None = None,
) -> dict:
    """Validate, budget and launch one turn. Returns ``{'turn_id': ...}``.

    ``extra`` is handed to the backend as ``ctx.extra`` -- per-turn options a backend
    understands and nothing above it has to know about.

    Raises ``ValueError`` for an unknown session or an empty message, and
    :class:`BudgetBlocked` when a ceiling refuses the turn.
    """
    text = str(message or '').strip()
    if not text:
        raise ValueError('message is required')
    session = memory.get_session(session_id)
    if session is None:
        raise ValueError(f'unknown session {session_id!r}')

    chosen_provider, chosen_model = _selection(provider, model)
    if not chosen_provider or not chosen_model:
        raise ValueError('no model is selected')

    memory.append_message(session_id, {'role': 'user', 'content': text})
    session = memory.get_session(session_id)
    if session is None:
        raise ValueError(f'unknown session {session_id!r}')

    cfg = budget.load_config()
    compacted = _maybe_compact(session, cfg, chosen_provider, chosen_model, cookie, csrf, actor)
    if compacted:
        session = memory.get_session(session_id) or session

    selection = {'provider': chosen_provider, 'model': chosen_model}
    system, messages, est = prompt.build(session, text, selection, cfg, image_b64=image_b64)

    verdict = budget.check_turn(chosen_provider, chosen_model, est)
    if not verdict.get('allowed'):
        _record_blocked(session, selection, verdict, est, actor, text)
        raise BudgetBlocked(str(verdict.get('reason') or 'the budget refused this turn'), verdict.get('state') or {})

    per_turn = cfg['per_turn']
    turn = {
        'id': uuid.uuid4().hex[:12],
        'session_id': session_id,
        'provider': chosen_provider,
        'model': chosen_model,
        'started': time.time(),
        'events': [],
        'seq': 0,
        'done': False,
        'cancel': threading.Event(),
        'pending_confirm': None,
        'cookie': str(cookie or ''),
        'csrf': str(csrf or ''),
        'actor': str(actor or ''),
        'usage': {},
        'tool_calls': [],
        'stop_reason': None,
        'system': system,
        'messages': messages,
        'message': text,
        'est_tokens': est,
        'compacted': bool(compacted),
        'budget_level': str(verdict.get('level') or 'ok'),
        'budget_reason': str(verdict.get('reason') or ''),
        'stage': 'confirm' if confirm else 'chat',
        'confirm': dict(confirm or {}),
        'extra': dict(extra or {}),
        'max_tool_calls': int(per_turn['max_tool_calls']),
        'max_output_tokens': int(per_turn['max_output_tokens']),
        'thinking_tokens': int(per_turn['thinking_tokens']),
        'timeout_s': int(per_turn['timeout_s']),
        'history_turns': int(session.get('turns') or 0),
    }
    with _COND:
        TURNS[turn['id']] = turn
        _reap()

    threading.Thread(target=run_turn, args=(turn,), name=f'zero-turn-{turn["id"]}', daemon=True).start()
    return {'turn_id': turn['id']}


def _record_blocked(session: dict, selection: dict, verdict: dict, est: int, actor: str, text: str) -> None:
    """A refused turn is still a turn: it goes into the ledger with its reason."""
    metrics.record_turn(
        {
            'turn_id': uuid.uuid4().hex[:12],
            'session_id': session.get('id') or '',
            'actor': actor,
            'provider': selection['provider'],
            'model': selection['model'],
            'backend': '',
            'stage': 'chat',
            'context_tokens_est': est,
            'history_turns': int(session.get('turns') or 0),
            'budget_level': str(verdict.get('level') or 'blocked'),
            'budget_reason': str(verdict.get('reason') or ''),
            'stop_reason': 'blocked',
            'error': str(verdict.get('reason') or 'blocked'),
            'message': text,
        }
    )


# ── compaction ───────────────────────────────────────────────────────────────


def _maybe_compact(session: dict, cfg: dict, provider: str, model: str, cookie: str, csrf: str, actor: str) -> bool:
    """Fold old history into the rolling summary when it has grown past the threshold.

    The summary costs one extra backend turn with no tools and a 600-token ceiling; it
    is recorded in the ledger under ``stage='compaction'`` so it is never invisible.
    """
    threshold = int((cfg.get('per_session') or {}).get('compact_after_tokens') or 24000)
    if not memory.needs_compaction(session, threshold):
        return False
    keep = int((cfg.get('per_session') or {}).get('keep_recent_turns') or 8)
    before = session.get('summary_covers')
    summarizer = _summarizer(session, provider, model, cookie, csrf, actor)
    try:
        after = memory.compact(session, summarizer, keep)
    except Exception as exc:  # noqa: BLE001 - a failed compaction keeps the history
        _log.warning('agent_zero.runner: compaction of %s failed (%s)', session.get('id'), exc)
        return False
    return after.get('summary_covers') != before


def _summarizer(session: dict, provider: str, model: str, cookie: str, csrf: str, actor: str):
    """A ``summarize(text) -> str`` that runs one tool-less backend turn."""

    def summarize(text: str) -> str:
        started = time.time()
        ctx = TurnContext(
            turn_id=uuid.uuid4().hex[:12],
            session_id=str(session.get('id') or ''),
            provider=provider,
            model=model,
            system=SUMMARY_SYSTEM,
            messages=[{'role': 'user', 'content': text}],
            tools=[],
            max_output_tokens=SUMMARY_MAX_TOKENS,
            max_tool_calls=0,
            cookie=cookie,
            csrf=csrf,
        )
        parts: list[str] = []
        usage: dict = {}
        error = None
        try:
            for event in backends.get(provider).run(ctx):
                kind = event.get('type')
                if kind == 'text_delta':
                    parts.append(str(event.get('text') or ''))
                elif kind == 'usage':
                    usage = event
                elif kind == 'error':
                    error = str(event.get('message') or '')
        except Exception as exc:  # noqa: BLE001 - reported, then the history is kept
            error = f'{type(exc).__name__}: {exc}'
            _log.warning('agent_zero.runner: summarizer backend failed (%s)', exc)
        summary = ''.join(parts).strip()
        budget.record(provider, model, usage)
        metrics.record_turn(
            {
                'turn_id': ctx.turn_id,
                'session_id': ctx.session_id,
                'actor': actor,
                'provider': provider,
                'model': model,
                'backend': backends_name(provider),
                'stage': 'compaction',
                'input_tokens': int(usage.get('input_tokens') or 0),
                'output_tokens': int(usage.get('output_tokens') or 0),
                'cache_read': int(usage.get('cache_read') or 0),
                'cache_write': int(usage.get('cache_write') or 0),
                'api_usd': usage.get('cost_usd'),
                'latency_ms': int((time.time() - started) * 1000),
                'compacted': True,
                'stop_reason': 'error' if error else 'end_turn',
                'error': error,
                'message': text[:300],
                'text': summary,
            }
        )
        return summary

    return summarize


def backends_name(provider: str) -> str:
    """The backend module name behind a provider, for the ledger's ``backend`` column."""
    try:
        return backends.get(provider).__name__.rsplit('.', 1)[-1]
    except Exception:  # noqa: BLE001 - an unknown provider logs an empty backend
        return ''


# ── running a turn ───────────────────────────────────────────────────────────


def _confirm_target(name: str, args: dict) -> tuple[str, dict]:
    """What a confirmation is really about: the inner tool of a ``zero_call``."""
    args = dict(args or {})
    if name == 'zero_call':
        inner = str(args.get('tool') or '')
        if inner:
            return inner, dict(args.get('args') or {})
    return str(name or ''), args


def _tool_runner(turn: dict):
    """The ``execute_tool`` closure handed to the backend (CONTRACT C)."""

    def execute_tool(name: str, args: dict) -> dict:
        if not budget.check_tool(len(turn['tool_calls'])):
            return {
                'ok': False,
                'text': (
                    f'the tool budget for this turn is spent ({len(turn["tool_calls"])} calls). '
                    'Answer with what you have and say what is left to do.'
                ),
                'ms': 0,
                'risk': 'read',
                'needs_confirmation': False,
                'confirm_id': None,
            }
        result = toolmap_exec.execute(
            name,
            dict(args or {}),
            turn['cookie'],
            turn['csrf'],
            confirmed=False,
            actor=turn['actor'],
        )
        if not isinstance(result, dict):
            result = {'ok': False, 'text': 'tool returned no result', 'ms': 0}
        target, target_args = _confirm_target(name, args)
        turn['tool_calls'].append(
            {
                'name': target,
                'ok': bool(result.get('ok')),
                'risk': str(result.get('risk') or 'read'),
                'ms': int(result.get('ms') or 0),
                'needs_confirmation': bool(result.get('needs_confirmation')),
            }
        )
        if result.get('needs_confirmation'):
            turn['pending_confirm'] = {
                'confirm_id': result.get('confirm_id'),
                'name': target,
                'args': target_args,
                'risk': str(result.get('risk') or 'danger'),
            }
        return result

    return execute_tool


def _context(turn: dict) -> TurnContext:
    extra = dict(turn.get('extra') or {})
    if turn.get('confirm'):
        extra['confirm'] = dict(turn['confirm'])
    ctx = TurnContext(
        turn_id=turn['id'],
        session_id=turn['session_id'],
        provider=turn['provider'],
        model=turn['model'],
        system=turn['system'],
        messages=turn['messages'],
        tools=toolmap.tool_specs(),
        execute_tool=_tool_runner(turn),
        max_output_tokens=turn['max_output_tokens'],
        max_tool_calls=turn['max_tool_calls'],
        thinking_tokens=turn['thinking_tokens'],
        timeout_s=turn['timeout_s'],
        cookie=turn['cookie'],
        csrf=turn['csrf'],
        cancel=turn['cancel'],
        extra=extra,
    )
    # 2026-10-08 review fix: the MCP bridge (routes_mcp) looks the per-turn secret up
    # through TURNS[turn_id]['ctx'].extra['mcp_token']; without this line the
    # subscription backend wrote the token into a context nobody could reach and
    # every tool call from the CLI shim was refused with 403.
    turn['ctx'] = ctx
    extra['turn'] = turn
    return ctx


def run_turn(turn: dict) -> None:
    """Drive one turn's backend to the end, then always book it. Never raises."""
    started = time.time()
    text_parts: list[str] = []
    ttft_ms = None
    error = None
    stop_reason = 'end_turn'

    try:
        reason = _auth_error(turn['provider'])
        if reason:
            raise _AuthError(reason)
        backend = backends.get(turn['provider'])
        for event in backend.run(_context(turn)):
            kind = event.get('type')
            if kind == 'text_delta':
                if ttft_ms is None:
                    ttft_ms = int((time.time() - started) * 1000)
                text_parts.append(str(event.get('text') or ''))
            elif kind == 'usage':
                turn['usage'] = dict(event)
            elif kind == 'error':
                error = str(event.get('message') or '')
            elif kind == 'done':
                stop_reason = str(event.get('stop_reason') or 'end_turn')
                if turn['pending_confirm']:
                    stop_reason = 'needs_confirmation'
                    _append(turn, dict(turn['pending_confirm'], type='confirm'))
                if turn['cancel'].is_set():
                    stop_reason = 'cancelled'
                _append(turn, {'type': 'done', 'stop_reason': stop_reason})
                continue
            _append(turn, dict(event))
    except _AuthError as exc:
        error, stop_reason = str(exc), 'error'
        _append(turn, {'type': 'error', 'message': error, 'kind': 'auth'})
        _append(turn, {'type': 'done', 'stop_reason': 'error'})
    except Exception as exc:  # noqa: BLE001 - a backend crash is an event, not a 500
        error, stop_reason = f'{type(exc).__name__}: {exc}', 'error'
        _log.warning('agent_zero.runner: turn %s failed (%s)', turn['id'], exc)
        _append(turn, {'type': 'error', 'message': error, 'kind': 'backend'})
        _append(turn, {'type': 'done', 'stop_reason': 'error'})

    turn['stop_reason'] = stop_reason
    _book(turn, ''.join(text_parts), started, ttft_ms, error, stop_reason)
    _finish(turn)


def _assistant_content(text: str, turn: dict) -> str:
    """The assistant message stored in the session: its prose plus a tool summary."""
    parts = [text.strip()] if text.strip() else []
    if turn['tool_calls']:
        names = ', '.join(f'{call["name"]}{"" if call["ok"] else " (failed)"}' for call in turn['tool_calls'])
        parts.append(f'[tools used: {names}]')
    if turn.get('pending_confirm'):
        parts.append(f'[waiting for confirmation: {turn["pending_confirm"]["name"]}]')
    return '\n'.join(parts)


def _book(turn: dict, text: str, started: float, ttft_ms, error, stop_reason: str) -> None:
    """Persist, bill and record one finished turn. Every step is best effort."""
    usage = turn.get('usage') or {}
    try:
        memory.append_message(
            turn['session_id'],
            {
                'role': 'assistant',
                'content': _assistant_content(text, turn),
                'turn_id': turn['id'],
            },
        )
    except Exception as exc:  # noqa: BLE001 - a lost message must not lose the metrics
        _log.warning('agent_zero.runner: cannot append the assistant message (%s)', exc)
    try:
        budget.record(turn['provider'], turn['model'], usage)
    except Exception as exc:  # noqa: BLE001 - billing is bookkeeping
        _log.warning('agent_zero.runner: budget.record failed (%s)', exc)
    calls = turn['tool_calls']
    metrics.record_turn(
        {
            'turn_id': turn['id'],
            'session_id': turn['session_id'],
            'actor': turn['actor'],
            'provider': turn['provider'],
            'model': turn['model'],
            'backend': backends_name(turn['provider']),
            'stage': turn['stage'],
            'input_tokens': int(usage.get('input_tokens') or 0),
            'output_tokens': int(usage.get('output_tokens') or 0),
            'cache_read': int(usage.get('cache_read') or 0),
            'cache_write': int(usage.get('cache_write') or 0),
            'api_usd': usage.get('cost_usd'),
            'latency_ms': int((time.time() - started) * 1000),
            'ttft_ms': ttft_ms,
            'tool_calls': len(calls),
            'tool_names': [call['name'] for call in calls],
            'tool_errors': sum(1 for call in calls if not call['ok']),
            'danger_calls': sum(1 for call in calls if call['risk'] == 'danger'),
            'confirmations': sum(1 for call in calls if call['needs_confirmation']),
            'context_tokens_est': int(turn['est_tokens']),
            'history_turns': int(turn['history_turns']),
            'compacted': bool(turn['compacted']),
            'budget_level': turn['budget_level'],
            'budget_reason': turn['budget_reason'],
            'stop_reason': stop_reason,
            'error': error,
            'cancelled': bool(turn['cancel'].is_set()),
            'message': turn['message'],
            'text': text,
        }
    )


# ── the confirmation handshake ───────────────────────────────────────────────


def confirm(
    session_id: str,
    confirm_id: str,
    approve: bool,
    cookie: str = '',
    csrf: str = '',
    actor: str = '',
) -> dict:
    """Answer a pending danger call and continue the conversation in a new turn.

    On approval the stored call is fired here -- not by the model -- and its result is
    handed back as the next user message, so the transcript shows who agreed to what.
    """
    name = toolmap_exec.pending_tool(confirm_id) or str(confirm_id or '')
    if approve:
        result = toolmap_exec.execute_confirmed(str(confirm_id or ''), cookie, csrf, actor)
        text = str((result or {}).get('text') or '')[:CONFIRM_RESULT_CHARS]
        message = f'[The user approved: {name}. Result: {text}] Continue.'
    else:
        message = f'[The user declined: {name}.] Continue without it.'
    return start_turn(
        session_id,
        message,
        cookie=cookie,
        csrf=csrf,
        actor=actor,
        confirm={'confirm_id': str(confirm_id or ''), 'approved': bool(approve), 'tool': name},
    )
