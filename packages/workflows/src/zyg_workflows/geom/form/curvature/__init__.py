# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

# ruff: noqa: F401,E402
"""Signed surface relief on the anny quad cage — the substrate every FORM predicate stands on.

WHY THIS MODULE EXISTS
geom.anthro answers "is this body inside the measured human distribution". Every historic
defect in this project passed those gates and failed the eye: a pectoral morph at 1.5 that
read as a bust (the widths were fine), a female solve that hit every width target within
1-2% while producing a swayback lumbar line, an abs sculpt that was 3.76 mm asymmetric. A
metric gate cannot see any of that, because what it gets wrong is RELIEF — whether a patch
of skin reads as a protrusion, a depression, or nothing at all. This module measures relief
and nothing else; the predicates that decide what a given relief MEANS live beside it.

THE FIRST TRAP is that an absolute curvature number on a body is meaningless. The mean
curvature over the deltoid of the anny neutral is +18 1/m and over the sternum +12 1/m —
both convex, because a torso is convex nearly everywhere, and neither figure says whether
a clavicle is showing. The landmark question is always LOCAL CONTRAST: is this patch
raised or sunk RELATIVE TO THE SURFACE AROUND IT. That is what region_relief does — it
dilates the group into a surrounding collar, fits a quadric to the collar ALONE, and
reports the group's residual against it. The result is a physical depth in millimetres, so
a threshold can be argued about in anatomical terms instead of in units of 1/m.

THE SECOND TRAP is scale. Curvature carries units of 1/m, so the same shape at 1.52 m
(abel) and 1.85 m (the male original) produces numbers that differ by 22%, and a threshold
tuned on one body silently fails the other. Everything scale-bearing here is therefore also
reported normalised by stature: `h_norm = H * stature` and `relief_frac_stature`. Both are
invariant to a uniform scale, and self_test() proves it by scaling a real character.

THE THIRD TRAP is the diagonal. A quad whose corners are not coplanar does not define a
surface: the 0-2 split and the 1-3 split are two different surfaces over the same control
points, and they disagree about curvature. The surface that SHIPS is the 0-2 split —
mesh_skeletons._export_glb writes np.concatenate([faces[:,[0,1,2]], faces[:,[0,2,3]]]) —
so that is the only surface on which a curvature result here is a statement about the
delivered artifact. We reuse geom.anthro.integrity.triangulate_quads rather than repeat the
choice, and refuse any other diagonal for curvature.

THE FOURTH TRAP is the normal, and it is subtle enough that it has already bitten this
project once. mesh_skeletons._vertex_normals takes each quad's normal from corners (0,1,2)
only. anny's quad set is a perfect mirror image of itself, but 10,265 of the 13,710 quads
are STORED STARTING AT A DIFFERENT CORNER on the mirrored side, so on a warped quad that
one-triangle normal is not mirror-equivariant — measured max |n - mirror(n_partner)| =
1.168, i.e. the two sides can disagree about which way the surface faces. A signed relief
built on that normal would manufacture left/right asymmetry that is not in the body. So
this module (a) computes vertex normals over BOTH delivered triangles, area-weighted, and
(b) takes the local frame for region_relief from a PCA of the collar's POSITIONS, which are
mirror-symmetric to 0.06 mm on these cages. What is left is not small and must be
respected: on the anny NEUTRAL, whose vertices mirror onto themselves to 0.0167 mm,
per-vertex stature-normalised mean curvature still differs between mirror partners by up to
34.55 (rms 0.699) against a body median of 20.3, and shape index by up to 0.38 (rms
0.0086). PER-VERTEX CURVATURE IS THEREFORE NOT A LEFT/RIGHT COMPARISON on this cage.
mirror_residual() measures that floor for any field a caller wants to compare across sides;
region_relief, being built from positions, does not inherit it.

SIGN CONVENTION: positive is CONVEX — a sphere of radius R comes out at H = +1/R
everywhere, a plane at 0, a saddle mixed. That is not asserted, it is measured: self_test()
builds those three primitives and fails loudly if the convention has drifted.

WHAT THIS MODULE DOES NOT DO: it does not know what a clavicle is. It takes a vertex group
from geom.form.regions and returns a number. If the group is wrong, the number is
confidently wrong, which is exactly why regions.py refuses to invent groups.

References for the discrete operators: Meyer, Desbrun, Schroder & Barr, "Discrete
Differential-Geometry Operators for Triangulated 2-Manifolds" (2003) for the cotangent
Laplace-Beltrami operator, the mixed Voronoi area and the angle-deficit Gaussian curvature;
Koenderink & van Doorn, "Surface shape and curvature scales" (1992) for the shape index and
curvedness. Both are standard published mathematics, implemented here from the definitions.
"""

import hashlib
import os
import sys
import weakref

import numpy as np

from zyg_workflows.geom.anthro import integrity as _integrity
import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)

from zyg_workflows.geom.form.curvature.topology import (
    _require,
    DELIVERED_DIAGONAL,
    SHAPE_CLASSES,
    delivered_triangles,
    _FACE_EDGE_CACHE,
    _FACE_EDGE_STATS,
    ZYG_FACE_EDGE_CACHE,
    _face_edges,
    face_edge_cache_stats,
    vertex_adjacency,
    dilate,
    COLLAR_GAP_FRAC,
    COLLAR_WIDTH_FRAC,
    COLLAR_MAX_TILT_DEG,
    COLLAR_MIN_VERTS,
    collar,
    boundary_vertices,
    vertex_normals,
    _triangle_terms,
    mixed_voronoi_area,
    cotangent_weights,
    curvature,
    shape_index,
    curvedness,
    shape_class,
    surface_distance,
)
from zyg_workflows.geom.form.curvature.relief import (
    RELIEF_MIN_CONTRAST,
    RELIEF_MIN_FRAC_STATURE,
    RELIEF_NULL_P99,
    region_relief,
    _footprint_reach,
    geodesic_ball,
    relief_null,
    mirror_residual,
)
from zyg_workflows.geom.form.curvature.selftest import (
    _quad_grid,
    _cube_sphere,
    self_test,
    main,
)

__all__ = [
    'delivered_triangles',
    'vertex_adjacency',
    'dilate',
    'collar',
    'boundary_vertices',
    'vertex_normals',
    'mixed_voronoi_area',
    'cotangent_weights',
    'curvature',
    'shape_index',
    'curvedness',
    'surface_distance',
    'geodesic_ball',
    'region_relief',
    'relief_null',
    'mirror_residual',
    'shape_class',
    'self_test',
    'DELIVERED_DIAGONAL',
    'SHAPE_CLASSES',
    'RELIEF_MIN_CONTRAST',
    'RELIEF_MIN_FRAC_STATURE',
    'RELIEF_NULL_P99',
    'COLLAR_GAP_FRAC',
    'COLLAR_WIDTH_FRAC',
    'COLLAR_MAX_TILT_DEG',
]
