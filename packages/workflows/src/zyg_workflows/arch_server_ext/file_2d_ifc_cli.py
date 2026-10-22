# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Command line of `zyg_workflows.arch_server_ext.file_2d_ifc`, moved out of the library
module so that library code never prints; `python -m zyg_workflows.arch_server_ext.file_2d_ifc`
(and `blender -b --python arch_server_ext/file_2d_ifc.py`, through that module's connector)
still reaches it.
"""

from __future__ import annotations

import argparse
import json
import sys
import traceback

from zyg_workflows.arch_server_ext.file_2d_ifc import run


def main() -> None:
    argv = sys.argv[sys.argv.index('--') + 1 :] if '--' in sys.argv else []
    ap = argparse.ArgumentParser(prog='file_2d_ifc.py')
    ap.add_argument('--in', dest='inp', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--schema', default='IFC4')
    ap.add_argument('--name', default='Drawing')
    args = ap.parse_args(argv)
    try:
        out = run(args)
    except Exception as e:  # noqa: BLE001
        traceback.print_exc()
        print('IFCOUT ' + json.dumps({'ok': False, 'error': '%s: %s' % (type(e).__name__, e)}), flush=True)
        sys.exit(1)
    print('IFCOUT ' + json.dumps(out), flush=True)


if __name__ == '__main__':
    main()
