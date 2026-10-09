# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Pixel ops: tone, colour, detail, grade. (im: RGBA, params) -> RGBA, deterministic."""

from __future__ import annotations

import math

from zyg_workflows import creature_fx as cfx

# ══════════════════════════════════════════════════════════════════════════════
#  PIXEL OPS
# ══════════════════════════════════════════════════════════════════════════════
# Everything here is (im: RGBA, params) -> RGBA, deterministic, and fast enough
# that the preview can run the whole chain on every knob move. The ops that
# creature_fx already implements are reused from there verbatim rather than
# re-typed — one implementation, one place a bug in it lives.
#
# Two rules every op below keeps, both learned the hard way in creature_fx:
#   * ALPHA IS NOT A TONE CHANNEL. A grade that lands on the alpha silently
#     fogs a cut-out's matte, so tonal work is done on RGB and the alpha is put
#     back untouched.
#   * ANYTHING RANDOM IS SEEDED, so a preview and its bake are the same file.

f, i, b, e, c, s = cfx.f, cfx.i, cfx.b, cfx.e, cfx.c, cfx.s
_rgb, _rgba = cfx._rgb, cfx._rgba
_lut = cfx._apply_rgb_lut


def _pil():
    from PIL import Image, ImageChops, ImageEnhance, ImageFilter, ImageOps

    return Image, ImageChops, ImageEnhance, ImageFilter, ImageOps


def _keep_alpha(im, rgb_out):
    """Put the source alpha back on an RGB result."""
    a = im.getchannel('A')
    out = rgb_out.convert('RGBA')
    out.putalpha(a)
    return out


def _px_vibrance(im, p):
    """Saturation weighted toward the DULL pixels.

    A flat saturation slider pushes an already-vivid mouth or eye into clipping
    long before it does anything for a muted background. This curves the S
    channel instead, so the amount applied falls away as saturation rises."""
    amt = float(p['v']) / 100.0
    a = im.getchannel('A')
    h, sc, v = im.convert('RGB').convert('HSV').split()
    # gain falls linearly from full at S=0 to zero at S=255
    tbl = [max(0, min(255, int(round(k + amt * k * (1.0 - k / 255.0) * 1.6)))) for k in range(256)]
    sc = sc.point(tbl)
    Image, _, _, _, _ = _pil()
    out = Image.merge('HSV', (h, sc, v)).convert('RGBA')
    out.putalpha(a)
    return out


def _tone_lut(lo_gain, hi_gain):
    """One 256-entry LUT that lifts the shadow half and the highlight half by
    independent amounts, with a smooth cosine weight so neither edge bands."""
    out = []
    for k in range(256):
        t = k / 255.0
        wlo = (math.cos(math.pi * min(1.0, t * 1.6)) + 1) / 2.0 if t < 0.625 else 0.0
        whi = (1 - math.cos(math.pi * min(1.0, max(0.0, (t - 0.375) * 1.6)))) / 2.0
        v = t + lo_gain * wlo * (1 - t) + hi_gain * whi * t
        out.append(max(0, min(255, int(round(v * 255)))))
    return out


def _px_shadows(im, p):
    tbl = _tone_lut(float(p['v']) / 140.0, 0.0)
    return _lut(im, tbl, tbl, tbl)


def _px_highlights(im, p):
    tbl = _tone_lut(0.0, float(p['v']) / 140.0)
    return _lut(im, tbl, tbl, tbl)


def _px_curve(im, p):
    """S-curve contrast about mid grey — the film response a straight contrast
    multiply does not have, and the reason a linear render reads plastic."""
    k = float(p['v']) / 100.0
    tbl = []
    for n in range(256):
        t = n / 255.0
        y = t + k * 0.5 * math.sin(2 * math.pi * (t - 0.5)) * -1
        tbl.append(max(0, min(255, int(round(y * 255)))))
    return _lut(im, tbl, tbl, tbl)


def _px_auto(im, p):
    _, _, _, _, ImageOps = _pil()
    return _keep_alpha(im, ImageOps.autocontrast(im.convert('RGB'), cutoff=float(p['cut'])))


def _px_equalize(im, p):
    Image, _, _, _, ImageOps = _pil()
    eq = ImageOps.equalize(im.convert('RGB'))
    blend = Image.blend(im.convert('RGB'), eq, max(0.0, min(1.0, p['a'] / 100.0)))
    return _keep_alpha(im, blend)


def _px_invert(im, p):
    _, _, _, _, ImageOps = _pil()
    return _keep_alpha(im, ImageOps.invert(im.convert('RGB')))


def _px_solarize(im, p):
    _, _, _, _, ImageOps = _pil()
    return _keep_alpha(im, ImageOps.solarize(im.convert('RGB'), threshold=int(p['thr'])))


def _px_threshold(im, p):
    thr = int(p['thr'])
    _, _, _, _, ImageOps = _pil()
    g = ImageOps.grayscale(im.convert('RGB')).point(lambda k: 255 if k >= thr else 0)
    return _keep_alpha(im, g.convert('RGB'))


def _px_sepia(im, p):
    Image, _, _, _, ImageOps = _pil()
    g = ImageOps.grayscale(im.convert('RGB'))
    tone = ImageOps.colorize(g, black='#1d1206', white='#f4e3c0')
    return _keep_alpha(im, Image.blend(im.convert('RGB'), tone, max(0.0, min(1.0, p['a'] / 100.0))))


def _px_duotone(im, p):
    Image, _, _, _, ImageOps = _pil()
    g = ImageOps.grayscale(im.convert('RGB'))
    tone = ImageOps.colorize(g, black=p['dark'], white=p['light'])
    return _keep_alpha(im, Image.blend(im.convert('RGB'), tone, max(0.0, min(1.0, p['a'] / 100.0))))


def _px_splittone(im, p):
    """Two colours, one into the shadows and one into the highlights, weighted
    by luminance. What a grade does that a single tint cannot."""
    Image, _, _, _, ImageOps = _pil()
    rgbim = im.convert('RGB')
    lum = ImageOps.grayscale(rgbim)
    amt = max(0.0, min(1.0, p['a'] / 100.0))
    sh = Image.new('RGB', im.size, _rgb(p['dark']))
    hi = Image.new('RGB', im.size, _rgb(p['light']))
    # shadow mask is the inverted luminance; highlight mask is the luminance
    mixed = Image.composite(hi, sh, lum)
    return _keep_alpha(im, Image.blend(rgbim, Image.blend(rgbim, mixed, 0.75), amt))


def _px_balance(im, p):
    """Per-channel gain — a white balance you set by eye rather than by a
    single warm/cool axis."""

    def g(v):
        k = 1.0 + float(v) / 100.0
        return [max(0, min(255, int(round(n * k)))) for n in range(256)]

    return _lut(im, g(p['r']), g(p['g']), g(p['b']))


def _px_chanswap(im, p):
    Image, _, _, _, _ = _pil()
    a = im.getchannel('A')
    r, g, bl = im.convert('RGB').split()
    ch = {'r': r, 'g': g, 'b': bl}
    order = p['v']
    out = Image.merge('RGB', (ch[order[0]], ch[order[1]], ch[order[2]])).convert('RGBA')
    out.putalpha(a)
    return out


def _px_clarity(im, p):
    """Local contrast — a wide, low-amount unsharp mask. It is what makes a
    render read as having been photographed rather than smoothed."""
    _, _, _, ImageFilter, _ = _pil()
    return im.filter(ImageFilter.UnsharpMask(radius=float(p['r']), percent=int(p['v']), threshold=0))


def _filt(kind):
    def go(im, p):
        _, _, _, ImageFilter, _ = _pil()
        flt = {
            'smooth': ImageFilter.SMOOTH_MORE,
            'detail': ImageFilter.DETAIL,
            'edge': ImageFilter.EDGE_ENHANCE_MORE,
            'emboss': ImageFilter.EMBOSS,
            'find': ImageFilter.FIND_EDGES,
            'contour': ImageFilter.CONTOUR,
        }[kind]
        Image, _, _, _, _ = _pil()
        done = im.convert('RGB').filter(flt)
        amt = max(0.0, min(1.0, float(p.get('a', 100)) / 100.0))
        return _keep_alpha(im, Image.blend(im.convert('RGB'), done, amt))

    return go


def _px_pixelate(im, p):
    Image, _, _, _, _ = _pil()
    n = max(2, int(p['n']))
    w, h = im.size
    small = im.resize((max(1, w // n), max(1, h // n)), Image.BILINEAR)
    return small.resize((w, h), Image.NEAREST)


def _px_motion(im, p):
    """Directional blur through an explicit convolution kernel.

    PIL has no motion blur; a line kernel IS the whole implementation, and
    naming the four directions beats a free angle that quantises to them
    anyway at this kernel size."""
    _, _, _, ImageFilter, _ = _pil()
    n = 5
    k = [0.0] * (n * n)
    for t in range(n):
        if p['dir'] == 'horizontal':
            k[(n // 2) * n + t] = 1.0
        elif p['dir'] == 'vertical':
            k[t * n + (n // 2)] = 1.0
        elif p['dir'] == 'diagonal':
            k[t * n + t] = 1.0
        else:
            k[t * n + (n - 1 - t)] = 1.0
    total = sum(k) or 1.0
    out = im
    for _ in range(max(1, int(p['n']))):
        out = out.filter(ImageFilter.Kernel((n, n), [v / total for v in k], scale=1))
    return out


def _px_tiltshift(im, p):
    """Blur everything but a horizontal band — the shallow-depth look, done as
    a mask rather than a real defocus, and the tooltip says so."""
    Image, _, _, ImageFilter, _ = _pil()
    w, h = im.size
    blurred = im.filter(ImageFilter.GaussianBlur(float(p['r'])))
    band = max(2, int(h * p['band'] / 100.0))
    feather = max(1, int(h * p['feather'] / 100.0))
    centre = int(h * p['y'] / 100.0)
    mask = Image.new('L', (1, h), 0)
    px = mask.load()
    for yy in range(h):
        d = abs(yy - centre) - band // 2
        if d <= 0:
            px[0, yy] = 0
        elif d >= feather:
            px[0, yy] = 255
        else:
            px[0, yy] = int(255 * d / feather)
    mask = mask.resize((w, h))
    return Image.composite(blurred, im, mask)


def _px_chroma(im, p):
    """Lateral chromatic aberration: R and B pushed apart by a pixel or two.

    A render has none at all, which is one of the tells that reads as CGI."""
    Image, _, _, _, _ = _pil()
    a = im.getchannel('A')
    r, g, bl = im.convert('RGB').split()
    n = int(p['n'])
    r = r.transform(r.size, Image.AFFINE, (1, 0, -n, 0, 1, 0))
    bl = bl.transform(bl.size, Image.AFFINE, (1, 0, n, 0, 1, 0))
    out = Image.merge('RGB', (r, g, bl)).convert('RGBA')
    out.putalpha(a)
    return out


def _px_bloom(im, p):
    """Screen a blurred bright-pass back over the picture."""
    Image, ImageChops, _, ImageFilter, _ = _pil()
    thr = int(p['thr'])
    rgbim = im.convert('RGB')
    bright = rgbim.point(lambda k: 0 if k < thr else k)
    bright = bright.filter(ImageFilter.GaussianBlur(float(p['r'])))
    glow = ImageChops.screen(rgbim, bright)
    return _keep_alpha(im, Image.blend(rgbim, glow, max(0.0, min(1.0, p['a'] / 100.0))))


def _px_halation(im, p):
    """The red bleed film gets around a blown highlight — a bloom biased into
    the red channel rather than a neutral one."""
    Image, ImageChops, _, ImageFilter, _ = _pil()
    rgbim = im.convert('RGB')
    r, g, bl = rgbim.split()
    thr = int(p['thr'])
    hot = r.point(lambda k: 0 if k < thr else k).filter(ImageFilter.GaussianBlur(float(p['r'])))
    zero = hot.point(lambda k: int(k * 0.35))
    tinted = Image.merge('RGB', (hot, zero, zero.point(lambda k: int(k * 0.4))))
    glow = ImageChops.screen(rgbim, tinted)
    return _keep_alpha(im, Image.blend(rgbim, glow, max(0.0, min(1.0, p['a'] / 100.0))))


def _px_scanlines(im, p):
    Image, ImageChops, _, _, _ = _pil()
    w, h = im.size
    every = max(2, int(p['n']))
    amt = max(0.0, min(1.0, p['a'] / 100.0))
    col = Image.new('L', (1, h), 255)
    px = col.load()
    for yy in range(h):
        if yy % every == 0:
            px[0, yy] = int(255 * (1 - amt))
    mask = col.resize((w, h))
    dark = ImageChops.multiply(im.convert('RGB'), Image.merge('RGB', (mask, mask, mask)))
    return _keep_alpha(im, dark)


def _px_bleach(im, p):
    """Bleach bypass — the luminance overlaid back on a desaturated base."""
    Image, ImageChops, ImageEnhance, _, ImageOps = _pil()
    rgbim = im.convert('RGB')
    g = ImageOps.grayscale(rgbim).convert('RGB')
    desat = ImageEnhance.Color(rgbim).enhance(0.35)
    out = ImageChops.overlay(desat, g)
    return _keep_alpha(im, Image.blend(rgbim, out, max(0.0, min(1.0, p['a'] / 100.0))))


def _px_cross(im, p):
    """Cross-process — the three channels curved against each other, which is
    the whole of what the look is."""
    k = max(0.0, min(1.0, p['a'] / 100.0))

    def curve(pts):
        return [max(0, min(255, int(round(n + k * (pts(n / 255.0) * 255 - n))))) for n in range(256)]

    r = curve(lambda t: min(1.0, t**0.82 + 0.04))
    g = curve(lambda t: t**1.06)
    bl = curve(lambda t: max(0.0, t**1.22 - 0.03))
    return _lut(im, r, g, bl)


def _px_faded(im, p):
    """Lift the blacks. A faded print never reaches zero, and the absence of
    that lift is what makes a digital frame read as digital."""
    lift = float(p['v']) / 100.0
    tbl = [max(0, min(255, int(round(n * (1 - lift) + 255 * lift * 0.22)))) for n in range(256)]
    return _lut(im, tbl, tbl, tbl)


def _px_dither(im, p):
    Image, _, _, _, _ = _pil()
    a = im.getchannel('A')
    if p['mode'] == 'mono':
        out = im.convert('L').convert('1', dither=Image.FLOYDSTEINBERG).convert('RGBA')
    else:
        out = (
            im.convert('RGB').convert('P', palette=Image.ADAPTIVE, colors=max(2, min(256, int(p['n'])))).convert('RGBA')
        )
    out.putalpha(a)
    return out


def _px_sketch(im, p):
    """Colour-dodge of the blurred inverse — the pencil-sketch construction,
    exact and instant, unlike asking a diffusion model for one."""
    Image, ImageChops, _, ImageFilter, ImageOps = _pil()
    g = ImageOps.grayscale(im.convert('RGB'))
    inv = ImageOps.invert(g).filter(ImageFilter.GaussianBlur(float(p['r'])))
    # colour dodge: base * 255 / (255 - top)
    dodge = Image.new('L', im.size)
    dodge.putdata([min(255, int(bp * 255 / max(1, 255 - tp))) for bp, tp in zip(g.getdata(), inv.getdata())])
    out = dodge.convert('RGB')
    return _keep_alpha(im, Image.blend(im.convert('RGB'), out, max(0.0, min(1.0, p['a'] / 100.0))))


def _px_cartoon(im, p):
    """Posterised colour multiplied by its own edge map."""
    Image, ImageChops, _, ImageFilter, ImageOps = _pil()
    rgbim = im.convert('RGB')
    flat = ImageOps.posterize(rgbim.filter(ImageFilter.MedianFilter(5)), max(1, min(8, int(p['bits']))))
    edges = ImageOps.invert(ImageOps.grayscale(rgbim).filter(ImageFilter.FIND_EDGES))
    edges = edges.point(lambda k: 255 if k > (255 - int(p['edge'])) else int(k * 0.35))
    out = ImageChops.multiply(flat, Image.merge('RGB', (edges, edges, edges)))
    return _keep_alpha(im, Image.blend(rgbim, out, max(0.0, min(1.0, p['a'] / 100.0))))


def _px_border(im, p):
    Image, _, _, _, _ = _pil()
    w, h = im.size
    n = max(0, int(round(min(w, h) * p['n'] / 100.0)))
    if not n:
        return im
    out = Image.new('RGBA', (w + 2 * n, h + 2 * n), _rgba(p['col'], 100))
    out.alpha_composite(im, (n, n))
    return out


def _px_round(im, p):
    """Round the corners into the ALPHA, not by painting a colour over them —
    a painted corner is wrong the moment the picture lands on anything but the
    colour it was painted with."""
    Image, ImageChops, _, _, _ = _pil()
    from PIL import ImageDraw

    w, h = im.size
    r = max(0, int(min(w, h) * p['r'] / 100.0))
    if not r:
        return im
    mask = Image.new('L', (w, h), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, w - 1, h - 1], radius=r, fill=255)
    out = im.copy()
    out.putalpha(ImageChops.multiply(im.getchannel('A'), mask))
    return out
