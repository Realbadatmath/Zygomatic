#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Outside check of video_overlay's take-2 layer keys: saturation, height_end.

The module's own --selftest proves the ramp GROWS (case 5). This proves the two
things that case cannot: that ``saturation`` actually moves the colour the way
a saturation control should, and that the ramp's extra scale pass has not cost
the composite any accuracy -- a layer whose height_end EQUALS its height goes
down the ramped code path (two scales, the second on straight alpha) and must
still agree with an independent numpy composite of the same element frame as
closely as the single-scale path does.

    ../.venv/bin/python tests_vst/check_overlay_take2.py
"""

import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402

from zyg_workflows import video_overlay as V  # noqa: E402

FFMPEG = V.FFMPEG


def _base(tmp):
    p = os.path.join(tmp, 'base.mp4')
    r = subprocess.run(
        [
            FFMPEG,
            '-hide_banner',
            '-v',
            'error',
            '-y',
            '-f',
            'lavfi',
            '-i',
            'color=c=0x808080:s=1280x720:r=24:d=5',
            '-c:v',
            'libx264',
            '-crf',
            '12',
            '-pix_fmt',
            'yuv420p',
            p,
        ],
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, r.stderr
    return p


def _disc(tmp):
    d = os.path.join(tmp, 'disc')
    os.makedirs(d)
    yy, xx = np.mgrid[0:200, 0:200]
    rgba = np.zeros((200, 200, 4), np.uint8)
    rgba[..., 0] = 220
    rgba[..., 1] = 40
    rgba[..., 2] = 40
    rgba[..., 3] = np.where(((xx - 100) ** 2 + (yy - 100) ** 2) <= 90**2, 255, 0).astype(np.uint8)
    for n in range(1, 13):
        Image.fromarray(rgba, 'RGBA').save(os.path.join(d, 'f_%04d.png' % n))
    return d


def main():
    tmp = tempfile.mkdtemp(prefix='vov_take2_')
    fails = []
    try:
        base, disc = _base(tmp), _disc(tmp)

        # ---- saturation --------------------------------------------------
        got = {}
        for name, sat in (('grey', 0.0), ('asis', 1.0), ('hot', 1.8)):
            rec = {
                'layers': [
                    {
                        'element': disc,
                        'x': 0.5,
                        'y': 0.6,
                        'height': 0.3,
                        'start_s': 0.5,
                        'saturation': sat,
                        'loop': True,
                        'fps': 24,
                    }
                ]
            }
            out = os.path.join(tmp, 'sat_%s.mp4' % name)
            V.composite(base, rec, out)
            px = V._frame_at(out, 2.0, os.path.join(tmp, 'sat_%s.png' % name))
            got[name] = px[int(0.6 * 720) - 40, 640]
        for name in ('grey', 'asis', 'hot'):
            print('  saturation %-4s centre pixel -> %s' % (name, got[name]))
        spread = lambda p: float(p.max() - p.min())  # noqa: E731
        luma = lambda p: float(np.dot(p, [0.2126, 0.7152, 0.0722]))  # noqa: E731
        if not spread(got['grey']) < 6:
            fails.append('saturation=0 left %.1f of colour spread' % spread(got['grey']))
        if not spread(got['hot']) > spread(got['asis']) * 1.2:
            fails.append(
                'saturation=1.8 spread %.1f is not clearly above the '
                'unsaturated %.1f' % (spread(got['hot']), spread(got['asis']))
            )
        # The whole point of the Rec.709 matrix: desaturating must not darken.
        dl = abs(luma(got['grey']) - luma(got['asis']))
        print('  saturation=0 luma %.1f vs as-shot %.1f (%.1f apart)' % (luma(got['grey']), luma(got['asis']), dl))
        if dl > 3:
            fails.append('saturation=0 moved the Rec.709 luma by %.1f (it should keep it)' % dl)

        # ---- the ramped code path is still accurate ----------------------
        # height_end == height: same picture as a plain layer, but rendered
        # through the two-scale ramp chain.
        flat = {
            'layers': [
                {
                    'element': V.GRENADE_MOV,
                    'x': 0.5,
                    'y': 0.9,
                    'height': 0.35,
                    'height_end': 0.35,
                    'start_s': 0.5,
                    'end_s': 5.0,
                    'warm': [1.0, 0.93, 0.80],
                }
            ]
        }
        out = os.path.join(tmp, 'flat.mp4')
        r = V.composite(base, flat, out)
        bx, by, bw, bh = r['layers'][0]['placed_px']
        assert r['layers'][0]['height_px_end'] == bh, r['layers'][0]
        a = V._frame_at(out, 1.5, os.path.join(tmp, 'f15.png'))
        b = V._frame_at(out, 0.2, os.path.join(tmp, 'f02.png'))
        dbox = float(np.abs(a[by : by + bh, bx : bx + bw] - b[by : by + bh, bx : bx + bw]).mean())
        ref = V._ref_box_diff(
            V.GRENADE_MOV, 1.0, (bx, by, bw, bh), 128.0, [1.0, 0.93, 0.80], os.path.join(tmp, 'ref.png')
        )
        dcorner = float(np.abs(a[0:40, 0:40] - b[0:40, 0:40]).max())
        print(
            '  flat ramp box mean|diff| = %.3f (numpy reference %.3f, %.1f%% '
            'apart)   corner max|diff| = %.3f' % (dbox, ref, 100 * abs(dbox - ref) / ref, dcorner)
        )
        if not abs(dbox - ref) <= V.REF_TOL * ref:
            fails.append(
                'the ramped chain renders %.3f against a %.3f numpy reference (> %d%%)' % (dbox, ref, V.REF_TOL * 100)
            )
        if dcorner != 0:
            fails.append('the ramped chain touched an untouched corner by %.3f' % dcorner)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    if fails:
        for f in fails:
            print('FAIL:', f)
        return 1
    print('CHECK OK')
    return 0


if __name__ == '__main__':
    sys.exit(main())
