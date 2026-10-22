# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Command line of `zyg_workflows.char_cycles_render`, moved out of the library module so that
library code never prints; `python -m zyg_workflows.char_cycles_render` still reaches it.
"""

import argparse
import json
import os
import sys

from zyg_workflows import char_cycles_render as _mod
from zyg_workflows.char_cycles_render import (
    BODIES,
    CHAR_BLEND,
    DEFAULT_HDRI,
    OUT_RENDER,
    bench,
    render,
)


def main():
    """The command line that used to live in char_cycles_render.main()."""
    ap = argparse.ArgumentParser(description=_mod.__doc__.splitlines()[0])
    ap.add_argument('--character', default='einar', choices=sorted(CHAR_BLEND))
    ap.add_argument('--parts', nargs='*', default=['hair', 'beard', 'brows'])
    ap.add_argument('--body', default='male_realistic', choices=sorted(BODIES))
    ap.add_argument('--colour', default='dark brown')
    ap.add_argument('--clay', action='store_true', help='no baked skin')
    ap.add_argument('--frame', default='head', choices=['head', 'bust', 'body'])
    ap.add_argument('--az', type=float, default=0.0)
    ap.add_argument('--el', type=float, default=0.0)
    ap.add_argument(
        '--lens', type=float, default=None, help='default depends on the framing: 85 mm head/bust, 50 mm body'
    )
    ap.add_argument('--size', nargs=2, type=int, default=[1080, 1350])
    ap.add_argument('--samples', type=int, default=256)
    ap.add_argument('--density', type=float, default=8.0)
    ap.add_argument('--hdri', default=DEFAULT_HDRI)
    ap.add_argument('--device', default='OPTIX')
    ap.add_argument('--transparent', action='store_true')
    ap.add_argument('--force-strands', action='store_true')
    ap.add_argument('--bench', action='store_true')
    ap.add_argument('--out', default=None)
    a = ap.parse_args()
    if a.bench:
        bench(a.character)
        return
    out = a.out or os.path.join(OUT_RENDER, f'{a.character}_{a.frame}.png')
    rep = render(
        out,
        character=a.character,
        parts=tuple(a.parts),
        body=a.body,
        colour=a.colour,
        photoreal=not a.clay,
        frame=a.frame,
        az=a.az,
        el=a.el,
        lens=a.lens,
        size=tuple(a.size),
        samples=a.samples,
        density=a.density,
        hdri=a.hdri,
        device=a.device,
        transparent=a.transparent,
        force_strands=a.force_strands,
    )
    print(
        json.dumps({k: rep[k] for k in ('out', 'device', 'size', 'samples', 't_hair', 't_render', 't_total')}, indent=1)
    )


if __name__ == '__main__':
    sys.exit(main())
