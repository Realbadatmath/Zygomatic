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

# ruff: noqa: F401, E402

from .constants import (
    math,
    bmesh,
    bpy,
    Vector,
    _zyg_logging,
    _zyg_log,
    IDX,
    P,
)
from .geometry import (
    _link,
    _sagitta,
    _face_centre_y,
    _face_surface_y,
    _outward,
    _cylindrical_uv,
    _sphere,
    _uv_sphere_data,
    _capsule,
    _subsurf,
    _fur,
    _bald_patch,
    _hair,
)
from .parts import (
    materials,
    build_body,
    build_face,
    build_eyes,
    build_mouth,
    build_arms,
    build_legs,
    build_feet,
    build_tail,
)
from .checks import (
    FUR_GEOMETRY_TAGS,
    is_fur_geometry,
    signed_volume,
    assert_geometry,
    assert_parts_visible,
    build,
    bounds,
)
