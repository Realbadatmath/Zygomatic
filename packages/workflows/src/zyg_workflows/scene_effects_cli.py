# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Command line of `zyg_workflows.scene_effects`, moved out of the library module so that
library code never prints; `python -m zyg_workflows.scene_effects` still reaches it.
"""

import argparse
import json
import sys

from zyg_workflows.scene_effects import (
    MAX_ARCHIVE_BYTES,
    VDB_DIR,
    available_packs,
    ensure_extracted,
)


def main(argv=None):
    ap = argparse.ArgumentParser(prog='scene_effects.py')
    ap.add_argument('--pack', default='', help='archive file name in %s' % VDB_DIR)
    ap.add_argument(
        '--allow-big', action='store_true', help='permit an archive over %.0f GB' % (MAX_ARCHIVE_BYTES / 1e9)
    )
    ap.add_argument('--max-frames', type=int, default=0, help='stride the sequence down to at most this many frames')
    ap.add_argument('--list', action='store_true', help='list the packs and exit')
    ap.add_argument('--quiet', action='store_true')
    args = ap.parse_args(argv)

    if args.list:
        print(json.dumps({'ok': True, 'packs': available_packs(), 'dir': VDB_DIR}))
        return 0
    if not args.pack:
        print(json.dumps({'ok': False, 'error': '--pack is required'}), flush=True)
        return 2
    try:
        seq, n = ensure_extracted(
            args.pack,
            allow_big=args.allow_big,
            max_frames=args.max_frames,
            log=None if args.quiet else (lambda m: print(m, file=sys.stderr, flush=True)),
        )
    except Exception as e:  # noqa: BLE001
        print(json.dumps({'ok': False, 'error': '%s: %s' % (type(e).__name__, e)}), flush=True)
        return 1
    print(json.dumps({'ok': True, 'pack': args.pack, 'seq': seq, 'n': n}), flush=True)
    return 0


if __name__ == '__main__':
    sys.exit(main())
