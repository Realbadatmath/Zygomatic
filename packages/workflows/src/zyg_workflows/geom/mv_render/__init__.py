# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Control image sets for the multi-view-consistency (MVC) gate.

WHY THIS MODULE EXISTS
======================
The MVC gate asks a 48-cell generated contact sheet one question: can Structure-
from-Motion reconstruct a single rigid 3D object out of these 48 pictures? A bare
SfM number answers nothing on its own, because SfM fails for at least three reasons
that have NOTHING to do with 3D consistency:

  * too few repeatable texture features (SIFT finds nothing on smooth skin),
  * too little baseline overlap between neighbouring views,
  * a background that is either featureless or — worse — features that belong to a
    STATIC backdrop while the subject rotates, which is a contradictory motion field.

So the gate's number has to be bracketed. This module renders the brackets. It
produces three directories of .png files, and a directory of .png files is the ENTIRE
contract with the gate module — nothing else is shared, no imports, no schema.

  data/assets/mvconsist_controls/positive_textured/    48 x cell_NN.png   CEILING
  data/assets/mvconsist_controls/positive_untextured/  48 x cell_NN.png   feature floor
  data/assets/mvconsist_controls/negative_mixed/       48 x cell_NN.png   FLOOR

positive_textured is the real female cage (data/assets/mesh_skeletons/originals/
female/skeleton_female.glb, 13718 verts / 27420 tris, stature 1.6800 m) on a 48-step
turntable, 7.5 deg apart, wearing a high-frequency procedural surface texture. These
images ARE projections of one rigid object, so if SfM cannot reconstruct THEM, the
framing/resolution/overlap is what is broken, not the subject.

positive_untextured is the identical geometry through the identical cameras with a
plain matte grey material. Same object, same rigidity, no albedo features. The drop
from positive_textured to positive_untextured is the price of "no features"; the drop
from positive_untextured to negative_mixed is the price of "no object".

negative_mixed is 48 real generated cells taken 8 apiece from SIX DIFFERENT characters
at MATCHING angle indices, so the angular coverage AND the resolution mix of the set
are identical to a real sheet while the subject identity changes every frame. It is
definitively not one object. Any score at or below this is indistinguishable from
noise. The six are visually far apart — a 12-year-old boy, a red-haired white woman, a
dark-skinned woman, a short-haired figure, an East Asian woman, a Black woman with
curly hair — with different clothing and different backdrops, so this is a hard floor
and not a near-miss.


THE ONE THING THAT WOULD INVALIDATE THE POSITIVE CONTROL
========================================================
If the surface texture were pinned to the SCREEN rather than to the SURFACE, every
frame would carry the same pattern in the same pixels, SIFT would match everything to
everything, and the "ceiling" would be a fiction. The texture is driven from
Texture Coordinate -> Object, i.e. the object's own local space. Three checks, all
run at build time and all recorded in manifest.json under "texture_lock_verification":

  1. STRUCTURAL. The material node tree is walked and asserted to contain exactly one
     Texture Coordinate node from which only the 'Object' output socket is linked. Any
     link out of 'Window', 'Camera', 'Reflection' or 'Normal' aborts the build. A
     screen-space texture in Blender can only come from those sockets.

  2. TRANSLATION TEST (the discriminating one). Render azimuth 0. Then translate the
     OBJECT +0.030 m along world X with the camera, the lights and everything else
     untouched, and render again. Cross-correlate a crop taken well INSIDE the
     silhouette (so the moving silhouette edge contributes almost nothing and the
     correlation is decided by the texture itself) and find the integer x-shift that
     maximises NCC. A surface-locked texture must peak at the projected shift; a
     screen-locked texture must peak at 0 because the pattern would stay in place
     while only the shading moves. MEASURED on the delivered build: peak at +75 px,
     NCC 0.9276 there and -0.0316 at zero shift. That is unambiguous.

     THE PREDICTION IS A RANGE. 0.030 m at 2488.96 px/m gives 74.67 px, but that is the
     scale AT THE CAMERA TARGET PLANE and the correlated pixels are on the front of the
     torso, ~48 mm nearer the camera, where the same shift projects to ~78.1 px. A
     +/-3 px window centred on 74.67 therefore EXCLUDED the physically correct value
     and passed only because the NCC averages over a crop whose sides recede toward the
     plane — zero real margin, and a false abort waiting for the next re-centring. The
     build now derives the window from the depth span of the mesh actually inside the
     crop and ABORTS outside it +/- TRANSLATION_TOL_PX. A screen-locked pattern peaks at
     0 px, which is nowhere near either end.

  3. AZIMUTH-DECORRELATION TEST. Cross-correlate azimuth 0 against azimuth 180. A
     screen-locked texture would put the identical high-frequency pattern in both, so
     NCC would be near 1. MEASURED: best NCC over +/-80 px of shift is 0.0834. The
     build ABORTS above 0.5.

Nothing here is asserted that was not measured; the numbers above come from the last
build and are rewritten into manifest.json every run, so a stale docstring cannot lie
about a fresh build — trust the manifest first.


FRAMING — AND WHERE IT DIFFERS FROM THE REAL CELLS
==================================================
Real cells were measured, not guessed. Subject coverage (fraction of the frame that is
not background) over Abel's 48 cells (c3345deb5bde), measured with the in-repo
MediaPipe selfie_multiclass segmenter (data/assets/detectors, Apache-2.0):

    head-and-shoulders cells (n=26)   median coverage 0.508   (min 0.412 max 0.767)
    medium / upper body      (n=10)   median 0.498
    close-up face            (n= 3)   median 0.593
    FULL BODY                (n= 9)   median 0.258   (min 0.113 max 0.564)
    all 48                            median 0.489

and on cell_00 the top of the hair sits at y = 0.058 of frame height while the subject
runs off the bottom edge. So the modal real cell is a head-and-shoulders portrait at
~0.51 coverage, and the controls are framed to match THAT: head vertex at 0.058 H,
subject cropped by the bottom edge, frame height 0.2755 x stature = 0.4628 m, an
85 mm lens at 1.0928 m. ACHIEVED on the delivered controls: median coverage 0.4783
(min 0.4205, max 0.5339) over the 48 frames — 6 % under the real portraits in relative
terms, and deliberately not nudged closer, see D7.

These are the framing differences the measuring agent has to know about, because every
one of them is a confound:

  D1  THE REAL SET IS NOT ONE FRAMING. It is a mix: ~26 head-and-shoulders, 10 medium,
      3 close-ups and 9 FULL BODY (cells 24-29, 45-47) whose subject coverage is half
      that of the portraits. The scale jump between a portrait cell and a full-body
      cell is by itself a plausible SfM failure mode that has nothing to do with 3D
      consistency, and THESE CONTROLS DO NOT BRACKET IT. A uniform turntable cannot.
      If the real sheet scores low, re-run the gate on cells 0-23,30-44 only before
      concluding anything about geometry.
  D2  ANGULAR SAMPLING. The controls step a uniform 7.5 deg over a full 360 deg at a
      constant 0 deg elevation. The real cells are a hand-written prompt list: 0, +-20,
      +-35, +-45, +-60, +-90, +-120, 180 azimuth, elevations from -20 to +30 plus one
      directly overhead (cell 42). Coverage is comparable, spacing is not uniform, and
      several real azimuths are duplicated with different lighting or expression.
  D3  POSE. The controls are the cage in its rest pose for all 48 frames — genuinely
      rigid. Nine real cells are A-pose, three are T-pose, cell 22 is a walking pose,
      and expression varies (smile on 8,9,10,20). The real subject is therefore NOT
      rigid even when the generator is behaving perfectly. This is a real ceiling on
      the real sheet that the positive control does not model.
  D4  BACKGROUND. The controls sit on a flat, featureless dark background: the object
      is the only thing SfM can latch onto. The real cells have a mottled studio
      backdrop that is regenerated per cell — features that are neither static nor
      attached to the subject. That can only hurt, but it is not simulated here.
  D5  SUBJECT. The cage is nude, bald and has no facial detail; the real subject is a
      clothed boy with hair. The controls therefore have no hair/cloth deformation,
      which is a source of real non-rigidity, and no eyes/mouth, which are the
      strongest SIFT features on a real portrait.
  D6  LENS. The controls use a physically explicit 85 mm lens on a portrait-orientation
      36 mm sensor at 1.10 m. The real cells come from a diffusion model and have no
      declared or verified focal length; their perspective is only approximately
      consistent, and matching it exactly is not possible.
  D7  MEASUREMENT ASYMMETRY. Coverage on the real cells is from the segmenter (its own
      error); coverage on the controls is the exact background mask (the background is
      a known flat colour). The two numbers are comparable to a few percent, not more.
  D8  RESOLUTION. The controls are 1024x1152 for all 48 frames. A REAL SHEET IS NOT.
      Checked on all six characters and identical on all six: 39 cells at 1024x1152,
      cells 24-29 (the full-body A-pose block) at 832x1216, and cells 45-47 (the
      T-pose block) at 1024x1024 — three sizes and three aspect ratios in one set.
      negative_mixed reproduces that faithfully because it copies real cells; the two
      positive sets do not. This is not cosmetic: a reconstruction that shares one
      camera model across the folder is being handed images from three different
      "cameras", and the intrinsics it solves will be wrong for at least two of them.
      Decide per-image intrinsics, or gate on the 39 same-size cells, before reading
      anything into a real sheet's score.

A NOTE ON WHAT THE BRACKET LOOKS LIKE BEFORE ANY SfM RUNS. OpenCV SIFT at library
defaults, on every 6th image of each delivered set, found a median of 2549 keypoints
per frame on positive_textured, 45 on positive_untextured, and 784 on negative_mixed.
So the untextured control is a genuine feature famine (45 keypoints cannot support a
reconstruction no matter how rigid the object is), and the negative set is NOT
feature-starved — it fails, if it fails, for the right reason.


ENGINE
======
Cycles on CPU, 32 samples (CYCLES_SAMPLES), OpenImageDenoise on. EEVEE_NEXT was tried first and does
run headless here, but it emits EGL_BAD_MATCH on every frame and was SLOWER than
Cycles on this scene (10.5 s vs 4.3 s on the probe), so there was nothing to buy.
Denoising is not cosmetic: per-pixel sampling noise is high-frequency and view-
INCONSISTENT, so it manufactures SIFT features that cannot match across frames and
would depress the ceiling for a reason that has nothing to do with geometry.

Materials are fully diffuse (roughness 1.0, specular IOR level 0) and the four area
lights are fixed in WORLD space, not parented to the camera. World-fixed lighting
means brightness varies smoothly with azimuth, exactly as it does for a real turntable;
camera-parented lighting would have been a second, subtler way to cheat.


CLI
===
    python -m zyg_workflows.geom.mv_render --set all --out data/assets/mvconsist_controls

--set accepts all | positive_textured | positive_untextured | negative_mixed. The two
positive sets are rendered by re-invoking this same file inside Blender
(blender -b -noaudio --python geom/mv_render.py -- <config.json>); the file is written
so that the Blender side imports nothing from this repo, which is why it duplicates a
couple of small constants rather than reaching for geom.mesh_skeletons.


HOW A FAILED BUILD IS PREVENTED FROM LOOKING LIKE A SUCCESSFUL ONE
==================================================================
Every abort above is a RuntimeError raised inside Blender, and BLENDER EXITS 0 ON AN
UNCAUGHT PYTHON EXCEPTION. For one build that meant every guard in this file was
decorative: the screen-lock test could abort, print its traceback, and the outer layer
would report success — because its only success test was that manifest.json existed in the
output directory, and the manifest it found was the one the PREVIOUS good build had left
there, complete with `verdict: surface_locked`. A deliberate screen-locked regression was
demonstrated end to end doing exactly that. The same hole swallowed a missing input file, a
tripped orientation guard, and a partial render (48 frames requested, 30 written, 18 stale
ones left over, reported as a complete set).

Four things now have to be true before a set is published, and they are checked in this
order:
  1. the Blender worker exits NON-ZERO on any exception (`_bl_main` catches BaseException
     and calls os._exit(3); sys.exit does not survive Blender's own runner),
  2. it wrote WORKER_STATUS as its LAST act, which only a completed run reaches,
  3. exactly N_VIEWS cell_*.png are present, and the worker agrees on the count,
  4. a manifest exists.
The render goes into `<set>.staging` and is renamed over the published directory only after
all four pass; a failed build deletes the staging directory and raises, leaving whatever was
published before untouched and clearly labelled as not the output of this run. `main()` then
re-checks the cell count before writing anything into PROVENANCE.json.

PROVENANCE.json is MERGED, not rewritten: it accounts for a directory, and rebuilding one
set used to replace the record for all three with just that one.

--force IS REQUIRED TO REBUILD AN EXISTING SET. geom/mvconsist_band.py's thresholds are
measured on the exact images in these directories and Cycles is stochastic, so a rebuild
silently leaves the band describing pixels that no longer exist.
"""

# ruff: noqa: F401,E402  # re-export surface: every name the pre-split module defined

import argparse
import datetime
import glob
import json
import math
import os
import shutil
import subprocess
import sys
import tempfile
import logging as _zyg_logging

from zyg_workflows import paths

from zyg_workflows.geom.mv_render.constants import (
    _zyg_log,
    BLENDER,
    ROOT,
    FEMALE_GLB,
    OUT_H,
    OUT_W,
    N_VIEWS,
    AZIMUTH_STEP_DEG,
    ELEVATION_DEG,
    SENSOR_MM,
    LENS_MM,
    FRAME_H_PER_STATURE,
    HEAD_TOP_MARGIN,
    CYCLES_SAMPLES,
    TRANSLATION_TOL_PX,
    WORKER_STATUS,
    NEG_CHARS,
    CHAR_ROOT,
    SETS,
    _now,
)
from zyg_workflows.geom.mv_render.blender_scene import (
    _bl_orient,
    _bl_texture_material,
    _bl_grey_material,
    _SCREEN_SPACE_SOCKETS,
    _bl_assert_surface_locked,
    _bl_scene,
    _bl_place_camera,
)
from zyg_workflows.geom.mv_render.blender_verify import (
    _bl_render,
    _bl_read_rgb,
    _bl_gray,
    _bl_ncc_shift,
    _bl_verify_texture_lock,
    _bl_subject_mask,
    _bl_coverage,
)
from zyg_workflows.geom.mv_render.blender_main import _bl_main, _bl_main_inner
from zyg_workflows.geom.mv_render.outer import _blender_version, _render_positive, _build_negative, _PROVENANCE, main
