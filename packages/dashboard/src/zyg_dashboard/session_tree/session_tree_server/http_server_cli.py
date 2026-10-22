# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Command line of `zyg_dashboard.session_tree.session_tree_server.http_server`, moved out
of the library module so that library code never prints;
`python -m zyg_dashboard.session_tree.session_tree_server.http_server` still reaches it.
"""

import os
import sys
import threading

from ._base import BIND_HOST, DATA, LOCK, ThreadingHTTPServer
from .http_server import Handler
from .peers import promote_planned
from .spawner import kick_spawner, spawner_thread
from .storage import CFG, audit, iso
from .usage import _usage, _usage_evt, _usage_load, usage_hold_active, usage_thread


def main():
    with LOCK:
        promote_planned('auto (server start)')
    audit({'cmd': 'server:start', 'ok': True, 'model': 'server', 'error': 'pid %d' % os.getpid()})
    _usage_load()
    if usage_hold_active():
        audit(
            {
                'cmd': 'usage:hold',
                'ok': False,
                'role': 'spawner',
                'model': CFG['executor_model'],
                'error': 'restored after restart: auto-spawn on HOLD until %s — %s'
                % (iso(_usage['hold_until']), _usage.get('hold_reason', '')[:200]),
            }
        )
    threading.Thread(target=spawner_thread, name='spawner', daemon=True).start()
    threading.Thread(target=usage_thread, name='usage-timer', daemon=True).start()
    _usage['want_poll'] = True
    _usage_evt.set()  # first meter read now
    kick_spawner()  # first sweep now, not after spawn_sweep_s
    srv = ThreadingHTTPServer((BIND_HOST, CFG['port']), Handler)
    print(
        f'[session-tree] serving on :{CFG["port"]}  data={DATA}  auto_spawn={CFG.get("auto_spawn")} '
        f'max_executors={CFG["max_executors"]} executor_model={CFG["executor_model"]}',
        flush=True,
    )
    srv.serve_forever()


if __name__ == '__main__':
    sys.exit(main())
