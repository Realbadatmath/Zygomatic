# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Non-destructive edits on the cmu_mb motion clips: trim, speed, mirror, loop.

The motion library ships raw sources — CMU mocap (``cmu/*``), authored actions
(``auth/*``) and video captures (``capture/*``).  A shot rarely wants a source
whole: it wants three seconds out of the middle, at half speed, facing the other
way, looping.  This module produces those derivatives as real BVH files on the
same 31-joint ``cmu_mb`` skeleton, writes them to
``data/assets/motion_library/edit/`` and registers them in ``library.json``
under a fourth bucket, ``edit``.  Nothing about the source is touched, and every
derived record carries ``source_clip`` + ``ops`` so its provenance and its
licence are the parent's.

The four operations, applied in this order:

``trim A B``
    Keep frames ``A..B`` (1-based, inclusive).  If the source carries a
    ``rest_frame`` (captures do — frame 1 is the reference pose
    ``blender_scripts/proxy_actor.py`` aligns against, not animation), that
    frame is re-prepended in front of the trimmed range and the derived record
    keeps ``rest_frame: 1``.

``speed F``
    Resample the channel rows by linear interpolation so the clip plays ``F``x
    faster: output frame ``i`` is the source at time ``i * F``.  ``frame_time``
    is unchanged, so the frame count drops to ``floor((n - 1) / F) + 1``.
    Euler channels are interpolated per channel, which is accurate enough for
    ``F`` in [0.5, 2]; well outside that range, resample the source instead.

``mirror``
    Reflect the clip through the ``x = 0`` plane.  Channels are swapped between
    every ``Left*``/``Right*`` pair (plus ``LHipJoint``/``RHipJoint`` and
    ``LThumb``/``RThumb``); the root X position and the Z and Y rotations are
    negated, X rotation is kept.  That is exactly ``R' = M R M`` for
    ``M = diag(-1, 1, 1)`` with the BVH's intrinsic ZYX Euler order.

    **The HIERARCHY is mirrored too.**  The cmu_mb rest skeleton is not exactly
    symmetric (``LeftUpLeg`` sits at x = +1.65674, ``RightUpLeg`` at -1.61070),
    so swapping only the channels would leave a clip that is 0.05 units off
    everywhere.  Each joint's OFFSET (and each End Site's) is therefore taken
    from its mirror partner with X negated, which makes the identity
    ``FK(mirror(clip))[j] == M @ FK(clip)[mirror(j)]`` exact to float noise.

``loop N``
    Crossfade the last ``N`` frames into the first ``N`` so the clip can be
    cycled.  The output is ``n - N`` frames long: the tail is laid over the head
    with a linear ramp (its root translation offset-corrected so the fade does
    not jump the body sideways), and the frames after the ramp are the source's.
    The result's last frame is the source frame immediately before the one its
    first frame came from, i.e. one frame step apart — the seam is a normal
    frame-to-frame delta rather than a cut.  The tail's Euler angles are
    unwrapped onto the head's branch before blending (179 deg and -179 deg are
    one degree apart, and their arithmetic mean is the opposite pose), so a
    channel may leave the +-180 range by a whole turn — the same rotation,
    measured across the seam with a wrapped difference.

BVH I/O is ``motion_capture``'s: :func:`motion_capture.parse_bvh` reads,
:func:`motion_capture._write_bvh` writes, :func:`motion_capture.forward_kinematics`
proves the mirror.  There is deliberately no second parser here; only End Site
offsets (which ``parse_bvh`` drops, being tips and not joints) get their own
small pass.

CLI::

    python -m zyg_workflows.motion_edit cmu/02_01 --mirror --save edit/walk_mirror \\
        --label "walk (mirrored)"
    python -m zyg_workflows.motion_edit cmu/02_01 --trim 60 300 --speed 0.5 --loop 24 \\
        --save edit/walk_slow_loop --label "walk, slow, looping"
"""

from __future__ import annotations

import argparse
import json
import os

import numpy as np

from zyg_workflows import motion_capture as MC
from zyg_workflows import motion_library as ML

# The channel layout motion_capture._write_bvh emits, and the one every CMU and
# capture BVH in the library already uses.
ROOT_CHANNELS = ['Xposition', 'Yposition', 'Zposition', 'Zrotation', 'Yrotation', 'Xrotation']
JOINT_CHANNELS = ['Zrotation', 'Yrotation', 'Xrotation']

# Rotation channels whose sign flips under a reflection through x = 0, and the
# position channel that does.  (M R M = Rz(-z) Ry(-y) Rx(x) for intrinsic ZYX.)
_MIRROR_NEGATED = {'Zrotation', 'Yrotation', 'Xposition'}

_MIRROR_PAIRS = [('Left', 'Right'), ('LHipJoint', 'RHipJoint'), ('LThumb', 'RThumb')]

EDIT_BUCKET = 'edit'


# --------------------------------------------------------------------- naming


def mirror_name(name):
    """The joint on the other side of the body, or ``name`` if it is central."""
    for left, right in _MIRROR_PAIRS:
        if name == left or name == right:
            return right if name == left else left
        if name.startswith(left) and left in ('Left',):
            return 'Right' + name[len(left) :]
        if name.startswith(right) and right in ('Right',):
            return 'Left' + name[len(right) :]
    return name


def slug_of(save_id):
    """``edit/walk_mirror`` or ``walk_mirror`` -> ``walk_mirror``."""
    slug = save_id.split('/', 1)[1] if '/' in save_id else save_id
    if not slug or '/' in slug or slug.startswith('.'):
        raise ValueError('bad --save target %r' % save_id)
    return slug


# ------------------------------------------------------------------- clip I/O


def _end_sites(path):
    """``{leaf joint name: [x, y, z]}`` for the End Site tips parse_bvh drops."""
    ends = {}
    joints, stack, current, pending = [], [], None, None
    with open(path, 'r', encoding='utf-8') as fh:
        for line in fh:
            parts = line.split()
            if not parts:
                continue
            head = parts[0]
            if head == 'MOTION':
                break
            if head in ('ROOT', 'JOINT'):
                joints.append(parts[1])
                current = len(joints) - 1
            elif head == 'End':
                pending = joints[current]
                current = None
            elif head == '{':
                stack.append(current if current is not None else stack[-1])
            elif head == '}':
                current = stack.pop()
            elif head == 'OFFSET' and pending is not None:
                ends[pending] = [float(v) for v in parts[1:4]]
                pending = None
    return ends


def load_clip(path):
    """Read a BVH into the dict every op in this module takes and returns.

    ``{joints, parents, offsets (N, 3), ends, frame_time, rows (F, C), col}``
    where ``rows`` is always in the canonical layout above and ``col[j]`` is
    joint ``j``'s first column.
    """
    bvh = MC.parse_bvh(path)
    joints = bvh['joints']
    columns, col = [], []
    for index, names in enumerate(bvh['channels']):
        want = ROOT_CHANNELS if bvh['parents'][index] < 0 else JOINT_CHANNELS
        if sorted(names) != sorted(want):
            raise ValueError('%s: joint %s has channels %s, expected %s' % (path, joints[index], names, want))
        col.append(len(columns))
        for name in want:
            columns.append(bvh['motion'][:, bvh['base'][index] + names.index(name)])
    return {
        'joints': joints,
        'parents': list(bvh['parents']),
        'offsets': np.array(bvh['offsets'], dtype=float),
        'ends': _end_sites(path),
        'frame_time': bvh['frame_time'],
        'rows': np.stack(columns, axis=1),
        'col': col,
    }


def channel_names(clip, joint):
    return ROOT_CHANNELS if clip['parents'][joint] < 0 else JOINT_CHANNELS


def column_of(clip, joint, channel):
    """Index of one channel's column in ``clip['rows']``."""
    return clip['col'][joint] + channel_names(clip, joint).index(channel)


def rotation_columns(clip):
    """Every rotation channel's column, in joint order."""
    out = []
    for joint in range(len(clip['joints'])):
        for name in channel_names(clip, joint):
            if name.endswith('rotation'):
                out.append(column_of(clip, joint, name))
    return out


def as_bvh(clip):
    """A dict shaped like :func:`motion_capture.parse_bvh`'s, for FK."""
    return {
        'joints': clip['joints'],
        'parents': clip['parents'],
        'offsets': clip['offsets'],
        'channels': [channel_names(clip, j) for j in range(len(clip['joints']))],
        'base': list(clip['col']),
        'frames': clip['rows'].shape[0],
        'frame_time': clip['frame_time'],
        'motion': clip['rows'],
    }


def write_clip(clip, path):
    MC._write_bvh(
        path, clip['joints'], clip['parents'], clip['offsets'], clip['ends'], clip['frame_time'], clip['rows']
    )


def _derive(clip, rows, offsets=None, ends=None):
    out = dict(clip)
    out['rows'] = np.ascontiguousarray(rows, dtype=float)
    if offsets is not None:
        out['offsets'] = offsets
    if ends is not None:
        out['ends'] = ends
    return out


# ----------------------------------------------------------------- operations


def trim(clip, first, last, rest_frame=None):
    """Keep frames ``first..last`` (1-based, inclusive).

    ``rest_frame`` is the source's reference-frame index (captures use 1); when
    it is given and falls outside the range, that frame is re-prepended so
    proxy_actor still has a rest pose to align against.
    """
    total = clip['rows'].shape[0]
    if not 1 <= first <= last <= total:
        raise ValueError('--trim %d %d outside 1..%d' % (first, last, total))
    rows = clip['rows'][first - 1 : last]
    if rest_frame is not None and not first <= rest_frame <= last:
        rows = np.concatenate([clip['rows'][rest_frame - 1 : rest_frame], rows])
    return _derive(clip, rows)


def speed(clip, factor):
    """Resample so the clip plays ``factor`` times faster; frame_time unchanged."""
    if factor <= 0:
        raise ValueError('--speed must be > 0, got %r' % factor)
    rows = clip['rows']
    total = rows.shape[0]
    if total < 2:
        return _derive(clip, rows)
    count = int((total - 1) // factor) + 1
    times = np.arange(count, dtype=float) * factor
    lower = np.clip(np.floor(times).astype(int), 0, total - 1)
    upper = np.clip(lower + 1, 0, total - 1)
    weight = (times - lower)[:, None]
    return _derive(clip, rows[lower] * (1.0 - weight) + rows[upper] * weight)


def mirror(clip):
    """Reflect the clip through x = 0, skeleton and animation together."""
    joints = clip['joints']
    index_of = {name: i for i, name in enumerate(joints)}
    partner = []
    for _joint, name in enumerate(joints):
        other = mirror_name(name)
        if other not in index_of:
            raise ValueError('%s has no mirror partner %r in this skeleton' % (name, other))
        partner.append(index_of[other])
    for joint in range(len(joints)):
        own, mate = clip['parents'][joint], clip['parents'][partner[joint]]
        if (own < 0) != (mate < 0) or (own >= 0 and partner[own] != mate):
            raise ValueError('skeleton is not left/right symmetric at %s' % joints[joint])

    flip = np.array([-1.0, 1.0, 1.0])
    offsets = np.array([clip['offsets'][partner[j]] * flip for j in range(len(joints))])
    ends = {name: list(np.array(clip['ends'][mirror_name(name)]) * flip) for name in clip['ends']}

    rows = np.empty_like(clip['rows'])
    for joint in range(len(joints)):
        for name in channel_names(clip, joint):
            source = column_of(clip, partner[joint], name)
            target = column_of(clip, joint, name)
            sign = -1.0 if name in _MIRROR_NEGATED else 1.0
            rows[:, target] = clip['rows'][:, source] * sign
    return _derive(clip, rows, offsets=offsets, ends=ends)


def loop(clip, blend):
    """Crossfade the last ``blend`` frames into the first ``blend``."""
    rows = clip['rows']
    total = rows.shape[0]
    if blend < 2 or blend * 2 > total:
        raise ValueError('--loop %d needs 2 <= N <= %d frames' % (blend, total // 2))
    head = rows[:blend].copy()
    tail = rows[total - blend :].copy()

    # Offset-correct the tail's root translation onto the head's, so the fade
    # blends two poses in the same place instead of dragging the body across.
    for channel in ('Xposition', 'Yposition', 'Zposition'):
        column = column_of(clip, 0, channel)
        tail[:, column] += head[0, column] - tail[0, column]
    # Unwrap the tail's Euler angles onto the head's branch: 359 deg and 1 deg
    # are the same pose, and their average is not.
    for column in rotation_columns(clip):
        tail[:, column] -= 360.0 * np.round((tail[:, column] - head[:, column]) / 360.0)

    weight = (np.arange(blend, dtype=float) / (blend - 1))[:, None]
    faded = tail * (1.0 - weight) + head * weight
    return _derive(clip, np.concatenate([faded, rows[blend : total - blend]]))


OPS = ('trim', 'speed', 'mirror', 'loop')


def apply_ops(clip, ops, rest_frame=None):
    """Run ``[{'op': ..., ...}]`` in trim, speed, mirror, loop order.

    Returns ``(clip, rest_frame)`` — the reference frame survives trim (it is
    re-prepended), speed (time 0 resamples to itself) and mirror, but not a
    loop crossfade, which blends the first frame away.
    """
    by_name = {spec['op']: spec for spec in ops}
    unknown = sorted(set(by_name) - set(OPS))
    if unknown:
        raise ValueError('unknown op(s) %s' % ', '.join(unknown))
    for name in OPS:
        spec = by_name.get(name)
        if spec is None:
            continue
        if name == 'trim':
            clip = trim(clip, spec['first'], spec['last'], rest_frame)
            rest_frame = 1 if rest_frame is not None else None
        elif name == 'speed':
            clip = speed(clip, spec['factor'])
        elif name == 'mirror':
            clip = mirror(clip)
        else:
            clip = loop(clip, spec['frames'])
            rest_frame = None
    return clip, rest_frame


# ------------------------------------------------------------------- register


def _read_library():
    with open(ML.LIBRARY_JSON, 'r', encoding='utf-8') as fh:
        return json.load(fh)


def _write_library(lib):
    with open(ML.LIBRARY_JSON, 'w', encoding='utf-8') as fh:
        json.dump(lib, fh, indent=2, ensure_ascii=False)
        fh.write('\n')


def save(clip, slug, source_id, ops, label=None, tags=None, rest_frame=None, index_text=None):
    """Write ``edit/<slug>.bvh`` and register its record in library.json.

    The record is the capture-style one plus ``source_clip`` and ``ops``; the
    licence and the publishable / may_train flags are inherited from the parent
    (from the library's own CMU licence when the parent is a ``cmu/*`` clip, so
    a derivative can never be more permissive than what it came from).

    Returns the record.
    """
    slug = slug_of(slug)
    lib = _read_library()
    parent = None
    for bucket in ('clips', 'authored', 'capture', EDIT_BUCKET):
        for rec in lib.get(bucket, []):
            if rec['id'] == source_id:
                parent = rec
                break
        if parent is not None:
            break
    if parent is None:
        raise ValueError('unknown source clip %r' % source_id)

    directory = os.path.join(ML.ROOT, EDIT_BUCKET)
    os.makedirs(directory, exist_ok=True)
    relative = '%s/%s.bvh' % (EDIT_BUCKET, slug)
    path = os.path.join(ML.ROOT, relative)
    write_clip(clip, path)

    # Read the record's numbers back off the file we just wrote, so the record
    # and the header can never disagree.
    header = ML.parse_bvh_header(path)
    record = {
        'id': '%s/%s' % (EDIT_BUCKET, slug),
        'file': relative,
        'label': label or '%s (edited)' % parent.get('label', slug),
        'tags': list(tags if tags is not None else parent.get('tags', [])),
        'frames': header['frames'],
        'frame_time': header['frame_time'],
        'fps': int(round(1.0 / header['frame_time'])),
        'root': header['joints'][0],
        'joints': len(header['joints']),
        'height_units': ML.root_height(header),
        'source_clip': source_id,
        'ops': list(ops),
        'licence': parent.get('licence', lib['licence']),
        'publishable': bool(parent.get('publishable', True)),
        'may_train': bool(parent.get('may_train', True)),
        'index_text': index_text
        or '%s: %s'
        % (parent.get('index_text', parent.get('label', source_id)), ', '.join(_describe(spec) for spec in ops)),
    }
    if rest_frame is not None:
        record['rest_frame'] = rest_frame

    bucket = [r for r in lib.get(EDIT_BUCKET, []) if r['id'] != record['id']]
    bucket.append(record)
    lib[EDIT_BUCKET] = bucket
    _write_library(lib)
    return record


def _describe(spec):
    if spec['op'] == 'trim':
        return 'frames %d-%d' % (spec['first'], spec['last'])
    if spec['op'] == 'speed':
        return '%gx speed' % spec['factor']
    if spec['op'] == 'loop':
        return 'looped over %d frames' % spec['frames']
    return 'mirrored'


def edit(source_id, ops, save_as, label=None, tags=None, index_text=None):
    """Load ``source_id``, apply ``ops``, save as ``edit/<slug>``.  -> record."""
    source = ML.clip(source_id)
    if source is None:
        raise ValueError('unknown source clip %r' % source_id)
    path = ML.clip_path(source_id)
    if path is None:
        raise ValueError('%r is an authored action and has no BVH to edit' % source_id)
    clip, rest_frame = apply_ops(load_clip(path), ops, source.get('rest_frame'))
    return save(clip, save_as, source_id, ops, label=label, tags=tags, rest_frame=rest_frame, index_text=index_text)


# ------------------------------------------------------------------------ CLI


def _ops_from_args(args):
    ops = []
    if args.trim:
        ops.append({'op': 'trim', 'first': args.trim[0], 'last': args.trim[1]})
    if args.speed is not None:
        ops.append({'op': 'speed', 'factor': args.speed})
    if args.mirror:
        ops.append({'op': 'mirror'})
    if args.loop is not None:
        ops.append({'op': 'loop', 'frames': args.loop})
    return ops


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog='motion_edit',
        description="Trim / speed / mirror / loop a cmu_mb motion clip into the library's 'edit' bucket.",
    )
    parser.add_argument('source', help='source clip id, e.g. cmu/02_01')
    parser.add_argument('--trim', nargs=2, type=int, metavar=('A', 'B'), help='keep frames A..B (1-based, inclusive)')
    parser.add_argument('--speed', type=float, metavar='F', help='play F times faster (0.5-2 is the sane range)')
    parser.add_argument('--mirror', action='store_true', help='reflect through x = 0, swapping left and right')
    parser.add_argument('--loop', type=int, metavar='N', help='crossfade the last N frames into the first N')
    parser.add_argument(
        '--save', required=True, metavar='edit/SLUG', help='where to register it, e.g. edit/walk_mirror'
    )
    parser.add_argument('--label', help='human label for the library record')
    parser.add_argument('--tags', nargs='*', help="override the parent's tags")
    args = parser.parse_args(argv)

    ops = _ops_from_args(args)
    if not ops:
        parser.error('nothing to do: pass at least one of --trim / --speed / --mirror / --loop')
    record = edit(args.source, ops, args.save, label=args.label, tags=args.tags)
    print(json.dumps(record, indent=2, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
