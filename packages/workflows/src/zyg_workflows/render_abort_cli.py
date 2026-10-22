# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Command line of `zyg_workflows.render_abort`, moved out of the library module so that
library code never prints; `python -m zyg_workflows.render_abort` still reaches it.
"""

import os
import sys
import time

from zyg_workflows.render_abort import RenderAbortWatchdog


def main() -> int:
    """The self-test that used to live under `if __name__ == '__main__'` in render_abort."""

    def _lg(m):
        print(m, flush=True)

    if len(sys.argv) < 2:
        print('usage: render_abort.py RUN_DIR [--seconds N]   (self-test, no ComfyUI needed)')
        return 2
    rd = sys.argv[1]
    os.makedirs(rd, exist_ok=True)
    secs = 6.0
    if '--seconds' in sys.argv:
        secs = float(sys.argv[sys.argv.index('--seconds') + 1])
    wd = RenderAbortWatchdog(rd, log_fn=_lg, poll_s=1.0).start()
    _lg(f'self-test: touch {os.path.join(rd, "ABORT")} within {secs:.0f}s')
    t0 = time.time()
    while time.time() - t0 < secs and not wd.fired:
        time.sleep(0.5)
    wd.stop()
    _lg(f'fired={wd.fired} reason={wd.reason}')
    return 0 if wd.fired else 1


if __name__ == '__main__':
    sys.exit(main())
