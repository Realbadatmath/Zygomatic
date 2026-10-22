# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Command line of `zyg_workflows.vfx_preview_check`, moved out of the library module so that
library code never prints; `python -m zyg_workflows.vfx_preview_check` still reaches it.
"""

from __future__ import annotations

import argparse
import json
import sys

from zyg_workflows import vfx_ingest as VI
from zyg_workflows.vfx_preview_check import __doc__ as _LIB_DOC
from zyg_workflows.vfx_preview_check import (
    check,
    vxdur,
)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=_LIB_DOC, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--cat', choices=sorted(VI.CATEGORIES), default=None)
    ap.add_argument('--json', action='store_true')
    ap.add_argument('--quiet', action='store_true', help='print only the failures and the totals')
    a = ap.parse_args(argv)

    out = check(a.cat)
    if a.json:
        print(json.dumps(out, indent=1))
        return 0 if out['fail'] == 0 else 1

    by_cat = {}
    for r in out['rows']:
        by_cat.setdefault(r['cat'], []).append(r)
    for cat, rows in by_cat.items():
        bad = [r for r in rows if not r['ok']]
        print(f'\n{VI.CATEGORIES[cat]["label"]}  ({cat})  {len(rows) - len(bad)}/{len(rows)} play')
        for r in rows:
            if a.quiet and r['ok']:
                continue
            mark = 'ok  ' if r['ok'] else 'FAIL'
            detail = ''
            if r['kind'] in ('video', 'volume') and r.get('frames'):
                detail = (
                    f'{vxdur(r.get("dur")):>7}  {r["lit"]}/{r["sampled"]} sampled '
                    f'frames hold a picture  peak span {r["peak_contrast"]}'
                )
            elif r['kind'] == 'image' and r.get('w'):
                detail = f'{r["w"]}x{r["h"]}  alpha max {r["alpha_max"]}  luma span {r["luma_span"]}'
            print(f'  {mark} {r["name"][:34]:34s} {detail}' + (f'   <- {r["why"]}' if r.get('why') else ''))
    print(f'\nTOTAL {out["pass"]} play, {out["fail"]} do not')
    return 0 if out['fail'] == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
