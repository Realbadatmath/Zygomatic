# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""track_plates.py — a pose track rasterised into VACE control plates (2026-09-02).

RUN:
    python -m zyg_workflows.geom.track_plates <track_dir_or_track.json> [--size 832x480]
                                [--modes depth,normal,skeleton,seg,composite]

WHAT THIS IS FOR. wan_vace_service builds every control frame as
`still*(1-mask) + 127*mask`, so wherever VACE is asked to generate it is handed a
CONSTANT — measured consequence: prop fidelity ~0 by frame 80, identity decay by
frame 200, the model re-inventing whatever the constant hides in every context
window (geom/vace_control.py header). geom.anny_animate closes that for a body
lerped between two fitted poses. This closes it for a body that was actually
TRACKED: every frame re-states the character's own geometry, so there is nothing
for the model to remember and nothing for it to forget.

WHAT IT DRAWS, from geom.pose_track's track.json + track_arrays.npz:

  depth      painter's algorithm over the 18439-vertex MHR mesh, near = white —
             the same convention and the same algorithm as anny_animate.render_depth,
             except the camera is the estimator's real pinhole rather than a fitted
             orthographic one, so nothing has to be re-solved.
  normal     camera-space normals, the usual (n+1)/2 encoding, painted with the same
             depth ordering. Normals state SURFACE where depth states DISTANCE, and
             the two disagree exactly where the mesh folds — which is where a video
             model most needs telling.
  skeleton   the 18 bones of geom.char_vace._BONES in its OpenPose colour order, so a
             plate from this module and a plate from char_vace are the same modality;
             joints come from the track's own 2D keypoints (MHR70 -> BlazePose names
             via pose_track.MHR70_TO_POSE), not from a re-detection.
  seg        the tracked subject's mask, white on black.
  composite  depth as the base with the skeleton drawn over it — one plate carrying
             both the volume and the joint statement.

THE AUDIT IS THE POINT, exactly as in vace_control: a control directory that is
still flat grey looks completely normal on disk, so the grey fraction is MEASURED
per mode and `main()` exits non-zero if any requested mode came out constant.

OUTPUT. `<track_dir>/plates_<mode>/ctrl_%05d.png` — the folder S01 passes as
`control_dir=` and S05's picker lists. Frame numbering is the TRACK's index (the
fitted frames, in order), which is what track.json's `frames[].i` refers to.
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import sys

import numpy as np

try:
    import cv2
except Exception:  # pragma: no cover
    cv2 = None
import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)


_CREWS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _CREWS not in sys.path:
    sys.path.insert(0, _CREWS)

MODES = ('depth', 'normal', 'skeleton', 'seg', 'composite')


def _load(track_arg: str):
    p = track_arg if track_arg.endswith('.json') else os.path.join(track_arg, 'track.json')
    with open(p, encoding='utf-8') as fh:
        tr = json.load(fh)
    d = os.path.dirname(os.path.abspath(p))
    npz_path = tr.get('arrays_npz')
    if not npz_path or not os.path.isfile(npz_path):
        npz_path = os.path.join(d, 'track_arrays.npz')
    arrays = np.load(npz_path)
    faces_npy = tr.get('faces_npy')
    if not faces_npy or not os.path.isfile(faces_npy):
        faces_npy = os.path.join(tr.get('arrays_dir') or d, 'faces.npy')
    faces = np.load(faces_npy).astype(np.int32)
    return tr, arrays, faces, d


def project(verts: np.ndarray, cam_t: np.ndarray, focal: float, W: int, H: int) -> tuple[np.ndarray, np.ndarray]:
    """MHR camera-space vertices -> pixel coords + depth.

    The model is the estimator's own (sam_3d_body camera_head.perspective_projection
    with the default intrinsics of prepare_batch: f = hypot(W,H), principal point at
    the image centre). pose_track writes a self-check of this into track.json —
    measured 0.0000 px against the estimator's `pred_keypoints_2d`, so this is the
    projection, not an approximation of it.
    """
    p = verts.astype(np.float64) + cam_t.astype(np.float64)
    z = np.clip(p[:, 2], 1e-4, None)
    x = focal * p[:, 0] / z + W / 2.0
    y = focal * p[:, 1] / z + H / 2.0
    return np.stack([x, y], -1), p[:, 2]


def _front_facing(verts, faces):
    """Faces whose normal points back towards the camera (camera looks down +z)."""
    v = verts.astype(np.float64)
    n = np.cross(v[faces[:, 1]] - v[faces[:, 0]], v[faces[:, 2]] - v[faces[:, 0]])
    return n[:, 2] < 0


def render_depth(verts, faces, cam_t, focal, W, H):
    """Painter's algorithm, near = white. Same convention as anny_animate.render_depth.

    ONE DELIBERATE DIFFERENCE. anny_animate normalises the shading over the 2nd-98th
    percentile of ALL vertex depths — front and back surfaces together. For a body
    facing the camera that is most of a metre of range of which only the near ~15 cm
    is ever visible, so the plate comes out almost flat white and the depth GRADIENT,
    which is the whole signal a video model reads off a depth control, is compressed
    into a few levels. The range here is taken over front-facing faces only, so the
    contrast lands on the surface that is actually drawn.
    """
    pts2, z = project(verts, cam_t, focal, W, H)
    fz = z[faces].mean(axis=1)
    order = np.argsort(-fz)  # far first, near painted last
    front = _front_facing(verts, faces)
    ref = fz[front] if front.sum() > 32 else fz
    lo, hi = np.percentile(ref, 2), np.percentile(ref, 98)
    shade = (1.0 - np.clip((fz - lo) / max(hi - lo, 1e-6), 0, 1)) * 235 + 20
    img = np.zeros((H, W), np.uint8)
    quads = pts2.astype(np.int32)[faces]
    for fi in order:
        q = quads[fi]
        if q[:, 0].max() < 0 or q[:, 0].min() >= W:
            continue
        if q[:, 1].max() < 0 or q[:, 1].min() >= H:
            continue
        cv2.fillConvexPoly(img, q, int(shade[fi]))
    return img


def render_normal(verts, faces, cam_t, focal, W, H):
    """Camera-space face normals as BGR, (n+1)/2, painted back-to-front."""
    pts2, z = project(verts, cam_t, focal, W, H)
    v = verts.astype(np.float64)
    a, b, c = v[faces[:, 0]], v[faces[:, 1]], v[faces[:, 2]]
    n = np.cross(b - a, c - a)
    ln = np.linalg.norm(n, axis=1, keepdims=True)
    n = n / np.maximum(ln, 1e-9)
    # face the camera: MHR camera space looks down +z, so flip normals pointing away.
    # Only back faces are flipped, and they are overpainted by the front ones anyway —
    # this is so an occasional inverted winding does not punch a dark hole in the plate.
    n[n[:, 2] > 0] *= -1.0
    col = np.clip(((n + 1.0) * 0.5) * 255.0, 0, 255)
    col = col[:, ::-1]  # RGB -> BGR for cv2
    fz = z[faces].mean(axis=1)
    order = np.argsort(-fz)
    img = np.zeros((H, W, 3), np.uint8)
    quads = pts2.astype(np.int32)[faces]
    for fi in order:
        q = quads[fi]
        if q[:, 0].max() < 0 or q[:, 0].min() >= W:
            continue
        if q[:, 1].max() < 0 or q[:, 1].min() >= H:
            continue
        cv2.fillConvexPoly(img, q, tuple(int(x) for x in col[fi]))
    return img


def render_skeleton(kp2, name_to_mhr, W, H, base=None):
    """The 18 char_vace bones, in its colour order, from the track's own 2D keypoints."""
    from .char_vace import _BONES, _POSE_COLOURS

    img = (
        np.zeros((H, W, 3), np.uint8)
        if base is None
        else (base if base.ndim == 3 else cv2.cvtColor(base, cv2.COLOR_GRAY2BGR)).copy()
    )
    th = max(3, H // 160)
    painted = 0
    for i, (p, q) in enumerate(_BONES):
        if p not in name_to_mhr or q not in name_to_mhr:
            continue
        a = kp2[name_to_mhr[p]]
        b = kp2[name_to_mhr[q]]
        if not (-W <= a[0] <= 2 * W and -H <= a[1] <= 2 * H):
            continue
        if not (-W <= b[0] <= 2 * W and -H <= b[1] <= 2 * H):
            continue
        cv2.line(
            img, (int(a[0]), int(a[1])), (int(b[0]), int(b[1])), _POSE_COLOURS[i % len(_POSE_COLOURS)], th, cv2.LINE_AA
        )
        painted += 1
    for _name, mi in name_to_mhr.items():
        a = kp2[mi]
        if -W <= a[0] <= 2 * W and -H <= a[1] <= 2 * H:
            cv2.circle(img, (int(a[0]), int(a[1])), max(2, th), (255, 255, 255), -1)
    return img, painted


def build(track_arg: str, *, modes=('depth', 'normal', 'skeleton', 'seg', 'composite'), size=None, log=print) -> dict:
    """Rasterise every requested mode. Returns {mode: {dir, frames, grey_*}}."""
    if cv2 is None:
        raise RuntimeError('cv2 required')
    from . import vace_control

    tr, arrays, faces, root = _load(track_arg)
    W, H = size or tr['size']
    src_W, src_H = tr['size']
    verts = arrays['vertices']
    kp2 = arrays['keypoints_2d'].astype(np.float64)
    cam_t = arrays['cam_t']
    focal = arrays['focal']
    n = verts.shape[0]
    name_to_mhr = tr['mhr70_to_pose_names']
    # the projection is defined in the SOURCE frame; if plates are asked for at a
    # different render size, project there instead of resampling a raster
    if (W, H) != (src_W, src_H):
        ar_src, ar_out = src_W / float(src_H), W / float(H)
        if abs(ar_src - ar_out) / ar_src > 0.01:
            raise SystemExit(
                'plate size %dx%d has a different aspect ratio from the tracked '
                '%dx%d; a non-uniform rescale would shear the projection, and the '
                'right fix is to re-track at the render size, not to squash the plate' % (W, H, src_W, src_H)
            )
        focal = focal * (float(W) / float(src_W))
    masks = sorted(glob.glob(os.path.join(tr.get('masks_dir') or '', 'm_*.png'))) if tr.get('masks_dir') else []

    report: dict = {'track': os.path.join(root, 'track.json'), 'size': [W, H], 'frames': n, 'modes': {}}
    tmp = os.path.join(root, '_plate_frames')
    for mode in modes:
        if mode not in MODES:
            raise SystemExit('unknown mode %r (want %s)' % (mode, ','.join(MODES)))
        os.makedirs(tmp, exist_ok=True)
        for old in glob.glob(os.path.join(tmp, 'frame_*.png')):
            os.remove(old)
        painted_total = 0
        for k in range(n):
            if mode == 'depth':
                img = render_depth(verts[k], faces, cam_t[k], float(focal[k]), W, H)
            elif mode == 'normal':
                img = render_normal(verts[k], faces, cam_t[k], float(focal[k]), W, H)
            elif mode == 'skeleton':
                img, pt = render_skeleton(kp2[k] * (W / float(src_W)), name_to_mhr, W, H)
                painted_total += pt
            elif mode == 'seg':
                img = np.zeros((H, W), np.uint8)
                if k < len(masks):
                    m = cv2.imread(masks[k], cv2.IMREAD_GRAYSCALE)
                    if m is not None:
                        img = cv2.resize(m, (W, H), interpolation=cv2.INTER_NEAREST)
            else:  # composite
                d = render_depth(verts[k], faces, cam_t[k], float(focal[k]), W, H)
                img, pt = render_skeleton(kp2[k] * (W / float(src_W)), name_to_mhr, W, H, base=d)
                painted_total += pt
            cv2.imwrite(os.path.join(tmp, 'frame_%05d.png' % k), img)

        out_dir = os.path.join(root, 'plates_%s' % mode)
        r = vace_control.build(tmp, out_dir, frames=n, size=(W, H))
        a = vace_control.audit(out_dir)
        report['modes'][mode] = {
            'dir': out_dir,
            'frames': r['frames'],
            'grey_fraction_mean': r['grey_fraction_mean'],
            'grey_fraction_max': r['grey_fraction_max'],
            'audit_ok': a['ok'],
            'audit_verdict': a['verdict'],
            'bones_painted_mean': (round(painted_total / max(n, 1), 2) if mode in ('skeleton', 'composite') else None),
        }
        log(
            '  %-9s %3d frames  grey %.4f%%  %s' % (mode, r['frames'], r['grey_fraction_mean'] * 100, a['verdict'][:48])
        )
    for old in glob.glob(os.path.join(tmp, 'frame_*.png')):
        os.remove(old)
    try:
        os.rmdir(tmp)
    except OSError as _exc:
        _zyg_log.debug('temp frame dir removal skipped: %s', _exc)

    rp = os.path.join(root, 'plates_report.json')
    with open(rp, 'w', encoding='utf-8') as fh:
        json.dump(report, fh, indent=1)
    log('  report: %s' % rp)
    return report


def contact_strip(track_arg: str, mode='composite', out=None, n=4):
    """Four evenly-spaced plates side by side — the human check that the plate is
    the character and not, say, a mesh projected off-frame."""
    tr, _a, _f, root = _load(track_arg)
    d = os.path.join(root, 'plates_%s' % mode)
    hits = sorted(glob.glob(os.path.join(d, 'ctrl_*.png')))
    if not hits:
        return None
    idxs = [int(round(i * (len(hits) - 1) / max(n - 1, 1))) for i in range(n)]
    imgs = []
    for i in idxs:
        im = cv2.imread(hits[i])
        if im is None:
            continue
        if im.ndim == 2:
            im = cv2.cvtColor(im, cv2.COLOR_GRAY2BGR)
        imgs.append(cv2.resize(im, None, fx=320.0 / im.shape[0], fy=320.0 / im.shape[0]))
    if not imgs:
        return None
    p = out or os.path.join(root, 'plates_%s_strip.png' % mode)
    cv2.imwrite(p, np.concatenate(imgs, axis=1))
    return p


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('track')
    ap.add_argument('--modes', default='depth,normal,skeleton,seg,composite')
    ap.add_argument('--size', default=None, help='WxH of the render, e.g. 832x480')
    ap.add_argument('--strip', default='composite', help='mode to write a contact strip for, or "" for none')
    a = ap.parse_args(argv)
    size = None
    if a.size:
        w, h = a.size.lower().split('x')
        size = (int(w), int(h))
    rep = build(a.track, modes=tuple(m.strip() for m in a.modes.split(',') if m.strip()), size=size)
    if a.strip:
        p = contact_strip(a.track, mode=a.strip)
        if p:
            print('  strip: %s' % p)
    bad = [m for m, v in rep['modes'].items() if not v['audit_ok']]
    if bad:
        print('  STILL CONSTANT: %s' % ', '.join(bad))
    return 2 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
