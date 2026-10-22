# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Command line of `zyg_zero.nomologin_sites`, moved out of the library module so that
library code never prints; `python -m zyg_zero.nomologin_sites` still reaches it.
"""

import sys

from zyg_zero.nomologin_sites import (
    CATALOGUE,
    GROUPS,
    SITES,
)


def main() -> int:
    import collections

    by_policy = collections.Counter(s['policy'] for s in SITES.values())
    print(f'{len(SITES)} sites in {len(GROUPS)} groups')
    for g in GROUPS:
        print(f'  {len(CATALOGUE[g]):>3}  {g}')
    print('policy:', dict(by_policy))
    return 0


if __name__ == '__main__':
    sys.exit(main())
