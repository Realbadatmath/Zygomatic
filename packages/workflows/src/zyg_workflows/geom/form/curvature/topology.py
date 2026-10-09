# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Topology, the face-edge cache, collars, and the discrete differential operators.

Carries the old module's own import block and `_require` as well, and was moved
verbatim out of the old single-file curvature.py (lines 71-91 and 120-602; `__all__`
stayed with the package __init__, where every name it lists is bound).
"""

import hashlib
import logging as _zyg_logging
import os
import weakref

import numpy as np

from zyg_workflows.geom.anthro import integrity as _integrity

# channel kept from the pre-split module
_zyg_log = _zyg_logging.getLogger('zyg_workflows.geom.form.curvature')


def _require(cond: object, msg: str) -> None:
    """Raise :class:`RuntimeError` when *cond* is falsy — an ``assert`` that survives ``-O``."""
    if not cond:
        raise RuntimeError(msg)


# The split mesh_skeletons._export_glb ships. Not a tunable.
DELIVERED_DIAGONAL = '02'

# Koenderink shape index bands. The boundaries are the standard eighths of the index's
# range; they are a NAMING convention for a continuous quantity, not a threshold.
SHAPE_CLASSES = (
    (-1.000, -0.625, 'cup'),
    (-0.625, -0.375, 'rut'),
    (-0.375, -0.125, 'saddle_rut'),
    (-0.125, +0.125, 'saddle'),
    (+0.125, +0.375, 'saddle_ridge'),
    (+0.375, +0.625, 'ridge'),
    (+0.625, +1.001, 'cap'),
)


# ---------------------------------------------------------------------------------
# topology
# ---------------------------------------------------------------------------------
def delivered_triangles(faces):
    """The triangulation that ships. Quads are split 0-2; triangles pass through."""
    return _integrity.triangulate_quads(faces, DELIVERED_DIAGONAL)


_FACE_EDGE_CACHE = {}  # id(faces) -> (weakref, content_key, edges)
_FACE_EDGE_STATS = {'hits_by_identity': 0, 'hits_by_content': 0, 'misses': 0}
ZYG_FACE_EDGE_CACHE = os.environ.get('ZYG_FACE_EDGE_CACHE', '1') != '0'


def _face_edges(faces):
    """Undirected edge list of the ORIGINAL faces — quad edges for a quad cage.

    Grouping (dilation, collars, geodesic radii) deliberately runs on the cage's own
    edges rather than on the delivered triangles: the 0-2 diagonal is an artefact of the
    export and adding 13,710 diagonal edges to the adjacency would make a "2-ring" mean
    something different on the two sides of the body wherever the quads start at
    different corners. Curvature uses the delivered triangles; grouping does not.

    MEMOISED, because this is a PURE FUNCTION OF `faces` and the topology never changes
    within a run. Profiled on the level-1 female surface (54,848 verts): one ridge_null
    plus one relief_null called it 147 times and spent 29.5 s of a 33.7 s run inside it —
    88% — essentially all of that in np.sort under np.unique. The mesh does not change
    between those 147 calls. At level 3 (877,448 verts) the same waste is the difference
    between minutes and hours, and it was mistaken for a numerical cost that wanted a GPU.

    CACHE CORRECTNESS, which is the only part that is subtle:
      * Keyed first on the array OBJECT (id + a live weakref). A bare id() key is unsafe —
        a freed array's address can be reused and would silently hand back another mesh's
        edges — so the weakref must still be alive for an identity hit to count.
      * On identity miss, falls back to a CONTENT hash. Correct for callers that rebuild
        an equal faces array, at ~7 ms per 219k-quad hash against ~200 ms recomputed.
      * The returned array is marked READ-ONLY. Callers previously received a fresh array
        and could in principle have mutated it; sharing one now makes that an aliasing bug.
        Read-only makes such a caller raise immediately instead of corrupting every later
        consumer silently. Disable with ZYG_FACE_EDGE_CACHE=0 if that ever fires.
    """
    f = np.asarray(faces)
    if f.ndim != 2 or f.shape[1] not in (3, 4):
        raise ValueError('faces must be (F,3) or (F,4), got %r' % (f.shape,))

    if not ZYG_FACE_EDGE_CACHE:
        k = f.shape[1]
        e = np.concatenate([f[:, [i, (i + 1) % k]] for i in range(k)], axis=0)
        return np.unique(np.sort(e, axis=1), axis=0)

    key = id(f)
    hit = _FACE_EDGE_CACHE.get(key)
    if hit is not None:
        ref, _ckey, edges = hit
        if ref() is f:  # same live object, not a reused id
            _FACE_EDGE_STATS['hits_by_identity'] += 1
            return edges
        del _FACE_EDGE_CACHE[key]

    ckey = (f.shape, f.dtype.str, hashlib.blake2b(np.ascontiguousarray(f).tobytes(), digest_size=16).digest())
    for k2, (ref2, ckey2, edges2) in list(_FACE_EDGE_CACHE.items()):
        if ref2() is None:
            del _FACE_EDGE_CACHE[k2]
        elif ckey2 == ckey:
            _FACE_EDGE_STATS['hits_by_content'] += 1
            try:
                _FACE_EDGE_CACHE[key] = (weakref.ref(f), ckey, edges2)
            except TypeError as _exc:
                _zyg_log.debug('face edge cache insert skipped (not weakref-able): %s', _exc)
            return edges2

    _FACE_EDGE_STATS['misses'] += 1
    k = f.shape[1]
    e = np.concatenate([f[:, [i, (i + 1) % k]] for i in range(k)], axis=0)
    edges = np.unique(np.sort(e, axis=1), axis=0)
    edges.flags.writeable = False
    try:
        _FACE_EDGE_CACHE[key] = (weakref.ref(f), ckey, edges)
    except TypeError as _exc:  # not all array subclasses weakref
        _zyg_log.debug('face edge cache insert skipped (not weakref-able): %s', _exc)
    return edges


def face_edge_cache_stats():
    """Hit/miss counters, so the saving is measured rather than assumed."""
    return dict(_FACE_EDGE_STATS, entries=len(_FACE_EDGE_CACHE))


def vertex_adjacency(faces, n_vertices=None):
    """Symmetric CSR adjacency over the cage's own edges, with edge lengths left to
    surface_distance so one build serves both hop-counting and Dijkstra."""
    from scipy.sparse import coo_matrix

    e = _face_edges(faces)
    n = int(np.asarray(faces).max()) + 1 if n_vertices is None else int(n_vertices)
    d = np.ones(len(e))
    A = coo_matrix(
        (np.concatenate([d, d]), (np.concatenate([e[:, 0], e[:, 1]]), np.concatenate([e[:, 1], e[:, 0]]))), shape=(n, n)
    ).tocsr()
    A.data[:] = 1.0
    return A


def dilate(faces, group, rings=1, adjacency=None, n_vertices=None):
    """Grow a vertex group by `rings` edge hops. rings=0 returns the group unchanged."""
    A = vertex_adjacency(faces, n_vertices) if adjacency is None else adjacency
    m = np.zeros(A.shape[0], bool)
    g = np.asarray(group, np.int64).ravel()
    if g.size == 0:
        raise ValueError('cannot dilate an empty group')
    m[g] = True
    for _ in range(int(rings)):
        m = m | (A.dot(m.astype(np.float64)) > 0)
    return np.nonzero(m)[0]


# HOUSE collar geometry, in fractions of stature so it is the same physical band on a
# 1.52 m child and a 1.85 m adult. gap keeps the feature's own shoulder out of the
# reference surface; width is thick enough to carry a 6-coefficient quadric.
COLLAR_GAP_FRAC = 0.006  # 10.1 mm at 1.686 m
COLLAR_WIDTH_FRAC = 0.014  # 23.6 mm at 1.686 m
COLLAR_MAX_TILT_DEG = 60.0
COLLAR_MIN_VERTS = 14


def collar(
    v,
    faces,
    group,
    gap_frac=COLLAR_GAP_FRAC,
    width_frac=COLLAR_WIDTH_FRAC,
    stature_m=None,
    normals=None,
    max_tilt_deg=COLLAR_MAX_TILT_DEG,
    min_verts=COLLAR_MIN_VERTS,
    distances=None,
    return_detail=False,
):
    """The band of surface AROUND a group, selected by GEODESIC DISTANCE, not by edge hops.

    RINGS DO NOT WORK ON THIS CAGE and the first version of this function used them. Cage
    edge lengths run 1.4 mm to 58.9 mm (median 5.9), so "5 rings" from a seed on the upper
    arm reaches 75-107 mm of surface distance — more than the arm's own circumference. The
    collar then wrapped the limb, the PCA frame had no meaning, and the quadric fitted to
    it left residuals of 10-21 mm RMS on patches of perfectly smooth skin, against 2.5-4 mm
    on the trunk where the same ring count stayed local. Every relief taken through such a
    collar was noise: measured +39.9 mm "protrusion" on a featureless stretch of upper arm.
    A metric band fixes it because it is a metric question.

    `gap_frac` is the buffer between group and collar, and it is load-bearing: a bony
    landmark does not stop at the edge of whatever anchor named it, so a collar taken flush
    against the group sits on the shoulder of the feature being measured and cancels it.

    `max_tilt_deg` drops collar vertices whose normal has turned more than that away from
    the group's own mean normal — i.e. surface that has curved round onto another aspect of
    the body and is not a graph over the patch's tangent plane any more. The normals used
    are this module's both-triangle ones, whose mirror residual is 0.0103 rms / 0.371 max
    against 0.1253 / 1.1743 for mesh_skeletons._vertex_normals (measured on the neutral),
    so this filter does not reintroduce the left/right artefact.

    The band WIDENS in steps if it is too thin to carry a 6-coefficient quadric, and the
    width actually used is returned. That is not silent adaptation — a caller reading
    `width_frac_used` sees it — and it is unavoidable on a cage whose vertex density varies
    by 40x between the face and the back.
    """
    v = np.asarray(v, np.float64)
    g = np.unique(np.asarray(group, np.int64).ravel())
    if g.size == 0:
        raise ValueError('cannot build a collar around an empty group')
    S = float(v[:, 2].max() - v[:, 2].min()) if stature_m is None else float(stature_m)
    d = surface_distance(v, faces, g) if distances is None else np.asarray(distances)
    n = vertex_normals(v, faces) if normals is None else np.asarray(normals, np.float64)
    pn = n[g].mean(0)
    ln = float(np.linalg.norm(pn))
    if ln <= 1e-9:
        raise ValueError('group normals cancel exactly; it spans opposite faces of the body')
    pn = pn / ln
    tilt_ok = n.dot(pn) >= np.cos(np.radians(max_tilt_deg))
    lo = gap_frac * S
    tried = []
    for k in (1.0, 1.5, 2.0, 3.0):
        w = width_frac * S * k
        idx = np.nonzero((d >= lo) & (d <= lo + w) & tilt_ok)[0]
        tried.append((round(width_frac * k, 5), int(len(idx))))
        if len(idx) >= min_verts:
            break
    else:
        raise ValueError(
            'collar around a %d-vertex group never reached %d vertices: (width_frac, n) '
            'tried %s, with a %.1f-degree tilt cut at a gap of %.4f of stature. Either the '
            'group sits on a part of the cage too coarsely tessellated to carry a local '
            'reference surface, or it already spans the whole aspect it lies on.'
            % (len(g), min_verts, tried, max_tilt_deg, gap_frac)
        )
    if return_detail:
        return idx, {
            'gap_frac': gap_frac,
            'width_frac_used': round(width_frac * k, 5),
            'width_steps_tried': tried,
            'max_tilt_deg': max_tilt_deg,
            'group_normal': [float(x) for x in pn],
        }
    return idx


def boundary_vertices(faces, n_vertices=None):
    """Vertices on an open boundary of the DELIVERED triangulation.

    Curvature is undefined there — the cotangent sum and the 2*pi angle deficit both
    assume a closed vertex star — so those vertices are returned as NaN rather than as a
    plausible number. The anny body shell, tongue and eyeballs are all closed, so this is
    empty on the cage; it is here because the primitives in self_test() are not.
    """
    tris = delivered_triangles(faces)
    e = np.sort(np.concatenate([tris[:, [0, 1]], tris[:, [1, 2]], tris[:, [2, 0]]]), axis=1)
    u, c = np.unique(e, axis=0, return_counts=True)
    b = u[c == 1]
    n = int(np.asarray(faces).max()) + 1 if n_vertices is None else int(n_vertices)
    m = np.zeros(n, bool)
    m[b.ravel()] = True
    return np.nonzero(m)[0]


# ---------------------------------------------------------------------------------
# differential operators
# ---------------------------------------------------------------------------------
def vertex_normals(v, faces):
    """Area-weighted vertex normals over BOTH delivered triangles of every quad.

    Deliberately not mesh_skeletons._vertex_normals, which uses corners (0,1,2) only: on
    this cage 10,265 of 13,710 quads are stored starting at a different corner on the
    mirrored side, and a one-triangle normal over a warped quad is then not
    mirror-equivariant (measured max deviation 1.168 — see the module docstring). Using
    both triangles is also simply what the delivered surface IS.
    """
    v = np.asarray(v, np.float64)
    tris = delivered_triangles(faces)
    fn = np.cross(v[tris[:, 1]] - v[tris[:, 0]], v[tris[:, 2]] - v[tris[:, 0]])
    n = np.zeros((len(v), 3))
    for k in range(3):
        for c in range(3):
            n[:, c] += np.bincount(tris[:, k], fn[:, c], minlength=len(v))
    ln = np.linalg.norm(n, axis=1)
    bad = ln <= 1e-14
    if bad.any():
        raise ValueError(
            '%d vertices have a degenerate normal (incident triangle areas '
            'cancel); first is vertex %d' % (int(bad.sum()), int(np.argmax(bad)))
        )
    return n / ln[:, None]


def _triangle_terms(v, tris):
    """Per-corner interior angles, cotangents and triangle areas."""
    P = v[tris[:, 0]], v[tris[:, 1]], v[tris[:, 2]]
    cr = np.cross(P[1] - P[0], P[2] - P[0])
    twice_area = np.linalg.norm(cr, axis=1)
    if (twice_area <= 0).any():
        j = int(np.argmin(twice_area))
        raise ValueError(
            'delivered triangle %d (vertices %s) has zero area, so its cotangents are '
            'undefined. The cotangent Laplacian cannot be computed on this mesh and '
            'clamping the weight would fabricate a curvature.' % (j, tris[j].tolist())
        )
    cot = np.empty((len(tris), 3))
    ang = np.empty((len(tris), 3))
    for k in range(3):
        a, b, c = P[k], P[(k + 1) % 3], P[(k + 2) % 3]
        u, w = b - a, c - a
        dot = (u * w).sum(1)
        cross = np.linalg.norm(np.cross(u, w), axis=1)
        cot[:, k] = dot / cross
        ang[:, k] = np.arctan2(cross, dot)
    return ang, cot, 0.5 * twice_area


def mixed_voronoi_area(v, faces):
    """Meyer et al. (2003) mixed area: Voronoi where the triangle is non-obtuse, a
    barycentric fallback where it is not.

    The plain Voronoi area goes NEGATIVE on an obtuse triangle, which turns the mean
    curvature at that vertex inside out. This is not an edge case here: 14,380 of the
    27,420 delivered triangles of the anny neutral are obtuse (52.4%, measured), because
    the cage's quads are long and thin over the limbs. The resulting areas span
    0.23 mm^2 to 1310 mm^2, a ratio of 5707 — which is also why every mean taken over a
    region in this module is area-weighted.
    """
    v = np.asarray(v, np.float64)
    tris = delivered_triangles(faces)
    ang, cot, area = _triangle_terms(v, tris)
    obtuse = ang.max(1) > np.pi / 2
    out = np.zeros(len(v))
    for k in range(3):
        i = tris[:, k]
        j, m = tris[:, (k + 1) % 3], tris[:, (k + 2) % 3]
        d_ij = ((v[i] - v[j]) ** 2).sum(1)
        d_im = ((v[i] - v[m]) ** 2).sum(1)
        a = 0.125 * (d_ij * cot[:, (k + 2) % 3] + d_im * cot[:, (k + 1) % 3])
        at_i = ang[:, k] > np.pi / 2
        a = np.where(obtuse, np.where(at_i, area * 0.5, area * 0.25), a)
        out += np.bincount(i, a, minlength=len(v))
    if (out <= 0).any():
        raise ValueError('%d vertices got a non-positive mixed area' % int((out <= 0).sum()))
    return out


def cotangent_weights(v, faces):
    """Symmetric CSR W with W[i,j] = 0.5 * (cot alpha + cot beta) over the delivered
    triangles, so that sum_j 2*W[i,j]*(x_i - x_j) is Meyer's mean-curvature normal
    numerator."""
    from scipy.sparse import coo_matrix

    v = np.asarray(v, np.float64)
    tris = delivered_triangles(faces)
    _, cot, _ = _triangle_terms(v, tris)
    rows, cols, vals = [], [], []
    for k in range(3):
        j, m = tris[:, (k + 1) % 3], tris[:, (k + 2) % 3]
        rows.append(j)
        cols.append(m)
        vals.append(0.5 * cot[:, k])
        rows.append(m)
        cols.append(j)
        vals.append(0.5 * cot[:, k])
    n = len(v)
    return coo_matrix((np.concatenate(vals), (np.concatenate(rows), np.concatenate(cols))), shape=(n, n)).tocsr()


def curvature(v, faces, stature_m=None, normals=None):
    """Per-vertex discrete curvature on the delivered triangulation.

    Returns a dict of (V,) arrays: mean H and Gaussian K in 1/m and 1/m^2, the principal
    curvatures k1 >= k2, the shape index and the curvedness, plus the stature-normalised
    forms that a threshold may actually be written against. Boundary vertices are NaN.

    k1/k2 are recovered from H and K through k = H +/- sqrt(H^2 - K). Discrete H and K are
    estimated independently and their discretisation errors do not agree, so H^2 - K comes
    out slightly negative on some vertices of a real mesh — measured on the anny neutral,
    526 of 13,718 (3.8%). That is an artefact of the estimator, not a property of the
    surface, so the radicand is clamped at zero and `umbilic_clamped` names every vertex
    where it fired, because a caller reading k1 and k2 needs to know they were forced
    equal there. H, K, shape index and curvedness elsewhere are untouched.
    """
    v = np.asarray(v, np.float64)
    n = vertex_normals(v, faces) if normals is None else np.asarray(normals, np.float64)
    tris = delivered_triangles(faces)
    ang, _, _ = _triangle_terms(v, tris)
    A = mixed_voronoi_area(v, faces)
    W = cotangent_weights(v, faces)

    # Meyer eq. 8: K(x_i) = (1/2A) sum_j (cot a + cot b)(x_i - x_j) = 2 * H * n.
    lap = (np.asarray(W.sum(1)).ravel()[:, None] * v) - W.dot(v)
    kvec = lap / A[:, None]
    H = 0.5 * (kvec * n).sum(1)

    deficit = 2.0 * np.pi - np.bincount(tris.ravel(), ang.ravel(), minlength=len(v))
    K = deficit / A

    b = boundary_vertices(faces, len(v))
    if len(b):
        H[b] = np.nan
        K[b] = np.nan

    disc = H * H - K
    clamped = disc < 0
    root = np.sqrt(np.maximum(disc, 0.0))
    k1, k2 = H + root, H - root

    si = shape_index(k1, k2)
    si[~np.isfinite(H)] = np.nan
    cv = curvedness(k1, k2)

    S = float(v[:, 2].max() - v[:, 2].min()) if stature_m is None else float(stature_m)
    if S <= 0:
        raise ValueError('stature must be positive, got %r' % (S,))
    return {
        'stature_m': S,
        'mean_H': H,
        'gaussian_K': K,
        'k1': k1,
        'k2': k2,
        'shape_index': si,
        'curvedness': cv,
        'area_mixed_m2': A,
        'normals': n,
        # dimensionless, so one threshold works on a 1.52 m child and a 1.85 m adult
        'mean_H_norm': H * S,
        'gaussian_K_norm': K * S * S,
        'curvedness_norm': cv * S,
        'boundary_vertices': b,
        'umbilic_clamped': np.nonzero(clamped & np.isfinite(H))[0],
    }


def shape_index(k1, k2):
    """Koenderink shape index in [-1, +1]: -1 cup, -0.5 rut, 0 saddle, +0.5 ridge, +1 cap.

    Answers "is this a ridge or a pit", which mean curvature alone cannot: a ridge and a
    saddle can share a mean curvature and are not the same form.

    An UMBILIC (k1 == k2, which is every vertex of a sphere and a third of the vertices of
    a real mesh once the estimator's H^2 < K artefact is clamped) has k1 - k2 = 0. The
    arctan2 form is 0/0 there and the obvious `np.where(d > 0, ..., 0.0)` guard silently
    files a sphere as a SADDLE — measured, it turned the primitive test's sphere from
    +1.0 to 0.0. An umbilic is a cap or a cup by the sign of its curvature; only a totally
    flat point has no shape index, and that one is NaN.
    """
    k1 = np.asarray(k1, np.float64)
    k2 = np.asarray(k2, np.float64)
    d = k1 - k2
    s = k1 + k2
    out = np.full(np.broadcast(k1, k2).shape, np.nan, np.float64)
    with np.errstate(invalid='ignore', divide='ignore'):
        np.divide(2.0 * np.arctan2(s, d), np.pi, out=out, where=(d > 0))
    umb = (d <= 0) & (s != 0)
    out = np.where(umb, np.sign(s), out)
    return out


def curvedness(k1, k2):
    """Koenderink curvedness, 1/m: how sharply curved, independent of the shape class."""
    k1 = np.asarray(k1, np.float64)
    k2 = np.asarray(k2, np.float64)
    return np.sqrt(0.5 * (k1 * k1 + k2 * k2))


def shape_class(si):
    """Name for one shape-index value, or 'undefined' for NaN."""
    if not np.isfinite(si):
        return 'undefined'
    for lo, hi, name in SHAPE_CLASSES:
        if lo <= si < hi:
            return name
    return 'cap' if si >= 0 else 'cup'


def surface_distance(v, faces, seeds, limit_m=None):
    """Along-surface distance in metres from a seed set, by Dijkstra over the cage's edges.

    This is a GRAPH geodesic, not a true one: a shortest path constrained to run along
    edges overestimates the true geodesic (the classic bound is up to ~15% on an
    irregular triangulation, less on a near-regular quad cage). Named as such because a
    "geodesic radius" that is quietly 10% too large silently grows every region built
    from it. Where the difference matters, use a smaller radius, not a better name.
    """
    from scipy.sparse import coo_matrix
    from scipy.sparse.csgraph import dijkstra

    v = np.asarray(v, np.float64)
    e = _face_edges(faces)
    w = np.linalg.norm(v[e[:, 0]] - v[e[:, 1]], axis=1)
    if (w <= 0).any():
        raise ValueError('%d cage edges have zero length' % int((w <= 0).sum()))
    n = len(v)
    G = coo_matrix(
        (np.concatenate([w, w]), (np.concatenate([e[:, 0], e[:, 1]]), np.concatenate([e[:, 1], e[:, 0]]))), shape=(n, n)
    ).tocsr()
    d = dijkstra(
        G,
        directed=False,
        indices=np.asarray(seeds, np.int64).ravel(),
        min_only=True,
        limit=np.inf if limit_m is None else float(limit_m),
    )
    return d
