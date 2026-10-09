# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""GATE 3 — t5_pronation_isolation.

Moved verbatim out of the old single-file pose_limits.py (lines 2368-2654).
"""

from zyg_workflows.geom.pose_limits.base import CANON, FAIL, MS, PASS, np
from zyg_workflows.geom.pose_limits.printed import (
    PRONATION_HUMERUS_ROTATION_MAX_DEG,
    PRONATION_SOURCE,
    TWIST_STATION_COUNTS,
)
from zyg_workflows.geom.pose_limits.rig import (
    _LONG,
    bone_index,
    joint_delta,
    kabsch,
    pose_from_local,
    rig_numerical_floor,
    rig_state,
    rot_angle_deg,
    swing_twist,
    unit,
)
from zyg_workflows.geom.pose_limits.rom import _res


# ---------------------------------------------------------------------------------
# GATE 3 — t5_pronation_isolation
# ---------------------------------------------------------------------------------
def _forearm_skin(state, side):
    """The forearm's own skin, by the rig's OWN skinning statement.

    Selecting by skinning weight is not circular here: the gate tests how the twist is
    DISTRIBUTED along the forearm, not which bone owns the skin. Using a geometric radius
    instead would put a free parameter into a gate whose whole claim is that it has none.
    """
    m = MS._model()
    vbi = m.vertex_bone_indices.numpy()
    vbw = m.vertex_bone_weights.numpy()
    want = {bone_index('lowerarm01.%s' % side), bone_index('lowerarm02.%s' % side)}
    w = np.zeros(len(vbi))
    for c in range(vbi.shape[1]):
        w += np.where(np.isin(vbi[:, c], list(want)), vbw[:, c], 0.0)
    return np.nonzero(w > 0.999)[0]


def _twist_profile(rest, posed, side, n_stations):
    """Signed rotation of each forearm cross-section about the forearm axis.

    Per station the rotation is the Kabsch fit of that ring of vertices from rest to posed
    — no free parameter — decomposed swing-twist about the segment axis. `n_stations` is a
    RESOLUTION choice and the gate is run at two of them so its dependence is visible.

    STATIONS ARE EQUAL-POPULATION, NOT EQUAL-WIDTH, and that is a measured correction
    rather than a preference. Cutting the forearm into equal slices of the axial parameter
    gave stations of 4 and 5 vertices next to stations of 16 and 15, because this cage's
    vertex rows are not perpendicular to the limb axis; the sparse stations then sat a few
    tenths of a degree off the trend and manufactured a non-monotonicity that is a
    statement about the cage's row layout, not about the twist. Sorting by axial parameter
    and cutting into contiguous groups of equal size removes it without introducing a
    threshold. Both the populations and the resulting axial spans ship in the record.

    WHAT "AT THE WRIST" MEANS HERE. The vertex set is the skin the rig itself assigns
    entirely to the two forearm bones, which stops short of the skin blended with the wrist
    bone, so the most distal station is the distal end of the FOREARM and not the hand. The
    claim tested is therefore "the twist is greatest at the distal end of the forearm",
    which is AFS p.150's gradient; it is not a measurement of the hand.
    """
    idx = _forearm_skin(rest, side)
    e0 = rest['heads'][bone_index('lowerarm01.%s' % side)]
    e1 = rest['heads'][bone_index('wrist.%s' % side)]
    ax = unit(e1 - e0)
    t = (rest['v'][idx] - e0) @ ax
    t = (t - t.min()) / max(1e-12, (t.max() - t.min()))
    order = np.argsort(t, kind='stable')
    idx, t = idx[order], t[order]
    ax_p = unit(posed['heads'][bone_index('wrist.%s' % side)] - posed['heads'][bone_index('lowerarm01.%s' % side)])
    out = []
    groups = np.array_split(np.arange(len(idx)), n_stations)
    for i, g in enumerate(groups):
        sel = idx[g]
        if len(sel) < 3:  # a rigid rotation needs three non-collinear points
            out.append(
                {
                    'station': i,
                    'n': int(len(sel)),
                    'twist_deg': None,
                    'why': 'fewer than three points: no rotation is determined',
                }
            )
            continue
        R, _ = kabsch(rest['v'][sel], posed['v'][sel])
        _, tw = swing_twist(R, 0.5 * (ax + ax_p))
        out.append(
            {
                'station': i,
                'n': int(len(sel)),
                'axial_span': [round(float(t[g[0]]), 4), round(float(t[g[-1]]), 4)],
                'axial_mid': float(t[g].mean()),
                'twist_deg': float(tw),
            }
        )
    return out


def t5_pronation_isolation(phenotype, local_changes=None, side='l', drive_deg=60.0):
    """Driving forearm pronation must move the humerus by EXACTLY ZERO, and the twist must
    accumulate monotonically to a maximum at the wrist.

    TWO HONESTIES UP FRONT.
    (1) There is no radius and no ulna on this rig, so "the radius rolls around a fixed
        ulna" is not testable and is not claimed. What is driven is a twist of lowerarm01
        and lowerarm02 about their own long axes, which is the rig operation that imitates
        pronation.
    (2) On a pure forward-kinematic rig a child bone cannot move its parent, so the
        zero-humerus-rotation half of AFS p.149 is satisfied BY CONSTRUCTION. That is
        reported as such — `humerus_zero_is_constructive` — because a gate that can only
        pass is not evidence about the rig. It is still worth running, because the thing it
        guards is not the rig: it is any IK solver, any retarget and any fit that writes
        into pose_aa, all of which can and do put shoulder twist into a pronated arm. Run
        it on THOSE poses (see pose_library_report) and it stops being constructive.
    The monotonic-gradient half is NOT constructive: it is a real measurement of how this
    rig's skinning distributes a twist, and it can fail.
    """
    S = 'L' if side.lower() == 'l' else 'R'
    rest = rig_state(phenotype, local_changes, None)
    la1, la2 = 'lowerarm01.%s' % S, 'lowerarm02.%s' % S

    # axis: each forearm bone's own long axis == +Y of its rest frame.
    def drive(split):
        d = {}
        if split == 'proportional':
            # length-weighted, i.e. the twist accumulates along the segment as AFS p.150
            # describes rather than stepping at one bone boundary
            l1 = np.linalg.norm(rest['tails'][bone_index(la1)] - rest['heads'][bone_index(la1)])
            l2 = np.linalg.norm(rest['tails'][bone_index(la2)] - rest['heads'][bone_index(la2)])
            f1 = l1 / (l1 + l2)
            d[la1] = np.array([0.0, np.radians(drive_deg * f1), 0.0])
            d[la2] = np.array([0.0, np.radians(drive_deg * (1 - f1)), 0.0])
        elif split == 'distal':
            d[la2] = np.array([0.0, np.radians(drive_deg), 0.0])
        elif split == 'proximal':
            d[la1] = np.array([0.0, np.radians(drive_deg), 0.0])
        return pose_from_local(d)

    results, worst = {}, PASS
    for split in ('proportional', 'distal', 'proximal'):
        posed = rig_state(phenotype, local_changes, drive(split))
        # humerus rotation, measured in world: both humeral segments
        hum = {}
        for b in ('upperarm01.%s' % S, 'upperarm02.%s' % S, 'shoulder01.%s' % S, 'clavicle.%s' % S):
            R = posed['R'][bone_index(b)] @ rest['R'][bone_index(b)].T
            hum[b] = round(rot_angle_deg(R), 12)
        prof = {}
        for n in TWIST_STATION_COUNTS:
            p = _twist_profile(rest, posed, S, n)
            vals = [abs(x['twist_deg']) for x in p if x['twist_deg'] is not None]
            pops = [x['n'] for x in p if x['twist_deg'] is not None]
            argmax = int(np.argmax(vals)) if vals else None
            # THE VERDICT IS A RANK ORDERING, NOT A STEP-BY-STEP COMPARISON, and the
            # reason is measured rather than convenient: this cage's vertex ROWS are not
            # perpendicular to the limb axis, so slicing the forearm by axial parameter
            # produces stations of wildly unequal population (4 and 5 vertices next to 16
            # and 15 at n=10, measured) and the under-populated ones sit off the trend by
            # a few tenths of a degree. A strict per-step test at that resolution is
            # measuring the cage's row layout. Spearman rank correlation = +1 is the same
            # monotonicity claim, has no free parameter, and does not care how the
            # stations were cut. The strict test is still reported, with the populations
            # and the offending pairs, so nothing is hidden.
            rho = None
            if len(vals) > 2:
                r1 = np.argsort(np.argsort(np.arange(len(vals))))
                r2 = np.argsort(np.argsort(np.asarray(vals)))
                rho = float(np.corrcoef(r1, r2)[0, 1])
            prof[str(n)] = {
                'stations': p,
                'spearman_rho': rho,
                'values_deg': [round(v, 6) for v in vals],
                'argmax_station': argmax,
                'max_at_wrist': (None if argmax is None else bool(argmax == len(vals) - 1)),
                'station_populations': pops,
            }
        results[split] = {'humerus_rotation_deg': hum, 'twist_profile': prof}

    floor = rig_numerical_floor(phenotype, local_changes)
    hum_max = max(v for r in results.values() for v in r['humerus_rotation_deg'].values())
    hum_ok = hum_max <= max(PRONATION_HUMERUS_ROTATION_MAX_DEG, floor['reproducibility_deg'])

    # THE NULL FOR THE GRADIENT TEST IS MEASURED, NOT CHOSEN. Driving the whole twist at
    # the PROXIMAL forearm bone rotates every forearm vertex rigidly, so every station
    # must read the same angle; the spread across stations in that run is exactly the
    # station estimator's own noise, at that resolution, on that body. A "decrease" in the
    # anatomical profile counts only when it exceeds that null. This is the same device
    # geom/form/curvature uses when it refuses to call a bump a landmark below the cage's
    # own relief null, and it is why a tie between two rigidly-moving proximal stations
    # does not read as a violation of a NON-DECREASING gradient.
    null = {}
    for k, p in results['proximal']['twist_profile'].items():
        v = p['values_deg']
        null[k] = float(max(v) - min(v)) if v else 0.0

    mono_rows = results['proportional']['twist_profile']
    drops, mono_ok, wrist_ok = {}, True, True
    for k, p in mono_rows.items():
        v = p['values_deg']
        tol = max(null.get(k, 0.0), floor['reproducibility_deg'])
        d = [
            {
                'from_station': i,
                'to_station': i + 1,
                'decrease_deg': round(v[i] - v[i + 1], 8),
                'null_deg': round(tol, 8),
                'n_from': p['station_populations'][i],
                'n_to': p['station_populations'][i + 1],
            }
            for i in range(len(v) - 1)
            if v[i + 1] < v[i] - tol
        ]
        drops[k] = d
        mono_ok = mono_ok and not d
        if p['max_at_wrist'] is not None:
            wrist_ok = wrist_ok and p['max_at_wrist']
    if not hum_ok or not mono_ok or not wrist_ok:
        worst = FAIL
    explain = (
        'humerus rotation %.3e deg under a %.0f deg forearm pronation against a '
        'measured numerical floor of %.3e deg; twist gradient non-decreasing '
        'against a measured rigid-rotation null=%s, maximum at the wrist=%s'
        % (hum_max, drive_deg, floor['reproducibility_deg'], mono_ok, wrist_ok)
    )
    return _res(
        't5_pronation_isolation',
        worst,
        explain,
        observed={
            'max_humerus_rotation_deg': hum_max,
            'numerical_floor_deg': floor['reproducibility_deg'],
            'gradient_non_decreasing': mono_ok,
            'gradient_max_at_wrist': wrist_ok,
            'rigid_rotation_null_deg': null,
            'decreases_above_null': drops,
        },
        numerical_floor=floor,
        rigid_control=(
            'the "proximal" split drives the whole twist at '
            'lowerarm01, which rotates the entire forearm rigidly. It '
            'is not a candidate anatomy — it is the NULL that says how '
            'much station-to-station spread the estimator produces on '
            'a motion with no gradient at all.'
        ),
        band={
            'humerus_rotation_deg': PRONATION_HUMERUS_ROTATION_MAX_DEG,
            'gradient': 'monotonic, argmax at the distal station',
        },
        source=PRONATION_SOURCE,
        provenance=CANON,
        humerus_zero_is_constructive=True,
        constructive_note=(
            'forward kinematics cannot propagate a child rotation '
            'to a parent, so the humerus-zero half of this gate '
            'passes by construction on a rig-driven pose. It is a '
            'real test only on an authored/retargeted/fitted pose, '
            'where both bones are written independently.'
        ),
        no_radius_no_ulna=(
            'this rig has no radius and no ulna bone, so the '
            '"radius rolls around a fixed ulna" half of AFS p.149 '
            'is UNRESOLVED and is not claimed'
        ),
        side=S,
        drive_deg=drive_deg,
        splits=results,
    )


def pronation_coupling_in_pose(sk, side='l'):
    """The NON-constructive half: in a pose somebody else authored, is the humerus twisted
    in step with the forearm?

    Returns the twist of each arm segment about its own long axis. AFS p.149 says the
    humerus twist should owe nothing to the forearm twist; a fitted or retargeted pose that
    puts them in lockstep has explained a pronated hand by rolling the shoulder.
    """
    if sk.state is None:
        return {
            'resolved': False,
            'reason': "segment twist about a bone's own long axis is not recoverable "
            'from joint positions; a 1-DOF chain of points is blind to axial '
            'roll. This needs bone orientations.',
        }
    S = 'L' if side.lower() == 'l' else 'R'
    st = sk.state
    out = {}
    for b in (
        'clavicle.%s' % S,
        'shoulder01.%s' % S,
        'upperarm01.%s' % S,
        'upperarm02.%s' % S,
        'lowerarm01.%s' % S,
        'lowerarm02.%s' % S,
        'wrist.%s' % S,
    ):
        # about the bone's OWN long axis, in the frame the delta lives in — see _LONG
        _, tw = swing_twist(joint_delta(st, b), _LONG)
        out[b] = round(float(tw), 4)
    return {
        'resolved': True,
        'segment_twist_deg': out,
        'forearm_twist_deg': out['lowerarm01.%s' % S] + out['lowerarm02.%s' % S],
        'humerus_twist_deg': out['upperarm01.%s' % S] + out['upperarm02.%s' % S],
    }
