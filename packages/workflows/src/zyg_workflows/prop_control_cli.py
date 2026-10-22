# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Command line of `zyg_workflows.prop_control`, moved out of the library module so
that library code never prints; `python -m zyg_workflows.prop_control` still reaches it.
"""

import sys

from zyg_workflows.prop_control import book_plate_from_meta, composite_into_control


def main() -> int:
    def _lg(m):
        print(m, flush=True)

    if len(sys.argv) < 5:
        print('usage: prop_control.py CONTROL.png SHOT_META.json PLATE_DIR OUT.png [MASK.png]')
        return 2
    ctrl, sm, pdir, outp = sys.argv[1:5]
    mask = sys.argv[5] if len(sys.argv) > 5 else None
    pl = book_plate_from_meta(sm, pdir, log_fn=_lg)
    r = composite_into_control(ctrl, pl, outp, mask_png=mask, log_fn=_lg)
    print('->', r)
    return 0 if r else 1


if __name__ == '__main__':
    sys.exit(main())
