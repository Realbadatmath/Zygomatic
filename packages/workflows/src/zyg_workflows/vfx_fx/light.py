# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The LIGHT / ATMOSPHERE section of the rail (vfx_fx.py lines 1855-2164)."""

from __future__ import annotations


from zyg_workflows.vfx_fx.registry import (
    f,
    i,
    b,
    e,
    c,
    _op,
    hexc,
    _n,
    _q,
)

# ── LIGHT / ATMOSPHERE ──────────────────────────────────────────────────────
# The ops that BRANCH.  Everything above is a straight line through one filter;
# a glow is the picture screened over a blurred copy of its own highlights, so
# it needs a split, two paths and a blend.  That is why `fn` may return a whole
# fragment rather than a filter: a compositor's most-used effects are graphs,
# not filters, and pretending otherwise would have cost the interesting half.


def _bright_pass(thr):
    """Keep only what is brighter than `thr` (0-1), per channel, black elsewhere."""
    v = int(round(max(0.0, min(1.0, thr)) * 255))
    ex = _q(f'if(gt(val,{v}),val,0)')
    return f'lutrgb=r={ex}:g={ex}:b={ex}'


def _fx_glow(p, x):
    return (
        '[IN]format=rgba,split[$a][$b];'
        f'[$b]{_bright_pass(p["thr"])},gblur=sigma={_n(p["sigma"])}:steps=3[$g];'
        f'[$a][$g]blend=all_mode=screen:all_opacity={_n(p["amount"])},format=rgba[OUT]'
    )


def _fx_streak(p, x):
    a2 = (p['angle'] + 90) % 360
    cross = f',dblur=angle={_n(a2)}:radius={_n(p["length"])}' if p['cross'] else ''
    return (
        '[IN]format=rgba,split[$a][$b];'
        f'[$b]{_bright_pass(p["thr"])},dblur=angle={_n(p["angle"])}:'
        f'radius={_n(p["length"])}{cross}[$g];'
        f'[$a][$g]blend=all_mode=screen:all_opacity={_n(p["amount"])},format=rgba[OUT]'
    )


def _fx_halation(p, x):
    return (
        '[IN]format=rgba,split[$a][$b];'
        f'[$b]{_bright_pass(p["thr"])},gblur=sigma={_n(p["sigma"])}:steps=3,'
        f'colorize=hue={_n(p["hue"])}:saturation={_n(p["sat"])}:lightness=0.5:mix=1[$g];'
        f'[$a][$g]blend=all_mode=screen:all_opacity={_n(p["amount"])},format=rgba[OUT]'
    )


def _fx_lightwrap(p, x):
    """Light wrap without a background plate: glow the element's OWN edge.

    A true light wrap samples the background and wraps it inward over the
    element's rim.  There is no background in the stack -- an element is edited
    alone here and married to a plate downstream -- so this does the half that
    does not need one: the band is `blur(alpha) - alpha`, i.e. exactly the ring
    just outside the matte, tinted and laid over the edge.  Named for what it
    is, because calling it a light wrap and having it not read the background
    would be a caption that lies."""
    col = hexc(p['color'], '#ffffff')
    return (
        '[IN]format=rgba,split[$a][$b];'
        '[$b]format=rgba,alphaextract,format=gray,split[$m1][$m2];'
        f'[$m1]gblur=sigma={_n(p["sigma"])}:steps=2[$mb];'
        '[$mb][$m2]blend=all_mode=subtract[$edge];'
        f'color=c={col}:s={x["w"]}x{x["h"]}:r={_n(x["fps"])},format=rgba[$col];'
        '[$col][$edge]alphamerge[$wrap];'
        f'[$a][$wrap]overlay=format=auto:shortest=1:alpha=premultiplied[OUT]'
        if False
        else '[IN]format=rgba,split[$a][$b];'
        '[$b]format=rgba,alphaextract,format=gray,split[$m1][$m2];'
        f'[$m1]gblur=sigma={_n(p["sigma"])}:steps=2[$mb];'
        '[$mb][$m2]blend=all_mode=subtract[$edge];'
        f'color=c={col}:s={x["w"]}x{x["h"]}:r={_n(x["fps"])},format=rgba[$col];'
        f'[$col][$edge]alphamerge,colorchannelmixer=aa={_n(p["amount"])}[$wrap];'
        '[$a][$wrap]overlay=format=auto:shortest=1[OUT]'
    )


_op(
    'glow',
    'Glow / bloom',
    'Light',
    'side',
    'Glow — screen a blurred copy of the highlights back over the picture. The '
    'threshold decides what counts as a highlight, which is the knob that matters: '
    'too low and the whole element fogs, too high and nothing blooms at all.',
    '<circle cx="12" cy="12" r="3.4" fill="currentColor" stroke="none"/>'
    '<circle cx="12" cy="12" r="6" opacity=".55"/><circle cx="12" cy="12" r="8.8" opacity=".28"/>',
    [
        f('thr', 'Threshold', 0.6, 0, 1, 0.005),
        f('sigma', 'Radius', 14, 0.5, 120, 0.5),
        f('amount', 'Amount', 0.7, 0, 1, 0.01),
    ],
    fn=_fx_glow,
)

_op(
    'streak',
    'Anamorphic streak',
    'Light',
    'side',
    'Streaks — the same bright-pass, blurred along ONE axis. This is the '
    'horizontal blue flare an anamorphic lens throws off a highlight; "cross" '
    'adds the perpendicular one for a four-point star.',
    '<path d="M3 12h18M12 3v18" opacity=".35"/><path d="M2 12h20"/>'
    '<circle cx="12" cy="12" r="2.2" fill="currentColor" stroke="none"/>',
    [
        f('thr', 'Threshold', 0.7, 0, 1, 0.005),
        f('angle', 'Angle', 0, 0, 360, 0.5),
        f('length', 'Length', 40, 1, 200, 0.5),
        f('amount', 'Amount', 0.6, 0, 1, 0.01),
        b('cross', 'Cross', False),
    ],
    fn=_fx_streak,
)

_op(
    'halation',
    'Halation',
    'Light',
    'side',
    'Halation — the warm bleed film gets when bright light scatters off the back '
    'of the stock and comes back through it. Always red-orange, always only '
    'around the highlights; it is most of why film highlights look kind.',
    '<circle cx="12" cy="12" r="3" fill="currentColor" stroke="none"/>'
    '<circle cx="12" cy="12" r="6.4" opacity=".5"/><path d="M12 2.6v2M12 19.4v2M2.6 12h2M19.4 12h2" opacity=".5"/>',
    [
        f('thr', 'Threshold', 0.72, 0, 1, 0.005),
        f('sigma', 'Radius', 18, 0.5, 120, 0.5),
        f('hue', 'Hue', 15, 0, 360, 1),
        f('sat', 'Saturation', 0.8, 0, 1, 0.01),
        f('amount', 'Amount', 0.5, 0, 1, 0.01),
    ],
    fn=_fx_halation,
)

_op(
    'lightwrap',
    'Edge light',
    'Light',
    'side',
    'Edge light — a tinted band exactly outside the matte, from blur(alpha) minus '
    'alpha. Not a true light wrap: there is no background in this stack to sample, '
    'so it lights the rim rather than wrapping the plate around it.',
    '<path d="M8 4.4h8a3.6 3.6 0 013.6 3.6v8a3.6 3.6 0 01-3.6 3.6H8A3.6 3.6 0 014.4 16V8A3.6 3.6 0 018 4.4z"/>'
    '<path d="M6 2.4h12a3.6 3.6 0 013.6 3.6v12" opacity=".4"/>',
    [c('color', 'Colour', '#ffffff'), f('sigma', 'Width', 10, 0.5, 80, 0.5), f('amount', 'Amount', 0.6, 0, 1, 0.01)],
    fn=_fx_lightwrap,
)

_op(
    'vignette',
    'Vignette',
    'Light',
    'side',
    'Vignette — darken towards the corners, the way a real lens does. A slight '
    'one is invisible and pulls the eye to the middle; a heavy one is a look. '
    "Backward mode brightens the corners instead, which undoes a plate's own.",
    '<rect x="3" y="4.4" width="18" height="15.2" rx="2"/><ellipse cx="12" cy="12" rx="6.6" ry="5.2" opacity=".5"/>',
    [
        f('angle', 'Angle', 1.0472, 0.1, 1.5, 0.005, 'radians — bigger is stronger'),
        f('x0', 'Centre X', 0.5, 0, 1, 0.005),
        f('y0', 'Centre Y', 0.5, 0, 1, 0.005),
        e('mode', 'Mode', 'forward', ['forward', 'backward']),
        b('dither', 'Dither', True),
    ],
    fn=lambda p, x: (
        f'vignette=angle={_n(p["angle"])}:x0=w*{_n(p["x0"])}:y0=h*{_n(p["y0"])}:'
        f'mode={p["mode"]}:dither={1 if p["dither"] else 0}:eval=init'
    ),
)

_op(
    'chromab',
    'Chromatic aberration',
    'Light',
    'side',
    'Push the red and blue channels apart in opposite directions — the colour '
    'fringing a cheap lens shows towards the edge of frame. A couple of pixels is '
    'a strong hint that an element was photographed rather than rendered.',
    '<circle cx="9.6" cy="12" r="6" opacity=".7"/><circle cx="12" cy="12" r="6" opacity=".5"/>'
    '<circle cx="14.4" cy="12" r="6" opacity=".7"/>',
    [
        i('rh', 'Red X', 2, -60, 60),
        i('rv', 'Red Y', 0, -60, 60),
        i('bh', 'Blue X', -2, -60, 60),
        i('bv', 'Blue Y', 0, -60, 60),
        e('edge', 'Edge', 'smear', ['smear', 'wrap', 'blank']),
    ],
    fn=lambda p, x: (
        f'rgbashift=rh={int(p["rh"])}:rv={int(p["rv"])}:bh={int(p["bh"])}:bv={int(p["bv"])}:edge={p["edge"]}'
    ),
)


def _fx_flicker(p, x):
    ex = _n(p['depth']) + '*sin(2*PI*' + _n(p['rate']) + '*t)'
    if p['rate2'] > 0:
        # two incommensurate sines, because ONE sine reads as a pulse rather
        # than as flicker -- the eye locks onto a period it can count
        ex += '*sin(2*PI*' + _n(p['rate2']) + '*t)'
    return 'eq=brightness=' + _q(ex) + ':eval=frame'


_op(
    'flicker',
    'Flicker',
    'Light',
    'side',
    'Modulate exposure over time — the unsteady light of a fire, a fluorescent '
    'tube or an old projector gate. It is an expression in t, so the rate and the '
    'depth are both yours; depth 0 turns it off without removing it from the stack.',
    '<path d="M12 3.4l2.4 5.6 5.6.6-4.2 3.8 1.2 5.6L12 16.4 6.9 19l1.3-5.6L4 9.6l5.6-.6z"/>',
    [
        f('depth', 'Depth', 0.08, 0, 0.8, 0.002),
        f('rate', 'Rate', 8, 0.1, 60, 0.1, 'Hz'),
        f('rate2', 'Second rate', 3.7, 0, 60, 0.1, '0 = single sine'),
    ],
    kinds='v',
    fn=lambda p, x: _fx_flicker(p, x),
)

_op(
    'bleach',
    'Bleach bypass',
    'Light',
    'side',
    'Bleach bypass — the silver-retention lab process: contrast way up, colour '
    'way down, highlights hard. A whole look in one button, and a preset rather '
    'than a filter, so the stack shows the three moves it is made of.',
    '<path d="M6 3.4h12l-1.6 14.2A3.4 3.4 0 0113 20.6h-2a3.4 3.4 0 01-3.4-3z"/><path d="M6.6 9.4h10.8" opacity=".5"/>',
    [f('amount', 'Amount', 1, 0, 1, 0.01)],
    fn=lambda p, x: (
        f'eq=saturation={_n(1 - 0.65 * p["amount"])}:contrast={_n(1 + 0.55 * p["amount"])}'
        f':eval=frame,curves=all={_q("0/0 0.25/0.16 0.5/0.5 0.75/0.86 1/1")}'
    ),
)

_op(
    'filmlook',
    'Film look',
    'Light',
    'side',
    'The stack a film emulation is actually made of, in one op: a soft S-curve, a '
    'touch of halation-free warmth, grain, and a light vignette. Every part of it '
    'exists separately in this rail — this is the shortcut, not the only route.',
    '<rect x="3.4" y="5.4" width="17.2" height="13.2" rx="1.4"/>'
    '<path d="M3.4 8.4h17.2M3.4 15.6h17.2"/><path d="M6.4 5.4v3M9.8 5.4v3M13.2 5.4v3M16.6 5.4v3"/>',
    [
        f('contrast', 'Contrast', 0.5, 0, 1, 0.01),
        f('warmth', 'Warmth', 0.4, 0, 1, 0.01),
        i('grain', 'Grain', 8, 0, 60),
        f('vig', 'Vignette', 0.35, 0, 1, 0.01),
    ],
    fn=lambda p, x: (
        f'curves=all={_q("0/0.02 0.25/0.2 0.5/0.5 0.75/0.8 1/0.98")},'
        f'eq=contrast={_n(1 + 0.4 * p["contrast"])}:eval=frame,'
        f'colortemperature=temperature={int(6500 - 1200 * p["warmth"])}:mix={_n(p["warmth"])}:pl=1'
        + (f',noise=alls={int(p["grain"])}:allf=t' if p['grain'] else '')
        + (f',vignette=angle={_n(0.3 + 0.7 * p["vig"])}:mode=forward:eval=init' if p['vig'] else '')
    ),
)

_op(
    'daynight',
    'Day for night',
    'Light',
    'side',
    'Day for night — the old trick of shooting in daylight and printing it as '
    'moonlight: underexpose hard, pull the colour towards blue, and crush the '
    'highlights so nothing reads as sun.',
    '<path d="M15.6 3.6A8.6 8.6 0 1020.4 13a6.8 6.8 0 01-4.8-9.4z"/>',
    [f('amount', 'Amount', 1, 0, 1, 0.01), i('kelvin', 'Kelvin', 15000, 6500, 40000, 100)],
    fn=lambda p, x: (
        f'exposure=exposure={_n(-1.6 * p["amount"])},'
        f'colortemperature=temperature={int(p["kelvin"])}:mix={_n(p["amount"])}:pl=0,'
        f'eq=saturation={_n(1 - 0.45 * p["amount"])}:contrast={_n(1 + 0.2 * p["amount"])}'
        f':eval=frame'
    ),
)

_op(
    'photosens',
    'Flash guard',
    'Light',
    'side',
    'Detect and damp frames that flash hard enough to be a photosensitivity risk. '
    'Half this library is nuclear-test footage and explosion elements, which is '
    'exactly the content that triggers it — this is a safety pass, not a look.',
    '<path d="M12 3.4l9 15.6H3z"/><path d="M12 9.4v4.4M12 16.4v.4" stroke-width="2"/>',
    [i('frames', 'Window', 30, 2, 240), f('threshold', 'Threshold', 1, 0.1, 1, 0.01), i('skip', 'Skip', 1, 1, 1024)],
    kinds='v',
    fn=lambda p, x: (
        f'photosensitivity=frames={int(p["frames"])}:threshold={_n(p["threshold"])}:skip={int(p["skip"])}:bypass=0'
    ),
)

_op(
    'limiter',
    'Legal limiter',
    'Light',
    'side',
    'Clamp every value into a legal range. Broadcast wants 16-235; a render that '
    'went over-range wants clipping somewhere sane rather than wherever the '
    'encoder decides. Runs last, after everything that could push a value out.',
    '<path d="M3.4 7.4h17.2M3.4 16.6h17.2"/><path d="M8 12h8" stroke-dasharray="2.2 2"/><path d="M6 5.4v4M18 14.6v4"/>',
    [
        i('min', 'Minimum', 16, 0, 65535),
        i('max', 'Maximum', 235, 0, 65535),
        e('planes', 'Planes', 'all', ['all', 'luma']),
    ],
    fn=lambda p, x: f'limiter=min={int(p["min"])}:max={int(p["max"])}:planes={15 if p["planes"] == "all" else 1}',
)
