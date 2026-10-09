# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""paths.py — the one module that derives paths from ``__file__`` in this package.

Every directory that ships inside ``zyg_dashboard`` is named here once, so no other module
has to spell out a ``__file__``-relative walk (and no module has to rebind ``__file__`` to
survive being moved into a sub-package). Each constant below ``PKG_DIR`` is overridable from
the environment, which is how a deployment moves one tree — the templates, the schedule —
off the package without moving the rest.
"""

from __future__ import annotations

import os
from pathlib import Path


def _path(name: str, default: Path) -> Path:
    """Return ``$name`` as a :class:`~pathlib.Path`, or *default* when it is unset or empty."""
    raw = os.environ.get(name, '').strip()
    return Path(raw).expanduser() if raw else default


#: This package's own directory. The only ``__file__`` lookup in ``zyg_dashboard``.
PKG_DIR = Path(__file__).resolve().parent

#: Flask's static tree (the folder is lowercase ``static/``; it was renamed from ``Static/``).
STATIC_DIR = _path('ZYG_DASHBOARD_STATIC_DIR', PKG_DIR / 'static')
#: Jinja templates.
TEMPLATES_DIR = _path('ZYG_DASHBOARD_TEMPLATES_DIR', PKG_DIR / 'templates')
#: JSON and reference data that ships with the package.
DATA_DIR = _path('ZYG_DASHBOARD_DATA_DIR', PKG_DIR / 'data')
#: Imagery and attachments the kanban board serves.
KANBAN_ASSETS_DIR = _path('ZYG_DASHBOARD_KANBAN_ASSETS_DIR', PKG_DIR / 'kanban_assets')
#: The scheduler's own tree.
SCHEDULE_DIR = _path('ZYG_DASHBOARD_SCHEDULE_DIR', PKG_DIR / 'Schedule')

__all__ = [
    'DATA_DIR',
    'KANBAN_ASSETS_DIR',
    'PKG_DIR',
    'SCHEDULE_DIR',
    'STATIC_DIR',
    'TEMPLATES_DIR',
]
