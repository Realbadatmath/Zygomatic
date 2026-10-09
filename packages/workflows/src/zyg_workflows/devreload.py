# SPDX-FileCopyrightText: 2026 Zygomatic
# SPDX-License-Identifier: AGPL-3.0-or-later

"""One gate for every hot-reload in the program: ``ZYG_DEV_RELOAD``.

Several hubs and blueprints used to call ``importlib.reload()`` on every request so an
edited collector went live without restarting the GUI — a developer convenience that
shipped to production, where it costs a re-execution of the module per request, loses
every module-level cache, and (since the god-module splits) only re-executes a
package's ``__init__.py`` anyway, so it does not even pick up an edited submodule.

Those call sites now go through :func:`maybe_reload`, which reloads only when the
environment variable ``ZYG_DEV_RELOAD`` is exactly ``'1'`` and otherwise hands the
module straight back. Development: export ``ZYG_DEV_RELOAD=1`` before starting the
GUI. Production: leave it unset.

The flag is read on every call, not captured at import, so it can be flipped in a
live process (``os.environ['ZYG_DEV_RELOAD'] = '1'``). ``ENABLED`` is the value as it
stood when this module was imported, for logs and banners.
"""

from __future__ import annotations

import importlib
import os

__all__ = ['ENABLED', 'enabled', 'maybe_reload']

ENV_VAR = 'ZYG_DEV_RELOAD'
ENABLED = os.environ.get(ENV_VAR) == '1'


def enabled():
    """True when hot-reload is armed right now (the env var is re-read on every call)."""
    return os.environ.get(ENV_VAR) == '1'


def maybe_reload(mod):
    """``importlib.reload(mod)`` under ``ZYG_DEV_RELOAD=1``, else ``mod`` unchanged."""
    return importlib.reload(mod) if os.environ.get(ENV_VAR) == '1' else mod
