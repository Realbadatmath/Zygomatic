# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""subscription_llm.py — the documentary pipeline's Claude calls on Opus 5 through the login. 2026-09-17.

Why this exists. The operator's decision (2026-09-17): every Anthropic call the documentary
pipeline makes — Haiku for outlines, hooks, fact checks, scene descriptions and the vision
judges, Sonnet for the script — runs on Claude Opus 5 through the paid Max subscription
instead of the API key. Measured on the quota meter (Metrics › Quota) an all-Opus episode
is 0.04-0.06 % of the weekly window, about 2-3 euro cents, against $0.62 on API billing.

How. A subscription can only be spent through Claude Code, so each call becomes one
headless `claude -p` turn on the operator's login, the same path the Architecture Studio
assistant and Vicky use: no tools, no settings, a neutral system prompt, the user message
sent as stream-json (so image blocks pass through unchanged for the vision judges), the
`result` event read back. `SubscriptionClient().messages.create(...)` and `.stream(...)`
return an object with the SDK's shape — `content[0].text`, `usage.input_tokens`,
`usage.output_tokens` — so the call sites in pipeline_scholarly.py did not change shape,
only their client factory and model names.

Rules:
  * the requested model is ignored and MODEL (claude-opus-5) is used; the substitution is
    recorded in the audit row (`requested_model`);
  * the spawn environment carries NO ANTHROPIC_* variable — the CLI would bill the key;
  * `temperature` has no CLI equivalent and is dropped; `max_tokens` becomes
    CLAUDE_CODE_MAX_OUTPUT_TOKENS (floor 1024, ceiling 64000 — the CLI's own);
  * a rejected rate limit raises SubscriptionLimitError; the pipeline's existing
    try/except around each call then takes its local fallback (Ollama) or skips the
    step — it never silently switches to the API key;
  * every turn is recorded in llm_audit with source='claude_code' (tokens, the CLI's own
    cost figure, session id) and leaves a transcript under CLI_DIR's project folder,
    which is where the quota meter reads the tokens per model.

Backend switch: ZYG_SCHOLARLY_LLM_BACKEND=subscription (default) | api. In api mode
`anthropic_client()` returns the real SDK client and the tiers keep their old models
(MODEL_SMALL_API / MODEL_LARGE_API); nothing else changes.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
import time
import uuid
import logging as _zyg_logging

from zyg_workflows import paths, runtime

_zyg_log = _zyg_logging.getLogger(__name__)


RUNTIME = paths.ZYG_METRICS_RUNTIME_DIR
CLI_DIR = os.environ.get('ZYG_SUBSCRIPTION_LLM_DIR') or os.path.join(RUNTIME, 'scholarly-llm-cli')


def _newest_cli() -> str:
    """The newest Claude Code binary on this box.

    2026-09-23, measured: claude 2.1.74 IGNORES MAX_THINKING_TOKENS=0 — a 400-word answer
    billed 4 428 output tokens with a thinking block; the same prompt on 2.1.273 billed 777
    with none, in a third of the time. Thinking is charged as output and lands on the weekly
    meter, so the CLI version is worth ~5x the quota of every turn this stack makes. Prefer
    the newest binary; the packaged one is only a fallback.
    """
    import glob as _glob
    import re as _re

    best, best_key = '', ()
    for pat in (
        os.path.expanduser('~/.vscode-server/extensions/anthropic.claude-code-*/resources/native-binary/claude'),
        os.path.expanduser('~/.vscode/extensions/anthropic.claude-code-*/resources/native-binary/claude'),
    ):
        for path in _glob.glob(pat):
            m = _re.search(r'claude-code-(\d+)\.(\d+)\.(\d+)', path)
            if not m or not os.access(path, os.X_OK):
                continue
            key = tuple(int(x) for x in m.groups())
            if key > best_key:
                best, best_key = path, key
    return best


CLI_BIN = (
    os.environ.get('ZYG_SUBSCRIPTION_LLM_CLI', '') or _newest_cli() or shutil.which('claude') or '/usr/local/bin/claude'
)


def cli_version() -> str:
    """The CLI's own version string, cached — recorded on every audit row."""
    global _CLI_VER
    try:
        return _CLI_VER
    except NameError as _exc:
        _zyg_log.debug('CLI version not cached yet: %s', _exc)
    try:
        out = subprocess.run([CLI_BIN, '--version'], capture_output=True, text=True, timeout=20).stdout
        _CLI_VER = (out.split() or [''])[0]
    except Exception:  # noqa: BLE001
        _CLI_VER = ''
    return _CLI_VER


CRED_PATH = os.environ.get('ZYG_CLAUDE_CREDENTIALS') or os.path.join(
    os.path.expanduser('~'), '.claude', '.credentials.json'
)
TIMEOUT_S = int(os.environ.get('ZYG_SUBSCRIPTION_LLM_TIMEOUT', '900'))
MAX_TURNS = 3  # one answer, plus the CLI's own "output limit hit, resume" continuations
# Floor measured 2026-09-17: claude 2.1.74 derives its thinking budget from the output cap
# and the API refuses a budget under 1024 — a 1024 cap 400s, 4096 works (thinking kept).
CLI_OUT_FLOOR, CLI_OUT_CEIL = 16000, 64000
THINKING_TOKENS = 0  # no thinking per turn (see _env): the API path (Sonnet 4.6) never had it

BACKEND = (os.environ.get('ZYG_SCHOLARLY_LLM_BACKEND', 'subscription') or 'subscription').strip().lower()
MODEL = os.environ.get('ZYG_SCHOLARLY_LLM_MODEL', '') or 'claude-opus-5'
MODEL_SMALL_API = 'claude-haiku-4-5-20251001'  # what the pipeline used on the API key (kept for api mode)
MODEL_LARGE_API = 'claude-sonnet-4-6'
# 2026-09-23 (operator ruling, hybrid): 09-17 put EVERY documentary call on Opus 5, which is
# ~5x Sonnet and ~15x Haiku on the meter — a 17-token "extract the subject" turn was costing
# Opus rates. The pipeline's own tiering is restored on the subscription, except the script
# turn (_LLM_SCRIPT), the one that writes the prose an episode is judged by, which stays Opus.
MODEL_SMALL_SUB = os.environ.get('ZYG_SCHOLARLY_LLM_MODEL_SMALL', '') or 'claude-haiku-4-5-20251001'
MODEL_LARGE_SUB = os.environ.get('ZYG_SCHOLARLY_LLM_MODEL_LARGE', '') or 'claude-sonnet-5'
MODEL_SCRIPT_SUB = os.environ.get('ZYG_SCHOLARLY_LLM_MODEL_SCRIPT', '') or MODEL
MODEL_SMALL = MODEL_SMALL_SUB if BACKEND == 'subscription' else MODEL_SMALL_API
MODEL_LARGE = MODEL_LARGE_SUB if BACKEND == 'subscription' else MODEL_LARGE_API
MODEL_SCRIPT = MODEL_SCRIPT_SUB if BACKEND == 'subscription' else MODEL_LARGE_API
# Whatever a call site asks for is mapped onto one of the three, by family. An unknown name
# falls back to MODEL rather than silently picking the cheapest.
_FAMILY_MODEL = (('haiku', 'MODEL_SMALL'), ('sonnet', 'MODEL_LARGE'), ('opus', 'MODEL_SCRIPT'))


def resolve_model(requested: str) -> str:
    name = str(requested or '').lower()
    for family, attr in _FAMILY_MODEL:
        if family in name:
            return globals()[attr]
    return MODEL


LOGIN_SENTINEL = 'subscription-login'

DEFAULT_SYSTEM = (
    'You are the language model inside an automated documentary production pipeline. '
    'Produce exactly the output the message asks for, in exactly the format it asks for: '
    'no preamble, no commentary, no questions back, no markdown fences unless asked. '
    'You have no tools and cannot browse; answer from the message alone.'
)


class SubscriptionLLMError(RuntimeError):
    """The headless turn did not produce a result."""


class SubscriptionLimitError(SubscriptionLLMError):
    """Claude's session or weekly limit refused the turn."""


# ── mode helpers (what the call sites import) ────────────────────────────────


def backend() -> str:
    return BACKEND


def login_present() -> bool:
    try:
        with open(CRED_PATH, encoding='utf-8') as fh:
            return bool(((json.load(fh) or {}).get('claudeAiOauth') or {}).get('accessToken'))
    except (OSError, ValueError):
        return False


def api_key_or_login() -> str:
    """What the call sites gate on. api mode: the key; subscription mode: a sentinel that
    is truthy only when a login exists, so a machine without one skips Claude exactly
    as a machine without a key used to."""
    if BACKEND == 'api':
        return os.environ.get('ANTHROPIC_API_KEY', '')
    return LOGIN_SENTINEL if (login_present() and os.path.exists(CLI_BIN)) else ''


def anthropic_client(api_key: str = ''):
    """`anthropic.Anthropic(api_key=...)` in api mode, the subscription shim otherwise."""
    if BACKEND == 'api':
        import anthropic

        return anthropic.Anthropic(api_key=api_key or os.environ.get('ANTHROPIC_API_KEY', ''))
    return SubscriptionClient()


# ── SDK-shaped response ──────────────────────────────────────────────────────


class _Usage:
    def __init__(self, u: dict):
        self.input_tokens = int(u.get('input_tokens') or 0)
        self.output_tokens = int(u.get('output_tokens') or 0)
        self.cache_read_input_tokens = int(u.get('cache_read_input_tokens') or 0)
        self.cache_creation_input_tokens = int(u.get('cache_creation_input_tokens') or 0)


class _TextBlock:
    type = 'text'

    def __init__(self, text: str):
        self.text = text


class Response:
    role = 'assistant'
    type = 'message'

    def __init__(self, text: str, result: dict, model: str):
        self.id = str(result.get('session_id') or uuid.uuid4())
        self.session_id = result.get('session_id')
        self.model = model
        self.stop_reason = 'end_turn'
        self.content = [_TextBlock(text)]
        self.usage = _Usage(result.get('usage') or {})
        self.total_cost_usd = float(result.get('total_cost_usd') or 0.0)
        self.num_turns = int(result.get('num_turns') or 0)
        self.duration_ms = result.get('duration_ms')


class _Stream:
    """`with client.messages.stream(...) as s: s.get_final_message()` — the turn runs
    on entry; there is nothing to stream from a print-mode CLI worth surfacing."""

    def __init__(self, response: Response):
        self._r = response

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def get_final_message(self) -> Response:
        return self._r

    @property
    def text_stream(self):
        yield self._r.content[0].text


class _Messages:
    def create(self, model=None, messages=None, max_tokens=4096, system=None, temperature=None, **_ignored) -> Response:
        return run_turn(messages or [], system=system, max_tokens=max_tokens, requested_model=model)

    def stream(self, **kw) -> _Stream:
        return _Stream(self.create(**kw))


class SubscriptionClient:
    def __init__(self):
        self.messages = _Messages()


# ── the turn ─────────────────────────────────────────────────────────────────


def _env(max_tokens: int) -> dict:
    env = dict(os.environ)
    for k in list(env):
        # ANTHROPIC_*: the CLI would bill the key. CLAUDE_CODE_* / CLAUDECODE: a parent Claude Code
        # session's own plumbing (messaging socket, session id, child-session flags) must not
        # reach the headless turn — it is not a child of that session.
        if k.startswith('ANTHROPIC_') or k.startswith('CLAUDE_CODE_') or k == 'CLAUDECODE':
            env.pop(k, None)
    # 2026-09-20: the cap is a CEILING, not a target — and when Opus 5 runs past it the CLI
    # "resumes" the turn (max-turns 3), the model starts over, and the turn ends in
    # "response exceeded the N output token maximum" after 4× the cap (seen: 32 000 tokens,
    # 461 s, on a script + scene list + metadata answer that needed ~9k). Give every turn
    # twice what the call site asked for, never below 16k, so one answer fits in one message.
    env['CLAUDE_CODE_MAX_OUTPUT_TOKENS'] = str(max(CLI_OUT_FLOOR, min(CLI_OUT_CEIL, 2 * int(max_tokens or 4096))))
    # 2026-09-20: without a cap the CLI derives the thinking budget from the output cap and
    # Opus 5 then thought for 16k+ tokens (3+ minutes, on the meter) on a script prompt that
    # answered in 30 s on another try. The API path (Sonnet 4.6) never had thinking at all;
    # claude 2.1.74 ignores a positive MAX_THINKING_TOKENS (a 2048 cap still thought 15k+) but
    # honours 0, and 0 is what the Sonnet API path always was. ZYG_SUBSCRIPTION_LLM_THINKING overrides.
    env['MAX_THINKING_TOKENS'] = os.environ.get('ZYG_SUBSCRIPTION_LLM_THINKING', '') or str(THINKING_TOKENS)
    env['CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC'] = '1'
    env.setdefault('HOME', os.path.expanduser('~'))
    return env


def _content_blocks(messages: list) -> list:
    """Fold the SDK message list into ONE user message. Prior assistant turns are quoted
    as text; image blocks pass through unchanged."""
    blocks: list = []
    for m in messages or []:
        role = m.get('role') if isinstance(m, dict) else 'user'
        content = m.get('content') if isinstance(m, dict) else m
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


def _request_text(blocks: list) -> str:
    return ' '.join(b['text'] for b in blocks if b.get('type') == 'text').strip()


def _cmd(model: str, system: str, session_id: str) -> list:
    return [
        CLI_BIN,
        '-p',
        '--model',
        model,
        '--output-format',
        'stream-json',
        '--input-format',
        'stream-json',
        '--verbose',
        '--system-prompt',
        system,
        '--tools',
        '',
        '--permission-mode',
        'dontAsk',
        '--max-turns',
        str(MAX_TURNS),
        '--setting-sources',
        '',
        '--session-id',
        session_id,
    ]


def _kill(p):
    try:
        p.kill()
    except Exception as _exc:  # noqa: BLE001
        _zyg_log.debug('CLI process kill skipped: %s', _exc)


_LIMIT_WORDS = ('rate limit', 'usage limit', 'weekly limit', 'session limit', 'limit reached', 'rejected', "you've hit")


RETRIES = int(os.environ.get('ZYG_SUBSCRIPTION_LLM_RETRIES', '1') or 1)


def run_turn(
    messages: list,
    system: str = None,
    max_tokens: int = 4096,
    requested_model: str = None,
    model: str = None,
    timeout: float = None,
    stage: str = None,
) -> Response:
    """One headless turn on the login, retried once on a non-limit failure (a cut stream, a
    timeout, the CLI's own "exceeded" error) — the call sites make one attempt each and abort
    the run on it. A limit refusal is never retried. Raises SubscriptionLimitError /
    SubscriptionLLMError."""
    last = None
    for attempt in range(1 + max(0, RETRIES)):
        try:
            return _run_turn_once(
                messages,
                system=system,
                max_tokens=max_tokens,
                requested_model=requested_model,
                model=model,
                timeout=timeout,
                stage=stage,
            )
        except SubscriptionLimitError:
            raise
        except SubscriptionLLMError as exc:
            last = exc
            if attempt < RETRIES:
                _zyg_log.info(f'[subscription_llm] turn failed ({str(exc)[:120]}) — retrying ({attempt + 1}/{RETRIES})')
    raise last


def _run_turn_once(
    messages: list,
    system: str = None,
    max_tokens: int = 4096,
    requested_model: str = None,
    model: str = None,
    timeout: float = None,
    stage: str = None,
) -> Response:
    """One headless turn on the login. Raises SubscriptionLimitError / SubscriptionLLMError."""
    model = model or resolve_model(requested_model)
    blocks = _content_blocks(messages)
    sys_prompt = (
        (system.strip() + '\n\n' + DEFAULT_SYSTEM) if isinstance(system, str) and system.strip() else DEFAULT_SYSTEM
    )
    stage = stage or _audit_stage()
    # ── Pre-Emptive bank (preempt_bank.py): a replay run answers text calls from the
    # ledger recorded while the subscription was there; a miss goes live only if the
    # bank's live policy allows it, else the call site takes its LOCAL fallback.
    _pctx = _preempt_ctx()
    # Every turn made inside a bank context carries the entry id and the mode, so the
    # metrics can tell bank-building spend from ordinary production spend (2026-09-23).
    _pex = {'preempt_entry': _pctx.get('entry_id'), 'preempt_mode': _pctx.get('mode')} if _pctx else None
    if _pctx and _pctx.get('mode') == 'replay':
        hit = runtime.preempt_bank.replay_turn(_pctx, model=model, stage=stage, system=sys_prompt, blocks=blocks)
        if hit:
            res = {
                'session_id': f'preempt-replay-{_pctx.get("entry_id")}',
                'usage': hit.get('usage') or {},
                'num_turns': 0,
                'duration_ms': 0,
                'total_cost_usd': 0.0,
                'subtype': 'success',
            }
            _audit(
                model,
                requested_model,
                res,
                blocks,
                sys_prompt,
                hit['text'],
                0,
                stage,
                error=False,
                backend='preempt_replay',
                extra=dict(_pex or {}, match=hit.get('match'), billable=False),
            )
            return Response(hit['text'], res, model)
        allowed, why = runtime.preempt_bank.live_allowed(_pctx)
        if not allowed:
            _pctx['refused'] = _pctx.get('refused', 0) + 1
            raise SubscriptionLimitError(
                f'pre-emptive replay: no recorded answer for this call and live turns are off ({why})'
            )
        _pctx['live'] = _pctx.get('live', 0) + 1
    if _pctx and _pctx.get('mode') == 'record':
        # A recording that was cut off (the GUI restarted under it) is re-run against the
        # turns it already has: identical calls are answered from disk, so an interrupted
        # run costs only the turns it never reached. A fresh entry has none and this is a
        # no-op. Strict matching only — see preempt_bank._match_turn.
        got = runtime.preempt_bank.resume_turn(_pctx, model=model, stage=stage, system=sys_prompt, blocks=blocks)
        if got:
            res = {
                'session_id': f'preempt-resume-{_pctx.get("entry_id")}',
                'usage': got.get('usage') or {},
                'num_turns': 0,
                'duration_ms': 0,
                'total_cost_usd': 0.0,
                'subtype': 'success',
            }
            _audit(
                model,
                requested_model,
                res,
                blocks,
                sys_prompt,
                got['text'],
                0,
                stage,
                error=False,
                backend='preempt_resume',
                extra=dict(_pex or {}, match=got.get('match'), billable=False),
            )
            return Response(got['text'], res, model)
    if not os.path.exists(CLI_BIN):
        raise SubscriptionLLMError(f'Claude Code CLI not found at {CLI_BIN} (ZYG_SUBSCRIPTION_LLM_CLI)')
    if not login_present():
        raise SubscriptionLLMError(f'no Claude login at {CRED_PATH} — run `claude login` on this machine')
    os.makedirs(CLI_DIR, exist_ok=True)
    sid = str(uuid.uuid4())
    t0 = time.time()
    p = subprocess.Popen(
        _cmd(model, sys_prompt, sid),
        cwd=CLI_DIR,
        env=_env(max_tokens),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding='utf-8',
        errors='replace',
        bufsize=1,
    )
    err_lines: list = []
    _err_reader = threading.Thread(
        target=lambda: err_lines.extend((p.stderr.read() or '').splitlines()[-30:]), daemon=True
    )
    _err_reader.start()
    watchdog = threading.Timer(timeout or TIMEOUT_S, lambda: _kill(p))
    watchdog.start()
    result = None
    limited = None
    text_parts: list = []
    try:
        try:
            p.stdin.write(json.dumps({'type': 'user', 'message': {'role': 'user', 'content': blocks}}) + '\n')
            p.stdin.close()
        except (BrokenPipeError, OSError) as _exc:
            _zyg_log.warning(
                'writing the prompt to the CLI stdin failed, the turn continues on whatever it answers: %s', _exc
            )
        _raw_fh = None
        if os.environ.get('ZYG_SUBSCRIPTION_LLM_RAW_DIR'):
            try:  # diagnostics: every CLI event of this turn, verbatim
                os.makedirs(os.environ['ZYG_SUBSCRIPTION_LLM_RAW_DIR'], exist_ok=True)
                _raw_fh = open(
                    os.path.join(os.environ['ZYG_SUBSCRIPTION_LLM_RAW_DIR'], f'{sid}.jsonl'), 'a', encoding='utf-8'
                )
            except OSError:
                _raw_fh = None
        for line in p.stdout:
            line = line.strip()
            if _raw_fh is not None:
                _raw_fh.write(line + '\n')
            if not line.startswith('{'):
                continue
            try:
                ev = json.loads(line)
            except ValueError as _exc:
                _zyg_log.debug('non-JSON CLI event line ignored: %s', _exc)
                continue
            t = ev.get('type')
            if t == 'rate_limit_event':
                info = ev.get('rate_limit_info') or {}
                if info.get('status') == 'rejected':
                    limited = f'{info.get("rateLimitType") or "usage"} limit rejected the turn'
            elif t == 'assistant':
                for b in (ev.get('message') or {}).get('content') or []:
                    if isinstance(b, dict) and b.get('type') == 'text' and b.get('text'):
                        text_parts.append(b['text'])
            elif t == 'result':
                result = ev
        p.wait(timeout=30)
    finally:
        watchdog.cancel()
        if _raw_fh is not None:
            try:
                _raw_fh.close()
            except OSError as _exc:
                _zyg_log.debug('raw event log close skipped: %s', _exc)
    elapsed_ms = int((time.time() - t0) * 1000)
    # The stderr reader races the exit: without the join a crash reports its exit code instead of
    # the CLI's own last words. Bounded, so a wedged pipe can never hold the turn.
    _err_reader.join(timeout=2.0)
    err = '\n'.join(err_lines).strip()
    if result is None:
        msg = err[-400:] or f'the CLI exited with code {p.returncode} without a result'
        if limited or any(w in msg.lower() for w in _LIMIT_WORDS):
            _note_limit(limited or msg)
            raise SubscriptionLimitError(limited or msg)
        raise SubscriptionLLMError(msg)
    text = str(result.get('result') or '').strip()
    joined = ''.join(text_parts).strip()
    if len(text_parts) > 1 and len(joined) > len(text):
        text = joined  # a continued turn: `result` is only the last message
    elif not text:
        text = joined
    ok = (not result.get('is_error')) and result.get('subtype') in (None, 'success')
    if not ok or not text:
        msg = text or str(result.get('subtype') or 'error') + (': ' + err[-300:] if err else '')
        _audit(model, requested_model, result, blocks, sys_prompt, msg, elapsed_ms, stage, error=True, extra=_pex)
        if limited or any(w in msg.lower() for w in _LIMIT_WORDS):
            _note_limit(limited or msg[:300])
            raise SubscriptionLimitError(limited or msg[:300])
        raise SubscriptionLLMError(msg[:300])
    _audit(model, requested_model, result, blocks, sys_prompt, text, elapsed_ms, stage, error=False, extra=_pex)
    if _pctx and _pctx.get('mode') == 'record':
        try:
            runtime.preempt_bank.record_turn(
                _pctx,
                model=model,
                stage=stage,
                system=sys_prompt,
                blocks=blocks,
                text=text,
                usage=result.get('usage') or {},
                requested_model=requested_model,
            )
        except Exception as _exc:  # noqa: BLE001 — recording never breaks a render
            _zyg_log.warning('pre-emptive bank did not record the turn, it is missing from the bank: %s', _exc)
    return Response(text, result, model)


# ── pre-emptive bank glue ────────────────────────────────────────────────────
# The bank is a dashboard module, registered on runtime at boot. Read it through
# `runtime.preempt_bank` at call time, never bound at import: None means headless
# (no bank), and then every call is live.


def _preempt_ctx():
    try:
        bank = runtime.preempt_bank
        return bank.current() if bank else None
    except Exception:  # noqa: BLE001
        return None


def _audit_stage() -> str:
    try:
        from zyg_workflows import llm_audit

        return llm_audit._CTX_STAGE.get() or ''
    except Exception:  # noqa: BLE001
        return ''


def _note_limit(reason: str) -> None:
    try:
        bank = runtime.preempt_bank
        if bank:
            bank.note_limit(reason=reason)
    except Exception as _exc:  # noqa: BLE001
        _zyg_log.warning('pre-emptive bank did not record the limit: %s', _exc)


def _audit(
    model,
    requested_model,
    result,
    blocks,
    sys_prompt,
    text,
    elapsed_ms,
    stage,
    error,
    backend='subscription',
    extra=None,
):
    try:
        from zyg_workflows import llm_audit

        u = result.get('usage') or {}
        llm_audit.record(
            source='claude_code',
            direction='exchange',
            llm=model,
            model=model,
            backend=backend,
            **(extra or {}),
            requested_model=requested_model,
            stage=stage,
            input_tokens=int(u.get('input_tokens') or 0),
            output_tokens=int(u.get('output_tokens') or 0),
            cache_read_input_tokens=int(u.get('cache_read_input_tokens') or 0),
            cache_creation_input_tokens=int(u.get('cache_creation_input_tokens') or 0),
            cost_usd=round(float(result.get('total_cost_usd') or 0), 4),
            duration_ms=result.get('duration_ms') or elapsed_ms,
            num_turns=result.get('num_turns'),
            subtype=result.get('subtype'),
            session_id=result.get('session_id'),
            cli_version=cli_version(),
            images=sum(1 for b in blocks if b.get('type') == 'image'),
            request=_request_text(blocks)[:500],
            response=str(text)[:1000],
            system_prompt=sys_prompt[:300],
            error=(text[:300] if error else None),
        )
    except Exception as _exc:  # noqa: BLE001 — auditing never breaks a render
        _zyg_log.warning('LLM audit record failed, this exchange is missing from the audit log: %s', _exc)


if __name__ == '__main__':  # python3 subscription_llm.py "prompt"  — one live turn on the login
    import sys

    prompt = ' '.join(sys.argv[1:]) or 'Reply with the single word OK.'
    r = run_turn([{'role': 'user', 'content': prompt}], max_tokens=200, stage='cli-probe')
    print(
        json.dumps(
            {
                'model': r.model,
                'text': r.content[0].text,
                'in': r.usage.input_tokens,
                'out': r.usage.output_tokens,
                'cache_read': r.usage.cache_read_input_tokens,
                'cache_write': r.usage.cache_creation_input_tokens,
                'cli_cost_usd': r.total_cost_usd,
                'turns': r.num_turns,
                'session': r.session_id,
            },
            indent=1,
        )
    )
