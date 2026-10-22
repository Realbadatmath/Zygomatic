# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Command line of `zyg_workflows.tools.motion_fidelity`, moved out of the library module so that
library code never prints; `python -m zyg_workflows.tools.motion_fidelity` still reaches it.
"""

import argparse
import json
import os
import subprocess
import tempfile

from zyg_workflows.bin import exe


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('clip')
    ap.add_argument('shot_dir')
    ap.add_argument('--n', type=int, default=8)
    a = ap.parse_args()
    from zyg_workflows.geom import keypoints as K
    import numpy as np

    J = json.load(open(os.path.join(a.shot_dir, 'plates_raw', 'joints.json')))
    frames = J['frames']
    names = J['names']
    li, ri = names.index('left_wrist'), names.index('right_wrist')
    ls, rs = names.index('left_shoulder'), names.index('right_shoulder')
    tmp = tempfile.mkdtemp(prefix='fid_')
    subprocess.run([exe('ffmpeg'), '-v', 'error', '-y', '-i', a.clip, os.path.join(tmp, 'f_%05d.png')], check=True)
    fs = sorted(os.listdir(tmp))
    n = min(len(fs), len(frames))
    idx = [round(i * (n - 1) / (a.n - 1)) for i in range(a.n)]
    rows = []
    for i in idx:
        det = K.detect(os.path.join(tmp, fs[i]))
        rig = frames[i]['actors'][next(iter(frames[i]['actors']))]['pts']
        vis = [p for p in rig if p[2] > 0.5]
        body_h = (max(p[1] for p in vis) - min(p[1] for p in vis)) if vis else None
        rec = {'frame': i + 1, 'detected': bool(det.body.ok), 'rig_body_h': round(body_h, 1) if body_h else None}
        if det.body.ok and det.body.pts is not None and len(det.body.pts) >= 17:
            p = np.asarray(det.body.pts)[:, :2]
            dl, dr = p[li], p[ri]
            rl, rr = np.array(rig[li][:2]), np.array(rig[ri][:2])
            direct = (np.linalg.norm(dl - rl) + np.linalg.norm(dr - rr)) / 2
            swapped = (np.linalg.norm(dl - rr) + np.linalg.norm(dr - rl)) / 2
            err = float(min(direct, swapped))
            rec.update(
                {
                    'wrist_err_px': round(err, 1),
                    'wrist_err_pct_body': round(100 * err / body_h, 1) if body_h else None,
                    'det_body_h': round(float(p[:, 1].max() - p[:, 1].min()), 1),
                }
            )
            # facing: sign of (right_shoulder.x - left_shoulder.x) — negative = seen from behind
            # (BlazePose labels are semantic left/right, as are the rig's)
            det_face = float(np.sign(p[rs][0] - p[ls][0]))
            rig_face = float(np.sign(rig[rs][0] - rig[ls][0]))
            rec.update(
                {
                    'facing_det': 'front' if det_face > 0 else 'back',
                    'facing_rig': 'front' if rig_face > 0 else 'back',
                    'facing_match': bool(det_face == rig_face),
                }
            )
        rows.append(rec)
    ok = [r for r in rows if r.get('wrist_err_px') is not None]
    fm = [r for r in ok if 'facing_match' in r]
    summary = {
        'clip': a.clip,
        'frames_sampled': len(rows),
        'frames_detected': len(ok),
        'facing_match_rate': round(sum(1 for r in fm if r['facing_match']) / len(fm), 2) if fm else None,
        'wrist_err_px_mean': round(sum(r['wrist_err_px'] for r in ok) / len(ok), 1) if ok else None,
        'wrist_err_pct_body_mean': round(sum(r['wrist_err_pct_body'] for r in ok) / len(ok), 1) if ok else None,
        'rows': rows,
    }
    with open(a.clip + '.fidelity.json', 'w') as fh:
        json.dump(summary, fh, indent=1)
    print(json.dumps({k: v for k, v in summary.items() if k != 'rows'}))
    for r in rows:
        print(' ', r)


if __name__ == '__main__':
    main()
