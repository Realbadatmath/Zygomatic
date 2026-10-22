#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""
Zygomatic hub supervisor.

Guarantees the hub stack is up **whenever the crews GUI on :5000 is up**:
  - hub_server.py            -> :7000   (the LAN bookmark, http://$ZYG_LAN_HOST:7000)
  - restart_api.py           -> :7001   (the hub's start/stop/restart button backend)
  - hub_launcher_headless.py -> :7777   (the launcher HTTP endpoint, no tkinter GUI)

Why this exists: :5000 is the system service `crewai-gui.service`, but the hub
processes historically do NOT autostart, so after any reboot/restart the bookmark
reads "hub offline". This runs as a `--user` systemd unit (linger is on, so it
starts at boot) and keeps the three components alive as long as :5000 is serving.

Semantics (matches the request "always active when port 5000 is active"):
  - :5000 UP   -> ensure all three hub components are running (relaunch any that died).
  - :5000 DOWN -> do nothing (never force-kill the hub over a transient :5000 blip;
                  the guarantee is a lower bound: 5000-up implies hub-up).

The python3 gotcha: bare `python3` on this box is the zygomatics-zero venv, which
has no Flask, and restart_api spawns bare `python3 *_server.py` children. So every
child is launched with /usr/bin/python3 and a PATH where /usr/bin precedes the venv.
"""

import os
import socket
import subprocess

from zyg_workflows.paths import BIND_HOST

import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)

HUB_DIR = os.path.expanduser('~/Zygomatic/hub')
PY = '/usr/bin/python3'
GATE_PORT = 5000  # crewai-gui.service — the "platform is up" signal
CHECK_INTERVAL = 15  # seconds between supervision passes

# name -> (port, script). hub_server + restart_api first, launcher last.
COMPONENTS = [
    ('hub_server', 7000, 'hub_server.py'),
    ('restart_api', 7001, 'restart_api.py'),
    ('hub_launcher', 7777, 'hub_launcher_headless.py'),
]

# Child environment: force /usr/bin ahead of the flask-less venv, and keep the
# user-session vars restart_api needs to route `systemctl --user` restart buttons.
CHILD_ENV = dict(os.environ)
CHILD_ENV['PATH'] = '/usr/bin:/bin:/usr/local/bin:' + CHILD_ENV.get('PATH', '')
CHILD_ENV.setdefault('XDG_RUNTIME_DIR', '/run/user/%d' % os.getuid())
CHILD_ENV.setdefault('DBUS_SESSION_BUS_ADDRESS', 'unix:path=/run/user/%d/bus' % os.getuid())

_procs = {}  # name -> Popen we launched (best-effort; port check is authoritative)


def _port_up(port: int) -> bool:
    """True iff something is accepting TCP on BIND_HOST:port.

    BIND_HOST is the address the supervised services bind (paths.BIND_HOST,
    127.0.0.1 unless an operator opts into LAN), so the probe follows them
    instead of assuming loopback.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(1.0)
        try:
            return s.connect_ex((BIND_HOST, port)) == 0
        except OSError:
            return False


def _ensure(name: str, port: int, script: str) -> None:
    """Launch `script` if its port isn't already being served and we don't have a
    live child for it. Idempotent: never double-spawns (port check is the gate)."""
    if _port_up(port):
        return
    p = _procs.get(name)
    if p is not None and p.poll() is None:
        return  # our child is still coming up
    log_path = os.path.join(HUB_DIR, f'{name}.log')
    log = open(log_path, 'ab', buffering=0)  # noqa: SIM115 — long-lived child log
    _procs[name] = subprocess.Popen(
        [PY, script],
        cwd=HUB_DIR,
        env=CHILD_ENV,
        stdout=log,
        stderr=log,
        stdin=subprocess.DEVNULL,
        start_new_session=True,
    )
    _zyg_log.info(f'[hub-watch] started {name} ({script}) pid={_procs[name].pid} -> :{port}')


if __name__ == '__main__':  # the CLI lives in hub_watch_cli
    from zyg_dashboard.hub.hub_watch_cli import main as _cli_main

    raise SystemExit(_cli_main())
