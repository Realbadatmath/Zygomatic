# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The COLOUR section of the rail (vfx_fx.py lines 498-1131)."""

from __future__ import annotations

import os

from zyg_workflows.vfx_fx.constants import (
    LUTDIR,
)
from zyg_workflows.vfx_fx.registry import (
    f,
    i,
    b,
    e,
    c,
    s,
    _op,
    hexc,
    _n,
    _q,
)

# ── COLOUR ──────────────────────────────────────────────────────────────────
# Ordered the way a grade is actually built: exposure and contrast first (get
# the range right), then the hue family, then the three that address specific
# tonal bands, then the transfer ops.  Stacking them in the rail's order is a
# sane default grade; the stack lets you reorder anyway, which matters because
# saturation before a curve and saturation after one are different pictures.


def _fx_curves(p, x):
    if p['preset'] != 'custom':
        return f'curves=preset={p["preset"]}'
    parts = []
    for ch in ('all', 'r', 'g', 'b'):
        v = str(p.get(ch) or '').strip()
        if v:
            parts.append(f'{ch}={_q(v)}')
    return 'curves=' + ':'.join(parts) if parts else 'null'


def _fx_lut3d(p, x):
    fn = os.path.basename(str(p.get('file') or ''))
    if not fn:
        return 'null'
    fp = os.path.realpath(os.path.join(LUTDIR, fn))
    root = os.path.realpath(LUTDIR)
    if not (fp.startswith(root + os.sep) and os.path.isfile(fp)):
        raise ValueError(f'LUT not found in the LUT library: {fn}')
    return f'lut3d=file={_q(fp)}:interp={p["interp"]}'


_op(
    'exposure',
    'Exposure',
    'Colour',
    'side',
    'Exposure — stops of light, applied linearly, the way a camera would have '
    'seen it. This is the knob to reach for first: a grade built on top of a '
    'wrong exposure fights itself the whole way.',
    '<circle cx="12" cy="12" r="4.2"/><path d="M12 2.4v3M12 18.6v3M2.4 12h3M18.6 12h3'
    'M5.2 5.2l2.1 2.1M16.7 16.7l2.1 2.1M18.8 5.2l-2.1 2.1M7.3 16.7l-2.1 2.1"/>',
    [f('e', 'Stops', 0, -4, 4, 0.01), f('black', 'Black point', 0, -0.2, 0.2, 0.001)],
    fn=lambda p, x: f'exposure=exposure={_n(p["e"])}:black={_n(p["black"])}',
)

_op(
    'bc',
    'Bright / Contrast',
    'Colour',
    'side',
    'Brightness and contrast — the fast, blunt pair. Contrast pivots about mid '
    'grey, so it will crush an element that was already sitting dark.',
    '<circle cx="12" cy="12" r="8.4"/><path d="M12 3.6a8.4 8.4 0 000 16.8z" fill="currentColor" stroke="none"/>',
    [f('brightness', 'Brightness', 0, -1, 1, 0.005), f('contrast', 'Contrast', 1, -2, 4, 0.01)],
    fn=lambda p, x: f'eq=brightness={_n(p["brightness"])}:contrast={_n(p["contrast"])}:eval=frame',
)

_op(
    'gamma',
    'Gamma',
    'Colour',
    'side',
    'Gamma — bend the mid-tones without moving black or white. Per-channel gamma '
    'is the honest way to neutralise a colour cast, because it leaves the ends '
    'of the range where they were.',
    '<path d="M4 5.5h11.4c3 0 4.2 2 3.2 4.6L14 20"/><path d="M11.6 11.4L8.4 20"/>',
    [
        f('g', 'Master', 1, 0.1, 4, 0.01),
        f('r', 'Red', 1, 0.1, 4, 0.01),
        f('gg', 'Green', 1, 0.1, 4, 0.01),
        f('bb', 'Blue', 1, 0.1, 4, 0.01),
        f('w', 'Weight', 1, 0, 1, 0.01, 'how much the correction spares the highlights'),
    ],
    fn=lambda p, x: (
        f'eq=gamma={_n(p["g"])}:gamma_r={_n(p["r"])}:gamma_g={_n(p["gg"])}:'
        f'gamma_b={_n(p["bb"])}:gamma_weight={_n(p["w"])}:eval=frame'
    ),
)

_op(
    'sat',
    'Saturation',
    'Colour',
    'side',
    'Saturation — a flat multiply on colourfulness. It will clip a fire element '
    'that is already at the edge of the gamut; Vibrance is the gentler one.',
    '<path d="M12 3.2s6.6 6.2 6.6 10.2a6.6 6.6 0 11-13.2 0C5.4 9.4 12 3.2 12 3.2z"/>',
    [f('s', 'Saturation', 1, 0, 3, 0.01)],
    fn=lambda p, x: f'eq=saturation={_n(p["s"])}:eval=frame',
)

_op(
    'vibrance',
    'Vibrance',
    'Colour',
    'side',
    'Vibrance — saturate what is dull and leave what is already saturated alone. '
    'On skin and on fire this is the difference between richer and radioactive.',
    '<path d="M4.6 18.4c4-10 10.8-13 14.8-13.8"/><path d="M4.6 18.4h14.8" stroke-dasharray="2.4 2.2"/>'
    '<circle cx="19.4" cy="4.6" r="1.6"/>',
    [
        f('intensity', 'Intensity', 0, -2, 2, 0.01),
        f('rbal', 'Red bal', 1, -10, 10, 0.05),
        f('gbal', 'Green bal', 1, -10, 10, 0.05),
        f('bbal', 'Blue bal', 1, -10, 10, 0.05),
        b('alternate', 'Alternate formula', False),
    ],
    fn=lambda p, x: (
        f'vibrance=intensity={_n(p["intensity"])}:rbal={_n(p["rbal"])}:'
        f'gbal={_n(p["gbal"])}:bbal={_n(p["bbal"])}:'
        f'alternate={1 if p["alternate"] else 0}'
    ),
)

_op(
    'hue',
    'Hue rotate',
    'Colour',
    'side',
    'Hue rotate — turn every colour around the wheel by the same angle. The one '
    'move that makes an orange fire element read as a blue-plasma one.',
    '<circle cx="12" cy="12" r="8.4"/><path d="M12 3.6v16.8" stroke-dasharray="2.4 2.2"/>'
    '<path d="M18.4 8.2A8.4 8.4 0 0112 20.4"/>',
    [f('h', 'Hue', 0, -180, 180, 0.5), f('s', 'Saturation', 1, -10, 10, 0.05), f('b2', 'Brightness', 0, -10, 10, 0.05)],
    fn=lambda p, x: f'hue=h={_n(p["h"])}:s={_n(p["s"])}:b={_n(p["b2"])}',
)

_op(
    'huesat',
    'Hue / Sat / Light',
    'Colour',
    'side',
    'Hue, saturation and lightness with a HUE RANGE — act on the reds only, or '
    "the cyans only. This is the one that changes a fire's colour without "
    'touching the smoke around it.',
    '<circle cx="12" cy="12" r="8.4"/><path d="M12 12l6.6-4.2M12 12l-1.6 8.2"/>'
    '<circle cx="12" cy="12" r="1.5" fill="currentColor" stroke="none"/>',
    [
        f('h', 'Hue', 0, -180, 180, 0.5),
        f('s', 'Saturation', 0, -1, 1, 0.01),
        f('i', 'Intensity', 0, -1, 1, 0.01),
        f('strength', 'Strength', 1, 0, 100, 0.1),
        b('r', 'Reds', True),
        b('y', 'Yellows', True),
        b('g', 'Greens', True),
        b('cy', 'Cyans', True),
        b('bl', 'Blues', True),
        b('m', 'Magentas', True),
    ],
    fn=lambda p, x: (
        f'huesaturation=hue={_n(p["h"])}:saturation={_n(p["s"])}:'
        f'intensity={_n(p["i"])}:strength={_n(p["strength"])}:colors='
        # `colors` is a FLAGS option, so the members are joined with '+'.
        # Concatenated ('rygcbm') is parsed as an EXPRESSION and dies
        # on "Undefined constant or missing '('" -- which reads as a
        # broken filtergraph rather than as a wrong separator.
        + (
            '+'.join(
                k
                for k, on in (
                    ('r', p['r']),
                    ('y', p['y']),
                    ('g', p['g']),
                    ('c', p['cy']),
                    ('b', p['bl']),
                    ('m', p['m']),
                )
                if on
            )
            or 'r'
        )
    ),
)

_op(
    'temp',
    'Temperature',
    'Colour',
    'side',
    'Colour temperature in kelvin — 6500 is neutral, below it warms, above it '
    "cools. Matching the element to the plate's white point is usually the "
    'single biggest step towards it looking like it was there.',
    '<path d="M10 14.4V5.4a2 2 0 014 0v9a4 4 0 11-4 0z"/><path d="M12 14.6a1.8 1.8 0 100 3.6 1.8 1.8 0 000-3.6z" fill="currentColor" stroke="none"/>',
    [
        i('temperature', 'Kelvin', 6500, 1000, 40000, 50),
        f('mix', 'Mix', 1, 0, 1, 0.01),
        f('pl', 'Preserve light', 0, 0, 1, 0.01),
    ],
    fn=lambda p, x: f'colortemperature=temperature={int(p["temperature"])}:mix={_n(p["mix"])}:pl={_n(p["pl"])}',
)

_op(
    'lgg',
    'Lift / Gamma / Gain',
    'Colour',
    'side',
    'Lift, gamma and gain — nine numbers, three per channel, one band each: '
    'shadows, mid-tones, highlights. The whole of a primary grade lives here, '
    'and it is the tool for a cast that only affects one end of the range.',
    '<path d="M3.4 20.6V15h3.6v5.6zM10.2 20.6V9.4h3.6v11.2zM17 20.6V4.2h3.6v16.4z"/>',
    [
        f('rs', 'Shadow R', 0, -1, 1, 0.005),
        f('gs', 'Shadow G', 0, -1, 1, 0.005),
        f('bs', 'Shadow B', 0, -1, 1, 0.005),
        f('rm', 'Mid R', 0, -1, 1, 0.005),
        f('gm', 'Mid G', 0, -1, 1, 0.005),
        f('bm', 'Mid B', 0, -1, 1, 0.005),
        f('rh', 'High R', 0, -1, 1, 0.005),
        f('gh', 'High G', 0, -1, 1, 0.005),
        f('bh', 'High B', 0, -1, 1, 0.005),
        b('pl', 'Preserve lightness', False),
    ],
    fn=lambda p, x: (
        'colorbalance='
        + ':'.join(f'{k}={_n(p[k])}' for k in ('rs', 'gs', 'bs', 'rm', 'gm', 'bm', 'rh', 'gh', 'bh'))
        + f':pl={1 if p["pl"] else 0}'
    ),
)

_op(
    'curves',
    'Curves',
    'Colour',
    'side',
    'Curves — arbitrary tone mapping, per channel or across all three. Points are '
    '"in/out" pairs from 0 to 1, space separated: 0/0 0.5/0.42 1/1 is a mild S '
    "pulled down in the mids. The presets are ffmpeg's own.",
    '<path d="M3.6 20.4C8 20.4 8.4 3.6 20.4 3.6"/><path d="M3.6 20.4V3.6M3.6 20.4h16.8" stroke-dasharray="2.2 2.2"/>',
    [
        e(
            'preset',
            'Preset',
            'custom',
            [
                'custom',
                'none',
                'color_negative',
                'cross_process',
                'darker',
                'increase_contrast',
                'lighter',
                'linear_contrast',
                'medium_contrast',
                'negative',
                'strong_contrast',
                'vintage',
            ],
        ),
        s('all', 'All points', '', 'e.g. 0/0 0.5/0.5 1/1', pat=r'[0-9./ ]{0,200}'),
        s('r', 'Red points', '', pat=r'[0-9./ ]{0,200}'),
        s('g', 'Green points', '', pat=r'[0-9./ ]{0,200}'),
        s('b', 'Blue points', '', pat=r'[0-9./ ]{0,200}'),
    ],
    fn=_fx_curves,
)

_op(
    'levels',
    'Levels',
    'Colour',
    'side',
    'Levels — set where black and white sit, per channel. Pulling the input white '
    'point down to where the histogram actually ends is how you get contrast '
    'without a curve, and without touching hue.',
    '<path d="M3.4 20.6l3.4-9 3.4 5 3.4-11.4 3.4 9 3.4-4.6"/><path d="M3.4 20.6h17.2"/>',
    [
        f('rimin', 'R in black', 0, -1, 1, 0.002),
        f('gimin', 'G in black', 0, -1, 1, 0.002),
        f('bimin', 'B in black', 0, -1, 1, 0.002),
        f('rimax', 'R in white', 1, -1, 1, 0.002),
        f('gimax', 'G in white', 1, -1, 1, 0.002),
        f('bimax', 'B in white', 1, -1, 1, 0.002),
        f('romin', 'R out black', 0, -1, 1, 0.002),
        f('romax', 'R out white', 1, -1, 1, 0.002),
    ],
    fn=lambda p, x: (
        'colorlevels='
        + ':'.join(f'{k}={_n(p[k])}' for k in ('rimin', 'gimin', 'bimin', 'rimax', 'gimax', 'bimax', 'romin', 'romax'))
    ),
)

_op(
    'mixer',
    'Channel mixer',
    'Colour',
    'side',
    'Channel mixer — build each output channel out of any mix of the input ones, '
    'alpha included. Cross-feeding a little green into red is how a green screen '
    'spill gets neutralised without a despill; the alpha row is how a channel '
    'becomes a matte.',
    '<path d="M4 6.4h16M4 12h16M4 17.6h16"/><circle cx="9" cy="6.4" r="2"/>'
    '<circle cx="15" cy="12" r="2"/><circle cx="7" cy="17.6" r="2"/>',
    [
        f('rr', 'R<-R', 1, -2, 2, 0.01),
        f('rg', 'R<-G', 0, -2, 2, 0.01),
        f('rb', 'R<-B', 0, -2, 2, 0.01),
        f('gr', 'G<-R', 0, -2, 2, 0.01),
        f('gg', 'G<-G', 1, -2, 2, 0.01),
        f('gb', 'G<-B', 0, -2, 2, 0.01),
        f('br', 'B<-R', 0, -2, 2, 0.01),
        f('bg', 'B<-G', 0, -2, 2, 0.01),
        f('bb', 'B<-B', 1, -2, 2, 0.01),
        f('aa', 'A<-A', 1, -2, 2, 0.01),
        e('pc', 'Preserve', 'none', ['none', 'lum', 'max', 'avg', 'sum', 'nrm', 'pwr']),
    ],
    fn=lambda p, x: (
        'colorchannelmixer='
        + ':'.join(f'{k}={_n(p[k])}' for k in ('rr', 'rg', 'rb', 'gr', 'gg', 'gb', 'br', 'bg', 'bb', 'aa'))
        + f':pc={p["pc"]}'
    ),
)

_op(
    'lut3d',
    '3D LUT',
    'Colour',
    'side',
    'Apply a 3D LUT (.cube / .3dl) from the LUT library. A look someone else '
    "built, or a camera-to-display transform. Only files inside the studio's own "
    'LUT directory load — a LUT path is a file read.',
    '<path d="M4.6 8.4l7.4-4.2 7.4 4.2v7.2L12 19.8l-7.4-4.2z"/><path d="M12 12.2l7.4-3.8M12 12.2v7.6M12 12.2L4.6 8.4"/>',
    [
        s('file', 'LUT file', '', 'a filename inside data/assets/luts/', pat=r'[-0-9A-Za-z_. ]{0,120}'),
        e('interp', 'Interpolation', 'tetrahedral', ['tetrahedral', 'trilinear', 'nearest', 'pyramid', 'prism']),
    ],
    fn=_fx_lut3d,
)

_op(
    'selcolor',
    'Selective colour',
    'Colour',
    'side',
    'Selective colour — adjust one colour family at a time in CMYK terms, the way '
    'a print grade does. Nine ranges including the neutrals, whites and blacks, '
    'which is the only place a "leave everything but the highlights" note lands.',
    '<circle cx="8.6" cy="9.4" r="4.6"/><circle cx="15.4" cy="9.4" r="4.6"/><circle cx="12" cy="15" r="4.6"/>',
    [
        e(
            'range',
            'Range',
            'reds',
            ['reds', 'yellows', 'greens', 'cyans', 'blues', 'magentas', 'whites', 'neutrals', 'blacks'],
        ),
        f('cyan', 'Cyan', 0, -1, 1, 0.01),
        f('magenta', 'Magenta', 0, -1, 1, 0.01),
        f('yellow', 'Yellow', 0, -1, 1, 0.01),
        f('black', 'Black', 0, -1, 1, 0.01),
        e('mode', 'Mode', 'absolute', ['absolute', 'relative']),
    ],
    fn=lambda p, x: (
        f'selectivecolor=correction_method={p["mode"]}:'
        f'{p["range"]}={_q(" ".join(_n(p[k]) for k in ("cyan", "magenta", "yellow", "black")))}'
    ),
)

_op(
    'ccorrect',
    'Shadow / High tint',
    'Colour',
    'side',
    'Tint the shadows one way and the highlights the other — the split-tone that '
    'separates a warm element from a cool plate. Two bands, four numbers, and it '
    'does not touch the mids at all.',
    '<path d="M12 3.4a8.6 8.6 0 000 17.2z" fill="currentColor" stroke="none"/>'
    '<circle cx="12" cy="12" r="8.6"/><path d="M12 3.4v17.2"/>',
    [
        f('rl', 'Shadow R', 0, -1, 1, 0.005),
        f('bl', 'Shadow B', 0, -1, 1, 0.005),
        f('rh', 'High R', 0, -1, 1, 0.005),
        f('bh', 'High B', 0, -1, 1, 0.005),
        f('saturation', 'Saturation', 1, -3, 3, 0.01),
        f('analyze', 'Analyze', 0, 0, 3, 1),
    ],
    fn=lambda p, x: (
        f'colorcorrect=rl={_n(p["rl"])}:bl={_n(p["bl"])}:rh={_n(p["rh"])}:'
        f'bh={_n(p["bh"])}:saturation={_n(p["saturation"])}'
    ),
)

_op(
    'ccontrast',
    'Colour contrast',
    'Colour',
    'side',
    'Contrast between opponent colour pairs — red vs cyan, green vs magenta, '
    'blue vs yellow — instead of between light and dark. Separates two things '
    'that are the same brightness, which luma contrast cannot do at all.',
    '<circle cx="9" cy="12" r="6"/><circle cx="15" cy="12" r="6"/>',
    [
        f('rc', 'Red-Cyan', 0, -1, 1, 0.01),
        f('gm', 'Green-Magenta', 0, -1, 1, 0.01),
        f('by', 'Blue-Yellow', 0, -1, 1, 0.01),
        f('pl', 'Preserve lightness', 0, 0, 1, 0.01),
    ],
    fn=lambda p, x: f'colorcontrast=rc={_n(p["rc"])}:gm={_n(p["gm"])}:by={_n(p["by"])}:pl={_n(p["pl"])}',
)

_op(
    'colorize',
    'Tint',
    'Colour',
    'side',
    'Tint — force the whole frame to one hue and keep its luminance. A dust or '
    'smoke element is grey by nature; this is how it becomes the colour of the '
    'ground it was kicked up from.',
    '<path d="M12 3.4l6 6a8.5 8.5 0 11-12 0z"/>',
    [
        f('hue', 'Hue', 0, 0, 360, 1),
        f('saturation', 'Saturation', 0.5, 0, 1, 0.01),
        f('lightness', 'Lightness', 0.5, 0, 1, 0.01),
        f('mix', 'Mix', 1, 0, 1, 0.01),
    ],
    fn=lambda p, x: (
        f'colorize=hue={_n(p["hue"])}:saturation={_n(p["saturation"])}:'
        f'lightness={_n(p["lightness"])}:mix={_n(p["mix"])}'
    ),
)

_op(
    'mono',
    'Monochrome',
    'Colour',
    'side',
    'Monochrome — desaturate through a filter, the way black-and-white film was '
    'shot. The two numbers are where in the colour plane the "filter" sits, so '
    'you choose which colours come out light and which come out dark.',
    '<circle cx="12" cy="12" r="8.4"/><path d="M12 3.6a8.4 8.4 0 010 16.8z" fill="currentColor" stroke="none"/>',
    [
        f('cb', 'Blue-yellow', 0, -1, 1, 0.01),
        f('cr', 'Red-green', 0, -1, 1, 0.01),
        f('size', 'Size', 1, 0.1, 10, 0.05),
        f('high', 'Highlights', 0, 0, 1, 0.01),
    ],
    fn=lambda p, x: f'monochrome=cb={_n(p["cb"])}:cr={_n(p["cr"])}:size={_n(p["size"])}:high={_n(p["high"])}',
)

_op(
    'negate',
    'Invert',
    'Colour',
    'side',
    'Invert the picture. With "alpha too" off, the matte survives the flip — '
    'inverting alpha as well is almost never what you meant and turns an element '
    'into a hole.',
    '<circle cx="12" cy="12" r="8.4"/><path d="M12 3.6v16.8"/>'
    '<path d="M12 3.6a8.4 8.4 0 000 16.8z" fill="currentColor" stroke="none"/>',
    [b('alpha', 'Alpha too', False)],
    fn=lambda p, x: f'negate=negate_alpha={1 if p["alpha"] else 0}',
)

_op(
    'posterize',
    'Posterize',
    'Colour',
    'side',
    'Posterize — quantise each channel to N levels. Four levels of orange is a '
    'cel-shaded flame; it is also how you check for banding you were about to '
    'introduce anyway.',
    '<path d="M3.4 20.6V16h4.3v-4.3H12V7.4h4.3V3.4h4.3"/>',
    [i('levels', 'Levels', 8, 2, 64)],
    fn=lambda p, x: (
        lambda n: (
            f'lutrgb=r={_q(f"floor(val/(256/{n}))*(255/{n - 1})")}:'
            f'g={_q(f"floor(val/(256/{n}))*(255/{n - 1})")}:'
            f'b={_q(f"floor(val/(256/{n}))*(255/{n - 1})")}'
        )
    )(int(p['levels'])),
)

_op(
    'threshold',
    'Threshold',
    'Colour',
    'side',
    'Hard threshold on luminance — everything above goes white, everything below '
    'goes black. Rarely a look on its own; constantly useful as the source of a '
    'matte for something else in the stack.',
    '<path d="M3.4 12h17.2"/><rect x="3.4" y="4" width="17.2" height="8" fill="currentColor" stroke="none" opacity=".35"/>'
    '<rect x="3.4" y="4" width="17.2" height="16" rx="1.2"/>',
    [f('t', 'Threshold', 0.5, 0, 1, 0.005)],
    fn=lambda p, x: (lambda v: f'lutyuv=y={_q(f"if(gt(val,{v}),255,0)")}:u=128:v=128')(int(round(16 + p['t'] * 219))),
)

_op(
    'pseudo',
    'False colour',
    'Colour',
    'side',
    'False colour — map luminance onto a palette so you can SEE exposure instead '
    'of guessing at it. A diagnostic view you would not ship, unless you are '
    'making something look like a thermal camera, in which case you would.',
    '<rect x="3.4" y="7" width="17.2" height="10" rx="1.4"/><path d="M7.7 7v10M12 7v10M16.3 7v10"/>',
    [
        e(
            'preset',
            'Palette',
            'magma',
            [
                'magma',
                'inferno',
                'plasma',
                'viridis',
                'turbo',
                'cividis',
                'range1',
                'range2',
                'shadows',
                'highlights',
                'solar',
                'nominal',
                'preferred',
                'total',
            ],
        ),
        f('opacity', 'Opacity', 1, 0, 1, 0.01),
    ],
    fn=lambda p, x: f'pseudocolor=preset={p["preset"]}:opacity={_n(p["opacity"])}',
)

_op(
    'tonemap',
    'Tonemap',
    'Colour',
    'side',
    'Tonemap — bring an over-range render down into a displayable 0-1 without '
    'the highlights turning into a flat white slab. This is the fix for the '
    'blown-element failure the volume renders hit: the alpha stays perfect while '
    'the RGB is unrecoverable, so nothing downstream reports a problem.',
    '<path d="M3.4 20.6c5-.4 6.6-12.6 17.2-16"/><path d="M3.4 20.6V3.4M3.4 20.6h17.2" stroke-dasharray="2.2 2.2"/>',
    [
        e('t', 'Curve', 'hable', ['none', 'clip', 'linear', 'gamma', 'reinhard', 'hable', 'mobius']),
        f('param', 'Param', 0.5, 0.01, 4, 0.01),
        f('desat', 'Desaturate', 2, 0, 8, 0.05),
        f('peak', 'Peak', 0, 0, 20, 0.1, '0 = detect'),
    ],
    fn=lambda p, x: (
        f'tonemap=tonemap={p["t"]}:param={_n(p["param"])}:desat={_n(p["desat"])}'
        + (f':peak={_n(p["peak"])}' if p['peak'] > 0 else '')
    ),
)

_op(
    'normalize',
    'Auto normalize',
    'Colour',
    'side',
    'Stretch the range so the darkest pixel lands on the black point and the '
    'brightest on the white point, tracked over time with a smoothing window. '
    'Independence 1 does it per channel, which also removes a colour cast.',
    '<path d="M3.4 17.4l4.6-4.6 3.4 3.4 9.2-9.2"/><path d="M13.8 7h7.2v7.2" stroke-dasharray="2.2 2"/>',
    [
        c('blackpt', 'Black point', '#000000'),
        c('whitept', 'White point', '#ffffff'),
        i('smoothing', 'Smoothing', 0, 0, 240, 1, 'frames of history'),
        f('independence', 'Independence', 1, 0, 1, 0.01),
        f('strength', 'Strength', 1, 0, 1, 0.01),
    ],
    kinds='v',
    fn=lambda p, x: (
        f'normalize=blackpt={hexc(p["blackpt"], "#000000")}:'
        f'whitept={hexc(p["whitept"], "#ffffff")}:'
        f'smoothing={int(p["smoothing"])}:independence={_n(p["independence"])}:'
        f'strength={_n(p["strength"])}'
    ),
)

_op(
    'histeq',
    'Histogram equalize',
    'Colour',
    'side',
    'Redistribute the tones so the histogram fills the range evenly. It pulls '
    'detail out of a flat, low-contrast plate — and it will also pull grain and '
    'compression blocks out with it, so look at the result at 1:1.',
    '<path d="M3.6 20.4V13h2.6v7.4zM8 20.4V8.6h2.6v11.8zM12.4 20.4V4.6H15v15.8zM16.8 20.4V10.4h2.6v10z"/>',
    [
        f('strength', 'Strength', 0.2, 0, 1, 0.01),
        f('intensity', 'Intensity', 0.21, 0, 1, 0.01),
        e('antibanding', 'Antibanding', 'none', ['none', 'weak', 'strong']),
    ],
    fn=lambda p, x: (
        f'histeq=strength={_n(p["strength"])}:intensity={_n(p["intensity"])}:antibanding={p["antibanding"]}'
    ),
)

_op(
    'colorhold',
    'Colour isolate',
    'Colour',
    'side',
    'Keep one colour and grey out everything else. The classic "red coat" shot, '
    'and a quick way to see how much of a plate is actually the colour you think '
    'you are about to key.',
    '<circle cx="12" cy="12" r="8.4" opacity=".4"/><path d="M12 3.6a8.4 8.4 0 018.4 8.4H12z" fill="currentColor" stroke="none"/>',
    [
        c('color', 'Colour', '#ff0000'),
        f('similarity', 'Similarity', 0.1, 0.01, 1, 0.005),
        f('blend', 'Blend', 0, 0, 1, 0.005),
    ],
    fn=lambda p, x: (
        f'colorhold=color={hexc(p["color"], "#ff0000")}:similarity={_n(p["similarity"])}:blend={_n(p["blend"])}'
    ),
)

_op(
    'colorspace',
    'Colour space',
    'Colour',
    'side',
    'Convert between colour spaces — primaries, transfer and matrix together. '
    'Nearly every file in this library has its colour properties UNSET, so this '
    'op has to be told what to assume the input is; without that ffmpeg refuses '
    'the frame outright. Getting it wrong is why an element that graded '
    'perfectly on one machine comes back green on another.',
    '<path d="M12 3.6l7.4 4.2v8.4L12 20.4l-7.4-4.2V7.8z"/><path d="M12 12l7.4-4.2M12 12v8.4M12 12L4.6 7.8"/>',
    [
        e(
            'iall',
            'Assume input is',
            'bt709',
            ['bt709', 'bt601-6-625', 'bt601-6-525', 'smpte170m', 'smpte240m', 'bt2020'],
        ),
        e('space', 'Matrix', 'bt709', ['bt709', 'bt470bg', 'smpte170m', 'bt2020ncl', 'fcc']),
        e('trc', 'Transfer', 'bt709', ['bt709', 'gamma22', 'gamma28', 'smpte170m', 'srgb', 'linear', 'bt2020-10']),
        e('primaries', 'Primaries', 'bt709', ['bt709', 'bt470bg', 'smpte170m', 'bt2020', 'film']),
        e('range', 'Range', 'tv', ['tv', 'pc']),
    ],
    fn=lambda p, x: (
        f'colorspace=iall={p["iall"]}:space={p["space"]}:trc={p["trc"]}:'
        f'primaries={p["primaries"]}:range={p["range"]}:format=yuv444p12'
    ),
)
