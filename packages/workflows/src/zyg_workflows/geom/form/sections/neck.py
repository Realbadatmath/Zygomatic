# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""sections.neck — t5_neck_section and the neck taper — HeadNeck p.106-107, p.172, p.173.

Moved verbatim from geom/form/sections.py; no logic, numbers or comments changed.
"""

import math

import numpy as np

from .constants import (
    CANON,
    FAIL,
    GEOMETRY,
    HEXAGON_CIRCULARITY,
    LMK,
    MEA,
    MS,
    PASS,
    REPORT,
    SEGMENT_MAJORITY,
    SRC_NECK_HEX,
    SRC_NECK_TAPER,
    UNMEASURABLE,
)

from .primitives import (
    _frame,
    _res,
    _rollup,
    _section,
    _shape_family,
    _split_front_back,
    bone_ends,
    segment_weight,
)

# =================================================================================
# t5_neck_section — HeadNeck p.106-107, p.172, p.173
# =================================================================================
NECK_BONE_SUBSTRINGS = ('neck',)


def _cervical_axis(names, heads, tails):
    """(base, top, unit) of the cervical column, from the rig.

    neck01's head is the cervico-thoracic junction and the `head` bone's head is the skull
    base, so the segment between them IS the neck. Anchored to bones rather than to a
    height fraction because the neck leans: measured on the five bodies the chain sits
    14.6-21.0 degrees forward of vertical, and a horizontal plane through a neck at that
    lean is not a neck section.
    """
    for a, b in (('neck01', 'head'),):
        if a in names and b in names:
            p0, p1 = heads[names.index(a)], heads[names.index(b)]
            d = p1 - p0
            L = float(np.linalg.norm(d))
            if L > 0:
                return p0, p1, d / L, L
    return None, None, None, None


def t5_neck_section(v, faces, phenotype=None, local_changes=None, sex=None, stature_m=None, zmin=None):
    """Five claims about the neck cross-section. HeadNeck p.106-107, p.172, p.173.

    hexagonality   the section should be described BETTER by a hexagon than by a circle.
                   Model selection over one family with one free parameter each — see
                   _ngon_residual. Ordering test.
    circularity    4*pi*A/P^2 must not exceed a regular hexagon's own 0.9069. A theorem
                   about hexagons used as a ceiling, so there is nothing to tune.
    front flatter  the same three readings as the torso, same verdict rule.
    spine posterior the cervical chain must lie posterior to the section centroid. Sign
                   test. The chain is a RIG construction, not a surface landmark, and is
                   labelled 'constructed' — but it is the only spine this cage has, and
                   landmarks.py already reports cervicale UNRESOLVED for exactly that
                   reason.
    taper          HeadNeck p.172 vs p.173: the male neck is roughly cylindrical, the female
                   neck is CONICAL — narrower at the top, widening to the base. This is a
                   derivative of a girth and neck_circumference structurally cannot see it.

    THE TAPER IS NOT MEASURED FROM SECTIONS, and the reason matters. Stations along the
    cervical axis stop being neck at different heights on different bodies — the mandible
    eats the top and the trapezius eats the base by different amounts once the morphs move —
    so an endpoint ratio taken over each body's own clean span compares different spans and
    the sex signal would be confounded by where the span happened to end. Instead the taper
    is regressed over the VERTEX SET the rig calls neck: every vertex whose majority
    skinning weight is on neck01/02/03 contributes one (along-axis, radius) pair. That
    vertex set is topology-fixed, so it is THE SAME SAMPLE on every body, and the regression
    has no span to choose.
    """
    if stature_m is None or zmin is None:
        zmin, stature_m = _frame(v)
    claims = {}
    detail = {}

    names, heads, tails = bone_ends(phenotype or LMK.REF_MALE, local_changes)
    p0, p1, ax, L = _cervical_axis(names, heads, tails)
    if ax is None:
        why = (
            'the rig carries no neck01/head bone pair, so there is no cervical axis and '
            'no defensible plane for a neck section'
        )
        for k in ('hexagonality', 'circularity', 'front_flatter_than_back', 'spine_posterior_to_centroid', 'taper'):
            claims[k] = _res(UNMEASURABLE, k, SRC_NECK_HEX, CANON, why)
        return {'gate': 't5_neck_section', 'claims': claims, 'status': _rollup(claims)}

    detail['cervical_axis'] = {
        'base_m': [float(x) for x in p0],
        'top_m': [float(x) for x in p1],
        'length_mm': L * 1000,
        'forward_lean_deg': float(math.degrees(math.acos(min(1.0, abs(float(ax[2])))))),
        'anchor': 'rig bones neck01(head) -> head(head), via anny get_bone_ends',
    }

    # --- the canonical station: the vendor's own neck-girth ring -----------------
    ring = MEA._ring_anchor(v, 'measure-neck-circ-incr')
    if ring is None:
        why = (
            "MakeHuman's measure-neck-circ-incr target has no support on this model, so "
            'the vendor neck-girth level cannot be placed. Substituting a height '
            "fraction would be our site wearing the vendor's name."
        )
        for k in ('hexagonality', 'circularity', 'front_flatter_than_back', 'spine_posterior_to_centroid'):
            claims[k] = _res(UNMEASURABLE, k, SRC_NECK_HEX, CANON, why)
        sec = None
    else:
        detail['station'] = {
            'origin_m': [float(x) for x in ring],
            'anchor': "MakeHuman measure-neck-circ-incr ring centroid — the vendor's own "
            'neck girth site, and the level geom.anthro.measure already takes '
            'neck_circumference at',
            't_along_cervical_axis': float((ring - p0) @ ax / L),
        }
        sec, err = _section(v, faces, ring, ax, np.array([1.0, 0.0, 0.0]), select='nearest', anchor=ring)
        if sec is None:
            for k in ('hexagonality', 'circularity', 'front_flatter_than_back', 'spine_posterior_to_centroid'):
                claims[k] = _res(UNMEASURABLE, k, SRC_NECK_HEX, CANON, err['reason'])
            sec = None

    if sec is not None:
        xy = sec['xy']
        met = sec['metrics']
        nw, nerr = segment_weight(NECK_BONE_SUBSTRINGS)
        ring_idx = np.asarray(sec['loop']['ring_below'])
        neck_frac = None if nw is None else float((nw[ring_idx] >= SEGMENT_MAJORITY).mean())
        detail['station'].update(
            contour_points=int(len(xy)),
            loops_found=sec['loops_found'],
            hull_mm=None if met['hull_m'] is None else met['hull_m'] * 1000,
            contour_mm=met['contour_m'] * 1000,
            area_mm2=met['area_m2'] * 1e6,
            neck_owned_ring_fraction=neck_frac,
            neck_mask_error=nerr,
        )

        # -- hexagonality --------------------------------------------------------
        fam = _shape_family(xy)
        if fam is None:
            claims['hexagonality'] = _res(
                UNMEASURABLE,
                'the neck section is better described by a hexagon than by a circle',
                SRC_NECK_HEX,
                CANON,
                'the section is degenerate in the whitened frame',
            )
        else:
            claims['hexagonality'] = _res(
                PASS if fam['hexagon_beats_circle'] else FAIL,
                'the neck section is better described by a hexagon than by a circle',
                SRC_NECK_HEX,
                CANON,
                (
                    'hexagon residual %.4f vs circle %.4f (%s); the best-fitting regular '
                    'polygon order in the whole family is %d'
                    % (
                        fam['hexagon_residual'],
                        fam['residual_circle'],
                        'hexagon wins' if fam['hexagon_beats_circle'] else 'CIRCLE WINS',
                        fam['best_order'],
                    )
                ),
                **fam,
            )

        # -- circularity ceiling -------------------------------------------------
        circ = 4.0 * math.pi * met['area_m2'] / met['contour_m'] ** 2 if met['contour_m'] > 0 else None
        detail['station']['circularity'] = circ
        if circ is None:
            claims['circularity'] = _res(
                UNMEASURABLE, 'neck circularity ceiling', SRC_NECK_HEX, GEOMETRY, 'zero perimeter'
            )
        else:
            claims['circularity'] = _res(
                PASS if circ <= HEXAGON_CIRCULARITY else FAIL,
                'the neck section is at least as far from a circle as a regular hexagon is',
                SRC_NECK_HEX + ' + exact hexagon isoperimetric ratio',
                GEOMETRY,
                "4*pi*A/P^2 = %.4f against a regular hexagon's %.4f%s"
                % (
                    circ,
                    HEXAGON_CIRCULARITY,
                    ''
                    if circ <= HEXAGON_CIRCULARITY
                    else ' — the section is MORE circular than a hexagon, so it cannot be one',
                ),
                circularity=circ,
                ceiling=HEXAGON_CIRCULARITY,
                ceiling_is='a theorem about regular hexagons, not a tolerance',
            )

        # -- front flatter than back ---------------------------------------------
        fb = _split_front_back(xy)
        if fb is None or fb['front']['median_norm_curvature'] is None:
            claims['front_flatter_than_back'] = _res(
                UNMEASURABLE,
                'the anterior arc of the neck section is flatter than the posterior arc',
                SRC_NECK_TAPER,
                CANON,
                'the section has no distinct widest pair',
            )
        else:
            f, b = fb['front'], fb['back']
            ok = f['median_norm_curvature'] < b['median_norm_curvature']
            claims['front_flatter_than_back'] = _res(
                PASS if ok else FAIL,
                'the anterior arc of the neck section is flatter than the posterior arc',
                SRC_NECK_TAPER,
                CANON,
                'median normalised curvature front %.3f vs back %.3f'
                % (f['median_norm_curvature'], b['median_norm_curvature']),
                front_median_curvature=f['median_norm_curvature'],
                back_median_curvature=b['median_norm_curvature'],
                front_camber=f['camber'],
                back_camber=b['camber'],
                front_fullness=f['fullness'],
                back_fullness=b['fullness'],
                camber_front_lt_back=bool(f['camber'] < b['camber']),
                fullness_front_gt_back=bool(f['fullness'] > b['fullness']),
            )

        # -- spine posterior to the centroid -------------------------------------
        # The spine locus is where the CERVICAL AXIS pierces this plane, not the plane's
        # origin. The plane origin is the vendor RING centroid, which is a centroid of
        # SURFACE points and therefore already close to the section centroid by
        # construction — using it here would have compared the section centroid with
        # itself and reported a couple of millimetres of nothing.
        cen = np.asarray(sec['loop']['pts'], np.float64).mean(axis=0)
        spine = p0 + float((ring - p0) @ ax) * ax
        post = np.array([0.0, 1.0, 0.0])
        post = post - ax * float(post @ ax)
        pn = float(np.linalg.norm(post))
        if pn < 1e-9:
            claims['spine_posterior_to_centroid'] = _res(
                UNMEASURABLE,
                'the cervical column lies posterior to the section centroid',
                SRC_NECK_HEX,
                CANON,
                'the cervical axis is parallel to the antero-posterior direction, so '
                '"posterior" has no in-plane meaning here',
            )
        else:
            post = post / pn
            d = float((spine - cen) @ post)
            claims['spine_posterior_to_centroid'] = _res(
                PASS if d > 0 else FAIL,
                'the cervical column lies posterior to the neck section centroid',
                SRC_NECK_HEX,
                CANON,
                'the cervical axis sits %+.1f mm posterior of the section centroid (positive = posterior)' % (d * 1000),
                offset_mm=d * 1000,
                spine_point_m=[float(x) for x in spine],
                centroid_m=[float(x) for x in cen],
                spine_locus='rig cervical chain — a CONSTRUCTED locus, not a surface '
                'landmark. landmarks.py reports cervicale UNRESOLVED on this '
                'cage, so there is no measured vertebral surface to use '
                'instead.',
                claim_kind='constructed',
            )

    # --- taper, from the rig's own neck vertex set -------------------------------
    taper = neck_taper(v, phenotype, local_changes, stature_m)
    detail['taper'] = taper
    if taper.get('error') or taper.get('taper_ratio') is None:
        claims['taper'] = _res(
            UNMEASURABLE,
            'the female neck tapers (narrower at the top); the male neck does not',
            SRC_NECK_TAPER,
            CANON,
            taper.get('error')
            or 'the fitted radius at the base of the neck is not positive, so a top/base ratio has no meaning',
        )
    elif (sex or '').lower() == 'female':
        claims['taper'] = _res(
            PASS if taper['taper_ratio'] < 1.0 else FAIL,
            'a female neck is conical: narrower at the top, widening toward the base',
            SRC_NECK_TAPER,
            CANON,
            'fitted neck radius ratio top/base = %.4f (%s)'
            % (taper['taper_ratio'], 'tapers upward' if taper['taper_ratio'] < 1.0 else 'does NOT taper upward'),
            **taper,
        )
    else:
        claims['taper'] = _res(
            REPORT,
            'a male neck is roughly cylindrical (ratio near 1.0) — REPORTED, NOT GATED',
            SRC_NECK_TAPER,
            CANON,
            'fitted neck radius ratio top/base = %.4f. "Roughly cylindrical" has no '
            'printed tolerance, and inventing one would be a tuned threshold. The male '
            'value is reported; the sex signal is gated by the paired direction test in '
            'neck_taper_dimorphism(), which has no threshold at all.' % taper['taper_ratio'],
            **taper,
        )

    return {
        'gate': 't5_neck_section',
        'source': SRC_NECK_HEX,
        'provenance': CANON,
        'detail': detail,
        'claims': claims,
        'status': _rollup(claims),
    }


def neck_taper(v, phenotype=None, local_changes=None, stature_m=None):
    """Regress neck radius on height over the vertex set the RIG calls neck.

    Returns the fitted top/base ratio, the dimensionless slope, and the sample. The vertex
    set is topology-fixed (the rig's weights are a property of the model, not of a
    character), so every body is measured on the same 171 vertices and the cross-body
    comparison has no span to confound it.
    """
    out = {}
    nw, nerr = segment_weight(NECK_BONE_SUBSTRINGS)
    if nw is None:
        return {'error': nerr}
    names, heads, tails = bone_ends(phenotype or LMK.REF_MALE, local_changes)
    p0, p1, ax, L = _cervical_axis(names, heads, tails)
    if ax is None:
        return {'error': 'no cervical axis on this rig'}
    v = np.asarray(v, np.float64)
    if len(nw) != len(v):
        return {'error': 'the rig weight vector is %d long against a %d-vertex mesh' % (len(nw), len(v))}
    idx = np.nonzero(nw >= SEGMENT_MAJORITY)[0]
    if len(idx) < 8:
        return {'error': 'only %d vertices carry a majority neck weight' % len(idx)}
    q = v[idx] - p0
    s = q @ ax
    r = np.linalg.norm(q - np.outer(s, ax), axis=1)
    A = np.stack([np.ones_like(s), s], axis=1)
    coef, *_ = np.linalg.lstsq(A, r, rcond=None)
    a, b = float(coef[0]), float(coef[1])
    s_lo, s_hi = float(s.min()), float(s.max())
    r_lo, r_hi = a + b * s_lo, a + b * s_hi
    out.update(
        vertices=int(len(idx)),
        span_mm=(s_hi - s_lo) * 1000,
        radius_base_mm=r_lo * 1000,
        radius_top_mm=r_hi * 1000,
        taper_ratio=float(r_hi / r_lo) if r_lo > 0 else None,
        slope_per_stature=float(b * stature_m) if stature_m else float(b),
        residual_rms_mm=float(np.sqrt(((r - (a + b * s)) ** 2).mean()) * 1000),
        sample='vertices whose majority skinning weight is on %s — topology-fixed, '
        'so identical across bodies' % (NECK_BONE_SUBSTRINGS,),
    )
    return out


def neck_taper_dimorphism(phenotype=None, local_changes=None):
    """The sex signal as a PAIRED DIRECTION TEST — the form with no threshold at all.

    Hold one recipe, flip only the gender macro, and require the female neck to taper more
    than the male's. HeadNeck p.172/p.173 states a direction, not a number, so this is the
    only shape the claim can honestly take. It is also the shape the plan's §4(a) asks for:
    a regression gate that fails on a ZERO delta.
    """
    base = dict(phenotype or LMK.REF_MALE)
    out = {}
    for tag, g in (('male', 0.0), ('female', 1.0)):
        ph = dict(base, gender=g)
        vv, ff, _ = MS._build_mesh(ph, local_changes)
        vv = np.asarray(vv, np.float64)
        zmin, H = _frame(vv)
        out[tag] = neck_taper(vv, ph, local_changes, H)
        out[tag]['stature_m'] = H
    if (
        out['male'].get('error')
        or out['female'].get('error')
        or out['male'].get('taper_ratio') is None
        or out['female'].get('taper_ratio') is None
    ):
        return {
            'status': UNMEASURABLE,
            'detail': out,
            'explain': (
                out['male'].get('error') or out['female'].get('error') or 'a fitted base radius is not positive'
            ),
        }
    tm, tf = out['male']['taper_ratio'], out['female']['taper_ratio']
    delta = tf - tm
    return {
        'status': PASS if delta < 0 else FAIL,
        'claim': 'flipping the gender macro alone must make the neck MORE conical',
        'source': SRC_NECK_TAPER,
        'provenance': CANON,
        'explain': 'taper ratio male %.4f, female %.4f, delta %+.4f (%s)'
        % (
            tm,
            tf,
            delta,
            'female more conical, as the book states'
            if delta < 0
            else 'the female neck is NOT more conical than the male on this cage',
        ),
        'evidence': {
            'male_ratio': tm,
            'female_ratio': tf,
            'delta': delta,
            'zero_delta_is_a_failure': True,
            'detail': out,
        },
    }
