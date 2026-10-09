# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""relational/spine.py — frame and context, the posterior midsagittal chain, lumbar curvature and the segment-tilt frames.

Moved verbatim out of relational.py (lines 180-500).
"""

from zyg_workflows.geom.form.relational.constants import (
    FRAME,
    LMK,
    ME,
    MIDLINE_TOL_M,
    MS,
    POSTERIOR_NORMAL_MIN,
    SIGN_CONVENTION,
    _CACHE,
    math,
    np,
)


# ---------------------------------------------------------------------------------
# frame and context
# ---------------------------------------------------------------------------------
def _frame(v, faces):
    """Assert the measured frame is the one every sign in this file is written against."""
    key = 'frame'
    if key not in _CACHE:
        _CACHE[key] = LMK.frame_report(v, faces)
    fr = _CACHE[key]
    for k, want in FRAME.items():
        got = fr[k]
        if got != want:
            raise RuntimeError(
                'frame_report measures %s = %r on this cage, but every sagittal sign in '
                'geom.form.relational is written against %r. Signs would be inverted '
                'silently, so this refuses. Measured convention: %s' % (k, got, want, fr['convention'])
            )
    return fr


def _context(v, faces, landmarks=None, phenotype=None, local_changes=None):
    v = np.asarray(v, np.float64)
    if len(v) != LMK.CAGE_VERTS:
        raise ValueError(
            'geom.form.relational is indexed against the %d-vertex anny cage; got %d' % (LMK.CAGE_VERTS, len(v))
        )
    faces = np.asarray(faces)
    _frame(v, faces)
    zmin = float(v[:, 2].min())
    H = float(v[:, 2].max()) - zmin
    if H <= 0:
        raise ValueError('degenerate mesh: zero stature')
    lm = landmarks if landmarks is not None else LMK.resolve_landmarks(v, faces, phenotype, local_changes)
    return {
        'v': v,
        'faces': faces,
        'zmin': zmin,
        'H': H,
        'fz': (v[:, 2] - zmin) / H,
        'n': MS._vertex_normals(v, faces),
        'lm': lm,
    }


def _lm_frac(ctx, name):
    """frac_stature of a resolved landmark, or None with its own reason attached."""
    rec = ctx['lm'].get(name)
    if rec is None:
        return None, 'landmarks.py publishes no landmark named %r' % name
    if rec.get('frac_stature') is None:
        return None, 'landmark %r is %s: %s' % (name, rec['confidence'], rec['note'])
    return float(rec['frac_stature']), None


def _unresolved(reason, **evidence):
    rec = {'resolved': False, 'reason': reason}
    rec.update(evidence)
    return rec


# ---------------------------------------------------------------------------------
# (1a) THE POSTERIOR MIDSAGITTAL CHAIN
# ---------------------------------------------------------------------------------
def posterior_midline_chain(v, faces, landmarks=None, phenotype=None, local_changes=None, fz_lo=None, fz_hi=None):
    """The dorsal midline of the cage as a real, edge-connected vertex path.

    WHY A VERTEX CHAIN AND NOT AN ENVELOPE. The obvious construction — max y over a thin
    midline slab, per height bin — is what this started as and it is wrong in a way that
    only shows up on some bodies: the cage's vertex rows are not horizontal, so a slab can
    contain no BACK vertex at all, and max-y then silently returns the ABDOMEN. Measured on
    the issued male at 0.545 of stature it returned y/H = -0.129, i.e. 239 mm anterior,
    which read as a violent kink in the lumbar profile that is not in the mesh. The cage
    carries an actual midsagittal column of vertices (|x| = 0.0000-0.0300 mm, next column
    out at 0.7307 mm), and 42 of the 43 consecutive pairs of the retained path share a cage
    edge — MEASURED, and reported in the record as 'edge_connected_pairs'.

    fz_lo / fz_hi default to the resolved buttock landmark and the resolved bust ring: the
    window is anatomy, not a fixed band, so it travels with a 1.52 m child.
    """
    ctx = _context(v, faces, landmarks, phenotype, local_changes)
    v, fz, n, H = ctx['v'], ctx['fz'], ctx['n'], ctx['H']
    if fz_lo is None:
        fz_lo, why = _lm_frac(ctx, 'buttock')
        if fz_lo is None:
            return _unresolved('the inferior window bound needs the buttock landmark: ' + why)
    if fz_hi is None:
        fz_hi, why = _lm_frac(ctx, 'bust_ring')
        if fz_hi is None:
            return _unresolved('the superior window bound needs the bust ring: ' + why)
    if not fz_hi > fz_lo:
        raise ValueError(
            'posterior midline window is inverted: buttock %.4f is not below bust ring %.4f of stature' % (fz_lo, fz_hi)
        )

    m = (np.abs(v[:, 0]) <= MIDLINE_TOL_M) & (n[:, 1] > POSTERIOR_NORMAL_MIN) & (fz >= fz_lo) & (fz <= fz_hi)
    idx = np.nonzero(m)[0]
    if len(idx) < 6:
        return _unresolved(
            'the posterior midsagittal column carries only %d vertices in the anatomical '
            'window %.4f-%.4f of stature; a curvature read off fewer than 6 samples is '
            'noise' % (len(idx), fz_lo, fz_hi),
            n_vertices=int(len(idx)),
            window=[fz_lo, fz_hi],
        )
    order = idx[np.argsort(v[idx, 2])]

    edges = _cage_edges(ctx['faces'])
    connected = sum(1 for a, b in zip(order[:-1], order[1:]) if (int(a), int(b)) in edges)
    gaps = np.diff(fz[order])
    return {
        'resolved': True,
        'vertex_idx': order.tolist(),
        'fz': fz[order].tolist(),
        'y_over_stature': (v[order, 1] / H).tolist(),
        'x_max_abs_mm': float(np.abs(v[order, 0]).max() * 1000.0),
        'normal_y_min': float(n[order, 1].min()),
        'n_vertices': int(len(order)),
        'edge_connected_pairs': int(connected),
        'consecutive_pairs': int(len(order) - 1),
        'max_gap_frac_stature': float(gaps.max()),
        'window_frac_stature': [float(fz_lo), float(fz_hi)],
        'window_anchor': 'inferior = resolved buttock landmark (ISO, maximum posterior '
        'protrusion); superior = resolved bust_ring '
        '(makehuman:measure-bust-circ-incr)',
        'anchor_kind': 'cage vertices, midline column',
        'note': 'a real edge-connected path of cage vertices, not a silhouette '
        'envelope. x_max_abs_mm is how far off the sagittal plane the column '
        'actually sits.',
    }


def _cage_edges(faces):
    key = ('edges', int(faces.shape[0]))
    if key in _CACHE:
        return _CACHE[key]
    e = set()
    f = np.asarray(faces)
    for a, b in ((0, 1), (1, 2), (2, 3), (3, 0)):
        for p, q in zip(f[:, a].tolist(), f[:, b].tolist()):
            e.add((p, q))
            e.add((q, p))
    _CACHE[key] = e
    return e


# ---------------------------------------------------------------------------------
# (1b) LUMBAR CURVATURE AND THE SAGITTAL OPPOSITION — the swayback detector
# ---------------------------------------------------------------------------------
def lumbar_curvature(v, faces, landmarks=None, phenotype=None, local_changes=None, chain=None):
    """Lordosis depth, index and the two chord tilts of the lumbar curve.

    CONSTRUCTION, which is the ordinary chord-and-depth (flexicurve) reading of a spinal
    curve and is a method, not anyone's expression of one:

      * take the posterior midsagittal chain over [buttock landmark, bust ring];
      * the LUMBAR TROUGH is its most ANTERIOR point (minimum y). It must be interior — a
        trough at either end means the window did not bracket a curve and the reading is
        refused rather than reported;
      * the SACRAL APEX is the most posterior point at or below the trough, the THORACIC
        APEX the most posterior point at or above it. Both are the profile's own extrema,
        not a table;
      * DEPTH is the anterior deviation of the trough from the apex-to-apex chord, in
        stature; INDEX is 100 x depth / chord length, which makes it scale-free;
      * the two CHORD TILTS are sacral-apex-to-trough and trough-to-thoracic-apex. The
        physiological opposition is lower tilt NEGATIVE (rising anteriorly out of the
        sacrum) and upper tilt POSITIVE (rising posteriorly into the thorax). Both the
        same sign is a flat or reversed lumbar spine, which is a different defect from a
        deep one and has to be distinguishable from it.

    WHY THIS IS THE SWAYBACK DETECTOR AND A WIDTH GATE IS NOT. Measured on the recipe that
    produced the 2026-08-05 swayback (geom/fit_reference.py records the cause: "any scalar
    the objective does not measure becomes a dumping ground for solver error") the index is
    25.15, against 13.11 for the shipped female, 7.73 male, 7.72 abel, 7.72 cornelis. The
    rejected body's widths were the ones the solver was fitting; they were fine.
    """
    ctx = _context(v, faces, landmarks, phenotype, local_changes)
    ch = chain if chain is not None else posterior_midline_chain(v, faces, landmarks=ctx['lm'])
    if not ch.get('resolved'):
        return _unresolved('the lumbar curve needs the posterior midsagittal chain: ' + ch['reason'], chain=ch)
    t = np.asarray(ch['fz'], np.float64)
    y = np.asarray(ch['y_over_stature'], np.float64)

    j = int(np.argmin(y))
    if j == 0 or j == len(y) - 1:
        return _unresolved(
            'the most anterior point of the posterior midline sits at the %s end of the '
            'anatomical window, so the window does not bracket a lumbar curve and there '
            'is nothing to measure the depth of' % ('inferior' if j == 0 else 'superior'),
            trough_index=j,
            n=int(len(y)),
            window_frac_stature=ch['window_frac_stature'],
        )
    a = int(np.argmax(y[: j + 1]))
    b = j + int(np.argmax(y[j:]))
    if a == b:
        return _unresolved('the sacral and thoracic apexes resolved to the same vertex', apex_index=a)

    chord = float(math.hypot(t[b] - t[a], y[b] - y[a]))
    y_on_chord = y[a] + (t[j] - t[a]) / (t[b] - t[a]) * (y[b] - y[a])
    depth = float(y_on_chord - y[j])
    lower = float(math.degrees(math.atan2(y[j] - y[a], t[j] - t[a])))
    upper = float(math.degrees(math.atan2(y[b] - y[j], t[b] - t[j])))
    return {
        'resolved': True,
        'lordosis_index': float(100.0 * depth / chord),
        'lordosis_depth_frac_stature': depth,
        'lordosis_depth_mm': depth * ctx['H'] * 1000.0,
        'chord_frac_stature': chord,
        'curve_angle_deg': float(abs(lower) + abs(upper)),
        'lower_chord_tilt_deg': lower,
        'upper_chord_tilt_deg': upper,
        'opposition_physiological': bool(lower < 0.0 < upper),
        'sacral_apex_frac_stature': float(t[a]),
        'trough_frac_stature': float(t[j]),
        'thoracic_apex_frac_stature': float(t[b]),
        'sacral_apex_y_over_stature': float(y[a]),
        'trough_y_over_stature': float(y[j]),
        'thoracic_apex_y_over_stature': float(y[b]),
        'samples_in_window': int(len(y)),
        'max_gap_frac_stature': ch['max_gap_frac_stature'],
        'sign_convention': SIGN_CONVENTION,
        'method': 'chord-and-depth (flexicurve) reading of the posterior midsagittal '
        'profile between its own sacral and thoracic posterior apexes',
    }


# ---------------------------------------------------------------------------------
# (1c) SEGMENT-TILT FRAMES — reported UNRESOLVED, with the instability that proves it
# ---------------------------------------------------------------------------------
def segment_tilt_opposition(v, faces, landmarks=None, phenotype=None, local_changes=None):
    """Thoracic and pelvic segment frames — UNRESOLVED on this cage, and here is why.

    The brief for this predicate is to fit a frame to each segment and require the
    physiological opposition between their sagittal tilts. Three frames were built and
    measured before this was written off, and each failed for its own reason:

      * SAGITTAL PCA of the segment point cloud. The long principal axis of a torso segment
        in the y-z plane is the ANTEROPOSTERIOR axis, not a body axis: measured, the
        thoracic segment reads 72-78 degrees from vertical on every body including the
        approved ones, and the resulting 'opposition' is 68-74 degrees on all of them. It
        is measuring the segment's aspect ratio.
      * BEST-FIT PLANE NORMAL of the bounding girth rings. The rings are not planar. The
        ratio of the smallest to the largest principal spread of the hip ring core is
        0.156-0.235 (measured, four bodies), so its 'normal' is the axis of a blob and it
        swings from -6.9 to -67.3 degrees across the four issued characters.
      * SLAB-CENTROID AXIS, arm-masked by measure.arm_skin_weights(), which is the correct
        construction and still fails for lack of a segment to run it over. The resolvable
        pelvic band is bounded below by the crotch (below it the trunk section is one
        thigh, measured by measure.py) and above by the top of the hip ring core, and that
        band is 0.06 of stature tall. Over it the axis reads +3.99 degrees on the issued
        male and -6.15 degrees on cornelis — a 10.1 degree swing between two bodies that
        carry the IDENTICAL 30-entry local-morph recipe and the identical anatomy layer,
        differing only in the age and height macros. A frame that moves 10 degrees when the
        pelvis does not is not measuring the pelvis.

    This function computes the third of those, reports it, and returns resolved=False. The
    numbers are here so the claim is auditable, NOT so a caller can gate on them; the
    lumbar chord tilts in lumbar_curvature() are the sagittal opposition this cage can
    actually carry, and they are read off a vertex path rather than a centroid of a section
    whose topology changes underneath it.
    """
    ctx = _context(v, faces, landmarks, phenotype, local_changes)
    v, fz, H = ctx['v'], ctx['fz'], ctx['H']
    arm = ME.arm_skin_weights()
    if arm['weight'] is None:
        return _unresolved(
            'the arm mask is unavailable (%s), and an unmasked torso '
            'centroid in the A-pose is the arm' % arm['provenance'].get('reason'),
            arm=arm['provenance'],
        )
    trunk = np.nonzero(arm['weight'] < ME.ARM_SKIN_WEIGHT_THRESHOLD)[0]

    crotch, why = _lm_frac(ctx, 'crotch')
    if crotch is None:
        return _unresolved('the pelvic band floor needs the crotch landmark: ' + why)
    hip = LMK._support_core('measure-hips-circ-incr', 0.8)
    ub = LMK._support_core('measure-underbust-circ-incr', 0.8)
    bust = LMK._support_core('measure-bust-circ-incr', 0.8)
    if hip is None or ub is None or bust is None:
        return _unresolved('a bounding girth-ring core did not resolve on this cage')
    pel_hi = float(fz[hip[0]].max())
    thx_lo = float(fz[ub[0]].min())
    thx_hi = float(fz[bust[0]].max())

    out = {
        'resolved': False,
        'reason': 'no segment frame on this cage is stable enough to gate on; see the '
        'docstring for the three that were measured and rejected',
        'pelvic_band_frac_stature': [crotch, pel_hi],
        'pelvic_band_height_frac_stature': pel_hi - crotch,
        'thoracic_band_frac_stature': [thx_lo, thx_hi],
        'method': 'slab-centroid axis over arm-masked trunk vertices',
        'sign_convention': SIGN_CONVENTION,
    }
    for name, lo, hi in (('pelvic', crotch, pel_hi), ('thoracic', thx_lo, thx_hi)):
        ax = _centroid_axis(v, fz, H, trunk, lo, hi)
        out[name + '_tilt_deg'] = None if ax is None else ax[0]
        out[name + '_slabs'] = 0 if ax is None else ax[1]
    if out['pelvic_tilt_deg'] is not None and out['thoracic_tilt_deg'] is not None:
        out['opposition_deg'] = out['thoracic_tilt_deg'] - out['pelvic_tilt_deg']
    return out


def _centroid_axis(v, fz, H, keep, lo, hi, step=0.005, half=0.008, min_slab=8):
    g = np.arange(lo, hi + 1e-9, step)
    pts = []
    for t in g:
        s = keep[np.abs(fz[keep] - t) <= half]
        if len(s) >= min_slab:
            pts.append((v[s, 1].mean() / H, v[s, 2].mean() / H))
    if len(pts) < 4:
        return None
    P = np.asarray(pts, np.float64)
    P = P - P.mean(0)
    w, V = np.linalg.eigh(np.cov(P.T))
    a = V[:, int(np.argmax(w))]
    if a[1] < 0:
        a = -a
    return float(math.degrees(math.atan2(a[0], a[1]))), int(len(pts))
