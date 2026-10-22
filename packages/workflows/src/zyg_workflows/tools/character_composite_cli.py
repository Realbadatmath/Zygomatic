# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Command line of `zyg_workflows.tools.character_composite`, moved out of the library module so
that library code never prints; `python -m zyg_workflows.tools.character_composite` still reaches
it.
"""

import argparse
import os
import subprocess
import tempfile
import shutil
import json
import numpy as np
import cv2
from PIL import Image
from zyg_workflows.bin import exe


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('clip')
    ap.add_argument('plates')
    ap.add_argument('out')
    ap.add_argument('--fps', type=float, default=24.0)
    ap.add_argument('--dilate', type=int, default=14)
    ap.add_argument('--feather', type=int, default=6)
    ap.add_argument('--keep-frames', default='')
    a = ap.parse_args()
    from rembg import remove, new_session

    sess = new_session('u2net')
    tmp = tempfile.mkdtemp(prefix='ccomp_')
    subprocess.run([exe('ffmpeg'), '-v', 'error', '-y', '-i', a.clip, os.path.join(tmp, 'g_%05d.png')], check=True)
    gen = sorted(f for f in os.listdir(tmp) if f.startswith('g_'))
    ps = json.load(open(os.path.join(a.plates, 'plateset.json')))
    n = min(len(gen), int(ps['frames']))
    outdir = a.keep_frames or os.path.join(tmp, 'out')
    os.makedirs(outdir, exist_ok=True)
    stats = []
    for k in range(1, n + 1):
        g = cv2.imread(os.path.join(tmp, gen[k - 1]), cv2.IMREAD_COLOR)
        bg = cv2.imread(os.path.join(a.plates, ps['bg'] % k), cv2.IMREAD_COLOR)
        m = cv2.imread(os.path.join(a.plates, ps['mask'] % k), cv2.IMREAD_GRAYSCALE)
        H, W = bg.shape[:2]
        if g.shape[:2] != (H, W):
            g = cv2.resize(g, (W, H), interpolation=cv2.INTER_AREA)
        hole = (m > 127).astype(np.uint8)
        hole = cv2.dilate(hole, np.ones((5, 5), np.uint8))
        clean = cv2.inpaint(bg, hole * 255, 5, cv2.INPAINT_TELEA)
        rgba = np.array(remove(Image.fromarray(cv2.cvtColor(g, cv2.COLOR_BGR2RGB)), session=sess))
        alpha = rgba[:, :, 3].astype(np.float32) / 255.0
        # keep every foreground component that touches the dilated proxy matte (the stick
        # the boy swings reaches far outside the proxy's silhouette; a wall the model
        # invented does not touch it)
        near = cv2.dilate((m > 127).astype(np.uint8), np.ones((2 * a.dilate + 1,) * 2, np.uint8))
        fg = (alpha > 0.5).astype(np.uint8)
        ncomp, lab = cv2.connectedComponents(fg)
        keep = np.zeros_like(fg)
        for c in range(1, ncomp):
            comp_m = lab == c
            if (near[comp_m] > 0).any():
                keep[comp_m] = 1
        lim = cv2.dilate(keep, np.ones((2 * a.feather + 1,) * 2, np.uint8)).astype(np.float32)
        lim = cv2.GaussianBlur(lim, (0, 0), a.feather)
        alpha = np.clip(alpha * lim, 0, 1)
        alpha = cv2.GaussianBlur(alpha, (0, 0), max(1, a.feather // 3))
        comp = g.astype(np.float32) * alpha[..., None] + clean.astype(np.float32) * (1 - alpha[..., None])
        cv2.imwrite(os.path.join(outdir, 'c_%05d.png' % k), comp.astype(np.uint8))
        stats.append(float(alpha.mean()))
    subprocess.run(
        [
            exe('ffmpeg'),
            '-v',
            'error',
            '-y',
            '-framerate',
            str(a.fps),
            '-i',
            os.path.join(outdir, 'c_%05d.png'),
            '-c:v',
            'libx264',
            '-crf',
            '14',
            '-pix_fmt',
            'yuv420p',
            a.out,
        ],
        check=True,
    )
    if not a.keep_frames:
        shutil.rmtree(tmp, ignore_errors=True)
    print(
        json.dumps(
            {
                'out': a.out,
                'frames': n,
                'alpha_mean': round(sum(stats) / len(stats), 4),
                'alpha_min': round(min(stats), 4),
            }
        )
    )


if __name__ == '__main__':
    main()
