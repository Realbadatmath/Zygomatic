# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The nasolabial angle and ear-axis / nose-dorsum parallelism."""

from zyg_workflows.geom.form.angles.base import (
    BANDS,
    SIGN_CONVENTION,
    _context,
    _spread,
    _strict,
    _target_displacement,
    _unresolved,
    _verdict,
    math,
    np,
)
from zyg_workflows.geom.form.angles.face import (
    face_profile,
)


# ---------------------------------------------------------------------------------
# (7) NASOLABIAL ANGLE — UNRESOLVED; the columella is the missing reference
# ---------------------------------------------------------------------------------
def nasolabial_angle(v, faces, landmarks=None, phenotype=None, local_changes=None, profile=None):
    """The nasolabial angle at subnasale. UNRESOLVED — the columella is not a feature here.

    HeadNeck p.77 prints 92-98 for men and 95-105 for women, so the narrower band is SIX
    DEGREES WIDE, and that width is what the construction has to beat.

    THE VERTEX AND ONE RAY RESOLVE CLEANLY. Subnasale and labiale superius are turning
    points of the midsagittal profile — subnasale is the first local maximum of y walking
    down from the nose tip, labiale superius the first local minimum below it — and
    face_profile() finds both without any search window, reporting the prominence of each.

    THE OTHER RAY DOES NOT. The angle's second ray is the COLUMELLA TANGENT, and a columella
    is a feature the profile between subnasale and pronasale would have to carry. It does
    not: MEASURED on the anny neutral, that stretch is a smooth 14.8 mm arc holding seven
    profile vertices, and taking each of them in turn as "the columella point" gives
    152.98, 142.29, 123.04, 114.93, 113.95, 117.01 and 121.45 degrees — a spread of 39.03
    against a 6 degree band, i.e. six and a half band widths. Averaging seven numbers that
    disagree by six band widths does not produce a measurement, so nothing is reported as
    one. The same sweep on the four issued characters spreads 26.75 to 41.76 degrees.

    Every one of those references is swept here per body rather than being chosen. If a
    future cage carries a columella — a real inflection between subnasale and the tip — the
    spread will close on its own and this will resolve without a code change, which is the
    property that makes the refusal a measurement rather than a verdict.
    """
    ctx = _context(v, faces, landmarks, phenotype, local_changes)
    prof = profile if profile is not None else face_profile(v, faces, landmarks=ctx['lm'])
    if not prof.get('resolved'):
        return _unresolved('the nasolabial angle needs the face profile: ' + prof.get('reason', '?'), profile=prof)
    pts = prof['points']
    for need in ('subnasale', 'labiale_superius', 'pronasale'):
        if need not in pts:
            return _unresolved(
                'the nasolabial angle needs %s, which the profile did not turn at: %s'
                % (need, prof['unresolved_points'].get(need, 'absent')),
                profile_points=sorted(pts),
            )

    H = np.asarray(prof['fz'], np.float64)
    Y = np.asarray(prof['y_over_stature'], np.float64)
    i_sub = pts['subnasale']['index']
    i_pro = pts['pronasale']['index']
    i_lab = pts['labiale_superius']['index']
    S = ctx['S']

    def ang(i_col):
        a = np.array([Y[i_col] - Y[i_sub], H[i_col] - H[i_sub]])
        b = np.array([Y[i_lab] - Y[i_sub], H[i_lab] - H[i_sub]])
        na, nb = np.linalg.norm(a), np.linalg.norm(b)
        if na <= 0 or nb <= 0:
            return None
        return math.degrees(math.acos(float(np.clip(a @ b / (na * nb), -1.0, 1.0))))

    ops = {}
    for i in range(i_sub + 1, i_pro + 1):
        ops['columella_at_%+.4f' % H[i]] = ang(i)
    if len(ops) < 2:
        return _unresolved(
            'the profile carries only %d vertices between subnasale and pronasale, so the '
            'columella reference cannot even be swept' % len(ops),
            subnasale=pts['subnasale'],
            pronasale=pts['pronasale'],
        )

    vals = [x for x in ops.values() if x is not None]
    spread = _spread(vals)
    width = BANDS['nasolabial_angle']['width_deg']
    primary_key = 'columella_at_%+.4f' % H[i_pro]
    strict = _strict()
    resolved = (not strict) or spread <= width
    rec = {
        'resolved': bool(resolved),
        'value_deg': ops[primary_key] if resolved else None,
        'primary_deg': ops[primary_key],
        'primary_convention': 'the subnasale-to-pronasale chord as the columella reference',
        'operationalisations': ops,
        'operationalisation_spread_deg': spread,
        'band_width_deg': width,
        'band': dict(BANDS['nasolabial_angle']),
        'claim': 'constructed',
        'subnasale': pts['subnasale'],
        'labiale_superius': pts['labiale_superius'],
        'pronasale': pts['pronasale'],
        'columella_span_mm': float(abs(H[i_pro] - H[i_sub]) * S * 1000.0),
        'columella_samples': int(i_pro - i_sub),
        'sign_convention': SIGN_CONVENTION,
    }
    if not resolved:
        rec['reason'] = (
            "the columella is not a feature on this cage. The angle's vertex (subnasale) "
            'and lip ray (labiale superius) are clean profile turning points, but the '
            '%d defensible columella references between subnasale and pronasale spread the '
            'angle over %.1f degrees against a printed band %.0f degrees wide.' % (len(ops), spread, width)
        )
    return rec


# ---------------------------------------------------------------------------------
# (8) EAR AXIS vs NOSE DORSUM
# ---------------------------------------------------------------------------------
def _ear_axis(ctx, side):
    """The ear's long axis in the sagittal plane, from MakeHuman's own ear SCALE targets.

    THE CONSTRUCTION, and why it is not the support's z-extremes. A scale target displaces
    each vertex in proportion to its offset from the region's centre, so the vertices it
    moves furthest UP and furthest DOWN are the region's own superior and inferior poles.
    That is a property of what a scale target IS, and it does not depend on where the
    support's blend region happens to peter out — which matters, because the SUPPORT's
    z-extremes give -12.06 and -6.89 degrees on the neutral (blend contamination) while the
    DISPLACEMENT extremes give +1.98 and +1.97 from two independent targets, agreeing to
    0.01 degrees.

    TRANSLATION TARGETS ARE EXCLUDED and the reason is measured: l-ear-trans-up displaces
    the ear core uniformly, so its extreme-displacement vertices sit in the blend region and
    the "axis" comes out at +51.31 degrees. A uniform displacement carries no shape
    information; only a scale target does.
    """
    v = ctx['v']
    pre = 'l' if side == 'left' else 'r'
    sgn = 1.0 if side == 'left' else -1.0
    ops = {}
    ends = {}
    for label in (pre + '-ear-scale-vert-incr', pre + '-ear-scale-incr'):
        try:
            d = _target_displacement(label, ctx['phenotype'])
        except RuntimeError as e:
            return None, str(e)
        sel = np.nonzero((np.linalg.norm(d, axis=1) > 3e-4) & (v[:, 0] * sgn > 1e-6))[0]
        if len(sel) < 20:
            return None, ('ear target %r displaces only %d vertices on the %s side' % (label, len(sel), side))
        hi = int(sel[int(np.argmax(d[sel, 2]))])
        lo = int(sel[int(np.argmin(d[sel, 2]))])
        ch = v[hi] - v[lo]
        if abs(ch[2]) < 1e-4:
            return None, (
                'ear target %r puts its two displacement poles at the same height, so it carries no long axis' % label
            )
        ops[label] = math.degrees(math.atan2(ch[1], ch[2]))
        ends[label] = {
            'superior_vertex': hi,
            'inferior_vertex': lo,
            'chord_mm': float(math.hypot(ch[1], ch[2]) * 1000.0),
            'n_support': int(len(sel)),
        }
    return {'operationalisations': ops, 'ends': ends}, None


def ear_nose_parallelism(v, faces, landmarks=None, phenotype=None, local_changes=None, profile=None):
    """HeadNeck p.69: the ear's long axis runs parallel to the dorsum of the nose, within
    about 8 degrees. RESOLVED — and it FAILS on every body we ship.

    THE TWO AXES, both in the sagittal plane and both signed the same way (POSITIVE when the
    superior end lies POSTERIOR of the inferior end):
      EAR      the chord between the two poles of MakeHuman's ear SCALE targets. Two
               independent targets, agreeing to 0.01 degrees on the neutral. See _ear_axis()
               for why a scale target's displacement extremes are the ear's own poles and
               why translation targets are excluded.
      DORSUM   the chord from NASION to PRONASALE, both turning points of the midsagittal
               profile found without a search window. The dorsum is convex, so the record
               also carries the least-squares direction over the whole dorsum segment as the
               second operationalisation; the spread between chord and fit is the
               construction ambiguity this rule is tested against.

    THE FINDING. Measured on the anny neutral the ear stands at +1.98 degrees, essentially
    vertical, while the dorsum leans back at about +26. The difference is roughly 24 degrees
    against a printed tolerance of 8, on every body, and the spread across a 12-year-old and
    three adults is under 2 degrees — so it is a property of the anny base mesh and not of
    any character's morphs. This is the one printed band in this file that both resolves and
    discriminates, and what it discriminates against is our own base asset.
    """
    ctx = _context(v, faces, landmarks, phenotype, local_changes)
    prof = profile if profile is not None else face_profile(v, faces, landmarks=ctx['lm'])
    if not prof.get('resolved'):
        return _unresolved('the nose dorsum needs the face profile: ' + prof.get('reason', '?'), profile=prof)
    pts = prof['points']
    if 'nasion' not in pts or 'pronasale' not in pts:
        return _unresolved(
            'the nose dorsum needs nasion and pronasale; the profile turned at %s' % sorted(pts),
            profile_points=sorted(pts),
            unresolved_points=prof['unresolved_points'],
        )

    H = np.asarray(prof['fz'], np.float64)
    Y = np.asarray(prof['y_over_stature'], np.float64)
    i_nas, i_pro = pts['nasion']['index'], pts['pronasale']['index']
    lo, hi = min(i_nas, i_pro), max(i_nas, i_pro)
    dorsum = {}
    ch = np.array([Y[i_nas] - Y[i_pro], H[i_nas] - H[i_pro]])
    dorsum['nasion_pronasale_chord'] = math.degrees(math.atan2(ch[0], ch[1]))
    seg = np.stack([Y[lo : hi + 1], H[lo : hi + 1]], 1)
    if len(seg) >= 3:
        P = seg - seg.mean(0)
        w, V = np.linalg.eigh(np.cov(P.T))
        a = V[:, int(np.argmax(w))]
        if a[1] < 0:
            a = -a
        dorsum['dorsum_least_squares_fit'] = math.degrees(math.atan2(a[0], a[1]))

    ears = {}
    for side in ('left', 'right'):
        e, why = _ear_axis(ctx, side)
        if e is None:
            return _unresolved('the ear axis did not resolve: ' + why, dorsum=dorsum)
        ears[side] = e
    ear_ops = {}
    for side in ears:
        for k, x in ears[side]['operationalisations'].items():
            ear_ops.setdefault(k.lstrip('lr').lstrip('-'), []).append(x)
    ear_ops = {k: float(np.mean(x)) for k, x in ear_ops.items()}

    ops = {}
    for ek, ev in sorted(ear_ops.items()):
        for dk, dv in sorted(dorsum.items()):
            ops['%s|%s' % (ek, dk)] = abs(ev - dv)
    spread = _spread(ops.values())
    width = BANDS['ear_nose_parallelism']['width_deg']
    primary = abs(ear_ops['ear-scale-vert-incr'] - dorsum['nasion_pronasale_chord'])
    strict = _strict()
    resolved = (not strict) or spread <= width
    rec = {
        'resolved': bool(resolved),
        'value_deg': primary if resolved else None,
        'primary_deg': primary,
        'primary_convention': 'ear vertical-scale poles against the nasion-pronasale chord',
        'ear_axis_deg': ear_ops,
        'ear_axis_spread_deg': _spread(ear_ops.values()),
        'ear_ends': {s: ears[s]['ends'] for s in ears},
        'dorsum_axis_deg': dorsum,
        'dorsum_spread_deg': _spread(dorsum.values()),
        'dorsum_samples': int(hi - lo + 1),
        'operationalisations': ops,
        'operationalisation_spread_deg': spread,
        'band_width_deg': width,
        'band': dict(BANDS['ear_nose_parallelism']),
        'claim': 'constructed',
        'nasion': pts['nasion'],
        'pronasale': pts['pronasale'],
        'sign_convention': SIGN_CONVENTION,
    }
    rec['verdict'] = _verdict(rec['value_deg'], *BANDS['ear_nose_parallelism']['bands']['both'])
    if not resolved:
        rec['reason'] = (
            'the ear and dorsum operationalisations disagree by %.2f degrees '
            'against a printed tolerance of %.0f' % (spread, width)
        )
    return rec
