#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""nomologin_mcp_shim.py — the persona's browser and mailbox as MCP tools.

Spawned by the Claude Code CLI (`claude -p --mcp-config ...`) for ONE assistant job.
Protocol: MCP over stdio, newline-delimited JSON-RPC 2.0. Stdlib only.

Unlike arch_mcp_shim, this calls the modules in-process rather than forwarding to a server:
the tools are persona-scoped, not job-scoped, so there is no job-local state for a server
to hold, and an HTTP hop would only add a failure mode.

**A job is pinned to ONE persona, from the environment.** No tool takes a persona argument
and none can be talked into another account. That is deliberate: these tools act on live
signed-in sessions, and "act on the account I was pointed at" has to be a property of the
process, not of the model's good behaviour.

What is deliberately absent: no tool signs in, registers, or submits credentials. The
assistant operates accounts that a person signed into by hand.

Env (set per job in the mcp-config the assistant writes):
  NOMOLOGIN_PERSONA   the persona id this job may touch
"""

import json
import os
import sys
import traceback
import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)


HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

PERSONA = os.environ.get('NOMOLOGIN_PERSONA', '')
SERVER_NAME = 'nomo'
VERSION = '1.0'

# Screenshots go back as image blocks so the model can see the page. Three is the ceiling
# per reply for the same reason arch caps them: context is the scarce resource.
MAX_IMAGES = 3


def _mods():
    """Imported lazily so a missing dependency is a tool error the model can read, not a
    dead server that fails at handshake with nothing in the log."""
    from zyg_zero import nomologin as nl
    from zyg_zero import nomologin_browser as nb
    from zyg_zero import nomologin_mail as nm

    return nl, nb, nm


# ── tool surface ──────────────────────────────────────────────────────────────────────
TOOLS = [
    {
        'name': 'page',
        'description': (
            'Read the current page: url, title, scroll position, and every clickable or '
            'typable element with an index. ALWAYS call this before clicking — indexes '
            'come from here and shift whenever the page repaints. Elements inside iframes '
            'are included and carry a frame number.'
        ),
        'inputSchema': {
            'type': 'object',
            'properties': {
                'tab': {
                    'type': 'string',
                    'description': 'tab index, or a substring of its url/title. Prefer the substring: tab '
                    'order changes when the operator clicks. Omit for the first tab.',
                }
            },
        },
    },
    {
        'name': 'text',
        'description': (
            'The page as plain text. Use for reading content — posts, analytics figures, '
            'notification lists — where the element list is not the point.'
        ),
        'inputSchema': {
            'type': 'object',
            'properties': {
                'tab': {'type': 'string'},
                'limit': {'type': 'integer', 'description': 'max characters, default 12000'},
            },
        },
    },
    {
        'name': 'look',
        'description': (
            'Screenshot the tab and return it as an image. Use when the text and element '
            'list are not enough — a chart, a layout question, or a page that will not '
            'explain itself.'
        ),
        'inputSchema': {
            'type': 'object',
            'properties': {
                'tab': {'type': 'string'},
                'full': {'type': 'boolean', 'description': 'full scrollable page, not just the viewport'},
            },
        },
    },
    {
        'name': 'tabs',
        'description': "List the persona's open tabs with their urls and titles.",
        'inputSchema': {'type': 'object', 'properties': {}},
    },
    {
        'name': 'navigate',
        'description': 'Point a tab at a url and wait for it to load.',
        'inputSchema': {
            'type': 'object',
            'properties': {'url': {'type': 'string'}, 'tab': {'type': 'string'}},
            'required': ['url'],
        },
    },
    {
        'name': 'click',
        'description': (
            'Click an element as a person would — a real mouse event at the element, in '
            'its own frame. Give `index` from the last `page` call, plus `expect` set to '
            "that element's label: if the page has changed underneath, the click is "
            'refused instead of landing on the wrong thing. A `selector` works too.'
        ),
        'inputSchema': {
            'type': 'object',
            'properties': {
                'index': {'type': 'integer', 'description': 'index from the last `page` call'},
                'expect': {
                    'type': 'string',
                    'description': 'the label you expect at that index — your guard against a repaint',
                },
                'selector': {'type': 'string', 'description': 'CSS selector, instead of index'},
                'tab': {'type': 'string'},
            },
        },
    },
    {
        'name': 'type',
        'description': (
            'Type into a field, one keystroke at a time. Give `index` or `selector` to '
            'focus a field first, or neither to type into whatever is already focused. '
            'Set `enter` to submit afterwards.'
        ),
        'inputSchema': {
            'type': 'object',
            'properties': {
                'text': {'type': 'string'},
                'index': {'type': 'integer'},
                'selector': {'type': 'string'},
                'clear': {'type': 'boolean', 'description': 'clear the field first, default true'},
                'enter': {'type': 'boolean', 'description': 'press Enter after typing'},
                'tab': {'type': 'string'},
            },
            'required': ['text'],
        },
    },
    {
        'name': 'press',
        'description': 'Press a key: Enter, Tab, Escape, Backspace, ArrowDown, PageDown…',
        'inputSchema': {
            'type': 'object',
            'properties': {'key': {'type': 'string'}, 'tab': {'type': 'string'}},
            'required': ['key'],
        },
    },
    {
        'name': 'scroll',
        'description': 'Scroll the page. Positive dy goes down. Returns the new position.',
        'inputSchema': {
            'type': 'object',
            'properties': {'dy': {'type': 'integer', 'description': 'pixels, default 600'}, 'tab': {'type': 'string'}},
        },
    },
    {
        'name': 'wait_for',
        'description': (
            'Wait for a selector to appear. Returns found:false rather than failing, so a '
            'button that never appears is something to reason about, not a crash.'
        ),
        'inputSchema': {
            'type': 'object',
            'properties': {
                'selector': {'type': 'string'},
                'timeout': {'type': 'integer', 'description': 'milliseconds, default 20000'},
                'tab': {'type': 'string'},
            },
            'required': ['selector'],
        },
    },
    {
        'name': 'back',
        'description': 'Go back in history.',
        'inputSchema': {'type': 'object', 'properties': {'tab': {'type': 'string'}}},
    },
    {
        'name': 'mail_recent',
        'description': (
            'Recent mail for this persona, newest first, headers only. Read-only: nothing '
            'here sends, deletes or marks anything read.'
        ),
        'inputSchema': {
            'type': 'object',
            'properties': {
                'n': {'type': 'integer', 'description': 'how many, default 20'},
                'unread': {'type': 'boolean'},
                'hours': {'type': 'number', 'description': 'only mail newer than this'},
            },
        },
    },
    {
        'name': 'mail_read',
        'description': 'One message whole, with its links and any codes found in it.',
        'inputSchema': {'type': 'object', 'properties': {'uid': {'type': 'string'}}, 'required': ['uid']},
    },
    {
        'name': 'mail_codes',
        'description': (
            'Scan recent mail for sign-in codes and confirm links. Returns candidates with '
            'their timestamps, not a verdict — codes expire in minutes and a stale one '
            'looks like a failed attempt to the platform, so check the time before using '
            'one. To open a confirm link, use mail_open_link, never navigate: the link is '
            "bound to this persona's session."
        ),
        'inputSchema': {
            'type': 'object',
            'properties': {'minutes': {'type': 'number', 'description': 'how far back, default 30'}},
        },
    },
    {
        'name': 'mail_open_link',
        'description': (
            "Open a link from the mailbox in THIS persona's browser, which is the only "
            'place a confirm link works — they bind to the session and exit IP that asked.'
        ),
        'inputSchema': {
            'type': 'object',
            'properties': {'url': {'type': 'string'}, 'tab': {'type': 'string'}},
            'required': ['url'],
        },
    },
    {
        'name': 'persona',
        'description': (
            "Who this job is acting as: the persona's label, its configured targets and "
            'handles, how old its cookie jar is, and whether its browser is drivable.'
        ),
        'inputSchema': {'type': 'object', 'properties': {}},
    },
]


def _persona_info():
    nl, nb, nm = _mods()
    p = nl.get_persona(PERSONA)
    age = nl.cookie_age_days(PERSONA)
    out = {
        'id': p['id'],
        'label': p.get('label'),
        'note': p.get('note'),
        'timezone': p.get('timezone'),
        'proxy': bool(p.get('proxy')),
        'targets': [{'platform': t.get('platform'), 'handle': t.get('handle')} for t in p.get('targets') or []],
        'cookie_age_days': round(age, 1) if age is not None else None,
        'browser': nb.status(PERSONA),
        'mail': nm.configured().get(PERSONA) or None,
    }
    if age is not None and age > 30:
        out['warning'] = (
            f'the cookie jar was last written {age:.0f} days ago — a session '
            'this old may have lapsed; expect a re-login challenge'
        )
    return out


def run_tool(name: str, args: dict) -> dict:
    """Returns {'text': ...} or {'error': ...}, plus optional 'images' [[mime, b64], ...]."""
    nl, nb, nm = _mods()
    if not PERSONA:
        return {'error': 'this job has no persona bound — the assistant spawned it wrong'}

    tab = args.get('tab')
    browser_actions = {
        'page': ('state', {}),
        'text': ('text', {'limit': args.get('limit')}),
        'navigate': ('navigate', {'url': args.get('url')}),
        'click': (
            'click',
            {'index': args.get('index'), 'selector': args.get('selector'), 'expect': args.get('expect')},
        ),
        'type': (
            'type',
            {
                'text': args.get('text'),
                'index': args.get('index'),
                'selector': args.get('selector'),
                'clear': args.get('clear'),
                'enter': args.get('enter'),
            },
        ),
        'press': ('press', {'key': args.get('key')}),
        'scroll': ('scroll', {'dy': args.get('dy')}),
        'wait_for': ('wait', {'selector': args.get('selector'), 'timeout': args.get('timeout')}),
        'back': ('back', {}),
        'tabs': ('tabs', {}),
    }

    if name in browser_actions:
        action, kw = browser_actions[name]
        kw = {k: v for k, v in kw.items() if v is not None}
        out = nb.act(PERSONA, action, tab=tab, **kw)
        if out.get('error'):
            return {'error': out['error']}
        return {'text': json.dumps(out, ensure_ascii=False, indent=1)[:14000]}

    if name == 'look':
        shots = os.path.join(nl.ROOT, 'shots', PERSONA)
        os.makedirs(shots, exist_ok=True)
        path = os.path.join(shots, 'assistant.png')
        out = nb.act(PERSONA, 'shot', tab=tab, path=path, full=bool(args.get('full')))
        if out.get('error'):
            return {'error': out['error']}
        import base64

        with open(path, 'rb') as fh:
            b64 = base64.b64encode(fh.read()).decode()
        return {'text': f'screenshot of {out.get("url", "the tab")}', 'images': [['image/png', b64]]}

    if name == 'mail_recent':
        kw = {k: args[k] for k in ('n', 'unread', 'hours') if args.get(k) is not None}
        return {'text': json.dumps(nm.recent(PERSONA, **kw), ensure_ascii=False, indent=1)[:12000]}
    if name == 'mail_read':
        return {'text': json.dumps(nm.message(PERSONA, args['uid']), ensure_ascii=False, indent=1)[:14000]}
    if name == 'mail_codes':
        kw = {'minutes': args['minutes']} if args.get('minutes') is not None else {}
        return {'text': json.dumps(nm.codes(PERSONA, **kw), ensure_ascii=False, indent=1)[:12000]}
    if name == 'mail_open_link':
        return {'text': json.dumps(nm.open_link(PERSONA, args['url'], tab), ensure_ascii=False)}
    if name == 'persona':
        return {'text': json.dumps(_persona_info(), ensure_ascii=False, indent=1)}

    return {'error': f'unknown tool {name}'}


def content_blocks(out: dict) -> list:
    text = out.get('error') or out.get('text') or ''
    content = [{'type': 'text', 'text': str(text)}]
    for one in (out.get('images') or [])[:MAX_IMAGES]:
        if isinstance(one, (list, tuple)) and len(one) == 2:
            content.append({'type': 'image', 'data': one[1], 'mimeType': one[0]})
    return content


# ── JSON-RPC plumbing ─────────────────────────────────────────────────────────────────
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
    elif method.startswith('notifications/'):
        return
    elif method == 'ping':
        _reply(mid, {})
    elif method == 'tools/list':
        _reply(mid, {'tools': TOOLS})
    elif method == 'tools/call':
        name = params.get('name') or ''
        args = params.get('arguments') or {}
        try:
            out = run_tool(name, args)
        except Exception as exc:  # noqa: BLE001
            # The traceback goes to stderr (the job log); the model gets the one line it
            # can act on. A stack trace in context is noise it will try to debug.
            traceback.print_exc(file=sys.stderr)
            out = {'error': f'{type(exc).__name__}: {exc}'[:400]}
        _reply(mid, {'content': content_blocks(out), 'isError': bool(out.get('error'))})
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
            _zyg_log.debug('suppressed %s: %s', type(_exc).__name__, _exc)
            continue
        if isinstance(msg, list):
            for m in msg:
                handle(m)
        else:
            handle(msg)


if __name__ == '__main__':
    main()
