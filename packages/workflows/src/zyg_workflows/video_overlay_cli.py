# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Command line and self-test of `zyg_workflows.video_overlay`, moved out of the library module.

The library file sits above the brand line (800 lines); its logic stays there and
only connects to this entry point, which `python -m zyg_workflows.video_overlay` still reaches.
"""

import argparse
import json
import os
import shutil
import sys
import tempfile
import time

from zyg_workflows.video_overlay import (
    FFMPEG,
    GRENADE_MOV,
    GRENADE_WEBM,
    MIN_BOX_DIFF,
    REF_TOL,
    _frame_at,
    _ref_box_diff,
    _run,
    _zyg_log,
    composite,
)


def _selftest():
    import numpy as np
    from PIL import Image

    tmp = tempfile.mkdtemp(prefix='vov_selftest_')
    failures = []
    try:
        # ---- static synthetic base (testsrc2 animates; a flat colour cannot)
        base = os.path.join(tmp, 'base.mp4')
        p = _run(
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
                base,
            ]
        )
        if p.returncode != 0:
            raise RuntimeError(p.stderr)

        # ---- (1) synthetic RGBA PNG element: a red disc -------------------
        edir = os.path.join(tmp, 'disc')
        os.makedirs(edir)
        yy, xx = np.mgrid[0:200, 0:200]
        inside = ((xx - 100) ** 2 + (yy - 100) ** 2) <= 90**2
        rgba = np.zeros((200, 200, 4), dtype=np.uint8)
        rgba[..., 0] = 255
        rgba[..., 3] = np.where(inside, 255, 0).astype(np.uint8)
        for n in range(1, 13):
            Image.fromarray(rgba, 'RGBA').save(os.path.join(edir, 'f_%04d.png' % n))

        rec1 = {
            'layers': [
                {
                    'element': edir,
                    'x': 0.25,
                    'y': 0.6,
                    'height': 0.2,
                    'start_s': 1.0,
                    'end_s': 4.0,
                    'loop': True,
                    'fps': 24,
                }
            ],
            'draft': {'width': 480, 'fps': 12},
        }
        out1 = os.path.join(tmp, 'out1.mp4')
        r1 = composite(base, rec1, out1)
        _zyg_log.info(' '.join(str(a) for a in ('receipt 1:', json.dumps(r1, indent=None))))

        px, py = int(0.25 * 1280), int(0.6 * 720 - 0.1 * 720)
        hot = _frame_at(out1, 2.5, os.path.join(tmp, 't25.png'))[py, px]
        cold = _frame_at(out1, 0.5, os.path.join(tmp, 't05.png'))[py, px]
        _zyg_log.info('  (1) pixel(%d,%d) t=2.5 -> %s   t=0.5 -> %s' % (px, py, hot, cold))
        if not (hot[0] > 180 and hot[1] < 90 and hot[2] < 90):
            failures.append('(1) element not red at t=2.5: %s' % (hot,))
        if cold[0] > 180 and cold[1] < 90 and cold[2] < 90:
            failures.append('(1) element visible before start_s at t=0.5: %s' % (cold,))

        # ---- (2) real CC0 element over the same base ----------------------
        rec2 = {
            'layers': [
                {
                    'element': GRENADE_MOV,
                    'x': 0.5,
                    'y': 0.9,
                    'height': 0.35,
                    'start_s': 0.5,
                    'speed': 1.0,
                    'warm': [1.0, 0.93, 0.80],
                }
            ],
            'draft': {'width': 480, 'fps': 12},
        }
        out2 = os.path.join(tmp, 'out2.mp4')
        r2 = composite(base, rec2, out2)
        _zyg_log.info(' '.join(str(a) for a in ('receipt 2:', json.dumps(r2, indent=None))))
        bx, by, bw, bh = r2['layers'][0]['placed_px']

        a = _frame_at(out2, 1.5, os.path.join(tmp, 'm15.png'))
        b = _frame_at(out2, 0.2, os.path.join(tmp, 'm02.png'))
        dbox = float(np.abs(a[by : by + bh, bx : bx + bw] - b[by : by + bh, bx : bx + bw]).mean())
        dcorner = float(np.abs(a[0:40, 0:40] - b[0:40, 0:40]).max())
        ref = _ref_box_diff(GRENADE_MOV, 1.0, (bx, by, bw, bh), 128.0, [1.0, 0.93, 0.80], os.path.join(tmp, 'ref2.png'))
        _zyg_log.info(
            '  (2) placed box mean|diff| = %.3f (numpy reference %.3f)   corner max|diff| = %.3f' % (dbox, ref, dcorner)
        )
        if not dbox > MIN_BOX_DIFF:
            failures.append('(2) placed box barely changed: %.3f (want > %.1f)' % (dbox, MIN_BOX_DIFF))
        if not abs(dbox - ref) <= REF_TOL * ref:
            failures.append(
                '(2) render %.3f disagrees with the numpy reference %.3f by more than %d%%' % (dbox, ref, REF_TOL * 100)
            )
        if dcorner != 0:
            failures.append('(2) untouched corner changed by %.3f (alpha not honoured)' % dcorner)

        # ---- (3) draft of the SAME record ---------------------------------
        out3 = os.path.join(tmp, 'out3.mp4')
        t0 = time.time()
        r3 = composite(base, rec2, out3, draft=True)
        wall = time.time() - t0
        _zyg_log.info(' '.join(str(a) for a in ('receipt 3:', json.dumps(r3, indent=None))))
        _zyg_log.info('  (3) draft width=%s wall=%.2fs' % (r3['width'], wall))
        if r3['width'] != 480:
            failures.append('(3) draft width is %s, want 480' % r3['width'])
        if not wall < 20:
            failures.append('(3) draft took %.2fs, want < 20s' % wall)

        # ---- (4) the webm variant, alpha via libvpx-vp9 --------------------
        rec4 = json.loads(json.dumps(rec2))
        rec4['layers'][0]['element'] = GRENADE_WEBM
        out4 = os.path.join(tmp, 'out4.mp4')
        r4 = composite(base, rec4, out4)
        _zyg_log.info(' '.join(str(a) for a in ('receipt 4:', json.dumps(r4, indent=None))))
        bx, by, bw, bh = r4['layers'][0]['placed_px']
        a = _frame_at(out4, 1.5, os.path.join(tmp, 'w15.png'))
        b = _frame_at(out4, 0.2, os.path.join(tmp, 'w02.png'))
        dbox4 = float(np.abs(a[by : by + bh, bx : bx + bw] - b[by : by + bh, bx : bx + bw]).mean())
        ref4 = _ref_box_diff(
            GRENADE_WEBM, 1.0, (bx, by, bw, bh), 128.0, [1.0, 0.93, 0.80], os.path.join(tmp, 'ref4.png')
        )
        _zyg_log.info('  (4) webm placed box mean|diff| = %.3f (numpy reference %.3f)' % (dbox4, ref4))
        if not dbox4 > MIN_BOX_DIFF:
            failures.append(
                '(4) webm placed box barely changed: %.3f (want > %.1f) '
                '- alpha probably lost to the native vp9 decoder' % (dbox4, MIN_BOX_DIFF)
            )
        if not abs(dbox4 - ref4) <= REF_TOL * ref4:
            failures.append(
                '(4) webm render %.3f disagrees with the numpy reference '
                '%.3f by more than %d%%' % (dbox4, ref4, REF_TOL * 100)
            )

        # ---- (5) the height ramp -------------------------------------------
        # 0.1 -> 0.3 over 1.0..4.0 s, measured on the red disc's own bounding
        # box: at t=1.2 the ramp is 6.7 % through (0.113) and at t=3.8 it is
        # 93.3 % through (0.287), so the later blob must be ~2.5x the earlier.
        rec5 = {
            'layers': [
                {
                    'element': edir,
                    'x': 0.5,
                    'y': 0.9,
                    'height': 0.1,
                    'height_end': 0.3,
                    'start_s': 1.0,
                    'end_s': 4.0,
                    'loop': True,
                    'fps': 24,
                }
            ],
            'draft': {'width': 480, 'fps': 12},
        }
        out5 = os.path.join(tmp, 'out5.mp4')
        r5 = composite(base, rec5, out5)
        _zyg_log.info(' '.join(str(a) for a in ('receipt 5:', json.dumps(r5, indent=None))))

        def _blob_h(t, png):
            fr = _frame_at(out5, t, os.path.join(tmp, png))
            red = (fr[..., 0] > 150) & (fr[..., 1] < 90)
            rows = np.nonzero(red.any(axis=1))[0]
            return int(rows.max() - rows.min() + 1) if rows.size else 0

        h_early, h_late = _blob_h(1.2, 'r12.png'), _blob_h(3.8, 'r38.png')
        ratio = h_late / float(h_early) if h_early else 0.0
        _zyg_log.info('  (5) red blob height t=1.2 -> %d px, t=3.8 -> %d px (x%.2f)' % (h_early, h_late, ratio))
        if h_early <= 0:
            failures.append('(5) no red blob at t=1.2 - the ramped layer never appeared')
        elif not ratio >= 2.2:
            failures.append('(5) the height ramp grew the element only x%.2f (want >= 2.2)' % ratio)

        # ---- (6) tint colorizes by luma -------------------------------------
        # The red disc is pure (255,0,0): luma 76.2, so a sand tint turns it
        # into a dull ochre -- R > G > B with the tint's own ordering, and the
        # hue is gone.  Its spread is bounded by its luma ((R-B) can only reach
        # 76.2 * (0.9-0.45) = 34), so the >= 40 spread is measured on a second
        # disc at the brightness the real dust elements actually carry.
        sdir = os.path.join(tmp, 'pale')
        os.makedirs(sdir)
        pale = np.zeros((200, 200, 4), dtype=np.uint8)
        pale[..., 0] = pale[..., 1] = pale[..., 2] = 230
        pale[..., 3] = rgba[..., 3]
        for n in range(1, 13):
            Image.fromarray(pale, 'RGBA').save(os.path.join(sdir, 'f_%04d.png' % n))

        TINT = [0.9, 0.7, 0.45]
        rec6 = {
            'layers': [
                {
                    'element': edir,
                    'x': 0.25,
                    'y': 0.6,
                    'height': 0.2,
                    'start_s': 1.0,
                    'end_s': 4.0,
                    'loop': True,
                    'fps': 24,
                    'tint': TINT,
                },
                {
                    'element': sdir,
                    'x': 0.75,
                    'y': 0.6,
                    'height': 0.2,
                    'start_s': 1.0,
                    'end_s': 4.0,
                    'loop': True,
                    'fps': 24,
                    'tint': TINT,
                },
            ],
            'draft': {'width': 480, 'fps': 12},
        }
        out6 = os.path.join(tmp, 'out6.mp4')
        r6 = composite(base, rec6, out6)
        _zyg_log.info(' '.join(str(a) for a in ('receipt 6:', json.dumps(r6, indent=None))))

        fr6 = _frame_at(out6, 2.5, os.path.join(tmp, 't6.png'))
        red_px = fr6[py, int(0.25 * 1280)].astype(np.int32)
        pale_px = fr6[py, int(0.75 * 1280)].astype(np.int32)
        _zyg_log.info(
            '  (6) tint %s -> red disc %s (R-B %d), pale disc %s (R-B %d)'
            % (TINT, tuple(red_px), red_px[0] - red_px[2], tuple(pale_px), pale_px[0] - pale_px[2])
        )
        if not (red_px[0] > red_px[1] > red_px[2]):
            failures.append('(6) tinted red disc is not R>G>B: %s' % (tuple(red_px),))
        if not (pale_px[0] > pale_px[1] > pale_px[2]):
            failures.append('(6) tinted pale disc is not R>G>B: %s' % (tuple(pale_px),))
        if not (pale_px[0] - pale_px[2]) >= 40:
            failures.append('(6) tinted disc R-B is %d, want >= 40' % (pale_px[0] - pale_px[2]))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    if failures:
        for f in failures:
            _zyg_log.info(' '.join(str(a) for a in ('FAIL:', f)))
        return 1
    _zyg_log.info('SELFTEST OK')
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--in', dest='video_in')
    ap.add_argument('--record')
    ap.add_argument('--out')
    ap.add_argument('--draft', action='store_true')
    ap.add_argument('--verbose', action='store_true')
    ap.add_argument('--selftest', action='store_true')
    a = ap.parse_args(argv)

    if a.selftest:
        return _selftest()
    if not (a.video_in and a.record and a.out):
        ap.error('--in, --record and --out are required (or use --selftest)')
    with open(a.record, 'r', encoding='utf-8') as fh:
        record = json.load(fh)
    receipt = composite(
        a.video_in, record, a.out, draft=a.draft, log=(lambda m: print(m, file=sys.stderr)) if a.verbose else None
    )
    print(json.dumps(receipt, indent=2))
    return 0


if __name__ == '__main__':
    sys.exit(main())
