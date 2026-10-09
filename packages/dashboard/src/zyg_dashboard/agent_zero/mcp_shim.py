#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later
"""mcp_shim.py — Agent Zero's meta-tools as an MCP server for the Claude Code CLI.

Why this exists. On the `subscription` backend one Zero turn is one headless
`claude -p` turn on the operator's Claude Max login (the only way a
subscription can be spent). The CLI can only reach tools through MCP, so this
script is spawned by the CLI itself (`--mcp-config {... command: python3, args:
[mcp_shim.py] ...}`) and forwards every `tools/list` and `tools/call` straight
back to the dashboard over HTTP. It owns no state: the turn, its tool map, its
budget and its audit trail all stay in the dashboard process, exactly where the
other backends keep them. The only thing that changed is who produces the tool
calls.

Tool names reach the model as `mcp__zero__<tool>`; the bridge strips the
prefix again before it calls the turn's executor.

Protocol: MCP over stdio, newline-delimited JSON-RPC 2.0. Stdlib only, so it
runs under a bare `python3 mcp_shim.py` with no package on sys.path.

Env (written per turn into the mcp-config by backends/subscription.py):
  ZERO_MCP_URL     http://127.0.0.1:5000 — the dashboard
  ZERO_MCP_TURN    turn id (the bridge looks it up in runner.TURNS)
  ZERO_MCP_TOKEN   per-turn secret; the bridge refuses calls without it
  ZERO_MCP_COOKIE  the user's dashboard session cookie value, sent as
                   `Cookie: session=<value>` so the dashboard's own login gate
                   authorises the bridge instead of a second auth scheme
  ZERO_MCP_CSRF    sent as X-CSRF-Token on the POST
"""

import json
import os
import sys
import urllib.error
import urllib.request

URL = os.environ.get('ZERO_MCP_URL', 'http://127.0.0.1:5000').rstrip('/')
# The shim sends the operator's dashboard session cookie to URL, so the scheme is pinned
# here, once, rather than trusted per request: a `file:` or custom-scheme ZERO_MCP_URL
# would hand that cookie to whatever urllib's handler for it decides to do.
if not URL.startswith(('http://', 'https://')):
    raise SystemExit(f'zero mcp shim: ZERO_MCP_URL must be an http(s) URL, got {URL!r}')
TURN = os.environ.get('ZERO_MCP_TURN', '')
TOKEN = os.environ.get('ZERO_MCP_TOKEN', '')
COOKIE = os.environ.get('ZERO_MCP_COOKIE', '')
CSRF = os.environ.get('ZERO_MCP_CSRF', '')
PREFIX = '/api/zero/v2/mcp'
SERVER_NAME = 'zero'
VERSION = '1.0'
LIST_TIMEOUT = 30
CALL_TIMEOUT = 300


def _headers(post: bool) -> dict:
    h = {}
    if post:
        h['Content-Type'] = 'application/json'
    if COOKIE:
        h['Cookie'] = 'session=' + COOKIE
    if CSRF:
        h['X-CSRF-Token'] = CSRF
    return h


def _http(path, body=None, timeout=CALL_TIMEOUT):
    if body is None:
        req = urllib.request.Request(URL + path, headers=_headers(False))  # noqa: S310  URL's scheme is pinned at import
    else:
        req = urllib.request.Request(  # noqa: S310  URL's scheme is pinned at import
            URL + path, data=json.dumps(body).encode('utf-8'), headers=_headers(True)
        )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:  # nosec B310  # noqa: S310  scheme pinned at import
            return json.loads(r.read().decode('utf-8'))
    except urllib.error.HTTPError as e:
        try:
            return json.loads(e.read().decode('utf-8'))
        except Exception:  # noqa: BLE001
            return {'ok': False, 'error': f'HTTP {e.code}'}
    except Exception as e:  # noqa: BLE001
        return {'ok': False, 'error': f'cannot reach the dashboard: {e}'}


def tools_list():
    """The turn's tool map, renamed into MCP's spelling (``inputSchema``).

    The dashboard decides which tools this turn may see, so the shim asks rather
    than caches: a refusal is raised, never answered with an empty list, so the
    CLI reports a broken server instead of a model that silently has no tools.
    """
    out = _http(f'{PREFIX}/{TURN}/tools?token={TOKEN}', timeout=LIST_TIMEOUT)
    if not out.get('ok'):
        raise RuntimeError(out.get('error') or 'tool list refused')
    tools = []
    for t in out.get('tools') or []:
        tools.append(
            {
                'name': t['name'],
                'description': t.get('description') or '',
                'inputSchema': t.get('input_schema') or {'type': 'object', 'properties': {}},
            }
        )
    return tools


def content_blocks(out):
    """The MCP content blocks for one tool reply. The bridge always answers with
    the execute_tool dict of CONTRACT C, whose human-readable payload is `text`
    whether the call succeeded or not."""
    out = out if isinstance(out, dict) else {}
    ok = bool(out.get('ok'))
    text = out.get('text') if ok else (out.get('text') or out.get('error') or 'tool failed')
    return [{'type': 'text', 'text': str(text or '')}]


def tools_call(name, args):
    """Run one tool call through the dashboard bridge and shape the MCP reply.

    A tool that fails is a *successful* JSON-RPC reply carrying ``isError``, not a
    protocol error: the model is meant to read the failure and decide what to do
    next, which it cannot do if the CLI swallows it as a transport fault.
    """
    out = _http(f'{PREFIX}/{TURN}/call', {'token': TOKEN, 'name': name, 'args': args or {}}, timeout=CALL_TIMEOUT)
    return {'content': content_blocks(out), 'isError': not out.get('ok')}


def _reply(mid, result=None, error=None):
    msg = {'jsonrpc': '2.0', 'id': mid}
    if error is not None:
        msg['error'] = error
    else:
        msg['result'] = result
    sys.stdout.write(json.dumps(msg) + '\n')
    sys.stdout.flush()


def handle(msg):
    """Dispatch one JSON-RPC message, writing at most one reply to stdout.

    Notifications (``notifications/*``) and any id-less message get no reply, as
    the spec requires; an unknown method with an id gets -32601 so the CLI fails
    loudly rather than waiting for a response that is never coming.
    """
    method = msg.get('method') or ''
    mid = msg.get('id')
    params = msg.get('params') or {}
    if method == 'initialize':
        _reply(
            mid,
            {
                'protocolVersion': params.get('protocolVersion') or '2025-06-18',
                'capabilities': {'tools': {}},
                'serverInfo': {'name': SERVER_NAME, 'version': VERSION},
            },
        )
    elif method.startswith('notifications/'):
        return  # notifications get no reply
    elif method == 'ping':
        _reply(mid, {})
    elif method == 'tools/list':
        try:
            _reply(mid, {'tools': tools_list()})
        except Exception as e:  # noqa: BLE001
            _reply(mid, error={'code': -32000, 'message': str(e)[:300]})
    elif method == 'tools/call':
        try:
            _reply(mid, tools_call(params.get('name') or '', params.get('arguments') or {}))
        except Exception as e:  # noqa: BLE001
            _reply(mid, {'content': [{'type': 'text', 'text': f'tool failed: {e}'[:300]}], 'isError': True})
    elif mid is not None:
        _reply(mid, error={'code': -32601, 'message': f'unknown method {method}'})


def main():
    """Read newline-delimited JSON-RPC from stdin until the CLI closes it.

    An unparseable line is skipped rather than fatal -- the CLI owns this process
    and a dead shim costs the turn -- and a batch (a JSON array) is handled
    message by message.
    """
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except ValueError:
            continue
        if isinstance(msg, list):
            for m in msg:
                handle(m)
        else:
            handle(msg)


if __name__ == '__main__':
    main()
