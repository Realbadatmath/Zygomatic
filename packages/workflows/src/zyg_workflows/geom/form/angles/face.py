# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The anterior midsagittal face profile and the gonial angle."""

from zyg_workflows.geom.form.angles.base import (
    BANDS,
    JAW_WEIGHT_CUTS,
    MIDLINE_TOL_M,
    OCCLUSION_HEIGHT_FRAC,
    OCCLUSION_MIN_GAP_FACTOR,
    OCCLUSION_SPLIT_FLOOR,
    SIGN_CONVENTION,
    _bone_head,
    _bone_weight,
    _context,
    _skin_mask,
    _spread,
    _unresolved,
    math,
    np,
)


# ---------------------------------------------------------------------------------
# (1) THE ANTERIOR MIDSAGITTAL FACE PROFILE, and its turning points
# ---------------------------------------------------------------------------------
def face_profile(v, faces, landmarks=None, phenotype=None, local_changes=None):
    """The outer profile of the face as a real ordered chain of midline cage vertices.

    WHY NOT AN ENVELOPE, AND WHY NOT A RAW MIDLINE SLAB. relational.posterior_midline_chain
    records why the obvious construction — max/min y over a thin midline slab per height bin
    — is wrong on the back: the cage's vertex rows are not horizontal, so a bin can contain
    no relevant vertex and the extremum silently returns a different anatomy. On the FRONT
    there is a second and worse failure, which is measured here: the midline column runs
    through the INSIDE OF THE MOUTH as well as the outside of the face, and those oral
    vertices carry anterior-facing normals (measured n_y = -0.995, -0.964, -0.546), so no
    normal test excludes them. An envelope (keep only the most anterior vertex per height
    window) excludes them and ALSO DESTROYS THE MEASUREMENT, because subnasale and nasion
    are by definition the LEAST anterior points of their neighbourhoods and an envelope
    deletes exactly those.

    So the filter is an OCCLUSION test rather than an envelope: a midline vertex is dropped
    only when another midline vertex at practically the same height sits far in front of it.
    Both constants have an order of magnitude of headroom and the record reports the ratio.

    Returns the ordered chain plus its own turning points. Every landmark below is the
    profile's own local extremum, found by walking outward from a point defined without any
    window at all, so no search band appears anywhere in this function:

      pronasale        the GLOBAL most anterior vertex of the face profile. On any human
                       head that is the tip of the nose; no window is needed to find it.
      subnasale        walking DOWN from pronasale, the first local maximum of y (the first
                       point that stops moving posteriorly).
      labiale superius walking DOWN from subnasale, the first local minimum of y.
      nasion           walking UP from pronasale, the first local maximum of y.
      glabella         walking UP from nasion, the first local minimum of y.

    Each carries the PROMINENCE of its turning point — how far the profile travels before it
    turns back — so a turning point that is one vertex of noise is visible as one.
    """
    ctx = _context(v, faces, landmarks, phenotype, local_changes)
    v, fz, n, S = ctx['v'], ctx['fz'], ctx['n'], ctx['S']
    skin = _skin_mask(v, ctx['faces'])

    men, why = _lm_frac(ctx, 'menton')
    if men is None:
        return _unresolved('the face profile is bounded below by the menton landmark: ' + why)
    cand = np.nonzero((np.abs(v[:, 0]) <= MIDLINE_TOL_M) & (n[:, 1] < 0.0) & (fz >= men) & skin)[0]
    if len(cand) < 12:
        return _unresolved(
            'the anterior midsagittal column carries only %d vertices above menton; a '
            'profile read off fewer than 12 samples cannot resolve a turning point' % len(cand),
            n_candidates=int(len(cand)),
        )

    y = v[cand, 1] / S
    h = fz[cand]
    occl = np.zeros(len(cand))
    for k in range(len(cand)):
        near = np.abs(h - h[k]) <= OCCLUSION_HEIGHT_FRAC
        near[k] = False
        if near.any():
            occl[k] = float(y[k] - y[near].min())  # how far in front the nearest surface is
    cut, gap_factor, split_at = _occlusion_cut(occl)
    if cut is None and gap_factor is not None:
        return _unresolved(
            'the anterior midline column of this body does not separate into a facial '
            'profile and an oral cavity: the deepest occlusions reach %.4f of stature but '
            'the largest multiplicative gap in the distribution is only a factor of %.2f, '
            'against the %.1f this filter is valid at. Splitting there would delete facial '
            'surface, so nothing is split and no profile is reported.'
            % (float(occl.max()), gap_factor, OCCLUSION_MIN_GAP_FACTOR),
            occlusion_max_frac_stature=float(occl.max()),
            occlusion_gap_factor=gap_factor,
            occlusion_split_floor=OCCLUSION_SPLIT_FLOOR,
            n_candidates=int(len(cand)),
        )
    keep = occl <= cut if cut is not None else np.ones(len(cand), bool)
    worst_kept = float(occl[keep].max()) if keep.any() else 0.0
    worst_dropped = float(occl[~keep].min()) if (~keep).any() else 0.0
    idx = cand[keep]
    if len(idx) < 12:
        return _unresolved(
            'the occlusion filter left only %d profile vertices' % len(idx),
            n_candidates=int(len(cand)),
            n_kept=int(len(idx)),
        )
    order = idx[np.argsort(v[idx, 2])]
    Y = v[order, 1] / S
    H = fz[order]

    n_dropped = int((~keep).sum())
    ratio = (worst_dropped / worst_kept) if worst_kept > 1e-12 else None

    def turn(start, step, want):
        """Walk from `start` in direction `step` to the first strict turning point.
        want=+1 finds a local MAXIMUM of y (least anterior), want=-1 a local minimum."""
        i = start
        while True:
            j = i + step
            if j < 0 or j >= len(Y):
                return (
                    None,
                    None,
                    'the profile ran off its %s end before turning' % ('inferior' if step < 0 else 'superior'),
                )
            if (Y[j] - Y[i]) * want < 0:
                break
            i = j
        # i is the turning vertex; prominence = travel from `start` to it
        return i, float(abs(Y[i] - Y[start])), None

    pro = int(np.argmin(Y))  # global most anterior
    if pro in (0, len(Y) - 1):
        return _unresolved(
            'the most anterior point of the face profile sits at the %s end of the chain, '
            'so the chain does not bracket a nose' % ('inferior' if pro == 0 else 'superior'),
            pronasale_index=int(pro),
        )

    out = {
        'resolved': True,
        'n_candidates': int(len(cand)),
        'n_profile': int(len(order)),
        'n_dropped_occluded': n_dropped,
        'occlusion_worst_kept_frac_stature': worst_kept,
        'occlusion_worst_dropped_frac_stature': worst_dropped or None,
        'occlusion_margin_ratio': ratio,
        'occlusion_cut_frac_stature': cut,
        'occlusion_gap_factor': gap_factor,
        'occlusion_split_between_frac_stature': split_at,
        'occlusion_min_gap_factor': OCCLUSION_MIN_GAP_FACTOR,
        'occlusion_split_floor': OCCLUSION_SPLIT_FLOOR,
        'vertex_idx': order.tolist(),
        'fz': H.tolist(),
        'y_over_stature': Y.tolist(),
        'x_max_abs_mm': float(np.abs(v[order, 0]).max() * 1000.0),
        'points': {},
        'unresolved_points': {},
        'anchor_kind': "cage vertices, anterior midline column; landmarks are the profile's own turning points",
        'sign_convention': SIGN_CONVENTION,
    }

    def emit(name, i, prom, why_):
        if i is None:
            out['unresolved_points'][name] = why_
            return None
        out['points'][name] = {
            'vertex': int(order[i]),
            'index': int(i),
            'frac_stature': float(H[i]),
            'y_over_stature': float(Y[i]),
            'point_m': [float(x) for x in v[order[i]]],
            'prominence_frac_stature': prom,
            'prominence_mm': None if prom is None else prom * S * 1000.0,
        }
        return i

    emit('pronasale', pro, 0.0, None)
    i_sub = emit('subnasale', *turn(pro, -1, +1))
    if i_sub is not None:
        emit('labiale_superius', *turn(i_sub, -1, -1))
    i_nas = emit('nasion', *turn(pro, +1, +1))
    if i_nas is not None:
        emit('glabella', *turn(i_nas, +1, -1))
    return out


def _occlusion_cut(occl):
    """Split one body's own occlusion depths into "facial surface" and "inside the mouth".

    Returns (cut, gap_factor, [lower, upper]). The cut is the geometric midpoint of the
    LARGEST MULTIPLICATIVE GAP in the sorted depths, considered only among gaps whose upper
    side clears OCCLUSION_SPLIT_FLOOR — the floor's only job is to keep the gap-finder out
    of the legitimate population on a body that has no interlopers, and it never decides
    which side a vertex falls on.

    (None, factor, span) means the two populations are NOT separated by
    OCCLUSION_MIN_GAP_FACTOR and the caller must refuse rather than split.
    (None, None, None) means there is nothing above the floor at all, i.e. nothing to drop.
    """
    a = np.sort(np.asarray(occl, np.float64))
    a = a[a > 1e-9]
    if not len(a) or a.max() < OCCLUSION_SPLIT_FLOOR:
        return None, None, None
    best = None
    for i in range(len(a) - 1):
        lo, hi = a[i], a[i + 1]
        if hi < OCCLUSION_SPLIT_FLOOR or lo <= 0:
            continue
        f = hi / lo
        if best is None or f > best[0]:
            best = (f, lo, hi)
    if best is None:
        return None, None, None
    f, lo, hi = best
    if f < OCCLUSION_MIN_GAP_FACTOR:
        return None, float(f), [float(lo), float(hi)]
    return float(math.sqrt(lo * hi)), float(f), [float(lo), float(hi)]


def _lm_frac(ctx, name):
    rec = ctx['lm'].get(name)
    if rec is None:
        return None, 'landmarks.py publishes no landmark named %r' % name
    if rec.get('frac_stature') is None:
        return None, 'landmark %r is %s: %s' % (name, rec['confidence'], rec['note'])
    return float(rec['frac_stature']), None


# ---------------------------------------------------------------------------------
# (2) GONIAL ANGLE — UNRESOLVED, with the measurement that proves it
# ---------------------------------------------------------------------------------
def gonial_angle(v, faces, landmarks=None, phenotype=None, local_changes=None):
    """The mandibular angle. UNRESOLVED ON THIS CAGE, and this is the measurement.

    HeadNeck p.15 and FacialExpr p.26 both print it — the only cross-book-confirmed number
    in the corpus — and the adult male band (100-120) and adult female band (120-140) touch
    at a single degree, so a mesh that carried this angle would carry the sharpest sex gate
    we have. It would also carry a monotone age curve from 135-150 at birth, which is
    exactly what a 12-year-old character needs. So the negative below is expensive and it is
    measured three ways rather than asserted once.

    WHAT THE ANGLE NEEDS: three points in the sagittal projection — the condylar pivot, GONION
    (the corner where the ramus meets the body), and menton.

    WHAT THIS CAGE HAS.
      * The pivot, yes: MakeHuman's rig carries a 'jaw' bone whose parent is 'head'
        (MEASURED), so its head IS the temporomandibular joint by construction of the rig.
        Measured on the anny neutral at y = -63.6, z = 718.8 mm.
      * Menton, yes: landmarks.py resolves it at medium confidence off the chin target's
        inferior extremum, with an outward normal pointing straight down.
      * GONION, NO. The 'jaw' bone is a SINGLE MIDLINE HINGE SEGMENT running from that pivot
        straight to the chin (tail measured at y = -118.1, z = 635.6). It is the
        condylion-menton CHORD. A chord has no corner on it, so the rig cannot supply
        gonion and it has to come off the surface.

    WHY THE SURFACE DOES NOT SUPPLY IT EITHER. The construction tried here is the standard
    parameter-free one: in the sagittal projection, gonion is the point of the mandibular
    surface furthest from the condylion-menton chord on the postero-inferior side. The
    mandibular surface is taken to be MakeHuman's own jaw-bone skinning support, and the
    weight cut is swept because there is no principled single value for it. MEASURED on the
    anny neutral, the resulting angle at cuts 0.05 / 0.10 / 0.20 / 0.30 / 0.50 is
    92.5 / 78.2 / 74.3 / 91.9 / 153.2 degrees — a spread of 78.9 degrees against a printed
    band width of 15. The cause is measured too and is reported as 'submental_overreach':
    the jaw skinning support reaches BELOW MENTON on the midline (measured 41 mm below on
    the neutral), i.e. what MakeHuman calls "driven by the jaw" includes upper-neck skin,
    so sweeping the cut walks the furthest-point down the neck and the angle follows it.

    That is a TESSELLATION-AND-RIGGING limit, not a threshold one, and it is the same class
    of finding as regions.py's psis entry: no cut recovers a corner the cage has no corner
    at. The record still reports the condylion-menton chord inclination, which IS
    well-defined on this cage, under its own name and with no band — the way landmarks.py
    ships neck_breadth_min beside the unresolved cervicale.
    """
    ctx = _context(v, faces, landmarks, phenotype, local_changes)
    v, S = ctx['v'], ctx['S']
    men, why = _lm_frac(ctx, 'menton')
    if men is None:
        return _unresolved('the gonial angle needs menton: ' + why)
    M3 = np.asarray(ctx['lm']['menton']['point'], np.float64)
    try:
        C3 = _bone_head('jaw', ctx['phenotype'], ctx['local_changes'])
    except Exception as e:  # noqa: BLE001
        return _unresolved('the rig did not yield a jaw pivot: %s: %s' % (type(e).__name__, e))
    wj = _bone_weight('jaw')

    C = np.array([C3[1], C3[2]])
    M = np.array([M3[1], M3[2]])
    chord = M - C
    L = float(np.linalg.norm(chord))
    if L <= 0:
        return _unresolved('the jaw pivot and menton project to the same sagittal point')
    u = chord / L
    nrm = np.array([-u[1], u[0]])
    if nrm[0] < 0:  # make +normal point POSTERIOR (+y)
        nrm = -nrm

    ops = {}
    picks = {}
    for cut in JAW_WEIGHT_CUTS:
        sel = np.nonzero((wj > cut) & (v[:, 0] > 1e-6))[0]
        if len(sel) < 8:
            ops['jaw_weight_%.2f' % cut] = None
            continue
        P = np.stack([v[sel, 1], v[sel, 2]], 1)
        dev = (P - C) @ nrm
        j = int(np.argmax(dev))
        G = P[j]
        a, b = C - G, M - G
        na, nb = np.linalg.norm(a), np.linalg.norm(b)
        if na <= 0 or nb <= 0:
            ops['jaw_weight_%.2f' % cut] = None
            continue
        ops['jaw_weight_%.2f' % cut] = math.degrees(math.acos(float(np.clip(a @ b / (na * nb), -1.0, 1.0))))
        picks['jaw_weight_%.2f' % cut] = {
            'vertex': int(sel[j]),
            'n_support': int(len(sel)),
            'point_m': [float(x) for x in v[sel[j]]],
            'deviation_from_chord_mm': float(dev[j] * 1000.0),
        }

    # THE DIAGNOSIS, measured rather than argued: how far below menton the jaw support
    # reaches on the midline. A mandible ends at menton.
    over = {}
    for cut in JAW_WEIGHT_CUTS:
        near = np.nonzero((wj > cut) & (np.abs(v[:, 0]) <= 0.010))[0]
        over['jaw_weight_%.2f' % cut] = None if not len(near) else float((M3[2] - v[near, 2].min()) * 1000.0)

    vals = [x for x in ops.values() if x is not None]
    spread = _spread(vals)
    width = BANDS['gonial_angle']['width_deg']
    rec = _unresolved(
        "gonion does not exist on this cage. MakeHuman's jaw bone is a single midline "
        'hinge segment carrying the condylion-menton CHORD, so the rig has no corner; and '
        'the surface construction that would supply one moves the angle over %.1f degrees '
        'across the jaw skinning-weight cut (%s), against a printed band width of %.0f. The '
        'cause is measured in submental_overreach_mm: the jaw support reaches up to %.1f mm '
        "BELOW menton on the midline, so it is not the mandible's own surface."
        % (
            spread,
            ', '.join('%.1f' % x for x in vals) or 'none resolved',
            width,
            max([x for x in over.values() if x is not None] or [float('nan')]),
        ),
        operationalisations=ops,
        operationalisation_spread_deg=spread,
        band_width_deg=width,
        gonion_picks=picks,
        submental_overreach_mm=over,
        condylion_sagittal_mm=[float(C[0] * 1000.0), float(C[1] * 1000.0)],
        condylion_anchor='rig bone "jaw" head; its parent is "head" (MEASURED), so the head '
        'of that bone IS the temporomandibular pivot',
        menton_sagittal_mm=[float(M[0] * 1000.0), float(M[1] * 1000.0)],
        menton_anchor=ctx['lm']['menton']['anchor'],
        # the geometric neighbour that IS well defined, shipped under its own name
        condylion_menton_chord={
            'length_mm': L * 1000.0,
            'length_frac_stature': L / S,
            'sagittal_tilt_deg': math.degrees(math.atan2(chord[0], -chord[1])),
            'is_not': 'a gonial angle. It is the chord the gonial corner would sit off, and '
            'it carries no printed band.',
        },
        band=dict(BANDS['gonial_angle']),
        sign_convention=SIGN_CONVENTION,
    )
    return rec
