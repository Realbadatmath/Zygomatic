#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""arch_mcp_shim.py — the Architecture Studio drawing tools as an MCP server.

Spawned by the Claude Code CLI (`claude -p --mcp-config ...`) for ONE assistant
job. It owns no state: every tools/list and tools/call is forwarded to the
kanban server, which holds the job's Drawing copy and runs the tool there.
That keeps the drawer, the `look` round-trip and `ask_user` exactly where they
were; only the thing that produces tool calls changed (the CLI on the
operator's Claude login instead of the API or Ollama).

Protocol: MCP over stdio, newline-delimited JSON-RPC 2.0. Only stdlib.

Env (set per job in the mcp-config the server writes):
  ARCH_ASSIST_URL    the kanban server base URL (defaults to ZYG_KANBAN_URL)
  ARCH_ASSIST_JOB    job id
  ARCH_ASSIST_TOKEN  per-job secret; the server refuses calls without it
"""

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
import logging as _zyg_logging

from zyg_workflows.paths import ZYG_KANBAN_URL

_zyg_log = _zyg_logging.getLogger(__name__)


URL = os.environ.get('ARCH_ASSIST_URL', ZYG_KANBAN_URL).rstrip('/')
JOB = os.environ.get('ARCH_ASSIST_JOB', '')
TOKEN = os.environ.get('ARCH_ASSIST_TOKEN', '')
PREFIX = '/inspect/api/architecture/assistant'
SERVER_NAME = 'arch'
VERSION = '1.0'


def _http(path, body=None, timeout=300):
    # ARCH_ASSIST_URL is read from the environment, so the scheme is checked before it is opened:
    # urlopen would otherwise happily serve a file:// or custom-scheme value from there.
    if urllib.parse.urlsplit(URL).scheme not in ('http', 'https'):
        return {'ok': False, 'error': f'ARCH_ASSIST_URL must be http(s), got {URL!r}'}
    if body is None:
        req = urllib.request.Request(URL + path)  # noqa: S310  scheme checked at the top of this function
    else:
        req = urllib.request.Request(  # noqa: S310  scheme checked at the top of this function
            URL + path, data=json.dumps(body).encode('utf-8'), headers={'Content-Type': 'application/json'}
        )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:  # nosec B310  # noqa: S310  req holds the checked URL
            return json.loads(r.read().decode('utf-8'))
    except urllib.error.HTTPError as e:
        try:
            return json.loads(e.read().decode('utf-8'))
        except Exception:  # noqa: BLE001
            return {'ok': False, 'error': f'HTTP {e.code}'}
    except Exception as e:  # noqa: BLE001
        return {'ok': False, 'error': f'cannot reach the studio server: {e}'}


def tools_list():
    out = _http(f'{PREFIX}/tools?id={JOB}&token={TOKEN}', timeout=30)
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


MAX_IMAGES = 3  # present() hands back three; the CLI gets no more


def content_blocks(out):
    """The MCP content blocks for one tool reply. `image` is the single picture
    `look` has always returned (it stays FIRST, where it was); `images` is a list
    of [mime, b64] a tool hands to the model to JUDGE (present(), 2026-09-11) and
    those follow the text, in order, at most MAX_IMAGES of them."""
    out = out if isinstance(out, dict) else {}
    ok = bool(out.get('ok'))
    content = [{'type': 'text', 'text': str(out.get('text') if ok else (out.get('error') or 'tool failed'))}]
    img = out.get('image')
    if ok and img and isinstance(img, (list, tuple)) and len(img) == 2:
        content.insert(0, {'type': 'image', 'data': img[1], 'mimeType': img[0]})
    imgs = out.get('images')
    if ok and isinstance(imgs, (list, tuple)):
        for one in list(imgs)[:MAX_IMAGES]:
            if isinstance(one, (list, tuple)) and len(one) == 2:
                content.append({'type': 'image', 'data': one[1], 'mimeType': one[0]})
    return content


def tools_call(name, args):
    # `look` blocks on the server until the studio has rendered (≤ 120 s there).
    out = _http(f'{PREFIX}/tool', {'id': JOB, 'token': TOKEN, 'name': name, 'args': args or {}}, timeout=300)
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
    elif method == 'notifications/initialized' or method.startswith('notifications/'):
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
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except ValueError as _exc:
            _zyg_log.warning('non-JSON MCP request line ignored: %s', _exc)
            continue
        if isinstance(msg, list):
            for m in msg:
                handle(m)
        else:
            handle(msg)


if __name__ == '__main__':
    main()
