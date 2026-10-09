# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""FALSIFICATION — the broken-body demos and the negative controls.

Moved verbatim out of the old single-file pose_limits.py (lines 4599-5210). The nine
numbered controls demo_broken() used to inline moved to falsification_controls.py on
2026-10-09 (the no-function-over-300-lines rule); what stays here is the orchestrator
that runs them in order and the opposition-constant controls, which mutate this module's
own globals and must therefore live in the module whose globals they mutate.
"""

from zyg_workflows.geom.pose_limits.base import (
    ERROR,
    FAIL,
    PASS,
    SCHEMA,
    np,
)
from zyg_workflows.geom.pose_limits.printed import (
    TILT_OPPOSITION_REQUIRED_FRACTION,
    opposition_verdict,
)
from zyg_workflows.geom.pose_limits.rig import anatomical_frame, rig_state
from zyg_workflows.geom.pose_limits.skeleton import METRIC3D, Skeleton
from zyg_workflows.geom.pose_limits.stiffness import t5_pose_stiffness
from zyg_workflows.geom.pose_limits.characters import NEUTRAL
from zyg_workflows.geom.pose_limits import falsification_controls as FC


# ---------------------------------------------------------------------------------
# FALSIFICATION. A gate that has never failed anything is not calibrated. Every gate in
# this file is shown to fail a deliberately broken control, following the pattern
# geom.form.blockout.demo_level1_error already sets.
# ---------------------------------------------------------------------------------
def demo_broken(phenotype=None, local_changes=None):
    """Run every negative control of the pose-limits stack and report how each behaved.

    Each control in falsification_controls builds a deliberately broken (or deliberately
    sound, for the two positive controls) input and records what the gate said about it.
    The order below is the order the controls were written in and is part of the record:
    1 wrist overdrive, 2 cervical overdrive, 3 the clone pose set, 4 lockstep pronation,
    5/5b the elbow-owner controls, 6 the same-bone invariance positive control, 7 the
    incoming BlazePose path, 8 the shipped pose libraries, 9 the incomplete library and
    10 the opposition-constant mutation. Two controls append nothing when the rig does
    not carry the geometry they need, which is why their helpers may return None.

    Returns {schema, controls, all_controls_behaved}; `all_controls_behaved` ignores the
    rows that reported no verdict (`ok` None) and is False as soon as one control did not
    behave as its `must_be` says it must.
    """
    ph = dict(phenotype or NEUTRAL)
    rest = rig_state(ph, local_changes, None)
    af = anatomical_frame(rest)
    out = []
    out.extend(FC.rom_overdrive_controls(ph, local_changes, rest, af))
    out.append(FC.clone_pose_set_control(ph, local_changes))
    out.append(FC.lockstep_pronation_control(ph, local_changes))
    out.extend(FC.elbow_owner_controls(ph, local_changes, rest))
    same_bone = FC.same_bone_invariance_control(ph, local_changes, rest)
    if same_bone is not None:
        out.append(same_bone)
    out.append(FC.incoming_blazepose_control(ph, local_changes))
    out.extend(FC.pose_library_controls(ph, local_changes))
    out.append(FC.incomplete_library_control(ph, local_changes))
    # 10. THE CONSTANT MUST DECIDE. This replaces a control that could not see the defect
    #     it was named for: the old clause compared the band's
    #     `tilt_opposition_required_fraction` against TILT_OPPOSITION_REQUIRED_FRACTION —
    #     i.e. the label against the thing that wrote the label — so with the constant set
    #     to 0.0 it reported OK while the gate went on FAILING abel at a measured
    #     opposition of 0.5000 (NEW-1). This one MUTATES THE CONSTANT and requires the
    #     VERDICT to move, on a set whose opposition fraction is known by construction:
    #     eight poses, four opposed and four same-sign, so the answer must be pass at a
    #     required fraction of 0.0 and 0.5 and fail at 0.625 and 1.0. Put
    #     `n_same_sign == 0` back in place of the constant and every row below reads fail.
    out.extend(_opposition_constant_controls())

    return {
        'schema': SCHEMA,
        'controls': out,
        'all_controls_behaved': all(c.get('ok') for c in out if c.get('ok') is not None),
    }


def _tilt_control_pose(sh_deg, hp_deg, i):
    """A skeleton whose transverse tilts are EXACTLY sh_deg and hp_deg.

    Shoulders and hips sit symmetrically about their own midpoints, and those midpoints
    are on the +z axis, so _trunk_tilts() recovers the requested angles to machine
    precision. Nothing here claims to be a rig pose: the subject of the control is the
    ARITHMETIC of AFS p.16's second conjunct, and a synthetic set is what makes the
    opposition fraction a known quantity instead of a measured one.
    """
    a, b = np.radians(float(sh_deg)), np.radians(float(hp_deg))
    mid_sh, mid_hp = np.array([0.0, 0.0, 1.40]), np.array([0.0, 0.0, 0.90])
    dsh = 0.20 * np.array([np.cos(a), 0.0, np.sin(a)])
    dhp = 0.15 * np.array([np.cos(b), 0.0, np.sin(b)])
    return Skeleton(
        'opposition-control-%d' % i,
        METRIC3D,
        {'shoulder_l': mid_sh + dsh, 'shoulder_r': mid_sh - dsh, 'hip_l': mid_hp + dhp, 'hip_r': mid_hp - dhp},
    )


# (shoulder_tilt_deg, hip_tilt_deg) — four OPPOSED pairs then four SAME-SIGN pairs, all
# well clear of TILT_SIGN_ZERO_FLOOR_DEG and spread widely enough that both girdle
# standard deviations clear the printed 2 deg floor, so the FIRST conjunct passes and the
# second one is the only thing that can move the verdict.
_OPPOSITION_CONTROL_POSES = (
    (5.0, -7.0),
    (-6.0, 8.0),
    (9.0, -11.0),
    (-10.0, 12.0),
    (7.0, 5.0),
    (-8.0, -6.0),
    (11.0, 9.0),
    (-12.0, -10.0),
)
# required fraction -> the verdict FOUR-OPPOSED-OF-EIGHT must earn under it. Written out
# rather than derived, because a control that derives its expectation from the code it is
# testing is the tautology this control exists to replace.
_OPPOSITION_CONTROL_EXPECT = ((0.0, PASS, 8), (0.5, PASS, 4), (0.625, FAIL, 3), (1.0, FAIL, 0))


def _opposition_constant_controls():
    """Mutate TILT_OPPOSITION_REQUIRED_FRACTION; require the enforced verdict to follow.

    Two controls:

      (a) THE CONSTANT DECIDES. Four values of the constant across the measured 0.5
          opposition of a constructed eight-pose set. The scored `tilt_sign_opposition`
          status, the conjunction `afs_p16_both_conjuncts_ok` and the published
          `tilt_n_same_sign_allowed` must all move with it. If the enforcement stops
          reading the constant — for instance by going back to `n_same_sign == 0` — every
          row reads fail and this control fails.

      (b) THE GUARD FIRES. `opposition_verdict` is temporarily replaced by exactly the old
          rule (`n_same_sign == 0`) while the constant says 0.5. The gate must return
          ERROR naming the divergence, not a verdict. This is the alarm the sd floor has
          had one tier up since wave 3 and this conjunct did not, and it is the reason the
          NEW-1 divergence would not have been caught by anything at run time.

    The module global is restored in a finally block; a control that leaves the constant
    moved would corrupt every later measurement in the same process.
    """
    rows = []
    sks = [_tilt_control_pose(sh, hp, i) for i, (sh, hp) in enumerate(_OPPOSITION_CONTROL_POSES)]
    up = np.array([0.0, 0.0, 1.0])
    g = globals()
    original = TILT_OPPOSITION_REQUIRED_FRACTION
    original_fn = opposition_verdict
    seen = []
    try:
        for frac, want_status, want_allowed in _OPPOSITION_CONTROL_EXPECT:
            g['TILT_OPPOSITION_REQUIRED_FRACTION'] = frac
            # the mirror moves with it, or the drift guard would (correctly) refuse the
            # whole gate on the CANON mismatch and hide the thing being measured here
            g['TILT_OPPOSITION_CANON_FRACTION'] = frac
            r = t5_pose_stiffness(sks, world_up=up)
            row = next(
                (x for x in (r.get('detail') or {}).get('scored') or [] if x['check'] == 'tilt_sign_opposition'), {}
            )
            seen.append(
                {
                    'required_fraction': frac,
                    'tilt_sign_opposition': row.get('status'),
                    'n_same_sign_allowed': row.get('n_same_sign_allowed'),
                    'band_n_same_sign_allowed': (r.get('band') or {}).get('tilt_n_same_sign_allowed'),
                    'afs_p16_both_conjuncts_ok': (r.get('observed') or {}).get('afs_p16_both_conjuncts_ok'),
                    'gate_status': r['status'],
                    'must_be': want_status,
                    'must_allow': want_allowed,
                }
            )
    finally:
        g['TILT_OPPOSITION_REQUIRED_FRACTION'] = original
        g['TILT_OPPOSITION_CANON_FRACTION'] = original
    ok_a = bool(
        len(seen) == len(_OPPOSITION_CONTROL_EXPECT)
        and all(
            x['tilt_sign_opposition'] == x['must_be']
            and x['n_same_sign_allowed'] == x['must_allow']
            and x['band_n_same_sign_allowed'] == x['must_allow']
            and x['afs_p16_both_conjuncts_ok'] is (x['must_be'] == PASS)
            and (x['gate_status'] == FAIL) is (x['must_be'] == FAIL)
            for x in seen
        )
        # and the verdict really did MOVE: a control that passes because every
        # row agrees would be blind to a constant nobody reads
        and len({x['tilt_sign_opposition'] for x in seen}) == 2
    )
    rows.append(
        {
            'control': 'TILT_OPPOSITION_REQUIRED_FRACTION mutated across the constructed 0.5 '
            'opposition of an eight-pose set (4 opposed, 4 same-sign)',
            'gate': 't5_pose_stiffness / AFS p.16 second conjunct',
            'must_be': 'the enforced verdict FOLLOWS the declared constant: pass at 0.0 and '
            '0.5, fail at 0.625 and 1.0, with the allowed same-sign count on the '
            'band moving 8 / 4 / 3 / 0',
            'observed': seen,
            'ok': ok_a,
        }
    )

    # (b) the guard
    def _old_rule(n_opposed, n_evaluated):
        """Verbatim the rule this gate enforced before 2026-08-06: no same-sign pose."""
        if not n_evaluated:
            return None
        return bool(int(n_evaluated) - int(n_opposed) == 0)

    try:
        g['TILT_OPPOSITION_REQUIRED_FRACTION'] = 0.5
        g['TILT_OPPOSITION_CANON_FRACTION'] = 0.5
        g['opposition_verdict'] = _old_rule
        r = t5_pose_stiffness(sks, world_up=up)
    finally:
        g['opposition_verdict'] = original_fn
        g['TILT_OPPOSITION_REQUIRED_FRACTION'] = original
        g['TILT_OPPOSITION_CANON_FRACTION'] = original
    d = (r.get('detail') or {}).get('opposition_rule_drift') or {}
    checks = {x['check'] for x in d.get('divergences') or []}
    rows.append(
        {
            'control': 'the pre-2026-08-06 rule (n_same_sign == 0) put back while the declared constant says 0.5',
            'gate': 't5_pose_stiffness / opposition_rule_drift',
            'status': r['status'],
            'must_be': 'ERROR naming the divergence — never a verdict, and never the pass the '
            'relaxed rule would have handed back in silence',
            'observed': {'status': r['status'], 'divergence_checks': sorted(checks), 'explain': r['explain'][:220]},
            'ok': bool(r['status'] == ERROR and {'live', 'boundary'} <= checks),
        }
    )
    return rows
