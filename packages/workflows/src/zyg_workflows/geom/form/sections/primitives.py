# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""sections.primitives — section primitives, mesh/rig access and the status roll-up.

Moved verbatim from geom/form/sections.py; no logic, numbers or comments changed.
"""

import math

import numpy as np

from .constants import (
    FAIL,
    LMK,
    MEA,
    MS,
    NGON_ORDERS,
    NGON_THETA_STEPS,
    NOT_APPLICABLE,
    PASS,
    REPORT,
    UNMEASURABLE,
    WARN,
)


# =================================================================================
# section primitives — geometry only, no anatomy, no thresholds
# =================================================================================
def _res(status, claim, source, provenance, explain, **evidence):
    """One predicate's verdict, in geom.anthro.gates' record shape."""
    return {
        'status': status,
        'claim': claim,
        'source': source,
        'provenance': provenance,
        'explain': explain,
        'evidence': evidence,
    }


def _plane_xy(pts, normal, u_hint):
    """Contour points in the plane's own 2-D frame, using measure.py's basis.

    Returns (xy, u, w). For a horizontal plane with u_hint = +x this gives xy[:,0] = the
    subject's left-right coordinate and xy[:,1] = the posterior coordinate, because the
    cage's measured frame is LPS (+x left, +y posterior, +z superior — landmarks.py
    frame_report). Both are checked at run time by _frame_check rather than assumed.
    """
    u, w = MEA._plane_basis(np.asarray(normal, np.float64), np.asarray(u_hint, np.float64))
    p = np.asarray(pts, np.float64)
    return np.stack([p @ u, p @ w], axis=1), u, w


def frame_check(v, faces):
    """Confirm the cage's frame is the one this module's 'front' and 'left' assume.

    EVERY VERDICT IN THIS FILE IS A SIGN, so a frame that is not the measured one does not
    degrade the numbers, it inverts them. The frame is not re-derived here: landmarks.py's
    frame_report establishes +x subject-left, +y posterior, +z superior by probing oriented
    morph targets, and a locally computed second opinion could disagree with the shipped
    one. Returns (ok, report). A caller that gets ok=False must treat every
    anterior/posterior and medial/lateral verdict in this module as VOID, not as noisy.
    """
    rep = LMK.frame_report(np.asarray(v, np.float64), faces)
    ok = (
        rep['up_axis'] == 'z'
        and rep['up_sign'] > 0
        and rep['anterior_axis'] == 'y'
        and rep['anterior_sign'] < 0
        and rep['subject_left_axis'] == 'x'
        and rep['subject_left_sign'] > 0
    )
    return bool(ok), rep


def _menger_curvature(xy):
    """Discrete curvature at every point of a CLOSED ordered plane curve.

    Menger curvature: the reciprocal radius of the circle through three consecutive points,
    4*area / (|ab||bc||ca|). Chosen over a finite-difference second derivative because the
    contour points are plane-triangle intersections and are therefore UNEVENLY SPACED —
    circumcircle curvature is exact for any three points and needs no parameterisation.
    """
    p = np.asarray(xy, np.float64)
    a, b, c = np.roll(p, 1, axis=0), p, np.roll(p, -1, axis=0)
    ab = np.linalg.norm(b - a, axis=1)
    bc = np.linalg.norm(c - b, axis=1)
    ca = np.linalg.norm(a - c, axis=1)
    cross = (b[:, 0] - a[:, 0]) * (c[:, 1] - a[:, 1]) - (b[:, 1] - a[:, 1]) * (c[:, 0] - a[:, 0])
    denom = ab * bc * ca
    k = np.zeros(len(p))
    ok = denom > 0
    k[ok] = 4.0 * 0.5 * np.abs(cross[ok]) / denom[ok]
    return k


def _polygon_area(xy):
    x, y = np.asarray(xy, np.float64)[:, 0], np.asarray(xy, np.float64)[:, 1]
    return float(abs((x * np.roll(y, -1) - np.roll(x, -1) * y).sum() / 2.0))


def _split_front_back(xy):
    """Split a closed section at its two extreme-u points into an anterior and a posterior
    arc, and describe each three different ways.

    THE SPLIT has no free parameter: the two points of maximum and minimum u (the section's
    widest pair) are where the surface turns from front to back, and they belong to both
    arcs. Which arc is anterior is decided by the mean w of its own points, +w being
    posterior in the cage's measured LPS frame.

    THREE READINGS OF 'FLATTER', because AFS p.24's phrase is not sharp and pretending it is
    would be the dishonest move. All three are returned; the gate names which one it takes
    its verdict from and why.

      curvature  median of the normalised Menger curvature over the arc's INTERIOR points,
                 normalised by 2/chord so a semicircle scores exactly 1.0. This is the only
                 one of the three that is a statement about the CONTOUR rather than about
                 its extent, which is why the gate uses it. The two split points are
                 excluded because they are corners SHARED by both arcs, so including them
                 would put the same spike in both numerators. The median rather than the
                 mean because a mesh contour carries tessellation spikes and the median is
                 the canonical robust centre, not a tuned trim.
      camber     max |deviation from the chord| / chord. This is the literal "how far from a
                 straight line" reading, but on a torso it is dominated by how far the
                 breast or the buttock projects, which is a DEPTH claim, not a flatness one.
      fullness   area between arc and chord, over chord * sagitta. How much of its own
                 bounding box the arc fills: 1.0 for a flat plate, pi/4 = 0.785 for a
                 semicircle, 0.5 for a wedge. A shape statistic, scale free, but blind to a
                 flat arc with rounded shoulders versus a shallow round one.
    """
    p = np.asarray(xy, np.float64)
    n = len(p)
    i0, i1 = int(np.argmin(p[:, 0])), int(np.argmax(p[:, 0]))
    if i0 == i1:
        return None
    kappa = _menger_curvature(p)

    def arc(i, j):
        return np.arange(i, j + 1) if j > i else np.concatenate([np.arange(i, n), np.arange(0, j + 1)])

    p0, p1 = p[i0], p[i1]
    d = p1 - p0
    chord = float(np.linalg.norm(d))
    if chord <= 0:
        return None
    nrm = np.array([-d[1], d[0]]) / chord
    out = {}
    for name, idx in (('A', arc(i0, i1)), ('B', arc(i1, i0))):
        q = p[idx]
        s = (q - p0) @ nrm
        sag = float(np.abs(s).max())
        # area between the arc and its chord: the shoelace of the closed polygon made of
        # the arc plus the chord. Exact, and immune to the arc doubling back in u, which a
        # trapezoid integration over u is not.
        area = _polygon_area(q)
        interior = idx[1:-1]
        kk = kappa[interior] * (chord / 2.0)
        out[name] = {
            'mean_w': float(q[:, 1].mean()),
            'points': int(len(idx)),
            'chord_m': chord,
            'sagitta_m': sag,
            'camber': sag / chord,
            'arc_over_chord': float(np.linalg.norm(np.diff(q, axis=0), axis=1).sum() / chord),
            'fullness': float(area / max(chord * sag, 1e-15)),
            'median_norm_curvature': float(np.median(kk)) if len(kk) else None,
        }
    front, back = ('A', 'B') if out['A']['mean_w'] < out['B']['mean_w'] else ('B', 'A')
    return {
        'front': out[front],
        'back': out[back],
        'split_points_uw': [[float(x) for x in p0], [float(x) for x in p1]],
        'split_rule': 'the two extreme-u (widest) points of the section; no parameter',
    }


def _hull_gaps(xy, min_depth):
    """Concavities of a closed section: arcs that dip inside their own convex hull.

    Returns one record per gap with its maximum depth, its arc midpoint and its length.
    A gap counts as a CONCAVITY only if it is deeper than `min_depth`; that floor is the
    cage's measured relief null (RELIEF_NULL_FRAC of stature) and nothing else — a dip
    shallower than the tessellation's own noise is not a feature, and calling it one would
    manufacture anatomy out of quantisation.

    The hull vertices of a simple closed curve appear in the curve's own cyclic order, so
    sorting them by contour index and walking consecutive pairs recovers each gap's arc
    with no matching heuristics.
    """
    from scipy.spatial import ConvexHull, QhullError

    p = np.asarray(xy, np.float64)
    try:
        h = ConvexHull(p)
    except QhullError as e:  # pragma: no cover
        return None, 'convex hull failed on this section: %s' % e
    hv = np.sort(h.vertices)
    gaps = []
    k = len(hv)
    for a in range(k):
        i, j = int(hv[a]), int(hv[(a + 1) % k])
        idx = np.arange(i + 1, j) if j > i else np.concatenate([np.arange(i + 1, len(p)), np.arange(0, j)])
        if not len(idx):
            continue
        p0, p1 = p[i], p[j]
        d = p1 - p0
        L = float(np.linalg.norm(d))
        if L <= 0:
            continue
        nrm = np.array([-d[1], d[0]]) / L
        dev = np.abs((p[idx] - p0) @ nrm)
        m = int(np.argmax(dev))
        gaps.append(
            {
                'depth_m': float(dev.max()),
                'chord_m': L,
                'apex_uw': [float(x) for x in p[idx][m]],
                'points': int(len(idx)),
            }
        )
    gaps.sort(key=lambda g: -g['depth_m'])
    deep = [g for g in gaps if g['depth_m'] > min_depth]
    return {
        'all': gaps,
        'resolved': deep,
        'n_all': len(gaps),
        'n_resolved': len(deep),
        'floor_m': float(min_depth),
    }, None


def _ngon_residual(xy, order, theta_steps=NGON_THETA_STEPS):
    """How well a regular `order`-gon (or a circle, order=None) describes this section.

    THE FAIRNESS PROBLEM, and how it is removed. A hexagon fitted with free vertices has 12
    parameters against a circle's 3, so it wins by construction and the comparison would be
    meaningless. Here the section is first WHITENED — translated to its centroid and
    transformed by C^(-1/2) of its own covariance — which removes centre and ellipticity
    from the data rather than from the model. What is left for the model to explain is pure
    SHAPE, and every member of the family (every N, and the circle) is then fitted with
    exactly ONE free parameter, a rotation, and one closed-form scale. The circle has no
    rotation at all, so if anything the family is handicapped in the circle's favour; the
    measured result is that the circle still wins on this cage, which makes the finding
    stronger, not weaker.

    The gauge used is the polygon's support function, max_k <p, n_k>, which equals the
    apothem exactly on the boundary; for the circle the same expression degenerates to |p|,
    so N and the circle are scored by ONE formula and not by two.

    Points are weighted by their own adjacent arc length, so the residual is a curve
    integral and not a vote of the tessellation's point density.
    """
    p = np.asarray(xy, np.float64)
    c = p.mean(axis=0)
    q = p - c
    C = (q.T @ q) / len(q)
    ev, V = np.linalg.eigh(C)
    if float(ev.min()) <= 0:
        return None
    W = V @ np.diag(1.0 / np.sqrt(ev)) @ V.T
    z = q @ W.T
    seg = np.linalg.norm(np.roll(z, -1, axis=0) - z, axis=1)
    wt = 0.5 * (seg + np.roll(seg, 1))
    wt = wt / wt.sum()

    def score(d):
        a = float((wt * d).sum())
        if a <= 0:
            return None
        return float(math.sqrt(float((wt * (d - a) ** 2).sum())) / a), a

    if order is None:
        s = score(np.linalg.norm(z, axis=1))
        return None if s is None else {'order': None, 'rel_residual': s[0], 'apothem': s[1], 'theta': None}
    best = None
    for t in range(theta_steps):
        th = 2.0 * math.pi / order * (t / float(theta_steps))
        ang = th + 2.0 * math.pi * np.arange(order) / order
        nrm = np.stack([np.cos(ang), np.sin(ang)], axis=1)
        s = score((z @ nrm.T).max(axis=1))
        if s is not None and (best is None or s[0] < best[0]):
            best = (s[0], s[1], th)
    if best is None:
        return None
    return {'order': int(order), 'rel_residual': best[0], 'apothem': best[1], 'theta': best[2]}


def _shape_family(xy):
    """The whole family at once: every N in NGON_ORDERS plus the circle, plus the argmin."""
    fits = {}
    for n in NGON_ORDERS:
        f = _ngon_residual(xy, n)
        if f is not None:
            fits[n] = f['rel_residual']
    cf = _ngon_residual(xy, None)
    if cf is None or not fits:
        return None
    best = min(fits.items(), key=lambda kv: (kv[1], kv[0]))
    return {
        'residual_by_order': {str(k): v for k, v in sorted(fits.items())},
        'residual_circle': cf['rel_residual'],
        'best_order': int(best[0]),
        'best_residual': float(best[1]),
        'hexagon_residual': float(fits.get(6, float('nan'))),
        'hexagon_beats_circle': bool(fits.get(6, float('inf')) < cf['rel_residual']),
    }


# =================================================================================
# mesh / rig access
# =================================================================================
def _frame(v):
    v = np.asarray(v, np.float64)
    zmin = float(v[:, 2].min())
    return zmin, float(v[:, 2].max() - zmin)


_RIG = {}


def bone_ends(phenotype, local_changes=None):
    """(names, heads, tails) for one recipe, IN THE SAME FRAME AS _build_mesh's vertices.

    This is not cosmetic. anny returns rest_bone_heads/tails in the REST space, which is not
    the space the mesh comes back in — measured on the neutral, rest_vertices and vertices
    differ by up to 64.6 mm — so composing the rest heads with anything but anny's own
    get_bone_ends puts the skeleton tens of millimetres away from the skin it is supposed to
    sit inside. Every rig-anchored number in this module goes through here.
    """
    import torch

    m = MS._model()
    kw = {'phenotype_kwargs': dict(phenotype)}
    if local_changes:
        kw['local_changes_kwargs'] = dict(local_changes)
    with torch.no_grad():
        out = m(**kw)
        h, t = m.get_bone_ends(
            out['rest_bone_heads'], out['rest_bone_tails'], out['rest_bone_poses'], out['bone_poses']
        )
    names = [str(n) for n in MS._bone_names(m)]
    return names, h[0].numpy().astype(np.float64), t[0].numpy().astype(np.float64)


def segment_weight(substrings):
    """Per-vertex summed skinning weight on the bones whose name contains any substring.

    Same construction and the same 0.5 majority rule as
    geom.anthro.measure.arm_skin_weights, and the same refusal discipline: returns
    (None, reason) when the rig cannot be read, never a silent zero. A silently zero mask is
    a mask that is not running.
    """
    key = tuple(sorted(substrings))
    if key in _RIG:
        return _RIG[key]
    try:
        m = MS._model()
        names = [str(n).lower() for n in MS._bone_names(m)]
        sel = np.array([any(k in nm for k in key) for nm in names])
        w = np.asarray(m.vertex_bone_weights.detach().cpu().numpy(), np.float64)
        i = np.asarray(m.vertex_bone_indices.detach().cpu().numpy(), np.int64)
    except Exception as e:  # noqa: BLE001
        _RIG[key] = (None, 'the anny rig could not be read: %s' % e)
        return _RIG[key]
    if not sel.any():
        _RIG[key] = (None, 'no bone name contains any of %s, so the mask would pass every vertex through' % (key,))
        return _RIG[key]
    _RIG[key] = ((w * sel[i]).sum(axis=1), None)
    return _RIG[key]


def _section(v, faces, origin, normal, u_hint, select='largest', anchor=None):
    """One plane, one selected loop, in measure.py's slicer and measure.py's conventions.

    Nothing is recomputed here: slice_loops does the exact, tolerance-free tracing,
    _select_loop applies the shipped selection policy, loop_metrics supplies the perimeter
    and area under the shipped girth conventions, and _split_arm_points / _arm_merge_check
    supply the shipped arm rules.
    """
    loops, info = MEA.slice_loops(v, faces, origin, normal)
    if not loops:
        return None, {'reason': 'no contour at this plane', **info}
    if select == 'largest':
        k, why = MEA._select_loop(loops, 'largest')
    else:
        k, why = MEA._select_loop(loops, 'nearest', anchor)
    loop = loops[k]
    xy, u, w = _plane_xy(loop['pts'], normal, u_hint)
    keep, ndrop, wmax = MEA._split_arm_points(loop)
    merge = MEA._arm_merge_check(faces, loops, k)
    met = MEA.loop_metrics(loop, normal, u_hint)
    return {
        'loop': loop,
        'xy': xy,
        'u': u,
        'w': w,
        'metrics': met,
        'loops_found': len(loops),
        'selected_by': why,
        'index': k,
        'arm_points_dropped': None if keep is None else int(ndrop),
        'arm_mask_available': keep is not None,
        'arm_max_weight': None if wmax is None else float(wmax),
        'arm_triangles_in_loop': merge['arm_triangles_in_loop'],
        'arm_loops_present': merge['arm_loops_present'],
        'arm_merged': bool(merge['merged']),
    }, None


def _torso_section_valid(sec):
    """Is this plane a section OF THE TRUNK, or of the trunk with an arm welded to it?

    measure.py's own rule, restated: a horizontal plane through an A-posed body cuts the
    torso and each arm as separate closed loops, so if any arm SURFACE is inside the
    selected loop the arm has fused and the section is not a trunk section. Refuse; do not
    widen a window, do not delete points from the middle of an ordered contour (a perimeter
    and a curvature profile have no meaning across a hole).
    """
    if not sec['arm_mask_available']:
        return False, (
            'the skinning-weight arm mask is unavailable on this rig, so whether '
            'an arm is inside this contour cannot be established. Refusing '
            'rather than assuming it is not.'
        )
    if sec['arm_points_dropped']:
        return False, (
            '%d contour points of the selected loop carry a majority arm '
            'skinning weight, so an arm has fused to the trunk at this plane and '
            'the section shape would be a trunk-plus-arm shape' % sec['arm_points_dropped']
        )
    if sec['arm_triangles_in_loop']:
        return False, (
            '%d triangles of the selected loop lie inside the arm mask with only '
            "%d arm loops of their own at this plane (measure.py's merge test)"
            % (sec['arm_triangles_in_loop'], sec['arm_loops_present'])
        )
    return True, None


# =================================================================================
# roll-up and entry point
# =================================================================================
_ORDER = {FAIL: 0, WARN: 1, UNMEASURABLE: 2, REPORT: 3, PASS: 4, NOT_APPLICABLE: 5}


def _rollup(claims):
    st = [c['status'] for c in claims.values()]
    if not st:
        return UNMEASURABLE
    return min(st, key=lambda s: _ORDER.get(s, 9))
