# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Shared Murch helpers: LLM tier model, prompt logger, debug log.

Moved verbatim from murch_engine.py lines 39-126.
"""

from __future__ import annotations
import os
import json
import logging
from datetime import datetime, timezone
from typing import Any

import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger('zyg_workflows.murch_engine')

logger = logging.getLogger('murch_engine')

# ── LLM tier model ───────────────────────────────────────────────────────────
# Used for emotion scoring, turning-point detection and the sequence self-eval.
# Must be a model that actually exists in the local Ollama roster: the old
# hardcoded qwen2.5:72b (47 GB) was never resident during pipeline runs, so
# every LLM tier silently fell back to keywords and the self-eval never ran.
MURCH_LLM_MODEL = os.environ.get('ZYG_MURCH_LLM_MODEL', 'qwen3.5:9b')


def _ollama_response_text(resp_bytes: bytes) -> str:
    """Extract generated text from an Ollama /api/generate reply.
    Thinking models (e.g. qwen3.5) can route their entire output — even with
    format:json — into the 'thinking' field, leaving 'response' empty. We ask
    for think:false, but fall back to 'thinking' for Ollama builds that ignore
    the flag."""
    data = json.loads(resp_bytes)
    return (data.get('response') or '').strip() or (data.get('thinking') or '').strip()


# ── Prompt logger (writes to the same prompt_log.json as crewai_web_gui) ─────
# Re-anchored for the package split: this module sits one directory deeper than
# the old murch_engine.py, so one extra dirname() keeps the path identical.
_MURCH_RUNTIME_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data', 'runtime')


def _log_ollama_prompt(
    prompt_type: str,
    stage: str,
    pipeline_id: str,
    prompt: str,
    direction: str = 'sent',
    role: str = 'user',
    llm: str = MURCH_LLM_MODEL,
    from_who: str = 'system',
    to_who: str = MURCH_LLM_MODEL,
    meta: dict | None = None,
):
    """Thread-unsafe but lightweight Ollama prompt logger for murch_engine.
    Writes to the same data/runtime/prompt_log.json consumed by the dashboard."""
    try:
        os.makedirs(_MURCH_RUNTIME_DIR, exist_ok=True)
        log_path = os.path.join(_MURCH_RUNTIME_DIR, 'prompt_log.json')
        entry = {
            'type': prompt_type,
            'stage': stage,
            'pipeline_id': pipeline_id,
            'prompt': prompt,
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'direction': direction,
            'role': role,
            'llm': llm,
            'from_who': from_who,
            'to_who': to_who,
        }
        if meta:
            entry.update(meta)
        entries = []
        if os.path.exists(log_path):
            try:
                with open(log_path) as _f:
                    entries = json.load(_f)
            except Exception:
                entries = []
        entries.append(entry)
        if len(entries) > 10000:
            entries = entries[-10000:]
        with open(log_path, 'w') as _f:
            json.dump(entries, _f, indent=2)
    except Exception as _exc:
        _zyg_log.warning('prompt log write failed, this prompt leaves no record: %s', _exc)


# ─────────────────────────────────────────────────────────────────────────────
# Debug helpers
# ─────────────────────────────────────────────────────────────────────────────


def _ts() -> str:
    return datetime.now(timezone.utc).isoformat(timespec='milliseconds')


def _dbg(log: list, fn: str, msg: str, level: str = 'DEBUG', data: Any = None):
    entry = {'ts': _ts(), 'fn': fn, 'level': level, 'msg': msg}
    if data is not None:
        entry['data'] = data
    log.append(entry)
    logger.debug('[murch/%s] %s', fn, msg)
