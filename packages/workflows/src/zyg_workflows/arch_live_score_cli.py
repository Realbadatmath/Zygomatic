# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Command line of `zyg_workflows.arch_live_score`, moved out of the library module so that
library code never prints; `python -m zyg_workflows.arch_live_score` still reaches it.

`--help` still shows the LIBRARY module's docstring (`_mod.__doc__`), which is where the
scorecard and its exit-code contract are documented.
"""

from __future__ import annotations

import argparse
import os
import sys

import zyg_workflows.arch_live_score as _mod
from zyg_workflows.arch_live_score import (
    LEDGER_DIR,
    RED,
    load_ledger,
    newest_ledger,
    pick_end_event,
    score,
)


def main(argv=None):
    ap = argparse.ArgumentParser(description=_mod.__doc__.split('\n')[0])
    ap.add_argument('--file', help='ledger jsonl (default: the newest under %s)' % LEDGER_DIR)
    ap.add_argument('--job', help='job id prefix (default: the last "end" event)')
    ap.add_argument('--expect-red', action='store_true', help='invert the exit code: 0 when at least one signal is RED')
    args = ap.parse_args(argv)

    path = args.file or newest_ledger()
    if not os.path.exists(path):
        sys.exit('no such ledger: %s' % path)
    end = pick_end_event(load_ledger(path), args.job)
    rows = score(end)

    print('scorecard — job %s   %s' % (end.get('id'), path))
    print('  %s' % (str(end.get('summary') or '(no summary)').split('\n')[0][:110]))
    print('-' * 96)
    for state, label, detail in rows:
        print('%-7s %-28s %s' % (state, label, detail))
    print('-' * 96)

    reds = [label for state, label, _ in rows if state == RED]
    if reds:
        print('%d RED: %s' % (len(reds), ', '.join(reds)))
    else:
        print('no RED signals')

    bad = bool(reds)
    if args.expect_red:
        return 0 if bad else 1
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
