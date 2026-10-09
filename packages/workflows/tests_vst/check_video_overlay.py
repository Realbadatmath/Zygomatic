#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Outside check for video_overlay.py: everything --selftest does not cover.

Covers: horizon tracking (magnitude + sign + the overlay actually following),
'screen' blend, speed, flip_h, blur, the three anchors, the portrait tornado
element, a real RGBA PNG-sequence master, loop, and audio pass-through.

Run:  "$ZYG_SERVER_PYTHON" \
        tests_vst/check_video_overlay.py
Exit 0 = all checks pass.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile

import numpy as np
from PIL import Image
from zyg_workflows.paths import ZYG_CREWS_ROOT

CREWS = str(ZYG_CREWS_ROOT)
sys.path.insert(0, CREWS)
from zyg_workflows import video_overlay as V  # noqa: E402

VFX = os.path.join(CREWS, 'data/asset_libraries/vfx_volumes')
TORNADO_MOV = os.path.join(VFX, 'tornadoloopingvdb_4k.mov')
#: The VFX element frames rendered beside the crews tree; $ZYG_VFX_ELEMENTS overrides it.
VFX_ELEMENTS = os.environ.get('ZYG_VFX_ELEMENTS') or str(ZYG_CREWS_ROOT.parents[1] / 'output' / 'vfx_elements')
PNG_MASTER = os.path.join(VFX_ELEMENTS, 'grenadedustimpactvdb_4k')

FAILS = []


def check(name, ok, detail=''):
    print('  %-46s %s  %s' % (name, 'PASS' if ok else 'FAIL', detail))
    if not ok:
        FAILS.append('%s: %s' % (name, detail))


def ff(*args):
    p = subprocess.run([V.FFMPEG, '-hide_banner', '-v', 'error', '-y'] + list(args), capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError('ffmpeg failed: %s\n%s' % (' '.join(args), p.stderr[-2000:]))


def frame(video, t, png):
    ff('-ss', '%.3f' % t, '-i', video, '-frames:v', '1', png)
    with Image.open(png) as im:
        return np.asarray(im.convert('RGB')).astype('float32')


def disc_dir(path, n=6, size=200, radius=90, rgb=(255, 0, 0)):
    os.makedirs(path, exist_ok=True)
    yy, xx = np.mgrid[0:size, 0:size]
    inside = ((xx - size // 2) ** 2 + (yy - size // 2) ** 2) <= radius**2
    a = np.zeros((size, size, 4), dtype=np.uint8)
    for c in range(3):
        a[..., c] = rgb[c]
    a[..., 3] = np.where(inside, 255, 0).astype(np.uint8)
    for i in range(1, n + 1):
        Image.fromarray(a, 'RGBA').save(os.path.join(path, 'f_%04d.png' % i))
    return path


def red_centre(img, box):
    """Centroid x of red-ish pixels inside box, or None."""
    x, y, w, h = box
    sub = img[max(0, y) : y + h, max(0, x) : x + w]
    m = (sub[..., 0] > 170) & (sub[..., 1] < 100) & (sub[..., 2] < 100)
    if m.sum() < 50:
        return None
    return float(np.argwhere(m)[:, 1].mean()) + max(0, x)


def main():
    tmp = tempfile.mkdtemp(prefix='vov_check_')
    try:
        # ---------------------------------------------------------------
        # base A: flat grey, no audio
        base = os.path.join(tmp, 'base.mp4')
        ff(
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
        )

        # base B: a real pan -- a static still cropped by a moving window.
        # The still is a sum of three octaves of smooth greyscale noise, which
        # is what footage looks like to a phase correlation.  Uniform pixel
        # noise is not a fair test (a 4x downscale aliases it into nothing)
        # and a periodic pattern locks onto false peaks.  Greyscale also
        # keeps red_centre() from picking up the background.
        import cv2

        rng = np.random.default_rng(7)
        g = np.zeros((720, 2560), np.float32)
        for sh, sw, wt in ((45, 160, 1.0), (90, 320, 0.5), (180, 640, 0.25)):
            g += wt * cv2.resize(rng.random((sh, sw)).astype(np.float32), (2560, 720), interpolation=cv2.INTER_CUBIC)
        g = (g - g.min()) / (g.max() - g.min())
        still = np.repeat((g * 235 + 10).astype(np.uint8)[..., None], 3, axis=2)
        still_png = os.path.join(tmp, 'still.png')
        Image.fromarray(still).save(still_png)
        pan = os.path.join(tmp, 'pan.mp4')
        ff(
            '-loop',
            '1',
            '-framerate',
            '24',
            '-i',
            still_png,
            '-vf',
            "crop=1280:720:'min(t*60,1200)':0,fps=24",
            '-t',
            '4',
            '-c:v',
            'libx264',
            '-crf',
            '10',
            '-pix_fmt',
            'yuv420p',
            pan,
        )

        # base C: grey with audio
        base_a = os.path.join(tmp, 'base_audio.mp4')
        ff(
            '-f',
            'lavfi',
            '-i',
            'color=c=0x808080:s=640x360:r=24:d=3',
            '-f',
            'lavfi',
            '-i',
            'sine=f=440:d=3',
            '-c:v',
            'libx264',
            '-crf',
            '20',
            '-pix_fmt',
            'yuv420p',
            '-c:a',
            'aac',
            '-shortest',
            base_a,
        )

        print('\n[1] horizon track: magnitude, sign, and the overlay following')
        track = V._horizon_track(pan)
        dxs = [t[1] for t in track]
        # the window moves right at 60 px/s for the first 20 s (capped at 1200),
        # so at t=3 the content has moved 180 px to the LEFT of frame 0
        at3 = dxs[min(len(dxs) - 1, int(3 * 24))]
        check('track magnitude at t=3 ~ 180 px', abs(abs(at3) - 180) < 6, 'measured |dx|=%.1f' % abs(at3))
        check('track sign: content moved left -> dx < 0', at3 < 0, 'dx=%.1f' % at3)
        # the window moves at a constant 60 px/s, so every sample must sit on
        # the ramp -- this is the check that catches spurious correlation peaks
        err = max(abs(dx + min(t * 60, 1200)) for (t, dx, _dy) in track)
        check(
            'every sample on the 60 px/s ramp (max err < 5 px)',
            err < 5,
            'max err %.2f px over %d frames' % (err, len(track)),
        )
        dyerr = max(abs(t[2]) for t in track)
        check('no phantom vertical drift on a horizontal pan', dyerr < 5, 'max |dy| %.2f px' % dyerr)

        d = disc_dir(os.path.join(tmp, 'disc'))
        rec_tr = {
            'layers': [
                {'element': d, 'x': 0.5, 'y': 0.5, 'anchor': 'center', 'height': 0.1, 'track': 'horizon', 'loop': True}
            ]
        }
        out_tr = os.path.join(tmp, 'tr.mp4')
        r = V.composite(pan, rec_tr, out_tr)
        check(
            'tracked layer flagged in the receipt',
            r['layers'][0]['tracked'] is True,
            json.dumps(r['layers'][0]['placed_px']),
        )
        bx, by, bw, bh = r['layers'][0]['placed_px']
        c0 = red_centre(frame(out_tr, 0.1, os.path.join(tmp, 'a.png')), (bx - 260, by - 40, bw + 520, bh + 80))
        c3 = red_centre(frame(out_tr, 3.0, os.path.join(tmp, 'b.png')), (bx - 260, by - 40, bw + 520, bh + 80))
        check(
            'overlay moved with the scene (~180 px left)',
            c0 is not None and c3 is not None and abs((c0 - c3) - 180) < 20,
            'x %.1f -> %.1f' % (c0 or -1, c3 or -1),
        )

        print('\n[2] untracked control: the same layer must not move')
        rec_no = json.loads(json.dumps(rec_tr))
        rec_no['layers'][0]['track'] = 'none'
        out_no = os.path.join(tmp, 'notr.mp4')
        V.composite(pan, rec_no, out_no)
        n0 = red_centre(frame(out_no, 0.1, os.path.join(tmp, 'c.png')), (bx - 260, by - 40, bw + 520, bh + 80))
        n3 = red_centre(frame(out_no, 3.0, os.path.join(tmp, 'd.png')), (bx - 260, by - 40, bw + 520, bh + 80))
        check(
            'untracked layer stays put', n0 is not None and abs(n0 - n3) < 2.0, 'x %.1f -> %.1f' % (n0 or -1, n3 or -1)
        )

        print('\n[3] anchors place the element where _anchor_xy says')
        for anchor, (fx, fy) in (('top-left', (0.1, 0.1)), ('center', (0.5, 0.5)), ('bottom-center', (0.75, 0.8))):
            rec = {'layers': [{'element': d, 'x': fx, 'y': fy, 'anchor': anchor, 'height': 0.2, 'loop': True}]}
            o = os.path.join(tmp, 'anc_%s.mp4' % anchor)
            rr = V.composite(base, rec, o)
            px, py, pw, ph = rr['layers'][0]['placed_px']
            img = frame(o, 1.0, os.path.join(tmp, 'anc.png'))
            cx = red_centre(img, (0, 0, 1280, 720))
            check(
                'anchor %s' % anchor,
                cx is not None and abs(cx - (px + pw / 2.0)) < 3.0,
                'receipt centre %.1f, measured %.1f' % (px + pw / 2.0, cx or -1),
            )

        print('\n[4] flip_h / blur / opacity')
        # an asymmetric element: red left half opaque, right half transparent
        asym = os.path.join(tmp, 'asym')
        os.makedirs(asym)
        a = np.zeros((100, 200, 4), dtype=np.uint8)
        a[..., 0] = 255
        a[:, :100, 3] = 255
        for i in range(1, 4):
            Image.fromarray(a, 'RGBA').save(os.path.join(asym, 'f_%04d.png' % i))
        for flip, want_left in ((False, True), (True, False)):
            rec = {
                'layers': [
                    {
                        'element': asym,
                        'x': 0.5,
                        'y': 0.5,
                        'anchor': 'center',
                        'height': 0.2,
                        'flip_h': flip,
                        'loop': True,
                    }
                ]
            }
            o = os.path.join(tmp, 'flip_%s.mp4' % flip)
            rr = V.composite(base, rec, o)
            px, py, pw, ph = rr['layers'][0]['placed_px']
            img = frame(o, 1.0, os.path.join(tmp, 'flip.png'))
            cx = red_centre(img, (px, py, pw, ph))
            got_left = cx < px + pw / 2.0
            check(
                'flip_h=%s puts the opaque half %s' % (flip, 'left' if want_left else 'right'),
                got_left == want_left,
                'centroid %.1f in box x %d..%d' % (cx, px, px + pw),
            )

        rec = {
            'layers': [
                {'element': d, 'x': 0.5, 'y': 0.5, 'anchor': 'center', 'height': 0.2, 'opacity': 0.5, 'loop': True}
            ]
        }
        o = os.path.join(tmp, 'op.mp4')
        rr = V.composite(base, rec, o)
        px, py, pw, ph = rr['layers'][0]['placed_px']
        v = frame(o, 1.0, os.path.join(tmp, 'op.png'))[py + ph // 2, px + pw // 2]
        check(
            'opacity 0.5 -> half-way to the base',
            abs(v[0] - 191) < 12 and v[1] > 40,
            'pixel %s (want ~[191,64,64])' % v,
        )

        rec = {
            'layers': [{'element': d, 'x': 0.5, 'y': 0.5, 'anchor': 'center', 'height': 0.2, 'blur': 8.0, 'loop': True}]
        }
        o = os.path.join(tmp, 'blur.mp4')
        rr = V.composite(base, rec, o)
        px, py, pw, ph = rr['layers'][0]['placed_px']
        img = frame(o, 1.0, os.path.join(tmp, 'blur.png'))
        edge = img[py + ph // 2, px : px + pw, 0]
        # the unblurred take, written beside blur.png as the eye-check reference
        frame(os.path.join(tmp, 'anc_center.mp4'), 1.0, os.path.join(tmp, 'sharp.png'))
        check(
            'blur softens the element edge',
            int((np.abs(np.diff(edge)) > 4).sum()) > 8,
            '%d transition pixels across the disc' % int((np.abs(np.diff(edge)) > 4).sum()),
        )

        print('\n[5] speed retimes the element')
        # 24 distinct frames: the disc's red channel steps 10,20,...240
        ramp = os.path.join(tmp, 'ramp')
        os.makedirs(ramp)
        for i in range(1, 25):
            b = np.zeros((100, 100, 4), dtype=np.uint8)
            b[..., 0] = i * 10
            b[..., 3] = 255
            Image.fromarray(b, 'RGBA').save(os.path.join(ramp, 'f_%04d.png' % i))
        vals = {}
        for sp in (1.0, 0.5):
            rec = {
                'layers': [
                    {
                        'element': ramp,
                        'x': 0.5,
                        'y': 0.5,
                        'anchor': 'center',
                        'height': 0.2,
                        'speed': sp,
                        'loop': False,
                        'fps': 24,
                    }
                ]
            }
            o = os.path.join(tmp, 'sp_%s.mp4' % sp)
            rr = V.composite(base, rec, o)
            px, py, pw, ph = rr['layers'][0]['placed_px']
            vals[sp] = float(frame(o, 0.5, os.path.join(tmp, 'sp.png'))[py + ph // 2, px + pw // 2, 0])
        check('speed 1.0 at t=0.5 ~ element frame 12', abs(vals[1.0] - 120) < 18, 'red=%.0f' % vals[1.0])
        check('speed 0.5 at t=0.5 ~ element frame 6', abs(vals[0.5] - 60) < 18, 'red=%.0f' % vals[0.5])

        print('\n[6] loop=True outlives the element, loop=False does not')
        for loop, want in ((True, True), (False, False)):
            rec = {
                'layers': [
                    {'element': ramp, 'x': 0.5, 'y': 0.5, 'anchor': 'center', 'height': 0.2, 'loop': loop, 'fps': 24}
                ]
            }
            o = os.path.join(tmp, 'loop_%s.mp4' % loop)
            rr = V.composite(base, rec, o)
            px, py, pw, ph = rr['layers'][0]['placed_px']
            v = float(frame(o, 3.0, os.path.join(tmp, 'lp.png'))[py + ph // 2, px + pw // 2, 0])
            present = abs(v - 128) > 12
            check(
                'loop=%s -> element %s at t=3.0 (element is 1.0 s)' % (loop, 'present' if want else 'gone'),
                present == want,
                'red=%.0f' % v,
            )

        print('\n[7] element_offset_s skips into the element')
        rec = {
            'layers': [
                {
                    'element': ramp,
                    'x': 0.5,
                    'y': 0.5,
                    'anchor': 'center',
                    'height': 0.2,
                    'loop': False,
                    'fps': 24,
                    'element_offset_s': 0.5,
                }
            ]
        }
        o = os.path.join(tmp, 'off.mp4')
        rr = V.composite(base, rec, o)
        px, py, pw, ph = rr['layers'][0]['placed_px']
        v = float(frame(o, 0.0, os.path.join(tmp, 'off.png'))[py + ph // 2, px + pw // 2, 0])
        check('offset 0.5 s starts at element frame ~12', abs(v - 130) < 25, 'red=%.0f' % v)

        print('\n[8] screen blend')
        rec = {
            'layers': [
                {'element': d, 'x': 0.5, 'y': 0.5, 'anchor': 'center', 'height': 0.2, 'blend': 'screen', 'loop': True}
            ]
        }
        o = os.path.join(tmp, 'screen.mp4')
        rr = V.composite(base, rec, o)
        check('receipt records blend=screen', rr['layers'][0]['blend'] == 'screen', rr['layers'][0]['blend'])
        px, py, pw, ph = rr['layers'][0]['placed_px']
        img = frame(o, 1.0, os.path.join(tmp, 'screen.png'))
        v = img[py + ph // 2, px + pw // 2]
        corner = float(np.abs(img[0:40, 0:40] - 128).max())
        # screen(base=128, red=255) = 255 for R, base unchanged for G/B
        check('screen brightens R to 255, leaves G/B', v[0] > 250 and abs(v[1] - 128) < 6, 'pixel %s' % v)
        check('screen leaves the rest of the frame alone', corner < 6, 'corner max dev %.1f' % corner)

        print('\n[9] real assets: portrait tornado .mov and a PNG master dir')
        rec = {
            'layers': [
                {'element': TORNADO_MOV, 'x': 0.25, 'y': 0.95, 'height': 0.8, 'loop': True, 'opacity': 0.9},
                {'element': PNG_MASTER, 'x': 0.75, 'y': 0.95, 'height': 0.4, 'start_s': 0.5, 'loop': True, 'fps': 45},
            ]
        }
        o = os.path.join(tmp, 'real.mp4')
        rr = V.composite(base, rec, o)
        print('   receipt:', json.dumps(rr))
        check('two real layers placed', len(rr['layers']) == 2 and rr['frames'] == 120, 'frames=%s' % rr['frames'])
        check(
            'portrait tornado keeps its aspect',
            abs(rr['layers'][0]['placed_px'][2] / float(rr['layers'][0]['placed_px'][3]) - 2934 / 3840.0) < 0.02,
            'w/h=%.3f want %.3f'
            % (rr['layers'][0]['placed_px'][2] / float(rr['layers'][0]['placed_px'][3]), 2934 / 3840.0),
        )
        check(
            'PNG master fps taken from the record (45, not 24)',
            rr['layers'][1]['element_fps'] == 45.0,
            str(rr['layers'][1]['element_fps']),
        )
        img = frame(o, 2.0, os.path.join(tmp, 'real.png'))
        for i in (0, 1):
            px, py, pw, ph = rr['layers'][i]['placed_px']
            px, py = max(0, px), max(0, py)
            dev = float(np.abs(img[py : py + ph, px : px + pw] - 128).mean())
            check('layer %d visibly composited' % i, dev > 3, 'mean dev %.2f' % dev)

        print('\n[10] audio is carried through')
        rec = {'layers': [{'element': d, 'x': 0.5, 'y': 0.5, 'anchor': 'center', 'height': 0.3, 'loop': True}]}
        o = os.path.join(tmp, 'aud.mp4')
        V.composite(base_a, rec, o)
        got = V._probe_video(o)
        check("output keeps the base's audio stream", got['has_audio'] is True, '')

        print('\n[11] draft and final read the same record')
        rec = {
            'layers': [{'element': d, 'x': 0.3, 'y': 0.7, 'height': 0.25, 'loop': True}],
            'draft': {'width': 320, 'fps': 8},
        }
        rf = V.composite(base, rec, os.path.join(tmp, 'f.mp4'))
        rd = V.composite(base, rec, os.path.join(tmp, 'dr.mp4'), draft=True)
        sx = rd['width'] / float(rf['width'])
        fp, dp = rf['layers'][0]['placed_px'], rd['layers'][0]['placed_px']
        check(
            'draft geometry is the final scaled by %.3f' % sx,
            all(abs(dp[k] - fp[k] * sx) <= 2 for k in range(4)),
            'final %s -> draft %s' % (fp, dp),
        )
        check(
            'draft honours width/fps from the record',
            rd['width'] == 320 and abs(rd['fps'] - 8) < 0.01,
            '%sx%s @ %s' % (rd['width'], rd['height'], rd['fps']),
        )
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print('')
    if FAILS:
        for f in FAILS:
            print('FAILED:', f)
        print('%d CHECK(S) FAILED' % len(FAILS))
        return 1
    print('ALL CHECKS PASS')
    return 0


if __name__ == '__main__':
    sys.exit(main())
