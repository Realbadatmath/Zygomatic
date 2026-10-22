# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Command line of `zyg_workflows.geom.anthro.pack`, moved out of the library module so that library
code never prints; `python -m zyg_workflows.geom.anthro.pack` still reaches it.
"""

import argparse
import json
import sys

from zyg_workflows.geom.anthro.pack import build, render


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog='python -m zyg_workflows.geom.anthro.pack',
        description='Neutral-facts context pack for subagents. Reads artefacts and source '
        'text; never runs the mesh pipeline; never carries a conclusion.',
    )
    ap.add_argument('--json', action='store_true', help='machine-readable')
    ap.add_argument(
        '--section', choices=('freshness', 'gates', 'facts', 'constants', 'symbols'), help='emit one section only'
    )
    a = ap.parse_args(argv)
    pack = build()
    if a.json:
        print(json.dumps(pack, indent=1, sort_keys=True, default=str))
    else:
        print(render(pack, a.section))
    # exit 1 on stale so a workflow script can refuse to hand out a stale pack
    return 1 if pack['freshness']['stale'] else 0


if __name__ == '__main__':
    sys.exit(main())
