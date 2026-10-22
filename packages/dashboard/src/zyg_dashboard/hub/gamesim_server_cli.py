# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Command line of `zyg_dashboard.hub.gamesim_server`, moved out of the library module so that
library code never prints; `python -m zyg_dashboard.hub.gamesim_server` still reaches it.
"""

import sys

from zyg_dashboard.hub.gamesim_server import BIND_HOST, app, lan_host


def main() -> int:
    """The command line that used to live under `if __name__ == '__main__'` in gamesim_server."""
    print(f'Game Simulator  →  http://{lan_host()}:6500')
    app.run(host=BIND_HOST, port=6500, threaded=True)
    return 0


if __name__ == '__main__':
    sys.exit(main())
