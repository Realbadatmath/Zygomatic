# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Command line of `zyg_workflows.voice_harvest_kyutai`, moved out of the library module so that
library code never prints; `python -m zyg_workflows.voice_harvest_kyutai` still reaches it.
"""

from __future__ import annotations

import sys

from zyg_workflows.voice_harvest_kyutai import (
    MANIFEST,
    REPO,
    SUBDIR,
    build,
    download,
)


def main() -> int:  # pragma: no cover — operator tool
    import argparse

    ap = argparse.ArgumentParser(description='Harvest the Kyutai CC0 voice donations')
    ap.add_argument('--skip-download', action='store_true')
    a = ap.parse_args()
    if not a.skip_download:
        print(f'downloading {REPO}/{SUBDIR} wavs (skipping .safetensors)…')
        print(f'  {download()} donations on disk')
    s = build()
    print(
        f'\nkept {s["kept"]} ({s["male"]} male / {s["female"]} female; '
        f"{s['low_conf']} flagged 'metrics unreliable', "
        f'{s["sex_guessed"]} with sex inferred rather than read)'
    )
    if s['skipped']:
        print(f'skipped {len(s["skipped"])}:')
        for i, w in s['skipped'][:20]:
            print(f'  {i}  {w}')
    print(f'\nmanifest: {MANIFEST}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
