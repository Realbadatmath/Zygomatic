# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""pipeline_effects.py — Effects workflow: add VISUAL EFFECTS to a plate or clip.

  * apply_effect_2d   — post-render compositing FX on a still (fog/bloom/vignette/grain/grade).
                        Pure PIL/numpy: deterministic, no GPU, and runs AFTER the face is locked
                        so it can never drift a character's identity.
  * generate_effect_3d — motion FX baked into a short clip by animating the plate through Wan I2V
                        with an effect-motion prompt (embers, rain, smoke, magic).

2D FX are layers OVER an existing plate, never new subjects — that's what makes them cheap + safe.
"""

import os
import math
import numpy as np
from PIL import Image, ImageFilter, ImageDraw, ImageChops
from zyg_workflows.bin import exe

_FX_2D = ('fog', 'bloom', 'godrays', 'vignette', 'grain', 'warm', 'cool')


def _log_noop(_m):
    pass


def _fog(img, amt=0.35):
    w, h = img.size
    grad = Image.new('L', (1, h))
    for y in range(h):
        grad.putpixel((0, y), int(255 * (1 - y / h) ** 1.4))  # brighter/hazier toward top
    haze = grad.resize((w, h)).filter(ImageFilter.GaussianBlur(w * 0.02)).convert('RGB')
    haze = Image.eval(haze, lambda v: int(v * amt))  # subtle screen-blended haze (no fixed brightness floor)
    return ImageChops.screen(img, haze)


def _bloom(img, amt=0.5, thresh=180):
    a = np.asarray(img).astype(np.float32)
    lum = a.mean(2)
    mask = np.clip((lum - thresh) / (255 - thresh), 0, 1)[..., None]
    bright = Image.fromarray((a * mask).astype('uint8')).filter(ImageFilter.GaussianBlur(img.size[0] * 0.012))
    return ImageChops.screen(img, Image.eval(bright, lambda v: int(v * amt)))


def _godrays(img, amt=0.4):
    # cheap radial light streaks from top: blur bright regions then radially smear upward
    b = _bloom(img, amt=0.9, thresh=200)
    streak = b.filter(ImageFilter.GaussianBlur(2))
    acc = np.asarray(streak).astype(np.float32)
    for s in (4, 10, 20):
        acc += np.asarray(streak.transform(streak.size, Image.AFFINE, (1, 0, 0, 0, 1, -s))).astype(np.float32) * 0.5
    acc = np.clip(acc / 2.5, 0, 255).astype('uint8')
    return ImageChops.screen(img, Image.eval(Image.fromarray(acc), lambda v: int(v * amt)))


def _vignette(img, amt=0.4):
    w, h = img.size
    m = Image.new('L', (w, h), 0)
    d = ImageDraw.Draw(m)
    d.ellipse([-w * 0.25, -h * 0.25, w * 1.25, h * 1.25], fill=255)
    m = m.filter(ImageFilter.GaussianBlur(min(w, h) * 0.15))
    a = np.asarray(img).astype(np.float32)
    v = (np.asarray(m).astype(np.float32) / 255.0)[..., None]
    out = a * (1 - amt * (1 - v))
    return Image.fromarray(np.clip(out, 0, 255).astype('uint8'))


def _grain(img, amt=8.0):
    a = np.asarray(img).astype(np.float32)
    # deterministic noise (no RNG): tiled hashed pattern
    h, w = a.shape[:2]
    yy, xx = np.mgrid[0:h, 0:w]
    n = ((np.sin(xx * 12.9898 + yy * 78.233) * 43758.5453) % 1.0)[..., None] - 0.5
    return Image.fromarray(np.clip(a + n * 2 * amt, 0, 255).astype('uint8'))


def _grade(img, warm=True, amt=0.18):
    a = np.asarray(img).astype(np.float32)
    if warm:
        a[..., 0] *= 1 + amt
        a[..., 2] *= 1 - amt * 0.6
    else:
        a[..., 2] *= 1 + amt
        a[..., 0] *= 1 - amt * 0.6
    return Image.fromarray(np.clip(a, 0, 255).astype('uint8'))


def apply_effect_2d(base_path, out_path, fx_kinds=('bloom', 'warm', 'vignette', 'grain'), strength=1.0, log_fn=None):
    """Apply a chain of compositing effects to a still. Returns out_path or None."""
    log = log_fn or _log_noop
    if not os.path.isfile(base_path):
        log(f'[fx2d] base not found: {base_path}')
        return None
    img = Image.open(base_path).convert('RGB')
    for fx in fx_kinds:
        s = strength
        if fx == 'fog':
            img = _fog(img, 0.35 * s)
        elif fx == 'bloom':
            img = _bloom(img, 0.5 * s)
        elif fx == 'godrays':
            img = _godrays(img, 0.4 * s)
        elif fx == 'vignette':
            img = _vignette(img, 0.4 * s)
        elif fx == 'grain':
            img = _grain(img, 8.0 * s)
        elif fx == 'warm':
            img = _grade(img, True, 0.18 * s)
        elif fx == 'cool':
            img = _grade(img, False, 0.18 * s)
        else:
            log(f'[fx2d] unknown fx "{fx}" — skipped')
    img.save(out_path)
    log(f'[fx2d] applied {list(fx_kinds)} → {out_path}')
    return out_path


def generate_effect_3d(
    base_path,
    out_dir,
    motion='a few faint glowing embers drift slowly through the air',
    seconds=5,
    seed=7,
    test_mode=True,
    log_fn=None,
):
    """Bake a SUBTLE motion effect into a short clip by animating the plate via Wan I2V —
    the scene and any characters stay intact; only a gentle effect layer moves.
    test_mode=True → one native ~5s sub-clip. Returns clip path or None."""
    log = log_fn or _log_noop
    os.makedirs(out_dir, exist_ok=True)
    if not os.path.isfile(base_path):
        log(f'[fx3d] base not found: {base_path}')
        return None
    try:
        from zyg_workflows import wan_video_service as WAN
    except Exception as e:
        log(f'[fx3d] wan import failed: {e}')
        return None
    meta = [
        {
            'prompt': f'The scene, lighting and any people stay exactly the same and clearly visible. '
            f'Add only a subtle, gentle atmospheric effect: {motion}. The effect is faint and '
            f'does not obscure or recolor the scene. Steady shot, cinematic, minimal change.',
            'subject': 'effect',
            'tag': 'fx',
            'slot_seconds': seconds,
            'index': 0,
            'path': base_path,
            'emotion': 'neutral',
            'shot_type': 'medium',
            'seed': seed,
        }
    ]
    res = WAN.generate(
        meta,
        out_dir,
        n_clips=1,
        n_chained=1 if test_mode else None,
        frames=81 if test_mode else None,
        steps=12 if test_mode else None,
        flow_shift=1.5,  # low shift → the base scene persists, effect stays subtle
        log_fn=log,
        visual_style='cinematic',
    )
    if not res:
        log('[fx3d] wan produced no clip')
        return None
    log(f'[fx3d] effect clip → {res[0].get("path")}')
    return res[0].get('path')


# ── Compositing-overlay motion FX (no GPU, scene-preserving) ──────────────────
_PARTICLE_FX = ('embers', 'snow', 'rain', 'dust')


def _draw_particles(W, H, fx, t, seed=42):
    """One frame of a procedural particle layer (on black, for screen-blend). t in [0,1)."""
    rng = np.random.RandomState(seed)
    count, col = {
        'embers': (80, (255, 170, 55)),
        'snow': (170, (236, 241, 255)),
        'rain': (230, (175, 195, 225)),
        'dust': (95, (205, 195, 165)),
    }.get(fx, (80, (255, 170, 55)))
    px = rng.rand(count)
    py = rng.rand(count)
    ph = rng.rand(count) * 6.2832
    spd = 0.3 + rng.rand(count) * 0.8
    siz = 1.0 + rng.rand(count) * 3.0
    ov = Image.new('RGB', (W, H), (0, 0, 0))
    d = ImageDraw.Draw(ov)
    for i in range(count):
        if fx == 'embers':
            y = (py[i] - t * spd[i] * 0.6) % 1.0
            x = (px[i] + 0.03 * math.sin(ph[i] + t * 8)) % 1.0
            r = 1.5 + siz[i]
            fl = 0.55 + 0.45 * math.sin(ph[i] + t * 20 * spd[i])
            c = tuple(max(0, min(255, int(v * fl))) for v in col)
            cx, cy = x * W, y * H
            d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=c)
        elif fx == 'snow':
            y = (py[i] + t * spd[i] * 0.5) % 1.0
            x = (px[i] + 0.04 * math.sin(ph[i] + t * 3)) % 1.0
            r = 1.0 + siz[i]
            cx, cy = x * W, y * H
            d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=col)
        elif fx == 'rain':
            y = (py[i] + t * spd[i] * 2.0) % 1.0
            x = px[i]
            cx, cy = x * W, y * H
            ln = 8 + siz[i] * 5
            d.line([cx, cy, cx - 2, cy + ln], fill=col, width=1)
        else:  # dust
            y = (py[i] - t * spd[i] * 0.15) % 1.0
            x = (px[i] + 0.05 * math.sin(ph[i] + t * 1.5)) % 1.0
            r = 0.8 + siz[i] * 0.6
            cx, cy = x * W, y * H
            c = tuple(int(v * 0.5) for v in col)
            d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=c)
    blur = {'embers': 1.4, 'snow': 0.8, 'rain': 0.4, 'dust': 1.8}.get(fx, 1.0)
    return ov.filter(ImageFilter.GaussianBlur(blur))


def composite_fx_clip(
    base_path, out_dir, fx='embers', seconds=5, fps=24, kenburns=True, grade=True, seed=42, log_fn=None
):
    """Subtle motion-FX clip WITHOUT GPU: slow Ken-Burns on the base plate + a procedural
    moving particle overlay (screen-blended) + a light grade. The scene is perfectly
    preserved (never recolored/distorted) — only the effect layer moves. Returns clip path."""
    log = log_fn or _log_noop
    os.makedirs(out_dir, exist_ok=True)
    if not os.path.isfile(base_path):
        log(f'[fxcomp] base not found: {base_path}')
        return None
    if fx not in _PARTICLE_FX:
        fx = 'embers'
    base = Image.open(base_path).convert('RGB')
    W, H = base.size
    W -= W % 2
    H -= H % 2  # even dims for h264
    base = base.resize((W, H), Image.LANCZOS)
    n = max(2, int(seconds * fps))
    framedir = os.path.join(out_dir, '_frames')
    os.makedirs(framedir, exist_ok=True)
    for f in range(n):
        t = f / (n - 1)
        img = base
        if kenburns:
            z = 1.0 + 0.06 * t
            cw, ch = int(W / z), int(H / z)
            x = (W - cw) // 2
            y = (H - ch) // 2
            img = base.crop((x, y, x + cw, y + ch)).resize((W, H), Image.LANCZOS)
        frame = ImageChops.screen(img, _draw_particles(W, H, fx, t, seed))
        if grade:
            frame = _vignette(frame, 0.22)
            frame = _grain(frame, 4.0)
        frame.save(os.path.join(framedir, f'f{f:04d}.png'))
    out = os.path.join(out_dir, f'fx_{fx}.mp4')
    import subprocess
    import shutil as _sh

    try:
        subprocess.run(
            [
                exe('ffmpeg'),
                '-y',
                '-framerate',
                str(fps),
                '-i',
                os.path.join(framedir, 'f%04d.png'),
                '-c:v',
                'libx264',
                '-pix_fmt',
                'yuv420p',
                '-crf',
                '18',
                out,
            ],
            capture_output=True,
            timeout=240,
            check=True,
        )
    except Exception as e:
        log(f'[fxcomp] ffmpeg encode failed: {e}')
        _sh.rmtree(framedir, ignore_errors=True)
        return None
    _sh.rmtree(framedir, ignore_errors=True)
    if os.path.isfile(out):
        log(f'[fxcomp] {fx} composite clip → {out}')
        return out
    return None
