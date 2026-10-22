# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""nomologin_board.py — the Nomologin board. 2026-09-22.

Serves Static/nomologin.html on 127.0.0.1:8750 and a small JSON API over nomologin.py.
The board only draws: every number, verdict, refusal and label is decided in nomologin.py,
so the card and the CLI cannot disagree.

BOUND TO LOOPBACK, DELIBERATELY. The rest of the hub listens on 0.0.0.0; this one must not.
It can launch browsers holding live sessions for every account you own and it prints 2FA
codes, so it is reachable only from this machine — and three further guards apply, because
"localhost only" is not by itself a defence against a web page you happen to be visiting:

  * Host header pinning — a page on the internet can resolve its own name to 127.0.0.1
    (DNS rebinding) and reach this port. Requests whose Host is not localhost:8750 are
    refused, which breaks that.
  * Sec-Fetch-Site — browsers label cross-site requests. Anything not `same-origin` or
    `none` is refused, so no other page can drive this board. The one exception is a
    top-level document navigation (`navigate`/`document` GET), which is how the hub card on
    :7000 opens the board; its response is unreadable to the page that started it.
  * A per-boot token, embedded in the page and required on every mutating call. A
    cross-origin script cannot read the page to learn it.

Run:  python3 nomologin_board.py [--port 8750]
"""

from __future__ import annotations

import json
import logging as _zyg_logging
import mimetypes
import os
import secrets
import socketserver
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from zyg_zero import nomologin as nl  # noqa: E402

# The assistant, browser control and mailbox are optional at runtime: this box may be
# without `node`, without puppeteer-core, or without the Claude CLI. A missing one must
# degrade to a disabled panel with a reason, not a board that will not start — the launcher
# half is what the operator needs on a posting day, and it does not depend on any of them.
try:
    from zyg_zero import nomologin_browser as nb  # noqa: E402
    from zyg_zero import nomologin_mail as nm  # noqa: E402
    from zyg_zero import nomologin_assistant as na  # noqa: E402

    ASSIST_ERROR = None
except Exception as _exc:  # noqa: BLE001
    nb = nm = na = None
    ASSIST_ERROR = f'{type(_exc).__name__}: {_exc}'

_zyg_log = _zyg_logging.getLogger(__name__)


PORT = int(os.environ.get('NOMOLOGIN_PORT', 8750))
STATIC = os.path.join(HERE, 'Static')
PAGE = os.path.join(STATIC, 'nomologin.html')

TOKEN = secrets.token_urlsafe(24)
_ALLOWED_HOSTS = {f'127.0.0.1:{PORT}', f'localhost:{PORT}', f'[::1]:{PORT}'}

# The overview shells out to `du` per persona, which is the slow part. Cache it briefly so
# the board's 5 s poll does not keep a disk busy walking twenty Chrome profiles.
_cache: dict = {'at': 0.0, 'data': None}
_cache_lock = threading.Lock()
CACHE_TTL = 4.0


def _overview(force: bool = False) -> dict:
    with _cache_lock:
        if not force and _cache['data'] and time.time() - _cache['at'] < CACHE_TTL:
            return _cache['data']
        data = nl.overview(with_disk=True)
        _cache.update(at=time.time(), data=data)
        return data


def _invalidate() -> None:
    with _cache_lock:
        _cache['at'] = 0.0


class Handler(BaseHTTPRequestHandler):
    server_version = 'Nomologin/1.0'
    protocol_version = 'HTTP/1.1'

    # ── plumbing ──────────────────────────────────────────────────────────────────────
    def log_message(self, fmt, *args):
        if '/api/' in (self.path or '') and not self.path.startswith('/api/overview'):
            sys.stderr.write(f'[NOMOLOGIN-BOARD] {self.address_string()} {fmt % args}\n')

    def _json(self, obj, code: int = 200) -> None:
        body = json.dumps(obj, ensure_ascii=False, default=str).encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError) as _exc:
            _zyg_log.debug('suppressed %s: %s', type(_exc).__name__, _exc)

    def _is_top_navigation(self) -> bool:
        """A cross-site GET that is the browser *navigating the whole tab here*.

        The hub card is served from a different origin, so clicking it
        labels the navigation `cross-site` and the Sec-Fetch-Site rule used to answer 403
        JSON instead of the board (2026-09-23). Letting this one shape through is safe: the
        page that started it cannot read the response (no CORS), the Host pin still stops
        DNS rebinding, and every mutating call is a POST that needs the per-boot token. An
        iframe or a script fetch is labelled `iframe`/`empty`, never `document`, so framing
        and cross-origin scripting stay refused.
        """
        return (
            self.command == 'GET'
            and self.headers.get('Sec-Fetch-Mode') == 'navigate'
            and self.headers.get('Sec-Fetch-Dest') == 'document'
        )

    def _guard(self, mutating: bool) -> bool:
        """Returns True when the request may proceed. See the module docstring."""
        if self.headers.get('Host', '') not in _ALLOWED_HOSTS:
            self._json({'ok': False, 'error': 'bad Host header'}, 403)
            return False
        site = self.headers.get('Sec-Fetch-Site')
        if site and site not in ('same-origin', 'none') and not self._is_top_navigation():
            self._json({'ok': False, 'error': f'cross-site request refused ({site})'}, 403)
            return False
        if mutating and self.headers.get('X-Nomologin-Token') != TOKEN:
            self._json(
                {'ok': False, 'error': 'missing or stale board token — reload the page (the token changes on restart)'},
                403,
            )
            return False
        return True

    def _body(self) -> dict:
        try:
            n = int(self.headers.get('Content-Length') or 0)
            return json.loads(self.rfile.read(n) or b'{}') if n else {}
        except (ValueError, json.JSONDecodeError):
            return {}

    # ── routes ────────────────────────────────────────────────────────────────────────
    def do_GET(self):  # noqa: N802
        if not self._guard(mutating=False):
            return
        path = (self.path or '/').split('?', 1)[0]

        if path in ('/', '/index.html', '/nomologin.html'):
            return self._page()
        if path == '/api/overview':
            ov = _overview(force='force' in (self.path.split('?', 1)[-1]))
            return self._json({'ok': True, 'token': TOKEN, **ov})
        if path == '/api/doctor':
            return self._json(nl.doctor())
        if path.startswith('/api/totp/'):
            parts = path.split('/')
            if len(parts) != 5:
                return self._json({'ok': False, 'error': 'want /api/totp/<id>/<platform>'}, 400)
            try:
                return self._json(nl.totp(parts[3], parts[4]))
            except Exception as e:  # noqa: BLE001
                return self._json({'ok': False, 'error': str(e)}, 500)
        if path.startswith('/api/assistant/') or path.startswith('/api/mail/') or path.startswith('/api/browser/'):
            return self._read_api(path)
        if path.startswith('/static/'):
            return self._static(path[len('/static/') :])
        return self._json({'ok': False, 'error': 'no such route'}, 404)

    def _read_api(self, path: str):
        """The read-only half of the assistant, mail and browser API.

        Mail reads sit under GET on purpose: the module cannot send, delete or mark
        anything read, so a mail fetch really is a read. Anything that writes — asking the
        assistant, storing a password — is POST and carries the token.
        """
        if na is None:
            return self._json({'ok': False, 'enabled': False, 'error': ASSIST_ERROR}, 503)
        parts = path.strip('/').split('/')
        try:
            if path == '/api/assistant/info':
                return self._json({'ok': True, 'enabled': True, **na.available()})
            if path == '/api/assistant/active':
                return self._json({'ok': True, 'jobs': na.active()})
            if path == '/api/assistant/history':
                return self._json({'ok': True, 'rows': na.history()})
            if len(parts) == 4 and parts[2] == 'job':
                return self._json(na.view(parts[3]))
            if len(parts) == 4 and parts[1] == 'mail':
                pid, verb = parts[2], parts[3]
                if verb == 'check':
                    return self._json(nm.check(pid))
                if verb == 'codes':
                    return self._json(nm.codes(pid))
                if verb == 'recent':
                    return self._json({'ok': True, 'messages': nm.recent(pid)})
            if len(parts) == 4 and parts[1] == 'browser' and parts[3] == 'status':
                return self._json({'ok': True, **nb.status(parts[2])})
        except KeyError as e:
            return self._json({'ok': False, 'error': str(e)}, 404)
        except Exception as e:  # noqa: BLE001
            return self._json({'ok': False, 'error': f'{type(e).__name__}: {e}'}, 500)
        return self._json({'ok': False, 'error': 'no such route'}, 404)

    def do_POST(self):  # noqa: N802
        if not self._guard(mutating=True):
            return
        path = (self.path or '/').split('?', 1)[0]
        body = self._body()
        parts = path.strip('/').split('/')

        try:
            if len(parts) == 3 and parts[0] == 'api':
                verb, pid = parts[1], parts[2]
                if verb == 'launch':
                    only = body.get('only') or None
                    r = nl.launch(pid, only=only, gate=body.get('gate', True))
                    _invalidate()
                    return self._json(r)
                if verb == 'stop':
                    r = nl.stop(pid, hard=bool(body.get('hard')))
                    _invalidate()
                    return self._json(r)
                if verb == 'probe':
                    r = nl.probe(pid)
                    _invalidate()
                    return self._json({'ok': True, **r})
                if verb == 'backup':
                    r = nl.backup(pid)
                    _invalidate()
                    return self._json(r)
            if path == '/api/persona':
                r = nl.add_persona(body)
                _invalidate()
                return self._json(r, 200 if r.get('ok') else 400)
            if path == '/api/sweep':
                r = nl.sweep()
                _invalidate()
                return self._json(r)
            if path.startswith('/api/assistant/') or path.startswith('/api/mail/'):
                if na is None:
                    return self._json({'ok': False, 'enabled': False, 'error': ASSIST_ERROR}, 503)
                if path == '/api/assistant/ask':
                    r = na.ask(body.get('persona') or '', body.get('text') or '', body.get('session'))
                    return self._json(r)
                if len(parts) == 4 and parts[1] == 'mail':
                    pid, verb = parts[2], parts[3]
                    if verb == 'configure':
                        return self._json(
                            nm.configure(
                                pid,
                                body.get('host') or '',
                                body.get('user') or '',
                                body.get('password') or '',
                                int(body.get('port') or 993),
                                bool(body.get('ssl', True)),
                            )
                        )
                    if verb == 'forget':
                        return self._json(nm.forget(pid))
            if path == '/api/stop-all':
                stopped = [p['id'] for p in _overview(True)['personas'] if p['running']]
                for pid in stopped:
                    nl.stop(pid)
                _invalidate()
                return self._json({'ok': True, 'stopped': stopped})
        except KeyError as e:
            return self._json({'ok': False, 'error': str(e)}, 404)
        except Exception as e:  # noqa: BLE001
            return self._json({'ok': False, 'error': f'{type(e).__name__}: {e}'}, 500)
        return self._json({'ok': False, 'error': 'no such route'}, 404)

    # ── static ────────────────────────────────────────────────────────────────────────
    def _page(self):
        if not os.path.exists(PAGE):
            return self._json({'ok': False, 'error': f'{PAGE} is missing'}, 500)
        with open(PAGE, 'rb') as fh:
            html = fh.read()
        html = html.replace(b'__NOMOLOGIN_TOKEN__', TOKEN.encode())
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Content-Length', str(len(html)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        try:
            self.wfile.write(html)
        except (BrokenPipeError, ConnectionResetError) as _exc:
            _zyg_log.debug('suppressed %s: %s', type(_exc).__name__, _exc)

    def _static(self, rel: str):
        full = os.path.normpath(os.path.join(STATIC, rel))
        if not full.startswith(STATIC + os.sep) or not os.path.isfile(full):
            return self._json({'ok': False, 'error': 'not found'}, 404)
        ctype = mimetypes.guess_type(full)[0] or 'application/octet-stream'
        with open(full, 'rb') as fh:
            data = fh.read()
        self.send_response(200)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        try:
            self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError) as _exc:
            _zyg_log.debug('suppressed %s: %s', type(_exc).__name__, _exc)


class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True
    request_queue_size = 64

    def handle_error(self, request, client_address):
        exc = sys.exc_info()[1]
        if isinstance(exc, (BrokenPipeError, ConnectionResetError)):
            return
        super().handle_error(request, client_address)


if __name__ == '__main__':  # the CLI lives in nomologin_board_cli
    from zyg_zero.nomologin_board_cli import main as _cli_main

    raise SystemExit(_cli_main())
