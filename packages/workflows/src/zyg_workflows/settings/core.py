# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The Flag record and the truthy spellings — settings.py lines 27-35, verbatim."""

from __future__ import annotations

from typing import Any, NamedTuple


class Flag(NamedTuple):
    """One environment flag: its name, the default the code uses, and where it is read."""

    name: str
    default: Any
    files: tuple[str, ...]


_TRUE = frozenset({'1', 'true', 'yes', 'on', 'y', 't'})
