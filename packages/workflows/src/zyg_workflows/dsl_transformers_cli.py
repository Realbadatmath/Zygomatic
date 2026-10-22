# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Command line of `zyg_workflows.dsl_transformers`, moved out of the library module so that
library code never prints; `python -m zyg_workflows.dsl_transformers` still reaches it.
"""

import sys

from zyg_workflows.dsl_transformers import dsl_to_all_configs


def main() -> int:
    """The demo that used to live under `if __name__ == '__main__'` in dsl_transformers."""
    # Demo: transform example scene
    from zyg_workflows.dsl_schema import EXAMPLE_SCENE

    print('=' * 70)
    print('TRANSFORMING SCENE TO TOOL CONFIGS')
    print('=' * 70)

    configs = dsl_to_all_configs(EXAMPLE_SCENE)

    for tool, config in configs.items():
        print(f'\n{tool.upper()} CONFIG:')
        for key, val in config.items():
            print(f'  {key}: {val}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
