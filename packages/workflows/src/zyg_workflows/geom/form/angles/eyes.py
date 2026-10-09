# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Canthal tilt, the palpebral fissure axis and the orbital long axis."""

from zyg_workflows.geom.form.angles.base import (
    BANDS,
    _context,
    _spread,
    _strict,
    _target_displacement,
    _unresolved,
    math,
    np,
)
from zyg_workflows.geom.form.angles.trunk_limb import (
    _local_change_labels,
)


# ---------------------------------------------------------------------------------
# (5) CANTHAL TILT and the palpebral fissure axis
# ---------------------------------------------------------------------------------
def _canthi(ctx, side):
    """The two canthi of one eye, from MakeHuman's own eye-corner targets.

    WHICH TARGET IS WHICH IS A MEASUREMENT, NOT A READING OF THE LABEL. MakeHuman ships
    'l-eye-corner1-up' and 'l-eye-corner2-up' and the names do not say which corner is
    which. MEASURED on the anny neutral: corner1's support spans |x| 38.2-51.0 mm and
    corner2's spans |x| 7.8-28.0 mm, so corner1 is LATERAL and corner2 is MEDIAL by two
    disjoint intervals. This function re-derives that per mesh rather than hardcoding it,
    and REFUSES if the two supports overlap in |x|, because then the assignment would be a
    coin toss.

    Two point conventions are returned, and they are the operationalisations the resolution
    test runs on:
      'peak'      the vertex the target displaces FURTHEST. A target named for a corner has
                  its maximum effect at that corner, so this is the corner itself.
      'centroid'  the displacement-weighted centroid of the support, which is the
                  convention landmarks.py uses for RINGS. On a corner it smears the point
                  across the patch around it, which is exactly why it is here: the
                  disagreement between the two is the construction ambiguity.
    """
    v = ctx['v']
    pre = 'l' if side == 'left' else 'r'
    sgn = 1.0 if side == 'left' else -1.0
    got = {}
    for tag, label in (('corner1', pre + '-eye-corner1-up'), ('corner2', pre + '-eye-corner2-up')):
        d = _target_displacement(label, ctx['phenotype'])
        dn = np.linalg.norm(d, axis=1)
        dn = np.where(v[:, 0] * sgn > 1e-6, dn, 0.0)
        idx = np.nonzero(dn > 3e-4)[0]
        if len(idx) < 8:
            return None, ('target %r displaces only %d vertices on the %s side' % (label, len(idx), side))
        got[tag] = {
            'label': label,
            'peak': v[int(np.argmax(dn))],
            'centroid': np.average(v[idx], axis=0, weights=dn[idx]),
            'n': int(len(idx)),
            'xabs_span_mm': [float(np.abs(v[idx, 0]).min() * 1000.0), float(np.abs(v[idx, 0]).max() * 1000.0)],
            'peak_disp_mm': float(dn.max() * 1000.0),
        }
    a, b = got['corner1']['xabs_span_mm'], got['corner2']['xabs_span_mm']
    if not (a[0] > b[1] or b[0] > a[1]):
        return None, (
            'the two eye-corner supports overlap in |x| (corner1 %.1f-%.1f mm, '
            'corner2 %.1f-%.1f mm), so which one is the lateral canthus cannot be '
            'decided by measurement' % (a[0], a[1], b[0], b[1])
        )
    lat, med = ('corner1', 'corner2') if a[0] > b[1] else ('corner2', 'corner1')
    return {
        'lateral': got[lat],
        'medial': got[med],
        'assignment': '%s is LATERAL (|x| %.1f-%.1f mm), %s is MEDIAL (|x| %.1f-%.1f '
        'mm) — disjoint, measured on this mesh'
        % (
            got[lat]['label'],
            got[lat]['xabs_span_mm'][0],
            got[lat]['xabs_span_mm'][1],
            got[med]['label'],
            got[med]['xabs_span_mm'][0],
            got[med]['xabs_span_mm'][1],
        ),
    }, None


def canthal_tilt(v, faces, landmarks=None, phenotype=None, local_changes=None):
    """Canthal tilt: the coronal inclination of the medial-to-lateral canthus line.

    HeadNeck p.43 makes two claims in one line and this cage answers one of them:
      A CEILING, tilt <= +10 degrees. RESOLVED and passing with a wide margin.
      A SIGN, "slightly positive". NOT RESOLVED: the two anchor conventions (peak
        displacement versus weighted centroid) straddle zero by about 2.5 degrees on the
        neutral, so the sign is a property of which convention you pick and not of the mesh.
    Reporting them separately is the point. Collapsing them into one pass/fail would have
    to choose the flattering convention, which is the exact failure this file exists to
    prevent.

    Sign: POSITIVE when the LATERAL canthus is SUPERIOR to the medial one.
    The tilt is measured in the CORONAL plane (x against z), which is where the rule is
    drawn; the record also carries the intercanthal chord length, because HeadNeck p.42/p.95
    ties eye width to intercanthal distance and a downstream gate will want it.
    """
    ctx = _context(v, faces, landmarks, phenotype, local_changes)
    out = {
        'per_side': {},
        'band': dict(BANDS['canthal_tilt']),
        'sign_convention': 'POSITIVE when the LATERAL canthus is SUPERIOR to the medial',
        'anchor_kind': 'makehuman morph target, point convention swept',
    }
    ops = {}
    for side, sgn in (('left', 1.0), ('right', -1.0)):
        c, why = _canthi(ctx, side)
        if c is None:
            return _unresolved('the canthi did not resolve: ' + why, **out)
        per = {'assignment': c['assignment']}
        for conv in ('peak', 'centroid'):
            med = np.asarray(c['medial'][conv], np.float64)
            lat = np.asarray(c['lateral'][conv], np.float64)
            dx = (lat[0] - med[0]) * sgn * 1000.0
            dz = (lat[2] - med[2]) * 1000.0
            if dx <= 0:
                return _unresolved(
                    'the %s lateral canthus is not lateral of the medial one under the %r '
                    'convention (dx = %.2f mm)' % (side, conv, dx),
                    **out,
                )
            per[conv] = {
                'tilt_deg': math.degrees(math.atan2(dz, dx)),
                'intercanthal_chord_mm': float(math.hypot(dx, dz)),
                'medial_m': [float(x) for x in med],
                'lateral_m': [float(x) for x in lat],
            }
            ops.setdefault(conv, []).append(per[conv]['tilt_deg'])
        per['support'] = {
            k: {kk: c[k][kk] for kk in ('label', 'n', 'xabs_span_mm', 'peak_disp_mm')} for k in ('medial', 'lateral')
        }
        out['per_side'][side] = per

    ops = {k: float(np.mean(x)) for k, x in ops.items()}
    spread = _spread(ops.values())
    width = BANDS['canthal_tilt']['width_deg']
    primary = ops['peak']
    ceiling = BANDS['canthal_tilt']['bands']['both'][1]

    out.update(
        {
            'operationalisations': ops,
            'operationalisation_spread_deg': spread,
            'band_width_deg': width,
            'claim': 'constructed',
            'primary_deg': primary,
            'primary_convention': 'peak displacement of the eye-corner target',
            'ceiling_deg': ceiling,
            # THE CEILING resolves when the whole spread sits under it: every convention agrees.
            'ceiling_resolved': bool(max(ops.values()) <= ceiling and min(ops.values()) >= -ceiling),
            'ceiling_verdict': ('in_band' if max(abs(x) for x in ops.values()) <= ceiling else 'above_band'),
            # THE SIGN resolves only when every convention agrees on it.
            'sign_resolved': bool(min(ops.values()) > 0.0 or max(ops.values()) < 0.0),
            'sign_positive': bool(primary > 0.0),
        }
    )
    strict = _strict()
    resolved = (not strict) or spread <= width
    out['resolved'] = bool(resolved)
    out['value_deg'] = primary if resolved else None
    # NOTE the two verdict fields and the reason there are two. 'ceiling_verdict' answers
    # only the |tilt| <= 10 half of HeadNeck p.43 and is two-sided. 'band_verdict', applied
    # by measure_angles() against the printed (0, 10) band, answers the SIGN and the ceiling
    # together, so a mesh with a small negative tilt reads ceiling_verdict='in_band' and
    # band_verdict='below_band'. That is not a contradiction, it is the two claims the page
    # makes reported separately, which is the whole point of splitting them.
    if not out['sign_resolved']:
        out['sign_reason'] = (
            'the two point conventions straddle zero (%s), so "slightly positive" is a '
            'property of the convention and not of this mesh; the CEILING half of the rule '
            'is unaffected because both conventions are far inside it'
            % ', '.join('%s %+.3f' % (k, x) for k, x in sorted(ops.items()))
        )
    if not resolved:
        out['reason'] = 'the point conventions disagree by %.2f degrees against a printed tolerance of %.0f' % (
            spread,
            width,
        )
    return out


# ---------------------------------------------------------------------------------
# (6) ORBITAL LONG AXIS — UNRESOLVED; the palpebral fissure axis reported beside it
# ---------------------------------------------------------------------------------
def orbital_long_axis(v, faces, landmarks=None, phenotype=None, local_changes=None):
    """The long axis of the BONY ORBITAL APERTURE, 20 degrees from horizontal
    (FacialExpr p.20). UNRESOLVED, and the neighbour that IS measurable is reported beside
    it under a different name so the two can never be confused.

    An AXIS OF AN APERTURE NEEDS A RING. That is the whole difficulty and it is not a
    threshold question:
      * anny's 256-label local-change vocabulary matches ZERO targets for 'orbit' (measured
        here), so there is no morph support to anchor to.
      * The orbital MARGIN does read as relief on this cage — the head-region probe measures
        +20.03 mm at the margin, well over the cage's own null of 2.45e-3 of stature — but a
        relief PATCH is not an aperture. An ellipse fitted to a patch returns the patch's
        aspect, and its long axis is whatever the patch happens to be shaped like.
      * The book's number is a POINT VALUE with no printed tolerance, so the
        operationalisation-spread test has nothing to run against: there is no width to
        compare a spread to. Resolution here rests entirely on whether an anchor exists.

    WHAT IS REPORTED INSTEAD: the PALPEBRAL FISSURE axis, medial to lateral canthus, in the
    coronal plane. It is a soft-tissue aperture and a different quantity from the bony orbit
    — on a living face the palpebral fissure is far shallower than 20 degrees — so it is
    shipped under its own key, in the way landmarks.py ships neck_breadth_min beside the
    unresolved cervicale "precisely so nobody calls it cervicale".
    """
    ctx = _context(v, faces, landmarks, phenotype, local_changes)
    labels = _local_change_labels()
    ct = canthal_tilt(v, faces, landmarks=ctx['lm'], phenotype=ctx['phenotype'], local_changes=ctx['local_changes'])
    return _unresolved(
        "the orbital long axis is the axis of the BONY ORBITAL APERTURE. anny's %d-label "
        'vocabulary matches ZERO targets for "orbit", and the orbital margin resolves on '
        'this cage only as a relief PATCH, which has an aspect but not an aperture axis. '
        'The book prints a single value with no tolerance, so even the spread test cannot '
        'run.' % len(labels),
        vocabulary_size=len(labels),
        vocabulary_matches={
            'orbit': [n for n in labels if 'orbit' in n.lower()],
            'eye': len([n for n in labels if 'eye' in n.lower()]),
        },
        band=dict(BANDS['orbital_long_axis']),
        measurable_neighbour={
            'name': 'palpebral_fissure_axis',
            'value_deg': ct.get('value_deg'),
            'resolved': ct.get('resolved'),
            'is_not': 'the orbital long axis. It is the SOFT-TISSUE eye opening, which on a '
            'living face is far shallower than the 20 degrees FacialExpr p.20 '
            'prints for the bony orbit.',
        },
    )
