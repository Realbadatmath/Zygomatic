# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Command line of `zyg_workflows.tools.gem_capture`, moved out of the library module so that
library code never prints; `python -m zyg_workflows.tools.gem_capture` still reaches it.

motion_capture runs gem_capture.py BY PATH under the GEM-X venv's python, where zyg_workflows is
not installed, so the library module is imported here by whichever of the two names resolves.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

try:
    from zyg_workflows.tools import gem_capture as _lib
except ImportError:  # the GEM-X venv has no zyg_workflows; the sibling module sits beside this file
    import gem_capture as _lib  # type: ignore[no-redef]


def main() -> int:
    ap = argparse.ArgumentParser(description=_lib.__doc__)
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
    os.chdir(_lib.GEMX_ROOT)
    sys.path.insert(0, str(_lib.GEMX_DEMO))

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
        print(f'  {k}: {_lib._describe(pred[k])}')
    print(f'body_params_global keys ({len(param_keys)}):')
    for k in param_keys:
        print(f'  {k}: {_lib._describe(body_params_global[k])}')

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
