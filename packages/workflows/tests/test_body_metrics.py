# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""geom.body_metrics — the fraction maths, and the real measurement of Abel.

The synthetic test pins the arithmetic with no detector in the loop; the Abel test is
the end-to-end one and needs MediaPipe plus the character's sheet cells on disk.
"""

import json
import os

import numpy as np
import pytest

from zyg_workflows.geom import body_metrics as BM
from zyg_workflows.geom import keypoints as K

ABEL = 'c3345deb5bde'

#: The synthetic tests below feed hand-made points straight into the fraction maths and
#: need no detector. The Abel tests run the real pose detector over his sheet cells, which
#: means opencv and MediaPipe — neither is a test dependency, so they skip without them.
needs_detector = pytest.mark.skipif(
    K.cv2 is None or not os.path.isfile(os.path.join(K._DET_DIR, 'pose_landmarker_full.task')),
    reason='the pose detector needs opencv-python and the MediaPipe task files under ZYG_DATA_ROOT/assets/detectors',
)


def _stick(h_px=1000.0, z_shoulder_gap=0.0):
    """A hand-made 33-point figure with exactly known ratios.

    crown (500,0) · shoulders y=200 width 200 · wrists y=600 straight down ·
    hips y=550 · ankles y=1000.  So over h_px=1000:
        head_neck 0.20 · shoulder 0.20 · torso 0.35 · arm 0.40 · leg 0.45
    """
    pts = np.zeros((33, 3), np.float32)
    pts[:, 2] = 0.9
    z = np.zeros(33, np.float32)
    put = lambda n, x, y: pts.__setitem__((K.P[n], slice(0, 2)), (x, y))  # noqa: E731
    put('nose', 500, 100)
    put('left_shoulder', 600, 200)
    put('right_shoulder', 400, 200)
    put('left_wrist', 600, 600)
    put('right_wrist', 400, 600)
    put('left_hip', 560, 550)
    put('right_hip', 440, 550)
    put('left_ankle', 560, 1000)
    put('right_ankle', 440, 1000)
    z[K.P['left_shoulder']] = z_shoulder_gap
    return pts, z, (500.0, 0.0), h_px


def test_fraction_maths_on_a_synthetic_stick_figure():
    pts, z, crown, h = _stick()
    pts[K.P['left_ankle'], 2] = 0.8  # the minimum, deliberately
    m = BM.measure_arrays(pts, z, crown, h)

    assert m['fractions'] == pytest.approx(
        {'head_neck': 0.20, 'shoulder': 0.20, 'torso': 0.35, 'arm': 0.40, 'leg': 0.45}, abs=1e-6
    )
    assert m['px']['height'] == 1000.0
    assert m['px']['leg'] == pytest.approx(450.0)
    assert m['visibility_min'] == pytest.approx(0.8)
    assert m['yaw_ok'] is True  # both shoulders at the same depth


def test_fractions_scale_with_standing_height():
    """Only ratios survive the sheet's framing — doubling every pixel changes nothing."""
    pts, z, crown, h = _stick()
    a = BM.measure_arrays(pts, z, crown, h)
    b = BM.measure_arrays(pts * np.array([2, 2, 1], np.float32), z * 2, (1000.0, 0.0), h * 2)
    assert b['fractions'] == pytest.approx(a['fractions'], abs=1e-6)


def test_shoulder_depth_difference_flags_a_turned_body():
    # shoulder width 200px, one shoulder 150px deeper -> ratio 0.75, over the 0.5 tol
    pts, z, crown, h = _stick(z_shoulder_gap=150.0)
    m = BM.measure_arrays(pts, z, crown, h)
    assert m['yaw_ratio'] == pytest.approx(0.75)
    assert m['yaw_ok'] is False


def test_measure_arrays_rejects_a_wrong_sized_skeleton():
    with pytest.raises(ValueError):
        BM.measure_arrays(np.zeros((17, 3), np.float32), np.zeros(17), (0, 0), 100.0)


@needs_detector
@pytest.mark.skipif(not os.path.isdir(BM.cells_dir(ABEL)), reason="Abel's contact sheet is not on this machine")
def test_measure_abel_writes_body_metrics_json():
    res = BM.measure(ABEL)

    path = BM.out_path(ABEL)
    assert os.path.isfile(path)
    with open(path, 'r', encoding='utf-8') as fh:
        on_disk = json.load(fh)
    assert on_disk['schema'] == 'zyg.body_metrics/1'
    assert on_disk['char_id'] == ABEL
    assert on_disk['fractions'] == res['fractions']

    # the bible's identity, copied in
    assert res['height_m'] == 1.52
    assert res['gender'] == 'male'
    assert res['age'] == 12
    assert res['body_build']

    fr = res['fractions']
    assert set(fr) == {'leg', 'arm', 'torso', 'head_neck', 'shoulder'}
    for k, v in fr.items():
        assert 0.05 < v < 0.75, '%s out of range: %r' % (k, v)
    assert 0.35 <= fr['leg'] <= 0.60
    assert 0.28 <= fr['arm'] <= 0.55
    assert res['visibility_min'] >= 0.5
    assert res['method'] == 'blazepose33/mask'
    assert res['confidence'] in ('high', 'low')
    assert os.path.isfile(res['image'])


@needs_detector
@pytest.mark.skipif(
    not os.path.isfile(BM.body_anchor_path(ABEL)), reason="Abel's body anchor cell is not on this machine"
)
def test_abels_body_anchor_is_a_portrait_and_is_not_measured():
    """The reason measure() scans past the anchor: Abel's cell_00_body.png is waist-up,
    so BlazePose puts his ankles outside the 1216px frame at visibility ~0."""
    anchor = BM._measure_image(BM.body_anchor_path(ABEL))
    assert anchor is not None
    assert anchor['full_body'] is False
    assert BM.measure(ABEL)['image'] != BM.body_anchor_path(ABEL)


def test_measure_refuses_an_unknown_character():
    with pytest.raises(FileNotFoundError):
        BM.measure('zz_no_such_character_zz')
