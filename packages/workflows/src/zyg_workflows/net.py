# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""net.py — the only two ways this package is allowed to fetch a URL.

``urllib.request.urlopen`` follows whatever scheme it is handed, so a URL that reaches it
from configuration or from a model's output can read local files (``file://``) or talk to
other protocols. :func:`safe_urlopen` validates the scheme first and always passes an
explicit timeout; call sites that used ``urlopen`` directly move here.
"""

from __future__ import annotations

import urllib.request
from typing import Any
from urllib.parse import urlsplit

_HTTP_SCHEMES = frozenset({'http', 'https'})


def _validate(url: str, allow_file: bool) -> None:
    if not isinstance(url, str):
        raise TypeError(f'url must be a string, got {type(url).__name__}')
    scheme = urlsplit(url).scheme.lower()
    allowed = _HTTP_SCHEMES | {'file'} if allow_file else _HTTP_SCHEMES
    if scheme not in allowed:
        raise ValueError(f'refusing to open {scheme or "scheme-less"} URL; allowed: {sorted(allowed)}')


def safe_urlopen(url: str, *, timeout: float = 30, allow_file: bool = False, **kw: Any):
    """Open *url* with :func:`urllib.request.urlopen` after checking its scheme.

    Only ``http``/``https`` are accepted, plus ``file`` when *allow_file* is true. Extra
    keyword arguments are passed through unchanged. Raises :class:`ValueError` on a scheme
    that is not allowed.
    """
    _validate(url, allow_file)
    # The suppressions below are for the rules that ask for exactly the audit _validate() performs
    # one line above: this is the single reviewed urlopen of the package, hence this module.
    return urllib.request.urlopen(url, timeout=timeout, **kw)  # nosec B310  # noqa: S310


def safe_get(url: str, timeout: float = 30):
    """GET *url* with ``requests`` when it is installed, otherwise with :func:`safe_urlopen`.

    With ``requests`` the return value is the ``Response``; without it, the file-like object
    ``urlopen`` returns. Either way the scheme is validated and a timeout is always set.
    """
    _validate(url, allow_file=False)
    try:
        import requests
    except ImportError:
        return safe_urlopen(url, timeout=timeout)
    return requests.get(url, timeout=timeout)


__all__ = ['safe_get', 'safe_urlopen']
