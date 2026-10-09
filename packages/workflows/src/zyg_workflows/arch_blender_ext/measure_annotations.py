# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""measure_annotations — the Blender half: all three annotation kinds are VOID.

A dimension, an angle and a label are statements ABOUT the building, not parts
of it. They belong on the drawing in the studio (lines plus a text sprite) and
nowhere in the exported model: a mesh of the number "5 m" would be milled with
the wall. So every builder here adds nothing and reports itself approximate.

`arch_blender_build` copes with an empty bmesh cleanly — remove_doubles and
recalc_face_normals on nothing are no-ops — and the object is left empty.
"""


def build_void(bm, p, kit):
    return ('~', [])


VOID_KINDS = ['dim_linear', 'dim_angle', 'label_text']
BUILDERS = {k: build_void for k in VOID_KINDS}
