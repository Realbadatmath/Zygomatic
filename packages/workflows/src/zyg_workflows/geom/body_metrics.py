# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""body_metrics.py — body proportions of a character, read off their sheet cell.

WHAT THIS IS FOR. The cmu_mb skeleton that every movement in the motion library targets
has 31 bones whose LENGTHS have to come from somewhere. Until now they came from an
MPFB-generated proxy body. This module reads them off the character's own picture
instead: a BlazePose 33-point skeleton plus the person segmentation mask give five
proportions expressed as FRACTIONS OF STANDING HEIGHT (leg, arm, torso, head_neck,
shoulder), which is exactly what a bone-length fitter can scale by the bible's
`identity.height_m` and apply to the clay base body.

WHY FRACTIONS AND NOT PIXELS. The cells are rendered at whatever framing the sheet
pipeline chose; only ratios survive that. Standing height in pixels is the mask's
extent (crown row to heel row), not the skeleton's — BlazePose extrapolates joints past
the frame edge and the mask does not.

WHICH IMAGE. `contact_sheet_pipeline._body_anchor_path_for` names a cell
`cell_000_body.png` / `cell_00_body.png`, and for most characters it is a standing
full-body render. It is NOT always: measured 2026-09-22 over the 16 characters that
have one, only 6 put the ankles inside the frame (Abel c3345deb5bde's body anchor is a
waist-up portrait — BlazePose puts his ankles at y=2172 in a 1216px image with
visibility 0.00). Measuring that cell would report a leg length invented by the
detector's extrapolator. So the body anchor is only the FIRST candidate: when it does
not hold a whole body, the other sheet cells are scanned in order and the first one
that does is used (Abel: cell_24.png). The cell actually measured is recorded in the
output's `image` field, and a head-and-shoulders cell can never win because the
acceptance test is precisely "the ankles are in frame and visible".

LICENCE. MediaPipe only (Apache-2.0 incl. weights), via geom.keypoints — no SMPL, no
DensePose, no insightface.
"""

from __future__ import annotations

import glob
import json
import os
from datetime import datetime, timezone

import numpy as np

from zyg_workflows import paths
from zyg_workflows.geom import keypoints as K

SCHEMA = 'zyg.body_metrics/1'

_DATASET_ROOT = str(paths.ZYG_LORA_DATASETS / 'storyteller_chars')

# a candidate cell is a usable full-body view when every landmark the fractions need is
# at least this visible and the ankles are inside the frame
_MIN_VIS = 0.6
# ...and 'high' confidence additionally wants this, plus a frontal view
_HIGH_VIS = 0.7
# shoulder z-difference over shoulder width above this means the person is turned
_YAW_TOL = 0.5
# a whole standing body cannot occupy less of the frame than this
_MIN_HEIGHT_FRAC = 0.30

# the landmarks every fraction is built from; visibility_min is taken over these
_USED = (
    'left_shoulder',
    'right_shoulder',
    'left_wrist',
    'right_wrist',
    'left_hip',
    'right_hip',
    'left_ankle',
    'right_ankle',
)


def cells_dir(char_id: str) -> str:
    return os.path.join(_DATASET_ROOT, char_id, 'contact_sheet', 'cells')


def body_anchor_path(char_id: str) -> str:
    """The body anchor cell, with the 03d/02d read compatibility of
    contact_sheet_pipeline._body_anchor_path_for (line 718)."""
    cdir = cells_dir(char_id)
    for name in ('cell_000_body.png', 'cell_00_body.png'):
        p = os.path.join(cdir, name)
        if os.path.isfile(p):
            return p
    return os.path.join(cdir, 'cell_000_body.png')


def candidate_images(char_id: str) -> list[str]:
    """Cells to try, best bet first: the body anchor, then the numbered cells in order."""
    out = []
    anchor = body_anchor_path(char_id)
    if os.path.isfile(anchor):
        out.append(anchor)
    for p in sorted(glob.glob(os.path.join(cells_dir(char_id), 'cell_*.png'))):
        if p not in out:
            out.append(p)
    return out


def _bible(char_id: str) -> dict:
    """identity block of the character bible, read only. Missing file -> {}."""
    try:
        from zyg_workflows import character_bible_service as CBS

        path = CBS.bible_path(char_id)
    except Exception:
        path = os.path.join(_DATASET_ROOT, char_id, 'character_bible.json')
    try:
        with open(path, 'r', encoding='utf-8') as fh:
            return dict(json.load(fh).get('identity') or {})
    except Exception:
        return {}


def _mask_extent(mask: np.ndarray) -> tuple[int, int]:
    """(top, bottom) rows of the silhouette. Raises when the mask is empty."""
    rows = np.where((mask > 0.5).any(axis=1))[0]
    if rows.size == 0:
        raise ValueError('person mask is empty')
    return int(rows[0]), int(rows[-1])


def _crown(mask: np.ndarray, pts: np.ndarray) -> tuple[float, float]:
    """Top of the silhouette AT THE HEAD COLUMN — the overall mask top can be a raised
    hand. The column window is the nose +/- half a shoulder width."""
    nose_x = float(pts[K.P['nose'], 0])
    ls, rs = pts[K.P['left_shoulder'], :2], pts[K.P['right_shoulder'], :2]
    half = max(float(np.linalg.norm(ls - rs)) * 0.5, 12.0)
    w = mask.shape[1]
    x0 = int(max(0, min(w - 1, nose_x - half)))
    x1 = int(max(x0 + 1, min(w, nose_x + half)))
    sub = mask[:, x0:x1] > 0.5
    rows = np.where(sub.any(axis=1))[0]
    if rows.size == 0:
        return nose_x, float(_mask_extent(mask)[0])
    top = int(rows[0])
    cols = np.where(sub[top])[0]
    return float(x0 + cols.mean()), float(top)


def _d(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.linalg.norm(np.asarray(a, np.float64)[:2] - np.asarray(b, np.float64)[:2]))


def measure_arrays(pts: np.ndarray, z: np.ndarray, crown, h_px: float) -> dict:
    """Pure geometry — the fraction maths, with no image and no detector.

    pts: (33,3) BlazePose [x, y, visibility] in pixels.  z: (33,) per-landmark depth in
    the same units as x.  crown: (x, y) top of the head.  h_px: standing height in px.
    """
    pts = np.asarray(pts, np.float64)
    z = np.asarray(z, np.float64)
    if pts.shape[0] != 33:
        raise ValueError('expected 33 BlazePose landmarks, got %d' % pts.shape[0])
    if not h_px > 0:
        raise ValueError('standing height must be positive')
    g = lambda n: pts[K.P[n]]  # noqa: E731

    leg_px = 0.5 * (_d(g('left_hip'), g('left_ankle')) + _d(g('right_hip'), g('right_ankle')))
    arm_px = 0.5 * (_d(g('left_shoulder'), g('left_wrist')) + _d(g('right_shoulder'), g('right_wrist')))
    mid_sh = 0.5 * (g('left_shoulder')[:2] + g('right_shoulder')[:2])
    mid_hip = 0.5 * (g('left_hip')[:2] + g('right_hip')[:2])
    torso_px = _d(mid_sh, mid_hip)
    head_neck_px = _d(np.asarray(crown, np.float64), mid_sh)
    shoulder_px = _d(g('left_shoulder'), g('right_shoulder'))

    # a turned body foreshortens the shoulder width (and only that fraction badly);
    # BlazePose's z is the only frontality signal 2D keypoints do not carry
    yaw_ratio = (
        (abs(float(z[K.P['left_shoulder']] - z[K.P['right_shoulder']])) / shoulder_px)
        if shoulder_px > 0
        else float('inf')
    )

    px = {
        'height': float(h_px),
        'leg': leg_px,
        'arm': arm_px,
        'torso': torso_px,
        'head_neck': head_neck_px,
        'shoulder': shoulder_px,
    }
    return {
        'fractions': {k: v / float(h_px) for k, v in px.items() if k != 'height'},
        'px': px,
        'visibility_min': min(float(g(n)[2]) for n in _USED),
        'yaw_ok': bool(yaw_ratio <= _YAW_TOL),
        'yaw_ratio': float(yaw_ratio),
    }


def _measure_image(path: str) -> dict | None:
    """Measure one cell. None when no body or no mask was detected."""
    det = K.detect(path)
    if not det.body.ok or det.person_mask is None:
        return None
    pts, z = det.body.pts, det.body.extra.get('z')
    if z is None:
        z = np.zeros(len(pts), np.float32)
    top, bottom = _mask_extent(det.person_mask)
    h_px = float(bottom - top)
    if h_px <= 0:
        return None
    m = measure_arrays(pts, z, _crown(det.person_mask, pts), h_px)
    m['image'] = path
    m['image_size'] = [int(det.w), int(det.h)]
    # a whole body is in frame only when the ankles are — BlazePose happily
    # extrapolates them past the frame edge on a waist-up portrait
    ankles_in = all(0.0 <= float(pts[K.P[n], 1]) < det.h for n in ('left_ankle', 'right_ankle'))
    m['full_body'] = bool(ankles_in and m['visibility_min'] >= _MIN_VIS and h_px >= _MIN_HEIGHT_FRAC * det.h)
    return m


def measure(char_id: str, image: str | None = None) -> dict:
    """Body proportions of `char_id`, written to body_metrics.json and returned.

    `image` forces one cell; otherwise the body anchor is tried first and the numbered
    cells are scanned until one holds a whole, frontal, confidently-detected body.
    Raises FileNotFoundError when there is nothing to measure and ValueError when
    nothing measurable was found in any candidate.
    """
    if image:
        if not os.path.isfile(image):
            raise FileNotFoundError('no such image: %s' % image)
        best = _measure_image(image)
        if best is None:
            raise ValueError('no body detected in %s' % image)
        scanned = 1
    else:
        cands = candidate_images(char_id)
        if not cands:
            raise FileNotFoundError('no contact-sheet cells for %s (looked in %s)' % (char_id, cells_dir(char_id)))
        best, scanned = None, 0
        for p in cands:
            scanned += 1
            m = _measure_image(p)
            if m is None or not m['full_body']:
                continue
            if m['yaw_ok'] and m['visibility_min'] >= _HIGH_VIS:
                best = m
                break  # a frontal, fully-visible body
            if best is None:
                best = m  # keep as the fallback
        if best is None:
            raise ValueError(
                'no whole body found in any of the %d cells of %s — the body anchor is '
                'a portrait and no numbered cell shows the ankles' % (scanned, char_id)
            )

    ident = _bible(char_id)
    out = {
        'schema': SCHEMA,
        'char_id': char_id,
        'image': best['image'],
        'image_size': best['image_size'],
        'cells_scanned': scanned,
        'from_body_anchor': best['image'] == body_anchor_path(char_id),
        'height_m': ident.get('height_m'),
        'gender': ident.get('gender'),
        'age': ident.get('age'),
        'body_build': ident.get('body_build'),
        'fractions': {k: round(v, 5) for k, v in best['fractions'].items()},
        'px': {k: round(v, 2) for k, v in best['px'].items()},
        'visibility_min': round(best['visibility_min'], 4),
        'yaw_ok': best['yaw_ok'],
        'yaw_ratio': round(best['yaw_ratio'], 4),
        'confidence': ('high' if best['yaw_ok'] and best['visibility_min'] >= _HIGH_VIS else 'low'),
        'method': 'blazepose33/mask',
        'measured': datetime.now(timezone.utc).isoformat(timespec='seconds'),
    }
    path = out_path(char_id)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as fh:
        json.dump(out, fh, indent=2)
        fh.write('\n')
    out['path'] = path
    return out


def out_path(char_id: str) -> str:
    return os.path.join(_DATASET_ROOT, char_id, 'body_metrics.json')


if __name__ == '__main__':  # the CLI lives in body_metrics_cli
    from zyg_workflows.geom.body_metrics_cli import main as _cli_main

    raise SystemExit(_cli_main())
