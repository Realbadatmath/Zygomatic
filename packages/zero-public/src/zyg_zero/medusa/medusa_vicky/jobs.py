# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""medusa_vicky.jobs — uploads, the job table, the workflow beacon, the turn worker and the HTTP glue.

Lines 1155-1612 of the original medusa_vicky.py, moved verbatim
(2026-10-07 split). No logic changed.
"""

from __future__ import annotations

import json
import medusa_victor
import os
import re
import threading
import time
import uuid
import logging as _zyg_logging

from .constants import (
    CLI_BIN,
    DEFAULT_ENGINE,
    ENGINES,
    RUNTIME_DIR,
    UPLOAD_DIR,
    UPLOAD_MAX_AGE,
)

from .cli import (
    _add_thought,
    _cli_model,
    _engine,
    _kill,
    _run_cli,
    cli_available,
    cli_login_present,
    engine_available,
    engine_info,
    system_prompt,
    vicky_rules,
)

from .ledger import (
    _close_orphans,
    _conv_end,
    _conv_start,
)

from .chat_store import (
    _backfill_chats_from_ledger,
    _chat_read,
    _valid_chat_id,
    chat_append,
    chat_delete,
    chat_delete_all,
    chat_list,
    chat_new,
    chat_pictures,
    chat_rename,
    chat_set_engine,
    chat_set_session,
    current_chat_id,
    open_chat,
)

# The single-file module logged under its own module name; __package__ is
# that same dotted name now that the module is a package, so the logger's
# name is unchanged.
_zyg_log = _zyg_logging.getLogger(__package__)


# ── uploads ──────────────────────────────────────────────────────────────────
# Videos and other binary files that cannot be base64-encoded inside the JSON
# body are saved here.  The directory is inside RUNTIME_DIR so it is fenced
# within Medusa's own folder tree, which Vicky's Read/Write/Bash rules already
# cover.  Old files are purged on startup (UPLOAD_MAX_AGE) so the folder does
# not grow without bound.

_SAFE_FNAME = re.compile(r'[^a-zA-Z0-9._-]')
_ALLOWED_IMAGE_TYPES = frozenset({'image/jpeg', 'image/png', 'image/gif', 'image/webp'})
_IMAGE_B64_MAX = 20 * 1024 * 1024  # ~15 MB decoded — above Claude's own limit anyway


def save_upload(filename: str, data: bytes) -> str:
    """Write binary data to UPLOAD_DIR with a uuid prefix and return the path."""
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    safe = _SAFE_FNAME.sub('_', str(filename or 'upload'))[:80] or 'upload'
    name = uuid.uuid4().hex[:8] + '_' + safe
    path = os.path.join(UPLOAD_DIR, name)
    with open(path, 'wb') as fh:
        fh.write(data)
    return path


def _purge_old_uploads() -> None:
    try:
        if not os.path.isdir(UPLOAD_DIR):
            return
        cutoff = time.time() - UPLOAD_MAX_AGE
        for f in os.listdir(UPLOAD_DIR):
            p = os.path.join(UPLOAD_DIR, f)
            try:
                if os.path.getmtime(p) < cutoff:
                    os.remove(p)
            except OSError as _exc:
                _zyg_log.debug('suppressed %s: %s', type(_exc).__name__, _exc)
    except OSError as _exc:
        _zyg_log.debug('suppressed %s: %s', type(_exc).__name__, _exc)


def _validate_attachments(raw: list) -> list:
    """Sanitize and cap the attachment list from the POST body.

    Images are validated by MIME type and data length.  Video paths must be
    real files inside UPLOAD_DIR — this prevents a forged path from letting a
    rogue request tell Vicky about an arbitrary file outside the uploads folder.
    """
    out: list[dict] = []
    for a in (raw or [])[:10]:  # hard cap: 10 attachments per message
        t = str(a.get('type') or '')
        if t == 'image':
            mime = str(a.get('mime_type') or '')
            b64 = str(a.get('data_b64') or '')
            name = str(a.get('name') or 'image')[:200]
            if mime not in _ALLOWED_IMAGE_TYPES:
                continue
            if not b64 or len(b64) > _IMAGE_B64_MAX:
                continue
            out.append({'type': 'image', 'mime_type': mime, 'data_b64': b64, 'name': name})
        elif t == 'video':
            path = str(a.get('path') or '')
            name = str(a.get('name') or 'video')[:200]
            if not path:
                continue
            try:
                real = os.path.realpath(path)
                upload_real = os.path.realpath(UPLOAD_DIR)
                if not real.startswith(upload_real + os.sep):
                    continue
                if not os.path.isfile(real):
                    continue
            except OSError as _exc:
                _zyg_log.debug('suppressed %s: %s', type(_exc).__name__, _exc)
                continue
            out.append({'type': 'video', 'path': real, 'name': name})
    return out


# ── jobs ────────────────────────────────────────────────────────────────────
JOBS: dict[str, dict] = {}
_JLOCK = threading.Lock()
_JOB_TTL = 3600


def _gc():
    now = time.time()
    with _JLOCK:
        for k in [k for k, j in JOBS.items() if now - j['t0'] > _JOB_TTL]:
            JOBS.pop(k, None)


def _job_view(j: dict) -> dict:
    out = {
        k: j.get(k)
        for k in (
            'id',
            'chat',
            'engine',
            'status',
            'phase',
            'error',
            'steps',
            'usage',
            'reply',
            'session',
            'model',
            'thinking',
            'think_s',
            'reply_live',
            'auth',
        )
    }
    # Pictures this turn actually rendered (medusa_victor._record_image writes
    # them). Reported while the turn is still running so the panel can show the
    # image the moment it exists, rather than when the model stops talking.
    out['images'] = j.get('images') or []
    out['thoughts_n'] = len(j.get('thoughts') or [])
    if j['status'] in ('done', 'error'):
        out['thoughts'] = j.get('thoughts') or []
    out['log'] = j['log'][-40:]
    out['elapsed'] = round(time.time() - j['t0'], 1)
    return out


def start_job(body: dict) -> dict:
    """POST /api/vicky/start — begin one request. Returns {ok, id}."""
    _gc()
    text = str(body.get('text') or '').strip()
    attachments = _validate_attachments(body.get('attachments') or [])
    body['attachments'] = attachments  # put back sanitised copy
    if not text and not attachments:
        return {'ok': False, 'error': 'empty request'}
    if not text:
        # Build a placeholder so the ledger and chat transcript record something
        text = ' '.join(f'[{a["name"]}]' for a in attachments)
        body['text'] = text
    # Bind the turn to a chat BEFORE it runs: the chat supplies the CLI session
    # id (Vicky's own memory of this conversation), and the user message is on
    # disk before the subprocess starts, so a crash mid-answer still leaves the
    # panel showing what was asked.
    chat = open_chat(body.get('chat'))
    cid = chat['id']
    # Which assistant answers: what the panel's switcher sent, else the engine
    # this chat was last held on. Written back to the chat so the next reader
    # (a refresh, another tab) reopens on the same one.
    engine = _engine(body.get('engine') or chat.get('engine'))
    # Refuse a switched-off engine HERE rather than letting the turn start and
    # fail downstream: the user message has not been appended yet, so the chat is
    # left exactly as it was and the operator can flip engines and resend.
    ok, why = engine_available(engine)
    if not ok:
        raise ValueError(f'{ENGINES[engine]["label"]} cannot answer: {why}')
    body['engine'] = engine
    if engine != chat.get('engine'):
        chat_set_engine(cid, engine)
        chat = _chat_read(cid) or chat
    if not str(body.get('session') or '').strip():
        body['session'] = chat.get('session') or ''
    chat_append(cid, {'role': 'user', 'text': text})

    jid = uuid.uuid4().hex[:12]
    job = {
        'id': jid,
        'chat': cid,
        'engine': engine,
        'status': 'running',
        'phase': 'working',
        'log': [],
        't0': time.time(),
        'steps': 0,
        'error': None,
        'reply': '',
        'cancel': False,
        'usage': None,
        'session': None,
        'model': None,
        'thinking': '',
        'thoughts': [],
        'think_s': 0.0,
        'reply_live': '',
        'auth': None,
        '_ev': threading.Event(),
        '_proc': None,
        '_stream': None,
        'body': body,
    }
    with _JLOCK:
        JOBS[jid] = job
    _conv_start(job)
    threading.Thread(target=_run, args=(job,), name=f'vicky-{jid}', daemon=True).start()
    _beacon_pulse()
    return {'ok': True, 'id': jid, 'chat': cid, 'engine': engine}


def job_status(jid: str) -> dict:
    j = JOBS.get(str(jid or ''))
    if not j:
        return {'ok': False, 'error': 'no such job'}
    v = _job_view(j)
    v['ok'] = True
    return v


def cancel_job(body: dict) -> dict:
    j = JOBS.get(str(body.get('id') or ''))
    if not j:
        return {'ok': False, 'error': 'no such job'}
    j['cancel'] = True
    j['_ev'].set()
    if j.get('_proc') is not None:
        _kill(j['_proc'])  # Vicky: kill the CLI subprocess
    stream = j.get('_stream')
    if stream is not None:
        # Victor: there is no child process to kill — the turn is an open HTTP
        # response being read line by line. Closing it makes that read raise,
        # and run_turn's own cancel check catches it on the next line either way.
        try:
            stream.close()
        except Exception as _exc:  # noqa: BLE001
            _zyg_log.debug('suppressed %s: %s', type(_exc).__name__, _exc)
    return {'ok': True}


def active_jobs() -> dict:
    """GET /api/vicky/active — what a medusa.service restart would kill. Check
    this is 0 before restarting."""
    live = [
        {
            'id': j['id'],
            'chat': j.get('chat'),
            'engine': j.get('engine'),
            'status': j['status'],
            'elapsed': round(time.time() - j['t0'], 1),
            'text': str((j.get('body') or {}).get('text') or '')[:120],
        }
        for j in JOBS.values()
        if j.get('status') == 'running'
    ]
    return {'ok': True, 'running': len(live), 'jobs': live}


# ── Workflow beacon (2026-09-17) ─────────────────────────────────────────────
# A request to Vicky or Victor made through this app IS a Medusa workflow
# (operator, 2026-09-17), and the Workflows board wants to show that. The board
# is served by another process (:8899 / bp_medusa on :5000) which cannot see
# JOBS, so the count is published as one small file it can stat.
#
# `ts` is refreshed every _BEACON_TICK seconds while a turn is running, and the
# reader ignores a stale file: if this service is killed mid-turn, the beacon is
# left saying "running" forever, and a board that believed it would claim a
# workflow was live for the rest of the day.
BEACON_PATH = os.path.join(RUNTIME_DIR, 'workflow_beacon.json')
_BEACON_TICK = 10.0
_beacon_thread = None


def _beacon_write() -> None:
    live = [j for j in JOBS.values() if j.get('status') == 'running']
    who = sorted({ENGINES[_engine(j.get('engine'))]['name'] for j in live})
    try:
        os.makedirs(RUNTIME_DIR, exist_ok=True)
        tmp = BEACON_PATH + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as fh:
            json.dump(
                {
                    'running': len(live),
                    'who': who,
                    'label': (' + '.join(who) + (' is working' if len(who) == 1 else ' are working')) if who else '',
                    'ts': time.time(),
                },
                fh,
            )
        os.replace(tmp, BEACON_PATH)
    except Exception as _exc:  # noqa: BLE001 — never break a turn
        _zyg_log.debug('suppressed %s: %s', type(_exc).__name__, _exc)


def _beacon_pulse() -> None:
    """Keep the beacon fresh while turns run, then stop. Started on demand so an
    idle Medusa carries no extra thread."""
    global _beacon_thread
    _beacon_write()
    if _beacon_thread is not None and _beacon_thread.is_alive():
        return

    def _loop():
        while any(j.get('status') == 'running' for j in list(JOBS.values())):
            time.sleep(_BEACON_TICK)
            _beacon_write()
        _beacon_write()  # final: running = 0

    _beacon_thread = threading.Thread(target=_loop, name='vicky-beacon', daemon=True)
    _beacon_thread.start()


def _run(job: dict):
    body = job['body']

    def log(line):
        job['log'].append(str(line)[:300])

    try:
        text = str(body['text']).strip()
        eng = ENGINES[_engine(job.get('engine'))]
        if eng['backend'] == 'ollama':
            # A local brain. The rules file is read here, fresh, exactly as it is
            # for the CLI path — the differences are which module turns it into a
            # system prompt, which brain answers, and that a local engine is
            # handed the chat itself because the transcript IS its memory (there
            # is no session to resume).
            final = medusa_victor.run_turn(
                job,
                log,
                text,
                vicky_rules(),
                body.get('attachments'),
                _chat_read(job.get('chat')),
                _add_thought,
                eng['brain'],
            )
        else:
            final = _run_cli(job, log, text, system_prompt(), body.get('attachments'))
        job['reply'] = final or job['reply'] or 'Done.'
        job['status'] = 'done'
        job['phase'] = 'done'
        log('done')
    except Exception as e:  # noqa: BLE001 — the panel shows it
        job['error'] = str(e)[:400]
        job['status'] = 'error'
        job['phase'] = 'error'
        log('error: ' + job['error'])
    finally:
        _conv_end(job)
        _chat_record_turn(job)
        _beacon_write()


def _chat_record_turn(job: dict) -> None:
    """Write this turn's outcome into the chat the panel reads back.

    The session id is saved even on a failed turn: the CLI may well have opened
    the conversation before it broke, and a follow-up should continue it rather
    than start Vicky over as a stranger.
    """
    cid = _valid_chat_id(job.get('chat'))
    if not cid:
        return
    try:
        # Only Vicky's turns carry a CLI session id. Victor's memory is the
        # message list this same function is about to append to, so there is
        # nothing to pin for him — and chat_set_session would refuse it anyway.
        if job.get('session'):
            chat_set_session(cid, job['session'])
        engine = _engine(job.get('engine'))
        # A picture the turn rendered belongs to the transcript, not just to the
        # live bubble: the operator asked for it in this chat and must still find
        # it here after a refresh. The list is written by the tool that made the
        # file, never from anything the model said about it.
        # Local backends only: the claude backend renders by curling :8899 from
        # Bash, and this module never sees what came back, so a picture made that
        # way arrives as a path in the text. Both enabled engines are local.
        images = [dict(i) for i in (job.get('images') or []) if i.get('path')]
        if job.get('status') == 'done':
            chat_append(
                cid,
                {
                    'role': 'vicky',
                    'text': str(job.get('reply') or 'Done.'),
                    'elapsed': round(time.time() - job['t0'], 1),
                    'think_s': job.get('think_s'),
                    'steps': job.get('steps'),
                    'usage': job.get('usage'),
                    'job': job.get('id'),
                    'engine': engine,
                    'model': job.get('model'),
                    **({'images': images} if images else {}),
                },
            )
        else:
            # A turn that broke AFTER the render still delivers the picture —
            # the file exists and it is what was asked for.
            chat_append(
                cid,
                {
                    'role': 'error',
                    'text': str(job.get('error') or 'the turn did not finish'),
                    'elapsed': round(time.time() - job['t0'], 1),
                    'job': job.get('id'),
                    'engine': engine,
                    **({'images': images} if images else {}),
                },
            )
    except Exception as e:  # noqa: BLE001 - never lose the turn over bookkeeping
        _zyg_log.info(f'[medusa_vicky] chat record failed: {e!r}')


# ── HTTP glue (medusa_server.py calls these) ─────────────────────────────────
PREFIX = '/api/vicky'


def handle_get(path: str, q: dict):
    if path == PREFIX + '/job':
        return job_status(q.get('id', '')), 200
    if path == PREFIX + '/active':
        return active_jobs(), 200
    if path == PREFIX + '/chats':
        return {'ok': True, 'chats': chat_list(), 'current': current_chat_id()}, 200
    if path == PREFIX + '/pictures':
        return chat_pictures(), 200
    if path == PREFIX + '/chat':
        chat = open_chat(q.get('id', ''))
        running = next((j for j in active_jobs()['jobs'] if j.get('chat') == chat['id']), None)
        return {'ok': True, 'chat': chat, 'running': running}, 200
    if path == PREFIX + '/engines':
        return {'ok': True, 'engines': engine_info(), 'default': DEFAULT_ENGINE}, 200
    if path == PREFIX + '/info':
        return {
            'ok': True,
            'default_engine': DEFAULT_ENGINE,
            'engines': engine_info(),
            'cli': {'bin': CLI_BIN, 'model': _cli_model(), 'available': cli_available(), 'login': cli_login_present()},
            # Per brain, not one blob: "is Ollama up" is no longer the whole
            # question now that two engines run on it and either model can be
            # missing on its own.
            'ollama': {k: medusa_victor.info(k) for k in medusa_victor.BRAINS},
        }, 200
    return {'error': 'not found'}, 404


def handle_post(path: str, body: dict):
    if path == PREFIX + '/start':
        out = start_job(body)
    elif path == PREFIX + '/cancel':
        out = cancel_job(body)
    elif path == PREFIX + '/chat/new':
        out = {'ok': True, 'chat': chat_new(engine=body.get('engine', ''))}
    elif path == PREFIX + '/chat/engine':
        chat = chat_set_engine(body.get('id', ''), body.get('engine', ''))
        out = {'ok': True, 'chat': chat} if chat else {'ok': False, 'error': 'no such chat'}
    elif path == PREFIX + '/chat/open':
        out = {'ok': True, 'chat': open_chat(body.get('id', ''))}
    elif path == PREFIX + '/chat/rename':
        chat = chat_rename(body.get('id', ''), body.get('title', ''))
        out = {'ok': True, 'chat': chat} if chat else {'ok': False, 'error': 'no such chat'}
    elif path == PREFIX + '/chat/delete':
        if body.get('all'):
            out = {'ok': True, 'deleted': chat_delete_all(), 'chat': open_chat()}
        elif chat_delete(body.get('id', '')):
            out = {'ok': True, 'deleted': 1, 'chat': open_chat()}
        else:
            out = {'ok': False, 'error': 'no such chat'}
    else:
        return {'error': 'not found'}, 404
    return out, (200 if out.get('ok') else 400)


_close_orphans()
_backfill_chats_from_ledger()
_purge_old_uploads()
