# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Unit tests for the stage helpers t5_pose_stiffness was split into (2026-10-09).

Every one of these behaviours used to be reachable only by calling the whole 453-line
gate; the helpers in `stiffness_measures` make each of them a one-call assertion. No GPU,
no network, no rig: every pose here is a hand-built Skeleton, which is also what makes the
AFS p.16 opposition fraction a KNOWN quantity instead of a measured one.
"""

import numpy as np
import pytest

from zyg_workflows.geom.pose_limits import printed as PRINTED
from zyg_workflows.geom.pose_limits import stiffness as ST
from zyg_workflows.geom.pose_limits import stiffness_measures as SM
from zyg_workflows.geom.pose_limits.base import CANON, ERROR, FAIL, HOUSE, PASS, REPORT, UNMEASURABLE, WARN
from zyg_workflows.geom.pose_limits.skeleton import IMAGE2D, METRIC3D, PSEUDO3D, Skeleton

UP = np.array([0.0, 0.0, 1.0])
MID_SH = np.array([0.0, 0.0, 1.40])
MID_HP = np.array([0.0, 0.0, 0.90])


def girdle_pose(sh_deg, hp_deg, name='p', frame=METRIC3D, limbs=False, state=None):
    """A pose whose transverse tilts are EXACTLY sh_deg and hp_deg, optionally with limbs.

    Both girdle midpoints sit on the +z axis, so the trunk axis is +z and the tilt of each
    girdle is the arcsin of its own z component — i.e. the angle that was asked for.
    """
    a, b = np.radians(float(sh_deg)), np.radians(float(hp_deg))
    dsh = 0.20 * np.array([np.cos(a), 0.0, np.sin(a)])
    dhp = 0.15 * np.array([np.cos(b), 0.0, np.sin(b)])
    j = {
        'shoulder_l': MID_SH + dsh,
        'shoulder_r': MID_SH - dsh,
        'hip_l': MID_HP + dhp,
        'hip_r': MID_HP - dhp,
    }
    if limbs:
        j['elbow_l'] = np.array([0.25, 0.0, 1.10])
        j['elbow_r'] = np.array([-0.25, 0.0, 1.10])
        j['wrist_l'] = np.array([0.25, 0.0, 0.85])
        j['wrist_r'] = np.array([-0.25, 0.0, 0.85])
        j['knee_l'] = np.array([0.15, 0.0, 0.45])
        j['knee_r'] = np.array([-0.15, 0.0, 0.45])
        j['ankle_l'] = np.array([0.15, 0.0, 0.05])
        j['ankle_r'] = np.array([-0.15, 0.0, 0.05])
    return Skeleton(name, frame, j, state=state)


def finger_state(straight):
    """A minimal rig state whose finger rotations are all zero (straight) or not."""
    names = ['spine01', 'finger2-1.L', 'finger3-1.L']
    aa = np.zeros((len(names), 3))
    if not straight:
        aa[1] = [0.4, 0.0, 0.0]
    return {'names': names, 'pose_aa': aa}


# ---- frame_guard -----------------------------------------------------------------


def test_frame_guard_refuses_an_empty_set_and_says_why():
    r = SM.frame_guard([])
    assert r['status'] == UNMEASURABLE
    assert r['explain'] == 'no poses supplied'
    assert r['provenance'] == CANON


def test_frame_guard_refuses_a_set_that_is_entirely_2d_and_carries_the_frame_note():
    r = SM.frame_guard([girdle_pose(5, -7, frame=IMAGE2D), girdle_pose(-6, 8, frame=IMAGE2D)])
    assert r['status'] == UNMEASURABLE
    assert r['explain'] == 'every supplied pose is a 2D projection'
    assert 'projection does not even bound it' in r['detail']['frame_note']


def test_frame_guard_lets_a_set_with_one_measurable_pose_through():
    assert SM.frame_guard([girdle_pose(5, -7, frame=IMAGE2D), girdle_pose(-6, 8)]) is None
    assert SM.frame_guard([girdle_pose(5, -7, frame=PSEUDO3D)]) is None


# ---- _trunk_tilts ----------------------------------------------------------------


def test_trunk_tilts_recovers_the_requested_angles_to_machine_precision():
    t = SM._trunk_tilts(girdle_pose(9.0, -11.0))
    assert t['shoulder_tilt_deg'] == pytest.approx(9.0, abs=1e-9)
    assert t['hip_tilt_deg'] == pytest.approx(-11.0, abs=1e-9)
    assert t['trunk_axis'] == pytest.approx(UP)


def test_trunk_tilts_is_none_when_either_girdle_is_absent():
    sk = Skeleton('half', METRIC3D, {'shoulder_l': MID_SH, 'shoulder_r': MID_SH})
    assert SM._trunk_tilts(sk) is None


# ---- measure_pose_set ------------------------------------------------------------


def test_measure_pose_set_records_two_limb_angles_per_pose_and_skips_what_is_absent():
    meas = SM.measure_pose_set([girdle_pose(5, -7, limbs=True), girdle_pose(-6, 8)], UP)
    assert len(meas.elbows) == 2  # only the posed-with-limbs skeleton answers, left+right
    assert len(meas.knees) == 2
    assert len(meas.forearm_par) == 1
    assert len(meas.tilts) == 2
    assert meas.finger_straight == []


def test_measure_pose_set_calls_mirrored_forearms_parallel_in_the_body():
    # the two forearms point in OPPOSITE world directions but are parallel in the body,
    # which is the comparison against BOTH senses the gate makes
    j = {
        'shoulder_l': MID_SH,
        'shoulder_r': MID_SH,
        'hip_l': MID_HP,
        'hip_r': MID_HP,
        'elbow_l': np.array([0.2, 0.0, 1.0]),
        'wrist_l': np.array([0.2, 0.0, 0.7]),
        'elbow_r': np.array([-0.2, 0.0, 0.7]),
        'wrist_r': np.array([-0.2, 0.0, 1.0]),
    }
    meas = SM.measure_pose_set([Skeleton('mirror', METRIC3D, j)], UP)
    assert meas.forearm_par == [pytest.approx(0.0, abs=1e-9)]


def test_measure_pose_set_needs_a_world_up_for_the_trunk_inclination():
    poses = [girdle_pose(5, -7, limbs=True)]
    assert SM.measure_pose_set(poses, UP).trunk_inc == [pytest.approx(0.0, abs=1e-9)]
    assert SM.measure_pose_set(poses, None).trunk_inc == []


def test_measure_pose_set_reads_finger_chains_only_from_a_pose_that_carries_rig_state():
    meas = SM.measure_pose_set(
        [
            girdle_pose(5, -7, state=finger_state(True)),
            girdle_pose(-6, 8, state=finger_state(False)),
            girdle_pose(9, -11),
        ],
        UP,
    )
    assert meas.finger_straight == [True, False]


# ---- _frac_near and window_fractions ---------------------------------------------


def test_frac_near_is_none_on_no_data_and_inclusive_at_the_window_edge():
    assert SM._frac_near([], (90.0, 180.0), 5.0) is None
    # 84 is 6 deg off the nearest target and drops out; 90 and 175 are both within 5
    assert SM._frac_near([84.0, 90.0, 175.0], (90.0, 180.0), 5.0) == pytest.approx(2 / 3)
    assert SM._frac_near([95.0], (90.0, 180.0), 5.0) == 1.0  # exactly on the edge counts
    assert SM._frac_near([85.0, 185.0], (90.0, 180.0), 5.0) == 1.0  # both edges, both sides


def test_window_fractions_keys_every_declared_window_and_refuses_an_empty_denominator():
    meas = SM.measure_pose_set([girdle_pose(5, -7)], UP)  # girdles only: no limbs at all
    wins = SM.window_fractions(meas)
    assert sorted(wins.elbow_locked) == ['3', '5', '8']
    assert sorted(wins.par) == ['10', '15', '5']
    assert sorted(wins.erect) == ['10', '15', '20']
    assert set(wins.par.values()) == {None}
    assert set(wins.elbow_locked.values()) == {None}
    assert set(wins.erect.values()) == {None}


def test_window_fractions_leaves_the_erect_share_unmeasured_without_knee_angles():
    j = {
        'shoulder_l': MID_SH + np.array([0.2, 0.0, 0.0]),
        'shoulder_r': MID_SH - np.array([0.2, 0.0, 0.0]),
        'hip_l': MID_HP + np.array([0.15, 0.0, 0.0]),
        'hip_r': MID_HP - np.array([0.15, 0.0, 0.0]),
    }
    meas = SM.measure_pose_set([Skeleton('noknees', METRIC3D, j)], UP)
    assert meas.trunk_inc  # the inclination WAS measured
    assert set(SM.window_fractions(meas).erect.values()) == {None}


# ---- tilt_statistics -------------------------------------------------------------


def test_tilt_statistics_cannot_answer_either_conjunct_on_fewer_than_two_poses():
    for tilts in ([], [(5.0, -7.0)]):
        t = SM.tilt_statistics(tilts)
        assert t.sd_sh is None and t.sd_hp is None
        assert t.sd_ok is None and t.opposition_ok is None
        assert t.both_conjuncts_ok is None
        assert (t.n_sign_eval, t.n_opposed, t.n_same_sign) == (0, 0, 0)
        assert t.same_sign_by_floor == {}


def test_tilt_statistics_counts_the_constructed_four_of_eight_opposition():
    pairs = [
        (5.0, -7.0),
        (-6.0, 8.0),
        (9.0, -11.0),
        (-10.0, 12.0),
        (7.0, 5.0),
        (-8.0, -6.0),
        (11.0, 9.0),
        (-12.0, -10.0),
    ]
    t = SM.tilt_statistics(pairs)
    assert (t.n_tilted, t.n_sign_eval, t.n_opposed, t.n_same_sign) == (8, 8, 4, 4)
    assert t.opposition == 0.5
    assert t.sd_ok is True  # both girdle standard deviations clear the printed 2 deg floor
    assert t.opposition_ok is False  # the printed constant requires every pose to oppose
    assert t.both_conjuncts_ok is False
    assert t.n_same_allowed == 0


def test_tilt_statistics_passes_the_second_conjunct_when_every_pose_opposes():
    t = SM.tilt_statistics([(5.0, -7.0), (-6.0, 8.0), (9.0, -11.0), (-10.0, 12.0)])
    assert t.opposition == 1.0
    assert t.opposition_ok is True
    assert t.both_conjuncts_ok is True


def test_tilt_statistics_excludes_an_indeterminate_sign_from_the_denominator():
    # a tilt under the numerical zero floor has no sign, so it leaves the denominator
    t = SM.tilt_statistics([(5.0, -7.0), (-6.0, 8.0), (0.0, 4.0), (3.0, 0.0)])
    assert t.n_tilted == 4
    assert t.n_sign_eval == 2
    assert t.n_opposed == 2
    assert t.opposition == 1.0


def test_tilt_statistics_reports_a_sensitivity_sweep_it_never_enforces():
    t = SM.tilt_statistics([(0.5, 0.5), (3.0, 4.0), (-5.0, -6.0), (9.0, -11.0)])
    assert sorted(t.same_sign_by_floor) == ['1.0', '2.0']
    # the 0.5/0.5 pose drops out above the 1 deg floor; three same-sign poses remain
    assert t.same_sign_by_floor['1.0'] == {'n_same_sign': 2, 'n_evaluated': 3}
    assert t.same_sign_by_floor['2.0'] == {'n_same_sign': 2, 'n_evaluated': 3}


def test_tilt_statistics_fails_the_sd_conjunct_on_a_set_with_no_tilt_variety():
    t = SM.tilt_statistics([(0.0, 0.0)] * 8)
    assert (t.sd_sh, t.sd_hp) == (0.0, 0.0)
    assert t.sd_ok is False
    assert t.opposition_ok is None  # untilted poses determine no sign
    assert t.both_conjuncts_ok is None


# ---- drift_refusal ---------------------------------------------------------------


def test_drift_refusal_is_silent_while_the_declared_and_enforced_rules_agree():
    assert SM.drift_refusal(8, SM.tilt_statistics([(5.0, -7.0), (-6.0, 8.0)])) is None


def test_drift_refusal_errors_when_the_declared_constant_leaves_its_canon_mirror(monkeypatch):
    monkeypatch.setattr(PRINTED, 'TILT_OPPOSITION_REQUIRED_FRACTION', 0.5)
    monkeypatch.setattr(SM, 'TILT_OPPOSITION_REQUIRED_FRACTION', 0.5)
    r = SM.drift_refusal(2, SM.tilt_statistics([(5.0, -7.0), (-6.0, 8.0)]))
    assert r is not None
    assert r['status'] == ERROR
    assert 'have diverged' in r['explain']
    assert r['observed']['afs_p16_both_conjuncts_ok'] is None
    assert r['observed']['opposition_rule_drift']['divergences']
    assert r['detail']['remedy'].startswith('geom/pose_limits.py: opposition_verdict()')
    assert 'mirror' in {d['check'] for d in r['observed']['opposition_rule_drift']['divergences']}


# ---- _p175_error -----------------------------------------------------------------


def test_p175_error_takes_its_verdict_at_the_narrowest_declared_window():
    row = SM._p175_error('elbows_locked', 'locked', {'3': 0.0, '5': 0.5, '8': 1.0}, (3.0, 5.0, 8.0), 4, 'arms')
    assert row['verdict_window_deg'] == 3.0
    assert row['window_choice'] == 'narrowest of [3.0, 5.0, 8.0]'
    assert row['fraction'] == 0.0
    assert row['status'] == PASS
    assert row['provenance'] == HOUSE
    assert row['can_block'] is False


def test_p175_error_warns_on_a_single_instance_and_never_blocks():
    row = SM._p175_error('forearms_parallel', 'parallel', {'5': 0.25}, (5.0, 10.0), 8, 'poses')
    assert row['status'] == WARN
    assert row['n'] == 2
    assert row['denominator_unit'] == 'poses'


@pytest.mark.parametrize(
    ('frac_by_window', 'denominator'),
    [({'5': None}, 8), ({'5': 0.5}, 0), ({'5': 0.5}, None), ({}, 8)],
)
def test_p175_error_says_unmeasurable_rather_than_clean_when_it_did_not_look(frac_by_window, denominator):
    row = SM._p175_error('forearms_parallel', 'parallel', frac_by_window, (5.0, 10.0), denominator, 'poses')
    assert row['status'] == UNMEASURABLE
    assert row['n'] is None


# ---- scored_rows and the rollup --------------------------------------------------


def _rows(pairs, poses):
    meas = SM.measure_pose_set(poses, UP)
    return SM.scored_rows(SM.tilt_statistics(pairs), SM.window_fractions(meas), meas), meas


def test_scored_rows_keeps_the_five_checks_in_rollup_order():
    rows, _ = _rows([(5.0, -7.0), (-6.0, 8.0)], [girdle_pose(5, -7, limbs=True), girdle_pose(-6, 8, limbs=True)])
    assert [r['check'] for r in rows] == [
        'transverse_tilt_sd',
        'tilt_sign_opposition',
        'forearms_parallel',
        'elbows_locked',
        'straight_finger_chains',
    ]
    assert [r['provenance'] for r in rows] == [CANON, CANON, HOUSE, HOUSE, HOUSE]
    assert all(r['entered_verdict'] for r in rows)


def test_scored_rows_publishes_the_count_the_band_allows_beside_the_verdict():
    rows, _ = _rows([(5.0, -7.0), (-6.0, -8.0)], [girdle_pose(5, -7), girdle_pose(-6, -8)])
    opp = rows[1]
    assert opp['status'] == FAIL
    assert opp['n_evaluated'] == 2
    assert opp['n_same_sign'] == 1
    assert opp['n_same_sign_allowed'] == 0
    assert opp['required_fraction'] == PRINTED.TILT_OPPOSITION_REQUIRED_FRACTION
    assert opp['rule_drift'] is None


def test_scored_rows_pairs_two_unmeasurable_canon_rows_on_a_single_pose():
    rows, _ = _rows([(5.0, -7.0)], [girdle_pose(5, -7)])
    assert [r['status'] for r in rows[:2]] == [UNMEASURABLE, UNMEASURABLE]
    assert rows[0]['why'] == 'fewer than two poses carry both shoulders and hips'
    assert rows[1]['why'] == 'fewer than two poses carry both shoulders and hips'


def test_scored_rows_counts_the_indeterminate_signs_it_dropped():
    pairs = [(5.0, -7.0), (-6.0, 8.0), (0.0, 4.0)]
    rows, _ = _rows(pairs, [girdle_pose(*p) for p in pairs])
    assert rows[1]['n_sign_indeterminate'] == 1


def test_scored_rows_reads_the_third_p175_error_off_the_pose_state_with_no_window():
    poses = [girdle_pose(5, -7, state=finger_state(True)), girdle_pose(-6, 8, state=finger_state(False))]
    rows, _ = _rows([(5.0, -7.0), (-6.0, 8.0)], poses)
    finger = rows[-1]
    assert finger['verdict_window_deg'] is None
    assert finger['window_choice'] == 'none: "fully extended" is an exact zero, not a window'
    assert finger['fraction'] == 0.5
    assert finger['n'] == 1
    assert finger['status'] == WARN


def test_contrib_caps_a_house_row_at_warn_and_leaves_canon_alone():
    assert SM._contrib({'provenance': CANON, 'status': FAIL}) == FAIL
    assert SM._contrib({'provenance': HOUSE, 'status': FAIL}) == WARN
    assert SM._contrib({'provenance': HOUSE, 'status': UNMEASURABLE}) == WARN
    assert SM._contrib({'provenance': HOUSE, 'status': PASS}) == PASS


def test_verdict_reports_rather_than_passes_when_no_canon_row_has_a_verdict():
    rows, _ = _rows([(5.0, -7.0)], [girdle_pose(5, -7)])
    status, explain = SM.verdict(rows, SM.tilt_statistics([(5.0, -7.0)]))
    assert status == REPORT
    assert explain.startswith('pose-set statistics measured;')


def test_verdict_fails_on_the_second_conjunct_and_names_it_in_the_sentence():
    pairs = [(5.0, -7.0), (-6.0, -8.0), (9.0, -11.0), (-10.0, 12.0)]
    poses = [girdle_pose(*p, limbs=True) for p in pairs]
    rows, _ = _rows(pairs, poses)
    status, explain = SM.verdict(rows, SM.tilt_statistics(pairs))
    assert status == FAIL
    assert 'FAILS on tilt_sign_opposition' in explain
    assert 'tilt the SAME way in 1 of 4 poses' in explain
    assert 'which allows none' in explain
    assert 'AFS p.175 errors' in explain


def test_verdict_meets_both_conjuncts_when_every_pose_opposes_with_spread():
    pairs = [(5.0, -7.0), (-6.0, 8.0), (9.0, -11.0), (-10.0, 12.0)]
    rows, _ = _rows(pairs, [girdle_pose(*p) for p in pairs])
    status, explain = SM.verdict(rows, SM.tilt_statistics(pairs))
    assert 'meets both' in explain
    assert 'tilts oppose in 4 of 4 poses' in explain
    assert status in (PASS, WARN)  # the HOUSE rows are unmeasurable here, so warn-capped


def test_verdict_sentence_states_the_allowance_the_constant_implies(monkeypatch):
    monkeypatch.setattr(PRINTED, 'TILT_OPPOSITION_REQUIRED_FRACTION', 0.5)
    monkeypatch.setattr(SM, 'TILT_OPPOSITION_REQUIRED_FRACTION', 0.5)
    pairs = [(5.0, -7.0), (-6.0, -8.0), (9.0, -11.0), (-10.0, 12.0)]
    tilt = SM.tilt_statistics(pairs)
    assert tilt.n_same_allowed == 2
    rows, _ = _rows(pairs, [girdle_pose(*p) for p in pairs])
    _, explain = SM.verdict(rows, tilt)
    assert 'which allows at most 2 of 4' in explain


# ---- build_result ----------------------------------------------------------------


def test_build_result_publishes_every_field_the_report_writers_read():
    pairs = [(5.0, -7.0), (-6.0, 8.0)]
    poses = [girdle_pose(*p, limbs=True, state=finger_state(True)) for p in pairs]
    meas = SM.measure_pose_set(poses, UP)
    wins = SM.window_fractions(meas)
    tilt = SM.tilt_statistics(pairs)
    rows = SM.scored_rows(tilt, wins, meas)
    status, explain = SM.verdict(rows, tilt)
    r = SM.build_result(len(poses), tilt, wins, meas, rows, status, explain)
    assert r['gate'] == 't5_pose_stiffness'
    assert r['observed']['n_poses'] == 2
    assert r['observed']['afs_p16_both_conjuncts_ok'] is tilt.both_conjuncts_ok
    assert r['observed']['fully_straight_finger_chain_fraction'] == 1.0
    assert r['observed']['scored_check_status'] == {x['check']: x['status'] for x in rows}
    assert r['band']['transverse_tilt_sd_min_deg'] == PRINTED.TRANSVERSE_TILT_STDEV_MIN_DEG
    assert r['band']['tilt_n_same_sign_allowed'] == tilt.n_same_allowed
    assert r['detail']['opposition_rule_drift'] is None
    assert r['detail']['house_windows']['elbow_deg'] == list(PRINTED.STIFF_ELBOW_WINDOWS_DEG)
    assert len(r['detail']['elbow_angles_deg']) == 4
    assert r['detail']['trunk_inclination_deg'] == [0.0, 0.0]


def test_build_result_truncates_the_raw_series_at_two_hundred_entries():
    pairs = [(5.0 + 0.01 * i, -7.0 - 0.01 * i) for i in range(150)]
    poses = [girdle_pose(*p, limbs=True) for p in pairs]
    meas = SM.measure_pose_set(poses, UP)
    wins = SM.window_fractions(meas)
    tilt = SM.tilt_statistics(pairs)
    rows = SM.scored_rows(tilt, wins, meas)
    r = SM.build_result(len(poses), tilt, wins, meas, rows, *SM.verdict(rows, tilt))
    assert len(meas.elbows) == 300
    assert len(r['detail']['elbow_angles_deg']) == 200
    assert len(r['detail']['trunk_inclination_deg']) == 150


def test_build_result_says_none_rather_than_an_empty_list_for_an_unmeasured_series():
    pairs = [(5.0, -7.0), (-6.0, 8.0)]
    meas = SM.measure_pose_set([girdle_pose(*p) for p in pairs], None)
    wins = SM.window_fractions(meas)
    tilt = SM.tilt_statistics(pairs)
    rows = SM.scored_rows(tilt, wins, meas)
    r = SM.build_result(2, tilt, wins, meas, rows, *SM.verdict(rows, tilt))
    assert r['detail']['trunk_inclination_deg'] is None
    assert r['detail']['elbow_angles_deg'] == []


# ---- the orchestrator still is the sum of its stages -----------------------------


def test_the_gate_is_exactly_its_stages_run_in_order():
    pairs = [(5.0, -7.0), (-6.0, 8.0), (9.0, -11.0), (-10.0, 12.0), (7.0, 5.0), (-8.0, -6.0)]
    poses = [girdle_pose(*p, limbs=True, state=finger_state(i % 2 == 0)) for i, p in enumerate(pairs)]
    meas = SM.measure_pose_set(poses, UP)
    wins = SM.window_fractions(meas)
    tilt = SM.tilt_statistics(meas.tilts)
    rows = SM.scored_rows(tilt, wins, meas)
    expected = SM.build_result(len(poses), tilt, wins, meas, rows, *SM.verdict(rows, tilt))
    assert ST.t5_pose_stiffness(poses, world_up=UP) == expected


def test_the_gate_still_re_exports_the_two_helpers_the_package_imports_from_it():
    assert ST._trunk_tilts is SM._trunk_tilts
    assert ST._p175_error is SM._p175_error
