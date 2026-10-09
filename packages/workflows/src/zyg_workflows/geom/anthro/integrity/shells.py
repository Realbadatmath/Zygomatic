# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""integrity.shells — Shell inventory and containment: what the separate shells ARE, and where they sit."""

import numpy as np
from scipy.spatial import ConvexHull
from zyg_workflows.geom.anthro.integrity.constants import (
    EPS_NORMAL,
    EPS_PLANE_M,
    HULL_VERIFY_TOL_M,
    MAX_SHELLS_ANALYSED,
    MIDLINE_FRAC_OF_STATURE,
    SHELL_SIGNATURES,
    _ms,
    _now,
)
from zyg_workflows.geom.anthro.integrity.mesh_checks import _tri_spheres

# ---------------------------------------------------------------------------------
# Shell inventory and containment: what the separate shells ARE, and where they sit
# ---------------------------------------------------------------------------------


def _fibonacci_directions(n):
    """n near-uniform unit directions, deterministic and RNG-free. Reproducibility is not
    a nicety here: an escape fraction that moves between runs cannot be a threshold."""
    k = np.arange(n, dtype=np.float64) + 0.5
    z = 1.0 - 2.0 * k / n
    r = np.sqrt(np.maximum(0.0, 1.0 - z * z))
    phi = np.pi * (1.0 + 5.0**0.5) * k
    return np.stack([r * np.cos(phi), r * np.sin(phi), z], axis=1)


def _winding_numbers(v, tris, pts, chunk=8):
    """Generalised winding number of a closed triangle soup at each query point.

    Van Oosterom & Strackee's signed solid angle, summed over every triangle and divided
    by 4*pi. For a closed, consistently wound surface this is exactly 1 inside and 0
    outside, with no ray to shoot and therefore no direction to get unlucky with — the
    failure mode of ray parity (a ray grazing an edge or hitting a vertex) has no analogue
    here. `_ray_crossings` is still run alongside it on a few probes, because two
    independent methods agreeing is evidence and one method asserting is not.
    """
    a, b, c = v[tris[:, 0]], v[tris[:, 1]], v[tris[:, 2]]
    out = np.zeros(len(pts))
    for s in range(0, len(pts), chunk):
        p = pts[s : s + chunk][:, None, :]
        A, B, C = a[None] - p, b[None] - p, c[None] - p
        la = np.linalg.norm(A, axis=2)
        lb = np.linalg.norm(B, axis=2)
        lc = np.linalg.norm(C, axis=2)
        num = np.einsum('nij,nij->ni', A, np.cross(B, C))
        den = (
            la * lb * lc
            + np.einsum('nij,nij->ni', A, B) * lc
            + np.einsum('nij,nij->ni', B, C) * la
            + np.einsum('nij,nij->ni', C, A) * lb
        )
        out[s : s + chunk] = np.arctan2(num, den).sum(axis=1) * 2.0
    return out / (4.0 * np.pi)


def _ray_crossings(v, tris, origin, dirs, spheres=None):
    """Forward crossing count of the surface, for every ray leaving ONE origin.

    Used for two things: an independent parity cross-check of the winding number, and the
    escape test — a ray with zero crossings reached infinity, which is what "this point can
    see open sky" means.

    Broad phase: a ray can only hit a triangle whose bounding sphere it enters, and for a
    fixed origin that test is one small gemm plus one comparison for ALL directions at
    once (the cosine of the angle to the sphere's centre against the cosine of its angular
    radius). It cannot drop a hit, because the sphere encloses the triangle, and it cuts
    the exact Moller-Trumbore test from 26,692 triangles per ray to a few dozen. VERIFIED
    2026-08-05 against a brute-force pass over every triangle: 7,520 rays on the four
    issued cages — every non-body vertex, plus the origin, plus a point 2 m away, over 44
    directions — 0 disagreements, 4.8x faster.
    """
    a, b, c = v[tris[:, 0]], v[tris[:, 1]], v[tris[:, 2]]
    cen, rad = spheres if spheres is not None else _tri_spheres(v, tris)
    e1, e2 = b - a, c - a

    u = cen - origin
    lu = np.linalg.norm(u, axis=1)
    safe = np.where(lu > 0.0, lu, 1.0)
    engulfs = lu <= rad  # origin inside the sphere: any direction
    cos_half = np.where(engulfs, -1.0, np.sqrt(np.maximum(0.0, 1.0 - (rad / safe) ** 2)))
    proj = (dirs @ u.T) / safe[None, :]  # (D, F) cosine to each sphere centre
    cand = proj >= cos_half[None, :]

    out = np.zeros(len(dirs), np.int64)
    for i in range(len(dirs)):
        idx = np.nonzero(cand[i])[0]
        if not len(idx):
            continue
        d = dirs[i]
        E1, E2, A = e1[idx], e2[idx], a[idx]
        P = np.cross(np.broadcast_to(d, E2.shape), E2)
        det = np.einsum('ij,ij->i', P, E1)
        ok = np.abs(det) > EPS_NORMAL
        inv = np.where(ok, 1.0 / np.where(ok, det, 1.0), 0.0)
        T = origin - A
        uu = np.einsum('ij,ij->i', T, P) * inv
        Q = np.cross(T, E1)
        ww = (Q @ d) * inv
        tt = np.einsum('ij,ij->i', Q, E2) * inv
        out[i] = int((ok & (uu >= 0.0) & (ww >= 0.0) & (uu + ww <= 1.0) & (tt > EPS_PLANE_M)).sum())
    return out


def _envelope_margin(pts, A, b, budget=2000000):
    """Signed distance from each point to the convex envelope: >0 outside, <0 inside.

    The hull's own half-space form (unit normals, so the value is metres) maxed over
    facets. Chunked on a fixed element budget because points x facets is the only thing
    here that can get large, and a cage that shattered into a noisy hull is exactly when
    this must still return.
    """
    p = np.asarray(pts, np.float64).reshape(-1, 3)
    out = np.empty(len(p))
    step = max(1, int(budget // max(len(b), 1)))
    for s in range(0, len(p), step):
        out[s : s + step] = (p[s : s + step] @ A.T + b).max(axis=1)
    return out


def _convex_envelope(body_pts):
    """The body's convex hull as half-spaces, VERIFIED against the points it was built on.

    This is the discriminator that replaced a tuned escape fraction (see
    ENVELOPE_ESCAPE_MAX_FRACTION). It answers one question exactly — is this point inside
    the body's own envelope, i.e. in a concavity of the body such as the mouth or an eye
    socket, or has it left the envelope altogether — and it answers it with a signed
    distance in metres rather than a fraction near a threshold.

    qhull is not taken on trust: the returned half-spaces must contain every body vertex
    to HULL_VERIFY_TOL_M or the envelope is declared UNAVAILABLE and the caller must
    report 'unresolved' rather than fall back to a benign verdict. A degenerate input
    (all points coplanar, fewer than 4 points) raises inside qhull and lands in the same
    place, with the exception text carried into the payload.
    """
    p = np.asarray(body_pts, np.float64)
    try:
        hull = ConvexHull(p)
    except Exception as exc:  # QhullError, ValueError, MemoryError
        return {
            'available': False,
            'facets': None,
            'verified': False,
            'body_vertices_max_margin_m': None,
            'reason': 'convex hull could not be built: %s: %s' % (type(exc).__name__, exc),
        }
    A = np.ascontiguousarray(hull.equations[:, :3], np.float64)
    b = np.ascontiguousarray(hull.equations[:, 3], np.float64)
    worst = float(_envelope_margin(p, A, b).max())
    ok = worst <= HULL_VERIFY_TOL_M
    return {
        'available': bool(ok),
        'A': A,
        'b': b,
        'facets': int(len(b)),
        'verified': bool(ok),
        'body_vertices_max_margin_m': worst,
        'reason': None
        if ok
        else (
            'the hull qhull returned does not contain every body vertex (worst margin '
            '%.3e m > %.3e m), so it cannot be used to decide what is inside it' % (worst, HULL_VERIFY_TOL_M)
        ),
        'method': 'scipy.spatial.ConvexHull (qhull) half-spaces, unit normals, then '
        'verified to contain every body vertex to %.0e m' % HULL_VERIFY_TOL_M,
    }


def _name_shell(entry, stature_m, all_entries):
    """Best-effort name for a shell, with the evidence that produced it.

    A name is for the operator's eyes only — nothing downstream keys off it — so this is
    allowed to be a heuristic, but it is NOT allowed to be a confident guess. Every entry
    records which facts matched, and a shell that matches nothing is called unidentified
    and described by its geometry instead of being labelled anyway.

    Anatomical side is deliberately NOT asserted: naming a shell 'left eye' needs the
    body's facing direction, which is a convention this file has not been told, so a
    mirrored pair is named by the sign of x and says so.
    """
    if entry['role'] == 'body':
        return 'body', 'largest connected component', 'high'
    if entry['role'] == 'loose_vertices':
        return (
            'loose vertices',
            '%d vertices with no faces — unreferenced geometry, not a shell' % entry['vertices'],
            'high',
        )
    cx = entry['centroid_m'][0]
    midline = abs(cx) <= MIDLINE_FRAC_OF_STATURE * stature_m
    zf = 0.5 * (entry['z_frac_min'] + entry['z_frac_max'])
    partner = None
    for o in all_entries:
        if o is entry or o['role'] == 'body':
            continue
        if (
            o['vertices'] == entry['vertices']
            and abs(o['centroid_m'][0] + cx) <= 1e-3 * stature_m
            and abs(o['centroid_m'][2] - entry['centroid_m'][2]) <= 1e-3 * stature_m
        ):
            partner = o['component']
    for sig in SHELL_SIGNATURES:
        if (
            entry['vertices'] == sig['vertices']
            and sig['midline'] == midline
            and sig['z_frac'][0] <= zf <= sig['z_frac'][1]
            and (sig['midline'] or partner is not None)
        ):
            side = '' if midline else (' (+x side)' if cx > 0 else ' (-x side)')
            basis = '%d vertices, %s, z %.3f of stature%s — %s' % (
                entry['vertices'],
                'midline' if midline else 'lateral',
                zf,
                '' if partner is None else ', mirrored by component %d' % partner,
                sig['provenance'],
            )
            return sig['name'] + side, basis, 'high'
    desc = 'unidentified shell: %d vertices, %s, z %.3f-%.3f of stature%s' % (
        entry['vertices'],
        'midline' if midline else 'lateral',
        entry['z_frac_min'],
        entry['z_frac_max'],
        '' if partner is None else ', mirrored by component %d' % partner,
    )
    return 'unidentified', desc, 'none'


_STATE_MEANING = {
    'enclosed': 'every vertex is inside the body solid — enclosed in the strict winding-number sense',
    'in_sealed_body_cavity': "entirely outside the body SOLID, entirely inside the body's "
    'CONVEX ENVELOPE, touching nothing, and no sampled direction '
    'from any probe point escapes to infinity — sealed in a pocket '
    'of the body (the mouth). An invagination is topologically '
    'exterior, so this is the correct state for a tongue, not a '
    'defect',
    'in_open_body_cavity': "entirely outside the body SOLID, entirely inside the body's "
    'CONVEX ENVELOPE, touching nothing, and some sampled directions '
    'escape — a shell recessed in a pocket that opens to the '
    'outside: a tongue behind parted lips (abel, 0.008 of '
    'directions), an eyeball recessed behind the palpebral aperture '
    '(bone_scale 0.80, 0.055, and 22-30 mm inside the envelope). '
    "WHAT IS ASSERTED: the shell has not left the body's own "
    'envelope and does not touch it. WHAT IS NOT ASSERTED: that a '
    'concavity is the anatomically right place for it — a shell '
    'adrift in a deep concavity that never reaches outside the '
    'envelope also lands here, so the escape fraction, the envelope '
    'margins and the clearance are all reported for the operator',
    'protrudes_through_body_surface': 'the shell crosses the body surface: part inside, '
    'part outside. Correct for an eyeball seen through '
    'the eyelid aperture; a defect for anything that is '
    'not supposed to be visible. THIS CHECK CANNOT TELL '
    'THOSE APART — it reports the geometry and the '
    'operator decides',
    'detached_in_open_air': 'outside the body solid, touching nothing, and at least one '
    "vertex lies OUTSIDE THE BODY'S CONVEX ENVELOPE — it has left "
    "the body's own outline, so it is not in a pocket of it. A "
    'shell floating loose next to the body. DEFECT',
    'outside_body_position_unresolved': 'outside the body solid and touching nothing, and the two independent position '
    'measurements do not support either verdict — either the convex envelope could not '
    'be built or verified, or the shell is inside the envelope yet a probe point '
    'reaches open sky in MORE than half of all directions, which is not what being in '
    'a pocket of the body looks like even though the envelope contains it. Whether the '
    'shell sits in a body pocket or in open air is UNDECIDED. Not a pass: unverified, '
    'not benign',
    'straddles_without_crossing': 'vertices on both sides of the body surface yet no face '
    'pair crosses it. Geometrically contradictory: either '
    'the containment test or the intersection test is '
    'wrong. DEFECT, and a defect in this file until proven '
    'otherwise',
    'enclosed_but_crossing': 'every vertex inside the body yet faces cross its surface — a '
    'sliver poking through between vertices. DEFECT',
    'indeterminate': 'the winding number did not come back cleanly 0 or 1, so containment '
    'has no answer on this geometry. DEFECT: unverifiable, not benign',
    'crossing_not_tested': 'vertices were located inside/outside as reported, but the '
    'self-intersection pass was switched off, so whether this '
    "shell's faces cross the body surface is unknown and "
    'enclosure is NOT established. Nothing asserted',
    'not_tested': 'not analysed — see the cap that bound in the payload',
}
_DEFECT_STATES = (
    'detached_in_open_air',
    'straddles_without_crossing',
    'enclosed_but_crossing',
    'indeterminate',
    'outside_body_position_unresolved',
)


def _check_shell_components(
    v, faces, tris, comp_labels, ncomp, euler_per_component, delivered_pairs_by_component=None, containment=True
):
    """Inventory every connected shell and decide where each non-body shell actually sits.

    This exists because the self-intersection check needed to know which contacts were a
    shell against itself, and answering that revealed that nobody here had ever written
    down what the cage is: FOUR closed shells, of which three are a tongue and two eyes.
    Reporting the inventory is most of the value — an operator who can see 'component 1,
    226 v, midline, z 0.874-0.893, tongue, sealed in the mouth pocket' does not have to
    rediscover it from 500 intersecting quad pairs.

    Enclosure is MEASURED, never assumed from size. The measurement that matters is the
    winding number, cross-checked against ray parity, and it says something most people
    guess wrong: an invagination is OUTSIDE. The mouth and the eye sockets are pockets, so
    the tongue is not 'inside the body' by any definition a solid modeller would accept.

    WHICH LEAVES THE REAL QUESTION: a shell outside the solid and touching nothing — is it
    in a pocket of the body, or adrift beside it? That used to be decided by one tuned
    number (escape fraction > 0.05 => defect) calibrated on one example, and it called a
    smaller-than-default eyeball, seated in its socket and 22-30 mm inside the head, a
    shell "floating loose next to the body". It is now decided by TWO independent
    measurements with no tuned constant between them:
      * the exact one — is every vertex inside conv(body), the body's own envelope, which
        is what a mouth or an eye socket is a concavity OF. Signed distance in metres,
        from a hull that is verified to contain the body before it is used;
      * the sampled one — the escape fraction, against the 1/2 half-space bound (see
        ENVELOPE_ESCAPE_MAX_FRACTION), which is a proof outside the envelope and a
        requirement inside it: nothing that sees sky in most directions is in a pocket.
    They agree on every case measured. When they do not, the shell is reported
    'outside_body_position_unresolved', which is a defect state, because a disagreement
    between the only two ways we have of asking is not evidence that the shell is fine.
    """
    # Imported here, not at module level: `shells_containment` imports this module's
    # geometry primitives, and only a lazy import on this side keeps that one-way.
    from zyg_workflows.geom.anthro.integrity.shells_containment import (
        body_probe_set,
        build_shell_inventory,
        build_shell_report,
        containment_payload,
        select_shell_state,
        shell_measurements,
    )

    t0 = _now()
    sh = build_shell_inventory(v, faces, comp_labels, ncomp, euler_per_component)
    shells = sh.shells
    analysed = shells[:MAX_SHELLS_ANALYSED] if containment and not sh.ambiguous else []
    probe_agree = probe_total = 0
    probes = body_probe_set(v, tris, comp_labels, sh, bool(analysed))

    for e in analysed:
        m = shell_measurements(probes, sh, e, delivered_pairs_by_component)
        probe_agree += m.agree
        probe_total += m.n_probes
        state, unresolved_because = select_shell_state(m)
        e['containment'] = containment_payload(m, state, unresolved_because)
    for e in shells[len(analysed) :]:
        e['containment'] = {'state': 'not_tested', 'state_meaning': _STATE_MEANING['not_tested']}

    out = build_shell_report(sh, ncomp, containment, probe_agree, probe_total, probes.env)
    out['ms'] = _ms(t0)
    return out
