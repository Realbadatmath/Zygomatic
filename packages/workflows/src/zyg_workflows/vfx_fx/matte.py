# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The MATTE / KEY section of the rail (vfx_fx.py lines 1132-1436)."""

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

# ── MATTE / KEY ─────────────────────────────────────────────────────────────
# Half of compositing is the matte and none of it is visible in an RGB view, so
# every op here has a partner in the dock's Alpha view.  Look at what these do
# on the matte, not on the picture: a key that looks clean over black is
# routinely full of holes you only see over white.


def _alpha_op(filt):
    """Run `filt` on the ALPHA channel alone and merge it back.

    alphaextract gives a greyscale video of the matte; anything that works on
    luma then works on the matte, which is how one erosion filter becomes a
    choke and one gblur becomes an edge feather.  The RGB is untouched
    throughout -- processing the picture along with the matte is how edges pick
    up a halo that no amount of despill will take off again."""
    return (
        '[IN]format=rgba,split[$a][$b];'
        f'[$b]format=rgba,alphaextract,format=gray,{filt}[$m];'
        '[$a][$m]alphamerge,format=rgba[OUT]'
    )


_op(
    'chromakey',
    'Chroma key',
    'Matte',
    'side',
    'Chroma key — pull a matte on a colour in YUV, which is the right space for '
    'it: it keys on hue and ignores how brightly the screen was lit. Similarity '
    'sets how much of the colour goes; blend softens the edge into it.',
    '<path d="M14.6 3.4l6 6-9.4 9.4-6-6z"/><circle cx="7.4" cy="16.6" r="3.4"/><path d="M3.4 20.6l1.6-1.6"/>',
    [
        c('color', 'Screen colour', '#00ff00'),
        f('similarity', 'Similarity', 0.1, 0.01, 1, 0.002),
        f('blend', 'Blend', 0, 0, 1, 0.002),
        b('yuv', 'Colour is YUV', False),
    ],
    fn=lambda p, x: (
        f'format=rgba,chromakey=color={hexc(p["color"], "#00ff00")}:'
        f'similarity={_n(p["similarity"])}:blend={_n(p["blend"])}:'
        f'yuv={1 if p["yuv"] else 0}'
    ),
)

_op(
    'colorkey',
    'Colour key',
    'Matte',
    'side',
    'Colour key — the same idea in RGB, which keys on the whole colour rather '
    'than the hue. Right for a flat graphic or a solid background; wrong for a '
    'lit screen, where the brightness varies across the frame.',
    '<circle cx="8.4" cy="8.4" r="4.6"/><path d="M11.6 11.6l8.4 8.4M17 14.6l-2.4 2.4"/>',
    [
        c('color', 'Colour', '#000000'),
        f('similarity', 'Similarity', 0.1, 0.01, 1, 0.002),
        f('blend', 'Blend', 0, 0, 1, 0.002),
    ],
    fn=lambda p, x: (
        f'format=rgba,colorkey=color={hexc(p["color"], "#000000")}:'
        f'similarity={_n(p["similarity"])}:blend={_n(p["blend"])}'
    ),
)

_op(
    'lumakey',
    'Luma key',
    'Matte',
    'side',
    'Luma key — matte on brightness. THE key for fire, explosions and sparks shot '
    'against black, which is most of a stock element library: the flame is the '
    'bright part and the background is genuinely zero.',
    '<path d="M12 3.4l2.6 6.6 6.6.6-5 4.4 1.5 6.6L12 18.2 6.3 21.6l1.5-6.6-5-4.4 6.6-.6z"/>',
    [
        f('threshold', 'Threshold', 0, 0, 1, 0.002),
        f('tolerance', 'Tolerance', 0.01, 0, 1, 0.002),
        f('softness', 'Softness', 0, 0, 1, 0.002),
    ],
    fn=lambda p, x: (
        f'format=rgba,lumakey=threshold={_n(p["threshold"])}:'
        f'tolerance={_n(p["tolerance"])}:softness={_n(p["softness"])}'
    ),
)

_op(
    'despill',
    'Despill',
    'Matte',
    'side',
    'Despill — take the screen colour back out of the edges and the semi-'
    'transparent parts, which is where a key always leaves it. Without this a '
    'keyed element wears a green rim in every shot it is ever used in.',
    '<path d="M12 3.4s5.6 6 5.6 9.6a5.6 5.6 0 11-11.2 0C6.4 9.4 12 3.4 12 3.4z"/>'
    '<path d="M4 4l16 16" stroke-dasharray="2.6 2.4"/>',
    [
        e('type', 'Screen', 'green', ['green', 'blue']),
        f('mix', 'Mix', 0.5, 0, 1, 0.01),
        f('expand', 'Expand', 0, 0, 1, 0.01),
        f('brightness', 'Brightness', 0, -10, 10, 0.05),
        b('alpha', 'Write to alpha', False),
    ],
    fn=lambda p, x: (
        f'despill=type={p["type"]}:mix={_n(p["mix"])}:expand={_n(p["expand"])}:'
        f'brightness={_n(p["brightness"])}:alpha={1 if p["alpha"] else 0}'
    ),
)

_op(
    'mchoke',
    'Matte choke',
    'Matte',
    'side',
    'Choke or spread the matte — erode pulls the edge in, dilate pushes it out. '
    'One or two pixels of choke is the standard cure for the light fringe a key '
    'leaves behind, and it costs you nothing but a hair of the element.',
    '<circle cx="12" cy="12" r="8.4" stroke-dasharray="2.6 2.4"/><circle cx="12" cy="12" r="5.2"/>'
    '<path d="M12 6.8v-2M12 19.2v-2M6.8 12h-2M19.2 12h2"/>',
    [
        i('amount', 'Pixels', 0, -12, 12, 1, 'negative chokes in, positive spreads out'),
        i('passes', 'Passes', 1, 1, 6, 1),
    ],
    fn=lambda p, x: _alpha_op(
        ','.join(
            [('erosion' if p['amount'] < 0 else 'dilation') + '=coordinates=255']
            * max(1, min(6, int(abs(p['amount'])) * int(p['passes'])))
        )
        if p['amount']
        else 'null'
    ),
)

_op(
    'mblur',
    'Matte blur',
    'Matte',
    'side',
    'Blur the matte and nothing else — a soft edge on a hard-keyed element, which '
    'is what makes it sit into a plate rather than sit on top of one. The picture '
    'is untouched; only the edge goes soft.',
    '<circle cx="12" cy="12" r="5"/><circle cx="12" cy="12" r="7.4" opacity=".55"/>'
    '<circle cx="12" cy="12" r="9.6" opacity=".28"/>',
    [f('sigma', 'Radius', 2, 0, 40, 0.1), i('steps', 'Steps', 1, 1, 6)],
    fn=lambda p, x: _alpha_op(f'gblur=sigma={_n(p["sigma"])}:steps={int(p["steps"])}'),
)

_op(
    'mgamma',
    'Matte gamma',
    'Matte',
    'side',
    'Gamma and contrast ON THE MATTE. This is the real edge control: gamma up '
    'recovers the semi-transparent smoke a key threw away, gamma down cleans a '
    'grey background that should have been solid zero.',
    '<path d="M4 6h5.6c3 0 4 2 3.2 4.6L9.6 19"/><path d="M14 5.6h6.4v13H14z" stroke-dasharray="2.2 2"/>',
    [
        f('gamma', 'Gamma', 1, 0.1, 4, 0.01),
        f('contrast', 'Contrast', 1, 0, 4, 0.01),
        f('brightness', 'Brightness', 0, -1, 1, 0.005),
    ],
    fn=lambda p, x: _alpha_op(
        f'eq=gamma={_n(p["gamma"])}:contrast={_n(p["contrast"])}:brightness={_n(p["brightness"])}:eval=frame'
    ),
)

_op(
    'alphainv',
    'Invert matte',
    'Matte',
    'side',
    'Invert the matte — what was solid becomes a hole and the hole becomes the '
    'element. Half of every garbage matte is this button.',
    '<rect x="3.4" y="3.4" width="17.2" height="17.2" rx="1.4"/>'
    '<path d="M3.4 20.6L20.6 3.4"/><path d="M20.6 3.4v17.2H3.4z" fill="currentColor" stroke="none" opacity=".3"/>',
    fn=lambda p, x: _alpha_op('negate'),
)

_op(
    'lumatte',
    'Luma to matte',
    'Matte',
    'side',
    "Take the picture's own brightness and make it the matte. An element shot on "
    'black already carries its own alpha in its luminance; this is how you get at '
    'it, and it holds the soft falloff that a threshold key destroys.',
    '<path d="M12 3.6a8.4 8.4 0 010 16.8z" fill="currentColor" stroke="none"/>'
    '<circle cx="12" cy="12" r="8.4"/><path d="M12 3.6v16.8"/>',
    [f('gain', 'Gain', 1, 0, 4, 0.01), f('gamma', 'Gamma', 1, 0.1, 4, 0.01), b('keeprgb', 'Keep RGB', True)],
    fn=lambda p, x: (
        '[IN]format=rgba,split[$a][$b];'
        f'[$b]format=gray,eq=gamma={_n(p["gamma"])}:contrast={_n(p["gain"])}:eval=frame[$m];'
        '[$a][$m]alphamerge,format=rgba[OUT]'
    ),
)

_op(
    'premul',
    'Premultiply',
    'Matte',
    'side',
    'Premultiply — multiply the colour by its own matte. Which of premultiplied '
    'and straight an element is decides whether a blur across its edge smears '
    'colour outward or darkens it, and every renderer disagrees about the default.',
    '<circle cx="9.4" cy="12" r="5.6"/><rect x="12" y="6.4" width="9" height="11.2" rx="1"/>'
    '<path d="M12 12h9" opacity=".5"/>',
    fn=lambda p, x: 'format=rgba,premultiply=inplace=1',
)

_op(
    'unpremul',
    'Unpremultiply',
    'Matte',
    'side',
    'Unpremultiply — divide the colour back out of the matte, so the semi-'
    'transparent pixels carry their true colour again. The move before a grade, '
    'because grading premultiplied edges bends them towards black.',
    '<circle cx="9.4" cy="12" r="5.6" stroke-dasharray="2.4 2.2"/>'
    '<rect x="12" y="6.4" width="9" height="11.2" rx="1"/><path d="M13.6 12h5.8"/>',
    fn=lambda p, x: 'format=rgba,unpremultiply=inplace=1',
)

_op(
    'garbage',
    'Garbage matte',
    'Matte',
    'side',
    'Garbage matte — knock a rectangle out of the alpha, or keep only what is '
    'inside it. The rig, the light stand and the edge of the set all leave this '
    'way, and it costs nothing.',
    '<rect x="3.4" y="3.4" width="17.2" height="17.2" rx="1.4" stroke-dasharray="3 2.6"/>'
    '<path d="M8.4 8.4h7.2v7.2H8.4z"/><path d="M8.4 15.6l7.2-7.2"/>',
    [
        f('x', 'X %', 10, 0, 100, 0.1),
        f('y', 'Y %', 10, 0, 100, 0.1),
        f('w', 'Width %', 80, 0, 100, 0.1),
        f('h', 'Height %', 80, 0, 100, 0.1),
        f('soft', 'Soft edge', 0, 0, 40, 0.5),
        b('inside', 'Keep inside', True),
    ],
    fn=lambda p, x: (
        lambda x0, y0, x1, y1, inside: _alpha_op(
            f'geq=lum={_q(("" if inside else "255-") + f"(between(X,{x0},{x1})*between(Y,{y0},{y1}))*p(X,Y)")}'
            + (f',gblur=sigma={_n(p["soft"])}' if p['soft'] > 0 else '')
        )
    )(
        int(p['x'] * x['w'] / 100),
        int(p['y'] * x['h'] / 100),
        int((p['x'] + p['w']) * x['w'] / 100),
        int((p['y'] + p['h']) * x['h'] / 100),
        bool(p['inside']),
    ),
)

_op(
    'maskgrad',
    'Gradient matte',
    'Matte',
    'side',
    'Ramp the matte from opaque to clear across the frame. Fades an element off '
    'into the distance, or off the bottom of frame where it should meet the '
    'ground and does not.',
    '<rect x="3.4" y="4.4" width="17.2" height="15.2" rx="1.4"/>'
    '<path d="M6.4 4.4v15.2M9.6 4.4v15.2" opacity=".85"/><path d="M13 4.4v15.2" opacity=".55"/>'
    '<path d="M16.4 4.4v15.2" opacity=".3"/>',
    [
        e('dir', 'Direction', 'left', ['left', 'right', 'up', 'down', 'radial']),
        f('start', 'Start %', 0, 0, 100, 0.5),
        f('end', 'End %', 100, 0, 100, 0.5),
    ],
    fn=lambda p, x: (lambda a, bnd: _alpha_op(f'geq=lum={_q(f"p(X,Y)*clip({a},0,1)")}'))(
        ('(X-%d)/%d' % (p['start'] * x['w'] / 100, max(1, (p['end'] - p['start']) * x['w'] / 100)))
        if p['dir'] == 'left'
        else ('1-(X-%d)/%d' % (p['start'] * x['w'] / 100, max(1, (p['end'] - p['start']) * x['w'] / 100)))
        if p['dir'] == 'right'
        else ('(Y-%d)/%d' % (p['start'] * x['h'] / 100, max(1, (p['end'] - p['start']) * x['h'] / 100)))
        if p['dir'] == 'down'
        else ('1-(Y-%d)/%d' % (p['start'] * x['h'] / 100, max(1, (p['end'] - p['start']) * x['h'] / 100)))
        if p['dir'] == 'up'
        else (
            '1-(hypot(X-%d,Y-%d)-%d)/%d'
            % (x['w'] / 2, x['h'] / 2, p['start'] * x['w'] / 200, max(1, (p['end'] - p['start']) * x['w'] / 200))
        ),
        None,
    ),
)

_op(
    'alphafill',
    'Fill matte',
    'Matte',
    'side',
    'Throw the matte away and make the frame fully opaque. The right first move '
    'when a source arrives with a broken or half-written alpha and you would '
    'rather build one from scratch than fight it.',
    '<rect x="3.4" y="3.4" width="17.2" height="17.2" rx="1.4" fill="currentColor" stroke="none" opacity=".45"/>'
    '<rect x="3.4" y="3.4" width="17.2" height="17.2" rx="1.4"/>',
    [f('a', 'Opacity', 1, 0, 1, 0.005)],
    fn=lambda p, x: (
        f"format=rgba,colorchannelmixer=aa=0:ar=0:ag=0:ab=0,geq=r='r(X,Y)':"
        f"g='g(X,Y)':b='b(X,Y)':a='{int(round(p['a'] * 255))}'"
        if p['a'] < 1
        else "format=rgba,geq=r='r(X,Y)':g='g(X,Y)':b='b(X,Y)':a='255'"
    ),
)
