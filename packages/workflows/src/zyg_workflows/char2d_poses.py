# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Pose engine for the 2D character gestures: rig names, ROM, schema, validator.

Pure Python (stdlib only) so it imports both in the GUI venv and in Blender's
own interpreter, next to ``blender_scripts/char2d_build.py``.

A gesture file is::

    {"name": "01_open_palm",
     "label": "Open-palm offering",
     "hands": "R",                     # "L" | "R" | "both"
     "meaning": "...",
     "reads_well": ["front", "front45R", "profileR"],
     "keys": [{"name": "rest", "hold_frames": 12, "bones": {}},
              {"name": "apex", "hold_frames": 18,
               "bones": {"upperarm01.R": [-42.0, 0.0, 18.0], ...}}]}

Angles are local XYZ Euler degrees, exactly as ``char2d_build.apply_bones``
feeds them to the pose bones.  A bone that a key does not mention keeps its
idle value (``IDLE_POSE``), so a key only spells out what it changes.

Key count: 2-4 for an animated gesture (2-4 changes per second at 24 fps with
``hold_frames`` in 6..24).  A single key is allowed and means a static hold --
that is what ``00_idle.json`` is; five or more keys is an error.

Left and right are authored explicitly: the ROM table lists every bone of both
sides with its own literal limits and the validator never mirrors anything.
``mirror()`` is offered to *authors* who want to derive the other hand.
"""

import glob
import json
import os
import sys

FPS = 24
HOLD_MIN, HOLD_MAX = 6, 24
MAX_KEYS = 4
HANDS = ('L', 'R', 'both')
VIEWS = ('front', 'front30L', 'front30R', 'front45L', 'front45R', 'profileL', 'profileR', 'back')

# Fingers: 1 = thumb .. 5 = little.  Segment 1 = proximal (MCP), 2 = middle
# (PIP), 3 = distal (DIP); the thumb's are CMC / MCP / IP.
AXES = ('x', 'y', 'z')

# ------------------------------------------------------------------ ROM table
# (x_lo, x_hi), (y_lo, y_hi), (z_lo, z_hi) in degrees.
# X on a finger segment is flexion (+60 on finger2..5 segments makes a fist).
#
# Axis meanings, measured on the MPFB 'default' rig (see the docstring of
# blender_scripts/char2d_render_pose.py for the probe):
#   upperarm01  x = shoulder flexion, +x swings the arm forward and up
#               y = humeral twist,    z = abduction (+40 drops the R arm to the side)
#   lowerarm01/02  x = elbow flexion, split evenly over the two segments
#   wrist       x = flexion/extension
#               y = pronation/supination -- the wrist bone's local Y is the
#                   twist axis: at y = +90 the right palm faces straight up,
#                   at y = -90 straight down, and the finger direction does not
#                   move at all.  Local Z is the (small) radial/ulnar deviation.
#                   This is the one place the rig disagrees with the usual
#                   "z = pron/sup" convention, so the limits are bound to the
#                   axis that actually twists, not to the letter of the name.

_ROM_LEFT = {
    'clavicle.L': ((-15, 15), (-15, 15), (-15, 15)),
    'shoulder01.L': ((-25, 25), (-25, 25), (-25, 25)),
    'upperarm01.L': ((-60, 170), (-90, 90), (-90, 90)),
    'upperarm02.L': ((-60, 170), (-90, 90), (-90, 90)),
    'lowerarm01.L': ((0, 70), (-10, 10), (-10, 10)),
    'lowerarm02.L': ((0, 70), (-10, 10), (-10, 10)),
    'wrist.L': ((-70, 70), (-80, 80), (-25, 25)),
    'metacarpal1.L': ((-10, 10), (-10, 10), (-10, 10)),
    'metacarpal2.L': ((-10, 10), (-10, 10), (-10, 10)),
    'metacarpal3.L': ((-10, 10), (-10, 10), (-10, 10)),
    'metacarpal4.L': ((-10, 10), (-10, 10), (-10, 10)),
    'metacarpal5.L': ((-10, 10), (-10, 10), (-10, 10)),
    'finger1-1.L': ((-20, 50), (-40, 40), (-30, 30)),
    'finger1-2.L': ((-10, 55), (-5, 5), (-5, 5)),
    'finger1-3.L': ((-15, 80), (-5, 5), (-5, 5)),
    'finger2-1.L': ((0, 90), (-20, 20), (-10, 10)),
    'finger2-2.L': ((0, 110), (-5, 5), (-5, 5)),
    'finger2-3.L': ((-10, 80), (-5, 5), (-5, 5)),
    'finger3-1.L': ((0, 90), (-20, 20), (-10, 10)),
    'finger3-2.L': ((0, 110), (-5, 5), (-5, 5)),
    'finger3-3.L': ((-10, 80), (-5, 5), (-5, 5)),
    'finger4-1.L': ((0, 90), (-20, 20), (-10, 10)),
    'finger4-2.L': ((0, 110), (-5, 5), (-5, 5)),
    'finger4-3.L': ((-10, 80), (-5, 5), (-5, 5)),
    'finger5-1.L': ((0, 90), (-20, 20), (-10, 10)),
    'finger5-2.L': ((0, 110), (-5, 5), (-5, 5)),
    'finger5-3.L': ((-10, 80), (-5, 5), (-5, 5)),
}

_ROM_RIGHT = {
    'clavicle.R': ((-15, 15), (-15, 15), (-15, 15)),
    'shoulder01.R': ((-25, 25), (-25, 25), (-25, 25)),
    'upperarm01.R': ((-60, 170), (-90, 90), (-90, 90)),
    'upperarm02.R': ((-60, 170), (-90, 90), (-90, 90)),
    'lowerarm01.R': ((0, 70), (-10, 10), (-10, 10)),
    'lowerarm02.R': ((0, 70), (-10, 10), (-10, 10)),
    'wrist.R': ((-70, 70), (-80, 80), (-25, 25)),
    'metacarpal1.R': ((-10, 10), (-10, 10), (-10, 10)),
    'metacarpal2.R': ((-10, 10), (-10, 10), (-10, 10)),
    'metacarpal3.R': ((-10, 10), (-10, 10), (-10, 10)),
    'metacarpal4.R': ((-10, 10), (-10, 10), (-10, 10)),
    'metacarpal5.R': ((-10, 10), (-10, 10), (-10, 10)),
    'finger1-1.R': ((-20, 50), (-40, 40), (-30, 30)),
    'finger1-2.R': ((-10, 55), (-5, 5), (-5, 5)),
    'finger1-3.R': ((-15, 80), (-5, 5), (-5, 5)),
    'finger2-1.R': ((0, 90), (-20, 20), (-10, 10)),
    'finger2-2.R': ((0, 110), (-5, 5), (-5, 5)),
    'finger2-3.R': ((-10, 80), (-5, 5), (-5, 5)),
    'finger3-1.R': ((0, 90), (-20, 20), (-10, 10)),
    'finger3-2.R': ((0, 110), (-5, 5), (-5, 5)),
    'finger3-3.R': ((-10, 80), (-5, 5), (-5, 5)),
    'finger4-1.R': ((0, 90), (-20, 20), (-10, 10)),
    'finger4-2.R': ((0, 110), (-5, 5), (-5, 5)),
    'finger4-3.R': ((-10, 80), (-5, 5), (-5, 5)),
    'finger5-1.R': ((0, 90), (-20, 20), (-10, 10)),
    'finger5-2.R': ((0, 110), (-5, 5), (-5, 5)),
    'finger5-3.R': ((-10, 80), (-5, 5), (-5, 5)),
}

_ROM_SPINE = {
    'spine01': ((-25, 25), (-25, 25), (-25, 25)),
    'spine02': ((-25, 25), (-25, 25), (-25, 25)),
    'spine03': ((-25, 25), (-25, 25), (-25, 25)),
    'spine04': ((-25, 25), (-25, 25), (-25, 25)),
    'spine05': ((-25, 25), (-25, 25), (-25, 25)),
    'neck01': ((-25, 25), (-25, 25), (-25, 25)),
    'neck02': ((-25, 25), (-25, 25), (-25, 25)),
    'neck03': ((-25, 25), (-25, 25), (-25, 25)),
    'head': ((-35, 35), (-35, 35), (-35, 35)),
    'jaw': ((0, 22), (-5, 5), (-5, 5)),
}

ROM = {}
ROM.update(_ROM_LEFT)
ROM.update(_ROM_RIGHT)
ROM.update(_ROM_SPINE)

RIG = tuple(sorted(ROM))

# Abduction is blocked once the knuckle is flexed: a real MCP joint has almost
# no side-to-side play past ~60 degrees of flexion.
MCP_FLEX_LOCK = 60.0
MCP_ABDUCT_MAX = 8.0
MCP_BONES = frozenset('finger%d-1.%s' % (f, s) for f in (2, 3, 4, 5) for s in ('L', 'R'))

# --------------------------------------------------------------------- idle
# Duplicated from blender_scripts/char2d_build.py (which cannot be imported
# here: it needs bpy).  tests/test_char2d_poses.py imports that module with a
# stub bpy and asserts the two tables are identical.

_FINGER_FAN = {2: 2.0, 3: 0.7, 4: -0.7, 5: -2.0}
_IDLE_CURL = (15.0, 20.0, 8.0)
_IDLE_THUMB_Y = 20.0
_IDLE_THUMB_CURL = (10.0, 6.0)
_IDLE_WRIST_Y = -25.0


def _build_idle():
    idle = {
        'upperarm01.L': (0.0, 0.0, -40.0),
        'upperarm01.R': (0.0, 0.0, 40.0),
        'lowerarm01.L': (8.0, 0.0, 0.0),
        'lowerarm01.R': (8.0, 0.0, 0.0),
        'wrist.L': (0.0, -_IDLE_WRIST_Y, 0.0),
        'wrist.R': (0.0, _IDLE_WRIST_Y, 0.0),
    }
    for finger in (2, 3, 4, 5):
        for segment, curl in zip((1, 2, 3), _IDLE_CURL):
            fan = _FINGER_FAN[finger] if segment == 1 else 0.0
            for side, sign in (('L', 1.0), ('R', -1.0)):
                idle['finger%d-%d.%s' % (finger, segment, side)] = (curl, 0.0, fan * sign)
    for side, sign in (('L', 1.0), ('R', -1.0)):
        idle['finger1-1.%s' % side] = (0.0, _IDLE_THUMB_Y * sign, 0.0)
        for segment, curl in zip((2, 3), _IDLE_THUMB_CURL):
            idle['finger1-%d.%s' % (segment, side)] = (curl, 0.0, 0.0)
    return idle


IDLE_POSE = _build_idle()


def idle_bones():
    """The idle pose as JSON-ready lists."""
    return {name: list(angles) for name, angles in sorted(IDLE_POSE.items())}


# -------------------------------------------------------------------- helpers


def side_of(bone):
    """'L', 'R' or None for a spine/neck/head bone."""
    if bone.endswith('.L'):
        return 'L'
    if bone.endswith('.R'):
        return 'R'
    return None


def mirror(bones):
    """Flip a bone dict to the other side: swap .L/.R and negate Y and Z.

    Authoring aid only -- nothing in validate() mirrors anything.
    """
    out = {}
    for name, angles in bones.items():
        side = side_of(name)
        if side is None:
            out[name] = list(angles)
            continue
        flipped = name[:-2] + ('.R' if side == 'L' else '.L')
        x, y, z = (float(a) for a in angles)
        out[flipped] = [x, -y, -z]
    return out


def sides_used(gesture):
    used = set()
    for key in gesture.get('keys') or []:
        if not isinstance(key, dict):
            continue
        for name in key.get('bones') or {}:
            side = side_of(name)
            if side:
                used.add(side)
    return used


def _declared_sides(hands):
    return {'L', 'R'} if hands == 'both' else {hands}


def check_bone(name, angles):
    """Errors for one bone entry: name known, 3 numbers, inside the ROM."""
    errors = []
    limits = ROM.get(name)
    if limits is None:
        return ['unknown bone %r (not in the MPFB "default" rig table)' % name]
    if not isinstance(angles, (list, tuple)) or len(angles) != 3:
        return ['%s: expected [x, y, z] degrees, got %r' % (name, angles)]
    values = []
    for axis, value in zip(AXES, angles):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            errors.append('%s.%s: %r is not a number' % (name, axis, value))
            values.append(0.0)
            continue
        values.append(float(value))
    if errors:
        return errors
    for axis, value, (lo, hi) in zip(AXES, values, limits):
        if value < lo or value > hi:
            errors.append('%s.%s = %g is outside the ROM [%g, %g]' % (name, axis, value, lo, hi))
    if name in MCP_BONES and values[0] > MCP_FLEX_LOCK and abs(values[1]) > MCP_ABDUCT_MAX:
        errors.append(
            '%s: abduction y = %g is impossible at x = %g (|y| must be '
            '<= %g once flexion passes %g)' % (name, values[1], values[0], MCP_ABDUCT_MAX, MCP_FLEX_LOCK)
        )
    return errors


def validate(gesture):
    """Return a list of human-readable errors; empty means the gesture is legal."""
    errors = []
    if not isinstance(gesture, dict):
        return ['gesture must be a JSON object, got %s' % type(gesture).__name__]

    for field in ('name', 'label', 'hands', 'meaning', 'reads_well', 'keys'):
        if field not in gesture:
            errors.append('missing field %r' % field)
    for field in ('name', 'label', 'meaning'):
        if field in gesture and not isinstance(gesture[field], str):
            errors.append('%s must be a string' % field)

    hands = gesture.get('hands')
    if hands not in HANDS:
        errors.append('hands must be one of %s, got %r' % ('/'.join(HANDS), hands))

    reads = gesture.get('reads_well')
    if not isinstance(reads, list) or not reads:
        errors.append('reads_well must be a non-empty list of view names')
    else:
        for view in reads:
            if view not in VIEWS:
                errors.append('reads_well: unknown view %r (known: %s)' % (view, ', '.join(VIEWS)))

    keys = gesture.get('keys')
    if not isinstance(keys, list) or not keys:
        errors.append('keys must be a non-empty list')
        return errors
    if len(keys) > MAX_KEYS:
        errors.append('%d keys: a gesture holds 2-%d keys (1 = a static hold)' % (len(keys), MAX_KEYS))

    for index, key in enumerate(keys, 1):
        tag = 'key %d' % index
        if not isinstance(key, dict):
            errors.append('%s must be an object' % tag)
            continue
        if not isinstance(key.get('name'), str) or not key['name']:
            errors.append('%s: missing name' % tag)
        else:
            tag = 'key %d (%s)' % (index, key['name'])
        hold = key.get('hold_frames')
        if isinstance(hold, bool) or not isinstance(hold, int):
            errors.append('%s: hold_frames must be an integer number of frames' % tag)
        elif not HOLD_MIN <= hold <= HOLD_MAX:
            errors.append(
                '%s: hold_frames %d outside %d..%d at %d fps '
                '(2-4 changes per second)' % (tag, hold, HOLD_MIN, HOLD_MAX, FPS)
            )
        bones = key.get('bones', {})
        if not isinstance(bones, dict):
            errors.append('%s: bones must be an object (missing bones stay idle)' % tag)
            continue
        for name in sorted(bones):
            for message in check_bone(name, bones[name]):
                errors.append('%s: %s' % (tag, message))

    if hands in HANDS:
        used = sides_used(gesture)
        declared = _declared_sides(hands)
        stray = sorted(used - declared)
        if stray:
            errors.append('hands=%s but the keys pose %s bones' % (hands, '/'.join('.%s' % s for s in stray)))
        idle_only = sorted(declared - used)
        if used and idle_only:
            errors.append('hands=%s but no key poses a %s bone' % (hands, '/'.join('.%s' % s for s in idle_only)))
    return errors


def load_all(directory):
    """{gesture name: gesture dict} for every *.json in directory, sorted by file."""
    out = {}
    for path in sorted(glob.glob(os.path.join(directory, '*.json'))):
        with open(path, 'r', encoding='utf-8') as fh:
            gesture = json.load(fh)
        name = gesture.get('name') if isinstance(gesture, dict) else None
        out[name or os.path.splitext(os.path.basename(path))[0]] = gesture
    return out


if __name__ == '__main__':  # the CLI lives in char2d_poses_cli
    from zyg_workflows.char2d_poses_cli import main as _cli_main

    raise SystemExit(_cli_main(sys.argv))
