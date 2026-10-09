# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

# ruff: noqa: E402, F401
"""SEPARATING SURFACE DETAIL FROM PROPORTION — a replacement for the umbrella low-pass.

WHY THIS EXISTS. geom/scan_ingest.py's stage_residual has to answer one question about a
scanned surface: which part of it is PROPORTION (limb lengths, girths — things we already
know far better from ANSUR II's 4,082 people than from any one subject) and which part is
DETAIL (the clavicular crest, the malleoli — things no survey can give us). It answered it
with a low-pass filter, and MEASURED its own failure: at its calibrated cutoff, 29.5% of a
537 mm feature — unambiguously a proportion — survived into the "detail" residual, while a
33.6 mm clavicle-scale feature was only 83% passed. Selectivity 2.8.

THIS MODULE IS THE FIX, AND IT IS THREE SEPARATE FIXES BECAUSE THERE WERE THREE FAULTS.

    FAULT 1 — THE OPERATOR. scan_ingest builds its Laplacian with `A.data[:] = 1.0`: a
    uniform/combinatorial umbrella operator, degree-normalised, no edge lengths and no
    vertex areas anywhere in it. On an irregular mesh the diffusion rate is then set by
    CONNECTIVITY rather than by DISTANCE, so a dense-triangle region diffuses slowly in
    millimetres and a sparse one diffuses fast. The effective cutoff wavelength varies
    across the body, and the measured global response is an average over a SPREAD of local
    cutoffs. That smears the transition band, which is exactly the symptom.
      scan_ingest records this without naming it: its own docstring says the analytic
    iteration count left the cutoff at 0.847 amplitude instead of 0.5, "under-smoothed by
    a large factor". A filter whose cutoff is in the wrong place by that much is a filter
    whose cutoff is not in ONE place.
      FIXED HERE by cotan_operator(): the true discrete Laplace-Beltrami, cotangent edge
    weights against a barycentric mass matrix. Its eigenvalues carry physical units, so a
    wavelength means the same thing on the calf as on the cheek.

    FAULT 2 — THE FILTER FAMILY HAS NO STEEPNESS KNOB, AND THAT IS PROVABLE. One
    diffusion step multiplies a mode of wavelength L by mu = 1 - alpha*(1 - cos(2*pi*h/L)),
    so N steps give mu^N, and for L >> h that is exp(-c*N/L^2). Pin the cutoff at -6 dB
    and the NORMALISED response is

        H(L) = exp(-ln2 * (L_cut / L)^2)

    in which N does not appear. Iterating harder moves the cutoff along a curve whose SHAPE
    is mathematically fixed. There is no steepness parameter to tune — not a badly tuned
    one, an absent one. scan_ingest's own sweep is this curve being sampled at different
    offsets, which is why selectivity FELL from 16.3 to 2.3 as it iterated more.
      FIXED HERE by offering families that have the knob: taubin_lowpass() (two-parameter,
    where the pair count sets steepness independently of the cutoff) and cheby_filter()
    (arbitrary response shape at a stated transition width).

    FAULT 3 — FREQUENCY IS THE WRONG AXIS, and this is the one that matters most.
    scan_ingest derives its 0.08 S cutoff honestly: the shortest thing it is willing to
    call proportion is the upper arm at 0.18 S, the widest thing it is willing to call
    detail is the zygomatic arch at 0.05 S, and 0.08 S sits between them. But read those
    numbers again — the whole separation has to happen inside a factor of 3.6 in
    wavelength. No smooth filter has a transition band that narrow. The two things overlap
    in the domain the filter operates on, so the filter cannot win, and no amount of
    steepness makes 0.18 S and 0.05 S far apart.
      FIXED HERE by morph_residual(): we already own an exact separator that is not a
    frequency. anny's phenotype macros and local morphs SPAN, by construction, the space we
    call proportion. Fit the cage to the scan first and the residual carries no proportion,
    because the parameter space that produced the base can only express proportion. There
    is no transition band because there is no frequency axis.

WHAT IS MEASURED HERE, AND WHY THE OLD ACCEPTANCE TEST WAS TOO KIND. scan_ingest swept at
4x and 0.25x of its cutoff — a factor of 16 window. The REAL operating requirement is
narrower and harder: full rejection by 0.18 S and full passage by 0.05 S, a factor of 3.6.
sweep() therefore reports BOTH, and OPERATING_SELECTIVITY (the 3.6 window) is the number
that decides whether a separator is usable. Reporting only the 16x window would flatter
every filter here including the one being replaced.

For reference, worked from the transfer function above rather than measured: at the
operating edges the diffusion family's own THEORETICAL best is 12.8% proportion leaked and
83.0% detail passed, i.e. operating selectivity 6.5. That is the ceiling of the approach
scan_ingest chose, before any implementation loss. Its measured 2.8 (at the kinder 16x
window) is well under even that.

NOTHING HERE TUNES A THRESHOLD TO MAKE ANYTHING PASS. The band edges are scan_ingest's own
published anatomy — 0.18 S and 0.05 S — and every separator is measured against the same
sweep with the same probe. A separator that loses, loses in the report.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time

import numpy as np
from scipy.sparse import coo_matrix, diags
from scipy.sparse.linalg import LinearOperator
import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)

# The sections of the single file this package replaces, imported in the original
# section order so every module-level side effect still runs when it used to.
from zyg_workflows.geom.detail_filter import operators
from zyg_workflows.geom.detail_filter import filters
from zyg_workflows.geom.detail_filter import acceptance

# Every name the single module defined, re-bound here so no importer and no
# attribute access anywhere has to change.
from zyg_workflows.geom.detail_filter.operators import (
    CHEBY_DEGREE_MAX,
    CHEBY_DEGREE_MIN,
    CHEBY_DEGREE_SAFETY,
    COTAN_CLAMP,
    DETAIL_EDGE_FRAC,
    DetailFilterError,
    LEGACY_CUTOFF_FRAC,
    LEGACY_SWEEP_MULTIPLES,
    LMAX_ITERS,
    LMAX_MARGIN,
    LMAX_TOL,
    PROPORTION_EDGE_FRAC,
    SCHEMA,
    _cotan_from_tris,
    _quad_triangulations,
    cotan_operator,
    mean_edge_length,
    umbrella_operator,
)
from zyg_workflows.geom.detail_filter.filters import (
    _bw_factors,
    band_response,
    butterworth_keep,
    butterworth_lowpass,
    butterworth_response,
    cheby_apply,
    cheby_apply_torch,
    cheby_coeffs,
    cheby_degree_for,
    cheby_keep,
    cheby_keep_torch,
    clear_factor_cache,
    diffusion_iters_for,
    diffusion_keep,
    eig_from_wavelength,
    lambda_max,
    rayleigh_check,
    taubin_keep,
    taubin_stability,
    wavelength_from_eig,
)
from zyg_workflows.geom.detail_filter.acceptance import (
    NYQUIST_EDGES_PER_WAVE,
    PROBE_LIVE_FRAC,
    _jsonable,
    _probe_is_live,
    _probe_kept,
    main,
    morph_keep,
    probe_floor_m,
    sweep,
    transfer_curve,
)
