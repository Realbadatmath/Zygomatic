# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""settings.py — the deployment-specific values of the public site, in one place.

``zyg_workflows.paths`` already owns every root the shared pipelines use. This module adds
only what the public site, nomologin and the Medusa apps need on top of it, and nothing
here names a machine, an address or an operator's home directory: an unconfigured checkout
gets loopback and directories under :data:`zyg_workflows.paths.ZYG_DATA_ROOT`, and a
deployment names its own in the environment.

See ``docs/configuration.md`` for the full table and what each value does.
"""

from __future__ import annotations

import os
from pathlib import Path

from zyg_workflows import paths


def _path(name: str, default: Path) -> Path:
    """Return ``$name`` as a :class:`~pathlib.Path`, or *default* when unset or empty."""
    raw = os.environ.get(name, '').strip()
    return Path(raw).expanduser() if raw else default


def _text(name: str, default: str) -> str:
    """Return ``$name`` stripped, or *default* when unset or empty."""
    raw = os.environ.get(name, '').strip()
    return raw or default


# --- LAN reachability -------------------------------------------------------------------
#: Comma- or semicolon-separated IPs/CIDRs allowed to reach the LAN-bound Medusa apps, on
#: top of loopback (which :mod:`zyg_zero.medusa.medusa_ipgate` always allows and which can
#: never be configured away). Empty by default: loopback only, so an unconfigured install
#: is reachable from the box itself and from nowhere else.
ZYG_LAN_ALLOWLIST = _text('ZYG_LAN_ALLOWLIST', '')

#: The host:port pairs the services print and link to are built on this. Loopback by
#: default; set it to the box's LAN name or address to advertise a reachable URL.
ZYG_LAN_HOST = _text('ZYG_LAN_HOST', '127.0.0.1')

#: The interface the services bind their listening socket to. Loopback by default, so an
#: unconfigured install is never exposed by accident; set it to '0.0.0.0' (or one address)
#: to accept connections from the LAN, which only makes sense together with
#: :data:`ZYG_LAN_ALLOWLIST` for the Medusa apps.
ZYG_BIND_HOST = _text('ZYG_BIND_HOST', '127.0.0.1')

# --- filesystem roots -------------------------------------------------------------------
#: Where resource imports land: one subdirectory per character, images inside it.
ZYG_MEDUSA_IMPORT_DIR = _path('ZYG_MEDUSA_IMPORT_DIR', paths.ZYG_DATA_ROOT / 'medusa_import')

#: Portfolio media shown on the public pages — the slideshow frames and the showreel.
ZYG_PORTFOLIO_DIR = _path('ZYG_PORTFOLIO_DIR', paths.ZYG_DATA_ROOT / 'portfolio')

#: Working directory of the sports-video pipeline (its ``status.json`` and its scripts).
ZYG_SPORTS_VIDEO_DIR = _path('ZYG_SPORTS_VIDEO_DIR', paths.ZYG_DATA_ROOT / 'sports-video-pipeline')

__all__ = [
    'ZYG_BIND_HOST',
    'ZYG_LAN_ALLOWLIST',
    'ZYG_LAN_HOST',
    'ZYG_MEDUSA_IMPORT_DIR',
    'ZYG_PORTFOLIO_DIR',
    'ZYG_SPORTS_VIDEO_DIR',
]
