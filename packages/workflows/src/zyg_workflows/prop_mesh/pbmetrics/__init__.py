# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""pbmetrics.py — dense, null-validated image measurements for the Pufferball fit.

WHY THIS EXISTS. Three look-dev convergence runs (68 agents, ~10 h) closed on a critic
verdict of "zero majors / close" against a render the operator called far off at a glance.
Two causes, both structural:

  1. The severity rubric was `major = "different creature" or "obviously CG-flat"`. A coat
     of radial needles where the anchor has overlapping locks is still the same creature and
     is not flat, so it scored MINOR. "Zero majors" never meant "matches".
  2. The only dense number in the loop was a DINO embedding similarity. DINO gives 0.78 to
     the picture in question and 0.83 to a WORSE one, so at this fidelity it has no
     discriminating power at all. It is a coarse identity alarm, not a fit metric.

Phase 1 of that same work also died on FOUR harness terms that were artefacts (an Otsu matte
that cut a hole through the belly and inflated "solidity"; an amber "eye" gate that matched
warm-lit belly fur; anchor mattes closed-and-filled while render mattes were raw alpha).
The agents chased all four and the picture got worse while the score went up.

So this module has one rule, enforced in code, not in comments:

    NO METRIC IS USABLE UNTIL ITS NULL MODEL IS MEASURED.

`null_report()` runs every metric over pairs whose answer is known in advance — anchor vs
itself (must be ~perfect), anchor vs its own mirror (must be ~perfect for direction-free
terms), anchor vs the v1 sphere render (must be terrible) — and prints the dynamic range.
A metric that cannot separate those is not a metric, and `usable_terms()` will refuse to
include it in the composite loss. That refusal is the whole point of the file.

WHAT IT MEASURES, and why each term exists:

  matte / silhouette     the outline, at several blur scales. Multi-scale because BOTH
                         images are spiky — the question is spiky at WHICH scale.
  orientation field      structure-tensor direction + coherence of the fur. This is the
                         term the old harness never had, and the coat is the biggest
                         visible defect. Compared REGISTRATION-FREE, as deviation from the
                         radial direction, so it needs no correspondence between two
                         differently-shaped subjects.
  lock scale             characteristic cross-lock wavelength from the power spectrum,
                         normalised by subject width: "how many locks across the body".
                         Needles and shingles differ here by construction.
  framing                subject extent and ink coverage in frame. Measured, because the
                         current render is 25-29% short of the anchor and nothing in the
                         old loop looked at it.
  colour                 CIELAB medians inside the matte, and per-region when an index
                         pass is supplied.

DEPENDENCIES are numpy + scipy + PIL ONLY. Deliberately not cv2: geom/passes_io imports cv2
at module scope, the test venv does not carry it, and a test that skips itself when cv2 is
missing stops guarding the thing it exists for.

CONVENTIONS. Images are float64 RGB in [0,1] unless named `_u8`. Masks are bool. Angles for
orientation are DIRECTORS in [0, pi) — fur has no head or tail — so every comparison goes
through the double-angle representation and never through a raw angle difference.
"""

# The package re-exports the pre-split module namespace.

import math
import os
import sys

import numpy as np
from PIL import Image
from scipy import ndimage

from zyg_workflows.prop_mesh.pbmetrics import constants
from zyg_workflows.prop_mesh.pbmetrics import io_matte
from zyg_workflows.prop_mesh.pbmetrics import fields
from zyg_workflows.prop_mesh.pbmetrics import colour
from zyg_workflows.prop_mesh.pbmetrics import top_level

__all__ = [
    'load_rgb',
    'load_mask',
    'estimate_matte',
    'largest_component',
    'orientation_field',
    'radial_deviation_profile',
    'orientation_distance',
    'lock_scale',
    'silhouette_stats',
    'framing_stats',
    'lab_stats',
    'measure',
    'compare',
    'null_report',
    'usable_terms',
    # Inherited import block, re-exported so the pre-split namespace survives.
    'math',
    'os',
    'sys',
    'np',
    'Image',
    'ndimage',
    'constants',
    'io_matte',
    'fields',
    'colour',
    'top_level',
    'SIGMA_D',
    'SIGMA_I',
    'COHERENCE_FLOOR',
    'N_AZIMUTH_BINS',
    'LOCK_K_MIN',
    'LOCK_K_MAX',
    'SIL_SCALES',
    'BALD_TAU',
    'BALD_BLUR',
    'MATTE_DL',
    'MATTE_DC',
    'MATTE_EDGE_COLS',
    '_luma',
    '_chroma',
    '_backdrop',
    'find_horizon',
    '_cut_floor',
    '_radial_theta',
    '_srgb_to_lab',
    'plate_region',
    'surface_detail',
    'largest_smooth_patch',
    'measure_rgb',
    'dump_visuals',
    'TERMS',
    'perturb',
    'COAT_TERMS',
    'DIRECTION_MARGIN',
    'direction_report',
    '_raw',
    '_fmt',
    'main',
]

from zyg_workflows.prop_mesh.pbmetrics.constants import (
    SIGMA_D,
    SIGMA_I,
    COHERENCE_FLOOR,
    N_AZIMUTH_BINS,
    LOCK_K_MIN,
    LOCK_K_MAX,
    SIL_SCALES,
    BALD_TAU,
    BALD_BLUR,
    MATTE_DL,
    MATTE_DC,
    MATTE_EDGE_COLS,
)
from zyg_workflows.prop_mesh.pbmetrics.io_matte import (
    load_rgb,
    load_mask,
    _luma,
    _chroma,
    largest_component,
    _backdrop,
    find_horizon,
    _cut_floor,
    estimate_matte,
)
from zyg_workflows.prop_mesh.pbmetrics.fields import (
    orientation_field,
    _radial_theta,
    radial_deviation_profile,
    orientation_distance,
    lock_scale,
    silhouette_stats,
    framing_stats,
)
from zyg_workflows.prop_mesh.pbmetrics.colour import (
    _srgb_to_lab,
    plate_region,
    surface_detail,
    largest_smooth_patch,
    lab_stats,
)
from zyg_workflows.prop_mesh.pbmetrics.top_level import (
    measure_rgb,
    measure,
    dump_visuals,
    TERMS,
    compare,
    perturb,
    COAT_TERMS,
    DIRECTION_MARGIN,
    direction_report,
    usable_terms,
    null_report,
    _raw,
    _fmt,
    main,
)
