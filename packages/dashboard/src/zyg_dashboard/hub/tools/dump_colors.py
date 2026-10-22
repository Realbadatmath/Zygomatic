#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Adds an average RGB colour to every block in hub/mc_blocks_1_20_4.json.

Run after tools/dump_blocks.js:

    python3 hub/tools/dump_colors.py

Colours are sampled from prismarine-viewer's per-block PNGs (already on disk),
so the Creator's palette and the isometric preview show what the build will
actually look like instead of a hand-maintained 18-entry guess.

Alpha-weighted mean, fully-transparent pixels ignored.  Blocks whose texture is
missing (or fully transparent, e.g. air) get null and fall back to grey in the UI.
"""

import sys
from pathlib import Path

import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)

HUB = Path(__file__).resolve().parent.parent
MANIFEST = HUB / 'mc_blocks_1_20_4.json'

try:
    from PIL import Image
except ImportError:
    _zyg_log.warning('[dump_colors] Pillow not available — install it or keep null colours')
    sys.exit(1)


def avg_color(png: Path):
    try:
        im = Image.open(png).convert('RGBA')
    except Exception:
        return None
    # Animated textures (e.g. water/fire) are a vertical strip of frames; the
    # first square frame is representative.
    w, h = im.size
    if h > w and w > 0 and h % w == 0:
        im = im.crop((0, 0, w, w))
    px = im.load()
    r = g = b = a_tot = 0
    for y in range(im.size[1]):
        for x in range(im.size[0]):
            pr, pg, pb, pa = px[x, y]
            if pa == 0:
                continue
            r += pr * pa
            g += pg * pa
            b += pb * pa
            a_tot += pa
    if a_tot == 0:
        return None
    return [round(r / a_tot), round(g / a_tot), round(b / a_tot)]


if __name__ == '__main__':  # the CLI lives in dump_colors_cli
    from zyg_dashboard.hub.tools.dump_colors_cli import main as _cli_main

    raise SystemExit(_cli_main())
