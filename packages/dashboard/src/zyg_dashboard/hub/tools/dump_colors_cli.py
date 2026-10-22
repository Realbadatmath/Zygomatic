# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Command line of `zyg_dashboard.hub.tools.dump_colors`, moved out of the library
module so that library code never prints; `python -m zyg_dashboard.hub.tools.dump_colors`
still reaches it.
"""

import json
import sys
from pathlib import Path

from zyg_dashboard.hub.tools.dump_colors import (
    MANIFEST,
    avg_color,
)


def main():
    data = json.loads(MANIFEST.read_text())
    tex_dir = Path(data['texture_dir']) / 'blocks'
    if not tex_dir.is_dir():
        print(f'[dump_colors] texture dir missing: {tex_dir}', file=sys.stderr)
        sys.exit(1)

    hit = miss = 0
    cache = {}
    for _name, b in data['blocks'].items():
        tex = b.get('tex')
        if not tex:
            b['color'] = None
            miss += 1
            continue
        if tex not in cache:
            cache[tex] = avg_color(tex_dir / f'{tex}.png')
        b['color'] = cache[tex]
        if b['color']:
            hit += 1
        else:
            miss += 1

    data['_colors_by'] = 'hub/tools/dump_colors.py (alpha-weighted mean of prismarine-viewer textures)'
    MANIFEST.write_text(json.dumps(data))
    print(f'[dump_colors] {hit} blocks coloured, {miss} without colour → {MANIFEST}')


if __name__ == '__main__':
    sys.exit(main())
