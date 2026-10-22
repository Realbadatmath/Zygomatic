# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Command line of `zyg_workflows.skill_integrity_monitor`, moved out of the library module so that
library code never prints; `python -m zyg_workflows.skill_integrity_monitor` still reaches it.
"""

import argparse
import os
import sys

from zyg_workflows.skill_integrity_monitor import (
    _save_baseline,
    build_baseline,
    check_integrity,
)


def main():
    parser = argparse.ArgumentParser(description='File integrity monitor')
    parser.add_argument('--reset', action='store_true', help='Rebuild baseline from current file state')
    args = parser.parse_args()

    if args.reset:
        baseline = build_baseline()
        _save_baseline(baseline)
        print(f'[INTEGRITY] Baseline reset — {len(baseline)} files hashed.', flush=True)
        for path, info in baseline.items():
            print(f'  {info["sha256"][:16]}…  {os.path.basename(path)}', flush=True)
        sys.exit(0)

    clean = check_integrity()
    sys.exit(0 if clean else 1)


if __name__ == '__main__':
    main()
