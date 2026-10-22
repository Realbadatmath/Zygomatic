# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Command line of `zyg_workflows.vfx_ingest`, moved out of the library module so that
library code never prints; `python -m zyg_workflows.vfx_ingest` still reaches it.
"""

from __future__ import annotations

import argparse
import sys

from zyg_workflows.vfx_ingest import __doc__ as _LIB_DOC
from zyg_workflows.vfx_ingest import (
    CATEGORIES,
    SIDECAR,
    backfill_image_dims,
    backfill_volume_counts,
    ingest_doe,
    ingest_jangafx,
    ingest_kenney,
    load_sidecar,
    save_sidecar,
)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=_LIB_DOC)
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--fix-counts', action='store_true', help='recount volume packs from their archives, then exit')
    ap.add_argument(
        '--fix-dims', action='store_true', help='measure w/h for sprite rows that are missing them, then exit'
    )
    ap.add_argument('--limit-plates', type=int, default=0, help='transcode at most N plates this run (0 = all)')
    ap.add_argument('--only', choices=['plates', 'sprites', 'volumes'], default=None)
    a = ap.parse_args(argv)

    meta = load_sidecar()
    if a.fix_dims:
        n = backfill_image_dims(meta)
        print(f'[vfx] measured {n} sprite(s)')
        return 0
    if a.fix_counts:
        n = backfill_volume_counts(meta)
        print(f'[vfx] recounted {n} volume pack(s)')
        return 0
    counts = {}
    if a.only in (None, 'volumes'):
        counts['volumes'] = ingest_jangafx(meta, a.dry_run)
    if a.only in (None, 'sprites'):
        counts['sprites'] = ingest_kenney(meta, a.dry_run)
    if a.only in (None, 'plates'):
        counts['plates'] = ingest_doe(meta, a.limit_plates, a.dry_run)
    if not a.dry_run:
        save_sidecar(meta)
    total = {c: sum(1 for r in meta.values() if r.get('cat') == c) for c in CATEGORIES}
    print(f'[vfx] added this run: {counts}')
    print(f'[vfx] library totals: {total}')
    print(f'[vfx] sidecar: {SIDECAR}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
