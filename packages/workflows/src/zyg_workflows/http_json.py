# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""http_json.py — JSON over HTTP for the workflow services, with the scheme checked.

``urllib.request`` follows whatever scheme the URL it is handed carries, so a base URL
that comes from configuration (``ZYG_OLLAMA_URL``, the kanban and Comfy endpoints, a
model gateway) could make a call read a local file (``file://``) or speak FTP.
:func:`request` validates the scheme first and always passes an explicit timeout.

:func:`zyg_workflows.net.safe_urlopen` already covers the plain GET. This module exists
for the calls that must send a body *and* headers — ``Content-Type: application/json``, a
bearer token — which ``urlopen`` cannot carry on its own, and it is the single reviewed
place where those requests are built.
"""

from __future__ import annotations

import json
import urllib.request
from typing import Any
from urllib.parse import urlsplit

_ALLOWED_SCHEMES = frozenset({'http', 'https'})


def request(
    url: str,
    *,
    data: bytes | None = None,
    headers: dict[str, str] | None = None,
    method: str | None = None,
    timeout: float = 30,
) -> bytes:
    """Return the raw response body of *url*, which must be ``http`` or ``https``.

    *method* defaults to ``POST`` when *data* is given and to ``GET`` otherwise. Raises
    :class:`ValueError` for any other scheme, before a connection is attempted.
    """
    scheme = urlsplit(url).scheme.lower()
    if scheme not in _ALLOWED_SCHEMES:
        raise ValueError(f'refusing to open {scheme or "scheme-less"} URL; allowed: {sorted(_ALLOWED_SCHEMES)}')
    # The two suppressions below are for the audit the check above performs: this is the
    # one reviewed urllib request builder of the package, which is why this module exists.
    req = urllib.request.Request(  # nosec B310  # noqa: S310
        url,
        data=data,
        headers=headers or {},
        method=method or ('POST' if data is not None else 'GET'),
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # nosec B310  # noqa: S310
        return resp.read()


def request_json(url: str, **kw: Any) -> Any:
    """Return the JSON-decoded response body of *url*; see :func:`request` for the keywords."""
    return json.loads(request(url, **kw) or b'null')


def post_json(url: str, payload: Any, **kw: Any) -> Any:
    """POST *payload* as ``application/json`` to *url* and return the decoded response."""
    headers = {'Content-Type': 'application/json', **(kw.pop('headers', None) or {})}
    return request_json(url, data=json.dumps(payload).encode(), headers=headers, **kw)


__all__ = ['post_json', 'request', 'request_json']
