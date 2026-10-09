# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""FLAGS — the 799 entries in their original order — and its two readers.

The dict literal was 1,683 lines, twice the 800-line module ceiling, so its entries
live in flags_abort_contact .. flags_remix_ytdlp. ``{**a, **b}`` keeps insertion
order, so FLAGS is key-for-key AND position-for-position the dict the single file
built, and list(FLAGS) is still the alphabetical sequence gen_settings.py wrote.
"""

from __future__ import annotations

import os
import warnings
from typing import Any, Callable

from zyg_workflows.settings.core import _TRUE, Flag
from zyg_workflows.settings.flags_abort_contact import _FLAGS_1
from zyg_workflows.settings.flags_contact_kids import _FLAGS_2
from zyg_workflows.settings.flags_kids_remix import _FLAGS_3
from zyg_workflows.settings.flags_remix_ytdlp import _FLAGS_4

#: 799 flags, scanned from src/zyg_workflows.
FLAGS: dict[str, Flag] = {
    **_FLAGS_1,
    **_FLAGS_2,
    **_FLAGS_3,
    **_FLAGS_4,
}


def get(name: str, cast: Callable[[Any], Any] = str) -> Any:
    """Return ``$name`` cast with *cast*, falling back to the registered default.

    Returns None when the variable is unset and no default is registered. ``cast=bool``
    reads the usual truthy spellings ('1', 'true', 'yes', 'on') rather than Python's
    non-empty-string rule, which would make '0' true. A default stored home-relative
    ('~/ai-models/…') is expanded; a value coming from the environment is used verbatim.
    """
    raw = os.environ.get(name)
    if raw is None or raw == '':
        flag = FLAGS.get(name)
        raw = flag.default if flag is not None else None
        if raw is None:
            return None
        if isinstance(raw, str) and raw.startswith('~'):
            raw = os.path.expanduser(raw)
    if cast is bool:
        return str(raw).strip().lower() in _TRUE
    if cast is str:
        return str(raw)
    return cast(raw)


def check(environ: dict[str, str] | None = None) -> list[str]:
    """Warn about ZYG_* variables set in the environment that no call site reads.

    Returns the sorted list of unknown names (a typo in a flag name is otherwise silent:
    the code keeps using its default and the operator sees no error).
    """
    env = os.environ if environ is None else environ
    unknown = sorted(name for name in env if name.startswith('ZYG_') and name not in FLAGS)
    for name in unknown:
        warnings.warn(f'{name} is set but no zyg_workflows call site reads it', RuntimeWarning, stacklevel=2)
    return unknown
