#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""nomologin_assistant.py — the persona assistant, on the operator's Claude login.

Backend is the Claude Code CLI (`claude -p --model opus`), NOT the API. The operator's
words on the architecture assistant apply here too: "through my subscription, not API".
That makes the spawn environment load-bearing — see `_env()`.

One job = one persona. The persona id is baked into the MCP server's environment, so no
tool in the job can reach another account; a job about one brand cannot wander into
another's inbox. The assistant's whole job is operating accounts that are ALREADY signed
in: if it meets a login wall it is told to stop and say so, not to try credentials.

State: jobs live in memory while they run and land in a per-day ledger when they finish, so
a board restart leaves a record of what was done to a live account rather than a gap.

Deliberately NOT importable-with-side-effects: there is no _close_orphans() at import here.
The architecture assistant's module writes false `killed` records into the live ledger the
moment it is imported, which makes any smoke test destructive; this one folds orphans only
when `boot()` is called explicitly.
"""

from __future__ import annotations

import json
import logging as _zyg_logging
import os
import subprocess
import sys
import threading
import time
import uuid
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from zyg_zero import nomologin as nl  # noqa: E402
from zyg_zero import nomologin_browser as nb  # noqa: E402

_zyg_log = _zyg_logging.getLogger(__name__)


CLI = os.environ.get('ZYG_NOMOLOGIN_CLI', 'claude')
SHIM = os.path.join(HERE, 'nomologin_mcp_shim.py')

RUNTIME = os.path.join(nl.ROOT, 'assistant')
CWD = os.path.join(RUNTIME, 'cli')  # no CLAUDE.md here, on purpose
LEDGER = os.path.join(RUNTIME, 'conversations')

# The operator asked for Opus on this one. Unlike the architecture assistant — where the
# task is tool mapping and Haiku does it for a tenth of the quota — the work here is
# reading an unfamiliar page and deciding what to click, which is what the bigger model is
# actually for. It is still quota: keep requests specific rather than open-ended.
#
# Pinned to the explicit id, NOT the `opus` alias: on CLI 2.1.74 the alias resolves to
# claude-opus-4-6 (measured — the init event said so), which is not what "run it on Opus"
# was asked for. An alias also moves under you on a CLI upgrade; an id does not.
MODEL = os.environ.get('ZYG_NOMOLOGIN_MODEL', 'claude-opus-5')

MAX_TURNS = int(os.environ.get('ZYG_NOMOLOGIN_MAX_TURNS', '40'))
CLI_TIMEOUT = float(os.environ.get('ZYG_NOMOLOGIN_CLI_TIMEOUT', '1800'))
CLI_MAX_OUTPUT = os.environ.get('ZYG_NOMOLOGIN_CLI_OUT', '64000')

_JOBS: dict[str, dict] = {}
_LOCK = threading.Lock()


SYSTEM = """You operate ONE social account persona for its owner, through a browser that is
already signed in and a mailbox that belongs to it. You are working on live accounts: every
click is real and most are not undoable.

WHAT YOU ARE FOR
Maintaining accounts that already exist — posting, replying, reading notifications, and
pulling back numbers (views, likes, followers, reach) from each platform's own analytics
pages and emailed reports.

WHAT YOU DO NOT DO
- You never sign in, register, or create an account. The sessions you use were signed into
  by hand. If you hit a login wall, a "verify it's you" challenge or a captcha, STOP and
  report exactly what you saw. Do not type credentials. Do not work around it.
- You never post anything the operator did not ask for, and you never guess at wording for
  something public. If a post's text is not given to you, ask for it.
- You do not delete, unfollow, block, or change account settings unless told to in the
  request you were given.

HOW TO WORK THE BROWSER
- Call `page` before every click. Indexes come from the last `page` call and shift whenever
  the page repaints.
- Pass `expect` with the label you believe is at that index. If it no longer matches, the
  click is refused rather than landing on the wrong control — that guard is there because a
  misplaced click on a live account can publish something.
- After an action that should change the page, look again before assuming it worked.
- `text` for reading content, `look` (a screenshot) when a layout or a chart will not
  explain itself in text.
- Prefer `tab` as a url substring over a tab number; the operator may be clicking too.

MAIL
- `mail_codes` finds sign-in codes and confirm links. Codes expire in minutes: check the
  timestamp and say so if the newest one is already stale rather than using it anyway.
- Open a confirm link with `mail_open_link`, never by navigating to it yourself — these are
  bound to the persona's session and exit IP.
- The mailbox is read-only to you. You cannot send, reply or delete.

REPORTING
Finish with what you actually did and what you saw, in the language the request was written
in. Name the numbers you read rather than summarising them away. If something did not work,
say what stopped you and where it stopped — half a posting flow that failed silently is far
worse than one that says where it stuck.
"""


def _now() -> float:
    return time.time()


def _day() -> str:
    return datetime.now(timezone.utc).strftime('%Y-%m-%d')


def available() -> dict:
    """Whether the assistant can run at all — checked before the panel offers a box."""
    out = {'model': MODEL, 'shim_ok': os.path.isfile(SHIM)}
    try:
        v = subprocess.run([CLI, '--version'], capture_output=True, text=True, timeout=15)
        out['cli'] = v.stdout.strip()
        out['cli_ok'] = v.returncode == 0
    except (OSError, subprocess.SubprocessError) as exc:
        out['cli'], out['cli_ok'] = str(exc), False
    out['browser'] = nb.available()
    out['ok'] = bool(out.get('cli_ok') and out['shim_ok'] and out['browser'].get('ok'))
    return out


def _env(persona: str) -> dict:
    """The spawn environment, and the reason this function exists.

    The CLI prefers an API key over the login whenever one is set, so a stray ANTHROPIC_*
    in the parent environment silently moves the whole job onto metered API billing while
    everything still appears to work. The .env on this box HAS such a key. Strip them.
    """
    env = {k: v for k, v in os.environ.items() if not k.startswith('ANTHROPIC_') and k != 'CLAUDECODE'}
    env['NOMOLOGIN_PERSONA'] = persona
    env['CLAUDE_CODE_MAX_OUTPUT_TOKENS'] = CLI_MAX_OUTPUT
    # The tools open a real browser window's pages; the child needs the display for the
    # same reason launch() does (the DISPLAY trap — a supervised service has no X).
    gui, _ = nl.gui_env(env)
    return gui


def _mcp_config(persona: str) -> str:
    cfg = {
        'mcpServers': {
            'nomo': {
                'command': sys.executable,
                'args': [SHIM],
                'env': {'NOMOLOGIN_PERSONA': persona},
            }
        }
    }
    return json.dumps(cfg)


def _ledger_write(row: dict) -> None:
    os.makedirs(LEDGER, exist_ok=True)
    path = os.path.join(LEDGER, f'{_day()}.jsonl')
    with open(path, 'a', encoding='utf-8') as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + '\n')


def _set(jid: str, **kw) -> None:
    with _LOCK:
        job = _JOBS.get(jid)
        if job:
            job.update(kw)


def _log(jid: str, line: str) -> None:
    with _LOCK:
        job = _JOBS.get(jid)
        if job is not None:
            job['log'].append(line[:500])
            del job['log'][:-200]


def ask(persona: str, text: str, session: str | None = None, max_turns: int | None = None) -> dict:
    """Start a job. Returns immediately; poll view(jid)."""
    nl.get_persona(persona)
    text = (text or '').strip()
    if not text:
        raise ValueError('nothing asked')

    jid = uuid.uuid4().hex[:12]
    job = {
        'id': jid,
        'persona': persona,
        'text': text,
        'status': 'running',
        'started': _now(),
        'model': MODEL,
        'session': session,
        'steps': 0,
        'tools': [],
        'thoughts': [],
        'reply': None,
        'error': None,
        'log': [],
        'usage': {},
    }
    with _LOCK:
        _JOBS[jid] = job
    _ledger_write(
        {
            'event': 'start',
            'id': jid,
            'persona': persona,
            'text': text,
            'model': MODEL,
            'session': session,
            'at': nl._iso(_now()),
        }
    )
    threading.Thread(target=_run, args=(jid, max_turns or MAX_TURNS), daemon=True).start()
    return view(jid)


def _run(jid: str, max_turns: int) -> None:
    job = _JOBS[jid]
    persona = job['persona']
    os.makedirs(CWD, exist_ok=True)

    argv = [
        CLI,
        '-p',
        '--model',
        MODEL,
        '--output-format',
        'stream-json',
        '--input-format',
        'stream-json',
        '--include-partial-messages',
        '--verbose',
        '--system-prompt',
        SYSTEM,
        '--mcp-config',
        _mcp_config(persona),
        '--strict-mcp-config',
        # No built-ins: this job has no business reading the filesystem, running shell
        # commands or searching the web. Its whole world is the persona's browser and
        # mailbox. Without this the CLI still reached for ToolSearch (measured).
        '--tools',
        '',
        '--allowedTools',
        'mcp__nomo',
        '--permission-mode',
        'dontAsk',
        '--max-turns',
        str(max_turns),
        '--setting-sources',
        '',
    ]
    if job.get('session'):
        argv += ['--resume', job['session']]

    proc = None
    try:
        proc = subprocess.Popen(
            argv,
            cwd=CWD,
            env=_env(persona),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        first = {'type': 'user', 'message': {'role': 'user', 'content': [{'type': 'text', 'text': job['text']}]}}
        proc.stdin.write(json.dumps(first) + '\n')
        proc.stdin.flush()
        proc.stdin.close()

        errs: list[str] = []
        threading.Thread(target=_drain_err, args=(proc, errs), daemon=True).start()

        deadline = _now() + CLI_TIMEOUT
        for line in proc.stdout:
            if _now() > deadline:
                proc.kill()
                raise TimeoutError(f'the assistant ran past {CLI_TIMEOUT:g}s and was stopped')
            line = line.strip()
            if not line:
                continue
            try:
                _event(jid, json.loads(line))
            except json.JSONDecodeError:
                _log(jid, line)

        proc.wait(timeout=30)
        if job['status'] == 'running':
            if proc.returncode == 0 and job.get('reply'):
                _set(jid, status='done')
            else:
                tail = ' '.join(errs[-4:])[:400] or f'exit {proc.returncode}'
                _set(jid, status='error', error=tail)
    except Exception as exc:  # noqa: BLE001
        if proc and proc.poll() is None:
            proc.kill()
        _set(jid, status='error', error=f'{type(exc).__name__}: {exc}'[:400])
    finally:
        _set(jid, finished=_now())
        _finish(jid)


def _drain_err(proc, errs: list) -> None:
    for line in proc.stderr:
        line = line.strip()
        if line:
            errs.append(line)
            del errs[:-40]


def _event(jid: str, ev: dict) -> None:
    """Fold one stream-json event into the job."""
    kind = ev.get('type')

    if kind == 'system' and ev.get('subtype') == 'init':
        _set(jid, session=ev.get('session_id'))
        # Proof the login is being used and not a key. If this ever reads anything but
        # "none", a stray ANTHROPIC_* got through _env() and the job is on API billing.
        _log(jid, f'init: model={ev.get("model")} apiKeySource={ev.get("apiKeySource")}')
        return

    if kind == 'assistant':
        msg = ev.get('message') or {}
        for block in msg.get('content') or []:
            btype = block.get('type')
            if btype == 'text' and block.get('text', '').strip():
                _set(jid, reply=block['text'])
            elif btype == 'thinking':
                # NOTE: on Opus 5 the API default for thinking display is `omitted`, so
                # this block routinely arrives EMPTY. An empty thought list here means the
                # model did not send one, not that it did not think.
                t = (block.get('thinking') or '').strip()
                if t:
                    with _LOCK:
                        _JOBS[jid]['thoughts'].append(t)
            elif btype == 'tool_use':
                name = str(block.get('name', '')).replace('mcp__nomo__', '')
                with _LOCK:
                    job = _JOBS[jid]
                    job['steps'] += 1
                    job['tools'].append({'name': name, 'input': block.get('input') or {}, 'at': _now()})
                    del job['tools'][:-60]
                _log(jid, f'tool {name}')
        if msg.get('usage'):
            _set(jid, usage=msg['usage'])
        return

    if kind == 'result':
        if ev.get('is_error'):
            _set(jid, status='error', error=str(ev.get('result'))[:400])
        else:
            if ev.get('result'):
                _set(jid, reply=str(ev['result']))
            _set(jid, status='done')
        if ev.get('usage'):
            _set(jid, usage=ev['usage'])
        _set(jid, cost_usd=ev.get('total_cost_usd'))


def _finish(jid: str) -> None:
    job = _JOBS.get(jid)
    if not job:
        return
    _ledger_write(
        {
            'event': 'end',
            'id': jid,
            'persona': job['persona'],
            'status': job['status'],
            'text': job['text'],
            'reply': job.get('reply'),
            'error': job.get('error'),
            'steps': job['steps'],
            'tools': job['tools'],
            'thoughts': job['thoughts'],
            'session': job.get('session'),
            'usage': job.get('usage'),
            'seconds': round((job.get('finished') or _now()) - job['started'], 1),
            'log': job['log'][-60:],
            'at': nl._iso(_now()),
        }
    )


def view(jid: str) -> dict:
    with _LOCK:
        job = _JOBS.get(jid)
        if not job:
            return {'ok': False, 'error': f'no job {jid}'}
        out = {k: v for k, v in job.items() if k != 'log'}
    out['ok'] = True
    out['seconds'] = round((out.get('finished') or _now()) - out['started'], 1)
    out['tools'] = [{'name': t['name'], 'input': t['input']} for t in out['tools'][-30:]]
    return out


def active() -> list[dict]:
    with _LOCK:
        return [
            {
                'id': j['id'],
                'persona': j['persona'],
                'text': j['text'][:120],
                'steps': j['steps'],
                'seconds': round(_now() - j['started'], 1),
            }
            for j in _JOBS.values()
            if j['status'] == 'running'
        ]


def history(day: str | None = None, n: int = 40) -> list[dict]:
    path = os.path.join(LEDGER, f'{day or _day()}.jsonl')
    if not os.path.isfile(path):
        return []
    rows = []
    with open(path, encoding='utf-8') as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as _exc:
                _zyg_log.debug('suppressed %s: %s', type(_exc).__name__, _exc)
                continue
            if row.get('event') == 'end':
                rows.append(row)
    return rows[-n:][::-1]


def boot() -> dict:
    """Fold conversations a restart killed. Called EXPLICITLY by the board at startup —
    never at import, so importing this module for a smoke test cannot rewrite history."""
    path = os.path.join(LEDGER, f'{_day()}.jsonl')
    if not os.path.isfile(path):
        return {'closed': 0}
    starts, ends = {}, set()
    with open(path, encoding='utf-8') as fh:
        for line in fh:
            try:
                row = json.loads(line)
            except json.JSONDecodeError as _exc:
                _zyg_log.debug('suppressed %s: %s', type(_exc).__name__, _exc)
                continue
            if row.get('event') == 'start':
                starts[row['id']] = row
            elif row.get('event') == 'end':
                ends.add(row['id'])
    orphans = [r for i, r in starts.items() if i not in ends]
    for row in orphans:
        _ledger_write(
            {
                'event': 'end',
                'id': row['id'],
                'persona': row.get('persona'),
                'status': 'killed',
                'text': row.get('text'),
                'error': 'the board restarted while the assistant was working',
                'steps': 0,
                'tools': [],
                'thoughts': [],
                'at': nl._iso(_now()),
            }
        )
    return {'closed': len(orphans)}


if __name__ == '__main__':  # the CLI lives in nomologin_assistant_cli
    from zyg_zero.nomologin_assistant_cli import cli_main as _cli_main

    raise SystemExit(_cli_main())
