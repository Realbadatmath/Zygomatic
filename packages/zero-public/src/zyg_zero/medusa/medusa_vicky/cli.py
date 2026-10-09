# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""medusa_vicky.cli — engine resolution and the `claude -p` subprocess that produces the tokens.

Lines 148-490 of the original medusa_vicky.py, moved verbatim
(2026-10-07 split). No logic changed.
"""

from __future__ import annotations

import json
import medusa_victor
import os
import re
import subprocess
import threading
import time
import uuid
import logging as _zyg_logging

from .constants import (
    ALLOWED_TOOLS,
    CLI_BIN,
    CLI_DIR,
    CLI_MAX_OUTPUT,
    CLI_MAX_TURNS,
    CLI_MODEL,
    CLI_TIMEOUT,
    DEFAULT_ENGINE,
    ENGINES,
    RULES_FILE,
)

from .ledger import (
    _conv_write,
    _partial_clear,
    _partial_write,
)

# The single-file module logged under its own module name; __package__ is
# that same dotted name now that the module is a package, so the logger's
# name is unchanged.
_zyg_log = _zyg_logging.getLogger(__package__)


def _engine(name) -> str:
    """Resolve an engine id, honouring what is switched on.

    A DISABLED engine still resolves to itself when a chat names it, and that is
    deliberate: chats carry their engine, and silently rewriting a Claude chat to
    Dolphin would hand Vicky's local brain a transcript whose memory lives in a
    CLI session it cannot read \u2014 she would answer as a stranger while the panel
    looked continuous, which is the exact failure the engine field exists to
    prevent. The chat stays on its engine, start_job refuses with a reason, and
    switching Sonnet back on resumes it. Only an UNKNOWN engine falls back.
    """
    name = str(name or '').strip().lower()
    return name if name in ENGINES else DEFAULT_ENGINE


def engine_available(name) -> tuple:
    """(can it answer, why not) for one engine \u2014 the single place that decides,
    so the switcher's label and start_job's refusal can never disagree."""
    e = ENGINES[_engine(name)]
    if not e['enabled']:
        return False, (
            'Sonnet is switched off for Vicky \u2014 either switch this chat to a '
            'local engine in the dropdown (it will read the visible transcript as '
            'its memory), or set ZYG_VICKY_CLAUDE=on and restart Medusa, which '
            'resumes the chat from its saved session instead'
        )
    if e['backend'] == 'claude':
        if not (cli_available() and cli_login_present()):
            return False, 'the Claude CLI is not installed, or `claude login` was never run here'
        return True, ''
    v = medusa_victor.info(e['brain'])
    if not v['available']:
        return False, f'Ollama is not answering at {v["url"]}'
    if not v['built']:
        return False, (
            f"the model '{v['wanted']}' is not built \u2014 {v['build']} "
            f'(right now this would answer as {v["model"]} instead)'
        )
    return True, ''


def engine_info() -> list:
    """What the panel's model switcher offers, with each engine's live
    availability — an option that cannot answer is still shown, but labelled,
    rather than silently missing."""
    out = []
    for e in ENGINES.values():
        row = dict(e)
        ok, why = engine_available(e['id'])
        row['available'], row['detail'] = ok, why
        row['model'] = _cli_model() if e['backend'] == 'claude' else medusa_victor.info(e['brain'])['model']
        out.append(row)
    return out


# Never Opus/Fable/Mythos — Vicky is Sonnet, always (standing rule, matches the
# Architecture Studio assistant's _cli_model()).
EXPENSIVE = ('opus', 'fable', 'mythos')


def _cli_model() -> str:
    name = (CLI_MODEL or 'sonnet').strip()
    return 'sonnet' if any(x in name.lower() for x in EXPENSIVE) else name


def cli_available() -> bool:
    return bool(CLI_BIN) and os.path.isfile(CLI_BIN) and os.access(CLI_BIN, os.X_OK)


def cli_login_present() -> bool:
    """The CLI's own login store. Absent = `claude login` was never run here."""
    return os.path.exists(os.path.join(os.path.expanduser('~'), '.claude', '.credentials.json'))


def _cli_env() -> dict:
    """No API key (the CLI would bill it instead of the operator's login), no
    nested-session markers."""
    env = dict(os.environ)
    for k in list(env):
        if k.startswith('ANTHROPIC_') or k in ('CLAUDECODE', 'CLAUDE_CODE_SESSION_ID', 'CLAUDE_CODE_ENTRYPOINT'):
            env.pop(k, None)
    env['CLAUDE_CODE_MAX_OUTPUT_TOKENS'] = str(CLI_MAX_OUTPUT)
    env.setdefault('HOME', os.path.expanduser('~'))
    return env


_UUID_RE = re.compile(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}')


def _is_uuid(s: str) -> bool:
    return bool(_UUID_RE.fullmatch(str(s or '').lower()))


def vicky_rules() -> str:
    """The ONLY behavioral rules Vicky is given, read fresh every single turn —
    never cached, so an edit to this file takes effect on the very next message."""
    try:
        with open(RULES_FILE, encoding='utf-8') as fh:
            return fh.read().strip()
    except OSError:
        return ''


def system_prompt() -> str:
    rules = vicky_rules()
    return (
        'You are Vicky, the AI assistant embedded in the Medusa app. You run as a '
        "Claude Sonnet subprocess rooted in Medusa's own folder, with your own "
        'project settings. The rules below are your ONLY standing instructions — '
        'nothing from any other project, port, or session applies to you; if you '
        "have no memory of some other app's conventions, that is correct, not a "
        'gap.\n\n'
        + (
            rules
            or '(No Medusa-specific rules have been written yet — use ordinary '
            "engineering judgement and stay inside this app's own folder.)"
        )
    )


def _cli_cmd(job: dict, system: str, fresh: bool) -> list:
    cmd = [
        CLI_BIN,
        '-p',
        '--model',
        _cli_model(),
        '--output-format',
        'stream-json',
        '--input-format',
        'stream-json',
        '--include-partial-messages',
        '--verbose',
        '--system-prompt',
        system,
        '--allowedTools',
        ALLOWED_TOOLS,
        '--permission-mode',
        'acceptEdits',
        '--setting-sources',
        'project',
        '--max-turns',
        str(CLI_MAX_TURNS),
    ]
    sid = str(job['body'].get('session') or '')
    if _is_uuid(sid) and not fresh:
        cmd += ['--resume', sid]
        job['_resumed'] = True
    else:
        sid = str(uuid.uuid4())
        cmd += ['--session-id', sid]
        job['_resumed'] = False
    job['session'] = sid
    return cmd


def _cli_first_message(text: str, attachments: list | None = None) -> str:
    """Build the stream-json user message, optionally with image content blocks.

    Images are passed as base64 content blocks — the Claude CLI's stream-json
    input format supports the same multimodal content the API does.  Videos
    have no native input-format support, so the file path is prepended to the
    text so Vicky can locate and describe the file with her own tools.
    """
    content: list[dict] = []
    for att in attachments or []:
        t = att.get('type', '')
        if t == 'image':
            content.append(
                {'type': 'image', 'source': {'type': 'base64', 'media_type': att['mime_type'], 'data': att['data_b64']}}
            )
        elif t == 'video' and att.get('path'):
            text = f'[User uploaded a video file at: {att["path"]}]\n\n' + text
    content.append({'type': 'text', 'text': text})
    return json.dumps({'type': 'user', 'message': {'role': 'user', 'content': content}}) + '\n'


def _kill(p):
    try:
        p.kill()
    except Exception as _exc:  # noqa: BLE001
        _zyg_log.debug('suppressed %s: %s', type(_exc).__name__, _exc)


def _run_cli(job: dict, log, user_text: str, system: str, attachments: list | None = None) -> str:
    """Drive one `claude -p` turn for the job. Because Vicky's tools are the
    CLI's own built-in Read/Write/Edit/Glob/Grep/Bash (not an MCP shim routed
    back through this server, like arch_assistant), the subprocess runs its
    whole agentic loop internally; we only stream the events out."""
    os.makedirs(CLI_DIR, exist_ok=True)
    if not cli_login_present():
        log('NOTE: no Claude login found (~/.claude/.credentials.json) — run `claude login` on this machine')
    text = user_text
    last_err = ''
    for attempt in (1, 2):
        fresh = attempt == 2 or not _is_uuid(str(job['body'].get('session') or ''))
        cmd = _cli_cmd(job, system, fresh)
        log(f"claude: {_cli_model()} on the operator's login" + ('' if fresh else ' (resuming the conversation)'))
        p = subprocess.Popen(
            cmd,
            cwd=CLI_DIR,
            env=_cli_env(),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding='utf-8',
            errors='replace',
            bufsize=1,
        )
        job['_proc'] = p
        err_lines: list[str] = []
        # Both closures bind this attempt's process and buffer as defaults: a second attempt
        # rebinds `p`/`err_lines`, and a late thread must still see the ones it was started for.
        threading.Thread(
            target=lambda proc=p, lines=err_lines: lines.extend(proc.stderr.read().splitlines()[-40:]),
            daemon=True,
        ).start()
        watchdog = threading.Timer(CLI_TIMEOUT, lambda proc=p: _kill(proc))
        watchdog.daemon = True
        watchdog.start()
        result = None
        try:
            try:
                p.stdin.write(_cli_first_message(text, attachments))
                p.stdin.close()
            except OSError as _exc:
                _zyg_log.debug('suppressed %s: %s', type(_exc).__name__, _exc)
            for line in p.stdout:
                line = line.strip()
                if not line.startswith('{'):
                    continue
                try:
                    ev = json.loads(line)
                except ValueError as _exc:
                    _zyg_log.debug('suppressed %s: %s', type(_exc).__name__, _exc)
                    continue
                result = _cli_event(job, ev, log) or result
                if job['cancel']:
                    _kill(p)
                    raise RuntimeError('cancelled')
            p.wait(timeout=30)
        finally:
            watchdog.cancel()
            job['_proc'] = None
        err = '\n'.join(err_lines).strip()
        if result is None:
            last_err = err[-400:] or f'the CLI exited with code {p.returncode} without a result'
            if not fresh and re.search(r'session|conversation', err, re.I):
                log('NOTE: the old conversation could not be resumed — starting a new one')
                continue
            raise RuntimeError(last_err)
        u = result.get('usage') or {}
        job['usage'] = {
            'in': int(u.get('input_tokens') or 0),
            'out': int(u.get('output_tokens') or 0),
            'cache_read': int(u.get('cache_read_input_tokens') or 0),
            'cache_write': int(u.get('cache_creation_input_tokens') or 0),
            'cost_usd': round(float(result.get('total_cost_usd') or 0), 4),
            'model': job.get('model') or _cli_model(),
            'turns': int(result.get('num_turns') or 0),
        }
        if result.get('session_id'):
            job['session'] = result['session_id']
        return str(job.get('reply') or result.get('result') or '').strip()
    raise RuntimeError(last_err or 'the CLI did not answer')


def _cli_event(job: dict, ev: dict, log):
    """One stream-json line from the CLI -> job state. Returns the result event
    when this line is it, else None. Mirrors arch_assistant._cli_event's
    thinking-stream handling."""
    t = ev.get('type')
    if t == 'system' and ev.get('subtype') == 'init':
        job['model'] = ev.get('model') or _cli_model()
        src = ev.get('apiKeySource')
        job['auth'] = 'login' if src in (None, '', 'none') else f'api-key:{src}'
        log(f'claude: {job["model"]} · auth {job["auth"]}')
        if job['auth'] != 'login':
            log('WARNING: an API key reached the CLI — the spawn env strips ANTHROPIC_* so this should be impossible')
    elif t == 'stream_event':
        e = ev.get('event') or {}
        et = e.get('type')
        job['_partials'] = True
        if et == 'content_block_start':
            cb = e.get('content_block') or {}
            job['_blk'] = cb.get('type')
            job['_blk_t0'] = time.time()
            if cb.get('type') == 'thinking':
                job['_think'] = ''
                job['thinking'] = ''
                _partial_clear(job)
            elif cb.get('type') == 'text':
                job['reply_live'] = ''
        elif et == 'content_block_delta':
            d = e.get('delta') or {}
            if d.get('type') == 'thinking_delta':
                job['_think'] = (job.get('_think') or '') + (d.get('thinking') or '')
                job['thinking'] = job['_think'][-1500:]
                _partial_write(job)
            elif d.get('type') == 'text_delta':
                job['reply_live'] = ((job.get('reply_live') or '') + (d.get('text') or ''))[-2000:]
        elif et == 'content_block_stop':
            if job.get('_blk') == 'thinking':
                _add_thought(job, job.get('_think') or '', time.time() - (job.get('_blk_t0') or time.time()), log)
                _partial_clear(job)
            job['_blk'] = None
            job['thinking'] = ''
            job['_think'] = ''
    elif t == 'assistant':
        for b in (ev.get('message') or {}).get('content') or []:
            bt = b.get('type')
            if bt == 'thinking' and not job.get('_partials') and (b.get('thinking') or '').strip():
                _add_thought(job, b['thinking'], 0.0, log)
            elif bt == 'text' and (b.get('text') or '').strip():
                job['steps'] += 1
                job['reply'] = b['text'].strip()
                job['reply_live'] = ''
                log('assistant: ' + job['reply'][:200])
            elif bt == 'tool_use':
                job['steps'] += 1
                name = str(b.get('name') or 'tool')
                arg_txt = ', '.join(f'{k}={v}' for k, v in list((b.get('input') or {}).items())[:4])
                log(f'{name}({arg_txt[:160]})')
    elif t == 'rate_limit_event':
        info = ev.get('rate_limit_info') or {}
        if info.get('status') not in (None, 'allowed'):
            log(f'NOTE: Claude login rate limit: {info.get("status")} ({info.get("rateLimitType")})')
    elif t == 'result':
        return ev
    return None


def _add_thought(job: dict, text: str, secs: float, log):
    text = (text or '').strip()
    if not text:
        return
    secs = round(max(0.0, secs), 1)
    job.setdefault('thoughts', []).append({'text': text, 's': secs})
    job['think_s'] = round((job.get('think_s') or 0) + secs, 1)
    log(f'thought {secs:g}s: ' + text[:160].replace('\n', ' '))
    # every finished thought is written to the ledger whole, as it ends — a
    # restart mid-request must not silently drop it (same lesson as arch_assistant).
    _conv_write({'event': 'thought', 'id': job.get('id'), 'n': len(job['thoughts']), 's': secs, 'text': text})
