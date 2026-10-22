# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Command line of `zyg_zero.zero_public_server`, moved out of the library module so that
library code never prints; `python -m zyg_zero.zero_public_server` still reaches it.
"""

import sys

from zyg_zero.zero_public_server import (
    PORT,
    _recover_stale_jobs,
    _start_mdns,
    _start_public_tunnel,
    app,
    settings,
)

# zero_public_server's only use of these two was the entry point that moved here, so they
# come from their defining module now. It must be imported second: zero_public_server loads
# the .env that zpub_config reads at import time.
from zyg_zero.zpub_config import INTERNAL_TOKEN, MAIN_APP_URL


def main() -> int:
    if not INTERNAL_TOKEN:
        print('[ZeroPub] WARNING: ZERO_PUBLIC_TOKEN is not set — internal API calls will be rejected by the main app.')
    _recover_stale_jobs()
    _start_mdns('ZygomaticsZero')
    _start_public_tunnel()
    print(f'[ZeroPub] Starting on http://{settings.ZYG_BIND_HOST}:{PORT}')
    print(f'[ZeroPub] Also accessible as http://ZygomaticsZero.local:{PORT}')
    print(f'[ZeroPub] Main app: {MAIN_APP_URL}')
    app.run(host=settings.ZYG_BIND_HOST, port=PORT, debug=False, use_reloader=False, threaded=True)
    return 0


if __name__ == '__main__':
    sys.exit(main())
