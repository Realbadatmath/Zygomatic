# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later
"""subscription.py — Agent Zero on the operator's Claude Max login. The default backend.

Why this exists. A Claude subscription can only be spent through Claude Code, never
through the API, so one Zero turn on Opus 5 is one headless `claude -p` turn on the
operator's login — the path subscription_llm.py (the documentary pipeline) and
arch_assistant.py (the Architecture Studio assistant) already prove. No API key is
ever used here: the spawn environment has every ANTHROPIC_* variable stripped, and a
key that leaked in would be billed instead of the subscription.

How the tools get there. The CLI reaches tools only over MCP, so Zero's meta-tools
are served to it by ../mcp_shim.py, a stdio JSON-RPC server the CLI itself spawns
from the `--mcp-config` written per turn. The shim is stateless: tools/list and
tools/call come straight back to the dashboard (routes_mcp.py), which runs them with
the turn's own `ctx.execute_tool`. The model therefore sees `mcp__zero__<tool>`; the
prefix is stripped off both sides. Because the bridge already executed the call and
recorded it, this module NEVER calls ctx.execute_tool itself — it only reports the
tool_use / tool_result blocks the CLI streams back.

Where the tokens land. The CLI runs with cwd = data/runtime/agent_zero/cli and
writes its transcripts under ~/.claude/projects/<encoded cwd>/; that folder is how
the quota meter (Metrics > Quota) attributes Zero's spend to Zero rather than to the
pipeline. Do not change the cwd without moving the meter with it.

The per-turn MCP secret is written to `ctx.extra['mcp_token']` BEFORE the process
starts (and mirrored onto `ctx.extra['turn'].mcp_token` when the runner put the Turn
there); routes_mcp.py reads it from the same place. See routes_mcp's docstring.

`python3 -m agent_zero.backends.subscription --dry-run` prints the argv and the
mcp-config a turn would use, without spawning anything.
"""

import json
import logging
import os
import secrets
import subprocess
import sys
import threading
import time
import uuid
from collections.abc import Iterator

from typing import Any

from .. import _host
from ..contracts import TurnContext

_log = logging.getLogger(__name__)

SERVER_NAME = 'zero'
TOOL_PREFIX = 'mcp__' + SERVER_NAME + '__'
SHIM = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'mcp_shim.py')
DASHBOARD_URL = (os.environ.get('ZERO_DASHBOARD_URL', '') or 'http://127.0.0.1:5000').rstrip('/')
TURN_HEADROOM = 2  # the model's own answer turns on top of its tool calls
CANCEL_POLL_S = 0.5
MCP_TOOL_TIMEOUT_MS = 300 * 1000  # a tool call may block on the dashboard for the shim's 300 s
MCP_TIMEOUT_MS = 30 * 1000

NO_LOGIN = 'No Claude login on this machine: run `claude login` as the operator'
LIMIT_MSG = "Claude's session or weekly limit refused the turn — pick a local model or wait for the reset"
FALLBACK_LIMIT_WORDS = (
    'rate limit',
    'usage limit',
    'weekly limit',
    'session limit',
    'limit reached',
    'rejected',
    "you've hit",
)


# ── the spawn ────────────────────────────────────────────────────────────────


def _limit_words() -> tuple:
    sl = _host.subscription_llm()
    words = getattr(sl, '_LIMIT_WORDS', None) if sl is not None else None
    return tuple(words) if words else FALLBACK_LIMIT_WORDS


def _is_limit(text: str) -> bool:
    low = str(text or '').lower()
    return any(w in low for w in _limit_words())


def _env(ctx: TurnContext) -> dict:
    """The spawn environment. subscription_llm._env does the load-bearing part: it
    strips ANTHROPIC_* / CLAUDE_CODE_* / CLAUDECODE (a parent Claude Code session's
    plumbing must not reach a turn that is not its child) and sets the output cap and
    CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC. Zero pins the thinking budget itself
    because the picker exposes it per model."""
    sl = _host.subscription_llm()
    env_fn: Any = getattr(sl, '_env', None) if sl is not None else None
    env: dict[str, str]
    if callable(env_fn):
        raw_env: Any = env_fn(int(ctx.max_output_tokens or 4096))
        env = dict(raw_env)
    else:
        _log.warning('subscription_llm is not importable — using the local env fallback')
        env = _fallback_env(int(ctx.max_output_tokens or 4096))
    env['MAX_THINKING_TOKENS'] = str(int(ctx.thinking_tokens or 0))
    env['MCP_TIMEOUT'] = str(MCP_TIMEOUT_MS)
    env['MCP_TOOL_TIMEOUT'] = str(MCP_TOOL_TIMEOUT_MS)
    return env


def _fallback_env(max_tokens: int) -> dict:
    env = dict(os.environ)
    for k in list(env):
        if k.startswith(('ANTHROPIC_', 'CLAUDE_CODE_')) or k == 'CLAUDECODE':
            env.pop(k, None)
    env['CLAUDE_CODE_MAX_OUTPUT_TOKENS'] = str(max(16000, min(64000, 2 * max(1, max_tokens))))
    env['CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC'] = '1'
    env.setdefault('HOME', os.path.expanduser('~'))
    return env


def _mcp_config(ctx: TurnContext, token: str) -> str:
    """The --mcp-config JSON *string* the CLI parses. The ZERO_MCP_* values ride in
    this server's own env block, not in the CLI's environment, so the secret and the
    user's cookie never appear in the spawn env of the model process."""
    return json.dumps(
        {
            'mcpServers': {
                SERVER_NAME: {
                    'command': sys.executable,
                    'args': [SHIM],
                    'env': {
                        'ZERO_MCP_URL': DASHBOARD_URL,
                        'ZERO_MCP_TURN': str(ctx.turn_id or ''),
                        'ZERO_MCP_TOKEN': token,
                        'ZERO_MCP_COOKIE': str(ctx.cookie or ''),
                        'ZERO_MCP_CSRF': str(ctx.csrf or ''),
                    },
                }
            }
        }
    )


def _cmd(ctx: TurnContext, cli_bin: str, mcp_json: str) -> list:
    """A fresh --session-id every turn: the conversation is carried in the folded
    content blocks (see _content_blocks), not in the CLI's own resume store, because
    Zero's session store is the single source of truth for history and compaction."""
    return [
        cli_bin,
        '-p',
        '--model',
        str(ctx.model or ''),
        '--output-format',
        'stream-json',
        '--input-format',
        'stream-json',
        '--include-partial-messages',
        '--verbose',
        '--system-prompt',
        str(ctx.system or ''),
        '--mcp-config',
        mcp_json,
        '--strict-mcp-config',
        '--tools',
        '',
        '--allowedTools',
        'mcp__' + SERVER_NAME,
        '--permission-mode',
        'dontAsk',
        '--max-turns',
        str(int(ctx.max_tool_calls or 0) + TURN_HEADROOM),
        '--setting-sources',
        '',
        '--session-id',
        str(uuid.uuid4()),
    ]


def _sdk_blocks(messages: list) -> list:
    """CONTRACT C blocks -> the SDK shape subscription_llm._content_blocks folds.
    Only images differ: the contract carries media_type/data flat, the SDK nests
    them under `source`."""
    out = []
    for m in messages or []:
        if not isinstance(m, dict):
            continue
        content = m.get('content')
        if isinstance(content, list):
            blocks = []
            for b in content:
                if isinstance(b, dict) and b.get('type') == 'image' and 'data' in b:
                    blocks.append(
                        {
                            'type': 'image',
                            'source': {
                                'type': 'base64',
                                'media_type': b.get('media_type') or 'image/png',
                                'data': b.get('data') or '',
                            },
                        }
                    )
                else:
                    blocks.append(b)
            content = blocks
        out.append({'role': m.get('role') or 'user', 'content': content})
    return out


def _content_blocks(messages: list) -> list:
    """The whole conversation folded into ONE user message: prior assistant turns
    quoted as '[Assistant earlier in this conversation]', images passed through."""
    sl = _host.subscription_llm()
    fold: Any = getattr(sl, '_content_blocks', None) if sl is not None else None
    sdk = _sdk_blocks(messages)
    if callable(fold):
        folded: Any = fold(sdk)
        return list(folded)
    return _fallback_fold(sdk)


def _fallback_fold(messages: list) -> list:
    blocks: list = []
    for m in messages:
        role, content = m.get('role'), m.get('content')
        prefix = '' if role == 'user' else '[Assistant earlier in this conversation]\n'
        if isinstance(content, str):
            blocks.append({'type': 'text', 'text': prefix + content})
            continue
        for b in content or []:
            if not isinstance(b, dict):
                blocks.append({'type': 'text', 'text': prefix + str(b)})
            elif b.get('type') == 'image' and isinstance(b.get('source'), dict):
                blocks.append({'type': 'image', 'source': b['source']})
            elif b.get('type') == 'text':
                blocks.append({'type': 'text', 'text': prefix + str(b.get('text') or '')})
            else:
                blocks.append({'type': 'text', 'text': prefix + json.dumps(b, default=str)[:4000]})
    if not any(b.get('type') == 'text' and b['text'].strip() for b in blocks):
        blocks.append({'type': 'text', 'text': 'Answer as instructed.'})
    return blocks


def _kill(p) -> None:
    try:
        p.kill()
    except Exception:  # noqa: BLE001, S110 — a process that is already gone needs no handling
        pass


def _watch(p, ctx: TurnContext, deadline: float, stop: threading.Event, state: dict) -> None:
    """Cancel + timeout in one thread: the reader below blocks on the CLI's stdout,
    so nothing in the main flow can poll. Whoever fires kills the process, which
    closes stdout and ends the read loop."""
    while not stop.wait(CANCEL_POLL_S):
        if ctx.cancel is not None and ctx.cancel.is_set():
            state['reason'] = 'cancelled'
            _kill(p)
            return
        if time.time() >= deadline:
            state['reason'] = 'timeout'
            _kill(p)
            return


# ── the turn ─────────────────────────────────────────────────────────────────


def run(ctx: TurnContext) -> Iterator[dict]:
    """Run one turn as a headless ``claude -p`` on the operator's Claude Max login.

    The CONTRACT C backend entry point: yields the usual event stream and ends with
    exactly one ``done``. Tools do not run here -- the CLI reaches them over MCP, so
    this spawns mcp_shim.py with a fresh per-turn ``token`` and lets the bridge call
    ``ctx.execute_tool``. A missing login or CLI is an ``auth`` error rather than an
    exception, because it is the one failure the operator can actually act on.
    """
    cli_bin = _host.claude_cli_bin()
    if not _host.claude_login_present() or not os.path.exists(cli_bin):
        yield {'type': 'error', 'kind': 'auth', 'message': NO_LOGIN}
        yield {'type': 'done', 'stop_reason': 'error'}
        return
    token = secrets.token_urlsafe(24)
    if not isinstance(ctx.extra, dict):
        ctx.extra = {}
    ctx.extra['mcp_token'] = token
    turn = ctx.extra.get('turn')
    if isinstance(turn, dict):  # runner.TURNS entries are plain dicts
        turn['mcp_token'] = token
    elif turn is not None:
        try:
            turn.mcp_token = token
        except AttributeError:  # a frozen Turn: ctx.extra is authoritative anyway
            _log.warning('could not mirror the mcp token onto the Turn object')
    cli_dir = os.path.join(_host.runtime_dir(), 'agent_zero', 'cli')
    os.makedirs(cli_dir, exist_ok=True)
    mcp_json = _mcp_config(ctx, token)
    blocks = _content_blocks(ctx.messages)
    verdict = {}
    for attempt in (0, 1):
        verdict = yield from _attempt(ctx, cli_bin, cli_dir, mcp_json, blocks)
        if verdict.get('kind') != 'retry' or attempt:
            break
        _log.warning('subscription turn %s: %s — retrying once', ctx.turn_id, verdict.get('message'))
    kind = verdict.get('kind')
    if kind == 'ok':
        yield {'type': 'done', 'stop_reason': verdict.get('stop_reason') or 'end_turn'}
        return
    if kind == 'cancelled':
        yield {'type': 'done', 'stop_reason': 'cancelled'}
        return
    if kind == 'limit':
        yield {'type': 'error', 'kind': 'limit', 'message': LIMIT_MSG}
    else:
        yield {
            'type': 'error',
            'kind': 'backend',
            'message': verdict.get('message') or 'the Claude Code turn produced no result',
        }
    yield {'type': 'done', 'stop_reason': 'error'}


def _attempt(ctx: TurnContext, cli_bin: str, cli_dir: str, mcp_json: str, blocks: list) -> Iterator[dict]:
    """One `claude -p` process. Yields the turn's events and returns a verdict dict
    {'kind': 'ok'|'retry'|'limit'|'cancelled'|'error', ...}; run() turns that into the
    single done/error pair."""
    cmd = _cmd(ctx, cli_bin, mcp_json)
    p = subprocess.Popen(
        cmd,
        cwd=cli_dir,
        env=_env(ctx),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding='utf-8',
        errors='replace',
        bufsize=1,
    )
    stdin, stdout, stderr = p.stdin, p.stdout, p.stderr
    if stdin is None or stdout is None or stderr is None:  # pragma: no cover - PIPE was requested above
        raise RuntimeError('claude subprocess pipes were not created')
    err_lines: list = []
    err_reader = threading.Thread(
        target=lambda: err_lines.extend((stderr.read() or '').splitlines()[-40:]), daemon=True
    )
    err_reader.start()
    stop, state = threading.Event(), {'reason': ''}
    watcher = threading.Thread(
        target=_watch, args=(p, ctx, time.time() + max(1, int(ctx.timeout_s or 900)), stop, state), daemon=True
    )
    watcher.start()
    result, limited = None, ''
    names: dict = {}
    delta_idx: set = set()
    try:
        try:
            stdin.write(json.dumps({'type': 'user', 'message': {'role': 'user', 'content': blocks}}) + '\n')
            stdin.close()
        except (BrokenPipeError, OSError):
            pass
        for raw in stdout:
            raw = raw.strip()
            if not raw.startswith('{'):
                continue
            try:
                ev = json.loads(raw)
            except ValueError:
                continue
            kind = ev.get('type')
            if kind == 'result':
                result = ev
            elif kind == 'rate_limit_event':
                info = ev.get('rate_limit_info') or {}
                if info.get('status') == 'rejected':
                    limited = f'{info.get("rateLimitType") or "usage"} limit rejected the turn'
            else:
                for out in _events(ev, names, delta_idx):
                    yield out
        p.wait(timeout=30)
    finally:
        stop.set()
    # The stderr reader must be joined before any error text is composed: the race
    # noted in subscription_llm.py is a turn that fails with an empty reason because
    # the thread had not yet appended the CLI's own message.
    err_reader.join(timeout=5)
    err = '\n'.join(err_lines).strip()
    if state['reason'] == 'cancelled':
        return {'kind': 'cancelled'}
    if state['reason'] == 'timeout':
        return {'kind': 'error', 'message': f'the turn passed its {int(ctx.timeout_s or 0)}s timeout and was killed'}
    if result is None:
        msg = err[-400:] or f'the CLI exited with code {p.returncode} without a result'
        if limited or _is_limit(msg):
            return {'kind': 'limit', 'message': limited or msg}
        return {'kind': 'retry', 'message': msg}
    for out in _usage(ctx, result):
        yield out
    return _verdict(result, limited, err)


def _verdict(result: dict, limited: str, err: str) -> dict:
    subtype = str(result.get('subtype') or '')
    text = str(result.get('result') or '')
    if limited or _is_limit(text) or _is_limit(err):
        return {'kind': 'limit', 'message': limited or text or err}
    if subtype == 'error_max_turns':
        return {'kind': 'ok', 'stop_reason': 'max_tool_calls'}
    if subtype in ('', 'success'):
        return {'kind': 'ok', 'stop_reason': 'end_turn'}
    if subtype == 'error_during_execution':
        return {
            'kind': 'error',
            'message': 'the Claude Code turn failed during execution' + (': ' + err[-200:] if err else ''),
        }
    return {'kind': 'error', 'message': (text or subtype or 'error') + (': ' + err[-200:] if err else '')}


def _usage(ctx: TurnContext, result: dict) -> Iterator[dict]:
    u = result.get('usage') or {}
    yield {
        'type': 'usage',
        'input_tokens': int(u.get('input_tokens') or 0),
        'output_tokens': int(u.get('output_tokens') or 0),
        'cache_read': int(u.get('cache_read_input_tokens') or 0),
        'cache_write': int(u.get('cache_creation_input_tokens') or 0),
        'cost_usd': round(float(result.get('total_cost_usd') or 0.0), 6),
        'model': result.get('model') or str(ctx.model or ''),
    }


def _events(ev: dict, names: dict, delta_idx: set) -> Iterator[dict]:
    """One non-result stream-json line -> CONTRACT C events.

    `--include-partial-messages` means text and thinking arrive twice: as
    content_block_delta while they are written, and whole in the closing
    `assistant` message. A text block that already streamed is skipped there (by
    block index) so the chat window never shows it twice. tool_result blocks are
    reported, never executed: the bridge ran the tool already."""
    kind = ev.get('type')
    if kind == 'stream_event':
        e = ev.get('event') or {}
        if e.get('type') != 'content_block_delta':
            return
        delta = e.get('delta') or {}
        if delta.get('type') == 'text_delta':
            delta_idx.add(e.get('index'))
            if delta.get('text'):
                yield {'type': 'text_delta', 'text': delta['text']}
        elif delta.get('type') == 'thinking_delta' and delta.get('thinking'):
            yield {'type': 'thinking', 'text': delta['thinking']}
        return
    if kind == 'assistant':
        for i, b in enumerate((ev.get('message') or {}).get('content') or []):
            if not isinstance(b, dict):
                continue
            bt = b.get('type')
            if bt == 'text' and (b.get('text') or '').strip() and i not in delta_idx:
                yield {'type': 'text_delta', 'text': b['text']}
            elif bt == 'tool_use':
                name = str(b.get('name') or '')
                name = name.removeprefix(TOOL_PREFIX)
                names[str(b.get('id') or '')] = name
                yield {
                    'type': 'tool_call',
                    'id': str(b.get('id') or ''),
                    'name': name,
                    'args': b.get('input') if isinstance(b.get('input'), dict) else {},
                }
        delta_idx.clear()
        return
    if kind == 'user':
        for b in (ev.get('message') or {}).get('content') or []:
            if not isinstance(b, dict) or b.get('type') != 'tool_result':
                continue
            tid = str(b.get('tool_use_id') or '')
            yield {
                'type': 'tool_result',
                'id': tid,
                'name': names.get(tid, ''),
                'ok': not bool(b.get('is_error')),
                'text': _result_text(b.get('content')),
                'ms': 0,
            }


def _result_text(content) -> str:
    if isinstance(content, str):
        return content
    parts = []
    for b in content or []:
        if isinstance(b, dict) and b.get('type') == 'text':
            parts.append(str(b.get('text') or ''))
        elif isinstance(b, dict) and b.get('type') == 'image':
            parts.append('[image]')
    return '\n'.join(parts)


# ── probe + dry run ──────────────────────────────────────────────────────────


def probe() -> dict:
    """Is this backend usable right now? No turn is spawned — cli_version() is
    cached in subscription_llm, so this costs nothing on the quota."""
    cli_bin = _host.claude_cli_bin()
    if not _host.claude_login_present():
        return {'ok': False, 'detail': NO_LOGIN}
    if not os.path.exists(cli_bin):
        return {'ok': False, 'detail': f'no Claude Code CLI at {cli_bin}'}
    sl = _host.subscription_llm()
    version = ''
    ver_fn = getattr(sl, 'cli_version', None) if sl is not None else None
    if callable(ver_fn):
        try:
            version = str(ver_fn() or '')
        except Exception:  # noqa: BLE001
            version = ''
    return {'ok': True, 'detail': f'login present, cli {version or "unknown"} at {cli_bin}'}


def _dry_run() -> int:
    ctx = TurnContext(
        turn_id='dry-run-turn',
        session_id='dry-run-session',
        provider='subscription',
        model='claude-opus-5',
        system='You are Agent Zero.',
        messages=[{'role': 'user', 'content': 'What is on the GPU right now?'}],
        tools=[],
        execute_tool=lambda name, args: {
            'ok': False,
            'text': 'dry run',
            'ms': 0,
            'risk': 'read',
            'needs_confirmation': False,
            'confirm_id': None,
        },
        max_output_tokens=8000,
        max_tool_calls=12,
        thinking_tokens=2048,
        timeout_s=900,
        cookie='<session-cookie>',
        csrf='<csrf>',
        cancel=threading.Event(),
        extra={},
    )
    mcp_json = _mcp_config(ctx, 'REDACTED')
    argv = _cmd(ctx, _host.claude_cli_bin(), mcp_json)
    sys.stdout.write('argv:\n')
    for part in argv:
        sys.stdout.write('  ' + part + '\n')
    sys.stdout.write('\nmcp-config:\n' + json.dumps(json.loads(mcp_json), indent=2) + '\n')
    sys.stdout.write('\nprobe: ' + json.dumps(probe()) + '\n')
    return 0


if __name__ == '__main__':
    if '--dry-run' in sys.argv[1:]:
        raise SystemExit(_dry_run())
    sys.stdout.write('usage: python3 -m agent_zero.backends.subscription --dry-run\n')
    raise SystemExit(2)
