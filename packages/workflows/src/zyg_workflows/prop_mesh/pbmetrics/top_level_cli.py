# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Command line of `zyg_workflows.prop_mesh.pbmetrics.top_level`, moved out of the
library module so that library code never prints;
`python -m zyg_workflows.prop_mesh.pbmetrics.top_level` still reaches it.
"""

import sys

import numpy as np

from zyg_workflows.prop_mesh.pbmetrics import top_level as _mod
from zyg_workflows.prop_mesh.pbmetrics.top_level import (
    TERMS,
    _fmt,
    dump_visuals,
    null_report,
)


def main(argv):
    args = [a for a in argv[1:] if not a.startswith('--')]
    opts = [a for a in argv[1:] if a.startswith('--')]
    if len(args) < 2:
        print(_mod.__doc__)
        print('usage: pbmetrics.py [--dump DIR] <anchor.png> <far.png> [near.png]')
        return 2
    anchor, far = args[0], args[1]
    near = args[2] if len(args) > 2 else None
    near_mask = args[3] if len(args) > 3 else None
    dump = None
    for o in opts:
        if o.startswith('--dump='):
            dump = o.split('=', 1)[1]
    if dump:
        for p, t in [(anchor, 'anchor'), (far, 'null'), (near, 'near')]:
            if p:
                r = dump_visuals(p, dump, tag=t)
                print('dumped %-6s fg=%.3f coh_kept=%.3f -> %s' % (t, r['fg_frac'], r['coh_kept'], r['matte']))
        print()
    rep = null_report(anchor, far, near, near_mask=near_mask)
    print('\nRAW MEASURES')
    keys = list(rep['raw']['anchor'].keys())
    who = [k for k in ('anchor', 'far', 'near') if k in rep['raw']]
    print('%-12s %s' % ('', ' '.join('%9s' % w for w in who)))
    for k in keys:
        print('%-12s %s' % (k, ' '.join('%9.4f' % rep['raw'][w][k] for w in who)))
    cols = ['self', 'mirror', 'far'] + (['near'] if near else [])
    print('\nNULL MODEL — every term, over pairs whose answer is known')
    print('  anchor : %s' % anchor)
    print('  far    : %s   (must be BAD)' % far)
    if near:
        print('  near   : %s   (the thing under test)' % near)
    print()
    print('%-10s %s   %s' % ('term', ' '.join('%8s' % c for c in cols), 'selectivity  verdict'))
    print('-' * 78)
    usable = rep['usable']
    for t in TERMS:
        row = ' '.join(_fmt(rep.get(c, {}).get(t)) for c in cols)
        sd, fd = rep['self'].get(t, float('nan')), rep['far'].get(t, float('nan'))
        sel = (fd / max(sd, fd * 1e-3)) if (np.isfinite(sd) and np.isfinite(fd) and fd > 0) else float('nan')
        mark = 'USABLE' if t in usable else 'REFUSED'
        print(
            '%-10s %s   %8s  %s   %s' % (t, row, ('%.1f' % sel) if np.isfinite(sel) else 'n/a', mark, TERMS[t]['what'])
        )
    print('-' * 78)
    print('%d/%d terms usable (selectivity >= 3.0 against the v1 null)' % (len(usable), len(TERMS)))
    if near:
        print('\nNORMALISED near-distance (0 = anchor, 1 = as wrong as the null):')
        for t, scale in sorted(usable.items()):
            v = rep['near'].get(t, float('nan'))
            if np.isfinite(v):
                print('   %-10s %.3f' % (t, v / scale))
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
