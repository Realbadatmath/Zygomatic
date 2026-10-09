# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""st_client_cli — the Session Tree CLI's transport and its shared printers.

Extracted from ``st_cli.py`` (2026-10-09) together with ``st_commands_cli``, which
holds one handler per command and imports everything here. Nothing in this module
talks to a tree: it POSTs to the board, formats the four blocks every command reuses
(a claimed brief, a refusal, a failure notice, a problem report) and carries the two
JSON templates ``st report-template`` / ``st tree-template`` print.

Stdlib-only, like ``st_cli`` itself: the CLI runs under ``/usr/bin/python3``, outside
the venv, so it cannot import ``zyg_workflows.paths``.
"""

import json
import os
import sys
import urllib.error
import urllib.request
from urllib.parse import urlsplit

# This CLI runs under /usr/bin/python3, outside the venv, so it is stdlib-only by
# design and cannot import zyg_workflows.paths.ZYG_SESSION_TREE_URL. The board
# address is therefore assembled from the environment here: ZYG_SESSION_TREE_URL
# wins as before, and its fallback is built from host + port rather than baked in,
# so no endpoint is hardcoded. The defaults are paths.ZYG_SESSION_TREE_URL's own.
ST_HOST = os.environ.get('ZYG_SESSION_TREE_HOST') or '127.0.0.1'
ST_PORT = os.environ.get('ZYG_SESSION_TREE_PORT') or '7100'
URL = os.environ.get('ZYG_SESSION_TREE_URL') or f'http://{ST_HOST}:{ST_PORT}'
SID = os.environ.get('CLAUDE_CODE_SESSION_ID', '')
PID = os.environ.get('CLAUDE_PID', '')

# The default cwd of TREE_TEMPLATE below: the legacy production tree. Stdlib-only for the
# reason above, this CLI cannot read zyg_workflows.paths.ZYG_CREWS_ROOT, the single source
# of truth for that root, so it honours the same ZYG_CREWS_ROOT variable paths.py does and
# falls back to the directory `st tree-template` was run from.
CREWS_ROOT = os.environ.get('ZYG_CREWS_ROOT') or os.getcwd()

TREE_TEMPLATE = {
    'title': 'Short tree title',
    'goal': 'One paragraph: what the whole tree achieves and how the operator will know.',
    'cwd': CREWS_ROOT,
    'eta_minutes': 45,
    'eta_note': "REQUIRED with eta_minutes. Your arithmetic: e.g. 'longest chain 3 tasks × (2 + 0.6×20 calls) = 42 min; "
    "2 heavy tasks serialised 2×15 = 30 min → max = 42, +3 spawn latency = 45'. Logged, compared with reality "
    'on the Metrics tab, never acted on.',
    'tasks': [
        {
            'title': '≤100 chars, verb first',
            'brief': 'EVERYTHING the executor needs. It reads nothing else: files to open with line '
            'numbers, what to change, what NOT to touch, how to prove it. ≥30 chars.',
            'weight': 'light',
            'eta_minutes': 14,
            'vram_gb': 0,
            'ram_gb': 4,
            'cwd': '',
            'verify_cmd': 'python3 -m pytest tests/test_x.py -q  (optional; exit 0 = pass; run by the server on done)',
            'expect_files': ['/abs/path/that/must/exist/and/be/fresh/after/the/task (optional)'],
            'depends_on': [],
        }
    ],
}

REPORT_TEMPLATE = {
    'summary': '≥40 chars. What you actually did, in past tense, specific.',
    'changed_files': ['/abs/path/one.py', '/abs/path/two.html'],
    'verification': {
        'cmd': 'the exact command you ran to prove it works',
        'output': 'its literal output (paste, do not paraphrase)',
    },
    'not_done': 'what is NOT done or only partly done — or the word: none',
    'notes': 'optional: gotchas the next agent needs',
}


def call(cmd, **payload):
    """POST *payload* to the board's ``/api/agent/<cmd>`` and return the decoded JSON.

    The session identity is added here, so no caller can forget it. Every failure comes
    back as a dict with ``ok: False`` and an ``error`` a human can act on — an unusable
    URL scheme, the server's own 4xx body, or an unreachable board — never an exception.
    """
    payload.update(session_id=SID, pid=PID)
    # URL comes from the environment, so the scheme is checked before the session id is
    # POSTed to it: file:// or a custom handler would otherwise be handed the identity.
    # safe_urlopen cannot be used here — it takes a URL, not a Request, and this CLI is
    # stdlib-only so that it runs under /usr/bin/python3 with no venv.
    scheme = urlsplit(URL).scheme.lower()
    if scheme not in ('http', 'https'):
        return {'ok': False, 'error': f'refusing to post to a {scheme or "scheme-less"} session tree URL: {URL}'}
    req = urllib.request.Request(  # nosec B310  # noqa: S310  scheme checked on the line above
        f'{URL}/api/agent/{cmd}',
        data=json.dumps(payload).encode(),
        headers={'Content-Type': 'application/json'},
        method='POST',
    )
    try:
        with urllib.request.urlopen(req, timeout=300) as r:  # nosec B310  # noqa: S310  scheme checked above
            return json.load(r)
    except urllib.error.HTTPError as e:
        try:
            return json.load(e)
        except Exception:
            return {'ok': False, 'error': f'HTTP {e.code}'}
    except urllib.error.URLError as e:
        return {
            'ok': False,
            'error': f'session tree server unreachable at {URL} ({e.reason}). '
            'Operator: systemctl --user restart session-tree.service',
        }


def print_brief(r):
    """Print a granted claim: the lease line, the title, the brief, and what proves it."""
    print(
        f'CLAIMED {r["tree"]}#{r["task"]} ({r["weight"]})  lease until {r["lease_until"]} '
        f'(touch every <{r["lease_minutes"]} min)'
    )
    print(f'title: {r["title"]}')
    if r.get('cwd'):
        print(f'cwd: {r["cwd"]}')
    print('--- BRIEF ---')
    print(r['brief'])
    print('--- END BRIEF ---')
    if r.get('verify_cmd'):
        print(f'server will run on done: {r["verify_cmd"]}')
    if r.get('expect_files'):
        print('must exist and be fresh on done: ' + ', '.join(r['expect_files']))
    print(f'when finished: st done {r["tree"]} {r["task"]} --report /path/report.json')


def die(res):
    """Print the server's refusal (and any retry hint) and exit the process with 2."""
    print('REFUSED: ' + str(res.get('error', res)))
    if res.get('retry_after_s'):
        print(f'retry_after_s: {res["retry_after_s"]}')
    sys.exit(2)


def read_json_arg(args, flag):
    """``(parsed JSON, args without the flag and its path)`` for ``--flag FILE``.

    Returns ``(None, args)`` unchanged when *flag* is absent, so a caller can tell a
    missing argument from a file that parsed to ``null``.
    """
    if flag in args:
        i = args.index(flag)
        path = args[i + 1]
        with open(path) as f:
            return json.load(f), args[:i] + args[i + 2 :]
    return None, args


def print_failure_notify(cn, tree, task):
    """Executor side: tell the executor to SendMessage the creator right now."""
    if not cn:
        return
    print('TASK FAILED — notify the creator NOW, then stop:')
    msg = (
        f'Session tree {tree} task #{task} FAILED ({cn.get("how", "")}): {cn.get("title", "")}. '
        f'Reason: {(cn.get("summary") or "")[:200]}. Run st report {tree} {task}, then st reset with a sharper brief '
        f'or create a continuation tree.'
    )
    if cn.get('alive') and cn.get('peer_name'):
        print(f'  SendMessage to="{cn["peer_name"]}" message="{msg}"')
    else:
        print(
            f'  creator session {(cn.get("session_id") or "")[:8]} ({cn.get("model")}) is not running; '
            f'its next `st wait`/`st status` shows the failure.'
        )


def problem_report(tree, r):
    """The text ``st wait`` exits with when a task failed or went stale.

    Names every problem task with its status and event, what is blocked behind it,
    whether the tree is about to auto-archive, and the exact next three commands.
    """
    lines = [
        f'TASK FAILED in {tree} "{r.get("title", "")}" — st wait exited early so you act now '
        f'(re-arm with `st wait {tree}` after the reset, or `st wait {tree} --until-archive` to ignore it):'
    ]
    for p in r.get('problems') or []:
        lines.append(f'  #{p["id"]} [{p["status"]}] {p["title"]}  at {p["at"]}  event: {p["event"]}')
        if p.get('summary'):
            lines.append('      ' + p['summary'][:300].replace('\n', ' '))
    if r.get('blocked'):
        lines.append(f'  blocked behind it: {r["blocked"]}')
    if r.get('settled'):
        lines.append(
            f'  the tree is SETTLED (nothing runnable) and auto-archives at {r.get("archive_at")} unless a task is reset'
        )
    ids = [str(p['id']) for p in r.get('problems') or []]
    lines.append(
        f'Now: st report {tree} {ids[0] if ids else "N"}  →  fix by hand if it is an install/permission '
        f'problem, then st reset {tree} {ids[0] if ids else "N"} [--brief FILE]  →  st wait {tree}'
    )
    return '\n'.join(lines)
