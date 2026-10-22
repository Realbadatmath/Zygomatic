# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Command line of `zyg_workflows._identity_embed_worker`, moved out of the library module
so that library code never prints; `python -m zyg_workflows._identity_embed_worker` still
reaches it.
"""

import argparse
import json
import os
import sys

from zyg_workflows._identity_embed_worker import _zyg_log


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--images', required=True, help='JSON file with list of image paths')
    ap.add_argument('--root', required=True, help='insightface root (contains models/antelopev2)')
    ap.add_argument('--out', required=True, help='output JSON path')
    ap.add_argument('--det-size', type=int, default=640)
    # SCRFD's 0.5 default misses hard 90-degree profiles; 0.35 recovers most of them.
    ap.add_argument('--det-thresh', type=float, default=0.35)
    # OPT-IN GPU (2026-08-09). Default stays CPU — see the provider comment below.
    ap.add_argument(
        '--gpu', action='store_true', help='use CUDAExecutionProvider (caller must guarantee the GPU is free)'
    )
    # 2026-08-09 AuraFace A/B: --pack auraface loads the Apache-2.0 fal/AuraFace-v1
    # pack (same FaceAnalysis API/file names) instead of NC insightface antelopev2.
    # 2026-08-26: default flipped to auraface — the insightface pretrained packs
    # are "non-commercial research purposes only" and antelopev2 was deleted.
    ap.add_argument(
        '--pack', default='auraface', help='insightface model pack under <root>/models/ (auraface | antelopev2)'
    )
    args = ap.parse_args()

    with open(args.images, encoding='utf-8') as fh:
        image_paths = json.load(fh)

    import cv2
    import numpy as np
    from insightface.app import FaceAnalysis

    # DEFAULT IS CPU, and must stay that way: this worker is called from
    # contact_sheet_pipeline's identity QC in the middle of render runs, where
    # competing with ComfyUI for VRAM would be far more expensive than the few
    # seconds CPU scoring costs.
    #
    # --gpu is opt-in for bulk callers that have already established the GPU is
    # idle (Medusa body-template preparation over thousands of photographs,
    # where CPU SCRFD is ~1.3 s/image). The CPU provider stays in the list as a
    # fallback so a missing/!broken CUDA EP degrades instead of crashing.
    if args.gpu:
        providers = ['CUDAExecutionProvider', 'CPUExecutionProvider']
        ctx_id = 0
    else:
        providers = ['CPUExecutionProvider']
        ctx_id = -1

    app = FaceAnalysis(
        name=args.pack,
        root=args.root,
        providers=providers,
        allowed_modules=['detection', 'recognition', 'landmark_3d_68'],
    )
    app.prepare(
        ctx_id=ctx_id,
        det_thresh=args.det_thresh,
        det_size=(args.det_size, args.det_size),
    )
    if args.gpu:
        try:
            import onnxruntime as _ort

            active = _ort.get_available_providers()
            print(f'[embed_worker] providers available: {active}', file=sys.stderr)
        except Exception as _exc:
            _zyg_log.debug('onnxruntime provider list unavailable: %s', _exc)

    results: dict = {}
    for path in image_paths:
        entry: dict = {
            'face_detected': False,
            'faces_count': 0,
            'faces_scores': [],
            'det_score': 0.0,
            'bbox': None,
            'embedding': None,
            'yaw': None,
            'roll': None,
            'img_w': None,
            'img_h': None,
        }
        try:
            img = cv2.imread(path)
            if img is None:
                entry['error'] = 'unreadable image'
                results[path] = entry
                continue
            entry['img_h'], entry['img_w'] = int(img.shape[0]), int(img.shape[1])
            faces = app.get(img)
            pad_x = pad_y = 0
            if not faces:
                # SCRFD large-face blind spot: faces filling ~90%+ of the frame
                # go undetected at det_size 640 (2026-07-16: 14 clean close-ups
                # scored no_face and tripped the circuit breaker). Retry once on
                # a 2x padded canvas and map the geometry back to the original.
                pad_y, pad_x = entry['img_h'] // 2, entry['img_w'] // 2
                padded = cv2.copyMakeBorder(
                    img,
                    pad_y,
                    pad_y,
                    pad_x,
                    pad_x,
                    cv2.BORDER_CONSTANT,
                    value=(128, 128, 128),
                )
                faces = app.get(padded)
                if faces:
                    entry['padded_retry'] = True
                else:
                    pad_x = pad_y = 0
            entry['faces_count'] = len(faces)
            entry['faces_scores'] = [float(getattr(f, 'det_score', 0.0)) for f in faces]
            if faces:
                # Largest face wins — tiles are single-subject portraits.
                face = max(
                    faces,
                    key=lambda f: (f.bbox[2] - f.bbox[0]) * (f.bbox[3] - f.bbox[1]),
                )
                emb = getattr(face, 'normed_embedding', None)
                if emb is None and getattr(face, 'embedding', None) is not None:
                    v = np.asarray(face.embedding, dtype=np.float64)
                    n = np.linalg.norm(v)
                    emb = v / n if n > 0 else None
                if emb is not None:
                    entry['face_detected'] = True
                    entry['det_score'] = float(getattr(face, 'det_score', 0.0))
                    # Map padded-retry coordinates back to the original frame
                    # (clamped) so edge-cut/texture checks see true geometry.
                    entry['bbox'] = [
                        max(0.0, min(float(face.bbox[0]) - pad_x, entry['img_w'])),
                        max(0.0, min(float(face.bbox[1]) - pad_y, entry['img_h'])),
                        max(0.0, min(float(face.bbox[2]) - pad_x, entry['img_w'])),
                        max(0.0, min(float(face.bbox[3]) - pad_y, entry['img_h'])),
                    ]
                    entry['embedding'] = [float(x) for x in emb]
                pose = getattr(face, 'pose', None)
                if pose is not None and len(pose) >= 2:
                    # insightface pose = (pitch, yaw, roll) degrees
                    entry['yaw'] = float(pose[1])
                    if len(pose) >= 3:
                        # roll catches sideways/inverted frames the detector
                        # still resolves (2026-07-16 audit: rotated portraits
                        # trained as-is because nothing checked orientation)
                        entry['roll'] = float(pose[2])
        except Exception as exc:  # per-image failure must not kill the batch
            entry['error'] = str(exc)[:200]
        results[path] = entry

    tmp = args.out + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as fh:
        json.dump(results, fh)
    os.replace(tmp, args.out)
    return 0


if __name__ == '__main__':
    sys.exit(main())
