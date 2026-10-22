# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Command line of `zyg_workflows.motion_edit`, moved out of the library module so
that library code never prints; `python -m zyg_workflows.motion_edit` still reaches it.
"""

import argparse
import json
import sys

from zyg_workflows.motion_edit import _ops_from_args, edit


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog='motion_edit',
        description="Trim / speed / mirror / loop a cmu_mb motion clip into the library's 'edit' bucket.",
    )
    parser.add_argument('source', help='source clip id, e.g. cmu/02_01')
    parser.add_argument('--trim', nargs=2, type=int, metavar=('A', 'B'), help='keep frames A..B (1-based, inclusive)')
    parser.add_argument('--speed', type=float, metavar='F', help='play F times faster (0.5-2 is the sane range)')
    parser.add_argument('--mirror', action='store_true', help='reflect through x = 0, swapping left and right')
    parser.add_argument('--loop', type=int, metavar='N', help='crossfade the last N frames into the first N')
    parser.add_argument(
        '--save', required=True, metavar='edit/SLUG', help='where to register it, e.g. edit/walk_mirror'
    )
    parser.add_argument('--label', help='human label for the library record')
    parser.add_argument('--tags', nargs='*', help="override the parent's tags")
    args = parser.parse_args(argv)

    ops = _ops_from_args(args)
    if not ops:
        parser.error('nothing to do: pass at least one of --trim / --speed / --mirror / --loop')
    record = edit(args.source, ops, args.save, label=args.label, tags=args.tags)
    print(json.dumps(record, indent=2, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())
