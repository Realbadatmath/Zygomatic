# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The DISTORT / WARP section of the rail (vfx_fx.py lines 2379-2556)."""

from __future__ import annotations


from zyg_workflows.vfx_fx.registry import (
    f,
    i,
    e,
    s,
    _op,
    _n,
    _q,
)

# ── DISTORT / WARP ──────────────────────────────────────────────────────────


def _fx_turb(p, x):
    """Warp by a pair of smoothed noise fields -- heat haze, water, wobble.

    `displace` needs two MAPS, one per axis, where 128 means "no shift".  The
    maps are made here rather than asked for: a noise source blurred to the
    wanted scale, one per axis with different seeds, because the same map on
    both axes moves everything diagonally in lockstep and reads as a slide
    rather than as turbulence."""
    amp = max(1, int(round(p['amount'])))
    sig = max(0.1, float(p['scale']))
    src = f'color=c=gray:s={x["w"]}x{x["h"]}:r={_n(x["fps"])},format=gray,noise=alls={amp}:allf=t+u'
    return (
        '[IN]format=rgba[$src];'
        f'{src}:all_seed=1,gblur=sigma={_n(sig)}:steps=2[$xm];'
        f'{src}:all_seed=77,gblur=sigma={_n(sig)}:steps=2[$ym];'
        f'[$src][$xm][$ym]displace=edge={p["edge"]},format=rgba[OUT]'
    )


def _fx_ripple(p, x):
    a, l, ph = _n(p['amp']), _n(max(1.0, p['wavelength'])), _n(p['phase'])
    if p['axis'] == 'x':
        sx = f'X+{a}*sin(2*PI*Y/{l}+{ph})'
        sy = 'Y'
    else:
        sx = 'X'
        sy = f'Y+{a}*sin(2*PI*X/{l}+{ph})'
    # geq NAMES its accessors, and the alpha one is `alpha()` -- there is no
    # `a()`, so the obvious symmetry (r/g/b/a) fails on exactly one channel and
    # takes the whole filter down with it.
    fns = {'r': 'r', 'g': 'g', 'b': 'b', 'a': 'alpha'}
    return 'format=rgba,geq=' + ':'.join(f'{c}={_q(f"{fns[c]}({sx},{sy})")}' for c in ('r', 'g', 'b', 'a'))


def _fx_kaleido(p, x):
    """Four-fold mirror -- and, incidentally, the seamless-tile maker.

    Mirroring a quadrant into all four is the one construction that guarantees
    the left edge matches the right and the top matches the bottom, so a
    smoke or cloud element comes out of this tileable by definition."""
    q = {'tl': '0:0', 'tr': 'iw/2:0', 'bl': '0:ih/2', 'br': 'iw/2:ih/2'}[p['quad']]
    return (
        '[IN]format=rgba,crop=iw/2:ih/2:' + q + ',split[$q1][$q2];'
        '[$q2]hflip[$q2f];[$q1][$q2f]hstack=inputs=2,split[$t1][$t2];'
        '[$t2]vflip[$t2f];[$t1][$t2f]vstack=inputs=2,format=rgba[OUT]'
    )


_op(
    'turb',
    'Turbulence',
    'Warp',
    'side',
    'Warp the frame by a pair of smoothed noise fields — heat haze over a fire, '
    'refraction through water, a wobble on an old tape. Scale sets how big the '
    'ripples are, amount sets how far pixels travel.',
    '<path d="M3.4 8c2.6-2.6 4.6 2.6 7.2 0s4.6 2.6 7.2 0 2.4 1 2.8 1.4"/>'
    '<path d="M3.4 16c2.6-2.6 4.6 2.6 7.2 0s4.6 2.6 7.2 0 2.4 1 2.8 1.4"/>',
    [
        f('amount', 'Amount', 20, 1, 100, 0.5),
        f('scale', 'Scale', 12, 0.5, 80, 0.5),
        e('edge', 'Edge', 'smear', ['smear', 'wrap', 'blank', 'mirror']),
    ],
    kinds='v',
    fn=_fx_turb,
)

_op(
    'ripple',
    'Ripple',
    'Warp',
    'side',
    'A clean sine wave along one axis — the deterministic cousin of turbulence. '
    'Phase is animatable by hand, so this is the one to use when the wobble has '
    'to match something else exactly rather than just look organic.',
    '<path d="M3.4 12c2.4-6 4.8 6 7.2 0s4.8 6 7.2 0 2.4-1.6 2.8-2"/>',
    [
        f('amp', 'Amplitude', 10, 0, 200, 0.5),
        f('wavelength', 'Wavelength', 60, 2, 2000, 1),
        f('phase', 'Phase', 0, 0, 6.284, 0.01),
        e('axis', 'Axis', 'x', ['x', 'y']),
    ],
    fn=_fx_ripple,
)

_op(
    'pixelize',
    'Pixelate',
    'Warp',
    'side',
    'Average the frame into blocks. A censor bar, a retro look, and — at a small '
    'size with "min" mode — a fast way to see the dominant colours an element '
    'actually contributes to a shot.',
    '<rect x="3.4" y="3.4" width="5.6" height="5.6"/><rect x="9.6" y="3.4" width="5.6" height="5.6" opacity=".5"/>'
    '<rect x="3.4" y="9.6" width="5.6" height="5.6" opacity=".5"/><rect x="9.6" y="9.6" width="5.6" height="5.6"/>'
    '<rect x="15.8" y="15.8" width="5.6" height="5.6" opacity=".5"/>',
    [
        i('w', 'Block width', 16, 1, 1024),
        i('h', 'Block height', 16, 1, 1024),
        e('mode', 'Mode', 'avg', ['avg', 'min', 'max']),
    ],
    fn=lambda p, x: f'pixelize=w={int(p["w"])}:h={int(p["h"])}:mode={p["mode"]}',
)

_op(
    'kaleido',
    'Mirror quad',
    'Warp',
    'side',
    'Mirror one quadrant into all four. A kaleidoscope, and — because mirroring '
    'guarantees the left edge matches the right — the one-click way to make a '
    'smoke or cloud element tile seamlessly.',
    '<path d="M12 3.4v17.2M3.4 12h17.2"/><path d="M12 12L4.6 4.6M12 12l7.4-7.4M12 12l-7.4 7.4M12 12l7.4 7.4" opacity=".5"/>',
    [e('quad', 'Source quadrant', 'tl', ['tl', 'tr', 'bl', 'br'])],
    fn=_fx_kaleido,
)

_op(
    'swaprect',
    'Swap rect',
    'Warp',
    'side',
    'Swap two rectangles of the frame with each other. A glitch, a patch, and the '
    'quickest way to cover something you do not want in a plate with something '
    'that is already the right texture.',
    '<rect x="3.4" y="3.4" width="7.4" height="7.4"/><rect x="13.2" y="13.2" width="7.4" height="7.4"/>'
    '<path d="M11.4 7.1h6.2M12.4 5.4l-1.6 1.7 1.6 1.7" opacity=".7"/>',
    [
        f('w', 'Width %', 20, 1, 100, 0.5),
        f('h', 'Height %', 20, 1, 100, 0.5),
        f('x1', 'A X %', 5, 0, 100, 0.5),
        f('y1', 'A Y %', 5, 0, 100, 0.5),
        f('x2', 'B X %', 60, 0, 100, 0.5),
        f('y2', 'B Y %', 60, 0, 100, 0.5),
    ],
    fn=lambda p, x: (
        f'swaprect=w=w*{_n(p["w"] / 100)}:h=h*{_n(p["h"] / 100)}:'
        f'x1=w*{_n(p["x1"] / 100)}:y1=h*{_n(p["y1"] / 100)}:'
        f'x2=w*{_n(p["x2"] / 100)}:y2=h*{_n(p["y2"] / 100)}'
    ),
)

_op(
    'polar',
    'Polar warp',
    'Warp',
    'side',
    'Bend the frame around a circle, or unroll a circular one flat. A straight '
    'line of fire becomes a ring of it; a fisheye plate becomes something you can '
    'work on with rectangular tools.',
    '<circle cx="12" cy="12" r="8.4"/><path d="M12 3.6v8.4h8.4"/><path d="M6 18l6-6" opacity=".5"/>',
    [e('dir', 'Direction', 'to_polar', ['to_polar', 'from_polar']), f('fov', 'Field', 180, 10, 360, 1)],
    fn=lambda p, x: (
        f'v360=flat:fisheye:h_fov={_n(p["fov"])}:v_fov={_n(p["fov"])}:interp=cubic'
        if p['dir'] == 'to_polar'
        else f'v360=fisheye:flat:ih_fov={_n(p["fov"])}:iv_fov={_n(p["fov"])}:h_fov=90:v_fov=90:interp=cubic'
    ),
)

_op(
    'datamosh',
    'Frame shuffle',
    'Warp',
    'side',
    'Reorder frames by an explicit map — 0 1 2 3 plays straight, 0 0 2 2 doubles '
    'every other one, and a scrambled map is the honest, deterministic version of '
    'a datamosh. The map repeats over the whole clip.',
    '<rect x="3.4" y="8" width="4.4" height="8"/><rect x="9.8" y="8" width="4.4" height="8" opacity=".55"/>'
    '<rect x="16.2" y="8" width="4.4" height="8" opacity=".3"/><path d="M7.8 6.4l6.4 0M14.2 17.6h-6.4" opacity=".6"/>',
    [s('map', 'Map', '0 1 2 3', 'frame indices, space separated', pat=r'[-0-9 ]{0,200}')],
    kinds='v',
    fn=lambda p, x: (lambda mm: f'shuffleframes={_q(mm)}')(' '.join(str(p['map']).split()) or '0'),
)
