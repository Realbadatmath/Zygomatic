# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Command line of `zyg_workflows.arch_blend_store`, moved out of the library module so that
library code never prints; `python -m zyg_workflows.arch_blend_store` still reaches it.
"""

import sys

from zyg_workflows.arch_blend_store import stats, sweep


def main() -> int:
    """The command line that used to live under `if __name__ == '__main__'` in arch_blend_store."""
    if '--sweep' in sys.argv:
        n, freed = sweep()
        print('swept %d files, freed %.2f GB' % (n, freed / float(1 << 30)))
    s = stats()
    print(
        'blend dir: %d files, %.2f GB, %d signatures (cap %.0f GB)'
        % (s['files'], s['bytes'] / float(1 << 30), s['signatures'], s['cap_bytes'] / float(1 << 30))
    )
    return 0


if __name__ == '__main__':
    sys.exit(main())
