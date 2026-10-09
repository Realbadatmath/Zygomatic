# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Where a measuring plane sits: rings, the ear top, height bands and the limb axes.

Moved verbatim out of the old single-file measure.py (lines 800-957).
"""

import numpy as np

from zyg_workflows.geom import mesh_skeletons as MS
from zyg_workflows.geom.anthro.measure.constants import _zyg_log


# ---------------------------------------------------------------------------------
# anchors
# ---------------------------------------------------------------------------------
def _ring_anchor(v, label, side=None):
    """Displacement-weighted centroid of a MakeHuman measure-* ring, optionally one side.

    The centroid of a ring of surface points sits INSIDE the limb, which is what a
    'nearest loop' selection wants — a surface landmark would sit on the contour of
    whichever loop it belongs to and give no separation at all.
    """
    try:
        idx, w = MS._morph_support(label)
    except RuntimeError:
        return None
    if side:
        keep = (v[idx, 0] > 0) if side == 'l' else (v[idx, 0] < 0)
        idx, w = idx[keep], w[keep]
        if not len(idx):
            return None
    return np.average(np.asarray(v, np.float64)[idx], axis=0, weights=w)


def _ear_top_frac(v, zmin, H):
    """Top of the ear, from the ear morph support, as a fraction of stature.

    Needed because ANSUR head breadth is explicitly "above the ears" and the ear is a real
    lateral bulge on this cage. Anchored to anny's own ear targets rather than to a fixed
    fraction so it tracks a head-scale morph. Returns None if the targets are absent.
    """
    idx = []
    for lab in (
        'l-ear-scale-incr',
        'r-ear-scale-incr',
        'l-ear-flap-incr',
        'r-ear-flap-incr',
        'l-ear-wing-incr',
        'r-ear-wing-incr',
    ):
        try:
            idx.append(MS._morph_support(lab)[0])
        except RuntimeError as _exc:
            _zyg_log.debug('ear target %s has no morph support: %s', lab, _exc)
    if not idx:
        return None
    idx = np.unique(np.concatenate(idx))
    return float(((np.asarray(v, np.float64)[idx, 2] - zmin) / H).max())


def _band(anchor, lo, hi, ear_top, crotch_frac, lm=None):
    """Apply the anatomical floors a survey definition demands to a HOUSE search band."""
    why = []
    if anchor.get('landmark_band'):
        name, dlo, dhi = anchor['landmark_band']
        r = (lm or {}).get(name) or {}
        if r.get('frac_stature') is None:
            return None, None, 'band anchor landmark %r unresolved' % name
        c = r['frac_stature']
        lo, hi = c + dlo, c + dhi
        why.append('band anchored on %s at %.4f of stature (HOUSE offsets %+.3f/%+.3f)' % (name, c, dlo, dhi))
    if anchor.get('above_ears') and ear_top is not None:
        if ear_top > lo:
            lo = ear_top
            why.append(
                'floor raised to the top of the ear morph support (%.4f of '
                'stature) because the definition says "above the ears"' % ear_top
            )
        if lo >= hi:
            return (
                None,
                None,
                'ear support reaches %.4f of stature, above the band '
                'ceiling %.4f — no cranial band left' % (ear_top, hi),
            )
    if anchor.get('above_crotch'):
        if crotch_frac is None:
            # A floor that could not be applied SAYS it could not be applied. Silence here
            # is indistinguishable from a floor that ran and changed nothing.
            why.append(
                'CROTCH FLOOR NOT APPLIED: the crotch landmark is unresolved on '
                'this mesh, so the band keeps its declared floor %.4f' % lo
            )
        else:
            if crotch_frac > lo:
                lo = crotch_frac
                why.append(
                    'floor raised to the resolved crotch height (%.4f of stature); '
                    'below it the torso scope selects ONE LEG, not the trunk' % crotch_frac
                )
            if lo >= hi:
                return None, None, ('crotch at %.4f of stature is above the band ceiling %.4f' % (crotch_frac, hi))
    if anchor.get('above_trochanterion'):
        fr = []
        for nm in ('trochanterion_l', 'trochanterion_r'):
            r = (lm or {}).get(nm) or {}
            if r.get('frac_stature') is None:
                return (
                    None,
                    None,
                    (
                        'band floor landmark %r is unresolved, so the trochanterion floor '
                        'cannot be placed. REFUSING to fall back to a lower floor: on this '
                        'cage the outer thigh is wider than the hip (landmarks.py measures '
                        'the widest lateral point of the pelvis-and-thigh region at 0.43 of '
                        'stature, 0.08 BELOW ANSUR trochanterion), so any band reaching below '
                        'the greater trochanter returns a thigh spread wearing the name of a '
                        'hip breadth.' % nm
                    ),
                )
            fr.append(float(r['frac_stature']))
        t = max(fr)
        if t > lo:
            lo = t
            why.append(
                'floor raised to the resolved trochanterion (%.4f of stature, the '
                'higher of left %.4f and right %.4f) because the greater trochanter '
                'is the inferior limit of the hip — below it the lateral silhouette '
                'of this cage is thigh, not hip' % (t, fr[0], fr[1])
            )
        else:
            why.append(
                'trochanterion sits at %.4f of stature, at or below the band floor '
                '%.4f already in force, so the floor is unchanged' % (t, lo)
            )
        if lo >= hi:
            return (
                None,
                None,
                ('trochanterion at %.4f of stature is at or above the band ceiling %.4f — no hip band left' % (t, hi)),
            )
    return lo, hi, '; '.join(why) or None


def _limb_axes(coco):
    """Limb axes as joint-centre to joint-centre directions.

    A joint centre is the honest anchor for an AXIS even though it is not a surface
    landmark: ISO 18825-2 asks for a plane perpendicular to the limb, and the limb's
    direction is a segment property, not a skin property.
    """
    if not coco:
        return {}
    k = {n: np.asarray(coco[n], np.float64) for n in coco}
    ax = {}
    for s in ('left', 'right'):
        p = s[0]
        ax['upperarm_%s' % p] = (k['%s_shoulder' % s], k['%s_elbow' % s])
        ax['forearm_%s' % p] = (k['%s_elbow' % s], k['%s_wrist' % s])
        ax['thigh_%s' % p] = (k['%s_hip' % s], k['%s_knee' % s])
        ax['shank_%s' % p] = (k['%s_knee' % s], k['%s_ankle' % s])
    sh = 0.5 * (k['left_shoulder'] + k['right_shoulder'])
    ear = 0.5 * (k['left_ear'] + k['right_ear'])
    ax['neck'] = (sh, ear)
    for s in ('left', 'right'):
        p = s[0]
        ax['elbow_%s' % p] = (k['%s_shoulder' % s], k['%s_wrist' % s])
    return ax
