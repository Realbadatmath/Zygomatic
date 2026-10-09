# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""pufferball.py — the Zygo AI Pufferball as real geometry (2026-08-26).

Imported by Blender scripts; needs bpy.

WHY THIS EXISTS.
The creature's 16-angle training sheet is built by rotating a 2D reference with
Qwen-Image-Edit, and a 2D rotation INVENTS whatever the source could not see. That
is not a tuning problem, it is the method: cell 10 (top-down) still reads the tail
as a crown swirl after two regens, and cell 08 grew a unicorn horn on one attempt.
Adding more angles buys more guesses, not more truth — the missing thing is not
coverage, it is geometry.

A mesh removes the guessing. Nothing is hidden from a renderer, so every angle is
consistent BY CONSTRUCTION, and the top-down view is no harder than the front.

The human characters already take this route (blender_character_service builds them
in Blender and trains on the renders). They can, because MHR/Anny are permissive
parametric human models. A novel creature has no parametric model to fit, and the
licence map closes the shortcut: EVERY image→mesh regressor is non-commercial
(4D-Humans, HybrIK, PIXIE, SMPLer-X, ECON/ICON, Sapiens, TRAM, and Multi-HMR's Anny
checkpoint too). On a monetised channel that is a hard block. So he is built, by
hand, from primitives — which is cheap for this creature precisely because he IS
primitives: a ball, two arms, two feet, and a segmented tail.

WHAT THE REFERENCE ACTUALLY SHOWS (the 16 sheet cells + brief.body_plan):
  * the body is a squashed sphere, MEASURABLY wider than tall — "almost as wide as
    it is tall" — and the fur silhouette is spiky, not smooth. A true sphere reads
    as a balloon; the spikes are what make it read as fur at a distance.
  * the face is a turquoise patch on the FRONT of that same ball, not a separate
    head. There is no neck and no head/body join anywhere in the reference.
  * the eyes are very large relative to the face, set wide, golden-brown iris with a
    big black pupil, and they PROTRUDE — the fur parts around them.
  * arms are short, turquoise, hang close to the body, and end in a few stubby
    fingers. In most cells they are half-buried in the fur; the silhouette is
    barely broken. They must NOT read as full limbs.
  * feet are turquoise, THREE-toed, and small — measured at ~0.28% of frame in the
    training cells. They sit under the body, not out from it.
  * the tail rises from the LOWER BACK, curls up and behind, is segmented, and is
    white fur with turquoise bands showing through. It tapers along its length.

SCALE. Body ~0.30 m across, so the creature is roughly cat-sized. Nothing downstream
depends on the absolute figure; it is fixed only so lamp energies and camera
distances in the sheet script mean something.

CONVENTION. +Y is BEHIND the creature, -Y is the direction he faces (Blender's
default camera looks down -Z, and the sheet script orbits in the XY plane placing
the camera at -Y for the front view). +Z is up. Origin sits on the ground plane.
"""

# ruff: noqa: F401

import math

import bmesh
import bpy
from mathutils import Vector
import logging as _zyg_logging

# channel kept from the pre-split module
_zyg_log = _zyg_logging.getLogger('zyg_workflows.prop_mesh.pufferball')


# pass_index vocabulary for this creature. Deliberately NOT pass_lib.IDX: that is
# the axe/forest gate's object vocabulary and the two should not collide. Read from
# the IndexOB pass to get an exact per-part segmentation mask for free.
IDX = {
    'body': 1,
    'face': 2,
    'eye': 3,
    'mouth': 4,
    'arm': 5,
    'foot': 6,
    'tail': 7,
    'ground': 8,
    # The pupil used to share the eye's index, so the segment channel could not
    # separate iris from pupil and no gaze-driven conditioning could be built
    # from it. They are different surfaces; they get different indices.
    'pupil': 9,
    'leg': 10,  # the body used to sit ON the feet; canon stands on legs
    'teeth': 11,  # brief: "Small mouth showing tiny teeth"
    'glint': 13,  # specular catchlight — the eyes read dead without it
}

# Every proportion in one place so the creature can be tuned without reading code.
# Metres.
P = {
    'body_rx': 0.160,  # half-width  (X) — the widest axis
    'body_ry': 0.112,  # half-depth  (Y). Shallower than body_rx so the tail
    # has somewhere to BE. At 0.150 the furred body alone
    # consumed the whole Y budget the anchors allow, and
    # the fitted tail ended up INSIDE the fur envelope —
    # geometrically present, visually absent.
    'body_rz': 0.118,  # half-height (Z) — smaller than rx: wider than tall
    'body_lift': 0.180,  # centre height above ground; legs carry the rest.
    # At 0.150 the body's underside (lift - body_rz) sat
    # BELOW the top of the foot, so there was no room for
    # a leg and none was built — the ball rested straight
    # on two pads. Raising it far enough to clear the fur
    # costs more height than the ANCHORS allow, so the
    # legs are built but the fur hangs over them from the
    # front, which is what anchor_full actually shows.
    'face_r': 0.098,  # turquoise patch radius on the front of the ball
    'face_z': 0.045,  # patch centre, relative to body centre
    'face_bulge': 0.012,  # how far the patch stands proud of the fur
    'bald_scale': 0.82,  # bald radius as a multiple of face_r. At 1.35 there
    # was a fur-FREE MARGIN around the whole patch, which
    # is what made the face read as a bald plastic dome
    # with a fur collar. Under 1.0 the fur grows over the
    # mask edge, which is what the canon cells show.
    'eye_r': 0.052,  # measured: mesh pupils were 6.9% of silhouette width
    'eye_sep': 0.052,  # half-distance between the two eyes
    'eye_z': 0.062,
    'eye_out': 0.026,  # eyeball front pole, past the FACE SURFACE at the
    # eye's own (x, z) — see _face_surface_y. Applying
    # this to the face CENTRE instead delivered 10.8 mm
    # of the 26 mm asked for and left the eye 86% buried.
    'pupil_r': 0.030,
    'glint_r': 0.008,
    'glint_out': 0.0015,  # catchlight cap height above the sclera
    'pupil_proud': 0.0020,  # pupil front past the SCLERA surface. A cabochon,
    # not a bead: at 8 mm the pupil stood further out
    # than the front pole of the eyeball holding it. It
    # cannot go arbitrarily small either — below the
    # sclera's own tessellation error the two surfaces
    # interleave and the pupil z-fights into a black
    # cross. _sagitta() sets the floor; 0.0005 was under
    # it and every eye rendered a plus sign.
    'eye_segs': 48,  # the eyes carry the identity and now stand 27 mm
    'eye_rings': 24,  # proud, so their silhouette is on show — and finer
    'pupil_segs': 32,  # rings also shrink the z-fight floor above.
    'pupil_rings': 16,
    'mouth_w': 0.030,
    'mouth_h': 0.013,
    'mouth_z': 0.002,
    'mouth_out': 0.006,  # mouth front pole past the face surface. The face
    # curve still clips it to a lens; the lip behind it
    # sets how much dark shows.
    'lip_scale': 1.32,  # tan rim around the mouth
    'lip_out': 0.0035,
    'teeth_out': 0.0015,  # teeth stand just proud of the dark mouth surface
    'muzzle_w': 0.024,
    'muzzle_h': 0.013,
    'muzzle_out': 0.004,
    'muzzle_z': 0.020,  # above the mouth, below the eyes
    'arm_len': 0.056,  # canon: "in most cells they are half-buried in the
    # fur; the silhouette is barely broken". At 0.076 the
    # HANDS were the widest thing on the creature and set
    # the whole silhouette width — 0.221 against a furred
    # body half-width of 0.196.
    'arm_r': 0.032,  # at the shoulder; tapers to ~55% at the wrist
    'arm_z': -0.012,
    'arm_drop': 58.0,  # degrees below horizontal — arms hang, not stick out
    'arm_fwd': 18.0,  # degrees forward of the side
    'finger_n': 3,
    'finger_r': 0.013,
    'finger_len': 0.024,
    'leg_r0': 0.030,  # at the hip
    'leg_r1': 0.024,  # at the ankle
    'foot_r': 0.036,  # brief: feet are "small" — ~0.28% of frame in canon
    'foot_sep': 0.062,  # half-distance between feet
    'foot_fwd': -0.020,  # slightly forward of body centre (-Y is forward)
    'toe_n': 3,
    'toe_r': 0.018,
    'toe_len': 0.030,
    # THE TAIL IS A SPIRE. It was a chain of equal beads walked around a circular
    # arc, and that reads as a handle: measured against the canon contact sheet the
    # back view came out 650x503 — WIDER than tall — where canon cell_07 is 599x774,
    # TALLER than wide, and the tail cleared the body by 23.5% of the height against
    # canon's 38.9%. The reference is a soft-serve swirl: thick at the lower back,
    # drawn to a point well above the crown.
    #
    # The path is a cubic Bezier in the YZ plane, control points in units of
    # (body_ry, body_rz) about the body centre, so the sweep is editable directly
    # instead of being implied by an arc's start and end angle.
    # SCALE COMES FROM THE ANCHORS, NOT THE CELLS. A first pass fitted this tail to
    # cell_07 (back), which shows a tall spire, and it produced a creature with
    # ar 0.72-0.73 in EVERY view against an anchor target of 1.20-1.22. The cells
    # do not agree with each other: front reads h/w 0.82 and back reads 1.29 for
    # the same rigid creature, a 58% disagreement, because they are 2D rotations
    # that invent whatever the source could not see. anchor_full.png IS cell_00.png
    # byte for byte; anchor_side.png is its own approved image. Those two are the
    # reference. Everything else on the sheet is a derived guess.
    'tail_segs': 40,
    'tail_r0': 0.048,  # radius at the base
    'tail_r1': 0.007,  # radius at the tip. Not free: below ~0.006 the last
    # beads stop touching at tail_segs=40 and the tip
    # renders as loose pearls — assert_geometry checks it.
    'tail_taper_pow': 1.45,  # r(t) = lerp ** pow — mass at the base, point at the
    # tip. A LINEAR taper is what kept the old tail an
    # even-width tube for its whole length.
    # Fitted 2026-08-27 against anchor_full (ar 1.22) and anchor_side (ar 1.20),
    # NOT against the derived cells — see the note on tail_segs. Sweep best:
    # front 1.21, side 1.18, and the tail clears the furred body by 83 mm — more
    # than the 50 mm of fur, so it reads as a tail rather than beads on a flank.
    #
    # THE CLEARANCE TERM IS NOT OPTIONAL. Fitted on aspect ratio alone the sweep
    # happily returned a tail tucked inside the fur: the bounding box was right and
    # the creature had no visible tail at all. A bbox cannot see a part it contains.
    'tail_p0': (0.91, -0.30),
    'tail_p1': (2.39, 0.17),
    'tail_p2': (2.19, 0.90),
    'tail_p3': (0.78, 1.24),
    'tail_band': 5,  # every Nth segment shows turquoise
    'fur_spike': 0.012,  # surface crinkle amplitude (shading, not silhouette)
    'fur_scale': 26.0,  # noise features across the body
    'hair_len': 0.050,  # strand length — this IS the spiky outline. Swept
    # 0.036/0.050/0.064 against anchor_full: 0.050 puts
    # the front aspect at 1.23 against the anchor's 1.22.
    # Silhouette FILL was not used to pick it — measured
    # 75-77% across every strand length tried, because it
    # is dominated by the alpha threshold and the framing
    # rather than by the fur. Aspect is threshold-free.
    'hair_count': 4200,
    'hair_child': 8,
    'hair_thick': 0.00034,  # EFFECTIVE strand radius in metres. 1.6 mm made each
    # strand ~3.6 px wide at 512 px and 23k of them rendered
    # as an opaque straw mat that swallowed the creature.
    'tail_hair_len': 0.008,
}
