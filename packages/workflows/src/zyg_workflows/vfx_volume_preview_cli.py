# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Command line of `zyg_workflows.vfx_volume_preview`, moved out of the library module so that
library code never prints; `python -m zyg_workflows.vfx_volume_preview` still reaches it.
"""

from __future__ import annotations

import argparse
import sys

from zyg_workflows import vfx_ingest as VI
from zyg_workflows.vfx_volume_preview import __doc__ as _LIB_DOC
from zyg_workflows.vfx_volume_preview import (
    build_all,
    reconcile,
    volume_records,
)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=_LIB_DOC, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--all', action='store_true', help='every volume pack')
    ap.add_argument('--pack', default=None, help='one archive name or slug')
    ap.add_argument('--force', action='store_true', help='rebuild existing previews')
    ap.add_argument('--list', action='store_true', help='show state, build nothing')
    ap.add_argument(
        '--reconcile',
        action='store_true',
        help='re-attach preview clips already on disk that the sidecar has stopped naming; renders nothing',
    )
    a = ap.parse_args(argv)

    if a.list:
        meta = VI.load_sidecar()
        for _, r in volume_records(meta):
            pv = r.get('preview') or ''
            state = (
                f'{pv}  [{r.get("preview_src", "?")}]'
                if pv
                else ('FAILED: ' + r.get('preview_error', '') if r.get('preview_error') else '— none —')
            )
            print(f'{(r.get("name") or r.get("file")):28s} {r.get("frames", 0):>4}f  {state}')
        return 0
    if a.reconcile:
        return 0 if reconcile()['fixed'] >= 0 else 1
    if not (a.all or a.pack):
        ap.error('give --all, --pack <archive> or --reconcile')
    out = build_all(only=a.pack, force=a.force)
    return 0 if out['failed'] == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
