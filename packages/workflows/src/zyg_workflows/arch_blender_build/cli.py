# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The `--in/--out/--glb` command line the old module's main() carried.

Moved verbatim out of the old single-file arch_blender_build.py (lines 1115-1132).
"""

import argparse
import json
import sys
import traceback

# Bound by assignment rather than `from … import` on purpose: CPython emits the
# LOAD_METHOD form for `X.method()` only when X was not bound by an import
# statement, and the moved lines below were compiled against a plain global.
from zyg_workflows.arch_blender_build import build_scene as _build_scene

build = _build_scene.build


def main():
    argv = sys.argv[sys.argv.index('--') + 1 :] if '--' in sys.argv else []
    ap = argparse.ArgumentParser(prog='arch_blender_build.py')
    ap.add_argument('--in', dest='inp', required=True, help='Architecture Studio drawing JSON')
    ap.add_argument('--out', required=True, help='output .blend')
    ap.add_argument('--glb', default=None, help='optional .glb export')
    args = ap.parse_args(argv)
    try:
        with open(args.inp, 'r', encoding='utf-8') as fh:
            drawing = json.load(fh)
        if not isinstance(drawing, dict):
            raise ValueError('drawing JSON must be an object')
        result = build(drawing, args.out, args.glb)
    except Exception as e:  # noqa: BLE001 - one JSON line is the contract
        traceback.print_exc()
        print(json.dumps({'ok': False, 'error': f'{type(e).__name__}: {e}'}), flush=True)
        sys.exit(1)
    print(json.dumps(result), flush=True)
