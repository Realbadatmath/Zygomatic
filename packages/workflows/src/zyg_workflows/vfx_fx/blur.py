# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The BLUR / DETAIL section of the rail (vfx_fx.py lines 1437-1854)."""

from __future__ import annotations


from zyg_workflows.vfx_fx.registry import (
    f,
    i,
    b,
    e,
    s,
    _op,
    _n,
    _q,
)

# ── BLUR / DETAIL ───────────────────────────────────────────────────────────
# Two jobs that look opposite and are the same job: making an element match the
# plate's own softness and grain.  A razor-sharp element on a soft, grainy plate
# is the single most common reason a composite reads as fake, and no amount of
# grading fixes it.

_op(
    'gblur',
    'Gaussian blur',
    'Detail',
    'side',
    'Gaussian blur — the honest, symmetrical one. Steps trades speed for how '
    'close it gets to a true gaussian; at big radii one step shows its box.',
    '<circle cx="12" cy="12" r="4.4"/><circle cx="12" cy="12" r="7" opacity=".5"/>'
    '<circle cx="12" cy="12" r="9.4" opacity=".25"/>',
    [
        f('sigma', 'Radius', 4, 0, 100, 0.1),
        i('steps', 'Steps', 1, 1, 6),
        e('planes', 'Planes', 'rgb', ['rgb', 'rgba', 'r', 'g', 'b', 'a']),
    ],
    fn=lambda p, x: (
        f'format=rgba,gblur=sigma={_n(p["sigma"])}:steps={int(p["steps"])}:planes='
        + {'rgb': '7', 'rgba': '15', 'r': '1', 'g': '2', 'b': '4', 'a': '8'}[p['planes']]
    ),
)

_op(
    'boxblur',
    'Box blur',
    'Detail',
    'side',
    'Box blur — separate radii for luma and chroma. Blurring chroma alone by a '
    'few pixels kills the colour noise in a dark plate without touching a scrap '
    'of the detail, which no gaussian on the full picture can do.',
    '<rect x="8.4" y="8.4" width="7.2" height="7.2"/><rect x="5.6" y="5.6" width="12.8" height="12.8" opacity=".5"/>'
    '<rect x="3" y="3" width="18" height="18" opacity=".25"/>',
    [
        i('lr', 'Luma radius', 2, 0, 60),
        i('lp', 'Luma passes', 1, 0, 6),
        i('cr', 'Chroma radius', 2, 0, 60),
        i('cp', 'Chroma passes', 1, 0, 6),
    ],
    fn=lambda p, x: f'boxblur=lr={int(p["lr"])}:lp={int(p["lp"])}:cr={int(p["cr"])}:cp={int(p["cp"])}',
)

_op(
    'dblur',
    'Directional blur',
    'Detail',
    'side',
    'Blur along one angle only — motion blur that you aim. Match it to the '
    'direction the element is travelling and a sprite stops reading as a still '
    'that someone slid across the frame.',
    '<path d="M3.4 12h17.2"/><path d="M15.6 7.2L20.6 12l-5 4.8"/><path d="M3.4 8.4h9M3.4 15.6h9" opacity=".45"/>',
    [f('angle', 'Angle', 45, 0, 360, 0.5), f('radius', 'Radius', 8, 0, 100, 0.1)],
    fn=lambda p, x: f'dblur=angle={_n(p["angle"])}:radius={_n(p["radius"])}',
)

_op(
    'avgblur',
    'Average blur',
    'Detail',
    'side',
    'Average blur with independent horizontal and vertical size. Set one of them '
    'to zero and you have a cheap streak, which is the base of every anamorphic '
    'flare.',
    '<rect x="3.4" y="9.4" width="17.2" height="5.2" rx="1"/><path d="M3.4 12h17.2" opacity=".5"/>',
    [i('sizeX', 'Horizontal', 4, 0, 100), i('sizeY', 'Vertical', 4, 0, 100)],
    fn=lambda p, x: f'avgblur=sizeX={int(p["sizeX"])}:sizeY={int(p["sizeY"])}',
)

_op(
    'smartblur',
    'Smart blur',
    'Detail',
    'side',
    'Blur the flat areas and leave the edges alone. Cleans up banding and noise '
    'in a sky or a smoke gradient without turning the whole shot to mush.',
    '<path d="M3.4 16.6c4-8 6.6 4 8.6-4 2-8 4.6 6 8.6 2"/><path d="M3.4 20.6h17.2" opacity=".4"/>',
    [f('lr', 'Radius', 3, 0.1, 5, 0.05), f('ls', 'Strength', 1, -1, 1, 0.01), i('lt', 'Threshold', 0, -30, 30)],
    fn=lambda p, x: f'smartblur=lr={_n(p["lr"])}:ls={_n(p["ls"])}:lt={int(p["lt"])}',
)

_op(
    'bilateral',
    'Bilateral',
    'Detail',
    'side',
    'Edge-preserving smooth — the "skin" filter. Sigma S is how far it reaches, '
    'sigma R is how different a pixel may be before it stops being averaged in.',
    '<path d="M3.4 18.6c3.4 0 3.4-13.2 6.8-13.2s3.4 13.2 6.8 13.2 3.6-6.6 3.6-6.6"/>',
    [
        f('sigmaS', 'Spatial', 8, 0, 512, 0.5),
        f('sigmaR', 'Range', 0.1, 0, 1, 0.002),
        e('planes', 'Planes', 'rgb', ['rgb', 'rgba']),
    ],
    fn=lambda p, x: (
        f'bilateral=sigmaS={_n(p["sigmaS"])}:sigmaR={_n(p["sigmaR"])}:planes={7 if p["planes"] == "rgb" else 15}'
    ),
)

_op(
    'unsharp',
    'Unsharp mask',
    'Detail',
    'side',
    'Unsharp mask — sharpen by subtracting a blur. A NEGATIVE amount blurs '
    "instead, which is the correct way to soften an element down to a plate's "
    'level of detail rather than blurring it out of existence.',
    '<path d="M12 3.4v17.2M3.4 12h17.2"/><circle cx="12" cy="12" r="4.2"/>'
    '<path d="M12 7.8v8.4M7.8 12h8.4" opacity=".4"/>',
    [
        i('lx', 'Luma X', 5, 3, 23, 2),
        i('ly', 'Luma Y', 5, 3, 23, 2),
        f('la', 'Luma amount', 1, -2, 5, 0.05),
        i('cx', 'Chroma X', 5, 3, 23, 2),
        i('cy', 'Chroma Y', 5, 3, 23, 2),
        f('ca', 'Chroma amount', 0, -2, 5, 0.05),
    ],
    fn=lambda p, x: (
        f'unsharp=lx={int(p["lx"]) | 1}:ly={int(p["ly"]) | 1}:la={_n(p["la"])}:'
        f'cx={int(p["cx"]) | 1}:cy={int(p["cy"]) | 1}:ca={_n(p["ca"])}'
    ),
)

_op(
    'cas',
    'Adaptive sharpen',
    'Detail',
    'side',
    'Contrast-adaptive sharpening — sharpens the soft parts harder than the parts '
    'that are already crisp, so it does not ring on an edge that needed nothing.',
    '<path d="M4 19.4l5.4-11 3.6 6.6 2.6-3.8 4.4 8.2z"/><path d="M4 19.4h16"/>',
    [f('strength', 'Strength', 0.3, 0, 1, 0.01), e('planes', 'Planes', 'rgb', ['rgb', 'rgba'])],
    fn=lambda p, x: f'cas=strength={_n(p["strength"])}:planes={7 if p["planes"] == "rgb" else 15}',
)

_op(
    'median',
    'Median',
    'Detail',
    'side',
    'Median filter — takes out salt-and-pepper speckle and leaves edges where '
    'they are. The cure for a dusty scan or a sensor with dead pixels.',
    '<circle cx="6.4" cy="7.4" r="1.4"/><circle cx="17.6" cy="6.6" r="1.4"/>'
    '<circle cx="9.4" cy="17.4" r="1.4"/><rect x="3.4" y="3.4" width="17.2" height="17.2" rx="1.4"/>',
    [i('radius', 'Radius', 1, 1, 127), f('percentile', 'Percentile', 0.5, 0, 1, 0.01)],
    fn=lambda p, x: f'median=radius={int(p["radius"])}:percentile={_n(p["percentile"])}',
)

_op(
    'hqdn3d',
    'Denoise (temporal)',
    'Detail',
    'side',
    'High-quality 3D denoise — spatial and TEMPORAL together, so it uses the '
    'neighbouring frames. The temporal half is the strong one and also the one '
    'that will smear a fast-moving element into a ghost, so raise it last.',
    '<path d="M4 12h4l2.4-5 3.2 10 2.4-5H20"/><path d="M4 18.6h16" opacity=".4"/>',
    [
        f('luma_spatial', 'Luma spatial', 4, 0, 50, 0.1),
        f('chroma_spatial', 'Chroma spatial', 3, 0, 50, 0.1),
        f('luma_tmp', 'Luma temporal', 6, 0, 50, 0.1),
        f('chroma_tmp', 'Chroma temporal', 4.5, 0, 50, 0.1),
    ],
    kinds='v',
    fn=lambda p, x: (
        f'hqdn3d={_n(p["luma_spatial"])}:{_n(p["chroma_spatial"])}:{_n(p["luma_tmp"])}:{_n(p["chroma_tmp"])}'
    ),
)

_op(
    'nlmeans',
    'Denoise (NLM)',
    'Detail',
    'side',
    'Non-local means — the slow, good one. It finds patches that look alike '
    'anywhere in the search window and averages those, so texture survives where '
    'a blur would have eaten it. Expensive; worth it on a hero frame.',
    '<rect x="3.4" y="3.4" width="6" height="6"/><rect x="14.6" y="9" width="6" height="6" stroke-dasharray="2 1.8"/>'
    '<path d="M9.4 6.4h5.2M12 6.4v5.6" opacity=".5"/>',
    [f('s', 'Strength', 1, 1, 30, 0.1), i('p', 'Patch', 7, 0, 99, 2), i('r', 'Research', 15, 0, 99, 2)],
    fn=lambda p, x: f'nlmeans=s={_n(p["s"])}:p={int(p["p"]) | 1}:r={int(p["r"]) | 1}',
)

_op(
    'atadenoise',
    'Denoise (adaptive)',
    'Detail',
    'side',
    'Adaptive temporal averaging — averages a pixel with itself across frames, '
    'but only while it stays within a threshold, so movement is left alone. '
    'Cheap, and safe on a locked-off plate.',
    '<path d="M4 8h16M4 12h16M4 16h16" opacity=".45"/><path d="M8 4v16M16 4v16"/>',
    [f('0a', 'Thr A', 0.02, 0, 0.3, 0.001), f('0b', 'Thr B', 0.04, 0, 5, 0.01), i('s', 'Frames', 9, 5, 129, 2)],
    kinds='v',
    fn=lambda p, x: f'atadenoise=0a={_n(p["0a"])}:0b={_n(p["0b"])}:s={int(p["s"]) | 1}',
)

_op(
    'fftdnoiz',
    'Denoise (FFT)',
    'Detail',
    'side',
    'Denoise in the frequency domain. Good at the fine, even grain a film scan '
    'carries, because that grain is a band rather than a set of outliers.',
    '<path d="M3.4 20.6V13M7 20.6V8M10.6 20.6V15M14.2 20.6V5M17.8 20.6V11M21 20.6v-6"/>',
    [
        f('sigma', 'Sigma', 1, 0, 30, 0.05),
        f('amount', 'Amount', 1, 0.01, 1, 0.01),
        e('block', 'Block', '32', ['8', '16', '32', '64', '128']),
        f('overlap', 'Overlap', 0.5, 0.2, 0.8, 0.01),
    ],
    fn=lambda p, x: (
        f'fftdnoiz=sigma={_n(p["sigma"])}:amount={_n(p["amount"])}:block={int(p["block"])}:overlap={_n(p["overlap"])}'
    ),
)

_op(
    'owdenoise',
    'Denoise (wavelet)',
    'Detail',
    'side',
    'Overcomplete wavelet denoise — the gentlest of the family on texture, and '
    'the slowest of them by a distance. Separate depth and thresholds for luma '
    'and chroma.',
    '<path d="M3.4 12c2-6 4 6 6 0s4 6 6 0 3 4 5 2"/>',
    [
        i('depth', 'Depth', 8, 8, 16),
        f('luma_strength', 'Luma', 1, 0, 1000, 0.5),
        f('chroma_strength', 'Chroma', 1, 0, 1000, 0.5),
    ],
    fn=lambda p, x: f'owdenoise=depth={int(p["depth"])}:ls={_n(p["luma_strength"])}:cs={_n(p["chroma_strength"])}',
)

_op(
    'deband',
    'Deband',
    'Detail',
    'side',
    'Break up the stair-stepped bands an 8-bit gradient shows — a smoke plume '
    'and a sky are where you will see them. It works by dithering, so it is a '
    'trade of banding for a little noise, which is the right trade.',
    '<rect x="3.4" y="4.4" width="17.2" height="4" opacity=".85"/>'
    '<rect x="3.4" y="9.4" width="17.2" height="4" opacity=".6"/>'
    '<rect x="3.4" y="14.4" width="17.2" height="4" opacity=".35"/>',
    [
        f('1thr', 'Y threshold', 0.02, 0.00003, 0.5, 0.001),
        f('2thr', 'U threshold', 0.02, 0.00003, 0.5, 0.001),
        f('3thr', 'V threshold', 0.02, 0.00003, 0.5, 0.001),
        i('range', 'Range', 16, 1, 64),
        b('blur', 'Blur', True),
        b('coupling', 'Coupling', False),
    ],
    fn=lambda p, x: (
        f'deband=1thr={_n(p["1thr"])}:2thr={_n(p["2thr"])}:3thr={_n(p["3thr"])}:'
        f'range={int(p["range"])}:blur={1 if p["blur"] else 0}:'
        f'coupling={1 if p["coupling"] else 0}'
    ),
)

_op(
    'gradfun',
    'Debanding (ramp)',
    'Detail',
    'side',
    'The other debander — it fits a gradient across a radius and dithers to it. '
    'Better than deband on a long, slow ramp; worse on fine detail, which it will '
    'flatten if the radius is too big.',
    '<path d="M3.4 20.6L20.6 3.4"/><path d="M3.4 20.6h17.2V3.4z" fill="currentColor" stroke="none" opacity=".18"/>',
    [f('strength', 'Strength', 1.2, 0.51, 64, 0.05), i('radius', 'Radius', 16, 4, 32, 1)],
    fn=lambda p, x: f'gradfun=strength={_n(p["strength"])}:radius={int(p["radius"])}',
)

_op(
    'deblock',
    'Deblock',
    'Detail',
    'side',
    'Take the 8x8 blocking out of a compressed source. Every plate that came off '
    'a streaming derivative has this, and it is invisible until you raise the '
    'contrast or key it — then every block edge becomes a matte edge.',
    '<rect x="3.4" y="3.4" width="8.2" height="8.2"/><rect x="12.4" y="3.4" width="8.2" height="8.2"/>'
    '<rect x="3.4" y="12.4" width="8.2" height="8.2"/><rect x="12.4" y="12.4" width="8.2" height="8.2"/>',
    [
        e('filter', 'Filter', 'strong', ['weak', 'strong']),
        i('block', 'Block', 8, 4, 512, 4),
        f('alpha', 'Alpha', 0.098, 0, 1, 0.002),
        f('beta', 'Beta', 0.05, 0, 1, 0.002),
    ],
    fn=lambda p, x: f'deblock=filter={p["filter"]}:block={int(p["block"])}:alpha={_n(p["alpha"])}:beta={_n(p["beta"])}',
)

_op(
    'removegrain',
    'Spatial cleanup',
    'Detail',
    'side',
    'RemoveGrain — a family of small spatial modes, each a different rule for '
    'clipping a pixel to its neighbours. Mode 1 is the mild one; the higher modes '
    'are aggressive and worth trying by eye rather than by number.',
    '<circle cx="7" cy="7.4" r="1.2"/><circle cx="16.4" cy="8.6" r="1.2"/>'
    '<circle cx="11" cy="16" r="1.2"/><circle cx="12" cy="12" r="8.6" stroke-dasharray="2.6 2.4"/>',
    [i('m0', 'Red mode', 1, 0, 24), i('m1', 'Green mode', 1, 0, 24), i('m2', 'Blue mode', 1, 0, 24)],
    fn=lambda p, x: f'removegrain=m0={int(p["m0"])}:m1={int(p["m1"])}:m2={int(p["m2"])}:m3=0',
)

_op(
    'noise',
    'Grain',
    'Detail',
    'side',
    'Add grain. The most under-used match in the toolkit: a clean CG element on a '
    'grainy plate is spotted instantly, and a few points of temporal noise fixes '
    'it. Temporal grain moves per frame; without it the grain is a fixed pattern '
    'welded to the element.',
    '<circle cx="6.4" cy="7" r="1"/><circle cx="12.4" cy="5.6" r="1"/><circle cx="17.6" cy="8.4" r="1"/>'
    '<circle cx="8" cy="13" r="1"/><circle cx="15" cy="12.4" r="1"/><circle cx="6" cy="18" r="1"/>'
    '<circle cx="12" cy="18.4" r="1"/><circle cx="18.4" cy="16.6" r="1"/>',
    [i('alls', 'Strength', 12, 0, 100), b('t', 'Temporal', True), b('u', 'Uniform', False), b('a', 'Averaged', False)],
    fn=lambda p, x: (
        f'noise=alls={int(p["alls"])}:allf='
        + (''.join(k for k, on in (('t', p['t']), ('u', p['u']), ('a', p['a'])) if on) or 'p')
    ),
)

_op(
    'conv',
    'Convolution',
    'Detail',
    'side',
    'A raw 3x3 (or 5x5) kernel, applied per channel. Every sharpen, emboss, edge '
    'and blur in the list above is one of these with the numbers already filled '
    'in — this is the one for when none of them is quite the thing.',
    '<rect x="3.4" y="3.4" width="17.2" height="17.2" rx="1.2"/><path d="M9.2 3.4v17.2M14.8 3.4v17.2M3.4 9.2h17.2M3.4 14.8h17.2"/>',
    [
        s('m', 'Matrix', '0 -1 0 -1 5 -1 0 -1 0', '9 or 25 numbers, space separated', pat=r'[-0-9. ]{0,300}'),
        f('rdiv', 'Divisor', 0, 0, 64, 0.1, '0 = sum of the matrix'),
        f('bias', 'Bias', 0, -255, 255, 1),
    ],
    fn=lambda p, x: (
        lambda mm: (
            f'convolution=0m={_q(mm)}:1m={_q(mm)}:2m={_q(mm)}:3m={_q("0 0 0 0 1 0 0 0 0")}'
            f':0rdiv={_n(p["rdiv"])}:1rdiv={_n(p["rdiv"])}:2rdiv={_n(p["rdiv"])}'
            f':0bias={_n(p["bias"])}:1bias={_n(p["bias"])}:2bias={_n(p["bias"])}'
        )
    )(' '.join(str(p['m']).split()) or '0 0 0 0 1 0 0 0 0'),
)

_op(
    'edge',
    'Edge detect',
    'Detail',
    'side',
    'Canny edge detection. As a look it is a wireframe; as a tool it is how you '
    'find where the detail actually is, which is what you want before you decide '
    'how hard to sharpen.',
    '<path d="M4.4 19.6l5-11.2 4.4 6.6 2.6-4 3.2 8.6z" stroke-dasharray="2.6 2"/>',
    [
        f('low', 'Low', 0.078, 0, 1, 0.002),
        f('high', 'High', 0.196, 0, 1, 0.002),
        e('mode', 'Mode', 'wires', ['wires', 'colormix', 'canny']),
    ],
    fn=lambda p, x: f'edgedetect=low={_n(p["low"])}:high={_n(p["high"])}:mode={p["mode"]}',
)

_op(
    'sobel',
    'Sobel',
    'Detail',
    'side',
    'Sobel gradient — the direction and steepness of every edge, as a picture. '
    'Scale it up and it is a relief; it is also the input a displacement map '
    'wants if you are warping one element by the shape of another.',
    '<path d="M3.4 20.6L12 3.4l8.6 17.2z"/><path d="M7 16h10" opacity=".5"/>',
    [f('scale', 'Scale', 1, 0, 65535, 0.05), f('delta', 'Delta', 0, -65535, 65535, 1)],
    fn=lambda p, x: f'sobel=scale={_n(p["scale"])}:delta={_n(p["delta"])}',
)

_op(
    'emboss',
    'Emboss',
    'Detail',
    'side',
    'Emboss — a directional convolution that turns the picture into a relief lit '
    'from one corner. Over a smoke element it reads as etched glass.',
    '<circle cx="12" cy="12" r="8.6"/><path d="M8.4 15.6l7.2-7.2"/><path d="M8.4 12l3.6-3.6" opacity=".5"/>',
    [f('depth', 'Depth', 1, 0, 4, 0.05)],
    fn=lambda p, x: (
        lambda d: (
            f'convolution=0m={_q(f"{-2 * d} {-1 * d} 0 {-1 * d} 1 {1 * d} 0 {1 * d} {2 * d}")}'
            f':1m={_q(f"{-2 * d} {-1 * d} 0 {-1 * d} 1 {1 * d} 0 {1 * d} {2 * d}")}'
            f':2m={_q(f"{-2 * d} {-1 * d} 0 {-1 * d} 1 {1 * d} 0 {1 * d} {2 * d}")}'
            f':3m={_q("0 0 0 0 1 0 0 0 0")}:0rdiv=1:1rdiv=1:2rdiv=1'
        )
    )(round(float(p['depth']), 3)),
)

_op(
    'fftfilt',
    'Frequency filter',
    'Detail',
    'side',
    'Shape the picture in the frequency domain — pull the low frequencies down '
    'for a high-pass, or the highs for a soft-focus that keeps its edges. This is '
    'the one that removes a repeating pattern a spatial filter cannot see.',
    '<path d="M3.4 16.4c2.4 0 2.4-8.8 4.8-8.8s2.4 8.8 4.8 8.8 2.4-8.8 4.8-8.8 2.4 8.8 3.4 8.8"/>',
    [
        s('dc_Y', 'DC luma', '0', pat=r'[0-9]{0,4}'),
        s('weight_Y', 'Luma weight', '1', 'an expression in X and Y', pat=r'[-+*/^()0-9a-zA-Z_. ]{0,160}'),
        s('weight_U', 'Chroma weight', '1', pat=r'[-+*/^()0-9a-zA-Z_. ]{0,160}'),
    ],
    fn=lambda p, x: (
        f'fftfilt=dc_Y={int(p["dc_Y"] or 0)}:weight_Y={_q(p["weight_Y"] or "1")}:weight_U={_q(p["weight_U"] or "1")}'
    ),
)
