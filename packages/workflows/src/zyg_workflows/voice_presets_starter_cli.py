# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Command line of `zyg_workflows.voice_presets_starter`, moved out of the library module so that
library code never prints; `python -m zyg_workflows.voice_presets_starter` still reaches it.
"""

from __future__ import annotations

import sys

from zyg_workflows.voice_presets_starter import (
    install,
    install_all,
)


def main() -> int:  # pragma: no cover — operator tool
    import argparse

    ap = argparse.ArgumentParser(description='Install the voice delivery starter tier')
    ap.add_argument('--voice', default='', help='one voice id (default: all)')
    ap.add_argument(
        '--overwrite', action='store_true', help='replace starters that already exist — DISCARDS operator edits'
    )
    a = ap.parse_args()
    res = {a.voice: install(a.voice, a.overwrite)} if a.voice else install_all(a.overwrite)
    total = sum(len(v) for v in res.values())
    for vid, slugs in res.items():
        print(f'{vid:22s} {len(slugs):2d} written' + (f'  ({", ".join(slugs)})' if slugs else '  — already present'))
    print(f'\n{total} preset files written across {len(res)} voices.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
