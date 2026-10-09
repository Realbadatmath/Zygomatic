# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Take the MOTION from a Wan render and apply it to the artist's own ink.

    /usr/bin/python3 warp_loop.py <render.mp4> <out_basename> [--scale N]

Why not just show the render. Measured on the 896x992 take: with her face locked
and only the mane composited, the mane still comes back visibly re-drawn — the
strokes thicken, the scales blob, the contrast climbs. A diffusion video model
does not move a drawing, it re-imagines one 81 times, and at the board's bar
that reads as a different, worse illustration that happens to wobble.

So this keeps none of the model's pixels. It measures the dense optical flow the
render describes, smooths it into a field that carries coils rather than
strokes, and warps the ORIGINAL drawing along it. What moves is exactly the ink
the artist drew; the model only says where it goes.

Consequences worth knowing:
  * boil cannot survive. A one-pixel shimmer of a stroke is high-frequency,
    spatially incoherent flow, and the smoothing pass is a low-pass filter over
    exactly that. What is left is the bulk motion of the coils.
  * occlusion cannot be invented. Where a coil slides off something, the warp
    stretches its neighbours instead of revealing what is behind. That is fine
    for a few px of sway and wrong for a large one, which is another reason to
    keep the amplitude modest.
  * the flow is CHAINED frame to frame and composed, not measured from frame 0.
    Between distant frames the estimator loses the correspondence entirely; one
    step at a time it is small-motion, which is where it is accurate.
"""

import json
import math
import os
import subprocess
import sys

import cv2
import numpy as np
from zyg_workflows.paths import ZYG_CREWS_ROOT

HERE = os.path.dirname(os.path.abspath(__file__))
MEDUSA = str(ZYG_CREWS_ROOT / 'kanban_assets' / 'medusa')
BASE = os.path.join(MEDUSA, 'medusa_base.jpg')
ALPHA = os.path.join(MEDUSA, 'loop_alpha.png')
SMOOTH = float(os.environ.get('MDZ_SMOOTH', '9'))  # px: how coarse the field is made
GAIN = float(os.environ.get('MDZ_GAIN', '1.0'))  # multiplier on the measured motion
CLAMP = float(os.environ.get('MDZ_CLAMP', '0'))  # px ceiling on displacement, 0 = none
BILAT = float(os.environ.get('MDZ_BILAT', '1.5'))  # flow-units: 0 disables the edge pass
MIN_LOOP = 40
FADE = 4
FLICKS = int(os.environ.get('MDZ_FLICKS', '2'))  # flicks per tongue per loop
OUT_FRAC = 0.30  # of the cycle the tongue is out


def _frames(path):
    cap = cv2.VideoCapture(path)
    fps = cap.get(cv2.CAP_PROP_FPS) or 17.0
    out = []
    while True:
        ok, f = cap.read()
        if not ok:
            break
        out.append(f)
    cap.release()
    return out, fps


def _compose(f_ab, f_bc):
    """Flow a->c from a->b and b->c: sample the second field where the first lands."""
    H, W = f_ab.shape[:2]
    gx, gy = np.meshgrid(np.arange(W, dtype=np.float32), np.arange(H, dtype=np.float32))
    mx, my = gx + f_ab[..., 0], gy + f_ab[..., 1]
    warped = cv2.remap(f_bc, mx, my, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
    return f_ab + warped


def _load_tongues():
    """The 8 tongues, as bake_medusa_masks.py left them: the ink as a sprite, the
    same rect with the ink inpainted away, an anchor on the lip and the angle the
    stroke leaves the mouth on."""
    js = open(os.path.join(MEDUSA, 'snakes.js'), encoding='utf-8').read()
    man = json.loads(js[js.index('{') : js.rindex('}') + 1])
    W, H = man['w'], man['h']
    out = []
    for t in man['tongues']:
        spr = cv2.imread(os.path.join(MEDUSA, t['f']), cv2.IMREAD_UNCHANGED)
        pat = cv2.imread(os.path.join(MEDUSA, t['p']), cv2.IMREAD_COLOR)
        rx, ry = int(round(t['x'] * W)), int(round(t['y'] * H))
        ax, ay = t['ax'] * W, t['ay'] * H
        ang = math.radians(t['ang'])
        reach = 1.0
        for cx, cy in (
            (rx, ry),
            (rx + spr.shape[1], ry),
            (rx, ry + spr.shape[0]),
            (rx + spr.shape[1], ry + spr.shape[0]),
        ):
            reach = max(reach, (cx - ax) * math.cos(ang) + (cy - ay) * math.sin(ang))
        out.append({'spr': spr, 'pat': pat, 'rx': rx, 'ry': ry, 'ax': ax, 'ay': ay, 'ang': ang, 'len': reach + 4})
    return out


def _draw_tongue(frame, t, ext, dx, dy):
    """Slide the tongue out of the mouth along its own axis, clipped at the lip.
    Same geometry as _mdzDrawTongue in kanban_main.js: nothing is scaled, so the
    fork never squashes, and what is not out yet is inside the head."""
    if ext <= 0.01:
        return
    H, W = frame.shape[:2]
    back = (1.0 - ext) * t['len']
    ca, sa = math.cos(t['ang']), math.sin(t['ang'])
    M = np.float32([[1, 0, -back * ca], [0, 1, -back * sa]])
    M[0, 2] += dx
    M[1, 2] += dy
    spr = t['spr']
    canvas = np.zeros((H, W, 4), np.uint8)
    canvas[t['ry'] : t['ry'] + spr.shape[0], t['rx'] : t['rx'] + spr.shape[1]] = spr
    moved = cv2.warpAffine(
        canvas, M, (W, H), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=(0, 0, 0, 0)
    )
    # the lip cuts it off: keep only what is on the outward side of the anchor
    gx, gy = np.meshgrid(np.arange(W, dtype=np.float32), np.arange(H, dtype=np.float32))
    along = (gx - (t['ax'] + dx)) * ca + (gy - (t['ay'] + dy)) * sa
    a = (moved[..., 3].astype(np.float32) / 255.0) * (along > -2.0)
    if not a.any():
        return
    ys, xs = np.nonzero(a > 0.004)
    y0, y1, x0, x1 = ys.min(), ys.max() + 1, xs.min(), xs.max() + 1
    sub_a = a[y0:y1, x0:x1, None]
    frame[y0:y1, x0:x1] = (
        moved[y0:y1, x0:x1, :3].astype(np.float32) * sub_a + frame[y0:y1, x0:x1].astype(np.float32) * (1 - sub_a)
    ).astype(np.uint8)


def main():
    src, outbase = sys.argv[1], sys.argv[2]
    raw, fps = _frames(src)
    if not raw:
        raise SystemExit(f'no frames in {src}')

    base = cv2.imread(BASE)
    H, W = base.shape[:2]
    alpha = (cv2.imread(ALPHA, cv2.IMREAD_GRAYSCALE).astype(np.float32) / 255.0)[..., None]

    # The tongues are drawn, not warped: the layer that moves is the drawing with
    # every drawn tongue inpainted out of it (the tpatch rects), and the eight
    # sprites are stamped back on top, flicking. Warping the drawn tongue instead
    # would give a tongue that sways but never moves, which is what it did on the
    # canvas before the flick existed.
    tongues = _load_tongues() if FLICKS else []
    plate = base.copy()
    for t in tongues:
        plate[t['ry'] : t['ry'] + t['pat'].shape[0], t['rx'] : t['rx'] + t['pat'].shape[1]] = t['pat']

    grey = [cv2.cvtColor(f, cv2.COLOR_BGR2GRAY) for f in raw]
    h, w = grey[0].shape
    sx, sy = W / w, H / h
    print(f'{len(raw)} frames @ {fps:.1f} fps, flow measured at {w}x{h}, applied at {W}x{H} (x{sx:.2f})')

    dis = cv2.DISOpticalFlow_create(cv2.DISOPTICAL_FLOW_PRESET_MEDIUM)
    dis.setUseSpatialPropagation(True)

    # chain: flow[i] carries frame 0 onto frame i
    flows = [np.zeros((h, w, 2), np.float32)]
    for i in range(1, len(grey)):
        step = dis.calc(grey[i - 1], grey[i], None)
        flows.append(_compose(flows[-1], step))

    t_rect = np.zeros((H, W), bool)
    for t in tongues:
        t_rect[
            max(0, t['ry'] - 30) : t['ry'] + t['pat'].shape[0] + 30,
            max(0, t['rx'] - 30) : t['rx'] + t['pat'].shape[1] + 30,
        ] = True

    gx, gy = np.meshgrid(np.arange(W, dtype=np.float32), np.arange(H, dtype=np.float32))
    warped = []
    fields = []
    mags = []
    for f in flows:
        # smooth FIRST at the measured scale, where the boil lives. The second
        # pass is EDGE-PRESERVING on the flow itself: a plain Gaussian blends a
        # moving coil's motion into the still background beside it, and warping
        # by that smeared field drags light paper across the coil's own outline
        # and rubs it out (measured: the head's lip vanished into a white cloud
        # at 11 px). A bilateral filter keeps the jump between "this coil moves"
        # and "that one does not", and a jump in an inverse map is a clean edge,
        # not a smear.
        fs = cv2.GaussianBlur(f, (0, 0), SMOOTH / max(sx, sy))
        if BILAT:
            fs = np.dstack([cv2.bilateralFilter(fs[..., c], -1, BILAT, SMOOTH / max(sx, sy) * 1.5) for c in (0, 1)])
        big = cv2.resize(fs, (W, H), interpolation=cv2.INTER_CUBIC)
        big[..., 0] *= sx * GAIN
        big[..., 1] *= sy * GAIN
        if CLAMP:
            # A ceiling, not a scale: the small motion that reads as a sway is
            # kept intact and only the excursions that stretch the ink into
            # taffy are held back.
            mag = np.hypot(big[..., 0], big[..., 1])
            over = mag > CLAMP
            if over.any():
                k = np.ones_like(mag)
                k[over] = CLAMP / mag[over]
                big *= k[..., None]
        # Taper the MOTION to zero at the lock instead of blending a warped copy
        # against a still one. Cross-fading the two is what put a soft double
        # image under the brow: both layers are the same drawing, so where the
        # warp had moved a coil the ramp showed it twice. A field that fades to
        # nothing is a single continuous deformation — every line stays one line,
        # and where alpha is 0 the displacement is 0, so her face is the drawing
        # by arithmetic rather than by compositing.
        big *= alpha
        mags.append(float(np.hypot(big[..., 0], big[..., 1])[alpha[..., 0] > 0.5].mean()))
        frame = cv2.remap(plate, gx + big[..., 0], gy + big[..., 1], cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)
        # the tongue patches live in the plate, so the locked region has to come
        # back from the plate too, not from the untouched drawing
        hard = (alpha[..., 0] > 0)[..., None]
        frame = np.where(hard, frame, plate).astype(np.uint8)
        fields.append(big)
        warped.append(frame)
    print(f'mane displacement: mean {np.mean(mags):.2f} px, peak {max(mags):.2f} px')

    # the loop: find the two frames whose FLOW matches best, which is the same
    # question as which two frames of the drawing look the same
    n = len(warped)
    min_loop = MIN_LOOP if n > MIN_LOOP + 4 else max(6, n // 2)
    small = [cv2.resize(f, (W // 4, H // 4), interpolation=cv2.INTER_AREA).astype(np.float32) for f in warped]
    m = cv2.resize((alpha[..., 0] > 0.5).astype(np.uint8), (W // 4, H // 4), interpolation=cv2.INTER_AREA) > 0
    step = float(np.mean([np.abs(small[i + 1][m] - small[i][m]).mean() for i in range(n - 1)]))
    best = None
    for i in range(FADE, n - min_loop):
        for j in range(i + min_loop, n):
            d = float(np.abs(small[j][m] - small[i][m]).mean())
            if best is None or d < best[0]:
                best = (d, i, j)
    gap, i0, j0 = best
    print(
        f'mane step {step:.2f}/frame; best loop {i0}..{j0} '
        f'({j0 - i0} frames) seam {gap:.2f} ({gap / max(step, 1e-6):.1f}x a step)'
    )

    cut = [f.astype(np.float32) for f in warped[i0:j0]]
    for k in range(FADE):
        wgt = (k + 1) / (FADE + 1)
        cut[-FADE + k] = (
            warped[j0 - FADE + k].astype(np.float32) * (1 - wgt) + warped[i0 - FADE + k].astype(np.float32) * wgt
        )
    cut = [np.clip(c, 0, 255).astype(np.uint8) for c in cut]
    cut_idx = list(range(i0, j0))
    pp = warped + warped[-2:0:-1]
    pp_idx = list(range(n)) + list(range(n - 2, 0, -1))

    def stamp(frames, idx):
        """The flicks, timed to the loop they are in: a whole number of cycles per
        loop, so the tongue is as far in at the last frame as it is at the first
        and the cut cannot show. Each tongue rides its own head — the anchor is
        displaced by the same flow field that moved the drawing under it."""
        if not tongues:
            return frames
        cycle = len(frames) / max(1, FLICKS)
        out = []
        for k, f in enumerate(frames):
            fr = f.copy()
            fl = fields[idx[k]]
            for ti, t in enumerate(tongues):
                u = ((k / cycle) + ti / len(tongues)) % 1.0
                if u >= OUT_FRAC:
                    continue
                e = math.sin(math.pi * u / OUT_FRAC) ** 0.35  # fast out, fast back
                ax, ay = int(round(t['ay'])), int(round(t['ax']))
                dx = float(fl[min(ax, H - 1), min(ay, W - 1), 0])
                dy = float(fl[min(ax, H - 1), min(ay, W - 1), 1])
                _draw_tongue(fr, t, e, dx, dy)
            out.append(fr)
        return out

    cut = stamp(cut, cut_idx)
    pp = stamp(pp, pp_idx)

    report = {
        'flow_src': os.path.basename(src),
        'fps': fps,
        'mane_px_mean': round(float(np.mean(mags)), 2),
        'mane_px_peak': round(float(max(mags)), 2),
        'cut_range': [i0, j0],
        'seam': round(gap, 2),
        'step': round(step, 2),
    }
    for name, frs in (('cut', cut), ('pp', pp)):
        ob = f'{outbase}_{name}'
        tmp = ob + '_raw.mp4'
        vw = cv2.VideoWriter(tmp, cv2.VideoWriter_fourcc(*'mp4v'), fps, (W, H))
        for c in frs:
            vw.write(c)
        vw.release()
        subprocess.run(
            [
                'ffmpeg',
                '-y',
                '-loglevel',
                'error',
                '-i',
                tmp,
                '-c:v',
                'libx264',
                '-preset',
                'slow',
                '-crf',
                '17',
                '-pix_fmt',
                'yuv420p',
                '-an',
                '-movflags',
                '+faststart',
                ob + '.mp4',
            ],
            check=True,
        )
        subprocess.run(
            [
                'ffmpeg',
                '-y',
                '-loglevel',
                'error',
                '-i',
                tmp,
                '-c:v',
                'libvpx-vp9',
                '-crf',
                '30',
                '-b:v',
                '0',
                '-row-mt',
                '1',
                '-an',
                ob + '.webm',
            ],
            check=True,
        )
        os.remove(tmp)
        # Two numbers, because the tongues are a deliberate exception: they are
        # drawn ON her skin, so a flick necessarily changes locked pixels inside
        # its own rectangle. Everywhere else, locked must mean the drawing.
        lk = alpha[..., 0] <= 0
        worst = max(int(np.abs(c.astype(int) - base.astype(int))[lk & ~t_rect].max()) for c in frs)
        worst_t = max(int(np.abs(c.astype(int) - base.astype(int))[lk & t_rect].max()) for c in frs)
        report[name] = {
            'frames': len(frs),
            'seconds': round(len(frs) / fps, 2),
            'locked_worst': worst,
            'locked_worst_tongue_rects': worst_t,
            'kb': round(os.path.getsize(ob + '.mp4') / 1024),
        }
        print(
            f'{name}: {len(frs)} frames, {len(frs) / fps:.1f} s, locked deviation '
            f'{worst} (0 required) / {worst_t} inside the tongue rects, '
            f'{report[name]["kb"]} KB'
        )
    cv2.imwrite(outbase + '.jpg', cut[0], [cv2.IMWRITE_JPEG_QUALITY, 92])
    with open(outbase + '_report.json', 'w') as fh:
        json.dump(report, fh, indent=1)


if __name__ == '__main__':
    main()
