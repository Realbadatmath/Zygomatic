# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Command line of `zyg_workflows.tools.measure_cinematic_clap`, moved out of the library module
so that library code never prints; `python -m zyg_workflows.tools.measure_cinematic_clap` still
reaches it.
"""

import argparse
import sys

from zyg_workflows.tools import measure_cinematic_clap as _mod
from zyg_workflows.tools.measure_cinematic_clap import (
    NEG_CURRENT,
    NEG_VARIANT,
    OUT_ROOT,
    phase_baseline,
    phase_cands,
    phase_probe,
    phase_regress,
    renders,
)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--phase', choices=('baseline', 'cands', 'regress', 'probe'), required=True)
    ap.add_argument('--neg', choices=('current', 'variant'), default='current')
    ap.add_argument('--sets', default='', help="comma list like 'suspense:S1,mystery:M2' (cands only)")
    ap.add_argument('--repeats', type=int, default=3, help='qc_clap calls per (file, caption set) — CLAP is noisy')
    a = ap.parse_args()

    # `score()` reads REPEATS off the library module, so the old `global REPEATS` of
    # this function is now a write THROUGH the module object.
    _mod.REPEATS = max(1, a.repeats)
    negatives = NEG_CURRENT if a.neg == 'current' else NEG_VARIANT
    reg = renders()
    if not reg:
        print(f'no renders under {OUT_ROOT}')
        return 1
    only = {s.strip() for s in a.sets.split(',') if s.strip()}

    if a.phase == 'baseline':
        phase_baseline(reg, negatives, a.neg)
    elif a.phase == 'cands':
        phase_cands(reg, negatives, a.neg, only)
    elif a.phase == 'probe':
        phase_probe(reg, negatives, a.neg, sorted(only) or ['suspense', 'mystery', 'triumph'])
    else:
        phase_regress(reg, negatives, a.neg)
    return 0


if __name__ == '__main__':
    sys.exit(main())
