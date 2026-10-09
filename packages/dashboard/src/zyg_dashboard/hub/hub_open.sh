#!/bin/bash

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

# Opens the Zygomatic Hub in the default browser, starting hub_server first if
# it is not already listening on :7000.
#
# NOTE: bare `python3` on this box resolves to the zygomatics-zero venv, which
# has no Flask — hub_server.py must be launched with /usr/bin/python3 and a PATH
# where /usr/bin precedes the venv (same gotcha as restart_api.py).
set -u

HUB_DIR="$HOME/Zygomatic/hub"
URL=http://localhost:7000/

listening() { exec 3<>/dev/tcp/127.0.0.1/7000 2>/dev/null && exec 3<&- 3>&-; }

if ! listening; then
    cd "$HUB_DIR" || exit 1
    setsid env PATH="/usr/bin:$PATH" /usr/bin/python3 hub_server.py \
        >> "$HUB_DIR/hub_server.log" 2>&1 < /dev/null &
    for _ in $(seq 1 20); do
        listening && break
        sleep 0.5
    done
fi

exec exo-open --launch WebBrowser "$URL"
