#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Headless entry point for the hub launcher (port 7777).

hub_launcher.py's __main__ is a desktop app: it opens a browser and then blocks
in tkinter's mainloop. Under systemd there is no DISPLAY, so tk.Tk() raises and
the unit would crash-loop. This wrapper starts the same HTTP handler without the
GUI, so the endpoint is available from boot; the browser/tray parts stay a
desktop-only convenience you can still launch by running hub_launcher.py itself.

Serves exactly what hub_launcher serves — same HubHandler, same port.
"""

import os
import sys

sys.path.insert(0, os.path.expanduser('~/Zygomatic/hub'))

# Read from the environment rather than zyg_workflows.paths: hub_watch launches this
# wrapper with /usr/bin/python3 (see its "python3 gotcha" note), outside the venv, so the
# module must stay stdlib-only. Same variable and same default as paths.BIND_HOST.
BIND_HOST = os.environ.get('BIND_HOST', '127.0.0.1')

import hub_launcher  # noqa: E402  (module-level code runs; the GUI is behind __main__)

if __name__ == '__main__':
    print(f'Hub launcher (headless) listening on {BIND_HOST}:{hub_launcher.PORT}', flush=True)
    hub_launcher.run_server()
