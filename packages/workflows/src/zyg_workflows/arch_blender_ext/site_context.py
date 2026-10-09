# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""site_context (Blender half) — the one kind of this family is VOID.

`site_boundary` is a survey line, not a thing: the studio draws a line loop with
a peg every 5 m and an area label, and the export must build nothing at all,
exactly as it builds nothing for `opening` and for the ground sculpts. An empty
bmesh gives an empty mesh object, which `arch_blender_build.build_kind` handles
cleanly (remove_doubles and recalc_face_normals on nothing are no-ops), and the
'~' prefix says out loud in the outliner that the object is not real geometry.

Roads, trees and the two underlays add no kind of their own — roads and trees
are the studio's own `road` and `tree`, and an underlay (aerial tiles or a
scanned plan) is a picture under the drawing plane, never geometry, so nothing
of it crosses into Blender either.

Only the standard library is used here.
"""

from __future__ import annotations

VOID_KINDS = ['site_boundary']


def build_site_boundary(bm, p, kit):
    return ('~', [])


BUILDERS = {'site_boundary': build_site_boundary}
