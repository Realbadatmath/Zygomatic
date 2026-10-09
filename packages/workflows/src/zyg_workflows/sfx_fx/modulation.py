# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later
"""sfx_fx.modulation — MODULATION blocks."""

from zyg_workflows.sfx_fx.helpers import _db, _pick


# ═══════════════════════════════════════════════════════════════════════════════
#  MODULATION
# ═══════════════════════════════════════════════════════════════════════════════
def _b_chorus(p, ctx):
    n = int(p['voices'])
    d0 = float(p['delay_ms'])
    delays, decays, speeds, depths = [], [], [], []
    for i in range(n):
        delays.append(f'{d0 + i * float(p["spread_ms"]):.2f}')
        decays.append(f'{max(0.01, min(0.9, float(p["decay"]) / 100.0)):.3f}')
        speeds.append(f'{max(0.01, float(p["speed"]) * (1.0 + 0.23 * i)):.3f}')
        depths.append(f'{float(p["depth"]):.2f}')
    return [
        f'chorus={float(p["in_gain"]) / 100.0:.3f}:{float(p["out_gain"]) / 100.0:.3f}'
        f':{"|".join(delays)}:{"|".join(decays)}:{"|".join(speeds)}:{"|".join(depths)}'
    ]


def _b_flanger(p, ctx):
    return [
        f'flanger=delay={float(p["delay_ms"]):.3f}:depth={float(p["depth_ms"]):.3f}'
        f':regen={float(p["regen"]):.2f}:width={float(p["width"]):.2f}'
        f':speed={float(p["speed"]):.3f}'
        f':shape={_pick(p, "shape", ["sinusoidal", "triangular"])}'
        f':phase={float(p["phase"]):.2f}'
        f':interp={_pick(p, "interp", ["linear", "quadratic"])}'
    ]


def _b_phaser(p, ctx):
    return [
        f'aphaser=in_gain={float(p["in_gain"]) / 100.0:.3f}'
        f':out_gain={float(p["out_gain"]) / 100.0:.3f}'
        f':delay={float(p["delay_ms"]):.3f}:decay={float(p["decay"]) / 100.0:.3f}'
        f':speed={float(p["speed"]):.3f}'
        f':type={_pick(p, "shape", ["triangular", "sinusoidal"])}'
    ]


def _b_tremolo(p, ctx):
    return [f'tremolo=f={float(p["rate"]):.3f}:d={float(p["depth"]) / 100.0:.4f}']


def _b_vibrato(p, ctx):
    return [f'vibrato=f={float(p["rate"]):.3f}:d={float(p["depth"]) / 100.0:.4f}']


def _b_ringmod(p, ctx):
    """Ring modulation as a per-channel expression: every partial gets sum and
    difference copies against the carrier, which is what makes it metallic."""
    fq = float(p['freq'])
    mix = float(p['mix']) / 100.0
    st = float(p['stereo_hz'])
    shape = _pick(p, 'shape', ['sin', 'squ', 'saw'])

    def car(f):
        if shape == 'sin':
            return f'sin(2*PI*{f:.4f}*t)'
        if shape == 'squ':
            return f'(2*(sin(2*PI*{f:.4f}*t)>0)-1)'
        return f'(2*(mod({f:.4f}*t\\,1))-1)'

    l = f'val(0)*({1 - mix:.4f}+{mix:.4f}*{car(fq)})'
    r = f'val(1)*({1 - mix:.4f}+{mix:.4f}*{car(fq + st)})'
    return [f'aeval=exprs={l}|{r}:c=same']


def _b_dynsmooth(p, ctx):
    return [f'adynamicsmooth=sensitivity={float(p["sensitivity"]):.4f}:basefreq={float(p["basefreq"]):.1f}']


def _b_spectral(p, ctx):
    """A spectral gate/expander through afftfilt: bins under the threshold are
    pulled down by the ratio, bins over it pass. This is the one that removes a
    noise bed without dulling the transients the way a broadband gate does."""
    th = _db(p['threshold'])
    amt = max(0.0, min(1.0, float(p['amount']) / 100.0))
    mode = _pick(p, 'mode', ['gate', 'boost'])
    if mode == 'gate':
        expr = f'{1 - amt:.4f}+{amt:.4f}*(1-exp(-pow(hypot(re\\,im)/{th:.8f}\\,2)))'
    else:
        expr = f'{1 - amt:.4f}+{amt:.4f}*(1+exp(-pow(hypot(re\\,im)/{th:.8f}\\,2)))'
    return [
        f'afftfilt=real=re*({expr}):imag=im*({expr})'
        f':win_size={int(p["win_size"])}'
        f':overlap={float(p["overlap"]) / 100.0:.3f}'
        f':win_func={_pick(p, "window", ["hann", "hamming", "blackman", "bartlett", "welch", "flattop", "nuttall"])}'
    ]
