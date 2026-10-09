# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""`python -m zyg_zero.medusa.medusa_server` — the systemd unit's entry point.

Moved verbatim out of medusa_server.py (lines 4358-4360), where the same block
guarded running the file directly.
"""

from zyg_zero import settings

from . import PORT, app

if __name__ == '__main__':
    print(f'Medusa  →  http://{settings.ZYG_LAN_HOST}:{PORT}')
    app.run(host=settings.ZYG_BIND_HOST, port=PORT, threaded=True)
