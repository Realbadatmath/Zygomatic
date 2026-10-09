# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Plane/mesh intersection, loop metrics, and the loop selection that excludes the arms.

Moved verbatim out of the old single-file measure.py (lines 517-799).
"""

import numpy as np

from zyg_workflows.geom.anthro.measure.constants import (
    PLANE_DEGENERATE_M,
    PLANE_NUDGE_M,
)
from zyg_workflows.geom.anthro.measure.topology import _topology


# ---------------------------------------------------------------------------------
# plane / mesh intersection, written here rather than delegated
# ---------------------------------------------------------------------------------
def slice_loops(v, faces, origin, normal, tri_mask=None):
    """Closed intersection contours of a plane with the cage.

    Returns (loops, info). Each loop is {'pts': (N,3), 'tris': triangle ids}, with pts in
    contour order so the perimeter is a plain consecutive-difference sum.

    Rolled by hand rather than taken from trimesh.section: trimesh's planar-section path
    returns a Path3D whose polygon handling wants shapely, which is not installed here.
    The tracing is exact anyway — each crossing EDGE yields exactly one point and each
    crossing triangle joins exactly two of them, so on an edge-manifold mesh every
    crossing point has degree exactly two and the loops fall out with no distance
    tolerance anywhere.
    """
    v = np.asarray(v, np.float64)
    topo = _topology(faces)
    E, uniq = topo['tri_edges'], topo['edges']
    mask = topo['body_tris'] if tri_mask is None else np.asarray(tri_mask, bool)

    n = np.asarray(normal, np.float64)
    n = n / np.linalg.norm(n)
    o = np.asarray(origin, np.float64)
    d = (v - o) @ n
    nudged = 0.0
    for _ in range(8):
        if float(np.abs(d).min()) > PLANE_DEGENERATE_M:
            break
        d = d - PLANE_NUDGE_M
        nudged += PLANE_NUDGE_M

    pos = d > 0
    cross = pos[uniq[:, 0]] != pos[uniq[:, 1]]
    ncross = cross[E].sum(axis=1)
    tsel = np.nonzero(mask & (ncross == 2))[0]
    info = {
        'plane_origin_m': [float(x) for x in o],
        'plane_normal': [float(x) for x in n],
        'plane_nudge_m': nudged,
        'crossing_triangles': int(len(tsel)),
    }
    if not len(tsel):
        return [], info

    pair = E[tsel][cross[E[tsel]]].reshape(-1, 2)
    nodes, seg = np.unique(pair, return_inverse=True)
    seg = seg.reshape(-1, 2)

    a, b = uniq[nodes, 0], uniq[nodes, 1]
    t = d[a] / (d[a] - d[b])
    P = v[a] + t[:, None] * (v[b] - v[a])
    # The arm skinning weight of the CROSSING POINT, interpolated along the same edge and
    # with the same parameter as the point itself. Taking the weight of the nearer vertex
    # instead would quantise the mask to the cage's edge length (8-20 mm here) exactly
    # where the trunk and the arm meet, which is the one place it has to be sharp.
    skin_w = topo['arm_skin_weight']
    A = None if skin_w is None else (skin_w[a] + t * (skin_w[b] - skin_w[a]))
    # The mesh vertex on the NEGATIVE side of each cut edge. Walking these in contour
    # order gives a coherent vertex ring — the row of cage vertices immediately below the
    # cut — which is what a MakeHuman measurement ring is. Picking "the nearest vertex to
    # each contour point" instead lets consecutive points alternate between the row above
    # and the row below, and the resulting zig-zag is LONGER than the contour it is
    # supposed to inscribe (measured: +49 mm on the male waist, +95 mm on the female
    # ankle, which would have inverted the hull-vs-polyline finding).
    below = np.where(d[a] < 0, a, b)

    k = len(nodes)
    nbr = np.full((k, 2), -1, np.int64)
    deg = np.zeros(k, np.int64)
    for _s, (i, j) in enumerate(seg):
        if deg[i] > 1 or deg[j] > 1:
            raise RuntimeError(
                'contour node degree exceeded 2 while tracing a slice — '
                'the mesh is not edge-manifold at this plane, so the '
                'contour cannot be ordered. Refusing to guess.'
            )
        nbr[i, deg[i]] = j
        deg[i] += 1
        nbr[j, deg[j]] = i
        deg[j] += 1
    if (deg != 2).any():
        raise RuntimeError(
            '%d contour nodes have degree %s, not 2 — the intersection is '
            'an open curve, which a closed shell cannot produce.'
            % (int((deg != 2).sum()), sorted(set(deg[deg != 2].tolist())))
        )

    node_tris = [[] for _ in range(k)]
    for s, (i, j) in enumerate(seg):
        node_tris[i].append(tsel[s])
        node_tris[j].append(tsel[s])

    seen = np.zeros(k, bool)
    loops = []
    for start in range(k):
        if seen[start]:
            continue
        order = []
        prev, cur = -1, start
        while True:
            seen[cur] = True
            order.append(cur)
            nx = nbr[cur, 0] if nbr[cur, 0] != prev else nbr[cur, 1]
            prev, cur = cur, nx
            if cur == start:
                break
            if seen[cur]:
                raise RuntimeError(
                    'slice tracing re-entered a visited node without closing — degenerate contour topology.'
                )
        oi = np.asarray(order, np.int64)
        tset = np.unique(np.concatenate([node_tris[i] for i in order]))
        loops.append({'pts': P[oi], 'tris': tset, 'ring_below': below[oi], 'arm_w': None if A is None else A[oi]})
    info['loops'] = len(loops)
    info['arm_mask'] = 'unavailable' if A is None else 'per-contour-point'
    return loops, info


def _plane_basis(normal, u_hint=None):
    n = np.asarray(normal, np.float64)
    n = n / np.linalg.norm(n)
    if u_hint is None:
        u_hint = np.eye(3)[int(np.argmin(np.abs(n)))]
    u = np.asarray(u_hint, np.float64) - n * float(np.asarray(u_hint, np.float64) @ n)
    nu = np.linalg.norm(u)
    if nu < 1e-9:
        u = np.eye(3)[int(np.argmin(np.abs(n)))]
        u = u - n * (u @ n)
        nu = np.linalg.norm(u)
    u = u / nu
    return u, np.cross(n, u)


def _shoelace(xy):
    """Signed area of an ordered 2-D polygon. Written out rather than using np.cross,
    which deprecated the 2-vector form in numpy 2.0."""
    x, y = xy[:, 0], xy[:, 1]
    return float((x * np.roll(y, -1) - np.roll(x, -1) * y).sum() / 2.0)


def loop_metrics(loop, normal, u_hint=None):
    """Perimeter under all three girth conventions, plus area and in-plane extents.

    contour_mm : the exact cross-section perimeter, following every concavity.
    hull_mm    : the convex hull of the same contour, in-plane. THE TAUT-TAPE EMULATION.
    area_mm2   : enclosed area, shoelace, used only to pick the torso loop out of a slice.

    Note the ordering that actually holds and is easy to get backwards: for a closed plane
    curve the convex hull is the SHORTEST closed curve enclosing it, so
    hull_mm <= contour_mm, with equality only when the section is already convex. A tape
    pulled taut bridges the concavities, which is exactly the hull, and that is why a
    contour perimeter overstates a tape measurement rather than understating it.
    """
    p = np.asarray(loop['pts'], np.float64)
    n = np.asarray(normal, np.float64)
    n = n / np.linalg.norm(n)
    u, w = _plane_basis(n, u_hint)
    xy = np.stack([p @ u, p @ w], axis=1)
    seg = np.roll(p, -1, axis=0) - p
    contour = float(np.linalg.norm(seg, axis=1).sum())
    area = float(abs(_shoelace(xy)))
    hull = None
    hull_area = None
    if len(xy) >= 3:
        from scipy.spatial import ConvexHull, QhullError

        try:
            h = ConvexHull(xy)
            hp = xy[h.vertices]
            hull = float(np.linalg.norm(np.roll(hp, -1, axis=0) - hp, axis=1).sum())
            hull_area = float(h.volume)
        except QhullError:
            hull = None
    return {
        'contour_m': contour,
        'hull_m': hull,
        'area_m2': area,
        'hull_area_m2': hull_area,
        'n_points': int(len(p)),
        'centroid': [float(x) for x in p.mean(axis=0)],
        'x_extent_m': float(p[:, 0].max() - p[:, 0].min()),
        'y_extent_m': float(p[:, 1].max() - p[:, 1].min()),
        'u_extent_m': float(xy[:, 0].max() - xy[:, 0].min()),
        'w_extent_m': float(xy[:, 1].max() - xy[:, 1].min()),
    }


def polyline_girth(v, faces, loop, normal=None, origin=None):
    """MakeHuman/anny convention: sum of straight 3D chords along a mesh VERTEX RING.

    Reproduces what anny.anthropometry.Anthropometry.waist_circumference does — roll the
    ring, sum the norms — for an arbitrary site, using the coherent ring of cage vertices
    immediately below the cut (see slice_loops for why "nearest vertex" is the wrong
    ring).

    IT IS NOT SAFE TO ASSUME THIS IS SHORTER THAN THE CONTOUR. A vertex ring is inscribed
    only if it is planar, and a cage ring is not: it undulates vertically, and the chord
    sum charges for that undulation. Returns the ring's out-of-plane spread alongside the
    length so the caller can see when that is what it is looking at.
    """
    v = np.asarray(v, np.float64)
    ring = np.asarray(loop.get('ring_below'))
    if ring is None or not len(ring):
        return None, np.asarray([], np.int64), None, None
    keep = np.concatenate([[True], ring[1:] != ring[:-1]])
    ring = ring[keep]
    if len(ring) > 1 and ring[0] == ring[-1]:
        ring = ring[:-1]
    if len(ring) < 3:
        return None, ring, None, None
    q = v[ring]
    length = float(np.linalg.norm(np.roll(q, -1, axis=0) - q, axis=1).sum())
    spread = None
    planar = None
    if normal is not None and origin is not None:
        n = np.asarray(normal, np.float64)
        n = n / np.linalg.norm(n)
        s = (q - np.asarray(origin, np.float64)) @ n
        spread = float(s.max() - s.min())
        # The same ring flattened into the slice plane. Isolates how much of the polyline's
        # excess over the contour is the vertical staircase (3D length minus this) and how
        # much is genuine in-plane shape.
        f = q - np.outer(s, n)
        planar = float(np.linalg.norm(np.roll(f, -1, axis=0) - f, axis=1).sum())
    return length, ring, spread, planar


# ---------------------------------------------------------------------------------
# loop selection — this is where the attached arms are dealt with
# ---------------------------------------------------------------------------------
def _select_loop(loops, policy, anchor=None):
    if not loops:
        return None, 'no contour at this plane'
    if policy == 'largest':
        areas = [abs(_shoelace(l['pts'][:, :2])) for l in loops]
        return int(np.argmax(areas)), 'largest enclosed area of %d loops' % len(loops)
    if policy == 'nearest':
        if anchor is None:
            raise ValueError("select='nearest' needs an anchor point")
        a = np.asarray(anchor, np.float64)
        d = [float(np.linalg.norm(l['pts'].mean(axis=0) - a)) for l in loops]
        return int(np.argmin(d)), (
            'loop centroid nearest the anchor (%.1f mm) of %d loops' % (min(d) * 1000, len(loops))
        )
    raise ValueError('unknown loop selection policy %r' % policy)


def _arm_merge_check(faces, loops, k):
    """Has an arm merged into the selected torso loop at this plane?

    Topological, not geometric. A horizontal plane through an A-posed chest cuts three
    closed loops: the torso and one per arm. If both arms are accounted for as loops of
    their own, the torso loop is arm-free by construction and the few axillary triangles
    an arm mask flags inside it are mask overspill, not a merge. When the arms fuse to
    the trunk the loop count collapses and those loops disappear — that is the signal.
    Measured on the male original: 3 loops with 4 / 43 / 43 arm triangles at 0.7192 of
    stature (clean), collapsing to 1 loop with 44 at 0.75 (merged).

    The DECIDER is the skinning-weight mask when the rig is readable, because the
    morph-support mask overspills: measured on the male original it reaches to |x| = 225 mm
    while the torso's own chest silhouette reaches 242 mm, so it reports 4 arm triangles
    inside a perfectly clean thelion loop on the male, cornelis and abel where the
    skinning mask reports 0. Both counts are returned, so a disagreement is visible rather
    than resolved silently.
    """
    topo = _topology(faces)
    morph = topo['arm_tris']
    skin = topo['arm_skin_tris']
    use = morph if skin is None else skin
    own = sum(1 for i, l in enumerate(loops) if i != k and use[l['tris']].any())
    inside = int(use[loops[k]['tris']].sum())
    return {
        'arm_triangles_in_loop': inside,
        'arm_loops_present': own,
        'merged': bool(inside and own < 2),
        'arm_triangle_mask': (
            'morph-support (FALLBACK: the rig was unreadable)' if skin is None else 'skinning weights'
        ),
        'arm_triangles_in_loop_morph_support': int(morph[loops[k]['tris']].sum()),
    }
