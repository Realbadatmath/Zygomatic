# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""char_control.py — control maps rendered from the character's fitted mesh (2026-08-04).

RUN:
    python3 -m zyg_workflows.geom.char_control <char_id> [--cells cell_00,cell_02] [--frames N -o DIR]

This is conditioning.py's job done for characters: the same four ControlNet-Union inputs
(depth, normal, segmentation, plus pose instead of lineart), derived from the FITTED GRID
rather than estimated by a model from pixels.

WHY THIS IS BETTER THAN THE ESTIMATORS IT REPLACES, per map:
  depth    rasterised from the 478-landmark face mesh's own z (Delaunay over the 2D
           points, z interpolated per triangle). MediaPipe's z is relative, not metric —
           but ControlNet depth wants ORDERING, not metres, and the ordering (nose in
           front of cheeks in front of ears) is exactly what the mesh knows. No
           Depth-Anything licence exposure, no dark-recess-reads-far confusion.
  normal   finite differences over that same rasterised depth — surface orientation the
           sampler can use to keep a cheek turned the way the mesh says it turns.
  pose     the 33-point skeleton drawn in the OpenPose colour convention the ControlNet
           was trained against. From the cascade, not from an NC OpenPose model.
  seg      the region map colourised — 26 addressable regions, not a person-blob.

--frames N writes the map sequence into a VACE control directory via vace_control.build,
so a character shot's control channel can carry the character's own grid exactly as the
tree scene's channel carries the tree — the same cure, applied to people.
"""

import json
import os

import numpy as np

try:
    import cv2
except Exception:  # pragma: no cover
    cv2 = None

from . import regions as R

# OpenPose-convention limb colours (BGR) — what controlnet-union's pose mode was fed
_POSE_COLOURS = [
    (0, 0, 255),
    (0, 85, 255),
    (0, 170, 255),
    (0, 255, 255),
    (0, 255, 170),
    (0, 255, 85),
    (0, 255, 0),
    (85, 255, 0),
    (170, 255, 0),
    (255, 255, 0),
    (255, 170, 0),
    (255, 85, 0),
    (255, 0, 0),
    (255, 0, 85),
    (255, 0, 170),
    (255, 0, 255),
    (170, 0, 255),
    (85, 0, 255),
]
_BONES = [
    ('left_shoulder', 'right_shoulder'),
    ('left_shoulder', 'left_elbow'),
    ('left_elbow', 'left_wrist'),
    ('right_shoulder', 'right_elbow'),
    ('right_elbow', 'right_wrist'),
    ('left_shoulder', 'left_hip'),
    ('right_shoulder', 'right_hip'),
    ('left_hip', 'right_hip'),
    ('left_hip', 'left_knee'),
    ('left_knee', 'left_ankle'),
    ('right_hip', 'right_knee'),
    ('right_knee', 'right_ankle'),
    ('nose', 'left_eye'),
    ('nose', 'right_eye'),
    ('left_eye', 'left_ear'),
    ('right_eye', 'right_ear'),
    ('left_ankle', 'left_foot_index'),
    ('right_ankle', 'right_foot_index'),
]


def _face_depth(mesh, w, h):
    """Rasterise the face mesh into a float depth image (nan where no face)."""
    from scipy.spatial import Delaunay
    from . import keypoints as K  # noqa: F401

    pts = np.asarray(mesh['face_landmarks'], np.float32)
    xy, z = pts[:, :2], pts[:, 2]
    depth = np.full((h, w), np.nan, np.float32)
    try:
        tri = Delaunay(xy)
    except Exception:
        return depth
    for simplex in tri.simplices:
        p = xy[simplex]
        zz = z[simplex]
        x0, y0 = np.floor(p.min(0)).astype(int)
        x1, y1 = np.ceil(p.max(0)).astype(int)
        x0, y0 = max(x0, 0), max(y0, 0)
        x1, y1 = min(x1, w - 1), min(y1, h - 1)
        if x1 <= x0 or y1 <= y0:
            continue
        # barycentric fill of the triangle's bounding box
        T = np.array([[p[0][0] - p[2][0], p[1][0] - p[2][0]], [p[0][1] - p[2][1], p[1][1] - p[2][1]]], np.float32)
        det = float(np.linalg.det(T))
        if abs(det) < 1e-6:
            continue
        Ti = np.linalg.inv(T)
        gx, gy = np.meshgrid(np.arange(x0, x1 + 1), np.arange(y0, y1 + 1))
        q = np.stack([gx - p[2][0], gy - p[2][1]], -1).astype(np.float32)
        l12 = q @ Ti.T
        l3 = 1.0 - l12.sum(-1)
        inside = (l12[..., 0] >= -1e-4) & (l12[..., 1] >= -1e-4) & (l3 >= -1e-4)
        zv = l12[..., 0] * zz[0] + l12[..., 1] * zz[1] + l3 * zz[2]
        region = depth[y0 : y1 + 1, x0 : x1 + 1]
        take = inside & (np.isnan(region) | (zv < region))  # nearer wins
        region[take] = zv[take]
        depth[y0 : y1 + 1, x0 : x1 + 1] = region
    return depth


def build_cell(cell_dir, out_dir=None):
    """Write pose/depth/normal/seg control maps for one processed cell."""
    with open(os.path.join(cell_dir, 'mesh.json')) as f:
        mesh = json.load(f)
    w, h = mesh['size']
    out_dir = out_dir or os.path.join(cell_dir, 'control')
    os.makedirs(out_dir, exist_ok=True)
    paths = {}

    # ── pose ────────────────────────────────────────────────────────────────
    if mesh.get('body'):
        from . import keypoints as K

        b = np.asarray(mesh['body_landmarks'], np.float32)
        pose = np.zeros((h, w, 3), np.uint8)
        for i, (a, c) in enumerate(_BONES):
            pa, pc = b[K.P[a]], b[K.P[c]]
            if pa[2] < 0.4 or pc[2] < 0.4:
                continue
            cv2.line(
                pose,
                (int(pa[0]), int(pa[1])),
                (int(pc[0]), int(pc[1])),
                _POSE_COLOURS[i % len(_POSE_COLOURS)],
                max(3, h // 180),
                cv2.LINE_AA,
            )
        for i in range(33):
            if b[i][2] >= 0.4:
                cv2.circle(
                    pose, (int(b[i][0]), int(b[i][1])), max(3, h // 220), _POSE_COLOURS[i % len(_POSE_COLOURS)], -1
                )
        paths['pose'] = os.path.join(out_dir, 'pose.png')
        cv2.imwrite(paths['pose'], pose)

    # ── face depth + normal ─────────────────────────────────────────────────
    if mesh.get('face') and mesh.get('face_landmarks'):
        d = _face_depth(mesh, w, h)
        m = np.isfinite(d)
        if m.any():
            lo, hi = np.percentile(d[m], 2), np.percentile(d[m], 98)
            nd = np.zeros((h, w), np.float32)
            nd[m] = 1.0 - np.clip((d[m] - lo) / max(hi - lo, 1e-6), 0, 1)  # near=white
            paths['face_depth'] = os.path.join(out_dir, 'face_depth.png')
            cv2.imwrite(paths['face_depth'], (nd * 255).astype(np.uint8))

            dz = np.where(m, d, np.nanmean(d[m]))
            gx = cv2.Sobel(dz, cv2.CV_32F, 1, 0, ksize=5)
            gy = cv2.Sobel(dz, cv2.CV_32F, 0, 1, ksize=5)
            n = np.dstack([-gx, -gy, np.full_like(gx, 24.0)])
            n /= np.maximum(np.linalg.norm(n, axis=2, keepdims=True), 1e-6)
            nm = ((n * 0.5 + 0.5) * 255).astype(np.uint8)
            nm[~m] = 128
            paths['face_normal'] = os.path.join(out_dir, 'face_normal.png')
            cv2.imwrite(paths['face_normal'], nm[:, :, ::-1])

    # ── segmentation ────────────────────────────────────────────────────────
    rm = cv2.imread(os.path.join(cell_dir, 'regions.png'), cv2.IMREAD_GRAYSCALE)
    if rm is not None:
        paths['seg'] = os.path.join(out_dir, 'seg.png')
        cv2.imwrite(paths['seg'], R.colourise(rm))
    return paths


if __name__ == '__main__':  # the CLI lives in char_control_cli
    from zyg_workflows.geom.char_control_cli import main as _cli_main

    raise SystemExit(_cli_main())
