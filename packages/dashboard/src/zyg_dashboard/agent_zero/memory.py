# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Agent Zero v2's session store and context manager (CONTRACT E).

A chat session is one JSON file under ``data/runtime/zero_sessions/<id>.json`` plus a row
in ``zero_sessions/index.json``, which is rewritten atomically on every save so the chat
list never has to open the sessions themselves.

The point of this module is that the prompt stays small *by construction* rather than by
truncation. A session keeps its full transcript on disk, but what goes into a turn is:

* the pinned facts (always, in full -- they are the user's own standing instructions),
* the rolling ``summary`` of everything older than ``keep_recent_turns`` pairs,
* those recent pairs, with tool results older than the last two turns reduced to a
  one-line note.

Two invariants hold whatever the budget says, because breaking either would trade
reliability for tokens:

* the **current user message is never trimmed** -- if it does not fit, ``budget.check_turn``
  refuses the turn and says so; this module does not quietly cut it down;
* a collapsed turn never leaves a ``tool_use`` block without its ``tool_result``. Both
  sides become text notes together, so the message list stays valid for the API.
"""

from __future__ import annotations

import datetime as _dt
import json
import logging
import os
import tempfile
import threading
import uuid

from . import _host
from .contracts import estimate_tokens

_log = logging.getLogger(__name__)

SESSIONS_DIRNAME = 'zero_sessions'
INDEX_NAME = 'index.json'
NEW_TITLE = 'New chat'

#: Longest auto-generated title, taken from the first user message.
TITLE_CHARS = 48

#: Recent turns whose tool results are kept verbatim. Older ones become a one-line note.
TOOL_DETAIL_TURNS = 2

_LOCK = threading.Lock()


# ── paths ───────────────────────────────────────────────────────────────────


def sessions_dir() -> str:
    """Directory holding the session files and the index, created on demand."""
    path = os.path.join(_host.runtime_dir(), SESSIONS_DIRNAME)
    os.makedirs(path, exist_ok=True)
    return path


def session_path(session_id: str) -> str:
    """Path of one session file. Raises ``ValueError`` on an id that is not a bare slug."""
    sid = str(session_id or '')
    if not sid or not all(c.isalnum() or c in '-_' for c in sid):
        raise ValueError(f'bad session id {session_id!r}')
    return os.path.join(sessions_dir(), f'{sid}.json')


def index_path() -> str:
    """Path of the chat-list index."""
    return os.path.join(sessions_dir(), INDEX_NAME)


def _now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat(timespec='seconds')


def _write_json(path: str, data) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), prefix='.zero_session.', suffix='.tmp')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as fh:
            json.dump(data, fh, indent=2)
            fh.write('\n')
        os.replace(tmp, path)
    except Exception:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def _read_json(path: str) -> dict:
    try:
        with open(path, encoding='utf-8') as fh:
            data = json.load(fh)
    except FileNotFoundError:
        return {}
    except Exception as exc:  # noqa: BLE001 - a corrupt session must not break the list
        _log.warning('agent_zero.memory: cannot read %s (%s)', path, exc)
        return {}
    return data if isinstance(data, dict) else {}


# ── CRUD ────────────────────────────────────────────────────────────────────


def new_session(user: str, provider: str, model: str) -> dict:
    """Create and persist an empty session, and return it."""
    session = {
        'id': uuid.uuid4().hex[:12],
        'title': NEW_TITLE,
        'created': _now(),
        'updated': _now(),
        'user': str(user or 'User'),
        'provider': str(provider or ''),
        'model': str(model or ''),
        'turns': 0,
        'messages': [],
        'summary': '',
        'summary_covers': 0,
        'pinned': [],
    }
    save_session(session)
    return session


def get_session(session_id: str) -> dict | None:
    """One session, or ``None`` when it does not exist."""
    try:
        data = _read_json(session_path(session_id))
    except ValueError:
        return None
    return _normalise(data) if data else None


def _normalise(session: dict) -> dict:
    """Fill in keys an older session file may not have."""
    session.setdefault('title', NEW_TITLE)
    session.setdefault('messages', [])
    session.setdefault('summary', '')
    session.setdefault('summary_covers', 0)
    session.setdefault('pinned', [])
    session.setdefault('turns', sum(1 for m in session['messages'] if m.get('role') == 'user'))
    return session


def save_session(session: dict) -> dict:
    """Write the session and rewrite the index. Both writes are atomic."""
    session['updated'] = _now()
    with _LOCK:
        _write_json(session_path(session['id']), session)
        index = _read_json(index_path())
        index[session['id']] = {
            'title': session.get('title') or NEW_TITLE,
            'updated': session['updated'],
            'turns': int(session.get('turns') or 0),
            'provider': session.get('provider') or '',
            'model': session.get('model') or '',
        }
        _write_json(index_path(), index)
    return session


def list_sessions(limit: int = 50) -> list[dict]:
    """Chat-list rows, newest first, read from the index alone."""
    index = _read_json(index_path())
    rows = [dict(row, id=sid) for sid, row in index.items() if isinstance(row, dict)]
    rows.sort(key=lambda r: r.get('updated') or '', reverse=True)
    return rows[: max(0, int(limit))]


def delete_session(session_id: str) -> bool:
    """Remove a session and its index row. False when there was nothing to remove."""
    try:
        path = session_path(session_id)
    except ValueError:
        return False
    with _LOCK:
        existed = os.path.exists(path)
        if existed:
            os.unlink(path)
        index = _read_json(index_path())
        if index.pop(session_id, None) is not None:
            _write_json(index_path(), index)
    return existed


def rename_session(session_id: str, title: str) -> dict | None:
    """Set a session's title (the chat list reads it from the index)."""
    session = get_session(session_id)
    if session is None:
        return None
    session['title'] = (str(title or '').strip() or NEW_TITLE)[:120]
    return save_session(session)


def _auto_title(text: str) -> str:
    flat = ' '.join(str(text or '').split())
    return flat[:TITLE_CHARS].strip() or NEW_TITLE


def append_message(session_id: str, msg: dict) -> dict | None:
    """Append one message, auto-titling the session from the first user message."""
    session = get_session(session_id)
    if session is None:
        return None
    entry = dict(msg or {})
    entry.setdefault('role', 'user')
    entry.setdefault('content', '')
    entry.setdefault('ts', _now())
    entry.setdefault('turn_id', uuid.uuid4().hex[:12])
    if entry['role'] == 'user':
        if session.get('title') in (None, '', NEW_TITLE) and session['turns'] == 0:
            session['title'] = _auto_title(_text_of(entry))
        session['turns'] = int(session.get('turns') or 0) + 1
    session['messages'].append(entry)
    return save_session(session)


def pin(session_id: str, text: str) -> dict | None:
    """Add a standing fact that goes into every prompt and survives compaction."""
    session = get_session(session_id)
    if session is None:
        return None
    fact = str(text or '').strip()
    if fact and fact not in session['pinned']:
        session['pinned'].append(fact)
        return save_session(session)
    return session


def unpin(session_id: str, text: str) -> dict | None:
    """Remove a pinned fact."""
    session = get_session(session_id)
    if session is None:
        return None
    fact = str(text or '').strip()
    if fact in session['pinned']:
        session['pinned'].remove(fact)
        return save_session(session)
    return session


# ── context assembly ────────────────────────────────────────────────────────


def _text_of(msg: dict) -> str:
    """Flatten a message's content to text for estimating and summarising."""
    content = msg.get('content')
    if isinstance(content, str):
        return content
    out = []
    for block in content or []:
        if not isinstance(block, dict):
            out.append(str(block))
        elif block.get('type') == 'text':
            out.append(str(block.get('text') or ''))
        elif block.get('type') == 'tool_use':
            out.append(f'[tool {block.get("name")} called with {json.dumps(block.get("input") or {}, default=str)}]')
        elif block.get('type') == 'tool_result':
            result = block.get('content') or ''
            out.append(f'[tool result: {result}]')
        elif block.get('type') == 'image':
            out.append('[image]')
    return '\n'.join(out)


def _msg_tokens(msg: dict) -> int:
    return estimate_tokens(_text_of(msg))


def estimate_history_tokens(session: dict) -> int:
    """Estimated size of the part of the transcript the summary has not replaced yet."""
    return sum(_msg_tokens(m) for m in _live_messages(session))


def _live_messages(session: dict) -> list[dict]:
    covers = max(0, int(session.get('summary_covers') or 0))
    return list(session.get('messages') or [])[covers:]


def needs_compaction(session: dict, compact_after_tokens: int) -> bool:
    """True when the un-summarised transcript has grown past the configured threshold."""
    return estimate_history_tokens(session) >= int(compact_after_tokens)


def _split_turns(messages: list[dict]) -> list[list[dict]]:
    """Group a flat message list into turns, each starting at a user message."""
    turns: list[list[dict]] = []
    for msg in messages:
        if msg.get('role') == 'user' or not turns:
            turns.append([msg])
        else:
            turns[-1].append(msg)
    return turns


def _tool_names(messages: list[dict]) -> dict[str, str]:
    """``tool_use_id -> tool name``, so a collapsed result can still name its tool."""
    names = {}
    for msg in messages:
        content = msg.get('content')
        if isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get('type') == 'tool_use' and block.get('id'):
                    names[str(block['id'])] = str(block.get('name') or 'tool')
    return names


def _collapse_tools(msg: dict, names: dict[str, str]) -> dict:
    """Replace this message's tool traffic with one-line notes.

    Both halves of a tool round-trip collapse together: a ``tool_use`` left behind
    without its ``tool_result`` would make the request invalid, which is a far worse
    outcome than the tokens it saves.
    """
    content = msg.get('content')
    if not isinstance(content, list):
        return dict(msg)
    blocks = []
    for block in content:
        if not isinstance(block, dict):
            blocks.append(block)
            continue
        kind = block.get('type')
        if kind == 'tool_use':
            blocks.append({'type': 'text', 'text': f'[tool {block.get("name") or "tool"} called]'})
        elif kind == 'tool_result':
            name = names.get(str(block.get('tool_use_id')), 'tool')
            status = 'error' if block.get('is_error') else 'ok'
            blocks.append({'type': 'text', 'text': f'[tool {name} ran, {status}]'})
        else:
            blocks.append(block)
    return dict(msg, content=blocks)


def history_for_prompt(session: dict, max_tokens: int, keep_recent_turns: int = 8) -> tuple[str, list[dict]]:
    """Assemble ``(summary_text, recent_messages)`` for one turn's prompt.

    ``summary_text`` is the rolling summary with the pinned facts in front of it; pinned
    facts are never dropped. ``recent_messages`` holds the last ``keep_recent_turns``
    user/assistant pairs, with tool traffic older than the last
    :data:`TOOL_DETAIL_TURNS` turns reduced to one-line notes, trimmed oldest-first until
    the estimate fits ``max_tokens``.

    The trailing user message is appended last and is never trimmed, even when it alone
    exceeds ``max_tokens`` -- refusing that turn is ``budget.check_turn``'s job, not a
    silent truncation here.
    """
    keep = max(1, int(keep_recent_turns or 1))
    summary_text = _summary_text(session)
    live = _live_messages(session)
    current = live[-1] if live and live[-1].get('role') == 'user' else None
    body = live[:-1] if current is not None else list(live)

    names = _tool_names(session.get('messages') or [])
    turns = _split_turns(body)[-keep:]
    flat: list[dict] = []
    for i, turn in enumerate(turns):
        collapse = i < len(turns) - TOOL_DETAIL_TURNS
        flat.extend(_collapse_tools(m, names) if collapse else dict(m) for m in turn)

    room = int(max_tokens) - estimate_tokens(summary_text) - (_msg_tokens(current) if current else 0)
    while flat and sum(_msg_tokens(m) for m in flat) > room:
        flat.pop(0)
    while flat and flat[0].get('role') != 'user':
        flat.pop(0)
    if current is not None:
        flat.append(dict(current))
    return summary_text, flat


def _summary_text(session: dict) -> str:
    """The pinned facts plus the rolling summary, as one prompt block."""
    parts = []
    pinned = [p for p in (session.get('pinned') or []) if str(p).strip()]
    if pinned:
        parts.append('Pinned facts:\n' + '\n'.join(f'- {p}' for p in pinned))
    if session.get('summary'):
        parts.append('Earlier in this chat:\n' + str(session['summary']))
    return '\n\n'.join(parts)


def compact(session: dict, summarize, keep_recent_turns: int = 8) -> dict:
    """Fold everything but the last ``keep_recent_turns`` pairs into ``summary``.

    ``summarize(text)`` is supplied by the runner and asks the selected model for <=400
    words of facts, decisions, open items and user preferences. A summarizer that raises
    or returns nothing leaves the session untouched: keeping a long history is always
    better than losing it.
    """
    keep = max(1, int(keep_recent_turns or 1))
    messages = list(session.get('messages') or [])
    covers = max(0, int(session.get('summary_covers') or 0))
    turns = _split_turns(messages[covers:])
    if len(turns) <= keep:
        return session
    old = [m for turn in turns[:-keep] for m in turn]
    if not old:
        return session
    rendered = '\n\n'.join(f'{m.get("role", "user")}: {_text_of(m)}' for m in old)
    if session.get('summary'):
        rendered = f'Summary so far:\n{session["summary"]}\n\nNewer turns:\n{rendered}'
    try:
        summary = summarize(rendered)
    except Exception as exc:  # noqa: BLE001 - a failed summary must not lose history
        _log.warning('agent_zero.memory: summarizer failed for %s (%s)', session.get('id'), exc)
        return session
    summary = str(summary or '').strip()
    if not summary:
        _log.warning('agent_zero.memory: empty summary for %s, keeping history', session.get('id'))
        return session
    session['summary'] = summary
    session['summary_covers'] = covers + len(old)
    return save_session(session)
