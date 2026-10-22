# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Command line of `zyg_workflows.tools.measure_kidsmusic_takes`, moved out of the library module
so that library code never prints; `python -m zyg_workflows.tools.measure_kidsmusic_takes` still
reaches it.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

from zyg_workflows.tools import measure_kidsmusic_takes as _mod
from zyg_workflows.tools.measure_kidsmusic_takes import aggregate, measure_files


def main(argv=None):
    ap = argparse.ArgumentParser(description=_mod.__doc__.splitlines()[0])
    ap.add_argument('files', nargs='+')
    ap.add_argument('--out', default='')
    ap.add_argument('--old-f0', default='')
    ap.add_argument('--quiet', action='store_true')
    a = ap.parse_args(argv)

    old = json.load(open(a.old_f0)) if a.old_f0 else {}
    log = (lambda m: None) if a.quiet else (lambda m: print(m, file=sys.stderr))
    rows = measure_files(a.files, old_f0=old, log=log)
    doc = {'rows': rows, 'aggregate': aggregate(rows)}
    if a.out:
        os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
        with open(a.out, 'w') as fh:
            json.dump(doc, fh, indent=1)
    else:
        json.dump(doc, sys.stdout, indent=1)
        print()
    return 0 if all(r['ok'] for r in rows) else 1


if __name__ == '__main__':
    sys.exit(main())
