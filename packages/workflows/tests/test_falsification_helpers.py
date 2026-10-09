# SPDX-FileCopyrightText: 2026 Zygomatic
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Unit tests for the helpers demo_broken() was split into (2026-10-09).

demo_broken() itself cannot run in CI: its first statement calls rig_state(), which
imports torch, and torch is in no venv here. So what is tested is everything the split
made reachable WITHOUT the rig — the orchestrator's own contract (which controls run, in
what order, and how `all_controls_behaved` treats a control that reported no verdict),
the two `if row is not None` guards that used to be `if len(cand) >= 8:` and
`if tub is not None and mal is not None:` inside the old 453-line body, the
per-character error row of control 8, the error row of control 7, and the synthetic
pose arithmetic control 10 rests on. Each of those was a stretch of straight-line code
in the middle of one giant function before and had never been exercised in isolation.
"""

import numpy as np
import pytest

from zyg_workflows.geom.pose_limits import falsification as FL
from zyg_workflows.geom.pose_limits import falsification_controls as FC
from zyg_workflows.geom.pose_limits.base import PASS
from zyg_workflows.geom.pose_limits.stiffness import _trunk_tilts


# ---- control 10's synthetic poses: the arithmetic the mutation control rests on -----


def test_tilt_control_pose_recovers_the_requested_tilts_to_machine_precision():
    """_tilt_control_pose(sh, hp, i) must measure back as EXACTLY sh and hp degrees."""
    for sh, hp in ((5.0, -7.0), (-10.0, 12.0), (0.0, 0.0), (11.0, 9.0)):
        t = _trunk_tilts(FL._tilt_control_pose(sh, hp, 0))
        assert t is not None
        assert t['shoulder_tilt_deg'] == pytest.approx(sh, abs=1e-9)
        assert t['hip_tilt_deg'] == pytest.approx(hp, abs=1e-9)


def test_tilt_control_pose_names_itself_after_its_index_and_carries_only_the_girdles():
    sk = FL._tilt_control_pose(5.0, -7.0, 3)
    assert sk.source == 'opposition-control-3'
    assert set(sk.joints) == {'shoulder_l', 'shoulder_r', 'hip_l', 'hip_r'}


def test_the_opposition_control_set_really_is_four_opposed_and_four_same_sign():
    """The control's expectation table is only meaningful if the set is 0.5 opposed."""
    poses = FL._OPPOSITION_CONTROL_POSES
    assert len(poses) == 8
    opposed = [(sh, hp) for sh, hp in poses if sh * hp < 0.0]
    assert len(opposed) == 4
    # and every tilt is clear of the sign-zero floor, so no pose is indeterminate
    assert all(abs(sh) >= 5.0 and abs(hp) >= 3.0 for sh, hp in poses)


def test_the_expectation_table_demands_the_verdict_actually_move():
    """Written-out, not derived: two distinct verdicts and a monotone allowed count."""
    fracs = [f for f, _s, _a in FL._OPPOSITION_CONTROL_EXPECT]
    allowed = [a for _f, _s, a in FL._OPPOSITION_CONTROL_EXPECT]
    assert fracs == sorted(fracs)
    assert allowed == sorted(allowed, reverse=True)
    assert len({s for _f, s, _a in FL._OPPOSITION_CONTROL_EXPECT}) == 2


# ---- the two optional-row guards the old body expressed inline ----------------------


def test_same_bone_invariance_control_appends_nothing_when_a_region_is_absent(monkeypatch):
    """The old `if tub is not None and mal is not None:` guard, now a None return."""
    monkeypatch.setattr(FC, '_region_group', lambda name, side: (None, None))
    assert FC.same_bone_invariance_control({}, None, {}) is None

    def one_missing(name, side):
        return ([0, 1], None) if name == 'tibial_tuberosity' else (None, None)

    monkeypatch.setattr(FC, '_region_group', one_missing)
    assert FC.same_bone_invariance_control({}, None, {}) is None


def test_elbow_owner_controls_drops_the_patch_row_and_keeps_the_conditioned_rows(monkeypatch):
    """The old `ok5 = None; if len(cand) >= 8:` guard, now a None from the patch helper."""
    monkeypatch.setattr(FC, '_elbow_owner_conditioned_rows', lambda ph, lc: [{'control': 'a'}, {'control': 'b'}])

    monkeypatch.setattr(FC, '_humeral_patch_owner_row', lambda ph, lc, rest: None)
    assert [r['control'] for r in FC.elbow_owner_controls({}, None, {})] == ['a', 'b']

    monkeypatch.setattr(FC, '_humeral_patch_owner_row', lambda ph, lc, rest: {'control': 'patch'})
    # the patch row comes FIRST, which is the order demo_broken() appended them in
    assert [r['control'] for r in FC.elbow_owner_controls({}, None, {})] == ['patch', 'a', 'b']


# ---- the error rows: one broken dependency must not take the demo down -------------


def test_pose_library_controls_walks_characters_in_sorted_asset_order(monkeypatch):
    monkeypatch.setattr(FC, 'POSE_LIBRARY_CHARACTERS', {'zzzz': 'last', 'aaaa': 'first'})
    monkeypatch.setattr(FC, '_pose_library_character_rows', lambda char, ph, lc: [{'control': char}])
    assert [r['control'] for r in FC.pose_library_controls({}, None)] == ['first', 'last']


def test_pose_library_controls_turns_one_characters_failure_into_its_own_error_row(monkeypatch):
    def rows(char, ph, lc):
        if char == 'abel':
            raise KeyError('t5_joint_rom')
        return [{'control': char, 'ok': True}]

    monkeypatch.setattr(FC, '_pose_library_character_rows', rows)
    out = FC.pose_library_controls({}, None)
    # sorted by ASSET id, so cornelis ('0015…') comes before abel ('c334…')
    assert [r['control'] for r in out] == ['cornelis', 'pose_layer on abel']
    assert out[1]['ok'] is False
    assert out[1]['gate'] == 'pose_layer'
    assert out[1]['error'] == "KeyError: 't5_joint_rom'"


def test_incoming_blazepose_control_reports_an_error_row_instead_of_raising(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError('no rig here')

    monkeypatch.setattr(FC, 'skeleton_from_rig', boom)
    row = FC.incoming_blazepose_control({}, None)
    assert row['ok'] is False
    assert row['gate'] == 't5_joint_rom'
    assert row['error'] == 'RuntimeError: no rig here'


# ---- the orchestrator's own contract ------------------------------------------------


def _stub_controls(monkeypatch, ok_by_name):
    """Replace every control helper with a row recorder; returns the call-order list."""
    calls = []
    monkeypatch.setattr(FL, 'rig_state', lambda ph, lc, pose: {'rest': True})
    monkeypatch.setattr(FL, 'anatomical_frame', lambda rest: {'af': True})

    def row(name):
        calls.append(name)
        return {'control': name, 'ok': ok_by_name[name]}

    monkeypatch.setattr(FC, 'rom_overdrive_controls', lambda ph, lc, rest, af: [row('wrist'), row('cervical')])
    monkeypatch.setattr(FC, 'clone_pose_set_control', lambda ph, lc: row('clone'))
    monkeypatch.setattr(FC, 'lockstep_pronation_control', lambda ph, lc: row('pronation'))
    monkeypatch.setattr(FC, 'elbow_owner_controls', lambda ph, lc, rest: [row('elbow')])
    monkeypatch.setattr(FC, 'same_bone_invariance_control', lambda ph, lc, rest: row('same_bone'))
    monkeypatch.setattr(FC, 'incoming_blazepose_control', lambda ph, lc: row('blazepose'))
    monkeypatch.setattr(FC, 'pose_library_controls', lambda ph, lc: [row('library')])
    monkeypatch.setattr(FC, 'incomplete_library_control', lambda ph, lc: row('incomplete'))
    monkeypatch.setattr(FL, '_opposition_constant_controls', lambda: [row('opposition')])
    return calls


_ALL_NAMES = [
    'wrist',
    'cervical',
    'clone',
    'pronation',
    'elbow',
    'same_bone',
    'blazepose',
    'library',
    'incomplete',
    'opposition',
]


def test_demo_broken_runs_every_control_in_the_recorded_order(monkeypatch):
    """The order the controls were written in is part of the record, so it is a test."""
    calls = _stub_controls(monkeypatch, dict.fromkeys(_ALL_NAMES, True))
    out = FL.demo_broken()
    assert calls == _ALL_NAMES
    assert [c['control'] for c in out['controls']] == _ALL_NAMES
    assert out['all_controls_behaved'] is True
    assert out['schema']


def test_demo_broken_is_false_as_soon_as_one_control_misbehaved(monkeypatch):
    oks = dict.fromkeys(_ALL_NAMES, True)
    oks['blazepose'] = False
    _stub_controls(monkeypatch, oks)
    assert FL.demo_broken()['all_controls_behaved'] is False


def test_demo_broken_ignores_a_control_that_reported_no_verdict(monkeypatch):
    """`ok` None is the old ok5/ok6 "the rig does not carry it" row: not a failure."""
    oks = dict.fromkeys(_ALL_NAMES, True)
    oks['same_bone'] = None
    _stub_controls(monkeypatch, oks)
    out = FL.demo_broken()
    assert out['all_controls_behaved'] is True
    assert len(out['controls']) == len(_ALL_NAMES)


def test_demo_broken_skips_the_same_bone_row_entirely_when_the_region_is_absent(monkeypatch):
    _stub_controls(monkeypatch, dict.fromkeys(_ALL_NAMES, True))
    monkeypatch.setattr(FC, 'same_bone_invariance_control', lambda ph, lc, rest: None)
    out = FL.demo_broken()
    assert [c['control'] for c in out['controls']] == [n for n in _ALL_NAMES if n != 'same_bone']
    assert out['all_controls_behaved'] is True


def test_demo_broken_defaults_to_the_neutral_phenotype_and_copies_it(monkeypatch):
    """The old body's `ph = dict(phenotype or NEUTRAL)` — a copy, never the global."""
    seen = {}
    _stub_controls(monkeypatch, dict.fromkeys(_ALL_NAMES, True))

    def record(ph, lc, pose):
        seen['ph'] = ph
        return {'rest': True}

    monkeypatch.setattr(FL, 'rig_state', record)
    FL.demo_broken()
    assert seen['ph'] == dict(FL.NEUTRAL)
    assert seen['ph'] is not FL.NEUTRAL

    seen.clear()
    mine = {'height_cm': 180.0}
    FL.demo_broken(phenotype=mine)
    assert seen['ph'] == mine
    assert seen['ph'] is not mine


# ---- the opposition-constant controls restore what they mutate ----------------------


def test_opposition_constant_controls_restore_the_module_globals_they_move():
    """A control that left the constant moved would corrupt every later measurement."""
    before = FL.TILT_OPPOSITION_REQUIRED_FRACTION
    before_fn = FL.opposition_verdict
    rows = FL._opposition_constant_controls()
    assert FL.TILT_OPPOSITION_REQUIRED_FRACTION == before
    assert FL.opposition_verdict is before_fn
    assert len(rows) == 2
    assert [r['gate'] for r in rows] == [
        't5_pose_stiffness / AFS p.16 second conjunct',
        't5_pose_stiffness / opposition_rule_drift',
    ]
    # the first control reports one row per declared required fraction
    assert [x['required_fraction'] for x in rows[0]['observed']] == [f for f, _s, _a in FL._OPPOSITION_CONTROL_EXPECT]


def test_the_control_set_is_what_the_gate_measures_as_half_opposed():
    """Ties control 10's construction to the gate: measured opposition must be 0.5."""
    sks = [FL._tilt_control_pose(sh, hp, i) for i, (sh, hp) in enumerate(FL._OPPOSITION_CONTROL_POSES)]
    r = FL.t5_pose_stiffness(sks, world_up=np.array([0.0, 0.0, 1.0]))
    assert r['observed']['tilt_opposition_fraction'] == pytest.approx(0.5)
    assert r['observed']['tilt_n_sign_evaluated'] == 8
    assert r['observed']['tilt_n_same_sign'] == 4
    # both girdle standard deviations clear the printed floor, so the FIRST conjunct
    # passes and the second one is the only thing that can move the verdict
    sd = [x for x in r['detail']['scored'] if x['check'] == 'transverse_tilt_sd'][0]
    assert sd['status'] == PASS
