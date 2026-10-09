# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Composite a character cut-out into a plate set's frame-1 background at the actor matte.

    python3 tools/keyframe_still.py PLATES_DIR CHARACTER_PNG OUT_PNG [--ref-out WHITE_PNG]

Used by scene_shot_run (video.keyframe) so VACE extends from a frame that already shows the
character in the scene (2026-09-20: the still it had was the grey proxy, and it animated that).
"""

import argparse
import os
import numpy as np
from PIL import Image


def cutout(path):
    from rembg import remove, new_session

    im = Image.open(path).convert('RGB')
    cut = remove(im, session=new_session('u2net'))
    a = np.array(cut)[:, :, 3]
    ys, xs = np.where(a > 64)
    return cut.crop((xs.min(), ys.min(), xs.max() + 1, ys.max() + 1))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('plates')
    ap.add_argument('character')
    ap.add_argument('out')
    ap.add_argument('--ref-out', default='')
    ap.add_argument('--frame', type=int, default=1)
    a = ap.parse_args()
    m = np.array(Image.open(os.path.join(a.plates, 'm_%05d.png' % a.frame)).convert('L')) > 128
    ys, xs = np.where(m)
    x0, x1, y0, y1 = xs.min(), xs.max(), ys.min(), ys.max()
    cut = cutout(a.character)
    h = y1 - y0 + 1
    w = int(round(cut.size[0] * h / cut.size[1]))
    c2 = cut.resize((w, h), Image.LANCZOS)
    bg = Image.open(os.path.join(a.plates, 'bg_%05d.png' % a.frame)).convert('RGB')
    out = bg.copy()
    out.paste(c2, ((x0 + x1) // 2 - w // 2, y1 - h + 1), c2)
    out.save(a.out)
    if a.ref_out:
        wb = Image.new('RGB', cut.size, 'white')
        wb.paste(cut, (0, 0), cut)
        wb.save(a.ref_out)
    print('keyframe still', a.out, 'matte h', h, 'placed w', w)


if __name__ == '__main__':
    main()
