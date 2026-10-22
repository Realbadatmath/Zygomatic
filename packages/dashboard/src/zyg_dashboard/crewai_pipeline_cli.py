# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Command line of `zyg_dashboard.crewai_pipeline`, moved out of the library module so that
library code never prints; `python -m zyg_dashboard.crewai_pipeline` still reaches it.
"""

import sys


def main() -> int:
    """The command line that used to live under `if __name__ == '__main__'` in crewai_pipeline."""
    # The library module does not import on a bare checkout (it is on tests/import_smoke_skip.txt),
    # so the CLI imports it only when it actually runs — the smoke test imports this module clean.
    from zyg_dashboard.crewai_pipeline import crew

    try:
        result = crew.kickoff()
        print('\nPipeline Result:')
        print(result)
    except Exception as e:
        import traceback

        print(f'\nAn error occurred: {e}')
        traceback.print_exc()
    return 0


if __name__ == '__main__':
    sys.exit(main())
