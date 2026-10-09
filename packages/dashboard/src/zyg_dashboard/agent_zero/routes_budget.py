# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later
"""HTTP surface of Agent Zero v2's spend ceilings (``/api/zero/v2/budget...``).

Three routes, all thin wrappers over :mod:`agent_zero.budget`: read the counters and
the config, patch the config, and grant the operator's override.

The override deserves a word. A ceiling that cannot be lifted is a ceiling the operator
works around by disabling it, so the budget refuses a turn *and* says how to continue:
``POST /api/zero/v2/budget/override`` lets the next N blocked turns through (N defaults
to ``policy.override_turns_granted``) without touching a single limit. The decision is
explicit, bounded and visible in the state the panel shows -- the opposite of quietly
raising a number nobody remembers lowering.

A rejected config patch writes nothing: :func:`agent_zero.budget.save_config` validates
every key first, so a 400 from here means the stored config is exactly what it was.
"""

from __future__ import annotations

import logging

from flask import jsonify, request

from . import bp, budget

_log = logging.getLogger(__name__)


def _body() -> dict:
    """The request's JSON body, tolerant of a missing or malformed one."""
    return request.get_json(silent=True) or {}


@bp.get('/api/zero/v2/budget')
def zero_v2_budget():
    """Counters, the operator's config, and the per-key documentation the panel shows."""
    return jsonify({'state': budget.state(), 'config': budget.load_config(), 'doc': budget.CONFIG_DOC})


@bp.post('/api/zero/v2/budget')
def zero_v2_budget_save():
    """Patch the config ({section: {key: value}}). 400 on an unknown key or a bad range."""
    try:
        config = budget.save_config(_body())
    except (TypeError, ValueError) as exc:
        return jsonify({'error': str(exc)}), 400
    except OSError as exc:
        _log.warning('agent_zero.routes_budget: cannot write the budget config (%s)', exc)
        return jsonify({'error': 'cannot write the budget config'}), 500
    return jsonify({'ok': True, 'config': config})


@bp.post('/api/zero/v2/budget/override')
def zero_v2_budget_override():
    """Let the next N blocked turns through. N defaults to the configured grant."""
    raw = _body().get('turns')
    try:
        turns = None if raw in (None, '') else int(raw)
    except (TypeError, ValueError):
        return jsonify({'error': 'turns must be a whole number'}), 400
    try:
        state = budget.grant_override(turns)
    except (TypeError, ValueError) as exc:
        return jsonify({'error': str(exc)}), 400
    return jsonify({'ok': True, 'override_turns_left': int((state or {}).get('override_turns_left') or 0)})
