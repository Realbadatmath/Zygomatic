# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Load-bearing constants, the error type and the mesh operators.

Verbatim from the single-file geom/detail_filter.py: lines 95-327 — SCHEMA, the
LOAD-BEARING CONSTANTS block, DetailFilterError and the MESH OPERATORS section.
"""

from __future__ import annotations

import numpy as np
from scipy.sparse import coo_matrix, diags
from scipy.sparse.linalg import LinearOperator


SCHEMA = 'geom.detail_filter/1'


# ----------------------------------------------------------------------------------
# LOAD-BEARING CONSTANTS
# ----------------------------------------------------------------------------------
#
# THE BAND EDGES ARE NOT OURS. They are geom/scan_ingest.py's published derivation, quoted
# so this module can be checked against it:
#
#   "UPPER BOUND -- the shortest thing we are willing to call a PROPORTION. The shortest
#    segment in the ANSUR chain we actually gate on is the upper arm (acromion-to-radiale),
#    ~0.18 of stature [...] A displacement feature whose wavelength is comparable to a
#    segment length IS a proportion change, and must not survive."
#
#   "LOWER BOUND -- the widest thing we are willing to call DETAIL. The bony relief
#    features this pipeline exists to recover are, at their widest, the zygomatic arch and
#    the clavicular crest: both under 0.05 S across."
#
# Everything this module reports is scored against those two numbers. Moving either of them
# to make a filter look better would be moving the anatomy to fit the instrument.
PROPORTION_EDGE_FRAC = 0.18  # reject completely at and above this wavelength
DETAIL_EDGE_FRAC = 0.05  # pass completely at and below this wavelength
LEGACY_CUTOFF_FRAC = 0.08  # scan_ingest.RESIDUAL_CUTOFF_FRAC, kept for comparison

# The kind window scan_ingest scored itself in (4x / 0.25x of the cutoff). Reported so the
# old and new numbers can be put side by side, NOT used to decide anything.
LEGACY_SWEEP_MULTIPLES = (4.0, 0.25)

# Cotangent weights go negative on obtuse triangles. Left alone they can make the operator
# indefinite and the polynomial filters diverge. Clamping to zero is the standard remedy;
# the count of clamped edges is REPORTED, because a mesh that needs a lot of clamping is a
# mesh whose operator is not trustworthy and that is a finding, not a detail.
COTAN_CLAMP = True

# Chebyshev degree is chosen from the spectrum, not picked: the transition band occupies a
# fraction of [0, lambda_max] and the degree has to resolve it. See cheby_degree_for().
CHEBY_DEGREE_SAFETY = 2.5
CHEBY_DEGREE_MIN = 32
CHEBY_DEGREE_MAX = 3000

# Power-iteration settings for the spectral bound.
LMAX_ITERS = 200
LMAX_TOL = 1e-6
LMAX_MARGIN = 1.02  # a Chebyshev domain that is slightly too big is safe;
# one that is too small is not (the recurrence blows up).


class DetailFilterError(RuntimeError):
    pass


# ----------------------------------------------------------------------------------
# MESH OPERATORS
# ----------------------------------------------------------------------------------


def _quad_triangulations(faces):
    """Both diagonal splits of a quad mesh, as two triangle arrays.

    A quad has two diagonals and picking one biases the operator along it: the cotan
    weights of the chosen diagonal appear, the other's do not. On a Catmull-Clark surface
    every face is a quad and the bias is therefore global and aligned with the parameter
    directions, which would show up in the sweep as direction-dependent attenuation --
    the same class of artefact as FAULT 1, just anisotropic instead of inhomogeneous.
    Averaging the two operators restores the symmetry. Triangle input is passed through.
    """
    faces = np.asarray(faces, np.int64)
    if faces.ndim != 2:
        raise DetailFilterError('faces must be (F, k)')
    if faces.shape[1] == 3:
        return [faces]
    if faces.shape[1] != 4:
        raise DetailFilterError('only tri or quad faces are supported, got k=%d' % faces.shape[1])
    a, b, c, d = faces[:, 0], faces[:, 1], faces[:, 2], faces[:, 3]
    t1 = np.concatenate([np.stack([a, b, c], 1), np.stack([a, c, d], 1)], 0)
    t2 = np.concatenate([np.stack([a, b, d], 1), np.stack([b, c, d], 1)], 0)
    return [t1, t2]


def _cotan_from_tris(v, tris, nv, clamp=COTAN_CLAMP):
    """Stiffness matrix K and barycentric mass diagonal M for one triangulation."""
    p0 = v[tris[:, 0]]
    p1 = v[tris[:, 1]]
    p2 = v[tris[:, 2]]

    e0 = p2 - p1  # opposite vertex 0
    e1 = p0 - p2  # opposite vertex 1
    e2 = p1 - p0  # opposite vertex 2

    cr = np.cross(e2, -e1)
    dbl_area = np.linalg.norm(cr, axis=1)
    degenerate = int(np.count_nonzero(dbl_area < 1e-14))
    dbl_area = np.maximum(dbl_area, 1e-14)

    # cot at vertex i = dot(adjacent edges) / (2 * area) = dot / |cross|
    cot0 = np.einsum('ij,ij->i', -e1, e2) / dbl_area
    cot1 = np.einsum('ij,ij->i', -e2, e0) / dbl_area
    cot2 = np.einsum('ij,ij->i', -e0, e1) / dbl_area

    n_neg = int(np.count_nonzero(cot0 < 0) + np.count_nonzero(cot1 < 0) + np.count_nonzero(cot2 < 0))
    if clamp:
        cot0 = np.maximum(cot0, 0.0)
        cot1 = np.maximum(cot1, 0.0)
        cot2 = np.maximum(cot2, 0.0)

    # edge (j,k) opposite vertex i carries weight cot_i / 2
    I = np.concatenate([tris[:, 1], tris[:, 2], tris[:, 2], tris[:, 0], tris[:, 0], tris[:, 1]])
    J = np.concatenate([tris[:, 2], tris[:, 1], tris[:, 0], tris[:, 2], tris[:, 1], tris[:, 0]])
    W = 0.5 * np.concatenate([cot0, cot0, cot1, cot1, cot2, cot2])

    Wm = coo_matrix((W, (I, J)), shape=(nv, nv)).tocsr()
    Wm = 0.5 * (Wm + Wm.T)  # exact symmetry, kills float asymmetry
    deg = np.asarray(Wm.sum(axis=1)).ravel()
    K = diags(deg) - Wm

    area = 0.5 * dbl_area
    M = np.zeros(nv, np.float64)
    np.add.at(M, tris[:, 0], area / 3.0)
    np.add.at(M, tris[:, 1], area / 3.0)
    np.add.at(M, tris[:, 2], area / 3.0)

    return K, M, {'n_negative_cotan': n_neg, 'n_degenerate_tris': degenerate, 'n_tris': int(tris.shape[0])}


def cotan_operator(v, faces, clamp=COTAN_CLAMP):
    """The discrete Laplace-Beltrami operator, as the pieces the filters need.

    Returns a dict with:
        K        (nv, nv) csr, symmetric PSD stiffness
        M        (nv,)    barycentric vertex areas, strictly positive
        Lsym     LinearOperator for M^-1/2 K M^-1/2 -- symmetric, same spectrum as M^-1 K
        stats    clamping / degeneracy counts

    The spectrum of M^-1 K is the physical one: a plane wave of wavelength L sits near
    (2*pi/L)^2, which is what makes eig_from_wavelength() meaningful. That relation is not
    assumed -- rayleigh_check() measures it on the actual mesh.
    """
    v = np.ascontiguousarray(np.asarray(v, np.float64))
    nv = int(v.shape[0])
    tri_sets = _quad_triangulations(faces)

    Ks, Ms, stats = [], [], []
    for t in tri_sets:
        K, M, st = _cotan_from_tris(v, t, nv, clamp=clamp)
        Ks.append(K)
        Ms.append(M)
        stats.append(st)

    K = Ks[0] if len(Ks) == 1 else (sum(Ks) / float(len(Ks))).tocsr()
    M = Ms[0] if len(Ms) == 1 else (sum(Ms) / float(len(Ms)))

    n_iso = int(np.count_nonzero(M <= 0.0))
    if n_iso:
        # An isolated vertex has no area and would divide by zero. It also cannot carry a
        # wavelength, so the honest handling is to give it the smallest real area on the
        # mesh rather than to silently drop it from the operator.
        M = np.where(M > 0.0, M, float(M[M > 0].min()) if np.any(M > 0) else 1.0)

    Minv_sqrt = 1.0 / np.sqrt(M)
    sqrtM = np.sqrt(M)

    def _mv(x):
        x = np.asarray(x, np.float64)
        flat = x.ndim == 1
        X = x.reshape(-1, 1) if flat else x
        Y = Minv_sqrt[:, None] * (K @ (Minv_sqrt[:, None] * X))
        return Y.ravel() if flat else Y

    Lsym = LinearOperator((nv, nv), matvec=_mv, matmat=_mv, dtype=np.float64)

    merged = {
        'n_negative_cotan': int(sum(s['n_negative_cotan'] for s in stats)),
        'n_degenerate_tris': int(sum(s['n_degenerate_tris'] for s in stats)),
        'n_tris': int(sum(s['n_tris'] for s in stats)),
        'n_triangulations_averaged': len(tri_sets),
        'n_zero_area_verts': n_iso,
        'clamped': bool(clamp),
        'total_area_m2': float(M.sum()),
        'mean_vertex_area_m2': float(M.mean()),
    }
    return {
        'K': K,
        'M': M,
        'sqrtM': sqrtM,
        'Minv_sqrt': Minv_sqrt,
        'Lsym': Lsym,
        'nv': nv,
        'stats': merged,
        'kind': 'cotan',
    }


def umbrella_operator(v, faces):
    """scan_ingest's operator, rebuilt here so the comparison is like-for-like.

    Uniform weights, degree-normalised, no lengths and no areas -- reproduced from
    geom/scan_ingest.py lines 1300-1314. Its 'eigenvalues' are dimensionless, so
    eig_from_wavelength() does NOT apply to it; it is driven by iteration count instead,
    exactly as scan_ingest drives it. Present as the BASELINE, not as an option.
    """
    v = np.asarray(v, np.float64)
    nv = int(v.shape[0])
    faces = np.asarray(faces, np.int64)
    n = faces.shape[1]
    I, J = [], []
    for i in range(n):
        a, b = faces[:, i], faces[:, (i + 1) % n]
        I.append(a)
        J.append(b)
        I.append(b)
        J.append(a)
    I = np.concatenate(I)
    J = np.concatenate(J)
    A = coo_matrix((np.ones(len(I)), (I, J)), shape=(nv, nv)).tocsr()
    A.data[:] = 1.0
    deg = np.asarray(A.sum(axis=1)).ravel()
    deg[deg == 0] = 1.0
    An = diags(1.0 / deg) @ A
    return {'A': An, 'nv': nv, 'kind': 'umbrella', 'mean_edge_m': float(mean_edge_length(v, faces))}


def mean_edge_length(v, faces):
    v = np.asarray(v, np.float64)
    faces = np.asarray(faces, np.int64)
    n = faces.shape[1]
    tot, cnt = 0.0, 0
    for i in range(n):
        a, b = faces[:, i], faces[:, (i + 1) % n]
        tot += float(np.linalg.norm(v[a] - v[b], axis=1).sum())
        cnt += len(a)
    return tot / max(cnt, 1)
