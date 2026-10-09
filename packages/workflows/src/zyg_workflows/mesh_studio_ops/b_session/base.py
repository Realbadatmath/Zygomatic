# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Mesh Studio ops, part B — the shared declaration helpers.

The original top block of ``b_session.py``, moved verbatim: the two imports
from the core, the ``SECTION_ORDER`` insertion the part-B sections rely on
(it must run before any of them registers), and the ``_side``/``_dock``
wrappers every section calls.
"""

# ruff: noqa: F401  # f/i/b/e/c/s are re-exported from here to the section modules
from zyg_workflows import mesh_studio as _core
from zyg_workflows.mesh_studio import _op, f, i, b, e, c, s

#: (new section, the section it goes directly after) — inserted, not appended,
#: so the rail reads Texture, Measure, Fit … Export, Render, Pipeline, View,
#: Session rather than dumping the three new ones at the end.
_NEW_SECTIONS = (('Fit', 'Measure'), ('Pipeline', 'Render'), ('View', 'Pipeline'))
for _sec, _after in _NEW_SECTIONS:
    if _sec not in _core.SECTION_ORDER:
        _core.SECTION_ORDER.insert(_core.SECTION_ORDER.index(_after) + 1, _sec)


def _side(id_, lb, sec, tip, svg, params=(), cls='edit', needs='mesh'):
    return _op(id_, lb, sec, 'side', tip, svg, params, cls=cls, needs=needs, ph=True)


def _dock(id_, lb, sec, tip, svg, params=(), cls='act', needs='mesh', tog=False):
    return _op(id_, lb, sec, 'dock', tip, svg, params, cls=cls, needs=needs, tog=tog, ph=True)
