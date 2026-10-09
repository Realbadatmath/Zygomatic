# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Motion library: the clips the scene-bridge actors can play.

Three sources, all indexed by ``data/assets/motion_library/library.json``:

* ``clips`` — CMU mocap BVH under ``data/assets/motion_library/cmu/``, from the
  CMU Graphics Lab Motion Capture Database in Bruce Hahne's MotionBuilder-
  friendly conversion; the joint names match the MPFB ``cmu_mb`` rig.
* ``authored`` — ``auth/*`` keyframe actions built by
  ``blender_scripts/motion_authored.py`` for the verbs mocap does not cover
  (fly, drive, scream).  No file on disk, licence 'in-house'.
* ``capture`` — ``capture/*`` BVH retargeted from a reference video by
  ``motion_capture.py`` (video -> NVIDIA GEM-X -> SOMA BVH -> cmu_mb BVH).
  Each carries its own ``licence``/``publishable``/``may_train`` flags, because
  the licence of a capture is the licence of the video it came from, and a
  ``rest_frame`` — the extra reference frame at the front that proxy_actor uses
  as the rest pose (a capture does not start in a T-pose the way CMU does).

* ``edit`` — ``edit/*`` BVH derived from one of the above by ``motion_edit.py``
  (trim / speed / mirror / loop).  Each carries ``source_clip`` and the ``ops``
  that made it, and inherits the parent's ``licence`` /
  ``publishable`` / ``may_train``, because a derivative is never freer than what
  it came from.

``clips()`` returns all four; ``bvh_clips()``, ``authored_clips()``,
``capture_clips()`` and ``edit_clips()`` return one each.
"""

from __future__ import annotations

import json
import os
import re

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', 'assets', 'motion_library')
LIBRARY_JSON = os.path.join(ROOT, 'library.json')

# The cmu_mb skeleton, in HIERARCHY order.
CMU_MB_JOINTS = [
    'Hips',
    'LHipJoint',
    'LeftUpLeg',
    'LeftLeg',
    'LeftFoot',
    'LeftToeBase',
    'RHipJoint',
    'RightUpLeg',
    'RightLeg',
    'RightFoot',
    'RightToeBase',
    'LowerBack',
    'Spine',
    'Spine1',
    'Neck',
    'Neck1',
    'Head',
    'LeftShoulder',
    'LeftArm',
    'LeftForeArm',
    'LeftHand',
    'LeftFingerBase',
    'LeftHandIndex1',
    'LThumb',
    'RightShoulder',
    'RightArm',
    'RightForeArm',
    'RightHand',
    'RightFingerBase',
    'RightHandIndex1',
    'RThumb',
]

_JOINT_RE = re.compile(r'^\s*(ROOT|JOINT)\s+(\S+)')
_CHANNELS_RE = re.compile(r'^\s*CHANNELS\s+(\d+)\s+(.*)$')


def parse_bvh_header(path):
    """Parse a BVH file's HIERARCHY and MOTION header.

    Returns ``{joints, frames, frame_time, channels}`` where ``channels`` maps
    each joint name to its channel-name list.  Only the header and the first
    motion frame are read, so this is cheap on multi-megabyte clips.
    """
    joints = []
    channels = {}
    frames = None
    frame_time = None
    first_frame = None
    current = None
    in_motion = False

    with open(path, 'r', encoding='utf-8', errors='replace') as fh:
        for line in fh:
            if not in_motion:
                if line.startswith('MOTION'):
                    in_motion = True
                    continue
                m = _JOINT_RE.match(line)
                if m:
                    current = m.group(2)
                    joints.append(current)
                    continue
                m = _CHANNELS_RE.match(line)
                if m and current is not None:
                    channels[current] = m.group(2).split()
                continue
            stripped = line.strip()
            if not stripped:
                continue
            if stripped.startswith('Frames:'):
                frames = int(stripped.split(':', 1)[1])
            elif stripped.startswith('Frame Time:'):
                frame_time = float(stripped.split(':', 1)[1])
            else:
                first_frame = [float(v) for v in stripped.split()]
                break

    return {
        'joints': joints,
        'frames': frames,
        'frame_time': frame_time,
        'channels': channels,
        'first_frame': first_frame,
    }


def root_height(header):
    """Hips Y position on the first (T-pose) frame, in BVH units."""
    frame = header.get('first_frame')
    root = header['joints'][0]
    names = header['channels'][root]
    if not frame or 'Yposition' not in names:
        return None
    return frame[names.index('Yposition')]


def _load():
    with open(LIBRARY_JSON, 'r', encoding='utf-8') as fh:
        return json.load(fh)


def bvh_clips():
    """The retargeted CMU mocap clips (``cmu/*``), in library.json order."""
    return _load()['clips']


def authored_clips():
    """The keyframed actions (``auth/*``) built by blender_scripts/motion_authored.py.

    They have no .bvh file: the pose is code, not captured data.
    """
    return _load().get('authored', [])


def capture_clips():
    """The retargeted video captures (``capture/*``) written by motion_capture.py."""
    return _load().get('capture', [])


def edit_clips():
    """The derived clips (``edit/*``) written by motion_edit.py."""
    return _load().get('edit', [])


def clips():
    """Every motion the actors can play: mocap, authored, captures, edits."""
    lib = _load()
    return lib['clips'] + lib.get('authored', []) + lib.get('capture', []) + lib.get('edit', [])


def clip(clip_id):
    """One clip record by id (``"cmu/02_01"``, ``"auth/fly"``, ``"edit/x"``)."""
    for rec in clips():
        if rec['id'] == clip_id:
            return rec
    return None


def clip_path(clip_id):
    """Absolute path to a clip's .bvh file; None for an authored motion."""
    rec = clip(clip_id)
    if rec is None or 'file' not in rec:
        return None
    return os.path.join(ROOT, rec['file'])


def licence():
    """``(licence_paragraph, acknowledgement)`` for the library's source."""
    lib = _load()
    return lib['licence'], lib['acknowledgement']
