# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Command line of `zyg_workflows.dsl_schema`, moved out of the library module so that
library code never prints; `python -m zyg_workflows.dsl_schema` still reaches it.
"""

import sys

from zyg_workflows.dsl_schema import EXAMPLE_SCENE


def main() -> int:
    """The demo that used to live under `if __name__ == '__main__'` in dsl_schema."""
    # Demo: print example scene
    print('=' * 70)
    print('EXAMPLE SCENE DSL')
    print('=' * 70)
    print(EXAMPLE_SCENE.to_yaml())
    return 0


if __name__ == '__main__':
    sys.exit(main())
