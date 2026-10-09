# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The per-site builders: girth sites, the pose-bias attachment and the extent measures.

Moved verbatim out of the old single-file measure.py (lines 2603-3122).
"""

import numpy as np

from zyg_workflows.geom.anthro.measure.constants import ARM_SKIN_WEIGHT_THRESHOLD
from zyg_workflows.geom.anthro.measure.anchors import _band
from zyg_workflows.geom.anthro.measure.primitives import (
    _extent_scan,
    _girth_at,
    _scan_girth,
)
from zyg_workflows.geom.anthro.measure.record import (
    HULL_CONVENTION,
    _anchor_point,
    _rec,
)


def _girth_site(v, faces, spec, side, lm, axes, zmin, H, step, coco, ear_top=None, crotch_frac=None, pose_ref=None):
    """One row of GIRTH_SITES, on one side.

    pose_ref, when given, is the arms-down copy from adducted_copy(). The whole site is
    re-measured on it — re-scanned, if the site scans, because the winning plane moves —
    and the difference is attached as a_pose_bias_mm. It is only spent where the A-posed
    section actually carries arm skinning weight; everywhere else the bias is exactly
    zero by construction (the displacement is weight-scaled) and is recorded as such
    without a second pass.
    """
    iso = spec['iso_class']
    common = dict(
        kind='girth',
        landmark=spec['landmark'],
        iso_class=iso,
        note=spec['note'],
        ansur_ratio=spec.get('ansur'),
        site=spec['name'],
        side=side,
        scope=spec['scope'],
    )
    band_note = None

    if spec['plane'] == 'horizontal':
        normal = np.array([0.0, 0.0, 1.0])
        anchor = None
        if spec['anchor'].get('fz_band') or spec['anchor'].get('landmark_band'):
            lo, hi = spec['anchor'].get('fz_band', (0.0, 1.0))
            lo, hi, band_note = _band(spec['anchor'], lo, hi, ear_top, crotch_frac, lm)
            if lo is None:
                return _rec(
                    None,
                    'girth',
                    spec['landmark'],
                    HULL_CONVENTION,
                    iso,
                    spec['note'],
                    provenance='UNMEASURABLE',
                    reason=band_note,
                    **{k: val for k, val in common.items() if k not in ('kind', 'landmark', 'iso_class', 'note')},
                )
            base = np.array([0.0, 0.0, zmin + lo * H])
            rec, _loop = _scan_girth(
                v,
                faces,
                base,
                normal,
                spec['scope'],
                anchor,
                spec['scan']['mode'],
                0.0,
                (hi - lo) * H,
                step,
                u_hint=np.array([1.0, 0.0, 0.0]),
            )
            if 'scan' in rec:
                rec['scan']['band_frac_stature'] = [lo, hi]
                rec['scan']['found_at_frac_stature'] = lo + rec['scan']['offset_m'] / H
            site_desc = '%s horizontal girth over %.4f-%.4f of stature' % (spec['scan']['mode'], lo, hi)
        else:
            p, why = _anchor_point(spec['anchor'], lm, v)
            if p is None:
                return _rec(
                    None,
                    'girth',
                    spec['landmark'],
                    HULL_CONVENTION,
                    iso,
                    spec['note'],
                    provenance='UNMEASURABLE',
                    reason=why,
                    **{k: val for k, val in common.items() if k not in ('kind', 'landmark', 'iso_class', 'note')},
                )
            rec, _loop = _girth_at(
                v, faces, np.array([0.0, 0.0, p[2]]), normal, spec['scope'], p, u_hint=np.array([1.0, 0.0, 0.0])
            )
            site_desc = 'horizontal plane at %s (%.4f of stature)' % (why, (p[2] - zmin) / H)
        conv = HULL_CONVENTION + ' — HORIZONTAL plane (torso convention)'
    else:
        ax = axes.get('%s_%s' % (spec['axis'], side)) if side else axes.get(spec['axis'])
        if ax is None:
            return _rec(
                None,
                'girth',
                spec['landmark'],
                HULL_CONVENTION,
                iso,
                spec['note'],
                provenance='UNMEASURABLE',
                reason='limb axis %r unavailable (anny COCO regressor did not run)' % spec['axis'],
                **{k: val for k, val in common.items() if k not in ('kind', 'landmark', 'iso_class', 'note')},
            )
        a, b = ax
        normal = b - a
        normal = normal / np.linalg.norm(normal)
        if spec['anchor'].get('coco'):
            key = spec['anchor']['coco'] % ('left' if side == 'l' else 'right')
            if not coco or key not in coco:
                return _rec(
                    None,
                    'girth',
                    spec['landmark'],
                    HULL_CONVENTION,
                    iso,
                    spec['note'],
                    provenance='UNMEASURABLE',
                    reason='COCO keypoint %r unavailable' % key,
                    **{k: val for k, val in common.items() if k not in ('kind', 'landmark', 'iso_class', 'note')},
                )
            p = np.asarray(coco[key], np.float64)
            why = 'anny COCO joint centre %s' % key
        else:
            p, why = _anchor_point(spec['anchor'], lm, v, side)
            if p is None:
                return _rec(
                    None,
                    'girth',
                    spec['landmark'],
                    HULL_CONVENTION,
                    iso,
                    spec['note'],
                    provenance='UNMEASURABLE',
                    reason=why,
                    **{k: val for k, val in common.items() if k not in ('kind', 'landmark', 'iso_class', 'note')},
                )
        if spec['scan']:
            hw = spec['scan']['half_fz'] * H
            rec, _loop = _scan_girth(
                v, faces, p, normal, spec['scope'], p, spec['scan']['mode'], -hw, hw, step, side=side
            )
        else:
            rec, _loop = _girth_at(v, faces, p, normal, spec['scope'], p, side=side)
        site_desc = 'plane through %s (%.4f of stature), normal along the %s axis' % (
            why,
            (p[2] - zmin) / H,
            spec['axis'],
        )
        conv = HULL_CONVENTION + ' — PERPENDICULAR TO THE LIMB AXIS (ISO 18825-2)'
        rec = dict(rec)
        # The horizontal variant is computed ONLY where a survey actually uses a
        # horizontal tape (thigh, calf). Computing it everywhere produced nonsense that
        # looked like data: the horizontal plane through the upper-arm ring cuts the whole
        # trunk, and the "upper arm girth" came out at 1722.90 mm on the male.
        if spec.get('ansur_uses') == 'horizontal':
            hn = np.array([0.0, 0.0, 1.0])
            if spec['scan']:
                hz, _l2 = _scan_girth(
                    v,
                    faces,
                    np.array([0.0, 0.0, p[2]]),
                    hn,
                    'limb',
                    p,
                    spec['scan']['mode'],
                    -spec['scan']['half_fz'] * H,
                    spec['scan']['half_fz'] * H,
                    step,
                    u_hint=np.array([1.0, 0.0, 0.0]),
                    side=side,
                )
            else:
                hz, _l2 = _girth_at(
                    v, faces, np.array([0.0, 0.0, p[2]]), hn, 'limb', p, u_hint=np.array([1.0, 0.0, 0.0]), side=side
                )
            rec['horizontal_mm'] = hz.get('value_mm')
            rec['horizontal_reason'] = hz.get('reason')
            # THE HORIZONTAL SCAN KEEPS ITS OWN EVIDENCE. horizontal_mm — not value_mm —
            # is what _ratios feeds to thigh_/calf_circumference_over_stature and what the
            # ANSUR band is therefore applied to, so dropping hz's scan block left the
            # gated number with no window record at all while the record's top-level
            # 'scan' and 'endpoint_warning' (the PERPENDICULAR scan's) sat next to it
            # describing a different number. Measured cost of that on 2026-08-05: the
            # female's thigh record advertised at_window_endpoint=False and no BAND-EDGE
            # flag while the 606.70 mm the band actually judged sat exactly on the +half_fz
            # edge of its own scan; cornelis's advertised 41/41 usable planes while 3 of
            # the horizontal scan's 41 were refused by the limb-side guard.
            rec['horizontal_scan'] = hz.get('scan')
            rec['horizontal_endpoint_warning'] = hz.get('endpoint_warning')
            rec['horizontal_minus_perpendicular_mm'] = (
                None if hz.get('value_mm') is None or rec.get('value_mm') is None else hz['value_mm'] - rec['value_mm']
            )
            rec['horizontal_note'] = (
                'the ANSUR tape value for this site, and the number the ANSUR band is '
                'applied to (see horizontal_scan / horizontal_endpoint_warning for ITS '
                'window — the top-level scan block belongs to the perpendicular value_mm '
                'above, which is a different plane). A horizontal plane through a limb '
                'that is not vertical cuts an ellipse, so it exceeds the perpendicular '
                "girth by roughly 1/cos(the limb's tilt from vertical)."
            )
            # Both warnings surface on the one line a reader actually sees. The renderer
            # flags BAND-EDGE off this key alone, so a warning that stays in a sub-block
            # is a warning that never reaches anyone.
            warns = []
            if rec.get('endpoint_warning'):
                warns.append('PERPENDICULAR (value_mm): %s' % rec['endpoint_warning'])
            if hz.get('endpoint_warning'):
                warns.append(
                    'HORIZONTAL TAPE (horizontal_mm, the number the ANSUR band '
                    'is applied to): %s' % hz['endpoint_warning']
                )
            if warns:
                rec['endpoint_warning'] = ' || '.join(warns)

    out = _rec(
        rec.get('value_mm'),
        'girth',
        spec['landmark'],
        conv,
        iso,
        spec['note'],
        provenance='MEASURED' if rec.get('value_mm') is not None else 'REFUSED',
        site_description=site_desc,
        ansur_ratio=spec.get('ansur'),
        ansur_uses=spec.get('ansur_uses', 'this'),
        side=side,
        scope=spec['scope'],
        survey_comparable=spec.get('survey_comparable', True),
        survey_not_comparable_because=spec.get('survey_reason'),
    )
    if band_note:
        out['band_adjustment'] = band_note
    for k in (
        'reason',
        'hull_mm',
        'contour_mm',
        'polyline_mm',
        'section_area_mm2',
        'polyline_planar_mm',
        'polyline_ring_out_of_plane_mm',
        'limb_side_check',
        'arm_loops_present',
        'x_extent_mm',
        'y_extent_mm',
        'loops_found',
        'selected_by',
        'contour_points',
        'ring_vertices',
        'arm_triangles_in_loop',
        'scan',
        'arm_mask',
        'arm_triangle_mask',
        'arm_triangles_in_loop_morph_support',
        'arm_masked_hull_mm',
        'hull_unmasked_mm',
        'arm_excluded_hull_mm',
        'arm_excluded_x_extent_mm',
        'arm_excluded_y_extent_mm',
        'x_extent_unmasked_mm',
        'y_extent_unmasked_mm',
        'endpoint_warning',
        'plane_origin_m',
        'plane_nudge_m',
        'horizontal_mm',
        'horizontal_reason',
        'horizontal_scan',
        'horizontal_endpoint_warning',
        'horizontal_minus_perpendicular_mm',
        'horizontal_note',
    ):
        if k in rec:
            out[k] = rec[k]
    if out.get('hull_mm') is not None and out.get('polyline_mm') is not None:
        out['hull_minus_polyline_mm'] = out['hull_mm'] - out['polyline_mm']
    if out.get('hull_mm') is not None and out.get('contour_mm') is not None:
        out['hull_minus_contour_mm'] = out['hull_mm'] - out['contour_mm']
    if out.get('value_mm') is not None:
        out['frac_stature'] = out['value_mm'] / (H * 1000)
    if pose_ref is not None and spec['plane'] == 'horizontal':
        _attach_pose_bias(
            out,
            lambda: _girth_site(
                pose_ref,
                faces,
                spec,
                side,
                lm,
                axes,
                float(np.asarray(pose_ref)[:, 2].min()),
                H,
                step,
                coco,
                ear_top,
                crotch_frac,
                pose_ref=None,
            ),
        )
    return out


def _attach_pose_bias(out, remeasure):
    """Attach a_pose_bias_mm to a finished record, spending a second pass only if needed.

    The displacement adducted_copy() applies is scaled by each vertex's own arm skinning
    weight, so a section that carries no arm weight cannot move: those sites get an exact
    zero without re-measuring. Everything else is genuinely re-measured, scan and all.
    """
    am = out.get('arm_mask') or {}
    wmax = am.get('max_arm_weight_on_section')
    if out.get('value_mm') is None:
        return
    if wmax is not None and wmax <= 0.0:
        out['a_pose_bias_mm'] = 0.0
        out['a_pose_bias_note'] = (
            'exactly zero: no point of this section carries any arm skinning weight, so '
            'no adduction of the humerus can move it. Not an estimate.'
        )
        return
    try:
        other = remeasure()
    except Exception as e:  # noqa: BLE001
        out['a_pose_bias_mm'] = None
        out['a_pose_bias_note'] = 'the arms-down re-measurement failed: %s' % e
        return
    ov = other.get('value_mm')
    if ov is None:
        out['a_pose_bias_mm'] = None
        out['a_pose_bias_note'] = 'the arms-down copy produced no value here (%s)' % other.get(
            'reason', 'no reason given'
        )
        return
    out['a_pose_bias_mm'] = ov - out['value_mm']
    out['a_pose_bias_note'] = (
        'signed shift of THIS measurement when the humeri are brought vertical by linear '
        'blend skinning (adducted_copy). Validated against a genuine re-pose of the rig, '
        'which moves 79-97%% as far on the trunk: read it as an UPPER BOUND ON THE '
        'MAGNITUDE of how far this number sits from the arms-hanging survey convention. '
        'It is reported, NOT applied — the value above is the A-posed body as issued. '
        'arms-down estimate = %.2f mm.' % ov
    )
    if other.get('found_at_frac_stature') is not None:
        out['a_pose_bias_found_at_frac_stature'] = other['found_at_frac_stature']


def _extent_measure(v, faces, spec, lm, zmin, H, step, axis, ear_top=None, crotch_frac=None, pose_ref=None):
    """A breadth (axis='x') or a depth (axis='y') off a selected cross-section loop.

    For scope 'torso' and 'head' the extent is taken over the ARM-FREE contour points
    (see _girth_at); for scope 'all' it is the full silhouette, because that is what the
    site means. pose_ref works exactly as it does in _girth_site.
    """
    kind = 'breadth' if axis == 'x' else 'depth'
    conv = (
        'lateral (subject left-right) extent of the selected cross-section contour'
        if axis == 'x'
        else 'anterior-posterior extent of the selected cross-section contour'
    )
    flags = dict(
        survey_comparable=spec.get('survey_comparable', True), survey_not_comparable_because=spec.get('survey_reason')
    )
    band_note = None
    if spec['anchor'].get('fz_band') or spec['anchor'].get('landmark_band'):
        lo, hi = spec['anchor'].get('fz_band', (0.0, 1.0))
        lo, hi, band_note = _band(spec['anchor'], lo, hi, ear_top, crotch_frac, lm)
        if lo is None:
            return _rec(
                None,
                kind,
                spec['landmark'],
                conv,
                spec['iso_class'],
                spec['note'],
                provenance='UNMEASURABLE',
                reason=band_note,
                ansur_ratio=spec.get('ansur'),
                **flags,
            )
        sc = _extent_scan(v, faces, zmin + lo * H, zmin + hi * H, step, spec['scope'], axis)
        if sc is None:
            return _rec(
                None,
                kind,
                spec['landmark'],
                conv,
                spec['iso_class'],
                spec['note'],
                provenance='REFUSED',
                reason='no usable contour anywhere in %.4f-%.4f of stature' % (lo, hi),
                ansur_ratio=spec.get('ansur'),
                **flags,
            )
        z, val, rec = sc['z'], sc['value_mm'], sc['rec']
        frac = (z - zmin) / H
        # THE ENDPOINT TEST IS AN INDEX TEST, NOT A DISTANCE TEST. The winner is on an
        # edge exactly when it is the first or the last USABLE plane of the scan. The
        # distance form this replaces (abs(frac - lo) < SCAN_STEP_FRAC/2) had two holes,
        # both measured: (1) it compared against the REQUESTED window, so any plane that
        # the band floor made degenerate pushed the winner a full step in and it cleared
        # the half-step test — hip_breadth reported at_window_endpoint=False on all five
        # bodies while being the first single-loop plane above the crotch every time;
        # (2) np.arange(zlo, zhi + 1e-12, step) generally stops SHORT of the ceiling by
        # up to a full step (the female's last hip plane was 0.5785 against hi=0.58, a
        # gap of 0.0015 > the 0.001 tolerance), so a maximum at the top of a band could
        # never be flagged at all. An index test has no tolerance to defeat.
        first = sc['winner_index_among_usable'] == 0
        last = sc['winner_index_among_usable'] == sc['n_planes_usable'] - 1
        endpoint = bool(first or last)
        extra = {
            'found_at_frac_stature': frac,
            'scan_window_frac_stature': [lo, hi],
            'planes_scanned': sc['n_planes'],
            'planes_usable': sc['n_planes_usable'],
            'winning_plane_rank_among_usable': sc['winner_index_among_usable'] + 1,
            'at_window_endpoint': endpoint,
            'scan_profile_mm': [
                (round((zz - zmin) / H, 5), None if xx is None else round(xx, 2), nl) for zz, xx, nl in sc['profile']
            ],
        }
        if endpoint:
            extra['endpoint_warning'] = (
                'NO INTERIOR MAXIMUM: the winner is the %s of the %d usable planes in the '
                'search band %.4f-%.4f of stature (%d planes scanned), so this number is '
                'the extent AT the band %s (%.5f of stature) and is a property of the '
                'window, not of the body. Read the band floor/ceiling rationale in this '
                "record's note and band_adjustment before using it."
                % (
                    'FIRST' if first else 'LAST',
                    sc['n_planes_usable'],
                    lo,
                    hi,
                    sc['n_planes'],
                    'floor' if first else 'ceiling',
                    frac,
                )
            )
    else:
        p, why = _anchor_point(spec['anchor'], lm, v)
        if p is None:
            return _rec(
                None,
                kind,
                spec['landmark'],
                conv,
                spec['iso_class'],
                spec['note'],
                provenance='UNMEASURABLE',
                reason=why,
                ansur_ratio=spec.get('ansur'),
                **flags,
            )
        rec, loop = _girth_at(
            v,
            faces,
            np.array([0.0, 0.0, p[2]]),
            np.array([0.0, 0.0, 1.0]),
            spec['scope'],
            p,
            u_hint=np.array([1.0, 0.0, 0.0]),
        )
        val = None if loop is None else (rec['x_extent_mm'] if axis == 'x' else rec['y_extent_mm'])
        if val is None:
            return _rec(
                None,
                kind,
                spec['landmark'],
                conv,
                spec['iso_class'],
                spec['note'],
                provenance='REFUSED',
                reason=rec.get('reason', 'no contour'),
                ansur_ratio=spec.get('ansur'),
                arm_mask=rec.get('arm_mask'),
                **flags,
            )
        extra = {'found_at_frac_stature': (p[2] - zmin) / H, 'anchor': why}
    out = _rec(
        val,
        kind,
        spec['landmark'],
        conv,
        spec['iso_class'],
        spec['note'],
        scope=spec['scope'],
        ansur_ratio=spec.get('ansur'),
        loops_found=rec.get('loops_found'),
        selected_by=rec.get('selected_by'),
        arm_triangles_in_loop=rec.get('arm_triangles_in_loop'),
        arm_mask=rec.get('arm_mask'),
        frac_stature=val / (H * 1000),
        **flags,
        **extra,
    )
    for k in ('x_extent_unmasked_mm', 'y_extent_unmasked_mm', 'arm_excluded_x_extent_mm', 'arm_excluded_y_extent_mm'):
        if k in rec:
            out[k] = rec[k]
    unmasked = rec.get('x_extent_unmasked_mm' if axis == 'x' else 'y_extent_unmasked_mm')
    if unmasked is not None:
        out['value_without_arm_mask_mm'] = unmasked
    if band_note:
        out['band_adjustment'] = band_note
    if spec['scope'] == 'all':
        out['arms_included'] = True
        excl = rec.get('arm_excluded_x_extent_mm' if axis == 'x' else 'arm_excluded_y_extent_mm')
        if excl is not None:
            out['arm_excluded_value_mm'] = excl
            out['arm_excluded_note'] = (
                'the same extent with every contour point at or above %.2f of arm '
                "skinning weight dropped. It is NOT this site's dimension — the site is "
                'defined over the arms — and it is not gated. It is here so an operator '
                'can see the trunk alone underneath the A-pose.' % ARM_SKIN_WEIGHT_THRESHOLD
            )
    if pose_ref is not None:
        _attach_pose_bias(
            out,
            lambda: _extent_measure(
                pose_ref,
                faces,
                spec,
                lm,
                float(np.asarray(pose_ref)[:, 2].min()),
                H,
                step,
                axis,
                ear_top,
                crotch_frac,
                pose_ref=None,
            ),
        )
    return out
