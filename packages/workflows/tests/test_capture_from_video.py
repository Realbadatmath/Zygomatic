# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""One call from footage to a library clip: motion_capture.capture_from_video.

The clip pinned here (``capture/qa_sword_short``) was produced by running

    python -m zyg_workflows.motion_capture capture /tmp/.../qa_short.mp4 \
        --id capture/qa_sword_short --label "sword swing (QA, 4 s)" \
        --tags swing,qa --licence "QA sample ... internal test only"

over a 4 s trim of data/assets/reaction_clips/0tpi77OR.mp4 (23.976 fps).  These
tests check the *product* of that chain — the registered record, the cmu_mb BVH
on disk and the provenance — not GEM-X itself, which needs the GPU.
"""

import os

import pytest

pytest.importorskip('scipy', reason='motion_capture needs scipy.spatial.transform')

from zyg_workflows import motion_capture as MC  # noqa: E402
from zyg_workflows import motion_library as ML  # noqa: E402

if not os.path.isdir(ML.ROOT):
    pytest.skip('the motion library is not in this checkout: %s' % ML.ROOT, allow_module_level=True)

CLIP_ID = 'capture/qa_sword_short'
CLIP_SECONDS = 4.0


@pytest.fixture(scope='module')
def record():
    rec = ML.clip(CLIP_ID)
    assert rec is not None, '%s is not registered in library.json' % CLIP_ID
    return rec


def test_the_capture_is_in_the_library(record):
    assert CLIP_ID in [c['id'] for c in ML.clips()]
    assert CLIP_ID in [c['id'] for c in ML.capture_clips()]
    assert record['file'] == 'capture/qa_sword_short.bvh'
    assert os.path.isfile(ML.clip_path(CLIP_ID))
    assert record['label'] == 'sword swing (QA, 4 s)'
    assert record['tags'] == ['swing', 'qa']


def test_the_file_is_a_cmu_mb_skeleton(record):
    header = ML.parse_bvh_header(ML.clip_path(CLIP_ID))
    assert header['joints'] == ML.CMU_MB_JOINTS
    assert record['joints'] == 31
    assert record['root'] == 'Hips'
    assert header['frames'] == record['frames']
    assert header['frame_time'] == record['frame_time']
    assert record['height_units'] == pytest.approx(ML.root_height(header))


def test_frames_match_the_four_second_source(record):
    """One frame per video frame, plus the prepended rest frame."""
    assert record['rest_frame'] == 1
    expected = CLIP_SECONDS * record['provenance']['fps']
    motion = record['frames'] - 1
    assert abs(motion - expected) <= 0.1 * expected, (motion, expected)
    assert record['frames'] == record['provenance']['soma_frames'] + 1
    assert record['fps'] == round(record['provenance']['fps'])


def test_provenance_names_the_engine_and_the_camera_fallback(record):
    prov = record['provenance']
    assert prov['engine'] == 'gem-x'
    assert record['engine'] == 'gem-x'
    assert prov['visual_odometry'] in MC.VO_STATES
    # The hip connectors are the only cmu_mb joints SOMA has no source for.
    assert prov['unmapped_joints'] == ['LHipJoint', 'RHipJoint']
    assert prov['demo_seconds'] > 0 and prov['export_seconds'] > 0
    assert prov['vram_peak_mib'] > 0
    for key in ('work_root', 'gem_dir', 'soma_bvh', 'source_copy'):
        assert os.path.exists(prov[key]), prov[key]


def test_a_reference_capture_is_not_publishable(record):
    assert record['publishable'] is False
    assert record['may_train'] is False
    assert 'internal test only' in record['licence']
    assert record['source_clip']


def test_capture_from_video_rejects_a_missing_video(tmp_path):
    with pytest.raises(FileNotFoundError):
        MC.capture_from_video(str(tmp_path / 'nope.mp4'), 'capture/nope', 'nope')


def test_slug_comes_from_the_clip_id():
    assert MC._slug('capture/qa_sword_short') == 'qa_sword_short'
    assert MC._slug('capture/Sword Swing!') == 'sword_swing'
