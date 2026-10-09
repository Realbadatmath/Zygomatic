# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

# ruff: noqa: F401
"""integrity.py — Tier-1 mesh integrity, the checks that must pass BEFORE any
anthropometric number taken off a mesh means anything (2026-08-05).

WHY THIS EXISTS. Every measurement the anthro layer will make — a stature, a girth from
a plane slice, a landmark height — assumes it is measuring a closed, orientable, non
self-penetrating surface. None of those assumptions is free. A girth taken through a
region where the arm passes through the ribcage returns a number; the number simply has
no referent. So the plausibility gates upstream of us are only meaningful on a mesh that
has cleared this file first, and this file must therefore never approximate.

THE TRAP IT AVOIDS is the single `is_valid` boolean. These are FOUR unrelated failure
modes and a body mesh routinely passes three and fails the fourth:
  * `trimesh.is_watertight` conflates "no boundary edges" with "no edge in >2 faces",
    reports one bool for both, and says nothing at all about the remaining two;
  * VERTEX-manifoldness (two cones meeting at a single pinch vertex — every edge is
    perfectly 2-manifold, yet the surface is not a surface) is the check most often
    skipped, because it needs a per-vertex link-graph traversal rather than an edge
    histogram. It is implemented properly here;
  * SELF-INTERSECTION is invisible to every topological check ever written. It is pure
    geometry, and on a human mesh it is the failure that actually happens — arm into
    torso, thigh into thigh, chin into neck.
Each check therefore reports independently, with its own pass flag and its own wall time.

THE SECOND TRAP is symmetry. There are two different quantities that both get called
"asymmetry" and merging them destroys both:
  * MORPH-CORRECTNESS (this file, `mirror_symmetry`): a body built from a bilaterally
    symmetric morph space must be symmetric to floating-point noise. Any deviation is a
    BUG in the build — a broken morph, or a post-morph sculpt that is not mirror-
    equivariant. Expected value: zero.
  * REALISM asymmetry: a deliberate 0-10mm injection (population mean 5.2mm) that makes
    a body stop looking machine-made. Expected value: NOT zero.
A gate that sees 3.8mm cannot tell you which one it is looking at, so this file measures
only the first and names it so in the returned payload. The second is not ours.

THE THIRD TRAP is calling a mesh "the mesh". WHAT THE ANNY CAGE ACTUALLY IS — measured
2026-08-05, identical on all four issued characters (male, female, abel, cornelis):

    comp 0   13348 v   closed, chi=2, GENUS 0            the body shell
    comp 1     226 v   closed, chi=2, genus 0, midline   the TONGUE      z 0.874-0.893 H
    comp 2      72 v   closed, chi=2, genus 0, +x side   an EYEBALL      z 0.918-0.941 H
    comp 3      72 v   closed, chi=2, genus 0, -x side   an EYEBALL      z 0.918-0.941 H

FOUR shells, not one. That single fact was worth 338-520 false "self-intersecting quad
pairs" per character before this file learned it: every one of those pairs was between
the eyeball shell and the head, i.e. an eye sitting in its socket, which is correct
modelling and not the cage penetrating itself. Intra- and inter-component contact are
therefore counted and reported SEPARATELY here, and only the intra-component count is a
defect. Measured after the split, in the triangulation that ships: male 0, cornelis 0,
abel 18 (mouth interior + both sets of toes), female 20 (toes, both feet) — the genuine
self-intersections that the eyeball noise had been burying.

WHICH TRIANGULATION IS "THE CAGE" IS ALSO A DECISION, and it is decided by the artifact,
not by us. A quad cage has two valid triangulations and they can disagree about self
contact; this file used to count only the pairs that BOTH diagonals agree on and call the
rest artefacts. That is right about the abstract quad cage and wrong about what we ship:
mesh_skeletons._export_glb writes skeleton_*.glb as [0,1,2]+[0,2,3], so the '02' diagonal
IS the delivered surface and a pair that crosses under it is a real defect in the
delivered artifact whatever the other diagonal says. MEASURED: abel has 18 such pairs
under '02', 16 under '13', 6 agreeing — and four of the twelve the old criterion threw
away are AT THE TOES (z 0.008), which is why abel's report used to place its
self-intersections at "the head". The gating number is now the delivered one; the
diagonal-agreeing subset and the pairs that exist only under the OTHER diagonal (which
genuinely do not ship: cornelis has 4) are both still reported.

AND "ENCLOSED" IS NOT WHAT YOU THINK, which is why this file measures it instead of
assuming it. A closed surface's inside is decided by the winding number, and an
INVAGINATION IS OUTSIDE: the mouth and the eye sockets are pockets in the body shell that
open to the exterior, so on all four cages
  * the tongue is 226/226 vertices OUTSIDE the body solid, does not touch it (0
    intersecting pairs, nearest approach 8-10 mm), and reaches open sky in 0.000-0.008 of
    directions — it is sealed inside the mouth pocket, exactly as it should be;
  * each eyeball straddles the surface (52/72 in for male, 35-37/72 for female and abel):
    its anterior cap lies outside the shell, bounded by the eyelid margin. That is the
    visible eye, seen through the palpebral aperture, and it is why "small == enclosed"
    must never be assumed. It also means genus 0 for the body: the mouth is a blind
    pocket, not a tunnel through to the throat.
The body shell's own genus is verified and reported per component, comp 0 alone.

SO WHAT SEPARATES "IN A POCKET" FROM "FLOATING LOOSE"? Not a tuned escape fraction — that
was the first answer here and it was wrong. It read "how much sky can this shell see",
calibrated on a single example (the tongue, 0.000-0.008) with the line at 0.05, and a
perfectly good eyeball recessed into its socket (bone_scale 0.80, still 22-30 mm inside
the head, touching nothing) scores 0.055 and was called a DEFECT by it. The line is now
the BODY'S CONVEX ENVELOPE, which is a measurement rather than a calibration:
  * a shell every vertex of which lies inside conv(body) is inside the body's own
    envelope — it is in a concavity of the body, which is what a mouth and an eye socket
    ARE. MEASURED margins: tongue 50-125 mm inside, recessed eyeball 22-30 mm inside;
  * a shell with any vertex outside conv(body) has left the envelope while touching
    nothing. MEASURED: tongue displaced 120 mm anterior sits 65 mm outside (92% of its
    vertices), displaced 2 m it is 1.87 m outside, a shell adrift between the thighs is
    31 mm outside, one adrift behind the knee 103 mm.
The escape fraction is still measured and still load-bearing — but the line it is read
against is 1/2, and 1/2 is a THEOREM rather than a calibration: from a point outside a
convex set every direction that hits the set lies in one open half-space, so such a point
must escape in MORE than half of all directions. Outside the envelope that is a proof and
it cross-checks the hull; inside the envelope the converse does not follow, so the same
number is used as a requirement instead — a shell that sees sky in most directions is not
in a pocket, whatever the hull says. Either way the two tests check each other rather than
one tuned scalar deciding alone, and when they disagree the shell is reported UNRESOLVED,
which is a defect state, because "the two ways of asking disagree" is not a pass.

NO open3d, NO pyembree — not installed and deliberately not a dependency. numpy, scipy
and trimesh only. The self-intersection narrow phase is an exact Moller triangle-triangle
test; the broad phase is a radius-binned cKDTree, because the flat single-radius
alternative allocates 22.6M candidate pairs on this cage where the binned one allocates
1.8M for identical results (measured, see SELF_INTERSECTION_NOTE).

Provenance discipline: every threshold below is tagged MEASURED (with source and n),
HOUSE (our policy, with the rationale), or is not shipped at all.
"""

import os
import time

import numpy as np
from scipy.sparse import csr_matrix
from scipy.sparse.csgraph import connected_components
from scipy.spatial import ConvexHull, cKDTree

from zyg_workflows.geom.anthro.integrity.constants import (
    EPS_DUPLICATE_M,
    EPS_AREA_M2,
    EPS_PLANE_M,
    EPS_NORMAL,
    SYM_MORPH_TOL_MM,
    _BROAD_BINS,
    SELF_INTERSECTION_NOTE,
    WINDING_INSIDE,
    WINDING_GUARD,
    ENVELOPE_ESCAPE_MAX_FRACTION,
    HULL_MARGIN_EPS_M,
    HULL_VERIFY_TOL_M,
    SKY_DIRECTIONS,
    SKY_PROBE_VERTICES,
    PARITY_DIRECTIONS,
    MAX_SHELLS_ANALYSED,
    MAX_CONTAINMENT_PROBE_VERTICES,
    BODY_DOMINANCE_MIN_RATIO,
    SHELL_SIGNATURES,
    MIDLINE_FRAC_OF_STATURE,
    TOPOLOGY_SCOPES,
    _now,
    _ms,
)
from zyg_workflows.geom.anthro.integrity.mesh_checks import (
    triangulate_quads,
    _undirected_edges,
    _check_watertight,
    _check_edge_manifold,
    _check_vertex_manifold,
    _check_winding,
    _signed_volume,
    _check_outward,
    _check_degenerate,
    _components,
    _check_euler,
    _tri_spheres,
    _stride,
)
from zyg_workflows.geom.anthro.integrity.self_intersection import (
    _broadphase,
    _interval,
    _tri_tri,
    _intersecting_pairs,
    _face_components,
    _split_by_component,
    _check_self_intersection,
    _pair_z,
    _spread_by_z,
    _z_span,
    _locality,
)
from zyg_workflows.geom.anthro.integrity.shells import (
    _fibonacci_directions,
    _winding_numbers,
    _ray_crossings,
    _envelope_margin,
    _convex_envelope,
    _name_shell,
    _STATE_MEANING,
    _DEFECT_STATES,
    _check_shell_components,
)
from zyg_workflows.geom.anthro.integrity.symmetry_topology import (
    mirror_symmetry,
    _check_mirror,
    _resolve_expect,
    face_topology_sha,
    _check_topology_identity,
    monotonic_chain,
)
from zyg_workflows.geom.anthro.integrity.entry import (
    check_integrity,
    _fmt,
    _print_shells,
    main,
)
