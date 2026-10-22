# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Command line of `zyg_zero.nomologin_board`, moved out of the library module so that
library code never prints; `python -m zyg_zero.nomologin_board` still reaches it.
"""

import argparse
import sys

from zyg_zero import nomologin_board as _mod
from zyg_zero.nomologin_board import (
    ASSIST_ERROR,
    PORT,
    Handler,
    Server,
    na,
    nl,
)


def main() -> int:
    ap = argparse.ArgumentParser(description='Nomologin board')
    ap.add_argument('--port', type=int, default=PORT)
    args = ap.parse_args()
    port = args.port
    # `--port` used to rebind the library module's own globals; Handler reads
    # `_ALLOWED_HOSTS` at request time, so set them on the module, not here.
    _mod.PORT = port
    _mod._ALLOWED_HOSTS = {f'127.0.0.1:{port}', f'localhost:{port}', f'[::1]:{port}'}
    nl.init()
    if na is not None:
        # Explicit, never at import: this rewrites the ledger, folding conversations a
        # restart killed. Doing it at import would make any smoke test destructive.
        closed = na.boot().get('closed')
        if closed:
            print(f'[NOMOLOGIN-BOARD] closed {closed} assistant job(s) a restart killed', flush=True)
    elif ASSIST_ERROR:
        print(f'[NOMOLOGIN-BOARD] assistant disabled: {ASSIST_ERROR}', flush=True)
    with Server(('127.0.0.1', port), Handler) as httpd:
        print(f'[NOMOLOGIN-BOARD] http://127.0.0.1:{port}  root={nl.ROOT}', flush=True)
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print('\n[NOMOLOGIN-BOARD] stopped', flush=True)
    return 0


if __name__ == '__main__':
    sys.exit(main())
