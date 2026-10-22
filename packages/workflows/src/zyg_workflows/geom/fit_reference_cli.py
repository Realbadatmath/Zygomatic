# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Command line of `zyg_workflows.geom.fit_reference`, moved out of the library module so that
library code never prints; `python -m zyg_workflows.geom.fit_reference` still reaches it.
"""

import argparse
import json
import sys

from zyg_workflows.geom.fit_reference import fit


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--sex', required=True, choices=('male', 'female'))
    ap.add_argument('--ref', required=True)
    ap.add_argument('--iters', type=int, default=400)
    ap.add_argument('--out', default='')
    a = ap.parse_args()
    rec = fit(a.sex, a.ref, a.iters)
    out = a.out or ('fit_%s.json' % a.sex)
    with open(out, 'w') as f:
        json.dump(rec, f, indent=2)
    print('WROTE %s' % out)
    print(json.dumps({k: rec[k] for k in ('phenotype', 'local_changes')}, indent=2))


if __name__ == '__main__':
    sys.exit(main())
