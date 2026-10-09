# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""scene_plates.build on a SYNTHETIC plates_raw — no Blender, no GPU, no canon library.

The fixture is a 5-frame 320x192 shot with one actor ('abel') whose proxy matte is a
rectangle, and a hand-placed 33-point skeleton with ELEVEN joints deliberately outside
that rectangle (head, wrists, ankles, feet). Those prove the load-bearing property of the
bridge: the guide skeleton is drawn over the whole frame, not clipped to the proxy's
silhouette, so a thin or missing proxy limb still tells the generator where the limb is.
"""

import json
import os

import numpy as np
import pytest

cv2 = pytest.importorskip('cv2', reason='scene_plates needs opencv-python')

from zyg_workflows import scene_plates as SP  # noqa: E402
from zyg_workflows.geom.keypoints import POSE_NAMES  # noqa: E402

W, H, N = 320, 192, 5
RECT = (120, 40, 200, 160)  # x0, y0, x1, y1 — the proxy matte
BEAUTY = 200  # flat beauty grey, distinct from the 127 fill
CLEAN = (50, 62, 124, 136)  # y0, y1, x0, x1 — inside RECT, no bone passes here

# x, y, visibility. The 11 marked OUT sit outside RECT on purpose.
JOINTS = {
    'nose': (160, 30, 1.0),  # OUT (above)
    'left_eye': (154, 25, 1.0),  # OUT
    'right_eye': (166, 25, 1.0),  # OUT
    'left_ear': (148, 27, 1.0),  # OUT
    'right_ear': (172, 27, 1.0),  # OUT
    'left_shoulder': (140, 70, 1.0),
    'right_shoulder': (180, 70, 1.0),
    'left_elbow': (125, 90, 1.0),
    'right_elbow': (195, 90, 1.0),
    'left_wrist': (100, 110, 1.0),  # OUT (left of RECT)
    'right_wrist': (220, 110, 1.0),  # OUT (right of RECT)
    'left_hip': (145, 110, 1.0),
    'right_hip': (175, 110, 1.0),
    'left_knee': (145, 145, 1.0),
    'right_knee': (175, 145, 1.0),
    'left_ankle': (140, 180, 1.0),  # OUT (below)
    'right_ankle': (180, 180, 1.0),  # OUT
    'left_foot_index': (135, 190, 1.0),  # OUT
    'right_foot_index': (185, 190, 1.0),  # OUT
}


def _pts():
    return [list(JOINTS.get(n, (0.0, 0.0, 0.0))) for n in POSE_NAMES]


def _write_raw(raw, n=N, mattes=True):
    os.makedirs(raw, exist_ok=True)
    x0, y0, x1, y1 = RECT
    for i in range(1, n + 1):
        cv2.imwrite(os.path.join(raw, 'beauty_%05d.png' % i), np.full((H, W, 3), BEAUTY, np.uint8))
        grad = np.tile(np.linspace(0, 65535, W, dtype=np.float64), (H, 1))
        cv2.imwrite(os.path.join(raw, 'depth_%05d.png' % i), grad.astype(np.uint16))
        if mattes:
            m = np.zeros((H, W), np.uint8)
            m[y0:y1, x0:x1] = 255
            cv2.imwrite(os.path.join(raw, 'matte_abel_%05d.png' % i), m)
    with open(os.path.join(raw, 'joints.json'), 'w', encoding='utf-8') as fh:
        json.dump(
            {
                'fps': 24,
                'width': W,
                'height': H,
                'names': POSE_NAMES,
                'frames': [{'f': i, 'actors': {'abel': {'pts': _pts()}}} for i in range(1, n + 1)],
            },
            fh,
        )
    with open(os.path.join(raw, 'camera.json'), 'w', encoding='utf-8') as fh:
        json.dump(
            {
                'width': W,
                'height': H,
                'fps': 24,
                'near': 0.5,
                'far': 60.0,
                'frames': [
                    {
                        'f': i,
                        'p': [0, -8, 1.6],
                        't': [0, 0, 1.0],
                        'fov': 50,
                        'lens_mm': 35.0,
                        'matrix_world': [0.0] * 16,
                    }
                    for i in range(1, n + 1)
                ],
            },
            fh,
        )


@pytest.fixture(scope='module')
def built(tmp_path_factory):
    shot = tmp_path_factory.mktemp('shot_synth')
    _write_raw(os.path.join(str(shot), 'plates_raw'))
    face = str(shot / 'canon_face.png')
    cv2.imwrite(face, np.full((100, 80, 3), 90, np.uint8))
    orig = SP.canon_face_crop
    SP.canon_face_crop = lambda cid, **kw: face
    try:
        ps = SP.build(str(shot), log=lambda m: None)
    finally:
        SP.canon_face_crop = orig
    return str(shot), ps


def test_outside_joints_are_really_outside():
    x0, y0, x1, y1 = RECT
    out = [n for n, (x, y, v) in JOINTS.items() if not (x0 <= x < x1 and y0 <= y < y1)]
    assert len(out) >= 8, out


def test_plateset_json(built):
    shot, ps = built
    with open(os.path.join(shot, 'plates', 'plateset.json'), 'r', encoding='utf-8') as fh:
        disk = json.load(fh)
    assert disk == ps
    assert disk['schema'] == 'zyg.plateset/1'
    assert (disk['frames'], disk['fps'], disk['width'], disk['height']) == (N, 24, W, H)
    assert disk['face_source'] == 'canon_static'
    assert disk['actors'][0]['id'] == 'abel'
    assert disk['actors'][0]['char_id'] == 'abel'
    assert 0.15 < disk['actors'][0]['matte_coverage_mean'] < 0.17
    for k, pat in (
        ('ctrl', 'ctrl_%05d.png'),
        ('mask', 'm_%05d.png'),
        ('pose', 'pose_%05d.png'),
        ('face', 'face_%05d.png'),
        ('bg', 'bg_%05d.png'),
    ):
        assert disk[k] == pat
        assert os.path.isfile(os.path.join(shot, 'plates', pat % 1))
    assert os.path.isfile(os.path.join(shot, 'plates', 'still.png'))
    assert os.path.isfile(os.path.join(shot, 'plates', 'depth_00001.png'))


def test_ctrl_is_grey_under_matte_and_carries_the_skeleton(built):
    shot, _ = built
    for i in range(1, N + 1):
        c = cv2.imread(os.path.join(shot, 'plates', 'ctrl_%05d.png' % i), cv2.IMREAD_COLOR)
        assert c.shape == (H, W, 3)
        cy0, cy1, cx0, cx1 = CLEAN
        assert (c[cy0:cy1, cx0:cx1] == 127).all()  # neutralised proxy region
        assert (c[0:20, 0:20] == BEAUTY).all()  # the city is untouched
        # bone 0 (left_shoulder -> right_shoulder) is _POSE_COLOURS[0] = BGR (0, 0, 255)
        assert ((c[:, :, 0] == 0) & (c[:, :, 1] == 0) & (c[:, :, 2] == 255)).any()


def test_skeleton_is_not_clipped_to_the_matte(built):
    """Drawn outside the proxy silhouette: the wrist discs and the head bones."""
    shot, _ = built
    p = cv2.imread(os.path.join(shot, 'plates', 'pose_00001.png'), cv2.IMREAD_COLOR)
    for name in ('left_wrist', 'right_wrist', 'left_ankle', 'right_ankle'):
        x, y, _v = JOINTS[name]
        assert p[y, x].tolist() == [255, 255, 255], name
    nx, ny, _ = JOINTS['nose']
    assert p[ny - 6 : ny + 6, nx - 10 : nx + 10].any()  # head bones exist above RECT


def test_pose_is_black_away_from_bones(built):
    shot, _ = built
    for i in range(1, N + 1):
        p = cv2.imread(os.path.join(shot, 'plates', 'pose_%05d.png' % i), cv2.IMREAD_COLOR)
        assert p.shape == (H, W, 3)
        assert not p[0:20, 0:20].any()
        assert not p[:, 240:].any()  # right of every joint
        assert p.any()


def test_mask_is_the_dilated_matte(built):
    shot, _ = built
    x0, y0, x1, y1 = RECT
    matte_frac = ((x1 - x0) * (y1 - y0)) / float(W * H)
    r = int(round(0.03 * H))
    exp = ((x1 - x0 + 2 * r) * (y1 - y0 + 2 * r)) / float(W * H)
    for i in range(1, N + 1):
        m = cv2.imread(os.path.join(shot, 'plates', 'm_%05d.png' % i), cv2.IMREAD_GRAYSCALE)
        assert set(np.unique(m).tolist()) <= {0, 255}
        frac = float((m > 127).sum()) / float(W * H)
        assert frac > matte_frac
        assert abs(frac - exp) < 0.01, (frac, exp)
        assert (m[y0:y1, x0:x1] == 255).all()
        assert m[y0 - r - 4, x0] == 0


def test_bg_is_ctrl_without_the_skeleton(built):
    shot, _ = built
    b = cv2.imread(os.path.join(shot, 'plates', 'bg_00001.png'), cv2.IMREAD_COLOR)
    x0, y0, x1, y1 = RECT
    assert (b[y0:y1, x0:x1] == 127).all()
    assert (b[0:20, 0:20] == BEAUTY).all()


def test_face_frames_are_512(built):
    shot, _ = built
    for i in range(1, N + 1):
        f = cv2.imread(os.path.join(shot, 'plates', 'face_%05d.png' % i), cv2.IMREAD_COLOR)
        assert f.shape == (512, 512, 3)


def test_refuses_frame_count_mismatch(tmp_path):
    raw = os.path.join(str(tmp_path), 'plates_raw')
    _write_raw(raw)
    os.remove(os.path.join(raw, 'depth_00005.png'))
    with pytest.raises(ValueError, match='frame counts disagree'):
        SP.build(str(tmp_path), log=lambda m: None)


def test_refuses_missing_matte(tmp_path):
    raw = os.path.join(str(tmp_path), 'plates_raw')
    _write_raw(raw, mattes=False)
    with pytest.raises(ValueError, match='matte frames'):
        SP.build(str(tmp_path), log=lambda m: None)
