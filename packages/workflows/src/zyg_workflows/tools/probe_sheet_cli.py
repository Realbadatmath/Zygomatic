# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Command line of `zyg_workflows.tools.probe_sheet`, moved out of the library module so that
library code never prints; `python -m zyg_workflows.tools.probe_sheet` still reaches it.
"""

import argparse
import os

from PIL import Image, ImageDraw

from zyg_workflows.tools.probe_sheet import frames


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('clip')
    ap.add_argument('draft')
    ap.add_argument('out')
    ap.add_argument('--n', type=int, default=6)
    a = ap.parse_args()
    w, h = 416, 240
    top, idx = frames(a.clip, a.n, w, h)
    bot, _ = frames(a.draft, a.n, w, h)
    W = Image.new('RGB', (w * a.n, h * 2 + 20), 'black')
    d = ImageDraw.Draw(W)
    for i, im in enumerate(top):
        W.paste(im, (i * w, 0))
        d.text((i * w + 4, 2), 'f%d' % (idx[i] + 1), fill='yellow')
    for i, im in enumerate(bot):
        W.paste(im, (i * w, h + 20))
    d.text((4, h + 4), os.path.basename(a.clip), fill='white')
    W.save(a.out)
    print(a.out)


if __name__ == '__main__':
    main()
