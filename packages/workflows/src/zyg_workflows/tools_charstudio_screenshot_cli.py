# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Command line of `zyg_workflows.tools_charstudio_screenshot`, moved out of the library module so that
library code never prints; `python -m zyg_workflows.tools_charstudio_screenshot` still reaches it.
"""

import argparse
import json
import sys

from zyg_workflows.tools_charstudio_screenshot import (
    URL,
    shoot,
    shoot_previews,
)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', default='')
    ap.add_argument('--photoreal', action='store_true')
    ap.add_argument('--clay', action='store_true', help='force the photoreal switch off')
    ap.add_argument('--compare', action='store_true')
    ap.add_argument('--frame', default='body', choices=['body', 'head'])
    ap.add_argument('--az', type=float, default=0.0)
    ap.add_argument('--el', type=float, default=0.0)
    ap.add_argument('--body', default='')
    ap.add_argument('--panel', action='store_true', help='open the Photoreal panel and shoot the whole page')
    ap.add_argument(
        '--models', action='store_true', help='open the Models dropdown, hover the first derived model, shoot the page'
    )
    ap.add_argument('--width', type=int, default=1600)
    ap.add_argument('--height', type=int, default=1400)
    ap.add_argument('--url', default=URL)
    ap.add_argument(
        '--previews',
        default='',
        help='write the Models-card previews (head_front/body_front/head_tq PNGs) into this directory and exit',
    )
    a = ap.parse_args(argv)
    if a.previews:
        r = shoot_previews(a.previews, body=a.body, url=a.url)
        print(json.dumps(r, indent=1))
        return 1 if r['errors'] else 0
    r = shoot(
        a.out,
        photoreal=a.photoreal,
        compare=a.compare,
        frame=a.frame,
        az=a.az,
        el=a.el,
        body=a.body,
        width=a.width,
        height=a.height,
        url=a.url,
        panel=a.panel,
        clay=a.clay,
        models=a.models,
    )
    print(json.dumps(r, indent=1))
    return 1 if r['errors'] else 0


if __name__ == '__main__':
    sys.exit(main())
