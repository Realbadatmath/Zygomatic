# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Proof — Movement Studio draws a REAL BODY over the 31-channel rig.

Headless WebGL through Playwright + SwiftShader at the operator's 67 %-zoom
viewport (2507x1567), against the base body the tab opens on.

Rewritten 2026-09-24. The Bones layer is no longer lathed capsules and the
Muscles layer is no longer a table of bellies: the actor GLB carries the
Blender Studio CC0 anatomical skeleton as a second SkinnedMesh (135 pieces on
the body's own 31 joints) and the Muscles layer is an ÉCORCHÉ — the body's own
geometry wearing the baked muscle atlas, 1.5 mm under the clay. So the two
checks that asserted procedural shaft and belly counts are replaced by the
assertions of tools/studio_verify/check_movement_skeleton_mesh.py and
check_movement_ecorche.py, which stay in place as the per-change records.

What it proves, in the order the operator would check it:

  1. the anatomy solved at all, off a measured mesh (MVA.ready, atlas.vert > 0)
     and the measurements are a BODY's — stature, hand, foot, ankle in foot
  2. THE JOINTS: far more than the rig's 31, and the hand actually has
     fingers — five distinct ray tips past the wrist, at the measured hand
     length, on both hands
  2b. the joint cloud is anatomical: 30 column levels ordered coccyx to C1,
     and no solved joint further from the rig than a body part can reach
  3. THE SKELETON MESH (was: procedural bone shafts) —
     (a) MVA.skel is the GLB's own SkinnedMesh, named 'skeleton', tagged
         userData.mvaLayer='bone', > 50 000 vertices, sharing the body's 31
         Bone OBJECTS by identity
     (b) the Bones switch drives it and `body: off` does not
     (c) the procedural bone/solid/socket passes are not created at all, the
         joints are untouched, counts.bone is the mesh's 135 pieces
     (d) the split routes it by baked side, keeping the axial column whole
     (e) a tick costs a frame and it moves with the clip
  4. THE ÉCORCHÉ (was: solved muscle bellies) —
     (a) MVA.ec is a SkinnedMesh 'ecorche' on a clone of the body geometry,
         remapped onto the 8192x4096 atlas, albedo and bump loaded
     (b) the Muscles switch drives it and `body: off` does not
     (c) halfbare/halfskin/skin route it to the muscle half, the skeleton to
         the other, and 'skin' hides it
     (d) A PIXEL PROBE: at the bind pose in view 'anat' the figure is RED
     (e) the per-frame anatomy cost is still a frame's worth
  5./6. nothing is clipped and what was solved is what is drawn — joints and
     links only, they are the two instanced passes left
  7. the body went translucent so the overlay is visible inside it
  8. it still plays: the mixer advances and the solve tracks it
  9. the frame cost is a frame's worth, not a stall (two skinned meshes more
     than before, so the ceiling is 4 ms)
 10. THE VIEW MENU: the icon opens, every view previews from this actor, a
     hover shows the picture, and the icon says Custom once a switch is moved
     by hand
 10b. THE SPLIT HOLDS WHILE THE BODY MOVES — over 8 frames of a moving clip
     the per-half JOINT counts are identical, the skeleton's and the écorché's
     side uniforms never change, and each mesh's aSide attribute is the same
     object at the same version. Which half a thing belongs to is a baked
     anatomical fact, not a test against a plane.
 11. no page error

Run:  ~/zygomatics-zero/venv/bin/python \
        tools/studio_verify/check_movement_anatomy.py
"""

import json
import os
import sys
from zyg_workflows import paths

from playwright.sync_api import sync_playwright

from . import constants as _constants
from . import run as _run
from . import cli as _cli

from .constants import (
    BIND,
    EC_PROBE,
    EC_READY,
    EC_TIMEOUT_MS,
    GFXQ,
    HERE,
    PIXEL,
    PROBE,
    READY_TIMEOUT_MS,
    RIG_CHANNELS,
    SHOT,
    SHOT_HAND,
    SHOT_MUSCLE,
    SIDE_AXIS,
    SIDE_L,
    SIDE_R,
    SKEL,
    SKEL_PIECES,
    URL,
    _require,
    side_of,
    wait_for,
)
from .run import (
    run,
)
from .cli import (
    main,
)

# Every name imported above is re-exported, not used here: this package IS the module
# the split replaced, so `__all__` declares the surface instead of a file-level noqa.
__all__ = [
    'json',
    'os',
    'sys',
    'paths',
    'sync_playwright',
    '_constants',
    '_run',
    '_cli',
    'BIND',
    'EC_PROBE',
    'EC_READY',
    'EC_TIMEOUT_MS',
    'GFXQ',
    'HERE',
    'PIXEL',
    'PROBE',
    'READY_TIMEOUT_MS',
    'RIG_CHANNELS',
    'SHOT',
    'SHOT_HAND',
    'SHOT_MUSCLE',
    'SIDE_AXIS',
    'SIDE_L',
    'SIDE_R',
    'SKEL',
    'SKEL_PIECES',
    'URL',
    '_require',
    'side_of',
    'wait_for',
    'run',
    'main',
]
