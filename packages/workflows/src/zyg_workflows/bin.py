# SPDX-FileCopyrightText: 2026 Zygomatic
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Resolve external executables once, never by partial path.

`exe('ffmpeg')` returns an absolute path: an explicit override `ZYG_BIN_FFMPEG`
wins, then `shutil.which`, then a clear error naming the binary and the
override variable. Subprocess argument lists use `exe(name)` as their first
element so a scanner sees an absolute program path and an operator can point
any tool at a specific build.
"""

from __future__ import annotations

import os
import shutil

_CACHE: dict[str, str] = {}


class MissingExecutable(RuntimeError):
    """Raised when a required external program cannot be found on this machine."""


def exe(name: str, *, required: bool = True) -> str:
    """Return the absolute path of external program `name`.

    Resolution order: `ZYG_BIN_<NAME>` environment override, then PATH.
    With `required=False` an unresolved program returns '' instead of raising.
    """
    if name in _CACHE:
        return _CACHE[name]
    override = os.environ.get('ZYG_BIN_' + name.upper().replace('-', '_').replace('.', '_'), '').strip()
    path = override or shutil.which(name) or ''
    if not path and required:
        raise MissingExecutable(f'{name!r} is not installed or not on PATH; set ZYG_BIN_{name.upper()} to its location')
    if path:
        _CACHE[name] = path
    return path
