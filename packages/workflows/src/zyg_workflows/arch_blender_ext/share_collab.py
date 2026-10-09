# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""share_collab — the Blender half: a markup note is VOID.

A pin that says "this wall is wrong" is a comment about the building, not a
part of it. Exporting it would put a little cone in the model and, worse, would
carry a reviewer's private remark into whatever the .blend is used for next. So
the builder adds nothing: `arch_blender_build` leaves an empty object where the
note sat, and the model is the building alone.
"""


def build_void(bm, p, kit):
    return ('~', [])


VOID_KINDS = ['markup_note']
BUILDERS = {k: build_void for k in VOID_KINDS}
