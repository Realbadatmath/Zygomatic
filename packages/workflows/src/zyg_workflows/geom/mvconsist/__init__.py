# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""mvconsist.py — MULTI-VIEW CONSISTENCY AS A GEOMETRIC MEASUREMENT, VIA STRUCTURE-FROM-MOTION.

WHY THIS EXISTS. Our 48-angle contact sheets are checked for identity consistency by a VLM
judge. That judge is subjective and it is promptable: it answers a question we phrased, and
a differently-phrased question gets a different answer. It cannot tell you whether the 48
images are pictures OF THE SAME PHYSICAL THING, because it never forms a physical model.

Structure-from-Motion can. Photogrammetry converges only when the images it is given are
projections of one rigid 3D object through one moving camera. Feed it 48 renders of a mesh
and it recovers the mesh and the orbit. Feed it 48 INDEPENDENT diffusion samples and it has
nothing to converge on: every sample is a slightly different body, so the epipolar geometry
that has to hold across every pair does not hold, and the reconstruction either refuses to
grow or shatters into pieces that disagree with each other.

That refusal is the measurement. It is objective, it is geometric, and there is no prompt
to phrase.

WHAT THIS MODULE DOES AND DOES NOT DO
-------------------------------------
It MEASURES. It contains NO THRESHOLD and returns NO PASS/FAIL. Verdicts live in verdict(),
which will not run unless the caller hands it a band, and the band is expected to come from
a CONTROL SET — renders of one real mesh — never from the images being judged. Tuning a
band until our own sheets pass would convert this file from an instrument into a rubber
stamp, and the whole reason to build it was that we already have one of those.

READ `status` CAREFULLY. `status == 'ok'` means THE MEASUREMENT RAN, not that the image set
is consistent. The real 48-cell Abel sheet returns status='ok' with 12 of 48 cameras
registered across 3 mutually disagreeing models — a successful measurement of a bad result.
Anything that reads `status` as a verdict has misread it. The verdict field is produced by
verdict(), and it is called `verdict`.

THE CONTRACT
------------
An image set is A DIRECTORY OF .png FILES. Nothing else is shared — no camera poses, no
intrinsics, no ordering, no metadata. Both the real sheets and the control renders must
arrive the same way or the comparison is not a comparison.

    measure(image_dir, work_dir=None, *, seed=0, max_image_size=1600, ...) -> dict

WHAT WE MEASURED BUILDING IT (2026-08-07, pycolmap 4.1.1 / COLMAP 4.1.1, CPU SIFT, no CUDA)
------------------------------------------------------------------------------------------
Two 48-image sets, delivered through the identical contract, measured with the identical
settings (quality='high', camera_grouping='per_resolution', seed=0):

  CONTROL — 48 Blender EEVEE orbit renders at 1024x1152 of ONE mesh
  (mesh_skeletons/originals/female/skeleton_female.glb, procedural noise texture, lights
  fixed in world space, elevation modulated so the orbit carries real parallax). This is a
  throwaway sanity control built to prove the instrument can register a set at all; the
  delivered control renderer is a separate piece of work:
      48/48 registered in ONE model, 9189 points, reproj 0.506 px, MEAN TRACK LENGTH 6.43,
      1687 SIFT features per image, 593 of 1128 pairs verified with parallax,
      48 of 48 images connected to something. 51 s.

  REAL — the Abel c3345deb5bde contact sheet, cell_00..cell_47:
      10-12 of 48 registered (see the spread below), 2-3 models, reproj 0.86-1.05 px,
      MEAN TRACK LENGTH 4.21-4.62, 6039 SIFT features per image, 236 of 1128 pairs
      verified with parallax, 44 of 48 images connected to something. 134 s.

The real sheet carries THREE AND A HALF TIMES the SIFT texture of the control and registers
a quarter of the cameras, into three models that do not agree with each other. That disposes
of the one benign explanation — the images are not featureless, they are richly detailed and
they disagree. This is why n_features_mean is in the return: it is what separates "nothing
to match" from "plenty to match, no 3D object behind it".

Do not over-read the pair of numbers as a calibrated ratio. The two sets are not strictly
comparable and the module says so in result['notes']: the control is one resolution and one
true orbit, whereas the Abel sheet turns out to contain THREE resolutions and includes
close-up crops, which is a different and in some ways easier problem. The comparison
establishes that the instrument works and that the real sheet is far from converging. It
does not establish a band. A band needs controls built through this same contract.

FOUR TRAPS, AND WHAT THIS FILE DOES ABOUT EACH
----------------------------------------------
1. A GATE THAT CANNOT MEASURE MUST SAY SO. If pycolmap is absent, or the directory is empty,
   or SfM throws, this returns status='error' with a reason. It never returns a number that
   could be mistaken for a pass. There is no silent fallback, no default, no zero-filled
   result. The one thing worse than a failing gate is a gate that reports success when it
   did not run.

2. n_models > 1 IS NOT PURELY AN INCONSISTENCY SIGNAL, AND WE MEASURED THIS THE HARD WAY.
   A full 360-degree orbit of an OPAQUE object splits naturally: front-facing views and
   back-facing views share no surface, so there is nothing to match across the seam. An
   early, under-textured version of the control (270 features/image) split into 3 models of
   2/22/21 images for exactly that reason, with no inconsistency present at all — it was one
   mesh. Adding texture closed the seam and it became one model of 48. So a split means
   "these views did not connect", which occlusion can cause on its own. Report it, weight it
   with the track length, do not read it alone.

3. SfM IS STOCHASTIC AND WE DO NOT GET TO PRETEND OTHERWISE. Every seed pycolmap exposes is
   set: the global RNG, IncrementalPipelineOptions.random_seed, the mapper's own
   random_seed, and the RANSAC seed inside geometric verification. What remains uncontrolled
   is recorded in result['nondeterminism'] rather than hidden — chiefly thread count,
   because feature extraction, brute-force matching and Ceres bundle adjustment all run
   multi-threaded and neither pycolmap nor COLMAP exposes a seed for the order in which
   threads finish. That is not a theoretical worry; SETTING EVERY SEED IS NOT ENOUGH, and
   repeated runs of the same directory with the same seed are NOT bit-identical.

   MEASURED SPREAD, same seed=0, same settings, repeated runs (this is the RESOLUTION LIMIT
   OF THE GATE — a difference smaller than the relevant row below is not a difference):

                            CONTROL (3 runs, converges)   ABEL (5 runs, does not converge)
     n_features_mean        1687.2  range 0.0             6038.7  range 0.0
     n_verified_matches     177343-177585  range 242      41614-41775  range 161
     n_registered           48  range 0                   10-12   range 2
     registration_rate      1.0  range 0.0                0.208-0.250  range 0.042
     n_models               1  range 0                    2-3  range 1
     mean_track_length      6.421-6.445  range 0.025      4.212-4.616  range 0.404
     mean_reproj_error_px   0.5048-0.5078  range 0.0030   0.861-1.046  range 0.185
     n_points3D             9174-9223  range 49 (0.5%)    427-2081  range 1654 (4.9x)

   THREE THINGS FOLLOW, AND THEY SHAPE HOW A BAND SHOULD BE BUILT.
     (a) The instrument is deterministic up to the mapper. n_features_mean is bit-identical
         across every run of both sets, and matching wobbles by 0.1-0.3%. ALL the instability
         enters in incremental mapping.
     (b) THE SPREAD IS REGIME-DEPENDENT. On a set that genuinely reconstructs, the answer is
         nearly exact (registration_rate range 0.0, reproj range 0.003 px). On a set that
         does not, the mapper is choosing between roughly equally bad initialisations and the
         result moves. So the gate is sharp exactly where it needs to be — near the
         pass/fail boundary a set either connects or it does not — and vague only in the
         region that is already far from passing.
     (c) DO NOT BAND ON n_points3D. On the failing set it varied by a factor of 4.9 between
         identical runs. registration_rate and mean_track_length are the stable, meaningful
         quantities; n_points3D is reported for diagnosis, not for judgement.

   stability() computes all of this for any set; run it before trusting a new band.

4. A STALE RECONSTRUCTION WOULD SILENTLY FAKE A RESULT. Nothing is cached, ever. Each
   measure() builds a fresh uuid-named working directory, writes a fresh database into it,
   and deletes the whole thing in a finally block. Passing work_dir does not change this: it
   only chooses the PARENT the fresh directory is made under. The image directory is never
   written to — the images are symlinked in, never copied out, never modified.

WHY CPU-ONLY IS FINE HERE. pycolmap.has_cuda is False in this environment, so dense
patch-match stereo is unavailable. We do not want it. Dense stereo produces a surface; we
only need to know whether a SPARSE reconstruction converges, which is the sharper question
anyway. Measured wall clock for 48 images at 1024x1152, quality='high': 51 s on the control,
134 s on the Abel sheet. The budget is 180 s and the Abel figure is uncomfortably close to
it — a set much larger than 48 images, or one with more texture, WILL exceed it. Exhaustive
matching is O(n^2) pairs and each pair is brute-forced on CPU. If that becomes a problem the
honest lever is quality='default' (7.8 s on the control) applied to EVERY set in the
comparison, not to the slow one only.

WHY quality='high' IS THE DEFAULT. It removes an objection: with estimate_affine_shape,
domain_size_pooling and guided matching enabled we cannot be accused of having starved the
reconstruction into failing.

MEASURED ON THE 48-CELL ABEL SHEET (c3345deb5bde), 2 repeats each, everything else held —
seed=0, camera_grouping='per_resolution', max_image_size=1600:

                        quality='default'      quality='high'
  n_features_mean       3065.2                 6038.7
  n_verified_pairs      190                    248
  n_registered of 48    2 and 10               10 and 11
  mean_track_length     2.00 and 4.48          4.4396 and 4.4573

Doubling the feature budget did not rescue the reconstruction: the sheet registers about a
fifth of its cameras either way. The failure is not a compute artefact.

THE FIGURES 6361.5 / 181 BELONG TO THE 39-CELL SUBSET, NOT TO THIS SHEET. An earlier version
of this paragraph quoted them as the 48-cell numbers, which contradicted line 102 of this
same docstring and every artefact on disk (6038.7 and 248) — they are the same sheet reduced
to its 39 same-resolution cells. Fewer, larger-average cells carry more features per image
and fewer verified pairs. Both sets of runs are on disk under
data/assets/anthro_reports/mvconsist/{all48,subset39}/; the quality='default' pair is
c3345deb5bde.quality_default.r{0,1}.json.

A caller comparing sets MUST hold quality fixed across them; it is recorded in the result so
a mismatched comparison is detectable after the fact.
"""

from zyg_workflows.geom.mvconsist.constants import (
    annotations,
    _glob,
    json,
    math,
    os,
    shutil,
    statistics,
    sys,
    time,
    uuid,
    Any,
    Dict,
    List,
    Optional,
    Sequence,
    _zyg_logging,
    _zyg_log,
    __all__,
    DEFAULT_GLOB,
    DEFAULT_MAX_IMAGE_SIZE,
    QUALITY_PRESETS,
    CAMERA_GROUPINGS,
    _CONFIG_WITH_PARALLAX,
    _CONFIG_NAMES,
    _MIN_CAMERAS_FOR_TRIANGULATION,
    _MIN_POINTS_FOR_STATISTICS,
    MVConsistError,
    _import_pycolmap,
    _quiet,
)
from zyg_workflows.geom.mvconsist.sfm import (
    _default_scratch_root,
    _stage_images,
    _read_sizes,
    _seed_everything,
    _nondeterminism_notes,
    measure,
    _run_sfm,
    _classify,
    _scale_applied,
    _error_result,
)
from zyg_workflows.geom.mvconsist.verdicts import (
    stability,
    verdict,
    _main,
)

# ── re-export surface ────────────────────────────────────────────────────────
# This package is the pre-split mvconsist.py seen from outside: every name above is
# imported here and used by nobody IN this file, because callers read them off the
# package (``from zyg_workflows.geom.mvconsist import measure, verdict, …``) exactly
# as they did before the split. ``__all__`` itself comes from constants.py (the
# original module's own list, which named measure/stability/verdict); extending it
# here is what makes the re-export deliberate rather than an unused import. Nothing
# does ``import *`` from this package, so __all__ changes no behaviour.
__all__ = __all__ + [
    'annotations',
    '_glob',
    'json',
    'math',
    'os',
    'shutil',
    'statistics',
    'sys',
    'time',
    'uuid',
    'Any',
    'Dict',
    'List',
    'Optional',
    'Sequence',
    '_zyg_logging',
    '_zyg_log',
    'DEFAULT_GLOB',
    'DEFAULT_MAX_IMAGE_SIZE',
    'QUALITY_PRESETS',
    'CAMERA_GROUPINGS',
    '_CONFIG_WITH_PARALLAX',
    '_CONFIG_NAMES',
    '_MIN_CAMERAS_FOR_TRIANGULATION',
    '_MIN_POINTS_FOR_STATISTICS',
    'MVConsistError',
    '_import_pycolmap',
    '_quiet',
    '_default_scratch_root',
    '_stage_images',
    '_read_sizes',
    '_seed_everything',
    '_nondeterminism_notes',
    'measure',
    '_run_sfm',
    '_classify',
    '_scale_applied',
    '_error_result',
    'stability',
    'verdict',
    '_main',
]
