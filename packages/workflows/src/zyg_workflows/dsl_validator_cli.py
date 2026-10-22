# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Command line of `zyg_workflows.dsl_validator`, moved out of the library module so that
library code never prints; `python -m zyg_workflows.dsl_validator` still reaches it.
"""

import sys

from zyg_workflows.dsl_validator import DSLValidator


def main() -> int:
    """The demo that used to live under `if __name__ == '__main__'` in dsl_validator."""
    # Demo: validate the example scene
    from zyg_workflows.dsl_schema import EXAMPLE_SCENE

    print('=' * 70)
    print('VALIDATING EXAMPLE SCENE')
    print('=' * 70)

    validator = DSLValidator()
    is_valid, errors = validator.validate(EXAMPLE_SCENE)

    if is_valid:
        print(f"✓ Scene '{EXAMPLE_SCENE.metadata.id}' is VALID")
    else:
        print(f"✗ Scene '{EXAMPLE_SCENE.metadata.id}' has errors:")
        for error in errors:
            print(f'  - {error}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
