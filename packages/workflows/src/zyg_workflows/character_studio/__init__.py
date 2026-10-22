# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Character Studio — the editable option surface over a character's own bible.

2026-09-02. Character Studio used to be a preview pane with eleven icons beside
it, every one of them a placeholder. This module is what makes most of the new
toolkit real: it exposes the fields that ALREADY EXIST in
``character_bible.json`` as a typed, whitelisted registry, reads them, and
writes them back through ``character_bible_service.save()`` — never by dumping
JSON over the file, because that function is where the age invariant is
enforced and ``updated_at`` is stamped.

Three rules this module is built around:

1. **A knob edits a field that something downstream actually reads.** The
   registry below is derived from ``character_bible_service.default_package()``
   and from the 132 bibles on disk, not from what a character editor "should"
   have. A tool in the UI that has no entry here is drawn as a placeholder and
   says so — an unbuilt knob is honest, a knob that writes a key nothing reads
   is a lie that survives to render time.

2. **The two copies of presentation stay in sync.** ``default_clothing``,
   ``accessories``, ``default_expression`` and ``posture`` live in BOTH
   ``default_presentation`` and ``style_profile`` (the legacy flat keys).
   ``_presentation_from_package`` prefers the former, but other callers read
   the latter directly, so a write to either must land on both or the same
   character wears two outfits depending on the code path.

3. **Derived facts are measured, not restated.** ``derived()`` stats the LoRA
   files on disk, counts the images per category and reads the sheet manifest.
   A panel that says "no FLUX LoRA" says it because the file is not there.
"""

from __future__ import annotations

# The original top import block, re-done so old attribute accesses on this
# module (``character_studio.os``, ``character_studio.json``, …) still resolve.
import json
import os
import re
import time
from typing import Any, Optional
import logging as _zyg_logging

from zyg_workflows import paths

# The sections, in their original order, so module-level side effects still
# run in the order the single file ran them in. ``fields_new`` exports no
# name of its own — it appends to ``FIELDS`` — but must still be imported.
from . import fields_new

from .fields import (
    _zyg_log,
    _HEX_RE,
    CHARS_ROOT,
    LORA_ROOT,
    MAX_TEXT,
    MAX_EDITS,
    FIELDS,
)

from .registry import (
    SECTIONS,
    LOCK_FIELD,
    MIRRORS,
    _get,
    _set,
    _coerce,
    _locked_paths,
    _FAMILIES,
    _stat,
    derived,
    _dir_bytes,
    _cbs,
    spec,
    _values,
    read,
    edit,
)

from .mesh_body import (
    MESH_ROOT,
    CANDIDATES,
    BODY_AXES,
    _mesh_registry,
    _roster,
    _key_is_real,
    candidate_path,
    load_candidate,
    body_axes,
    write_candidate,
    resolve_body,
)


# Every name below is imported above and not used in this module: this package
# IS the re-export surface of the pre-split module, so the imports are the
# deliberate public surface, not dead weight.  Nothing does ``import *`` from
# here, so __all__ changes no behaviour.
__all__ = [
    'json',
    'os',
    're',
    'time',
    'Any',
    'Optional',
    '_zyg_logging',
    'paths',
    'fields_new',
    '_zyg_log',
    '_HEX_RE',
    'CHARS_ROOT',
    'LORA_ROOT',
    'MAX_TEXT',
    'MAX_EDITS',
    'FIELDS',
    'SECTIONS',
    'LOCK_FIELD',
    'MIRRORS',
    '_get',
    '_set',
    '_coerce',
    '_locked_paths',
    '_FAMILIES',
    '_stat',
    'derived',
    '_dir_bytes',
    '_cbs',
    'spec',
    '_values',
    'read',
    'edit',
    'MESH_ROOT',
    'CANDIDATES',
    'BODY_AXES',
    '_mesh_registry',
    '_roster',
    '_key_is_real',
    'candidate_path',
    'load_candidate',
    'body_axes',
    'write_candidate',
    'resolve_body',
]
