# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later
"""sfx_fx.restoration — RESTORATION blocks."""

from zyg_workflows.sfx_fx.helpers import _pick


# ═══════════════════════════════════════════════════════════════════════════════
#  RESTORATION
# ═══════════════════════════════════════════════════════════════════════════════
def _b_denoise(p, ctx):
    return [
        f'afftdn=nr={float(p["reduction"]):.2f}:nf={float(p["floor"]):.1f}'
        f':nt={_pick(p, "noise_type", ["white", "vinyl", "shellac", "custom"])}'
        f':tn={"true" if p["track"] else "false"}'
        f':om={_pick(p, "out", ["input", "output", "noise"])}'
        f':ad={float(p["adaptivity"]) / 100.0:.4f}'
        f':bm={float(p["band_mult"]):.3f}'
        f':gs={int(p["smooth"])}'
    ]


_WAVELETS = ['sym2', 'sym4', 'rbior68', 'deb10', 'sym10', 'coif5', 'bl3']


def _b_denoise_wav(p, ctx):
    return [
        f'afwtdn=sigma={float(p["sigma"]) / 1000.0:.6f}'
        f':levels={int(p["levels"])}'
        f':wavet={_pick(p, "wavelet", _WAVELETS)}'
        f':percent={float(p["percent"]):.2f}'
        f':softness={float(p["softness"]):.3f}'
        f':adaptive={"true" if p["adaptive"] else "false"}'
    ]


def _b_denoise_nlm(p, ctx):
    return [
        f'anlmdn=s={max(1e-5, float(p["strength"]) / 10000.0):.8f}'
        f':p={float(p["patch_ms"]) / 1000.0:.6f}'
        f':r={float(p["research_ms"]) / 1000.0:.6f}'
        f':o={_pick(p, "out", ["i", "o", "n"])}'
        f':m={float(p["smooth"]):.2f}'
    ]


def _b_declick(p, ctx):
    return [
        f'adeclick=w={float(p["window"]):.1f}:o={float(p["overlap"]):.1f}'
        f':a={float(p["order"]):.1f}:t={float(p["threshold"]):.2f}'
        f':b={float(p["burst"]):.2f}'
        f':m={_pick(p, "method", ["add", "save"])}'
    ]


def _b_declip(p, ctx):
    return [
        f'adeclip=w={float(p["window"]):.1f}:o={float(p["overlap"]):.1f}'
        f':a={float(p["order"]):.1f}:t={float(p["threshold"]):.2f}'
        f':n={int(p["hsize"])}'
        f':m={_pick(p, "method", ["add", "save"])}'
    ]


def _b_hum(p, ctx):
    base = float(_pick(p, 'mains', [50, 60]))
    f = []
    for i in range(1, int(p['harmonics']) + 1):
        fq = base * i
        if fq > 18000:
            break
        f.append(f'bandreject=f={fq:.1f}:t=q:w={max(0.05, float(p["q"])):.3f}')
    return f


def _b_dialogue(p, ctx):
    return [
        f'dialoguenhance=original={float(p["original"]) / 100.0:.4f}'
        f':enhance={float(p["enhance"]):.3f}:voice={float(p["voice"]):.2f}'
    ]


def _b_denorm(p, ctx):
    return [f'adenorm=level={float(p["level"]):.1f}:type={_pick(p, "type", ["dc", "ac", "square", "pulse"])}']
