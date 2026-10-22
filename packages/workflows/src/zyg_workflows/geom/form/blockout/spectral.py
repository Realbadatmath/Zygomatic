# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

# This module carries the original top import block verbatim; the names it does not use
# itself are read THROUGH it by the siblings and by __init__.py, so they are declared
# re-exports in __all__ below rather than deleted.

"""The block-out ladder — does this body read as anatomy at every scale, or only at one?

WHY THIS MODULE EXISTS
Anatomy For Sculptors, Bridgman's Constructive Anatomy (1920) and every atelier since
teach a figure the same way: level 1 is a BLOCK-OUT of primitive volumes (the ribcage egg,
the pelvic box, the cranial ball), level 2 refines those into muscle masses, and only then
comes surface. A figure can be correct at one level and wrong at another, and the two
failures look nothing alike:

  LEVEL-1 ERROR — the primitive volume is the wrong volume. The historic case here is the
    male original at torso-muscle-pectoral-incr 1.5, which the operator rejected because it
    "looked like a bust". Every width was inside its ANSUR band. A metric gate has no
    predicate for "the chest volume is now a breast volume", because breadth and depth and
    circumference are all satisfied by both shapes.
  LEVEL-3 ERROR — the volumes and masses are right and there is NO SURFACE. That is "waxy
    skin": high-frequency relief has been smoothed away, so the body reads as a mannequin.
    Again no metric moves; a smoothed mesh measures the same as the mesh it came from, to
    well under a millimetre.

Both are invisible to geom.anthro, which is a METRIC layer, and both are invisible to a
single curvature number, which cannot say at what SCALE the surface went wrong. What
separates them is a band split: decompose the surface into the scales a sculptor works at
and ask which band carries how much. That is what this module computes.

HOW: MANIFOLD HARMONICS, NOT ITERATED SMOOTHING
The bands come from the generalised eigenproblem L phi = lambda M phi of the cotangent
Laplacian (Vallet & Levy 2008; Taubin 1995). Projecting positions onto the eigenvectors
below a cutoff gives the level-1 block-out DIRECTLY — a smooth, non-shrunken body.

The obvious alternative, implicit Laplacian smoothing at increasing timesteps, was tried
first and rejected on measured grounds, and the reason matters: implicit smoothing is
mean-curvature flow, so a cylinder of radius r moves inward by about t/r per step. A
timestep large enough to erase a torso-scale feature (sqrt(t) ~ 0.06 * stature = 0.11 m on
the male) displaces a 0.05 m-radius forearm by 0.25 m. It does not blur the arms into a
block-out, it DELETES them. Spectral projection has no such collapse: it is an orthogonal
projection, not a flow. Implicit smoothing survives in this module only as `smooth()`, at
timesteps small enough for the flow interpretation to be safe, and there it is used to
CONSTRUCT the waxy defect, not to measure it.

MEASURED COST, which is why the ladder stops where it does (RTX 4090 host, scipy
splu shift-invert, 13,348-vertex body shell): k=400 eigenpairs 7.9 s, k=600 16.3 s,
k=1500 116 s. k=1500 only reaches a feature wavelength of 0.042 * stature. Resolving true
skin-scale relief spectrally is therefore not affordable at any useful frame rate, and this
module does not pretend to: LOW and MID are spectral bands, and HIGH is the EXACT RESIDUAL
x - LOW - MID. Nothing is lost by that (the three bands still sum to x identically), but
HIGH is one bucket and cannot be sub-divided here. geom.form.curvature is the tool for
scales below HIGH's cutoff.

THE FOUR SHELLS. The cage is not one surface: measured, 13,348 v body + 226 v tongue +
2 x 72 v eyeball. A Laplacian over all four is block-diagonal, so a low-band reconstruction
gives each shell its OWN constant mode and collapses the eyeballs to points. Every number
and every render here is therefore computed on the BODY SHELL ALONE, and the excluded
shells are reported by name and vertex count rather than quietly dropped.

SCALE NORMALISATION, so a 1.52 m child and a 1.85 m adult are comparable. Eigenvalues carry
units of 1/m^2 and displacements carry metres, so neither is comparable across statures.
Everything published here is dimensionless: band cutoffs are quoted as lambda * stature^2
(equivalently, as a feature WAVELENGTH in fractions of stature), and every energy is an
M-weighted RMS displacement divided by stature, reported in MILLISTATURE (1 mstat = 0.001
of the subject's own height = 1.85 mm on the male original, 1.52 mm on abel). self_test()
proves the invariance by scaling a real character by 1.7 and re-measuring.

WHAT THIS MODULE DOES NOT DO. It ships no threshold and no gate. A form gate needs a
rejection rate against a reference sample of bodies our own pipeline accepts (the
Monte-Carlo morph-space sample under data/assets/form_reference/), and until that rate is
measured no number in here has earned the right to block anything. PREDICATES below names
the scalars a gate would band, and says so.
"""

import json
import os
import sys
import time

import numpy as np
import scipy.sparse as sp
import scipy.sparse.linalg as spl
from scipy.sparse.csgraph import connected_components

try:
    from zyg_workflows.geom.form import curvature as CV
except ImportError:  # pragma: no cover
    try:
        import curvature as CV  # running inside geom/form
    except ImportError as e:
        raise ImportError(
            'geom.form.blockout needs geom.form.curvature for the delivered '
            'triangulation, the cotangent weights and the mixed-Voronoi mass matrix. It '
            'could not be imported: %s. Nothing in this module reimplements them — one '
            'Laplacian for the whole form layer or the bands and the curvatures stop '
            'being comparable.' % e
        ) from e

__version__ = '1'

# Imports read through this module but not used here (energies: json/os; demos: os;
# the package __init__: json/os/sys). Everything else it exports is used here too.
__all__ = [
    'json',
    'os',
    'sys',
]

# ---------------------------------------------------------------------------------
# the ladder
# ---------------------------------------------------------------------------------
BANDS = ('low', 'mid', 'high', 'micro')

# Band boundaries as a FEATURE WAVELENGTH in fractions of stature. A Laplacian eigenvalue
# lambda corresponds to a plane wave of wavelength 2*pi/sqrt(lambda), so a cutoff quoted
# this way is a length a sculptor can argue about, and dividing by stature makes it the
# same argument on a child and on an adult.
#
# HOUSE, and deliberately round. 0.25 * stature is 0.46 m on the male original: the scale
# of the ribcage egg and the pelvic box, i.e. exactly the primitive volumes of a level-1
# block-out, and nothing smaller survives. 0.08 * stature is 0.148 m: the scale of a
# pectoralis, a deltoid, a gluteal mass — level 2. These are not measured thresholds and
# they are not tuned against any defect; they are a statement of which two scales the
# pedagogy names, and any predicate built on them still has to earn its own rejection rate.
WAVELENGTH_LOW_FRAC = 0.25
WAVELENGTH_MID_FRAC = 0.08

# lambda * stature^2 at those wavelengths — the dimensionless cutoffs actually used.
LAMBDA_LOW = (2.0 * np.pi / WAVELENGTH_LOW_FRAC) ** 2  # 631.65
LAMBDA_MID = (2.0 * np.pi / WAVELENGTH_MID_FRAC) ** 2  # 6168.50

# HIGH is split once more, and by a DIFFERENT operator, because the spectral route cannot
# reach skin scale at any affordable cost (see the module docstring: k=1500 costs 116 s and
# still only reaches 0.042 of stature). One implicit smoothing step at diffusion length
# MICRO_SIGMA_FRAC * stature is a legitimate low-pass at that scale — this is the regime
# where the mean-curvature-flow objection does NOT apply, because the displacement t/r is
# 0.27 mm on a 50 mm-radius forearm — and it costs one sparse LU. The split is exact:
# high = S(residual), micro = residual - S(residual), so the four bands still sum to x.
#
# HOUSE. 0.002 of stature is 3.7 mm on the male original and 3.0 mm on abel: the relief a
# viewer reads as skin and muscle striation rather than as a mass. Its half-power
# wavelength is 2*pi*sigma = 0.0126 of stature (23 mm on the male).
MICRO_SIGMA_FRAC = 0.002

BAND_MEANING = {
    'low': 'level-1 block-out: primitive volumes, features coarser than %.2f of stature' % WAVELENGTH_LOW_FRAC,
    'mid': 'level-2 masses: %.2f to %.2f of stature — muscle-group scale' % (WAVELENGTH_MID_FRAC, WAVELENGTH_LOW_FRAC),
    'high': 'coarse surface: about %.3f to %.2f of stature — the residual x - low - mid, '
    'low-passed by one implicit step at %.3f of stature'
    % (2 * np.pi * MICRO_SIGMA_FRAC, WAVELENGTH_MID_FRAC, MICRO_SIGMA_FRAC),
    'micro': 'skin-scale relief: finer than about %.3f of stature. The waxy band — and '
    'the only band computed by a LOCAL operator, so unlike low/mid it does not '
    'spread a localised change across the whole body' % (2 * np.pi * MICRO_SIGMA_FRAC),
}

# Weyl's law lambda_k ~ 4*pi*k/A gives the mode count needed to reach a cutoff; the margin
# covers the fact that Weyl is asymptotic and a body is not a disc. If the solved spectrum
# still stops short of LAMBDA_MID the basis GROWS and re-solves rather than silently
# banding on a truncated spectrum, because a MID band that is missing its top modes dumps
# them into HIGH and inflates exactly the number the waxy predicate reads.
EIGS_MARGIN = 1.35
EIGS_MIN_K = 64
EIGS_MAX_K = 1200
EIGS_GROWTH = 1.6
EIGS_SIGMA = -1e-6  # shift below the null eigenvalue; the cotan L is only PSD on
# a Delaunay mesh and this cage is not one, so sigma=0 can
# land on a genuinely tiny negative eigenvalue and fail.

# 1 millistature = 0.001 of the subject's own stature. Every energy in this module is in
# these units; the millimetre column beside it is a convenience, not the comparable number.
MSTAT = 1000.0


PREDICATES = (
    {
        'id': 'form.blockout.surface_band_energy',
        'stat': "energies['body']['high']['rms_mstat']",
        'direction': 'LOW is the defect — a collapsed HIGH band is waxy skin',
        'detects': 'surface detail smoothed away while every metric and every primitive volume is unchanged',
        'calibration': 'NONE SHIPPED. Needs the rejection rate of a candidate floor against '
        'the Monte-Carlo morph-space sample; until that is measured this '
        'scalar may be reported but may not gate.',
    },
    {
        'id': 'form.blockout.level1_delta',
        'stat': "delta_bands(...)['<region>']['low']['rms_mstat']",
        'direction': 'HIGH is the defect — the primitive volume moved',
        'detects': 'a level-1 error against a declared reference body: the block-out volume '
        'changed while breadths, depths and circumferences did not',
        'calibration': 'NONE SHIPPED. It is a two-body comparison, so its reference sample '
        'is pairs, not bodies: the rate would have to be measured over '
        'accepted-vs-accepted pairs from the Monte-Carlo sample.',
    },
    {
        'id': 'form.blockout.band_share',
        'stat': "energies['<region>']['<band>']['share']",
        'direction': 'either — a region whose energy has migrated between bands has changed '
        'level without changing size',
        'detects': 'mass redistributed across scales, e.g. a pectoral morph turning surface '
        'relief into a mid-scale volume',
        'calibration': 'NONE SHIPPED.',
    },
)


# ---------------------------------------------------------------------------------
# shells
# ---------------------------------------------------------------------------------
def shell_split(v, faces):
    """Connected components of the delivered triangulation, largest first.

    Returns a dict with 'body' (the largest component) and 'excluded' — every other shell
    with its vertex count and z-fraction span, so a caller can see WHICH shells the bands
    do not cover instead of discovering later that the eyeballs were silently included.
    """
    v = np.asarray(v, np.float64)
    tris = CV.delivered_triangles(faces)
    n = len(v)
    i = np.concatenate([tris[:, 0], tris[:, 1], tris[:, 2]])
    j = np.concatenate([tris[:, 1], tris[:, 2], tris[:, 0]])
    adj = sp.coo_matrix((np.ones(len(i)), (i, j)), shape=(n, n)).tocsr()
    ncomp, label = connected_components(adj, directed=False)
    sizes = np.bincount(label, minlength=ncomp)
    order = np.argsort(-sizes)
    body = int(order[0])

    zmin = float(v[:, 2].min())
    H = float(v[:, 2].max()) - zmin
    if H <= 0:
        raise ValueError('degenerate mesh: zero stature, so nothing can be normalised')

    excluded = []
    for c in order[1:]:
        m = label == c
        fz = (v[m, 2] - zmin) / H
        excluded.append(
            {
                'vertices': int(sizes[c]),
                'z_frac_span': [round(float(fz.min()), 4), round(float(fz.max()), 4)],
                'centroid_x_m': round(float(v[m, 0].mean()), 5),
            }
        )

    vid = np.nonzero(label == body)[0]
    keep = label[tris[:, 0]] == body
    remap = np.full(n, -1, np.int64)
    remap[vid] = np.arange(len(vid))
    return {
        'vid': vid,
        'tris': remap[tris[keep]],
        'label': label,
        'n_shells': int(ncomp),
        'body_vertices': int(sizes[body]),
        'excluded': excluded,
        'stature_m': H,
        'z_min_m': zmin,
    }


def _body_quads(faces, vid, n_vertices):
    """The cage quads whose four corners all lie on the body shell, reindexed.

    Quads are kept as quads: the renderer, the subdivision and the wireframe overlay in
    mesh_skeletons all work on the cage's quad grid, and handing them triangles would
    produce a preview that does not look like the previews it is meant to be compared to.
    """
    f = np.asarray(faces)
    remap = np.full(n_vertices, -1, np.int64)
    remap[vid] = np.arange(len(vid))
    keep = (remap[f] >= 0).all(axis=1)
    return remap[f[keep]], keep


# ---------------------------------------------------------------------------------
# spectral basis
# ---------------------------------------------------------------------------------
def spectral_basis(v, faces, k=None, lambda_max=LAMBDA_MID, name=None):
    """Manifold-harmonic basis of the BODY SHELL, enough of it to reach `lambda_max`.

    Returns a dict carrying the eigenvalues (raw and stature-normalised), the M-orthonormal
    eigenvectors, the mass vector, the shell split and the measured solve time. `k` forces
    a mode count instead of estimating one; the estimate is Weyl's law with EIGS_MARGIN and
    grows on demand.

    The mass matrix is geom.form.curvature.mixed_voronoi_area — Meyer's mixed area, which
    that module already guarantees strictly positive. A plain Voronoi lumping goes negative
    on obtuse triangles (1 in ~7 on this cage, measured there) and a negative mass makes
    this generalised eigenproblem indefinite, at which point the "smallest" eigenvalues are
    not the smooth ones and the whole ladder is upside down.
    """
    v = np.asarray(v, np.float64)
    shells = shell_split(v, faces)
    vid = shells['vid']
    H = shells['stature_m']

    t0 = time.time()
    W = CV.cotangent_weights(v, faces)[vid][:, vid].tocsr()
    mass_full = CV.mixed_voronoi_area(v, faces)
    m = mass_full[vid]
    L = (sp.diags(np.asarray(W.sum(axis=1)).ravel()) - W).tocsc()
    M = sp.diags(m).tocsc()
    t_assemble = time.time() - t0

    area = float(m.sum())
    if k is None:
        # Weyl: lambda_k ~ 4*pi*k/A, and lambda_max is quoted normalised, so the k that
        # reaches it is lambda_max * A / (4*pi*H^2).
        k = int(np.ceil(EIGS_MARGIN * lambda_max * area / (4.0 * np.pi * H * H)))
    k = int(np.clip(k, EIGS_MIN_K, EIGS_MAX_K))

    t0 = time.time()
    attempts = []
    while True:
        w, U = spl.eigsh(L, k=k, M=M, sigma=EIGS_SIGMA, which='LM')
        order = np.argsort(w)
        w, U = w[order], U[:, order]
        lam = w * H * H
        attempts.append({'k': int(k), 'lambda_max_reached': round(float(lam.max()), 1)})
        if lam.max() >= lambda_max or k >= EIGS_MAX_K:
            break
        k = min(EIGS_MAX_K, int(np.ceil(k * EIGS_GROWTH)))
    t_eigs = time.time() - t0

    if lam.max() < lambda_max:
        raise RuntimeError(
            'the basis stopped at lambda*stature^2 = %.0f but the MID/HIGH cutoff is '
            '%.0f, and EIGS_MAX_K=%d was reached. Banding here would put the top of the '
            'MID band into HIGH and inflate the surface-detail number this module exists '
            'to measure. Raise EIGS_MAX_K deliberately or decimate the mesh.' % (lam.max(), lambda_max, EIGS_MAX_K)
        )

    nulls = int((lam < 1e-6).sum())
    if nulls != 1:
        raise RuntimeError(
            'the body shell produced %d near-zero eigenvalues, not 1. A connected closed '
            'surface has exactly one constant mode; %d means shell_split handed the '
            'solver something disconnected and the low band would reconstruct each piece '
            'about its own centroid.' % (nulls, nulls)
        )

    t0 = time.time()
    micro_lu = spl.splu((M + (MICRO_SIGMA_FRAC * H) ** 2 * L).tocsc())
    t_lu = time.time() - t0

    return {
        'name': name,
        'w': w,
        'lambda_norm': lam,
        'U': U,
        'mass': m,
        'shells': shells,
        'stature_m': H,
        'area_m2': area,
        'k': int(len(w)),
        'sel': {'low': lam <= LAMBDA_LOW, 'mid': (lam > LAMBDA_LOW) & (lam <= LAMBDA_MID)},
        'micro_lu': micro_lu,
        'micro_sigma_frac': MICRO_SIGMA_FRAC,
        'timing_s': {'assemble': round(t_assemble, 3), 'eigsh': round(t_eigs, 3), 'micro_lu': round(t_lu, 3)},
        'attempts': attempts,
        'n_modes': {
            'low': int((lam <= LAMBDA_LOW).sum()),
            'mid': int(((lam > LAMBDA_LOW) & (lam <= LAMBDA_MID)).sum()),
        },
    }


def decompose(basis, v):
    """Split a position (or displacement) field into LOW + MID + HIGH. They sum to x
    exactly.

    `v` may be a full-cage array or one already restricted to the body shell. Decomposing
    a field that is not the basis's own mesh is not an abuse of the API, it is the point:
    an A/B comparison is only a band decomposition if both sides went through the same
    basis (see delta_bands).
    """
    U, m = basis['U'], basis['mass']
    v = np.asarray(v, np.float64)
    if len(v) == len(m):
        x = v
    elif len(v) == len(basis['shells']['label']):
        x = v[basis['shells']['vid']]
    else:
        raise ValueError(
            'field has %d rows; expected %d (body shell) or %d (full cage)'
            % (len(v), len(m), len(basis['shells']['label']))
        )
    y = U.T @ (m[:, None] * x)
    low = U[:, basis['sel']['low']] @ y[basis['sel']['low']]
    mid = U[:, basis['sel']['mid']] @ y[basis['sel']['mid']]
    rest = x - low - mid
    lu = basis['micro_lu']
    high = np.column_stack([lu.solve(m * rest[:, k]) for k in range(3)])
    micro = rest - high
    resid = float(np.abs(low + mid + high + micro - x).max())
    if resid > 1e-9:
        raise RuntimeError('band decomposition does not reconstruct: max residual %.3g m' % resid)
    return {'x': x, 'low': low, 'mid': mid, 'high': high, 'micro': micro}
