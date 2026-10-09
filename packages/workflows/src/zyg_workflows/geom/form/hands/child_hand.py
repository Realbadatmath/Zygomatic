# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The child hand - three DIRECTION tests, no threshold anywhere.

Moved verbatim out of the old single-file hands.py (lines 2957-3327).
"""

import numpy as np

from zyg_workflows.geom.form.hands.rig import (
    PASS,
    WARN,
    FAIL,
    UNMEASURABLE,
    UNRESOLVED,
    HOUSE,
    CANON,
    FINGERS,
    DIGIT_BONES,
    RIDGE_SLAB_FRAC,
    _side,
    _segment_idx,
    _unit,
    resolve_hand,
)
from zyg_workflows.geom.form.hands.provenance import (
    _rec,
)


# ---------------------------------------------------------------------------------
# The child hand — three DIRECTION tests, no threshold anywhere
#
# AFS p.185 and p.178 give directions, not numbers: a child's fingers are proportionally
# THICKER, a child's knuckles do NOT protrude the way an adult's do (a dimple in
# infancy, a knuckle in the adult), and a child's hand is SMALLER relative to the head.
# A direction has no tolerance to tune, but it does need a bar to be measured against,
# and the bar here is THE SAME CHARACTER WITH ITS AGE MACRO SET TO ADULT — every other
# macro, every local morph and every bone scale held. That is a self-control: it cannot
# import another body's build, and it has no free parameter.
#
# ALREADY COVERED ELSEWHERE, so not duplicated here:
#   * hand SIZE relative to the body. geom.anthro.measure ships `hand_length`
#     (wrist_ring -> dactylion) and the `hand_length_over_stature` ANSUR ratio, and
#     geom.anthro.gates.CHILD_PROPORTION_ASSERTIONS already carries
#     ('hand_length_over_stature', 'above_or_equal') with a distal-to-proximal growth
#     argument. measure.py additionally carries `hand_frac_stature` as a pose window.
#     Nothing here re-measures any of that.
#   * the dactylion landmark itself, resolved by geom.anthro.landmarks.
#   * `foot_length_over_stature`, likewise already asserted for a child.
#   What is NEW is hand-to-HEAD (there is no head-relative hand ratio anywhere in
#   geom.anthro), finger thickness, and knuckle relief.
# ---------------------------------------------------------------------------------
# The same cut point geom.anthro.gates.t2_child_growth uses, and for the same reason:
# the CDC 2000 growth charts run to 240 months, so 20 y is where "child" stops being a
# defined population rather than a matter of taste.
CHILD_AGE_MAX_Y = 20.0
# anny's age macro for an adult. measure._age_years maps 0.5 -> 25 y and that mapping is
# verified there against the two derived characters' declared ages.
ADULT_AGE_MACRO = 0.5


def _finger_thickness(v, F, d):
    """(diameter / length) of a digit's proximal segment, and its parts.

    Diameter is twice the mean distance of the segment's majority-owned cage vertices
    from the segment's own axis, so it is a real mean radius over the whole segment and
    not a single caliper reading that a lucky vertex could set.
    """
    S = F['side']
    sel = _segment_idx(S, [DIGIT_BONES[d][1]])
    mcp, pip = F['joints'][(d, 'mcp')], F['joints'][(d, 'pip')]
    L = float(np.linalg.norm(pip - mcp))
    if L <= 0 or len(sel) < 8:
        return None
    a = (pip - mcp) / L
    P = v[sel] - mcp
    r = np.linalg.norm(P - np.outer(P @ a, a), axis=1)
    dia = 2.0 * float(r.mean())
    return {'diameter_m': dia, 'length_m': L, 'value': dia / L, 'n_vertices': len(sel)}


def _knuckle_relief(v, F, d):
    """Dorsal protrusion of one MCP over its own local collar. A SIGN, then a size.

    The dorsal surface of the finger ray is profiled along the ray in the mid-sagittal
    slab, from one proximal-segment length behind the MCP to one in front. The knuckle
    value is the highest dorsal point within +/-0.20 of that length of the MCP; the
    collar is the mean dorsal height of the two flanking stretches beyond +/-0.45. The
    difference is the relief: POSITIVE is a protruding knuckle, NEGATIVE is a dimple,
    which is the sign AFS p.185 says flips between infancy and adulthood. Normalised by
    the segment's own length so a 12-year-old's smaller hand does not read as flatter
    just for being smaller.
    """
    S = F['side']
    bones = [x for x in (DIGIT_BONES[d][0], DIGIT_BONES[d][1]) if x]
    sel = _segment_idx(S, bones)
    mcp, pip = F['joints'][(d, 'mcp')], F['joints'][(d, 'pip')]
    L = float(np.linalg.norm(pip - mcp))
    if L <= 0 or len(sel) < 24:
        return None
    a = (pip - mcp) / L
    n = F['palmar_normal']
    dor = -n - float(np.dot(-n, a)) * a
    dor = _unit(dor)
    lat = np.cross(a, dor)
    P = v[sel] - mcp
    t, u, w = P @ a, P @ dor, P @ lat
    slab = np.abs(w - np.median(w)) < RIDGE_SLAB_FRAC * (w.max() - w.min())
    edges = np.linspace(-L, L, 17)
    c = 0.5 * (edges[:-1] + edges[1:])
    prof = np.full(16, np.nan)
    for i in range(16):
        k = slab & (t >= edges[i]) & (t < edges[i + 1])
        if k.sum():
            prof[i] = float(u[k].max())
    near = prof[np.abs(c) < 0.20 * L]
    left = prof[c < -0.45 * L]
    right = prof[c > 0.45 * L]
    if np.all(np.isnan(near)) or np.all(np.isnan(left)) or np.all(np.isnan(right)):
        return None
    collar = 0.5 * (float(np.nanmean(left)) + float(np.nanmean(right)))
    rel = float(np.nanmax(near)) - collar
    return {
        'relief_m': rel,
        'segment_length_m': L,
        'value': rel / L,
        'sign': ('protruding' if rel > 0 else ('dimple' if rel < 0 else 'flat')),
        'n_vertices': len(sel),
    }


def _hand_over_head(v, faces, F):
    """hand length / head height (vertex to menton).

    Both ends come from geom.anthro.landmarks so this cannot disagree with the metric
    layer about how long a hand is or how tall a head is. measure.py registers
    `head_height_vertex_menton` and flags it survey_comparable=False (ANSUR ships
    tragion-to-vertex, not menton-to-vertex); that flag is inherited, not re-litigated.
    """
    from zyg_workflows.geom.anthro import landmarks as LMK

    lmk = LMK.resolve_landmarks(v, faces)
    vx = (lmk.get('vertex') or {}).get('point')
    mn = (lmk.get('menton') or {}).get('point')
    if vx is None or mn is None:
        return None
    hh = abs(float(np.asarray(vx, np.float64)[2] - np.asarray(mn, np.float64)[2]))
    if hh <= 0:
        return None
    return {'hand_length_m': F['hand_length_m'], 'head_height_m': hh, 'value': F['hand_length_m'] / hh}


def _child_channels(v, faces, side):
    F = resolve_hand(v, faces, side)
    th, kn = {}, {}
    for d in FINGERS:
        th[d] = _finger_thickness(v, F, d)
        kn[d] = _knuckle_relief(v, F, d)
    prot = [r for r in kn.values() if r]
    return {
        'per_finger': {
            'thickness_over_length': {d: (th[d] or {}).get('value') for d in FINGERS},
            'knuckle_relief_over_segment': {d: (kn[d] or {}).get('value') for d in FINGERS},
        },
        'scalar': {
            'knuckle_protruding_fraction': (float(np.mean([r['relief_m'] > 0 for r in prot])) if prot else None),
            'hand_over_head': (_hand_over_head(v, faces, F) or {}).get('value'),
        },
        'detail': {'thickness': th, 'knuckle': kn, 'hand_length_m': F['hand_length_m']},
    }


# (channel, required direction of CHILD vs the SAME BODY AGED TO ADULT, kind, why).
#
# A 'per_finger' channel must hold on EVERY finger. It is deliberately NOT averaged:
# a mean over four fingers turns a 2-up-2-down split into a confident verdict, and a
# split is not a direction — it is the absence of one. When the fingers disagree the
# channel comes back UNRESOLVED with the split attached, which is the honest answer and
# is exactly what happened to knuckle relief on this cage.
CHILD_HAND_ASSERTIONS = (
    (
        'thickness_over_length',
        'above',
        'per_finger',
        "AFS p.185: a child's fingers are proportionally thicker — diameter over length sits above the adult value",
    ),
    (
        'knuckle_relief_over_segment',
        'below',
        'per_finger',
        'AFS p.185: the knuckle grows into a protrusion with age, so at 12 the relief '
        "must still be BELOW the adult value. Normalised by the segment's own length, so "
        'a smaller hand cannot read as flatter merely for being smaller',
    ),
    (
        'knuckle_protruding_fraction',
        'below',
        'scalar',
        'AFS p.185 in its STRONGEST and threshold-free form: the knuckle is a DIMPLE in '
        'infancy and a PROTRUSION in the adult, so the SIGN has to change with age. This '
        'channel is the fraction of fingers whose relief is positive; in a child it must '
        "be below the adult's. If it is 1.0 at both ages the cage carries no knuckle sign "
        'information about age at all, and no magnitude argument can rescue that',
    ),
    (
        'hand_over_head',
        'below',
        'scalar',
        'AFS p.178: the hand is smaller relative to the head in a child than in an adult, '
        'because the head is nearly grown and the hand is not',
    ),
)


def measure_child_hand(phenotype, local_changes=None, bone_scales=None, side='L', anatomy=None, params=None):
    from zyg_workflows.geom import mesh_skeletons as MS

    S = _side(side)
    from zyg_workflows.geom.anthro import measure as ME

    age_y = ME._age_years(phenotype.get('age', ADULT_AGE_MACRO))

    def build(phen):
        # params= on BOTH halves. The child bar is "the same recipe with the age macro
        # moved", so the subject and the bar have to carry the same phalanx correction or
        # the direction test would be reading the correction instead of the age.
        vv, ff, _ = MS._build_mesh(phen, local_changes or None, bone_scales or None, params=params)
        vv = np.asarray(
            MS._apply_anatomy(
                vv,
                ff,
                anatomy or {},
                phenotype=phen,
                local_changes=local_changes or None,
                bone_scales=bone_scales or None,
                params=params,
            ),
            np.float64,
        )
        return vv, ff

    v0, f0 = build(dict(phenotype))
    adult = dict(phenotype)
    adult['age'] = ADULT_AGE_MACRO
    v1, f1 = build(adult)
    return {
        'side': S,
        'age_years': age_y,
        'adult_age_years': ME._age_years(ADULT_AGE_MACRO),
        'subject': _child_channels(v0, f0, S),
        'adult_bar': _child_channels(v1, f1, S),
        'stature_child_m': float(np.ptp(np.asarray(v0, np.float64)[:, 2])),
        'stature_adult_m': float(np.ptp(np.asarray(v1, np.float64)[:, 2])),
        'bar': (
            'the same recipe with the age macro moved to %.3f (%.1f y); every '
            'other macro, every local morph and every bone scale held'
            % (ADULT_AGE_MACRO, ME._age_years(ADULT_AGE_MACRO))
        ),
    }


def check_child_hand(phenotype, local_changes=None, bone_scales=None, side='L', anatomy=None, params=None):
    m = measure_child_hand(phenotype, local_changes, bone_scales, side, anatomy, params)
    if m['age_years'] >= CHILD_AGE_MAX_Y:
        return _rec(
            'child_hand',
            'mesh',
            UNMEASURABLE,
            None,
            'direction vs the adult bar',
            'the subject is %.1f y, at or past the %.0f y edge of the CDC 2000 child '
            'reference geom.anthro.gates.t2_child_growth uses, so there is no child '
            'claim to test.' % (m['age_years'], CHILD_AGE_MAX_Y),
            provenance=HOUSE,
            source='applicability window matched to geom.anthro.gates.t2_child_growth',
            # This row's provenance is HOUSE while the registry declares t5_child_hand
            # CANON, and the disagreement is real rather than an oversight: they describe
            # DIFFERENT THINGS. CANON is the provenance of the gate's CLAIM (AFS p.185 and
            # p.178, three directions) and it is what the row below carries. HOUSE is the
            # provenance of the SCOPE DECISION this row is — where we stop calling a body
            # a child. The 20 y edge is the domain of the CDC 2000 charts, but choosing to
            # inherit that domain here is ours, and no page says it. Tagging this row CANON
            # to make the two agree would be inventing a citation for a decision we made;
            # it stays at the weaker tag, and the mismatch is explained instead of hidden.
            provenance_note=(
                "HOUSE is the tag of the APPLICABILITY WINDOW, not of the gate's claim. "
                'The registry declares t5_child_hand CANON because the three direction '
                'tests come off AFS p.185 and p.178; this row makes none of them — it '
                'declines to test them on a %.1f y body. HOUSE is the weaker of the two '
                'tags and is the honest one for a scope decision that is ours.' % m['age_years']
            ),
            age_years=m['age_years'],
            channels=m['subject'],
        )
    rows, fails, unres = {}, [], []

    def _dir(a, b, want):
        return (a > b) if want == 'above' else (a < b)

    for key, want, kind, why in CHILD_HAND_ASSERTIONS:
        if kind == 'scalar':
            a = m['subject']['scalar'].get(key)
            b = m['adult_bar']['scalar'].get(key)
            if a is None or b is None:
                rows[key] = {'status': UNMEASURABLE, 'child': a, 'adult': b, 'why': why}
                unres.append(key)
                continue
            ok = _dir(a, b, want)
            rows[key] = {
                'status': (PASS if ok else FAIL),
                'kind': kind,
                'child': a,
                'adult': b,
                'required': want,
                'delta_child_minus_adult': a - b,
                'why': why,
            }
            if not ok:
                fails.append(key)
            continue
        ch = m['subject']['per_finger'][key]
        ad = m['adult_bar']['per_finger'][key]
        per = {}
        for d in FINGERS:
            a, b = ch.get(d), ad.get(d)
            per[d] = (
                {'child': a, 'adult': b, 'holds': None}
                if a is None or b is None
                else {'child': a, 'adult': b, 'holds': _dir(a, b, want), 'relative_delta': (a - b) / b if b else None}
            )
        got = [x['holds'] for x in per.values() if x['holds'] is not None]
        if not got:
            st = UNMEASURABLE
        elif all(got):
            st = PASS
        elif not any(got):
            st = FAIL
        else:
            # The fingers disagree. That is not a direction; it is the absence of one.
            st = UNRESOLVED
        rows[key] = {
            'status': st,
            'kind': kind,
            'required': want,
            'per_finger': per,
            'n_holding': sum(1 for x in got if x),
            'n_fingers': len(got),
            'largest_relative_delta': max(
                (abs(x['relative_delta']) for x in per.values() if x.get('relative_delta') is not None), default=None
            ),
            'why': why,
        }
        if st == FAIL:
            fails.append(key)
        elif st in (UNRESOLVED, UNMEASURABLE):
            unres.append(key)
    return _rec(
        'child_hand',
        'mesh',
        (FAIL if fails else (WARN if unres else PASS)),
        len(fails),
        'count of failed direction assertions',
        "three directions, no magnitudes: a child's fingers are proportionally thicker "
        "(AFS p.185), a child's knuckles have not yet begun to protrude (AFS p.185, "
        "sign flips dimple->knuckle with age) and a child's hand is small relative to "
        'the head (AFS p.178). The bar is %s, so nothing is fitted and nothing is '
        'imported from another body.' % m['bar'],
        band=None,
        threshold=0,
        provenance=CANON,
        severity='warn',
        severity_why=(
            'CANON, so capped at warn. No survey of child knuckle relief, child finger '
            'thickness or child hand-to-head was found, so there is no MEASURED source '
            'for a CANON threshold to be overruled by — but the house ranking puts a '
            'book below a survey and the conservative reading is a warning. The '
            'knuckle_protruding_fraction sub-check is the one that could be promoted '
            'without argument: it is a pure SIGN test with no threshold at all, and it '
            "is the plan's preferred gate class."
        ),
        source='AFS p.185 and p.178, direction only. The threshold of 0 is a count of '
        'failed directions, not an anatomical cut point — a direction test has '
        'no number in it that a MEASURED source could contradict.',
        age_years=m['age_years'],
        assertions=rows,
        failed=fails,
        unresolved=unres,
        adult_bar_age_years=m['adult_age_years'],
        stature_child_m=m['stature_child_m'],
        stature_adult_m=m['stature_adult_m'],
        child_detail=m['subject']['detail'],
        note=(
            'finger thickness inherits whatever the phalanx-ratio verdict says about '
            'this rig: the denominator is the proximal segment length. It is '
            'therefore a WITHIN-CAGE direction only and must never be read as an '
            'absolute finger slenderness.'
        ),
    )
