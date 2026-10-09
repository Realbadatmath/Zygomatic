# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The Claude Code CLI backend.

Moved verbatim out of the old single-file arch_assistant.py (lines 2806-3233).
"""

from __future__ import annotations

import json
import os
import re
import secrets
import subprocess
import sys
import threading
import time
import uuid

from zyg_workflows.arch_assistant._base import _zyg_log

# ── Claude Code CLI backend (2026-09-07) ─────────────────────────────────────
_UUID_RE = re.compile(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}')


def _is_uuid(s: str) -> bool:
    return bool(_UUID_RE.fullmatch(str(s or '').lower()))


def cli_available() -> bool:
    return bool(CLI_BIN) and os.path.isfile(CLI_BIN) and os.access(CLI_BIN, os.X_OK)


def cli_login_present() -> bool:
    """The CLI's own login store. Absent = `claude login` was never run here."""
    return os.path.exists(os.path.join(os.path.expanduser('~'), '.claude', '.credentials.json'))


def _cli_model(job: dict | None = None) -> str:
    """Never Opus/Fable here (standing rule): those burn the shared quota for a
    tool-mapping task. Anything expensive becomes sonnet.
    2026-09-17 CONTEST EXCEPTION: a job whose body carries `contest: true` AND
    `cli_model` runs on that model verbatim — the operator's own planner/worker
    A/B through the headless driver; the studio tab never sends the flag."""
    if job is not None:
        body = job.get('body') or {}
        want = str(body.get('cli_model') or '').strip()
        if want and body.get('contest'):
            return want
    name = (CLI_MODEL or 'sonnet').strip()
    return 'sonnet' if any(x in name.lower() for x in EXPENSIVE) else name


def _cli_env() -> dict:
    """The spawn environment: no API key (the CLI would bill it instead of the
    login), no nested-session markers, generous MCP timeouts for `look`."""
    env = dict(os.environ)
    for k in list(env):
        if k.startswith('ANTHROPIC_') or k in ('CLAUDECODE', 'CLAUDE_CODE_SESSION_ID', 'CLAUDE_CODE_ENTRYPOINT'):
            env.pop(k, None)
    env['MCP_TIMEOUT'] = '30000'
    env['MCP_TOOL_TIMEOUT'] = str(180 * 1000)  # a `look` waits up to 120 s for the studio
    env['CLAUDE_CODE_MAX_OUTPUT_TOKENS'] = str(CLI_MAX_OUTPUT)  # 2026-09-10: the CLI ceiling, not its 32k default
    env.setdefault('HOME', os.path.expanduser('~'))
    return env


def _mcp_config(job: dict) -> str:
    return json.dumps(
        {
            'mcpServers': {
                MCP_SERVER: {
                    'command': sys.executable,
                    'args': [SHIM],
                    'env': {
                        'ARCH_ASSIST_URL': SERVER_URL,
                        'ARCH_ASSIST_JOB': job['id'],
                        'ARCH_ASSIST_TOKEN': job['_token'],
                    },
                }
            }
        }
    )


def _cli_cmd(job: dict, system: str, fresh: bool) -> list:
    cmd = [
        CLI_BIN,
        '-p',
        '--model',
        _cli_model(job),
        '--output-format',
        'stream-json',
        '--input-format',
        'stream-json',
        '--include-partial-messages',
        '--verbose',
        '--system-prompt',
        system,
        '--mcp-config',
        _mcp_config(job),
        '--strict-mcp-config',
        '--tools',
        '',
        '--allowedTools',
        'mcp__' + MCP_SERVER,
        '--permission-mode',
        'dontAsk',
        '--max-turns',
        str(MAX_CALLS + CLI_TURN_HEADROOM),
        '--setting-sources',
        '',
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


def _cli_first_message(text: str, image) -> str:
    """One stream-json user turn: the viewport shot (if any) + the request."""
    content = []
    if image:
        content.append({'type': 'image', 'source': {'type': 'base64', 'media_type': image[0], 'data': image[1]}})
    content.append({'type': 'text', 'text': text})
    return json.dumps({'type': 'user', 'message': {'role': 'user', 'content': content}}) + '\n'


def _history_text(turns) -> str:
    lines = []
    for t in turns or []:
        txt = str(t.get('text') or '').strip()
        if txt:
            lines.append(('assistant: ' if t.get('role') == 'assistant' else 'user: ') + txt[:800])
    return '\n'.join(lines)[-6000:]


def server_summary(job: dict, d) -> str:
    """The summary the SERVER writes when the model never called done — never the
    model's last half sentence. It is made of what is actually on the drawing:
    what was built, what the design check says, what the programme still wants."""
    u = job.get('usage') or {}
    turns = int(u.get('turns') or job.get('steps') or 0)
    added = list(getattr(d, 'added', None) or []) if d is not None else []
    removed = list(getattr(d, 'removed', None) or []) if d is not None else []
    parts = [f'UNFINISHED — the run stopped after {turns} turns without calling done.']
    kinds: dict[str, int] = {}
    for oid in added:
        rec = d.find(oid)
        if rec:
            kinds[rec['kind']] = kinds.get(rec['kind'], 0) + 1
    top = ', '.join(f'{v} {k}' for k, v in sorted(kinds.items(), key=lambda kv: -kv[1])[:8])
    parts.append(f'Built: +{len(added)} −{len(removed)}' + (f' ({top}).' if top else '.'))
    findings = design_findings(d) if d is not None else []
    errs = [f for f in findings if f.get('sev') == 'error']
    warns = [f for f in findings if f.get('sev') == 'warn']
    texts = '; '.join(str(f.get('text') or '').split(' — ')[0] for f in (errs + warns)[:4])
    parts.append(f'Design check: {len(errs)} errors, {len(warns)} warnings' + (f': {texts}.' if texts else '.'))
    mod = EXT_MODULES.get('building_program')
    prog = None
    if mod is not None and d is not None:
        try:
            prog = mod.get_program(d)
        except Exception:  # noqa: BLE001
            prog = None
    if prog:
        try:
            rows = mod.status(d, prog)
        except Exception:  # noqa: BLE001
            rows = []
        miss = [str(r.get('title') or r.get('key')) for r in rows if r.get('need') == 'required' and not r.get('ok')]
        parts.append('Programme: required items not built: ' + (', '.join(miss[:8]) if miss else 'none') + '.')
        un = prog.get('unmapped')
        if un:
            parts.append(
                'Request words without evidence: '
                + (', '.join(str(x) for x in un) if isinstance(un, (list, tuple)) else str(un))
                + '.'
            )
    return ' '.join(parts)


def _run_cli(job: dict, d: Drawing, log, user_text: str, image, system: str) -> str:
    """Drive one `claude -p` turn for the job. Tool calls come back through the
    shim → /assistant/tool → shim_tool(), which draws on `d` and sets
    job['_final'] (done) or job['question'] (ask_user). Returns the summary."""
    os.makedirs(CLI_DIR, exist_ok=True)
    job['_token'] = secrets.token_hex(12)
    job['_d'] = d
    job['_final'] = ''
    if not cli_login_present():
        log('NOTE: no Claude login found (~/.claude/.credentials.json) — run `claude login` on this machine')
    text = user_text
    hist = _history_text(job['body'].get('history'))
    last_err = ''
    for attempt in (1, 2):
        fresh = attempt == 2 or not _is_uuid(str(job['body'].get('session') or ''))
        cmd = _cli_cmd(job, system, fresh)
        if fresh and hist:
            text = (
                'Earlier conversation (for context; the drawing summary below is current):\n'
                + hist
                + '\n\n'
                + user_text
            )
        log(f"claude: {_cli_model(job)} on the operator's login" + ('' if fresh else ' (resuming the conversation)'))
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
        threading.Thread(
            target=lambda el=err_lines, pr=p: el.extend(pr.stderr.read().splitlines()[-40:]), daemon=True
        ).start()
        watchdog = threading.Timer(CLI_TIMEOUT, lambda pr=p: _kill(pr))
        watchdog.daemon = True
        watchdog.start()
        result = None
        try:
            try:
                p.stdin.write(_cli_first_message(text, image))
                p.stdin.close()
            except OSError as _exc:
                _zyg_log.warning('CLI stdin write failed, the run gets no prompt: %s', _exc)
            for line in p.stdout:
                line = line.strip()
                if not line.startswith('{'):
                    continue
                try:
                    ev = json.loads(line)
                except ValueError as _exc:
                    _zyg_log.debug('non-JSON CLI output line skipped: %s', _exc)
                    continue
                result = _cli_event(job, ev, log, p) or result
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
            'model': job.get('model') or _cli_model(job),
            'turns': int(result.get('num_turns') or 0),
        }
        if result.get('session_id'):
            job['session'] = result['session_id']
        au = _audit()
        if au:
            try:
                au.record(
                    source='claude_code',
                    direction='exchange',
                    llm=job['usage']['model'],
                    backend='claude',
                    model=job['usage']['model'],
                    input_tokens=job['usage']['in'],
                    output_tokens=job['usage']['out'],
                    cache_read_input_tokens=job['usage']['cache_read'],
                    cache_creation_input_tokens=job['usage']['cache_write'],
                    cost_usd=job['usage']['cost_usd'],
                    duration_ms=result.get('duration_ms'),
                    num_turns=result.get('num_turns'),
                    subtype=result.get('subtype'),
                    session_id=job.get('session'),
                    think_s=job.get('think_s'),
                    thoughts_n=len(job.get('thoughts') or []),
                    request=str(job['body'].get('text') or '')[:500],
                    response=str(job.get('_final') or job.get('reply') or result.get('result') or '')[:1000],
                )
            except Exception as _exc:  # noqa: BLE001
                _zyg_log.warning('assistant ledger record failed for job %s: %s', job.get('id'), _exc)
        # 2026-09-10: the run that never called done. Job 71ac02b0 ended subtype
        # 'error_max_turns' at 29 turns with NO done call and was still handed to
        # the operator as status 'done' with the model's half sentence "Now the
        # aerial:" as the summary. Nothing is thrown away — the drawing injects as
        # it always did — but the summary is written by the SERVER from the drawing
        # itself and the job is marked incomplete, so the panel, the job view and
        # the ledger all say the run stopped short.
        if not (job.get('_final') or job.get('question')):
            sub = str(result.get('subtype') or ('error' if result.get('is_error') else 'no_done_call'))
            job['incomplete'] = True
            job['stop'] = sub
            model_text = str(job.get('reply') or result.get('result') or '').strip()
            note = server_summary(job, d)
            log(f'UNFINISHED ({sub}): the model never called done — the server wrote the summary')
            job['reply'] = (model_text + '\n\n' + note) if model_text else note
            return job['reply']
        return str(job.get('_final') or job.get('reply') or result.get('result') or '').strip()
    raise RuntimeError(last_err or 'the CLI did not answer')


def _cli_event(job: dict, ev: dict, log, p=None):
    """One stream-json line from the CLI -> job state. Returns the result event
    when this line is it, else None.
    Thinking (2026-09-07): the CLI is spawned with --include-partial-messages,
    so the model's thinking arrives as `stream_event` deltas. The live tail
    goes to job['thinking'] (the panel's wait bubble shows it as it is
    written), the finished block to job['thoughts'] with its seconds — the
    "Thought for N s" line the operator knows from claude.ai. The final
    `assistant` event carries the same block whole; it is the fallback when
    no deltas came (a model whose thinking display is omitted)."""
    t = ev.get('type')
    if t == 'system' and ev.get('subtype') == 'init':
        bad = [s for s in (ev.get('mcp_servers') or []) if s.get('status') != 'connected']
        if bad or not ev.get('mcp_servers'):
            if p is not None:
                _kill(p)
            raise RuntimeError(
                'the drawing tools did not connect to the CLI: '
                + (', '.join(f'{s.get("name")}={s.get("status")}' for s in bad) or 'no MCP server')
            )
        job['model'] = ev.get('model') or _cli_model(job)
        # 2026-09-10: which credential the CLI actually used. _cli_env() strips every
        # ANTHROPIC_* variable so this must always be the operator's login; anything
        # else means the spawn env leaked a key and the run is being BILLED.
        src = ev.get('apiKeySource')
        job['auth'] = 'login' if src in (None, '', 'none') else f'api-key:{src}'
        log(f'claude: {job["model"]} · auth {job["auth"]} · tools connected')
        if job['auth'] != 'login':
            log('WARNING: an API key reached the CLI — the spawn env strips ANTHROPIC_* so this should be impossible')
        if ev.get('session_id'):  # 2026-09-07 night: the ledger learns the CLI session at once,
            job['_sid'] = ev['session_id']  # so a killed run can still be tied to its transcript
            _conv_write(
                {
                    'event': 'session',
                    'id': job.get('id'),
                    'session': ev['session_id'],
                    'transcript': _transcript_src(ev['session_id']),
                }
            )
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
                _partial_clear(job)  # a new block starts: nothing unfinished on disk any more
            elif cb.get('type') == 'text':
                job['reply_live'] = ''
        elif et == 'content_block_delta':
            d = e.get('delta') or {}
            if d.get('type') == 'thinking_delta':
                job['_think'] = (job.get('_think') or '') + (d.get('thinking') or '')
                job['thinking'] = job['_think'][-1500:]
                _partial_write(job)  # 2026-09-08: throttled mirror — a kill keeps the block so far
            elif d.get('type') == 'text_delta':
                job['reply_live'] = ((job.get('reply_live') or '') + (d.get('text') or ''))[-2000:]
        elif et == 'content_block_stop':
            if job.get('_blk') == 'thinking':
                _add_thought(job, job.get('_think') or '', time.time() - (job.get('_blk_t0') or time.time()), log)
                _partial_clear(job)  # the whole thought is a ledger line now
            job['_blk'] = None
            job['thinking'] = ''
            job['_think'] = ''
    elif t == 'assistant':
        for b in (ev.get('message') or {}).get('content') or []:
            bt = b.get('type')
            if bt == 'thinking' and not job.get('_partials') and (b.get('thinking') or '').strip():
                _add_thought(job, b['thinking'], 0.0, log)  # no deltas came: record the whole block
            elif bt == 'text' and (b.get('text') or '').strip():
                job['steps'] += 1
                job['reply'] = b['text'].strip()
                job['reply_live'] = ''
                log('assistant: ' + job['reply'][:200])
            elif bt == 'tool_use':
                job['steps'] += 1
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
        # 2026-09-08: an EMPTY finished thinking block is the signature of
        # `thinking.display = "omitted"`, which is the DEFAULT on Sonnet 5 and
        # Opus 5 (Sonnet 4.6 defaults to "summarized", which is the only reason
        # thoughts appear at all). Without this line a model bump would keep
        # writing thought lines with no text and nobody would know the ledger
        # had gone blind. Pin `display` explicitly before changing the model.
        n = job['_empty_thoughts'] = int(job.get('_empty_thoughts') or 0) + 1
        if n == 3:
            log(
                'WARNING: 3 empty thinking blocks — this model appears to send '
                'thinking.display="omitted"; the thought ledger is blind until display is pinned'
            )
        return
    secs = round(max(0.0, secs), 1)
    job.setdefault('thoughts', []).append({'text': text, 's': secs})  # whole — no cap (was 4000 chars)
    job['think_s'] = round((job.get('think_s') or 0) + secs, 1)
    log(f'thought {secs:g}s: ' + text[:160].replace('\n', ' '))
    # 2026-09-07 night: every finished thought is written to the ledger as it ends, whole. Before this the
    # thoughts lived only in the job dict until the end line, so a restart mid-request took them with it.
    _conv_write({'event': 'thought', 'id': job.get('id'), 'n': len(job['thoughts']), 's': secs, 'text': text})


def _kill(p):
    try:
        p.kill()
    except Exception as _exc:  # noqa: BLE001
        _zyg_log.warning('watchdog kill of the CLI process failed: %s', _exc)


def _shim_job(q: dict):
    j = JOBS.get(str(q.get('id') or ''))
    tok = str(q.get('token') or '')
    if not j or not j.get('_token') or not tok or not secrets.compare_digest(tok, j['_token']):
        return None
    return j


# Imported here, at the foot of the module, because these names are used only inside
# function bodies and their modules import this one back: by this line every name
# above is already bound, so the call-time cycle resolves either way round.
from zyg_workflows.arch_assistant.config import (  # noqa: E402
    CLI_BIN,
    CLI_DIR,
    CLI_MAX_OUTPUT,
    CLI_MODEL,
    CLI_TIMEOUT,
    CLI_TURN_HEADROOM,
    EXPENSIVE,
    MAX_CALLS,
    MCP_SERVER,
    SERVER_URL,
    SHIM,
)
from zyg_workflows.arch_assistant.drawing import Drawing  # noqa: E402
from zyg_workflows.arch_assistant.ground import EXT_MODULES  # noqa: E402
from zyg_workflows.arch_assistant.backends import _audit  # noqa: E402
from zyg_workflows.arch_assistant.gate import design_findings  # noqa: E402
from zyg_workflows.arch_assistant.ledger import (  # noqa: E402
    _conv_write,
    _partial_clear,
    _partial_write,
    _transcript_src,
)
from zyg_workflows.arch_assistant.jobs import JOBS  # noqa: E402
