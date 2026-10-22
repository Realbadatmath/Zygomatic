# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Command line of `zyg_workflows.vfx_plate_preview`, moved out of the library module so that
library code never prints; `python -m zyg_workflows.vfx_plate_preview` still reaches it.
"""

from __future__ import annotations

import argparse
import sys

from zyg_workflows.vfx_plate_preview import __doc__ as _LIB_DOC
from zyg_workflows.vfx_plate_preview import build


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=_LIB_DOC.splitlines()[0])
    ap.add_argument('--only', help='one working-copy filename')
    ap.add_argument('--force', action='store_true', help='rebuild even if one exists')
    ap.add_argument(
        '--at',
        type=float,
        help='take the cut from this second instead of picking one; '
        'recorded as a manual pick and never re-derived after',
    )
    a = ap.parse_args(argv)
    if a.at is not None and not a.only:
        ap.error("--at sets one plate's window, so it needs --only")
    # --at is an instruction to change the window, so it implies a rebuild.
    n = build(only=a.only, force=a.force or a.at is not None, at=a.at)
    print(f'[plate-pv] {n} preview(s) built')
    return 0


if __name__ == '__main__':
    sys.exit(main())
