# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later
"""What the model actually sees: the system prompt and the message list for one turn.

Everything Agent Zero knows before it calls a single tool is assembled here, and the
order of the pieces is the whole design:

1. the **fixed text** -- identity, rules, risk legend. Under 450 estimated tokens and
   byte-identical from turn to turn.
2. the **tool index** (:func:`agent_zero.toolmap.index_text`) -- large, but it only
   changes when a route is added.
3. the **state snapshot** -- telemetry, running pipelines, pending approvals, the quota
   meter, the selected model. Small (<=300 tokens) and different every turn.
4. the **budget line**, then the pinned facts and the rolling session summary.

Volatile text at the bottom is not tidiness: Anthropic's prompt cache matches on a
prefix, so every byte that moves invalidates everything after it. Keeping 1 and 2
stable means a chat pays for the tool index once instead of once per turn.

The snapshot never calls a tool and never issues an HTTP request. It reads the host's
telemetry cache and the three runtime JSON files directly, and every one of its lines
is optional: a missing file, an unimportable host or a dead quota sampler drops that
line and nothing else.
"""

from __future__ import annotations

import json
import logging
import os
import sys

from . import _host, budget, memory, toolmap
from .contracts import estimate_tokens

_log = logging.getLogger(__name__)

__all__ = ['build', 'fixed_text', 'snapshot']

#: Tokens the tool index may occupy.
INDEX_TOKENS = 1200

#: Tokens the state snapshot may occupy.
SNAPSHOT_TOKENS = 300

#: Floor for the history window, so a huge system prompt can never starve the chat.
MIN_HISTORY_TOKENS = 1000

_IDENTITY = (
    "You are Zero, the operator's agent for the Zygomatic program running on this "
    'machine. You act through tools; you never guess state you can read.'
)

_RULES = (
    'Rules\n'
    '- Answer directly. No preamble, no restating the question.\n'
    '- Before saying a thing cannot be done, call zero_find and look.\n'
    '- Call danger tools only after the user confirms. The tool tells you when a '
    'confirmation is required; then ask in one line and wait.\n'
    '- Be concise. Write numbers in digits.\n'
    '- Never paste secrets, API keys or tokens into the chat.\n'
    '- If a request needs more than the tool-call budget, say what you did and what is left.'
)

_RISK_LEGEND = (
    'Risk legend\n'
    '- read: runs at once, changes nothing.\n'
    '- act: runs at once, changes state, is logged.\n'
    '- danger: destructive or costly (GPU hours, Claude quota) and needs the user yes first.'
)

#: Runtime files the snapshot reads. Names only -- the directory comes from _host.
_PIPELINE_JOBS = 'clipfarm_pipeline_jobs.json'
_APPROVAL_REQUESTS = 'clipfarm_zero_approval_requests.json'
_APPROVAL_STORE = 'clipfarm_zero_approval_store.json'
_ZPUB_PENDING = 'zpub_pending.json'


def fixed_text(user: str) -> str:
    """The stable head of the system prompt (identity, user, rules, risk legend)."""
    return '\n\n'.join([_IDENTITY, f'You are talking to {user}.', _RULES, _RISK_LEGEND])


# ── the state snapshot ───────────────────────────────────────────────────────


def _host_module():
    """The dashboard module -- only when it is ALREADY imported.

    Assembling a prompt must stay cheap, and ``_host.app()`` is not: importing the
    dashboard starts its ~19 watcher threads. In the process that actually serves a
    chat the module is loaded long before a turn begins, so a ``sys.modules`` lookup
    finds it; anywhere else (a test, a CLI) the telemetry line is simply dropped --
    where the sampler never ran there would be nothing to report anyway.

    The module *names* still come from the host seam (``_host``'s own candidate table),
    so :mod:`agent_zero.prompt` names no host module of its own.
    """
    for dotted in getattr(_host, '_CANDIDATES', {}).get('crewai_web_gui', ()):
        module = sys.modules.get(dotted)
        if module is not None:
            return module
    return None


def _read_json(name: str):
    path = os.path.join(_host.runtime_dir(), name)
    try:
        with open(path, encoding='utf-8') as fh:
            return json.load(fh)
    except FileNotFoundError:
        return None
    except Exception as exc:  # noqa: BLE001 - a corrupt runtime file drops its line
        _log.debug('agent_zero.prompt: cannot read %s (%s)', path, exc)
        return None


def _telemetry_line() -> str:
    module = _host_module()
    read = getattr(module, '_read_local_telemetry', None) if module is not None else None
    if read is None:
        return ''
    try:
        snap = read() or {}
    except Exception as exc:  # noqa: BLE001 - telemetry is a nicety, never a blocker
        _log.debug('agent_zero.prompt: telemetry read failed (%s)', exc)
        return ''
    parts = []
    if snap.get('cpu_pct_raw') is not None:
        parts.append(f'cpu {snap["cpu_pct_raw"]:g}%')
    if snap.get('ram_pct') is not None:
        parts.append(f'ram {snap["ram_pct"]:g}%')
    gpus = snap.get('gpus') or []
    if gpus:
        gpu = gpus[0] or {}
        used = float(gpu.get('memory_used_mb') or 0) / 1024.0
        total = float(gpu.get('memory_total_mb') or 0) / 1024.0
        parts.append(f'gpu {float(gpu.get("utilization_pct") or 0):g}%')
        parts.append(f'vram {used:.1f}/{total:.1f} GB')
    return 'Hardware: ' + ', '.join(parts) if parts else ''


def _pipeline_line() -> str:
    jobs = _read_json(_PIPELINE_JOBS)
    if not isinstance(jobs, dict):
        return ''
    running = [j for j in jobs.values() if isinstance(j, dict) and j.get('status') == 'running']
    if not running:
        return 'Pipelines: none running'
    first = running[0]
    stage = str(first.get('current_stage') or 'in progress')
    return f'Pipelines: {len(running)} running (first: {stage})'


def _approvals_line() -> str:
    requests = _read_json(_APPROVAL_REQUESTS)
    if not isinstance(requests, dict):
        return ''
    store = _read_json(_APPROVAL_STORE)
    decided = set(store) if isinstance(store, dict) else set()
    pending = sum(1 for key in requests if key not in decided)
    return f'Approvals waiting: {pending}'


def _public_line() -> str:
    rows = _read_json(_ZPUB_PENDING)
    if not isinstance(rows, list):
        return ''
    pending = sum(1 for row in rows if isinstance(row, dict) and row.get('status') == 'pending')
    return f'Zero-public permission requests pending: {pending}'


def _meter_line() -> str:
    meter = _host.quota_meter()
    if meter is None:
        return ''
    try:
        status = meter.read_status() or {}
    except Exception as exc:  # noqa: BLE001 - the meter is bookkeeping
        _log.debug('agent_zero.prompt: quota meter read failed (%s)', exc)
        return ''
    parts = []
    if status.get('seven_day_pct') is not None:
        parts.append(f'week {float(status["seven_day_pct"]):g}%')
    if status.get('five_hour_pct') is not None:
        parts.append(f'5h {float(status["five_hour_pct"]):g}%')
    return 'Claude meter: ' + ', '.join(parts) if parts else ''


def snapshot(selection: dict | None = None, max_tokens: int = SNAPSHOT_TOKENS) -> str:
    """The live state of the machine as a handful of one-line facts.

    Lines that cannot be measured are left out entirely rather than reported as
    ``unknown``: an absent line costs no tokens and tells the model nothing false.
    """
    lines = [
        _telemetry_line(),
        _pipeline_line(),
        _approvals_line(),
        _public_line(),
        _meter_line(),
    ]
    if selection:
        lines.append(f'Selected model: {selection.get("provider")}/{selection.get("model")}')
    body = [line for line in lines if line]
    while body and estimate_tokens('STATE SNAPSHOT\n' + '\n'.join(body)) > max_tokens:
        body.pop()
    if not body:
        return ''
    return 'STATE SNAPSHOT\n' + '\n'.join(body)


# ── the message list ─────────────────────────────────────────────────────────


def _media_type(image_b64: str) -> str:
    """PNG files start with the magic ``\\x89PNG``, which is ``iVBOR`` in base64."""
    return 'image/png' if str(image_b64 or '').startswith('iVBOR') else 'image/jpeg'


def user_message(text: str, image_b64: str | None = None) -> dict:
    """The new user message: plain text, or image-then-text blocks when a photo came."""
    body = str(text or '')
    if not image_b64:
        return {'role': 'user', 'content': body}
    return {
        'role': 'user',
        'content': [
            {'type': 'image', 'media_type': _media_type(image_b64), 'data': str(image_b64)},
            {'type': 'text', 'text': body},
        ],
    }


def build(
    session: dict,
    user_msg: str,
    selection: dict,
    budget_cfg: dict,
    image_b64: str | None = None,
) -> tuple[str, list, int]:
    """Assemble one turn: ``(system, messages, est_tokens)``.

    ``session`` is a :mod:`agent_zero.memory` session; ``user_msg`` is the message the
    operator just sent (it may already be the session's last message -- it is replaced,
    not duplicated). ``budget_cfg`` is :func:`agent_zero.budget.load_config`.
    """
    user = str(session.get('user') or _host.user_name())
    head = fixed_text(user)
    parts = [head, toolmap.index_text(INDEX_TOKENS)]

    state = snapshot(selection)
    if state:
        parts.append(state)
    try:
        parts.append(budget.summary_line())
    except Exception as exc:  # noqa: BLE001 - the budget line is informational
        _log.debug('agent_zero.prompt: budget summary unavailable (%s)', exc)

    per_turn = (budget_cfg or {}).get('per_turn') or {}
    per_session = (budget_cfg or {}).get('per_session') or {}
    max_context = int(per_turn.get('max_context_tokens') or 14000)
    keep_recent = int(per_session.get('keep_recent_turns') or 8)

    head_tokens = estimate_tokens('\n\n'.join(parts))
    room = max(MIN_HISTORY_TOKENS, max_context - head_tokens)
    summary_text, history = memory.history_for_prompt(session, room, keep_recent)
    if summary_text:
        parts.append(summary_text)

    # history_for_prompt ends with the session's trailing user message, which is this
    # turn's message already appended by the runner. Replace it with the built one so
    # an attached image survives and the message is never sent twice.
    if history and history[-1].get('role') == 'user':
        history = history[:-1]
    messages = history + [user_message(user_msg, image_b64)]

    system = '\n\n'.join(part for part in parts if part)
    est_tokens = budget.estimate_turn_tokens(system, messages, [])
    return system, messages, est_tokens
