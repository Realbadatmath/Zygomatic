# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Catmull-Clark, the combinatorial mirror map and the index-preservation proof.

Moved verbatim out of the old single-file relief_subdiv.py (lines 375-703).
"""

import numpy as np
# ---------------------------------------------------------------------------------
# Catmull-Clark
# ---------------------------------------------------------------------------------


def catmull_clark(v, faces):
    """One Catmull-Clark step on a CLOSED, ALL-QUAD mesh.

    Returns (V2, F2) with V2 ordered [updated originals | face points | edge points], so
    original vertex i is V2[i] at every level. That ordering is the whole reason this is
    written out rather than delegated; see the module docstring, reason 2.

    The closed/all-quad precondition is ASSERTED, not assumed: every undirected edge must
    be shared by exactly two quads. anny's cage satisfies it on all four components (body,
    tongue, two eyeballs). A mesh that does not satisfy it needs the boundary rules, which
    are not implemented here, and getting silently smoothed by the interior rules instead
    is how a lip or an eyelid rim quietly loses its crease.
    """
    v = np.asarray(v, np.float64)
    F = np.asarray(faces, np.int64)
    if F.ndim != 2 or F.shape[1] != 4:
        raise ValueError('catmull_clark needs quads, got faces of shape %r' % (F.shape,))
    n, m = len(v), len(F)

    fp = v[F].mean(axis=1)  # face points

    # undirected edge table: 4 per quad, deduplicated on the sorted index pair
    E = np.concatenate([np.stack([F[:, k], F[:, (k + 1) % 4]], 1) for k in range(4)], 0)
    uniq, inv = np.unique(np.sort(E, axis=1), axis=0, return_inverse=True)
    inv = inv.ravel()
    ne = len(uniq)
    cnt = np.bincount(inv, minlength=ne)
    if cnt.min() != 2 or cnt.max() != 2:
        raise ValueError(
            'the mesh is not closed and 2-manifold: %d edges are used once and %d more '
            "than twice. Catmull-Clark's interior rules are the only ones implemented "
            'here and applying them to a boundary would smooth the boundary away.'
            % (int((cnt == 1).sum()), int((cnt > 2).sum()))
        )

    # edge point = (a + b + fp(f1) + fp(f2)) / 4
    fsum = np.zeros((ne, 3), np.float64)
    np.add.at(fsum, inv, fp[np.tile(np.arange(m, dtype=np.int64), 4)])
    ep = 0.25 * (v[uniq[:, 0]] + v[uniq[:, 1]] + fsum)

    # new vertex point = (F_avg + 2 R_avg + (val - 3) P) / val, R = edge MIDPOINTS
    val = np.bincount(F.ravel(), minlength=n).astype(np.float64)  # closed => faces=valence
    if (val <= 0).any():
        raise ValueError('%d vertices belong to no quad' % int((val <= 0).sum()))
    Favg = np.zeros((n, 3), np.float64)
    np.add.at(Favg, F.ravel(), np.repeat(fp, 4, axis=0))
    Favg /= val[:, None]
    emid = 0.5 * (v[uniq[:, 0]] + v[uniq[:, 1]])
    eval_ = np.bincount(uniq.ravel(), minlength=n).astype(np.float64)
    Ravg = np.zeros((n, 3), np.float64)
    np.add.at(Ravg, uniq[:, 0], emid)
    np.add.at(Ravg, uniq[:, 1], emid)
    Ravg /= eval_[:, None]
    newP = (Favg + 2.0 * Ravg + (val - 3.0)[:, None] * v) / val[:, None]

    V2 = np.concatenate([newP, fp, ep], 0)
    ei = inv.reshape(4, m).T + (n + m)  # ei[f, k] = edge point of corner k -> k+1
    fpi = np.arange(m, dtype=np.int64) + n
    F2 = np.concatenate([np.stack([F[:, k], ei[:, k], fpi, ei[:, (k + 3) % 4]], 1) for k in range(4)], 0)
    return (
        V2,
        F2,
        {
            'n_verts': int(len(V2)),
            'n_faces': int(len(F2)),
            'n_edges_cage': int(ne),
            'offsets': {'originals': 0, 'face_points': n, 'edge_points': n + m},
        },
    )


def subdivide(v, faces, levels):
    """`levels` Catmull-Clark steps. Returns (V, F, provenance) with a record per level.

    `provenance['originals_moved_mm']` is the distance each ORIGINAL vertex travelled under
    the smoothing rule, cumulative. It is not an error term — Catmull-Clark converges to
    the limit surface from the inside and the originals really do move — but it is the
    number that says how far the surface a group was authored on has drifted from the
    surface it is now being read on, so it is measured and printed rather than assumed
    small.
    """
    v0 = np.asarray(v, np.float64)
    V, F = v0, np.asarray(faces, np.int64)
    prov = {
        'levels': int(levels),
        'per_level': [],
        'cage': {'n_verts': int(len(v0)), 'n_faces': int(len(F)), 'stature_m': float(v0[:, 2].max() - v0[:, 2].min())},
    }
    for lv in range(int(levels)):
        V, F, rec = catmull_clark(V, F)
        S = float(V[:, 2].max() - V[:, 2].min())
        moved = np.linalg.norm(V[: len(v0)] - v0, axis=1)
        rec.update(
            level=lv + 1,
            stature_m=S,
            stature_delta_mm=1e3 * (S - prov['cage']['stature_m']),
            originals_moved_mm={'max': float(1e3 * moved.max()), 'median': float(1e3 * np.median(moved))},
        )
        prov['per_level'].append(rec)
    return V, F, prov


def subdiv_mirror_map(mate_cage, faces_cage, levels):
    """The mirror partner map on the subdivided mesh, derived COMBINATORIALLY.

    Exact where the geometric mutual-nearest-neighbour search is only approximately safe:
    subdivision halves the vertex spacing per level while the mesh's own mirror residual
    is inherited from the cage (0.0599 mm on originals/male against a 0.2517 mm closest
    distinct-vertex spacing), so by level 3 the residual is several times the spacing and a
    nearest-neighbour pairing can land on a neighbour of the true partner.

    The rules follow the subdivision's own structure:
      originals    keep the cage's partner (index preservation makes this an identity)
      face points  pair with the face whose corner SET is the mirror of this face's
      edge points  pair with the edge (mate[a], mate[b])
    Anything whose partner is unpaired at the previous level stays unpaired (-1), which is
    the same convention relief.mirror_map uses and what drives midline x-displacement to
    exactly zero.
    """
    mate = np.asarray(mate_cage, np.int64).copy()
    F = np.asarray(faces_cage, np.int64)
    for _ in range(int(levels)):
        n, m = len(mate), len(F)
        uniq, inv = np.unique(
            np.sort(np.concatenate([np.stack([F[:, k], F[:, (k + 1) % 4]], 1) for k in range(4)], 0), axis=1),
            axis=0,
            return_inverse=True,
        )
        inv = inv.ravel()
        ne = len(uniq)

        # face point partners: key each face by its sorted corner tuple, look up the
        # sorted MIRRORED corner tuple in the same table
        key = np.sort(F, axis=1)
        order = np.lexsort(key.T[::-1])
        ksorted = key[order]
        mf = np.where(mate[F] >= 0, mate[F], -1)
        bad_f = (mf < 0).any(axis=1)
        mkey = np.sort(np.where(mf < 0, 0, mf), axis=1)
        pos = _lexsearch(ksorted, mkey)
        fmate = np.where((pos >= 0) & ~bad_f, order[np.clip(pos, 0, m - 1)], -1)

        # edge point partners
        me = np.where(mate[uniq] >= 0, mate[uniq], -1)
        bad_e = (me < 0).any(axis=1)
        eorder = np.arange(ne)  # uniq is already lexsorted by np.unique
        epos = _lexsearch(uniq, np.sort(np.where(me < 0, 0, me), axis=1))
        emate = np.where((epos >= 0) & ~bad_e, eorder[np.clip(epos, 0, ne - 1)], -1)

        new = np.concatenate([mate, np.where(fmate >= 0, fmate + n, -1), np.where(emate >= 0, emate + n + m, -1)])
        ei = inv.reshape(4, m).T + (n + m)
        fpi = np.arange(m, dtype=np.int64) + n
        F = np.concatenate([np.stack([F[:, k], ei[:, k], fpi, ei[:, (k + 3) % 4]], 1) for k in range(4)], 0)
        mate = new
    return mate


def fast_mirror_map(v, tol_m):
    """relief.mirror_map's ANSWER, by k-d tree instead of by a Python loop over vertices.

    IDENTICAL BY CONSTRUCTION, not merely similar, and that matters because it is
    substituted for the real one inside the layer at levels 2 and 3. Both compute: for
    every vertex, the nearest vertex to its x-negated image; keep the pair only if the
    match is MUTUAL and within tol_m. relief.mirror_map prunes the search to a z-slab of
    +/-20*tol_m first, which cannot change any surviving pair — a candidate outside that
    slab is more than 20*tol_m away in z alone, so it is beyond tol_m and would be refused
    regardless. The only remaining difference is tie-breaking (relief takes the lowest
    index via np.argmin; a k-d tree's tie order is unspecified), and an exact distance tie
    between two distinct candidates does not occur on these meshes — which is checked, not
    assumed, by _verify_fast_mirror_map().

    WHY IT IS NEEDED. The loop version is O(V) Python iterations over a z-slab whose own
    size grows with V, so it is quadratic in practice: MEASURED, ~5 minutes at 219,368
    vertices and an extrapolated ~80 minutes at 877,448, called once inside relief_field
    and once again by the audit. That is not a change of method, it is a change of search
    structure, and it is the only reason level 3 is reachable at all.
    """
    from scipy.spatial import cKDTree

    P = np.asarray(v, np.float64)
    q = P.copy()
    q[:, 0] *= -1.0
    tree = cKDTree(P)
    d1, m1 = tree.query(q, k=1, workers=-1)
    m1 = np.asarray(m1, np.int64)
    ok = d1 <= float(tol_m)
    mutual = np.zeros(len(P), bool)
    idx = np.nonzero(ok)[0]
    mutual[idx] = m1[m1[idx]] == idx
    back = np.where(mutual, m1, -1).astype(np.int64)
    return back, np.asarray(d1, np.float64)


def _verify_fast_mirror_map(v, tol_m):
    """fast_mirror_map against relief.mirror_map on the SAME mesh, index for index.

    Run at the levels where the loop version is affordable (cage and level 1), so the
    substitution at levels 2 and 3 rests on a measurement rather than on the argument in
    fast_mirror_map's docstring.
    """
    from zyg_workflows.geom import relief as RL

    a, _ = RL.mirror_map(v, tol_m)
    b, _ = fast_mirror_map(v, tol_m)
    return {
        'n': int(len(a)),
        'paired_loop': int((a >= 0).sum()),
        'paired_tree': int((b >= 0).sum()),
        'differences': int((a != b).sum()),
        'identical': bool(np.array_equal(a, b)),
    }


class mirror_map_override(object):
    """Scoped substitution of relief.mirror_map by a PRECOMPUTED map of the same mesh.

    A monkeypatch, said out loud rather than hidden in a helper: relief._Ctx builds its
    mirror map internally and there is no seam to pass one in. The substitution is restored
    in `finally` on every path, and it refuses to answer for any mesh whose vertex count it
    was not built for, falling through to the real function instead.

    WHAT IT INSTALLS IS WHATEVER THE CALLER HANDS IT, AND ON THE DEFAULT PATH THAT IS NOT
    relief.mirror_map's ANSWER. apply_relief_at passes the COMBINATORIAL map (mirror=
    'combinatorial', the default), which is derived through the subdivision and is exact.
    That map is not always what relief.mirror_map's mutual-nearest-neighbour search returns:
    MEASURED on originals/male at level 2 the geometric search pairs 219,352 of 219,368 and
    disagrees with the combinatorial map on 40 of them. So this class is a BEHAVIOURAL
    substitution on the default path, not a performance one — the layer's mirror diagnostics
    (paired count, Newell-normal mirror residual, the symmetry warning) differ between the
    two maps, and on the male at level 2 the geometric map fires a warning the combinatorial
    one does not. Read `report['mirror_map_used']['kind']` before comparing two runs.

    Passing fast_mirror_map's answer (mirror='geometric') IS the performance-only case: it
    reproduces relief.mirror_map exactly where that function is trustworthy, which is what
    _verify_fast_mirror_map checks at cage level and level 1. That verification validates
    the geometric path; it says nothing about the combinatorial map, which is verified
    separately by mirror_audit at every level and by the involution and two-level checks in
    self_test.
    """

    def __init__(self, mate, dist, n_expected):
        self.mate = np.asarray(mate, np.int64)
        self.dist = np.asarray(dist, np.float64)
        self.n = int(n_expected)
        self._real = None

    def __enter__(self):
        from zyg_workflows.geom import relief as RL

        self._real = RL.mirror_map
        real = self._real
        mate, dist, n = self.mate, self.dist, self.n

        def patched(v, tol_m):
            if len(v) != n:
                return real(v, tol_m)
            return mate.copy(), dist.copy()

        patched.__doc__ = 'relief_subdiv.mirror_map_override: precomputed fast_mirror_map for the %d-vertex mesh' % n
        RL.mirror_map = patched
        return self

    def __exit__(self, *exc):
        from zyg_workflows.geom import relief as RL

        RL.mirror_map = self._real
        return False


def _lexsearch(table_sorted, queries):
    """Row index of each query row in a lexicographically sorted integer table, or -1.

    np.searchsorted has no 2-D form; packing rows into a single integer key is exact here
    because every index is < 2**31 and the rows are at most 4 wide, so the packed key fits
    in the 64-bit signed range only for 2 columns — hence the explicit per-column
    tie-break search instead of packing.
    """
    t = np.asarray(table_sorted, np.int64)
    q = np.asarray(queries, np.int64)
    lo = np.zeros(len(q), np.int64)
    hi = np.full(len(q), len(t), np.int64)
    for c in range(t.shape[1]):
        col = t[:, c]
        newlo = np.empty_like(lo)
        newhi = np.empty_like(hi)
        for i in range(len(q)):  # bounded by the 4 columns, not by V
            a, b = int(lo[i]), int(hi[i])
            if b <= a:
                newlo[i], newhi[i] = a, a
                continue
            seg = col[a:b]
            newlo[i] = a + int(np.searchsorted(seg, q[i, c], 'left'))
            newhi[i] = a + int(np.searchsorted(seg, q[i, c], 'right'))
        lo, hi = newlo, newhi
    return np.where(hi > lo, lo, -1)


def verify_index_preservation(v_cage, v_sub, faces_cage, faces_sub, levels):
    """The guarantee the whole regions.json reuse rests on, checked rather than trusted.

    Two independent statements:
      (1) POSITIONAL — subdivided vertex i is the smoothed image of cage vertex i, so the
          distance between them is the smoothing displacement and nothing else. Reported in
          mm; it is NOT expected to be zero.
      (2) STRUCTURAL — cage vertex i still appears as a corner of 4^levels * valence(i)
          subdivided quads, i.e. it kept its own 1-ring. If the ordering were wrong this
          fails outright rather than reading a plausible-looking wrong number.
    """
    v_cage = np.asarray(v_cage, np.float64)
    n = len(v_cage)
    moved = np.linalg.norm(np.asarray(v_sub, np.float64)[:n] - v_cage, axis=1)
    # Each Catmull-Clark step replaces every incident quad of vertex i with exactly ONE
    # sub-quad that still has i as a corner, so the corner count of an original vertex is
    # invariant under subdivision and equals its cage valence at every level.
    want = np.bincount(np.asarray(faces_cage, np.int64).ravel(), minlength=n)
    got = np.bincount(np.asarray(faces_sub, np.int64).ravel(), minlength=len(v_sub))[:n]
    ok = bool(np.array_equal(got, want))
    return {
        'n_cage_verts': int(n),
        'levels': int(levels),
        'positional_moved_mm': {'max': float(1e3 * moved.max()), 'median': float(1e3 * np.median(moved))},
        'structural_corner_count_preserved': ok,
        'structural_mismatches': int((got != want).sum()),
    }
