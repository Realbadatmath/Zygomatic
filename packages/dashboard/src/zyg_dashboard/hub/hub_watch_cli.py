# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Command line of `zyg_dashboard.hub.hub_watch`, moved out of the library module so that
library code never prints; `python -m zyg_dashboard.hub.hub_watch` still reaches it.
"""

import time

from zyg_dashboard.hub.hub_watch import CHECK_INTERVAL, COMPONENTS, GATE_PORT, _ensure, _port_up


def main() -> None:
    """The supervision loop that used to live in hub_watch.main()."""
    print(f'[hub-watch] supervisor up; gating hub (7000/7001/7777) on :{GATE_PORT}', flush=True)
    gate_was_up = None
    while True:
        try:
            gate_up = _port_up(GATE_PORT)
            if gate_up != gate_was_up:
                print(f'[hub-watch] :{GATE_PORT} is {"UP" if gate_up else "DOWN"}', flush=True)
                gate_was_up = gate_up
            if gate_up:
                for name, port, script in COMPONENTS:
                    _ensure(name, port, script)
        except Exception as exc:  # never let a transient error kill the supervisor
            print(f'[hub-watch] error: {exc}', flush=True)
        time.sleep(CHECK_INTERVAL)


if __name__ == '__main__':
    raise SystemExit(main())
