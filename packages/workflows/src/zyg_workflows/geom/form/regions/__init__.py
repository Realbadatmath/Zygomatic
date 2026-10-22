# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Named vertex GROUPS for form predicates on the anny 13,718-vertex cage — and an honest
record of which named landmarks have no signature on it at all.

WHY GROUPS AND NOT POINTS
geom.anthro.landmarks answers "where is this landmark", and a point is the right answer to
that: a landmark height is a scalar. A FORM predicate asks a different question — "does the
clavicle read as visible", "do the buttocks sit inside the hips", "is the inferior angle of
the scapula showing" — and the answer to that is a PATCH and its relief against the skin
around it. One vertex has no relief; a patch does.

WHY THIS FILE IS MOSTLY A LIST OF FAILURES
The rules these groups exist to test come from figure-drawing anatomy — Anatomy For
Sculptors' free blog for the shoulder and pelvis material, Gray's Anatomy 1918 "Surface
Anatomy and Surface Markings" and Bridgman's Constructive Anatomy 1920 for the same
landmarks in the public domain. Those texts describe a HUMAN BODY. This cage is a
MakeHuman-derived quad shell whose morph vocabulary contains no bone at all, and
geom.anthro.landmarks already had to report five ANSUR landmarks UNRESOLVED because the
cage carries no vertebra prominens, no costal margin, no iliac crest, no radial styloid and
no lateral malleolus. The same thing happens here, and it is the most useful thing this file
says. MEASURED on the anny neutral, against that body's OWN relief null (curvature.
relief_null: p99 of |relief| over random torso and limb skin is 2.45e-3 of stature, 4.1 mm
at 1.686 m, at a contrast of 3.66):

  * NO CLAVICLE. A sweep of the whole antero-superior shoulder, 202 vertices, tops out at
    +4.4 mm at a contrast of 1.6 — below the body's own p99 — and the raised vertices do not
    form a line from the sternum to the acromion. They form a VERTICAL ridge at x = 0.09 m,
    which is the trapezius edge, not the clavicle.
  * NO SCAPULAR SPINE, MEDIAL BORDER OR INFERIOR ANGLE. 139 vertices over the posterior
    shoulder; strongest feature +4.2 mm at contrast 2.7, and it is that same vertical
    trapezius ridge. Nothing runs horizontally where a scapular spine would.
  * NO PSIS DIMPLES. The whole sacral window holds 23 VERTICES. The only depression in it
    sits at x = 3 mm — the midline natal cleft, not a paired dimple 30 mm off-centre. A
    feature the cage does not have the vertices to represent cannot be measured on it.
  * NO ASIS.
  * NO MALLEOLAR OR ULNAR-HEAD PROMINENCE, confirming landmarks.py from the other direction:
    it found no local maximum in the malleolar HEIGHT profile, and there is none in the
    surface RELIEF either (-0.2 mm lateral, +0.7 mm medial, contrast 0.06 / 0.29).

Inventing an anchor for any of those would be the one unforgivable outcome, because a form
gate that measures the wrong patch will confidently pass a deformed body.

WHAT DOES RESOLVE, and by what right — in the order of preference the brief sets out:
  (a) a MakeHuman morph support (landmarks._support). MakeHuman's own statement about where
      an anatomical region is. Used for the deltopectoral triangle, which is definitionally
      the gap between the DELTOID and the PECTORALIS, and both of those have named targets.
  (b) a geometric construction from a landmark geom.anthro.landmarks already resolved —
      acromion and trochanterion, each grown into a patch by a graph geodesic ball.
  (c) a JOINT LINE. A segment-length morph does not move the joint it pivots about, so the
      BOUNDARY of its support is that joint's line on the skin. landmarks.py already uses
      the trick for tibiale; here it gives the elbow, knee, hip and shoulder lines as closed
      20-vertex rings, and sectors of those rings in the limb's own frame give the
      olecranon, the two humeral epicondyles, the patella and the malleoli.

THE CLAIM FIELD IS THE POINT OF THIS FILE. Every resolved region carries `claim`:
  'landmark'       the patch is anchored ON the named structure and a predicate may read
                   the structure's shape from it.
  'surface_aspect' the patch is positionally right — it is the lateral aspect of the ankle,
                   the front of the knee — but the named BONE has no measured signature
                   there. A predicate may say "this aspect is flatter than that one"; it may
                   NOT say "the malleolus is prominent", because nothing here can see one.
A region with claim 'surface_aspect' that gets written into a gate as if it were a landmark
is exactly the failure mode this whole module exists to prevent.

MIRROR CONSISTENCY IS BY CONSTRUCTION, NOT BY SEARCH. Only the LEFT group is ever resolved;
the right one is its image under landmarks._mirror(), the cage's own vertex pairing. If both
sides were searched independently they would disagree by a vertex here and there and a form
predicate would report a left/right asymmetry that is an artefact of the grouping. That
matters especially because per-vertex curvature on this cage is NOT mirror-symmetric (see
curvature.py, trap four: 34.55 max residual in H*stature on a cage that mirrors onto itself
to 0.0167 mm).

GROUPS ARE AUTHORED ONCE, ON THE NEUTRAL, AND FROZEN. Every anchor here is topology-fixed,
so a group is a fixed patch of SKIN and the morphs carry that skin with the body. Resolving
per-body instead would let the patch wander between characters and destroy the comparison
the predicates exist to make. The consequence must be stated plainly: on abel (12 y) the
patch called `patella_l` is the same skin as on cornelis (43 y) by MakeHuman's own
correspondence, and nothing here verifies that the correspondence is anatomically true at
that age.
"""

# Pattern A package: regions.py was cut at its own section banners into the modules below.
# The original top import block is re-done here so old attribute access (regions.os, ...)
# still resolves, the submodules are imported in the original section order, and every
# name the single module defined is re-exported.

import hashlib
import json
import os
import sys
import tempfile
import time

import numpy as np
from zyg_workflows.geom import mesh_skeletons as MS  # noqa: E402
from zyg_workflows.geom.anthro import landmarks as LM  # noqa: E402
from zyg_workflows.geom.form import curvature as CV  # noqa: E402
import logging as _zyg_logging

from zyg_workflows.geom.form.regions.context import (
    _zyg_log,
    SCHEMA_VERSION,
    CAGE_VERTS,
    CAGE_FACES,
    REGIONS_PATH,
    FEATURE_MIN_FRAC,
    FEATURE_MIN_CONTRAST,
    FEATURE_PROBE_RADIUS,
    _patch_seed_fix_enabled,
    _CTX,
    _ctx,
    _relief,
    _ball,
    _support,
    _left,
    _joint_line,
    _limb_frame,
    _sector,
    _r_landmark_ball,
    _r_support_gap,
    _r_feature_search,
    _window_mask,
    _RESOLVERS,
)
from zyg_workflows.geom.form.regions.spec import (
    REGION_SPEC,
    REGION_NAMES,
)
from zyg_workflows.geom.form.regions.builder import (
    _ARM_LABELS,
    _sector_ring,
    _sector_axis_rings,
    _resolve_left,
    build_regions,
    _safe_relief,
    _one_line,
    _jsonable,
    _content_sha,
    _atomic_json,
    load_regions,
    mirror_check,
    resolve_regions,
    main,
)
from zyg_workflows.geom.form.regions.context import __all__

__all__ = __all__ + [
    'hashlib',
    'json',
    'os',
    'sys',
    'tempfile',
    'time',
    'np',
    'MS',
    'LM',
    'CV',
    '_zyg_logging',
    '_zyg_log',
    'SCHEMA_VERSION',
    'CAGE_VERTS',
    'CAGE_FACES',
    'REGIONS_PATH',
    'FEATURE_MIN_FRAC',
    'FEATURE_MIN_CONTRAST',
    'FEATURE_PROBE_RADIUS',
    '_patch_seed_fix_enabled',
    '_CTX',
    '_ctx',
    '_relief',
    '_ball',
    '_support',
    '_left',
    '_joint_line',
    '_limb_frame',
    '_sector',
    '_r_landmark_ball',
    '_r_support_gap',
    '_r_feature_search',
    '_window_mask',
    '_RESOLVERS',
    'REGION_SPEC',
    'REGION_NAMES',
    '_ARM_LABELS',
    '_sector_ring',
    '_sector_axis_rings',
    '_resolve_left',
    'build_regions',
    '_safe_relief',
    '_one_line',
    '_jsonable',
    '_content_sha',
    '_atomic_json',
    'load_regions',
    'mirror_check',
    'resolve_regions',
    'main',
]
