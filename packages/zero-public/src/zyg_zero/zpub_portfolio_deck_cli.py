# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Command line of `zyg_zero.zpub_portfolio_deck`, moved out of the library module so that
library code never prints; `python -m zyg_zero.zpub_portfolio_deck` still reaches it.
"""

import os
import sys

from zyg_zero.zpub_portfolio_deck import (
    CHAPTERS,
    SLIDES_DIR,
    build_deck,
)


def main() -> int:
    d = build_deck()
    print(f'{d["count"]} slides in {len(d["chapters"])} chapters, {len(d["extra"])} extra frames')
    for ch in d['chapters']:
        print(f'  {ch["title"]}: {len(ch["slides"])}')
    missing = [
        s['file']
        for ch in CHAPTERS
        for s in ch['slides']
        if s.get('file') and not os.path.isfile(os.path.join(SLIDES_DIR, s['file']))
    ]
    if missing:
        print('MISSING:', missing)
    return 0


if __name__ == '__main__':
    sys.exit(main())
