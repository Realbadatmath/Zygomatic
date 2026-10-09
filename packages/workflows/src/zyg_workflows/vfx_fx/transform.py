# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The TRANSFORM section of the rail (vfx_fx.py lines 174-497)."""

from __future__ import annotations


from zyg_workflows.vfx_fx.registry import (
    f,
    i,
    b,
    e,
    _op,
    _n,
)

# ── TRANSFORM ───────────────────────────────────────────────────────────────
# Every geometric op that can push pixels off the frame keeps the canvas size
# and fills with black@0, not black.  Filling an element's new corners with
# OPAQUE black is the mistake that turns a matte into a card, and it renders as
# a perfectly plausible-looking success.


def _fx_move(p, x):
    # ffmpeg has no translate filter.  overlay onto a transparent canvas is the
    # one formulation that takes NEGATIVE offsets natively; pad+crop needs a
    # different expression per sign and gets the edge wrong on one of them.
    dx, dy = p['dx'] * x['w'] / 100.0, p['dy'] * x['h'] / 100.0
    return (
        f'color=c=black@0:s={x["w"]}x{x["h"]}:r={_n(x["fps"])},format=rgba[$bg];'
        f'[$bg][IN]overlay=x={_n(dx)}:y={_n(dy)}:format=auto:shortest=1[OUT]'
    )


def _fx_scale2d(p, x):
    sx, sy = p['sx'] / 100.0, (p['sx'] if p['lock'] else p['sy']) / 100.0
    sc = f'scale=iw*{_n(sx)}:ih*{_n(sy)}:flags={p["flags"]},format=rgba'
    if not p['keep']:
        return sc
    return (
        f'[IN]{sc}[$s];color=c=black@0:s={x["w"]}x{x["h"]}:r={_n(x["fps"])},format=rgba[$bg];'
        f'[$bg][$s]overlay=x=(W-w)/2:y=(H-h)/2:format=auto:shortest=1[OUT]'
    )


def _fx_rot(p, x):
    a = f'{_n(p["a"])}*PI/180'
    g = f'rotate={a}:c=black@0:fillcolor=black@0'
    if p['expand']:
        g += f':ow=rotw({a}):oh=roth({a})'
    return g


def _fx_tile(p, x):
    """Repeat the frame nx x ny times, in space.

    NOT the `tile` filter: that one packs successive FRAMES into a mosaic, so on
    a plate it makes a contact sheet of the shot and on a still it makes one
    cell and 15 black ones.  Spatial repetition is split -> hstack -> vstack,
    which is generated here because the arity is a parameter."""
    nx, ny = int(p['nx']), int(p['ny'])
    n = nx * ny
    if n <= 1:
        return 'null'
    g = [f'[IN]scale=iw/{nx}:ih/{ny}:flags=bilinear,format=rgba,split={n}' + ''.join(f'[$c{k}]' for k in range(n))]
    rows = []
    for r in range(ny):
        ins = ''.join(f'[$c{r * nx + k}]' for k in range(nx))
        if nx == 1:
            rows.append(f'[$c{r * nx}]null[$r{r}]')
        else:
            rows.append(f'{ins}hstack=inputs={nx}[$r{r}]')
    g += rows
    if ny == 1:
        g.append('[$r0]null[OUT]')
    else:
        g.append(''.join(f'[$r{r}]' for r in range(ny)) + f'vstack=inputs={ny}[OUT]')
    return ';'.join(g)


_op(
    'move',
    'Offset',
    'Transform',
    'side',
    'Offset — slide the element in the frame. Percent of width and height, so it '
    'means the same thing at any resolution. What leaves the frame is gone; what '
    'arrives is transparent, never black.',
    '<path d="M12 3v18M3 12h18"/><path d="M12 3l-2.4 2.5M12 3l2.4 2.5M12 21l-2.4-2.5M12 21l2.4-2.5'
    'M3 12l2.5-2.4M3 12l2.5 2.4M21 12l-2.5-2.4M21 12l-2.5 2.4"/>',
    [
        f('dx', 'X', 0, -200, 200, 0.1, 'percent of frame width'),
        f('dy', 'Y', 0, -200, 200, 0.1, 'percent of frame height'),
    ],
    fn=_fx_move,
)

_op(
    'scale2d',
    'Scale',
    'Transform',
    'side',
    'Scale — resize the element about its centre. "keep canvas" holds the frame '
    'size and lets the element grow past it or shrink inside it; off, the frame '
    'itself changes size.',
    '<rect x="3.2" y="12.6" width="8.2" height="8.2"/><path d="M14 10L21 3M21 3h-5.2M21 3v5.2"/>',
    [
        f('sx', 'Size %', 100, 1, 800, 0.5),
        f('sy', 'Height %', 100, 1, 800, 0.5),
        b('lock', 'Lock aspect', True),
        b('keep', 'Keep canvas', True),
        e(
            'flags',
            'Filter',
            'lanczos',
            ['lanczos', 'bicubic', 'bilinear', 'neighbor', 'spline'],
            'neighbor keeps a sprite crisp; lanczos is right for footage',
        ),
    ],
    fn=_fx_scale2d,
)

_op(
    'rot',
    'Rotate',
    'Transform',
    'side',
    'Rotate — turn the element about its centre. "expand" grows the canvas so the corners are not clipped.',
    '<path d="M20.2 12a8.2 8.2 0 11-2.7-6.1"/><path d="M20.4 3.6v4.6h-4.6"/>',
    [f('a', 'Angle', 0, -360, 360, 0.5, 'degrees'), b('expand', 'Expand canvas', False)],
    fn=_fx_rot,
)

_op(
    'fliph',
    'Flip H',
    'Transform',
    'side',
    'Flip horizontally — mirror left-to-right. The cheapest way to get a second '
    'take out of one element without it reading as the same element.',
    '<path d="M12 2.6v18.8" stroke-dasharray="2.6 2.4"/><path d="M9.2 6.6L3.6 12l5.6 5.4z"/>'
    '<path d="M14.8 6.6L20.4 12l-5.6 5.4z"/>',
    fn=lambda p, x: 'hflip',
)

_op(
    'flipv',
    'Flip V',
    'Transform',
    'side',
    'Flip vertically — mirror top-to-bottom.',
    '<path d="M2.6 12h18.8" stroke-dasharray="2.6 2.4"/><path d="M6.6 9.2L12 3.6l5.4 5.6z"/>'
    '<path d="M6.6 14.8L12 20.4l5.4-5.6z"/>',
    fn=lambda p, x: 'vflip',
)

_op(
    'crop',
    'Crop',
    'Transform',
    'side',
    'Crop — cut a rectangle out of the frame. All four numbers are percentages of '
    'the source, so the same crop survives a change of resolution.',
    '<path d="M6.5 2.5v13a2 2 0 002 2h13"/><path d="M2.5 6.5h13a2 2 0 012 2v13"/>',
    [
        f('x', 'X %', 0, 0, 99, 0.1),
        f('y', 'Y %', 0, 0, 99, 0.1),
        f('w', 'Width %', 100, 1, 100, 0.1),
        f('h', 'Height %', 100, 1, 100, 0.1),
    ],
    fn=lambda p, x: f'crop=iw*{_n(p["w"] / 100)}:ih*{_n(p["h"] / 100)}:iw*{_n(p["x"] / 100)}:ih*{_n(p["y"] / 100)}',
)

_op(
    'padop',
    'Canvas',
    'Transform',
    'side',
    'Canvas — grow the frame around the element with transparency. Room for a '
    'glow or a streak to fall off into, which a tight crop has nowhere to put.',
    '<rect x="2.4" y="2.4" width="19.2" height="19.2" rx="1.4" stroke-dasharray="3 2.6"/>'
    '<rect x="7.4" y="7.4" width="9.2" height="9.2" rx="1"/>',
    [f('sx', 'Width %', 100, 100, 400, 1), f('sy', 'Height %', 100, 100, 400, 1)],
    fn=lambda p, x: f'format=rgba,pad=iw*{_n(p["sx"] / 100)}:ih*{_n(p["sy"] / 100)}:(ow-iw)/2:(oh-ih)/2:color=black@0',
)

_op(
    'resize',
    'Resize',
    'Transform',
    'side',
    'Resize — set the output resolution outright. "fit" letterboxes into the box '
    'with transparency; "fill" crops to it; "stretch" ignores the aspect.',
    '<rect x="3" y="5" width="18" height="14" rx="1.4"/><path d="M8 9.5h8M8 14.5h5"/>',
    [
        i('w', 'Width', 1920, 16, 8192, 2),
        i('h', 'Height', 1080, 16, 8192, 2),
        e('fit', 'Fit', 'fit', ['fit', 'fill', 'stretch']),
        e('flags', 'Filter', 'lanczos', ['lanczos', 'bicubic', 'bilinear', 'neighbor', 'spline']),
    ],
    fn=lambda p, x: (
        f'scale={int(p["w"])}:{int(p["h"])}:flags={p["flags"]},format=rgba'
        if p['fit'] == 'stretch'
        else f'scale={int(p["w"])}:{int(p["h"])}:force_original_aspect_ratio=decrease:'
        f'flags={p["flags"]},format=rgba,'
        f'pad={int(p["w"])}:{int(p["h"])}:(ow-iw)/2:(oh-ih)/2:color=black@0'
        if p['fit'] == 'fit'
        else f'scale={int(p["w"])}:{int(p["h"])}:force_original_aspect_ratio=increase:'
        f'flags={p["flags"]},format=rgba,crop={int(p["w"])}:{int(p["h"])}'
    ),
)

_op(
    'persp',
    'Corner pin',
    'Transform',
    'side',
    'Corner pin — drag the four corners independently. This is how an element is '
    'laid onto a surface that is not facing the camera: a wall, a floor, a screen.',
    '<path d="M3.4 6.2L20.6 3.2v14.4L3.4 20.8z"/><circle cx="3.4" cy="6.2" r="1.5"/>'
    '<circle cx="20.6" cy="3.2" r="1.5"/><circle cx="20.6" cy="17.6" r="1.5"/>'
    '<circle cx="3.4" cy="20.8" r="1.5"/>',
    [
        f('x0', 'TL X %', 0, -60, 160, 0.1),
        f('y0', 'TL Y %', 0, -60, 160, 0.1),
        f('x1', 'TR X %', 100, -60, 160, 0.1),
        f('y1', 'TR Y %', 0, -60, 160, 0.1),
        f('x2', 'BL X %', 0, -60, 160, 0.1),
        f('y2', 'BL Y %', 100, -60, 160, 0.1),
        f('x3', 'BR X %', 100, -60, 160, 0.1),
        f('y3', 'BR Y %', 100, -60, 160, 0.1),
        e('sense', 'Sense', 'source', ['source', 'destination']),
    ],
    fn=lambda p, x: (
        'perspective='
        + ':'.join(
            f'{ax}{n}=' + (f'W*{_n(p[f"x{n}"] / 100)}' if ax == 'x' else f'H*{_n(p[f"y{n}"] / 100)}')
            for n in range(4)
            for ax in ('x', 'y')
        )
        + f':sense={0 if p["sense"] == "source" else 1}:eval=init'
    ),
)

_op(
    'shear',
    'Shear',
    'Transform',
    'side',
    'Shear — slant the element. A lean on a fire column or a smoke plume reads as '
    'wind without having to re-simulate it.',
    '<path d="M7.6 4.5h12.9L16.4 19.5H3.5z"/>',
    [f('shx', 'X', 0, -2, 2, 0.01), f('shy', 'Y', 0, -2, 2, 0.01)],
    fn=lambda p, x: f'format=rgba,shear=shx={_n(p["shx"])}:shy={_n(p["shy"])}:fillcolor=black@0',
)

_op(
    'lens',
    'Lens distort',
    'Transform',
    'side',
    'Lens distortion — barrel (negative) or pincushion (positive). Match the '
    'element to the lens the plate was shot on, or undistort a plate before you '
    'track it.',
    '<circle cx="12" cy="12" r="8.6"/><path d="M12 3.4c-3 3.6-3 13.6 0 17.2M12 3.4c3 3.6 3 13.6 0 17.2"/>',
    [
        f('k1', 'K1', 0, -1, 1, 0.005),
        f('k2', 'K2', 0, -1, 1, 0.005),
        f('cx', 'Centre X', 0.5, 0, 1, 0.005),
        f('cy', 'Centre Y', 0.5, 0, 1, 0.005),
    ],
    fn=lambda p, x: (
        f'lenscorrection=cx={_n(p["cx"])}:cy={_n(p["cy"])}:k1={_n(p["k1"])}:k2={_n(p["k2"])}:i=bilinear:fc=black@0'
    ),
)

_op(
    'v360',
    'Reproject',
    'Transform',
    'side',
    'Reproject — read the frame as one projection and write it as another. '
    'Equirectangular to flat pulls a usable element out of a 360 plate; flat to '
    'fisheye is a cheap wide-angle.',
    '<circle cx="12" cy="12" r="8.6"/><ellipse cx="12" cy="12" rx="3.6" ry="8.6"/><path d="M3.4 12h17.2"/>',
    [
        e(
            'src',
            'From',
            'equirect',
            ['equirect', 'flat', 'fisheye', 'cube3x2', 'dfisheye', 'stereographic', 'mercator', 'ball'],
        ),
        e(
            'dst',
            'To',
            'flat',
            ['flat', 'equirect', 'fisheye', 'cube3x2', 'stereographic', 'mercator', 'ball', 'hammer'],
        ),
        f('yaw', 'Yaw', 0, -180, 180, 0.5),
        f('pitch', 'Pitch', 0, -90, 90, 0.5),
        f('roll', 'Roll', 0, -180, 180, 0.5),
        f('fov', 'Out FOV', 90, 10, 360, 1),
    ],
    fn=lambda p, x: (
        f'v360={p["src"]}:{p["dst"]}:yaw={_n(p["yaw"])}:pitch={_n(p["pitch"])}:'
        f'roll={_n(p["roll"])}:h_fov={_n(p["fov"])}:v_fov={_n(p["fov"])}:'
        f'interp=cubic'
    ),
)

_op(
    'tileop',
    'Tile',
    'Transform',
    'side',
    'Tile — repeat the element across the frame in a grid. Turns one puff into a '
    'field of them, and a seamless plate into a texture.',
    '<rect x="3" y="3" width="7.6" height="7.6"/><rect x="13.4" y="3" width="7.6" height="7.6"/>'
    '<rect x="3" y="13.4" width="7.6" height="7.6"/><rect x="13.4" y="13.4" width="7.6" height="7.6"/>',
    [i('nx', 'Across', 2, 1, 8), i('ny', 'Down', 2, 1, 8)],
    fn=_fx_tile,
)

_op(
    'scrollop',
    'Scroll',
    'Transform',
    'side',
    'Scroll — drift the frame and wrap it around. A slow scroll on a cloud or '
    'smoke plate is drifting atmosphere for free.',
    '<rect x="3.4" y="4.4" width="17.2" height="15.2" rx="1.4"/><path d="M8 15.4l4-4 4 4M8 10.6l4-4 4 4"/>',
    [
        f('h', 'Horizontal', 0, -1, 1, 0.0005, 'frame widths per frame'),
        f('v', 'Vertical', 0, -1, 1, 0.0005, 'frame heights per frame'),
    ],
    kinds='v',
    fn=lambda p, x: f'scroll=horizontal={_n(p["h"])}:vertical={_n(p["v"])}',
)
