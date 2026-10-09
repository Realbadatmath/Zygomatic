# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""draw_guides (Blender half) — the three guide kinds are VOID.

A guide is a drafting aid: something you draw TO, never something that is
built. The studio draws it as a cyan line; Blender must build nothing at all,
exactly as it builds nothing for `opening` and for the ground sculpts. An empty
bmesh gives an empty mesh object, which `arch_blender_build.build_kind` handles
cleanly (remove_doubles and recalc_face_normals on nothing are no-ops), and the
'~' prefix says out loud in the outliner that the object is not real geometry.

Only the standard library is used here.
"""

from __future__ import annotations

VOID_KINDS = ['guide_arc', 'guide_poly', 'guide_path']


def build_guide_arc(bm, p, kit):
    return ('~', [])


def build_guide_poly(bm, p, kit):
    return ('~', [])


def build_guide_path(bm, p, kit):
    return ('~', [])


BUILDERS = {'guide_arc': build_guide_arc, 'guide_poly': build_guide_poly, 'guide_path': build_guide_path}
