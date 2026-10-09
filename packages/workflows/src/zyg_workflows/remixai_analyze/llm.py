# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""zyg_workflows.remixai_analyze.llm — verbatim from remixai_analyze.py lines 37-174.

the original import block, the model/endpoint settings, the GPU guard,
the ollama JSON caller and the optional Claude Haiku fallback
"""

from __future__ import annotations

# ruff: noqa: F401  this module inherits remixai_analyze.py's original top import
# block verbatim; __init__ re-exports the names it binds so old attribute
# accesses off the module (remixai_analyze.os, .json, …) still resolve.

import base64
import json
import os
import re
import subprocess
from zyg_workflows import http_json as _hj
from zyg_workflows.net import safe_urlopen as _safe_urlopen
from zyg_workflows import paths
from zyg_workflows.bin import exe
import logging as _zyg_logging

# channel kept from the pre-split module
_zyg_log = _zyg_logging.getLogger('zyg_workflows.remixai_analyze')


_CREWS = str(paths.PKG_DIR)
_OLLAMA = os.environ.get('OLLAMA_HOST_URL', paths.ZYG_OLLAMA_URL)


def _llm_model() -> str:
    return os.environ.get('ZYG_REMIXAI_LLM_MODEL', 'qwen3.5:9b')


def _vlm_model() -> str:
    return os.environ.get('ZYG_REMIXAI_VLM_MODEL', 'qwen3.5:9b')


def _gpu_clear(min_free_gb: float) -> bool:
    """Fail-closed GPU gate (vlm_inspector pattern): never squeeze a render."""
    try:
        from zyg_workflows import comfy_offload as CO

        if CO.comfy_is_sampling():
            return False
        free = CO.gpu_free_gb()
        # FAIL CLOSED on an unmeasurable GPU. The inherited pipeline_remix form
        # was `free is None or free >= min_free_gb`, which treats "I could not
        # read the GPU" as "the GPU is fine" — the same value for clean and for
        # broken. Here that is not academic: running a vision model against a
        # GPU that is actually full does not fail, it CRAWLS, and a stage that
        # normally takes 40 s sat for 20+ minutes burning per-call timeouts.
        # Not knowing is a reason to wait, not to proceed.
        return free is not None and free >= min_free_gb
    except Exception:
        return False


def _run(cmd, timeout=600):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.returncode, r.stdout or '', r.stderr or ''
    except Exception as e:
        return -1, '', str(e)


# ── ollama ──────────────────────────────────────────────────────────────────


def _ollama_json(prompt, timeout=300, num_predict=1200, images=None, stage='remixai'):
    """Strict-JSON ollama call. `think:False` only on qwen3.x — non-thinking
    models 500 on the key, thinking models route the answer into 'thinking' and
    leave 'response' empty without it."""
    if not _gpu_clear(9.0):
        return None
    try:
        with _safe_urlopen(f'{_OLLAMA}/api/version', timeout=3):
            pass
    except Exception:
        return None
    m = _vlm_model() if images else _llm_model()
    payload = {
        'model': m,
        'prompt': prompt,
        'stream': False,
        'format': 'json',
        **({'think': False} if m.startswith('qwen3') else {}),
        'keep_alive': '3m',
        'options': {'temperature': 0.3, 'num_predict': num_predict, 'num_ctx': 8192},
    }
    if images:
        payload['images'] = images
    try:
        from zyg_workflows import llm_audit as _la

        data = _la.ollama_post(f'{_OLLAMA}/api/generate', payload, timeout=timeout, stage=stage)
        raw = (data.get('response') or '').strip() or (data.get('thinking') or '')
        raw = raw.strip().strip('`')
        return json.loads(raw[raw.find('{') : raw.rfind('}') + 1])
    except Exception:
        return None


def _ollama_release():
    for m in {_llm_model(), _vlm_model()}:
        try:
            _hj.post_json(f'{_OLLAMA}/api/generate', {'model': m, 'prompt': '', 'keep_alive': 0}, timeout=15)
        except Exception as _exc:
            _zyg_log.debug('ollama unload of model %s skipped: %s', m, _exc)


# ── optional Claude Haiku fallback ──────────────────────────────────────────


def _haiku_enabled() -> bool:
    return str(os.environ.get('ZYG_REMIXAI_HAIKU', '0')).lower() in ('1', 'true', 'yes', 'on') and bool(
        os.environ.get('ANTHROPIC_API_KEY', '').strip()
    )


def _haiku_json(prompt, max_tokens=1400):
    """The ONE paid model this department is allowed to call, and only when the
    local model has already failed. Off by default."""
    if not _haiku_enabled():
        return None
    try:
        import anthropic

        client = anthropic.Anthropic(api_key=os.environ['ANTHROPIC_API_KEY'])
        msg = client.messages.create(
            model=os.environ.get('ZYG_REMIXAI_HAIKU_MODEL', 'claude-haiku-4-5-20251001'),
            max_tokens=max_tokens,
            messages=[{'role': 'user', 'content': prompt + '\n\nReturn ONLY valid JSON.'}],
        )
        raw = ''.join(b.text for b in msg.content if getattr(b, 'type', '') == 'text')
        raw = raw.strip().strip('`')
        return json.loads(raw[raw.find('{') : raw.rfind('}') + 1])
    except Exception:
        return None


def _llm(prompt, **kw):
    """Local first, Haiku only if local returned nothing."""
    out = _ollama_json(prompt, **kw)
    if out:
        return out, 'local'
    out = _haiku_json(prompt)
    return (out, 'haiku') if out else (None, 'none')
