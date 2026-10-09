# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Unit tests for the steps ``qc_character_balance`` was split into.

Every one of these behaviours used to live inside a single 398-line function and
could only be reached by decoding a real clip on a machine with cv2, MTCNN and a
GPU — which is why none of them had a test. The steps take plain dicts, so each
is now exercised directly: the step-calibration warning, the record a region
reports, the freeze floor, the cross-character ratio (including a per-pair
override under the flipped ordering), the "measured nothing" guard, the hands
report and the box-quality verdict."""

import pytest

from zyg_workflows.pipeline_debug.gates_charbal_detect import (
    _CHARBAL_BOX_AREA_MAX,
    _CHARBAL_DIR_STEP,
    _CHARBAL_FACE_FILL_MIN,
    _CHARBAL_FACE_RATIO_MAX,
    _CHARBAL_FLOW_STEP,
)
from zyg_workflows.pipeline_debug.gates_charbal_steps import (
    box_suspects,
    gate_face_floor,
    gate_face_ratio,
    judge_box_quality,
    measurable_faces,
    part_record,
    report_hands,
    resolve_steps,
    score_box_against_detections,
)
from zyg_workflows.pipeline_debug.gates_motion import _MOTION_COHERENCE_FLOOR


def _out():
    """An empty report dict of the shape every step mutates."""
    return {'ok': True, 'characters': {}, 'cross': {}, 'checks': [], 'reasons': []}


def _perpix(median, mean=None, p90=1.0, burst=0.25, n=9):
    """A ``_perpix_stats``-shaped bundle with the median the test cares about."""
    return {
        'flow_median': median,
        'flow_mean': mean if mean is not None else median,
        'flow_p90': p90,
        'burst_frac': burst,
        'n_samples': n,
    }


def _vecs(flow_mean, reversals=3.0, net=0.5, net_win=0.25):
    """A ``_motion_vector_stats``-shaped bundle."""
    return {'flow_mean': flow_mean, 'reversals_per_s': reversals, 'net_path': net, 'net_path_win': net_win}


def _face(median, mean=None, **extra):
    """A measured face record as ``measure_characters`` would have produced it."""
    rec = {
        'box': [0.1, 0.1, 0.2, 0.2],
        'flow_median': median,
        'flow_mean': mean if mean is not None else median,
        'burst_frac': 0.25,
    }
    rec.update(extra)
    return rec


# ── resolve_steps ────────────────────────────────────────────────────────────


def test_resolve_steps_defaults_are_the_calibrated_pair():
    out = _out()
    assert resolve_steps(out, None, None, None, lambda _m: None) == (_CHARBAL_FLOW_STEP, _CHARBAL_DIR_STEP)
    assert (out['step_flow'], out['step_dir']) == (_CHARBAL_FLOW_STEP, _CHARBAL_DIR_STEP)
    assert 'step_warning' not in out
    assert out['reasons'] == []


def test_resolve_steps_warns_when_an_uncalibrated_step_meets_an_implicit_cap():
    out, lines = _out(), []
    sf, sd = resolve_steps(out, _CHARBAL_FLOW_STEP + 1, 3, None, lines.append)
    assert (sf, sd) == (_CHARBAL_FLOW_STEP + 1, 3)
    assert out['step_warning'] is True
    assert len(out['reasons']) == 1
    assert 'the ratio cap was calibrated at' in out['reasons'][0]
    assert lines and lines[0].startswith('[qc_character_balance] WARNING:')


def test_resolve_steps_is_silent_when_the_cap_is_explicit():
    out = _out()
    resolve_steps(out, _CHARBAL_FLOW_STEP + 1, None, 2.0, lambda _m: None)
    assert 'step_warning' not in out
    assert out['reasons'] == []


# ── part_record ──────────────────────────────────────────────────────────────


def test_part_record_without_per_pixel_stats_is_an_unmeasured_stub():
    rec = part_record((0.0, 0.0, 0.5, 0.5), None, _vecs(1.0))
    assert rec == {'box': [0.0, 0.0, 0.5, 0.5], 'unmeasured': True}


def test_part_record_rounds_and_marks_a_moving_region():
    rec = part_record(
        (0.0, 0.0, 0.5, 0.5),
        _perpix(0.123456, mean=0.23456, p90=0.5, burst=0.4321, n=11),
        _vecs(_MOTION_COHERENCE_FLOOR + 1.0, reversals=4.5678, net=0.98765, net_win=0.4321),
    )
    assert rec['flow_median'] == 0.1235
    assert rec['flow_mean'] == 0.2346
    assert rec['burst_frac'] == 0.432
    assert rec['reversals_per_s'] == 4.568
    assert rec['net_path'] == 0.9877
    assert rec['net_path_win'] == 0.4321
    assert rec['n_samples'] == 11
    assert rec['box_area'] == 0.25
    assert rec['moving'] is True
    assert 'direction_note' not in rec


def test_part_record_notes_that_direction_is_noise_below_the_coherence_floor():
    rec = part_record((0.0, 0.0, 0.1, 0.1), _perpix(0.2), _vecs(_MOTION_COHERENCE_FLOOR / 2))
    assert rec['moving'] is False
    assert 'below the coherence floor' in rec['direction_note']


def test_part_record_without_vector_stats_reports_no_direction_at_all():
    rec = part_record((0.0, 0.0, 0.1, 0.1), _perpix(0.2), None)
    assert rec['reversals_per_s'] is None
    assert rec['net_path'] is None
    assert rec['net_path_win'] is None
    assert rec['vec_mean'] is None
    assert rec['moving'] is False
    assert 'direction_note' not in rec


# ── score_box_against_detections ─────────────────────────────────────────────


def test_score_box_matches_the_overlapping_detection_not_the_largest():
    # The supplied box sits on the small right-hand face; the big left-hand
    # detection must not be the one it is scored against.
    face = {'box': [0.6, 0.0, 0.8, 0.2]}
    score_box_against_detections(
        face,
        [
            {'box': [0.0, 0.0, 0.5, 0.5], 'side': 'left'},
            {'box': [0.6, 0.0, 0.7, 0.2], 'side': 'right'},
        ],
    )
    assert face['matched_detection'] == 'right'
    assert face['face_fill'] == 0.5  # half of the supplied box is face
    assert face['face_covered'] == 1.0  # all of the detection is inside it


# ── measurable_faces ─────────────────────────────────────────────────────────


def test_measurable_faces_keeps_only_the_faces_that_measured():
    out = _out()
    out['characters'] = {
        'cornelis': {'face': _face(0.30)},
        'abel': {'face': {'box': [0, 0, 1, 1], 'unmeasured': True}},
        'extra': {'face': None},
    }
    norm = {
        'cornelis': {'face': (0, 0, 1, 1), 'hands': None},
        'abel': {'face': (0, 0, 1, 1), 'hands': None},
        'extra': {'face': None, 'hands': None},
    }
    faces = measurable_faces(out, norm, lambda _m: None)
    assert list(faces) == ['cornelis']
    assert out['checks'] == []
    assert 'error' not in out


def test_measurable_faces_refuses_to_pass_when_nothing_measured_at_all():
    out = _out()
    out['characters'] = {'cornelis': {'face': {'box': [0, 0, 1, 1], 'unmeasured': True}}}
    norm = {'cornelis': {'face': (0, 0, 1, 1), 'hands': None}}
    lines = []
    assert measurable_faces(out, norm, lines.append) == {}
    assert 'THIS GATE DID NOT RUN' in out['error']
    assert out['checks'] == [
        {
            'check': 'character_balance:measured',
            'ok': False,
            'faces_supplied': 1,
            'faces_measured': 0,
            'note': out['error'],
        }
    ]
    assert lines and 'WARNING' in lines[0]


# ── gate_face_floor ──────────────────────────────────────────────────────────


def test_gate_face_floor_fails_a_frozen_face_and_passes_a_live_one():
    out = _out()
    out['characters'] = {
        'cornelis': {'ok': True, 'reasons': [], 'face': _face(0.30)},
        'abel': {'ok': True, 'reasons': [], 'face': _face(0.0008)},
    }
    faces = {n: c['face'] for n, c in out['characters'].items()}
    gate_face_floor(out, faces, None, None, lambda _m: None)
    assert faces['cornelis']['ok'] is True
    assert faces['abel']['ok'] is False
    assert out['characters']['abel']['ok'] is False
    assert 'FROZEN' in out['characters']['abel']['reasons'][0]
    assert [c['ok'] for c in out['checks']] == [True, False]
    assert [c['check'] for c in out['checks']] == [
        'character_balance:cornelis.face',
        'character_balance:abel.face',
    ]


def test_gate_face_floor_honours_a_per_character_threshold_and_the_mean_gate():
    out = _out()
    out['characters'] = {'abel': {'ok': True, 'reasons': [], 'face': _face(0.30, mean=0.31)}}
    faces = {'abel': out['characters']['abel']['face']}
    gate_face_floor(out, faces, {'abel': 0.40}, {'abel': 0.50}, lambda _m: None)
    assert faces['abel']['ok'] is False
    assert faces['abel']['min_flow'] == 0.40
    assert len(out['characters']['abel']['reasons']) == 2
    assert 'the v12 pin signature' in out['characters']['abel']['reasons'][1]


# ── report_hands ─────────────────────────────────────────────────────────────


def test_report_hands_reports_measured_hands_and_never_gates_them():
    out = _out()
    out['characters'] = {
        'cornelis': {'hands': _face(9.9, reversals_per_s=11.0, net_path=0.1), 'hand_face_ratio': 33.0},
        'abel': {'hands': {'box': [0, 0, 1, 1], 'unmeasured': True}},
        'extra': {'hands': None},
    }
    report_hands(out, lambda _m: None)
    assert len(out['checks']) == 1
    check = out['checks'][0]
    assert check['check'] == 'character_balance:cornelis.hands'
    assert check['ok'] is True
    assert check['hand_face_ratio'] == 33.0
    assert 'reported, not gated' in check['note']


# ── gate_face_ratio ──────────────────────────────────────────────────────────


def test_gate_face_ratio_cannot_run_on_fewer_than_two_faces():
    out = _out()
    cross = gate_face_ratio(out, {'cornelis': _face(0.3)}, None, lambda _m: None)
    assert cross == {'n_faces': 1, 'ok': True, 'note': cross['note']}
    assert 'a balance ratio needs two' in cross['note']
    assert out['checks'] == [{'check': 'character_balance:face_ratio', 'ok': True, 'note': cross['note']}]


def test_gate_face_ratio_fails_the_shot_one_character_is_carrying():
    out = _out()
    faces = {'cornelis': _face(0.400), 'abel': _face(0.160)}
    cross = gate_face_ratio(out, faces, None, lambda _m: None)
    assert cross['lead'] == 'cornelis'
    assert cross['lag'] == 'abel'
    assert cross['face_flow_ratio'] == 2.5
    assert cross['max_ratio'] == _CHARBAL_FACE_RATIO_MAX
    assert cross['ok'] is False
    assert 'ONE CHARACTER IS CARRYING THE SHOT' in cross['reasons'][0]
    assert out['checks'][0]['ratio'] == 2.5


def test_gate_face_ratio_passes_inside_the_cap():
    out = _out()
    cross = gate_face_ratio(out, {'cornelis': _face(0.300), 'abel': _face(0.200)}, None, lambda _m: None)
    assert cross['face_flow_ratio'] == 1.5
    assert cross['ok'] is True
    assert cross['reasons'] == []


@pytest.mark.parametrize('key', ['cornelis/abel', 'abel/cornelis'])
def test_gate_face_ratio_finds_a_pair_override_under_either_ordering(key):
    # Which character leads is an OUTPUT, so an override written for the run
    # where abel led must still apply on the run where cornelis does.
    out = _out()
    cross = gate_face_ratio(out, {'cornelis': _face(0.400), 'abel': _face(0.160)}, {key: 3.0}, lambda _m: None)
    assert cross['max_ratio'] == 3.0
    assert cross['ok'] is True


# ── box quality ──────────────────────────────────────────────────────────────


def test_box_suspects_is_empty_for_a_tight_well_filled_box():
    assert box_suspects({'abel': _face(0.3, box_area=_CHARBAL_BOX_AREA_MAX / 2, face_fill=0.9)}) == []


def test_box_suspects_names_both_defects_of_one_box():
    suspect = box_suspects(
        {
            'abel': _face(
                0.3,
                box_area=_CHARBAL_BOX_AREA_MAX + 0.1,
                face_fill=_CHARBAL_FACE_FILL_MIN - 0.1,
            )
        }
    )
    assert len(suspect) == 1
    assert suspect[0].startswith('abel.face: ')
    assert 'of the frame' in suspect[0]
    assert ' and ' in suspect[0]
    assert 'is face' in suspect[0]


def test_box_suspects_ignores_a_box_whose_fill_was_never_measured():
    assert box_suspects({'abel': _face(0.3, box_area=_CHARBAL_BOX_AREA_MAX / 2)}) == []


def test_judge_box_quality_marks_a_passing_ratio_inconclusive():
    out = _out()
    cross = {'ok': True}
    faces = {'abel': _face(0.3, box_area=_CHARBAL_BOX_AREA_MAX + 0.1, face_fill=0.9)}
    msg = judge_box_quality(out, faces, cross, {'ok': True, 'faces': []}, lambda _m: None)
    assert msg and 'before believing a PASS' in msg
    assert cross['inconclusive'] is True
    assert out['checks'][0] == {
        'check': 'character_balance:box_quality',
        'ok': False,
        'suspect': 1,
        'note': msg,
    }
    assert out['reasons'] == [msg]


def test_judge_box_quality_passes_and_says_whether_fill_was_checked():
    out = _out()
    faces = {'abel': _face(0.3, box_area=_CHARBAL_BOX_AREA_MAX / 2, face_fill=0.9)}
    assert judge_box_quality(out, faces, {'ok': True}, {'ok': True, 'faces': []}, lambda _m: None) is None
    assert out['checks'][0]['ok'] is True
    assert out['checks'][0]['note'] == 'every face box is inside the calibrated envelope'

    out2 = _out()
    assert judge_box_quality(out2, faces, {'ok': True}, None, lambda _m: None) is None
    assert 'face_fill NOT checked' in out2['checks'][0]['note']
