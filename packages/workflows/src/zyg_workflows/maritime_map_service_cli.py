# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Command line of `zyg_workflows.maritime_map_service`, moved out of the library module so that
library code never prints; `python -m zyg_workflows.maritime_map_service` still reaches it.
"""

import json
import sys

from zyg_workflows.maritime_map_service import (
    WEST_AFRICA_RUN,
    build_chart,
    check_route,
    route_path,
)


def main() -> int:
    """What used to run under `if __name__` in maritime_map_service."""
    c = build_chart(force='--force' in sys.argv)
    print(json.dumps(c.as_dict(), indent=1))
    p, m = route_path(WEST_AFRICA_RUN, c)
    print(f'route: {len(p)} samples, {len(m)} ports')
    for mk in m:
        print(f'  {mk["name"]:<10} frac {mk["frac"]:.3f}  px {mk["xy"][0]:.0f},{mk["xy"][1]:.0f}')
    check_route(p, c, marks=m)
    return 0


if __name__ == '__main__':
    sys.exit(main())
