# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Command line of `zyg_zero.nomologin_proxy`, moved out of the library module so that
library code never prints; `python -m zyg_zero.nomologin_proxy` still reaches it.
"""

import argparse
import json
import sys

from zyg_zero.nomologin_proxy import (
    direct_ip,
    probe,
    serve,
)


def main() -> int:
    ap = argparse.ArgumentParser(description='Nomologin per-persona proxy shim')
    ap.add_argument('--listen', type=int, help='loopback port for Chrome to use')
    ap.add_argument('--upstream', help='http(s)://|socks5://[user:pass@]host:port')
    ap.add_argument('--probe', metavar='UPSTREAM', help='report the egress IP and exit')
    ap.add_argument('--direct', action='store_true', help="report this machine's own IP")
    a = ap.parse_args()
    if a.direct:
        print(json.dumps({'direct_ip': direct_ip()}, indent=2))
    elif a.probe:
        print(json.dumps(probe(a.probe), indent=2))
    elif a.listen and a.upstream:
        try:
            serve(a.listen, a.upstream)
        except KeyboardInterrupt:
            print('\n[NOMOLOGIN-PROXY] stopped', flush=True)
    else:
        ap.error('need --listen with --upstream, or --probe, or --direct')
    return 0


if __name__ == '__main__':
    sys.exit(main())
