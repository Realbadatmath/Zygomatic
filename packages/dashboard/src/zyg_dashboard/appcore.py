# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Shared application infrastructure, extracted so the blueprints stop lazy-importing
the `crewai_web_gui` god-module.

The rate limiter, the CSRF token helper, the canonical data directory and the
Agent Zero audit trail were defined in `crewai_web_gui.py` and pulled back out of
it by in-function `from zyg_dashboard.crewai_web_gui import ...` lines scattered
through the blueprints — a circular import deferred to request time. They live
here now, with ONE definition each; `crewai_web_gui` imports them back at their
old definition sites, so `crewai_web_gui.<name>` still resolves.

This is only the infra round: the blueprints that import `crewai_web_gui` eagerly
at module top level are deliberately untouched, because they pull the ~130 names
of the god-module itself. Moving those is a later round.
"""

import json
import logging as _zyg_logging
import os
import secrets

from flask import session
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

from zyg_workflows.runtime import ams_iso as _ams_iso, workflow_jobs as _workflow_jobs  # noqa: F401  re-exported

__all__ = [
    'DATA_DIR',
    'ZERO_AUDIT_PATH',
    '_ensure_csrf_token',
    '_rate_limit_key',
    '_workflow_jobs',
    '_zero_audit_log',
    'get_remote_address',
    'limiter',
]

_zyg_log = _zyg_logging.getLogger(__name__)


# Rate limiting: coarse at proxy, fine-grained in app for sensitive endpoints
def _rate_limit_key():
    """Use session user_id when logged in, else IP. Per-user limits for fairness."""
    uid = session.get('user_id') or session.get('user_role')
    if uid:
        return f'user:{uid}'
    return f'ip:{get_remote_address()}'


# No `app=` here: the Flask app lives in crewai_web_gui, which calls
# `limiter.init_app(app)` at the site this constructor used to occupy.
limiter = Limiter(
    key_func=_rate_limit_key,
    default_limits=['200/hour'],
    storage_uri=os.environ.get('RATELIMIT_STORAGE_URI', 'memory://'),
)


# CSRF: state-changing API routes require X-CSRF-Token header when using cookie sessions
def _ensure_csrf_token():
    """Ensure session has a CSRF token. Call when user has valid session."""
    if '_csrf_token' not in session:
        session['_csrf_token'] = secrets.token_urlsafe(32)


# --- Canonical data (single truth per entity, see docs/canonical-data-ownership.md) ---
DATA_DIR = os.path.join(os.path.dirname(__file__), 'data')

ZERO_AUDIT_PATH = os.path.join(DATA_DIR, 'zero_audit.jsonl')


def _zero_audit_log(action: str, payload: dict) -> None:
    """Append Zero decision/action to audit trail. Append-only."""
    if not os.path.isdir(DATA_DIR):
        return
    try:
        entry = {
            'timestamp': _ams_iso(),
            'actor': 'Agent Zero',
            'action': action,
            'payload': payload,
        }
        with open(ZERO_AUDIT_PATH, 'a', encoding='utf-8') as f:
            f.write(json.dumps(entry, ensure_ascii=False) + '\n')
    except Exception as _exc:
        _zyg_log.warning('zero audit entry %r not appended to %s: %s', action, ZERO_AUDIT_PATH, _exc)
