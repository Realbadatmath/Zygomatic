# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

import glob
import os
import shutil
import subprocess
import tempfile

import numpy as np
from PIL import Image, ImageDraw, ImageFilter
from zyg_workflows.bin import exe


def _log_noop(_m):
    pass


def make_script_texture(w, h, lines=5, seed=7, stroke_w=2):
    """Period-looking script: per line, a wandering baseline stroke with micro-oscillations
    (letter humps), occasional ascenders/descenders and word gaps. Unreadable by design.

    stroke_w stays >= 2 in rectified space — thinner strokes disappear entirely once the
    frame-space blur is raised to the render's own softness at 480p."""
    rng = np.random.default_rng(seed)
    im = Image.new('L', (w, h), 0)
    d = ImageDraw.Draw(im)
    line_h = h / (lines + 1)
    sw = max(2, int(stroke_w))
    for li in range(lines):
        y0 = line_h * (li + 1)
        x = int(w * 0.03)
        while x < w * 0.95:
            word_len = int(rng.uniform(0.05, 0.14) * w)
            pts = []
            xx = x
            phase = rng.uniform(0, 6.28)
            while xx < min(x + word_len, w * 0.95):
                hump = np.sin((xx - x) * 0.55 + phase) * line_h * 0.14
                asc = 0.0
                if rng.random() < 0.06:
                    asc = -line_h * rng.uniform(0.25, 0.45)  # ascender
                elif rng.random() < 0.05:
                    asc = line_h * rng.uniform(0.2, 0.4)  # descender
                pts.append((xx, y0 + hump + asc + rng.normal(0, 0.5)))
                xx += 2
            if len(pts) > 2:
                d.line(pts, fill=230, width=sw)
            x += word_len + int(rng.uniform(0.015, 0.035) * w)
    return im.filter(ImageFilter.GaussianBlur(0.6))


def composite_write_on(
    clip_path, out_path, page_box, start_s=0.0, end_s=None, fps=17, lines=5, ink_color=(48, 38, 30), seed=7, log_fn=None
):
    """Reveal script ink inside page_box (fx0,fy0,fx1,fy1 fractions) from start_s to end_s,
    left-to-right line-by-line at writing pace. Page must be screen-static (pinned book)."""
    log = log_fn or _log_noop
    tmp = tempfile.mkdtemp(prefix='inkfx_')
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
            return None
        frames = sorted(glob.glob(os.path.join(tmp, 'f_*.png')))
        n = len(frames)
        if n < 8:
            return None
        W, H = Image.open(frames[0]).size
        fx0, fy0, fx1, fy1 = page_box
        px0, py0 = int(W * fx0), int(H * fy0)
        pw, ph = int(W * (fx1 - fx0)), int(H * (fy1 - fy0))
        ink = np.asarray(make_script_texture(pw, ph, lines=lines, seed=seed), dtype=np.float32) / 255.0
        end_s = end_s if end_s is not None else n / fps
        line_h = ph / (lines + 1)
        col = np.array(ink_color, dtype=np.float32)
        outdir = os.path.join(tmp, 'out')
        os.makedirs(outdir, exist_ok=True)
        for i, fp in enumerate(frames):
            t = i / float(fps)
            img = np.asarray(Image.open(fp).convert('RGB'), dtype=np.float32)
            if t > start_s:
                prog = min((t - start_s) / max(end_s - start_s, 1e-3), 1.0)
                total = prog * lines  # lines written so far (fractional)
                reveal = np.zeros((ph, pw), dtype=np.float32)
                full = int(total)
                for li in range(min(full, lines)):
                    y0 = int(line_h * (li + 0.4))
                    y1 = int(min(line_h * (li + 1.7), ph))
                    reveal[y0:y1, :] = 1.0
                if full < lines:
                    frac = total - full
                    y0 = int(line_h * (full + 0.4))
                    y1 = int(min(line_h * (full + 1.7), ph))
                    reveal[y0:y1, : int(pw * frac)] = 1.0
                a = (ink * reveal)[:, :, None] * 0.85
                region = img[py0 : py0 + ph, px0 : px0 + pw]
                img[py0 : py0 + ph, px0 : px0 + pw] = region * (1 - a) + col * a
            Image.fromarray(np.clip(img, 0, 255).astype('uint8')).save(os.path.join(outdir, f'o_{i:05d}.png'))
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
            return None
        log(f'[ink] write-on composited ({lines} lines, {start_s:.0f}-{end_s:.0f}s)')
        return out_path
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ── v2: perspective-correct quad write-on (2026-07-30) ──────────────────────────


def _reveal_lines_mask(tw, th, lines, prog):
    """v1 pacing in rectified page space: full lines top-down, current line
    left-to-right. prog in [0,1] over start_s..end_s."""
    reveal = np.zeros((th, tw), dtype=np.float32)
    line_h = th / (lines + 1)
    total = prog * lines  # lines written so far (fractional)
    full = int(total)
    for li in range(min(full, lines)):
        y0 = int(line_h * (li + 0.4))
        y1 = int(min(line_h * (li + 1.7), th))
        reveal[y0:y1, :] = 1.0
    if full < lines:
        frac = total - full
        y0 = int(line_h * (full + 0.4))
        y1 = int(min(line_h * (full + 1.7), th))
        reveal[y0:y1, : int(tw * frac)] = 1.0
    return reveal


def _ink_tint(ink_color, target_luma=0.25):
    """Per-channel multiply factor with the hue of ink_color, scaled so its luma is
    ~target_luma: out = page * tint under full ink keeps candle-lit paper shading."""
    t = np.array(ink_color, dtype=np.float32) / 255.0
    luma = float(0.299 * t[0] + 0.587 * t[1] + 0.114 * t[2])
    return np.clip(t * (target_luma / max(luma, 1e-4)), 0.0, 1.0)
