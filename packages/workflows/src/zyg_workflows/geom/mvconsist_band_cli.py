# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Command line of `zyg_workflows.geom.mvconsist_band`, moved out of the library module so that
library code never prints; `python -m zyg_workflows.geom.mvconsist_band` still reaches it.
"""

import json
import sys

from zyg_workflows.geom.mvconsist_band import BAND, DERIVATION, REQUIRED_SETTINGS


def main() -> int:
    """The convenience dump that used to live under `if __name__` in mvconsist_band."""
    print(json.dumps({'BAND': BAND, 'REQUIRED_SETTINGS': REQUIRED_SETTINGS, 'DERIVATION': DERIVATION}, indent=2))
    return 0


if __name__ == '__main__':
    sys.exit(main())
