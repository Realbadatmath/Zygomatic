# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""char_mesh.py — batch the mesh grid over a character's images (2026-08-04).

RUN:
    python3 -m zyg_workflows.geom.char_mesh <char_id> [--images DIR] [--out DIR] [--limit N]

For every image of a character (default: its LoRA training cells under
$ZYG_LORA_DATASETS/wan_chars/<char_id>/images) this writes, per cell:

    overlay.png        the deliverable: region tint + face tesselation + skeleton on the
                       frame — the visible mesh grid
    regions.png        uint8 region-id map (regions.REGION_IDX values). THE artifact the
                       rest of the pipeline addresses: VLM crops, inpaint masks, drift
                       comparisons all read this
    regions_color.png  the same map, colourised for humans
    mesh.json          landmarks (face 478 xyz, body 33 xy+vis), blendshapes, detection
                       route (full/crop/none), region pixel stats

and per character: mesh_summary.json with corpus-level statistics. The summary is what
gate_character.py consumes, and what the manifest's character entry points at.

Detection failures are RECORDED, never papered over: a rear-view cell gets
face=false and only body/hair regions, and the summary counts it as a rear view rather
than a failure — measured on Abel, 4 of 48 cells are genuine rear views and 1 is a
tiny-face hard profile. Those numbers belong in the record, not smoothed out of it.
"""

import glob
import json
import os
import time

import numpy as np

try:
    import cv2
except Exception:  # pragma: no cover
    cv2 = None

from .. import paths
from . import keypoints as K
from . import regions as R

DATASETS = str(paths.ZYG_LORA_DATASETS / 'wan_chars')
OUT_ROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'output', 'char_mesh')


def process_image(path, out_dir):
    """One image -> artifacts + record. Returns the record dict."""
    os.makedirs(out_dir, exist_ok=True)
    bgr = cv2.imread(path)
    if bgr is None:
        return {'image': path, 'error': 'unreadable'}
    det = K.detect(path)
    rm = R.build(det)
    st = R.stats(rm)

    cv2.imwrite(os.path.join(out_dir, 'regions.png'), rm)
    cv2.imwrite(os.path.join(out_dir, 'regions_color.png'), R.colourise(rm))
    cv2.imwrite(os.path.join(out_dir, 'overlay.png'), R.overlay(bgr, det, rm))

    rec = {
        'image': path,
        'size': [det.w, det.h],
        'face': det.face.ok,
        'face_via': det.face.via,
        'body': det.body.ok,
        'person_px': int((det.person_mask > 0.5).sum()) if det.person_mask is not None else 0,
        'regions': st,
        'blendshapes_top': dict(sorted(det.blendshapes.items(), key=lambda kv: -kv[1])[:8]) if det.blendshapes else {},
    }
    with open(os.path.join(out_dir, 'mesh.json'), 'w') as f:
        json.dump(
            {
                **rec,
                'face_landmarks': None if not det.face.ok else np.round(det.face.pts, 2).tolist(),
                'body_landmarks': None if not det.body.ok else np.round(det.body.pts, 2).tolist(),
                # per-landmark z — the fitter's yaw seed; see keypoints.py
                'body_z': None
                if not (det.body.ok and 'z' in det.body.extra)
                else np.round(det.body.extra['z'], 2).tolist(),
                # head yaw (radians) from the facial transformation matrix
                'face_yaw': (None if not det.face.ok else det.face.extra.get('yaw')),
            },
            f,
        )
    return rec


def run(char_id, images=None, out=None, limit=0):
    img_dir = images or os.path.join(DATASETS, char_id, 'images')
    files = sorted(glob.glob(os.path.join(img_dir, '*.png')))
    if limit:
        files = files[:limit]
    if not files:
        raise SystemExit('no images under %s' % img_dir)
    out_dir = out or os.path.join(OUT_ROOT, char_id)
    os.makedirs(out_dir, exist_ok=True)

    records, t0 = [], time.time()
    for f in files:
        cell = os.path.splitext(os.path.basename(f))[0]
        records.append(process_image(f, os.path.join(out_dir, cell)))

    ok_face = sum(1 for r in records if r.get('face'))
    via_crop = sum(1 for r in records if r.get('face_via') == 'crop')
    ok_body = sum(1 for r in records if r.get('body'))
    # a cell with a body but no face and hair present is (almost always) a rear view
    rear = sum(1 for r in records if r.get('body') and not r.get('face') and 'hair_head' in r.get('regions', {}))
    summary = {
        'char_id': char_id,
        'images': len(records),
        'face_detected': ok_face,
        'face_via_crop': via_crop,
        'body_detected': ok_body,
        'no_face_rear_or_tiny': len(records) - ok_face,
        'rear_view_estimate': rear,
        'region_presence': {},
        'seconds': round(time.time() - t0, 1),
        'generated': time.strftime('%Y-%m-%dT%H:%M:%S'),
    }
    for name in R.REGION_IDX:
        summary['region_presence'][name] = sum(1 for r in records if name in r.get('regions', {}))
    with open(os.path.join(out_dir, 'mesh_summary.json'), 'w') as f:
        json.dump({'summary': summary, 'cells': records}, f, indent=1)
    return summary


if __name__ == '__main__':  # the CLI lives in char_mesh_cli
    from zyg_workflows.geom.char_mesh_cli import main as _cli_main

    raise SystemExit(_cli_main())
