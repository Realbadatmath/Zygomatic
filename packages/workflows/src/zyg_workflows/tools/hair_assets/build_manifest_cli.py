# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Command line of `zyg_workflows.tools.hair_assets.build_manifest`, moved out of the library
module so that library code never prints; `python -m
zyg_workflows.tools.hair_assets.build_manifest` still reaches it.

There is nothing to run here: the module is a library of writers that
install_hair_packs.py drives. Saying so on stderr is the whole command line.
"""

import sys


def main() -> int:
    print('build_manifest.py is driven by install_hair_packs.py', file=sys.stderr)
    return 0


if __name__ == '__main__':
    sys.exit(main())
