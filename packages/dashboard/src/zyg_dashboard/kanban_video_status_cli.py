# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Command line of `zyg_dashboard.kanban_video_status`, moved out of the library module
so that library code never prints; `python -m zyg_dashboard.kanban_video_status` still
reaches it.
"""

import json
import os
import sys

from zyg_dashboard.kanban_video_status import (
    LOGBOOK_DIR,
    kanban_payload,
    read_run,
)


def main() -> int:
    if len(sys.argv) > 1 and sys.argv[1] == 'all':
        for nm in sorted(os.listdir(LOGBOOK_DIR)):
            if nm.endswith('.jsonl') and nm != 'index.jsonl':
                r = read_run(os.path.join(LOGBOOK_DIR, nm))
                if r:
                    print(
                        f'{r["run_key"]:16s} {r["state"]:8s} cur={str(r["current_stage"]):20s} '
                        f'alive={r["driver_alive"]!s:5s} age={r["last_event_age_s"]:>8.1f}s '
                        f'dry={r["dry_run"]}'
                    )
        sys.exit(0)
    p = kanban_payload(log_fn=lambda m: print(m, file=sys.stderr))
    if not p:
        print('no active video run')
        sys.exit(1)
    print(json.dumps(p, indent=2))
    return 0


if __name__ == '__main__':
    sys.exit(main())
