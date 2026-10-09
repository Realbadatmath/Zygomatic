# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Pixel ops: the frame, the alpha channel and what goes behind it."""

from __future__ import annotations

import math

from zyg_workflows.picture_fx.pixel_tone import _pil, _rgb, _rgba


def _aspect_of(name, w, h):
    if name == 'source':
        return w / float(h or 1)
    a, _, b_ = name.partition(':')
    try:
        return float(a) / float(b_)
    except (TypeError, ValueError, ZeroDivisionError):
        return w / float(h or 1)


def _px_aspect(im, p):
    """Crop to an aspect — centred, or biased to the top, which is where a
    portrait's face is and where a centred crop takes the chin off."""
    w, h = im.size
    want = _aspect_of(p['v'], w, h)
    have = w / float(h or 1)
    if abs(want - have) < 1e-4:
        return im
    if have > want:  # too wide: cut the sides
        nw = int(round(h * want))
        x0 = int((w - nw) * (p['bias'] / 100.0))
        return im.crop((x0, 0, x0 + nw, h))
    nh = int(round(w / want))  # too tall: cut top or bottom
    y0 = int((h - nh) * (p['bias'] / 100.0))
    return im.crop((0, y0, w, y0 + nh))


def _px_letterbox(im, p):
    """PAD to an aspect instead of cropping to it — nothing leaves the frame."""
    Image, _, _, _, _ = _pil()
    w, h = im.size
    want = _aspect_of(p['v'], w, h)
    have = w / float(h or 1)
    if abs(want - have) < 1e-4:
        return im
    if have > want:
        nh = int(round(w / want))
        out = Image.new('RGBA', (w, nh), _rgba(p['col'], p['a']))
        out.alpha_composite(im, (0, (nh - h) // 2))
        return out
    nw = int(round(h * want))
    out = Image.new('RGBA', (nw, h), _rgba(p['col'], p['a']))
    out.alpha_composite(im, ((nw - w) // 2, 0))
    return out


def _px_longedge(im, p):
    """Resize by the LONG EDGE — the only resize that means the same thing for
    a portrait and a landscape, and what every downstream size limit is
    actually written in."""
    Image, _, _, _, _ = _pil()
    w, h = im.size
    n = int(p['n'])
    if max(w, h) == n:
        return im
    k = n / float(max(w, h))
    flt = {'lanczos': Image.LANCZOS, 'bicubic': Image.BICUBIC, 'bilinear': Image.BILINEAR, 'nearest': Image.NEAREST}[
        p['flt']
    ]
    return im.resize((max(1, int(round(w * k))), max(1, int(round(h * k)))), flt)


def _px_straighten(im, p):
    """A small rotation that KEEPS the canvas rectangular: rotate without
    expanding, then crop in far enough that no transparent wedge survives.

    The wedge is the whole reason a plain rotate is the wrong tool for a
    horizon that is two degrees off."""
    Image, _, _, _, _ = _pil()
    a = float(p['a'])
    if abs(a) < 0.01:
        return im
    w, h = im.size
    rot = im.rotate(-a, resample=Image.BICUBIC, expand=False)
    rad = abs(math.radians(a))
    scale = 1.0 / (abs(math.cos(rad)) + (h / float(w)) * abs(math.sin(rad)))
    nw, nh = int(w * scale), int(h * scale)
    x0, y0 = (w - nw) // 2, (h - nh) // 2
    out = rot.crop((x0, y0, x0 + nw, y0 + nh))
    return out.resize((w, h), Image.LANCZOS) if p['refit'] else out


def _px_mirror_half(im, p):
    """Mirror one half onto the other. A symmetry CHECK, not a beauty filter —
    a face that only looks right one way round is a face the model built out of
    two different references."""
    Image, _, _, _, _ = _pil()
    w, h = im.size
    half = w // 2
    out = im.copy()
    if p['v'] == 'left':
        left = im.crop((0, 0, half, h))
        out.paste(left.transpose(Image.FLIP_LEFT_RIGHT), (w - half, 0))
    else:
        right = im.crop((w - half, 0, w, h))
        out.paste(right.transpose(Image.FLIP_LEFT_RIGHT), (0, 0))
    return out


def _px_alpha_invert(im, p):
    _, _, _, _, ImageOps = _pil()
    out = im.copy()
    out.putalpha(ImageOps.invert(im.getchannel('A')))
    return out


def _px_alpha_feather(im, p):
    _, _, _, ImageFilter, _ = _pil()
    out = im.copy()
    out.putalpha(im.getchannel('A').filter(ImageFilter.GaussianBlur(float(p['r']))))
    return out


def _px_alpha_choke(im, p):
    """Pull the matte IN by a pixel or two. What kills the light halo a keyer
    leaves around a subject that was cut off a bright plate."""
    _, _, _, ImageFilter, _ = _pil()
    a = im.getchannel('A')
    n = int(p['n'])
    for _ in range(max(0, n)):
        a = a.filter(ImageFilter.MinFilter(3))
    out = im.copy()
    out.putalpha(a)
    return out


def _px_dropshadow(im, p):
    Image, _, _, ImageFilter, _ = _pil()
    off = int(p['off'])
    r = float(p['r'])
    pad = int(r * 2) + abs(off) + 2
    w, h = im.size
    canvas = Image.new('RGBA', (w + 2 * pad, h + 2 * pad), (0, 0, 0, 0))
    sh = Image.new('RGBA', (w, h), _rgba(p['col'], p['a']))
    sh.putalpha(im.getchannel('A').point(lambda k: int(k * p['a'] / 100.0)))
    shadow = Image.new('RGBA', canvas.size, (0, 0, 0, 0))
    shadow.paste(sh, (pad + off, pad + off))
    shadow = shadow.filter(ImageFilter.GaussianBlur(r))
    canvas.alpha_composite(shadow)
    canvas.alpha_composite(im, (pad, pad))
    return canvas


def _px_outline(im, p):
    """A stroke that follows the MATTE, grown out of the alpha itself rather
    than drawn round the bounding box."""
    Image, ImageChops, _, ImageFilter, _ = _pil()
    a = im.getchannel('A')
    grown = a
    for _ in range(max(1, int(p['n']))):
        grown = grown.filter(ImageFilter.MaxFilter(3))
    ring = ImageChops.subtract(grown, a)
    stroke = Image.new('RGBA', im.size, _rgba(p['col'], 100))
    stroke.putalpha(ring)
    out = Image.new('RGBA', im.size, (0, 0, 0, 0))
    out.alpha_composite(stroke)
    out.alpha_composite(im)
    return out


def _px_glow(im, p):
    Image, _, _, ImageFilter, _ = _pil()
    a = im.getchannel('A').filter(ImageFilter.GaussianBlur(float(p['r'])))
    glow = Image.new('RGBA', im.size, _rgba(p['col'], 100))
    glow.putalpha(a.point(lambda k: int(k * p['a'] / 100.0)))
    out = Image.new('RGBA', im.size, (0, 0, 0, 0))
    out.alpha_composite(glow)
    out.alpha_composite(im)
    return out


def _px_ground_grad(im, p):
    """Composite over a vertical two-colour ground — the honest inverse of the
    keyer when a flat colour reads as a cut-out."""
    Image, _, _, _, _ = _pil()
    w, h = im.size
    top, bot = _rgb(p['top']), _rgb(p['bot'])
    strip = Image.new('RGB', (1, h))
    px = strip.load()
    for yy in range(h):
        t = yy / float(max(1, h - 1))
        px[0, yy] = tuple(int(round(top[k] + (bot[k] - top[k]) * t)) for k in range(3))
    bg = strip.resize((w, h)).convert('RGBA')
    bg.alpha_composite(im)
    return bg


def _px_extend(im, p):
    """Grow the canvas by MIRRORING the edges outward.

    The deterministic answer to "the crop clipped the hair": it invents no
    detail, it reflects what is already there, and it is the right plate to
    hand an outpaint when you want one."""
    Image, _, _, _, _ = _pil()
    w, h = im.size
    m = int(round(max(w, h) * p['m'] / 100.0))
    if m <= 0:
        return im
    m = min(m, w - 1, h - 1)
    out = Image.new('RGBA', (w + 2 * m, h + 2 * m), (0, 0, 0, 0))
    out.paste(im, (m, m))
    left = im.crop((0, 0, m, h)).transpose(Image.FLIP_LEFT_RIGHT)
    right = im.crop((w - m, 0, w, h)).transpose(Image.FLIP_LEFT_RIGHT)
    out.paste(left, (0, m))
    out.paste(right, (w + m, m))
    band = out.crop((0, m, w + 2 * m, m + m)).transpose(Image.FLIP_TOP_BOTTOM)
    out.paste(band, (0, 0))
    band = out.crop((0, h, w + 2 * m, h + m)).transpose(Image.FLIP_TOP_BOTTOM)
    out.paste(band, (0, h + m))
    return out
