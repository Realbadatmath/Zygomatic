#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""
Generate cinematic .cube LUT files for the Zygomatic video pipeline.

Each LUT is a 33x33x33 3D lookup table that applies a creative color grade.
Run this script once; the .cube files are committed to assets/luts/ and
loaded at pipeline runtime by the ffmpeg lut3d filter.

Usage:
    python3 scripts/generate_luts.py
"""

import math
import os

# ── Output directory ───────────────────────────────────────────────────────────
LUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'assets', 'luts')
os.makedirs(LUT_DIR, exist_ok=True)

N = 33  # 33×33×33 = 35 937 entries — industry standard minimum


# ── Math helpers ───────────────────────────────────────────────────────────────


def luma(r, g, b):
    """BT.709 luma weight."""
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def s_curve(x, strength=0.08):
    """Gentle sine S-curve — lifts shadow toe, rolls off highlights."""
    return x + strength * math.sin(math.pi * x)


def sat_adjust(r, g, b, amount=0.85):
    """Scale saturation. amount < 1 = desaturate; > 1 = boost."""
    l = luma(r, g, b)
    return l + amount * (r - l), l + amount * (g - l), l + amount * (b - l)


def clamp(v):
    return max(0.0, min(1.0, v))


# ── LUT transforms ─────────────────────────────────────────────────────────────


def cinematic(r, g, b):
    """Warm, slightly desaturated film-look with a gentle S-curve and lifted blacks."""
    r, g, b = s_curve(r, 0.06), s_curve(g, 0.06), s_curve(b, 0.06)
    l = luma(r, g, b)
    warm = 0.04 * max(0.0, 1.0 - abs(l - 0.5) * 2.0)
    r = r + warm * 0.8
    b = b - warm * 0.5
    r, g, b = sat_adjust(r, g, b, 0.88)
    r = r * 0.96 + 0.02
    g = g * 0.96 + 0.02
    b = b * 0.96 + 0.02
    return r, g, b


def orange_teal(r, g, b):
    """Hollywood split-tone: teal shadows, orange highlights."""
    l = luma(r, g, b)
    shadow_w = max(0.0, 1.0 - l / 0.35) ** 1.5
    highlight_w = max(0.0, (l - 0.45) / 0.55) ** 1.5
    r = r - shadow_w * 0.04 + highlight_w * 0.05
    g = g - shadow_w * 0.01 + highlight_w * 0.02
    b = b + shadow_w * 0.06 - highlight_w * 0.06
    r, g, b = s_curve(r, 0.05), s_curve(g, 0.05), s_curve(b, 0.05)
    return r, g, b


def documentary(r, g, b):
    """Natural, slightly cooler grade with minimal processing — realistic look."""
    l = luma(r, g, b)
    cool_w = max(0.0, (l - 0.5) / 0.5) * 0.5
    b = b + cool_w * 0.03
    r = r - cool_w * 0.02
    r, g, b = sat_adjust(r, g, b, 0.92)
    r, g, b = s_curve(r, 0.04), s_curve(g, 0.04), s_curve(b, 0.04)
    return r, g, b


def anime(r, g, b):
    """Vibrant, boosted saturation with clean blacks — anime / Disney look."""
    r, g, b = sat_adjust(r, g, b, 1.18)
    l = luma(r, g, b)
    mid_boost = 0.025 * max(0.0, 1.0 - abs(l - 0.5) * 2.0)
    r, g, b = r + mid_boost, g + mid_boost, b + mid_boost
    r, g, b = s_curve(r, 0.05), s_curve(g, 0.05), s_curve(b, 0.05)
    return r, g, b


def filmic(r, g, b):
    """Strong Kodak-inspired film emulation: deep blacks, warm shadows, cool highlights."""
    r, g, b = s_curve(r, 0.12), s_curve(g, 0.12), s_curve(b, 0.12)
    l = luma(r, g, b)
    shadow_w = max(0.0, 1.0 - l / 0.4) ** 2
    highlight_w = max(0.0, (l - 0.6) / 0.4) ** 2
    r = r + shadow_w * 0.03
    g = g + shadow_w * 0.015
    b = b + highlight_w * 0.04
    r, g, b = sat_adjust(r, g, b, 0.82)
    r = r * 0.94 + 0.03
    g = g * 0.94 + 0.03
    b = b * 0.94 + 0.03
    return r, g, b


# ── Writer ─────────────────────────────────────────────────────────────────────


def write_cube(filename, transform, title):
    path = os.path.join(LUT_DIR, filename)
    with open(path, 'w') as f:
        f.write(f'TITLE "{title}"\n')
        f.write(f'LUT_3D_SIZE {N}\n\n')
        for bi in range(N):
            for gi in range(N):
                for ri in range(N):
                    ro, go, bo = transform(ri / (N - 1), gi / (N - 1), bi / (N - 1))
                    f.write(f'{clamp(ro):.6f} {clamp(go):.6f} {clamp(bo):.6f}\n')
    size_kb = os.path.getsize(path) // 1024
    print(f'  ✓  {filename:<22} {size_kb} KB  →  {path}')


# ── Generate ───────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    print(f'Generating LUTs → {LUT_DIR}\n')
    write_cube('cinematic.cube', cinematic, 'Cinematic Grade — Zygomatic')
    write_cube('orange_teal.cube', orange_teal, 'Orange & Teal — Zygomatic')
    write_cube('documentary.cube', documentary, 'Documentary Grade — Zygomatic')
    write_cube('anime.cube', anime, 'Anime Vibrant — Zygomatic')
    write_cube('filmic.cube', filmic, 'Filmic Emulation — Zygomatic')
    print('\nAll LUTs generated.')
