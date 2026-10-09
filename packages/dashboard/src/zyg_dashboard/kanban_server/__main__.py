# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""``python -m zyg_dashboard.kanban_server`` — the original module's __main__ block.

Verbatim lines 3162-3172 of the pre-split ``kanban_server.py``. The ``if`` guard is kept
so the bytes are the original ones; run under ``-m`` it is true, exactly as before.
"""

from zyg_workflows.paths import BIND_HOST

from zyg_dashboard.kanban.common import PORT
from zyg_dashboard.kanban.studios import _agents
from zyg_dashboard.kanban_server import _Handler, _Server

if __name__ == '__main__':
    # Warm the agent sampler at boot rather than on the first page load: its
    # event feed is a HISTORY, and a feed that only starts when someone opens
    # the panel cannot show what ran while nobody was looking.
    try:
        _agents()
    except Exception as _e:  # noqa: BLE001
        print(f'[KANBAN-SERVER] agent sampler did not start — {_e}', flush=True)
    with _Server((BIND_HOST, PORT), _Handler) as httpd:
        print(f'[KANBAN-SERVER] Serving kanban.html + inspection API on {BIND_HOST}:{PORT}', flush=True)
        httpd.serve_forever()
