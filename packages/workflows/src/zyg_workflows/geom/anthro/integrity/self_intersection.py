# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""integrity.self_intersection — Self-intersection: binned broad phase + exact Moller narrow phase."""

import numpy as np
from scipy.spatial import cKDTree
from zyg_workflows.geom.anthro.integrity.constants import (
    EPS_NORMAL,
    EPS_PLANE_M,
    SELF_INTERSECTION_NOTE,
    _BROAD_BINS,
    _ms,
    _now,
)
from zyg_workflows.geom.anthro.integrity.mesh_checks import _stride, _tri_spheres, triangulate_quads

# ---------------------------------------------------------------------------------
# Self-intersection: binned broad phase + exact Moller narrow phase
# ---------------------------------------------------------------------------------


def _broadphase(cen, rad):
    """Candidate pairs with |c_i - c_j| <= r_i + r_j, found without ever materialising
    the flat single-radius pair set. Binning by radius is what makes this affordable:
    every bin pair is queried at rmax_i + rmax_j, which can only over-report, so the
    result is identical to the flat query while allocating an order of magnitude less."""
    edges = np.concatenate([[0.0], np.percentile(rad, _BROAD_BINS), [rad.max() + 1e-9]])
    edges = np.unique(edges)
    bid = np.clip(np.searchsorted(edges, rad, side='right') - 1, 0, len(edges) - 2)
    nb = len(edges) - 1
    idxs = [np.nonzero(bid == k)[0] for k in range(nb)]
    trees = [cKDTree(cen[ix]) if len(ix) else None for ix in idxs]
    rmax = [float(rad[ix].max()) if len(ix) else 0.0 for ix in idxs]

    parts = []
    for p in range(nb):
        if trees[p] is None:
            continue
        for q in range(p, nb):
            if trees[q] is None:
                continue
            r = rmax[p] + rmax[q]
            if p == q:
                pr = trees[p].query_pairs(r, output_type='ndarray')
                if len(pr):
                    parts.append(np.stack([idxs[p][pr[:, 0]], idxs[p][pr[:, 1]]], axis=1))
            else:
                sd = trees[p].sparse_distance_matrix(trees[q], r, output_type='ndarray')
                if len(sd):
                    parts.append(np.stack([idxs[p][sd['i']], idxs[q][sd['j']]], axis=1))
    if not parts:
        return np.zeros((0, 2), np.int64)
    return np.concatenate(parts).astype(np.int64)


def _interval(d, p):
    """Where a triangle crosses the other triangle's plane, as a 1-D interval along the
    two planes' intersection line. Built from every candidate contact point at once —
    vertices sitting exactly on the plane, plus the crossing point of every edge whose
    endpoints straddle it — so the sign-permutation case analysis in Moller's original
    listing is not needed and cannot be got wrong."""
    lo = np.full(len(d), np.inf)
    hi = np.full(len(d), -np.inf)
    for k in range(3):
        m = d[:, k] == 0.0
        lo = np.where(m, np.minimum(lo, p[:, k]), lo)
        hi = np.where(m, np.maximum(hi, p[:, k]), hi)
    for k in range(3):
        a, b = k, (k + 1) % 3
        m = (d[:, a] * d[:, b]) < 0.0
        den = d[:, a] - d[:, b]
        den = np.where(den == 0.0, 1.0, den)
        t = p[:, a] + (p[:, b] - p[:, a]) * (d[:, a] / den)
        lo = np.where(m, np.minimum(lo, t), lo)
        hi = np.where(m, np.maximum(hi, t), hi)
    return lo, hi


def _tri_tri(P, Q, tol_m=0.0):
    """Exact triangle-triangle intersection (Moller 1997), vectorised over pairs.

    Returns (hit, coplanar, degenerate). Coplanar and degenerate pairs are returned as
    their own masks rather than folded into `hit`, because silently calling either one
    'no intersection' is exactly the kind of quiet wrong answer this file exists to
    prevent.

    tol_m is the minimum overlap length that counts. At the default 0.0 a pair that meets
    at a single point — two triangles touching tangentially — is NOT an intersection,
    which is the behaviour a body mesh needs.
    """
    n1 = np.cross(P[:, 1] - P[:, 0], P[:, 2] - P[:, 0])
    n2 = np.cross(Q[:, 1] - Q[:, 0], Q[:, 2] - Q[:, 0])
    l1 = np.linalg.norm(n1, axis=1)
    l2 = np.linalg.norm(n2, axis=1)
    degenerate = (l1 <= EPS_NORMAL) | (l2 <= EPS_NORMAL)
    safe1 = np.where(l1 > EPS_NORMAL, l1, 1.0)[:, None]
    safe2 = np.where(l2 > EPS_NORMAL, l2, 1.0)[:, None]
    u1, u2 = n1 / safe1, n2 / safe2

    dP = np.einsum('nj,nij->ni', u2, P - Q[:, 0:1, :])
    dQ = np.einsum('nj,nij->ni', u1, Q - P[:, 0:1, :])
    dP = np.where(np.abs(dP) < EPS_PLANE_M, 0.0, dP)
    dQ = np.where(np.abs(dQ) < EPS_PLANE_M, 0.0, dQ)

    reject = (dP > 0).all(1) | (dP < 0).all(1) | (dQ > 0).all(1) | (dQ < 0).all(1)
    coplanar = (dP == 0.0).all(1) & (dQ == 0.0).all(1)

    live = ~(reject | coplanar | degenerate)
    hit = np.zeros(len(P), bool)
    if live.any():
        D = np.cross(u1[live], u2[live])
        lD = np.linalg.norm(D, axis=1)
        D = D / np.where(lD > 0, lD, 1.0)[:, None]
        pP = np.einsum('nj,nij->ni', D, P[live])
        pQ = np.einsum('nj,nij->ni', D, Q[live])
        lo1, hi1 = _interval(dP[live], pP)
        lo2, hi2 = _interval(dQ[live], pQ)
        overlap = np.minimum(hi1, hi2) - np.maximum(lo1, lo2)
        h = np.zeros(len(P), bool)
        h[np.nonzero(live)[0]] = overlap > tol_m
        hit = h
    return hit, coplanar & ~degenerate, degenerate


def _intersecting_pairs(v, tris, tol_m=0.0, chunk=250000):
    a, b, c = v[tris[:, 0]], v[tris[:, 1]], v[tris[:, 2]]
    cen, rad = _tri_spheres(v, tris)  # same spheres the ray broad phase uses, by sharing
    pairs = _broadphase(cen, rad)
    n_broad = len(pairs)
    if not n_broad:
        return (np.zeros((0, 2), np.int64), 0, 0, 0, 0)

    i, j = pairs[:, 0], pairs[:, 1]
    keep = np.linalg.norm(cen[i] - cen[j], axis=1) <= (rad[i] + rad[j])
    i, j = i[keep], j[keep]

    lo = np.minimum(np.minimum(a, b), c)
    hi = np.maximum(np.maximum(a, b), c)
    keep = np.all((lo[i] <= hi[j]) & (lo[j] <= hi[i]), axis=1)
    i, j = i[keep], j[keep]

    ti, tj = tris[i], tris[j]
    share = np.zeros(len(i), bool)
    for x in range(3):
        for y in range(3):
            share |= ti[:, x] == tj[:, y]
    i, j = i[~share], j[~share]
    n_narrow = len(i)

    out, ncop, ndeg = [], 0, 0
    for s in range(0, n_narrow, chunk):
        e = min(s + chunk, n_narrow)
        P = np.stack([v[tris[i[s:e], 0]], v[tris[i[s:e], 1]], v[tris[i[s:e], 2]]], axis=1)
        Q = np.stack([v[tris[j[s:e], 0]], v[tris[j[s:e], 1]], v[tris[j[s:e], 2]]], axis=1)
        hit, cop, deg = _tri_tri(P, Q, tol_m)
        ncop += int(cop.sum())
        ndeg += int(deg.sum())
        if hit.any():
            out.append(np.stack([i[s:e][hit], j[s:e][hit]], axis=1))
    hits = np.concatenate(out) if out else np.zeros((0, 2), np.int64)
    return hits, n_broad, n_narrow, ncop, ndeg


def _face_components(faces, comp_labels):
    """Component index of every face. A face is exactly what makes its vertices connected,
    so all of them are in the same component and vertex 0 decides it."""
    return comp_labels[np.asarray(faces)[:, 0]]


def _split_by_component(pairs, face_comp):
    """(intra, inter, {'i|j': count}) for a set of face pairs.

    THE DISTINCTION THIS DRAWS IS THE WHOLE POINT. A pair of faces that belong to the SAME
    shell and cross each other is that shell penetrating itself — a defect. A pair from
    two DIFFERENT shells is two objects meeting, which on a body cage is an eyeball in its
    socket: correct modelling, and it must not be reported as self-intersection, because a
    shell cannot self-intersect with a shell it is not part of.
    """
    z = np.zeros((0, 2), np.int64)
    if not len(pairs):
        return z, z, {}
    ca, cb = face_comp[pairs[:, 0]], face_comp[pairs[:, 1]]
    intra = ca == cb
    key = np.sort(np.stack([ca, cb], axis=1), axis=1)
    u, n = np.unique(key, axis=0, return_counts=True)
    counts = {'%d|%d' % (p, q): int(c) for (p, q), c in zip(u.tolist(), n.tolist())}
    return pairs[intra], pairs[~intra], counts


def _check_self_intersection(v, faces, comp_labels, tol_m=0.0, cross_check=True):
    """Self-intersection, counted per connected component, ON THE SURFACE THAT SHIPS.

    `pass` is decided by the INTRA-component count alone. Before that split this check
    failed all four issued characters on 338-520 pairs that were, every one of them, an
    eyeball shell meeting the head — a gate firing on correct modelling. The
    inter-component pairs are still counted, still reported per component pair, and are
    handed to `shell_components`, which is where the question they actually bear on ("is
    that shell where it should be") gets answered.

    WHICH TRIANGULATION DECIDES, AND WHY IT CHANGED (2026-08-05). This check used to pass
    a body unless BOTH quad diagonals agreed that a pair crossed, on the argument that a
    one-diagonal pair is an artefact of splitting a non-planar quad. That argument is
    sound about the abstract quad cage and unsound about the artifact: the .glb this
    pipeline delivers is triangulated [0,1,2]+[0,2,3] by mesh_skeletons._export_glb, so
    every pair that crosses under '02' is a genuine self-intersection of the delivered
    surface, agreed or not. MEASURED on abel: 18 pairs under '02', 16 under '13', 6
    agreeing — the old criterion reported 6, called 12 artefacts, and because its examples
    came from those 6 it located abel's self-intersections at "the head" while four of the
    discarded twelve were at the TOES (z 0.008). It also left a hole with no floor: a body
    with 0 agreeing pairs and any number of '02'-only pairs passed while shipping a
    self-intersecting mesh (cornelis is that body with the diagonals the other way round —
    4 pairs that exist only under '13' and therefore never ship).

    So the gating population is now '02', the delivered one. The agreeing subset and the
    '13'-only population are still measured and still reported — the first because a pair
    both triangulations produce is a stronger statement about the cage, the second because
    a pair that only the road-not-taken produces is exactly the artefact the old criterion
    was right about.
    """
    t0 = _now()
    f = np.asarray(faces)
    is_quad = f.ndim == 2 and f.shape[1] == 4
    fcomp = _face_components(f, comp_labels)

    tris, src = triangulate_quads(f, '02', return_source=True)
    hits, n_broad, n_narrow, ncop, ndeg = _intersecting_pairs(v, tris, tol_m)
    quad_pairs = (
        np.unique(np.sort(np.stack([src[hits[:, 0]], src[hits[:, 1]]], 1), 1), axis=0)
        if len(hits)
        else np.zeros((0, 2), np.int64)
    )
    intra02, inter02, counts02 = _split_by_component(quad_pairs, fcomp)

    involved = np.unique(tris[np.unique(hits)]) if len(hits) else np.zeros(0, np.int64)
    detail = {
        'diagonal': '02',
        'diagonal_is_delivered': True,
        'delivered_triangulation': 'faces[:, [0,1,2]] then faces[:, [0,2,3]] — byte-identical to '
        'mesh_skeletons._export_glb, so this is the surface inside skeleton_*.glb',
        'components': int(comp_labels.max() + 1) if len(comp_labels) else 0,
        'intersecting_triangle_pairs': int(len(hits)),
        'intersecting_face_pairs': int(len(quad_pairs)),
        'intersecting_face_pairs_intra_component': int(len(intra02)),
        'intersecting_face_pairs_inter_component': int(len(inter02)),
        'face_pairs_by_component_pair': counts02,
        'vertices_involved': int(len(involved)),
        'vertex_fraction': round(float(len(involved)) / max(len(v), 1), 8),
        'broadphase_candidate_pairs': int(n_broad),
        'narrowphase_pairs_tested': int(n_narrow),
        'coplanar_pairs': int(ncop),
        'degenerate_pairs_skipped': int(ndeg),
        'overlap_tol_m': tol_m,
        'method': SELF_INTERSECTION_NOTE,
    }

    # THE DELIVERED SURFACE GATES. Not the diagonal-agreeing subset: see the docstring.
    defect, other = intra02, inter02
    detail['face_pairs_delivered_intra_component'] = int(len(intra02))
    detail['face_pairs_delivered_inter_component'] = int(len(inter02))
    detail['delivered_face_pairs_by_component_pair'] = counts02

    if is_quad and cross_check:
        tb, sb = triangulate_quads(f, '13', return_source=True)
        hb, _, _, _, _ = _intersecting_pairs(v, tb, tol_m)
        qb = (
            np.unique(np.sort(np.stack([sb[hb[:, 0]], sb[hb[:, 1]]], 1), 1), axis=0)
            if len(hb)
            else np.zeros((0, 2), np.int64)
        )
        sa = set(map(tuple, quad_pairs.tolist()))
        sbb = set(map(tuple, qb.tolist()))
        agr = np.array(sorted(sa & sbb), np.int64).reshape(-1, 2)
        alt = np.array(sorted(sbb - sa), np.int64).reshape(-1, 2)
        dlv = np.array(sorted(sa - sbb), np.int64).reshape(-1, 2)
        g_intra, g_inter, g_counts = _split_by_component(agr, fcomp)
        a_intra, a_inter, _ = _split_by_component(alt, fcomp)
        d_intra, d_inter, _ = _split_by_component(dlv, fcomp)
        detail['alt_diagonal_13_face_pairs'] = int(len(qb))
        detail['face_pairs_diagonal_agreeing_intra_component'] = int(len(g_intra))
        detail['face_pairs_diagonal_agreeing_total'] = int(len(agr))
        detail['face_pairs_diagonal_agreeing_inter_component'] = int(len(g_inter))
        detail['diagonal_agreeing_face_pairs_by_component_pair'] = g_counts
        detail['face_pairs_delivered_only_intra_component'] = int(len(d_intra))
        detail['face_pairs_delivered_only_total'] = int(len(dlv))
        detail['face_pairs_delivered_only_inter_component'] = int(len(d_inter))
        detail['face_pairs_alt_diagonal_only_intra_component'] = int(len(a_intra))
        detail['face_pairs_alt_diagonal_only_total'] = int(len(alt))
        detail['face_pairs_alt_diagonal_only_inter_component'] = int(len(a_inter))
        detail['diagonal_note'] = (
            'THREE populations, not two. DELIVERED (%d intra) cross in the triangulation '
            'inside the .glb and are the defect this check gates on. AGREEING (%d intra) '
            'are the subset of those that also cross under the other diagonal — a stronger '
            'statement about the cage, and NOT the pass criterion, because the shipped mesh '
            'commits to one diagonal. ALT-DIAGONAL-ONLY (%d intra) cross only under the '
            'diagonal we do not export, so they are not in any artifact and do not count.'
            % (len(intra02), len(g_intra), len(a_intra))
        )
        # LEGACY KEY NAMES, repointed 2026-08-05. gates.t1_self_intersection reads these two
        # names; both now carry the delivered-surface figures so the number that blocks is
        # the number that describes the artifact.
        detail['face_pairs_both_diagonals'] = int(len(intra02))
        detail['face_pairs_both_diagonals_total'] = int(len(quad_pairs))
        detail['face_pairs_both_diagonals_inter_component'] = int(len(inter02))
        detail['robust_face_pairs_by_component_pair'] = counts02
        detail['face_pairs_diagonal_dependent'] = int(len(a_intra))
        detail['face_pairs_diagonal_dependent_total'] = int(len(alt))
        detail['face_pairs_diagonal_dependent_inter_component'] = int(len(a_inter))
        detail['legacy_key_note'] = (
            'face_pairs_both_diagonals / robust_face_pairs_by_component_pair NO LONGER MEAN '
            '"found under both diagonals": they carry the DELIVERED-triangulation figures '
            '(face_pairs_delivered_*), because that is what a gate must block on. '
            'face_pairs_diagonal_dependent now carries alt-diagonal-only pairs, which are '
            'the ones that genuinely do not ship. The old both-diagonals figures live under '
            'face_pairs_diagonal_agreeing_*. Read the explicit names; these exist only so a '
            'consumer written against the old payload keeps working and keeps FAILING '
            'CLOSED rather than under-reporting.'
        )
    else:
        detail['alt_diagonal_13_face_pairs'] = None
        detail['face_pairs_diagonal_agreeing_intra_component'] = int(len(intra02)) if not is_quad else None
        detail['face_pairs_delivered_only_intra_component'] = 0 if not is_quad else None
        detail['face_pairs_alt_diagonal_only_intra_component'] = 0 if not is_quad else None
        detail['face_pairs_both_diagonals'] = int(len(intra02))
        detail['face_pairs_diagonal_dependent'] = 0 if not is_quad else None
        detail['diagonal_note'] = (
            'a triangle mesh has no diagonal to choose, so the delivered figures are the only figures'
            if not is_quad
            else 'the cross-check against the other quad diagonal was switched OFF, so the '
            'agreeing/alt-only split is UNMEASURED (None, not 0). The delivered figures '
            'stand on their own and are what this check gates on.'
        )
        detail['legacy_key_note'] = (
            'face_pairs_both_diagonals carries the delivered-triangulation intra-component '
            'count. Where the alt-diagonal pass did not run, the split keys are None — '
            'not measured is not zero.'
        )

    detail['key_semantics'] = (
        'Every face_pairs_* key without an explicit _total/_inter_component suffix counts '
        'INTRA-COMPONENT pairs only — the shell against itself, which is the defect. '
        'Changed 2026-08-05: the gating population is the DELIVERED triangulation '
        "(mesh_skeletons exports the '02' split), not the both-diagonals intersection; the "
        'legacy key names are repointed accordingly and legacy_key_note says so.'
    )
    detail['component_note'] = (
        "INTRA-component pairs are a defect and set this check's pass flag. "
        'INTER-component pairs are two shells meeting; whether that is correct is decided '
        'by the shell_components check, not here.'
    )

    # Examples are chosen by z, spread across the defect population, so the locality
    # report cannot miss an end of the body. Taking the first 8 by face index is how
    # abel's toe defects stayed invisible behind its mouth defects.
    ex = _spread_by_z(v, f, defect, 8)
    detail['examples'] = ex.tolist()
    detail['examples_intra_component'] = ex.tolist()
    detail['examples_inter_component'] = other[:8].tolist()
    detail['examples_note'] = (
        '`examples` carries INTRA-component (defect) pairs from the DELIVERED '
        'triangulation, so a locality report built on it points at the defect and not at '
        'the eyes, and they are sampled evenly along z rather than by face index so the '
        'extremes are always represented. Inter-component examples are listed separately. '
        'Both index the `faces` array AS GIVEN — quads for a quad cage, triangles for a '
        'triangle mesh — and must NOT be used to index a triangulation.'
    )
    detail['example_locality'] = _locality(v, f, ex)
    detail['example_locality_note'] = (
        'Where the example defects ARE, resolved here so no caller has to map a face index '
        'back through a triangulation to find out — doing that with the wrong index space '
        'is how a defect at the toes gets reported at the jaw. z_frac is 0 at the lowest '
        'vertex of the whole mesh and 1 at the highest. Because the examples always '
        'include the lowest and the highest defect pair, a consumer that summarises them '
        'sees both ends of the body even though it is shown only 8 pairs; '
        'defect_locality_all_pairs carries the exact range over EVERY defect pair on the '
        'same basis.'
    )
    detail['defect_locality_all_pairs'] = _z_span(v, f, defect)
    return {'pass': bool(len(defect) == 0), 'detail': detail, 'ms': _ms(t0)}


def _pair_z(v, faces, pairs):
    """Mean height of each face pair, in metres. One number per pair, for ordering."""
    f = np.asarray(faces)
    p = np.asarray(pairs).reshape(-1, 2)
    if not len(p):
        return np.zeros(0)
    return 0.5 * (v[f[p[:, 0]]][:, :, 2].mean(axis=1) + v[f[p[:, 1]]][:, :, 2].mean(axis=1))


def _spread_by_z(v, faces, pairs, k):
    """k example pairs sampled EVENLY ALONG THE BODY, lowest and highest always included.

    `pairs[:k]` is ordered by face index, which is an artefact of the mesh's vertex
    numbering and has nothing to do with anatomy: on abel it returned 8 mouth-interior
    pairs and hid four toe pairs behind them, so the locality report said "the head" about
    a body whose feet were also broken. Sorting by height and striding cannot do that —
    _stride includes both endpoints, so the reported z span is the true span.
    """
    p = np.asarray(pairs).reshape(-1, 2)
    if len(p) <= k:
        order = np.argsort(_pair_z(v, faces, p), kind='stable')
        return p[order]
    order = np.argsort(_pair_z(v, faces, p), kind='stable')
    return p[order][_stride(len(p), k)]


def _z_span(v, faces, pairs):
    """The height range of EVERY pair in a set, not just the examples.

    Measured on the same basis as `_locality` — the centroid of each face of each pair —
    so the two are directly comparable and the example span is always a subset of this
    one.
    """
    f = np.asarray(faces)
    p = np.asarray(pairs).reshape(-1, 2)
    if not len(p):
        return {
            'n_pairs': 0,
            'z_frac_min': None,
            'z_frac_max': None,
            'note': 'over ALL defect pairs, not only the examples',
        }
    z = np.concatenate([v[f[p[:, 0]]][:, :, 2].mean(axis=1), v[f[p[:, 1]]][:, :, 2].mean(axis=1)])
    zmin = float(v[:, 2].min())
    H = float(v[:, 2].max()) - zmin
    Hs = H if H > 0 else 1.0
    fr = (z - zmin) / Hs
    return {
        'n_pairs': int(len(p)),
        'z_frac_min': round(float(fr.min()), 4),
        'z_frac_max': round(float(fr.max()), 4),
        'note': 'over ALL defect pairs, not only the examples; face centroids, the same basis as example_locality',
    }


def _locality(v, faces, pairs):
    """Where a set of face pairs sits, in stature fractions and metres."""
    f = np.asarray(faces)
    zmin = float(v[:, 2].min())
    H = float(v[:, 2].max()) - zmin
    Hs = H if H > 0 else 1.0
    out = []
    for a, b in np.asarray(pairs).reshape(-1, 2).tolist():
        ca = v[f[a]].mean(axis=0)
        cb = v[f[b]].mean(axis=0)
        out.append(
            {
                'faces': [int(a), int(b)],
                'z_frac': [round(float((ca[2] - zmin) / Hs), 4), round(float((cb[2] - zmin) / Hs), 4)],
                'centroid_m': [round(float(x), 5) for x in (ca + cb) * 0.5],
                'separation_m': round(float(np.linalg.norm(ca - cb)), 6),
            }
        )
    if out:
        zs = [z for e in out for z in e['z_frac']]
        return {'pairs': out, 'z_frac_min': min(zs), 'z_frac_max': max(zs), 'n_shown': len(out)}
    return {'pairs': [], 'z_frac_min': None, 'z_frac_max': None, 'n_shown': 0}
