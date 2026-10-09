# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Stage helpers for GATE 2 — t5_pose_stiffness.

Split out of stiffness.py (2026-10-09, the no-function-over-300-lines rule): the gate
entry point is now an orchestrator and every step it used to inline — the frame guard,
the per-pose measurement walk, the HOUSE window tables, AFS p.16's tilt arithmetic, the
drift refusal, the scored rows, the rollup and its prose, and the final record — lives
here as a named function with explicit parameters.

Import direction: this module imports the pose_limits siblings it needs (base, printed,
rig, skeleton, rom) and NEVER stiffness.py, so stiffness.py imports it at module level
without a cycle. `_trunk_tilts` and `_p175_error` moved here whole; stiffness.py
re-exports both by assignment so `pose_limits/__init__.py` keeps importing them from
stiffness, unchanged.
"""

from dataclasses import dataclass

from zyg_workflows.geom.pose_limits.base import (
    CANON,
    ERROR,
    FAIL,
    HOUSE,
    PASS,
    REPORT,
    UNMEASURABLE,
    UNRESOLVED,
    WARN,
    np,
    rollup,
)
from zyg_workflows.geom.pose_limits.printed import (
    ERECT_TRUNK_WINDOWS_DEG,
    STIFFNESS_SOURCE,
    STIFF_ELBOW_WINDOWS_DEG,
    STIFF_PARALLEL_WINDOWS_DEG,
    TILT_OPPOSITION_CANON_FRACTION,
    TILT_OPPOSITION_REQUIRED_FRACTION,
    TILT_SIGN_SENSITIVITY_FLOORS_DEG,
    TILT_SIGN_ZERO_FLOOR_DEG,
    TRANSVERSE_TILT_STDEV_MIN_DEG,
    max_same_sign_allowed,
    opposition_rule_drift,
    opposition_verdict,
)
from zyg_workflows.geom.pose_limits.rig import unit
from zyg_workflows.geom.pose_limits.skeleton import FRAME_NOTES, IMAGE2D
from zyg_workflows.geom.pose_limits.rom import _res, elbow_angle, knee_angle


@dataclass
class PoseSetMeasures:
    """The per-pose quantities the gate reads off a pose SET, in supply order.

    `elbows` and `knees` carry two entries per pose that has the joint (left then right);
    the other four carry at most one entry per pose, and a pose that cannot answer
    contributes nothing rather than a zero.
    """

    elbows: list
    knees: list
    forearm_par: list
    tilts: list
    trunk_inc: list
    finger_straight: list


@dataclass
class WindowFractions:
    """The three HOUSE window tables, each keyed by its window width in whole degrees."""

    elbow_locked: dict
    par: dict
    erect: dict


@dataclass
class TiltStats:
    """AFS p.16's two conjuncts as numbers, plus the sensitivity sweep beside them.

    `sd_ok` and `opposition_ok` are None when the set could not answer that conjunct;
    `both_conjuncts_ok` is their three-valued conjunction. `n_tilted` is how many poses
    carried both girdles at all, so `n_tilted - n_sign_eval` is the number whose sign was
    indeterminate.
    """

    sd_sh: float
    sd_hp: float
    sd_ok: bool
    opposition: float
    opposition_ok: bool
    n_tilted: int
    n_sign_eval: int
    n_opposed: int
    n_same_sign: int
    n_same_allowed: int
    same_sign_by_floor: dict
    both_conjuncts_ok: bool


def frame_guard(skeletons):
    """Refuse a set this gate cannot measure at all, else None.

    An empty set and a set whose EVERY pose is a 2D projection both come back as finished
    UNMEASURABLE records to hand straight to the caller. A set with at least one non-2D
    pose returns None and the gate goes on.
    """
    if not skeletons:
        return _res('t5_pose_stiffness', UNMEASURABLE, 'no poses supplied', source=STIFFNESS_SOURCE, provenance=CANON)
    if any(s.frame == IMAGE2D for s in skeletons):
        n2d = sum(1 for s in skeletons if s.frame == IMAGE2D)
        if n2d == len(skeletons):
            return _res(
                't5_pose_stiffness',
                UNMEASURABLE,
                'every supplied pose is a 2D projection',
                source=STIFFNESS_SOURCE,
                provenance=CANON,
                frame_note=FRAME_NOTES[IMAGE2D],
            )
    return None


def _trunk_tilts(sk):
    """Shoulder and hip transverse tilts about this pose's own trunk axis.

    Returns {trunk_axis, shoulder_tilt_deg, hip_tilt_deg}, or None when the pose is
    missing either girdle. The axis is the unit vector from the hip midpoint to the
    shoulder midpoint, so the tilts are measured in the body and not against the world.
    """
    if sk.missing('shoulder_l', 'shoulder_r', 'hip_l', 'hip_r'):
        return None
    mid_sh = 0.5 * (sk.p('shoulder_l') + sk.p('shoulder_r'))
    mid_hp = 0.5 * (sk.p('hip_l') + sk.p('hip_r'))
    up = unit(mid_sh - mid_hp)
    sh = unit(sk.p('shoulder_l') - sk.p('shoulder_r'))
    hp = unit(sk.p('hip_l') - sk.p('hip_r'))
    return {
        'trunk_axis': up,
        'shoulder_tilt_deg': float(np.degrees(np.arcsin(np.clip(sh @ up, -1, 1)))),
        'hip_tilt_deg': float(np.degrees(np.arcsin(np.clip(hp @ up, -1, 1)))),
    }


def measure_pose_set(skeletons, world_up):
    """Walk the poses once and collect every quantity the scored rows are built from.

    `world_up` may be None, in which case no trunk inclination is recorded and the ERECT
    share stays unmeasurable — the inclination is the only quantity that needs a world
    frame. Returns a PoseSetMeasures.
    """
    elbows, forearm_par, tilts, trunk_inc, knees, finger_straight = [], [], [], [], [], []
    for sk in skeletons:
        for side in ('l', 'r'):
            a = elbow_angle(sk, side)
            if a is not None:
                elbows.append(a)
            k = knee_angle(sk, side)
            if k is not None:
                knees.append(k)
        if not sk.missing('elbow_l', 'wrist_l', 'elbow_r', 'wrist_r'):
            fl = unit(sk.p('wrist_l') - sk.p('elbow_l'))
            fr = unit(sk.p('wrist_r') - sk.p('elbow_r'))
            # "parallel" for a mirrored pair means the axes are parallel in the body, so
            # the comparison is against BOTH senses; the smaller deviation is the answer.
            d = np.degrees(np.arccos(np.clip(abs(fl @ fr), -1, 1)))
            forearm_par.append(float(d))
        t = _trunk_tilts(sk)
        if t is not None:
            tilts.append((t['shoulder_tilt_deg'], t['hip_tilt_deg']))
            if world_up is not None:
                trunk_inc.append(float(np.degrees(np.arccos(np.clip(abs(t['trunk_axis'] @ unit(world_up)), -1, 1)))))
        if sk.state is not None:
            aa = sk.state['pose_aa']
            names = sk.state['names']
            fidx = [i for i, n in enumerate(names) if n.startswith('finger')]
            finger_straight.append(bool(np.all(np.linalg.norm(aa[fidx], axis=1) < 1e-6)))
    return PoseSetMeasures(
        elbows=elbows,
        knees=knees,
        forearm_par=forearm_par,
        tilts=tilts,
        trunk_inc=trunk_inc,
        finger_straight=finger_straight,
    )


def _frac_near(vals, targets, win):
    """Share of `vals` sitting within `win` of the nearest of `targets`; None if empty."""
    if not vals:
        return None
    return float(np.mean([min(abs(v - t) for t in targets) <= win for v in vals]))


def window_fractions(meas):
    """The three HOUSE window tables over an already-measured pose set.

    elbow_locked: the share of ARMS within each declared window of 90 or 180 degrees.
    par: the share of POSES whose two forearms sit within each declared window.
    erect: the share of poses whose trunk inclination is inside each declared window —
    None for every width unless both the inclinations and the knee angles were measured,
    which is the condition the page's ERECT split needs.
    """
    elbow_locked = {('%.0f' % w): _frac_near(meas.elbows, (90.0, 180.0), w) for w in STIFF_ELBOW_WINDOWS_DEG}
    par = {
        ('%.0f' % w): (float(np.mean([p <= w for p in meas.forearm_par])) if meas.forearm_par else None)
        for w in STIFF_PARALLEL_WINDOWS_DEG
    }
    erect = {}
    for w in ERECT_TRUNK_WINDOWS_DEG:
        if meas.trunk_inc and meas.knees:
            erect['%.0f' % w] = float(np.mean([t <= w for t in meas.trunk_inc]))
        else:
            erect['%.0f' % w] = None
    return WindowFractions(elbow_locked=elbow_locked, par=par, erect=erect)


def tilt_statistics(tilts):
    """Both conjuncts of AFS p.16, measured on the (shoulder, hip) tilt pairs.

    Fewer than two pairs leaves every verdict field None: a standard deviation needs two
    poses. A tilt below the numerical zero floor has no determined sign and is excluded
    from the opposition denominator rather than counted either way; how many poses that
    removes is published beside the answer. The sign-opposition verdict is
    opposition_verdict()'s, which reads the declared constant — nothing here re-derives
    it. Returns a TiltStats.
    """
    sh = np.array([t[0] for t in tilts]) if tilts else np.zeros(0)
    hp = np.array([t[1] for t in tilts]) if tilts else np.zeros(0)
    sd_ok = None
    opposition = None
    opposition_ok = None
    n_sign_eval = n_opposed = n_same_sign = 0
    same_sign_by_floor = {}
    if len(sh) >= 2:
        sd_sh = float(sh.std(ddof=1))
        sd_hp = float(hp.std(ddof=1))
        sd_ok = bool(sd_sh > TRANSVERSE_TILT_STDEV_MIN_DEG and sd_hp > TRANSVERSE_TILT_STDEV_MIN_DEG)
        # CONJUNCT 2 of the same printed sentence. A tilt below the numerical zero floor
        # has no determined sign and is excluded from the denominator rather than counted
        # either way; how many poses that removes is published beside the answer.
        nz = (np.abs(sh) > TILT_SIGN_ZERO_FLOOR_DEG) & (np.abs(hp) > TILT_SIGN_ZERO_FLOOR_DEG)
        n_sign_eval = int(nz.sum())
        if n_sign_eval:
            opp = np.sign(sh[nz]) != np.sign(hp[nz])
            n_opposed = int(opp.sum())
            n_same_sign = n_sign_eval - n_opposed
            opposition = float(n_opposed) / float(n_sign_eval)
            # THE DECLARED CONSTANT DECIDES THIS, and nothing else does. The predecessor
            # of this line read `bool(n_same_sign == 0)`, so the constant on the band was
            # decorative and the declared rule and the enforced rule were free to part
            # company without an alarm (NEW-1).
            opposition_ok = opposition_verdict(n_opposed, n_sign_eval)
        # SENSITIVITY, so that "your failure is numerical noise" is answerable with a
        # number instead of an opinion: how many poses still tilt the same way when both
        # tilts are required to exceed a HOUSE magnitude floor. Reported, never enforced.
        for f in TILT_SIGN_SENSITIVITY_FLOORS_DEG:
            m = (np.abs(sh) > f) & (np.abs(hp) > f)
            same = (np.sign(sh[m]) == np.sign(hp[m])).sum() if m.any() else 0
            same_sign_by_floor['%.1f' % f] = {'n_same_sign': int(same), 'n_evaluated': int(m.sum())}
    else:
        sd_sh = sd_hp = None
    return TiltStats(
        sd_sh=sd_sh,
        sd_hp=sd_hp,
        sd_ok=sd_ok,
        opposition=opposition,
        opposition_ok=opposition_ok,
        n_tilted=int(len(sh)),
        n_sign_eval=n_sign_eval,
        n_opposed=n_opposed,
        n_same_sign=n_same_sign,
        n_same_allowed=max_same_sign_allowed(n_sign_eval),
        same_sign_by_floor=same_sign_by_floor,
        both_conjuncts_ok=(None if (sd_ok is None or opposition_ok is None) else bool(sd_ok and opposition_ok)),
    )


def drift_refusal(n_poses, tilt):
    """THE DRIFT GUARD ON THE SECOND CONJUNCT, as a finished ERROR record or None.

    The first conjunct of this same printed sentence has had one a tier up since wave 3
    (geom/anthro/gates.py mirrors the sd floor and returns ERROR when the mirror and the
    module part company); the conjunct that actually decides abel and cornelis had none,
    so relaxing it would have returned both rows to PASS in silence (NEW-1). This runs on
    EVERY call, before a verdict exists, and it refuses rather than reporting a band that
    is not the band that was enforced.
    """
    drift = opposition_rule_drift(n_opposed=tilt.n_opposed, n_evaluated=tilt.n_sign_eval, enforced=tilt.opposition_ok)
    if drift is None:
        return None
    return _res(
        't5_pose_stiffness',
        ERROR,
        "the DECLARED and the ENFORCED form of AFS p.16's sign-opposition conjunct "
        'have diverged, so no verdict this gate could return would be about the band '
        'it prints: %s. Measured on this set: %s of %s poses with a determined sign '
        'oppose (fraction %s), enforced verdict %r, declared required fraction %r.'
        % (
            '; '.join('%s — %s' % (d['check'], d['why']) for d in drift['divergences']),
            tilt.n_opposed,
            tilt.n_sign_eval,
            'n/a' if tilt.opposition is None else '%.4f' % tilt.opposition,
            tilt.opposition_ok,
            TILT_OPPOSITION_REQUIRED_FRACTION,
        ),
        observed={
            'n_poses': n_poses,
            'shoulder_tilt_sd_deg': tilt.sd_sh,
            'hip_tilt_sd_deg': tilt.sd_hp,
            'afs_p16_both_conjuncts_ok': None,
            'tilt_opposition_fraction': tilt.opposition,
            'tilt_opposition_required_fraction': TILT_OPPOSITION_REQUIRED_FRACTION,
            'tilt_n_same_sign': tilt.n_same_sign,
            'tilt_n_sign_evaluated': tilt.n_sign_eval,
            'tilt_n_same_sign_allowed': tilt.n_same_allowed,
            'opposition_rule_drift': drift,
        },
        band={
            'transverse_tilt_sd_min_deg': TRANSVERSE_TILT_STDEV_MIN_DEG,
            'tilt_opposition_required_fraction': TILT_OPPOSITION_REQUIRED_FRACTION,
            'tilt_opposition_canon_fraction': TILT_OPPOSITION_CANON_FRACTION,
        },
        source=STIFFNESS_SOURCE,
        provenance=CANON,
        opposition_rule_drift=drift,
        remedy='geom/pose_limits.py: opposition_verdict() is the only place this '
        'conjunct may be decided and it must read '
        'TILT_OPPOSITION_REQUIRED_FRACTION; TILT_OPPOSITION_CANON_FRACTION is '
        'what AFS p.16 supports. Fix whichever of the two is wrong — do not '
        'delete this check.',
    )


def _p175_error(check, phrase, frac_by_window, windows, denominator, denominator_label):
    """Score one of AFS p.175's three named pose errors. HOUSE, WARN-capped, never blocks.

    The page names a CONFIGURATION and calls it an error. It prints no allowed share, so
    the only operationalisation with no invented number in it is presence/absence: a pose
    in that configuration is an instance of the named error, and one instance is one
    instance. What IS ours is the window that decides whether a pose is in the
    configuration, so the VERDICT is taken at the NARROWEST declared width — the strictest
    reading of "exactly" and of "parallel", i.e. the fewest poses this function is willing
    to call an error — and all three widths ship beside it so the reader can see that the
    answer does not hang on the choice.

    A window that produced no data returns UNMEASURABLE and says so. It never returns PASS:
    "we did not look" and "we looked and it was clean" are different sentences.
    """
    w = min(windows)
    frac = frac_by_window.get('%.0f' % w)
    if frac is None or denominator is None or denominator <= 0:
        st, n = UNMEASURABLE, None
    else:
        n = int(round(frac * denominator))
        st = WARN if frac > 0 else PASS
    return {
        'check': check,
        'page': 'AFS p.175',
        'named_error': phrase,
        'provenance': HOUSE,
        'can_block': False,
        'entered_verdict': True,
        'verdict_window_deg': w,
        'window_choice': 'narrowest of %s' % (list(windows),),
        'fraction': frac,
        'n': n,
        'denominator': denominator,
        'denominator_unit': denominator_label,
        'fraction_by_window_deg': frac_by_window,
        'status': st,
    }


def _tilt_rows(tilt):
    """The two AFS p.16 rows: the sd conjunct then the sign-opposition conjunct.

    Both are CANON and both can block. When the set carried fewer than two usable poses
    they are a pair of UNMEASURABLE rows that say so, which is a different sentence from
    a clean pass.
    """
    if tilt.sd_ok is None:
        return [
            {
                'check': 'transverse_tilt_sd',
                'page': 'AFS p.16',
                'provenance': CANON,
                'can_block': True,
                'entered_verdict': True,
                'status': UNMEASURABLE,
                'floor_deg': TRANSVERSE_TILT_STDEV_MIN_DEG,
                'why': 'fewer than two poses carry both shoulders and hips',
            },
            {
                'check': 'tilt_sign_opposition',
                'page': 'AFS p.16',
                'provenance': CANON,
                'can_block': True,
                'entered_verdict': True,
                'status': UNMEASURABLE,
                'why': 'fewer than two poses carry both shoulders and hips',
            },
        ]
    return [
        {
            'check': 'transverse_tilt_sd',
            'page': 'AFS p.16',
            'provenance': CANON,
            'can_block': True,
            'entered_verdict': True,
            'status': PASS if tilt.sd_ok else FAIL,
            'floor_deg': TRANSVERSE_TILT_STDEV_MIN_DEG,
            'shoulder_tilt_sd_deg': tilt.sd_sh,
            'hip_tilt_sd_deg': tilt.sd_hp,
        },
        {
            'check': 'tilt_sign_opposition',
            'page': 'AFS p.16',
            'provenance': CANON,
            'can_block': True,
            'entered_verdict': True,
            'status': (UNMEASURABLE if tilt.opposition_ok is None else PASS if tilt.opposition_ok else FAIL),
            'required_fraction': TILT_OPPOSITION_REQUIRED_FRACTION,
            'canon_fraction': TILT_OPPOSITION_CANON_FRACTION,
            'printed_tolerance': None,
            # what the CONSTANT allows on THIS denominator. The status above is
            # opposition_verdict()'s answer and this is the same rule stated as
            # a count, so a reader can check the verdict against the band
            # without re-deriving anything (NEW-1).
            'n_same_sign_allowed': tilt.n_same_allowed,
            'rule_drift': None,
            'fraction': tilt.opposition,
            'n_opposed': tilt.n_opposed,
            'n_same_sign': tilt.n_same_sign,
            'n_evaluated': tilt.n_sign_eval,
            'n_sign_indeterminate': int(tilt.n_tilted - tilt.n_sign_eval),
            'zero_floor_deg': TILT_SIGN_ZERO_FLOOR_DEG,
            'same_sign_by_tilt_floor_deg': tilt.same_sign_by_floor,
            'why': (
                None
                if tilt.opposition_ok is not None
                else 'no pose carries a tilt above the numerical zero floor at both girdles, so no sign is determined'
            ),
        },
    ]


def scored_rows(tilt, wins, meas):
    """EVERY conjunct this gate registers, scored, in rollup order.

    Nothing in the list is computed and then left unread: `entered_verdict` says so per
    row and the rollup consumes them all. The order is the two CANON p.16 rows, then
    p.175's forearms-parallel, elbows-locked and straight-finger-chains rows. The third
    p.175 error has NO window: "fully extended" is every finger rotation exactly zero,
    which is a boolean the pose file answers on its own.
    """
    scored = _tilt_rows(tilt)
    scored.append(
        _p175_error(
            'forearms_parallel',
            'left and right forearms parallel',
            wins.par,
            STIFF_PARALLEL_WINDOWS_DEG,
            len(meas.forearm_par),
            'poses',
        )
    )
    scored.append(
        _p175_error(
            'elbows_locked',
            'elbows locked at exactly 90 or 180 degrees',
            wins.elbow_locked,
            STIFF_ELBOW_WINDOWS_DEG,
            len(meas.elbows),
            'arms',
        )
    )
    finger_frac = float(np.mean(meas.finger_straight)) if meas.finger_straight else None
    scored.append(
        {
            'check': 'straight_finger_chains',
            'page': 'AFS p.175',
            'named_error': 'fully extended finger chains in a relaxed hand',
            'provenance': HOUSE,
            'can_block': False,
            'entered_verdict': True,
            'verdict_window_deg': None,
            'window_choice': 'none: "fully extended" is an exact zero, not a window',
            'fraction': finger_frac,
            'n': (None if finger_frac is None else int(round(finger_frac * len(meas.finger_straight)))),
            'denominator': len(meas.finger_straight),
            'denominator_unit': 'poses',
            'status': (UNMEASURABLE if finger_frac is None else WARN if finger_frac > 0 else PASS),
            'why': (
                None
                if meas.finger_straight
                else 'no supplied pose carries the joint-rotation state a finger chain would be read from'
            ),
        }
    )
    return scored


def _contrib(row):
    """A row's contribution to the rollup, with every HOUSE row capped at WARN.

    None of p.175's three can block, and a HOUSE row that could not be computed must not
    read as clean either, so it is carried at WARN rather than dropped or promoted to a
    non-verdict on the CANON claim.
    """
    if row['provenance'] == CANON:
        return row['status']
    return WARN if row['status'] in (WARN, UNMEASURABLE, UNRESOLVED, FAIL) else PASS


def _explain_text(canon_rows, house_rows, tilt):
    """The gate's sentence: the p.16 verdict with its numbers, then the p.175 tally.

    THE SENTENCE IS GENERATED FROM THE CONSTANT. It used to say "printed rule allows
    none" whatever TILT_OPPOSITION_REQUIRED_FRACTION was set to, which is the prose half
    of the same divergence (NEW-1): declared 0.0, printed "allows none".
    """
    failed = [r['check'] for r in canon_rows if r['status'] == FAIL]
    unmeas = [r['check'] for r in canon_rows if r['status'] == UNMEASURABLE]
    warned = [r['check'] for r in house_rows if _contrib(r) != PASS]
    sd_txt = 'shoulder/hip tilt sd %.2f/%.2f deg vs the printed %.1f deg floor' % (
        tilt.sd_sh,
        tilt.sd_hp,
        TRANSVERSE_TILT_STDEV_MIN_DEG,
    )
    allow_txt = (
        'allows none'
        if tilt.n_same_allowed == 0
        else 'has no denominator to allow anything of'
        if tilt.n_same_allowed is None
        else 'allows at most %d of %d' % (tilt.n_same_allowed, tilt.n_sign_eval)
    )
    if tilt.opposition_ok is None:
        opp_txt = 'sign opposition NOT determined on any pose'
    elif tilt.opposition_ok:
        opp_txt = (
            'shoulder and hip tilts oppose in %d of %d poses where both signs '
            'are determined (opposition fraction %.4f, at or above the required '
            '%.4f, which %s same-sign)'
            % (tilt.n_opposed, tilt.n_sign_eval, tilt.opposition, TILT_OPPOSITION_REQUIRED_FRACTION, allow_txt)
        )
    else:
        opp_txt = (
            'shoulder and hip tilt the SAME way in %d of %d poses (opposition '
            'fraction %.4f against a required %.4f, which %s; %s)'
            % (
                tilt.n_same_sign,
                tilt.n_sign_eval,
                tilt.opposition,
                TILT_OPPOSITION_REQUIRED_FRACTION,
                allow_txt,
                ', '.join(
                    '%d of %d still same-sign with both tilts over %s deg' % (v['n_same_sign'], v['n_evaluated'], k)
                    for k, v in sorted(tilt.same_sign_by_floor.items())
                ),
            )
        )
    p175_txt = '; '.join(
        '%s %s of %s %s'
        % (r['check'], 'unmeasurable' if r['n'] is None else r['n'], r['denominator'], r['denominator_unit'])
        for r in house_rows
    )
    verdict_txt = (
        'FAILS on ' + ', '.join(failed)
        if failed
        else 'is UNMEASURABLE on ' + ', '.join(unmeas)
        if unmeas
        else 'meets both'
    )
    return (
        'AFS p.16 has two conjuncts and this set %s: %s; %s. AFS p.175 errors '
        '(HOUSE windows, warn only, cannot block%s): %s.'
        % (verdict_txt, sd_txt, opp_txt, '' if not warned else ' — present: ' + ', '.join(warned), p175_txt)
    )


def verdict(scored, tilt):
    """Roll the scored rows up into (status, explain).

    A MEASURED breach of EITHER p.16 conjunct outranks a non-verdict on the other — the
    rule ROLLUP_RANK already states ("a breach that was measured is a fact"). Scoring the
    pair as a three-valued AND instead would send the eight-identical-poses control,
    whose shoulder-tilt sd is a measured 0.00 against a printed 2.0 floor, out as
    `unmeasurable` because a set of untilted poses determines no sign. That is how a real
    failure becomes a non-event, and demo_broken() catches it.
    """
    canon_rows = [r for r in scored if r['provenance'] == CANON]
    house_rows = [r for r in scored if r['provenance'] != CANON]
    if all(r['status'] == UNMEASURABLE for r in canon_rows):
        return REPORT, (
            'pose-set statistics measured; the transverse-tilt test needs at least '
            'two poses carrying shoulders and hips'
        )
    canon_contrib = rollup([r['status'] for r in canon_rows])
    if (tilt.both_conjuncts_ok is True) != (canon_contrib == PASS):  # unreachable by construction
        canon_contrib = ERROR
    status = rollup([canon_contrib] + [_contrib(r) for r in house_rows])
    return status, _explain_text(canon_rows, house_rows, tilt)


def build_result(n_poses, tilt, wins, meas, scored, status, explain):
    """Assemble the gate's record: observed, band, the scoring note and the raw series."""
    finger_frac = float(np.mean(meas.finger_straight)) if meas.finger_straight else None
    return _res(
        't5_pose_stiffness',
        status,
        explain,
        observed={
            'n_poses': n_poses,
            'shoulder_tilt_sd_deg': tilt.sd_sh,
            'hip_tilt_sd_deg': tilt.sd_hp,
            # BOTH halves of the printed sentence, as one answer. None means
            # one of them could not be computed and the row says which.
            'afs_p16_both_conjuncts_ok': tilt.both_conjuncts_ok,
            'tilt_opposition_fraction': tilt.opposition,
            'tilt_opposition_required_fraction': TILT_OPPOSITION_REQUIRED_FRACTION,
            'tilt_n_same_sign': tilt.n_same_sign,
            'tilt_n_sign_evaluated': tilt.n_sign_eval,
            # the required fraction expressed as the count it allows on THIS
            # denominator: the band and the verdict in the same units, so a
            # reader can see the constant doing the deciding (NEW-1).
            'tilt_n_same_sign_allowed': tilt.n_same_allowed,
            'tilt_opposition_rule_drift': None,
            'tilt_same_sign_by_floor_deg': tilt.same_sign_by_floor,
            'elbow_locked_fraction_by_window_deg': wins.elbow_locked,
            'forearms_parallel_fraction_by_window_deg': wins.par,
            'erect_fraction_by_trunk_window_deg': wins.erect,
            'fully_straight_finger_chain_fraction': finger_frac,
            'scored_check_status': {r['check']: r['status'] for r in scored},
        },
        band={
            'transverse_tilt_sd_min_deg': TRANSVERSE_TILT_STDEV_MIN_DEG,
            'tilt_opposition_required_fraction': TILT_OPPOSITION_REQUIRED_FRACTION,
            'tilt_opposition_canon_fraction': TILT_OPPOSITION_CANON_FRACTION,
            'tilt_n_same_sign_allowed': tilt.n_same_allowed,
            'p175_named_errors_at_narrowest_window': 0,
        },
        source=STIFFNESS_SOURCE,
        provenance=CANON,
        scored=scored,
        scoring_note=(
            'BOTH conjuncts of AFS p.16 are enforced and all three of '
            "AFS p.175's named errors are scored. Until 2026-08-06 the "
            'sign-opposition conjunct and the p.175 fractions were '
            'computed and never read, so a set violating half the quoted '
            'sentence rendered as a clean pass (R1). The p.16 conjuncts '
            'are CANON and block; the p.175 rows are HOUSE and are capped '
            'at warn; the p.19 ERECT share is reported and not scored '
            'because the page gives no target for it. The sign-opposition '
            'verdict is opposition_verdict(), which READS '
            'TILT_OPPOSITION_REQUIRED_FRACTION — for the first three days '
            'of the fix it did not, and the constant on this band was a '
            'label (NEW-1). opposition_rule_drift() re-checks that on '
            'every call and this gate returns ERROR, not a verdict, when '
            'the declared band and the enforced test disagree.'
        ),
        opposition_rule_drift=None,
        house_windows={
            'elbow_deg': list(STIFF_ELBOW_WINDOWS_DEG),
            'parallel_deg': list(STIFF_PARALLEL_WINDOWS_DEG),
            'erect_trunk_deg': list(ERECT_TRUNK_WINDOWS_DEG),
        },
        taxonomy_note=(
            "AFS p.19's five-configuration taxonomy is NOT reproduced: "
            'the category definitions are not in our possession and '
            'inventing them would fabricate a statistic. Only the '
            'ERECT / not-ERECT split is computed.'
        ),
        elbow_angles_deg=[round(e, 2) for e in meas.elbows[:200]],
        trunk_inclination_deg=([round(t, 2) for t in meas.trunk_inc[:200]] if meas.trunk_inc else None),
    )
