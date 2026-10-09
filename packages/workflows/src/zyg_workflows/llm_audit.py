# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""llm_audit.py — permanent, automatic capture of every LLM call (2026-08-20).

WHY THIS EXISTS
---------------
Prompt logging used to be an opt-in second call (`stage_runner._log_prompt`)
that the author had to remember next to each LLM call. An AST audit on
2026-08-20 found **39 of 45 call sites unlogged — 87% invisible**: only 6 were
logged and 5 of those 6 lived in one module. `cell_vlm_judge` logged 0 of 12.
The documentary's fact-check, its period/era lock and its Stage 3.5a
time-locked scene anchors — the three calls that most shape an episode — left
no record at all, so a bad anchor or a missed fact-check was unreviewable
after the fact.

Discipline does not scale, so this does it by construction:

  * `install()` wraps the Anthropic SDK ONCE. Every `client.messages.create(...)`
    anywhere in the repo is then recorded automatically — including call sites
    nobody has written yet. No call site changes, nothing to remember.
  * `ollama_generate()` is a logged replacement for the raw /api/generate posts
    the local models use (those cannot be patched at a class boundary).

AND PERMANENTLY
---------------
`_log_prompt` keeps only the last 10 000 entries of a single 21 MB JSON file
that it rewrites in full on every call — at 8 437 entries across 266 runs it
was near the cliff, and past it the oldest runs are deleted silently. This
module instead APPENDS one line per call to a per-run JSONL under
`data/runtime/llm_audit/`. Append-only, never trimmed, never rewritten, so a
crash mid-write costs at most the last line rather than the file.

`prompt_log.json` is left exactly as it is: it remains the recent-activity view
it is good at. Anthropic entries are recorded here by the SDK wrapper, so
`_log_prompt` deliberately does NOT duplicate them — it only records the
non-Anthropic prompt types it alone sees (image prompts, system entries).
"""

from __future__ import annotations

import contextlib
import contextvars
import json
import os
import threading
import time
import urllib.request
import logging as _zyg_logging
from zyg_workflows import paths

_zyg_log = _zyg_logging.getLogger(__name__)


def _open_http(url, *, headers=None, data=None, method=None, timeout=60):
    """``urlopen`` restricted to http/https.

    Plain ``urlopen`` follows ``file:`` and any custom scheme, so a URL that arrives from
    configuration or from an API response can read local files. Headers are needed here, so
    :func:`zyg_workflows.net.safe_urlopen` (which takes a bare URL) cannot be used directly;
    the same scheme check is applied to the composed ``Request`` instead.
    """
    req = urllib.request.Request(url, headers=headers or {}, data=data, method=method)  # noqa: S310  scheme checked on the next line
    if req.type not in ('http', 'https'):
        raise ValueError(f'refusing to open a {req.type!r} URL: {url!r}')
    return urllib.request.urlopen(req, timeout=timeout)  # noqa: S310  scheme validated two lines above  # nosec B310


_RUNTIME_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', 'runtime')
_AUDIT_DIR = os.path.join(_RUNTIME_DIR, 'llm_audit')
_LOCK = threading.Lock()
_INSTALLED = False

# Call context. Contextvars are per-thread, and every pipeline runs in its own
# thread, so two concurrent pipelines never cross-label each other's calls.
_CTX_PIPELINE = contextvars.ContextVar('llm_audit_pipeline_id', default='')
_CTX_STAGE = contextvars.ContextVar('llm_audit_stage', default='')
_CTX_TYPE = contextvars.ContextVar('llm_audit_pipeline_type', default='')


def set_context(pipeline_id=None, stage=None, pipeline_type=None):
    """Update whichever fields are given; others keep their current value."""
    if pipeline_id is not None:
        _CTX_PIPELINE.set(str(pipeline_id))
    if stage is not None:
        _CTX_STAGE.set(str(stage))
    if pipeline_type is not None:
        _CTX_TYPE.set(str(pipeline_type))


@contextlib.contextmanager
def context(pipeline_id=None, stage=None, pipeline_type=None):
    """Scoped variant of set_context()."""
    tokens = []
    if pipeline_id is not None:
        tokens.append((_CTX_PIPELINE, _CTX_PIPELINE.set(str(pipeline_id))))
    if stage is not None:
        tokens.append((_CTX_STAGE, _CTX_STAGE.set(str(stage))))
    if pipeline_type is not None:
        tokens.append((_CTX_TYPE, _CTX_TYPE.set(str(pipeline_type))))
    try:
        yield
    finally:
        for var, tok in reversed(tokens):
            try:
                var.reset(tok)
            except Exception as _exc:
                _zyg_log.debug('audit context reset skipped: %s', _exc)


def _now_iso():
    try:
        from zoneinfo import ZoneInfo
        from datetime import datetime

        return datetime.now(ZoneInfo('Europe/Amsterdam')).isoformat(timespec='milliseconds')
    except Exception:
        return time.strftime('%Y-%m-%dT%H:%M:%S')


def _path_for(pipeline_id: str) -> str:
    safe = ''.join(c for c in (pipeline_id or 'misc') if c.isalnum() or c in '-_')[:64] or 'misc'
    return os.path.join(_AUDIT_DIR, f'{safe}.jsonl')


def record(**fields) -> None:
    """Append ONE json line. Never raises — auditing must not break a render."""
    try:
        entry = {
            'ts': _now_iso(),
            'pipeline_id': fields.pop('pipeline_id', None) or _CTX_PIPELINE.get(),
            'stage': fields.pop('stage', None) or _CTX_STAGE.get(),
            'pipeline_type': fields.pop('pipeline_type', None) or _CTX_TYPE.get(),
        }
        entry.update(fields)
        os.makedirs(_AUDIT_DIR, exist_ok=True)
        line = json.dumps(entry, ensure_ascii=False, default=str)
        with _LOCK:
            with open(_path_for(entry['pipeline_id']), 'a', encoding='utf-8') as fh:
                fh.write(line + '\n')
    except Exception as _exc:
        _zyg_log.warning('audit line not written, this LLM call leaves no audit record: %s', _exc)


def _text_of(content) -> str:
    """Flatten Anthropic message content (str | list of blocks) to text.

    Image blocks are summarised, never inlined: a base64 frame would be
    megabytes per line and the audit would become the biggest thing on disk.
    """
    if isinstance(content, str):
        return content
    out = []
    for block in content or []:
        if isinstance(block, str):
            out.append(block)
            continue
        if isinstance(block, dict):
            btype = block.get('type')
            if btype == 'text':
                out.append(str(block.get('text', '')))
            elif btype == 'image':
                src = block.get('source') or {}
                data = src.get('data') or ''
                out.append(f'<image {src.get("media_type", "?")} {len(data)}b base64>')
            else:
                out.append(f'<{btype}>')
        else:
            out.append(str(block))
    return '\n'.join(out)


def install(log_fn=None) -> bool:
    """Patch the Anthropic SDK so every messages.create is recorded. Idempotent."""
    global _INSTALLED
    if _INSTALLED:
        return True
    try:
        from anthropic.resources.messages import Messages
    except Exception as exc:
        if log_fn:
            log_fn(f'[llm_audit] Anthropic SDK not patched: {exc!r}')
        return False
    if getattr(Messages.create, '_llm_audit_wrapped', False):
        _INSTALLED = True
        return True
    _orig = Messages.create

    def create(self, *args, **kwargs):
        t0 = time.time()
        model = kwargs.get('model', '')
        msgs = kwargs.get('messages') or []
        try:
            prompt = '\n\n'.join(_text_of(m.get('content')) for m in msgs)
        except Exception:
            prompt = ''
        system = kwargs.get('system') or ''
        try:
            resp = _orig(self, *args, **kwargs)
        except Exception as exc:
            record(
                source='sdk',
                direction='error',
                llm=model,
                prompt=prompt,
                system_prompt=system if isinstance(system, str) else '',
                error=f'{type(exc).__name__}: {exc}',
                elapsed_s=round(time.time() - t0, 2),
            )
            raise
        try:
            text = ''.join(getattr(b, 'text', '') for b in (resp.content or []))
        except Exception:
            text = ''
        usage = getattr(resp, 'usage', None)
        record(
            source='sdk',
            direction='exchange',
            llm=model,
            prompt=prompt,
            system_prompt=system if isinstance(system, str) else '',
            response=text,
            temperature=kwargs.get('temperature'),
            max_tokens=kwargs.get('max_tokens'),
            input_tokens=getattr(usage, 'input_tokens', None),
            output_tokens=getattr(usage, 'output_tokens', None),
            elapsed_s=round(time.time() - t0, 2),
        )
        return resp

    create._llm_audit_wrapped = True
    Messages.create = create
    _INSTALLED = True
    if log_fn:
        log_fn('[llm_audit] Anthropic SDK instrumented — every messages.create is recorded')
    return True


def ollama_generate(
    model: str,
    prompt: str,
    *,
    images=None,
    think=False,
    options=None,
    fmt=None,
    keep_alive='5m',
    timeout=300,
    host=paths.ZYG_OLLAMA_URL,
    stage=None,
):
    """Logged POST to Ollama /api/generate. Returns the generated text.

    Handles the thinking-model case the roster hit repeatedly: qwen3.5 routes
    its whole answer into 'thinking' and leaves 'response' empty unless asked
    not to, so think:false is the default and 'thinking' is the fallback read.
    """

    t0 = time.time()
    body = {'model': model, 'prompt': prompt, 'stream': False, 'think': bool(think), 'keep_alive': keep_alive}
    if options:
        body['options'] = options
    if fmt:
        body['format'] = fmt
    if images:
        body['images'] = images
    payload = json.dumps(body).encode()
    n_img = len(images or [])
    try:
        with _open_http(
            f'{host}/api/generate',
            data=payload,
            method='POST',
            headers={'Content-Type': 'application/json'},
            timeout=timeout,
        ) as rsp:
            data = json.loads(rsp.read())
    except Exception as exc:
        record(
            source='ollama',
            direction='error',
            llm=model,
            stage=stage,
            prompt=prompt,
            n_images=n_img,
            error=f'{type(exc).__name__}: {exc}',
            elapsed_s=round(time.time() - t0, 2),
        )
        raise
    text = (data.get('response') or '').strip() or (data.get('thinking') or '').strip()
    record(
        source='ollama',
        direction='exchange',
        llm=model,
        stage=stage,
        prompt=prompt,
        response=text,
        n_images=n_img,
        eval_count=data.get('eval_count'),
        prompt_eval_count=data.get('prompt_eval_count'),
        elapsed_s=round(time.time() - t0, 2),
    )
    return text


def ollama_post(url: str, payload: dict, *, timeout: int = 300, stage=None):
    """POST a PRE-BUILT Ollama payload, record it, return the parsed JSON.

    Deliberately takes the payload the caller already constructs rather than
    keyword arguments: the vision judges build theirs through their own
    `_ollama_vision_payload()` helpers (num_ctx, think, format, keep_alive,
    per-model quirks), and re-expressing that here would change behaviour at
    thirteen call sites for no benefit. This swaps the TRANSPORT only, so the
    request on the wire is byte-identical to what it was.

    Evictions and warm-ups (keep_alive 0, or an empty prompt) generate nothing
    and are not recorded — they would drown the audit in noise.

    Raises on transport/HTTP error, like requests' raise_for_status().
    """

    t0 = time.time()
    body = dict(payload or {})
    model = str(body.get('model') or '')
    images = list(body.get('images') or [])
    prompt = str(body.get('prompt') or '')
    if not prompt and isinstance(body.get('messages'), list):
        # /api/chat carries the text in a messages array, and images hang off
        # the message rather than the top level. Without this a chat call looks
        # promptless and would be written off as a warm-up.
        parts = []
        for msg in body['messages']:
            if not isinstance(msg, dict):
                continue
            parts.append(str(msg.get('content') or ''))
            images.extend(msg.get('images') or [])
        prompt = '\n\n'.join(p for p in parts if p)
    is_noop = (body.get('keep_alive') == 0) or not prompt.strip()
    data = json.dumps(body).encode()
    try:
        with _open_http(
            url, data=data, method='POST', headers={'Content-Type': 'application/json'}, timeout=timeout
        ) as rsp:
            parsed = json.loads(rsp.read())
    except Exception as exc:
        if not is_noop:
            record(
                source='ollama',
                direction='error',
                llm=model,
                stage=stage,
                prompt=prompt,
                n_images=len(images),
                error=f'{type(exc).__name__}: {exc}',
                elapsed_s=round(time.time() - t0, 2),
            )
        raise
    if not is_noop:
        text = (parsed.get('response') or '').strip() or (parsed.get('thinking') or '').strip()
        extra = {}
        if isinstance(parsed.get('message'), dict):  # /api/chat
            msg = parsed['message']
            text = text or str(msg.get('content') or '').strip()
            # 2026-09-06: a thinking model that never reaches its answer used
            # to be recorded as an EMPTY exchange — 29k tokens of reasoning,
            # invisible. Keep the tail of the thinking and the tool calls.
            if msg.get('thinking'):
                extra['thinking_tail'] = str(msg['thinking'])[-2000:]
                extra['thinking_chars'] = len(str(msg['thinking']))
            if msg.get('tool_calls'):
                extra['tool_calls'] = [
                    ((tc.get('function') or {}).get('name'), (tc.get('function') or {}).get('arguments'))
                    for tc in msg['tool_calls']
                ][:12]
        if parsed.get('done_reason'):
            extra['done_reason'] = parsed.get('done_reason')
        record(
            source='ollama',
            direction='exchange',
            llm=model,
            stage=stage,
            prompt=prompt,
            response=text,
            n_images=len(images),
            eval_count=parsed.get('eval_count'),
            prompt_eval_count=parsed.get('prompt_eval_count'),
            elapsed_s=round(time.time() - t0, 2),
            **extra,
        )
    return parsed


def read_run(pipeline_id: str) -> list:
    """Every recorded call for one run, oldest first."""
    path = _path_for(pipeline_id)
    out = []
    if not os.path.isfile(path):
        return out
    with open(path, encoding='utf-8') as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except ValueError as _exc:
                _zyg_log.debug('malformed audit line skipped: %s', _exc)
                continue
    return out
