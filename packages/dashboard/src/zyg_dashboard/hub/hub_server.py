#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""
Zygomatic Hub — Linux web server, port 7000
Serves the hub HTML so any device on the local network can access it.
Bookmark:  http://$ZYG_LAN_HOST:7000

The listening address is ``zyg_workflows.paths.BIND_HOST`` and defaults to
``127.0.0.1``: this server is loopback-only unless LAN exposure is asked for
explicitly by setting ``BIND_HOST=0.0.0.0`` in the environment.
"""

import os
import re
from pathlib import Path
from flask import Flask, Response, send_file

app = Flask(__name__)

HUB_FILE = Path(__file__).parent / 'hub_launcher.py'

# The card URLs in hub_launcher.HUB_HTML carry this placeholder; see
# docs/configuration.md. Read per request so a changed env needs no restart.
LAN_HOST_PLACEHOLDER = '__ZYG_LAN_HOST__'


def lan_host() -> str:
    return os.environ.get('ZYG_LAN_HOST', '127.0.0.1')


def get_html() -> str:
    src = HUB_FILE.read_text(encoding='utf-8')
    m = re.search(r'HUB_HTML = """(.*?)"""', src, re.DOTALL)
    if not m:
        return '<h1>Error: could not parse hub HTML from hub_launcher.py</h1>'
    return m.group(1).replace(LAN_HOST_PLACEHOLDER, lan_host())


@app.route('/favicon.ico')
def favicon():
    # 2026-08-22: this file used to be a 32x32 PNG wearing a .ico extension, which
    # is why the mimetype said image/png. It is now a genuine multi-resolution ICO
    # (16-64), so the mimetype has to match or Chrome refuses to paint the tab.
    return send_file(Path(__file__).parent / 'favicon.ico', mimetype='image/x-icon')


@app.route('/')
def index():
    return Response(get_html(), content_type='text/html; charset=utf-8', headers={'Cache-Control': 'no-store'})


if __name__ == '__main__':  # the CLI lives in hub_server_cli
    from zyg_dashboard.hub.hub_server_cli import main as _cli_main

    raise SystemExit(_cli_main())
