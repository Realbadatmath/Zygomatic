# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""medusa_chars.py — whether a storyteller character originated from Medusa.

Medusa-originated characters are adult content and must never surface in a stock
contact-sheet library, a public listing, or an inspection view that was not asked for
the ``medusa`` scope. The two detectors below are the shared answer to that question.
They used to live in the dashboard blueprint that writes the markers, which forced the
public site to import the dashboard; they live here so every layer above
``zyg_workflows`` can ask without depending on any other.

Two independent signals are read, because either one on its own can be missing:

* ``.medusa_origin`` inside the character's dataset directory — durable, survives a
  rotation of the runtime state, written by the pipeline that creates the character.
* ``medusa_<char_id>_state.json`` in the runtime directory — present while a run is
  live and for as long as its state file is kept.

Both roots are environment-driven so a checkout that configures nothing still reads the
same locations as the legacy production tree.
"""

from __future__ import annotations

import logging as _zyg_logging
import os

from zyg_workflows import paths

_zyg_log = _zyg_logging.getLogger(__name__)

#: Dataset root holding one directory per storyteller character.
CHARS_ROOT = os.path.realpath(paths.ZYG_STORYTELLER_CHARS)

#: Runtime directory holding the per-character ``medusa_<id>_state.json`` files.
MEDUSA_RUNTIME_DIR = os.path.realpath(paths.ZYG_MEDUSA_RUNTIME_DIR)


def is_medusa_char(char_id: str) -> bool:
    """True iff *char_id* originated from Medusa.

    Checked by the durable ``.medusa_origin`` marker first, then by the presence of a
    runtime state file. Fail-safe: an unreadable root means 'not medusa', so a broken
    path can never silently reclassify a stock character as adult content.
    """
    if not char_id:
        return False
    try:
        if os.path.exists(os.path.join(CHARS_ROOT, char_id, '.medusa_origin')):
            return True
    except Exception as _exc:
        _zyg_log.debug('suppressed %s: %s', type(_exc).__name__, _exc)
    try:
        return os.path.exists(os.path.join(MEDUSA_RUNTIME_DIR, f'medusa_{char_id}_state.json'))
    except Exception as _exc:
        _zyg_log.debug('suppressed %s: %s', type(_exc).__name__, _exc)
        return False


def filter_out_medusa(sheets):
    """Drop medusa-originated entries from a contact-sheet library list.

    Entries are dicts keyed by ``char_id`` or ``id``. Fail-safe: returns the input
    unchanged on any error, so a malformed list degrades to 'unfiltered' rather than
    to 'empty'.
    """
    try:
        return [s for s in (sheets or []) if not is_medusa_char((s or {}).get('char_id') or (s or {}).get('id'))]
    except Exception as _exc:
        _zyg_log.debug('suppressed %s: %s', type(_exc).__name__, _exc)
        return sheets


__all__ = ['CHARS_ROOT', 'MEDUSA_RUNTIME_DIR', 'filter_out_medusa', 'is_medusa_char']
