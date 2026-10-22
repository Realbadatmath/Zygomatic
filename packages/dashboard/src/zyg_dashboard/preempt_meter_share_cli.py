# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Command line of `zyg_dashboard.preempt_meter_share`, moved out of the library module
so that library code never prints; `python -m zyg_dashboard.preempt_meter_share` still
reaches it.
"""

from __future__ import annotations

import sys
from datetime import datetime

from zyg_dashboard.preempt_meter_share import (
    BANK_PROJECT,
    bank_share,
)


def main() -> int:
    hhmm = sys.argv[sys.argv.index('--since') + 1] if '--since' in sys.argv else '21:00'
    since = datetime.now().replace(hour=int(hhmm[:2]), minute=int(hhmm[3:]), second=0, microsecond=0).timestamp()
    s = bank_share(since)
    print(f'{s["sessions"]} sessions billed to this login since {hhmm}\n')
    print('%-46s %7s %10s %10s %10s' % ('session', 'calls', 'out_tok', '$ output', '$ w/ cache'))
    rows = dict(s['others'])
    rows[BANK_PROJECT] = s['bank']
    for proj, r in sorted(rows.items(), key=lambda kv: -kv[1]['out_value']):
        tag = '  <-- THE BANK' if proj == BANK_PROJECT else ''
        print(
            '%-46s %7d %10d %10.2f %10.2f%s'
            % (
                proj.replace('-home-zygomatic-', '~/')[:46],
                r['calls'],
                r['out_tokens'],
                r['out_value'],
                r['list_value'],
                tag,
            )
        )
    print(
        f'\nbank share of the meter: {100 * (s["share_out"] or 0):.1f} % by output, '
        f'{100 * (s["share_list"] or 0):.1f} % with cache counted — the true weighting is between them'
    )
    return 0


if __name__ == '__main__':
    sys.exit(main())
