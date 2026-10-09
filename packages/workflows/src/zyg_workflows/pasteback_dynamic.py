# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""pasteback_dynamic.py — hand-aware paste-back (2026-07-30).

WHY THIS EXISTS — the frozen-Abel root cause.
Pinning a world-static prop (the ledger) with a STATIC keep-mask and restoring the
anchor's pixels over it also restores anything that MOVES ACROSS that region. Abel's
writing hand lives inside the book box (book 0.495-0.825 x 0.700-0.920; his hand
0.58-0.83 x 0.60-0.90), so every frame of his animation was overwritten by the anchor's
static hand. Measured on the scene20_v8 render:

    region    pre-paste-back   post-paste-back
    a_hand        0.254            0.080     <- 68% of his motion DESTROYED
    a_head        0.150            0.127
    c_hands       0.141            0.112

The model had animated him correctly the whole time (0.254 is well over the 0.12 gate);
the post-process erased it. Two renders (v7, v8a) were misdiagnosed as "frozen Abel" and
"prompt didn't give him an action" because of this.

THE RULE: a keep-region pins a WORLD-STATIC surface, so it must be subtracted by whatever
MOVES OVER that surface in each frame. The mask is therefore per-frame, not static:

    keep_frame_i = static_keep_mask MINUS dilated(moving occluders detected in frame i)

Occluders come from MediaPipe hand landmarks (anatomy_qc, Apache-2.0, ~34 ms/frame CPU,
no VRAM) so the page still pins pixel-exact — which the fixed ink quad depends on — while
the hand and quill stay generated and alive.

    paste_back_keep_regions_dynamic(clip, still, mask, out, fps=17,
                                    occluder_boxes_fn=None, dilate_px=18, feather_px=9)

Falls back to a plain static paste-back (with a loud log) when MediaPipe is unavailable,
so a missing optional dep can never silently change compositing behaviour.
"""

import os

from PIL import Image, ImageFilter
from zyg_workflows.bin import exe


def _log_noop(_m):
    pass


def _hand_boxes_mediapipe(image_path, log_fn=None):
    """[(fx0,fy0,fx1,fy1)] fractional boxes of every detected hand, or None when the
    detector is unavailable (caller must then fail SAFE, not silently static)."""
    log = log_fn or _log_noop
    try:
        from zyg_workflows import anatomy_qc
    except Exception as e:
        log(f'[pasteback] anatomy_qc unavailable ({e})')
        return None
    try:
        r = anatomy_qc.qc_hands_frame(image_path)
    except Exception as e:
        log(f'[pasteback] hand detect error ({e})')
        return None
    if not isinstance(r, dict) or r.get('error'):
        return None
    boxes = []
    for h in r.get('hands') or []:
        bb = h.get('bbox') or h.get('box') or h.get('bbox_frac')
        if not bb or len(bb) != 4:
            pts = h.get('landmarks') or h.get('points')
            if not pts:
                continue
            xs = [p[0] for p in pts]
            ys = [p[1] for p in pts]
            bb = (min(xs), min(ys), max(xs), max(ys))
        x0, y0, x1, y1 = [float(v) for v in bb]
        if max(x0, y0, x1, y1) > 1.5:  # pixel-space box → normalise later by caller
            boxes.append(('px', x0, y0, x1, y1))
        else:
            boxes.append(('frac', x0, y0, x1, y1))
    return boxes


def paste_back_keep_regions_dynamic(
    clip_path,
    still_path,
    mask_path,
    out_path,
    fps=17,
    occluder_boxes_fn=None,
    dilate_px=18,
    feather_px=9,
    region_limit=None,
    log_fn=None,
):
    """Paste the anchor's pixels over keep (black-mask) regions EXCEPT where a moving
    occluder sits in that frame. region_limit (fx0,fy0,fx1,fy1) restricts occluder search
    to one area (e.g. Abel's side) so the other character's hands never punch holes in
    their own pinned props. Returns out_path, or None."""
    log = log_fn or _log_noop
    import glob as _glob
    import subprocess
    import tempfile

    import numpy as _np

    tmp = tempfile.mkdtemp(prefix='pasteback_dyn_')
    try:
        r = subprocess.run(
            [
                exe('ffmpeg'),
                '-y',
                '-loglevel',
                'error',
                '-i',
                clip_path,
                '-vsync',
                '0',
                os.path.join(tmp, 'f_%05d.png'),
            ],
            capture_output=True,
            text=True,
        )
        if r.returncode != 0:
            log(f'[pasteback] extract failed: {(r.stderr or "")[-200:]}')
            return None
        frames = sorted(_glob.glob(os.path.join(tmp, 'f_*.png')))
        if not frames:
            return None
        W, H = Image.open(frames[0]).size
        still = _np.asarray(Image.open(still_path).convert('RGB').resize((W, H)), dtype=_np.float32)
        base_m = _np.asarray(Image.open(mask_path).convert('L').resize((W, H)), dtype=_np.float32) / 255.0
        detect = occluder_boxes_fn or _hand_boxes_mediapipe
        outdir = os.path.join(tmp, 'out')
        os.makedirs(outdir, exist_ok=True)
        n_holes = 0
        detector_dead = False
        for i, fp in enumerate(frames):
            fr = _np.asarray(Image.open(fp).convert('RGB'), dtype=_np.float32)
            m = base_m
            if not detector_dead:
                boxes = detect(fp, log_fn=log if i == 0 else None)
                if boxes is None:
                    detector_dead = True
                    log(
                        '[pasteback] occluder detector unavailable — falling back to '
                        'STATIC paste-back for the remaining frames (moving occluders '
                        'over pinned regions WILL be frozen)'
                    )
                elif boxes:
                    hole = Image.new('L', (W, H), 0)
                    import PIL.ImageDraw as _D

                    d = _D.Draw(hole)
                    for b in boxes:
                        kind, x0, y0, x1, y1 = b
                        if kind == 'frac':
                            x0, y0, x1, y1 = x0 * W, y0 * H, x1 * W, y1 * H
                        if region_limit:
                            rx0, ry0, rx1, ry1 = region_limit
                            cx, cy = (x0 + x1) / 2.0 / W, (y0 + y1) / 2.0 / H
                            if not (rx0 <= cx <= rx1 and ry0 <= cy <= ry1):
                                continue
                        d.rectangle([x0 - dilate_px, y0 - dilate_px, x1 + dilate_px, y1 + dilate_px], fill=255)
                        n_holes += 1
                    hole = hole.filter(ImageFilter.GaussianBlur(max(1, feather_px)))
                    hm = _np.asarray(hole, dtype=_np.float32) / 255.0
                    # a hole means "generate here" → push the keep-mask toward white
                    m = _np.maximum(base_m, hm)
            comp = still * (1.0 - m[:, :, None]) + fr * m[:, :, None]
            Image.fromarray(_np.clip(comp, 0, 255).astype('uint8')).save(os.path.join(outdir, f'o_{i:05d}.png'))
        enc = subprocess.run(
            [
                exe('ffmpeg'),
                '-y',
                '-loglevel',
                'error',
                '-framerate',
                str(fps),
                '-i',
                os.path.join(outdir, 'o_%05d.png'),
                '-c:v',
                'libx264',
                '-pix_fmt',
                'yuv420p',
                '-crf',
                '16',
                out_path,
            ],
            capture_output=True,
            text=True,
        )
        if enc.returncode != 0:
            log(f'[pasteback] encode failed: {(enc.stderr or "")[-200:]}')
            return None
        log(f'[pasteback] dynamic keep-regions restored ({len(frames)} frames, {n_holes} occluder holes cut)')
        return out_path
    finally:
        import shutil

        shutil.rmtree(tmp, ignore_errors=True)
