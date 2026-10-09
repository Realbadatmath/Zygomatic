# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Mesh Studio ops, part B — the surface, the measurements and the session.

Sections: Texture, Measure and Fit on bar 'side' (they are still statements
about what the mesh IS); Export, Render, Pipeline, View and Session on bar
'dock' (the session half — what is done WITH the mesh once it is right).

EVERY op here is ph=True, exactly as in part A: declared, described, iconned
and knobbed, but not implemented. Each tooltip is written in the present tense
of the finished thing because that is the contract a build is held to, not a
claim that it runs today. The page draws these dashed with an amber pip.

Three of the sections below (Fit, Pipeline, View) are not named in the core's
``SECTION_ORDER``, so this file adds them to it at import time — from here, not
by editing mesh_studio.py. That is not only about rail order: ``ops_payload``'s
``rank()`` falls back to ``order.index(key)`` for an unnamed section, and
CPython empties a list while ``list.sort`` is running, so the fallback raises
``ValueError`` instead of appending. Naming the section keeps rank() on its
``SECTION_ORDER.index`` path. The core's fallback is still broken for anyone
who ships a section without declaring it; that is the core's to fix.
"""

# ruff: noqa: F401  # a Pattern A package: __init__ re-exports the old module surface
from .base import _core, _op, f, i, b, e, c, s, _NEW_SECTIONS, _sec, _after, _side, _dock

# The section modules register their ops at import time and export no name of
# their own, so they must be imported explicitly — in the ORIGINAL section order,
# because that order is the order the rail draws.
from . import texture, measure, fit, export, render, pipeline, view, session
