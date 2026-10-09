# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The backend registry: provider id -> the module that runs a turn for it.

Every backend under this package speaks exactly the CONTRACT C interface -- ``run(ctx)``
yielding events and ``probe()`` -- so the runner never has to know whether a turn goes
to the Claude Code CLI, a hosted API, the local Ollama server or the deterministic
:mod:`agent_zero.backends.fake` used by the tests.

The mapping itself is not kept here: it lives in :data:`agent_zero.contracts.BACKEND_FOR`,
and is read on every call rather than captured at import time. That is deliberate -- a
test (or a future provider) can extend the table and :func:`get` follows immediately.
"""

from __future__ import annotations

import logging
from importlib import import_module
from types import ModuleType

from .. import contracts

_log = logging.getLogger(__name__)

__all__ = ['get', 'probe_all']

#: module name -> imported module. Importing a backend is cheap (the vendor SDKs are
#: imported lazily inside their functions), but a turn should not pay for it twice.
_cache: dict[str, ModuleType] = {}


def get(provider: str) -> ModuleType:
    """The backend module for ``provider``.

    Raises ``ValueError`` for a provider that has no entry in ``contracts.BACKEND_FOR``
    and for one whose module cannot be imported -- both are configuration errors the
    runner turns into a single ``error`` event, never a traceback in a chat.
    """
    name = contracts.BACKEND_FOR.get(str(provider or ''))
    if not name:
        known = ', '.join(sorted(contracts.BACKEND_FOR))
        raise ValueError(f'unknown provider {provider!r}. Known providers: {known}')
    cached = _cache.get(name)
    if cached is not None:
        return cached
    try:
        module = import_module(f'{__name__}.{name}')
    except Exception as exc:
        raise ValueError(f'backend {name!r} for provider {provider!r} is not importable: {exc}') from exc
    _cache[name] = module
    return module


def probe_all() -> dict:
    """``{provider: {'ok', 'detail'}}`` for every provider in ``contracts.BACKEND_FOR``.

    A probe must be cheap and must never spend tokens; one that raises is reported as
    ``ok=False`` with the exception text, so the panel always gets a full table.
    """
    out: dict[str, dict] = {}
    for provider in contracts.BACKEND_FOR:
        try:
            module = get(provider)
            result = module.probe()
        except Exception as exc:  # noqa: BLE001 - a probe reports, it never raises
            _log.debug('agent_zero.backends: probe of %s failed (%s)', provider, exc)
            out[provider] = {'ok': False, 'detail': str(exc)}
            continue
        if not isinstance(result, dict):
            out[provider] = {'ok': False, 'detail': f'probe() returned {type(result).__name__}'}
            continue
        out[provider] = {'ok': bool(result.get('ok')), 'detail': str(result.get('detail') or '')}
    return out
