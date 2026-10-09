# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

from __future__ import annotations

from zyg_dashboard.agent_activity.sampler import _transcripts
from zyg_dashboard.agent_activity.tunables import _PROJ_DIR, _REDACT_RE, _SESS_EVENT_CAP, _TAIL_BYTES
import glob
import json
import os

try:
    import psutil
except Exception:  # pragma: no cover
    psutil = None
import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__package__)


# ── Transcript tail ─────────────────────────────────────────────────────────
def _transcript_path(sid: str) -> str:
    hit = glob.glob(os.path.join(_PROJ_DIR, '*', f'{sid}.jsonl'))
    return hit[0] if hit else ''


def _summarise_input(name: str, inp) -> str:
    """One readable line for a tool call — never the tool's full payload."""
    if not isinstance(inp, dict):
        return ''
    for key in ('command', 'file_path', 'pattern', 'path', 'url', 'prompt', 'query', 'description', 'skill'):
        v = inp.get(key)
        if isinstance(v, str) and v.strip():
            return _REDACT_RE.sub(lambda mo: mo.group(1) + '***', ' '.join(v.split()))[:200]
    return ''


def _parse_transcript_lines(raw_iter) -> list[dict]:
    """Turn transcript JSONL rows into one readable line each."""
    items: list[dict] = []
    for raw in raw_iter:
        try:
            d = json.loads(raw.decode('utf-8', 'replace'))
        except ValueError as _exc:
            _zyg_log.debug('skipping unparseable transcript row: %s', _exc)
            continue
        typ = d.get('type')
        ts = d.get('timestamp') or ''
        # A sidechain row is a subagent working under this session — worth
        # seeing (it is the session's own CPU), worth distinguishing.
        mark = '\u21b3 ' if d.get('isSidechain') else ''
        msg = d.get('message')
        if typ == 'assistant' and isinstance(msg, dict):
            for it in msg.get('content') or []:
                if not isinstance(it, dict):
                    continue
                if it.get('type') == 'tool_use':
                    arg = _summarise_input(it.get('name', ''), it.get('input'))
                    items.append(
                        {
                            'ts': ts,
                            'level': 'tool',
                            'text': mark + f'{it.get("name", "tool")}' + (f' \u2014 {arg}' if arg else ''),
                        }
                    )
                elif it.get('type') == 'text':
                    t = ' '.join(str(it.get('text') or '').split())
                    if t:
                        items.append({'ts': ts, 'level': 'say', 'text': mark + t[:220]})
        elif typ == 'user' and isinstance(msg, dict):
            c = msg.get('content')
            if isinstance(c, str) and c.strip():
                items.append({'ts': ts, 'level': 'ask', 'text': mark + ' '.join(c.split())[:220]})
    return items


def _transcript_items(sid: str, limit: int = 40) -> list[dict]:
    """Recent tool calls / replies for one session, from its own transcript.

    Read INCREMENTALLY.  These files run to tens of megabytes and grow while
    the panel polls every few seconds, so the first read takes a tail window
    and every read after that starts at the previous end-of-file offset and
    parses only what was appended.  The tail window widens on the first read
    when the window held too few rows — a session dumping large tool results
    can put 300 KB between two commands, which is how the first cut of this
    showed three lines for a session that had run dozens.
    """
    path = _transcript_path(sid)
    if not path:
        return []
    try:
        st = os.stat(path)
    except OSError:
        return []
    c = _transcripts.get(sid)
    if c and c['path'] == path and c['offset'] <= st.st_size:
        if st.st_size == c['offset']:
            return c['items'][-limit:]
        # append-only growth: parse just the new bytes, stopping at the last
        # complete line (the writer may be mid-record).
        try:
            with open(path, 'rb') as fh:
                fh.seek(c['offset'])
                chunk = fh.read(_TAIL_BYTES * 8)
        except OSError:
            return c['items'][-limit:]
        cut = chunk.rfind(b'\n')
        if cut < 0:
            return c['items'][-limit:]
        c['items'].extend(_parse_transcript_lines(chunk[:cut].splitlines()))
        del c['items'][: -_SESS_EVENT_CAP * 2]
        c['offset'] += cut + 1
        return c['items'][-limit:]

    # First read for this session: widen the window until it holds enough rows.
    window, items, offset = _TAIL_BYTES, [], 0
    for _ in range(5):
        try:
            with open(path, 'rb') as fh:
                if st.st_size > window:
                    fh.seek(-window, os.SEEK_END)
                    fh.readline()  # drop the partial first line
                offset = st.st_size
                items = _parse_transcript_lines(fh)
        except OSError:
            return []
        if len(items) >= min(limit, 60) or window >= st.st_size:
            break
        window *= 4
    _transcripts[sid] = {'path': path, 'offset': offset, 'items': items[-_SESS_EVENT_CAP * 2 :]}
    return items[-limit:]
