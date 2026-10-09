# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The conversation ledger.

Moved verbatim out of the old single-file arch_assistant.py (lines 3504-3845).
"""

from __future__ import annotations

import json
import os
import re
import shutil
import threading
import time

from zyg_workflows.arch_assistant._base import HERE, _zyg_log

# ── conversation ledger (2026-09-07) ─────────────────────────────────────────
# Every request the operator sends is written to disk TWICE: a `start` line
# the moment the job exists and an `end` line when it finishes (done /
# question / error / cancelled). A start without an end means the process
# died under it — a service restart kills the CLI and the shim with the
# server (that is exactly what happened twice on 2026-09-07: "MCP error
# -32000: Connection closed" at 21:59:55 and a silent death at 22:13:38, both
# systemd restarts). `_close_orphans()` runs at import and writes those
# `end` lines with status "killed", so the ledger never has a hole.
# Files: data/runtime/arch_assistant/conversations/<YYYY-MM-DD>.jsonl.
CONV_DIR = os.path.join(HERE, 'data', 'runtime', 'arch_assistant', 'conversations')
# 2026-09-07 night: the CLI's own transcript (every thinking block whole, every tool call and result, the
# images) is copied here when a request ends — the only complete record, and it lived in ~/.claude only.
TRANSCRIPT_DIR = os.path.join(HERE, 'data', 'runtime', 'arch_assistant', 'transcripts')
# 2026-09-08: the thinking block that is still streaming. Deltas only reached the ledger at
# content_block_stop, so a restart mid-block lost the WHOLE thought (37,705 chars in one
# measured run) — job['_think'] lives in memory and _close_orphans runs in a fresh process.
# A file here always means "unfinished": it is removed the moment the block completes.
PARTIAL_DIR = os.path.join(HERE, 'data', 'runtime', 'arch_assistant', 'partials')
PARTIAL_FLUSH_S = 2.0  # a kill loses at most this much time of a block...
PARTIAL_FLUSH_CHARS = 4096  # ...or this many characters, whichever comes first
_CLOCK = threading.Lock()


def _transcript_src(session: str) -> str:
    """Where the CLI writes a session's transcript: <config>/projects/<cwd slug>/<session>.jsonl.
    The slug is the cwd with every non-alphanumeric character turned into '-'."""
    cfg = os.environ.get('CLAUDE_CONFIG_DIR') or os.path.join(os.path.expanduser('~'), '.claude')
    return os.path.join(cfg, 'projects', re.sub(r'[^A-Za-z0-9]', '-', CLI_DIR), f'{session}.jsonl')


def _archive_transcript(session: str) -> str | None:
    """Copy the CLI transcript of `session` into TRANSCRIPT_DIR (re-copied when it grew, e.g. a resumed
    conversation). Returns the archive path, or None when there is nothing to copy. Never raises."""
    if not session or not _is_uuid(str(session)):
        return None
    src = _transcript_src(session)
    try:
        if not os.path.exists(src):
            return None
        os.makedirs(TRANSCRIPT_DIR, exist_ok=True)
        dst = os.path.join(TRANSCRIPT_DIR, f'{session}.jsonl')
        if (
            not os.path.exists(dst)
            or os.path.getsize(dst) != os.path.getsize(src)
            or os.path.getmtime(dst) < os.path.getmtime(src)
        ):
            shutil.copy2(src, dst)
        return dst
    except Exception as e:  # noqa: BLE001
        _zyg_log.info(f'[arch_assistant] transcript archive failed: {e!r}')
        return None


def _conv_path(day: str = '') -> str:
    return os.path.join(CONV_DIR, (day or time.strftime('%Y-%m-%d')) + '.jsonl')


def _conv_write(entry: dict) -> None:
    """Append one line. Never raises — a ledger must not break a drawing."""
    try:
        os.makedirs(CONV_DIR, exist_ok=True)
        entry = {'ts': time.strftime('%Y-%m-%dT%H:%M:%S'), **entry}
        with _CLOCK:
            with open(_conv_path(), 'a', encoding='utf-8') as fh:
                fh.write(json.dumps(entry, ensure_ascii=False, default=str) + '\n')
    except Exception as e:  # noqa: BLE001
        _zyg_log.info(f'[arch_assistant] ledger write failed: {e!r}')


def _partial_path(jid: str) -> str:
    return os.path.join(PARTIAL_DIR, f'{jid}.txt')


def _partial_write(job: dict, force: bool = False) -> None:
    """Mirror the in-flight thinking block to disk, throttled, so a restart cannot take it.
    The sidecar is rewritten whole (a thought is tens of KB — cheap at this cadence) via a
    tmp + os.replace, so a reader never sees a half-written file. Never raises: a ledger
    must not break a drawing."""
    jid = str(job.get('id') or '')
    txt = job.get('_think') or ''
    if not jid or not txt:
        return
    now = time.time()
    if (
        not force
        and (now - float(job.get('_pflush') or 0)) < PARTIAL_FLUSH_S
        and (len(txt) - int(job.get('_pflushed') or 0)) < PARTIAL_FLUSH_CHARS
    ):
        return
    try:
        os.makedirs(PARTIAL_DIR, exist_ok=True)
        head = json.dumps({'id': jid, 't0': job.get('_blk_t0'), 'n': len(job.get('thoughts') or []) + 1})
        tmp = _partial_path(jid) + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as fh:
            fh.write(head + '\n' + txt)
        os.replace(tmp, _partial_path(jid))
        job['_pflush'], job['_pflushed'] = now, len(txt)
    except Exception as e:  # noqa: BLE001
        _zyg_log.info(f'[arch_assistant] partial thought write failed: {e!r}')


def _partial_clear(job_or_id) -> None:
    """Drop the sidecar: the block finished (its whole text is a `thought` line now) or the
    job ended. Leaving one behind would make _close_orphans fold a thought already recorded."""
    is_job = isinstance(job_or_id, dict)
    jid = str((job_or_id.get('id') if is_job else job_or_id) or '')
    if is_job:
        job_or_id['_pflush'] = job_or_id['_pflushed'] = 0
    if not jid:
        return
    for f in (_partial_path(jid), _partial_path(jid) + '.tmp'):
        try:
            os.remove(f)
        except OSError as _exc:
            _zyg_log.debug('partial sidecar removal skipped: %s', _exc)


def _partial_read(jid: str) -> dict | None:
    """The unfinished thinking block a killed run left behind, or None. `s` is measured to the
    last flush (mtime), so it under-reports by up to PARTIAL_FLUSH_S — the text does too."""
    f = _partial_path(jid)
    try:
        with open(f, encoding='utf-8') as fh:
            head, _, text = fh.read().partition('\n')
    except OSError:
        return None
    text = text.strip()
    if not text:
        return None
    try:
        meta = json.loads(head)
    except ValueError:
        meta = {}
    secs = 0.0
    try:
        if meta.get('t0'):
            secs = round(max(0.0, os.path.getmtime(f) - float(meta['t0'])), 1)
    except (OSError, TypeError, ValueError) as _exc:
        _zyg_log.debug('partial age not computed: %s', _exc)
    return {'s': secs, 'text': text, 'partial': True}


def _partial_sweep(folded=()) -> None:
    """Remove the sidecars just folded into a killed end, and any left over 2 days (a job whose
    day file has rolled past _close_orphans' window is never coming back)."""
    folded = set(folded or ())
    try:
        for f in os.listdir(PARTIAL_DIR):
            p = os.path.join(PARTIAL_DIR, f)
            try:
                stale = (time.time() - os.path.getmtime(p)) > 2 * 86400
            except OSError as _exc:
                _zyg_log.debug('partial sidecar stat skipped: %s', _exc)
                continue
            if f[:-4] in folded or f[:-8] in folded or stale:
                try:
                    os.remove(p)
                except OSError as _exc:
                    _zyg_log.debug('partial sidecar removal skipped: %s', _exc)
    except OSError as _exc:
        _zyg_log.debug('partial dir listing skipped: %s', _exc)


def _conv_start(job: dict) -> None:
    body = job.get('body') or {}
    doc = body.get('doc') or {}
    objs = doc.get('objects') if isinstance(doc.get('objects'), list) else []
    _conv_write(
        {
            'event': 'start',
            'id': job['id'],
            'text': str(body.get('text') or '')[:4000],
            'drawing': str(body.get('name') or doc.get('name') or ''),
            'objects': len(objs),
            'backend': job.get('backend'),
            'session_in': str(body.get('session') or '') or None,
            'state': body.get('state') or {},
            'history_turns': len(body.get('history') or []),
            'screenshot': bool(body.get('screenshot')),
        }
    )


def _conv_end(job: dict) -> None:
    _partial_clear(job)  # the request is over; an unfinished block here would outlive its job
    calls = [l for l in job.get('log', []) if re.match(r'^[a-z_]+\(', l)]
    res = job.get('result') or {}
    session = job.get('session') or job.get('_sid')
    # 2026-09-07 night: whole — thoughts (were 20 x 1500 chars), reply (4000), tool calls (60), log (60 lines).
    _conv_write(
        {
            'event': 'end',
            'id': job['id'],
            'status': job.get('status'),
            'elapsed': round(time.time() - job['t0'], 1),
            'backend': job.get('backend'),
            'model': job.get('model'),
            'session': session,
            'auth': job.get('auth'),
            'incomplete': bool(job.get('incomplete')),
            'stop': job.get('stop'),
            'draw_calls': int(job.get('_draw_calls') or 0),
            'budget': MAX_CALLS,
            'transcript': _archive_transcript(session),
            'steps': job.get('steps'),
            'usage': job.get('usage'),
            'think_s': job.get('think_s'),
            'thoughts': [{'s': t.get('s'), 'text': str(t.get('text') or '')} for t in (job.get('thoughts') or [])],
            'tool_calls': calls,
            'reply': str(job.get('reply') or ''),
            'summary': str(res.get('summary') or '') if res else None,
            'added': len(res.get('added') or []) if res else None,
            'removed': len(res.get('removed') or []) if res else None,
            'question': job.get('question'),
            'error': job.get('error'),
            'log': job.get('log', []),
        }
    )


def _close_orphans() -> int:
    """Start lines without an end line (today and yesterday) get an `end` with
    status 'killed'. Runs when the module loads, i.e. after every restart."""
    n = 0
    folded = []
    try:
        days = [time.strftime('%Y-%m-%d', time.localtime(time.time() - 86400 * k)) for k in (1, 0)]
        for day in days:
            p = _conv_path(day)
            if not os.path.exists(p):
                continue
            starts, ends, thoughts, sessions = {}, set(), {}, {}
            with open(p, encoding='utf-8') as fh:
                for line in fh:
                    try:
                        e = json.loads(line)
                    except ValueError as _exc:
                        _zyg_log.debug('non-JSON conversation log line skipped: %s', _exc)
                        continue
                    if e.get('event') == 'start':
                        starts[e.get('id')] = e
                    elif e.get('event') == 'end':
                        ends.add(e.get('id'))
                    elif e.get('event') == 'thought':  # written as each thought ended — they survive the kill
                        thoughts.setdefault(e.get('id'), []).append({'s': e.get('s'), 'text': e.get('text') or ''})
                    elif e.get('event') == 'session':
                        sessions[e.get('id')] = e.get('session')
            for jid, e in starts.items():
                if jid in ends:
                    continue
                th = list(thoughts.get(jid) or [])
                part = _partial_read(jid)  # 2026-09-08: the block the kill cut mid-stream
                if part:
                    th.append(part)
                    folded.append(jid)
                _conv_write(
                    {
                        'event': 'end',
                        'id': jid,
                        'status': 'killed',
                        'started': e.get('ts'),
                        'day': day,
                        'error': 'the server restarted (or crashed) while the assistant was working — '
                        'the CLI and its tools died with it; nothing was injected'
                        + (' · the last thought was cut mid-stream and is kept as partial' if part else ''),
                        'text': e.get('text', ''),
                        'session': sessions.get(jid),
                        'transcript': _archive_transcript(sessions.get(jid) or ''),
                        'partial_thought': bool(part),
                        'thoughts': th,
                        'think_s': round(sum(float(t.get('s') or 0) for t in th), 1),
                    }
                )
                n += 1
    except Exception as e:  # noqa: BLE001
        _zyg_log.info(f'[arch_assistant] orphan close failed: {e!r}')
    _partial_sweep(folded)
    if n:
        _zyg_log.info(f'[arch_assistant] ledger: closed {n} conversation(s) killed by the last restart')
    return n


def conversations(n: int = 50, day: str = '') -> dict:
    """GET /assistant/log?n=&day= — the last n conversations, start + end joined."""
    p = _conv_path(day)
    rows = {}
    order = []
    if os.path.exists(p):
        with open(p, encoding='utf-8') as fh:
            for line in fh:
                try:
                    e = json.loads(line)
                except ValueError as _exc:
                    _zyg_log.debug('non-JSON conversation log line skipped: %s', _exc)
                    continue
                jid = e.get('id')
                if e.get('event') == 'start':
                    rows[jid] = {
                        'id': jid,
                        'started': e.get('ts'),
                        'text': e.get('text'),
                        'drawing': e.get('drawing'),
                        'objects': e.get('objects'),
                        'session_in': e.get('session_in'),
                    }
                    order.append(jid)
                elif e.get('event') == 'end' and jid in rows:
                    rows[jid].update({k: v for k, v in e.items() if k not in ('event', 'id', 'text')})
                    rows[jid]['ended'] = e.get('ts')
                elif e.get('event') == 'end':
                    rows[jid] = dict(e, started=e.get('started'), ended=e.get('ts'))
                    order.append(jid)
                elif e.get('event') == 'thought' and jid in rows:  # per-thought lines, for a row without an end yet
                    rows[jid].setdefault('_thoughts', []).append({'s': e.get('s'), 'text': e.get('text') or ''})
                elif e.get('event') == 'session' and jid in rows:
                    rows[jid]['session'] = e.get('session')
                    rows[jid].setdefault('transcript', e.get('transcript'))
    for r in rows.values():
        th = r.pop('_thoughts', None)
        if th and not r.get('thoughts'):  # still running, or killed before the ledger carried thoughts
            r['thoughts'] = th
            r.setdefault('think_s', round(sum(float(t.get('s') or 0) for t in th), 1))
    out = [rows[j] for j in order][-max(1, min(int(n or 50), 500)) :]
    return {'ok': True, 'day': day or time.strftime('%Y-%m-%d'), 'file': p, 'count': len(out), 'conversations': out}


def active_jobs() -> dict:
    """GET /assistant/active — what a restart would kill."""
    live = [
        {
            'id': j['id'],
            'status': j['status'],
            'elapsed': round(time.time() - j['t0'], 1),
            'text': str((j.get('body') or {}).get('text') or '')[:120],
        }
        for j in JOBS.values()
        if j.get('status') in ('running', 'need_client')
    ]
    return {'ok': True, 'running': len(live), 'jobs': live}


# Imported here, at the foot of the module, because these names are used only inside
# function bodies and their modules import this one back: by this line every name
# above is already bound, so the call-time cycle resolves either way round.
from zyg_workflows.arch_assistant.config import (  # noqa: E402
    CLI_DIR,
    MAX_CALLS,
)
from zyg_workflows.arch_assistant.cli_backend import _is_uuid  # noqa: E402
from zyg_workflows.arch_assistant.jobs import JOBS  # noqa: E402
