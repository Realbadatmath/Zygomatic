# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The HTTP handler, the routes and main().

Moved verbatim from session_tree_server.py lines 3698-3874.
"""

from ._base import (
    BaseHTTPRequestHandler,
    LOCK,
    STATIC,
    json,
    os,
    parse_qs,
    re,
    urlparse,
)
from .storage import CFG, audit, audit_tail
from .identity import identify
from .resources import queue_state, wait_queue
from .metrics import ui_metrics
from .commands import Refuse
from .creator_commands import AGENT_COMMANDS
from .ui import ui_action, ui_active, ui_counts, ui_finished, ui_planned, ui_suggested

import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)


# ───────────────────────────── HTTP ──────────────────────────────────────────


class Handler(BaseHTTPRequestHandler):
    server_version = 'SessionTree/1.0'

    def log_message(self, fmt, *args):
        if '/api/ui/' in (args[0] if args else ''):
            return  # the 3-second poll would flood the log
        _zyg_log.info('[session-tree] ' + fmt % args)

    def _send(self, code, payload, ctype='application/json'):
        data = payload if isinstance(payload, bytes) else json.dumps(payload, indent=1).encode()
        self.send_response(code)
        self.send_header('Content-Type', ctype + ('; charset=utf-8' if 'json' in ctype or 'html' in ctype else ''))
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(data)

    def _is_browser(self):
        # Keeps agents out of the finished tab and the operator-only actions.
        # Sec-Fetch-Site is only sent to "trustworthy" origins (https or
        # localhost) — on a plain-http LAN address like http://<lan-host>:7100
        # Chrome omits it, which
        # broke the page on 2026-09-02. So also accept a same-origin Referer
        # from a Mozilla-family user agent: browsers send both on the page's
        # own fetches, curl/urllib/requests send neither.
        if self.headers.get('Sec-Fetch-Site'):
            return True
        ua = self.headers.get('User-Agent', '')
        ref = self.headers.get('Referer', '')
        host = self.headers.get('Host', '')
        return 'Mozilla/' in ua and host != '' and ('://' + host) in ref

    def _body(self):
        n = int(self.headers.get('Content-Length') or 0)
        if n <= 0:
            return {}
        try:
            return json.loads(self.rfile.read(n).decode('utf-8'))
        except Exception:
            return {}

    def do_GET(self):
        u = urlparse(self.path)
        if u.path in ('/', '/index.html'):
            with open(os.path.join(STATIC, 'index.html'), 'rb') as f:
                return self._send(200, f.read(), 'text/html')
        if u.path == '/favicon.svg':
            with open(os.path.join(STATIC, 'favicon.svg'), 'rb') as f:
                return self._send(200, f.read(), 'image/svg+xml')
        if u.path == '/rules.md':
            p = os.path.expanduser('~/.claude/skills/session-tree/SKILL.md')
            try:
                with open(p, 'rb') as f:
                    return self._send(200, f.read(), 'text/plain')
            except FileNotFoundError:
                return self._send(404, b'no rules file', 'text/plain')
        if u.path == '/api/health':
            return self._send(
                200, {'ok': True, 'port': CFG['port'], 'queue': queue_state(), 'waiting': len(wait_queue())}
            )
        if u.path.startswith('/api/ui/'):
            if not self._is_browser():
                return self._send(
                    403,
                    {
                        'ok': False,
                        'error': 'browser-only endpoint. Agents use the `st` CLI and never read finished trees.',
                    },
                )
            if u.path == '/api/ui/counts':
                return self._send(200, ui_counts())
            if u.path == '/api/ui/metrics':
                return self._send(200, ui_metrics())
            with LOCK:
                if u.path == '/api/ui/active':
                    return self._send(200, ui_active())
                if u.path == '/api/ui/suggested':
                    return self._send(200, ui_suggested())
                if u.path == '/api/ui/planned':
                    return self._send(200, ui_planned())
                if u.path == '/api/ui/finished':
                    return self._send(200, ui_finished())
                if u.path == '/api/ui/log':
                    n = int(parse_qs(u.query).get('n', ['80'])[0])
                    return self._send(200, {'events': audit_tail(n)})
        return self._send(404, {'ok': False, 'error': 'not found'})

    def do_POST(self):
        u = urlparse(self.path)
        body = self._body()
        if u.path == '/api/ui/action':
            if not self._is_browser():
                return self._send(403, {'ok': False, 'error': 'browser-only endpoint'})
            with LOCK:
                res = ui_action(body)
            audit(
                {
                    'cmd': 'ui:' + str(body.get('action')),
                    'tree': body.get('tree'),
                    'task': body.get('task'),
                    'ok': res.get('ok'),
                    'model': str(body.get('by') or 'operator'),
                }
            )
            return self._send(200, res)
        m = re.fullmatch(r'/api/agent/([a-z-]+)', u.path)
        if not m:
            return self._send(404, {'ok': False, 'error': 'not found'})
        cmd = m.group(1)
        fn = AGENT_COMMANDS.get(cmd)
        if not fn:
            return self._send(404, {'ok': False, 'error': f'unknown command {cmd}'})
        ident = identify(body)
        with LOCK:
            try:
                res = fn(ident, body)
                code = 200
            except Refuse as e:
                res = {'ok': False, 'error': str(e)}
                if e.retry_after:
                    res['retry_after_s'] = e.retry_after
                code = 409
            except Exception as e:
                res = {'ok': False, 'error': f'server error: {e!r}'}
                code = 500
        if cmd not in ('whoami', 'status'):
            audit(
                {
                    'cmd': cmd,
                    'session': ident['session_id'][:8],
                    'model': ident['model'],
                    'role': ident['role'],
                    'tree': body.get('tree') or res.get('tree'),
                    'task': body.get('task') or res.get('task'),
                    'ok': res.get('ok'),
                    'error': (res.get('error') or '')[:300],
                }
            )
        return self._send(code, res)


def main(*a, **k):
    """Delegate to the CLI — `session_tree_server/__init__.py` re-exports `main` from here."""
    from .http_server_cli import main as _m

    return _m(*a, **k)


if __name__ == '__main__':  # the CLI lives in http_server_cli
    from zyg_dashboard.session_tree.session_tree_server.http_server_cli import main as _cli_main

    raise SystemExit(_cli_main())
