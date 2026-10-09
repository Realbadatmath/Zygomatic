# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""integrity.mesh_checks — Quads -> triangles, edge topology, components / Euler / genus, and the two shared
sampling helpers (_tri_spheres, _stride) both the ray tests and the self-intersection
broad phase query."""

import numpy as np
from scipy.sparse import csr_matrix
from scipy.sparse.csgraph import connected_components
from scipy.spatial import cKDTree
from zyg_workflows.geom.anthro.integrity.constants import EPS_AREA_M2, EPS_DUPLICATE_M, _ms, _now

# ---------------------------------------------------------------------------------
# Quads -> triangles
# ---------------------------------------------------------------------------------


def triangulate_quads(faces, diagonal='02', return_source=False):
    """Split a QUAD cage into triangles. Passes (F,3) input through unchanged.

    THE DIAGONAL IS A CHOICE, AND IT IS NOT FREE. A quad whose four corners are not
    coplanar does not define a surface; splitting it on 0-2 and splitting it on 1-3
    produce two DIFFERENT piecewise-linear surfaces, each a valid interpolant of the same
    control points, and they can disagree about whether the mesh touches itself. A
    self-intersection reported under one diagonal and absent under the other is an
    artefact of this choice, not a property of the cage.

    THE CHOICE IS NOT OURS TO MAKE, THOUGH — the exporter already made it. The '02' layout
    deliberately reproduces mesh_skeletons._export_glb exactly — two stacked blocks,
    [0,1,2] then [0,2,3] — so triangle indices here and triangle indices in the issued .glb
    are the same integers, and '02' IS the surface that ships. `check_integrity` therefore
    runs both diagonals, gates on '02' (the delivered surface, where an intersection is a
    real defect of a real artifact), and reports the other two populations beside it: the
    pairs both diagonals agree on, and the pairs that exist only under '13' and therefore
    do not ship at all. Nothing else in this file should re-litigate it.

    Returns tris (2F,3), or (tris, quad_of_tri) when return_source is set.
    """
    f = np.asarray(faces)
    if f.ndim != 2:
        raise ValueError('faces must be 2-D, got shape %r' % (f.shape,))
    if f.shape[1] == 3:
        tris = f
        src = np.arange(len(f))
    elif f.shape[1] == 4:
        if diagonal == '02':
            tris = np.concatenate([f[:, [0, 1, 2]], f[:, [0, 2, 3]]], axis=0)
        elif diagonal == '13':
            tris = np.concatenate([f[:, [0, 1, 3]], f[:, [1, 2, 3]]], axis=0)
        else:
            raise ValueError("diagonal must be '02' or '13', got %r" % (diagonal,))
        src = np.tile(np.arange(len(f)), 2)
    else:
        raise ValueError('faces must have 3 or 4 columns, got %d' % f.shape[1])
    tris = np.ascontiguousarray(tris.astype(np.int64))
    return (tris, src) if return_source else tris


# ---------------------------------------------------------------------------------
# Edge topology
# ---------------------------------------------------------------------------------


def _undirected_edges(tris):
    e = np.concatenate([tris[:, [0, 1]], tris[:, [1, 2]], tris[:, [2, 0]]], axis=0)
    e = np.sort(e, axis=1)
    uniq, counts = np.unique(e, axis=0, return_counts=True)
    return uniq, counts


def _check_watertight(v, tris):
    """Closed <=> every edge is used by exactly two faces. Boundary edges (count 1) and
    non-manifold edges (count >2) are DIFFERENT defects and are counted separately even
    though a single bool would hide that."""
    t0 = _now()
    uniq, counts = _undirected_edges(tris)
    boundary = int((counts == 1).sum())
    over = int((counts > 2).sum())
    ok = boundary == 0 and over == 0
    detail = {
        'edges': int(len(uniq)),
        'boundary_edges': boundary,
        'edges_in_more_than_2_faces': over,
        'edges_in_exactly_2_faces': int((counts == 2).sum()),
        'max_faces_per_edge': int(counts.max()) if len(counts) else 0,
    }
    return {'pass': bool(ok), 'detail': detail, 'ms': _ms(t0)}


def _check_edge_manifold(v, tris):
    t0 = _now()
    uniq, counts = _undirected_edges(tris)
    bad = np.nonzero(counts > 2)[0]
    detail = {
        'non_manifold_edges': int(len(bad)),
        'max_faces_per_edge': int(counts.max()) if len(counts) else 0,
        'examples': uniq[bad[:8]].tolist() if len(bad) else [],
    }
    return {'pass': bool(len(bad) == 0), 'detail': detail, 'ms': _ms(t0)}


def _check_vertex_manifold(v, tris):
    """The check that gets skipped. A vertex is manifold iff its LINK — the graph whose
    edges are the opposite edges of its incident triangles — is a single closed cycle.

    Edge-manifoldness does not imply it: glue two cones tip to tip and every edge is used
    by exactly two faces, the mesh is watertight and orientable, and yet the neighbourhood
    of the shared tip is two disks joined at a point, which no surface can be. That shows
    up here as a link with two components and nowhere else.

    Vectorised: link edges for all vertices at once are node-disjoint between different
    apexes (a link edge never joins two apexes), so ONE global connected-components pass
    over (apex, ring-vertex) nodes yields every vertex's fan count simultaneously.
    """
    t0 = _now()
    nv = len(v)
    apex = np.concatenate([tris[:, 0], tris[:, 1], tris[:, 2]])
    ring_a = np.concatenate([tris[:, 1], tris[:, 2], tris[:, 0]])
    ring_b = np.concatenate([tris[:, 2], tris[:, 0], tris[:, 1]])

    key_a = apex * nv + ring_a
    key_b = apex * nv + ring_b
    nodes, inv = np.unique(np.concatenate([key_a, key_b]), return_inverse=True)
    ia, ib = inv[: len(key_a)], inv[len(key_a) :]

    # link-node degree: in a closed fan every ring vertex is hit by exactly 2 link edges
    deg = np.bincount(np.concatenate([ia, ib]), minlength=len(nodes))
    node_apex = nodes // nv

    g = csr_matrix((np.ones(len(ia), np.int8), (ia, ib)), shape=(len(nodes), len(nodes)))
    ncomp, labels = connected_components(g, directed=False)

    # fans per apex = number of distinct component labels among that apex's link nodes
    pairs = np.unique(np.stack([node_apex, labels], axis=1), axis=0)
    fan_apex, fan_count = np.unique(pairs[:, 0], return_counts=True)
    fans = np.zeros(nv, np.int64)
    fans[fan_apex] = fan_count

    bad_deg_nodes = deg != 2
    open_fan = np.zeros(nv, bool)  # a link path, i.e. a boundary vertex
    over_fan = np.zeros(nv, bool)  # degree >2: non-manifold edge touching this vertex
    np.logical_or.at(open_fan, node_apex[deg == 1], True)
    np.logical_or.at(over_fan, node_apex[deg > 2], True)

    referenced = np.zeros(nv, bool)
    referenced[apex] = True
    pinched = referenced & (fans > 1)
    nonmanifold = referenced & (pinched | open_fan | over_fan)

    detail = {
        'vertices_referenced': int(referenced.sum()),
        'non_manifold_vertices': int(nonmanifold.sum()),
        'pinch_vertices_multi_fan': int(pinched.sum()),
        'boundary_vertices_open_fan': int(open_fan.sum()),
        'vertices_on_non_manifold_edge': int(over_fan.sum()),
        'max_fans_at_a_vertex': int(fans.max()) if nv else 0,
        'link_nodes_with_degree_not_2': int(bad_deg_nodes.sum()),
        'examples': np.nonzero(nonmanifold)[0][:8].tolist(),
    }
    return {'pass': bool(nonmanifold.sum() == 0), 'detail': detail, 'ms': _ms(t0)}


def _check_winding(v, tris):
    """Consistent winding: on a closed orientable surface each undirected edge is
    traversed once in each direction. A directed edge appearing twice means the two
    faces sharing it disagree about which way is out.

    Outward-ness is a SEPARATE question and is answered by signed volume (divergence
    theorem), per connected component — a correctly wound body with its eyeballs inverted
    is consistent and still wrong.
    """
    t0 = _now()
    de = np.concatenate([tris[:, [0, 1]], tris[:, [1, 2]], tris[:, [2, 0]]], axis=0)
    uniq, counts = np.unique(de, axis=0, return_counts=True)
    dup = int((counts > 1).sum())
    detail = {
        'directed_edges': int(len(de)),
        'duplicated_directed_edges': dup,
        'examples': uniq[np.nonzero(counts > 1)[0][:8]].tolist() if dup else [],
    }
    return {'pass': bool(dup == 0), 'detail': detail, 'ms': _ms(t0)}


def _signed_volume(v, tris):
    a, b, c = v[tris[:, 0]], v[tris[:, 1]], v[tris[:, 2]]
    return float(np.einsum('ij,ij->i', a, np.cross(b, c)).sum() / 6.0)


def _check_outward(v, tris, comp_labels, ncomp, winding_ok=None):
    """Do the normals point out of the shell? Signed volume, per connected component.

    THIS QUESTION IS ILL-POSED UNLESS THE WINDING IS ALREADY CONSISTENT, and answering it
    anyway was a real can't-fail path. Signed volume comes from the divergence theorem,
    which assumes the triangles form a coherently oriented boundary. On a mesh where some
    faces are reversed, the sum is not a volume of anything — it is the correct volume
    minus twice the contribution of the flipped subset. Flip a small fraction and the total
    stays comfortably positive, so this check returned `pass`.

    MEASURED 2026-08-08 by geom/anthro/mutation.py: reversing 4% of faces left
    t1_outward_normals passing, while t1_winding_consistent correctly failed. The 100%-
    flipped case never reached here at all — the measurement precondition refuses it — so
    between the two defences there was a band of partial inversions that nothing caught,
    which is exactly the shape of gap that survives review.

    The fix is not a better volume test. A partially flipped mesh has no outward direction
    to test, so the honest answer is UNMEASURABLE: refuse, name the reason, and let
    winding_consistent carry the failure it already detects.
    """
    t0 = _now()
    if winding_ok is False:
        return {
            'pass': None,
            'unmeasurable': True,
            'detail': {
                'reason': 'winding is inconsistent, so orientation is undefined and '
                'signed volume is not a volume. Fix winding_consistent first; '
                'this check cannot be evaluated until then, and reporting a '
                'pass here would be reporting on an ill-posed question.',
                'depends_on': 'winding_consistent',
            },
            'ms': _ms(t0),
        }
    per = []
    all_out = True
    for k in range(ncomp):
        sel = comp_labels[tris[:, 0]] == k
        if not sel.any():
            continue
        vol = _signed_volume(v, tris[sel])
        per.append(
            {'component': k, 'faces': int(sel.sum()), 'signed_volume_m3': round(vol, 9), 'outward': bool(vol > 0)}
        )
        all_out = all_out and vol > 0
    total = _signed_volume(v, tris)
    detail = {
        'total_signed_volume_m3': round(total, 9),
        'total_signed_volume_litres': round(total * 1000.0, 4),
        'per_component': per,
        'convention': 'positive signed volume == counter-clockwise front faces == outward normals',
    }
    return {'pass': bool(all_out), 'detail': detail, 'ms': _ms(t0)}


def _check_degenerate(v, faces, tris):
    t0 = _now()
    a, b, c = v[tris[:, 0]], v[tris[:, 1]], v[tris[:, 2]]
    area = 0.5 * np.linalg.norm(np.cross(b - a, c - a), axis=1)
    zero_area = np.nonzero(area < EPS_AREA_M2)[0]

    dup_pairs = cKDTree(v).query_pairs(EPS_DUPLICATE_M, output_type='ndarray')

    referenced = np.zeros(len(v), bool)
    referenced[np.asarray(faces).reshape(-1)] = True
    unref = np.nonzero(~referenced)[0]

    f = np.asarray(faces)
    repeated = np.zeros(len(f), bool)
    for i in range(f.shape[1]):
        for j in range(i + 1, f.shape[1]):
            repeated |= f[:, i] == f[:, j]

    detail = {
        'zero_area_faces': int(len(zero_area)),
        'min_triangle_area_m2': float(area.min()) if len(area) else None,
        'median_triangle_area_m2': float(np.median(area)) if len(area) else None,
        'duplicate_vertex_pairs': int(len(dup_pairs)),
        'duplicate_eps_m': EPS_DUPLICATE_M,
        'unreferenced_vertices': int(len(unref)),
        'faces_with_repeated_index': int(repeated.sum()),
        'examples_zero_area': zero_area[:8].tolist(),
        'examples_unreferenced': unref[:8].tolist(),
    }
    ok = len(zero_area) == 0 and len(dup_pairs) == 0 and len(unref) == 0 and not repeated.any()
    return {'pass': bool(ok), 'detail': detail, 'ms': _ms(t0)}


# ---------------------------------------------------------------------------------
# Components / Euler / genus
# ---------------------------------------------------------------------------------


def _components(v, tris):
    rows = np.concatenate([tris[:, 0], tris[:, 1], tris[:, 2]])
    cols = np.concatenate([tris[:, 1], tris[:, 2], tris[:, 0]])
    g = csr_matrix((np.ones(len(rows), np.int8), (rows, cols)), shape=(len(v), len(v)))
    return connected_components(g, directed=False)


def _check_euler(v, tris, comp_labels, ncomp):
    """Report the true Euler characteristic per component. We do NOT assert genus 0: a
    human cage may legitimately be higher genus if the mouth cavity connects through to
    the throat, and a mesh with eyes and a tongue as separate shells has chi = 2 per
    shell, so the whole-mesh number is a sum whose value depends on how many shells the
    exporter happened to include. Measure it, report it, let the caller decide.

    genus is only defined for a CLOSED orientable component; it is reported as None
    otherwise rather than as a misleading integer.
    """
    t0 = _now()
    per = []
    closed_all = True
    for k in range(ncomp):
        fsel = comp_labels[tris[:, 0]] == k
        if not fsel.any():
            continue
        t = tris[fsel]
        vi = np.unique(t)
        uniq, counts = _undirected_edges(t)
        chi = len(vi) - len(uniq) + len(t)
        closed = bool((counts == 2).all())
        closed_all = closed_all and closed
        genus = int((2 - chi) // 2) if (closed and chi % 2 == 0) else None
        per.append(
            {
                'component': k,
                'vertices': int(len(vi)),
                'edges': int(len(uniq)),
                'faces_tri': int(len(t)),
                'euler_chi': int(chi),
                'closed': closed,
                'genus': genus,
                'z_min': round(float(v[vi, 2].min()), 4),
                'z_max': round(float(v[vi, 2].max()), 4),
            }
        )
    uniq_all, _ = _undirected_edges(tris)
    chi_all = len(v) - len(uniq_all) + len(tris)
    detail = {
        'components': int(len(per)),
        'euler_chi_total': int(chi_all),
        'per_component': per,
        'note': 'chi is triangulation-invariant: splitting a quad adds one edge '
        'and one face, so the quad cage and its triangulation agree.',
    }
    return {'pass': bool(closed_all), 'detail': detail, 'ms': _ms(t0)}


def _tri_spheres(v, tris):
    """Per-triangle bounding sphere (centroid, max corner distance). The broad phase of
    both the self-intersection test and the ray tests is a query against these."""
    a, b, c = v[tris[:, 0]], v[tris[:, 1]], v[tris[:, 2]]
    cen = (a + b + c) / 3.0
    rad = np.max(np.linalg.norm(np.stack([a - cen, b - cen, c - cen], axis=1), axis=2), axis=1)
    return cen, rad


def _stride(n, k):
    """k evenly spread indices out of n, deterministic, no RNG, no duplicates."""
    if n <= k:
        return np.arange(n)
    return np.unique(np.linspace(0, n - 1, k).astype(np.int64))
