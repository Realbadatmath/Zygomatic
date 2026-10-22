# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Command line of `zyg_dashboard.hub.tests.test_compiler`, moved out of the library module so that
library code never prints; `python -m zyg_dashboard.hub.tests.test_compiler` still reaches it.
"""

import sys

from zyg_dashboard.hub.tests.test_compiler import (
    FAILURES,
    PASSES,
    load_builtins,
    test_builtins_certify,
    test_face_centers,
    test_falsification,
    test_floating_block,
    test_lint_catches_corruption,
    test_manifest,
    test_model_constants,
    test_order_is_valid,
    test_scaffold_repairs_column,
    test_standing_in,
    test_watchtower_ablation_is_buildable,
)


def main():
    """The ground-truth suite runner that used to live in test_compiler.main()."""
    print('=' * 72)
    print('buildability compiler — ground truth suite')
    print('=' * 72)
    test_model_constants()
    test_manifest()
    test_face_centers()
    test_standing_in()
    test_lint_catches_corruption()
    test_floating_block()
    test_falsification()
    test_scaffold_repairs_column()
    schematics = load_builtins()
    test_builtins_certify(schematics)
    test_order_is_valid(schematics)
    test_watchtower_ablation_is_buildable(schematics)

    print('\n' + '=' * 72)
    print(f'{len(PASSES)} passed, {len(FAILURES)} failed')
    for name, detail in FAILURES:
        print(f'  FAILED: {name}  {detail}')
    print('=' * 72)
    return 1 if FAILURES else 0


if __name__ == '__main__':
    sys.exit(main())
