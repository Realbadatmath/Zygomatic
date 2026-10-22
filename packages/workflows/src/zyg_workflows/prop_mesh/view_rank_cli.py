# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Command line of `zyg_workflows.prop_mesh.view_rank`, moved out of the library module so
that library code never prints; `python -m zyg_workflows.prop_mesh.view_rank` still reaches it.
"""

import argparse
import json
import sys

from zyg_workflows.prop_mesh import view_rank as _mod
from zyg_workflows.prop_mesh.view_rank import run


def _main():
    ap = argparse.ArgumentParser(description=_mod.__doc__.split('\n')[0])
    ap.add_argument('--asset', required=True)
    ap.add_argument('--view', default='top_down')
    ap.add_argument('--ref', dest='ref_view', default='front_full')
    ap.add_argument('--seed', type=int, default=7)
    ap.add_argument('--steps', type=int, default=24)
    ap.add_argument('--size', type=int, default=1024)
    ap.add_argument('--prompt', default=None)
    a = ap.parse_args()
    r = run(a.asset, a.view, a.ref_view, seed=a.seed, steps=a.steps, size=a.size, prompt=a.prompt)
    print(json.dumps({k: v for k, v in r.items() if k != 'arms'}, indent=2))
    return 0


if __name__ == '__main__':
    sys.exit(_main())
