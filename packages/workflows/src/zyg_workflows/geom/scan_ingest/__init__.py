# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""PHOTOGRAMMETRY SCAN INGEST — photographs in, high-frequency displacement out.

WHY THIS EXISTS, AND WHAT IT REFUSES TO DO. We do not want proportions from a scan.
Proportions come from ANSUR II — 4,082 men and 1,986 women, 93 dimensions each, public
domain. A scan gives proportions from one person with no percentile behind them, and we
have already measured what fitting to a single body costs us: the current chamfer
reference scores crotch_height_over_stature at the 2nd percentile (cornelis p0.4, female
p1.5, male p2.7). One more single body does not fix that; taken as dimensional truth it
makes it worse.

What we want from a scan is DETAIL. Measured on the delivered originals, 0 of the 20 body
landmark probes in geom/form/regions.py resolve outside the cage's own relief null
(2.45e-3 of stature = 4.13 mm at S = 1.686 m, contrast floor 3.66). There is no clavicle,
no iliac crest, no trochanter, no PSIS, no cervicale; both malleoli measure flat
(-0.18 mm / +0.71 mm); the patella's +8.90 mm sits at contrast 3.06, below the floor.
Detail is far more forgiving than proportion, because a clavicle is a clavicle — it does
not need to be a statistically average clavicle. A 30 % amplitude error on a 6 mm ridge is
2 mm nobody sees. A 30 % error on crotch height is a different human being.

So stage (d) below throws the scan's proportions away BY CONSTRUCTION rather than by good
intentions: the cage is shrinkwrapped to the scan, the resulting displacement field is
low-passed, and only the DIFFERENCE is kept. Everything at or above the cutoff wavelength
— which is to say everything that is a proportion — is discarded before it can reach an
asset. See RESIDUAL_CUTOFF_FRAC for where the cutoff comes from; it is derived, not tuned,
and the achieved filter response is MEASURED on the actual mesh at run time rather than
asserted.

The capture half of this is docs/photogrammetry_capture.md. Read it first. Nearly every
failure of a single-camera human scan is baked in at capture time.


THE LOW-PASS IS SHALLOW — MEASURED, AND NOT YET GOOD ENOUGH
-----------------------------------------------------------
The separator in stage (d) is umbrella-Laplacian diffusion, and on this mesh it is a BROAD
filter, not a clean band split. Measured on the subdivided female cage (level 1, 54,848
verts, mean edge 4.62 mm, lambda_cut = 134.4 mm), sweeping the iteration count:

The "kept" columns are the MEASURED amplitude of the emitted residual, RMS(f - lowpass(f))
/ RMS(f). They are not `1 - lowpass_ratio`. This module used to report that algebraic
identity, which holds only if the low-pass returns a scalar multiple of its input; on an
irregular mesh it does not, and the identity understated proportion leakage by 1.86x. The
old column is shown beside the measurement so the size of the error is on the record.

    iters | response at cutoff | kept at 4x cutoff | kept at 0.25x cutoff | selectivity
          |                    | MEASURED  (1-r)   | MEASURED   (1-r)     | MEAS.  (1-r)
       60 |       0.840        |  0.072    0.030   |  0.724     0.489     | 10.0   16.5
      239 |       0.732        |  0.195    0.086   |  0.876     0.670     |  4.5    7.8
      600 |       0.658        |  0.322    0.150   |  0.935     0.744     |  2.9    5.0
     1200 |       0.600        |  0.423    0.209   |  0.956     0.784     |  2.3    3.8
     2969 |       0.509        |  0.549    0.295   |  0.971     0.831     |  1.8    2.8
     6000 |       0.422        |  0.632    0.368   |  0.981     0.864     |  1.6    2.4

There is NO iteration count at which long wavelength is rejected AND short wavelength is
passed. At the properly calibrated cutoff (response 0.5095 at 2,969 iterations, the -6 dB
convention), 54.9 % of a 537 mm feature — unambiguously a PROPORTION — survives into the
"detail" residual, while a 33.6 mm clavicle-scale feature is 97.1 % passed. True selectivity
is 1.77, not the 2.81 the algebraic column reads. The transition band is wider than the 16x
of wavelength this sweep covers, and it is wider than the first version of this docstring
claimed.

What this means honestly: the claim "proportions are discarded by construction" is
DIRECTIONALLY true and quantitatively weak — weaker than this module first reported. Long
wavelength is attenuated, not removed, and more than half of a 4x-cutoff feature comes
through. The report from stage 'residual' carries `proportion_leakage` — the measured
fraction of a 4x-cutoff feature that survives — and that number, not the intent in this
docstring, is what a caller must read before trusting a residual. Before this pipeline is
used on a real subject, the diffusion filter should be replaced with something with a
steeper roll-off (a spectral / Laplace-Beltrami-eigenbasis projection, or a geodesic-aware
kernel); at 55 % proportion leakage that is not an improvement, it is a prerequisite.
Nothing here should be tuned to hide this: the sweep above is the evidence, and the fix is
a better filter, not a friendlier threshold.

THE ITERATION COUNT SCALES WITH RESOLUTION, AND THE GUARD USED TO BIND. Required iterations
go as (lambda/h)^2. MEASURED, same body, same 134.4 mm cutoff, only the mesh changing:

    level | verts   | mean edge | analytic n | CALIBRATED n | response | prop. leakage
      1   |  54,848 |  4.62 mm  |     59     |     2,969    |  0.5095  |    0.549
      2   | 219,368 |  2.31 mm  |    239     |    11,922    |  0.5095  |    0.549

Level 2 is DEFAULT_SUBDIV_LEVEL — the level the CLI runs — and the old flat
LOWPASS_MAX_ITERS = 4000 clamped it at 4,000 iterations and a measured response of 0.6163,
while the stage went on reporting a 134.4 mm cutoff and a 0.1925 proportion leakage. That
0.1925 was not a better filter, it was an under-smoothed one: less is removed, so less shows
up as removed, and the honesty number moves in the flattering direction exactly where nobody
was checking. Converged, level 2 reads the same 0.549 as level 1, which is what it should —
the filter is defined by a physical wavelength and the mesh only sets how many steps it
takes to get there. The guard is now derived from the mesh (LOWPASS_ITER_GUARD_MULT: 47,800
at level 2) and a calibration that does not converge is REFUSED by stage_residual rather
than reported. The level-2 calibration costs 174 s.


WHAT ACTUALLY RUNS ON THIS MACHINE
----------------------------------
pycolmap 4.1.1 is installed, BSD-3-Clause, and reports has_cuda = False.

  * SPARSE SfM (SIFT extraction, matching, incremental mapping, bundle adjustment) runs
    on CPU. This works.
  * pycolmap.patch_match_stereo — COLMAP's real dense multi-view stereo — is CUDA-ONLY.
    It is not "slow without a GPU", it is not built. Calling it here raises. This module
    does NOT silently degrade: dense_method='patchmatch' raises ScanIngestError naming
    the missing capability, and the run report records dense.patchmatch_available=False
    on every run whatever method was chosen.
  * open3d and pymeshlab are NOT installed, so their Poisson / normal-estimation paths
    are unavailable. pycolmap.poisson_meshing IS available and is CPU — that is the
    surfacing path used here.

The best CPU densification available is therefore, in order of preference:

  1. 'sgbm'   — rectified two-view semi-global block matching (cv2.StereoSGBM) over image
                pairs selected from the SfM co-visibility graph, using the poses and
                intrinsics COLMAP solved. This is a genuine dense stereo path and it is
                what runs by default when cv2 is importable. It is WEAKER than
                patch-match: no photometric-consistency check across more than two views,
                no normal estimation in the matcher, no view-selection per pixel. Expect
                more outliers and more smoothing than a CUDA COLMAP run would give.
  2. 'sparse' — the triangulated SfM points only, filtered by track length and
                reprojection error. Thousands of points, not millions. Honest fallback,
                and enough to prove the plumbing; not enough to carry a clavicle ridge.

Both then get oriented normals and go through pycolmap.poisson_meshing. Poisson INVENTS
surface in unsupported regions by design; PoissonMeshingOptions.trim (default 10.0) is
what removes the least-supported of it. Invented surface is not measurement, and the
residual stage additionally refuses any cage vertex whose nearest scan sample is further
than SHRINKWRAP_SUPPORT_FRAC away, so unsupported regions contribute a coverage hole
rather than a fabricated ridge.


THE THING PHOTOGRAMMETRY CANNOT GIVE YOU: SCALE
-----------------------------------------------
Structure-from-motion reconstructs a scene up to an unknown SIMILARITY transform. A body
twice as large photographed from twice as far produces pixel-identical images. There is no
information in the photographs from which absolute size can be recovered.

This module therefore REQUIRES an explicit scale declaration and REFUSES to guess. It also
refuses the tempting shortcut of solving scale during the rigid alignment in stage (c):
that would launder our own cage's proportions into the "measured" scan and then read them
back out as if they had been observed. Alignment here is rotation and translation only.

A silently mis-scaled scan is the worst failure mode in the whole pipeline, because it is
invisible — the mesh looks perfect and every number downstream is wrong.


LICENCE / RIGHTS
----------------
A scan of a real person is that person's likeness. ingest() requires a `consent` record
and writes it into the output PROVENANCE.json in the same shape as
data/assets/anthro_reference/PROVENANCE.json and data/assets/detectors/PROVENANCE.json.
No consent record, no run. See docs/photogrammetry_capture.md §5.


STAGES — each independently runnable, each writing its own artefacts
--------------------------------------------------------------------
    a. 'sfm'      sparse reconstruction            -> sfm/ + 01_sfm.json
    b. 'scale'    apply the declared scale         -> 02_scale.json
    c. 'dense'    densify + surface                -> dense/ + 03_dense.json
    d. 'align'    rigid-align scan to our cage     -> 04_align.json
    e. 'residual' shrinkwrap, low-pass, KEEP THE DIFFERENCE
                                                   -> residual.npz + 05_residual.json
    f. 'emit'     offsets for geom/relief_subdiv   -> scan_residual.npz, PROVENANCE.json

A later stage reads the earlier stages' artefacts off disk, so a failure in 'residual'
does not cost the SfM run (which is the expensive one: CPU-only exhaustive SIFT matching
is O(n^2) in frames — 2,556 pairs at 72 images).

    python -m zyg_workflows.geom.scan_ingest --selftest        # synthetic end-to-end, no real person
    python -m zyg_workflows.geom.scan_ingest --photos DIR --character female --out DIR \\
        --scale-kind stature_m --scale-value 1.734 --consent consent.json
"""

import argparse
import glob
import json
import math
import os
import sys
import time

import numpy as np
import logging as _zyg_logging


from zyg_workflows.geom.scan_ingest.constants import (
    SCHEMA,
    STAGES,
    RESIDUAL_CUTOFF_FRAC,
    SCAN_BUTTERWORTH_ORDER,
    LOWPASS_ALPHA,
    LOWPASS_ITER_GUARD_MULT,
    LOWPASS_ITER_HARD_CAP,
    CALIBRATION_TOL,
    CALIBRATION_MAX_ROUNDS,
    DEFAULT_SUBDIV_LEVEL,
    SHRINKWRAP_SUPPORT_FRAC,
    SHRINKWRAP_MAX_FRAC,
    MIN_TRACK_LENGTH,
    MAX_REPROJ_ERROR_PX,
    NORMAL_KNN,
    SGBM_MIN_TRI_ANGLE_DEG,
    SGBM_MAX_TRI_ANGLE_DEG,
    SGBM_MIN_SHARED_POINTS,
    SGBM_MAX_PAIRS,
    SGBM_MAX_IMAGE_PX,
    DENSE_BBOX_MARGIN,
    SGBM_MIN_HORIZONTAL_BASELINE,
    SGBM_MAX_DISPARITY_PX,
    SGBM_RECTIFY_ALPHA,
    DENSE_MAX_POINTS,
    USE_POISSON_MESH_AS_SCAN,
    PERM_MATCH_TOL_M,
    VALID_SCALE_KINDS,
    CONSENT_REQUIRED_KEYS,
    CONSENT_MIN_FIELD_CHARS,
    SOFTWARE_LICENCES,
    ScanIngestError,
)

from zyg_workflows.geom.scan_ingest.helpers import (
    _log,
    _atomic_json,
    _jsonable,
    _read_json,
    _stage_path,
    _maybe_call,
    _quads_to_tris,
    _stature_of,
    _try_pycolmap,
    _try_cv2,
    _try_trimesh,
    _try_mvconsist,
    _target_cage,
)

from zyg_workflows.geom.scan_ingest.sfm import (
    stage_sfm,
)

from zyg_workflows.geom.scan_ingest.scale import (
    stage_scale,
)

from zyg_workflows.geom.scan_ingest.dense import (
    _camera_K_dist,
    _sgbm_pairs,
    _stereo_pair,
    _sgbm_densify,
    _estimate_normals,
    _write_ply,
    stage_dense,
)

from zyg_workflows.geom.scan_ingest.align import (
    _scan_points_m,
    _pca_frame,
    _icp,
    stage_align,
)

from zyg_workflows.geom.scan_ingest.residual import (
    _adjacency,
    _lowpass_iters,
    _iter_ceiling,
    _smooth,
    _rms0,
    _probe_response,
    _calibrate_lowpass,
    stage_residual,
)

from zyg_workflows.geom.scan_ingest.emit import (
    _validate_consent,
    _relief_subdiv_permutation,
    stage_emit,
)

from zyg_workflows.geom.scan_ingest.orchestration import (
    ingest,
    synthetic_capture,
    SYNTHETIC_CONSENT,
    _consent_gate_check,
    self_test,
    main,
)

_zyg_log = _zyg_logging.getLogger(__name__)


# ── re-export surface ────────────────────────────────────────────────────────
# This package is the pre-split scan_ingest.py seen from outside: the original top
# import block and every stage name are imported above and used by nobody IN this
# file, because callers read them off the package
# (from zyg_workflows.geom.scan_ingest import ingest, stage_sfm, …) exactly as
# they did before the split. Declaring them is what makes the re-export deliberate
# rather than an unused import; nothing does import * from here, so __all__
# changes no behaviour.
__all__ = [
    'argparse',
    'glob',
    'json',
    'math',
    'os',
    'sys',
    'time',
    'np',
    'SCHEMA',
    'STAGES',
    'RESIDUAL_CUTOFF_FRAC',
    'SCAN_BUTTERWORTH_ORDER',
    'LOWPASS_ALPHA',
    'LOWPASS_ITER_GUARD_MULT',
    'LOWPASS_ITER_HARD_CAP',
    'CALIBRATION_TOL',
    'CALIBRATION_MAX_ROUNDS',
    'DEFAULT_SUBDIV_LEVEL',
    'SHRINKWRAP_SUPPORT_FRAC',
    'SHRINKWRAP_MAX_FRAC',
    'MIN_TRACK_LENGTH',
    'MAX_REPROJ_ERROR_PX',
    'NORMAL_KNN',
    'SGBM_MIN_TRI_ANGLE_DEG',
    'SGBM_MAX_TRI_ANGLE_DEG',
    'SGBM_MIN_SHARED_POINTS',
    'SGBM_MAX_PAIRS',
    'SGBM_MAX_IMAGE_PX',
    'DENSE_BBOX_MARGIN',
    'SGBM_MIN_HORIZONTAL_BASELINE',
    'SGBM_MAX_DISPARITY_PX',
    'SGBM_RECTIFY_ALPHA',
    'DENSE_MAX_POINTS',
    'USE_POISSON_MESH_AS_SCAN',
    'PERM_MATCH_TOL_M',
    'VALID_SCALE_KINDS',
    'CONSENT_REQUIRED_KEYS',
    'CONSENT_MIN_FIELD_CHARS',
    'SOFTWARE_LICENCES',
    'ScanIngestError',
    '_log',
    '_atomic_json',
    '_jsonable',
    '_read_json',
    '_stage_path',
    '_maybe_call',
    '_quads_to_tris',
    '_stature_of',
    '_try_pycolmap',
    '_try_cv2',
    '_try_trimesh',
    '_try_mvconsist',
    '_target_cage',
    'stage_sfm',
    'stage_scale',
    '_camera_K_dist',
    '_sgbm_pairs',
    '_stereo_pair',
    '_sgbm_densify',
    '_estimate_normals',
    '_write_ply',
    'stage_dense',
    '_scan_points_m',
    '_pca_frame',
    '_icp',
    'stage_align',
    '_adjacency',
    '_lowpass_iters',
    '_iter_ceiling',
    '_smooth',
    '_rms0',
    '_probe_response',
    '_calibrate_lowpass',
    'stage_residual',
    '_validate_consent',
    '_relief_subdiv_permutation',
    'stage_emit',
    'ingest',
    'synthetic_capture',
    'SYNTHETIC_CONSENT',
    '_consent_gate_check',
    'self_test',
    'main',
]
