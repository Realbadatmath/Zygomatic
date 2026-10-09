# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

# ruff: noqa: F401,E402
"""BONY RELIEF AT SUBDIVISION LEVEL — the same anatomy, evaluated where the surface can
carry it.

WHY THIS EXISTS. geom/relief.py places fifteen landmark features on anny's 13,718-vertex
CAGE and measures 1/20 -> 3/20 body landmarks resolved on the male original, 2/20 -> 2/20
on the female. The delivered recipes do not carry the layer. The diagnosis this module
acts on is that the failure is a RESOLUTION failure, not an anatomy failure: at 13,718
vertices the median torso edge is 20-27 mm, the falloff radius the layer is allowed is
12.6-13.9 mm, and a feature whose whole support is one or two vertices wide is not a
crest — it is a spike, and the probe's own null on that tessellation reads 2.45e-3 of
stature (4.13 mm at 1.686 m) before any landmark exists. A displacement of 3.0e-3 of
stature into a null of 2.45e-3 is a 1.2x signal, and no placement fixes that.

Detail belongs on the SUBDIVIDED surface. 3D Scan Store's architecture is the same shape
and for the same reason: a clean low-poly base cage, a high-subdivision sculpt layer, and
baked maps. Our own subdivision ladder is 13,718 -> 54,848 (1) -> 219,368 (2, the level
the stills render from) -> 877,448 (3, the level the 3D export carries).

WHAT THIS MODULE DOES AND DOES NOT DO. It subdivides, it re-measures the null at the
subdivided level, it evaluates relief.py's own features at the subdivided vertex
positions, and it probes the result with the SAME resolvers. It does not touch
geom/mesh_skeletons.py, it does not touch geom/relief.py, and it does not re-issue any
delivered character. Wiring is a later step and deliberately not taken here.

THE SUBDIVISION IS CATMULL-CLARK IN PYTHON, NOT BLENDER MULTIRES, AND THAT IS A DECISION
-----------------------------------------------------------------------------------------
Three reasons, in order of weight:
  1. THE GLB IS TRIANGULATED. data/assets/mesh_skeletons/**/skeleton_*.glb exports as one
     mesh of 13,718 verts and 27,420 TRIANGLES with no armature. The 13,710-quad cage
     exists only inside geom/mesh_skeletons.py in Python. Catmull-Clark on triangles gives
     a valence-3 vertex at every original corner and a topology that is not the cage's, so
     any route through the GLB measures a different surface from the one the gates measure.
  2. INDEX PRESERVATION IS LOAD-BEARING HERE. The output vertex order is
     [updated originals | face points | edge points], so cage vertex i is subdivided vertex
     i at every level. That is what lets geom/form/regions.py's frozen, neutral-authored
     vertex groups — the 20 REGION_SPEC patches every relief claim is measured on — be used
     unchanged at 219,368 and 877,448 vertices. A Blender modifier gives no such guarantee,
     and re-authoring the regions on a subdivided mesh would change what is being measured
     at the same time as changing the resolution, which is not an experiment.
  3. It is exact, deterministic and has no unordered reduction: edges come from
     np.unique on sorted index pairs, every average is a np.add.at over a fixed order.

The recurrence is Catmull & Clark 1978 as published (face point = mean of the face's
corners; edge point = mean of the edge's two ends and its two adjacent face points; new
vertex point = (F + 2R + (n-3)P)/n). It is implemented here from that definition — no
third-party code and no external asset, so there is nothing for a PROVENANCE.json to
carry. The cage is closed and all-quad on every component (V-E+F = 8 over 4 components,
E = 2F), so none of the boundary or crease rules apply and the implementation asserts
that rather than assuming it.

WHAT SUBDIVISION COSTS, MEASURED. Catmull-Clark is a smoothing operator: it converges to
the limit surface from the inside. On originals/female the stature goes 1.680013 m ->
1.678345 (level 1) -> 1.677920 (level 2) -> 1.677857 (level 3), i.e. the level-2 surface
is 2.09 mm shorter than the cage — OUTSIDE gates.BUILD_TARGET_STATURE_TOL_MM (2.0 mm).
Any pipeline that subdivides and then re-asserts a build target has to re-anchor stature
after subdivision; that is a finding about the ladder, not about this layer, and every
number below is taken against the stature of the mesh it was measured on.

WHAT IS CARRIED OVER FROM relief.py, BECAUSE IT WAS PAID FOR
------------------------------------------------------------
Everything. This module does not re-implement the layer; it calls relief.apply_relief on
the SUBDIVIDED mesh. So it inherits, unchanged and unweakened:
  * NEWELL NORMALS. The cage's own vertex normals are not mirror-symmetric (max
    |n - mirror(n_partner)| = 1.168, because 10,265 of 13,710 mirrored quads are stored
    from a different start corner). relief.newell_vertex_normals is cyclic-invariant and
    is what the direction field uses. Catmull-Clark inherits the start-corner convention
    face by face, so the trap survives subdivision and so must the defence.
  * SEED LEFT, MIRROR THROUGH THE MUTUAL NEAREST-NEIGHBOUR MAP, THEN SYMMETRISE THE FIELD.
  * AMPLITUDES IN FRACTIONS OF STATURE, so 1.52 m and 1.85 m get the same verdict.
  * FALLOFF_FRAC = 0.0075 strictly inside ridge.RIDGE_GAP_FRAC = 0.008, so no feature can
    reach the collar its own relief is measured against. relief._check_falloff_inside_collar
    still runs at import and still fails loudly.
  * claim='constructed' on every landmark whose bone the 163-bone rig does not have
    (scapula, rib, patella, radius, ulna, sternum), so nothing downstream can read one as
    measured.

THE ONE THING THAT CANNOT BE CARRIED, AND WHAT IS DONE INSTEAD. relief.verify_bone_frame's
second check — "the bone's posed segment lies inside the height span of the vertices its
OWN skinning weights claim" — reads a (13718, 9) per-cage-vertex weight array. Those rows
do not index a subdivided mesh. Rather than transfer weights (which would invent a
quantity and then verify against the invention), the bone frame is verified ON THE CAGE,
with the real weights, BEFORE subdivision, and that record is carried into this module's
report as `bone_frame_cage`. The bone dict is a property of the rig and the pose, not of
the tessellation, so verifying it at cage level verifies it for every level. The depth
check still runs at subdivision level inside relief_field.

THE MIRROR MAP AT HIGH RESOLUTION IS A TRAP, AND IT IS NOT HYPOTHETICAL — IT IS MEASURED
AND IT FIRES. relief.mirror_map pairs each vertex with the nearest vertex to its x-negated
image, mutual matches only. That is safe when the mesh's own mirror residual is far below
the vertex spacing. Subdivision halves the spacing per level while the residual is
inherited from the cage: the male original's cage mirror residual is 0.0599 mm against a
0.2517 mm closest distinct-vertex spacing, a 4.2x margin at cage level and none at all
after two subdivisions. MEASURED at level 2 on originals/male: the geometric search pairs
219,352 of 219,368 vertices and gives 40 of them the WRONG partner. On originals/female
(cage residual 0.0006 mm) it pairs all 219,368 and disagrees on none. So the layer mirrors
through a map derived COMBINATORIALLY through the subdivision instead — originals keep the
cage's partner, a face point pairs with the face whose corner set is the mirror of its own,
an edge point pairs with the mirrored edge. That map is exact by construction, is verified
to reproduce the geometric one where the geometric one is trustworthy, and the
disagreement count is reported at every level rather than absorbed.

THE NULL IS RE-MEASURED AT EVERY LEVEL, AND ITS POOLS ARE MATCHED BY PHYSICAL SIZE.
ridge._pool_of_size matches null pools to probe pools by VERTEX COUNT, which is the right
rule at fixed resolution and the wrong one across resolutions: the same physical patch
holds 4^level times as many vertices after subdivision. What governs the false-positive
rate is the pool's physical extent — the candidate curves through it, their length, their
station spacing — and the candidate count is fixed at SEARCH_N_DIRECTIONS *
SEARCH_N_OFFSETS = 42 whatever the vertex count. So the null's target sizes are scaled by
4**level, which reproduces the cage's physical pools at the new density. Scaling them the
other way (leaving the counts at 30/100/300) would measure the null on patches 1/4 and
1/8 the physical size of the ones being probed, and would be anti-conservative.

TWO CUTS ARE REPORTED PER LEVEL AND THEY ANSWER DIFFERENT QUESTIONS. Neither is tuned.
  SHIPPED CUT — exactly what ridge.probe_pools applies: ridge.station_cut() floored at
    curvature.RELIEF_NULL_P99 / ridge.RIDGE_NULL_P99, min_run floored at the 24-seed panel
    value. This is the cut that produced the published "0 of 20", so this column is the
    apples-to-apples comparison and it is the CONSERVATIVE one.
  LEVEL CUT — the per-station p99 measured on landmark-free skin OF THE MESH BEING PROBED,
    with min_run = max(shipped panel value, the level's own discrete estimate). The station
    floor is allowed to fall below the shipped constant here, and ONLY here, because the
    shipped constant is a property of the 13,718-vertex tessellation and this is a
    different surface; a threshold read off a different mesh is not a control for this one.
    The floor never falls below the level's OWN measurement, the run threshold never falls
    below the panel, and the measured false-positive rate at the level cut is printed
    beside every count so no resolution can be read without its chance rate.

AND THE CONTROL THAT DECIDES THE QUESTION. Three states are probed at every level:
    base       subdivide(cage)                        no relief at all
    cage2sub   subdivide(cage + relief.apply_relief)  the EXISTING layer, viewed at
                                                      subdivision resolution
    sub        subdivide(cage) + relief.apply_relief  this module: the field evaluated at
                                                      the subdivided vertex positions
`base` says how much of any gain is the null shrinking. `cage2sub` says how much is the
probe seeing an existing displacement better. `sub` minus `cage2sub` is the only part that
is attributable to evaluating the field at the higher resolution. Reporting `sub` against
`base` alone would credit this module with the resolver's improvement, and that would be
the wrong conclusion drawn from a real number.

MEASURED RESULT, 2026-08-07 — the numbers this module is allowed to claim.
-------------------------------------------------------------------------
THE NULL DOES FALL WITH RESOLUTION, AND THE ESTIMATOR THAT MATTERS FALLS BY HALF. The
per-station cut the ridge primitive is actually scored on, ridge.ridge_null mode='ridge':
        level 0 (13,718 v)    female 3.6688e-3 / c4.277     male 4.3210e-3 / c4.069
        level 2 (219,368 v)   female 1.9057e-3 / c2.452     male 1.8248e-3 / c2.693
        level 3 (877,448 v)   female 1.7837e-3 / c2.361     male not run
i.e. 1.93x on the female and 2.37x on the male from cage to level 2, and converging by
level 3. Each figure is a p99 over 13,900-50,100 scored stations, so it is well determined.
The ISOTROPIC ball null (curvature.relief_null, the estimator the standing 2.45e-3 figure
comes from) is NOT well determined at its p99 — it is the 3rd largest of ~300 patches — and
it does not fall monotonically: female 2.3564e-3 -> 2.8274e-3 -> 2.1215e-3 over the three
levels, male 3.1131e-3 -> 2.5275e-3. Its CONTRAST p99 does fall monotonically (female 3.662
-> 2.891 -> 2.692; male 4.408 -> 2.148). Read the station cut, not the ball p99.

THE FIELD'S VERTEX SUPPORT WAS THE OTHER HALF OF THE DIAGNOSIS, AND IT IS ARITHMETIC.
Vertices displaced per feature on originals/female, cage -> level 2 -> level 3:
    c7 1 -> 24 -> 84            acromion 2 -> 26 -> 86        asis 2 -> 20 -> 68
    psis 2 -> 26 -> 94          malleolus_med 2 -> 48 -> 172  jugular_notch 3 -> 25 -> 110
    olecranon 6 -> 62 -> 236    ulnar_head 12 -> 166 -> 646   clavicle 26 -> 334 -> 1350
    whole layer 328 -> 4,458 -> 16,841 vertices
SIX of the fifteen features have a support of ONE TO THREE VERTICES on the cage. A landmark
carried by two vertices is not a surface feature at any amplitude, and that is the shape of
the failure the cage-level layer was reporting.

AND YET THE RESOLVED COUNT BARELY MOVES. Body landmark resolution, 20 probes, three states
(base = subdivided cage, cage2sub = the cage-level layer subdivided, sub = this module):
    SCORED AT THE LEVEL'S OWN CUT       base    cage2sub   sub
      female level 0                    0/20     0/20      0/20
      female level 2                    1/20     1/20      2/20
      female level 3                    1/20     0/20      1/20
      male   level 0                    0/20     0/20      0/20
      male   level 2                    1/20     1/20      1/20
    SCORED AT THE SHIPPED CAGE CUT      base    cage2sub   sub
      female level 2                    0/20     0/20      0/20
      male   level 2                    0/20     0/20      0/20
Every landmark that resolves in a `sub` column also resolves in that level's `base` column
except one, so almost all of it is the finer null and not this layer: at level 2 it is
ulnar_head on both bodies, at level 3 it is deltopectoral_triangle on the female, and each
of those reads the same on the UNTOUCHED subdivided cage. The layer's own net contribution
is +1 of 20 on the female at level 2 (olecranon: flat -> ridge/4, +7.91 mm at contrast 7.2),
+0 on the male at level 2, and +0 on the female at level 3.

THE CAGE-LEVEL LAYER, VIEWED AT LEVEL 3, LOSES A LANDMARK THE BARE CAGE HAD. cage2sub
scores 0/20 against base's 1/20 on the female at level 3: subdividing the cage-level
displacement turns the deltopectoral fossa from furrow/5 into point_only/3. Evaluating the
same features at level 3 keeps it (furrow/4). That is the one place the two states separate
cleanly, and it says the cage-level field is not merely too weak — at this resolution it is
mildly destructive, because a 2-vertex spike smoothed by Catmull-Clark is not the feature
it was standing in for.

WHAT DID MOVE, AND WHAT IT SAYS THE REAL BOTTLENECK IS. Landmarks reading 'flat' fall from
16/20 to 8/20 (female L2), 16/20 to 9/20 (male L2) and 17/20 to 10/20 (female L3) when the
field is evaluated at subdivision level, and peak contrast rises sharply where it does:
female L2 malleolus_med c1.8 -> c17.8, olecranon c-2.9 -> c7.2, malleolus_lat c2.5 -> c7.2;
male L2 sternal_end c-1.3 -> c14.3, olecranon c-3.5 -> c12.9, malleolus_med c2.2 -> c9.8;
female L3 malleolus_med c2.1 -> c11.9, malleolus_lat c-3.3 -> c6.7, ulnar_head c2.5 ->
c6.1. So the landmark IS on the surface now and a
depth or normal pass will carry it. What stops it counting as resolved is CONTINUITY: the
verdict needs a same-sign qualifying RUN of 3 (point mode) or 4 (ridge mode) consecutive
stations, and eight of these twenty probes are single prominences — a malleolus, an
olecranon, an acromion, the ASIS — which under a CURVE primitive can only ever produce
run 1, i.e. 'point_only', which ridge.RESOLVED_VERDICTS correctly refuses because it occurs
on 8-29% of landmark-free skin. That is a gap in the PROBE SET, not in the layer and not in
the resolution: there is no point-landmark primitive whose verdict is allowed to resolve.

SO: resolution was a real bottleneck and it is now measured rather than argued, but it was
not the only one and on these amplitudes it is not the binding one. Nothing here licenses
raising an amplitude to chase a count, and nothing here has been.

STRUCTURAL RESULTS, all measured on both bodies at level 2 and on the female at level 3:
  index preservation  originals moved 0.54 mm median / 6.96 mm max (female L2) and 0.57 /
                      7.29 mm (female L3), corner counts preserved exactly at both levels,
                      0 structural mismatches
  mirror              field residual after symmetrisation 0.000e+00 mm at every level;
                      combinatorial map pairs 219,368/219,368 and 877,448/877,448
  geometric map       female agrees everywhere; MALE at level 2 pairs only 219,352 and
                      mispairs 40 — the trap, fired. Verified separately: the delivered
                      mesh is byte-identical under both maps on the male at level 2, so
                      those 40 vertices are outside every displaced region TODAY. It is a
                      latent defect, not a live one, and the combinatorial map closes it.
  stature             Catmull-Clark costs 2.09 mm (female) and 1.95 mm (male) by level 2,
                      against gates.BUILD_TARGET_STATURE_TOL_MM = 2.0 mm. A pipeline that
                      subdivides and then re-asserts a build target must re-anchor.
  determinism         `python -m zyg_workflows.geom.relief_subdiv determinism female 2` — subdivide plus
                      sculpt at 1 and at 8 torch threads, sha256 96b18b7f9e0b7a86 both ways
  cost                level 2: subdivide 0.2 s, mirror map <1 s, field 15 s, point null
                      312 s, ridge null 416 s, one probe pass 321-430 s; whole run 3,430 s
                      (female) / 3,277 s (male) concurrent, peak RSS 1.61 GB.
                      level 3: subdivide 1.7 s, mirror map 16.7 s, field 118 s, point null
                      698 s (150 patches), ridge null 539 s (4 pools/size), one probe pass
                      783-808 s; whole female run 3,817 s, peak RSS 2.38 GB. The male at
                      level 3 was NOT run: it is another ~3,800 s and the male's level-2
                      result already shows the same pattern.
                      relief.mirror_map's own loop costs 166 s of the level-2 field build
                      and is why fast_mirror_map exists; with it the build is 15 s.

EVERY REPORT SAYS WHICH BUILD WROTE IT. `measure()` stamps `produced_by` with the sha256 of
this file, of geom/form/ridge.py and of geom/relief.py, plus the seed panel. This is not
bookkeeping: the first delivered level-2 artefacts were written by a build that mirrored
through the GEOMETRIC map and derived the level cut from ONE null draw, and they sat on disk
looking current with nothing in them to say otherwise. A report with no `produced_by` key
predates 2026-08-08 and its numbers are not this code's numbers; one whose sha does not
match the module you are reading is stale the same way. See PROVENANCE.md next to the
reports. THE SELF-TEST ASSERTS — it raises and main() returns 1 on any failed invariant, so
a CI step reading the exit status is told the truth by it.

COST WARNING, AFTER THE SEED PANEL. The level null is now drawn over six seeds
(LEVEL_NULL_SEED_PANEL), so the dominant cost of a `measure` run is multiplied by six
against the single-draw figures quoted above. Level 0 is ~4 minutes; level 2 and level 3
are hours, not the 3,300-3,800 s recorded above. Run the two level-2 bodies concurrently.

RUN IT
    python -m zyg_workflows.geom.relief_subdiv selftest                 primitives, no anny model
    python -m zyg_workflows.geom.relief_subdiv determinism female 2
    python -m zyg_workflows.geom.relief_subdiv measure female 2         one body, one level
    python -m zyg_workflows.geom.relief_subdiv measure female 2,3 out.json
"""

import json
import os
import resource
import sys
import time

import numpy as np
import logging as _zyg_logging

from zyg_workflows.geom.relief_subdiv.constants import (
    _zyg_log,
    SCHEMA,
    _module_provenance,
    SUBDIV_STILLS,
    SUBDIV_3D,
    CAGE_VERTS,
    CAGE_FACES,
    CAGE_NULL_TARGET_SIZES,
    NULL_POOLS_BY_LEVEL,
    POINT_NULL_N_BY_LEVEL,
    LEVEL_CUT_ABSOLUTE_FLOOR_FRAC,
    LEVEL_CUT_ABSOLUTE_FLOOR_CONTRAST,
    LEVEL_NULL_SEED_PANEL,
)
from zyg_workflows.geom.relief_subdiv.subdivision import (
    catmull_clark,
    subdivide,
    subdiv_mirror_map,
    fast_mirror_map,
    _verify_fast_mirror_map,
    mirror_map_override,
    _lexsearch,
    verify_index_preservation,
)
from zyg_workflows.geom.relief_subdiv.nulls import (
    _pooled_runs_at,
    _panel_cut,
    level_null,
    cuts_for,
    probe_at_cut,
)
from zyg_workflows.geom.relief_subdiv.layer import apply_relief_at, mirror_audit
from zyg_workflows.geom.relief_subdiv.measurement import (
    _row,
    _fmt,
    measure,
    determinism_check,
    _jsonable,
)
from zyg_workflows.geom.relief_subdiv.cli import self_test, main
