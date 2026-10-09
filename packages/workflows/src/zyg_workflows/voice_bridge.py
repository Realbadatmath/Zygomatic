# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""
Voice bridge — the server seam between the browser microphone and the studios
(2026-09-15).

The operator speaks into the :8899 page; the page POSTs the blob here; this
module turns it into TEXT (voice_stt), decides WHO said it (voice_ext/speaker),
turns it into ACTIONS (voice_brain), and pushes those actions down a long-lived
SSE stream to the ONE tab that holds the driver token. The tab runs each action
against the studio's own handler and POSTs an ack back.

Nothing here touches the GUI and nothing here synthesises audio: the `say` event
carries a URL (`/inspect/api/voice/ext/tts/say?text=...`) that the page fetches
when it wants to hear it.

Public seam (kanban_server mounts exactly these):
    handle_get(path, query)   -> (dict, code) | (bytes, mime, filename)
    handle_post(path, body)   -> (dict, code) | (bytes, mime, filename)
    handle_sse(handler, query)-> None, writes an event-stream on handler.wfile
    BODY_LIMIT

Extensions: voice_ext/<name>.py exporting ROUTES = {'<op>': fn(payload, method)}
are reachable at /inspect/api/voice/ext/<name>/<op> and are re-imported whenever
their file's mtime moves, so an ext lands without a server restart (the same
pattern as architecture_studio.ext_dispatch).
"""

import base64
import glob
import json
import os
import queue
import re
import threading
import time
import urllib.parse
import uuid
from collections import deque
import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)


HERE = os.path.dirname(os.path.abspath(__file__))

# Source tree: where the ext modules and their client-side .js live.
EXT_DIR = os.path.join(HERE, 'voice_ext')
# Runtime: config, the say cache, enrolled speakers, the ledger.
RUNTIME_DIR = os.path.join(HERE, 'data', 'runtime', 'voice_bridge')
SPEAKER_DIR = os.path.join(RUNTIME_DIR, 'speakers')
SAY_DIR = os.path.join(RUNTIME_DIR, 'say')
LEDGER_PATH = os.path.join(RUNTIME_DIR, 'ledger.jsonl')

for _d in (RUNTIME_DIR, SPEAKER_DIR, SAY_DIR):
    os.makedirs(_d, exist_ok=True)

# A microphone second of opus is ~6 KB, but base64 of a 30 s utterance plus the
# view context still has to fit, and the page never sends anything else this big.
BODY_LIMIT = 4_000_000

PREFIX = '/inspect/api/voice/'
SSE_PING_SECONDS = 15
MAX_REGISTRY = 2000
LEDGER_MEMORY = 200

_TOKEN_RE = re.compile(r'^[A-Za-z0-9_.:-]{1,64}$')
_EXT_NAME = re.compile(r'^[a-z0-9_]{1,48}$')

_LOCK = threading.RLock()
# token -> {'queue', 'sub', 'registry', 'view', 'hello_ts', 'last_text', 'seen'}
_DRIVERS: dict = {}
# The ledger's live tail: acks arrive after the utterance line is already on
# disk, so the entry an ack updates has to be findable in memory.
_LEDGER: deque = deque(maxlen=LEDGER_MEMORY)
_BY_ACTION: dict = {}
_TRANSCRIPTS: deque = deque(maxlen=20)
_LEDGER_LOCK = threading.Lock()

_EXT_MODS: dict = {}

REJECT_SAY = 'I only take commands from an enrolled voice'


# ── small helpers ──────────────────────────────────────────────────────────
def _now() -> float:
    return round(time.time(), 3)


def _new_id() -> str:
    return uuid.uuid4().hex[:12]


def say_url(text: str) -> str:
    """The URL the page fetches to HEAR `text`. Built, never rendered, here."""
    return PREFIX + 'ext/tts/say?text=' + urllib.parse.quote(text or '', safe='')


def _rest(path: str) -> str:
    p = (path or '').split('?', 1)[0]
    return p[len(PREFIX) :].strip('/') if p.startswith(PREFIX) else p.strip('/')


def _token(value) -> str:
    t = str(value or '').strip()
    return t if _TOKEN_RE.match(t) else ''


def _driver(token: str, create: bool = True):
    with _LOCK:
        d = _DRIVERS.get(token)
        if d is None and create:
            d = {
                'queue': queue.Queue(maxsize=500),
                'sub': 0,
                'registry': [],
                'view': '',
                'hello_ts': 0.0,
                'last_text': '',
                'seen': 0,
            }
            _DRIVERS[token] = d
        return d


def _push(token: str, event: str, data: dict) -> bool:
    """Queue one SSE event for a driver. False when the queue is full — a full
    queue means nobody has been reading for a long time, and dropping the oldest
    event would hide that."""
    d = _driver(token)
    try:
        d['queue'].put_nowait((event, data))
        return True
    except queue.Full:
        return False


# ── ledger ─────────────────────────────────────────────────────────────────
def _ledger_append(entry: dict) -> None:
    line = json.dumps(entry, separators=(',', ':'), default=str)
    with _LEDGER_LOCK:
        try:
            os.makedirs(os.path.dirname(LEDGER_PATH), exist_ok=True)
            with open(LEDGER_PATH, 'a', encoding='utf-8') as fh:
                fh.write(line + '\n')
        except OSError as _exc:
            _zyg_log.warning('ledger append to %s failed, line kept in memory only: %s', LEDGER_PATH, _exc)


def _ledger_record(entry: dict) -> None:
    """One utterance line: kept in memory (acks amend it) and on disk."""
    with _LOCK:
        if len(_LEDGER) == _LEDGER.maxlen and _LEDGER:
            for a in _LEDGER[0].get('actions') or []:
                _BY_ACTION.pop(a.get('id'), None)
        _LEDGER.append(entry)
        for a in entry.get('actions') or []:
            if a.get('id'):
                _BY_ACTION[a['id']] = entry
    _ledger_append(entry)


def _ledger_tail(n: int) -> list:
    with _LOCK:
        rows = list(_LEDGER)
    return rows[-n:] if n > 0 else rows


# ── extension modules (voice_ext/<name>.py) ────────────────────────────────
def ext_module(name: str):
    """Import voice_ext/<name>.py, re-importing it when its mtime moved."""
    if not _EXT_NAME.match(name or ''):
        raise ValueError('bad ext name')
    path = os.path.join(EXT_DIR, name + '.py')
    if not os.path.isfile(path):
        return None
    mtime = os.path.getmtime(path)
    hit = _EXT_MODS.get(name)
    if hit and hit[0] == mtime and hit[2] == path:
        return hit[1]
    import importlib.util

    spec = importlib.util.spec_from_file_location('voice_ext.' + name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    _EXT_MODS[name] = (mtime, mod, path)
    return mod


def ext_names() -> dict:
    """{name: [ops]} for every voice_ext/*.py that imports."""
    out: dict = {}
    if not os.path.isdir(EXT_DIR):
        return out
    for f in sorted(os.listdir(EXT_DIR)):
        if not f.endswith('.py') or f.startswith('_'):
            continue
        name = f[:-3]
        try:
            mod = ext_module(name)
            out[name] = sorted((getattr(mod, 'ROUTES', {}) or {}).keys())
        except Exception as e:  # noqa: BLE001
            out[name] = ['ERROR: %s' % (str(e)[:120],)]
    return out


def ext_dispatch(method: str, rest: str, payload: dict):
    """'<name>/<op>' -> the op's result: a dict, or (bytes, mime, filename)."""
    parts = (rest or '').strip('/').split('/')
    if len(parts) == 1 and parts[0] == '':
        return {'ok': True, 'ext': ext_names()}
    if len(parts) != 2:
        return {'error': 'use /ext/<name>/<op>', 'code': 404}
    name, op = parts
    if not _EXT_NAME.match(name) or not _EXT_NAME.match(op):
        return {'error': 'bad ext or op name', 'code': 404}
    mod = ext_module(name)
    if mod is None:
        return {'error': f'no voice extension {name}', 'code': 404}
    fn = (getattr(mod, 'ROUTES', {}) or {}).get(op)
    if fn is None:
        return {'error': f'{name} has no op {op}', 'code': 404}
    return fn(payload if isinstance(payload, dict) else {}, method)


def bundle_js() -> str:
    """voice_ext/*.js concatenated in name order behind the VB registry.

    Loaded by ONE <script> placed BEFORE the studio script, so a file here may
    only REGISTER at top level; anything touching the DOM or a studio global
    belongs in run()/el() or a VB.ready callback.
    """
    parts = [
        'window.VB = window.VB || {actions:{}, aliases:{}, ready:[], views:{}};',
        '/* voice_ext bundle — generated per request */',
    ]
    for f in sorted(glob.glob(os.path.join(EXT_DIR, '*.js'))):
        base = os.path.basename(f)
        try:
            with open(f, encoding='utf-8') as fh:
                parts.append(
                    f'/* ── {base} ── */\ntry {{\n'
                    + fh.read()
                    + f'\n}} catch (e) {{ console.error("voice_ext {base}", e); }}'
                )
        except OSError as e:
            parts.append(f'console.error("voice_ext {base} unreadable: {e}");')
    return '\n'.join(parts)


# ── speaker gate ───────────────────────────────────────────────────────────
def _speakers_enrolled(mod) -> bool:
    fn = (getattr(mod, 'ROUTES', {}) or {}).get('list')
    if fn is not None:
        try:
            res = fn({}, 'GET')
        except Exception:  # noqa: BLE001
            res = None
        if isinstance(res, dict):
            for key in ('speakers', 'enrolled', 'names'):
                v = res.get(key)
                if isinstance(v, (list, tuple, dict)):
                    return len(v) > 0
                if isinstance(v, int) and not isinstance(v, bool):
                    return v > 0
    try:
        return any(not f.startswith('.') for f in os.listdir(SPEAKER_DIR))
    except OSError:
        return False


def _verify_speaker(audio_b64: str, mime: str, text: str):
    """{'name','score','accepted'} — or None when there is no gate to apply.

    No speaker extension, or nobody enrolled, means the gate is not armed: the
    bridge obeys whoever is at the microphone. That is deliberate — a bridge
    that refuses every command until someone enrols cannot be enrolled by voice.
    """
    try:
        mod = ext_module('speaker')
    except Exception:  # noqa: BLE001
        return None
    if mod is None or not _speakers_enrolled(mod):
        return None
    fn = (getattr(mod, 'ROUTES', {}) or {}).get('verify')
    if fn is None:
        return None
    try:
        res = fn({'audio_b64': audio_b64, 'mime': mime, 'text': text}, 'POST')
    except Exception as e:  # noqa: BLE001
        return {'name': '', 'score': 0.0, 'accepted': False, 'error': f'{type(e).__name__}: {e}'[:200]}
    if not isinstance(res, dict):
        return None
    return {
        'name': str(res.get('name') or ''),
        'score': round(float(res.get('score') or 0.0), 4),
        'accepted': bool(res.get('accepted')),
    }


# ── the routes ─────────────────────────────────────────────────────────────
def _hello(body: dict):
    token = _token(body.get('driver'))
    if not token:
        return {'ok': False, 'error': 'hello needs a driver token'}, 400
    reg = body.get('registry')
    rows = []
    if isinstance(reg, list):
        for r in reg[:MAX_REGISTRY]:
            if not isinstance(r, dict) or not r.get('name'):
                continue
            rows.append(
                {
                    'name': str(r.get('name'))[:120],
                    'view': str(r.get('view') or '')[:40],
                    'label': str(r.get('label') or '')[:160],
                    'aliases': [str(a)[:120] for a in (r.get('aliases') or [])][:32],
                    'args': r.get('args') if isinstance(r.get('args'), dict) else None,
                }
            )
    d = _driver(token)
    with _LOCK:
        d['registry'] = rows
        d['view'] = str(body.get('view') or '')[:40]
        d['hello_ts'] = _now()
    return {
        'ok': True,
        'driver': token,
        'actions': len(rows),
        'view': d['view'],
        'ext': ext_names(),
        'events': PREFIX + 'events?driver=' + urllib.parse.quote(token, safe=''),
    }, 200


def _utterance(body: dict):
    token = _token(body.get('driver'))
    if not token:
        return {'ok': False, 'error': 'utterance needs a driver token'}, 400
    audio_b64 = str(body.get('audio_b64') or '')
    mime = str(body.get('mime') or 'audio/webm')[:60]
    d = _driver(token)
    view = str(body.get('view') or d.get('view') or '')[:40]
    with _LOCK:
        d['view'] = view
        registry = list(d['registry'])

    try:
        audio = base64.b64decode(audio_b64, validate=False)
    except Exception:  # noqa: BLE001
        return {'ok': False, 'error': 'audio_b64 is not base64'}, 400

    try:
        from zyg_workflows import voice_stt
    except Exception as e:  # noqa: BLE001
        return {'ok': False, 'error': 'stt unavailable', 'detail': f'{type(e).__name__}: {e}'[:200]}, 503
    try:
        stt = voice_stt.transcribe_utterance(audio, mime) or {}
    except Exception as e:  # noqa: BLE001
        return {'ok': False, 'error': f'stt failed: {type(e).__name__}: {e}'[:300]}, 500
    text = str(stt.get('text') or '').strip()

    speaker = _verify_speaker(audio_b64, mime, text)
    rejected = speaker is not None and not speaker.get('accepted')

    tier, actions, say_text, brain_error = 'none', [], '', ''
    if rejected:
        say_text = REJECT_SAY
    elif text:
        try:
            from zyg_workflows import voice_brain
        except Exception as e:  # noqa: BLE001
            brain_error = f'{type(e).__name__}: {e}'[:200]
            voice_brain = None
        if voice_brain is not None:
            try:
                plan = voice_brain.plan(text, {'view': view, 'registry': registry}) or {}
            except Exception as e:  # noqa: BLE001
                plan = {}
                brain_error = f'{type(e).__name__}: {e}'[:200]
            tier = str(plan.get('tier') or 'none')
            say_text = str(plan.get('say') or '')
            for a in plan.get('actions') or []:
                if not isinstance(a, dict) or not a.get('name'):
                    continue
                actions.append(
                    {
                        'id': _new_id(),
                        'name': str(a['name'])[:120],
                        'args': a.get('args') if isinstance(a.get('args'), dict) else None,
                        'say': str(a.get('say') or '')[:300],
                    }
                )

    say = {'id': _new_id(), 'text': say_text, 'wav': say_url(say_text)} if say_text else None

    for a in actions:
        _push(token, 'action', a)
    if say:
        _push(token, 'say', say)

    with _LOCK:
        d['last_text'] = text
        d['seen'] += 1
        _TRANSCRIPTS.append({'ts': _now(), 'driver': token, 'text': text, 'tier': tier})

    _ledger_record(
        {
            'ts': _now(),
            'kind': 'utterance',
            'driver': token,
            'text': text,
            'speaker': speaker,
            'tier': tier,
            'actions': [{'id': a['id'], 'name': a['name'], 'args': a['args']} for a in actions],
            'acks': [],
        }
    )

    out = {
        'ok': True,
        'text': text,
        'speaker': speaker,
        'tier': tier,
        'actions': actions,
        'say': say,
        'stt': {k: stt.get(k) for k in ('seconds', 'ms', 'device', 'model', 'reason') if stt.get(k) is not None},
    }
    if brain_error:
        out['brain_error'] = brain_error
    return out, 200


def _ack(body: dict):
    aid = str(body.get('id') or '')[:64]
    if not aid:
        return {'ok': False, 'error': 'ack needs an action id'}, 400
    rec = {
        'ts': _now(),
        'id': aid,
        'ok': bool(body.get('ok')),
        'error': str(body.get('error') or '')[:300],
        'detail': str(body.get('detail') or '')[:500],
        'view': str(body.get('view') or '')[:40],
    }
    token = _token(body.get('driver'))
    matched = False
    with _LOCK:
        entry = _BY_ACTION.get(aid)
        if entry is not None:
            entry.setdefault('acks', []).append(rec)
            matched = True
            if not token:
                token = entry.get('driver') or ''
    _ledger_append(
        {
            'ts': rec['ts'],
            'kind': 'ack',
            'driver': token,
            'text': '',
            'speaker': None,
            'tier': '',
            'actions': [{'id': aid}],
            'acks': [rec],
        }
    )
    return {'ok': True, 'id': aid, 'matched': matched}, 200


def _say(body: dict):
    token = _token(body.get('driver'))
    if not token:
        return {'ok': False, 'error': 'say needs a driver token'}, 400
    text = str(body.get('text') or '').strip()
    if not text:
        return {'ok': False, 'error': 'say needs text'}, 400
    ev = {'id': _new_id(), 'text': text[:600], 'wav': say_url(text[:600])}
    queued = _push(token, 'say', ev)
    return {'ok': True, 'queued': queued, **ev}, 200


def _action(body: dict):
    token = _token(body.get('driver'))
    if not token:
        return {'ok': False, 'error': 'action needs a driver token'}, 400
    name = str(body.get('name') or '').strip()
    if not name:
        return {'ok': False, 'error': 'action needs a name'}, 400
    ev = {
        'id': _new_id(),
        'name': name[:120],
        'args': body.get('args') if isinstance(body.get('args'), dict) else None,
        'say': str(body.get('say') or '')[:300],
    }
    queued = _push(token, 'action', ev)
    _ledger_record(
        {
            'ts': _now(),
            'kind': 'action',
            'driver': token,
            'text': '',
            'speaker': None,
            'tier': 'manual',
            'actions': [{'id': ev['id'], 'name': ev['name'], 'args': ev['args']}],
            'acks': [],
        }
    )
    if ev['say']:
        _push(token, 'say', {'id': _new_id(), 'text': ev['say'], 'wav': say_url(ev['say'])})
    return {'ok': True, 'queued': queued, **ev}, 200


def _state():
    with _LOCK:
        drivers = [
            {
                'driver': t,
                'view': d['view'],
                'actions': len(d['registry']),
                'connected': d['sub'] > 0 and d.get('live', False),
                'queue': d['queue'].qsize(),
                'hello_ts': d['hello_ts'],
                'utterances': d['seen'],
                'last_text': d['last_text'],
            }
            for t, d in sorted(_DRIVERS.items())
        ]
        transcripts = list(_TRANSCRIPTS)
        depth = sum(x['queue'] for x in drivers)
    return {
        'ok': True,
        'drivers': drivers,
        'transcripts': transcripts,
        'queue_depth': depth,
        'ledger': len(_LEDGER),
        'ext': ext_names(),
    }, 200


def handle_get(path, query):
    rest = _rest(path)
    q = dict(query or {})
    if rest == 'ext' or rest.startswith('ext/'):
        res = ext_dispatch('GET', rest[3:], q)
        return _ext_result(res)
    if rest == 'state':
        return _state()
    if rest == 'ledger':
        try:
            n = max(1, min(LEDGER_MEMORY, int(q.get('n') or 50)))
        except (TypeError, ValueError):
            n = 50
        return {'ok': True, 'entries': _ledger_tail(n), 'path': LEDGER_PATH}, 200
    if rest in ('', 'health'):
        return {'ok': True, 'drivers': len(_DRIVERS), 'ext': ext_names(), 'body_limit': BODY_LIMIT}, 200
    return {'ok': False, 'error': f'no such voice route: {rest}'}, 404


def handle_post(path, body):
    rest = _rest(path)
    b = body if isinstance(body, dict) else {}
    if rest == 'ext' or rest.startswith('ext/'):
        return _ext_result(ext_dispatch('POST', rest[3:], b))
    if rest == 'hello':
        return _hello(b)
    if rest == 'utterance':
        return _utterance(b)
    if rest == 'ack':
        return _ack(b)
    if rest == 'say':
        return _say(b)
    if rest == 'action':
        return _action(b)
    return {'ok': False, 'error': f'no such voice route: {rest}'}, 404


def _ext_result(res):
    """An ext op returns a dict (JSON) or (bytes, mime, filename) (raw)."""
    if isinstance(res, tuple):
        return res
    if not isinstance(res, dict):
        return {'ok': True, 'result': res}, 200
    code = 200
    if res.get('error') and not res.get('ok'):
        code = int(res.get('code') or 400)
    return res, code


# ── SSE ────────────────────────────────────────────────────────────────────
def _sse_write(w, event: str, data) -> None:
    payload = json.dumps(data, separators=(',', ':'), default=str)
    w.write(('event: %s\ndata: %s\n\n' % (event, payload)).encode('utf-8'))
    w.flush()


def handle_sse(handler, query) -> None:
    """Hold one event-stream open for a driver token.

    kanban_server is a ThreadingTCPServer with daemon threads, so this occupies
    one thread for as long as the tab is open — hours. Everything it does has to
    be cheap and it must never raise out of the loop, or the thread dies with a
    half-written response.
    """
    token = _token((query or {}).get('driver'))
    if not token:
        body = json.dumps({'ok': False, 'error': 'events needs a driver token'}).encode()
        handler.send_response(400)
        handler.send_header('Content-Type', 'application/json')
        handler.send_header('Content-Length', str(len(body)))
        handler.end_headers()
        try:
            handler.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError, OSError) as _exc:
            _zyg_log.debug('client gone before the error body was sent: %s', _exc)
        return None

    d = _driver(token)
    with _LOCK:
        d['sub'] += 1
        mine = d['sub']
        d['live'] = True
        q = d['queue']
    # A second connection for the same token replaces the first subscriber: the
    # old loop sees d['sub'] != mine and lets go. The QUEUE is kept, so an action
    # pushed while the tab was reloading is still delivered.
    try:
        q.put_nowait(None)  # wake the previous reader
    except queue.Full as _exc:
        _zyg_log.debug('wake-up of the previous subscriber skipped, its queue is full: %s', _exc)

    # No Content-Length: the body ends when the socket does, so this connection
    # can never be reused.
    handler.close_connection = True
    handler.send_response(200)
    handler.send_header('Content-Type', 'text/event-stream; charset=utf-8')
    handler.send_header('Cache-Control', 'no-store')
    handler.send_header('X-Accel-Buffering', 'no')
    handler.send_header('Connection', 'keep-alive')
    handler.end_headers()
    w = handler.wfile
    try:
        w.write(b': open\n\n')
        w.flush()
        _sse_write(w, 'status', {'text': 'bridge connected', 'driver': token, 'actions': len(d['registry'])})
        while True:
            with _LOCK:
                if d['sub'] != mine:
                    break
            try:
                item = q.get(timeout=SSE_PING_SECONDS)
            except queue.Empty:
                w.write(b': ping\n\n')
                w.flush()
                continue
            if item is None:  # wake-up sentinel
                continue
            event, data = item
            _sse_write(w, event, data)
    except (BrokenPipeError, ConnectionResetError, OSError, ValueError) as _exc:
        _zyg_log.debug('event stream closed by the client: %s', _exc)
    finally:
        with _LOCK:
            if d['sub'] == mine:
                d['live'] = False
    return None
