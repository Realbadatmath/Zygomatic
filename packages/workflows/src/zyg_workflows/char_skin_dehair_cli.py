# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Command line of `zyg_workflows.char_skin_dehair`, moved out of the library module so that
library code never prints; `python -m zyg_workflows.char_skin_dehair` still reaches it.
"""

import argparse
import json
import sys

from zyg_workflows.char_skin_dehair import dehair


def main():
    """The command line that used to live in char_skin_dehair.main()."""
    ap = argparse.ArgumentParser()
    ap.add_argument('--body', default='male_realistic')
    ap.add_argument('--regions', nargs='*', default=['brows', 'beard', 'scalp'])
    ap.add_argument('--radius', type=int, default=9)
    ap.add_argument('--preview', default=None)
    a = ap.parse_args()
    print(json.dumps(dehair(a.body, tuple(a.regions), a.radius, a.preview), indent=1))


if __name__ == '__main__':
    sys.exit(main())
