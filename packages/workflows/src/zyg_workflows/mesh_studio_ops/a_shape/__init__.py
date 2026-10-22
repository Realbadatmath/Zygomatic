# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Mesh Studio ops, part A — what the mesh IS.

Sections: Library, Import, Topology, Transform, Shape, Rig, Weights, UV,
Material. All on bar 'side' (the left rail). Part B (b_session.py, task 5)
adds Texture..Session.

EVERY op here is ph=True: declared, described, iconned and knobbed, but not
implemented. The tooltip says what it WILL do when it is built, in the present
tense of the finished thing, because that is the contract the build is held to
-- not a promise that it works today. The page draws these dashed.
"""

# The original top import block, so a_shape._op / .f / .i / .b / .e / .c / .s
# resolve on the package exactly as they did on the module.
from zyg_workflows.mesh_studio import _op, f, i, b, e, c, s

# Sections in the EXACT original order: every one of these modules registers
# ops into mesh_studio.OPS at import time, and that order is the rail order.
from zyg_workflows.mesh_studio_ops.a_shape.library_import import _side
from zyg_workflows.mesh_studio_ops.a_shape import (
    library_import,
    topology_transform,
    shape_rig,
    weights_uv_material,
)

# ── re-export surface ────────────────────────────────────────────────────────
# Every name above, in import order: none is used in this file, they are read
# OFF the package (``a_shape._op`` / ``.f`` / ``.c`` …) exactly as they were off
# the pre-split module. Nothing does ``import *`` from here, so __all__ changes
# no behaviour — it only makes the re-export deliberate.
__all__ = [
    '_op',
    'f',
    'i',
    'b',
    'e',
    'c',
    's',
    '_side',
    'library_import',
    'topology_transform',
    'shape_rig',
    'weights_uv_material',
]
