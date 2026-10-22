# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Command line of `zyg_dashboard.hub.hub_launcher_headless`, moved out of the library module so
that library code never prints; `python -m zyg_dashboard.hub.hub_launcher_headless` still reaches it.
"""

import sys

from zyg_dashboard.hub.hub_launcher_headless import BIND_HOST, hub_launcher


def main() -> int:
    """The command line that used to live under `if __name__ == '__main__'` in hub_launcher_headless."""
    print(f'Hub launcher (headless) listening on {BIND_HOST}:{hub_launcher.PORT}', flush=True)
    hub_launcher.run_server()
    return 0


if __name__ == '__main__':
    sys.exit(main())
