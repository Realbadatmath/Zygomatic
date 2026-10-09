# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Paths, id charsets and the category maps every other picture_fx module reads.

The original module's top block, verbatim, with the two `__file__`-derived values
re-anchored one directory up: this file sits inside the picture_fx/ package, so
`dirname(__file__)` is the package and `dirname(dirname(__file__))` is the
zyg_workflows directory picture_fx.py used to sit in. `_zyg_log` is taken on
`__package__` for the same reason — the logger must keep the name
`zyg_workflows.picture_fx` it had before the split."""

from __future__ import annotations

import os
import re

from zyg_workflows import paths
import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__package__)

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(HERE, 'data')
RUNTIME = os.path.join(DATA, 'runtime')
PRESETS = os.path.join(RUNTIME, 'picture_fx_presets.json')
JOBDIR = os.path.join(RUNTIME, 'picture_fx_jobs')

CHARS_ROOT = os.path.realpath(paths.ZYG_STORYTELLER_CHARS)

CHAR_ID_RE = re.compile(r'^[A-Za-z0-9_]{6,24}$')
NAME_RE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._-]{0,120}$')
IMG_EXT = ('.png', '.jpg', '.jpeg', '.webp')

PREVIEW_MAX = 1400
BAKE_DIR = 'picture_studio'

# Where a character's images live, relative to the character dir. Same three
# categories the Library tab reviews (kanban_server._CATS), plus this studio's
# own output directory — which is a category here for the same reason `studio`
# is one in creature_fx: a derived edit must never be confusable with a
# pipeline image, and nothing in the dock can reach a cell or a final when it
# deletes.
CHAR_CATS = {
    'arcane_final': ('arcane_instantid', 'Arcane FINAL'),
    'cells': (os.path.join('contact_sheet', 'cells'), 'Source cell'),
    'tiles': (os.path.join('contact_sheet', 'tiles'), 'Cropped tile'),
    BAKE_DIR: (BAKE_DIR, 'Studio edit'),
}

LIBS = ('char', 'creature')
