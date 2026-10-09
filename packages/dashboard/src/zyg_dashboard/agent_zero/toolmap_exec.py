# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Executing one tool of the map -- in process, as the calling user, under a risk gate.

This module is the ``execute_tool`` of CONTRACT C. Three things make it what it is:

* **The caller's own session authorises the call.** A dashboard route is not re-invented
  here and no internal back door exists: the tool is dispatched through the live Flask
  app's ``test_client`` carrying the browser's own session cookie and CSRF token, so
  every ``require_login`` / ``localhost`` / CSRF gate the dashboard already has decides
  the outcome. Agent Zero can do exactly what the person talking to it can do.
* **Danger is a gate, not a label.** A tool classed ``danger`` (destructive, or costly in
  GPU hours or Claude quota) refuses to run and answers ``needs_confirmation`` with a
  ``confirm_id``; the runner shows the sentence to the operator and only
  :func:`execute_confirmed` -- once, within 30 minutes -- actually fires it.
* **Everything is logged.** One JSON line per execution in
  ``data/runtime/zero_tool_log.jsonl``: timestamp, actor, tool, risk, outcome, duration,
  HTTP status and the argument *names*. Never the argument values -- a brief or a prompt
  can carry anything, and the log is not the place for it.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import time
import uuid

from . import _host, toolmap

_log = logging.getLogger(__name__)

#: Pending danger calls awaiting the operator's yes: confirm_id -> {tool, args, ts}.
PENDING: dict = {}

#: How long a confirmation request stays valid.
PENDING_TTL_S = 30 * 60

#: Response bodies are cut here before they reach a model's context.
MAX_TEXT = 6000

#: JSON data files are cut here (20 kB).
MAX_JSON = 20_000

_SERVICE_TIMEOUT_S = 10
_SHELL_TIMEOUT_S = 20
_GREP_TIMEOUT_S = 10

#: Root of the code sandbox: the directory that carries the dashboard sources, its
#: ``tests/`` and the ``apitests/`` route inventory. In the flatter pre-monorepo tree
#: that was the package's grandparent; here the package sits two levels deeper
#: (``packages/dashboard/src/zyg_dashboard/agent_zero/``), so four ``dirname`` hops reach
#: the same structural directory, ``packages/dashboard``. Relative paths a model passes to
#: ``code.read`` / ``data.read_json`` are resolved against it.
_CREWS_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
_DOCS_DIR = os.path.join(os.path.dirname(os.path.dirname(_CREWS_DIR)), 'docs')
_SANDBOX_ROOTS = (_CREWS_DIR, _DOCS_DIR)

_ROUTES_JSON = os.path.join(_CREWS_DIR, 'apitests', 'routes.json')
_LOG_NAME = 'zero_tool_log.jsonl'

#: grep flags that keep dated backup copies and caches out of every answer. crews/ is
#: full of ``.bak-*`` siblings and ``.tts_*_backups_*`` trees; a hit in one of those is
#: a hit in dead code, and it crowds out the live file.
_SKIP_DIRS = (
    '--exclude-dir=.*',
    '--exclude-dir=__pycache__',
    '--exclude-dir=node_modules',
    '--exclude-dir=output',
    '--exclude=.*',
)

_SYMBOL_RE = re.compile(r'^[A-Za-z_][A-Za-z_0-9]*$')
_PLACEHOLDER_RE = re.compile(r'\{([a-zA-Z_][a-zA-Z_0-9]*)\}')


def _result(ok: bool, text: str, ms: int = 0, risk: str = 'read', confirm_id=None, status=None) -> dict:
    out = {
        'ok': bool(ok),
        'text': text,
        'ms': int(ms),
        'risk': risk,
        'needs_confirmation': confirm_id is not None,
        'confirm_id': confirm_id,
    }
    if status is not None:
        out['status'] = status
    return out


# ── the entry point ──────────────────────────────────────────────────────────


def execute(name: str, args: dict, cookie: str = '', csrf: str = '', confirmed: bool = False, actor: str = '') -> dict:
    """Run one meta-tool call (``zero_index`` / ``zero_find`` / ``zero_call``)."""
    args = dict(args or {})
    if name == 'zero_index':
        group = str(args.get('group') or '').strip()
        if not group:
            return _result(True, toolmap.index_text())
        return _result(True, toolmap.group_text(group))
    if name == 'zero_find':
        return _result(True, _find_text(str(args.get('query') or '')))
    if name != 'zero_call':
        return _result(False, f'unknown tool {name!r}. Use zero_index, zero_find or zero_call.')

    tool_id = str(args.get('tool') or '').strip()
    call_args = dict(args.get('args') or {})
    confirm = bool(confirmed or args.get('confirm'))
    return call(tool_id, call_args, cookie=cookie, csrf=csrf, confirmed=confirm, actor=actor)


def call(tool_id: str, args: dict, cookie: str = '', csrf: str = '', confirmed: bool = False, actor: str = '') -> dict:
    """Run one mapped tool by id, applying the risk gate."""
    tool = toolmap.get(tool_id)
    if tool is None:
        return _result(False, f'unknown tool {tool_id!r}. Closest ids: {_closest(tool_id)}')
    risk = tool.get('risk', 'read')
    if risk == 'danger' and not confirmed:
        confirm_id = uuid.uuid4().hex
        _expire_pending()
        PENDING[confirm_id] = {'tool': tool_id, 'args': dict(args or {}), 'ts': time.time()}
        text = (
            f'CONFIRMATION REQUIRED: {tool.get("title", tool_id)} '
            f'({toolmap.target(tool)}) — ask the user; it is a destructive or costly action.'
        )
        return _result(False, text, risk=risk, confirm_id=confirm_id)
    return _run(tool, dict(args or {}), cookie, csrf, actor)


def _closest(tool_id: str) -> str:
    """The five ids a mistyped tool name most likely meant."""
    import difflib

    ids = [tool['id'] for tool in toolmap.catalog()]
    hits = difflib.get_close_matches(tool_id or '', ids, n=5, cutoff=0.4)
    hits += [hit['id'] for hit in toolmap.find(tool_id or '', limit=5) if hit['id'] not in hits]
    return ', '.join(hits[:5]) or 'none'


def execute_confirmed(confirm_id: str, cookie: str = '', csrf: str = '', actor: str = '') -> dict:
    """Run a danger call the operator has agreed to. Each ``confirm_id`` works once."""
    _expire_pending()
    entry = PENDING.pop(str(confirm_id or ''), None)
    if entry is None:
        return _result(False, f'unknown or expired confirmation {confirm_id!r}')
    return call(entry['tool'], entry['args'], cookie=cookie, csrf=csrf, confirmed=True, actor=actor)


def pending_tool(confirm_id: str):
    """The tool id a confirmation is waiting on, without consuming it."""
    _expire_pending()
    entry = PENDING.get(str(confirm_id or ''))
    return entry['tool'] if entry else None


def _expire_pending() -> None:
    cutoff = time.time() - PENDING_TTL_S
    for key in [key for key, row in PENDING.items() if row['ts'] < cutoff]:
        PENDING.pop(key, None)


def _find_text(query: str) -> str:
    hits = toolmap.find(query, limit=10)
    if not hits:
        return f'no tool matches {query!r}. Call zero_index() for the groups.'
    lines = [f'{len(hits)} match(es) for {query!r}:']
    lines += [toolmap.tool_line(hit) for hit in hits]
    return '\n'.join(lines)


# ── dispatch ─────────────────────────────────────────────────────────────────


def _run(tool: dict, args: dict, cookie: str, csrf: str, actor: str) -> dict:
    kind = tool.get('kind', 'http')
    started = time.time()
    try:
        if kind == 'http':
            out = _run_http(tool, args, cookie, csrf)
        elif kind == 'service':
            out = _run_service(tool, args)
        elif kind == 'code':
            out = _run_code(tool, args)
        elif kind == 'shell':
            out = _run_shell(tool)
        else:
            out = _result(False, f'tool {tool["id"]} has unsupported kind {kind!r}')
    except Exception as exc:  # noqa: BLE001 - a tool must never raise into the model
        _log.warning('toolmap_exec: %s raised %s', tool['id'], exc)
        out = _result(False, f'{tool["id"]} failed: {type(exc).__name__}: {exc}')
    out['ms'] = int((time.time() - started) * 1000)
    out['risk'] = tool.get('risk', 'read')
    out.setdefault('needs_confirmation', False)
    out.setdefault('confirm_id', None)
    _audit(tool, args, out, actor)
    return out


def _fill_path(template: str, args: dict) -> tuple:
    """Substitute ``{name}`` placeholders from ``args``.

    Returns ``(path, leftover args, missing placeholder names)``.
    """
    rest = dict(args)
    missing = []

    def _sub(match):
        name = match.group(1)
        if name in rest:
            return str(rest.pop(name))
        missing.append(name)
        return match.group(0)

    path = _PLACEHOLDER_RE.sub(_sub, template or '')
    return path, rest, missing


def _run_http(tool: dict, args: dict, cookie: str, csrf: str) -> dict:
    app = _host.app()
    if app is None:
        return _result(False, 'the dashboard application is not importable in this process')
    path, rest, missing = _fill_path(tool.get('path', ''), args)
    if missing:
        return _result(False, f'{tool["id"]} needs path parameter(s): {", ".join(missing)}')
    method = (tool.get('method') or 'GET').upper()
    body = dict(tool.get('body') or {})
    body.update(rest)

    headers = {}
    if cookie:
        headers['Cookie'] = 'session=' + cookie
    if csrf and method not in ('GET', 'HEAD'):
        headers['X-CSRF-Token'] = csrf

    # use_cookies=False is load-bearing, not tidiness: werkzeug's test client rewrites
    # (and, with an empty jar, DELETES) the request's Cookie header from its own cookie
    # jar, so a hand-set 'Cookie: session=...' silently disappears and every gated route
    # answers 401. A jar-less client is also the right shape here -- one tool call must
    # carry exactly the caller's session and keep no state of its own.
    client = app.test_client(use_cookies=False)
    kwargs = {'headers': headers, 'environ_base': {'REMOTE_ADDR': '127.0.0.1'}}
    if method in ('GET', 'HEAD'):
        if body:
            kwargs['query_string'] = {key: _flat(value) for key, value in body.items()}
    else:
        kwargs['json'] = body
    resp = client.open(path, method=method, **kwargs)
    text = _body_text(resp.get_data(as_text=True), resp.content_type or '')
    ok = 200 <= resp.status_code < 300
    head = f'{method} {path} -> {resp.status_code}'
    return _result(ok, f'{head}\n{text}', risk=tool.get('risk', 'read'), status=resp.status_code)


def _flat(value):
    return json.dumps(value) if isinstance(value, (dict, list)) else value


def _body_text(raw: str, content_type: str) -> str:
    """Pretty-print JSON compactly, then truncate -- a model pays for every byte."""
    text = raw or ''
    if 'json' in (content_type or '') or text[:1] in ('{', '['):
        try:
            text = json.dumps(json.loads(text), indent=0, default=str)
        except ValueError:
            pass
    return _truncate(text)


def _truncate(text: str, limit: int = MAX_TEXT) -> str:
    raw = text or ''
    if len(raw) <= limit:
        return raw
    return raw[:limit] + f'… (truncated, {len(raw.encode("utf-8"))} bytes)'


def _run_service(tool: dict, args: dict) -> dict:
    import requests

    url_template = tool.get('url', '')
    if '{ollama_url}' in url_template:
        url_template = url_template.replace('{ollama_url}', _host.ollama_url())
    url, rest, missing = _fill_path(url_template, args)
    if missing:
        return _result(False, f'{tool["id"]} needs path parameter(s): {", ".join(missing)}')
    method = (tool.get('method') or 'GET').upper()
    if method != 'GET' and tool.get('risk') not in ('act', 'danger'):
        return _result(False, f'{tool["id"]} may only be called with GET')
    try:
        if method == 'GET':
            resp = requests.get(url, params=rest or None, timeout=_SERVICE_TIMEOUT_S)
        else:
            resp = requests.request(method, url, json=rest or None, timeout=_SERVICE_TIMEOUT_S)
    except requests.RequestException as exc:
        return _result(False, f'{method} {url} unreachable: {type(exc).__name__}: {exc}')
    text = _body_text(resp.text, resp.headers.get('Content-Type', ''))
    ok = 200 <= resp.status_code < 300
    return _result(ok, f'{method} {url} -> {resp.status_code}\n{text}', status=resp.status_code)


def _run_shell(tool: dict) -> dict:
    """Run the fixed argv of a shell tool. No user argument ever reaches this."""
    argv = list(tool.get('argv') or [])
    if not argv:
        return _result(False, f'{tool["id"]} has no argv')
    binary = shutil.which(argv[0])
    if not binary:
        return _result(False, f'{argv[0]} is not on PATH')
    try:
        proc = subprocess.run(
            [binary] + argv[1:], capture_output=True, text=True, timeout=_SHELL_TIMEOUT_S, check=False
        )
    except subprocess.TimeoutExpired:
        return _result(False, f'{" ".join(argv)} timed out after {_SHELL_TIMEOUT_S}s')
    text = (proc.stdout or '') + (('\n' + proc.stderr) if proc.stderr else '')
    return _result(proc.returncode == 0, _truncate(text.strip()), status=proc.returncode)


# ── code & docs handlers ─────────────────────────────────────────────────────


def _run_code(tool: dict, args: dict) -> dict:
    handler = _CODE_HANDLERS.get(tool['id'])
    if handler is None:
        return _result(False, f'no handler for code tool {tool["id"]}')
    return handler(args)


def _resolve(path: str):
    """Resolve a caller-supplied path inside the sandbox, or return (None, reason).

    The sandbox is ``crews/`` plus the repository's ``docs/``. Secrets are refused even
    inside it: dotenv files, anything named like a credential, and JSON under ``data/``
    whose name mentions a key or a token.
    """
    raw = str(path or '').strip()
    if not raw:
        return None, 'path is required'
    candidate = raw if os.path.isabs(raw) else os.path.join(_CREWS_DIR, raw)
    real = os.path.realpath(candidate)
    if not any(real == root or real.startswith(root + os.sep) for root in _SANDBOX_ROOTS):
        return None, f'{raw!r} is outside the sandbox (crews/ and docs/ only)'
    base = os.path.basename(real).lower()
    if base.startswith('.env') or base.endswith('.env'):
        return None, f'{raw!r} is refused: environment files are never readable'
    if 'credential' in real.lower() or 'secret' in base:
        return None, f'{raw!r} is refused: credentials are never readable'
    if base.endswith('.json') and ('key' in base or 'token' in base):
        return None, f'{raw!r} is refused: key/token files are never readable'
    if not os.path.isfile(real):
        return None, f'{raw!r} not found'
    return real, ''


def _rel(path: str) -> str:
    for root in _SANDBOX_ROOTS:
        if path.startswith(root + os.sep):
            return os.path.relpath(path, root)
    return path


def _code_read(args: dict) -> dict:
    real, why = _resolve(str(args.get('path') or ''))
    if real is None:
        return _result(False, why)
    try:
        start = max(1, int(args.get('start') or 1))
    except (TypeError, ValueError):
        start = 1
    try:
        count = int(args.get('lines') or 200)
    except (TypeError, ValueError):
        count = 200
    count = max(1, min(count, 200))
    with open(real, encoding='utf-8', errors='replace') as fh:
        lines = fh.readlines()
    chunk = lines[start - 1 : start - 1 + count]
    head = f'{_rel(real)} lines {start}-{start + len(chunk) - 1} of {len(lines)}'
    body = ''.join(f'{start + i}: {line}' for i, line in enumerate(chunk))
    return _result(True, _truncate(f'{head}\n{body}'))


def _docs_read(args: dict) -> dict:
    real, why = _resolve(str(args.get('path') or ''))
    if real is None:
        return _result(False, why)
    with open(real, encoding='utf-8', errors='replace') as fh:
        text = fh.read()
    return _result(True, _truncate(f'{_rel(real)}\n{text}'))


def _data_read_json(args: dict) -> dict:
    real, why = _resolve(str(args.get('path') or ''))
    if real is None:
        return _result(False, why)
    if not real.endswith('.json'):
        return _result(False, f'{_rel(real)} is not a .json file')
    try:
        with open(real, encoding='utf-8') as fh:
            data = json.load(fh)
    except ValueError as exc:
        return _result(False, f'{_rel(real)} is not valid JSON: {exc}')
    return _result(True, f'{_rel(real)}\n' + _truncate(json.dumps(data, indent=0, default=str), MAX_JSON))


def _code_find_route(args: dict) -> dict:
    query = str(args.get('query') or '').strip().lower()
    if not query:
        return _result(False, 'query is required')
    try:
        with open(_ROUTES_JSON, encoding='utf-8') as fh:
            inventory = json.load(fh)
    except (OSError, ValueError) as exc:
        return _result(False, f'route inventory unavailable: {exc}')
    hits = []
    for app_name, rows in (inventory.get('apps') or {}).items():
        for row in rows:
            haystack = f'{row.get("rule", "")} {row.get("endpoint", "")} {row.get("func", "")}'.lower()
            if query in haystack:
                methods = ','.join(row.get('methods') or [])
                flag = ' DANGER' if row.get('danger') else ''
                hits.append(
                    f'{app_name}: {methods} {row.get("rule")} -> {row.get("endpoint")} '
                    f'({row.get("func")}, gate={row.get("gate")}){flag}'
                )
            if len(hits) >= 30:
                break
    if not hits:
        return _result(True, f'no route matches {query!r}')
    return _result(True, _truncate(f'{len(hits)} route(s) matching {query!r}:\n' + '\n'.join(hits)))


def _code_find_symbol(args: dict) -> dict:
    name = str(args.get('name') or '').strip()
    if not _SYMBOL_RE.match(name):
        return _result(False, 'name must be a plain python identifier')
    argv = ['grep', '-rn', '--include=*.py', *_SKIP_DIRS, '-E', rf'^(def|class|async def) {name}\b', _CREWS_DIR]
    return _grep_result(argv, 30, f'definitions of {name}')


def _code_grep(args: dict) -> dict:
    pattern = str(args.get('pattern') or '')
    if not pattern:
        return _result(False, 'pattern is required')
    glob = str(args.get('glob') or '*.py')
    ripgrep = shutil.which('rg') or shutil.which('ugrep')
    if ripgrep:
        argv = [ripgrep, '-n', '--no-heading', '--max-count', '5', '-g', glob, '-e', pattern, _CREWS_DIR, _DOCS_DIR]
    else:
        argv = ['grep', '-rn', f'--include={glob}', *_SKIP_DIRS, '-E', pattern, _CREWS_DIR, _DOCS_DIR]
    return _grep_result(argv, 50, f'{pattern!r} in {glob}')


def _docs_search(args: dict) -> dict:
    query = str(args.get('query') or '').strip()
    if not query:
        return _result(False, 'query is required')
    argv = ['grep', '-rn', '-i', '-B', '1', '-A', '1', '--include=*.md', '-F', query, _CREWS_DIR, _DOCS_DIR]
    return _grep_result(argv, 20 * 4, f'{query!r} in the docs')


def _grep_result(argv: list, max_hits: int, what: str) -> dict:
    try:
        proc = subprocess.run(argv, capture_output=True, text=True, timeout=_GREP_TIMEOUT_S, check=False)
    except subprocess.TimeoutExpired:
        return _result(False, f'search for {what} timed out after {_GREP_TIMEOUT_S}s')
    if proc.returncode not in (0, 1):
        return _result(False, f'search failed: {_truncate(proc.stderr.strip(), 400)}')
    lines = [line for line in (proc.stdout or '').splitlines() if line.strip()]
    shown = [_rel(line) for line in lines[:max_hits]]
    rest = len(lines) - len(shown)
    head = f'{len(lines)} hit(s) for {what}' + (f', first {len(shown)}' if rest > 0 else '')
    if not lines:
        return _result(True, f'no hits for {what}')
    return _result(True, _truncate(head + ':\n' + '\n'.join(shown)))


_CODE_HANDLERS = {
    'code.read': _code_read,
    'code.grep': _code_grep,
    'code.find_route': _code_find_route,
    'code.find_symbol': _code_find_symbol,
    'docs.search': _docs_search,
    'docs.read': _docs_read,
    'data.read_json': _data_read_json,
}


# ── audit ────────────────────────────────────────────────────────────────────


def log_path() -> str:
    """``data/runtime/zero_tool_log.jsonl`` -- one line per executed tool."""
    return os.path.join(_host.runtime_dir(), _LOG_NAME)


def _audit(tool: dict, args: dict, out: dict, actor: str) -> None:
    row = {
        'ts': time.strftime('%Y-%m-%dT%H:%M:%S'),
        'actor': actor or '',
        'tool': tool['id'],
        'risk': tool.get('risk', 'read'),
        'ok': bool(out.get('ok')),
        'ms': int(out.get('ms') or 0),
        'status': out.get('status'),
        'args_keys': sorted(str(key) for key in (args or {})),
    }
    try:
        with open(log_path(), 'a', encoding='utf-8') as fh:
            fh.write(json.dumps(row) + '\n')
    except OSError as exc:
        _log.warning('toolmap_exec: cannot append to the tool log (%s)', exc)
