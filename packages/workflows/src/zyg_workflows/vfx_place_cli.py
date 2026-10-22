# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Command line of `zyg_workflows.vfx_place`, moved out of the library module so that
library code never prints; `python -m zyg_workflows.vfx_place` still reaches it.
"""

from __future__ import annotations

import argparse
import json
import sys

from zyg_workflows.vfx_place import __doc__ as _LIB_DOC
from zyg_workflows.vfx_place import _composite


def main() -> int:
    """The command line that used to live under `if __name__` in vfx_place."""
    ap = argparse.ArgumentParser(description=_LIB_DOC.splitlines()[0])
    ap.add_argument('clip')
    ap.add_argument('out')
    ap.add_argument('--element', default='none')
    ap.add_argument('--anchor', default='0.50,0.85')
    ap.add_argument('--offset', default='0,0,0')
    ap.add_argument('--size', type=float, default=3.0)
    ap.add_argument('--fov', type=float, default=50.0)
    ap.add_argument('--cam-height', type=float, default=1.6)
    ap.add_argument('--pitch', type=float, default=0.0)
    ap.add_argument('--full', action='store_true')
    a = ap.parse_args()
    par = {
        'vfx_element': a.element,
        'vfx_anchor': a.anchor,
        'vfx_offset': a.offset,
        'vfx_size_m': a.size,
        'vfx_cam_fov': a.fov,
        'vfx_cam_height': a.cam_height,
        'vfx_cam_pitch': a.pitch,
    }
    out = _composite(a.clip, par, a.out, not a.full)
    print(json.dumps({k: out[k] for k in ('cam_source', 'seconds', 'width', 'placement')}, indent=1, default=str))
    return 0


if __name__ == '__main__':
    sys.exit(main())
