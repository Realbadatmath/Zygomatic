# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Angle measurement, the result record, and GATE 1 t5_joint_rom.

Moved verbatim out of the old single-file pose_limits.py (lines 1376-1854).
"""

from zyg_workflows.geom.pose_limits.base import (
    CANON,
    FAIL,
    PASS,
    REPORT,
    STATUSES,
    UNMEASURABLE,
    UNRESOLVED,
    WARN,
    np,
    strict_wrist,
)
from zyg_workflows.geom.pose_limits.printed import (
    CERVICAL_EXTENSION_TOTAL_MAX_DEG,
    CERVICAL_MAPPING_NOTE,
    CERVICAL_PER_JOINT_DEG,
    CERVICAL_RIG_JOINTS,
    CERVICAL_SOURCE,
    OCCIPUT_C2_MIN_SHARE,
    OCCIPUT_SOURCE,
    WRIST_EXTENSION_FORCED_DEG,
    WRIST_EXTENSION_NATURAL_DEG,
    WRIST_FLEXION_FORCED_DEG,
    WRIST_FLEXION_NATURAL_DEG,
    WRIST_RADIAL_MAX_DEG,
    WRIST_SOURCE,
    WRIST_ULNAR_MAX_DEG,
)
from zyg_workflows.geom.pose_limits.rig import (
    _LONG,
    _joint_ref_axes,
    _model_index,
    anatomical_frame,
    bone_index,
    joint_delta,
    rot_angle_deg,
    swing_twist,
    unit,
)
from zyg_workflows.geom.pose_limits.skeleton import FRAME_NOTES, IMAGE2D, PSEUDO3D


# ---------------------------------------------------------------------------------
# ANGLE MEASUREMENT. Every construction below is available to both sources.
# ---------------------------------------------------------------------------------
def _hand_frame(sk, side):
    """(forearm distal axis, ulnar axis, dorsal axis) for one hand, all measured.

    The ulnar direction is unambiguous — it points from the index MCP to the pinky MCP, and
    both sources name those landmarks.

    THE DORSAL SIGN IS A CHIRALITY, AND THAT MATTERS. The obvious construction — test which
    side of the forearm's plane the thumb tip is on — is what this started as and it is
    wrong in a way that only appears at large angles: the plane is built on the FOREARM
    axis, the thumb travels with the HAND, and past about 90 degrees of wrist extension the
    thumb crosses that plane and the sign flips. MEASURED: a wrist driven to 120 degrees of
    extension then read back at -117.6 degrees, i.e. as violent flexion.

    So the sign is taken from a quantity that is invariant under any rigid motion of the
    hand: the handedness of (hand axis, ulnar axis, thumb offset), all three of which live
    in the hand and rotate together. That chirality is then applied to the forearm-frame
    normal. It is the same number at rest and it stays the same number at 120 degrees.
    """
    need = [
        'elbow_%s' % side,
        'wrist_%s' % side,
        'index_mcp_%s' % side,
        'pinky_mcp_%s' % side,
        'thumb_tip_%s' % side,
        'mcp3_%s' % side,
    ]
    miss = sk.missing(*need)
    if miss:
        return None, miss
    u = unit(sk.p('wrist_%s' % side) - sk.p('elbow_%s' % side))
    t_raw = sk.p('pinky_mcp_%s' % side) - sk.p('index_mcp_%s' % side)
    t = unit(t_raw - (t_raw @ u) * u)
    # chirality, entirely inside the hand
    h = sk.p('mcp3_%s' % side) - sk.p('wrist_%s' % side)
    centre = 0.5 * (sk.p('index_mcp_%s' % side) + sk.p('pinky_mcp_%s' % side))
    chir = float((sk.p('thumb_tip_%s' % side) - centre) @ np.cross(h, t_raw))
    if abs(chir) < 1e-12:
        return None, [
            'thumb_tip_%s (degenerate: the thumb, the hand axis and the ulnar '
            'axis are coplanar, so the dorsal sign cannot be measured)' % side
        ]
    dorsal = unit(-np.sign(chir) * np.cross(u, t))
    kind = 'hand_derived'

    # THE FRAME MUST BE FIXED TO THE FOREARM OR THE TWO ANGLES CONTAMINATE EACH OTHER.
    # A hand-derived transverse axis travels with the hand: at 70 deg of pure dorsiflexion
    # its projection into the plane perpendicular to the forearm has itself swung, and the
    # deviation reading picks that up. MEASURED on the neutral with the hand-derived frame:
    # a PURE 70 deg extension drive reports 17.7 deg of ulnar deviation that is not in the
    # motion. Where the rig is available the forearm's OWN bone frame is used instead — a
    # wrist rotation does not move lowerarm02, so those axes are genuinely stationary and
    # the decomposition is exact. Which bone axis is 'ulnar' and which 'dorsal' is not
    # assumed: it is fixed once from the REST hand, where the hand is at neutral and the
    # hand-derived frame is correct, and then carried through the pose rigidly.
    if sk.state is not None:
        S = 'L' if side == 'l' else 'R'
        fb = 'lowerarm02.%s' % S
        if fb in _model_index():
            st = sk.state
            rh, rt = st['rest_heads'], st['rest_tails']
            u0 = unit(rh[bone_index('wrist.%s' % S)] - rh[bone_index('lowerarm01.%s' % S)])
            t0r = rh[bone_index('finger5-1.%s' % S)] - rh[bone_index('finger2-1.%s' % S)]
            t0 = unit(t0r - (t0r @ u0) * u0)
            h0 = rh[bone_index('finger3-1.%s' % S)] - rh[bone_index('wrist.%s' % S)]
            c0 = 0.5 * (rh[bone_index('finger2-1.%s' % S)] + rh[bone_index('finger5-1.%s' % S)])
            chir0 = float((rt[bone_index('finger1-3.%s' % S)] - c0) @ np.cross(h0, t0r))
            d0 = unit(-np.sign(chir0) * np.cross(u0, t0))
            R = st['R'][bone_index(fb)] @ st['rest_R'][bone_index(fb)].T
            t = unit(R @ t0)
            dorsal = unit(R @ d0)
            t = unit(t - (t @ u) * u)
            dorsal = unit(dorsal - (dorsal @ u) * u - (dorsal @ t) * t)
            kind = 'forearm_bone'
    return {'forearm': u, 'ulnar': t, 'dorsal': dorsal, 'frame_kind': kind, 'hand_chirality': chir}, []


def wrist_angles(sk, side):
    """Extension(+)/flexion(-) and ulnar(+)/radial(-) deviation of one wrist, in degrees.

    THE ZERO IS ANATOMICAL NEUTRAL, not the rig's rest pose: the clinical definition of a
    neutral wrist is the hand axis collinear with the forearm axis, and that definition
    travels between our rig and an incoming skeleton while a rig-specific rest offset does
    not. On the anny neutral the rest pose measures -2.9 deg of extension and -5.0 deg of
    ulnar deviation by this construction, i.e. the shipped A-pose is already within 6
    degrees of anatomical neutral at both wrists on all five bodies.

    The hand axis is wrist -> third-metacarpal head, which is the axis a goniometer is laid
    along.
    """
    fr, miss = _hand_frame(sk, side)
    if fr is None:
        return {'resolved': False, 'missing': miss}
    u, t, n = fr['forearm'], fr['ulnar'], fr['dorsal']
    h = unit(sk.p('mcp3_%s' % side) - sk.p('wrist_%s' % side))
    total = float(np.degrees(np.arccos(np.clip(h @ u, -1.0, 1.0))))

    # THE DECOMPOSITION IS THE ROTATION VECTOR OF THE MINIMAL ROTATION u -> h, resolved on
    # the two anatomical axes. It is exact and it is DECOUPLED: a pure rotation about the
    # transverse axis has a rotation vector parallel to that axis, so its deviation
    # component is identically zero.
    #
    # WHY NOT THE OBVIOUS THING. Two projected angles, atan2(h.dorsal, h.forearm) and
    # atan2(h.ulnar, h.forearm), is what clinical goniometry reads and it is what this did
    # first. It is wrong here in two measurable ways. (1) They share a denominator, so a
    # large extension inflates the apparent deviation from nothing: MEASURED on the
    # neutral, a PURE 70 deg dorsiflexion drive reported 30.3 deg of radial deviation that
    # is not in the motion. (2) Past 90 degrees the shared denominator turns negative and
    # the second angle jumps a branch, reporting 154.9 deg. Both projections are kept in
    # the record as `projected_*` because they are the numbers a goniometer would show, but
    # the gate reads the rotation vector.
    axis = np.cross(u, h)
    s = float(np.linalg.norm(axis))
    ang = float(np.arctan2(s, float(np.clip(u @ h, -1.0, 1.0))))
    w = (axis / s) * ang if s > 1e-12 else np.zeros(3)
    # Rotating about a unit axis `a` moves u in the direction a x u, so the generator that
    # carries the hand DORSALLY is unit(u x dorsal) and the one that carries it ULNARWARD
    # is unit(u x ulnar). Written this way the signs are correct for both hands without a
    # per-side special case — which matters, because (forearm, ulnar, dorsal) is
    # right-handed on one side and left-handed on the other by construction.
    ext = float(np.degrees(w @ unit(np.cross(u, n))))
    uln = float(np.degrees(w @ unit(np.cross(u, t))))
    out_of_plane = float(np.degrees(abs(w @ u)))
    pext = float(np.degrees(np.arctan2(h @ n, h @ u)))
    puln = float(np.degrees(np.arctan2(h @ t, h @ u)))
    return {
        'resolved': True,
        'extension_deg': ext,
        'ulnar_deviation_deg': uln,
        'frame_kind': fr['frame_kind'],
        'frame_caveat': (
            None
            if fr['frame_kind'] == 'forearm_bone'
            else 'the transverse and dorsopalmar axes are derived from the '
            'HAND, because a positions-only skeleton carries no forearm '
            'roll — three points cannot see an axial rotation. MEASURED '
            'cost of that on our own rig: a pure 70 deg dorsiflexion '
            'reads about 18 deg of ulnar deviation that is not in the '
            'motion. Extension is nearly unaffected.'
        ),
        'flexion_deg': -ext,
        'radial_deviation_deg': -uln,
        'total_deviation_from_neutral_deg': total,
        'projected_extension_deg': pext,
        'projected_ulnar_deviation_deg': puln,
        'out_of_plane_component_deg': out_of_plane,
        # the rotation vector is single-valued to 180 deg; nothing here degenerates
        # inside the physiological range, and past 180 the swing itself is ambiguous.
        'projection_degenerate': bool(total > 180.0 - 1e-9),
        'degenerate_reason': (
            None
            if total <= 180.0 - 1e-9
            else 'the hand axis is antiparallel to the forearm axis; the '
            'minimal rotation between them has no unique axis'
        ),
        'mcp3_constructed': ('mcp3_%s' % side) in sk.constructed,
        'hand_chirality': fr['hand_chirality'],
    }


def elbow_angle(sk, side):
    """The INCLUDED angle at the elbow. 180 = straight. Frame-free, source-free."""
    need = ['shoulder_%s' % side, 'elbow_%s' % side, 'wrist_%s' % side]
    if sk.missing(*need):
        return None
    a = sk.p('shoulder_%s' % side) - sk.p('elbow_%s' % side)
    b = sk.p('wrist_%s' % side) - sk.p('elbow_%s' % side)
    return float(np.degrees(np.arccos(np.clip(unit(a) @ unit(b), -1.0, 1.0))))


def knee_angle(sk, side):
    need = ['hip_%s' % side, 'knee_%s' % side, 'ankle_%s' % side]
    if sk.missing(*need):
        return None
    a = sk.p('hip_%s' % side) - sk.p('knee_%s' % side)
    b = sk.p('ankle_%s' % side) - sk.p('knee_%s' % side)
    return float(np.degrees(np.arccos(np.clip(unit(a) @ unit(b), -1.0, 1.0))))


def cervical_angles(sk):
    """Per-joint and total cervical rotation, and the occiput-C2 share.

    RIG ONLY, and the reason is structural rather than incidental: per-joint cervical
    angles need the orientation of each neck bone, and the only way to know how a rotation
    divides between neck01, neck02, neck03 and the head is to look at the bones. A
    keypoint skeleton has one head landmark and one neck landmark and can express the TOTAL
    and nothing else — so on any non-rig source this returns unresolved with the reason
    attached rather than dividing the total by four and calling it a measurement.
    """
    if sk.state is None:
        return {
            'resolved': False,
            'reason': 'per-joint cervical angles need per-bone orientations; this '
            'skeleton carries joint POSITIONS only. A cervical chain with '
            'four joints and two observable endpoints is under-determined '
            'and no split can be measured from it.',
            'source_frame': sk.frame,
        }
    st = sk.state
    af = anatomical_frame(st)
    ant, left = af['anterior'], af['subject_left']
    posterior = -ant
    per = {}
    for bone in CERVICAL_RIG_JOINTS:
        # joint_delta returns the delta in the BONE'S OWN REST FRAME, where the long axis
        # is exactly +Y. Decomposing it against a world direction is a frame error, and a
        # loud one: it made every neck joint read 16-23 degrees of extension AT REST,
        # because the neck bones lean and the world 'posterior' has a component along them.
        # The reference directions are carried into the bone frame instead, and
        # orthogonalised against the long axis so the rest pose reads exactly zero.
        ex, ey = _joint_ref_axes(st, bone, posterior, left)
        Q = joint_delta(st, bone)
        d = Q @ _LONG
        pitch = float(np.degrees(np.arctan2(d @ ex, d @ _LONG)))
        bend = float(np.degrees(np.arctan2(d @ ey, d @ _LONG)))
        _, twist = swing_twist(Q, _LONG)
        per[bone] = {
            'extension_deg': pitch,
            'lateral_bend_deg': bend,
            'yaw_deg': float(twist),
            'total_deg': rot_angle_deg(Q),
        }
    # the TOTAL is measured geometrically between the head and the thorax, not summed:
    # finite rotations do not commute and the sum is only an approximation of the total.
    # This one IS a world-space rotation, so its axes are world axes.
    Rn = st['R'][bone_index('head')] @ st['rest_R'][bone_index('head')].T
    Rt = st['R'][bone_index('spine01')] @ st['rest_R'][bone_index('spine01')].T
    Rc = Rt.T @ Rn
    axis = unit(st['rest_R'][bone_index('head')][:, 1])
    ex = unit(posterior - (posterior @ axis) * axis)
    ey = unit(left - (left @ axis) * axis)
    d = Rc @ axis
    tot_ext = float(np.degrees(np.arctan2(d @ ex, d @ axis)))
    tot_bend = float(np.degrees(np.arctan2(d @ ey, d @ axis)))
    _, tot_yaw = swing_twist(Rc, axis)
    sum_ext = sum(per[b]['extension_deg'] for b in CERVICAL_RIG_JOINTS)
    sum_yaw = sum(per[b]['yaw_deg'] for b in CERVICAL_RIG_JOINTS)

    def share(key, total):
        denom = sum(abs(per[b][key]) for b in CERVICAL_RIG_JOINTS)
        if denom < 1e-9:
            return None
        return float(abs(per['head'][key]) / denom)

    return {
        'resolved': True,
        'per_joint': per,
        'total_extension_deg': tot_ext,
        'total_lateral_bend_deg': tot_bend,
        'total_yaw_deg': float(tot_yaw),
        'total_deg': rot_angle_deg(Rc),
        'sum_of_joint_extension_deg': sum_ext,
        'sum_of_joint_yaw_deg': sum_yaw,
        'sum_minus_total_extension_deg': sum_ext - tot_ext,
        'occiput_share_pitch': share('extension_deg', tot_ext),
        'occiput_share_yaw': share('yaw_deg', tot_yaw),
        'joints': list(CERVICAL_RIG_JOINTS),
        'mapping_note': CERVICAL_MAPPING_NOTE,
    }


# ---------------------------------------------------------------------------------
# result record
# ---------------------------------------------------------------------------------
def _res(gate, status, explain, observed=None, band=None, source=None, provenance=None, **detail):
    if status not in STATUSES:
        raise ValueError('unknown status %r' % status)
    out = {
        'gate': gate,
        'status': status,
        'observed': observed,
        'band': band,
        'source': source,
        'provenance': provenance,
        'explain': explain,
    }
    if detail:
        out['detail'] = detail
    return out


# ---------------------------------------------------------------------------------
# GATE 1 — t5_joint_rom
# ---------------------------------------------------------------------------------
def t5_joint_rom(sk):
    """Per-joint ROM against the printed bands, on the rig AND on incoming pose data."""
    if sk.frame == IMAGE2D:
        return _res(
            't5_joint_rom',
            UNMEASURABLE,
            'a 2D projection cannot bound a 3D joint angle',
            source=WRIST_SOURCE,
            provenance=CANON,
            frame=sk.frame,
            frame_note=FRAME_NOTES[IMAGE2D],
            remedy='lift the pose through geom/anny_fit.py, which fits the rig to '
            'the keypoints and produces a metric3d skeleton this gate can '
            'read',
        )
    checks, worst = [], PASS
    ext_fail = WRIST_EXTENSION_NATURAL_DEG if strict_wrist() else WRIST_EXTENSION_FORCED_DEG
    flx_fail = WRIST_FLEXION_NATURAL_DEG if strict_wrist() else WRIST_FLEXION_FORCED_DEG

    def bump(s):
        order = {PASS: 0, REPORT: 0, WARN: 1, UNMEASURABLE: 1, UNRESOLVED: 1, FAIL: 2}
        return s if order[s] > order[worst] else worst

    for side in ('l', 'r'):
        w = wrist_angles(sk, side)
        if not w['resolved']:
            checks.append({'check': 'wrist_%s' % side, 'status': UNRESOLVED, 'missing': w['missing']})
            worst = bump(UNRESOLVED)
            continue
        ext, uln = w['extension_deg'], w['ulnar_deviation_deg']
        # extension / flexion
        if ext >= 0:
            st = FAIL if ext > ext_fail else WARN if ext > WRIST_EXTENSION_NATURAL_DEG else PASS
            checks.append(
                {
                    'check': 'wrist_%s_extension' % side,
                    'status': st,
                    'observed_deg': round(ext, 2),
                    'natural_deg': WRIST_EXTENSION_NATURAL_DEG,
                    'forced_deg': WRIST_EXTENSION_FORCED_DEG,
                }
            )
        else:
            f = -ext
            st = FAIL if f > flx_fail else WARN if f > WRIST_FLEXION_NATURAL_DEG else PASS
            checks.append(
                {
                    'check': 'wrist_%s_flexion' % side,
                    'status': st,
                    'observed_deg': round(f, 2),
                    'natural_deg': WRIST_FLEXION_NATURAL_DEG,
                    'forced_deg': WRIST_FLEXION_FORCED_DEG,
                }
            )
        worst = bump(st)
        # deviation. Radial is the unnatural direction and is flagged as such at ANY
        # magnitude, per AFS p.181-182, in addition to its 20-degree limit.
        if w['projection_degenerate']:
            checks.append(
                {
                    'check': 'wrist_%s_deviation' % side,
                    'status': UNMEASURABLE,
                    'reason': w['degenerate_reason'],
                    'total_deviation_from_neutral_deg': round(w['total_deviation_from_neutral_deg'], 2),
                }
            )
            worst = bump(UNMEASURABLE)
        elif uln >= 0:
            st = FAIL if uln > WRIST_ULNAR_MAX_DEG else PASS
            checks.append(
                {
                    'check': 'wrist_%s_ulnar_deviation' % side,
                    'status': st,
                    'observed_deg': round(uln, 2),
                    'max_deg': WRIST_ULNAR_MAX_DEG,
                }
            )
        else:
            r = -uln
            st = FAIL if r > WRIST_RADIAL_MAX_DEG else PASS
            checks.append(
                {
                    'check': 'wrist_%s_radial_deviation' % side,
                    'status': st,
                    'observed_deg': round(r, 2),
                    'max_deg': WRIST_RADIAL_MAX_DEG,
                    'unnatural_direction': True,
                    'note': 'radial deviation is the unnatural direction; any non-zero value is flagged',
                }
            )
        worst = bump(st)

    cerv = cervical_angles(sk)
    if not cerv['resolved']:
        checks.append({'check': 'cervical', 'status': UNRESOLVED, 'reason': cerv['reason']})
        worst = bump(UNRESOLVED)
    else:
        ext = cerv['total_extension_deg']
        st = FAIL if ext > CERVICAL_EXTENSION_TOTAL_MAX_DEG else PASS
        checks.append(
            {
                'check': 'cervical_extension_total',
                'status': st,
                'observed_deg': round(ext, 2),
                'max_deg': CERVICAL_EXTENSION_TOTAL_MAX_DEG,
            }
        )
        worst = bump(st)
        for bone in CERVICAL_RIG_JOINTS:
            e = abs(cerv['per_joint'][bone]['extension_deg'])
            st = FAIL if e > CERVICAL_PER_JOINT_DEG[1] else WARN if e > CERVICAL_PER_JOINT_DEG[0] else PASS
            checks.append(
                {
                    'check': 'cervical_per_joint_%s' % bone,
                    'status': st,
                    'observed_deg': round(e, 2),
                    'band_deg': list(CERVICAL_PER_JOINT_DEG),
                }
            )
            worst = bump(st)
        for key, label, tot in (
            ('occiput_share_pitch', 'pitch', cerv['total_extension_deg']),
            ('occiput_share_yaw', 'yaw', cerv['total_yaw_deg']),
        ):
            sh = cerv[key]
            if sh is None:
                checks.append(
                    {
                        'check': 'occiput_c2_share_%s' % label,
                        'status': UNMEASURABLE,
                        'reason': 'total cervical %s is zero in this pose, so there '
                        'is no rotation to apportion' % label,
                    }
                )
                continue
            st = FAIL if sh < OCCIPUT_C2_MIN_SHARE else PASS
            # THE MAGNITUDE SHIPS WITH THE SHARE, ALWAYS. A share is a ratio and says
            # nothing about how much rotation was misplaced: 0.17 on a 40 deg turn and
            # 0.17 on a 0.4 deg twitch are the same number and are not the same finding.
            # No magnitude cut-off is applied, because no printed source gives one — the
            # size is reported instead so the reader can weigh it.
            checks.append(
                {
                    'check': 'occiput_c2_share_%s' % label,
                    'status': st,
                    'observed_share': round(sh, 4),
                    'min_share': OCCIPUT_C2_MIN_SHARE,
                    'total_cervical_deg': round(float(tot), 3),
                    'occiput_joint_deg': round(
                        float(cerv['per_joint']['head']['extension_deg' if label == 'pitch' else 'yaw_deg']), 3
                    ),
                }
            )
            worst = bump(st)

    n_fail = sum(1 for c in checks if c['status'] == FAIL)
    n_warn = sum(1 for c in checks if c['status'] == WARN)
    explain = '%d of %d ROM sub-checks failed, %d warned' % (n_fail, len(checks), n_warn)
    if sk.frame == PSEUDO3D:
        # The sub-check verdicts are kept because they carry information, but the GATE
        # verdict is downgraded: BlazePose's z is not on the same scale as its x and y, so
        # every angle read off it carries an unknown anisotropic bias and no verdict from
        # it may block. Stated in the module docstring and enforced here.
        worst = REPORT
        explain += ' — reported, NOT gated: %s' % FRAME_NOTES[PSEUDO3D]
    return _res(
        't5_joint_rom',
        worst,
        explain,
        observed={'fail': n_fail, 'warn': n_warn, 'checks': len(checks)},
        band={
            'wrist': [
                WRIST_EXTENSION_NATURAL_DEG,
                WRIST_EXTENSION_FORCED_DEG,
                WRIST_FLEXION_NATURAL_DEG,
                WRIST_FLEXION_FORCED_DEG,
                WRIST_ULNAR_MAX_DEG,
                WRIST_RADIAL_MAX_DEG,
            ],
            'cervical_total': CERVICAL_EXTENSION_TOTAL_MAX_DEG,
            'cervical_per_joint': list(CERVICAL_PER_JOINT_DEG),
            'occiput_share': OCCIPUT_C2_MIN_SHARE,
        },
        source='; '.join((WRIST_SOURCE, CERVICAL_SOURCE, OCCIPUT_SOURCE)),
        provenance=CANON,
        checks=checks,
        frame=sk.frame,
        skeleton=sk.source,
        strict_wrist=strict_wrist(),
        cervical=cerv if cerv['resolved'] else None,
    )
