# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""integrity.symmetry_topology — Bilateral symmetry (morph correctness only), topology identity, and the generic
ordering helper."""

import numpy as np
from scipy.spatial import cKDTree
from zyg_workflows.geom.anthro.integrity.constants import SYM_MORPH_TOL_MM, TOPOLOGY_SCOPES, _ms, _now

# ---------------------------------------------------------------------------------
# Bilateral symmetry — MORPH CORRECTNESS ONLY
# ---------------------------------------------------------------------------------


def mirror_symmetry(v, axis=0, plane=0.0, tol_mm=SYM_MORPH_TOL_MM):
    """Mirror the cage across the sagittal plane and measure how far it misses itself.

    THIS IS THE MORPH-CORRECTNESS CHECK AND NOTHING ELSE. A body built from a bilaterally
    symmetric morph space is symmetric by construction; the expected value here is zero
    to floating-point noise, and a non-zero result means the BUILD is broken — a morph
    that is not mirrored, or a post-morph sculpt that is not mirror-equivariant. It is
    NOT the realism-asymmetry measurement (a deliberate 0-10mm injection, population mean
    5.2mm), it must never be compared against that band, and the returned payload carries
    `check: 'morph_correctness'` so a caller cannot confuse the two by accident.

    Both a DECLARED plane and the BEST-FIT plane are reported. That separates two very
    different faults which a single number merges: a whole body sitting a few microns off
    the origin (rigid, harmless, shows up at the declared plane and vanishes at the
    best-fit one) versus a genuinely lopsided shape (survives both).

    Matching is nearest-neighbour, and `bijective` reports whether the mirrored point set
    maps one-to-one onto the original. A symmetric cage yields an exact involution; a
    non-bijective match means the nearest-neighbour pairing itself is unreliable and the
    deviation figures should be read with that in mind.
    """
    v = np.asarray(v, np.float64)
    if v.ndim != 2 or v.shape[1] != 3:
        raise ValueError('v must be (N,3), got %r' % (v.shape,))
    if axis not in (0, 1, 2):
        raise ValueError('axis must be 0, 1 or 2, got %r' % (axis,))
    tree = cKDTree(v)

    def _dev(c):
        m = v.copy()
        m[:, axis] = 2.0 * c - m[:, axis]
        d, idx = tree.query(m, k=1)
        return d, idx

    d, idx = _dev(plane)

    # Best-fit plane, in closed form. A bounded scalar minimiser is the obvious way to do
    # this and it is a trap: scipy's default xatol is 1e-5, which in metres is the same
    # size as the rigid offsets actually present on these cages (~3e-5 m), so it returns
    # the offset with roughly 100% error. Solve it exactly instead.
    #
    # With the mirror correspondence held fixed, only the mirrored axis depends on c: the
    # residual for vertex i against its partner p is (2c - u_i - u_p), so the least-
    # squares c is just mean((u_i + u_p)/2). The centroid is an exact fixed point for a
    # perfectly symmetric point set, which makes it the right seed, and the
    # correspondence stabilises immediately in practice.
    u = v[:, axis]
    c = float(u.mean())
    for _ in range(8):
        _, p = _dev(c)
        c_new = float(((u + u[p]) * 0.5).mean())
        if abs(c_new - c) < 1e-13:
            c = c_new
            break
        c = c_new
    db, _ = _dev(c)

    max_mm = float(d.max() * 1000.0)
    return {
        'check': 'morph_correctness',
        'not': 'realism_asymmetry',
        'axis': int(axis),
        'plane_m': float(plane),
        'max_mm': round(max_mm, 6),
        'rms_mm': round(float(np.sqrt((d**2).mean()) * 1000.0), 6),
        'matched': int(len(np.unique(idx))),
        'vertices': int(len(v)),
        'bijective': bool(len(np.unique(idx)) == len(v)),
        'best_fit_plane_m': c,
        'max_mm_about_best_fit': round(float(db.max() * 1000.0), 6),
        'rms_mm_about_best_fit': round(float(np.sqrt((db**2).mean()) * 1000.0), 6),
        'rigid_offset_um': round(c * 1e6, 4),
        'vertices_over_tol': int((d * 1000.0 > tol_mm).sum()),
        # a rigid offset puts EVERY vertex over the tolerance while the shape stays
        # perfectly symmetric, so the same count about the best-fit plane is what tells
        # a translated body apart from a lopsided one
        'vertices_over_tol_about_best_fit': int((db * 1000.0 > tol_mm).sum()),
        'tol_mm': tol_mm,
        'tol_provenance': 'HOUSE, calibrated on MEASURED values, RE-CALIBRATED 2026-08-05 after the '
        'asymmetric abs_definition sculpt this gate was first tuned against was made '
        "symmetric by construction. The floor left underneath it is anny's own "
        'local-morph target data, which is not bit-mirror-symmetric: measured over six '
        'bodies with the sculpt layer off — female 0.0014, stock male/female 0.0167, '
        'abel 0.0229, cornelis 0.0600, male 0.0632 mm — the worst is 0.0632 mm and it '
        'rises with the number of fitted measure-* locals applied. 0.15 mm clears that '
        'floor with 2.4x headroom and still catches the 2.93-3.76 mm asymmetric-sculpt '
        'defect that motivated the gate by ~25x. NOTE ALL SIX ARE PURE-MORPH BODIES: '
        'the pre-fix text of this field filed cornelis and male under the sculpt '
        'category at 2.93/3.76 mm. That described the calibration of the RETIRED '
        '0.05 mm tolerance and these measurements refute it — it was wrong about those '
        'two bodies by 49x and 60x, and the pure-morph maximum it quoted (0.0229 mm) '
        'excluded the two bodies that actually set the floor.',
        'tol_provenance_revised': '2026-08-05',
        'pass': bool(max_mm <= tol_mm),
        'worst_vertex': int(np.argmax(d)),
    }


def _check_mirror(v, tol_mm=SYM_MORPH_TOL_MM):
    t0 = _now()
    d = mirror_symmetry(v, axis=0, plane=0.0, tol_mm=tol_mm)
    return {'pass': bool(d['pass']), 'detail': d, 'ms': _ms(t0)}


# ---------------------------------------------------------------------------------
# Topology identity
# ---------------------------------------------------------------------------------


def _resolve_expect(value, key):
    if value is None:
        return None, None
    if isinstance(value, str):
        if value not in TOPOLOGY_SCOPES:
            raise KeyError('unknown topology scope %r; known: %s' % (value, sorted(TOPOLOGY_SCOPES)))
        return TOPOLOGY_SCOPES[value][key], value
    return int(value), None


def face_topology_sha(faces):
    """A canonical digest of face CONNECTIVITY — which vertices share a face.

    WHY THIS IS SEPARATE FROM _vert_sha, AND MUST STAY SEPARATE. mesh_skeletons._vert_sha
    hashes ONLY rest-cage vertex positions, and that narrowness is a deliberate, valuable
    property: it is why fixing a skinning weight or moving a bone does not perturb the cage
    identity, which is what makes those fixes free. Widening it to cover faces would make
    every rig change a cage-identity change. So: a SECOND hash for a second thing, never a
    wider first one.

    WHAT IT CATCHES, measured 2026-08-08 by geom/anthro/mutation.py: t1_topology_identity
    compares vertex and face COUNTS. Reverse the winding on 4% of faces, or permute the
    face list, or reassign which vertices form which quad, and the counts are unchanged —
    so the gate named "topology identity" could not see a change in topology.

    DELIBERATELY WINDING-INSENSITIVE. Each face's vertex ids are sorted before hashing, so
    a reversed face hashes the same. That is not an oversight: t1_winding_consistent
    already detects orientation defects, and making this hash react to them too would
    report one defect as two, in two gates, with no way to tell which is the cause. This
    answers only "is the connectivity the same set of faces over the same vertices".
    """
    import hashlib

    f = np.ascontiguousarray(np.sort(np.asarray(faces, np.int64), axis=1))
    order = np.lexsort(tuple(f[:, i] for i in range(f.shape[1] - 1, -1, -1)))
    return hashlib.blake2b(np.ascontiguousarray(f[order]).tobytes(), digest_size=16).hexdigest()


def _check_topology_identity(v, faces, expect_vertices, expect_faces, expect_face_sha=None):
    """The caller declares the scope; we assert it. We never guess, because 'the body
    mesh' is not one number: this cage ships the tongue and both eyes as separate closed
    shells, so 13718 and 13348 are both correct answers to different questions."""
    t0 = _now()
    f = np.asarray(faces)
    arity = int(f.shape[1])
    key = 'faces_quad' if arity == 4 else 'faces_tri'
    ev, scope_v = _resolve_expect(expect_vertices, 'vertices')
    ef, scope_f = _resolve_expect(expect_faces, key)

    got_v, got_f = int(len(v)), int(len(f))
    matches = [n for n, s in TOPOLOGY_SCOPES.items() if s['vertices'] == got_v and s.get(key) == got_f]

    problems = []
    if ev is not None and got_v != ev:
        problems.append('vertices: declared %d, got %d' % (ev, got_v))
    if ef is not None and got_f != ef:
        problems.append('faces(%s): declared %d, got %d' % (key, ef, got_f))

    # CONNECTIVITY, not just counts. Reported ALWAYS so it can be recorded and compared
    # later; asserted only when a caller declares an expected value. Introducing it as
    # report-only is deliberate — every existing record predates it, and a gate that fails
    # all five characters at once on a bookkeeping change teaches everyone to ignore it.
    got_sha = face_topology_sha(f)
    if expect_face_sha and got_sha != expect_face_sha:
        problems.append('face connectivity: declared sha %s, got %s' % (str(expect_face_sha)[:16], got_sha[:16]))

    detail = {
        'vertices': got_v,
        'faces': got_f,
        'face_arity': arity,
        'declared_vertices': ev,
        'declared_faces': ef,
        'declared_scope': scope_v or scope_f,
        'matching_known_scopes': matches,
        'face_topology_sha': got_sha,
        'declared_face_topology_sha': expect_face_sha,
        'face_topology_sha_is': (
            'canonical digest of face CONNECTIVITY (vertex ids sorted within each face, '
            'then faces lexsorted), so it is invariant to face order and to winding '
            'direction. Winding defects belong to winding_consistent; this answers only '
            'whether the same faces span the same vertices. Report-only until a caller '
            'declares an expected value.'
        ),
        'problems': problems,
        'nothing_declared': ev is None and ef is None and expect_face_sha is None,
    }
    if ev is None and ef is None:
        detail['note'] = (
            'no scope declared, so nothing was asserted — counts are '
            'reported only. Pass a scope name from TOPOLOGY_SCOPES or an '
            'explicit integer to turn this into a gate.'
        )
    return {'pass': bool(not problems), 'detail': detail, 'ms': _ms(t0)}


# ---------------------------------------------------------------------------------
# Generic ordering helper (landmark ordering itself belongs to the gates layer)
# ---------------------------------------------------------------------------------


def monotonic_chain(values, names=None, increasing=True, tol=0.0):
    """Assert a sequence is monotonic, reporting EVERY violation with its magnitude.

    Provided because ordering assertions are structurally identical wherever they occur,
    but the anatomical content — which landmark must sit above which — is deliberately
    NOT here. Encoding 'acromion is above crotch' in an integrity module would put an
    anatomical claim in a file that is supposed to know only about triangles. The gates
    layer owns the landmark chains and calls this to evaluate them.

    tol is a slack in the same units as `values`: a step is a violation only when it goes
    the wrong way by MORE than tol.
    """
    a = np.asarray(values, np.float64)
    if a.ndim != 1:
        raise ValueError('values must be 1-D, got %r' % (a.shape,))
    if names is not None and len(names) != len(a):
        raise ValueError('names has length %d but values has %d' % (len(names), len(a)))
    d = np.diff(a)
    bad = np.nonzero((d < -tol) if increasing else (d > tol))[0]
    viol = []
    for k in bad:
        viol.append(
            {
                'index': int(k),
                'from': (names[k] if names is not None else int(k)),
                'to': (names[k + 1] if names is not None else int(k + 1)),
                'delta': float(d[k]),
                'magnitude': float(abs(d[k])) - tol,
            }
        )
    return {
        'pass': bool(len(viol) == 0),
        'increasing': bool(increasing),
        'tol': float(tol),
        'n': int(len(a)),
        'violations': viol,
    }
