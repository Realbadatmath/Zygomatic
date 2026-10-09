# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""paths.py — the one module that derives paths from ``__file__`` in this package.

Every directory that ships inside ``zyg_zero`` is named here once, so no other module has to
spell out a ``__file__``-relative walk (and no module has to rebind ``__file__`` to survive
being moved into a sub-package). Each constant below ``PKG_DIR`` is overridable from the
environment, which is how a deployment moves one tree off the package without moving the rest.
"""

from __future__ import annotations

import os
from pathlib import Path


def _path(name: str, default: Path) -> Path:
    """Return ``$name`` as a :class:`~pathlib.Path`, or *default* when it is unset or empty."""
    raw = os.environ.get(name, '').strip()
    return Path(raw).expanduser() if raw else default


#: This package's own directory. The only ``__file__`` lookup in ``zyg_zero``.
PKG_DIR = Path(__file__).resolve().parent

#: Jinja templates for the public site.
TEMPLATES_DIR = _path('ZYG_ZERO_TEMPLATES_DIR', PKG_DIR / 'templates')
#: JSON and reference data that ships with the package.
DATA_DIR = _path('ZYG_ZERO_DATA_DIR', PKG_DIR / 'data')
#: The Medusa sub-site's own tree.
MEDUSA_DIR = _path('ZYG_ZERO_MEDUSA_DIR', PKG_DIR / 'medusa')

__all__ = [
    'DATA_DIR',
    'MEDUSA_DIR',
    'PKG_DIR',
    'TEMPLATES_DIR',
]
