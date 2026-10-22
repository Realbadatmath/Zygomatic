#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Shot record for the Blender scene bridge — schema ``zyg.scene_shot/1``.

This module is the single contract every task of the scene-bridge tree reads
or writes.  Stdlib only, so it can be imported from inside Blender as well as
from the kanban server.

FRAMES OF REFERENCE
-------------------
Studio frame (everything in shot.json, and the Architecture Studio drawings):
    +X is to the right, +Y is up, -Z goes INTO the screen (so +Z points back
    out towards the viewer).  Units are metres.  Ground is y = 0 unless the
    drawing's site pad says otherwise.

Blender frame: +X right, +Y into the screen, +Z up.  The conversion is
    to_blender((x, y, z))   -> (x, -z, y)
    from_blender((x, y, z)) -> (x, z, -y)
and every Blender script in this tree must use these two functions rather
than re-deriving the swap.

HEADINGS
--------
An actor's ``ry`` is a heading in degrees about the vertical (+Y) axis.
    ry = 0    -> the actor faces (0, 0, -1), i.e. away from the viewer,
                 into the screen.
    ry = 180  -> the actor faces (0, 0, +1), i.e. out of the screen, towards
                 a camera that sits at positive Z.
Positive ry rotates the facing direction by the usual right-handed rotation
about +Y (counter-clockwise seen from above, from +Y looking down).

RELATIVE PLACEMENT (the ``rel`` block on an effect)
---------------------------------------------------
``rel`` lets an operator say "the campfire goes a metre to his right and two
metres back" without doing any arithmetic.  ``resolve_positions()`` turns it
into an absolute ``p`` and drops the ``rel`` key.  Both anchors use the same
three words, and in both cases the words are meant the way a person on set
says them:

  rel.to = <actor id>
      dx  positive = towards THAT ACTOR'S OWN RIGHT HAND.
      dy  positive = straight up.
      dz  positive = BEHIND the actor, away from the direction they face.
      Vectors: forward = Ry(ry) * (0, 0, -1); back = -forward; up = (0, 1, 0);
      right = cross(up, back).  So an actor at the origin with ry = 0 and
      rel dx = 1, dz = -2 lands the effect at (1, 0, -2): one metre to his
      right and two metres in front of him (further into the screen).
      When the actor faces the camera (ry = 180, the usual framing) "behind
      him" is also "deeper into the shot", which is how the operator reads it.

  rel.to = "camera"
      dx  positive = towards SCREEN RIGHT.
      dy  positive = towards SCREEN UP.
      dz  positive = DEEPER INTO THE SHOT, further away from the camera.
      Vectors: forward = normalise(t - p) (the way the camera looks);
      right = cross(forward, up); the effect lands at
      p_cam + dx*right + dy*up + dz*forward.  So dz = 2, dx = 1 is two metres
      further from the camera and one metre to the right as seen on screen.

The anchor is sampled at the effect's ``start_frame`` (default 1).

CLI
---
    python3 scene_shot.py validate <shot.json>
    python3 scene_shot.py resolve  <shot.json>     # prints the resolved JSON
    python3 scene_shot.py new <id> <drawing.json>  # writes a minimal shot
"""

from __future__ import annotations

import copy
import json
import math
import os
import re
import sys
import tempfile

SCHEMA = 'zyg.scene_shot/1'

_HERE = os.path.dirname(os.path.abspath(__file__))
SHOTS_DIR = os.path.join(_HERE, 'data', 'architecture', 'shots')
from zyg_workflows import paths as _zyg_paths  # noqa: E402

VDB_DIR = str(_zyg_paths.ZYG_DATA_ROOT / 'asset_libraries' / '_originals' / 'jangafx_embergen_vdb')

ID_RE = re.compile(r'^[a-z0-9_-]{1,48}$')

UP = (0.0, 1.0, 0.0)


# --------------------------------------------------------------------------
# frame conversion
# --------------------------------------------------------------------------


def to_blender(v):
    """Studio (x, y, z) -> Blender (x, -z, y)."""
    x, y, z = (float(v[0]), float(v[1]), float(v[2]))
    return (x, -z, y)


def from_blender(v):
    """Blender (x, y, z) -> studio (x, z, -y).  Inverse of to_blender."""
    x, y, z = (float(v[0]), float(v[1]), float(v[2]))
    return (x, z, -y)


# --------------------------------------------------------------------------
# small vector helpers
# --------------------------------------------------------------------------


def _vec3(v):
    return (float(v[0]), float(v[1]), float(v[2]))


def _add(a, b):
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def _sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _scale(a, k):
    return (a[0] * k, a[1] * k, a[2] * k)


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def _norm(a):
    n = math.sqrt(a[0] * a[0] + a[1] * a[1] + a[2] * a[2])
    if n <= 1e-12:
        return (0.0, 0.0, -1.0)
    return (a[0] / n, a[1] / n, a[2] / n)


def _lerp(a, b, u):
    return a + (b - a) * u


def _lerp3(a, b, u):
    return [_lerp(a[0], b[0], u), _lerp(a[1], b[1], u), _lerp(a[2], b[2], u)]


def heading_forward(ry):
    """The direction an actor with heading ``ry`` (degrees) faces."""
    a = math.radians(float(ry))
    c, s = math.cos(a), math.sin(a)
    # Ry * (0, 0, -1) with Ry = [[c,0,s],[0,1,0],[-s,0,c]]
    return (-s, 0.0, -c)


# --------------------------------------------------------------------------
# io
# --------------------------------------------------------------------------


def shot_dir(shot_or_id):
    """Directory that holds a shot's shot.json, blend, plates and renders."""
    sid = shot_or_id.get('id') if isinstance(shot_or_id, dict) else shot_or_id
    return os.path.join(SHOTS_DIR, str(sid))


def load(path):
    """Read a shot.json and validate it.  Raises ValueError on any error."""
    with open(path, 'r', encoding='utf-8') as fh:
        shot = json.load(fh)
    errs = validate(shot)
    if errs:
        raise ValueError('invalid shot %s: %s' % (path, '; '.join(errs)))
    return shot


def save(shot, path=None):
    """Write a shot atomically.  Default path is SHOTS_DIR/<id>/shot.json."""
    if path is None:
        path = os.path.join(shot_dir(shot), 'shot.json')
    d = os.path.dirname(os.path.abspath(path))
    os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=d, prefix='.shot-', suffix='.json')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as fh:
            json.dump(shot, fh, indent=2, sort_keys=False)
            fh.write('\n')
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise
    return path


# --------------------------------------------------------------------------
# validation
# --------------------------------------------------------------------------


def _is_num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _num3(v):
    return isinstance(v, (list, tuple)) and len(v) == 3 and all(_is_num(c) for c in v)


def validate(shot, warnings=None):
    """Return a list of error strings; empty when the shot is usable.

    Non-fatal remarks are appended to ``warnings`` when a list is supplied
    (for example: Wan wants a 4n+1 frame count).
    """
    e = []
    w = warnings if isinstance(warnings, list) else []

    if not isinstance(shot, dict):
        return ['shot is not an object']

    if shot.get('schema') != SCHEMA:
        e.append('schema must be %r, got %r' % (SCHEMA, shot.get('schema')))

    sid = shot.get('id')
    if not isinstance(sid, str) or not ID_RE.match(sid):
        e.append('id %r must match %s' % (sid, ID_RE.pattern))

    drawing = shot.get('drawing')
    if not isinstance(drawing, str) or not drawing:
        e.append('drawing must be a path string')
    elif not os.path.isfile(drawing):
        e.append('drawing does not exist: %s' % drawing)
    else:
        try:
            with open(drawing, 'r', encoding='utf-8') as fh:
                doc = json.load(fh)
        except Exception as exc:  # noqa: BLE001
            e.append('drawing does not parse: %s (%s)' % (drawing, exc))
        else:
            if not isinstance(doc, dict) or not isinstance(doc.get('objects'), list):
                e.append('drawing has no list "objects": %s' % drawing)

    fps = shot.get('fps')
    if not _is_num(fps) or not (1 <= fps <= 120):
        e.append('fps %r must be a number in 1..120' % (fps,))

    frames = shot.get('frames')
    if not isinstance(frames, int) or isinstance(frames, bool) or not (1 <= frames <= 2000):
        e.append('frames %r must be an int in 1..2000' % (frames,))
    elif frames % 4 != 1:
        w.append('frames=%d is not 4n+1; Wan video engines want 4n+1' % frames)

    res = shot.get('resolution')
    if not (
        isinstance(res, (list, tuple))
        and len(res) == 2
        and all(isinstance(c, int) and not isinstance(c, bool) for c in res)
    ):
        e.append('resolution %r must be two ints' % (res,))
    else:
        for c in res:
            if c % 16 != 0:
                e.append('resolution component %d is not a multiple of 16' % c)
            if not (64 <= c <= 4096):
                e.append('resolution component %d out of 64..4096' % c)

    cam = shot.get('camera')
    keys = cam.get('keys') if isinstance(cam, dict) else None
    if not isinstance(keys, list) or not keys:
        e.append('camera.keys must be a non-empty list')
    else:
        for i, k in enumerate(keys):
            if not isinstance(k, dict):
                e.append('camera.keys[%d] is not an object' % i)
                continue
            if not _is_num(k.get('f')):
                e.append('camera.keys[%d].f must be a number' % i)
            if not _num3(k.get('p')):
                e.append('camera.keys[%d].p must be three numbers' % i)
            if not _num3(k.get('t')):
                e.append('camera.keys[%d].t must be three numbers' % i)
            fov = k.get('fov')
            if not _is_num(fov) or not (4 <= fov <= 160):
                e.append('camera.keys[%d].fov %r must be a number in 4..160' % (i, fov))
        fs = [k.get('f') for k in keys if isinstance(k, dict) and _is_num(k.get('f'))]
        if fs != sorted(fs):
            e.append('camera.keys must be sorted by f')

    sun = shot.get('sun')
    if sun is not None:
        if not isinstance(sun, dict) or not _is_num(sun.get('hour')):
            e.append('sun.hour must be a number')
        elif not (0 <= sun['hour'] <= 24):
            e.append('sun.hour %r out of 0..24' % (sun['hour'],))

    actor_ids = []
    actors = shot.get('actors', [])
    if not isinstance(actors, list):
        e.append('actors must be a list')
        actors = []
    for i, a in enumerate(actors):
        if not isinstance(a, dict):
            e.append('actors[%d] is not an object' % i)
            continue
        aid = a.get('id')
        if not isinstance(aid, str) or not ID_RE.match(aid):
            e.append('actors[%d].id %r must match %s' % (i, aid, ID_RE.pattern))
        elif aid in actor_ids:
            e.append('duplicate actor id %r' % aid)
        else:
            actor_ids.append(aid)
        h = a.get('height_m')
        if not _is_num(h) or not (0.3 <= h <= 3.0):
            e.append('actors[%d].height_m %r must be a number in 0.3..3.0' % (i, h))
        path = a.get('path')
        if not isinstance(path, list) or not path:
            e.append('actors[%d].path must be a non-empty list' % i)
            continue
        pf = []
        for j, k in enumerate(path):
            if not isinstance(k, dict):
                e.append('actors[%d].path[%d] is not an object' % (i, j))
                continue
            if not _is_num(k.get('f')):
                e.append('actors[%d].path[%d].f must be a number' % (i, j))
            else:
                pf.append(k['f'])
            if not _num3(k.get('p')):
                e.append('actors[%d].path[%d].p must be three numbers' % (i, j))
            if not _is_num(k.get('ry', 0)):
                e.append('actors[%d].path[%d].ry must be a number' % (i, j))
        if pf != sorted(pf):
            e.append('actors[%d].path must be sorted by f' % i)

    eff_ids = []
    effects = shot.get('effects', [])
    if not isinstance(effects, list):
        e.append('effects must be a list')
        effects = []
    for i, fx in enumerate(effects):
        if not isinstance(fx, dict):
            e.append('effects[%d] is not an object' % i)
            continue
        fid = fx.get('id')
        if not isinstance(fid, str) or not ID_RE.match(fid):
            e.append('effects[%d].id %r must match %s' % (i, fid, ID_RE.pattern))
        elif fid in eff_ids:
            e.append('duplicate effect id %r' % fid)
        else:
            eff_ids.append(fid)
        pack = fx.get('pack')
        if not isinstance(pack, str) or not pack:
            e.append('effects[%d].pack must be a file name' % i)
        elif os.path.basename(pack) != pack:
            e.append('effects[%d].pack %r must be a bare file name' % (i, pack))
        elif not os.path.isfile(os.path.join(VDB_DIR, pack)):
            e.append('effects[%d].pack %r not found in %s' % (i, pack, VDB_DIR))
        size = fx.get('size_m')
        if not _is_num(size) or not (0.1 <= size <= 500):
            e.append('effects[%d].size_m %r must be a number in 0.1..500' % (i, size))
        rel = fx.get('rel')
        if rel is None:
            if not _num3(fx.get('p')):
                e.append('effects[%d] needs p (three numbers) or rel' % i)
        else:
            if not isinstance(rel, dict):
                e.append('effects[%d].rel is not an object' % i)
            else:
                to = rel.get('to')
                if to != 'camera' and to not in actor_ids:
                    e.append('effects[%d].rel.to %r is not an actor id or "camera"' % (i, to))
                for ax in ('dx', 'dy', 'dz'):
                    if not _is_num(rel.get(ax, 0)):
                        e.append('effects[%d].rel.%s must be a number' % (i, ax))

    vid = shot.get('video')
    if vid is not None:
        if not isinstance(vid, dict):
            e.append('video must be an object')
        elif vid.get('engine') not in ('vace', 'animate'):
            e.append('video.engine %r must be "vace" or "animate"' % (vid.get('engine'),))

    return e


# --------------------------------------------------------------------------
# sampling
# --------------------------------------------------------------------------


def _bracket(keys, f):
    """Return (a, b, u) for linear interpolation, holding outside the range."""
    f = float(f)
    if f <= keys[0]['f']:
        return keys[0], keys[0], 0.0
    if f >= keys[-1]['f']:
        return keys[-1], keys[-1], 0.0
    for i in range(len(keys) - 1):
        a, b = keys[i], keys[i + 1]
        if a['f'] <= f <= b['f']:
            span = float(b['f']) - float(a['f'])
            u = 0.0 if span <= 0 else (f - float(a['f'])) / span
            return a, b, u
    return keys[-1], keys[-1], 0.0


def camera_at(shot, f):
    """Camera {p, t, fov} at frame ``f``; linear between keys, held outside."""
    keys = shot['camera']['keys']
    a, b, u = _bracket(keys, f)
    return {
        'p': _lerp3(a['p'], b['p'], u),
        't': _lerp3(a['t'], b['t'], u),
        'fov': _lerp(float(a.get('fov', 50)), float(b.get('fov', 50)), u),
    }


def _find_actor(shot, actor):
    if isinstance(actor, dict):
        return actor
    for a in shot.get('actors', []):
        if a.get('id') == actor:
            return a
    raise KeyError('no actor %r in shot %r' % (actor, shot.get('id')))


def actor_at(shot, actor, f):
    """Actor {p, ry} at frame ``f``; linear between path keys, held outside."""
    a = _find_actor(shot, actor)
    keys = a['path']
    ka, kb, u = _bracket(keys, f)
    return {
        'p': _lerp3(ka['p'], kb['p'], u),
        'ry': _lerp(float(ka.get('ry', 0.0)), float(kb.get('ry', 0.0)), u),
    }


# --------------------------------------------------------------------------
# relative placement
# --------------------------------------------------------------------------


def actor_basis(ry):
    """(right, up, back) for an actor with heading ``ry``.

    back points behind the actor; right is the actor's own right hand.
    """
    forward = heading_forward(ry)
    back = _scale(forward, -1.0)
    right = _cross(UP, back)
    return right, UP, back


def camera_basis(cam):
    """(right, up, forward) for a camera key — screen right/up, into the shot."""
    forward = _norm(_sub(_vec3(cam['t']), _vec3(cam['p'])))
    right = _cross(forward, UP)
    n = math.sqrt(sum(c * c for c in right))
    if n > 1e-12:
        right = _scale(right, 1.0 / n)
    up = _cross(right, forward)
    return right, up, forward


def resolve_positions(shot):
    """Deep copy of ``shot`` with every effect's ``rel`` turned into a ``p``.

    See the module docstring for the sign conventions.  The anchor is sampled
    at the effect's ``start_frame`` (default 1).
    """
    out = copy.deepcopy(shot)
    for fx in out.get('effects', []):
        rel = fx.get('rel')
        if not rel:
            continue
        f = fx.get('start_frame', 1)
        dx = float(rel.get('dx', 0.0))
        dy = float(rel.get('dy', 0.0))
        dz = float(rel.get('dz', 0.0))
        if rel.get('to') == 'camera':
            cam = camera_at(out, f)
            right, up, forward = camera_basis(cam)
            anchor = _vec3(cam['p'])
            depth = forward  # dz positive = deeper into the shot
        else:
            st = actor_at(out, rel['to'], f)
            right, up, back = actor_basis(st['ry'])
            anchor = _vec3(st['p'])
            depth = back  # dz positive = behind the actor
        p = _add(anchor, _add(_scale(right, dx), _add(_scale(up, dy), _scale(depth, dz))))
        fx['p'] = [p[0], p[1], p[2]]
        fx.pop('rel', None)
    return out


# --------------------------------------------------------------------------
# construction
# --------------------------------------------------------------------------


def new_shot(id, drawing, **kw):
    """A minimal valid shot dict carrying the contract's defaults."""
    shot = {
        'schema': SCHEMA,
        'id': id,
        'name': kw.pop('name', id.replace('_', ' ').replace('-', ' ').strip().title()),
        'drawing': os.path.abspath(drawing),
        'fps': 24,
        'frames': 49,
        'resolution': [832, 480],
        'camera': {'keys': [{'f': 1, 'p': [14.0, 1.7, 18.0], 't': [4.0, 1.5, 4.0], 'fov': 50.0}]},
        'sun': {'hour': 14.0},
        'actors': [],
        'effects': [],
        'render': {
            'draft': {'width': 320, 'height': 180, 'engine': 'BLENDER_WORKBENCH'},
            'full': {'samples': 64, 'denoise': 1},
        },
        'video': {'engine': 'vace', 'prompt': '', 'steps': 20, 'seed': 7},
    }
    shot.update(kw)
    return shot


if __name__ == '__main__':  # the CLI lives in scene_shot_cli
    from zyg_workflows.scene_shot_cli import _main as _cli_main

    raise SystemExit(_cli_main(sys.argv))
