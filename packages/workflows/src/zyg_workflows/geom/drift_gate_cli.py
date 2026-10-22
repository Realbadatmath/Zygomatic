# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Command line of `zyg_workflows.geom.drift_gate`, moved out of the library module so that
library code never prints; `python -m zyg_workflows.geom.drift_gate` still reaches it.
"""

import argparse
import sys

from zyg_workflows.geom.drift_gate import gate, run


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('char_id')
    ap.add_argument('--k', type=float, default=3.5)
    a = ap.parse_args(argv)
    doc = run(a.char_id, a.k)
    gate.print_report(doc)
    for reg, info in doc['regions'].items():
        out = info.get('outliers') or {}
        line = '  %-11s cells=%-3s median Lab=%s' % (reg, info.get('cells'), info.get('median_lab'))
        if out:
            line += '  OUTLIERS: ' + ', '.join('%s(%s)' % (n, d['axis']) for n, d in list(out.items())[:6])
        print(line)
    return 0 if doc['passed'] else 2


if __name__ == '__main__':
    sys.exit(main())
