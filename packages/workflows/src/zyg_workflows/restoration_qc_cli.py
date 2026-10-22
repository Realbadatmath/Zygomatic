# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Command line of `zyg_workflows.restoration_qc`, moved out of the library module so that
library code never prints; `python -m zyg_workflows.restoration_qc` still reaches it.
"""

import os

from zyg_workflows import restoration_qc as _mod
from zyg_workflows.restoration_qc import (
    PASS,
    calibrate,
    compare,
    judge,
    measure_folder,
    measure_pair,
)


def _main():
    import json
    import sys

    argv = sys.argv[1:]
    cmd = argv[0] if argv else 'help'

    def log(m):
        print(m, flush=True)

    if cmd == 'pair' and len(argv) >= 3:
        m = measure_pair(argv[1], argv[2])
        v, why = judge(m)
        print(json.dumps({**m, 'verdict': v, 'reason': why}, indent=2))
        return 0 if v == PASS else 1
    if cmd == 'calibrate' and len(argv) >= 3:
        lim = int(argv[3]) if len(argv) > 3 else None
        print(json.dumps(calibrate(argv[1], argv[2], limit=lim, log_fn=log), indent=2))
        return 0
    if cmd == 'compare' and len(argv) >= 4:
        lim = int(argv[4]) if len(argv) > 4 else None
        print(
            json.dumps(
                compare(
                    argv[1],
                    argv[2],
                    argv[3],
                    limit=lim,
                    label_a=os.path.basename(argv[2].rstrip('/')),
                    label_b=os.path.basename(argv[3].rstrip('/')),
                    log_fn=log,
                ),
                indent=2,
            )
        )
        return 0
    if cmd == 'folder' and len(argv) >= 3:
        lim = int(argv[3]) if len(argv) > 3 else None
        res = measure_folder(argv[1], argv[2], limit=lim, log_fn=log)
        for f in res.get('frames', []):
            v, why = judge(f)
            print(f'{f.get("src"):>14s} -> {v:8s} {why}')
        return 0
    print(_mod.__doc__)
    return 0


if __name__ == '__main__':
    raise SystemExit(_main())
