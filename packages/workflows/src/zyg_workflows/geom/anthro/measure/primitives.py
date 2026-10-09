# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The measurement primitives, the A-pose convention bias, the preconditions and the volume.

Moved verbatim out of the old single-file measure.py (lines 1718-2208).
"""

import math

import numpy as np

from zyg_workflows.geom import mesh_skeletons as MS
from zyg_workflows.geom.anthro import landmarks as LMK
from zyg_workflows.geom.anthro.measure.constants import (
    MIRROR_MAP_ADVISORY_MM,
    MIRROR_MAP_VALIDITY_MAX_MM,
    POSE_HALFSPAN_FRAC_STATURE,
    POSE_HAND_FRAC_STATURE,
)
from zyg_workflows.geom.anthro.measure.topology import (
    _arm_mask_record,
    _split_arm_points,
    _topology,
    arm_skin_weights,
)
from zyg_workflows.geom.anthro.measure.slicing import (
    _arm_merge_check,
    _select_loop,
    loop_metrics,
    polyline_girth,
    slice_loops,
)


# ---------------------------------------------------------------------------------
# measurement primitives
# ---------------------------------------------------------------------------------
def _girth_at(v, faces, origin, normal, scope, anchor, u_hint=None, side=None):
    """One plane, one selected loop, all three conventions. Returns (record, loop).

    `side` is the limb guard. A plane through an abducted arm or a thigh stops being a
    limb section the moment the limb merges into the torso or into its partner, and the
    girth silently becomes a pelvis girth — measured on cornelis before this guard existed,
    the thigh scan returned 1139 mm (0.633 of stature against an ANSUR thigh of 0.356).
    The test is that a limb section lies entirely on its own side of the midsagittal
    plane; a merged section always crosses it. Violation REFUSES the plane, it does not
    fall back to a narrower window.

    THE ARM MASK. For scope 'torso' and 'head' every contour point at or above
    ARM_SKIN_WEIGHT_THRESHOLD of arm skinning weight is dropped before the breadth, the
    depth and the hull are taken, and the record carries how many were dropped and what
    the numbers were without the mask. The girth is conditional: a hull over the arm-free
    points is a taut tape passing under the arm while the trunk contour is still closed
    and both arms appear as loops of their own, so it IS promoted to value_mm there; once
    an arm has merged into the trunk the mask removes an arc rather than a few axillary
    points, the hull across that gap is not a tape reading, and the girth is refused —
    while the breadth and depth, which are well defined on any point set, survive. Scope
    'all' is the tape that DELIBERATELY goes over both deltoids, so its primary numbers
    stay unmasked and the arm-free ones ride alongside as arm_excluded_*.
    """
    loops, info = slice_loops(v, faces, origin, normal)
    if not loops:
        return {'value_mm': None, 'reason': 'no contour at this plane', **info}, None
    if scope == 'all':
        pts = np.vstack([l['pts'] for l in loops])
        aws = [l.get('arm_w') for l in loops]
        merged = {
            'pts': pts,
            'tris': np.unique(np.concatenate([l['tris'] for l in loops])),
            'ring_below': np.concatenate([l['ring_below'] for l in loops]),
            'arm_w': None if any(a is None for a in aws) else np.concatenate(aws),
        }
        met = loop_metrics(merged, normal, u_hint)
        rec = {
            'value_mm': met['hull_m'] * 1000 if met['hull_m'] is not None else None,
            'hull_mm': met['hull_m'] * 1000 if met['hull_m'] is not None else None,
            'contour_mm': None,
            'loops_found': len(loops),
            'loops_used': len(loops),
            'selected_by': 'ALL loops merged before hulling (tape passes over the arms)',
            'x_extent_mm': met['x_extent_m'] * 1000,
            'y_extent_mm': met['y_extent_m'] * 1000,
            'arm_triangles_in_loop': None,
            **info,
        }
        keep, ndrop, wmax = _split_arm_points(merged)
        rec['arm_mask'] = _arm_mask_record(scope, keep, ndrop, wmax, met, None)
        if keep is not None and int(keep.sum()) >= 3:
            af = loop_metrics({'pts': pts[keep]}, normal, u_hint)
            rec['arm_excluded_hull_mm'] = None if af['hull_m'] is None else af['hull_m'] * 1000
            rec['arm_excluded_x_extent_mm'] = af['x_extent_m'] * 1000
            rec['arm_excluded_y_extent_mm'] = af['y_extent_m'] * 1000
        return rec, merged
    if scope in ('torso', 'head'):
        k, why = _select_loop(loops, 'largest')
    else:
        k, why = _select_loop(loops, 'nearest', anchor)
    loop = loops[k]
    met = loop_metrics(loop, normal, u_hint)
    poly, ring, spread, planar = polyline_girth(v, faces, loop, normal, origin)
    merge = _arm_merge_check(faces, loops, k)
    arm = merge['arm_triangles_in_loop']

    # arm exclusion, for the scopes whose definition is "the trunk / the head"
    keep, ndrop, wmax = _split_arm_points(loop)
    masked = scope in ('torso', 'head') and keep is not None and ndrop
    met_af = met
    if masked:
        if int(keep.sum()) >= 3:
            met_af = loop_metrics({'pts': loop['pts'][keep]}, normal, u_hint)
        else:
            met_af = None

    rec = {
        'value_mm': met['hull_m'] * 1000 if met['hull_m'] is not None else None,
        'hull_mm': met['hull_m'] * 1000 if met['hull_m'] is not None else None,
        'contour_mm': met['contour_m'] * 1000,
        'polyline_mm': poly * 1000 if poly is not None else None,
        'polyline_planar_mm': None if planar is None else planar * 1000,
        'polyline_ring_out_of_plane_mm': None if spread is None else spread * 1000,
        'section_area_mm2': met['area_m2'] * 1e6,
        'x_extent_mm': met['x_extent_m'] * 1000,
        'y_extent_mm': met['y_extent_m'] * 1000,
        'loops_found': len(loops),
        'selected_by': why,
        'contour_points': met['n_points'],
        'ring_vertices': int(len(ring)),
        'arm_triangles_in_loop': arm,
        'arm_triangle_mask': merge['arm_triangle_mask'],
        'arm_triangles_in_loop_morph_support': merge['arm_triangles_in_loop_morph_support'],
        'arm_loops_present': merge['arm_loops_present'],
        **info,
    }
    rec['arm_mask'] = _arm_mask_record(scope, keep, ndrop, wmax, met, met_af)
    if masked:
        # Extents ARE well defined on a point subset even when the section is interrupted,
        # so they always come from the arm-free points and the unmasked ones sit beside
        # them. The GIRTH is conditional: a hull over the arm-free points is a taut tape
        # passing under the arm only while the trunk contour is still a closed loop with
        # both arms accounted for elsewhere. Once the arm has MERGED into the trunk the
        # mask removes an arc, not a few axillary points, and the hull across that gap is
        # not a tape reading — so the girth is refused below, exactly as before.
        rec['x_extent_unmasked_mm'] = met['x_extent_m'] * 1000
        rec['y_extent_unmasked_mm'] = met['y_extent_m'] * 1000
        rec['arm_masked_hull_mm'] = None if met_af is None or met_af['hull_m'] is None else met_af['hull_m'] * 1000
        rec['hull_unmasked_mm'] = None if met['hull_m'] is None else met['hull_m'] * 1000
        rec['arm_mask']['contour_mm_is_unmasked'] = (
            'contour_mm, polyline_mm and section_area_mm2 are the RAW section: a '
            'perimeter and a vertex ring have no meaning once points are removed from '
            'the middle of them, so they are left unmasked rather than recomputed on a '
            'broken curve.'
        )
        if met_af is None:
            rec['x_extent_mm'] = None
            rec['y_extent_mm'] = None
        else:
            rec['x_extent_mm'] = met_af['x_extent_m'] * 1000
            rec['y_extent_mm'] = met_af['y_extent_m'] * 1000
            if not merge['merged'] and met_af['hull_m'] is not None:
                rec['value_mm'] = met_af['hull_m'] * 1000
                rec['hull_mm'] = met_af['hull_m'] * 1000
                rec['arm_mask']['girth_masked'] = True
        rec['arm_mask'].setdefault('girth_masked', False)
        rec['arm_mask']['changed_the_extents'] = True
    if side in ('l', 'r'):
        x = loop['pts'][:, 0]
        crosses = (x.min() < 0) if side == 'l' else (x.max() > 0)
        rec['limb_side_check'] = (
            ("all contour points on the subject's %s" % ('left' if side == 'l' else 'right'))
            if not crosses
            else 'CROSSES THE MIDLINE'
        )
        if crosses:
            rec['value_mm'] = None
            rec['reason'] = (
                'REFUSED: the selected %s-limb section spans x = %.1f to '
                '%.1f mm, i.e. it crosses the midsagittal plane, so the limb '
                'has merged with the torso or with the opposite limb at this '
                'plane and the girth would be a pelvis or trunk girth.'
                % ('left' if side == 'l' else 'right', x.min() * 1000, x.max() * 1000)
            )
            return rec, loop
    if scope == 'torso' and merge['merged']:
        rec['value_mm'] = None
        rec['reason'] = (
            'REFUSED: %d triangles of the selected torso loop are entirely '
            'inside the arm mask and only %d of the two arms appear as loops '
            'of their own at this plane, so an arm has fused to the trunk '
            'and the girth would include it. Nothing is clamped and no '
            'window is widened — the measurement is not available for this '
            'mesh at this site.' % (arm, merge['arm_loops_present'])
        )
    return rec, loop


def _scan_girth(v, faces, base_origin, normal, scope, anchor, mode, lo, hi, step, u_hint=None, side=None):
    """Search along the plane normal for the extreme girth the survey definition asks for.

    Returns the winning record with the scan window and whether the extreme landed on a
    band ENDPOINT — an endpoint hit means there is no interior extremum and the number is
    a boundary artefact of the window, which the caller must see.
    """
    n = np.asarray(normal, np.float64)
    n = n / np.linalg.norm(n)
    ts = np.arange(lo, hi + 1e-12, step)
    best = None
    prof = []
    for t in ts:
        rec, loop = _girth_at(v, faces, np.asarray(base_origin, np.float64) + t * n, n, scope, anchor, u_hint, side)
        val = rec.get('value_mm')
        prof.append((float(t), val))
        if val is None:
            continue
        if best is None or (val > best[1] if mode == 'max' else val < best[1]):
            best = (float(t), val, rec, loop)
    if best is None:
        return {
            'value_mm': None,
            'reason': 'no usable contour anywhere in the scan window (every plane was '
            'empty or refused by the limb / arm guard)',
            'scan_window_m': [float(lo), float(hi)],
        }, None
    t, val, rec, loop = best
    rec = dict(rec)
    usable = sum(1 for _a, b in prof if b is not None)
    rec['scan'] = {
        'mode': mode,
        'window_m': [float(lo), float(hi)],
        'step_m': float(step),
        'n_planes': int(len(ts)),
        'n_planes_usable': usable,
        'offset_m': t,
        'at_window_endpoint': bool(
            abs(t - min(a for a, b in prof if b is not None)) < step / 2
            or abs(t - max(a for a, b in prof if b is not None)) < step / 2
        ),
        'profile_mm': [(round(a, 5), None if b is None else round(b, 2)) for a, b in prof],
    }
    if rec['scan']['at_window_endpoint']:
        rec['endpoint_warning'] = (
            'the %s landed on the edge of the search window, so there is no interior '
            'extremum here and this number is a property of the window, not of the body' % mode
        )
    return rec, loop


def _extent_scan(v, faces, zlo, zhi, step, scope, axis, anchor=None):
    """Maximum in-plane extent along x (breadth) or y (depth) over a height band.

    A plane qualifies on whether it yields an EXTENT, not on whether it yields a girth.
    The two come apart exactly where an arm has merged into the trunk: the trunk section
    is no longer closed so its hull is not a tape reading, but the arm-free points still
    have a perfectly well-defined lateral spread. Keying this on value_mm (the girth) is
    what used to throw those planes away.

    Returns None when no plane in the band yielded an extent, otherwise a dict carrying
    the winner AND the whole scan: the full profile, the TOTAL number of planes scanned,
    the TOTAL number that were usable, and the winner's INDEX among the usable planes.

    The index is what the endpoint test is built on. Until 2026-08-05 this function
    returned the running usable count at the moment the best was found and the caller
    published it as 'planes_usable' — a RANK sold as a total, which read 1 or 2 on every
    body and every site regardless of how well supported the scan was, and read lowest
    exactly when the scan was most suspect. Rank and total are now separate fields, and
    the endpoint test compares indices rather than distances so it cannot be defeated by
    np.arange stopping short of the ceiling or by a winner that sits one full step in.
    """
    best = None
    prof = []
    n_ok = 0
    for z in np.arange(zlo, zhi + 1e-12, step):
        rec, loop = _girth_at(
            v,
            faces,
            np.array([0.0, 0.0, z]),
            np.array([0.0, 0.0, 1.0]),
            scope,
            anchor,
            u_hint=np.array([1.0, 0.0, 0.0]),
        )
        val = None
        if loop is not None:
            val = rec['x_extent_mm'] if axis == 'x' else rec['y_extent_mm']
        prof.append((float(z), val, rec.get('loops_found')))
        if val is None:
            continue
        if best is None or val > best[1]:
            best = (float(z), val, rec, n_ok)
        n_ok += 1
    if best is None:
        return None
    z, val, rec, idx = best
    return {
        'z': z,
        'value_mm': val,
        'rec': rec,
        'profile': prof,
        'n_planes': len(prof),
        'n_planes_usable': n_ok,
        'winner_index_among_usable': idx,
    }


# ---------------------------------------------------------------------------------
# the A-pose convention bias — how much of a torso number is the pose
# ---------------------------------------------------------------------------------
def _rodrigues(axis, ang):
    a = np.asarray(axis, np.float64)
    a = a / np.linalg.norm(a)
    K = np.array([[0.0, -a[2], a[1]], [a[2], 0.0, -a[0]], [-a[1], a[0], 0.0]])
    return np.eye(3) + math.sin(ang) * K + (1.0 - math.cos(ang)) * (K @ K)


def adducted_copy(v, coco):
    """This body with each humerus brought vertical, by linear blend skinning.

    WHY IT EXISTS. Excluding the arms from a torso loop does not put the trunk on the
    survey's convention. ANSUR breadths and girths are taken with the arms hanging in the
    anatomical position; anny's rest pose abducts the humerus 39.4-42.3 degrees (measured
    from the rig on all five bodies), and the axillary tissue is partly bound to the
    humerus, so abduction pulls the trunk silhouette itself sideways. That is a bias on
    chest breadth, chest depth and chest circumference which no arm mask can remove,
    because the tissue in question is trunk.

    HOW. Each vertex is displaced by its OWN arm skinning weight times the rigid rotation
    that takes the shoulder-to-elbow direction to straight down, about anny's own COCO
    shoulder centre. That is exactly the linear-blend-skinning response to an adduction of
    upperarm01, using the cage's real weights — not a heuristic, and not a fitted constant.

    ACCURACY, MEASURED 2026-08-05 against a GENUINE re-pose of the rig (rotating
    upperarm01.L/R until the humerus reads 0.7-1.4 degrees off vertical, then re-slicing
    the re-posed body at the same plane). Order: female / abel / stock / male / cornelis.

        chest breadth at thelion   genuine  -6.8  -10.1  -18.5  -36.9  -44.0 mm
                                   estimate -7.5  -11.9  -20.9  -46.1  -55.4 mm
        chest girth   at thelion   genuine -10.3  -10.6  -17.1  -44.3  -50.4 mm
                                   estimate -10.6  -13.2  -20.1  -53.7  -60.6 mm
        waist, buttock, head       genuine 0.0 mm exactly; estimate 0.0 mm exactly

    IT IS AN UPPER BOUND ON THE MAGNITUDE, NOT A LOWER ONE, and getting that backwards
    would make a gate too permissive rather than too strict. The genuine shift is 79-97%
    of this estimate on the trunk (0.79 0.80 0.85 0.89 0.91 on breadth, 0.80 0.83 0.83
    0.85 0.97 on girth); it over-corrects because rotating every arm-weighted vertex
    rigidly about the shoulder centre also swings the forearm and hand, which the rig's
    own kinematic chain does not do the same way. On the trunk it never UNDER-states the
    bias, on 10 of 10 site-body pairs measured.

    At bideltoid level it over-corrects far more — genuine -92.6 to -155.5 mm against an
    estimate of -117.9 to -198.9, i.e. the genuine shift is only 74-80% of it — and the
    estimate would move the male's bideltoid from p100 to inside the band while the
    genuine re-pose leaves it outside. That is exactly why bideltoid breadth and shoulder
    circumference are NOT rescued by this and stay NOT SURVEY-COMPARABLE: an arm-defined
    dimension in an A-pose is a different dimension, and a 20-26% error on a 150 mm
    correction is not a tolerance.

    Returns (vertices, info) or (None, info-with-a-reason). It never modifies v.
    """
    info = {
        'method': 'linear blend skinning: each vertex moves by its own arm-bone '
        'skinning weight times the rigid rotation that takes the '
        'shoulder-to-elbow direction to vertical, about the COCO shoulder '
        'centre',
        'bound': 'UPPER BOUND ON THE MAGNITUDE — validated against a genuine re-pose '
        'of the rig, which moves 79-97% as far on the trunk and 74-80% as '
        'far at bideltoid level. It never under-states the trunk bias on the '
        '10 site-body pairs measured.',
    }
    aw = arm_skin_weights()['weight']
    if aw is None:
        info.update(
            available=False,
            reason='no arm skinning weights: %s' % arm_skin_weights()['provenance'].get('reason', 'rig unreadable'),
        )
        return None, info
    if not coco:
        info.update(
            available=False,
            reason='anny COCO joint centres unavailable, so there is no shoulder '
            'centre to rotate about and no humerus direction to measure',
        )
        return None, info
    need = ('left_shoulder', 'left_elbow', 'right_shoulder', 'right_elbow')
    if any(k not in coco for k in need):
        info.update(available=False, reason='COCO is missing %s' % ', '.join(k for k in need if k not in coco))
        return None, info
    v = np.asarray(v, np.float64)
    if len(v) != len(aw):
        info.update(available=False, reason='mesh has %d vertices, the rig weights %d' % (len(v), len(aw)))
        return None, info
    out = v.copy()
    down = np.array([0.0, 0.0, -1.0])
    angles = {}
    for side, sign in (('left', 1.0), ('right', -1.0)):
        h = np.asarray(coco['%s_shoulder' % side], np.float64)
        e = np.asarray(coco['%s_elbow' % side], np.float64)
        d = e - h
        nd = np.linalg.norm(d)
        if nd < 1e-9:
            continue
        d = d / nd
        ax = np.cross(d, down)
        na = np.linalg.norm(ax)
        if na < 1e-9:  # already vertical
            angles[side] = 0.0
            continue
        ang = float(math.atan2(na, float(d @ down)))
        R = _rodrigues(ax / na, ang)
        w = np.where((v[:, 0] * sign) > 0.0, aw, 0.0)
        out += w[:, None] * ((h + (v - h) @ R.T) - v)
        angles[side] = math.degrees(ang)
    info.update(available=True, humerus_abduction_deg={k: round(a, 2) for k, a in angles.items()})
    return out, info


# ---------------------------------------------------------------------------------
# preconditions
# ---------------------------------------------------------------------------------
def check_pose_and_frame(v, faces):
    """Refuse to measure a mesh whose frame or pose is not the one every table assumes.

    This is not decoration. If +x were not the subject's left, every breadth would be a
    depth; if the pose were a T-pose, the deltoid would sit elsewhere and the arm loops
    would merge into the torso at different heights.
    """
    fr = LMK.frame_report(v, faces)
    problems = []
    if (fr['up_axis'], fr['up_sign']) != ('z', 1):
        problems.append('up axis is %s%s, expected +z' % ('+-'[fr['up_sign'] < 0], fr['up_axis']))
    if (fr['anterior_axis'], fr['anterior_sign']) != ('y', -1):
        problems.append('anterior axis is %s%s, expected -y' % ('+-'[fr['anterior_sign'] < 0], fr['anterior_axis']))
    if (fr['subject_left_axis'], fr['subject_left_sign']) != ('x', 1):
        problems.append(
            'subject-left axis is %s%s, expected +x' % ('+-'[fr['subject_left_sign'] < 0], fr['subject_left_axis'])
        )
    if not fr['handedness'].startswith('right-handed'):
        problems.append('frame is %s' % fr['handedness'])
    if not fr['outward_normals']:
        problems.append('vertex normals point inward; volume sign and hull orientation would both be wrong')
    advisories = []
    resid = fr['bilateral_symmetry_max_residual_mm']
    if resid > MIRROR_MAP_VALIDITY_MAX_MM:
        problems.append(
            "bilateral residual %.3f mm exceeds %.1f mm, so landmarks.py's "
            'mirror map can no longer be trusted to pair a left landmark with '
            'its true right twin, and every _r measurement would be taken at '
            'the wrong vertex' % (resid, MIRROR_MAP_VALIDITY_MAX_MM)
        )
    elif resid > MIRROR_MAP_ADVISORY_MM:
        advisories.append(
            'bilateral residual %.4f mm is above the %.2f mm morph-correctness tolerance. '
            'Measurement continues (the mirror map is still valid at this scale) but this '
            'mesh should FAIL geom.anthro.integrity.mirror_symmetry, which owns that gate. '
            'On the issued characters the cause is MS._apply_anatomy: the raw morph output '
            'is symmetric to 0.06 mm and the abs_definition sculpt is not mirror-'
            'equivariant.' % (resid, MIRROR_MAP_ADVISORY_MM)
        )

    vv = np.asarray(v, np.float64)
    zmin = float(vv[:, 2].min())
    H = float(vv[:, 2].max()) - zmin
    hand = MS._morph_support('l-hand-fingers-length-incr')[0]
    hand_fz = float(((vv[hand, 2] - zmin) / H).mean())
    halfspan = float(np.abs(vv[:, 0]).max()) / H
    if not (POSE_HAND_FRAC_STATURE[0] <= hand_fz <= POSE_HAND_FRAC_STATURE[1]):
        problems.append(
            'hand-support centroid at %.4f of stature is outside the A-pose '
            'window %s' % (hand_fz, POSE_HAND_FRAC_STATURE)
        )
    if not (POSE_HALFSPAN_FRAC_STATURE[0] <= halfspan <= POSE_HALFSPAN_FRAC_STATURE[1]):
        problems.append(
            'half-span %.4f of stature is outside the A-pose window %s — a '
            'T-pose or an arms-down pose invalidates the loop-separation '
            'argument that excludes the arms from every torso measurement' % (halfspan, POSE_HALFSPAN_FRAC_STATURE)
        )

    out = {
        'ok': not problems,
        'problems': problems,
        'advisories': advisories,
        'pose': 'A-pose (hand-support centroid %.4f of stature, half-span %.4f of stature)' % (hand_fz, halfspan),
        'hand_frac_stature': hand_fz,
        'halfspan_frac_stature': halfspan,
        'axis_convention': fr['convention'],
        'handedness': fr['handedness'],
        'ground_plane': fr['ground_plane'],
        'bilateral_residual_mm': resid,
        'mirror_map_involutive': fr['mirror_map_involutive'],
        'symmetry_note': 'this is a MIRROR-MAP VALIDITY check, not a symmetry gate; '
        'the morph-correctness gate is '
        'geom.anthro.integrity.mirror_symmetry',
        'outward_normals': fr['outward_normals'],
        'pose_window_house': {
            'hand_frac_stature': list(POSE_HAND_FRAC_STATURE),
            'halfspan_frac_stature': list(POSE_HALFSPAN_FRAC_STATURE),
            'provenance': 'HOUSE — margin around the four issued characters, measured 2026-08-05',
        },
    }
    if problems:
        raise ValueError(
            'mesh fails the measurement precondition and will NOT be measured:\n  - ' + '\n  - '.join(problems)
        )
    return out


# ---------------------------------------------------------------------------------
# volume
# ---------------------------------------------------------------------------------
def body_volume(v, faces):
    """Signed-volume sum over the BODY SHELL only, in cubic metres.

    The cage ships as four closed shells — the body plus eye/mouth inclusions. Summing all
    of them adds the inclusions to the body volume (measured: 0.057 L on the neutral,
    0.08 L on the male), which is small but is not the body.
    """
    v = np.asarray(v, np.float64)
    topo = _topology(faces)
    tri = topo['tri'][topo['body_tris']]
    a, b, c = v[tri[:, 0]], v[tri[:, 1]], v[tri[:, 2]]
    body = float(abs((np.cross(a, b) * c).sum() / 6.0))
    tri_all = topo['tri']
    a, b, c = v[tri_all[:, 0]], v[tri_all[:, 1]], v[tri_all[:, 2]]
    allv = float(abs((np.cross(a, b) * c).sum() / 6.0))
    return body, allv, topo['shell_note']
