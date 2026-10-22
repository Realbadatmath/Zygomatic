# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Command line of `zyg_dashboard.hub.hub_server`, moved out of the library module so that
library code never prints; `python -m zyg_dashboard.hub.hub_server` still reaches it.
"""

import sys

from zyg_workflows.paths import BIND_HOST

from zyg_dashboard.hub.hub_server import app, lan_host


def main() -> int:
    """The command line that used to live under `if __name__ == '__main__'` in hub_server."""
    print(f'Zygomatic Hub  →  http://{lan_host()}:7000')
    app.run(host=BIND_HOST, port=7000, threaded=True)
    return 0


if __name__ == '__main__':
    sys.exit(main())
