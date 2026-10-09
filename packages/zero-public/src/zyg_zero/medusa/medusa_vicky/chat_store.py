# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""medusa_vicky.chat_store — the operator's chats on disk, the picture gallery and the ledger backfill.

Lines 694-1152 of the original medusa_vicky.py, moved verbatim
(2026-10-07 split). No logic changed.
"""

from __future__ import annotations

from zyg_workflows import paths
import json
import os
import re
import threading
import time
import uuid
import logging as _zyg_logging

from .constants import (
    CHAT_DIR,
    CHAT_KEEP_MESSAGES,
    CHAT_TITLE_MAX,
    CONV_DIR,
    CURRENT_FILE,
    ENGINES,
    RUNTIME_DIR,
)

from .cli import (
    _engine,
    _is_uuid,
)

# The single-file module logged under its own module name; __package__ is
# that same dotted name now that the module is a package, so the logger's
# name is unchanged.
_zyg_log = _zyg_logging.getLogger(__package__)


# ── chat store ─────────────────────────────────────────────────
# The ledger above is an append-only AUDIT trail (one line per event, by day).
# This is the other thing entirely: the operator's chats, one file each, read
# back by the GUI so a browser refresh reopens the conversation instead of
# losing it.
#
# Two different memories live in a chat record and both matter:
#   - ``messages`` is what the OPERATOR sees when the panel reloads.
#   - ``session`` is the Claude CLI session id, which is what VICKY remembers:
#     resuming it hands the subprocess its own transcript. A chat with its
#     messages restored but no session would look continuous and answer as a
#     stranger, so the two are always written together.
#
# Ids are 12 hex chars and every path is built through _chat_path(), which
# refuses anything else — a chat id arrives from the browser, so it is never
# pasted into a path unchecked.
_CHAT_ID_RE = re.compile(r'^[0-9a-f]{12}$')
_CHAT_LOCK = threading.Lock()
_CHAT_CACHE: dict[str, tuple[float, dict]] = {}


def _valid_chat_id(cid) -> str:
    cid = str(cid or '').strip().lower()
    return cid if _CHAT_ID_RE.match(cid) else ''


def _chat_path(cid: str) -> str:
    cid = _valid_chat_id(cid)
    if not cid:
        raise ValueError('bad chat id')
    return os.path.join(CHAT_DIR, cid + '.json')


def _chat_title_from(text: str) -> str:
    t = ' '.join(str(text or '').split())
    if len(t) > CHAT_TITLE_MAX:
        t = t[: CHAT_TITLE_MAX - 1].rstrip() + '\u2026'
    return t or 'New chat'


def _chat_read(cid: str) -> dict | None:
    """One chat off disk, mtime-cached (the GUI lists chats on every load)."""
    try:
        path = _chat_path(cid)
        mt = os.path.getmtime(path)
    except (ValueError, OSError):
        return None
    hit = _CHAT_CACHE.get(cid)
    if hit and hit[0] == mt:
        return hit[1]
    try:
        with open(path, encoding='utf-8') as fh:
            chat = json.load(fh)
    except (OSError, ValueError):
        return None
    if not isinstance(chat, dict):
        return None
    chat.setdefault('id', cid)
    chat.setdefault('messages', [])
    # Chats written before the engine switch existed are Vicky's by definition.
    chat.setdefault('engine', 'claude')
    _CHAT_CACHE[cid] = (mt, chat)
    return chat


def _chat_write(chat: dict) -> dict:
    """Atomic write (tmp + os.replace) so a reader never sees half a chat."""
    cid = _valid_chat_id(chat.get('id'))
    if not cid:
        raise ValueError('bad chat id')
    chat['updated'] = time.strftime('%Y-%m-%dT%H:%M:%S')
    msgs = chat.get('messages') or []
    if len(msgs) > CHAT_KEEP_MESSAGES:
        # Trim the OLDEST messages only. Vicky's own recall is the CLI session,
        # not this list, so trimming the display transcript never costs her
        # context — it only shortens what the panel scrolls back through.
        chat['messages'] = msgs[-CHAT_KEEP_MESSAGES:]
        chat['trimmed'] = True
    os.makedirs(CHAT_DIR, exist_ok=True)
    path = _chat_path(cid)
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as fh:
        json.dump(chat, fh, ensure_ascii=False, indent=1, default=str)
    os.replace(tmp, path)
    try:
        _CHAT_CACHE[cid] = (os.path.getmtime(path), chat)
    except OSError:
        _CHAT_CACHE.pop(cid, None)
    return chat


def _chat_summary(chat: dict) -> dict:
    msgs = chat.get('messages') or []
    last = ''
    for m in reversed(msgs):
        if (m.get('text') or '').strip():
            last = ' '.join(str(m['text']).split())[:120]
            break
    return {
        'id': chat.get('id'),
        'title': chat.get('title') or 'New chat',
        'created': chat.get('created'),
        'updated': chat.get('updated'),
        'messages': len(msgs),
        'session': chat.get('session') or None,
        'engine': _engine(chat.get('engine')),
        'preview': last,
    }


def chat_new(title: str = '', engine: str = '') -> dict:
    chat = {
        'id': uuid.uuid4().hex[:12],
        'title': title or 'New chat',
        'created': time.strftime('%Y-%m-%dT%H:%M:%S'),
        'session': None,
        'engine': _engine(engine),
        'messages': [],
    }
    _chat_write(chat)
    set_current_chat(chat['id'])
    return chat


def chat_list() -> list[dict]:
    out: list[dict] = []
    try:
        names = os.listdir(CHAT_DIR)
    except OSError:
        return out
    for name in names:
        if not name.endswith('.json'):
            continue
        chat = _chat_read(name[:-5])
        if chat:
            out.append(_chat_summary(chat))
    out.sort(key=lambda c: str(c.get('updated') or c.get('created') or ''), reverse=True)
    return out


# Where the still service writes a rendered picture. The chat store points at
# files in here; STILLS_DIR is only read to catch pictures whose chat was
# deleted, so they still show up in the gallery instead of vanishing.
STILLS_DIR = os.environ.get('ZYG_MEDUSA_STILLS_DIR') or str(paths.ZYG_OUTPUT_ROOT / 'video_studio' / '_stills')


def chat_pictures() -> dict:
    """Every picture a chat delivered, newest first, across ALL saved chats.

    A picture lives in ONE chat bubble, behind the chat dropdown, so once a
    few chats exist the operator has no way to see what was made without
    reopening each one. This walks the chat store (the `images` the tool
    recorded on a message - never anything the model said) and adds any
    Medusa-flagged still on disk that no chat references any more (its chat
    was deleted). Missing files are reported, not hidden, so a picture that
    was removed from disk shows as gone rather than silently dropping out.
    """
    out: list[dict] = []
    seen: set[str] = set()
    try:
        names = [n for n in os.listdir(CHAT_DIR) if n.endswith('.json')]
    except OSError:
        names = []
    for name in names:
        chat = _chat_read(name[:-5])
        if not chat:
            continue
        title = chat.get('title') or 'New chat'
        for m in chat.get('messages') or []:
            for im in m.get('images') or []:
                path = str(im.get('path') or '')
                if not path:
                    continue
                seen.add(path)
                out.append(
                    {
                        'path': path,
                        'name': im.get('name') or os.path.basename(path),
                        'prompt': im.get('prompt') or '',
                        'ts': m.get('ts') or '',
                        'engine': _engine(m.get('engine')),
                        'chat': chat.get('id'),
                        'chat_title': title,
                        'exists': os.path.isfile(path),
                    }
                )
    # Orphans: rendered for Medusa, but the chat that asked for it is gone.
    try:
        for n in os.listdir(STILLS_DIR):
            if not n.endswith('.json'):
                continue
            base = os.path.join(STILLS_DIR, n[:-5])
            png = base + '.png'
            if png in seen or not os.path.isfile(png):
                continue
            try:
                with open(os.path.join(STILLS_DIR, n), encoding='utf-8') as fh:
                    meta = json.load(fh)
            except (OSError, ValueError) as _exc:
                _zyg_log.debug('suppressed %s: %s', type(_exc).__name__, _exc)
                continue
            if not meta.get('medusa'):
                continue
            seen.add(png)
            out.append(
                {
                    'path': png,
                    'name': os.path.basename(png),
                    'prompt': meta.get('prompt') or '',
                    'ts': time.strftime('%Y-%m-%dT%H:%M:%S', time.localtime(os.path.getmtime(png))),
                    'engine': '',
                    'chat': None,
                    'chat_title': '(chat deleted)',
                    'exists': True,
                }
            )
    except OSError as _exc:
        _zyg_log.debug('suppressed %s: %s', type(_exc).__name__, _exc)
    out.sort(key=lambda i: str(i.get('ts') or ''), reverse=True)
    missing = sum(1 for i in out if not i.get('exists'))
    return {'ok': True, 'pictures': out, 'count': len(out), 'missing': missing}


def chat_append(cid: str, msg: dict) -> dict | None:
    with _CHAT_LOCK:
        chat = _chat_read(cid)
        if chat is None:
            return None
        msg = {'ts': time.strftime('%Y-%m-%dT%H:%M:%S'), **msg}
        chat.setdefault('messages', []).append(msg)
        if msg.get('role') == 'user' and chat.get('title') in (None, '', 'New chat'):
            chat['title'] = _chat_title_from(msg.get('text'))
        return _chat_write(chat)


def chat_set_session(cid: str, session: str) -> None:
    """Record the CLI session id — this is the half of a chat that is VICKY's
    memory rather than the operator's."""
    session = str(session or '').strip()
    if not _is_uuid(session):
        return
    with _CHAT_LOCK:
        chat = _chat_read(cid)
        if chat is not None and chat.get('session') != session:
            chat['session'] = session
            _chat_write(chat)


def chat_set_engine(cid: str, engine: str) -> dict | None:
    """Remember which assistant this chat is talking to.

    Stored server-side next to the session id, so a refresh or a second browser
    reopens the chat on the engine that has its memory rather than on whatever
    the dropdown happened to default to."""
    with _CHAT_LOCK:
        chat = _chat_read(cid)
        if chat is None:
            return None
        want = _engine(engine)
        if chat.get('engine') == want:
            return chat
        chat['engine'] = want
        return _chat_write(chat)


def chat_rename(cid: str, title: str) -> dict | None:
    with _CHAT_LOCK:
        chat = _chat_read(cid)
        if chat is None:
            return None
        chat['title'] = _chat_title_from(title) if str(title or '').strip() else 'New chat'
        return _chat_write(chat)


def chat_delete(cid: str) -> bool:
    cid = _valid_chat_id(cid)
    if not cid:
        return False
    with _CHAT_LOCK:
        try:
            os.remove(_chat_path(cid))
        except (ValueError, OSError):
            return False
        _CHAT_CACHE.pop(cid, None)
    if current_chat_id() == cid:
        set_current_chat('')
    return True


def chat_delete_all() -> int:
    """Clear the whole chat history. The day-by-day audit ledger under
    conversations/ is deliberately NOT touched — clearing the panel is a
    display decision, not a licence to erase the record of what ran."""
    n = 0
    for c in chat_list():
        if chat_delete(c['id']):
            n += 1
    set_current_chat('')
    return n


def current_chat_id() -> str:
    try:
        with open(CURRENT_FILE, encoding='utf-8') as fh:
            return _valid_chat_id((json.load(fh) or {}).get('chat'))
    except (OSError, ValueError):
        return ''


def set_current_chat(cid: str) -> None:
    cid = _valid_chat_id(cid)
    try:
        os.makedirs(RUNTIME_DIR, exist_ok=True)
        tmp = CURRENT_FILE + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as fh:
            json.dump({'chat': cid or None}, fh)
        os.replace(tmp, CURRENT_FILE)
    except OSError as e:  # noqa: BLE001
        _zyg_log.info(f'[medusa_vicky] current-chat write failed: {e!r}')


def open_chat(cid: str = '') -> dict:
    """The chat the panel should show: the one asked for, else the last one
    used, else a fresh one. Always leaves a real chat on disk."""
    chat = _chat_read(_valid_chat_id(cid)) if _valid_chat_id(cid) else None
    if chat is None:
        chat = _chat_read(current_chat_id())
    if chat is None:
        # No pointer (first run, or the open chat was just deleted): fall back
        # to the most recent surviving chat. Minting a fresh empty one here
        # would answer a delete with a blank panel AND a new file to delete.
        recent = chat_list()
        if recent:
            chat = _chat_read(recent[0]['id'])
    if chat is None:
        chat = chat_new()
    set_current_chat(chat['id'])
    return chat


def chat_markdown(chat: dict) -> str:
    """A chat as a Markdown file — what the Save button downloads."""
    lines = [
        f'# {chat.get("title") or "Vicky chat"}',
        '',
        f'*Vicky · Medusa · started {chat.get("created") or "?"}'
        f'{", last message " + chat["updated"] if chat.get("updated") else ""}*',
        '',
    ]
    if chat.get('trimmed'):
        lines += ['*(older messages were trimmed from this transcript)*', '']
    for m in chat.get('messages') or []:
        who = {'user': 'Operator', 'vicky': 'Vicky', 'error': 'Error'}.get(m.get('role'), m.get('role') or '?')
        if m.get('role') == 'vicky':
            who = ENGINES[_engine(m.get('engine'))]['name']
        meta = ''
        if m.get('elapsed'):
            meta = f' · {m["elapsed"]}s'
            if m.get('think_s'):
                meta += f', {m["think_s"]}s thinking'
        lines += [f'### {who} — {m.get("ts") or ""}{meta}', '', str(m.get('text') or ''), '']
        for im in m.get('images') or []:
            # A saved transcript should still point at the picture it delivered.
            lines += [f'![{im.get("name") or "render"}]({im.get("path") or ""})', '']
    return '\n'.join(lines).rstrip() + '\n'


def _backfill_chats_from_ledger() -> int:
    """One-off: rebuild chats from the audit ledger the first time this runs.

    Vicky answered real questions before there was a chat store; grouping the
    ledger's completed turns by CLI session id reconstructs those conversations
    exactly, so the feature does not land by throwing the operator's existing
    history away. Skipped as soon as any chat file exists.
    """
    try:
        os.makedirs(CHAT_DIR, exist_ok=True)
        if any(n.endswith('.json') for n in os.listdir(CHAT_DIR)):
            return 0
        days = sorted(n for n in os.listdir(CONV_DIR) if n.endswith('.jsonl')) if os.path.isdir(CONV_DIR) else []
    except OSError:
        return 0

    starts: dict[str, dict] = {}
    turns: list[dict] = []
    for day in days:
        try:
            with open(os.path.join(CONV_DIR, day), encoding='utf-8') as fh:
                for line in fh:
                    try:
                        e = json.loads(line)
                    except ValueError as _exc:
                        _zyg_log.debug('suppressed %s: %s', type(_exc).__name__, _exc)
                        continue
                    if e.get('event') == 'start':
                        starts[e.get('id')] = e
                    elif e.get('event') == 'end':
                        st = starts.pop(e.get('id'), {})
                        turns.append(
                            {
                                **e,
                                'prompt': st.get('text') or e.get('text') or '',
                                'started': st.get('ts') or e.get('ts'),
                            }
                        )
        except OSError as _exc:
            _zyg_log.debug('suppressed %s: %s', type(_exc).__name__, _exc)
            continue

    by_session: dict[str, list[dict]] = {}
    for t in turns:
        key = str(t.get('session') or '') or f'orphan:{t.get("id")}'
        by_session.setdefault(key, []).append(t)

    made = 0
    for key, group in by_session.items():
        group.sort(key=lambda t: str(t.get('started') or t.get('ts') or ''))
        msgs: list[dict] = []
        for t in group:
            if (t.get('prompt') or '').strip():
                msgs.append({'ts': t.get('started'), 'role': 'user', 'text': t['prompt']})
            if (t.get('reply') or '').strip():
                msgs.append(
                    {
                        'ts': t.get('ts'),
                        'role': 'vicky',
                        'text': t['reply'],
                        'elapsed': t.get('elapsed'),
                        'think_s': t.get('think_s'),
                        'usage': t.get('usage'),
                        'job': t.get('id'),
                    }
                )
            elif t.get('status') in ('error', 'killed'):
                msgs.append(
                    {'ts': t.get('ts'), 'role': 'error', 'text': str(t.get('error') or t.get('status') or 'failed')}
                )
        if not msgs:
            continue
        chat = {
            'id': uuid.uuid4().hex[:12],
            'title': _chat_title_from(next((m['text'] for m in msgs if m['role'] == 'user'), '')),
            'created': group[0].get('started') or group[0].get('ts'),
            'session': key if _is_uuid(key) else None,
            'messages': msgs,
            'restored_from_ledger': True,
        }
        try:
            _chat_write(chat)
            made += 1
        except (OSError, ValueError) as _exc:
            _zyg_log.debug('suppressed %s: %s', type(_exc).__name__, _exc)
            continue
    if made:
        newest = max(chat_list(), key=lambda c: str(c.get('updated') or ''), default=None)
        if newest:
            set_current_chat(newest['id'])
        _zyg_log.info(f'[medusa_vicky] chat store: restored {made} conversation(s) from the audit ledger')
    return made
