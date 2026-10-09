# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The five mesh-space form predicates, the Monte-Carlo thresholds they are judged
against, and check_hand_mesh.

Moved verbatim out of the old single-file hands.py (lines 825-1234).
"""

import json
import os
import numpy as np

from zyg_workflows.geom.form.hands.rig import (
    SCHEMA,
    PREDICATES,
    FAIL,
    REPORT,
    UNMEASURABLE,
    HOUSE,
    DIGITS,
    FINGERS,
    WEBS,
    SAMPLE_FILE,
    CAGE_VERTS,
    DIGIT_BONES,
    WEB_FACE_W_MIN,
    RIDGE_SLAB_FRAC,
    RIDGE_BINS,
    DP_AXIS_MIN_ANISOTROPY,
    rig,
    _segment_idx,
    _unit,
    _line_residuals,
    _line_angle,
    _principal_axes,
    _triangulate,
    _plane_cut,
    resolve_hand,
)
from zyg_workflows.geom.form.hands.provenance import (
    _rec,
    _judge,
)
from zyg_workflows.geom.form.hands.unresolved import (
    MESH_UNRESOLVED,
    DIGIT_UNRESOLVED,
)
from zyg_workflows.geom.form.hands.digits_rig import (
    _env_flag,
    DIGIT_GATES_FLAG,
)
from zyg_workflows.geom.form.hands.digit_chains import (
    check_digit_chains,
    check_phalanx_ratio,
)
from zyg_workflows.geom.form.hands.child_hand import (
    check_child_hand,
)


# -- mesh predicates ---------------------------------------------------------------
def _mesh_knuckle_arch(F):
    J, hl = F['joints'], F['hand_length_m']
    P4 = np.array([J[(d, 'mcp')] for d in FINGERS])
    P5 = np.vstack([P4, J[('thumb', 'mcp')]])
    r4 = _line_residuals(P4)
    r5 = _line_residuals(P5)
    rms4 = float(np.sqrt((r4**2).mean()))
    return {
        'value': rms4 / hl,
        'rms4_m': rms4,
        'max4_m': float(r4.max()),
        'rms5_m': float(np.sqrt((r5**2).mean())),
        'per_finger_m': {d: float(x) for d, x in zip(FINGERS, r4)},
    }


def _mesh_middle_finger_ratio(F):
    J, hl = F['joints'], F['hand_length_m']
    mf = float(np.linalg.norm(J[('middle', 'tip')] - J[('middle', 'mcp')]))
    return {'value': mf / hl, 'middle_finger_m': mf, 'hand_length_m': hl}


def _web_axes(F, a, b):
    J = F['joints']
    m0 = 0.5 * (J[(a, 'mcp')] + J[(b, 'mcp')])
    ax = _unit(0.5 * (J[(a, 'tip')] + J[(b, 'tip')]) - m0)
    lat = J[(b, 'mcp')] - J[(a, 'mcp')]
    lat = lat - float(np.dot(lat, ax)) * ax
    gap = float(np.linalg.norm(lat))
    pp = 0.5 * (
        float(np.linalg.norm(J[(a, 'pip')] - J[(a, 'mcp')])) + float(np.linalg.norm(J[(b, 'pip')] - J[(b, 'mcp')]))
    )
    return m0, ax, lat / gap, gap, pp


def _mesh_webbing(v, tris, F):
    """Commissure position as a fraction of proximal-phalanx length, distal of the MCP line.

    The mid-plane between two digits is cut against the delivered triangulation, restricted
    to the two digits' own faces. Proximal of the commissure the plane passes through the
    web and returns crossings; distal of it the plane passes through the gap between the
    fingers and returns none. The most distal crossing IS the commissure, with no
    tolerance parameter anywhere in the construction.
    """
    S = F['side']
    out = {}
    for a, b in WEBS:
        m0, ax, lat, gap, pp = _web_axes(F, a, b)
        bones = [x for d in (a, b) for x in DIGIT_BONES[d] if x]
        w = rig()['weights']
        tot = np.zeros(CAGE_VERTS)
        for bn in bones:
            tot += w['%s.%s' % (bn, S)]
        keep = tot > WEB_FACE_W_MIN
        ft = tris[keep[tris].all(1)]
        P = _plane_cut(v, ft, m0, lat)
        if len(P) < 6:
            out[(a, b)] = {
                'value': None,
                'n_crossings': int(len(P)),
                'why': 'the inter-digital mid-plane cut returned %d crossings; '
                'there is no web surface to measure' % len(P),
            }
            continue
        t = (P - m0) @ ax
        out[(a, b)] = {
            'value': float(t.max() / pp),
            'commissure_m': float(t.max()),
            'proximal_phalanx_m': pp,
            'n_crossings': int(len(P)),
            'inter_mcp_gap_m': gap,
        }
    vals = [r['value'] for r in out.values() if r['value'] is not None]
    return {'value': (min(vals) if vals else None), 'webs': out, 'n_measured': len(vals)}


def _dp_axis(v, S, d):
    """Unsigned dorso-palmar axis of a digit, from the distal block's cross-section.

    A finger's cross-section is wider medio-laterally than dorso-palmarly, so the SMALLEST
    principal axis of the block distal to the PIP joint is the dorso-palmar one. The block
    is (middle + distal) phalanx for a finger and (distal) phalanx for the thumb, which has
    one phalanx fewer — a deliberate asymmetry, stated rather than hidden, and the one that
    measures best: with it the four fingers agree to within 18.5-19.1 degrees on all four
    issued characters, against 24.5-27.1 for distal-only and 35.8-42.7 for the whole digit.
    """
    bones = DIGIT_BONES[d]
    use = [x for x in bones[2:] if x]
    seg = _segment_idx(S, use)
    axes, sv = _principal_axes(v[seg])
    aniso = float(sv[1] / sv[2]) if sv[2] > 0 else float('inf')
    return axes[2], axes[0], aniso, len(seg)


def _mesh_thumb_opposition(v, F):
    S = F['side']
    dp, ax, an = {}, {}, {}
    for d in DIGITS:
        dp[d], ax[d], an[d], _ = _dp_axis(v, S, d)
    weak = {d: round(a, 3) for d, a in an.items() if a < DP_AXIS_MIN_ANISOTROPY}
    M = sum(np.outer(dp[d], dp[d]) for d in FINGERS)
    _, V = np.linalg.eigh(M)
    consensus = V[:, -1]
    worst = max(_line_angle(dp[FINGERS[i]], dp[FINGERS[j]]) for i in range(4) for j in range(i + 1, 4))
    return {
        'value': _line_angle(dp['thumb'], consensus),
        'finger_agreement_deg': worst,
        'long_axis_divergence_deg': _line_angle(ax['thumb'], ax['middle']),
        'anisotropy': {d: round(a, 4) for d, a in an.items()},
        'ill_conditioned': weak,
    }


def _mesh_dorsal_over_palmar(v, F, web):
    """Caliper finger length from the knuckle over caliper finger length from the web.

    THE CONVENTION IS THE CALIPER ONE, and it is chosen over integrating the two surface
    profiles because that integration does not survive this cage's sampling density. There
    are 154 vertices in the index finger's mid-sagittal slab; binned 14 ways, several bins
    hold one vertex, and if that vertex happens to sit on the dorsal side the palmar
    profile's per-bin minimum jumps to a DORSAL value. Measured on the male original, one
    such bin added 37 mm of spurious length to an 80 mm path and inverted the ratio to
    0.78. A chord between two real cage vertices has no such failure mode.

    Both lengths run to the same fingertip. The dorsal one starts at the knuckle — the
    most dorsal cage vertex in the finger's proximal mid-sagittal slab. The palmar one
    starts on the palmar surface at the WEB level. If the web sits at the MCP line, which
    is the V-notch hand, the palmar start slides proximal, the palmar chord becomes the
    longer of the two and the ratio drops below 1. So this predicate is NOT independent of
    `webbing`; it is the same web position read as a length, and it is reported as such.

    CAVEAT ON SIZE. The commissure is the WEB APEX, not the palmar digital crease, and the
    crease lies distal of the apex on a real hand. Expect a smaller ratio here than the
    ~1.15 a caliper on a photograph gives.
    """
    S, J, n = F['side'], F['joints'], F['palmar_normal']
    out = {}
    for d in FINGERS:
        seg = _segment_idx(S, [x for x in DIGIT_BONES[d][1:] if x])
        mcp, tip = J[(d, 'mcp')], J[(d, 'tip')]
        a = _unit(tip - mcp)
        L = float(np.linalg.norm(tip - mcp))
        dor = _unit(-n - float(np.dot(-n, a)) * a)
        lat = np.cross(a, dor)
        P = v[seg] - mcp
        t, u, w = P @ a, P @ dor, P @ lat
        slab = (np.abs(w - np.median(w)) < RIDGE_SLAB_FRAC * (w.max() - w.min())) & (t >= 0)
        # web level for this finger: the mean of its adjacent commissures, projected onto
        # this finger's own axis
        tw = []
        for pair in WEBS:
            if d not in pair:
                continue
            r = web['webs'].get(pair) or {}
            if r.get('value') is None:
                continue
            m0, wax, _, _, _ = _web_axes(F, pair[0], pair[1])
            tw.append(float(np.dot(m0 + r['commissure_m'] * wax - mcp, a)))
        if not tw:
            out[d] = {'value': None, 'why': 'no adjacent commissure was measurable'}
            continue
        t_web = float(np.mean(tw))
        knuckle = slab & (t <= L / float(RIDGE_BINS)) & (u > 0)
        palmar = slab & (u < 0)
        if knuckle.sum() < 1 or palmar.sum() < 1:
            out[d] = {
                'value': None,
                'why': 'mid-sagittal slab holds %d dorsal-proximal and %d palmar '
                'vertices' % (int(knuckle.sum()), int(palmar.sum())),
            }
            continue
        i_dor = np.nonzero(knuckle)[0][int(np.argmax(u[knuckle]))]
        j = np.nonzero(palmar)[0]
        i_pal = j[int(np.argmin(np.abs(t[j] - t_web)))]
        d_len = float(np.linalg.norm(tip - v[seg[i_dor]]))
        p_len = float(np.linalg.norm(tip - v[seg[i_pal]]))
        out[d] = {
            'value': d_len / p_len,
            'dorsal_m': d_len,
            'palmar_m': p_len,
            'web_level_m': t_web,
            'finger_axis_m': L,
            'palmar_start_t_m': float(t[i_pal]),
        }
    vals = [r['value'] for r in out.values() if r['value'] is not None]
    return {'value': (min(vals) if vals else None), 'fingers': out, 'n_measured': len(vals)}


def measure_hand_mesh(v, faces, side):
    """Raw numbers for one hand, with no thresholds applied. The calibration runs on this."""
    v = np.asarray(v, np.float64)
    tris = _triangulate(faces)
    F = resolve_hand(v, faces, side)
    web = _mesh_webbing(v, tris, F)
    return {
        'frame': F,
        'knuckle_arch': _mesh_knuckle_arch(F),
        'middle_finger_ratio': _mesh_middle_finger_ratio(F),
        'webbing': web,
        'thumb_opposition': _mesh_thumb_opposition(v, F),
        'dorsal_over_palmar': _mesh_dorsal_over_palmar(v, F, web),
    }


# ---------------------------------------------------------------------------------
# Thresholds
#
# Loaded from the Monte-Carlo sample if one has been built, and ABSENT otherwise: a
# predicate with no calibration is reported, never gated, which is the same rule
# geom.anthro.gates applies to a gate that declares no calibration.
# ---------------------------------------------------------------------------------
# HOUSE. A floor is placed outside the whole observed range by this fraction of the range,
# so the reference sample rejects 0/N by construction and what gets reported is the
# rule-of-three 95% upper bound. Chosen rather than a percentile because a percentile
# threshold rejects its own percentile by construction and would calibrate itself.
FLOOR_MARGIN = 0.5

_CAL = {}


def calibration(path=SAMPLE_FILE, reload=False):
    """The measured thresholds, or None if the sample has not been built on this machine."""
    if not reload and path in _CAL:
        return _CAL[path]
    doc = None
    if os.path.exists(path):
        with open(path) as f:
            doc = json.load(f)
        if doc.get('schema') != SCHEMA:
            raise ValueError('%s was written by %r, this module speaks %r' % (path, doc.get('schema'), SCHEMA))
    _CAL[path] = doc
    return doc


def _band_for(pred, cal):
    if not cal:
        return None, None, None
    b = (cal.get('predicates') or {}).get(pred)
    if not b or b.get('band') is None:
        return None, None, None
    lo, hi = b['band']
    return (lo, hi), b, b.get('severity')


def check_hand_mesh(v, faces, side, params=None):
    """FORM verdict for one hand of one anny cage.

    Returns {'schema', 'basis': 'mesh', 'side', 'frame', 'predicates': {name: record},
             'unresolved': [...]} with the same predicate vocabulary check_hand_image uses.

    `params` is optional and, when given, must be the registry params dict the cage was
    built from. It unlocks the three DIGIT_PREDICATES, which read the SKELETON and so
    cannot be computed from vertices alone. Passing params that do not match `v` would
    measure two different bodies, so this path rebuilds nothing from them beyond the
    skeleton and reports the cage-vs-recipe agreement; callers with only a cage should
    keep using the three-argument form and get the five form predicates as before.
    """
    m = measure_hand_mesh(v, faces, side)
    cal = calibration()
    F = m['frame']
    preds = {}

    band, cb, sev = _band_for('knuckle_arch', cal)
    a = m['knuckle_arch']
    preds['knuckle_arch'] = _rec(
        'knuckle_arch',
        'mesh',
        _judge(a['value'], band),
        a['value'],
        'line residual over the four finger MCPs / hand length',
        'the four metacarpal heads form an arch, so a line through them leaves a residual; '
        'a flat residual is the fused-knuckle hand. Five-point residual %.5f m is reported '
        'and gates nothing — it is 7.5x the four-point one and the thumb alone keeps it '
        'large.' % a['rms5_m'],
        band=band,
        threshold=(band[0] if band else None),
        provenance=(HOUSE if band else None),
        source=(cb.get('source') if cb else None),
        **a,
    )

    band, cb, sev = _band_for('middle_finger_ratio', cal)
    r = m['middle_finger_ratio']
    preds['middle_finger_ratio'] = _rec(
        'middle_finger_ratio',
        'mesh',
        _judge(r['value'], band),
        r['value'],
        'middle finger (MCP->tip) / hand length (wrist ring->dactylion)',
        'the middle finger is about half the hand. The band is measured from the morph sample, not asserted at 0.5.',
        band=band,
        threshold=None,
        provenance=(HOUSE if band else None),
        source=(cb.get('source') if cb else None),
        **r,
    )

    band, cb, sev = _band_for('webbing', cal)
    w = m['webbing']
    preds['webbing'] = _rec(
        'webbing',
        'mesh',
        (_judge(w['value'], band) if w['value'] is not None else UNMEASURABLE),
        w['value'],
        'commissure distance distal of the MCP line / proximal phalanx length',
        'the interdigital commissure sits DISTAL of the MCP line. A commissure AT that '
        'line is the V-notch hand diffusion models emit.',
        band=band,
        threshold=(band[0] if band else None),
        provenance=(HOUSE if band else None),
        source=(cb.get('source') if cb else None),
        webs={'%s-%s' % k: val for k, val in w['webs'].items()},
        n_measured=w['n_measured'],
    )

    band, cb, sev = _band_for('thumb_opposition', cal)
    t = m['thumb_opposition']
    ill = bool(t['ill_conditioned'])
    st = UNMEASURABLE if ill else _judge(t['value'], band)
    # The relational floor, which is the one that means something: an opposition angle no
    # larger than the four fingers' own disagreement is estimator noise, not a thumb.
    rel = (cb or {}).get('floor_relational') if cb else None
    rel_violated = (not ill) and t['value'] <= t['finger_agreement_deg']
    if rel and rel.get('severity') == 'block' and rel_violated:
        st = FAIL
    preds['thumb_opposition'] = _rec(
        'thumb_opposition',
        'mesh',
        st,
        t['value'],
        "degrees between the thumb dorso-palmar axis and the four fingers' consensus",
        'the thumbnail faces a different direction from the other four. The four fingers '
        "agree to %.1f deg on this hand, which is this estimator's own noise floor; the "
        'number conflates axial rotation with long-axis divergence (%.1f deg here) and '
        'both are reported.' % (t['finger_agreement_deg'], t['long_axis_divergence_deg']),
        band=band,
        threshold=(band[0] if band else None),
        provenance=(HOUSE if band else None),
        source=(cb.get('source') if cb else None),
        relational_floor=rel,
        relational_floor_violated=bool(rel_violated),
        **t,
    )

    band, cb, sev = _band_for('dorsal_over_palmar', cal)
    dpv = m['dorsal_over_palmar']
    preds['dorsal_over_palmar'] = _rec(
        'dorsal_over_palmar',
        'mesh',
        (_judge(dpv['value'], band) if dpv['value'] is not None else UNMEASURABLE),
        dpv['value'],
        'dorsal ridge length (from the knuckle) / palmar ridge length (from the web)',
        'a finger is longer seen from the back than from the palm. NOT INDEPENDENT of '
        'webbing: it is the same web offset expressed as a length.',
        band=band,
        threshold=(band[0] if band else None),
        provenance=(HOUSE if band else None),
        source=(cb.get('source') if cb else None),
        fingers=dpv['fingers'],
        n_measured=dpv['n_measured'],
    )

    # Scoped to PREDICATES on purpose. These five are the Monte-Carlo-calibrated form
    # predicates, and without the sample file they have no threshold at all. The digit
    # pack merged in below carries EXTERNAL bands (radiographic surveys) that do not
    # depend on this machine having built a morph sample, so it must not be downgraded
    # by an absent sample file.
    for k in PREDICATES:
        p = preds[k]
        if p['band'] is None and p['status'] not in (UNMEASURABLE,):
            p['status'] = REPORT
            p['explain'] += (
                ' NO CALIBRATION on this machine (%s absent), so this is reported and gates nothing.' % SAMPLE_FILE
            )

    unresolved = list(MESH_UNRESOLVED)
    if params is not None and _env_flag(DIGIT_GATES_FLAG, True):
        phen = params['phenotype']
        loc = params.get('local_changes') or None
        bs = params.get('bone_scales') or None
        # params= is threaded, and that is the whole point of this branch. Without it
        # skeleton() reaches HC.effective_scales with params=None, which is the FRESH
        # BUILD signal: it re-SOLVES a correction from the phenotype instead of reusing
        # the one this body was issued with. For a body issued under the current solver
        # the two answers agree to ~1e-14 and the omission is invisible; for a body
        # issued under an older version, or before the correction existed, it silently
        # measures a hand that never shipped — the exact split-brain t5_phalanx_ratio
        # exists to catch. check_digits() (the gate's own entry point) has always
        # threaded it; this door is the one that did not. MEASURED 2026-09-02: with a
        # params dict carrying no `hand_correction`, abel's worst mid/prox z moves from
        # 1.13e-14 (re-solved, the hand that did not ship) to 3.5474817160166459
        # (recorded `before`, the hand that did) — the same three-state contract
        # effective_scales and _build_mesh already keep.
        preds['digit_chains'] = check_digit_chains(phen, loc, bs, F['side'], params=params)
        preds['phalanx_ratio'] = check_phalanx_ratio(phen, loc, bs, F['side'], v, faces, params=params)
        preds['child_hand'] = check_child_hand(phen, loc, bs, F['side'], params.get('anatomy_layer'), params=params)
        unresolved += list(DIGIT_UNRESOLVED)
    return {
        'schema': SCHEMA,
        'basis': 'mesh',
        'side': F['side'],
        'frame': {k: (val.tolist() if isinstance(val, np.ndarray) else val) for k, val in F.items() if k != 'joints'},
        'joints_m': {'%s_%s' % k: val.tolist() for k, val in F['joints'].items()},
        'predicates': preds,
        'unresolved': unresolved,
        'calibrated': bool(cal),
    }
