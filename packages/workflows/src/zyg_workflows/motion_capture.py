# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Capture source for the motion library: SOMA BVH -> cmu_mb BVH.

A reference video goes through NVIDIA GEM-X (Apache-2.0 code, NVIDIA Open Model
weights) and comes back as a 78-joint SOMA body with a world trajectory, exported
as a BVH.  Movement Studio animates MPFB proxy actors from the 31-joint ``cmu_mb``
rig, so the SOMA clip has to be retargeted onto that skeleton before
``blender_scripts/proxy_actor.py`` can use it.

What the SOMA BVH actually is
-----------------------------
Every joint carries six channels (``Xposition Yposition Zposition Zrotation
Yrotation Xrotation``); the position channels of a non-root joint simply repeat
its ``OFFSET`` (bone lengths are constant), only the root's Hips translation
moves.  The world is Y-up and the units are centimetres (hips at ~113).

The exporter writes every ``OFFSET`` **in its parent bone's local frame with the
bone along +X**.  That means the zero-rotation "rest" pose of the file is *not* a
T-pose: with all rotations zeroed, the spine, both arms and both legs all point
along +X and the figure collapses into a line.  A converter that took the
zero-rotation world positions as its rest skeleton would produce a garbage rig,
so this module takes the rest skeleton from a **reference frame** instead (frame
0, the first video frame) and transfers rotations relative to that frame.

The transfer
------------
Let ``Rs[s](f)`` be the world rotation of SOMA joint ``s`` at frame ``f`` (from a
plain forward kinematics pass) and ``ps[s](f)`` its world position.  Pick the
reference frame ``f0``.  Then

* cmu_mb ``OFFSET[j] = ps[src(j)](f0) - ps[src(parent(j))](f0)`` — the real bone
  vectors of the captured body, in the captured world frame, so the rest pose is
  upright and Y-up;
* cmu_mb world rotation ``Rt[j](f) = Rs[src(j)](f) @ Rs[src(j)](f0)^-1``;
* local rotation ``Rl[j](f) = Rt[parent(j)](f)^-1 @ Rt[j](f)``, written as
  ``Zrotation Yrotation Xrotation`` degrees (intrinsic ZYX, the BVH convention);
* Hips position ``= ps[Hips](f)`` in centimetres.

That identity is exact: ``Rt[j](f) @ OFFSET[child]`` reproduces the source bone
vector ``ps[src(child)](f) - ps[src(j)](f)`` for every bone whose child is rigidly
attached to ``src(j)``.  The only pair where it is an approximation is
``LeftFingerBase -> LeftHandIndex1`` (and its mirror): SOMA hangs the index and
the middle finger off the wrist as siblings, so the index placement drifts by the
middle finger's own curl.  Cosmetic on a 31-joint proxy rig.

The prepended reference frame
-----------------------------
``blender_scripts/proxy_actor.py`` treats BVH frame 1 as the reference pose:
``align_rest()`` turns the MPFB arm bones to the frame-1 direction and applies it
as the rest pose, ``retarget()`` bakes world-space deltas relative to frame 1 and
``build()`` reads the frame-1 hips height to scale the clip.  CMU clips start in a
T-pose; a capture starts wherever the actor was standing.  So the output gets one
extra frame at the front with **all rotations zero** — which, with the rest
skeleton defined above, is exactly the reference frame's pose — and the clip
record carries ``rest_frame: 1`` so proxy_actor can start the motion at frame 2.
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time

import numpy as np
from scipy.spatial.transform import Rotation as Rot

from zyg_workflows import motion_library as ML
from zyg_workflows import paths
from zyg_workflows.bin import exe

ROOT = ML.ROOT
LIBRARY_JSON = ML.LIBRARY_JSON
CAPTURE_DIR = os.path.join(ROOT, 'capture')
CREWS = os.path.dirname(os.path.abspath(__file__))

# The GEM-X install (see $ZYG_MODELS_DIR/gemx/README_ZYG.md).  Its demo
# and tools/gem_capture.py both resolve inputs/soma_assets relative to the CWD,
# so every subprocess here runs with cwd=GEMX_ROOT.
GEMX_ROOT = str(paths.ZYG_MODELS_DIR / 'gemx' / 'GEM-X')
GEMX_PYTHON = os.path.join(GEMX_ROOT, '.venv', 'bin', 'python')
GEMX_DEMO = 'scripts/demo/demo_soma.py'
GEMX_CKPT = 'inputs/pretrained/gem_soma.ckpt'
GEM_CAPTURE = os.path.join(CREWS, 'tools', 'gem_capture.py')
CAPTURE_WORK_ROOT = os.path.join(CREWS, 'output', 'movement', '_capture')

# The cmu_mb hierarchy, exactly as the CMU MotionBuilder-friendly BVH files nest
# it (see data/assets/motion_library/cmu/02_01.bvh).  Depth-first pre-order of
# this tree is motion_library.CMU_MB_JOINTS.
HIERARCHY = (
    'Hips',
    [
        ('LHipJoint', [('LeftUpLeg', [('LeftLeg', [('LeftFoot', [('LeftToeBase', [])])])])]),
        ('RHipJoint', [('RightUpLeg', [('RightLeg', [('RightFoot', [('RightToeBase', [])])])])]),
        (
            'LowerBack',
            [
                (
                    'Spine',
                    [
                        (
                            'Spine1',
                            [
                                ('Neck', [('Neck1', [('Head', [])])]),
                                (
                                    'LeftShoulder',
                                    [
                                        (
                                            'LeftArm',
                                            [
                                                (
                                                    'LeftForeArm',
                                                    [
                                                        (
                                                            'LeftHand',
                                                            [
                                                                ('LeftFingerBase', [('LeftHandIndex1', [])]),
                                                                ('LThumb', []),
                                                            ],
                                                        )
                                                    ],
                                                )
                                            ],
                                        )
                                    ],
                                ),
                                (
                                    'RightShoulder',
                                    [
                                        (
                                            'RightArm',
                                            [
                                                (
                                                    'RightForeArm',
                                                    [
                                                        (
                                                            'RightHand',
                                                            [
                                                                ('RightFingerBase', [('RightHandIndex1', [])]),
                                                                ('RThumb', []),
                                                            ],
                                                        )
                                                    ],
                                                )
                                            ],
                                        )
                                    ],
                                ),
                            ],
                        )
                    ],
                )
            ],
        ),
    ],
)

# cmu_mb joint -> SOMA joint candidates, first match wins.  Both spellings are
# listed: the USD names GEM-X's retarget_utils exports and the snake_case python
# names of the SOMA body model.  An empty tuple means "no source": the joint
# inherits its parent's world rotation (the CMU hip connectors).
NAME_MAP = {
    'Hips': ('Hips', 'c_hips', 'pelvis', 'Pelvis'),
    'LHipJoint': (),
    'LeftUpLeg': ('LeftLeg', 'l_upleg', 'LeftUpLeg'),
    'LeftLeg': ('LeftShin', 'l_lowleg', 'LeftShin'),
    'LeftFoot': ('LeftFoot', 'l_foot'),
    'LeftToeBase': ('LeftToeBase', 'l_ball', 'l_toe'),
    'RHipJoint': (),
    'RightUpLeg': ('RightLeg', 'r_upleg', 'RightUpLeg'),
    'RightLeg': ('RightShin', 'r_lowleg', 'RightShin'),
    'RightFoot': ('RightFoot', 'r_foot'),
    'RightToeBase': ('RightToeBase', 'r_ball', 'r_toe'),
    'LowerBack': ('Spine1', 'c_spine0', 'Spine'),
    'Spine': ('Spine2', 'c_spine1'),
    'Spine1': ('Chest', 'c_spine2', 'c_spine3', 'Spine3'),
    'Neck': ('Neck1', 'c_neck', 'Neck'),
    # SOMA's second neck joint if it has one, otherwise the same joint as Neck
    # (a zero-length bone with an identity local rotation).
    'Neck1': ('Neck2', 'c_neck1', 'Neck1', 'c_neck', 'Neck'),
    'Head': ('Head', 'c_head'),
    'LeftShoulder': ('LeftShoulder', 'l_clavicle'),
    'LeftArm': ('LeftArm', 'l_uparm'),
    'LeftForeArm': ('LeftForeArm', 'l_lowarm'),
    'LeftHand': ('LeftHand', 'l_wrist'),
    'LeftFingerBase': ('LeftHandMiddle1', 'l_middle1'),
    'LeftHandIndex1': ('LeftHandIndex1', 'l_index1'),
    'LThumb': ('LeftHandThumb1', 'l_thumb1'),
    'RightShoulder': ('RightShoulder', 'r_clavicle'),
    'RightArm': ('RightArm', 'r_uparm'),
    'RightForeArm': ('RightForeArm', 'r_lowarm'),
    'RightHand': ('RightHand', 'r_wrist'),
    'RightFingerBase': ('RightHandMiddle1', 'r_middle1'),
    'RightHandIndex1': ('RightHandIndex1', 'r_index1'),
    'RThumb': ('RightHandThumb1', 'r_thumb1'),
}

# Where each End Site's tip comes from, same first-match-wins rule.
END_MAP = {
    'LeftToeBase': ('LeftToeEnd', 'l_ball_end', 'l_toe_end'),
    'RightToeBase': ('RightToeEnd', 'r_ball_end', 'r_toe_end'),
    'Head': ('HeadEnd', 'c_head_end'),
    'LeftHandIndex1': ('LeftHandIndex2', 'l_index2'),
    'RightHandIndex1': ('RightHandIndex2', 'r_index2'),
    'LThumb': ('LeftHandThumb2', 'l_thumb2'),
    'RThumb': ('RightHandThumb2', 'r_thumb2'),
}

_EULER = 'ZYX'


# ------------------------------------------------------------------ BVH parse


def _flatten(node, parent, joints, parents, children):
    name, kids = node
    index = len(joints)
    joints.append(name)
    parents.append(parent)
    children.append([kid[0] for kid in kids])
    for kid in kids:
        _flatten(kid, index, joints, parents, children)


def cmu_mb_skeleton():
    """``(joints, parents)`` of the cmu_mb rig, parents as indices (-1 = root)."""
    joints, parents, children = [], [], []
    _flatten(HIERARCHY, -1, joints, parents, children)
    return joints, parents


def parse_bvh(path):
    """Read a whole BVH: hierarchy, channel layout and every motion frame.

    Returns ``{joints, parents, offsets, channels, base, frames, frame_time,
    motion}``; ``base[j]`` is the column of joint ``j``'s first channel in a
    motion row, ``offsets`` is an (N, 3) array and ``motion`` an (F, C) array.
    """
    with open(path, 'r', encoding='utf-8') as fh:
        lines = fh.read().splitlines()

    joints, parents, offsets, channels = [], [], [], []
    stack = []
    current = None
    index = 0
    while index < len(lines):
        parts = lines[index].split()
        index += 1
        if not parts:
            continue
        head = parts[0]
        if head == 'MOTION':
            break
        if head in ('ROOT', 'JOINT'):
            joints.append(parts[1])
            parents.append(stack[-1] if stack else -1)
            offsets.append(None)
            channels.append([])
            current = len(joints) - 1
        elif head == 'End':
            current = None  # End Site offsets are not joints
        elif head == '{':
            stack.append(current if current is not None else stack[-1])
        elif head == '}':
            stack.pop()
        elif head == 'OFFSET':
            if current is not None and offsets[current] is None:
                offsets[current] = [float(v) for v in parts[1:4]]
        elif head == 'CHANNELS':
            if current is not None:
                channels[current] = parts[2:]

    frames = frame_time = None
    rows = []
    while index < len(lines):
        line = lines[index].strip()
        index += 1
        if not line:
            continue
        if line.startswith('Frames:'):
            frames = int(line.split(':', 1)[1])
        elif line.startswith('Frame Time:'):
            frame_time = float(line.split(':', 1)[1])
        else:
            rows.append([float(v) for v in line.split()])

    base, column = [], 0
    for names in channels:
        base.append(column)
        column += len(names)

    return {
        'joints': joints,
        'parents': parents,
        'offsets': np.array(offsets, dtype=float),
        'channels': channels,
        'base': base,
        'frames': frames if frames is not None else len(rows),
        'frame_time': frame_time,
        'motion': np.array(rows, dtype=float),
    }


def forward_kinematics(bvh):
    """World position and rotation of every joint, every frame.

    ``(positions (F, N, 3), rotations (F, N, 3, 3))``.  BVH rotation channels are
    intrinsic Euler angles applied in channel order, i.e. ``R = Rz @ Ry @ Rx`` for
    the usual ``Zrotation Yrotation Xrotation`` layout.
    """
    joints = bvh['joints']
    parents = bvh['parents']
    offsets = bvh['offsets']
    motion = bvh['motion']
    count = len(joints)
    total = motion.shape[0]

    local_pos = np.tile(offsets, (total, 1, 1))
    angles = np.zeros((total, count, 3))  # z, y, x degrees
    for joint in range(count):
        names = bvh['channels'][joint]
        start = bvh['base'][joint]
        for slot, name in enumerate(names):
            column = motion[:, start + slot]
            if name == 'Xposition':
                local_pos[:, joint, 0] = column
            elif name == 'Yposition':
                local_pos[:, joint, 1] = column
            elif name == 'Zposition':
                local_pos[:, joint, 2] = column
            elif name == 'Zrotation':
                angles[:, joint, 0] = column
            elif name == 'Yrotation':
                angles[:, joint, 1] = column
            elif name == 'Xrotation':
                angles[:, joint, 2] = column

    local_rot = Rot.from_euler(_EULER, angles.reshape(-1, 3), degrees=True).as_matrix().reshape(total, count, 3, 3)

    world_rot = np.empty_like(local_rot)
    world_pos = np.empty((total, count, 3))
    for joint in range(count):
        parent = parents[joint]
        if parent < 0:
            world_rot[:, joint] = local_rot[:, joint]
            world_pos[:, joint] = local_pos[:, joint]
        else:
            world_rot[:, joint] = world_rot[:, parent] @ local_rot[:, joint]
            world_pos[:, joint] = world_pos[:, parent] + np.einsum(
                'fij,fj->fi', world_rot[:, parent], local_pos[:, joint]
            )
    return world_pos, world_rot


def _resolve(candidates, name_to_index):
    for name in candidates:
        if name in name_to_index:
            return name_to_index[name]
    return None


# ------------------------------------------------------------------- converter


def _format(value):
    return '%.6f' % (value + 0.0)


def _write_bvh(path, joints, parents, offsets, ends, frame_time, rows):
    out = ['HIERARCHY']

    def emit(joint, depth):
        pad = '\t' * depth
        label = 'ROOT %s' % joints[joint] if parents[joint] < 0 else 'JOINT %s' % joints[joint]
        out.append(pad + label)
        out.append(pad + '{')
        out.append(
            '%s\tOFFSET %s %s %s'
            % (pad, _format(offsets[joint][0]), _format(offsets[joint][1]), _format(offsets[joint][2]))
        )
        if parents[joint] < 0:
            out.append(pad + '\tCHANNELS 6 Xposition Yposition Zposition Zrotation Yrotation Xrotation')
        else:
            out.append(pad + '\tCHANNELS 3 Zrotation Yrotation Xrotation')
        kids = [k for k in range(len(joints)) if parents[k] == joint]
        for kid in kids:
            emit(kid, depth + 1)
        if not kids:
            tip = ends[joints[joint]]
            out.append(pad + '\tEnd Site')
            out.append(pad + '\t{')
            out.append('%s\t\tOFFSET %s %s %s' % (pad, _format(tip[0]), _format(tip[1]), _format(tip[2])))
            out.append(pad + '\t}')
        out.append(pad + '}')

    emit(0, 0)
    out.append('MOTION')
    out.append('Frames: %d' % len(rows))
    out.append('Frame Time: %s' % _format(frame_time))
    for row in rows:
        out.append(' '.join(_format(v) for v in row))
    with open(path, 'w', encoding='utf-8') as fh:
        fh.write('\n'.join(out) + '\n')


def soma_bvh_to_cmu_mb(src, dst, fps=None):
    """Retarget a SOMA BVH onto the 31-joint cmu_mb skeleton.

    ``src`` is a GEM-X SOMA BVH, ``dst`` the cmu_mb BVH to write.  ``fps``
    overrides the source frame rate (the frame count never changes).  The output
    has one extra frame at the front: the reference pose, all rotations zero.

    Returns ``{frames, source_frames, joints, fps, frame_time, height_units,
    mapped, unmapped, rest_frame, reference_frame}``.
    """
    bvh = parse_bvh(src)
    name_to_index = {name: i for i, name in enumerate(bvh['joints'])}
    world_pos, world_rot = forward_kinematics(bvh)
    total = world_pos.shape[0]
    if total == 0:
        raise ValueError('%s has no motion frames' % src)

    joints, parents = cmu_mb_skeleton()
    if joints != ML.CMU_MB_JOINTS:
        raise AssertionError('HIERARCHY drifted from motion_library.CMU_MB_JOINTS')

    direct = {}
    mapped, unmapped = [], []
    for name in joints:
        found = _resolve(NAME_MAP[name], name_to_index)
        direct[name] = found
        (mapped if found is not None else unmapped).append(name)
    if direct['Hips'] is None:
        raise ValueError(
            '%s has no joint this converter recognises as the hips (looked for %s)' % (src, ', '.join(NAME_MAP['Hips']))
        )

    # An unmapped joint borrows its nearest mapped ancestor: it keeps that
    # ancestor's world rotation, so its own local rotation is the identity.
    source_of = []
    for index, name in enumerate(joints):
        found = direct[name]
        while found is None:
            index = parents[index]
            found = direct[joints[index]]
        source_of.append(found)

    ref = 0
    rest_pos = world_pos[ref]
    rest_rot_inv = np.transpose(world_rot[ref], (0, 2, 1))

    offsets = np.zeros((len(joints), 3))
    for index in range(1, len(joints)):
        offsets[index] = rest_pos[source_of[index]] - rest_pos[source_of[parents[index]]]

    ends = {}
    for index, name in enumerate(joints):
        if any(p == index for p in parents):
            continue
        tip = _resolve(END_MAP.get(name, ()), name_to_index)
        if tip is not None:
            ends[name] = rest_pos[tip] - rest_pos[source_of[index]]
        else:
            # No SOMA tip for this joint: extend the bone by a third of its own
            # length so the End Site still gives Blender a direction.
            ends[name] = offsets[index] / 3.0

    # World rotation of every cmu_mb joint, relative to the reference frame.
    target_rot = np.empty((total, len(joints), 3, 3))
    for index in range(len(joints)):
        source = source_of[index]
        target_rot[:, index] = world_rot[:, source] @ rest_rot_inv[source]

    rows = []
    for frame in range(total):
        row = list(world_pos[frame, direct['Hips']])
        for index in range(len(joints)):
            parent = parents[index]
            local = target_rot[frame, index] if parent < 0 else target_rot[frame, parent].T @ target_rot[frame, index]
            row.extend(Rot.from_matrix(local).as_euler(_EULER, degrees=True))
        rows.append(row)

    # Frame 1: the reference pose, every rotation zero.  With the rest skeleton
    # taken from the reference frame this is the reference frame's pose exactly,
    # which is what proxy_actor's align_rest/retarget want to see.
    rest_row = [rest_pos[direct['Hips']][0], rest_pos[direct['Hips']][1], rest_pos[direct['Hips']][2]] + [0.0] * (
        3 * len(joints)
    )
    rows.insert(0, rest_row)

    source_fps = round(1.0 / bvh['frame_time']) if bvh['frame_time'] else 24
    out_fps = int(fps or source_fps)
    frame_time = round(1.0 / out_fps, 6)

    os.makedirs(os.path.dirname(os.path.abspath(dst)) or '.', exist_ok=True)
    _write_bvh(dst, joints, parents, offsets, ends, frame_time, rows)

    return {
        'frames': len(rows),
        'source_frames': total,
        'joints': len(joints),
        'fps': out_fps,
        'frame_time': float(_format(frame_time)),
        'height_units': float(_format(rest_row[1])),
        'mapped': mapped,
        'unmapped': unmapped,
        'rest_frame': 1,
        'reference_frame': ref,
    }


# -------------------------------------------------------------------- library


def register_capture(
    clip_id,
    bvh_rel_path,
    label,
    tags,
    source_clip,
    licence,
    publishable=False,
    provenance=None,
    may_train=False,
    captured=None,
    engine='gem-x',
):
    """Add (or replace) a clip in ``library.json``'s ``capture`` list.

    ``bvh_rel_path`` is relative to ``motion_library.ROOT``, like the CMU clips'
    ``file``.  The frame count, frame time, fps and hips height are read back
    from the BVH itself so the record cannot disagree with the file.
    """
    path = os.path.join(ROOT, bvh_rel_path)
    header = ML.parse_bvh_header(path)
    if header['joints'] != ML.CMU_MB_JOINTS:
        raise ValueError('%s is not a cmu_mb skeleton' % path)

    record = {
        'id': clip_id,
        'file': bvh_rel_path,
        'label': label,
        'tags': list(tags),
        'frames': header['frames'],
        'frame_time': header['frame_time'],
        'fps': int(round(1.0 / header['frame_time'])),
        'root': 'Hips',
        'joints': len(header['joints']),
        'height_units': ML.root_height(header),
        'rest_frame': 1,
        'source_clip': source_clip,
        'licence': licence,
        'publishable': bool(publishable),
        'may_train': bool(may_train),
        'captured': captured or datetime.date.today().isoformat(),
        'engine': engine,
    }
    if provenance:
        record['provenance'] = dict(provenance)

    with open(LIBRARY_JSON, 'r', encoding='utf-8') as fh:
        library = json.load(fh)
    capture = library.get('capture') or []
    capture = [rec for rec in capture if rec.get('id') != clip_id]
    capture.append(record)
    library['capture'] = capture
    with open(LIBRARY_JSON, 'w', encoding='utf-8') as fh:
        json.dump(library, fh, indent=2)
        fh.write('\n')
    return record


# ------------------------------------------------------------ video -> clip

_SLUG_RE = re.compile(r'[^a-z0-9_]+')
VO_STATES = ('ran', 'fallback_static', 'unknown')


def _slug(clip_id):
    """``capture/qa_sword_short`` -> ``qa_sword_short``."""
    return _SLUG_RE.sub('_', clip_id.rsplit('/', 1)[-1].strip().lower()).strip('_')


def _gemx_env():
    env = dict(os.environ)
    env['PYOPENGL_PLATFORM'] = 'egl'
    env['EGL_PLATFORM'] = 'surfaceless'
    env['VIRTUAL_ENV'] = os.path.join(GEMX_ROOT, '.venv')
    env['PATH'] = os.path.join(GEMX_ROOT, '.venv', 'bin') + os.pathsep + env.get('PATH', '')
    return env


def video_fps(path):
    """Frames per second of ``path``, from ffprobe's ``r_frame_rate``."""
    out = subprocess.run(
        [
            exe('ffprobe'),
            '-v',
            'error',
            '-select_streams',
            'v:0',
            '-show_entries',
            'stream=r_frame_rate',
            '-of',
            'default=noprint_wrappers=1:nokey=1',
            path,
        ],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    num, _, den = out.partition('/')
    return float(num) / float(den or 1)


class _VramSampler(threading.Thread):
    """Poll nvidia-smi every ``interval`` seconds while a child process runs.

    Records the total VRAM in use on the device and, separately, what the child
    process itself holds, so the report can say what the capture really cost.
    """

    def __init__(self, log_path, interval=2.0):
        super().__init__(daemon=True)
        self.log_path = log_path
        self.interval = interval
        self.pid = None
        self.baseline_mib = self._total()
        self.total_peak_mib = self.baseline_mib
        self.process_peak_mib = 0
        self._halt = threading.Event()
        self._lines = []

    @staticmethod
    def _query(args):
        try:
            return subprocess.run([exe('nvidia-smi')] + args, capture_output=True, text=True, timeout=20).stdout
        except (OSError, subprocess.SubprocessError):
            return ''

    def _total(self):
        out = self._query(['--query-gpu=memory.used', '--format=csv,noheader,nounits'])
        values = [int(v) for v in out.split() if v.strip().isdigit()]
        return max(values) if values else 0

    def _sample(self):
        total = self._total()
        self.total_peak_mib = max(self.total_peak_mib, total)
        self._lines.append('T %d %d' % (time.time(), total))
        out = self._query(['--query-compute-apps=pid,used_memory', '--format=csv,noheader,nounits'])
        for line in out.splitlines():
            parts = [p.strip() for p in line.split(',')]
            if len(parts) != 2 or not parts[0].isdigit():
                continue
            self._lines.append('P %s, %s' % (parts[0], parts[1]))
            if self.pid is not None and int(parts[0]) == self.pid:
                self.process_peak_mib = max(self.process_peak_mib, int(parts[1]))

    def run(self):
        while not self._halt.is_set():
            self._sample()
            self._halt.wait(self.interval)

    def stop(self):
        self._halt.set()
        self.join(timeout=10)
        if self.log_path:
            os.makedirs(os.path.dirname(self.log_path), exist_ok=True)
            with open(self.log_path, 'w', encoding='utf-8') as fh:
                fh.write('\n'.join(self._lines) + '\n')

    @property
    def peak_mib(self):
        """What to report: the process's own peak, else the device total."""
        return self.process_peak_mib or self.total_peak_mib


def _run_logged(args, cwd, log_path, sampler=None):
    """Run a subprocess, tee its output to ``log_path``, return (seconds, text)."""
    started = time.time()
    proc = subprocess.Popen(
        args, cwd=cwd, env=_gemx_env(), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, errors='replace'
    )
    if sampler is not None:
        sampler.pid = proc.pid
    text = proc.communicate()[0]
    seconds = time.time() - started
    if log_path:
        os.makedirs(os.path.dirname(log_path), exist_ok=True)
        with open(log_path, 'w', encoding='utf-8') as fh:
            fh.write(text)
    if proc.returncode != 0:
        tail = '\n'.join(text.strip().splitlines()[-25:])
        raise RuntimeError(
            '%s exited %d\n%s' % (os.path.basename(args[1] if len(args) > 1 else args[0]), proc.returncode, tail)
        )
    return seconds, text


# camera.pt is an (F, 4, 4) array of camera matrices.  The identity on every
# frame means visual odometry did not run and the static-camera fallback was
# used, so the recovered "global" translation is camera-relative.
_VO_PROBE = """
import sys, numpy as np, torch
cam = torch.load(sys.argv[1], map_location="cpu", weights_only=False)
if isinstance(cam, dict):
    cam = cam.get("camera", cam.get("R", next(iter(cam.values()))))
if hasattr(cam, "detach"):
    cam = cam.detach().cpu().numpy()
arr = np.asarray(cam, dtype=float)
size = arr.shape[-1]
print("fallback_static"
      if np.allclose(arr.reshape(-1, size, size), np.eye(size), atol=1e-5)
      else "ran")
"""


def _visual_odometry_state(gem_dir, log=print):
    """``ran`` / ``fallback_static`` / ``unknown``, by reading camera.pt itself.

    ``demo_soma.py`` only warns about the static-camera fallback when camera.pt
    is absent, so a re-run over an existing preprocess dir cannot be judged from
    the log — the rotations have to be looked at.
    """
    # the probe runs with cwd=GEMX_ROOT, so the path has to be absolute
    camera = os.path.abspath(os.path.join(gem_dir, 'preprocess', 'camera.pt'))
    if not os.path.isfile(camera):
        return 'unknown'
    try:
        out = subprocess.run(
            [GEMX_PYTHON, '-c', _VO_PROBE, camera],
            cwd=GEMX_ROOT,
            env=_gemx_env(),
            capture_output=True,
            text=True,
            timeout=300,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        log('visual odometry probe failed: %s' % exc)
        return 'unknown'
    state = out.stdout.strip().splitlines()[-1] if out.stdout.strip() else ''
    if state not in VO_STATES:
        log('visual odometry probe said %r (%s)' % (state, out.stderr.strip()[-200:]))
        return 'unknown'
    return state


def capture_from_video(
    video, clip_id, label, tags=(), licence='', publishable=False, may_train=False, fps=None, work_root=None, log=print
):
    """Teach a movement from footage: video -> GEM-X -> registered cmu_mb clip.

    Runs the whole chain in one call — ``demo_soma.py`` inference,
    ``tools/gem_capture.py`` (78-joint SOMA BVH), ``soma_bvh_to_cmu_mb`` and
    ``register_capture`` — and returns the library record plus the timings, the
    VRAM peak and the provenance the record carries.

    ``fps`` defaults to the video's own rate (ffprobe).  ``work_root`` defaults
    to ``output/movement/_capture/<slug>/`` and keeps the GEM-X outputs, the
    logs and the intermediate SOMA BVH: that directory *is* the provenance.
    """
    video = os.path.abspath(video)
    if not os.path.isfile(video):
        raise FileNotFoundError(video)
    slug = _slug(clip_id)
    if not slug:
        raise ValueError('clip_id %r has no usable name' % clip_id)

    work = os.path.abspath(work_root or os.path.join(CAPTURE_WORK_ROOT, slug))
    gem_root = os.path.join(work, 'gem')
    os.makedirs(gem_root, exist_ok=True)

    # demo_soma.py names its output dir after the video file, so give it a copy
    # called <slug>.mp4: the work dir then reads back as one capture.
    source = os.path.join(work, slug + os.path.splitext(video)[1].lower())
    if os.path.abspath(source) != video:
        shutil.copyfile(video, source)

    rate = float(fps) if fps else video_fps(source)
    log('capture %s: %s @ %.3f fps -> %s' % (clip_id, source, rate, work))

    sampler = _VramSampler(os.path.join(work, 'vram.log'))
    sampler.start()
    try:
        demo_seconds, _ = _run_logged(
            [GEMX_PYTHON, GEMX_DEMO, '--video', source, '--output_root', gem_root, '--ckpt', GEMX_CKPT, '--verbose'],
            cwd=GEMX_ROOT,
            log_path=os.path.join(work, 'demo_stdout.log'),
            sampler=sampler,
        )
    finally:
        sampler.stop()
    log(
        '  demo_soma.py: %.1f s, VRAM peak %d MiB (baseline %d MiB)'
        % (demo_seconds, sampler.peak_mib, sampler.baseline_mib)
    )

    gem_dir = next(
        (
            d
            for d in (os.path.join(gem_root, slug), gem_root)
            if os.path.isfile(os.path.join(d, 'hpe_results.pt'))
            or os.path.isfile(os.path.join(d, 'preprocess', 'hpe_results.pt'))
        ),
        None,
    )
    if gem_dir is None:
        raise RuntimeError('no hpe_results.pt under %s after demo_soma.py' % gem_root)

    vo = _visual_odometry_state(gem_dir, log=log)
    soma_bvh = os.path.join(work, slug + '_soma.bvh')
    export_seconds, _ = _run_logged(
        [
            GEMX_PYTHON,
            GEM_CAPTURE,
            '--gem-dir',
            gem_dir,
            '--fps',
            '%.6f' % rate,
            '--out',
            soma_bvh,
            '--clip',
            source,
            '--wall-seconds',
            '%.3f' % demo_seconds,
            '--vram-peak-mib',
            str(sampler.peak_mib),
            '--vram-baseline-mib',
            str(sampler.baseline_mib),
            '--vo',
            vo,
        ],
        cwd=GEMX_ROOT,
        log_path=os.path.join(work, 'gem_capture.log'),
    )
    log('  gem_capture.py: %.1f s -> %s (visual odometry: %s)' % (export_seconds, soma_bvh, vo))

    bvh_rel = 'capture/%s.bvh' % slug
    info = soma_bvh_to_cmu_mb(soma_bvh, os.path.join(ROOT, bvh_rel), fps=int(round(rate)))
    log('  retarget: %d frames, %d joints, rest_frame %d' % (info['frames'], info['joints'], info['rest_frame']))

    provenance = {
        'engine': 'gem-x',
        'gem_dir': gem_dir,
        'work_root': work,
        'source_copy': source,
        'soma_bvh': soma_bvh,
        'soma_frames': info['source_frames'],
        'visual_odometry': vo,
        'fps': rate,
        'demo_seconds': round(demo_seconds, 3),
        'export_seconds': round(export_seconds, 3),
        'vram_peak_mib': sampler.peak_mib,
        'vram_baseline_mib': sampler.baseline_mib,
        'unmapped_joints': info['unmapped'],
    }
    # library.json is written by other tools too (the edit bucket); read it back
    # at write time rather than holding a copy across the minutes above.
    inside = os.path.relpath(video, CREWS)
    record = register_capture(
        clip_id,
        bvh_rel,
        label,
        tags,
        source_clip=inside if not inside.startswith(os.pardir) else video,
        licence=licence,
        publishable=publishable,
        provenance=provenance,
        may_train=may_train,
        engine='gem-x',
    )
    log('  registered %s (%s)' % (record['id'], record['file']))

    return {
        'record': record,
        'provenance': provenance,
        'retarget': info,
        'work_root': work,
        'soma_bvh': soma_bvh,
        'clip_path': os.path.join(ROOT, bvh_rel),
        'seconds': {
            'demo': round(demo_seconds, 3),
            'export': round(export_seconds, 3),
            'total': round(demo_seconds + export_seconds, 3),
        },
        'vram_peak_mib': sampler.peak_mib,
        'visual_odometry': vo,
        'fps': rate,
    }


# ------------------------------------------------------------------- command


def main(argv=None):
    parser = argparse.ArgumentParser(prog='motion_capture', description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)

    cap = sub.add_parser('capture', help='video -> GEM-X -> registered cmu_mb clip')
    cap.add_argument('video')
    cap.add_argument('--id', required=True, dest='clip_id', help='library clip id, e.g. capture/qa_sword_short')
    cap.add_argument('--label', required=True)
    cap.add_argument('--tags', default='', help='comma-separated')
    cap.add_argument('--licence', default='')
    cap.add_argument('--publishable', action='store_true')
    cap.add_argument('--may-train', action='store_true')
    cap.add_argument('--fps', type=float, default=None, help="override the video's own frame rate")
    cap.add_argument('--work-root', default=None)

    args = parser.parse_args(argv)
    out = capture_from_video(
        args.video,
        args.clip_id,
        args.label,
        tags=[t.strip() for t in args.tags.split(',') if t.strip()],
        licence=args.licence,
        publishable=args.publishable,
        may_train=args.may_train,
        fps=args.fps,
        work_root=args.work_root,
    )
    json.dump(out['record'], sys.stdout, indent=2)
    sys.stdout.write('\n')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
