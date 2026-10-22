# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""BONY RELIEF SCULPT LAYER — landmark-anchored displacement over the anny cage.

WHY THIS EXISTS. The ControlNet depth and normal passes we render off these bodies carry
no bony-landmark signal at all: measured on the delivered originals, 0 of the 20 body
landmark probes in geom/form/regions.py resolve outside the cage's own relief null
(2.45e-3 of stature at contrast 3.66). The three that come closest — patella +8.90 mm
(contrast 3.06), epicondyle_lat +6.84 (11.5), epicondyle_med +4.53 (2.69) — are the elbow
and knee FLARING wider than the limb above and below them, not modelled bone. There is no
clavicle, no iliac crest, no trochanter, no PSIS, no cervicale, and both malleoli measure
flat (-0.18 mm / +0.71 mm). An image model conditioned on those passes has to invent the
skeleton in every frame, and invents it differently each time.

This module is the sibling of mesh_skeletons._apply_anatomy: the same kind of layer (a
displacement field on the CAGE, after morphs, before export and subdivision), anchored on
LANDMARKS instead of on a body region. It does not edit mesh_skeletons; the entry point a
caller wires in is apply_relief(), which has the same shape as _apply_anatomy() and is a
strict no-op — byte-identical output, no report side effects beyond `absent` — when the
anatomy dict carries no 'bony_relief' key.

    v = relief.apply_relief(v, faces, anatomy, phenotype=phen, bones=bones)

THE FOUR THINGS THAT MAKE THIS MEASURABLE RATHER THAN DECORATIVE
---------------------------------------------------------------
1. ANCHORED ON THE RIG WHERE THE RIG HAS A BONE. The clavicle, olecranon, ulnar head,
   malleoli, acromion and C7 are placed off anny's own 163-bone skeleton, taken in the
   POSED frame (see bone_frame() — the rest frame is a different frame and using it would
   put the clavicle at 0.910 of stature, in the neck). Landmarks whose bone the rig does
   NOT have — there is no scapula, rib, patella, radius, ulna or sternum bone — are
   constructed and every record carries claim='constructed' so no predicate can read one
   as a measurement. The iliac crest's HEIGHT is the one constructed quantity with a
   measured source: ANSUR II iliocristale/stature, via landmarks.REFERENCE_FRACTIONS.

2. SYMMETRIC BY CONSTRUCTION, THEN MEASURED. The cage's vertex normals are structurally
   non-mirror-symmetric — max |n - mirror(n_partner)| = 1.168 over the cage, because
   10265 of 13710 mirrored quads are stored starting at a different corner and
   mesh_skeletons._vertex_normals takes each face normal from corners (0,1,2) only. That
   trap already cost _apply_anatomy one rebuild. Three independent defences here:
     (a) this module uses its own NEWELL normals (all four corners, cyclic-invariant), so
         the direction field is mirror-symmetric to ~2e-3 before anything else runs;
     (b) every bilateral feature is seeded on the LEFT and its right seeds are taken as
         the mirror PARTNERS of the left ones through the mutual nearest-neighbour map,
         so the two sides are the same construction on the same numbers;
     (c) the finished displacement field is symmetrised through that same mutual map,
         exactly as _apply_anatomy does.
   The residual is then MEASURED in mm and reported, against integrity.SYM_MORPH_TOL_MM.

3. THE FALLOFF RADIUS CANNOT INFLATE ITS OWN CONTRAST. Every feature falls to exactly
   zero at FALLOFF_FRAC = 0.0075 of stature, strictly inside ridge.RIDGE_GAP_FRAC =
   0.008, which is the inner edge of the collar the probe measures relief AGAINST. The
   layer therefore never lifts its own collar. This is a structural property, not a tuned
   number: if RIDGE_GAP_FRAC ever moves, _check_falloff_inside_collar() fails loudly.

4. AMPLITUDES ARE IN FRACTIONS OF STATURE. A 1.68 m and a 1.85 m body get the same
   verdict. The ladder is the one the three resolved landmarks measured on this cage:
   patella +8.90 mm = 5.3e-3 S > epicondyle_lat 4.0e-3 > epicondyle_med 2.7e-3, with the
   null at 2.45e-3.

WHAT THE MEASURED RELIEF OF A CREST IS NOT. Relief is measured against a COLLAR at 0.008
to 0.022 of stature from the feature. Each feature's own falloff stops short of its own
collar (point 3), but a NEIGHBOURING feature's does not have to: the supraclavicular and
infraclavicular fossae sit 0.017 and 0.022 of stature from the clavicle crest, i.e. inside
the crest's collar band. So the clavicle's measured relief is the crest's displacement
PLUS the fossae the anatomy puts beside it, and on originals/male that is +8.25 mm
measured against a +4.58 mm displacement. That is the anatomy — a clavicle reads because
of the hollows around it — but it is not a licence to attribute the whole number to the
crest, so relief_field(include=...) exists and the validation harness reports the
crest-alone column beside the full one. Read them together.

WHAT THIS MODULE DOES NOT CLAIM. It does not claim the relief is anatomically correct in
shape — it claims each feature is placed on its bone (or on a declared construction), at a
declared amplitude, and that the result is or is not measurable by the SAME resolvers at
the SAME thresholds that measured its absence. Everything else is reported, not asserted.

DETERMINISM. mesh_skeletons._vert_sha hashes rest-cage vertices only, so this layer DOES
change the cage hash of any body that carries it and those bodies must be re-issued. The
field itself has no unordered reduction: the mirror pairing is a stable z-sort plus
np.argmin (lowest index wins ties), the geodesic distance is scipy dijkstra from a sorted
seed array, and everything after that is elementwise. MEASURED: `python -m zyg_workflows.geom.relief
determinism` builds the whole layer at 1 and at 8 torch threads and the delivered cage is
byte-identical (sha256 d3732479054cc8bd both ways on originals/male).

MEASURED RESULT, 2026-08-06, `python -m zyg_workflows.geom.relief measure` — the numbers this module is
allowed to claim, and the ones it is not.
  RESOLUTION, geom/form/ridge.py probe_pools over the 20 regions.REGION_SPEC probes, one
  null measured on the untouched anny neutral and used for BOTH columns:
      originals/male    1/20 -> 3/20   gained clavicle_shaft, epicondyle_med
      originals/female  2/20 -> 2/20   gained none
  Identical under the SHIPPED published cut (null=None). clavicle_shaft on the male goes
  flat/0 +6.70 mm at contrast 3.8 -> ridge/run 2 +8.25 mm at contrast 4.6. Nothing is lost
  on either body.
  MIRROR: displacement-field residual 0.000e+00 mm on both bodies (9.3e-06 mm BEFORE
  symmetrisation on the male, 2.4e-15 on the female — the mirror-by-construction is
  carrying it, the symmetriser is confirming it). The delivered cage's own mirror residual
  is unchanged by this layer: 0.0599 mm male, 0.0014 mm female, against
  integrity.SYM_MORPH_TOL_MM = 0.15.
  NEGATIVE CONTROL: the fibula shaft, the strip opposite the tibial facet, moves by
  0.000000000000 mm over 24/26 vertices on the two bodies.
  NOISE FLOOR: curvature.relief_null p99 on the delivered cage moves +0.11% (male) and
  +2.33% (female) — the layer is not judged against a floor it raised.

WHAT DOES NOT WORK, MEASURED, AND NOT FIXED BY MOVING A THRESHOLD.
  (a) SIX OF THE FIFTEEN AMPLITUDES CANNOT RESOLVE AT ANY PLACEMENT. After their
      conditionals, infraclavicular_fossa (0.62x), acromion (0.98x), ulnar_border (0.65x),
      iliac_crest (0.74x male / 1.00x female), psis (0.90x male / 0.53x female) and
      nuchal_furrow (0.82x) deliver LESS than the cage's own relief p99 of 2.45e-3 of
      stature. That is arithmetic, not placement: report['amplitude_audit'] states it
      before any probe runs. They are built anyway — they are real anatomy and they
      contribute to the depth and normal passes — but no predicate may read them as
      resolved.
  (b) THE CLAVICLE IS MARGINAL AND THE MUSCLE CONDITIONAL IS WHY. 3.0e-3 x 0.823 (both
      originals fitted to muscle ~0.94) = 2.475e-3 of stature, which clears the POINT-mode
      floor (2.45e-3) and is below the RIDGE-mode station floor measured this run
      (2.973e-3). The male clears only because the supraclavicular and infraclavicular
      fossae lie inside its collar; the female does not — its best station reads 5.16 mm
      at contrast 5.3 but only ONE station qualifies, so longest_run is 1 and the verdict
      stays point_only. To clear the ridge-mode floor at muscle 0.94 the base would have
      to be >= 3.61e-3 of stature, 20% above the figure this layer was given. That number
      is REPORTED, not adopted.
  (c) THE TIBIAL FACET DOES NOT FLATTEN MEASURABLY. planarity_ratio 0.04531 -> 0.04514
      (male), 0.04451 -> 0.04438 (female); facet_flatness already returns 'facet' BEFORE
      the layer runs. Two reasons, both measured: at the falloff radius this layer is
      allowed (13.9 mm), the strip is 28 mm wide and a 28 mm patch on a ~40 mm-radius
      shank departs from a plane by about 2.5 mm, so the ruled-plane fit has almost
      nothing to correct; and the target |curvature| <= 0.5e-3 of stature (1.08 1/m) is a
      statement about the LIMB (measured max |k| 78 1/m), not about a landmark, so no
      landmark-relief layer can reach it. Reaching that target requires reshaping the
      shank, which is a morph, not a sculpt layer.
  (d) PSIS IS A TESSELLATION LIMIT, NOT AN AMPLITUDE ONE. regions.py already records that
      the sacral window holds ~23 vertices; measured here it holds 5 on originals/male, so
      each dimple is ONE vertex and the pair cannot be separated at +/-0.020 of stature.
      The pits are placed and are visible in the field; the probe cannot see them and no
      threshold change recovers a feature the cage has no vertices to carry.
"""

# Pattern A package: relief.py was split at its own section banners into constants.py, primitives.py, anchors.py, layer.py, selftest.py.
# The import path is unchanged, the original top import block is re-done below so
# attribute access on the module keeps working, the submodules are imported in the
# original section order, and every public and underscore name is re-exported.

import sys

import numpy as np
import logging as _zyg_logging

from zyg_workflows.geom.relief.constants import (
    AMP,
    ANATOMY_KEY,
    ASPECT_MIN_DOT,
    CLAVICLE_N_STATIONS,
    CLAVICLE_S_AMPLITUDE_FRAC,
    CLAVICLE_S_CROSSING,
    CONDITIONALS,
    CREST_AZIMUTH_DEG,
    CREST_DROP_ANTERIOR_FRAC,
    CREST_DROP_POSTERIOR_FRAC,
    CREST_N_STATIONS,
    FACET_CAP_FRAC,
    FALLOFF_FRAC,
    MALLEOLUS_HEIGHT_OFFSET_FRAC,
    MALLEOLUS_LAT_POSTERIOR_FRAC,
    MIRROR_TOL_FRAC,
    NEWELL_MIRROR_MAX,
    NUCHAL_N_STATIONS,
    PERP_MAX_FRAC,
    PSIS_BELOW_CREST_FRAC,
    PSIS_HALF_SEPARATION_FRAC,
    SCHEMA,
    STATION_SPACING_FRAC,
    TIBIAL_FACET_CURVATURE_TARGET_FRAC,
    TISSUE_MAX_FRAC,
    TISSUE_MIN_FRAC,
    ULNAR_BORDER_N_STATIONS,
    _zyg_log,
    cond_asis,
    cond_clavicle,
    cond_infraclavicular,
    cond_none,
    cond_psis,
)
from zyg_workflows.geom.relief.primitives import (
    _check_falloff_inside_collar,
    bone_frame,
    bone_weights,
    bones_for,
    field_mirror_residual_m,
    mirror_map,
    newell_vertex_normals,
    symmetrise_field,
    verify_bone_frame,
)
from zyg_workflows.geom.relief.anchors import (
    _Ctx,
    _build_features,
    _clavicle_crest,
    _crest_points,
    _curve,
    _elbow_posterior,
    _falloff,
    _mirror_seeds,
    _pelvis_axis,
    _resample,
    _snap,
    _unit,
    _wrist_postero_ulnar,
)
from zyg_workflows.geom.relief.layer import (
    _facet_project,
    apply_relief,
    relief_field,
    relief_regions,
)
from zyg_workflows.geom.relief.selftest import (
    determinism_check,
    main,
    measure,
    self_test,
)

import sys as _sys
from types import ModuleType as _ModuleType

__all__ = [
    'sys',
    'np',
    '_zyg_logging',
    'AMP',
    'ANATOMY_KEY',
    'ASPECT_MIN_DOT',
    'CLAVICLE_N_STATIONS',
    'CLAVICLE_S_AMPLITUDE_FRAC',
    'CLAVICLE_S_CROSSING',
    'CONDITIONALS',
    'CREST_AZIMUTH_DEG',
    'CREST_DROP_ANTERIOR_FRAC',
    'CREST_DROP_POSTERIOR_FRAC',
    'CREST_N_STATIONS',
    'FACET_CAP_FRAC',
    'FALLOFF_FRAC',
    'MALLEOLUS_HEIGHT_OFFSET_FRAC',
    'MALLEOLUS_LAT_POSTERIOR_FRAC',
    'MIRROR_TOL_FRAC',
    'NEWELL_MIRROR_MAX',
    'NUCHAL_N_STATIONS',
    'PERP_MAX_FRAC',
    'PSIS_BELOW_CREST_FRAC',
    'PSIS_HALF_SEPARATION_FRAC',
    'SCHEMA',
    'STATION_SPACING_FRAC',
    'TIBIAL_FACET_CURVATURE_TARGET_FRAC',
    'TISSUE_MAX_FRAC',
    'TISSUE_MIN_FRAC',
    'ULNAR_BORDER_N_STATIONS',
    '_zyg_log',
    'cond_asis',
    'cond_clavicle',
    'cond_infraclavicular',
    'cond_none',
    'cond_psis',
    '_check_falloff_inside_collar',
    'bone_frame',
    'bone_weights',
    'bones_for',
    'field_mirror_residual_m',
    'mirror_map',
    'newell_vertex_normals',
    'symmetrise_field',
    'verify_bone_frame',
    '_Ctx',
    '_build_features',
    '_clavicle_crest',
    '_crest_points',
    '_curve',
    '_elbow_posterior',
    '_falloff',
    '_mirror_seeds',
    '_pelvis_axis',
    '_resample',
    '_snap',
    '_unit',
    '_wrist_postero_ulnar',
    '_facet_project',
    'apply_relief',
    'relief_field',
    'relief_regions',
    'determinism_check',
    'main',
    'measure',
    'self_test',
]

_SECTIONS = tuple(
    _sys.modules[__name__ + '.' + _n] for _n in ('constants', 'primitives', 'anchors', 'layer', 'selftest')
)


class _SplitModule(_ModuleType):
    """Keep `setattr(relief, name, value)` behaving as it did on the single module.

    Live code patches a name on this module and restores it afterwards (geom/
    relief_subdiv's mirror_map_override is one such patch), and the moved code resolves
    those names through its own section's globals — so a write here has to reach every
    section that holds the name, exactly as rebinding one module global used to.
    """

    def __setattr__(self, name, value):
        _ModuleType.__setattr__(self, name, value)
        for _m in self.__dict__.get('_SECTIONS') or ():
            if name in _m.__dict__:
                _ModuleType.__setattr__(_m, name, value)

    def __delattr__(self, name):
        _ModuleType.__delattr__(self, name)
        for _m in self.__dict__.get('_SECTIONS') or ():
            if name in _m.__dict__:
                _ModuleType.__delattr__(_m, name)


# Must be the last statement: from here on, every attribute write fans out.
_sys.modules[__name__].__class__ = _SplitModule
