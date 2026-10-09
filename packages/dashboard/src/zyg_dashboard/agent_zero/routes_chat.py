# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The chat HTTP contract of Agent Zero v2 (CONTRACT G): sessions, turns, SSE, tools.

This is the surface the chat window is built against, and it is deliberately thin:
sessions come from :mod:`agent_zero.memory`, a turn is launched by
:func:`agent_zero.runner.start_turn` and the browser then *reads* the turn as a stream
of events. Nothing here knows how a model works.

Three decisions are worth stating, because the frontend depends on them:

* **A turn is accepted, not awaited.** ``POST .../turn`` answers ``202`` with a
  ``turn_id`` the moment the runner's thread is alive, so a slow model never holds an
  HTTP worker. Everything the turn produces is read back from
  ``GET /api/zero/v2/turns/<id>/events``, a Server-Sent Events stream whose every frame
  carries the runner's monotonic ``seq``: a browser that reconnects asks for
  ``?from=<last seq>`` and loses nothing.
* **One turn per session.** A second ``POST .../turn`` while a turn is still running on
  the same session answers ``409`` with the running ``turn_id`` instead of interleaving
  two models in one transcript.
* **Authentication is the dashboard's.** The host's ``before_request`` login gate and
  CSRF check already cover every route on this blueprint, so no route re-implements
  them -- and the session cookie plus the ``X-CSRF-Token`` header are handed to the
  runner, because a tool call is made *as the person talking to Agent Zero*.
"""

from __future__ import annotations

import json
import logging

from flask import Response, jsonify, request, stream_with_context

from . import _host, bp, memory, models, runner, toolmap, toolmap_exec

_log = logging.getLogger(__name__)

#: Longest ``tool_result`` text sent to the browser in a session payload. The full text
#: stays on disk -- this is a transport ceiling, not a retention policy.
TOOL_RESULT_CHARS = 4000

#: Seconds the SSE generator blocks on the runner before it emits a keepalive comment.
SSE_WAIT_S = 15

#: The greeting sentence. Fixed wording: the chat window asserts it verbatim.
GREETING = 'Hi {name}, how can I help you?'


def _body() -> dict:
    """The request's JSON body, tolerant of a missing or malformed one."""
    return request.get_json(silent=True) or {}


def _error(message: str, status: int, **extra):
    """Every JSON error on this blueprint has the same shape."""
    return jsonify({'error': str(message), **extra}), status


def _actor() -> str:
    """Who is talking: the dashboard session's user name."""
    return _host.user_name()


def _selection() -> dict:
    """The currently selected ``{'provider', 'model'}``, never raising."""
    try:
        chosen = models.get_selection() or {}
    except Exception as exc:  # noqa: BLE001 - a greeting must not fail on the registry
        _log.warning('agent_zero.routes_chat: cannot read the model selection (%s)', exc)
        return {'provider': '', 'model': ''}
    return {'provider': str(chosen.get('provider') or ''), 'model': str(chosen.get('model') or '')}


def _for_wire(session: dict) -> dict:
    """A session as the browser gets it: tool results truncated, disk untouched.

    The copy is shallow until a message actually needs trimming, so the common case
    (no tool blocks) costs nothing.
    """
    out = dict(session)
    messages = []
    for msg in session.get('messages') or []:
        content = msg.get('content')
        if not isinstance(content, list):
            messages.append(msg)
            continue
        blocks = []
        trimmed = False
        for block in content:
            if isinstance(block, dict) and block.get('type') == 'tool_result':
                text = block.get('content')
                if isinstance(text, str) and len(text) > TOOL_RESULT_CHARS:
                    block = dict(block, content=text[:TOOL_RESULT_CHARS], truncated=True)
                    trimmed = True
            blocks.append(block)
        messages.append(dict(msg, content=blocks) if trimmed else msg)
    out['messages'] = messages
    return out


def _running_turn(session_id: str) -> dict | None:
    """The unfinished turn of this session, if one is still going."""
    for turn in list(runner.TURNS.values()):
        if turn.get('session_id') == session_id and not turn.get('done'):
            return turn
    return None


# ── greeting and tools ──────────────────────────────────────────────────────


@bp.get('/api/zero/v2/greeting')
def zero_v2_greeting():
    """What the chat window shows before the operator has typed anything."""
    name = _actor()
    return jsonify({'text': GREETING.format(name=name), 'user': name, 'selected': _selection()})


@bp.get('/api/zero/v2/tools')
def zero_v2_tools():
    """The tool map as text, for the UI's ``/tools`` help and the metrics tab."""
    group = str(request.args.get('group') or '').strip()
    query = str(request.args.get('q') or '').strip()
    payload = {'index': toolmap.index_text(), 'count': len(toolmap.catalog())}
    if group:
        payload['group'] = toolmap.group_text(group)
    if query:
        payload['results'] = toolmap.find(query)
    return jsonify(payload)


# ── sessions ────────────────────────────────────────────────────────────────


@bp.get('/api/zero/v2/sessions')
def zero_v2_sessions():
    """The chat list, newest first, read from the index alone."""
    try:
        limit = int(request.args.get('limit') or 50)
    except (TypeError, ValueError):
        limit = 50
    return jsonify({'sessions': memory.list_sessions(max(0, limit))})


@bp.post('/api/zero/v2/sessions')
def zero_v2_session_new():
    """Start an empty chat against the current model selection."""
    chosen = _selection()
    session = memory.new_session(_actor(), chosen['provider'], chosen['model'])
    return jsonify({'session': session}), 201


@bp.get('/api/zero/v2/sessions/<session_id>')
def zero_v2_session_get(session_id):
    """One whole chat, messages included."""
    session = memory.get_session(session_id)
    if session is None:
        return _error(f'unknown session: {session_id}', 404)
    return jsonify({'session': _for_wire(session)})


@bp.delete('/api/zero/v2/sessions/<session_id>')
def zero_v2_session_delete(session_id):
    """Forget a chat. Deleting an already-gone chat is not an error."""
    memory.delete_session(session_id)
    return jsonify({'ok': True})


@bp.post('/api/zero/v2/sessions/<session_id>/rename')
def zero_v2_session_rename(session_id):
    """Set a chat's title."""
    session = memory.rename_session(session_id, str(_body().get('title') or ''))
    if session is None:
        return _error(f'unknown session: {session_id}', 404)
    return jsonify({'ok': True, 'title': session['title']})


@bp.post('/api/zero/v2/sessions/<session_id>/pin')
def zero_v2_session_pin(session_id):
    """Add a standing fact that goes into every prompt of this chat."""
    text = str(_body().get('text') or '').strip()
    if not text:
        return _error('text is required', 400)
    session = memory.pin(session_id, text)
    if session is None:
        return _error(f'unknown session: {session_id}', 404)
    return jsonify({'ok': True, 'pinned': session['pinned']})


@bp.post('/api/zero/v2/sessions/<session_id>/unpin')
def zero_v2_session_unpin(session_id):
    """Remove a pinned fact."""
    text = str(_body().get('text') or '').strip()
    if not text:
        return _error('text is required', 400)
    session = memory.unpin(session_id, text)
    if session is None:
        return _error(f'unknown session: {session_id}', 404)
    return jsonify({'ok': True, 'pinned': session['pinned']})


# ── turns ───────────────────────────────────────────────────────────────────


@bp.post('/api/zero/v2/sessions/<session_id>/turn')
def zero_v2_turn(session_id):
    """Launch one turn. 202 with a ``turn_id``; the stream is read separately."""
    body = _body()
    message = str(body.get('message') or '').strip()
    image_b64 = body.get('image_b64') or None
    if not message and not image_b64:
        return _error('message is required', 400)
    if memory.get_session(session_id) is None:
        return _error(f'unknown session: {session_id}', 404)
    running = _running_turn(session_id)
    if running is not None:
        return _error('turn in progress', 409, turn_id=running['id'])

    try:
        started = runner.start_turn(
            session_id,
            message,
            image_b64=image_b64,
            provider=str(body.get('provider') or '') or None,
            model=str(body.get('model') or '') or None,
            cookie=request.cookies.get('session', ''),
            csrf=request.headers.get('X-CSRF-Token', ''),
            actor=_actor(),
        )
    except runner.BudgetBlocked as exc:
        return _error(exc.reason, 429, budget=exc.state, kind='budget')
    except ValueError as exc:
        return _error(str(exc), 400)

    turn = runner.TURNS.get(started['turn_id']) or {}
    return (
        jsonify(
            {
                'turn_id': started['turn_id'],
                'session_id': session_id,
                'provider': turn.get('provider') or '',
                'model': turn.get('model') or '',
            }
        ),
        202,
    )


@bp.get('/api/zero/v2/turns/<turn_id>')
def zero_v2_turn_state(turn_id):
    """A turn's snapshot, for a client that polls instead of streaming."""
    snapshot = runner.get_turn(turn_id)
    if snapshot is None:
        return _error(f'unknown turn: {turn_id}', 404)
    snapshot['events_count'] = len(runner.events_since(turn_id, 0))
    return jsonify(snapshot)


def _frame(event: dict) -> str:
    """One Server-Sent Events frame carrying the runner's own sequence number."""
    return 'id: {seq}\nevent: {kind}\ndata: {data}\n\n'.format(
        seq=event.get('seq') or 0,
        kind=event.get('type') or 'message',
        data=json.dumps(event, default=str),
    )


@bp.get('/api/zero/v2/turns/<turn_id>/events')
def zero_v2_turn_events(turn_id):
    """Stream a turn as Server-Sent Events, resumable with ``?from=<seq>``."""
    if runner.get_turn(turn_id) is None:
        return _error(f'unknown turn: {turn_id}', 404)
    try:
        start = int(request.args.get('from') or 0)
    except (TypeError, ValueError):
        start = 0

    def gen():
        seq = max(0, start)
        while True:
            events = runner.wait_events(turn_id, seq, timeout=SSE_WAIT_S)
            if not events:
                snapshot = runner.get_turn(turn_id)
                if snapshot is None or snapshot['done']:
                    return
                yield ': keepalive\n\n'
                continue
            for event in events:
                seq = max(seq, int(event.get('seq') or 0))
                yield _frame(event)
                if event.get('type') == 'done':
                    return

    response = Response(stream_with_context(gen()), mimetype='text/event-stream')
    response.headers['Cache-Control'] = 'no-store'
    response.headers['X-Accel-Buffering'] = 'no'
    return response


@bp.post('/api/zero/v2/turns/<turn_id>/cancel')
def zero_v2_turn_cancel(turn_id):
    """Ask a running turn to stop. Cancelling a finished turn is not an error."""
    if runner.get_turn(turn_id) is None:
        return _error(f'unknown turn: {turn_id}', 404)
    return jsonify({'ok': runner.cancel_turn(turn_id)})


@bp.post('/api/zero/v2/sessions/<session_id>/confirm')
def zero_v2_confirm(session_id):
    """Answer a pending danger call; the continuation runs as a new turn."""
    body = _body()
    confirm_id = str(body.get('confirm_id') or '').strip()
    if not confirm_id:
        return _error('confirm_id is required', 400)
    if memory.get_session(session_id) is None:
        return _error(f'unknown session: {session_id}', 404)
    if toolmap_exec.pending_tool(confirm_id) is None:
        return _error(f'unknown confirmation: {confirm_id}', 404)
    try:
        started = runner.confirm(
            session_id,
            confirm_id,
            bool(body.get('approve')),
            cookie=request.cookies.get('session', ''),
            csrf=request.headers.get('X-CSRF-Token', ''),
            actor=_actor(),
        )
    except runner.BudgetBlocked as exc:
        return _error(exc.reason, 429, budget=exc.state, kind='budget')
    except ValueError as exc:
        return _error(str(exc), 400)
    return jsonify({'turn_id': started['turn_id']}), 202
