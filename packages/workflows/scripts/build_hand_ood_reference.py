#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Build the hand-QC style-drift OOD reference set (see hand_qc_service.py).

Detects hands in the known-good photoreal fixture directory (run 59e8d33f,
the control set the no-harm regression harness already uses), crops them the
same way hand_qc_service judges them, embeds each crop with the frozen DINOv2
backbone, and caches the result to data/runtime/hand_qc/ood_reference.npz.

Also reports the reference set's self-consistency spread (the auto threshold
hand_qc_service derives from it) and, as a sanity check, the OOD distance of
a sample from the known-BAD directory — both directories are photoreal, so a
defective-but-photoreal hand should still measure IN-distribution. If it does
not, the gate is confusing 'anatomically wrong' with 'stylistically foreign'
and needs a rethink before shipping.

Usage (agents venv, from the crews dir):
    ../.venv/bin/python scripts/build_hand_ood_reference.py [--max-crops 200]
"""

from __future__ import annotations

import argparse
import glob
import os
import sys

_CREWS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _CREWS_DIR not in sys.path:
    sys.path.insert(0, _CREWS_DIR)

_GOOD_DIR = os.environ.get(
    'ZYG_HANDFIX_REG_GOOD_DIR',
    os.path.join(_CREWS_DIR, 'data', 'output', 'clips', '59e8d33f-a277-41be-a165-472301def385'),
)
_BAD_DIR = os.environ.get(
    'ZYG_HANDFIX_REG_BAD_DIR',
    os.path.join(_CREWS_DIR, 'data', 'output', 'clips', '6278904c-a6a5-4174-9a2e-53cba4caa2cd'),
)


def _collect_crops(image_dir: str, max_crops: int):
    from zyg_workflows import hand_qc_service as hqs

    crops = []
    for path in sorted(glob.glob(os.path.join(image_dir, 'scene_*.png'))):
        if len(crops) >= max_crops:
            break
        try:
            boxes = hqs.detect_hand_boxes(path)
        except Exception as exc:
            print(f'  [skip] {os.path.basename(path)}: {exc}')
            continue
        for b in boxes:
            if len(crops) >= max_crops:
                break
            crops.append(hqs._crop_pil(path, b['box']))
    return crops


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--max-crops', type=int, default=200)
    args = ap.parse_args()

    import numpy as np
    from zyg_workflows import vfx_embed as VE

    info = VE.available()
    if not info.get('ok'):
        print(f'embedding backbone unavailable: {info}')
        return 2

    print(f'Collecting hand crops from good dir: {_GOOD_DIR}')
    good_crops = _collect_crops(_GOOD_DIR, args.max_crops)
    print(f'  {len(good_crops)} crops detected')
    if len(good_crops) < 8:
        print('too few reference crops to build a meaningful reference set')
        return 3

    ref = VE.embed_images(good_crops).astype(np.float32)
    out_path = os.path.join(_CREWS_DIR, 'data', 'runtime', 'hand_qc', 'ood_reference.npz')
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    np.savez(out_path, ref=ref)
    print(f'Saved {len(ref)} reference embeddings -> {out_path}')

    n = np.linalg.norm(ref, axis=1, keepdims=True)
    unit = ref / np.maximum(n, 1e-8)
    sim = unit @ unit.T
    np.fill_diagonal(sim, -1.0)
    k = min(5, sim.shape[1])
    self_dist = 1.0 - np.sort(sim, axis=1)[:, -k:].mean(axis=1)
    threshold = float(self_dist.mean() + 4 * self_dist.std())
    print(f'Self-consistency distance: mean {self_dist.mean():.4f} std {self_dist.std():.4f} max {self_dist.max():.4f}')
    print(f'Auto OOD threshold (mean + 4*std): {threshold:.4f}')

    print(f'\nSanity check against known-BAD photoreal dir: {_BAD_DIR}')
    bad_crops = _collect_crops(_BAD_DIR, 40)
    if bad_crops:
        bad_feat = VE.embed_images(bad_crops).astype(np.float32)
        bn = np.linalg.norm(bad_feat, axis=1, keepdims=True)
        bad_unit = bad_feat / np.maximum(bn, 1e-8)
        bad_sim = bad_unit @ unit.T
        bad_dist = 1.0 - np.sort(bad_sim, axis=1)[:, -k:].mean(axis=1)
        flagged = int((bad_dist > threshold).sum())
        print(
            f'  {len(bad_crops)} known-bad (but still photoreal) crops: '
            f'mean dist {bad_dist.mean():.4f}, max {bad_dist.max():.4f}, '
            f'{flagged}/{len(bad_crops)} would be flagged OOD'
        )
        if flagged:
            print(
                '  NOTE: some anatomically-defective-but-photoreal crops read as '
                'OOD too — the gate is not purely style-selective on this sample. '
                'That is still safe (it only ever makes the fixer look CLOSER, '
                'never skip a look), but worth knowing before tightening the '
                'threshold further.'
            )
    else:
        print('  no known-bad crops detected — skipping sanity check')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
