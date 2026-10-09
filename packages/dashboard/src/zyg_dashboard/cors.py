# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Explicit CORS allowlist for every cross-origin endpoint of the dashboard.

Before 2026-10-05 some thirty endpoints answered with a wildcard
`Access-Control-Allow-Origin`, which let any page on the internet read the
pipeline, asset and integrity APIs of a box that happened to be reachable.
The allowlist is now explicit: an origin gets the header only when it is named
in `ZYG_CORS_ORIGINS` (comma-separated). The default is empty, so no header is
sent at all and the browser enforces same-origin — the safe default for a fresh
checkout. The in-house cross-origin callers (the kanban boards on :8899, the
Creator Nexus frontend on :8090, Medusa on :5300) are configured per box.
"""

import os

_ENV_VAR = 'ZYG_CORS_ORIGINS'


def allowed_origins() -> tuple[str, ...]:
    """Origins allowed to read responses cross-origin; empty means same-origin only."""
    raw = os.environ.get(_ENV_VAR, '')
    return tuple(part.strip() for part in raw.split(',') if part.strip())


def allowed_origin(origin: str | None) -> str | None:
    """Return `origin` when it is allowlisted, else None (meaning: send no header)."""
    if not origin:
        return None
    return origin if origin in allowed_origins() else None


def apply_cors(resp, request):
    """Set Access-Control-Allow-Origin on `resp` only for an allowlisted request Origin.

    `Vary: Origin` is always added, so a cached response for one allowed origin is
    never served to another. Returns `resp` for use as `return apply_cors(resp, request)`.
    """
    resp.vary.add('Origin')
    origin = allowed_origin(request.headers.get('Origin'))
    if origin:
        resp.headers['Access-Control-Allow-Origin'] = origin
    return resp
