# SPDX-FileCopyrightText: 2026 Zygomatic
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Unit tests for the record builders `pose_layer()` was split into.

Until the 2026-10-09 function split these were blocks inside a 368-line
`pose_layer()` — the 190-line gate loop body, the absent-library stand-in, the
`_rate_txt` closure and the library block — reachable only by loading the rig
model and re-posing it once per fitted pose. They are now module-level functions
in `pose_limits.pose_layer_records`, so this file is the first time any of that
logic is exercised in isolation: every test below feeds plain dicts, touches no
GPU, no network and no service, and asserts a behaviour the old function had.

The behaviour under the most pressure here is the roll-up rule the whole entry
point exists for: a gate that passes on the rest pose and DECLARES a fitted pose
library it could not read reports UNRESOLVED, never PASS.
"""

from zyg_workflows.geom.pose_limits.base import CANON, FAIL, PASS, REPORT, UNRESOLVED
from zyg_workflows.geom.pose_limits.pose_layer import (
    POSE_LAYER_GATE_KEYS,
    POSE_LAYER_SUBJECTS,
    PoseLayerContractError,
    verify_contract,
)
from zyg_workflows.geom.pose_limits.pose_layer_records import (
    absent_library_report,
    gate_explain,
    gate_observed,
    gate_record,
    gate_subjects,
    library_block,
    rate_text,
)

_ROM = POSE_LAYER_SUBJECTS['t5_joint_rom']
_PRONATION = POSE_LAYER_SUBJECTS['t5_pronation_isolation']
_STIFFNESS = POSE_LAYER_SUBJECTS['t5_pose_stiffness']
_ELBOW = POSE_LAYER_SUBJECTS['t5_elbow_owner']


def _rest_record(status=PASS):
    """A stand-in `run_character()` gate record, in the shape the builders read."""
    return {
        'gate': 't5_joint_rom',
        'status': status,
        'explain': '0 of 11 ROM sub-checks failed',
        'observed': {'n_checks': 11, 'n_failed': 0},
        'band': {'min_deg': 0.0, 'max_deg': 145.0},
        'source': 'AFS p.181-182',
        'provenance': CANON,
        'detail': {'checks': []},
    }


def _report(n_poses=44, n_violating=44, status=FAIL):
    """A stand-in `pose_library_report()` for a library that WAS read."""
    return {
        'status': status,
        'n_poses': n_poses,
        'rate_denominator': n_poses,
        'n_violating': n_violating,
        'n_warning': 0,
        'n_passing': n_poses - n_violating,
        'violation_rate': (float(n_violating) / n_poses) if n_poses else None,
        'warn_rate': 0.0,
        'status_counts': {FAIL: n_violating},
        'per_check_counts': {'elbow_flexion': {'fail': n_violating, 'warn': 0}},
        'worst_offenders': {
            'by_check': [{'check': 'elbow_flexion', 'fail': n_violating}],
            'by_pose': [{'cell': 'a01', 'fail': 3}],
        },
        'library_complete': True,
        'library_incomplete_note': None,
        'integrity': {'n_files_found': n_poses},
        'occiput_share_failures_by_total_rotation': {},
        'pronation_coupling': {
            'humerus_twist_deg_abs_mean': 7.28,
            'forearm_twist_deg_abs_mean': 41.1,
            'pearson_r_forearm_vs_humerus': -0.58,
            'n_arms': 44,
        },
        'explain': '44 of 44 fitted poses FAIL the printed bands',
        'reason': None,
        'policy': 'a high rate is a finding about our pose library.',
    }


def _present_library():
    """The `library` block of a character whose fitted library was read and failed."""
    return library_block(_report(), True, 'abel_char_mesh', None)


def _absent_library(name='nobody'):
    """The `library` block of a character that ships no fitted library at all."""
    rep = absent_library_report(name, 97)
    return library_block(rep, False, None, None), rep


def test_absent_library_report_is_unresolved_with_no_rate_and_a_measured_reason():
    rep = absent_library_report('nobody', 97)

    assert rep['status'] == UNRESOLVED
    assert rep['n_poses'] == 0
    assert rep['rate_denominator'] == 0
    # Never 0.0: a rate of zero reads as a pass, and nothing was measured.
    assert rep['violation_rate'] is None
    assert rep['n_violating'] is None
    assert rep['library_complete'] is False
    assert rep['integrity']['expected_pose_aa_rows'] == 97
    assert 'nobody' in rep['reason']
    assert 'not a pass' in rep['explain']


def test_rate_text_says_not_evaluated_rather_than_reporting_a_zero_rate():
    present = _present_library()
    absent, _ = _absent_library()

    assert rate_text(present) == 'library 44/44 pose(s) FAIL (rate 1.0000)'
    assert rate_text(absent) == 'library NOT evaluated'


def test_library_block_calls_a_mapped_asset_with_zero_measured_poses_absent():
    scored = library_block(_report(), True, 'abel_char_mesh', None)
    empty = library_block(_report(n_poses=0, n_violating=0, status=UNRESOLVED), True, 'abel_char_mesh', None)

    assert scored['present'] is True
    assert scored['n_files_found'] == 44
    assert scored['violation_rate'] == 1.0
    assert scored['stiffness'] is None
    # `present` is narrower than lib_present: no pose was measured, so as far as
    # every gate is concerned the library is not there.
    assert empty['present'] is False
    assert empty['n_poses'] == 0


def test_a_gate_that_declares_a_library_it_cannot_read_rolls_up_to_unresolved():
    absent, rep = _absent_library('nobody')

    sub = gate_subjects('t5_joint_rom', _ROM, _rest_record(PASS), absent, rep, None)

    assert sub.rest_status == PASS
    assert sub.evaluated == ['rest']
    assert sub.library_status == UNRESOLVED
    assert 'nobody' in sub.not_evaluated['library']
    # THE defect this entry point closes: PASS on the rest pose alone is not the
    # verdict of a gate whose text claims the fitted library too.
    assert sub.status == UNRESOLVED


def test_rom_subject_over_a_failing_library_rolls_up_to_fail_and_carries_the_numbers():
    library = _present_library()

    sub = gate_subjects('t5_joint_rom', _ROM, _rest_record(PASS), library, _report(), None)

    assert sub.status == FAIL
    assert sub.evaluated == ['rest', 'library']
    assert sub.library_record['violation_rate'] == 1.0
    assert sub.library_record['n_violating'] == 44
    # band/source/provenance of the library record come from the rest record.
    assert sub.library_record['source'] == 'AFS p.181-182'
    assert sub.not_evaluated == {}


def test_pronation_library_subject_is_report_and_never_scored():
    library = _present_library()

    sub = gate_subjects('t5_pronation_isolation', _PRONATION, _rest_record(PASS), library, _report(), None)

    assert sub.library_status == REPORT
    assert sub.status == REPORT
    assert sub.library_record['provenance'] == CANON
    assert 'no printed source gives one' in sub.library_record['not_scored_because']


def test_the_rest_subject_of_pose_stiffness_is_not_applicable_and_contributes_nothing():
    library = _present_library()
    stiff = {'status': PASS, 'explain': 'tilt sd 4.1 deg', 'observed': {'shoulder_tilt_sd_deg': 4.1}}

    sub = gate_subjects('t5_pose_stiffness', _STIFFNESS, None, library, _report(), stiff)

    assert sub.rest_status is None
    assert sub.evaluated == ['library']
    assert 'standard deviation of' in sub.not_applicable['rest']
    assert sub.not_evaluated == {}
    # The not-applicable rest subject adds no UNRESOLVED, so a passing library
    # alone is a pass here.
    assert sub.status == PASS


def test_observed_names_the_library_in_words_when_a_gate_does_not_declare_it():
    library = _present_library()
    rest = _rest_record(PASS)
    sub = gate_subjects('t5_elbow_owner', _ELBOW, rest, library, _report(), None)

    obs = gate_observed('t5_elbow_owner', _ELBOW, rest, sub, library, None)

    assert obs['library_subject'].startswith('not applicable: ')
    assert 'rig SKINNING' in obs['library_subject']
    # The ROM violation rate belongs to the ROM gate's subject, not to this one.
    assert 'violation_rate' not in obs
    assert 'n_poses' not in obs
    assert obs['rest_observed'] == {'n_checks': 11, 'n_failed': 0}


def test_observed_of_the_rom_gate_carries_the_rate_and_the_worst_check():
    library = _present_library()
    rest = _rest_record(PASS)
    sub = gate_subjects('t5_joint_rom', _ROM, rest, library, _report(), None)

    obs = gate_observed('t5_joint_rom', _ROM, rest, sub, library, None)

    assert obs['n_poses'] == 44
    assert obs['library_complete'] is True
    assert obs['violation_rate'] == 1.0
    assert obs['worst_check'] == 'elbow_flexion'
    assert obs['worst_check_fail_count'] == 44


def test_explain_joins_the_subject_clauses_in_the_published_order():
    absent, rep = _absent_library('nobody')
    rest = _rest_record(PASS)
    sub = gate_subjects('t5_joint_rom', _ROM, rest, absent, rep, None)

    txt = gate_explain('t5_joint_rom', _ROM, rest, sub, absent, None)
    parts = txt.split(' | ')

    assert parts[0] == 'rest pose: pass (0 of 11 ROM sub-checks failed)'
    assert parts[1] == 'fitted pose library: unresolved — library NOT evaluated'
    assert parts[2].startswith('library subject DECLARED but NOT evaluated: ')


def test_gate_record_carries_exactly_the_published_gate_keys():
    library = _present_library()

    rec = gate_record('t5_joint_rom', _ROM, _rest_record(PASS), library, _report(), None)

    assert set(rec) == set(POSE_LAYER_GATE_KEYS)
    assert rec['gate'] == 't5_joint_rom'
    assert rec['status'] == FAIL
    assert rec['rest_only_status'] == PASS
    assert rec['library_only_status'] == FAIL
    assert rec['subjects_declared'] == ['rest', 'library']
    assert rec['subject_not_evaluated'] is None
    assert rec['subject_not_applicable'] is None
    assert rec['band'] == {'min_deg': 0.0, 'max_deg': 145.0}
    assert rec['detail']['rest_record']['gate'] == 't5_joint_rom'


def test_gate_record_of_a_rest_only_gate_publishes_its_not_applicable_reason():
    library = _present_library()

    rec = gate_record('t5_elbow_owner', _ELBOW, _rest_record(PASS), library, _report(), None)

    assert set(rec) == set(POSE_LAYER_GATE_KEYS)
    assert rec['subjects_declared'] == ['rest']
    assert rec['subjects_evaluated'] == ['rest']
    assert 'library' in rec['subject_not_applicable']
    assert rec['library_only_status'] is None
    assert rec['status'] == PASS


def test_verify_contract_refuses_a_record_that_is_not_the_published_shape():
    try:
        verify_contract({'schema': 'geom.pose_limits/pose_layer/1'})
    except PoseLayerContractError as exc:
        assert 'top level' in str(exc)
    else:
        raise AssertionError('verify_contract accepted a record with one key')
