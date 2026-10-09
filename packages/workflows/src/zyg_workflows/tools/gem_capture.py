#!/usr/bin/env python

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Export a GEM-X SOMA demo result as a 78-joint SOMA BVH plus a metadata sidecar.

Runs inside the GEM-X venv ($ZYG_MODELS_DIR/gemx/GEM-X/.venv). It reads the
``preprocess/hpe_results.pt`` written by ``scripts/demo/demo_soma.py``, takes the
world-space body params, builds the SOMA skeleton for the recovered identity and
writes the BVH with the demo's own ``retarget_utils`` helpers.

``build_soma_skeleton_from_model`` resolves ``inputs/soma_assets`` relative to the
process CWD, so this script resolves every user path to an absolute one and then
chdirs into the GEM-X root itself.

Usage:
    python tools/gem_capture.py \
        --gem-dir .../capture/_raw/qa_sword/gem/qa_sword \
        --fps 24 \
        --out .../capture/_raw/qa_sword/qa_sword_soma.bvh
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

# This script runs under the GEM-X venv, where zyg_workflows is not importable, so the
# ZYG_HOME / ZYG_MODELS_DIR roots are read here with the defaults paths.py uses.
_ZYG_HOME = Path(os.environ.get('ZYG_HOME', '').strip() or Path.home())
_MODELS_DIR = Path(os.environ.get('ZYG_MODELS_DIR', '').strip() or _ZYG_HOME / 'models')
GEMX_ROOT = _MODELS_DIR / 'gemx' / 'GEM-X'
GEMX_DEMO = GEMX_ROOT / 'scripts' / 'demo'


def _describe(value):
    """One-line shape/type description of a tensor, array or container."""
    shape = getattr(value, 'shape', None)
    if shape is not None:
        return f'{type(value).__name__}{tuple(shape)}'
    if isinstance(value, dict):
        return f'dict({len(value)} keys)'
    if isinstance(value, (list, tuple)):
        return f'{type(value).__name__}({len(value)})'
    return type(value).__name__


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--gem-dir', required=True, help='demo output dir holding preprocess/hpe_results.pt')
    ap.add_argument('--fps', type=float, required=True)
    ap.add_argument('--out', required=True, help='output .bvh path; the sidecar .json sits next to it')
    ap.add_argument('--clip', default='', help='source video, recorded in the sidecar')
    ap.add_argument('--wall-seconds', type=float, default=None, help='demo_soma.py wall time')
    ap.add_argument('--vram-peak-mib', type=int, default=None, help='max of the nvidia-smi sample log')
    ap.add_argument('--vram-baseline-mib', type=int, default=None, help='VRAM in use before the run')
    ap.add_argument(
        '--vo',
        default='unknown',
        choices=['ran', 'fallback_static', 'unknown'],
        help='whether visual odometry ran or the static-camera fallback was used',
    )
    args = ap.parse_args()

    gem_dir = Path(args.gem_dir).resolve()
    out_bvh = Path(args.out).resolve()
    # demo_soma.py (configs/demo_soma.yaml) writes hpe_results.pt at the clip root;
    # the older demo.yaml layout put it under preprocess/.
    candidates = [gem_dir / 'hpe_results.pt', gem_dir / 'preprocess' / 'hpe_results.pt']
    hpe_path = next((p for p in candidates if p.exists()), None)
    if hpe_path is None:
        ap.error('no hpe_results.pt at ' + ' or '.join(str(p) for p in candidates))
    out_bvh.parent.mkdir(parents=True, exist_ok=True)

    # retarget_utils and the SOMA assets are both resolved relative to the GEM-X root.
    os.chdir(GEMX_ROOT)
    sys.path.insert(0, str(GEMX_DEMO))

    from demo_soma import _get_body_params  # also patches torch.load(weights_only=False)
    import retarget_utils

    import torch

    # No weights_only=True here, and no weights_only kwarg at all: hpe_results.pt is
    # this pipeline's OWN intermediate, written by demo_soma.py seconds earlier in the
    # same run from a local clip — not a downloaded checkpoint. It holds non-tensor
    # body-param objects that weights_only=True rejects, which is why demo_soma patches
    # torch.load's default; passing the kwarg back into that patched callable would
    # collide with the value it already binds.
    pred = torch.load(str(hpe_path))  # local intermediate of this run, not a fetched checkpoint  # nosec B614
    body_params_global = _get_body_params(pred, 'body_params_global')

    top_keys = sorted(pred.keys())
    param_keys = sorted(body_params_global.keys())
    print(f'hpe_results.pt top-level keys ({len(top_keys)}):')
    for k in top_keys:
        print(f'  {k}: {_describe(pred[k])}')
    print(f'body_params_global keys ({len(param_keys)}):')
    for k in param_keys:
        print(f'  {k}: {_describe(body_params_global[k])}')

    identity_coeffs = body_params_global['identity_coeffs']
    scale_params = body_params_global['scale_params']
    skeleton = retarget_utils.build_soma_skeleton_from_model(identity_coeffs, scale_params)
    retarget_utils.export_soma_bvh(body_params_global, skeleton, args.fps, str(out_bvh))

    frames = 0
    with open(out_bvh, 'r', encoding='utf-8') as fh:
        for line in fh:
            if line.strip().startswith('Frames:'):
                frames = int(line.split(':', 1)[1])
                break

    meta = {
        'source': 'nvidia/GEM-X demo_soma.py -> retarget_utils.export_soma_bvh',
        'input_clip': args.clip or None,
        'gem_dir': str(gem_dir),
        'bvh': str(out_bvh),
        'frames': frames,
        'fps': args.fps,
        'num_joints': int(skeleton.num_joints),
        'joint_names': list(skeleton.joint_names),
        'parent_indices': [int(p) for p in skeleton.parent_indices],
        'hpe_results_keys': top_keys,
        'body_params_global_keys': param_keys,
        'vram_peak_mib': args.vram_peak_mib,
        'vram_baseline_mib': args.vram_baseline_mib,
        'vram_attributable_mib': (
            args.vram_peak_mib - args.vram_baseline_mib
            if args.vram_peak_mib is not None and args.vram_baseline_mib is not None
            else None
        ),
        'demo_wall_seconds': args.wall_seconds,
        'visual_odometry': args.vo,
    }
    out_json = out_bvh.with_suffix('.json')
    out_json.write_text(json.dumps(meta, indent=2) + '\n', encoding='utf-8')

    print(f'wrote {out_bvh} ({frames} frames, {skeleton.num_joints} joints)')
    print(f'wrote {out_json}')
    print('first 12 joints:', list(skeleton.joint_names)[:12])
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
