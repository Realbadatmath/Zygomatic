# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Model backends — env, free VRAM, Ollama and Anthropic.

Moved verbatim out of the old single-file arch_assistant.py (lines 2478-2805).
"""

from __future__ import annotations

import json
import os
import re
import subprocess

from zyg_workflows.bin import exe

from zyg_workflows.arch_assistant._base import HERE, _zyg_log


# ── model backends ──────────────────────────────────────────────────────────
def _load_env():
    if os.environ.get('ANTHROPIC_API_KEY'):
        return
    for p in (os.path.join(os.path.dirname(os.path.dirname(HERE)), '.env'), os.path.join(HERE, '.env')):
        try:
            with open(p, encoding='utf-8') as fh:
                for line in fh:
                    line = line.strip()
                    if line.startswith('ANTHROPIC_API_KEY=') and not os.environ.get('ANTHROPIC_API_KEY'):
                        v = line.split('=', 1)[1].strip().strip('"').strip("'")
                        if v:
                            os.environ['ANTHROPIC_API_KEY'] = v
        except OSError as _exc:
            _zyg_log.debug('.env not readable at %s: %s', p, _exc)


def free_vram_gb() -> float:
    try:
        out = (
            subprocess.run(
                [exe('nvidia-smi'), '--query-gpu=memory.free', '--format=csv,noheader,nounits'],
                capture_output=True,
                text=True,
                timeout=5,
            )
            .stdout.strip()
            .splitlines()
        )
        return max(float(x) for x in out) / 1024.0
    except Exception:
        return 0.0


def _audit():
    try:
        from zyg_workflows import llm_audit

        llm_audit.install()
        return llm_audit
    except Exception:
        return None


def ollama_loaded() -> bool:
    """Is the local model already resident? Then it costs no MORE VRAM, and the
    free-memory check would wrongly count its own 27 GB against it."""
    try:
        from zyg_workflows.net import safe_urlopen

        with safe_urlopen(OLLAMA_URL + '/api/ps', timeout=3) as r:
            ps = json.loads(r.read().decode())
        return any(str(m.get('name') or m.get('model') or '') == OLLAMA_MODEL for m in ps.get('models') or [])
    except Exception:
        return False


def pick_backend(want: str, log) -> str:
    """'claude' | 'auto' | 'anthropic' | 'local' -> the backend that will actually run.
    Since 2026-09-07 the default is the Claude Code CLI on the operator's login;
    'auto' means the same and only falls back to the old rule when the CLI is
    missing. 'anthropic' and 'local' are explicit, dormant choices."""
    _load_env()
    want = (want or 'claude').lower()
    if want in ('claude', 'cli', 'sonnet', 'auto'):
        if cli_available():
            return 'claude'
        if want != 'auto':
            raise RuntimeError(f'Claude Code CLI not found at {CLI_BIN} (set ZYG_ARCH_ASSIST_CLI)')
        log(f'NOTE: Claude Code CLI not found at {CLI_BIN} — using the old auto rule (local first)')
    have_key = bool(os.environ.get('ANTHROPIC_API_KEY'))
    if want in ('local', 'auto'):
        if ollama_loaded():
            return 'local'
        free = free_vram_gb()
        if free >= OLLAMA_NEED_GB:
            return 'local'
        if have_key:
            log(f'NOTE: local model needs {OLLAMA_NEED_GB:g} GB free, {free:.1f} GB free — using Anthropic instead')
            return 'anthropic'
        raise RuntimeError(
            f'no Anthropic key and only {free:.1f} GB of VRAM free for the local model (it needs {OLLAMA_NEED_GB:g})'
        )
    if not have_key:
        raise RuntimeError('ANTHROPIC_API_KEY is not set (put it in the legacy tree .env, beside ZYG_CREWS_ROOT)')
    wanted = os.environ.get('ZYG_ARCH_ASSIST_MODEL', '')
    if wanted and _cheap_model(wanted) != wanted:
        log(f'NOTE: {wanted} is not allowed here (cost) — using {ANTHROPIC_MODEL}')
    return 'anthropic'


def _img_parts(data_url: str):
    """data:image/jpeg;base64,... -> (media_type, b64) or None."""
    if not data_url or not isinstance(data_url, str):
        return None
    m = re.match(r'data:(image/(?:jpeg|png|webp));base64,(.+)$', data_url, re.S)
    if not m:
        return None
    return m.group(1), m.group(2).strip()


def _adaptive_family(model: str) -> bool:
    """Sonnet 5 / Opus 4.6+ / Fable take adaptive thinking + effort; Haiku 4.5
    and older take neither."""
    m = re.match(r'claude-[a-z]+-(\d+)(?:-(\d+))?', model or '')
    if not m:
        return False
    major, minor = int(m.group(1)), int(m.group(2) or 0)
    return major >= 5 or (major == 4 and minor >= 6)


class _Anthropic:
    def __init__(self, log):
        import anthropic

        _audit()  # patch messages.create BEFORE the first call
        self.anthropic = anthropic
        self.client = anthropic.Anthropic()
        self.log = log
        self.messages = []
        self.usage = {'in': 0, 'out': 0, 'cache_read': 0, 'cache_write': 0}

    def user(self, text, image=None):
        content = []
        if image:
            content.append({'type': 'image', 'source': {'type': 'base64', 'media_type': image[0], 'data': image[1]}})
        content.append({'type': 'text', 'text': text})
        self._drop_old_images()
        self.messages.append({'role': 'user', 'content': content})

    def history(self, turns):
        for t in turns:
            role = 'assistant' if t.get('role') == 'assistant' else 'user'
            txt = str(t.get('text') or '').strip()
            if not txt:
                continue
            if self.messages and self.messages[-1]['role'] == role:
                self.messages[-1]['content'][0]['text'] += '\n' + txt
            else:
                self.messages.append({'role': role, 'content': [{'type': 'text', 'text': txt}]})

    def _drop_old_images(self):
        for m in self.messages:
            if m['role'] != 'user' or not isinstance(m['content'], list):
                continue
            for i, b in enumerate(m['content']):
                if isinstance(b, dict) and b.get('type') == 'image':
                    m['content'][i] = {'type': 'text', 'text': '[an earlier view of the drawing, omitted]'}
                elif isinstance(b, dict) and b.get('type') == 'tool_result' and isinstance(b.get('content'), list):
                    b['content'] = [
                        ({'type': 'text', 'text': '[an earlier view, omitted]'} if c.get('type') == 'image' else c)
                        for c in b['content']
                    ]

    def step(self, system, tools):
        a = self.anthropic
        model = _cheap_model(ANTHROPIC_MODEL)
        kw = dict(
            model=model,
            max_tokens=16000,
            system=[{'type': 'text', 'text': system, 'cache_control': {'type': 'ephemeral'}}],
            tools=tools,
            messages=self.messages,
        )
        if _adaptive_family(model):
            # 4.6+ family: adaptive thinking + effort. Haiku 4.5 rejects both
            # (effort is a 400 there, adaptive thinking is not a mode it has),
            # and this task is tool mapping, so it runs without thinking.
            kw['thinking'] = {'type': 'adaptive'}
            kw['output_config'] = {'effort': os.environ.get('ZYG_ARCH_ASSIST_EFFORT', 'medium')}
        try:
            resp = self.client.messages.create(**kw)
        except a.BadRequestError as e:
            raise RuntimeError(f'Anthropic refused the request: {getattr(e, "message", e)}') from e
        except a.AuthenticationError as _exc:
            raise RuntimeError('Anthropic rejected the API key') from _exc
        except a.RateLimitError as _exc:
            raise RuntimeError('Anthropic rate limit — try again in a minute') from _exc
        except a.APIStatusError as e:
            raise RuntimeError(f'Anthropic error {e.status_code}') from e
        except a.APIConnectionError as _exc:
            raise RuntimeError('cannot reach api.anthropic.com') from _exc
        u = getattr(resp, 'usage', None)
        if u:
            self.usage['in'] += int(getattr(u, 'input_tokens', 0) or 0)
            self.usage['out'] += int(getattr(u, 'output_tokens', 0) or 0)
            self.usage['cache_read'] += int(getattr(u, 'cache_read_input_tokens', 0) or 0)
            self.usage['cache_write'] += int(getattr(u, 'cache_creation_input_tokens', 0) or 0)
        if resp.stop_reason == 'refusal':
            raise RuntimeError('the model declined this request')
        self.messages.append({'role': 'assistant', 'content': resp.content})
        text, calls = [], []
        for b in resp.content:
            if b.type == 'text':
                text.append(b.text)
            elif b.type == 'tool_use':
                calls.append({'id': b.id, 'name': b.name, 'args': dict(b.input or {})})
        return '\n'.join(text).strip(), calls, resp.stop_reason

    def results(self, items):
        """items: [(call_id, text, image_or_None)] -> one user message."""
        content = []
        for cid, txt, img in items:
            if img:
                content.append(
                    {
                        'type': 'tool_result',
                        'tool_use_id': cid,
                        'content': [
                            {'type': 'image', 'source': {'type': 'base64', 'media_type': img[0], 'data': img[1]}},
                            {'type': 'text', 'text': txt},
                        ],
                    }
                )
            else:
                content.append({'type': 'tool_result', 'tool_use_id': cid, 'content': txt})
        self._drop_old_images()
        self.messages.append({'role': 'user', 'content': content})


class _Ollama:
    def __init__(self, log):
        self.log = log
        self.messages = []
        self.audit = _audit()
        self.usage = {'in': 0, 'out': 0}

    def user(self, text, image=None):
        self._drop_old_images()
        m = {'role': 'user', 'content': text}
        if image:
            m['images'] = [image[1]]
        self.messages.append(m)

    def history(self, turns):
        for t in turns:
            role = 'assistant' if t.get('role') == 'assistant' else 'user'
            txt = str(t.get('text') or '').strip()
            if txt:
                self.messages.append({'role': role, 'content': txt})

    def _drop_old_images(self):
        for m in self.messages:
            if m.get('images'):
                m.pop('images', None)
                m['content'] = '[an earlier view of the drawing, omitted]\n' + m.get('content', '')

    def _post(self, payload):
        try:
            if self.audit:
                return self.audit.ollama_post(OLLAMA_URL + '/api/chat', payload, timeout=900, stage='arch_assistant')
            import urllib.parse
            import urllib.request

            chat_url = OLLAMA_URL + '/api/chat'
            if urllib.parse.urlsplit(chat_url).scheme not in ('http', 'https'):
                raise ValueError(f'ollama URL must be http(s), got {OLLAMA_URL!r}')
            # A Request is needed for the headers, so safe_urlopen (str only) cannot carry this one;
            # the scheme check above is the audit both rules ask for.
            req = urllib.request.Request(  # noqa: S310  scheme checked on the line above
                chat_url,
                data=json.dumps(payload).encode(),
                headers={'Content-Type': 'application/json'},
            )
            with urllib.request.urlopen(req, timeout=900) as r:  # nosec B310  # noqa: S310  req holds the checked URL
                return json.loads(r.read().decode())
        except Exception as e:
            raise RuntimeError(f'Ollama failed: {str(e)[:200]}') from e

    def step(self, system, tools):
        tl = [
            {
                'type': 'function',
                'function': {'name': t['name'], 'description': t['description'], 'parameters': t['input_schema']},
            }
            for t in tools
        ]
        payload = {
            'model': OLLAMA_MODEL,
            'stream': False,
            'keep_alive': '10m',
            'messages': [{'role': 'system', 'content': system}] + self.messages,
            'tools': tl,
            'options': {'num_ctx': OLLAMA_NUM_CTX, 'temperature': 0.2, 'num_predict': OLLAMA_NUM_PREDICT},
        }
        resp = self._post(payload)
        msg = resp.get('message') or {}
        self.usage['in'] += int(resp.get('prompt_eval_count') or 0)
        self.usage['out'] += int(resp.get('eval_count') or 0)
        cut = (resp.get('done_reason') == 'length') and not msg.get('tool_calls')
        if cut:
            self.log(
                f'NOTE: local model thought for {resp.get("eval_count")} tokens without answering — retrying the step with thinking off'
            )
            resp = self._post({**payload, 'think': False})
            msg = resp.get('message') or {}
            self.usage['in'] += int(resp.get('prompt_eval_count') or 0)
            self.usage['out'] += int(resp.get('eval_count') or 0)
            if resp.get('done_reason') == 'length' and not msg.get('tool_calls'):
                raise RuntimeError(f'the local model ran out of output tokens twice ({OLLAMA_NUM_PREDICT} each)')
        self.messages.append(
            {
                'role': 'assistant',
                'content': msg.get('content') or '',
                **({'tool_calls': msg['tool_calls']} if msg.get('tool_calls') else {}),
            }
        )
        calls = []
        for i, tc in enumerate(msg.get('tool_calls') or []):
            fn = tc.get('function') or {}
            args = fn.get('arguments')
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except ValueError:
                    args = {}
            calls.append({'id': f'c{len(self.messages)}_{i}', 'name': fn.get('name', ''), 'args': args or {}})
        return (msg.get('content') or '').strip(), calls, ('tool_use' if calls else 'end_turn')

    def results(self, items):
        self._drop_old_images()
        for _cid, txt, img in items:
            m = {'role': 'tool', 'content': txt}
            if img:
                m['images'] = [img[1]]
            self.messages.append(m)


# Imported here, at the foot of the module, because these names are used only inside
# function bodies and their modules import this one back: by this line every name
# above is already bound, so the call-time cycle resolves either way round.
from zyg_workflows.arch_assistant.config import (  # noqa: E402
    ANTHROPIC_MODEL,
    CLI_BIN,
    OLLAMA_MODEL,
    OLLAMA_NEED_GB,
    OLLAMA_NUM_CTX,
    OLLAMA_NUM_PREDICT,
    OLLAMA_URL,
    _cheap_model,
)
from zyg_workflows.arch_assistant.cli_backend import cli_available  # noqa: E402
