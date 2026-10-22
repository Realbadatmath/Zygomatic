# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Command line of `zyg_dashboard.hub.restart_api`, moved out of the library module so that
library code never prints; `python -m zyg_dashboard.hub.restart_api` still reaches it.
"""

import sys
from http.server import HTTPServer

from zyg_dashboard.hub.restart_api import HOST, PORT, Handler


def main() -> int:
    """The server loop that used to live under `if __name__ == '__main__'` in restart_api."""
    server = HTTPServer((HOST, PORT), Handler)
    print(f'Restart API listening on {HOST}:{PORT}')
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print('Stopped.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
