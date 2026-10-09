# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""SIDE / PIXEL — the deterministic half of the toolbox: arithmetic on the pixels, previewed live.

Moved verbatim out of the old single-file creature_fx.py (lines 3169-3801).
"""

from __future__ import annotations

import re

from zyg_workflows.creature_fx.base import _pix, b, c, e, f, i


# ══ SIDE · PIXEL ════════════════════════════════════════════════════════════
# Deterministic Pillow ops. These are the ops the preview can actually SHOW,
# because they are arithmetic: what you see in the pane is byte-for-byte what
# the bake writes. They run BEFORE the generative edit if they sit above it in
# the stack and AFTER it if they sit below -- which is what stack order means
# everywhere else in this toolbox and would be a lie here if it did not.
#
# Everything runs in RGBA. A creature cut out of its background is the asset
# that gets composited into a scene, and an op that quietly flattened the alpha
# would hand back a card that looks identical until the day it is used.


def _pil():
    from PIL import Image, ImageChops, ImageEnhance, ImageFilter, ImageOps

    return Image, ImageChops, ImageEnhance, ImageFilter, ImageOps


def _px_crop(im, p):
    w, h = im.size
    x0 = int(w * p['x'] / 100.0)
    y0 = int(h * p['y'] / 100.0)
    x1 = min(w, x0 + max(1, int(w * p['w'] / 100.0)))
    y1 = min(h, y0 + max(1, int(h * p['h'] / 100.0)))
    return im.crop((x0, y0, max(x0 + 1, x1), max(y0 + 1, y1)))


def _px_scale(im, p):
    Image, _, _, _, _ = _pil()
    w, h = im.size
    sx = max(1, int(round(w * p['s'] / 100.0)))
    sy = max(1, int(round(h * (p['s'] if p['lock'] else p['sy']) / 100.0)))
    flt = {'lanczos': Image.LANCZOS, 'bicubic': Image.BICUBIC, 'bilinear': Image.BILINEAR, 'nearest': Image.NEAREST}[
        p['flt']
    ]
    return im.resize((sx, sy), flt)


def _px_rot(im, p):
    Image, _, _, _, _ = _pil()
    return im.rotate(-float(p['a']), resample=Image.BICUBIC, expand=bool(p['expand']), fillcolor=(0, 0, 0, 0))


def _px_pad(im, p):
    Image, _, _, _, _ = _pil()
    w, h = im.size
    m = int(round(max(w, h) * p['m'] / 100.0))
    out = Image.new('RGBA', (w + 2 * m, h + 2 * m), _rgba(p['col'], p['a']))
    out.alpha_composite(im, (m, m))
    return out


def _px_enh(kind):
    def go(im, p):
        _, _, ImageEnhance, _, _ = _pil()
        cls = {
            'bright': ImageEnhance.Brightness,
            'contrast': ImageEnhance.Contrast,
            'colour': ImageEnhance.Color,
            'sharp': ImageEnhance.Sharpness,
        }[kind]
        return cls(im).enhance(1.0 + float(p['v']) / 100.0)

    return go


def _px_gamma(im, p):
    g = max(0.05, float(p['g']))
    lut = [min(255, int(round(255.0 * ((k / 255.0) ** (1.0 / g))))) for k in range(256)]
    return _apply_rgb_lut(im, lut, lut, lut)


def _px_levels(im, p):
    lo, hi = float(p['lo']), float(p['hi'])
    if hi <= lo:
        hi = lo + 1
    lut = []
    for k in range(256):
        v = (k - lo) * 255.0 / (hi - lo)
        lut.append(int(max(0, min(255, round(v)))))
    return _apply_rgb_lut(im, lut, lut, lut)


def _px_temp(im, p):
    """Warm/cool by scaling R and B against each other.

    Done as a channel LUT rather than a colour overlay, because an overlay
    lands on the ALPHA too and quietly fogs a cut-out's matte."""
    k = float(p['v']) / 100.0
    r = [min(255, int(round(c * (1 + 0.35 * k)))) for c in range(256)]
    b = [min(255, int(round(c * (1 - 0.35 * k)))) for c in range(256)]
    g = list(range(256))
    return _apply_rgb_lut(im, r, g, b)


def _px_tint(im, p):
    """Tint the midtones toward a colour, leaving alpha alone."""
    Image, ImageChops, _, _, _ = _pil()
    rgb = im.convert('RGB')
    a = im.getchannel('A')
    solid = Image.new('RGB', im.size, _rgb(p['col']))
    out = Image.blend(rgb, ImageChops.multiply(rgb, solid), max(0.0, min(1.0, p['a'] / 100.0)))
    out = out.convert('RGBA')
    out.putalpha(a)
    return out


def _px_hue(im, p):
    """Rotate hue via HSV, keeping alpha.

    PIL has no hue filter; converting through HSV and rolling the H channel is
    the whole implementation, and it is exact for integer degrees."""
    a = im.getchannel('A')
    hsv = im.convert('RGB').convert('HSV')
    h, s, v = hsv.split()
    shift = int(round(float(p['a']) * 255.0 / 360.0)) % 256
    h = h.point(lambda k: (k + shift) % 256)
    Image, _, _, _, _ = _pil()
    out = Image.merge('HSV', (h, s, v)).convert('RGBA')
    out.putalpha(a)
    return out


def _px_blur(im, p):
    _, _, _, ImageFilter, _ = _pil()
    r = float(p['r'])
    return im.filter(ImageFilter.GaussianBlur(r)) if r > 0.05 else im


def _px_usm(im, p):
    _, _, _, ImageFilter, _ = _pil()
    return im.filter(ImageFilter.UnsharpMask(radius=float(p['r']), percent=int(p['amt']), threshold=int(p['thr'])))


def _px_median(im, p):
    _, _, _, ImageFilter, _ = _pil()
    n = int(p['n'])
    n = n if n % 2 else n + 1
    return im.filter(ImageFilter.MedianFilter(max(3, min(9, n))))


def _px_vig(im, p):
    """Darken toward the corners.

    Built as a radial mask multiplied into RGB only. A vignette drawn into the
    alpha would silently eat the edge of a cut-out element."""
    Image, ImageChops, _, ImageFilter, _ = _pil()
    w, h = im.size
    a = im.getchannel('A')
    mask = Image.new('L', (w, h), 0)
    import math

    px = mask.load()
    cx, cy = w / 2.0, h / 2.0
    mx = math.hypot(cx, cy)
    amt = max(0.0, min(1.0, p['a'] / 100.0))
    feath = max(0.05, p['f'] / 100.0)
    for yy in range(h):
        for xx in range(0, w):
            d = math.hypot(xx - cx, yy - cy) / mx
            t = (d - (1 - feath)) / feath
            t = 0.0 if t < 0 else (1.0 if t > 1 else t)
            px[xx, yy] = int(255 * (1 - amt * t))
    rgb = im.convert('RGB')
    dark = ImageChops.multiply(rgb, Image.merge('RGB', (mask, mask, mask)))
    out = dark.convert('RGBA')
    out.putalpha(a)
    return out


def _px_grain(im, p):
    """Monochrome grain, seeded so a preview and its bake match exactly."""
    Image, ImageChops, _, _, _ = _pil()
    import random

    rnd = random.Random(int(p['seed']))
    w, h = im.size
    amt = max(0, min(100, int(p['a'])))
    n = Image.new('L', (w, h))
    n.putdata([128 + int(rnd.gauss(0, amt * 0.6)) for _ in range(w * h)])
    a = im.getchannel('A')
    rgb = im.convert('RGB')
    noise = Image.merge('RGB', (n, n, n))
    out = ImageChops.add(ImageChops.subtract(rgb, noise, scale=1, offset=0), noise, scale=2)
    out = Image.blend(rgb, out, 0.9).convert('RGBA')
    out.putalpha(a)
    return out


def _px_post(im, p):
    _, _, _, _, ImageOps = _pil()
    a = im.getchannel('A')
    out = ImageOps.posterize(im.convert('RGB'), max(1, min(8, int(p['bits'])))).convert('RGBA')
    out.putalpha(a)
    return out


def _px_mono(im, p):
    _, _, _, _, ImageOps = _pil()
    Image, _, _, _, _ = _pil()
    a = im.getchannel('A')
    g = ImageOps.grayscale(im.convert('RGB'))
    if p['tint']:
        g = ImageOps.colorize(g, black='#000000', white=p['col'])
    out = g.convert('RGBA')
    out.putalpha(a)
    return Image.blend(im, out, max(0.0, min(1.0, p['a'] / 100.0)))


def _px_bg(im, p):
    """Knock out a flat background by colour distance from a corner sample.

    This is a KEYER, not a segmentation: it is exact on the plain studio plates
    the sheet pipeline makes and it is wrong on a photograph, which is why the
    tooltip says so instead of the result implying otherwise."""
    Image, _, _, ImageFilter, _ = _pil()
    rgb = im.convert('RGB')
    w, h = rgb.size
    if p['pick'] == 'corner':
        ref = rgb.getpixel((1, 1))
    elif p['pick'] == 'top-left':
        ref = rgb.getpixel((1, 1))
    elif p['pick'] == 'top-right':
        ref = rgb.getpixel((w - 2, 1))
    else:
        ref = _rgb(p['col'])
    tol = max(1, int(p['tol'])) * 3
    soft = max(1, int(p['soft'])) * 3
    src = rgb.load()
    mask = Image.new('L', (w, h), 255)
    mp = mask.load()
    for yy in range(h):
        for xx in range(w):
            r, g, bl = src[xx, yy]
            d = abs(r - ref[0]) + abs(g - ref[1]) + abs(bl - ref[2])
            if d <= tol:
                mp[xx, yy] = 0
            elif d < tol + soft:
                mp[xx, yy] = int(255 * (d - tol) / soft)
    if p['feather'] > 0.05:
        mask = mask.filter(ImageFilter.GaussianBlur(float(p['feather'])))
    out = im.copy()
    old = im.getchannel('A')
    Image, ImageChops, _, _, _ = _pil()
    out.putalpha(ImageChops.multiply(old, mask))
    return out


def _px_flat(im, p):
    """Composite over a solid ground -- the honest inverse of the keyer."""
    Image, _, _, _, _ = _pil()
    bg = Image.new('RGBA', im.size, _rgba(p['col'], 100))
    bg.alpha_composite(im)
    return bg


def _px_trim(im, p):
    """Strip letterbox bars, the same measurement creature_sheet_service makes.

    Bars are what a Qwen edit adds when it decides the composition wants them,
    and every downstream crop then treats them as part of the creature."""
    rgb = im.convert('RGB')
    w, h = rgb.size
    px = rgb.load()
    tol = int(p['tol'])

    def flat_row(y):
        r0, g0, b0 = px[0, y]
        for xx in range(0, w, max(1, w // 64)):
            r, g, bl = px[xx, y]
            if abs(r - r0) + abs(g - g0) + abs(bl - b0) > tol:
                return False
        return True

    def flat_col(xx):
        r0, g0, b0 = px[xx, 0]
        for yy in range(0, h, max(1, h // 64)):
            r, g, bl = px[xx, yy]
            if abs(r - r0) + abs(g - g0) + abs(bl - b0) > tol:
                return False
        return True

    top, bot, left, right = 0, h - 1, 0, w - 1
    lim = int(h * 0.45)
    while top < lim and flat_row(top):
        top += 1
    while bot > h - lim and flat_row(bot):
        bot -= 1
    lim = int(w * 0.45)
    while left < lim and flat_col(left):
        left += 1
    while right > w - lim and flat_col(right):
        right -= 1
    if bot - top < 8 or right - left < 8:
        return im
    return im.crop((left, top, right + 1, bot + 1))


def _px_square(im, p):
    """Pad to a square canvas -- what the trainer's aspect buckets want."""
    Image, _, _, _, _ = _pil()
    w, h = im.size
    n = max(w, h)
    out = Image.new('RGBA', (n, n), _rgba(p['col'], p['a']))
    out.alpha_composite(im, ((n - w) // 2, (n - h) // 2))
    return out


def _px_flip(axis):
    def go(im, p):
        Image, _, _, _, _ = _pil()
        return im.transpose(Image.FLIP_LEFT_RIGHT if axis == 'h' else Image.FLIP_TOP_BOTTOM)

    return go


def _rgb(hexv):
    hexv = str(hexv or '#000000')
    if not re.fullmatch(r'#[0-9a-fA-F]{6}', hexv):
        hexv = '#000000'
    return (int(hexv[1:3], 16), int(hexv[3:5], 16), int(hexv[5:7], 16))


def _rgba(hexv, a=100):
    r, g, b_ = _rgb(hexv)
    return (r, g, b_, int(max(0, min(100, a)) * 255 / 100))


def _apply_rgb_lut(im, r, g, b_):
    a = im.getchannel('A')
    out = im.convert('RGB').point(r + g + b_).convert('RGBA')
    out.putalpha(a)
    return out


_pix(
    'px_crop',
    'Crop',
    'Pixel',
    'Crop — exact, in percentages of the source so the same crop survives a change of '
    'resolution. Deterministic: what the preview shows is what bakes.',
    '<path d="M6.5 2.5v13a2 2 0 002 2h13"/><path d="M2.5 6.5h13a2 2 0 012 2v13"/>',
    [
        f('x', 'X %', 0, 0, 99, 0.5),
        f('y', 'Y %', 0, 0, 99, 0.5),
        f('w', 'Width %', 100, 1, 100, 0.5),
        f('h', 'Height %', 100, 1, 100, 0.5),
    ],
    pfn=_px_crop,
)

_pix(
    'px_scale',
    'Resize',
    'Pixel',
    'Resize — with the filter named. Nearest keeps a pixel-art creature crisp; lanczos is '
    'right for a render. The trainer wants 1024, and going up from 512 invents detail.',
    '<rect x="3.4" y="12.6" width="8" height="8" rx="1.2"/><path d="M14 10L20.6 3.4"/>'
    '<path d="M20.6 3.4h-5M20.6 3.4v5"/>',
    [
        f('s', 'Size %', 100, 5, 400, 1),
        f('sy', 'Height %', 100, 5, 400, 1),
        b('lock', 'Lock aspect', True),
        e('flt', 'Filter', 'lanczos', ['lanczos', 'bicubic', 'bilinear', 'nearest']),
    ],
    pfn=_px_scale,
)

_pix(
    'px_rot',
    'Rotate',
    'Pixel',
    'Rotate — about the centre, filling with transparency rather than black. "Expand" '
    'grows the canvas so the corners are not clipped.',
    '<path d="M20.2 12a8.2 8.2 0 11-2.7-6.1"/><path d="M20.4 3.6v4.6h-4.6"/>',
    [f('a', 'Degrees', 0, -180, 180, 0.5), b('expand', 'Expand canvas', True)],
    pfn=_px_rot,
)

_pix(
    'px_fliph',
    'Flip H',
    'Pixel',
    'Flip horizontally. The sheet pipeline uses exactly this to make the opposite profile '
    'from one side anchor, because these creatures are bilaterally symmetric — check the '
    'Symmetry op before you trust it.',
    '<path d="M12 2.6v18.8" stroke-dasharray="2.6 2.4"/><path d="M9.2 6.6L3.6 12l5.6 5.4z"/>'
    '<path d="M14.8 6.6L20.4 12l-5.6 5.4z"/>',
    pfn=_px_flip('h'),
)

_pix(
    'px_flipv',
    'Flip V',
    'Pixel',
    'Flip vertically.',
    '<path d="M2.6 12h18.8" stroke-dasharray="2.6 2.4"/><path d="M6.6 9.2L12 3.6l5.4 5.6z"/>'
    '<path d="M6.6 14.8L12 20.4l5.4-5.6z"/>',
    pfn=_px_flip('v'),
)

_pix(
    'px_bright',
    'Exposure',
    'Pixel',
    'Exposure — a straight multiply on the RGB, alpha untouched.',
    '<circle cx="12" cy="12" r="4"/><path d="M12 2.6v3M12 18.4v3M2.6 12h3M18.4 12h3'
    'M5.4 5.4l2.2 2.2M16.4 16.4l2.2 2.2M18.6 5.4l-2.2 2.2M7.6 16.4l-2.2 2.2"/>',
    [f('v', 'Exposure', 0, -90, 200, 1)],
    pfn=_px_enh('bright'),
)

_pix(
    'px_contrast',
    'Contrast',
    'Pixel',
    'Contrast — about mid grey.',
    '<circle cx="12" cy="12" r="8.4"/><path d="M12 3.6a8.4 8.4 0 010 16.8z" fill="currentColor" stroke="none"/>',
    [f('v', 'Contrast', 0, -90, 200, 1)],
    pfn=_px_enh('contrast'),
)

_pix(
    'px_sat',
    'Saturation',
    'Pixel',
    "Saturation — exact and instant, unlike the Colour section's intensity op, which asks "
    'the model to paint differently. Both are useful; they are not the same thing.',
    '<circle cx="9.6" cy="12" r="5.2"/><circle cx="14.4" cy="12" r="5.2"/><path d="M12 6.8v10.4"/>',
    [f('v', 'Saturation', 0, -100, 200, 1)],
    pfn=_px_enh('colour'),
)

_pix(
    'px_hue',
    'Hue',
    'Pixel',
    'Hue rotation, in degrees, through HSV. Exact, reversible and it does not touch alpha.',
    '<circle cx="12" cy="12" r="8.4"/><path d="M12 3.6v8.4l6 4.2"/>',
    [f('a', 'Degrees', 0, -180, 180, 1)],
    pfn=_px_hue,
)

_pix(
    'px_temp',
    'Temperature',
    'Pixel',
    'Temperature — warm or cool, as a channel LUT rather than a colour overlay. An overlay '
    'would land on the alpha and fog a cut-out matte.',
    '<path d="M10 13.4V5.4a2 2 0 014 0v8"/><circle cx="12" cy="16.4" r="3.4"/><path d="M17.4 7.4h3M17.4 11h3"/>',
    [f('v', 'Cool ← → warm', 0, -100, 100, 1)],
    pfn=_px_temp,
)

_pix(
    'px_gamma',
    'Gamma',
    'Pixel',
    'Gamma — midtones without moving black or white. The right knob when a render is '
    'correctly exposed but reads muddy.',
    '<path d="M3.6 19.4c6-1 9-6 10-14"/><path d="M3.6 19.4h16.8"/>',
    [f('g', 'Gamma', 1.0, 0.2, 3.0, 0.01)],
    pfn=_px_gamma,
)

_pix(
    'px_levels',
    'Levels',
    'Pixel',
    'Levels — black point and white point. Setting the black point on a render that never '
    'reaches zero is what makes it stop looking flat.',
    '<path d="M3.6 19.4V8.4M8 19.4V4.6M12.4 19.4v-9M16.8 19.4V6.4M21 19.4v-4"/>',
    [f('lo', 'Black point', 0, 0, 200, 1), f('hi', 'White point', 255, 55, 255, 1)],
    pfn=_px_levels,
)

_pix(
    'px_tint',
    'Tint',
    'Pixel',
    'Tint — multiply the picture toward a colour. Useful for matching a creature into a '
    "scene's light without re-rendering it.",
    '<path d="M12 3.6c3.4 4.6 5.6 7.8 5.6 10.4a5.6 5.6 0 11-11.2 0c0-2.6 2.2-5.8 5.6-10.4z"/>',
    [c('col', 'Colour', '#ffcc88'), f('a', 'Amount', 40, 0, 100, 1)],
    pfn=_px_tint,
)

_pix(
    'px_mono',
    'Monochrome',
    'Pixel',
    'Monochrome — with an optional tone. A creature judged in greyscale is a creature '
    'judged on value alone, which is where a weak silhouette shows up.',
    '<circle cx="12" cy="12" r="8.4"/><path d="M12 3.6v16.8"/>'
    '<path d="M12 3.6a8.4 8.4 0 000 16.8z" fill="currentColor" stroke="none"/>',
    [f('a', 'Amount', 100, 0, 100, 1), b('tint', 'Tone it', False), c('col', 'Tone', '#e8d8b0')],
    pfn=_px_mono,
)

_pix(
    'px_blur',
    'Blur',
    'Pixel',
    'Gaussian blur, in pixels at the source resolution — so it means the same thing on a '
    '512 cell and a 2048 render, which a percentage would not.',
    '<circle cx="12" cy="12" r="7.6" stroke-dasharray="1.6 2.6"/><circle cx="12" cy="12" r="3.4"/>',
    [f('r', 'Radius', 2, 0, 40, 0.1)],
    pfn=_px_blur,
)

_pix(
    'px_sharp',
    'Sharpen',
    'Pixel',
    'Unsharp mask — radius, amount and threshold, the three knobs that decide whether it '
    'sharpens the creature or the noise around it.',
    '<path d="M12 3.6l3 6.4 6.4 1-4.6 4.6 1 6.4-5.8-3-5.8 3 1-6.4-4.6-4.6 6.4-1z"/>',
    [f('r', 'Radius', 2, 0.1, 12, 0.1), i('amt', 'Amount %', 120, 0, 400, 5), i('thr', 'Threshold', 3, 0, 40, 1)],
    pfn=_px_usm,
)

_pix(
    'px_denoise',
    'Denoise',
    'Pixel',
    'Median denoise. Cheap, exact and it eats fine fur — which is why the radius is small '
    'and capped rather than a free slider.',
    '<circle cx="12" cy="12" r="8.4"/><path d="M7.4 13.4c1.6-2.4 3-3.4 4.6-3.4s3 1 4.6 3.4"/>',
    [i('n', 'Radius', 3, 3, 9, 2)],
    pfn=_px_median,
)

_pix(
    'px_vig',
    'Vignette',
    'Pixel',
    'Vignette — darkens toward the corners, multiplied into RGB only. Drawn into the alpha '
    'it would silently eat the edge of a cut-out.',
    '<rect x="3.4" y="4.6" width="17.2" height="14.8" rx="2"/><ellipse cx="12" cy="12" rx="6.4" ry="5"/>',
    [f('a', 'Amount', 45, 0, 100, 1), f('f', 'Feather', 60, 5, 100, 1)],
    pfn=_px_vig,
)

_pix(
    'px_grain',
    'Grain',
    'Pixel',
    'Film grain — seeded, so the preview and the bake carry the SAME grain. An unseeded '
    'grain would make every re-render a different file for no reason.',
    '<rect x="3.6" y="5.4" width="16.8" height="13.2" rx="1.6"/>'
    '<circle cx="8" cy="10" r=".9"/><circle cx="13" cy="9" r=".9"/><circle cx="16.4" cy="13" r=".9"/>'
    '<circle cx="9.4" cy="14.4" r=".9"/><circle cx="13.6" cy="15.4" r=".9"/>',
    [f('a', 'Amount', 12, 0, 60, 1), i('seed', 'Seed', 7, 0, 99999, 1)],
    pfn=_px_grain,
)

_pix(
    'px_post',
    'Posterize',
    'Pixel',
    'Posterize — bits per channel. A fast way to see the value structure, and a real stylisation at 2–3 bits.',
    '<path d="M3.6 19.4h4V14h4V9.4h4V5h4.8"/>',
    [i('bits', 'Bits', 4, 1, 8, 1)],
    pfn=_px_post,
)

_pix(
    'px_key',
    'Key background',
    'Pixel',
    'Key out a FLAT background by colour distance from a sampled corner. Exact on the '
    'studio plates this pipeline makes; wrong on a photograph — it is a keyer, not a '
    'segmentation, and the difference matters on a furred edge.',
    '<path d="M14.4 9.6a3.4 3.4 0 10-3.4 3.4l-1 1-2 .4-.4 2-2 .4-.4 2.4 3.4-.4.4-2 2-.4.4-2 2.6-2.6z"/>',
    [
        e('pick', 'Sample', 'corner', ['corner', 'top-left', 'top-right', 'colour']),
        c('col', 'Colour', '#ffffff'),
        i('tol', 'Tolerance', 18, 1, 120, 1),
        i('soft', 'Softness', 14, 1, 120, 1),
        f('feather', 'Feather', 1.0, 0, 12, 0.1),
    ],
    pfn=_px_bg,
)

_pix(
    'px_flat',
    'Flatten',
    'Pixel',
    'Flatten onto a solid ground — the honest inverse of the keyer, and what a trainer '
    'tile needs, since a transparent PNG trains as black.',
    '<rect x="3.6" y="3.6" width="16.8" height="16.8" rx="2"/><path d="M3.6 14.4l5-4.6 3.4 3 3-2.4 5.4 4.6"/>',
    [c('col', 'Ground', '#808080')],
    pfn=_px_flat,
)

_pix(
    'px_trim',
    'Trim bars',
    'Pixel',
    'Trim letterbox bars — the same measurement creature_sheet_service makes after every '
    'edit, because a Qwen edit adds bars whenever it decides the composition wants them '
    'and every later crop then treats them as part of the creature.',
    '<rect x="3.6" y="7.4" width="16.8" height="9.2" rx="1.2"/>'
    '<path d="M3.6 4.4h16.8M3.6 19.6h16.8" stroke-dasharray="2.4 2.4"/>',
    [i('tol', 'Tolerance', 10, 1, 60, 1)],
    pfn=_px_trim,
)

_pix(
    'px_pad',
    'Pad',
    'Pixel',
    'Pad — add margin around the image, transparent by default. The counterpart to Crop '
    'when a cell clipped a tail tip.',
    '<rect x="2.6" y="2.6" width="18.8" height="18.8" rx="2" stroke-dasharray="2.4 2.4"/>'
    '<rect x="7" y="7" width="10" height="10" rx="1.2"/>',
    [f('m', 'Margin %', 10, 0, 100, 0.5), c('col', 'Colour', '#000000'), f('a', 'Opacity %', 0, 0, 100, 1)],
    pfn=_px_pad,
)

_pix(
    'px_square',
    'Square up',
    'Pixel',
    "Pad to a square canvas — what the trainer's aspect buckets want, and what stops a "
    'tall creature being letterboxed by the bucketer instead.',
    '<rect x="4.4" y="4.4" width="15.2" height="15.2" rx="1.6"/>'
    '<path d="M4.4 12h15.2M12 4.4v15.2" stroke-dasharray="2 2.4"/>',
    [c('col', 'Ground', '#808080'), f('a', 'Opacity %', 0, 0, 100, 1)],
    pfn=_px_square,
)
