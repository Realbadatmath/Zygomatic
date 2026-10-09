# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""scene_plates.py — Blender raw plates -> the plate sets the two video engines accept.

The Blender exporter writes `plates_raw/` (beauty, 16-bit depth, per-actor mattes,
joints.json, camera.json). Neither wan_vace_service nor wan_animate_service can read that
directly: VACE wants a control frame plus a generate-mask, Wan-Animate wants a pose video,
a face video and a background video. This module is the bridge, and it is the ONLY place
where the raw-plate contract is interpreted.

WHAT THE ACTOR REGION BECOMES. The proxy meshes in the beauty render are placeholders —
their silhouette is right, their surface is not. So the actor region is neutralised to flat
grey 127 (the same inpaint semantics wan_vace_service already uses) and the actor's own
skeleton is drawn back on top as a GUIDE. The skeleton is drawn over the whole frame, NOT
clipped to the matte: where the proxy is thin the guide must still state where the limb is,
or the generator has nothing to follow exactly where it needs it most.

The drawing convention is imported, never re-stated: `_BONES` / `_POSE_COLOURS` from
geom.char_vace (18 bones, BGR, index-matched) and the joint index map from geom.keypoints,
with the same thickness/visibility/circle rules as wan_animate_service.build_pose_frames.

FACES. A proxy mesh has no face, so there is nothing to crop per frame. The character's
canonical face crop is repeated on every frame — a held expression, recorded honestly in
plateset.json as face_source 'canon_static'.
"""

import glob
import json
import os
import shutil
import time

import cv2
import numpy as np

from zyg_workflows.geom.char_vace import _BONES, _POSE_COLOURS
from zyg_workflows.geom.keypoints import P

try:
    from zyg_workflows.canon_service import canon_face_crop
except Exception:  # pragma: no cover
    canon_face_crop = None

SCHEMA = 'zyg.plateset/1'

# the joints wan_animate_service.build_pose_frames marks with a filled white disc
_CIRCLE_JOINTS = (
    'nose',
    'left_eye',
    'right_eye',
    'left_ear',
    'right_ear',
    'left_wrist',
    'right_wrist',
    'left_ankle',
    'right_ankle',
)

_VIS_MIN = 0.4
_GREY = 127
_DILATE_FRAC = 0.03  # mask grows by 3 % of frame height: regenerate the character's
_FACE_SIZE = 512  # edge, not the proxy's


def _draw_skeleton(canvas, pts, th):
    """wan_animate_service.build_pose_frames L229-249, verbatim in behaviour."""
    drawn = 0
    for j, (a, c) in enumerate(_BONES):
        pa, pc = pts[P[a]], pts[P[c]]
        if pa[2] < _VIS_MIN or pc[2] < _VIS_MIN:
            continue
        cv2.line(
            canvas,
            (int(pa[0]), int(pa[1])),
            (int(pc[0]), int(pc[1])),
            _POSE_COLOURS[j % len(_POSE_COLOURS)],
            th,
            cv2.LINE_AA,
        )
        drawn += 1
    for nm in _CIRCLE_JOINTS:
        p = pts[P[nm]]
        if p[2] >= _VIS_MIN:
            cv2.circle(canvas, (int(p[0]), int(p[1])), max(2, th), (255, 255, 255), -1)
    return drawn


def _read_json(path):
    with open(path, 'r', encoding='utf-8') as fh:
        return json.load(fh)


def _char_id_for(actor_id, joints, raw_dir):
    """actor id -> character id. joints.json may name it; plates_raw/actors.json may;
    otherwise the actor IS the character (the usual case: actor 'abel' is char 'abel')."""
    for src in (joints.get('chars') or {}, joints.get('actors') or {}):
        v = src.get(actor_id)
        if isinstance(v, str):
            return v
        if isinstance(v, dict) and v.get('char_id'):
            return v['char_id']
    p = os.path.join(raw_dir, 'actors.json')
    if os.path.isfile(p):
        v = (_read_json(p) or {}).get(actor_id)
        if isinstance(v, str):
            return v
        if isinstance(v, dict) and v.get('char_id'):
            return v['char_id']
    return actor_id


def build(shot_dir, log=print):
    """plates_raw/ -> plates/. Returns the plateset dict (also written as plateset.json)."""
    shot_dir = os.path.abspath(shot_dir)
    raw = os.path.join(shot_dir, 'plates_raw')
    out = os.path.join(shot_dir, 'plates')
    if not os.path.isdir(raw):
        raise FileNotFoundError('no plates_raw in %s' % shot_dir)
    os.makedirs(out, exist_ok=True)

    beauty = sorted(glob.glob(os.path.join(raw, 'beauty_*.png')))
    depth = sorted(glob.glob(os.path.join(raw, 'depth_*.png')))
    joints = _read_json(os.path.join(raw, 'joints.json'))
    camera = _read_json(os.path.join(raw, 'camera.json'))
    jframes = sorted(joints.get('frames') or [], key=lambda d: d.get('f', 0))

    n = len(beauty)
    if not n:
        raise ValueError('no beauty frames in %s' % raw)
    if not (len(depth) == n == len(jframes)):
        raise ValueError('frame counts disagree: beauty=%d depth=%d joints=%d' % (n, len(depth), len(jframes)))

    actor_ids = []
    for fr in jframes:
        for a in fr.get('actors') or {}:
            if a not in actor_ids:
                actor_ids.append(a)

    mattes = {}
    for aid in actor_ids:
        f = sorted(glob.glob(os.path.join(raw, 'matte_%s_*.png' % aid)))
        if len(f) != n:
            raise ValueError('actor %r has %d matte frames, expected %d' % (aid, len(f), n))
        mattes[aid] = f

    im0 = cv2.imread(beauty[0], cv2.IMREAD_COLOR)
    if im0 is None:
        raise ValueError('unreadable beauty frame %s' % beauty[0])
    h, w = im0.shape[:2]
    th = max(
        5, h // 96
    )  # 5 px at 480p (was 3): a thin skeleton stops steering VACE once the actor shrinks (2026-09-20)
    r = max(1, int(round(_DILATE_FRAC * h)))
    kern = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * r + 1, 2 * r + 1))

    chars = {aid: _char_id_for(aid, joints, raw) for aid in actor_ids}
    face_src, face_img = 'none', None
    if actor_ids and canon_face_crop is not None:
        cid = chars[actor_ids[0]]
        try:
            fp = canon_face_crop(cid)
        except Exception as exc:  # noqa: BLE001
            fp, exc_s = None, str(exc)
            log('[plates] canon face crop failed for %s: %s' % (cid, exc_s))
        if fp and os.path.isfile(fp):
            fi = cv2.imread(fp, cv2.IMREAD_COLOR)
            if fi is not None:
                face_img = cv2.resize(fi, (_FACE_SIZE, _FACE_SIZE), interpolation=cv2.INTER_CUBIC)
                face_src = 'canon_static'
    if face_img is None:
        log('[plates] no canon face for %s — face frames omitted' % (chars.get(actor_ids[0]) if actor_ids else '-'))

    cover = {aid: 0.0 for aid in actor_ids}
    for i in range(n):
        bgr = cv2.imread(beauty[i], cv2.IMREAD_COLOR)
        if bgr is None:
            raise ValueError('unreadable beauty frame %s' % beauty[i])
        if bgr.shape[:2] != (h, w):
            raise ValueError('frame %s is %s, expected %dx%d' % (beauty[i], bgr.shape[:2], w, h))
        union = np.zeros((h, w), np.uint8)
        for aid in actor_ids:
            m = cv2.imread(mattes[aid][i], cv2.IMREAD_GRAYSCALE)
            if m is None:
                raise ValueError('unreadable matte %s' % mattes[aid][i])
            m = (m > 127).astype(np.uint8)
            cover[aid] += float(m.sum()) / float(h * w * n)
            union |= m

        bg = bgr.copy()
        bg[union > 0] = _GREY
        ctrl = bg.copy()
        pose = np.zeros((h, w, 3), np.uint8)
        acts = jframes[i].get('actors') or {}
        for aid in actor_ids:
            pts = (acts.get(aid) or {}).get('pts')
            if not pts:
                continue
            pts = np.asarray(pts, np.float32)
            _draw_skeleton(ctrl, pts, th)
            _draw_skeleton(pose, pts, th)

        k = i + 1
        cv2.imwrite(os.path.join(out, 'bg_%05d.png' % k), bg)
        cv2.imwrite(os.path.join(out, 'ctrl_%05d.png' % k), ctrl)
        cv2.imwrite(os.path.join(out, 'pose_%05d.png' % k), pose)
        cv2.imwrite(os.path.join(out, 'm_%05d.png' % k), cv2.dilate(union * 255, kern))
        shutil.copyfile(depth[i], os.path.join(out, 'depth_%05d.png' % k))
        if face_img is not None:
            cv2.imwrite(os.path.join(out, 'face_%05d.png' % k), face_img)

    shutil.copyfile(beauty[0], os.path.join(out, 'still.png'))

    ps = {
        'schema': SCHEMA,
        'shot': os.path.basename(shot_dir),
        'frames': n,
        'fps': camera.get('fps') or joints.get('fps') or 24,
        'width': w,
        'height': h,
        'actors': [
            {'id': aid, 'char_id': chars[aid], 'matte_coverage_mean': round(cover[aid], 6)} for aid in actor_ids
        ],
        'face_source': face_src,
        'ctrl': 'ctrl_%05d.png',
        'mask': 'm_%05d.png',
        'pose': 'pose_%05d.png',
        'face': 'face_%05d.png',
        'bg': 'bg_%05d.png',
        'depth': 'depth_%05d.png',
        'still': 'still.png',
        'built': time.strftime('%Y-%m-%dT%H:%M:%S'),
    }
    with open(os.path.join(out, 'plateset.json'), 'w', encoding='utf-8') as fh:
        json.dump(ps, fh, indent=2)
    log(
        '[plates] %s: %d frames %dx%d, %d actor(s), face_source=%s -> %s'
        % (ps['shot'], n, w, h, len(actor_ids), face_src, out)
    )
    return ps


if __name__ == '__main__':
    import sys

    if len(sys.argv) != 2:
        print('usage: scene_plates.py <shot_dir>')
        raise SystemExit(2)
    build(sys.argv[1])
